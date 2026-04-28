#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RCA Module - Root Cause Analysis (根因分析模块)

【设计理念】
受论文 "Rethinking the Evaluation of Microservice RCA with a Fault Propagation-Aware Benchmark" 启发

在多智能体系统中，错误往往不是在报错位置产生的，而是从上游传播下来的。
例如：Reviewer 报错，但根因可能是 Coder 生成的代码有 Bug。

【核心功能】
1. Fault Propagation Graph: 追踪错误在 Agent 间的传播路径
2. Root Cause Localization: 定位真正的错误源头
3. Propagation-Aware Retry: 基于传播链选择更好的重试策略

【Agent 调用链】
Supervisor → Coder → Reviewer → ErrorHandler
    ↓          ↓         ↓            ↓
  路由决策   代码生成   验证结果    错误修复

【使用方式】
```python
from rca_module import fault_analyzer

# 记录 Agent 执行结果
fault_analyzer.record_agent_execution(
    agent="Coder",
    input_data={"query": "查询茅台股价"},
    output_data={"code": "..."},
    success=True,
    error=None
)

# 当发生错误时，进行根因分析
root_cause = fault_analyzer.analyze_root_cause()
print(f"根因在 {root_cause['agent']}，错误类型: {root_cause['error_type']}")
```

【参考论文】
Fang et al., "Rethinking the Evaluation of Microservice RCA with a Fault Propagation-Aware Benchmark"
arXiv:2510.04711, FSE'26 Accepted
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import json
from enum import Enum


# =============================================================================
# 1. 错误类型定义 (参考 RCA 论文的 Fault Type Taxonomy)
# =============================================================================

class FaultType(Enum):
    """故障类型（参考 RCA 论文的分类）"""
    CODE_ERROR = "code_error"           # 代码逻辑错误
    API_ERROR = "api_error"             # API 调用失败
    NETWORK_ERROR = "network_error"     # 网络超时
    DATA_ERROR = "data_error"           # 数据为空或格式错误
    AUTH_ERROR = "auth_error"           # 认证/权限错误
    ROUTING_ERROR = "routing_error"     # 路由决策错误
    VALIDATION_ERROR = "validation_error"  # 验证失败
    UNKNOWN = "unknown"                 # 未知错误


class PropagationType(Enum):
    """传播类型"""
    DIRECT = "direct"           # 直接传播（上游错误直接导致下游失败）
    CASCADING = "cascading"     # 级联传播（上游部分错误累积导致下游崩溃）
    MASKED = "masked"           # 被掩盖的传播（上游错误被捕获但未完全处理）


# =============================================================================
# 2. 数据结构
# =============================================================================

@dataclass
class AgentExecution:
    """单个 Agent 的执行记录"""
    agent: str                          # Agent 名称
    timestamp: datetime                 # 执行时间
    input_data: Dict                    # 输入数据
    output_data: Dict                   # 输出数据
    success: bool                       # 是否成功
    error: Optional[str] = None         # 错误信息
    error_type: FaultType = FaultType.UNKNOWN  # 错误类型
    latency_ms: float = 0.0             # 执行延迟
    
    def to_dict(self) -> Dict:
        return {
            "agent": self.agent,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "error": self.error,
            "error_type": self.error_type.value,
            "latency_ms": self.latency_ms
        }


@dataclass
class FaultPropagationEdge:
    """故障传播边（表示错误从 source 传播到 target）"""
    source_agent: str                   # 源 Agent
    target_agent: str                   # 目标 Agent
    propagation_type: PropagationType   # 传播类型
    source_error: str                   # 源错误
    target_error: str                   # 目标错误
    confidence: float = 1.0             # 置信度（0-1）


@dataclass
class RootCauseResult:
    """根因分析结果"""
    root_agent: str                     # 根因 Agent
    root_error: str                     # 根因错误
    root_error_type: FaultType          # 根因错误类型
    propagation_path: List[str]         # 传播路径 ["Coder", "Reviewer", "ErrorHandler"]
    propagation_depth: int              # 传播深度
    confidence: float                   # 置信度
    recommendation: str                 # 修复建议


# =============================================================================
# 3. 核心类：Fault Propagation Analyzer
# =============================================================================

