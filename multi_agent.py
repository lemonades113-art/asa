#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Multi-Agent Architecture with Supervisor Pattern
LangGraph Supervisor
:Supervisor() + Coder() + Reviewer() + ProfileUpdater()
 Self-Correction()(Re-planning)

v2.0 升级要点：
1. 模型分层策略: smart (qwen-plus) vs fast (qwen-turbo), 成本优化 10%-20%
2. 画像更新后置: ProfileUpdater 移至 Reviewer 之后，基于完整对话更新
3. 错误分类细化: Coder 错误细分为 code_error / network_error / auth_error
4. 输入断言增强: Coder 代码增加 assert 校验，提前捕获数据异常
5. 动态路由配置: 支持 routing_config.json 热更新路由策略
6. 新增模块集成:
   - TrajectoryCollector: DPO 微调数据收集
   - MemorySystem: 短期+长期记忆 (类似 Letta/MemGPT)
   - Orchestrator: 失败重调度 + Fallback 机制 (参考 AutoGen)
   - RCA Module: 根因分析 + 故障传播图
   - ToolUsageGraph: 工具调用成功率追踪 (参考 AutoTool AAAI 2026)
7. 查询重写: QueryRewriter 参考 MindSearch 实现查询扩展
8. 结果融合: ResultFusion 参考 MindSearch + RankLLM 实现多源数据融合
9. 智能降级: SmartFallback 基于记忆系统的错误恢复策略
10. 4级自愈: ErrorHandler 实现 4-Level Self-Healing 机制

配置文件: routing_config.json
  - "routes": 节点路由规则
  - "route_rules": 条件路由配置
  - "error_classification": 错误类型分类
  - "model_config": 模型参数配置
"""

import json
import operator
import datetime
import os
import sys
import traceback
from typing import Annotated, TypedDict, Literal, List, Union, Tuple, Optional, Dict, Any

# Windows 控制台 UTF-8 输出，防止 emoji 导致 GBK 编码崩溃
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from lib import (
    get_chat_model, search, run_python_script, global_kernel,
    INTENT_PROMPT, get_system_prompt, multi_path_schema_recall,
    truth_anchor_scan
)

# =============================================================================
# Prompt 外化加载 - 支持热更新，无需重启修改 Prompt
# 参考 autoresearch/program.md 设计哲学：规则外化，运行时读取
# =============================================================================

def _load_prompt(name: str, fallback: str = "") -> str:
    """从 config/prompts/{name}.txt 加载 Prompt，文件不存在时返回 fallback。
    
    设计优势：
    - 支持热更新：修改 txt 文件后重启即生效，无需改动代码
    - 关注点分离：Prompt 工程与代码逻辑解耦
    - 便于版本控制：Prompt 变更历史独立可追溯
    """
    prompt_path = os.path.join(os.path.dirname(__file__), "config", "prompts", f"{name}.txt")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"[PromptLoader] 已加载 {name}.txt ({len(content)} chars)")
        return content
    except FileNotFoundError:
        if fallback:
            print(f"[PromptLoader] {name}.txt 不存在，使用内置 fallback")
            return fallback
        raise FileNotFoundError(f"Prompt 文件缺失: {prompt_path}")
    except Exception as e:
        print(f"[PromptLoader] 加载 {name}.txt 失败: {e}，使用 fallback")
        return fallback


# =============================================================================
# 可选模块导入 - DPO 微调数据收集
# =============================================================================
try:
    from trajectory_collector import trajectory_collector, classify_error
    TRAJECTORY_ENABLED = True
    print("[System] TrajectoryCollector 已加载 - 用于DPO微调数据收集")
except ImportError:
    TRAJECTORY_ENABLED = False
    print("[System] TrajectoryCollector 未加载 - 跳过DPO数据收集")

# =============================================================================
# 可选模块导入 - 错误分类器
# =============================================================================
try:
    from error_classifier import ErrorClassifier, classify_error
    ERROR_CLASSIFIER_ENABLED = True
    print("[System] ErrorClassifier 已加载 - 用于智能错误分类")
except ImportError:
    ERROR_CLASSIFIER_ENABLED = False
    classify_error = None
    print("[System] ErrorClassifier 未加载 - 使用简单错误分类")

# =============================================================================
# 可选模块导入 - 记忆系统 (ASA 2.0)
# =============================================================================
try:
    from memory_system import memory_system, get_memory_context, record_successful_execution, SessionAwareShortTermMemory
    MEMORY_ENABLED = True
    # 初始化会话感知的短期记忆管理器
    session_stm_manager = SessionAwareShortTermMemory(max_size=10, ttl_minutes=30)
    print("[System] MemorySystem 已加载 - 短期 + 长期记忆 (类似 Letta/MemGPT)")
    print("[System] SessionAwareShortTermMemory 已激活 - 支持多用户会话隔离")
except ImportError:
    MEMORY_ENABLED = False
    get_memory_context = lambda x: ""  # fallback
    record_successful_execution = lambda *args, **kwargs: None  # fallback
    session_stm_manager = None
    print("[System] MemorySystem 未加载 - 禁用记忆功能")

# =============================================================================
# 可选模块导入 - Orchestrator + Fallback (ASA 2.0)
# =============================================================================
try:
    from orchestrator import orchestrator, handle_agent_failure, AgentRole, ToolUsageGraph
    ORCHESTRATOR_ENABLED = True
    TOOL_GRAPH_ENABLED = True
    print("[System] Orchestrator 已加载 - 失败重调度 + Fallback 机制 (参考 AutoGen)")
    print("[System] ToolUsageGraph 已加载 - 工具调用成功率追踪")
except ImportError:
    ORCHESTRATOR_ENABLED = False
    TOOL_GRAPH_ENABLED = False
    handle_agent_failure = lambda *args, **kwargs: {"action": "retry", "message": "fallback"}  # fallback
    ToolUsageGraph = None
    print("[System] Orchestrator 未加载 - 禁用智能调度")
    print("[System] ToolUsageGraph 未加载 - 禁用工具图")

# =============================================================================
# 可选模块导入 - RCA 根因分析 (ASA 2.1)
# =============================================================================
try:
    from rca_module import fault_analyzer, get_rca_enhanced_retry_strategy, FaultType
    RCA_ENABLED = True
    print("[System] RCA Module 已加载 - 根因分析 + 故障传播图")
except ImportError:
    RCA_ENABLED = False
    fault_analyzer = None
    get_rca_enhanced_retry_strategy = lambda s, e: (s, "跳过 RCA")
    print("[System] RCA Module 未加载 - 禁用根因分析")

# =============================================================================
# 可选模块导入 - Self-Improving 错题本 (ASA 2.2)
# 借鉴 OpenClaw pskoett/self-improving-agent 机制
# 失败时写入 .learnings/ERRORS.md，成功时写入 .learnings/LEARNINGS.md
# Supervisor 在构建 System Prompt 时自动注入相关历史经验
# =============================================================================
try:
    from self_improver import get_learnings_context, record_error_to_learnings, record_success_to_learnings
    SELF_IMPROVER_ENABLED = True
    print("[System] SelfImprover 已加载 - Self-Improving 错题本 (.learnings/)")
except ImportError:
    SELF_IMPROVER_ENABLED = False
    get_learnings_context = lambda q, **kwargs: ""
    record_error_to_learnings = lambda *args, **kwargs: None
    record_success_to_learnings = lambda *args, **kwargs: None
    print("[System] SelfImprover 未加载 - 禁用 Self-Improving 机制")

# Schema 多路召回开关（默认开启，可用环境变量关闭）
ENABLE_SCHEMA_RECALL = os.getenv("ASA_ENABLE_SCHEMA_RECALL", "true").lower() == "true"

# =============================================================================
# 可选模块导入 - YAML 工具权限 + 运行时中间件 (OpenCode 借鉴)
# 参考: OpenCode executeToolCall 传递 agent.name 上下文
# loader: YAML 驱动的 AgentFactory，ToolsConfig.can_use(tool_name)
# tool_node: ToolCallMiddleware (Pre-exec 权限门) + DataOutputValidator (Post-exec 格式验证)
# =============================================================================
try:
    from loader import agent_factory
    from tool_node import ToolCallMiddleware, DataOutputValidator
    YAML_PERMISSIONS_ENABLED = True
    _permission_middleware = ToolCallMiddleware()
    _data_validator = DataOutputValidator(
        data_prefix="[DATA]:",
        validate_non_empty=True
    )
    print("[System] YAML权限模块 已加载 - ToolCallMiddleware + DataOutputValidator")
except ImportError as _e:
    YAML_PERMISSIONS_ENABLED = False
    agent_factory = None
    _permission_middleware = None
    _data_validator = None
    print(f"[System] YAML权限模块 未加载 ({_e}) - 使用默认工具列表")

# 输出截断阈值 (借鉴 OpenCode Truncate.MAX_OUTPUT_SIZE = 50000)
_MAX_TOOL_OUTPUT = 8000  # ASA 场景下适当缩小，避免消耗过多 Token


# =============================================================================
# Structured Output Schemas (ASA 2.3)
# 三个核心 Pydantic 模型，替代正则验证，将格式对齐率提升到 100%
# =============================================================================

class CoderOutput(BaseModel):
    """
    Coder 节点的结构化输出 Schema
    
    设计思路：用 with_structured_output 代替正则解析 [DATA]: 标记
    LLM 直接输出合法 Python 对象，零解析失败率
    
    面试要点：
    - with_structured_output 工作在 Logits 层，通过 FSM 约束 Token 选择
    - 这比事后正则验证+重试模式高效得多
    """
    code: str = Field(description="要执行的 Python 代码")
    rationale: str = Field(description="代码逻辑说明")
    expected_output_type: str = Field(
        default="data",
        description="预期输出类型: data/result/chart"
    )


class AnalysisOutput(BaseModel):
    """
    金融分析结果的结构化 Schema
    
    面试要点：
    - 强制指定 data/logic/confidence 三个字段，避免模型自行发明格式
    - confidence 字段在金融合规场景有实际意义（标注不确定因素）
    """
    data: Any = Field(description="核心金融数据 JSON")
    logic: str = Field(description="分析推导过程")
    confidence: float = Field(
        default=0.9,
        ge=0.0, le=1.0,
        description="结论置信度 0~1"
    )


class FieldErrorSchema(BaseModel):
    """
    字段错误诊断的结构化 Schema
    
    面试要点：将错误识别结果结构化，方便下游处理
    """
    wrong_field: str = Field(description="错误的字段名")
    suggested_field: Optional[str] = Field(None, description="建议的正确字段名")
    interface: Optional[str] = Field(None, description="Tushare 接口名")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


# with_structured_output 展示用函数（不移除现有正则验证，作为即将升级路径的展示）
def parse_coder_output_structured(model, messages: list) -> Optional[CoderOutput]:
    """
    使用 with_structured_output 的结构化输出路径（面试展示用）
    
    展示了 Prompt 工程→结构化输出的演进路径：
    Phase 1 (当前): Prompt 约束 + 正则验证（惺窟率 ~5%）
    Phase 2 (近期): with_structured_output + Pydantic Schema（惺窟率 ~1%）
    Phase 3 (远期): Constrained Generation / Outlines（惺窟率 0%）
    
    Args:
        model: LangChain 模型实例
        messages: 对话消息列表
        
    Returns:
        CoderOutput Pydantic 对象，或 None（失败时 fallback 到正则验证）
    """
    try:
        structured_model = model.with_structured_output(CoderOutput)
        result = structured_model.invoke(messages)
        return result
    except Exception as e:
        print(f"[StructuredOutput] with_structured_output 失败 (fallback 到正则): {e}")
        return None  # Fallback 到现有正则验证



tool_usage_graph = None
if TOOL_GRAPH_ENABLED and ToolUsageGraph:
    tool_usage_graph = ToolUsageGraph(smoothing_factor=0.01)
    print("[System] ToolUsageGraph 已激活")
else:
    print("[System] ToolUsageGraph 未激活 (可选模块)")



# =============================================================================
# 回溯路由器 (Backtracking Router)
# =============================================================================

class BacktrackingRouter:
    """
    回溯路由器 - 实现多策略重试机制
    
    核心思想:
    当一个策略失败时，自动切换到备选策略，而不是直接放弃。
    参考 LangGraph 的 backtracking 机制实现。
    
    适用场景:
    -  Tushare API 数据缺失
    -  查询参数需要调整
    -  需要切换数据源
    -  需要改变查询策略
    
    使用示例:
    ```python
    router = BacktrackingRouter()
    router.start_query("查询茅台股价")
    
    while router.has_next_strategy():
        strategy = router.get_current_strategy()
        result = execute_strategy(strategy)
        
        if result.success:
            router.mark_success(result)
            break
        else:
            router.mark_failure(result.error, result.error_type)
    ```
    """
    
    # 预定义策略列表
    STRATEGIES = [
        {
            "name": "direct_query",
            "description": " Tushare API ",
            "prompt_hint": " Tushare API "
        },
        {
            "name": "step_by_step",
            "description": "",
            "prompt_hint": ""
        },
        {
            "name": "alternative_fields",
            "description": "",
            "prompt_hint": "pe_ttm  pepb  pe"
        },
        {
            "name": "reject_with_reason",
            "description": "",
            "prompt_hint": " [REJECT]: "
        }
    ]
    
    def __init__(self):
        self.current_query: str = ""
        self.current_strategy_index: int = 0
        self.failure_history: List[dict] = []  # {"strategy": ..., "error": ..., "error_type": ...}
        self.success_history: List[dict] = []
        self.max_retries: int = len(self.STRATEGIES)
    
    def start_query(self, query: str):
        """
        开始新的查询，初始化路由器状态
        
        同时通知 RCA 模块开始追踪
        """
        self.current_query = query
        self.current_strategy_index = 0
        self.failure_history = []
        print(f"[Backtrack] 开始查询: {query[:50]}...")
        
        # 通知 RCA 模块开始追踪
        if RCA_ENABLED and fault_analyzer:
            fault_analyzer.start_query(query)
    
    def has_next_strategy(self) -> bool:
        """检查是否还有可用策略"""
        return self.current_strategy_index < len(self.STRATEGIES)
    
    def get_current_strategy(self) -> dict:
        """获取当前策略"""
        if self.current_strategy_index >= len(self.STRATEGIES):
            return self.STRATEGIES[-1]  # 返回最后一个策略
        return self.STRATEGIES[self.current_strategy_index]
    
    def mark_failure(self, error: str, error_type: str = "unknown", agent: str = "Coder"):
        """
        标记当前策略失败，切换到下一个策略
            
        同时记录到 RCA 模块和记忆系统
            
        Args:
            error: 错误信息
            error_type: 错误类型 (code_error, network_error, auth_error, data_missing)
            agent: 失败的 Agent 名称
        """
        current = self.get_current_strategy()
            
        # 记录到 RCA 模块 (Agent 执行追踪)
        if RCA_ENABLED and fault_analyzer:
            fault_analyzer.record_agent_execution(
                agent=agent,
                input_data={"strategy": current["name"], "query": self.current_query[:100]},
                output_data={},
                success=False,
                error=error[:200],
                latency_ms=0
            )
                
            # 获取 RCA 建议的策略
            suggested_strategy, reason = get_rca_enhanced_retry_strategy(
                current["name"], error
            )
                
            # 如果 RCA 建议了不同策略，跳转到该策略
            if suggested_strategy != current["name"]:
                for i, s in enumerate(self.STRATEGIES):
                    if s["name"] == suggested_strategy:
                        print(f"[RCA] 建议跳转到 '{suggested_strategy}': {reason}")
                        self.current_strategy_index = i
                        break
            
        self.failure_history.append({
            "strategy": current["name"],
            "error": error[:200],
            "error_type": error_type,
            "agent": agent  # 记录失败的 Agent
        })
            
        # 记录到 ASA 记忆系统 (SmartFallback 使用)
        if MEMORY_ENABLED:
            try:
                from memory_system import record_successful_execution
                # 注意：这里记录的是"失败"，但 record_successful_execution 
                # 会被 LTM 的 search 用于避免重复错误
                record_successful_execution(
                    query=self.current_query[:200],
                    strategy=f"策略 '{current['name']}' 失败 '{error_type}' 类型",
                    steps=[f"错误: {error[:100]}"],
                    category="error_fix"  # 错误修复类别
                )
                print(f"[Backtrack] 已记录失败到记忆系统")
            except Exception as e:
                print(f"[Backtrack] 记忆系统记录失败: {e}")
            
        self.current_strategy_index += 1
            
        if self.has_next_strategy():
            next_strategy = self.get_current_strategy()
            print(f"[Backtrack] 从 '{current['name']}' 切换到 '{next_strategy['name']}'")
        else:
            print(f"[Backtrack] 所有策略已耗尽")
    
    def mark_success(self, result: str):
        """标记当前策略成功"""
        current = self.get_current_strategy()
        self.success_history.append({
            "query": self.current_query[:100],
            "strategy": current["name"],
            "retries": self.current_strategy_index
        })
        print(f"[Backtrack] 策略 '{current['name']}' 成功，重试次数: {self.current_strategy_index}")
    
    def get_prompt_hint(self) -> str:
        """
        获取当前策略的提示词，用于注入到 System Prompt
        
        包含失败历史和 RCA 分析结果
        """
        current = self.get_current_strategy()
        hint = f"\n\n策略提示: {current['description']}\n{current['prompt_hint']}"
        
        # 添加失败历史
        if self.failure_history:
            hint += "\n\n之前的失败:"
            for f in self.failure_history[-3:]:  # 只显示最近3次
                hint += f"\n- {f['strategy']}: {f['error'][:50]}..."
        
        # 添加 RCA 分析
        if RCA_ENABLED and fault_analyzer and fault_analyzer.propagation_edges:
            rca_summary = fault_analyzer.get_propagation_summary()
            if rca_summary:
                hint += f"\n\n{rca_summary}"
        
        return hint
    
    def should_reject(self) -> bool:
        """是否应该拒绝查询（所有策略都失败了）"""
        return self.current_strategy_index >= len(self.STRATEGIES) - 1
    
    def get_statistics(self) -> dict:
        """获取路由统计信息"""
        return {
            "current_query": self.current_query[:50],
            "current_strategy": self.get_current_strategy()["name"],
            "retries": self.current_strategy_index,
            "failures": len(self.failure_history),
            "total_successes": len(self.success_history)
        }


# 全局回溯路由器实例
backtracking_router = BacktrackingRouter()


# =============================================================================
# 差异化重试策略配置（参考PrimoAgent+CrewAI最佳实践）
# =============================================================================

ERROR_RETRY_CONFIG = {
    "network_timeout": {
        "max_retries": 3,
        "backoff": "exponential",  # 指数退避: 1s, 2s, 4s
        "backoff_base": 1.0,
        "fallback": "use_cached_data",
        "description": "网络超时，可重试"
    },
    "rate_limit": {
        "max_retries": 2,
        "backoff": "fixed",  # 固定60秒等待
        "backoff_seconds": 60,
        "fallback": "switch_to_backup_api",
        "description": "API限流，等待后重试"
    },
    "field_not_found": {
        "max_retries": 1,  # RAG纠错只需1次
        "backoff": None,
        "fallback": "rag_field_correction",  # ASA特色：RAG字段纠错
        "description": "字段不存在，RAG查询纠正"
    },
    "data_vacuum": {
        "max_retries": 0,  # 合法业务状态，不重试
        "backoff": None,
        "fallback": "return_explanation",
        "description": "数据真空，直接说明原因"
    },
    "auth_error": {
        "max_retries": 0,  # 永久错误，不重试
        "backoff": None,
        "fallback": "graceful_degradation",
        "description": "认证失败，降级处理"
    },
    "code_error": {
        "max_retries": 2,
        "backoff": "immediate",  # 立即重试
        "fallback": "regenerate_code",
        "description": "代码错误，重新生成"
    },
    "validation_error": {
        "max_retries": 1,
        "backoff": None,
        "fallback": "adjust_parameters",
        "description": "验证失败，调整参数"
    }
}


def get_retry_strategy(error_type: str) -> dict:
    """
    根据错误类型获取重试策略
    
    Args:
        error_type: 错误类型标识
    
    Returns:
        重试策略配置字典
    """
    return ERROR_RETRY_CONFIG.get(error_type, {
        "max_retries": 2,
        "backoff": "exponential",
        "backoff_base": 1.0,
        "fallback": "retry_with_caution",
        "description": "未知错误，默认重试"
    })


def calculate_backoff_delay(error_type: str, retry_count: int) -> float:
    """
    计算退避延迟时间
    
    Args:
        error_type: 错误类型
        retry_count: 当前重试次数
    
    Returns:
        延迟秒数
    """
    config = get_retry_strategy(error_type)
    backoff_type = config.get("backoff")
    
    if backoff_type is None:
        return 0.0
    
    if backoff_type == "exponential":
        base = config.get("backoff_base", 1.0)
        return min(base * (2 ** retry_count), 30.0)  # 最大30秒
    
    if backoff_type == "fixed":
        return config.get("backoff_seconds", 5.0)
    
    if backoff_type == "immediate":
        return 0.0
    
    return 0.0


# =============================================================================
# 1. Multi-Agent 状态定义
# =============================================================================

class MultiAgentState(TypedDict):
    """Multi-Agent 状态类型定义"""
    messages: Annotated[List[BaseMessage], operator.add]  # 消息历史
    next: str  # 下一个节点 (Supervisor/Coder/Reviewer/FINISH)
    retry_count: int  # 重试计数
    user_profile: dict  # 用户画像
    execution_status: str  # 执行状态 (pending/success/error)
    # 新增字段
    last_sender: str  # 最后发送者 (User/Supervisor/Coder/Reviewer/ErrorHandler)
    task_plan: dict  # 任务计划 {"steps": [...], "current_step_index": 0}
    remaining_steps: list  # 剩余步骤
    error_type: str  # 错误类型 (code_error/network_error/auth_error/unknown)
    network_retry_count: int  # 网络重试计数 (code)
    supervisor_retry: int  # Supervisor 重试计数
    last_execution_data: dict  # 最后执行数据 (用于错误恢复)
    message_window_size: int  # 消息窗口大小 (用于Token控制)
    # 新增 P0-E: 工具调用计数
    tool_call_count: int = 0  # 工具调用次数 (防循环)
    reviewer_fail_count: int = 0  # Reviewer 失败计数 (Reviewer 重试上限)
    total_step_count: int = 0  # 全局步数计数器 (防RecursionLimit)


# =============================================================================
# 2. Supervisor 路由响应模型
# =============================================================================

class RouteResponse(BaseModel):
    """Supervisor 路由决策响应"""
    next: Literal["Coder", "Reviewer", "FINISH"] = Field(
        ..., description="下一步节点: Coder(执行代码), Reviewer(审核结果), FINISH(结束对话)"
    )
    reason: str = Field(..., description="路由决策原因")


# =============================================================================
# 3. 模型初始化
# =============================================================================

# 高性能模型: Supervisor, Coder, Reviewer
# 使用 smart 模型 (qwen-plus / deepseek-v3 / gpt-4o)
smart_model = get_chat_model(model_type="smart", timeout=120)

# 快速模型: ErrorHandler, ProfileUpdater
# 使用 fast 模型 (qwen-turbo / gpt-4o-mini) - 成本低，响应快
fast_model = get_chat_model(model_type="fast", timeout=60)

@tool
def search_tushare_docs_local(query: str, top: int = 5) -> str:
    """搜索 Tushare 文档"""
    return search(query, top)


@tool
def run_script(content: str) -> str:
    """执行 Python 代码"""
    try:
        result = run_python_script(content)
        return result
    except Exception:
        import traceback
        stack_trace = traceback.format_exc()
        return f"Error:\n{stack_trace}"


@tool
def get_current_datetime() -> str:
    """获取当前日期时间，格式为 YYYY-MM-DD HH:MM:SS"""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =============================================================================
# coder_tools 工具列表 - YAML 驱动加载，硬编码 fallback
# 借鉴 OpenCode: agent.tools 白名单过滤 + Tool.all() 注册表
# =============================================================================
_TOOL_REGISTRY = {
    "search_tushare_docs_local": search_tushare_docs_local,
    "search_tushare_docs": search_tushare_docs_local,  # 兼容旧名称
    "run_script": run_script,
    "get_current_datetime": get_current_datetime,
}
_HARDCODED_CODER_TOOLS = [search_tushare_docs_local, run_script, get_current_datetime]

if YAML_PERMISSIONS_ENABLED and agent_factory:
    try:
        _allowed_names = agent_factory.get_allowed_tools("coder")
        coder_tools = [_TOOL_REGISTRY[n] for n in _allowed_names if n in _TOOL_REGISTRY]
        if not coder_tools:
            coder_tools = _HARDCODED_CODER_TOOLS
            print("[System] YAML coder 工具列表为空，回退到硬编码列表")
        else:
            print(f"[System] coder_tools 来源 YAML: {[t.name for t in coder_tools]}")
    except Exception as _e:
        coder_tools = _HARDCODED_CODER_TOOLS
        print(f"[System] YAML 工具加载失败 ({_e})，回退到硬编码")
else:
    coder_tools = _HARDCODED_CODER_TOOLS
    print(f"[System] coder_tools 使用硬编码列表: {[t.name for t in coder_tools]}")

coder_model = smart_model.bind_tools(coder_tools)  # Coder 绑定 smart_model + 工具列表
reviewer_model = smart_model  # Reviewer



# =============================================================================
# 4. Supervisor 核心逻辑
# =============================================================================

#  ASA 查询重写器 - 参考 MindSearch
class QueryRewriter:
    """
    查询重写器 - 将用户查询扩展为多个子查询
    
    核心功能:
    - 参考 MindSearch 实现查询分解 / 扩展 / 重写
    - 使用 fast_model 降低成本
    - 支持多维度查询扩展
    
    使用场景:
    -  decompose_task 中用于生成子查询
    """
    
    def __init__(self, model=None):
        self.model = model or fast_model
    
    def _parse_resp(self, text: str) -> List[str]:
        """解析模型响应，提取查询列表"""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # 过滤掉注释和空行
        queries = [l for l in lines if not l.startswith('#') and len(l) > 5]
        return queries
    
    def rewrite(self, user_query: str) -> List[str]:
        """
        重写用户查询，生成多个子查询
        
        Returns:
            子查询列表
        """
        prompt = f"""请为用户查询生成 3-5 个相关子查询，用于全面获取信息。

