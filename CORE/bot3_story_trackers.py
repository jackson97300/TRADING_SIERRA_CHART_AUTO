"""bot3_story_trackers.py - Story Trackers Bot 3 v2 Narrative Layer (Phase 1).

Module : 13 trackers narratifs (11 obligatoires + 2 bonus) consumes par
NarrativeStateMachine (NSM) pour transitions T10/T11/T20-T29 (ICT BOS detection,
TREND continuation, Wyckoff Spring, Exhaustion).

Architecture : Bot 3 v2 Narrative Layer (Phase 1 TRACKING ONLY).
Pattern reference : `CORE/live_enricher_state.py:51-200` (LiveEnricherState).
Decision pattern : ADR 0002 (mirror LiveEnricherState, NOT BreakoutRetestSM).

Data source : Databento payload V4 enriched canonical (~465 cols/bar).
  Inputs principaux : high, low, close, open, volume, ts_event,
                      session_date_trading, session, mins_et.
  Input critique : swing_state (last_swing_high.price / last_swing_low.price)
                   depuis sessions_swings_lag_streaming.py.

13 Trackers (cf DOCS/specs/2026-05-18-bot3v2-phase1-story-trackers-spec.md) :
  1. hh_count_60                 : Higher Highs count (ICT HH structural)
  2. ll_count_60                 : Lower Lows count (mirror)
  3. swing_progression_score     : (hh - ll) / (hh + ll) ∈ [-1, +1] (Dow/Wyckoff)
  4. slope_close_30              : OLS regression close 30 bars (Lopez Ch 5)
  5. slope_close_60              : OLS regression close 60 bars
  6. bars_since_last_BOS         : ICT Break of Structure detection
  7. last_BOS_dir                : -1 / 0 / +1
  8. bars_since_session_high     : Dalton Ch 8 Initial Balance
  9. bars_since_session_low      : mirror
  10. acceptance_zones_session   : Dalton Ch 9-10 HVN intra-session
  11. rejection_count_at_level   : Anti re-fire MQ_PUT (Dalton p.102)
  Bonus :
  12. hh_count_5                 : Anti contradictoire BOS court terme
  13. bars_since_open            : NSM T6/T7 OPEN_DRIVE require bar_idx > 30

Created : 2026-05-18 by Jackson + Claude (mode mentor proactif)
Last modified : 2026-05-18 - creation Phase 1 J+0 PM (spec agent 4.30/5)

Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md
Review trace : LOGS/reviews/REVIEW_BOT3V2_story_trackers_*.json
Memory feedback : .claude/memory/feedback_bot3v2_story_*.md (post-review)

Auteur : Bot 3 v2 Narrative Layer Phase 1
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 : creation skeleton 13 trackers (Phase 1 J+0 PM, ADR 0002+0003)
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

try:
    from CORE.bot3_narrative_logging import emit
except ImportError:
    from bot3_narrative_logging import emit

STORY_TRACKERS_SCHEMA_VERSION: str = "2.0.0"
BARS_HISTORY_MAXLEN: int = 60
HH_LOOKBACK: int = 10  # bars de lookback pour HH/LL detection
ACCEPTANCE_TIGHT_RANGE_RATIO: float = 0.5  # range 3 bars < 0.5 * atr_session
ACCEPTANCE_VOL_MULT: float = 1.2  # vol 3 bars > 1.2 * mean session
ACCEPTANCE_MAX_ZONES_PER_SESSION: int = 10  # cap memoire
TREND_CONFIRMED_HH_THRESHOLD: int = 3
TREND_CONFIRMED_SLOPE_THRESHOLD: float = 0.15
THROTTLE_TREND_CONFIRMED_BARS: int = 30
THROTTLE_REVERSAL_CANDIDATE_BARS: int = 10


@dataclass
class StoryTrackersState:
    """State Story Trackers per symbol (mirror LiveEnricherState pattern ADR 0002).

    1 instance per symbol. Pickle persistent via bot3_narrative_persistence.
    schema_version'ed pour backward compat futur. threading.RLock per-symbol
    pour concurrency NSM + mp_engine main loop.

    Attributes:
        symbol: ES.c.0 / NQ.c.0 / MGC.v.0.
        schema_version: bump si breaking change dataclass.
        bars_history: ring buffer deque(maxlen=60). Append O(1), evict FIFO.
        bars_since_last_BOS: -1 si jamais detecte, sinon counter.
        last_BOS_dir: -1 / 0 / +1.
        last_BOS_bar_idx: bar_idx au moment du dernier BOS.
        last_BOS_price: price reference swing au moment du BOS.
        current_session_date_trading: str (reset extremes au change).
        session_high / session_low: max/min de la session courante.
        bar_idx_session_high / low : index bar du high/low session.
        bar_idx_session_open: 1ere bar de la session courante.
        bar_idx_current: counter monotone bars depuis init.
        acceptance_zones: list HVN intra-session detectees.
        _acceptance_buffer: deque 3 bars pour detection sliding window.
        rejection_count_at_level: dict[level_name -> count].
        last_trend_confirmed_bar_idx: throttle BOT3_STORY_TREND_CONFIRMED log.
        last_reversal_candidate_bar_idx: throttle BOT3_STORY_REVERSAL_CANDIDATE log.
        last_slope_close_60: pour detection slope flip (reversal candidate).
        engine_states: extensible dict pour futurs trackers Phase 2+.
    """
    symbol: str = ""
    schema_version: str = STORY_TRACKERS_SCHEMA_VERSION
    bars_history: deque = field(default_factory=lambda: deque(maxlen=BARS_HISTORY_MAXLEN))
    bars_since_last_BOS: int = -1
    last_BOS_dir: int = 0
    last_BOS_bar_idx: int = -1
    last_BOS_price: float | None = None
    current_session_date_trading: str | None = None
    session_high: float | None = None
    session_low: float | None = None
    bar_idx_session_high: int = -1
    bar_idx_session_low: int = -1
    bar_idx_session_open: int = -1
    bar_idx_current: int = 0
    acceptance_zones: list[dict] = field(default_factory=list)
    _acceptance_buffer: deque = field(default_factory=lambda: deque(maxlen=3))
    rejection_count_at_level: dict[str, int] = field(default_factory=dict)
    last_trend_confirmed_bar_idx: int = -999
    last_reversal_candidate_bar_idx: int = -999
    last_slope_close_60: float = 0.0
    engine_states: dict[str, Any] = field(default_factory=dict)
    n_bars_processed: int = 0
    # Concurrency (exclu du pickle)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def __getstate__(self) -> dict:
        """Exclude _lock du pickle (cf live_enricher_state.py:95-103)."""
        state = self.__dict__.copy()
        state.pop("_lock", None)
        return state

    def __setstate__(self, state: dict) -> None:
        """Restore + recreate _lock au load."""
        self.__dict__.update(state)
        self._lock = threading.RLock()


# ═══════════════════════════════════════════════════════════════════════════
# Pure helpers (stateless, recompute depuis bars_history)
# ═══════════════════════════════════════════════════════════════════════════

def _compute_hh_count(bars: deque, window: int = BARS_HISTORY_MAXLEN,
                     lookback: int = HH_LOOKBACK) -> int:
    """Count Higher Highs sur window. HH = high[i] > max(high[i-lookback:i]).

    Args:
        bars: deque of bar dicts (high required).
        window: max bars considered from end.
        lookback: bars en arriere pour comparaison HH.

    Returns:
        int count HH dans la fenetre.
    """
    if len(bars) < lookback + 1:
        return 0
    bars_list = list(bars)[-window:]
    count = 0
    for i in range(lookback, len(bars_list)):
        h_i = bars_list[i].get("high")
        if h_i is None or (isinstance(h_i, float) and math.isnan(h_i)):
            continue
        max_prev = max(
            (b.get("high", -math.inf) for b in bars_list[i - lookback:i]),
            default=-math.inf,
        )
        if h_i > max_prev:
            count += 1
    return count


def _compute_ll_count(bars: deque, window: int = BARS_HISTORY_MAXLEN,
                     lookback: int = HH_LOOKBACK) -> int:
    """Mirror SHORT : count Lower Lows. LL = low[i] < min(low[i-lookback:i])."""
    if len(bars) < lookback + 1:
        return 0
    bars_list = list(bars)[-window:]
    count = 0
    for i in range(lookback, len(bars_list)):
        l_i = bars_list[i].get("low")
        if l_i is None or (isinstance(l_i, float) and math.isnan(l_i)):
            continue
        min_prev = min(
            (b.get("low", math.inf) for b in bars_list[i - lookback:i]),
            default=math.inf,
        )
        if l_i < min_prev:
            count += 1
    return count


def _compute_swing_progression_score(hh: int, ll: int) -> float:
    """(hh - ll) / max(hh + ll, 1) ∈ [-1.0, +1.0]. Dow Theory / Wyckoff."""
    total = max(hh + ll, 1)
    return (hh - ll) / total


def _compute_slope_close(bars: deque, window: int) -> float:
    """OLS regression analytique fermee (PAS np.polyfit pour perf <50us).

    Formule : slope = (n*Σxy − Σx*Σy) / (n*Σx² − (Σx)²)
    Reference : Lopez AFML Ch 5 stationnarite via slope (PAS EMA).

    Returns:
        float slope (points/bar). 0.0 si insufficient data.
    """
    if len(bars) < window:
        return 0.0
    closes = [b.get("close") for b in list(bars)[-window:]]
    # Filter None/NaN
    valid = [(i, c) for i, c in enumerate(closes)
             if c is not None and not (isinstance(c, float) and math.isnan(c))]
    n = len(valid)
    if n < 2:
        return 0.0
    sum_x = sum(i for i, _ in valid)
    sum_y = sum(c for _, c in valid)
    sum_xy = sum(i * c for i, c in valid)
    sum_xx = sum(i * i for i, _ in valid)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


# ═══════════════════════════════════════════════════════════════════════════
# Stateful helpers (mutent state)
# ═══════════════════════════════════════════════════════════════════════════

def _append_bar(state: StoryTrackersState, bar: dict) -> None:
    """Append bar normalise au ring buffer + increment counter."""
    minimal = {
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "open": bar.get("open"),
        "volume": bar.get("volume"),
        "ts": bar.get("ts_event") or bar.get("ts"),
        "session_date_trading": bar.get("session_date_trading"),
        "session": bar.get("session"),
    }
    state.bars_history.append(minimal)
    state.bar_idx_current += 1
    state.n_bars_processed += 1


def _update_session_extremes(state: StoryTrackersState, bar: dict) -> None:
    """Update session_high/low + bar_idx + open. Reset si SDT change."""
    sdt = bar.get("session_date_trading")
    if sdt != state.current_session_date_trading:
        # Reset session : new SDT
        state.current_session_date_trading = sdt
        state.session_high = None
        state.session_low = None
        state.bar_idx_session_high = state.bar_idx_current
        state.bar_idx_session_low = state.bar_idx_current
        state.bar_idx_session_open = state.bar_idx_current
        # Reset acceptance zones + buffer (new session = fresh)
        state.acceptance_zones = []
        state._acceptance_buffer = deque(maxlen=3)

    high = bar.get("high")
    low = bar.get("low")
    if high is not None and not (isinstance(high, float) and math.isnan(high)):
        if state.session_high is None or high > state.session_high:
            state.session_high = float(high)
            state.bar_idx_session_high = state.bar_idx_current
    if low is not None and not (isinstance(low, float) and math.isnan(low)):
        if state.session_low is None or low < state.session_low:
            state.session_low = float(low)
            state.bar_idx_session_low = state.bar_idx_current


def _detect_bos(
    state: StoryTrackersState,
    bar: dict,
    swing_state: Any,
    log_fn: Any = None,
) -> None:
    """ICT canonical Break of Structure detection + state update + emit log.

    Bullish BOS : close[i] > last_swing_high.price ET close[i-1] <= last_swing_high.price
    Bearish BOS : close[i] < last_swing_low.price ET close[i-1] >= last_swing_low.price

    Increment bars_since_last_BOS sauf si nouveau BOS detecte (reset 0).
    """
    # Increment compteur sauf si on detecte nouveau BOS (reset)
    if state.bars_since_last_BOS >= 0:
        state.bars_since_last_BOS += 1

    close = bar.get("close")
    if close is None or (isinstance(close, float) and math.isnan(close)):
        return
    close_f = float(close)

    # Previous close = avant l'append courant (donc dernier element history[-2] avant append)
    # Mais on a deja append : history[-1] = bar courante, history[-2] = previous
    if len(state.bars_history) < 2:
        return
    prev_close = state.bars_history[-2].get("close")
    if prev_close is None or (isinstance(prev_close, float) and math.isnan(prev_close)):
        return
    prev_close_f = float(prev_close)

    swing_high_price = getattr(getattr(swing_state, "last_swing_high", None), "price", None)
    swing_low_price = getattr(getattr(swing_state, "last_swing_low", None), "price", None)

    bos_detected_dir = 0
    bos_ref_price = None

    if swing_high_price is not None:
        if close_f > swing_high_price and prev_close_f <= swing_high_price:
            bos_detected_dir = +1
            bos_ref_price = swing_high_price

    if swing_low_price is not None and bos_detected_dir == 0:
        if close_f < swing_low_price and prev_close_f >= swing_low_price:
            bos_detected_dir = -1
            bos_ref_price = swing_low_price

    if bos_detected_dir != 0:
        state.bars_since_last_BOS = 0
        state.last_BOS_dir = bos_detected_dir
        state.last_BOS_bar_idx = state.bar_idx_current
        state.last_BOS_price = close_f
        emit(
            "BOT3_STORY_BOS_DETECTED",
            log_fn=log_fn,
            sym=state.symbol,
            bos_dir=bos_detected_dir,
            bos_price=close_f,
            bar_idx=state.bar_idx_current,
            prev_close=prev_close_f,
            swing_ref=bos_ref_price,
        )


def _update_acceptance_zones(state: StoryTrackersState, bar: dict) -> None:
    """Detect HVN intra-session : 3 bars consecutives tight range + vol > seuil.

    Critere :
      max(high[-3:]) - min(low[-3:]) < ACCEPTANCE_TIGHT_RANGE_RATIO * atr_session_proxy
      sum(volume[-3:]) > ACCEPTANCE_VOL_MULT * mean_volume_session

    atr_session_proxy = mean(high-low) sur 20 dernieres bars (cheap proxy).
    Si detecte : append zone {price_center, count, bar_idx_start} (cap MAX zones).
    """
    state._acceptance_buffer.append({
        "high": bar.get("high"),
        "low": bar.get("low"),
        "close": bar.get("close"),
        "volume": bar.get("volume"),
        "bar_idx": state.bar_idx_current,
    })

    if len(state._acceptance_buffer) < 3:
        return
    if len(state.acceptance_zones) >= ACCEPTANCE_MAX_ZONES_PER_SESSION:
        return

    buf = list(state._acceptance_buffer)
    highs = [b["high"] for b in buf if b["high"] is not None]
    lows = [b["low"] for b in buf if b["low"] is not None]
    vols = [b["volume"] for b in buf if b["volume"] is not None]
    closes = [b["close"] for b in buf if b["close"] is not None]
    if len(highs) < 3 or len(lows) < 3 or len(vols) < 3 or len(closes) < 3:
        return

    range_3 = max(highs) - min(lows)
    vol_3 = sum(vols)

    # atr_session_proxy : mean(high-low) sur 20 last bars history
    if len(state.bars_history) < 20:
        return
    recent_20 = list(state.bars_history)[-20:]
    valid_hl = [(b["high"] - b["low"]) for b in recent_20
                if b["high"] is not None and b["low"] is not None]
    if not valid_hl:
        return
    atr_proxy = sum(valid_hl) / len(valid_hl)
    if atr_proxy <= 0:
        return

    # mean_volume_session : approxime avec mean volume 20 last bars
    valid_vols = [b["volume"] for b in recent_20 if b["volume"] is not None]
    if not valid_vols:
        return
    mean_vol = sum(valid_vols) / len(valid_vols)
    if mean_vol <= 0:
        return

    tight = range_3 < ACCEPTANCE_TIGHT_RANGE_RATIO * atr_proxy
    high_vol = vol_3 > ACCEPTANCE_VOL_MULT * mean_vol * 3

    if tight and high_vol:
        state.acceptance_zones.append({
            "price_center": (max(closes) + min(closes)) / 2,
            "count": 3,
            "bar_idx_start": buf[0]["bar_idx"],
            "bar_idx_end": buf[-1]["bar_idx"],
        })


# ═══════════════════════════════════════════════════════════════════════════
# API publique
# ═══════════════════════════════════════════════════════════════════════════

def increment_rejection_at_level(state: StoryTrackersState, level_name: str) -> None:
    """API externe : incremente compteur rejection pour un level (touche sans GO).

    Appele par Bot 3 mp_engine quand level touche mais decision = SKIP.
    Anti-pattern P0-2 : ne reset PAS au session change (decay Phase 2+).
    """
    with state.lock:
        state.rejection_count_at_level[level_name] = (
            state.rejection_count_at_level.get(level_name, 0) + 1
        )


def update_story_trackers(
    state: StoryTrackersState,
    bar: dict,
    swing_state: Any,
    log_fn: Any = None,
) -> dict[str, Any]:
    """Update incremental sur 1 bar. Returns snapshot consume par NSM.

    Args:
        state: StoryTrackersState mutable (mirror EdgeZonesState pattern).
        bar: payload V4 enriched canonical (dict avec high, low, close, etc.).
        swing_state: SessionsSwingsLagState ref (last_swing_high/low).
        log_fn: callable optionnel pour log capture en tests.

    Returns:
        dict snapshot 13 trackers + meta (cf spec section 2.2).
    """
    with state.lock:
        _append_bar(state, bar)
        _update_session_extremes(state, bar)
        _detect_bos(state, bar, swing_state, log_fn=log_fn)
        _update_acceptance_zones(state, bar)

        hh_60 = _compute_hh_count(state.bars_history, BARS_HISTORY_MAXLEN, HH_LOOKBACK)
        ll_60 = _compute_ll_count(state.bars_history, BARS_HISTORY_MAXLEN, HH_LOOKBACK)
        hh_5 = _compute_hh_count(state.bars_history, 5, 2)
        ll_5 = _compute_ll_count(state.bars_history, 5, 2)
        score = _compute_swing_progression_score(hh_60, ll_60)
        slope_30 = _compute_slope_close(state.bars_history, 30)
        slope_60 = _compute_slope_close(state.bars_history, 60)

        # Emit BOT3_STORY_TREND_CONFIRMED (throttle 30 bars)
        bars_since_trend = state.bar_idx_current - state.last_trend_confirmed_bar_idx
        if (
            hh_60 >= TREND_CONFIRMED_HH_THRESHOLD
            and slope_60 > TREND_CONFIRMED_SLOPE_THRESHOLD
            and bars_since_trend >= THROTTLE_TREND_CONFIRMED_BARS
        ):
            emit(
                "BOT3_STORY_TREND_CONFIRMED",
                log_fn=log_fn,
                sym=state.symbol,
                trend_dir=+1,
                hh=hh_60,
                ll=ll_60,
                slope60=slope_60,
                bar_idx=state.bar_idx_current,
            )
            state.last_trend_confirmed_bar_idx = state.bar_idx_current
        elif (
            ll_60 >= TREND_CONFIRMED_HH_THRESHOLD
            and slope_60 < -TREND_CONFIRMED_SLOPE_THRESHOLD
            and bars_since_trend >= THROTTLE_TREND_CONFIRMED_BARS
        ):
            emit(
                "BOT3_STORY_TREND_CONFIRMED",
                log_fn=log_fn,
                sym=state.symbol,
                trend_dir=-1,
                hh=hh_60,
                ll=ll_60,
                slope60=slope_60,
                bar_idx=state.bar_idx_current,
            )
            state.last_trend_confirmed_bar_idx = state.bar_idx_current

        # Emit BOT3_STORY_REVERSAL_CANDIDATE (slope flip + contradiction HH/LL)
        bars_since_rev = state.bar_idx_current - state.last_reversal_candidate_bar_idx
        slope_flip = (
            (state.last_slope_close_60 > 0.05 and slope_60 < -0.05)
            or (state.last_slope_close_60 < -0.05 and slope_60 > 0.05)
        )
        contradiction = (
            (slope_60 < 0 and ll_5 == 0)  # bearish but no recent LL
            or (slope_60 > 0 and hh_5 == 0)  # bullish but no recent HH
        )
        if slope_flip and contradiction and bars_since_rev >= THROTTLE_REVERSAL_CANDIDATE_BARS:
            emit(
                "BOT3_STORY_REVERSAL_CANDIDATE",
                log_fn=log_fn,
                sym=state.symbol,
                slope60_prev=state.last_slope_close_60,
                slope60=slope_60,
                hh5=hh_5,
                ll5=ll_5,
            )
            state.last_reversal_candidate_bar_idx = state.bar_idx_current

        state.last_slope_close_60 = slope_60

        # Snapshot consume par NSM
        return {
            "hh_count_60": hh_60,
            "ll_count_60": ll_60,
            "swing_progression_score": score,
            "slope_close_30": slope_30,
            "slope_close_60": slope_60,
            "bars_since_last_BOS": state.bars_since_last_BOS,
            "last_BOS_dir": state.last_BOS_dir,
            "bars_since_session_high": (
                state.bar_idx_current - state.bar_idx_session_high
                if state.bar_idx_session_high >= 0 else 0
            ),
            "bars_since_session_low": (
                state.bar_idx_current - state.bar_idx_session_low
                if state.bar_idx_session_low >= 0 else 0
            ),
            "acceptance_zones_session": list(state.acceptance_zones),
            "rejection_count_at_level": dict(state.rejection_count_at_level),
            "hh_count_5": hh_5,
            "bars_since_open": (
                state.bar_idx_current - state.bar_idx_session_open
                if state.bar_idx_session_open >= 0 else 0
            ),
        }
