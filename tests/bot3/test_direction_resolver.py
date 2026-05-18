"""tests/bot3/test_direction_resolver.py - Tests Phase 3 DirectionResolver.

Tests pytest pour `CORE/bot3_direction_resolver.py`.
Coverage cible >= 85%. Tests par scenario + ConfirmationGate state machine.

HISTORY
2026-05-18 PM : creation tests Phase 3 J+2 (scenarios S01-S10 + pending state machine)
"""
from __future__ import annotations

import pickle

import pytest

from CORE.bot3_direction_resolver import (
    CONF_HIGH,
    CONF_NO_TRADE,
    CONF_RANGE_PLAY,
    CONF_REVERSAL,
    CONF_TREND_FOLLOW,
    DirectionResolver,
    PendingEntry,
    ResolvedDirection,
)
from CORE.bot3_narrative_state_machine import NarrativeState, NarrativeStateSnapshot


# ─── Helpers ──────────────────────────────────────────────────────────────


def _make_snapshot(
    state: NarrativeState = NarrativeState.OPEN_DRIVE_UP,
    bias_dir: int = +1,
    bar_idx_current: int = 10,
    state_entered_at_bar_idx: int = 5,
    symbol: str = "ES",
) -> NarrativeStateSnapshot:
    return NarrativeStateSnapshot(
        symbol=symbol,
        state=state,
        state_entered_at_bar_idx=state_entered_at_bar_idx,
        bar_idx_current=bar_idx_current,
        bias_dir=bias_dir,
        confidence=0.85,
    )


def _make_bar(
    close: float = 100.0,
    open_: float = 100.0,
    high: float = 100.5,
    low: float = 99.5,
    vol_z: float = 1.0,
) -> dict:
    return {
        "close": close,
        "open": open_,
        "high": high,
        "low": low,
        "vol_zscore_20": vol_z,
        "ts_event_iso": "2026-05-18T13:30:00Z",
    }


# ════════════════════════════════════════════════════════════════════════════
# Scenarios S01-S10 (table-driven lookup)
# ════════════════════════════════════════════════════════════════════════════


def test_S01_OD_UP_support_bounce_pending_then_LONG():
    """S01 : OPEN_DRIVE_UP + support → LONG confidence HIGH, pending rejection_with_volume.
    Confirme apres 1 bar avec lower_wick + vol_z>0.5."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP)

    # Step 1 : resolve initial → pending NO_TRADE
    r1 = res.resolve(snap, "MQ_PUT", "support", level_price=99.5,
                     bar=_make_bar(close=100.0))
    assert r1.side == "NO_TRADE"
    assert r1.scenario_id == "S01_OD_UP_support_bounce"
    assert res.pending_count() == 1

    # Step 2 : bar suivante avec rejection (lower_wick + vol)
    # close 100.5, low 99.0, open 99.5 → lower_wick = 99.5-99.0 = 0.5, bar_range = 1.5
    # lower_wick/range = 0.33 > 0.30 + vol_z 1.0 > 0.5 → confirm
    snap2 = _make_snapshot(bar_idx_current=11)
    r2 = res.resolve(snap2, "MQ_PUT", "support", level_price=99.5,
                     bar=_make_bar(close=100.5, open_=99.5, high=100.5, low=99.0, vol_z=1.0))
    assert r2.side == "LONG"
    assert r2.confidence == pytest.approx(CONF_HIGH, abs=0.01)
    assert res.pending_count() == 0  # consumed


def test_S02_OD_DOWN_resistance_rejection_pending_then_SHORT():
    """S02 : OPEN_DRIVE_DOWN + resistance → SHORT confidence HIGH."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.OPEN_DRIVE_DOWN, bias_dir=-1)

    r1 = res.resolve(snap, "MQ_CALL", "resistance", level_price=100.5,
                     bar=_make_bar(close=100.0))
    assert r1.side == "NO_TRADE"
    assert r1.scenario_id == "S02_OD_DOWN_resistance_rejection"

    # Confirme avec upper_wick
    snap2 = _make_snapshot(state=NarrativeState.OPEN_DRIVE_DOWN, bar_idx_current=11, bias_dir=-1)
    r2 = res.resolve(snap2, "MQ_CALL", "resistance", level_price=100.5,
                     bar=_make_bar(close=99.5, open_=100.5, high=101.0, low=99.5, vol_z=1.0))
    assert r2.side == "SHORT"
    assert r2.confidence == pytest.approx(CONF_HIGH, abs=0.01)


