# 如何借鉴 OpenCode 构建自己的 AI Agent

## 一、快速上手：最小可行架构

如果你想构建一个类似 OpenCode 的 agent，可以从最小架构开始：

### 1.1 核心组件（MVP）

```
my-agent/
├── src/
│   ├── agent/           # Agent 定义
│   │   └── index.ts
│   ├── tool/           # Tool 系统
│   │   ├── tool.ts    # Tool 接口
│   │   ├── read.ts    # 读文件
│   │   ├── write.ts   # 写文件
│   │   └── bash.ts    # 执行命令
│   ├── session/        # 会话管理
│   │   └── index.ts
│   ├── permission/     # 权限系统
│   │   └── index.ts
│   └── index.ts        # 入口
└── package.json
```

### 1.2 最小实现

**Step 1: Tool 接口定义**

```typescript
// src/tool/tool.ts
import z from "zod";

export namespace Tool {
  export interface Context {
    sessionID: string;
    abort: AbortSignal;
  }

  export interface Info<P extends z.ZodType = z.ZodType> {
    id: string;
    description: string;
    parameters: P;
    execute(
      args: z.infer<P>,
      ctx: Context
    ): Promise<{
      output: string;
      metadata?: Record<string, any>;
    }>;
  }

  // Tool 注册表
  const registry = new Map<string, Info>();

  export function define<P extends z.ZodType>(
    id: string,
    info: Omit<Info<P>, "id">
  ): Info<P> {
    const tool = { id, ...info };
    registry.set(id, tool);
    return tool;
  }

  export function get(id: string): Info | undefined {
    return registry.get(id);
  }

  export function all(): Info[] {
    return Array.from(registry.values());
  }
}
```

**Step 2: 实现基础 Tools**

```typescript
// src/tool/read.ts
import { Tool } from "./tool";
import z from "zod";
import fs from "fs/promises";

export const Read = Tool.define("read", {
  description: "Read file contents",
  parameters: z.object({
    file_path: z.string(),
  }),

  async execute(args, ctx) {
    const content = await fs.readFile(args.file_path, "utf-8");
    return {
      output: content,
      metadata: { path: args.file_path },
    };
  },
});
```

```typescript
// src/tool/bash.ts
import { Tool } from "./tool";
import z from "zod";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

export const Bash = Tool.define("bash", {
  description: "Execute bash command",
  parameters: z.object({
    command: z.string(),
  }),

  async execute(args, ctx) {
    const { stdout, stderr } = await execAsync(args.command);
    return {
      output: stdout || stderr,
      metadata: { command: args.command },
    };
  },
});
```

**Step 3: Session 管理**

```typescript
// src/session/index.ts
import { streamText } from "ai";
import { anthropic } from "@ai-sdk/anthropic";
import { Tool } from "../tool/tool";

export namespace Session {
  interface Message {
    role: "user" | "assistant" | "system";
    content: string;
  }

  const sessions = new Map<
    string,
    {
      id: string;
      messages: Message[];
    }
  >();

  export function create(id: string) {
    sessions.set(id, { id, messages: [] });
    return sessions.get(id)!;
  }

  export async function run(sessionID: string, userMessage: string) {
    const session = sessions.get(sessionID);
    if (!session) throw new Error("Session not found");

    // 添加用户消息
    session.messages.push({ role: "user", content: userMessage });

    // 获取所有工具
    const tools = Object.fromEntries(
      Tool.all().map((tool) => [
        tool.id,
        {
          description: tool.description,
          parameters: tool.parameters,
          execute: async (args: any) => {
            const result = await tool.execute(args, {
              sessionID,
              abort: new AbortController().signal,
            });
            return result.output;
          },
        },
      ])
    );

    // 调用 LLM
    const stream = await streamText({
      model: anthropic("claude-3-5-sonnet-20241022"),
      messages: session.messages,
      tools,
    });

    let assistantMessage = "";

    // 处理流式响应
    for await (const chunk of stream.textStream) {
      assistantMessage += chunk;
      process.stdout.write(chunk);
    }

    // 保存助手消息
    session.messages.push({ role: "assistant", content: assistantMessage });

    return assistantMessage;
  }
}
```

**Step 4: 入口文件**

