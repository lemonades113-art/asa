#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
快速开始指南 - 使用LangGraph增强架构

项目已完成以下升级：
✓ 意图路由系统 (Intent Router)
✓ 用户画像持久化 (User Profile)
✓ 动态系统提示生成 (Dynamic System Prompt)
✓ 有状态执行内核 (Stateful Python Kernel)
✓ 多用户隔离 (Multi-user Isolation)
"""

def show_menu():
    """显示菜单"""
    print("\n" + "=" * 80)
    print("LangGraph 增强架构 - 快速开始")
    print("=" * 80)
    print("""
【选项】

1. 运行快速验证 (test_quick_check.py)
   - 验证所有核心模块是否正常
   - 检查意图识别、画像管理、系统提示等

2. 运行完整演示 (demo_complete_workflow.py)
   - 演示意图路由的完整流程
   - 展示用户画像如何自动更新
   * 需要有效的API密钥

3. 运行测试流程 (test_langgraph_flow.py)
   - 测试单用户多轮对话
   - 测试多用户隔离
   - 演示完整的LangGraph工作流
   * 需要有效的API密钥

4. 启动Web界面 (agent_gradio.py)
   - 基于Gradio的Web交互界面
   - 支持多用户会话管理
   - 实时显示用户画像
   * 需要有效的API密钥

5. 查看项目结构

6. 查看使用说明

0. 退出
    """)

def show_project_structure():
    """显示项目结构"""
    print("\n" + "=" * 80)
    print("项目结构")
    print("=" * 80)
    print("""
核心文件：
  - lib.py
    * 意图定义 (IntentSchema)
    * Prompt模板 (INTENT_PROMPT, PROFILE_UPDATE_PROMPT)
    * 动态系统提示函数 (get_system_prompt)
    * 有状态执行内核 (StatefulPythonKernel)
    * 混合检索器 (HybridRetriever)

  - agent.py
    * LangGraph状态定义 (AgentState)
    * 四个关键节点 (router, agent, tools, profile_updater)
    * 图的构建和编译 (StateGraph)
    * 编译后的应用 (app)

  - agent_gradio.py
    * Gradio Web界面 (ChatInterface)
    * 会话管理
    * 用户画像显示

测试和演示文件：
  - test_quick_check.py: 快速验证脚本（不需要API密钥）
  - test_langgraph_flow.py: 完整流程测试（需要API密钥）
  - demo_complete_workflow.py: 工作流演示（需要API密钥）
  - test_simple.py: 简单测试
  - test_upgrade.py: 升级测试

配置文件：
  - conf.py: API密钥和基础配置
  - pyproject.toml: 项目配置
    """)

def show_usage_guide():
    """显示使用指南"""
    print("\n" + "=" * 80)
    print("使用指南")
    print("=" * 80)
    print("""
【基础用法】

1. 导入app并初始化会话：
```python
import uuid
from agent import app
from langchain_core.messages import HumanMessage

thread_id = str(uuid.uuid4())
config = {"configurable": {"thread_id": thread_id}}

# 初始化用户画像
initial_profile = {
    "username": "张三",
    "risk_preference": "稳健型",
    "interested_industries": ["新能源"],
    "investment_style": "基本面",
    "notes": ""
}

app.update_state(config, {
    "messages": [],
    "user_profile": initial_profile,
    "intent": "general_chat"
})
```

2. 执行查询：
```python
# 流式执行
for event in app.stream(
    {"messages": [HumanMessage(content="帮我分析贵州茅台")]},
    config,
    stream_mode="values"
):
    # 处理事件
    pass

# 获取最终状态
final_state = app.get_state(config).values
intent = final_state['intent']
profile = final_state['user_profile']
```

【意图类型】
- fetch_data: 获取数据（股价、财报等）
- analysis: 数据分析（计算指标、寻找原因等）
- charting: 画图（展示图表）
- general_chat: 通用对话

【LangGraph工作流】
Router (意图识别) 
  ↓
Agent (主逻辑执行)
  ↓
Tools (调用工具)
  ↓
ProfileUpdater (自动更新画像)
  ↓
END

【状态持久化】
每个thread_id对应一个独立的用户会话，包含：
- messages: 对话历史
- user_profile: 用户画像（自动更新）
- intent: 当前意图

用户画像会在每次对话后自动分析和更新。
    """)

if __name__ == "__main__":
    import subprocess
    import sys
    
    while True:
        show_menu()
        choice = input("\n请选择 (0-6): ").strip()
        
        if choice == "1":
            print("\n执行: python test_quick_check.py")
            subprocess.run([sys.executable, "test_quick_check.py"])
        elif choice == "2":
            print("\n执行: python demo_complete_workflow.py")
            subprocess.run([sys.executable, "demo_complete_workflow.py"])
        elif choice == "3":
            print("\n执行: python test_langgraph_flow.py")
            subprocess.run([sys.executable, "test_langgraph_flow.py"])
        elif choice == "4":
            print("\n执行: python agent_gradio.py")
            subprocess.run([sys.executable, "agent_gradio.py"])
        elif choice == "5":
            show_project_structure()
        elif choice == "6":
            show_usage_guide()
        elif choice == "0":
            print("\n再见！")
            break
        else:
            print("\n无效选择，请重试")
