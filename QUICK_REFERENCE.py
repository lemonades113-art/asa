#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Multi-Agent & Agent Quick Reference
快速参考指南
"""

def show_quick_reference():
    print("""
╔════════════════════════════════════════════════════════════════════════════════╗
║                         Quick Reference Guide                                  ║
║                           快速参考指南                                          ║
╚════════════════════════════════════════════════════════════════════════════════╝

【系统架构对比】

┌─────────────────────────────────────────────────────────────────────────────┐
│                         单体Agent vs Multi-Agent                            │
├─────────────┬──────────────────────┬────────────────────────────────────────┤
│ 特性        │ 单体Agent (v1)       │ Multi-Agent (v2) 新增                  │
├─────────────┼──────────────────────┼────────────────────────────────────────┤
│ 模式        │ 单一Agent处理所有    │ Supervisor + Coder + Reviewer          │
│ 职能        │ 混合（代码+分析）   │ 分离（Coder专代码，Reviewer专分析）   │
│ 错误修复    │ 无                   │ 自动修复（3次重试）                    │
│ 工作流      │ 固定流程             │ 动态路由                                │
│ 复杂任务    │ 困难                 │ 优势                                    │
│ 延迟        │ 5-10秒               │ 15-30秒                                 │
│ Token成本   │ 1000-3000            │ 2000-6000                               │
│ 代码质量    │ 中                   │ 高（自动修复）                         │
│ 报告质量    │ 中                   │ 高（专业分析）                         │
└─────────────┴──────────────────────┴────────────────────────────────────────┘


【使用场景速查】

简单查询 → 用单体Agent
  例: "平安银行现在股价多少?"
  文件: agent.py
  优点: 快速、低成本
  
  from agent import app
  from langchain_core.messages import HumanMessage
  import uuid
  
  thread_id = str(uuid.uuid4())
  config = {"configurable": {"thread_id": thread_id}}
  
  for event in app.stream(
      {"messages": [HumanMessage(content="平安银行现在股价多少?")]},
      config
  ):
      pass


复杂分析 → 用Multi-Agent  
  例: "查询平安银行最近30天数据，画图，分析走势，给建议"
  文件: multi_agent.py
  优点: 自动修复、高质量
  
  from multi_agent import multi_agent_app
  from langchain_core.messages import HumanMessage
  import uuid
  
  thread_id = str(uuid.uuid4())
  config = {"configurable": {"thread_id": thread_id}}
  
  multi_agent_app.update_state(config, {
      "messages": [],
      "next": "Supervisor",
      "retry_count": 0,
      "user_profile": {"username": "用户"},
      "execution_status": "pending"
  })
  
  for event in multi_agent_app.stream(
      {"messages": [HumanMessage(content="查询...")]},
      config
  ):
      pass


【核心API速查】

单体Agent (agent.py):
  
  导入：
    from agent import app
  
  初始化：
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    app.update_state(config, {"messages": [], "user_profile": {...}})
  
  执行：
    for event in app.stream(
        {"messages": [HumanMessage(content="")]},
        config
    ):
        pass
  
  获取结果：
    state = app.get_state(config).values
    print(state["messages"][-1])


Multi-Agent (multi_agent.py):
  
  导入：
    from multi_agent import multi_agent_app
  
  初始化：
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    multi_agent_app.update_state(config, {
        "messages": [],
        "next": "Supervisor",
        "retry_count": 0,
        "user_profile": {...},
        "execution_status": "pending"
    })
  
  执行：
    for event in multi_agent_app.stream(
        {"messages": [HumanMessage(content="")]},
        config
    ):
        print(event.get("next"))  # 查看当前执行者
  
  获取结果：
    state = multi_agent_app.get_state(config).values
    final_msg = state["messages"][-1]
    print(f"执行者: {state['next']}")
    print(f"重试: {state['retry_count']}")
    print(f"状态: {state['execution_status']}")


【文件导航】

项目结构：
  
  核心：
    agent.py          - 单体Agent（v1）
    multi_agent.py    - Multi-Agent（v2）
    lib.py            - 通用工具库
  
  测试：
    test_quick_check.py          - 单体Agent快速验证
    test_multi_agent_quick.py    - Multi-Agent快速验证
    test_langgraph_flow.py       - 单体Agent完整测试
    test_multi_agent.py          - Multi-Agent完整测试
  
  文档/指南：
    MULTI_AGENT_GUIDE.py    - Multi-Agent详细指南
    MULTI_AGENT_SUMMARY.py  - Multi-Agent项目总结
    get_started.py          - 交互式菜单
    QUICK_REFERENCE.py      - 本文件


【关键概念】

Supervisor (主管)：
  - 中心决策节点
  - 分析State，决定next (Coder/Reviewer/FINISH)
  - 使用RouteResponse结构化输出

Coder (编码员)：
  - 生成Python代码
  - 调用Tushare API
  - 输出: tool_calls

