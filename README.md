# ASA (AI Stock Analyst) - 多智能体金融数据分析系统

## 项目概述

ASA是一个基于LangGraph的多智能体协作系统，用于解决金融量化分析中的"长链路推理"与"数据真空"问题。系统通过Supervisor模式协调多个Agent节点，实现从任务规划、代码生成、逻辑审计到故障自愈的完整闭环。

**核心代码规模**：7800+行
- `multi_agent.py`: 3268行 - Supervisor模式编排框架
- `lib.py`: 1598行 - 模型工厂、执行内核、工具函数
- `memory_system.py`: 1201行 - 分层记忆系统
- `orchestrator.py`: 1656行 - Agent协调层
- `rca_module.py`: 551行 - 根因分析模块
- `trajectory_collector.py`: 433行 - 轨迹收集器

---

## 系统架构

### 核心Agent节点

```
User Input
    ↓
Supervisor (任务规划与路由)
    ↓
Coder (代码生成与执行) ←→ Tools (工具调用)
    ↓
Reviewer (逻辑审计)
    ↓
ErrorHandler (错误修复) ←→ ProfileUpdater (画像更新)
    ↓
FINISH
```

### 关键设计模式

1. **Supervisor模式**：中央控制器负责任务分解和节点调度
2. **物理任务队列**：通过`remaining_steps.pop(0)`强制任务执行顺序
3. **模型分层**：qwen-plus(强逻辑) vs qwen-turbo(轻量级)
4. **Skill-on-demand**：动态技能注入机制
5. **Thread隔离**：KernelManager实现会话级Namespace隔离

---

## 核心机制详解

### 1. 确定性流程控制

**物理任务队列** (`multi_agent.py` 第728、762、804行)：

```python
# 只有成功执行才物理弹出
finished_step = remaining_steps.pop(0)
```

**解决的问题**：
- LLM在长链路任务中容易产生"虚假完成"幻觉
- 通过`pop(0)`强制物理控制，只要列表不为空就必须继续执行

### 2. 动态技能注入 (Skill-on-demand)

**技能库** (`skills.json`)：

| 技能名 | 触发关键词 | 核心功能 |
|--------|-----------|---------|
| dividend_expert | 分红、股息 | dv_ttm单位转换、状态过滤 |
| charting_expert | 画图、可视化 | 中文字体、路径生成 |
| finance_audit | 财报、收入 | 单位转换、时间滞后检查 |
| market_expert | 港股、ETF | 代码后缀、估值切换 |
| error_handling | 错误、重试 | 重试策略、优雅降级 |

**工作流程**：
1. Supervisor识别意图 → 建议加载技能
2. Coder调用`load_skill()`工具
3. 系统读取skills.json，将规则注入为ToolMessage
4. Coder在接收技能后生成代码

### 3. 模型分层工厂

**实现** (`lib.py` 第67-108行)：

```python
def get_chat_model(model_type):
    config = {
        "smart": {"model": "qwen-plus", "temperature": 0.1},   # Supervisor, Coder, Reviewer
        "fast": {"model": "qwen-turbo", "temperature": 0.1}   # ErrorHandler, ProfileUpdater
    }
```

**效果**：轻量级节点用低成本模型，核心逻辑节点用高性能模型，有效控制推理成本。

### 4. 会话隔离 (KernelManager)

**实现** (`lib.py` 第481-552行)：

```python
class KernelManager:
    def get_kernel(self, thread_id: str):
        if thread_id not in self._kernels:
            self._kernels[thread_id] = StatefulPythonKernel()
        return self._kernels[thread_id]
```

**特性**：
- 每个thread_id拥有独立的Python执行环境
- 多租户间变量物理隔离
- 同一用户多轮对话可接力使用变量

### 5. 4级回溯策略 (BacktrackingRouter)

**实现** (`multi_agent.py` 第105-160行)：

| 级别 | 策略 | 触发条件 |
|-----|------|---------|
| L1 | direct_query | 首次尝试 |
| L2 | step_by_step | 数据为空 |
| L3 | alternative_fields | 主字段失效 |
| L4 | reject_with_reason | 所有策略穷尽 |

### 6. Self-Correction反思机制

**实现** (`multi_agent.py` 第646-681行)：

```python
if execution_status == "error" and retry_count >= 2:
    # 触发反思循环
    reflection_prompt = f"""
    用户意图: {last_msg_content}
    错误类型: {error_type}
    重试次数: {retry_count}
    
    请反思：
    1. 意图理解是否有偏差？
    2. 技能选择是否恰当？
    3. API参数是否正确？
    4. 有无其他备选方案？
    """
```

---

## 扩展模块

### 1. 分层记忆系统 (memory_system.py)

