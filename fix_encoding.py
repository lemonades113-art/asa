#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修复multi_agent.py中的emoji和特殊字符"""

import re

# 读取文件
with open('multi_agent.py', 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 移除所有emoji字符（使用正则表达式）
emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"  # emoticons
        u"\U0001F300-\U0001F5FF"  # symbols & pictographs
        u"\U0001F680-\U0001F6FF"  # transport & map symbols
        u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
        u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE)

content = emoji_pattern.sub('', content)

# 替换特殊中文字符
replacements = {
    '【': '[',
    '】': ']',
    '「': '"',
    '」': '"',
    '✅': '',  # checkmark
    '❌': '',  # cross mark  
    '⚠': '[WARNING]',  # warning
    '️': '',  # variation selector
}

for old, new in replacements.items():
    content = content.replace(old, new)

# 写回文件，强制使用UTF-8编码
with open('multi_agent.py', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content)

print("修复完成！已移除所有emoji和特殊字符")
