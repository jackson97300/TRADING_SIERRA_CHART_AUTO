"""scenario_generator.py - Generateur de scenarios dynamiques marche.

Consume NarrativeContext (CORE/narrative_engine.py) et produit 3-4 scenarios
probabilistiques avec setups conditionnels.

# Principe ANTI-PATTERN_11

Les scenarios sont des OBSERVATIONS PROBABILISTIQUES.
PAS de hardcoded gates, PAS de decisions automatiques.

Le ML / strategy downstream consomme la List[Scenario] et decide
quel scenario suivre + quand entrer.

# Architecture

Scenario contient :
  - name, direction (bullish/bearish/range)
  - probability_pct (heuristique base sur context)
  - key_levels_used (references vers NarrativeContext.key_levels)
  - setups : List[TradingSetup] conditionnels

TradingSetup contient :
  - side, entry_price, entry_zone, target_1/2, stop_loss
  - r_r_ratio calcul
  - conditions_validation : List[str] (e.g. "BN absorb_bid > 0")
  - conditions_invalidation : List[str]
  - confidence : low/medium/high
  - rationale : explication concise

Auteur : MIA Trading V5 Phase B scenario generator
Date   : 2026-06-12
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from CORE.narrative_engine import KeyLevel, NarrativeContext


# ════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class TradingSetup:
    """Setup trading conditionnel."""
    name: str
    side: str  # "long" / "short"
    entry_price: float
    entry_zone_low: float
    entry_zone_high: float
    target_1: float
    target_2: Optional[float]
    stop_loss: float
    r_r_ratio: float
    conditions_validation: list = field(default_factory=list)
    conditions_invalidation: list = field(default_factory=list)
    confidence: str = "medium"  # "low" / "medium" / "high"
    rationale: str = ""


@dataclass
class Scenario:
    """Scenario directionnel probabilistique."""
    name: str
    direction: str  # "bullish" / "bearish" / "range"
    probability_pct: int  # estimation heuristique 0-100
    description: str
    key_levels_used: list = field(default_factory=list)  # List[KeyLevel] references
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


# ════════════════════════════════════════════════════════════════════════════
# SCENARIO BUILDERS
# ════════════════════════════════════════════════════════════════════════════

def _scenario_bullish_continuation(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : continuation bull (macro bias BULL + structure favorable)."""
    if ctx.order_flow.macro_bias != "BULL":
        return None
    near_res = _nearest_resistance(ctx)
    near_sup = _nearest_support(ctx)
    if near_res is None or near_sup is None:
        return None

    # Probabilite heuristique
    proba = 30
    if ctx.market_structure.profile_shape == "P":  # acceptance haut
        proba += 15
    if ctx.market_structure.open_relation == "OAOR" and ctx.close > ctx.market_structure.range_pos_va_pct:
        proba += 10
    if ctx.session.judas_swing_direction == 1:
        proba += 10
    proba = min(proba, 75)

    # Setup LONG pullback sur support proche
    setup_entry = near_sup.price
    setup_target = near_res.price
    setup_stop = setup_entry - 0.3 * ctx.atr
    rr = _compute_r_r(setup_entry, setup_target, setup_stop, "long")

    setup = TradingSetup(
        name=f"LONG pullback {near_sup.label}",
        side="long",
        entry_price=setup_entry,
        entry_zone_low=setup_entry - 0.1 * ctx.atr,
        entry_zone_high=setup_entry + 0.1 * ctx.atr,
        target_1=setup_target,
        target_2=ctx.key_levels_resistance[1].price if len(ctx.key_levels_resistance) > 1 else None,
        stop_loss=round(setup_stop, 2),
        r_r_ratio=rr,
        conditions_validation=[
            "Rebond confirme sur support (close > entry + 0.2 ATR)",
            "Delta_bar > 0 sur la bar du rebond",
            "BN absorb_bid > 0 OU bn_long_up = 1",
            "finish_strength > 0",
        ],
        conditions_invalidation=[
            f"Close < {round(setup_stop, 2)} (stop touche)",
            "Cassure support avec volume > 2x average",
            "Delta day passe NEUTRAL ou BEAR",
        ],
        confidence="high" if proba >= 60 else "medium",
        rationale=f"Macro BULL (CVD day {ctx.order_flow.cvd_day:+d}), pullback opportuniste sur {near_sup.label}",
    )

    return Scenario(
        name="Bullish continuation",
        direction="bullish",
        probability_pct=proba,
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
    """Scenario : rejection majeur resistance (test + reject)."""
    major_res = _major_resistance(ctx)
    if major_res is None:
        return None
    # Considere resistance majeure si confluence >= 2 ET proche
    if major_res.confluence_count < 2 and major_res.distance_atr > 1.5:
        return None

    # Probabilite heuristique
    proba = 25
    if major_res.confluence_count >= 3:
        proba += 20
    if ctx.order_flow.session_bias == "BEAR":
        proba += 10
    if ctx.patterns.sweep_high_active > 0 or ctx.patterns.sweep_high_this_bar:
        proba += 15
    if ctx.market_structure.range_pos_va_pct >= 0.9:
        proba += 5
    proba = min(proba, 70)

    near_sup = _nearest_support(ctx)
    if near_sup is None:
        return None

    setup_entry = major_res.price
    setup_target = near_sup.price
    setup_stop = setup_entry + 0.3 * ctx.atr
    rr = _compute_r_r(setup_entry, setup_target, setup_stop, "short")

    setup = TradingSetup(
        name=f"SHORT rejet {major_res.label}",
        side="short",
        entry_price=setup_entry,
        entry_zone_low=setup_entry - 0.15 * ctx.atr,
        entry_zone_high=setup_entry + 0.15 * ctx.atr,
        target_1=setup_target,
        target_2=ctx.key_levels_support[1].price if len(ctx.key_levels_support) > 1 else None,
        stop_loss=round(setup_stop, 2),
        r_r_ratio=rr,
        conditions_validation=[
            f"Rejet confirme (long wick haut > 0.3 ATR)",
            "Delta_bar < 0 sur la bar de rejet",
            "BN absorb_ask > 0 OU bn_long_dn = 1",
            "finish_strength < 0",
            f"Confluence {major_res.confluence_count} niveaux superposes",
        ],
        conditions_invalidation=[
            f"Close > {round(setup_stop, 2)} (stop touche)",
            f"Cassure {major_res.label} avec volume > 2x average",
            "Delta day reste BULL fort",
        ],
        confidence="high" if proba >= 55 else "medium",
        rationale=f"Confluence {major_res.confluence_count} sources sur {major_res.price} ({major_res.label}), setup contre-trend",
    )

    return Scenario(
        name="Bearish rejection",
        direction="bearish",
        probability_pct=proba,
        description=(
            f"Confluence forte sur {major_res.label} (@{major_res.price}, "
            f"{major_res.confluence_count} sources). Setup SHORT contre-trend "
            f"avec target {near_sup.label}."
        ),
        key_levels_used=[major_res, near_sup],
        setups=[setup],
    )


def _scenario_range_bound(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : range entre support et resistance."""
    if ctx.market_structure.day_type not in ("NormVar", "Neutral"):
        return None
    if ctx.market_structure.trend_day_probability > 0.3:
        return None

    near_res = _nearest_resistance(ctx)
    near_sup = _nearest_support(ctx)
    if near_res is None or near_sup is None:
        return None

    range_atr = near_res.distance_atr - near_sup.distance_atr
    if range_atr < 0.5:  # Range trop etroit
        return None

    proba = 35
    if ctx.market_structure.day_type == "NormVar":
        proba += 10
    proba = min(proba, 60)

    setups = []

    # Setup LONG fade vers support
    long_entry = near_sup.price
    long_target = near_res.price
    long_stop = long_entry - 0.4 * ctx.atr
    setups.append(TradingSetup(
        name=f"LONG fade {near_sup.label}",
        side="long",
        entry_price=long_entry,
        entry_zone_low=long_entry - 0.1 * ctx.atr,
        entry_zone_high=long_entry + 0.1 * ctx.atr,
        target_1=long_target,
        target_2=None,
        stop_loss=round(long_stop, 2),
        r_r_ratio=_compute_r_r(long_entry, long_target, long_stop, "long"),
        conditions_validation=["Touch support + delta+ + finish_strength +"],
        conditions_invalidation=["Cassure support avec volume"],
        confidence="medium",
        rationale="Range NormVar attendu, fade support",
    ))

    # Setup SHORT fade vers resistance
    short_entry = near_res.price
    short_target = near_sup.price
    short_stop = short_entry + 0.4 * ctx.atr
    setups.append(TradingSetup(
        name=f"SHORT fade {near_res.label}",
        side="short",
        entry_price=short_entry,
        entry_zone_low=short_entry - 0.1 * ctx.atr,
        entry_zone_high=short_entry + 0.1 * ctx.atr,
        target_1=short_target,
        target_2=None,
        stop_loss=round(short_stop, 2),
        r_r_ratio=_compute_r_r(short_entry, short_target, short_stop, "short"),
        conditions_validation=["Touch resistance + delta- + finish_strength -"],
        conditions_invalidation=["Cassure resistance avec volume"],
        confidence="medium",
        rationale="Range NormVar attendu, fade resistance",
    ))

    return Scenario(
        name="Range bound",
        direction="range",
        probability_pct=proba,
        description=(
            f"Day type {ctx.market_structure.day_type} + trend_day_prob "
            f"{ctx.market_structure.trend_day_probability:.2f} = range attendu "
            f"entre {near_sup.label} ({near_sup.price}) et {near_res.label} "
            f"({near_res.price}). Setups fade des 2 cotes."
        ),
        key_levels_used=[near_sup, near_res],
        setups=setups,
    )


def _scenario_judas_reversal(ctx: NarrativeContext) -> Optional[Scenario]:
    """Scenario : Judas Swing detected -> reversal vraie direction."""
    if not ctx.patterns.judas_swing_active:
        return None
    direction = ctx.session.judas_swing_direction
    if direction == 0:
        return None

    proba = 50  # Judas detected = signal fort
    if ctx.order_flow.bn_signals_active:
        proba += 10
    proba = min(proba, 75)

    if direction == +1:  # Vraie direction UP
        near_res = _nearest_resistance(ctx)
        if near_res is None:
            return None
        return Scenario(
            name="Judas Swing reversal LONG",
            direction="bullish",
            probability_pct=proba,
            description=(
                f"Judas Swing detected (London first hour direction OPPOSEE). "
                f"Vraie direction = UP. Target {near_res.label} (@{near_res.price})."
            ),
            key_levels_used=[near_res],
            setups=[TradingSetup(
                name="LONG post-Judas",
                side="long",
                entry_price=ctx.close,
                entry_zone_low=ctx.close - 0.1 * ctx.atr,
                entry_zone_high=ctx.close + 0.1 * ctx.atr,
                target_1=near_res.price,
                target_2=None,
                stop_loss=round(ctx.close - 0.5 * ctx.atr, 2),
                r_r_ratio=_compute_r_r(ctx.close, near_res.price,
                                       ctx.close - 0.5 * ctx.atr, "long"),
                conditions_validation=["Continuation UP confirme post-Judas detected"],
                conditions_invalidation=["Retour direction first hour"],
                confidence="high" if proba >= 65 else "medium",
                rationale="Judas Swing ICT detected, direction vraie identifiee",
            )],
        )
    else:  # direction == -1 -> SHORT
        near_sup = _nearest_support(ctx)
        if near_sup is None:
            return None
        return Scenario(
            name="Judas Swing reversal SHORT",
            direction="bearish",
            probability_pct=proba,
            description=(
                f"Judas Swing detected (London first hour direction OPPOSEE). "
                f"Vraie direction = DOWN. Target {near_sup.label} (@{near_sup.price})."
            ),
            key_levels_used=[near_sup],
            setups=[TradingSetup(
                name="SHORT post-Judas",
                side="short",
                entry_price=ctx.close,
                entry_zone_low=ctx.close - 0.1 * ctx.atr,
                entry_zone_high=ctx.close + 0.1 * ctx.atr,
                target_1=near_sup.price,
                target_2=None,
                stop_loss=round(ctx.close + 0.5 * ctx.atr, 2),
                r_r_ratio=_compute_r_r(ctx.close, near_sup.price,
                                       ctx.close + 0.5 * ctx.atr, "short"),
                conditions_validation=["Continuation DOWN confirme post-Judas detected"],
                conditions_invalidation=["Retour direction first hour"],
                confidence="high" if proba >= 65 else "medium",
                rationale="Judas Swing ICT detected, direction vraie identifiee",
            )],
        )


# ════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE
# ════════════════════════════════════════════════════════════════════════════

def generate_scenarios(ctx: NarrativeContext) -> list:
    """Genere 3-4 scenarios probabilistiques depuis NarrativeContext.

    Args:
        ctx : NarrativeContext extrait par build_narrative_context()

    Returns:
        List[Scenario] sortee par probability_pct descending.
    """
    scenarios = []
    builders = [
        _scenario_bullish_continuation,
        _scenario_bearish_rejection,
        _scenario_range_bound,
        _scenario_judas_reversal,
    ]
    for builder in builders:
        try:
            sc = builder(ctx)
            if sc is not None:
                scenarios.append(sc)
        except Exception:  # noqa: BLE001
            # Fail-soft : un builder qui crash ne casse pas les autres
            pass

    # Sort par probabilite descending
    scenarios.sort(key=lambda s: -s.probability_pct)
    return scenarios
