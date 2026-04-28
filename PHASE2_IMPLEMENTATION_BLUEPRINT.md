# 🚀 Phase 2 实施蓝图：详细改动思路（不含代码）

> **目标**：将单脑系统（仅 Coder 获取数据）升级为双脑系统（Coder 获取财务 + Reporter 搜索新闻）
>
> **工作量评估**：400-600 行代码改动，涉及 3 个文件，风险等级：**中等偏低**

---

## 📊 第一部分：改动规模评估（不会报错的关键原因）

### **为什么不会出现"报错无法输出"？**

你的系统已经有这些"防护机制"：

```
✅ 防护层1：ErrorHandler
   - 当任何 Agent 执行失败时，会捕获异常并归类
   - Reporter 失败 → ErrorHandler 标记为 "reporter_error"
   - 系统不会因为 Reporter 失败就中断流程

✅ 防护层2：Supervisor 的状态机
   - 基于 last_sender 和 execution_status 的路由
   - 即使 Reporter 没数据，Supervisor 也能决定下一步
   - 可以让 Coder 的数据先过 Reviewer，Reporter 的新闻用作补充

✅ 防护层3：Message 的 operator.add 机制
   - messages 是累积式的，不会被覆盖
   - Reporter 的输出会自动 append 到 messages
   - Reviewer 在接收时能同时看到 [DATA] 和 [NEWS]

✅ 防护层4：get_initial_state() 工厂函数
   - 已经为所有 State 字段提供了默认值
   - 新增字段只需在这里添加默认值
   - 不会因为缺少字段而报错
```

**结论**：即使 Reporter 失败，系统会：
1. ErrorHandler 捕获异常
2. Supervisor 识别状态 (status="error")
3. 降级：跳过新闻，继续进行财务分析
4. 前端输出：财务分析报告 + "新闻搜索失败"的警告

---

## 🔧 第二部分：改动清单（按文件分类）

### **改动文件数：3 个**

```
multi_agent.py    ← 改动最大（80% 工作量）
lib.py            ← 改动中等（15% 工作量）  
grtu.py           ← 可选改动（5% 工作量，仅前端展示）
```

---

## 📋 第三部分：详细改动清单

### **【改动 1】multi_agent.py - State 扩展**

**目标**：在 MultiAgentState 中添加新闻相关字段

**改动位置**：L47-66（`class MultiAgentState(TypedDict):`）

**改动类型**：**加字段（非常安全）**

**具体内容**：
```
在现有的 TypedDict 定义中添加：

# 新闻数据相关
news_data: dict  # 存储 Reporter 的输出
news_keywords: str  # 搜索关键词（从任务分解中提取）

# 并行执行标志
parallel_task_flag: bool  # 是否需要同时执行 Coder 和 Reporter
reporter_ready: bool  # Reporter 是否执行完毕
coder_news_combined: bool  # Coder 是否已经调用了新闻工具

# 错误跟踪（参考 ErrorHandler 的设计）
reporter_error_type: str  # 新闻搜索的错误分类
reporter_fail_count: int  # Reporter 失败计数（防止死循环）
```

**为什么安全**：
- ✅ 只是添加新字段，不删除旧字段
- ✅ 已有的 get_initial_state() 会自动提供默认值
- ✅ 所有代码路径都能识别这些字段（或用 .get() 方法）

**改动量**：约 5-8 行

---

### **【改动 2】multi_agent.py - get_initial_state() 更新**

**目标**：为新 State 字段提供初始值

**改动位置**：L2217-2267（`def get_initial_state():`）

**改动类型**：**加初始值（非常安全）**

**具体内容**：
```
在 return 字典中添加新闻相关的初始化：

# 在 "# --- 【工作记忆】中间数据 ---" 注释下方添加

# --- 【工作记忆】新闻和舆情数据 ---
"news_data": {},  # Reporter 搜索结果
"news_keywords": "",  # 搜索关键词
"parallel_task_flag": False,  # 默认不并行
"reporter_ready": False,  # 默认 Reporter 未执行
"coder_news_combined": False,  # 默认 Coder 未调用新闻工具

# --- 【工作记忆】新闻搜索的错误处理 ---
"reporter_error_type": None,
"reporter_fail_count": 0,
```

