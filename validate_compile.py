# -*- coding: utf-8 -*-
import sys

file_path = 'multi_agent.py'

# 读取文件
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 用 UTF-8 BOM 重新保存
with open(file_path, 'w', encoding='utf-8-sig') as f:
    f.write(content)

print("✅ 已使用 UTF-8-BOM 编码重新保存文件")

# 尝试编译
try:
    compile(content, file_path, 'exec')
    print("✅ Python 编译成功")
except SyntaxError as e:
    print(f"❌ 编译失败: {e}")
    print(f"   位置: 第 {e.lineno} 行, 列 {e.offset}")
    if e.text:
        print(f"   代码: {e.text[:100]}")
