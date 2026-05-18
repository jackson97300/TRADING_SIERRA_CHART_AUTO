"""tests/bot3/test_narrative_state_machine.py - Tests Phase 1 NSM.

Tests pytest pour `CORE/bot3_narrative_state_machine.py`.
Coverage cible >= 90%. Tests par transition + concurrency + pickle + edge cases.

HISTORY
2026-05-18 PM : creation skeleton tests Phase 1 J+0 (30+ tests, T1-T32 selective)
"""
from __future__ import annotations

import pickle
import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from CORE.bot3_narrative_state_machine import (
    NarrativeEvent,
    NarrativeState,
    NarrativeStateMachine,
    NarrativeStateSnapshot,
)


# ─── Stubs ────────────────────────────────────────────────────────────────


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
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    atr: float = 10.0,
    vol_z: float = 0.0,
    bar_idx: int = 0,
    sdt: str = "2026-05-18",
    volume: int = 1000,
) -> dict:
    return {
        "ts_event_iso": ts,
        "ts_event": ts,
        "close": close,
        "open": open_ if open_ is not None else close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "atr": atr,
        "vol_zscore_20": vol_z,
        "bar_idx_session": bar_idx,
        "volume": volume,
        "session_date_trading": sdt,
    }


def _make_ctx(
    session: str = "ASIA",
    open_type: int = 3,
    asia_close: float = 100.0,
    asia_open: float = 100.0,
    open_cash: float = 100.0,
    prev_vah: float = 110.0,
    prev_val: float = 90.0,
    ib_complete: bool = False,
    ib_range: float = 8.0,
    inside_value_area: bool = True,
    tick_size: float = 0.25,
) -> dict:
    return {
        "session": session,
        "open_type": open_type,
        "asia_close": asia_close,
        "asia_open": asia_open,
        "open_cash": open_cash,
        "prev_vah": prev_vah,
        "prev_val": prev_val,
        "ib_complete": ib_complete,
        "ib_range": ib_range,
        "inside_value_area": inside_value_area,
        "tick_size": tick_size,
    }


# ════════════════════════════════════════════════════════════════════════════
# Cold start + base
# ════════════════════════════════════════════════════════════════════════════


def test_cold_start_seeds_pre_open_neutral():
    """1ere bar = cold start, snap = PRE_OPEN_NEUTRAL."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    snap = nsm.transition(
        "ES.c.0",
        _make_bar(close=100.0),
        _make_ctx(session="ASIA"),
        regime=None,
        story_trackers={},
        swing_state=swing,
    )
    assert snap is not None
    assert snap.symbol == "ES.c.0"
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL
    assert snap.schema_version == "2.0.0"


def test_invalid_symbol_returns_none():
    """symbol vide retourne None safe."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    snap = nsm.transition(
        "", _make_bar(), _make_ctx(), regime=None, story_trackers={}, swing_state=swing
    )
    assert snap is None


def test_current_returns_none_before_transition():
    """nsm.current(sym) avant 1er transition = None."""
    nsm = NarrativeStateMachine()
    assert nsm.current("ES.c.0") is None


# ════════════════════════════════════════════════════════════════════════════
# Transitions T2/T3 PRE_OPEN_BEARISH/BULLISH
# ════════════════════════════════════════════════════════════════════════════


def test_T2_preopen_bearish_from_neutral():
    """slope_60<-0.2 + asia_close<asia_open + session=ASIA → PRE_OPEN_BEARISH."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    snap = nsm.transition(
        "ES",
        _make_bar(close=98.0),
        _make_ctx(session="ASIA", asia_close=98.0, asia_open=100.0),
        regime=None,
        story_trackers={"slope_close_60": -0.5},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.PRE_OPEN_BEARISH
    assert snap.bias_dir == -1


def test_T3_preopen_bullish_from_neutral():
    """slope_60>+0.2 + asia_close>asia_open → PRE_OPEN_BULLISH."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    snap = nsm.transition(
        "ES",
        _make_bar(close=102.0),
        _make_ctx(session="ASIA", asia_close=102.0, asia_open=100.0),
        regime=None,
        story_trackers={"slope_close_60": +0.5},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.PRE_OPEN_BULLISH
    assert snap.bias_dir == +1


# ════════════════════════════════════════════════════════════════════════════
# Transitions T6/T7 OPEN_DRIVE_UP/DOWN (Dalton D1)
# ════════════════════════════════════════════════════════════════════════════


