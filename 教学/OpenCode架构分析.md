# OpenCode 架构深度解析

## 一、项目概述

**OpenCode** 是一个开源的 AI 编码 agent，与 Claude Code 类似但有关键差异：

### 核心特点
- **100% 开源**：完全透明的架构和实现
- **多模型支持**：不绑定特定 AI 提供商（Claude、OpenAI、Google、本地模型等）
- **LSP 集成**：内置语言服务器协议支持
- **TUI 优先**：专注于终端界面，由 neovim 用户打造
- **客户端/服务器架构**：支持远程操作，TUI 只是众多客户端之一
- **多平台部署**：支持桌面应用（Tauri）、VS Code 插件、Web 等

---

## 二、项目架构

### 2.1 Monorepo 结构

OpenCode 使用 **Turbo** 作为 monorepo 工具，项目结构如下：

```
opencode/
├── packages/
│   ├── opencode/          # 核心包 (244个TS文件)
│   ├── desktop/           # 桌面应用 (Tauri)
│   ├── desktop-electron/  # Electron 版本
│   ├── console/          # Web 控制台
│   │   ├── app/          # 前端应用
│   │   ├── core/         # 核心逻辑
│   │   ├── function/     # 云函数
│   │   └── mail/         # 邮件服务
│   ├── ui/               # UI 组件库
│   ├── sdk/              # JavaScript SDK
│   ├── util/             # 工具库
│   ├── plugin/           # 插件系统
│   └── ...
├── sdks/
│   └── vscode/           # VS Code 扩展
├── infra/                # 基础设施配置 (SST)
└── turbo.json           # Turbo 配置
```

**技术栈**：
- 运行时：**Bun** (高性能 JavaScript 运行时)
- 语言：**TypeScript** (53.6%)
- 数据库：**Drizzle ORM** (SQLite)
- UI：**SolidJS** + **OpenTUI** (终端界面)
- 构建：**Turbo** (monorepo 工具)
- 部署：**SST** (Serverless Stack)

---

## 三、核心设计理念

### 3.1 Agent 系统设计

OpenCode 实现了一个灵活的 **多 Agent 系统**，每个 agent 有不同的职责和权限：

#### Agent 类型定义

```typescript
// packages/opencode/src/agent/agent.ts
export const Info = z.object({
  name: z.string(),                    // agent 名称
  description: z.string().optional(),  // 描述
  mode: z.enum(["subagent", "primary", "all"]), // 运行模式
  native: z.boolean().optional(),      // 是否为内置 agent
  hidden: z.boolean().optional(),      // 是否隐藏
  permission: PermissionNext.Ruleset,  // 权限规则集
  model: z.object({                    // 模型配置
    modelID: z.string(),
    providerID: z.string(),
  }).optional(),
  prompt: z.string().optional(),       // 自定义提示词
  options: z.record(z.string(), z.any()),
  steps: z.number().int().positive().optional(),
})
```

#### 内置 Agent

**1. Build Agent（默认）**
```typescript
{
  name: "build",
  description: "默认的全权限开发 agent",
  mode: "primary",
  permission: {
    question: "allow",      // 允许提问
    plan_enter: "allow",    // 允许进入规划模式
    // 其他工具默认 allow
  }
}
```

**2. Plan Agent（只读）**
```typescript
{
  name: "plan",
  description: "只读分析和代码探索",
  mode: "primary",
  permission: {
    question: "allow",
    plan_exit: "allow",
    edit: {
      "*": "deny",  // 拒绝所有编辑
      // 只允许编辑计划文件
      [".opencode/plans/*.md"]: "allow"
    }
  }
}
```

**3. General Subagent**
```typescript
{
  name: "general",
  description: "处理复杂搜索和多步骤任务",
  mode: "subagent",  // 子 agent，可被其他 agent 调用
  permission: {
    todoread: "deny",
    todowrite: "deny",
    // 其他默认 allow
  }
}
```

**4. Explore Agent（专注搜索）**
```typescript
{
  name: "explore",
  description: "快速探索代码库",
  mode: "subagent",
  permission: {
    "*": "deny",  // 默认拒绝所有
    // 只允许只读操作
    grep: "allow",
    glob: "allow",
    read: "allow",
    bash: "allow",
    webfetch: "allow",
  },
  prompt: PROMPT_EXPLORE  // 自定义探索提示词
}
```

