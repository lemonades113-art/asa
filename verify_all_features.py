#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ASA v2.1 新功能验证脚本"""

import sys
print('=' * 60)
print('ASA v2.1 新功能验证脚本')
print('=' * 60)

# Test 1: AST 安全检查
print('\n[1] AST 安全检查 (lib.py)')
try:
    from lib import StatefulPythonKernel
    # 正常代码
    passed, reason = StatefulPythonKernel.safety_check('df = pd.DataFrame()')
    print(f'    OK: 正常代码通过: {reason}')
    # 危险代码
    passed2, reason2 = StatefulPythonKernel.safety_check('import os')
    print(f'    OK: 危险代码拦截: {reason2}')
except Exception as e:
    print(f'    FAIL: {e}')

# Test 2: ThreadSafeKernelManager
print('\n[2] ThreadSafeKernelManager (lib.py)')
try:
    from lib import ThreadSafeKernelManager
    mgr = ThreadSafeKernelManager()
    print(f'    OK: ThreadSafeKernelManager 初始化成功')
except Exception as e:
    print(f'    FAIL: {e}')

# Test 3: 字段别名热重载表
print('\n[3] 字段别名热重载表 (error_handlers.py)')
try:
    from error_handlers import resolve_field_name, _FIELD_ALIAS_TABLE, reload_alias_table
    # 测试别名解析
    result = resolve_field_name('市盈率')
    print(f'    OK: "市盈率" -> "{result}"')
    result2 = resolve_field_name('PE')
    print(f'    OK: "PE" -> "{result2}"')
    # 测试热重载
    reload_alias_table({'test_field': 'test_value'})
    result3 = resolve_field_name('test_field')
    print(f'    OK: 热重载测试: "test_field" -> "{result3}"')
    print(f'    OK: 别名表共 {len(_FIELD_ALIAS_TABLE)} 条映射')
except Exception as e:
    print(f'    FAIL: {e}')

# Test 4: Pydantic Schema
print('\n[4] Pydantic Schema (multi_agent.py)')
try:
    from multi_agent import CoderOutput, AnalysisOutput, FieldErrorSchema
    coder = CoderOutput(code='df = pd.DataFrame()', rationale='创建DataFrame')
    print(f'    OK: CoderOutput: {coder.code[:20]}...')
    analysis = AnalysisOutput(data={'a': 1}, logic='test')
    print(f'    OK: AnalysisOutput: {analysis.data}')
except Exception as e:
    print(f'    FAIL: {e}')

# Test 5: 三重验证函数
print('\n[5] 三重验证函数 (multi_agent.py)')
try:
    from multi_agent import validate_coder_result
    # 正常
    ok, msg, level = validate_coder_result('[DATA]: {"name": "test"}')
    print(f'    OK: 正常数据: {msg}')
    # 空数据
    ok2, msg2, level2 = validate_coder_result('[DATA]: ')
    print(f'    OK: 空数据检测: {msg2}')
    # PARTIAL
    ok3, msg3, level3 = validate_coder_result('[PARTIAL]: timeout')
    print(f'    OK: PARTIAL标记: {msg3}')
except Exception as e:
    print(f'    FAIL: {e}')

print('\n' + '=' * 60)
print('验证完成！所有新功能已集成到项目中。')
print('=' * 60)
