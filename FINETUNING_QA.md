# ASA 微调深度问答 - 快速参考表

## 📌 核心问题速查

| # | 问题 | 结论 | 代码依据 |
|---|------|------|---------|
| **1** | 开源多跳数据集适合吗？ | ⚠️ 部分适合，需转换格式 | FinQA 答案是 DSL，不是 Python |
| **2** | 不考虑成本要微调吗？ | ✅ 要，目的是"变准"不是"变快" | `trajectory_collector.py` 收集偏好对 |
| **3** | RL 选 GRPO 还是 PPO？ | ✅ GRPO（如果非要用 RL） | 不需要 reward model，更简单 |
| **4** | 数据量要多少？ | DPO 需 500-1K，RL 需 2K-5K | 执行轨迹，不是答案 |
| **5** | 微调什么？ | Coder 的底座模型（Qwen-7B） | `lib.py` 第 56-60 行 |
| **6** | 这算 Agentic RL 吗？ | ⚠️ 轻量版，离线学习 | 用历史日志训练，不是在线交互 |
| **7** | 为什么减少延迟？ | 重试次数减少（3-4 倍） | `BacktrackingRouter` 机制 |
| **8** | 微调比不微调好吗？ | ⚠️ 取决于场景 | 样本 < 500 时不微调 |
| **9** | 评估目的是什么？ | 发现瓶颈，指导优化 | Error-Specific 分层训练 |

---

## 1️⃣ 开源数据集适配性

```
╔══════════════════════════════════════════════════════════════╗
║ 数据集       │ 规模   │ 适配度 │ 原因                        ║
╠══════════════════════════════════════════════════════════════╣
║ FinQA        │ 8.7K   │ ⚠️ 中  │ 答案是 DSL，不是 Python      ║
║ ConvFinQA    │ 3.6K   │ ✅ 高  │ 多轮对话，接近真实交互        ║
║ Fino1        │ 5.5K   │ ✅ 高  │ 包含 GPT-4 推理链            ║
╠══════════════════════════════════════════════════════════════╣
║ 【推荐】ConvFinQA + Fino1 混合使用                            ║
╚══════════════════════════════════════════════════════════════╝

使用方式：
    pip install datasets huggingface_hub
    python run_opensource_dataset.py --dataset convfinqa --num_samples 50
```

---

## 2️⃣ 微调目的（不是变快，是变准）

```python
# 来自 trajectory_collector.py 第 4-22 行
"""
TrajectoryCollector - 轨迹收集器
用于自动收集智能体运行轨迹，为后续 SFT/DPO 微调准备数据

【研究价值】
- 将工程运行过程转化为 Preference Data（偏好数据）
- 格式兼容 DPO (Direct Preference Optimization) 训练
- 支持 Error-Specific 分类，为分层微调提供基础
"""

# 微调后模型学会：
# 1. 正确的 Tushare 字段名：pe_ttm vs pe
# 2. 错误恢复模式：遇到 DataEmpty 用备选数据源
# 3. 格式化输出：返回 [DATA]: {...} 而不是废话
```

---

## 3️⃣ RL 技术选型

```
PPO 流程（❌ 不推荐）：
  1. 训练 Reward Model（需要额外数据）← 多一步
  2. 用 Actor-Critic 优化策略
  3. 需要 on-policy 采样（慢）
  4. 超参：8+ 个

GRPO 流程（✅ 如果非要用 RL）：
  1. 不需要 Reward Model ← 省一步
  2. 用组内相对排序代替绝对 reward
  3. 可以 off-policy（用历史数据）
  4. 超参：3-4 个

DPO 流程（✅✅ 最推荐）：
  1. 直接用 (chosen, rejected) 对训练
  2. 你的 trajectory_collector 已经产生这个格式
  3. 代码 20 行 vs PPO 150 行
```

---

## 4️⃣ 数据量和构造方式

```
数据来源：执行轨迹，不是最终答案

┌─────────────────────────────────────────────────────────────┐
│ 错误理解：                                                  │
│   问题："茅台股价"                                          │
│   答案："1800元"                                            │
│   → 这不是微调数据！                                        │
│                                                             │
│ 正确理解：                                                  │
│   问题："茅台股价"                                          │
│   chosen：                                                  │
│     df = ts.pro_api().daily(ts_code='600519.SH')           │
│     print(df['close'].iloc[0])                             │
│     → 执行成功，输出 1800                                   │
│   rejected：                                                │
│     df = ts.pro_api().daily(code='600519')  # 参数名错了    │
│     → 执行失败，TypeError                                   │
│   → 这才是微调数据！                                        │
└─────────────────────────────────────────────────────────────┘

数据量要求：
  SFT：100-500 个成功轨迹
  DPO：200-1000 个 (chosen, rejected) 对
  RL：2000-5000 个轨迹（需要探索）
```

---

## 5️⃣ 微调对象

