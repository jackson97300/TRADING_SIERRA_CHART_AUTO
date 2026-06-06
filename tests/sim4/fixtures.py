# tests/sim4/fixtures.py
"""Synthetic bars for narrative engine tests."""

from typing import Any


# Real column names from DATA/live_enriched/NQ/YYYYMMDD_NQ.jsonl (verified 2026-06-06)
DEFAULT_BAR_FIELDS = {
    "ts": 1780531200000,
    "symbol": "NQ.c.0",
    "open": 30000.0,
    "high": 30010.0,
    "low": 29995.0,
    "close": 30005.0,
    "volume": 1000,
    "delta_bar": 50.0,
    "cur_vpoc": 30002.0,
    "cur_vah": 30015.0,
    "cur_val": 29990.0,
    "inside_value_area": 1,
    "cvd_session": 500.0,
    "day_type": 0,
    "open_type": 0,
    "profile_shape": 1,
    "regime_mode": "NORMAL",
    "regime_favor": "NEUTRE",
    "regime_actionable": 0,
    "vwap_d": 30000.0,
    "vwap_slope_10": 0.0,
    "atr": 50.0,
    "ctx_failed_auction": 0,
    "delta_div_buy_clean": 0,
    "delta_div_sell_clean": 0,
    "ib_complete": 1,
    "session_date_trading": "2026-01-15",
    "cur_pdh": 30100.0,
    "cur_pdl": 29900.0,
    "is_in_us_cash": 1,
}


def make_bar(**overrides: Any) -> dict[str, Any]:
    """Build a synthetic enriched bar with optional field overrides."""
    bar = dict(DEFAULT_BAR_FIELDS)
    bar.update(overrides)
    return bar


def make_day_bars(n: int = 60, **bar_overrides: Any) -> list[dict[str, Any]]:
    """Build a list of n bars representing a day (60 = 1h of 1-min bars)."""
    return [make_bar(ts=1780531200000 + i * 60000, **bar_overrides) for i in range(n)]
