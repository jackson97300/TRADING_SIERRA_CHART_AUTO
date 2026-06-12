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

# VIX regime filter - drop scenarios incompatibles avec regime courant.
# Reference : Vilkov/Dimitrov 2024 (cf feedback_regime_gex_finding.md).
# Re-review market-analyst 12/06 v2 : ajout Bullish continuation en extreme
# (mean reversion domine en VIX>35) + Single Print Magnet en calm (pas de
# fast moves donc magnet inefficace).
# Re-review code-reviewer 12/06 v2 : filtre par prefix matching pour couvrir
# les noms scenarios variantes (ex: "FVG Magnet UP" + "FVG Magnet DOWN").
VIX_INCOMPATIBLE_PREFIXES = {
    "extreme": ("Range bound", "FVG Magnet", "Bullish continuation"),
    "stressed": ("FVG Magnet",),
    "calm_vix_low": ("Single Print Magnet",),
    "calm": (),
    "elevated": (),
    "UNKNOWN": (),
}


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
                     confidence: str = "medium", rationale: str = "") -> TradingSetup:
    """Factory LONG setup avec stops calibres.

    R:R calcule sur target_2 si swing + disponible (full move), sinon target_1.
    """
    stop_frac = _stop_distance_atr(setup_type)
    stop = entry - stop_frac * ctx.atr
    rr_target = _rr_base_target(target, target_2, setup_type)
    return TradingSetup(
        name=name, side="long",
        entry_price=entry,
        entry_zone_low=entry - ENTRY_ZONE_ATR_FRAC * ctx.atr,
        entry_zone_high=entry + ENTRY_ZONE_ATR_FRAC * ctx.atr,
        target_1=target, target_2=target_2,
        stop_loss=round(stop, 2),
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
                      confidence: str = "medium", rationale: str = "") -> TradingSetup:
    """Factory SHORT setup avec stops calibres.

    R:R calcule sur target_2 si swing + disponible (full move), sinon target_1.
    """
    stop_frac = _stop_distance_atr(setup_type)
    stop = entry + stop_frac * ctx.atr
    rr_target = _rr_base_target(target, target_2, setup_type)
    return TradingSetup(
        name=name, side="short",
        entry_price=entry,
        entry_zone_low=entry - ENTRY_ZONE_ATR_FRAC * ctx.atr,
        entry_zone_high=entry + ENTRY_ZONE_ATR_FRAC * ctx.atr,
        target_1=target, target_2=target_2,
        stop_loss=round(stop, 2),
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

    # Score heuristique non-calibre
    score = 30
    if ctx.market_structure.profile_shape == "P":  # acceptance haut
        score += 15
    if (ctx.market_structure.open_relation == "OAOR"
            and ctx.market_structure.range_pos_va_pct > 0.7):  # acceptance haute VA
        score += 10
    if ctx.session.judas_swing_direction == 1:
        score += 10
    score = min(score, 75)

    setup = _make_setup_long(
        name=f"LONG pullback {near_sup.label}",
        entry=near_sup.price,
        target=near_res.price,
        ctx=ctx,
        setup_type="swing",
        target_2=ctx.key_levels_resistance[1].price if len(ctx.key_levels_resistance) > 1 else None,
        conditions_validation=[
            "Rebond confirme sur support (close > entry + 0.2 ATR)",
            "Delta_bar > 0 sur la bar du rebond",
            "BN absorb_bid > 0 OU bn_long_up = 1",
            "finish_strength > 0",
        ],
        conditions_invalidation=[
            "Stop touche (entry - 0.8 ATR)",
            "Cassure support avec volume > 2x average",
            "Delta day passe NEUTRAL ou BEAR",
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
        conditions_validation=[
            "Rejet confirme (long wick haut > 0.3 ATR)",
            "Delta_bar < 0 sur la bar de rejet",
            "BN absorb_ask > 0 OU bn_long_dn = 1",
            "finish_strength < 0",
            f"Confluence {major_res.confluence_count} niveaux superposes",
        ],
        conditions_invalidation=[
            "Stop touche (entry + 0.8 ATR)",
            f"Cassure {major_res.label} avec volume > 2x average",
            "Delta day reste BULL fort",
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
    score = 35
    if ctx.market_structure.day_type == "NormVar":
        score += 10
    score = min(score, 60)
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
        conditions_validation=[
            "Touch support + delta+ + finish_strength +",
            "BN absorb_bid > 0 OU bn_long_up = 1",
        ],
        conditions_invalidation=["Cassure support avec volume > 2x average"],
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
        conditions_validation=[
            "Touch resistance + delta- + finish_strength -",
            "BN absorb_ask > 0 OU bn_long_dn = 1",
        ],
        conditions_invalidation=["Cassure resistance avec volume > 2x average"],
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
    """Scenario : Judas Swing detected -> reversal vraie direction."""
    if not ctx.patterns.judas_swing_active:
        return None
    direction = ctx.session.judas_swing_direction
    if direction == 0:
        return None

    score = 50  # Judas detected = signal fort (non-calibre)
    if ctx.order_flow.bn_signals_active:
        score += 10
    score = min(score, 75)

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
            conditions_validation=["Continuation UP confirme post-Judas detected"],
            conditions_invalidation=["Retour direction first hour London"],
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
        conditions_validation=["Continuation DOWN confirme post-Judas detected"],
        conditions_invalidation=["Retour direction first hour London"],
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
        score = min(score, 65)

        setup = _make_setup_long(
            name="LONG Spring (failed breakdown)",
            entry=ctx.close,
            target=near_res.price,
            ctx=ctx,
            setup_type="swing",
            conditions_validation=[
                "Close > entry sur bar suivante (acceptance reverse)",
                "Delta_bar > 0 + finish_strength > 0",
                "BN absorb_bid > 0 (smart money LONG)",
            ],
            conditions_invalidation=[
                "Re-cassure low avec volume",
                "Stop touche (entry - 0.8 ATR)",
            ],
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
        score = min(score, 65)

        setup = _make_setup_short(
            name="SHORT UTAD (failed breakout)",
            entry=ctx.close,
            target=near_sup.price,
            ctx=ctx,
            setup_type="swing",
            conditions_validation=[
                "Close < entry sur bar suivante (acceptance reverse)",
                "Delta_bar < 0 + finish_strength < 0",
                "BN absorb_ask > 0 (smart money SHORT)",
            ],
            conditions_invalidation=[
                "Re-cassure high avec volume",
                "Stop touche (entry + 0.8 ATR)",
            ],
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
            conditions_validation=[
                "Continuation UP avec delta+",
                "Pas de rejection sur niveau intermediaire",
            ],
            conditions_invalidation=["Reversal BEAR avec volume"],
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
            conditions_validation=[
                "Continuation DOWN avec delta-",
                "Pas de bounce sur niveau intermediaire",
            ],
            conditions_invalidation=["Reversal BULL avec volume"],
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
            conditions_validation=[
                "Acceleration UP vers single print zone",
                "Pas de niveau majeur intermediaire",
            ],
            conditions_invalidation=["Reversal vers cur_vpoc"],
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
            conditions_validation=[
                "Acceleration DOWN vers single print zone",
                "Pas de niveau majeur intermediaire",
            ],
            conditions_invalidation=["Reversal vers cur_vpoc"],
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
    _scenario_bullish_continuation,
    _scenario_bearish_rejection,
    _scenario_range_bound_long_fade,    # Lot 1 split
    _scenario_range_bound_short_fade,   # Lot 1 split
    _scenario_judas_reversal,
    _scenario_failed_breakout,          # Lot 3
    _scenario_fvg_magnet,               # Lot 3 (rename v3 : magnet convention)
    _scenario_single_print_magnet,      # Lot 3
]


def generate_scenarios(ctx: NarrativeContext) -> list:
    """Genere N scenarios heuristiques depuis NarrativeContext.

    ATTENTION : heuristic_score n'est PAS une probabilite calibree.
    Tant qu'aucune calibration empirique (Platt scaling Lopez AFML ch.13)
    n'est realisee sur 30j+ outcomes, NE PAS sizer sur ce score.

    Args:
        ctx : NarrativeContext extrait par build_narrative_context()

    Returns:
        List[Scenario] sortee par heuristic_score descending, filtree VIX.
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

    # Lot 4 : filtre regime VIX
    scenarios = _apply_vix_regime_filter(scenarios, ctx)

    # Sort par score descending
    scenarios.sort(key=lambda s: -s.heuristic_score)
    return scenarios
