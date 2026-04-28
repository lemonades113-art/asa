# OpenCode 关键代码示例与实现细节

## 一、Agent 实现细节

### 1.1 完整的 Agent 配置

让我们看看实际代码中 agent 是如何配置的：

```typescript
// packages/opencode/src/agent/agent.ts (第76-114行)

const result: Record<string, Info> = {
  // BUILD AGENT - 默认的全功能 agent
  build: {
    name: "build",
    description: "The default agent. Executes tools based on configured permissions.",
    options: {},
    permission: PermissionNext.merge(
      defaults,  // 基础权限
      PermissionNext.fromConfig({
        question: "allow",      // 允许提问用户
        plan_enter: "allow",    // 允许进入规划模式
      }),
      user,  // 用户自定义权限
    ),
    mode: "primary",   // 主 agent
    native: true,      // 内置 agent
  },

  // PLAN AGENT - 只读分析 agent
  plan: {
    name: "plan",
    description: "Plan mode. Disallows all edit tools.",
    options: {},
    permission: PermissionNext.merge(
      defaults,
      PermissionNext.fromConfig({
        question: "allow",
        plan_exit: "allow",
        // 外部目录白名单
        external_directory: {
          [path.join(Global.Path.data, "plans", "*")]: "allow",
        },
        // 编辑权限：默认拒绝，只允许编辑计划文件
        edit: {
          "*": "deny",
          [path.join(".opencode", "plans", "*.md")]: "allow",
          [path.relative(
            Instance.worktree,
            path.join(Global.Path.data, "plans", "*.md")
          )]: "allow",
        },
      }),
      user,
    ),
    mode: "primary",
    native: true,
  },

  // GENERAL AGENT - 通用子任务 agent
  general: {
    name: "general",
    description: `General-purpose agent for researching complex questions and executing multi-step tasks.`,
    permission: PermissionNext.merge(
      defaults,
      PermissionNext.fromConfig({
        todoread: "deny",   // 不需要看 todo
        todowrite: "deny",  // 不需要写 todo
      }),
      user,
    ),
    options: {},
    mode: "subagent",  // 只能被其他 agent 调用
    native: true,
  },

  // EXPLORE AGENT - 专注代码探索
  explore: {
    name: "explore",
    permission: PermissionNext.merge(
      defaults,
      PermissionNext.fromConfig({
        "*": "deny",  // 默认拒绝所有操作
        // 白名单：只允许只读操作
        grep: "allow",
        glob: "allow",
        list: "allow",
        bash: "allow",
        webfetch: "allow",
        websearch: "allow",
        codesearch: "allow",
        read: "allow",
        external_directory: {
          "*": "ask",
          ...Object.fromEntries(whitelistedDirs.map((dir) => [dir, "allow"])),
        },
      }),
      user,
    ),
    description: `Fast agent specialized for exploring codebases...`,
    prompt: PROMPT_EXPLORE,  // 自定义系统提示词
    options: {},
    mode: "subagent",
    native: true,
  },
};
```

**关键设计**：
- 使用 `merge` 函数合并权限：defaults → agent config → user config
- Plan agent 通过权限系统实现只读：`edit: { "*": "deny" }`
- Explore agent 明确白名单：只允许读取操作

---

### 1.2 权限系统实现

