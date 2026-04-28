#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ASA 综合集成测试 - 实际运行测试查询
执行：python run_test_query.py
"""

import asyncio
import sys
import time
from datetime import datetime

sys.path.insert(0, '.')

async def run_test():
    """运行集成测试"""
    
    print("=" * 100)
    print("🚀 ASA 综合集成测试启动")
    print("=" * 100)
    print()
    
    # 导入核心模块
    try:
        from multi_agent import run_graph
        from memory_system import memory_system
        from orchestrator import tool_monitor
        print("✅ 所有核心模块导入成功\n")
    except Exception as e:
        print(f"❌ 模块导入失败: {e}\n")
        return False
    
    # 测试查询
    test_query = """对比分析贵州茅台(600519)和五粮液(000858)哪个更值得投资？
请从股价、市盈率、股息率、财务数据等维度分析。"""
    
    print("=" * 100)
    print("📋 测试信息")
    print("=" * 100)
    print(f"查询ID：TEST_001")
    print(f"查询内容：{test_query.strip()}")
    print(f"时间戳：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 记录前的状态
    print("【系统状态检查】")
    print(f"  - 长期记忆：{len(memory_system.long_term)} 条")
    print(f"  - 短期记忆：{len(memory_system.short_term)} 条")
    print(f"  - 工具调用监控：已启用")
    print()
    
    # 执行查询
    print("=" * 100)
    print("⏳ 执行查询（预期时间 30-60 秒）")
    print("=" * 100)
    print()
    
    start_time = time.time()
    
    try:
        # 调用多智能体系统
        result = await run_graph(
            query=test_query,
            user_id="test_user",
            conversation_id="test_001"
        )
        
        elapsed_time = time.time() - start_time
        
        # 输出结果
        print()
        print("=" * 100)
        print("✅ 查询执行完成")
        print("=" * 100)
        print(f"执行耗时：{elapsed_time:.2f} 秒")
        print()
        
        # 检查结果
        if result:
            print("【结果摘要】")
            result_str = str(result)
            
            # 检查关键标记
            checks = {
                "[DATA] 标记": "[DATA]" in result_str,
                "市盈率": "市盈率" in result_str or "PE" in result_str,
                "股息率": "股息率" in result_str or "分红" in result_str,
                "财务数据": "财务" in result_str or "利润" in result_str,
                "投资建议": "建议" in result_str or "推荐" in result_str,
            }
            
            for check_name, check_result in checks.items():
                symbol = "✅" if check_result else "⚠️"
                print(f"  {symbol} {check_name}")
            
            print()
            print("【完整输出】")
            print("-" * 100)
            print(result[:500] + ("..." if len(result) > 500 else ""))
            print("-" * 100)
        else:
            print("⚠️ 查询返回空结果")
        
        print()
        print("=" * 100)
        print("📊 测试统计")
        print("=" * 100)
        
        # 工具调用统计
        if hasattr(tool_monitor, 'get_tool_graph_stats'):
            try:
                stats = tool_monitor.get_tool_graph_stats()
                print(f"工具调用图统计：{stats}")
            except:
                pass
        
        # 记忆系统统计
        mem_stats = memory_system.get_stats()
        print(f"长期记忆：{mem_stats['long_term_count']} 条")
        print(f"短期记忆：{mem_stats['short_term_count']} 条")
        if 'causal_graph' in mem_stats:
            print(f"因果图节点：{mem_stats['causal_graph'].get('total_nodes', 0)}")
        
        print()
        print("=" * 100)
        print("✅ 测试执行成功！")
        print("=" * 100)
        
        return True
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        print()
        print("=" * 100)
        print(f"❌ 测试执行失败")
        print("=" * 100)
        print(f"错误信息：{str(e)}")
        print(f"耗时：{elapsed_time:.2f} 秒")
        print()
        
        import traceback
        print("完整堆栈跟踪：")
        traceback.print_exc()
        
        return False

if __name__ == "__main__":
    print("⚠️  注意：此脚本需要 async 运行环境")
    print("如果使用 Jupyter 或异步环境，请调用：await run_test()\n")
    
    try:
        # 尝试异步运行
        success = asyncio.run(run_test())
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"运行失败：{e}")
        sys.exit(1)
