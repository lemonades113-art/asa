#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Memory System - 分层记忆系统（参考 Letta/MemGPT 架构）

【面试对标】
解决面试高频问题：
- "如何设计 Agent 的记忆系统？"
- "长期记忆和短期记忆如何划分？"
- "记忆衰退机制如何实现？"

【核心架构】
┌─────────────────────────────────────────────────────────────┐
│                    Memory System                            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │   短期记忆       │  │   长期记忆       │                  │
│  │ (Working Memory)│  │ (Long-Term)     │                  │
│  │                 │  │                 │                  │
│  │ - 最近 5 轮对话  │  │ - 成功策略       │                  │
│  │ - 当前任务上下文 │  │ - 知识片段       │                  │
│  │ - TTL: 30min    │  │ - 用户偏好       │                  │
│  └─────────────────┘  └─────────────────┘                  │
│           ↓                    ↓                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              记忆衰退 (Memory Decay)                  │   │
│  │  - 基于时间: 30天未访问 → 权重 -50%                   │   │
│  │  - 基于重要性: success_count > 3 → 永久保留           │   │
│  │  - 基于相关性: embedding 相似度 < 0.5 → 不召回        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

【设计原则】
1. 渐进式增强：不依赖外部向量数据库，内置简单实现
2. 可插拔：支持后续替换为 Chroma/Pinecone
3. 零破坏：不修改 multi_agent.py 现有逻辑
"""

import json
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from collections import OrderedDict
import math

# 尝试导入向量数据库（可选）
try:
    import chromadb
    CHROMA_AVAILABLE = True
except Exception:
    CHROMA_AVAILABLE = False
    print("[MemorySystem] ChromaDB 不可用，使用内置简单向量存储")


# =============================================================================
# 1. 记忆数据结构
# =============================================================================

@dataclass
class MemoryItem:
    """单条记忆"""
    memory_id: str
    content: str  # 记忆内容
    memory_type: str  # "short_term" | "long_term" | "episodic"
    
    # 元数据
    source: str = ""  # 来源 (user_query, agent_response, successful_strategy, etc.)
    category: str = ""  # 分类 (stock_query, financial_analysis, error_fix, etc.)
    
    # 时间信息
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    
    # 权重和衰退
    importance: float = 1.0  # 初始重要性
    decay_rate: float = 0.1  # 衰退速率
    
    # 关联信息
    embedding: Optional[List[float]] = None  # 向量表示（可选）
    related_ids: List[str] = field(default_factory=list)  # 关联记忆
    
    # 成功/失败统计（用于策略记忆）
    success_count: int = 0
    failure_count: int = 0
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "MemoryItem":
        return cls(**data)
    
    def get_current_weight(self) -> float:
        """
        计算当前权重（考虑衰退）
        
        公式: weight = importance * decay_factor * access_bonus
        - decay_factor = exp(-decay_rate * days_since_last_access)
        - access_bonus = log(1 + access_count)
        """
        days_since_access = (time.time() - self.last_accessed) / (24 * 3600)
        decay_factor = math.exp(-self.decay_rate * days_since_access)
        access_bonus = math.log(1 + self.access_count)
        
        # 成功的策略获得额外权重
        success_bonus = 1.0 + (self.success_count * 0.2)
        
        return self.importance * decay_factor * (1 + access_bonus * 0.1) * success_bonus
    
    def touch(self):
        """访问记忆，更新时间戳和访问计数"""
        self.last_accessed = time.time()
        self.access_count += 1


# =============================================================================
# 2. 短期记忆（Working Memory）
# =============================================================================

class ShortTermMemory:
    """
    短期记忆 - 存储最近的对话上下文
    
    特点：
    - 容量限制：最多 N 条消息
    - TTL 限制：超过 30 分钟自动过期
    - FIFO 淘汰：容量满时移除最旧的
    """
    
    def __init__(self, max_size: int = 10, ttl_minutes: int = 30):
        self.max_size = max_size
        self.ttl_seconds = ttl_minutes * 60
        self._memory: OrderedDict[str, MemoryItem] = OrderedDict()
    
    def add(self, content: str, source: str = "conversation", category: str = "") -> str:
        """添加短期记忆"""
        # 生成 ID
        memory_id = f"stm_{hashlib.md5(f'{content}{time.time()}'.encode()).hexdigest()[:8]}"
        
        item = MemoryItem(
            memory_id=memory_id,
            content=content,
            memory_type="short_term",
            source=source,
            category=category,
            importance=0.5  # 短期记忆默认重要性较低
        )
        
        # 容量控制
        while len(self._memory) >= self.max_size:
            self._memory.popitem(last=False)  # 移除最旧的
        
        self._memory[memory_id] = item
        return memory_id
    
    def get_recent(self, n: int = 5) -> List[MemoryItem]:
        """获取最近 N 条记忆"""
        self._cleanup_expired()
        items = list(self._memory.values())
        return items[-n:] if len(items) > n else items
    
    def get_context_string(self, n: int = 5) -> str:
        """获取上下文字符串（用于注入 Prompt）"""
        recent = self.get_recent(n)
        if not recent:
            return ""
        
        context_parts = ["【近期对话记忆】"]
        for item in recent:
            context_parts.append(f"- [{item.source}] {item.content[:100]}...")
        
        return "\n".join(context_parts)
    
    def _cleanup_expired(self):
        """清理过期记忆"""
        now = time.time()
        expired = [
            mid for mid, item in self._memory.items()
            if now - item.created_at > self.ttl_seconds
        ]
        for mid in expired:
            del self._memory[mid]
    
    def clear(self):
        """清空短期记忆"""
        self._memory.clear()
    
    def __len__(self):
        return len(self._memory)


# =============================================================================
# 2.5 会话隔离的短期记忆管理器（参考 OpenCode Session 设计）
# =============================================================================

class SessionAwareShortTermMemory:
    """
    会话感知的短期记忆管理器
    
    解决多用户并发时的记忆隔离问题：
    - 每个 session_id 有独立的 ShortTermMemory
    - 共享全局长期记忆
    - 自动清理不活跃会话
    
    使用方式：
    ```python
    stm_manager = SessionAwareShortTermMemory()
    
    # 获取或创建会话记忆
    session_stm = stm_manager.get_or_create("session_123")
    session_stm.add("用户查询", source="user")
    
    # 获取上下文（仅本会话）
    context = session_stm.get_context_string(n=5)
    ```
    """
    
    def __init__(self, max_size: int = 10, ttl_minutes: int = 30):
        self.max_size = max_size
        self.ttl_minutes = ttl_minutes
        self._sessions: Dict[str, ShortTermMemory] = {}
        self._last_accessed: Dict[str, float] = {}  # session_id -> timestamp
    
    def get_or_create(self, session_id: str) -> ShortTermMemory:
        """获取或创建会话的短期记忆"""
        self._last_accessed[session_id] = time.time()
        
        if session_id not in self._sessions:
            self._sessions[session_id] = ShortTermMemory(
                max_size=self.max_size,
                ttl_minutes=self.ttl_minutes
            )
            print(f"[SessionSTM] 创建新会话: {session_id[:8]}...")
        
        return self._sessions[session_id]
    
    def get(self, session_id: str) -> Optional[ShortTermMemory]:
        """获取会话记忆（不创建）"""
        return self._sessions.get(session_id)
    
    def cleanup_inactive(self, ttl_hours: int = 24):
        """清理不活跃会话"""
        now = time.time()
        ttl_seconds = ttl_hours * 3600
        
        to_remove = [
            sid for sid, last in self._last_accessed.items()
            if now - last > ttl_seconds
        ]
        
        for sid in to_remove:
            del self._sessions[sid]
            del self._last_accessed[sid]
        
        if to_remove:
            print(f"[SessionSTM] 清理 {len(to_remove)} 个不活跃会话")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "active_sessions": len(self._sessions),
            "max_size_per_session": self.max_size,
            "ttl_minutes": self.ttl_minutes
        }


# =============================================================================
# 3. 因果记忆图（Causal Memory Graph）
# =============================================================================

class CausalMemoryGraph:
    """
    因果记忆图 - 记录任务之间的因果关系
    
    核心思想（基于 Hindsight 论文）：
    如果前一个节点失败了，就会影响后一个节点也失败。
    通过预测下一节点的失败风险，实现主动预防而非被动修复。
    
    数据结构：
    - nodes: 任务/调用节点，记录成功/失败统计
    - causal_edges: 有向边，表示因果关系 from_id → to_id
    
    应用场景：
    - Tool A 调用失败 → 预测 Tool B 失败风险提升
    - Query 解析失败 → 预测后续工具调用都会失败
    - Memory 检索失败 → 预测生成质量会下降
    """
    
    def __init__(self):
        self.nodes: Dict[str, Dict[str, Any]] = {}  # node_id -> node_info
        self.causal_edges: Dict[str, List[str]] = {}  # from_id -> [to_id, ...]
        self.node_counter = 0
        self.edge_counter = 0
    
    def add_node(
        self,
        content: str,
        node_type: str = "task",
        success: bool = True
    ) -> str:
        """
        添加节点到因果图
        
        Args:
            content: 节点内容（查询、工具调用、结果等）
            node_type: 节点类型 (task, tool_call, memory_retrieve, review, etc.)
            success: 该节点是否执行成功
        
        Returns:
            node_id: 新节点的 ID
        """
        node_id = f"cnode_{self.node_counter}"
        self.node_counter += 1
        
        self.nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            "content": content[:200],  # 截断长文本
            "created_at": time.time(),
            "success_count": 1 if success else 0,
            "failure_count": 0 if success else 1,
            "caused_by": [],  # 哪些节点导致了这个节点的失败
            "caused_next": []  # 这个节点的失败会导致哪些节点失败
        }
        
        if node_id not in self.causal_edges:
            self.causal_edges[node_id] = []
        
        return node_id
    
    def add_causal_edge(
        self,
        from_id: str,
        to_id: str,
        strength: float = 1.0
    ) -> bool:
        """
        添加因果边：from_id 的失败会影响 to_id 的失败
        
        Args:
            from_id: 源节点 ID
            to_id: 目标节点 ID
            strength: 因果强度 (0.0-1.0)，表示影响程度
        
        Returns:
            成功添加返回 True，否则 False
        """
        if from_id not in self.nodes or to_id not in self.nodes:
            return False
        
        if to_id not in self.causal_edges.get(from_id, []):
            if from_id not in self.causal_edges:
                self.causal_edges[from_id] = []
            
            self.causal_edges[from_id].append(to_id)
            self.nodes[to_id]["caused_by"].append(from_id)
            self.nodes[from_id]["caused_next"].append(to_id)
            self.edge_counter += 1
            return True
        
        return False
    
    def record_failure_chain(
        self,
        node_id: str
    ) -> List[str]:
        """
        记录失败链：从失败节点反向追踪到根因
        
        Returns:
            失败传播链的节点 ID 列表
        """
        if node_id not in self.nodes:
            return []
        
        chain = [node_id]
        current_node = self.nodes[node_id]
        
        # 反向追踪因果链
        visited = set([node_id])
        queue = current_node["caused_by"][:]
        
        while queue:
            from_id = queue.pop(0)
            if from_id in visited:
                continue
            
            visited.add(from_id)
            chain.append(from_id)
            
            # 继续追踪上游节点
            if from_id in self.nodes:
                queue.extend(self.nodes[from_id]["caused_by"])
        
        return chain
    
    def predict_failure_risk(
        self,
        node_id: str
    ) -> Dict[str, Any]:
        """
        预测节点的失败风险
        
        基于：
        1. 该节点的历史失败率
        2. 导致该节点的上游节点的失败率
        
        Returns:
            {
                "node_id": str,
                "failure_rate": float (0.0-1.0),
                "risk_level": str ("low", "medium", "high"),
                "contributing_factors": List[str]
            }
        """
        if node_id not in self.nodes:
            return {"error": "node not found"}
        
        node = self.nodes[node_id]
        total_count = node["success_count"] + node["failure_count"]
        
        if total_count == 0:
            direct_failure_rate = 0.0
        else:
            direct_failure_rate = node["failure_count"] / total_count
        
        # 计算上游节点的失败率影响
        upstream_failure_rates = []
        for from_id in node["caused_by"]:
            if from_id in self.nodes:
                from_node = self.nodes[from_id]
                from_total = from_node["success_count"] + from_node["failure_count"]
                if from_total > 0:
                    upstream_failure_rates.append(
                        from_node["failure_count"] / from_total
                    )
        
        # 综合计算失败风险
        if upstream_failure_rates:
            avg_upstream_rate = sum(upstream_failure_rates) / len(upstream_failure_rates)
            # 30% 直接失败率 + 70% 上游影响
            combined_failure_rate = 0.3 * direct_failure_rate + 0.7 * avg_upstream_rate
        else:
            combined_failure_rate = direct_failure_rate
        
        # 判断风险等级
        if combined_failure_rate < 0.2:
            risk_level = "low"
        elif combined_failure_rate < 0.5:
            risk_level = "medium"
        else:
            risk_level = "high"
        
        contributing_factors = []
        if direct_failure_rate > 0.3:
            contributing_factors.append(
                f"Direct failure history: {direct_failure_rate:.1%}"
            )
        
        for idx, from_id in enumerate(node["caused_by"]):
            if idx < len(upstream_failure_rates):
                rate = upstream_failure_rates[idx]
                if rate > 0.3:
                    from_node = self.nodes[from_id]
                    contributing_factors.append(
                        f"Upstream {from_node['type']} failure: {rate:.1%}"
                    )
        
        return {
            "node_id": node_id,
            "failure_rate": combined_failure_rate,
            "risk_level": risk_level,
            "contributing_factors": contributing_factors
        }
    
    def get_preventive_actions(
        self,
        node_id: str
    ) -> List[Dict[str, str]]:
        """
        获取主动预防处方（而非被动修复）
        
        基于失败风险预测，给出预防性建议
        
        Returns:
            [
                {"action": str, "rationale": str},
                ...
            ]
        """
        risk_info = self.predict_failure_risk(node_id)
        
        if "error" in risk_info:
            return []
        
        actions = []
        node = self.nodes[node_id]
        
        # 根据风险等级提供建议
        if risk_info["risk_level"] == "high":
            actions.append({
                "action": "Increase validation before execution",
                "rationale": f"High failure risk ({risk_info['failure_rate']:.1%}) detected"
            })
            
            # 如果是上游导致的失败，建议修复上游
            if len(node["caused_by"]) > 0:
                actions.append({
                    "action": "Check and fix upstream dependencies first",
                    "rationale": f"Failures in upstream nodes may cascade: {node['caused_by']}"
                })
        
        elif risk_info["risk_level"] == "medium":
            actions.append({
                "action": "Add defensive checks and error handling",
                "rationale": f"Medium failure risk ({risk_info['failure_rate']:.1%}) - prepare for fallback"
            })
        
        # 通用建议
        actions.append({
            "action": "Log execution context for debugging",
            "rationale": "Enable root cause analysis if failure occurs"
        })
        
        return actions
    
    def get_graph_stats(self) -> Dict[str, Any]:
        """
        获取因果图的统计信息
        """
        total_successes = sum(
            node["success_count"] for node in self.nodes.values()
        )
        total_failures = sum(
            node["failure_count"] for node in self.nodes.values()
        )
        total_count = total_successes + total_failures
        
        success_rate = (
            total_successes / total_count if total_count > 0 else 0.0
        )
        
        node_types = {}
        for node in self.nodes.values():
            node_type = node["type"]
            if node_type not in node_types:
                node_types[node_type] = {"count": 0, "failures": 0}
            node_types[node_type]["count"] += 1
            node_types[node_type]["failures"] += node["failure_count"]
        
        return {
            "total_nodes": len(self.nodes),
            "total_edges": self.edge_counter,
            "total_executions": total_count,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "overall_success_rate": success_rate,
            "node_types": node_types,
            "high_risk_nodes": [
                node_id for node_id in self.nodes
                if self.predict_failure_risk(node_id)["risk_level"] == "high"
            ]
        }
    
    def export_to_graphviz(self, output_path: str = "./causal_graph.dot"):
        """
        导出为 Graphviz DOT 格式（因果图可视化）
        
        参考文档优化建议：
        - 节点颜色表示失败率（绿色=低，橙色=中，红色=高）
        - 支持命令行转换: dot -Tpng causal_graph.dot -o causal_graph.png
        
        Args:
            output_path: 输出文件路径
        """
        lines = ["digraph CausalGraph {"]
        lines.append('  rankdir=LR;')
        lines.append('  node [shape=box, style="rounded,filled", fontname="Arial"];')
        lines.append('  edge [fontname="Arial", fontsize=10];')
        
        # 添加节点
        for node_id, node in self.nodes.items():
            total = node["success_count"] + node["failure_count"]
            
            # 根据失败率确定颜色
            if total == 0:
                color = "gray90"
                fontcolor = "black"
            else:
                failure_rate = node["failure_count"] / total
                if failure_rate > 0.5:
                    color = "#ffcccc"  # 浅红
                    fontcolor = "#cc0000"
                elif failure_rate > 0.2:
                    color = "#ffe6cc"  # 浅橙
                    fontcolor = "#cc6600"
                else:
                    color = "#ccffcc"  # 浅绿
                    fontcolor = "#006600"
            
            # 截断标签
            label = f"{node['type']}\\n{node['content'][:30]}..."
            lines.append(f'  "{node_id}" [label="{label}", fillcolor="{color}", fontcolor="{fontcolor}"];')
        
        # 添加边
        for from_id, to_ids in self.causal_edges.items():
            for to_id in to_ids:
                lines.append(f'  "{from_id}" -> "{to_id}";')
        
        lines.append("}")
        
        # 写入文件
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\\n".join(lines))
        
        print(f"[CausalGraph] 已导出到 {output_path}")
        print(f"[CausalGraph] 转换命令: dot -Tpng {output_path} -o {output_path.replace('.dot', '.png')}")
    
    def export_to_json(self, output_path: str = "./causal_graph.json"):
        """
        导出为 JSON 格式（供前端可视化）
        
        Args:
            output_path: 输出文件路径
        """
        data = {
            "nodes": [
                {
                    "id": node_id,
                    "type": node["type"],
                    "content": node["content"],
                    "success_count": node["success_count"],
                    "failure_count": node["failure_count"],
                    "failure_rate": node["failure_count"] / max(1, node["success_count"] + node["failure_count"])
                }
                for node_id, node in self.nodes.items()
            ],
            "edges": [
                {"from": from_id, "to": to_id}
                for from_id, to_ids in self.causal_edges.items()
                for to_id in to_ids
            ],
            "stats": self.get_graph_stats()
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"[CausalGraph] 已导出到 {output_path}")
    
    def get_failure_hotspots(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """
        获取失败热点（最容易失败的节点）
        
        用于监控和告警
        
        Returns:
            失败热点列表，按失败率排序
        """
        hotspots = []
        
        for node_id, node in self.nodes.items():
            total = node["success_count"] + node["failure_count"]
            if total < 3:  # 执行次数太少，不统计
                continue
            
            failure_rate = node["failure_count"] / total
            if failure_rate > 0.3:  # 失败率 > 30%
                hotspots.append({
                    "node_id": node_id,
                    "node_type": node["type"],
                    "content_preview": node["content"][:50],
                    "failure_rate": failure_rate,
                    "total_executions": total,
                    "downstream_impact": len(node.get("caused_next", []))
                })
        
        # 按失败率排序
        hotspots.sort(key=lambda x: x["failure_rate"], reverse=True)
        return hotspots[:top_n]
    
    def generate_monitoring_report(self) -> str:
        """
        生成监控报告（用于告警和调试）
        
        Returns:
            格式化的监控报告文本
        """
        stats = self.get_graph_stats()
        hotspots = self.get_failure_hotspots(top_n=5)
        
        report_lines = [
            "=" * 50,
            "【因果图监控报告】",
            "=" * 50,
            f"总节点数: {stats['total_nodes']}",
            f"总边数: {stats['total_edges']}",
            f"总执行次数: {stats['total_executions']}",
            f"总体成功率: {stats['overall_success_rate']:.1%}",
            "",
            "【节点类型分布】"
        ]
        
        for node_type, info in stats.get("node_types", {}).items():
            fail_rate = info['failures'] / max(1, info['count'])
            report_lines.append(f"  {node_type}: {info['count']} 个 (失败率: {fail_rate:.1%})")
        
        report_lines.extend([
            "",
            "【失败热点 TOP 5】"
        ])
        
        if hotspots:
            for idx, hotspot in enumerate(hotspots, 1):
                report_lines.append(
                    f"{idx}. [{hotspot['node_type']}] "
                    f"失败率 {hotspot['failure_rate']:.1%} "
                    f"({hotspot['total_executions']} 次执行)"
                )
                report_lines.append(f"   内容: {hotspot['content_preview']}...")
        else:
            report_lines.append("  无失败热点（系统运行良好）")
        
        report_lines.append("=" * 50)
        
        return "\\n".join(report_lines)


# =============================================================================
# 4. 长期记忆（Long-Term Memory）
# =============================================================================

class LongTermMemory:
    """
    长期记忆 - 存储成功策略、知识片段、用户偏好
    
    特点：
    - 持久化存储（JSON 文件）
    - 向量检索（可选 Chroma）
    - 记忆衰退（基于时间和访问频率）
    - 重要性过滤（低于阈值不召回）
    """
    
    def __init__(self, storage_path: str = "./memory_store"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(exist_ok=True)
        self._memory: Dict[str, MemoryItem] = {}
        
        # 加载已有记忆
        self._load()
        
        # 初始化向量存储（可选）
        self._vector_store = None
        if CHROMA_AVAILABLE:
            self._init_vector_store()
    
    def _init_vector_store(self):
        """初始化 Chroma 向量存储（可选）"""
        try:
            client = chromadb.PersistentClient(path=str(self.storage_path / "chroma"))
            self._vector_store = client.get_or_create_collection(
                name="asa_memory",
                metadata={"hnsw:space": "cosine"}
            )
            print("[LongTermMemory] ChromaDB 向量存储已初始化")
        except Exception as e:
            print(f"[LongTermMemory] ChromaDB 初始化失败: {e}")
            self._vector_store = None
    
    def add(
        self,
        content: str,
        source: str,
        category: str = "",
        importance: float = 1.0,
        embedding: Optional[List[float]] = None,
        causal_graph: Optional['CausalMemoryGraph'] = None
    ) -> str:
        """添加长期记忆"""
        memory_id = f"ltm_{hashlib.md5(f'{content}'.encode()).hexdigest()[:12]}"
        
        # 检查是否已存在（去重）
        if memory_id in self._memory:
            # 已存在，更新访问
            self._memory[memory_id].touch()
            return memory_id
        
        item = MemoryItem(
            memory_id=memory_id,
            content=content,
            memory_type="long_term",
            source=source,
            category=category,
            importance=importance,
            embedding=embedding
        )
        
        self._memory[memory_id] = item
        
        # 添加到向量存储（如果可用）
        if self._vector_store and embedding:
            try:
                self._vector_store.add(
                    ids=[memory_id],
                    embeddings=[embedding],
                    documents=[content],
                    metadatas=[{"source": source, "category": category}]
                )
            except Exception as e:
                print(f"[LongTermMemory] 向量存储添加失败: {e}")
        
        # 记录到因果图（用于主动预防）
        if causal_graph:
            try:
                causal_graph.add_node(
                    content=f"Memory add: {source}_{category}",
                    node_type="memory_retrieve",
                    success=True
                )
            except Exception as e:
                pass  # 因果图记录失败不影响主流程
        
        return memory_id
    
    def add_successful_strategy(
        self,
        query_pattern: str,
        strategy: str,
        execution_steps: List[str],
        category: str = ""
    ) -> str:
        """
        添加成功的策略（专用方法）
        
        这是面试高频问题："如何让 Agent 记住成功的解题思路？"
        """
        content = json.dumps({
            "query_pattern": query_pattern,
            "strategy": strategy,
            "execution_steps": execution_steps,
            "success_count": 1
        }, ensure_ascii=False)
        
        return self.add(
            content=content,
            source="successful_strategy",
            category=category,
            importance=1.5  # 成功策略重要性更高
        )
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        min_weight: float = 0.3,
        category: Optional[str] = None,
        causal_graph: Optional['CausalMemoryGraph'] = None
    ) -> List[Tuple[MemoryItem, float]]:
        """
        搜索相关记忆
            
        Args:
            query: 查询文本
            top_k: 返回数量
            min_weight: 最小权重阈值（记忆衻退后低于此值不返回）
            category: 可选的类别过滤
            causal_graph: 因果图（用于主动预防）
            
        Returns:
            [(MemoryItem, score), ...]
        """
        results = []
            
        # 方式 1：向量检索（如果可用）
        if self._vector_store:
            try:
                vector_results = self._vector_store.query(
                    query_texts=[query],
                    n_results=top_k * 2,  # 多查一些，后面再过滤
                    where={"category": category} if category else None
                )
                    
                for mid, score in zip(vector_results["ids"][0], vector_results["distances"][0]):
                    if mid in self._memory:
                        item = self._memory[mid]
                        weight = item.get_current_weight()
                        if weight >= min_weight:
                            item.touch()  # 更新访问
                            results.append((item, 1 - score))  # Chroma 返回距离，转为相似度
            except Exception as e:
                print(f"[LongTermMemory] 向量检索失败: {e}")
            
        # 方式 2：关键词匹配（fallback）
        if not results:
            query_lower = query.lower()
            for item in self._memory.values():
                # 类别过滤
                if category and item.category != category:
                    continue
                    
                # 简单关键词匹配
                content_lower = item.content.lower()
                if any(word in content_lower for word in query_lower.split()):
                    weight = item.get_current_weight()
                    if weight >= min_weight:
                        item.touch()
                        # 计算简单匹配分数
                        match_count = sum(1 for word in query_lower.split() if word in content_lower)
                        score = match_count / len(query_lower.split())
                        results.append((item, score * weight))
            
        # 排序并返回 top_k
        results.sort(key=lambda x: x[1], reverse=True)
        top_results = results[:top_k]
            
        # 记录到因果图（用于主动预防）
        if causal_graph and top_results:
            try:
                search_node_id = causal_graph.add_node(
                    content=f"Memory search: {query[:50]}",
                    node_type="memory_retrieve",
                    success=len(top_results) > 0
                )
                # 记录检索结果数中可告诉主动预防
                if len(top_results) == 0:
                    causal_graph.nodes[search_node_id]["failure_count"] = 1
                    causal_graph.nodes[search_node_id]["success_count"] = 0
            except Exception as e:
                pass  # 因果图记录失败不影响主流程
            
        return top_results
    
    def get_strategy_hint(self, query: str) -> Optional[str]:
        """
        获取策略提示（用于注入 Supervisor Prompt）
        
        如果找到相似的成功策略，返回提示；否则返回 None
        """
        results = self.search(query, top_k=3, category="")
        
        # 过滤出成功策略
        strategies = [
            (item, score) for item, score in results
            if item.source == "successful_strategy" and score > 0.5
        ]
        
        if not strategies:
            return None
        
        best_item, score = strategies[0]
        try:
            strategy_data = json.loads(best_item.content)
            hint = f"""