探索 agent 的提示词设计：
```text
You are a file search specialist. You excel at thoroughly navigating and exploring codebases.

Your strengths:
- Rapidly finding files using glob patterns
- Searching code and text with powerful regex patterns
- Reading and analyzing file contents

Guidelines:
- Use Glob for broad file pattern matching
- Use Grep for searching file contents with regex
- Use Read when you know the specific file path
- Adapt your search approach based on thoroughness level
- Return file paths as absolute paths
- Do not create any files or modify system state
```

**设计亮点**：
- **职责分离**：每个 agent 有明确的职责边界
- **权限隔离**：通过 permission ruleset 精确控制工具访问
- **可扩展性**：用户可以自定义 agent

---

### 3.2 权限系统（Permission System）

OpenCode 实现了一个细粒度的权限控制系统：

```typescript
// 权限规则类型
type Permission = "allow" | "ask" | "deny"

// 权限规则集支持 glob 模式
const defaults = {
  "*": "allow",  // 默认允许
  doom_loop: "ask",  // 防止死循环，需要询问
  external_directory: {
    "*": "ask",  // 外部目录默认询问
    [Truncate.GLOB]: "allow",  // 白名单目录允许
  },
  read: {
    "*": "allow",
    "*.env": "ask",  // 敏感文件询问
    "*.env.*": "ask",
    "*.env.example": "allow",
  }
}
```

**权限合并策略**：
```typescript
// 权限优先级：用户配置 > agent 配置 > 默认配置
const permission = PermissionNext.merge(
  defaults,
  agentPermission,
  userPermission
)
```

**实际应用**：
```typescript
// Plan agent 禁止编辑，但允许编辑计划文件
permission: {
  edit: {
    "*": "deny",
    [path.join(".opencode", "plans", "*.md")]: "allow",
  }
}
```

---

### 3.3 Tool 系统设计

OpenCode 的 tool 系统是核心架构之一，所有与外部交互都通过 tool 实现。

#### Tool 接口定义

```typescript
// packages/opencode/src/tool/tool.ts
export namespace Tool {
  export interface Info<Parameters extends z.ZodType, Metadata> {
    id: string;
    init: (ctx?: InitContext) => Promise<{
      description: string;
      parameters: Parameters;  // Zod schema 定义参数
      execute(
        args: z.infer<Parameters>,
        ctx: Context,
      ): Promise<{
        title: string;
        metadata: Metadata;
        output: string;
        attachments?: FilePart[];
      }>;
      formatValidationError?(error: z.ZodError): string;
    }>;
  }

  export type Context = {
    sessionID: string;
    messageID: string;
    agent: string;
    abort: AbortSignal;
    messages: MessageV2.WithParts[];
    // 请求权限
    ask(input: PermissionRequest): Promise<void>;
    // 更新元数据
    metadata(input: { title?: string; metadata?: M }): void;
  }
}
```

#### Tool 定义示例

**Read Tool**：
```typescript
// packages/opencode/src/tool/read.ts
export const Read = Tool.define("read", {
  description: "读取文件内容",
  parameters: z.object({
    file_path: z.string(),
    offset: z.number().optional(),
    limit: z.number().optional(),
  }),

  async execute(args, ctx) {
    // 1. 参数验证
    const filePath = path.resolve(args.file_path);

    // 2. 权限检查
    await ctx.ask({
      action: "read",
      path: filePath,
    });

    // 3. 执行操作
    const content = await Bun.file(filePath).text();
    const lines = content.split('\n');
    const slice = lines.slice(args.offset ?? 0, args.limit);

    // 4. 返回结果
    return {
      title: `Read ${path.basename(filePath)}`,
      metadata: { path: filePath },
      output: slice.map((line, i) =>
        `${i + 1}→${line}`
      ).join('\n'),
    };
  }
});
```