```typescript
// packages/opencode/src/permission/next.ts

export namespace PermissionNext {
  // 权限类型
  export type Rule = "allow" | "ask" | "deny";

  // 权限规则集（支持嵌套和 glob 模式）
  export type Ruleset =
    | Rule
    | {
        [key: string]: Ruleset;
      };

  // 合并权限规则
  export function merge(...rulesets: Ruleset[]): Ruleset {
    return rulesets.reduce((acc, ruleset) => {
      if (typeof ruleset === "string") return ruleset;
      if (typeof acc === "string") return ruleset;

      // 深度合并对象
      return mergeDeep(acc, ruleset);
    }, {});
  }

  // 从配置对象创建规则集
  export function fromConfig(config: Record<string, any>): Ruleset {
    const result: any = {};
    for (const [key, value] of Object.entries(config)) {
      if (typeof value === "string") {
        result[key] = value as Rule;
      } else if (typeof value === "object") {
        result[key] = fromConfig(value);
      }
    }
    return result;
  }

  // 检查权限
  export function check(
    ruleset: Ruleset,
    path: string[]  // 例如: ["edit", "src/index.ts"]
  ): Rule {
    if (typeof ruleset === "string") return ruleset;

    const [first, ...rest] = path;

    // 1. 精确匹配
    if (first in ruleset) {
      const subrule = ruleset[first];
      if (rest.length === 0) {
        return typeof subrule === "string" ? subrule : "deny";
      }
      return check(subrule, rest);
    }

    // 2. Glob 模式匹配
    for (const [pattern, subrule] of Object.entries(ruleset)) {
      if (minimatch(first, pattern)) {
        if (rest.length === 0) {
          return typeof subrule === "string" ? subrule : "deny";
        }
        return check(subrule, rest);
      }
    }

    // 3. 通配符
    if ("*" in ruleset) {
      const subrule = ruleset["*"];
      return typeof subrule === "string" ? subrule : check(subrule, rest);
    }

    // 4. 默认拒绝
    return "deny";
  }
}
```

**使用示例**：
```typescript
const permissions = {
  "*": "allow",
  read: {
    "*": "allow",
    "*.env": "ask",      // .env 文件需要询问
    "secrets/*": "deny", // secrets 目录拒绝
  },
  edit: {
    "*": "deny",
    "src/**/*.ts": "allow",  // 只允许编辑 src 下的 ts 文件
  },
};

// 检查权限
PermissionNext.check(permissions, ["read", "config.json"]); // "allow"
PermissionNext.check(permissions, ["read", ".env"]);        // "ask"
PermissionNext.check(permissions, ["read", "secrets/key.txt"]); // "deny"
PermissionNext.check(permissions, ["edit", "src/index.ts"]); // "allow"
PermissionNext.check(permissions, ["edit", "package.json"]); // "deny"
```

---

## 二、Tool 系统深入

### 2.1 Edit Tool 实现

Edit 是最复杂的 tool 之一，让我们看看它的实现：

```typescript
// packages/opencode/src/tool/edit.ts

export const Edit = Tool.define("edit", async (initCtx) => ({
  description: "Performs exact string replacements in files",
  parameters: z.object({
    file_path: z.string(),
    old_string: z.string(),
    new_string: z.string(),
    replace_all: z.boolean().default(false),
  }),

  async execute(args, ctx) {
    // 1. 解析文件路径
    const filePath = path.isAbsolute(args.file_path)
      ? args.file_path
      : path.join(Instance.worktree, args.file_path);

    // 2. 权限检查
    await ctx.ask({
      action: "edit",
      path: filePath,
      metadata: {
        oldString: args.old_string.slice(0, 100),
        newString: args.new_string.slice(0, 100),
      },
    });

    // 3. 读取文件
    const content = await Bun.file(filePath).text();

    // 4. 检查 old_string 是否存在
    const occurrences = countOccurrences(content, args.old_string);
    if (occurrences === 0) {
      throw new Error(
        `String not found in file. The old_string does not exist in ${args.file_path}`
      );
    }

    // 5. 检查唯一性（如果不是 replace_all）
    if (!args.replace_all && occurrences > 1) {
      throw new Error(
        `Found ${occurrences} occurrences of old_string. ` +
        `Either provide more context or use replace_all: true`
      );
    }

    // 6. 执行替换
    const newContent = args.replace_all
      ? content.replaceAll(args.old_string, args.new_string)
      : content.replace(args.old_string, args.new_string);

    // 7. 写入文件
    await Bun.write(filePath, newContent);

    // 8. 生成 diff
    const diff = generateDiff(content, newContent);

    // 9. 返回结果
    return {
      title: `Edited ${path.basename(filePath)}`,
      metadata: {
        path: filePath,
        occurrences: args.replace_all ? occurrences : 1,
      },
      output: `Successfully edited ${filePath}\n\n${diff}`,
    };
  },
}));

// 工具函数
function countOccurrences(text: string, search: string): number {
  let count = 0;
  let pos = 0;
  while ((pos = text.indexOf(search, pos)) !== -1) {
    count++;
    pos += search.length;
  }
  return count;
}

function generateDiff(oldContent: string, newContent: string): string {
  const diffLines = diffWords(oldContent, newContent);
  return diffLines
    .map((part) => {
      if (part.added) return `+ ${part.value}`;
      if (part.removed) return `- ${part.value}`;
      return `  ${part.value}`;
    })
    .join("\n");
}
```

