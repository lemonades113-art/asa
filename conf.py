"""
created_by: way
created_time: 2025-11-06 10:57:52
description: API 配置（支持多厂商切换）
"""

# 🔧 模型厂商配置（三选一）
# 方案1: 阿里云通义千问（默认）
# base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# api_key = "sk-a50a3a64975649e69a8bcfae7db0ae0a"  # 阿里云 API Key

# 方案2: DeepSeek（推荐，支持 Function Calling + Structured Output，性价比高）
base_url = "https://api.deepseek.com/v1"
api_key = "sk-37f98c0f403241b99b069f12abc71493"  # DeepSeek API Key

# 方案3: MiniMax M1（支持 Function Calling）
# base_url = "https://api.minimax.chat/v1"
# api_key = "sk-your-minimax-api-key-here"  # MiniMax API Key

# 🟢 Tushare 配置（用于股票数据获取）
tushare_token = "ad7e792fd375410484787145ef0420b5ad2fb43ce9d169746ca5775a"  # Tushare Pro 账户 token