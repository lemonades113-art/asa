#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA Agent 加载器 - YAML 配置化与 AgentFactory
=============================================
功能:
  1. 从 config/agents.yaml 加载 Agent 配置
  2. Pydantic 校验必填字段，缺失字段抛出清晰异常
  3. 支持热加载（检测 YAML 文件 mtime，无需重启）
  4. AgentFactory 根据配置动态创建 ChatOpenAI 实例
  5. 自动检查 required_packages（Skill Prerequisites 机制）
  6. 支持注入 learnings_context 到 System Prompt 经验区

使用示例:
  from loader import agent_factory

  # 创建 Coder 模型
  coder_model = agent_factory.create_model("coder")

  # 获取 Supervisor 系统提示词（含历史经验注入）
  system_prompt = agent_factory.get_system_prompt("supervisor", learnings_context="...")

  # 手动热加载（文件变更后自动触发，此处为强制刷新）
  agent_factory.reload()
"""

import os
import importlib
from pathlib import Path
from typing import Optional, Dict, List, Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

import conf

# ===========================================================================
# 默认配置路径
# ===========================================================================
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "agents.yaml"


# ===========================================================================
# Pydantic 数据模型
# ===========================================================================

# ===========================================================================
# 新增: 工具权限 & 输出约束 Pydantic 模型
# 参考: TradingAgents default_config.py 的分层配置思路
#       fin-agent 的工具注册表模式
#       OpenCode agent.tools 权限声明
# ===========================================================================

class ToolsConfig(BaseModel):
    """
    Agent 工具权限配置

    allowed: 允许使用的工具名列表（空列表 = 无工具权限）
    denied:  明确禁止的工具名列表（用于文档化意图，运行时也做检查）
    """
    allowed: List[str] = Field(default_factory=list, description="允许使用的工具名")
    denied: List[str] = Field(default_factory=list, description="明确禁止的工具名")

    def can_use(self, tool_name: str) -> bool:
        """检查工具是否被允许"""
        if tool_name in self.denied:
            return False
        # 空 allowed 表示无任何工具权限
        if not self.allowed:
            return False
        return tool_name in self.allowed


class OutputConstraints(BaseModel):
    """
    Agent 输出约束配置

    参考 fin-agent 的结构化输出规范 + ASA 三重验证机制。
    这里只做配置声明，实际验证逻辑在 tool_node.ToolCallMiddleware 中执行。
    """
    data_prefix: Optional[str] = Field(None, description="数据输出必须以此前缀开头，如 '[DATA]:'")
    format: Optional[str] = Field(None, description="数据格式要求：json / text / any")
    max_retries: int = Field(3, ge=1, le=10, description="最大重试次数")
    validate_non_empty: bool = Field(False, description="是否拒绝空数据返回")
    require_routing_decision: bool = Field(False, description="是否必须包含 next 字段路由")
    require_verdict: bool = Field(False, description="是否必须包含 PASS/FAIL 判断")
    require_recovery_level: bool = Field(False, description="是否必须包含 recovery_level 字段")


class AgentConfig(BaseModel):
    """单个 Agent 的配置模型（含校验规则）"""

    role: str = Field(..., min_length=1, description="Agent 角色名称，不可为空")
    goal: str = Field(..., min_length=1, description="Agent 目标描述，不可为空")
    backstory: str = Field(..., min_length=1, description="Agent 背景故事/System Prompt，不可为空")
    model_name: str = Field(..., description="模型名称，如 qwen-plus / qwen-turbo")
    temperature: float = Field(0.1, ge=0.0, le=2.0, description="生成温度 [0.0, 2.0]")
    max_tokens: Optional[int] = Field(None, gt=0, description="最大输出 Token 数")
    required_packages: List[str] = Field(
        default_factory=list,
        description="运行此 Agent 所需的 Python 包列表（Skill Prerequisites）"
    )
    # 新增: 工具权限和输出约束
    tools: ToolsConfig = Field(
        default_factory=ToolsConfig,
        description="工具权限配置（allowed/denied）"
    )
    output_constraints: OutputConstraints = Field(
        default_factory=OutputConstraints,
        description="输出约束配置"
    )

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        allowed_prefixes = ("qwen", "gpt", "deepseek", "claude")
        if not any(v.startswith(p) for p in allowed_prefixes):
            raise ValueError(
                f"model_name '{v}' 不在已知前缀列表中 ({allowed_prefixes})。"
                f"如需使用自定义模型，请在 loader.py 中扩展 allowed_prefixes。"
            )
        return v

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, v: float) -> float:
        if not (0.0 <= v <= 2.0):
            raise ValueError(f"temperature 必须在 [0.0, 2.0] 范围内，当前值: {v}")
        return v


class AgentsYamlConfig(BaseModel):
    """YAML 文件的根结构校验"""

    agents: Dict[str, AgentConfig] = Field(
        ..., min_length=1, description="agents 字段不可为空，至少定义一个 Agent"
    )

    @model_validator(mode="after")
    def validate_required_agents(self) -> "AgentsYamlConfig":
        """确保核心 Agent 都存在"""
        required = {"supervisor", "coder", "reviewer"}
        missing = required - set(self.agents.keys())
        if missing:
            raise ValueError(
                f"config/agents.yaml 缺少必要的 Agent 定义: {missing}。"
                f"请确保 supervisor, coder, reviewer 均已定义。"
            )
        return self


# ===========================================================================
# AgentLoader - 带热加载的配置读取器
# ===========================================================================

class AgentLoader:
    """
    YAML 配置热加载器

    原理:
      每次调用 load() 时检查文件 mtime（最后修改时间）。
      若文件已更新，重新解析并用 Pydantic 校验；否则返回缓存。
      这样在不重启进程的情况下，修改 YAML 后立即生效。
    """

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        self.config_path = Path(config_path)
        self._config: Optional[AgentsYamlConfig] = None
        self._last_mtime: float = 0.0

        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Agent 配置文件不存在: {self.config_path}\n"
                f"请确保 config/agents.yaml 文件存在并包含正确的 Agent 定义。"
            )

    def _is_stale(self) -> bool:
        """检查文件是否已被修改"""
        try:
            mtime = os.path.getmtime(self.config_path)
            return mtime > self._last_mtime
        except OSError:
            return True

    def load(self, force: bool = False) -> AgentsYamlConfig:
        """
        加载配置（支持热加载）

        Args:
            force: 强制重新加载，忽略缓存

        Returns:
            AgentsYamlConfig: 经过 Pydantic 校验的配置对象

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: YAML 内容缺少必要字段或字段值不合法
        """
        if not force and self._config is not None and not self._is_stale():
            return self._config

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        if raw_data is None:
            raise ValueError(f"config/agents.yaml 文件内容为空，请检查 YAML 格式。")

        # Pydantic 校验 - 任何字段缺失或格式错误都会在此抛出清晰异常
        try:
            self._config = AgentsYamlConfig(**raw_data)
        except Exception as e:
            raise ValueError(
                f"config/agents.yaml 配置校验失败:\n{e}\n"
                f"请检查 YAML 字段是否完整（role, goal, backstory, model_name 为必填）。"
            ) from e

        self._last_mtime = os.path.getmtime(self.config_path)
        print(f"[AgentLoader] 配置已加载: {list(self._config.agents.keys())}")
        return self._config

    def reload(self) -> AgentsYamlConfig:
        """强制热重载配置"""
        print(f"[AgentLoader] 触发热重载: {self.config_path}")
        return self.load(force=True)

    def get_agent(self, agent_name: str) -> AgentConfig:
        """
        获取单个 Agent 配置

        Raises:
            KeyError: Agent 名称不存在
        """
        config = self.load()
        if agent_name not in config.agents:
            available = list(config.agents.keys())
            raise KeyError(
                f"Agent '{agent_name}' 未在 config/agents.yaml 中定义。"
                f"可用 Agent: {available}"
            )
        return config.agents[agent_name]


# ===========================================================================
# Prerequisites 检查器 - 借鉴 OpenClaw Skill Prerequisites 机制
# ===========================================================================

class PrerequisitesChecker:
    """
    运行时依赖检查器

    在 Agent/Skill 执行前检查所需包是否已安装。
    如缺失，直接返回错误信息，不浪费 Token 触发 LLM 调用。

    参考: OpenClaw Skill Prerequisites 设计
    """

    @staticmethod
    def check(agent_name: str, required_packages: List[str]) -> Optional[str]:
        """
        检查所有依赖包是否可导入

        Returns:
            None: 所有依赖满足
            str: 缺失包的错误信息（供 State 写入 error_info）
        """
        missing = []
        for pkg in required_packages:
            # 处理 langchain_openai → langchain-openai 这类命名差异
            import_name = pkg.replace("-", "_").replace("langchain_", "langchain_")
            try:
                importlib.import_module(import_name)
            except ImportError:
                missing.append(pkg)

        if missing:
            return (
                f"[Prerequisites] Agent '{agent_name}' 缺少依赖包: {missing}。"
                f"请执行: pip install {' '.join(missing)}"
            )
        return None

    @staticmethod
    def check_agent(agent_cfg: AgentConfig, agent_name: str) -> Optional[str]:
        """检查单个 Agent 配置中的 required_packages"""
        return PrerequisitesChecker.check(agent_name, agent_cfg.required_packages)


# ===========================================================================
# AgentFactory - 根据 YAML 配置动态生成 LLM 实例
# ===========================================================================

class AgentFactory:
    """
    Agent 工厂类

    根据 config/agents.yaml 中的配置，动态创建 ChatOpenAI 实例。
    每次创建时自动检查热加载（文件变更后自动生效，无需重启）。

    使用示例:
        factory = AgentFactory()
        model = factory.create_model("coder")
        prompt = factory.get_system_prompt("supervisor", learnings_context="...")
    """

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        self.loader = AgentLoader(config_path)
        self._prereq_checker = PrerequisitesChecker()

    def create_model(
        self,
        agent_name: str,
        check_prerequisites: bool = True
    ):
        """
        创建指定 Agent 的 ChatOpenAI 模型实例

        Args:
            agent_name: Agent 名称（必须存在于 agents.yaml）
            check_prerequisites: 是否检查 required_packages

        Returns:
            ChatOpenAI 实例

        Raises:
            KeyError: Agent 不存在
            RuntimeError: 依赖检查失败
            ValueError: 配置字段不合法
        """
        from langchain_openai import ChatOpenAI  # 延迟导入，避免循环依赖

        agent_cfg = self.loader.get_agent(agent_name)

        # Skill Prerequisites 检查
        if check_prerequisites and agent_cfg.required_packages:
            error_msg = self._prereq_checker.check_agent(agent_cfg, agent_name)
            if error_msg:
                raise RuntimeError(error_msg)

        kwargs = {
            "model": agent_cfg.model_name,
            "temperature": agent_cfg.temperature,
            "api_key": conf.api_key,
            "base_url": conf.base_url,
        }
        if agent_cfg.max_tokens is not None:
            kwargs["max_tokens"] = agent_cfg.max_tokens

        print(f"[AgentFactory] 创建 Agent: {agent_name} | 模型: {agent_cfg.model_name} | temperature: {agent_cfg.temperature}")
        return ChatOpenAI(**kwargs)

    def get_system_prompt(
        self,
        agent_name: str,
        learnings_context: str = "",
        extra_context: str = ""
    ) -> str:
        """
        获取指定 Agent 的 System Prompt

        支持动态注入 learnings_context（Self-Improving 经验区）。
        修改 agents.yaml 后热加载生效，无需重启。
        新增：自动将 output_constraints 注入提示词，强化输出规范。

        Args:
            agent_name: Agent 名称
            learnings_context: 从 .learnings/ 读取的历史经验（自动注入）
            extra_context: 其他临时上下文（如当前日期、用户画像摘要等）

        Returns:
            完整的 System Prompt 字符串
        """
        agent_cfg = self.loader.get_agent(agent_name)

        sections = [
            f"【角色】{agent_cfg.role}",
            f"【目标】{agent_cfg.goal}",
            f"【背景】{agent_cfg.backstory.strip()}",
        ]

        # 新增：自动注入输出约束到提示词（将 YAML 声明转化为 Prompt 软约束）
        # 参考: TradingAgents 的 agent instruction 动态拼装
        oc = agent_cfg.output_constraints
        constraints_lines = []
        if oc.data_prefix:
            constraints_lines.append(
                f"- 所有数据输出必须以 `{oc.data_prefix}` 开头，"
                f"格式：print(f\"{oc.data_prefix} {{json.dumps(data, ensure_ascii=False)}}\")"
            )
        if oc.validate_non_empty:
            constraints_lines.append("- 严禁返回空 DataFrame 或空列表，必须校验数据非空后再输出")
        if oc.require_routing_decision:
            constraints_lines.append("- 必须在回复末尾明确指定下一步执行者（Coder / Reviewer / FINISH）")
        if oc.require_verdict:
            constraints_lines.append("- 必须在回复末尾给出明确判断：[PASS] 或 [FAIL: 原因]")
        if oc.require_recovery_level:
            constraints_lines.append("- 必须在回复中包含 recovery_level 字段标明当前恢复层级")
        if constraints_lines:
            sections.append("\n【输出规范 - 严格遵守】\n" + "\n".join(constraints_lines))

        if learnings_context:
            sections.append(
                f"\n【历史经验 - 请参考以下过往错误和解决方案，避免重蹈覆辙】\n{learnings_context}"
            )

        if extra_context:
            sections.append(f"\n【补充信息】\n{extra_context}")

        return "\n\n".join(sections)

    def get_allowed_tools(self, agent_name: str) -> List[str]:
        """
        获取指定 Agent 允许使用的工具列表

        Returns:
            允许的工具名列表（空列表表示无工具权限）
        """
        agent_cfg = self.loader.get_agent(agent_name)
        return list(agent_cfg.tools.allowed)

    def can_use_tool(self, agent_name: str, tool_name: str) -> bool:
        """
        检查指定 Agent 是否有权使用某工具

        参考: OpenCode agent.tools 权限声明
              TradingAgents agent_pool 工具绑定
        """
        agent_cfg = self.loader.get_agent(agent_name)
        return agent_cfg.tools.can_use(tool_name)

    def create_agent_with_tools(
        self,
        agent_name: str,
        tool_registry: Optional[Dict[str, Any]] = None,
        learnings_context: str = ""
    ):
        """
        使用 LangGraph prebuilt API 创建带权限控制的 Agent

        参考: langgraph-supervisor-py create_react_agent 模式
              TradingAgents 的 deep_think_llm / quick_think_llm 分离

        Args:
            agent_name: Agent 名称（必须在 agents.yaml 中定义）
            tool_registry: 工具名 -> BaseTool 对象的映射字典
                          若为 None，自动从 lib.py 加载默认工具
            learnings_context: Self-Improving 历史经验注入

        Returns:
            create_react_agent 返回的 CompiledGraph（Runnable 接口）
        """
        from langgraph.prebuilt import create_react_agent

        model = self.create_model(agent_name)
        prompt = self.get_system_prompt(agent_name, learnings_context=learnings_context)
        agent_cfg = self.loader.get_agent(agent_name)

        # 构建允许的工具列表
        if tool_registry is None:
            tool_registry = self._load_default_tool_registry()

        allowed_tools = []
        for tool_name in agent_cfg.tools.allowed:
            if tool_name in tool_registry:
                allowed_tools.append(tool_registry[tool_name])
            else:
                print(f"[AgentFactory] WARNING: tool '{tool_name}' not found in registry, skipped.")

        print(
            f"[AgentFactory] create_agent_with_tools: {agent_name} "
            f"| tools={[t.name if hasattr(t, 'name') else str(t) for t in allowed_tools]}"
        )

        return create_react_agent(
            model=model,
            tools=allowed_tools,
            prompt=prompt,
            name=agent_name
        )

    @staticmethod
    def _load_default_tool_registry() -> Dict[str, Any]:
        """
        加载 ASA 默认工具注册表

        参考: fin-agent 的工具注册表设计
              AgenticTrading 的 Data Agent Pool 工具绑定
        """
        try:
            from lib import search, run_python_script, get_current_datetime
            return {
                "search_tushare_docs": search,
                "run_script": run_python_script,
                "get_current_datetime": get_current_datetime,
            }
        except ImportError as e:
            print(f"[AgentFactory] WARNING: failed to load lib tools: {e}")
            return {}

    def reload(self) -> None:
        """手动触发热重载（通常无需调用，自动检测 mtime）"""
        self.loader.reload()

    def list_agents(self) -> List[str]:
        """返回所有已定义的 Agent 名称列表"""
        return list(self.loader.load().agents.keys())

    def get_output_constraints(self, agent_name: str) -> OutputConstraints:
        """获取指定 Agent 的输出约束配置"""
        agent_cfg = self.loader.get_agent(agent_name)
        return agent_cfg.output_constraints


# ===========================================================================
# 全局单例 - 供 multi_agent.py 导入使用
# ===========================================================================
try:
    agent_factory = AgentFactory()
    print(f"[AgentFactory] 初始化成功，已加载 Agent: {agent_factory.list_agents()}")
except Exception as e:
    agent_factory = None
    print(f"[AgentFactory] 初始化失败（config/agents.yaml 不存在或格式错误）: {e}")
