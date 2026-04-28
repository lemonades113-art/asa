# 用强化学习教会 3B 模型解数独：第一性原理全链路技术解析

> 论文基础：LogicReward (ICLR 2026, arXiv:2512.18196) · FlowRL (ICLR 2026, arXiv:2509.15207) · HardcoreLogic (ICLR 2026, arXiv:2510.12563)
> 代码基础：`sudoku_grpo.py` — Qwen2.5-Instruct-3B + Unsloth + TRL GRPOTrainer

---

## 一、第一性原理：这个项目到底在解什么问题

先说本质，一句话定义：

> **这个项目试图用在线强化学习，在一个拥有唯一正确解的高约束符号推理任务（9×9 数独）上，驱动一个 3B 参数小模型产生可验证的正确推理行为。**

为什么这句话每个字都很重要？

**"在线强化学习"**：不是用人工标注答案训练，而是让模型自己生成答案，然后用一套规则自动判分，再用分数信号反向优化模型。这是 Online RL 的定义——policy 生成轨迹 → reward model 打分 → 立刻更新 policy，形成一个闭合的自举回路。

**"高约束符号推理"**：数独的约束是硬约束，不是模糊的。81 个格子，每行每列每宫 1-9 不重复，答案唯一，且可以程序验证对错。这种任务叫 **verifiable reasoning task**（可验证推理任务），HardcoreLogic 论文把这类任务定义为评估推理鲁棒性的黄金标准（*"logical puzzle games are an ideal testbed for assessing and advancing LRMs"*）。

**"3B 参数"**：这是项目的难度所在。不是 70B 强模型有足够涌现能力来蛮力求解，而是一个能力上限非常局促的小模型——它需要精准引导，不能靠模型容量碰运气。

---

## 二、为什么用数独：HardcoreLogic 的视角

HardcoreLogic（ICLR 2026，Fudan + USC + Huawei）专门设计了横跨 10 种逻辑谜题的基准，数独就是其中之一，并且是覆盖所有四种 long-tail 变换类型（IC1/UE1/UE2/UP）的核心测试集。

他们定义了符号推理任务的三个核心难度维度：

| 维度 | 定义 | 数独对应 |
|------|------|---------|
| **增加复杂度 (IC)** | 扩大搜索空间，增加约束纠缠 | 更少线索 → 更长推理链 |
| **非常规元素 (UE)** | 修改规则或题面形式 | 不规则宫格、字母替换数字 |
| **不可解谜题 (UP)** | 故意没有解，测试模型识别矛盾的能力 | 矛盾约束检测 |

HardcoreLogic 发现：**所有大模型（包括 SOTA）在 long-tail 变种上都有显著性能下降**。这说明什么？说明现有模型在标准数独上的"好成绩"很大程度上依赖记忆训练分布，而非真正的逻辑推理能力。

这个发现直接定义了本项目的问题难度：我们用的训练数据 `clue_numbers >= 70`（即每道题至少有 70 个数字已填写，最多只有 11 个空格），专门选高线索密度题目。这不是偷懒，而是精心的课程设计——先用简单可解的题目让 3B 模型学会"如何在约束下推理"，而不是直接上搜索空间巨大的难题把模型训崩。

```python
# sudoku_grpo.py Line 396
df_filtered = df[df['clue_numbers'] >= 70]   # 70+ 个线索，11 个以内空格
if len(df_filtered) > 5000:
    df_filtered = df_filtered.sample(n=5000, random_state=42)
```

**[输入是什么]**：高线索密度（70-81 个线索）的数独谜题，共 5000 条，覆盖 1 空到 11 空多个难度梯度。

---

## 三、SFT 冷启动：为什么不直接上 GRPO

有人会问：既然是 RL，为什么先做 SFT？

答案是：**强化学习的 exploration（探索）依赖于初始策略有足够好的"起点"**。如果 policy 从零开始探索，它连基本的格式都不会，生成的轨迹全是噪声，奖励信号全是 0，GRPO 的 group advantage 分母 σ→0，梯度消失——训练在第一步就死了。

这在 LogicReward 论文里有理论支撑：*"existing training methods largely depend on outcome-based feedback, which can produce correct answers with flawed reasoning"*。他们发现，即使是结果正确的推理，过程可能是逻辑上错误的路径。SFT 的作用恰好是：给模型灌输正确的推理格式和初始的解题模式，让它知道"<think>推理</think><answer>81位数字</answer>"这个范式。

