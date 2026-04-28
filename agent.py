import json
import os
import uuid
import datetime
import traceback
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage

from lib import (
    get_chat_model, search, run_python_script, GradioInterface, global_kernel,
    INTENT_PROMPT, PROFILE_UPDATE_PROMPT, get_system_prompt, IntentSchema
)

# =============================================================================
# 第一步: 定义增强版状态
# =============================================================================

class AgentState(TypedDict):
    """增强的Agent状态，包含消息、用户画像和意图"""
    messages: Annotated[list[BaseMessage], "add_messages"]  # 消息历史
    user_profile: dict  # 用户画像（持久化存储）
    intent: str         # 当前意图（临时状态）
    # 🔒 P0-E: 工具调用深度限制
    tool_call_count: int  # 工具调用计数器（防止无限循环）


# =============================================================================
# 第二步: 初始化模型和工具
# =============================================================================

model = get_chat_model()

@tool
def search_tushare_docs_local(query: str, top: int = 5) -> str:
    """混合搜索tushare文档"""
    return search(query, top)


@tool
def run_script(content: str):
    """执行Python脚本（有状态执行环境）"""
    result_data = run_python_script(content)

    try:
        while True:
            line = next(result_data)
            print(line, end='')
    except StopIteration as e:
        print(e.value)
        return e.value
    except Exception:
        stack_trace = traceback.format_exc()
        return f'代码运行出错:\n{stack_trace}'


