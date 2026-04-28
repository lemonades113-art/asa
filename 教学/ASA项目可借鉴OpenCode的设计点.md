# 你的 ASA 项目可以借鉴 OpenCode 的设计点

## 项目对比分析

### 你的系统（ASA - Agent Stock Assistant）

**架构特点**：
- **框架**：LangGraph + LangChain（Python）
- **模式**：Supervisor Pattern（中心化调度）
- **Agent**：Supervisor、Coder、Reviewer、ProfileUpdater、ErrorHandler
- **路由**：`routing_config.json` 字典查表法
- **技能**：`skills.json` 领域专家知识注入
- **记忆**：分层记忆系统（短期+长期）
- **错误处理**：4-Level Self-Healing + 策略模式

### OpenCode 系统

**架构特点**：
- **框架**：自研 Tool 系统 + Vercel AI SDK（TypeScript/Bun）
- **模式**：去中心化 Agent 系统（agent 可嵌套）
- **Agent**：build、plan、explore、general（可扩展）
- **权限**：细粒度的 PermissionNext 系统（支持 glob 模式）
- **Tool**：统一 Tool 接口（40+ 内置工具）
- **Session**：会话持久化 + 消息压缩

---

## 🎯 核心借鉴建议（按优先级）

### ⭐⭐⭐ 高优先级（立即可用）

#### 1. **工具权限系统**

**你目前的问题**：
```python
# loader.py - 工具权限配置过于简单
class ToolsConfig(BaseModel):
    allowed: List[str] = []  # 仅支持工具名白名单
    denied: List[str] = []   # 黑名单

    def can_use(self, tool_name: str) -> bool:
        # 只能粗粒度控制工具访问
        if tool_name in self.denied: return False
        return tool_name in self.allowed
```

**OpenCode 的方案**：
```python
# 支持 glob 模式 + 多层嵌套的权限规则
permission = {
    "*": "allow",  # 默认允许
    "read": {
        "*": "allow",
        "*.env": "ask",        # .env 文件需要询问
        "secrets/*": "deny",   # secrets 目录拒绝
    },
    "bash": {
        "*": "ask",            # 默认询问
        "ls *": "allow",       # ls 命令允许
        "rm -rf *": "deny",    # 危险命令拒绝
        "git diff": "allow",
        "git log": "allow",
    },
    "edit": {
        "*": "deny",           # 默认拒绝
        "src/**/*.py": "allow",  # 只允许编辑 src 下的 py 文件
    }
}
```

**借鉴方案**（适配你的系统）：

