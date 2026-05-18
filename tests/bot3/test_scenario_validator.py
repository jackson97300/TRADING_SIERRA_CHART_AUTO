"""tests/bot3/test_scenario_validator.py - Tests Phase 2 ScenarioValidator.

Tests pytest pour `CORE/bot3_scenario_validator.py`.
Coverage cible >= 90%. Tests par regle invalidation + time decay + exempt states.

HISTORY
2026-05-18 PM : creation tests Phase 2 J+1 (12 tests)
"""
from __future__ import annotations

import pytest

from CORE.bot3_narrative_state_machine import NarrativeState, NarrativeStateSnapshot
from CORE.bot3_plot_twist_detectors import PlotTwist
from CORE.bot3_scenario_validator import (
    TIME_DECAY_BARS_DEFAULT,
    is_narrative_still_valid,
)


def _make_snapshot(
    state: NarrativeState = NarrativeState.TREND_UP_CONTINUATION,
    bars_in_state: int = 10,
    bias_dir: int = +1,
) -> NarrativeStateSnapshot:
    return NarrativeStateSnapshot(
        symbol="ES",
        state=state,
        state_entered_at_bar_idx=0,
        bar_idx_current=bars_in_state,
        bias_dir=bias_dir,
        confidence=0.85,
    )


def _make_twist(
    twist_type: str = "STRUCTURE_BREAK",
    direction: int = -1,
    severity: float = 0.8,
) -> PlotTwist:
    return PlotTwist(
        twist_type=twist_type,
        direction=direction,
        severity=severity,
        bar_ts="2026-05-18T13:30:00Z",
        bar_idx=10,
        symbol="ES",
    )


# ════════════════════════════════════════════════════════════════════════════
# Time decay
# ════════════════════════════════════════════════════════════════════════════


def test_time_decay_invalidates_after_threshold():
    """bars_in_state > TIME_DECAY_BARS_DEFAULT (240) → INVALIDATED via TIME_DECAY."""
    snap = _make_snapshot(
        state=NarrativeState.TREND_UP_CONTINUATION,
        bars_in_state=300,
    )
    is_valid, reason = is_narrative_still_valid(snap, twists=[])
    assert is_valid is False
    assert reason == "TIME_DECAY"


def test_time_decay_does_not_invalidate_before_threshold():
    """bars_in_state < threshold = valid."""
    snap = _make_snapshot(bars_in_state=100)
    is_valid, reason = is_narrative_still_valid(snap, twists=[])
    assert is_valid is True
    assert reason == ""


def test_time_decay_exempt_for_pre_open_states():
    """PRE_OPEN_* exemptes du time decay (peut durer 16h+ Asia/London)."""
    snap = _make_snapshot(
        state=NarrativeState.PRE_OPEN_NEUTRAL,
        bars_in_state=600,  # bien au-dela 240
    )
    is_valid, reason = is_narrative_still_valid(snap, twists=[])
    assert is_valid is True


def test_time_decay_exempt_for_invalidated_state():
    """INVALIDATED deja terminal, pas re-invalide."""
    snap = _make_snapshot(state=NarrativeState.INVALIDATED, bars_in_state=999)
    is_valid, reason = is_narrative_still_valid(snap, twists=[])
    assert is_valid is True


def test_time_decay_custom_threshold():
    """time_decay_bars=120 invalidates si bars_in_state=150."""
    snap = _make_snapshot(bars_in_state=150)
    is_valid, reason = is_narrative_still_valid(
        snap, twists=[], time_decay_bars=120,
    )
    assert is_valid is False
    assert reason == "TIME_DECAY"


# ════════════════════════════════════════════════════════════════════════════
# Invalidating twists per state
# ════════════════════════════════════════════════════════════════════════════


def test_trend_up_invalidated_by_BOS_bearish():
    """TREND_UP_CONTINUATION + STRUCTURE_BREAK dir=-1 → INVALIDATED."""
    snap = _make_snapshot(state=NarrativeState.TREND_UP_CONTINUATION)
    twist = _make_twist(twist_type="STRUCTURE_BREAK", direction=-1)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is False
    assert "STRUCTURE_BREAK" in reason
    assert "-1" in reason


def test_trend_up_not_invalidated_by_BOS_bullish():
    """TREND_UP_CONTINUATION + STRUCTURE_BREAK dir=+1 = continuation, pas inval."""
    snap = _make_snapshot(state=NarrativeState.TREND_UP_CONTINUATION)
    twist = _make_twist(twist_type="STRUCTURE_BREAK", direction=+1)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is True


