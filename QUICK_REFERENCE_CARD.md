# 多智能体系统 - 快速参考卡（基于代码分析）

## 🎯 系统核心架构

```
User Query
    ↓
【Supervisor】任务路由 + 分解 + 重规划
    ├─ 分析用户问题
    ├─ 分解成子任务
    ├─ 当retry_count >= 3时触发重规划
    └─ 路由到：Coder / Reviewer / ProfileUpdater / FINISH
    ↓
【Coder】执行数据查询 + 编程
    ├─ 执行工具调用 + 数据处理
    ├─ 强制输出[DATE][SOURCE][META][DATA]标签
    ├─ 支持自救方案A/B/C（改策略）
    ├─ 最多重试3次（code_error计数）
    └─ 网络错误独立计数（不占用code_error重试次数）
    ↓
【Tools】工具调用（支持缓存）
    ├─ ToolCache分层缓存
    ├─ realtime工具：30秒TTL
    ├─ daily工具：300秒TTL
    └─ 默认：60秒TTL
    ↓
【ErrorHandler】智能错误处理
    ├─ 四层错误分类：code_error / network_error / auth_error / unknown
    ├─ 代码错误：最多3次重试
    ├─ 网络错误：指数退避重试（独立计数）
    ├─ 认证错误：提示更新凭证
    └─ 重试耗尽：建议Supervisor重规划
    ↓
【Reviewer】生成分析报告
    ├─ 接收Coder的[DATA]
    ├─ 自动过滤污染消息（孤儿ToolMessage等）
    ├─ 生成投资分析报告（3-5段）
    ├─ 失败时生成降级兜底报告
    └─ 最多重试3次
    ↓
【ProfileUpdater】更新用户画像
    ├─ 识别投资风格（激进/稳健/保守）
    ├─ 识别风险偏好（高/中/低）
    ├─ 记录关注行业（禁止过度推理）
    ├─ 记录分析深度偏好（深度/中等/简洁）
    └─ 为下一个会话提供上下文
    ↓
Output Report
```

---

## ✅ 已实现的核心功能

### 1. 多错误层级处理
```
❌ 错误发生
    ↓
【ErrorHandler】四层分类：
  ├─ code_error (Python错误) → 改变策略重试（最多3次）
  ├─ network_error (连接问题) → 指数退避重试（独立计数）
  ├─ auth_error (认证失败) → 提示更新凭证
  └─ unknown (未知错误) → 日志记录并建议手工干预
    ↓
✅ 修复成功 或 🔄 重规划
```

**关键特性：**
- ✅ 网络错误不占用代码错误的重试次数（独立计数）
- ✅ 重试3次仍失败 → Supervisor改变策略而非一直重试
- ✅ 自救方案A/B/C：扩大范围 / 放宽条件 / 换API

### 2. 元数据透传保证

```
【Coder强制输出】
[DATE]: 2025-11-30
[SOURCE]: Tushare (pro_bar接口)
[META]: 股票=600519, 周期=D, 记录数=10, 时间范围=2025-11-20至2025-11-30
[DATA]:
| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 |
|------|------|------|------|------|--------|
| 2025-11-30 | 15.20 | 15.45 | 15.10 | 15.35 | 1230000 |

【Reviewer查证】
[检查是否存在[DATA]标记]
  ├─ ✅ 存在 → 提取数据，生成报告
  └─ ❌ 不存在 → 认为执行失败，触发降级
```

**保证机制：**
- ✅ CODER_SYSTEM_PROMPT第809-826行明确要求四个标签
- ✅ Reviewer在第1130-1140行强制查找[DATA]标记
- ✅ ProfileUpdater在第1315行检查元数据标签
- ✅ 不符合要求 → 系统自动降级处理

### 3. 智能重规划

```
第1-3次：Coder尝试修复（retry_count: 1 → 2 → 3）
    ↓
【关键判断】retry_count >= 3?
    ├─ YES → Supervisor改变任务策略（重规划）
    │          └─ retry_count重置为0（重新开始）
    │          └─ 新策略可能是：降低精度、扩大范围、换API
    │
    └─ NO → ErrorHandler继续重试
```

**重规划过程：**
- ✅ 检查trigger：retry_count >= 3 或 network_retry_count >= 2
- ✅ 生成新策略：而不是机械重试
- ✅ 重置计数器：允许新策略重新尝试3次
- ✅ 流程：Supervisor → ErrorHandler → Supervisor（重规划）→ Coder（新策略）

### 4. 用户画像跨会话学习

```
会话1：
"我对医药和新能源感兴趣"
    ↓
【ProfileUpdater】识别并更新：
  - interested_sectors: ["医药", "新能源"]
  - investment_style: "激进" (推断)
  - preferred_analysis_depth: "深度"
    ↓
保存到 state["user_profile"]

会话2（新建连接）：
get_initial_state(user_profile=...)
    ↓
【Supervisor】能够访问上一个会话的用户画像
    ↓
主动推荐医药和新能源相关的分析
```

