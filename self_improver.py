#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA Self-Improving 错题本机制
===============================
借鉴 OpenClaw Self-Improving Agent 的核心思路：
  - 失败时将 (问题, 错误代码, 错误信息, 修复方案) 写入 .learnings/ERRORS.md
  - 成功时将经验写入 .learnings/LEARNINGS.md
  - AgentFactory 在构建 System Prompt 时自动读取相关记录注入"经验区"

目录结构:
  .learnings/
    ERRORS.md    ← 错误记录本（失败案例 + 修复建议）
    LEARNINGS.md ← 成功经验本（成功案例 + 解决方案）

使用示例:
  from self_improver import learning_recorder, get_learnings_context

  # 记录错误（在 error_handler_node 最终失败时调用）
  learning_recorder.record_error(
      query="查询茅台分红",
      error_code="df = pro.dividend(ts_code='600519.SH')",
      error_message="KeyError: 'dv_ratio'",
      error_type="code_error"
  )

  # 记录成功（在 Reviewer 通过后调用）
  learning_recorder.record_success(
      query="查询茅台分红",
      solution="使用 dv_ttm 字段替代 dv_ratio，并除以100转换百分比"
  )

  # 获取与当前查询相关的历史经验（注入 System Prompt）
  context = get_learnings_context("茅台分红")
