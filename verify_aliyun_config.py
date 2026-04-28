#!/usr/bin/env python3
"""
验证阿里云 API 和 Tushare 配置是否正确
"""

import sys
import traceback

print("\n" + "="*60)
print("🔧 阿里云 API + Tushare 配置验证工具")
print("="*60)

# ========================================
# 第一步: 验证配置文件
# ========================================
print("\n【第一步】验证配置文件...")
try:
    import conf
    print("✅ conf.py 导入成功")
    
    # 检查阿里云配置
    assert hasattr(conf, 'base_url'), "❌ 缺少 base_url"
    assert hasattr(conf, 'api_key'), "❌ 缺少 api_key"
    assert hasattr(conf, 'tushare_token'), "❌ 缺少 tushare_token"
    
    print(f"✅ base_url: {conf.base_url}")
    print(f"✅ api_key: {conf.api_key[:10]}...{conf.api_key[-10:]}")  # 隐藏中间部分
    print(f"✅ tushare_token: {conf.tushare_token[:10]}...{conf.tushare_token[-10:]}")
    
except Exception as e:
    print(f"❌ 配置文件验证失败: {e}")
    traceback.print_exc()
    sys.exit(1)

# ========================================
# 第二步: 验证 ChatOpenAI 导入
# ========================================
print("\n【第二步】验证 ChatOpenAI 库...")
try:
    from langchain_openai import ChatOpenAI
    print("✅ ChatOpenAI 导入成功")
except Exception as e:
    print(f"❌ ChatOpenAI 导入失败: {e}")
    print("   解决方案: pip install langchain-openai")
    sys.exit(1)

# ========================================
# 第三步: 验证模型初始化
# ========================================
print("\n【第三步】验证模型初始化...")
try:
    from lib import get_chat_model
    print("✅ get_chat_model 导入成功")
    
    # 尝试创建模型实例
    print("\n   创建 smart 模型 (qwen-plus)...")
    smart_model = get_chat_model(model_type="smart")
    print("   ✅ qwen-plus 模型创建成功")
    
    print("\n   创建 fast 模型 (qwen-turbo)...")
    fast_model = get_chat_model(model_type="fast")
    print("   ✅ qwen-turbo 模型创建成功")
    
    print("\n   创建 default 模型 (qwen-plus)...")
    default_model = get_chat_model(model_type="default")
    print("   ✅ default 模型创建成功")
    
except Exception as e:
    print(f"❌ 模型创建失败: {e}")
    traceback.print_exc()
    print("\n   这可能是因为:")
    print("   1. API Key 不正确")
    print("   2. 网络连接问题")
    print("   3. 模型名称不正确")
    sys.exit(1)

# ========================================
# 第四步: 验证 Tushare 配置
# ========================================
print("\n【第四步】验证 Tushare 配置...")
try:
    import tushare as ts
    print("✅ tushare 库导入成功")
    
    # 设置 token
    ts.set_token(conf.tushare_token)
    print("✅ Tushare token 设置成功")
    
    # 获取 API 实例
    pro = ts.pro_api()
    print("✅ Tushare Pro API 初始化成功")
    
    # 尝试调用一个简单的接口
    print("\n   测试简单 API 调用 (获取交易日历)...")
    data = pro.query('trade_cal', exchange='SSE', start_date='20250101', end_date='20250131')
    print(f"   ✅ API 调用成功! 获取了 {len(data)} 条记录")
    
except Exception as e:
    print(f"⚠️  Tushare 验证失败: {e}")
    print("\n   这可能是因为:")
    print("   1. Token 不正确")
    print("   2. 网络连接问题")
    print("   3. API 配额已用尽")
    print("\n   但这不是致命问题，系统仍然可以运行")

# ========================================
# 第五步: 验证 LangGraph
# ========================================
print("\n【第五步】验证 LangGraph...")
try:
    from langgraph.graph import StateGraph
    print("✅ LangGraph 导入成功")
except Exception as e:
    print(f"❌ LangGraph 导入失败: {e}")
    print("   解决方案: pip install langgraph")
    sys.exit(1)

# ========================================
# 第六步: 验证 Agent 初始化
# ========================================
print("\n【第六步】验证 Agent 初始化...")
try:
    from agent import app, initialize_state_with_default_profile
    print("✅ Agent 应用导入成功")
    
    # 验证初始化函数
    state = initialize_state_with_default_profile()
    print("✅ 默认状态初始化成功")
    print(f"   - tool_call_count: {state.get('tool_call_count')}")
    print(f"   - user_profile: {list(state.get('user_profile', {}).keys())}")
    
except Exception as e:
    print(f"❌ Agent 初始化失败: {e}")
    traceback.print_exc()
    sys.exit(1)

# ========================================
# 第七步: 验证 Multi-Agent
# ========================================
print("\n【第七步】验证 Multi-Agent...")
try:
    from multi_agent import graph
    print("✅ Multi-Agent 应用导入成功")
except Exception as e:
    print(f"⚠️  Multi-Agent 初始化失败: {e}")
    print("   这可能需要额外的依赖，但不影响基本功能")

# ========================================
# 完成
# ========================================
print("\n" + "="*60)
print("✅ 所有关键配置验证完成！")
print("="*60)

print("\n📋 配置总结:")
print(f"  • API 端点: {conf.base_url}")
print(f"  • 主模型: qwen-plus (用于复杂任务)")
print(f"  • 快速模型: qwen-turbo (用于轻量级任务)")
print(f"  • Tushare: 已配置 ({conf.tushare_token[:10]}...)")

print("\n🚀 下一步:")
print("  1. 运行基础演示: python demo_complete_workflow.py")
print("  2. 启动 Web UI: python agent_gradio.py")
print("  3. 运行完整演示: python demo_multi_agent_usage.py")

print("\n💡 提示:")
print("  • 所有 API 调用都已配置为使用阿里云通义千问")
print("  • Tushare 可用于获取实时股票数据")
print("  • 如果出现 API 错误，请检查网络连接和配额")

print()
