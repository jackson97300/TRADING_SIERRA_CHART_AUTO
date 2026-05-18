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
# 2026-05-18 PM : refonte post-review NOGO market-analyst + GO-RES code-reviewer.
#                 Fixes critiques :
#                 B1 (PATTERN_11_INVERSE) : import OpenType IntEnum officielle
#                   (CORE/game_changers.py:38) au lieu de int hardcoded 0/1/3.
#                   T6/T7 split par OD_UP/OD_DOWN, T8 OTD_UP/OTD_DOWN, T9 OAIR.
#                 B2 : fusion BREAKOUT/BREAKDOWN_CONTINUATION dans TREND_UP/DOWN
#                   (17 -> 15 etats). Distinction semantique recreable via bars_in_state.
#                 B3 : inverser T30/T31. EXHAUSTION + follow-through (close<high-atr)
#                   = thesis confirmee -> TREND_DOWN. EXHAUSTION + no follow-through
#                   (close>=high) -> INVALIDATED (T30b/T31b).
#                 F1 : _events_lock separe pour _pending_events (race condition
#                   consume_events vs transition multi-symbol).
#                 F6 : bar_idx_current += 1 APRES _evaluate_transitions (parallele
#                   au fix T32 sdt sync).
#                 F5 : magic numbers (vol_z thresholds, conf levels) extracted
#                   en module-level constants.
#                 M1 : guard whitelist Wyckoff Spring/Upthrust (etats Phase A+B prerequis).
#                 M2 : conf Wyckoff Spring/Upthrust 0.85 -> 0.65 pre-SOS (Pruden Ch.7).
#                 T1 ajout : * + sdt change + session=ASIA -> PRE_OPEN_NEUTRAL
#                   (Sierra Chart session-reset convention, anti sticky state).
# 2026-05-18 PM (3) : audit replay 5 jours ES revele coverage gap OAOR/ORR.
#                 11/05-12/05 OK (OTD/OD couvre par T6-T9). 13/05-14/05-15/05 ZERO
#                 transition car open_type=8 (OAOR_UP) ou 9 (OAOR_DOWN) non couvert.
#                 Dalton MOM Ch.8 : OAOR = highest-confidence directional setup.
#                 Verdict market-analyst + ml-trainer NOGO. Ajout :
#                 T6bis : PRE_OPEN_* + NY + OAOR_UP + close>open_cash → OPEN_DRIVE_UP
#                 T7bis : PRE_OPEN_* + NY + OAOR_DOWN + close<open_cash → OPEN_DRIVE_DOWN
#                 T9bis : PRE_OPEN_* + NY + ORR_UP|DOWN → OPEN_ROTATION (reversal)
#                 INCIDENT_LOG : VALIDATION_MISS spec NSM incomplete vs realite marche.
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

try:
    from CORE.bot3_narrative_logging import emit
    from CORE.game_changers import OpenType
except ModuleNotFoundError:
    from bot3_narrative_logging import emit  # type: ignore[no-redef]
    from game_changers import OpenType  # type: ignore[no-redef]

NSM_SCHEMA_VERSION: str = "2.0.0"
# FLICKER_GUARD_THRESHOLD calibre 12 (vs 8 initial) post-audit replay 18/05 :
# data live ES mai 2026 montre 9 transitions/jour typique sur jours actifs
# (Wyckoff Spring x2 + BOS + Upthrust + Trend + Exhaustion + reset cross-session
# = setup Dalton-Wyckoff multi-phase canon). Seuil 8 declenchait sur 60% sessions
# actives = trop conservateur. Seuil 12 = block uniquement vraies cascades flicker
# (> 12 transitions/jour = signal noise vs vraie histoire narrative).
FLICKER_GUARD_THRESHOLD: int = 12

# ─── Magic numbers extraits (F5 fix) ──────────────────────────────────────
# Volume z-score thresholds par regime
VOL_Z_SPRING_MIN: float = 1.5       # T22/T23 Wyckoff Spring/Upthrust volume canon
VOL_Z_EXHAUSTION_MIN: float = 2.5   # T28/T29 climax volume Pruden
VOL_Z_OPEN_DRIVE_MIN: float = 1.0   # T6/T7 OPEN_DRIVE Dalton volume confirm
VOL_Z_OTD_CONFIRM_MIN: float = 0.5  # T14/T15 OTD direction confirm
VOL_Z_BOS_MIN: float = 0.0          # T20/T21 BOS volume confirm (faible exigence)
VOL_Z_REVERT_MAX: float = -0.5      # T12/T13 OPEN_DRIVE revert vol exhaustion

# ATR multiples
ATR_MULT_OD: float = 1.0                  # T6/T7 close vs open_cash distance
ATR_MULT_EXHAUSTION_RANGE: float = 2.0    # T28/T29 bar_range exhaustion
ATR_MULT_WYCKOFF_RECOVERY: float = 1.0    # T24/T25 spring recovery confirm
ATR_MULT_OTD_DIRECTION: float = 0.5       # T14/T15 OTD threshold close vs open

# Slope thresholds (Pre-Open)
SLOPE_PREOPEN_THRESHOLD: float = 0.2      # T2/T3 slope_60 directional
SLOPE_NEUTRAL_BAND: float = 0.1           # T4/T5 rebalance neutral band