```
┌─────────────────┐  ┌─────────────────┐
│   短期记忆       │  │   长期记忆       │
│ (Working Memory)│  │ (Long-Term)     │
│                 │  │                 │
│ - 最近5轮对话   │  │ - 成功策略       │
│ - TTL: 30min   │  │ - 知识片段       │
└─────────────────┘  └─────────────────┘
         ↓                    ↓
┌─────────────────────────────────────┐
│         记忆衰退机制                 │
│ - 时间: 30天未访问 → 权重-50%       │
│ - 重要性: success_count>3 → 永久保留│
│ - 相关性: embedding<0.5 → 不召回    │
└─────────────────────────────────────┘
```

### 2. Agent协调层 (orchestrator.py)

**功能**：
- Agent间冲突仲裁（投票、优先级、共识）
- 4级Fallback策略（重试→切换→人工→拒答）
- Human-in-the-Loop（低置信度触发人工确认）
- ToolUsageGraph（工具智能路由）

### 3. 根因分析 (rca_module.py)

**功能**：
- Fault Propagation Graph：追踪错误在Agent间的传播路径
- Root Cause Localization：定位真正的错误源头
- Propagation-Aware Retry：基于传播链选择重试策略

### 4. 轨迹收集 (trajectory_collector.py)

**功能**：
- 自动收集Agent运行轨迹
- 生成DPO格式的偏好数据
- Error-Specific分类（12种错误类型）

---

## 测试验证

### 压测结果

| 测试批次 | 样本数 | 成功率 | 关键观察 |
|---------|-------|--------|---------|
| batch_run_20260130_173002 | 45 | **80.0%** | finance_audit技能，28步完成 |
| batch_run_20260130_155446 | 27 | **66.7%** | charting_expert技能，API授权问题 |
| **合计** | **72** | **73%** | 技能加载100%成功 |

### 真实案例演示

**输入**：`"查询科大讯飞的政府补贴占净利润比重，分析其盈利质量。"`

**执行流程**：
1. Supervisor识别意图 → 建议加载finance_audit
2. Coder调用load_skill("finance_audit") → ✅ 技能加载成功
3. Coder生成Tushare查询代码
4. Tools执行代码 → 返回原始数据
5. Coder数据处理 → 单位转换、字段提取
6. ... (共28步)
7. Reviewer逻辑审计 → ⚠️ 检测到数据异常
8. Reviewer生成报告 → 详细风险分析
9. ProfileUpdater更新画像

**输出**：成功完成，Reviewer正确识别"2025年净利润在2025年2月前不可能存在"等数据问题。

---

## 项目状态

**当前阶段**：功能原型已成型，生产级可靠性优化进行中

**已验证**：
- ✅ Supervisor模式编排
- ✅ 物理任务队列控制
- ✅ 动态技能注入
- ✅ 模型分层调度
- ✅ KernelManager会话隔离
- ✅ 72轮压测验证（73%成功率）

**进行中**：
- 🔄 执行序列审计机制（防止递归死循环）
- 🔄 OpenSandbox内核集成
- 🔄 记忆系统深度集成

---

## 技术栈

- **编排框架**：LangGraph
- **LLM**：阿里云通义千问 (qwen-plus / qwen-turbo)
- **数据源**：Tushare Pro API
- **数据处理**：Pandas, NumPy
- **向量存储**：ChromaDB (可选)
- **执行隔离**：StatefulPythonKernel / OpenSandbox (预留)

---

## 文件结构

```
ASA/
├── multi_agent.py          # 核心编排框架 (3268行)
├── lib.py                  # 模型工厂、执行内核 (1598行)
├── memory_system.py        # 分层记忆系统 (1201行)
├── orchestrator.py         # Agent协调层 (1656行)
├── rca_module.py           # 根因分析 (551行)
├── trajectory_collector.py # 轨迹收集 (433行)
├── skills.json             # 5类技能库
├── conf.py                 # 配置管理
├── batch_test_runner.py    # 压测框架
└── evaluation_results/     # 测试结果
    ├── batch_run_20260130_173002.jsonl  # 45轮测试
    └── batch_run_20260130_155446.jsonl  # 27轮测试
```

---

## 核心代码引用

| 机制 | 文件 | 行号 |
|-----|------|-----|
| remaining_steps.pop(0) | multi_agent.py | 728, 762, 804 |
| 模型分层工厂 | lib.py | 67-108 |
| KernelManager | lib.py | 481-552 |
| BacktrackingRouter | multi_agent.py | 105-160 |
| Self-Correction | multi_agent.py | 646-681 |
| MultiAgentState | multi_agent.py | 317-336 |

---

**项目作者**：way  
**创建时间**：2025-11-06  
**最后更新**：2026-01-30
