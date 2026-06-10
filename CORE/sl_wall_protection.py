"""sl_wall_protection.py — Smart SL placement derriere mur structurel.

Spec : DOCS/specs/2026-04-28-smart-sl-wall-protection.md.

Principe (regle d'or Jackson 28/04) :
  Au lieu de SL = entry +/- K_SL × ATR (generique), on cherche le mur structurel
  le plus proche au-dela du SL baseline et on place SL = mur +/- buffer_ticks
  (3-5 ticks anti stop hunter).

42 niveaux audites parquet v5d, classes en 3 tiers :
  Tier 1 (score 1.0) : PDH/PDL, PVA, PVWAP+SD, VWAP_d+SD3 (21 murs)
  Tier 2 (score 0.7) : IB, OVN, Asia/London, Sess, VWAP_w/m+SD (15 murs)
  Tier 3 (score 0.3) : after, cash (4 murs, souvent NaN)
  MQ (score 1.2)     : non disponible parquet (raw JSONL only)

Auteur : MIA Trading System V2
Date   : 2026-04-28 10:05 (Smart SL Wall — regle d'or Jackson)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


TICK_SIZE = 0.25  # ES + NQ identique


@dataclass
class Wall:
    """Niveau structurel candidat pour placement SL."""
    name: str           # "PDL", "PVAL", "vwap_d_sd1d", "MQ_put_0dte"
    price: float        # niveau absolu
    tier: int           # 1=fort, 2=moyen, 3=faible
    score: float        # priorite (1.0, 0.7, 0.3, 1.2)


# Mapping (column_name, display_name, tier, score) — depuis audit parquet v5d
WALL_DEFINITIONS = [
    # TIER 1 — Murs forts (score 1.0)
    ("pdh", "PDH", 1, 1.0),
    ("pdl", "PDL", 1, 1.0),
    ("prev_vah", "PVAH", 1, 1.0),
    ("prev_val", "PVAL", 1, 1.0),
    ("prev_vpoc", "PVPOC", 1, 1.0),
    ("pvwap", "PVWAP", 1, 1.0),
    ("pvwap_sd1u", "PVWAP_SD1u", 1, 1.0),
    ("pvwap_sd1d", "PVWAP_SD1d", 1, 1.0),
    ("cur_vah", "VAH_cur", 1, 1.0),
    ("cur_val", "VAL_cur", 1, 1.0),
    ("cur_vpoc", "VPOC_cur", 1, 1.0),
    ("vwap_d", "VWAP_d", 1, 1.0),
    ("vwap_d_sd1u", "VWAP_d_SD1u", 1, 1.0),
    ("vwap_d_sd1d", "VWAP_d_SD1d", 1, 1.0),
    ("vwap_d_sd2u", "VWAP_d_SD2u", 1, 1.0),
    ("vwap_d_sd2d", "VWAP_d_SD2d", 1, 1.0),
    ("vwap_d_sd3u", "VWAP_d_SD3u", 1, 1.0),
    ("vwap_d_sd3d", "VWAP_d_SD3d", 1, 1.0),

    # TIER 2 — Murs moyens (score 0.7)
    ("ib_high", "IB_high", 2, 0.7),
    ("ib_low", "IB_low", 2, 0.7),
    ("ovn_high", "OVN_high", 2, 0.7),
    ("ovn_low", "OVN_low", 2, 0.7),
    ("asia_high", "Asia_high", 2, 0.7),
    ("asia_low", "Asia_low", 2, 0.7),
    ("london_high", "London_high", 2, 0.7),
    ("london_low", "London_low", 2, 0.7),
    ("sess_high", "Sess_high", 2, 0.7),
    ("sess_low", "Sess_low", 2, 0.7),
    ("vwap_w", "VWAP_w", 2, 0.7),
    ("vwap_w_sd1u", "VWAP_w_SD1u", 2, 0.7),
    ("vwap_w_sd1d", "VWAP_w_SD1d", 2, 0.7),
    ("vwap_w_sd2u", "VWAP_w_SD2u", 2, 0.7),
    ("vwap_w_sd2d", "VWAP_w_SD2d", 2, 0.7),
    ("vwap_m", "VWAP_m", 2, 0.7),
    ("vwap_m_sd1u", "VWAP_m_SD1u", 2, 0.7),
    ("vwap_m_sd1d", "VWAP_m_SD1d", 2, 0.7),

    # TIER 3 — Murs faibles (score 0.3)
    ("after_high", "After_high", 3, 0.3),
    ("after_low", "After_low", 3, 0.3),
    ("cash_high", "Cash_high", 3, 0.3),
    ("cash_low", "Cash_low", 3, 0.3),
]


def collect_walls(bar: dict, direction: int, entry: float,
                   max_distance_pts: float = 30.0) -> List[Wall]:
    """Collecte tous les murs disponibles dans la direction adverse au trade.

    Args:
        bar: dict avec features parquet v5d ou JSONL DMP.
        direction: +1 BUY (cherche murs SOUS entry), -1 SELL (au-dessus).
        entry: prix entry.
        max_distance_pts: ignorer murs trop loin (cap absolu).

    Returns:
        Liste de Wall valides (NaN/None ignored), tries par proximite a entry.
    """
    walls: List[Wall] = []
    for col, display, tier, score in WALL_DEFINITIONS:
        if col not in bar:
            continue
        v = bar[col]
        if v is None:
            continue
        try:
            price = float(v)
            if price != price:  # NaN
                continue
            if price <= 0:  # invalid (forex 0, etc.)
                continue
        except (TypeError, ValueError):
            continue

        # Filtre direction
        if direction == 1 and price >= entry:
            continue  # BUY : on veut murs SOUS entry
        if direction == -1 and price <= entry:
            continue  # SELL : on veut murs AU-DESSUS

        # Filtre distance max
        if abs(entry - price) > max_distance_pts:
            continue

        walls.append(Wall(name=display, price=price, tier=tier, score=score))

    # Tri par proximite a entry (le plus proche en premier)
    walls.sort(key=lambda w: abs(entry - w.price))
    return walls


def compute_protected_sl(direction: int, entry: float, walls: List[Wall],
                          base_sl: float, buffer_ticks: int = 3,
                          tick_size: float = TICK_SIZE,
                          max_sl_multiplier: float = 1.5
                          ) -> Tuple[float, str]:
    """Place SL derriere le mur le plus pertinent au-dela du base_sl.

    Args:
        direction: +1 BUY, -1 SELL.
        entry: prix entry.
        walls: liste de Wall (sortie de collect_walls).
        base_sl: SL baseline (K_SL × ATR).
        buffer_ticks: marge anti stop hunter (3-5 typique).
        tick_size: 0.25 par defaut.
        max_sl_multiplier: si abs(entry-wall) > max_mult * abs(entry-base_sl),
                            keep base_sl (eviter SL trop loin).

    Returns:
        (sl_price, wall_name). wall_name = "ATR_baseline" si aucun mur valide.
    """
    if not walls:
        return (base_sl, "ATR_baseline")

    # Distance baseline (positive)
    base_dist = abs(entry - base_sl)
    max_dist_allowed = max_sl_multiplier * base_dist

    # Filtrer les murs valides : derriere base_sl (plus loin) ET pas trop loin
    candidates: List[Wall] = []
    for w in walls:
        wall_dist = abs(entry - w.price)
        # Mur DOIT etre derriere ou egal au base_sl (plus loin)
        if direction == 1:  # BUY : SL sous entry, mur DOIT etre <= base_sl
            if w.price > base_sl:
                continue
        else:  # SELL : SL au-dessus entry, mur DOIT etre >= base_sl
            if w.price < base_sl:
                continue
        # Cap distance
        if wall_dist > max_dist_allowed:
            continue
        candidates.append(w)

    if not candidates:
        return (base_sl, "ATR_baseline")

    # Selection : combine proximite (close to base_sl = good) + score tier
    # score_combined = score / (1 + abs(wall - base_sl) / base_dist)
    # Le plus proche du base_sl avec le tier le plus fort gagne.
    def _ranking_score(w: Wall) -> float:
        proximity_to_base = abs(w.price - base_sl)
        # Plus le mur est proche du base_sl, mieux c'est
        proximity_factor = 1.0 / (1.0 + proximity_to_base / max(0.1, base_dist))
        return w.score * proximity_factor

    best = max(candidates, key=_ranking_score)

    # Place SL avec buffer anti stop hunter
    if direction == 1:  # BUY : SL sous mur
        sl_price = best.price - buffer_ticks * tick_size
    else:  # SELL : SL au-dessus mur
        sl_price = best.price + buffer_ticks * tick_size

    return (sl_price, best.name)


def main_demo():
    """Demo CLI : python -m CORE.sl_wall_protection."""
    # Bar exemple NQ 27/04
    bar = {
        "close": 27431.0,
        "pdh": 27449.75, "pdl": 27305.50,
        "prev_vah": 27523.75, "prev_val": 27391.75, "prev_vpoc": 27463.75,
        "pvwap": 27406.42,
        "vwap_d": 27395.0, "vwap_d_sd1u": 27450.0, "vwap_d_sd1d": 27340.0,
        "ib_high": 27445.0, "ib_low": 27370.0,
    }

    print("=" * 70)
    print("DEMO Smart SL Wall Protection")
    print("=" * 70)

    # Setup BUY pullback proche PVAL
    entry = 27395.0
    base_sl = 27385.0  # K_SL × ATR baseline
    walls = collect_walls(bar, direction=1, entry=entry, max_distance_pts=30.0)
    print(f"\n[BUY] entry={entry} base_sl={base_sl} (ATR baseline)")
    print(f"  Walls disponibles ({len(walls)}) :")
    for w in walls[:8]:
        print(f"    {w.name:20s} price={w.price:.2f} tier={w.tier} score={w.score}")
    sl, wall_name = compute_protected_sl(direction=1, entry=entry, walls=walls,
                                          base_sl=base_sl, buffer_ticks=3)
    print(f"  → SL protege : {sl:.2f} ({wall_name})")
    print(f"  → distance SL: {abs(entry - sl):.2f} pts (vs baseline {abs(entry-base_sl):.2f}pts)")

    # Setup SELL fade
    entry = 27445.0
    base_sl = 27455.0
    walls = collect_walls(bar, direction=-1, entry=entry, max_distance_pts=30.0)
    print(f"\n[SELL] entry={entry} base_sl={base_sl} (ATR baseline)")
    print(f"  Walls disponibles ({len(walls)}) :")
    for w in walls[:8]:
        print(f"    {w.name:20s} price={w.price:.2f} tier={w.tier} score={w.score}")
    sl, wall_name = compute_protected_sl(direction=-1, entry=entry, walls=walls,
                                          base_sl=base_sl, buffer_ticks=3)
    print(f"  → SL protege : {sl:.2f} ({wall_name})")
    print(f"  → distance SL: {abs(entry - sl):.2f} pts (vs baseline {abs(entry-base_sl):.2f}pts)")


if __name__ == "__main__":
    main_demo()
