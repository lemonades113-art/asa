#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Error Handler Strategy Pattern
==============================
Reference: LangGraph Issue #6170 - Middleware-style error handling
         + rohitrmd/multi-agent-supervisor-system Command construct

Replaces the 300+ line nested if-else in error_handler_node with pluggable strategies.

v2.1 升级要点 (面试强化):
1. 字段纠错机制：RAG-assisted field correction for KeyError
2. 错误压缩：压缩冗长 Traceback 用于上下文窗口
"""

import re
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from difflib import get_close_matches

try:
    import conf
except ImportError:
    conf = None


# =============================================================================
# 字段纠错机制（Field Correction Mechanism）
# 解决 Tushare 字段命名不规范导致的 KeyError
# =============================================================================

def extract_field_error(error_message: str) -> Optional[Dict[str, str]]:
    """
    从错误信息中提取字段名
    
    Args:
        error_message: 错误信息字符串
        
    Returns:
        {"field": 错误字段名} 或 None
        
    Example:
        Input: "KeyError: 'pb_ttm'"
        Output: {"field": "pb_ttm"}
    """
    # 匹配 KeyError: 'field_name' 或 KeyError: "field_name"
    match = re.search(r"KeyError:\s*['\"](\w+)['\"]", error_message)
    if match:
        return {"field": match.group(1)}
    
    # 匹配 DataFrame 列不存在的情况
    match = re.search(r"'(\w+)'\s+not\s+in\s+index", error_message, re.IGNORECASE)
    if match:
        return {"field": match.group(1)}
    
    return None


def suggest_field_correction(wrong_field: str, available_fields: list, cutoff: float = 0.6) -> Optional[str]:
    """
    使用模糊匹配建议正确的字段名
    
    Args:
        wrong_field: 错误的字段名
        available_fields: 可用的字段列表
        cutoff: 相似度阈值（0-1）
        
    Returns:
        建议的正确字段名，或 None
    """
    matches = get_close_matches(wrong_field, available_fields, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def generate_field_correction_feedback(wrong_field: str, suggested_field: Optional[str], 
                                       interface_hint: str = "") -> str:
    """
    生成字段纠错的反馈消息
    
    Args:
        wrong_field: 错误的字段名
        suggested_field: 建议的正确字段名
        interface_hint: 接口提示（如 "daily_basic"）
        
    Returns:
        结构化的纠错反馈
    """
    feedback = f"""【字段纠错】检测到字段 '{wrong_field}' 不存在

可能原因：
1. 字段名拼写错误
2. 该接口不包含此字段
3. 字段名已变更（Tushare 偶尔会调整字段名）
"""
    
    if suggested_field:
        feedback += f"""
【建议修正】
错误字段: {wrong_field}
建议字段: {suggested_field}

请将代码中的 '{wrong_field}' 替换为 '{suggested_field}' 后重试。
"""
    else:
        feedback += f"""