```python
# loader.py - 升级版 ToolsConfig

from pathlib import Path
from fnmatch import fnmatch

class PermissionRule(BaseModel):
    """权限规则（支持嵌套和 glob 模式）"""
    rule: Literal["allow", "ask", "deny"]
    paths: List[str] = []  # 路径模式列表

class ToolsConfig(BaseModel):
    """增强版工具权限配置"""

    # 基础配置（向后兼容）
    allowed: List[str] = []
    denied: List[str] = []

    # 高级配置（参考 OpenCode）
    advanced_rules: Dict[str, Union[str, Dict[str, Any]]] = Field(
        default_factory=dict,
        description="高级权限规则（支持 glob 模式和嵌套）"
    )

    def can_use(self, tool_name: str, resource: Optional[str] = None) -> Tuple[bool, str]:
        """
        检查工具权限（增强版）

        返回: (是否允许, 拒绝原因)

        示例:
            can_use("read", "config.json")  -> (True, "")
            can_use("read", ".env")         -> (False, "需要询问用户")
            can_use("bash", "rm -rf /")     -> (False, "危险命令被拒绝")
        """
        # 1. 基础黑名单检查（向后兼容）
        if tool_name in self.denied:
            return False, f"工具 {tool_name} 在黑名单中"

        # 2. 如果没有高级规则，使用简单白名单
        if not self.advanced_rules:
            if not self.allowed:
                return False, "未配置任何允许的工具"
            return tool_name in self.allowed, f"工具 {tool_name} 不在白名单中"

        # 3. 高级规则检查（参考 OpenCode）
        return self._check_advanced_rules(tool_name, resource)

    def _check_advanced_rules(self, tool_name: str, resource: Optional[str]) -> Tuple[bool, str]:
        """检查高级规则"""
        rules = self.advanced_rules

        # 3.1 工具不存在规则，检查通配符
        if tool_name not in rules:
            if "*" in rules:
                default_rule = rules["*"]
                if default_rule == "allow":
                    return True, ""
                elif default_rule == "deny":
                    return False, "默认拒绝"
                elif default_rule == "ask":
                    return False, "需要询问用户"
            return False, f"工具 {tool_name} 无权限规则"

        # 3.2 工具存在规则
        tool_rule = rules[tool_name]

        # 3.2.1 简单字符串规则
        if isinstance(tool_rule, str):
            if tool_rule == "allow":
                return True, ""
            elif tool_rule == "deny":
                return False, f"工具 {tool_name} 被拒绝"
            elif tool_rule == "ask":
                return False, "需要询问用户"

        # 3.2.2 嵌套规则（针对资源路径）
        if isinstance(tool_rule, dict) and resource:
            # 精确匹配
            if resource in tool_rule:
                return self._parse_rule(tool_rule[resource])

            # Glob 模式匹配
            for pattern, rule in tool_rule.items():
                if fnmatch(resource, pattern):
                    return self._parse_rule(rule)

            # 检查默认规则
            if "*" in tool_rule:
                return self._parse_rule(tool_rule["*"])

        # 默认拒绝
        return False, "无匹配的权限规则"

    def _parse_rule(self, rule: Any) -> Tuple[bool, str]:
        """解析规则"""
        if rule == "allow":
            return True, ""
        elif rule == "deny":
            return False, "被规则拒绝"
        elif rule == "ask":
            return False, "需要询问用户"
        return False, "未知规则"


# ===== 在 agents.yaml 中配置 =====

# config/agents.yaml
agents:
  coder:
    role: "Coder"
    goal: "执行 Python 代码并处理数据"
    backstory: "..."
    model_name: "qwen-plus"
    tools:
      # 简单模式（向后兼容）
      allowed: ["run_python_script", "search"]
      denied: []

      # 高级模式（参考 OpenCode）
      advanced_rules:
        "*": "ask"  # 默认询问

        run_python_script: "allow"  # 允许执行代码

        search:
          "*": "allow"
          "financial_data/*": "allow"

        file_operations:  # 新增：文件操作权限
          "*": "ask"
          "*.py": "allow"
          "*.json": "allow"
          "*.env": "deny"
          "secrets/*": "deny"

  reviewer:
    role: "Reviewer"
    goal: "审查代码和结果"
    tools:
      # Reviewer 只读权限（参考 OpenCode plan agent）
      advanced_rules:
        "*": "deny"  # 默认拒绝
        "read": "allow"
        "search": "allow"
        "run_python_script": "deny"  # 不能执行代码


# ===== 在工具调用时使用 =====

# multi_agent.py
def coder_node(state: AgentState):
    """Coder 节点 - 使用工具前检查权限"""
    agent_config = agent_factory.get_agent_config("coder")
    tools_config = agent_config.tools

    # 检查工具权限
    tool_name = "run_python_script"
    resource = state.get("script_path")  # 脚本路径

    allowed, reason = tools_config.can_use(tool_name, resource)

    if not allowed:
        if "需要询问用户" in reason:
            # 询问用户权限
            user_approved = ask_user_permission(tool_name, resource)
            if not user_approved:
                return {
                    "messages": [AIMessage(content=f"用户拒绝执行 {tool_name}")],
                    "execution_status": "error",
                    "error_type": "permission_denied"
                }
        else:
            # 直接拒绝
            return {
                "messages": [AIMessage(content=f"权限拒绝: {reason}")],
                "execution_status": "error",
                "error_type": "permission_denied"
            }

    # 执行工具
    result = run_python_script(state["code"])
    return {"messages": [AIMessage(content=result)]}
```

**收益**：
- ✅ 细粒度权限控制（文件级别、命令级别）
- ✅ 安全性提升（防止危险操作）
- ✅ 灵活的权限策略（支持 glob 模式）
- ✅ 向后兼容（简单模式仍然可用）

---

#### 2. **统一 Tool 接口**

**你目前的问题**：
```python
# lib.py - 工具定义散乱
@tool
def run_python_script(code: str) -> str:
    """执行 Python 代码"""
    # 直接实现，缺少统一的权限检查、日志、元数据
    result = exec(code)
    return str(result)

@tool
def search(query: str) -> str:
    """搜索知识库"""
    # 另一个独立实现
    return search_knowledge_base(query)
```

**OpenCode 的方案**：
```typescript
// 统一 Tool 接口
export const Tool = Tool.define("tool-name", {
  description: "...",
  parameters: z.object({ /* Zod schema */ }),

  async execute(args, ctx) {
    // 1. 权限检查（自动）
    await ctx.ask({ action: "tool-name", resource: args.path });

    // 2. 执行逻辑
    const result = doSomething(args);

    // 3. 返回标准格式
    return {
      title: "Tool Result",
      metadata: { /* 元数据 */ },
      output: result,
    };
  }
});
```

**借鉴方案**（适配你的系统）：

