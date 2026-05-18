"""tests/bot3/conftest.py — Fixtures partagees Bot 3 v2 Narrative Layer.

Phase 1 scope (TRACKING ONLY). Stubs minimaux pour decouples tests par module.
Pas de mock impossible (file mtime OS).
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pytest


# ─── Stubs RegimeSnapshot (output regime_engine.compute_regime) ──────────────


@dataclass
class StubRegime:
    """Stub minimal de RegimeSnapshot pour tests NSM + StoryTrackers."""

    mode: str = "NEUTRAL"  # TREND_UP / TREND_DOWN / RANGE / NEUTRAL
    favor: int = 0  # -1, 0, +1
    is_actionable: bool = True
    vol_bucket: str = "MED"  # LOW / MED / HIGH / EXTREME
    confidence_score: float = 0.6


@pytest.fixture
def stub_regime():
    """Factory function returning fresh StubRegime instance."""
    return StubRegime


# ─── Stubs SwingState (output sessions_swings_lag_streaming) ─────────────────


@dataclass
class StubSwingPoint:
    price: float = 0.0
    bar_idx: int = -1


@dataclass
class StubSwingState:
    last_swing_high: StubSwingPoint = field(default_factory=StubSwingPoint)
    last_swing_low: StubSwingPoint = field(default_factory=StubSwingPoint)


@pytest.fixture
def stub_swings():
    """Factory function returning fresh StubSwingState instance."""
    def _make(last_high: float = 5900.0, last_low: float = 5800.0,
              hi_bar_idx: int = -1, lo_bar_idx: int = -1) -> StubSwingState:
        return StubSwingState(
            last_swing_high=StubSwingPoint(price=last_high, bar_idx=hi_bar_idx),
            last_swing_low=StubSwingPoint(price=last_low, bar_idx=lo_bar_idx),
        )
    return _make


# ─── Stubs StoryTrackerSnapshot (output bot3_story_trackers) ─────────────────


@dataclass
class StubStoryTrackers:
    """Stub minimal StoryTrackersState pour tests NSM isole."""

    hh_count_60: int = 0
    ll_count_60: int = 0
    hh_count_5: int = 0
    bars_since_BOS: int = 999
    last_BOS_dir: int = 0
    bars_since_session_high: int = 0
    bars_since_session_low: int = 0
    slope_close_30: float = 0.0
    slope_close_60: float = 0.0
    swing_progression_score: float = 0.0
    acceptance_zones: list = field(default_factory=list)
    rejection_count_at_level: dict = field(default_factory=dict)


@pytest.fixture
def stub_story():
    """Factory function returning fresh StubStoryTrackers instance."""
    return StubStoryTrackers


# ─── Bar / ctx helpers (snapshots V4 enriched canonical-like) ────────────────


def _bar(
    close: float = 5850.0,
    ts: str = "2026-05-18T08:00:00Z",
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    atr: float = 10.0,
    vol_zscore_20: float = 0.0,
    bar_idx: int = 0,
    instrument_id: int = 42004058,
    delta_bar: float = 0.0,
    volume: int = 100,
    cvd_day: float = 0.0,
    mq_1d_max: float = 6000.0,
    mq_1d_min: float = 5700.0,
    sess_high: float = 5900.0,
    sess_low: float = 5800.0,
    session_date_trading: str = "2026-05-18",
    mins_et: int = 480,  # 08:00 ET = pre-RTH
) -> dict:
    """Stub bar V4 enriched canonical minimal."""
    return {
        "ts_event_iso": ts,
        "ts_event": ts,
        "close": close,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close + 1,
        "low": low if low is not None else close - 1,
        "atr": atr,
        "vol_zscore_20": vol_zscore_20,
        "bar_idx_session": bar_idx,
        "instrument_id": instrument_id,
        "delta_bar": delta_bar,
        "volume": volume,
        "cvd_day": cvd_day,
        "mq_1d_max": mq_1d_max,
        "mq_1d_min": mq_1d_min,
        "sess_high": sess_high,
        "sess_low": sess_low,
        "session_date_trading": session_date_trading,
        "mins_et": mins_et,
    }


def _ctx(
    session: str = "ASIA",
    open_type: int = 3,
    ib_complete: bool = False,
    ib_range_atr: float = 0.8,
    asia_close: float = 5850.0,
    asia_open: float = 5850.0,
    london_close: float = 5850.0,
    london_open: float = 5850.0,
    inside_value_area: bool = True,
    open_cash: float = 5850.0,
    prev_vah: float = 5870.0,
    prev_val: float = 5830.0,
    tick_size: float = 0.25,
    **kw: Any,
) -> dict:
    """Stub ctx output `bot3_context_analyzer.analyze_context`."""
    return {
        "session": session,
        "open_type": open_type,
        "ib_complete": ib_complete,
        "ib_range_atr": ib_range_atr,
        "asia_close": asia_close,
        "asia_open": asia_open,
        "london_close": london_close,
        "london_open": london_open,
        "inside_value_area": inside_value_area,
        "open_cash": open_cash,
        "prev_vah": prev_vah,
        "prev_val": prev_val,
        "tick_size": tick_size,
        **kw,
    }


@pytest.fixture
def bar_factory():
    """Factory function pour bars de test."""
    return _bar


@pytest.fixture
def ctx_factory():
    """Factory function pour ctx dicts de test."""
    return _ctx