**Bash Tool**（执行命令）：
```typescript
// packages/opencode/src/tool/bash.ts
export const Bash = Tool.define("bash", {
  description: "执行 bash 命令",
  parameters: z.object({
    command: z.string(),
    timeout: z.number().optional(),
    run_in_background: z.boolean().optional(),
  }),

  async execute(args, ctx) {
    // 权限检查
    await ctx.ask({
      action: "bash",
      command: args.command,
    });

    // 执行命令
    const proc = Bun.spawn(["bash", "-c", args.command], {
      cwd: Instance.worktree,
      timeout: args.timeout ?? 120000,
    });

    const output = await proc.text();

    return {
      title: `$ ${args.command}`,
      metadata: { exitCode: proc.exitCode },
      output,
    };
  }
});
```

**Task Tool**（启动子 agent）：
```typescript
// packages/opencode/src/tool/task.ts
export const Task = Tool.define("task", {
  description: "启动子 agent 处理复杂任务",
  parameters: z.object({
    description: z.string(),
    prompt: z.string(),
    subagent_type: z.string(),  // 'general', 'explore' 等
    run_in_background: z.boolean().optional(),
  }),

  async execute(args, ctx) {
    // 创建子会话
    const childSession = await Session.create({
      parentID: ctx.sessionID,
      agent: args.subagent_type,
    });

    // 执行子任务
    const result = await Session.run(childSession.id, args.prompt);

    return {
      title: args.description,
      metadata: { childSessionID: childSession.id },
      output: result.output,
    };
  }
});
```

#### 内置 Tools 列表

```
├── bash.ts          # 执行 shell 命令
├── read.ts          # 读取文件
├── edit.ts          # 编辑文件（精确字符串替换）
├── write.ts         # 写入新文件
├── glob.ts          # 文件模式匹配
├── grep.ts          # 内容搜索
├── ls.ts            # 列出目录
├── task.ts          # 启动子 agent
├── question.ts      # 询问用户
├── plan.ts          # 进入/退出计划模式
├── lsp.ts           # LSP 集成（代码补全、跳转等）
├── webfetch.ts      # 获取网页内容
├── websearch.ts     # 网络搜索
├── codesearch.ts    # 代码搜索
├── skill.ts         # 执行用户技能
└── todo.ts          # 任务管理
```

**设计亮点**：
- **统一接口**：所有 tool 都实现相同接口
- **参数验证**：使用 Zod schema 自动验证
- **权限集成**：每个 tool 调用都经过权限检查
- **输出截断**：自动处理超长输出（Truncate.output）
- **可扩展**：用户可以通过插件添加自定义 tool

---

### 3.4 Session 管理

Session 是 OpenCode 的核心概念，代表一次对话会话。

#### Session 数据结构

```typescript
// packages/opencode/src/session/index.ts
export const Info = z.object({
  id: Identifier.schema("session"),
  slug: z.string(),                  // URL 友好的标识符
  projectID: z.string(),             // 所属项目
  workspaceID: z.string().optional(),
  directory: z.string(),             // 工作目录
  parentID: z.string().optional(),   // 父会话（用于子任务）
  title: z.string(),
  version: z.string(),

  summary: z.object({
    additions: z.number(),           // 代码统计
    deletions: z.number(),
    files: z.number(),
    diffs: Snapshot.FileDiff.array().optional(),
  }).optional(),

  share: z.object({
    url: z.string(),                 // 分享链接
  }).optional(),

  permission: PermissionNext.Ruleset.optional(),

  time: z.object({
    created: z.number(),
    updated: z.number(),
    compacting: z.number().optional(), // 压缩时间戳
    archived: z.number().optional(),
  }),

  revert: z.object({
    messageID: z.string(),
    snapshot: z.string().optional(),
  }).optional(),
});
```

#### Session 生命周期

```typescript
// 1. 创建会话
const session = await Session.create({
  projectID,
  directory: process.cwd(),
  agent: "build",
});

// 2. 运行会话
await Session.run(session.id, userMessage);

// 3. 压缩历史（节省 token）
await Session.compact(session.id);

// 4. 归档会话
await Session.archive(session.id);
```

#### Message 结构（V2）

```typescript
// packages/opencode/src/session/message-v2.ts
export namespace MessageV2 {
  export type Role = "system" | "user" | "assistant" | "tool";

  export interface Message {
    id: string;
    sessionID: string;
    role: Role;
    time: number;
    parts: Part[];  // 消息可以包含多个部分
  }

  export type Part =
    | TextPart
    | ToolCallPart
    | ToolResultPart
    | FilePart;

  export interface TextPart {
    type: "text";
    content: string;
  }

  export interface ToolCallPart {
    type: "tool_call";
    toolID: string;
    args: Record<string, any>;
  }

  export interface ToolResultPart {
    type: "tool_result";
    toolCallID: string;
    output: string;
    metadata: Record<string, any>;
  }
}
```

