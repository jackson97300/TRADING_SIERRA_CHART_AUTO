"""Bot 4 v2 regime_source — FORK CORE/regime_engine_v2.py (25/06/2026) + adaptations.

FORK Phase P2 (25/06/2026) :
- Isolation totale bot4_v2 (pas d'import CORE/*)
- Env var renommee BOT4V2_REGIME_SKIP_ENABLED (vs MIA_REGIME_V2_SKIP_ENABLED)
- Calib version v4_bot4v2_fork_20260625 (traçabilite)
- Module exposé bot4_v2.core.regime_source

Heritages V1 conserves IDENTIQUES (do NOT regress) :
- FIX confidence /12.0 -> /votes_exprimes (anti pattern 11 V1, 27/05)
- FIX range_pos echelle [0,1] default 0.5 (vs 50.0, 03/06)
- FIX mode TREND fallback votes directionnels (vs bias_proxy NEUTRE 99.7%, 03/06)
- FIX day_type INVALID guard Asia/London (vs trend systematique, 06/06)
- FIX atr_regime_zscore_60d cross-instrument (vs sess_range_atr NaN ES/MGC, 11/05)
- FIX seuils bias_proxy +/-0.20 (vs +/-0.30 99.7% NEUTRE, 03/06)
- FIX trend_up_votes / trend_down_votes (anti faux positifs 03/06 backtest)

Workflow trade Jackson preserve :
  1. DIRECTION CLAIRE (compute_regime ici)  <- STEP 0
  2. NIVEAU touch (P3 layers via P3 decision_router)
  3. RECONFIRMATION direction + orderflow
  4. TRADE

Source unique regime cross-bot4v2 :
  - bot4_v2/decision/route_narrative.py (P3) consomme via compute_regime()
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

from bot4_v2.observability.telemetry import get_logger

# Logger reserve P3 (consumer narrative_engine + decision_router emit
# BOT4V2_REGIME_KILL_SWITCH_ACTIVE / BOT4V2_REGIME_INSUFFICIENT_FEATURES
# au moment de consommer RegimeAnalysis.details). R1 review batch 2 P2.
_LOG = get_logger(__name__)  # noqa: F841 (reserve P3 consumers)

# ===========================================================================
# Kill switch + version v4 fork bot4v2
# ===========================================================================
# Rollback rapide via env var dedie :
#   BOT4V2_REGIME_SKIP_ENABLED=0 nssm restart MIA-Bot-4-Paper-v2  (30s)
# Note : namespace BOT4V2_* isole de CORE/regime_engine_v2 (MIA_REGIME_V2_*).
REGIME_SKIP_ENABLED: bool = os.environ.get(
    "BOT4V2_REGIME_SKIP_ENABLED", "1"
) == "1"

# Version calibration v4 = fork bot4v2 2026-06-25 (post fork v3 2026-05-27)
REGIME_CALIB_VERSION: str = "v4_bot4v2_fork_20260625"

# Seuil pour flag "votes insuffisants" (typique hors-RTH features MP NaN)
REGIME_MIN_VOTES_THRESHOLD: int = 4


@dataclass
class RegimeAnalysis:
    """Sortie unifiee detecteur de regime (5 features cles + details)."""
    mode: str                # "TREND" | "RANGE" | "NORMAL"
    favor: str               # "LONG" | "SHORT" | "NEUTRE"
    confidence: float        # [0.0, 1.0] — derive de votes nets exprimes
    trend_votes: int         # 0-12
    range_votes: int         # 0-12
    vol_regime: str          # "EXTREME" | "HIGH" | "NORMAL" | "LOW"
    bias_score: float        # [-1, 1] — proxy bias (BEAR <-> BULL)
    is_actionable: bool      # True si mode != NORMAL + favor != NEUTRE + vol != EXTREME
    details: list = field(default_factory=list)
    bear_factors: int = 0
    bull_factors: int = 0
    trend_up_votes: int = 0
    trend_down_votes: int = 0


# ===========================================================================
# Helpers safe-extraction
# ===========================================================================


def _get_field(d: dict, key: str, default: float = 0.0) -> float:
    """Lit float du dict avec fallback (NaN, None, missing)."""
    v = d.get(key)
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


def _get_int_field(d: dict, key: str, default: int = 0) -> int:
    v = d.get(key)
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:
            return default
        return int(f)
    except (TypeError, ValueError):
        return default


# ===========================================================================
# Bias proxy (sans dependance compute_bias pour eviter cycle import)
# ===========================================================================


def _compute_bias_proxy(bar: dict) -> Tuple[float, str, int, int]:
    """Calcul bias proxy (sans CORE/bias_calculator dependency).

    Returns:
        (bias_score [-1,1], bias_label, bear_factors_count, bull_factors_count)
    """
    score = 0.0
    bear_factors = 0
    bull_factors = 0

    vwap_slope = _get_field(bar, "vwap_slope_10", 0.0)
    if vwap_slope > 1.0:
        score += 0.25
        bull_factors += 1
    elif vwap_slope < -1.0:
        score -= 0.25
        bear_factors += 1

    delta_dir = _get_int_field(bar, "delta_day_dir", 0)
    cvd_dir = _get_int_field(bar, "cvd_day_dir", 0)
    of_dir = delta_dir or cvd_dir
    if of_dir > 0:
        score += 0.25
        bull_factors += 1
    elif of_dir < 0:
        score -= 0.25
        bear_factors += 1

    # FIX V1 (03/06) : range_pos echelle [0,1] (vs [0,100] silent mort 18/05+).
    pos = _get_field(bar, "range_pos", 0.5)
    if pos > 0.70:
        score -= 0.20
        bear_factors += 1
    elif pos < 0.30:
        score += 0.20
        bull_factors += 1

    vwap_d = _get_int_field(bar, "vwap_d_side", 0)
    if vwap_d > 0:
        score += 0.15
        bull_factors += 1
    elif vwap_d < 0:
        score -= 0.15
        bear_factors += 1

    delta_div = _get_int_field(bar, "delta_divergence", 0)
    if delta_div != 0:
        if delta_div > 0:
            score += 0.15
            bull_factors += 1
        else:
            score -= 0.15
            bear_factors += 1

    score = max(-1.0, min(1.0, score))
    # FIX V1 (03/06) : seuils +/-0.20 (vs +/-0.30 99.7% NEUTRE empirique).
    if score > 0.20:
        label = "BULLISH"
    elif score < -0.20:
        label = "BEARISH"
    else:
        label = "NEUTRE"
    return score, label, bear_factors, bull_factors


# ===========================================================================
# Compute regime — coeur logique (10 votes ponderes)
# ===========================================================================


def compute_regime(bar: dict) -> RegimeAnalysis:
    """Detecte regime via 10 votes ponderes Market Profile + VWAP + Open.

    Args:
        bar: dict ligne enriched (sierra_enriched JSONL ou parquet V4).
             Doit contenir 28 features regime DMP.

    Returns:
        RegimeAnalysis avec mode/favor/confidence/votes/vol_regime/bias.
    """
    # Kill switch rollback rapide sans redeploy code
    if not REGIME_SKIP_ENABLED:
        return RegimeAnalysis(
            mode="NORMAL", favor="NEUTRE", confidence=0.0,
            trend_votes=0, range_votes=0, vol_regime="NORMAL",
            bias_score=0.0, is_actionable=False,
            details=["KILL_SWITCH_REGIME_DISABLED"],
        )

    if not bar:
        return RegimeAnalysis(
            mode="NORMAL", favor="NEUTRE", confidence=0.0,
            trend_votes=0, range_votes=0, vol_regime="NORMAL",
            bias_score=0.0, is_actionable=False,
            details=["empty_bar"],
        )

    trend_votes = 0
    range_votes = 0
    # FIX V1 (03/06) : tracker direction des votes trend (LONG vs SHORT bias).
    trend_up_votes = 0
    trend_down_votes = 0
    details = []

    # 1. IB Breakout (poids 2 si breakout, 1 si IB intacte)
    ib_up = _get_int_field(bar, "ib_broken_up", 0)
    ib_dn = _get_int_field(bar, "ib_broken_down", 0)
    ib_formed_bool = _get_int_field(bar, "ib_formed_bool", -1)
    if ib_formed_bool == -1:
        ib_range = _get_field(bar, "ib_range_ticks", 0.0)
        ib_formed_bool = 1 if ib_range > 0 else 0
    if ib_up or ib_dn:
        trend_votes += 2
        if ib_up:
            trend_up_votes += 2
        else:
            trend_down_votes += 2
        details.append("IB cassee " + ("UP" if ib_up else "DOWN"))
    elif ib_formed_bool:
        range_votes += 1
        details.append("IB intacte")

    # 2. Day Type Market Profile + FIX V1 (06/06) guard INVALID Asia/London
    day_type_raw = bar.get("day_type")
    is_day_type_valid = (
        day_type_raw is not None
        and not (isinstance(day_type_raw, float) and (day_type_raw != day_type_raw))
        and float(day_type_raw) >= 0
    )
    if is_day_type_valid:
        day_type = _get_int_field(bar, "day_type", 0)
        if day_type == 4:
            trend_votes += 2
            details.append("Day Type: Trend")
        elif day_type == 2:
            trend_votes += 1
            details.append("Day Type: Norm Variation")
        elif day_type == 1:
            range_votes += 1
            details.append("Day Type: Normal")
        elif day_type == 3:
            range_votes += 1
            details.append("Day Type: Neutral")
    else:
        details.append("Day Type: INVALID (Asia/London hors RTH) - skip vote")

    # 3. Single Prints (calibre p25=47, p75=170)
    single_prints = _get_int_field(bar, "single_print_count", 0)
    if single_prints > 100:
        trend_votes += 1
        details.append(f"SinglePrints: {single_prints} (fort)")
    elif single_prints < 30:
        range_votes += 1
        details.append(f"SinglePrints: {single_prints} (faible)")

    # 4. VWAP Slope (calibre grid search optimal 3.5)
    vwap_slope_10 = _get_field(bar, "vwap_slope_10", 0.0)
    vwap_sl = abs(vwap_slope_10)
    if vwap_sl > 3.5:
        trend_votes += 1
        if vwap_slope_10 > 0:
            trend_up_votes += 1
        else:
            trend_down_votes += 1
        details.append(f"VWAP slope: {vwap_slope_10:+.1f}")
    elif vwap_sl < 0.5:
        range_votes += 1
        details.append(f"VWAP slope: {vwap_slope_10:+.1f} (plat)")

    # 5. Sess/ATR (vol ratio)
    atr_ratio = _get_field(bar, "sess_range_atr", 0.0)
    if atr_ratio > 1.0:
        trend_votes += 1
        details.append(f"Sess/ATR: {atr_ratio:.2f}x (expansion)")
    elif atr_ratio < 0.4:
        range_votes += 1
        details.append(f"Sess/ATR: {atr_ratio:.2f}x (compression)")

    # 6. Open Type (1=OD up, 2=OD down, 3-4=OTD, 5-6=ORR)
    open_type = _get_int_field(bar, "open_type", 0)
    if open_type in (1, 2):
        trend_votes += 1
        if open_type == 1:
            trend_up_votes += 1
        else:
            trend_down_votes += 1
        details.append("Open Drive")
    elif open_type in (3, 4):
        trend_votes += 1
        if open_type == 3:
            trend_up_votes += 1
        else:
            trend_down_votes += 1
        details.append("Open Test Drive")
    elif open_type in (5, 6):
        range_votes += 1
        details.append("Open Rejection Reverse")

    # 7. Profile Shape (1=P, 2=b directionnel ; 0=D, 3=DoubleDist range)
    profile_shape = _get_int_field(bar, "profile_shape", -1)
    if profile_shape in (1, 2):
        trend_votes += 1
        if profile_shape == 1:
            trend_up_votes += 1
        else:
            trend_down_votes += 1
        details.append("Profile: " + ("P" if profile_shape == 1 else "b") + "-Shape")
    elif profile_shape in (0, 3):
        range_votes += 1
        details.append("Profile: " + ("D" if profile_shape == 0 else "DoubleDist"))

    # 8. POC distance (calibre p50=9, p75=19)
    poc_dist = _get_field(bar, "poc_bar_dist", 0.0)
    if poc_dist > 15:
        trend_votes += 1
        details.append(f"POC distant: {poc_dist:.0f} bars")
    elif poc_dist < 3:
        range_votes += 1
        details.append(f"POC proche: {poc_dist:.0f} bars")

    # 9. Bars in VA (% temps prix dans Value Area)
    bars_va = _get_field(bar, "bars_in_va", 0.0)
    if bars_va > 30:
        range_votes += 1
        details.append(f"Bars in VA: {bars_va:.0f}% (confine)")
    elif bars_va < 10:
        trend_votes += 1
        details.append(f"Bars in VA: {bars_va:.0f}% (hors VA)")

    # 10. Trend Day Probability (calibre p75=0.35)
    tdp = _get_field(bar, "trend_day_probability", 0.5)
    if tdp > 0.30:
        trend_votes += 1
        details.append(f"TrendProb: {tdp:.0%}")
    elif tdp < 0.10:
        range_votes += 1
        details.append(f"TrendProb: {tdp:.0%} (faible)")

    # ===== Mode verdict (seuil grid search optimal mode_strong=3) =====
    if trend_votes >= 3 and trend_votes >= range_votes + 1:
        mode = "TREND"
    elif range_votes >= 3 and range_votes >= trend_votes + 1:
        mode = "RANGE"
    else:
        mode = "NORMAL"

    # ===== Bias proxy (pour favor en mode TREND/NORMAL) =====
    bias_score, bias_label, bear_factors, bull_factors = _compute_bias_proxy(bar)
    # FIX V1 (03/06) : default 0.5 (centre) au lieu de 50.0.
    range_pos = _get_field(bar, "range_pos", 0.5)

    # ===== Direction (favor) =====
    if mode == "RANGE":
        if range_pos >= 0.70:
            favor = "SHORT"
        elif range_pos <= 0.30:
            favor = "LONG"
        else:
            favor = "NEUTRE"
    elif mode == "TREND":
        # FIX V1 (03/06) : mode TREND infere favor depuis votes directionnels.
        # ITERATION 03/06 : anti faux positifs (si aucun vote directionnel, NEUTRE).
        if trend_up_votes > trend_down_votes:
            favor = "LONG"
            details.append(
                f"TREND_favor_VOTES_UP({trend_up_votes}>{trend_down_votes})"
            )
        elif trend_down_votes > trend_up_votes:
            favor = "SHORT"
            details.append(
                f"TREND_favor_VOTES_DN({trend_down_votes}>{trend_up_votes})"
            )
        elif trend_up_votes == 0 and trend_down_votes == 0:
            favor = "NEUTRE"
            details.append("TREND_favor_NEUTRE_no_directional_votes")
        elif bias_label == "BULLISH":
            favor = "LONG"
            details.append(f"TREND_favor_BIAS_BULL_tied_{trend_up_votes}")
        elif bias_label == "BEARISH":
            favor = "SHORT"
            details.append(f"TREND_favor_BIAS_BEAR_tied_{trend_down_votes}")
        else:
            favor = "NEUTRE"
            details.append(f"TREND_favor_NEUTRE_tied_{trend_up_votes}_no_bias")
    elif bias_label == "BULLISH":
        favor = "LONG"
    elif bias_label == "BEARISH":
        favor = "SHORT"
    else:
        favor = "NEUTRE"

    # Override coherence : evite LONG si structure bearish
    if favor == "LONG" and bear_factors >= 3:
        favor = "NEUTRE"
        details.append("Override LONG -> NEUTRE (3+ bear factors)")
    elif favor == "SHORT" and bull_factors >= 3:
        favor = "NEUTRE"
        details.append("Override SHORT -> NEUTRE (3+ bull factors)")

    # ===== Volatility regime — FIX V1 (11/05) atr_regime_zscore_60d =====
    atr_z = _get_field(bar, "atr_regime_zscore_60d", float('nan'))
    if atr_z != atr_z:  # NaN — premiers 60j rolling, neutralite explicite
        vol_regime = "NORMAL"
    elif atr_z >= 2.5:
        vol_regime = "EXTREME"
    elif atr_z >= 1.5:
        vol_regime = "HIGH"
    elif atr_z >= -0.5:
        vol_regime = "NORMAL"
    else:
        vol_regime = "LOW"

    # ===== Confidence FIX V1 (27/05) /votes_exprimes (anti pattern 11 V1) =====
    # AVANT (regime_engine.py original) : net / 12.0 -> max conf 0.25 (~25%).
    # APRES : net / votes_exprimes. 5 trend / 2 range : net=3, total=7 -> conf=0.43.
    # Anti pattern 11 V1 (2 patches NORMALIZE_MAX 0.25 -> 0.35 sur sparadrap).
    net = abs(trend_votes - range_votes)
    total_votes = trend_votes + range_votes
    confidence = min(1.0, net / max(total_votes, 1))

    # Flag votes insuffisants
    if total_votes < REGIME_MIN_VOTES_THRESHOLD:
        details.append(
            f"INSUFFICIENT_FEATURES (votes={total_votes} < {REGIME_MIN_VOTES_THRESHOLD})"
        )

    # ===== Is actionable (calibre conf_actionable=0.10) =====
    is_actionable = (
        mode != "NORMAL"
        and favor != "NEUTRE"
        and vol_regime != "EXTREME"
        and confidence >= 0.10
    )

    return RegimeAnalysis(
        mode=mode, favor=favor,
        confidence=round(confidence, 2),
        trend_votes=trend_votes, range_votes=range_votes,
        vol_regime=vol_regime,
        bias_score=round(bias_score, 2),
        is_actionable=is_actionable,
        details=details,
        bear_factors=bear_factors,
        bull_factors=bull_factors,
        trend_up_votes=trend_up_votes,
        trend_down_votes=trend_down_votes,
    )


def compute_regime_dict(bar: dict) -> dict:
    """Wrapper retournant dict (cohrence pipeline V4 builder)."""
    r = compute_regime(bar)
    return {
        "regime_mode": r.mode,
        "regime_favor": r.favor,
        "regime_confidence": r.confidence,
        "regime_trend_votes": r.trend_votes,
        "regime_range_votes": r.range_votes,
        "regime_vol": r.vol_regime,
        "regime_actionable": int(r.is_actionable),
    }
