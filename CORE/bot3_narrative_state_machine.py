"""CORE/bot3_narrative_state_machine.py - NSM Bot 3 v2 Narrative Layer (Phase 1).

Module : Narrative State Machine (NSM) state machine globale du marche par symbole.
17 etats narratifs (Dalton + Wyckoff + ICT) + 32 transitions deterministes
table-driven (anti Pattern 11 V1 composite hardcoded).

Architecture : Bot 3 v2 Narrative Layer (Phase 1 TRACKING ONLY).
Pattern reference : `CORE/live_enricher_state.py:51-200` (LiveEnricherState).
NOT `bot3_breakout_retest.BreakoutRetestStateMachine` (cf ADR 0002 :
  BRS key=(sym,level) lifecycle instance-per-event,
  NSM key=sym lifecycle persistent FSM 24/7 = differents).

Data source : Databento payload V4 enriched canonical (~467 cols/bar).
  Inputs : bar (V4) + ctx (analyze_context) + regime + story_trackers snapshot
           + swing_state (last_swing_high/low).

17 Etats (cf DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md) :
  Pre-open : PRE_OPEN_BEARISH / BULLISH / NEUTRAL
  Dalton Open Types : OPEN_DRIVE_UP / DOWN / OPEN_TEST_DRIVE / OPEN_ROTATION
  Sessions : TREND_UP_CONTINUATION / TREND_DOWN_CONTINUATION / RANGE_RESPECTED
  Wyckoff Phase C : WYCKOFF_SPRING_LONG / WYCKOFF_UPTHRUST_SHORT
  ICT BOS : BREAKDOWN_CONTINUATION / BREAKOUT_CONTINUATION
  Terminal : EXHAUSTION_TOP / EXHAUSTION_BOTTOM / INVALIDATED

32 Transitions T1-T32 (cf spec section 4) : table-driven, evaluees ordre
priorite, premier match wins. Anti-flicker guard : >8 transitions/jour/sym
= block + log BOT3_NSM_FLICKER_GUARD.

Created : 2026-05-18 by Jackson + Claude (mode mentor proactif)
Last modified : 2026-05-18 PM - creation Phase 1 J+0 (spec agent 4.20/5)

Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md
Review trace : LOGS/reviews/REVIEW_BOT3V2_narrative_state_machine_*.json
Memory feedback : .claude/memory/feedback_bot3v2_nsm_*.md (post-review)

Auteur : Bot 3 v2 Narrative Layer Phase 1
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 PM : creation skeleton 17 etats + 32 transitions (Phase 1 J+0)
# 2026-05-18 PM : fix T32 sdt sync bug — l'update de current_session_date_trading
#                 etait fait AVANT _evaluate_transitions, empechant T32 (INVALIDATED
#                 + sdt change → PRE_OPEN_NEUTRAL) de detecter le change. Update
#                 deplace apres evaluate. Detecte par pytest test_invalidated_state_
#                 resets_on_sdt_change. 26/26 tests PASS apres fix.
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

try:
    from CORE.bot3_narrative_logging import emit
except ModuleNotFoundError:
    from bot3_narrative_logging import emit  # type: ignore[no-redef]

NSM_SCHEMA_VERSION: str = "2.0.0"
FLICKER_GUARD_THRESHOLD: int = 8  # >8 transitions/jour/sym = anti flicker block


class NarrativeState(Enum):
    """17 etats narratifs du marche pour Bot 3 v2.

    Cf DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md section 2.1.
    """
    # Pre-open (avant 09:30 ET)
    PRE_OPEN_BEARISH = "PRE_OPEN_BEARISH"
    PRE_OPEN_BULLISH = "PRE_OPEN_BULLISH"
    PRE_OPEN_NEUTRAL = "PRE_OPEN_NEUTRAL"
    # Dalton Open Types (D1-D4)
    OPEN_DRIVE_UP = "OPEN_DRIVE_UP"
    OPEN_DRIVE_DOWN = "OPEN_DRIVE_DOWN"
    OPEN_TEST_DRIVE = "OPEN_TEST_DRIVE"
    OPEN_ROTATION = "OPEN_ROTATION"
    # Sessions etablies
    TREND_UP_CONTINUATION = "TREND_UP_CONTINUATION"
    TREND_DOWN_CONTINUATION = "TREND_DOWN_CONTINUATION"
    RANGE_RESPECTED = "RANGE_RESPECTED"
    # Wyckoff Phase C (reversal setups)
    WYCKOFF_SPRING_LONG = "WYCKOFF_SPRING_LONG"
    WYCKOFF_UPTHRUST_SHORT = "WYCKOFF_UPTHRUST_SHORT"
    # ICT BOS confirmed
    BREAKDOWN_CONTINUATION = "BREAKDOWN_CONTINUATION"
    BREAKOUT_CONTINUATION = "BREAKOUT_CONTINUATION"
    # Exhaustion / Terminal
    EXHAUSTION_TOP = "EXHAUSTION_TOP"
    EXHAUSTION_BOTTOM = "EXHAUSTION_BOTTOM"
    # Reset / error
    INVALIDATED = "INVALIDATED"


# Set des etats PRE_OPEN_* (T6/T7/T8/T9 transitions multi-from)
_PRE_OPEN_STATES: frozenset[NarrativeState] = frozenset({
    NarrativeState.PRE_OPEN_BEARISH,
    NarrativeState.PRE_OPEN_BULLISH,
    NarrativeState.PRE_OPEN_NEUTRAL,
})


@dataclass
class NarrativeStateSnapshot:
    """Snapshot etat narratif d'un symbol a un instant t.

    Mirror `LiveEnricherState` pattern (ADR 0002) : 1 instance per symbol,
    pickle persistent, schema_version'ed.
    """
    schema_version: str = NSM_SCHEMA_VERSION
    symbol: str = ""
    state: NarrativeState = NarrativeState.PRE_OPEN_NEUTRAL
    state_entered_at_ts: str | None = None
    state_entered_at_bar_idx: int = 0
    bar_idx_current: int = 0
    bias_dir: int = 0  # -1 / 0 / +1
    confidence: float = 0.0  # [0.0, 1.0]
    triggering_features: dict[str, Any] = field(default_factory=dict)
    expected_targets: list[str] = field(default_factory=list)
    invalidation_triggers: list[str] = field(default_factory=list)
    engine_states: dict[str, Any] = field(default_factory=dict)
    n_transitions_today: int = 0
    current_session_date_trading: str | None = None


@dataclass
class NarrativeEvent:
    """Event emit par NSM apres transition (pattern observer)."""
    event_type: str  # STATE_TRANSITION / SCENARIO_INVALIDATED / STATE_RESET_SESSION
    from_state: NarrativeState | None
    to_state: NarrativeState
    bar_ts: str
    bar_idx: int
    symbol: str
    payload: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers : safe accessors + fenetre evaluation (anti NaN/None silent)
# ═══════════════════════════════════════════════════════════════════════════

def _safe_float(v: Any) -> float | None:
    """Cast safe en float, retourne None si invalide/NaN."""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    """Cast safe en int, retourne None si invalide."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _get_session(ctx: dict) -> str:
    """Extract session string normalisee (ASIA/LONDON/NY/OTHER)."""
    s = ctx.get("session", "")
    if isinstance(s, str):
        return s.upper()
    return "OTHER"


