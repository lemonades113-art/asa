#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA系统30+场景压测脚本
功能：
1. 生成30+个符合ASA系统的金融问答prompt
2. 调用Tushare API获取真实数据
3. 调用LLM API生成答案
4. 记录执行日志和性能指标
5. 生成压测报告

运行方式：
    python stress_test_30_questions.py --output stress_test_results.json
"""

import json
import os
import sys
import time
import asyncio
import aiohttp
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 尝试导入ASA系统组件
try:
    from lib import KernelManager, HybridRetriever, StatefulPythonKernel
    from multi_agent import create_workflow
    ASA_AVAILABLE = True
except ImportError as e:
    print(f"[警告] ASA组件导入失败: {e}")
    ASA_AVAILABLE = False


@dataclass
class TestQuestion:
    """测试问题数据结构"""
    id: str
    category: str
    difficulty: str
    question: str
    expected_tools: List[str]
    expected_output_type: str
    validation_keywords: List[str]
    description: str


@dataclass
class TestResult:
    """测试结果数据结构"""
    question_id: str
    question: str
    category: str
    difficulty: str
    status: str  # success, failed, timeout
    start_time: str
    end_time: str
    duration_ms: int
    answer: str
    logs: List[str]
    tushare_calls: List[Dict]
    llm_calls: List[Dict]
    error: Optional[str] = None


# ============================================================================
# 30+个ASA系统测试问题（覆盖Easy/Medium/Hard三个难度）
# ============================================================================

TEST_QUESTIONS = [
    # ========== Easy (10个) - 基础单查询 ==========
    TestQuestion(
        id="Q001",
        category="单查询-股息率",
        difficulty="Easy",
        question="查询中国平安(601318)的最新股息率是多少？",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["股息率", "dv_ttm", "601318"],
        description="基础股息率查询，验证Tushare daily_basic接口调用"
    ),
    TestQuestion(
        id="Q002",
        category="单查询-市盈率",
        difficulty="Easy",
        question="贵州茅台(600519)当前的市盈率PE是多少？",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["市盈率", "pe", "600519"],
        description="基础市盈率查询"
    ),
    TestQuestion(
        id="Q003",
        category="单查询-股价",
        difficulty="Easy",
        question="查询五粮液(000858)的最新收盘价",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["收盘价", "close", "000858"],
        description="基础股价查询"
    ),
    TestQuestion(
        id="Q004",
        category="单查询-市值",
        difficulty="Easy",
        question="比亚迪(002594)目前的总市值是多少？",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["总市值", "total_mv", "002594"],
        description="基础市值查询"
    ),
    TestQuestion(
        id="Q005",
        category="单查询-ROE",
        difficulty="Easy",
        question="查询宁德时代(300750)的ROE（净资产收益率）",
        expected_tools=["fina_indicator"],
        expected_output_type="[DATA]",
        validation_keywords=["ROE", "roe", "300750"],
        description="基础ROE查询"
    ),
    TestQuestion(
        id="Q006",
        category="单查询-营收",
        difficulty="Easy",
        question="美的集团(000333)2024年三季度营业收入是多少？",
        expected_tools=["income"],
        expected_output_type="[DATA]",
        validation_keywords=["营业收入", "total_revenue", "000333"],
        description="基础营收查询"
    ),
    TestQuestion(
        id="Q007",
        category="单查询-净利润",
        difficulty="Easy",
        question="查询招商银行(600036)2024年三季度净利润",
        expected_tools=["income"],
        expected_output_type="[DATA]",
        validation_keywords=["净利润", "net_profit", "600036"],
        description="基础净利润查询"
    ),
    TestQuestion(
        id="Q008",
        category="单查询-毛利率",
        difficulty="Easy",
        question="恒瑞医药(600276)的毛利率是多少？",
        expected_tools=["fina_indicator"],
        expected_output_type="[DATA]",
        validation_keywords=["毛利率", "grossprofit_margin", "600276"],
        description="基础毛利率查询"
    ),
    TestQuestion(
        id="Q009",
        category="单查询-港股",
        difficulty="Easy",
        question="查询腾讯控股(00700.HK)的港股市值",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["港股", "00700", "total_mv"],
        description="港股查询测试"
    ),
    TestQuestion(
        id="Q010",
        category="单查询-ETF",
        difficulty="Easy",
        question="沪深300ETF(510300)的最新净值是多少？",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["ETF", "510300", "close"],
        description="ETF查询测试"
    ),
    
    # ========== Medium (15个) - 多指标/对比/计算 ==========
    TestQuestion(
        id="Q011",
        category="多指标-综合",
        difficulty="Medium",
        question="查询工商银行(601398)的市盈率、市净率和股息率",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["市盈率", "市净率", "股息率", "601398"],
        description="多指标批量查询"
    ),
    TestQuestion(
        id="Q012",
        category="对比-双股",
        difficulty="Medium",
        question="对比贵州茅台(600519)和五粮液(000858)的PE和PB估值水平",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["对比", "600519", "000858", "PE", "PB"],
        description="双股对比分析"
    ),
    TestQuestion(
        id="Q013",
        category="对比-多股",
        difficulty="Medium",
        question="对比白酒行业三大龙头（茅台、五粮液、泸州老窖）的ROE和毛利率",
        expected_tools=["daily_basic", "fina_indicator"],
        expected_output_type="[DATA]",
        validation_keywords=["对比", "ROE", "毛利率", "白酒"],
        description="多股行业对比"
    ),
    TestQuestion(
        id="Q014",
        category="计算-财务指标",
        difficulty="Medium",
        question="计算科大讯飞(002230)2024年三季度的净利率是多少？",
        expected_tools=["income"],
        expected_output_type="[DATA]",
        validation_keywords=["净利率", "net_profit", "total_revenue", "002230"],
        description="财务指标计算"
    ),
    TestQuestion(
        id="Q015",
        category="历史-趋势",
        difficulty="Medium",
        question="查询中国平安过去5年的分红数据（2020-2024）",
        expected_tools=["dividend"],
        expected_output_type="[DATA]",
        validation_keywords=["分红", "dividend", "历史", "601318"],
        description="历史分红数据查询"
    ),
    TestQuestion(
        id="Q016",
        category="历史-财务",
        difficulty="Medium",
        question="分析海康威视(002415)近3年的营收增长趋势",
        expected_tools=["income"],
        expected_output_type="[REPORT]",
        validation_keywords=["营收", "增长", "趋势", "002415"],
        description="历史财务趋势分析"
    ),
    TestQuestion(
        id="Q017",
        category="估值-分析",
        difficulty="Medium",
        question="分析招商银行(600036)当前的估值水平是否合理？",
        expected_tools=["daily_basic", "fina_indicator"],
        expected_output_type="[REPORT]",
        validation_keywords=["估值", "PE", "PB", "合理", "600036"],
        description="估值合理性分析"
    ),
    TestQuestion(
        id="Q018",
        category="行业-排名",
        difficulty="Medium",
        question="银行板块中股息率最高的5只股票是哪些？",
        expected_tools=["daily_basic", "stock_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["银行", "股息率", "排名", "top5"],
        description="行业排名查询"
    ),
    TestQuestion(
        id="Q019",
        category="财务-多维度",
        difficulty="Medium",
        question="分析比亚迪(002594)的盈利能力（毛利率、净利率、ROE）",
        expected_tools=["fina_indicator", "income"],
        expected_output_type="[REPORT]",
        validation_keywords=["盈利", "毛利率", "净利率", "ROE", "002594"],
        description="多维度盈利能力分析"
    ),
    TestQuestion(
        id="Q020",
        category="投资-建议",
        difficulty="Medium",
        question="基于股息率和PE，分析长江电力(600900)是否适合价值投资？",
        expected_tools=["daily_basic"],
        expected_output_type="[REPORT]",
        validation_keywords=["股息率", "PE", "价值投资", "600900"],
        description="价值投资分析"
    ),
    TestQuestion(
        id="Q021",
        category="对比-港股A股",
        difficulty="Medium",
        question="对比中国平安A股(601318)和港股(02318.HK)的估值差异",
        expected_tools=["daily_basic"],
        expected_output_type="[DATA]",
        validation_keywords=["A股", "港股", "估值差异", "601318", "02318"],
        description="AH股估值对比"
    ),
    TestQuestion(
        id="Q022",
        category="计算-收益率",
        difficulty="Medium",
        question="如果一年前买入宁德时代(300750)，现在的收益率是多少？",
        expected_tools=["daily"],
        expected_output_type="[DATA]",
        validation_keywords=[["收益率", "一年前", "300750"]],
        description="历史收益率计算"
    ),
    TestQuestion(
        id="Q023",
        category="财务-质量",
        difficulty="Medium",
        question="分析格力电器(000651)的现金流状况",
        expected_tools=["cashflow"],
        expected_output_type="[REPORT]",
        validation_keywords=["现金流", "经营", "投资", "000651"],
        description="现金流分析"
    ),
    TestQuestion(
        id="Q024",
        category="分红-策略",
        difficulty="Medium",
        question="哪些股票的股息率超过5%且连续3年分红？",
        expected_tools=["daily_basic", "dividend"],
        expected_output_type="[DATA]",
        validation_keywords=["股息率", "5%", "连续分红", "高分红"],
        description="高分红策略筛选"
    ),
    TestQuestion(
        id="Q025",
        category="综合-画像",
        difficulty="Medium",
        question="生成迈瑞医疗(300760)的投资画像（估值、盈利、成长）",
        expected_tools=["daily_basic", "fina_indicator", "income"],
        expected_output_type="[REPORT]",
        validation_keywords=["投资画像", "估值", "盈利", "成长", "300760"],
        description="投资画像生成"
    ),
    
    # ========== Hard (10个) - 复杂推理/多步骤/报告 ==========
    TestQuestion(
        id="Q026",
        category="复杂-投资决策",
        difficulty="Hard",
        question="对比分析茅台(600519)、五粮液(000858)、泸州老窖(000568)三只白酒股，哪只最值得投资？请从估值、盈利能力、成长性三个维度分析。",
        expected_tools=["daily_basic", "fina_indicator", "income"],
        expected_output_type="[REPORT]",
        validation_keywords=["对比", "估值", "盈利", "成长", "投资建议"],
        description="多维度投资决策分析"
    ),
    TestQuestion(
        id="Q027",
        category="复杂-行业分析",
        difficulty="Hard",
        question="分析新能源行业头部公司（比亚迪、宁德时代、隆基绿能）的竞争力对比",
        expected_tools=["daily_basic", "fina_indicator", "income"],
        expected_output_type="[REPORT]",
        validation_keywords=["新能源", "竞争力", "对比", "行业分析"],
        description="行业竞争力分析"
    ),
    TestQuestion(
        id="Q028",
        category="复杂-财务诊断",
        difficulty="Hard",
        question="对恒瑞医药(600276)进行全面的财务健康诊断，包括偿债能力、营运能力、盈利能力",
        expected_tools=["fina_indicator", "balancesheet", "income"],
        expected_output_type="[REPORT]",
        validation_keywords=["财务诊断", "偿债", "营运", "盈利", "600276"],
        description="全面财务诊断"
    ),
    TestQuestion(
        id="Q029",
        category="复杂-策略回测",
        difficulty="Hard",
        question="如果采用'股息率>4%且PE<15'的选股策略，在银行股中能选出哪些标的？策略有效性如何？",
        expected_tools=["daily_basic", "stock_basic"],
        expected_output_type="[REPORT]",
        validation_keywords=["策略", "股息率", "PE", "选股", "银行"],
        description="量化策略回测分析"
    ),
    TestQuestion(
        id="Q030",
        category="复杂-风险评估",
        difficulty="Hard",
        question="分析万科A(000002)当前的投资风险（财务风险、行业风险、估值风险）",
        expected_tools=["daily_basic", "fina_indicator", "balancesheet"],
        expected_output_type="[REPORT]",
        validation_keywords=[["风险", "财务", "行业", "估值", "000002"]],
        description="投资风险评估"
    ),
    TestQuestion(
        id="Q031",
        category="报告-深度",
        difficulty="Hard",
        question="生成一份关于招商银行(600036)的深度研究报告，包含公司概况、财务分析、估值分析、投资建议",
        expected_tools=["daily_basic", "fina_indicator", "income", "balancesheet"],
        expected_output_type="[REPORT]",
        validation_keywords=["研究报告", "财务分析", "估值", "投资建议", "600036"],
        description="深度研究报告生成"
    ),
    TestQuestion(
        id="Q032",
        category="推理-预测",
        difficulty="Hard",
        question="基于历史财务数据，预测贵州茅台2025年的净利润增长趋势",
        expected_tools=["income", "fina_indicator"],
        expected_output_type="[REPORT]",
        validation_keywords=["预测", "净利润", "增长", "趋势", "600519"],
        description="趋势预测分析"
    ),
    TestQuestion(
        id="Q033",
        category="复杂-组合",
        difficulty="Hard",
        question="构建一个保守型高股息组合（5只股票），要求：股息率>4%、PE<20、市值>500亿",
        expected_tools=["daily_basic", "stock_basic"],
        expected_output_type="[REPORT]",
        validation_keywords=["组合", "高股息", "保守", "股息率", "PE"],
        description="投资组合构建"
    ),
    TestQuestion(
        id="Q034",
        category="复杂-事件",
        difficulty="Hard",
        question="分析某股票分红送股后的填权概率（以中国平安历史分红为例）",
        expected_tools=["dividend", "daily"],
        expected_output_type="[REPORT]",
        validation_keywords=["分红", "送股", "填权", "概率", "601318"],
        description="事件驱动分析"
    ),
    TestQuestion(
        id="Q035",
        category="复杂-宏观",
        difficulty="Hard",
        question="分析当前银行板块的整体估值水平与历史分位，判断是否具有配置价值",
        expected_tools=["daily_basic", "stock_basic"],
        expected_output_type="[REPORT]",
        validation_keywords=["银行板块", "估值", "历史分位", "配置价值"],
        description="板块配置分析"
    ),
]


class StressTester:
    """压测执行器"""
    
    def __init__(self, max_workers: int = 3, timeout: int = 120):
        self.max_workers = max_workers
        self.timeout = timeout
        self.results: List[TestResult] = []
        
        # 从conf.py加载配置
        try:
            import conf
            self.tushare_token = conf.tushare_token
            self.llm_api_key = conf.api_key
            self.base_url = conf.base_url
        except ImportError:
            # 回退到环境变量
            self.tushare_token = os.getenv("TUSHARE_TOKEN", "")
            self.llm_api_key = os.getenv("DASHSCOPE_API_KEY", "")
            self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        
    def _call_tushare(self, api_name: str, params: Dict) -> Dict:
        """调用Tushare API"""
        import tushare as ts
        try:
            # 设置token
            ts.set_token(self.tushare_token)
            pro = ts.pro_api()
            func = getattr(pro, api_name)
            df = func(**params)
            return {
                "success": True,
                "data": df.to_dict('records') if not df.empty else [],
                "count": len(df)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    def _call_llm(self, prompt: str, model: str = "qwen-plus") -> Dict:
        """调用LLM API - 使用OpenAI兼容接口"""
        try:
            from openai import OpenAI
            
            client = OpenAI(
                api_key=self.llm_api_key,
                base_url=self.base_url
            )
            
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            
            return {
                "success": True,
                "content": response.choices[0].message.content,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                } if response.usage else {}
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    def _extract_stock_code(self, question: str) -> Optional[str]:
        """从问题中提取股票代码"""
        import re
        # 匹配6位数字代码
        match = re.search(r'\b(\d{6})', question)
        if match:
            return match.group(1)
        # 匹配港股代码
        match = re.search(r'(\d{5})\.HK', question, re.IGNORECASE)
        if match:
            return match.group(1) + ".HK"
        return None
    
    def _execute_single_test(self, question: TestQuestion) -> TestResult:
        """执行单个测试"""
        start_time = datetime.now()
        logs = []
        tushare_calls = []
        llm_calls = []
        
        try:
            logs.append(f"[{start_time.isoformat()}] 开始测试: {question.id}")
            logs.append(f"问题: {question.question}")
            
            # 提取股票代码
            stock_code = self._extract_stock_code(question.question)
            logs.append(f"提取股票代码: {stock_code}")
            
            # 模拟ASA系统执行流程
            # Step 1: Supervisor分析（调用LLM）
            supervisor_prompt = f"""你是一个Supervisor智能体，负责分析用户查询并规划任务。
            
