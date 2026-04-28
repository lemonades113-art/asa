#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Evaluation - 评估脚本
实现 Pass@K 指标计算和多维度评估体系

【研究价值】
- 算法岗标准配置：定量评估系统性能
- 体现研究严谨性
- 支持多维度指标（Execution Accuracy, Semantic Similarity, etc.）

【评估指标】
1. Pass@K: K次尝试内成功的比例
2. Execution Accuracy: 代码能否成功执行
3. Data Completeness: 数据完整性（是否有 [DATA] 输出）
4. Hallucination Rate: 幻觉率
5. Latency: 响应延迟
"""

import json
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Callable, Any
from dataclasses import dataclass, field
import re

# 尝试导入 OpenAI（如果没有安装，使用规则评估）
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("[Warning] openai not installed. LLM-as-Judge will be unavailable.")


# =============================================================================
# 1. 测试用例定义
# =============================================================================

@dataclass
class TestCase:
    """测试用例"""
    query: str  # 用户查询
    expected_output_pattern: Optional[str] = None  # 期望输出的正则模式
    expected_data_keys: Optional[List[str]] = None  # 期望的数据字段
    difficulty: str = "medium"  # easy/medium/hard
    category: str = "general"  # 类别：stock_query/financial_analysis/chart/report
    timeout: int = 60  # 超时时间（秒）
    
    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "expected_output_pattern": self.expected_output_pattern,
            "expected_data_keys": self.expected_data_keys,
            "difficulty": self.difficulty,
            "category": self.category,
            "timeout": self.timeout
        }


# 金融领域的 Golden Test Cases
GOLDEN_TEST_CASES = [
    # === Easy: 简单单一查询 ===
    TestCase(
        query="查询贵州茅台的股息率",
        expected_output_pattern=r"\[DATA\].*股息率|dv_ttm",
        expected_data_keys=["股息率", "dv_ttm"],
        difficulty="easy",
        category="stock_query"
    ),
    TestCase(
        query="贵州茅台今天的收盘价是多少？",
        expected_output_pattern=r"\[DATA\].*收盘价|close",
        expected_data_keys=["收盘价", "close"],
        difficulty="easy",
        category="stock_query"
    ),
    TestCase(
        query="查询比亚迪的市值",
        expected_output_pattern=r"\[DATA\].*市值|total_mv",
        expected_data_keys=["市值", "total_mv"],
        difficulty="easy",
        category="stock_query"
    ),
    TestCase(
        query="中国平安的市盈率是多少？",
        expected_output_pattern=r"\[DATA\].*市盈率|pe",
        expected_data_keys=["市盈率", "pe"],
        difficulty="easy",
        category="stock_query"
    ),
    TestCase(
        query="宁德时代的股票代码是什么？",
        expected_output_pattern=r"300750|宁德时代",
        difficulty="easy",
        category="stock_query"
    ),
    
    # === Medium: 多步骤查询 + 计算 ===
    TestCase(
        query="计算贵州茅台最近5年的年均净利润增长率",
        expected_output_pattern=r"\[DATA\].*增长率|growth",
        expected_data_keys=["增长率", "growth"],
        difficulty="medium",
        category="financial_analysis"
    ),
    TestCase(
        query="对比贵州茅台和五粮液的ROE",
        expected_output_pattern=r"\[DATA\].*ROE|roe",
        expected_data_keys=["ROE", "roe"],
        difficulty="medium",
        category="financial_analysis"
    ),
    TestCase(
        query="分析比亚迪最近3年的营收变化趋势",
        expected_output_pattern=r"\[DATA\].*营收|revenue",
        expected_data_keys=["营收", "revenue"],
        difficulty="medium",
        category="financial_analysis"
    ),
    TestCase(
        query="查询银行板块中股息率最高的5只股票",
        expected_output_pattern=r"\[DATA\]",
        difficulty="medium",
        category="stock_query"
    ),
    TestCase(
        query="画出贵州茅台最近一年的股价走势图",
        expected_output_pattern=r"\[CHART\]|\.png|图",
        difficulty="medium",
        category="chart"
    ),
    
    # === Hard: 复杂分析 + 报告 ===
    TestCase(
        query="对比分析贵州茅台、五粮液、泸州老窖三家公司的财务状况，给出投资建议",
        expected_output_pattern=r"\[DATA\].*\[REPORT\]|\[分析\]",
        difficulty="hard",
        category="report"
    ),
    TestCase(
        query="筛选出A股中市盈率低于20、股息率高于3%、ROE高于15%的股票",
        expected_output_pattern=r"\[DATA\]",
        difficulty="hard",
        category="stock_query"
    ),
    TestCase(
        query="分析新能源汽车板块的整体估值水平和投资价值",
        expected_output_pattern=r"\[DATA\].*\[REPORT\]|\[分析\]",
        difficulty="hard",
        category="report"
    ),
    TestCase(
        query="计算贵州茅台的自由现金流并评估其内在价值",
        expected_output_pattern=r"\[DATA\].*自由现金流|FCF",
        difficulty="hard",
        category="financial_analysis"
    ),
    TestCase(
        query="生成一份关于比亚迪的完整投研报告，包括基本面分析、技术面分析和风险提示",
        expected_output_pattern=r"\[REPORT\]|报告|分析",
        difficulty="hard",
        category="report"
    ),
]


# =============================================================================
# 2. 评估结果数据结构
# =============================================================================

@dataclass
class EvaluationResult:
    """
    单个测试用例的评估结果
    
    【RCA 增强】新增根因分析指标
    """
    test_case: TestCase
    response: str
    execution_success: bool  # 是否成功执行（无异常）
    output_match: bool  # 输出是否匹配期望
    has_data_output: bool  # 是否有 [DATA] 输出
    has_hallucination: bool  # 是否有幻觉（需人工验证）
    latency_ms: float  # 响应延迟（毫秒）
    error_msg: Optional[str] = None  # 错误信息
    attempt_number: int = 1  # 第几次尝试
    llm_judge_reason: str = ""  # ✨ LLM 评估理由
    # ✨ 【RCA 增强】根因分析指标
    rca_root_agent: str = ""  # 根因 Agent
    rca_propagation_depth: int = 0  # 传播深度
    rca_error_type: str = ""  # 根因错误类型


@dataclass
class PassAtKResult:
    """Pass@K 评估结果"""
    k: int
    pass_rate: float
    passed_cases: int
    total_cases: int


# =============================================================================
# 3.5 ✨ 【ASA 优化】根因分析器 - 不同于 RCA 模块，这里专上评测
# =============================================================================

class RootCauseAnalyzer:
    """
    ✨ 根因分析器 - 多层次诊断失败原因
    
    【设计来源】
    RAFFLES (NeurIPS 2023): Multi-level Failure Diagnosis
    ✨直接管路：Query → Tool → Memory → Reviewer
    
    【核心价值】
    - 不会能显示什么丢了（稍庅等不告诉你）
    - 看清楚稍庅转到丢的处每一步
    - 前客→后端，地形→云，整个新活幻滑
    
    【四层诊断流程】
    Layer 1: Query 分析
      - 需求提取是否丢失了那有严重幫助
      - 需求扩展是否扩彥了
    
    Layer 2: Tool 执行
      - API 是否调用了
      - 是否出现错误
    
    Layer 3: Memory 召回
      - 是否有相关记忆
      - 是否召回失败了
    
    Layer 4: Reviewer 生成
      - 是否能准确初步和轮
      - 是否均候提供了改总
    """
    
    def __init__(self):
        self.diagnosis_history: List[Dict[str, Any]] = []
    
    def diagnose_layer1_query(self, query: str, test_case: TestCase) -> Dict[str, Any]:
        """
        第1层：需求分析
        
        判断是否是需求欋客添桥
        """
        issues = []
        
        # 检查：需求提取是否丢失
        if not query or len(query) < 5:
            issues.append("Query too short or empty")
        
        # 检查：日求是否有干鼉物
        if test_case.expected_output_pattern and query.lower() not in test_case.query.lower():
            issues.append("Query mismatch with test case")
        
        return {
            "layer": 1,
            "layer_name": "Query Parsing",
            "healthy": len(issues) == 0,
            "issues": issues
        }
    
    def diagnose_layer2_tool(self, response: str, execution_success: bool, error_msg: Optional[str] = None) -> Dict[str, Any]:
        """
        第2层：工具执行
        
        判断 API 调用是否遇到了错误
        """
        issues = []
        
        # 检查：执行是否失败
        if not execution_success:
            issues.append(f"Tool execution failed: {error_msg}")
        
        # 检查：是否有错误信态串
        if "Error" in response or "error" in response or "Traceback" in response:
            issues.append("Error signature detected in response")
        
        # 检查：响应是否为空
        if not response or len(response.strip()) == 0:
            issues.append("Empty response from tool")
        
        return {
            "layer": 2,
            "layer_name": "Tool Execution",
            "healthy": len(issues) == 0,
            "issues": issues
        }
    
    def diagnose_layer3_memory(self, response: str, has_data_output: bool) -> Dict[str, Any]:
        """
        第3层：记忆召回
        
        判断是否优控了有效的记忆
        """
        issues = []
        
        # 检查：是否有 [DATA] 标记
        if not has_data_output:
            issues.append("No [DATA] marker found in response")
        
        # 检查：是否有数据需求
        if "[data]" not in response.lower() and "data" not in response.lower():
            issues.append("No structured data in response")
        
        return {
            "layer": 3,
            "layer_name": "Memory Retrieval",
            "healthy": len(issues) == 0,
            "issues": issues
        }
    
    def diagnose_layer4_reviewer(self, response: str, output_match: bool, llm_judge_reason: str = "") -> Dict[str, Any]:
        """
        第4层：Reviewer 生成
        
        判断 Reviewer 模式是否成功幻幛
        """
        issues = []
        
        # 检查：输出是否匹配
        if not output_match:
            issues.append(f"Output pattern mismatch. LLM reason: {llm_judge_reason}")
        
        # 检查：是否为空
        if not response or len(response.strip()) == 0:
            issues.append("Empty response from reviewer")
        
        return {
            "layer": 4,
            "layer_name": "Reviewer Generation",
            "healthy": len(issues) == 0,
            "issues": issues
        }
    
    def diagnose_full(self, evaluation_result: 'EvaluationResult') -> Dict[str, Any]:
        """
        推迟在示评伋结果上底一题论槻转移的是哪一段
        
        Returns:
            {
                'failure_layer': int,  # 1-4, 0 表成功
                'diagnosis': [layer1, layer2, layer3, layer4],
                'root_cause': str,
                'recommendation': str
            }
        """
        results = {
            'test_case_query': evaluation_result.test_case.query,
            'layers': []
        }
        
        # 诊断一题论槻
        l1 = self.diagnose_layer1_query(evaluation_result.test_case.query, evaluation_result.test_case)
        l2 = self.diagnose_layer2_tool(evaluation_result.response, evaluation_result.execution_success, evaluation_result.error_msg)
        l3 = self.diagnose_layer3_memory(evaluation_result.response, evaluation_result.has_data_output)
        l4 = self.diagnose_layer4_reviewer(evaluation_result.response, evaluation_result.output_match, evaluation_result.llm_judge_reason)
        
        results['layers'] = [l1, l2, l3, l4]
        
        # 判断根因：第一个不健康的层
        for layer in results['layers']:
            if not layer['healthy']:
                results['failure_layer'] = layer['layer']
                results['root_cause'] = f"{layer['layer_name']}: {', '.join(layer['issues'])}"
                break
        else:
            results['failure_layer'] = 0  # 成功
            results['root_cause'] = "All layers healthy"
        
        # 简化推荐
        if results['failure_layer'] == 1:
            results['recommendation'] = "Query Layer: Review input requirements extraction"
        elif results['failure_layer'] == 2:
            results['recommendation'] = "Tool Layer: Debug API calls and error handling"
        elif results['failure_layer'] == 3:
            results['recommendation'] = "Memory Layer: Improve data retrieval and persistence"
        elif results['failure_layer'] == 4:
            results['recommendation'] = "Reviewer Layer: Improve response generation and ranking"
        else:
            results['recommendation'] = "All systems operational"
        
        self.diagnosis_history.append(results)
        return results



class Evaluator:
    """
    评估器 - 多维度评估系统性能
    
    【核心功能】
    1. Pass@K 计算
    2. 执行准确率
    3. 数据完整性
    4. 延迟统计
    5. 按难度/类别分层统计
    6. LLM-as-Judge 深度语义评估
    7. 【RCA 增强】根因分析与传播链统计
    
    【参考论文】
    RCA 评估维度参考: "Rethinking the Evaluation of Microservice RCA with a Fault Propagation-Aware Benchmark"
    arXiv:2510.04711, FSE'26 Accepted
    """
    
    # LLM-as-Judge 模板（参考飞书 Text2SQL）
    SEMANTIC_EVALUATION_TEMPLATE = """
