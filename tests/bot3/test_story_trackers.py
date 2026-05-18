"""tests/bot3/test_story_trackers.py - Phase 1 TRACKING ONLY.

Tests pytest pour `CORE/bot3_story_trackers.py` (Bot 3 v2 Narrative Layer).
Coverage cible >= 90%. Pattern : mirror tests/bot3/test_*.py existants.

HISTORY
2026-05-18 : creation skeleton 7+ tests obligatoires (Phase 1 J+0 PM)
"""
from __future__ import annotations

import pickle
import threading
from dataclasses import dataclass, field

import pytest

from CORE.bot3_story_trackers import (
    StoryTrackersState,
    increment_rejection_at_level,
    update_story_trackers,
)


# ─── Stubs SwingState (mirror tests/bot3/conftest.py) ────────────────────────


@dataclass
class StubSwingPoint:
    price: float = 0.0
    bar_idx: int = -1


@dataclass
class StubSwingState:
    last_swing_high: StubSwingPoint = field(default_factory=StubSwingPoint)
    last_swing_low: StubSwingPoint = field(default_factory=StubSwingPoint)


def _make_bar(
    ts: str = "2026-05-18T13:30:00Z",
    close: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    open_: float | None = None,
    volume: int = 1000,
    sdt: str = "2026-05-18",
    session: str = "NY",
) -> dict:
    return {
        "ts_event": ts,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "close": close,
        "volume": volume,
        "session_date_trading": sdt,
        "session": session,
    }


# ════════════════════════════════════════════════════════════════════════════
# Test 1 : hh_count_60 simple trend up
# ════════════════════════════════════════════════════════════════════════════


def test_hh_count_60_simple_trend_up():
    """60 bars croissantes → hh_count_60 = 50 (avec lookback=10)."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()
    snap = None
    for i in range(60):
        snap = update_story_trackers(
            state, _make_bar(close=100.0 + i * 0.5, high=100.5 + i * 0.5), swing
        )
    assert snap is not None
    assert snap["hh_count_60"] >= 40, f"trend up strict: hh >= 40 attendu, got {snap['hh_count_60']}"
    assert snap["ll_count_60"] == 0
    assert snap["swing_progression_score"] > 0.95
    assert snap["slope_close_60"] == pytest.approx(0.5, abs=0.01)


# ════════════════════════════════════════════════════════════════════════════
# Test 2 : BOS detection canonical ICT
# ════════════════════════════════════════════════════════════════════════════


def test_bos_detection_canonical_ict_bullish():
    """ICT canonical : close > last_swing_high ET close[-1] <= last_swing_high."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0, bar_idx=5))

    # 5 bars sous 100
    for i in range(5):
        update_story_trackers(state, _make_bar(close=99.0 + 0.1 * i, high=99.5), swing)
    # Prev close 99.5
    update_story_trackers(state, _make_bar(close=99.5, high=99.8), swing)
    # BOS bar : close=100.5 > 100 ET prev=99.5 <= 100
    snap = update_story_trackers(state, _make_bar(close=100.5, high=101.0), swing)

    assert snap["bars_since_last_BOS"] == 0
    assert snap["last_BOS_dir"] == +1


def test_bos_detection_canonical_ict_bearish():
    """Mirror SHORT : close < last_swing_low ET close[-1] >= last_swing_low."""
    state = StoryTrackersState(symbol="NQ")
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0, bar_idx=5))

    for i in range(5):
        update_story_trackers(state, _make_bar(close=101.0 + 0.1 * i, low=100.5), swing)
    update_story_trackers(state, _make_bar(close=100.5, low=100.2), swing)
    snap = update_story_trackers(state, _make_bar(close=99.5, low=99.0), swing)

    assert snap["bars_since_last_BOS"] == 0
    assert snap["last_BOS_dir"] == -1


# ════════════════════════════════════════════════════════════════════════════
# Test 3 : pickle roundtrip preserves state
# ════════════════════════════════════════════════════════════════════════════


