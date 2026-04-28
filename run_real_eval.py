#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"  # 使用国内镜像加速

"""
ASA Real Benchmark Evaluation Script
=====================================
Two-part evaluation (all against REAL APIs, no mocks):

Part 1: RAG Retrieval Quality
  - HybridRetriever (BM25 + Embedding, alpha=0.7)
  - Metrics: Context Recall, Context Precision, MRR@5, Hit@1

Part 2: End-to-End System Evaluation (real Tushare + real LLM)
  - Pass@1 by difficulty (easy/medium/hard)
  - Error classification accuracy
  - [DATA] output protocol compliance rate
  - Avg latency per difficulty tier

Usage:
  python run_real_eval.py                    # full eval (both parts)
  python run_real_eval.py --rag-only         # part 1 only
  python run_real_eval.py --e2e-only         # part 2 only
  python run_real_eval.py --e2e-n 5          # e2e with first 5 cases only (quick smoke test)
"""

import sys
import json
import time
import uuid
import re
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ============================================================
# 0. Args
# ============================================================
parser = argparse.ArgumentParser()
parser.add_argument("--rag-only",  action="store_true", help="Run RAG eval only")
parser.add_argument("--e2e-only",  action="store_true", help="Run E2E eval only")
parser.add_argument("--e2e-n",     type=int, default=None, help="Limit E2E to first N cases")
parser.add_argument("--e2e-start", type=int, default=0, help="Start E2E from case N (0-indexed)")
args = parser.parse_args()

RUN_RAG = not args.e2e_only
RUN_E2E = not args.rag_only

# ============================================================
# 1. Imports (fail fast with clear message)
# ============================================================
print("[Init] Loading project modules...")
try:
    import conf
    from lib import HybridRetriever, search, get_chat_model
except ImportError as e:
    print(f"[FATAL] Cannot import project modules: {e}")
    print("Make sure you run this script from the ASA project root directory.")
    sys.exit(1)

# ============================================================
# 2. RAG Ground-Truth Dataset
#    Format: {query, relevant_docs (keywords that must appear), irrelevant_queries}
#    All queries are real Tushare API documentation questions.
# ============================================================