```python
# lib.py - 统一 Tool 基类

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
import time
import logging

logger = logging.getLogger(__name__)


class ToolContext(BaseModel):
    """工具执行上下文"""
    session_id: str
    agent_name: str
    user_id: Optional[str] = None
    permission_checker: Any = None  # ToolsConfig 实例


class ToolResult(BaseModel):
    """工具执行结果（标准格式）"""
    success: bool
    output: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: float = 0


class BaseTool(ABC):
    """统一 Tool 基类（参考 OpenCode）"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self._stats = {
            "call_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_time_ms": 0
        }

    @abstractmethod
    def _execute_impl(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        """子类实现的核心逻辑"""
        pass

    @abstractmethod
    def validate_args(self, args: Dict[str, Any]) -> bool:
        """参数验证（子类实现）"""
        pass

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        """
        统一执行入口（参考 OpenCode Tool.execute）

        流程:
        1. 参数验证
        2. 权限检查
        3. 执行逻辑
        4. 记录统计
        5. 返回标准结果
        """
        start_time = time.time()
        self._stats["call_count"] += 1

        try:
            # 1. 参数验证
            if not self.validate_args(args):
                raise ValueError(f"Invalid arguments for {self.name}")

            # 2. 权限检查
            if ctx.permission_checker:
                resource = args.get("resource") or args.get("path") or ""
                allowed, reason = ctx.permission_checker.can_use(self.name, resource)

                if not allowed:
                    if "需要询问用户" in reason:
                        # TODO: 集成用户询问机制
                        logger.warning(f"Tool {self.name} requires user permission")
                        raise PermissionError(f"需要用户授权: {reason}")
                    else:
                        raise PermissionError(reason)

            # 3. 执行核心逻辑
            output = self._execute_impl(args, ctx)

            # 4. 记录成功
            self._stats["success_count"] += 1
            execution_time = (time.time() - start_time) * 1000
            self._stats["total_time_ms"] += execution_time

            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "tool_name": self.name,
                    "agent": ctx.agent_name,
                    "execution_time_ms": execution_time
                }
            )

        except Exception as e:
            # 5. 记录失败
            self._stats["failure_count"] += 1
            execution_time = (time.time() - start_time) * 1000

            logger.error(f"Tool {self.name} failed: {e}")

            return ToolResult(
                success=False,
                output="",
                error=str(e),
                metadata={
                    "tool_name": self.name,
                    "agent": ctx.agent_name,
                    "execution_time_ms": execution_time
                }
            )

    def get_stats(self) -> Dict[str, Any]:
        """获取工具统计信息"""
        return {
            **self._stats,
            "success_rate": (
                self._stats["success_count"] / self._stats["call_count"]
                if self._stats["call_count"] > 0 else 0
            ),
            "avg_time_ms": (
                self._stats["total_time_ms"] / self._stats["call_count"]
                if self._stats["call_count"] > 0 else 0
            )
        }


# ===== 具体 Tool 实现 =====

class PythonScriptTool(BaseTool):
    """Python 代码执行工具"""

    def __init__(self):
        super().__init__(
            name="run_python_script",
            description="执行 Python 代码并返回结果"
        )

    def validate_args(self, args: Dict[str, Any]) -> bool:
        return "code" in args and isinstance(args["code"], str)

    def _execute_impl(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        code = args["code"]

        # 安全检查（参考你的 skills.json error_handling）
        dangerous_patterns = ["rm -rf", "os.system", "__import__"]
        for pattern in dangerous_patterns:
            if pattern in code:
                raise ValueError(f"危险代码检测: {pattern}")

        # 执行代码
        try:
            # 使用你现有的 global_kernel
            result = global_kernel.run_code(code)
            return result
        except Exception as e:
            raise RuntimeError(f"代码执行失败: {e}")


class SearchTool(BaseTool):
    """知识库搜索工具"""

    def __init__(self):
        super().__init__(
            name="search",
            description="搜索知识库或网络"
        )

    def validate_args(self, args: Dict[str, Any]) -> bool:
        return "query" in args

    def _execute_impl(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        query = args["query"]

        # 使用你现有的搜索逻辑
        results = search_knowledge_base(query)
        return json.dumps(results, ensure_ascii=False)


class TushareDataTool(BaseTool):
    """Tushare 数据查询工具（新增）"""

    def __init__(self):
        super().__init__(
            name="tushare_query",
            description="查询 Tushare 金融数据"
        )
        self.pro = ts.pro_api(conf.tushare_token)

    def validate_args(self, args: Dict[str, Any]) -> bool:
        required = ["api_name", "params"]
        return all(k in args for k in required)

    def _execute_impl(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        api_name = args["api_name"]
        params = args["params"]

        # 执行查询（参考你的 skills.json）
        try:
            df = getattr(self.pro, api_name)(**params)

            # 空数据检查（参考 charting_expert skill）
            if df.empty:
                logger.warning(f"[WARNING]: {api_name} 返回空数据")
                return json.dumps({"warning": "数据为空", "data": []})

            # 数据转换（参考 finance_audit skill）
            # 例如：revenue 转换为亿元
            if "revenue" in df.columns:
                df["revenue_bn"] = df["revenue"] / 1e8

            return df.to_json(orient="records", force_ascii=False)

        except Exception as e:
            # 错误分类（参考你的 error_classification）
            if "429" in str(e) or "限流" in str(e):
                raise RuntimeError(f"API限流: {e}")
            elif "authentication" in str(e).lower():
                raise PermissionError(f"认证失败: {e}")
            else:
                raise RuntimeError(f"查询失败: {e}")


# ===== Tool 注册表 =====

class ToolRegistry:
    """工具注册表（参考 OpenCode）"""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        """注册工具"""
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """列出所有工具"""
        return list(self._tools.keys())

    def get_stats(self) -> Dict[str, Any]:
        """获取所有工具的统计信息"""
        return {
            name: tool.get_stats()
            for name, tool in self._tools.items()
        }


# 全局工具注册表
tool_registry = ToolRegistry()

# 注册内置工具
tool_registry.register(PythonScriptTool())
tool_registry.register(SearchTool())
tool_registry.register(TushareDataTool())


# ===== 在 multi_agent.py 中使用 =====

def coder_node(state: AgentState):
    """Coder 节点 - 使用统一 Tool 接口"""
    agent_config = agent_factory.get_agent_config("coder")

    # 构建上下文
    ctx = ToolContext(
        session_id=state.get("session_id", "unknown"),
        agent_name="Coder",
        permission_checker=agent_config.tools
    )

    # 执行工具
    tool = tool_registry.get("run_python_script")
    result = await tool.execute(
        args={"code": state["generated_code"]},
        ctx=ctx
    )

    if result.success:
        return {
            "messages": [AIMessage(content=result.output)],
            "execution_status": "success",
            "execution_time_ms": result.metadata["execution_time_ms"]
        }
    else:
        return {
            "messages": [AIMessage(content=f"执行失败: {result.error}")],
            "execution_status": "error",
            "error_type": "code_error"
        }
```

