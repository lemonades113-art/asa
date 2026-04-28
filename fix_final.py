#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""最终修复multi_agent.py - 只移除emoji不改其他"""

import re

print("开始修复multi_agent.py...")

# 读取文件
with open('multi_agent.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. 移除所有emoji（完整Unicode范围）
print("1. 移除emoji...")
emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002500-\U00002BEF"  # chinese char
        u"\U00002702-\U000027B0"
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        u"\U0001f926-\U0001f937"
        u"\U00010000-\U0010ffff"
        u"\u2640-\u2642" 
        u"\u2600-\u2B55"
        u"\u200d"
        u"\u23cf"
        u"\u23e9"
        u"\u231a"
        u"\ufe0f"  # dingbats
        u"\u3030"
        "]+", flags=re.UNICODE)

content = emoji_pattern.sub('', content)

# 2. 只替换可能导致语法错误的特殊标点
print("2. 替换特殊标点...")
replacements = {
    '【': '[',
    '】': ']',
    '「': '"',
    '」': '"',
}
for old, new in replacements.items():
    content = content.replace(old, new)

# 3. 写回文件
print("3. 写回文件...")
with open('multi_agent.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)

print("修复完成！")

# 验证语法
print("\n验证语法...")
try:
    import ast
    ast.parse(content)
    print("✓ 语法检查通过！")
except SyntaxError as e:
    print(f"✗ 仍有语法错误 at line {e.lineno}: {e.msg}")
    if e.text:
        print(f"   问题行: {e.text.strip()[:80]}")