**为什么安全**：
- ✅ 只是添加默认值，不改现有逻辑
- ✅ 所有节点都会从这个函数创建初始状态
- ✅ 防止了 KeyError（字段不存在）

**改动量**：约 8-10 行

---

### **【改动 3】multi_agent.py - Supervisor System Prompt 更新**

**目标**：让 Supervisor 能识别何时需要新闻搜索

**改动位置**：L217-267（`def supervisor_node():`中的 system_prompt 定义）

**改动类型**：**改 Prompt（完全安全，只是文字修改）**

**具体内容**：

**原有 Prompt**（大约 L220-230）：
```
你是团队主管(Supervisor)。你有两名员工：

1. Coder: 负责编写Python代码，获取数据、计算指标、绘制图表。
2. Reviewer: 负责根据Coder的运行结果，撰写专业的金融分析报告。

你的职责是根据当前的消息历史，判断下一步应该由谁执行。
```

**新增内容**：
```
在第 2 点之后添加：

3. Reporter: 负责搜索财经新闻、舆情和市场事件，提供定性分析素材。

【何时派遣 Reporter】：
- 用户问"为什么"、"最近"、"发生了什么"等
- 关键词触发：["新闻", "为什么", "最近", "事件", "公告", "利好", "利空"]
- Coder 执行后，如果问题不是纯数据性的，派给 Reporter 补充新闻
```

**为什么安全**：
- ✅ 只是改 System Prompt 中的文字
- ✅ 不改 LangGraph 的流程、不改路由逻辑
- ✅ 最多是让 LLM 选择不同的路由，但路由本身没变
- ✅ 可以随时调整或删除，无代码侵入

**改动量**：约 10-15 行文字

---

### **【改动 4】multi_agent.py - supervisor_node() 中的任务分解**

**目标**：在任务分解时识别是否需要消息面

**改动位置**：L280-285（`if (last_sender == "User" or task_plan is None):`）

**改动类型**：**加逻辑（低风险，可以 try-except 保护）**

**具体内容**：

**原有逻辑**：
```python
if (last_sender == "User" or task_plan is None) and trimmed_messages:
    user_query = trimmed_messages[-1].content
    plan = decompose_task(user_query)
    remaining_steps = plan.get("steps", []).copy()
    task_plan = plan
```

**新增逻辑**：
```python
if (last_sender == "User" or task_plan is None) and trimmed_messages:
    user_query = trimmed_messages[-1].content
    plan = decompose_task(user_query)
    remaining_steps = plan.get("steps", []).copy()
    task_plan = plan
    
    # 【新增】分析是否需要消息面
    news_keywords = ["新闻", "为什么", "最近", "事件", "公告", "利好", "利空"]
    needs_news = any(kw in user_query for kw in news_keywords)
    
    # 【新增】如果需要新闻，设置标志
    if needs_news:
        state["parallel_task_flag"] = True
        state["news_keywords"] = user_query  # 提供搜索线索
```

**为什么安全**：
- ✅ 只是添加一个标志位，不改现有流程
- ✅ 即使 needs_news 判断错了，最多是派遣了不必要的 Reporter
- ✅ Reporter 失败了，系统仍能继续（ErrorHandler 会捕获）
- ✅ 可以用 try-except 包裹，防止任何异常

**改动量**：约 8-12 行

---

### **【改动 5】multi_agent.py - 新增 Reporter 节点**

**目标**：创建 Reporter 节点的代码骨架

**改动位置**：L1860-1920（ErrorHandler 和 Reviewer 之间，或单独一个块）

**改动类型**：**新增函数（复杂但隔离）**

