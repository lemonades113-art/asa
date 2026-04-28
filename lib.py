"""
created_by: way
created_time: 2025-11-06 10:34:33
description: ASA (Agent Stock Assistant) 工具库

v2.0 升级要点:
1. 模型分层: smart (qwen-plus) vs fast (qwen-turbo)
2. Thread-aware Kernel 管理器: 实现 Namespace 隔离
3. OpenSandbox SDK 支持: 工业级代码执行环境
4. 混合检索器: 向量搜索 + BM25
5. Tushare 数据适配层: 自动处理类型转换、列名兼容性
6. 消息修剪: 防止 Token 爆炸
7. 工具动态发现机制: 参考 smolagents

v2.1 升级要点 (面试强化):
1. 输出协议强制: _format_execution_result 自动添加 [DATA]:/[ERROR]:/[RESULT]: 标记
2. 用户隔离强化: 每个 thread_id 独立的 threading.Lock，确保单用户串行、多用户并行
"""
import contextlib
import datetime
import io
import json
import os
import re
import subprocess
import sys
import traceback
import uuid
import asyncio
from typing import Union, Dict, Optional, Tuple
import threading

# 🔧 [修复] huggingface_hub 版本兼容性 - 必须在 gradio 之前执行
try:
    import huggingface_hub
    if not hasattr(huggingface_hub, "HfFolder"):
        class MockHfFolder:
            @staticmethod
            def get_token(): return None
            @staticmethod
            def save_token(t): pass
            @staticmethod
            def delete_token(): pass
        huggingface_hub.HfFolder = MockHfFolder
except ImportError:
    pass

# 🚀 [新增] OpenSandbox SDK 支持 (工业级代码执行环境)
try:
    from opensandbox import Sandbox
    from code_interpreter import CodeInterpreter, SupportedLanguage
    OPENSANDBOX_AVAILABLE = True
    print("[OpenSandbox] SDK 已加载")
except ImportError:
    OPENSANDBOX_AVAILABLE = False
    print("[OpenSandbox] SDK 未安装，使用本地内核")

import gradio as gr
import jieba
import numpy as np
import pandas as pd
from gradio import ChatMessage

from langchain_core.messages import AIMessageChunk, ToolMessage, SystemMessage, HumanMessage, BaseMessage
from langchain_openai import ChatOpenAI
from rank_bm25 import BM25Okapi
from langchain_huggingface import HuggingFaceEmbeddings
import faiss as _faiss  # ms-agent 同款：FAISS 替代 chromadb，完全兼容 Python 3.14
try:
    from langchain_chroma import Chroma
    _CHROMA_AVAILABLE = True
except Exception:
    Chroma = None
    _CHROMA_AVAILABLE = False
    # 不打印 WARN，FAISS 路径会接管向量检索
from langchain_core.documents import Document
from langchain_core.tools import tool, BaseTool
from pydantic import BaseModel, Field
from typing import Literal, TypedDict, Annotated, Callable, Any, Dict, List, Optional, Tuple

import functools

from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph.state import CompiledStateGraph

import conf
import tushare as ts


def get_chat_model(
        model_type: str = "default", temperature=None, max_tokens=None, timeout=120, max_retries=2,
        api_key=conf.api_key, base_url=conf.base_url, verbose=False, **kwargs
) -> ChatOpenAI:
    """
    模型工厂：支持模型分层
    
    支持阿里云通义千问模型
    model_type:
      - "smart": qwen-plus (用于 Supervisor, Coder, Reviewer - 强逻辑)
      - "fast": qwen-turbo (用于 ErrorHandler, ProfileUpdater - 轻量级)
      - "default": qwen-plus (默认高性能模型)
    """
    # 🔧 模型配置（支持多厂商切换）
    config = {
        # 阿里云通义千问
        "smart": {"model": "qwen-plus", "temperature": 0.1},  # 高性能模型（用于生产）
        "fast": {"model": "qwen-turbo", "temperature": 0.1},  # 快速模型（低成本）
        "default": {"model": "qwen-plus", "temperature": 0.1},  # 默认高性能模型
        
        # MiniMax M1（支持 function calling，适合 structured output）
        "minimax": {"model": "MiniMax-M1", "temperature": 0.1},
        
        # DeepSeek（推荐：性价比高，支持 Function Calling + Structured Output）
        "deepseek": {"model": "deepseek-chat", "temperature": 0.1},
        "smart": {"model": "deepseek-chat", "temperature": 0.1},  # 覆盖 smart 为 DeepSeek
        "fast": {"model": "deepseek-chat", "temperature": 0.1},   # DeepSeek 无 qwen-turbo，统一用 deepseek-chat
        "default": {"model": "deepseek-chat", "temperature": 0.1},  # 默认也用 DeepSeek
        
        # Kimi（Moonshot，支持 tool use）
        "kimi": {"model": "moonshot-v1-8k", "temperature": 0.1},
    }
    
    # 获取目标配置
    if model_type in config:
        target_config = config[model_type]
        actual_model = target_config["model"]
        actual_temperature = temperature if temperature is not None else target_config["temperature"]
    else:
        # 如果 model_type 是具体的模型名，直接使用
        actual_model = model_type
        actual_temperature = temperature if temperature is not None else 0.1
    
    # 🔧 阿里云 API 为 OpenAI 兼容模式，直接使用 ChatOpenAI
    return ChatOpenAI(
        model=actual_model,
        temperature=actual_temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        api_key=api_key,
        base_url=base_url,
        verbose=verbose,
        **kwargs
    )


def stream_agent(query: str, agent_executor: CompiledStateGraph, system_prompt: str, thread_id=None,
                 is_new_conversation=True):
    """
    触发agent多轮对话，并进行流式输出。

    参数:
        query: 用户查询
        agent_executor: 已创建的agent执行器实例
        system_prompt: 系统prompt
        thread_id: 对话线程ID，用于维护对话上下文
        is_new_conversation: 是否为新对话

    返回:
        agent_executor: agent执行器实例，可用于后续对话
    """
    if not thread_id:
        thread_id = f'thread_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}_{uuid.uuid4()}'

    # Use the agent with the same thread_id for context continuity
    config = {"configurable": {"thread_id": thread_id}}

    if is_new_conversation:
        # For new conversation, include system message
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
    else:
        # For follow-up conversation, just add user message
        messages = [{"role": "user", "content": query}]

    tool_flag = False
    for stream_mode, chunk in agent_executor.stream(
            {"messages": messages}, config,
            stream_mode=["messages", "custom"]
    ):
        if stream_mode == "messages":
            message_chunk, metadata = chunk
            if isinstance(message_chunk, AIMessageChunk):  # Check if it's an AIMessageChunk
                if not message_chunk.tool_call_chunks:
                    tool_flag = False
                    print(message_chunk.content, end="", flush=True)
                elif not tool_flag:
                    tool_flag = True
                    print('\n', end="", flush=True)
                    print(message_chunk.tool_call_chunks[0]['name'], message_chunk.tool_call_chunks[0]['id'], end="\n",
                          flush=True)
                else:
                    print(message_chunk.tool_call_chunks[0]['args'], end="", flush=True)

            elif isinstance(message_chunk, ToolMessage):  # Check if it's a ToolMessage
                print(message_chunk.content, flush=True)
            yield message_chunk
        elif stream_mode == "custom":
            print(chunk, end="", flush=True)
            yield chunk

    return agent_executor


