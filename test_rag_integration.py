"""
RAG集成测试 - 验证数据为空时自动查询接口文档
"""
import json
import time
from multi_agent import run_asa_agent

# 设计需要查询接口文档的问题
TEST_QUERIES = [
    {
        "id": "Q001",
        "query": "查询贵州茅台(600519.SH)2024年12月31日的龙虎榜机构明细",
        "expected_interface": "top_inst",
        "description": "龙虎榜机构明细接口 - 需要trade_date参数"
    },
    {
        "id": "Q002",
        "query": "查询最近一个月融资融券标的有哪些",
        "expected_interface": "margin_secs",
        "description": "融资融券标的接口 - 查询可融券的股票"
    },
    {
        "id": "Q003",
        "query": "查询宁德时代(300750.SZ)的财务指标数据",
        "expected_interface": "fina_indicator",
        "description": "财务指标数据接口 - 需要知道参数格式"
    },
    {
        "id": "Q004",
        "query": "查询比亚迪(002594.SZ)前十大股东",
        "expected_interface": "top10_holders",
        "description": "前十大股东接口 - 可能需要知道字段含义"
    },
    {
        "id": "Q005",
        "query": "查询海康威视(002415.SZ)的主营业务构成",
        "expected_interface": "main_bsic",
        "description": "主营业务构成接口 - 较少用的接口"
    }
]

def run_test():
    """运行RAG集成测试"""
    results = []

    for test in TEST_QUERIES:
        print(f"\n{'='*60}")
        print(f"测试: {test['id']} - {test['description']}")
        print(f"问题: {test['query']}")
        print(f"{'='*60}")

        try:
            start_time = time.time()
            result = run_asa_agent(test['query'], verbose=True)
            duration = time.time() - start_time

            # 解析结果
            answer = result.get("answer", "")
            logs = result.get("logs", [])

            # 检查是否触发了RAG
            rag_triggered = any(
                "RAG" in log or "检索" in log or "search_tushare_docs" in str(logs)
                for log in logs
            )

            # 检查Tushare调用
            tushare_calls = [log for log in logs if "tushare" in str(log).lower() or "pro." in str(log)]

            test_result = {
                "id": test['id'],
                "query": test['query'],
                "expected_interface": test['expected_interface'],
                "duration_sec": round(duration, 2),
                "status": "success" if answer else "failed",
                "rag_triggered": rag_triggered,
                "tushare_calls": len(tushare_calls),
                "answer_preview": answer[:500] if answer else "无答案",
                "logs": logs[:10]  # 只保留前10条日志
            }

            print(f"\n结果:")
            print(f"  状态: {test_result['status']}")
            print(f"  耗时: {test_result['duration_sec']}秒")
            print(f"  RAG触发: {test_result['rag_triggered']}")
            print(f"  Tushare调用次数: {test_result['tushare_calls']}")

            results.append(test_result)

        except Exception as e:
            print(f"错误: {e}")
            results.append({
                "id": test['id'],
                "query": test['query'],
                "error": str(e),
                "status": "error"
            })

    # 保存结果
    output_file = f"rag_test_result_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"测试完成，结果已保存到: {output_file}")
    print(f"{'='*60}")

    # 统计
    success_count = sum(1 for r in results if r.get('status') == 'success')
    rag_count = sum(1 for r in results if r.get('rag_triggered', False))

    print(f"\n统计:")
    print(f"  成功: {success_count}/{len(results)}")
    print(f"  RAG触发次数: {rag_count}")

    return results

if __name__ == "__main__":
    run_test()
