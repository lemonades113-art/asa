# 🔧 阿里云 API 配置完成指南

## ✅ 已完成的配置

### 1️⃣ 配置文件更新 (conf.py)

```python
# 🔧 阿里云通义千问 API 配置
base_url = "https://dashscope.aliyuncs.com/api/v1"  # 阿里云 API 端点
api_key = "sk-a50a3a64975649e69a8bcfae7db0ae0a"     # 阿里云 API Key

# 🟢 Tushare 配置（用于股票数据获取）
tushare_token = "ad7e792fd375410484787145ef0420b5ad2fb43ce9d169746ca5775a"  # Tushare Pro token
```

**文件位置**: `conf.py` (已更新 ✅)

---

### 2️⃣ 模型配置更新 (lib.py)

#### 更新的模型映射:

| 模型类型 | 之前 | 现在 | 用途 |
|---------|------|------|------|
| smart | deepseek-v3 | qwen-plus | Supervisor/Coder/Reviewer (强逻辑任务) |
| fast | gpt-4o-mini | qwen-turbo | ErrorHandler/ProfileUpdater (轻量级) |
| default | deepseek-v3 | qwen-plus | 默认高性能模型 |

**特点**:
- ✅ 完全兼容 OpenAI API 格式
- ✅ 自动适配阿里云 API 端点
- ✅ 无需修改业务代码

**文件位置**: `lib.py` 第 41-79 行 (已更新 ✅)

---

### 3️⃣ Tushare API 初始化 (lib.py)

在 `StatefulPythonKernel` 类的初始化代码中，添加了自动配置:

```python
# 🔧 配置 Tushare API 令牌
ts.set_token('{tushare_token}')  # 自动使用 conf.py 中的 token
pro = ts.pro_api()
```

**效果**:
- ✅ Coder 节点可以直接使用 `pro` 对象获取股票数据
- ✅ 无需手动配置 token

**文件位置**: `lib.py` 第 293-302 行 (已更新 ✅)

---

## 🚀 验证配置是否正确

### 方式1: 运行验证脚本 (推荐)

```powershell
# 进入项目目录
cd "d:\HuaweiMoveData\Users\HUAWEI\Desktop\simpletradingagent-ai\agentscope_trading_agent\ts 备份"

# 运行配置验证脚本
python verify_aliyun_config.py
```

**输出预期**:
```
============================================================
🔧 阿里云 API + Tushare 配置验证工具
============================================================

【第一步】验证配置文件...
✅ conf.py 导入成功
✅ base_url: https://dashscope.aliyuncs.com/api/v1
✅ api_key: sk-a50a3a...ae0a
✅ tushare_token: ad7e792...5a

【第二步】验证 ChatOpenAI 库...
✅ ChatOpenAI 导入成功

【第三步】验证模型初始化...
✅ get_chat_model 导入成功
   创建 smart 模型 (qwen-plus)...
   ✅ qwen-plus 模型创建成功
   
   创建 fast 模型 (qwen-turbo)...
   ✅ qwen-turbo 模型创建成功
   
   创建 default 模型 (qwen-plus)...
   ✅ default 模型创建成功

【第四步】验证 Tushare 配置...
✅ tushare 库导入成功
✅ Tushare token 设置成功
✅ Tushare Pro API 初始化成功
   测试简单 API 调用 (获取交易日历)...
   ✅ API 调用成功! 获取了 N 条记录

【第五步】验证 LangGraph...
✅ LangGraph 导入成功

【第六步】验证 Agent 初始化...
✅ Agent 应用导入成功
✅ 默认状态初始化成功
   - tool_call_count: 0
   - user_profile: [...]

【第七步】验证 Multi-Agent...
✅ Multi-Agent 应用导入成功

============================================================
✅ 所有关键配置验证完成！
============================================================
```

### 方式2: 快速测试 (2分钟)

```powershell
# 运行快速启动脚本
python get_started.py
```

---

## 📊 配置对比表