```python
# 来自 lib.py 第 42-60 行
def get_chat_model(model_type: str = "default", ...) -> ChatOpenAI:
    config = {
        "smart": {"model": "qwen-plus", "temperature": 0.1},  # 云端 API
        "fast": {"model": "qwen-turbo", "temperature": 0.1},
    }

# 微调后：
def get_chat_model(model_type: str = "default", ...) -> ChatOpenAI:
    config = {
        "smart": {"model": "local-qwen-7b-lora", ...},  # 本地微调模型
        "fast": {"model": "qwen-turbo", ...},           # 仍用 API
    }

微调对象矩阵：
  ┌─────────────────────────────────────────────────┐
  │  Supervisor (路由)      │ ❌ 不微调             │
  │  Coder (代码生成)       │ ✅ 微调（核心）       │ ← 主要目标
  │  Reviewer (审核)        │ ⚠️ 可选              │
  │  ErrorHandler (错误修复)│ ✅ 微调（学修复模式） │
  └─────────────────────────────────────────────────┘
```

---

## 6️⃣ 是否是 Agentic RL？

```
标准 Agentic RL（如 AutoGPT、Voyager）：
  Agent 做决策 → 环境反馈 reward → RL 更新策略 → 继续交互
                      ↑
                  在线学习，边运行边学

ASA 的方式：
  Agent 执行 → 收集轨迹（成功/失败）→ DPO 训练 → 部署新模型
                      ↑
                  离线学习，用历史数据

结论：ASA 是"轻量版 Agentic RL"
  ✅ 更安全：不会训练时搞破坏
  ✅ 更高效：不需要实时交互
  ⚠️ 限制：不能探索全新策略
```

---

## 7️⃣ 为什么减少延迟？

```
延迟来源拆解：

当前（无微调）：
  用户提问
    → Coder 生成代码（200ms）
    → 执行失败（NameError）       ← 重试 1
    → Reviewer 分析（150ms）
    → Coder 重试（200ms）
    → 执行失败（TypeError）       ← 重试 2
    → Coder 再重试（200ms）
    → 执行成功
  总延迟：750ms + 网络 = 1s+

微调后（第一次就对）：
  用户提问
    → Coder 生成代码（200ms）
    → 执行成功                    ← 无重试
  总延迟：200ms + 网络 = 300ms

结论：
  70% 延迟减少来自"重试次数减少"
  不是"模型推理变快"

代码依据：BacktrackingRouter（multi_agent.py 第 78-100 行）
```

---

## 8️⃣ 微调 vs 不微调

```
何时不需要微调：
  ☐ API 模型已经够好（Qwen-Plus 准确率 90%+）
  ☐ 样本量 < 500（容易过拟合）
  ☐ 不需要成本控制
  ☐ 不需要行为固定

何时需要微调：
  ☑ 有大量领域数据（500+）
  ☑ 需要成本控制（API 太贵）
  ☑ 需要固定行为（避免 API 升级变化）
  ☑ 需要特定能力（如"遇到数据为空用备选字段"）

ASA 当前情况：
  - 使用 Qwen-Plus API（已经很准）
  - 轨迹数据只有 10 个样本
  → 现在不需要微调
  → 积累 500+ 轨迹后再考虑
```

---

## 9️⃣ 评估的目的

```
评估 ≠ 优化
评估 = 知道要优化什么

流程：
  评估 50 个 Prompt
      ↓
  发现 TypeError 失败 15 次（最多）
      ↓
  分析 TypeError 的 rejected 样本
      ↓
  发现模型经常把 int 传给期望 str 的函数
      ↓
  收集更多 TypeError 的 (chosen, rejected) 对
      ↓
  用 Error-Specific DPO（β=0.7）专门训练
      ↓
  再评估 → TypeError 失败降到 5 次

代码依据：ERROR_CATEGORIES（trajectory_collector.py 第 37-50 行）
```

---

## 📦 新生成的文件

```
run_opensource_dataset.py (476 行)
├─ 描述：一键运行 FinQA/ConvFinQA 评估
├─ 功能：
│  ├─ 自动下载 HuggingFace 数据集
│  ├─ 转换为 ASA 可用格式
│  ├─ 批量运行并收集轨迹
│  └─ 生成评估报告
└─ 使用：
    pip install datasets huggingface_hub
    python run_opensource_dataset.py --dataset convfinqa --num_samples 50
```

---

## 🚀 立即行动

```bash
# 1. 安装依赖
pip install datasets huggingface_hub

# 2. 运行 ConvFinQA 评估（最适合 ASA）
cd d:\HuaweiMoveData\Users\HUAWEI\Desktop\简历\ASA
python run_opensource_dataset.py --dataset convfinqa --num_samples 50

# 3. 查看数据集适配性分析
python run_opensource_dataset.py --analyze

# 4. 混合多个数据集
python run_opensource_dataset.py --dataset all --num_samples 30
```

---

## 🎯 决策树

```
你现在应该做什么？

1. 数据量 < 500？
   ├─ 是 → 先用 run_opensource_dataset.py 收集更多轨迹
   └─ 否 → 继续

2. API 成本是瓶颈吗？
   ├─ 是 → 微调，部署本地模型
   └─ 否 → 继续

3. 需要行为固定吗？
   ├─ 是 → 微调，避免 API 升级变化
   └─ 否 → 暂时不微调，继续用 API

4. 如果微调，用什么方法？
   ├─ 首选：DPO（你已经有数据格式）
   ├─ 次选：GRPO（如果非要用 RL）
   └─ 不选：PPO（太复杂，需要 reward model）
```