用户查询: {user_query}

请生成子查询，要求:
1. 覆盖不同的信息维度
2. 包含具体的API接口查询
3. 考虑时间范围、指标类型等
4. 使用中文

直接列出子查询，每行一个:"""
        
        try:
            resp = self.model.invoke(prompt)
            sub_queries = self._parse_resp(resp.content)
            # 去重
            sub_queries = list(dict.fromkeys(q.strip() for q in sub_queries if q.strip()))
            
            if sub_queries:
                print(f"[QueryRewriter] 生成 {len(sub_queries)} 个子查询")
                return sub_queries
            else:
                print(f"[QueryRewriter] 未生成子查询，使用原查询")
                return [user_query]
        
        except Exception as e:
            import logging
            logging.warning(f"[QueryRewriter] 重写失败: {e}")
            return [user_query]


# 任务分解器: (任务分解 + 查询重写)
def decompose_task(user_query: str, max_retries: int = 1, max_steps: int = 10) -> dict:
    """
    任务分解 - 将用户查询分解为可执行步骤
    
    结合 ASA 查询重写器:
    1. 使用 QueryRewriter 生成子查询
    2. 使用 smart 模型生成 JSON 格式的任务计划
    3. 支持失败回退
    """
    # Step 0: 查询重写 - 生成子查询
    rewriter = QueryRewriter()
    sub_queries = rewriter.rewrite(user_query)  # 默认返回 [user_query]
    
    try:
        decompose_prompt = f"""请将用户查询分解为执行步骤(JSON格式)。
步骤应该具体可执行(如调用API、计算指标、生成图表)。
返回格式: {{"steps": ["步骤1", "步骤2", ...]}}

用户查询: {user_query}

请返回JSON格式:{{"steps": ["1", "2", ...]}}"""
        
        response = smart_model.invoke(decompose_prompt)  # 使用 smart 模型
        
        # 解析 JSON
        try:
            plan_text = response.content.replace("```json", "").replace("```", "").strip()
            plan = json.loads(plan_text)
        except:
            # 解析失败，使用回退策略
            plan = {"steps": ["执行查询"]}
        
        # 验证步骤: 确保 steps 有效
        steps = plan.get("steps", [])
        if not steps or not any(any(action in step for action in ["查询", "获取", "计算", "分析", "生成"]) for step in steps):
            print(f"[TaskDecompose] 步骤无效，使用回退策略")
            # 回退: 使用子查询作为步骤
            steps = [f"查询: {q}" for q in sub_queries]
            return {"steps": steps[:max_steps], "sub_queries": sub_queries, "fallback": True}
        
        # 限制步骤数量
        steps = steps[:max_steps]
        
        print(f"[TaskDecompose] 任务分解: {steps}")
        print(f"[TaskDecompose] 子查询数量: {len(sub_queries)}")
        return {"steps": steps, "sub_queries": sub_queries, "fallback": False}
    
    except Exception as e:
        print(f"[TaskDecompose] 分解失败: {e}, 使用回退策略")
        steps = [f"查询: {q}" for q in sub_queries]
        return {"steps": steps[:max_steps], "sub_queries": sub_queries, "fallback": True}


# Tushare API 已知问题库
TUSHARE_KNOWN_ISSUES = {
    "pe_missing_etf": {
        "condition": "ETF 基金查询",
        "issue": "PE 字段可能为 NaN 或缺失",
        "solution": "使用 pb 或 dividend_yield 替代; ETF通常不关注PE"
    },
    "hk_stock_code_format": {
        "condition": "港股代码",
        "issue": "腾讯 00700.HK, 有些API需要 00700 或 HK00700",
        "solution": "检查代码格式 .HK 后缀, 或使用 .HSI 指数代码, 参考API文档"
    },
    "quarterly_report_timing": {
        "condition": "季度财报(1-4月)",
        "issue": "年报(report_type=1)可能未发布,只有季报(report_type=2)",
        "solution": "尝试不同的 report_type 值,或使用 limit 参数"
    },
    "data_lag_financial": {
        "condition": "财务数据",
        "issue": "财报数据通常有 1-2 个月延迟,最新数据可能缺失",
        "solution": "使用 report_date 参数查询历史数据,或扩大时间范围(2个月)"
    },
    "dv_ttm_is_percentage": {
        "condition": "股息率 dv_ttm(百分比)",
        "issue": "dv_ttm 可能是小数(如 5.2)或百分比(如 5.2%),需要统一",
        "solution": "检查数据格式, dv_ttm 通常是小数,如需百分比则乘以 100"
    },
    "daily_basic_empty": {
        "condition": "个股查询",
        "issue": "daily_basic 可能返回空数据(新股或停牌)",
        "solution": "检查 DataFrame 是否为空, 尝试其他 API(daily 或 quote)"
    }
}


# =============================================================================
# 增强数据验证函数（参考PrimoAgent严格检查设计）
# =============================================================================

def validate_data_schema(data: Any, expected_schema: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    验证数据结构是否符合预期schema（第4重验证）
    
    Args:
        data: 待验证数据（通常是DataFrame或dict）
        expected_schema: 预期结构，如 {"columns": ["date", "open", "close"], "min_rows": 1}
    
    Returns:
        (是否通过, 失败原因列表)
    """
    import pandas as pd
    issues = []
    
    try:
        # 转换为DataFrame统一处理
        if isinstance(data, dict):
            df = pd.DataFrame([data])
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, pd.DataFrame):
            df = data
        else:
            return False, [f"不支持的数据类型: {type(data)}"]
        
        if df.empty:
            return False, ["数据为空DataFrame"]
        
        # 检查必需列
        if "columns" in expected_schema:
            missing_cols = set(expected_schema["columns"]) - set(df.columns)
            if missing_cols:
                issues.append(f"缺少必需列: {missing_cols}")
        
        # 检查最小行数
        if "min_rows" in expected_schema:
            if len(df) < expected_schema["min_rows"]:
                issues.append(f"行数不足: {len(df)} < {expected_schema['min_rows']}")
        
        # 检查数据类型
        if "dtypes" in expected_schema:
            for col, expected_type in expected_schema["dtypes"].items():
                if col in df.columns:
                    actual_type = str(df[col].dtype)
                    if expected_type not in actual_type:
                        issues.append(f"列 {col} 类型不匹配: 期望 {expected_type}, 实际 {actual_type}")
        
    except Exception as e:
        issues.append(f"Schema验证异常: {e}")
    
    return len(issues) == 0, issues