**关键特性**：
- ✅ 精确字符串替换（不是行号，避免并发问题）
- ✅ 自动检测唯一性（防止误操作）
- ✅ 支持批量替换（replace_all）
- ✅ 生成 diff 供用户审查
- ✅ 权限检查集成

---

### 2.2 Task Tool（子任务委托）

```typescript
// packages/opencode/src/tool/task.ts

export const Task = Tool.define("task", {
  description: "Launch a new agent to handle complex tasks",
  parameters: z.object({
    description: z.string(),  // 任务简短描述
    prompt: z.string(),       // 详细任务内容
    subagent_type: z.string(), // agent 类型
    model: z.enum(["sonnet", "opus", "haiku"]).optional(),
    run_in_background: z.boolean().optional(),
    resume: z.string().optional(),  // 恢复之前的 agent
  }),

  async execute(args, ctx) {
    // 1. 获取子 agent 配置
    const agentInfo = await Agent.get(args.subagent_type);
    if (!agentInfo) {
      throw new Error(`Unknown agent type: ${args.subagent_type}`);
    }
    if (agentInfo.mode === "primary") {
      throw new Error(`Cannot invoke primary agent as subagent`);
    }

    // 2. 创建子会话
    const childSession = await Session.create({
      projectID: ctx.sessionID,
      parentID: ctx.sessionID,
      agent: args.subagent_type,
      directory: Instance.worktree,
    });

    // 3. 准备消息
    const messages: Message[] = [
      {
        role: "system",
        content: agentInfo.prompt || "",
      },
      {
        role: "user",
        content: args.prompt,
      },
    ];

    // 4. 执行子任务
    if (args.run_in_background) {
      // 后台执行
      Session.runAsync(childSession.id, messages).catch(console.error);

      return {
        title: args.description,
        metadata: {
          childSessionID: childSession.id,
          background: true,
        },
        output: `Task started in background. Session ID: ${childSession.id}`,
      };
    } else {
      // 前台执行
      const result = await Session.run(childSession.id, messages);

      return {
        title: args.description,
        metadata: {
          childSessionID: childSession.id,
          background: false,
        },
        output: result.output,
      };
    }
  },
});
```

**使用场景**：
```typescript
// 主 agent 可以这样委托任务：

// 场景1：深度代码探索
await Task.execute({
  subagent_type: "explore",
  description: "探索认证系统",
  prompt: `
    请分析这个项目的认证系统：
    1. 找到所有认证相关的文件
    2. 识别使用的认证策略（JWT/Session/OAuth）
    3. 找到用户模型定义
    4. 总结认证流程
  `,
});

// 场景2：并行搜索
await Promise.all([
  Task.execute({
    subagent_type: "general",
    description: "搜索 API 端点",
    prompt: "列出所有 REST API 端点及其用途",
  }),
  Task.execute({
    subagent_type: "general",
    description: "搜索数据库模型",
    prompt: "列出所有数据库模型和关系",
  }),
]);
```

---

### 2.3 LSP Tool（代码智能）

