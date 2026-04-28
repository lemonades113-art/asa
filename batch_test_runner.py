
import os
import json
import asyncio
import datetime
import uuid
import sys
import traceback
import io

# 1. 修复 huggingface_hub 版本兼容性问题 (HfFolder 缺失)
# 必须在任何其他导入（尤其是 gradio）之前执行
try:
    import huggingface_hub
    if not hasattr(huggingface_hub, "HfFolder"):
        class MockHfFolder:
            @staticmethod
            def get_token(): return None
            @staticmethod
            def save_token(t): pass
            @staticmethod
            def delete_token(): pass
        huggingface_hub.HfFolder = MockHfFolder
        print("[Fix] 已 Mock 缺失的 huggingface_hub.HfFolder")
except ImportError:
    pass

# 2. 强制使用 UTF-8 编码并支持写日志到文件
# 在 Windows 上使用 utf-8-sig (带BOM) 确保汉字被正确识别
log_file_path = r"D:\HuaweiMoveData\Users\HUAWEI\Desktop\简历\三个\ASA two\evaluation_results\full_run.log"
log_dir = os.path.dirname(log_file_path)
if not os.path.exists(log_dir):
    os.makedirs(log_dir, exist_ok=True)

class Tee:
    def __init__(self, filename):
        self.file = open(filename, "w", encoding="utf-8-sig")
        self.stdout = sys.stdout

    def write(self, data):
        self.file.write(data)
        try:
            # 尝试写入控制台，如果编码不支持则忽略或降级
            self.stdout.write(data)
        except UnicodeEncodeError:
            self.stdout.write(data.encode('ascii', 'ignore').decode('ascii'))
        self.file.flush()

    def flush(self):
        self.file.flush()
        self.stdout.flush()

if sys.platform == "win32":
    sys.stdout = Tee(log_file_path)
    sys.stderr = sys.stdout

# 3. 强制禁用沙箱，切回本地内核
os.environ["USE_ASA_SANDBOX"] = "false"

# 4. 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from multi_agent import multi_agent_app, get_initial_state
from langchain_core.messages import HumanMessage