**函数骨架**：
```
def reporter_node(state: MultiAgentState):
    """
    📰 Reporter 节点：财经新闻和舆情搜集
    """
    
    # 【第 1 步】生成 System Prompt
    sys_msg = SystemMessage(content=REPORTER_SYSTEM_PROMPT)
    
    # 【第 2 步】准备消息
    messages = [sys_msg] + state["messages"]
    
    # 【第 3 步】调用 LLM 生成搜索指令
    try:
        response = reporter_model.invoke(messages)
        
        # 【第 4 步】提取搜索关键词
        search_keywords = extract_search_keywords_from_response(response.content)
        
        # 【第 5 步】调用新闻搜索函数
        news_results = search_news_aggregated(
            query=search_keywords.get("query", state.get("news_keywords", "")),
            stock_code=search_keywords.get("stock_code"),
            days=search_keywords.get("days", 30)
        )
        
        # 【第 6 步】返回结果
        return {
            "messages": [response],
            "news_data": json.loads(news_results),
            "last_sender": "Reporter",
            "reporter_ready": True,
            "reporter_error_type": None,
            "reporter_fail_count": 0
        }
    
    except Exception as e:
        # 【错误处理】捕获所有异常，不中断流程
        error_classification = classify_reporter_error(str(e))
        return {
            "messages": [HumanMessage(content=f"新闻搜索失败: {str(e)[:100]}")],
            "news_data": {},
            "last_sender": "Reporter",
            "reporter_ready": True,
            "reporter_error_type": error_classification,
            "reporter_fail_count": state.get("reporter_fail_count", 0) + 1
        }
```

**为什么安全**：
- ✅ 函数是隔离的，不影响现有节点
- ✅ 有完整的 try-except，不会抛出异常
- ✅ 即使失败，也返回有效的 state 字典
- ✅ 可以单独测试，不需要跑整个 Graph

**改动量**：约 50-80 行（包括文档和注释）

---

### **【改动 6】multi_agent.py - StateGraph 中添加 Reporter 节点和连接**

**目标**：将 Reporter 节点集成到 LangGraph 中

**改动位置**：L2142-2193（`workflow.add_node()` 和条件边的定义）

**改动类型**：**加节点和边（遵循现有模式）**

**具体内容**：

**第 1 处**：添加 Reporter 节点（L2143 下方）
```python
# 原有代码：
workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("Coder", coder_node)
workflow.add_node("Reviewer", reviewer_node)

# 【新增】
workflow.add_node("Reporter", reporter_node)  # 在 Coder 后面添加
```

**第 2 处**：修改 Supervisor 的路由选项（L2154-2163）
```python
# 原有代码：
workflow.add_conditional_edges(
    "Supervisor",
    route_supervisor,
    {
        "Coder": "Coder",
        "Reviewer": "Reviewer",
        "ProfileUpdater": "ProfileUpdater",
        "FINISH": END
    }
)

# 【改为】
workflow.add_conditional_edges(
    "Supervisor",
    route_supervisor,
    {
        "Coder": "Coder",
        "Reporter": "Reporter",  # ✨ 新增路由选项
        "Reviewer": "Reviewer",
        "ProfileUpdater": "ProfileUpdater",
        "FINISH": END
    }
)
```

**第 3 处**：添加 Reporter 的输出连接（L2188 下方）
```python
# 原有代码：
workflow.add_edge("Reviewer", "ProfileUpdater")

# 【新增】
workflow.add_edge("Reporter", "Supervisor")  # Reporter 完成后回到 Supervisor 做同步判断
```

**为什么安全**：
- ✅ 只是添加新节点和新边，没删除任何现有的
- ✅ 遵循现有的设计模式（和 ErrorHandler 一样）
- ✅ 即使 Reporter 节点有 bug，其他节点不受影响
- ✅ 可以通过改 route_supervisor() 快速禁用 Reporter

**改动量**：约 5-10 行

---

### **【改动 7】multi_agent.py - 新增 route_supervisor() 的路由逻辑**

