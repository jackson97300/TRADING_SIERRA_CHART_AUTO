"""Verifier syntax mia_bench.py."""
import ast
with open(r"C:\TRADING_SIERRA_CHART_AUTO\CORE\mia_bench.py", "r", encoding="utf-8") as f:
    src = f.read()
try:
    ast.parse(src)
    print("syntax OK")
except SyntaxError as e:
    print(f"SyntaxError ligne {e.lineno}: {e.msg}")