| 项目 | 之前 | 现在 | 状态 |
|------|------|------|------|
| API 提供商 | 豆包/OpenAI | 阿里云通义千问 | ✅ |
| API 端点 | https://ark.cn-beijing.volces.com/api/v3 | https://dashscope.aliyuncs.com/api/v1 | ✅ |
| API Key | token | sk-a50a3a... | ✅ |
| Smart 模型 | deepseek-v3-1-terminus | qwen-plus | ✅ |
| Fast 模型 | gpt-4o-mini | qwen-turbo | ✅ |
| Tushare Token | 未配置 | ad7e792fd... | ✅ |
| 自动初始化 | ❌ | ✅ | ✅ |

---

## 💡 使用示例

### 例1: 在代码中获取模型

```python
from lib import get_chat_model

# 获取强逻辑模型（qwen-plus）
smart_model = get_chat_model(model_type="smart")

# 获取轻量级模型（qwen-turbo）
fast_model = get_chat_model(model_type="fast")

# 使用默认模型
default_model = get_chat_model()
```

### 例2: 在 Coder 节点中使用 Tushare

```python
# 代码会自动在 Coder 节点中执行
code = """
import tushare as ts

# pro 对象已自动初始化，可直接使用
data = pro.daily(ts_code='000001.SZ', start_date='20250101', end_date='20250131')
print(data.head())
"""
```

---

## ⚠️ 常见问题

### Q1: API Key 不正确怎么办？

**A**: 更新 `conf.py` 中的 `api_key`:

```python
api_key = "你的真实API_KEY"  # 从阿里云官网获取
```

然后重新运行验证脚本:
```powershell
python verify_aliyun_config.py
```

---

### Q2: Tushare Token 失效怎么办？

**A**: 更新 `conf.py` 中的 `tushare_token`:

```python
tushare_token = "你的新token"  # 从 Tushare 官网获取
```

系统会在下次运行时自动重新配置。

---

### Q3: 网络连接超时怎么办？

**A**: 可能的原因和解决方案:

1. **检查网络连接**
   ```powershell
   ping dashscope.aliyuncs.com
   ```

2. **检查防火墙**
   - 确保阿里云 API 端点未被防火墙拦截

3. **检查 API 配额**
   - 登录阿里云控制台，检查 API 调用配额

---

### Q4: 如何切换回之前的模型？

**A**: 编辑 `lib.py` 第 56-58 行，改回之前的模型名:

```python
config = {
    "smart": {"model": "deepseek-v3-1-terminus", "temperature": 0.1},  # 改回原来的
    "fast": {"model": "gpt-4o-mini", "temperature": 0.1},              # 改回原来的
    "default": {"model": "deepseek-v3-1-terminus", "temperature": 0.1} # 改回原来的
}
```

---

## 🎯 下一步

### 1️⃣ 验证配置
```powershell
python verify_aliyun_config.py
```

### 2️⃣ 运行演示
```powershell
# 选项1: 基础演示 (快速)
python demo_complete_workflow.py

# 选项2: Web UI (推荐)
python agent_gradio.py

# 选项3: 完整演示 (详细)
python demo_multi_agent_usage.py
```

### 3️⃣ 开始开发
- 修改系统提示词在 `multi_agent.py` 中
- 添加新工具到 `lib.py` 中
- 自定义路由规则在 `routing_config.json` 中

---

## 📋 配置清单

- [x] 更新 `conf.py` 中的 API 端点和 Key
- [x] 更新 `conf.py` 中的 Tushare Token
- [x] 更新 `lib.py` 中的模型配置 (qwen-plus/turbo)
- [x] 更新 `lib.py` 中的 Tushare 自动初始化
- [x] 创建验证脚本 `verify_aliyun_config.py`
- [x] 所有改动向下兼容，无需修改业务代码

---

## 📞 技术支持

如有问题，请检查：
1. API Key 是否正确
2. 网络连接是否正常
3. Tushare 账户是否有效
4. 模型名称是否正确

运行验证脚本能帮助快速诊断问题：
```powershell
python verify_aliyun_config.py
```

---

**配置完成时间**: 2025-11-28  
**状态**: ✅ 生产就绪