**目标**：在 Supervisor 的路由函数中添加对 Reporter 的决策

**改动位置**：约 L207-514（supervisor_node 函数内的路由逻辑）

**改动类型**：**改条件判断（低风险）**

**具体内容**：

**原有逻辑**（大约）：
```python
if execution_status == "success" and last_sender == "Coder":
    # 如果没有步骤了
    if not remaining_steps:
        return {
            "next": "Reviewer",
            ...
        }
```

**新增逻辑**：
```python
if execution_status == "success" and last_sender == "Coder":
    # 检查是否需要从 Reporter 等待数据
    if state.get("parallel_task_flag") and not state.get("reporter_ready"):
        # 并行模式下，Coder 完成了，但 Reporter 还没完成
        # → 等待 Reporter
        return {
            "next": "Supervisor",  # 保持在 Supervisor，不派给 Reviewer
            ...
        }
    
    if not remaining_steps:
        # Coder 完成，Reporter 也完成了（或不需要 Reporter）
        return {
            "next": "Reviewer",
            ...
        }
```

**为什么安全**：
- ✅ 只是添加一个额外的条件检查
- ✅ 不改现有的路由逻辑，只是在路由前多检查一个标志
- ✅ 如果标志设置错了，最多是多执行一次 Supervisor（没有灾难性后果）

**改动量**：约 10-15 行

---

### **【改动 8】multi_agent.py - 新增 REPORTER_SYSTEM_PROMPT**

**目标**：为 Reporter 定义系统提示

**改动位置**：L1217-1369 附近（在 REVIEWER_SYSTEM_PROMPT 之前）

**改动类型**：**新增字符串常量（完全安全）**

**内容框架**：
```python
REPORTER_SYSTEM_PROMPT = """# Role（角色设定）

你是一名财经新闻记者，负责搜索和总结与投资分析相关的新闻、公告和市场事件。

【核心职责】
1. 理解用户的查询意图
2. 生成搜索关键词和股票代码
3. 调用搜索工具获取新闻
4. 整理成结构化的 JSON 格式

【输出格式】
你的输出应该是一个 JSON 对象，包含：
{
    "query": "搜索关键词",
    "stock_code": "股票代码（如果有）",
    "days": 30,  # 时间范围
    "keywords_extracted": ["关键词1", "关键词2"]
}

【质量要求】
- 必须过滤掉广告和无关信息
- 优先使用权威财经媒体的新闻
- 每条新闻标注时间、来源、核心信息
"""
```

**为什么安全**：
- ✅ 只是添加一个新的字符串常量
- ✅ 不改任何执行逻辑
- ✅ 可以随时修改或删除

**改动量**：约 30-50 行

---

### **【改动 9】multi_agent.py - 更新 REVIEWER_SYSTEM_PROMPT**

**目标**：教 Reviewer 如何融合 [DATA] 和 [NEWS]

**改动位置**：L1218-1369（REVIEWER_SYSTEM_PROMPT 字符串中）

**改动类型**：**改 Prompt（完全安全）**

**具体内容**：

**原有 Prompt** 有这些部分：
```
# 处理数据的规范

## 正常情况：[DATA] 存在
```

**新增部分**（在"正常情况"之后添加）：
```
## 扩展情况：[DATA] + [NEWS] 并存

当 Coder 调用了新闻搜索工具时，你会同时收到：
- [DATA]：财务数据和技术指标
- [NEWS]：搜索到的新闻和舆情

### 融合规则：

1. **优先级排序**
   - 数据（[DATA]）是事实基础
   - 新闻（[NEWS]）是背景和解释
   - 用数据验证新闻，用新闻解释数据

2. **冲突检测**
   例：新闻说"分红为 X 元"，财报说"分红为 Y 元"
   → 标注为"需关注数据差异"

3. **输出结构**
   【基本面分析】
     - 使用 [DATA] 的信息
   
   【消息面分析】
     - 使用 [NEWS] 的信息
     - 引用新闻来源和时间
   
   【综合评价】
     - 结合两者给出投资建议
```

