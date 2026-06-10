"""regime_detector.py — Detecteur de regime mutualise Bot 1 + Bot 3.

Source unique de verite pour la detection de regime de marche.
Sortie : RegimeAnalysis avec direction (LONG/SHORT/NEUTRE), mode (TREND/RANGE/NORMAL),
confidence, vol_regime, et flag is_actionable.

Architecture (Jackson 03/05/2026) :
  1. DIRECTION CLAIRE (regime + bias) — etape 1 du workflow trade
  2. NIVEAU touch — etape 2 (Bot 3 levels ou Bot 2 setups)
  3. RECONFIRMATION direction + orderflow — etape 3
  4. TRADE — etape 4

Bot 1 utilise detect_regime_dmp() avec un dict bar issu du DMP Sierra Chart JSONL
(262 colonnes, schema 3.7.x). Logique = 10 votes ponderes, identique au dashboard
build_regime_context() ligne 120-362 de DASHBOARD/api/builders.py.

Bot 3 utilise detect_regime_databento() avec un dict bar issu du parquet V4 enriched
(~426 colonnes Databento). Features regime partielles → fallback sur 6 votes
disponibles (vwap_slope_10, momentum_5b, position_in_range, atr_14m_pct, day_move,
n_single_prints_pct).

Reference :
  - DASHBOARD/api/builders.py:120-362 (build_regime_context dashboard)
  - CORE/bias_calculator.py (compute_bias)
  - feedback_regime_gex_finding.md (15/04 — regime-dependence edge)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RegimeAnalysis:
    """Sortie unifiee detecteur de regime."""
    direction: str           # "LONG" | "SHORT" | "NEUTRE"
    mode: str                # "TREND" | "RANGE" | "NORMAL"
    vol_regime: str          # "EXTREME" | "HIGH" | "NORMAL" | "LOW"
    confidence: float        # [0.0, 1.0]
    is_actionable: bool      # True si direction non-NEUTRE + mode != RANGE_CHOPPY
    trend_votes: int
    range_votes: int
    bias_score: float        # signed [-1, 1] (BEAR ... BULL)
    details: list = field(default_factory=list)
    source: str = ""         # "DMP" ou "DATABENTO_V4"


def _safe_float(d: dict, key: str, default: float = 0.0) -> float:
    """Lit float du dict avec fallback (NaN, None, missing)."""
    v = d.get(key)
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN check
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_int(d: dict, key: str, default: int = 0) -> int:
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


# =====================================================================
# BOT 1 — Detecteur DMP Sierra Chart (10 votes ponderes, code dashboard)
# =====================================================================

def detect_regime_dmp(bar: dict) -> RegimeAnalysis:
    """Detecte regime via DMP Sierra Chart features (Bot 1).

    Reproduction fidele de DASHBOARD/api/builders.py:120-362
    build_regime_context() — 10 votes ponderes :
      1. IB Breakout (poids 2)
      2. Day Type Market Profile (poids 2 ou 1)
      3. Single Prints
      4. VWAP Slope
      5. Sess/ATR
      6. Open Type (OD/OTD/ORR)
      7. Profile Shape (P/b/D/Double Dist)
      8. POC distance
      9. Bars in VA
      10. Trend Day Probability

    Args:
        bar: dict ligne JSONL DMP (schema 3.7.x, 262 colonnes)

    Returns:
        RegimeAnalysis avec source="DMP"
    """
    if not bar:
        return RegimeAnalysis("NEUTRE", "NORMAL", "NORMAL", 0.0, False, 0, 0, 0.0,
                              ["empty_bar"], "DMP")

    trend_votes = 0
    range_votes = 0
    details = []

    # 1. IB Breakout (poids 2)
    ib_up = _safe_int(bar, "ib_broken_up", 0)
    ib_dn = _safe_int(bar, "ib_broken_down", 0)
    ib_range = _safe_float(bar, "ib_range_ticks", 0.0)
    if ib_up or ib_dn:
        trend_votes += 2
        details.append("IB cassee " + ("UP" if ib_up else "DOWN"))
    elif ib_range > 0:
        range_votes += 1
        details.append("IB intacte")

    # 2. Day Type
    day_type = _safe_int(bar, "day_type", 0)
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

    # 3. Single Prints
    sp = _safe_int(bar, "single_print_count", 0)
    if sp > 10:
        trend_votes += 1
        details.append(f"SinglePrints: {sp} (fort)")
    elif sp < 3:
        range_votes += 1
        details.append(f"SinglePrints: {sp} (faible)")

    # 4. VWAP Slope
    vwap_slope = _safe_float(bar, "vwap_slope_10", 0.0)
    vwap_sl_abs = abs(vwap_slope)
    if vwap_sl_abs > 5:
        trend_votes += 1
        details.append(f"VWAP slope: {vwap_slope:+.1f}")
    elif vwap_sl_abs < 1:
        range_votes += 1
        details.append(f"VWAP slope: {vwap_slope:+.1f} (plat)")

    # 5. Sess/ATR
    atr_ratio = _safe_float(bar, "sess_range_atr", 0.0)
    if atr_ratio > 1.2:
        trend_votes += 1
        details.append(f"Sess/ATR: {atr_ratio:.2f}x (expansion)")
    elif atr_ratio < 0.6:
        range_votes += 1
        details.append(f"Sess/ATR: {atr_ratio:.2f}x (compression)")

    # 6. Open Type
    open_type = _safe_int(bar, "open_type", 0)
    if open_type in (1, 2):
        trend_votes += 1
        details.append("Open Drive")
    elif open_type in (3, 4):
        trend_votes += 1
        details.append("Open Test Drive")
    elif open_type in (5, 6):
        range_votes += 1
        details.append("Open Rejection Reverse")

    # 7. Profile Shape
    profile_shape = _safe_int(bar, "profile_shape", -1)
    if profile_shape in (1, 2):
        trend_votes += 1
        details.append("Profile: directionnel " + ("P" if profile_shape == 1 else "b"))
    elif profile_shape in (0, 3):
        range_votes += 1
        details.append("Profile: range " + ("D" if profile_shape == 0 else "DoubleDist"))

    # 8. POC distance
    poc_dist = _safe_float(bar, "poc_bar_dist", 0.0)
    if poc_dist > 30:
        trend_votes += 1
        details.append(f"POC distant: {poc_dist:.0f} bars")
    elif poc_dist < 5:
        range_votes += 1
        details.append(f"POC proche: {poc_dist:.0f} bars")

    # 9. Bars in VA
    bars_va = _safe_float(bar, "bars_in_va", 0.0)
    if bars_va > 60:
        range_votes += 1
        details.append(f"Bars in VA: {bars_va:.0f}% (confine)")
    elif bars_va < 30:
        trend_votes += 1
        details.append(f"Bars in VA: {bars_va:.0f}% (hors VA)")

    # 10. Trend Day Probability
    tdp = _safe_float(bar, "trend_day_probability", 0.5)
    if tdp > 0.65:
        trend_votes += 1
        details.append(f"TrendProb: {tdp:.0%}")
    elif tdp < 0.3:
        range_votes += 1
        details.append(f"TrendProb: {tdp:.0%} (faible)")

    # Mode verdict (seuil dashboard 5+ ou +2 d'avance)
    if trend_votes >= 5:
        mode = "TREND"
    elif range_votes >= 5:
        mode = "RANGE"
    elif trend_votes >= range_votes + 2:
        mode = "TREND"
    elif range_votes >= trend_votes + 2:
        mode = "RANGE"
    else:
        mode = "NORMAL"

    # Bias score (proxy via VWAP slope + delta_day_dir + range_pos)
    range_pos = _safe_float(bar, "range_pos", 50.0)
    delta_day_dir = _safe_int(bar, "delta_day_dir", 0)
    bias_score = 0.0
    if vwap_slope > 0: bias_score += 0.3
    elif vwap_slope < 0: bias_score -= 0.3
    if delta_day_dir > 0: bias_score += 0.3
    elif delta_day_dir < 0: bias_score -= 0.3
    if range_pos > 70: bias_score += 0.2
    elif range_pos < 30: bias_score -= 0.2
    bias_score = max(-1.0, min(1.0, bias_score))

    # Direction
    if mode == "RANGE":
        if range_pos >= 70: direction = "SHORT"
        elif range_pos <= 30: direction = "LONG"
        else: direction = "NEUTRE"
    elif bias_score > 0.3:
        direction = "LONG"
    elif bias_score < -0.3:
        direction = "SHORT"
    else:
        direction = "NEUTRE"

    # Volatility regime
    if atr_ratio >= 2.0: vol_regime = "EXTREME"
    elif atr_ratio >= 1.2: vol_regime = "HIGH"
    elif atr_ratio >= 0.5: vol_regime = "NORMAL"
    else: vol_regime = "LOW"

    # Confidence (conviction > 5 votes net)
    total_votes = trend_votes + range_votes
    net = abs(trend_votes - range_votes)
    confidence = min(1.0, net / 10.0) if total_votes > 0 else 0.0

    # Is actionable : direction non-NEUTRE + (TREND OU RANGE clair) + vol pas EXTREME
    is_actionable = (
        direction != "NEUTRE"
        and mode != "NORMAL"
        and vol_regime != "EXTREME"
        and confidence >= 0.2
    )

    return RegimeAnalysis(
        direction=direction, mode=mode, vol_regime=vol_regime,
        confidence=round(confidence, 2), is_actionable=is_actionable,
        trend_votes=trend_votes, range_votes=range_votes,
        bias_score=round(bias_score, 2), details=details, source="DMP",
    )


# =====================================================================
# BOT 3 — Detecteur Databento V4 enriched (6 votes, features dispo)
# =====================================================================

def detect_regime_databento(bar: dict) -> RegimeAnalysis:
    """Detecte regime via Databento V4 enriched features (Bot 3).

    V4 manque day_type, open_type, profile_shape, trend_day_probability,
    vix_level, single_print_count (vs DMP). Fallback sur 6 votes :
      1. VWAP slope (vwap_slope_10) — directionnel
      2. ATR expansion (atr_14m_pct vs session avg)
      3. Position in range (extreme = trend mature)
      4. Momentum (momentum_5b)
      5. RVOL (rvol > 1.2 = trend acceleration)
      6. n_single_prints_pct (V4 alias)

    Args:
        bar: dict ligne parquet V4 enriched (~426 colonnes)

    Returns:
        RegimeAnalysis avec source="DATABENTO_V4"
    """
    if not bar:
        return RegimeAnalysis("NEUTRE", "NORMAL", "NORMAL", 0.0, False, 0, 0, 0.0,
                              ["empty_bar"], "DATABENTO_V4")

    trend_votes = 0
    range_votes = 0
    details = []

    # 1. VWAP slope (poids 2)
    vwap_slope = _safe_float(bar, "vwap_slope_10", 0.0)
    vwap_sl_abs = abs(vwap_slope)
    if vwap_sl_abs > 0.001:  # 0.1%
        trend_votes += 2
        details.append(f"VWAP slope: {vwap_slope:+.4f}")
    elif vwap_sl_abs < 0.0002:
        range_votes += 1
        details.append(f"VWAP slope: {vwap_slope:+.4f} (plat)")

    # 2. ATR expansion
    atr_pct = _safe_float(bar, "atr_14m_pct", 0.0)
    atr_zscore = _safe_float(bar, "atr_regime_zscore_60d", 0.0)
    if atr_zscore > 0.5:
        trend_votes += 1
        details.append(f"ATR expansion z={atr_zscore:.2f}")
    elif atr_zscore < -0.5:
        range_votes += 1
        details.append(f"ATR contraction z={atr_zscore:.2f}")

    # 3. Position in range (extreme = trend mature)
    pos = _safe_float(bar, "position_in_range", 0.5)
    if pos > 0.80 or pos < 0.20:
        trend_votes += 1
        details.append(f"Pos extreme: {pos:.2f}")
    elif 0.40 <= pos <= 0.60:
        range_votes += 1
        details.append(f"Pos milieu: {pos:.2f}")

    # 4. Momentum
    mom = _safe_float(bar, "momentum_5b", 0.0)
    mom_abs = abs(mom)
    if mom_abs > 0.002:
        trend_votes += 1
        details.append(f"Momentum 5b: {mom:+.4f}")
    elif mom_abs < 0.0005:
        range_votes += 1
        details.append(f"Momentum 5b: {mom:+.4f} (plat)")

    # 5. RVOL
    rvol = _safe_float(bar, "rvol", 0.0)
    if rvol > 1.2:
        trend_votes += 1
        details.append(f"RVOL: {rvol:.2f}x")
    elif rvol < 0.7:
        range_votes += 1
        details.append(f"RVOL: {rvol:.2f}x (faible)")

    # 6. Single prints pct (V4 alias)
    sp_pct = _safe_float(bar, "n_single_prints_pct", 0.0)
    if sp_pct > 0.10:
        trend_votes += 1
        details.append(f"SinglePrints: {sp_pct:.1%}")
    elif sp_pct < 0.02:
        range_votes += 1
        details.append(f"SinglePrints: {sp_pct:.1%} (faible)")

    # Mode verdict (seuils adaptes a 6 votes max au lieu de 10)
    if trend_votes >= 4:
        mode = "TREND"
    elif range_votes >= 3:
        mode = "RANGE"
    elif trend_votes >= range_votes + 2:
        mode = "TREND"
    elif range_votes >= trend_votes + 2:
        mode = "RANGE"
    else:
        mode = "NORMAL"

    # Bias score
    cvd_dir = _safe_int(bar, "cvd_day_dir", 0)
    bias_score = 0.0
    if vwap_slope > 0.0005: bias_score += 0.3
    elif vwap_slope < -0.0005: bias_score -= 0.3
    if cvd_dir > 0: bias_score += 0.3
    elif cvd_dir < 0: bias_score -= 0.3
    if mom > 0.001: bias_score += 0.2
    elif mom < -0.001: bias_score -= 0.2
    if pos > 0.7: bias_score += 0.2
    elif pos < 0.3: bias_score -= 0.2
    bias_score = max(-1.0, min(1.0, bias_score))

    # Direction
    if mode == "RANGE":
        if pos >= 0.70: direction = "SHORT"
        elif pos <= 0.30: direction = "LONG"
        else: direction = "NEUTRE"
    elif bias_score > 0.3:
        direction = "LONG"
    elif bias_score < -0.3:
        direction = "SHORT"
    else:
        direction = "NEUTRE"

    # Vol regime (proxy via atr_zscore)
    if atr_zscore >= 1.5: vol_regime = "EXTREME"
    elif atr_zscore >= 0.5: vol_regime = "HIGH"
    elif atr_zscore >= -0.5: vol_regime = "NORMAL"
    else: vol_regime = "LOW"

    # Confidence
    total_votes = trend_votes + range_votes
    net = abs(trend_votes - range_votes)
    confidence = min(1.0, net / 6.0) if total_votes > 0 else 0.0

    is_actionable = (
        direction != "NEUTRE"
        and mode != "NORMAL"
        and vol_regime != "EXTREME"
        and confidence >= 0.25
    )

    return RegimeAnalysis(
        direction=direction, mode=mode, vol_regime=vol_regime,
        confidence=round(confidence, 2), is_actionable=is_actionable,
        trend_votes=trend_votes, range_votes=range_votes,
        bias_score=round(bias_score, 2), details=details,
        source="DATABENTO_V4",
    )