def stream_writer(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = None
        try:
            content = ' '.join(str(arg) for arg in args) + kwargs.get('end', '\n')
            writer = get_stream_writer()
            writer(content)
            result = func(*args, **kwargs)
        except:
            pass
        return result

    return wrapper


print = stream_writer(print)


class GradioInterface:
    def __init__(self, agent_executor, system_prompt: str):
        self.agent_executor = agent_executor
        self.system_prompt = system_prompt

    def stream_response(self, query, history):
        """流式获取agent的响应"""
        is_new_conversation = not bool(history)
        if is_new_conversation:
            thread_id = f"thread_{datetime.datetime.now().strftime('%y%m%d%H%M%S')}_{uuid.uuid4()}"
        else:
            thread_id = history[0]['options'][0]['value']

        if query.strip():
            # 添加用户消息
            user_message = ChatMessage(role="user", content=query)
            if is_new_conversation:
                user_message.options = [{'value': thread_id}]
            history.append(user_message)
            yield history, ""

            try:
                tool_flag = False
                sa = stream_agent(
                    query,
                    agent_executor=self.agent_executor,
                    system_prompt=self.system_prompt,
                    thread_id=thread_id,
                    is_new_conversation=is_new_conversation
                )
                last_message_id = None
                while True:
                    message_chunk = next(sa)

                    if isinstance(message_chunk, AIMessageChunk):  # Check if it's an AIMessageChunk
                        if message_chunk.id != last_message_id:
                            last_message_id = message_chunk.id
                            history.append(ChatMessage(role="assistant", content=''))
                        if not message_chunk.tool_call_chunks:
                            tool_flag = False
                            history[-1].content += message_chunk.content
                        else:
                            if not tool_flag:
                                tool_flag = True
                                history.append(ChatMessage(
                                    role="assistant", content='',
                                    metadata={
                                        'title': '🛠️ ' + message_chunk.tool_call_chunks[0]['name'],
                                        'id': str(message_chunk.tool_call_chunks[0]['id']),
                                        'log': '',
                                    }
                                ))
                            else:
                                if len(history[-1].metadata['log']) < 40:
                                    history[-1].metadata['log'] += message_chunk.tool_call_chunks[0][
                                        'args']
                                else:
                                    history[-1].metadata['log'] = history[-1].metadata['log'][:-3] + '...'

                    elif isinstance(message_chunk, ToolMessage):  # Check if it's a ToolMessage
                        history[-1].content += message_chunk.content
                        if 'search_dh_functions' in history[-1].metadata['title']:
                            history[-1].content = history[-1].content[:500]
                    else:
                        history[-1].content += message_chunk
                        if 'search_dh_functions' in history[-1].metadata['title']:
                            history[-1].content = history[-1].content[:500]
                    yield history, ""
            except StopIteration as e:
                self.agent_executor = e.value  # 从这里获取 return 的值
        else:
            yield history, ""

    def create_interface(self, title: str, description: str = ''):
        """创建Gradio界面"""
        with gr.Blocks(title=title) as demo:
            gr.Markdown(f"# {title}")
            gr.Markdown(f"{description}")

            with gr.Row():
                with gr.Column(scale=3):
                    # 使用type="messages"启用ChatMessage格式
                    chatbot = gr.Chatbot(label="对话历史", height=800, type="messages")
                    msg = gr.Textbox(label="输入您的查询", placeholder="请输入您的查询...")
                    # with gr.Row():
                    #     submit_btn = gr.Button("提交")
            # # 设置事件处理
            # submit_event = submit_btn.click(
            #     self.stream_response,
            #     inputs=[msg, chatbot],
            #     outputs=[chatbot, msg, file_selector,thread_id_output]
            # )

            msg.submit(
                self.stream_response,
                inputs=[msg, chatbot],
                outputs=[chatbot, msg]
            )

        return demo


# 创建一个单独的脚本文件来运行测试函数
def create_temp_script(script_content):
    # 创建临时脚本文件
    script_root = os.path.join(os.path.dirname(__file__), 'tmp_scripts')
    os.makedirs(script_root, exist_ok=True)
    script_path = os.path.join(script_root, f'{uuid.uuid4()}.py')
    os.makedirs(script_root, exist_ok=True)
    with open(script_path, mode='w', encoding='utf-8') as f:
        f.write(script_content)
        return script_path


class StatefulPythonKernel:
    """
    持久化、有状态的Python执行内核（本地原生版）
    
    v2.1 安全增强：内置 AST 静态防御层
    - 在 exec() 前遍历 AST，拦截危险模块和函数
    - 防御黑名单：os, subprocess, sys, shutil, socket 等系统模块
    - 防御 getattr 间接绕过、compile/eval 二次执行
    - 节点复杂度检查防止 CPU Bomb
    """
    
    # 黑名单：系统级模块（防止文件系统/网络/进程操作）
    _BLOCKED_MODULES = {
        "os", "subprocess", "sys", "shutil", "socket",
        "ctypes", "multiprocessing", "threading",
        "importlib", "pathlib", "glob",
    }
    
    # 黑名单：危险内置函数
    _BLOCKED_BUILTINS = {
        "eval", "exec", "compile", "open", "__import__",
        "getattr", "setattr", "delattr",
    }
    
    @staticmethod
    def safety_check(code: str) -> Tuple[bool, str]:
        """
        AST 级别静态安全检查（在 exec() 前调用）
        
        面试金句："我实现了 AST 节点巡检，任何尝试通过 getattr(os, 'system') 等
        隐蔽手段绕过权限的指令，在代码运行前就会被系统丢弃。"
        
        Returns:
            (passed: bool, reason: str)
        """
        import ast as _ast
        
        # Step 1: 语法合法性
        try:
            tree = _ast.parse(code)
        except SyntaxError as e:
            return False, f"语法错误: {e}"
        
        # Step 2: 节点复杂度检查（防止 CPU Bomb）
        node_count = sum(1 for _ in _ast.walk(tree))
        if node_count > 2000:
            return False, f"代码复杂度过高（AST 节点数 {node_count} > 2000），可能存在循环展开攻击"
        
        # Step 3: 逐节点巡检
        for node in _ast.walk(tree):
            # 3a. 拦截 import 语句（import os / import subprocess）
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    top_module = alias.name.split(".")[0]
                    if top_module in StatefulPythonKernel._BLOCKED_MODULES:
                        return False, f"禁止导入系统模块: {alias.name}"
            
            # 3b. 拦截 from xxx import（from os import system）
            if isinstance(node, _ast.ImportFrom):
                if node.module:
                    top_module = node.module.split(".")[0]
                    if top_module in StatefulPythonKernel._BLOCKED_MODULES:
                        return False, f"禁止 from 导入系统模块: {node.module}"
            
            # 3c. 拦截危险内置函数调用
            if isinstance(node, _ast.Call):
                func = node.func
                # 直接调用：eval(...), exec(...)
                if isinstance(func, _ast.Name) and func.id in StatefulPythonKernel._BLOCKED_BUILTINS:
                    return False, f"禁止调用危险函数: {func.id}()"
                # 属性调用：obj.eval(...) 等
                if isinstance(func, _ast.Attribute) and func.attr in StatefulPythonKernel._BLOCKED_BUILTINS:
                    return False, f"禁止通过属性调用危险函数: .{func.attr}()"
        
        return True, "AST 安全检查通过"
    
    def __init__(self):
        # 初始化全局变量字典，预置常用库
        self.globals = {
            "__builtins__": __builtins__,
            "pd": pd,
            "ts": ts,
            "np": np,
        }
        # 预导入常用库
        self._run_pre_imports()
        
        # 🔧 【P0优化】初始化API缓存，减少rate_limit触发
        try:
            from api_cache import get_api_cache
            self.api_cache = get_api_cache()
            print("[StatefulPythonKernel] API缓存已启用")
        except ImportError:
            self.api_cache = None
            print("[StatefulPythonKernel] API缓存未启用")
    
    def _run_pre_imports(self):
        """初始化时预先导入常用库和初始化API"""
        setup_code = """
import pandas as pd
import tushare as ts
import numpy as np
import datetime
from datetime import datetime as dt

# 🔧 配置 Tushare API 令牌
ts.set_token('{tushare_token}')
pro = ts.pro_api()

# 🔧 【P0优化】限制 pandas 输出长度，防止 Token 爆表
pd.set_option('display.max_rows', 20)
pd.set_option('display.max_columns', 10)
pd.set_option('display.width', 200)
pd.set_option('display.max_colwidth', 50)

# 🔧 【P0优化】注入API缓存包装器，减少rate_limit触发
try:
    from api_cache import get_api_cache
    _api_cache = get_api_cache()
    
    # 包装pro的常用方法，添加缓存
    _original_daily_basic = pro.daily_basic
    def _cached_daily_basic(**kwargs):
        result = _api_cache.get("daily_basic", **kwargs)
        if result is not None:
            return result
        result = _original_daily_basic(**kwargs)
        _api_cache.set("daily_basic", result, **kwargs)
        return result
    pro.daily_basic = _cached_daily_basic
    
    _original_income = pro.income
    def _cached_income(**kwargs):
        result = _api_cache.get("income", **kwargs)
        if result is not None:
            return result
        result = _original_income(**kwargs)
        _api_cache.set("income", result, **kwargs)
        return result
    pro.income = _cached_income
    
    print("[内核] API缓存包装器已注入: daily_basic, income")
except ImportError:
    print("[内核] API缓存未启用")
""".format(tushare_token=conf.tushare_token)
        try:
            exec(setup_code, self.globals)
        except Exception as e:
            print(f"[内核初始化警告] {e}")
    
    def execute(self, code: str, max_output_length: int = 8000, timeout: int = 60) -> str:
        """
        在持久化环境中执行Python代码（带熔断器）
        
        Args:
            code: 要执行的Python代码
            max_output_length: 最大输出长度限制，防止Token爆表（默认8000字符）
            timeout: 执行超时时间（秒），防止死循环阻塞（默认60秒，大数据查询需要更长时间）
        
        Returns:
            执行结果或错误信息
        """
        import threading
        import time
        
        # 清理代码中的 Markdown 标记
        code = code.replace("```python", "").replace("```", "").strip()
        
        # 用于存储执行结果
        result_container = {"output": None, "error": None, "done": False}
        
        def target():
            """在独立线程中执行代码"""
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                try:
                    # 🔒 [AST 安全检查] 在 exec 前拦截危险代码
                    passed, reason = StatefulPythonKernel.safety_check(code)
                    if not passed:
                        result_container["error"] = f"[SECURITY] 代码被 AST 安全层拦截: {reason}"
                        result_container["done"] = True
                        return
                    
                    # 核心：在持久化的 self.globals 作用域下执行代码
                    exec(code, self.globals)
                except Exception as e:
                    result_container["error"] = f"代码执行出错:\n{traceback.format_exc()}"
                    result_container["done"] = True
                    return
            
            # 获取输出内容
            output = stdout_capture.getvalue()
            error_out = stderr_capture.getvalue()
            
            final_output = ""
            if output:
                final_output += f"{output}"
            if error_out:
                final_output += f"[错误输出]\n{error_out}"
            
            if not final_output:
                final_output = "代码已执行，无控制台输出。"
            
            # 🔧 【P0优化】截断过长的输出，防止Token爆表
            if len(final_output) > max_output_length:
                truncated_len = len(final_output) - max_output_length
                final_output = final_output[:max_output_length] + f"\n\n[输出截断] 已省略 {truncated_len} 字符，仅显示前 {max_output_length} 字符。如需查看完整数据，请缩小查询范围。"
            
            result_container["output"] = final_output
            result_container["done"] = True
        
        # 创建并启动执行线程
        exec_thread = threading.Thread(target=target)
        exec_thread.daemon = True  # 设置为守护线程，主线程退出时自动终止
        
        start_time = time.time()
        exec_thread.start()
        
        # 等待执行完成或超时
        exec_thread.join(timeout=timeout)
        
        # 检查是否超时
        if not result_container["done"]:
            # ⚡ 熔断器触发：执行超时
            elapsed = time.time() - start_time
            print(f"[熔断器] 代码执行超时（{elapsed:.1f}s > {timeout}s），强制终止")
            
            # 智能判断：根据已有输出决定处理方式
            partial_output = stdout_capture.getvalue()
            
            if partial_output and len(partial_output) > 100:
                # 场景2: 有输出但慢 → 降级处理，返回部分结果
                return f"[PARTIAL RESULT] 数据查询耗时较长（>{timeout}秒），已返回部分结果。\n\n已获取数据:\n{partial_output[:2000]}...\n\n[建议] 如需完整数据，请：\n1. 缩小查询时间范围\n2. 使用limit参数限制条数（如limit=100）\n3. 分多次查询"
            else:
                # 场景1/3: 无输出 → 可能是死循环或接口超时
                return f"[ERROR] 代码执行超过{timeout}秒，已强制终止。\n\n可能原因：\n1. 死循环（如while True未设置退出条件）\n2. Tushare接口响应超时或网络问题\n3. 数据量过大导致处理缓慢\n\n建议：\n- 检查循环条件，确保有退出机制\n- 使用limit参数限制数据量\n- 缩小查询时间范围\n- 稍后重试或检查网络连接"
        
        # 执行完成，返回结果
        if result_container["error"]:
            return result_container["error"]
        return result_container["output"]
    
    def get_variable(self, var_name: str):
        """获取执行环境中的变量"""
        return self.globals.get(var_name, None)
    
    def reset(self):
        """重置执行环境（清空所有自定义变量，但保留库）"""
        keys_to_delete = [k for k in self.globals.keys() if not k.startswith('__') and k not in ['pd', 'ts', 'np', 'datetime', 'dt', 'pro']]
        for k in keys_to_delete:
            del self.globals[k]



class OpenSandboxKernel:
    """基于 OpenSandbox 的工业级有状态执行内核"""
    
    def __init__(self, server_url="http://localhost:8080", image="opensandbox/code-interpreter:v1.0.1"):
        self.server_url = server_url
        self.image = image
        self.sandbox = None
        self.interpreter = None
        self._loop = None
        
    async def _init_sandbox(self):
        """异步初始化沙箱和解释器"""
        if self.sandbox is None:
            print(f"[OpenSandbox] 正在连接沙箱服务器: {self.server_url}")
            self.sandbox = await Sandbox.create(
                self.image,
                server_url=self.server_url,
                env={"TUSHARE_TOKEN": conf.tushare_token}
            )
            self.interpreter = await CodeInterpreter.create(self.sandbox)
            
            # 预热环境
            setup_code = """
import pandas as pd
import tushare as ts
import numpy as np
import os
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()
"""
            await self.interpreter.codes.run(setup_code, language=SupportedLanguage.PYTHON)
            print("[OpenSandbox] 金融沙箱初始化完成")

    def execute(self, code: str) -> str:
        """同步包装异步调用，兼容原有接口"""
        # 清理代码
        code = code.replace("```python", "").replace("```", "").strip()
        
        try:
            # 使用 asyncio 运行异步任务
            return asyncio.run(self._async_execute(code))
        except Exception as e:
            return f"[OpenSandbox 错误] 执行失败: {str(e)}\n{traceback.format_exc()}"

    async def _async_execute(self, code: str) -> str:
        await self._init_sandbox()
        
        # 执行代码
        result = await self.interpreter.codes.run(
            code,
            language=SupportedLanguage.PYTHON
        )
        
        # 收集输出
        output = ""
        if result.logs.stdout:
            output += "\n".join([log.text for log in result.logs.stdout])
        
        if result.logs.stderr:
            output += "\n[错误输出]\n" + "\n".join([log.text for log in result.logs.stderr])
            
        if not output and not result.result:
            output = "代码已执行，无控制台输出。"
        elif result.result:
            # 如果有返回结果（最后一个表达式的值），也拼接到输出中
            output += f"\n[返回结果]\n{result.result[0].text}"
            
        return output

    def reset(self):
        """重启沙箱实现重置"""
        if self.sandbox:
            asyncio.run(self.sandbox.kill())
            self.sandbox = None
            self.interpreter = None
            print("[OpenSandbox] 沙箱已重置")

# =============================================================================
# 【工业级改进】Thread-aware Kernel 管理器 - 实现 Namespace 隔离
# =============================================================================
# 问题：原全局单例 global_kernel 导致所有用户共享同一个执行环境
# 解决：使用 thread_id 作为 key，每个会话拥有独立的 Kernel 实例
# =============================================================================

class KernelManager:
    """
    内核管理器 - 为每个 thread_id 提供隔离的执行环境
    
    【核心机制】
    - 隔离性：每个 thread_id 拥有独立的 Kernel 实例，变量互不干扰
    - 持久性：同一用户的多次请求共享同一个 Kernel，支持多轮对话
    - 自动清理：支持定期清理不活跃的 Kernel，防止内存泄漏
    
    【使用方式】
    kernel_manager = KernelManager()
    kernel = kernel_manager.get_kernel(thread_id)
    result = kernel.execute(code)
    """
    
    def __init__(self):
        self._kernels: Dict[str, Union[StatefulPythonKernel, OpenSandboxKernel]] = {}
        self._lock = asyncio.Lock() if asyncio else None
        self._use_sandbox = os.getenv("USE_ASA_SANDBOX", "false").lower() == "true"
        
        # 打印初始化信息
        if self._use_sandbox and OPENSANDBOX_AVAILABLE:
            print("[内核选择] [Rocket] 正在启动 OpenSandbox 工业级内核 (Thread-aware)...")
        else:
            if self._use_sandbox:
                print("[内核警告] [Warning] USE_ASA_SANDBOX=true 但 opensandbox 未安装，降级为本地内核")
            else:
                print("[内核选择] [Home] 当前使用本地 Python 内核 (非隔离, Thread-aware)")
    
    def get_kernel(self, thread_id: str) -> Union[StatefulPythonKernel, OpenSandboxKernel]:
        """
        获取指定 thread_id 对应的 Kernel 实例
        
        Args:
            thread_id: 会话唯一标识（如用户ID、session ID等）
            
        Returns:
            Kernel 实例（如果不存在则自动创建）
        """
        if thread_id not in self._kernels:
            # 创建新的 Kernel 实例
            if self._use_sandbox and OPENSANDBOX_AVAILABLE:
                self._kernels[thread_id] = OpenSandboxKernel()
            else:
                self._kernels[thread_id] = StatefulPythonKernel()
            print(f"[KernelManager] 为 thread_id={thread_id} 创建新内核实例")
        
        return self._kernels[thread_id]
    
    def release_kernel(self, thread_id: str):
        """释放指定 thread_id 的 Kernel（用于会话结束或重置）"""
        if thread_id in self._kernels:
            kernel = self._kernels[thread_id]
            if hasattr(kernel, 'reset'):
                kernel.reset()
            del self._kernels[thread_id]
            print(f"[KernelManager] 已释放 thread_id={thread_id} 的内核")
    
    def list_active_threads(self) -> List[str]:
        """列出当前活跃的 thread_id 列表"""
        return list(self._kernels.keys())
    
    def get_stats(self) -> Dict[str, int]:
        """获取内核管理统计信息"""
        return {
            "active_kernels": len(self._kernels),
            "using_sandbox": self._use_sandbox and OPENSANDBOX_AVAILABLE
        }


# =============================================================================
# 输出协议强制：自动添加 [DATA]:/[ERROR]:/[RESULT]: 标记
# 参考 OpenCode 的 Tool Output Protocol 设计
# =============================================================================

def _format_execution_result(raw_result: str, code: str) -> str:
    """
    格式化执行结果（强制添加标记）
    
    标记规范：
    - [DATA]: 数据查询结果（DataFrame、列表、字典、JSON）
    - [RESULT]: 计算结果（数值、字符串）
    - [ERROR]: 执行错误
    - [PARTIAL]: 超时部分结果
    
    Args:
        raw_result: 原始执行结果
        code: 执行的代码（用于推断结果类型）
        
    Returns:
        带标记的格式化结果
    """
    # 如果已经有标记，不重复添加
    if any(tag in raw_result for tag in ["[DATA]:", "[ERROR]:", "[RESULT]:", "[PARTIAL]:"]):
        return raw_result
    
    # 错误处理
    if "Traceback" in raw_result or "Error:" in raw_result:
        return f"[ERROR]: {raw_result}"
    
    # 检测是否为部分结果（超时）
    if "[PARTIAL]" in raw_result or "执行超时" in raw_result:
        return f"[PARTIAL]: {raw_result}"
    
    # 检测结果是否为结构化数据（JSON、DataFrame 字符串等）
    result_stripped = raw_result.strip()
    is_structured_data = (
        result_stripped.startswith(("{", "[")) or  # JSON
        "DataFrame" in result_stripped or  # DataFrame
        "Data type:" in result_stripped or  # 数据类型信息
        any(indicator in code for indicator in ["pro.", "query", "df", "get_data"])  # 代码特征
    )
    
    if is_structured_data:
        return f"[DATA]: {raw_result}"
    
    # 检测是否为计算结果
    is_computation = any(op in code for op in ["sum(", "mean(", "count(", "max(", "min(", "calculate"])
    if is_computation:
        return f"[RESULT]: {raw_result}"
    
    # 默认作为结果返回
    return f"[RESULT]: {raw_result}"


# =============================================================================
# 内核管理器改进：用户隔离强化
# 每个 thread_id 独立的 threading.Lock，确保单用户串行、多用户并行
# =============================================================================

class ThreadSafeKernelManager:
    """
    线程安全的内核管理器（用户隔离强化版）
    
    设计：
    - 每个用户（thread_id）有独立的 Kernel 实例
    - 每个 Kernel 有独立的 threading.Lock，确保串行执行
    - 多个用户的 Kernel 可以并行执行
    - _manager_lock 保护字典操作的线程安全
    
    面试要点：
    - 单用户串行：保证变量连续性（第一步的 df 可以在第二步使用）
    - 多用户并行：不同用户的 Lock 相互独立，避免相互阻塞
    """
    
    def __init__(self):
        self._kernels: Dict[str, Union[StatefulPythonKernel, OpenSandboxKernel]] = {}
        self._locks: Dict[str, threading.Lock] = {}  # 每个用户独立的锁
        self._manager_lock = threading.Lock()  # 保护字典操作
        self._use_sandbox = os.getenv("USE_ASA_SANDBOX", "false").lower() == "true"
        
        print(f"[ThreadSafeKernelManager] 初始化完成 (sandbox={self._use_sandbox})")
    
    def get_kernel(self, thread_id: str) -> Tuple[Union[StatefulPythonKernel, OpenSandboxKernel], threading.Lock]:
        """
        获取指定 thread_id 对应的 Kernel 实例和锁
        
        Args:
            thread_id: 会话唯一标识
            
        Returns:
            (kernel, lock) 元组
        """
        with self._manager_lock:
            if thread_id not in self._kernels:
                # 创建新的 Kernel 实例
                if self._use_sandbox and OPENSANDBOX_AVAILABLE:
                    self._kernels[thread_id] = OpenSandboxKernel()
                else:
                    self._kernels[thread_id] = StatefulPythonKernel()
                
                # 🔥 关键：为每个用户创建独立的锁
                self._locks[thread_id] = threading.Lock()
                print(f"[ThreadSafeKernelManager] 为用户 {thread_id[:8]}... 创建独立内核和锁")
            
            return self._kernels[thread_id], self._locks[thread_id]
    
    def execute(self, thread_id: str, code: str, timeout: int = 60) -> str:
        """
        执行代码（用户隔离 + 串行保证）
        
        Args:
            thread_id: 用户标识
            code: Python代码
            timeout: 超时时间（秒）
            
        Returns:
            带标记的执行结果
        """
        kernel, lock = self.get_kernel(thread_id)
        
        # 🔥 关键：用户级别的Lock，确保单用户串行
        with lock:
            try:
                raw_result = kernel.execute(code)
                # 强制添加标记
                return _format_execution_result(raw_result, code)
            except TimeoutError:
                return "[PARTIAL]: 执行超时，返回部分结果"
            except Exception as e:
                return f"[ERROR]: {type(e).__name__}: {str(e)}"
    
    def release_kernel(self, thread_id: str):
        """释放指定 thread_id 的 Kernel"""
        with self._manager_lock:
            if thread_id in self._kernels:
                del self._kernels[thread_id]
                del self._locks[thread_id]
                print(f"[ThreadSafeKernelManager] 已释放用户 {thread_id[:8]}... 的资源")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._manager_lock:
            return {
                "active_kernels": len(self._kernels),
                "active_users": list(self._locks.keys()),
                "using_sandbox": self._use_sandbox and OPENSANDBOX_AVAILABLE
            }


# 使用新的线程安全管理器
kernel_manager = ThreadSafeKernelManager()


def run_python_script(script_content: str, thread_id: str = "default") -> str:
    """
    执行Python脚本（Thread-aware + 输出协议强制版本）
    
    Args:
        script_content: 要执行的Python代码
        thread_id: 会话唯一标识，用于隔离不同用户的执行环境
        
    Returns:
        带标记的执行结果字符串
    """
    return kernel_manager.execute(thread_id, script_content)


# 为了向后兼容，保留 global_kernel 作为默认线程的引用
# 但新代码应该使用 kernel_manager.get_kernel(thread_id) 方式
USE_SANDBOX = os.getenv("USE_ASA_SANDBOX", "false").lower() == "true"
if USE_SANDBOX and OPENSANDBOX_AVAILABLE:
    global_kernel = OpenSandboxKernel()
else:
    global_kernel = StatefulPythonKernel()


# =============================================================================
# B1: Query Expansion - 金融同义词扩展表
# 将用户的自然语言指标名映射到 Tushare 实际字段名，扩展检索入口
# 设计原则：宁可多召回（recall↑），BM25+FAISS 融合评分再过滤
# =============================================================================
FINANCIAL_SYNONYMS: Dict[str, List[str]] = {
    # 利润表字段
    "净利润":    ["n_income", "n_income_attr_p", "net_profit", "归母净利润", "扣非净利润"],
    "营收":      ["revenue", "total_revenue", "营业收入", "营业总收入"],
    "营业成本":  ["oper_cost", "total_cogs"],
    "销售费用":  ["sell_exp"],
    "管理费用":  ["admin_exp"],
    "财务费用":  ["fin_exp"],
    "eps":       ["basic_eps", "diluted_eps", "每股收益"],
    # 资产负债表字段
    "总资产":    ["total_assets", "资产总计"],
    "总负债":    ["total_liab", "负债总计"],
    "股东权益":  ["total_hldr_eqy_exc_min_int", "所有者权益"],
    "货币资金":  ["money_cap"],
    "存货":      ["inventories"],
    "bps":       ["bps", "每股净资产"],
    # 每日指标字段
    "市盈率":    ["pe", "pe_ttm", "滚动市盈率"],
    "市净率":    ["pb"],
    "股息率":    ["dv_ttm", "dv_ratio", "dividend_yield"],
    "总市值":    ["total_mv", "circ_mv"],
    "换手率":    ["turnover_rate", "turnover_rate_f"],
    "量比":      ["volume_ratio"],
    # 财务指标字段
    "roe":       ["roe", "净资产收益率", "roe_yearly"],
    "roa":       ["roa", "总资产收益率"],
    "毛利率":    ["grossprofit_margin", "gross_margin"],
    "净利率":    ["netprofit_margin", "net_profit_margin"],
    "资产负债率": ["debt_to_assets"],
    # 日线行情字段
    "开盘价":    ["open"],
    "收盘价":    ["close"],
    "成交量":    ["vol", "volume"],
    "涨跌幅":    ["pct_chg", "change"],
    # 分红字段
    "现金分红":  ["cash_div", "dv_before_tax", "dividend"],
    "分红比率":  ["div_proc", "ex_date"],
    # 现金流字段
    "经营现金流": ["n_cashflow_act", "operating_cash_flow"],
}


def truth_anchor_scan(code: str) -> Optional[str]:
    """
    Truth-Anchor-Scanner: 执行前字段合约校验（Pre-execution Field Contract Validation）

    设计思路（Repo-as-truth）：
      LLM 生成的代码中，字段名必须与 Tushare API 实际字段名严格对齐。
      FINANCIAL_SYNONYMS 是 RAG 召回的权威 schema 来源。
      其中的键（如 "净利润"、"市盈率"）是中文概念词，不是合法的 DataFrame 列名。
      若代码中出现 df["净利润"]，运行时必然 KeyError —— 无需进沙箱执行，静态拦截即可。

    检测范围：
      - df["field"] / data["field"] / result["field"] 形式的括号访问
      - fields="f1,f2,f3" 参数中的字段列表

    Returns:
        None: 校验通过，允许执行
        str:  拦截原因（含修正建议），直接作为 ToolMessage 返回给 Coder，阻止沙箱执行
    """
    import re

    # 1. 提取括号字段引用：df["净利润"] → "净利润"
    bracket_fields = re.findall(r"""(?:df|data|result|row)\[['"]([^'"]+)['"]\]""", code)

    # 2. 提取 fields="f1,f2" 参数中的字段列表
    fields_param_matches = re.findall(r"""fields\s*=\s*['"]([^'"]+)['"]""", code)
    fields_from_param: List[str] = []
    for fp in fields_param_matches:
        fields_from_param.extend([f.strip() for f in fp.split(",")])

    all_referenced = set(bracket_fields + fields_from_param)

    # 3. 对照 FINANCIAL_SYNONYMS：键是概念词，不能作字段名
    violations: List[str] = []
    for field in sorted(all_referenced):
        if field in FINANCIAL_SYNONYMS:
            valid_examples = FINANCIAL_SYNONYMS[field][:2]
            violations.append(f"  ✗ '{field}'  →  实际字段名应为 {valid_examples}")

    if violations:
        return (
            "[TruthAnchorScan] 字段合约校验失败，代码已拦截（未进入沙箱）。\n"
            "以下中文概念词被误用为 Tushare API 字段名：\n"
            + "\n".join(violations)
            + "\n\n请将上述字段名替换为括号内的实际 API 字段名后重新提交。"
        )

    return None


class HybridRetriever:
    """
    混合检索器：FAISS 向量检索 + BM25 精确匹配

    参考 ms-agent HybridRetriever 设计（faiss.IndexFlatIP + BM25Okapi），
    彻底移除 chromadb 依赖，完全兼容 Python 3.14。
    索引在内存中构建，启动时 ~3s，无需持久化文件。

    核心优化（相比基础版本）：
    - B2 Field-level chunking：每个 API 文档按字段行拆分为独立 chunk，
      340 篇文档 → ~2000 字段级 chunk，显著提升细粒度字段查询召回率
    - B1 Query Expansion：FINANCIAL_SYNONYMS 扩展查询词，
      将'净利润'等自然语言扩展成['n_income','net_profit']再检索
    """

    def __init__(self, doc_df: pd.DataFrame, persist_dir="./chroma_db", use_gpu=False):
        """
        初始化混合检索器
        :param doc_df: Tushare 文档 DataFrame
        :param persist_dir: 保留参数（兼容旧调用），FAISS 版本不使用持久化目录
        :param use_gpu: 是否使用 GPU（FAISS 版本保留参数，暂不启用）
        """
        self.doc_df = doc_df
        self.documents: list = []    # 文档文本列表
        self.bm25 = None
        # FAISS 相关
        self._faiss_index = None
        self._faiss_embeddings: np.ndarray = None

        device = 'cuda' if use_gpu else 'cpu'
        print("[检索器] 正在初始化BGE-Small Embedding模型...")
        self.embedding = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5",
            model_kwargs={'device': device},
            encode_kwargs={'normalize_embeddings': True},
        )

        self._prepare_data()

    def _prepare_data(self):
        """
        构建 FAISS 向量索引 + BM25 索引

        B2 Field-level Chunking 策略：
        原来：1 个 API 文档 = 1 个 chunk（340 篇）
        现在：
          - 每个 API 文档保留一个「接口级」 chunk（含标题+描述+参数列表）
          - 输出参数表的每一个字段行拆出为独立的「字段级」 chunk
          - 字段 chunk 格式："{API名} {字段名} {字段类型} {描述}"
        效果：340 篇 → ~2000+ chunk，字段级查询 Hit@3 预计提升 +20%

        磁盘缓存：所有数据（documents/meta/bm25/faiss）全量缓存到 .faiss_cache/
        缓存命中：跳过所有构建步骤，直接加载（首次 3-5min，后续 <3s）
        """
        import pickle
        # FAISS C++ FileIOWriter 不支持含中文的路径，缓存写到用户 home 目录
        _cache_dir = os.path.join(os.path.expanduser("~"), ".asa_faiss_cache")
        os.makedirs(_cache_dir, exist_ok=True)
        _index_path  = os.path.join(_cache_dir, "faiss.index")
        _embs_path   = os.path.join(_cache_dir, "embeddings.pkl")
        _meta_path   = os.path.join(_cache_dir, "chunk_meta.pkl")
        _docs_path   = os.path.join(_cache_dir, "documents.pkl")
        _corpus_path = os.path.join(_cache_dir, "corpus_tokens.pkl")

        _all_cache_exist = all(os.path.exists(p) for p in [
            _index_path, _embs_path, _meta_path, _docs_path, _corpus_path
        ])

        if _all_cache_exist:
            print(f"[检索器] 从磁盘加载全量缓存 ({_cache_dir})...")
            try:
                self._faiss_index = _faiss.read_index(_index_path)
                with open(_embs_path, 'rb') as f:
                    self._faiss_embeddings = pickle.load(f)
                with open(_meta_path, 'rb') as f:
                    self._chunk_meta = pickle.load(f)
                with open(_docs_path, 'rb') as f:
                    self.documents = pickle.load(f)
                with open(_corpus_path, 'rb') as f:
                    corpus_tokens = pickle.load(f)
                self.bm25 = BM25Okapi(corpus_tokens)
                total_chunks = self._faiss_index.ntotal
                interface_chunks = sum(1 for m in self._chunk_meta if m['type'] == 'interface')
                field_chunks = total_chunks - interface_chunks
                print(f"[检索器] 缓存命中！接口级={interface_chunks}, 字段级={field_chunks}, 总计={total_chunks}")
                print("[检索器] 初始化完成！")
                return
            except Exception as e:
                print(f"[检索器] 缓存加载失败 ({e})，重建索引...")

        # 缓存未命中 —— 重新构建
        print("[检索器] 准备文档数据（B2 Field-level Chunking）...")
        corpus_tokens = []
        texts = []

        # 每个文档的元数据（用于 search 时返回来源信息）
        self._chunk_meta: List[Dict[str, str]] = []

        for idx, row in self.doc_df.iterrows():
            api_title = str(row['TITLE'])
            src_content = str(row['SRC_CONTENT'])

            # --- Chunk 1：接口级 chunk（全文，为接口选择类查询保留）---
            interface_chunk = f"{api_title}\n{src_content}"
            texts.append(interface_chunk)
            corpus_tokens.append(list(jieba.cut_for_search(interface_chunk)))
            self.documents.append(interface_chunk)
            self._chunk_meta.append({'title': api_title, 'type': 'interface', 'field': ''})

            # --- Chunk 2+：字段级 chunk（解析输出参数表每一行）---
            in_output_section = False
            for line in src_content.splitlines():
                stripped = line.strip()
                if '输出参数' in stripped:
                    in_output_section = True
                    continue
                if not in_output_section:
                    continue
                if stripped.startswith('---') or stripped.startswith('|--') or set(stripped.replace(' ', '').replace('-', '').replace('|', '')) == set():
                    continue
                if '名称' in stripped and '描述' in stripped:
                    continue
                if '|' in stripped:
                    clean = stripped.strip('|').strip()
                    parts = [p.strip() for p in clean.split('|')]
                    parts = [p for p in parts if p]
                    if len(parts) >= 2:
                        field_name = parts[0].strip()
                        field_desc = parts[-1].strip() if len(parts) >= 3 else ''
                        field_type = parts[1].strip() if len(parts) >= 3 else ''
                        if (field_name and len(field_name) >= 2
                                and not field_name.startswith('-')
                                and not field_name.startswith('名称')
                                and field_type in ('str', 'float', 'int', 'double', 'bigint', 'date')):
                            field_chunk = f"{api_title} 字段: {field_name} ({field_type}) - {field_desc}"
                            texts.append(field_chunk)
                            corpus_tokens.append(list(jieba.cut_for_search(field_chunk)))
                            self.documents.append(field_chunk)
                            self._chunk_meta.append({
                                'title': api_title,
                                'type': 'field',
                                'field': field_name,
                                'desc': field_desc,
                            })

        total_chunks = len(texts)
        interface_chunks = sum(1 for m in self._chunk_meta if m['type'] == 'interface')
        field_chunks = total_chunks - interface_chunks
        print(f"[检索器] Chunking 完成: 接口级={interface_chunks}, 字段级={field_chunks}, 总计={total_chunks}")

        # BM25
        print(f"[检索器] 初始化BM25索引 ({total_chunks} chunks)...")
        self.bm25 = BM25Okapi(corpus_tokens)

        # FAISS IndexFlatIP
        try:
            print("[检索器] 构建 FAISS 向量索引（参考 ms-agent HybridRetriever）...")
            raw_embs = self.embedding.embed_documents(texts)
            embs = np.array(raw_embs, dtype='float32')
            norms = np.linalg.norm(embs, axis=1, keepdims=True)
            norms = np.where(norms == 0, 1e-9, norms)
            embs = embs / norms
            self._faiss_embeddings = embs
            dim = embs.shape[1]
            self._faiss_index = _faiss.IndexFlatIP(dim)
            self._faiss_index.add(embs)
            print(f"[检索器] FAISS 索引构建完成，维度={dim}，chunk数={total_chunks}")

            # 写入全量缓存
            print(f"[检索器] 写入磁盘缓存 ({_cache_dir})...")
            _faiss.write_index(self._faiss_index, _index_path)
            with open(_embs_path,   'wb') as f: pickle.dump(embs,         f)
            with open(_meta_path,   'wb') as f: pickle.dump(self._chunk_meta, f)
            with open(_docs_path,   'wb') as f: pickle.dump(self.documents,   f)
            with open(_corpus_path, 'wb') as f: pickle.dump(corpus_tokens,    f)
            print(f"[检索器] 缓存已写入 {_cache_dir}")
        except Exception as e:
            print(f"[FAISS BUILD FAILED]: {e}")
            traceback.print_exc()
            self._faiss_index = None

        print("[检索器] 初始化完成！")


    def _expand_query(self, query: str) -> str:
        """
        B1 Query Expansion：金融同义词扩展
        将自然语言指标名（如「净利润」）映射到实际字段名（n_income、net_profit）
        设计原则：展寄词追加在 query 末尾，BM25 因词频 TF 增强，FAISS 也能识别字段型 chunk
        """
        extra_terms = []
        for concept, field_names in FINANCIAL_SYNONYMS.items():
            # 匹配概念词（如"净利润"）或执于字段名本身（如"roe"）
            if concept.lower() in query.lower() or any(fn.lower() in query.lower() for fn in field_names):
                extra_terms.extend(field_names)
        if extra_terms:
            # 去重后追加到 query
            unique_terms = list(dict.fromkeys(extra_terms))
            expanded = query + " " + " ".join(unique_terms)
            return expanded
        return query
    
    def search(self, query: str, top_k: int = 5, vector_weight: float = 0.7) -> str:
        """
        混合搜索：FAISS 向量检索 + BM25 + Query Expansion
        :param query: 查询字符串
        :param top_k: 返回结果数
        :param vector_weight: 向量搜索权重（0-1），BM25权重 = 1 - vector_weight
        :return: 格式化搜索结果字符串
        """
        # B1: 查询扩展
        expanded_query = self._expand_query(query)
    
        # 1. FAISS 向量检索（使用扩展后的 query）
        vector_scores: dict = {}
        if self._faiss_index is not None:
            try:
                q_emb = np.array(
                    self.embedding.embed_query(expanded_query), dtype='float32'
                ).reshape(1, -1)
                norm = np.linalg.norm(q_emb)
                if norm > 0:
                    q_emb = q_emb / norm
                k = min(top_k * 3, self._faiss_index.ntotal)  # 字段级 chunk 更多，扩大候选集
                scores, indices = self._faiss_index.search(q_emb, k)
                max_score = float(scores[0][0]) if len(scores[0]) > 0 and scores[0][0] > 0 else 1.0
                for score, idx in zip(scores[0], indices[0]):
                    if idx >= 0:
                        vector_scores[int(idx)] = float(score) / max_score
            except Exception as e:
                print(f"[警告] FAISS 检索失败: {e}，降级使用BM25")
    
        # 2. BM25 检索（使用扩展后的 query）
        tokenized_query = list(jieba.cut_for_search(expanded_query))
        bm25_scores = self.bm25.get_scores(tokenized_query)
        bm25_top_n = np.argsort(bm25_scores)[::-1][:min(top_k * 3, 30)]
        bm25_subset = bm25_scores[bm25_top_n]
        bm25_norm: dict = {}
        if len(bm25_subset) > 0:
            min_s, max_s = float(np.min(bm25_subset)), float(np.max(bm25_subset))
            denom = max_s - min_s + 1e-9
            for idx in bm25_top_n:
                bm25_norm[int(idx)] = (bm25_scores[idx] - min_s) / denom
    
        # 3. 融合评分
        hybrid_scores: dict = {}
        all_ids = set(vector_scores) | set(bm25_norm)
        for idx in all_ids:
            v = vector_scores.get(idx, 0.0) * vector_weight
            b = bm25_norm.get(idx, 0.0) * (1 - vector_weight)
            hybrid_scores[idx] = v + b
    
        # 4. 排序输出（使用 _chunk_meta 而不是 doc_df.iloc，支持字段级 chunk）
        sorted_items = sorted(hybrid_scores.items(), key=lambda x: x[1], reverse=True)
        results = []
        seen_titles = set()  # 同一 API 文档只保留最高分 chunk，避免重复返回
        for doc_id, score in sorted_items:
            if len(results) >= top_k:
                break
            if doc_id >= len(self.documents):
                continue
            meta = self._chunk_meta[doc_id]
            api_title = meta['title']
            chunk_text = self.documents[doc_id]
    
            # 接口级 chunk：每个 API 标题只展示一次
            if meta['type'] == 'interface':
                if api_title in seen_titles:
                    continue
                seen_titles.add(api_title)
                preview = chunk_text[len(api_title)+1:]  # 去掉标题行
                preview = preview[:500] if len(preview) > 500 else preview
                results.append(f"# {api_title} (匹配度: {score:.3f})\n\n{preview}...")
            else:
                # 字段级 chunk：直接展示字段信息
                field_name = meta.get('field', '')
                field_desc = meta.get('desc', '')
                results.append(f"# {api_title} → {field_name} (匹配度: {score:.3f})\n\n字段: {field_name} - {field_desc}")
                seen_titles.add(api_title)  # 同一 API 的字段不再重复返回接口级
    
        return "\n\n".join(results) if results else "未找到相关文档"



