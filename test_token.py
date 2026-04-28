#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速测试 Tushare Token"""

import tushare as ts
import conf

print("=" * 50)
print("Tushare Token 测试")
print("=" * 50)

# 设置token
print(f"Token: {conf.tushare_token[:15]}...{conf.tushare_token[-10:]}")
ts.set_token(conf.tushare_token)

try:
    pro = ts.pro_api()
    print("✅ pro_api() 初始化成功")
    
    # 测试简单查询
    print("正在查询贵州茅台数据...")
    df = pro.daily(ts_code='600519.SH', limit=1)
    
    if df is not None and not df.empty:
        print("✅ Token 有效！")
        print(f"最新数据: {df['trade_date'].iloc[0]}, 收盘价: {df['close'].iloc[0]}")
    else:
        print("❌ Token 可能无效或无权限")
        
except Exception as e:
    print(f"❌ 错误: {type(e).__name__}: {e}")

print("=" * 50)
