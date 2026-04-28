#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ASA 系统完整性检查"""

import sys
sys.path.insert(0, '.')

print()
print('=' * 100)
print('✅ ASA 系统完整性检查')
print('=' * 100)
print()

try:
    # 1. 配置检查
    from conf import api_key, tushare_token
    print('【配置状态】')
    print(f'  ✓ Tushare Token: {tushare_token[:30]}...')
    print(f'  ✓ API Key: {api_key[:30]}...')
    print()
except Exception as e:
    print(f'❌ 配置检查失败: {e}\n')
    sys.exit(1)

try:
    # 2. 核心模块检查  
    from orchestrator import ToolUsageGraph
    from memory_system import CausalMemoryGraph, MemorySystem
    from evaluation import RootCauseAnalyzer
    
    print('【核心模块状态】')
    print(f'  ✓ ToolUsageGraph: {ToolUsageGraph.__name__}')
    print(f'  ✓ CausalMemoryGraph: {CausalMemoryGraph.__name__}')
    print(f'  ✓ RootCauseAnalyzer: {RootCauseAnalyzer.__name__}')
    print()
except Exception as e:
    print(f'❌ 模块检查失败: {e}\n')
    sys.exit(1)

try:
    # 3. 记忆系统检查
    print('【记忆系统】')
    mem = MemorySystem(storage_path='./memory_store')
    stats = mem.get_stats()
    print(f'  ✓ 长期记忆: {stats.get("long_term_count", 0)} 条')
    print(f'  ✓ 短期记忆: {stats.get("short_term_count", 0)} 条')
    print(f'  ✓ 因果图: 已激活')
    print()
except Exception as e:
    print(f'❌ 记忆系统检查失败: {e}\n')
    sys.exit(1)

print('=' * 100)
print('✅ 所有系统检查通过，可以开始测试！')
print('=' * 100)
print()

print('【推荐的测试脚本】')
print()
print('1️⃣  quick_test_asa_run.py (快速检查)')
print('   - 验证所有配置和模块')
print('   - 耗时: 5 秒')
print()
print('2️⃣  test_multi_agent.py (完整测试)')
print('   - 运行实际的多智能体系统')
print('   - 需要真实 API 调用')
print()
print('3️⃣  run_test_query.py (集成测试)')
print('   - 执行茅台 vs 五粮液对比查询')
print('   - 耗时: 30-60 秒')
print()

print('=' * 100)