```typescript
// packages/opencode/src/tool/lsp.ts

export const LSP = Tool.define("lsp", async (initCtx) => {
  // 初始化 LSP 客户端
  const lspClients = new Map<string, LanguageClient>();

  async function getClient(filePath: string): Promise<LanguageClient> {
    const language = detectLanguage(filePath);
    if (lspClients.has(language)) {
      return lspClients.get(language)!;
    }

    // 启动 LSP 服务器
    const client = await startLanguageServer(language);
    lspClients.set(language, client);
    return client;
  }

  return {
    description: "Interact with Language Server Protocol",
    parameters: z.object({
      action: z.enum([
        "completion",
        "definition",
        "references",
        "hover",
        "rename",
        "codeAction",
      ]),
      file_path: z.string(),
      line: z.number(),
      column: z.number(),
      new_name: z.string().optional(),
    }),

    async execute(args, ctx) {
      const client = await getClient(args.file_path);

      // 根据 action 调用不同的 LSP 方法
      let result: any;
      switch (args.action) {
        case "completion":
          result = await client.sendRequest("textDocument/completion", {
            textDocument: { uri: fileToUri(args.file_path) },
            position: { line: args.line, character: args.column },
          });
          break;

        case "definition":
          result = await client.sendRequest("textDocument/definition", {
            textDocument: { uri: fileToUri(args.file_path) },
            position: { line: args.line, character: args.column },
          });
          break;

        case "references":
          result = await client.sendRequest("textDocument/references", {
            textDocument: { uri: fileToUri(args.file_path) },
            position: { line: args.line, character: args.column },
            context: { includeDeclaration: true },
          });
          break;

        case "rename":
          if (!args.new_name) {
            throw new Error("new_name is required for rename action");
          }
          result = await client.sendRequest("textDocument/rename", {
            textDocument: { uri: fileToUri(args.file_path) },
            position: { line: args.line, character: args.column },
            newName: args.new_name,
          });
          break;

        // ... 其他 action
      }

      return {
        title: `LSP ${args.action}`,
        metadata: { action: args.action, file: args.file_path },
        output: JSON.stringify(result, null, 2),
      };
    },
  };
});

// 检测文件语言
function detectLanguage(filePath: string): string {
  const ext = path.extname(filePath);
  const languageMap: Record<string, string> = {
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".py": "python",
    ".rs": "rust",
    ".go": "go",
    // ... 更多语言
  };
  return languageMap[ext] || "plaintext";
}

// 启动 LSP 服务器
async function startLanguageServer(language: string): Promise<LanguageClient> {
  const serverMap: Record<string, { command: string; args: string[] }> = {
    typescript: {
      command: "typescript-language-server",
      args: ["--stdio"],
    },
    python: {
      command: "pylsp",
      args: [],
    },
    rust: {
      command: "rust-analyzer",
      args: [],
    },
    // ... 更多语言
  };

  const serverInfo = serverMap[language];
  if (!serverInfo) {
    throw new Error(`No LSP server configured for ${language}`);
  }

  // 启动服务器进程
  const serverProcess = Bun.spawn([serverInfo.command, ...serverInfo.args], {
    stdin: "pipe",
    stdout: "pipe",
    stderr: "pipe",
  });

  // 创建 LSP 客户端
  const client = new LanguageClient({
    process: serverProcess,
    rootPath: Instance.worktree,
  });

  await client.initialize();
  return client;
}
```

**实际应用**：
```typescript
// AI 可以利用 LSP 进行智能操作

// 1. 查找函数定义
await LSP.execute({
  action: "definition",
  file_path: "src/index.ts",
  line: 10,
  column: 5,
});
// 返回: { uri: "file:///src/utils.ts", range: { start: { line: 20 } } }

// 2. 查找所有引用
await LSP.execute({
  action: "references",
  file_path: "src/utils.ts",
  line: 20,
  column: 15,
});
// 返回: [
//   { uri: "file:///src/index.ts", range: { start: { line: 10 } } },
//   { uri: "file:///src/app.ts", range: { start: { line: 5 } } },
// ]

// 3. 重命名符号
await LSP.execute({
  action: "rename",
  file_path: "src/utils.ts",
  line: 20,
  column: 15,
  new_name: "newFunctionName",
});
// 返回: WorkspaceEdit 包含所有需要修改的位置

// 4. 代码补全
await LSP.execute({
  action: "completion",
  file_path: "src/index.ts",
  line: 15,
  column: 10,
});
// 返回: [
//   { label: "functionName", kind: "Function", detail: "(param: string) => void" },
//   { label: "variableName", kind: "Variable", detail: "string" },
// ]
```