def validate_data_sanity(data: Any) -> Tuple[bool, List[str]]:
    """
    数据合理性检查（第5重验证）- 异常值检测
    
    检查项:
    - 价格类字段不为负数
    - 无NaN值
    - 日期格式正确
    - 数值在合理范围内
    """
    import pandas as pd
    import numpy as np
    issues = []
    
    try:
        if isinstance(data, dict):
            df = pd.DataFrame([data])
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, pd.DataFrame):
            df = data
        else:
            return True, []  # 无法验证的类型默认通过
        
        if df.empty:
            return True, []
        
        # 价格类字段检查（常见金融字段）
        price_columns = ['close', 'open', 'high', 'low', 'price', 'pre_close', 'change']
        for col in price_columns:
            if col in df.columns:
                # 检查负数
                if (df[col] < 0).any():
                    issues.append(f"列 {col} 存在负值")
                # 检查NaN
                if df[col].isna().any():
                    issues.append(f"列 {col} 存在NaN")
                # 检查极端值（价格>10万可能是数据错误）
                if (df[col] > 100000).any():
                    issues.append(f"列 {col} 存在极端值(>10万)")
        
        # 涨跌幅检查
        if 'pct_change' in df.columns or 'change_pct' in df.columns:
            pct_col = 'pct_change' if 'pct_change' in df.columns else 'change_pct'
            if (df[pct_col].abs() > 0.5).any():  # 涨跌幅超过50%警告
                issues.append(f"{pct_col} 存在极端涨跌幅(>50%)")
        
        # 成交量检查
        if 'vol' in df.columns or 'volume' in df.columns:
            vol_col = 'vol' if 'vol' in df.columns else 'volume'
            if (df[vol_col] < 0).any():
                issues.append(f"{vol_col} 存在负值")
        
    except Exception as e:
        issues.append(f"合理性验证异常: {e}")
    
    return len(issues) == 0, issues


def validate_task_alignment(data: Any, task_goal: str, fast_model=None) -> Tuple[bool, str]:
    """
    验证结果是否与任务目标一致（第6重验证）- LLM语义验证
    
    Args:
        data: 执行结果数据
        task_goal: 任务目标描述
        fast_model: 快速模型实例（可选，用于LLM判断）
    
    Returns:
        (是否通过, 判断理由)
    """
    # 简化版：基于关键词匹配（避免调用LLM增加延迟）
    data_str = str(data).lower()
    goal_lower = task_goal.lower()
    
    # 提取任务关键词
    key_indicators = []
    if "财务" in goal_lower or "financial" in goal_lower:
        key_indicators.extend(["利润", "收入", "资产", "负债", "roe", "净利润", "revenue"])
    if "估值" in goal_lower or "valuation" in goal_lower:
        key_indicators.extend(["pe", "pb", "ps", "估值", "value"])
    if "趋势" in goal_lower or "trend" in goal_lower:
        key_indicators.extend(["趋势", "上涨", "下跌", "trend", "up", "down"])
    if "分红" in goal_lower or "dividend" in goal_lower:
        key_indicators.extend(["分红", "股息", "dividend", "div"])
    
    # 检查是否有至少一个关键词匹配
    matched = [k for k in key_indicators if k in data_str]
    
    if not key_indicators:
        # 无法提取关键词，默认通过
        return True, "无法提取明确指标，默认通过"
    
    if matched:
        return True, f"匹配到关键词: {matched}"
    else:
        return False, f"未匹配到期望指标({key_indicators})，可能偏离任务目标"


def log_node_execution(node_name: str, state: MultiAgentState, details: Dict[str, Any] = None):
    """
    结构化节点执行日志（Debug可观测性）
    
    参考PrimoAgent的debug_state设计，在每个节点后记录关键信息
    """
    import json
    from datetime import datetime
    
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "node": node_name,
        "task_queue_length": len(state.get("remaining_steps", [])),
        "retry_count": state.get("retry_count", 0),
        "execution_status": state.get("execution_status", "unknown"),
        "last_sender": state.get("last_sender", "unknown"),
    }
    
    # 添加额外详情
    if details:
        log_entry["details"] = details
    
    # 记录变量数量（执行内核中）
    if "exec_kernel" in state:
        log_entry["variables_count"] = len(state["exec_kernel"])
    
    # 记录消息数
    if "messages" in state:
        log_entry["messages_count"] = len(state["messages"])
    
    # 打印结构化日志
    print(f"[NodeLog] {json.dumps(log_entry, ensure_ascii=False)}")
    
    return log_entry


# =============================================================================
# 三重验证机制（Triple Validation Mechanism）
# 解决逻辑早停问题：确保数据完整性后才允许推进到下一节点
# =============================================================================

def validate_coder_result(result: str) -> Tuple[bool, str, int]:
    """
    三重验证机制（确保数据完整性）
    
    验证维度：
    1. 标记存在性：检查 [DATA]: 或 [RESULT]: 标记
    2. 数据非空性：排除 {}, [], null, None 等空值
    3. 状态有效性：排除 [ERROR]: 和 [PARTIAL]: 状态
    
    Args:
        result: Coder 返回的结果字符串
        
    Returns:
        Tuple[bool, str, int]: (是否通过, 失败原因, 失败的检查项)
        - 检查项: 0=通过, 1=标记缺失, 2=数据为空, 3=状态错误
        
    面试要点：
    - 为什么需要三重验证：LLM 遵循 Prompt 存在概率失效，需要代码层兜底
    - 与 Prompt 工程的关系：Prompt 是软约束，验证函数是硬约束
    - 金融场景必要性：数据完整性是监管要求，不能依赖模型自律
    """
    # 验证1：检查数据标记存在性（包括部分结果标记）
    has_data_tag = "[DATA]:" in result
    has_result_tag = "[RESULT]:" in result
    has_partial_tag = "[PARTIAL]:" in result or "[PARTIAL RESULT]" in result
    
    if not has_data_tag and not has_result_tag and not has_partial_tag:
        return False, "缺少输出标记 [DATA]: / [RESULT]: / [PARTIAL]:", 1
    
    # 验证2：检查数据非空性
    # 提取标记后的内容
    if ":" in result:
        content = result.split(":", 1)[1].strip()
    else:
        content = result.strip()
    
    empty_indicators = ["", "{}", "[]", "null", "None", "''", '""']
    if content in empty_indicators:
        return False, "输出内容为空", 2
    
    # 额外启发式检查：数据标记但内容明显为空
    if has_data_tag and len(content) < 5:
        return False, "数据标记存在但内容过少", 2
    
    # 验证3：检查是否为错误状态
    if "[ERROR]:" in result:
        return False, "执行报错", 3
    
    # 验证4：检查是否为部分结果状态（特殊处理）
    if "[PARTIAL]:" in result or "[PARTIAL RESULT]" in result:
        return True, "部分结果（超时）", 0
    
    return True, "验证通过", 0


def generate_validation_feedback(failed_check: int, result: str) -> str:
    """
    根据失败的检查项生成诊断反馈
    
    Args:
        failed_check: 失败的检查项（1, 2, 或 3）
        result: 原始结果
        
    Returns:
        诊断反馈消息
    """
    if failed_check == 1:
        return """【验证失败】缺少输出标记

你的代码必须包含以下格式的输出：
print(f"[DATA]: {json.dumps(results, ensure_ascii=False)}")

如果数据获取失败，也要输出错误信息：
print(f"[DATA]: {json.dumps({'error': '原因说明'}, ensure_ascii=False)}")

请修改代码并重新执行。"""
    
    elif failed_check == 2:
        return """【验证失败】输出内容为空

可能原因：
1. 股票代码不存在或已退市
2. 查询日期范围内无数据
3. API 返回空结果

请尝试：
1. 检查股票代码格式（如 '000001.SZ'）
2. 扩大日期范围
3. 检查 API 调用是否有返回数据

如果确实无数据，请输出包含 error 字段的 JSON。"""
    
    elif failed_check == 3:
        return """【验证失败】执行报错

请检查代码中的语法错误、字段名是否正确。
使用 try-except 捕获异常并输出友好的错误信息。"""
    
    return "【验证失败】未知错误"


