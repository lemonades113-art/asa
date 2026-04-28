#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TrajectoryCollector - 轨迹收集器
用于自动收集智能体运行轨迹，为后续 SFT/DPO 微调准备数据

【研究价值】
- 将工程运行过程转化为 Preference Data（偏好数据）
- 格式兼容 DPO (Direct Preference Optimization) 训练
- 支持 Error-Specific 分类，为分层微调提供基础

【数据格式】
{
    "prompt": "用户查询",
    "chosen": "成功执行的代码/回答",
    "rejected": "失败的代码/回答",
    "error_type": "SyntaxError|NameError|TypeError|...",
    "error_msg": "具体错误信息",
    "difficulty": "easy|medium|hard",
    "trajectory_id": "唯一标识",
    "timestamp": "ISO格式时间戳"
}
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict


# =============================================================================
# 1. 错误分类枚举（对应 Error-Specific DPO）
# =============================================================================

ERROR_CATEGORIES = {
    "SyntaxError": {"beta": 0.8, "description": "语法错误，通常是代码格式问题"},
    "NameError": {"beta": 0.6, "description": "变量名错误，通常是拼写或作用域问题"},
    "TypeError": {"beta": 0.7, "description": "类型错误，通常是数据类型不匹配"},
    "ValueError": {"beta": 0.7, "description": "值错误，通常是参数范围问题"},
    "KeyError": {"beta": 0.6, "description": "键错误，通常是字典访问问题"},
    "IndexError": {"beta": 0.6, "description": "索引错误，通常是列表越界"},
    "AttributeError": {"beta": 0.7, "description": "属性错误，通常是对象没有该属性"},
    "ImportError": {"beta": 0.5, "description": "导入错误，通常是缺少依赖"},
    "TimeoutError": {"beta": 0.9, "description": "超时错误，通常是代码效率问题"},
    "NetworkError": {"beta": 1.0, "description": "网络错误，通常是API调用问题"},
    "DataEmpty": {"beta": 0.8, "description": "数据为空，通常是查询条件问题"},
    "Unknown": {"beta": 0.5, "description": "未知错误"}
}


def classify_error(error_msg: str) -> str:
    """
    根据错误信息自动分类错误类型
    
    Args:
        error_msg: 错误信息字符串
    
    Returns:
        错误类型（用于 Error-Specific DPO）
    """
    error_msg_lower = error_msg.lower()
    
    if "syntaxerror" in error_msg_lower or "invalid syntax" in error_msg_lower:
        return "SyntaxError"
    elif "nameerror" in error_msg_lower or "is not defined" in error_msg_lower:
        return "NameError"
    elif "typeerror" in error_msg_lower:
        return "TypeError"
    elif "valueerror" in error_msg_lower:
        return "ValueError"
    elif "keyerror" in error_msg_lower:
        return "KeyError"
    elif "indexerror" in error_msg_lower:
        return "IndexError"
    elif "attributeerror" in error_msg_lower:
        return "AttributeError"
    elif "importerror" in error_msg_lower or "modulenotfounderror" in error_msg_lower:
        return "ImportError"
    elif "timeout" in error_msg_lower:
        return "TimeoutError"
    elif "connection" in error_msg_lower or "network" in error_msg_lower:
        return "NetworkError"
    elif "[data]: {}" in error_msg_lower or "[data]: []" in error_msg_lower or "empty" in error_msg_lower:
        return "DataEmpty"
    else:
        return "Unknown"


# =============================================================================
# 2. 轨迹数据结构
# =============================================================================

@dataclass
class TrajectoryStep:
    """单步轨迹"""
    action: str  # 动作类型: "coder_generate", "tool_call", "reviewer_analyze", etc.
    input_content: str  # 输入内容
    output_content: str  # 输出内容
    success: bool  # 是否成功
    error_msg: Optional[str] = None  # 错误信息（如果失败）
    error_type: Optional[str] = None  # 错误类型（自动分类）
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Trajectory:
    """完整轨迹"""
    trajectory_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_query: str = ""
    steps: List[TrajectoryStep] = field(default_factory=list)
    final_success: bool = False
    final_output: Optional[str] = None
    total_retries: int = 0
    difficulty: str = "medium"  # easy/medium/hard
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# =============================================================================
# 3. TrajectoryCollector 核心类
# =============================================================================