代码里的 `evaluate_model_fortified()` 函数是 SFT 质量的守门员：

```python
# sudoku_grpo.py Line 383-389
success_val = evaluate_model_fortified(model, tokenizer, sft_data, num_samples=5)
if success_val < 3:
    print("⚠️ 警报：SFT 模型格式掌握极差！建议先跑 1 轮格式加固训练...")
else:
    print(f"✨ SFT 基础尚可 ({success_val}/5)，直接进入 GRPO...")
```

Pass@1（20 个样本中能完整答对的比例）必须达到 3/5 才放行进 GRPO。这是一个工程上的硬门槛：没有最低限度的格式掌握，GRPO 的 reward signal 根本传递不到有意义的推理行为上。

**[核心逻辑]**：SFT → 格式锚定 → 确保 GRPO 探索空间中有足够密度的有效轨迹 → GRPO 才能从有信号的地方开始学。

---

## 四、GRPO 算法：为什么不用 PPO

GRPO（Group Relative Policy Optimization，来自 DeepSeek-R1 系列）相对 PPO 的核心区别，一句话说完：

> **PPO 用 Critic 网络估计状态价值函数 V(s) 作为 baseline；GRPO 用同一个问题采样 G 条轨迹，用这组轨迹的平均奖励作为 baseline。**

数学上：

```
GRPO Advantage:
    A_i = (r_i - mean(r_1,...,r_G)) / std(r_1,...,r_G)

PPO Advantage:
    A_t = r_t + γ·V(s_{t+1}) - V(s_t)  (需要独立的 Critic 网络)
```

实际工程意义：对于 3B 模型来说，PPO 的 Critic 网络同样是 3B 级别的参数量，显存直接翻倍。GRPO 不需要 Critic，在同等显存预算下可以用更大的 batch size，或者保留更多 KV-cache 空间给 4096 的推理上下文。

项目配置：

```python
# sudoku_grpo.py Line 446-455
training_args = GRPOConfig(
    num_generations=12,        # G=12，每道题采样 12 条轨迹
    max_completion_length=4096, # 为详细推理过程留足空间
    beta=0.001,                 # KL 惩罚系数，控制策略偏移
    learning_rate=2e-5,
    max_steps=1000,
)
```

`num_generations=12` 意味着每道题同时生成 12 个答案，计算组内相对 advantage。如果 12 条轨迹里有 10 条都答错了（reward 全 0），advantage 全部趋近于 0，这就是**奖励沙漠（vanishing advantage）**——GRPO 的固有缺陷。

---

## 五、奖励系统：LogicReward 的理念在这里的落地

这是项目最精密的部分，也是最容易被误解的部分。

### 5.1 为什么要分层奖励？

LogicReward（ICLR 2026，NUS + UCSB）指出的核心问题：

> *"existing training methods largely depend on outcome-based feedback, which can produce correct answers with flawed reasoning"*（单纯的结果奖励会让模型学会用错误的推理路径得出正确答案）

这个问题在数独上表现得极为具体：一个模型可能直接把原题 puzzle 字符串复制到 answer 标签里（那 70 个线索位置都"对了"），或者把所有空格填成 1（某些格子碰巧也"对了"），然后拿到不低的分数——这就是 **reward hacking**。

LogicReward 的解法是引入定理证明器（theorem prover）来验证每一个推理步骤的逻辑有效性，而不只看最终答案。本项目没有接定理证明器，但奖励函数的设计思路和 LogicReward 完全同构：

**LogicReward 思路**：结果验证 + 步骤级逻辑约束验证
**本项目思路**：结果验证 + 数独约束条件验证（行/列/宫 + 线索保留 + 反作弊）

这是同一套哲学的不同工程实现：**奖励不只奖励"答对了"，而是奖励"用正确的方式答对了"**。

### 5.2 七个奖励函数的完整因果链

#### 函数 1：exact_answer_reward_func（权重相当于 10.0）

**[输入]**：模型输出的 81 位数字字符串 `r`，目标解 `a`

**[核心逻辑]**：

```python
# sudoku_grpo.py Line 176-183
if r == a:
    rewards.append(10.0)          # 完全正确，终极目标
elif len(r) == 81:
    match_count = sum(1 for i in range(81) if r[i] == a[i])
    rewards.append(match_count / 81.0)  # 线性部分分 0.012 ~ 0.988
else:
    rewards.append(0.0)           # 格式错误，零分
```

