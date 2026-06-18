"""
bias_calculator.py — Module partage pour calcul du biais directionnel MIA.

Source unique de verite pour :
- DASHBOARD/api/builders.py (affichage biais Mike/humain)
- CORE/mia_paper_trader.py (gate directionnel check_entry)
- Backtest et tests

Logique extraite de DASHBOARD/api/builders.py (lignes 130-335 environ, build_regime).
Reproduction fidele de la logique V1 bias :
  - Position 1D range (30%)
  - OrderFlow (delta_day + delta_pct) (25%)
  - VWAP position (20%)
  - VWAP slope (15%)
  - CVD direction (10%)
  - Divergence quality score (bonus -0.35 a +0.35 hors trending)

Sortie : BiasResult avec :
  - score_bull, score_bear separes (permet bias_clarity, essentiel pour bot)
  - score_signed (-1 a +1) pour backward compat dashboard
  - direction : "BULL" / "BEAR" / "NEUTRE"
  - bias_clarity = |score_bull - score_bear|
  - reasons separees par side (audit trade)

Auteur : MIA Trading System
Date : 2026-04-24 (extraction logique existante + separation bull/bear)
Version : 1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ==============================================================================
# CONSTANTES — seuils documentes depuis builders.py
# ==============================================================================

# Position 1D range
POS_EXTREME_HIGH = 80  # >= 80 % du range 1D = proche du top
POS_EXTREME_LOW = 20  # <= 20 % du range 1D = proche du bottom

# Score points (reprise fidele builders.py)
PTS_POS_BREAKOUT = 0.10  # breakout detecte (new_high + delta_day > 0)
PTS_POS_EXTREME = 0.30  # position extreme sans breakout

PTS_OF_STRONG = 0.25  # delta_day fort + delta_pct concordant
PTS_OF_WEAK = 0.10  # delta_day directionnel mais barre neutre

PTS_VWAP_POSITION = 0.20  # prix > VWAP +15t ou < VWAP -15t
VWAP_POSITION_THRESHOLD_TICKS = 15.0

PTS_VWAP_SLOPE = 0.15  # slope > +2 ou < -2
VWAP_SLOPE_THRESHOLD = 2.0

# ──────────────────────────────────────────────────────────────────────────────
# 🆕 Plan A1 (08/06/2026) — Refactor BLOC 5 CVD apres incident NQ LONG drift
# Bot 1 SIM1 -$2010 le 08/06 sur 7 trades 100% LONG. Cas casseur identifie sur
# snapshot NQ #3 : bias=BULLISH bias_score=0.75 malgre CVD DISTRIBUTION (-17k
# cumule session) car PTS_CVD=0.10 vs PTS_OF_STRONG=0.25 → delta intra-bar
# ecrasait silencieusement le signal de distribution cumulative.
#
# Plan A1 :
#   1. PTS_CVD 0.10 → 0.25 (symetrie avec delta_day_dir, anti silent override)
#   2. delta_cvd_divergence_flag (qualite signal degradee si conflit)
#   3. vwap_m_side veto vers NEUTRAL si signal CONTRE l'ancrage long-terme
#
# Justification PAS empirique (pas de calibration N<30, cf. data_mining_trap) :
# logique pure de symetrie orderflow (delta intra-bar = cvd cumulative dans
# le meme axe direction). Cf. .claude/rules/critical-tasks-review.md.
# ──────────────────────────────────────────────────────────────────────────────
PTS_CVD = 0.25  # 🆕 Plan A1 (08/06) — symetrie avec PTS_OF_STRONG (etait 0.10)

# Divergence quality bonus
DIV_BONUS_MAX = 0.35  # cap bonus div sur le score final

# Seuils direction
SCORE_BULL_THRESHOLD = 0.25  # score > seuil = BULL
SCORE_BEAR_THRESHOLD = -0.25  # score < seuil = BEAR

# Trending detection (pour ne pas fader un breakout avec div)
TRENDING_SLOPE = 5.0
TRENDING_DELTA_DIR = 1

# Divergence quality threshold pour etre exploitee
DIV_QUALITY_THRESHOLD = 5.0


# ==============================================================================
# DATACLASS RESULTAT
# ==============================================================================


@dataclass
class BiasResult:
    """Resultat du calcul de biais directionnel.

    Attributs critiques :
    - score_bull / score_bear : scores separes [0, 1+], utilises par le bot
      pour le gate directionnel et la clarity.
    - bias_clarity : ecart absolu entre bull et bear, mesure de conviction.
    - score_signed : score net (bull - bear), borne [-1, +1] pour backward
      compat avec l'affichage dashboard actuel.
    - direction : "BULL" / "BEAR" / "NEUTRE" (humain-lisible).
    - reasons_bull / reasons_bear : raisons detaillees de chaque side (audit
      decision bot, debug en cas de rejection).
    """

    score_bull: float = 0.0
    score_bear: float = 0.0
    score_signed: float = 0.0  # = min(1, max(-1, bull - bear))
    bias_clarity: float = 0.0
    direction: str = "NEUTRE"  # "BULL" / "BEAR" / "NEUTRE"
    reasons_bull: List[str] = field(default_factory=list)
    reasons_bear: List[str] = field(default_factory=list)
    reasons_neutral: List[str] = field(default_factory=list)
    div_quality: float = 0.0
    div_grade: str = "NONE"  # "NONE" / "FAIBLE" / "MODEREE" / "FORTE" / "EXTREME"
    div_active: bool = False  # True si delta_divergence = 1 sur la barre
    div_factors: List[str] = field(default_factory=list)  # detail contributions div quality
    is_trending: bool = False
    # 🆕 Plan A1 (08/06/2026) — flags qualite signal post-incident NQ LONG drift
    delta_cvd_divergence: bool = False  # True si delta_day_dir != cvd_day_dir (signal degrade)
    vwap_m_veto_applied: bool = False  # True si bias finale poussee a NEUTRE par veto vwap_m_side

    def to_dashboard_dict(self) -> Dict[str, Any]:
        """Format SUBSET du dashboard build_regime_context.

        **ATTENTION** : ce dict ne remplace PAS `build_regime_context()` qui
        emet ~29 cles dont VIX, momentum, atr_ratio, mode marche, etc.
        Il emet seulement les cles liees au **calcul du biais** (9 cles) :
          - bias, bias_label, bias_score, bias_confidence, bias_factors
          - div_active, div_grade, div_quality, div_factors

        Si tu utilises ce dict pour construire un `regime` complet, tu DOIS
        completer avec les autres sections (VIX, momentum, mode marche, etc.)
        separement. Sinon le front dashboard aura des champs manquants.

        Usage type dans builders.py :
            regime = build_regime_context_skeleton(bar)  # VIX, VWAP, momentum...
            regime.update(compute_bias(bar).to_dashboard_dict())  # 9 cles biais+div
        """
        if self.direction == "BULL":
            bias_label = "HAUSSIER"
            bias = "BULLISH"
        elif self.direction == "BEAR":
            bias_label = "BAISSIER"
            bias = "BEARISH"
        else:
            bias_label = "NEUTRE"
            bias = "NEUTRAL"

        # Factors ordonnes : bull puis bear puis neutral
        factors = []
        for r in self.reasons_bull:
            factors.append({"icon": "bull", "text": r})
        for r in self.reasons_bear:
            factors.append({"icon": "bear", "text": r})
        for r in self.reasons_neutral:
            factors.append({"icon": "neutral", "text": r})

        return {
            "bias": bias,
            "bias_label": bias_label,
            "bias_score": round(self.score_signed, 3),
            "bias_confidence": round(_calc_confidence(self.score_signed, factors), 2),
            "bias_factors": factors,
            # Divergence details (consomme par dashboard.js L975, L1164-1175, L1551-1552)
            "div_active": self.div_active,
            "div_grade": self.div_grade,
            "div_quality": round(self.div_quality, 2),
            "div_factors": list(self.div_factors),
            # 🆕 Plan A1 (08/06) — observabilite signal degrade / veto long-terme
            "delta_cvd_divergence": self.delta_cvd_divergence,
            "vwap_m_veto_applied": self.vwap_m_veto_applied,
        }


# ==============================================================================
# HELPER : confiance du biais (source unique — partage bot + dashboard)
# ==============================================================================


def calc_confidence(score: float, factors: List[Dict[str, Any]]) -> float:
    """Confiance = consensus facteurs + amplitude score.

    Source unique de verite — utilisee par :
    - BiasResult.to_dashboard_dict() (via _calc_confidence alias)
    - DASHBOARD/api/builders.py:build_regime_context (import direct)

    Malus si peu de facteurs actifs (< 3).

    Args:
        score: Score signed final (score_bull - score_bear borne [-1, +1]).
        factors: Liste de dicts {"icon": "bull"|"bear"|"neutral", "text": str}.

    Returns:
        Confiance [0.0, 1.0].
    """
    if not factors:
        return 0.0
    bulls = sum(1 for f in factors if f.get("icon") == "bull")
    bears = sum(1 for f in factors if f.get("icon") == "bear")
    active = bulls + bears
    if active == 0:
        return 0.0
    consensus = max(bulls, bears) / active
    amplitude = min(abs(score) * 2, 1.0)
    confidence = consensus * 0.6 + amplitude * 0.4
    # Malus si trop peu de facteurs — 1 facteur seul ne vaut pas 84%
    if active < 3:
        confidence *= active / 3
    return min(confidence, 1.0)


# Alias rétrocompatibilité (anciens usages internes)
_calc_confidence = calc_confidence


# ==============================================================================
# HELPERS
# ==============================================================================


def _get(bar: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Accesseur sur dict bar avec fallback robuste (None, NaN, str, missing)."""
    v = bar.get(key, default)
    if v is None:
        return default
    try:
        f = float(v)
        # NaN check
        if f != f:
            return default
        return f
    except (TypeError, ValueError):
        return default