**为什么安全**：
- ✅ 只是改 Prompt，不改逻辑
- ✅ LLM 会自动理解并执行新的指导

**改动量**：约 20-30 行

---

### **【改动 10】lib.py - 新增新闻搜索函数**

**目标**：实现 `search_news_aggregated()` 函数供 Reporter 调用

**改动位置**：lib.py 末尾（约 L1096 后）

**改动类型**：**新增函数（隔离）**

**函数框架**：
```python
def search_news_aggregated(query: str, stock_code: str = None, 
                          days: int = 30, limit: int = 10) -> str:
    """
    搜索财经新闻
    
    实现方式（三个选项，按优先级）：
    
    选项 1：使用 Tushare 官方 API（推荐，无需爬虫）
    - pro.news() 获取财经快讯
    - 优点：官方、稳定、无 IP 封禁风险
    
    选项 2：使用 akshare（开源财经库）
    - 实现简单，专为中文财经数据优化
    
    选项 3：BeautifulSoup 爬虫（备选，仅用于测试）
    - 爬取新浪财经、东方财富
    - 缺点：有 IP 封禁风险
    
    返回：JSON 字符串，包含 news 列表
    """
    
    # 【伪代码】
    try:
        # 步骤 1：构造搜索参数
        search_params = {
            "query": query,
            "stock_code": stock_code,
            "time_range": f"last_{days}_days"
        }
        
        # 步骤 2：调用数据源（这里用 Tushare 为例）
        if stock_code:
            # 如果有股票代码，直接搜索该股的新闻
            pro = ts.pro_api()
            # pro.news() 获取新闻（假设有这个接口）
            news_df = pro.news(ts_code=stock_code, limit=limit)
        else:
            # 没有股票代码，用关键词搜索
            # 这需要额外的爬虫或 API
            news_df = search_by_keywords(query, days, limit)
        
        # 步骤 3：清洗和格式化
        result = {
            "query": query,
            "stock_code": stock_code,
            "fetch_time": datetime.now().isoformat(),
            "news": [
                {
                    "title": row["title"],
                    "date": row["pub_date"],
                    "source": row["source"],
                    "content": row["content"][:200]  # 摘要
                }
                for _, row in news_df.iterrows()
            ]
        }
        
        # 步骤 4：返回 JSON 字符串
        return json.dumps(result, ensure_ascii=False)
    
    except Exception as e:
        # 错误处理
        return json.dumps({
            "error": str(e),
            "query": query,
            "news": []
        }, ensure_ascii=False)
```

**为什么安全**：
- ✅ 是一个独立函数，不影响其他代码
- ✅ 完整的 try-except 保护
- ✅ 即使失败，也返回有效的 JSON
- ✅ 可以单独测试

**改动量**：约 60-100 行（包括多种数据源选项）

---

### **【改动 11】multi_agent.py - 辅助函数**

**目标**：添加一些工具函数

**改动位置**：L1860-1900（比较空闲的地方）

**改动类型**：**新增函数（可选）**

**需要的辅助函数**：

1. **extract_search_keywords_from_response(response_text: str) -> dict**
   - 从 Reporter 的 LLM 响应中提取搜索关键词
   - 因为 Reporter 会输出一个 JSON，需要解析它

2. **classify_reporter_error(error_str: str) -> str**
   - 分类 Reporter 的错误
   - 参考 ErrorHandler 的做法（code_error, network_error 等）

**改动量**：约 20-30 行

---

## 🎯 第四部分：改动顺序和依赖关系

