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
except ModuleNotFoundError:
    from bot3_narrative_logging import emit  # type: ignore[no-redef]

PLOT_TWIST_SCHEMA_VERSION: str = "2.0.0"

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
THROTTLE_BOS_BARS: int = 30             # BOS plus strict (Pruden 1-3 BOS reels/jour)
TICK_THRESHOLD_BOS: float = 2.0         # close>swing+2*tick = acceptance Dalton


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
    climax_buffer: deque = field(
        default_factory=lambda: deque(maxlen=CAPITULATION_BARS_REQUIRED)
    )
    last_twist_bar_idx: dict[str, int] = field(default_factory=dict)
    bar_idx_current: int = 0
    last_BOS_dir: int = 0
    last_BOS_bar_idx: int = -1
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
    tick_size: float = 0.25,
    log_fn: Callable[..., None] | None = None,
) -> PlotTwist | None:
    """ICT BOS/CHoCH : close casse swing avec confirmation.

    BOS bullish : close > last_swing_high + 2*tick + vol_z>0 (acceptance Dalton).
    BOS bearish : close < last_swing_low - 2*tick + vol_z>0.

    Anti-double-fire : meme direction throttle 3 bars (state.last_BOS_*).
    """
    close = _safe_float(bar.get("close"))
    vol_z = _safe_float(bar.get("vol_zscore_20"))
    swing_high = _swing_high_price(swing_state)
    swing_low = _swing_low_price(swing_state)

    if close is None or vol_z is None or vol_z <= 0:
        return None

    # Guard : swing price doit etre > 0 (sinon placeholder default = pas de swing reel)
    # Important : un swing_high=0.0 (StubSwingPoint default ou cold start) ferait
    # toujours match BOS bullish car close > 0.5. Skip si swing invalide.
    swing_high_valid = swing_high is not None and swing_high > 0.0
    swing_low_valid = swing_low is not None and swing_low > 0.0

    # BOS bullish
    if (swing_high_valid
            and close > swing_high + TICK_THRESHOLD_BOS * tick_size):
        # Anti double-fire meme direction
        if state.last_BOS_dir == +1 and (
            state.bar_idx_current - state.last_BOS_bar_idx
        ) < THROTTLE_BOS_BARS:
            return None
        state.last_BOS_dir = +1
        state.last_BOS_bar_idx = state.bar_idx_current
        state.last_twist_bar_idx["STRUCTURE_BREAK"] = state.bar_idx_current
        emit(
            "BOT3_PLOT_TWIST_STRUCTURE_BREAK",
            log_fn=log_fn,
            sym=state.symbol,
            direction=+1,
            close=close,
            swing_ref=swing_high,
            bar_ts=str(bar.get("ts_event_iso", "")),
        )
        return PlotTwist(
            twist_type="STRUCTURE_BREAK",
            direction=+1,
            severity=min(1.0, abs(close - swing_high) / max(swing_high * 0.001, 1.0)),
            bar_ts=str(bar.get("ts_event_iso", "")),
            bar_idx=state.bar_idx_current,
            symbol=state.symbol,
            triggering_features={
                "close": close, "swing_high": swing_high, "vol_z": vol_z,
            },
        )

    # BOS bearish
    if (swing_low_valid
            and close < swing_low - TICK_THRESHOLD_BOS * tick_size):
        if state.last_BOS_dir == -1 and (
            state.bar_idx_current - state.last_BOS_bar_idx
        ) < THROTTLE_TWIST_BARS:
            return None
        state.last_BOS_dir = -1
        state.last_BOS_bar_idx = state.bar_idx_current
        state.last_twist_bar_idx["STRUCTURE_BREAK"] = state.bar_idx_current
        emit(
            "BOT3_PLOT_TWIST_STRUCTURE_BREAK",
            log_fn=log_fn,
            sym=state.symbol,
            direction=-1,
            close=close,
            swing_ref=swing_low,
            bar_ts=str(bar.get("ts_event_iso", "")),
        )
        return PlotTwist(
            twist_type="STRUCTURE_BREAK",
            direction=-1,
            severity=min(1.0, abs(swing_low - close) / max(swing_low * 0.001, 1.0)),
            bar_ts=str(bar.get("ts_event_iso", "")),
            bar_idx=state.bar_idx_current,
            symbol=state.symbol,
            triggering_features={
                "close": close, "swing_low": swing_low, "vol_z": vol_z,
            },
        )

    return None