```typescript
// src/index.ts
import { Session } from "./session";
import { Read } from "./tool/read";
import { Bash } from "./tool/bash";

async function main() {
  // 创建会话
  const session = Session.create("session_1");

  // 交互循环
  const readline = require("readline");
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });

  console.log("AI Agent ready. Type your message:");

  rl.on("line", async (input: string) => {
    if (input === "exit") {
      rl.close();
      return;
    }

    await Session.run(session.id, input);
    console.log("\n---\n");
  });
}

main();
```

这就是一个最小可行的 agent！只有 ~200 行代码，但已经具备：
- ✅ Tool 系统
- ✅ Session 管理
- ✅ LLM 集成
- ✅ 流式输出

---

## 二、进阶：添加权限系统

### 2.1 实现简单的权限检查

```typescript
// src/permission/index.ts

export type Permission = "allow" | "deny" | "ask";

export interface PermissionRule {
  [key: string]: Permission | PermissionRule;
}

export class PermissionChecker {
  constructor(private rules: PermissionRule) {}

  check(path: string[]): Permission {
    let current: any = this.rules;

    for (const segment of path) {
      if (typeof current === "string") return current as Permission;
      if (segment in current) {
        current = current[segment];
      } else if ("*" in current) {
        current = current["*"];
      } else {
        return "deny"; // 默认拒绝
      }
    }

    return typeof current === "string" ? current : "deny";
  }

  async ask(action: string, resource: string): Promise<boolean> {
    const permission = this.check([action, resource]);

    if (permission === "allow") return true;
    if (permission === "deny") return false;

    // ask: 询问用户
    const readline = require("readline");
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });

    return new Promise((resolve) => {
      rl.question(
        `Allow ${action} on ${resource}? (y/n): `,
        (answer: string) => {
          rl.close();
          resolve(answer.toLowerCase() === "y");
        }
      );
    });
  }
}
```

### 2.2 集成到 Tool 系统

```typescript
// src/tool/tool.ts (修改)

export namespace Tool {
  export interface Context {
    sessionID: string;
    abort: AbortSignal;
    permission: PermissionChecker; // 添加
  }

  export interface Info<P extends z.ZodType = z.ZodType> {
    id: string;
    description: string;
    parameters: P;
    requiresPermission?: boolean; // 添加
    execute(
      args: z.infer<P>,
      ctx: Context
    ): Promise<{
      output: string;
      metadata?: Record<string, any>;
    }>;
  }

  // 修改执行逻辑
  export async function execute(
    toolID: string,
    args: any,
    ctx: Context
  ): Promise<{ output: string; metadata?: Record<string, any> }> {
    const tool = registry.get(toolID);
    if (!tool) throw new Error(`Tool ${toolID} not found`);

    // 权限检查
    if (tool.requiresPermission) {
      const allowed = await ctx.permission.ask(toolID, JSON.stringify(args));
      if (!allowed) {
        throw new Error(`Permission denied for ${toolID}`);
      }
    }

    return tool.execute(args, ctx);
  }
}
```

### 2.3 使用示例

```typescript
// 定义权限规则
const permissions = new PermissionChecker({
  read: "allow", // 允许读取
  write: "ask", // 写入需要询问
  bash: {
    "*": "ask", // 默认询问
    "ls *": "allow", // ls 命令允许
    "rm -rf *": "deny", // 危险命令拒绝
  },
});

// 在 session 中使用
await Tool.execute("bash", { command: "ls -la" }, {
  sessionID: "session_1",
  abort: new AbortController().signal,
  permission: permissions,
});
```

---

## 三、高级特性：多 Agent 系统

### 3.1 Agent 定义

```typescript
// src/agent/index.ts

export interface Agent {
  id: string;
  name: string;
  description: string;
  systemPrompt: string;
  tools: string[]; // Tool IDs
  permissions: PermissionRule;
  maxSteps?: number;
}

export const agents: Record<string, Agent> = {
  developer: {
    id: "developer",
    name: "Developer Agent",
    description: "Full access development agent",
    systemPrompt: `You are a helpful development assistant.
You can read, write, and execute code.
Use tools to help the user accomplish their tasks.`,
    tools: ["read", "write", "bash", "edit"],
    permissions: {
      "*": "allow",
      bash: {
        "rm -rf /": "deny",
      },
    },
    maxSteps: 10,
  },

  reviewer: {
    id: "reviewer",
    name: "Code Reviewer",
    description: "Read-only code review agent",
    systemPrompt: `You are an expert code reviewer.
