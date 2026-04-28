import ast
import sys

try:
    with open('multi_agent.py', 'r', encoding='utf-8') as f:
        code = f.read()
    ast.parse(code)
    print("Syntax OK")
except SyntaxError as e:
    print(f"SyntaxError at line {e.lineno}: {e.msg}")
    print(f"Text: {e.text}")
    sys.exit(1)