class FaultPropagationAnalyzer:
    """
    故障传播分析器 - 多智能体系统的 RCA 模块
    
    【核心思想】
    在多智能体系统中，当 Reviewer 报错时，不一定是 Reviewer 的问题。
    可能是 Coder 生成的代码有 Bug，只是在 Reviewer 验证时才暴露。
    
    这个模块追踪错误在 Agent 间的传播路径，找到真正的根因。
    
    【Agent 调用链权重】
    Supervisor(0.3) → Coder(0.5) → Reviewer(0.15) → ErrorHandler(0.05)
    
    权重表示：如果多个 Agent 都有错误，优先怀疑权重高的 Agent。
    因为 Coder 生成代码的复杂度最高，最容易出错。
    """
    
    # Agent 可疑度权重（值越高，越可能是根因）
    AGENT_SUSPICION_WEIGHTS = {
        "Supervisor": 0.3,    # 路由决策错误
        "Coder": 0.5,         # 代码生成错误（最常见）
        "Reviewer": 0.15,     # 验证逻辑错误
        "ErrorHandler": 0.05  # 修复逻辑错误
    }
    
    # 错误类型 → Agent 映射（启发式规则）
    ERROR_AGENT_MAPPING = {
        FaultType.CODE_ERROR: ["Coder"],
        FaultType.API_ERROR: ["Coder", "Supervisor"],
        FaultType.NETWORK_ERROR: ["Coder"],
        FaultType.DATA_ERROR: ["Coder", "Supervisor"],
        FaultType.AUTH_ERROR: ["Coder"],
        FaultType.ROUTING_ERROR: ["Supervisor"],
        FaultType.VALIDATION_ERROR: ["Reviewer", "Coder"],
    }
    
    def __init__(self):
        self.executions: List[AgentExecution] = []  # 当前查询的执行记录
        self.propagation_edges: List[FaultPropagationEdge] = []  # 传播边
        self.history: List[Dict] = []  # 历史分析结果
        self.current_query: str = ""
    
    def start_query(self, query: str):
        """开始新查询，重置状态"""
        self.current_query = query
        self.executions = []
        self.propagation_edges = []
        print(f"[RCA] 开始追踪: {query[:50]}...")
    
    def record_agent_execution(
        self,
        agent: str,
        input_data: Dict,
        output_data: Dict,
        success: bool,
        error: Optional[str] = None,
        error_type: Optional[FaultType] = None,
        latency_ms: float = 0.0
    ):
        """
        记录 Agent 执行结果
        
        Args:
            agent: Agent 名称 (Supervisor/Coder/Reviewer/ErrorHandler)
            input_data: 输入数据
            output_data: 输出数据
            success: 是否成功
            error: 错误信息（如果失败）
            error_type: 错误类型（如果失败）
            latency_ms: 执行延迟
        """
        # 自动分类错误类型
        if not success and error and not error_type:
            error_type = self._classify_error(error)
        
        execution = AgentExecution(
            agent=agent,
            timestamp=datetime.now(),
            input_data=input_data,
            output_data=output_data,
            success=success,
            error=error,
            error_type=error_type or FaultType.UNKNOWN,
            latency_ms=latency_ms
        )
        
        self.executions.append(execution)
        
        # 如果失败，检查是否有传播关系
        if not success:
            self._detect_propagation(execution)
        
        status = "✓" if success else "✗"
        print(f"[RCA] {status} {agent}: {error[:50] if error else 'OK'}")
    
    def _classify_error(self, error: str) -> FaultType:
        """自动分类错误类型（基于错误信息的关键词）"""
        error_lower = error.lower()
        
        if any(kw in error_lower for kw in ["syntax", "indentation", "name error", "type error"]):
            return FaultType.CODE_ERROR
        elif any(kw in error_lower for kw in ["api", "tushare", "401", "403"]):
            return FaultType.API_ERROR
        elif any(kw in error_lower for kw in ["timeout", "connection", "network", "refused"]):
            return FaultType.NETWORK_ERROR
        elif any(kw in error_lower for kw in ["empty", "null", "none", "no data", "dataframe"]):
            return FaultType.DATA_ERROR
        elif any(kw in error_lower for kw in ["auth", "token", "permission", "credential"]):
            return FaultType.AUTH_ERROR
        elif any(kw in error_lower for kw in ["route", "dispatch", "next agent"]):
            return FaultType.ROUTING_ERROR
        elif any(kw in error_lower for kw in ["valid", "check", "assert", "expect"]):
            return FaultType.VALIDATION_ERROR
        else:
            return FaultType.UNKNOWN
    
    def _detect_propagation(self, failed_execution: AgentExecution):
        """
        检测错误传播关系
        
        【核心逻辑】
        如果当前 Agent 失败，检查上一个 Agent 的输出是否有问题。
        例如：Reviewer 失败，检查 Coder 生成的代码是否有潜在 Bug。
        """
        # 找到上一个执行的 Agent
        if len(self.executions) < 2:
            return
        
        prev_execution = self.executions[-2]
        
        # 判断是否存在传播关系
        # 规则 1: 如果上游成功但下游失败，可能是「被掩盖的传播」
        if prev_execution.success and not failed_execution.success:
            # 检查上游输出是否包含潜在问题
            propagation_type = PropagationType.MASKED
            confidence = 0.7  # 中等置信度
        
        # 规则 2: 如果上游也失败，是「直接传播」
        elif not prev_execution.success and not failed_execution.success:
            propagation_type = PropagationType.DIRECT
            confidence = 0.9  # 高置信度
        
        else:
            return  # 没有传播关系
        
        edge = FaultPropagationEdge(
            source_agent=prev_execution.agent,
            target_agent=failed_execution.agent,
            propagation_type=propagation_type,
            source_error=prev_execution.error or "(上游输出可能有隐患)",
            target_error=failed_execution.error or "",
            confidence=confidence
        )
        
        self.propagation_edges.append(edge)
        print(f"[RCA] 检测到传播: {edge.source_agent} → {edge.target_agent} ({propagation_type.value})")
    
    def analyze_root_cause(self) -> RootCauseResult:
        """
        分析根因
        
        【算法】
        1. 找到所有失败的 Agent
        2. 根据传播边构建传播图
        3. 找到传播链的起点（没有入边的失败节点）
        4. 综合考虑 Agent 可疑度权重
        """
        failed_executions = [e for e in self.executions if not e.success]
        
        if not failed_executions:
            return RootCauseResult(
                root_agent="None",
                root_error="No error detected",
                root_error_type=FaultType.UNKNOWN,
                propagation_path=[],
                propagation_depth=0,
                confidence=1.0,
                recommendation="系统运行正常，无需修复"
            )
        
        # 找到传播链的起点
        # 构建入度统计
        in_degree = {e.agent: 0 for e in failed_executions}
        for edge in self.propagation_edges:
            if edge.target_agent in in_degree:
                in_degree[edge.target_agent] += 1
        
        # 入度为 0 的就是潜在的根因
        potential_roots = [agent for agent, degree in in_degree.items() if degree == 0]
        
        if not potential_roots:
            # 如果没有入度为 0 的节点，选择可疑度最高的
            potential_roots = [e.agent for e in failed_executions]
        
        # 根据可疑度权重排序
        root_agent = max(
            potential_roots,
            key=lambda a: self.AGENT_SUSPICION_WEIGHTS.get(a, 0.1)
        )
        
        # 找到对应的执行记录
        root_execution = next(
            (e for e in failed_executions if e.agent == root_agent),
            failed_executions[0]
        )
        
        # 构建传播路径
        propagation_path = self._build_propagation_path(root_agent)
        
        # 生成修复建议
        recommendation = self._generate_recommendation(root_execution)
        
        result = RootCauseResult(
            root_agent=root_agent,
            root_error=root_execution.error or "未知错误",
            root_error_type=root_execution.error_type,
            propagation_path=propagation_path,
            propagation_depth=len(propagation_path) - 1,
            confidence=0.8 if len(potential_roots) == 1 else 0.6,
            recommendation=recommendation
        )
        
        # 保存到历史
        self.history.append({
            "query": self.current_query,
            "result": {
                "root_agent": result.root_agent,
                "root_error_type": result.root_error_type.value,
                "propagation_depth": result.propagation_depth,
                "recommendation": result.recommendation
            },
            "timestamp": datetime.now().isoformat()
        })
        
        return result
    
    def _build_propagation_path(self, start_agent: str) -> List[str]:
        """构建从根因到最终报错的传播路径"""
        path = [start_agent]
        current = start_agent
        
        # BFS 构建路径
        visited = {start_agent}
        for edge in self.propagation_edges:
            if edge.source_agent == current and edge.target_agent not in visited:
                path.append(edge.target_agent)
                visited.add(edge.target_agent)
                current = edge.target_agent
        
        return path
    
    def _generate_recommendation(self, root_execution: AgentExecution) -> str:
        """生成修复建议"""
        recommendations = {
            FaultType.CODE_ERROR: f"检查 {root_execution.agent} 生成的代码逻辑，特别是变量类型和 API 参数",
            FaultType.API_ERROR: "验证 Tushare API 的调用参数和频率限制",
            FaultType.NETWORK_ERROR: "添加重试逻辑和超时处理，考虑使用指数退避",
            FaultType.DATA_ERROR: "在代码中添加空值检查，考虑使用备选数据源",
            FaultType.AUTH_ERROR: "检查 API Token 是否有效，确认账户权限",
            FaultType.ROUTING_ERROR: "检查 Supervisor 的路由逻辑，可能需要调整任务分解策略",
            FaultType.VALIDATION_ERROR: "检查验证规则是否过于严格，或者调整输出格式",
        }
        
        return recommendations.get(
            root_execution.error_type,
            f"检查 {root_execution.agent} 的实现逻辑"
        )
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        failed = [e for e in self.executions if not e.success]
        
        error_type_counts = {}
        for e in failed:
            error_type = e.error_type.value
            error_type_counts[error_type] = error_type_counts.get(error_type, 0) + 1
        
        return {
            "total_executions": len(self.executions),
            "failed_executions": len(failed),
            "propagation_edges": len(self.propagation_edges),
            "error_type_distribution": error_type_counts,
            "history_count": len(self.history)
        }
    
    def get_propagation_summary(self) -> str:
        """获取传播链摘要（用于注入 Prompt）"""
        if not self.propagation_edges:
            return ""
        
        summary = "【RCA 分析】错误传播路径:\n"
        for edge in self.propagation_edges:
            summary += f"  {edge.source_agent} → {edge.target_agent}: {edge.propagation_type.value}\n"
        
        root_cause = self.analyze_root_cause()
        summary += f"\n【根因定位】{root_cause.root_agent} ({root_cause.root_error_type.value})\n"
        summary += f"【修复建议】{root_cause.recommendation}"
        
        return summary