Analyze code for bugs, security issues, and best practices.
You cannot modify files, only read and analyze them.`,
    tools: ["read", "grep", "glob"],
    permissions: {
      read: "allow",
      grep: "allow",
      glob: "allow",
      "*": "deny",
    },
    maxSteps: 5,
  },

  explorer: {
    id: "explorer",
    name: "Codebase Explorer",
    description: "Fast codebase navigation and search",
    systemPrompt: `You are a codebase explorer.
Find files, search for patterns, and analyze project structure.`,
    tools: ["glob", "grep", "read"],
    permissions: {
      read: "allow",
      glob: "allow",
      grep: "allow",
      "*": "deny",
    },
    maxSteps: 3,
  },
};

export function getAgent(id: string): Agent {
  const agent = agents[id];
  if (!agent) throw new Error(`Agent ${id} not found`);
  return agent;
}
```

### 3.2 修改 Session 支持多 Agent

```typescript
// src/session/index.ts (修改)

export namespace Session {
  interface SessionInfo {
    id: string;
    agentID: string;
    messages: Message[];
  }

  export function create(id: string, agentID: string = "developer") {
    const agent = getAgent(agentID);
    const session: SessionInfo = {
      id,
      agentID,
      messages: [
        {
          role: "system",
          content: agent.systemPrompt,
        },
      ],
    };
    sessions.set(id, session);
    return session;
  }

  export async function run(sessionID: string, userMessage: string) {
    const session = sessions.get(sessionID);
    if (!session) throw new Error("Session not found");

    const agent = getAgent(session.agentID);

    // 只加载 agent 允许的工具
    const tools = Object.fromEntries(
      Tool.all()
        .filter((tool) => agent.tools.includes(tool.id))
        .map((tool) => [tool.id, /* ... */])
    );

    // 使用 agent 的权限
    const permission = new PermissionChecker(agent.permissions);

    // ... 其余逻辑
  }
}
```

### 3.3 使用示例

```typescript
// 使用不同的 agent

// 1. 开发 agent
const devSession = Session.create("dev_1", "developer");
await Session.run(devSession.id, "重构这个函数");

// 2. 审查 agent
const reviewSession = Session.create("review_1", "reviewer");
await Session.run(reviewSession.id, "审查 src/index.ts 的代码质量");

// 3. 探索 agent
const exploreSession = Session.create("explore_1", "explorer");
await Session.run(exploreSession.id, "找出所有使用了 Express 的文件");
```

---

## 四、实用功能：子任务委托

### 4.1 实现 Task Tool

```typescript
// src/tool/task.ts

export const Task = Tool.define("task", {
  description: "Delegate task to a sub-agent",
  parameters: z.object({
    agent: z.enum(["developer", "reviewer", "explorer"]),
    description: z.string(),
    prompt: z.string(),
  }),

  async execute(args, ctx) {
    // 创建子会话
    const childSessionID = `${ctx.sessionID}_child_${Date.now()}`;
    const childSession = Session.create(childSessionID, args.agent);

    // 执行子任务
    const result = await Session.run(childSession.id, args.prompt);

    return {
      output: `Sub-task completed by ${args.agent}:\n\n${result}`,
      metadata: {
        childSessionID,
        agent: args.agent,
      },
    };
  },
});
```

### 4.2 使用场景

```typescript
// 主 agent 可以委托子任务

// 场景1：委托代码审查
await Task.execute(
  {
    agent: "reviewer",
    description: "Review authentication code",
    prompt: "Review the authentication logic in src/auth.ts for security issues",
  },
  ctx
);

// 场景2：委托代码探索
await Task.execute(
  {
    agent: "explorer",
    description: "Find all API endpoints",
    prompt: "List all REST API endpoints defined in this project",
  },
  ctx
);
```

---

## 五、性能优化：消息压缩

### 5.1 简单的压缩策略

```typescript
// src/session/compaction.ts

const RECENT_COUNT = 5; // 保留最近 5 条消息
const MAX_LENGTH = 50000; // 最大上下文长度

export async function compactMessages(
  messages: Message[]
): Promise<Message[]> {
  const totalLength = messages.reduce(
    (sum, msg) => sum + msg.content.length,
    0
  );

  if (totalLength < MAX_LENGTH) {
    return messages; // 不需要压缩
  }

  // 保留系统消息和最近的消息
  const systemMessages = messages.filter((m) => m.role === "system");
  const recent = messages.slice(-RECENT_COUNT);
  const old = messages.slice(0, -RECENT_COUNT).filter((m) => m.role !== "system");

  // 生成摘要
  const summary = await summarize(old);

  return [
    ...systemMessages,
    {
      role: "system" as const,
      content: `Previous conversation summary:\n${summary}`,
    },
    ...recent,
  ];
}

async function summarize(messages: Message[]): Promise<string> {
  const response = await generateText({
    model: anthropic("claude-3-haiku-20240307"),
    prompt: `Summarize this conversation, keeping key information:\n\n${messages
      .map((m) => `${m.role}: ${m.content}`)
      .join("\n\n")}`,
  });

  return response.text;
}
```