---

### 3.5 Provider 抽象层

OpenCode 不绑定特定 AI 提供商，通过 provider 抽象层支持多种模型：

```typescript
// packages/opencode/src/provider/provider.ts
export namespace Provider {
  export interface Info {
    id: string;
    name: string;
    models: Model[];
  }

  export interface Model {
    id: string;
    name: string;
    maxTokens: number;
    supportsImages: boolean;
    supportsTools: boolean;
    pricing?: {
      input: number;   // 每百万 token 价格
      output: number;
    };
  }
}

// 支持的提供商
const providers = [
  anthropicProvider,    // Claude
  openaiProvider,       // GPT-4
  googleProvider,       // Gemini
  cohereProvider,
  groqProvider,
  ollamaProvider,       // 本地模型
  // ... 更多
];
```

**统一接口**（基于 Vercel AI SDK）：
```typescript
import { generateText, streamText } from 'ai';

// 所有提供商都通过相同接口调用
const response = await streamText({
  model: provider.model(modelId),
  messages: sessionMessages,
  tools: availableTools,
});
```

---

## 四、关键设计模式

### 4.1 代码风格哲学

OpenCode 有非常独特的代码风格指南（AGENTS.md）：

**核心原则**：
```typescript
// ✅ 好：单词变量名
const foo = 1;
function journal(dir: string) {}

// ❌ 坏：驼峰复合词
const fooBar = 1;
function prepareJournal(dir: string) {}

// ✅ 好：内联使用一次的值
const journal = await Bun.file(path.join(dir, "journal.json")).json();

// ❌ 坏：不必要的中间变量
const journalPath = path.join(dir, "journal.json");
const journal = await Bun.file(journalPath).json();

// ✅ 好：早返回
function foo() {
  if (condition) return 1;
  return 2;
}

// ❌ 坏：else 语句
function foo() {
  if (condition) return 1;
  else return 2;
}
```

**原因**：
- **可读性**：简短的名称在上下文中更清晰
- **减少认知负担**：少的变量 = 少的心智负担
- **函数式风格**：偏好 map/filter/flatMap 而非 for 循环

---

### 4.2 错误处理

```typescript
// 避免 try/catch，优先使用 Result 类型
type Result<T, E = Error> =
  | { ok: true; value: T }
  | { ok: false; error: E };

// 使用类型守卫
const files = await glob("**/*.ts");
const tsFiles = files.filter((f): f is string => f.endsWith('.ts'));
```

---

### 4.3 Bun API 优先

```typescript
// ✅ 使用 Bun API
const content = await Bun.file(path).text();
const json = await Bun.file(path).json();

// ❌ 避免 Node API
import fs from 'fs/promises';
const content = await fs.readFile(path, 'utf-8');
```

---

## 五、架构亮点

### 5.1 客户端/服务器分离

```
┌─────────────┐     WebSocket/HTTP     ┌──────────────┐
│   TUI 客户端  │ ◄──────────────────► │  OpenCode    │
│   (OpenTUI)  │                       │   Server     │
└─────────────┘                       └──────────────┘
                                             ▲
┌─────────────┐                             │
│ Desktop App  │ ─────────────────────────────┤
│   (Tauri)    │                             │
└─────────────┘                             │
                                             │
┌─────────────┐                             │
│  VS Code    │ ─────────────────────────────┤
│  Extension  │                             │
└─────────────┘                             ▼
                                      ┌────────────┐
┌─────────────┐                      │  Storage   │
│   Mobile    │ ─────────────────────│  (SQLite)  │
│   (未来)     │                      └────────────┘
└─────────────┘
```

**优势**：
- **多客户端**：一套后端，多种前端
- **远程协作**：服务器可以运行在开发机，客户端在本地
- **状态持久化**：所有状态存储在服务器端

---

### 5.2 LSP 集成

OpenCode 内置 Language Server Protocol 支持：