RAG_EVAL_CASES = [
    # ============ 1. 接口选择查询 (25题) ============
    # 基础行情
    {"query": "查询股票日线行情数据用哪个接口", "relevant_keywords": ["daily", "日线", "open", "close", "vol"], "category": "interface_selection"},
    {"query": "获取股票的分钟级数据用什么接口", "relevant_keywords": ["min", "分钟", "minute"], "category": "interface_selection"},
    {"query": "查询股票的周K线数据", "relevant_keywords": ["weekly", "周线", "week"], "category": "interface_selection"},
    {"query": "获取股票的月K线数据", "relevant_keywords": ["monthly", "月线", "month"], "category": "interface_selection"},
    {"query": "查询实时行情数据用哪个接口", "relevant_keywords": ["realtime", "实时", "quotation"], "category": "interface_selection"},
    # 财务数据
    {"query": "获取上市公司财务指标ROE用哪个接口", "relevant_keywords": ["fina_indicator", "roe", "财务指标"], "category": "interface_selection"},
    {"query": "查询利润表数据用什么接口", "relevant_keywords": ["income", "利润", "revenue"], "category": "interface_selection"},
    {"query": "获取资产负债表数据", "relevant_keywords": ["balancesheet", "资产负债", "assets"], "category": "interface_selection"},
    {"query": "查询现金流量表数据", "relevant_keywords": ["cashflow", "现金流", "cash"], "category": "interface_selection"},
    {"query": "获取主要财务指标数据", "relevant_keywords": ["fina_indicator", "财务指标", "indicator"], "category": "interface_selection"},
    {"query": "查询业绩预告数据用哪个接口", "relevant_keywords": ["forecast", "预告", "业绩"], "category": "interface_selection"},
    {"query": "获取业绩快报数据", "relevant_keywords": ["express", "快报", "brief"], "category": "interface_selection"},
    # 分红融资
    {"query": "查询股票分红送股数据", "relevant_keywords": ["dividend", "分红", "cash_div", "div_proc"], "category": "interface_selection"},
    {"query": "获取配股数据用什么接口", "relevant_keywords": ["placement", "配股", "allotment"], "category": "interface_selection"},
    {"query": "查询增发数据", "relevant_keywords": ["seasoning", "增发", "seo"], "category": "interface_selection"},
    {"query": "获取IPO新股数据", "relevant_keywords": ["ipo", "新股", "new_stock"], "category": "interface_selection"},
    # 市场数据
    {"query": "北向资金每日持股数据怎么查", "relevant_keywords": ["hk_hold", "北向", "hushen", "hold_ratio"], "category": "interface_selection"},
    {"query": "获取个股资金流向数据", "relevant_keywords": ["moneyflow", "资金流向", "net_mf_amount"], "category": "interface_selection"},
    {"query": "查询行业资金流向", "relevant_keywords": ["moneyflow_industry", "行业资金", "industry"], "category": "interface_selection"},
    {"query": "获取龙虎榜数据用哪个接口", "relevant_keywords": ["top_list", "龙虎榜", "dragon_tiger"], "category": "interface_selection"},
    {"query": "查询融资融券数据", "relevant_keywords": ["margin", "融资", "融券", "margin_detail"], "category": "interface_selection"},
    {"query": "获取每日涨停股票数据", "relevant_keywords": ["limit_list", "涨停", "limit_up"], "category": "interface_selection"},
    {"query": "查询大宗交易数据", "relevant_keywords": ["block_trade", "大宗", "block"], "category": "interface_selection"},
    # 基础信息
    {"query": "获取股票基本信息用哪个接口", "relevant_keywords": ["stock_basic", "基本", "basic"], "category": "interface_selection"},
    {"query": "查询上市公司信息", "relevant_keywords": ["stock_company", "公司", "company"], "category": "interface_selection"},
    {"query": "获取交易日历数据", "relevant_keywords": ["trade_cal", "日历", "calendar"], "category": "interface_selection"},

    # ============ 2. 字段名查询 (25题) ============
    # daily_basic 字段
    {"query": "daily_basic接口中股息率字段名是什么", "relevant_keywords": ["dv_ttm", "dv_ratio", "daily_basic", "股息率"], "category": "field_name"},
    {"query": "daily_basic中市盈率PE对应哪个字段", "relevant_keywords": ["pe", "pe_ttm", "daily_basic", "市盈率"], "category": "field_name"},
    {"query": "daily_basic中市净率PB的字段名", "relevant_keywords": ["pb", "pb_ttm", "daily_basic", "市净率"], "category": "field_name"},
    {"query": "daily_basic中总市值字段是什么", "relevant_keywords": ["total_mv", "总市值", "market_value"], "category": "field_name"},
    {"query": "daily_basic中换手率字段名", "relevant_keywords": ["turnover_rate", "换手率", "turnover"], "category": "field_name"},
    {"query": "daily_basic中量比字段", "relevant_keywords": ["volume_ratio", "量比", "vr"], "category": "field_name"},
    # income 字段
    {"query": "income接口中营业收入对应的字段", "relevant_keywords": ["total_revenue", "revenue", "income", "营业收入"], "category": "field_name"},
    {"query": "income中净利润字段名是什么", "relevant_keywords": ["n_income", "net_income", "净利润", "profit"], "category": "field_name"},
    {"query": "income中营业成本字段", "relevant_keywords": ["oper_cost", "成本", "cost"], "category": "field_name"},
    {"query": "income中销售费用字段", "relevant_keywords": ["sell_exp", "销售费用", "selling"], "category": "field_name"},
    {"query": "income中管理费用字段名", "relevant_keywords": ["admin_exp", "管理费用", "admin"], "category": "field_name"},
    {"query": "income中财务费用字段", "relevant_keywords": ["fin_exp", "财务费用", "finance"], "category": "field_name"},
    # balancesheet 字段
    {"query": "balancesheet资产负债表总资产字段", "relevant_keywords": ["total_assets", "balancesheet", "资产负债"], "category": "field_name"},
    {"query": "balancesheet中总负债字段", "relevant_keywords": ["total_liab", "总负债", "liability"], "category": "field_name"},
    {"query": "balancesheet中股东权益字段", "relevant_keywords": ["total_hldr_eqy", "股东权益", "equity"], "category": "field_name"},
    {"query": "balancesheet中货币资金字段", "relevant_keywords": ["money_cap", "货币资金", "cash"], "category": "field_name"},
    {"query": "balancesheet中存货字段", "relevant_keywords": ["inventories", "存货", "inventory"], "category": "field_name"},
    # fina_indicator 字段
    {"query": "fina_indicator中ROE字段名", "relevant_keywords": ["roe", "fina_indicator", "净资产收益率"], "category": "field_name"},
    {"query": "fina_indicator中ROA字段", "relevant_keywords": ["roa", "总资产收益率", "return_on_assets"], "category": "field_name"},
    {"query": "fina_indicator中毛利率字段", "relevant_keywords": ["grossprofit_margin", "毛利率", "gross"], "category": "field_name"},
    {"query": "fina_indicator中净利率字段", "relevant_keywords": ["netprofit_margin", "净利率", "net_margin"], "category": "field_name"},
    {"query": "fina_indicator中资产负债率字段", "relevant_keywords": ["debt_to_assets", "资产负债率", "debt_ratio"], "category": "field_name"},
    # daily 字段
    {"query": "daily接口中开盘价字段", "relevant_keywords": ["open", "开盘价", "open_price"], "category": "field_name"},
    {"query": "daily中收盘价字段名", "relevant_keywords": ["close", "收盘价", "close_price"], "category": "field_name"},
    {"query": "daily中成交量字段", "relevant_keywords": ["vol", "volume", "成交量"], "category": "field_name"},

    # ============ 3. 错误修复/字段纠正 (20题) ============
    {"query": "pe_ratio字段不存在应该用什么替代", "relevant_keywords": ["pe", "pe_ttm", "daily_basic", "市盈率"], "category": "field_correction"},
    {"query": "dv字段报KeyError应该换成哪个字段", "relevant_keywords": ["dv_ttm", "dv_ratio", "dividend_yield", "股息率"], "category": "field_correction"},
    {"query": "revenue字段在income表中不存在怎么办", "relevant_keywords": ["total_revenue", "revenue", "income", "营业收入"], "category": "field_correction"},
    {"query": "profit字段报错应该用哪个字段替代", "relevant_keywords": ["n_income", "profit", "净利润", "net_income"], "category": "field_correction"},
    {"query": "assets字段不存在在balancesheet中", "relevant_keywords": ["total_assets", "assets", "总资产"], "category": "field_correction"},
    {"query": "liability字段报错怎么修", "relevant_keywords": ["total_liab", "liability", "总负债"], "category": "field_correction"},
    {"query": "roe_ratio字段不存在", "relevant_keywords": ["roe", "roe_ratio", "净资产收益率"], "category": "field_correction"},
    {"query": "pb_ratio字段报错", "relevant_keywords": ["pb", "pb_ttm", "pb_ratio", "市净率"], "category": "field_correction"},
    {"query": "market_value字段不存在", "relevant_keywords": ["total_mv", "market_value", "总市值"], "category": "field_correction"},
    {"query": "turnover字段报错", "relevant_keywords": ["turnover_rate", "turnover", "换手率"], "category": "field_correction"},
    {"query": "volume字段在daily中不存在", "relevant_keywords": ["vol", "volume", "成交量"], "category": "field_correction"},
    {"query": "open_price字段报错", "relevant_keywords": ["open", "open_price", "开盘价"], "category": "field_correction"},
    {"query": "close_price字段不存在", "relevant_keywords": ["close", "close_price", "收盘价"], "category": "field_correction"},
    {"query": "high_price字段报错", "relevant_keywords": ["high", "high_price", "最高价"], "category": "field_correction"},
    {"query": "low_price字段不存在", "relevant_keywords": ["low", "low_price", "最低价"], "category": "field_correction"},
    {"query": "eps字段报错应该用哪个", "relevant_keywords": ["eps", "basic_eps", "每股收益"], "category": "field_correction"},
    {"query": "bps字段不存在", "relevant_keywords": ["bps", "book_value_per_share", "每股净资产"], "category": "field_correction"},
    {"query": "cash_flow字段报错", "relevant_keywords": ["n_cashflow", "cash_flow", "现金流"], "category": "field_correction"},
    {"query": "debt字段不存在", "relevant_keywords": ["total_liab", "debt", "负债"], "category": "field_correction"},
    {"query": "equity字段报错", "relevant_keywords": ["total_hldr_eqy", "equity", "权益"], "category": "field_correction"},

    # ============ 4. 参数理解 (15题) ============
    {"query": "pro.daily接口的ts_code参数格式是什么", "relevant_keywords": ["ts_code", "daily", "股票代码", "000001.SZ"], "category": "parameter"},
    {"query": "trade_date参数应该传什么格式", "relevant_keywords": ["trade_date", "日期格式", "YYYYMMDD"], "category": "parameter"},
    {"query": "start_date和end_date参数怎么用", "relevant_keywords": ["start_date", "end_date", "起始日期", "结束日期"], "category": "parameter"},
    {"query": "fina_indicator的ann_date参数是什么", "relevant_keywords": ["ann_date", "公告日期", "fina_indicator"], "category": "parameter"},
    {"query": "daily_basic接口的trade_date必填吗", "relevant_keywords": ["trade_date", "daily_basic", "必填"], "category": "parameter"},
    {"query": "如何批量查询多只股票的数据", "relevant_keywords": ["批量", "多只股票", "ts_code", "逗号分隔"], "category": "parameter"},
    {"query": "pro.stock_basic接口的exchange参数", "relevant_keywords": ["exchange", "交易所", "SSE", "SZSE"], "category": "parameter"},
    {"query": "list_status参数的作用是什么", "relevant_keywords": ["list_status", "上市状态", "L", "D"], "category": "parameter"},
    {"query": "is_hs参数是什么意思", "relevant_keywords": ["is_hs", "沪深港通", "H", "S", "N"], "category": "parameter"},
    {"query": "pro.dividend接口的record_date参数", "relevant_keywords": ["record_date", "股权登记日", "dividend"], "category": "parameter"},
    {"query": "ex_date参数在分红中代表什么", "relevant_keywords": ["ex_date", "除权除息日", "除权", "除息"], "category": "parameter"},
    {"query": "pay_date参数是什么意思", "relevant_keywords": ["pay_date", "派息日", "分红到账"], "category": "parameter"},
    {"query": "moneyflow接口的trade_date范围限制", "relevant_keywords": ["moneyflow", "trade_date", "范围限制"], "category": "parameter"},
    {"query": "hk_hold接口的trade_date格式", "relevant_keywords": ["hk_hold", "trade_date", "北向资金"], "category": "parameter"},
    {"query": "top_list接口的trade_date必填吗", "relevant_keywords": ["top_list", "trade_date", "龙虎榜"], "category": "parameter"},

    # ============ 5. 多表关联/复杂查询 (15题) ============
    {"query": "如何同时获取股票的日线行情和基本面数据", "relevant_keywords": ["daily", "daily_basic", "合并", "join"], "category": "multi_table"},
    {"query": "查询股票的财务指标和利润表数据如何关联", "relevant_keywords": ["fina_indicator", "income", "关联", "ts_code"], "category": "multi_table"},
    {"query": "如何对比多只股票的ROE和净利润", "relevant_keywords": ["对比", "多只股票", "ROE", "净利润", "fina_indicator"], "category": "multi_table"},
    {"query": "获取股票的历史股价和分红数据", "relevant_keywords": ["daily", "dividend", "历史", "股价", "分红"], "category": "multi_table"},
    {"query": "如何计算股票的复权价格", "relevant_keywords": ["复权", "adj_factor", "daily", "factor"], "category": "multi_table"},
    {"query": "查询融资融券和资金流向的关联分析", "relevant_keywords": ["margin", "moneyflow", "融资", "资金流向"], "category": "multi_table"},
    {"query": "如何获取股票的龙虎榜和资金流向数据", "relevant_keywords": ["top_list", "moneyflow", "龙虎榜", "资金"], "category": "multi_table"},
    {"query": "分析股票的北向资金持股和股价走势", "relevant_keywords": ["hk_hold", "daily", "北向资金", "股价"], "category": "multi_table"},
    {"query": "如何查询行业板块的成分股和行情", "relevant_keywords": ["index_member", "daily", "行业", "成分股"], "category": "multi_table"},
    {"query": "获取股票的IPO信息和上市后表现", "relevant_keywords": ["ipo", "daily", "上市", "新股"], "category": "multi_table"},
    {"query": "如何分析股票的业绩预告和实际业绩", "relevant_keywords": ["forecast", "income", "预告", "实际"], "category": "multi_table"},
    {"query": "查询股票的股东人数和股价关系", "relevant_keywords": ["stk_holdernumber", "daily", "股东人数", "股价"], "category": "multi_table"},
    {"query": "如何获取股票的限售解禁和股价数据", "relevant_keywords": ["share_float", "daily", "解禁", "限售"], "category": "multi_table"},
    {"query": "分析股票的机构持股和涨跌幅关系", "relevant_keywords": ["inst_hold", "daily", "机构", "持股"], "category": "multi_table"},
    {"query": "如何查询股票的大宗交易和二级市场表现", "relevant_keywords": ["block_trade", "daily", "大宗交易", "二级市场"], "category": "multi_table"},
]