```
【推荐改动顺序】（防止依赖问题）

第 1 步：改 MultiAgentState（L47-66）
  → 新增字段
  → 无依赖

第 2 步：改 get_initial_state()（L2217-2267）
  → 初始化新字段
  → 依赖：第 1 步完成

第 3 步：在 lib.py 添加 search_news_aggregated()
  → 新增函数
  → 可以独立完成

第 4 步：新增 REPORTER_SYSTEM_PROMPT（L1217 前）
  → 新增常量
  → 无依赖

第 5 步：新增 reporter_node() 函数（L1860）
  → 新增函数
  → 依赖：第 3、4 步完成

第 6 步：改 Supervisor System Prompt（L220-230）
  → 改 Prompt 文字
  → 无代码依赖

第 7 步：改 supervisor_node() 中的任务分解逻辑（L280-285）
  → 添加意图识别
  → 依赖：第 1 步完成

第 8 步：改 supervisor_node() 中的路由逻辑（L207-514）
  → 添加 Reporter 的同步检查
  → 依赖：第 1、7 步完成

第 9 步：改 StateGraph（L2142-2193）
  → 添加节点和边
  → 依赖：第 5、8 步完成

第 10 步：改 REVIEWER_SYSTEM_PROMPT（L1218-1369）
  → 添加融合指导
  → 无代码依赖

第 11 步：添加辅助函数（L1860-1900）
  → extract_search_keywords...
  → classify_reporter_error...
  → 依赖：第 5 步完成
```

---

## 🛡️ 第五部分：风险评估和缓解

### **改动风险分级**

| 风险项 | 等级 | 说明 | 缓解方案 |
|--------|------|------|---------|
| **State 字段添加** | 🟢 极低 | 字段都有默认值 | 检查 get_initial_state() 的初始化 |
| **Reporter 节点新增** | 🟡 低 | 隔离的函数，有 try-except | 先用 print() 打印日志，观察执行流程 |
| **Supervisor 路由改动** | 🟡 低 | 只是添加条件，不删除现有逻辑 | 保留原有路由选项，新选项作为"可选" |
| **StateGraph 连接** | 🟢 极低 | 遵循现有模式 | 确保所有节点都有入边和出边 |
| **Prompt 修改** | 🟢 极低 | 文字改动，无代码影响 | 监控 LLM 的决策是否符合预期 |
| **新闻搜索 API** | 🟡 低 | 外部 API 可能失败 | 所有调用都用 try-except，降级处理 |

### **"哪些改动最容易出错"**

```
❌ 最容易出错的 3 个地方：

1. 【State 字段类型定义】
   问题：在 TypedDict 中声明的字段类型不匹配
   例如：news_data: dict，但返回的是 str
   
   缓解：
   ✅ 用 Union[dict, str] 表示可能的多种类型
   ✅ 在返回前检查类型：isinstance(news_data, dict)
   ✅ 用 json.dumps() 确保能序列化

2. 【Reporter 函数的返回值】
   问题：返回的字典字段不完整，后续节点读取时 KeyError
   例如：返回了 {"messages": ...}，但漏了 "last_sender"
   
   缓解：
   ✅ 参考 coder_node() 的返回值格式
   ✅ 确保返回的字典包含所有可能被读取的字段
   ✅ 用 state.get("field", default) 代替直接访问

3. 【StateGraph 的节点连接】
   问题：Reporter 的输出没有连接到正确的下一个节点
   例如：reporter_node() 没有边连接到 Supervisor
   
   缓解：
   ✅ 检查 workflow.add_edge() 是否覆盖了所有节点
   ✅ 用 workflow.compile() 后检查图的有效性
   ✅ 画出拓扑图，确认没有"悬挂"的节点
```

---

## 📊 第六部分：改动量化统计