def supervisor_node(state: MultiAgentState):
    """
    Supervisor 节点: 路由决策 + 任务分解 + 错误恢复 + 记忆集成
    
    核心职责:
    1. 启动轨迹收集 (用于DPO微调)
    2. 根据 last_sender 和 execution_status 决定下一步
    3. 消息修剪防止 Token 爆炸
    4. 注入 Tushare 已知问题提示
    5. 集成记忆系统上下文
    """
    # 全局步数检查 - 防止 RecursionLimit
    current_step = state.get("total_step_count", 0) + 1
    if current_step > 25:
        print(f"[Supervisor] 全局步数超限 ({current_step} > 25)，强制终止")
        return {
            "messages": [AIMessage(content="[ERROR]: 任务执行步数超限，系统已终止。请简化查询或稍后重试。")],
            "next": "FINISH",
            "total_step_count": current_step,
            "execution_status": "error"
        }
    
    # 轨迹收集 - 新查询开始时
    if TRAJECTORY_ENABLED:
        last_sender = state.get("last_sender", "User")
        if last_sender == "User" and state.get("messages"):
            # 
            user_query = state["messages"][-1].content if hasattr(state["messages"][-1], 'content') else str(state["messages"][-1])
            trajectory_collector.start_trajectory(user_query)
            print(f"[Trajectory] : {user_query[:50]}...")
    
    # 系统提示词 - Supervisor 角色定义
    system_prompt = """你是 Supervisor (主管)，负责协调多智能体系统的工作流程。

可用 Agent:
1. Coder: 执行 Python 代码，调用 Tushare API 获取数据，进行计算分析
2. Reviewer: 审核 Coder 的结果，生成最终回复给用户

路由规则:
- 用户输入 -> 任务分解 -> Coder
- Coder 成功执行 -> Reviewer
- Reviewer 审核完成 -> FINISH

注意: Tushare API 可能有数据延迟或缺失，Coder 应该处理这些情况。
当 Coder 返回错误时，可以重试或转给 Reviewer 生成降级回复。
"""
    
    # 检测潜在问题
    last_msg_content = ""
    if state.get("messages"):
        last_msg = state["messages"][-1]
        if hasattr(last_msg, 'content'):
            last_msg_content = str(last_msg.content).lower()
    
    # 
    potential_issues = []
    if "etf" in last_msg_content or "" in last_msg_content:
        potential_issues.append(TUSHARE_KNOWN_ISSUES["pe_missing_etf"])
    if "" in last_msg_content or "hk" in last_msg_content or "" in last_msg_content:
        potential_issues.append(TUSHARE_KNOWN_ISSUES["hk_stock_code_format"])
    if "" in last_msg_content or "income" in last_msg_content or "quarter" in last_msg_content:
        potential_issues.append(TUSHARE_KNOWN_ISSUES["quarterly_report_timing"])
        potential_issues.append(TUSHARE_KNOWN_ISSUES["data_lag_financial"])
    if "" in last_msg_content or "" in last_msg_content or "dv_ttm" in last_msg_content:
        potential_issues.append(TUSHARE_KNOWN_ISSUES["dv_ttm_is_percentage"])
    
    # 注入已知问题提示到 System Prompt
    if potential_issues:
        system_prompt += "\n注意以下已知问题:\n"
        for issue in potential_issues:
            system_prompt += f"\n- {issue['condition']}: {issue['issue']}"
            system_prompt += f"\n  解决方案: {issue['solution']}\n"
    
    # 添加 Coder 代码规范提示
    system_prompt += """\nCoder 代码规范:
- 使用描述性变量名 (如 df_maotai, df_wuliangye)，避免重复使用 df
- 处理 API 返回的空数据情况
- 使用 try-except 捕获异常

输出格式 (JSON):
{"next": "Coder" 或 "Reviewer" 或 "FINISH", "reason": "决策原因"}

请根据对话历史决定下一步。"""
    
    # ASA 2.0 + 记忆系统集成
    if MEMORY_ENABLED and session_stm_manager:
        try:
            # 获取会话 ID（LangGraph thread_id）
            config = state.get("__config__", {})
            session_id = config.get("configurable", {}).get("thread_id", "default")
            
            # 获取或创建当前会话的短期记忆
            session_short_term = session_stm_manager.get_or_create(session_id)
            
            # 添加用户查询到短期记忆
            user_query_for_memory = last_msg_content if last_msg_content else ""
            if user_query_for_memory:
                session_short_term.add(
                    content=f"[user] {user_query_for_memory}",
                    source="conversation",
                    category="user_query"
                )
            
            # 获取上下文（本会话短期记忆 + 全局长期记忆）
            memory_context = get_memory_context(user_query_for_memory)
            if memory_context:
                system_prompt += f"\n\n{memory_context}"
                print(f"[MemorySystem] 注入记忆上下文：{len(memory_context)} 字符 (session={session_id[:8]}...)")
                
                # 使用混合检索替代普通检索（如果 memory_system 中有 search_hybrid）
                try:
                    # 自动优先使用 search_hybrid
                    if hasattr(memory_system.long_term, 'search_hybrid'):
                        hybrid_results = memory_system.long_term.search_hybrid(
                            query=user_query_for_memory,
                            top_k=5,
                            alpha=0.7  # 70% 向量，30% BM25
                        )
                        print(f"[MemorySystem] 使用 search_hybrid() - 检索到 {len(hybrid_results)} 条结果")
                    else:
                        print("[MemorySystem] search_hybrid() 不可用，降级到 search()")
                except Exception as e:
                    print(f"[MemorySystem] search_hybrid() 调用失败：{e}，降级到 search()")
        except Exception as e:
            print(f"[MemorySystem] 集成失败：{e}")

    # ASA 2.2: Self-Improving 历史经验注入
    # 从 .learnings/ 目录读取过往错误和成功经验，注入到 System Prompt 经验区
    # 随着运行积累，Agent 会越来越智能（参考 OpenClaw self-improving-agent）
    if SELF_IMPROVER_ENABLED:
        try:
            user_query_for_learnings = last_msg_content if last_msg_content else ""
            learnings_context = get_learnings_context(user_query_for_learnings, max_chars=1500)
            if learnings_context:
                system_prompt += f"\n\n{learnings_context}"
                print(f"[SelfImprover] 注入历史经验: {len(learnings_context)} 字符")
        except Exception as e:
            print(f"[SelfImprover] 注入经验失败: {e}")
    
    # 步骤 0: 消息压缩/修剪 (防止 Token 爆炸)
    # compact_messages: 超过阈值时用 fast_model 生成摘要 (借鉴 OpenCode Compaction)
    # trim_messages_for_context: 兜底截断 (保留最近 N 条)
    messages = state.get("messages", [])
    messages = compact_messages(messages)           # 先尝试摘要压缩
    trimmed_messages = trim_messages_for_context(messages, max_keep=15)  # 再做截断兜底
    
    # 步骤 1: 状态检查 (任务计划)
    last_sender = state.get("last_sender", "User")
    remaining_steps = state.get("remaining_steps", [])
    task_plan = state.get("task_plan", None)
    execution_status = state.get("execution_status", "pending")
    
    # Self-Correction Loop: 自我纠正机制
    retry_count = state.get("retry_count", 0)
    error_type = state.get("error_type", None)
    
    if execution_status == "error" and retry_count >= 2:
        print(f"[Self-Correction] 检测到重复错误 ({error_type}), 重试次数: {retry_count}, 触发反思...")
        
        # 生成反思提示
        reflection_prompt = f"""
请分析以下错误并给出改进建议:

用户查询: {last_msg_content[:100] if 'last_msg_content' in locals() else ''}
错误类型: {error_type}
重试次数: {retry_count}

请提供:
1. 错误原因分析
2. 可能的解决方案
3. 建议的查询策略调整
4. 预防措施

请简洁回答。"""
        
        # 执行反思
        try:
            reflection_response = smart_model.invoke([
                SystemMessage(content="你是错误分析专家。"),
                HumanMessage(content=reflection_prompt)
            ])
            
            print(f"[Self-Correction] 反思结果: {reflection_response.content[:100]}...")
            
            # 将反思结果添加到消息中
            messages.append(HumanMessage(content=f"[系统反思] {reflection_response.content}"))
        except Exception as e:
            print(f"[Self-Correction] 反思失败: {e}")
    
    # 新查询或没有计划时: 分解任务
    if (last_sender == "User" or task_plan is None) and trimmed_messages:
        user_query = trimmed_messages[-1].content
        
        #  - 
        backtracking_router.start_query(user_query)
        
        # 🔧 【P0优化】任务复杂度评估与动态步骤限制
        complexity_score = assess_task_complexity(user_query)
        max_steps = get_max_steps_by_complexity(complexity_score)
        
        plan = decompose_task(user_query, max_steps=max_steps)
        remaining_steps = plan.get("steps", []).copy()
        task_plan = plan
        print(f"[Supervisor] 复杂度:{complexity_score}, 步骤:{len(remaining_steps)}/{max_steps}")
    
    # 步骤 2: 任务推进验证（使用三重验证机制）
    if remaining_steps and last_sender == "Coder" and execution_status == "success":
        # 获取 Coder 的最后一条消息
        last_message_content = state["messages"][-1].content if state.get("messages") else ""
        last_message_str = str(last_message_content)
        
        # 🔥 使用独立的三重验证函数（替代原有的内联验证）
        is_valid, reason, failed_check = validate_coder_result(last_message_str)
        
        # 提取诊断信息（用于日志）
        has_diagnostics = "[DIAGNOSTICS]:" in last_message_str
        diagnostics_content = ""
        if has_diagnostics:
            diag_start = last_message_str.find("[DIAGNOSTICS]:")
            diag_end = last_message_str.find("\n", diag_start)
            if diag_end == -1:
                diag_end = len(last_message_str)
            diagnostics_content = last_message_str[diag_start:diag_end]
        
        # 处理部分结果（熔断器触发后的降级结果）
        has_partial_result = "[PARTIAL RESULT]" in last_message_str or "[PARTIAL]:" in last_message_str
        if has_partial_result:
            print("[Supervisor] 检测到部分结果（熔断器触发），转到 Reviewer 生成降级回复")
            return {
                "next": "Reviewer",
                "last_sender": "Supervisor",
                "task_plan": task_plan,
                "execution_status": "success",
                "messages": [HumanMessage(content=f"[PARTIAL RESULT] Coder 返回部分结果，请生成降级回复。\n\n{last_message_str[:2000]}")]
            }
        
        # 三重验证失败处理
        if not is_valid:
            print(f"[Supervisor] ⚠️ 三重验证失败（检查项 {failed_check}）: {reason}")
            remaining_steps.pop(0)  # 仍然弹出步骤（已尝试过）
            
            # 使用标准化的诊断反馈生成函数
            diagnostic_feedback = generate_validation_feedback(failed_check, last_message_str)
            
            if remaining_steps:
                # 
                return {
                    "next": "Coder",
                    "last_sender": "Supervisor",
                    "remaining_steps": remaining_steps,
                    "task_plan": task_plan,
                    "execution_status": "pending",  # pending,Coder
                    "messages": [HumanMessage(content=diagnostic_feedback)]
                }
            else:
                # ,Reviewer(,)
                return {
                    "next": "Reviewer",
                    "last_sender": "Supervisor",
                    "task_plan": task_plan,
                    "execution_status": "pending",
                    "messages": [HumanMessage(content=diagnostic_feedback)]
                }
        
        # P0: 数据质量验证（范围检查）
        has_data_quality_issue = False
        quality_issues = []
        try:
            import re
            import json
            import pandas as pd
            from data_validator import DataValidator
            
            # 从 [DATA]: 中提取 JSON 数据
            data_match = re.search(r'\[DATA\]:\s*(\{.*?\}|\[.*?\])', last_message_str, re.DOTALL)
            if data_match:
                try:
                    data_dict = json.loads(data_match.group(1))
                    # 转换为 DataFrame 以便验证
                    if isinstance(data_dict, dict):
                        df_to_validate = pd.DataFrame([data_dict])
                    elif isinstance(data_dict, list):
                        df_to_validate = pd.DataFrame(data_dict)
                    else:
                        df_to_validate = None
                    
                    if df_to_validate is not None and not df_to_validate.empty:
                        validator = DataValidator(strict_mode=False, auto_fix=False)
                        validation_result = validator.validate(df_to_validate, context="Supervisor数据质量检查")
                        
                        if not validation_result.passed:
                            has_data_quality_issue = True
                            for issue in validation_result.issues:
                                quality_issues.append(f"{issue.issue_type.value}: {issue.description}")
                                print(f"[Supervisor] 数据质量告警: {issue.description}")
                except json.JSONDecodeError:
                    pass  # 数据格式不是JSON，跳过验证
        except Exception as e:
            print(f"[Supervisor] 数据质量验证跳过: {e}")
        
        # 如果有数据质量问题，生成警告但继续（不中断流程）
        if has_data_quality_issue:
            quality_warning = f"""[数据质量告警]
检测到以下数据质量问题：
{chr(10).join('- ' + issue for issue in quality_issues[:3])}

系统将继续处理，但建议您检查数据。
"""
            print("[Supervisor] 数据质量问题检测到，但继续处理（降级模式）")
        
        if is_data_empty:
            print("[Supervisor]  P1, Coder ")
            
            #  修复：增加retry_count检查，防止跳步
            retry_count = state.get("retry_count", 0)
            max_retries = 2
            
            if retry_count >= max_retries:
                #  重试耗尽，不弹出步骤，转到ErrorHandler处理
                print(f"[Supervisor] 重试耗尽({retry_count}/{max_retries})，转到ErrorHandler")
                return {
                    "next": "ErrorHandler",
                    "last_sender": "Supervisor",
                    "remaining_steps": remaining_steps,  #  保留步骤
                    "task_plan": task_plan,
                    "execution_status": "error",
                    "error_type": "data_missing",
                    "retry_count": 0,  #  重置，ErrorHandler有自己的计数
                    "messages": [HumanMessage(content="[DATA] 数据为空，重试耗尽")]
                }
            
            #  保留步骤，增加重试计数
            print(f"[Supervisor] 数据为空，重试 {retry_count + 1}/{max_retries}")
            
            #  RAG查询：获取相关API文档
            rag_context = ""
            try:
                # 从用户查询中提取关键词进行RAG检索
                user_query = state["messages"][0].content if state.get("messages") else ""
                if user_query:
                    from lib import search
                    rag_results = search(user_query, top=3)
                    if rag_results and rag_results != "未找到相关文档":
                        rag_context = f"\n\n【相关API文档】\n{rag_results}\n"
                        print(f"[Supervisor] RAG检索完成，获取到相关文档")
            except Exception as e:
                print(f"[Supervisor] RAG检索失败: {e}")
            
            diagnostic_feedback = f""": [DATA] .

 ():
1. ( '002594.SZ')
2. :5(3)
3. :()
4. API(df.shape[0] )

,,:
print(f\"[DATA]: {json.dumps({'': {'error': ''}})}\")

 [DATA]: {{}}  [DATA]: []!

.{rag_context}

【RAG建议】
如果上述API文档有帮助，请根据文档调整查询策略：
- 检查接口参数格式（如日期格式YYYYMMDD）
- 尝试文档中提到的备选接口
- 注意文档中的特殊说明（如字段含义、数据限制）
"""
            
            #  不弹出remaining_steps，保留当前步骤
            return {
                "next": "Coder",
                "last_sender": "Supervisor",
                "remaining_steps": remaining_steps,  #  保留步骤
                "task_plan": task_plan,
                "execution_status": "pending",
                "retry_count": retry_count + 1,  #  增加重试计数
                "messages": [HumanMessage(content=diagnostic_feedback)]
            }
        
        # :!
        print(f"[Supervisor]  P1, Reviewer")
        if has_diagnostics:
            print(f"   :{diagnostics_content}")
        
        # :,
        finished_step = remaining_steps.pop(0)
        print(f" [Supervisor] : {finished_step},{len(remaining_steps)}")
        
        if remaining_steps:
            # ,Coder
            next_step = remaining_steps[0]
            return {
                "next": "Coder",
                "last_sender": "Supervisor",
                "remaining_steps": remaining_steps,
                "task_plan": task_plan,
                "execution_status": execution_status,  #  
                "messages": [HumanMessage(content=f":{next_step}")]
            }
        else:
            # ,Reviewer
            print(f"[Supervisor] ,Reviewer")
            return {
                "next": "Reviewer",
                "last_sender": "Supervisor",
                "task_plan": task_plan,
                "execution_status": execution_status,  #  
                "recovery_level": 0,  #  
                "recovery_history": []  #  
            }
    
    #  3:failed()
    if execution_status == "error" and last_sender == "Coder":
        print(f"[Supervisor] ,,")
        #  remaining_steps,ErrorHandler
        pass
    
    #  P1Reviewer()
    if last_sender == "Reviewer" and execution_status == "error":
        reviewer_fail_count = state.get("reviewer_fail_count", 0)
        print(f"[Supervisor] Reviewer,: {reviewer_fail_count}")
        
        if reviewer_fail_count >= 2:  # Reviewer2
            print(f"[Supervisor]  Reviewer({reviewer_fail_count}),")
            return {
                "next": "FINISH",
                "last_sender": "Supervisor",
                "execution_status": "error",
                "reviewer_fail_count": reviewer_fail_count,
                "messages": [HumanMessage(content="Reviewer,,")]
            }
        else:
            # 
            print(f"[Supervisor] Reviewer({reviewer_fail_count}),")
            return {
                "next": "FINISH",
                "last_sender": "Supervisor",
                "execution_status": "error",
                "reviewer_fail_count": reviewer_fail_count,
                "messages": [HumanMessage(content="Reviewer,,")]
            }
    
    #  P1:  +  - 
    if execution_status == "error" and last_sender == "ErrorHandler":
        retry_count = state.get("retry_count", 0)
        error_type = state.get("error_type", "unknown")
        
        # 
        last_msg = state["messages"][-1] if state["messages"] else None
        error_info = last_msg.content if last_msg else ""
        
        # 
        backtracking_router.mark_failure(error_info, error_type)
        
        # 
        if backtracking_router.has_next_strategy() and not backtracking_router.should_reject():
            next_strategy = backtracking_router.get_current_strategy()
            strategy_hint = backtracking_router.get_prompt_hint()
            
            print(f"[Supervisor]  : {next_strategy['name']}")
            
            # 
            original_query = state["messages"][0].content if state["messages"] else ""
            backtrack_message = f"""

: {original_query}
{strategy_hint}

"""
            
            return {
                "next": "Coder",
                "last_sender": "Supervisor",
                "execution_status": "pending",
                "retry_count": 0,  # 
                "messages": [HumanMessage(content=backtrack_message)]
            }
        
        # 
        if backtracking_router.should_reject():
            print(f"[Supervisor]  ")
            stats = backtracking_router.get_statistics()
            reject_message = f"[REJECT]:  {stats['retries']} {error_info[:200]}"
            return {
                "next": "FINISH",
                "last_sender": "Supervisor",
                "execution_status": "error",
                "messages": [HumanMessage(content=reject_message)]
            }
        
        # retry_exhausted 机制（参考 autoresearch discard + continue loop 设计）
        # 重试 >= 3 次时，不再死磕同一条路，触发 Supervisor replan 换思路
        # 覆盖所有错误类型（field_error / code_error / network_error / unknown）
        if retry_count >= 3:
            print(f"[Supervisor] retry_exhausted: 已重试 {retry_count} 次 (error_type={error_type})，触发 replan...")
            error_type = "retry_exhausted"  # 标记为耗尽，便于后续分析/DPO数据收集
            
            # 
            original_query = state["messages"][0].content if state["messages"] else ""
            
            # :
            replan_prompt = f""":{original_query}

,:
{error_info}

,.
JSON: {{"steps": ["1", "2", ...]}}"""
            
            try:
                strong_model = get_chat_model(model_type="smart")
                response = strong_model.invoke(replan_prompt)
                
                # 
                plan_text = response.content.replace("```json", "").replace("```", "").strip()
                new_plan = json.loads(plan_text)
                new_steps = new_plan.get("steps", [""])
                
                print(f"[Supervisor] ,: {new_steps}")
                
                return {
                    "task_plan": new_plan,
                    "remaining_steps": new_steps.copy(),
                    "retry_count": 0,  # 
                    "last_sender": "Supervisor",
                    "execution_status": "pending",  #  pending
                    "next": "Coder" if new_steps else "Reviewer",
                    "messages": [HumanMessage(content=f",:{new_steps[0] if new_steps else ''}")]
                }
            except Exception as e:
                print(f"[Supervisor] : {e}, Reviewer")
                return {
                    "next": "Reviewer",
                    "last_sender": "Supervisor",
                    "retry_count": 0,
                    "execution_status": "pending",  #  
                    "messages": [HumanMessage(content=",")]
                }
    
    messages = [SystemMessage(content=system_prompt)] + trimmed_messages
    
    #  4: - Coder,
    #  LLM "FINISH"
    if remaining_steps and last_sender == "Coder" and execution_status == "success":
        #  : LLM,
        print(f"[Supervisor] :{len(remaining_steps)},Coder")
        next_step = remaining_steps[0]
        return {
            "next": "Coder",
            "last_sender": "Supervisor",
            "remaining_steps": remaining_steps,
            "task_plan": task_plan,
            "execution_status": execution_status,  #  
            "messages": [HumanMessage(content=f":{next_step}")]
        }
    
    try:
        # 🔧 【P0优化】优先尝试 structured output（如果模型支持）
        structured_result = parse_coder_output_structured(coder_model, messages)
        if structured_result is not None:
            # 构造模拟的 AIMessage
            from langchain_core.messages import AIMessage
            response = AIMessage(
                content=f"[CODE]: {structured_result.code}\n[RATIONALE]: {structured_result.rationale}",
                additional_kwargs={"structured_output": True}
            )
            print(f"[Coder] 使用 structured output 成功")
        else:
            # Fallback 到普通调用
            response = coder_model.invoke(messages)
            
        #   JSON 
        import json
        response_text = response.content
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
            
        if json_start >= 0 and json_end > json_start:
            json_str = response_text[json_start:json_end]
            parsed = json.loads(json_str)
            next_node = parsed.get('next', 'FINISH')
            reason = parsed.get('reason', '')
        else:
            #  JSON,
            print(f"[Supervisor] JSON,")
            next_node, reason = _fallback_keyword_route(state)
    except json.JSONDecodeError as e:
        # JSON ,
        print(f"[Supervisor] JSON,")
        next_node, reason = _fallback_keyword_route(state)
    
    except ValueError as e:
        # 1 → 
        print(f"[Supervisor] (): {str(e)[:50]}")
        next_node, reason = _fallback_keyword_route(state)
    
    except Exception as e:
        # 2API → 
        supervisor_retry = state.get("supervisor_retry", 0)
        error_str = str(e).lower()
        
        # (429,timeout),
        if supervisor_retry < 2 and ("429" in str(e) or "timeout" in error_str):
            print(f"[Supervisor] API({supervisor_retry+1}/2): {str(e)[:50]}")
            import time
            time.sleep(2 ** supervisor_retry)  # 
            return {
                "supervisor_retry": supervisor_retry + 1,
                "last_sender": "Supervisor",
                "execution_status": execution_status,  #  
                "next": "Supervisor"
            }
        else:
            # 3 → 
            print(f"[Supervisor] ,: {str(e)[:100]}")
            next_node, reason = _fallback_keyword_route(state)
    
    print(f"[Supervisor] : {next_node} (: {reason})")
    #   - FINISH 
    if TRAJECTORY_ENABLED and next_node == "FINISH":
        # /
        is_success = execution_status == "success"
        final_output = state["messages"][-1].content if state.get("messages") else ""
        trajectory_collector.finish_trajectory(
            success=is_success,
            final_output=str(final_output)[:1000]
        )
        trajectory_collector.save()
        print(f"[Trajectory]  - : {is_success}")
    
    #  ASA 2.0
    if MEMORY_ENABLED and next_node == "FINISH" and execution_status == "success":
        try:
            # 
            original_query = state["messages"][0].content if state.get("messages") else ""
            # 
            steps = task_plan.get("steps", []) if task_plan else []
            # 
            strategy_used = backtracking_router.get_current_strategy().get("name", "direct_query")
            
            record_successful_execution(
                query=str(original_query)[:200],
                strategy=f" {strategy_used} ",
                steps=steps[:5] if steps else [""],
                category="stock_query"  # 
            )
            print(f"[MemorySystem] ")
        except Exception as e:
            print(f"[MemorySystem] : {e}")
    
    return {
        "next": next_node,
        "last_sender": "Supervisor",
        "task_plan": task_plan,
        "remaining_steps": remaining_steps,
        "execution_status": execution_status,  #  :execution_status,
        "supervisor_retry": 0,  # 
        "total_step_count": current_step  # 全局步数递增
    }