**收益**：
- ✅ 统一接口（所有工具相同的调用方式）
- ✅ 自动权限检查
- ✅ 统一错误处理
- ✅ 自动统计和监控
- ✅ 标准化的输出格式

---

#### 3. **Session 持久化和消息压缩**

**你目前的问题**：
```python
# multi_agent.py - 会话管理分散在 LangGraph 的 MemorySaver 中
memory = MemorySaver()
graph = StateGraph(AgentState)
# ... 构建图
app = graph.compile(checkpointer=memory)

# 消息历史没有压缩机制，长对话可能导致 Token 爆炸
```

**OpenCode 的方案**：
- Session 持久化到 SQLite
- 自动消息压缩（保留最近 N 条 + 摘要）
- 快照系统（可回滚）

**借鉴方案**（适配你的系统）：

```python
# session_manager.py - 新增文件

import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import json

class SessionManager:
    """
    会话管理器（参考 OpenCode）

    功能:
    1. 持久化会话到 SQLite
    2. 自动消息压缩
    3. 会话统计和分析
    """

    def __init__(self, db_path: str = "./data/sessions.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 会话表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                agent_name TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                message_count INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active'
            )
        """)

        # 消息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                content TEXT,
                tool_calls TEXT,
                metadata TEXT,
                created_at INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)

        # 压缩历史表（参考 OpenCode compaction）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compaction_history (
                compaction_id TEXT PRIMARY KEY,
                session_id TEXT,
                original_message_count INTEGER,
                compressed_message_count INTEGER,
                summary TEXT,
                created_at INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)

        conn.commit()
        conn.close()

    def create_session(
        self,
        session_id: str,
        user_id: str,
        agent_name: str
    ) -> Dict[str, Any]:
        """创建新会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = int(datetime.now().timestamp())

        cursor.execute("""
            INSERT INTO sessions (session_id, user_id, agent_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, user_id, agent_name, now, now))

        conn.commit()
        conn.close()

        return {
            "session_id": session_id,
            "user_id": user_id,
            "agent_name": agent_name,
            "created_at": now
        }

    def add_message(
        self,
        session_id: str,
        message_id: str,
        role: str,
        content: str,
        tool_calls: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ):
        """添加消息到会话"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = int(datetime.now().timestamp())

        cursor.execute("""
            INSERT INTO messages (
                message_id, session_id, role, content, tool_calls, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            message_id,
            session_id,
            role,
            content,
            json.dumps(tool_calls or []),
            json.dumps(metadata or {}),
            now
        ))

        # 更新会话统计
        cursor.execute("""
            UPDATE sessions
            SET message_count = message_count + 1,
                updated_at = ?
            WHERE session_id = ?
        """, (now, session_id))

        conn.commit()
        conn.close()

    def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """获取会话消息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = """
            SELECT message_id, role, content, tool_calls, metadata, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
        """

        if limit:
            query += f" LIMIT {limit}"

        cursor.execute(query, (session_id,))
        rows = cursor.fetchall()

        conn.close()

        messages = []
        for row in rows:
            messages.append({
                "message_id": row[0],
                "role": row[1],
                "content": row[2],
                "tool_calls": json.loads(row[3]),
                "metadata": json.loads(row[4]),
                "created_at": row[5]
            })

        return messages

    def compact_session(self, session_id: str, keep_recent: int = 10):
        """
        压缩会话（参考 OpenCode Compaction）

        策略:
        1. 保留最近 keep_recent 条消息
        2. 旧消息生成摘要
        3. 用摘要替换旧消息
        """
        messages = self.get_messages(session_id)

        if len(messages) <= keep_recent:
            return  # 不需要压缩

        # 分割消息
        recent = messages[-keep_recent:]
        old = messages[:-keep_recent]

        # 生成摘要（使用 LLM）
        summary = self._summarize_messages(old)

        # 删除旧消息
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        old_ids = [m["message_id"] for m in old]
        cursor.execute(f"""
            DELETE FROM messages
            WHERE message_id IN ({','.join(['?'] * len(old_ids))})
        """, old_ids)

        # 插入摘要消息
        now = int(datetime.now().timestamp())
        summary_id = f"summary_{session_id}_{now}"

        cursor.execute("""
            INSERT INTO messages (
                message_id, session_id, role, content, tool_calls, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            summary_id,
            session_id,
            "system",
            f"【历史对话摘要】\n{summary}",
            "[]",
            json.dumps({"compacted": True, "original_count": len(old)}),
            now
        ))

        # 记录压缩历史
        cursor.execute("""
            INSERT INTO compaction_history (
                compaction_id, session_id, original_message_count,
                compressed_message_count, summary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            f"comp_{session_id}_{now}",
            session_id,
            len(old),
            1,
            summary,
            now
        ))

        conn.commit()
        conn.close()

        print(f"[Compaction] 压缩会话 {session_id}: {len(old)} 条消息 → 1 条摘要")

    def _summarize_messages(self, messages: List[Dict]) -> str:
        """生成消息摘要（使用 LLM）"""
        # 构建提示词
        message_text = "\n".join([
            f"{m['role']}: {m['content'][:200]}..."
            for m in messages
        ])

        prompt = f"""请总结以下对话，保留关键信息：

{message_text}

要求：
1. 保留重要的决策和结果
2. 保留关键的数据和文件路径
3. 保留错误和解决方案
4. 使用简洁的语言，不超过 500 字

摘要："""

        # 使用快速模型生成摘要
        from lib import get_chat_model
        model = get_chat_model(model_type="fast")

        response = model.invoke([HumanMessage(content=prompt)])
        return response.content

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """获取会话统计"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                s.session_id,
                s.message_count,
                s.total_tokens,
                s.created_at,
                s.updated_at,
                COUNT(DISTINCT c.compaction_id) as compaction_count
            FROM sessions s
            LEFT JOIN compaction_history c ON s.session_id = c.session_id
            WHERE s.session_id = ?
            GROUP BY s.session_id
        """, (session_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return {}

        return {
            "session_id": row[0],
            "message_count": row[1],
            "total_tokens": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "compaction_count": row[5]
        }


# ===== 集成到 multi_agent.py =====

# multi_agent.py
from session_manager import SessionManager

session_manager = SessionManager()

def create_agent_executor():
    """创建 agent 执行器（修改版）"""
    # ... 原有代码

    # 原来的 MemorySaver
    memory = MemorySaver()

    # 包装一层，同时保存到 SQLite
    class PersistentMemorySaver(MemorySaver):
        def put(self, key, value):
            super().put(key, value)

            # 同时保存到 SessionManager
            session_id = key.get("configurable", {}).get("thread_id")
            if session_id and "messages" in value:
                for msg in value["messages"]:
                    if not msg.get("_saved"):  # 避免重复保存
                        session_manager.add_message(
                            session_id=session_id,
                            message_id=msg.get("id", str(uuid.uuid4())),
                            role=msg["role"],
                            content=msg["content"],
                            tool_calls=msg.get("tool_calls"),
                            metadata={"agent": msg.get("name")}
                        )
                        msg["_saved"] = True

                # 检查是否需要压缩
                stats = session_manager.get_session_stats(session_id)
                if stats.get("message_count", 0) > 20:
                    session_manager.compact_session(session_id, keep_recent=10)

    memory = PersistentMemorySaver()
    app = graph.compile(checkpointer=memory)

    return app
```

