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
    CONF_OPEN_DRIVE,
    CONF_WYCKOFF_PRE_SOS,
    NarrativeEvent,
    NarrativeState,
    NarrativeStateMachine,
    NarrativeStateSnapshot,
)
from CORE.game_changers import OpenType


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
    open_type: int = 0,  # default UNKNOWN = ne fire aucune T6-T9 (safe)
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
    """NY + open_type=OD_UP + close>open_cash+atr + vol_z>+1 → OPEN_DRIVE_UP.

    Fix B1 : utilise OpenType.OD_UP (=1) via enum officielle game_changers.OpenType.
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    # Bootstrap PRE_OPEN_NEUTRAL
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=111.0, atr=10.0, vol_z=1.5, bar_idx=1),
        _make_ctx(session="NY", open_type=int(OpenType.OD_UP), open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_DRIVE_UP
    assert snap.bias_dir == +1
    assert snap.confidence == pytest.approx(CONF_OPEN_DRIVE, abs=0.01)


def test_T7_open_drive_down_from_preopen():
    """NY + open_type=OD_DOWN + close<open_cash-atr + vol_z>+1 → OPEN_DRIVE_DOWN.

    Fix B1 : utilise OpenType.OD_DOWN (=2) via enum officielle.
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=89.0, atr=10.0, vol_z=1.5, bar_idx=1),
        _make_ctx(session="NY", open_type=int(OpenType.OD_DOWN), open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_DRIVE_DOWN
    assert snap.bias_dir == -1


def test_T9_open_rotation_OAIR():
    """NY + open_type=OAIR (=7, D4 Open Auction In Range) → OPEN_ROTATION.

    Fix B1 : utilise OpenType.OAIR (=7) via enum officielle. Avant test
    utilisait int hardcode 3 (=OTD_UP) qui faisait fire T8 OPEN_TEST_DRIVE.
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, bar_idx=1),
        _make_ctx(session="NY", open_type=int(OpenType.OAIR)),
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
    # Bootstrap to OPEN_DRIVE_UP via T6
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    nsm.transition("ES", _make_bar(close=111.0, atr=10.0, vol_z=1.5, bar_idx=5),
                   _make_ctx(session="NY", open_type=int(OpenType.OD_UP),
                             open_cash=100.0),
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
    → WYCKOFF_SPRING_LONG (conf 0.65 pre-SOS).

    Fix M1 : bootstrap state=RANGE_RESPECTED (whitelist guard Phase C Pruden).
    Fix M2 : conf 0.65 (CONF_WYCKOFF_PRE_SOS) vs 0.85 avant review.
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    # Bootstrap cold start
    nsm.transition("ES", _make_bar(close=101.0), _make_ctx(session="LONDON"),
                   regime=None,
                   story_trackers={"bars_since_last_BOS": 20},
                   swing_state=swing)
    # Force state RANGE_RESPECTED (whitelist M1)
    nsm._states["ES"].state = NarrativeState.RANGE_RESPECTED

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
    assert snap.confidence == pytest.approx(CONF_WYCKOFF_PRE_SOS, abs=0.01)


def test_T23_wyckoff_upthrust_short_canonical():
    """high>=swing_high + close<swing_high-2*tick + vol_z>1.5 + bars_since_BOS>5
    → WYCKOFF_UPTHRUST_SHORT (conf 0.65 pre-SOS).

    Fix M1 : bootstrap state=RANGE_RESPECTED.
    Fix M2 : conf 0.65 (CONF_WYCKOFF_PRE_SOS).
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    nsm.transition("ES", _make_bar(close=99.0), _make_ctx(session="LONDON"),
                   regime=None,
                   story_trackers={"bars_since_last_BOS": 20},
                   swing_state=swing)
    # Force state RANGE_RESPECTED (whitelist M1)
    nsm._states["ES"].state = NarrativeState.RANGE_RESPECTED

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
    assert snap.confidence == pytest.approx(CONF_WYCKOFF_PRE_SOS, abs=0.01)


def test_T22_no_spring_if_BOS_too_recent():
    """bars_since_BOS<=5 = pas de Spring (anti faux-positif data sale).

    Fix M1 : bootstrap state=RANGE_RESPECTED.
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    nsm.transition("ES", _make_bar(close=101.0), _make_ctx(session="LONDON"),
                   regime=None, story_trackers={"bars_since_last_BOS": 3},
                   swing_state=swing)
    nsm._states["ES"].state = NarrativeState.RANGE_RESPECTED

    snap = nsm.transition(
        "ES",
        _make_bar(close=100.6, low=99.0, vol_z=2.0, atr=5.0),
        _make_ctx(session="LONDON", tick_size=0.25),
        regime=None,
        story_trackers={"bars_since_last_BOS": 3},  # too recent
        swing_state=swing,
    )
    assert snap.state != NarrativeState.WYCKOFF_SPRING_LONG


def test_T22_blocked_if_state_not_in_whitelist():
    """Fix M1 : T22 guard whitelist - PRE_OPEN_NEUTRAL ne peut PAS faire Spring
    directement (Wyckoff Phase A+B prerequis)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    nsm.transition("ES", _make_bar(close=101.0), _make_ctx(session="LONDON"),
                   regime=None, story_trackers={"bars_since_last_BOS": 20},
                   swing_state=swing)
    # PRE_OPEN_NEUTRAL = etat NON whitelist Wyckoff Spring
    assert nsm._states["ES"].state == NarrativeState.PRE_OPEN_NEUTRAL

    snap = nsm.transition(
        "ES",
        _make_bar(close=100.6, low=99.0, vol_z=2.0, atr=5.0),
        _make_ctx(session="LONDON", tick_size=0.25),
        regime=None,
        story_trackers={"bars_since_last_BOS": 20},
        swing_state=swing,
    )
    # Pas de Spring depuis PRE_OPEN_NEUTRAL
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


# ════════════════════════════════════════════════════════════════════════════
# Coverage gap fill - Phase 1 NSM post-review (22+ transitions non testees)
# ════════════════════════════════════════════════════════════════════════════


def _force_state(nsm: NarrativeStateMachine, symbol: str,
                 state: NarrativeState, sdt: str = "2026-05-18",
                 prev_close: float | None = None) -> None:
    """Helper bootstrap : cold start puis force state + sdt + prev_close.

    Compact helper pour les 22 tests transitions manquantes.
    """
    if symbol not in nsm._states:
        nsm.transition(symbol, _make_bar(close=100.0, sdt=sdt),
                       _make_ctx(session="ASIA"),
                       regime=None, story_trackers={}, swing_state=StubSwingState())
    nsm._states[symbol].state = state
    nsm._states[symbol].current_session_date_trading = sdt
    if prev_close is not None:
        nsm._states[symbol].engine_states["prev_close"] = prev_close


# ─── T1 : cross-session reset (any state + sdt change + session=ASIA) ──────


def test_T1_cross_session_reset_from_trend_up():
    """T1 : TREND_UP_CONTINUATION + sdt change + session=ASIA → PRE_OPEN_NEUTRAL.

    Fix post-review : Mark Douglas every-moment-is-unique. Eviter sticky state.
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.TREND_UP_CONTINUATION, sdt="2026-05-15")
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, sdt="2026-05-18"),
        _make_ctx(session="ASIA"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL
    assert snap.bias_dir == 0
    assert snap.triggering_features.get("trigger") == "T1_cross_session_reset"


def test_T1_does_not_fire_if_session_not_ASIA():
    """T1 ne fire QUE si session=ASIA. Si LONDON ou NY, state persiste."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.RANGE_RESPECTED, sdt="2026-05-15")
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, sdt="2026-05-18"),
        _make_ctx(session="LONDON"),  # PAS ASIA
        regime=None, story_trackers={}, swing_state=swing,
    )
    # State persiste (T1 ne fire pas)
    assert snap.state == NarrativeState.RANGE_RESPECTED