def test_pickle_roundtrip_preserves_state():
    """Pickle dump/load preserves deque + state + rejection counter.

    Critical : __getstate__ exclut _lock, __setstate__ recree.
    """
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()
    for i in range(20):
        update_story_trackers(state, _make_bar(close=100.0 + i), swing)
    increment_rejection_at_level(state, "MQ_PUT_0DTE")
    increment_rejection_at_level(state, "MQ_PUT_0DTE")
    increment_rejection_at_level(state, "GEX_DN")

    blob = pickle.dumps(state)
    loaded = pickle.loads(blob)

    assert loaded.symbol == "ES"
    assert len(loaded.bars_history) == 20
    assert loaded.rejection_count_at_level["MQ_PUT_0DTE"] == 2
    assert loaded.rejection_count_at_level["GEX_DN"] == 1
    assert loaded.n_bars_processed == 20
    assert loaded._lock is not None
    with loaded._lock:
        pass


# ════════════════════════════════════════════════════════════════════════════
# Test 4 : concurrency multi-symbol no race
# ════════════════════════════════════════════════════════════════════════════


def test_concurrency_multi_symbol_no_race():
    """2 threads ES + NQ workers 100 iter chacun. 0 race, 0 cross-pollution."""
    states = {
        "ES": StoryTrackersState(symbol="ES"),
        "NQ": StoryTrackersState(symbol="NQ"),
    }
    swings = {sym: StubSwingState() for sym in states}
    errors: list[tuple[str, Exception]] = []

    def worker(sym: str) -> None:
        try:
            for i in range(100):
                update_story_trackers(
                    states[sym], _make_bar(close=100.0 + i * 0.1), swings[sym]
                )
        except Exception as e:
            errors.append((sym, e))

    threads = [threading.Thread(target=worker, args=(sym,)) for sym in states]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"race errors: {errors}"
    assert states["ES"].n_bars_processed == 100
    assert states["NQ"].n_bars_processed == 100
    assert len(states["ES"].bars_history) == 60  # deque maxlen evict 40 FIFO
    assert len(states["NQ"].bars_history) == 60
    assert states["ES"].symbol == "ES"
    assert states["NQ"].symbol == "NQ"


# ════════════════════════════════════════════════════════════════════════════
# Test 5 : session reset (SDT change)
# ════════════════════════════════════════════════════════════════════════════


def test_session_extremes_reset_on_sdt_change():
    """Quand session_date_trading change : session_high/low + bar_idx reset."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()

    # Session 1 : 10 bars sdt=2026-05-15
    for i in range(10):
        update_story_trackers(
            state, _make_bar(close=100.0 + i, sdt="2026-05-15"), swing
        )
    snap_1 = update_story_trackers(
        state, _make_bar(close=110.0, sdt="2026-05-15"), swing
    )
    bar_idx_high_sess1 = state.bar_idx_session_high

    # Session 2 : sdt=2026-05-18 → reset session
    snap_2 = update_story_trackers(
        state, _make_bar(close=105.0, sdt="2026-05-18"), swing
    )

    assert state.current_session_date_trading == "2026-05-18"
    assert state.bar_idx_session_open == state.bar_idx_current
    # bars_since_session_high reset apres SDT change
    assert snap_2["bars_since_session_high"] == 0


# ════════════════════════════════════════════════════════════════════════════
# Test 6 : rejection_count API
# ════════════════════════════════════════════════════════════════════════════


def test_rejection_count_increments_via_external_api():
    """increment_rejection_at_level cumule par level_name."""
    state = StoryTrackersState(symbol="ES")
    increment_rejection_at_level(state, "MQ_PUT_0DTE")
    increment_rejection_at_level(state, "MQ_PUT_0DTE")
    increment_rejection_at_level(state, "MQ_PUT_0DTE")
    increment_rejection_at_level(state, "GEX_DN")

    assert state.rejection_count_at_level["MQ_PUT_0DTE"] == 3
    assert state.rejection_count_at_level["GEX_DN"] == 1
    assert "OTHER_LEVEL" not in state.rejection_count_at_level


# ════════════════════════════════════════════════════════════════════════════
# Test 7 : snapshot dict structure (contract NSM)
# ════════════════════════════════════════════════════════════════════════════


def test_snapshot_returns_all_expected_keys():
    """update_story_trackers retourne dict avec 13 keys (contract NSM)."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()
    snap = update_story_trackers(state, _make_bar(close=100.0), swing)

    expected_keys = {
        "hh_count_60",
        "ll_count_60",
        "swing_progression_score",
        "slope_close_30",
        "slope_close_60",
        "bars_since_last_BOS",
        "last_BOS_dir",
        "bars_since_session_high",
        "bars_since_session_low",
        "acceptance_zones_session",
        "rejection_count_at_level",
        "hh_count_5",
        "bars_since_open",
    }
    assert set(snap.keys()) == expected_keys


