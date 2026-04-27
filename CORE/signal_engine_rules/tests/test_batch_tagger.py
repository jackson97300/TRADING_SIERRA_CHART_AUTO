"""Tests batch_tagger.py — apply rules to parquet → enriched parquet."""
import pandas as pd
import pytest

from CORE.signal_engine_rules.batch_tagger import apply_rules_to_dataframe
from CORE.signal_engine_rules.tests.fixtures import (
    make_bar_long_up_rth, make_bar_color_up_close, make_bar_base,
)


RULE_NAMES = [
    "long_up_bar", "long_dn_bar", "color_up_proximity", "color_dn_proximity",
    "color_zone_break", "cluster_at_high", "cluster_at_low",
    "failed_ib_poor_high", "edge_zone_fire",
]


def test_apply_rules_adds_18_columns():
    """Each of 9 rules adds 2 cols: <name>_dir + <name>_strength."""
    bars = [make_bar_base(), make_bar_long_up_rth(), make_bar_color_up_close()]
    df = pd.DataFrame(bars)
    df_out = apply_rules_to_dataframe(df)
    expected_cols = []
    for rule_name in RULE_NAMES:
        expected_cols.append(f"rule_{rule_name}_dir")
        expected_cols.append(f"rule_{rule_name}_strength")
    for col in expected_cols:
        assert col in df_out.columns, f"Missing column {col}"
    assert df_out.shape[0] == len(bars)


def test_apply_rules_long_up_fires_correctly():
    """long_up_bar bar in RTH → rule_long_up_bar_dir == 1."""
    bars = [make_bar_long_up_rth(), make_bar_base()]
    df = pd.DataFrame(bars)
    df_out = apply_rules_to_dataframe(df)
    assert df_out.iloc[0]["rule_long_up_bar_dir"] == 1
    assert df_out.iloc[1]["rule_long_up_bar_dir"] == 0


def test_apply_rules_dtype_int8_for_dir():
    bars = [make_bar_base() for _ in range(10)]
    df = pd.DataFrame(bars)
    df_out = apply_rules_to_dataframe(df)
    assert df_out["rule_long_up_bar_dir"].dtype == "int8"
    assert df_out["rule_long_up_bar_strength"].dtype == "float32"


def test_apply_rules_preserves_original_columns():
    bars = [make_bar_base() for _ in range(3)]
    df = pd.DataFrame(bars)
    original_cols = set(df.columns)
    df_out = apply_rules_to_dataframe(df)
    assert original_cols.issubset(set(df_out.columns))


def test_apply_rules_handles_empty_dataframe():
    df = pd.DataFrame(columns=["close", "high", "low", "ts_event", "atr"])
    df_out = apply_rules_to_dataframe(df)
    assert len(df_out) == 0
    # Still has new rule columns
    assert "rule_long_up_bar_dir" in df_out.columns


def test_apply_rules_computes_mins_et_when_absent():
    """Anomaly fix 27/04: parquet v5b has no mins_et col. batch_tagger must
    compute it from ts_event for failed_ib_poor_high anti-leak guard."""
    bars = [{
        "ts_event": pd.Timestamp("2026-04-27 14:30:00", tz="UTC"),  # 10:30 ET = 630
        "high": 4500.0, "low": 4499.0, "close": 4499.5, "open": 4499.5, "atr": 5.0,
        "is_in_us_cash": 1, "delta_day_dir": 1,
        "long_up_bar": 0, "long_dn_bar": 0,
        "dist_color_up_nearest_pct": -0.5, "dist_color_dn_nearest_pct": 0.5,
        "cluster_at_high": 0, "cluster_at_low": 0,
        "ib_broken_up": 1, "ib_broken_dn": 0, "ib_position_pct": 0.5,
        "bar_edge_buy_fire": 0, "bar_edge_sell_fire": 0,
    }]
    df = pd.DataFrame(bars)
    assert "mins_et" not in df.columns  # ensure absent in input

    df_out = apply_rules_to_dataframe(df)
    # Should compute mins_et and trigger failed_ib_poor_high (br_up + pos < 1.0 + post-IB)
    assert "mins_et" in df_out.columns, "batch_tagger must compute mins_et from ts_event"
    assert df_out.iloc[0]["mins_et"] == 630, f"Expected 630 (10:30 ET), got {df_out.iloc[0]['mins_et']}"
    assert df_out.iloc[0]["rule_failed_ib_poor_high_dir"] == -1, \
        "failed_ib_poor_high should fire SHORT (broken_up + pos<1)"