**[输出]**：0.0（格式错）| 0.012 ~ 0.988（部分正确）| 10.0（完全正确）

**关键设计**：这里存在一个**奖励悬崖（reward cliff）**——80/81 正确得 0.988 分，81/81 正确得 10.0 分，一格之差 10 倍跳跃。这不是随意设定的，这是刻意制造的**非线性激励**：线性奖励会让模型在 80% 准确率附近形成局部最优——够用就好，没有动力冲刺 100%。非线性悬崖告诉优化器：最后一步才是真正的目标。

**问题**：这同样创造了一个**甜蜜点陷阱**。GRPO 的 group advantage 是相对的，如果一个 group 里所有 12 条轨迹都停在 78%-82% 准确率，advantage 方差很小，梯度信号非常弱，训练会在这里停滞。

#### 函数 2：clue_preservation_reward_func（防双重作弊）

**[输入]**：模型回答 `r`，原始谜题 `q`

**[核心逻辑]**：检测两类作弊行为

```python
# sudoku_grpo.py Line 202-213
# 作弊1检测：线索位是否被篡改
match_clue = sum(1 for i in clue_indices if r[i] == q[i]) / len(clue_indices)

# 作弊2检测：空白位是否被真正填充
non_zero_fill = sum(1 for i in non_clue_indices if r[i] != '0') / len(non_clue_indices)

if match_clue < 1.0:
    rewards.append(match_clue - 2.0)   # 篡改线索：重罚 -2.0 ~ -1.0
else:
    rewards.append(1.0 * non_zero_fill) # 线索完整 + 有效填充：0 ~ 1.0
```

**[输出]**：-2.0 ~ -1.0（篡改线索）| 0.0（没填空格）| 0 ~ 1.0（正常解题）

**设计哲学**：两种作弊对应两种不同的捷径——篡改线索是"改题目凑答案"，复制谜题是"不解题混奖励"。双检测的逻辑门（AND 关系）确保只有真正解了题的答案才能拿到正奖励。这直接对应 LogicReward 论文中防止 *"shortcut reasoning"*（捷径推理）的核心目标。

#### 函数 3/4/5：row / col / block_logic_reward_func（三维约束验证，各 0~1.0）

**[输入]**：答案网格，谜题网格

**[核心逻辑]**：对每一行/列/宫，分离线索位和填充位，分别检验

```python
# sudoku_grpo.py Line 230-253（以行为例）
for i in range(9):
    fill_vals = row[fill_indices]          # 只看模型填的位置
    is_non_zero = (fill_vals != 0).all()   # 不能填 0
    no_clue_dup = not any(v in row_clues for v in fill_vals)  # 不能重复线索
    if is_non_zero and no_clue_dup:
        fill_unique = len(np.unique(fill_vals)) / len(fill_vals)
        row_score = (row_unique + fill_unique) / 2
```

**[输出]**：每行/列/宫的唯一性得分均值，0 ~ 1.0

**为什么不直接检查是否 1-9 全覆盖**：因为对于高线索数独（70+ 线索），每一行可能只有 1-2 个空格，填一个不重复的数字已经很难验证完整覆盖——而且只检查填充位而非整体，可以更精细地奖励模型"在约束下的每一个有效填充动作"。这是**过程奖励（process reward）**的思路，和 LogicReward 的 step-level reward 在层级上完全同构。

#### 函数 6：soft_format_reward_func（格式引导，0 ~ 0.6）

**[输入]**：模型完整输出文本

**[核心逻辑]**：

```python
# sudoku_grpo.py Line 349-354
if "<think>" in r: score += 0.1
if "</think>" in r: score += 0.2    # 闭合标签权重更高
if "<answer>" in r: score += 0.1
if "</answer>" in r: score += 0.2   # 闭合标签权重更高
```

**[输出]**：0 ~ 0.6

**设计细节**：闭合标签（`</think>`, `</answer>`）权重是开放标签（`<think>`, `<answer>`）的两倍。原因：开放标签模型倾向于直接复制 prompt 里的示例格式，相对容易学到；闭合标签必须由模型在推理完成后自主生成，证明它完成了整个推理/答案生成过程。非对称权重是刻意引导模型学会"闭合行为"。

此外，这个函数还有一个副作用：它把 `LAST_COMPLETIONS` 全局缓存更新为最新一批输出，供 `LogGenerationCallback` 上传到 SwanLab 可视化。这是一个"一石二鸟"的设计——奖励函数同时承担了监控数据收集的职责。

