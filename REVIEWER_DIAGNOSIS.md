# 🔍 Reviewer 返回空响应根本原因诊断

## 现象回顾

```
[Coder] 执行成功（输出 10 只股票数据）
  ↓
[Reviewer] 开始生成报告 (尝试 1/3)...
[Reviewer] 警告: 返回内容为空，准备重试...
[Reviewer] 开始生成报告 (尝试 2/3)...
[Reviewer] 警告: 返回内容为空，准备重试...
[Reviewer] 开始生成报告 (尝试 3/3)...
[Reviewer] 报告撰写失败: 模型返回空响应
```

这说明 **3 次重试都失败**，Reviewer 持续返回空。

---

## 🎯 根本原因诊断

### 可能原因 1️⃣ : **Coder 输出格式不匹配**

**现象**：
- Coder Prompt 要求输出 JSON 格式：
  ```python
  print(f"[DATA]: {json.dumps(stocks_data, ensure_ascii=False)}")
  ```

- 但实际用户日志显示 Coder 输出的是多行文本：
  ```
  [DATA]: 股票代码 000651.SZ, 股息率 3.45%, 3个月涨幅 5.23%, ...
  [DATA]: 股票代码 601398.SH, 股息率 2.89%, 3个月涨幅 -1.50%, ...
  ```

**为什么导致 Reviewer 返回空？**
```
Reviewer Prompt 说：「解析 JSON 格式的 [DATA]」
但实际接收的是：「10 行纯文本 [DATA]」

Reviewer 期望：
  [DATA]: {"stocks": [{...}, {...}]}  ← JSON 一行

实际收到：
  [DATA]: 股票1的描述...
  [DATA]: 股票2的描述...
  [DATA]: ...（共10行）

Reviewer 的解析逻辑：
  1. 寻找 [DATA]: { 或 [DATA]: [
  2. 但看到的是 [DATA]: 股票代码...
  3. 无法识别为 JSON
  4. 陷入困境：「是什么格式？我该怎么处理？」
  5. 返回空（模型放弃了）
```

---

### 可能原因 2️⃣ : **消息上下文混乱**

**问题场景**：

Coder 执行后的消息链如下：
```python
messages = [
    SystemMessage(CODER_SYSTEM_PROMPT),  # ← Coder 的 Prompt
    HumanMessage("用户查询"),
    AIMessage(tool_calls=[...]),        # ← Coder 的工具调用
    ToolMessage("[DATE]: ...\n[SOURCE]: ...\n[DATA]: ..."),  # ← Coder 的输出
]
```

然后 Reviewer 接收到：
```python
messages = [
    SystemMessage(REVIEWER_SYSTEM_PROMPT),  # ← Reviewer 自己的 Prompt
    HumanMessage("用户查询"),
    AIMessage(tool_calls=[...]),            # ← 这是 Coder 的工具调用！
    ToolMessage("[DATE]: ...\n..."),        # ← 这是 Coder 的输出结果
]
```

**问题**：
- ToolMessage 中既有 Coder 的执行结果，也可能混入了其他信息
- Reviewer Prompt 说「从 ToolMessage 中提取 [DATA]」，但 ToolMessage 可能包含多行混合内容
- 模型不确定应该如何解析

---

### 可能原因 3️⃣ : **Reviewer Prompt 的语义模糊**

**当前 Reviewer Prompt 的问题**：

