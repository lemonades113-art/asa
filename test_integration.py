#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
集成测试：ErrorClassifier + Multi-Agent系统
测试优化后的完整错误处理流程
"""

import json
import asyncio
from datetime import datetime
from typing import Dict, List
from error_classifier import ErrorClassifier, classify_error


# 定义15个测试场景（覆盖各种错误类型）
TEST_PROMPTS = [
    # 1. 正常查询（应成功）
    {
        "id": "TEST_001",
        "prompt": "查询中国平安的股息率",
        "expected_error": None,
        "description": "正常查询-分红数据"
    },
    # 2. API授权失效（应优雅降级）
    {
        "id": "TEST_002", 
        "prompt": "查询贵州茅台的市盈率",
        "mock_error": "API授权失效,请检查配置: Tushare Token无效",
        "expected_error_type": "auth_error",
        "expected_strategy": "graceful_degradation",
        "description": "授权失效-不可重试"
    },
    # 3. 请求限流（应指数退避）
    {
        "id": "TEST_003",
        "prompt": "查询比亚迪的财务报表",
        "mock_error": "请求过于频繁，请稍后再试 (429 Too Many Requests)",
        "expected_error_type": "rate_limit",
        "expected_strategy": "exponential_backoff",
        "description": "限流错误-指数退避"
    },
    # 4. 网络超时（应指数退避）
    {
        "id": "TEST_004",
        "prompt": "查询宁德时代的市值",
        "mock_error": "Connection timeout after 30 seconds: 无法连接到api.tushare.pro",
        "expected_error_type": "network_error",
        "expected_strategy": "exponential_backoff",
        "description": "网络超时-指数退避"
    },
    # 5. 数据真空-财报未发布（应优雅降级）
    {
        "id": "TEST_005",
        "prompt": "查询2025年一季报净利润（2月份查询）",
        "mock_error": "[DATA]: {'error': '无数据', 'reason': '2025年一季报尚未发布'}",
        "expected_error_type": "data_vacuum",
        "expected_strategy": "graceful_degradation",
        "description": "数据真空-财报未发布"
    },
    # 6. 数据真空-股票停牌（应优雅降级）
    {
        "id": "TEST_006",
        "prompt": "查询ST泰禾的最新股价",
        "mock_error": "股票已停牌，无法获取数据 (ts_code: 000732.SZ)",
        "expected_error_type": "data_vacuum",
        "expected_strategy": "graceful_degradation",
        "description": "数据真空-股票停牌"
    },
    # 7. 代码错误-KeyError（应立即重试）
    {
        "id": "TEST_007",
        "prompt": "计算ROE增长率",
        "mock_error": "KeyError: 'roe' not found in DataFrame columns",
        "expected_error_type": "code_error",
        "expected_strategy": "immediate_retry",
        "description": "代码错误-KeyError"
    },
    # 8. 代码错误-TypeError（应立即重试）
    {
        "id": "TEST_008",
        "prompt": "对比两只股票的PE",
        "mock_error": "TypeError: cannot concatenate 'str' and 'float' objects",
        "expected_error_type": "code_error",
        "expected_strategy": "immediate_retry",
        "description": "代码错误-TypeError"
    },
    # 9. 复杂查询-多股票对比（应成功）
    {
        "id": "TEST_009",
        "prompt": "对比茅台、五粮液、泸州老窖的股息率",
        "expected_error": None,
        "description": "复杂查询-多股票对比"
    },
    # 10. 数据真空-退市股票（应优雅降级）
    {
        "id": "TEST_010",
        "prompt": "查询退市银鸽的财务数据",
        "mock_error": "该股票已退市，无法获取数据",
        "expected_error_type": "data_vacuum",
        "expected_strategy": "graceful_degradation",
        "description": "数据真空-退市股票"
    },
    # 11. 网络错误-DNS解析失败（应指数退避）
    {
        "id": "TEST_011",
        "prompt": "查询上证指数成分股",
        "mock_error": "Network unreachable: getaddrinfo failed: api.tushare.pro",
        "expected_error_type": "network_error",
        "expected_strategy": "exponential_backoff",
        "description": "网络错误-DNS失败"
    },
    # 12. 未知错误（应立即重试）
    {
        "id": "TEST_012",
        "prompt": "查询某股票的波动率",
        "mock_error": "Unknown error occurred: internal server error",
        "expected_error_type": "unknown",
        "expected_strategy": "immediate_retry",
        "description": "未知错误-默认重试"
    },
    # 13. 长链路任务-多步骤（应成功）
    {
        "id": "TEST_013",
        "prompt": "分析科大讯飞的政府补贴占净利润比重，并评估盈利质量",
        "expected_error": None,
        "description": "长链路任务-28步成功"
    },
    # 14. 代码错误-NameError（应立即重试）
    {
        "id": "TEST_014",
        "prompt": "计算夏普比率",
        "mock_error": "NameError: name 'np' is not defined",
        "expected_error_type": "code_error",
        "expected_strategy": "immediate_retry",
        "description": "代码错误-NameError"
    },
    # 15. API限流-频繁查询（应指数退避）
    {
        "id": "TEST_015",
        "prompt": "批量查询10只股票的估值指标",
        "mock_error": "访问过于频繁，请降低查询频率 (limit: 60/min)",
        "expected_error_type": "rate_limit",
        "expected_strategy": "exponential_backoff",
        "description": "限流错误-批量查询"
    }
]


class IntegratedSystemTester:
    """集成系统测试器"""
    
    def __init__(self):
        self.results = []
        
    def simulate_agent_execution(self, test_case: Dict, retry_count: int = 0) -> Dict:
        """
        模拟Agent执行流程（集成ErrorClassifier）
        """
        prompt = test_case["prompt"]
        mock_error = test_case.get("mock_error")
        
        # 模拟执行步骤
        steps = []
        
        # Step 1: Supervisor解析意图
        steps.append({
            "node": "Supervisor",
            "action": "parse_intent",
            "content": f"解析查询意图: {prompt[:30]}..."
        })
        
        # Step 2: Coder生成代码
        steps.append({
            "node": "Coder",
            "action": "generate_code",
            "content": "生成Python代码调用Tushare API"
        })
        
        # Step 3: 执行（可能出错）
        if mock_error:
            # 出错 → ErrorClassifier分类
            classification = classify_error(mock_error, retry_count)
            
            steps.append({
                "node": "Tools",
                "action": "execute",
                "status": "error",
                "error_msg": mock_error[:100]
            })
            
            steps.append({
                "node": "ErrorHandler",
                "action": "classify_error",
                "error_type": classification.error_type,
                "strategy": classification.strategy,
                "is_retryable": classification.is_retryable
            })
            
            # 根据策略处理
            if classification.strategy == "graceful_degradation":
                steps.append({
                    "node": "ErrorHandler",
                    "action": "graceful_degradation",
                    "reason": f"{classification.error_type}不可重试",
                    "user_message": classification.user_message
                })
                final_status = "graceful_degraded"
                success = True  # 优雅降级视为成功处理
                
            elif classification.strategy == "exponential_backoff":
                if retry_count < 2:
                    steps.append({
                        "node": "ErrorHandler",
                        "action": "exponential_backoff",
                        "wait_seconds": classification.backoff_seconds,
                        "retry_count": retry_count + 1
                    })
                    # 递归模拟重试
                    retry_result = self.simulate_agent_execution(test_case, retry_count + 1)
                    steps.extend(retry_result["steps"][3:])  # 跳过前面重复的步骤
                    final_status = retry_result["final_status"]
                    success = retry_result["success"]
                else:
                    steps.append({
                        "node": "ErrorHandler",
                        "action": "max_retries_exceeded",
                        "reason": "超过最大重试次数(3次)"
                    })
                    final_status = "failed"
                    success = False
                    
            else:  # immediate_retry
                if retry_count < 2:
                    steps.append({
                        "node": "ErrorHandler",
                        "action": "immediate_retry",
                        "retry_count": retry_count + 1
                    })
                    retry_result = self.simulate_agent_execution(test_case, retry_count + 1)
                    steps.extend(retry_result["steps"][3:])
                    final_status = retry_result["final_status"]
                    success = retry_result["success"]
                else:
                    steps.append({
                        "node": "ErrorHandler",
                        "action": "max_retries_exceeded"
                    })
                    final_status = "failed"
                    success = False
        else:
            # 成功执行
            steps.append({
                "node": "Tools",
                "action": "execute",
                "status": "success",
                "has_data": True
            })
            
            steps.append({
                "node": "Reviewer",
                "action": "audit",
                "content": "审计数据完整性和逻辑合理性"
            })
            
            steps.append({
                "node": "ProfileUpdater",
                "action": "update_profile",
                "content": "更新用户画像"
            })
            
            final_status = "success"
            success = True
        
        return {
            "steps": steps,
            "final_status": final_status,
            "success": success,
            "total_steps": len(steps)
        }
    
    def run_tests(self):
        """运行所有测试"""
        print("=" * 80)
        print("集成测试：ErrorClassifier + Multi-Agent系统")
        print("=" * 80)
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"测试场景: {len(TEST_PROMPTS)}个")
        print("=" * 80)
        
        for i, test in enumerate(TEST_PROMPTS, 1):
            print(f"\n{'='*80}")
            print(f"测试 {i:02d}/15: {test['id']}")
            print(f"场景: {test['description']}")
            print(f"Prompt: {test['prompt']}")
            
            # 执行测试
            result = self.simulate_agent_execution(test)
            
            # 验证结果
            if test.get("expected_error_type"):
                # 有错误场景
                error_handler_step = [s for s in result["steps"] if s["node"] == "ErrorHandler" and s["action"] == "classify_error"]
                if error_handler_step:
                    actual_type = error_handler_step[0]["error_type"]
                    expected_type = test["expected_error_type"]
                    match = actual_type == expected_type
                    
                    print(f"\n错误分类:")
                    print(f"  预期: {expected_type}")
                    print(f"  实际: {actual_type}")
                    print(f"  {'✅ 匹配' if match else '❌ 不匹配'}")
                    
                    print(f"\n处理策略:")
                    print(f"  预期: {test['expected_strategy']}")
                    print(f"  实际: {error_handler_step[0]['strategy']}")
            
            print(f"\n执行结果:")
            print(f"  总步数: {result['total_steps']}")
            print(f"  最终状态: {result['final_status']}")
            print(f"  是否成功: {'✅' if result['success'] else '❌'}")
            
            # 记录结果
            self.results.append({
                "test_id": test["id"],
                "prompt": test["prompt"],
                "description": test["description"],
                "expected_error_type": test.get("expected_error_type"),
                "actual_error_type": error_handler_step[0]["error_type"] if test.get("expected_error_type") else None,
                "strategy": error_handler_step[0]["strategy"] if test.get("expected_error_type") else None,
                "total_steps": result["total_steps"],
                "final_status": result["final_status"],
                "success": result["success"],
                "steps": result["steps"]
            })
        
        # 生成统计
        self._generate_report()
    
    def _generate_report(self):
        """生成测试报告"""
        print(f"\n{'='*80}")
        print("测试报告")
        print(f"{'='*80}")
        
        total = len(self.results)
        success = len([r for r in self.results if r["success"]])
        failed = total - success
        
        # 按错误类型统计
        error_types = {}
        strategies = {}
        for r in self.results:
            if r["expected_error_type"]:
                et = r["actual_error_type"]
                error_types[et] = error_types.get(et, 0) + 1
                
                st = r["strategy"]
                strategies[st] = strategies.get(st, 0) + 1
        
        print(f"\n总体统计:")
        print(f"  总测试数: {total}")
        print(f"  成功处理: {success} ({success/total*100:.1f}%)")
        print(f"  失败终止: {failed} ({failed/total*100:.1f}%)")
        
        print(f"\n错误类型分布:")
        for et, count in sorted(error_types.items()):
            print(f"  - {et}: {count}")
        
        print(f"\n处理策略分布:")
        for st, count in sorted(strategies.items()):
            print(f"  - {st}: {count}")
        
        # 保存详细日志
        report = {
            "test_timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total,
                "success": success,
                "failed": failed,
                "success_rate": f"{success/total*100:.1f}%"
            },
            "error_type_distribution": error_types,
            "strategy_distribution": strategies,
            "results": self.results
        }
        
        filename = f"integration_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 详细报告已保存: {filename}")


if __name__ == "__main__":
    tester = IntegratedSystemTester()
    tester.run_tests()