"""

import datetime
import re
from pathlib import Path
from typing import Optional, List

# ===========================================================================
# 文件路径配置
# ===========================================================================
LEARNINGS_DIR = Path(".learnings")
ERRORS_FILE = LEARNINGS_DIR / "ERRORS.md"
LEARNINGS_FILE = LEARNINGS_DIR / "LEARNINGS.md"

MAX_ENTRIES = 100      # 每个文件最多保留100条记录（防止无限增长）
MAX_INJECT_CHARS = 1500  # 注入 System Prompt 的最大字符数


# ===========================================================================
# LearningRecorder - 错题本核心类
# ===========================================================================

class LearningRecorder:
    """
    Self-Improving 错题本记录器

    核心机制（借鉴 OpenClaw pskoett/self-improving-agent）:
    1. 每次任务最终失败 → 记录到 ERRORS.md
    2. 每次任务成功 → 记录到 LEARNINGS.md
    3. 下次执行相似任务时，从两个文件中提取相关经验注入 System Prompt
    4. 随着运行，Agent 会"越来越聪明"，避免重复犯同类错误
    """

    def __init__(self):
        self._ensure_files()

    def _ensure_files(self) -> None:
        """确保 .learnings/ 目录和文件存在"""
        try:
            LEARNINGS_DIR.mkdir(exist_ok=True)

            if not ERRORS_FILE.exists():
                ERRORS_FILE.write_text(
                    "# ASA 错误记录本（Self-Improving）\n\n"
                    "> 系统自动维护，记录失败案例和修复建议。\n\n",
                    encoding="utf-8"
                )

            if not LEARNINGS_FILE.exists():
                LEARNINGS_FILE.write_text(
                    "# ASA 经验总结（Self-Improving）\n\n"
                    "> 系统自动维护，记录成功解决方案。\n\n",
                    encoding="utf-8"
                )
        except Exception as e:
            print(f"[SelfImprover] 初始化 .learnings/ 目录失败: {e}")

    def record_error(
        self,
        query: str,
        error_code: str = "",
        error_message: str = "",
        error_type: str = "unknown",
        fix_hint: str = ""
    ) -> None:
        """
        记录失败案例到 ERRORS.md

        在 error_handler_node 最终放弃时（recovery_level >= 4）调用。

        Args:
            query: 用户原始问题
            error_code: 导致错误的代码片段（取前500字符）
            error_message: 异常堆栈或错误信息（取前300字符）
            error_type: 错误类型 code_error / network_error / auth_error / unknown
            fix_hint: 已知的修复建议（如果有）
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        # 截断过长内容
        query_short = query[:200] if query else "（未知查询）"
        code_short = error_code[:500] if error_code else "（无代码）"
        msg_short = error_message[:300] if error_message else "（无错误信息）"

        entry_parts = [
            f"\n## [{ts}] [{error_type}] {query_short[:80]}",
            "",
            f"**完整问题**: {query_short}",
            "",
            f"**错误类型**: `{error_type}`",
            "",
        ]

        if code_short and code_short != "（无代码）":
            entry_parts += [
                "**错误代码**:",
                "```python",
                code_short,
                "```",
                "",
            ]

        entry_parts += [
            f"**错误信息**: {msg_short}",
            "",
        ]

        if fix_hint:
            entry_parts.append(f"**修复建议**: {fix_hint}")
            entry_parts.append("")

        entry_parts.append("---")
        entry = "\n".join(entry_parts) + "\n"

        try:
            with open(ERRORS_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
            print(f"[SelfImprover] 错误已记录到 {ERRORS_FILE}: [{error_type}] {query_short[:50]}...")
            self._trim_file(ERRORS_FILE)
        except Exception as e:
            print(f"[SelfImprover] 写入 ERRORS.md 失败: {e}")

    def record_success(
        self,
        query: str,
        solution: str = "",
        key_insight: str = ""
    ) -> None:
        """
        记录成功案例到 LEARNINGS.md

        在 Reviewer 通过（execution_status == "success"）后调用。

        Args:
            query: 用户原始问题
            solution: 成功的解决方案摘要
            key_insight: 关键技术要点（供后续参考）
        """
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        query_short = query[:200] if query else "（未知查询）"
        solution_short = solution[:500] if solution else "（无详细方案）"

        entry_parts = [
            f"\n## [{ts}] ✓ {query_short[:80]}",
            "",
            f"**问题**: {query_short}",
            "",
            f"**解决方案**: {solution_short}",
            "",
        ]

        if key_insight:
            entry_parts.append(f"**关键要点**: {key_insight}")
            entry_parts.append("")

        entry_parts.append("---")
        entry = "\n".join(entry_parts) + "\n"

        try:
            with open(LEARNINGS_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
            print(f"[SelfImprover] 经验已记录到 {LEARNINGS_FILE}: {query_short[:50]}...")
            self._trim_file(LEARNINGS_FILE)
        except Exception as e:
            print(f"[SelfImprover] 写入 LEARNINGS.md 失败: {e}")

    def get_relevant_learnings(
        self,
        query: str,
        max_chars: int = MAX_INJECT_CHARS
    ) -> str:
        """
        获取与当前 query 相关的历史经验

        策略:
          1. 从 ERRORS.md 和 LEARNINGS.md 各取最近 5 条记录
          2. 用简单关键词匹配过滤相关条目
          3. 截断到 max_chars 以控制 Token 消耗

        Args:
            query: 当前用户问题（用于关键词匹配）
            max_chars: 返回内容最大字符数

        Returns:
            格式化的经验摘要字符串，为空时返回 ""
        """
        result_sections = []

        # 提取关键词（简单分词：取2字以上的词）
        keywords = self._extract_keywords(query)

        # 从 ERRORS.md 提取相关条目
        error_entries = self._get_entries_from_file(ERRORS_FILE, keywords, max_entries=3)
        if error_entries:
            result_sections.append("【过往错误案例，请参考避免重蹈覆辙】")
            result_sections.extend(error_entries)

        # 从 LEARNINGS.md 提取相关条目
        learning_entries = self._get_entries_from_file(LEARNINGS_FILE, keywords, max_entries=2)
        if learning_entries:
            result_sections.append("【成功经验，可参考借鉴】")
            result_sections.extend(learning_entries)

        if not result_sections:
            return ""

        combined = "\n\n".join(result_sections)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n...（已截断）"

        return combined

    def _extract_keywords(self, query: str) -> List[str]:
        """从查询中提取关键词（简单规则：2字以上中文词组）"""
        # 提取常见金融关键词
        financial_terms = [
            "分红", "股息", "茅台", "利润", "营收", "PE", "PB",
            "财报", "年报", "季报", "港股", "ETF", "指数", "画图",
            "KeyError", "NaN", "空数据", "超时", "限流"
        ]
        found = [term for term in financial_terms if term in query]

        # 额外提取中文词组（2-4字）
        cn_words = re.findall(r'[\u4e00-\u9fff]{2,4}', query)
        found.extend(cn_words[:5])

        return list(set(found)) if found else [query[:10]]

    def _get_entries_from_file(
        self,
        filepath: Path,
        keywords: List[str],
        max_entries: int = 3
    ) -> List[str]:
        """
        从指定文件中获取与关键词相关的条目

        Returns:
            相关条目的摘要列表
        """
        if not filepath.exists():
            return []

        try:
            content = filepath.read_text(encoding="utf-8")
        except Exception:
            return []

        # 按 "---" 分割为独立条目
        raw_entries = content.split("---")

        # 过滤：只保留有实际内容的条目
        valid_entries = [e.strip() for e in raw_entries if len(e.strip()) > 50]

        # 取最近的条目
        recent = valid_entries[-10:] if len(valid_entries) > 10 else valid_entries

        # 关键词相关性过滤
        relevant = []
        for entry in reversed(recent):  # 最近的优先
            score = sum(1 for kw in keywords if kw in entry)
            if score > 0:
                relevant.append((score, entry))

        # 若无匹配，取最近3条
        if not relevant and recent:
            relevant = [(0, e) for e in recent[-3:]]

        # 按相关度排序，取 top N
        relevant.sort(key=lambda x: x[0], reverse=True)
        top_entries = [e for _, e in relevant[:max_entries]]

        # 截断单条记录长度
        return [e[:400] + "..." if len(e) > 400 else e for e in top_entries]

    def _trim_file(self, filepath: Path, max_entries: int = MAX_ENTRIES) -> None:
        """
        防止文件无限增长：超过 max_entries 条时删除最早的记录
        """
        try:
            content = filepath.read_text(encoding="utf-8")
            sections = content.split("---\n")
            if len(sections) > max_entries + 2:  # +2 for header
                header = sections[0]
                kept = sections[-(max_entries):]
                new_content = header + "---\n".join(kept)
                filepath.write_text(new_content, encoding="utf-8")
                print(f"[SelfImprover] 已裁剪 {filepath.name}，保留最近 {max_entries} 条记录")
        except Exception as e:
            print(f"[SelfImprover] 裁剪文件失败: {e}")

    def get_stats(self) -> dict:
        """返回错题本统计信息"""
        stats = {"errors": 0, "learnings": 0, "errors_file": str(ERRORS_FILE), "learnings_file": str(LEARNINGS_FILE)}
        for key, filepath in [("errors", ERRORS_FILE), ("learnings", LEARNINGS_FILE)]:
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8")
                stats[key] = content.count("---")
        return stats


# ===========================================================================
# 全局单例 + 便捷函数
# ===========================================================================

learning_recorder = LearningRecorder()


def get_learnings_context(query: str, max_chars: int = MAX_INJECT_CHARS) -> str:
    """
    便捷函数：获取与当前查询相关的历史经验

    供 multi_agent.py 的 supervisor_node 直接调用，注入 System Prompt。

    Args:
        query: 当前用户问题
        max_chars: 最大注入字符数

    Returns:
        经验摘要字符串，为空时返回 ""
    """
    return learning_recorder.get_relevant_learnings(query, max_chars)


def record_error_to_learnings(
    query: str,
    error_message: str,
    error_type: str = "unknown",
    error_code: str = "",
    fix_hint: str = ""
) -> None:
    """
    便捷函数：记录错误

    供 error_handler_node 最终放弃时调用。
    """
    learning_recorder.record_error(
        query=query,
        error_code=error_code,
        error_message=error_message,
        error_type=error_type,
        fix_hint=fix_hint
    )


def record_success_to_learnings(query: str, solution: str = "", key_insight: str = "") -> None:
    """
    便捷函数：记录成功经验

    供 Reviewer 通过后调用。
    """
    learning_recorder.record_success(query=query, solution=solution, key_insight=key_insight)
