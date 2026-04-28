#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA 项目 - 开源数据集评估脚本

【功能】
1. 自动下载 FinQA/ConvFinQA 数据集
2. 转换为 ASA 可用的格式
3. 批量运行并收集轨迹
4. 生成评估报告

【使用方式】
    # 安装依赖
    pip install datasets huggingface_hub
    
    # 运行评估
    python run_opensource_dataset.py --dataset convfinqa --num_samples 50

【数据集选项】
- finqa: FinQA 数据集（8K 问题，偏向数值推理）
- convfinqa: ConvFinQA 数据集（3.6K 多轮对话，更接近 ASA 场景）
- fino1: Fino1_Reasoning_Path（5.5K，包含推理链）
"""

import json
import time
import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

# 检查依赖
try:
    from datasets import load_dataset
    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    print("⚠️  请先安装 datasets: pip install datasets huggingface_hub")


# =============================================================================
# 1. 数据集加载和转换
# =============================================================================

@dataclass
class TestSample:
    """测试样本"""
    id: int
    source: str  # finqa | convfinqa | fino1
    question: str
    context: str  # 财务报表/表格上下文
    gold_answer: Optional[str] = None
    reasoning_chain: Optional[str] = None  # 推理链（如果有）
    difficulty: str = "medium"


def load_finqa_samples(num_samples: int = 50) -> List[TestSample]:
    """加载 FinQA 数据集"""
    print(f"正在加载 FinQA 数据集（{num_samples} 个样本）...")
    
    try:
        dataset = load_dataset("ibm-research/finqa", split="train")
        samples = []
        
        for i, item in enumerate(dataset):
            if i >= num_samples:
                break
            
            # 提取问题和上下文
            question = item.get("question", "")
            pre_text = item.get("pre_text", [])
            post_text = item.get("post_text", [])
            table = item.get("table", [])
            
            # 构建上下文
            context_parts = []
            if pre_text:
                context_parts.append("【背景】" + " ".join(pre_text))
            if table:
                context_parts.append("【表格数据】" + str(table))
            if post_text:
                context_parts.append("【补充】" + " ".join(post_text))
            context = "\n".join(context_parts)
            
            # 获取答案
            answer = item.get("answer", "")
            
            samples.append(TestSample(
                id=i + 1,
                source="finqa",
                question=question,
                context=context,
                gold_answer=str(answer),
                difficulty="medium" if i < num_samples // 2 else "hard"
            ))
        
        print(f"✅ 加载了 {len(samples)} 个 FinQA 样本")
        return samples
        
    except Exception as e:
        print(f"❌ 加载 FinQA 失败: {e}")
        return []


def load_convfinqa_samples(num_samples: int = 50) -> List[TestSample]:
    """加载 ConvFinQA 数据集（多轮对话）"""
    print(f"正在加载 ConvFinQA 数据集（{num_samples} 个样本）...")
    
    try:
        # ConvFinQA 在 FinGPT 的 HuggingFace 仓库
        dataset = load_dataset("FinGPT/fingpt-convfinqa", split="train")
        samples = []
        
        for i, item in enumerate(dataset):
            if i >= num_samples:
                break
            
            # ConvFinQA 格式：instruction + input + output
            instruction = item.get("instruction", "")
            input_text = item.get("input", "")
            output = item.get("output", "")
            
            # 合并为问题
            question = instruction
            if input_text:
                question += f"\n上下文: {input_text}"
            
            samples.append(TestSample(
                id=i + 1,
                source="convfinqa",
                question=question,
                context=input_text,
                gold_answer=output,
                difficulty="medium"
            ))
        
        print(f"✅ 加载了 {len(samples)} 个 ConvFinQA 样本")
        return samples
        
    except Exception as e:
        print(f"❌ 加载 ConvFinQA 失败: {e}")
        return []


def load_fino1_samples(num_samples: int = 50) -> List[TestSample]:
    """加载 Fino1 数据集（包含推理链）"""
    print(f"正在加载 Fino1 数据集（{num_samples} 个样本）...")
    
    try:
        dataset = load_dataset("TheFinAI/Fino1_Reasoning_Path_FinQA", split="train")
        samples = []
        
        for i, item in enumerate(dataset):
            if i >= num_samples:
                break
            
            question = item.get("question", "")
            answer = item.get("answer", "")
            reasoning = item.get("reasoning_path", "")  # 推理链
            
            samples.append(TestSample(
                id=i + 1,
                source="fino1",
                question=question,
                context="",
                gold_answer=answer,
                reasoning_chain=reasoning,
                difficulty="hard" if reasoning else "medium"
            ))
        
        print(f"✅ 加载了 {len(samples)} 个 Fino1 样本")
        return samples
        
    except Exception as e:
        print(f"❌ 加载 Fino1 失败: {e}")
        return []


# =============================================================================
# 2. ASA 系统调用
# =============================================================================

def run_asa_query(question: str, context: str = "") -> Dict[str, Any]:
    """
    调用 ASA 多智能体系统
    
    Returns:
        {
            "success": bool,
            "response": str,
            "time_seconds": float,
            "error": Optional[str],
            "trajectory": Optional[dict]  # 轨迹数据（用于微调）
        }
    """
    try:
        from langchain_core.messages import HumanMessage
        from multi_agent import multi_agent_app
        
        # 构建完整问题
        full_query = question
        if context:
            full_query = f"{question}\n\n参考数据:\n{context[:500]}..."  # 截断上下文
        
        # 配置
        thread_id = f"opensource_test_{int(time.time()*1000)}"
        config = {"configurable": {"thread_id": thread_id}}
        
        # 初始状态
        initial_state = {
            "messages": [HumanMessage(content=full_query)],
            "next_agent": "supervisor",
        }
        
        # 执行
        start_time = time.time()
        final_state = multi_agent_app.invoke(initial_state, config)
        elapsed = time.time() - start_time
        
        # 提取响应
        messages = final_state.get("messages", [])
        if messages:
            last_msg = messages[-1]
            response = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
        else:
            response = ""
        
        return {
            "success": True,
            "response": response,
            "time_seconds": elapsed,
            "error": None,
        }
        
    except Exception as e:
        return {
            "success": False,
            "response": "",
            "time_seconds": 0,
            "error": str(e)[:200],
        }


# =============================================================================
# 3. 批量评估
# =============================================================================

def evaluate_samples(samples: List[TestSample], output_file: str) -> Dict[str, Any]:
    """批量评估样本"""
    
    print(f"\n{'='*70}")
    print(f"【开始批量评估】")
    print(f"样本数: {len(samples)}")
    print(f"输出文件: {output_file}")
    print(f"{'='*70}\n")
    
    results = []
    start_time = time.time()
    
    for i, sample in enumerate(samples, 1):
        print(f"[{i:3d}/{len(samples)}] {sample.source:12s} | {sample.question[:50]:50s}", end=" ")
        
        result = run_asa_query(sample.question, sample.context)
        
        # 简单的答案匹配（如果有 gold_answer）
        answer_match = False
        if sample.gold_answer and result["success"]:
            # 简单匹配：检查关键数字或关键词是否出现
            gold_lower = sample.gold_answer.lower()
            response_lower = result["response"].lower()
            # 提取数字进行匹配
            import re
            gold_numbers = set(re.findall(r'\d+\.?\d*', gold_lower))
            response_numbers = set(re.findall(r'\d+\.?\d*', response_lower))
            if gold_numbers and gold_numbers.intersection(response_numbers):
                answer_match = True
        
        results.append({
            "id": sample.id,
            "source": sample.source,
            "question": sample.question,
            "gold_answer": sample.gold_answer,
            "asa_response": result["response"][:500],  # 截断
            "success": result["success"],
            "answer_match": answer_match,
            "time_seconds": result["time_seconds"],
            "error": result.get("error"),
            "difficulty": sample.difficulty,
        })
        
        status = "✅" if result["success"] else "❌"
        match = "🎯" if answer_match else ""
        print(f"{status} {result['time_seconds']:.1f}s {match}")
        
        # 休息，避免 API 限流
        time.sleep(0.5)
    
    total_time = time.time() - start_time
    
    # 保存结果
    with open(output_file, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    
    # 计算统计
    success_count = sum(1 for r in results if r["success"])
    match_count = sum(1 for r in results if r["answer_match"])
    
    stats = {
        "total": len(results),
        "success": success_count,
        "success_rate": success_count / len(results) if results else 0,
        "answer_match": match_count,
        "match_rate": match_count / len(results) if results else 0,
        "total_time_seconds": total_time,
        "avg_time_seconds": total_time / len(results) if results else 0,
    }
    
    # 按来源统计
    by_source = {}
    for r in results:
        src = r["source"]
        if src not in by_source:
            by_source[src] = {"total": 0, "success": 0, "match": 0}
        by_source[src]["total"] += 1
        if r["success"]:
            by_source[src]["success"] += 1
        if r["answer_match"]:
            by_source[src]["match"] += 1
    
    stats["by_source"] = by_source
    
    return stats


def print_summary(stats: Dict[str, Any]):
    """打印统计摘要"""
    print(f"\n{'='*70}")
    print("【评估完成 - 统计摘要】")
    print(f"{'='*70}")
    
    print(f"\n📊 整体统计：")
    print(f"   总数: {stats['total']}")
    print(f"   成功: {stats['success']} ({stats['success_rate']:.0%})")
    print(f"   答案匹配: {stats['answer_match']} ({stats['match_rate']:.0%})")
    print(f"   总耗时: {stats['total_time_seconds']/60:.1f} 分钟")
    print(f"   平均耗时: {stats['avg_time_seconds']:.1f} 秒/个")
    
    print(f"\n📈 按数据集分布：")
    for src, data in stats.get("by_source", {}).items():
        success_rate = data["success"] / data["total"] if data["total"] else 0
        match_rate = data["match"] / data["total"] if data["total"] else 0
        print(f"   {src:12s}: 成功 {success_rate:.0%} | 匹配 {match_rate:.0%}")
    
    print(f"\n{'='*70}")


# =============================================================================
# 4. 数据集适配性分析
# =============================================================================

def analyze_dataset_fit():
    """分析各数据集与 ASA 的适配性"""
    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║                    开源数据集与 ASA 适配性分析                              ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 数据集       │ 规模   │ 适配度 │ 原因                                     ║
╠══════════════════════════════════════════════════════════════════════════╣
║ FinQA        │ 8.7K   │ ⚠️ 中  │ 答案是 DSL 程序，不是自然语言              ║
║ ConvFinQA    │ 3.6K   │ ✅ 高  │ 多轮对话，接近真实交互                     ║
║ Fino1        │ 5.5K   │ ✅ 高  │ 包含 GPT-4 推理链，可直接参考               ║
║ TAT-QA       │ 16.4K  │ ⚠️ 中  │ 偏表格理解，ASA 场景较少                   ║
╠══════════════════════════════════════════════════════════════════════════╣
║ 【推荐】ConvFinQA + Fino1 混合使用                                        ║
║   - ConvFinQA: 测试多轮对话能力                                            ║
║   - Fino1: 提供推理链参考，可用于 SFT 数据增强                              ║
╚══════════════════════════════════════════════════════════════════════════╝
""")