**收益**：
- ✅ 会话持久化（不依赖内存）
- ✅ 自动消息压缩（节省 token）
- ✅ 会话统计和分析
- ✅ 可查询历史会话
- ✅ 兼容现有的 LangGraph MemorySaver

---

### ⭐⭐ 中优先级（渐进增强）

#### 4. **Agent 可嵌套（子任务委托）**

**你目前的限制**：
- Supervisor 模式是中心化的
- 所有任务都由 Supervisor 调度
- 缺少 agent 之间的直接协作

**OpenCode 的方案**：
- Task Tool 可以启动子 agent
- 子 agent 有独立的权限和上下文
- 支持并行执行多个子任务

**借鉴方案**：

```python
# multi_agent.py - 新增 Task Tool

class TaskTool(BaseTool):
    """
    子任务委托工具（参考 OpenCode Task Tool）

    允许 Agent 启动子 Agent 处理复杂任务
    """

    def __init__(self):
        super().__init__(
            name="delegate_task",
            description="委托子任务给专门的 Agent 处理"
        )

    def validate_args(self, args: Dict[str, Any]) -> bool:
        required = ["agent_type", "task_description", "prompt"]
        return all(k in args for k in required)

    def _execute_impl(self, args: Dict[str, Any], ctx: ToolContext) -> str:
        agent_type = args["agent_type"]  # "data_analyst", "chart_maker", etc.
        task_description = args["task_description"]
        prompt = args["prompt"]
        run_in_background = args.get("run_in_background", False)

        # 创建子会话
        child_session_id = f"{ctx.session_id}_child_{uuid.uuid4().hex[:8]}"

        session_manager.create_session(
            session_id=child_session_id,
            user_id=ctx.user_id or "system",
            agent_name=agent_type
        )

        # 加载子 Agent 配置
        agent_config = agent_factory.get_agent_config(agent_type)

        # 构建子 Agent 的初始状态
        child_state = {
            "messages": [
                SystemMessage(content=agent_config.backstory),
                HumanMessage(content=prompt)
            ],
            "session_id": child_session_id,
            "parent_session_id": ctx.session_id,
            "agent_name": agent_type,
            "execution_status": "running"
        }

        if run_in_background:
            # 后台执行（异步）
            import threading
            threading.Thread(
                target=self._run_child_agent,
                args=(child_state, agent_config)
            ).start()

            return json.dumps({
                "status": "background",
                "child_session_id": child_session_id,
                "message": f"子任务已启动（后台）: {task_description}"
            })
        else:
            # 前台执行（同步）
            result = self._run_child_agent(child_state, agent_config)

            return json.dumps({
                "status": "completed",
                "child_session_id": child_session_id,
                "result": result,
                "message": f"子任务完成: {task_description}"
            })

    def _run_child_agent(self, state: Dict, config: AgentConfig) -> str:
        """运行子 Agent"""
        # 创建子 Agent 的执行器
        child_executor = create_agent_executor(agent_type=config.role)

        # 执行
        result = child_executor.invoke(
            state,
            config={"configurable": {"thread_id": state["session_id"]}}
        )

        # 提取结果
        final_message = result["messages"][-1]
        return final_message.content


# ===== 注册 Task Tool =====
tool_registry.register(TaskTool())


# ===== 使用示例 =====

# 在 Supervisor 中使用
def supervisor_node(state: AgentState):
    """Supervisor 可以委托子任务"""

    # 判断是否需要委托
    if "需要深度数据分析" in state["messages"][-1].content:
        # 委托给专门的数据分析 Agent
        task_tool = tool_registry.get("delegate_task")

        result = await task_tool.execute(
            args={
                "agent_type": "data_analyst",
                "task_description": "分析茅台近5年财务数据",
                "prompt": """请分析贵州茅台（600519）近5年的财务数据：
1. 营收和利润趋势
2. 盈利能力指标（ROE、净利率）
3. 成长性指标（营收增长率、利润增长率）
4. 给出投资建议
""",
                "run_in_background": False
            },
            ctx=ToolContext(
                session_id=state["session_id"],
                agent_name="Supervisor"
            )
        )

        # 使用子任务的结果
        result_data = json.loads(result.output)
        analysis = result_data["result"]

        return {
            "messages": [AIMessage(content=f"数据分析完成：\n{analysis}")],
            "next": "Reviewer"
        }
```