用户查询: {question.question}
提取的股票代码: {stock_code}

请分析：
1. 用户需要什么类型的数据？
2. 需要调用哪些Tushare接口？{question.expected_tools}
3. 任务复杂度如何？{question.difficulty}

输出任务规划（JSON格式）。"""
            
            supervisor_result = self._call_llm(supervisor_prompt, model="qwen-turbo")
            llm_calls.append({
                "step": "supervisor",
                "model": "qwen-turbo",
                "success": supervisor_result["success"],
                "timestamp": datetime.now().isoformat()
            })
            logs.append(f"Supervisor分析完成: {supervisor_result['success']}")
            
            # Step 2: 调用Tushare获取数据
            if stock_code and not stock_code.endswith(".HK"):
                # 查询daily_basic
                tushare_result = self._call_tushare("daily_basic", {
                    "ts_code": stock_code + ".SH" if stock_code.startswith("6") else stock_code + ".SZ",
                    "limit": 1
                })
                tushare_calls.append({
                    "api": "daily_basic",
                    "params": {"ts_code": stock_code},
                    "success": tushare_result["success"],
                    "timestamp": datetime.now().isoformat()
                })
                logs.append(f"Tushare调用完成: {tushare_result['success']}")
                
                # 如果需要财务指标
                if "fina_indicator" in question.expected_tools:
                    fina_result = self._call_tushare("fina_indicator", {
                        "ts_code": stock_code + ".SH" if stock_code.startswith("6") else stock_code + ".SZ",
                        "limit": 4
                    })
                    tushare_calls.append({
                        "api": "fina_indicator",
                        "success": fina_result["success"],
                        "timestamp": datetime.now().isoformat()
                    })
            
            # Step 3: Coder生成代码/分析（调用LLM）
            coder_prompt = f"""你是一个Coder智能体，负责生成数据分析代码。

