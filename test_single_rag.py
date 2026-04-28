"""
单个问题RAG测试 - 验证数据为空时自动查询接口文档
"""
import sys
import time
import json

# 测试问题：需要查询较少用的接口
test_query = "查询贵州茅台(600519.SH)2024年12月31日的龙虎榜机构明细"

print("="*70)
print("RAG集成测试")
print("="*70)
print(f"问题: {test_query}")
print(f"预期接口: top_inst (龙虎榜机构明细)")
print("="*70)

# 记录开始时间
start_time = time.time()

# 收集日志
logs = []

try:
    # 导入并运行
    print("\n[1/4] 导入agent模块...")
    from agent import run_stream, initialize_state_with_default_profile
    
    print("[2/4] 开始执行查询...")
    print("[3/4] 等待ASA系统处理 (预计30-120秒)...\n")
    
    # 使用流式接口
    initial_state = initialize_state_with_default_profile()
    
    answer_parts = []
    for event in run_stream(test_query, initial_state=initial_state):
        event_type = event.get("type", "unknown")
        content = event.get("content", "")
        
        # 记录日志
        logs.append(f"[{event_type}] {content[:100]}")
        
        # 打印关键事件
        if event_type == "tool_call":
            print(f"🛠️  调用工具: {content}")
        elif event_type == "tool_result":
            print(f"📊 工具结果: {content[:200]}...")
            # 检查是否包含RAG相关信息
            if "RAG" in content or "检索" in content or "相关API文档" in content:
                print("✅ RAG已触发!")
        elif event_type == "response":
            answer_parts.append(content)
            print(f"💬 AI回复: {content[:100]}...")
        elif event_type == "error":
            print(f"❌ 错误: {content}")
    
    # 计算耗时
    duration = time.time() - start_time
    
    print("\n" + "="*70)
    print("[4/4] 执行完成")
    print("="*70)
    
    # 组装答案
    answer = "\n".join(answer_parts)
    
    # 检查RAG触发
    rag_triggered = any(
        "RAG" in str(log) or "检索" in str(log) or "相关API文档" in str(log)
        for log in logs
    )
    
    # 检查Tushare调用
    tushare_calls = [log for log in logs if "tushare" in str(log).lower() or "pro." in str(log)]
    
    # 检查是否有数据为空的处理
    data_empty_handled = any("数据为空" in str(log) or "P1" in str(log) for log in logs)
    
    print(f"\n📊 测试结果:")
    print(f"  总耗时: {duration:.2f}秒")
    print(f"  状态: {'✅ 成功' if answer else '❌ 失败'}")
    print(f"  RAG触发: {'✅ 是' if rag_triggered else '❌ 否'}")
    print(f"  数据空处理: {'✅ 是' if data_empty_handled else '❌ 否'}")
    print(f"  Tushare调用次数: {len(tushare_calls)}")
    
    print(f"\n📝 答案预览 (前500字):")
    print("-" * 70)
    print(answer[:500] if answer else "无答案")
    print("-" * 70)
    
    print(f"\n📋 关键日志 (最后10条):")
    for log in logs[-10:]:
        print(f"  {log}")
    
    # 保存详细结果
    output = {
        "query": test_query,
        "duration_sec": round(duration, 2),
        "status": "success" if answer else "failed",
        "rag_triggered": rag_triggered,
        "data_empty_handled": data_empty_handled,
        "tushare_calls": len(tushare_calls),
        "answer": answer,
        "logs": logs
    }
    
    output_file = f"single_rag_test_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 详细结果已保存: {output_file}")
    
except Exception as e:
    duration = time.time() - start_time
    print(f"\n❌ 错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