def detect_volume_anomaly(
    state: PlotTwistDetectorsState,
    bar: dict,
    log_fn: Callable[..., None] | None = None,
) -> PlotTwist | None:
    """Climax volume Wyckoff/Pruden : vol_z > 2.0 (event significatif).

    Direction = -1 si close<open (selling climax), +1 si close>open, 0 sinon.
    Throttle 3 bars : evite spam pendant grosse fenetre volume.
    """
    if _throttled(state, "VOLUME_ANOMALY"):
        return None

    vol_z = _safe_float(bar.get("vol_zscore_20"))
    if vol_z is None or vol_z < VOL_Z_ANOMALY_MIN:
        return None

    close = _safe_float(bar.get("close"))
    open_ = _safe_float(bar.get("open"))
    direction = 0
    if close is not None and open_ is not None:
        if close > open_:
            direction = +1
        elif close < open_:
            direction = -1

    state.last_twist_bar_idx["VOLUME_ANOMALY"] = state.bar_idx_current
    emit(
        "BOT3_PLOT_TWIST_VOLUME_ANOMALY",
        log_fn=log_fn,
        sym=state.symbol,
        vol_z=vol_z,
        bar_ts=str(bar.get("ts_event_iso", "")),
    )
    severity = min(1.0, (vol_z - VOL_Z_ANOMALY_MIN) / 3.0)  # 2.0=0.0, 5.0=1.0
    return PlotTwist(
        twist_type="VOLUME_ANOMALY",
        direction=direction,
        severity=severity,
        bar_ts=str(bar.get("ts_event_iso", "")),
        bar_idx=state.bar_idx_current,
        symbol=state.symbol,
        triggering_features={"vol_z": vol_z, "close": close, "open": open_},
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
    high_ref = ref_bar.get("high")
    low_ref = ref_bar.get("low")
    cvd_ref = ref_bar.get("cvd")
    if high_ref is None or low_ref is None or cvd_ref is None:
        return None

    price_delta_hi = high_now - high_ref
    price_delta_lo = low_now - low_ref
    cvd_delta = cvd_now - cvd_ref

    # Bearish divergence : price HH + CVD DOWN
    if price_delta_hi > 0 and cvd_delta < 0:
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
            severity=min(1.0, abs(cvd_delta) / 10000.0),  # arbitraire vs |CVD|
            bar_ts=str(bar.get("ts_event_iso", "")),
            bar_idx=state.bar_idx_current,
            symbol=state.symbol,
            triggering_features={
                "price_delta": price_delta_hi, "cvd_delta": cvd_delta,
                "high_now": high_now, "high_ref": high_ref,
            },
        )

    # Bullish divergence : price LL + CVD UP
    if price_delta_lo < 0 and cvd_delta > 0:
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
            severity=min(1.0, abs(cvd_delta) / 10000.0),
            bar_ts=str(bar.get("ts_event_iso", "")),
            bar_idx=state.bar_idx_current,
            symbol=state.symbol,
            triggering_features={
                "price_delta": price_delta_lo, "cvd_delta": cvd_delta,
                "low_now": low_now, "low_ref": low_ref,
            },
        )

    return None


def detect_capitulation(
    state: PlotTwistDetectorsState,
    bar: dict,
    log_fn: Callable[..., None] | None = None,
) -> PlotTwist | None:
    """Pruden Ch.7 capitulation : 3+ bars consecutifs avec vol_z>2.5 ET
    bar_range > 1.5*atr.

    Direction = -1 si majorite des bars close<open (selling climax),
                +1 si majorite close>open (buying climax).
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

    if is_climax:
        state.climax_buffer.append({
            "close": close, "open": open_, "vol_z": vol_z,
            "bar_idx": state.bar_idx_current,
        })
    else:
        # Bar non climax : reset buffer (capitulation = consecutive bars)
        state.climax_buffer.clear()
        return None

    # Check si on a CAPITULATION_BARS_REQUIRED bars consecutifs
    if len(state.climax_buffer) < CAPITULATION_BARS_REQUIRED:
        return None

    # Verifier consecutifs (bar_idx successifs)
    indices = [b["bar_idx"] for b in state.climax_buffer]
    if not all(indices[i] == indices[i - 1] + 1 for i in range(1, len(indices))):
        # Pas consecutifs : reset partiel garde le dernier
        last_bar = state.climax_buffer[-1]
        state.climax_buffer.clear()
        state.climax_buffer.append(last_bar)
        return None

    # Determiner direction
    downs = sum(1 for b in state.climax_buffer if b["close"] < b["open"])
    ups = sum(1 for b in state.climax_buffer if b["close"] > b["open"])
    direction = -1 if downs > ups else (+1 if ups > downs else 0)

    state.last_twist_bar_idx["CAPITULATION"] = state.bar_idx_current
    n_climax = len(state.climax_buffer)
    emit(
        "BOT3_PLOT_TWIST_CAPITULATION",
        log_fn=log_fn,
        sym=state.symbol,
        direction=direction,
        n_climax=n_climax,
        bar_ts=str(bar.get("ts_event_iso", "")),
    )
    return PlotTwist(
        twist_type="CAPITULATION",
        direction=direction,
        severity=min(1.0, n_climax / 5.0),  # 3 bars = 0.6, 5+ = 1.0
        bar_ts=str(bar.get("ts_event_iso", "")),
        bar_idx=state.bar_idx_current,
        symbol=state.symbol,
        triggering_features={
            "n_climax_bars": n_climax, "downs": downs, "ups": ups,
        },
    )


def scan_all(
    state: PlotTwistDetectorsState,
    bar: dict,
    swing_state: Any,
    tick_size: float = 0.25,
    log_fn: Callable[..., None] | None = None,
) -> list[PlotTwist]:
    """Scan tous les 4 detectors sur la bar courante.

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
        st_break = detect_structure_break(state, bar, swing_state, tick_size, log_fn)
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
