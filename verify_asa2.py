#!/usr/bin/env python3
"""ASA 2.0 改造验证脚本"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

print("=" * 50)
print("ASA 2.0 改造验证")
print("=" * 50)

# 1. 验证 memory_system
print("\n[1] 验证 memory_system.py...")
try:
    from memory_system import memory_system, get_memory_context, record_successful_execution
    print("    - 导入成功")
    
    # 测试短期记忆
    memory_system.add_short_term("查询贵州茅台股票", "user")
    print(f"    - 短期记忆: {memory_system.short_term.size()} 条")
    
    # 测试记忆上下文
    ctx = get_memory_context("股票查询")
    print(f"    - 记忆上下文: {len(ctx)} 字符")
    
    # 测试成功策略记录
    record_successful_execution(
        query="测试查询",
        strategy="direct_query",
        steps=["步骤1", "步骤2"],
        category="test"
    )
    print("    - 成功策略记录: OK")
    print("    ✓ memory_system 验证通过")
except Exception as e:
    print(f"    ✗ 失败: {e}")

# 2. 验证 orchestrator
print("\n[2] 验证 orchestrator.py...")
try:
    from orchestrator import orchestrator, handle_agent_failure, AgentRole, FallbackLevel
    print("    - 导入成功")
    print(f"    - 冲突策略: {orchestrator.conflict_resolver.strategy}")
    print(f"    - 最大重试: {orchestrator.fallback_manager.max_retries}")
    
    # 测试 fallback
    result = handle_agent_failure("test_agent", "task_1", "timeout")
    print(f"    - Fallback 结果: {result['action']}")
    print("    ✓ orchestrator 验证通过")
except Exception as e:
    print(f"    ✗ 失败: {e}")

# 3. 验证 multi_agent 条件导入
print("\n[3] 验证 multi_agent.py 集成...")
try:
    import multi_agent
    mem_enabled = getattr(multi_agent, 'MEMORY_ENABLED', 'N/A')
    orch_enabled = getattr(multi_agent, 'ORCHESTRATOR_ENABLED', 'N/A')
    print(f"    - MEMORY_ENABLED: {mem_enabled}")
    print(f"    - ORCHESTRATOR_ENABLED: {orch_enabled}")
    
    if mem_enabled and orch_enabled:
        print("    ✓ multi_agent 集成验证通过")
    else:
        print("    ⚠ 部分功能未启用（降级模式）")
except Exception as e:
    print(f"    ✗ 失败: {e}")

print("\n" + "=" * 50)
print("验证完成")
print("=" * 50)
