"""
熔断器功能测试 - 验证执行超时保护
"""
import time
import sys

print("="*70)
print("熔断器功能测试")
print("="*70)

# 测试1：正常执行
print("\n[测试1] 正常代码执行（应在1秒内完成）")
print("-" * 70)

from lib import StatefulPythonKernel

kernel = StatefulPythonKernel()

code_normal = """
import pandas as pd
df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})
print(df)
print("执行成功")
"""

start = time.time()
result = kernel.execute(code_normal, timeout=30)
elapsed = time.time() - start

print(f"耗时: {elapsed:.2f}秒")
print(f"结果: {result[:200]}...")
print(f"状态: {'✅ 通过' if '执行成功' in result else '❌ 失败'}")

# 测试2：死循环（熔断器应触发）
print("\n[测试2] 死循环代码（熔断器应在30秒后触发）")
print("-" * 70)

code_deadloop = """
import time
print("开始死循环...")
count = 0
while True:
    count += 1
    if count % 1000000 == 0:
        print(f"循环计数: {count}")
"""

start = time.time()
result = kernel.execute(code_deadloop, timeout=5)  # 5秒熔断，方便测试
elapsed = time.time() - start

print(f"耗时: {elapsed:.2f}秒")
print(f"结果: {result[:300]}...")
print(f"状态: {'✅ 熔断器触发' if '已强制终止' in result else '❌ 熔断器未触发'}")

# 测试3：长时间sleep（熔断器应触发）
print("\n[测试3] 长时间sleep（熔断器应在5秒后触发）")
print("-" * 70)

code_sleep = """
import time
print("开始sleep 60秒...")
time.sleep(60)
print("sleep结束")
"""

start = time.time()
result = kernel.execute(code_sleep, timeout=5)  # 5秒熔断
elapsed = time.time() - start

print(f"耗时: {elapsed:.2f}秒")
print(f"结果: {result[:300]}...")
print(f"状态: {'✅ 熔断器触发' if '已强制终止' in result else '❌ 熔断器未触发'}")

# 测试4：Tushare超时模拟
print("\n[测试4] Tushare超时模拟（熔断器应触发）")
print("-" * 70)

code_tushare_timeout = """
import time
print("模拟Tushare查询超时...")
# 模拟网络超时
time.sleep(100)
print("查询完成")
"""

start = time.time()
result = kernel.execute(code_tushare_timeout, timeout=5)
elapsed = time.time() - start

print(f"耗时: {elapsed:.2f}秒")
print(f"结果: {result[:300]}...")
print(f"状态: {'✅ 熔断器触发' if '已强制终止' in result else '❌ 熔断器未触发'}")

print("\n" + "="*70)
print("测试完成")
print("="*70)

# 统计
all_passed = (
    '执行成功' in kernel.execute(code_normal, timeout=30) and
    '已强制终止' in kernel.execute(code_deadloop, timeout=5) and
    '已强制终止' in kernel.execute(code_sleep, timeout=5) and
    '已强制终止' in kernel.execute(code_tushare_timeout, timeout=5)
)

print(f"\n总结果: {'✅ 全部通过' if all_passed else '❌ 部分失败'}")