---

## 三、Session 和消息管理

### 3.1 Session 运行逻辑

```typescript
// packages/opencode/src/session/index.ts

export namespace Session {
  export async function run(
    sessionID: string,
    userMessage: string
  ): Promise<{ output: string; messages: Message[] }> {
    // 1. 加载会话信息
    const session = await Session.get(sessionID);
    const agent = await Agent.get(session.agent);

    // 2. 加载历史消息
    const history = await Message.list(sessionID);

    // 3. 构建系统提示词
    const systemPrompt = await SessionPrompt.build(session, agent);

    // 4. 准备消息
    const messages: Message[] = [
      { role: "system", content: systemPrompt },
      ...history,
      { role: "user", content: userMessage },
    ];

    // 5. 获取模型配置
    const provider = await Provider.get(agent.model?.providerID || "anthropic");
    const model = provider.model(agent.model?.modelID || "claude-opus-4");

    // 6. 加载可用工具
    const tools = await loadTools(agent);

    // 7. 流式调用 LLM
    let assistantMessage = "";
    const stream = await streamText({
      model,
      messages,
      tools,
      temperature: agent.temperature ?? 0.7,
      topP: agent.topP ?? 0.95,
      maxSteps: agent.steps ?? 10,  // 最多 10 轮工具调用
    });

    // 8. 处理流式响应
    for await (const chunk of stream) {
      if (chunk.type === "text-delta") {
        // 文本输出
        assistantMessage += chunk.textDelta;
        // 实时发送给客户端
        await Bus.publish(Session.Event.StreamChunk, {
          sessionID,
          content: chunk.textDelta,
        });
      } else if (chunk.type === "tool-call") {
        // 工具调用
        const toolResult = await executeToolCall(
          sessionID,
          chunk,
          agent.permission
        );

        // 发送工具结果回 LLM
        stream.addToolResult(toolResult);
      } else if (chunk.type === "finish") {
        // 完成
        break;
      }
    }

    // 9. 保存消息
    await Message.save(sessionID, [
      { role: "user", content: userMessage },
      { role: "assistant", content: assistantMessage },
    ]);

    // 10. 更新会话统计
    await Session.update(sessionID, {
      time: { updated: Date.now() },
    });

    return {
      output: assistantMessage,
      messages: [...messages, { role: "assistant", content: assistantMessage }],
    };
  }

  // 执行工具调用
  async function executeToolCall(
    sessionID: string,
    toolCall: ToolCall,
    permission: PermissionNext.Ruleset
  ): Promise<ToolResult> {
    const tool = await Tool.get(toolCall.toolID);

    // 权限检查
    const allowed = await checkPermission(permission, toolCall);
    if (!allowed) {
      return {
        toolCallID: toolCall.id,
        output: "Permission denied",
        error: true,
      };
    }

    try {
      // 执行工具
      const result = await tool.execute(toolCall.args, {
        sessionID,
        messageID: toolCall.messageID,
        agent: agent.name,
        // ... 其他上下文
      });

      return {
        toolCallID: toolCall.id,
        output: result.output,
        metadata: result.metadata,
      };
    } catch (error) {
      return {
        toolCallID: toolCall.id,
        output: `Error: ${error.message}`,
        error: true,
      };
    }
  }
}
```

---

### 3.2 消息压缩（Compaction）

