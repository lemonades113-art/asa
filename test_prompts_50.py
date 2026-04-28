#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA 项目核心能力验证 Prompt 集（50 个）

设计原则：
1. 分层覆盖：Easy (10) + Medium (25) + Hard (15)
2. 多维度验证：单工具调用、多跳推理、错误恢复、金融知识
3. 可自动评估：每个 prompt 配套期望输出特征
4. 实战数据：基于真实金融场景设计

运行方式：
    python test_prompts_50.py --batch --output results.jsonl
"""

import json
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict


@dataclass
class TestPrompt:
    """测试 Prompt 数据结构"""
    id: int                      # 唯一 ID (1-50)
    difficulty: str              # easy | medium | hard
    category: str                # 分类：单查询、多跳、报告、错误恢复等
    query: str                   # 实际问题
    expected_output_type: str    # 期望输出类型：[DATA]|[CHART]|[REPORT]
    expected_steps: int          # 预期需要多少步
    validation_keywords: List[str] # 用于评估的关键词
    description: str             # 这个 Prompt 测试什么能力
    

# ============================================================================
# 第一类：简单查询（Easy，10 个）- 验证基础工具调用
# ============================================================================
EASY_PROMPTS = [
    TestPrompt(
        id=1,
        difficulty="easy",
        category="单跳查询",
        query="查询贵州茅台（600519）最新的股价",
        expected_output_type="[DATA]",
        expected_steps=1,
        validation_keywords=["600519", "股价", "贵州茅台"],
        description="验证基础的股票查询能力和 API 调用"
    ),
    TestPrompt(
        id=2,
        difficulty="easy",
        category="单跳查询",
        query="比亚迪今天的市盈率（PE）是多少？",
        expected_output_type="[DATA]",
        expected_steps=1,
        validation_keywords=["比亚迪", "市盈率", "PE"],
        description="验证金融指标查询能力"
    ),
    TestPrompt(
        id=3,
        difficulty="easy",
        category="单跳查询",
        query="中国平安最近的分红数据",
        expected_output_type="[DATA]",
        expected_steps=1,
        validation_keywords=["中国平安", "分红", "数据"],
        description="验证财务数据查询"
    ),
    TestPrompt(
        id=4,
        difficulty="easy",
        category="单跳查询",
        query="宁德时代（300750）的市值是多少？",
        expected_output_type="[DATA]",
        expected_steps=1,
        validation_keywords=["300750", "宁德时代", "市值"],
        description="验证市值查询能力"
    ),
    TestPrompt(
        id=5,
        difficulty="easy",
        category="单跳查询",
        query="万科A的流动比率是多少",
        expected_output_type="[DATA]",
        expected_steps=1,
        validation_keywords=["万科", "流动比率"],
        description="验证财务比率查询"
    ),
    TestPrompt(
        id=6,
        difficulty="easy",
        category="单跳查询",
        query="查询恒瑞医药最近30天的股价走势",
        expected_output_type="[CHART]",
        expected_steps=2,  # 查询数据 + 绘图
        validation_keywords=["恒瑞医药", "走势", "图"],
        description="验证基础绘图能力"
    ),
    TestPrompt(
        id=7,
        difficulty="easy",
        category="单跳查询",
        query="招商银行过去3年的净利润增长趋势",
        expected_output_type="[DATA]",
        expected_steps=2,
        validation_keywords=["招商银行", "净利润", "增长"],
        description="验证历史数据对比"
    ),
    TestPrompt(
        id=8,
        difficulty="easy",
        category="单跳查询",
        query="腾讯控股和阿里巴巴的市值哪个更高",
        expected_output_type="[DATA]",
        expected_steps=2,
        validation_keywords=["腾讯", "阿里", "市值"],
        description="验证两个标的对比能力"
    ),
    TestPrompt(
        id=9,
        difficulty="easy",
        category="单跳查询",
        query="美的集团最新财报中的营业收入",
        expected_output_type="[DATA]",
        expected_steps=1,
        validation_keywords=["美的", "营业收入"],
        description="验证财报数据提取"
    ),
    TestPrompt(
        id=10,
        difficulty="easy",
        category="单跳查询",
        query="格力电器的股息率排名在空调行业中的位置",
        expected_output_type="[DATA]",
        expected_steps=2,
        validation_keywords=["格力", "股息率", "行业"],
        description="验证行业对标能力"
    ),
]

# ============================================================================
# 第二类：中等难度（Medium，25 个）- 验证多跳推理、错误恢复、智能分析
# ============================================================================
MEDIUM_PROMPTS = [
    TestPrompt(
        id=11,
        difficulty="medium",
        category="多跳查询",
        query="比较贵州茅台和五粮液过去5年的净利润增长率，哪个更高？",
        expected_output_type="[DATA]",
        expected_steps=3,
        validation_keywords=["茅台", "五粮液", "净利润", "增长率"],
        description="验证多标的多跳推理能力"
    ),
    TestPrompt(
        id=12,
        difficulty="medium",
        category="多跳查询",
        query="分析银行板块中，市盈率最低的3只股票，并比较它们的股息率",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["银行", "市盈率", "股息率"],
        description="验证复杂筛选和排序能力"
    ),
    TestPrompt(
        id=13,
        difficulty="medium",
        category="分析报告",
        query="基于最近3个月的数据，分析贵州茅台的走势特点，说明买入/卖出的理由",
        expected_output_type="[REPORT]",
        expected_steps=3,
        validation_keywords=["走势", "分析", "买入", "理由"],
        description="验证基础投资决策分析能力"
    ),
    TestPrompt(
        id=14,
        difficulty="medium",
        category="多跳查询",
        query="选择科技行业中，市值大于100亿、PE < 30的所有股票，计算它们的平均股息率",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["科技", "市值", "PE", "股息率"],
        description="验证复杂条件筛选和统计计算"
    ),
    TestPrompt(
        id=15,
        difficulty="medium",
        category="多跳查询",
        query="为什么新能源汽车板块的估值在过去一年大幅下降？分析关键驱动因素",
        expected_output_type="[REPORT]",
        expected_steps=4,
        validation_keywords=["新能源", "估值", "驱动因素"],
        description="验证行业基本面分析能力"
    ),
    TestPrompt(
        id=16,
        difficulty="medium",
        category="多跳查询",
        query="对比恒生指数和沪深300，过去12个月哪个涨幅更大？并解释原因",
        expected_output_type="[REPORT]",
        expected_steps=3,
        validation_keywords=["恒生", "沪深300", "涨幅"],
        description="验证指数对标和解释能力"
    ),
    TestPrompt(
        id=17,
        difficulty="medium",
        category="分析报告",
        query="找出过去一个月中，股价上涨超过10%的房地产股票，并分析共同的驱动因素",
        expected_output_type="[REPORT]",
        expected_steps=4,
        validation_keywords=["房地产", "涨幅", "驱动"],
        description="验证事件驱动分析能力"
    ),
    TestPrompt(
        id=18,
        difficulty="medium",
        category="多跳查询",
        query="计算过去一年中，金融板块中所有股票的平均收益率，并与大盘表现对比",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["金融", "收益率", "大盘"],
        description="验证板块统计和对标能力"
    ),
    TestPrompt(
        id=19,
        difficulty="medium",
        category="分析报告",
        query="基于财务指标（PE、PB、股息率），为一个1000万的投资组合推荐5只股票，说明理由",
        expected_output_type="[REPORT]",
        expected_steps=5,
        validation_keywords=["推荐", "财务", "投资"],
        description="验证投资推荐能力"
    ),
    TestPrompt(
        id=20,
        difficulty="medium",
        category="多跳查询",
        query="医药板块中，过去3年研发投入占营收比超过10%的公司，ROE是多少？",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["医药", "研发", "ROE"],
        description="验证复杂财务特征筛选"
    ),
    TestPrompt(
        id=21,
        difficulty="medium",
        category="错误恢复",
        query="查询一个不存在的股票代码 999999 的价格",
        expected_output_type="[REJECT]",
        expected_steps=2,
        validation_keywords=["不存在", "无法", "拒答"],
        description="验证错误检测和优雅降级"
    ),
    TestPrompt(
        id=22,
        difficulty="medium",
        category="错误恢复",
        query="查询茅台明天的股价",
        expected_output_type="[REJECT]",
        expected_steps=2,
        validation_keywords=["无法预测", "历史数据"],
        description="验证时间超界检测"
    ),
    TestPrompt(
        id=23,
        difficulty="medium",
        category="多跳查询",
        query="绘制过去半年贵州茅台和五粮液的收盘价对比图",
        expected_output_type="[CHART]",
        expected_steps=3,
        validation_keywords=["对比", "图"],
        description="验证多序列绘图能力"
    ),
    TestPrompt(
        id=24,
        difficulty="medium",
        category="分析报告",
        query="分析一个跨越疫情前后的股票（如医疗股）的走势变化，并解释政策影响",
        expected_output_type="[REPORT]",
        expected_steps=4,
        validation_keywords=["疫情", "政策", "变化"],
        description="验证宏观事件分析能力"
    ),
    TestPrompt(
        id=25,
        difficulty="medium",
        category="多跳查询",
        query="根据最近一年的数据，分析哪个行业的估值洼地最大",
        expected_output_type="[REPORT]",
        expected_steps=4,
        validation_keywords=["估值", "洼地", "行业"],
        description="验证价值发现能力"
    ),
    TestPrompt(
        id=26,
        difficulty="medium",
        category="多跳查询",
        query="计算消费板块中，净利润同比增长超过20%且股息率高于2%的股票数量",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["消费", "净利润", "股息率"],
        description="验证多条件统计能力"
    ),
    TestPrompt(
        id=27,
        difficulty="medium",
        category="分析报告",
        query="评估一个高科技成长股的估值是否合理，需要从哪些维度分析？",
        expected_output_type="[REPORT]",
        expected_steps=3,
        validation_keywords=["估值", "成长", "分析维度"],
        description="验证方法论输出能力"
    ),
    TestPrompt(
        id=28,
        difficulty="medium",
        category="多跳查询",
        query="在保险行业中，找出最近3年ROE持续增长的所有公司",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["保险", "ROE", "增长"],
        description="验证时间序列筛选"
    ),
    TestPrompt(
        id=29,
        difficulty="medium",
        category="错误恢复",
        query="一个股票代码写错了（如 60051a），系统如何处理？",
        expected_output_type="[REJECT]",
        expected_steps=2,
        validation_keywords=["无效", "格式"],
        description="验证输入验证能力"
    ),
    TestPrompt(
        id=30,
        difficulty="medium",
        category="分析报告",
        query="基于技术面（均线、MACD）和基本面（PE、股息率），综合评估一只股票的投资价值",
        expected_output_type="[REPORT]",
        expected_steps=4,
        validation_keywords=["技术面", "基本面", "综合"],
        description="验证多维度综合分析能力"
    ),
    TestPrompt(
        id=31,
        difficulty="medium",
        category="多跳查询",
        query="对比A股和H股同时上市的公司（如阿里、腾讯），港股溢价有多大？",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["A股", "H股", "溢价"],
        description="验证跨市场对比能力"
    ),
    TestPrompt(
        id=32,
        difficulty="medium",
        category="分析报告",
        query="分析消费升级趋势下，哪些行业/公司最受益，以及潜在的风险是什么？",
        expected_output_type="[REPORT]",
        expected_steps=4,
        validation_keywords=["消费升级", "趋势", "风险"],
        description="验证趋势分析和风险识别能力"
    ),
    TestPrompt(
        id=33,
        difficulty="medium",
        category="多跳查询",
        query="统计制造业上市公司中，负债率超过60%的企业数量和它们的平均PE",
        expected_output_type="[DATA]",
        expected_steps=4,
        validation_keywords=["制造业", "负债率", "PE"],
        description="验证高维度筛选统计"
    ),
    TestPrompt(
        id=34,
        difficulty="medium",
        category="分析报告",
        query="解释为什么同样是芯片公司，不同企业的PE差异这么大，差距来自哪里？",
        expected_output_type="[REPORT]",
        expected_steps=4,
        validation_keywords=["芯片", "PE", "差异"],
        description="验证微观经济学分析能力"
    ),
    TestPrompt(
        id=35,
        difficulty="medium",
        category="多跳查询",
        query="绘制过去2年沪深300成份股中，涨幅top10和跌幅top10的对比图表",
        expected_output_type="[CHART]",
        expected_steps=4,
        validation_keywords=["top10", "对比", "图表"],
        description="验证高级绘图和排序能力"
    ),
]

# ============================================================================
# 第三类：困难（Hard，15 个）- 验证复杂报告生成、深度分析、多角度视角
# ============================================================================
HARD_PROMPTS = [
    TestPrompt(
        id=36,
        difficulty="hard",
        category="复杂报告",
        query="生成一份关于贵州茅台的完整投研报告，包括：基本面分析、技术面分析、估值评估、风险提示、建议",
        expected_output_type="[REPORT]",
        expected_steps=6,
        validation_keywords=["基本面", "技术面", "估值", "风险", "建议"],
        description="验证综合投研报告生成能力"
    ),
    TestPrompt(
        id=37,
        difficulty="hard",
        category="复杂报告",
        query="对比分析三家竞争对手（茅台、五粮液、泸州老窖），从财务、估值、市场地位等维度评估投资价值",
        expected_output_type="[REPORT]",
        expected_steps=6,
        validation_keywords=["对比", "财务", "估值", "市场"],
        description="验证多维度竞争分析能力"
    ),
    TestPrompt(
        id=38,
        difficulty="hard",
        category="复杂报告",
        query="分析新能源电池行业的整体投资机会，包括产业链分析、主要玩家对比、估值水位、未来空间等",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["产业链", "竞争", "估值", "空间"],
        description="验证产业链深度研究能力"
    ),
    TestPrompt(
        id=39,
        difficulty="hard",
        category="复杂报告",
        query="基于过去10年的宏观经济数据和政策背景，分析房地产板块的长期投资价值变化",
        expected_output_type="[REPORT]",
        expected_steps=6,
        validation_keywords=["宏观", "政策", "长期", "价值"],
        description="验证宏观经济关联分析能力"
    ),
    TestPrompt(
        id=40,
        difficulty="hard",
        category="复杂报告",
        query="为一个100万的投资组合设计配置方案，考虑行业均衡、风险分散、预期收益，并说明逻辑",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["配置", "风险", "收益", "逻辑"],
        description="验证投资组合设计能力"
    ),
    TestPrompt(
        id=41,
        difficulty="hard",
        category="复杂报告",
        query="分析中国制造业转型升级中的投资机遇，从产业升级、技术进步、成本优化等角度分析",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["转型", "升级", "机遇", "分析"],
        description="验证战略性产业分析能力"
    ),
    TestPrompt(
        id=42,
        difficulty="hard",
        category="复杂报告",
        query="评估一个科技初创公司的IPO估值合理性，需要对标哪些企业，预期何种增长才能支撑估值",
        expected_output_type="[REPORT]",
        expected_steps=6,
        validation_keywords=["IPO", "估值", "对标", "增长"],
        description="验证估值合理性判断能力"
    ),
    TestPrompt(
        id=43,
        difficulty="hard",
        category="复杂报告",
        query="分析碳中和政策对能源、电力、新材料等多个行业的长期影响，并找出最大受益者",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["碳中和", "政策", "行业", "受益"],
        description="验证政策影响跨行业分析能力"
    ),
    TestPrompt(
        id=44,
        difficulty="hard",
        category="复杂报告",
        query="设计一个量化投资策略：基于PE、PB、股息率、动量因子的多因子模型，回测效果如何？",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["量化", "因子", "模型", "回测"],
        description="验证量化分析和模型设计能力"
    ),
    TestPrompt(
        id=45,
        difficulty="hard",
        category="复杂报告",
        query="分析全球供应链重构对中国上市公司的影响，涉及哪些行业，哪些公司是赢家/输家？",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["供应链", "全球", "赢家"],
        description="验证地缘政治经济分析能力"
    ),
    TestPrompt(
        id=46,
        difficulty="hard",
        category="复杂报告",
        query="对比美国纳斯达克和中国科创板的科技企业估值水平，差异来源和未来趋势如何？",
        expected_output_type="[REPORT]",
        expected_steps=6,
        validation_keywords=["纳斯达克", "科创板", "估值", "对比"],
        description="验证国际市场对标能力"
    ),
    TestPrompt(
        id=47,
        difficulty="hard",
        category="复杂报告",
        query="分析消费金融行业的风险，包括政策风险、信用风险、市场风险，如何防范？",
        expected_output_type="[REPORT]",
        expected_steps=6,
        validation_keywords=["风险", "防范", "消费金融"],
        description="验证风险识别和防范分析能力"
    ),
    TestPrompt(
        id=48,
        difficulty="hard",
        category="复杂报告",
        query="设计一个关于医药行业的配置策略：如何在医疗控费和行业增长之间找到平衡？",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["医药", "配置", "控费"],
        description="验证行业特定策略设计能力"
    ),
    TestPrompt(
        id=49,
        difficulty="hard",
        category="复杂报告",
        query="分析一个黑天鹅事件（如疫情、地震、金融危机）对股票市场的长期影响，恢复周期通常多长？",
        expected_output_type="[REPORT]",
        expected_steps=6,
        validation_keywords=["黑天鹅", "事件", "影响", "恢复"],
        description="验证危机分析和恢复逻辑能力"
    ),
    TestPrompt(
        id=50,
        difficulty="hard",
        category="复杂报告",
        query="设计一个5年期的投资主题组合：基于人口老龄化、城市化、技术升级等大趋势，如何选股配置？",
        expected_output_type="[REPORT]",
        expected_steps=7,
        validation_keywords=["主题", "趋势", "5年", "配置"],
        description="验证长期主题投资设计能力"
    ),
]

# 合并所有 Prompt
ALL_PROMPTS = EASY_PROMPTS + MEDIUM_PROMPTS + HARD_PROMPTS

# ============================================================================
# 批处理脚本
# ============================================================================

def save_to_jsonl(prompts: List[TestPrompt], output_file: str):
    """保存为 JSONL 格式"""
    with open(output_file, "w", encoding="utf-8") as f:
        for p in prompts:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    print(f"✅ 已保存 {len(prompts)} 个 prompt 到 {output_file}")


def print_summary():
    """打印摘要"""
    print("\n" + "="*70)
    print("【ASA 项目核心能力验证 Prompt 集】")
    print("="*70)
    print(f"\n总计：{len(ALL_PROMPTS)} 个 Prompt")
    print(f"  - Easy（简单）：{len(EASY_PROMPTS)} 个")
    print(f"  - Medium（中等）：{len(MEDIUM_PROMPTS)} 个")
    print(f"  - Hard（困难）：{len(HARD_PROMPTS)} 个")
    
    print(f"\n覆盖的核心能力：")
    categories = set(p.category for p in ALL_PROMPTS)
    for cat in sorted(categories):
        count = sum(1 for p in ALL_PROMPTS if p.category == cat)
        print(f"  - {cat}：{count} 个")
    
    print(f"\n期望输出类型：")
    output_types = set(p.expected_output_type for p in ALL_PROMPTS)
    for ot in sorted(output_types):
        count = sum(1 for p in ALL_PROMPTS if p.expected_output_type == ot)
        print(f"  - {ot}：{count} 个")
    
    print("\n"+"="*70)


def generate_batch_script(output_file: str = "batch_test_script.py"):
    """生成可执行的批处理脚本"""
    script = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA 项目批量测试脚本 - 自动生成
运行方式：python batch_test_script.py
"""

