"""scenario_generator.py - Generateur de scenarios dynamiques marche.

Consume NarrativeContext (CORE/narrative_engine.py) et produit N scenarios
heuristiques avec setups conditionnels.

# Principe ANTI-PATTERN_11 (souverain)

Les scenarios sont des OBSERVATIONS HEURISTIQUES NON-CALIBREES.
PAS de hardcoded gates, PAS de decisions trade automatiques.

`heuristic_score` n'est PAS une probabilite trade. C'est un ordre de
priorite indicatif tant qu'aucune calibration empirique (Platt scaling
ou isotonic regression sur 30j+ outcomes Lopez AFML ch.13) n'a ete
realisee. NE PAS sizer sur ce score - utiliser comme bucket de tri
seulement.

Le ML / strategy downstream consomme la List[Scenario] et decide
quel scenario suivre + quand entrer.

# Architecture

Scenario contient :
  - name, direction (bullish/bearish/range)
  - heuristic_score (0-100, non-calibre)
  - key_levels_used (references vers NarrativeContext.key_levels)
  - setups : List[TradingSetup] conditionnels

TradingSetup contient :
  - side, entry_price, entry_zone, target_1/2, stop_loss
  - r_r_ratio calcul
  - setup_type : "scalp" / "swing" (defini stops)
  - conditions_validation : List[str] (e.g. "BN absorb_bid > 0")
  - conditions_invalidation : List[str]
  - confidence : low/medium/high
  - rationale : explication concise

# Lot 3 - Setups manquants (12/06)

- Failed Breakout / Wyckoff Spring (sweep + retour intra-bar)
- FVG Fill (ICT - price returns to gap)
- Single Print Magnet (Steidlmayer - price attracted to single prints)

# Lot 4 - VIX regime filter + backlog placeholders

VIX regime filter applique avant retour des scenarios.
Placeholders documentes pour multi-TF / eco event / cross-instrument.

Auteur : MIA Trading V5 Phase B scenario generator
Date   : 2026-06-12
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from CORE.narrative_engine import KeyLevel, NarrativeContext

_LOG = logging.getLogger("scenario_generator")


# ════════════════════════════════════════════════════════════════════════════
# CONSTANTS - Stops calibres par setup_type (anti-PATTERN_11 visible)
# ════════════════════════════════════════════════════════════════════════════

# Lopez AFML ch.3 (Triple Barrier) : stop >= 1.5x volatilite intrabar.
# ATR 1min ~= volatilite intrabar -> stop minimum ~ 1 ATR pour swing.
# Scalp accepte stop plus serre car horizon court (1-5 bars).
#
# Trade-off mecanique :
#   - Swing stop 0.8 ATR + target_1 a nearest support/resistance proche
#     -> R:R 0.95 frequent. Compense par target_2 (full move) base R:R
#     quand dispo (cf _rr_base_target).
#   - Scalp stop 0.3 ATR + target proche -> R:R 1.5-2.0 typique.
#
# Acceptable ranges etroits + win rate eleve assume (Lopez asymetrie),
# mais NON-CALIBRE empirique - Phase C arbitrera.
STOP_ATR_FRAC_SWING = 0.8
STOP_ATR_FRAC_SCALP = 0.3
ENTRY_ZONE_ATR_FRAC = 0.10  # +/- 10% ATR autour entry
# Buffer de bruit ajoute sous/au-dessus d'un stop STRUCTUREL (niveau
# d'invalidation reel : ib_low/high, swing, support fade). Evite d'etre
# sorti par le bruit exactement au niveau. ctx.atr = ATR intraday POINTS.
STOP_BUFFER_ATR_FRAC = 0.25

# VIX regime filter - drop scenarios incompatibles avec regime courant.
# Reference : Vilkov/Dimitrov 2024 (cf feedback_regime_gex_finding.md).
# Phase B v4 (review market-analyst) : ajout Failed Breakout drop en calm_vix_low
# (faux signaux frequents low vol) + Range bound drop en stressed (trop volatile fade).
VIX_INCOMPATIBLE_PREFIXES = {
    "extreme": ("Range bound", "FVG Magnet", "Bullish continuation"),
    "stressed": ("FVG Magnet", "Range bound"),
    "calm_vix_low": ("Single Print Magnet", "Failed Breakout"),
    "calm": (),
    "elevated": (),
    "UNKNOWN": (),
}

# Phase B v4 Lot D - VIX hierarchy boost/penalize (market-analyst Q7 v2)
# Reference Vilkov/Dimitrov 2024 + Williams VSA regime behavior.
# Filtre BOOST/PENALIZE score, n'AJOUTE PAS de gate cascadante (anti-PATTERN_11).
VIX_SCORE_ADJUSTMENTS = {
    "calm_vix_low": {
        "Bullish continuation": +10,
        "Range bound": +5,
    },
    "calm": {
        "Range bound": +10,
        "FVG Magnet": +5,
    },
    "elevated": {
        "Failed Breakout": +10,
        "Single Print Magnet": +5,
    },
    "stressed": {
        "Failed Breakout": +15,
        "Bearish rejection": +10,
        "Judas Swing": +5,
    },
    "extreme": {
        "Failed Breakout LONG": +20,
        "Bearish rejection": +10,
    },
    "UNKNOWN": {},
}

# Phase B v4 Lot C - Filtres pro-Douglas
MIN_SCORE_FILTER = 55  # drop scenarios low-conviction
MAX_SCENARIOS_PER_BAR = 3  # max scenarios retournes (Douglas consistency)


# ════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class TradingSetup:
    """Setup trading conditionnel.

    setup_type definit le stop_loss :
      - "scalp" : stop 0.3 ATR (horizon 1-5 bars)
      - "swing" : stop 0.8 ATR (horizon 30+ bars, Lopez AFML compliant)
    """
    name: str
    side: str  # "long" / "short"
    entry_price: float
    entry_zone_low: float
    entry_zone_high: float
    target_1: float
    target_2: Optional[float]
    stop_loss: float
    r_r_ratio: float
    setup_type: str = "swing"  # "scalp" / "swing"
    conditions_validation: list = field(default_factory=list)
    conditions_invalidation: list = field(default_factory=list)
    confidence: str = "medium"  # "low" / "medium" / "high"
    rationale: str = ""


@dataclass
class Scenario:
    """Scenario directionnel heuristique.

    ATTENTION : heuristic_score n'est PAS une probabilite calibree.
    NE PAS sizer sur ce score. Utiliser comme bucket de priorite seulement.
    """
    name: str
    direction: str  # "bullish" / "bearish" / "range"
    heuristic_score: int  # 0-100 (NON-CALIBRE - anti-PATTERN_11)
    description: str
    key_levels_used: list = field(default_factory=list)  # List[KeyLevel]
    setups: list = field(default_factory=list)  # List[TradingSetup]
    primary: bool = False  # Phase B v4 Lot C : top scenario du bar (Douglas)


# ════════════════════════════════════════════════════════════════════════════
# HELPERS HEURISTIQUES
# ════════════════════════════════════════════════════════════════════════════

def _nearest_resistance(ctx: NarrativeContext) -> Optional[KeyLevel]:
    if not ctx.key_levels_resistance:
        return None
    return ctx.key_levels_resistance[0]


def _nearest_support(ctx: NarrativeContext) -> Optional[KeyLevel]:
    if not ctx.key_levels_support:
        return None
    return ctx.key_levels_support[0]


def _major_resistance(ctx: NarrativeContext) -> Optional[KeyLevel]:
    """Resistance majeure = highest confluence_count parmi top 5."""
    if not ctx.key_levels_resistance:
        return None
    top5 = ctx.key_levels_resistance[:5]
    return max(top5, key=lambda l: l.confluence_count)


def _major_support(ctx: NarrativeContext) -> Optional[KeyLevel]:
    if not ctx.key_levels_support:
        return None
    top5 = ctx.key_levels_support[:5]
    return max(top5, key=lambda l: l.confluence_count)


def _compute_r_r(entry: float, target: float, stop: float, side: str) -> float:
    """Compute R:R ratio."""
    if side == "long":
        reward = target - entry
        risk = entry - stop
    else:
        reward = entry - target
        risk = stop - entry
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def _stop_distance_atr(setup_type: str) -> float:
    """Retourne fraction ATR pour stop selon setup_type."""
    if setup_type == "scalp":
        return STOP_ATR_FRAC_SCALP
    return STOP_ATR_FRAC_SWING


def _rr_base_target(target_1: float, target_2: Optional[float], setup_type: str) -> float:
    """R:R base : target_2 si swing + disponible (plein move), sinon target_1.

    Re-review market-analyst 12/06 v2 : R:R 0.95 mecanique inacceptable
    Lopez sur swing. Solution : R:R calcule sur target_2 (full move) par
    defaut sur swing. target_1 reste cible partielle (50% close convention).
    """
    if setup_type == "swing" and target_2 is not None:
        return target_2
    return target_1


def _make_setup_long(name: str, entry: float, target: float, ctx: NarrativeContext,
                     setup_type: str = "swing", target_2: Optional[float] = None,
                     conditions_validation: Optional[list] = None,
                     conditions_invalidation: Optional[list] = None,
                     confidence: str = "medium", rationale: str = "",
                     stop_level: Optional[float] = None,
                     stop_buffer_atr: float = STOP_BUFFER_ATR_FRAC) -> TradingSetup:
    """Factory LONG setup avec stops calibres.

    stop_level : niveau d'invalidation STRUCTUREL (ib_low, swing low, support
        fade...). Si fourni, stop = stop_level - buffer (coherence d'horizon
        avec target structurel). Sinon fallback ATR intraday (scalp/swing).
    stop_buffer_atr : marge sous le niveau (default 0.25 ATR). Override possible
        (ex vwap_sd 0.5 : bandes SD transpercees a la meche = fait structurel).
    R:R calcule sur target_2 si swing + disponible (full move), sinon target_1.
    """
    if stop_level is not None and stop_level <= entry:
        # <= : famille A (fade) a entry == niveau, le buffer cree la marge.
        stop = stop_level - stop_buffer_atr * ctx.atr
    else:
        if stop_level is not None:
            # stop_level fourni mais du mauvais cote (> entry) -> fallback ATR
            # silencieux = anti-pattern VALIDATION_MISS. On trace.
            _LOG.warning(
                "LONG '%s' : stop_level=%.2f rejete (> entry=%.2f), fallback ATR %s",
                name, stop_level, entry, setup_type,
            )
        stop_frac = _stop_distance_atr(setup_type)
        stop = entry - stop_frac * ctx.atr
    # Arrondi AVANT calcul RR : le RR expose doit correspondre au stop_loss
    # expose (sinon incoherence visible sur famille A ou risk = buffer seul
    # ~3 pts amplifie l'ecart d'arrondi). Coherence interne, pas seuil.
    stop = round(stop, 2)
    rr_target = _rr_base_target(target, target_2, setup_type)
    return TradingSetup(
        name=name, side="long",
        entry_price=entry,
        entry_zone_low=entry - ENTRY_ZONE_ATR_FRAC * ctx.atr,
        entry_zone_high=entry + ENTRY_ZONE_ATR_FRAC * ctx.atr,
        target_1=target, target_2=target_2,
        stop_loss=stop,
        r_r_ratio=_compute_r_r(entry, rr_target, stop, "long"),
        setup_type=setup_type,
        conditions_validation=conditions_validation or [],
        conditions_invalidation=conditions_invalidation or [],
        confidence=confidence, rationale=rationale,
    )


def _make_setup_short(name: str, entry: float, target: float, ctx: NarrativeContext,
                      setup_type: str = "swing", target_2: Optional[float] = None,
                      conditions_validation: Optional[list] = None,
                      conditions_invalidation: Optional[list] = None,
                      confidence: str = "medium", rationale: str = "",
                      stop_level: Optional[float] = None,
                      stop_buffer_atr: float = STOP_BUFFER_ATR_FRAC) -> TradingSetup:
    """Factory SHORT setup avec stops calibres.

    stop_level : niveau d'invalidation STRUCTUREL (ib_high, swing high,
        resistance fade...). Si fourni, stop = stop_level + buffer. Sinon
        fallback ATR intraday (scalp/swing).
    stop_buffer_atr : marge au-dessus du niveau (default 0.25 ATR). Override
        possible (ex vwap_sd 0.5).
    R:R calcule sur target_2 si swing + disponible (full move), sinon target_1.
    """
    if stop_level is not None and stop_level >= entry:
        # >= : famille A (fade) a entry == niveau, le buffer cree la marge.
        stop = stop_level + stop_buffer_atr * ctx.atr
    else:
        if stop_level is not None:
            _LOG.warning(
                "SHORT '%s' : stop_level=%.2f rejete (< entry=%.2f), fallback ATR %s",
                name, stop_level, entry, setup_type,
            )
        stop_frac = _stop_distance_atr(setup_type)
        stop = entry + stop_frac * ctx.atr
    # Arrondi AVANT calcul RR : coherence stop_loss expose <-> RR expose.
    stop = round(stop, 2)
    rr_target = _rr_base_target(target, target_2, setup_type)
    return TradingSetup(
        name=name, side="short",
        entry_price=entry,
        entry_zone_low=entry - ENTRY_ZONE_ATR_FRAC * ctx.atr,
        entry_zone_high=entry + ENTRY_ZONE_ATR_FRAC * ctx.atr,
        target_1=target, target_2=target_2,
        stop_loss=stop,
        r_r_ratio=_compute_r_r(entry, rr_target, stop, "short"),
        setup_type=setup_type,
        conditions_validation=conditions_validation or [],
        conditions_invalidation=conditions_invalidation or [],
        confidence=confidence, rationale=rationale,
    )


# ════════════════════════════════════════════════════════════════════════════
# SCENARIO BUILDERS
# ════════════════════════════════════════════════════════════════════════════

def _scenario_bullish_continuation(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : continuation bull (macro bias BULL + structure favorable).

    Note Lot 1 fix : range_pos_va_pct compare a 0.7 (acceptance haute),
    non a ctx.close (bug initial comparant prix absolu a ratio).
    """
    if ctx.order_flow.macro_bias != "BULL":
        return None
    near_res = _nearest_resistance(ctx)
    near_sup = _nearest_support(ctx)
    if near_res is None or near_sup is None:
        return None

    # Score heuristique non-calibre (Phase B v4 Lot B : cap 75->65, Raschke
    # Holy Grail manquant donc continuation pure ~50-55% WR seule)
    score = 30
    if ctx.market_structure.profile_shape == "P":  # acceptance haut
        score += 15
    if (ctx.market_structure.open_relation == "OAOR"
            and ctx.market_structure.range_pos_va_pct > 0.7):  # acceptance haute VA
        score += 10
    if ctx.session.judas_swing_direction == 1:
        score += 10
    score = min(score, 65)

    # Invalidation (market-analyst 15/06) : continuation de tendance = cassure
    # du swing low (higher-low Brooks) prioritaire ; sinon cassure du support.
    bc_stop = (ctx.swing_low if (ctx.swing_low is not None and ctx.swing_low < near_sup.price)
               else near_sup.price)
    setup = _make_setup_long(
        name=f"LONG pullback {near_sup.label}",
        entry=near_sup.price,
        target=near_res.price,
        ctx=ctx,
        setup_type="swing",
        target_2=ctx.key_levels_resistance[1].price if len(ctx.key_levels_resistance) > 1 else None,
        stop_level=bc_stop,
        # Confirmation DSL (order-flow haussier au rebond) - 2 signaux non redondants
        conditions_validation=[
            "delta_bar > 0",
            "finish_strength > 0",
        ],
        conditions_invalidation=[
            "cvd_day < 0",  # macro flip bear = continuation morte
        ],
        confidence="high" if score >= 60 else "medium",
        rationale=f"Macro BULL (CVD day {ctx.order_flow.cvd_day:+d}), pullback opportuniste sur {near_sup.label}",
    )

    return Scenario(
        name="Bullish continuation",
        direction="bullish",
        heuristic_score=score,
        description=(
            f"Macro BULL confirme par CVD day {ctx.order_flow.cvd_day:+d}. "
            f"Profile {ctx.market_structure.profile_shape}-shape favorable. "
            f"Pullback vers support {near_sup.label} (@{near_sup.price}) "
            f"comme opportunite long vers resistance {near_res.label}."
        ),
        key_levels_used=[near_sup, near_res],
        setups=[setup],
    )


