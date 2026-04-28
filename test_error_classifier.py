#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ErrorClassifier 完整测试与执行日志生成
模拟真实场景：API错误 → 分类 → 处理策略 → 结果
"""

import json
import time
from datetime import datetime
from error_classifier import ErrorClassifier, classify_error


def simulate_error_handling(test_case: dict, retry_count: int = 0) -> dict:
    """
    模拟错误处理流程
    
    Returns:
        dict: 执行结果日志
    """
    error_msg = test_case["error_msg"]
    scenario = test_case["scenario"]
    
    # 步骤1: 错误分类
    classification = classify_error(error_msg, retry_count)
    
    # 步骤2: 根据策略处理
    steps = []
    final_status = "pending"
    
    if classification.strategy == "graceful_degradation":
        # 优雅降级：直接返回说明，不重试
        steps.append({
            "action": "graceful_degradation",
            "reason": f"{classification.error_type}不可重试",
            "user_message": classification.user_message
        })
        final_status = "graceful_degraded"
        
    elif classification.strategy == "exponential_backoff":
        # 指数退避：等待后重试
        if retry_count < 3:
            steps.append({
                "action": "exponential_backoff",
                "wait_seconds": classification.backoff_seconds,
                "retry_count": retry_count + 1
            })
            final_status = "retry_scheduled"
        else:
            steps.append({
                "action": "max_retries_exceeded",
                "reason": "超过最大重试次数"
            })
            final_status = "failed"
            
    elif classification.strategy == "immediate_retry":
        # 立即重试
        if retry_count < 3:
            steps.append({
                "action": "immediate_retry",
                "retry_count": retry_count + 1
            })
            final_status = "retry_scheduled"
        else:
            steps.append({
                "action": "max_retries_exceeded"
            })
            final_status = "failed"
    
    return {
        "timestamp": datetime.now().isoformat(),
        "scenario": scenario,
        "error_msg": error_msg[:100],
        "classification": {
            "error_type": classification.error_type,
            "is_retryable": classification.is_retryable,
            "strategy": classification.strategy
        },
        "steps": steps,
        "final_status": final_status,
        "user_message": classification.user_message
    }


def generate_test_log():
    """生成完整测试日志"""
    
    # 测试场景定义
    test_scenarios = [
        {
            "scenario": "API授权失效",
            "error_msg": "API授权失效,请检查配置: [DATE]: 2026-01-30 [SOURCE]: Tushare Pro API",
            "expected_type": "auth_error",
            "expected_strategy": "graceful_degradation"
        },
        {
            "scenario": "Tushare限流",
            "error_msg": "请求过于频繁，请稍后再试 (429 Too Many Requests)",
            "expected_type": "rate_limit",
            "expected_strategy": "exponential_backoff"
        },
        {
            "scenario": "网络超时",
            "error_msg": "Connection timeout after 30 seconds: HTTPSConnectionPool(host='api.tushare.pro', port=443)",
            "expected_type": "network_error",
            "expected_strategy": "exponential_backoff"
        },
        {
            "scenario": "数据真空-财报未发布",
            "error_msg": "[DATA]: {'error': '无数据', 'reason': '2025年一季报尚未发布'}",
            "expected_type": "data_vacuum",
            "expected_strategy": "graceful_degradation"
        },
        {
            "scenario": "数据真空-股票停牌",
            "error_msg": "股票已停牌，无法获取数据 (ts_code: 000001.SZ)",
            "expected_type": "data_vacuum",
            "expected_strategy": "graceful_degradation"
        },
        {
            "scenario": "代码错误-KeyError",
            "error_msg": "KeyError: 'trade_date' not found in DataFrame",
            "expected_type": "code_error",
            "expected_strategy": "immediate_retry"
        },
        {
            "scenario": "代码错误-TypeError",
            "error_msg": "TypeError: cannot concatenate 'str' and 'int' objects",
            "expected_type": "code_error",
            "expected_strategy": "immediate_retry"
        },
        {
            "scenario": "未知错误",
            "error_msg": "Unknown error occurred during execution",
            "expected_type": "unknown",
            "expected_strategy": "immediate_retry"
        }
    ]
    
    # 执行测试
    results = []
    print("=" * 80)
    print("ErrorClassifier 完整测试 - 模拟真实错误处理场景")
    print("=" * 80)
    
    for i, test in enumerate(test_scenarios, 1):
        print(f"\n{'='*80}")
        print(f"测试 {i}/8: {test['scenario']}")
        print(f"{'='*80}")
        print(f"错误信息: {test['error_msg'][:80]}...")
        
        # 模拟处理
        result = simulate_error_handling(test)
        results.append(result)
        
        # 打印结果
        print(f"\n分类结果:")
        print(f"  - 错误类型: {result['classification']['error_type']}")
        print(f"  - 是否可重试: {result['classification']['is_retryable']}")
        print(f"  - 处理策略: {result['classification']['strategy']}")
        print(f"\n处理步骤:")
        for step in result['steps']:
            print(f"  - {step['action']}")
        print(f"\n最终状态: {result['final_status']}")
        print(f"用户消息: {result['user_message']}")
        
        # 验证
        if result['classification']['error_type'] == test['expected_type']:
            print(f"✅ 分类正确")
        else:
            print(f"❌ 分类错误 (期望: {test['expected_type']})")
    
    # 生成统计
    stats = {
        "total_tests": len(results),
        "graceful_degradation": len([r for r in results if r['final_status'] == 'graceful_degraded']),
        "retry_scheduled": len([r for r in results if r['final_status'] == 'retry_scheduled']),
        "failed": len([r for r in results if r['final_status'] == 'failed']),
        "by_error_type": {}
    }
    
    for r in results:
        et = r['classification']['error_type']
        stats['by_error_type'][et] = stats['by_error_type'].get(et, 0) + 1
    
    print(f"\n{'='*80}")
    print("测试统计")
    print(f"{'='*80}")
    print(f"总测试数: {stats['total_tests']}")
    print(f"优雅降级: {stats['graceful_degradation']} (不可重试错误)")
    print(f"计划重试: {stats['retry_scheduled']} (可重试错误)")
    print(f"失败终止: {stats['failed']} (超过重试次数)")
    print(f"\n错误类型分布:")
    for et, count in stats['by_error_type'].items():
        print(f"  - {et}: {count}")
    
    # 保存日志
    log_data = {
        "test_timestamp": datetime.now().isoformat(),
        "summary": stats,
        "results": results
    }
    
    log_filename = f"error_classifier_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_filename, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 执行日志已保存: {log_filename}")
    
    return log_data


if __name__ == "__main__":
    log_data = generate_test_log()
