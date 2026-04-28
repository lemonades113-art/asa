#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Multi-Agent Architecture Guide
多智能体架构使用指南
"""

def show_guide():
    """显示Multi-Agent系统使用指南"""
    print("""
╔════════════════════════════════════════════════════════════════════════════════╗
║                      Multi-Agent System Guide                                  ║
║                 基于LangGraph Supervisor模式的多智能体架构                     ║
╚════════════════════════════════════════════════════════════════════════════════╝

【架构核心】

Supervisor (主管) - 决定谁执行
    |
    +-- Coder (编码员) - 执行代码、获取数据
    |
    +-- Reviewer (分析师) - 撰写报告、分析数据
    |
    +-- ErrorHandler (错误处理) - 自动修复错误


【关键特性】

1. Supervisor Pattern (主管模式)
   - 中心化决策：由Supervisor根据State决定下一个执行者
   - 避免Agent之间无序对话导致的死循环
   - 状态管理清晰：所有Agent共享MultiAgentState

2. Self-Correction (自我修正)
   - ErrorHandler检测执行错误
   - 自动生成修正提示并回跳Coder
   - 最多3次重试，防止无限循环

3. Role Specialization (角色分离)
   - Coder: 专注代码执行，不处理文本分析
   - Reviewer: 专注数据解读，不编写代码
   - 避免混合两个任务导致的上下文混乱


【MultiAgentState结构】

{
    "messages": [BaseMessage, ...],        # 消息历史
    "next": "Coder" | "Reviewer" | "FINISH",  # 下一个执行者
    "retry_count": 0,                      # 重试次数 (0-3)
    "user_profile": {...},                 # 用户画像
    "execution_status": "pending" | "success" | "error"
}


【工作流示例1：数据获取+绘图】

User: "帮我查平安银行最近30天收盘价，画个图"

Step 1: Supervisor
        Input: [HumanMessage("帮我查...")]
        Logic: 检测到"查"和"图" -> 需要Coder
        Output: next="Coder"
        
Step 2: Coder
        Output: AIMessage(tool_calls=[{"name": "run_script", ...}])
        
Step 3: Tools (自动执行)
        Execute: run_script("pro.daily(...)")
        Result: ToolMessage("DataFrame: \n...")
        
Step 4: ErrorHandler
        Input: ToolMessage("DataFrame...")
        Logic: 无Error -> success
        Output: next="Supervisor"
        
Step 5: Supervisor
        Input: [HumanMessage, AIMessage, ToolMessage(结果)]
        Logic: 已有数据+绘图结果 -> 需要Reviewer分析
        Output: next="Reviewer"
        
Step 6: Reviewer
        Output: AIMessage("平安银行股价走势分析...\n建议...")
        
Step 7: Supervisor
        Input: [HumanMessage, ..., AIMessage(报告)]
        Logic: 报告完成
        Output: next="FINISH"


【工作流示例2：代码执行失败+自我修正】

Step 1-3: (同上，但代码有bug)
        
Step 4: ErrorHandler
        Input: ToolMessage("Error: NameError: name 'pro' is not defined")
        Logic: 检测到"Error" -> retry_count=0 < 3
        Output: next="Coder", retry_count=1, 新增修正提示
        
Step 5: Coder (重试)
        Input: [HumanMessage, AIMessage(bug), ToolMessage(Error), HumanMessage(修正提示)]
        Logic: 分析错误，发现"pro未定义"
        Output: AIMessage(tool_calls=[{"name": "run_script", "args": "pro = ts.pro_api()..."}])
        
Step 6-7: Tools + ErrorHandler
        Execute: 新代码
        Result: ToolMessage("执行成功: DataFrame...")
        Logic: 无Error -> success
        Output: next="Supervisor"
        
Step 8+: (继续到Reviewer和FINISH)


【何时使用单体vs多智能体】

Use agent.py (单体Agent):
  + 简单查询
  + 低延迟
  + 低API成本
  - 处理复杂工作流困难
  - 没有自动错误修复

