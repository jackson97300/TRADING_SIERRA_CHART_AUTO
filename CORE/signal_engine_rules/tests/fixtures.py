"""Shared synthetic bar fixtures for rule tests.

Builds dict[str, Any] features matching v5b parquet schema for tests.
NO REAL DATA — all values are deterministic, hand-crafted to trigger or
not-trigger specific rules.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_bar_base(ts_event: str = "2026-04-27 14:30:00") -> dict:
    """Base bar with all common features set to neutral/safe defaults.

    Use as base, override specific fields per test.
    """
    return {
        "ts_event": pd.Timestamp(ts_event, tz="UTC"),
        "high": 4500.0, "low": 4499.0, "close": 4499.5, "open": 4499.5,
        "atr": 5.0,  # ticks
        "is_in_us_cash": 1,  # default RTH
        "mins_et": 600,  # default 10:00 ET (post-IB-window=630 false; cash session true 570-960)
        "delta_day_dir": 1,
        # Long bar features
        "long_up_bar": 0, "long_dn_bar": 0,
        "long_up_dn_pattern": 0, "long_dn_up_pattern": 0,
        # Color zones
        "dist_color_up_nearest_pct": 0.5, "dist_color_dn_nearest_pct": -0.5,
        # Cluster
        "cluster_at_high": 0, "cluster_at_low": 0,
        # IB
        "ib_broken_up": 0, "ib_broken_down": 0, "ib_position_pct": 0.5,
        # Edge zones
        "bar_edge_buy_fire": 0, "bar_edge_sell_fire": 0,
    }


def make_bar_long_up_rth() -> dict:
    """Bar that should fire long_up_bar (long up bar in RTH)."""
    bar = make_bar_base()
    bar["long_up_bar"] = 1
    bar["is_in_us_cash"] = 1
    return bar


def make_bar_long_up_outside_rth() -> dict:
    """Bar long_up_bar but OUTSIDE RTH (should NOT fire)."""
    bar = make_bar_base()
    bar["long_up_bar"] = 1
    bar["is_in_us_cash"] = 0
    return bar


def make_bar_color_up_close() -> dict:
    """Bar very close to color_up zone with positive delta (fires color_up_proximity)."""
    bar = make_bar_base()
    bar["dist_color_up_nearest_pct"] = 0.0003  # 0.03% < threshold 0.05%
    bar["delta_day_dir"] = 1
    return bar


def make_bar_color_up_far() -> dict:
    """Bar far from color_up (should NOT fire)."""
    bar = make_bar_base()
    bar["dist_color_up_nearest_pct"] = 0.5  # far
    bar["delta_day_dir"] = 1
    return bar


def make_bar_failed_ib_pre_close() -> dict:
    """Failed IB pattern but BEFORE 10:30 ET (anti-leak: must NOT fire)."""
    bar = make_bar_base()
    bar["mins_et"] = 600  # 10:00 ET, before 10:30
    bar["ib_broken_up"] = 1
    bar["ib_position_pct"] = 0.0  # back inside IB
    return bar


def make_bar_failed_ib_post_close() -> dict:
    """Failed IB pattern AFTER 10:30 ET (fires SHORT)."""
    bar = make_bar_base()
    bar["mins_et"] = 700  # 11:40 ET, post-IB
    bar["ib_broken_up"] = 1
    bar["ib_position_pct"] = 0.0  # back inside IB
    return bar


def make_bar_cluster_at_low() -> dict:
    """Bar with cluster_at_low + delta dir up → fires BUY."""
    bar = make_bar_base()
    bar["cluster_at_low"] = 1
    bar["delta_day_dir"] = 1
    return bar


def make_bar_edge_buy() -> dict:
    """Bar with bar_edge_buy_fire=1 → fires BUY."""
    bar = make_bar_base()
    bar["bar_edge_buy_fire"] = 1
    return bar


def make_bar_with_nan(rule_field: str) -> dict:
    """Bar with NaN on critical feature for given rule."""
    bar = make_bar_base()
    bar[rule_field] = np.nan
    return bar


def make_dataframe_from_bars(bars: list[dict]) -> pd.DataFrame:
    """Helper: build a DataFrame from list of bar dicts."""
    return pd.DataFrame(bars)