import json
import time
import uuid
from langchain_core.messages import HumanMessage
from multi_agent import multi_agent_app, get_initial_state

# 导入 50 个 Prompt
from test_prompts_50 import ALL_PROMPTS

def batch_test(max_workers: int = 1, output_file: str = "batch_results.jsonl"):
    """
    批量测试
    
    Args:
        max_workers: 并发数（建议 1-3，避免 API 限流）
        output_file: 输出文件
    """
    
    results = []
    start_time = time.time()
    
    print(f"\\n开始批量测试 {len(ALL_PROMPTS)} 个 prompt...")
    print(f"预估耗时：{len(ALL_PROMPTS) * 8 / 60:.0f} 分钟（假设每个 8 秒）\\n")
    
    for idx, prompt in enumerate(ALL_PROMPTS):
        print(f"[{idx+1}/{len(ALL_PROMPTS)}] {prompt.category} - {prompt.query[:40]}...", end=" ")
        
        thread_id = f"batch_test_{prompt.id}_{int(time.time())}"
        config = {"configurable": {"thread_id": thread_id}}
        
        initial_state = get_initial_state()
        initial_state["messages"] = [HumanMessage(content=prompt.query)]
        
        try:
            # 执行
            query_start = time.time()
            result = multi_agent_app.invoke(initial_state, config)
            query_time = time.time() - query_start
            
            # 提取最终响应
            final_msg = result.get("messages", [])[-1]
            response = final_msg.content if hasattr(final_msg, 'content') else str(final_msg)
            
            # 简单的输出类型检测
            detected_type = "[DATA]" if "[DATA]" in response else (
                "[CHART]" if "[CHART]" in response or "图" in response else (
                "[REPORT]" if len(response) > 200 else (
                "[REJECT]" if "无法" in response or "不存在" in response else "[OTHER]"
            )))
            
            results.append({
                "id": prompt.id,
                "query": prompt.query,
                "difficulty": prompt.difficulty,
                "category": prompt.category,
                "expected_type": prompt.expected_output_type,
                "detected_type": detected_type,
                "type_match": detected_type == prompt.expected_output_type,
                "response_length": len(response),
                "time_seconds": query_time,
                "success": True
            })
            
            print(f"✅ {query_time:.1f}s")
            
        except Exception as e:
            results.append({
                "id": prompt.id,
                "query": prompt.query,
                "difficulty": prompt.difficulty,
                "category": prompt.category,
                "error": str(e)[:100],
                "success": False,
                "time_seconds": 0
            })
            
            print(f"❌ {str(e)[:30]}...")
        
        # 休息，避免 API 限流
        time.sleep(1)
    
    # 保存结果
    with open(output_file, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\\n")
    
    # 打印摘要
    total_time = time.time() - start_time
    success_count = sum(1 for r in results if r["success"])
    
    print("\\n" + "="*70)
    print("【批量测试完成】")
    print("="*70)
    print(f"总耗时：{total_time/60:.1f} 分钟（{total_time:.0f} 秒）")
    print(f"总数：{len(results)}")
    print(f"成功：{success_count} ({success_count/len(results):.0%})")
    print(f"失败：{len(results)-success_count}")
    
    # 按难度统计
    by_difficulty = {}
    for r in results:
        diff = r.get("difficulty", "unknown")
        if diff not in by_difficulty:
            by_difficulty[diff] = {"total": 0, "success": 0}
        by_difficulty[diff]["total"] += 1
        if r["success"]:
            by_difficulty[diff]["success"] += 1
    
    print(f"\\n按难度分层：")
    for diff in ["easy", "medium", "hard"]:
        if diff in by_difficulty:
            stats = by_difficulty[diff]
            rate = stats["success"] / stats["total"]
            print(f"  {diff:8s}: {stats['success']}/{stats['total']} ({rate:.0%})")
    
    # 按输出类型统计
    type_stats = {}
    for r in results:
        if r["success"]:
            t = r.get("detected_type", "unknown")
            if t not in type_stats:
                type_stats[t] = 0
            type_stats[t] += 1
    
    print(f"\\n按输出类型分布：")
    for t in sorted(type_stats.keys()):
        print(f"  {t:12s}: {type_stats[t]} 个")
    
    print(f"\\n结果已保存到 {output_file}")
    print("="*70)


if __name__ == "__main__":
    batch_test()
'''
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(script)
    
    print(f"✅ 批处理脚本已生成：{output_file}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="test_prompts_50.jsonl", help="输出文件")
    parser.add_argument("--generate-script", action="store_true", help="生成批处理脚本")
    parser.add_argument("--summary", action="store_true", help="打印摘要")
    
    args = parser.parse_args()
    
    # 保存为 JSONL
    save_to_jsonl(ALL_PROMPTS, args.output)
    
    # 打印摘要
    print_summary()
    
    # 生成批处理脚本
    if args.generate_script:
        generate_batch_script()
    
    print(f"\n💡 使用方式：")
    print(f"  1. 保存为 JSONL: python test_prompts_50.py --output prompts.jsonl")
    print(f"  2. 生成脚本: python test_prompts_50.py --generate-script")
    print(f"  3. 运行批测试: python batch_test_script.py")