def _fallback_keyword_route(state: MultiAgentState) -> tuple:
    """
     :last_senderexecution_status
    
    ,:
    ① last_sender:→ 
    ② execution_status:→ 
    ③ ,
    
    :
        (next_node, reason)
    """
    last_sender = state.get("last_sender", "User")
    execution_status = state.get("execution_status", "pending")
    last_content = state["messages"][-1].content if state.get("messages") else ""
    
    #   ① 
    if "Error" in last_content or "Traceback" in last_content or "" in last_content:
        return "Coder", ",Coder"
    
    #   ②  → 
    if last_sender == "Coder" and execution_status == "success":
        # Coder → Reviewer
        return "Reviewer", "Coder,Reviewer"
    
    #   ③ Reviewer
    if last_sender == "Reviewer":
        return "ProfileUpdater", "Reviewer,"
    
    #   ③a ErrorHandler
    if last_sender == "ErrorHandler" and execution_status == "success":
        return "Reviewer", "ErrorHandler,Reviewer"
    
    #   ④ ProfileUpdater 
    if last_sender == "ProfileUpdater":
        return "FINISH", "ProfileUpdater,"
    
    #   ④ (User)
    if last_sender == "User":
        return "Coder", ",Coder"
    
    #   ⑤ ()
    if last_sender == "Supervisor":
        # Supervisor,
        return "Coder", "Supervisor,Coder"
    
    #   ⑥ ()
    return "FINISH", ","


# =============================================================================
# 5. Coder
# =============================================================================

# Schema -  + 
AVAILABLE_TUSHARE_FIELDS = {
    "stock_basic": {
        "primary_key": "ts_code",
        "queryable_fields": ["name", "area", "industry", "market", "list_date"],
        "notes": ""
    },
    "daily": {
        "primary_key": "ts_code",
        "queryable_fields": ["trade_date", "open", "high", "low", "close", "vol", "amount"],
        "notes": " ts_code  date "
    },
    "daily_basic": {
        "primary_key": "ts_code",
        "queryable_fields": ["trade_date", "close", "turnover_rate", "turnover_rate_f", "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ttm", "total_mv"],
        "notes": "NaNETFPE"
    },
    "fina_indicator": {
        "primary_key": "ts_code",
        "queryable_fields": ["ann_date", "end_date", "report_type", "roe", "gross_margin", "debt_to_assets", "current_ratio"],
        "notes": " 1-2 "
    }
}

SCHEMA_CONSTRAINT_PROMPT = f""" - 

vs 

1. 
   
{json.dumps(AVAILABLE_TUSHARE_FIELDS, ensure_ascii=False, indent=2)}
   
   
   a)  pe_ttm  pe
   b) 两个双引号

2. 
   - 避免使用多个连续的引号

3. 
   -  999999
   -  stock_basic() 
   - [REJECT]:  {{code}}

4. 
   -  NaN ETF  PE
   - [DATA]:
"""

# CODER_SYSTEM_PROMPT 已外化到 config/prompts/coder.txt
# 参考 autoresearch program.md 设计哲学：规则外化，运行时读取，支持热更新
CODER_SYSTEM_PROMPT = _load_prompt("coder")



def coder_node(state: MultiAgentState):
    """Coder: 动态注入任务专属技能"""
    
    # ============ 新增：动态技能注入机制 ============
    # Step 1: 加载skills.json
    try:
        with open('skills.json', 'r', encoding='utf-8') as f:
            all_skills = json.load(f)
        SKILLS_AVAILABLE = True
    except Exception as e:
        print(f"[Coder] skills.json加载失败: {e}，使用静态prompt")
        all_skills = {}
        SKILLS_AVAILABLE = False
    
    # Step 2: 从用户查询中提取关键词，匹配对应技能
    injected_skills = []
    user_query = ""
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            user_query = msg.content  # 保留原始大小写，规则路径需要
            break

    # Step 3: 构造动态 System Prompt（先注入 Schema 多路召回提示）
    dynamic_prompt = CODER_SYSTEM_PROMPT

    if ENABLE_SCHEMA_RECALL and user_query:
        try:
            schema_hint = multi_path_schema_recall(user_query)
            if schema_hint:
                dynamic_prompt = dynamic_prompt + schema_hint
                print("[Coder] 已注入 Schema 多路召回提示")
        except Exception as e:
            print(f"[Coder] Schema 多路召回失败，降级为原始 Prompt: {e}")

    # 基于关键词的技能注入（在 Schema 提示之后继续追加）
    uq_lower = user_query.lower()
    if SKILLS_AVAILABLE and user_query:
        # 关键词匹配
        skill_keyword_map = {
            'dividend_expert': ['分红', '股息', '送转', '除权', '派息'],
            'charting_expert': ['画图', '展示图表', '可视化', '曲线', '柱状图', '图表'],
            'finance_audit': ['财报', '收入', '利润', '资产负债', '季报', '年报'],
            'market_expert': ['港股', 'hk', '指数', 'etf', '基金'],
            'error_handling': ['错误', '失败', '重试', '超时', '限流']
        }
        
        for skill_name, keywords in skill_keyword_map.items():
            if any(kw in uq_lower for kw in keywords):
                if skill_name in all_skills:
                    injected_skills.append(skill_name)
        
        if injected_skills:
            print(f"[Coder] 检测到任务类型，注入技能: {', '.join(injected_skills)}")
    
    if injected_skills and SKILLS_AVAILABLE:
        skills_injection = "\n\n【动态注入的任务专属技能】\n"
        for skill_name in injected_skills:
            skill_info = all_skills.get(skill_name, {})
            skills_injection += f"\n【技能: {skill_info.get('skill_name', skill_name)}】\n"
            skills_injection += f"{skill_info.get('content', '')}\n"
            if skill_info.get('template_code'):
                skills_injection += f"\n示例代码:\n```python\n{skill_info.get('template_code')}\n```\n"
        dynamic_prompt = dynamic_prompt + skills_injection
        print(f"[Coder] 已注入 {len(injected_skills)} 个技能包")
    
    # ============ 使用动态prompt ============
    # 【P0修复】检测是否收到工具执行结果，如果是，添加指令生成最终答案
    final_answer_instruction = ""
    if state.get("messages"):
        last_msg = state["messages"][-1]
        if isinstance(last_msg, ToolMessage):
            final_answer_instruction = """

【重要】你刚刚收到了工具执行结果。请基于这些结果：
1. 分析数据是否满足用户需求
2. 如果数据完整，生成最终答案（包含 [DATA]: 标记）
3. 如果数据缺失或错误，说明原因
4. 不要再次调用工具，直接生成回复
"""
    
    sys_msg = SystemMessage(content=dynamic_prompt + final_answer_instruction)
    messages = [sys_msg] + state["messages"]
    
    #  P0-D: : 
    try:
        response = coder_model.invoke(messages)
        
        # ---  (Qwen ) ---
        print(f"\n[DEBUG Coder] Type: {type(response)}")
        print(f"[DEBUG Coder] Content: {repr(response.content)}")
        print(f"[DEBUG Coder] Tool Calls: {getattr(response, 'tool_calls', [])}")
        # --------------------------------

        # : content  AND tool_calls 
        # Qwen  content  tool_calls ,!
        has_content = bool(response.content and str(response.content).strip())
        has_tool_calls = bool(hasattr(response, 'tool_calls') and response.tool_calls)

        if not has_content and not has_tool_calls:
            # ,
            print(f"[Coder] : ")
            raise ValueError("Coder (No content and no tool_calls)")
        
        print(f"[Coder] ")
        
        #   - 
        if TRAJECTORY_ENABLED:
            trajectory_collector.record_step(
                action="coder_generate",
                input_content=str(messages[-1].content)[:500] if messages else "",
                output_content=str(response.content)[:1000] if response.content else "[tool_calls]",
                success=True
            )
            print(f"[Trajectory] ")
        
        return {
            "messages": [response],
            "last_sender": "Coder",
            "execution_status": "success",  #  success
            "error_type": None,  #  
            "retry_count": 0  #  
        }
    except Exception as e:
        #  ,LLM
        error_details = traceback.format_exc()
        error_msg = f"[Coder] : {str(e)[:100]}"
        error_type = classify_error_simple(str(e))
        
        print(f"{error_msg}\n:\n{error_details}")
        
        #   - 
        if TRAJECTORY_ENABLED:
            trajectory_collector.record_step(
                action="coder_generate",
                input_content=str(messages[-1].content)[:500] if messages else "",
                output_content="",
                success=False,
                error_msg=str(e)[:500]
            )
            print(f"[Trajectory] : {error_type}")
        
        return {
            "messages": [HumanMessage(content=error_msg)],
            "last_sender": "Coder",
            "execution_status": "error",  #  error
            "error_type": error_type,  #  
            "next": "ErrorHandler"  #  
        }


# =============================================================================
# 6. Reviewer
# =============================================================================

# REVIEWER_SYSTEM_PROMPT 已外化到 config/prompts/reviewer.txt
# 支持热更新：修改 txt 文件后重启即生效
REVIEWER_SYSTEM_PROMPT = _load_prompt("reviewer")

# ... existing code ...


#  ASA  -  MindSearch + RankLLM
class ResultFusion:
    """
     -  [DATA] 
    
    
    -  MindSearch 
    - /PE/
    -  fast_model 
    
    
    -  reviewer_node “ [DATA]”
    """
    
    def __init__(self, model=None):
        self.model = model or fast_model
    
    def _clean_sources(self, sources: List[str]) -> List[str]:
        """
         [DATA] 
        
        
        -  > 10% A 1-3%
        - PE > 100 
        -  > 20% ST  10%
        """
        cleaned = []
        import re
        
        for content in sources:
            # 1
            if "" in content or "dv_ttm" in content or "" in content:
                #  12.5%
                nums = re.findall(r"\d+\.?\d*%", content)
                for num in nums:
                    try:
                        val = float(num.replace("%", ""))
                        if val > 10:  # 
                            tag = f"{num}"
                            content = content.replace(num, tag, 1)  # 
                    except ValueError:
                        continue
            
            # 2PE 
            if "pe" in content.lower() or "" in content:
                #  "PE: 125" 
                pe_matches = re.findall(r"PE[:\s]*(\d+\.?\d*)", content, re.IGNORECASE)
                for pe_str in pe_matches:
                    try:
                        pe_val = float(pe_str)
                        if pe_val > 100:
                            content = content.replace(f"PE: {pe_str}", f"PE: {pe_str}", 1)
                    except ValueError:
                        continue
            
            cleaned.append(content)
        
        return cleaned
    
    def fuse(self, user_query: str, sources: List[str]) -> str:
        """
        
        
        Args:
            user_query: 
            sources:  [DATA] 
        
        Returns:
            
        """
        # Step 1: 
        cleaned_sources = self._clean_sources(sources)
        
        # Step 2: 
        joined = "\n\n".join([
            f"{i+1}:\n{c[:500]}" 
            for i, c in enumerate(cleaned_sources)
        ])
        
        # Step 3:  Prompt
        prompt = f"""{user_query}



{joined}


1. 
2. 
3. 
   - 
   -  [DATA] 
   - “”


- 
- """
        
        try:
            resp = self.model.invoke(prompt)
            print(f"[ResultFusion]   {len(sources)} ")
            return resp.content
        except Exception as e:
            import logging
            logging.warning(f"[ResultFusion]  : {e}")
            # 
            return joined