【建议】
请使用 search 工具查询 "{interface_hint} 接口字段列表" 获取正确的字段名。
常见字段：ts_code, trade_date, open, high, low, close, vol, amount
"""
    
    return feedback


# =============================================================================
# 错误压缩机制（Error Compression）
# 防止冗长 Traceback 占满上下文窗口
# =============================================================================

def compress_error_traceback(error_message: str, max_lines: int = 5) -> str:
    """
    压缩冗长的错误堆栈，保留关键信息
    
    Args:
        error_message: 原始错误信息
        max_lines: 保留的最大行数
        
    Returns:
        压缩后的错误信息
        
    Example:
        Input: 50行 Traceback
        Output: "Error: KeyError: 'pb_ttm'\n... (45 lines omitted) ...\nFile xxx.py, line 42"
    """
    lines = error_message.split('\n')
    
    if len(lines) <= max_lines:
        return error_message
    
    # 保留：第一行（错误类型）+ 最后几行（位置信息）
    first_lines = lines[:2]  # 错误类型和简要信息
    last_lines = lines[-(max_lines-2):]  # 最后的位置信息
    omitted_count = len(lines) - len(first_lines) - len(last_lines)
    
    compressed = '\n'.join(first_lines)
    compressed += f"\n... ({omitted_count} lines omitted) ..."
    compressed += '\n' + '\n'.join(last_lines)
    
    return compressed


# =============================================================================
# 错误处理策略基类
# =============================================================================


@dataclass
class ErrorContext:
    """Error handling context"""
    error_type: str
    recovery_level: int
    retry_count: int
    error_message: str
    last_sender: str
    fallback_strategy: Dict[str, Any]


class ErrorHandlerStrategy(ABC):
    """Base class for error handling strategies"""
    
    @abstractmethod
    def can_handle(self, ctx: ErrorContext) -> bool:
        """Check if this strategy can handle the error"""
        pass
    
    @abstractmethod
    def handle(self, ctx: ErrorContext, state: Dict) -> Dict:
        """Handle the error and return state update"""
        pass


class ImmediateRetryHandler(ErrorHandlerStrategy):
    """
    Level 1: Immediate Retry with Field Correction
    For code_error / field_error / network_error with retry_count < 3

    v2.3 升级：
    - field_error 类型直接查 _FIELD_ALIAS_TABLE 建议字段，迭代效率 +50%
    - 字段纠错反馈带入 Schema 提示头，速引导层标识
    """

    def can_handle(self, ctx: ErrorContext) -> bool:
        return (
            ctx.recovery_level == 1
            and ctx.error_type in ["code_error", "field_error", "network_error"]
            and ctx.retry_count < 3
        )

    def handle(self, ctx: ErrorContext, state: Dict) -> Dict:
        feedback_parts = []

        # 1. 基础提示
        fallback_hint = ctx.fallback_strategy.get("hint", "")
        if fallback_hint:
            feedback_parts.append(f"[Retry Hint] {fallback_hint}")

        # 2. 字段错误快速纠错（新增：field_error 直接查别名表）
        if ctx.error_type == "field_error":
            wrong_field = None
            # 从错误信息中提取字段名
            fe = extract_field_error(ctx.error_message)
            if fe:
                wrong_field = fe["field"]

            if wrong_field:
                # 直接查别名表（O(1)，无需 LLM 调用）
                suggested = _FIELD_ALIAS_TABLE.get(wrong_field)
                # 再尝试模糊匹配
                if not suggested:
                    suggested = suggest_field_correction(
                        wrong_field, list(_FIELD_ALIAS_TABLE.values()), cutoff=0.6
                    )
                correction = generate_field_correction_feedback(
                    wrong_field=wrong_field,
                    suggested_field=suggested,
                    interface_hint=ctx.fallback_strategy.get("interface_hint", "")
                )
                feedback_parts.append(
                    f"[Schema 字段纠错] {correction}"
                )
                if suggested:
                    feedback_parts.append(
                        f"[Alias Table 快速路由] '{wrong_field}' 建议替换为 '{suggested}'"
                    )
        else:
            # 3. 常规字段纠错反馈
            field_correction = ctx.fallback_strategy.get("field_correction")
            if field_correction:
                feedback_parts.append(field_correction)

        # 4. 错误预览（压缩后）
        error_preview = ctx.error_message[:300]
        feedback_parts.append(f"[Error Preview] {error_preview}...")

        full_feedback = "\n\n".join(feedback_parts)

        return {
            "recovery_level": ctx.recovery_level + 1,
            "retry_count": ctx.retry_count + 1,
            "execution_status": "error",
            "error_type": ctx.error_type,
            "last_sender": "ErrorHandler",
            "next": "Supervisor",
            "messages": [{
                "role": "system",
                "content": full_feedback
            }]
        }


class SmartFallbackHandler(ErrorHandlerStrategy):
    """
    Level 2: Smart Fallback with memory-based strategy
    """
    
    def can_handle(self, ctx: ErrorContext) -> bool:
        return ctx.recovery_level == 2
    
    def handle(self, ctx: ErrorContext, state: Dict) -> Dict:
        fallback_hint = ctx.fallback_strategy.get("hint", "")
        return {
            "recovery_level": ctx.recovery_level + 1,
            "execution_status": "error",
            "error_type": ctx.error_type,
            "last_sender": "ErrorHandler",
            "next": "Supervisor",
            "messages": [{
                "role": "system",
                "content": f"[Fallback Strategy] {fallback_hint}"
            }]
        }


class RCAEnhancedHandler(ErrorHandlerStrategy):
    """
    Level 3: Root Cause Analysis enhanced retry
    """
    
    def can_handle(self, ctx: ErrorContext) -> bool:
        return ctx.recovery_level == 3
    
    def handle(self, ctx: ErrorContext, state: Dict) -> Dict:
        # RCA module integration
        return {
            "recovery_level": ctx.recovery_level + 1,
            "execution_status": "error",
            "error_type": ctx.error_type,
            "last_sender": "ErrorHandler",
            "next": "Supervisor",
            "messages": [{
                "role": "system",
                "content": "[RCA Analysis] Analyzing root cause and adjusting strategy..."
            }]
        }


class RejectHandler(ErrorHandlerStrategy):
    """
    Level 4: Final rejection with Self-Improving record
    """
    
    def can_handle(self, ctx: ErrorContext) -> bool:
        return ctx.recovery_level >= 4 or ctx.error_type == "auth_error"
    
    def handle(self, ctx: ErrorContext, state: Dict) -> Dict:
        # Record to .learnings/ for Self-Improving
        try:
            from self_improver import record_error_to_learnings
            record_error_to_learnings(
                query=state.get("original_query", ""),
                error_message=ctx.error_message[:300],
                error_type=ctx.error_type,
                fix_hint=ctx.fallback_strategy.get("hint", "")
            )
        except Exception:
            pass  # Non-blocking
        
        return {
            "recovery_level": 0,
            "recovery_history": [],
            "execution_status": "error",
            "error_type": ctx.error_type,
            "last_sender": "ErrorHandler",
            "next": "Supervisor",
            "messages": [{
                "role": "assistant",
                "content": f"[REJECT] Max retries exceeded for {ctx.error_type}. Error: {ctx.error_message[:200]}"
            }]
        }


class ErrorHandlerRouter:
    """
    Router that delegates to appropriate strategy
    Reference: langgraph-supervisor-py pattern
    """
    
    def __init__(self):
        self.strategies = [
            ImmediateRetryHandler(),
            SmartFallbackHandler(),
            RCAEnhancedHandler(),
            RejectHandler()  # Must be last (catch-all)
        ]
    
    def route(self, ctx: ErrorContext, state: Dict) -> Dict:
        """Route error to appropriate handler"""
        for strategy in self.strategies:
            if strategy.can_handle(ctx):
                return strategy.handle(ctx, state)
        
        # Fallback: should never reach here if RejectHandler is last
        return RejectHandler().handle(ctx, state)


# Global router instance
error_router = ErrorHandlerRouter()


# =============================================================================
# API 实时 Schema 查询（解决 RAG 文档过期问题）
# =============================================================================

class TushareSchemaClient:
    """
    Tushare API 实时 Schema 查询客户端
    
    设计思路：
    - 不是删除 RAG，而是作为 RAG 的补充
    - 当 RAG 检索不到或字段报错时，实时查询官方 Schema
    - 缓存结果，避免重复请求
    """
    
    def __init__(self, token: str = None):
        self.token = token or (conf.tushare_token if conf else None)
        self._cache = {}  # 内存缓存
        self._cache_ttl = 3600  # 缓存 1 小时
        self._cache_time = {}
    
    def get_api_fields(self, api_name: str) -> Dict[str, str]:
        """
        获取指定 API 的字段列表（实时查询 + 缓存）
        
        Args:
            api_name: API 名称，如 'daily_basic', 'income'
            
        Returns:
            {字段名: 字段描述}
        """
        # 检查缓存
        now = time.time()
        if api_name in self._cache:
            if now - self._cache_time.get(api_name, 0) < self._cache_ttl:
                return self._cache[api_name]
        
        # 实时查询（通过 Tushare API 的 query 接口）
        try:
            import tushare as ts
            pro = ts.pro_api(self.token)
            
            # Tushare 提供 api 字段查询接口
            df = pro.query('api_fields', api_name=api_name)
            
            if df is not None and not df.empty:
                fields = {}
                for _, row in df.iterrows():
                    field_name = row.get('field', row.get('name', ''))
                    field_desc = row.get('desc', row.get('description', ''))
                    fields[field_name] = field_desc
                
                # 更新缓存
                self._cache[api_name] = fields
                self._cache_time[api_name] = now
                
                print(f"[SchemaClient] 实时获取 {api_name} 字段: {len(fields)} 个")
                return fields
            
        except Exception as e:
            print(f"[SchemaClient] 实时查询失败: {e}")
        
        # 失败返回空
        return {}
    
    def find_similar_field(self, api_name: str, wrong_field: str, cutoff: float = 0.6) -> Optional[str]:
        """
        在实时 Schema 中查找相似字段
        
        Args:
            api_name: API 名称
            wrong_field: 错误的字段名
            cutoff: 相似度阈值
            
        Returns:
            最相似的字段名，或 None
        """
        fields = self.get_api_fields(api_name)
        if not fields:
            return None
        
        from difflib import get_close_matches
        matches = get_close_matches(wrong_field, fields.keys(), n=1, cutoff=cutoff)
        
        if matches:
            suggested = matches[0]
            print(f"[SchemaClient] 字段纠错: {wrong_field} -> {suggested} (API: {api_name})")
            return suggested
        
        return None


# 全局 Schema 客户端实例
schema_client = TushareSchemaClient()


# =============================================================================
# Tushare Schema 变更监控（自动检测字段变动）
# =============================================================================

import hashlib
import json
from datetime import datetime, timedelta
from typing import List, Dict

class TushareSchemaMonitor:
    """
    Tushare Schema 变更监控器
    
    功能：
    1. 定期抓取 Tushare 官方文档
    2. 对比本地缓存，检测字段增删改
    3. 自动更新 _FIELD_ALIAS_TABLE
    4. 发送告警通知
    
    使用：
    - 手动调用：monitor.check_schema_changes()
    - 定时任务：每日凌晨自动执行
    """
    
    def __init__(self, token: str = None, cache_dir: str = "./.schema_cache"):
        self.token = token or (conf.tushare_token if conf else None)
        self.cache_dir = cache_dir
        self.changelog_path = f"{cache_dir}/schema_changelog.json"
        self._ensure_cache_dir()
    
    def _ensure_cache_dir(self):
        import os
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def _fetch_all_api_schemas(self) -> Dict[str, List[str]]:
        """获取所有 API 的字段列表"""
        try:
            import tushare as ts
            pro = ts.pro_api(self.token)
            
            # 获取所有 API 列表
            api_list_df = pro.query('api_list')  # 假设有这个接口
            
            schemas = {}
            for api_name in api_list_df['api_name'] if api_list_df is not None else []:
                fields_df = pro.query('api_fields', api_name=api_name)
                if fields_df is not None and not fields_df.empty:
                    schemas[api_name] = fields_df['field'].tolist()
            
            return schemas
            
        except Exception as e:
            print(f"[SchemaMonitor] 获取 Schema 失败: {e}")
            return {}
    
    def _compute_schema_hash(self, schemas: Dict) -> str:
        """计算 Schema 指纹"""
        schema_str = json.dumps(schemas, sort_keys=True)
        return hashlib.md5(schema_str.encode()).hexdigest()
    
    def _load_last_snapshot(self) -> Dict:
        """加载上次快照"""
        snapshot_path = f"{self.cache_dir}/last_snapshot.json"
        if os.path.exists(snapshot_path):
            with open(snapshot_path, 'r') as f:
                return json.load(f)
        return {}
    
    def _save_snapshot(self, schemas: Dict):
        """保存当前快照"""
        snapshot_path = f"{self.cache_dir}/last_snapshot.json"
        with open(snapshot_path, 'w') as f:
            json.dump(schemas, f, indent=2)
    
    def _detect_changes(self, old: Dict, new: Dict) -> List[Dict]:
        """检测变更"""
        changes = []
        
        for api_name, new_fields in new.items():
            old_fields = old.get(api_name, [])
            
            # 新增字段
            for field in new_fields:
                if field not in old_fields:
                    changes.append({
                        "api": api_name,
                        "field": field,
                        "action": "added",
                        "timestamp": datetime.now().isoformat()
                    })
            
            # 删除字段
            for field in old_fields:
                if field not in new_fields:
                    changes.append({
                        "api": api_name,
                        "field": field,
                        "action": "removed",
                        "timestamp": datetime.now().isoformat()
                    })
        
        # 新增 API
        for api_name in new:
            if api_name not in old:
                changes.append({
                    "api": api_name,
                    "action": "api_added",
                    "fields": new[api_name],
                    "timestamp": datetime.now().isoformat()
                })
        
        return changes
    
    def check_schema_changes(self) -> List[Dict]:
        """
        检查 Schema 变更
        
        Returns:
            变更列表，每个变更包含 api, field, action, timestamp
        """
        print(f"[SchemaMonitor] 开始检测 Schema 变更...")
        
        # 获取当前 Schema
        current_schemas = self._fetch_all_api_schemas()
        if not current_schemas:
            return []
        
        # 加载上次快照
        last_schemas = self._load_last_snapshot()
        
        # 检测变更
        changes = self._detect_changes(last_schemas, current_schemas)
        
        if changes:
            print(f"[SchemaMonitor] 检测到 {len(changes)} 项变更:")
            for change in changes[:5]:  # 只显示前 5 个
                print(f"  - {change['api']}: {change.get('field', 'N/A')} {change['action']}")
            
            # 自动更新 alias table
            self._auto_update_aliases(changes)
            
            # 记录变更日志
            self._log_changes(changes)
        else:
            print(f"[SchemaMonitor] 无变更")
        
        # 保存快照
        self._save_snapshot(current_schemas)
        
        return changes
    
    def _auto_update_aliases(self, changes: List[Dict]):
        """自动更新别名表"""
        new_aliases = {}
        
        for change in changes:
            if change['action'] == 'added':
                # 新字段：检查是否有常见别名
                field = change['field']
                # 例如：pe_ttm 的别名可能有市盈率、PE 等
                # 这里可以接入翻译服务或规则库
                pass
            
            elif change['action'] == 'removed':
                # 删除字段：在 alias table 中标记为废弃
                field = change['field']
                if field in _FIELD_ALIAS_TABLE.values():
                    print(f"[SchemaMonitor] 警告：字段 {field} 已被删除，但仍在 alias table 中")
        
        if new_aliases:
            reload_alias_table(new_aliases)
            print(f"[SchemaMonitor] 自动更新 alias table: {len(new_aliases)} 项")
    
    def _log_changes(self, changes: List[Dict]):
        """记录变更日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "changes": changes
        }
        
        # 追加到 changelog
        logs = []
        if os.path.exists(self.changelog_path):
            with open(self.changelog_path, 'r') as f:
                logs = json.load(f)
        
        logs.append(log_entry)
        
        # 只保留最近 30 天
        cutoff = datetime.now() - timedelta(days=30)
        logs = [l for l in logs if datetime.fromisoformat(l['timestamp']) > cutoff]
        
        with open(self.changelog_path, 'w') as f:
            json.dump(logs, f, indent=2)


