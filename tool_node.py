#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Standardized Tool Node with Permission Control & Output Middleware
=================================================================
Reference:
  - langgraph-supervisor-py: Tool-based agent handoff
  - OpenCode agent.tools: Per-agent tool permission
  - TradingAgents(Tauric): Agent pool tool binding
  - fin-agent(YUHAI0): Structured output validation ([DATA]: marker)
  - Microsoft Agent Governance Toolkit: Zero-trust middleware

Components:
  PermissionControlledTool  - tool wrapper with agent-level allow/deny
  ToolCallMiddleware        - pre-execution permission gate (NEW)
  DataOutputValidator       - post-execution [DATA]: format enforcer (NEW)
  ASAToolNode               - unified execution entry point
  create_agent_with_tools   - factory using YAML-driven permissions
"""

from typing import Dict, List, Any, Optional, Tuple
from functools import wraps
from langchain_core.tools import BaseTool, tool
from langchain_core.messages import ToolMessage
from langgraph.prebuilt import ToolNode as LangGraphToolNode


class PermissionControlledTool:
    """
    Tool wrapper with agent-level permission control
    Reference: OpenCode agent.tools config
    """
    
    def __init__(
        self,
        tool: BaseTool,
        allowed_agents: List[str],
        rate_limit: Optional[int] = None
    ):
        self.tool = tool
        self.allowed_agents = set(allowed_agents)
        self.rate_limit = rate_limit
        self.call_count = 0
    
    def can_execute(self, agent_name: str) -> bool:
        """Check if agent has permission to use this tool"""
        if agent_name not in self.allowed_agents:
            return False
        if self.rate_limit and self.call_count >= self.rate_limit:
            return False
        return True
    
    def execute(self, *args, **kwargs) -> Any:
        """Execute tool with rate limiting"""
        self.call_count += 1
        return self.tool.invoke(*args, **kwargs)


class ToolCallMiddleware:
    """
    Pre-execution permission gate (middleware pattern)

    工具调用前的权限阈门检查，参考 Microsoft Agent Governance Toolkit 中间件思路。

    查找顺序（参考 OpenCode tools 配置 + TradingAgents agent_pool）:
      1. 先检查 YAML denied 列表（确定性禁止）
      2. 再检查 YAML allowed 列表（必须在内才允许）
      3. 通过则返回 None，否则返回拒绝的 ToolMessage
    """

    def __init__(self):
        # 延迟导入，避免循环依赖
        self._factory = None

    def _get_factory(self):
        if self._factory is None:
            try:
                from loader import agent_factory
                self._factory = agent_factory
            except Exception:
                self._factory = None
        return self._factory

    def check(
        self,
        agent_name: str,
        tool_name: str,
        tool_call_id: str
    ) -> Optional[ToolMessage]:
        """
        执行权限检查

        Args:
            agent_name: 发起工具调用的 Agent 名称
            tool_name:  被调用的工具名
            tool_call_id: LangGraph ToolCall ID

        Returns:
            None   → 权限通过，继续执行
            ToolMessage → 权限拒绝，直接返回错误
        """
        factory = self._get_factory()
        if factory is None:
            # 无法加载配置，降级为放行（兼容旧逻辑）
            return None

        try:
            can_use = factory.can_use_tool(agent_name, tool_name)
        except Exception:
            # 配置读取失败，降级为放行
            return None

        if not can_use:
            agent_cfg = None
            try:
                agent_cfg = factory.loader.get_agent(agent_name)
            except Exception:
                pass

            denied = (agent_cfg.tools.denied if agent_cfg else [])
            allowed = (agent_cfg.tools.allowed if agent_cfg else [])

            if tool_name in denied:
                reason = f"tool '{tool_name}' is explicitly denied for agent '{agent_name}'"
            elif allowed and tool_name not in allowed:
                reason = f"tool '{tool_name}' is not in allowed list {allowed} for agent '{agent_name}'"
            else:
                reason = f"agent '{agent_name}' has no tool permissions"

            print(f"[ToolCallMiddleware] BLOCKED: {reason}")
            return ToolMessage(
                content=f"[PERMISSION DENIED] {reason}",
                tool_call_id=tool_call_id,
                name=tool_name
            )

        return None  # 通过


class DataOutputValidator:
    """
    Post-execution [DATA]: format validator

    工具执行后的数据格式验证器。
    参考 fin-agent 的结构化输出规范。

    验证逻辑：
      1. 确认输出包含 [DATA]: 前缀
      2. 确认 [DATA]: 后的内容非空（可选）
      3. 不合格就返回错误信息，让 ErrorHandler 触发重试
    """

    def __init__(self, data_prefix: str = "[DATA]:", validate_non_empty: bool = True):
        self.data_prefix = data_prefix
        self.validate_non_empty = validate_non_empty

    def validate(self, output: str, tool_call_id: str, tool_name: str) -> Tuple[bool, ToolMessage]:
        """
        验证工具输出格式

        Returns:
            (True, original_msg)  → 通过验证
            (False, error_msg)    → 验证失败，返回错误 ToolMessage
        """
        ok_msg = ToolMessage(content=output, tool_call_id=tool_call_id, name=tool_name)

        # 检查 [DATA]: 前缀是否存在
        if self.data_prefix and self.data_prefix not in output:
            error_content = (
                f"[VALIDATION ERROR] Output missing required prefix '{self.data_prefix}'.\n"
                f"Expected: print(f\"{self.data_prefix} {{json.dumps(data)}}\")"
            )
            print(f"[DataOutputValidator] FAIL: missing '{self.data_prefix}' in output")
            return False, ToolMessage(
                content=error_content,
                tool_call_id=tool_call_id,
                name=tool_name
            )

        # 检查 [DATA]: 后内容是否非空
        if self.validate_non_empty and self.data_prefix in output:
            after_prefix = output.split(self.data_prefix, 1)[-1].strip()
            empty_values = ("{}", "[]", "null", "None", "{'error'")
            if any(after_prefix.startswith(ev) for ev in empty_values):
                error_content = (
                    f"[VALIDATION ERROR] '{self.data_prefix}' contains empty/error data: "
                    f"{after_prefix[:100]}"
                )
                print(f"[DataOutputValidator] FAIL: empty data after '{self.data_prefix}'")
                return False, ToolMessage(
                    content=error_content,
                    tool_call_id=tool_call_id,
                    name=tool_name
                )

        return True, ok_msg


class ASAToolNode:
    """
    ASA Standard Tool Node

    Features:
    1. Pre-execution permission gate via ToolCallMiddleware (YAML-driven)
    2. Post-execution output validation via DataOutputValidator (for coder)
    3. Tool usage tracking (for ToolUsageGraph)
    4. Standard LangGraph ToolNode interface
    """

    def __init__(self):
        # Tool registry with permission control
        self.tools_by_agent: Dict[str, List[PermissionControlledTool]] = {}
        self.all_tools: Dict[str, BaseTool] = {}

        # Middleware components (NEW)
        self._permission_middleware = ToolCallMiddleware()
        self._data_validator = DataOutputValidator(
            data_prefix="[DATA]:",
            validate_non_empty=True
        )

        # Initialize from config
        self._init_tools()
    
    def _init_tools(self):
        """Initialize tools with permission config - now YAML-driven"""
        from lib import search, run_python_script

        # Attempt YAML-driven initialization first (preferred)
        try:
            from loader import agent_factory
            if agent_factory is not None:
                for agent_name in agent_factory.list_agents():
                    allowed_names = agent_factory.get_allowed_tools(agent_name)
                    self.tools_by_agent[agent_name] = []
                    for tool_name in allowed_names:
                        raw_tool = self._resolve_tool(tool_name)
                        if raw_tool is not None:
                            wrapped = PermissionControlledTool(
                                tool=raw_tool,
                                allowed_agents=[agent_name]
                            )
                            self.tools_by_agent[agent_name].append(wrapped)
                            self.all_tools[tool_name] = raw_tool
                print(f"[ASAToolNode] YAML-driven tool init: {list(self.tools_by_agent.keys())}")
                return
        except Exception as e:
            print(f"[ASAToolNode] YAML-driven init failed, falling back: {e}")

        # Fallback: hard-coded defaults (backward compatible)
        tool_configs = {
            "coder": [
                ("search_tushare_docs", search, ["coder"]),
                ("run_script", run_python_script, ["coder"]),
            ],
            "reviewer": [
                ("search_tushare_docs", search, ["reviewer"]),
            ],
            "supervisor": [
                ("search_tushare_docs", search, ["supervisor"]),
            ]
        }
        for agent_name, tools in tool_configs.items():
            self.tools_by_agent[agent_name] = []
            for tool_name, tool_func, allowed in tools:
                wrapped = PermissionControlledTool(tool=tool_func, allowed_agents=allowed)
                self.tools_by_agent[agent_name].append(wrapped)
                self.all_tools[tool_name] = tool_func
        print("[ASAToolNode] Fallback hard-coded tool init complete")

    @staticmethod
    def _resolve_tool(tool_name: str) -> Optional[BaseTool]:
        """Resolve tool name to BaseTool object from lib.py registry"""
        try:
            from lib import search, run_python_script, get_current_datetime
            registry = {
                "search_tushare_docs": search,
                "run_script": run_python_script,
                "get_current_datetime": get_current_datetime,
            }
            return registry.get(tool_name)
        except ImportError:
            return None
    
    def get_tools_for_agent(self, agent_name: str) -> List[BaseTool]:
        """Get tools available to specific agent"""
        controlled = self.tools_by_agent.get(agent_name, [])
        return [ct.tool for ct in controlled if agent_name in ct.allowed_agents]
    
    def invoke(self, state: Dict, agent_name: str) -> Dict:
        """
        Execute tools with permission + output validation pipeline

        Pipeline (NEW):
          1. ToolCallMiddleware.check()  -> permission gate
          2. PermissionControlledTool.execute() -> actual execution
          3. DataOutputValidator.validate() -> output format check (coder only)

        Args:
            state: Current state with messages
            agent_name: Name of agent requesting tool execution

        Returns:
            Dict with tool results
        """
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last_message = messages[-1]

        if not hasattr(last_message, 'tool_calls') or not last_message.tool_calls:
            return {"messages": []}

        tool_results = []

        for tool_call in last_message.tool_calls:
            tool_name = tool_call.get("name", "")
            tool_input = tool_call.get("args", {})
            tool_call_id = tool_call.get("id", "")

            # --- Step 1: Permission middleware check ---
            denied_msg = self._permission_middleware.check(agent_name, tool_name, tool_call_id)
            if denied_msg is not None:
                tool_results.append(denied_msg)
                continue

            # --- Step 2: Find and execute tool ---
            allowed_tools = self.tools_by_agent.get(agent_name, [])
            tool_wrapper = next(
                (t for t in allowed_tools if t.tool.name == tool_name),
                None
            )

            if not tool_wrapper or not tool_wrapper.can_execute(agent_name):
                tool_results.append(ToolMessage(
                    content=f"[PERMISSION DENIED] Agent '{agent_name}' cannot use tool '{tool_name}'",
                    tool_call_id=tool_call_id,
                    name=tool_name
                ))
                continue

            try:
                result = str(tool_wrapper.execute(tool_input))
            except Exception as e:
                tool_results.append(ToolMessage(
                    content=f"[TOOL ERROR] {str(e)}",
                    tool_call_id=tool_call_id,
                    name=tool_name
                ))
                continue

            # --- Step 3: Output validation (only for coder run_script) ---
            if agent_name == "coder" and tool_name == "run_script":
                is_valid, validated_msg = self._data_validator.validate(
                    result, tool_call_id, tool_name
                )
                tool_results.append(validated_msg)
            else:
                tool_results.append(ToolMessage(
                    content=result,
                    tool_call_id=tool_call_id,
                    name=tool_name
                ))

        return {"messages": tool_results}


# Global instance
tool_node = ASAToolNode()


def create_agent_with_tools(agent_name: str, model, prompt: str):
    """
    Create agent with restricted tool set
    Reference: langgraph-supervisor-py create_react_agent
    """
    from langgraph.prebuilt import create_react_agent
    
    tools = tool_node.get_tools_for_agent(agent_name)
    
    return create_react_agent(
        model=model,
        tools=tools,
        prompt=prompt,
        name=agent_name
    )