def _scenario_bearish_rejection(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : rejection majeur resistance (test + reject).

    Lot 1 fix : confluence>=2 ET distance<=1.5 ATR (AND obligatoire,
    Wyckoff test + cause). Le OR initial declenchait sur cluster
    solitaire a 1.4 ATR (faux signal).
    """
    major_res = _major_resistance(ctx)
    if major_res is None:
        return None
    # Wyckoff : test + cause = confluence ET proche
    if not (major_res.confluence_count >= 2 and major_res.distance_atr <= 1.5):
        return None

    near_sup = _nearest_support(ctx)
    if near_sup is None:
        return None

    # Score heuristique
    score = 25
    if major_res.confluence_count >= 3:
        score += 20
    if ctx.order_flow.session_bias == "BEAR":
        score += 10
    if ctx.patterns.sweep_high_active > 0 or ctx.patterns.sweep_high_this_bar:
        score += 15
    if ctx.market_structure.range_pos_va_pct >= 0.9:
        score += 5
    score = min(score, 70)

    setup = _make_setup_short(
        name=f"SHORT rejet {major_res.label}",
        entry=major_res.price,
        target=near_sup.price,
        ctx=ctx,
        setup_type="swing",
        target_2=ctx.key_levels_support[1].price if len(ctx.key_levels_support) > 1 else None,
        # Invalidation Wyckoff : test rate = close acceptee au-dessus de la resistance.
        stop_level=major_res.price,
        # Contre-tendance : exhaustion order-flow OBLIGATOIRE (delta- + divergence
        # baissiere) sinon on se fait ecraser dans une tendance haussiere.
        conditions_validation=[
            "delta_bar < 0",
            "delta_div_strength < 0",
        ],
        conditions_invalidation=[
            "cvd_day > 0",  # macro reste franchement bull = rejet dangereux
        ],
        confidence="high" if score >= 55 else "medium",
        rationale=f"Confluence {major_res.confluence_count} sources sur {major_res.price} ({major_res.label}), setup contre-trend",
    )

    return Scenario(
        name="Bearish rejection",
        direction="bearish",
        heuristic_score=score,
        description=(
            f"Confluence forte sur {major_res.label} (@{major_res.price}, "
            f"{major_res.confluence_count} sources). Setup SHORT contre-trend "
            f"avec target {near_sup.label}."
        ),
        key_levels_used=[major_res, near_sup],
        setups=[setup],
    )


def _range_bound_conditions(ctx: NarrativeContext) -> Optional[tuple]:
    """Conditions communes range bound. Returns (near_sup, near_res, score) ou None."""
    if ctx.market_structure.day_type not in ("NormVar", "Neutral"):
        return None
    if ctx.market_structure.trend_day_probability > 0.3:
        return None
    near_res = _nearest_resistance(ctx)
    near_sup = _nearest_support(ctx)
    if near_res is None or near_sup is None:
        return None
    range_atr = near_res.distance_atr - near_sup.distance_atr
    if range_atr < 0.5:  # range trop etroit
        return None
    # Phase B v4 Lot B : cap 60->50 (Brooks/Dalton balance check manquant)
    score = 30
    if ctx.market_structure.day_type == "NormVar":
        score += 10
    score = min(score, 50)
    return near_sup, near_res, score


def _scenario_range_bound_long_fade(ctx: NarrativeContext) -> Optional[Scenario]:
    """Lot 1 fix : Range bound split. Setup LONG fade support seul (Scenario XOR)."""
    cond = _range_bound_conditions(ctx)
    if cond is None:
        return None
    near_sup, near_res, score = cond

    setup = _make_setup_long(
        name=f"LONG fade {near_sup.label}",
        entry=near_sup.price,
        target=near_res.price,
        ctx=ctx,
        setup_type="swing",
        # Invalidation : cassure du support = sortie de range par le bas.
        stop_level=near_sup.price,
        conditions_validation=[
            "delta_bar > 0",
            "finish_strength > 0",
        ],
        conditions_invalidation=[],
        confidence="medium",
        rationale="Range NormVar attendu, fade support (XOR vs SHORT fade)",
    )

    return Scenario(
        name="Range bound LONG fade",
        direction="bullish",
        heuristic_score=score,
        description=(
            f"Day type {ctx.market_structure.day_type} + trend_day_prob "
            f"{ctx.market_structure.trend_day_probability:.2f} = range attendu. "
            f"LONG fade support {near_sup.label} ({near_sup.price})."
        ),
        key_levels_used=[near_sup, near_res],
        setups=[setup],
    )


def _scenario_range_bound_short_fade(ctx: NarrativeContext) -> Optional[Scenario]:
    """Lot 1 fix : Range bound split. Setup SHORT fade resistance seul (Scenario XOR)."""
    cond = _range_bound_conditions(ctx)
    if cond is None:
        return None
    near_sup, near_res, score = cond

    setup = _make_setup_short(
        name=f"SHORT fade {near_res.label}",
        entry=near_res.price,
        target=near_sup.price,
        ctx=ctx,
        setup_type="swing",
        # Invalidation : cassure de la resistance = sortie de range par le haut.
        stop_level=near_res.price,
        conditions_validation=[
            "delta_bar < 0",
            "finish_strength < 0",
        ],
        conditions_invalidation=[],
        confidence="medium",
        rationale="Range NormVar attendu, fade resistance (XOR vs LONG fade)",
    )

    return Scenario(
        name="Range bound SHORT fade",
        direction="bearish",
        heuristic_score=score,
        description=(
            f"Day type {ctx.market_structure.day_type} + trend_day_prob "
            f"{ctx.market_structure.trend_day_probability:.2f} = range attendu. "
            f"SHORT fade resistance {near_res.label} ({near_res.price})."
        ),
        key_levels_used=[near_sup, near_res],
        setups=[setup],
    )


def _scenario_judas_reversal(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Judas Swing detected -> reversal vraie direction.

    STOP STRUCTUREL EN ATTENTE (market-analyst 15/06) : l'invalidation canon ICT
    est le retour au-dela de l'extreme du judas swing (London first hour). Or
    london_high/low ne sont PAS persistes jusqu'a la session US (london_open=None
    confirme empiriquement). Tant que le pipeline ne les expose pas, ce builder
    reste en fallback ATR swing (0.8) - NE PAS marquer "corrige". Cf
    DOCS/SCENARIO_INVALIDATION_ANALYSIS.md (judas bloque pipeline).
    """
    if not ctx.patterns.judas_swing_active:
        return None
    direction = ctx.session.judas_swing_direction
    if direction == 0:
        return None

    # Phase B v4 Lot B : cap 75->60 (ICT OTE confluence manquant)
    score = 40
    if ctx.order_flow.bn_signals_active:
        score += 10
    score = min(score, 60)

    if direction == +1:  # Vraie direction UP
        near_res = _nearest_resistance(ctx)
        if near_res is None:
            return None
        setup = _make_setup_long(
            name="LONG post-Judas",
            entry=ctx.close,
            target=near_res.price,
            ctx=ctx,
            setup_type="swing",
            conditions_validation=["delta_bar > 0", "finish_strength > 0"],
            conditions_invalidation=[],
            confidence="high" if score >= 65 else "medium",
            rationale="Judas Swing ICT detected, direction vraie identifiee",
        )
        return Scenario(
            name="Judas Swing reversal LONG",
            direction="bullish",
            heuristic_score=score,
            description=(
                f"Judas Swing detected (London first hour direction OPPOSEE). "
                f"Vraie direction = UP. Target {near_res.label} (@{near_res.price})."
            ),
            key_levels_used=[near_res],
            setups=[setup],
        )

    # direction == -1 -> SHORT
    near_sup = _nearest_support(ctx)
    if near_sup is None:
        return None
    setup = _make_setup_short(
        name="SHORT post-Judas",
        entry=ctx.close,
        target=near_sup.price,
        ctx=ctx,
        setup_type="swing",
        conditions_validation=["delta_bar < 0", "finish_strength < 0"],
        conditions_invalidation=[],
        confidence="high" if score >= 65 else "medium",
        rationale="Judas Swing ICT detected, direction vraie identifiee",
    )
    return Scenario(
        name="Judas Swing reversal SHORT",
        direction="bearish",
        heuristic_score=score,
        description=(
            f"Judas Swing detected (London first hour direction OPPOSEE). "
            f"Vraie direction = DOWN. Target {near_sup.label} (@{near_sup.price})."
        ),
        key_levels_used=[near_sup],
        setups=[setup],
    )


# ════════════════════════════════════════════════════════════════════════════
# LOT 3 - SCENARIOS MANQUANTS
# ════════════════════════════════════════════════════════════════════════════

def _scenario_failed_breakout(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Failed Breakout / Wyckoff Spring (sweep + retour intra-bar).

    Reference : Wyckoff Phases (Spring sous range = test echec accumulation,
    UTAD au-dessus range = test echec distribution). Setup ICT historiquement
    le plus rentable.

    Trigger : sweep_high_this_bar OU sweep_low_this_bar = True + retour
    dans la range (verifie via range_pos_va).
    """
    # Spring (sweep low + retour up)
    if ctx.patterns.sweep_low_this_bar and ctx.market_structure.range_pos_va_pct >= 0.3:
        near_res = _nearest_resistance(ctx)
        if near_res is None:
            return None
        # Re-review market-analyst 12/06 v2 : Failed Breakout WR historique
        # ~30% sans confirmation N+1 (Wyckoff VSA). Score base reduit 45->35.
        score = 35
        if ctx.order_flow.bn_signals_active:
            score += 10
        if ctx.order_flow.macro_bias == "BULL":
            score += 10
        # Phase B v4 Lot B : cap 65->50 (Wyckoff VSA test bar N+1 manquant)
        score = min(score, 50)

        setup = _make_setup_long(
            name="LONG Spring (failed breakdown)",
            entry=ctx.close,
            target=near_res.price,
            ctx=ctx,
            setup_type="swing",
            # Invalidation Wyckoff (Pruden) : re-cassure du low du Spring lui-meme
            # (la barre de sweep). Si refranchi, l'accumulation est invalidee.
            stop_level=ctx.bar_low,
            conditions_validation=["delta_bar > 0", "finish_strength > 0"],
            conditions_invalidation=[],
            confidence="high" if score >= 60 else "medium",
            rationale="Sweep low + retour dans range = Spring Wyckoff (failed breakdown)",
        )
        return Scenario(
            name="Failed Breakout LONG (Spring)",
            direction="bullish",
            heuristic_score=score,
            description=(
                f"Sweep low detected this bar + retour dans range "
                f"(range_pos_va {ctx.market_structure.range_pos_va_pct:.2f}). "
                f"Wyckoff Spring = failed breakdown. Target {near_res.label}."
            ),
            key_levels_used=[near_res],
            setups=[setup],
        )

    # UTAD (sweep high + retour down)
    if ctx.patterns.sweep_high_this_bar and ctx.market_structure.range_pos_va_pct <= 0.7:
        near_sup = _nearest_support(ctx)
        if near_sup is None:
            return None
        # Re-review market-analyst 12/06 v2 : score base reduit 45->35
        score = 35
        if ctx.order_flow.bn_signals_active:
            score += 10
        if ctx.order_flow.macro_bias == "BEAR":
            score += 10
        # Phase B v4 Lot B : cap 65->50 (Wyckoff VSA test bar N+1 manquant)
        score = min(score, 50)

        setup = _make_setup_short(
            name="SHORT UTAD (failed breakout)",
            entry=ctx.close,
            target=near_sup.price,
            ctx=ctx,
            setup_type="swing",
            # Invalidation Wyckoff : re-cassure du high de l'UTAD (barre de sweep).
            stop_level=ctx.bar_high,
            conditions_validation=["delta_bar < 0", "finish_strength < 0"],
            conditions_invalidation=[],
            confidence="high" if score >= 60 else "medium",
            rationale="Sweep high + retour dans range = UTAD Wyckoff (failed breakout)",
        )
        return Scenario(
            name="Failed Breakout SHORT (UTAD)",
            direction="bearish",
            heuristic_score=score,
            description=(
                f"Sweep high detected this bar + retour dans range "
                f"(range_pos_va {ctx.market_structure.range_pos_va_pct:.2f}). "
                f"Wyckoff UTAD = failed breakout. Target {near_sup.label}."
            ),
            key_levels_used=[near_sup],
            setups=[setup],
        )

    return None


def _scenario_fvg_magnet(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : FVG Magnet (price attire vers zone d'inefficience FVG).

    # Convention semantique (cf market_profile_v5.py:_extract_fvg_state)

    `active_fvg_up` est filtre sur `gap_low >= close` : ce sont les FVG UP
    dont la zone se trouve AU-DESSUS du close. `dist_fvg_up_nearest_atr > 0`.
    Interpretation : zone d'inefficience que le price tend a venir "remplir"
    (effet magnet Steidlmayer-like, pas strict ICT "fill by retrace").

    NB ICT canonique : un bullish FVG (formed during move up) est typiquement
    consomme par retrace DOWN. Notre convention SC = magnet UP vers zone
    above. Difference assume - calibration Phase C arbitrera.

    Trigger : FVG present + distance < 1.0 ATR + macro compatible.
    """
    # FVG zone above (positive dist) -> magnet LONG si pas macro BEAR
    if (ctx.patterns.fvg_up_count > 0
            and ctx.patterns.fvg_up_dist_atr is not None
            and 0 < ctx.patterns.fvg_up_dist_atr < 1.0):
        if ctx.order_flow.macro_bias == "BEAR":
            return None
        near_res = _nearest_resistance(ctx)
        if near_res is None:
            return None
        score = 35
        if ctx.patterns.fvg_up_count >= 3:
            score += 10
        if ctx.order_flow.macro_bias == "BULL":
            score += 10
        score = min(score, 60)

        target_price = ctx.close + (ctx.patterns.fvg_up_dist_atr * ctx.atr)
        setup = _make_setup_long(
            name="LONG FVG magnet (above)",
            entry=ctx.close,
            target=round(target_price, 2),
            ctx=ctx,
            setup_type="scalp",
            conditions_validation=["delta_bar > 0"],
            conditions_invalidation=[],
            confidence="medium",
            rationale="FVG zone above proche - price tend vers inefficience",
        )
        return Scenario(
            name="FVG Magnet UP",
            direction="bullish",
            heuristic_score=score,
            description=(
                f"FVG up active a {ctx.patterns.fvg_up_dist_atr:.2f} ATR "
                f"({ctx.patterns.fvg_up_count} gaps). Convention magnet."
            ),
            key_levels_used=[near_res],
            setups=[setup],
        )

    # FVG zone below (negative dist) -> magnet SHORT si pas macro BULL
    if (ctx.patterns.fvg_dn_count > 0
            and ctx.patterns.fvg_dn_dist_atr is not None
            and -1.0 < ctx.patterns.fvg_dn_dist_atr < 0):
        if ctx.order_flow.macro_bias == "BULL":
            return None
        near_sup = _nearest_support(ctx)
        if near_sup is None:
            return None
        score = 35
        if ctx.patterns.fvg_dn_count >= 3:
            score += 10
        if ctx.order_flow.macro_bias == "BEAR":
            score += 10
        score = min(score, 60)

        target_price = ctx.close + (ctx.patterns.fvg_dn_dist_atr * ctx.atr)
        setup = _make_setup_short(
            name="SHORT FVG magnet (below)",
            entry=ctx.close,
            target=round(target_price, 2),
            ctx=ctx,
            setup_type="scalp",
            conditions_validation=["delta_bar < 0"],
            conditions_invalidation=[],
            confidence="medium",
            rationale="FVG zone below proche - price tend vers inefficience",
        )
        return Scenario(
            name="FVG Magnet DOWN",
            direction="bearish",
            heuristic_score=score,
            description=(
                f"FVG dn active a {ctx.patterns.fvg_dn_dist_atr:.2f} ATR "
                f"({ctx.patterns.fvg_dn_count} gaps). Convention magnet."
            ),
            key_levels_used=[near_sup],
            setups=[setup],
        )

    return None


def _scenario_single_print_magnet(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Single Print Magnet (Steidlmayer - price attracted to single prints).

    Reference : Mind Over Markets Dalton/Steidlmayer. Single prints = zones
    de transition rapide (peu d'acceptance). Marche tend a y revenir pour
    "remplir" l'espace inefficace.

    Trigger : single_prints_present + distance reasonnable.
    """
    if not ctx.patterns.single_prints_present:
        return None
    if ctx.patterns.single_print_dist_atr is None:
        return None
    dist = ctx.patterns.single_print_dist_atr
    if abs(dist) > 1.5:  # Trop loin
        return None

    score = 30
    if ctx.patterns.single_print_density >= 0.5:
        score += 10
    if abs(dist) < 0.5:  # Tres proche
        score += 10
    score = min(score, 55)

    # Direction : single print above = magnet UP, below = magnet DOWN
    if ctx.patterns.single_print_position == "above" and dist > 0:
        target_price = ctx.close + (dist * ctx.atr)
        setup = _make_setup_long(
            name="LONG Single Print magnet",
            entry=ctx.close,
            target=round(target_price, 2),
            ctx=ctx,
            setup_type="scalp",
            conditions_validation=["delta_bar > 0"],
            conditions_invalidation=[],
            confidence="medium",
            rationale="Steidlmayer single print magnet - inefficience a combler",
        )
        return Scenario(
            name="Single Print Magnet LONG",
            direction="bullish",
            heuristic_score=score,
            description=(
                f"Single print zone {dist:.2f} ATR above "
                f"(density {ctx.patterns.single_print_density:.2f}). "
                f"Price tend a y revenir (Steidlmayer)."
            ),
            key_levels_used=[],
            setups=[setup],
        )

    if ctx.patterns.single_print_position == "below" and dist < 0:
        target_price = ctx.close + (dist * ctx.atr)  # dist negatif
        setup = _make_setup_short(
            name="SHORT Single Print magnet",
            entry=ctx.close,
            target=round(target_price, 2),
            ctx=ctx,
            setup_type="scalp",
            conditions_validation=["delta_bar < 0"],
            conditions_invalidation=[],
            confidence="medium",
            rationale="Steidlmayer single print magnet - inefficience a combler",
        )
        return Scenario(
            name="Single Print Magnet SHORT",
            direction="bearish",
            heuristic_score=score,
            description=(
                f"Single print zone {dist:.2f} ATR below "
                f"(density {ctx.patterns.single_print_density:.2f}). "
                f"Price tend a y revenir (Steidlmayer)."
            ),
            key_levels_used=[],
            setups=[setup],
        )

    return None


# ════════════════════════════════════════════════════════════════════════════
# PHASE B v4 LOT A - SCENARIOS MANQUANTS CRITIQUES
# ════════════════════════════════════════════════════════════════════════════
# Audit cross-check 3 agents 12/06 (trading-strategy-analyst + market-analyst
# + audit local) : couverture actuelle ~35% repertoire pro classique. Lot A
# ajoute 5 scenarios prioritaires :
# A1. BN Fired Confluence (souverain Jackson, manuel section 4-5)
# A2. Open Type Driven (Dalton OD/OAIR/OOR - Tier 1 INVENTAIRE)
# A3. IB Break Continuation + Failed Break (21 features Dalton mortes)
# A4. VWAP SD2/SD3 Touch Reversal (12 features bands mortes)
# A5. Holy Grail Raschke (Street Smarts ch.7, WR doc 65-70%)
#
# Anti-PATTERN_11 : chaque scenario MAX 3 conditions DURES dans trigger,
# le reste en bonus score (cf .claude/rules/critical-tasks-review.md).


def _scenario_bn_fired_confluence(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Battle Navale signal fired sur niveau confluence.

    SOUVERAIN JACKSON (MANUEL_EDGE_JACKSON.md section 4-5) :
    "Aucune zone BN ne se trade SEULE. Entree valide = CONFLUENCE multiple
    + NIVEAU SOLIDE". Scoring composite Jackson HVL <=20t (+3), GEX <=15t
    (+2), seuil >=8 = setup valide.

    Trigger (anti-PATTERN_11 = MAX 3 conditions DURES) :
    1. BN signal actif (bn_bull_strength >= 1 OR bn_bear_strength >= 1)
    2. Niveau cluster confluence_count >= 2 dans <= 0.5 ATR
    3. Macro_bias coherent avec direction BN

    Cap 85 (signal souverain Jackson - le SEUL scenario > 75).
    """
    bn_dir = 0
    if ctx.order_flow.bn_bull_strength >= 1:
        bn_dir = +1
    elif ctx.order_flow.bn_bear_strength >= 1:
        bn_dir = -1
    if bn_dir == 0:
        return None

    # Cherche niveau confluence proche (regle souveraine Jackson)
    levels_pool = (ctx.key_levels_resistance[:3] + ctx.key_levels_support[:3]) if bn_dir > 0 else \
                  (ctx.key_levels_support[:3] + ctx.key_levels_resistance[:3])
    confluence_level = None
    for lvl in levels_pool:
        if abs(lvl.distance_atr) <= 0.5 and lvl.confluence_count >= 2:
            confluence_level = lvl
            break
    if confluence_level is None:
        return None

    # Direction-macro alignment check
    if bn_dir > 0:
        if ctx.order_flow.macro_bias == "BEAR":
            return None  # BN bull contre macro bear = piege probable
        targets_pool = [l for l in ctx.key_levels_resistance if l.price > ctx.close]
        sup_lvl = next((l for l in ctx.key_levels_support if l.price < ctx.close), None)
    else:
        if ctx.order_flow.macro_bias == "BULL":
            return None
        targets_pool = [l for l in ctx.key_levels_support if l.price < ctx.close]
        sup_lvl = next((l for l in ctx.key_levels_resistance if l.price > ctx.close), None)
    if not targets_pool:
        return None
    target_lvl = targets_pool[0]
    target_2 = targets_pool[1].price if len(targets_pool) > 1 else None

    # Score base 50 (signal souverain) + bonus orthogonaux
    score = 50
    if confluence_level.confluence_count >= 3:
        score += 15
    if ctx.order_flow.macro_bias == ("BULL" if bn_dir > 0 else "BEAR"):
        score += 10
    if ctx.order_flow.bn_score_raw > 0.5 if bn_dir > 0 else ctx.order_flow.bn_score_raw < -0.5:
        score += 10
    score = min(score, 85)  # cap signal souverain

    side = "long" if bn_dir > 0 else "short"
    factory = _make_setup_long if side == "long" else _make_setup_short
    setup = factory(
        name=f"{side.upper()} BN Fired @ {confluence_level.label}",
        entry=ctx.close,
        target=target_lvl.price,
        ctx=ctx,
        setup_type="swing",
        target_2=target_2,
        # Invalidation : niveau d'invalidation du BON cote (sup_lvl = support
        # sous close pour long / resistance au-dessus pour short, deja calcule).
        # confluence_level est souvent du mauvais cote (resistance au-dessus pour
        # un long) -> 96% fallback ATR (reserve code-reviewer 15/06). sup_lvl est
        # garanti du bon cote de l'entry.
        stop_level=(sup_lvl.price if sup_lvl is not None else None),
        # Confirmation DSL direction-aware : delta + BN score alignes
        conditions_validation=(
            ["delta_bar > 0", "bn_score_raw > 0"] if bn_dir > 0
            else ["delta_bar < 0", "bn_score_raw < 0"]
        ),
        conditions_invalidation=(
            ["bn_score_raw < 0"] if bn_dir > 0 else ["bn_score_raw > 0"]
        ),
        confidence="high",
        rationale=f"BN {('bull' if bn_dir > 0 else 'bear')} strength={ctx.order_flow.bn_bull_strength if bn_dir > 0 else ctx.order_flow.bn_bear_strength} + confluence {confluence_level.confluence_count}",
    )

    return Scenario(
        name=f"BN Fired Confluence {side.upper()}",
        direction="bullish" if bn_dir > 0 else "bearish",
        heuristic_score=score,
        description=(
            f"Battle Navale {('BULL' if bn_dir > 0 else 'BEAR')} strength="
            f"{ctx.order_flow.bn_bull_strength if bn_dir > 0 else ctx.order_flow.bn_bear_strength} "
            f"sur niveau confluence {confluence_level.label} "
            f"({confluence_level.confluence_count}x). Souverain Jackson."
        ),
        key_levels_used=[confluence_level, target_lvl],
        setups=[setup],
    )


def _scenario_open_type_driven(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Open Type Dalton drive direction (Markets in Profile ch.4).

    Trois variantes :
    - OD (Open Drive) : trend day, drive away from open price -> continuation
    - OAIR (Open Auction In Range) : range day, fade extremes -> range bound
    - OAOR (Open Auction Out of Range) : breakout/reversal selon direction

    Restriction time-of-day : OD only us_cash_open + first 30min (Dalton).
    """
    open_relation = ctx.market_structure.open_relation
    open_dir = ctx.market_structure.open_direction
    trend_prob = ctx.market_structure.trend_day_probability

    # OD trend day continuation
    if (ctx.market_structure.open_drive
            and trend_prob > 0.6
            and open_dir != 0):
        # Time restriction : us_cash_open + first 30min only
        if not (ctx.session.is_in_us_cash and ctx.session.mins_et is not None
                and 570 <= ctx.session.mins_et <= 600):  # 09:30-10:00 ET
            return None

        score = 45
        if ctx.market_structure.open_bias_conf >= 0.7:
            score += 15
        if ctx.order_flow.macro_bias == ("BULL" if open_dir > 0 else "BEAR"):
            score += 10
        score = min(score, 70)

        if open_dir > 0:
            near_res = _nearest_resistance(ctx)
            near_sup = _nearest_support(ctx)
            if near_res is None or near_sup is None:
                return None
            setup = _make_setup_long(
                name="LONG Open Drive",
                entry=ctx.close,
                target=near_res.price,
                ctx=ctx,
                setup_type="swing",
                target_2=ctx.key_levels_resistance[1].price if len(ctx.key_levels_resistance) > 1 else None,
                # Invalidation Dalton : un Open Drive ne retrace pas a l'open cash.
                stop_level=ctx.open_cash,
                conditions_validation=["delta_bar > 0"],
                conditions_invalidation=[],
                confidence="high" if score >= 60 else "medium",
                rationale=f"Dalton Open Drive UP + trend_prob {trend_prob:.2f}",
            )
            return Scenario(
                name="Open Drive LONG (Dalton)",
                direction="bullish",
                heuristic_score=score,
                description=f"Open Drive UP detected, trend_day_prob {trend_prob:.2f}, us_cash first 30min",
                key_levels_used=[near_sup, near_res],
                setups=[setup],
            )

        # SHORT
        near_sup = _nearest_support(ctx)
        if near_sup is None:
            return None
        setup = _make_setup_short(
            name="SHORT Open Drive",
            entry=ctx.close,
            target=near_sup.price,
            ctx=ctx,
            setup_type="swing",
            target_2=ctx.key_levels_support[1].price if len(ctx.key_levels_support) > 1 else None,
            # Invalidation Dalton : un Open Drive ne retrace pas a l'open cash.
            stop_level=ctx.open_cash,
            conditions_validation=["delta_bar < 0"],
            conditions_invalidation=[],
            confidence="high" if score >= 60 else "medium",
            rationale=f"Dalton Open Drive DOWN + trend_prob {trend_prob:.2f}",
        )
        return Scenario(
            name="Open Drive SHORT (Dalton)",
            direction="bearish",
            heuristic_score=score,
            description=f"Open Drive DOWN detected, trend_day_prob {trend_prob:.2f}, us_cash first 30min",
            key_levels_used=[near_sup],
            setups=[setup],
        )

    return None


def _scenario_ib_break(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Initial Balance Break (Dalton Markets in Profile ch.6).

    Range Extension probability documente 65-70% apres cassure IB (Dalton
    p.187 Markets in Profile + Mind Over Markets 2007). Setup classique :
    IB etroite + cassure direction + volume.

    Targets Dalton (IB extension en POINTS) :
    - target_1 = 0.5x IB range au-dela du break (partial profit)
    - target_2 = 1.0x IB range au-dela du break (full move)
    - stop    = retour dans IB (ib_low pour LONG / ib_high pour SHORT) - 0.1 ATR buffer

    FIX 12/06 (audit market-analyst + cross-check empirique 32K trades 0% hit) :
    Ancienne version multipliait `ib_range_atr * 1.5 * atr` -> target a 22-31 ATR
    (mediane) = INATTEIGNABLE. ib_range_atr est deja un RATIO normalise par ATR,
    multiplier encore par ATR = double normalisation. Cause racine PATTERN_11
    sur edge Dalton (cf incident Plan C 27/05 meme famille bug units).

    Reference : Dalton "Markets in Profile" ch.6 p.187 "Extension = 1x IB range".
    """
    if not ctx.market_structure.ib_complete:
        return None
    if not (ctx.market_structure.ib_broken_up or ctx.market_structure.ib_broken_down):
        return None
    if ctx.market_structure.ib_high is None or ctx.market_structure.ib_low is None:
        return None

    # Direction
    is_up = ctx.market_structure.ib_broken_up
    ib_h = ctx.market_structure.ib_high
    ib_l = ctx.market_structure.ib_low
    ib_range_pts = ib_h - ib_l  # POINTS (pas ratio)
    if ib_range_pts <= 0:
        return None

    score = 35
    if ctx.market_structure.ib_is_narrow:
        score += 15  # Compression release favorable
    if ctx.order_flow.macro_bias == ("BULL" if is_up else "BEAR"):
        score += 10
    if abs(ctx.order_flow.cvd_session) > 200:
        score += 10
    score = min(score, 70)

    if is_up:
        # Target Dalton : ib_high + N * ib_range_POINTS (pas multiples ATR)
        target_1_price = ib_h + 0.5 * ib_range_pts  # partial profit (0.5x extension)
        target_2_price = ib_h + 1.0 * ib_range_pts  # full move Dalton (1x extension)
        # Stop STRUCTUREL (Dalton) : invalidation = retour sous ib_high (le
        # niveau casse devenu support). Coherence d'horizon avec target Dalton.
        # Pas de stop ATR 1min (asymetrie d'horizon -> RR gonfle).
        setup = _make_setup_long(
            name="LONG IB Break Continuation",
            entry=ctx.close,
            target=round(target_1_price, 2),
            ctx=ctx,
            setup_type="swing",
            target_2=round(target_2_price, 2),
            stop_level=ib_h,
            conditions_validation=["delta_bar > 0", "ib_broken_up == 1"],
            conditions_invalidation=[],
            confidence="high" if score >= 60 else "medium",
            rationale=f"IB broken_up, ib_range={ib_range_pts:.1f}pts, narrow={ctx.market_structure.ib_is_narrow}",
        )
        return Scenario(
            name="IB Break Continuation LONG (Dalton)",
            direction="bullish",
            heuristic_score=score,
            description=f"IB broken UP. Target_1 = ib_high + 0.5x range = {target_1_price:.1f}, target_2 = ib_high + 1.0x range = {target_2_price:.1f} (Dalton)",
            key_levels_used=ctx.key_levels_resistance[:2],
            setups=[setup],
        )

    # SHORT
    target_1_price = ib_l - 0.5 * ib_range_pts
    target_2_price = ib_l - 1.0 * ib_range_pts
    setup = _make_setup_short(
        name="SHORT IB Break Continuation",
        entry=ctx.close,
        target=round(target_1_price, 2),
        ctx=ctx,
        setup_type="swing",
        target_2=round(target_2_price, 2),
        stop_level=ib_l,
        conditions_validation=["delta_bar < 0", "ib_broken_down == 1"],
        conditions_invalidation=[],
        confidence="high" if score >= 60 else "medium",
        rationale=f"IB broken_down, ib_range={ib_range_pts:.1f}pts, narrow={ctx.market_structure.ib_is_narrow}",
    )
    return Scenario(
        name="IB Break Continuation SHORT (Dalton)",
        direction="bearish",
        heuristic_score=score,
        description=f"IB broken DOWN. Target_1 = ib_low - 0.5x range = {target_1_price:.1f}, target_2 = ib_low - 1.0x range = {target_2_price:.1f} (Dalton)",
        key_levels_used=ctx.key_levels_support[:2],
        setups=[setup],
    )


def _scenario_vwap_sd_touch_reversal(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : VWAP SD2/SD3 touch = exhaustion reversal (statistical edge).

    VWAP SD bands = ecart standard. Touch SD2 = 5% statistique, SD3 = 0.3%.
    Reference : Brett Steenbarger statistical edges + mean reversion regime
    Dim/Eraker/Vilkov 2024.

    Trigger : price <= 0.10 ATR de vwap_d_sd2u/d ou sd3u/d + divergence signal.
    """
    if ctx.atr <= 0:
        return None

    # Touch SD3 upper -> SHORT exhaustion
    if ctx.vwap_d_sd3u is not None and ctx.close >= ctx.vwap_d_sd3u - 0.1 * ctx.atr:
        sd_level = ctx.vwap_d_sd3u
        near_sup = _nearest_support(ctx)
        if near_sup is None or ctx.vwap_d is None:
            return None
        score = 40  # SD3 = 0.3% statistique = edge fort
        if ctx.order_flow.delta_div_event < 0:  # divergence bearish
            score += 15
        if ctx.order_flow.finish_strength < 0:
            score += 10
        score = min(score, 65)
        setup = _make_setup_short(
            name="SHORT VWAP SD3 Exhaustion",
            entry=ctx.close,
            target=ctx.vwap_d,
            ctx=ctx,
            setup_type="swing",
            target_2=near_sup.price,
            # Invalidation Steenbarger : acceptance au-dela de la bande SD3 =
            # exhaustion refutee. Buffer 0.5 (bandes SD percees a la meche).
            stop_level=sd_level,
            stop_buffer_atr=0.5,
            conditions_validation=["delta_div_strength < 0", "finish_strength < 0"],
            conditions_invalidation=[],
            confidence="high" if score >= 55 else "medium",
            rationale=f"VWAP SD3 upper touch @ {sd_level:.2f}, 0.3% statistique exhaustion",
        )
        return Scenario(
            name="VWAP SD3 Touch Reversal SHORT",
            direction="bearish",
            heuristic_score=score,
            description=f"Price touche VWAP +3 SD ({sd_level:.2f}), exhaustion stat. Target = VWAP day.",
            key_levels_used=[near_sup],
            setups=[setup],
        )

    # Touch SD3 lower -> LONG exhaustion
    if ctx.vwap_d_sd3d is not None and ctx.close <= ctx.vwap_d_sd3d + 0.1 * ctx.atr:
        sd_level = ctx.vwap_d_sd3d
        near_res = _nearest_resistance(ctx)
        if near_res is None or ctx.vwap_d is None:
            return None
        score = 40
        if ctx.order_flow.delta_div_event > 0:
            score += 15
        if ctx.order_flow.finish_strength > 0:
            score += 10
        score = min(score, 65)
        setup = _make_setup_long(
            name="LONG VWAP SD3 Exhaustion",
            entry=ctx.close,
            target=ctx.vwap_d,
            ctx=ctx,
            setup_type="swing",
            target_2=near_res.price,
            # Invalidation Steenbarger : acceptance sous la bande SD3. Buffer 0.5.
            stop_level=sd_level,
            stop_buffer_atr=0.5,
            conditions_validation=["delta_div_strength > 0", "finish_strength > 0"],
            conditions_invalidation=[],
            confidence="high" if score >= 55 else "medium",
            rationale=f"VWAP SD3 lower touch @ {sd_level:.2f}, 0.3% statistique exhaustion",
        )
        return Scenario(
            name="VWAP SD3 Touch Reversal LONG",
            direction="bullish",
            heuristic_score=score,
            description=f"Price touche VWAP -3 SD ({sd_level:.2f}), exhaustion stat. Target = VWAP day.",
            key_levels_used=[near_res],
            setups=[setup],
        )

    # SD2 plus frequent mais score plus bas (5% statistique)
    if ctx.vwap_d_sd2u is not None and ctx.close >= ctx.vwap_d_sd2u - 0.1 * ctx.atr \
            and (ctx.vwap_d_sd3u is None or ctx.close < ctx.vwap_d_sd3u - 0.1 * ctx.atr):
        sd_level = ctx.vwap_d_sd2u
        near_sup = _nearest_support(ctx)
        if near_sup is None or ctx.vwap_d is None:
            return None
        score = 30
        if ctx.order_flow.delta_div_event < 0:
            score += 15
        score = min(score, 55)
        setup = _make_setup_short(
            name="SHORT VWAP SD2 Touch",
            entry=ctx.close,
            target=ctx.vwap_d,
            ctx=ctx,
            # Reclasse scalp->swing (target=vwap_d ~2 SD = horizon swing, pas scalp).
            setup_type="swing",
            stop_level=sd_level,
            stop_buffer_atr=0.5,
            conditions_validation=["delta_div_strength < 0"],
            conditions_invalidation=[],
            confidence="medium",
            rationale=f"VWAP SD2 upper touch @ {sd_level:.2f}",
        )
        return Scenario(
            name="VWAP SD2 Touch Reversal SHORT",
            direction="bearish",
            heuristic_score=score,
            description=f"VWAP +2 SD touche ({sd_level:.2f}), 5% statistique scalp.",
            key_levels_used=[near_sup],
            setups=[setup],
        )

    if ctx.vwap_d_sd2d is not None and ctx.close <= ctx.vwap_d_sd2d + 0.1 * ctx.atr \
            and (ctx.vwap_d_sd3d is None or ctx.close > ctx.vwap_d_sd3d + 0.1 * ctx.atr):
        sd_level = ctx.vwap_d_sd2d
        near_res = _nearest_resistance(ctx)
        if near_res is None or ctx.vwap_d is None:
            return None
        score = 30
        if ctx.order_flow.delta_div_event > 0:
            score += 15
        score = min(score, 55)
        setup = _make_setup_long(
            name="LONG VWAP SD2 Touch",
            entry=ctx.close,
            target=ctx.vwap_d,
            ctx=ctx,
            # Reclasse scalp->swing (target=vwap_d ~2 SD = horizon swing, pas scalp).
            setup_type="swing",
            stop_level=sd_level,
            stop_buffer_atr=0.5,
            conditions_validation=["delta_div_strength > 0"],
            conditions_invalidation=[],
            confidence="medium",
            rationale=f"VWAP SD2 lower touch @ {sd_level:.2f}",
        )
        return Scenario(
            name="VWAP SD2 Touch Reversal LONG",
            direction="bullish",
            heuristic_score=score,
            description=f"VWAP -2 SD touche ({sd_level:.2f}), 5% statistique scalp.",
            key_levels_used=[near_res],
            setups=[setup],
        )

    return None


def _scenario_holy_grail(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Holy Grail Raschke (Street Smarts ch.7, WR doc 65-70%).

    Original ADX>30 + pullback to 20-EMA. Sans ADX en feature, proxy via :
    - trend_day_probability > 0.5 (trend regime)
    - Pullback proche VWAP day (proxy 20-EMA)
    - Macro bias aligne avec trend direction

    Restriction time-of-day : preferentiel us_cash 10:00-15:30 ET.
    """
    if ctx.atr <= 0 or ctx.vwap_d is None:
        return None
    if ctx.market_structure.trend_day_probability < 0.5:
        return None

    # Time-of-day boost : us_cash session ideale
    in_us_session = (ctx.session.is_in_us_cash and ctx.session.mins_et is not None
                     and 600 <= ctx.session.mins_et <= 930)  # 10:00-15:30 ET
    if not in_us_session and ctx.session.current_segment not in ("london",):
        return None  # Pas de Holy Grail hors London/US_cash power session

    # Direction trend
    if ctx.order_flow.macro_bias == "BULL":
        side = "long"
        # Pullback proche VWAP day = entry zone (proxy 20-EMA)
        dist_vwap_atr = (ctx.close - ctx.vwap_d) / ctx.atr
        if not (-0.1 <= dist_vwap_atr <= 0.5):  # Pullback en cours
            return None
        near_res = _nearest_resistance(ctx)
        if near_res is None:
            return None
        target = near_res.price
        entry = ctx.close
    elif ctx.order_flow.macro_bias == "BEAR":
        side = "short"
        dist_vwap_atr = (ctx.close - ctx.vwap_d) / ctx.atr
        if not (-0.5 <= dist_vwap_atr <= 0.1):
            return None
        near_sup = _nearest_support(ctx)
        if near_sup is None:
            return None
        target = near_sup.price
        entry = ctx.close
    else:
        return None

    score = 50  # Base Holy Grail (Raschke WR doc 65-70%)
    if ctx.market_structure.trend_day_probability >= 0.7:
        score += 15
    if in_us_session:
        score += 10
    if ctx.vwap_triple_align == 1:
        score += 5  # Triple VWAP alignment renforce trend
    score = min(score, 75)

    factory = _make_setup_long if side == "long" else _make_setup_short
    # Invalidation Raschke (Street Smarts ch.7) : le stop va sous le SWING LOW du
    # pullback (long) / au-dessus du swing high (short), PAS a la VWAP day. La
    # VWAP day (proxy 20-EMA) est la zone d'ENTREE, pas l'invalidation : y placer
    # le stop = stop a l'entree (faux corrige 15/06 sur verdict market-analyst).
    hg_stop = ctx.swing_low if side == "long" else ctx.swing_high
    setup = factory(
        name=f"{side.upper()} Holy Grail Raschke",
        entry=entry,
        target=target,
        ctx=ctx,
        setup_type="swing",
        stop_level=hg_stop,
        # Confirmation reprise de tendance post-pullback (side-aware)
        conditions_validation=(
            ["delta_bar > 0", "finish_strength > 0"] if side == "long"
            else ["delta_bar < 0", "finish_strength < 0"]
        ),
        conditions_invalidation=[],
        confidence="high" if score >= 65 else "medium",
        rationale=f"Raschke Holy Grail (Street Smarts ch.7) - trend_prob {ctx.market_structure.trend_day_probability:.2f} + pullback VWAP",
    )
    return Scenario(
        name=f"Holy Grail Raschke {side.upper()}",
        direction="bullish" if side == "long" else "bearish",
        heuristic_score=score,
        description=(
            f"Raschke Holy Grail {side.upper()} : trend_day_prob "
            f"{ctx.market_structure.trend_day_probability:.2f} + pullback VWAP day. "
            f"Target {target:.2f}."
        ),
        key_levels_used=[],
        setups=[setup],
    )


# ════════════════════════════════════════════════════════════════════════════
# LOT 4 - BACKLOG PLACEHOLDERS (a calibrer Phase C post-data)
# ════════════════════════════════════════════════════════════════════════════

def is_high_impact_eco_event_imminent(ctx: NarrativeContext,
                                      lookahead_minutes: int = 30) -> bool:
    """Placeholder : detecte si event eco impact >=2 attendu < N min.

    BACKLOG Phase C : integration calendrier eco (forexfactory / TE).
    Si True, downstream devrait drop tous scenarios (volatilite imprevisible).

    Pour l'instant retourne toujours False (no-op). A implementer apres
    integration calendrier eco JSONL (cf project_backlog_ui_animations.md).
    """
    _ = (ctx, lookahead_minutes)  # silence linter
    return False


def get_multi_timeframe_alignment(ctx: NarrativeContext) -> dict:
    """Placeholder : alignement multi-TF (5m / 15m / 1h).

    BACKLOG Phase C : necessite acces JSONL multi-TF agreges.
    Reference Dalton/Steidlmayer : timeframe superieur force direction.

    Returns dict vide pour l'instant.
    """
    _ = ctx
    return {}


def get_cross_instrument_state(ctx: NarrativeContext) -> dict:
    """Placeholder : cross-instrument ES/NQ correlation state.

    BACKLOG Phase C : necessite acces simultane aux 2 NarrativeContext.
    Reference feedback_cross_instrument_bonus_not_gate.md (24/04) :
    cross-instrument = BONUS/MALUS de score, JAMAIS gate bloquant.

    Returns dict vide pour l'instant.
    """
    _ = ctx
    return {}


def _apply_vix_regime_filter(scenarios: list, ctx: NarrativeContext) -> list:
    """Lot 4 : Drop scenarios incompatibles avec regime VIX courant.

    Reference Vilkov/Dimitrov 2024 (feedback_regime_gex_finding.md) :
    - VIX extreme (>35) : range + FVG + continuation incoherents
      (mean reversion domine, range explose)
    - VIX stressed (25-35) : FVG fill peu fiable (volatilite tue precision)
    - VIX calm_vix_low (<15) : Single Print Magnet inefficace (pas fast moves)

    Filtre DROP via prefix matching (re-review 12/06 v2 : bug exact-match
    "FVG Fill (up)" jamais detecte par "FVG Fill"), n'AJUSTE PAS
    heuristic_score (anti-PATTERN_11).
    """
    regime = ctx.macro_regime
    prefixes = VIX_INCOMPATIBLE_PREFIXES.get(regime, ())
    if not prefixes:
        return scenarios
    filtered = [
        s for s in scenarios
        if not any(s.name.startswith(p) for p in prefixes)
    ]
    dropped = len(scenarios) - len(filtered)
    if dropped > 0:
        _LOG.debug("VIX regime %s : %d scenarios filtres (prefixes=%s)",
                   regime, dropped, prefixes)
    return filtered


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE
# ════════════════════════════════════════════════════════════════════════════

_BUILDERS: list[Callable[[NarrativeContext], Optional[Scenario]]] = [
    # Phase B v4 Lot A - PRIORITAIRES (souverains / Tier 1)
    _scenario_bn_fired_confluence,      # A1 (souverain Jackson, cap 85)
    _scenario_open_type_driven,         # A2 (Dalton Tier 1)
    _scenario_ib_break,                 # A3 (Dalton range extension)
    _scenario_vwap_sd_touch_reversal,   # A4 (12 features SD bands)
    _scenario_holy_grail,               # A5 (Raschke WR 65-70%)
    # Phase B v3 - scenarios existants
    _scenario_bullish_continuation,
    _scenario_bearish_rejection,
    _scenario_range_bound_long_fade,    # Lot 1 split
    _scenario_range_bound_short_fade,   # Lot 1 split
    _scenario_judas_reversal,
    _scenario_failed_breakout,          # Lot 3
    _scenario_fvg_magnet,               # Lot 3 (rename v3 : magnet convention)
    _scenario_single_print_magnet,      # Lot 3
]


def _apply_vix_score_adjustments(scenarios: list, ctx: NarrativeContext) -> list:
    """Phase B v4 Lot D : boost/penalize heuristic_score selon regime VIX.

    Reference Vilkov/Dimitrov 2024 + Williams VSA regime behavior.
    Anti-PATTERN_11 : adjustment +/- score, JAMAIS gate cascadante.
    Le filtre VIX_INCOMPATIBLE_PREFIXES (DROP) reste actif en amont.
    """
    regime = ctx.macro_regime
    adjustments = VIX_SCORE_ADJUSTMENTS.get(regime, {})
    if not adjustments:
        return scenarios
    for sc in scenarios:
        for prefix, delta in adjustments.items():
            if sc.name.startswith(prefix):
                sc.heuristic_score = max(0, min(100, sc.heuristic_score + delta))
                break  # 1 seul ajustement par scenario
    return scenarios


def _apply_douglas_filter(scenarios: list) -> list:
    """Phase B v4 Lot C : filtre pro-Douglas consistency.

    Mark Douglas "Trading in the Zone" : trader pro = 1-2 setups maitrise.
    1. Drop low-conviction (heuristic_score < MIN_SCORE_FILTER)
    2. Cap N <= MAX_SCENARIOS_PER_BAR
    3. Tag primary=True sur top-1

    Anti-PATTERN_11 : seuils statiques fixes, pas dynamiques VIX-based
    (eviterait de fabriquer une proba calibree).
    """
    filtered = [s for s in scenarios if s.heuristic_score >= MIN_SCORE_FILTER]
    filtered.sort(key=lambda s: -s.heuristic_score)
    filtered = filtered[:MAX_SCENARIOS_PER_BAR]
    if filtered:
        filtered[0].primary = True
    return filtered


def generate_scenarios(ctx: NarrativeContext, apply_filter: bool = True) -> list:
    """Genere N scenarios heuristiques depuis NarrativeContext.

    ATTENTION : heuristic_score n'est PAS une probabilite calibree.
    Tant qu'aucune calibration empirique (Platt scaling Lopez AFML ch.13)
    n'est realisee sur 30j+ outcomes, NE PAS sizer sur ce score.

    Args:
        ctx : NarrativeContext extrait par build_narrative_context()
        apply_filter : Phase B v4 Lot C - applique filtre Douglas
            (score>=MIN_SCORE_FILTER, max MAX_SCENARIOS_PER_BAR, primary tag).
            False pour dashboard "voir tout" ou tests low-score builders.

    Returns:
        List[Scenario] sortee par heuristic_score descending, filtree VIX.
        Si apply_filter=False : tous les scenarios (utile UI debug).
    """
    # Lot 4 : bloquer si event eco majeur imminent
    if is_high_impact_eco_event_imminent(ctx):
        _LOG.info("Event eco imminent - aucun scenario emis")
        return []

    scenarios = []
    for builder in _BUILDERS:
        try:
            sc = builder(ctx)
            if sc is not None:
                scenarios.append(sc)
        except Exception as exc:  # noqa: BLE001
            # Fail-soft : un builder qui crash ne casse pas les autres,
            # mais on log avec le nom du builder (anti-VALIDATION_MISS).
            _LOG.warning("scenario_builder %s a crash: %s",
                         builder.__name__, exc)

    # Lot 4 : filtre regime VIX (DROP incompatibles) - toujours actif
    scenarios = _apply_vix_regime_filter(scenarios, ctx)

    # Phase B v4 Lot D : adjustment VIX score (boost/penalize) - toujours actif
    scenarios = _apply_vix_score_adjustments(scenarios, ctx)

    if apply_filter:
        # Phase B v4 Lot C : filtre Douglas (score>=55, max 3, primary tag)
        scenarios = _apply_douglas_filter(scenarios)
    else:
        scenarios.sort(key=lambda s: -s.heuristic_score)

    return scenarios