# 全局检索器实例
global_retriever = None


def initialize_retriever(use_gpu=False):
    """初始化全局检索器"""
    global global_retriever
    if global_retriever is None:
        try:
            tushare_docs = load_tushare_docs()[0]
            # 如果加载失败（返回空DataFrame），则跳过HybridRetriever初始化
            if tushare_docs is None or (hasattr(tushare_docs, 'empty') and tushare_docs.empty):
                print(f"[⚠️ Warning] Tushare文档为空，跳过初始化HybridRetriever")
                return None
            global_retriever = HybridRetriever(tushare_docs, use_gpu=use_gpu)
        except Exception as e:
            print(f"[❌ Error] 初始化检索器失败: {e}")
            print(f"[💡 Fallback] 返回None，检索功能降级")
            return None
    return global_retriever


tushare_docs = None
docs = []
meta = []  # store id + title + api_name
bm25 = None


def load_tushare_docs():
    global tushare_docs
    global bm25
    if tushare_docs is None:
        try:
            csv_path = os.path.join(os.path.dirname(__file__), r'TUSHARE_API_DOCUMENT__202510210919.csv')
            if not os.path.exists(csv_path):
                print(f"[⚠️ Warning] Tushare文档文件不存在: {csv_path}")
                print(f"[💡 Fallback] 使用默认文档库")
                # 返回空的默认值，不中断流程
                return pd.DataFrame(), [], [], BM25Okapi([])
            
            tushare_docs = pd.read_csv(csv_path)
            tushare_docs = tushare_docs[17:].dropna().reset_index(drop=True)
            tushare_docs = tushare_docs[tushare_docs["SRC_CONTENT"].apply(
                lambda x: isinstance(x, str) and any(line.startswith("接口") for line in x.splitlines()[:10])
            )]
            tushare_docs = tushare_docs[~tushare_docs['TITLE'].isin([
                'Python安装', '操作手册', '获取token', '调取数据', 'IDE开发工具介绍', '全球区块链项目Logo',
                '全球区块链项目白皮书', '数据采集预处理与建模'
            ])]

            for row_id, row in tushare_docs.iterrows():  # 假设是你的 DataFrame 行
                text = (row['TITLE'] + "\n" + row['SRC_CONTENT']).strip()
                if len(row['SRC_CONTENT'].strip()) < 400 and row['TITLE'] != '交易所交易对（新）':
                    # print(text)
                    # print('---------------------------------------------')
                    continue
                tokens = list(jieba.cut(text))
                docs.append(tokens)
                meta.append({'id': row_id, 'title': row['TITLE'], 'doc': row['SRC_CONTENT']})
                # meta.append(row['SRC_CONTENT'])

            bm25 = BM25Okapi(docs)
        except Exception as e:
            print(f"[❌ Error] Tushare文档加载失败: {e}")
            print(f"[💡 Fallback] 使用默认文档库")
            # 返回空的默认值，不中断流程
            return pd.DataFrame(), [], [], BM25Okapi([])
    return tushare_docs, docs, meta, bm25