# =============================================================================
# 4. 全局实例
# =============================================================================

fault_analyzer = FaultPropagationAnalyzer()


# =============================================================================
# 5. 便捷函数（用于集成到 BacktrackingRouter）
# =============================================================================

def get_rca_enhanced_retry_strategy(current_strategy: str, error: str) -> Tuple[str, str]:
    """
    基于 RCA 分析选择更好的重试策略
    
    Args:
        current_strategy: 当前策略
        error: 错误信息
    
    Returns:
        (建议策略, 策略调整理由)
    """
    root_cause = fault_analyzer.analyze_root_cause()
    
    # 基于根因类型调整策略
    strategy_mapping = {
        FaultType.CODE_ERROR: ("step_by_step", "代码错误，建议分步执行以便定位问题"),
        FaultType.API_ERROR: ("alternative_fields", "API 错误，尝试使用替代字段"),
        FaultType.NETWORK_ERROR: ("direct_with_retry", "网络错误，增加重试逻辑"),
        FaultType.DATA_ERROR: ("alternative_fields", "数据为空，尝试备选查询"),
        FaultType.ROUTING_ERROR: ("step_by_step", "路由错误，重新分解任务"),
    }
    
    return strategy_mapping.get(
        root_cause.root_error_type,
        (current_strategy, "维持当前策略")
    )