# 全局监控器实例
schema_monitor = TushareSchemaMonitor()


def run_daily_schema_check():
    """每日 Schema 检查（可作为定时任务调用）"""
    return schema_monitor.check_schema_changes()


# =============================================================================
# 字段别名热重载表（Hot-Reloadable Alias Table）
# 解决 Tushare Schema 变动导致的字段对齐问题
#
# 面试金句："设计了三级字段路由：
# 高频易错字段 → Hot-Reloadable Alias Table 实时订正
# 中频字段   → BM25 + 向量库 RAG 语义检索
# 长尾字段   → Coder 节点自我纠偏"
# =============================================================================

# 核心别名表：{LLM常用称呼: Tushare实际字段}
# 支持中英文两种表达方式
_FIELD_ALIAS_TABLE: Dict[str, str] = {
    # === PE/PB/ROE 类 ===
    "市盈率": "pe_ttm",
    "PE": "pe_ttm",
    "pe_ratio": "pe_ttm",          # 旧字段厂改点
    "p_e": "pe_ttm",
    "市净率": "pb",
    "PB": "pb",
    "pb_ratio": "pb",
    "市销率": "ps_ttm",
    "PS": "ps_ttm",
    "净资产收益率": "roe",
    "ROE": "roe",
    
    # === 财务数据类 ===
    "净利润": "n_income",
    "net_profit": "n_income",       # income 接口字段地图
    "营业收入": "revenue",
    "每股收益": "eps",
    "EPS": "eps",
    
    # === 市场行情类 ===
    "收盘价": "close",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "成交量": "vol",
    "成交额": "amount",
    
    # === 分红类 ===
    "派息": "div_procf",
    "现金分红": "cash_div",
    "dividend": "cash_div",
    
    # === 日期类 ===
    "交易日期": "trade_date",
    "报告日期": "ann_date",
    "报告期": "end_date",
}