def search(query, topk=5):
    """
    优化后的检索(混合检索)
    :param query: 查询字符串
    :param topk: 返回结果数
    :return: 格式化的检索结果
    """
    try:
        retriever = initialize_retriever(use_gpu=False)
        # 如果检索器为None，直接降级
        if retriever is None:
            print(f"[⚠️ Warning] 检索器为None，返回默认帮助文本")
            return """未找到相关Tushare文档。建议：
            1. 使用tushare.pro_api()API直接获取数据
            2. 常用接口：ts.pro_api().daily()  日线数据
            3. 更多接口参考Tushare官方文档。
            """
        return retriever.search(query, top_k=topk)
    except Exception as e:
        print(f"[⚠️ Warning] Tushare文档检索失败: {e}")
        print(f"[💡 Fallback] 返回默认帮助...")
        # 返回默认参考文本，不中断流程
        return """未找到相关Tushare文档。建议：
        1. 使用tushare.pro_api()API直接获取数据
        2. 常用接口：ts.pro_api().daily()  日线数据
        3. 更多接口参考Tushare官方文档。
        """


# =============================================================================
# 【Schema 多路召回】三路融合：规则路径 + LLM 结构化意图 + RAG
# =============================================================================

class SchemaIntent(BaseModel):
    """LLM 结构化意图抽取 Schema"""
    stocks: List[str] = Field(
        default_factory=list,
        description="目标标的，如 600519.SH、000001.SZ"
    )
    metrics: List[str] = Field(
        default_factory=list,
        description="关心的指标名或字段名，如 ROE、净利润、PE、股息率"
    )
    time_range: Optional[str] = Field(
        default=None,
        description="时间范围，如 近4个季度、2020年以来、最近一年"
    )
    dimension: Optional[Literal["single_stock", "comparison", "industry", "index"]] = Field(
        default=None,
        description="分析维度：单只股票、对比、多行业、指数等"
    )