---

## 六、安全性增强

### 6.1 命令过滤

```typescript
// src/security/command-filter.ts

const DANGEROUS_PATTERNS = [
  /rm\s+-rf\s+\//,
  /:\(\)\{\s*:\|:\&\s*\};:/,  // Fork bomb
  /dd\s+if=/,
  /mkfs/,
  /> \/dev\/sd/,
];

export function isDangerousCommand(command: string): boolean {
  return DANGEROUS_PATTERNS.some((pattern) => pattern.test(command));
}

export function sanitizeCommand(command: string): string {
  // 移除多行命令
  if (command.includes("\n") || command.includes(";")) {
    throw new Error("Multi-line commands are not allowed");
  }

  // 检查危险命令
  if (isDangerousCommand(command)) {
    throw new Error("Dangerous command detected");
  }

  return command;
}
```

### 6.2 在 Bash Tool 中使用

```typescript
// src/tool/bash.ts (修改)

export const Bash = Tool.define("bash", {
  description: "Execute bash command",
  parameters: z.object({
    command: z.string(),
  }),
  requiresPermission: true,

  async execute(args, ctx) {
    // 安全检查
    const safeCommand = sanitizeCommand(args.command);

    // 设置超时和资源限制
    const { stdout, stderr } = await execAsync(safeCommand, {
      timeout: 30000, // 30 秒超时
      maxBuffer: 1024 * 1024, // 1MB 输出限制
    });

    return {
      output: stdout || stderr,
      metadata: { command: safeCommand },
    };
  },
});
```

---

## 七、用户界面选择

### 7.1 选项 A：简单的 CLI

```typescript
// cli.ts
import * as readline from "readline";

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
});

async function main() {
  const session = Session.create("cli_session");

  console.log("🤖 AI Agent Ready");
  console.log("Type 'exit' to quit\n");

  rl.on("line", async (input) => {
    if (input === "exit") {
      rl.close();
      process.exit(0);
    }

    try {
      await Session.run(session.id, input);
      console.log("\n---\n");
    } catch (error) {
      console.error("Error:", error.message);
    }
  });
}

main();
```

### 7.2 选项 B：使用 Ink（React for CLI）

```tsx
// ui.tsx
import React, { useState } from "react";
import { render, Box, Text, TextInput } from "ink";

function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");

  const handleSubmit = async () => {
    const userMessage = input;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);

    const response = await Session.run("session_1", userMessage);
    setMessages((prev) => [...prev, { role: "assistant", content: response }]);
  };

  return (
    <Box flexDirection="column">
      <Box flexDirection="column" marginBottom={1}>
        {messages.map((msg, i) => (
          <Box key={i}>
            <Text color={msg.role === "user" ? "green" : "blue"}>
              {msg.role === "user" ? "You" : "AI"}:
            </Text>
            <Text> {msg.content}</Text>
          </Box>
        ))}
      </Box>

      <Box>
        <Text color="gray">› </Text>
        <TextInput value={input} onChange={setInput} onSubmit={handleSubmit} />
      </Box>
    </Box>
  );
}

render(<App />);
```

### 7.3 选项 C：Web 界面（Next.js）

```typescript
// pages/api/chat.ts (Next.js API Route)
import { NextApiRequest, NextApiResponse } from "next";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  const { message, sessionID } = req.body;

  // 流式响应
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");

  const session = Session.get(sessionID) || Session.create(sessionID);

  // 使用 streamText 并流式发送
  const stream = await streamText({
    model: anthropic("claude-3-5-sonnet-20241022"),
    messages: [...session.messages, { role: "user", content: message }],
    tools: /* ... */,
  });

  for await (const chunk of stream.textStream) {
    res.write(`data: ${JSON.stringify({ content: chunk })}\n\n`);
  }

  res.end();
}
```

---

## 八、部署建议

### 8.1 本地开发

```json
// package.json
{
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js"
  }
}
```