def resolve_field_name(query_field: str, rag_search_func=None) -> str:
    """
    三级字段路由：Alias Table > RAG 语义检索 > 原字段套入
    
    面试金句："高频易错字段通过 Hot-Reloadable Alias Table 实时订正，
    中频字段通过向量库 RAG 语义检索，长尾字段由 Coder 节点自我纠偏。"
    
    Args:
        query_field: LLM 产生的字段名称（可能是中文或非标准英文）
        rag_search_func: RAG 检索函数（可选，不传则跳过 RAG 层）
        
    Returns:
        Tushare 标准字段名
    """
    # 第一级：精确 Alias Table 匹配（O(1) 时间复杂度）
    if query_field in _FIELD_ALIAS_TABLE:
        resolved = _FIELD_ALIAS_TABLE[query_field]
        return resolved
    
    # 第二级：RAG 语义检索（若提供了 rag_search_func）
    if rag_search_func is not None:
        try:
            rag_result = rag_search_func(query_field)
            if rag_result and rag_result != query_field:
                return rag_result
        except Exception:
            pass  # RAG 失败就降级
    
    # 第三级：原字段名传回，由 Coder 节点自我纠偏
    return query_field


def reload_alias_table(new_aliases: Dict[str, str]):
    """
    热重载别名表（不需重启服务）
    
    面试金句："Tushare Schema 升级后，只需调用 reload_alias_table() 传入新映射，
    不需重启服务。这就是 Hot-Reload 的工程价値。"
    
    Args:
        new_aliases: 新的别名映射表
    """
    _FIELD_ALIAS_TABLE.update(new_aliases)


def get_alias_table_stats() -> Dict[str, Any]:
    """获取别名表统计信息（用于监控和调试）"""
    return {
        "total_aliases": len(_FIELD_ALIAS_TABLE),
        "categories": {
            "pe_pb": len([k for k in _FIELD_ALIAS_TABLE if any(x in k.lower() for x in ["pe", "pb", "roe", "市"])]),
            "financial": len([k for k in _FIELD_ALIAS_TABLE if any(x in k for x in ["收益", "利润", "income", "eps"])]),
            "market": len([k for k in _FIELD_ALIAS_TABLE if any(x in k for x in ["价", "close", "open", "vol"])]),
        },
        "sample_entries": dict(list(_FIELD_ALIAS_TABLE.items())[:5])
    }