def _get_open_type(ctx: dict, bar: dict) -> int | None:
    """open_type : check ctx puis bar (V4 enriched canonical embed)."""
    v = ctx.get("open_type")
    if v is None:
        v = bar.get("open_type")
    return _safe_int(v)


def _swing_high_price(swing_state: Any) -> float | None:
    """Safe accessor swing_state.last_swing_high.price."""
    if swing_state is None:
        return None
    sh = getattr(swing_state, "last_swing_high", None)
    if sh is None:
        return None
    return _safe_float(getattr(sh, "price", None))


def _swing_low_price(swing_state: Any) -> float | None:
    """Safe accessor swing_state.last_swing_low.price."""
    if swing_state is None:
        return None
    sl = getattr(swing_state, "last_swing_low", None)
    if sl is None:
        return None
    return _safe_float(getattr(sl, "price", None))


# ═══════════════════════════════════════════════════════════════════════════
# Transitions evaluators (deterministes, ordre priorite)
# ═══════════════════════════════════════════════════════════════════════════

def _evaluate_transitions(
    current: NarrativeStateSnapshot,
    bar: dict,
    ctx: dict,
    story: dict[str, Any],
    swing_state: Any,
) -> tuple[NarrativeState, int, float, dict[str, Any]] | None:
    """Evaluate les 32 transitions T1-T32 dans l'ordre priorite.

    Retourne (next_state, bias_dir, confidence, triggering_features) si transition
    legitime, None sinon (= stay current state).

    Premier match wins. Anti-flicker guard applique en amont par caller.
    """
    state = current.state
    close = _safe_float(bar.get("close"))
    high = _safe_float(bar.get("high"))
    low = _safe_float(bar.get("low"))
    open_ = _safe_float(bar.get("open"))
    atr = _safe_float(bar.get("atr"))
    vol_z = _safe_float(bar.get("vol_zscore_20"))
    bar_idx = _safe_int(bar.get("bar_idx_session")) or current.bar_idx_current
    session = _get_session(ctx)
    open_type = _get_open_type(ctx, bar)
    open_cash = _safe_float(ctx.get("open_cash") or bar.get("open_cash"))
    asia_close = _safe_float(ctx.get("asia_close"))
    asia_open = _safe_float(ctx.get("asia_open"))
    ib_complete = bool(ctx.get("ib_complete") or bar.get("ib_complete"))
    inside_va = bool(ctx.get("inside_value_area") or bar.get("inside_value_area"))
    ib_range = _safe_float(ctx.get("ib_range") or bar.get("ib_range"))
    prev_vah = _safe_float(ctx.get("prev_vah") or bar.get("prev_vah"))
    prev_val = _safe_float(ctx.get("prev_val") or bar.get("prev_val"))
    tick_size = _safe_float(ctx.get("tick_size")) or 0.25

    # Story trackers (consumer NSM)
    slope_60 = float(story.get("slope_close_60", 0.0))
    hh_60 = int(story.get("hh_count_60", 0))
    ll_60 = int(story.get("ll_count_60", 0))
    bars_since_BOS = int(story.get("bars_since_last_BOS", -1))

    # Previous close (depuis bars_history non-accessible NSM, on track via state.engine_states)
    prev_close = current.engine_states.get("prev_close")

    # Swing references
    swing_high = _swing_high_price(swing_state)
    swing_low = _swing_low_price(swing_state)

    # T32: INVALIDATED + session_date_trading changed → PRE_OPEN_NEUTRAL
    sdt = bar.get("session_date_trading")
    if state == NarrativeState.INVALIDATED:
        if sdt != current.current_session_date_trading:
            return (
                NarrativeState.PRE_OPEN_NEUTRAL, 0, 0.5,
                {"trigger": "T32_sdt_change_from_invalidated"},
            )
        return None  # stay INVALIDATED

    # T22: any (sauf INVAL) + low<=last_swing_low + close>last_swing_low+2*tick
    # + vol_zscore>+1.5 + bars_since_BOS>5 → WYCKOFF_SPRING_LONG
    if (low is not None and close is not None and swing_low is not None
            and vol_z is not None and atr is not None):
        if (low <= swing_low
                and close > swing_low + 2 * tick_size
                and vol_z > 1.5
                and bars_since_BOS > 5):
            return (
                NarrativeState.WYCKOFF_SPRING_LONG, +1, 0.85,
                {"trigger": "T22_wyckoff_spring", "low": low, "swing_low": swing_low,
                 "close": close, "vol_z": vol_z, "bars_since_BOS": bars_since_BOS},
            )

    # T23: any (sauf INVAL) + high>=last_swing_high + close<last_swing_high-2*tick
    # + vol_zscore>+1.5 + bars_since_BOS>5 → WYCKOFF_UPTHRUST_SHORT
    if (high is not None and close is not None and swing_high is not None
            and vol_z is not None and atr is not None):
        if (high >= swing_high
                and close < swing_high - 2 * tick_size
                and vol_z > 1.5
                and bars_since_BOS > 5):
            return (
                NarrativeState.WYCKOFF_UPTHRUST_SHORT, -1, 0.85,
                {"trigger": "T23_wyckoff_upthrust", "high": high, "swing_high": swing_high,
                 "close": close, "vol_z": vol_z, "bars_since_BOS": bars_since_BOS},
            )

    # T24/T25/T26/T27 : WYCKOFF spring/upthrust exit conditions
    if state == NarrativeState.WYCKOFF_SPRING_LONG and atr is not None:
        if close is not None and swing_low is not None:
            if close > swing_low + atr:
                return (
                    NarrativeState.TREND_UP_CONTINUATION, +1, 0.80,
                    {"trigger": "T24_spring_recovery_confirmed"},
                )
            if close < swing_low - atr:
                return (
                    NarrativeState.INVALIDATED, 0, 0.0,
                    {"trigger": "T26_spring_failed"},
                )

    if state == NarrativeState.WYCKOFF_UPTHRUST_SHORT and atr is not None:
        if close is not None and swing_high is not None:
            if close < swing_high - atr:
                return (
                    NarrativeState.TREND_DOWN_CONTINUATION, -1, 0.80,
                    {"trigger": "T25_upthrust_confirmed"},
                )
            if close > swing_high + atr:
                return (
                    NarrativeState.INVALIDATED, 0, 0.0,
                    {"trigger": "T27_upthrust_failed"},
                )

    # T28: TREND_UP + vol_zscore>+2.5 + close<open + bar_range>2*atr → EXHAUSTION_TOP
    if state == NarrativeState.TREND_UP_CONTINUATION:
        if (vol_z is not None and vol_z > 2.5 and close is not None and open_ is not None
                and high is not None and low is not None and atr is not None):
            if close < open_ and (high - low) > 2 * atr:
                return (
                    NarrativeState.EXHAUSTION_TOP, -1, 0.75,
                    {"trigger": "T28_exhaustion_top", "vol_z": vol_z, "bar_range": high - low},
                )

    # T29: TREND_DOWN + vol_zscore>+2.5 + close>open + bar_range>2*atr → EXHAUSTION_BOTTOM
    if state == NarrativeState.TREND_DOWN_CONTINUATION:
        if (vol_z is not None and vol_z > 2.5 and close is not None and open_ is not None
                and high is not None and low is not None and atr is not None):
            if close > open_ and (high - low) > 2 * atr:
                return (
                    NarrativeState.EXHAUSTION_BOTTOM, +1, 0.75,
                    {"trigger": "T29_exhaustion_bottom", "vol_z": vol_z, "bar_range": high - low},
                )

    # T30: EXHAUSTION_TOP + next.close<high-atr → INVALIDATED
    if state == NarrativeState.EXHAUSTION_TOP and atr is not None:
        if close is not None and high is not None and close < high - atr:
            return (
                NarrativeState.INVALIDATED, 0, 0.0,
                {"trigger": "T30_exhaustion_top_followthrough"},
            )

    # T31: EXHAUSTION_BOTTOM + next.close>low+atr → INVALIDATED
    if state == NarrativeState.EXHAUSTION_BOTTOM and atr is not None:
        if close is not None and low is not None and close > low + atr:
            return (
                NarrativeState.INVALIDATED, 0, 0.0,
                {"trigger": "T31_exhaustion_bottom_followthrough"},
            )

    # T20: TREND_UP_CONT + close<last_swing_low + close[-1]>=last_swing_low + vol_zscore>0
    if state == NarrativeState.TREND_UP_CONTINUATION:
        if (close is not None and swing_low is not None and prev_close is not None
                and vol_z is not None):
            if close < swing_low and prev_close >= swing_low and vol_z > 0:
                return (
                    NarrativeState.BREAKDOWN_CONTINUATION, -1, 0.70,
                    {"trigger": "T20_BOS_bearish_from_trendup", "swing_low": swing_low},
                )

    # T21: TREND_DOWN_CONT + close>last_swing_high + close[-1]<=last_swing_high + vol_zscore>0
    if state == NarrativeState.TREND_DOWN_CONTINUATION:
        if (close is not None and swing_high is not None and prev_close is not None
                and vol_z is not None):
            if close > swing_high and prev_close <= swing_high and vol_z > 0:
                return (
                    NarrativeState.BREAKOUT_CONTINUATION, +1, 0.70,
                    {"trigger": "T21_BOS_bullish_from_trenddown", "swing_high": swing_high},
                )

    # T10: OPEN_DRIVE_UP + bar_idx>30 + story.hh_count_60>=3 → TREND_UP_CONTINUATION
    if state == NarrativeState.OPEN_DRIVE_UP and bar_idx > 30 and hh_60 >= 3:
        return (
            NarrativeState.TREND_UP_CONTINUATION, +1, 0.80,
            {"trigger": "T10_open_drive_up_continuation", "hh_60": hh_60},
        )

    # T11: OPEN_DRIVE_DOWN + bar_idx>30 + story.ll_count_60>=3 → TREND_DOWN_CONTINUATION
    if state == NarrativeState.OPEN_DRIVE_DOWN and bar_idx > 30 and ll_60 >= 3:
        return (
            NarrativeState.TREND_DOWN_CONTINUATION, -1, 0.80,
            {"trigger": "T11_open_drive_down_continuation", "ll_60": ll_60},
        )

    # T12: OPEN_DRIVE_UP + close<open_cash + vol_zscore_20<-0.5 → OPEN_ROTATION
    if state == NarrativeState.OPEN_DRIVE_UP:
        if (close is not None and open_cash is not None and vol_z is not None
                and close < open_cash and vol_z < -0.5):
            return (
                NarrativeState.OPEN_ROTATION, 0, 0.5,
                {"trigger": "T12_open_drive_up_reverted"},
            )

    # T13: OPEN_DRIVE_DOWN + close>open_cash + vol_zscore_20<-0.5 → OPEN_ROTATION
    if state == NarrativeState.OPEN_DRIVE_DOWN:
        if (close is not None and open_cash is not None and vol_z is not None
                and close > open_cash and vol_z < -0.5):
            return (
                NarrativeState.OPEN_ROTATION, 0, 0.5,
                {"trigger": "T13_open_drive_down_reverted"},
            )

    # T14: OPEN_TEST_DRIVE + bar_idx∈[5,15] + close>open_cash+0.5*atr + vol_zscore>+0.5 → OPEN_DRIVE_UP
    if state == NarrativeState.OPEN_TEST_DRIVE and 5 <= bar_idx <= 15:
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close > open_cash + 0.5 * atr and vol_z > 0.5):
            return (
                NarrativeState.OPEN_DRIVE_UP, +1, 0.70,
                {"trigger": "T14_OTD_confirmed_up"},
            )

    # T15: OPEN_TEST_DRIVE + bar_idx∈[5,15] + close<open_cash-0.5*atr + vol_zscore>+0.5 → OPEN_DRIVE_DOWN
    if state == NarrativeState.OPEN_TEST_DRIVE and 5 <= bar_idx <= 15:
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close < open_cash - 0.5 * atr and vol_z > 0.5):
            return (
                NarrativeState.OPEN_DRIVE_DOWN, -1, 0.70,
                {"trigger": "T15_OTD_confirmed_down"},
            )

    # T16: OPEN_TEST_DRIVE + bar_idx_session>15 → OPEN_ROTATION
    if state == NarrativeState.OPEN_TEST_DRIVE and bar_idx > 15:
        return (
            NarrativeState.OPEN_ROTATION, 0, 0.4,
            {"trigger": "T16_OTD_timeout_rotation"},
        )

    # T17: OPEN_ROTATION + ib_complete + inside_value_area + ib_range/atr<1.2 → RANGE_RESPECTED
    if state == NarrativeState.OPEN_ROTATION and ib_complete and inside_va:
        if ib_range is not None and atr is not None and atr > 0 and (ib_range / atr) < 1.2:
            return (
                NarrativeState.RANGE_RESPECTED, 0, 0.70,
                {"trigger": "T17_rotation_range_respected"},
            )

    # T18: RANGE_RESPECTED + close>prev_vah + close[-1]>prev_vah → BREAKOUT_CONTINUATION
    if state == NarrativeState.RANGE_RESPECTED:
        if (close is not None and prev_vah is not None and prev_close is not None
                and close > prev_vah and prev_close > prev_vah):
            return (
                NarrativeState.BREAKOUT_CONTINUATION, +1, 0.75,
                {"trigger": "T18_range_breakout_VAH"},
            )

    # T19: RANGE_RESPECTED + close<prev_val + close[-1]<prev_val → BREAKDOWN_CONTINUATION
    if state == NarrativeState.RANGE_RESPECTED:
        if (close is not None and prev_val is not None and prev_close is not None
                and close < prev_val and prev_close < prev_val):
            return (
                NarrativeState.BREAKDOWN_CONTINUATION, -1, 0.75,
                {"trigger": "T19_range_breakdown_VAL"},
            )

    # T6: PRE_OPEN_* + session=NY + open_type=0 + close>open_cash+atr + vol_zscore>+1.0 → OPEN_DRIVE_UP
    if state in _PRE_OPEN_STATES and session == "NY" and open_type == 0:
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close > open_cash + atr and vol_z > 1.0):
            return (
                NarrativeState.OPEN_DRIVE_UP, +1, 0.85,
                {"trigger": "T6_open_drive_up", "vol_z": vol_z, "atr_mult": close - open_cash},
            )

    # T7: PRE_OPEN_* + session=NY + open_type=0 + close<open_cash-atr + vol_zscore>+1.0 → OPEN_DRIVE_DOWN
    if state in _PRE_OPEN_STATES and session == "NY" and open_type == 0:
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close < open_cash - atr and vol_z > 1.0):
            return (
                NarrativeState.OPEN_DRIVE_DOWN, -1, 0.85,
                {"trigger": "T7_open_drive_down", "vol_z": vol_z, "atr_mult": open_cash - close},
            )

    # T8: PRE_OPEN_* + session=NY + open_type=1 → OPEN_TEST_DRIVE
    if state in _PRE_OPEN_STATES and session == "NY" and open_type == 1:
        return (
            NarrativeState.OPEN_TEST_DRIVE, 0, 0.5,
            {"trigger": "T8_open_test_drive"},
        )

    # T9: PRE_OPEN_* + session=NY + open_type=3 → OPEN_ROTATION
    if state in _PRE_OPEN_STATES and session == "NY" and open_type == 3:
        return (
            NarrativeState.OPEN_ROTATION, 0, 0.6,
            {"trigger": "T9_open_auction_rotation"},
        )

    # T2: PRE_OPEN_NEUTRAL + slope_60<-0.2 + asia_close<asia_open → PRE_OPEN_BEARISH
    if state == NarrativeState.PRE_OPEN_NEUTRAL and session in ("ASIA", "LONDON"):
        if slope_60 < -0.2 and asia_close is not None and asia_open is not None:
            if asia_close < asia_open:
                return (
                    NarrativeState.PRE_OPEN_BEARISH, -1, 0.6,
                    {"trigger": "T2_preopen_bearish", "slope_60": slope_60},
                )

    # T3: PRE_OPEN_NEUTRAL + slope_60>+0.2 + asia_close>asia_open → PRE_OPEN_BULLISH
    if state == NarrativeState.PRE_OPEN_NEUTRAL and session in ("ASIA", "LONDON"):
        if slope_60 > 0.2 and asia_close is not None and asia_open is not None:
            if asia_close > asia_open:
                return (
                    NarrativeState.PRE_OPEN_BULLISH, +1, 0.6,
                    {"trigger": "T3_preopen_bullish", "slope_60": slope_60},
                )

    # T4: PRE_OPEN_BEARISH + slope_60 ∈ [-0.1, +0.1] → PRE_OPEN_NEUTRAL
    if state == NarrativeState.PRE_OPEN_BEARISH and -0.1 <= slope_60 <= 0.1:
        return (
            NarrativeState.PRE_OPEN_NEUTRAL, 0, 0.5,
            {"trigger": "T4_rebalance_neutral", "slope_60": slope_60},
        )

    # T5: PRE_OPEN_BULLISH + slope_60 ∈ [-0.1, +0.1] → PRE_OPEN_NEUTRAL
    if state == NarrativeState.PRE_OPEN_BULLISH and -0.1 <= slope_60 <= 0.1:
        return (
            NarrativeState.PRE_OPEN_NEUTRAL, 0, 0.5,
            {"trigger": "T5_rebalance_neutral", "slope_60": slope_60},
        )

    return None  # No transition, stay current state


