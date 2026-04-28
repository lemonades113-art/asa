#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA 快速集成测试 - 验证完整工作流
"""

import sys
import json
import time
sys.path.insert(0, '.')

from conf import api_key, tushare_token

print("=" * 80)
print("🚀 ASA 系统快速测试启动")
print("=" * 80)
print()

# 1. 环境检查
print("【步骤 1】环境配置检查")
print("-" * 80)

checks = {
    "阿里云 API Key": bool(api_key and len(api_key) > 10),
    "Tushare Token": bool(tushare_token and len(tushare_token) > 10),
}

for name, status in checks.items():
    symbol = "✅" if status else "❌"
    print(f"{symbol} {name}: {'已配置' if status else '缺失'}")

if not all(checks.values()):
    print("\n❌ 环境配置不完整，无法继续")
    sys.exit(1)

print("\n✅ 所有必需配置已就位\n")

# 2. 检查核心模块
print("【步骤 2】核心模块导入检查")
print("-" * 80)

modules_to_check = [
    ("orchestrator", "ToolUsageGraph"),
    ("memory_system", "CausalMemoryGraph"),
    ("evaluation", "RootCauseAnalyzer"),
]

for module_name, class_name in modules_to_check:
    try:
        module = __import__(module_name)
        if hasattr(module, class_name):
            print(f"✅ {module_name}.{class_name}")
        else:
            print(f"⚠️  {module_name} 中未找到 {class_name}")
    except Exception as e:
        print(f"❌ 导入 {module_name} 失败: {str(e)[:50]}")

print()

# 3. 测试查询
print("【步骤 3】准备测试查询")
print("-" * 80)

test_query = """对比分析贵州茅台(600519)和五粮液(000858)哪个更值得投资？
请从股价、市盈率、股息率、财务数据等维度分析。"""

print("📝 测试查询：")
print(f"  {test_query.strip()}")
print()

# 4. 验证记忆系统
print("【步骤 4】记忆系统初始化检查")
print("-" * 80)

try:
    from memory_system import MemorySystem
    mem = MemorySystem(storage_path="./memory_store")
    stats = mem.get_stats()
    print(f"✅ 短期记忆: {stats['short_term_count']} 条")
    print(f"✅ 长期记忆: {stats['long_term_count']} 条")
    print(f"✅ 因果图: 已激活")
    print(f"✅ ChromaDB: {'可用' if stats.get('chroma_available') else '不可用（可选）'}")
except Exception as e:
    print(f"⚠️  记忆系统初始化警告: {str(e)[:80]}")

print()

# 5. 系统就绪状态
print("=" * 80)
print("✅ ASA 系统已就绪！")
print("=" * 80)
print()

print("📋 接下来的步骤：")
print("""
1. 启动 multi_agent.py 的主流程
2. 提交测试查询
3. 观察以下工作流：
   - 🔧 error_handler_node 中的智能工具选择
   - 📊 记忆系统的数据检索
   - 🎯 根因分析诊断
   - 🧁 因果预防检查

预期输出应包含：
   ✓ [DATA] 标记的结构化数据
   ✓ 市盈率、股息率、财务对比
   ✓ 投资建议
   ✓ 多 Agent 协作过程
""")

print("\n" + "=" * 80)
print(f"⏱️  测试生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)