# --- 50条压测提示词集 ---
# 【P0评估】预期技能映射 - 用于计算工具选择准确率
EXPECTED_SKILLS = {
    # A. 分红专家 (Dividend Expert)
    "计算中国平安过去三年的累计分红金额，并计算当前的股息率是否超过5%。": ["dividend_expert"],
    "对比招商银行和工商银行的股息率（dv_ttm），注意单位转换问题。": ["dividend_expert"],
    "查询格力电器最新的分红方案，确认是否已经'实施'，排除未实施方案。": ["dividend_expert"],
    "分析长江电力的分红稳定性，列出过去5年的每股派息金额。": ["dividend_expert"],
    "计算万科A的分红支付率（股利/净利润），注意财务单位一致性。": ["dividend_expert", "finance_audit"],
    "如果我想获得4%的股息收益，现在买入中国建筑合适吗？请分析其股息率。": ["dividend_expert"],
    "对比中信证券和华泰证券的分红慷慨度。": ["dividend_expert"],
    "查询并计算红利指数前三大权重股的平均股息率。": ["dividend_expert"],
    "分析贵州茅台历史上的送转股记录，对股价复权有何影响？": ["dividend_expert"],
    "找出目前房地产板块中，股息率最高的前三只股票。": ["dividend_expert", "market_expert"],

    # B. 市场专家 (Market Expert)
    "查询腾讯控股(00700)今天的表现，并计算其当前PE。": ["market_expert"],
    "对比沪深300 ETF(510300)和恒生电子的估值指标，注意ETF应查看PB而非PE。": ["market_expert"],
    "查询美团-W(03690)的最新成交额，单位换算成人民币。": ["market_expert"],
    "分析中芯国际(00981)在港股市场的估值水平，对比 A 股中芯国际。": ["market_expert"],
    "如果一只股票停牌了，你能查到它最后交易日的数据吗？请以 ST 泰禾为例。": ["market_expert"],
    "查询并对比纳指ETF和标普500ETF的近期涨幅。": ["market_expert"],
    "恒生指数目前的成份股中，市值最大的是哪三家？请带后缀查询。": ["market_expert"],
    "分析中概互联ETF(513050)的折溢价情况。": ["market_expert"],
    "对比小米集团和联想集团的研发投入占比。": ["market_expert", "finance_audit"],
    "查询并展示近期新上市的港股表现。": ["market_expert"],

    # C. 财务审计 (Finance Audit)
    "对比贵州茅台和五粮液2024年最新的营业收入，单位统一用亿元。": ["finance_audit"],
    "分析宁德时代过去三年的研发费用走势，并画图展示。": ["finance_audit", "charting_expert"],
    "查询比亚迪最新的资产负债率，并说明其财务稳健性。": ["finance_audit"],
    "提取隆基绿能最近一份年报中的净利润数据，注意排除单季度波动的干扰。": ["finance_audit"],
    "由于现在是4月份，请查询一季报还没出时，各大银行去年的年报净利润。": ["finance_audit"],
    "分析京东方的毛利率变化，对比同行业的深天马。": ["finance_audit"],
    "查询药明康德的商誉占总资产比例，是否存在减值风险？": ["finance_audit"],
    "对比顺丰控股和圆通速递的单位邮件成本或毛利。": ["finance_audit"],
    "提取海尔智家海外收入占比，分析其全球化布局。": ["finance_audit"],
    "查询科大讯飞的政府补贴占净利润比重，分析其盈利质量。": ["finance_audit"],

    # D. 综合与绘图 (Charting & Mixed)
    "画出东方财富近一年的股价走势图，并标注出最高点日期。": ["charting_expert"],
    "对比'茅五泸'三家公司的市盈率走势，画在一张图里。": ["charting_expert", "market_expert"],
    "分析半导体板块的整体估值走势，选择前五大龙头画出柱状图。": ["charting_expert", "market_expert"],
    "查询并绘图展示科创50指数近三个月的波动情况。": ["charting_expert"],
    "对比新能源汽车三强（蔚小理）的月度交付量走势图。": ["charting_expert"],
    "获取中石油和中石化的分红对比，并用饼图展示其利润分配。": ["charting_expert", "dividend_expert"],
    "查询最近一周北向资金的流入情况，并画出趋势图。": ["charting_expert"],
    "分析近期热门 AI 概念股的成交量变化，画出成交量图。": ["charting_expert"],
    "对比不同券商对中信证券的目标价预测，并画出分布图。": ["charting_expert"],
    "查询并可视化展示过去 10 年上证指数在 2 月份的平均表现。": ["charting_expert"],
    
    # E. 极端/异常边界测试
    "查询一只根本不存在的股票代码 999999.SH，看系统如何报错。": [],
    "如果你在获取数据时遇到网络超时，你会尝试重试吗？请演示查询平安银行。": [],
    "尝试同时查询 10 只股票的详细财务指标，测试系统的并发处理能力。": ["finance_audit"],
    "在财报发布空窗期，查询某小众科创板公司的'实时'净利润，看如何处理空值。": ["finance_audit"],
    "反复修改你的查询需求：先看茅台，再改看五粮液，最后对比两者。测试上下文记忆。": ["market_expert"],
}

TEST_PROMPTS = list(EXPECTED_SKILLS.keys())