```typescript
// packages/opencode/src/session/compaction.ts

export namespace Compaction {
  const RECENT_MESSAGE_COUNT = 10;  // 保留最近 10 条消息
  const MAX_CONTEXT_LENGTH = 100000; // 最大上下文长度（字符）

  export async function compact(sessionID: string) {
    // 1. 获取所有消息
    const messages = await Message.list(sessionID);

    // 2. 计算上下文长度
    const totalLength = messages.reduce(
      (sum, msg) => sum + msg.content.length,
      0
    );

    // 3. 检查是否需要压缩
    if (totalLength < MAX_CONTEXT_LENGTH) {
      return; // 不需要压缩
    }

    // 4. 分割消息
    const recent = messages.slice(-RECENT_MESSAGE_COUNT);
    const old = messages.slice(0, -RECENT_MESSAGE_COUNT);

    // 5. 使用专门的 compaction agent 生成摘要
    const summary = await summarize(sessionID, old);

    // 6. 替换旧消息
    const compacted = [
      {
        role: "system" as const,
        content: `Previous conversation summary:\n\n${summary}`,
        metadata: { compacted: true, originalCount: old.length },
      },
      ...recent,
    ];

    // 7. 更新数据库
    await Message.replaceAll(sessionID, compacted);

    // 8. 记录压缩时间
    await Session.update(sessionID, {
      time: { compacting: Date.now() },
    });

    console.log(
      `Compacted ${old.length} messages into summary (${summary.length} chars)`
    );
  }

  // 使用 compaction agent 生成摘要
  async function summarize(
    sessionID: string,
    messages: Message[]
  ): Promise<string> {
    const compactionAgent = await Agent.get("compaction");

    const prompt = `
Summarize the following conversation, preserving:
- Key decisions and changes made
- Important context for future interactions
- File paths and code locations mentioned
- User preferences and instructions

Messages:
${messages.map((m) => `${m.role}: ${m.content}`).join("\n\n")}
`;

    const response = await generateText({
      model: provider.model("claude-haiku-4"),  // 使用便宜的模型
      prompt,
      temperature: 0.3,  // 低温度，更确定性
    });

    return response.text;
  }

  // 自动触发压缩
  export function autoCompact(sessionID: string) {
    // 每 20 条消息检查一次
    const messageCount = await Message.count(sessionID);
    if (messageCount % 20 === 0) {
      await compact(sessionID);
    }
  }
}
```

---

## 四、客户端实现（TUI）

### 4.1 终端界面架构

OpenCode 使用 **OpenTUI** + **SolidJS** 构建终端界面：

```typescript
// packages/console/app/src/App.tsx

import { createSignal, For, Show } from "solid-js";
import { Box, Text, Input } from "@opentui/solid";

export function App() {
  const [messages, setMessages] = createSignal<Message[]>([]);
  const [input, setInput] = createSignal("");
  const [streaming, setStreaming] = createSignal(false);

  // WebSocket 连接到服务器
  const ws = new WebSocket("ws://localhost:3000/session");

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === "message") {
      setMessages((prev) => [...prev, data.message]);
    } else if (data.type === "stream-chunk") {
      // 流式更新最后一条消息
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant") {
          return [
            ...prev.slice(0, -1),
            { ...last, content: last.content + data.content },
          ];
        }
        return [...prev, { role: "assistant", content: data.content }];
      });
    } else if (data.type === "tool-call") {
      // 显示工具调用
      setMessages((prev) => [
        ...prev,
        {
          role: "tool",
          tool: data.toolName,
          args: data.args,
          status: "running",
        },
      ]);
    }
  };

  const sendMessage = async () => {
    const text = input();
    if (!text.trim()) return;

    // 添加用户消息
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);

    // 发送到服务器
    ws.send(JSON.stringify({ type: "message", content: text }));
  };

  return (
    <Box flexDirection="column" height="100%">
      {/* 消息列表 */}
      <Box flexDirection="column" flexGrow={1} overflow="auto">
        <For each={messages()}>
          {(msg) => (
            <Show
              when={msg.role === "user"}
              fallback={
                <Show
                  when={msg.role === "assistant"}
                  fallback={<ToolCallMessage message={msg} />}
                >
                  <AssistantMessage message={msg} />
                </Show>
              }
            >
              <UserMessage message={msg} />
            </Show>
          )}
        </For>
      </Box>

      {/* 输入框 */}
      <Box borderStyle="single" borderColor="blue">
        <Input
          value={input()}
          onChange={setInput}
          onSubmit={sendMessage}
          placeholder="Type a message..."
          disabled={streaming()}
        />
      </Box>
    </Box>
  );
}

// 用户消息组件
function UserMessage(props: { message: Message }) {
  return (
    <Box padding={1} borderStyle="round" borderColor="green">
      <Text color="green" bold>
        You:
      </Text>
      <Text>{props.message.content}</Text>
    </Box>
  );
}

// AI 消息组件
function AssistantMessage(props: { message: Message }) {
  return (
    <Box padding={1} borderStyle="round" borderColor="blue">
      <Text color="blue" bold>
        Assistant:
      </Text>
      <Text>{props.message.content}</Text>
    </Box>
  );
}

// 工具调用组件
function ToolCallMessage(props: { message: ToolMessage }) {
  return (
    <Box padding={1} borderStyle="round" borderColor="yellow">
      <Text color="yellow" bold>
        🔧 {props.message.tool}
      </Text>
      <Text color="gray">{JSON.stringify(props.message.args, null, 2)}</Text>
      <Show when={props.message.status === "running"}>
        <Text color="yellow">⏳ Running...</Text>
      </Show>
    </Box>
  );
}
```

