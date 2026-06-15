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

Strategy unifiee : etoile-mere = dashboard verdict (deja cluster 6 sous-signaux
bull_pts/bear_pts/bias/MTF/divergence/gamma). On NE DUPLIQUE PAS MTF par dessus
(double-comptage = pattern 11 V1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from CORE.bot1_v2.config import Bot1V2Config


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
    stars_count: int = 0  # nombre etoiles qualite allumees
    stars_total: int = 5  # total etoiles
    ready_to_arm: bool = False
    skip_reason: str = ""


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


def _direction_from_action(action: str) -> Optional[str]:
    """ACHAT -> LONG, VENTE -> SHORT, else None."""
    if not isinstance(action, str):
        return None
    a = action.upper()
    if "ACHAT" in a:
        return "LONG"
    if "VENTE" in a:
        return "SHORT"
    return None


# ============================================================
# BASE - reproduit logique dashboard
# ============================================================

def _compute_mtf_counts(bar: dict) -> tuple[int, int, int]:
    """MTF confluence : compte bulls/bears/neutres sur 4 VRAIES timeframes.

    Source 1 : si dashboard injecte mtf_bulls/bears (live mode) -> read direct.
    Source 2 : fallback VRAI MTF a partir de sierra_enriched 613 features :
      - TF1 (court 3-min) : momentum_3b sign
      - TF2 (moyen 5-min) : momentum_5b sign
      - TF3 (daily) : vwap_d_side (au-dessus/sous VWAP daily)
      - TF4 (long terme) : vwap_w_side OU vwap_m_side (weekly preferable)

    Ces 4 TF sont REELLEMENT differentes (3min / 5min / 1day / 1week)
    contrairement au fallback precedent qui melangeait indicateurs sur meme bar.
    """
    # Si bar contient deja les comptes (dashboard data injectee live)
    mtf_bulls = _as_int(bar.get("mtf_bulls"))
    mtf_bears = _as_int(bar.get("mtf_bears"))
    mtf_neutres = _as_int(bar.get("mtf_neutres"))
    if (mtf_bulls + mtf_bears + mtf_neutres) > 0:
        return mtf_bulls, mtf_bears, mtf_neutres

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
    return bulls, bears, neutres


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


def _compute_dashboard_action(
    bar: dict,
    bull_pts: int,
    bear_pts: int,
    bias_label: str,
    mtf_bulls: int,
    mtf_bears: int,
) -> str:
    """Reproduit conseil_global logic (builders.py).

    Si dashboard data injectee -> read direct.
    Sinon : derive selon pts + MTF (simplifie).
    """
    # 1. Si bar contient deja le verdict dashboard (mode shadow)
    action = bar.get("conseil_action") or bar.get("executable_action")
    if isinstance(action, str) and action.strip():
        return action.strip().upper()

    # 2. Derive STRICT (sans verdict dashboard inject, on est conservateur).
    #    Critere : TOUS les 4 signaux directionnels + MTF + bias coherent.
    #    Cible : ~0.5-2% bars passent = trades RARES de qualite.
    bias_bull = bias_label == "BULLISH"
    bias_bear = bias_label == "BEARISH"

    # ACHAT FORT : 4/4 bull + MTF >= 3 + bias BULLISH
    if bull_pts == 4 and bear_pts == 0 and mtf_bulls >= 3 and bias_bull:
        return "ACHAT"
    # VENTE FORTE : 4/4 bear + MTF >= 3 + bias BEARISH
    if bear_pts == 4 and bull_pts == 0 and mtf_bears >= 3 and bias_bear:
        return "VENTE"
    # ACHAT PRUDENT : 3/4 bull + MTF >= 3 + bias BULLISH
    if bull_pts >= 3 and bear_pts == 0 and mtf_bulls >= 3 and bias_bull:
        return "ACHAT PRUDENT"
    # VENTE PRUDENTE : 3/4 bear + MTF >= 3 + bias BEARISH
    if bear_pts >= 3 and bull_pts == 0 and mtf_bears >= 3 and bias_bear:
        return "VENTE PRUDENTE"
    return "ATTENDRE"


def _compute_pts(bar: dict) -> tuple[int, int]:
    """Bull/bear points - read dashboard si present, sinon derive simplifie."""
    bull = _as_int(bar.get("bull_pts") or bar.get("conseil_bull_pts"))
    bear = _as_int(bar.get("bear_pts") or bar.get("conseil_bear_pts"))
    if (bull + bear) > 0:
        return bull, bear

    # Derive simplifie :
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
    momentum = _as_float(bar.get("momentum_5b"))
    if momentum > 1.0:
        bull += 1
    elif momentum < -1.0:
        bear += 1
    return bull, bear


# ============================================================
# AMELIORATIONS - 4 vetos hard
# ============================================================

def _check_climax_veto(
    bar: dict, direction: Optional[str], cfg: Bot1V2Config,
) -> Optional[VetoFired]:
    """VETO Wyckoff climax : epuisement = reversal probable.

    Trade -$967 (15/06 ES SHORT) avait ctx_climax_signal=True, ignored par bot
    actuel. Bot 1 v2 BLOQUE.
    """
    if not cfg.CLIMAX_VETO_ENABLED:
        return None
    if not _as_bool(bar.get("ctx_climax_signal")):
        return None
    # climax + direction = blocage hard (peu importe sens climax car detection
    # binaire dans ctx_rolling, on assume bidirectionnel)
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
    """
    rvol_z = abs(_as_float(bar.get("rvol_zscore")))
    if rvol_z <= cfg.RVOL_ZSCORE_VETO_THRESHOLD:
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


def _check_quality_bias(
    bar: dict, direction: str, bias_score: float, cfg: Bot1V2Config,
) -> Optional[QualityMiss]:
    """Etoile qualite : bias score absolu fort + signe coherent direction."""
    if abs(bias_score) < cfg.BIAS_SCORE_MIN_ABS:
        return QualityMiss(
            name="BIAS_WEAK",
            reason=f"|bias_score|={abs(bias_score):.2f} < {cfg.BIAS_SCORE_MIN_ABS}",
            value=bias_score,
        )
    # Direction coherence : LONG necessite bias_score positif, SHORT negatif
    if direction == "LONG" and bias_score < 0:
        return QualityMiss(
            name="BIAS_OPPOSITE", reason=f"LONG mais bias_score={bias_score:.2f}", value=bias_score,
        )
    if direction == "SHORT" and bias_score > 0:
        return QualityMiss(
            name="BIAS_OPPOSITE", reason=f"SHORT mais bias_score={bias_score:.2f}", value=bias_score,
        )
    return None


def _check_quality_mtf(
    direction: str, mtf_bulls: int, mtf_bears: int, cfg: Bot1V2Config,
) -> Optional[QualityMiss]:
    """Etoile qualite : MTF aligne (>=3) sans TF opposee (max 0)."""
    if direction == "LONG":
        if mtf_bulls < cfg.MTF_MIN_ALIGNED:
            return QualityMiss(
                name="MTF_INSUFFICIENT",
                reason=f"LONG mtf_bulls={mtf_bulls} < {cfg.MTF_MIN_ALIGNED}",
                value=mtf_bulls,
            )
        if mtf_bears > cfg.MTF_MAX_OPPOSED:
            return QualityMiss(
                name="MTF_CONFLICT",
                reason=f"LONG mtf_bears={mtf_bears} > {cfg.MTF_MAX_OPPOSED}",
                value=mtf_bears,
            )
    else:  # SHORT
        if mtf_bears < cfg.MTF_MIN_ALIGNED:
            return QualityMiss(
                name="MTF_INSUFFICIENT",
                reason=f"SHORT mtf_bears={mtf_bears} < {cfg.MTF_MIN_ALIGNED}",
                value=mtf_bears,
            )
        if mtf_bulls > cfg.MTF_MAX_OPPOSED:
            return QualityMiss(
                name="MTF_CONFLICT",
                reason=f"SHORT mtf_bulls={mtf_bulls} > {cfg.MTF_MAX_OPPOSED}",
                value=mtf_bulls,
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


def _check_quality_momentum(
    bar: dict, direction: str, cfg: Bot1V2Config,
) -> Optional[QualityMiss]:
    """Etoile qualite : momentum 5b fort dans la direction du signal."""
    momentum = _as_float(bar.get("momentum_5b"))
    if direction == "LONG":
        if momentum < cfg.MOMENTUM_5B_MIN_ABS:
            return QualityMiss(
                name="MOMENTUM_WEAK",
                reason=f"LONG momentum_5b={momentum:.2f} < {cfg.MOMENTUM_5B_MIN_ABS}",
                value=momentum,
            )
    else:  # SHORT
        if momentum > -cfg.MOMENTUM_5B_MIN_ABS:
            return QualityMiss(
                name="MOMENTUM_WEAK",
                reason=f"SHORT momentum_5b={momentum:.2f} > {-cfg.MOMENTUM_5B_MIN_ABS}",
                value=momentum,
            )
    return None


def _check_quality_near_level(
    bar: dict, cfg: Bot1V2Config,
) -> Optional[QualityMiss]:
    """Etoile qualite : price action SUR un niveau de confluence.

    Critere : `bool_near_level == 1` (feature dashboard).
    Fallback : verifier dist_cur_vpoc OR dist_vwap_d OR dist_cur_vah/val proche.
    """
    if not cfg.REQUIRE_NEAR_LEVEL:
        return None
    bool_near = _as_int(bar.get("bool_near_level"))
    if bool_near == 1:
        return None
    # Fallback : verifier si proche d'un niveau key dans le bar
    for key in ("dist_cur_vpoc", "dist_vwap_d", "dist_cur_vah", "dist_cur_val"):
        dist = _as_float(bar.get(key))
        if 0 < abs(dist) <= 5:  # +/- 5 ticks d'un niveau key
            return None
    return QualityMiss(
        name="NO_LEVEL_NEAR",
        reason="bool_near_level=0 et aucun niveau key proche (price dans le vide)",
    )


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
    """Calcule le verdict miroir dashboard + applique vetos + etoiles qualite.

    Args:
        bar : dict sierra_enriched (613 features) + dashboard data optionnelle
        cfg : config (default si None)
        symbol : "ES" / "NQ" / "MGC" pour pullback ticks calibration

    Returns:
        MirrorVerdict avec ready_to_arm True ssi action valide + 0 veto + 6/6 stars.
    """
    if cfg is None:
        cfg = Bot1V2Config.from_env()
    # Auto-detect symbol depuis bar si possible
    bar_sym = bar.get("sym") or bar.get("symbol")
    if isinstance(bar_sym, str) and bar_sym in ("ES", "NQ", "MGC"):
        symbol = bar_sym

    # 1. BASE - reproduit dashboard
    bull_pts, bear_pts = _compute_pts(bar)
    mtf_bulls, mtf_bears, mtf_neutres = _compute_mtf_counts(bar)
    bias_score, bias_label = _compute_bias(bar)
    mtf_verdict = "ALIGNE" if max(mtf_bulls, mtf_bears) >= 3 else "CONFLIT"

    action = _compute_dashboard_action(
        bar, bull_pts, bear_pts, bias_label, mtf_bulls, mtf_bears,
    )
    direction = _direction_from_action(action)

    # 2. ETOILE-MERE : action doit etre dans liste acceptee
    action_accepted = action in cfg.DASHBOARD_VERDICTS_ACCEPTED
    if not action_accepted or direction is None:
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
            ready_to_arm=False,
            skip_reason=f"DASHBOARD_VERDICT_REJECTED:{action}",
        )

    # 3. VETOS HARD (rejet immediat)
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

    # 4. ETOILES QUALITE (FORTE CONVICTION cluster)
    # Jackson souverain : "SIGNAUX FORT CONVICTION" + "TRADE DANS SENS TENDANCE"
    # 6 etoiles. TOUTES doivent etre allumees pour ready_to_arm = True.
    quality_misses: list[QualityMiss] = []
    for check_fn in (
        lambda: _check_quality_bias(bar, direction, bias_score, cfg),
        lambda: _check_quality_mtf(direction, mtf_bulls, mtf_bears, cfg),
        lambda: _check_quality_rvol(bar, cfg),
        lambda: _check_quality_momentum(bar, direction, cfg),
        lambda: _check_quality_near_level(bar, cfg),
        lambda: _check_quality_pullback(bar, direction, cfg, symbol),
    ):
        miss = check_fn()
        if miss:
            quality_misses.append(miss)

    stars_total = 6
    stars_count = stars_total - len(quality_misses)

    # Verdict : aucun veto ET toutes etoiles allumees (5/5)
    ready = (len(vetos) == 0) and (stars_count == stars_total)

    skip_reason = ""
    if vetos:
        skip_reason = "VETO:" + ",".join(v.name for v in vetos)
    elif quality_misses:
        skip_reason = f"QUALITY_INSUFFICIENT:{stars_count}/{stars_total}:" + ",".join(m.name for m in quality_misses)

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
        vetos=tuple(vetos),
        quality_misses=tuple(quality_misses),
        stars_count=stars_count,
        stars_total=stars_total,
        ready_to_arm=ready,
        skip_reason=skip_reason,
    )
