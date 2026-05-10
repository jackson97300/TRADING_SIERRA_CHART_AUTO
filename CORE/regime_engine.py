"""regime_engine.py — Detecteur de regime UNIFIE (source unique de verite).

Source unique de logique regime, consommee par :
  - DASHBOARD/api/builders.py (build_regime_context)
  - CORE/build_dataset_v4_dmp_databento.py (calcul + persist V4)
  - CORE/mia_paper_trader.py (Bot 1 — STEP 0 regime gate)
  - CORE/databento_paper_trader_v2.py (Bot 2 + Bot 3 — STEP 0 regime gate)

Architecture (Jackson 03/05/2026 — anti Pattern 11) :
  V1 = 11 layers cascades = 65% faux rejets (cf feedback_cross_instrument_bonus_not_gate.md)
  V2 = 1 verdict regime calcule UNE FOIS, expose comme 5 features V4, partage par 3 bots.

Workflow trade Jackson :
  1. DIRECTION CLAIRE (regime_engine ici)        ← STEP 0
  2. NIVEAU touch (Bot 3 levels ou Bot 2 setups)
  3. RECONFIRMATION direction + orderflow
  4. TRADE

Reproduction fidele DASHBOARD/api/builders.py:120-362 (build_regime_context) :
  - 10 votes ponderes (IB, day_type, single prints, VWAP slope, sess/ATR,
    open type, profile shape, POC distance, bars in VA, trend day prob)
  - Direction selon mode + bias
  - Override coherence (pas LONG si 3+ bear factors)
  - Volatilite regime EXTREME/HIGH/NORMAL/LOW
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional

# === Kill switch + version (R1+R2 code-reviewer 03/05) ===
# Permet rollback rapide en cas de probleme RTH J+1 sans redeploy code :
#   MIA_REGIME_SKIP_ENABLED=0 nssm restart MIA-DataBento-Paper-V2  (30s)
REGIME_SKIP_ENABLED: bool = os.environ.get("MIA_REGIME_SKIP_ENABLED", "1") == "1"

# Version calibration pour distinguer Bot 1 (dashboard ancienne 2.0) vs
# Bot 2+3 (regime_engine v2 grid search optimal 5.5).
REGIME_CALIB_VERSION: str = "v2_optim_20260503"


@dataclass
class RegimeAnalysis:
    """Sortie unifiee detecteur de regime (5 features cles + details)."""
    mode: str                # "TREND" | "RANGE" | "NORMAL"
    favor: str               # "LONG" | "SHORT" | "NEUTRE"
    confidence: float        # [0.0, 1.0] — derive de votes nets
    trend_votes: int         # 0-12
    range_votes: int         # 0-12
    vol_regime: str          # "EXTREME" | "HIGH" | "NORMAL" | "LOW"
    bias_score: float        # [-1, 1] — proxy bias (BEAR <-> BULL)
    is_actionable: bool      # True si mode != NORMAL + favor != NEUTRE + vol != EXTREME
    details: list = field(default_factory=list)
    bear_factors: int = 0    # nombre de facteurs bias bear (pour audit)
    bull_factors: int = 0    # nombre de facteurs bias bull (pour audit)


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

def _compute_bias_proxy(bar: dict) -> tuple[float, str, int, int]:
    """Calcul bias proxy (vs CORE/bias_calculator.py compute_bias).

    Logique simplifiee (60% du compute_bias V1) :
      - VWAP slope (pente directionnelle)
      - delta_day_dir / cvd_day_dir (orderflow direction)
      - range_pos (haut = bear bias, bas = bull bias)
      - vwap_d_side (above/below VWAP)
      - delta_divergence (binaire)

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

    pos = _get_field(bar, "range_pos", 50.0)
    if pos > 70:
        score -= 0.20
        bear_factors += 1
    elif pos < 30:
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
    if score > 0.30:
        label = "BULLISH"
    elif score < -0.30:
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
        bar: dict ligne (DMP JSONL ou parquet V4 enriched).
             Doit contenir les 28 features regime DMP requises.

    Returns:
        RegimeAnalysis avec mode/favor/confidence/votes/vol_regime/bias.

    Reproduction fidele DASHBOARD/api/builders.py:170-324 build_regime_context.
    """
    if not bar:
        return RegimeAnalysis(
            mode="NORMAL", favor="NEUTRE", confidence=0.0,
            trend_votes=0, range_votes=0, vol_regime="NORMAL",
            bias_score=0.0, is_actionable=False,
            details=["empty_bar"],
        )

    trend_votes = 0
    range_votes = 0
    details = []

    # ============================================================
    # SEUILS CALIBRES EMPIRIQUEMENT (grid search 03/05/2026 sur 14j NQ)
    # ============================================================
    # Calibration optimale sur quartiles distribution V4 NQ 17/04 -> 30/04 :
    #   vol_extreme=5.5 (was 2.0, capture vrais p90+)
    #   mode_strong=3 (was 5, plus permissif TREND/RANGE)
    #   conf_actionable=0.10 (was 0.20)
    #   vwap_dir=3.5 (was 5.0)
    #   sp_strong=100 (was 10), sp_weak=30 (was 3)
    #   poc_distant=15 (was 30), poc_close=3 (was 5)
    #   va_confine=30 (was 60), va_hors=10 (was 30)
    #   tdp_strong=0.30 (was 0.65), tdp_weak=0.10 (was 0.30)
    # Resultat : actionable rate 3% -> 20.2% (target 15-25%).
    # Cross-validation PnL Bot V1 : 4/5 jours alignes (22/04 BULL / 28/04 SHORT-dom /
    # 23/04 choppy OK ; 30/04 regime dit BULL mais reversal).

    # 1. IB Breakout (poids 2 si breakout, 1 si IB intacte)
    ib_up = _get_int_field(bar, "ib_broken_up", 0)
    ib_dn = _get_int_field(bar, "ib_broken_down", 0)
    ib_formed_bool = _get_int_field(bar, "ib_formed_bool", -1)
    # Si ib_formed_bool absent (DMP source), fallback sur ib_range_ticks > 0
    if ib_formed_bool == -1:
        ib_range = _get_field(bar, "ib_range_ticks", 0.0)
        ib_formed_bool = 1 if ib_range > 0 else 0
    if ib_up or ib_dn:
        trend_votes += 2
        details.append("IB cassee " + ("UP" if ib_up else "DOWN"))
    elif ib_formed_bool:
        range_votes += 1
        details.append("IB intacte")

    # 2. Day Type Market Profile (Steidlmayer 0=NonTrend 1=Normal 2=NormVar 3=Neutral 4=Trend)
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
    # day_type == 0 (NonTrend, 7%) : pas de vote

    # 3. Single Prints — empreinte de conviction (calibre p25=47, p75=170)
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
        details.append(f"VWAP slope: {vwap_slope_10:+.1f}")
    elif vwap_sl < 0.5:
        range_votes += 1
        details.append(f"VWAP slope: {vwap_slope_10:+.1f} (plat)")

    # 5. Sess/ATR (vol ratio) — calibre p50=2.27, p75=4.04
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
        details.append("Open Drive")
    elif open_type in (3, 4):
        trend_votes += 1
        details.append("Open Test Drive")
    elif open_type in (5, 6):
        range_votes += 1
        details.append("Open Rejection Reverse")

    # 7. Profile Shape (1=P, 2=b directionnel ; 0=D, 3=DoubleDist range)
    profile_shape = _get_int_field(bar, "profile_shape", -1)
    if profile_shape in (1, 2):
        trend_votes += 1
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

    # 9. Bars in VA (% temps prix dans Value Area) — calibre p75=22, p90=53
    bars_va = _get_field(bar, "bars_in_va", 0.0)
    if bars_va > 30:
        range_votes += 1
        details.append(f"Bars in VA: {bars_va:.0f}% (confine)")
    elif bars_va < 10:
        trend_votes += 1
        details.append(f"Bars in VA: {bars_va:.0f}% (hors VA)")

    # 10. Trend Day Probability (calibre p75=0.35, p90=0.35)
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
    range_pos = _get_field(bar, "range_pos", 50.0)

    # ===== Direction (favor) =====
    if mode == "RANGE":
        if range_pos >= 70:
            favor = "SHORT"
        elif range_pos <= 30:
            favor = "LONG"
        else:
            favor = "NEUTRE"
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

    # ===== Volatility regime — Fix 11/05/2026 (audit feature-engineer) =====
    # AVANT : utilisait sess_range_atr (ratio sess/atr) qui est NaN 97.5% ES
    #   et ABSENT MGC -> fallback 0.0 -> vol_regime="LOW" constant.
    #   ES 97.7% LOW, MGC 100% LOW -> feature inutilisable.
    # APRES : utilise atr_regime_zscore_60d (z-score normalise rolling 60d).
    #   Cross-instrument (meme echelle ES/NQ/MGC).
    #   ES/MGC ~52% non-NaN, distribution attendue : LOW 25%, NORMAL 60%,
    #   HIGH 12%, EXTREME 3%. Seuils calibres sur quantiles empiriques
    #   ES q95=1.94, MGC q95=2.22.
    # Fallback : si z-score NaN (premiers 60j rolling), retour "NORMAL"
    #   (neutralite plutot que LOW biaise).
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

    # ===== Confidence (votes nets / total max possible 12) =====
    net = abs(trend_votes - range_votes)
    confidence = min(1.0, net / 12.0)

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
    )


def compute_regime_dict(bar: dict) -> dict:
    """Wrapper retournant dict (pour pipeline V4 builder)."""
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
