"""CORE/bot3_plot_twist_detectors.py - Plot Twist Detectors Bot 3 v2 (Phase 2).

Module : 4 detectors narratifs scannes a chaque bar pour identifier
"plot twists" du marche (evenements significatifs qui peuvent INVALIDER
ou CONFIRMER la narrative courante) :

  1. STRUCTURE_BREAK (BOS/CHoCH ICT) : close casse swing high/low + vol_z>0
  2. VOLUME_ANOMALY               : vol_z > 2.0 vs prev 5 bars (climax detection)
  3. DIVERGENCE (price vs CVD)    : price new HH/LL + CVD diverge (Wyckoff effort/result)
  4. CAPITULATION                 : 3+ bars consecutifs climax + range>1.5*ATR (Pruden)

Architecture : Bot 3 v2 Narrative Layer (Phase 2 TRACKING ONLY).
Pattern reference : `CORE/bot3_story_trackers.py` (1 instance per symbol +
  ring buffer history + threading.RLock + schema_version'ed).

Data source : Databento payload V4 enriched canonical (~467 cols/bar).
  Inputs principaux : high, low, close, open, vol_zscore_20, atr,
                      cvd_5d_rolling_ffd (ou similaire), bar_idx_session.
  Input critique : swing_state (last_swing_high/low) depuis sessions_swings_lag.

Created : 2026-05-18 by Jackson + Claude (Phase 2 J+1 anti-Pattern 11 V1)
Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md (sect 247-258)
Review trace : LOGS/reviews/REVIEW_BOT3V2_plot_twist_*.json (a creer)
Memory feedback : .claude/memory/feedback_bot3v2_phase2_*.md (post-review)

Auteur : Bot 3 v2 Narrative Layer Phase 2
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 PM : creation Phase 2 J+1 - 4 detectors + state ring buffer
#                 Pattern reference : bot3_story_trackers (LiveEnricherState).
#                 Anti-pattern 11 V1 : detection narrative, pas hardcoded gate.
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from CORE.bot3_narrative_logging import emit
    from CORE.constants import get_tick_size as _get_tick_size
except ModuleNotFoundError:
    from bot3_narrative_logging import emit  # type: ignore[no-redef]
    try:
        from constants import get_tick_size as _get_tick_size  # type: ignore[no-redef]
    except ModuleNotFoundError:
        _get_tick_size = None  # type: ignore[assignment]

PLOT_TWIST_SCHEMA_VERSION: str = "2.1.0"  # bump R1-R3 fixes 18/05 PM

# ─── Thresholds calibres canon Wyckoff/Pruden/Steidlmayer ─────────────────
# Calibrage 18/05 post-replay : 2.0 trop sensible sur 1m bars (326 fires/5j ES).
# Pruden Ch.5 "buying/selling climax" canon = z-score >= 2.5 (event marque).
# Capitulation = climax extreme = 3.0 (Pruden "three pushes pattern").
VOL_Z_ANOMALY_MIN: float = 2.5
VOL_Z_CAPITULATION_MIN: float = 3.0
CAPITULATION_BARS_REQUIRED: int = 3     # 3+ bars climax consecutifs
CAPITULATION_RANGE_ATR_MULT: float = 1.5  # bar_range > 1.5*atr
BARS_HISTORY_MAXLEN: int = 10           # Buffer pour DIVERGENCE + ANOMALY
DIVERGENCE_PRICE_LOOKBACK: int = 5      # Compare price actuelle vs N bars avant
THROTTLE_TWIST_BARS: int = 3            # Min bars entre 2 fires (volume/divergence/capit)
THROTTLE_BOS_BARS: int = 30             # BOS meme direction (Pruden 1-3 BOS reels/jour)
THROTTLE_BOS_GLOBAL: int = 10           # BOS ANY direction (anti chop ping-pong, R8 fix)
TICK_THRESHOLD_BOS: float = 2.0         # close>swing+2*tick = acceptance Dalton
# R1 fix : acceptance multi-bar (Dalton MOM Ch.7 + ICT displacement+follow-through).
# BOS confirme apres N bars maintenu au-dessus/dessous swing. Pas fire instant.
BOS_ACCEPTANCE_BARS_REQUIRED: int = 2   # 2 bars consecutifs maintien acceptance
# R6 fix : throttle CHoCH (Change of Character) plus court que BOS continuation.
# Pattern ICT : BOS dans trend + bullish HH count fort = continuation legitimate.
# CHoCH dans trend oppose = signal critique, throttle 5 bars uniquement.
THROTTLE_CHOCH_BARS: int = 5
CHOCH_TREND_THRESHOLD: int = 5          # hh_count_60 ou ll_count_60 >= 5 = trend etabli
# R7 fix : CAPITULATION Pruden "Three Pushes" canon - peut avoir retracements.
# Window de 5 bars contenant >= 3 climax bars (pas strictement consecutifs).
CAPITULATION_WINDOW_BARS: int = 5
# R3 fix : severity STRUCTURE_BREAK normalisee en ticks (cross-symbol invariant)
# 10 ticks = severity 1.0, 3 ticks = severity 0.3 (~ seuil invalidation)
SEVERITY_BOS_TICKS_DIVISOR: float = 10.0
# DIVERGENCE severity : ratio vs CVD ref absolu (au lieu de /10000 arbitraire).
# Ratio 0.5 (= 50% du CVD ref) = severity 1.0. Cross-symbol invariant.
SEVERITY_DIVERGENCE_RATIO_DIVISOR: float = 0.5


@dataclass
class PlotTwist:
    """Event detecte par un des 4 detectors. Consume par ScenarioValidator
    + log emit + replay analysis."""
    twist_type: str       # STRUCTURE_BREAK / VOLUME_ANOMALY / DIVERGENCE / CAPITULATION
    direction: int        # -1 / 0 / +1 (bias narrative)
    severity: float       # [0.0, 1.0] - confidence du signal
    bar_ts: str           # timestamp bar declencheur
    bar_idx: int          # bar_idx_current du detector state
    symbol: str           # ES.c.0 / NQ.c.0 / MGC.v.0
    triggering_features: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlotTwistDetectorsState:
    """State per symbol (mirror StoryTrackersState pattern ADR 0002).

    Attributes:
        symbol : ES.c.0 / NQ.c.0 / MGC.v.0
        schema_version : bump si breaking change
        bars_history : ring buffer deque(maxlen=10) avec (high, low, close, vol_z, atr, cvd)
        climax_buffer : deque(maxlen=CAPITULATION_BARS_REQUIRED) pour capitulation tracking
        last_twist_bar_idx : dict[twist_type, bar_idx] pour throttle anti-spam
        bar_idx_current : counter monotone
        last_BOS_dir : -1 / 0 / +1 (anti double-fire BOS meme direction)
        last_BOS_bar_idx : bar_idx du dernier BOS detecte
        engine_states : extensible dict pour futurs detectors Phase 3+
        _lock : threading.RLock (exclu du pickle)
    """
    symbol: str = ""
    schema_version: str = PLOT_TWIST_SCHEMA_VERSION
    bars_history: deque = field(default_factory=lambda: deque(maxlen=BARS_HISTORY_MAXLEN))
    # R7 fix : maxlen aligne sur WINDOW (5) au lieu de REQUIRED (3) pour permettre
    # tracking climax bars dans une fenetre Pruden "Three Pushes" avec retracements.
    climax_buffer: deque = field(
        default_factory=lambda: deque(maxlen=CAPITULATION_WINDOW_BARS)
    )
    last_twist_bar_idx: dict[str, int] = field(default_factory=dict)
    bar_idx_current: int = 0
    # Legacy fields (compat pickle pre-R8 18/05) — toujours present mais deprecated.
    # Nouveaux trackers separes per-direction (fix R8) :
    last_BOS_dir: int = 0
    last_BOS_bar_idx: int = -1
    last_BOS_bullish_bar_idx: int = -1
    last_BOS_bearish_bar_idx: int = -1
    # R1 fix : pending BOS state machine (acceptance multi-bar Dalton/ICT)
    # When close casse swing : on enregistre pending. Si bar suivante CONFIRME
    # (close still beyond swing + N bars), fire. Sinon abort.
    bos_pending_dir: int = 0                 # 0 si pas pending, +1 / -1 sinon
    bos_pending_swing_ref: float = 0.0       # swing au moment du pending
    bos_pending_start_bar_idx: int = -1      # bar_idx initial du pending
    bos_pending_bars_confirmed: int = 0      # nb bars consecutives validees
    engine_states: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def __getstate__(self) -> dict:
        """Exclude _lock du pickle (mirror bot3_story_trackers pattern)."""
        state = self.__dict__.copy()
        state.pop("_lock", None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._lock = threading.RLock()


# ─── Helpers ──────────────────────────────────────────────────────────────


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _swing_high_price(swing_state: Any) -> float | None:
    if swing_state is None:
        return None
    sh = getattr(swing_state, "last_swing_high", None)
    if sh is None:
        return None
    return _safe_float(getattr(sh, "price", None))


def _swing_low_price(swing_state: Any) -> float | None:
    if swing_state is None:
        return None
    sl = getattr(swing_state, "last_swing_low", None)
    if sl is None:
        return None
    return _safe_float(getattr(sl, "price", None))


def _throttled(state: PlotTwistDetectorsState, twist_type: str) -> bool:
    """Return True si twist_type emit < THROTTLE_TWIST_BARS bars ago.
    Anti-spam : evite same twist fire chaque bar pendant volume anomaly soutenue."""
    last_idx = state.last_twist_bar_idx.get(twist_type, -999)
    return (state.bar_idx_current - last_idx) < THROTTLE_TWIST_BARS


# ─── Detectors ────────────────────────────────────────────────────────────


def detect_structure_break(
    state: PlotTwistDetectorsState,
    bar: dict,
    swing_state: Any,
    tick_size: float | None = None,
    story_trackers: dict[str, Any] | None = None,
    log_fn: Callable[..., None] | None = None,
) -> PlotTwist | None:
    """ICT BOS/CHoCH : close casse swing avec acceptance multi-bar.

    FIX R1 (Dalton MOM Ch.7 + ICT canonical) : acceptance multi-bar OBLIGATOIRE.
    Etape 1 : close > swing + 2*tick → enregistre `bos_pending_*`.
    Etape 2 : N bars consecutives close > swing (=BOS_ACCEPTANCE_BARS_REQUIRED)
              → fire PlotTwist. Sinon abort pending si close revient.
    Anti ICT liquidity sweep trap (algo run stops + wick reverse instant).

    FIX R6 (ICT CHoCH discrimination) : CHoCH = cassure dir CONTRAIRE au trend
    etabli (hh_count_60 / ll_count_60 fort). Throttle court 5 bars sur CHoCH
    (signal critique reversal). BOS continuation = throttle long 30 bars.

    FIX R3 (cross-symbol invariant) : severity en ticks normalisee.
    FIX R3bis (.claude/rules/tick-size-policy.md) : tick_size MANDATORY.
    FIX R8 : trackers BOS bullish/bearish separes + throttle GLOBAL 10 bars.
    """
    # Fix R3bis : resolve tick_size si None
    if tick_size is None:
        if _get_tick_size is not None and state.symbol:
            tick_size = _get_tick_size(state.symbol)
        else:
            tick_size = 0.25  # fallback ultime ES/NQ + warning silencieux

    close = _safe_float(bar.get("close"))
    vol_z = _safe_float(bar.get("vol_zscore_20"))
    swing_high = _swing_high_price(swing_state)
    swing_low = _swing_low_price(swing_state)

    if close is None or vol_z is None or vol_z <= 0:
        return None

    # Guard : swing price doit etre > 0 (sinon placeholder default = pas de swing reel)
    swing_high_valid = swing_high is not None and swing_high > 0.0
    swing_low_valid = swing_low is not None and swing_low > 0.0

    # R1 fix : si pending BOS deja enregistre, check si on confirme/abort
    if state.bos_pending_dir != 0:
        pending_swing = state.bos_pending_swing_ref
        pending_dir = state.bos_pending_dir
        # Maintien acceptance ?
        if pending_dir == +1 and close > pending_swing + TICK_THRESHOLD_BOS * tick_size:
            state.bos_pending_bars_confirmed += 1
        elif pending_dir == -1 and close < pending_swing - TICK_THRESHOLD_BOS * tick_size:
            state.bos_pending_bars_confirmed += 1
        else:
            # Retracement intra-pending = abort (faux BOS / sweep trap ICT)
            state.bos_pending_dir = 0
            state.bos_pending_bars_confirmed = 0
            state.bos_pending_swing_ref = 0.0
            state.bos_pending_start_bar_idx = -1
            # Tomber sur detection nouvelle ci-dessous

        # Acceptance confirmee ? Fire.
        if state.bos_pending_dir != 0 \
                and state.bos_pending_bars_confirmed >= BOS_ACCEPTANCE_BARS_REQUIRED:
            confirmed_dir = state.bos_pending_dir
            confirmed_swing = state.bos_pending_swing_ref
            # Reset pending state
            state.bos_pending_dir = 0
            state.bos_pending_bars_confirmed = 0
            state.bos_pending_swing_ref = 0.0
            state.bos_pending_start_bar_idx = -1
            # Update trackers + emit
            if confirmed_dir == +1:
                state.last_BOS_bullish_bar_idx = state.bar_idx_current
            else:
                state.last_BOS_bearish_bar_idx = state.bar_idx_current
            state.last_BOS_dir = confirmed_dir
            state.last_BOS_bar_idx = state.bar_idx_current
            state.last_twist_bar_idx["STRUCTURE_BREAK"] = state.bar_idx_current

            ticks_break = abs(close - confirmed_swing) / tick_size
            severity = min(1.0, ticks_break / SEVERITY_BOS_TICKS_DIVISOR)
            emit(
                "BOT3_PLOT_TWIST_STRUCTURE_BREAK",
                log_fn=log_fn, sym=state.symbol, direction=confirmed_dir,
                close=close, swing_ref=confirmed_swing,
                bar_ts=str(bar.get("ts_event_iso", "")),
            )
            return PlotTwist(
                twist_type="STRUCTURE_BREAK",
                direction=confirmed_dir,
                severity=severity,
                bar_ts=str(bar.get("ts_event_iso", "")),
                bar_idx=state.bar_idx_current,
                symbol=state.symbol,
                triggering_features={
                    "close": close, "swing": confirmed_swing, "vol_z": vol_z,
                    "ticks_break": ticks_break,
                    "bars_acceptance": state.bos_pending_bars_confirmed,
                },
            )
        elif state.bos_pending_dir != 0:
            # Pending toujours actif, attente confirmation. Pas de fire.
            return None

    # R8 fix : throttle global ALL_BOS (anti chop). Si N'IMPORTE QUEL BOS fire
    # < THROTTLE_BOS_GLOBAL bars ago, on bloque tout (meme direction inverse).
    last_any_bos_idx = max(state.last_BOS_bullish_bar_idx,
                           state.last_BOS_bearish_bar_idx)
    if last_any_bos_idx >= 0 and (
        state.bar_idx_current - last_any_bos_idx
    ) < THROTTLE_BOS_GLOBAL:
        return None

    # R6 fix : CHoCH discrimination via story_trackers.
    # Trend up etabli (hh_count_60 >= 5) + BOS bearish = CHoCH = throttle court.
    hh_60 = int(story_trackers.get("hh_count_60", 0)) if story_trackers else 0
    ll_60 = int(story_trackers.get("ll_count_60", 0)) if story_trackers else 0

    # BOS bullish - detection initiale (enregistrement pending)
    if (swing_high_valid
            and close > swing_high + TICK_THRESHOLD_BOS * tick_size):
        # R6 : CHoCH = BOS bullish dans trend DOWN etabli
        is_choch = ll_60 >= CHOCH_TREND_THRESHOLD
        throttle = THROTTLE_CHOCH_BARS if is_choch else THROTTLE_BOS_BARS
        if state.last_BOS_bullish_bar_idx >= 0 and (
            state.bar_idx_current - state.last_BOS_bullish_bar_idx
        ) < throttle:
            return None
        # R1 : enregistre pending, attendre acceptance
        state.bos_pending_dir = +1
        state.bos_pending_swing_ref = swing_high
        state.bos_pending_start_bar_idx = state.bar_idx_current
        state.bos_pending_bars_confirmed = 1
        return None

    # BOS bearish - detection initiale
    if (swing_low_valid
            and close < swing_low - TICK_THRESHOLD_BOS * tick_size):
        # R6 : CHoCH = BOS bearish dans trend UP etabli
        is_choch = hh_60 >= CHOCH_TREND_THRESHOLD
        throttle = THROTTLE_CHOCH_BARS if is_choch else THROTTLE_BOS_BARS
        if state.last_BOS_bearish_bar_idx >= 0 and (
            state.bar_idx_current - state.last_BOS_bearish_bar_idx
        ) < throttle:
            return None
        state.bos_pending_dir = -1
        state.bos_pending_swing_ref = swing_low
        state.bos_pending_start_bar_idx = state.bar_idx_current
        state.bos_pending_bars_confirmed = 1
        return None

    return None


def detect_volume_anomaly(
    state: PlotTwistDetectorsState,
    bar: dict,
    log_fn: Callable[..., None] | None = None,
) -> PlotTwist | None:
    """Climax volume Wyckoff/Pruden Ch.5 : vol_z > 2.5 = event significatif.

    Direction semantique (FIX R2 review market-analyst 18/05) :
    Pruden Three Skills Ch.5 definit explicitement :
    - Buying climax : prix monte + close > open MAIS volume enorme = vendeurs
      absorbants livrent → reversal **BEARISH** imminent. Direction = -1.
    - Selling climax : prix descend + close < open MAIS volume enorme =
      acheteurs absorbants entrent → reversal **BULLISH** imminent. Direction = +1.

    Donc direction climax = INVERSE de la close direction (contra aggressor).
    Pour preciser : si payload V4 contient `delta_pct` (aggressor side -1 to +1),
    utiliser comme proxy plus precis. Sinon fallback close vs open inverse.

    Throttle 3 bars : evite spam pendant grosse fenetre volume.
    """
    if _throttled(state, "VOLUME_ANOMALY"):
        return None

    vol_z = _safe_float(bar.get("vol_zscore_20"))
    if vol_z is None or vol_z < VOL_Z_ANOMALY_MIN:
        return None

    close = _safe_float(bar.get("close"))
    open_ = _safe_float(bar.get("open"))
    delta_pct = _safe_float(bar.get("delta_pct"))

    # Direction Wyckoff canon : INVERSE de l'aggressor side (absorption thesis).
    # Priorite 1 : delta_pct (aggressor signed, +1 = buyers aggress, -1 = sellers)
    # → direction climax = inverse aggressor (les absorbants prennent l'autre cote)
    direction = 0
    if delta_pct is not None and abs(delta_pct) > 0.1:
        direction = -1 if delta_pct > 0 else +1
    elif close is not None and open_ is not None and close != open_:
        # Fallback : direction climax = inverse close-open sign
        direction = -1 if close > open_ else +1

    state.last_twist_bar_idx["VOLUME_ANOMALY"] = state.bar_idx_current
    emit(
        "BOT3_PLOT_TWIST_VOLUME_ANOMALY",
        log_fn=log_fn,
        sym=state.symbol,
        vol_z=vol_z,
        bar_ts=str(bar.get("ts_event_iso", "")),
    )
    severity = min(1.0, (vol_z - VOL_Z_ANOMALY_MIN) / 3.0)
    return PlotTwist(
        twist_type="VOLUME_ANOMALY",
        direction=direction,
        severity=severity,
        bar_ts=str(bar.get("ts_event_iso", "")),
        bar_idx=state.bar_idx_current,
        symbol=state.symbol,
        triggering_features={
            "vol_z": vol_z, "close": close, "open": open_,
            "delta_pct": delta_pct,
        },
    )


def detect_divergence(
    state: PlotTwistDetectorsState,
    bar: dict,
    log_fn: Callable[..., None] | None = None,
) -> PlotTwist | None:
    """Wyckoff effort vs result : price new HH/LL mais CVD diverge.

    Bearish divergence : high actuel > high(N bars avant) MAIS cvd actuel < cvd(N).
    Bullish divergence : low actuel < low(N) MAIS cvd actuel > cvd(N).

    Requires >= DIVERGENCE_PRICE_LOOKBACK bars dans bars_history.
    """
    if _throttled(state, "DIVERGENCE"):
        return None
    if len(state.bars_history) < DIVERGENCE_PRICE_LOOKBACK:
        return None

    high_now = _safe_float(bar.get("high"))
    low_now = _safe_float(bar.get("low"))
    # CVD column name : V4 enriched a "cvd_5d_rolling_ffd" (post Phase 3c) ou
    # "ctx_cvd_session" en alias. Tester les 2.
    cvd_now = _safe_float(
        bar.get("cvd_5d_rolling_ffd") or bar.get("ctx_cvd_session")
    )
    if cvd_now is None or high_now is None or low_now is None:
        return None

    # N bars avant (le N-eme depuis la fin)
    ref_bar = state.bars_history[-DIVERGENCE_PRICE_LOOKBACK]
    cvd_ref = ref_bar.get("cvd")
    if cvd_ref is None:
        return None

    # FIX 18/05 audit Wyckoff canon : exige NEW EXTREME sur le window, pas juste
    # mouvement haussier. Pruden Ch.6 "effort vs result" : divergence valable
    # uniquement si price fait NOUVEAU sommet/creux sur N bars. Sinon = bruit.
    lookback_window = list(state.bars_history)[-DIVERGENCE_PRICE_LOOKBACK:]
    highs_window = [b.get("high") for b in lookback_window if b.get("high") is not None]
    lows_window = [b.get("low") for b in lookback_window if b.get("low") is not None]
    if not highs_window or not lows_window:
        return None
    max_high_window = max(highs_window)
    min_low_window = min(lows_window)

    cvd_delta = cvd_now - cvd_ref

    # Bearish divergence : NEW HH absolu sur window + CVD DOWN
    if high_now > max_high_window and cvd_delta < 0:
        price_delta_hi = high_now - max_high_window
        state.last_twist_bar_idx["DIVERGENCE"] = state.bar_idx_current
        emit(
            "BOT3_PLOT_TWIST_DIVERGENCE",
            log_fn=log_fn,
            sym=state.symbol,
            direction=-1,
            price_delta=price_delta_hi,
            cvd_delta=cvd_delta,
            bar_ts=str(bar.get("ts_event_iso", "")),
        )
        return PlotTwist(
            twist_type="DIVERGENCE",
            direction=-1,
            # Fix R3 : severity normalisee ratio vs |CVD_ref| (cross-symbol invariant)
            severity=min(1.0, (abs(cvd_delta) / max(abs(cvd_ref), 1.0))
                         / SEVERITY_DIVERGENCE_RATIO_DIVISOR),
            bar_ts=str(bar.get("ts_event_iso", "")),
            bar_idx=state.bar_idx_current,
            symbol=state.symbol,
            triggering_features={
                "price_delta": price_delta_hi, "cvd_delta": cvd_delta,
                "high_now": high_now, "max_high_window": max_high_window,
            },
        )

    # Bullish divergence : NEW LL absolu sur window + CVD UP
    if low_now < min_low_window and cvd_delta > 0:
        price_delta_lo = low_now - min_low_window
        state.last_twist_bar_idx["DIVERGENCE"] = state.bar_idx_current
        emit(
            "BOT3_PLOT_TWIST_DIVERGENCE",
            log_fn=log_fn,
            sym=state.symbol,
            direction=+1,
            price_delta=price_delta_lo,
            cvd_delta=cvd_delta,
            bar_ts=str(bar.get("ts_event_iso", "")),
        )
        return PlotTwist(
            twist_type="DIVERGENCE",
            direction=+1,
            # Fix R3 : severity normalisee ratio vs |CVD_ref| (cross-symbol invariant)
            severity=min(1.0, (abs(cvd_delta) / max(abs(cvd_ref), 1.0))
                         / SEVERITY_DIVERGENCE_RATIO_DIVISOR),
            bar_ts=str(bar.get("ts_event_iso", "")),
            bar_idx=state.bar_idx_current,
            symbol=state.symbol,
            triggering_features={
                "price_delta": price_delta_lo, "cvd_delta": cvd_delta,
                "cvd_ratio": abs(cvd_delta) / max(abs(cvd_ref), 1.0),
                "low_now": low_now, "min_low_window": min_low_window,
            },
        )

    return None


def detect_capitulation(
    state: PlotTwistDetectorsState,
    bar: dict,
    log_fn: Callable[..., None] | None = None,
) -> PlotTwist | None:
    """Pruden Ch.7 "Three Pushes" canon : 3+ bars climax dans WINDOW 5 bars.

    FIX R7 (review market-analyst) : avant version exigeait 3 CONSECUTIFS strict.
    Pruden permet retracements 1-5 bars entre pushes (80% des three-pushes
    historiques ont retracements intermediaires). Maintenant window-based :
    si dans les 5 dernieres bars on a >= 3 climax bars, fire.

    Direction Wyckoff canon (R2 aligned) :
    - majorite close<open = selling climax bars = signal BULLISH (+1)
    - majorite close>open = buying climax bars = signal BEARISH (-1)
    """
    if _throttled(state, "CAPITULATION"):
        return None

    vol_z = _safe_float(bar.get("vol_zscore_20"))
    high = _safe_float(bar.get("high"))
    low = _safe_float(bar.get("low"))
    atr = _safe_float(bar.get("atr"))
    open_ = _safe_float(bar.get("open"))
    close = _safe_float(bar.get("close"))

    # Bar climax (vol+range) ?
    is_climax = (
        vol_z is not None and vol_z > VOL_Z_CAPITULATION_MIN
        and high is not None and low is not None and atr is not None
        and atr > 0 and (high - low) > CAPITULATION_RANGE_ATR_MULT * atr
        and close is not None and open_ is not None
    )

    # R7 fix : track climax bars dans une fenetre window (vs reset strict).
    # On utilise toujours climax_buffer pour stocker mais SANS clear sur non-climax.
    # Au lieu : on filtre par bar_idx_current - bar_idx_in_buffer <= WINDOW.
    if is_climax:
        state.climax_buffer.append({
            "close": close, "open": open_, "vol_z": vol_z,
            "bar_idx": state.bar_idx_current,
        })

    # Filter buffer : garder uniquement bars dans la window (5 dernieres)
    window_start = state.bar_idx_current - CAPITULATION_WINDOW_BARS + 1
    # rebuild deque avec items dans window
    in_window = [b for b in state.climax_buffer if b["bar_idx"] >= window_start]
    # On NE peut pas modifier deque size (maxlen=3), donc tracking via copie locale
    n_climax_in_window = len(in_window)

    if n_climax_in_window < CAPITULATION_BARS_REQUIRED:
        return None

    # Direction Wyckoff canon (R2 aligne) : INVERSE de bar majorite
    downs = sum(1 for b in in_window if b["close"] < b["open"])
    ups = sum(1 for b in in_window if b["close"] > b["open"])
    # Selling climax = bars majoritairement close<open = signal BULLISH
    # Buying climax = bars majoritairement close>open = signal BEARISH
    if downs > ups:
        direction = +1  # selling climax → absorbers entrent → bullish
    elif ups > downs:
        direction = -1  # buying climax → absorbers vendent → bearish
    else:
        direction = 0

    state.last_twist_bar_idx["CAPITULATION"] = state.bar_idx_current
    emit(
        "BOT3_PLOT_TWIST_CAPITULATION",
        log_fn=log_fn,
        sym=state.symbol,
        direction=direction,
        n_climax=n_climax_in_window,
        bar_ts=str(bar.get("ts_event_iso", "")),
    )
    return PlotTwist(
        twist_type="CAPITULATION",
        direction=direction,
        severity=min(1.0, n_climax_in_window / 5.0),  # 3 bars = 0.6, 5+ = 1.0
        bar_ts=str(bar.get("ts_event_iso", "")),
        bar_idx=state.bar_idx_current,
        symbol=state.symbol,
        triggering_features={
            "n_climax_bars": n_climax_in_window, "downs": downs, "ups": ups,
            "window_bars": CAPITULATION_WINDOW_BARS,
        },
    )


def scan_all(
    state: PlotTwistDetectorsState,
    bar: dict,
    swing_state: Any,
    tick_size: float | None = None,
    story_trackers: dict[str, Any] | None = None,
    log_fn: Callable[..., None] | None = None,
) -> list[PlotTwist]:
    """Scan tous les 4 detectors sur la bar courante.

    FIX R3bis (.claude/rules/tick-size-policy.md) : tick_size MANDATORY.
    Si None : resolve via get_tick_size(state.symbol). Fallback 0.25 + warning.

    FIX R6 (ICT CHoCH discrimination) : story_trackers facultatif. Si fourni,
    passe a detect_structure_break pour discriminer BOS continuation vs CHoCH.

    Append bar dans bars_history pour DIVERGENCE lookback APRES detection
    (anti leak : on compare bar_current vs bars[-DIVERGENCE_PRICE_LOOKBACK]
    qui est avant l'append).

    Returns:
        list[PlotTwist] : 0 a 4 twists detectes sur cette bar (les detectors
        sont independants, plusieurs peuvent fire en meme temps).
    """
    with state.lock:
        state.bar_idx_current += 1
        twists: list[PlotTwist] = []

        # Detect AVANT append pour preserver lookback CVD
        st_break = detect_structure_break(
            state, bar, swing_state, tick_size=tick_size,
            story_trackers=story_trackers, log_fn=log_fn,
        )
        if st_break is not None:
            twists.append(st_break)

        vol_anom = detect_volume_anomaly(state, bar, log_fn)
        if vol_anom is not None:
            twists.append(vol_anom)

        div = detect_divergence(state, bar, log_fn)
        if div is not None:
            twists.append(div)

        capit = detect_capitulation(state, bar, log_fn)
        if capit is not None:
            twists.append(capit)

        # Append bar APRES detection (pour next call divergence lookback)
        state.bars_history.append({
            "high": _safe_float(bar.get("high")),
            "low": _safe_float(bar.get("low")),
            "close": _safe_float(bar.get("close")),
            "open": _safe_float(bar.get("open")),
            "vol_z": _safe_float(bar.get("vol_zscore_20")),
            "atr": _safe_float(bar.get("atr")),
            "cvd": _safe_float(
                bar.get("cvd_5d_rolling_ffd") or bar.get("ctx_cvd_session")
            ),
            "bar_idx": state.bar_idx_current,
        })

        return twists