def _get_int(bar: Dict[str, Any], key: str, default: int = 0) -> int:
    """Accesseur int avec fallback robuste."""
    v = bar.get(key, default)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ==============================================================================
# CALCUL BIAIS
# ==============================================================================


def compute_bias(bar: Dict[str, Any]) -> BiasResult:
    """Calcule le biais directionnel a partir d'une barre JSONL DMP.

    Reproduction fidele de la logique dashboard builders.py:130-335 avec
    decomposition en score_bull / score_bear separes (pour gate bot).

    Args:
        bar: Dict (typiquement une ligne JSONL DMP) avec au moins les cles :
            range_pos, new_swing_high, new_swing_low, delta_day,
            delta_pct, delta_day_dir,
            dist_vwap_d, vwap_slope_10,
            vwap_d_side, vwap_w_side, vwap_m_side,
            cvd_day_dir,
            delta_divergence, sess_range_atr, vix_level, rvol.
        Toute cle manquante = 0.0 (pas de crash).

    Returns:
        BiasResult avec scores separes, raisons, et format compat dashboard.
    """
    result = BiasResult()

    # ----------------------------------------------------------------------
    # BLOC 1 — Position dans range 1D (30%)
    # ----------------------------------------------------------------------
    pos = _get(bar, "range_pos", 50.0)
    new_high = _get_int(bar, "new_swing_high", 0)
    new_low = _get_int(bar, "new_swing_low", 0)
    delta_day = _get(bar, "delta_day", 0.0)

    if pos >= POS_EXTREME_HIGH:
        # Breakout detection : nouveau high + delta positif = expansion
        if new_high and delta_day > 0:
            result.score_bull += PTS_POS_BREAKOUT
            result.reasons_bull.append(f"Position 1D: {pos:.0f}% (BREAKOUT UP)")
        else:
            # Sinon = TOP, bearish
            result.score_bear += PTS_POS_EXTREME
            result.reasons_bear.append(f"Position 1D: {pos:.0f}% (TOP)")
    elif pos <= POS_EXTREME_LOW:
        if new_low and delta_day < 0:
            # Breakdown expansion
            result.score_bear += PTS_POS_BREAKOUT
            result.reasons_bear.append(f"Position 1D: {pos:.0f}% (BREAKDOWN)")
        else:
            # Bottom, bullish rebond potentiel
            result.score_bull += PTS_POS_EXTREME
            result.reasons_bull.append(f"Position 1D: {pos:.0f}% (BOTTOM)")
    else:
        result.reasons_neutral.append(f"Position 1D: {pos:.0f}% (MIDDLE)")

    # ----------------------------------------------------------------------
    # BLOC 2 — OrderFlow (delta_day + delta_pct) (25%)
    # ----------------------------------------------------------------------
    delta_pct = _get(bar, "delta_pct", 0.0)
    delta_day_dir = _get_int(bar, "delta_day_dir", 0)

    if delta_day_dir > 0 and delta_pct > 0.05:
        result.score_bull += PTS_OF_STRONG
        result.reasons_bull.append(
            f"OrderFlow: jour ACHETEUR + barre {delta_pct:+.1%}"
        )
    elif delta_day_dir < 0 and delta_pct < -0.05:
        result.score_bear += PTS_OF_STRONG
        result.reasons_bear.append(
            f"OrderFlow: jour VENDEUR + barre {delta_pct:+.1%}"
        )
    elif delta_day_dir > 0:
        result.score_bull += PTS_OF_WEAK
        result.reasons_bull.append(
            f"OrderFlow: jour ACHETEUR (barre neutre {delta_pct:+.1%})"
        )
    elif delta_day_dir < 0:
        result.score_bear += PTS_OF_WEAK
        result.reasons_bear.append(
            f"OrderFlow: jour VENDEUR (barre neutre {delta_pct:+.1%})"
        )
    else:
        result.reasons_neutral.append(f"OrderFlow: neutre ({delta_pct:+.1%})")

    # ----------------------------------------------------------------------
    # BLOC 3 — VWAP position (20%)
    # dist_vwap_d convention DMP :
    #   positif = VWAP AU-DESSUS du prix → prix SOUS VWAP → BEAR
    #   negatif = VWAP EN DESSOUS du prix → prix AU-DESSUS → BULL
    # ----------------------------------------------------------------------
    dist_vwap = _get(bar, "dist_vwap_d", 0.0)

    if dist_vwap < -VWAP_POSITION_THRESHOLD_TICKS:
        result.score_bull += PTS_VWAP_POSITION
        result.reasons_bull.append(f"VWAP: {dist_vwap:.1f}t (PRIX AU-DESSUS)")
    elif dist_vwap > VWAP_POSITION_THRESHOLD_TICKS:
        result.score_bear += PTS_VWAP_POSITION
        result.reasons_bear.append(f"VWAP: +{dist_vwap:.1f}t (PRIX EN-DESSOUS)")
    else:
        result.reasons_neutral.append(f"VWAP: {dist_vwap:+.1f}t (PROCHE)")

    # ----------------------------------------------------------------------
    # BLOC 4 — VWAP slope 10 barres (15%)
    # ----------------------------------------------------------------------
    vwap_slope_10 = _get(bar, "vwap_slope_10", 0.0)

    if vwap_slope_10 > VWAP_SLOPE_THRESHOLD:
        result.score_bull += PTS_VWAP_SLOPE
        result.reasons_bull.append(f"VWAP Slope: {vwap_slope_10:+.1f} (HAUSSIER)")
    elif vwap_slope_10 < -VWAP_SLOPE_THRESHOLD:
        result.score_bear += PTS_VWAP_SLOPE
        result.reasons_bear.append(f"VWAP Slope: {vwap_slope_10:+.1f} (BAISSIER)")
    else:
        result.reasons_neutral.append(f"VWAP Slope: {vwap_slope_10:+.1f} (PLAT)")

    # ----------------------------------------------------------------------
    # BLOC 5 — CVD direction (25%) — 🆕 Plan A1 (08/06/2026)
    #
    # Refactor post-incident NQ LONG drift (-$2010 sur 7 trades 100% LONG) :
    #   - PTS_CVD remontee de 0.10 a 0.25 (symetrie avec PTS_OF_STRONG delta).
    #   - Detection conflit delta vs cvd → flag `delta_cvd_divergence` (qualite
    #     signal degradee, retournement potentiel en orderflow analysis classique).
    #
    # Compat absence cvd : si cvd_day_dir absent (bar Databento live_enriched), le
    # helper _get_int retourne default 0 → aucun signal ajoute, pas de crash.
    # ----------------------------------------------------------------------
    cvd_dir = _get_int(bar, "cvd_day_dir", 0)

    if cvd_dir == 1:
        result.score_bull += PTS_CVD
        result.reasons_bull.append("CVD: ACCUMULATION")
    elif cvd_dir == -1:
        result.score_bear += PTS_CVD
        result.reasons_bear.append("CVD: DISTRIBUTION")

    # 🆕 Plan A1 — Detection divergence delta vs cvd (signal de qualite degradee)
    # ⚠️ NOTE INCIDENT #73 (18/06/2026 mentor mode Jackson) :
    #   Commentaire historique FAUX : delta_day_dir N'EST PAS intra-bar.
    #   Empirique 18/06 : delta_bar == cvd_bar_delta (MEME metrique source).
    #   delta_day (sg9) et cvd_day (sg18) sont 2 cumuls C++ passthrough avec
    #   baselines de reset cassees (sg18 jamais reset, sg9 reset partiel ailleurs).
    #   APRES override cvd_session_override.py (fix #73) :
    #     delta_day == cvd_day == cumul session-ET-based depuis delta_bar
    #     -> delta_day_dir == cvd_day_dir TOUJOURS
    #     -> divergence IMPOSSIBLE, ce code est DORMANT.
    #   Conserve pour future re-activation si sources distinctes restorees
    #   (ex: delta_bar par-bar vs cvd cumul session). Pour l'instant : no-op.
    if delta_day_dir != 0 and cvd_dir != 0 and delta_day_dir != cvd_dir:
        result.delta_cvd_divergence = True
        result.reasons_neutral.append(
            f"DELTA/CVD DIVERGENCE: delta_dir={delta_day_dir:+d} vs cvd_dir={cvd_dir:+d} "
            f"(signal qualite degradee)"
        )

    # ----------------------------------------------------------------------
    # BLOC 6 — Divergence quality (bonus hors trending)
    # ----------------------------------------------------------------------
    delta_div = _get_int(bar, "delta_divergence", 0)
    div_quality = 0.0
    result.div_active = bool(delta_div)

    if delta_div:
        # 1. VWAP stretch (facteur le plus important)
        vwap_stretch = abs(dist_vwap)
        if vwap_stretch > 200:
            div_quality += 3.0
            result.div_factors.append(f"VWAP stretch extreme ({vwap_stretch:.0f}t)")
        elif vwap_stretch > 80:
            div_quality += 2.0
            result.div_factors.append(f"VWAP stretch fort ({vwap_stretch:.0f}t)")
        elif vwap_stretch > 30:
            div_quality += 1.0
            result.div_factors.append(f"VWAP stretch modere ({vwap_stretch:.0f}t)")

        # 2. Range position extreme
        if pos >= 90 or pos <= 10:
            div_quality += 2.0
            result.div_factors.append(f"Range extreme ({pos:.0f}%)")
        elif pos >= 80 or pos <= 20:
            div_quality += 1.0
            result.div_factors.append(f"Range eleve ({pos:.0f}%)")

        # 3. Session extension (atr_ratio)
        atr_ratio = _get(bar, "sess_range_atr", 1.0)
        if atr_ratio > 1.3:
            div_quality += 1.5
            result.div_factors.append(f"Session etendue ({atr_ratio:.2f}x ATR)")
        elif atr_ratio > 1.0:
            div_quality += 0.5
            result.div_factors.append(f"Session active ({atr_ratio:.2f}x ATR)")

        # 4. VIX eleve
        vix = _get(bar, "vix_level", 0.0)
        if vix > 25:
            div_quality += 1.0
            result.div_factors.append(f"VIX eleve ({vix:.1f})")
        elif vix > 20:
            div_quality += 0.5
            result.div_factors.append(f"VIX modere ({vix:.1f})")

        # 5. Triple VWAP align CONTRE direction prix (mean reversion)
        vwap_d_side = _get_int(bar, "vwap_d_side", 0)
        vwap_w_side = _get_int(bar, "vwap_w_side", 0)
        vwap_m_side = _get_int(bar, "vwap_m_side", 0)

        if (
            dist_vwap < -100
            and vwap_d_side == 1
            and vwap_w_side == 1
            and vwap_m_side == 1
        ):
            div_quality += 1.5
            result.div_factors.append("Triple VWAP au-dessous (mean reversion)")
        elif (
            dist_vwap > 100
            and vwap_d_side == -1
            and vwap_w_side == -1
            and vwap_m_side == -1
        ):
            div_quality += 1.5
            result.div_factors.append("Triple VWAP au-dessus (mean reversion)")

        # 6. RVOL faible (push sans conviction)
        rvol = _get(bar, "rvol", 1.0)
        if rvol < 0.7:
            div_quality += 1.0
            result.div_factors.append(f"Volume faible ({rvol:.2f}x) = push sans conviction")

    result.div_quality = div_quality

    # Grade divergence
    if div_quality >= 6:
        result.div_grade = "EXTREME"
    elif div_quality >= 4:
        result.div_grade = "FORTE"
    elif div_quality >= 3:
        result.div_grade = "MODEREE"
    elif delta_div:
        result.div_grade = "FAIBLE"

    # Trending detection (ne pas fader un breakout)
    trending_up = vwap_slope_10 > TRENDING_SLOPE and delta_day_dir > 0
    trending_dn = vwap_slope_10 < -TRENDING_SLOPE and delta_day_dir < 0
    result.is_trending = trending_up or trending_dn

    # Application du bonus divergence (hors trending)
    if div_quality >= DIV_QUALITY_THRESHOLD and not result.is_trending:
        div_bias = 0.0
        if pos >= 70 and dist_vwap < -50:
            # Overextended haut → mean reversion bearish
            div_bias = min(div_quality / 20.0, DIV_BONUS_MAX)
            result.score_bear += div_bias
            result.reasons_bear.append(
                f"DIV {result.div_grade}: prix overextended haut ({div_quality:.0f}/10)"
            )
        elif pos <= 30 and dist_vwap > 50:
            # Overextended bas → mean reversion bullish
            div_bias = min(div_quality / 20.0, DIV_BONUS_MAX)
            result.score_bull += div_bias
            result.reasons_bull.append(
                f"DIV {result.div_grade}: prix overextended bas ({div_quality:.0f}/10)"
            )
    elif div_quality >= DIV_QUALITY_THRESHOLD and result.is_trending:
        result.reasons_neutral.append(
            f"DIV {result.div_grade} ignoree — trending (slope={vwap_slope_10:+.1f})"
        )
    elif div_quality >= 3:
        result.reasons_neutral.append(
            f"DIV {result.div_grade}: contexte insuffisant ({div_quality:.0f}/10)"
        )

    # ----------------------------------------------------------------------
    # FINALISATION
    # ----------------------------------------------------------------------
    # Score signed = bull - bear, borne [-1, +1] pour backward compat
    result.score_signed = max(-1.0, min(1.0, result.score_bull - result.score_bear))
    result.bias_clarity = abs(result.score_bull - result.score_bear)

    # Direction humaine
    if result.score_signed > SCORE_BULL_THRESHOLD:
        result.direction = "BULL"
    elif result.score_signed < SCORE_BEAR_THRESHOLD:
        result.direction = "BEAR"
    else:
        result.direction = "NEUTRE"

    # ----------------------------------------------------------------------
    # 🆕 Plan A1 (08/06/2026) — VETO vwap_m_side : ancrage long-terme
    #
    # vwap_m_side (VWAP MENSUEL position) = ancrage long-terme du marche.
    # Etre BULLISH contre vwap_m_side<0 (prix sous VWAP mensuel) ou BEARISH
    # contre vwap_m_side>0 (prix au-dessus VWAP mensuel) = "swimming upstream"
    # contre la structure de fond.
    #
    # Application : pousse a NEUTRE si le bias propose contredit vwap_m_side.
    # NB : ne touche pas score_bull / score_bear / score_signed (audit preserve),
    # seul `direction` bascule + flag observable `vwap_m_veto_applied`.
    #
    # Cas non-evalue : si vwap_m_side absent → _get_int default 0 → pas de veto.
    # ----------------------------------------------------------------------
    vwap_m_side_final = _get_int(bar, "vwap_m_side", 0)
    if vwap_m_side_final != 0 and result.direction != "NEUTRE":
        if result.direction == "BULL" and vwap_m_side_final < 0:
            result.vwap_m_veto_applied = True
            result.reasons_neutral.append(
                "VWAP_M VETO: signal BULL ecrase NEUTRE (vwap_m_side<0, ancrage long-terme bearish)"
            )
            result.direction = "NEUTRE"
        elif result.direction == "BEAR" and vwap_m_side_final > 0:
            result.vwap_m_veto_applied = True
            result.reasons_neutral.append(
                "VWAP_M VETO: signal BEAR ecrase NEUTRE (vwap_m_side>0, ancrage long-terme bullish)"
            )
            result.direction = "NEUTRE"

    return result


# ==============================================================================
# EXPORT
# ==============================================================================

__all__ = ["BiasResult", "compute_bias", "calc_confidence"]