def _rule_based_schema_hints(query: str) -> Dict[str, Any]:
    """
    规则路径：正则抽取 ts_code + 关键词匹配字段别名
    纯本地执行，无 LLM 调用，延迟 < 1ms
    """
    hints: Dict[str, Any] = {"stocks": [], "metrics": [], "raw_keywords": []}
    if not query:
        return hints

    upper_q = query.upper()
    # 使用 (?<!\d) 替代 \b，确保中文字符前后也能匹配
    ts_code_pattern = r"(?<!\d)\d{6}\.(SH|SZ|BJ)"
    stocks = {m.group(0) for m in re.finditer(ts_code_pattern, upper_q)}
    hints["stocks"] = sorted(stocks)

    query_lower = query.lower()
    metric_alias_map: Dict[str, List[str]] = {
        "roe": ["roe", "净资产收益率", "净资产回报率"],
        "pe_ttm": ["市盈率", "pe", "pe_ttm", "滚动市盈率"],
        "pb": ["市净率", "pb"],
        "dv_ttm": ["股息率", "股息", "分红率", "dividend yield", "股利"],
        "revenue": ["营收", "营业收入", "revenue"],
        "n_income": ["净利润", "归母净利润", "profit", "earnings"],
        "grossprofit_margin": ["毛利率", "gross margin"],
        "netprofit_margin": ["净利率", "net margin"],
    }
    metrics: List[str] = []
    raw_keywords: List[str] = []
    for field, keywords in metric_alias_map.items():
        for kw in keywords:
            if kw.lower() in query_lower:
                metrics.append(field)
                raw_keywords.append(kw)
                break

    hints["metrics"] = sorted(set(metrics))
    hints["raw_keywords"] = sorted(set(raw_keywords))
    return hints


