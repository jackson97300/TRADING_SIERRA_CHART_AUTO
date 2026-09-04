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

import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

# Seuils par symbole + helper d'echelle. Source unique de verite : les seuils
# ne doivent JAMAIS etre codes en dur dans ce fichier (audit 04/09 : tous les
# seuils etaient ceux de NQ, appliques tels quels a ES).
try:
    from CORE.regime_calibration import (
        RANGE_POS_BAS, RANGE_POS_HAUT, VIX_EXTREME, VIX_HIGH, VIX_LOW,
        fenetre_de_barre, get_seuils, seuils_sont_par_defaut, symbole_de_barre,
    )
    from CORE.constants import range_pos_pct
except ImportError:  # scripts lances depuis CORE/
    from regime_calibration import (
        RANGE_POS_BAS, RANGE_POS_HAUT, VIX_EXTREME, VIX_HIGH, VIX_LOW,
        fenetre_de_barre, get_seuils, seuils_sont_par_defaut, symbole_de_barre,
    )
    from constants import range_pos_pct

_logger = logging.getLogger(__name__)

# Anti-spam : le VIX manque sur ~1.2 % des barres, concentrees sur
# quelques jours. Un warning par barre noierait les logs ; un par jour
# suffit a alerter.
_vix_absent_signale: set = set()

# === Kill switch + version (R1+R2 code-reviewer 03/05) ===
# Permet rollback rapide en cas de probleme RTH J+1 sans redeploy code :
#   MIA_REGIME_SKIP_ENABLED=0 nssm restart MIA-DataBento-Paper-V2  (30s)
REGIME_SKIP_ENABLED: bool = os.environ.get("MIA_REGIME_SKIP_ENABLED", "1") == "1"

# Version calibration pour distinguer Bot 1 (dashboard ancienne 2.0) vs
# Bot 2+3 (regime_engine v2 grid search optimal 5.5).
REGIME_CALIB_VERSION: str = "v3_etats_20260904"


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
    calib_symbole: str = ""  # symbole dont les seuils ont servi (audit)


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

