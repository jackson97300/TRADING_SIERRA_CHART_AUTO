"""Test syntax 5 fichiers cote VPS."""
import ast
files = [
    "C:/TRADING_SIERRA_CHART_AUTO/BOT/dtc_connector.py",
    "C:/TRADING_SIERRA_CHART_AUTO/CORE/mia_paper_trader.py",
    "C:/TRADING_SIERRA_CHART_AUTO/CORE/mia2_brain_v6_databento.py",
    "C:/TRADING_SIERRA_CHART_AUTO/CORE/databento_paper_trader_v2.py",
    "C:/TRADING_SIERRA_CHART_AUTO/CORE/bot3_config.py",
    "C:/TRADING_SIERRA_CHART_AUTO/CORE/log_catalog.py",
    "C:/TRADING_SIERRA_CHART_AUTO/BOT/log_catalog.py",
]
for f in files:
    try:
        with open(f, encoding="utf-8") as fp:
            ast.parse(fp.read())
        print(f"OK: {f}")
    except Exception as e:
        print(f"ERROR: {f} {type(e).__name__}: {e}")