# ═══════════════════════════════════════════════════════════════════════════
# NarrativeStateMachine class
# ═══════════════════════════════════════════════════════════════════════════

class NarrativeStateMachine:
    """State machine narrative globale par symbole.

    1 instance NSM, dict[symbol, NarrativeStateSnapshot]. Pickle persistent
    via bot3_narrative_persistence (ADR 0003 atomic commun NSM + Story).

    Concurrency : threading.RLock per-symbol (mp_engine + paper_trader parallel).

    Phase 1 scope (TRACKING ONLY) :
      - 17 etats + 32 transitions deterministes
      - Events buffer consume par mp_engine pour emit logs
      - Anti-flicker guard (>8 transitions/jour/sym)
      - PAS de ScenarioValidator (Phase 2)
      - PAS de PlotTwistDetectors (Phase 2)
      - PAS de DirectionResolver coupling (Phase 3)
    """

    def __init__(self) -> None:
        """Init empty state. Pickle recovery deferred bot3_narrative_persistence."""
        self._states: dict[str, NarrativeStateSnapshot] = {}
        self._locks: dict[str, threading.RLock] = {}
        self._lock_creation_lock: threading.Lock = threading.Lock()
        self._pending_events: list[NarrativeEvent] = []

    def _get_lock(self, symbol: str) -> threading.RLock:
        """Lazy-create RLock per symbol. Thread-safe creation."""
        if symbol not in self._locks:
            with self._lock_creation_lock:
                if symbol not in self._locks:  # double-check
                    self._locks[symbol] = threading.RLock()
        return self._locks[symbol]

    def transition(
        self,
        symbol: str,
        bar: dict,
        ctx: dict,
        regime: Any,
        story_trackers: dict[str, Any],
        swing_state: Any,
        log_fn: Callable[..., None] | None = None,
    ) -> NarrativeStateSnapshot | None:
        """Evaluate transitions et update state.

        Args:
            symbol: ES.c.0 / NQ.c.0 / MGC.v.0.
            bar: payload V4 enriched canonical (dict ~467 cols).
            ctx: output bot3_context_analyzer.analyze_context.
            regime: RegimeSnapshot (output regime_engine.compute_regime). Not used Phase 1.
            story_trackers: dict snapshot output bot3_story_trackers.update_story_trackers.
            swing_state: SessionsSwingsLagState ref.
            log_fn: callable optionnel pour test capture.

        Returns:
            NarrativeStateSnapshot post-transition (meme si stay).
            None si symbol/bar invalide.
        """
        if not symbol:
            return None
        _ = regime  # Phase 1 unused (Phase 3 DirectionResolver)

        with self._get_lock(symbol):
            current = self._states.get(symbol)
            if current is None:
                # Seed cold start : PRE_OPEN_NEUTRAL
                current = NarrativeStateSnapshot(
                    schema_version=NSM_SCHEMA_VERSION,
                    symbol=symbol,
                    state=NarrativeState.PRE_OPEN_NEUTRAL,
                    state_entered_at_ts=bar.get("ts_event_iso") or bar.get("ts_event"),
                    state_entered_at_bar_idx=0,
                    bar_idx_current=0,
                    bias_dir=0,
                    confidence=0.5,
                    triggering_features={"trigger": "cold_start"},
                    current_session_date_trading=bar.get("session_date_trading"),
                )
                self._states[symbol] = current

            # Increment bar counter
            current.bar_idx_current += 1

            # Reset n_transitions_today si SDT change
            # NB: ne PAS mettre a jour current.current_session_date_trading ici —
            # _evaluate_transitions (T32) en a besoin pour detecter le change.
            # L'update est faite apres evaluate (cf. ligne ~702).
            sdt = bar.get("session_date_trading")
            sdt_changed = sdt != current.current_session_date_trading
            if sdt_changed:
                emit(
                    "BOT3_NSM_SESSION_RESET",
                    log_fn=log_fn,
                    sym=symbol,
                    new_sdt=str(sdt),
                    n=current.n_transitions_today,
                )
                current.n_transitions_today = 0

            # Anti-flicker guard
            if current.n_transitions_today > FLICKER_GUARD_THRESHOLD:
                emit(
                    "BOT3_NSM_FLICKER_GUARD",
                    log_fn=log_fn,
                    sym=symbol,
                    n=current.n_transitions_today,
                )
                # Still update prev_close + return current (no transition)
                close = _safe_float(bar.get("close"))
                if close is not None:
                    current.engine_states["prev_close"] = close
                return current

            # Evaluate transitions
            result = _evaluate_transitions(current, bar, ctx, story_trackers, swing_state)

            if result is not None:
                next_state, bias_dir, confidence, triggering = result
                if next_state != current.state:
                    from_state = current.state
                    bar_ts = bar.get("ts_event_iso") or bar.get("ts_event") or ""
                    # Apply transition
                    current.state = next_state
                    current.state_entered_at_ts = bar_ts
                    current.state_entered_at_bar_idx = current.bar_idx_current
                    current.bias_dir = bias_dir
                    current.confidence = confidence
                    current.triggering_features = triggering
                    current.n_transitions_today += 1

                    # Emit transition event + log
                    event = NarrativeEvent(
                        event_type="STATE_TRANSITION",
                        from_state=from_state,
                        to_state=next_state,
                        bar_ts=bar_ts,
                        bar_idx=current.bar_idx_current,
                        symbol=symbol,
                        payload={
                            "bias_dir": bias_dir,
                            "confidence": confidence,
                            "triggering": triggering,
                        },
                    )
                    self._pending_events.append(event)
                    emit(
                        "BOT3_NSM_STATE_TRANSITION",
                        log_fn=log_fn,
                        sym=symbol,
                        from_state=from_state.value,
                        to_state=next_state.value,
                        bias_dir=bias_dir,
                        confidence=confidence,
                        bar_ts=bar_ts,
                    )

                    # If INVALIDATED emit additional CRITIQUE
                    if next_state == NarrativeState.INVALIDATED:
                        emit(
                            "BOT3_NSM_INVALIDATED",
                            log_fn=log_fn,
                            sym=symbol,
                            from_state=from_state.value,
                            trigger=triggering.get("trigger", ""),
                            bar_ts=bar_ts,
                        )
            else:
                # Pas de transition, observe only (throttle to INFO)
                bars_in_state = current.bar_idx_current - current.state_entered_at_bar_idx
                emit(
                    "BOT3_NSM_STATE_OBSERVE",
                    log_fn=log_fn,
                    sym=symbol,
                    state=current.state.value,
                    bar_idx=current.bar_idx_current,
                    bars_in_state=bars_in_state,
                )

            # Update prev_close pour next bar BOS detection
            close = _safe_float(bar.get("close"))
            if close is not None:
                current.engine_states["prev_close"] = close

            # Sync current_session_date_trading apres evaluate_transitions
            # (T32 a deja consomme la valeur prev pour detecter le change).
            if sdt_changed:
                current.current_session_date_trading = sdt

            return current

    def current(self, symbol: str) -> NarrativeStateSnapshot | None:
        """Returns current snapshot or None si symbol jamais vu."""
        with self._get_lock(symbol):
            return self._states.get(symbol)

    def consume_events(self) -> list[NarrativeEvent]:
        """Pop all pending events buffer. Caller emit logs externe si necessaire."""
        evts, self._pending_events = self._pending_events, []
        return evts

    def __getstate__(self) -> dict:
        """Exclude _locks + _lock_creation_lock du pickle."""
        state = self.__dict__.copy()
        state.pop("_locks", None)
        state.pop("_lock_creation_lock", None)
        return state

    def __setstate__(self, state: dict) -> None:
        """Restore + recreate locks au load."""
        self.__dict__.update(state)
        self._locks = {}
        self._lock_creation_lock = threading.Lock()