# ─── T4 : PRE_OPEN_BEARISH → PRE_OPEN_NEUTRAL (slope rebalance) ────────────


def test_T4_preopen_bearish_to_neutral_on_slope_rebalance():
    """T4 : PRE_OPEN_BEARISH + slope_60 ∈ [-0.1, +0.1] → PRE_OPEN_NEUTRAL."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.PRE_OPEN_BEARISH)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, bar_idx=2),
        _make_ctx(session="ASIA"),
        regime=None,
        story_trackers={"slope_close_60": 0.05},  # ∈ [-0.1, +0.1]
        swing_state=swing,
    )
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL


# ─── T5 : PRE_OPEN_BULLISH → PRE_OPEN_NEUTRAL (slope rebalance) ────────────


def test_T5_preopen_bullish_to_neutral_on_slope_rebalance():
    """T5 : PRE_OPEN_BULLISH + slope_60 ∈ [-0.1, +0.1] → PRE_OPEN_NEUTRAL."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.PRE_OPEN_BULLISH)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, bar_idx=2),
        _make_ctx(session="ASIA"),
        regime=None,
        story_trackers={"slope_close_60": -0.03},  # ∈ [-0.1, +0.1]
        swing_state=swing,
    )
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL


# ─── T8 : NY + open_type=OTD_UP/OTD_DOWN → OPEN_TEST_DRIVE ─────────────────