Use multi_agent.py (多智能体):
  + 复杂工作流（数据+处理+分析）
  + 自动错误修复
  + 结果质量更高
  + 职能分离更清晰
  - 响应延迟较长
  - API成本较高


【使用Multi-Agent】

# 1. 导入
from multi_agent import multi_agent_app
from langchain_core.messages import HumanMessage
import uuid

# 2. 初始化会话
thread_id = str(uuid.uuid4())
config = {"configurable": {"thread_id": thread_id}}

# 3. 准备初始状态
initial_state = {
    "messages": [],
    "next": "Supervisor",
    "retry_count": 0,
    "user_profile": {"username": "张三", ...},
    "execution_status": "pending"
}
multi_agent_app.update_state(config, initial_state)

# 4. 发送用户查询
user_query = "帮我分析平安银行的股价走势"

for event in multi_agent_app.stream(
    {"messages": [HumanMessage(content=user_query)]},
    config,
    stream_mode="values"
):
    if "next" in event:
        print(f"Next agent: {event['next']}")

# 5. 获取最终结果
final_state = multi_agent_app.get_state(config).values
print(final_state["messages"][-1].content)  # 最后的输出


【性能对比】

指标          | 单体Agent      | 多智能体
-------------|----------------|------------------
Token消耗     | ~1000-3000     | ~2000-6000
API调用次数    | 1-2次          | 3-5次
平均延迟      | 5-10秒         | 15-30秒
错误自动修复   | 否             | 是 (3次重试)
报告质量      | 中等           | 较高
适合任务      | 简单查询       | 复杂工作流


【故障排除】

问题：Supervisor总是路由到FINISH
解决：检查Supervisor的System Prompt逻辑，确保能正确识别任务需求

问题：Coder生成的代码反复出错
解决：修改Coder的System Prompt，增加调试建议

问题：Token消耗过高
解决：
  - 使用message trimming减少历史消耗
  - 使用较小的模型 (gpt-4o-mini 而非 gpt-4)
  - 限制重试次数

问题：Reviewer的报告太简洁
解决：修改Reviewer的System Prompt，要求更详细的分析


【扩展】

Add more worker nodes:
  - DataFetcher: 专门处理数据获取
  - Validator: 验证数据质量
  - Visualizer: 专门绘图

Improve Supervisor:
  - 使用tool_calls让Supervisor"思考"
  - 学习用户历史决策
  - 动态调整路由权重

Advanced error handling:
  - 按错误类型路由到不同处理器
  - 记录错误模式，下次自动预防
  - 集成外部错误诊断工具


【调试方法】

# 启用详细日志
import logging
logging.basicConfig(level=logging.DEBUG)

# 逐步执行，检查每一步的状态
for event in multi_agent_app.stream(...):
    print("Current state:")
    print(f"  Next: {event.get('next')}")
    print(f"  Retry: {event.get('retry_count')}")
    print(f"  Status: {event.get('execution_status')}")
    print()

# 检查消息历史
state = multi_agent_app.get_state(config).values
for i, msg in enumerate(state["messages"]):
    print(f"Message {i}: {type(msg).__name__}")
    if hasattr(msg, 'content'):
        print(f"  Content: {msg.content[:100]}...")


【关键代码位置】

多智能体核心逻辑：
  - multi_agent.py: 主要实现文件

节点定义：
  - supervisor_node: Supervisor路由逻辑
  - coder_node: Coder代码执行
  - reviewer_node: Reviewer报告撰写
  - error_handler_node: 错误检测和修正

路由函数：
  - route_supervisor: Supervisor的条件边
  - route_coder: Coder的条件边
  - execute_tools: 工具执行


【下一步】

1. 运行测试：python test_multi_agent.py
2. 查看架构：python MULTI_AGENT_GUIDE.py
3. 集成到应用：在agent_gradio.py中替换单体Agent为Multi-Agent
4. 监控效果：对比单体vs多智能体的结果质量
5. 优化成本：根据实际使用调整模型和参数

    """)


if __name__ == "__main__":
    show_guide()