用户查询: {question.question}
股票代码: {stock_code}

请生成Python代码来分析这个问题，或直接用自然语言回答（如果是简单查询）。
要求输出格式包含[META]和[DATA]标签。"""
            
            coder_result = self._call_llm(coder_prompt, model="qwen-plus")
            llm_calls.append({
                "step": "coder",
                "model": "qwen-plus",
                "success": coder_result["success"],
                "timestamp": datetime.now().isoformat()
            })
            logs.append(f"Coder执行完成: {coder_result['success']}")
            
            # Step 4: Reviewer审查（调用LLM，Hard问题使用）
            if question.difficulty == "Hard":
                reviewer_prompt = f"""你是一个Reviewer智能体，负责审查金融分析结果。

原始查询: {question.question}
Coder输出: {coder_result.get('content', '')[:500]}

请审查：
1. 数据是否准确？
2. 分析逻辑是否合理？
3. 输出格式是否规范？

输出审查报告。"""
                
                reviewer_result = self._call_llm(reviewer_prompt, model="qwen-plus")
                llm_calls.append({
                    "step": "reviewer",
                    "model": "qwen-plus",
                    "success": reviewer_result["success"],
                    "timestamp": datetime.now().isoformat()
                })
                logs.append(f"Reviewer审查完成: {reviewer_result['success']}")
            
            # 计算执行时间
            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            # 生成答案
            answer = coder_result.get("content", "")
            if question.difficulty == "Hard" and 'reviewer_result' in locals():
                answer += "\n\n[Reviewer审查]\n" + reviewer_result.get("content", "")[:300]
            
            logs.append(f"[{end_time.isoformat()}] 测试完成，耗时: {duration_ms}ms")
            
            return TestResult(
                question_id=question.id,
                question=question.question,
                category=question.category,
                difficulty=question.difficulty,
                status="success",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                duration_ms=duration_ms,
                answer=answer[:2000],  # 限制长度
                logs=logs,
                tushare_calls=tushare_calls,
                llm_calls=llm_calls
            )
            
        except Exception as e:
            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            logs.append(f"[ERROR] {str(e)}")
            logs.append(traceback.format_exc())
            
            return TestResult(
                question_id=question.id,
                question=question.question,
                category=question.category,
                difficulty=question.difficulty,
                status="failed",
                start_time=start_time.isoformat(),
                end_time=end_time.isoformat(),
                duration_ms=duration_ms,
                answer="",
                logs=logs,
                tushare_calls=tushare_calls,
                llm_calls=llm_calls,
                error=str(e)
            )
    
    def run_stress_test(self, questions: List[TestQuestion] = None) -> Dict:
        """执行压测"""
        if questions is None:
            questions = TEST_QUESTIONS
        
        print(f"\n{'='*70}")
        print("ASA系统30+场景压测")
        print(f"{'='*70}")
        print(f"测试时间: {datetime.now().isoformat()}")
        print(f"测试问题数: {len(questions)}")
        print(f"并发数: {self.max_workers}")
        print(f"超时时间: {self.timeout}s")
        print(f"{'='*70}\n")
        
        # 检查API配置
        if not self.tushare_token:
            print("[警告] TUSHARE_TOKEN未设置，Tushare调用将失败")
        if not self.llm_api_key:
            print("[警告] DASHSCOPE_API_KEY未设置，LLM调用将失败")
        
        # 串行执行（避免API限流）
        results = []
        for i, question in enumerate(questions, 1):
            print(f"\n[{i}/{len(questions)}] 测试 {question.id} - {question.category}")
            print(f"问题: {question.question[:60]}...")
            
            result = self._execute_single_test(question)
            results.append(result)
            
            status_symbol = "[OK]" if result.status == "success" else "[FAIL]"
            print(f"{status_symbol} 状态: {result.status}, 耗时: {result.duration_ms}ms")
            
            # API调用统计
            tushare_ok = sum(1 for c in result.tushare_calls if c.get("success"))
            llm_ok = sum(1 for c in result.llm_calls if c.get("success"))
            print(f"    Tushare: {tushare_ok}/{len(result.tushare_calls)}, LLM: {llm_ok}/{len(result.llm_calls)}")
            
            # 短暂延迟避免限流
            time.sleep(0.5)
        
        self.results = results
        return self._generate_report()
    
    def _generate_report(self) -> Dict:
        """生成压测报告"""
        total = len(self.results)
        success = sum(1 for r in self.results if r.status == "success")
        failed = sum(1 for r in self.results if r.status == "failed")
        
        # 按难度统计
        easy_total = sum(1 for r in self.results if r.difficulty == "Easy")
        easy_success = sum(1 for r in self.results if r.difficulty == "Easy" and r.status == "success")
        medium_total = sum(1 for r in self.results if r.difficulty == "Medium")
        medium_success = sum(1 for r in self.results if r.difficulty == "Medium" and r.status == "success")
        hard_total = sum(1 for r in self.results if r.difficulty == "Hard")
        hard_success = sum(1 for r in self.results if r.difficulty == "Hard" and r.status == "success")
        
        # 耗时统计
        durations = [r.duration_ms for r in self.results]
        avg_duration = sum(durations) / len(durations) if durations else 0
        max_duration = max(durations) if durations else 0
        min_duration = min(durations) if durations else 0
        
        # API调用统计
        total_tushare_calls = sum(len(r.tushare_calls) for r in self.results)
        total_llm_calls = sum(len(r.llm_calls) for r in self.results)
        
        report = {
            "metadata": {
                "test_name": "ASA系统30+场景压测",
                "timestamp": datetime.now().isoformat(),
                "total_questions": total,
                "concurrency": self.max_workers,
                "timeout_seconds": self.timeout
            },
            "summary": {
                "total": total,
                "success": success,
                "failed": failed,
                "success_rate": f"{success/total*100:.1f}%" if total > 0 else "0%",
                "avg_duration_ms": int(avg_duration),
                "max_duration_ms": max_duration,
                "min_duration_ms": min_duration,
                "total_tushare_calls": total_tushare_calls,
                "total_llm_calls": total_llm_calls
            },
            "by_difficulty": {
                "Easy": {
                    "total": easy_total,
                    "success": easy_success,
                    "rate": f"{easy_success/easy_total*100:.1f}%" if easy_total > 0 else "0%"
                },
                "Medium": {
                    "total": medium_total,
                    "success": medium_success,
                    "rate": f"{medium_success/medium_total*100:.1f}%" if medium_total > 0 else "0%"
                },
                "Hard": {
                    "total": hard_total,
                    "success": hard_success,
                    "rate": f"{hard_success/hard_total*100:.1f}%" if hard_total > 0 else "0%"
                }
            },
            "results": [asdict(r) for r in self.results]
        }
        
        return report


def print_report(report: Dict):
    """打印报告"""
    print("\n" + "="*70)
    print("压测报告摘要")
    print("="*70)
    
    summary = report["summary"]
    print(f"\n总体统计:")
    print(f"  总问题数: {summary['total']}")
    print(f"  成功: {summary['success']}")
    print(f"  失败: {summary['failed']}")
    print(f"  成功率: {summary['success_rate']}")
    print(f"  平均耗时: {summary['avg_duration_ms']}ms")
    print(f"  最大耗时: {summary['max_duration_ms']}ms")
    print(f"  最小耗时: {summary['min_duration_ms']}ms")
    print(f"  Tushare调用: {summary['total_tushare_calls']}次")
    print(f"  LLM调用: {summary['total_llm_calls']}次")
    
    print(f"\n按难度统计:")
    for diff, stats in report["by_difficulty"].items():
        print(f"  {diff}: {stats['success']}/{stats['total']} ({stats['rate']})")
    
    # 失败详情
    failed_results = [r for r in report["results"] if r["status"] == "failed"]
    if failed_results:
        print(f"\n失败详情:")
        for r in failed_results:
            print(f"  [{r['question_id']}] {r['category']}")
            print(f"    错误: {r.get('error', 'Unknown')[:100]}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ASA系统30+场景压测")
    parser.add_argument("--output", "-o", default=None, help="输出文件路径")
    parser.add_argument("--workers", "-w", type=int, default=1, help="并发数(默认1)")
    parser.add_argument("--timeout", "-t", type=int, default=120, help="超时时间(秒)")
    parser.add_argument("--count", "-c", type=int, default=None, help="测试问题数(默认全部)")
    args = parser.parse_args()
    
    # 选择测试问题
    questions = TEST_QUESTIONS
    if args.count:
        questions = TEST_QUESTIONS[:args.count]
    
    # 执行压测
    tester = StressTester(max_workers=args.workers, timeout=args.timeout)
    report = tester.run_stress_test(questions)
    
    # 打印报告
    print_report(report)
    
    # 保存报告
    if args.output:
        output_file = args.output
    else:
        output_file = f"stress_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n详细报告已保存: {output_file}")
    
    # 生成执行日志
    log_file = f"stress_test_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("="*70 + "\n")
        f.write("ASA系统30+场景压测 - 执行日志\n")
        f.write("="*70 + "\n\n")
        
        for r in report["results"]:
            f.write(f"\n{'='*70}\n")
            f.write(f"[{r['question_id']}] {r['category']} - {r['difficulty']}\n")
            f.write(f"状态: {r['status']}, 耗时: {r['duration_ms']}ms\n")
            f.write(f"问题: {r['question']}\n")
            f.write("-"*70 + "\n")
            f.write("执行日志:\n")
            for log in r["logs"]:
                f.write(f"  {log}\n")
            if r.get("error"):
                f.write(f"\n错误: {r['error']}\n")
            f.write("-"*70 + "\n")
            f.write("Tushare调用:\n")
            for call in r["tushare_calls"]:
                f.write(f"  {call}\n")
            f.write("LLM调用:\n")
            for call in r["llm_calls"]:
                f.write(f"  {call}\n")
    
    print(f"执行日志已保存: {log_file}")


if __name__ == "__main__":
    main()