```
文件        改动行数    改动类型        难度    安全性
────────────────────────────────────────────────
multi_agent.py
  ├─ State      8         新增字段      ⭐     🟢
  ├─ initial    10        新增初始值    ⭐     🟢
  ├─ Supervisor_Prompt  15  改文字     ⭐     🟢
  ├─ task_decompose    12   改逻辑     ⭐⭐   🟡
  ├─ reporter_node    70    新增函数    ⭐⭐   🟡
  ├─ route_logic      15    改条件     ⭐⭐   🟡
  ├─ REPORTER_PROMPT  40    新增常量    ⭐     🟢
  ├─ REVIEWER_PROMPT  25    改 Prompt   ⭐     🟢
  ├─ StateGraph       10    新增边      ⭐     🟢
  ├─ helper_funcs     30    新增函数    ⭐⭐   🟡
  └─ 小计             235-250 行

lib.py
  └─ search_news      80-100  新增函数   ⭐⭐⭐  🟡

grtu.py （可选）
  └─ 前端展示        30-50   新增组件   ⭐⭐   🟡

────────────────────────────────────────────────
【总计】  345-400 行代码改动
```

---

## ✅ 第七部分：不会出现"报错无法输出"的关键保障

### **系统的容错机制**

```
【保障 1】：异常处理链
User Query
  ↓
Supervisor (如果崩溃 → 记录日志，继续)
  ↓
Coder / Reporter (如果崩溃 → ErrorHandler 捕获)
  ↓
Tools / 外部 API (如果失败 → ToolMessage 记录，继续)
  ↓
Reviewer (即使收到空数据 → 仍能生成报告 + 警告)
  ↓
前端展示 (总会有输出，最坏情况是"失败报告")

【保障 2】：State 的防御性编程
- 所有字段都有默认值
- 所有读取都用 state.get("field", default)
- 不会因为缺字段而崩溃

【保障 3】：Message 的累积机制
- messages 用 operator.add，会自动追加
- 即使某个节点失败，消息仍保留
- Reviewer 能看到所有历史信息

【保障 4】：Supervisor 的多重路由
- 主路由失败 → 降级到关键字匹配
- 关键字匹配失败 → 回到状态机
- 保证总能做出决策
```

### **"如果 Reporter 失败了会怎样"**

```
场景：Reporter 搜索新闻时超时或 API 错误

执行流程：
Step 1. reporter_node() 捕获异常 ← 有 try-except
        返回 {"news_data": {}, "reporter_error_type": "network_error", ...}

Step 2. ErrorHandler 检查状态 ← last_sender="Reporter"
        看到 reporter_error_type，分类为网络错误

Step 3. ErrorHandler 决策
        如果 reporter_fail_count < 3 → 重试 Reporter
        否则 → 派给 Supervisor，跳过新闻

Step 4. Supervisor 看到 reporter_fail_count >= 3
        设置 parallel_task_flag = False
        派给 Reviewer（无新闻）

Step 5. Reviewer 接收 [DATA]（有）+ [NEWS]（无/空）
        照常生成报告，并在"消息面"部分标注"新闻搜索失败"

Step 6. 前端输出：财务分析报告 + "新闻搜索失败的警告"
        ✅ 系统仍能输出完整的分析，只是少了新闻部分
```

---

## 🎯 第八部分：验证方案（改动后如何测试）

### **改动后的验证步骤**

```
【第 1 步】：单元测试（每个改动单独测试）

□ 测试 State 初始化
  print(get_initial_state())
  → 检查 news_data, reporter_ready 等字段是否存在

□ 测试 Reporter 节点
  state = get_initial_state()
  result = reporter_node(state)
  print(result)
  → 检查返回值是否包含所有必要字段

□ 测试新闻搜索函数
  news = search_news_aggregated("分红", "601398.SH")
  print(news)
  → 检查是否返回有效的 JSON

【第 2 步】：集成测试（整个流程）

□ 运行完整流程（用户查询 → 最终报告）
  用户输入："茅台为什么大涨？"
  → 观察 Supervisor 是否识别为需要新闻
  → 观察 Reporter 是否执行
  → 观察 Reviewer 是否融合了 [DATA] + [NEWS]

□ 测试降级方案
  手动注释掉 search_news_aggregated() 中的实现
  → 观察 Reporter 是否优雅地失败
  → 观察系统是否仍能输出报告

【第 3 步】：日志观察

在改动的地方都加 print()，观察执行流程：

print(f"[Supervisor] 检测到需要新闻: {needs_news}")
print(f"[Reporter] 开始搜索新闻: {search_keywords}")
print(f"[Reporter] 搜索结果: {news_data}")
print(f"[Reviewer] 接收到 [DATA] + [NEWS]: {state['news_data']}")

【第 4 步】：边界测试

□ 新闻搜索失败
  让 search_news_aggregated() 抛异常
  → 系统应降级，仍能输出报告

□ Reporter 超时
  设置 timeout，让 Reporter 超时
  → 系统应捕获，派给 Supervisor 重新路由

□ 不需要新闻的查询
  用户输入："茅台的 PE 是多少？"
  → Supervisor 应识别为不需要新闻
  → Reporter 不应执行
```