Reviewer (分析师)：
  - 解读代码执行结果
  - 撰写金融分析报告
  - 不调用工具

ErrorHandler (错误处理)：
  - 检测Error关键字
  - 生成修正提示
  - 管理retry_count (最多3次)

MultiAgentState：
  {
    "messages": [BaseMessage, ...],  # 消息历史
    "next": "Coder" | "Reviewer" | "FINISH",
    "retry_count": 0-3,
    "user_profile": {...},
    "execution_status": "pending" | "success" | "error"
  }


【性能优化】

降低成本：
  • 使用gpt-4o-mini替代gpt-4o
  • 启用message trimming
  • 减少重试次数
  • 缓存常见查询

提高速度：
  • 使用单体Agent处理简单任务
  • 减少System Prompt长度
  • 使用流式响应
  • 并行执行独立任务

提高质量：
  • 使用Multi-Agent处理复杂任务
  • 优化System Prompts
  • 增加重试次数（需平衡成本）
  • 使用更强的模型


【故障排除】

问题：无响应或超时
  解决：
    • 检查API密钥
    • 检查网络连接
    • 设置timeout参数
    • 使用较小的模型

问题：错误修复无效
  解决：
    • 增加retry_count上限
    • 优化ErrorHandler提示
    • 检查错误检测逻辑
    • 增加调试信息

问题：响应质量不满意
  解决：
    • 优化System Prompt
    • 使用更强的模型
    • 使用Multi-Agent (高质量)
    • 添加上下文信息

问题：成本过高
  解决：
    • 使用单体Agent (低成本)
    • 减少重试次数
    • 启用缓存
    • 使用mini模型


【常见命令】

# 快速验证
python test_quick_check.py                  # 单体Agent验证
python test_multi_agent_quick.py            # Multi-Agent验证

# 完整测试
python test_langgraph_flow.py               # 单体Agent测试
python test_multi_agent.py                  # Multi-Agent测试

# 查看文档
python MULTI_AGENT_GUIDE.py                 # Multi-Agent指南
python MULTI_AGENT_SUMMARY.py               # 项目总结
python get_started.py                       # 交互式菜单

# 启动Web界面
python agent_gradio.py                      # 基于agent.py
# (需要为multi_agent_app创建Gradio版本)


【决策树】

用户查询来了
  │
  ├─ 简单查询? (是否只需要单一答案)
  │   ├─ YES → 用agent.py (5-10秒，1000-3000 tokens)
  │   └─ NO  ↓
  │
  ├─ 需要代码执行? (是否需要数据处理/绘图)
  │   ├─ NO  → 用agent.py或回答问题
  │   └─ YES ↓
  │
  ├─ 代码出错频繁? (是否需要自动修复)
  │   ├─ NO  → 用agent.py
  │   └─ YES ↓
  │
  ├─ 结果质量重要? (是否重视分析质量)
  │   ├─ NO  → 用agent.py (成本优先)
  │   └─ YES ↓
  │
  └─ 用multi_agent.py (15-30秒，2000-6000 tokens，高质量)


【下一步】

新手：
  1. python test_quick_check.py          # 验证环境
  2. python MULTI_AGENT_GUIDE.py         # 学习概念
  3. python get_started.py               # 交互式学习

开发者：
  1. 查看agent.py和multi_agent.py源码
  2. 运行test_langgraph_flow.py和test_multi_agent.py
  3. 在自己的项目中集成使用

部署者：
  1. 在agent_gradio.py中支持Multi-Agent
  2. 添加模型选择器（自动选择v1或v2）
  3. 监控成本和质量指标


【参考资源】

项目文件：
  • multi_agent.py (407行) - 核心实现
  • agent.py (252行) - 单体版本参考
  
测试文件：
  • test_multi_agent_quick.py - 快速验证
  • test_multi_agent.py - 完整工作流测试
  
文档文件：
  • MULTI_AGENT_GUIDE.py - 详细指南
  • MULTI_AGENT_SUMMARY.py - 项目总结

关键类和函数：
  • MultiAgentState - 状态定义
  • supervisor_node - 路由逻辑 (L154-195)
  • coder_node - 代码执行 (L198-207)
  • reviewer_node - 报告撰写 (L210-220)
  • error_handler_node - 错误处理 (L238-278)
  • multi_agent_app - 编译的应用


【版本差异速览】

Agent v1.0 (agent.py):
  ✓ 单体设计，职能混合
  ✓ 意图识别 + 用户画像 + 动态提示
  ✓ 响应快速，成本低
  ✗ 无自动错误修复
  ✗ 复杂任务处理困难

Agent v2.0 (multi_agent.py):
  ✓ 多智能体，职能分离
  ✓ Supervisor路由，Coder编码，Reviewer分析
  ✓ 自动错误修复（3次重试）
  ✓ 复杂工作流处理
  ✗ 响应较慢
  ✗ 成本较高

推荐：根据具体需求选择合适版本，或使用混合方案。

    """)

if __name__ == "__main__":
    show_quick_reference()
