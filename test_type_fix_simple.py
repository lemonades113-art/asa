#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pandas as pd
from lib import TushareDataHelper

print("\n" + "="*80)
print("TEST: Type conversion fix for report_type")
print("="*80)

# Test 1: Direct type conversion
print("\n【Test 1】Direct type conversion")
helper = TushareDataHelper(None)

test_df = pd.DataFrame({
    'report_type': ['1', '1', '2', '2'],
    'revenue': [100, 200, 300, 400],
    'n_income': [10, 20, 30, 40]
})

print("Original data:")
print("  report_type dtype: {}".format(test_df['report_type'].dtype))
print("  Values: {}".format(test_df['report_type'].tolist()))

result_df = helper.normalize_numeric(test_df, ['report_type'])

print("\nAfter conversion:")
print("  report_type dtype: {}".format(result_df['report_type'].dtype))
print("  Values: {}".format(result_df['report_type'].tolist()))

# Test 2: Numeric comparison
print("\n【Test 2】Numeric comparison")
try:
    filtered = result_df[result_df['report_type'] == 1]
    print("[OK] Comparison succeeded!")
    print("  Rows with report_type == 1: {}".format(len(filtered)))
    print("  Result:")
    for idx, row in filtered.iterrows():
        print("    revenue: {}, n_income: {}".format(row['revenue'], row['n_income']))
except Exception as e:
    print("[FAIL] Comparison failed: {}".format(e))
    exit(1)

# Test 3: List comprehension for multiple columns
print("\n【Test 3】Get column value from multiple candidates")
test_row = pd.Series({
    'n_income': 100,
    'net_profit': 99,
    'n_income_attr_p': 101,
    'other_col': 'test'
})

column_candidates = ['n_income', 'n_income_attr_p', 'net_profit']
value = helper.get_column_value(test_row, column_candidates)
print("Selected value from candidates {}: {}".format(column_candidates, value))

if value == 100:
    print("[OK] Correctly selected first available column")
else:
    print("[FAIL] Wrong value selected")
    exit(1)

print("\n" + "="*80)
print("[SUCCESS] All type conversion tests passed!")
print("="*80 + "\n")
#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pandas as pd
from lib import TushareDataHelper

print("\n" + "="*80)
print("TEST: Type conversion fix for report_type")
print("="*80)

# Test 1: Direct type conversion
print("\n【Test 1】Direct type conversion")
helper = TushareDataHelper(None)

test_df = pd.DataFrame({
    'report_type': ['1', '1', '2', '2'],
    'revenue': [100, 200, 300, 400],
    'n_income': [10, 20, 30, 40]
})

print("Original data:")
print("  report_type dtype: {}".format(test_df['report_type'].dtype))
print("  Values: {}".format(test_df['report_type'].tolist()))

result_df = helper.normalize_numeric(test_df, ['report_type'])

print("\nAfter conversion:")
print("  report_type dtype: {}".format(result_df['report_type'].dtype))
print("  Values: {}".format(result_df['report_type'].tolist()))

# Test 2: Numeric comparison
print("\n【Test 2】Numeric comparison")
try:
    filtered = result_df[result_df['report_type'] == 1]
    print("[OK] Comparison succeeded!")
    print("  Rows with report_type == 1: {}".format(len(filtered)))
    print("  Result:")
    for idx, row in filtered.iterrows():
        print("    revenue: {}, n_income: {}".format(row['revenue'], row['n_income']))
except Exception as e:
    print("[FAIL] Comparison failed: {}".format(e))
    exit(1)

# Test 3: List comprehension for multiple columns
print("\n【Test 3】Get column value from multiple candidates")
test_row = pd.Series({
    'n_income': 100,
    'net_profit': 99,
    'n_income_attr_p': 101,
    'other_col': 'test'
})

column_candidates = ['n_income', 'n_income_attr_p', 'net_profit']
value = helper.get_column_value(test_row, column_candidates)
print("Selected value from candidates {}: {}".format(column_candidates, value))

if value == 100:
    print("[OK] Correctly selected first available column")
else:
    print("[FAIL] Wrong value selected")
    exit(1)

print("\n" + "="*80)
print("[SUCCESS] All type conversion tests passed!")
print("="*80 + "\n")
