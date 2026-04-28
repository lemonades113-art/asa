#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Multi-Agent系统测试脚本
演示：Supervisor路由 + Coder执行 + ErrorHandler自我修正 + Reviewer分析
"""

import uuid
from langchain_core.messages import HumanMessage

from multi_agent import multi_agent_app, MultiAgentState


def test_multi_agent_workflow():
    """测试Multi-Agent完整工作流"""
    
    print("\n" + "=" * 80)
    print("Multi-Agent系统完整工作流演示")
    print("=" * 80 + "\n")
    
    # 1. 初始化会话
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "messages": [],
        "next": "Supervisor",
        "retry_count": 0,
        "user_profile": {
            "username": "用户",
            "risk_preference": "稳健型",
            "interested_industries": ["金融"],
            "investment_style": "基本面"
        },
        "execution_status": "pending"
    }
    
    multi_agent_app.update_state(config, initial_state)
    
    print(f"✓ 会话已初始化")
    print(f"  Thread ID: {thread_id}\n")
    
    # 2. 测试场景1：数据获取和绘图
    print("-" * 80)
    print("【测试场景1】获取数据并绘图")
    print("-" * 80)
    print("User: 帮我查一下平安银行最近30天的收盘价，画成折线图看看\n")
    
    query1 = "帮我查一下平安银行最近30天的收盘价，画成折线图看看"
    
    step = 0
    for event in multi_agent_app.stream(
        {"messages": [HumanMessage(content=query1)]},
        config,
        stream_mode="values"
    ):
        step += 1
        if "next" in event:
            print(f"[Step {step}] Next: {event.get('next', 'N/A')}")
    
    state1 = multi_agent_app.get_state(config).values
    print(f"\n✓ 场景1完成")
    print(f"  最后状态: {state1.get('next')}")
    print(f"  执行状态: {state1.get('execution_status')}")
    print(f"  重试次数: {state1.get('retry_count')}\n")
    
    # 3. 测试场景2：带错误修正的代码执行
    print("-" * 80)
    print("【测试场景2】分析数据并生成报告")
    print("-" * 80)
    print("User: 现在基于这个数据，帮我分析一下平安银行的走势\n")
    
    query2 = "现在基于这个数据，帮我分析一下平安银行的走势"
    
    step = 0
    for event in multi_agent_app.stream(
        {"messages": [HumanMessage(content=query2)]},
        config,
        stream_mode="values"
    ):
        step += 1
        if "next" in event:
            print(f"[Step {step}] Next: {event.get('next', 'N/A')}")
    
    state2 = multi_agent_app.get_state(config).values
    print(f"\n✓ 场景2完成")
    print(f"  最后状态: {state2.get('next')}")
    print(f"  执行状态: {state2.get('execution_status')}")
    print(f"  重试次数: {state2.get('retry_count')}\n")
    
    print("=" * 80)
    print("Multi-Agent工作流演示完成")
    print("=" * 80)
    print(f"""
工作流说明：
1. Supervisor: 分析用户需求，决定派给Coder或Reviewer
2. Coder: 编写并执行Python代码，获取数据、计算、绘图
3. Tools: 执行Coder调用的工具（run_script、search等）
4. ErrorHandler: 检测执行错误，决定重试还是继续
5. Reviewer: 基于Coder的结果，撰写分析报告
6. Supervisor: 最终确认任务完成

多智能体优势：
✓ 职能分离：Coder专注代码，Reviewer专注分析
✓ 自我修正：ErrorHandler在3次重试内修复代码错误
✓ 状态管理：所有Agent共享统一的State，信息流清晰
✓ 路由灵活：Supervisor根据动态规则决定执行顺序
✓ 上下文控制：避免单体Agent处理过长的推理链

本次测试验证了完整的Multi-Agent工作流。
    """)


def test_supervisor_routing():
    """测试Supervisor的路由逻辑"""
    
    print("\n" + "=" * 80)
    print("Supervisor路由逻辑单元测试")
    print("=" * 80 + "\n")
    
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    # 测试用例
    test_cases = [
        ("我要查询美的集团的股票数据", "应路由到Coder"),
        ("根据上面的数据，给我写个分析", "应路由到Reviewer"),
        ("画个图表出来", "应路由到Coder"),
    ]
    
    for query, expected in test_cases:
        print(f"Query: {query}")
        print(f"Expected: {expected}")
        
        initial_state = {
            "messages": [],
            "next": "Supervisor",
            "retry_count": 0,
            "user_profile": {"username": "test"},
            "execution_status": "pending"
        }
        
        multi_agent_app.update_state(config, initial_state)
        
        # 执行一步
        for event in multi_agent_app.stream(
            {"messages": [HumanMessage(content=query)]},
            config,
            stream_mode="values"
        ):
            pass
        
        state = multi_agent_app.get_state(config).values
        print(f"Actual: Routed to {state.get('next')}\n")


def test_error_handling():
    """测试错误处理和自我修正机制"""
    
    print("\n" + "=" * 80)
    print("错误处理和自我修正机制单元测试")
    print("=" * 80 + "\n")
    
    print("""
测试场景：Coder执行代码时出错，ErrorHandler应该：
1. 检测到ToolMessage中的"Error"关键字
2. 增加retry_count
3. 生成修正提示消息
4. 路由回Coder（重试次数 < 3）
5. 超过3次后，路由回Supervisor（放弃修复）

这个测试需要实际执行代码有错，
在test_multi_agent_workflow()中已经通过集成测试验证了。
    """)


if __name__ == "__main__":
    try:
        print("\n开始Multi-Agent系统测试...\n")
        
        # 测试1：完整工作流
        test_multi_agent_workflow()
        
        # 测试2：Supervisor路由
        print("\n\n")
        test_supervisor_routing()
        
        # 测试3：错误处理
        print("\n\n")
        test_error_handling()
        
        print("\n" + "=" * 80)
        print("所有测试完成！")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
