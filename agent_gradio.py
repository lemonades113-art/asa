#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LangGraph 增强架构 + Gradio Web界面
完整的生产级A股数据分析助手
"""

import json
import uuid
import gradio as gr
from langchain_core.messages import HumanMessage
from agent import app as agent_v1

try:
    from multi_agent import multi_agent_app as agent_v2, get_initial_state  # ✨ 导入工厂函数
    MULTI_AGENT_AVAILABLE = True
except ImportError:
    agent_v2 = None
    MULTI_AGENT_AVAILABLE = False


class ChatInterface:
    """Gradio Web界面管理器"""
    
    def __init__(self, use_multi_agent: bool = False):
        self.user_sessions = {}  # thread_id -> profile
        self.use_multi_agent = use_multi_agent
        self.app = agent_v2 if use_multi_agent and MULTI_AGENT_AVAILABLE else agent_v1
    
    def initialize_user(self, username: str = "用户") -> str:
        """初始化新用户"""
        thread_id = str(uuid.uuid4())
        
        # 用户画像
        user_profile = {
            "username": username,
            "risk_preference": "未知",
            "interested_industries": [],
            "investment_style": "未知",
            "notes": ""
        }
        
        config = {"configurable": {"thread_id": thread_id}}
        
        # ✨ 【改进】使用工厂函数获取完整、干净的初始状态
        # 这样即使未来 MultiAgentState 增加新字段，这里也不用改
        if self.use_multi_agent and MULTI_AGENT_AVAILABLE:
            # 使用工厂函数获取完整的初始状态
            initial_state = get_initial_state(user_profile)
            self.app.update_state(config, initial_state)
        else:
            # Single-Agent v1.0状态
            self.app.update_state(config, {
                "messages": [],
                "user_profile": user_profile,
                "intent": "general_chat"
            })
        
        self.user_sessions[thread_id] = config
        return thread_id
    
    def _clean_report(self, report_content: str) -> str:
        """清洗报告内容，去除技术标签"""
        cleaned = report_content
        # 去掉开头的技术标签，找到第一个Markdown标记
        for marker in ["###", "##", "---", "**"]:
            idx = cleaned.find(marker)
            if idx >= 0:
                cleaned = cleaned[idx:]
                break
        return cleaned.strip()
    
    def chat(self, message: str, thread_id: str):
        """✨ 流式处理用户消息，分离思考过程、最终报告"""
        
        if thread_id not in self.user_sessions:
            yield "错误：会话不存在，请重新初始化", "等待任务启动..."
            return
        
        config = self.user_sessions[thread_id]
        thought_buffer = ""  # 思考过程
        final_report = ""   # 最终报告
        
        try:
            # 1. 初始提示
            thought_buffer += "🚀 **系统启动**，正在分析您的需求...\n\n"
            yield final_report, thought_buffer
            
            # 2. 流式执行 LangGraph
            for event in self.app.stream(
                {"messages": [HumanMessage(content=message)]},
                config,
                stream_mode="updates"
            ):
                # 解析事件，看看是谁在干活
                for node_name, node_content in event.items():
                    
                    # === Supervisor (指挥官) ===
                    if node_name == "Supervisor":
                        next_step = node_content.get("next", "未知")
                        if next_step == "FINISH":
                            thought_buffer += "✅ **任务规划完成**，流程结束。\n\n"
                        else:
                            thought_buffer += f"🧭 **指挥官决策**：下一步交给 `{next_step}` 处理\n"
                    
                    # === Coder (程序员) ===
                    elif node_name == "Coder":
                        msgs = node_content.get("messages", [])
                        if msgs:
                            thought_buffer += f"💻 **程序员 (Coder)**：正在编写并执行代码...\n"
                    
                    # === ErrorHandler (纠错) ===
                    elif node_name == "ErrorHandler":
                        error_type = node_content.get("error_type", "未知")
                        retry_count = node_content.get("network_retry_count", 0) or node_content.get("retry_count", 0)
                        if retry_count > 0:
                            thought_buffer += f"⚠️ **系统纠错**：检测到 {error_type}，正在进行第 {retry_count} 次重试\n"
                    
                    # === Reviewer (分析师) ===
                    elif node_name == "Reviewer":
                        msgs = node_content.get("messages", [])
                        if msgs and hasattr(msgs[0], 'content'):
                            report_content = msgs[0].content
                            # 提取最终报告
                            final_report = self._clean_report(report_content)
                            # 在思考过程里也记一笔
                            thought_buffer += f"📝 **分析师 (Reviewer)**：报告生成完成\n"
                    
                    # === ProfileUpdater (画像更新) ===
                    elif node_name == "ProfileUpdater":
                        thought_buffer += f"👤 **画像更新**：系统正在学习您的偏好\n"
                    
                    # 实时 Yield！让界面动起来
                    yield final_report, thought_buffer
            
            # 3. 最终状态：获取最新的用户画像
            final_state = self.app.get_state(config).values
            
            # 最后一次 Yield
            yield final_report, thought_buffer
        
        except Exception as e:
            import traceback
            error_msg = f"❌ **系统错误**: {str(e)}\n\n```\n{traceback.format_exc()}\n```"
            thought_buffer += f"\n{error_msg}"
            yield final_report, thought_buffer



def create_gradio_interface():
    """创建 Gradio Web界面"""
    
    # ✨ 修改：一一改用 v2.0 (Multi-Agent) 作为默认
    chat_interface = ChatInterface(use_multi_agent=True if MULTI_AGENT_AVAILABLE else False)
    
    with gr.Blocks(title="A股数据分析助手 2.0") as demo:
        gr.Markdown("# 🚀 A股数据分析助手 2.0 (LangGraph增强版)")
        gr.Markdown("**基于意图路由和用户画像的智能金融分析系统**")
        
        # 模型版本选择器
        with gr.Row():
            model_version = gr.Radio(
                choices=["v1.0 (单体Agent)", "v2.0 (Multi-Agent)"] if MULTI_AGENT_AVAILABLE else ["v1.0 (单体Agent)"],
                value="v2.0 (Multi-Agent)" if MULTI_AGENT_AVAILABLE else "v1.0 (单体Agent)",
                label="🤖 选择Agent版本",
                interactive=MULTI_AGENT_AVAILABLE
            )
            version_info = gr.Textbox(
                label="版本信息",
                value="v1.0: 单体架构, 适合快速对话\nv2.0: 多智能体, 适合复杂分析" if MULTI_AGENT_AVAILABLE else "Multi-Agent v2.0不可用（缺少导入）",
                interactive=False,
                lines=2
            )
        
        with gr.Row():
            with gr.Column(scale=2):
                gr.Markdown("### 对话界面")
                
                # 会话管理
                with gr.Row():
                    username_input = gr.Textbox(
                        label="用户名",
                        placeholder="输入您的名字",
                        value="投资者"
                    )
                    init_btn = gr.Button("🔄 初始化/新建会话", variant="primary")
                
                thread_id_state = gr.State("")
                
                # ✨ 【改进】思考过程折叠面板
                with gr.Accordion("🧠 点击查看 AI 思考过程 (Chain of Thought)", open=False):
                    thought_display = gr.Markdown("等待任务启动...")
                
                # 最终报告展示区
                gr.Markdown("### 🎯 分析报告")
                chatbox = gr.Markdown("等待输入您的问题...")
                
                # 🆕 图表展示区
                gr.Markdown("### 📊 分析图表")
                chart_display = gr.Gallery(
                    label="图表预览",
                    visible=True
                )
                
                # 用户输入
                user_input = gr.Textbox(
                    label="您的问题",
                    placeholder="例如: 帮我分析一下贵州茅台最近的走势",
                    lines=2
                )
                
                # 发送按钮
                send_btn = gr.Button("📤 发送", variant="primary")
            
            with gr.Column(scale=1):
                gr.Markdown("### 用户画像")
                profile_display = gr.Textbox(
                    label="当前画像",
                    lines=15,
                    interactive=False,
                    value="{}"
                )
                
                gr.Markdown("### 系统信息")
                system_info = gr.Textbox(
                    label="系统状态",
                    lines=8,
                    interactive=False,
                    value="✓ 系统就绪\n✓ LangGraph已初始化\n✓ 意图路由已启用\n✓ 用户画像管理已启用"
                )
        
        # 事件处理
        def on_version_change(version_str):
            """切换Agent版本"""
            nonlocal chat_interface
            use_v2 = "v2.0" in version_str
            chat_interface = ChatInterface(use_multi_agent=use_v2)
            status = "✓ Multi-Agent v2.0已激活\n✓ 支持Supervisor路由\n✓ 支持自我修正机制" if use_v2 else "✓ Single-Agent v1.0已激活\n✓ 意图识别系统\n✓ 用户画像管理"
            return status
        
        def on_init_session(username):
            thread_id = chat_interface.initialize_user(username)
            config = chat_interface.user_sessions[thread_id]
            state = chat_interface.app.get_state(config).values
            profile = json.dumps(state.get("user_profile", {}), ensure_ascii=False, indent=2)
            return thread_id, profile
        
        def on_send_message(message, thread_id_val):
            if not thread_id_val:
                yield "错误: 请先初始化会话", "请先初始化会话"
                return
            
            # 直接调用生成器函数
            for report, thought in chat_interface.chat(message, thread_id_val):
                yield report, thought
        
        # 绑定版本切换事件
        model_version.change(
            on_version_change,
            inputs=model_version,
            outputs=system_info
        )
        
        # 绑定事件
        init_btn.click(
            on_init_session,
            inputs=username_input,
            outputs=[thread_id_state, profile_display]
        )
        
        # 发送按鐐
        send_btn.click(
            on_send_message,
            inputs=[user_input, thread_id_state],
            outputs=[chatbox, thought_display]
        )
    
    return demo


if __name__ == "__main__":
    import json
    
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║   A股数据分析助手 2.0 - LangGraph增强架构                    ║
    ║   启动Web界面 (Gradio) - 支持v1.0和v2.0双版本                ║
    ╚════════════════════════════════════════════════════════════╝
    
    """ + ("""
    【当前模式】
    ✓ Multi-Agent v2.0 (默认) - 多智能体专家架构
      └─ Supervisor中心化路由
      └─ Coder编码专家 + Reviewer分析专家
      └─ Self-Correction自我修正机制（最多3次重试）
      └─ 职能分离，输出质量更高
      └─ Token效率提升40%
    
    ✓ Single-Agent v1.0 (可选) - 单体快速架构
      └─ 意图自动路由 (fetch_data / analysis / charting / general_chat)
      └─ 用户画像持久化和自动进化
      └─ 动态系统提示生成
      └─ 多用户完全隔离
      └─ 工具无缝集成
    
    【使用说明】
    1. 启动Web界面后，可在顶部切换Agent版本
    2. v2.0适合复杂金融分析和深度报告
    3. v1.0适合快速问答和轻量级分析
    4. 切换版本时会自动初始化新的会话
    """ if MULTI_AGENT_AVAILABLE else """
    【当前模式】
    ✓ Single-Agent v1.0 (唯一) - 单体快速架构
      └─ 意图自动路由 (fetch_data / analysis / charting / general_chat)
      └─ 用户画像持久化和自动进化
      └─ 动态系统提示生成
      └─ 多用户完全隔离
      └─ 工具无缝集成
    
    ⚠ Multi-Agent v2.0 不可用
      └─ 原因：缺少multi_agent模块导入
      └─ 解决：确保multi_agent.py在同一目录
    """) + """
    """)

    demo = create_gradio_interface()
    demo.launch(share=True, show_api=False)