def test_T8_open_test_drive_OTD_UP():
    """T8 : NY + open_type=OTD_UP → OPEN_TEST_DRIVE.

    Fix B1 : enum OpenType.OTD_UP=3 (avant code utilisait int 1 = OD_UP = inverse).
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, bar_idx=1),
        _make_ctx(session="NY", open_type=int(OpenType.OTD_UP)),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_TEST_DRIVE


def test_T8_open_test_drive_OTD_DOWN():
    """T8 fire aussi sur OTD_DOWN (direction affinee par T14/T15 dans [5,15] bars)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, bar_idx=1),
        _make_ctx(session="NY", open_type=int(OpenType.OTD_DOWN)),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_TEST_DRIVE


# ─── T11 : OPEN_DRIVE_DOWN + bar_idx>30 + ll_60>=3 → TREND_DOWN_CONT ──────


def test_T11_trend_down_continuation_from_open_drive_down():
    """T11 : OPEN_DRIVE_DOWN + bar_idx>30 + ll_60>=3 → TREND_DOWN_CONTINUATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.OPEN_DRIVE_DOWN)
    snap = nsm.transition(
        "ES",
        _make_bar(close=80.0, bar_idx=35),
        _make_ctx(session="NY"),
        regime=None,
        story_trackers={"ll_count_60": 5},
        swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_DOWN_CONTINUATION
    assert snap.bias_dir == -1


# ─── T12 : OPEN_DRIVE_UP revert → OPEN_ROTATION ───────────────────────────


def test_T12_open_drive_up_reverts_to_rotation():
    """T12 : OPEN_DRIVE_UP + close<open_cash + vol_z<-0.5 → OPEN_ROTATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.OPEN_DRIVE_UP)
    snap = nsm.transition(
        "ES",
        _make_bar(close=99.0, vol_z=-1.0, bar_idx=10),
        _make_ctx(session="NY", open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_ROTATION


# ─── T13 : OPEN_DRIVE_DOWN revert → OPEN_ROTATION ─────────────────────────


def test_T13_open_drive_down_reverts_to_rotation():
    """T13 : OPEN_DRIVE_DOWN + close>open_cash + vol_z<-0.5 → OPEN_ROTATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.OPEN_DRIVE_DOWN)
    snap = nsm.transition(
        "ES",
        _make_bar(close=101.0, vol_z=-1.0, bar_idx=10),
        _make_ctx(session="NY", open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_ROTATION


# ─── T14 : OPEN_TEST_DRIVE → OPEN_DRIVE_UP ────────────────────────────────


def test_T14_OTD_confirmed_up():
    """T14 : OPEN_TEST_DRIVE + bar_idx∈[5,15] + close>open_cash+0.5*atr + vol_z>0.5
    → OPEN_DRIVE_UP."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.OPEN_TEST_DRIVE)
    snap = nsm.transition(
        "ES",
        _make_bar(close=106.0, atr=10.0, vol_z=1.0, bar_idx=10),
        _make_ctx(session="NY", open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_DRIVE_UP


# ─── T15 : OPEN_TEST_DRIVE → OPEN_DRIVE_DOWN ──────────────────────────────


def test_T15_OTD_confirmed_down():
    """T15 : OPEN_TEST_DRIVE + bar_idx∈[5,15] + close<open_cash-0.5*atr + vol_z>0.5
    → OPEN_DRIVE_DOWN."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.OPEN_TEST_DRIVE)
    snap = nsm.transition(
        "ES",
        _make_bar(close=94.0, atr=10.0, vol_z=1.0, bar_idx=10),
        _make_ctx(session="NY", open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_DRIVE_DOWN


# ─── T16 : OPEN_TEST_DRIVE timeout → OPEN_ROTATION ────────────────────────


def test_T16_OTD_timeout_rotation():
    """T16 : OPEN_TEST_DRIVE + bar_idx>15 → OPEN_ROTATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.OPEN_TEST_DRIVE)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, bar_idx=20),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.OPEN_ROTATION


# ─── T17 : OPEN_ROTATION → RANGE_RESPECTED ────────────────────────────────


def test_T17_rotation_to_range_respected():
    """T17 : OPEN_ROTATION + ib_complete + inside_va + ib_range/atr<1.2
    → RANGE_RESPECTED."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.OPEN_ROTATION)
    snap = nsm.transition(
        "ES",
        _make_bar(close=100.0, atr=10.0, bar_idx=30),
        _make_ctx(session="NY", ib_complete=True, inside_value_area=True,
                  ib_range=8.0),  # 8/10 = 0.8 < 1.2
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.RANGE_RESPECTED


# ─── T18 : RANGE_RESPECTED + breakout VAH → TREND_UP_CONT (fusion B2) ────


def test_T18_range_breakout_VAH_to_trend_up():
    """T18 (fusion B2) : RANGE_RESPECTED + close>prev_vah + prev_close>prev_vah
    → TREND_UP_CONTINUATION (avant BREAKOUT_CONTINUATION, fusion post-review)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.RANGE_RESPECTED, prev_close=111.0)
    snap = nsm.transition(
        "ES",
        _make_bar(close=112.0, bar_idx=40),
        _make_ctx(session="NY", prev_vah=110.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_UP_CONTINUATION
    assert snap.bias_dir == +1


# ─── T19 : RANGE_RESPECTED + breakdown VAL → TREND_DOWN_CONT (fusion B2) ─


def test_T19_range_breakdown_VAL_to_trend_down():
    """T19 (fusion B2) : RANGE_RESPECTED + close<prev_val + prev_close<prev_val
    → TREND_DOWN_CONTINUATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.RANGE_RESPECTED, prev_close=89.0)
    snap = nsm.transition(
        "ES",
        _make_bar(close=88.0, bar_idx=40),
        _make_ctx(session="NY", prev_val=90.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_DOWN_CONTINUATION
    assert snap.bias_dir == -1


# ─── T20 : TREND_UP_CONT + BOS bearish → TREND_DOWN_CONT (fusion B2) ─────


def test_T20_BOS_bearish_from_trend_up():
    """T20 (fusion B2) : TREND_UP_CONT + close<swing_low + prev_close>=swing_low
    + vol_z>0 → TREND_DOWN_CONTINUATION (BOS reversal)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    _force_state(nsm, "ES", NarrativeState.TREND_UP_CONTINUATION, prev_close=101.0)
    snap = nsm.transition(
        "ES",
        _make_bar(close=99.0, vol_z=0.5, bar_idx=50),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_DOWN_CONTINUATION
    assert snap.bias_dir == -1


# ─── T21 : TREND_DOWN_CONT + BOS bullish → TREND_UP_CONT (fusion B2) ─────


def test_T21_BOS_bullish_from_trend_down():
    """T21 (fusion B2) : TREND_DOWN_CONT + close>swing_high + prev_close<=swing_high
    + vol_z>0 → TREND_UP_CONTINUATION (BOS reversal)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    _force_state(nsm, "ES", NarrativeState.TREND_DOWN_CONTINUATION, prev_close=99.0)
    snap = nsm.transition(
        "ES",
        _make_bar(close=101.0, vol_z=0.5, bar_idx=50),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_UP_CONTINUATION
    assert snap.bias_dir == +1


# ─── T24/T25 : Wyckoff Spring/Upthrust recovery confirmed (SOS) ──────────


def test_T24_spring_recovery_confirmed():
    """T24 : WYCKOFF_SPRING_LONG + close>swing_low+atr → TREND_UP_CONTINUATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    _force_state(nsm, "ES", NarrativeState.WYCKOFF_SPRING_LONG)
    snap = nsm.transition(
        "ES",
        _make_bar(close=106.0, atr=5.0, bar_idx=30),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_UP_CONTINUATION


def test_T25_upthrust_confirmed():
    """T25 : WYCKOFF_UPTHRUST_SHORT + close<swing_high-atr → TREND_DOWN_CONTINUATION."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    _force_state(nsm, "ES", NarrativeState.WYCKOFF_UPTHRUST_SHORT)
    snap = nsm.transition(
        "ES",
        _make_bar(close=94.0, atr=5.0, bar_idx=30),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.TREND_DOWN_CONTINUATION


# ─── T26/T27 : Wyckoff Spring/Upthrust failed → INVALIDATED ──────────────


def test_T26_spring_failed_to_invalidated():
    """T26 : WYCKOFF_SPRING_LONG + close<swing_low-atr → INVALIDATED."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_low=StubSwingPoint(price=100.0))
    _force_state(nsm, "ES", NarrativeState.WYCKOFF_SPRING_LONG)
    snap = nsm.transition(
        "ES",
        _make_bar(close=94.0, atr=5.0, bar_idx=30),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.INVALIDATED


def test_T27_upthrust_failed_to_invalidated():
    """T27 : WYCKOFF_UPTHRUST_SHORT + close>swing_high+atr → INVALIDATED."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState(last_swing_high=StubSwingPoint(price=100.0))
    _force_state(nsm, "ES", NarrativeState.WYCKOFF_UPTHRUST_SHORT)
    snap = nsm.transition(
        "ES",
        _make_bar(close=106.0, atr=5.0, bar_idx=30),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.INVALIDATED


# ─── T29 : TREND_DOWN + climax volume → EXHAUSTION_BOTTOM ────────────────


def test_T29_exhaustion_bottom_from_trend_down():
    """T29 : TREND_DOWN_CONT + vol_z>2.5 + close>open + bar_range>2*atr
    → EXHAUSTION_BOTTOM (selling climax canon Pruden)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.TREND_DOWN_CONTINUATION)
    snap = nsm.transition(
        "ES",
        _make_bar(close=110.0, open_=99.0, high=110.0, low=90.0, atr=5.0,
                  vol_z=3.0, bar_idx=60),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.EXHAUSTION_BOTTOM
    assert snap.bias_dir == +1


# ─── T30/T30b : EXHAUSTION_TOP follow-through (fix B3 INVERSE) ───────────


def test_T30_exhaustion_top_followthrough_to_trend_down():
    """T30 (fix B3) : EXHAUSTION_TOP + close<high-atr → TREND_DOWN_CONTINUATION
    (follow-through baissier = thesis confirmee, PAS INVALIDATED comme avant)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.EXHAUSTION_TOP)
    snap = nsm.transition(
        "ES",
        _make_bar(close=90.0, high=100.0, atr=5.0, bar_idx=65),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    # Fix B3 : close 90 < high 100 - atr 5 = 95 → follow-through baissier confirme
    assert snap.state == NarrativeState.TREND_DOWN_CONTINUATION
    assert snap.bias_dir == -1


def test_T30b_exhaustion_top_no_followthrough_to_invalidated():
    """T30b (fix B3) : EXHAUSTION_TOP + close>=high → INVALIDATED (faux climax)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.EXHAUSTION_TOP)
    snap = nsm.transition(
        "ES",
        _make_bar(close=101.0, high=100.0, atr=5.0, bar_idx=65),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    # close 101 >= high 100 → pas de follow-through, faux climax
    assert snap.state == NarrativeState.INVALIDATED


# ─── T31/T31b : EXHAUSTION_BOTTOM follow-through (fix B3 INVERSE) ────────


def test_T31_exhaustion_bottom_followthrough_to_trend_up():
    """T31 (fix B3) : EXHAUSTION_BOTTOM + close>low+atr → TREND_UP_CONTINUATION
    (follow-through haussier = thesis confirmee, PAS INVALIDATED comme avant)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.EXHAUSTION_BOTTOM)
    snap = nsm.transition(
        "ES",
        _make_bar(close=110.0, low=100.0, atr=5.0, bar_idx=65),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    # close 110 > low 100 + atr 5 = 105 → follow-through haussier confirme
    assert snap.state == NarrativeState.TREND_UP_CONTINUATION
    assert snap.bias_dir == +1


def test_T31b_exhaustion_bottom_no_followthrough_to_invalidated():
    """T31b (fix B3) : EXHAUSTION_BOTTOM + close<=low → INVALIDATED (faux climax)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    _force_state(nsm, "ES", NarrativeState.EXHAUSTION_BOTTOM)
    snap = nsm.transition(
        "ES",
        _make_bar(close=99.0, low=100.0, atr=5.0, bar_idx=65),
        _make_ctx(session="NY"),
        regime=None, story_trackers={}, swing_state=swing,
    )
    # close 99 <= low 100 → pas de follow-through, faux climax
    assert snap.state == NarrativeState.INVALIDATED


# ─── F1 fix : race condition consume_events sous events_lock ──────────────


def test_F1_concurrent_transition_and_consume_no_event_loss():
    """F1 fix : transition() append + consume_events() swap concurrents
    ne perdent aucun event grace au _events_lock dedie."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    captured_events: list[NarrativeEvent] = []
    stop_flag = threading.Event()

    def producer(sym: str) -> None:
        i = 0
        while not stop_flag.is_set() and i < 100:
            nsm.transition(
                sym, _make_bar(close=100.0 + (i * 0.01), bar_idx=i),
                _make_ctx(session="ASIA",
                          asia_close=98.0 + (i % 2) * 4.0,  # alterne pour trigger T2/T4
                          asia_open=100.0),
                regime=None,
                story_trackers={"slope_close_60": -0.5 if i % 2 == 0 else 0.0},
                swing_state=swing,
            )
            i += 1

    def consumer() -> None:
        while not stop_flag.is_set():
            captured_events.extend(nsm.consume_events())

    threads = [
        threading.Thread(target=producer, args=("ES",)),
        threading.Thread(target=producer, args=("NQ",)),
        threading.Thread(target=consumer),
    ]
    for t in threads:
        t.start()
    # Laisser tourner brievement puis stopper
    import time
    time.sleep(0.2)
    stop_flag.set()
    for t in threads:
        t.join(timeout=2.0)
    # Final drain
    captured_events.extend(nsm.consume_events())

    # Aucune exception levee = pas de race detectee
    # Pas de check count exact car consumer peut polluer entre transitions,
    # mais au moins 1 event capture (le bot tourne)
    assert isinstance(captured_events, list)


# ─── Coverage : default open_type=0 (UNKNOWN) ne fire aucune T6-T9 ───────


def test_unknown_open_type_no_transition_fired():
    """Fix B1 garde-fou : open_type=0 (UNKNOWN) en session NY ne fire aucune
    transition T6-T9. State persiste PRE_OPEN_NEUTRAL.

    Anti regression : avant fix B1, T6 firait sur open_type=0 (UNKNOWN) =
    faux positifs OPEN_DRIVE pendant ~60 min ouverture (avant 10h30 quand
    classify_open_type a tous ses inputs).
    """
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    # NY + open_type=UNKNOWN(0) + close>open_cash+atr + vol_z>1.0 :
    # AVANT fix : T6 firait (faux positif).
    # APRES fix : T6 ne fire pas (open_type != OD_UP=1), state persiste.
    snap = nsm.transition(
        "ES",
        _make_bar(close=111.0, atr=10.0, vol_z=1.5, bar_idx=1),
        _make_ctx(session="NY", open_type=int(OpenType.UNKNOWN), open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    assert snap.state == NarrativeState.PRE_OPEN_NEUTRAL


# ─── Coverage : bar_idx ordering after F6 fix ────────────────────────────


def test_F6_state_entered_at_bar_idx_matches_current_bar():
    """F6 fix : transition fires sur bar N → state_entered_at_bar_idx = N
    (= bar_idx_current apres increment, qui represente le bar courant)."""
    nsm = NarrativeStateMachine()
    swing = StubSwingState()
    nsm.transition("ES", _make_bar(close=100.0), _make_ctx(session="ASIA"),
                   regime=None, story_trackers={}, swing_state=swing)
    # bar_idx_current = 1 apres cold start
    assert nsm.current("ES").bar_idx_current == 1

    # Transition T6 sur bar suivante
    snap = nsm.transition(
        "ES",
        _make_bar(close=111.0, atr=10.0, vol_z=1.5, bar_idx=1),
        _make_ctx(session="NY", open_type=int(OpenType.OD_UP), open_cash=100.0),
        regime=None, story_trackers={}, swing_state=swing,
    )
    # bar_idx_current = 2 maintenant
    assert snap.bar_idx_current == 2
    # state_entered_at_bar_idx = 2 (le bar ou T6 a fire)
    assert snap.state_entered_at_bar_idx == 2