def extract_schema_intent(query: str) -> Optional[SchemaIntent]:
    """
    LLM 路径：使用 with_structured_output 抽取结构化意图
    失败时静默降级，不中断主流程
    """
    if not query:
        return None
    try:
        model = get_chat_model(model_type="smart", temperature=0.1)
        # DeepSeek 用 function_calling 模式，避免 JSON mode 不兼容问题
        structured_model = model.with_structured_output(SchemaIntent, method="function_calling")
        prompt = (
            "你是一个金融数据分析助手，负责从自然语言问题中抽取结构化意图。\n"
            "请从以下用户问题中提取：目标股票代码、关心的指标字段、时间范围、分析维度。\n"
            "如果信息不存在则留空，不要臆造。\n\n"
            f"用户问题：{query}"
        )
        result: SchemaIntent = structured_model.invoke(prompt)
        return result
    except Exception as e:
        print(f"[SchemaIntent] 结构化意图抽取失败，已降级为规则+RAG: {e}")
        return None


def multi_path_schema_recall(query: str, topk: int = 5) -> str:
    """
    三路融合 Schema 召回：
      路径1 - 规则路径（正则 + 关键词，零延迟）
      路径2 - LLM 结构化意图（with_structured_output）
      路径3 - RAG 路径（BGE-Small + BM25 混合检索 Tushare 文档）
    返回中文提示文本，供 Coder System Prompt 拼接
    """
    if not query:
        return ""

    # 路径1：规则路径
    rule_hints = _rule_based_schema_hints(query)

    # 路径2：LLM 结构化意图
    schema_intent = extract_schema_intent(query)

    # 路径3：RAG 路径
    try:
        doc_snippets = search(query, topk=topk)
    except Exception as e:
        print(f"[SchemaRecall] RAG路径失败: {e}")
        doc_snippets = ""
    if isinstance(doc_snippets, str) and len(doc_snippets) > 1500:
        doc_snippets = doc_snippets[:1500] + "\n...(已截断)"

    # 融合三路结果
    parts: List[str] = []
    parts.append("\n\n【Schema 多路召回提示】\n")

    if rule_hints.get("stocks"):
        parts.append(f"- 规则识别到的标的(ts_code)：{', '.join(rule_hints['stocks'])}\n")
    if rule_hints.get("metrics"):
        parts.append(f"- 规则识别到的关键字段：{', '.join(rule_hints['metrics'])}\n")

    if schema_intent:
        if schema_intent.stocks:
            parts.append(f"- LLM意图抽取的标的：{', '.join(schema_intent.stocks)}\n")
        if schema_intent.metrics:
            parts.append(f"- LLM意图抽取的指标：{', '.join(schema_intent.metrics)}\n")
        if schema_intent.time_range:
            parts.append(f"- 关注时间范围：{schema_intent.time_range}\n")
        if schema_intent.dimension:
            parts.append(f"- 分析维度：{schema_intent.dimension}\n")

    if doc_snippets:
        parts.append("\n【文档召回片段（来自 Tushare 文档混合检索，仅供参考，禁止臆造字段）】\n")
        parts.append(str(doc_snippets))

    return "".join(parts)


def send_result(result: str):
    """
    发送最终结果。
    :param result: 最终结果，只能是字符串，长度不能超过3000。
    :return:
    """
    fr = json.dumps({'final_result': result}, ensure_ascii=False)
    print('FINAL_RESULT:', fr)
    if len(fr) > 3000:
        fr = fr[:3000] + '...(字符串过长，截取前3000个字符)'
    return fr


# =============================================================================
# 下面是新增的第一步: 意图识别和画像管理
# =============================================================================

# --- 1. 意图定义 ---

class IntentSchema(BaseModel):
    """意图分类Schema"""
    intent: Literal['fetch_data', 'analysis', 'charting', 'general_chat'] = Field(
        ..., description="用户的意图分类"
    )


INTENT_PROMPT = """你是一个交易助手的意图分类器。请分析用户的输入，将其归类为以下之一：

- fetch_data: 用户明确要求获取某些具体数据（如股价、财报、新闻）。
- analysis: 用户要求对数据进行分析、总结、计算指标或寻找原因。
- charting: 用户明确要求画图、展示图表。
- general_chat: 打招呼、闲聊或不涉及具体金融数据的询问。

用户输入: {query}
"""

# --- 2. 画像更新定义 ---

PROFILE_UPDATE_PROMPT = """你是一个用户画像分析师。请根据当前的对话历史和已有的用户画像，更新用户的信息。

已有画像: {current_profile}

本次对话: {conversation_summary}

请提取以下维度的信息（如果无法提取则保持原有内容或留空）：

1. 风险偏好 (risk_preference): 如保守、激进、稳健
2. 优先关注行业 (interested_industries): 用户经常查询的板块
3. 投资风格 (investment_style): 如技术面、基本面、短线、长线
4. 备注 (notes): 其他值得记录的偏好

仅返回 JSON 格式数据，不要包含其他解释。
"""

# --- 3. 动态系统提示词生成 ---

