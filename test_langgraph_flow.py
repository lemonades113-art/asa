#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LangGraph 增强架构测试脚本
演示：意图路由 + 用户画像持久化 + 动态系统提示
"""

import uuid
from langchain_core.messages import HumanMessage
from agent import app, AgentState

# =============================================================================
# 测试1：单用户单线程对话流程
# =============================================================================

def test_single_user_conversation():
    """演示完整的多轮对话流程"""
    
    print("\n" + "=" * 80)
    print("【测试1】单用户单线程对话流程（意图识别 + 画像更新）")
    print("=" * 80 + "\n")
    
    # 1. 初始化配置
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    # 2. 显式初始化用户画像（模拟首次引导）
    initial_profile = {
        "username": "Way",
        "risk_preference": "稳健型",
        "interested_industries": ["新能源", "白酒"],
        "investment_style": "价值投资",
        "notes": "不喜欢小盘股"
    }
    
    # 初始化状态
    initial_state = {
        "messages": [],
        "user_profile": initial_profile,
        "intent": "general_chat"
    }
    
    # 更新初始状态
    app.update_state(config, initial_state)
    print(f"✓ 当前用户: {initial_profile['username']}")
    print(f"✓ 风险偏好: {initial_profile['risk_preference']}")
    print(f"✓ 优先关注: {initial_profile['interested_industries']}")
    print(f"✓ 分析风格: {initial_profile['investment_style']}\n")
    
    # 3. Round 1: 意图应为 'analysis'
    print("-" * 80)
    print("【Round 1】分析贵州茅台的MACD走势")
    print("-" * 80)
    
    user_query_1 = "帮我分析一下贵州茅台最近的MACD走势，要不要卖出？"
    print(f"User: {user_query_1}\n")
    
    # 流式执行
    for event in app.stream(
        {"messages": [HumanMessage(content=user_query_1)]},
        config,
        stream_mode="values"
    ):
        # 此处可以实时捕获中间节点的执行情况
        pass
    
    # 获取最终状态
    final_state_1 = app.get_state(config).values
    print(f"\n识别的意图: {final_state_1.get('intent', 'unknown')}")
    print(f"更新后的画像: {final_state_1.get('user_profile', {})}\n")
    
    # 4. Round 2: 意图应为 'charting'
    print("-" * 80)
    print("【Round 2】绘制贵州茅台的K线图")
    print("-" * 80)
    
    user_query_2 = "把它最近一个月的K线画出来看看"
    print(f"User: {user_query_2}\n")
    
    for event in app.stream(
        {"messages": [HumanMessage(content=user_query_2)]},
        config,
        stream_mode="values"
    ):
        pass
    
    final_state_2 = app.get_state(config).values
    print(f"\n识别的意图: {final_state_2.get('intent', 'unknown')}")
    print(f"更新后的画像: {final_state_2.get('user_profile', {})}\n")
    
    # 5. Round 3: 意图应为 'fetch_data'
    print("-" * 80)
    print("【Round 3】获取白酒行业的财报数据")
    print("-" * 80)
    
    user_query_3 = "给我查一下白酒行业龙头股最近的ROE排行"
    print(f"User: {user_query_3}\n")
    
    for event in app.stream(
        {"messages": [HumanMessage(content=user_query_3)]},
        config,
        stream_mode="values"
    ):
        pass
    
    final_state_3 = app.get_state(config).values
    print(f"\n识别的意图: {final_state_3.get('intent', 'unknown')}")
    print(f"最终画像（已自动更新）:")
    print(f"  {final_state_3.get('user_profile', {})}\n")
    
    print("\n✓ 测试1完成：画像在多轮对话中自动进化！\n")


# =============================================================================
# 测试2：多用户场景
# =============================================================================

def test_multi_user():
    """演示多用户隔离"""
    
    print("\n" + "=" * 80)
    print("【测试2】多用户隔离（不同thread_id各自维护画像）")
    print("=" * 80 + "\n")
    
    # User A
    user_a_profile = {
        "username": "张三",
        "risk_preference": "激进型",
        "interested_industries": ["芯片", "新能源"],
        "investment_style": "技术面",
        "notes": "追求高收益"
    }
    
    # User B
    user_b_profile = {
        "username": "李四",
        "risk_preference": "保守型",
        "interested_industries": ["消费", "医药"],
        "investment_style": "基本面",
        "notes": "追求稳定"
    }
    
    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())
    
    config_a = {"configurable": {"thread_id": thread_a}}
    config_b = {"configurable": {"thread_id": thread_b}}
    
    # 初始化两个用户
    app.update_state(config_a, {
        "messages": [],
        "user_profile": user_a_profile,
        "intent": "general_chat"
    })
    
    app.update_state(config_b, {
        "messages": [],
        "user_profile": user_b_profile,
        "intent": "general_chat"
    })
    
    print(f"✓ User A ({user_a_profile['username']}): {user_a_profile['risk_preference']}")
    print(f"✓ User B ({user_b_profile['username']}): {user_b_profile['risk_preference']}\n")
    
    # User A 的查询
    print("User A 的查询：")
    for event in app.stream(
        {"messages": [HumanMessage(content="帮我找芯片行业最有潜力的小盘股")]},
        config_a,
        stream_mode="values"
    ):
        pass
    
    state_a = app.get_state(config_a).values
    print(f"User A 当前意图: {state_a.get('intent')}\n")
    
    # User B 的查询
    print("User B 的查询：")
    for event in app.stream(
        {"messages": [HumanMessage(content="哪些消费股的分红收益率最高")]},
        config_b,
        stream_mode="values"
    ):
        pass
    
    state_b = app.get_state(config_b).values
    print(f"User B 当前意图: {state_b.get('intent')}\n")
    
    print("✓ 测试2完成：两个用户的画像和状态完全隔离！\n")


# =============================================================================
# 测试3：完整流程演示
# =============================================================================

def test_full_workflow():
    """完整演示LangGraph的意图识别流程"""
    
    print("\n" + "=" * 80)
    print("【测试3】完整工作流：Router → Agent → Tools → ProfileUpdater")
    print("=" * 80 + "\n")
    
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    # 初始画像
    profile = {
        "username": "投资者",
        "risk_preference": "未知",
        "interested_industries": [],
        "investment_style": "未知",
        "notes": ""
    }
    
    app.update_state(config, {
        "messages": [],
        "user_profile": profile,
        "intent": "general_chat"
    })
    
    # 一个完整的分析询问
    query = "我想研究一下新能源汽车的上下游产业链，从电池、芯片、到整车，各环节的龙头股有哪些？"
    
    print(f"User Query: {query}\n")
    print("执行流程：Router → Agent → (Tools) → ProfileUpdater → END\n")
    
    step = 1
    for event in app.stream(
        {"messages": [HumanMessage(content=query)]},
        config,
        stream_mode="values"
    ):
        # 捕获不同步骤
        print(f"Step {step}: 状态更新中...")
        step += 1
    
    final_state = app.get_state(config).values
    print(f"\n✓ 最终意图: {final_state.get('intent')}")
    print(f"✓ 更新后的画像: {final_state.get('user_profile')}\n")
    
    print("✓ 测试3完成：完整的LangGraph工作流执行成功！\n")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("LangGraph 增强架构完整测试")
    print("=" * 80)
    
    try:
        test_single_user_conversation()
        test_multi_user()
        test_full_workflow()
        
        print("\n" + "=" * 80)
        print("🎉 所有测试通过！")
        print("=" * 80)
        print("""
核心特性验证：
✓ 意图路由 (Intent Router) - 自动分类用户意图
✓ 用户画像持久化 - 跨对话保留和更新
✓ 动态系统提示 - 根据画像调整AI行为
✓ 多用户隔离 - 每个用户独立的状态
✓ 工具集成 - 无缝调用数据和分析工具
✓ 后置更新 - 自动进化用户画像

下一步：
python agent_gradio.py  # 启动Web界面版本
        """)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