def test_S03_TREND_UP_support_pullback_LONG():
    """S03 : TREND_UP_CONTINUATION + support → LONG conf TREND_FOLLOW."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.TREND_UP_CONTINUATION)

    r1 = res.resolve(snap, "IB_LOW", "support", level_price=99.5,
                     bar=_make_bar())
    assert r1.scenario_id == "S03_TREND_UP_support_pullback"

    snap2 = _make_snapshot(state=NarrativeState.TREND_UP_CONTINUATION, bar_idx_current=11)
    r2 = res.resolve(snap2, "IB_LOW", "support", level_price=99.5,
                     bar=_make_bar(close=100.5, open_=99.5, high=100.5, low=99.0, vol_z=1.0))
    assert r2.side == "LONG"
    assert r2.confidence == pytest.approx(CONF_TREND_FOLLOW, abs=0.01)


def test_S05_SPRING_recovery_long_pre_SOS():
    """S05 : WYCKOFF_SPRING_LONG + support → LONG conf REVERSAL (pre-SOS Pruden)."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG)

    r1 = res.resolve(snap, "VPOC", "support", level_price=99.5,
                     bar=_make_bar())
    assert r1.scenario_id == "S05_SPRING_recovery_long"
    assert res.pending_count() == 1

    # Spring recovery : low penetre < target ET close > target
    # min_bars=2, max_bars=3 → faut attendre au moins 2 bars
    snap2 = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG, bar_idx_current=11)
    r2 = res.resolve(snap2, "VPOC", "support", level_price=99.5,
                     bar=_make_bar(close=100.0, low=99.0))
    # bars_waited = 11-10 = 1 < min_bars 2 → wait
    assert r2.side == "NO_TRADE"

    snap3 = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG, bar_idx_current=12)
    r3 = res.resolve(snap3, "VPOC", "support", level_price=99.5,
                     bar=_make_bar(close=100.0, low=99.0))
    # bars_waited = 2 >= min_bars 2, check pattern spring_recovery
    assert r3.side == "LONG"
    assert r3.confidence == pytest.approx(CONF_REVERSAL, abs=0.01)


def test_S09_EXHAUSTION_TOP_short_break_strike():
    """S09 : EXHAUSTION_TOP + resistance → SHORT, pattern break_below_strike."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.EXHAUSTION_TOP, bias_dir=-1)

    r1 = res.resolve(snap, "MQ_CALL_0DTE", "resistance", level_price=100.0,
                     bar=_make_bar(close=99.8))
    assert r1.scenario_id == "S09_EXHAUSTION_TOP_short"

    # Step 2 : close < target_price (100.0)
    snap2 = _make_snapshot(state=NarrativeState.EXHAUSTION_TOP, bar_idx_current=11, bias_dir=-1)
    r2 = res.resolve(snap2, "MQ_CALL_0DTE", "resistance", level_price=100.0,
                     bar=_make_bar(close=99.5))
    assert r2.side == "SHORT"
    assert r2.confidence == pytest.approx(CONF_REVERSAL, abs=0.01)


# ════════════════════════════════════════════════════════════════════════════
# NO_TRADE fallback (no scenario match)
# ════════════════════════════════════════════════════════════════════════════


def test_NO_TRADE_unknown_combination():
    """OPEN_TEST_DRIVE + resistance = pas dans _SCENARIOS → NO_TRADE."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.OPEN_TEST_DRIVE)

    r = res.resolve(snap, "MQ_CALL", "resistance", level_price=100.0, bar=_make_bar())
    assert r.side == "NO_TRADE"
    assert r.scenario_id == "NO_MATCH"
    assert r.confidence == CONF_NO_TRADE


def test_NO_TRADE_pre_open_states():
    """PRE_OPEN_NEUTRAL + n'importe quoi → NO_TRADE (pas dans scenarios)."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.PRE_OPEN_NEUTRAL)

    r = res.resolve(snap, "MQ_PUT", "support", level_price=99.0, bar=_make_bar())
    assert r.side == "NO_TRADE"


def test_NO_TRADE_invalidated_state():
    """INVALIDATED + n'importe quoi → NO_TRADE."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.INVALIDATED)

    r = res.resolve(snap, "MQ_PUT", "support", level_price=99.0, bar=_make_bar())
    assert r.side == "NO_TRADE"


# ════════════════════════════════════════════════════════════════════════════
# ConfirmationGate state machine
# ════════════════════════════════════════════════════════════════════════════