---

## 💡 第九部分：改动完成后的预期效果

### **改动成功的表现**

```
【用户问】："茅台为什么大涨？"

【改动前的输出】：
  基本面分析：
    PE 值 27.84，过去 3 个月涨幅 +15%，成交量增加...
  
  建议：可以关注...

【改动后的输出】：
  基本面分析：
    PE 值 27.84，过去 3 个月涨幅 +15%，成交量增加...
  
  消息面分析：  ← 【新增！】
    最近（过去 30 天）的关键新闻：
    1. 2024-12-05（财联社）：茅台发布新酒品类...
    2. 2024-12-02（东方财富）：分析师上调目标价...
    ...
  
  综合评价：
    基本面稳健（高 PE 但有增长）
    + 消息面利好（新品类、提价预期）
    = 短期看好
```

---

## 📋 总结：改动清单速记

```
| 改动项 | 文件 | 行数 | 类型 | 风险 |
|--------|------|------|------|------|
| State 新增字段 | multi_agent.py | 8 | 加字段 | 🟢 极低 |
| State 初始化 | multi_agent.py | 10 | 加初值 | 🟢 极低 |
| Supervisor Prompt | multi_agent.py | 15 | 改文字 | 🟢 极低 |
| 任务分解逻辑 | multi_agent.py | 12 | 改逻辑 | 🟡 低 |
| Reporter 节点 | multi_agent.py | 70 | 新函数 | 🟡 低 |
| 路由逻辑 | multi_agent.py | 15 | 改条件 | 🟡 低 |
| Reporter Prompt | multi_agent.py | 40 | 新常量 | 🟢 极低 |
| Reviewer Prompt | multi_agent.py | 25 | 改文字 | 🟢 极低 |
| StateGraph | multi_agent.py | 10 | 新边 | 🟢 极低 |
| 辅助函数 | multi_agent.py | 30 | 新函数 | 🟡 低 |
| 新闻搜索函数 | lib.py | 80-100 | 新函数 | 🟡 低 |
| 前端展示（可选）| grtu.py | 30-50 | 新组件 | 🟡 低 |
```

---

## 🎓 最终结论

### **为什么改动后"不会报错无法输出"**

1. ✅ **State 有完整的默认值** → KeyError 不会出现
2. ✅ **所有 API 调用都有 try-except** → 即使失败也有降级
3. ✅ **系统的容错链完善** → 任何环节失败都有兜底
4. ✅ **Supervisor 的多重路由** → 保证总能做出决策
5. ✅ **Reviewer 能处理空/错误数据** → 总能输出报告

### **最坏情况**

```
用户输入："茅台为什么大涨？"
     ↓
所有新闻 API 都失败
     ↓
Reporter 的新闻搜索返回空结果
     ↓
Reviewer 仍然输出报告
     ↓
前端显示："基本面分析：... 消息面分析：未能获取近期新闻"
     ↓
✅ 系统仍然能输出完整的分析报告，只是少了新闻部分
```

---

**结论**：这个改动方案设计得很保守，所有新功能都是"可选"的，系统的主流程（Coder → Reviewer）完全不受影响。改动会成功，报错和无法输出的概率极低。

