#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pandas as pd
import tushare as ts
from lib import create_tushare_helper

print("\n" + "="*80)
print("TEST: Verify income() API type conversion fix")
print("="*80)

pro = ts.pro_api()
helper = create_tushare_helper(pro)

code = '002594.SZ'
start_date = '20220101'

print("\nGetting income data for {}...".format(code))
df = helper.get_income_safe(ts_code=code, start_date=start_date)

if df.empty:
    print("[ERROR] No data returned")
    exit(1)

print("[OK] Data rows: {}".format(len(df)))
print("[OK] Columns: {}".format(list(df.columns)))

if 'report_type' in df.columns:
    print("\n【report_type Check】")
    print("Data type: {}".format(df['report_type'].dtype))
    print("Unique values: {}".format(df['report_type'].unique()))
    
    try:
        df_filtered = df[df['report_type'] == 1]
        print("Filtering report_type == 1: {} records".format(len(df_filtered)))
        
        if len(df_filtered) > 0:
            print("[OK] PASS - Type conversion works!")
            df_sorted = df_filtered.sort_values('end_date', ascending=False)
            for idx, row in df_sorted.head(3).iterrows():
                print("  {} - revenue: {}, n_income: {}".format(
                    row['end_date'], 
                    row.get('revenue'), 
                    row.get('n_income')
                ))
            exit(0)
        else:
            print("[FAIL] No records with report_type == 1")
            exit(1)
    except Exception as e:
        print("[FAIL] Comparison failed: {}".format(e))
        exit(1)
else:
    print("[FAIL] report_type column not found")
    exit(1)