def _compute_bias_proxy(bar: dict, mode: str) -> tuple[float, str, int, int]:
    """Calcul bias proxy (vs CORE/bias_calculator.py compute_bias).

    Logique simplifiee (60% du compute_bias V1) :
      - VWAP slope (pente directionnelle)
      - delta_day_dir / cvd_day_dir (orderflow direction)
      - range_pos (haut = bear bias, bas = bull bias) — SKIP en mode TREND (BUG #2 fix)
      - vwap_d_side (above/below VWAP)
      - delta_divergence (binaire)

    Args:
        bar: dict ligne DMP/parquet
        mode: regime mode deja calcule par compute_regime ("TREND"|"RANGE"|"NORMAL")
              OBLIGATOIRE (fail-loud, anti silent fallback — R2 code-reviewer 08/06)

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

    # FIX BUG #3 (08/06/2026) — separer delta (priorite) + cvd (modulation).
    # AVANT : `of_dir = delta_dir or cvd_dir` (OR booleen short-circuit). Si
    # delta=+1, cvd=-1 (divergence orderflow = signal retournement classique),
    # delta prioritaire ecrasait silencieusement le cvd oppose.
    #
    # APRES : delta + cvd separes, calibration ADAPTATIVE selon presence cvd
    # (R1 code-reviewer ac988048c9c6bff6b — pipeline Databento absent de cvd_day_dir).
    # - cvd PRESENT (source Sierra DMP) : delta=0.20 vote + cvd=0.05 modulation.
    #   Max aligne 0.25. Conflit delta=+1 cvd=-1 → 0.15 (delta wins attenue).
    # - cvd ABSENT (source Databento live_enriched) : delta=0.25 vote (compat pre-fix).
    #   Eviter regression -20% signal sur 50% des consommateurs.
    # bear/bull_factors comptent UNIQUEMENT delta (cvd = modulation, pas vote).
    delta_dir = _get_int_field(bar, "delta_day_dir", 0)
    cvd_present = ("cvd_day_dir" in bar) and (bar.get("cvd_day_dir") is not None)
    cvd_dir = _get_int_field(bar, "cvd_day_dir", 0) if cvd_present else 0
    # Calibration delta adaptee : 0.20 si cvd present (split), 0.25 si cvd absent (compat).
    delta_weight = 0.20 if cvd_present else 0.25
    if delta_dir > 0:
        score += delta_weight
        bull_factors += 1
    elif delta_dir < 0:
        score -= delta_weight
        bear_factors += 1
    # CVD modulation +/- 0.05 (uniquement si present, pas de vote structurel)
    if cvd_present:
        if cvd_dir > 0:
            score += 0.05
        elif cvd_dir < 0:
            score -= 0.05

    # FIX BUG #2 (08/06/2026) — range_pos = logique mean-reversion.
    # AVANT : applique uniformement → en TREND DAY UP, range_pos > 70 est NATUREL
    # mais le proxy decrete BEAR a tort, declenchant override coherence (3 bear
    # factors) qui forcait favor = NEUTRE → STEP 0 reject 'regime_bias_neutral'
    # alors que le regime etait legitimement TREND favor=LONG.
    # APRES : range_pos n'est evalue que hors mode TREND (RANGE ou NORMAL).
    # En TREND, le prix aux extremes est attendu, pas un signal contraire.
    # FIX 04/09/2026 (INCIDENT #99 bis) — range_pos etait lu brut alors que
    # le champ est en echelle [0,1] (mediane 0.53). Avec des seuils 70/30,
    # "pos > 70" ne partait jamais et "pos < 30" partait toujours : biais
    # bull constant. range_pos_pct() lit range_pos_va, seule source [0,100].
    if mode != "TREND":
        pos = range_pos_pct(bar)
        if pos > RANGE_POS_HAUT:
            score -= 0.20
            bear_factors += 1
        elif pos < RANGE_POS_BAS:
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

def compute_regime(bar: dict, symbole: str | None = None) -> RegimeAnalysis:
    """Detecte le regime via 4 votes ponderes sur des etats Market Profile.

    Les criteres reposant sur des compteurs cumules de session
    (single_print_count, bars_in_va, sess_range_atr) et sur des magnitudes
    dependantes de l'heure (vwap_slope, poc_bar_dist) ont ete retires le
    04/09/2026 : ils mesuraient le temps ecoule plus que le marche.
    Voir CORE/regime_calibration.py et INCIDENT_LOG #100.

    Args:
        bar: barre enrichie (live_enriched) ou ligne de parquet V4.
        symbole: "ES" / "NQ". A passer explicitement depuis les builders de
            dataset : les parquets ne portent pas de colonne symbole, et le
            repli silencieux sur ES a deja produit des datasets NQ calibres
            avec les seuils ES.

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

    # Seuils calibres pour CE symbole (repli ES si inconnu). Le symbole vient
    # de l'appelant ou, a defaut, de la barre elle-meme (cle `sym`).
    # Plus aucun critere du MODE n'a de seuil numerique depuis le 04/09 :
    # les quatre restants sont des categories (IB, day type, open type,
    # profile shape). `sym` et `fenetre` ne servent donc plus qu'a tracer la
    # provenance dans `calib_symbole` — et a accueillir un futur critere
    # calibre sans avoir a re-cabler la signature.
    sym = symbole or symbole_de_barre(bar)
    fenetre = fenetre_de_barre(bar)

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

    # 3. RETIRE le 04/09/2026 — `single_print_count` est un compteur cumule
    # depuis le debut de session : mediane ES en seance 33, 33, 32, 35, puis
    # 3 apres le reset de 17h UTC, soit un facteur 11.7 pilote par l'heure.
    # Recalibrer son seuil ne corrige rien, la grandeur est mal posee.
    # Pourra revenir normalise par le temps ecoule dans la session.

    # 4. RETIRE le 04/09/2026 — |vwap_slope_10| varie d'un facteur 9.6 selon
    # l'heure en seance (0.33 a 16h UTC, 2.31 a 17h au reset du VWAP) et d'un
    # facteur 11 entre seance et hors-seance (p75 1.256 contre 0.114). La
    # pente absolue mesure surtout ou l'on se trouve dans la session.
    # Le SIGNE de la pente reste utilise par le bias proxy, ou il est
    # legitime : c'est une direction, pas une magnitude.

    # 5. RETIRE le 04/09/2026 — sess_range_atr est un cumul de session : il
    # croit mecaniquement avec l'heure (mediane ES 2.13 a 00h UTC, 4.66 a 16h,
    # 0.69 au reset de 17h, facteur 6.8). C'est une horloge, pas un regime.
    # Avec le seuil 1.0 il votait TREND sur 94.96 % des barres ES. Un vote
    # quasi-constant n'informe pas, il decale seulement le seuil effectif du
    # verdict. Total max de votes : 12 -> 11.

    # 6. Open Type — classification Dalton. Le mapping complet est dans
    # DASHBOARD/api/readers.py:OPEN_TYPE_LABELS (0 a 11).
    #
    # FIX 04/09/2026 : le code ne traitait que les valeurs 1 a 6. Or le
    # classifieur emet aussi 7, 8 et 9, qui representent 16.4 % des barres ES
    # (OAOR 9.84 % + OAIR 3.28 % + 3.28 %) — ignorees en silence, donc autant
    # de votes perdus. Semantique Market Profile :
    #   OD / OTD  : le marche part et ne revient pas       -> conviction
    #   OAOR      : ouverture HORS du range de la veille   -> conviction
    #   ORR       : rejet immediat, retournement           -> equilibre
    #   OAIR      : auction A L'INTERIEUR du range veille  -> equilibre
    #   ODF       : un drive qui echoue                    -> equilibre
    # A valider empiriquement (ces categories predisent-elles la continuation ?)
    # avant d'en faire davantage qu'un vote parmi quatre.
    open_type = _get_int_field(bar, "open_type", 0)
    if open_type in (1, 2):
        trend_votes += 1
        details.append("Open Drive")
    elif open_type in (3, 4):
        trend_votes += 1
        details.append("Open Test Drive")
    elif open_type in (8, 9):
        trend_votes += 1
        details.append("Open Auction Out of Range")
    elif open_type in (5, 6):
        range_votes += 1
        details.append("Open Rejection Reverse")
    elif open_type == 7:
        range_votes += 1
        details.append("Open Auction In Range")
    elif open_type in (10, 11):
        range_votes += 1
        details.append("Open Drive Failure")

    # 7. Profile Shape (1=P, 2=b directionnel ; 0=D, 3=DoubleDist range)
    profile_shape = _get_int_field(bar, "profile_shape", -1)
    if profile_shape in (1, 2):
        trend_votes += 1
        details.append("Profile: " + ("P" if profile_shape == 1 else "b") + "-Shape")
    elif profile_shape in (0, 3):
        range_votes += 1
        details.append("Profile: " + ("D" if profile_shape == 0 else "DoubleDist"))

    # 8 et 9. RETIRES le 04/09/2026.
    # `poc_bar_dist` : facteur 3.0 selon l'heure, et seuil calibre sur NQ
    # (p75 NQ = 15 contre p75 ES = 2) -> 0.35 % de declenchement sur ES.
    # `bars_in_va` : compteur cumule (mediane ES en seance 0, 0, 0, 0, 1, 3, 9
    # de 13h a 19h UTC). Son vote TREND se declenchait EXCLUSIVEMENT sur les
    # zeros (45.25 % des barres ES, dont 45.25 % sous le seuil), c'est-a-dire
    # sur l'absence de donnee — le defaut meme qui a fait desactiver le vote
    # RANGE de trend_day_probability. Deux poids deux mesures, corrige.

    # 10. RETIRE le 04/09/2026 — `trend_day_probability` n'a que deux valeurs
    # utiles en seance : 0.15 et 0.35. Sur ES, 0.35 couvre 70.53 % des barres
    # et 0.15 en couvre 23.64 % ; les valeurs superieures (0.45, 0.65) pesent
    # 0.16 %. Aucun seuil ne donne un taux de declenchement exploitable :
    # au-dessus de 0.30 le vote part 70.68 % du temps, au-dessus de 0.35 il ne
    # part plus du tout. C'est un booleen deguise, pas une probabilite.
    #
    # Le vote MODE ne conserve donc que quatre criteres, tous des etats
    # Market Profile verifies stables dans la journee : IB, day type,
    # open type, profile shape. Maximum 6 votes TREND, 4 votes RANGE.

    # ===== Mode verdict =====
    # Quatre criteres, tous des etats Market Profile : IB (poids 2 en
    # breakout, 1 si intacte), day type (2 ou 1), open type (1), profile
    # shape (1). Maximum atteignable : 6 votes TREND, 4 votes RANGE.
    # Seuil ramene de 3 a 2 le 04/09/2026. Le 3 avait ete derive quand le vote
    # comptait dix criteres ; avec quatre il ne restait que 10.8 % de TREND et
    # 82.3 % de NORMAL — un mode degenere. Mesure a 2 : ES TREND 27.9 % /
    # RANGE 8.5 % / NORMAL 63.6 %, NQ 25.6 % / 15.3 % / 59.1 %.
    #
    # DETTE MESUREE, a traiter : `day_type` vaut 2 ("Normal Variation") sur
    # 91.68 % des barres ES et 84.43 % des NQ, donc il vote trend+1 presque
    # toujours. Le cote RANGE part avec un handicap systematique, ce qui
    # explique l'ecart 27.9 % / 8.5 %. Soit le classifieur de day type ne
    # discrimine pas, soit la periode etudiee est atypique — a verifier JOUR
    # par jour (et non barre par barre) avant de toucher a ce critere.
    if trend_votes >= 2 and trend_votes >= range_votes + 1:
        mode = "TREND"
    elif range_votes >= 2 and range_votes >= trend_votes + 1:
        mode = "RANGE"
    else:
        mode = "NORMAL"

    # ===== Bias proxy (pour favor en mode TREND/NORMAL) =====
    # BUG #2 fix : passer `mode` au proxy pour qu'il skip range_pos en TREND
    # (mean reversion incoherente quand le prix est attendu aux extremes).
    bias_score, bias_label, bear_factors, bull_factors = _compute_bias_proxy(bar, mode)
    # FIX 04/09/2026 — meme bug que le bias proxy. Mesure sur 12 754 barres :
    # "range_pos >= 70" se declenchait 0.00 % du temps, "range_pos <= 30"
    # 100 % du temps. En mode RANGE, favor valait LONG sur TOUTES les barres
    # et SHORT jamais. Corrige le 03/06 dans regime_engine_v2.py et
    # bot4_v2/core/regime_source.py, jamais retroporte ici.
    range_pos = range_pos_pct(bar)

    # ===== Direction (favor) =====
    if mode == "RANGE":
        if range_pos >= RANGE_POS_HAUT:
            favor = "SHORT"
        elif range_pos <= RANGE_POS_BAS:
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

    # ===== Volatility regime — refonte 04/09/2026 =====
    # Deux sources ecartees apres mesure sur 10 jours :
    #   - atr_regime_zscore_60d : jamais positif (ES max +0.27, NQ max -0.31)
    #     alors que les seuils etaient a +1.5 et +2.5. HIGH et EXTREME
    #     inatteignables -> vol_regime constant. Le fix du 11/05 n'a pas tenu.
    #   - sess_range_atr : cumul de session, croit avec l'heure (facteur 6.8
    #     entre creux et pic de journee). Horloge, pas regime.
    # Le VIX est rempli a 100 %, stable dans la journee (0.49 pt d'ecart entre
    # medianes horaires) et directement interpretable par un trader d'indices.
    # Repli : NORMAL si absent (neutralite, jamais LOW qui serait un biais).
    vix = _get_field(bar, "vix_level", 0.0)
    if vix <= 0:
        # 1.23 % des barres ES sur 49 jours, concentrees sur 3 jours (dont
        # 35 % de la seance du 10/08). Le regime de volatilite est alors
        # inconnu, pas normal — on le signale au lieu de l'inventer.
        _jour = str(bar.get("session_date") or bar.get("session_date_trading") or "?")
        if _jour not in _vix_absent_signale:
            _vix_absent_signale.add(_jour)
            _logger.warning(
                "regime : vix_level absent ou nul (%r) le %s pour %s — "
                "vol_regime force a NORMAL (regime de volatilite inconnu, "
                "pas normal)", bar.get("vix_level"), _jour, sym)
        vol_regime = "NORMAL"
    elif vix >= VIX_EXTREME:
        vol_regime = "EXTREME"
    elif vix >= VIX_HIGH:
        vol_regime = "HIGH"
    elif vix < VIX_LOW:
        vol_regime = "LOW"
    else:
        vol_regime = "NORMAL"

    # ===== Confidence (votes nets / maximum atteignable) =====
    # 6 = maximum du cote TREND (2 IB + 2 day type + 1 open + 1 shape).
    # Le cote RANGE plafonne a 4, donc |trend - range| ne depasse pas 6.
    net = abs(trend_votes - range_votes)
    confidence = min(1.0, net / 6.0)

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
        calib_symbole=("%s/%s" % (sym, fenetre) if sym
                       else "DEFAUT_ES/%s" % fenetre),
    )


def compute_regime_dict(bar: dict, symbole: str | None = None) -> dict:
    """Wrapper retournant dict (pour pipeline V4 builder)."""
    r = compute_regime(bar, symbole)
    return {
        "regime_mode": r.mode,
        "regime_favor": r.favor,
        "regime_confidence": r.confidence,
        "regime_trend_votes": r.trend_votes,
        "regime_range_votes": r.range_votes,
        "regime_vol": r.vol_regime,
        "regime_actionable": int(r.is_actionable),
    }
