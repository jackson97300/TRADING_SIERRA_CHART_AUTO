"""Test imports critiques post-fix."""
import sys
sys.path.insert(0, "C:/TRADING_SIERRA_CHART_AUTO/CORE")
sys.path.insert(0, "C:/TRADING_SIERRA_CHART_AUTO/BOT")

# Test 1 : dtc_connector get_last_fill_price method exists
try:
    from dtc_connector import DTCConnector
    has_method = hasattr(DTCConnector, "get_last_fill_price")
    print(f"[1] DTCConnector.get_last_fill_price exists: {has_method}")
except Exception as e:
    print(f"[1] FAIL: {type(e).__name__}: {e}")

# Test 2 : bot3_config MAX_DRIFT_TICKS
try:
    from bot3_config import MAX_DRIFT_TICKS, TRADE_ACCOUNT_BOT3
    print(f"[2] MAX_DRIFT_TICKS: {MAX_DRIFT_TICKS}")
    print(f"[2] TRADE_ACCOUNT_BOT3: {TRADE_ACCOUNT_BOT3}")
except Exception as e:
    print(f"[2] FAIL: {type(e).__name__}: {e}")

# Test 3 : log_catalog new codes
try:
    from log_catalog import LOG_CODES
    codes = ["BOT_ENTRY_FILL_RECORDED", "BOT_DRIFT_REJECT"]
    for c in codes:
        if c in LOG_CODES:
            level, cat, template = LOG_CODES[c]
            print(f"[3] {c}: level={level.name}, cat={cat}, template_ok")
        else:
            print(f"[3] {c}: MISSING")
except Exception as e:
    print(f"[3] FAIL: {type(e).__name__}: {e}")

print("\n=== TESTS DONE ===")
