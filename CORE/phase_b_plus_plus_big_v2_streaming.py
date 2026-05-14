"""phase_b_plus_plus_big_v2_streaming.py

API streaming-aware phase_b_plus_plus_engine.py - LOT 2 (Big Orders V2).
Couvre add_big_orders_features_v2 : scan VAP cells par bar pour detecter
les grosses commandes (AskVol/BidVol >= seuil tier).

Features (10) :
  n_big_ask_v2_t1, t2, t3, t4 : count cellules AskVol >= seuil tier
  n_big_bid_v2_t1, t2, t3, t4 : count cellules BidVol >= seuil tier
  max_big_ask_vol_in_bar      : max AskVol sur toutes cellules de la bar
  max_big_bid_vol_in_bar      : max BidVol idem

Stateless : pure function par bar (consomme footprint_cells du caller).

Different de LOT 1 (trades aggregates) :
  LOT 1 = big orders au sens "trade individuel de taille >= seuil"
          (count trades, depuis trades_in_window)
  LOT 2 = big orders au sens "cellule VAP avec volume agrege >= seuil"
          (count cellules de prix, depuis footprint cells)

Tiers per-symbole BIG_ORDERS_TIERS_NEW (different de BIG_ORDER_TIERS LOT 1) :
  ES : [100, 150, None, None] (t3/t4 dropped audit 27/04)
  NQ : [40, 80, None, None]
  MGC : [10, 20, 30, None]

Convention pipeline : appele apres footprint_builder_streaming qui produit cells.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from phase_b_plus_plus_engine import BIG_ORDERS_TIERS_NEW

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


@dataclass
class BigOrdersV2State:
    """State streaming Big Orders V2.

    Stateless en pratique (config per-symbole uniquement).
    """
    symbol: str = "ES"
    tick: float = 0.25
    tiers: list = None  # list[int|None] de 4 elements

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = [100, 150, None, None]


def make_big_orders_v2_state(symbol: str = "ES") -> "BigOrdersV2State":
    """Factory per-symbole."""
    sym = symbol.upper().split(".")[0]
    tiers = list(BIG_ORDERS_TIERS_NEW.get(sym, BIG_ORDERS_TIERS_NEW["ES"]))
    return BigOrdersV2State(
        symbol=sym,
        tick=_get_tick_size(sym),
        tiers=tiers,
    )


def add_big_orders_v2_streaming(
    row: dict,
    state: BigOrdersV2State,
    footprint_cells: Optional[Dict[float, Dict[str, float]]] = None,
) -> dict:
    """Sub-engine streaming LOT 2 big_orders_v2 - 10 features.

    Args:
        row : dict (sera enrichi).
        state : BigOrdersV2State avec tiers per-symbole.
        footprint_cells : dict[price -> {ask_vol, bid_vol}] de la bar courante
                          (depuis build_footprint_cells_streaming).
                          None/{} = toutes features = 0.

    Returns:
        dict row + 10 features.
    """
    out = dict(row)

    # Init defaults (si pas de cells)
    for ti in (1, 2, 3, 4):
        out[f"n_big_ask_v2_t{ti}"] = 0
        out[f"n_big_bid_v2_t{ti}"] = 0
    out["max_big_ask_vol_in_bar"] = 0
    out["max_big_bid_vol_in_bar"] = 0

    if not footprint_cells:
        return out

    tiers = state.tiers
    n_ask_t = [0, 0, 0, 0]
    n_bid_t = [0, 0, 0, 0]
    bar_max_ask = 0
    bar_max_bid = 0

    for cell in footprint_cells.values():
        ask_v = cell.get("ask_vol", 0)
        bid_v = cell.get("bid_vol", 0)
        if ask_v > bar_max_ask:
            bar_max_ask = ask_v
        if bid_v > bar_max_bid:
            bar_max_bid = bid_v
        for ti_idx, seuil in enumerate(tiers):
            if seuil is None:
                continue
            if ask_v >= seuil:
                n_ask_t[ti_idx] += 1
            if bid_v >= seuil:
                n_bid_t[ti_idx] += 1

    for ti_idx in range(4):
        if tiers[ti_idx] is None:
            out[f"n_big_ask_v2_t{ti_idx + 1}"] = 0
            out[f"n_big_bid_v2_t{ti_idx + 1}"] = 0
        else:
            out[f"n_big_ask_v2_t{ti_idx + 1}"] = n_ask_t[ti_idx]
            out[f"n_big_bid_v2_t{ti_idx + 1}"] = n_bid_t[ti_idx]
    out["max_big_ask_vol_in_bar"] = int(bar_max_ask)
    out["max_big_bid_vol_in_bar"] = int(bar_max_bid)

    return out