**收益**：
- ✅ Agent 可以委托专门的子 Agent
- ✅ 支持并行处理多个子任务
- ✅ 子任务有独立的上下文和权限
- ✅ 减轻 Supervisor 的负担

---

#### 5. **Skill 系统升级**

**你目前的实现**：
```json
// skills.json - 静态 JSON 配置
{
  "dividend_expert": {
    "trigger_keywords": ["分红", "股息"],
    "content": "【技能注入：分红专家】\n1. 字段冲突提示...\n2. 状态过滤..."
  }
}
```

**OpenCode 的方案**：
- Skill 可以包含自定义工具
- 支持代码执行（不仅仅是提示词）
- 热加载和版本管理

**借鉴方案**：

```python
# skills.py - 升级版 Skill 系统

from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
import importlib.util
import json

class Skill(BaseModel):
    """技能定义（参考 OpenCode）"""
    name: str
    description: str
    trigger_keywords: List[str] = []

    # 提示词注入（现有功能）
    prompt_injection: Optional[str] = None

    # 新增：自定义工具
    custom_tools: List[str] = []  # 工具名列表

    # 新增：前置检查函数
    prerequisite_check: Optional[Callable] = None

    # 新增：后置处理函数
    post_process: Optional[Callable] = None


class SkillRegistry:
    """技能注册表（参考 OpenCode）"""

    def __init__(self, skill_dirs: List[str]):
        self.skill_dirs = [Path(d) for d in skill_dirs]
        self._skills: Dict[str, Skill] = {}
        self._load_all_skills()

    def _load_all_skills(self):
        """加载所有技能"""
        for skill_dir in self.skill_dirs:
            if not skill_dir.exists():
                continue

            # 遍历技能目录
            for skill_path in skill_dir.iterdir():
                if not skill_path.is_dir():
                    continue

                # 查找 skill.json
                config_file = skill_path / "skill.json"
                if not config_file.exists():
                    continue

                # 加载技能
                skill = self._load_skill(skill_path)
                if skill:
                    self._skills[skill.name] = skill
                    print(f"[Skill] 加载技能: {skill.name}")

    def _load_skill(self, skill_path: Path) -> Optional[Skill]:
        """加载单个技能"""
        try:
            # 1. 加载配置
            config_file = skill_path / "skill.json"
            with open(config_file) as f:
                config = json.load(f)

            skill = Skill(
                name=config["skill_name"],
                description=config["description"],
                trigger_keywords=config.get("trigger_keywords", []),
                prompt_injection=config.get("content"),
                custom_tools=config.get("custom_tools", [])
            )

            # 2. 加载自定义代码（如果存在）
            code_file = skill_path / "skill.py"
            if code_file.exists():
                # 动态导入模块
                spec = importlib.util.spec_from_file_location(
                    f"skill_{skill.name}",
                    code_file
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 注册自定义函数
                if hasattr(module, "prerequisite_check"):
                    skill.prerequisite_check = module.prerequisite_check

                if hasattr(module, "post_process"):
                    skill.post_process = module.post_process

                # 注册自定义工具
                if hasattr(module, "register_tools"):
                    custom_tools = module.register_tools(tool_registry)
                    skill.custom_tools.extend(custom_tools)

            return skill

        except Exception as e:
            print(f"[Skill] 加载失败 {skill_path.name}: {e}")
            return None

    def get_skill(self, name: str) -> Optional[Skill]:
        """获取技能"""
        return self._skills.get(name)

    def match_skills(self, query: str) -> List[Skill]:
        """根据查询匹配技能"""
        matched = []
        for skill in self._skills.values():
            if any(kw in query for kw in skill.trigger_keywords):
                matched.append(skill)
        return matched

    def inject_skills(self, query: str, base_prompt: str) -> str:
        """
        注入技能到提示词（参考 OpenCode）

        返回: 增强后的提示词
        """
        matched_skills = self.match_skills(query)

        if not matched_skills:
            return base_prompt

        # 构建技能注入部分
        skill_sections = []
        for skill in matched_skills:
            if skill.prompt_injection:
                skill_sections.append(f"\n### {skill.name}\n{skill.prompt_injection}")

        # 拼接到 base_prompt
        enhanced_prompt = base_prompt + "\n\n" + "## 激活的技能\n" + "\n".join(skill_sections)

        return enhanced_prompt


# ===== 高级 Skill 示例 =====

# skills/tushare_helper/skill.json
{
  "skill_name": "tushare_helper",
  "description": "Tushare API 调用助手，自动处理限流和重试",
  "trigger_keywords": ["tushare", "金融数据", "股票数据"],
  "content": "【技能注入：Tushare 助手】\n使用 tushare_query_with_retry 工具代替直接调用 Tushare API。",
  "custom_tools": ["tushare_query_with_retry"]
}

# skills/tushare_helper/skill.py
import time
from typing import Dict, Any

def register_tools(tool_registry):
    """注册自定义工具"""

    class TushareRetryTool(BaseTool):
        """带重试的 Tushare 查询工具"""

        def __init__(self):
            super().__init__(
                name="tushare_query_with_retry",
                description="查询 Tushare 数据（自动处理限流）"
            )
            self.pro = ts.pro_api(conf.tushare_token)

        def validate_args(self, args: Dict[str, Any]) -> bool:
            return "api_name" in args and "params" in args

        def _execute_impl(self, args: Dict[str, Any], ctx: ToolContext) -> str:
            api_name = args["api_name"]
            params = args["params"]
            max_retries = args.get("max_retries", 3)

            for attempt in range(max_retries):
                try:
                    df = getattr(self.pro, api_name)(**params)

                    if df.empty:
                        return json.dumps({
                            "success": False,
                            "data": [],
                            "message": "数据为空"
                        })

                    return json.dumps({
                        "success": True,
                        "data": df.to_dict(orient="records"),
                        "message": f"查询成功，返回 {len(df)} 条数据"
                    })

                except Exception as e:
                    error_msg = str(e)

                    # 限流检测
                    if "429" in error_msg or "限流" in error_msg:
                        wait_time = 2 ** attempt  # 指数退避
                        print(f"[Tushare] 限流，等待 {wait_time} 秒...")
                        time.sleep(wait_time)
                        continue

                    # 其他错误
                    raise RuntimeError(f"Tushare 查询失败: {error_msg}")

            raise RuntimeError(f"Tushare 查询失败：重试 {max_retries} 次后仍失败")

    # 注册工具
    tool = TushareRetryTool()
    tool_registry.register(tool)

    return [tool.name]


# ===== 集成到 multi_agent.py =====

# 创建技能注册表
skill_registry = SkillRegistry(skill_dirs=[
    "./skills",  # 本地技能
    "~/.asa/skills"  # 全局技能
])

# 在 Supervisor 中使用
def supervisor_node(state: AgentState):
    """Supervisor - 自动注入技能"""
    query = state["messages"][-1].content

    # 获取基础 prompt
    base_prompt = agent_factory.get_system_prompt("supervisor")

    # 注入匹配的技能
    enhanced_prompt = skill_registry.inject_skills(query, base_prompt)

    # 使用增强后的 prompt
    model = get_chat_model(model_type="smart")
    response = model.invoke([
        SystemMessage(content=enhanced_prompt),
        *state["messages"]
    ])

    return {"messages": [response]}
```

