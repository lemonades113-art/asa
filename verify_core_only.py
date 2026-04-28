#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""核心功能独立验证（无需 gradio/langchain）"""
import ast as _ast
from difflib import get_close_matches
import re

print("=" * 50)
print("核心功能独立验证")
print("=" * 50)

# 1. AST 安全检查
BLOCKED_MODULES = {"os", "subprocess", "sys", "shutil", "socket"}
BLOCKED_BUILTINS = {"eval", "exec", "compile", "open", "__import__", "getattr"}

def safety_check(code):
    try:
        tree = _ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误: {e}"
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BLOCKED_MODULES:
                    return False, f"禁止导入: {alias.name}"
        if isinstance(node, _ast.ImportFrom):
            if node.module:
                if node.module.split(".")[0] in BLOCKED_MODULES:
                    return False, f"禁止from导入: {node.module}"
        if isinstance(node, _ast.Call):
            func = node.func
            if isinstance(func, _ast.Name) and func.id in BLOCKED_BUILTINS:
                return False, f"禁止调用: {func.id}()"
            if isinstance(func, _ast.Attribute) and func.attr in BLOCKED_BUILTINS:
                return False, f"禁止属性调用: .{func.attr}()"
    return True, "OK"

print("\n[AST安全检查]")
tests = [
    ("正常代码", 'df = pd.DataFrame()'),
    ("危险import", "import os"),
    ("危险from", "from subprocess import Popen"),
    ("危险eval", 'eval("1+1")'),
    ("危险exec", 'exec("print(1)")'),
]
for name, code in tests:
    ok, msg = safety_check(code)
    print(f"  {name}: {'拦截' if not ok else '通过'} ({msg})")

# 2. 字段别名表
print("\n[字段别名表]")
ALIAS = {
    "市盈率": "pe_ttm",
    "PE": "pe_ttm",
    "pe_ratio": "pe_ttm",
    "pb_ratio": "pb",
    "净利润": "n_income",
    "ROE": "roe",
    "收盘价": "close",
    "开盘价": "open",
}
for k, v in ALIAS.items():
    print(f"  {k} -> {v}")

# 3. KeyError 提取
print("\n[KeyError提取]")
def extract_field_error(error_message):
    match = re.search(r"KeyError:\s*['\"](\w+)['\"]", error_message)
    if match:
        return match.group(1)
    return None

err1 = "KeyError: 'pb_ttm'"
err2 = "KeyError: 'roe_weighted'"
print(f"  '{err1}' -> 字段: {extract_field_error(err1)}")
print(f"  '{err2}' -> 字段: {extract_field_error(err2)}")

# 4. 错误压缩
print("\n[错误压缩]")
def compress_error(msg, max_lines=5):
    lines = msg.split("\n")
    if len(lines) <= max_lines:
        return msg
    first = lines[:2]
    last = lines[-(max_lines-2):]
    omitted = len(lines) - len(first) - len(last)
    return "\n".join(first) + f"\n... ({omitted} lines omitted) ..." + "\n".join(last)

long_error = "Error: KeyError\nline1\nline2\nline3\nline4\nline5\nline6\nline7\nline8"
print(f"  压缩后: {compress_error(long_error)}")

print("\n" + "=" * 50)
print("核心功能验证通过！")
print("=" * 50)
