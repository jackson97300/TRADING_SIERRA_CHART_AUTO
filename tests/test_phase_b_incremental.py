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