class TrajectoryCollector:
    """
    轨迹收集器 - 自动收集智能体运行轨迹
    
    【核心功能】
    1. 记录每一步的输入/输出
    2. 自动分类错误类型
    3. 生成 DPO 格式的偏好数据
    4. 按难度分层（用于 Curriculum Learning）
    
    【使用方式】
    collector = TrajectoryCollector()
    collector.start_trajectory(user_query)
    collector.record_step(action, input, output, success, error_msg)
    collector.finish_trajectory(success, final_output)
    collector.save()
    """
    
    def __init__(self, output_dir: str = "./trajectories"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.current_trajectory: Optional[Trajectory] = None
        self.all_trajectories: List[Trajectory] = []
        
        # 统计信息
        self.stats = {
            "total": 0,
            "success": 0,
            "failed": 0,
            "by_error_type": {},
            "by_difficulty": {"easy": 0, "medium": 0, "hard": 0}
        }
    
    def start_trajectory(self, user_query: str) -> str:
        """
        开始记录一条新的轨迹
        
        Args:
            user_query: 用户的原始查询
        
        Returns:
            trajectory_id: 轨迹唯一标识
        """
        self.current_trajectory = Trajectory(user_query=user_query)
        print(f"[TrajectoryCollector] 开始记录轨迹: {self.current_trajectory.trajectory_id}")
        return self.current_trajectory.trajectory_id
    
    def record_step(
        self,
        action: str,
        input_content: str,
        output_content: str,
        success: bool,
        error_msg: Optional[str] = None
    ):
        """
        记录一步执行
        
        Args:
            action: 动作类型 ("coder_generate", "tool_call", "reviewer_analyze", etc.)
            input_content: 输入内容（prompt/code）
            output_content: 输出内容（response/result）
            success: 是否成功
            error_msg: 错误信息（如果失败）
        """
        if not self.current_trajectory:
            print("[TrajectoryCollector] 警告: 未开始轨迹，忽略此步")
            return
        
        # 自动分类错误
        error_type = None
        if not success and error_msg:
            error_type = classify_error(error_msg)
            self.current_trajectory.total_retries += 1
        
        step = TrajectoryStep(
            action=action,
            input_content=input_content,
            output_content=output_content,
            success=success,
            error_msg=error_msg,
            error_type=error_type
        )
        
        self.current_trajectory.steps.append(step)
        
        # 打印日志
        status = "✅" if success else f"❌ [{error_type}]"
        print(f"[TrajectoryCollector] {status} {action}")
    
    def finish_trajectory(self, success: bool, final_output: Optional[str] = None):
        """
        完成当前轨迹记录
        
        Args:
            success: 整体是否成功
            final_output: 最终输出
        """
        if not self.current_trajectory:
            print("[TrajectoryCollector] 警告: 未开始轨迹，无法完成")
            return
        
        self.current_trajectory.final_success = success
        self.current_trajectory.final_output = final_output
        
        # 根据重试次数判断难度
        retries = self.current_trajectory.total_retries
        if retries == 0:
            self.current_trajectory.difficulty = "easy"
        elif retries <= 2:
            self.current_trajectory.difficulty = "medium"
        else:
            self.current_trajectory.difficulty = "hard"
        
        # 更新统计
        self.stats["total"] += 1
        if success:
            self.stats["success"] += 1
        else:
            self.stats["failed"] += 1
        
        self.stats["by_difficulty"][self.current_trajectory.difficulty] += 1
        
        # 统计错误类型
        for step in self.current_trajectory.steps:
            if step.error_type:
                self.stats["by_error_type"][step.error_type] = \
                    self.stats["by_error_type"].get(step.error_type, 0) + 1
        
        # 保存到列表
        self.all_trajectories.append(self.current_trajectory)
        
        print(f"[TrajectoryCollector] 轨迹完成: {self.current_trajectory.trajectory_id} "
              f"({'成功' if success else '失败'}, 难度: {self.current_trajectory.difficulty})")
        
        self.current_trajectory = None
    
    def to_dpo_format(self, trajectory: Trajectory) -> Optional[Dict[str, Any]]:
        """
        将轨迹转换为 DPO 训练格式
        
        【DPO 数据结构】
        - prompt: 用户查询
        - chosen: 成功的代码/回答
        - rejected: 失败的代码/回答
        - error_type: 错误类型（用于 Error-Specific DPO）
        """
        if not trajectory.final_success:
            # 如果最终失败，没有 chosen 样本
            return None
        
        # 找到最后一个成功的输出作为 chosen
        chosen = trajectory.final_output
        
        # 找到最后一个失败的输出作为 rejected
        rejected = None
        error_type = None
        error_msg = None
        
        for step in reversed(trajectory.steps):
            if not step.success and step.output_content:
                rejected = step.output_content
                error_type = step.error_type
                error_msg = step.error_msg
                break
        
        if not rejected:
            # 没有失败样本，纯 SFT 数据
            return {
                "prompt": trajectory.user_query,
                "chosen": chosen,
                "rejected": None,
                "error_type": None,
                "difficulty": trajectory.difficulty,
                "trajectory_id": trajectory.trajectory_id,
                "timestamp": trajectory.timestamp,
                "data_type": "sft_only"
            }
        
        return {
            "prompt": trajectory.user_query,
            "chosen": chosen,
            "rejected": rejected,
            "error_type": error_type,
            "error_msg": error_msg,
            "difficulty": trajectory.difficulty,
            "trajectory_id": trajectory.trajectory_id,
            "timestamp": trajectory.timestamp,
            "data_type": "dpo_pair"
        }
    
    def save(self, filename: Optional[str] = None):
        """
        保存所有轨迹到文件
        
        Args:
            filename: 文件名（默认按日期生成）
        """
        if not filename:
            filename = f"trajectories_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        
        filepath = self.output_dir / filename
        
        # 保存 DPO 格式数据
        dpo_data = []
        for traj in self.all_trajectories:
            dpo_item = self.to_dpo_format(traj)
            if dpo_item:
                dpo_data.append(dpo_item)
        
        with open(filepath, "w", encoding="utf-8") as f:
            for item in dpo_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        
        print(f"[TrajectoryCollector] 保存 {len(dpo_data)} 条轨迹到 {filepath}")
        
        # 保存统计信息
        stats_file = self.output_dir / "stats.json"
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2)
        
        print(f"[TrajectoryCollector] 统计信息: {self.stats}")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.stats
    
    def get_error_distribution(self) -> Dict[str, int]:
        """获取错误类型分布（用于 Error-Specific DPO 分析）"""
        return self.stats["by_error_type"]


