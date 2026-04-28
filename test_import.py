#!/usr/bin/env python
# -*- coding: utf-8 -*-

try:
    from multi_agent import multi_agent_app, get_initial_state
    print("✓ multi_agent 导入成功！")
    print(f"✓ multi_agent_app = {multi_agent_app}")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    import traceback
    traceback.print_exc()