### 8.2 打包为可执行文件

使用 **pkg** 或 **Bun** 打包：

```bash
# 使用 Bun
bun build src/index.ts --compile --outfile my-agent

# 使用 pkg
pkg . --targets node18-linux-x64,node18-macos-x64,node18-win-x64
```

### 8.3 发布到 npm

```json
// package.json
{
  "name": "my-ai-agent",
  "version": "1.0.0",
  "bin": {
    "my-agent": "./dist/index.js"
  },
  "files": ["dist"]
}
```

安装使用：
```bash
npm install -g my-ai-agent
my-agent  # 全局命令
```

---

## 九、常见问题和解决方案

### Q1: Token 使用太多，成本高

**解决方案**：
1. 实现消息压缩（compaction）
2. 使用便宜的模型（Haiku）处理简单任务
3. 限制历史消息数量

```typescript
// 自动选择模型
function selectModel(task: string): string {
  const simplePatterns = ["list files", "search for", "find"];
  const isSimple = simplePatterns.some((p) => task.includes(p));

  return isSimple
    ? "claude-3-haiku-20240307" // 便宜
    : "claude-3-5-sonnet-20241022"; // 强大
}
```

### Q2: 工具调用太慢

**解决方案**：
1. 支持并行工具调用
2. 缓存常见查询结果
3. 使用更快的运行时（Bun）

```typescript
// 并行执行多个工具
const results = await Promise.all([
  Tool.execute("glob", { pattern: "**/*.ts" }, ctx),
  Tool.execute("grep", { pattern: "function" }, ctx),
  Tool.execute("read", { file_path: "README.md" }, ctx),
]);
```

### Q3: 权限管理太复杂

**解决方案**：
使用预设的权限模板：

```typescript
// 权限模板
const PERMISSION_PRESETS = {
  readonly: {
    read: "allow",
    grep: "allow",
    glob: "allow",
    "*": "deny",
  },
  safe: {
    read: "allow",
    write: "ask",
    bash: "ask",
    edit: "ask",
  },
  full: {
    "*": "allow",
    bash: {
      "rm -rf /": "deny",
    },
  },
};

// 使用
const agent = {
  permissions: PERMISSION_PRESETS.safe,
};
```

---

## 十、完整示例项目

完整的项目结构：

```
my-agent/
├── src/
│   ├── agent/
│   │   └── index.ts          # Agent 定义
│   ├── tool/
│   │   ├── tool.ts          # Tool 接口
│   │   ├── read.ts          # 读文件
│   │   ├── write.ts         # 写文件
│   │   ├── edit.ts          # 编辑文件
│   │   ├── bash.ts          # 执行命令
│   │   ├── task.ts          # 子任务
│   │   ├── glob.ts          # 文件搜索
│   │   └── grep.ts          # 内容搜索
│   ├── session/
│   │   ├── index.ts         # Session 管理
│   │   └── compaction.ts    # 消息压缩
│   ├── permission/
│   │   └── index.ts         # 权限系统
│   ├── security/
│   │   └── command-filter.ts # 命令过滤
│   └── index.ts             # 入口
├── tests/
│   ├── tool.test.ts
│   └── session.test.ts
├── package.json
├── tsconfig.json
└── README.md
```

启动命令：
```bash
npm install
npm run dev
```

---

## 十一、学习资源

### 推荐阅读
1. **Vercel AI SDK 文档**: https://sdk.vercel.ai
2. **Anthropic Claude 文档**: https://docs.anthropic.com
3. **OpenCode 源码**: https://github.com/anomalyco/opencode
4. **Zod 文档**: https://zod.dev

### 相关项目
- **Cursor**: 闭源 AI IDE
- **Copilot Workspace**: GitHub 的 AI agent
- **Devin**: 完全自主的软件工程师
- **SWE-agent**: 学术研究项目

---

## 十二、总结

构建一个类似 OpenCode 的 agent，关键是：

1. **从小开始**：先实现 MVP（Tool + Session + LLM）
2. **逐步迭代**：添加权限、多 agent、压缩等功能
3. **关注安全**：命令过滤、权限检查、沙箱执行
4. **用户友好**：选择合适的界面（CLI/TUI/Web）
5. **性能优化**：消息压缩、并行执行、模型选择

最重要的是：**动手实践**！从最小实现开始，逐步添加功能，在实践中学习和改进。

祝你构建出色的 AI Agent！🚀