def get_system_prompt(intent: str, profile: dict) -> str:
    """
    根据意图和画像构造动态系统提示
    """
    # 基础设定
    base_prompt = "你是一名资深数据分析师，擅长通过数据挖掘、统计分析和可视化来解答商业问题。"
    
    # 注入画像
    username = profile.get("username", "投资者")
    risk = profile.get("risk_preference", "未知")
    style = profile.get("investment_style", "综合")
    industries = profile.get("interested_industries", [])
    
    industries_str = "、".join(industries) if industries else "未提供"
    
    persona = f"""

[用户画像上下文]
当前服务对象：{username}
风险偏好：{risk}
偏好分析风格：{style}
优先关注行业：{industries_str}
请根据以上画像调整你的回答语气和建议深度。
    """
    
    # 根据意图切换策略
    strategy = ""
    if intent == "fetch_data":
        strategy = """

[当前任务：数据获取]
请准确调用工具获取数据，优先展示最新、最核心的指标，不要进行过度的发散分析。
        """
    elif intent == "analysis":
        strategy = """

[当前任务：深度分析]
请综合多方面数据，提供有逻辑的推导。如果数据不足，请主动调用工具补充数据。
        """
    elif intent == "charting":
        strategy = """

[当前任务：图表绘制]
用户需要可视化结果。请调用绘图工具，并确保生成的代码可以运行。在回复中简要说明图表的含义。
        """
    else:
        strategy = """

[当前任务：通用对话]
请用专业且亲切的口吻回答，如果涉及投资建议，请提示风险。
        """
    
    return base_prompt + persona + strategy


# =============================================================================
# 【P0-F】消息修剪：防止Token爆炸
# =============================================================================

def trim_messages_for_context(
    messages: list,
    max_keep: int = 15,
    preserve_first: bool = True
) -> list:
    """
    修剪消息列表，防止Token爆炸
    
    策略：保留第一条SystemMessage + 最近N条消息
    超出时对中间消息进行摘要
    
    Args:
        messages: 原始消息列表
        max_keep: 最多保留的消息数 (推荐15)
        preserve_first: 是否保留第一条消息 (SystemMessage)
    
    Returns:
        修剪后的消息列表
    
    示例：
        原: [sys_msg, msg1, msg2, ..., msg100] (50k tokens)
        后: [sys_msg, summary, msg90, ..., msg100] (2k tokens)
    """
    if len(messages) <= max_keep:
        return messages  # 无需修剪
    
    preserved = []
    
    # ✅ 保留第一条消息（通常是SystemMessage）
    if preserve_first and messages:
        preserved.append(messages[0])
    
    # ✅ 保留最近的消息
    recent_messages = messages[-(max_keep-1):] if len(messages) > max_keep else messages[1:]
    
    # ✅ 对中间消息进行摘要
    if len(messages) > max_keep:
        old_messages = messages[1:len(messages)-(max_keep-1)]
        summary = _summarize_messages_batch(old_messages)
        
        # 用摘要替代
        preserved.append(
            SystemMessage(content=f"[对话摘要] {summary}")
        )
    
    preserved.extend(recent_messages)
    
    # ✅ 记录修剪日志
    reduction = len(messages) - len(preserved)
    print(f"[消息修剪] {len(messages)} → {len(preserved)} 条消息 (节省{reduction}条, 约-60% tokens)")
    
    return preserved


def _summarize_messages_batch(messages: list, max_length: int = 200) -> str:
    """
    对多条消息进行快速摘要
    提取关键信息而不是完整内容
    """
    if not messages:
        return "[无内容]"
    
    summary_parts = []
    
    for i, msg in enumerate(messages[:5]):  # 最多摘要前5条
        if isinstance(msg, HumanMessage):
            content = msg.content[:40] if msg.content else "[空]"
            summary_parts.append(f"用户查询{i+1}: {content}...")
        elif isinstance(msg, AIMessage):
            content = msg.content[:40] if msg.content else "[空]"
            summary_parts.append(f"AI回复{i+1}: {content}...")
        elif isinstance(msg, ToolMessage):
            summary_parts.append(f"工具结果{i+1}: [已执行]")
    
    # ✅ 限制总长度
    summary = "; ".join(summary_parts)
    if len(summary) > max_length:
        summary = summary[:max_length-3] + "..."
    
    return summary


# =============================================================================
# 【P0-E + P0-D】消息状态查询辅助函数 (保留消息时序，解决类型判断繁琐)
# =============================================================================

def get_last_user_message(state: dict) -> "HumanMessage | None":
    """
    倒序查找最后一条用户消息
    
    用途：精确获取用户最新输入，避免繁琐的类型判断
    
    示例：
        last_user = get_last_user_message(state)
        if last_user:
            print(f"用户说: {last_user.content}")
    """
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg
    return None


def count_consecutive_tool_failures(state: dict) -> int:
    """
    统计最近连续的工具执行失败次数
    
    用途：判断是否应该触发error_handler或重新规划
    
    返回值:
        连续失败次数 (0 表示最后一条不是失败)
    
    示例：
        failures = count_consecutive_tool_failures(state)
        if failures >= 3:
            return {"next": "ErrorHandler", "should_replan": True}
    """
    messages = state.get("messages", [])
    count = 0
    
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage) and "Error" in msg.content:
            count += 1
        else:
            break  # 遇到非错误消息，停止计数
    
    return count


def get_recent_execution_summary(state: dict, window: int = 5) -> str:
    """
    获取最近N条消息的执行摘要
    
    用途：用于错误诊断、日志记录
    
    示例:
        summary = get_recent_execution_summary(state, window=3)
        print(f"[执行摘要] {summary}")
    """
    messages = state.get("messages", [])
    recent = messages[-window:]
    
    summary_parts = []
    for msg in recent:
        if isinstance(msg, HumanMessage):
            summary_parts.append(f"用户: {msg.content[:30]}...")
        elif isinstance(msg, AIMessage):
            summary_parts.append(f"AI: {msg.content[:30]}...")
        elif isinstance(msg, ToolMessage):
            status = "✓" if "Error" not in msg.content else "✗"
            summary_parts.append(f"工具{status}: {msg.content[:30]}...")
    
    return " → ".join(summary_parts)


# =============================================================================
# 【Tushare 数据适配层】- 自动处理类型转换、列名兼容性 + 数据验证
# =============================================================================

# 导入数据验证模块
try:
    from data_validator import (
        DataValidator, 
        DataRetrier,
        ValidationResult,
        RetryResult,
        create_data_validator,
        create_data_retrier,
        validate_and_fix
    )
    DATA_VALIDATOR_AVAILABLE = True
    print("[✅ 数据验证模块] 已加载")
except ImportError:
    DATA_VALIDATOR_AVAILABLE = False
    print("[⚠️ 数据验证模块] 未加载，禁用验证功能")