**学习规则：**
- ✅ 仅更新"明确提及"的信息（禁止过度推理）
- ✅ 禁止因提到技术指标就添加行业分类
- ✅ 必须有一致的表现才能更新（如多次提到"保守"）
- ⚠️ 当前无数据库持久化（系统重启后丢失，仅在内存中进化）

### 5. 工具缓存分层TTL

```
ToolCache 的三层缓存策略：

realtime工具 (含"realtime"或"current"关键词)
  └─ TTL: 30秒
  └─ 场景：当日实时价格、分钟级数据
  └─ 特点：快速更新，避免重复查询

daily工具 (含"daily"或"history"关键词)
  └─ TTL: 300秒（5分钟）
  └─ 场景：历史日线数据、月线数据
  └─ 特点：相对稳定，缓存时间更长

默认工具 (其他)
  └─ TTL: 60秒
  └─ 场景：通用查询
  └─ 特点：平衡速度和准确性

【缓存命中流程】
查询 → ToolCache.get(tool_name, args)
  ├─ 计算缓存key（MD5）
  ├─ 检查是否存在且未过期
  └─ YES → 返回缓存结果（<50ms）
     NO → 执行API调用，保存缓存，返回结果
```

**缓存机制：**
- ✅ 自动TTL失效（第1706行检查时间戳）
- ✅ 手动失效方法：`tool_cache.invalidate(tool_name)`
- ✅ 缓存键基于工具名+参数的MD5（相同查询自动命中）

### 6. 模型分层成本优化

```
强逻辑层（strong models）：deepseek-v3 / gpt-4o
  ├─ Supervisor：复杂的任务分解和路由决策
  ├─ Coder：编程和数据分析
  └─ Reviewer：撰写高质量投资报告
  └─ 成本：高（每次调用3-5秒，token消耗大）

轻量级层（fast models）：gpt-4o-mini
  ├─ ErrorHandler：错误分类和建议
  └─ ProfileUpdater：用户画像更新
  └─ 成本：低（每次调用<1秒，token消耗少）
  └─ 优势：节省50-70%的API成本

【成本估算】
传统架构（全用strong模型）：
  每个查询 = Supervisor(5s) + Coder(5s) + Reviewer(3s) = 13秒
  成本 = 3 × strong_model_cost = 高

分层架构（本系统）：
  每个查询 = Supervisor(5s) + Coder(5s) + ErrorHandler(1s) + Reviewer(3s) + ProfileUpdater(1s) = 15秒
  成本 = 3 × strong + 2 × fast ≈ strong × 2.3（比全strong便宜30-40%）
```

---

## 🚨 关键限制与陷阱

### 1. ProfileUpdater的持久化
❌ **当前问题：** user_profile只保存在内存，系统重启会丢失
✅ **解决方案：** 如需跨会话持久化，需要补充数据库连接（如Redis/PostgreSQL）

### 2. Token超限处理
⚠️ **当前问题：** 长对话可能超过模型的token限制
✅ **缓解措施：** 已有消息修剪（trim_messages_for_context），但没有主动计算token
✅ **改进方向：** 可添加token计算和主动降级

### 3. API速率限制
⚠️ **当前问题：** 如果Tushare返回429（Too Many Requests），ErrorHandler能检测但没有明确的处理
✅ **缓解措施：** 已有缓存机制，减少重复查询

### 4. 并发安全性
⚠️ **当前问题：** ToolCache和state没有线程锁
✅ **适用场景：** 单用户/低并发场景可以工作，高并发时需要加锁

---

## 📊 系统性能指标

| 指标 | 估计值 | 备注 |
|------|--------|------|
| 单个查询（无重试） | 10-16秒 | Supervisor(3-5s) + Coder(3-5s) + Tools(1-2s) + Reviewer(2-3s) + ProfileUpdater(0.5-1s) |
| 单个查询（1次重试） | 18-25秒 | 加上ErrorHandler重试时间 |
| 单个查询（3次重试+重规划） | 35-50秒 | 最坏情况 |
| 缓存命中查询 | <2秒 | 直接返回缓存 + Reviewer生成报告 |
| Coder代码执行 | 3-5秒 | 包括工具调用 |
| Reviewer报告生成 | 2-3秒 | 包括上下文清洗 |
| ErrorHandler分类 | 0.5-1秒 | 使用fast模型 |
| ProfileUpdater更新 | 0.5-1秒 | 使用fast模型 |

---

## 🔍 调试技巧

### 启用详细日志
系统已经内置了丰富的[DEBUG]日志：
```
[DEBUG Supervisor] 接收到用户消息
[DEBUG Coder] 执行结果
[DEBUG Reviewer] 清洁消息数
[DEBUG ErrorHandler] 错误分类
[ToolCache] 命中缓存 / 保存缓存
[TrimMessages] 消息修剪
[ValidateToolCalls] 孤儿消息清理
```