def test_pending_invalidated_on_narrative_INVALIDATED():
    """Pending abort si narrative passe INVALIDATED mid-wait."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP)
    res.resolve(snap, "MQ_PUT", "support", level_price=99.5, bar=_make_bar())
    assert res.pending_count() == 1

    # State change INVALIDATED mid-wait
    snap2 = _make_snapshot(state=NarrativeState.INVALIDATED, bar_idx_current=11)
    r2 = res.resolve(snap2, "MQ_PUT", "support", level_price=99.5, bar=_make_bar())
    assert r2.side == "NO_TRADE"
    assert "invalidated" in r2.rationale.lower() or "INVALIDATED" in r2.rationale
    assert res.pending_count() == 0


def test_pending_timeout_after_max_bars():
    """Pending timeout si bars_waited > max_bars."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP)
    res.resolve(snap, "MQ_PUT", "support", level_price=99.5, bar=_make_bar())

    # OD_UP support : min_bars=1, max_bars=2
    # bar_idx_current=13 → bars_waited=3 > max_bars=2 → timeout
    snap_late = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP, bar_idx_current=13)
    r_late = res.resolve(snap_late, "MQ_PUT", "support", level_price=99.5,
                          bar=_make_bar())
    assert r_late.side == "NO_TRADE"
    assert "timeout" in r_late.rationale.lower()
    assert res.pending_count() == 0


def test_pending_persistence_across_bars_until_confirmed():
    """Pending reste actif tant que pas confirme ni timeout ni invalid."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG)
    res.resolve(snap, "VPOC", "support", level_price=99.5, bar=_make_bar())
    assert res.pending_count() == 1

    # Bar 11 : pas encore min_bars=2 atteint
    snap2 = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG, bar_idx_current=11)
    r2 = res.resolve(snap2, "VPOC", "support", level_price=99.5,
                     bar=_make_bar(close=100.0))
    assert r2.side == "NO_TRADE"
    assert res.pending_count() == 1  # still pending


def test_pattern_rejection_with_volume_LONG():
    """Pattern rejection_with_volume : lower_wick > 30% + vol_z > 0.5."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP)
    res.resolve(snap, "MQ_PUT", "support", level_price=99.5, bar=_make_bar())

    snap2 = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP, bar_idx_current=11)
    # Pas de rejection (vol_z faible)
    r_no_vol = res.resolve(snap2, "MQ_PUT", "support", level_price=99.5,
                            bar=_make_bar(close=100.5, open_=99.5,
                                          high=100.5, low=99.0, vol_z=0.1))
    assert r_no_vol.side == "NO_TRADE"  # vol_z trop faible


def test_pattern_break_below_strike_SHORT():
    """Pattern break_below_strike_confirmed : close < target_price (SHORT)."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.EXHAUSTION_TOP, bias_dir=-1)
    res.resolve(snap, "MQ_CALL", "resistance", level_price=100.0,
                bar=_make_bar(close=99.9))

    # Bar 2 : close > target → no confirm (pour SHORT besoin close<target)
    snap2 = _make_snapshot(state=NarrativeState.EXHAUSTION_TOP,
                            bar_idx_current=11, bias_dir=-1)
    r_above = res.resolve(snap2, "MQ_CALL", "resistance", level_price=100.0,
                           bar=_make_bar(close=100.5))
    assert r_above.side == "NO_TRADE"


def test_pattern_spring_recovery_LONG():
    """Pattern spring_recovery : low < target ET close > target."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG)
    res.resolve(snap, "VPOC", "support", level_price=99.5, bar=_make_bar())

    # Bar 11 : min_bars 2 pas atteint
    snap2 = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG, bar_idx_current=11)
    res.resolve(snap2, "VPOC", "support", level_price=99.5, bar=_make_bar())

    # Bar 12 : low penetre target + close recovery → confirm
    snap3 = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG, bar_idx_current=12)
    r3 = res.resolve(snap3, "VPOC", "support", level_price=99.5,
                     bar=_make_bar(close=100.0, low=99.0, high=100.5))
    assert r3.side == "LONG"  # spring confirmed


# ════════════════════════════════════════════════════════════════════════════
# Multi-symbol concurrency + pickle
# ════════════════════════════════════════════════════════════════════════════


def test_pending_isolation_per_symbol_per_level():
    """Pending entries isolated per (symbol, level)."""
    res = DirectionResolver()
    snap_es = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP, symbol="ES")
    snap_nq = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP, symbol="NQ")

    res.resolve(snap_es, "MQ_PUT", "support", level_price=99.5, bar=_make_bar())
    res.resolve(snap_nq, "MQ_PUT", "support", level_price=99.5, bar=_make_bar())
    # Same level name "MQ_PUT" mais 2 symbols → 2 pending separes
    assert res.pending_count() == 2


def test_pickle_roundtrip_preserves_pending_entries():
    """Pickle dump/load preserve _pending_entries + recreate _lock."""
    res = DirectionResolver()
    snap = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP)
    res.resolve(snap, "MQ_PUT", "support", level_price=99.5, bar=_make_bar())
    assert res.pending_count() == 1

    blob = pickle.dumps(res)
    loaded = pickle.loads(blob)
    assert loaded.pending_count() == 1
    # _lock recreee
    with loaded._lock:
        pass