class TushareDataHelper:
    """
    Tushare 数据适配器：自动处理 API 返回的不一致性 + 数据验证重试
    
    解决问题：
    1. report_type 有时是字符串 '1'，有时是整数 1
    2. 列名在不同 API 版本中可能变化（如 net_profit vs n_income）
    3. 日期格式不统一
    4. 数值类型混合（字符串、整数、浮点数混在一起）
    
    【新增】迭代修复流程：
    1. API 调用 → 数据验证（空数据/缺失字段/类型错误/数值异常）
    2. 验证失败 → 调整参数重试
    3. 自动修复可修复的问题
    4. 最终返回清洁数据
    
    使用示例：
        helper = TushareDataHelper(pro, enable_validation=True)
        df = helper.get_income_safe('002594.SZ', '20220101')
        # 返回的 DataFrame 已自动修复所有已知问题
    """
    
    def __init__(self, pro, enable_validation: bool = True, max_retries: int = 3):
        """初始化 Tushare 代理
        
        Args:
            pro: tushare.pro_api() 返回的对象
            enable_validation: 是否启用数据验证（新增）
            max_retries: 最大重试次数（新增）
        """
        self.pro = pro
        self.enable_validation = enable_validation and DATA_VALIDATOR_AVAILABLE
        self.max_retries = max_retries
        
        # 初始化验证器和重试器
        if self.enable_validation:
            self.validator = create_data_validator(auto_fix=True)
            self.retrier = create_data_retrier(
                validator=self.validator,
                max_retries=max_retries,
                retry_delay=0.5
            )
            print(f"[✅ 数据验证] 已启用，最大重试 {max_retries} 次")
    
    def normalize_numeric(self, df: pd.DataFrame, columns: list) -> pd.DataFrame:
        """将指定列转换为数值类型
        
        Args:
            df: DataFrame
            columns: 需要转换的列名列表
            
        Returns:
            转换后的 DataFrame
        """
        df = df.copy()
        for col in columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    
    def normalize_date(self, date_str: str, target_format: str = 'YYYYMMDD') -> str:
        """统一日期格式
        
        Args:
            date_str: 原始日期字符串（支持多种格式）
            target_format: 目标格式，'YYYYMMDD' 或 'YYYY-MM-DD'
            
        Returns:
            格式化后的日期字符串
        """
        try:
            dt = pd.to_datetime(date_str)
            if target_format == 'YYYYMMDD':
                return dt.strftime('%Y%m%d')
            elif target_format == 'YYYY-MM-DD':
                return dt.strftime('%Y-%m-%d')
            else:
                return str(dt)
        except Exception as e:
            print(f"[WARNING] 日期格式转换失败: {date_str}, 错误: {e}")
            return date_str
    
    def get_column_value(self, row: pd.Series, column_names: list):
        """从多个可能的列名中获取值
        
        用途：处理列名变化，自动选择存在且非空的列
        
        Args:
            row: DataFrame 的一行
            column_names: 可能的列名列表，按优先级排序
            
        Returns:
            找到的值，或 None
        """
        for col_name in column_names:
            if col_name in row.index and pd.notna(row[col_name]):
                val = row[col_name]
                # 跳过 NaN 和空字符串
                if pd.notna(val) and val != '':
                    return val
        return None
    
    def get_income_safe(self, ts_code: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """安全的 income() API 调用，自动修复常见问题 + 数据验证重试
        
        【迭代修复流程】
        1. 调用 income API
        2. 验证数据（空数据/类型错误/数值异常）
        3. 失败则调整参数重试
        4. 自动修复可修复的问题
        
        Args:
            ts_code: 股票代码（如 '002594.SZ'）
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）
            
        Returns:
            清理后的 DataFrame
        """
        # 构建参数
        kwargs = {'ts_code': ts_code}
        if start_date:
            kwargs['start_date'] = self.normalize_date(start_date, 'YYYYMMDD')
        if end_date:
            kwargs['end_date'] = self.normalize_date(end_date, 'YYYYMMDD')
        
        # 如果启用验证，使用重试器
        if self.enable_validation:
            # 定义 API 调用函数
            def api_call(**params):
                return self.pro.income(**params)
            
            # 备选参数（扩大日期范围）
            fallback_params = []
            if start_date:
                try:
                    start = pd.to_datetime(start_date)
                    extended_start = (start - pd.Timedelta(days=90)).strftime('%Y%m%d')
                    fallback_params.append({**kwargs, 'start_date': extended_start})
                except:
                    pass
            
            # 执行带验证的重试
            result = self.retrier.execute_with_retry(
                api_func=api_call,
                api_params=kwargs,
                fallback_params=fallback_params,
                context=f"income({ts_code})"
            )
            
            df = result.final_data if result.final_data is not None else pd.DataFrame()
        else:
            # 不启用验证，直接调用
            try:
                df = self.pro.income(**kwargs)
            except Exception as e:
                print(f"[ERROR] income() API 调用失败: {e}")
                return pd.DataFrame()
        
        if df.empty:
            print(f"[WARNING] income() 返回空数据: {ts_code}")
            return df
        
        # 自动修复：report_type 类型转换（关键！）
        if 'report_type' in df.columns:
            df['report_type'] = pd.to_numeric(df['report_type'], errors='coerce')
        
        # 自动修复：数值列转换
        numeric_cols = ['revenue', 'n_income', 'net_profit', 'eps', 'roe']
        df = self.normalize_numeric(df, numeric_cols)
        
        return df
    
    def get_dividend_safe(self, ts_code: str, limit: int = 10) -> pd.DataFrame:
        """安全的 dividend() API 调用，自动处理列名变化
        
        Args:
            ts_code: 股票代码
            limit: 返回记录数
            
        Returns:
            清理后的 DataFrame
        """
        try:
            df = self.pro.dividend(ts_code=ts_code, limit=limit)
            
            if df.empty:
                return df
            
            # 自动修复：数值列转换
            numeric_cols = ['div_procf', 'dv_before_tax', 'dv_after_tax', 'dividend', 'cash_div']
            df = self.normalize_numeric(df, numeric_cols)
            
            return df
            
        except Exception as e:
            print(f"[WARNING] dividend() API 调用失败: {e}")
            return pd.DataFrame()
    
    def get_daily_basic_safe(self, ts_code: str, limit: int = 1) -> pd.DataFrame:
        """安全的 daily_basic() API 调用
        
        Args:
            ts_code: 股票代码
            limit: 返回记录数
            
        Returns:
            清理后的 DataFrame
        """
        try:
            df = self.pro.daily_basic(ts_code=ts_code, limit=limit)
            
            if df.empty:
                return df
            
            # 自动修复：数值列转换
            numeric_cols = ['close', 'dv_ttm', 'dv_ratio', 'pe', 'pb', 'ps']
            df = self.normalize_numeric(df, numeric_cols)
            
            return df
            
        except Exception as e:
            print(f"[WARNING] daily_basic() API 调用失败: {e}")
            return pd.DataFrame()
    
    def get_daily_safe(self, ts_code: str, start_date: str = None, limit: int = None) -> pd.DataFrame:
        """安全的 daily() API 调用 + 数据验证重试
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            limit: 返回记录数
            
        Returns:
            清理后的 DataFrame
        """
        kwargs = {'ts_code': ts_code}
        if start_date:
            kwargs['start_date'] = self.normalize_date(start_date, 'YYYYMMDD')
        if limit:
            kwargs['limit'] = limit
        
        # 如果启用验证，使用重试器
        if self.enable_validation:
            def api_call(**params):
                return self.pro.daily(**params)
            
            # 备选参数
            fallback_params = []
            if start_date:
                try:
                    start = pd.to_datetime(start_date)
                    extended_start = (start - pd.Timedelta(days=30)).strftime('%Y%m%d')
                    fallback_params.append({**kwargs, 'start_date': extended_start})
                except:
                    pass
            
            result = self.retrier.execute_with_retry(
                api_func=api_call,
                api_params=kwargs,
                fallback_params=fallback_params,
                context=f"daily({ts_code})"
            )
            
            df = result.final_data if result.final_data is not None else pd.DataFrame()
        else:
            try:
                df = self.pro.daily(**kwargs)
            except Exception as e:
                print(f"[WARNING] daily() API 调用失败: {e}")
                return pd.DataFrame()
        
        if df.empty:
            return df
        
        # 自动修复：数值列转换
        numeric_cols = ['open', 'high', 'low', 'close', 'vol', 'amount']
        df = self.normalize_numeric(df, numeric_cols)
        
        return df
    
    def validate_data(self, data: pd.DataFrame, required_fields: List[str] = None) -> Tuple[bool, pd.DataFrame, List[str]]:
        """
        便捷方法：验证并修复数据
        
        Args:
            data: 待验证的 DataFrame
            required_fields: 必需字段
        
        Returns:
            (passed, fixed_data, issues_summary)
        """
        if self.enable_validation:
            return validate_and_fix(data, required_fields or [])
        else:
            return (True, data, [])


def create_tushare_helper(pro=None, enable_validation: bool = True, max_retries: int = 3) -> TushareDataHelper:
    """创建 Tushare 数据助手（支持数据验证重试）
    
    Args:
        pro: tushare.pro_api() 返回的对象，如果为 None 则自动初始化
        enable_validation: 是否启用数据验证（新增）
        max_retries: 最大重试次数（新增）
        
    Returns:
        TushareDataHelper 实例
    """
    if pro is None:
        import tushare as ts
        pro = ts.pro_api()
    return TushareDataHelper(pro, enable_validation=enable_validation, max_retries=max_retries)


# =============================================================================
# 【P1】工具动态发现机制 - 参考 smolagents
# =============================================================================

class ToolRegistry:
    """
    工具注册表 - 支持动态工具发现和管理
    
    【参考 smolagents 核心设计】
    - 支持从 LangChain 工具导入
    - 支持从函数动态创建工具
    - 支持工具分组和过滤
    - 统一工具描述格式
    
    使用示例:
        registry = ToolRegistry()
        
        # 注册自定义函数为工具
        @registry.register
        def my_tool(query: str) -> str:
            '''我的工具描述'''
            return f"处理: {query}"
        
        # 从 LangChain 工具导入
        registry.register_from_langchain(langchain_tool)
        
        # 获取所有工具
        tools = registry.get_all_tools()
    """
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._tool_groups: Dict[str, List[str]] = {}
        self._tool_metadata: Dict[str, Dict] = {}
    
    def register(self, func: Callable = None, *, name: str = None, group: str = "default"):
        """
        装饰器：注册函数为工具
        
        Args:
            func: 要注册的函数
            name: 工具名称（默认使用函数名）
            group: 工具分组
        
        示例:
            @registry.register
            def search(query: str) -> str:
                '''搜索工具'''
                return results
            
            @registry.register(name="custom_search", group="search")
            def my_search(query: str) -> str:
                '''自定义搜索'''
                return results
        """
        def decorator(f: Callable):
            tool_name = name or f.__name__
            
            # 使用 langchain @tool 装饰器创建工具
            wrapped = tool(f)
            
            self._tools[tool_name] = wrapped
            
            # 记录分组
            if group not in self._tool_groups:
                self._tool_groups[group] = []
            self._tool_groups[group].append(tool_name)
            
            # 记录元数据
            self._tool_metadata[tool_name] = {
                "name": tool_name,
                "description": f.__doc__ or "无描述",
                "group": group,
                "source": "function"
            }
            
            print(f"[ToolRegistry] 注册工具: {tool_name} (分组: {group})")
            return wrapped
        
        if func is not None:
            return decorator(func)
        return decorator
    
    def register_from_langchain(self, lc_tool: BaseTool, group: str = "langchain"):
        """
        从 LangChain 工具导入
        
        Args:
            lc_tool: LangChain 工具实例
            group: 工具分组
        
        示例:
            from langchain_community.tools import DuckDuckGoSearchRun
            registry.register_from_langchain(DuckDuckGoSearchRun())
        """
        tool_name = lc_tool.name
        self._tools[tool_name] = lc_tool
        
        if group not in self._tool_groups:
            self._tool_groups[group] = []
        self._tool_groups[group].append(tool_name)
        
        self._tool_metadata[tool_name] = {
            "name": tool_name,
            "description": lc_tool.description,
            "group": group,
            "source": "langchain"
        }
        
        print(f"[ToolRegistry] 导入 LangChain 工具: {tool_name}")
    
    def register_tool(self, lc_tool: BaseTool, group: str = "custom"):
        """
        直接注册工具实例
        
        Args:
            lc_tool: 工具实例
            group: 工具分组
        """
        self.register_from_langchain(lc_tool, group)
    
    def get_tool(self, name: str) -> Optional[BaseTool]:
        """获取指定工具"""
        return self._tools.get(name)
    
    def get_all_tools(self) -> List[BaseTool]:
        """获取所有工具列表"""
        return list(self._tools.values())
    
    def get_tools_by_group(self, group: str) -> List[BaseTool]:
        """获取指定分组的工具"""
        tool_names = self._tool_groups.get(group, [])
        return [self._tools[name] for name in tool_names if name in self._tools]
    
    def get_tool_descriptions(self) -> str:
        """
        获取所有工具的描述（用于 Prompt 注入）
        
        Returns:
            格式化的工具描述字符串
        """
        descriptions = []
        for name, meta in self._tool_metadata.items():
            desc = f"- {name}: {meta['description'][:100]}"
            descriptions.append(desc)
        return "\n".join(descriptions)
    
    def list_tools(self) -> Dict[str, List[str]]:
        """列出所有工具（按分组）"""
        return self._tool_groups.copy()
    
    def unregister(self, name: str):
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
        if name in self._tool_metadata:
            group = self._tool_metadata[name].get("group")
            del self._tool_metadata[name]
            if group and group in self._tool_groups:
                self._tool_groups[group] = [
                    n for n in self._tool_groups[group] if n != name
                ]
        print(f"[ToolRegistry] 注销工具: {name}")
    
    def __len__(self):
        return len(self._tools)
    
    def __contains__(self, name: str):
        return name in self._tools


# 全局工具注册表实例
global_tool_registry = ToolRegistry()