@tool
def get_current_datetime():
    """获取当前时间"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool
def reset_execution_environment():
    """重置执行环境"""
    global_kernel.reset()
    return "执行环境已重置。"


tools = [search_tushare_docs_local, run_script, get_current_datetime, reset_execution_environment]
model_with_tools = model.bind_tools(tools)

# =============================================================================
# 第三步: 定义图节点
# =============================================================================

def intent_router_node(state: AgentState):
    """分析用户最新的一条消息，确定意图"""
    messages = state['messages']
    last_user_msg = messages[-1].content if isinstance(messages[-1], HumanMessage) else messages[-2].content
    
    # 🔒 P0-E: 重置工具调用计新开始
    # 使用 get_last_user_message 辅动函数获取用户消息
    from lib import get_last_user_message
    last_user = get_last_user_message(state)
    if last_user:
        last_user_msg = last_user.content
    
    # 使用简单的提示和解析来确定意图（更兼容的方式）
    prompt_text = INTENT_PROMPT.format(query=last_user_msg)
    prompt_with_instruction = prompt_text + "\n\n请回复一个json对象，格式为: {\"intent\": \"fetch_data\" | \"analysis\" | \"charting\" | \"general_chat\"}"
    
    try:
        response = model.invoke(prompt_with_instruction)
        
        # 尝试解析JSON
        import json as json_lib
        response_text = response.content
        # 提取JSON
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start >= 0 and json_end > json_start:
            json_str = response_text[json_start:json_end]
            parsed = json_lib.loads(json_str)
            intent = parsed.get('intent', 'general_chat')
        else:
            # 降级：简单的关键字匹配
            if '画' in response_text or '图' in response_text:
                intent = 'charting'
            elif '分析' in response_text or '计算' in response_text:
                intent = 'analysis'
            elif '查' in response_text or '获取' in response_text or '数据' in response_text:
                intent = 'fetch_data'
            else:
                intent = 'general_chat'
    except Exception as e:
        print(f"[Router] 意图识别异常，使用默认值: {e}")
        intent = 'general_chat'
    
    print(f"[Router] 识别意图: {intent}")
    return {
        "intent": intent,
        "tool_call_count": 0  # 🔒 P0-E: 抽象于新对豱开始
    }


def agent_node(state: AgentState):
    """根据意图和画像执行主逻辑"""
    # 🔒 P0-D: 三壹一: 添加异常捕获
    try:
        intent = state.get('intent', 'general_chat')
        profile = state.get('user_profile', {})
        
        # 动态生成 System Prompt
        sys_prompt = get_system_prompt(intent, profile)
        
        # 构建消息列表：System + History
        messages = [SystemMessage(content=sys_prompt)] + state['messages']
        
        # ✨ 新增：清理孤立的 ToolMessage（防止消息链破裂）
        # 问题：ToolMessage 必须对应前一条消息的 tool_calls
        # 解决：如果 ToolMessage 前面不是 AIMessage with tool_calls，则删除它
        cleaned_messages = []
        for i, msg in enumerate(messages):
            if msg.type == "tool":
                # 检查前一条消息是否有 tool_calls
                if i > 0 and hasattr(messages[i-1], 'tool_calls') and messages[i-1].tool_calls:
                    cleaned_messages.append(msg)  # 有对应的 tool_calls，保留
                # 否则跳过这个孤立的 ToolMessage（无对应的 tool_calls）
            else:
                cleaned_messages.append(msg)
        
        # 使用清理后的消息
        response = model_with_tools.invoke(cleaned_messages)
        
        print(f"[Agent] 执行成功")
        return {
            "messages": [response],
            "tool_call_count": state.get('tool_call_count', 0)  # 🔒 维持计数（減1先不於）
        }
    except Exception as e:
        error_msg = f"[Agent] 执行失败: {str(e)[:100]}"
        print(f"{error_msg}\n详细信息:\n{traceback.format_exc()}")
        
        return {
            "messages": [HumanMessage(content=error_msg)],
            "tool_call_count": state.get('tool_call_count', 0)  # 🔒 维持计数
        }


def profile_updater_node(state: AgentState):
    """在对话结束后，分析并更新画像"""
    # 🔒 P0-D: 希蘿一: 为画像更新添加异常捕获
    try:
        recent_msgs = state['messages'][-4:]
        summary = "\n".join([f"{m.type}: {m.content}" for m in recent_msgs])
        current_profile = json.dumps(state.get('user_profile', {}), ensure_ascii=False)
        
        prompt = PROFILE_UPDATE_PROMPT.format(
            current_profile=current_profile,
            conversation_summary=summary
        )
        
        response = model.invoke(prompt)
        
        try:
            # 解析 JSON
            new_profile_data = response.content.replace("```json", "").replace("```", "").strip()
            new_profile = json.loads(new_profile_data)
            print(f"[Profile] 画像已更新: {new_profile}")
            return {
                "user_profile": new_profile,
                "tool_call_count": state.get('tool_call_count', 0)  # 🔒 维持计数
            }
        except Exception as e:
            print(f"[Profile] JSON解析失败: {e}")
            return {
                "user_profile": state.get('user_profile', {}),
                "tool_call_count": state.get('tool_call_count', 0)
            }
    except Exception as e:
        error_msg = f"[Profile] 更新失败: {str(e)[:100]}"
        print(f"{error_msg}\n详细信息:\n{traceback.format_exc()}")
        
        return {
            "user_profile": state.get('user_profile', {}),
            "tool_call_count": state.get('tool_call_count', 0)
        }


# 工具执行节点
def tool_node(state: AgentState):
    """执行 LLM 调用的工具"""
    # 🔒 P0-D: 二吉一: 为工具执行添加异常捕获
    try:
        messages = state['messages']
        last_message = messages[-1]
        
        # 检查是否有工具调用
        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return state
        
        tool_calls = last_message.tool_calls
        results = []
        
        # 🔒 P0-E: 添加计数（每个工具调用）
        new_count = state.get('tool_call_count', 0) + len(tool_calls)
        
        for tool_call in tool_calls:
            tool_name = tool_call['name']
            tool_input = tool_call['args']
            
            # 查找并执行对应的工具
            for tool in tools:
                if tool.name == tool_name:
                    result = tool.func(**tool_input)
                    results.append({
                        'tool_call_id': tool_call['id'],
                        'content': result
                    })
                    break
        
        # 返回工具执行结果消息
        tool_messages = []
        for result in results:
            from langchain_core.messages import ToolMessage
            tool_messages.append(
                ToolMessage(
                    tool_call_id=result['tool_call_id'],
                    content=result['content']
                )
            )
        
        return {
            "messages": tool_messages,
            "tool_call_count": new_count  # 🔒 更新计数
        }
    except Exception as e:
        error_msg = f"[Tool] 执行失败: {str(e)[:100]}"
        print(f"{error_msg}\n详细信息:\n{traceback.format_exc()}")
        
        return {
            "messages": [HumanMessage(content=error_msg)],
            "tool_call_count": state.get('tool_call_count', 0)  # 🔒 严重错误时维持数字
        }


# =============================================================================
# 第四步: 定义图控制逻辑
# =============================================================================

# =============================================================================
# 第三步: 新序
# =============================================================================

# 🔒 P1-B: 冷启动优化 - 默认画像

def get_default_profile() -> dict:
    """
    默认用户画像 - 用于冷启动优化
    
    的活：不配合那种第一轮对话可能
    没有画像信息的问题
    """
    return {
        "investment_style": "中幣覆盖",  # 默认中简
        "risk_preference": "中",  # 默认中颠峰
        "interested_sectors": ["粗粥", "医药", "科技"],  # 默认商业领域
        "preferred_analysis_depth": "深度",  # 默认深度分析
        "onboarded": False,  # 会标记：是否完成冷启动
        "update_timestamp": datetime.datetime.now().strftime("%Y-%m-%d")
    }


def should_continue(state: AgentState):
    """判断是继续调用工具，还是结束对话"""
    # 🔒 P0-E: 二梯一: 添加工具深度限制
    messages = state.get('messages', [])
    tool_call_count = state.get('tool_call_count', 0)
    max_tool_calls = 5  # 🔒 最大工具调用次数（不超在5次）
    
    # 🔒 准则一: 工具调用超限 → 结束
    if tool_call_count >= max_tool_calls:
        print(f"[Limiter] 工具调用次数({tool_call_count})超限({max_tool_calls})，结束对话")
        return "profile_updater"
    
    # 🔒 准则二: 有工具调用→ 执行工具
    last_message = messages[-1] if messages else None
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        print(f"[Limiter] 检测到工具调用（次数2: {tool_call_count}/{max_tool_calls}）")
        return "tools"
    
    # 🔒 默认: 结束（转变画像更新）
    return "profile_updater"


# =============================================================================
# 第五步: 构建和编译图
# =============================================================================

memory = MemorySaver()
workflow = StateGraph(AgentState)

# 🔒 P1-B: 冷启动优化 - 在正的初始化时注入默认画像
def initialize_state_with_default_profile() -> dict:
    """
    分序库初始化湛礫，不要等特一轮转换
    
    需要在Web UI 或 CLI 入口中调用：
        initial_state = initialize_state_with_default_profile()
        result = app.invoke(
            {**initial_state, "messages": [HumanMessage(content=query)]},
            config={"configurable": {"thread_id": "user_123"}}
        )
    """
    return {
        "messages": [],
        "user_profile": get_default_profile(),
        "intent": "general_chat",
        "tool_call_count": 0  # 🔒 P0-E: 也要正序化的加入计数器
    }

# 添加节点
workflow.add_node("router", intent_router_node)
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)
workflow.add_node("profile_updater", profile_updater_node)

# 设置边
workflow.set_entry_point("router")
workflow.add_edge("router", "agent")

# Agent 的条件边
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        "profile_updater": "profile_updater"
    }
)

# 工具执行完回到 Agent
workflow.add_edge("tools", "agent")

# 画像更新完结束
workflow.add_edge("profile_updater", END)

# 编译图
app = workflow.compile(checkpointer=memory)

print("[System] LangGraph 应用已编译，支持意图路由和画像持久化")

# 这就是全部！agent.app 已经可以使用了，支持：
# - 意图路由 (fetch_data / analysis / charting / general_chat)
# - 用户画像持久化和自动更新
# - 动态系统提示生成
# - 工具无缝集成


# =============================================================================
# 【P2 新增】流式处理支持 - 参考 smolagents
# =============================================================================

def run_stream(query: str, thread_id: str = None, initial_state: dict = None):
    """
    【P2 流式处理】流式运行 Agent，渐进式返回结果
    
    参考 smolagents 的 stream() 方法，实现实时输出
    
    Args:
        query: 用户查询
        thread_id: 会话 ID（用于维持上下文）
        initial_state: 初始状态（可选）
    
    Yields:
        Dict: 流式事件，格式为:
            {
                "type": "thinking" | "tool_call" | "tool_result" | "response",
                "content": str,
                "metadata": dict
            }
    
    使用示例:
        for event in run_stream("查询今天股价"):
            if event["type"] == "thinking":
                print(f"🧠 思考中: {event['content'][:50]}...")
            elif event["type"] == "tool_call":
                print(f"🛠️ 调用工具: {event['content']}")
            elif event["type"] == "response":
                print(f"💬 回复: {event['content']}")
    """
    import uuid as uuid_module
    
    # 生成 thread_id
    if not thread_id:
        thread_id = f"stream_{uuid_module.uuid4()}"
    
    config = {"configurable": {"thread_id": thread_id}}
    
    # 初始化状态
    if initial_state is None:
        initial_state = initialize_state_with_default_profile()
    
    # 构建输入
    from langchain_core.messages import HumanMessage as HM
    input_state = {
        **initial_state,
        "messages": [HM(content=query)]
    }
    
    # 流式执行
    try:
        for event in app.stream(input_state, config, stream_mode="updates"):
            # 解析事件
            for node_name, node_output in event.items():
                messages = node_output.get("messages", [])
                
                for msg in messages:
                    # 判断消息类型
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        # 工具调用
                        for tool_call in msg.tool_calls:
                            yield {
                                "type": "tool_call",
                                "content": tool_call.get('name', 'unknown'),
                                "metadata": {
                                    "node": node_name,
                                    "args": tool_call.get('args', {})
                                }
                            }
                    elif msg.type == "tool":
                        # 工具结果
                        yield {
                            "type": "tool_result",
                            "content": str(msg.content)[:500],
                            "metadata": {"node": node_name}
                        }
                    elif msg.type == "ai":
                        # AI 回复
                        content = msg.content if hasattr(msg, 'content') else str(msg)
                        if content:
                            yield {
                                "type": "response",
                                "content": content,
                                "metadata": {"node": node_name}
                            }
                    else:
                        # 其他类型
                        yield {
                            "type": "thinking",
                            "content": str(msg)[:200],
                            "metadata": {"node": node_name, "msg_type": msg.type}
                        }
    except Exception as e:
        yield {
            "type": "error",
            "content": str(e),
            "metadata": {"error_type": type(e).__name__}
        }


async def run_stream_async(query: str, thread_id: str = None, initial_state: dict = None):
    """
    【P2 异步流式处理】异步版流式运行
    
    用于异步场景（如 FastAPI、WebSocket）
    
    Args:
        query: 用户查询
        thread_id: 会话 ID
        initial_state: 初始状态
    
    Yields:
        Dict: 流式事件
    
    使用示例 (FastAPI):
        @app.get("/stream")
        async def stream_endpoint(query: str):
            async def event_generator():
                async for event in run_stream_async(query):
                    yield f"data: {json.dumps(event)}\n\n"
            return StreamingResponse(event_generator())
    """
    # 同步版本的包装，逐步 yield
    for event in run_stream(query, thread_id, initial_state):
        yield event