**收益**：
- ✅ Skill 可以包含可执行代码
- ✅ 自动注入匹配的技能
- ✅ 支持自定义工具
- ✅ 热加载和版本管理

---

### ⭐ 低优先级（长期优化）

#### 6. **LSP 集成（代码智能）**

OpenCode 内置了 LSP 支持，可以：
- 代码补全
- 跳转到定义
- 查找引用
- 重命名符号

对于你的金融数据分析场景，LSP 可能不是必需的，但如果你将来扩展到代码生成/修改场景，可以考虑集成。

#### 7. **多模型支持**

OpenCode 支持多种 AI 提供商（Claude、GPT-4、Gemini 等）。

你目前使用阿里云通义千问，如果需要切换模型，可以参考 OpenCode 的 Provider 抽象层。

#### 8. **Web UI / Desktop App**

OpenCode 支持多种客户端（TUI、Web、Desktop）。

你目前使用 Gradio，可以参考 OpenCode 的客户端/服务器分离架构，实现：
- Web 界面（Next.js）
- 桌面应用（Tauri）
- 移动端（React Native）

---

## 📊 总结对比

| 特性 | 你的系统（ASA） | OpenCode | 借鉴建议 |
|------|----------------|----------|---------|
| **权限系统** | 简单白名单/黑名单 | 细粒度 glob 模式 | ⭐⭐⭐ 立即借鉴 |
| **Tool 接口** | 分散的 @tool 装饰器 | 统一 Tool.define 接口 | ⭐⭐⭐ 立即借鉴 |
| **Session 管理** | LangGraph MemorySaver | 持久化 + 压缩 | ⭐⭐⭐ 立即借鉴 |
| **Agent 嵌套** | 中心化 Supervisor | 支持子任务委托 | ⭐⭐ 渐进增强 |
| **Skill 系统** | 静态 JSON | 可执行代码 + 自定义工具 | ⭐⭐ 渐进增强 |
| **LSP 集成** | 无 | 内置支持 | ⭐ 长期考虑 |
| **多模型支持** | 单一提供商 | Provider 抽象层 | ⭐ 长期考虑 |
| **客户端多样性** | Gradio Web | TUI/Web/Desktop | ⭐ 长期考虑 |