async def run_test(prompt, sem):
    async with sem:
        test_id = str(uuid.uuid4())[:8]
        print(f"\n[START] Test {test_id}: {prompt[:50]}...")
        
        # 【P0评估】Token 消耗统计
        token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "node_tokens": {}  # 各节点 Token 消耗
        }
        
        # 【监控指标】性能监控
        perf_metrics = {
            "start_time": datetime.datetime.now(),
            "node_latencies": {},  # 各节点延迟
            "tool_calls": [],      # 工具调用记录
            "api_errors": []       # API 错误记录
        }
        
        result = {
            "test_id": test_id,
            "prompt": prompt,
            "timestamp": datetime.datetime.now().isoformat(),
            "steps": [],
            "final_answer": "",
            "skills_used": [],
            "success": False,
            # 【P0评估】新增字段
            "expected_skills": EXPECTED_SKILLS.get(prompt, []),
            "skill_selection_accuracy": None,  # 工具选择准确率
            "token_stats": token_stats,
            "recursion_error": False,
            "error_type": None,
            # 【监控指标】新增字段
            "perf_metrics": perf_metrics,
            "total_latency_ms": 0
        }
        
        try:
            # 提高递归上限到 100（因为添加了总重试限制，足够用）
            config = {"configurable": {"thread_id": test_id}, "recursion_limit": 100}
            initial_state = get_initial_state()
            initial_state["messages"] = [HumanMessage(content=prompt)]
            
            async for event in multi_agent_app.astream(initial_state, config, stream_mode="updates"):
                node_start_time = datetime.datetime.now()  # 【监控指标】节点开始时间
                
                for node_name, output in event.items():
                    step_info = {"node": node_name}
                    
                    # 【监控指标】计算节点延迟
                    node_end_time = datetime.datetime.now()
                    node_latency = (node_end_time - node_start_time).total_seconds() * 1000  # ms
                    perf_metrics["node_latencies"][node_name] = perf_metrics["node_latencies"].get(node_name, 0) + node_latency
                    
                    if "messages" in output and output["messages"]:
                        last_msg = output["messages"][-1]
                        content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
                        step_info["content"] = content
                        
                        # 【P0评估】统计 Token 消耗（按字符数估算）
                        content_len = len(content) if content else 0
                        token_stats["output_tokens"] += content_len // 4  # 粗略估算：4字符 ≈ 1 token
                        token_stats["node_tokens"][node_name] = token_stats["node_tokens"].get(node_name, 0) + content_len // 4
                        
                        # 【监控指标】记录工具调用
                        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
                            step_info["tool_calls"] = last_msg.tool_calls
                            for tc in last_msg.tool_calls:
                                perf_metrics["tool_calls"].append({
                                    "node": node_name,
                                    "tool": tc.get("name", "unknown"),
                                    "timestamp": datetime.datetime.now().isoformat()
                                })
                    
                    if "skills_loaded" in output:
                        result["skills_used"].extend(output["skills_loaded"])
                    
                    result["steps"].append(step_info)
                    
                    if node_name == "Reviewer" or node_name == "FINISH":
                        result["final_answer"] = step_info.get("content", "")
            
            result["success"] = True
            
            # 【P0评估】计算工具选择准确率
            expected = set(result["expected_skills"])
            actual = set(result["skills_used"])
            if expected:
                # 准确率 = 正确选择的技能数 / 应选技能数
                correct_selections = len(expected & actual)
                # 也考虑多选的情况：如果选了额外的技能，适当惩罚
                extra_selections = len(actual - expected)
                result["skill_selection_accuracy"] = max(0, correct_selections - 0.5 * extra_selections) / len(expected)
            else:
                # 如果预期不需要技能，实际也没选，则准确率为 1
                result["skill_selection_accuracy"] = 1.0 if not actual else 0.0
            
            # 【P0评估】计算总 Token 数
            token_stats["total_tokens"] = token_stats["input_tokens"] + token_stats["output_tokens"]
            
            # 【监控指标】计算总延迟
            total_end_time = datetime.datetime.now()
            result["total_latency_ms"] = (total_end_time - perf_metrics["start_time"]).total_seconds() * 1000
            
            print(f"[SUCCESS] Test {test_id} completed. Skills: {result['skills_used']}, Accuracy: {result['skill_selection_accuracy']:.2f}, Latency: {result['total_latency_ms']:.0f}ms")
            
        except Exception as e:
            error_str = str(e)
            result["error"] = error_str
            result["traceback"] = traceback.format_exc()
            
            # 【P0评估】错误分类
            if "Recursion limit" in error_str:
                result["recursion_error"] = True
                result["error_type"] = "recursion_limit"
            elif "timeout" in error_str.lower():
                result["error_type"] = "timeout"
            elif "api" in error_str.lower() or "rate" in error_str.lower():
                result["error_type"] = "api_error"
            else:
                result["error_type"] = "other"
            
            print(f"[ERROR] Test {test_id} failed: {error_str[:100]}")
            
        return result