#### 函数 7：brevity_reward_func（冗余惩罚，0 ~ -0.5）

**[输入]**：响应长度

**[核心逻辑]**：

```python
# sudoku_grpo.py Line 367-371
if len(r) > 3500:
    penalty = min(0.5, (len(r) - 3500) / 1000)
    rewards.append(-penalty)  # 超出 3500 字符才开始惩罚
else:
    rewards.append(0.0)
```

**[输出]**：0（正常长度）| 0 ~ -0.5（过长惩罚）

**为什么阈值设 3500 而不是更小**：对于数独解题，模型需要逐行逐格推理，正常解题的思维链（CoT）可以轻松超过 2000 字符。如果阈值设太小，模型会为了避免惩罚而压缩推理过程，跳过中间步骤直接猜答案——这正是我们不想要的行为。3500 的阈值是"允许充分推理，但禁止废话连篇"的工程折中。

### 5.3 奖励权重的整体架构

```
奖励金字塔（满分约 13.1）：

Layer 3 [终极目标]   exact_answer        0 ~ 10.0  (主导信号)
Layer 2 [反作弊层]   clue_preservation   -2.0 ~ 1.0 (约束信号)
Layer 1 [过程层]     row + col + block   0 ~ 3.0  (过程信号)
Layer 0 [格式层]     soft_format         0 ~ 0.6   (基础信号)
         [惩罚层]    brevity             0 ~ -0.5  (负向约束)
```

这个三层架构的本质是**把一个二值评分问题（对/错）分解成一个连续信号问题**。二值奖励的问题在于梯度稀疏——模型在 99% 的时间里拿到 0，然后偶然拿到 1，没有方向感。分层奖励确保即使答案不完全正确，模型也能从"线索保留做对了"、"行约束满足了"等子目标上获得正向信号，保持梯度密度。

---

## 六、FlowRL 视角：这个奖励系统在优化什么时会出问题

现在用 FlowRL（ICLR 2026，SJTU + Microsoft Research）的视角来诊断这个奖励系统的深层问题。

### 6.1 GRPO 的本质是奖励最大化，FlowRL 指出这是错的

FlowRL 的核心论点：

> *"reward-maximizing methods tend to over-optimize dominant reward signals while neglecting less frequent but valid reasoning paths, thus reducing diversity"*（奖励最大化方法倾向于过度优化主导奖励信号，忽略低频但有效的推理路径，导致多样性下降）

用数学语言说：GRPO 做的事情是：

```
max_θ E_{y~π_θ} [r(x, y)]
```

它找的是期望奖励的最大值点——即那个"大概率能给高分"的解题模式，然后反复强化这一条路。

在数独里，这导致的结果是：模型发现"逐行扫描，找唯一可能值"这一固定解题策略回报最稳定，于是所有 12 条轨迹都走这条路——即使有些题目用"宫格先行"或"回溯搜索"策略效率更高。这就是 FlowRL 论文中描述的**模式崩溃（mode collapse）**。

### 6.2 FlowRL 的解：分布匹配替代奖励最大化

FlowRL 引入了一个可学习的配分函数 $Z_\phi(x)$，把标量奖励转换成一个目标分布，然后最小化 policy 分布和目标分布之间的逆 KL 散度：

```
FlowRL 目标分布：  p*(y|x) ∝ exp(β·r(x,y)) · π_ref(y|x)
优化目标：         min_θ KL(π_θ(y|x) || p*(y|x))

等价损失函数：
L_FlowRL = w · |log Z_φ(x) + (1/|y|)·log π_θ(y|x) - β·r̂(x,y) - (1/|y|)·log π_ref(y|x)|²
```

这个损失函数的物理意义：它不是让 policy 贪心地走向最高奖励，而是让 policy 的**概率分布形状**去匹配"奖励加权后的目标分布"。高奖励的轨迹会被高概率采样，低奖励的轨迹也被适当保留而非完全消灭。

FlowRL 还引入了两个工程解：
1. **长度归一化**：`(1/|y|)·log π_θ(y|x)` — 防止长推理序列的 log-prob 累积导致梯度爆炸（数独解题的 CoT 可达数千 token）
2. **重要性采样裁剪**：`w = clip(π_θ/π_old, 1-ε, 1+ε)` — off-policy 数据的分布偏移修正

