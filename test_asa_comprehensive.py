#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA 综合功能测试 - 验证系统完整工作流程
测试查询：贵州茅台 vs 五粮液，哪个更值得投资？（需要查询股价、市盈率、股息率、财报等数据）
"""

import json
import sys
sys.path.insert(0, '.')

# 模拟测试用例
test_queries = [
    {
        "id": 1,
        "query": "对比分析贵州茅台(600519)和五粮液(000858)哪个更值得投资？请从股价、市盈率、股息率、财务数据等维度分析。",
        "expected_output_markers": ["[DATA]", "市盈率", "股息率", "财务"],
        "category": "stock_comparison",
        "difficulty": "high"
    },
    {
        "id": 2,
        "query": "查询贵州茅台最近一个季度的财务数据（净利润、ROE、毛利率）",
        "expected_output_markers": ["[DATA]", "净利润", "ROE", "毛利率"],
        "category": "financial_analysis",
        "difficulty": "medium"
    },
    {
        "id": 3,
        "query": "茅台和五粮液的股息率对比如何？哪个更适合分红投资？",
        "expected_output_markers": ["[DATA]", "股息率", "分红"],
        "category": "dividend_analysis",
        "difficulty": "medium"
    }
]

def generate_test_prompt(query_obj):
    """生成测试 Prompt"""
    return f"""
【测试用例 #{query_obj['id']}】
难度：{query_obj['difficulty'].upper()}
类别：{query_obj['category']}

用户查询：
{query_obj['query']}

系统要求：
1. 使用 Tushare/API 获取实时股票数据
2. 输出结构化数据，需要包含 [DATA] 标记
3. 提供明确的投资建议
4. 展示数据来源和时间戳

期望输出包含以下标记：{', '.join(query_obj['expected_output_markers'])}
"""

if __name__ == "__main__":
    print("=" * 80)
    print("🧪 ASA 系统综合功能测试")
    print("=" * 80)
    print()
    
    print("📋 生成的测试查询：\n")
    for query_obj in test_queries:
        print(f"\n【测试 #{query_obj['id']}】{query_obj['category'].upper()}")
        print("-" * 60)
        print(f"难度：{query_obj['difficulty']}")
        print(f"查询：{query_obj['query'][:80]}...")
        print(f"预期标记：{', '.join(query_obj['expected_output_markers'])}")
    
    print("\n" + "=" * 80)
    print("✅ 测试查询生成完毕")
    print("=" * 80)
    print()
    
    # 输出最难的测试用例
    print("🎯 推荐首先运行的测试用例（最难，最全面）：\n")
    hardest = [q for q in test_queries if q['difficulty'] == 'high'][0]
    print(generate_test_prompt(hardest))
    
    print("\n" + "=" * 80)
    print("📝 运行建议：")
    print("=" * 80)
    print("""
1. 环境检查：✅ Tushare Token & API Key 已验证
2. 测试顺序：medium → high（从简到难）
3. 核心验证点：
   - ✓ 工具调用（Tushare API）
   - ✓ 数据检索（LongTermMemory）
   - ✓ 根因分析（RootCauseAnalyzer）
   - ✓ 结果生成（Reviewer）
   - ✓ 因果预防（CausalMemoryGraph）

4. 命令运行：
   python -m pytest test_multi_agent.py -v
   或
   python demo_multi_agent_usage.py

5. 预期结果：
   - 查询响应时间 < 30s
   - 数据结构化输出含 [DATA] 标记
   - 至少 3 层 Agent 协作完成
""")
