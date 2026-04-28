#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""完整修复multi_agent.py"""

import re

print("开始修复multi_agent.py...")

# 读取文件
with open('multi_agent.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. 移除所有emoji
print("1. 移除emoji...")
emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  
        u"\U0001F300-\U0001F5FF"  
        u"\U0001F680-\U0001F6FF"  
        u"\U0001F1E0-\U0001F1FF"  
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)
content = emoji_pattern.sub('', content)

# 2. 替换特殊中文标点
print("2. 替换特殊标点...")
replacements = {
    '【': '[',
    '】': ']',
    '「': '"',
    '」': '"',
    '✅': '',
    '❌': '',
    '⚠': '[WARNING]',
    '️': '',
}
for old, new in replacements.items():
    content = content.replace(old, new)

# 3. 修复反引号问题（在三引号字符串内的反引号转义）
print("3. 转义反引号...")
# 简单策略：在三引号字符串内的单个反引号前加转义
content = content.replace('`', '\\`')

# 4. 修复多余引号
print("4. 修复引号...")
#content = re.sub(r'""""+', '"""', content)  # 4个或更多引号简化为3个

# 5. 确保文件以UTF-8保存
print("5. 写回文件...")
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
        print(f"   Text: {e.text[:100]}")