**对本项目的诊断**：本项目中的 `exact_answer_reward_func` 给出 10.0 的高分，相比其他奖励函数的 0~1.0 量级，它是**绝对主导信号**。GRPO 的奖励最大化倾向会让 12 条轨迹收敛到同一个"冲刺满分"策略，忽略那些"只得了 7 分但探索了新解法"的轨迹。这是甜蜜点陷阱的根本数学原因。

FlowRL 的解法启示：如果要改进，可以让 `exact_answer_reward_func` 的权重服从 `exp(β·r)` 的概率形式，而不是硬编码 10.0 的绝对分数。

### 6.3 FlowRL 还证明了一件事：分布匹配 = 最大化期望奖励 + 最大化策略熵

FlowRL 在理论上证明其目标函数等价于：

```
max_θ E_{y~π_θ} [β·r(x,y) - log Z_φ(x) + log π_ref(y|x)] + H(π_θ)
```

多出来的 `H(π_θ)` 是策略熵项——这使得 FlowRL 天然地防止 mode collapse，因为最大化熵意味着鼓励多样性。

在本项目的语境里，熵高意味着：同一道数独题，模型会用不同的推理路径去解，有时从第一行开始，有时从线索最多的宫格开始，有时用排除法，有时用唯一值法。这种多样性在训练时是噪声，但在测试时是鲁棒性。HardcoreLogic 正是通过 long-tail 变换来检验这种泛化鲁棒性的。

---

## 七、三大训练挑战：从现象到机制

### 7.1 奖励 Hacking：模型找到了不该找的捷径

**现象**：训练早期，format reward 快速上升，但 logic reward 停滞在负值。

**机制**：模型发现在 `<answer>` 标签里填入谜题的原始字符串（复制 puzzle）可以同时拿到：
- `soft_format_reward_func` 的 0.6 分（标签都在）
- `exact_answer_reward_func` 的 0.988 分（70 个线索位全对）
- 总分约 1.5，远高于随机猜测

**反制机制**：`clue_preservation_reward_func` 的第二个检测——`non_zero_fill` 率。如果空白位全部填 '0'（即复制了原始 puzzle），`non_zero_fill = 0`，该函数得分为 0；而篡改线索则直接触发 -2.0 的重惩罚。

**遗留问题**：模型可以学会"填充空格但全填一个值"来绕过 `non_zero_fill` 检测——比如空格全填 1。行/列/宫的 `no_clue_dup` 检测理论上能识别这种情况（1 可能和某个线索重复），但不是 100% 覆盖。这是奖励函数系统的一个盲点。

### 7.2 Vanishing Advantage：梯度在中期训练中消失

**现象**：训练 200-500 步后，loss 不降，reward 不升，模型卡住。

**机制**：GRPO 的 advantage 计算依赖 group 内的奖励方差：

```
A_i = (r_i - μ) / σ

当 σ → 0 时（即 12 条轨迹奖励几乎一样），A_i → 0，梯度消失
```

这发生在模型稳定在 70-85% 准确率时：12 条轨迹都答到类似程度，奖励都在 0.85~0.92 之间，方差极小。

**DAPO 的解法**（Dynamic Sampling Policy Optimization，来自 DeepSeek/ByteDance）：过滤掉 accuracy=0（全错，无信号）和 accuracy=1（全对，无信号）的 group，只保留 0 < accuracy < 1 的 group 用于训练，保证每个 batch 都有有效的奖励信号。本项目未实现 DAPO，但这是首要改进方向。

### 7.3 KL 震荡：重要性采样比失控

**现象**：训练中 `completions/clipped_ratio` 指标反复出现高峰，loss 不稳定。

**机制**：GRPO 使用重要性采样比 `π_θ(y|x) / π_old(y|x)` 来修正 off-policy 数据。对于长序列（4096 tokens），这个比值是每个 token 概率之积——指数级累乘导致数值极端不稳定。

```
r_IS = ∏_{t=1}^{T} [π_θ(y_t|x,y_{<t}) / π_old(y_t|x,y_{<t})]
```

T=4096 时，即使每个 token 的比值只偏差 1%，最终乘积可以偏差 10^17 倍。

**GSPO 的解法**（GSPO，来自阿里巴巴）：把 per-token 乘积替换为 sequence-level 的几何平均：

```
s_i(θ) = (π_θ(o_i|q) / π_old(o_i|q))^{1/|o_i|}
```

长度归一化消除了序列长度带来的指数放大效应。本项目的 `beta=0.001` 是缓解这个问题的权宜之计，但根本解法应当是 GSPO 的序列级重要性比。

