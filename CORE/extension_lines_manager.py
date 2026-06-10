"""
extension_lines_manager.py — Gestion zones actives "Extension Lines" (Sierra Chart pattern).

Reproduit le mecanisme `AddLineUntilFutureIntersection` de Sierra Chart :
  - Une zone est creee a un prix (ou groupe de prix) sur une bar source
  - La zone reste ACTIVE jusqu'a ce qu'un bar futur la touche
  - Une zone touchee est DESACTIVEE (mais pas supprimee, gardee pour stats)

Utilise par :
  - Edge Zones (cellules diagonales >= 600% ES / 1000% NQ)
  - Volume At Price Threshold Alert V2 (Big Orders avec extension lines)

Convention SC verifiee :
  - "Draw Extension Lines = All Prices in Adjacent Alerts" : zone = groupe de prix consecutifs
  - "Highlight Adjacent Alerts Minimum Group Size = 2" : min 2 cellules consecutives
  - "Draw Extension Lines until End of Chart = No" : ligne stop a intersection
  - Zone est touchee si bar_low <= max_price AND bar_high >= min_price (overlap)

Auteur : Phase B+++ Bloc 3 (2026-04-26) - feature #1 Edge Zones prereq
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass
class Zone:
    """Une zone Extension Lines (groupe de prix consecutifs)."""
    created_bar_idx: int
    side: str                  # 'buy' ou 'sell'
    min_price: float
    max_price: float
    n_prices: int              # nombre de cellules dans le stack
    active: bool = True
    deactivated_bar_idx: Optional[int] = None

    @property
    def range_size(self) -> float:
        return self.max_price - self.min_price


class ExtensionLineBuffer:
    """
    Buffer de zones actives.

    Conventions :
      - add_zone : appele quand une nouvelle zone fire sur le bar courant
      - update_with_bar : appele a chaque bar pour deactivate les zones touchees
                          (DOIT etre appele AVANT add_zone du meme bar)

    Performance : O(N_active_zones) par bar. Si trop de zones actives, on prune
                  les plus anciennes apres N bars (max_age).
    """

    def __init__(self, max_age_bars: int = 1380 * 5,  # 5 jours sur 1-min
                 max_zones_per_side: int = 100):
        self.zones: List[Zone] = []
        self.max_age_bars = max_age_bars
        self.max_zones_per_side = max_zones_per_side

    def add_zone(self, bar_idx: int, prices: List[float], side: str):
        """Ajoute une nouvelle zone (groupe de prix consecutifs)."""
        if not prices:
            return
        side = side.lower()
        assert side in ("buy", "sell"), f"side must be 'buy'|'sell', got {side}"
        zone = Zone(
            created_bar_idx=bar_idx,
            side=side,
            min_price=float(min(prices)),
            max_price=float(max(prices)),
            n_prices=len(prices),
        )
        self.zones.append(zone)
        # Prune oldest si depasse capacity
        same_side = [z for z in self.zones if z.side == side and z.active]
        if len(same_side) > self.max_zones_per_side:
            # Deactivate oldest (FIFO)
            oldest = sorted(same_side, key=lambda z: z.created_bar_idx)[0]
            oldest.active = False
            oldest.deactivated_bar_idx = bar_idx  # pruned, pas touche

    def update_with_bar(self, bar_idx: int, bar_low: float, bar_high: float):
        """
        Deactivate les zones actives touchees par le range [bar_low, bar_high].

        Une zone est touchee si overlap geometrique :
          bar_low <= zone.max_price AND bar_high >= zone.min_price
        """
        for z in self.zones:
            if not z.active:
                continue
            # Skip zones cree dans la meme bar (ne peuvent pas etre touchees instantanement)
            if z.created_bar_idx == bar_idx:
                continue
            if bar_low <= z.max_price and bar_high >= z.min_price:
                z.active = False
                z.deactivated_bar_idx = bar_idx
            elif bar_idx - z.created_bar_idx > self.max_age_bars:
                # Age max atteint sans touche (purge security)
                z.active = False
                z.deactivated_bar_idx = bar_idx

    def count_active(self, side: str) -> int:
        """Compte zones actives pour un side ('buy'|'sell')."""
        side = side.lower()
        return sum(1 for z in self.zones if z.side == side and z.active)

    def nearest_distance(self, side: str, close: float) -> float:
        """
        Distance au plus proche zone active (en price units, NaN si aucune).
        Distance signee : positive si zone au-dessus du close, negative si en-dessous.
        """
        side = side.lower()
        active = [z for z in self.zones if z.side == side and z.active]
        if not active:
            return np.nan

        distances = []
        for z in active:
            if close < z.min_price:
                d = z.min_price - close  # zone au-dessus
            elif close > z.max_price:
                d = -(close - z.max_price)  # zone en-dessous (signe negatif)
            else:
                d = 0  # close dans la zone
            distances.append(d)

        # Plus proche en valeur absolue
        return min(distances, key=abs)

    def reset(self):
        """Reset complet (utilise pour test ou reset session)."""
        self.zones.clear()

    def stats(self) -> dict:
        """Stats globaux pour debug."""
        n_total = len(self.zones)
        n_buy = sum(1 for z in self.zones if z.side == "buy")
        n_sell = sum(1 for z in self.zones if z.side == "sell")
        n_active_buy = sum(1 for z in self.zones if z.side == "buy" and z.active)
        n_active_sell = sum(1 for z in self.zones if z.side == "sell" and z.active)
        return {
            "total": n_total,
            "buy_total": n_buy,
            "sell_total": n_sell,
            "active_buy": n_active_buy,
            "active_sell": n_active_sell,
        }