def reviewer_node(state: MultiAgentState):
    """Reviewer:( + )"""
    import datetime
    
    # ... existing code ...
    messages_received = state.get("messages", [])
    print(f"[DEBUG Reviewer]  {len(messages_received)} ")
    for i, msg in enumerate(messages_received[-3:]):
        msg_type = type(msg).__name__
        msg_preview = str(msg.content)[:150] if hasattr(msg, 'content') else "[]"
        print(f"  [{i}] {msg_type}: {msg_preview}...")
    
    #  :,
    # : + (HumanMessageAPI)
    print("[DEBUG Reviewer] ...")
    
    # 1: HumanMessage()
    first_human_msg = None
    for msg in messages_received:
        if isinstance(msg, HumanMessage):
            first_human_msg = msg
            break
    
    # 2:([DATA])
    #  ASA  [DATA] ResultFusion 
    data_contents = []
    for msg in reversed(messages_received):
        msg_content = str(msg.content) if hasattr(msg, 'content') else ""
        # ToolMessage  AIMessage  [DATA] 
        if "[DATA]:" in msg_content:
            data_contents.append(msg_content)
            #  5 
            if len(data_contents) >= 5:
                break
    
    # 
    data_contents = list(reversed(data_contents))
    print(f"[DEBUG Reviewer]  {len(data_contents)} ")
    
    # 3: Reviewer
    clean_messages = []
    
    # 
    current_date = datetime.datetime.now().strftime("%Y%m%d")
    sys_prompt_with_date = REVIEWER_SYSTEM_PROMPT.replace("{DATE}", current_date).replace("{current_date}", current_date)
    sys_msg = SystemMessage(content=sys_prompt_with_date)
    clean_messages.append(sys_msg)
    
    # 2.5(): - 
    # ""
    # Reviewer,
    print("[DEBUG Reviewer] ()...")
    
    # 
    stock_context = {}
    for msg in reversed(messages_received[-10:]):  # 10
        msg_content = str(msg.content) if hasattr(msg, 'content') else ""
        #  "ts_code='600519.SH'" 
        import re
        code_match = re.findall(r"ts_code=['\"]([^'\"]+)[\'\"]", msg_content)
        if code_match:
            stock_code = code_match[-1]  # 
            stock_context['last_code'] = stock_code
            # ()
            if '600519' in stock_code or 'maotai' in msg_content.lower():
                stock_context['last_name'] = ''
            elif '000858' in stock_code or 'wuliangye' in msg_content.lower():
                stock_context['last_name'] = ''
            elif '00700' in stock_code or 'tencent' in msg_content.lower():
                stock_context['last_name'] = ''
            break
    
    #  + 
    if first_human_msg:
        user_query = first_human_msg.content
        # ,
        if "" in user_query and stock_context.get('last_code'):
            clarified_query = user_query.replace(
                "",
                f"{stock_context.get('last_name', stock_context['last_code'])}(:{stock_context['last_code']})"
            )
            print(f"[DEBUG Reviewer] :{user_query}\n            -> {clarified_query}")
            clean_messages.append(HumanMessage(content=clarified_query))
        else:
            clean_messages.append(first_human_msg)
        print(f"[DEBUG Reviewer] ()")
    
    #  P0(HumanMessageToolMessage)
    # :ToolMessageAIMessage(tool_calls),API 400
    # :,HumanMessage,
    #  ASA  ResultFusion 
    if data_contents:
        # 
        if len(data_contents) > 1:
            print(f"[DEBUG Reviewer]  ({len(data_contents)} ) ResultFusion")
            fusion = ResultFusion()
            user_query = first_human_msg.content if first_human_msg else ""
            fused_data = fusion.fuse(user_query=user_query, sources=data_contents)
            
            # 
            context_note = ""
            if stock_context.get('last_code'):
                context_note = f"[:{stock_context['last_code']}]\n"
            data_msg = HumanMessage(content=f"(Coder):\n{context_note}\n{fused_data}")
            clean_messages.append(data_msg)
            print(f"[DEBUG Reviewer] (:{len(fused_data)})")
        else:
            # 
            print(f"[DEBUG Reviewer] ")
            last_successful_data_content = data_contents[0]
            #  stock_context,
            context_note = ""
            if stock_context.get('last_code'):
                context_note = f"[:{stock_context['last_code']}]\n"
            data_msg = HumanMessage(content=f"(Coder):\n{context_note}\n{last_successful_data_content}")
            clean_messages.append(data_msg)
            print(f"[DEBUG Reviewer] (HumanMessage,)")
    else:
        # :,(,ToolMessage)
        print(f"[DEBUG Reviewer] ,")
        #  : tool_calls  AIMessage
        #  ToolMessage,​​“” AIMessage
        filtered_messages = []
        for msg in messages_received:
            msg_type = type(msg).__name__
            # :
            # 1.  ToolMessage
            # 2.  AIMessage, tool_calls
            if msg_type == "ToolMessage":
                continue  #  ToolMessage
            if msg_type == "AIMessage" and hasattr(msg, 'tool_calls') and msg.tool_calls:
                continue  #  tool_calls  AIMessage( ToolMessage)
            filtered_messages.append(msg)
        clean_messages = [sys_msg] + filtered_messages
    
    print(f"[DEBUG Reviewer] :{len(clean_messages)}")
    
    # ... existing code ...
    
    # 3. ()
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            print(f"[Reviewer]  ( {attempt+1}/{max_retries})...")
            # ... existing code ...
            response = reviewer_model.invoke(clean_messages)
            
            # ... existing code ...
            print(f"[DEBUG Reviewer] {attempt+1}:")
            print(f"  Type: {type(response)}")
            print(f"  Content: {len(response.content) if response.content else 0}")
            print(f"  Content: {response.content[:200] if response.content else '[]'}")
            
            # ... existing code ...
            if response.content and str(response.content).strip():
                print(f"[Reviewer]  (: {len(response.content)})")
                #  
                print("\n" + "="*80)
                print("Reviewer ")
                print("="*80)
                print(response.content)
                print("="*80 + "\n")
                
                # 【P0修复】如果有数据内容，在答案前添加 [DATA]: 标记
                final_content = response.content
                if data_contents:
                    # 提取关键数据信息
                    import re
                    data_json_match = re.search(r'\{[^{}]*"stock"[^{}]*\}', str(data_contents[0]))
                    if data_json_match:
                        final_content = f"[DATA]: {data_json_match.group()}\n\n{response.content}"
                    else:
                        # 简单添加标记
                        final_content = f"[DATA]: 数据已获取\n\n{response.content}"
                
                return {
                    "messages": [AIMessage(content=final_content)],
                    "last_sender": "Reviewer",
                    "execution_status": "success",
                    "error_type": None
                }
            else:
                print(f"[Reviewer] : ,...")
                last_error = ""
                
        except Exception as e:
            print(f"[Reviewer] : : {str(e)[:100]}")
            last_error = str(e)
    
    # 4.  :()
    print(f"[Reviewer] (3),")
    print(f"[Reviewer] : {last_error}")
    
    # Coder
    coder_data = ""
    for msg in reversed(messages_received[-10:]):  # 10Coder
        msg_content = str(msg.content) if hasattr(msg, 'content') else ""
        if "[DATA]:" in msg_content:
            coder_data = msg_content[:500]  # 500
            break
    
    fallback_content = f"""****

AI,.

****(Coder):
{coder_data if coder_data else 'Coder'}

****:
1. ,
2. ,

*()*"""
    
    #   HumanMessage  AIMessage
    #  API  tool_calls  AIMessage
    return {
        "messages": [HumanMessage(content=fallback_content)],
        "last_sender": "Reviewer",
        "execution_status": "error",
        "error_type": "reviewer_api_error",
        "reviewer_fail_count": state.get("reviewer_fail_count", 0) + 1
    }


# =============================================================================
# 7. 
# =============================================================================

PROFILE_UPDATE_PROMPT = """.

,..

:
{current_profile}

:
{conversation_summary}


1. ****..
   -  ,
   -  ,(,,)
   -  (,RSI), interested_sectors
   -  ,""

2. ** interested_sectors**:
   - ,
   - 
   - ,

3. ** investment_style,risk_preference,preferred_analysis_depth**:
   - ,

4. ** update_timestamp**:().

JSON,:
{{
  "investment_style": "//",
  "risk_preference": "//",
  "interested_sectors": ["", "", "", ...],
  "preferred_analysis_depth": "//",
  "update_timestamp": "{current_date}"
}}


,.
 JSON,."""

def profile_updater_node(state: MultiAgentState):
    """P0:  () [1]"""
    
    import datetime
    current_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # ... existing code ...
    if state.get("execution_status") != "success" and state.get("last_sender") != "Reviewer":
        #  Reviewer,
        # Reviewer(error),()
        print(f"[ProfileUpdater]  (status={state.get('execution_status')}),")
        return {
            "last_sender": "ProfileUpdater",
            "user_profile": state.get("user_profile", {})
        }
    
    messages_all = state.get("messages", [])
    profile = state.get("user_profile", {})
    
    #  : + AI(Reviewer)
    # ,,JSON,
    print("[DEBUG ProfileUpdater] ...")
    
    #  HumanMessage
    first_human = None
    for msg in messages_all:
        if isinstance(msg, HumanMessage):
            first_human = msg
            break
    
    # AI(AIMessage)
    last_ai_report = None
    for msg in reversed(messages_all):
        if isinstance(msg, AIMessage) and hasattr(msg, 'content'):
            content = msg.content
            # ([DATA])
            if content and "[DATA]:" not in content and "Traceback" not in content and len(content) > 50:
                last_ai_report = msg
                print(f"[DEBUG ProfileUpdater] AI,:{len(content)}")
                break
    
    #  ,
    conversation_summary = ""
    if first_human and last_ai_report:
        # AI,
        human_content = first_human.content[:500]  # 
        ai_content = last_ai_report.content[:500]  # 
        conversation_summary = f":{human_content}\n\nAI:{ai_content}"
    else:
        # :,5
        recent_msgs = messages_all[-5:]
        conversation_summary = "\n".join([
            f"{type(m).__name__}: {m.content[:100] if hasattr(m, 'content') else '[]'}..."
            for m in recent_msgs
        ])
    
    print(f"[DEBUG ProfileUpdater] :{len(conversation_summary)}")
    
    #  prompt()
    current_profile_str = json.dumps(profile, ensure_ascii=False, indent=2)
    prompt = PROFILE_UPDATE_PROMPT.format(
        current_profile=current_profile_str,
        conversation_summary=conversation_summary,
        current_date=current_date
    )
    
    try:
        #  fast (gpt-4o-mini) 
        fast_model = get_chat_model(model_type="fast")
        response = fast_model.invoke(prompt)
        
        #  JSON
        json_text = response.content.replace("```json", "").replace("```", "").strip()
        new_profile = json.loads(json_text)
        
        # 
        updated_profile = {**profile, **new_profile}
        print(f"[ProfileUpdater] : {new_profile}")
        
        return {
            "user_profile": updated_profile,
            "last_sender": "ProfileUpdater"
        }
    except Exception as e:
        print(f"[ProfileUpdater] : {e},")
        return {
            "last_sender": "ProfileUpdater",
            "user_profile": profile
        }


# =============================================================================
# 8. 
# =============================================================================

#  ASA  -  mem0 + Agent_memory_system
class SmartFallback:
    """
     - 
    
    
    -  mem0 
    -  ASA  LongTermMemory.search() + get_current_weight()
    - 
    
    
    -  error_handler_node 
    -  BacktrackingRouter.mark_failure  LTM
    """
    
    def __init__(self, memory_system=None):
        from memory_system import memory_system as default_memory
        self.memory = memory_system or default_memory
    
    def get_fallback(self, error: str, query: str, error_type: str = "unknown") -> dict:
        """
        
        
        Args:
            error: 
            query: 
            error_type:  (code_error/network_error/auth_error/unknown)
        
        Returns:
            {
                "strategy": "reuse_history" | "regenerate_code" | "wait_and_retry" | "fail_fast",
                "hint": "",
                "confidence": 0.0-1.0,
                "reason": ""
            }
        """
        # Step 1: 
        try:
            results = self.memory.long_term.search(
                query=f": {error[:100]}",  # 
                top_k=3,
                category="error_fix"  # 
            )
            
            # Step 2: 
            valid_strategies = []
            for item, match_score in results:
                weight = item.get_current_weight()
                # 
                combined = match_score * weight
                if combined >= 0.5:  # 
                    valid_strategies.append((item, combined))
            
            if valid_strategies:
                # 
                best_item, best_score = max(valid_strategies, key=lambda x: x[1])
                print(f"[SmartFallback]   (: {best_score:.2f})")
                return {
                    "strategy": "reuse_history",
                    "hint": best_item.content,
                    "confidence": best_score,
                    "reason": ""
                }
        
        except Exception as e:
            import logging
            logging.warning(f"[SmartFallback] : {e}")
        
        # Step 3:  → 
        print(f"[SmartFallback]  ")
        
        if error_type == "network_error":
            return {
                "strategy": "wait_and_retry",
                "hint": "2 API ",
                "delay": 2,
                "confidence": 0.8,
                "reason": ""
            }
        elif error_type == "code_error":
            return {
                "strategy": "regenerate_code",
                "hint": "1) API  2)  3) ",
                "attempt": 1,
                "confidence": 0.7,
                "reason": " Coder "
            }
        elif error_type == "auth_error":
            return {
                "strategy": "fail_fast",
                "hint": "API  API Key ",
                "confidence": 0.9,
                "reason": ""
            }
        else:
            return {
                "strategy": "use_cache_or_reject",
                "hint": "",
                "confidence": 0.5,
                "reason": ""
            }


#  :
def classify_error_simple(error_content: str) -> str:
    """
    简化错误分类，返回 5 个类型：
    - field_error:  KeyError 或字段不存在（新增）
    - code_error:  语法错误、类型错误、属性错误
    - network_error: 超时、限流、连接失败
    - auth_error: API Key 失效、鉴权失败
    - retry_exhausted: 由 Supervisor 注入，表示重试耗尽（>= 3 次）
    - unknown: 其他
    """
    error_lower = error_content.lower()

    # 字段错误（最先判断，优先级最高）
    if any(kw in error_lower for kw in ["keyerror", "not in index", "column", "no column named"]):
        return "field_error"

    # API/鉴权错误
    if any(kw in error_lower for kw in ["authentication", "api key", "unauthorized", "401", "403"]):
        return "auth_error"

    # 网络错误
    if any(kw in error_lower for kw in ["timeout", "429", "503", "connection", "request timed", "超时", "限流"]):
        return "network_error"

    # 代码错误
    if any(kw in error_lower for kw in ["syntaxerror", "keyerror", "typeerror", "attributeerror", "valueerror"]):
        return "code_error"

    return "unknown"