# =============================================================================
# 5. 主函数
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ASA 项目 - 开源数据集评估脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 使用 ConvFinQA 评估 50 个样本
    python run_opensource_dataset.py --dataset convfinqa --num_samples 50
    
    # 使用 FinQA 评估 100 个样本
    python run_opensource_dataset.py --dataset finqa --num_samples 100
    
    # 使用 Fino1（包含推理链）
    python run_opensource_dataset.py --dataset fino1 --num_samples 50
    
    # 混合多个数据集
    python run_opensource_dataset.py --dataset all --num_samples 30
        """
    )
    
    parser.add_argument(
        "--dataset",
        type=str,
        default="convfinqa",
        choices=["finqa", "convfinqa", "fino1", "all"],
        help="选择数据集"
    )
    
    parser.add_argument(
        "--num_samples",
        type=int,
        default=50,
        help="每个数据集的样本数"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default="opensource_eval_results.jsonl",
        help="输出文件路径"
    )
    
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="仅显示数据集适配性分析，不运行评估"
    )
    
    args = parser.parse_args()
    
    # 仅分析模式
    if args.analyze:
        analyze_dataset_fit()
        return
    
    # 检查依赖
    if not HF_AVAILABLE:
        print("❌ 缺少依赖，请运行: pip install datasets huggingface_hub")
        sys.exit(1)
    
    # 加载数据集
    samples = []
    
    if args.dataset == "finqa" or args.dataset == "all":
        samples.extend(load_finqa_samples(args.num_samples))
    
    if args.dataset == "convfinqa" or args.dataset == "all":
        samples.extend(load_convfinqa_samples(args.num_samples))
    
    if args.dataset == "fino1" or args.dataset == "all":
        samples.extend(load_fino1_samples(args.num_samples))
    
    if not samples:
        print("❌ 没有加载到任何样本")
        sys.exit(1)
    
    # 运行评估
    stats = evaluate_samples(samples, args.output)
    
    # 打印摘要
    print_summary(stats)
    
    print(f"\n✅ 结果已保存到: {args.output}")
    print(f"💡 下一步: 分析失败案例，收集轨迹用于微调")


if __name__ == "__main__":
    main()
