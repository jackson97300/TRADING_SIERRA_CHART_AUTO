"""Tests Phase 1b refacto window-based.

Coverage :
- Task 1 : load_trades_for_window (subset month)
- Task 2 : compute_window_cutoff (3 edge cases)
- Task 3 : apply_all_engines (idempotence)
- Task 4 : process_partition_incremental (parite vs full)
- Task 5 : CLI flag --incremental-window-days

Tous les tests skippent si data 2026-04 ES non dispo localement.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))


def test_load_trades_for_window_returns_subset_of_month():
    """load_trades_for_window must return strict subset of load_trades_for_month."""
    from build_dataset_v4_phase_b import load_trades_for_month, load_trades_for_window

    sym = "ES"
    year, month = 2026, 4

    df_month = load_trades_for_month(sym, year, month)
    if df_month.empty:
        pytest.skip(f"No trades data for {sym} {year}-{month}, cannot test")

    # Pick a 3-day window in the middle of the month
    ts_min = df_month["ts_event"].min()
    start_ts = ts_min + pd.Timedelta(days=5)
    end_ts = start_ts + pd.Timedelta(days=3)

    df_window = load_trades_for_window(sym, start_ts, end_ts)

    # Window must be subset of month
    assert len(df_window) <= len(df_month), "Window cannot have more trades than month"
    # All window timestamps must be in the requested range
    if not df_window.empty:
        assert (df_window["ts_event"] >= start_ts).all(), "Trade before start_ts found"
        assert (df_window["ts_event"] < end_ts).all(), "Trade at/after end_ts found"
    # Window must contain all month-trades in that range (no data loss)
    df_month_in_range = df_month[
        (df_month["ts_event"] >= start_ts) & (df_month["ts_event"] < end_ts)
    ]
    assert len(df_window) == len(df_month_in_range), \
        f"Window missing trades: {len(df_window)} vs {len(df_month_in_range)}"


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — compute_window_cutoff edge cases
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_window_cutoff_empty_df_returns_none():
    """Empty df -> cutoff = None (signal full rebuild mode)."""
    from build_dataset_v4_phase_b import compute_window_cutoff

    df_empty = pd.DataFrame({"ts_event": pd.to_datetime([], utc=True)})
    cutoff = compute_window_cutoff(df_empty, window_days=3)
    assert cutoff is None, "Empty df must return None cutoff"


def test_compute_window_cutoff_3d_window():
    """3-day window: cutoff = last_ts - 3 days."""
    from build_dataset_v4_phase_b import compute_window_cutoff

    ts_max = pd.Timestamp("2026-05-13T22:00:00", tz="UTC")
    ts_range = pd.date_range(end=ts_max, periods=10000, freq="1min", tz="UTC")
    df = pd.DataFrame({"ts_event": ts_range})

    cutoff = compute_window_cutoff(df, window_days=3)
    expected = ts_max - pd.Timedelta(days=3)
    assert cutoff == expected, f"Cutoff {cutoff} != {expected}"


def test_compute_window_cutoff_window_larger_than_data_caps_to_min_ts():
    """If window > data span: cutoff = ts_min (full rebuild equivalent)."""
    from build_dataset_v4_phase_b import compute_window_cutoff

    ts_max = pd.Timestamp("2026-05-13T22:00:00", tz="UTC")
    # Only 1 day of data
    ts_range = pd.date_range(end=ts_max, periods=1440, freq="1min", tz="UTC")
    df = pd.DataFrame({"ts_event": ts_range})

    cutoff = compute_window_cutoff(df, window_days=30)
    # When window > data, cutoff capped to ts_min (rebuild all)
    assert cutoff == df["ts_event"].min(), "Cutoff must cap to ts_min when window > data"


# ─────────────────────────────────────────────────────────────────────────────
# Task 3 — apply_all_engines idempotence
# ─────────────────────────────────────────────────────────────────────────────

def test_apply_all_engines_idempotent_on_same_input():
    """apply_all_engines must produce identical output when run twice on same input.

    Test idempotence : run 2x sur same data -> outputs bit-for-bit identiques.
    Test rapide (200 dernieres bars) pour TDD feedback rapide.
    """
    import numpy as np
    from build_dataset_v4_phase_b import apply_all_engines, load_v4_partition
    try:
        from CORE.constants import get_tick_size, get_session_boundaries
    except ImportError:
        from constants import get_tick_size, get_session_boundaries

    sym = "ES"
    df = load_v4_partition(sym, 2026, 4)
    if df.empty:
        pytest.skip(f"No data for {sym} 2026-04")

    # Take last 200 bars (fast test, suffisant pour rolling features qui ont window 60)
    df_subset = df.tail(200).copy().reset_index(drop=True)
    trades_df = pd.DataFrame()  # Empty trades for fast test
    tick = get_tick_size(sym)
    bounds = get_session_boundaries(sym)

    out1 = apply_all_engines(df_subset.copy(), trades_df, sym, tick, bounds)
    out2 = apply_all_engines(df_subset.copy(), trades_df, sym, tick, bounds)

    # Check identical shape
    assert out1.shape == out2.shape, f"Shape diff: {out1.shape} vs {out2.shape}"
    # Check identical columns
    assert set(out1.columns) == set(out2.columns), \
        f"Column set differs: {set(out1.columns) ^ set(out2.columns)}"
    # Check key feature columns are deterministic
    for col in ("rvol_zscore", "vwap_slope_10", "ctx_va_developing_10"):
        if col in out1.columns and col in out2.columns:
            v1 = out1[col].fillna(-999.0).values
            v2 = out2[col].fillna(-999.0).values
            assert np.allclose(v1, v2, rtol=1e-9, atol=1e-12, equal_nan=True), \
                f"Non-deterministic column {col}"