# =============================================================================
# 4. 全局实例（供 multi_agent.py 使用）
# =============================================================================

# 创建全局收集器实例
trajectory_collector = TrajectoryCollector()


# =============================================================================
# 5. 集成到 multi_agent.py 的辅助函数
# =============================================================================

def integrate_with_multi_agent(state: Dict) -> None:
    """
    在 multi_agent.py 的关键节点调用此函数
    
    用法（在 supervisor_node 开始时）:
        from trajectory_collector import trajectory_collector
        trajectory_collector.start_trajectory(user_query)
    
    用法（在 coder_node 执行后）:
        trajectory_collector.record_step(
            action="coder_generate",
            input_content=prompt,
            output_content=response,
            success=not has_error,
            error_msg=error_msg
        )
    
    用法（在 FINISH 节点）:
        trajectory_collector.finish_trajectory(success=True, final_output=report)
        trajectory_collector.save()
    """
    pass  # 占位符，实际集成在 multi_agent.py 中完成


# =============================================================================
# 6. 测试代码
# =============================================================================

if __name__ == "__main__":
    # 模拟一次成功的轨迹
    collector = TrajectoryCollector(output_dir="./test_trajectories")
    
    # 开始
    collector.start_trajectory("查询贵州茅台最近的股息率")
    
    # 第一次尝试（失败）
    collector.record_step(
        action="coder_generate",
        input_content="生成查询股息率的代码",
        output_content="import tushare as ts\ndf = ts.pro_api().daily_basic(ts_code='600519')",
        success=False,
        error_msg="NameError: name 'ts' is not defined"
    )
    
    # 第二次尝试（成功）
    collector.record_step(
        action="coder_generate",
        input_content="修复后的代码",
        output_content="import tushare as ts\npro = ts.pro_api()\ndf = pro.daily_basic(ts_code='600519.SH')\nprint(df['dv_ttm'].iloc[0])",
        success=True
    )
    
    # 完成
    collector.finish_trajectory(
        success=True,
        final_output="贵州茅台的股息率为 1.23%"
    )
    
    # 保存
    collector.save()
    
    print("\n=== 统计信息 ===")
    print(collector.get_stats())
    print("\n=== 错误分布 ===")
    print(collector.get_error_distribution())
