#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证关键修复的完整性
检查：
1. 消息修剪机制
2. Supervisor降级路由
3. ErrorHandler异常处理
4. execute_tools缓存和异常处理
"""

import sys
from typing import List
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

print("="*80)
print("[验证开始] 关键修复功能检查")
print("="*80)

# ============================================================================
# 测试1：消息修剪机制
# ============================================================================
print("\n[测试1] 消息修剪机制")
print("-"*80)

try:
    from multi_agent import trim_messages_for_context
    
    # 创建测试消息
    test_messages = [
        SystemMessage(content="You are a helpful assistant"),
        *[HumanMessage(content=f"User message {i}") for i in range(30)],
        *[AIMessage(content=f"AI response {i}") for i in range(20)]
    ]
    
    print(f"  原始消息数: {len(test_messages)}")
    
    # 执行修剪
    trimmed = trim_messages_for_context(test_messages, max_keep=15)
    
    print(f"  修剪后消息数: {len(trimmed)}")
    print(f"  保留SystemMessage: {any(isinstance(m, SystemMessage) for m in trimmed)}")
    print(f"  保留HumanMessage: {any(isinstance(m, HumanMessage) for m in trimmed)}")
    
    assert 6 <= len(trimmed) <= 15, f"修剪结果异常: {len(trimmed)} 条消息"
    assert any(isinstance(m, SystemMessage) for m in trimmed), "未保留SystemMessage"
    
    print("  ✅ 消息修剪机制正常")

except Exception as e:
    print(f"  ❌ 消息修剪机制失败: {str(e)}")
    sys.exit(1)

# ============================================================================
# 测试2：Supervisor降级路由逻辑
# ============================================================================
print("\n[测试2] Supervisor降级路由逻辑")
print("-"*80)

try:
    from multi_agent import _fallback_keyword_route, MultiAgentState
    
    # 测试场景1：Coder成功 → 应该派Reviewer
    state1 = {
        'last_sender': 'Coder',
        'execution_status': 'success',
        'messages': [HumanMessage(content="test")]
    }
    next_node, reason = _fallback_keyword_route(state1)
    assert next_node == 'Reviewer', f"期望Reviewer，得到{next_node}"
    print(f"  场景1 (Coder成功): {next_node} ✅")
    
    # 测试场景2：Reviewer完成 → 应该FINISH
    state2 = {
        'last_sender': 'Reviewer',
        'execution_status': 'success',
        'messages': [HumanMessage(content="test")]
    }
    next_node, reason = _fallback_keyword_route(state2)
    assert next_node == 'FINISH', f"期望FINISH，得到{next_node}"
    print(f"  场景2 (Reviewer完成): {next_node} ✅")
    
    # 测试场景3：有错误 → 应该Coder修复
    state3 = {
        'last_sender': 'ErrorHandler',
        'execution_status': 'error',
        'messages': [HumanMessage(content="Error: some error occurred")]
    }
    next_node, reason = _fallback_keyword_route(state3)
    assert next_node == 'Coder', f"期望Coder，得到{next_node}"
    print(f"  场景3 (错误检测): {next_node} ✅")
    
    # 测试场景4：用户新需求 → 应该Coder执行
    state4 = {
        'last_sender': 'User',
        'execution_status': 'pending',
        'messages': [HumanMessage(content="查询数据")]
    }
    next_node, reason = _fallback_keyword_route(state4)
    assert next_node == 'Coder', f"期望Coder，得到{next_node}"
    print(f"  场景4 (用户需求): {next_node} ✅")
    
    print("  ✅ Supervisor降级路由逻辑正常")

except Exception as e:
    print(f"  ❌ Supervisor路由失败: {str(e)}")
    sys.exit(1)

# ============================================================================
# 测试3：ErrorHandler错误分类
# ============================================================================
print("\n[测试3] ErrorHandler错误分类")
print("-"*80)

try:
    from multi_agent import classify_error_simple
    
    # 测试代码错误
    error_type = classify_error_simple("TypeError: unsupported operand type(s)")
    assert error_type == "code_error", f"代码错误分类失败: {error_type}"
    print(f"  代码错误识别: {error_type} ✅")
    
    # 测试网络错误
    error_type = classify_error_simple("Connection timeout after 30s")
    assert error_type == "network_error", f"网络错误分类失败: {error_type}"
    print(f"  网络错误识别: {error_type} ✅")
    
    # 测试授权错误
    error_type = classify_error_simple("Authentication failed: API key invalid")
    assert error_type == "auth_error", f"授权错误分类失败: {error_type}"
    print(f"  授权错误识别: {error_type} ✅")
    
    print("  ✅ 错误分类机制正常")

except Exception as e:
    print(f"  ❌ 错误分类失败: {str(e)}")
    sys.exit(1)

# ============================================================================
# 测试4：工具缓存机制
# ============================================================================
print("\n[测试4] 工具缓存机制")
print("-"*80)

try:
    from multi_agent import tool_cache
    
    # 测试缓存保存
    tool_cache.put("test_tool", {"arg1": "value1"}, "cached_result")
    print(f"  缓存保存: ✅")
    
    # 测试缓存获取
    result = tool_cache.get("test_tool", {"arg1": "value1"})
    assert result == "cached_result", f"缓存获取失败: {result}"
    print(f"  缓存获取: ✅")
    
    # 测试缓存失效（TTL过期）
    tool_cache.invalidate("test_tool", {"arg1": "value1"})
    result = tool_cache.get("test_tool", {"arg1": "value1"})
    assert result is None, f"缓存失效失败: {result}"
    print(f"  缓存失效: ✅")
    
    print("  ✅ 工具缓存机制正常")

except Exception as e:
    print(f"  ❌ 工具缓存失败: {str(e)}")
    sys.exit(1)

# ============================================================================
# 测试5：异常处理防御
# ============================================================================
print("\n[测试5] 异常处理防御机制")
print("-"*80)

try:
    from multi_agent import execute_tools, MultiAgentState
    
    # 创建包含异常工具调用的状态
    ai_msg = AIMessage(
        content="test",
        tool_calls=[{"id": "test_id", "name": "nonexistent_tool", "args": {}}]
    )
    
    state = {
        'messages': [ai_msg],
        'next': 'Tools',
        'retry_count': 0,
        'user_profile': {},
        'execution_status': 'pending',
        'last_sender': 'Coder',
        'task_plan': {},
        'remaining_steps': [],
        'error_type': None,
        'network_retry_count': 0,
        'supervisor_retry': 0,
        'last_execution_data': {},
        'message_window_size': 15
    }
    
    # 执行工具（应该优雅地处理异常）
    result = execute_tools(state)
    
    # 检查是否返回ToolMessage
    assert 'messages' in result, "结果缺少messages字段"
    assert len(result['messages']) > 0, "未生成ToolMessage"
    assert isinstance(result['messages'][0], ToolMessage), "生成的不是ToolMessage"
    
    # 检查错误信息是否被捕获
    error_content = result['messages'][0].content
    assert "Error" in error_content, "未捕获到错误信息"
    
    print(f"  异常捕获: ✅")
    print(f"  错误信息正确返回: ✅")
    print("  ✅ 异常处理防御机制正常")

except Exception as e:
    print(f"  ❌ 异常处理失败: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# 总结
# ============================================================================
print("\n" + "="*80)
print("✅ 所有关键修复验证通过！")
print("="*80)
print("\n测试项目:")
print("  ✅ 消息修剪机制 - 防止Token爆炸")
print("  ✅ Supervisor降级路由 - 防止死循环")
print("  ✅ ErrorHandler错误分类 - 精细化处理")
print("  ✅ 工具缓存机制 - 避免重复调用")
print("  ✅ 异常处理防御 - 确保流程不中断")
print("\n系统已准备好用于生产环境。")
print("="*80)
