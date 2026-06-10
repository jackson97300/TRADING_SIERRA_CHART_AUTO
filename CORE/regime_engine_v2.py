"""regime_engine_v2.py — FORK regime_engine.py 2026-05-27 (Bot 4 V2 ONLY).

**ATTENTION** : ce module est un FORK de `CORE/regime_engine.py`. Il est UTILISE
UNIQUEMENT par `NEW_BOT_2_MIA_TRADER/src/layers/l1_regime.py` (Bot 4 V2).

**Bot 1 (mia_paper_trader.py), Bot 2 (databento_paper_trader_v2.py BN V4 + Bot 3),
et l'enricher (CORE/enricher_chain.py) continuent d'utiliser `regime_engine.py`
ORIGINAL inchange.** Cette separation evite de casser leur comportement actuel
(Bot 1 utilise `regime_actionable` comme HARD GATE qui depend du bug `/12.0`).

Historique des fixes (vs regime_engine.py original) :
  - 2026-05-27 (fork v3) : `confidence = net / max(trend+range, 1)` au lieu de
    `/ 12.0`. Le denominateur 12.0 etait MAL CALIBRE (max conf observe = 0.25
    sur 21k bars NQ+ES = ~25% du max theorique).
    -> Audit code-reviewer 27/05 verdict : "Pattern 11 V1 textbook : 2 patches
    successifs (NORMALIZE_MAX 0.25 -> 0.35) sur le sparadrap au lieu du bug
    racine `/12.0`".
    Fix correct : formule ponderee `net / votes_exprimes`. Si 5 trend votes
    contre 2 range votes : net=3, total=7 -> conf=0.43 (vs 0.25 ancienne).
  - 2026-05-27 (fork v3) : signaux insuffisants flagges via flag dans details.
    Si `(trend_votes + range_votes) < 4`, ajout "INSUFFICIENT_FEATURES" dans
    details list. Caller (l1_regime.py) peut emit log BOT4_REGIME_INSUFFICIENT_FEATURES.

Source unique de logique regime UNIFIEE pour Bot 4 :
  - NEW_BOT_2_MIA_TRADER/src/layers/l1_regime.py (compute_l1_regime)

Workflow trade Jackson preserve :
  1. DIRECTION CLAIRE (regime_engine_v2 ici)     <- STEP 0
  2. NIVEAU touch (Bot 4 layers L4/L5)
  3. RECONFIRMATION direction + orderflow
  4. TRADE
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional

# === Kill switch + version v2 (separate des v1 pour ne pas collisionner) ===
# Permet rollback rapide en cas de probleme via env var dedie :
#   MIA_REGIME_V2_SKIP_ENABLED=0 nssm restart MIA-Bot-4-Paper  (30s)
# Note : nom different de REGIME_SKIP_ENABLED (regime_engine.py) pour isoler
# Bot 4 (v2) de Bot 1/2/3 (v1).
REGIME_V2_SKIP_ENABLED: bool = os.environ.get("MIA_REGIME_V2_SKIP_ENABLED", "1") == "1"

# Version calibration v3 = fork 2026-05-27 avec fix denominateur ponderation
# par votes exprimes au lieu du max theorique 12.
REGIME_V2_CALIB_VERSION: str = "v3_fix_confidence_20260527"

# Seuil pour flag "votes insuffisants" (typique hors-RTH features MP NaN)
REGIME_V2_MIN_VOTES_THRESHOLD: int = 4


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
    # FIX BUG #3 (03/06) : votes directionnels TREND (IB UP/DN, Open Type, VWAP slope, Profile).
    # Utilise pour inferer favor en mode TREND si bias_proxy NEUTRE.
    # Champ typee pour audit J+1 (vs string dans details).
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

    # FIX BUG #2 (03/06) : range_pos est echelle [0,1] en live_enriched
    # (enricher_chain.py:795 : payload["range_pos"] = (c-l) / range).
    # AVANT : seuils 30/70 sur echelle [0,100] -> JAMAIS satisfait avec [0,1]
    # -> range_pos contribuait TOUJOURS 0 au bias_score (silent mort 18/05+).
    # APRES : seuils 0.30/0.70 adaptes echelle [0,1]. Default 0.5 (centre).
    # Cf audit empirique 02/06 : 99.7% favor=NEUTRE en partie cause par ce bug.
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
    # FIX BUG #1 (03/06) : seuils 0.30/0.30 trop conservateurs.
    # Audit empirique 02/06 NQ RTH : 99.7% favor=NEUTRE alors que mode=TREND 71.6%.
    # Cause : score bias_proxy max theorique = 1.0 (5 facteurs a 0.15-0.25).
    # Pour franchir +/-0.30 il faut 2-3 facteurs orderflow alignes simultanement.
    # En realite la plupart des bars ont 0-1 facteur aligne (range_pos cassait
    # silencieusement Bug #2 + delta/cvd souvent neutres).
    # APRES : seuils +/-0.20. 1-2 facteurs alignes = label BULL/BEAR.
    # Risque : faux positifs sur orderflow ambigu. Compensation : floor confidence
    # L1 + modulator (cf l1_regime.py PATCH A).
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
        bar: dict ligne (DMP JSONL ou parquet V4 enriched).
             Doit contenir les 28 features regime DMP requises.

    Returns:
        RegimeAnalysis avec mode/favor/confidence/votes/vol_regime/bias.

    Reproduction fidele DASHBOARD/api/builders.py:170-324 build_regime_context.
    """
    # KILL SWITCH (fix code-reviewer 27/05) : si env var MIA_REGIME_V2_SKIP_ENABLED=0,
    # retourner output neutre force. Permet rollback rapide sans redeploy code.
    # Bot 4 fallback alors sur lecture bar.get(regime_*) v1 (cf l1_regime.py heuristique).
    if not REGIME_V2_SKIP_ENABLED:
        return RegimeAnalysis(
            mode="NORMAL", favor="NEUTRE", confidence=0.0,
            trend_votes=0, range_votes=0, vol_regime="NORMAL",
            bias_score=0.0, is_actionable=False,
            details=["KILL_SWITCH_REGIME_V2_DISABLED"],
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
    # FIX BUG #3 (03/06) : tracker direction des votes trend (LONG bias vs SHORT bias).
    # AVANT : mode TREND ne convertit en favor qu'via bias_proxy (NEUTRE 99.7% bars).
    # APRES : si bias_proxy=NEUTRE en mode TREND, fallback sur votes directionnels.
    # IB cassee UP=+1 LONG, ib_dn=+1 SHORT, open_type=1(OD up)=+1 LONG, open_type=2=+1 SHORT.
    # Audit 02/06 : 71.6% mode TREND mais 0% favor LONG/SHORT (TREND_NEUTRE saturation).
    trend_up_votes = 0
    trend_down_votes = 0
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
        # FIX BUG #3 : tracker direction IB pour fallback favor en mode TREND
        if ib_up:
            trend_up_votes += 2
        else:
            trend_down_votes += 2
        details.append("IB cassee " + ("UP" if ib_up else "DOWN"))
    elif ib_formed_bool:
        range_votes += 1
        details.append("IB intacte")

    # 2. Day Type Market Profile (Steidlmayer 0=NonTrend 1=Normal 2=NormVar 3=Neutral 4=Trend)
    # FIX Phase 2.1bis (06/06/2026) : guard day_type INVALID (null/NaN/negatif)
    # Sierra DMP 3.7.16+ : day_type = DMP_INVALID hors RTH cash session.
    # Audit 15j NQ confirme 76% bars Asia/London pre-fix avaient day_type=2
    # MENTEUSE -> regime_engine biaisait TREND systematiquement Asia/London.
    # Post-fix : day_type null/NaN -> skip vote (pas de pollution).
    day_type_raw = bar.get("day_type")
    is_day_type_valid = (
        day_type_raw is not None
        and not (isinstance(day_type_raw, float) and (day_type_raw != day_type_raw))  # NaN check
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
        # day_type == 0 (NonTrend, 7%) : pas de vote
    else:
        details.append("Day Type: INVALID (Asia/London hors RTH) - skip vote")

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
        # FIX BUG #3 : direction VWAP slope (slope positif = LONG, negatif = SHORT)
        if vwap_slope_10 > 0:
            trend_up_votes += 1
        else:
            trend_down_votes += 1
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
        # FIX BUG #3 : 1=OD up = LONG bias, 2=OD down = SHORT bias
        if open_type == 1:
            trend_up_votes += 1
        else:
            trend_down_votes += 1
        details.append("Open Drive")
    elif open_type in (3, 4):
        trend_votes += 1
        # FIX BUG #3 : 3=OTD up = LONG bias, 4=OTD down = SHORT bias
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
        # FIX BUG #3 : P-shape (1) = base etroite en bas + expansion haut = LONG breakout
        #              b-shape (2) = base etroite en haut + expansion bas = SHORT breakdown
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
    # FIX BUG #2 (03/06) — RESIDUAL : default 0.5 (centre) au lieu de 50.0.
    # Cf code-reviewer 03/06 : avec default 50.0, range_pos absent retournait
    # SHORT systematique en mode RANGE (50.0 >= 0.70). Coherent avec ligne 146.
    range_pos = _get_field(bar, "range_pos", 0.5)

    # ===== Direction (favor) =====
    # FIX BUG #2 (03/06) : range_pos echelle [0,1] (cf bias_proxy + enricher).
    if mode == "RANGE":
        if range_pos >= 0.70:
            favor = "SHORT"
        elif range_pos <= 0.30:
            favor = "LONG"
        else:
            favor = "NEUTRE"
    elif mode == "TREND":
        # FIX BUG #3 (03/06) : mode TREND infere favor depuis votes directionnels.
        # AVANT : depend de bias_proxy -> 99.7% NEUTRE empirique 02/06.
        # APRES : trend_up_votes vs trend_down_votes (IB cassee + open_type + vwap_slope
        # + profile_shape directionnels).
        # ITERATION 03/06 (post-backtest empirique) : ANTI FAUX POSITIFS.
        # Backtest 02/06 a montre 4 SHORTs faux positifs (shortes au low +45 a +69 pts contre)
        # tous trigger par fallback BIAS_BEAR_tie (votes directionnels=0 + bias proxy bearish).
        # Cause : live_enriched a features manquantes (profile_shape, single_print_count, etc)
        # -> moteur 10 votes tourne sur ~5 votes effectifs -> tied a 0 frequent.
        # SOLUTION : si AUCUN vote directionnel emis (tied a 0), retourner NEUTRE
        # plutot que fallback bias_proxy. Sain : mieux 0 trade que faux positifs.
        # Le fallback bias n'est utilise QUE si tied mais >0 (rare en pratique).
        if trend_up_votes > trend_down_votes:
            favor = "LONG"
            details.append(f"TREND_favor_VOTES_UP({trend_up_votes}>{trend_down_votes})")
        elif trend_down_votes > trend_up_votes:
            favor = "SHORT"
            details.append(f"TREND_favor_VOTES_DN({trend_down_votes}>{trend_up_votes})")
        elif trend_up_votes == 0 and trend_down_votes == 0:
            # ITERATION 03/06 : aucun vote directionnel -> NEUTRE (anti faux positif).
            favor = "NEUTRE"
            details.append("TREND_favor_NEUTRE_no_directional_votes")
        elif bias_label == "BULLISH":
            # Tied mais >0 votes (rare) + bias bullish -> LONG modere
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

    # ===== Confidence FIX 2026-05-27 (audit code-reviewer) =====
    # AVANT (regime_engine.py original) : `net / 12.0` (denominateur max theorique).
    # PROBLEME : sur 21k bars NQ+ES, max conf observe = 0.25 (~25% du max). Le
    # /12.0 plafonne mathematiquement et a force 2 patches successifs cote
    # consumer (l1_regime.py NORMALIZE_MAX 0.25 -> 0.35 = pattern 11 V1).
    # APRES : ponderation par votes EXPRIMES. Si 5 trend / 2 range votes : net=3,
    # total=7 -> conf=3/7=0.43 (vs 3/12=0.25). Discrimination preservee, pas de
    # plafonnement artificiel. Le caller peut directement utiliser cette
    # confidence sans NORMALIZE_MAX. Anti-pattern 11 V1.
    net = abs(trend_votes - range_votes)
    total_votes = trend_votes + range_votes
    confidence = min(1.0, net / max(total_votes, 1))

    # Flag votes insuffisants (hors-RTH features Market Profile typiquement NaN
    # -> votes < 4). Caller peut emit log BOT4_REGIME_INSUFFICIENT_FEATURES.
    if total_votes < REGIME_V2_MIN_VOTES_THRESHOLD:
        details.append(f"INSUFFICIENT_FEATURES (votes={total_votes} < {REGIME_V2_MIN_VOTES_THRESHOLD})")

    # ===== Is actionable (calibre conf_actionable=0.10 inchange) =====
    # Note : seuil conf >= 0.10 garde son sens avec la nouvelle formule (plus
    # facile a satisfaire car conf max ~0.5-0.8 au lieu de 0.25). Calibration
    # finale `is_actionable` rate visee : 25-35% (vs 3% actuel).
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
        # FIX BUG #3 (03/06) : expose votes directionnels au consumer pour audit.
        trend_up_votes=trend_up_votes,
        trend_down_votes=trend_down_votes,
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