```typescript
// packages/opencode/src/lsp/index.ts
export namespace LSP {
  // 启动 LSP 服务器
  export async function start(language: string) {
    const server = await startLanguageServer(language);
    return {
      // 代码补全
      completion: (file, position) =>
        server.sendRequest('textDocument/completion', { file, position }),

      // 跳转到定义
      definition: (file, position) =>
        server.sendRequest('textDocument/definition', { file, position }),

      // 查找引用
      references: (file, position) =>
        server.sendRequest('textDocument/references', { file, position }),

      // 重命名
      rename: (file, position, newName) =>
        server.sendRequest('textDocument/rename', { file, position, newName }),
    };
  }
}
```

**Tool 集成**：
```typescript
// LSP Tool
export const LSP = Tool.define("lsp", {
  parameters: z.object({
    action: z.enum(["completion", "definition", "references", "rename"]),
    file: z.string(),
    line: z.number(),
    column: z.number(),
    newName: z.string().optional(),
  }),

  async execute(args, ctx) {
    const lsp = await LSP.start(detectLanguage(args.file));
    const result = await lsp[args.action](args.file, {
      line: args.line,
      column: args.column,
    });
    return { title: `LSP ${args.action}`, metadata: {}, output: JSON.stringify(result, null, 2) };
  }
});
```

---

### 5.3 Snapshot 系统（代码快照）

```typescript
// packages/opencode/src/snapshot/index.ts
export namespace Snapshot {
  // 创建快照
  export async function create(sessionID: string) {
    const files = await glob("**/*", { ignore: [".git", "node_modules"] });
    const snapshot: Snapshot = {
      id: ulid(),
      sessionID,
      timestamp: Date.now(),
      files: await Promise.all(
        files.map(async (file) => ({
          path: file,
          content: await Bun.file(file).text(),
          hash: await hashFile(file),
        }))
      ),
    };
    await Storage.snapshot.insert(snapshot);
    return snapshot;
  }

  // 恢复快照
  export async function restore(snapshotID: string) {
    const snapshot = await Storage.snapshot.get(snapshotID);
    for (const file of snapshot.files) {
      await Bun.write(file.path, file.content);
    }
  }

  // 计算 diff
  export async function diff(fromID: string, toID: string) {
    const from = await Storage.snapshot.get(fromID);
    const to = await Storage.snapshot.get(toID);
    return computeDiff(from.files, to.files);
  }
}
```

**用途**：
- **撤销功能**：回滚到任意时间点
- **代码审查**：查看所有改动
- **分享会话**：包含完整的代码上下文

---

### 5.4 Skill 系统（用户自定义能力）

```typescript
// packages/opencode/src/skill/index.ts
export namespace Skill {
  export interface Info {
    name: string;
    description: string;
    prompt: string;      // 注入的系统提示词
    tools?: Tool.Info[]; // 自定义工具
  }

  // 加载用户技能
  export async function load() {
    const skillDirs = [
      path.join(Global.Path.data, "skills"),  // 全局技能
      path.join(Instance.worktree, ".opencode", "skills"), // 项目技能
    ];

    const skills: Info[] = [];
    for (const dir of skillDirs) {
      const files = await glob(`${dir}/**/skill.json`);
      for (const file of files) {
        const skill = await Bun.file(file).json();
        skills.push(skill);
      }
    }
    return skills;
  }
}
```

**Skill 示例**（`~/.opencode/skills/commit/skill.json`）：
```json
{
  "name": "commit",
  "description": "创建 git commit",
  "prompt": "当用户说 /commit 时，按照以下步骤：\n1. 运行 git status\n2. 运行 git diff\n3. 生成 commit message\n4. 运行 git commit"
}
```

---

### 5.5 消息压缩（Compaction）

为了节省 token，OpenCode 会自动压缩历史消息：

```typescript
// packages/opencode/src/session/compaction.ts
export async function compact(sessionID: string) {
  const messages = await Message.list(sessionID);

  // 1. 保留最近 N 条消息
  const recent = messages.slice(-10);

  // 2. 压缩旧消息
  const old = messages.slice(0, -10);
  const summary = await summarize(old);

  // 3. 替换为摘要
  const compacted = [
    {
      role: "system",
      content: `以下是之前的对话摘要：\n${summary}`,
    },
    ...recent,
  ];

  await Message.replace(sessionID, compacted);
}

// 使用 LLM 生成摘要
async function summarize(messages: Message[]) {
  const response = await generateText({
    model: provider.model("claude-3-haiku"),
    prompt: `总结以下对话，保留关键信息：\n${JSON.stringify(messages)}`,
  });
  return response.text;
}
```

