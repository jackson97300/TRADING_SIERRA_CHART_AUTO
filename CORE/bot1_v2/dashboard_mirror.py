"""Dashboard mirror Bot 1 v2 - reproduit logique dashboard EXACTE + AMELIORATIONS.

Jackson souverain 16/06/2026 :
> "ON GARDE dashboard_mirror.py COMME BASE MULTI TIMEFRAME MAIS ON L AMELIORE"

Base : reproduit DASHBOARD/api/builders.py:build_conseil_global
  - conseil_global (ACHAT/VENTE FORTE/MODEREE/PRUDENTE/ATTENDRE)
  - mtf_bulls / mtf_bears (4 timeframes : 1M/5M/15M/1H)
  - gamma_block_long / gamma_block_short
  - bias regime + bias_score

Ameliorations Bot 1 v2 (consomme features sierra_enriched IGNOREES par dashboard) :
  - VETO ctx_climax_signal (Wyckoff epuisement) - dashboard ignore
  - VETO rvol_zscore > 3.0 (Dalton zone exceptional) - dashboard observe only
  - VETO gamma_block_short/long HARD (dashboard cap mou) - root cause -$967
  - VETO vix_regime EXTREME/CALM - regime GEX papers

Principe NO-PARALYSIS Jackson :
> "DES TRADES DE QUALITE DOIVENT PASSER, PAS TOUT BLOQUER"

Vetos calibres pour bloquer SEULEMENT cas extremes :
  - climax = True (rare event Wyckoff)
  - |rvol_zscore| > 3.0 (catastrophe, pas 2.5)
  - vix > 35 OR vix < 13 (cygne noir OR death market)
  - gamma_block True (mur < seuil critique dashboard)

Strategy REFONTE Phase 4 (19/06) : la cascade ET (verdict 4/0 x 4 vetos x
7 etoiles toutes requises = 0 trade) est remplacee par :
  1. verdict directionnel souple (dir_score = bull_pts - bear_pts, with-trend)
  2. 4 vetos hard INCHANGES
  3. 1 CORE (near_level direction-aware : support LONG / resistance SHORT)
  4. BONUS k-of-n (compte rvol/pullback/bar_confirmation >= MIN_BONUS_COUNT)
Anti double-comptage : bias/MTF/momentum sont DEJA dans dir_score -> diagnostic
seulement, ils NE gatent PLUS et NE sont PAS dans le bonus (pattern 11 V1).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from CORE.bot1_v2.config import Bot1V2Config

try:
    from CORE.constants import is_rth_bar
except ImportError:
    from constants import is_rth_bar  # type: ignore


# ============================================================
# RESULT TYPES
# ============================================================

@dataclass(frozen=True)
class VetoFired:
    """Un veto declenche - reject immediat trade."""
    name: str
    reason: str
    value: object = None


@dataclass(frozen=True)
class QualityMiss:
    """Une etoile QUALITE manquee - reduit conviction.

    Distinct des VETOS : un quality_miss ne bloque pas SI N etoiles allumees,
    mais reduit le score conviction. Si plusieurs miss = signal faible -> skip.
    """
    name: str
    reason: str
    value: object = None


@dataclass(frozen=True)
class MirrorVerdict:
    """Verdict miroir dashboard + vetos.

    Lecture par cluster.py :
      - action = ACHAT/VENTE/ACHAT PRUDENT/VENTE PRUDENTE/ATTENDRE/CONFLIT/...
      - direction = "LONG" / "SHORT" / None (ATTENDRE)
      - vetos = liste vetos declenches (vide = aucun)
      - ready_to_arm = action valide ET aucun veto
    """
    action: str  # ex: "ACHAT", "ATTENDRE"
    direction: Optional[str]  # "LONG" / "SHORT" / None
    bull_pts: int = 0
    bear_pts: int = 0
    bias_score: float = 0.0
    bias_label: str = "NEUTRAL"
    confidence: float = 0.0
    freshness: str = "IDLE"
    mtf_bulls: int = 0
    mtf_bears: int = 0
    mtf_neutres: int = 0
    mtf_verdict: str = "CONFLIT"
    gamma_block_long: bool = False
    gamma_block_short: bool = False
    vix_level: float = 0.0
    vix_regime_label: str = "?"
    rvol_zscore: float = 0.0
    ctx_climax_signal: bool = False
    vetos: tuple = field(default_factory=tuple)
    quality_misses: tuple = field(default_factory=tuple)
    stars_count: int = 0  # bonus_count (nb dimensions bonus allumees)
    stars_total: int = 3  # bonus_total (k-of-3) - compat cluster logging
    ready_to_arm: bool = False
    skip_reason: str = ""
    # FIX audit ULTRATHINK 19/06 : detecte le divorce silencieux du Mirror.
    # `bull_pts`/`bear_pts` du dashboard ne sont JAMAIS injectes dans bar
    # enriched live (NULL 100% sur 990 bars NQ 19/06). Le code tombe en fallback
    # derive simplifie (4 features hardcoded) qui n'utilise PAS les memes
    # ponderations que build_conseil_global du dashboard reel.
    # Cf agents code-reviewer + trading-strategy-analyst + schema-auditor.
    # Si True -> emit MAJEUR cote consumer (main.py) pour tracer divorce.
    fallback_pts_used: bool = False
    fallback_mtf_used: bool = False
    # FIX B3 review 19/06 : flags Phase 2 pour tracabilite J+1 cote main.py.
    daytype_regime: str = "UNKNOWN"
    daytype_confidence: float = 0.0
    daytype_aware_active: bool = False
    bypass_near_level_active: bool = False
    climax_bypass_active: bool = False
    pullback_waived_active: bool = False


# ============================================================
# HELPERS
# ============================================================

def _as_int(x, default: int = 0) -> int:
    if x is None or x is False:
        return default if x is None else 0
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _as_float(x, default: float = 0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _as_bool(x) -> bool:
    if x is None or x is False:
        return False
    if x is True:
        return True
    try:
        return float(x) != 0.0
    except (TypeError, ValueError):
        pass
    s = str(x).strip().lower()
    return s in ("true", "1", "yes", "on")


def _action_from_direction(direction: Optional[str]) -> str:
    """LONG -> ACHAT, SHORT -> VENTE, None -> ATTENDRE (compat MirrorVerdict)."""
    if direction == "LONG":
        return "ACHAT"
    if direction == "SHORT":
        return "VENTE"
    return "ATTENDRE"


# ============================================================
# BASE - reproduit logique dashboard
# ============================================================

def _compute_mtf_counts(bar: dict) -> tuple[int, int, int, bool]:
    """MTF confluence : compte bulls/bears/neutres sur 4 VRAIES timeframes.

    Source 1 : si dashboard injecte mtf_bulls/bears (live mode) -> read direct.
    Source 2 : fallback VRAI MTF a partir de sierra_enriched 613 features :
      - TF1 (court 3-min) : momentum_3b sign
      - TF2 (moyen 5-min) : momentum_5b sign
      - TF3 (daily) : vwap_d_side (au-dessus/sous VWAP daily)
      - TF4 (long terme) : vwap_w_side OU vwap_m_side (weekly preferable)

    Ces 4 TF sont REELLEMENT differentes (3min / 5min / 1day / 1week)
    contrairement au fallback precedent qui melangeait indicateurs sur meme bar.

    FIX audit 19/06 : retourne aussi flag fallback_used pour tracer divorce.
    """
    # Si bar contient deja les comptes (dashboard data injectee live)
    mtf_bulls = _as_int(bar.get("mtf_bulls"))
    mtf_bears = _as_int(bar.get("mtf_bears"))
    mtf_neutres = _as_int(bar.get("mtf_neutres"))
    if (mtf_bulls + mtf_bears + mtf_neutres) > 0:
        return mtf_bulls, mtf_bears, mtf_neutres, False

    # Fallback VRAI MTF : 4 timeframes distinctes
    bulls = 0
    bears = 0
    # TF1 : momentum 3-min (court terme)
    m3 = _as_float(bar.get("momentum_3b"))
    if m3 > 0.5: bulls += 1
    elif m3 < -0.5: bears += 1
    # TF2 : momentum 5-min (moyen terme)
    m5 = _as_float(bar.get("momentum_5b"))
    if m5 > 0.5: bulls += 1
    elif m5 < -0.5: bears += 1
    # TF3 : VWAP daily (tendance journaliere)
    vwap_d = _as_int(bar.get("vwap_d_side"))
    if vwap_d > 0: bulls += 1
    elif vwap_d < 0: bears += 1
    # TF4 : VWAP weekly (tendance hebdomadaire = grosse direction)
    vwap_w = _as_int(bar.get("vwap_w_side"))
    if vwap_w > 0: bulls += 1
    elif vwap_w < 0: bears += 1

    neutres = 4 - bulls - bears
    return bulls, bears, neutres, True  # fallback_used=True


def _compute_bias(bar: dict) -> tuple[float, str]:
    """Bias regime : score + label.

    Si dashboard data injectee -> read direct.
    Sinon : derive depuis cvd_day_dir + delta_day_dir + vwap_d_side.
    """
    score = _as_float(bar.get("bias_score"))
    label = bar.get("bias_label") or bar.get("bias")
    if isinstance(label, str) and label:
        return score, label.upper()

    cvd_dir = _as_float(bar.get("cvd_day_dir"))
    delta_dir = _as_float(bar.get("delta_day_dir"))
    vwap_side = _as_float(bar.get("vwap_d_side"))
    raw_score = (cvd_dir + delta_dir + vwap_side) / 3.0
    if raw_score > 0.33:
        return raw_score, "BULLISH"
    if raw_score < -0.33:
        return raw_score, "BEARISH"
    return raw_score, "NEUTRAL"


def _compute_pts(
    bar: dict, cfg: Optional[Bot1V2Config] = None, symbol: str = "ES",
) -> tuple[int, int, bool]:
    """Bull/bear points - read dashboard si present, sinon derive simplifie.

    SYMBOL-AWARE (Phase 4) : le point momentum utilise le seuil symbol-aware
    (ES 1.0, NQ 10.0) car momentum_5b brut n'a pas la meme echelle ES vs NQ.

    FIX audit 19/06 : retourne aussi un flag fallback_used (True si bull/bear
    dashboard absents -> fallback derive). Consumer doit emit MAJEUR pour
    tracer le divorce silencieux Mirror vs dashboard reel.
    """
    bull = _as_int(bar.get("bull_pts") or bar.get("conseil_bull_pts"))
    bear = _as_int(bar.get("bear_pts") or bar.get("conseil_bear_pts"))
    if (bull + bear) > 0:
        return bull, bear, False

    # Derive simplifie (fallback_used=True):
    bull = 0
    bear = 0
    cvd_dir = _as_float(bar.get("cvd_day_dir"))
    if cvd_dir > 0:
        bull += 1
    elif cvd_dir < 0:
        bear += 1
    delta_dir = _as_float(bar.get("delta_day_dir"))
    if delta_dir > 0:
        bull += 1
    elif delta_dir < 0:
        bear += 1
    if _as_int(bar.get("vwap_d_side")) > 0:
        bull += 1
    elif _as_int(bar.get("vwap_d_side")) < 0:
        bear += 1
    # Point momentum SYMBOL-AWARE (seuil ES 1.0 / NQ 10.0 via cfg).
    momentum = _as_float(bar.get("momentum_5b"))
    mom_min = cfg.momentum_min_abs(symbol) if cfg is not None else 1.0
    if momentum > mom_min:
        bull += 1
    elif momentum < -mom_min:
        bear += 1
    return bull, bear, True  # fallback_used=True


# ============================================================
# AMELIORATIONS - 4 vetos hard
# ============================================================

def _check_climax_veto(
    bar: dict, direction: Optional[str], cfg: Bot1V2Config,
) -> Optional[VetoFired]:
    """VETO Wyckoff climax : epuisement = reversal probable.

    Trade -$967 (15/06 ES SHORT) avait ctx_climax_signal=True, ignored par bot
    actuel. Bot 1 v2 BLOQUE.

    FIX Phase 2 audit ULTRATHINK 19/06 : climax BIDIRECTIONNEL.
    Wyckoff distingue buying climax (= bullish exhaustion = OK SHORT) vs
    selling climax (= bearish exhaustion = OK LONG). Le veto actuel bloquait
    les DEUX cas indistinctement -> perd des entries contrarian valides.
    Proxy : utiliser delta_bar comme indicateur du sens du climax.
    Source : memory `feedback_lightgbm_no_composite_indicators.md` + audit
    trading-strategy-analyst Phase 2 brief.
    Bypass possible via BOT1V2_CLIMAX_BIDIRECTIONAL=0 si comportement legacy
    bidirectionnel binaire (preserve trade -$967 protection).
    """
    if not cfg.CLIMAX_VETO_ENABLED:
        return None
    if not _as_bool(bar.get("ctx_climax_signal")):
        return None
    # FIX 19/06 : climax bidirectionnel
    # FIX 2.6.4 review trading-strategy-analyst 19/06 : default OFF.
    # Proxy delta_bar seul = insuffisant Wyckoff (need volume+spread+close+delta).
    # Risque false positive 50% sur veto rare event (3.6% bars) qui protege contre
    # disasters trade -$967 type. Phase 3 backtest requis avant activation.
    bidirectional = os.environ.get("BOT1V2_CLIMAX_BIDIRECTIONAL", "0") == "1"
    if bidirectional and direction is not None:
        delta_bar = _as_float(bar.get("delta_bar"))
        if delta_bar > 0 and direction == "SHORT":
            # buying climax (bull bar climax) -> exhaustion haussiere -> OK SHORT
            return None
        if delta_bar < 0 and direction == "LONG":
            # selling climax (bear bar climax) -> exhaustion baissiere -> OK LONG
            return None
    return VetoFired(
        name="CLIMAX_WYCKOFF",
        reason=f"ctx_climax_signal=True (epuisement Wyckoff, reversal probable)",
        value=True,
    )


def _check_rvol_veto(
    bar: dict, cfg: Bot1V2Config,
) -> Optional[VetoFired]:
    """VETO Dalton RVOL exceptional : zone d'epuisement volume.

    Calibre NO-PARALYSIS : > 3.0 (catastrophe, pas 2.5 trop strict).

    FIX audit ULTRATHINK 19/06 : cold-start guard premiere bar RTH.
    rvol_zscore rolling 20 bars contient des bars Asia/London low-vol au
    cold-start RTH open -> z-score spike artificiel (ex: 3.67 sur premier
    bar RTH 19/06). Veto faux positif systematique sur 5-10 premieres bars
    RTH = bloque les meilleurs setups d'ouverture.
    Garde : si bars_since_boot < RVOL_COLD_START_BARS (default 20) -> skip veto.
    """
    rvol_z = abs(_as_float(bar.get("rvol_zscore")))
    if rvol_z <= cfg.RVOL_ZSCORE_VETO_THRESHOLD:
        return None
    # FIX 19/06 : cold-start guard
    cold_start_bars = getattr(cfg, "RVOL_COLD_START_BARS", 20)
    bars_since_boot = _as_int(bar.get("bars_since_boot"), default=99999)
    if bars_since_boot < cold_start_bars:
        # rvol_zscore spike non fiable (rolling window pas encore RTH-pure)
        return None
    return VetoFired(
        name="RVOL_EXCEPTIONAL",
        reason=f"|rvol_zscore|={rvol_z:.2f} > {cfg.RVOL_ZSCORE_VETO_THRESHOLD} (Dalton zone epuisement)",
        value=rvol_z,
    )


def _check_gamma_veto(
    bar: dict, direction: Optional[str], cfg: Bot1V2Config,
) -> Optional[VetoFired]:
    """VETO MenthorQ gamma block : trade contre mur gamma proche.

    Root cause trade -$967 : gamma_block_short=True dans snapshot, ignored.
    Bot 1 v2 hard veto.
    """
    if not cfg.GAMMA_BLOCK_VETO_ENABLED:
        return None
    if direction == "LONG":
        if _as_bool(bar.get("gamma_block_long")):
            return VetoFired(
                name="GAMMA_BLOCK_LONG",
                reason="gamma_block_long=True (MenthorQ wall trop proche pour LONG)",
                value=True,
            )
    elif direction == "SHORT":
        if _as_bool(bar.get("gamma_block_short")):
            return VetoFired(
                name="GAMMA_BLOCK_SHORT",
                reason="gamma_block_short=True (MenthorQ wall trop proche pour SHORT)",
                value=True,
            )
    return None


def _check_quality_rvol(
    bar: dict, cfg: Bot1V2Config,
) -> Optional[QualityMiss]:
    """Etoile qualite : RVOL minimum (volume confirme).

    Note : > 3.0 = veto exceptional separe. Ici on demande >= RVOL_MIN (1.3).
    """
    rvol = _as_float(bar.get("rvol"))
    if rvol < cfg.RVOL_MIN:
        return QualityMiss(
            name="RVOL_LOW",
            reason=f"rvol={rvol:.2f} < {cfg.RVOL_MIN} (volume insuffisant)",
            value=rvol,
        )
    return None


# Niveaux d'intervention pro (sierra_enriched dist_* signes, en ticks).
# Convention verifiee (enricher_chain.py:905/963) : dist_X = (niveau - prix)/tick
#   dist > 0 -> niveau AU-DESSUS du prix -> RESISTANCE
#   dist < 0 -> niveau EN-DESSOUS du prix -> SUPPORT
# next_wall_dist_ticks RETIRE : non signe (cote inconnu). next_wall_is_call
# permettrait de le reintegrer signe plus tard (YAGNI v1).
_NEAR_LEVEL_KEYS = (
    "dist_cur_vpoc", "dist_cur_vah", "dist_cur_val",      # Market Profile jour
    "dist_vwap_d", "dist_vwap_w", "dist_vwap_m",          # VWAP multi-TF
    "dist_prev_vpoc", "dist_prev_vah", "dist_prev_val",   # niveaux veille MP
    "dist_pdh", "dist_pdl",                               # high/low veille
    "dist_open_cash", "dist_open_830",                    # open RTH
    "dist_ib_high", "dist_ib_low",                        # Initial Balance
    "dist_sess_high", "dist_sess_low",                    # range jour
)

# Mapping dist_* -> niveau brut absolu, pour sanity-check de signe (garde-fou
# pollution cross-instrument partner-bar, enricher_chain.py:745). Seuls les
# niveaux qui ont un champ brut absolu dans sierra_enriched sont mappes.
_DIST_TO_RAW_LEVEL = {
    "dist_cur_vpoc": "cur_vpoc",
    "dist_cur_vah": "cur_vah",
    "dist_cur_val": "cur_val",
    "dist_vwap_d": "vwap_d",
    "dist_pdh": "pdh",
    "dist_pdl": "pdl",
    "dist_ib_high": "ib_high",
    "dist_ib_low": "ib_low",
    "dist_sess_high": "sess_high",
    "dist_sess_low": "sess_low",
}


def _check_quality_near_level(
    bar: dict, direction: str, cfg: Bot1V2Config, symbol: str = "ES",
) -> Optional[QualityMiss]:
    """Etoile qualite : price action AU NIVEAU D'INTERVENTION PRO, COTE CORRECT.

    Jackson souverain : "ON DOIS AVOIR DES ZONES OU INTERVENIR
                         ON NE DOIS PAS TRADER A TOUT VAS"

    DIRECTION-AWARE (fix D-2, 18/06) : un LONG doit etre proche d'un SUPPORT
    (niveau en-dessous/au prix), un SHORT proche d'une RESISTANCE (au-dessus/au
    prix). Avant ce fix le check etait purement geometrique et validait des SHORT
    colles au plus bas de session (= vendre dans le trou).

    Convention dist_X = (niveau - prix)/tick :
      - dist > 0  -> RESISTANCE (au-dessus)
      - dist < 0  -> SUPPORT (en-dessous)
      - |dist| <= AT_TOL -> niveau ~AU prix (compte support ET resistance)

    Classement par SIGNE runtime niveau-par-niveau : un meme niveau (VWAP, VPOC,
    open, PDH/PDL...) est support OU resistance selon sa position vs prix a
    l'instant t. PAS de table statique support/resistance.

    Garde-fou : si le niveau brut absolu est present et que
    sign(niveau_brut - close) contredit sign(dist), le dist_* est suspect
    (pollution partner-bar cross-instrument) -> niveau ignore (fail-safe).
    """
    if not cfg.REQUIRE_NEAR_LEVEL:
        return None

    max_ticks = cfg.near_level_max_ticks(symbol)
    at_tol = cfg.NEAR_LEVEL_AT_TOL_TICKS
    close = _as_float(bar.get("close"))
    # GATE vwap_d overnight (defense, impact mesure 0 mais coherent avec sl_tp) :
    # dist_vwap_d est RTH-anchored, perime hors RTH -> ne pas l'utiliser comme zone.
    is_rth = is_rth_bar(bar)

    # 2 trackers separes : on logue le niveau du TYPE attendu par la direction.
    nearest_support = float("inf")
    nearest_resistance = float("inf")
    nearest_support_key = None
    nearest_resistance_key = None

    for key in _NEAR_LEVEL_KEYS:
        if not is_rth and key == "dist_vwap_d":
            continue  # vwap_d perime overnight -> pas une zone valide
        dist = bar.get(key)
        try:
            dist = float(dist)
        except (TypeError, ValueError):
            continue

        # Garde-fou signe : ignorer un dist_* incoherent avec son niveau brut.
        raw_key = _DIST_TO_RAW_LEVEL.get(key)
        if raw_key is not None and close > 0:
            raw = bar.get(raw_key)
            if isinstance(raw, (int, float)) and raw > 0:
                raw_sign = 1 if (raw - close) > 0 else (-1 if (raw - close) < 0 else 0)
                dist_sign = 1 if dist > 0 else (-1 if dist < 0 else 0)
                if raw_sign != 0 and dist_sign != 0 and raw_sign != dist_sign:
                    continue  # dist_* suspect (cross-instrument) -> ignore

        abs_d = abs(dist)
        # SUPPORT : niveau en-dessous ou ~au prix (dist <= +AT_TOL)
        if dist <= at_tol and abs_d < nearest_support:
            nearest_support = abs_d
            nearest_support_key = key
        # RESISTANCE : niveau au-dessus ou ~au prix (dist >= -AT_TOL)
        if dist >= -at_tol and abs_d < nearest_resistance:
            nearest_resistance = abs_d
            nearest_resistance_key = key

    if direction == "LONG":
        if nearest_support <= max_ticks:
            return None
        return QualityMiss(
            name="NOT_AT_SUPPORT",
            reason=(
                f"LONG pas a un support (proche={nearest_support_key} "
                f"@ {nearest_support:.1f}t > {max_ticks}t)"
                if nearest_support_key is not None
                else f"LONG aucun support detecte (need <= {max_ticks}t)"
            ),
            value=(nearest_support if nearest_support != float("inf") else None),
        )
    # SHORT
    if nearest_resistance <= max_ticks:
        return None
    return QualityMiss(
        name="NOT_AT_RESISTANCE",
        reason=(
            f"SHORT pas a une resistance (proche={nearest_resistance_key} "
            f"@ {nearest_resistance:.1f}t > {max_ticks}t)"
            if nearest_resistance_key is not None
            else f"SHORT aucune resistance detectee (need <= {max_ticks}t)"
        ),
        value=(nearest_resistance if nearest_resistance != float("inf") else None),
    )


def _check_quality_bar_confirmation(
    bar: dict, direction: str, cfg: Bot1V2Config,
) -> Optional[QualityMiss]:
    """Etoile qualite : la bar d'entry doit deja confirmer la direction.

    Wyckoff "test bar" : on N'ENTRE PAS sur la chute du pullback,
    on entre quand la bar courante MONTRE deja le rebond.

    Critere LONG :
      - close > open (bar verte)
      - finish_strength >= 30% (clot pres du high de la bar)
      - OR bar_color_up == 1
    Critere SHORT (symetrique).
    """
    if not cfg.BAR_CONFIRMATION_REQUIRED:
        return None

    close = _as_float(bar.get("close"))
    open_p = _as_float(bar.get("open"))
    if close <= 0 or open_p <= 0:
        return None

    finish_strength = _as_float(bar.get("finish_strength"))
    # Note : finish_strength_pct existe peut-etre dans certaines bars (0-1)
    # mais on utilise finish_strength en ticks/points selon sierra_enriched

    # FIX Phase 1A audit ULTRATHINK 24/06/2026 (market-analyst) :
    # BAR_FINISH_STRENGTH_MIN (config.py:176) etait DEAD CONFIG (jamais lu).
    # Trade 22/06 17:13 ES LONG : bar verte +0.75t MAIS finish_strength=-42
    # (close pres du low de la bar) -> SL en 0 secondes.
    # Empirique 13 trades 22/06 <60s majoritaires ont bars avortees.
    # Solution : exiger close > open ET finish_strength >= MIN (default 30).
    # Backtest mental 7j : sacrifice ~3 TP, evite ~5-7 SL = +$30 estime.
    # Wins preserves : 70-80%. Backward compat via flag config (default off
    # pour eviter regression - active explicitement via BOT1V2_BAR_FINISH_STRENGTH_ENABLED).
    finish_required = getattr(cfg, "BAR_FINISH_STRENGTH_ENABLED", False)
    finish_min = getattr(cfg, "BAR_FINISH_STRENGTH_MIN", 30.0)

    if direction == "LONG":
        # bar verte
        bar_is_green = close > open_p
        # OR bar_color_up flag
        bar_color = _as_int(bar.get("bar_color_up"))

        # Methode robust : exiger AU MOINS bar verte (color OK)
        if not bar_is_green and bar_color != 1:
            return QualityMiss(
                name="BAR_NOT_CONFIRMED_LONG",
                reason=f"LONG mais bar rouge (close={close:.2f} <= open={open_p:.2f}, color_up={bar_color})",
            )
        # FIX 24/06 : finish_strength check si activé (anti bar avortee)
        # finish_strength positif = clot pres du high (favorable LONG)
        # negatif = clot pres du low (= rejet)
        if finish_required and finish_strength < finish_min:
            return QualityMiss(
                name="BAR_FINISH_STRENGTH_WEAK_LONG",
                reason=(
                    f"LONG bar verte mais finish_strength={finish_strength:.1f}<{finish_min:.1f} "
                    "(close pres du low = bar avortee)"
                ),
            )
        return None
    else:  # SHORT
        bar_is_red = close < open_p
        bar_color = _as_int(bar.get("bar_color_dn"))

        if not bar_is_red and bar_color != 1:
            return QualityMiss(
                name="BAR_NOT_CONFIRMED_SHORT",
                reason=f"SHORT mais bar verte (close={close:.2f} >= open={open_p:.2f}, color_dn={bar_color})",
            )
        # FIX 24/06 : finish_strength inverse pour SHORT
        # SHORT bar rouge ideale = finish_strength <= -finish_min (clot pres du low)
        if finish_required and finish_strength > -finish_min:
            return QualityMiss(
                name="BAR_FINISH_STRENGTH_WEAK_SHORT",
                reason=(
                    f"SHORT bar rouge mais finish_strength={finish_strength:.1f}>{-finish_min:.1f} "
                    "(close pres du high = bar avortee)"
                ),
            )
        return None


def _check_quality_pullback(
    bar: dict, direction: str, cfg: Bot1V2Config, symbol: str = "ES",
) -> Optional[QualityMiss]:
    """Etoile qualite : entry sur PULLBACK, pas sur extremum local.

    LONG : prix doit etre RETRACE depuis le high recent
      = close < high_recent - min_pullback_ticks
    SHORT : prix doit etre RETRACE depuis le low recent
      = close > low_recent + min_pullback_ticks

    Si pas de features high/low recent disponibles, fallback sur momentum :
      LONG : momentum_3b doit etre moins positif que momentum_5b (= debut pullback)
      SHORT : momentum_3b doit etre moins negatif que momentum_5b
    """
    if not cfg.PULLBACK_REQUIRED:
        return None

    close = _as_float(bar.get("close"))
    if close <= 0:
        return None

    min_pullback_ticks = cfg.pullback_min_ticks(symbol)
    try:
        from CORE.constants import get_tick_size
    except ImportError:
        from constants import get_tick_size  # type: ignore
    tick = get_tick_size(symbol)
    min_pullback_pts = min_pullback_ticks * tick

    # Methode 1 : high/low session locale (si dispo)
    if direction == "LONG":
        # Cherche le high recent : sess_high ou cash_high ou day_max
        for key in ("sess_high", "cash_high", "day_max_price"):
            high_recent = _as_float(bar.get(key))
            if high_recent > close:
                pullback_pts = high_recent - close
                if pullback_pts >= min_pullback_pts:
                    return None  # OK pullback present
                else:
                    return QualityMiss(
                        name="NO_PULLBACK_LONG",
                        reason=f"close={close:.2f} too close to {key}={high_recent:.2f} (only {pullback_pts:.2f}pts retracement, need {min_pullback_pts:.2f})",
                    )
        # Methode 2 fallback : momentum 3b vs 5b (debut pullback)
        m3 = _as_float(bar.get("momentum_3b"))
        m5 = _as_float(bar.get("momentum_5b"))
        # Pour LONG : on veut m5 > m3 (recent momentum decline = pullback)
        if m5 > 0 and m3 < m5:
            return None  # pullback OK via momentum
        return QualityMiss(
            name="NO_PULLBACK_LONG",
            reason=f"momentum_3b={m3:.2f} >= momentum_5b={m5:.2f} (push haussier, pas pullback)",
        )
    else:  # SHORT
        for key in ("sess_low", "cash_low", "day_min_price"):
            low_recent = _as_float(bar.get(key))
            if 0 < low_recent < close:
                bounce_pts = close - low_recent
                if bounce_pts >= min_pullback_pts:
                    return None
                else:
                    return QualityMiss(
                        name="NO_PULLBACK_SHORT",
                        reason=f"close={close:.2f} too close to {key}={low_recent:.2f} (only {bounce_pts:.2f}pts bounce, need {min_pullback_pts:.2f})",
                    )
        # Fallback momentum
        m3 = _as_float(bar.get("momentum_3b"))
        m5 = _as_float(bar.get("momentum_5b"))
        # Pour SHORT : on veut m5 < m3 (recent momentum recovery = bounce)
        if m5 < 0 and m3 > m5:
            return None
        return QualityMiss(
            name="NO_PULLBACK_SHORT",
            reason=f"momentum_3b={m3:.2f} <= momentum_5b={m5:.2f} (push baissier, pas bounce)",
        )


def _check_vix_veto(
    bar: dict, cfg: Bot1V2Config,
) -> Optional[VetoFired]:
    """VETO VIX regime : skip EXTREME (>35) et CALM (<13).

    EXTREME : cygne noir / margin call risk (Bot 1 paper Sim2 doit skip)
    CALM : death market (faible edge mean reversion)
    """
    if not cfg.VIX_REGIME_VETO_ENABLED:
        return None
    vix = _as_float(bar.get("vix_level"))
    if vix <= 0:
        return None  # vix manquant : pas de veto fail-safe
    if vix > cfg.VIX_LEVEL_MAX:
        return VetoFired(
            name="VIX_EXTREME",
            reason=f"vix={vix:.2f} > {cfg.VIX_LEVEL_MAX} (cygne noir risk)",
            value=vix,
        )
    if vix < cfg.VIX_LEVEL_MIN:
        return VetoFired(
            name="VIX_CALM",
            reason=f"vix={vix:.2f} < {cfg.VIX_LEVEL_MIN} (death market, low edge)",
            value=vix,
        )
    return None


# ============================================================
# ORCHESTRATEUR
# ============================================================

def compute_verdict(
    bar: dict, cfg: Optional[Bot1V2Config] = None, symbol: str = "ES",
) -> MirrorVerdict:
    """Calcule le verdict directionnel souple + vetos hard + CORE + bonus k-of-n.

    REFONTE Phase 4 (19/06) : remplace la cascade ET (verdict 4/0 x 4 vetos x
    7 etoiles toutes requises = 0 trade) par :
      1. dir_score = bull_pts - bear_pts -> direction souple (with-trend)
      2. 4 vetos hard (climax, rvol_zscore>3, gamma, vix) INCHANGES
      3. CORE : near_level direction-aware (support pour LONG, resistance SHORT)
      4. BONUS : compte k-of-3 dimensions independantes (rvol, pullback,
         bar_confirmation). count >= MIN_BONUS_COUNT requis.

    Anti double-comptage (pattern 11 V1) : bias / MTF / momentum sont DEJA dans
    dir_score -> ils servent UNIQUEMENT de diagnostic (MirrorVerdict), ils NE
    gatent PLUS le verdict et NE sont PAS comptes dans le bonus.

    Args:
        bar : dict sierra_enriched (613 features) + dashboard data optionnelle
        cfg : config (default si None)
        symbol : "ES" / "NQ" / "MGC" pour seuils symbol-aware

    Returns:
        MirrorVerdict avec ready_to_arm True ssi direction definie + 0 veto +
        near_level OK + bonus_count >= MIN_BONUS_COUNT.
    """
    if cfg is None:
        cfg = Bot1V2Config.from_env()
    # Auto-detect symbol depuis bar si possible
    bar_sym = bar.get("sym") or bar.get("symbol")
    if isinstance(bar_sym, str) and bar_sym in ("ES", "NQ", "MGC"):
        symbol = bar_sym

    # 1. BASE - reproduit dashboard (DIAGNOSTIC seulement, sauf bull/bear_pts).
    bull_pts, bear_pts, fallback_pts_used = _compute_pts(bar, cfg, symbol)
    mtf_bulls, mtf_bears, mtf_neutres, fallback_mtf_used = _compute_mtf_counts(bar)

    # FIX B3 review 19/06 : day_verdict init early (utilise par _verdict closure).
    # En Phase 2 dormante (default OFF), le day_verdict est calcule pour
    # diagnostic mais n'influence pas la cascade. En Phase 2 active (env
    # BOT1V2_DAYTYPE_AWARE=1), il modifie bypass_near_level + waive_pullback.
    daytype_aware_global = os.environ.get("BOT1V2_DAYTYPE_AWARE", "0") == "1"
    day_verdict = None
    try:
        from CORE.bot1_v2.day_type_classifier import classify_day_type
        day_verdict = classify_day_type(bar, cfg)
    except ImportError:
        pass
    bias_score, bias_label = _compute_bias(bar)
    mtf_verdict = "ALIGNE" if max(mtf_bulls, mtf_bears) >= 3 else "CONFLIT"

    # 2. VERDICT DIRECTIONNEL SOUPLE (with-trend, dir_score).
    #    LONG  : dir_score >= +DIR_SCORE_MIN ET bear_pts <= OPPOSING_PTS_MAX
    #    SHORT : dir_score <= -DIR_SCORE_MIN ET bull_pts <= OPPOSING_PTS_MAX
    #    sinon : ATTENDRE (None). bias/MTF NE gatent PLUS.
    # FIX audit 19/06 : seuils env-configurables (defauts 3/1 preservent comportement).
    dir_min = getattr(cfg, "DIR_SCORE_MIN", 3)
    opp_max = getattr(cfg, "OPPOSING_PTS_MAX", 1)
    dir_score = bull_pts - bear_pts
    direction: Optional[str]
    if dir_score >= dir_min and bear_pts <= opp_max:
        direction = "LONG"
    elif dir_score <= -dir_min and bull_pts <= opp_max:
        direction = "SHORT"
    else:
        direction = None

    action = _action_from_direction(direction)

    # Snapshot diagnostic commun (re-utilise dans tous les returns).
    def _verdict(**kw) -> MirrorVerdict:
        return MirrorVerdict(
            action=action,
            direction=direction,
            bull_pts=bull_pts,
            bear_pts=bear_pts,
            bias_score=bias_score,
            bias_label=bias_label,
            mtf_bulls=mtf_bulls,
            mtf_bears=mtf_bears,
            mtf_neutres=mtf_neutres,
            mtf_verdict=mtf_verdict,
            gamma_block_long=_as_bool(bar.get("gamma_block_long")),
            gamma_block_short=_as_bool(bar.get("gamma_block_short")),
            vix_level=_as_float(bar.get("vix_level")),
            rvol_zscore=_as_float(bar.get("rvol_zscore")),
            ctx_climax_signal=_as_bool(bar.get("ctx_climax_signal")),
            fallback_pts_used=fallback_pts_used,
            fallback_mtf_used=fallback_mtf_used,
            daytype_regime=getattr(day_verdict, "regime", "UNKNOWN") if day_verdict else "UNKNOWN",
            daytype_confidence=getattr(day_verdict, "confidence", 0.0) if day_verdict else 0.0,
            daytype_aware_active=daytype_aware_global,
            **kw,
        )

    if direction is None:
        return _verdict(
            ready_to_arm=False,
            skip_reason="DASHBOARD_VERDICT_REJECTED:ATTENDRE",
        )

    # 3. VETOS HARD (rejet immediat) - INCHANGES.
    vetos: list[VetoFired] = []
    for check_fn in (
        lambda: _check_climax_veto(bar, direction, cfg),
        lambda: _check_rvol_veto(bar, cfg),
        lambda: _check_gamma_veto(bar, direction, cfg),
        lambda: _check_vix_veto(bar, cfg),
    ):
        veto = check_fn()
        if veto:
            vetos.append(veto)

    if vetos:
        return _verdict(
            vetos=tuple(vetos),
            stars_count=0,
            stars_total=3,
            ready_to_arm=False,
            skip_reason="VETO:" + ",".join(v.name for v in vetos),
        )

    # 4. CORE : near_level direction-aware (support LONG / resistance SHORT).
    #    Seul filtre qualite OBLIGATOIRE hors vetos. Garde le nom du miss
    #    (NOT_AT_SUPPORT / NOT_AT_RESISTANCE) comme skip_reason.
    # FIX Phase 2 audit 19/06 : day-type aware. En trend day strong, on bypass
    # le CORE near_level (Dalton "find direction in morning, stick"). En balance
    # day, on garde le filtre strict actuel.
    # day_verdict deja calcule au top (ligne ~688) pour _verdict closure.
    try:
        from CORE.bot1_v2.day_type_classifier import should_bypass_pullback
    except ImportError:
        should_bypass_pullback = lambda v: False  # noqa: E731
    # FIX B2/B3 review 19/06 : seuils env-configurables + default OFF (data-mining).
    daytype_aware = daytype_aware_global
    try:
        bypass_conf_min = float(
            os.environ.get("BOT1V2_DAYTYPE_BYPASS_CONF_MIN", "0.65")
        )
    except (TypeError, ValueError):
        bypass_conf_min = 0.65
    bypass_near_level = (
        daytype_aware
        and day_verdict is not None
        and day_verdict.regime in ("TREND_UP", "TREND_DOWN")
        and day_verdict.confidence >= bypass_conf_min
        and (
            (day_verdict.regime == "TREND_DOWN" and direction == "SHORT")
            or (day_verdict.regime == "TREND_UP" and direction == "LONG")
        )
    )
    if not bypass_near_level:
        near_miss = _check_quality_near_level(bar, direction, cfg, symbol)
        if near_miss is not None:
            return _verdict(
                quality_misses=(near_miss,),
                stars_count=0,
                stars_total=3,
                ready_to_arm=False,
                skip_reason=near_miss.name,
            )

    # 5. BONUS : COMPTE de 3 dimensions INDEPENDANTES (k-of-n).
    #    rvol >= RVOL_MIN, pullback, bar_confirmation. count >= MIN_BONUS_COUNT.
    #    Anti double-comptage : PAS bias/MTF/momentum (deja dans dir_score),
    #    PAS de bonus "conviction" (= dir_score, redondant).
    # FIX Phase 2 audit 19/06 : regime-aware. En trend day strong, le pullback
    # est statistiquement absent (continuation pure). Waiver pullback en trend
    # day pour eviter contradiction philosophique with-trend.
    # Source : memory `feedback_lightgbm_no_composite_indicators.md` + audit
    # trading-strategy-analyst : "trend day = no pullback, bot rate setups
    # valides Dalton/Wyckoff".
    # FIX 2.6.4 review trading-strategy-analyst 19/06 : env var dedie pour kill-switch
    # independant DAYTYPE_AWARE (granularite individuelle composant).
    # Default OFF : memory `feedback_no_quick_fixes.md` = pas de waiver pullback
    # sans backtest 6 mois (Dalton "shallow pullbacks" PAS bypass total).
    pullback_waive_enabled = (
        os.environ.get("BOT1V2_DAYTYPE_WAIVE_PULLBACK", "0") == "1"
    )
    waive_pullback = (
        daytype_aware
        and pullback_waive_enabled
        and day_verdict is not None
        and should_bypass_pullback(day_verdict)
        and (
            (day_verdict.regime == "TREND_DOWN" and direction == "SHORT")
            or (day_verdict.regime == "TREND_UP" and direction == "LONG")
        )
    )
    bonus_misses: list[QualityMiss] = []
    check_fns = [
        lambda: _check_quality_rvol(bar, cfg),
        lambda: _check_quality_bar_confirmation(bar, direction, cfg),
    ]
    if not waive_pullback:
        check_fns.append(
            lambda: _check_quality_pullback(bar, direction, cfg, symbol)
        )
    for check_fn in check_fns:
        miss = check_fn()
        if miss:
            bonus_misses.append(miss)

    # bonus_total adjusts to active checks (2 si pullback waived, 3 sinon)
    bonus_total = len(check_fns)
    bonus_count = bonus_total - len(bonus_misses)
    # FIX B1 review code-reviewer 19/06 : MIN_BONUS_COUNT scaling dynamique.
    # BUG legacy : si pullback waived (bonus_total=2) avec MIN_BONUS_COUNT=2,
    # le filtre devient PLUS strict (2/2=100% requis) qu'avant (2/3=66%).
    # Inverse l'intention du waive. Scale proportionnellement :
    #   bonus_total=3 -> min_required = MIN_BONUS_COUNT (legacy 2/3)
    #   bonus_total=2 -> min_required = MIN_BONUS_COUNT-1 (au moins 1/2 PASS,
    #                    coherent avec "Dalton trend day : direction et stick").
    pullback_dropped = 3 - bonus_total  # 0 ou 1
    min_required = max(1, cfg.MIN_BONUS_COUNT - pullback_dropped)

    if bonus_count < min_required:
        return _verdict(
            quality_misses=tuple(bonus_misses),
            stars_count=bonus_count,
            stars_total=bonus_total,
            ready_to_arm=False,
            skip_reason=(
                f"BONUS_INSUFFICIENT:{bonus_count}/{bonus_total}"
                f"(min={min_required}, pullback_waived={pullback_dropped>0})"
            ),
        )

    # 6. READY : direction OK + 0 veto + near_level OK + bonus_count suffisant.
    return _verdict(
        quality_misses=tuple(bonus_misses),
        stars_count=bonus_count,
        stars_total=bonus_total,
        ready_to_arm=True,
        skip_reason="",
    )