```python
【当[DATA]是JSON格式时的解析方法】
1. 找到 `[DATA]: {` 或 `[DATA]: [` 开头的行
2. 提取整个JSON字符串
3. 使用Python或会话鼠标解析JSON：`data = json.loads(json_str)`
4. 基于类表字典或列表的数据进行分析
```

**模糊之处**：
1. 「提取整个JSON字符串」- 但没有明确说多行 JSON 如何处理
2. 「使用 Python 解析」- LLM 不是 Python 执行器，它不能真的调用 json.loads()
3. 「会话鼠标」- 这是什么？（应该是笔误）

**模型的真实理解**：
> "我需要识别 JSON，但你没有告诉我具体怎么做。我猜不出你想要什么，所以返回空。"

---

### 可能原因 4️⃣ : **Prompt 长度和复杂度**

**Reviewer Prompt 的现状**：
- 开头部分（核心职责）：~100 Token
- 数据提取指南：~400 Token
- JSON 解析说明：~300 Token
- 数据质量处理：~300 Token
- 报告撰写规范：~500 Token
- **总计**：~1600 Token

**加上消息历史**：
- User 消息：~200 Token
- Coder 工具调用：~300 Token
- ToolMessage 数据输出：~1500 Token (10 只股票的数据)
- **小计**：~2000 Token

**总输入**：~3600 Token（在模型能力范围内 ✅）

**但问题是**：
- Reviewer Prompt 指令太多、层次太复杂
- 模型容易「迷失」在众多规则中
- 真正的关键指导信息被埋没了

---

## ✅ 根本原因总结

| 原因 | 严重程度 | 表现 | 根源 |
|-----|---------|------|------|
| **格式不匹配** | 🔴 高 | Prompt 要求 JSON，但 Coder 输出文本 | Coder Prompt 和实际执行不一致 |
| **消息混乱** | 🟠 中 | ToolMessage 内容复杂，无法清晰解析 | 对话历史结构不优化 |
| **Prompt 模糊** | 🟠 中 | 「怎么解析 JSON」的指导不够具体 | Reviewer Prompt 过度复杂化 |
| **指令冲突** | 🟡 低 | 多个 JSON 相关指令相互干扰 | Prompt 工程问题 |

---

## 🔧 修改思路

### 修改方向 A: **强制 Coder 输出 JSON** (根本解决)

改动 Coder 的代码生成逻辑，确保多条股票数据以 JSON 格式输出：

```python
# ❌ 当前（多行文本）
for _, row in df_results.iterrows():
    print(f"[DATA]: 股票代码 {row['ts_code']}, 股息率 {row['dividend_yield']:.2f}%, ...")

# ✅ 修改后（JSON 一行）
import json
stocks_list = [
    {"code": row['ts_code'], "dividend_yield": row['dividend_yield'], ...}
    for _, row in df_results.iterrows()
]
print(f"[DATA]: {json.dumps(stocks_list, ensure_ascii=False)}")
```

**优点**：
- ✅ 格式统一
- ✅ 易于解析
- ✅ 减少 Reviewer 的处理复杂度

**缺点**：
- ❌ 需要修改 Coder 生成的代码结构

---

### 修改方向 B: **简化 Reviewer Prompt** (改进指导)

将冗长的 Reviewer Prompt 简化为核心指导：

```python
REVIEWER_SYSTEM_PROMPT = """你是一名资深的金融分析师。

【任务】
基于 Coder 执行的数据，撰写专业的投资分析报告。

【数据来源】
消息历史中的 ToolMessage 包含：
- [DATE]: 分析日期
- [SOURCE]: 数据来源
- [TIME_RANGE]: 时间范围
- [DATA]: 核心指标（可能是 JSON 格式）
- [WARNING]: 数据质量警告
- [IMAGE]: 图表路径

【报告结构】
1. 开头：分析日期、数据来源、数据范围
2. 核心结论：基于 [DATA] 的主要发现
3. 详细分析：逐项分析关键指标
4. 风险提示：基于 [WARNING] 的提醒
5. 投资建议：综合评估
6. 免责声明：AI 自动生成

【注意】
- 严格基于 [DATA]，不编造数据
- [WARNING] 不是错误，是数据质量说明
- 如果遇到 JSON 数据，按字段逐一分析描述
- 输出 800-1200 字的专业报告
"""
```

**优点**：
- ✅ 指导清晰简洁
- ✅ 减少模型的"困惑"
- ✅ 易于理解和执行

**缺点**：
- ❌ 丢失了一些细节说明
- ❌ 模型自由度更大，可能出现不规范的内容

---

### 修改方向 C: **添加中间处理节点** (增强鲁棒性)

在 Coder 和 Reviewer 之间添加一个数据规范化节点：

```python
def data_formatter_node(state: MultiAgentState):
    """
    数据规范化节点：
    - 提取 ToolMessage 中的 [DATA] 标记
    - 检查格式（JSON or 文本）
    - 如果是文本格式，转换为标准 JSON
    - 传递给 Reviewer
    """
    # ... 实现代码 ...
    
    return {
        "messages": [...],
        "last_sender": "DataFormatter",
        "formatted_data": standardized_json  # 标准化的 JSON
    }
```

**优点**：
- ✅ 数据格式保证
- ✅ Reviewer 总是接收一致的格式
- ✅ 高度可控

**缺点**：
- ❌ 增加了一个节点，复杂度上升
- ❌ 额外的 API 调用成本

---

## 🎯 推荐方案

**优先度从高到低**：

### 🥇 **方案 1: 修改方向 B（简化 Prompt）** - 立即改

**理由**：
- 改动最小（只改 Prompt 文本）
- 成本最低（无额外调用）
- 效果可见（模型更容易理解）

**实施**：改 REVIEWER_SYSTEM_PROMPT，删除冗余说明，只保留核心指导。

---

### 🥈 **方案 2: 修改方向 A（强制 JSON）** - 长期改

**理由**：
- 根本解决格式问题
- 为未来的其他功能做准备

**实施**：在用户提供的 Coder 代码示例中，自动将多行输出转换为 JSON。

---

### 🥉 **方案 3: 修改方向 C（中间节点）** - 可选

**理由**：
- 最鲁棒的方案
- 但成本和复杂度最高

**实施**：如果 A 和 B 都无法解决，再考虑。

---

## 📊 对比表

| 方案 | 改动量 | 成本 | 效果 | 难度 |
|-----|-------|------|------|------|
| B（简化 Prompt） | 最小 | 0 | 立竿见影 | 简单 |
| A（强制 JSON） | 中 | 0 | 根本解决 | 中等 |
| C（中间节点） | 最大 | 高 | 最鲁棒 | 复杂 |

**建议**：**先改 B，再改 A，保留 C 作为备选。**