# ════════════════════════════════════════════════════════════════════════════
# Test 8 : ring buffer maxlen FIFO
# ════════════════════════════════════════════════════════════════════════════


def test_ring_buffer_evict_fifo_at_maxlen_60():
    """Input 100 bars → bars_history len capped to 60 (FIFO evict)."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()
    for i in range(100):
        update_story_trackers(state, _make_bar(close=100.0 + i), swing)
    assert len(state.bars_history) == 60
    assert state.n_bars_processed == 100
    # Oldest bar evicted : 1st bar close should be bar i=40 (since maxlen=60)
    oldest = state.bars_history[0]
    assert oldest["close"] == pytest.approx(100.0 + 40)


# ════════════════════════════════════════════════════════════════════════════
# Test 9 : slope_close_60 OLS regression accuracy
# ════════════════════════════════════════════════════════════════════════════


def test_slope_close_60_regression_ols_accuracy():
    """60 bars slope +0.5/bar → slope_close_60 ≈ 0.5 (analytic OLS)."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()
    snap = None
    for i in range(60):
        snap = update_story_trackers(state, _make_bar(close=200.0 + i * 0.5), swing)
    assert snap is not None
    assert snap["slope_close_60"] == pytest.approx(0.5, abs=0.005)


def test_slope_close_60_flat_returns_zero():
    """60 bars close=100 → slope_close_60 ≈ 0.0."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()
    snap = None
    for _ in range(60):
        snap = update_story_trackers(state, _make_bar(close=100.0), swing)
    assert snap is not None
    assert abs(snap["slope_close_60"]) < 0.001


# ════════════════════════════════════════════════════════════════════════════
# Test 10 : edge cases - input None/NaN
# ════════════════════════════════════════════════════════════════════════════


def test_handles_nan_values_gracefully():
    """Bars avec NaN high/low/close ne crashent pas."""
    state = StoryTrackersState(symbol="ES")
    swing = StubSwingState()
    # 5 bars normales
    for i in range(5):
        update_story_trackers(state, _make_bar(close=100.0 + i), swing)
    # 1 bar avec NaN
    bar_nan = _make_bar(close=float("nan"), high=float("nan"), low=float("nan"))
    snap = update_story_trackers(state, bar_nan, swing)
    # Doit pas crasher
    assert "hh_count_60" in snap
    assert "slope_close_60" in snap


def test_handles_missing_swing_state_gracefully():
    """swing_state sans last_swing_high/low ne crash pas le BOS detector."""
    state = StoryTrackersState(symbol="ES")
    swing_empty = StubSwingState()  # last_swing_high.price = 0.0 default
    swing_empty.last_swing_high = None
    swing_empty.last_swing_low = None
    snap = update_story_trackers(state, _make_bar(close=100.0), swing_empty)
    assert snap["bars_since_last_BOS"] == -1  # jamais detecte
    assert snap["last_BOS_dir"] == 0