def should_escalate_to_human(propagation_depth: int = 2) -> bool:
    """
    判断是否应该升级到人工处理
    
    【规则】
    如果错误传播深度超过阈值，说明问题复杂，需要人工介入。
    """
    root_cause = fault_analyzer.analyze_root_cause()
    return root_cause.propagation_depth >= propagation_depth


# =============================================================================
# 6. 测试代码
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("RCA Module - Root Cause Analysis 测试")
    print("=" * 60)
    
    # 模拟一个查询的执行过程
    fault_analyzer.start_query("查询贵州茅台的股息率")
    
    # Supervisor 成功
    fault_analyzer.record_agent_execution(
        agent="Supervisor",
        input_data={"query": "查询贵州茅台的股息率"},
        output_data={"next": "Coder", "plan": ["获取股票代码", "查询股息率"]},
        success=True,
        latency_ms=150
    )
    
    # Coder 成功（但代码有潜在 Bug）
    fault_analyzer.record_agent_execution(
        agent="Coder",
        input_data={"task": "获取股票代码"},
        output_data={"code": "df = pro.daily_basic(ts_code='600519.SH')"},
        success=True,
        latency_ms=2000
    )
    
    # Reviewer 失败（发现 Coder 的代码有问题）
    fault_analyzer.record_agent_execution(
        agent="Reviewer",
        input_data={"code": "df = pro.daily_basic(ts_code='600519.SH')"},
        output_data={},
        success=False,
        error="DataFrame is empty: 股息率字段 dv_ttm 为 NaN",
        latency_ms=500
    )
    
    # ErrorHandler 尝试修复
    fault_analyzer.record_agent_execution(
        agent="ErrorHandler",
        input_data={"error": "DataFrame is empty"},
        output_data={},
        success=False,
        error="无法修复: 需要更换 API 或使用备选字段",
        latency_ms=300
    )
    
    # 分析根因
    print("\n" + "=" * 60)
    result = fault_analyzer.analyze_root_cause()
    
    print(f"\n【根因分析结果】")
    print(f"  根因 Agent: {result.root_agent}")
    print(f"  根因错误类型: {result.root_error_type.value}")
    print(f"  传播路径: {' → '.join(result.propagation_path)}")
    print(f"  传播深度: {result.propagation_depth}")
    print(f"  置信度: {result.confidence:.0%}")
    print(f"  修复建议: {result.recommendation}")
    
    print("\n" + "=" * 60)
    print("【统计信息】")
    stats = fault_analyzer.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 60)
    print("【传播链摘要（可注入 Prompt）】")
    print(fault_analyzer.get_propagation_summary())