---

## 六、实战示例

### 6.1 典型工作流程

```typescript
// 1. 用户发送消息
const userMessage = "帮我重构这个函数";

// 2. 创建/获取会话
const session = await Session.getOrCreate({
  projectID: "project_123",
  agent: "build",
});

// 3. AI 调用工具
const response = await streamText({
  model: provider.model("claude-opus-4"),
  messages: [
    ...session.history,
    { role: "user", content: userMessage },
  ],
  tools: {
    read: Read,
    edit: Edit,
    bash: Bash,
    // ... 更多工具
  },
});

// 4. 处理工具调用
for await (const chunk of response) {
  if (chunk.type === "tool-call") {
    // 权限检查
    const permitted = await Permission.check(
      session,
      chunk.toolName,
      chunk.args
    );

    if (permitted) {
      // 执行工具
      const result = await Tool.execute(
        chunk.toolName,
        chunk.args,
        context
      );

      // 发送结果回 AI
      response.addToolResult(result);
    }
  } else if (chunk.type === "text") {
    // 流式输出给用户
    process.stdout.write(chunk.content);
  }
}

// 5. 保存消息历史
await Message.save(session.id, response.messages);

// 6. 创建快照（如果有文件改动）
if (hasFileChanges) {
  await Snapshot.create(session.id);
}
```

---

### 6.2 子任务委托示例

```typescript
// 用户：分析这个项目的架构

// 主 agent (build) 决定委托给 explore agent
const explorerTask = await Task.execute({
  subagent_type: "explore",
  description: "探索项目架构",
  prompt: `
    请分析这个项目：
    1. 找到所有主要的目录结构
    2. 识别配置文件
    3. 列出核心模块
    4. 总结架构模式
  `,
});

// explore agent 执行（权限受限，只能读取）
// - 使用 glob 找到目录
// - 使用 grep 搜索关键字
// - 使用 read 读取配置文件
// - 返回分析结果

// 主 agent 使用结果继续对话
```

---

## 七、安全性设计

### 7.1 权限隔离

```typescript
// 每个操作都需要权限检查
async function checkPermission(
  session: Session,
  action: string,
  resource: string
): Promise<boolean> {
  const agent = await Agent.get(session.agent);
  const permission = agent.permission[action];

  // 1. 检查全局规则
  if (permission === "deny") return false;
  if (permission === "allow") return true;

  // 2. 检查模式匹配
  for (const [pattern, rule] of Object.entries(permission)) {
    if (minimatch(resource, pattern)) {
      if (rule === "deny") return false;
      if (rule === "allow") return true;
      if (rule === "ask") {
        // 询问用户
        return await askUser(`允许 ${action} ${resource}?`);
      }
    }
  }

  return false;
}
```

### 7.2 沙箱执行

```typescript
// Bash 命令在受限环境中执行
export async function executeBash(command: string) {
  // 1. 检查危险命令
  const dangerous = ["rm -rf /", ":(){ :|:& };:"];
  if (dangerous.some(d => command.includes(d))) {
    throw new Error("危险命令被拒绝");
  }

  // 2. 设置环境限制
  const proc = Bun.spawn(["bash", "-c", command], {
    cwd: Instance.worktree,
    env: {
      ...process.env,
      PATH: filterPath(process.env.PATH),
    },
    timeout: 120000,
    // 限制资源
    ulimit: {
      cpu: 60,      // CPU 秒数
      fsize: 100,   // 文件大小 MB
      nproc: 100,   // 进程数
    },
  });

  return await proc.text();
}
```

---

## 八、性能优化

### 8.1 输出截断