Evaluate if the response correctly answers the question. Consider semantic equivalence and correctness of data.

**CORRECT** criteria:
- Answers the core question accurately
- Data is relevant and complete
- No hallucinated information
- If data is provided, it should be sourced and accurate

**INCORRECT** criteria:
- Misses the core question
- Provides irrelevant or incomplete data
- Contains hallucinated data
- Contradicts the question

Question: {question}
Response: {response}

Return only "CORRECT" or "INCORRECT".
""".strip()
    
    def __init__(self, output_dir: str = "./evaluation_results", llm_api_config: Optional[Dict] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.results: List[EvaluationResult] = []
        
        # ✨ 【ASA 优化】根因分析器
        self.rca = RootCauseAnalyzer()
        
        # LLM-as-Judge 配置
        self.llm_api_config = llm_api_config or {}
        self.llm_client = None
        if OPENAI_AVAILABLE and self.llm_api_config:
            self._init_llm_client()
    
    def _init_llm_client(self):
        """
        初始化 LLM 客户端
        
        配置示例:
        llm_api_config = {
            "base_url": "http://localhost:8000/v1",
            "api_key": "EMPTY",
            "model": "QwQ-32B"
        }
        """
        try:
            if "base_url" in self.llm_api_config:
                self.llm_client = openai.Client(
                    base_url=self.llm_api_config["base_url"],
                    api_key=self.llm_api_config.get("api_key", "EMPTY")
                )
            else:
                self.llm_client = openai.Client(api_key=self.llm_api_config.get("api_key", ""))
            print("[Evaluator] LLM-as-Judge 已初始化")
        except Exception as e:
            print(f"[Evaluator] LLM 初始化失败: {e}")
            self.llm_client = None
    
    def evaluate_with_llm(self, question: str, response: str) -> Tuple[bool, str]:
        """
        【LLM-as-Judge】使用 LLM 进行深度语义评估
        
        核心思想：用强模型来评估强模型，解决规则匹配的死板问题。
        
        【参考飞书 Text2SQL】可以理解复杂的语义等价性、数据单位差异等。
        
        Args:
            question: 用户问题
            response: Agent 响应
        
        Returns:
            (是否正确, 判断理由)
        """
        # ✨【改进】：直接使用阿里云 API（已在 conf.py 中配置）
        from langchain_openai import ChatOpenAI
        
        try:
            # 使用配置中的 API Key 初始化 LLM
            llm = ChatOpenAI(
                model="qwen-plus",
                api_key=self.llm_api_config.get("api_key", ""),
                base_url=self.llm_api_config.get("base_url", "")
            )
            
            # ✨【关键 Prompt】：让 LLM 理解"语义等价"而非"字面相同"
            judge_prompt = f"""你是一个专业的金融数据验证官。

