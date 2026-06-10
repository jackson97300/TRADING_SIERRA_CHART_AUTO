"""rules_trader_pd_attentiste.py — Moteur de rules attentiste base niveaux PD.

Spec : DOCS/specs/2026-04-28-rules-trader-pd-attentiste-design.md.

4 scenarios isoles (anti pattern 11 V1 : pas de cascade, pas de voting) :
  A — BUY pullback PVAL/PSD-1     (R:R 1:3, secure)
  B — BUY retest PVWAP            (R:R 1:2, dynamique)
  C — SELL fade PSD+1/PVAH/PDH    (R:R 1:3, fade triple confluence)
  D — SELL break-down PDL         (R:R 1:2, momentum)

Pre-trade gates communs :
  - mins_et dans [600, 900] (10:00-15:00 ET, evite open noise + EOD)
    (Scenario C plus strict : <= 870 = avant 14:30 ET)
  - vix_level < 30 (pas de regime panic)
  - PDLevels charge (sinon SKIP)

Output : list[RuleSignal] — le bot routeur decide quel signal prendre
(1 trade max par instrument via cooldown/exposure).

Auteur : MIA Trading System V2
Date   : 2026-04-28 01:00 (Voie 2 Bloc 2 — Plan B Rules PD)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from CORE.pd_levels_extractor import PDLevels


# ==============================================================================
# Constantes scenarios + RuleSignal
# ==============================================================================

SCENARIO_A_BUY_PULLBACK_PVAL = "A_buy_pullback_pval"
SCENARIO_B_BUY_PVWAP_RETEST = "B_buy_pvwap_retest"
SCENARIO_C_SELL_FADE_TOP = "C_sell_fade_top"
SCENARIO_D_SELL_BREAK_PDL = "D_sell_break_pdl"


@dataclass
class RuleSignal:
    """Signal emis par un scenario rules_trader_pd_attentiste.

    Note : structure differente du RuleSignal de CORE/rule_engine.py (qui agrege
    les regles V1 globales). Ici 1 RuleSignal = 1 scenario isole avec entry/SL/TP.
    """
    scenario: str               # SCENARIO_A_* / B_ / C_ / D_
    direction: int              # +1 BUY, -1 SELL
    entry: float                # prix d'entree
    sl: float                   # stop loss
    tp1: float                  # take profit 1 (50% size sortie)
    tp2: float                  # take profit 2 (50% restant)
    strength: float = 0.0       # qualite du setup [0, 1]
    triggers_fired: List[str] = field(default_factory=list)
    notes: str = ""


# ==============================================================================
# Helpers
# ==============================================================================


def _f(bar: dict, key: str, default: float = 0.0) -> float:
    """Safe float read avec fallback (price <-> close, high <-> bar_high)."""
    fallbacks = {
        "price": "close",
        "close": "price",
        "high": "bar_high",
        "low": "bar_low",
    }
    v = bar.get(key)
    if v is None and key in fallbacks:
        v = bar.get(fallbacks[key])
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


def _i(bar: dict, key: str, default: int = 0) -> int:
    v = bar.get(key, default)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _common_gates(bar: dict, pdl: Optional[PDLevels],
                   min_mins_et: int = 600, max_mins_et: int = 900) -> bool:
    """Gates communs a tous les scenarios. False = bloque."""
    if pdl is None:
        return False
    mins_et = _i(bar, "mins_et", -1)
    if mins_et < min_mins_et or mins_et > max_mins_et:
        return False
    vix = _f(bar, "vix_level", 0)
    if vix > 30.0:
        return False
    return True


# ==============================================================================
# Scenarios
# ==============================================================================


def _scenario_A_buy_pullback_pval(bar: dict, pdl: PDLevels) -> Optional[RuleSignal]:
    """A — BUY pullback PVAL/PSD-1 (priorite 1 secure, R:R 1:3)."""
    if not _common_gates(bar, pdl):
        return None

    price = _f(bar, "price")
    # Zone : PSD-1 <= price <= PVAL (double confluence basse)
    zone_lo = min(pdl.PSD_minus_1, pdl.PVAL)
    zone_hi = max(pdl.PSD_minus_1, pdl.PVAL)
    if not (zone_lo <= price <= zone_hi):
        return None

    triggers = []
    # Trigger 1 : meche bas claire
    # Compat : wick_low_ticks (test fixtures) OU bar_lower_wick_pct (parquet v5d)
    wick = _f(bar, "wick_low_ticks")
    wick_pct = _f(bar, "bar_lower_wick_pct")
    if wick < 5 and wick_pct < 0.05:
        return None
    triggers.append(f"wick_low={wick:.0f}t/{wick_pct:.2f}pct")

    # Trigger 2 : long_dn_up_pattern fire
    if _i(bar, "long_dn_up_pattern") != 1:
        return None
    triggers.append("long_dn_up=1")

    # Trigger 3 : cluster color_up >= 3
    n_color = _i(bar, "n_color_up_zones_active")
    if n_color < 3:
        return None
    triggers.append(f"color_up={n_color}")

    # Trigger 4 : delta acheteur
    delta = _f(bar, "delta_bar")
    if delta <= 0:
        return None
    triggers.append(f"delta+={delta:.0f}")

    # SL : sous PDL - 3 ticks (TICK = 0.25)
    sl = pdl.PDL - 3 * 0.25
    # TP1 : PVPOC, TP2 : PDH - 2 ticks
    tp1 = pdl.PVPOC
    tp2 = pdl.PDH - 2 * 0.25

    # Strength : combinaison normalisee triggers
    strength = min(1.0, (wick / 12.0) + (n_color / 8.0) + (min(delta, 100) / 200.0))

    return RuleSignal(
        scenario=SCENARIO_A_BUY_PULLBACK_PVAL,
        direction=1, entry=price, sl=sl, tp1=tp1, tp2=tp2,
        strength=round(strength, 3),
        triggers_fired=triggers,
        notes=f"zone[{zone_lo:.2f},{zone_hi:.2f}] R:R~{(tp1-price)/(price-sl):.2f}",
    )


def _scenario_B_buy_pvwap_retest(bar: dict, pdl: PDLevels) -> Optional[RuleSignal]:
    """B — BUY retest PVWAP (priorite 2 dynamique, R:R 1:2)."""
    if not _common_gates(bar, pdl):
        return None

    price = _f(bar, "price")
    # Zone : PVWAP - 10t <= price <= PVWAP + 5t (TICK 0.25, ~2.5pt fenetre)
    # FIX 28/04 : ancienne fenetre (3t down, 5t up) trop etroite sur NQ.
    # Stats empiriques : seulement 8 bars sur 24j × 300 RTH bars ~ <0.1%.
    if not (pdl.PVWAP - 10 * 0.25 <= price <= pdl.PVWAP + 5 * 0.25):
        return None

    triggers = []
    wick = _f(bar, "wick_low_ticks")
    wick_pct = _f(bar, "bar_lower_wick_pct")
    if wick < 4 and wick_pct < 0.04:
        return None
    triggers.append(f"wick_low={wick:.0f}t/{wick_pct:.2f}pct")

    # OR (long_dn_up OR bn_trapped_sellers_at_support)
    has_long_dn_up = _i(bar, "long_dn_up_pattern") == 1
    has_trapped = _i(bar, "bn_trapped_sellers_at_support") == 1
    if not (has_long_dn_up or has_trapped):
        return None
    triggers.append("long_dn_up" if has_long_dn_up else "trapped_sellers")

    n_color = _i(bar, "n_color_up_zones_active")
    if n_color < 2:
        return None
    triggers.append(f"color_up={n_color}")

    delta = _f(bar, "delta_bar")
    if delta <= 0:
        return None
    triggers.append(f"delta+={delta:.0f}")

    # SL : sous PVAL - 3 ticks
    sl = pdl.PVAL - 3 * 0.25
    # TP1 : PDC + 5t, TP2 : PDH - 2t
    tp1 = pdl.PDC + 5 * 0.25
    tp2 = pdl.PDH - 2 * 0.25

    strength = min(1.0, (wick / 10.0) + (n_color / 6.0) + (min(delta, 60) / 120.0))

    return RuleSignal(
        scenario=SCENARIO_B_BUY_PVWAP_RETEST,
        direction=1, entry=price, sl=sl, tp1=tp1, tp2=tp2,
        strength=round(strength, 3),
        triggers_fired=triggers,
        notes=f"PVWAP={pdl.PVWAP:.2f} R:R~{(tp1-price)/(price-sl) if price > sl else 0:.2f}",
    )


def _scenario_C_sell_fade_top(bar: dict, pdl: PDLevels) -> Optional[RuleSignal]:
    """C — SELL fade triple confluence PSD+1/PVAH/PDH (R:R 1:3)."""
    # Gate plus strict : avant 14:30 ET (anti-EOD pump)
    if not _common_gates(bar, pdl, max_mins_et=870):
        return None

    price = _f(bar, "price")
    # Zone serree : PSD+1 <= price <= PVAH
    zone_lo = min(pdl.PSD_plus_1, pdl.PVAH)
    zone_hi = max(pdl.PSD_plus_1, pdl.PVAH)
    if not (zone_lo <= price <= zone_hi):
        return None

    triggers = []
    wick = _f(bar, "wick_high_ticks")
    wick_pct = _f(bar, "bar_upper_wick_pct")
    if wick < 5 and wick_pct < 0.05:
        return None
    triggers.append(f"wick_high={wick:.0f}t/{wick_pct:.2f}pct")

    if _i(bar, "long_up_dn_pattern") != 1:
        return None
    triggers.append("long_up_dn")

    n_color = _i(bar, "n_color_dn_zones_active")
    if n_color < 3:
        return None
    triggers.append(f"color_dn={n_color}")

    delta = _f(bar, "delta_bar")
    if delta >= 0:
        return None
    triggers.append(f"delta-={delta:.0f}")

    # Bloc gamma : si above MQ call 0DTE (breakout cassant gamma) → bloque
    if _i(bar, "bool_above_mq_call_0dte") == 1:
        return None

    # SL : au-dessus du max(PDH, PSD+1, PVAH) + 4 ticks
    # FIX 28/04 : ancien SL trop large -> MaxDD 1169t NQ. Cap a 25 ticks max.
    raw_sl = max(pdl.PDH, pdl.PSD_plus_1, pdl.PVAH) + 4 * 0.25
    max_sl_dist = 25 * 0.25  # cap 25 ticks (6.25 pt) pour limiter loss/trade
    sl = min(raw_sl, price + max_sl_dist)
    # TP1 : PVPOC (50%), TP2 : PVWAP (50%)
    tp1 = pdl.PVPOC
    tp2 = pdl.PVWAP

    strength = min(1.0, (wick / 12.0) + (n_color / 8.0) + (min(abs(delta), 100) / 200.0))

    return RuleSignal(
        scenario=SCENARIO_C_SELL_FADE_TOP,
        direction=-1, entry=price, sl=sl, tp1=tp1, tp2=tp2,
        strength=round(strength, 3),
        triggers_fired=triggers,
        notes=f"triple={pdl.PDH:.2f}/{pdl.PSD_plus_1:.2f}/{pdl.PVAH:.2f}",
    )


def _scenario_D_sell_break_pdl(bar: dict, pdl: PDLevels) -> Optional[RuleSignal]:
    """D — SELL break-down PDL (R:R 1:2, momentum)."""
    if not _common_gates(bar, pdl):
        return None

    price = _f(bar, "price")
    close = _f(bar, "close", default=price)
    # Zone : PDL-5t <= price <= PDL-1t
    if not (pdl.PDL - 5 * 0.25 <= price <= pdl.PDL - 1 * 0.25):
        return None

    # Gate gamma : above HVL (gamma+) bloque (mean reversion environnement)
    if _i(bar, "bool_above_mq_hvl") == 1:
        return None

    triggers = []
    # Clean break : close < PDL
    if close >= pdl.PDL:
        return None
    triggers.append(f"close<PDL ({close:.2f}<{pdl.PDL:.2f})")

    delta = _f(bar, "delta_bar")
    if delta >= 0:
        return None
    triggers.append(f"delta-={delta:.0f}")

    if _i(bar, "vol_spike_dn") != 1:
        return None
    triggers.append("vol_spike_dn")

    n_color = _i(bar, "n_color_dn_zones_active")
    if n_color < 2:
        return None
    triggers.append(f"color_dn={n_color}")

    # SL : PDL + 6 ticks (1.5 pt) — re-entry above PDL = false breakdown
    # FIX 28/04 : ancien SL = PVAL+2t cree des SL > 100t, SR catastrophe.
    sl = pdl.PDL + 6 * 0.25
    # TP1 : 50% du move PDL <-> PVAL (target proche, secure)
    tp1 = pdl.PDL - (pdl.PVAL - pdl.PDL) * 0.5
    # TP2 : full mirror move (PDL - (PVAL - PDL))
    tp2 = pdl.PDL - (pdl.PVAL - pdl.PDL)

    strength = min(1.0, (n_color / 6.0) + (min(abs(delta), 100) / 200.0) + 0.3)

    return RuleSignal(
        scenario=SCENARIO_D_SELL_BREAK_PDL,
        direction=-1, entry=price, sl=sl, tp1=tp1, tp2=tp2,
        strength=round(strength, 3),
        triggers_fired=triggers,
        notes=f"PDL={pdl.PDL:.2f} clean break",
    )


# ==============================================================================
# API publique
# ==============================================================================


SCENARIO_FNS = [
    _scenario_A_buy_pullback_pval,
    _scenario_B_buy_pvwap_retest,
    _scenario_C_sell_fade_top,
    _scenario_D_sell_break_pdl,
]


def evaluate_scenarios(bar: dict, pdl: Optional[PDLevels]) -> List[RuleSignal]:
    """Evalue les 4 scenarios isoles. Retourne tous les signaux fires.

    Args:
        bar: dict avec features de la barre courante (price, mins_et, wick_*, etc.)
        pdl: PDLevels du jour J-1 (ou None si pas dispo)

    Returns:
        Liste de RuleSignal (vide si rien fire ou pdl None).
    """
    if pdl is None:
        return []
    signals: List[RuleSignal] = []
    for fn in SCENARIO_FNS:
        s = fn(bar, pdl)
        if s is not None:
            signals.append(s)
    return signals