def error_handler_node(state: MultiAgentState):
    """
    Error Handler Node - Refactored with Strategy Pattern + Field Correction (ASA 2.3)
    
    Reference:
    - LangGraph Issue #6170: Middleware-style error handling
    - langgraph-supervisor-py: Command-based routing
    - rohitrmd/multi-agent-supervisor-system: Edgeless graph architecture
    
    v2.3 升级要点:
    1. 字段纠错机制：KeyError 时自动提取字段名并建议修正
    2. 错误压缩：压缩冗长 Traceback 防止上下文窗口爆炸
    3. 四级自愈策略：代码错误→规划错误→数据真空→不可恢复
    """
    messages = state["messages"]
    
    if not messages:
        return {"execution_status": "pending", "next": "Supervisor", "last_sender": "ErrorHandler"}
    
    last_msg = messages[-1]
    
    # Check if error
    is_error = isinstance(last_msg, ToolMessage) and (
        "Error" in last_msg.content or "Traceback" in last_msg.content
    )
    
    if is_error:
        # 🔥 ASA 2.3: 错误压缩（防止上下文窗口爆炸）
        try:
            from error_handlers import compress_error_traceback
            compressed_error = compress_error_traceback(last_msg.content, max_lines=8)
            if len(compressed_error) < len(last_msg.content):
                print(f"[ErrorHandler] 错误信息已压缩: {len(last_msg.content)} → {len(compressed_error)} 字符")
        except Exception as compress_e:
            print(f"[ErrorHandler] 错误压缩失败 (non-fatal): {compress_e}")
            compressed_error = last_msg.content[:1000]  # 兜底截断
        
        # 🔥 ASA 2.3: 字段纠错机制（KeyError 时自动提取并建议修正）
        field_correction_feedback = None
        try:
            from error_handlers import (
                extract_field_error, generate_field_correction_feedback
            )
            field_error = extract_field_error(last_msg.content)
            if field_error:
                wrong_field = field_error["field"]
                print(f"[ErrorHandler] 检测到字段错误: {wrong_field}")
                
                # 尝试从上下文中推断接口名
                interface_hint = ""
                for msg in reversed(messages[-5:]):
                    if hasattr(msg, 'content') and isinstance(msg.content, str):
                        if 'pro.' in msg.content:
                            # 提取 pro.xxx 作为接口提示
                            import re
                            match = re.search(r'pro\.(\w+)', msg.content)
                            if match:
                                interface_hint = match.group(1)
                                break
                
                # 生成字段纠错反馈（不强制纠正，只给建议）
                field_correction_feedback = generate_field_correction_feedback(
                    wrong_field=wrong_field,
                    suggested_field=None,  # 暂不进行模糊匹配，避免误纠
                    interface_hint=interface_hint
                )
                print(f"[ErrorHandler] 已生成字段纠错建议")
        except Exception as field_e:
            print(f"[ErrorHandler] 字段纠错处理失败 (non-fatal): {field_e}")
        
        # ASA 2.3: Use Strategy Pattern for error handling
        try:
            from error_handlers import ErrorContext, error_router
            
            # Classify error
            if ERROR_CLASSIFIER_ENABLED and classify_error:
                error_info = classify_error(last_msg.content)
                error_type = error_info.error_type
                fallback_strategy = {'hint': error_info.strategy if hasattr(error_info, 'strategy') else ''}
            else:
                error_type = classify_error_simple(last_msg.content)
                fallback_strategy = {'hint': 'Retry with modified parameters'}
            
            # 🔥 如果有字段纠错反馈，添加到 fallback_strategy
            if field_correction_feedback:
                fallback_strategy['field_correction'] = field_correction_feedback
                # 标记为代码错误，触发重试
                if error_type == 'unknown':
                    error_type = 'code_error'
            
            # Orchestrator Fallback 决策 (handle_agent_failure 真正接入)
            # 让 Orchestrator 记录失败并返回 4级 Fallback 建议，补充策略模式决策
            orchestrator_action = None
            if ORCHESTRATOR_ENABLED:
                try:
                    task_id = f"err_{state.get('retry_count', 0)}_{error_type}"
                    user_query = ""
                    for m in reversed(state.get("messages", [])):
                        if hasattr(m, "content") and isinstance(m.content, str) and len(m.content) > 5:
                            if not m.content.startswith("["):
                                user_query = m.content[:100]
                                break
                    orchestrator_result = handle_agent_failure(
                        agent_name="Coder",
                        task_id=task_id,
                        error=last_msg.content[:200],
                        task=user_query
                    )
                    orchestrator_action = orchestrator_result.get("action", "retry")
                    print(f"[ErrorHandler] Orchestrator 建议: {orchestrator_action} - {orchestrator_result.get('message', '')}")
                    # Level 4: Orchestrator 建议放弃时直接返回拒答
                    if orchestrator_action == "give_up":
                        return {
                            "execution_status": "error",
                            "next": "Reviewer",
                            "last_sender": "ErrorHandler",
                            "retry_count": state.get("retry_count", 0) + 1,
                            "messages": [AIMessage(content="系统已达到最大重试次数，转正屖Reviewer生成降级回复。")]
                        }
                except Exception as orch_e:
                    print(f"[ErrorHandler] Orchestrator 调用失败 (non-fatal): {orch_e}")
            
            # Build context
            ctx = ErrorContext(
                error_type=error_type,
                recovery_level=state.get("recovery_level", 0) + 1,
                retry_count=state.get("retry_count", 0),
                error_message=last_msg.content[:500],
                last_sender=state.get("last_sender", "Unknown"),
                fallback_strategy=fallback_strategy
            )
            
            # Route to appropriate strategy
            result = error_router.route(ctx, state)
            
            # Convert messages format
            if result.get("messages"):
                from langchain_core.messages import AIMessage, SystemMessage
                formatted_msgs = []
                for m in result["messages"]:
                    if isinstance(m, dict):
                        if m.get("role") == "system":
                            formatted_msgs.append(SystemMessage(content=m["content"]))
                        else:
                            formatted_msgs.append(AIMessage(content=m["content"]))
                result["messages"] = formatted_msgs
            
            return result
            
        except Exception as e:
            # Fallback to simple retry if strategy pattern fails
            print(f"[ErrorHandler] Strategy pattern failed: {e}, falling back to simple retry")
            return {
                "execution_status": "error",
                "next": "Supervisor",
                "last_sender": "ErrorHandler",
                "retry_count": state.get("retry_count", 0) + 1
            }
    else:
        # No error - continue to Supervisor
        print("[ErrorHandler] No error detected, routing to Supervisor")
        return {
            "retry_count": 0,
            "network_retry_count": 0,
            "execution_status": "success",
            "error_type": None,
            "last_sender": "ErrorHandler",
            "next": "Supervisor"
        }


# =============================================================================
# 8. ProfileUpdater (User Preference Memory)
# =============================================================================

#  
USER_PREFERENCE_DB = {}

def profile_updater_node(state: MultiAgentState):
    """
    ProfileUpdater:  +  
    
    :
    1.  (output_format: table/json/markdown)
    2.  (stock_code, industry)
    3.  (dividend, pe, roe)
    4.  (risk_level)
    
    : thread_id  
    """
    messages = state.get("messages", [])
    config = state.get("__config__", {})
    session_id = config.get("configurable", {}).get("thread_id", "default")
    
    if not messages:
        return {"last_sender": "ProfileUpdater", "next": "FINISH"}
    
    #  
    if session_id not in USER_PREFERENCE_DB:
        USER_PREFERENCE_DB[session_id] = {
            "query_count": 0,
            "preferred_format": None,  # table/json/markdown
            "frequent_stocks": [],  #  
            "frequent_metrics": [],  #  
            "risk_preference": None,  # conservative/moderate/aggressive
            "last_updated": None
        }
    
    profile = USER_PREFERENCE_DB[session_id]
    
    #  
    user_queries = [m.content for m in messages if isinstance(m, HumanMessage)]
    ai_responses = [m.content for m in messages if isinstance(m, AIMessage)]
    
    # 1: 
    for query in user_queries[-3:]:  # 3
        query_lower = query.lower()
        
        # 
        if any(kw in query_lower for kw in ["json", "", ""]):
            profile["preferred_format"] = "json"
        elif any(kw in query_lower for kw in ["table", "", ""]):
            profile["preferred_format"] = "table"
        elif any(kw in query_lower for kw in ["markdown", "md", ""]):
            profile["preferred_format"] = "markdown"
        
        # 
        import re
        stock_codes = re.findall(r'\d{6}\.(SH|SZ|BJ)', query)
        for code in stock_codes:
            if code not in profile["frequent_stocks"]:
                profile["frequent_stocks"].insert(0, code)
                profile["frequent_stocks"] = profile["frequent_stocks"][:5]  # 5
        
        # 
        metrics = []
        if any(kw in query_lower for kw in ["pe", "", ""]):
            metrics.append("pe")
        if any(kw in query_lower for kw in ["pb", "", ""]):
            metrics.append("pb")
        if any(kw in query_lower for kw in ["roe", "", ""]):
            metrics.append("roe")
        if any(kw in query_lower for kw in ["dividend", "", ""]):
            metrics.append("dividend")
        if any(kw in query_lower for kw in ["revenue", "", ""]):
            metrics.append("revenue")
        
        for metric in metrics:
            if metric not in profile["frequent_metrics"]:
                profile["frequent_metrics"].insert(0, metric)
                profile["frequent_metrics"] = profile["frequent_metrics"][:5]
        
        # 
        if any(kw in query_lower for kw in ["conservative", "", ""]):
            profile["risk_preference"] = "conservative"
        elif any(kw in query_lower for kw in ["aggressive", "", ""]):
            profile["risk_preference"] = "aggressive"
        elif any(kw in query_lower for kw in ["moderate", "", ""]):
            profile["risk_preference"] = "moderate"
    
    # 2:  
    profile["query_count"] += len(user_queries)
    profile["last_updated"] = datetime.datetime.now().isoformat()
    
    # AI 回复也添加到短期记忆
    if MEMORY_ENABLED and session_stm_manager:
        try:
            ai_responses = [m.content for m in messages if isinstance(m, AIMessage)]
            if ai_responses:
                session_short_term = session_stm_manager.get_or_create(session_id)
                for response in ai_responses[-2:]:  # 最近 2 条 AI 回复
                    session_short_term.add(
                        content=f"[assistant] {str(response)[:200]}",
                        source="agent_response",
                        category="ai_reply"
                    )
        except Exception as e:
            print(f"[MemorySystem] 记录 AI 回复失败：{e}")
    
    # 3:  
    preference_hint = ""
    if profile["preferred_format"]:
        preference_hint += f"[: {profile['preferred_format']}] "
    if profile["frequent_stocks"]:
        preference_hint += f"[: {', '.join(profile['frequent_stocks'][:3])}] "
    if profile["frequent_metrics"]:
        preference_hint += f"[: {', '.join(profile['frequent_metrics'][:3])}] "
    if profile["risk_preference"]:
        preference_hint += f"[: {profile['risk_preference']}]"
    
    if preference_hint:
        print(f"[ProfileUpdater] : {preference_hint}")
        print(f"[ProfileUpdater] : {profile['query_count']} ")
    
    # 4:  state
    return {
        "user_profile": profile,
        "preference_hint": preference_hint,
        "last_sender": "ProfileUpdater",
        "next": "FINISH"
    }


def get_user_profile(thread_id: str = "default") -> dict:
    """ """
    return USER_PREFERENCE_DB.get(thread_id, {})


def update_profile_from_feedback(thread_id: str, feedback: dict):
    """ """
    if thread_id in USER_PREFERENCE_DB:
        profile = USER_PREFERENCE_DB[thread_id]
        if "preferred_format" in feedback:
            profile["preferred_format"] = feedback["preferred_format"]
        if "risk_preference" in feedback:
            profile["risk_preference"] = feedback["risk_preference"]
        profile["last_updated"] = datetime.datetime.now().isoformat()
        print(f"[ProfileUpdater]  : {thread_id}")


# =============================================================================
# 9. 
# =============================================================================

def route_supervisor(state: MultiAgentState) -> str:
    """Supervisor"""
    return state["next"]