【历史成功策略参考】（相似度: {score:.2f}）
- 问题模式: {strategy_data.get('query_pattern', '')}
- 成功策略: {strategy_data.get('strategy', '')}
- 执行步骤: {' → '.join(strategy_data.get('execution_steps', []))}
- 历史成功次数: {strategy_data.get('success_count', 0)}

建议参考此策略执行当前任务。
"""
            return hint
        except:
            return None
    
    def search_hybrid(
        self,
        query: str,
        top_k: int = 5,
        min_weight: float = 0.3,
        category: Optional[str] = None,
        alpha: float = 0.7  # 向量检索权重
    ) -> List[Tuple[MemoryItem, float]]:
        """
        混合检索（向量 + BM25 + 缓存）
        
        参考 OpenCode 和文档优化建议：
        - BM25 索引加速关键词匹配
        - 混合分数（向量 + BM25）
        - 查询缓存避免重复计算
        
        Args:
            query: 查询文本
            top_k: 返回数量
            min_weight: 最小权重阈值
            category: 类别过滤
            alpha: 向量检索权重（1-alpha 为 BM25 权重）
        
        Returns:
            [(MemoryItem, final_score), ...]
        """
        import hashlib
        from functools import lru_cache
        
        # 1. 检查简单缓存（基于查询哈希）
        cache_key = hashlib.md5(f"{query}_{top_k}_{category}_{alpha}".encode()).hexdigest()
        if hasattr(self, '_query_cache') and cache_key in self._query_cache:
            return self._query_cache[cache_key]
        
        # 初始化缓存
        if not hasattr(self, '_query_cache'):
            self._query_cache = {}
            self._cache_max_size = 100
        
        results_dict: Dict[str, float] = {}  # memory_id -> score
        
        # 2. 向量检索（如果可用）
        if self._vector_store:
            try:
                vector_results = self._vector_store.query(
                    query_texts=[query],
                    n_results=top_k * 2,
                    where={"category": category} if category else None
                )
                
                for mid, distance in zip(vector_results["ids"][0], vector_results["distances"][0]):
                    if mid in self._memory:
                        similarity = 1 - distance  # 距离转相似度
                        results_dict[mid] = alpha * similarity
            except Exception as e:
                print(f"[LongTermMemory] 向量检索失败: {e}")
        
        # 3. BM25 检索（简化版：基于词频）
        query_words = set(query.lower().split())
        if query_words:
            for mid, item in self._memory.items():
                # 类别过滤
                if category and item.category != category:
                    continue
                
                # 计算 BM25 分数（简化：匹配词数 / 总词数）
                content_words = set(item.content.lower().split())
                matches = len(query_words & content_words)
                
                if matches > 0:
                    bm25_score = matches / len(query_words)
                    
                    if mid in results_dict:
                        # 混合分数
                        results_dict[mid] += (1 - alpha) * bm25_score
                    else:
                        results_dict[mid] = (1 - alpha) * bm25_score
        
        # 4. 过滤、排序
        results = []
        for mid, score in results_dict.items():
            item = self._memory[mid]
            weight = item.get_current_weight()
            final_score = score * weight
            
            if final_score >= min_weight:
                item.touch()
                results.append((item, final_score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        top_results = results[:top_k]
        
        # 5. 缓存结果
        if len(self._query_cache) >= self._cache_max_size:
            # 移除最旧的
            oldest_key = next(iter(self._query_cache))
            del self._query_cache[oldest_key]
        
        self._query_cache[cache_key] = top_results
        
        return top_results
    
    def mark_strategy_success(self, memory_id: str):
        """标记策略成功（增加成功计数）"""
        if memory_id in self._memory:
            item = self._memory[memory_id]
            item.success_count += 1
            item.importance = min(2.0, item.importance + 0.1)  # 提升重要性
            
            # 更新内容中的 success_count
            try:
                data = json.loads(item.content)
                data["success_count"] = item.success_count
                item.content = json.dumps(data, ensure_ascii=False)
            except:
                pass
    
    def mark_strategy_failure(self, memory_id: str):
        """标记策略失败（降低权重）"""
        if memory_id in self._memory:
            item = self._memory[memory_id]
            item.failure_count += 1
            item.importance = max(0.1, item.importance - 0.1)  # 降低重要性
    
    def cleanup_decayed(self, min_weight: float = 0.1):
        """清理衰退过度的记忆"""
        to_remove = [
            mid for mid, item in self._memory.items()
            if item.get_current_weight() < min_weight
            and item.success_count < 3  # 成功次数高的永久保留
        ]
        
        for mid in to_remove:
            del self._memory[mid]
            # 同时从向量存储删除
            if self._vector_store:
                try:
                    self._vector_store.delete(ids=[mid])
                except:
                    pass
        
        if to_remove:
            print(f"[LongTermMemory] 清理 {len(to_remove)} 条衰退记忆")
    
    def _load(self):
        """从文件加载记忆"""
        memory_file = self.storage_path / "long_term_memory.json"
        if memory_file.exists():
            try:
                with open(memory_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item_data in data:
                        item = MemoryItem.from_dict(item_data)
                        self._memory[item.memory_id] = item
                print(f"[LongTermMemory] 加载 {len(self._memory)} 条记忆")
            except Exception as e:
                print(f"[LongTermMemory] 加载失败: {e}")
    
    def save(self):
        """保存记忆到文件"""
        memory_file = self.storage_path / "long_term_memory.json"
        try:
            data = [item.to_dict() for item in self._memory.values()]
            with open(memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[LongTermMemory] 保存 {len(self._memory)} 条记忆")
        except Exception as e:
            print(f"[LongTermMemory] 保存失败: {e}")
    
    def get_causal_analysis(
        self,
        memory_id: str,
        causal_graph: Optional['CausalMemoryGraph'] = None
    ) -> Optional[Dict[str, Any]]:
        """
        获取记忆条目的因果分析（主动预防的关键）
        
        能奋：
        - 判断该记忆是否一直失败
        - 预测下一个使用该记忆的节点是否会失败
        - 注入预防性提供
        
        Args:
            memory_id: 记忆条目 ID
            causal_graph: 因果图实例
        
        Returns:
            {
                "memory_id": str,
                "success_rate": float,
                "risk_level": str,
                "recommended_actions": List[str]
            }
        """
        if memory_id not in self._memory or not causal_graph:
            return None
        
        item = self._memory[memory_id]
        total = item.success_count + item.failure_count
        
        if total == 0:
            success_rate = 0.0
        else:
            success_rate = item.success_count / total
        
        # 判断风险等级
        if success_rate > 0.8:
            risk_level = "low"
        elif success_rate > 0.5:
            risk_level = "medium"
        else:
            risk_level = "high"
        
        recommendations = []
        if risk_level == "high":
            recommendations.append(
                f"下一步操作或调用该记忆时，需要增强验证或沿用品线（历史成功率仅 {success_rate:.1%}）"
            )
        elif risk_level == "medium":
            recommendations.append(
                f"下一步操作或调用该记忆时，清预备错误处理（歷史成功率 {success_rate:.1%}）"
            )
        
        recommendations.append(
            f"创建日志记录：{item.memory_id} - {item.source} - {item.category}"
        )
        
        return {
            "memory_id": memory_id,
            "success_rate": success_rate,
            "risk_level": risk_level,
            "recommended_actions": recommendations
        }
    
    def enable_causal_tracking(
        self,
        causal_graph: 'CausalMemoryGraph'
    ) -> bool:
        """
        启用因果追踪（将该记忆系统的所有操作记录到因果图）
        
        Args:
            causal_graph: 因果图实例
        
        Returns:
            是否成功启用
        """
        try:
            for memory_id, item in self._memory.items():
                # 为每一条记忆添加一个节点
                causal_graph.add_node(
                    content=f"{item.source}: {item.category}",
                    node_type="memory_item",
                    success=True  # 记忆本身不算失败
                )
            
            print(f"[LongTermMemory] 启用因果追踪，已记录 {len(self._memory)} 条记忆")
            return True
        except Exception as e:
            print(f"[LongTermMemory] 启用因果追踪失败: {e}")
            return False
    
    def __len__(self):
        return len(self._memory)


# =============================================================================
# 4. 统一记忆系统（Memory System）
# =============================================================================

class MemorySystem:
    """
    统一记忆系统 - 整合短期和长期记忆
    
    【使用方式】
    memory = MemorySystem()
    
    # 记录对话
    memory.add_conversation(role="user", content="查询茅台股价")
    memory.add_conversation(role="agent", content="茅台股价为 1850 元")
    
    # 记录成功策略
    memory.add_successful_strategy(
        query_pattern="查询[股票]的[指标]",
        strategy="使用 daily_basic 接口",
        execution_steps=["获取股票代码", "调用 API", "格式化输出"]
    )
    
    # 检索相关记忆
    context = memory.get_context_for_query("查询五粮液股价")
    """
    
    def __init__(
        self,
        storage_path: str = "./memory_store",
        short_term_size: int = 10,
        short_term_ttl: int = 30
    ):
        self.short_term = ShortTermMemory(
            max_size=short_term_size,
            ttl_minutes=short_term_ttl
        )
        self.long_term = LongTermMemory(storage_path=storage_path)
        
        # 初始化因果记忆图 - 用于主动预防
        self.causal_graph = CausalMemoryGraph()
        
        print(f"[MemorySystem] 初始化完成 - 短期: {len(self.short_term)}, 长期: {len(self.long_term)}, 因果图: 已激活")
    
    def add_conversation(self, role: str, content: str, category: str = "") -> str:
        """添加对话到短期记忆"""
        return self.short_term.add(
            content=f"[{role}] {content}",
            source="conversation",
            category=category
        )
    
    def add_successful_strategy(
        self,
        query_pattern: str,
        strategy: str,
        execution_steps: List[str],
        category: str = ""
    ) -> str:
        """添加成功策略到长期记忆"""
        return self.long_term.add_successful_strategy(
            query_pattern=query_pattern,
            strategy=strategy,
            execution_steps=execution_steps,
            category=category
        )
    
    def add_knowledge(self, content: str, source: str, category: str = "") -> str:
        """添加知识片段到长期记忆"""
        return self.long_term.add(
            content=content,
            source=source,
            category=category,
            importance=1.0
        )
    
    def get_context_for_query(self, query: str, include_strategies: bool = True) -> str:
        """
        获取查询相关的完整上下文（用于注入 Prompt）
        
        Returns:
            包含短期记忆 + 长期记忆提示的字符串
        """
        context_parts = []
        
        # 1. 短期记忆（近期对话）
        short_context = self.short_term.get_context_string(n=5)
        if short_context:
            context_parts.append(short_context)
        
        # 2. 长期记忆（成功策略）- 使用 search_hybrid() 提升检索性能
        if include_strategies and query:
            try:
                # 优先使用 search_hybrid()（BM25+ 向量混合检索）
                if hasattr(self.long_term, 'search_hybrid'):
                    results = self.long_term.search_hybrid(
                        query=query,
                        top_k=3,
                        alpha=0.7  # 70% 向量，30% BM25
                    )
                    print(f"[MemorySystem] 使用 search_hybrid() 检索到 {len(results)} 条策略")
                else:
                    # 降级到普通 search()
                    results = self.long_term.search(query, top_k=3)
                    print(f"[MemorySystem] 使用 search() 检索到 {len(results)} 条策略")
                
                # 构建策略提示
                if results:
                    strategy_parts = ["\n【历史成功策略】"]
                    for item, score in results[:3]:
                        if item.source == "successful_strategy" and score > 0.4:
                            try:
                                strategy_data = json.loads(item.content)
                                strategy_parts.append(
                                    f"- 问题模式：{strategy_data.get('query_pattern', '')}\n"
                                    f"  成功策略：{strategy_data.get('strategy', '')}\n"
                                    f"  执行步骤：{' → '.join(strategy_data.get('execution_steps', []))}\n"
                                    f"  匹配度：{score:.2f}"
                                )
                            except:
                                pass
                    if len(strategy_parts) > 1:
                        context_parts.append("\n".join(strategy_parts))
            except Exception as e:
                print(f"[MemorySystem] 长期记忆检索失败：{e}")
        
        return "\n\n".join(context_parts) if context_parts else ""
    
    def promote_to_long_term(self, short_term_id: str, importance: float = 1.0):
        """将短期记忆提升为长期记忆"""
        # 从短期记忆中查找
        if short_term_id in self.short_term._memory:
            item = self.short_term._memory[short_term_id]
            self.long_term.add(
                content=item.content,
                source=item.source,
                category=item.category,
                importance=importance
            )
            print(f"[MemorySystem] 记忆 {short_term_id} 提升为长期记忆")
    
    def clear_short_term(self):
        """清空短期记忆"""
        self.short_term.clear()
    
    def save(self):
        """保存所有记忆"""
        self.long_term.save()
    
    def cleanup(self, min_weight: float = 0.1):
        """清理衰退的长期记忆"""
        self.long_term.cleanup_decayed(min_weight=min_weight)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        causal_stats = self.causal_graph.get_graph_stats()
        return {
            "short_term_count": len(self.short_term),
            "long_term_count": len(self.long_term),
            "chroma_available": CHROMA_AVAILABLE,
            "causal_graph": causal_stats
        }
    
    def record_execution_node(
        self,
        content: str,
        node_type: str = "task",
        success: bool = True
    ) -> str:
        """
        记录执行节点到因果图（用于主动预防）
        
        Args:
            content: 节点描述
            node_type: 节点类型 (task, tool_call, memory_retrieve, review)
            success: 是否成功
        
        Returns:
            node_id: 新节点的 ID
        """
        return self.causal_graph.add_node(content, node_type, success)
    
    def record_causal_relationship(
        self,
        from_node_id: str,
        to_node_id: str,
        strength: float = 1.0
    ) -> bool:
        """
        记录因果关系（上一个节点失败可能导致下一个节点失败）
        
        Args:
            from_node_id: 源节点 ID
            to_node_id: 目标节点 ID
            strength: 因果强度 (0.0-1.0)
        
        Returns:
            是否成功添加
        """
        return self.causal_graph.add_causal_edge(from_node_id, to_node_id, strength)
    
    def get_failure_predictions(
        self,
        node_id: str
    ) -> Dict[str, Any]:
        """
        获取节点的失败风险预测（主动预防的关键）
        
        Returns:
            {
                "node_id": str,
                "failure_rate": float,
                "risk_level": str ("low", "medium", "high"),
                "contributing_factors": List[str],
                "preventive_actions": List[Dict[str, str]]
            }
        """
        risk_info = self.causal_graph.predict_failure_risk(node_id)
        preventive_actions = self.causal_graph.get_preventive_actions(node_id)
        
        return {
            **risk_info,
            "preventive_actions": preventive_actions
        }
    
    def get_root_causes(
        self,
        node_id: str
    ) -> List[str]:
        """
        获取节点失败的根因链
        
        Returns:
            失败传播链的节点 ID 列表（从失败点到根因点）
        """
        return self.causal_graph.record_failure_chain(node_id)


# =============================================================================
# 5. 全局实例（供 multi_agent.py 使用）
# =============================================================================

# 创建全局记忆系统实例
memory_system = MemorySystem(storage_path="./memory_store")


# =============================================================================
# 6. 集成辅助函数
# =============================================================================

def get_memory_context(query: str) -> str:
    """
    便捷函数：获取记忆上下文
    
    在 multi_agent.py 中使用：
    ```python
    from memory_system import get_memory_context
    
    context = get_memory_context(user_query)
    system_prompt += context
    ```
    """
    return memory_system.get_context_for_query(query)


def record_successful_execution(
    query: str,
    strategy: str,
    steps: List[str],
    category: str = ""
):
    """
    便捷函数：记录成功执行
    
    在 multi_agent.py 的 FINISH 节点使用：
    ```python
    from memory_system import record_successful_execution
    
    if execution_status == "success":
        record_successful_execution(
            query=original_query,
            strategy="使用 daily_basic 接口查询",
            steps=["获取代码", "调用API", "输出结果"]
        )
    ```
    """
    memory_system.add_successful_strategy(
        query_pattern=query,
        strategy=strategy,
        execution_steps=steps,
        category=category
    )
    memory_system.save()


# =============================================================================
# 7. 测试代码
# =============================================================================

if __name__ == "__main__":
    print("=== 记忆系统测试 ===\n")
    
    # 创建测试实例
    memory = MemorySystem(storage_path="./test_memory_store")
    
    # 1. 测试短期记忆
    print("【1. 短期记忆测试】")
    memory.add_conversation("user", "查询贵州茅台的股息率")
    memory.add_conversation("agent", "[DATA] 贵州茅台股息率为 1.23%")
    memory.add_conversation("user", "和五粮液比呢？")
    
    print(f"短期记忆数量: {len(memory.short_term)}")
    print(memory.short_term.get_context_string())
    
    # 2. 测试成功策略记录
    print("\n【2. 成功策略记录】")
    strategy_id = memory.add_successful_strategy(
        query_pattern="查询[股票]的股息率",
        strategy="使用 daily_basic 接口的 dv_ttm 字段",
        execution_steps=["获取股票代码", "调用 daily_basic", "提取 dv_ttm"],
        category="stock_query"
    )
    print(f"策略 ID: {strategy_id}")
    
    # 3. 测试记忆检索
    print("\n【3. 记忆检索测试】")
    context = memory.get_context_for_query("查询比亚迪的股息率")
    print(context)
    
    # 4. 测试统计
    print("\n【4. 统计信息】")
    print(memory.get_stats())
    
    # 5. 保存
    memory.save()
    print("\n记忆已保存!")
