import re

# 读取日志文件
log_file = "分.markdown"

try:
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
except:
    with open(log_file, 'r', encoding='gbk') as f:
        content = f.read()

# 统计关键指标
print("=" * 60)
print("日志统计分析报告")
print("=" * 60)

# 1. 统计任务分解次数
task_decompose = re.findall(r'任务分解成功:', content)
print(f"\n1. 任务分解次数: {len(task_decompose)}")

# 2. 统计FINISH次数
finish_count = re.findall(r'\[Supervisor\] 决策: FINISH', content)
print(f"2. FINISH次数: {len(finish_count)}")

# 3. 统计ErrorHandler执行次数
error_handler = re.findall(r'\[ErrorHandler\]', content)
print(f"3. ErrorHandler执行次数: {len(error_handler)}")

# 4. 统计错误类型
code_error = re.findall(r'检测到错误类型: code_error', content)
network_error = re.findall(r'检测到错误类型: network_error', content)
auth_error = re.findall(r'检测到错误类型: auth_error', content)
print(f"4. 错误类型分布:")
print(f"   - code_error: {len(code_error)}")
print(f"   - network_error: {len(network_error)}")
print(f"   - auth_error: {len(auth_error)}")

# 5. 统计重试次数
retry_1 = re.findall(r'第1次重试', content)
retry_2 = re.findall(r'第2次重试', content)
retry_3 = re.findall(r'第3次重试', content)
print(f"5. 重试统计:")
print(f"   - 第1次重试: {len(retry_1)}")
print(f"   - 第2次重试: {len(retry_2)}")
print(f"   - 第3次重试: {len(retry_3)}")

# 6. 统计消息清洁
clean_msg = re.findall(r'清洁消息数：(\d+)', content)
print(f"6. 消息清洁次数: {len(clean_msg)}")
if clean_msg:
    print(f"   - 清洁后消息数: {', '.join(set(clean_msg))}")

# 7. 统计缓存保存
cache_save = re.findall(r'\[ToolCache\] 保存缓存', content)
print(f"7. 缓存保存次数: {len(cache_save)}")

# 8. 统计元数据标签
date_tag = re.findall(r'\[DATE\]:', content)
source_tag = re.findall(r'\[SOURCE\]:', content)
meta_tag = re.findall(r'\[META\]:', content)
data_tag = re.findall(r'\[DATA\]:', content)
print(f"8. 元数据标签统计:")
print(f"   - [DATE]: {len(date_tag)}")
print(f"   - [SOURCE]: {len(source_tag)}")
print(f"   - [META]: {len(meta_tag)}")
print(f"   - [DATA]: {len(data_tag)}")

# 9. 统计Reviewer生成报告
reviewer_report = re.findall(r'\[Reviewer\] 报告撰写成功', content)
print(f"9. Reviewer报告生成次数: {len(reviewer_report)}")

# 10. 提取所有用户查询
queries = re.findall(r'查询(.+?)(?:的|，|。|\n)', content[:3000])  # 只看前3000字符
print(f"\n10. 识别到的用户查询示例:")
for i, q in enumerate(queries[:5], 1):
    print(f"    {i}. {q}")

print("\n" + "=" * 60)
print("分析完成")
print("=" * 60)