---

## 🚀 实施路线图

### 第 1 周：权限系统升级
1. 实现 `ToolsConfig` 的高级规则
2. 在 `agents.yaml` 中配置权限
3. 在工具调用前集成权限检查

### 第 2 周：统一 Tool 接口
1. 实现 `BaseTool` 基类
2. 迁移现有工具到新接口
3. 实现 `ToolRegistry`
4. 集成到 `multi_agent.py`

### 第 3 周：Session 持久化
1. 实现 `SessionManager`
2. 集成到 LangGraph MemorySaver
3. 实现消息压缩
4. 添加会话统计和分析

### 第 4 周：Agent 嵌套
1. 实现 `TaskTool`
2. 创建专门的子 Agent（data_analyst, chart_maker 等）
3. 在 Supervisor 中集成子任务委托

### 第 5 周：Skill 系统升级
1. 实现 `SkillRegistry`
2. 支持 skill.py 代码执行
3. 实现自定义工具注册
4. 迁移现有 skills.json

---

## 💡 关键要点

1. **优先级排序**：
   - 先做权限系统和 Tool 接口（安全性和规范性）
   - 再做 Session 管理（可观测性）
   - 最后做 Agent 嵌套和 Skill 升级（功能增强）

2. **渐进式迁移**：
   - 保持向后兼容
   - 逐步迁移现有功能
   - 不要一次性重写

3. **测试驱动**：
   - 每个新功能都要写测试
   - 确保现有功能不被破坏

4. **文档同步**：
   - 更新 README
   - 添加使用示例
   - 记录设计决策

---

希望这份分析对你有帮助！如果需要我深入讲解某个部分的实现细节，请告诉我。🚀
