"""
edge_zones_engine.py — Reproduction Sierra Chart Edge Zones Imbalance.

Sources :
  - SC etudes :
    * EDGE ZONES IMBALANCE BUY 600%DIAG (ID 32 ES Chart 1)
    * EDGE ZONES IMBALANCE SELL 600%DIAG (ID 35 ES Chart 1)
    * EDGE ZONES IMBALANCE BUY 0DIAG (ID 4 NQ Chart 2) - seuil 1000%
    * EDGE ZONES IMBALANCE SELL 0DIAG (ID 2 NQ Chart 2) - seuil -1000%
  - Inputs SC verifies par Jackson 26/04/2026 :
    * Comparison Method = "Ask Volume Bid Volume Diagonal Ratio"
    * Percentage Threshold : 600 (ES) / 1000 (NQ)
    * Enable Zero Bid/Ask Compares = Yes (Set 0 to 1)
    * Highlight Adjacent Alerts Minimum Group Size = 2
    * Draw Extension Lines = All Prices in Adjacent Alerts
    * Draw Extension Lines until End of Chart = No (intersection prix)

Formule decryptee :
  Pour chaque cellule a prix P dans la barre courante :
    bid_p = max(BVAP(P, 0), 1)         # zero handling : 0 -> 1
    ask_above = AVAP(P + TICKSIZE, 0)
    ratio_buy = ask_above / bid_p * 100
    is_imb_buy = ratio_buy >= threshold (600 ES / 1000 NQ)

    ask_p = max(AVAP(P, 0), 1)
    bid_below = BVAP(P - TICKSIZE, 0)
    ratio_sell = bid_below / ask_p * 100
    is_imb_sell = ratio_sell >= threshold

  ZONE = au moins min_group_size cellules consecutives is_imb=True
  ALERT FIRE = barre contient au moins 1 zone
  Extension lines = persistent jusqu'a touche prix futur (geree par
                    extension_lines_manager.ExtensionLineBuffer)

Features ML generees (8) :
  - bar_edge_buy_fire (1 si stack BUY detectee dans cette bar, 0 sinon)
  - bar_edge_sell_fire
  - bar_edge_buy_zone_size (nb cellules dans le max stack BUY ce bar, 0 si pas fire)
  - bar_edge_sell_zone_size
  - n_edge_buy_active (count zones BUY actives non touchees)
  - n_edge_sell_active
  - dist_edge_buy_nearest_pct (distance close vers zone BUY active la plus proche, en %)
  - dist_edge_sell_nearest_pct

Auteur : Phase B+++ Bloc 3 #1 (2026-04-26)
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from extension_lines_manager import ExtensionLineBuffer

TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick explicitement

# Seuils per-symbole (Jackson 26/04/2026)
EDGE_THRESHOLD_PCT = {
    "ES": 600,
    "NQ": 1000,
}
MIN_GROUP_SIZE = 2  # SC default Highlight Adjacent Alerts Minimum Group Size


def _detect_stacks_for_bar(
    cells: Dict[float, Dict[str, float]],
    threshold_pct: float,
    tick: float,
    min_group_size: int,
    side: str,
) -> list:
    """
    Detecte les stacks (groupes consecutifs cellules imb) dans 1 bar.

    Args:
        cells: dict[price -> {'ask_vol', 'bid_vol', ...}] pour 1 bar
        threshold_pct: seuil % (600 ES / 1000 NQ)
        tick: tick size
        min_group_size: taille mini groupe (default 2)
        side: 'buy' ou 'sell'

    Returns:
        list of stacks, chaque stack = list[float] de prix consecutifs
    """
    if not cells:
        return []

    prices_sorted = sorted(cells.keys())
    if len(prices_sorted) < 2:
        return []

    # Marquer chaque cellule imb_buy ou imb_sell
    is_imb = {}
    for i, p in enumerate(prices_sorted):
        c_p = cells[p]
        ask_p = c_p["ask_vol"]
        bid_p = c_p["bid_vol"]

        if side == "buy":
            # Cellule au-dessus (P + tick)
            p_above = round(p + tick, 4)
            cell_above = cells.get(p_above)
            if cell_above is None:
                # Pas de cellule au-dessus -> pas d'imbalance possible
                is_imb[p] = False
                continue
            ask_above = cell_above["ask_vol"]
            # Zero handling : Bid=0 -> 1
            bid_eff = max(bid_p, 1)
            ratio = (ask_above / bid_eff) * 100 if ask_above > 0 else 0
            is_imb[p] = ratio >= threshold_pct
        else:  # sell
            # Cellule en-dessous (P - tick)
            p_below = round(p - tick, 4)
            cell_below = cells.get(p_below)
            if cell_below is None:
                is_imb[p] = False
                continue
            bid_below = cell_below["bid_vol"]
            # Zero handling : Ask=0 -> 1
            ask_eff = max(ask_p, 1)
            ratio = (bid_below / ask_eff) * 100 if bid_below > 0 else 0
            is_imb[p] = ratio >= threshold_pct

    # Detecte runs de cellules consecutives imb=True
    stacks = []
    current_stack = []
    for i, p in enumerate(prices_sorted):
        if is_imb.get(p, False):
            # Verifier que c'est consecutif (pas de gap > tick)
            if current_stack and abs(p - current_stack[-1] - tick) > 1e-6:
                # Gap : termine le stack en cours
                if len(current_stack) >= min_group_size:
                    stacks.append(current_stack)
                current_stack = [p]
            else:
                current_stack.append(p)
        else:
            # Termine le stack en cours
            if len(current_stack) >= min_group_size:
                stacks.append(current_stack)
            current_stack = []
    # Stack final
    if len(current_stack) >= min_group_size:
        stacks.append(current_stack)

    return stacks


def apply_edge_zones(
    df: pd.DataFrame,
    footprint: Dict[int, Dict[float, Dict[str, float]]],
    symbol: str = "ES",
    threshold_pct: Optional[float] = None,
    min_group_size: int = MIN_GROUP_SIZE,
    tick: float = TICK_SIZE,
) -> pd.DataFrame:
    """
    Pipeline complet Edge Zones :
      1. Pour chaque bar : detecter stacks BUY + SELL
      2. Si stack detecte : ajouter zone au buffer + fire feature ce bar
      3. Mettre a jour zones actives (deactivate si touchees)
      4. Compute features bar par bar

    Args:
        df: DataFrame avec ts_event, high, low, close (ordre temporel)
        footprint: dict[bar_idx -> dict[price -> {'ask_vol', 'bid_vol', ...}]]
        symbol: 'ES' ou 'NQ' (determine seuil)
        threshold_pct: override seuil (sinon EDGE_THRESHOLD_PCT[symbol])
        min_group_size: cellules consecutives mini (default 2)
        tick: tick size

    Returns:
        df + 8 features ML (cf docstring module).
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    if threshold_pct is None:
        threshold_pct = EDGE_THRESHOLD_PCT.get(sym, 600)

    n = len(df)
    buffer = ExtensionLineBuffer()

    # Output arrays
    fire_buy = np.zeros(n, dtype=np.int8)
    fire_sell = np.zeros(n, dtype=np.int8)
    zone_size_buy = np.zeros(n, dtype=np.int32)
    zone_size_sell = np.zeros(n, dtype=np.int32)
    n_active_buy = np.zeros(n, dtype=np.int32)
    n_active_sell = np.zeros(n, dtype=np.int32)
    dist_buy = np.full(n, np.nan, dtype=np.float64)
    dist_sell = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        bar_high = df["high"].iloc[i]
        bar_low = df["low"].iloc[i]
        close = df["close"].iloc[i]

        # 1. UPDATE : deactivate zones existantes touchees par ce bar
        buffer.update_with_bar(i, bar_low, bar_high)

        # 2. DETECT stacks dans cette bar
        cells = footprint.get(i, {})
        if cells:
            stacks_buy = _detect_stacks_for_bar(cells, threshold_pct, tick, min_group_size, "buy")
            stacks_sell = _detect_stacks_for_bar(cells, threshold_pct, tick, min_group_size, "sell")

            if stacks_buy:
                fire_buy[i] = 1
                # Max stack size de ce bar
                zone_size_buy[i] = max(len(s) for s in stacks_buy)
                # Add chaque stack au buffer (zone independante)
                for s in stacks_buy:
                    buffer.add_zone(i, s, "buy")

            if stacks_sell:
                fire_sell[i] = 1
                zone_size_sell[i] = max(len(s) for s in stacks_sell)
                for s in stacks_sell:
                    buffer.add_zone(i, s, "sell")

        # 3. FEATURES : count active + nearest distance APRES update
        n_active_buy[i] = buffer.count_active("buy")
        n_active_sell[i] = buffer.count_active("sell")

        d_buy = buffer.nearest_distance("buy", close)
        d_sell = buffer.nearest_distance("sell", close)

        # Distances en % du close (ML-usable, pas de fuite instrument)
        if not np.isnan(d_buy) and close > 0:
            dist_buy[i] = (d_buy / close) * 100
        if not np.isnan(d_sell) and close > 0:
            dist_sell[i] = (d_sell / close) * 100

    df["bar_edge_buy_fire"] = fire_buy
    df["bar_edge_sell_fire"] = fire_sell
    df["bar_edge_buy_zone_size"] = zone_size_buy
    df["bar_edge_sell_zone_size"] = zone_size_sell
    df["n_edge_buy_active"] = n_active_buy
    df["n_edge_sell_active"] = n_active_sell
    df["dist_edge_buy_nearest_pct"] = dist_buy
    df["dist_edge_sell_nearest_pct"] = dist_sell

    return df


EDGE_ZONES_GENERATED = {
    "bar_edge_buy_fire", "bar_edge_sell_fire",
    "bar_edge_buy_zone_size", "bar_edge_sell_zone_size",
    "n_edge_buy_active", "n_edge_sell_active",
    "dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
}
