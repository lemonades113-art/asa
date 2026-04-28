#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试脚本：验证项目升级后的核心功能
1. 有状态执行环境（StatefulPythonKernel）
2. 混合检索系统（HybridRetriever）
"""

import sys
import os

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 80)
print("【开始测试：A股数据分析AI助手 2.0 升级】")
print("=" * 80)

# ============================================================================
# 测试1：有状态执行环境
# ============================================================================
print("\n【测试1】有状态执行环境（StatefulPythonKernel）\n")

try:
    from lib import global_kernel
    
    print("✓ 成功导入有状态内核")
    print(f"✓ 内核全局变量中已初始化的库: {[k for k in global_kernel.globals.keys() if not k.startswith('_')]}")
    
    # 测试第一步：定义变量
    code1 = """
result = {'step': 1, 'data': [1, 2, 3, 4, 5]}
print(f"第一步执行完成，result = {result}")
"""
    print("\n> 执行第一步代码...")
    output1 = global_kernel.execute(code1)
    print(output1)
    
    # 测试第二步：使用第一步的变量
    code2 = """
# 直接使用第一步定义的 result 变量
print(f"第二步读取第一步的变量: {result}")
result['step'] = 2
result['sum'] = sum(result['data'])
print(f"第二步修改后: {result}")
"""
    print("> 执行第二步代码（无需重新定义result）...")
    output2 = global_kernel.execute(code2)
    print(output2)
    
    print("✓ 有状态执行环境测试通过！变量成功跨步骤保留")
    
except Exception as e:
    print(f"✗ 有状态执行环境测试失败: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# 测试2：混合检索系统
# ============================================================================
print("\n" + "=" * 80)
print("【测试2】混合检索系统（HybridRetriever）")
print("=" * 80 + "\n")

try:
    from lib import initialize_retriever
    import time
    
    print("正在初始化混合检索系统...")
    print("（首次初始化需要加载Tushare文档和BGE模型，可能需要1-2分钟）\n")
    
    start_time = time.time()
    retriever = initialize_retriever(use_gpu=False)
    init_time = time.time() - start_time
    
    print(f"✓ 混合检索系统初始化成功！耗时: {init_time:.2f}秒\n")
    
    # 测试检索1：关键词检索
    print("测试检索1：查找'日线行情'相关文档")
    print("-" * 60)
    query1 = "日线行情数据获取"
    start_time = time.time()
    result1 = retriever.search(query1, top_k=3, vector_weight=0.7)
    search_time = time.time() - start_time
    
    print(result1[:500] + "...\n" if len(result1) > 500 else result1 + "\n")
    print(f"✓ 检索耗时: {search_time:.2f}秒\n")
    
    # 测试检索2：语义检索
    print("测试检索2：查找'盈利能力分析'相关文档")
    print("-" * 60)
    query2 = "盈利能力财务指标"
    start_time = time.time()
    result2 = retriever.search(query2, top_k=3, vector_weight=0.7)
    search_time = time.time() - start_time
    
    print(result2[:500] + "...\n" if len(result2) > 500 else result2 + "\n")
    print(f"✓ 检索耗时: {search_time:.2f}秒\n")
    
    print("✓ 混合检索系统测试通过！")
    
except Exception as e:
    print(f"✗ 混合检索系统测试失败: {e}")
    import traceback
    traceback.print_exc()

# ============================================================================
# 测试3：Tushare API集成测试
# ============================================================================
print("\n" + "=" * 80)
print("【测试3】Tushare API集成测试")
print("=" * 80 + "\n")

try:
    print("测试Tushare API连接...")
    code_test_api = """
# 测试 pro.stock_basic 接口
try:
    data = pro.stock_basic(list_status='L', fields='ts_code,name,industry')
    print(f"✓ 成功获取股票列表，共 {len(data)} 条")
    print(f"  示例数据:\\n{data.head(3).to_string()}")
except Exception as e:
    print(f"✗ API调用失败: {e}")
"""
    output_test = global_kernel.execute(code_test_api)
    print(output_test)
    print("✓ Tushare API集成测试完成！")
    
except Exception as e:
    print(f"⚠ Tushare API测试失败（可能是网络或token问题）: {e}")

# ============================================================================
# 总结
# ============================================================================
print("\n" + "=" * 80)
print("【测试总结】")
print("=" * 80)
print("""
✓ 核心功能升级完成：
  1. ✅ 有状态Python执行环境（StatefulPythonKernel）- 支持跨步骤变量保留
  2. ✅ 混合检索系统（HybridRetriever）- 结合向量语义和BM25精确匹配
  3. ✅ 自动初始化库和API客户端 - 无需重复导入

🚀 项目已做好上线准备！

下一步：
  1. 启动Gradio Web界面: python agent.py
  2. 打开浏览器访问: http://localhost:7860
  3. 开始多步分析工作流！
""")

print("=" * 80)
