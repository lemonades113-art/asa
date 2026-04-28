#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tushare 数据验证脚本
验证股票数据的准确性和真实性
"""

import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def validate_tushare_data(ts_code: str, start_date: str, end_date: str) -> dict:
    """
    完整的数据验证框架
    
    参数:
        ts_code: 股票代码，如 '600036.SH'
        start_date: 开始日期，格式 '20251103'
        end_date: 结束日期，格式 '20251128'
    
    返回:
        验证结果字典
    """
    print("\n" + "="*80)
    print(f"【数据验证】{ts_code} ({start_date} ~ {end_date})")
    print("="*80 + "\n")
    
    pro = ts.pro_api()
    
    # ============================================================================
    # 第 1 步：数据获取
    # ============================================================================
    print("【步骤 1】获取原始数据...")
    try:
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        print(f"✅ 成功获取 {len(df)} 条记录")
    except Exception as e:
        print(f"❌ 获取失败: {e}")
        return {"status": "failed", "error": str(e)}
    
    if df.empty:
        print("❌ 数据为空")
        return {"status": "failed", "error": "数据为空"}
    
    print(f"   列名: {list(df.columns)}")
    
    # ============================================================================
    # 第 2 步：逻辑验证（数据内部一致性）
    # ============================================================================
    print("\n【步骤 2】逻辑验证（内部一致性）...\n")
    
    validation_results = {
        "price_logic": [],      # 价格逻辑检查
        "return_calculation": [],  # 涨跌幅计算
        "volume_validation": [],   # 成交量检查
        "date_validation": [],     # 日期有效性
        "extreme_values": []       # 极端值检查
    }
    
    # 2.1 价格逻辑：high >= close >= low >= 0
    print("2.1 价格逻辑检查（high >= close >= low >= 0）")
    price_issues = []
    for idx, row in df.iterrows():
        high, close, low, open_price = row['high'], row['close'], row['low'], row['open']
        
        if not (high >= close):
            price_issues.append(f"  ❌ 行 {idx}: 最高价({high}) < 收盘价({close})")
        if not (close >= low):
            price_issues.append(f"  ❌ 行 {idx}: 收盘价({close}) < 最低价({low})")
        if not (high >= open_price >= 0):
            price_issues.append(f"  ❌ 行 {idx}: 开盘价({open_price}) 异常")
        if not (low >= 0):
            price_issues.append(f"  ❌ 行 {idx}: 最低价({low}) < 0")
    
    if price_issues:
        validation_results["price_logic"] = price_issues
        for issue in price_issues[:3]:  # 只显示前 3 个
            print(issue)
        if len(price_issues) > 3:
            print(f"  ... 还有 {len(price_issues)-3} 个问题")
    else:
        print("  ✅ 所有价格逻辑正确")
    
    validation_results["price_logic"] = "✅ 通过" if not price_issues else f"❌ {len(price_issues)} 个错误"
    
    # 2.2 涨跌幅计算：(close - pre_close) / pre_close * 100 ≈ pct_chg
    print("\n2.2 涨跌幅计算检查 ((close-pre_close)/pre_close*100 ≈ pct_chg)")
    pct_issues = []
    for idx, row in df.iterrows():
        if row['pre_close'] <= 0:
            continue
        # ✅ 正确的公式：相对于前一日收盘价
        calculated_pct = (row['close'] - row['pre_close']) / row['pre_close'] * 100
        difference = abs(calculated_pct - row['pct_chg'])
        
        # 允许 0.01% 的误差（四舍五入）
        if difference > 0.01:
            pct_issues.append(
                f"  ❌ 行 {idx}: 计算={calculated_pct:.4f}%, "
                f"实际={row['pct_chg']:.4f}%, 差异={difference:.4f}%"
            )
    
    if pct_issues:
        for issue in pct_issues[:3]:
            print(issue)
        if len(pct_issues) > 3:
            print(f"  ... 还有 {len(pct_issues)-3} 个问题")
    else:
        print("  ✅ 所有涨跌幅计算正确")
    
    validation_results["return_calculation"] = "✅ 通过" if not pct_issues else f"❌ {len(pct_issues)} 个错误"
    
    # 2.3 成交量和成交额
    print("\n2.3 成交量检查 (vol > 0 且合理)")
    vol_issues = []
    vol_stats = df['vol'].describe()
    
    if (df['vol'] <= 0).any():
        zero_vol_count = (df['vol'] <= 0).sum()
        vol_issues.append(f"  ⚠️  {zero_vol_count} 个交易日成交量为 0（可能是停牌日期）")
    
    # 检查极端的成交量变化
    df_with_vol = df[df['vol'] > 0].copy()
    if len(df_with_vol) > 1:
        vol_changes = df_with_vol['vol'].pct_change()
        extreme_vol_changes = vol_changes[abs(vol_changes) > 5]  # 成交量变化 > 500%
        
        if len(extreme_vol_changes) > 0:
            vol_issues.append(f"  ⚠️  {len(extreme_vol_changes)} 个交易日成交量变化 > 500%（正常异常活跃）")
    
    print(f"  成交量统计：")
    print(f"    - 平均: {vol_stats['mean']:.0f}")
    print(f"    - 最小: {vol_stats['min']:.0f}")
    print(f"    - 最大: {vol_stats['max']:.0f}")
    
    if vol_issues:
        for issue in vol_issues:
            print(issue)
    else:
        print("  ✅ 成交量数据合理")
    
    validation_results["volume_validation"] = "✅ 通过" if not vol_issues else f"⚠️  {len(vol_issues)} 个警告"
    
    # 2.4 日期有效性
    print("\n2.4 日期有效性检查")
    try:
        df['trade_date_dt'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        df_sorted = df.sort_values('trade_date_dt')
        
        # 检查重复日期
        duplicate_dates = df_sorted['trade_date'].duplicated().sum()
        if duplicate_dates > 0:
            print(f"  ❌ {duplicate_dates} 个重复的交易日期")
            validation_results["date_validation"] = f"❌ {duplicate_dates} 个重复日期"
        else:
            print(f"  ✅ 日期无重复，共 {len(df)} 个交易日")
            validation_results["date_validation"] = "✅ 通过"
    except Exception as e:
        print(f"  ❌ 日期格式错误: {e}")
        validation_results["date_validation"] = f"❌ 日期格式错误"
    
    # 2.5 极端值检查
    print("\n2.5 极端值检查（是否存在异常数据）")
    extreme_issues = []
    
    # 检查涨跌幅 > 20%（一般认为是极端情况）
    extreme_pct = df[abs(df['pct_chg']) > 20]
    if len(extreme_pct) > 0:
        for idx, row in extreme_pct.iterrows():
            print(f"  ⚠️  {row['trade_date']}: 涨跌幅 {row['pct_chg']:.2f}%（极端波动，可能是分红除权等）")
            extreme_issues.append(row['trade_date'])
    
    # 检查价格跳空 > 5%
    if len(df_sorted) > 1:
        df_sorted['price_gap'] = df_sorted['open'] / df_sorted['close'].shift(1) - 1
        gaps = df_sorted[abs(df_sorted['price_gap']) > 0.05]
        if len(gaps) > 0:
            for idx, row in gaps.iterrows():
                print(f"  ⚠️  {row['trade_date']}: 开盘跳空 {row['price_gap']*100:.2f}%")
    
    if not extreme_issues:
        print("  ✅ 无明显极端值")
        validation_results["extreme_values"] = "✅ 通过"
    else:
        validation_results["extreme_values"] = f"⚠️  {len(extreme_issues)} 个极端值"
    
    # ============================================================================
    # 第 3 步：统计摘要
    # ============================================================================
    print("\n【步骤 3】统计摘要\n")
    
    print("关键指标统计：")
    print(f"  交易日数:      {len(df)}")
    print(f"  平均收盘价:    {df['close'].mean():.4f}")
    print(f"  最高价:        {df['high'].max():.4f}")
    print(f"  最低价:        {df['low'].min():.4f}")
    print(f"  平均涨跌幅:    {df['pct_chg'].mean():.4f}%")
    print(f"  最大单日涨幅:  {df['pct_chg'].max():.4f}% ({df.loc[df['pct_chg'].idxmax(), 'trade_date']})")
    print(f"  最大单日跌幅:  {df['pct_chg'].min():.4f}% ({df.loc[df['pct_chg'].idxmin(), 'trade_date']})")
    print(f"  收益率:        {(df.iloc[-1]['close'] / df.iloc[0]['close'] - 1) * 100:.4f}%")
    
    # ============================================================================
    # 第 4 步：验证结论
    # ============================================================================
    print("\n【步骤 4】验证结论\n")
    
    total_issues = sum(1 for v in validation_results.values() if "❌" in str(v))
    total_warnings = sum(1 for v in validation_results.values() if "⚠️" in str(v))
    
    print("验证结果汇总：")
    for name, result in validation_results.items():
        print(f"  {name:25} {result}")
    
    print("\n" + "="*80)
    if total_issues == 0 and total_warnings == 0:
        print("✅ 【结论】数据完全有效，可以放心使用")
        status = "valid"
    elif total_issues == 0:
        print(f"⚠️  【结论】数据基本有效，但有 {total_warnings} 个警告（通常无碍）")
        status = "valid_with_warnings"
    else:
        print(f"❌ 【结论】数据存在 {total_issues} 个问题，建议核实")
        status = "invalid"
    print("="*80 + "\n")
    
    return {
        "status": status,
        "total_records": len(df),
        "validation_results": validation_results,
        "summary": df[['trade_date', 'open', 'high', 'low', 'close', 'vol', 'pct_chg']].head(10)
    }


# ============================================================================
# 使用示例
# ============================================================================
if __name__ == "__main__":
    # 验证招商银行的数据
    result = validate_tushare_data(
        ts_code='600036.SH',
        start_date='20251103',
        end_date='20251128'
    )
    
    print("\n【原始数据样本】")
    print(result['summary'])
    
    # 对比验证：你也可以手工验证某个关键日期
    print("\n【手工验证建议】")
    print("建议对比以下日期的数据：")
    print("1. 访问：http://www.sse.com.cn（上交所官网）")
    print("2. 搜索招商银行，查看历史行情")
    print("3. 比较 2025-11-04 的涨幅是否为 2.9194%")
    print("4. 比较最高价和最低价")