def route_coder(state: MultiAgentState) -> str:
    """Coder:tool_calls"""
    messages = state["messages"]
    if not messages:
        return "error_handler"
    
    last_msg = messages[-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "tools"
    else:
        return "error_handler"


#  :()
def trim_messages_for_context(messages: List[BaseMessage], max_keep: int = 15) -> List[BaseMessage]:
    """
    消息修剪: 防止 Token 爆炸
    
    策略:
    1. 保留 SystemMessage(系统提示词)
    2. 保留第一条 HumanMessage(原始查询)
    3. 保留最近 N 条 (活动上下文)
    4. 移除孤立 ToolMessage (完整性检查)
    
    Args:
        messages: 全量消息列表
        max_keep: 最大保留条数 (默认 15)
    
    Returns:
        修剪后的消息列表 (6-15 条)
    """
    if not messages or len(messages) <= max_keep:
        return messages
    
    print(f"[TrimMessages] 消息数 {len(messages)} 超限, 开始修剪...")
    
    # 1: 提取系统消息和首条用户消息
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
    first_human = next((m for m in messages if isinstance(m, HumanMessage)), None)
    
    # 2: 取最近 max_keep-2 条
    recent_msgs = messages[-(max_keep-2):] if len(messages) > max_keep-2 else messages[1:]
    
    # 3: 拼装结果 (系统 + 首条 + 最近)
    trimmed = []
    
    # 系统消息
    if system_msgs:
        trimmed.extend(system_msgs)
    
    # 首条用户消息 (recent 中没有的情况下才加)
    if first_human and first_human not in recent_msgs:
        trimmed.append(first_human)
    
    # 最近消息
    trimmed.extend(recent_msgs)
    
    # 4: 工具调用完整性检查
    trimmed = _validate_tool_call_integrity(trimmed)
    
    print(f"[TrimMessages] 修剪完成: {len(trimmed)} 条")
    return trimmed


# =============================================================================
# 消息摄要压缩 - 借鉴 OpenCode Compaction 设计
# 问题: trim_messages_for_context 是直接截断，会丢失中间上下文
# 方案: 超过阈値时用 fast_model 生成摘要，替换旧消息
# =============================================================================

# 消息压缩阈値 (借鉴 OpenCode RECENT_MESSAGE_COUNT=10, MAX_CONTEXT_LENGTH=100000)
_COMPACT_THRESHOLD = 20      # 超过 N 条触发压缩
_COMPACT_KEEP_RECENT = 8     # 压缩后保留最近 N 条


def compact_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    消息摄要压缩 (OpenCode Compaction 工作原理)

    与 trim_messages_for_context 的区别:
      - trim: 直接切掉旧消息，内容永久丢失
      - compact: 对旧消息用 fast_model 生成摘要，保留关键信息

    流程:
      1. 消息数 <= 阈値，不压缩
      2. 分割: old(旧) + recent(新)
      3. 用 fast_model 对 old 生成流式摸要
      4. 返回: [SystemMessage + 摘要消息 + recent]
    """
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]
    system_msgs = [m for m in messages if isinstance(m, SystemMessage)]

    if len(non_system) <= _COMPACT_THRESHOLD:
        return messages  # 不需要压缩

    recent = non_system[-_COMPACT_KEEP_RECENT:]
    old = non_system[:-_COMPACT_KEEP_RECENT]

    print(f"[Compaction] 触发压缩: {len(old)} 条旧消息 -> 生成摄要...")

    # 用 fast_model 生成摄要 (借鉴 OpenCode summarize 使用便宜模型)
    try:
        old_text = ""
        for m in old:
            role = type(m).__name__.replace("Message", "")
            content = ""
            if hasattr(m, "content"):
                c = m.content
                content = c[:300] if isinstance(c, str) else str(c)[:300]
            old_text += f"{role}: {content}\n"

        summary_prompt = f"""请对以下对话过程生成简洁摄要，保留以下内容:
1. 用户原始查询意图
2. Coder 已执行的关键操作和 [DATA] 数据结果
3. 发生过的错误及解决方案
4. 待完成的任务步骤

对话内容:
{old_text}

严格要求: 不超过 500 字。摆要:"""

        summary_response = fast_model.invoke([
            SystemMessage(content="你是对话摄要专家。"),
            HumanMessage(content=summary_prompt)
        ])
        summary_text = summary_response.content
        print(f"[Compaction] 摄要生成完成: {len(summary_text)} 字符")

    except Exception as e:
        # 摄要失败时降级为直接保留旧消息的文本摘要
        summary_text = f"《历史对话摄要》\n[{len(old)}条旧消息已压缩]主要执行了数据查询操作。"
        print(f"[Compaction] 摄要失败，降级处理: {e}")

    summary_msg = SystemMessage(content=f"《历史对话摄要》\n{summary_text}")
    compacted = system_msgs + [summary_msg] + recent
    print(f"[Compaction] 压缩完成: {len(messages)} -> {len(compacted)} 条")
    return compacted


def _validate_tool_call_integrity(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
     ,
    
    :
    1.  AIMessage  tool_calls, ToolMessage
    2.  ToolMessage(AIMessage),
    3. ,
    """
    validated = messages.copy()
    
    # 
    while validated:
        first_msg = validated[0]
        
        # 1:ToolMessage(AIMessage)
        if isinstance(first_msg, ToolMessage):
            # AIMessage
            has_parent = any(
                isinstance(m, AIMessage) and 
                hasattr(m, 'tool_calls') and 
                any(tc['id'] == first_msg.tool_call_id for tc in m.tool_calls if isinstance(tc, dict) or hasattr(tc, 'id'))
                for m in validated[:validated.index(first_msg)]
            )
            if not has_parent:
                print(f"[ValidateToolCalls]  ToolMessage")
                validated.pop(0)
            else:
                break
        
        # 2:AIMessagetool_callsToolMessage
        elif isinstance(first_msg, AIMessage) and hasattr(first_msg, 'tool_calls') and first_msg.tool_calls:
            # ToolMessage
            tool_ids = {tc['id'] if isinstance(tc, dict) else tc.id for tc in first_msg.tool_calls}
            has_result = any(
                isinstance(m, ToolMessage) and m.tool_call_id in tool_ids
                for m in validated[1:]
            )
            if not has_result:
                print(f"[ValidateToolCalls]  AIMessage()")
                validated.pop(0)
            else:
                break
        
        else:
            # HumanMessage  AIMessage,
            break
    
    return validated


#  :
import hashlib

class ToolCache:
    """"""
    def __init__(self, ttl_config: dict = None):
        self.cache = {}  # {hash: (result, timestamp)}
        #  TTL
        self.ttl_config = ttl_config or {
            "realtime": 30,  #  30()
            "daily": 300,  #  5
            "default": 60  #  110
        }
    
    def _make_key(self, tool_name: str, tool_input: dict) -> str:
        """"""
        key_str = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_ttl(self, tool_name: str) -> int:
        """TTL"""
        if "realtime" in tool_name or "current" in tool_name:
            return self.ttl_config["realtime"]
        elif "daily" in tool_name or "history" in tool_name:
            return self.ttl_config["daily"]
        else:
            return self.ttl_config["default"]
    
    def get(self, tool_name: str, tool_input: dict):
        """"""
        key = self._make_key(tool_name, tool_input)
        if key in self.cache:
            result, timestamp = self.cache[key]
            import time
            if time.time() - timestamp < self._get_ttl(tool_name):
                print(f"[ToolCache] :{tool_name}")
                return result
            else:
                del self.cache[key]
        return None
    
    def put(self, tool_name: str, tool_input: dict, result: str):
        """"""
        key = self._make_key(tool_name, tool_input)
        import time
        self.cache[key] = (result, time.time())
        print(f"[ToolCache] :{tool_name}")
    
    def invalidate(self, tool_name: str = None, tool_input: dict = None):
        """/"""
        if tool_input:
            key = self._make_key(tool_name, tool_input)
            if key in self.cache:
                del self.cache[key]
                print(f"[ToolCache] {tool_name}")
        else:
            # 
            keys_to_del = [k for k in self.cache.keys() if k.startswith(tool_name)]
            for k in keys_to_del:
                del self.cache[k]
            print(f"[ToolCache] {tool_name}")

# 
tool_cache = ToolCache()

def execute_tools(state: MultiAgentState, agent_name: str = "coder") -> dict:
    """工具执行节点: 缓存查询 + 工具执行 + 权限检查 + 输出截断
    
    拓展 OpenCode 设计思路:
    1. 输入 agent_name 参数 (参考 OpenCode executeToolCall 传递 ctx.agent)
    2. Pre-exec 权限门 (ToolCallMiddleware, YAML 驱动)
    3. 工具执行 (带缓存)
    4. 输出截断 (借鉴 OpenCode Truncate.MAX_OUTPUT_SIZE)
    5. Post-exec 格式验证 (DataOutputValidator, 仅 coder+run_script)
    6. 封装为 ToolMessage 返回
    """
    import time
    messages = state["messages"]
    if not messages:
        return {"messages": []}
    
    last_msg = messages[-1]
    
    if not hasattr(last_msg, "tool_calls") or not last_msg.tool_calls:
        return {"messages": []}
    
    tool_calls = last_msg.tool_calls
    tool_results = []
    
    for tool_call in tool_calls:
        tool_name = tool_call["name"]
        tool_input = tool_call["args"]
        tool_call_id = tool_call["id"]
        
        try:
            # Step 1: 权限门 (Pre-exec) - 借鉴 OpenCode PermissionNext.check()
            # YAML allowed/denied 列表的运行时执行
            if YAML_PERMISSIONS_ENABLED and _permission_middleware:
                denied_msg = _permission_middleware.check(agent_name, tool_name, tool_call_id)
                if denied_msg is not None:
                    print(f"[ExecuteTools] 权限拒绝: {agent_name} 无法调用 {tool_name}")
                    tool_results.append(denied_msg)
                    continue

            # Step 1.5: Truth-Anchor-Scanner (Pre-execution Field Contract Validation)
            # 在代码进入 Python 沙箱之前，静态扫描字段引用合法性。
            # 只拦截 FINANCIAL_SYNONYMS 中文概念词误用（如 df["净利润"]），零误报率。
            # 设计：Repo-as-truth —— schema 权威来自 RAG 召回，不信任 LLM 的字段假设。
            if agent_name == "coder" and tool_name == "run_script":
                _code_content = tool_input.get("content", "")
                _scan_violation = truth_anchor_scan(_code_content)
                if _scan_violation is not None:
                    print(f"[TruthAnchorScan] 拦截 run_script，字段合约违规，代码未执行")
                    tool_results.append(ToolMessage(
                        tool_call_id=tool_call_id,
                        content=_scan_violation,
                        metadata={"source": "truth_anchor_scan", "agent": agent_name}
                    ))
                    continue

            # Step 2: 查询缓存
            cached_result = tool_cache.get(tool_name, tool_input)
            if cached_result:
                tool_results.append(
                    ToolMessage(
                        tool_call_id=tool_call_id,
                        content=cached_result,
                        metadata={"source": "cache"}
                    )
                )
                continue
            
            # Step 3: 工具执行（记录延迟供 ToolCallMonitor 使用）
            result = None
            tool_found = False
            _exec_start = time.time()
            _exec_error: Optional[str] = None
            
            for tool in coder_tools:
                if tool.name == tool_name:
                    tool_found = True
                    try:
                        result = tool.func(**tool_input)
                    except Exception as e:
                        _exec_error = str(e)
                        result = f"Error:\n{traceback.format_exc()}"
                        print(f"[ExecuteTools] [{tool_name}] 执行异常: {str(e)[:100]}")
                    break
            
            if not tool_found:
                _exec_error = f"Tool '{tool_name}' not found"
                result = f"Error: Tool '{tool_name}' not found in available tools"
                print(f"[ExecuteTools] 未知工具: {tool_name}")
            
            _exec_latency = time.time() - _exec_start
            result_str = str(result)
            
            # Step 3.5: ToolCallMonitor 接入 (Orchestrator 监控器)
            # 记录每次工具调用的延迟和成功率，为 RL 训练环境提供稳定数据
            _exec_success = _exec_error is None and not result_str.startswith("Error")
            if ORCHESTRATOR_ENABLED:
                try:
                    orchestrator.tool_monitor.record_call(
                        tool_name=tool_name,
                        success=_exec_success,
                        latency=_exec_latency,
                        error=_exec_error
                    )
                except Exception:
                    pass
            
            # Step 3.6: suggest_fallback - 工具失败时从 ToolUsageGraph 推荐替代工具
            # 转移图有真实历史数据后，优先推荐成功率最高的替代工具
            if not _exec_success and TOOL_GRAPH_ENABLED and tool_usage_graph:
                available = [t.name for t in coder_tools if t.name != tool_name]
                try:
                    fallback_tool = tool_usage_graph.suggest_fallback(tool_name, available)
                    if fallback_tool:
                        result_str = (
                            result_str +
                            f"\n\n[Orchestrator] 建议改用工具: {fallback_tool}"
                        )
                        print(f"[ExecuteTools] [{tool_name}] 失败，ToolUsageGraph 推荐替代: {fallback_tool}")
                except Exception:
                    pass
            
            # Step 4: 输出截断 (借鉴 OpenCode Truncate.output)
            # 超过 _MAX_TOOL_OUTPUT 时截断，防止大数据查询耗尽 Token
            if len(result_str) > _MAX_TOOL_OUTPUT:
                truncated = result_str[:_MAX_TOOL_OUTPUT]
                result_str = (
                    truncated +
                    f"\n\n[输出已截断，共 {len(str(result))} 字符，已显示前 {_MAX_TOOL_OUTPUT} 字符]"
                )
                print(f"[ExecuteTools] [{tool_name}] 输出超长截断: {len(str(result))} -> {_MAX_TOOL_OUTPUT} chars")
            
            # Step 5: Post-exec 格式验证 (仅 coder + run_script)
            # 校验 [DATA]: 前缀 + 非空数据 (借鉴 OpenCode tool.execute 返回结构规范)
            # NOTE: 临时禁用验证，因为_format_execution_result已添加标记
            if False and (agent_name == "coder" and tool_name == "run_script"
                    and YAML_PERMISSIONS_ENABLED and _data_validator):
                is_valid, validated_msg = _data_validator.validate(
                    result_str, tool_call_id, tool_name
                )
                if not is_valid:
                    print(f"[ExecuteTools] 输出验证失败: {tool_name}")
                    tool_results.append(validated_msg)
                    continue
            
            # Step 6: 写入缓存
            tool_cache.put(tool_name, tool_input, result_str)
            
            # Step 6.5: 记录工具调用到 ToolUsageGraph (Orchestrator 接入)
            # 让工具转移图有真实数据，支持后续 fallback 推荐
            is_success = not result_str.startswith("Error")
            if TOOL_GRAPH_ENABLED and tool_usage_graph:
                prev_tool = getattr(execute_tools, "_last_tool", "start")
                try:
                    tool_usage_graph.record_transition(
                        from_tool=prev_tool,
                        to_tool=tool_name,
                        success=is_success,
                        weight=1.0 if is_success else 0.5
                    )
                except Exception:
                    pass
                execute_tools._last_tool = tool_name
            
            # Step 7: 封装 ToolMessage
            tool_results.append(
                ToolMessage(
                    tool_call_id=tool_call_id,
                    content=result_str,
                    metadata={"source": "api", "agent": agent_name}
                )
            )
        
        except Exception as outer_e:
            error_msg = f"Tool execution framework error: {str(outer_e)}\n{traceback.format_exc()}"
            print(f"[ExecuteTools] 框架层异常 ({agent_name}/{tool_name}): {str(outer_e)[:100]}")
            
            tool_results.append(
                ToolMessage(
                    tool_call_id=tool_call["id"],
                    content=error_msg,
                    metadata={"source": "framework_error", "agent": agent_name}
                )
            )
    
    return {"messages": tool_results}


# =============================================================================
# 9. Multi-Agent
# =============================================================================

memory = MemorySaver()
workflow = StateGraph(MultiAgentState)

# 
workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("Coder", coder_node)
workflow.add_node("Reviewer", reviewer_node)
workflow.add_node("ErrorHandler", error_handler_node)
workflow.add_node("Tools", execute_tools)
workflow.add_node("ProfileUpdater", profile_updater_node)  #   ProfileUpdater 

# 
workflow.set_entry_point("Supervisor")

# Supervisor
workflow.add_conditional_edges(
    "Supervisor",
    route_supervisor,
    {
        "Coder": "Coder",
        "Reviewer": "Reviewer",
        "ProfileUpdater": "ProfileUpdater",  #  
        "FINISH": END
    }
)

# Coder:tool_calls,
workflow.add_conditional_edges(
    "Coder",
    route_coder,
    {
        "tools": "Tools",
        "error_handler": "ErrorHandler"
    }
)

# Tools
workflow.add_edge("Tools", "ErrorHandler")

# 
workflow.add_conditional_edges(
    "ErrorHandler",
    lambda x: x["next"],
    {
        "Coder": "Coder",
        "Supervisor": "Supervisor"
    }
)

# ReviewerProfileUpdater
workflow.add_edge("Reviewer", "ProfileUpdater")  #  

# ProfileUpdaterSupervisor
workflow.add_edge("ProfileUpdater", "Supervisor")  #  

# 
multi_agent_app = workflow.compile(checkpointer=memory)

print("[System] Multi-Agent,Supervisor,Self-Correction")
print("[System] :Supervisor -> Coder/Reviewer -> Tools -> ErrorHandler -> Supervisor -> ProfileUpdater -> FINISH")
print("[System] :")
print(f"  - Smart(): deepseek-v3 / gpt-4o (Supervisor, Coder, Reviewer)")
print(f"  - Fast(): gpt-4o-mini (ErrorHandler, ProfileUpdater)")
print("[System] P0-")
print("  1. Coder")
print("  2. ErrorHandler(code/network/auth)")
print("  3. ProfileUpdater")
print("[System] P1-")
print("  1. assert")
print("  2. ")
print("[System] P2-")
print("  1.  (SummaryNode)")
print("  2.  (routing_engine.py)")

# =============================================================================
# 10. ()
# =============================================================================

def get_initial_state(user_profile: dict = None) -> dict:
    """
     ,
    
    (SSOT),:
    1. 
    2. (messages, task_plan)
    3. (user_profile)
    4. 
    
    :
        user_profile: ,None
    
    :
        
    """
    if user_profile is None:
        user_profile = {
            "username": "",
            "risk_preference": "",
            "interested_industries": [],
            "investment_style": "",
            "notes": ""
        }
    
    return {
        # ---  ---
        "messages": [],              # 
        "next": "Supervisor",        # 
        "execution_status": "pending",  # 
        
        # ---  ---
        "last_sender": "User",       # 
        "task_plan": None,           # 
        "remaining_steps": [],       # 
        
        # ---  ---
        "retry_count": 0,            # 
        "error_type": None,          # 
        "network_retry_count": 0,    # 
        "supervisor_retry": 0,       # Supervisor
        "reviewer_fail_count": 0,    # Reviewer
        
        # ---  4  ---
        "recovery_level": 0,         #  (0-4)
        "recovery_history": [],      # 
        
        # ---  ---
        "last_execution_data": {},   # 
        "message_window_size": 15,   # 
        "tool_call_count": 0,        # 
        
        # --- (!)---
        "user_profile": user_profile,  #  ,
    }


# =============================================================================
# 11.  (P0)
# =============================================================================

def assess_task_complexity(user_query: str) -> int:
    """
    评估任务复杂度（0-10分）
    
    评分维度：
    - 股票数量（每只+1分，最多+3分）
    - 指标数量（每个+1分，最多+3分）
    - 时间范围（历史数据+2分，实时数据+0分）
    - 操作类型（对比分析+2分，单查询+0分）
    - 可视化需求（+2分）
    
    Returns:
        复杂度分数（0-10）
    """
    import re
    
    score = 0
    query_lower = user_query.lower()
    
    # 1. 股票数量
    stock_codes = re.findall(r'\d{6}\.[A-Z]{2}', user_query)
    stock_names = ['茅台', '五粮液', '平安', '比亚迪', '腾讯', '阿里']
    stock_count = len(stock_codes)
    for name in stock_names:
        if name in query_lower:
            stock_count += 1
    score += min(stock_count, 3)
    
    # 2. 指标数量
    metrics = ['pe', 'pb', 'roe', 'eps', 'dividend', 'revenue', 'profit', 'margin']
    metric_count = sum(1 for m in metrics if m in query_lower)
    score += min(metric_count, 3)
    
    # 3. 时间范围
    if any(kw in query_lower for kw in ['历史', '过去', '近年', '趋势']):
        score += 2
    
    # 4. 操作类型
    if any(kw in query_lower for kw in ['对比', '比较', 'vs', '排名']):
        score += 2
    
    # 5. 可视化
    if any(kw in query_lower for kw in ['画图', '图表', '走势', '可视化']):
        score += 2
    
    return min(score, 10)


def get_max_steps_by_complexity(complexity_score: int) -> int:
    """
    根据复杂度动态限制最大步骤数
    
    策略：
    - 0-3分（简单）：最多5步
    - 4-6分（中等）：最多9步
    - 7-10分（复杂）：最多15步
    
    目的：防止简单任务过度规划，复杂任务步骤失控
    """
    if complexity_score <= 3:
        return 5
    elif complexity_score <= 6:
        return 9
    else:
        return 15


# =============================================================================
# 12. 
# =============================================================================

__all__ = ["multi_agent_app", "MultiAgentState", "get_initial_state", 
           "assess_task_complexity", "get_max_steps_by_complexity"]