async def main():
    print("=== ASA 潜力压测执行脚本 ===")
    print(f"待测 Prompt 总数: {len(TEST_PROMPTS)}")
    
    # 准备输出文件
    output_dir = r"D:\HuaweiMoveData\Users\HUAWEI\Desktop\简历\三个\ASA two\evaluation_results"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"batch_run_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
    
    # 限制并发数为 2
    sem = asyncio.Semaphore(2)
    
    # 使用 as_completed 或手动管理，实现增量写入
    tasks = [run_test(p, sem) for p in TEST_PROMPTS]
    
    # 【P0评估】统计变量
    success_count = 0
    skill_hit_count = 0
    total = len(TEST_PROMPTS)
    skill_accuracy_sum = 0.0
    skill_accuracy_count = 0
    total_tokens = 0
    recursion_error_count = 0
    error_type_counts = {}
    
    # 【监控指标】统计变量
    total_latency_ms = 0
    latency_list = []
    tool_call_count = 0
    node_latency_accumulator = {}
    
    print(f"结果将增量保存至: {output_file}")
    
    with open(output_file, "a", encoding="utf-8") as f:
        for coro in asyncio.as_completed(tasks):
            result = await coro
            # 立即写入文件
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
            f.flush() # 强制刷入磁盘
            
            # 【P0评估】累加统计
            if result["success"]: 
                success_count += 1
            if result["skills_used"]: 
                skill_hit_count += 1
            if result.get("skill_selection_accuracy") is not None:
                skill_accuracy_sum += result["skill_selection_accuracy"]
                skill_accuracy_count += 1
            if result.get("token_stats"):
                total_tokens += result["token_stats"].get("total_tokens", 0)
            if result.get("recursion_error"):
                recursion_error_count += 1
            if result.get("error_type"):
                error_type_counts[result["error_type"]] = error_type_counts.get(result["error_type"], 0) + 1
            
            # 【监控指标】累加统计
            if result.get("total_latency_ms"):
                total_latency_ms += result["total_latency_ms"]
                latency_list.append(result["total_latency_ms"])
            if result.get("perf_metrics"):
                tool_call_count += len(result["perf_metrics"].get("tool_calls", []))
                # 累加各节点延迟
                for node, latency in result["perf_metrics"].get("node_latencies", {}).items():
                    node_latency_accumulator[node] = node_latency_accumulator.get(node, 0) + latency
            
            print(f"[PROGRESS] {success_count + (total - len(tasks))}/{total} completed.")

    # 【P0评估】输出汇总报告
    print(f"\n{'='*60}")
    print("=== ASA 压测评估报告 (P0 指标) ===")
    print(f"{'='*60}")
    print(f"📊 基础指标:")
    print(f"   总测试数: {total}")
    print(f"   成功率: {success_count}/{total} ({success_count/total*100:.1f}%)")
    print(f"   技能命中率: {skill_hit_count}/{total} ({skill_hit_count/total*100:.1f}%)")
    
    print(f"\n🎯 工具选择准确率:")
    if skill_accuracy_count > 0:
        avg_accuracy = skill_accuracy_sum / skill_accuracy_count
        print(f"   平均准确率: {avg_accuracy:.2%}")
        print(f"   评估样本数: {skill_accuracy_count}")
    else:
        print(f"   暂无数据")
    
    print(f"\n📝 Token 消耗:")
    print(f"   总 Token 数: {total_tokens:,}")
    print(f"   平均每测试: {total_tokens/total:,.0f} tokens")
    
    print(f"\n⚠️  错误分析:")
    print(f"   递归超限: {recursion_error_count} ({recursion_error_count/total*100:.1f}%)")
    for error_type, count in error_type_counts.items():
        print(f"   {error_type}: {count}")
    
    # 【监控指标】输出性能报告
    print(f"\n⚡ 性能监控:")
    if latency_list:
        avg_latency = total_latency_ms / len(latency_list)
        max_latency = max(latency_list)
        min_latency = min(latency_list)
        p95_latency = sorted(latency_list)[int(len(latency_list) * 0.95)]
        print(f"   平均延迟: {avg_latency:.0f}ms")
        print(f"   P95 延迟: {p95_latency:.0f}ms")
        print(f"   最大延迟: {max_latency:.0f}ms")
        print(f"   最小延迟: {min_latency:.0f}ms")
    print(f"   总工具调用: {tool_call_count}")
    print(f"   平均每测试工具调用: {tool_call_count/total:.1f}")
    
    # 【监控指标】各节点延迟分布
    if node_latency_accumulator:
        print(f"\n📊 各节点延迟分布:")
        for node, total_node_latency in sorted(node_latency_accumulator.items(), key=lambda x: x[1], reverse=True):
            avg_node_latency = total_node_latency / total
            print(f"   {node}: {avg_node_latency:.0f}ms (总计: {total_node_latency:.0f}ms)")
    
    # 【定位策略】故障快速定位指南
    print(f"\n🔍 故障定位指南:")
    if recursion_error_count > 0:
        print(f"   → 递归超限: 检查 ErrorHandler 重试限制 (当前限制已优化)")
    if error_type_counts.get("api_error", 0) > 0:
        print(f"   → API 限流: 考虑降低并发数 (当前 sem=2)")
    if skill_accuracy_count > 0 and (skill_accuracy_sum / skill_accuracy_count) < 0.8:
        print(f"   → 工具选择准确率低: 优化 Supervisor Prompt 触发规则")
    if latency_list and max(latency_list) > 30000:
        print(f"   → 存在高延迟: 检查 Tushare API 响应时间")
    
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
