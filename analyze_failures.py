#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分析压测失败案例"""
import json
import os

def analyze_failures():
    result_file = r"D:\HuaweiMoveData\Users\HUAWEI\Desktop\简历\三个\ASA two\evaluation_results\batch_run_20260130_173002.jsonl"
    
    failures = []
    with open(result_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                if not data.get('success', False):
                    failures.append(data)
    
    print(f"=" * 80)
    print(f"失败案例分析 - 共 {len(failures)} 个失败案例")
    print(f"=" * 80)
    
    for i, fail in enumerate(failures, 1):
        print(f"\n[{i}] Test ID: {fail['test_id']}")
        print(f"Prompt: {fail['prompt']}")
        print(f"Error: {fail.get('error', 'Unknown')[:200]}")
        print(f"Skills Used: {fail.get('skills_used', [])}")
        print("-" * 80)
    
    # 分类统计
    print("\n" + "=" * 80)
    print("失败类型统计")
    print("=" * 80)
    
    error_types = {}
    for fail in failures:
        error = fail.get('error', 'Unknown')
        if 'Recursion limit' in error:
            key = 'Recursion Limit (递归超限)'
        elif 'timeout' in error.lower():
            key = 'Timeout (超时)'
        elif 'api' in error.lower() or 'tushare' in error.lower():
            key = 'API Error (接口错误)'
        else:
            key = 'Other (其他)'
        error_types[key] = error_types.get(key, 0) + 1
    
    for error_type, count in error_types.items():
        print(f"  {error_type}: {count}")
    
    return failures

if __name__ == "__main__":
    analyze_failures()