```typescript
// packages/opencode/src/tool/truncation.ts
export namespace Truncate {
  const MAX_OUTPUT_SIZE = 50000; // 字符

  export async function output(
    content: string,
    options: {},
    agent?: Agent.Info
  ) {
    if (content.length <= MAX_OUTPUT_SIZE) {
      return { content, truncated: false };
    }

    // 保存完整输出到文件
    const outputPath = path.join(
      Global.Path.data,
      "truncated",
      `${ulid()}.txt`
    );
    await Bun.write(outputPath, content);

    // 返回截断内容
    const truncated = content.slice(0, MAX_OUTPUT_SIZE);
    return {
      content: truncated + `\n\n[输出被截断，完整内容: ${outputPath}]`,
      truncated: true,
      outputPath,
    };
  }
}
```

### 8.2 并行工具调用

```typescript
// AI 可以并行调用多个工具
const response = await streamText({
  model,
  tools: { read: Read, grep: Grep, glob: Glob },
  experimental_parallelToolCalls: true,  // 启用并行
});

// 实现
export async function executeToolCalls(calls: ToolCall[]) {
  return await Promise.all(
    calls.map(call => Tool.execute(call.name, call.args, context))
  );
}
```

---

## 九、总结与启发

### 9.1 核心设计思想

1. **模块化架构**：清晰的职责分离（agent、tool、session、permission）
2. **可扩展性**：通过 agent、tool、skill 系统支持自定义
3. **安全第一**：细粒度权限控制 + 沙箱执行
4. **提供商中立**：不绑定特定 AI 模型
5. **客户端灵活性**：一套后端，多种前端
6. **代码质量**：严格的风格指南，追求简洁

### 9.2 值得学习的点

**对于 Agent 开发者**：
- ✅ 使用 Zod 进行类型安全的参数验证
- ✅ 实现细粒度的权限系统
- ✅ 设计可组合的 tool 系统
- ✅ 支持子任务委托（agent 嵌套）
- ✅ 实现消息压缩节省 token
- ✅ 使用快照系统支持撤销

**对于架构设计**：
- ✅ 客户端/服务器分离
- ✅ 使用 monorepo 管理复杂项目
- ✅ 抽象层设计（provider、tool）
- ✅ 状态持久化（SQLite）
- ✅ 流式输出提升用户体验

**对于代码风格**：
- ✅ 偏好简洁的变量名
- ✅ 避免不必要的中间变量
- ✅ 使用函数式编程风格
- ✅ 早返回避免嵌套

### 9.3 与其他 Agent 的对比

| 特性 | OpenCode | Claude Code | Cursor | Copilot |
|------|----------|-------------|--------|---------|
| 开源 | ✅ | ❌ | ❌ | ❌ |
| 多模型支持 | ✅ | ❌ (仅Claude) | ✅ | ❌ (仅OpenAI) |
| TUI | ✅ | ✅ | ❌ | ❌ |
| LSP 集成 | ✅ | ✅ | ✅ | ✅ |
| 权限系统 | ✅ 细粒度 | ✅ | ❌ | ❌ |
| 子任务委托 | ✅ | ✅ | ❌ | ❌ |
| 客户端多样性 | ✅ | ❌ | ❌ | ❌ |

---

## 十、延伸阅读

### 推荐深入研究的文件

```
packages/opencode/src/
├── agent/agent.ts          # Agent 系统核心
├── tool/tool.ts            # Tool 抽象层
├── session/index.ts        # 会话管理
├── permission/next.ts      # 权限系统
├── provider/provider.ts    # 模型提供商抽象
└── storage/db.ts           # 数据库层

packages/console/app/        # Web 控制台前端
packages/desktop/            # Tauri 桌面应用
sdks/vscode/                # VS Code 扩展
```

### 相关技术栈

- **Bun**: https://bun.sh
- **Drizzle ORM**: https://orm.drizzle.team
- **Vercel AI SDK**: https://sdk.vercel.ai
- **OpenTUI**: https://github.com/opentui/opentui
- **SST**: https://sst.dev
- **Tauri**: https://tauri.app

---

**最后的建议**：

如果你想借鉴 OpenCode 的设计：
1. **先理解 Tool 系统**：这是整个架构的基础
2. **再看 Agent 系统**：理解如何组织不同职责的 agent
3. **然后研究权限系统**：学习如何安全地执行用户代码
4. **最后看客户端实现**：了解如何构建用户界面

OpenCode 的代码质量很高，非常适合作为学习材料。建议从 `packages/opencode/src/` 开始阅读，按照上述顺序逐步深入。