---

## 五、实用技巧和最佳实践

### 5.1 自定义 Agent

用户可以在 `~/.opencode/agents/` 创建自定义 agent：

```json
// ~/.opencode/agents/reviewer.json
{
  "name": "reviewer",
  "description": "Code review specialist",
  "mode": "primary",
  "prompt": "You are an expert code reviewer. When reviewing code:\n1. Check for bugs and security issues\n2. Suggest improvements for readability\n3. Verify best practices\n4. Provide constructive feedback",
  "permission": {
    "*": "deny",
    "read": "allow",
    "grep": "allow",
    "glob": "allow",
    "bash": {
      "*": "deny",
      "git diff": "allow",
      "git log": "allow"
    },
    "question": "allow"
  },
  "model": {
    "providerID": "anthropic",
    "modelID": "claude-opus-4"
  }
}
```

使用：
```bash
opencode --agent reviewer
```

---

### 5.2 自定义 Tool

通过插件系统添加自定义工具：

```typescript
// ~/.opencode/plugins/my-plugin/index.ts

import { Tool } from "opencode/tool";
import z from "zod";

export const MyTool = Tool.define("my-tool", {
  description: "My custom tool",
  parameters: z.object({
    param: z.string(),
  }),

  async execute(args, ctx) {
    // 自定义逻辑
    const result = await doSomething(args.param);

    return {
      title: "My Tool Result",
      metadata: {},
      output: result,
    };
  },
});

// 注册工具
export function activate() {
  Tool.register(MyTool);
}
```

---

### 5.3 Skill 系统

创建可复用的技能：

```bash
# ~/.opencode/skills/deploy/skill.json
{
  "name": "deploy",
  "description": "Deploy application to production",
  "prompt": "执行部署流程：\n1. 运行测试\n2. 构建生产版本\n3. 备份当前版本\n4. 部署新版本\n5. 运行烟雾测试\n6. 回滚（如果失败）",
  "tools": ["bash", "read", "write"]
}
```

使用：
```
用户：/deploy
```

---

## 六、总结

OpenCode 的架构设计体现了以下核心理念：

1. **模块化**：清晰的职责分离（agent、tool、session、permission）
2. **可扩展**：通过 agent、tool、skill 支持自定义
3. **安全性**：细粒度权限控制 + 沙箱执行
4. **提供商中立**：支持多种 AI 模型
5. **用户友好**：TUI、Desktop、VS Code 多种界面

这些设计值得在你自己的 agent 项目中借鉴和应用。