def test_T6_open_drive_up_from_preopen():
    """NY + open_type=0 + close>open_cash+atr + vol_z>+1 → OPEN_DRIVE_UP."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    # Bootstrap PRE_OPEN_NEUTRAL
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=111.0, atr=10.0, vol_z=1.5, bar_idx=1),
        _make_ctx(session="NY", open_type=0, open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_DRIVE_UP
    assert snap.bias_dir == +1
    assert snap.confidence == pytest.approx(0.85, abs=0.01)


def test_T7_open_drive_down_from_preopen():
    """NY + open_type=0 + close<open_cash-atr + vol_z>+1 → OPEN_DRIVE_DOWN."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=89.0, atr=10.0, vol_z=1.5, bar_idx=1),
        _make_ctx(session="NY", open_type=0, open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_DRIVE_DOWN
    assert snap.bias_dir == -1


def test_T9_open_rotation_open_type_3():
    """NY + open_type=3 (D4) → OPEN_ROTATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, bar_idx=1),
        _make_ctx(session="NY", open_type=3),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_ROTATION
    assert snap.bias_dir == 0


# ════════════════════════════════════════════════════════════════════════════
# Transitions T10/T11 TREND CONTINUATION
# ════════════════════════════════════════════════════════════════════════════


def test_T10_trend_up_continuation_from_open_drive_up():
    """OPEN_DRIVE_UP + bar_idx>30 + hh_60>=3 → TREND_UP_CONTINUATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    # Bootstrap to OPEN_DRIVE_UP
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    nsm.transition("ES", _make_bar(close=111.0, atr=10.0, vol_z=1.5, bar_idx=5),
                   _make_ctx(session="NY", open_type=0, open_cash=100.0),
                   regime=None, story_trackers={}, swing_state=swing)
    assert nsm.current("ES").state == NarrativeState.OPEN_DRIVE_UP

    # Next : bar_idx=35 + hh_60=5
    snap = nsm.transition(
        "ES",
        _make_bar(close=120.0, bar_idx=35),
        _make_ctx(session="NY"),
        regime=None,
        story_trackers={"hh_count_60": 5},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_UP_CONTINUATION


# ════════════════════════════════════════════════════════════════════════════
# Transitions T22 WYCKOFF SPRING (canonical Wyckoff Phase C)
# ════════════════════════════════════════════════════════════════════════════


def test_T22_wyckoff_spring_long_canonical():
    """low<=swing_low + close>swing_low+2*tick + vol_z>1.5 + bars_since_BOS>5
    → WYCKOFF_SPRING_LONG."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    # Bootstrap
    nsm.transition("ES", _make_bar(close=101.0), _make_ctx(session="LONDON"),
                   regime=None,
                   story_trackers={"bars_since_last_BOS": 20},
                   swing_state=swing)
    # Spring : low=99 <= 100 swing_low, close=100.6 > 100 + 2*0.25
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.6, low=99.0, vol_z=2.0, atr=5.0),
        _make_ctx(session="LONDON", tick_size=0.25),
        regime=None,
        story_trackers={"bars_since_last_BOS": 20},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.WYCKOFF_SPRING_LONG
    assert snap.bias_dir == +1


def test_T23_wyckoff_upthrust_short_canonical():
    """high>=swing_high + close<swing_high-2*tick + vol_z>1.5 + bars_since_BOS>5
    → WYCKOFF_UPTHRUST_SHORT."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    nsm.transition("ES", _make_bar(close=99.0), _make_ctx(session="LONDON"),
                   regime=None,
                   story_trackers={"bars_since_last_BOS": 20},
                   swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=99.4, high=101.0, vol_z=2.0, atr=5.0),
        _make_ctx(session="LONDON", tick_size=0.25),
        regime=None,
        story_trackers={"bars_since_last_BOS": 20},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.WYCKOFF_UPTHRUST_SHORT
    assert snap.bias_dir == -1


def test_T22_no_spring_if_BOS_too_recent():
    """bars_since_BOS<=5 = pas de Spring (anti faux-positif data sale)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    nsm.transition("ES", _make_bar(close=101.0), _make_ctx(session="LONDON"),
                   regime=None, story_trackers={"bars_since_last_BOS": 3},
                   swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.6, low=99.0, vol_z=2.0, atr=5.0),
        _make_ctx(session="LONDON", tick_size=0.25),
        regime=None,
        story_trackers={"bars_since_last_BOS": 3},  # too recent
        swing_state=swing,
    )
    assert snap.state != NarrativeState.WYCKOFF_SPRING_LONG


# ════════════════════════════════════════════════════════════════════════════
# Transitions T28/T29 EXHAUSTION (Wyckoff Buying Climax)
# ════════════════════════════════════════════════════════════════════════════


def test_T28_exhaustion_top_from_trend_up():
    """TREND_UP + vol_z>2.5 + close<open + bar_range>2*atr → EXHAUSTION_TOP."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    # Force state TREND_UP_CONTINUATION manually
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    state = nsm._states["ES"]
    state.state = NarrativeState.TREND_UP_CONTINUATION

    # Exhaustion bar : vol_z=3.0, close=99 < open=110, range=20 > 2*atr=10
    snap = nsm.transition(
        "ES",
        _make_bar(close=99.0, open_=110.0, high=110.0, low=90.0, atr=5.0, vol_z=3.0),
        _make_ctx(session="NY"),
        regime=None,
        story_trackers={},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.EXHAUSTION_TOP
    assert snap.bias_dir == -1


# ════════════════════════════════════════════════════════════════════════════
# Anti-flicker guard
# ════════════════════════════════════════════════════════════════════════════


def test_flicker_guard_blocks_after_8_transitions():
    """>8 transitions/jour/sym = block + log BOT3_NSM_FLICKER_GUARD."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    # Force 9 transitions
    nsm._states["ES"].n_transitions_today = 9

    # Capture les logs emit
    captured: list[tuple[str, dict]] = []
    def cap(code, **ctx):
        captured.append((code, ctx))

    snap = nsm.transition(
        "ES",
        _make_bar(close=98.0, bar_idx=1),
        _make_ctx(session="ASIA", asia_close=98.0, asia_open=100.0),
        regime=None,
        story_trackers={"slope_close_60": -0.5},
        swing_state=swing,
        log_fn=cap,
    )
    # State NE doit PAS transitioner (flicker block)
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL
    # Log FLICKER_GUARD emit
    assert any(c == "BOT3_NSM_FLICKER_GUARD" for c, _ in captured)


# ════════════════════════════════════════════════════════════════════════════
# Session reset
# ════════════════════════════════════════════════════════════════════════════


def test_session_reset_clears_n_transitions_today():
    """SDT change = reset n_transitions_today + emit SESSION_RESET."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    captured: list[str] = []
    def cap(code, **ctx):
        captured.append(code)

    nsm.transition("ES", _make_bar(close=100.0, sdt="2026-05-15"),
                   _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing, log_fn=cap)
    nsm._states["ES"].n_transitions_today = 5
    nsm.transition("ES", _make_bar(close=100.0, sdt="2026-05-18"),
                   _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing, log_fn=cap)

    assert nsm._states["ES"].n_transitions_today == 0
    assert nsm._states["ES"].current_session_date_trading == "2026-05-18"
    assert "BOT3_NSM_SESSION_RESET" in captured


# ════════════════════════════════════════════════════════════════════════════
# Events buffer
# ════════════════════════════════════════════════════════════════════════════


def test_events_consumed_once_then_empty():
    """consume_events() vide la liste, idempotent."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    nsm.transition("ES", _make_bar(close=98.0, bar_idx=1),
                   _make_ctx(session="ASIA", asia_close=98.0, asia_open=100.0),
                   regime=None, story_trackers={"slope_close_60": -0.5}, swing_state=swing)
    e1 = nsm.consume_events()
    e2 = nsm.consume_events()
    assert len(e1) >= 1
    assert e2 == []


def test_transition_event_has_correct_metadata():
    """NarrativeEvent payload contient from/to/bias/confidence."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    nsm.transition("ES", _make_bar(close=98.0, bar_idx=1),
                   _make_ctx(session="ASIA", asia_close=98.0, asia_open=100.0),
                   regime=None, story_trackers={"slope_close_60": -0.5}, swing_state=swing)
    events = nsm.consume_events()
    transitions = [e for e in events if e.event_type == "STATE_TRANSITION"]
    assert len(transitions) >= 1
    evt = transitions[0]
    assert evt.from_state == NarrativeState.PRE_OPEN_NEUTRAL
    assert evt.to_state == NarrativeState.PRE_OPEN_BEARISH
    assert evt.payload["bias_dir"] == -1
    assert evt.symbol == "ES"


# ════════════════════════════════════════════════════════════════════════════
# Pickle roundtrip + concurrency
# ════════════════════════════════════════════════════════════════════════════


def test_pickle_roundtrip_preserves_multi_symbol_state():
    """Pickle dump/load preserves all symbol states + _locks recreate."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    for sym in ("ES.c.0", "NQ.c.0", "MGC.v.0"):
        for i in range(3):
            nsm.transition(sym, _make_bar(close=100.0 + i, bar_idx=i),
                           _make_ctx(session="ASIA"),
                           regime=None, story_trackers={}, swing_state=swing)

    blob = pickle.dumps(nsm)
    loaded = pickle.loads(blob)

    for sym in ("ES.c.0", "NQ.c.0", "MGC.v.0"):
        snap = loaded.current(sym)
        assert snap is not None
        assert snap.symbol == sym
        assert snap.bar_idx_current == 3
    # _locks recree (lazy)
    assert loaded._get_lock("ES.c.0") is not None


def test_concurrency_multi_symbol_no_race():
    """2 threads ES + NQ workers 50 iter chacun, 0 race, 0 cross-pollution."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    errors: list[tuple[str, Exception]] = []

    def worker(sym: str) -> None:
        try:
            for i in range(50):
                nsm.transition(
                    sym, _make_bar(close=100.0 + i * 0.1, bar_idx=i),
                    _make_ctx(session="ASIA"),
                    regime=None, story_trackers={}, swing_state=swing,
                )
        except Exception as e:
            errors.append((sym, e))

    threads = [
        threading.Thread(target=worker, args=("ES",)),
        threading.Thread(target=worker, args=("NQ",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"race errors: {errors}"
    es = nsm.current("ES")
    nq = nsm.current("NQ")
    assert es is not None
    assert nq is not None
    assert es.symbol == "ES"
    assert nq.symbol == "NQ"
    # Isolation : ES != NQ same state ne signifie pas cross-pollution
    assert es.bar_idx_current == 50
    assert nq.bar_idx_current == 50


# ════════════════════════════════════════════════════════════════════════════
# Edge cases
# ════════════════════════════════════════════════════════════════════════════


def test_handles_missing_swing_state_gracefully():
    """swing_state None ou pas .last_swing_high/low ne crash pas."""
    nsm = NarrativeStateMachine()
    swing_none = None
    snap = nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                          regime=None, story_trackers={}, swing_state=swing_none)
    assert snap is not None
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL


def test_handles_nan_values_gracefully():
    """Bars avec NaN ne crashent pas."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    snap = nsm.transition(
        "ES",
        _make_bar(close=float("nan"), high=float("nan"), low=float("nan"),
                  atr=float("nan"), vol_z=float("nan")),
        _make_ctx(session="ASIA"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap is not None  # cold start malgre NaN


def test_invalidated_state_resets_on_sdt_change():
    """T32 : INVALIDATED + sdt change → PRE_OPEN_NEUTRAL."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    # Force INVALIDATED
    nsm.transition("ES", _make_bar(close=100.0, sdt="2026-05-15"),
                   _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    nsm._states["ES"].state = NarrativeState.INVALIDATED
    nsm._states["ES"].current_session_date_trading = "2026-05-15"
    # SDT change
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, sdt="2026-05-18"),
        _make_ctx(session="ASIA"),
        regime=None,
        story_trackers={},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL


def test_invalidated_state_stays_within_same_sdt():
    """INVALIDATED reste tant que sdt n'a pas change (anti instant recovery)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0, sdt="2026-05-18"),
                   _make_ctx(session="LONDON"),
                   regime=None, story_trackers={}, swing_state=swing)
    nsm._states["ES"].state = NarrativeState.INVALIDATED
    nsm._states["ES"].current_session_date_trading = "2026-05-18"

    snap = nsm.transition(
        "ES",
        _make_bar(close=100.5, sdt="2026-05-18"),
        _make_ctx(session="LONDON"),
        regime=None,
        story_trackers={},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.INVALIDATED


# ════════════════════════════════════════════════════════════════════════════
# Snapshot structure (contract DirectionResolver Phase 3)
# ════════════════════════════════════════════════════════════════════════════


def test_snapshot_has_all_required_fields():
    """NarrativeStateSnapshot contient tous les fields requis pour Phase 3."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.current("ES")
    assert snap.schema_version
    assert snap.symbol == "ES"
    assert snap.state in NarrativeState
    assert snap.bar_idx_current >= 0
    assert snap.bias_dir in (-1, 0, +1)
    assert 0.0 <= snap.confidence <= 1.0
    assert isinstance(snap.triggering_features, dict)
    assert isinstance(snap.engine_states, dict)


def test_bar_idx_current_increments():
    """bar_idx_current increment monotone par symbol."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    for i in range(5):
        nsm.transition("ES", _make_bar(close=100.0 + i), _make_ctx(session="ASIA"),
                       regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.current("ES")
    assert snap.bar_idx_current == 5


def test_prev_close_tracked_in_engine_states():
    """prev_close tracke dans engine_states pour BOS detection T20/T21."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=99.5), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.current("ES")
    assert snap.engine_states.get("prev_close") == 99.5
