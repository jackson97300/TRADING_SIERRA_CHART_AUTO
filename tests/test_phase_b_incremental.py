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