def test_trend_up_invalidated_by_CAPITULATION_bearish():
    """TREND_UP + CAPITULATION dir=-1 (selling climax top) → INVALIDATED."""
    snap = _make_snapshot(state=NarrativeState.TREND_UP_CONTINUATION)
    twist = _make_twist(twist_type="CAPITULATION", direction=-1, severity=0.9)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is False
    assert "CAPITULATION" in reason


def test_trend_down_invalidated_by_BOS_bullish():
    """TREND_DOWN_CONTINUATION + STRUCTURE_BREAK dir=+1 → INVALIDATED."""
    snap = _make_snapshot(state=NarrativeState.TREND_DOWN_CONTINUATION, bias_dir=-1)
    twist = _make_twist(twist_type="STRUCTURE_BREAK", direction=+1)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is False


def test_wyckoff_spring_invalidated_by_BOS_bearish():
    """WYCKOFF_SPRING_LONG + BOS bearish = spring failed → INVALIDATED."""
    snap = _make_snapshot(state=NarrativeState.WYCKOFF_SPRING_LONG)
    twist = _make_twist(twist_type="STRUCTURE_BREAK", direction=-1)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is False


def test_open_drive_up_invalidated_by_capitulation_bearish():
    """OPEN_DRIVE_UP + CAPITULATION bearish = reversal climax = INVALIDATED."""
    snap = _make_snapshot(state=NarrativeState.OPEN_DRIVE_UP)
    twist = _make_twist(twist_type="CAPITULATION", direction=-1, severity=0.7)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is False


def test_low_severity_twist_does_not_invalidate():
    """severity < 0.3 = ignore (anti-bruit)."""
    snap = _make_snapshot(state=NarrativeState.TREND_UP_CONTINUATION)
    twist = _make_twist(twist_type="STRUCTURE_BREAK", direction=-1, severity=0.1)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is True


def test_range_respected_not_invalidated_by_twists():
    """RANGE_RESPECTED gere ses propres transitions T18/T19 via NSM, validator
    n'invalide pas (rules vide)."""
    snap = _make_snapshot(state=NarrativeState.RANGE_RESPECTED, bias_dir=0)
    twist = _make_twist(twist_type="STRUCTURE_BREAK", direction=+1, severity=0.9)
    is_valid, reason = is_narrative_still_valid(snap, twists=[twist])
    assert is_valid is True


def test_no_twists_no_time_decay_returns_valid():
    """Cas baseline : etat actif < threshold time decay, pas de twists = valid."""
    snap = _make_snapshot(bars_in_state=50)
    is_valid, reason = is_narrative_still_valid(snap, twists=[])
    assert is_valid is True
    assert reason == ""


def test_multiple_invalidating_twists_strongest_returns():
    """Fix #2 review Claude 4.7 : strongest signal (severity max) wins, pas first-match.

    TREND_UP + BOS bearish severity 0.4 + CAPITULATION bearish severity 0.9
    → invalidates avec CAPITULATION (severity max) pas STRUCTURE_BREAK (first).
    Important pour attribution post-mortem Phase 3 DirectionResolver.
    """
    snap = _make_snapshot(state=NarrativeState.TREND_UP_CONTINUATION)
    twists = [
        _make_twist(twist_type="VOLUME_ANOMALY", direction=+1, severity=0.5),  # ne match pas
        _make_twist(twist_type="STRUCTURE_BREAK", direction=-1, severity=0.4),  # match faible
        _make_twist(twist_type="CAPITULATION", direction=-1, severity=0.9),    # match fort
    ]
    is_valid, reason = is_narrative_still_valid(snap, twists=twists)
    assert is_valid is False
    # Strongest (CAPITULATION severity 0.9) returned, pas STRUCTURE_BREAK
    assert "CAPITULATION" in reason


def test_negative_bars_in_state_handled_defensively():
    """Fix #3 review Claude 4.7 : bar_idx_current < state_entered_at_bar_idx
    (snapshot inconsistant ex: NSM rollback / pickle corrompu).
    Validator ne doit PAS invalidate sur donnee corrompue (defensif)."""
    snap = NarrativeStateSnapshot(
        symbol="ES",
        state=NarrativeState.TREND_UP_CONTINUATION,
        state_entered_at_bar_idx=100,  # entered later (impossible normalement)
        bar_idx_current=50,            # < state_entered (rollback ?)
        bias_dir=+1,
        confidence=0.85,
    )
    is_valid, reason = is_narrative_still_valid(snap, twists=[])
    # Defensif : retourne valid (laisse passer) au lieu d'invalidate sur donnee inconsistante
    assert is_valid is True
    assert reason == ""
