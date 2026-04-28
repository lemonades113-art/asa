#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pandas as pd

# 模拟 TushareDataHelper 的核心功能
def normalize_numeric(df, columns):
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

# 测试
print("\n=== 类型转换测试 ===")

# 原始数据（模拟 Tushare 返回的数据）
test_df = pd.DataFrame({
    'report_type': ['1', '1', '2'],
    'revenue': [100, 200, 300],
    'n_income': [10, 20, 30]
})

print("原始数据:")
print("  report_type 类型:", test_df['report_type'].dtype)
print("  report_type 值:", test_df['report_type'].tolist())

# 转换后
result_df = normalize_numeric(test_df, ['report_type'])

print("\n转换后:")
print("  report_type 类型:", result_df['report_type'].dtype)
print("  report_type 值:", result_df['report_type'].tolist())

# 测试数值比较
filtered = result_df[result_df['report_type'] == 1]
print("\n筛选 report_type == 1:")
print("  结果行数:", len(filtered))

if len(filtered) > 0:
    print("[SUCCESS] 类型转换成功！")
else:
    print("[FAIL] 类型转换失败！")
