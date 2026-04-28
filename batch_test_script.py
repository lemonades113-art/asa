#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA 项目批量测试脚本 - 自动生成

使用方式：
    python batch_test_script.py --num_workers 1 --output batch_results.jsonl

会自动：
    1. 加载 50 个 test prompt
    2. 逐个调用 ASA 多智能体系统
    3. 记录响应时间、成功率、输出类型
    4. 生成统计报告
"""

import json
import time
import sys
import argparse
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime

# ASA 项目导入
try:
    from test_prompts_50 import ALL_PROMPTS
    from multi_agent import multi_agent_app
    print("✅ 成功导入 ASA 项目模块")
except ImportError as e:
    print(f"❌ 导入失败：{e}")
    print("请确保在 ASA 项目目录下运行此脚本")
    sys.exit(1)


class BatchTester:
    """批量测试器"""
    
    def __init__(self, output_file: str = "batch_results.jsonl"):
        self.output_file = output_file
        self.results: List[Dict[str, Any]] = []
        self.start_time = None
        self.total_time = 0
    
    def _detect_output_type(self, response: str) -> str:
        """检测输出类型"""
        if not response:
            return "[UNKNOWN]"
        
        # 简单的启发式检测
        if "[DATA]" in response or "数据" in response:
            return "[DATA]"
        elif "[CHART]" in response or "图" in response or "绘制" in response:
            return "[CHART]"
        elif "[REPORT]" in response or "报告" in response or len(response) > 500:
            return "[REPORT]"
        elif "无法" in response or "不存在" in response or "拒答" in response:
            return "[REJECT]"
        else:
            return "[OTHER]"
    
    def _test_single_prompt(self, prompt) -> Dict[str, Any]:
        """测试单个 prompt"""
        
        result = {
            "id": prompt.id,
            "query": prompt.query,
            "difficulty": prompt.difficulty,
            "category": prompt.category,
            "expected_type": prompt.expected_output_type,
            "success": False,
            "detected_type": None,
            "type_match": False,
            "response_length": 0,
            "time_seconds": 0,
            "error": None,
        }
        
        query_start = time.time()
        
        try:
            # 构造输入状态
            from langchain_core.messages import HumanMessage
            
            thread_id = f"batch_test_{prompt.id}_{int(time.time()*1000)}"
            config = {"configurable": {"thread_id": thread_id}}
            
            # 初始化状态
            initial_state = {
                "messages": [HumanMessage(content=prompt.query)],
                "next_agent": "supervisor",
            }
            
            # 调用多智能体系统
            final_state = multi_agent_app.invoke(initial_state, config)
            
            # 提取响应
            messages = final_state.get("messages", [])
            if messages:
                last_msg = messages[-1]
                if hasattr(last_msg, 'content'):
                    response = last_msg.content
                else:
                    response = str(last_msg)
            else:
                response = ""
            
            # 分析输出
            detected_type = self._detect_output_type(response)
            type_match = detected_type == prompt.expected_output_type
            
            result.update({
                "success": True,
                "detected_type": detected_type,
                "type_match": type_match,
                "response_length": len(response),
                "response_preview": response[:100],  # 保留前 100 字符用于调试
            })
            
        except Exception as e:
            result.update({
                "success": False,
                "error": str(e)[:150],
            })
        
        finally:
            result["time_seconds"] = time.time() - query_start
        
        return result
    
    def run(self, num_workers: int = 1, delay_between_queries: float = 0.5, limit: int = 0):
        """运行批量测试
        
        Args:
            num_workers: 并发数（暂未实现）
            delay_between_queries: 查询间隔（秒）
            limit: 限制测试数量（0=全部）
        """
        
        self.start_time = time.time()
        
        # ✨ 支持限制测试数量
        prompts_to_test = ALL_PROMPTS[:limit] if limit > 0 else ALL_PROMPTS
        total_prompts = len(prompts_to_test)
        
        print(f"\n{'='*70}")
        print("【ASA 项目批量测试启动】")
        print(f"{'='*70}")
        print(f"总计 Prompt 数：{total_prompts}")
        print(f"预估耗时：{total_prompts * 8 / 60:.0f} 分钟（假设每个 8 秒）")
        print(f"开始时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        # 逐个测试
        for idx, prompt in enumerate(prompts_to_test, 1):
            print(f"[{idx:2d}/{total_prompts}] {prompt.difficulty:6s} | {prompt.category:10s} | {prompt.query[:50]:50s}", 
                  end=" ", flush=True)
            
            result = self._test_single_prompt(prompt)
            self.results.append(result)
            
            if result["success"]:
                status = f"✅ {result['time_seconds']:.1f}s | {result['detected_type']}"
            else:
                status = f"❌ {result['error']}"
            
            print(status)
            
            # 间隔，避免 API 限流
            if idx < total_prompts:
                time.sleep(delay_between_queries)
        
        self.total_time = time.time() - self.start_time
        self._save_results()
        self._print_summary()
    
    def _save_results(self):
        """保存结果为 JSONL"""
        
        with open(self.output_file, "w", encoding="utf-8") as f:
            for result in self.results:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        
        print(f"\n✅ 结果已保存到：{self.output_file}")
    
    def _print_summary(self):
        """打印统计摘要"""
        
        total = len(self.results)
        success_count = sum(1 for r in self.results if r["success"])
        type_match_count = sum(1 for r in self.results if r.get("type_match", False))
        
        print(f"\n{'='*70}")
        print("【批量测试完成 - 统计摘要】")
        print(f"{'='*70}")
        
        print(f"\n⏱️  耗时统计：")
        print(f"   总耗时：{self.total_time/60:.1f} 分钟（{self.total_time:.0f} 秒）")
        print(f"   平均耗时：{self.total_time/total:.1f} 秒/个")
        
        print(f"\n📊 成功率：")
        print(f"   总数：{total}")
        print(f"   成功：{success_count} ({success_count/total:.0%})")
        print(f"   失败：{total-success_count} ({(total-success_count)/total:.0%})")
        
        print(f"\n🎯 输出类型匹配率：")
        print(f"   匹配：{type_match_count} ({type_match_count/total:.0%})")
        print(f"   不匹配：{total-type_match_count} ({(total-type_match_count)/total:.0%})")
        
        # 按难度分类
        print(f"\n📈 按难度分层：")
        by_difficulty = {}
        for r in self.results:
            diff = r.get("difficulty", "unknown")
            if diff not in by_difficulty:
                by_difficulty[diff] = {"total": 0, "success": 0, "match": 0, "total_time": 0}
            by_difficulty[diff]["total"] += 1
            if r["success"]:
                by_difficulty[diff]["success"] += 1
                by_difficulty[diff]["match"] += r.get("type_match", False)
                by_difficulty[diff]["total_time"] += r.get("time_seconds", 0)
        
        for diff in ["easy", "medium", "hard"]:
            if diff in by_difficulty:
                stats = by_difficulty[diff]
                success_rate = stats["success"] / stats["total"]
                match_rate = stats["match"] / stats["success"] if stats["success"] > 0 else 0
                avg_time = stats["total_time"] / stats["success"] if stats["success"] > 0 else 0
                print(f"   {diff:8s}: {stats['success']:2d}/{stats['total']:2d} ({success_rate:.0%}) | "
                      f"匹配率 {match_rate:.0%} | 平均 {avg_time:.1f}s")
        
        # 按类别分类
        print(f"\n📑 按类别分布：")
        by_category = {}
        for r in self.results:
            cat = r.get("category", "unknown")
            if cat not in by_category:
                by_category[cat] = {"total": 0, "success": 0}
            by_category[cat]["total"] += 1
            if r["success"]:
                by_category[cat]["success"] += 1
        
        for cat in sorted(by_category.keys()):
            stats = by_category[cat]
            rate = stats["success"] / stats["total"]
            print(f"   {cat:15s}: {stats['success']:2d}/{stats['total']:2d} ({rate:.0%})")
        
        # 按输出类型分布
        print(f"\n🎨 按输出类型分布：")
        by_output_type = {}
        for r in self.results:
            if r["success"]:
                ot = r.get("detected_type", "unknown")
                if ot not in by_output_type:
                    by_output_type[ot] = 0
                by_output_type[ot] += 1
        
        for ot in sorted(by_output_type.keys()):
            print(f"   {ot:12s}: {by_output_type[ot]:3d} 个")
        
        # 失败分析
        failed_results = [r for r in self.results if not r["success"]]
        if failed_results:
            print(f"\n❌ 失败分析（共 {len(failed_results)} 个）：")
            error_types = {}
            for r in failed_results:
                error = r.get("error", "unknown")[:50]
                if error not in error_types:
                    error_types[error] = 0
                error_types[error] += 1
            
            for error, count in sorted(error_types.items(), key=lambda x: -x[1])[:5]:
                print(f"   {error}: {count} 个")
        
        # 输出建议
        print(f"\n💡 优化建议：")
        if success_count / total > 0.95:
            print(f"   ✅ 系统整体表现优秀，成功率 > 95%")
        elif success_count / total > 0.80:
            print(f"   ⚠️  成功率 80-95%，建议优化错误处理")
        else:
            print(f"   🔴 成功率 < 80%，需要诊断关键问题")
        
        if type_match_count / total > 0.85:
            print(f"   ✅ 输出类型匹配率高，提示词设计合理")
        else:
            print(f"   ⚠️  输出类型匹配率低，可能需要调整提示词")
        
        avg_response_length = sum(r.get("response_length", 0) for r in self.results if r["success"]) / success_count if success_count > 0 else 0
        if avg_response_length > 200:
            print(f"   ℹ️  平均响应长度 {avg_response_length:.0f} 字，系统倾向生成详细回答")
        
        print(f"\n{'='*70}\n")


def main():
    """主函数"""
    
    parser = argparse.ArgumentParser(
        description="ASA 项目批量测试脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法：
    python batch_test_script.py                              # 默认参数运行
    python batch_test_script.py --output my_results.jsonl    # 自定义输出文件
    python batch_test_script.py --delay 1.0                  # 增加查询间隔（API 限流时）
        """
    )
    
    parser.add_argument(
        "--output",
        default="batch_results.jsonl",
        help="输出文件路径（JSONL 格式）"
    )
    
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="查询间隔（秒），避免 API 限流"
    )
    
    parser.add_argument(
        "--num_workers",
        type=int,
        default=1,
        help="并发数（建议 1-3，不建议超过 3）"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="限制测试数量（0=全部），用于快速验证流程"
    )
    
    args = parser.parse_args()
    
    # 创建测试器并运行
    tester = BatchTester(output_file=args.output)
    tester.run(num_workers=args.num_workers, delay_between_queries=args.delay, limit=args.limit)


if __name__ == "__main__":
    main()