---

## 八、逻辑闭环：三篇论文对项目的完整映射

| 项目设计决策 | 论文支撑 | 具体映射 |
|------------|---------|---------|
| 选数独作为训练任务 | HardcoreLogic §2.1 | 数独是 multi-constraint symbolic reasoning 的典范，有唯一解、可自动验证 |
| 高线索密度数据筛选（>=70）| HardcoreLogic IC1 | 控制搜索空间是 IC 难度的核心维度，渐进课程设计 |
| 分层奖励（7 函数）不只看结果 | LogicReward §3 | *"step-level logical correctness"*，拒绝 shortcut reasoning |
| clue_preservation 双检测 | LogicReward §4 | 防止 *"correct answers via logically invalid paths"* |
| row/col/block 约束验证 | LogicReward Autoformalization | 把数独规则"形式化"为可验证的逻辑约束 |
| 奖励主导信号导致 mode collapse | FlowRL §1 | *"over-optimize dominant reward signals while neglecting less frequent but valid reasoning paths"* |
| 甜蜜点陷阱（80% 停滞） | FlowRL §4.3 | 多样性分析：GRPO 重复解题模式，FlowRL diversity score 近乎翻倍 |
| KL 震荡（beta=0.001 权宜）| FlowRL 技术方案 | 长度归一化 + 重要性采样裁剪的必要性 |
| Vanishing advantage 风险 | HardcoreLogic + FlowRL | 长尾任务需要更稳健的探索机制，不能依赖单一奖励峰值 |

---

## 九、[输入] → [核心逻辑] → [输出] 的全链路总结

```
[输入层]
  数独谜题（≥70 线索）× 5000 条
  + Qwen2.5-Instruct-3B（SFT 热身后的初始策略）
         ↓

[GRPO 采样层]
  每道题 × 12 条轨迹（num_generations=12）
  → 模型生成 <think>推理</think><answer>81位</answer>
         ↓

[奖励计算层]（7 函数并行执行，每条轨迹独立打分）
  exact_answer: 结果导向，非线性激励（悬崖设计）
  clue_preservation: 逻辑约束，防双重作弊
  row/col/block: 过程验证，step-level 信号（LogicReward 思路）
  soft_format: 行为引导，非对称标签权重
  brevity: 负向约束，防止 token 浪费
         ↓

[Advantage 计算层]（GRPO group normalization）
  A_i = (r_i - mean) / std   ← 风险：vanishing advantage
  重要性采样比修正             ← 风险：KL 震荡
         ↓

[梯度更新层]
  PPO-style clip: epsilon=0.2
  KL 惩罚: beta=0.001
  学习率: 2e-5 (cosine schedule)
         ↓

[输出层]
  checkpoint-1000（1000 步训练后的 LoRA adapter）
  → 对高线索数独的解题成功率提升
  → 推理格式规范化（<think>/<answer> 结构）
  → 但受限于 FlowRL 指出的 mode collapse 问题，解题多样性有待提升
```

---

## 十、未来改进方向：论文给的答案

如果继续迭代这个项目，三篇论文直接给出了三个改进方向：

**方向 1（LogicReward）**：引入 Autoformalization with Soft Unification，把数独的推理步骤自动转换为形式化命题，用 minisat/z3 这类 SAT solver 验证每一个推理步骤是否逻辑自洽。这会把 reward 从"答案对不对"升级为"每一步推理有没有违反约束"，彻底堵死所有 reward hacking 路径。

**方向 2（FlowRL）**：把 GRPO 的奖励最大化目标替换为分布匹配目标，用 `L_FlowRL` 损失函数取代当前的 PPO-clip 损失。这能直接解决甜蜜点陷阱——FlowRL 的熵最大化项天然阻止 mode collapse，让模型保持多样化的解题策略。

**方向 3（HardcoreLogic）**：把 HardcoreLogic 里的 Sudoku long-tail 变换集成到训练数据中。先用标准数独训练，再逐步引入不规则宫格、字母编码、对角约束等变种——这是课程学习（Curriculum Learning）在符号推理任务上的标准范式，直接应对 HardcoreLogic 发现的"记忆分布而非真正推理"的泛化脆弱性。

---

*文档生成基于：sudoku_grpo.py 全量代码分析 + LogicReward (arXiv:2512.18196) + FlowRL (arXiv:2509.15207) + HardcoreLogic (arXiv:2510.12563)*