# Confidence levels (calibre Dalton/Wyckoff doctrine)
CONF_OPEN_DRIVE: float = 0.85             # T6/T7 OD = pattern Dalton conviction max
CONF_WYCKOFF_PRE_SOS: float = 0.65        # T22/T23 Spring/Upthrust AVANT SOS (Pruden 50-65%)
CONF_WYCKOFF_POST_SOS: float = 0.80       # T24/T25 Spring/Upthrust confirme SOS
CONF_TREND_CONTINUATION: float = 0.80     # T10/T11 OD -> TREND
CONF_BOS: float = 0.70                    # T20/T21 BOS structurel
CONF_RANGE_BREAKOUT: float = 0.75         # T18/T19 range breakout VAH/VAL
CONF_EXHAUSTION: float = 0.75             # T28/T29 EXHAUSTION_TOP/BOTTOM
CONF_RANGE_RESPECTED: float = 0.70        # T17 OPEN_ROTATION -> RANGE
CONF_PRE_OPEN_DIRECTIONAL: float = 0.6    # T2/T3 PRE_OPEN_BEARISH/BULLISH
CONF_OTD_CONFIRM: float = 0.70            # T14/T15 OTD -> OD
CONF_OTD_NEUTRAL: float = 0.5             # T8 OTD entry conf neutre
CONF_OPEN_ROTATION: float = 0.6           # T9 OAIR conf
CONF_ROTATION_TIMEOUT: float = 0.4        # T16 OTD timeout
CONF_NEUTRAL: float = 0.5                 # T4/T5/T1 reset neutral
CONF_INVALIDATED: float = 0.0             # INVALIDATED state

# Other thresholds
BARS_SINCE_BOS_MIN_WYCKOFF: int = 5       # T22/T23 anti immediate Spring post-BOS
TICK_WYCKOFF_MULT: float = 2.0            # T22/T23 close > swing + 2*tick threshold
IB_RANGE_ATR_MAX: float = 1.2             # DEPRECATED 2026-05-18 : ancienne formule T17 (ib_range/atr_daily < 1.2). Remplacee par canon Dalton (no_break + inside_va). Constante gardee pour back-compat imports externes mais non utilisee. A retirer apres review tests.
BARS_SINCE_BOS_MIN_RANGE: int = 90        # T17 anti-cycle TREND<->RANGE : RANGE_RESPECTED requires >=90 min depuis dernier swing BOS (canon Dalton : range confirme apres consolidation prolongee, pas pullback court)
BAR_IDX_OD_CONTINUATION_MIN: int = 30     # T10/T11 OD -> TREND validation bar threshold
BAR_IDX_OTD_WINDOW_MIN: int = 5           # T14/T15 OTD confirm window start
BAR_IDX_OTD_WINDOW_MAX: int = 15          # T14/T15 OTD confirm window end
BAR_IDX_OTD_TIMEOUT: int = 15             # T16 OTD timeout (>15 -> rotation)
TICK_SIZE_DEFAULT: float = 0.25           # ES/NQ default; MGC=0.10 via ctx