【用户问题】：{question}

【Agent 回答】：{response}

【评估标准】：
1. 数据准确性：回答的数据是否来自真实查询（是否有 [DATA] 标记）
2. 语义一致性：忽略数字精度差异（如 1410 vs 1410.5），只看逻辑是否相符
3. 单位理解：股价、市值、市盈率等单位是否对应正确
4. 幻觉识别：是否编造了数据库中不存在的数据

【判定】：
CORRECT（正确） - 语义等价，有数据源标记
INCOMPLETE（不完整） - 逻辑对但数据不全
INCORRECT（错误） - 语义不符或存在幻觉
UNCERTAIN（无法判断） - 信息不足

只回复：判定结果 + 简短理由（20字内）"""
            
            result = llm.invoke(judge_prompt)
            judgment = result.content.upper().strip()
            
            # 解析判断结果
            is_correct = "CORRECT" in judgment
            reason = judgment
            
            print(f"[LLM-Judge] {judgment}")
            return is_correct, reason
            
        except Exception as e:
            print(f"[Evaluator] LLM 评估失败（降级为规则匹配）: {e}")
            return False, f"评估失败: {str(e)}"
    
    def evaluate_single(
        self,
        agent_fn: Callable[[str], str],
        test_case: TestCase,
        attempt: int = 1,
        use_llm_eval: bool = False
    ) -> EvaluationResult:
        """
        评估单个测试用例
        
        Args:
            agent_fn: Agent 调用函数
            test_case: 测试用例
            attempt: 第几次尝试
        
        Returns:
            EvaluationResult
        """
        start_time = time.time()
        
        try:
            response = agent_fn(test_case.query)
            execution_success = True
            error_msg = None
        except Exception as e:
            response = ""
            execution_success = False
            error_msg = str(e)
        
        latency_ms = (time.time() - start_time) * 1000
        
        # 检查是否有 [DATA] 输出
        has_data_output = "[DATA]" in response or "[data]" in response.lower()
        
        # 检查输出是否匹配
        output_match = False
        llm_judge_reason = ""
        
        if execution_success:
            # 第一步：规则匹配（快速过滤）
            if test_case.expected_output_pattern:
                output_match = bool(re.search(test_case.expected_output_pattern, response, re.IGNORECASE))
            
            # 第二步：LLM-as-Judge 深度评估（规则失败或显式启用时）
            if (not output_match or use_llm_eval) and has_data_output:
                # ✨【关键】：启用 LLM 二次评估
                llm_result, llm_reason = self.evaluate_with_llm(test_case.query, response)
                if not output_match:  # 规则失败时，用 LLM 结果
                    output_match = llm_result
                    llm_judge_reason = llm_reason
        
        # 检查幻觉（简单启发式：在应该有数据时没有数据源标记）
        has_hallucination = False
        if test_case.category in ["stock_query", "financial_analysis"]:
            # 如果有数值但没有 [DATA] 标记，可能是幻觉
            has_numbers = bool(re.search(r'\d+\.\d+%|\d+亿|\d+万', response))
            if has_numbers and not has_data_output:
                has_hallucination = True
        
        result = EvaluationResult(
            test_case=test_case,
            response=response,
            execution_success=execution_success,
            output_match=output_match,
            has_data_output=has_data_output,
            has_hallucination=has_hallucination,
            latency_ms=latency_ms,
            error_msg=error_msg,
            attempt_number=attempt,
            llm_judge_reason=llm_judge_reason  # ✨【注入】LLM 评估理由
        )
        
        # ✨ 【ASA 优化】根因分析（所有失败案例）
        if not output_match or not execution_success:
            diagnosis = self.rca.diagnose_full(result)
            result.rca_root_agent = f"Layer {diagnosis['failure_layer']}"
            result.rca_error_type = diagnosis['root_cause'][:100]
            print(f"[RCA] {diagnosis['recommendation']}")
        
        return result
    
    def evaluate_pass_at_k(
        self,
        agent_fn: Callable[[str], str],
        test_cases: List[TestCase],
        k: int = 3,
        verbose: bool = True
    ) -> Tuple[PassAtKResult, List[List[EvaluationResult]]]:
        """
        计算 Pass@K 指标
        
        Args:
            agent_fn: Agent 调用函数
            test_cases: 测试用例列表
            k: 最多尝试次数
            verbose: 是否打印详情
        
        Returns:
            (PassAtKResult, 所有尝试的结果列表)
        """
        all_attempts: List[List[EvaluationResult]] = []
        passed_cases = 0
        
        for i, test_case in enumerate(test_cases):
            if verbose:
                print(f"[Eval] [{i+1}/{len(test_cases)}] {test_case.query[:50]}...")
            
            attempts = []
            passed = False
            
            for attempt in range(1, k + 1):
                result = self.evaluate_single(agent_fn, test_case, attempt)
                attempts.append(result)
                
                # 判断是否通过
                if result.execution_success and (result.output_match or result.has_data_output):
                    passed = True
                    if verbose:
                        print(f"   [PASS] Pass at attempt {attempt}")
                    break
                else:
                    if verbose:
                        print(f"   [FAIL] Attempt {attempt} failed")
            
            if passed:
                passed_cases += 1
            
            all_attempts.append(attempts)
        
        pass_rate = passed_cases / len(test_cases) if test_cases else 0
        
        result = PassAtKResult(
            k=k,
            pass_rate=pass_rate,
            passed_cases=passed_cases,
            total_cases=len(test_cases)
        )
        
        if verbose:
            print(f"\n[Eval] Pass@{k} = {pass_rate:.2%} ({passed_cases}/{len(test_cases)})")
        
        return result, all_attempts
    
    def run_full_evaluation(
        self,
        agent_fn: Callable[[str], str],
        test_cases: Optional[List[TestCase]] = None,
        k_values: List[int] = [1, 3, 5]
    ) -> Dict:
        """
        运行完整评估
        
        Args:
            agent_fn: Agent 调用函数
            test_cases: 测试用例（默认使用 GOLDEN_TEST_CASES）
            k_values: 要计算的 K 值列表
        
        Returns:
            完整评估报告
        """
        if test_cases is None:
            test_cases = GOLDEN_TEST_CASES
        
        print(f"[Eval] 开始完整评估，共 {len(test_cases)} 个测试用例")
        print(f"[Eval] K values: {k_values}")
        print("=" * 60)
        
        # 按最大 K 值运行一次，记录所有尝试
        max_k = max(k_values)
        _, all_attempts = self.evaluate_pass_at_k(agent_fn, test_cases, k=max_k, verbose=True)
        
        # 计算各个 K 值的 Pass@K
        pass_at_k_results = {}
        for k in k_values:
            passed = 0
            for attempts in all_attempts:
                # 检查前 k 次尝试是否有成功的
                for attempt in attempts[:k]:
                    if attempt.execution_success and (attempt.output_match or attempt.has_data_output):
                        passed += 1
                        break
            
            pass_rate = passed / len(test_cases) if test_cases else 0
            pass_at_k_results[f"pass@{k}"] = {
                "rate": pass_rate,
                "passed": passed,
                "total": len(test_cases)
            }
        
        # 计算其他指标
        all_first_attempts = [attempts[0] for attempts in all_attempts]
        
        execution_accuracy = sum(1 for r in all_first_attempts if r.execution_success) / len(all_first_attempts)
        data_completeness = sum(1 for r in all_first_attempts if r.has_data_output) / len(all_first_attempts)
        hallucination_rate = sum(1 for r in all_first_attempts if r.has_hallucination) / len(all_first_attempts)
        avg_latency = sum(r.latency_ms for r in all_first_attempts) / len(all_first_attempts)
        
        # 按难度分层
        by_difficulty = {}
        for diff in ["easy", "medium", "hard"]:
            diff_cases = [i for i, tc in enumerate(test_cases) if tc.difficulty == diff]
            if diff_cases:
                diff_passed = sum(1 for i in diff_cases 
                                  if any(a.execution_success and (a.output_match or a.has_data_output) 
                                        for a in all_attempts[i][:1]))
                by_difficulty[diff] = {
                    "total": len(diff_cases),
                    "passed": diff_passed,
                    "rate": diff_passed / len(diff_cases)
                }
        
        # 按类别分层
        by_category = {}
        categories = set(tc.category for tc in test_cases)
        for cat in categories:
            cat_cases = [i for i, tc in enumerate(test_cases) if tc.category == cat]
            if cat_cases:
                cat_passed = sum(1 for i in cat_cases 
                                 if any(a.execution_success and (a.output_match or a.has_data_output) 
                                       for a in all_attempts[i][:1]))
                by_category[cat] = {
                    "total": len(cat_cases),
                    "passed": cat_passed,
                    "rate": cat_passed / len(cat_cases)
                }
        
        # 汇总报告
        report = {
            "timestamp": datetime.now().isoformat(),
            "total_test_cases": len(test_cases),
            "pass_at_k": pass_at_k_results,
            "execution_accuracy": execution_accuracy,
            "data_completeness": data_completeness,
            "hallucination_rate": hallucination_rate,
            "avg_latency_ms": avg_latency,
            "by_difficulty": by_difficulty,
            "by_category": by_category,
            "details": [
                {
                    "query": test_cases[i].query,
                    "difficulty": test_cases[i].difficulty,
                    "category": test_cases[i].category,
                    "attempts": len(all_attempts[i]),
                    "final_success": any(a.execution_success and (a.output_match or a.has_data_output) 
                                        for a in all_attempts[i]),
                    "first_attempt_success": all_attempts[i][0].execution_success,
                    "latency_ms": all_attempts[i][0].latency_ms
                }
                for i in range(len(test_cases))
            ],
            # ✨ 【ASA 优化】根因分析统计
            "rca_statistics": self._aggregate_rca_statistics(all_attempts)
        }
        
        return report
    
    def _aggregate_rca_statistics(self, all_attempts: List[List[EvaluationResult]]) -> Dict:
        """
        记孕根因分析统计
        
        并计根因分析器的诊断结果
        """
        root_agent_dist = {}
        error_type_dist = {}
        layer_dist = {1: 0, 2: 0, 3: 0, 4: 0}
        total_failures = 0
        
        for attempts in all_attempts:
            for result in attempts:
                if result.rca_root_agent or result.rca_error_type:
                    total_failures += 1
                    
                    # 统计根因 Agent
                    if result.rca_root_agent:
                        root_agent_dist[result.rca_root_agent] = root_agent_dist.get(result.rca_root_agent, 0) + 1
                    
                    # 统计错误类型
                    if result.rca_error_type:
                        error_type_dist[result.rca_error_type[:30]] = error_type_dist.get(result.rca_error_type[:30], 0) + 1
                    
                    # 提取根因层数字
                    if result.rca_root_agent and "Layer" in result.rca_root_agent:
                        try:
                            layer_num = int(result.rca_root_agent.split()[-1])
                            if layer_num in layer_dist:
                                layer_dist[layer_num] += 1
                        except:
                            pass
        
        return {
            "total_failures": total_failures,
            "root_agent_distribution": root_agent_dist,
            "error_type_distribution": error_type_dist,
            "layer_distribution": layer_dist,
            "rca_diagnosis_history": self.rca.diagnosis_history[:5]  # 保留最近 5 条
        }
    
    def print_report(self, report: Dict):
        """
        打印评估报告
        
        【RCA 增强】新增根因分析统计
        """
        print("\n" + "=" * 60)
        print("[REPORT] EVALUATION REPORT")
        print("=" * 60)
        
        print(f"\n总测试用例: {report['total_test_cases']}")
        
        print("\n【Pass@K 指标】")
        for k, data in report["pass_at_k"].items():
            print(f"  {k}: {data['rate']:.2%} ({data['passed']}/{data['total']})")
        
        print("\n【其他指标】")
        print(f"  执行准确率: {report['execution_accuracy']:.2%}")
        print(f"  数据完整性: {report['data_completeness']:.2%}")
        print(f"  幻觉率: {report['hallucination_rate']:.2%}")
        print(f"  平均延迟: {report['avg_latency_ms']:.0f}ms")
        
        print("\n【按难度分层】")
        for diff, data in report["by_difficulty"].items():
            print(f"  {diff}: {data['rate']:.2%} ({data['passed']}/{data['total']})")
        
        print("\n【按类别分层】")
        for cat, data in report["by_category"].items():
            print(f"  {cat}: {data['rate']:.2%} ({data['passed']}/{data['total']})")
        
        # ✨ 【RCA 增强】打印根因分析统计
        if "rca_statistics" in report:
            rca = report["rca_statistics"]
            print("\n【RCA 根因分析】")
            print(f"  平均传播深度: {rca.get('avg_propagation_depth', 0):.2f}")
            print(f"  错误类型分布:")
            for error_type, count in rca.get("error_type_distribution", {}).items():
                print(f"    {error_type}: {count}")
            print(f"  根因 Agent 分布:")
            for agent, count in rca.get("root_agent_distribution", {}).items():
                print(f"    {agent}: {count}")
        
        print("=" * 60)
    
    def save_report(self, report: Dict, filename: Optional[str] = None):
        """保存报告到文件"""
        if filename is None:
            filename = f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        filepath = self.output_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"[Eval] 报告已保存到 {filepath}")
    
    def analyze_trajectories(self, trajectory_file: str) -> Dict:
        """
        ✨ 【ASA 优化】分析多 Agent 轨迹（DPO 数据）
        
        基于 TrajectoryCollector.save() 输出的 jsonl 文件进行统计分析。
        
        Args:
            trajectory_file: 轨迹文件路径 (jsonl 格式)
        
        Returns:
            {
                "total_samples": int,
                "sft_only_samples": int,  # 纯 SFT 数据（没有失败样本）
                "dpo_pair_samples": int,  # DPO 数据对（有 chosen + rejected）
                "difficulty_distribution": {"easy": int, "medium": int, "hard": int},
                "error_type_distribution": {"SyntaxError": int, "NetworkError": int, ...}
            }
        """
        total = 0
        sft_only = 0
        dpo_pair = 0
        error_count = {}
        difficulty_count = {"easy": 0, "medium": 0, "hard": 0}
        
        print(f"[Evaluator] 开始分析轨迹文件: {trajectory_file}")
        
        try:
            with open(trajectory_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    total += 1
                    item = json.loads(line)
                    
                    # 统计数据类型
                    data_type = item.get("data_type", "sft_only")
                    if data_type == "sft_only":
                        sft_only += 1
                    elif data_type == "dpo_pair":
                        dpo_pair += 1
                    
                    # 统计难度
                    difficulty = item.get("difficulty", "medium")
                    if difficulty in difficulty_count:
                        difficulty_count[difficulty] += 1
                    
                    # 统计错误类型
                    err_type = item.get("error_type")
                    if err_type:
                        error_count[err_type] = error_count.get(err_type, 0) + 1
            
            result = {
                "total_samples": total,
                "sft_only_samples": sft_only,
                "dpo_pair_samples": dpo_pair,
                "difficulty_distribution": difficulty_count,
                "error_type_distribution": error_count,
                "dpo_pair_rate": dpo_pair / total if total > 0 else 0,
                "analysis_timestamp": datetime.now().isoformat()
            }
            
            print(f"[Evaluator] ✅ 分析完成:")
            print(f"  总样本数: {total}")
            print(f"  SFT 样本: {sft_only} ({sft_only/total*100:.1f}%)")
            print(f"  DPO 数据对: {dpo_pair} ({dpo_pair/total*100:.1f}%)")
            print(f"  难度分布: {difficulty_count}")
            print(f"  错误类型分布: {error_count}")
            
            return result
        
        except FileNotFoundError:
            print(f"[Evaluator] ❌ 轨迹文件不存在: {trajectory_file}")
            return {
                "error": "File not found",
                "total_samples": 0
            }
        except Exception as e:
            print(f"[Evaluator] ❌ 分析失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "error": str(e),
                "total_samples": 0
            }

# =============================================================================
# 4. 便捷函数
# =============================================================================

def quick_evaluate(agent_fn: Callable[[str], str], num_cases: int = 5) -> Dict:
    """
    快速评估（用于开发调试）
    
    Args:
        agent_fn: Agent 调用函数
        num_cases: 测试用例数量
    
    Returns:
        简化的评估报告
    """
    evaluator = Evaluator()
    test_cases = GOLDEN_TEST_CASES[:num_cases]
    
    report = evaluator.run_full_evaluation(agent_fn, test_cases, k_values=[1, 3])
    evaluator.print_report(report)
    
    return report


# =============================================================================
# 5. 测试代码
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # ✨ 【真实落地】默认启用真实 multi_agent（使用 --mock 可降级）
    USE_REAL_AGENT = "--mock" not in sys.argv and "-m" not in sys.argv
    
    # 加载 MVE 数据集
    try:
        with open('ASA/test_cases.json', encoding='utf-8') as f:
            test_data = json.load(f)
            test_queries = test_data.get('tasks', [])
            print(f"[ASA] 已加载 {len(test_queries)} 个测试用例")
    except FileNotFoundError:
        print("[ASA] test_cases.json 未找到，使用默认测试集")
        test_queries = None
    
    # ✨ 【深化】真实的 multi_agent 调用函数
    def real_agent(query: str) -> str:
        """
        调用真实的 multi_agent 系统
        这是一个完整的端到端调用，而不是 mock
        """
        try:
            from multi_agent import multi_agent_app, get_initial_state
            from langchain_core.messages import HumanMessage
            
            # 初始化状态
            state = get_initial_state()
            state["messages"] = [HumanMessage(content=query)]
            
            # 调用 multi_agent 工作流
            config = {"configurable": {"thread_id": f"eval_{int(time.time())}"}}
            result = multi_agent_app.invoke(state, config)
            
            # 提取最终输出
            if result.get("messages"):
                final_msg = result["messages"][-1]
                return str(final_msg.content) if hasattr(final_msg, 'content') else str(final_msg)
            else:
                return "[ERROR]: 无输出"
        except Exception as e:
            return f"[ERROR]: {str(e)}"
    
    # 模拟一个简单的 Agent
    def mock_agent(query: str) -> str:
        time.sleep(0.1)  # 模拟延迟
        
        if "股息率" in query:
            return "[DATA]: {'贵州茅台': {'股息率': '1.23%'}}"
        elif "收盘价" in query:
            return "[DATA]: {'贵州茅台': {'收盘价': 1850.00}}"
        elif "ROE" in query:
            return "[DATA]: {'贵州茅台': {'ROE': 30.5}, '五粮液': {'ROE': 25.2}}"
        elif "画" in query or "图" in query:
            return "[CHART]: 图表已保存到 ./output/chart.png"
        elif "报告" in query:
            return "[REPORT]: 根据分析，贵州茅台...（详细报告）"
        elif "999999" in query:
            return "[REJECT]: 股票代码不存在"
        elif "明天" in query or "未来" in query:
            return "[REJECT]: 无法预测未来股价"
        else:
            return "查询结果：数据获取成功"
    
    # ✨ 选择使用真实或 mock agent（默认使用真实）
    if USE_REAL_AGENT:
        print("\n[ASA] 模式: 真实 Multi-Agent (默认)")
        print("[ASA] 提示: 使用 --mock 或 -m 参数降级为 Mock Agent\n")
        agent_fn = real_agent
    else:
        print("\n[ASA] 模式: Mock Agent (--mock)")
        print("[ASA] 提示: 移除 --mock 参数可启用真实 Multi-Agent\n")
        agent_fn = mock_agent
    
    # 运行评估
    evaluator = Evaluator(output_dir="./test_eval")
    
    # ✨【改进】启用 LLM-as-Judge 评估，验证蕥释率是否真的地降低
    evaluator.run_full_evaluation = lambda agent_fn, test_cases, k_values=[1], **kw: evaluator._run_with_llm_judge(agent_fn, test_cases, k_values)
    
    # 定义 LLM 评估包装函数
    def _run_with_llm_judge(evaluator, agent_fn, test_cases, k_values):
        """启用 LLM 评估的完整评估流程"""
        print("[ASA] ✨【LLM-as-Judge】启动 LLM 验证蕥释...\n")
        
        # 调用原体的评估函数，但启用 LLM 评估
        all_results = []
        for test_case in test_cases:
            # 每个测试用例采用 use_llm_eval=True
            result = evaluator.evaluate_single(agent_fn, test_case, attempt=1, use_llm_eval=True)
            all_results.append([result])
            
            # 实时打印 LLM 判断结果
            status = "[PASS]" if result.output_match else "[FAIL]"
            print(f"{status} {test_case.query[:50]}...")
            if result.llm_judge_reason:
                print(f"  → LLM：{result.llm_judge_reason}")
        
        # 计算 Pass@K
        from typing import Dict
        report: Dict = {
            "total_cases": len(test_cases),
            "pass_at_k": {},
            "by_difficulty": {},
            "by_category": {},
            "all_results": all_results
        }
        
        for k in k_values:
            passed = sum(1 for res in all_results if res[0].output_match)
            report["pass_at_k"][k] = {"passed": passed, "total": len(test_cases), "rate": passed/len(test_cases)}
        
        return report
    
    # 绑定方法
    evaluator._run_with_llm_judge = _run_with_llm_judge.__get__(evaluator, Evaluator)
    
    # 定义原始评估函数（不用 LLM）
    def run_without_llm(evaluator, agent_fn, test_cases, k_values=[1], **kwargs):
        return evaluator.run_full_evaluation.__wrapped__(agent_fn, test_cases, k_values)
    
    # 如果加载了 MVE 数据，使用加载的数据；否则使用默认的 GOLDEN_TEST_CASES
    if test_queries:
        test_cases = [TestCase(query=q, difficulty="medium", category="stock_query") for q in test_queries]
        print(f"[ASA] 运行 {len(test_cases)} 个 MVE 测试用例...\n")
        report = evaluator._run_with_llm_judge(agent_fn, test_cases, k_values=[1])
    else:
        # 快速评估（使用默认的 GOLDEN_TEST_CASES）
        report = quick_evaluate(agent_fn, num_cases=5)
    
    evaluator.print_report(report)
    # 保存报告
    evaluator.save_report(report)