# ============================================================
# 3. E2E Test Cases (subset of evaluation.py GOLDEN_TEST_CASES)
#    Annotated with expected [DATA] presence and key fields
# ============================================================

E2E_TEST_CASES = [
    # ============ Easy (40题) ============
    # 基础股价查询
    {"query": "查询贵州茅台(600519.SH)的最新股息率", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["dv_ttm", "股息率", "600519"]},
    {"query": "贵州茅台今天的收盘价是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["close", "收盘价", "600519"]},
    {"query": "查询比亚迪(002594.SZ)的市值", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["total_mv", "市值", "002594"]},
    {"query": "中国平安的市盈率PE是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["pe", "市盈率"]},
    {"query": "宁德时代最新的每股收益是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["eps", "每股收益", "300750"]},
    {"query": "查询招商银行(600036.SH)的市净率", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["pb", "市净率", "600036"]},
    {"query": "腾讯控股的港股代码是什么", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["00700", "腾讯"]},
    {"query": "查询阿里巴巴的港股股价", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["09988", "阿里巴巴"]},
    {"query": "茅台股票的开盘价是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["open", "开盘价", "茅台"]},
    {"query": "查询五粮液(000858.SZ)的换手率", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["turnover", "换手率", "000858"]},
    # 财务指标查询
    {"query": "查询工商银行(601398.SH)的ROE", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["roe", "601398"]},
    {"query": "建设银行的总资产是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["total_assets", "资产", "建行"]},
    {"query": "查询中国平安的净利润", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["n_income", "净利润", "平安"]},
    {"query": "比亚迪的营业收入是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["total_revenue", "营业收入", "比亚迪"]},
    {"query": "查询宁德时代的毛利率", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["grossprofit_margin", "毛利率", "宁德"]},
    {"query": "招商银行的资产负债率是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["debt_to_assets", "资产负债率", "招行"]},
    {"query": "查询茅台的每股净资产", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["bps", "每股净资产", "茅台"]},
    {"query": "五粮液的经营现金流是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["n_cashflow", "现金流", "五粮液"]},
    {"query": "查询中信证券的净利率", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["netprofit_margin", "净利率", "中信"]},
    {"query": "海康威视的总市值是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["total_mv", "市值", "海康"]},
    # 分红数据查询
    {"query": "查询贵州茅台最近一年的分红情况", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["dividend", "分红", "600519"]},
    {"query": "工商银行的分红派息日是什么时候", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["pay_date", "派息", "工行"]},
    {"query": "查询中国平安的股权登记日", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["record_date", "股权登记", "平安"]},
    {"query": "建设银行的每股分红是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["cash_div", "每股分红", "建行"]},
    {"query": "查询招商银行的除权除息日", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["ex_date", "除权", "除息", "招行"]},
    # 市场数据查询
    {"query": "查询贵州茅台的资金流向", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["moneyflow", "资金流向", "600519"]},
    {"query": "比亚迪的北向资金持股多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["hk_hold", "北向资金", "比亚迪"]},
    {"query": "查询宁德时代是否上了龙虎榜", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["top_list", "龙虎榜", "宁德"]},
    {"query": "中国平安的融资余额是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["margin", "融资", "平安"]},
    {"query": "查询五粮液的融券余额", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["margin", "融券", "五粮液"]},
    {"query": "茅台股票的成交量是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["vol", "成交量", "茅台"]},
    {"query": "查询招商银行的量比", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["volume_ratio", "量比", "招行"]},
    {"query": "宁德时代的振幅是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["amp", "振幅", "宁德"]},
    {"query": "查询比亚迪的涨跌幅", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["pct_chg", "涨跌幅", "比亚迪"]},
    {"query": "工商银行的最高价是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["high", "最高价", "工行"]},
    {"query": "查询建设银行的最低价", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["low", "最低价", "建行"]},
    {"query": "中国平安的成交额是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["amount", "成交额", "平安"]},
    {"query": "查询茅台的涨停价", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["up_limit", "涨停", "茅台"]},
    {"query": "五粮液的跌停价是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["down_limit", "跌停", "五粮液"]},
    {"query": "查询宁德时代的动态市盈率", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["pe_ttm", "动态市盈率", "宁德"]},
    {"query": "比亚迪的静态市盈率是多少", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["pe", "静态市盈率", "比亚迪"]},
    {"query": "查询招商银行的股息率", "difficulty": "easy", "category": "stock_query", "expect_data": True, "expect_keywords": ["dv_ttm", "股息率", "招行"]},

    # ============ Medium (35题) ============
    # 财务分析
    {"query": "计算贵州茅台最近3年的年均净利润增长率", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["增长率", "净利润", "n_income"]},
    {"query": "对比贵州茅台和五粮液的ROE数据", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["roe", "ROE"]},
    {"query": "查询银行板块中股息率最高的前5只股票", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["dv_ttm", "银行"]},
    {"query": "分析茅台和五粮液的毛利率差异", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["grossprofit_margin", "毛利率", "茅台", "五粮液"]},
    {"query": "对比比亚迪和宁德时代的资产负债率", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["debt_to_assets", "资产负债率"]},
    {"query": "计算招商银行近5年的平均ROE", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["roe", "平均", "招行"]},
    {"query": "分析中国平安的营收和净利润趋势", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["revenue", "n_income", "趋势", "平安"]},
    {"query": "对比工商银行和建设银行的总资产规模", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["total_assets", "资产规模"]},
    {"query": "查询白酒行业市盈率最低的前10只股票", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["pe", "白酒", "市盈率"]},
    {"query": "分析宁德时代近3年的营收增长率", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["revenue", "增长率", "宁德"]},
    {"query": "对比茅台、五粮液、泸州老窖的净利率", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["netprofit_margin", "净利率", "白酒"]},
    {"query": "查询新能源板块市值最大的5家公司", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["total_mv", "新能源", "市值"]},
    {"query": "分析比亚迪的ROA和ROE关系", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["roa", "roe", "比亚迪"]},
    {"query": "对比银行板块和保险板块的平均股息率", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["dv_ttm", "银行", "保险", "平均"]},
    {"query": "查询医药板块中毛利率高于80%的股票", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["grossprofit_margin", "医药", "毛利率"]},
    # 多维度对比
    {"query": "对比茅台和五粮液的股价走势和估值水平", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["股价", "pe", "pb", "茅台", "五粮液"]},
    {"query": "分析宁德时代的资金流向和北向资金持股变化", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["moneyflow", "hk_hold", "宁德"]},
    {"query": "查询比亚迪的融资融券余额和股价关系", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["margin", "股价", "比亚迪"]},
    {"query": "对比招商银行和平安银行的资产质量", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["npl_ratio", "不良率", "招行", "平安银行"]},
    {"query": "分析中国平安的保费收入和净利润关系", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["premium", "n_income", "平安"]},
    {"query": "查询白酒板块的龙头股市值和估值对比", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["total_mv", "pe", "白酒", "龙头"]},
    {"query": "对比宁德时代和比亚迪的营收增速", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["revenue", "增速", "宁德", "比亚迪"]},
    {"query": "分析工商银行的净息差和ROE关系", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["nim", "净息差", "roe", "工行"]},
    {"query": "查询科技板块中研发投入占比最高的公司", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["rd_exp", "研发", "科技"]},
    {"query": "对比茅台和五粮液的现金流质量", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["cash_flow", "现金流", "茅台", "五粮液"]},
    {"query": "分析建设银行的资本充足率变化", "difficulty": "medium", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["car", "资本充足率", "建行"]},
    # 筛选排序
    {"query": "筛选A股市净率低于1的银行股", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["pb", "市净率", "银行"]},
    {"query": "查询近一年涨幅超过50%的消费股", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["pct_chg", "涨幅", "消费"]},
    {"query": "筛选ROE连续5年高于15%的公司", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["roe", "连续", "15%"]},
    {"query": "查询股息率超过5%的蓝筹股", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["dv_ttm", "股息率", "蓝筹"]},
    {"query": "筛选市值在100-500亿之间的成长股", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["total_mv", "市值", "成长"]},
    {"query": "分析近一个月换手率最高的前20只股票", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["turnover", "换手率", "一个月"]},
    {"query": "查询北向资金持股比例最高的10只股票", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["hk_hold", "北向资金", "持股比例"]},
    {"query": "筛选负债率低于40%的制造业公司", "difficulty": "medium", "category": "stock_query", "expect_data": True, "expect_keywords": ["debt_to_assets", "负债率", "制造业"]},

    # ============ Hard (25题) ============
    # 复杂分析
    {"query": "分析比亚迪最近3年的营收变化趋势，给出数据支撑", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["revenue", "营收", "002594", "趋势"]},
    {"query": "筛选A股中市盈率低于20且股息率高于3%的股票", "difficulty": "hard", "category": "stock_query", "expect_data": True, "expect_keywords": ["pe", "dv_ttm", "筛选"]},
    {"query": "对比分析茅台、五粮液、泸州老窖的估值和成长性", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["pe", "pb", "growth", "茅台", "五粮液", "老窖"]},
    {"query": "计算宁德时代近3年的自由现金流并分析趋势", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["fcf", "自由现金流", "宁德", "趋势"]},
    {"query": "分析银行板块的净息差收窄对ROE的影响", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["nim", "净息差", "roe", "银行"]},
    {"query": "对比新能源车和传统车企的估值水平和盈利能力", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["pe", "pb", "roe", "新能源", "传统车企"]},
    {"query": "分析中国平安的寿险业务价值和新业务价值变化", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["nbv", "新业务价值", "平安", "寿险"]},
    {"query": "查询近一年北向资金持续流入且涨幅超过30%的股票", "difficulty": "hard", "category": "stock_query", "expect_data": True, "expect_keywords": ["hk_hold", "北向资金", "涨幅", "30%"]},
    {"query": "分析茅台的批价、库存和股价的关系", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["price", "inventory", "股价", "茅台", "批价"]},
    {"query": "对比分析四大行的资产质量、盈利能力和估值水平", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["npl_ratio", "roe", "pb", "四大行"]},
    {"query": "计算比亚迪的WACC并分析其资本结构合理性", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["wacc", "资本成本", "资本结构", "比亚迪"]},
    {"query": "分析白酒行业的周期性和龙头公司的竞争优势", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["cycle", "周期", "competitive", "白酒", "龙头"]},
    {"query": "筛选PEG小于1且ROE高于20%的成长股", "difficulty": "hard", "category": "stock_query", "expect_data": True, "expect_keywords": ["peg", "roe", "成长股", "20%"]},
    {"query": "分析宁德时代的产能扩张和资本开支计划", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["capex", "资本开支", "产能", "宁德"]},
    {"query": "对比分析中美银行股估值差异及原因", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["pb", "pe", "中美", "银行", "估值差异"]},
    {"query": "分析茅台的提价能力和品牌护城河", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["pricing_power", "提价", "护城河", "茅台"]},
    {"query": "查询近半年机构持续加仓且业绩超预期的股票", "difficulty": "hard", "category": "stock_query", "expect_data": True, "expect_keywords": ["inst_hold", "机构", "业绩", "超预期"]},
    {"query": "分析比亚迪的垂直整合战略对毛利率的影响", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["vertical_integration", "垂直整合", "毛利率", "比亚迪"]},
    {"query": "计算招商银行的核心一级资本充足率并评估其安全性", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["core_car", "核心一级资本", "招行", "安全性"]},
    {"query": "分析保险行业的长端利率走势对投资收益的影响", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["interest_rate", "长端利率", "投资收益", "保险"]},
    {"query": "对比分析宁德时代和LG新能源的全球竞争力", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["competitive", "竞争力", "宁德", "LG", "全球"]},
    {"query": "筛选具有持续分红能力且分红率适中的价值股", "difficulty": "hard", "category": "stock_query", "expect_data": True, "expect_keywords": ["dividend", "分红能力", "分红率", "价值股"]},
    {"query": "分析茅台的渠道库存和真实动销情况", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["inventory", "渠道库存", "动销", "茅台"]},
    {"query": "对比分析互联网平台公司和传统零售公司的估值逻辑", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["valuation", "估值逻辑", "互联网", "零售"]},
    {"query": "分析比亚迪的海外扩张战略和出口数据", "difficulty": "hard", "category": "financial_analysis", "expect_data": True, "expect_keywords": ["overseas", "海外", "出口", "比亚迪", "扩张"]},
]


# ============================================================
# 4. RAG Evaluation
# ============================================================

def run_rag_evaluation() -> Dict:
    """
    Evaluates HybridRetriever quality against RAG_EVAL_CASES.

    Metrics computed:
      - Hit@1:  top-1 result contains at least one relevant keyword
      - Hit@3:  any of top-3 results contain a relevant keyword
      - MRR@5:  mean reciprocal rank of first relevant hit within top-5
      - Context Precision:  fraction of retrieved docs (top-3) that are relevant
      - Context Recall:     fraction of relevant keywords covered by top-3 results
    """
    print("\n" + "="*60)
    print("PART 1: RAG Retrieval Quality Evaluation")
    print("="*60)
    print(f"Test cases: {len(RAG_EVAL_CASES)}")
    print("Retriever: HybridRetriever (BM25 + Embedding, alpha=0.7)\n")

    hit1_list, hit3_list, mrr_list = [], [], []
    precision_list, recall_list = [], []
    per_case_results = []

    for i, case in enumerate(RAG_EVAL_CASES):
        query = case["query"]
        rel_kws = [kw.lower() for kw in case["relevant_keywords"]]

        try:
            # Real retrieval — search() calls HybridRetriever.search() internally
            raw_result = search(query, topk=5)
            result_lower = raw_result.lower()

            # Split into doc chunks (HybridRetriever returns numbered sections)
            # Try to parse individual doc results
            doc_sections = re.split(r'\n---|\n\d+\.\s', raw_result)
            doc_sections = [s for s in doc_sections if len(s.strip()) > 20]

            # Hit@1
            top1 = doc_sections[0].lower() if doc_sections else result_lower[:500]
            hit1 = any(kw in top1 for kw in rel_kws)

            # Hit@3
            top3_text = " ".join(doc_sections[:3]).lower() if len(doc_sections) >= 3 else result_lower
            hit3 = any(kw in top3_text for kw in rel_kws)

            # MRR@5
            mrr = 0.0
            for rank, doc in enumerate(doc_sections[:5], start=1):
                if any(kw in doc.lower() for kw in rel_kws):
                    mrr = 1.0 / rank
                    break

            # Context Precision (top-3 relevant / 3)
            relevant_docs = sum(
                1 for doc in doc_sections[:3]
                if any(kw in doc.lower() for kw in rel_kws)
            )
            precision = relevant_docs / min(3, len(doc_sections)) if doc_sections else 0.0

            # Context Recall (keywords covered in top-3)
            covered = sum(1 for kw in rel_kws if kw in top3_text)
            recall = covered / len(rel_kws)

            hit1_list.append(hit1)
            hit3_list.append(hit3)
            mrr_list.append(mrr)
            precision_list.append(precision)
            recall_list.append(recall)

            status = "PASS" if hit3 else "MISS"
            print(f"  [{i+1:02d}] {status} | query: {query[:35]:<35} | "
                  f"hit@1={int(hit1)} hit@3={int(hit3)} mrr={mrr:.2f} "
                  f"prec={precision:.2f} rec={recall:.2f}")

            per_case_results.append({
                "query": query,
                "category": case["category"],
                "hit1": hit1, "hit3": hit3, "mrr": mrr,
                "precision": precision, "recall": recall,
                "retrieved_snippet": raw_result[:300],
            })

        except Exception as e:
            print(f"  [{i+1:02d}] ERROR | {query[:35]} | {e}")
            hit1_list.append(False)
            hit3_list.append(False)
            mrr_list.append(0.0)
            precision_list.append(0.0)
            recall_list.append(0.0)
            per_case_results.append({
                "query": query, "category": case["category"],
                "error": str(e),
                "hit1": False, "hit3": False, "mrr": 0.0,
                "precision": 0.0, "recall": 0.0,
            })

    n = len(RAG_EVAL_CASES)
    summary = {
        "total": n,
        "hit_at_1":          round(sum(hit1_list) / n, 4),
        "hit_at_3":          round(sum(hit3_list) / n, 4),
        "mrr_at_5":          round(sum(mrr_list)  / n, 4),
        "context_precision": round(sum(precision_list) / n, 4),
        "context_recall":    round(sum(recall_list)    / n, 4),
    }

    print()
    print("--- RAG Summary ---")
    for k, v in summary.items():
        pct = f"  ({v*100:.1f}%)" if isinstance(v, float) else ""
        print(f"  {k:<22}: {v}{pct}")

    return {"summary": summary, "per_case": per_case_results}


# ============================================================
# 5. E2E System Evaluation
# ============================================================

def run_e2e_evaluation(limit: Optional[int] = None) -> Dict:
    """
    Runs end-to-end evaluation against real Tushare API + real LLM.

    For each test case the full multi-agent pipeline is invoked via
    multi_agent_app.ainvoke / synchronous invoke.

    Metrics:
      - Pass@1 overall and by difficulty
      - [DATA]: protocol compliance rate
      - Error classification (code_error / data_vacuum / network_error)
      - Avg / P95 latency by difficulty
    """
    print("\n" + "="*60)
    print("PART 2: End-to-End System Evaluation")
    print("="*60)

    # Import the compiled graph — this triggers full system init
    print("[E2E] Loading multi_agent_app (this may take ~10s)...")
    try:
        from multi_agent import multi_agent_app
        from langchain_core.messages import HumanMessage
    except Exception as e:
        print(f"[E2E] FATAL: Cannot load multi_agent_app: {e}")
        return {"error": str(e)}

    start_idx = args.e2e_start
    all_cases = E2E_TEST_CASES[start_idx:]  # Skip first N cases
    cases = all_cases[:limit] if limit else all_cases
    print(f"[E2E] Running {len(cases)} test cases (starting from #{start_idx+1}) against real APIs\n")

    results = []
    for i, case in enumerate(cases):
        query    = case["query"]
        diff     = case["difficulty"]
        expect_d = case["expect_data"]
        exp_kws  = [kw.lower() for kw in case["expect_keywords"]]

        thread_id = f"eval_{uuid.uuid4().hex[:8]}"
        config    = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}

        initial_state = {
            "messages": [HumanMessage(content=query)],
            "next": "Supervisor",
            "retry_count": 0,
            "user_profile": {},
            "execution_status": "pending",
            "last_sender": "User",
            "task_plan": {},
            "remaining_steps": [],
            "error_type": None,
            "network_retry_count": 0,
            "supervisor_retry": 0,
            "last_execution_data": {},
            "message_window_size": 20,
            "tool_call_count": 0,
            "reviewer_fail_count": 0,
            "total_step_count": 0,  # 全局步数计数器 (防RecursionLimit)
        }

        t0 = time.time()
        final_answer = ""
        error_msg    = ""
        success      = False

        try:
            # Synchronous invoke
            final_state = multi_agent_app.invoke(initial_state, config)
            latency_ms  = (time.time() - t0) * 1000

            # Extract final answer from last AI message
            msgs = final_state.get("messages", [])
            for msg in reversed(msgs):
                content = getattr(msg, "content", "")
                if content and isinstance(content, str) and len(content) > 20:
                    final_answer = content
                    break

            # Also collect all message content (including ToolMessages) for [DATA]: detection
            all_content = " ".join(
                getattr(m, "content", "") or ""
                for m in msgs
                if isinstance(getattr(m, "content", ""), str)
            )

            # Evaluate
            answer_lower = final_answer.lower()
            all_lower    = all_content.lower()
            has_data     = "[data]:" in all_lower or "[data]" in all_lower
            kw_hits      = sum(1 for kw in exp_kws if kw in all_lower)
            kw_recall    = kw_hits / len(exp_kws) if exp_kws else 0.0

            # Pass criterion: has [DATA] + at least 50% expected keywords present
            success = has_data and kw_recall >= 0.5

            status = "PASS" if success else "FAIL"
            print(f"  [{i+1:02d}] {status} [{diff:6s}] {query[:40]:<40} | "
                  f"data={int(has_data)} kw_recall={kw_recall:.2f} "
                  f"latency={latency_ms/1000:.1f}s")

        except Exception as e:
            latency_ms  = (time.time() - t0) * 1000
            error_msg   = str(e)
            has_data    = False
            kw_recall   = 0.0
            success     = False
            status      = "ERROR"
            print(f"  [{i+1:02d}] {status} [{diff:6s}] {query[:40]:<40} | {error_msg[:60]}")

        results.append({
            "query":        query,
            "difficulty":   diff,
            "category":     case["category"],
            "success":      success,
            "has_data":     has_data,
            "kw_recall":    round(kw_recall, 4),
            "latency_ms":   round(latency_ms, 1),
            "final_answer": final_answer[:500],
            "error":        error_msg[:200] if error_msg else "",
        })

    # Aggregate stats
    total   = len(results)
    passed  = sum(1 for r in results if r["success"])
    has_data_rate = sum(1 for r in results if r["has_data"]) / total

    by_diff: Dict[str, Dict] = {}
    for diff in ["easy", "medium", "hard"]:
        subset = [r for r in results if r["difficulty"] == diff]
        if subset:
            by_diff[diff] = {
                "total":        len(subset),
                "passed":       sum(1 for r in subset if r["success"]),
                "pass_rate":    round(sum(1 for r in subset if r["success"]) / len(subset), 4),
                "avg_latency_s": round(sum(r["latency_ms"] for r in subset) / len(subset) / 1000, 2),
                "data_rate":    round(sum(1 for r in subset if r["has_data"]) / len(subset), 4),
            }

    summary = {
        "total":            total,
        "passed":           passed,
        "pass_at_1":        round(passed / total, 4),
        "data_protocol_rate": round(has_data_rate, 4),
        "avg_latency_s":    round(sum(r["latency_ms"] for r in results) / total / 1000, 2),
        "by_difficulty":    by_diff,
    }

    print()
    print("--- E2E Summary ---")
    print(f"  pass@1 overall       : {summary['pass_at_1']:.4f}  ({passed}/{total})")
    print(f"  [DATA] protocol rate : {summary['data_protocol_rate']:.4f}")
    print(f"  avg latency          : {summary['avg_latency_s']:.2f}s")
    for diff, stats in by_diff.items():
        print(f"  [{diff:6s}] pass={stats['pass_rate']:.2f}  "
              f"data={stats['data_rate']:.2f}  "
              f"lat={stats['avg_latency_s']:.1f}s  "
              f"({stats['passed']}/{stats['total']})")

    return {"summary": summary, "per_case": results}


# ============================================================
# 6. Main
# ============================================================

def main():
    ts_start = datetime.now()
    print(f"\nASA Real Benchmark — started at {ts_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"LLM backend : {conf.base_url}")
    print(f"Tushare token prefix: {conf.tushare_token[:8]}...")

    output = {
        "run_time":   ts_start.isoformat(),
        "llm_backend": conf.base_url,
    }

    if RUN_RAG:
        rag_results = run_rag_evaluation()
        output["rag"] = rag_results
    else:
        print("[Skip] RAG evaluation skipped (--e2e-only)")

    if RUN_E2E:
        e2e_results = run_e2e_evaluation(limit=args.e2e_n)
        output["e2e"] = e2e_results
    else:
        print("[Skip] E2E evaluation skipped (--rag-only)")

    # Save results
    out_dir  = Path("evaluation_results")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"real_eval_{ts_start.strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[Done] Results saved to: {out_file}")

    # Print concise metric card for resume copy-paste
    print("\n" + "="*60)
    print("METRIC CARD  (copy to resume)")
    print("="*60)
    if "rag" in output:
        s = output["rag"]["summary"]
        print(f"  RAG Hit@3           : {s['hit_at_3']*100:.1f}%")
        print(f"  RAG Context Recall  : {s['context_recall']*100:.1f}%")
        print(f"  RAG Context Precision: {s['context_precision']*100:.1f}%")
        print(f"  RAG MRR@5           : {s['mrr_at_5']*100:.1f}%")
    if "e2e" in output:
        s = output["e2e"]["summary"]
        print(f"  E2E Pass@1 overall  : {s['pass_at_1']*100:.1f}%  ({s['passed']}/{s['total']})")
        print(f"  [DATA] protocol rate: {s['data_protocol_rate']*100:.1f}%")
        print(f"  Avg latency         : {s['avg_latency_s']:.1f}s")
        for diff, stats in s.get("by_difficulty", {}).items():
            print(f"    [{diff:6s}] pass={stats['pass_rate']*100:.0f}%  "
                  f"lat={stats['avg_latency_s']:.1f}s")
    print("="*60)


if __name__ == "__main__":
    main()