class NarrativeState(Enum):
    """15 etats narratifs du marche pour Bot 3 v2.

    Cf DOCS/specs/2026-05-18-bot3v2-phase1-nsm-spec.md section 2.1.

    Note B2 fix : BREAKOUT/BREAKDOWN_CONTINUATION fusionnes avec TREND_UP/DOWN_
    CONTINUATION. La distinction semantique "BOS recent" vs "trend etabli" est
    recreable via bars_in_state (snapshot.bar_idx_current - state_entered_at_bar_idx).
    17 -> 15 etats apres review market-analyst (absorbing states sans transition out).
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
    # Sessions etablies (BOS et breakout VAH/VAL fusionnes ici via bars_in_state)
    TREND_UP_CONTINUATION = "TREND_UP_CONTINUATION"
    TREND_DOWN_CONTINUATION = "TREND_DOWN_CONTINUATION"
    RANGE_RESPECTED = "RANGE_RESPECTED"
    # Wyckoff Phase C (reversal setups)
    WYCKOFF_SPRING_LONG = "WYCKOFF_SPRING_LONG"
    WYCKOFF_UPTHRUST_SHORT = "WYCKOFF_UPTHRUST_SHORT"
    # Exhaustion / Terminal
    EXHAUSTION_TOP = "EXHAUSTION_TOP"
    EXHAUSTION_BOTTOM = "EXHAUSTION_BOTTOM"
    # Reset / error
    INVALIDATED = "INVALIDATED"


# Whitelist M1 fix : etats permis pour Wyckoff Phase C (Spring/Upthrust)
# Phase A (SC+AR) + Phase B (range building) prerequis Pruden Ch.7.
# Acceptable : range respecte, trend contraire (epuisement), open rotation.
_WYCKOFF_SPRING_ALLOWED_STATES: frozenset[NarrativeState] = frozenset({
    NarrativeState.RANGE_RESPECTED,
    NarrativeState.TREND_DOWN_CONTINUATION,
    NarrativeState.OPEN_ROTATION,
})
_WYCKOFF_UPTHRUST_ALLOWED_STATES: frozenset[NarrativeState] = frozenset({
    NarrativeState.RANGE_RESPECTED,
    NarrativeState.TREND_UP_CONTINUATION,
    NarrativeState.OPEN_ROTATION,
})


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
    """Evaluate les 32+ transitions T1-T32 dans l'ordre priorite.

    Retourne (next_state, bias_dir, confidence, triggering_features) si transition
    legitime, None sinon (= stay current state).

    Premier match wins. Anti-flicker guard applique en amont par caller.

    INVARIANTS :
    - T1 (cross-session reset) prioritaire absolu : capture le cas general avant T32
    - T22/T23 (Wyckoff) ordre prioritaire vs T20/T21 (BOS) : Spring/Upthrust
      decouvre AVANT que le BOS T20/T21 fire (mutex naturelle car close conditions
      sont opposees mais guard whitelist M1 ajoute pour proteger)
    - T30/T31 (EXHAUSTION follow-through) interprete close<high-atr comme
      CONFIRMATION de thesis baissiere (-> TREND_DOWN_CONT), pas invalidation
      (fix B3 post-review market-analyst NOGO)
    """
    state = current.state
    close = _safe_float(bar.get("close"))
    high = _safe_float(bar.get("high"))
    low = _safe_float(bar.get("low"))
    open_ = _safe_float(bar.get("open"))
    atr = _safe_float(bar.get("atr"))
    # ATR intraday (= ATR Wilder 14-bars 1-min) pour conditions PAR-BAR :
    # T22-T27 Wyckoff recovery, T28/T29 EXHAUSTION climax, T30/T31 follow-through.
    # Source primaire : bar["atr_intraday"] (alias explicite ajoute par live_enricher
    # ou replay tool). Fallback : bar["atr_14m"] (live enricher v1.0).
    # Dernier fallback DEGRADE : bar["atr"] (incoherent d'echelle si atr daily,
    # mais evite crash). Le warning BOT3_NSM_ATR_FALLBACK_DAILY est emit par
    # NarrativeStateMachine.transition() (methode classe) qui a access a symbol.
    # Cf incident 2026-05-18 : NSM utilisait atr daily (~17 pts ES) pour seuil
    # bar_range > 2*atr = 35 pts impossible sur 1-min (p99 bar_range = 7 pts).
    atr_intraday = (
        _safe_float(bar.get("atr_intraday"))
        or _safe_float(bar.get("atr_14m"))
        or atr  # fallback degrade, warning emit cote NarrativeStateMachine.transition()
    )
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
    tick_size = _safe_float(ctx.get("tick_size")) or TICK_SIZE_DEFAULT

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

    # T1: * + session_date_trading changed + session=ASIA → PRE_OPEN_NEUTRAL
    # Sierra Chart session-reset convention : sdt change a 18:00 ET veille marque
    # un nouveau jour de trading. NSM doit forget l'etat narratif du jour D-1 car
    # 1) Pre-open du jour D commence avec contexte clean (Asia/London Bias).
    # 2) Eviter sticky state ex: TREND_UP du jour D-1 colle au matin du jour D
    #    (probleme observe Bot 3 v1 multi-jours).
    # NB: cite plus loin Mark Douglas concernant la psycho trader, pas l'FSM.
    sdt = bar.get("session_date_trading")
    sdt_changed = sdt != current.current_session_date_trading
    if sdt_changed and session == "ASIA":
        return (
            NarrativeState.PRE_OPEN_NEUTRAL, 0, CONF_NEUTRAL,
            {"trigger": "T1_cross_session_reset", "new_sdt": str(sdt)},
        )

    # T32: INVALIDATED + session_date_trading changed → PRE_OPEN_NEUTRAL
    # (couvre cas INVALIDATED hors fenetre ASIA, ex: session=LONDON apres invalidation)
    if state == NarrativeState.INVALIDATED:
        if sdt_changed:
            return (
                NarrativeState.PRE_OPEN_NEUTRAL, 0, CONF_NEUTRAL,
                {"trigger": "T32_sdt_change_from_invalidated"},
            )
        return None  # stay INVALIDATED (anti instant recovery)

    # T22: WYCKOFF_SPRING_LONG (guard whitelist M1)
    # state in {RANGE_RESPECTED, TREND_DOWN_CONTINUATION, OPEN_ROTATION}
    # + low<=last_swing_low + close>last_swing_low+2*tick + vol_zscore>+1.5
    # + bars_since_BOS>5 → WYCKOFF_SPRING_LONG (conf 0.65 pre-SOS)
    if state in _WYCKOFF_SPRING_ALLOWED_STATES:
        if (low is not None and close is not None and swing_low is not None
                and vol_z is not None and atr_intraday is not None):
            if (low <= swing_low
                    and close > swing_low + TICK_WYCKOFF_MULT * tick_size
                    and vol_z > VOL_Z_SPRING_MIN
                    and bars_since_BOS > BARS_SINCE_BOS_MIN_WYCKOFF):
                return (
                    NarrativeState.WYCKOFF_SPRING_LONG, +1, CONF_WYCKOFF_PRE_SOS,
                    {"trigger": "T22_wyckoff_spring", "low": low,
                     "swing_low": swing_low, "close": close, "vol_z": vol_z,
                     "bars_since_BOS": bars_since_BOS},
                )

    # T23: WYCKOFF_UPTHRUST_SHORT (guard whitelist M1)
    # state in {RANGE_RESPECTED, TREND_UP_CONTINUATION, OPEN_ROTATION}
    # + high>=last_swing_high + close<last_swing_high-2*tick + vol_zscore>+1.5
    # + bars_since_BOS>5 → WYCKOFF_UPTHRUST_SHORT (conf 0.65 pre-SOS)
    if state in _WYCKOFF_UPTHRUST_ALLOWED_STATES:
        if (high is not None and close is not None and swing_high is not None
                and vol_z is not None and atr_intraday is not None):
            if (high >= swing_high
                    and close < swing_high - TICK_WYCKOFF_MULT * tick_size
                    and vol_z > VOL_Z_SPRING_MIN
                    and bars_since_BOS > BARS_SINCE_BOS_MIN_WYCKOFF):
                return (
                    NarrativeState.WYCKOFF_UPTHRUST_SHORT, -1, CONF_WYCKOFF_PRE_SOS,
                    {"trigger": "T23_wyckoff_upthrust", "high": high,
                     "swing_high": swing_high, "close": close, "vol_z": vol_z,
                     "bars_since_BOS": bars_since_BOS},
                )

    # T24/T25/T26/T27 : WYCKOFF spring/upthrust exit conditions
    # PAR-BAR : recovery mesure dans la barre actuelle relatif au swing → atr_intraday
    if state == NarrativeState.WYCKOFF_SPRING_LONG and atr_intraday is not None:
        if close is not None and swing_low is not None:
            if close > swing_low + ATR_MULT_WYCKOFF_RECOVERY * atr_intraday:
                return (
                    NarrativeState.TREND_UP_CONTINUATION, +1, CONF_WYCKOFF_POST_SOS,
                    {"trigger": "T24_spring_recovery_confirmed"},
                )
            if close < swing_low - ATR_MULT_WYCKOFF_RECOVERY * atr_intraday:
                return (
                    NarrativeState.INVALIDATED, 0, CONF_INVALIDATED,
                    {"trigger": "T26_spring_failed"},
                )

    if state == NarrativeState.WYCKOFF_UPTHRUST_SHORT and atr_intraday is not None:
        if close is not None and swing_high is not None:
            if close < swing_high - ATR_MULT_WYCKOFF_RECOVERY * atr_intraday:
                return (
                    NarrativeState.TREND_DOWN_CONTINUATION, -1, CONF_WYCKOFF_POST_SOS,
                    {"trigger": "T25_upthrust_confirmed"},
                )
            if close > swing_high + ATR_MULT_WYCKOFF_RECOVERY * atr_intraday:
                return (
                    NarrativeState.INVALIDATED, 0, CONF_INVALIDATED,
                    {"trigger": "T27_upthrust_failed"},
                )

    # T28: TREND_UP + vol_zscore>+2.5 + close<open + bar_range>2*atr_intraday → EXHAUSTION_TOP
    # PAR-BAR : climax = bar exceptionnelle relative au timeframe d'analyse (1-min).
    # Fix 2026-05-18 : atr daily ecrasait seuil 2*atr = 35pts ES impossible.
    # Avec atr_intraday (~1.7pts ES mean batch / ~4.4pts ES live), seuil
    # 2*atr_intraday capture ~3.4% des bars en ratio brut, ~1.1% en intersection
    # vol_z>2.5 & color (empirique ES batch Mai 2026). Sensitivity sweep
    # ATR_MULT_EXHAUSTION_RANGE in {2.0, 2.5, 3.0} prevu Phase 5 walk-forward
    # DSR Lopez (recommendation market-analyst 2026-05-18 review).
    if state == NarrativeState.TREND_UP_CONTINUATION:
        if (vol_z is not None and vol_z > VOL_Z_EXHAUSTION_MIN
                and close is not None and open_ is not None
                and high is not None and low is not None and atr_intraday is not None):
            if close < open_ and (high - low) > ATR_MULT_EXHAUSTION_RANGE * atr_intraday:
                return (
                    NarrativeState.EXHAUSTION_TOP, -1, CONF_EXHAUSTION,
                    {"trigger": "T28_exhaustion_top", "vol_z": vol_z,
                     "bar_range": high - low},
                )

    # T29: TREND_DOWN + vol_zscore>+2.5 + close>open + bar_range>2*atr_intraday → EXHAUSTION_BOTTOM
    if state == NarrativeState.TREND_DOWN_CONTINUATION:
        if (vol_z is not None and vol_z > VOL_Z_EXHAUSTION_MIN
                and close is not None and open_ is not None
                and high is not None and low is not None and atr_intraday is not None):
            if close > open_ and (high - low) > ATR_MULT_EXHAUSTION_RANGE * atr_intraday:
                return (
                    NarrativeState.EXHAUSTION_BOTTOM, +1, CONF_EXHAUSTION,
                    {"trigger": "T29_exhaustion_bottom", "vol_z": vol_z,
                     "bar_range": high - low},
                )

    # T30 (fix B3 INVERSE) :
    # EXHAUSTION_TOP + close<high-atr_intraday → TREND_DOWN_CONTINUATION
    # (follow-through baissier = thesis confirmee, Wyckoff buying climax canon Pruden Ch.7)
    # T30b : EXHAUSTION_TOP + close>=high (high preserve, pas de follow-through)
    #        → INVALIDATED (faux climax)
    # PAR-BAR : follow-through mesure dans la barre actuelle → atr_intraday.
    if state == NarrativeState.EXHAUSTION_TOP and atr_intraday is not None:
        if close is not None and high is not None:
            if close < high - atr_intraday:
                return (
                    NarrativeState.TREND_DOWN_CONTINUATION, -1, CONF_WYCKOFF_POST_SOS,
                    {"trigger": "T30_exhaustion_top_followthrough_confirmed",
                     "close": close, "high": high},
                )
            if close >= high:
                return (
                    NarrativeState.INVALIDATED, 0, CONF_INVALIDATED,
                    {"trigger": "T30b_exhaustion_top_no_followthrough",
                     "close": close, "high": high},
                )

    # T31 (fix B3 INVERSE) :
    # EXHAUSTION_BOTTOM + close>low+atr_intraday → TREND_UP_CONTINUATION
    # (follow-through haussier = thesis confirmee, Wyckoff selling climax canon Pruden Ch.7)
    # T31b : EXHAUSTION_BOTTOM + close<=low → INVALIDATED (faux climax)
    if state == NarrativeState.EXHAUSTION_BOTTOM and atr_intraday is not None:
        if close is not None and low is not None:
            if close > low + atr_intraday:
                return (
                    NarrativeState.TREND_UP_CONTINUATION, +1, CONF_WYCKOFF_POST_SOS,
                    {"trigger": "T31_exhaustion_bottom_followthrough_confirmed",
                     "close": close, "low": low},
                )
            if close <= low:
                return (
                    NarrativeState.INVALIDATED, 0, CONF_INVALIDATED,
                    {"trigger": "T31b_exhaustion_bottom_no_followthrough",
                     "close": close, "low": low},
                )

    # T20 (fusion B2) : TREND_UP_CONT + close<last_swing_low + close[-1]>=last_swing_low
    # + vol_zscore>0 → TREND_DOWN_CONTINUATION (BOS bearish reversal)
    if state == NarrativeState.TREND_UP_CONTINUATION:
        if (close is not None and swing_low is not None and prev_close is not None
                and vol_z is not None):
            if (close < swing_low and prev_close >= swing_low
                    and vol_z > VOL_Z_BOS_MIN):
                return (
                    NarrativeState.TREND_DOWN_CONTINUATION, -1, CONF_BOS,
                    {"trigger": "T20_BOS_bearish_from_trendup",
                     "swing_low": swing_low},
                )

    # T21 (fusion B2) : TREND_DOWN_CONT + close>last_swing_high + close[-1]<=last_swing_high
    # + vol_zscore>0 → TREND_UP_CONTINUATION (BOS bullish reversal)
    if state == NarrativeState.TREND_DOWN_CONTINUATION:
        if (close is not None and swing_high is not None and prev_close is not None
                and vol_z is not None):
            if (close > swing_high and prev_close <= swing_high
                    and vol_z > VOL_Z_BOS_MIN):
                return (
                    NarrativeState.TREND_UP_CONTINUATION, +1, CONF_BOS,
                    {"trigger": "T21_BOS_bullish_from_trenddown",
                     "swing_high": swing_high},
                )

    # T10: OPEN_DRIVE_UP + bar_idx>30 + story.hh_count_60>=3 → TREND_UP_CONTINUATION
    if (state == NarrativeState.OPEN_DRIVE_UP
            and bar_idx > BAR_IDX_OD_CONTINUATION_MIN and hh_60 >= 3):
        return (
            NarrativeState.TREND_UP_CONTINUATION, +1, CONF_TREND_CONTINUATION,
            {"trigger": "T10_open_drive_up_continuation", "hh_60": hh_60},
        )

    # T11: OPEN_DRIVE_DOWN + bar_idx>30 + story.ll_count_60>=3 → TREND_DOWN_CONTINUATION
    if (state == NarrativeState.OPEN_DRIVE_DOWN
            and bar_idx > BAR_IDX_OD_CONTINUATION_MIN and ll_60 >= 3):
        return (
            NarrativeState.TREND_DOWN_CONTINUATION, -1, CONF_TREND_CONTINUATION,
            {"trigger": "T11_open_drive_down_continuation", "ll_60": ll_60},
        )

    # T12: OPEN_DRIVE_UP + close<open_cash + vol_zscore_20<-0.5 → OPEN_ROTATION
    if state == NarrativeState.OPEN_DRIVE_UP:
        if (close is not None and open_cash is not None and vol_z is not None
                and close < open_cash and vol_z < VOL_Z_REVERT_MAX):
            return (
                NarrativeState.OPEN_ROTATION, 0, CONF_OTD_NEUTRAL,
                {"trigger": "T12_open_drive_up_reverted"},
            )

    # T13: OPEN_DRIVE_DOWN + close>open_cash + vol_zscore_20<-0.5 → OPEN_ROTATION
    if state == NarrativeState.OPEN_DRIVE_DOWN:
        if (close is not None and open_cash is not None and vol_z is not None
                and close > open_cash and vol_z < VOL_Z_REVERT_MAX):
            return (
                NarrativeState.OPEN_ROTATION, 0, CONF_OTD_NEUTRAL,
                {"trigger": "T13_open_drive_down_reverted"},
            )

    # T14: OPEN_TEST_DRIVE + bar_idx∈[5,15] + close>open_cash+0.5*atr + vol_zscore>+0.5 → OPEN_DRIVE_UP
    if (state == NarrativeState.OPEN_TEST_DRIVE
            and BAR_IDX_OTD_WINDOW_MIN <= bar_idx <= BAR_IDX_OTD_WINDOW_MAX):
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close > open_cash + ATR_MULT_OTD_DIRECTION * atr
                and vol_z > VOL_Z_OTD_CONFIRM_MIN):
            return (
                NarrativeState.OPEN_DRIVE_UP, +1, CONF_OTD_CONFIRM,
                {"trigger": "T14_OTD_confirmed_up"},
            )

    # T15: OPEN_TEST_DRIVE + bar_idx∈[5,15] + close<open_cash-0.5*atr + vol_zscore>+0.5 → OPEN_DRIVE_DOWN
    if (state == NarrativeState.OPEN_TEST_DRIVE
            and BAR_IDX_OTD_WINDOW_MIN <= bar_idx <= BAR_IDX_OTD_WINDOW_MAX):
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close < open_cash - ATR_MULT_OTD_DIRECTION * atr
                and vol_z > VOL_Z_OTD_CONFIRM_MIN):
            return (
                NarrativeState.OPEN_DRIVE_DOWN, -1, CONF_OTD_CONFIRM,
                {"trigger": "T15_OTD_confirmed_down"},
            )

    # T16: OPEN_TEST_DRIVE + bar_idx_session>15 → OPEN_ROTATION
    if (state == NarrativeState.OPEN_TEST_DRIVE
            and bar_idx > BAR_IDX_OTD_TIMEOUT):
        return (
            NarrativeState.OPEN_ROTATION, 0, CONF_ROTATION_TIMEOUT,
            {"trigger": "T16_OTD_timeout_rotation"},
        )

    # T17 (refacto 2026-05-18 P0/P1 review market-analyst) :
    # Canon Dalton MOM Ch.9 "Day Type Recognition" : Range Day = prix oscille
    # DANS l'IB toute la session.
    # State guard elargi : {OPEN_ROTATION, TREND_UP, TREND_DOWN} car OPEN_ROTATION
    # arrive souvent AVANT IB complete (bar 16-30 via T16), et le state peut
    # avoir transite vers TREND avant IB complete (bar 60+). Le canon dit "range
    # confirme apres IB+1h", donc on accepte TREND→RANGE_RESPECTED quand l'IB
    # complete sans breakout et price reste in VA.
    # Anti-cycle TREND<->RANGE : guard bars_since_BOS > 30 (= ~30 min depuis
    # dernier swing break, proxy "consolidation prolongee").
    # Conditions :
    #   - state in {OPEN_ROTATION, TREND_UP_CONTINUATION, TREND_DOWN_CONTINUATION}
    #   - ib_complete (IB formed = post-bar 60)
    #   - inside_value_area (prix dans VA = consolidation)
    #   - not ib_broken_up AND not ib_broken_dn (pas de breakout IB)
    #   - bars_since_BOS > 30 (anti-flip immediat depuis trend actif)
    if state in {NarrativeState.OPEN_ROTATION,
                 NarrativeState.TREND_UP_CONTINUATION,
                 NarrativeState.TREND_DOWN_CONTINUATION}:
        if ib_complete and inside_va:
            ib_broken_up = bool(bar.get("ib_broken_up") or ctx.get("ib_broken_up"))
            ib_broken_dn = bool(bar.get("ib_broken_dn") or ctx.get("ib_broken_dn"))
            if (not ib_broken_up and not ib_broken_dn
                    and bars_since_BOS > BARS_SINCE_BOS_MIN_RANGE):
                return (
                    NarrativeState.RANGE_RESPECTED, 0, CONF_RANGE_RESPECTED,
                    {"trigger": "T17_range_respected_canon_dalton",
                     "bars_since_BOS": bars_since_BOS},
                )

    # T18 (fusion B2) : RANGE_RESPECTED + close>prev_vah + close[-1]>prev_vah
    # → TREND_UP_CONTINUATION (range breakout VAH = trend up structurel)
    if state == NarrativeState.RANGE_RESPECTED:
        if (close is not None and prev_vah is not None and prev_close is not None
                and close > prev_vah and prev_close > prev_vah):
            return (
                NarrativeState.TREND_UP_CONTINUATION, +1, CONF_RANGE_BREAKOUT,
                {"trigger": "T18_range_breakout_VAH"},
            )

    # T19 (fusion B2) : RANGE_RESPECTED + close<prev_val + close[-1]<prev_val
    # → TREND_DOWN_CONTINUATION (range breakdown VAL = trend down structurel)
    if state == NarrativeState.RANGE_RESPECTED:
        if (close is not None and prev_val is not None and prev_close is not None
                and close < prev_val and prev_close < prev_val):
            return (
                NarrativeState.TREND_DOWN_CONTINUATION, -1, CONF_RANGE_BREAKOUT,
                {"trigger": "T19_range_breakdown_VAL"},
            )

    # T6 (fix B1) : PRE_OPEN_* + session=NY + open_type=OpenType.OD_UP
    # + close>open_cash+atr + vol_zscore>+1.0 → OPEN_DRIVE_UP
    if (state in _PRE_OPEN_STATES and session == "NY"
            and open_type == OpenType.OD_UP):
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close > open_cash + ATR_MULT_OD * atr
                and vol_z > VOL_Z_OPEN_DRIVE_MIN):
            return (
                NarrativeState.OPEN_DRIVE_UP, +1, CONF_OPEN_DRIVE,
                {"trigger": "T6_open_drive_up", "vol_z": vol_z,
                 "atr_mult": close - open_cash},
            )

    # T7 (fix B1) : PRE_OPEN_* + session=NY + open_type=OpenType.OD_DOWN
    # + close<open_cash-atr + vol_zscore>+1.0 → OPEN_DRIVE_DOWN
    if (state in _PRE_OPEN_STATES and session == "NY"
            and open_type == OpenType.OD_DOWN):
        if (close is not None and open_cash is not None and atr is not None
                and vol_z is not None
                and close < open_cash - ATR_MULT_OD * atr
                and vol_z > VOL_Z_OPEN_DRIVE_MIN):
            return (
                NarrativeState.OPEN_DRIVE_DOWN, -1, CONF_OPEN_DRIVE,
                {"trigger": "T7_open_drive_down", "vol_z": vol_z,
                 "atr_mult": open_cash - close},
            )

    # T8 (fix B1) : PRE_OPEN_* + session=NY + open_type ∈ {OTD_UP, OTD_DOWN}
    # → OPEN_TEST_DRIVE (les deux directions OTD couvertes ici, direction
    # affinee par T14/T15 dans la fenetre [5,15] bars)
    if (state in _PRE_OPEN_STATES and session == "NY"
            and open_type in (OpenType.OTD_UP, OpenType.OTD_DOWN)):
        return (
            NarrativeState.OPEN_TEST_DRIVE, 0, CONF_OTD_NEUTRAL,
            {"trigger": "T8_open_test_drive", "open_type": int(open_type)},
        )

    # T9 (fix B1) : PRE_OPEN_* + session=NY + open_type=OpenType.OAIR
    # → OPEN_ROTATION (Open Auction In Range = D4 Dalton)
    if (state in _PRE_OPEN_STATES and session == "NY"
            and open_type == OpenType.OAIR):
        return (
            NarrativeState.OPEN_ROTATION, 0, CONF_OPEN_ROTATION,
            {"trigger": "T9_open_auction_rotation"},
        )

    # T6bis (audit replay 18/05) : PRE_OPEN_* + session=NY + open_type=OAOR_UP
    # + close>open_cash (prix tient au-dessus VA) → OPEN_DRIVE_UP
    # Dalton MOM Ch.8 : "Open Auction Out of Range = strong directional move
    # below/above prior day's value area, highest-confidence directional setup".
    # OAOR confirme = bullish strong, equivalent conviction OD.
    if (state in _PRE_OPEN_STATES and session == "NY"
            and open_type == OpenType.OAOR_UP):
        if (close is not None and open_cash is not None
                and vol_z is not None
                and close > open_cash
                and vol_z > VOL_Z_OTD_CONFIRM_MIN):  # 0.5 = exigence faible
            return (
                NarrativeState.OPEN_DRIVE_UP, +1, CONF_OPEN_DRIVE,
                {"trigger": "T6bis_open_auction_out_of_range_up",
                 "vol_z": vol_z, "open_type": int(open_type)},
            )

    # T7bis (audit replay 18/05) : PRE_OPEN_* + session=NY + open_type=OAOR_DOWN
    # + close<open_cash (prix tient en-dessous VA) → OPEN_DRIVE_DOWN
    if (state in _PRE_OPEN_STATES and session == "NY"
            and open_type == OpenType.OAOR_DOWN):
        if (close is not None and open_cash is not None
                and vol_z is not None
                and close < open_cash
                and vol_z > VOL_Z_OTD_CONFIRM_MIN):
            return (
                NarrativeState.OPEN_DRIVE_DOWN, -1, CONF_OPEN_DRIVE,
                {"trigger": "T7bis_open_auction_out_of_range_down",
                 "vol_z": vol_z, "open_type": int(open_type)},
            )

    # T9bis (audit replay 18/05) : PRE_OPEN_* + session=NY + open_type ∈ {ORR_UP, ORR_DOWN}
    # → OPEN_ROTATION (Open Range Rotation = open hors VA reverse vers VA = signal
    # directionnel faible/contradictoire, comportement rotation safer).
    # Dalton MOM Ch.8 : ORR = "auction tried to extend out of range, rejected by
    # acceptance back into prior day's value" = reversal = pas de bias directionnel.
    if (state in _PRE_OPEN_STATES and session == "NY"
            and open_type in (OpenType.ORR_UP, OpenType.ORR_DOWN)):
        return (
            NarrativeState.OPEN_ROTATION, 0, CONF_OPEN_ROTATION,
            {"trigger": "T9bis_open_range_rotation",
             "open_type": int(open_type)},
        )

    # T2: PRE_OPEN_NEUTRAL + slope_60<-0.2 + asia_close<asia_open → PRE_OPEN_BEARISH
    if state == NarrativeState.PRE_OPEN_NEUTRAL and session in ("ASIA", "LONDON"):
        if slope_60 < -SLOPE_PREOPEN_THRESHOLD and asia_close is not None and asia_open is not None:
            if asia_close < asia_open:
                return (
                    NarrativeState.PRE_OPEN_BEARISH, -1, CONF_PRE_OPEN_DIRECTIONAL,
                    {"trigger": "T2_preopen_bearish", "slope_60": slope_60},
                )

    # T3: PRE_OPEN_NEUTRAL + slope_60>+0.2 + asia_close>asia_open → PRE_OPEN_BULLISH
    if state == NarrativeState.PRE_OPEN_NEUTRAL and session in ("ASIA", "LONDON"):
        if slope_60 > SLOPE_PREOPEN_THRESHOLD and asia_close is not None and asia_open is not None:
            if asia_close > asia_open:
                return (
                    NarrativeState.PRE_OPEN_BULLISH, +1, CONF_PRE_OPEN_DIRECTIONAL,
                    {"trigger": "T3_preopen_bullish", "slope_60": slope_60},
                )

    # T4: PRE_OPEN_BEARISH + slope_60 ∈ [-0.1, +0.1] → PRE_OPEN_NEUTRAL
    if (state == NarrativeState.PRE_OPEN_BEARISH
            and -SLOPE_NEUTRAL_BAND <= slope_60 <= SLOPE_NEUTRAL_BAND):
        return (
            NarrativeState.PRE_OPEN_NEUTRAL, 0, CONF_NEUTRAL,
            {"trigger": "T4_rebalance_neutral", "slope_60": slope_60},
        )

    # T5: PRE_OPEN_BULLISH + slope_60 ∈ [-0.1, +0.1] → PRE_OPEN_NEUTRAL
    if (state == NarrativeState.PRE_OPEN_BULLISH
            and -SLOPE_NEUTRAL_BAND <= slope_60 <= SLOPE_NEUTRAL_BAND):
        return (
            NarrativeState.PRE_OPEN_NEUTRAL, 0, CONF_NEUTRAL,
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
        # F1 fix: lock separe pour _pending_events buffer.
        # transition() peut etre appele concurremment par 2 symboles (ES/NQ) sous
        # locks per-symbol differents, mais ils partagent _pending_events. Sans ce
        # lock dedie, consume_events() peut swap pendant que transition() append
        # = events perdus silencieusement. Race detectee par review code-reviewer
        # ULTRATHINK 18/05.
        self._events_lock: threading.Lock = threading.Lock()

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
            bar: payload V4 enriched canonical (dict ~467 cols). Doit contenir :
                - "atr" (ATR daily Wilder, echelle session : T6/T7/T14/T15/T17)
                - "atr_intraday" ou "atr_14m" (ATR Wilder 14-bars 1-min, echelle
                  par-bar : T22-T27 Wyckoff recovery, T28/T29 EXHAUSTION climax,
                  T30/T31 follow-through). Fix 2026-05-18 : sans cette
                  distinction, le seuil bar_range>2*atr_daily = 35 pts ES etait
                  inatteignable sur barre 1-min (p99 bar_range = 7 pts).
                  Fallback : si atr_intraday absent, utilise atr (incoherent
                  d'echelle mais evite crash).
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
                    confidence=CONF_NEUTRAL,
                    triggering_features={"trigger": "cold_start"},
                    current_session_date_trading=bar.get("session_date_trading"),
                )
                self._states[symbol] = current

            # P0-1 garde-fou : detecter regression silencieuse atr_intraday absent.
            # Si pipeline ne fournit ni atr_intraday ni atr_14m, le code _evaluate_transitions
            # tombe sur fallback atr daily -> seuils T28/T29/T30/T31 inatteignables a nouveau
            # = retour au bug pre-fix 2026-05-18. Emit MAJEUR pour detection J+1 grep logs.
            # Idempotence : emit 1x par symbol par session (eviter spam si fallback chronique).
            if not current.engine_states.get("_atr_fallback_warned"):
                has_atr_intraday = (
                    bar.get("atr_intraday") is not None
                    or bar.get("atr_14m") is not None
                )
                atr_daily_val = _safe_float(bar.get("atr"))
                if not has_atr_intraday and atr_daily_val is not None:
                    emit(
                        "BOT3_NSM_ATR_FALLBACK_DAILY",
                        log_fn=log_fn,
                        sym=symbol,
                        atr_daily=atr_daily_val,
                    )
                    current.engine_states["_atr_fallback_warned"] = True

            # Reset n_transitions_today si SDT change
            # NB: ne PAS mettre a jour current.current_session_date_trading ici —
            # _evaluate_transitions (T1/T32) en a besoin pour detecter le change.
            # L'update est faite apres evaluate (cf. fin de methode).
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
                # Still update prev_close + bar_idx + return current (no transition)
                close = _safe_float(bar.get("close"))
                if close is not None:
                    current.engine_states["prev_close"] = close
                current.bar_idx_current += 1
                if sdt_changed:
                    current.current_session_date_trading = sdt
                return current

            # Evaluate transitions FIRST (F6 fix : avant increment bar_idx_current)
            # _evaluate_transitions utilise current.bar_idx_current comme fallback si
            # bar.bar_idx_session absent. Garder l'ancienne valeur ici donne la
            # semantique correcte "bar courant = N, on l'evalue".
            result = _evaluate_transitions(
                current, bar, ctx, story_trackers, swing_state
            )

            # Increment bar counter APRES evaluate (F6 fix)
            current.bar_idx_current += 1

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
                    # F1 fix : append _pending_events sous _events_lock (race vs consume_events)
                    with self._events_lock:
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
            # (T1/T32 a deja consomme la valeur prev pour detecter le change).
            if sdt_changed:
                current.current_session_date_trading = sdt

            return current

    def current(self, symbol: str) -> NarrativeStateSnapshot | None:
        """Returns current snapshot or None si symbol jamais vu."""
        with self._get_lock(symbol):
            return self._states.get(symbol)

    def consume_events(self) -> list[NarrativeEvent]:
        """Pop all pending events buffer. Caller emit logs externe si necessaire.

        F1 fix : swap sous _events_lock pour empecher race vs transition() qui
        peut etre appele concurremment depuis 2 symboles ES/NQ (locks per-symbol
        differents mais _pending_events partage).

        Note pickle (contract documente) :
        - `pickle.dumps(nsm)` direct : _pending_events PRESERVE
        - via NarrativePersistedState wrapper (bot3_narrative_persistence.py:73) :
          _pending_events NON serialise (intentionnel, anti double-emit au restore)
        """
        with self._events_lock:
            evts, self._pending_events = self._pending_events, []
        return evts

    def __getstate__(self) -> dict:
        """Exclude _locks + _lock_creation_lock + _events_lock du pickle.

        _pending_events EST preserve si pickle direct mais le wrapper
        NarrativePersistedState ne l'extrait pas (cf consume_events docstring).
        """
        state = self.__dict__.copy()
        state.pop("_locks", None)
        state.pop("_lock_creation_lock", None)
        state.pop("_events_lock", None)
        return state

    def __setstate__(self, state: dict) -> None:
        """Restore + recreate locks au load."""
        self.__dict__.update(state)
        self._locks = {}
        self._lock_creation_lock = threading.Lock()
        self._events_lock = threading.Lock()
