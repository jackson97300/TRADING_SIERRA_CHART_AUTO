"""
bias_calculator_v6.py — Module bias enrichi V4 Databento pour Bot V6 (Sim2).

CONTEXTE 04/05/2026 (Jackson) :
  Copie autonome de bias_calculator.py qui reste INCHANGE (utilise par Bot 1).
  Ce module sera enrichi progressivement via les buckets V4 :
    Phase 0 : identique au standard (parite testee)
    Phase 1 (Bucket #3) : Bloc 7 Absorption at level (+15%)
    Phase 2 (Bucket #1) : delta SMT contrarian/confirmation
    Phase 3-N : autres buckets selon plan refonte V6

Suit la meme architecture (BiasResult, blocs ponderes, score_signed [-1,+1]).
Score re-normalise [-1, +1] apres chaque ajout de bloc pour compatibilite.

Source unique de verite pour Bot V6 :
- CORE/mia2_brain_v6_databento.py (gate directionnel check_entry)
- DASHBOARD/api/builders.py (si scoring V6 dual avec calc_bias_v6 endpoint)

Logique V1 preservee (Phase 0) :
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
Date : 2026-04-24 / Copie V6 : 2026-05-04 (Jackson refonte Bot V6 Sim2)
Version : 6.0 (Phase 0 = parite avec V1 — enrichissement progressif via buckets V4)
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

PTS_CVD = 0.10

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
    # BLOC 5 — CVD direction (10%)
    # ----------------------------------------------------------------------
    cvd_dir = _get_int(bar, "cvd_day_dir", 0)

    if cvd_dir == 1:
        result.score_bull += PTS_CVD
        result.reasons_bull.append("CVD: ACCUMULATION")
    elif cvd_dir == -1:
        result.score_bear += PTS_CVD
        result.reasons_bear.append("CVD: DISTRIBUTION")

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
    # BLOC 7 — V6 BUCKET #3 : Exhaustion / Absorption (Phase 1, 04/05)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE 04/05 : sur 2726 bars NQ V4 mai 2026 :
    #   bn_absorb_*_at_level = 0% (DEAD) -> non utilisable
    #   bn_trapped_*_at_* = 0% (DEAD) -> non utilisable
    #   ctx_delta_exhaustion = 98.1% actif
    #   ctx_absorption_streak_5 = 16.5% actif (>= 1)
    # -> Re-design focus ctx_* (seules features V4 reellement actives).
    # TODO: investiguer pipeline V4 pourquoi bn_*_at_level non calcules.
    # Les branches bn_* sont conservees defensivement (no-op si features=0)
    # pour permettre activation automatique si pipeline fixe.
    #
    # Logique CONTRARIAN : exhaustion confirmee (delta_exhaustion + streak >= 3)
    # + range extreme = mean reversion forte. Lissage : streak=5 bars requis
    # filtre les spikes instantanes.
    PTS_EXHAUSTION_STRONG = 0.20  # bumped (seul mecanisme actif)
    PTS_ABSORB_AT_LEVEL = 0.15    # no-op tant que pipeline V4 ne fournit pas
    PTS_TRAPPED = 0.10            # no-op tant que pipeline V4 ne fournit pas

    # Branches bn_*_at_level (defensives, no-op actuellement)
    bn_absorb_ask_at_level = _get_int(bar, "bn_absorb_ask_at_level", 0)
    if bn_absorb_ask_at_level == 1 and pos >= 70:
        result.score_bear += PTS_ABSORB_AT_LEVEL
        result.reasons_bear.append(
            f"Absorption ASK au niveau (pos {pos:.0f}%) -> rejection probable"
        )
    bn_absorb_bid_at_level = _get_int(bar, "bn_absorb_bid_at_level", 0)
    if bn_absorb_bid_at_level == 1 and pos <= 30:
        result.score_bull += PTS_ABSORB_AT_LEVEL
        result.reasons_bull.append(
            f"Absorption BID au niveau (pos {pos:.0f}%) -> rebond probable"
        )
    trapped_buyers_at_resist = _get_int(bar, "bn_trapped_buyers_at_resistance", 0)
    if trapped_buyers_at_resist == 1:
        result.score_bear += PTS_TRAPPED
        result.reasons_bear.append("Trapped buyers a la resistance -> sortie forcee")
    trapped_sellers_at_supp = _get_int(bar, "bn_trapped_sellers_at_support", 0)
    if trapped_sellers_at_supp == 1:
        result.score_bull += PTS_TRAPPED
        result.reasons_bull.append("Trapped sellers au support -> rachat force")

    # MECANISME PRINCIPAL ACTIF : exhaustion + absorption streak (data dense)
    delta_exhaustion = _get(bar, "ctx_delta_exhaustion", 0.0)
    absorption_streak = _get(bar, "ctx_absorption_streak_5", 0.0)
    # Seuil delta_exhaustion > 0.20 (filtre exhaustion legere)
    # + streak >= 3 (lissage temporel anti flip-flop)
    if delta_exhaustion > 0.20 and absorption_streak >= 3:
        if delta_day_dir > 0 and pos >= 60:
            # Acheteurs s'epuisent en haut -> contrarian BEAR fort
            result.score_bear += PTS_EXHAUSTION_STRONG
            result.reasons_bear.append(
                f"Exhaustion acheteurs (delta={delta_exhaustion:.2f} streak={absorption_streak:.0f}) "
                f"en haut (pos {pos:.0f}%)"
            )
        elif delta_day_dir < 0 and pos <= 40:
            # Vendeurs s'epuisent en bas -> contrarian BULL fort
            result.score_bull += PTS_EXHAUSTION_STRONG
            result.reasons_bull.append(
                f"Exhaustion vendeurs (delta={delta_exhaustion:.2f} streak={absorption_streak:.0f}) "
                f"en bas (pos {pos:.0f}%)"
            )

    # ----------------------------------------------------------------------
    # BLOC 8 — V6 BUCKET #1 : SMT cross-instrument ES/NQ (Phase 2, 04/05)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE : sur 2726 bars NQ V4 mai 2026 :
    #   im_smt_divergence = 0.1% (rare, contrarian fort quand fire)
    #   im_delta_day_divergence = 1.7% (modeste, mean reversion signal)
    #   im_cross_delta_agreement_5 = 99.7% (signal confirmation/contrarian)
    #   im_volume_lead = 51% (qui mene ES ou NQ)
    # Les 2 premiers sont rares mais TRES informatifs (contrarian fort).
    # Les 2 derniers sont denses, utilises comme confirmation/divergence directionnelle.
    PTS_SMT_DIVERGENCE_STRONG = 0.20  # rare (0.1%) -> poids fort quand fire
    PTS_SMT_AGREEMENT_CONFIRM = 0.05  # dense (99.7%) -> poids faible (cofirmation usuelle)
    PTS_DELTA_DAY_DIVERGENCE = 0.10   # modeste (1.7%) -> mean reversion signal

    # SMT divergence classique (rare mais puissant) : ES new high mais NQ pas
    # = contrarian BEAR (techs decoivent vs SP). Inverse pour BULL.
    smt_div = _get_int(bar, "im_smt_divergence", 0)
    if smt_div != 0:
        # smt_div peut etre signe (-1 = NQ underperform = bearish, +1 = NQ outperform = bullish)
        if smt_div > 0:
            result.score_bull += PTS_SMT_DIVERGENCE_STRONG
            result.reasons_bull.append("SMT divergence (NQ outperform) -> BULL")
        else:
            result.score_bear += PTS_SMT_DIVERGENCE_STRONG
            result.reasons_bear.append("SMT divergence (NQ underperform) -> BEAR")

    # Delta day divergence (ES delta+ but NQ delta- ou inverse) -> mean reversion
    delta_day_div = _get_int(bar, "im_delta_day_divergence", 0)
    if delta_day_div != 0:
        # Contre la direction du delta_day_dir local (mean reversion)
        if delta_day_dir > 0:
            result.score_bear += PTS_DELTA_DAY_DIVERGENCE
            result.reasons_bear.append("Delta day divergence ES/NQ -> mean reversion BEAR")
        elif delta_day_dir < 0:
            result.score_bull += PTS_DELTA_DAY_DIVERGENCE
            result.reasons_bull.append("Delta day divergence ES/NQ -> mean reversion BULL")

    # FIX P1-5 + P2-1 (code-reviewer 04/05) : retire le bonus cross_agree
    # car double comptage avec Bloc 5 (CVD direction). Le cross_delta_agreement
    # est utilise dans regime_v6 (Vote 12) pour TREND/RANGE, pas dans bias.
    # Defaut=0 si feature absente (anciennement defaut=1 -> bonus fantome).
    # Conserve uniquement la lecture explicite si feature presente, sans points.
    _ = _get_int(bar, "im_cross_delta_agreement_5", 0)  # no-op, signal regime only

    # ----------------------------------------------------------------------
    # BLOC 9 — V6 BUCKET #5 : Multi-session structure (Phase 3, 04/05)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE : sur 2726 bars NQ V4 mai 2026 :
    #   is_in_asia/london/us_cash/us_after = 100% actifs (un par session)
    #   above_asia/london/ny/after_open = 4-26% selon session
    #   is_new_cash_high = 1.3% / is_new_cash_low = 0.4%
    # Logique : nouveau cash high/low = breakout structurel directional fort.
    # above_open = directionnel modere (trend day signal).
    PTS_NEW_CASH_EXTREME = 0.20   # rare et fort (breakout structurel)
    PTS_ABOVE_OPEN = 0.05         # frequent et modere

    # Nouveau cash high session = breakout BULL structurel
    is_new_cash_h = _get_int(bar, "is_new_cash_high", 0)
    if is_new_cash_h == 1:
        result.score_bull += PTS_NEW_CASH_EXTREME
        result.reasons_bull.append("Nouveau cash high session -> breakout BULL")
    is_new_cash_l = _get_int(bar, "is_new_cash_low", 0)
    if is_new_cash_l == 1:
        result.score_bear += PTS_NEW_CASH_EXTREME
        result.reasons_bear.append("Nouveau cash low session -> breakdown BEAR")

    # Above session opens (cumul aligne = directional confirm)
    # Ne compte que les sessions ouvertes pour eviter double comptage
    is_in_us = _get_int(bar, "is_in_us_cash", 0) or _get_int(bar, "is_in_us_after", 0)
    is_in_ld = _get_int(bar, "is_in_london", 0)
    is_in_as = _get_int(bar, "is_in_asia", 0)
    above_count_bull = 0
    above_count_bear = 0
    if is_in_us:
        if _get_int(bar, "above_ny_open", 0) == 1:
            above_count_bull += 1
        else:
            above_count_bear += 1
    if is_in_ld or is_in_us:
        if _get_int(bar, "above_london_open", 0) == 1:
            above_count_bull += 1
        else:
            above_count_bear += 1
    if is_in_as or is_in_ld or is_in_us:
        if _get_int(bar, "above_asia_open", 0) == 1:
            above_count_bull += 1
        else:
            above_count_bear += 1
    # Si toutes les sessions au-dessus opens = trend bull, inverse = trend bear
    if above_count_bull >= 2 and above_count_bear == 0:
        result.score_bull += PTS_ABOVE_OPEN
        result.reasons_bull.append(f"Above opens session ({above_count_bull} aligned)")
    elif above_count_bear >= 2 and above_count_bull == 0:
        result.score_bear += PTS_ABOVE_OPEN
        result.reasons_bear.append(f"Below opens session ({above_count_bear} aligned)")

    # ----------------------------------------------------------------------
    # BLOC 10 — V6 BUCKET #6 : Liquidity / SMC ICT (Phase 4, 04/05)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE :
    #   liquidity_sweep_high/low_lag5 = 1.8% (rare, fort signal contrarian)
    #   premium_zone = 59.1% / discount_zone = 40.8% (denses, ICT directional)
    #   spike_detected_lag3 = 3.9%
    #   swing_high/low_active_lag10 = 1.7-2.3%
    # Logique ICT/SMC :
    #   - Sweep liquidity high (lag5) = liquidite prise au top -> contrarian BEAR
    #   - Sweep liquidity low (lag5) = liquidite prise au bottom -> contrarian BULL
    #   - Premium zone (top 30% range) = favorise SHORT
    #   - Discount zone (bot 30% range) = favorise LONG
    PTS_LIQUIDITY_SWEEP = 0.15  # contrarian fort (rare)
    PTS_ZONE = 0.05             # directional faible (frequent)

    sweep_high = _get_int(bar, "liquidity_sweep_high_lag5", 0)
    if sweep_high == 1:
        result.score_bear += PTS_LIQUIDITY_SWEEP
        result.reasons_bear.append("Liquidity sweep HIGH (lag5) -> contrarian BEAR")
    sweep_low = _get_int(bar, "liquidity_sweep_low_lag5", 0)
    if sweep_low == 1:
        result.score_bull += PTS_LIQUIDITY_SWEEP
        result.reasons_bull.append("Liquidity sweep LOW (lag5) -> contrarian BULL")

    # Premium/Discount zones (ICT) - LIGHT direction signal
    in_prem = _get_int(bar, "premium_zone", 0)
    in_disc = _get_int(bar, "discount_zone", 0)
    if in_prem == 1 and in_disc == 0:
        result.score_bear += PTS_ZONE
        result.reasons_bear.append("Premium zone (ICT) -> short bias")
    elif in_disc == 1 and in_prem == 0:
        result.score_bull += PTS_ZONE
        result.reasons_bull.append("Discount zone (ICT) -> long bias")

    # ----------------------------------------------------------------------
    # BLOC 11 — V6 BUCKET #8 : Delta Divergence enriched (Phase 5, 04/05)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE :
    #   delta_div_buy = 30.2% / delta_div_sell = 34.8% (denses, signal directional)
    #   finish_strong_up/dn = 23%
    #   delta_change = 50%
    # Logique : `delta_div_buy/sell` directional (different du legacy `delta_divergence`
    # binaire utilise dans Bloc 6). Plus precis car distingue side.
    # Le Bloc 6 reste actif pour mean reversion bonus (>= DIV_QUALITY_THRESHOLD).
    # Ce bloc 11 ajoute une lecture directional CLEAN sur delta_div_buy/sell.
    PTS_DELTA_DIV_DIRECTIONAL = 0.10
    PTS_FINISH_STRONG = 0.05

    delta_div_buy_v = _get_int(bar, "delta_div_buy", 0)
    delta_div_sell_v = _get_int(bar, "delta_div_sell", 0)
    # Divergence buy = absorption a la hausse = preparation BULL
    # Divergence sell = absorption a la baisse = preparation BEAR
    if delta_div_buy_v == 1 and delta_div_sell_v == 0:
        result.score_bull += PTS_DELTA_DIV_DIRECTIONAL
        result.reasons_bull.append("Delta divergence BUY -> preparation BULL")
    elif delta_div_sell_v == 1 and delta_div_buy_v == 0:
        result.score_bear += PTS_DELTA_DIV_DIRECTIONAL
        result.reasons_bear.append("Delta divergence SELL -> preparation BEAR")

    # Finish strong : la barre cloture pres de son extreme avec volume
    # = momentum continuation
    finish_su = _get_int(bar, "finish_strong_up", 0)
    finish_sd = _get_int(bar, "finish_strong_dn", 0)
    if finish_su == 1:
        result.score_bull += PTS_FINISH_STRONG
        result.reasons_bull.append("Finish strong UP -> momentum BULL")
    elif finish_sd == 1:
        result.score_bear += PTS_FINISH_STRONG
        result.reasons_bear.append("Finish strong DN -> momentum BEAR")

    # ----------------------------------------------------------------------
    # BLOC 12 — V6 BUCKET #2 : Big Orders dominance (Phase 6, 04/05)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE :
    #   n_big_t1 = 25.7% / n_big_buy_t1 = 16.3%
    #   aggressor_imbalance = 49.8% (numeric)
    #   big_buy_dominance = 90.6% / big_sell_dominance = 89.9% (numerique)
    # Logique : si dominance institutionnelle forte (> 0.7 par cote), boost direction.
    PTS_BIG_DOM = 0.10

    big_buy_dom = _get(bar, "big_buy_dominance", 0.0)
    big_sell_dom = _get(bar, "big_sell_dominance", 0.0)
    if big_buy_dom > 0.70 and big_sell_dom < 0.30:
        result.score_bull += PTS_BIG_DOM
        result.reasons_bull.append(f"Big BUY dominance {big_buy_dom:.0%}")
    elif big_sell_dom > 0.70 and big_buy_dom < 0.30:
        result.score_bear += PTS_BIG_DOM
        result.reasons_bear.append(f"Big SELL dominance {big_sell_dom:.0%}")

    # ----------------------------------------------------------------------
    # BLOC 13 — V6 BUCKET #4 : Naked POC + Single Prints magnetism (Phase 7)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE :
    #   n_naked_poc_active = 3.5% / dist_naked_poc_nearest_pct = 3.5%
    #   has_single_print_above = 43.3% / n_single_print_zones = 53.8%
    # Logique : si naked POC tres proche (< 0.3% dist) -> magnetism directional.
    # Single print above -> attraction up (bull bias).
    PTS_NAKED_POC = 0.10
    PTS_SP = 0.05

    n_naked = _get_int(bar, "n_naked_poc_active", 0)
    dist_naked = _get(bar, "dist_naked_poc_nearest_pct", 999)
    if n_naked >= 1 and abs(dist_naked) < 0.3:
        # Magnetism vers naked POC : direction selon signe (positif=above=bull, negatif=below=bear)
        if dist_naked > 0:
            result.score_bull += PTS_NAKED_POC
            result.reasons_bull.append(f"Naked POC magnetism (dist {dist_naked:+.2f}%)")
        else:
            result.score_bear += PTS_NAKED_POC
            result.reasons_bear.append(f"Naked POC magnetism (dist {dist_naked:+.2f}%)")

    has_sp_above = _get_int(bar, "has_single_print_above", 0)
    if has_sp_above == 1 and pos < 70:  # eviter double comptage si deja en haut
        result.score_bull += PTS_SP
        result.reasons_bull.append("Single print above -> attraction up")

    # ----------------------------------------------------------------------
    # BLOC 14 — V6 BUCKET #7 : Edge / Color zones fire (Phase 8, 04/05)
    # ----------------------------------------------------------------------
    # AUDIT DENSITE :
    #   bar_edge_buy_fire = 5.4% / bar_edge_sell_fire = 6.2%
    #   bn_color_up_fwd1 = 5.6% / bn_color_dn_fwd1 = 6.3%
    # Logique : edge fire = signal directional Sierra Chart Game Changer.
    PTS_EDGE_FIRE = 0.10

    edge_b_fire = _get_int(bar, "bar_edge_buy_fire", 0)
    edge_s_fire = _get_int(bar, "bar_edge_sell_fire", 0)
    if edge_b_fire == 1 and edge_s_fire == 0:
        result.score_bull += PTS_EDGE_FIRE
        result.reasons_bull.append("Edge BUY fire (Game Changer)")
    elif edge_s_fire == 1 and edge_b_fire == 0:
        result.score_bear += PTS_EDGE_FIRE
        result.reasons_bear.append("Edge SELL fire (Game Changer)")

    # ----------------------------------------------------------------------
    # BLOC 15 — V6 BUCKET #9 : VWAP W/D/M alignment (Phase 9, 04/05)
    # ----------------------------------------------------------------------
    # Logique : si VWAP W et D alignes meme cote = trend cross-TF confirmed.
    # `vwap_w_d_aligned` directement dispo en V4.
    PTS_VWAP_ALIGN = 0.10

    vwap_wd_aligned = _get_int(bar, "vwap_w_d_aligned", 0)
    if vwap_wd_aligned == 1:
        # Direction selon vwap_d_side (1=above=bull, -1=below=bear)
        vd_side = _get_int(bar, "vwap_d_side", 0)
        if vd_side > 0:
            result.score_bull += PTS_VWAP_ALIGN
            result.reasons_bull.append("VWAP W+D aligned BULL (cross-TF)")
        elif vd_side < 0:
            result.score_bear += PTS_VWAP_ALIGN
            result.reasons_bear.append("VWAP W+D aligned BEAR (cross-TF)")

    # ----------------------------------------------------------------------
    # BLOC 16 — V6 BUCKET #10 : VP contexte etendu / failed_auction (Phase 10)
    # ----------------------------------------------------------------------
    # Logique : ctx_failed_auction = rotation cassee = trend day signal.
    # poc_migration_dir signe = direction migration POC (trend).
    PTS_FAILED_AUCTION = 0.10
    PTS_POC_MIGRATION = 0.05

    # FIX P1-5 (code-reviewer 04/05) : retire la branche conditionnelle a
    # delta_day_dir car double comptage avec Bloc 2 (OrderFlow direction).
    # Le failed_auction signal le regime (TREND), pas la direction (deja vue
    # par autres blocs). Garde dans regime_v6 Vote 14 uniquement.
    _ = _get(bar, "ctx_failed_auction", 0.0)  # no-op bias, signal regime only

    poc_mig = _get_int(bar, "poc_migration_dir", 0)
    if poc_mig > 0:
        result.score_bull += PTS_POC_MIGRATION
        result.reasons_bull.append("POC migration UP (trend BULL)")
    elif poc_mig < 0:
        result.score_bear += PTS_POC_MIGRATION
        result.reasons_bear.append("POC migration DN (trend BEAR)")

    # ----------------------------------------------------------------------
    # BLOC 17 — V6 PHASE 11 PEPITE #1 : VWAP W/M SD bands pullback support
    # ----------------------------------------------------------------------
    # Jackson 05/05 : "le marche revient s'appuyer sur une bande deviation du VWAP
    # pour monter en escalier". Densite W/M SD bands : 100% sur V4 enriched.
    # Logique : en TREND, proche W_SD1d/M_SD1d = support dynamique (LONG opp).
    # PROX_SD 0.05% = ~14 ticks sur NQ 27000 = zone touche acceptable.
    PTS_VWAP_SD_PULLBACK = 0.10
    PROX_SD_PCT = 0.05

    if vwap_slope_10 > 0.5:  # trend up confirmed
        d_w_sd1d_pct = _get(bar, "dist_vwap_w_sd1d_pct", 999)
        d_m_sd1d_pct = _get(bar, "dist_vwap_m_sd1d_pct", 999)
        if abs(d_w_sd1d_pct) < PROX_SD_PCT or abs(d_m_sd1d_pct) < PROX_SD_PCT:
            result.score_bull += PTS_VWAP_SD_PULLBACK
            result.reasons_bull.append(
                f"VWAP W/M SD-1d support dynamique (pullback escalier en trend bull)"
            )
    elif vwap_slope_10 < -0.5:  # trend down
        d_w_sd1u_pct = _get(bar, "dist_vwap_w_sd1u_pct", 999)
        d_m_sd1u_pct = _get(bar, "dist_vwap_m_sd1u_pct", 999)
        if abs(d_w_sd1u_pct) < PROX_SD_PCT or abs(d_m_sd1u_pct) < PROX_SD_PCT:
            result.score_bear += PTS_VWAP_SD_PULLBACK
            result.reasons_bear.append(
                "VWAP W/M SD+1u resistance dynamique (rebound escalier en trend bear)"
            )

    # ----------------------------------------------------------------------
    # BLOC 18 — V6 PHASE 11 PEPITE #3 : Color zones persistantes (multi-bar)
    # ----------------------------------------------------------------------
    # V6 actuel utilise bar_edge_buy/sell_fire (event 1 barre). Cette pepite
    # exploite n_color_up/dn_zones_active (densite 40-91%) = murs dynamiques
    # multi-barres. Proche zone = support/resistance V4-validated.
    PTS_COLOR_ZONE = 0.05
    PROX_COLOR_PCT = 0.10

    n_color_up = _get(bar, "n_color_up_zones_active", 0)
    n_color_dn = _get(bar, "n_color_dn_zones_active", 0)
    d_color_up = _get(bar, "dist_color_up_nearest_pct", 999)
    d_color_dn = _get(bar, "dist_color_dn_nearest_pct", 999)
    if n_color_up >= 1 and abs(d_color_up) < PROX_COLOR_PCT:
        result.score_bull += PTS_COLOR_ZONE
        result.reasons_bull.append(
            f"Color UP zone active proche ({d_color_up:+.2f}%) - support multi-bar"
        )
    if n_color_dn >= 1 and abs(d_color_dn) < PROX_COLOR_PCT:
        result.score_bear += PTS_COLOR_ZONE
        result.reasons_bear.append(
            f"Color DN zone active proche ({d_color_dn:+.2f}%) - resistance multi-bar"
        )

    # ----------------------------------------------------------------------
    # BLOC 19 — V6 PHASE 11 PEPITE #4 : Spike origins liquidity (Smart Money)
    # ----------------------------------------------------------------------
    # n_spike_origins_active densite 78% = zones d'auction failed = retest magnet.
    # Theorie ICT/Auction : prix revient tester les niveaux ou auction a casse.
    PTS_SPIKE_ORIGIN = 0.10
    PROX_SPIKE_PCT = 0.10

    n_spk = _get(bar, "n_spike_origins_active", 0)
    d_spk = _get(bar, "dist_last_spike_origin_pct", 999)
    if n_spk >= 2 and abs(d_spk) < PROX_SPIKE_PCT:
        if d_spk > 0:
            # Spike origin au-dessus = retest magnet vers le haut
            result.score_bull += PTS_SPIKE_ORIGIN
            result.reasons_bull.append(
                f"Spike origin actif au-dessus ({d_spk:+.2f}%) - magnet retest BULL"
            )
        else:
            result.score_bear += PTS_SPIKE_ORIGIN
            result.reasons_bear.append(
                f"Spike origin actif en-dessous ({d_spk:+.2f}%) - magnet retest BEAR"
            )

    # ----------------------------------------------------------------------
    # BLOC 20 — V6 PHASE 11 PEPITE #5 : Cross-instrument detaille NQ/ES
    # ----------------------------------------------------------------------
    # Au-dela de im_smt_divergence + im_cross_delta_agreement : exploiter
    # im_price_ratio_slope_10 (rotation tech vs SP) et im_rolling_correlation_10.
    # Densite : 100% / 99.9%. Correlation drop = setup divergent risque.
    PTS_CROSS_CORR_PENALTY = 0.05
    PTS_RATIO_SLOPE = 0.05

    corr_10 = _get(bar, "im_rolling_correlation_10", 1.0)
    ratio_slope = _get(bar, "im_price_ratio_slope_10", 0.0)
    # FIX R3 re-audit code-reviewer (05/05) : penalty 2-cotes paralysait le bot
    # en regime divergent (VIX>25 NQ tech rotation). Maintenant penalty
    # DIRECTIONAL : penalise UNIQUEMENT le cote contredisant ratio_slope.
    # Si corr<0.5 ET ratio_slope>0 (NQ outperform) -> penalise BEAR (corr drop
    # invalide la direction NQ underperform implicite).
    if corr_10 < 0.5:
        if ratio_slope > 0:
            # NQ outperform mais correlation cassee -> penaliser BEAR (signal contra)
            result.score_bear = max(0.0, result.score_bear - PTS_CROSS_CORR_PENALTY)
            result.reasons_neutral.append(
                f"Cross-corr drop ({corr_10:.2f}) + NQ outperform - BEAR penalise"
            )
        elif ratio_slope < 0:
            # NQ underperform mais correlation cassee -> penaliser BULL (signal contra)
            result.score_bull = max(0.0, result.score_bull - PTS_CROSS_CORR_PENALTY)
            result.reasons_neutral.append(
                f"Cross-corr drop ({corr_10:.2f}) + NQ underperform - BULL penalise"
            )
        # Si ratio_slope ~0 et corr<0.5, no-op (vraie incertitude, on laisse aux
        # autres blocs decider)
    # Ratio slope NQ/ES : positif = NQ outperform = bullish tech rotation
    if ratio_slope > 0.0001:
        result.score_bull += PTS_RATIO_SLOPE
        result.reasons_bull.append(
            f"NQ/ES ratio slope positif ({ratio_slope:+.4f}) - tech rotation BULL"
        )
    elif ratio_slope < -0.0001:
        result.score_bear += PTS_RATIO_SLOPE
        result.reasons_bear.append(
            f"NQ/ES ratio slope negatif ({ratio_slope:+.4f}) - tech rotation BEAR"
        )

    # ----------------------------------------------------------------------
    # BLOC 21 — V6 PHASE 11 PEPITE #6 : Pre-news attenuation continue
    # ----------------------------------------------------------------------
    # eco_calendar.is_blocked_combined() est binaire (block/allow). Ce bloc
    # ajoute une attenuation CONTINUE 5-30 min avant news (anti-clustering Lopez).
    # mins_to_next_news densite 100%.
    PRE_NEWS_PENALTY = 0.05

    mins_news = _get(bar, "mins_to_next_news", 999)
    if 5 <= mins_news < 15:
        if result.score_bull > 0:
            result.score_bull = max(0.0, result.score_bull - PRE_NEWS_PENALTY)
        if result.score_bear > 0:
            result.score_bear = max(0.0, result.score_bear - PRE_NEWS_PENALTY)
        result.reasons_neutral.append(
            f"PRE-NEWS proche ({mins_news:.0f}min) - bias attenue (-{PRE_NEWS_PENALTY})"
        )
    elif 0 < mins_news < 5:
        # Tres proche news : penalite double + flag (eco_calendar gate fait le block)
        if result.score_bull > 0:
            result.score_bull = max(0.0, result.score_bull - PRE_NEWS_PENALTY * 2)
        if result.score_bear > 0:
            result.score_bear = max(0.0, result.score_bear - PRE_NEWS_PENALTY * 2)
        result.reasons_neutral.append(
            f"PRE-NEWS imminent ({mins_news:.0f}min) - bias divise par 2"
        )

    # ----------------------------------------------------------------------
    # FINALISATION
    # ----------------------------------------------------------------------
    # Score signed = bull - bear, borne [-1, +1] pour backward compat
    # FIX P1-4 (04/05) + R1 re-audit Phase 11 (05/05) :
    # Avec 21 blocs maintenant (16 base + 5 pepites Phase 11 17-21), max theorique
    # bull = 3.00 + (0.10+0.05+0.10+0.05+0.05) = ~3.35.
    # NORM_FACTOR ajuste 0.50 -> 0.40 pour limiter clip absorption a ~24%
    # (vs 39% si on gardait 0.50). Preserve signal nuance entre 0.40-1.00.
    BIAS_V6_NORM_FACTOR = 0.40
    delta_raw = result.score_bull - result.score_bear
    delta_norm = delta_raw * BIAS_V6_NORM_FACTOR
    result.score_signed = max(-1.0, min(1.0, delta_norm))
    # bias_clarity normalise aussi pour coherence avec score_signed (P3-2 review)
    result.bias_clarity = abs(delta_norm)

    # Direction humaine
    if result.score_signed > SCORE_BULL_THRESHOLD:
        result.direction = "BULL"
    elif result.score_signed < SCORE_BEAR_THRESHOLD:
        result.direction = "BEAR"
    else:
        result.direction = "NEUTRE"

    return result


# ==============================================================================
# EXPORT
# ==============================================================================

__all__ = ["BiasResult", "compute_bias", "calc_confidence"]