### 快速定位问题
| 症状 | 可能原因 | 调试方向 |
|------|--------|---------|
| Reviewer报告生成失败 | 消息链格式错误 | 查看[ToolMessage]孤儿 |
| 元数据标签缺失 | Coder没有按要求输出 | 检查CODER_SYSTEM_PROMPT |
| 缓存总是MISS | 参数不同或超过TTL | 检查[ToolCache]日志 |
| 无限重试 | retry_count没有到3 | 查看retry_count增长 |
| ProfileUpdater不工作 | user_profile为None | 检查get_initial_state() |

### 常用的验证命令
```python
# 1. 检查系统初始化
python -c "from multi_agent import multi_agent_app; print('✅ 系统初始化成功')"

# 2. 单步测试Supervisor
state = {"messages": [HumanMessage("...")]}
result = supervisor_node(state)

# 3. 检查缓存状态
print(f"缓存条目数: {len(tool_cache.cache)}")

# 4. 清空所有缓存
tool_cache.invalidate()

# 5. 运行完整流程并观察日志
response = multi_agent_app.invoke({"messages": [...]})
```

---

## 🎓 系统学习路径

### 初级（理解架构）
1. 了解5个智能体的角色（Supervisor/Coder/Reviewer/ErrorHandler/ProfileUpdater）
2. 运行Prompt P1-P3（基础验证）
3. 观察系统日志，理解流程

### 中级（理解机制）
1. 理解ErrorHandler的四层错误分类
2. 理解元数据标签的强制输出和验证
3. 运行Prompt P6-P9（进阶验证）
4. 阅读multi_agent.py的核心节点代码

### 高级（深度优化）
1. 理解重规划逻辑和retry_count的reset机制
2. 理解ToolCache的TTL分层策略
3. 理解Reviewer的消息清洗和孤儿处理
4. 运行Prompt P10-P14（复杂场景）
5. 考虑定制化改进（如添加持久化、token计算等）

---

## 📞 常见问题

### Q: 为什么网络错误不占用code_error的重试次数？
**A:** 这是一个聪明的设计。网络错误是暂时的（可能下一秒就好），而代码错误是数据问题（需要改变策略）。分离计数让系统能在网络抖动时更有耐心，但在代码错误时更有决断。

### Q: 为什么Coder必须输出四个标签？
**A:** 这四个标签是数据可验证性的保证：DATE确保时效性，SOURCE说明数据来源，META提供参数和量化信息，DATA是实际内容。没有这些，Reviewer无法确认数据有效性。

### Q: ProfileUpdater为什么禁止过度推理？
**A:** 过度推理容易产生错误的用户画像（如"提到技术指标"就假设用户是"高级交易者"）。保守策略确保用户画像的准确性和可信度。

### Q: 系统支持并发吗？
**A:** 当前设计是单线程/低并发。如果需要并发，需要为state和ToolCache添加线程锁（threading.Lock）。

### Q: 如何实现ProfileUpdater的持久化？
**A:** 需要在state中添加database连接，并在ProfileUpdater节点中添加save/load逻辑。可以参考agent_gradio.py中的ChatInterface类如何管理会话。

---

## ✨ 系统的主要优势

1. **智能错误恢复**：不是机械重试，而是改变策略的智能恢复
2. **元数据透明**：强制输出数据来源和参数，实现可验证性
3. **渐进式重规划**：重试失败后改变思路而非放弃
4. **用户画像学习**：为个性化分析提供基础
5. **成本优化**：分层模型节省30-40%的API成本
6. **缓存加速**：频繁查询直接命中缓存，响应时间<2秒
7. **消息链验证**：自动清洗污染消息，避免API错误
8. **降级兜底**：系统失败时仍能给出可用的基础报告

---

## 🚀 后续可能的改进

1. **数据库持久化**：让ProfileUpdater的学习跨系统重启
2. **Token自适应**：主动计算和管理token消耗
3. **并发支持**：添加线程安全机制支持多用户
4. **速率限制处理**：明确的429/503处理策略
5. **分布式部署**：使用消息队列支持分布式多agent
6. **日志分析**：添加性能监控和异常告警
7. **用户反馈环路**：让用户显式评价报告质量，加强学习
8. **多模型支持**：让用户选择不同的strong/fast模型组合

---

## 📚 相关文件索引

- **代码主文件**：`multi_agent.py`（1963行）
- **前端界面**：`agent_gradio.py`（328行）
- **详细分析**：`PROJECT_REAL_CAPABILITY_ANALYSIS.md`
- **验证Prompt集**：`VERIFIED_PROMPT_COLLECTION.md`（14个验证Prompt）
- **代码vs文档**：`CODE_vs_DOCUMENTATION_ANALYSIS.md`
- **系统引导**：`SYSTEM_CAPABILITY_GUIDE_REVISED.md`
- **技术深度**：`ARCHITECTURE_DEEP_ANALYSIS.md`

