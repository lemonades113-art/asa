"""
Multi-Agent RAG测试 - 使用multi_agent.py中的Supervisor架构
"""
import sys
import time
import json

# 测试问题：需要查询较少用的接口
test_query = "查询贵州茅台(600519.SH)2024年12月31日的龙虎榜机构明细"

print("="*70)
print("Multi-Agent RAG集成测试")
print("="*70)
print(f"问题: {test_query}")
print(f"预期接口: top_inst (龙虎榜机构明细)")
print("="*70)

# 记录开始时间
start_time = time.time()

# 收集日志
logs = []

try:
    # 导入multi_agent
    print("\n[1/4] 导入multi_agent模块...")
    from multi_agent import multi_agent_app, MultiAgentState
    from langchain_core.messages import HumanMessage
    
    print("[2/4] 初始化状态...")
    # 初始化状态
    initial_state = {
        "messages": [HumanMessage(content=test_query)],
        "next": "Supervisor",
        "retry_count": 0,
        "user_profile": {},
        "execution_status": "pending",
        "last_sender": "User",
        "task_plan": None,
        "remaining_steps": [],
        "error_type": None,
        "network_retry_count": 0,
        "supervisor_retry": 0,
        "last_execution_data": {},
        "message_window_size": 15,
        "tool_call_count": 0,
        "reviewer_fail_count": 0
    }
    
    print("[3/4] 执行Multi-Agent工作流 (预计30-120秒)...\n")
    
    # 执行
    config = {"configurable": {"thread_id": f"rag_test_{int(time.time())}"}}
    
    # 流式执行以观察过程
    answer = ""
    for event in multi_agent_app.stream(initial_state, config, stream_mode="updates"):
        for node_name, node_output in event.items():
            # 记录节点执行
            log_msg = f"[Node] {node_name}"
            logs.append(log_msg)
            print(f"📍 执行节点: {node_name}")
            
            # 检查消息
            messages = node_output.get("messages", [])
            for msg in messages:
                content = str(msg.content) if hasattr(msg, 'content') else str(msg)
                
                # 检查RAG触发
                if "RAG" in content or "相关API文档" in content or "检索" in content:
                    print(f"✅ RAG已触发! 内容: {content[:200]}")
                    logs.append(f"[RAG] {content[:200]}")
                
                # 检查数据为空处理
                if "数据为空" in content or "P1" in content:
                    print(f"⚠️  数据为空处理: {content[:200]}")
                    logs.append(f"[DataEmpty] {content[:200]}")
                
                # 收集最终答案
                if node_name == "Reviewer" and content:
                    answer = content
                    print(f"💬 Reviewer输出: {content[:100]}...")
                
                # 检查Tushare调用
                if "tushare" in content.lower() or "pro." in content:
                    logs.append(f"[Tushare] {content[:100]}")
    
    # 计算耗时
    duration = time.time() - start_time
    
    print("\n" + "="*70)
    print("[4/4] 执行完成")
    print("="*70)
    
    # 检查结果
    rag_triggered = any("[RAG]" in log for log in logs)
    data_empty_handled = any("[DataEmpty]" in log for log in logs)
    tushare_calls = [log for log in logs if "[Tushare]" in log]
    
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
    
    print(f"\n📋 关键日志 (最后15条):")
    for log in logs[-15:]:
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
    
    output_file = f"multi_agent_rag_test_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 详细结果已保存: {output_file}")
    
except Exception as e:
    duration = time.time() - start_time
    print(f"\n❌ 错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
