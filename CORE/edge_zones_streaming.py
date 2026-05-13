"""edge_zones_streaming.py

API streaming-aware du module `edge_zones_engine.py` (Sierra Chart Edge Zones).
Reproduit 8 features ML edge zones (BUY/SELL stacks d'imbalance Ask/Bid).

Architecture batch (edge_zones_engine.py:175-269) :
    apply_edge_zones(df, footprint, symbol) boucle bar par bar :
      1. buffer.update_with_bar(i, low, high)  # deactivate zones touchees
      2. detect stacks dans footprint[i]
      3. si stacks : buffer.add_zone() + fire feature
      4. compute features : count_active + nearest_distance

Le batch est DEJA row-by-row. Le streaming reutilise ExtensionLineBuffer
+ _detect_stacks_for_bar directement. State = buffer + bar_idx counter.

Convention pipeline :
    add_edge_zones_streaming(row, state, footprint_cells)
    where footprint_cells = dict[price -> {'ask_vol', 'bid_vol'}] pour
    cette bar (reconstruit par Live Enricher depuis trades_in_window).

Features (8) :
    bar_edge_buy_fire, bar_edge_sell_fire,
    bar_edge_buy_zone_size, bar_edge_sell_zone_size,
    n_edge_buy_active, n_edge_sell_active,
    dist_edge_buy_nearest_pct, dist_edge_sell_nearest_pct

Module batch INTOUCHE (additive-only).

Auteur : Phase 3b semaine 3 (2026-05-13)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np
import pandas as pd

from edge_zones_engine import _detect_stacks_for_bar, EDGE_THRESHOLD_PCT, MIN_GROUP_SIZE
from extension_lines_manager import ExtensionLineBuffer

# Tick policy : source unique de verite
try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


@dataclass
class EdgeZonesState:
    """State streaming Edge Zones.

    Pickle-safe : ExtensionLineBuffer contient une liste de Zone dataclasses
    (primitifs), bar_idx_counter int, scalars config.
    """
    symbol: str = "ES"
    tick: float = 0.25
    threshold_pct: float = 600.0
    min_group_size: int = MIN_GROUP_SIZE
    buffer: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    bar_idx: int = 0  # compteur incremente a chaque bar (mirror enumerate batch)


def make_edge_zones_state(
    symbol: str = "ES",
    threshold_pct: Optional[float] = None,
) -> "EdgeZonesState":
    """Factory EdgeZonesState avec config per-symbole.

    Mirror batch ligne 202-204 :
        sym = symbol.upper().split('.')[0]
        threshold_pct = EDGE_THRESHOLD_PCT.get(sym, 600)

    Args:
        symbol : ES, NQ, MGC (sans suffixe contrat ex 'ES.c.0' -> 'ES')
        threshold_pct : override seuil (sinon EDGE_THRESHOLD_PCT[symbol])
    """
    sym = symbol.upper().split(".")[0]
    if threshold_pct is None:
        threshold_pct = float(EDGE_THRESHOLD_PCT.get(sym, 600))
    return EdgeZonesState(
        symbol=sym,
        tick=_get_tick_size(sym),
        threshold_pct=threshold_pct,
        min_group_size=MIN_GROUP_SIZE,
        buffer=ExtensionLineBuffer(),
        bar_idx=0,
    )


def add_edge_zones_streaming(
    row: dict,
    state: EdgeZonesState,
    footprint_cells: Optional[Dict[float, Dict[str, float]]] = None,
) -> dict:
    """Sub-engine streaming Edge Zones — 8 features ML.

    Args:
        row : dict avec high, low, close.
        state : EdgeZonesState mutable (buffer + bar_idx counter).
        footprint_cells : dict[price -> {'ask_vol', 'bid_vol'}] pour cette bar.
                          None ou {} = pas de footprint disponible -> aucun stack.
                          Le Live Enricher reconstruit footprint depuis
                          trades_in_window (mirror footprint_builder logic).

    Returns:
        dict row + 8 features edge zones.
    """
    out = dict(row)

    # ─── Inputs ────────────────────────────────────────────────────────────
    bar_high = out.get("high")
    bar_low = out.get("low")
    close = out.get("close")
    # Safe cast
    try:
        bar_high_f = float(bar_high) if bar_high is not None else np.nan
    except (TypeError, ValueError):
        bar_high_f = np.nan
    try:
        bar_low_f = float(bar_low) if bar_low is not None else np.nan
    except (TypeError, ValueError):
        bar_low_f = np.nan
    try:
        close_f = float(close) if close is not None else np.nan
    except (TypeError, ValueError):
        close_f = np.nan

    fire_buy = 0
    fire_sell = 0
    zone_size_buy = 0
    zone_size_sell = 0

    # ─── 1. UPDATE : deactivate zones touchees par cette bar (mirror batch:225) ─
    if not (np.isnan(bar_low_f) or np.isnan(bar_high_f)):
        state.buffer.update_with_bar(state.bar_idx, bar_low_f, bar_high_f)

    # ─── 2. DETECT stacks dans footprint cells (mirror batch:229-245) ──────
    if footprint_cells:
        stacks_buy = _detect_stacks_for_bar(
            footprint_cells, state.threshold_pct, state.tick,
            state.min_group_size, "buy",
        )
        stacks_sell = _detect_stacks_for_bar(
            footprint_cells, state.threshold_pct, state.tick,
            state.min_group_size, "sell",
        )

        if stacks_buy:
            fire_buy = 1
            zone_size_buy = max(len(s) for s in stacks_buy)
            for s in stacks_buy:
                state.buffer.add_zone(state.bar_idx, s, "buy")

        if stacks_sell:
            fire_sell = 1
            zone_size_sell = max(len(s) for s in stacks_sell)
            for s in stacks_sell:
                state.buffer.add_zone(state.bar_idx, s, "sell")

    # ─── 3. FEATURES : count active + nearest distance (mirror batch:248-258) ─
    n_active_buy = state.buffer.count_active("buy")
    n_active_sell = state.buffer.count_active("sell")

    d_buy = state.buffer.nearest_distance("buy", close_f) if not np.isnan(close_f) else np.nan
    d_sell = state.buffer.nearest_distance("sell", close_f) if not np.isnan(close_f) else np.nan

    # Distances en % du close (ML-usable)
    if not np.isnan(d_buy) and not np.isnan(close_f) and close_f > 0:
        dist_buy_pct = (d_buy / close_f) * 100
    else:
        dist_buy_pct = np.nan
    if not np.isnan(d_sell) and not np.isnan(close_f) and close_f > 0:
        dist_sell_pct = (d_sell / close_f) * 100
    else:
        dist_sell_pct = np.nan

    out["bar_edge_buy_fire"] = fire_buy
    out["bar_edge_sell_fire"] = fire_sell
    out["bar_edge_buy_zone_size"] = zone_size_buy
    out["bar_edge_sell_zone_size"] = zone_size_sell
    out["n_edge_buy_active"] = n_active_buy
    out["n_edge_sell_active"] = n_active_sell
    out["dist_edge_buy_nearest_pct"] = dist_buy_pct
    out["dist_edge_sell_nearest_pct"] = dist_sell_pct

    # ─── Increment bar_idx APRES traitement ────────────────────────────────
    state.bar_idx += 1

    return out
