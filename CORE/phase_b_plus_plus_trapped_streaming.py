"""phase_b_plus_plus_trapped_streaming.py

API streaming-aware phase_b_plus_plus_engine.py - LOT 5 (Trapped Traders).
Couvre add_trapped_traders_features : detection trapped buyers/sellers +
Extension Lines persistantes + clusters.

Features (10) :
  bn_trapped_buyers_raw       : AskVol(top zone) >= seuil + finish<=30 + delta>0 + close<open
  bn_trapped_sellers_raw      : BidVol(bot zone) >= seuil + finish>=70 + delta<0 + close>open
  bn_trapped_buyers_at_resistance  : raw AND near_resistance (from LOT 4)
  bn_trapped_sellers_at_support    : raw AND near_support
  n_trapped_buyers_zones_active    : count Extension Lines actives
  n_trapped_sellers_zones_active   : idem
  dist_trapped_buyers_nearest_pct  : distance % close -> nearest zone active
  dist_trapped_sellers_nearest_pct : idem
  n_trapped_buyers_cluster_within_0_2pct : zones actives dans 0.2% close
  n_trapped_sellers_cluster_within_0_2pct: idem

SC params Jackson 27/04 :
  TRAPPED_THRESHOLD_VOL : ES=30, NQ=10 (ratio 3:1 coherent Big Orders)
  TRAPPED_FINISH_PCT_BUYERS = 30 (close dans bottom 30% du range)
  TRAPPED_FINISH_PCT_SELLERS = 70 (close dans top 70%)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

from extension_lines_manager import ExtensionLineBuffer
from phase_b_plus_plus_engine import (
    TRAPPED_THRESHOLD_VOL,
    TRAPPED_FINISH_PCT_BUYERS,
    TRAPPED_FINISH_PCT_SELLERS,
)

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


@dataclass
class TrappedTradersState:
    """State streaming Trapped Traders."""
    symbol: str = "ES"
    tick: float = 0.25
    threshold_vol: int = 10
    bar_idx: int = 0
    buf_buy: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    buf_sell: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)


def make_trapped_traders_state(symbol: str = "ES") -> "TrappedTradersState":
    """Factory per-symbole."""
    sym = symbol.upper().split(".")[0]
    return TrappedTradersState(
        symbol=sym,
        tick=_get_tick_size(sym),
        threshold_vol=TRAPPED_THRESHOLD_VOL.get(sym, 10),
        buf_buy=ExtensionLineBuffer(),
        buf_sell=ExtensionLineBuffer(),
        bar_idx=0,
    )


def _safe_float(x) -> float:
    if x is None:
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def add_trapped_traders_streaming(
    row: dict,
    state: TrappedTradersState,
    footprint_cells: Optional[Dict[float, Dict[str, float]]] = None,
    cluster_pct: float = 0.2,
) -> dict:
    """Sub-engine streaming LOT 5 Trapped Traders - 10 features.

    Args:
        row : dict avec open, high, low, close, delta_bar + near_resistance_level,
              near_support_level (depuis LOT 4 absorb).
        state : TrappedTradersState mutable (2 ExtensionLineBuffer).
        footprint_cells : dict[price -> {ask_vol, bid_vol}].
        cluster_pct : range cluster local (default 0.2%).

    Returns:
        dict row + 10 features.
    """
    out = dict(row)

    # Init defaults
    out["bn_trapped_buyers_raw"] = 0
    out["bn_trapped_sellers_raw"] = 0
    out["bn_trapped_buyers_at_resistance"] = 0
    out["bn_trapped_sellers_at_support"] = 0
    out["n_trapped_buyers_zones_active"] = 0
    out["n_trapped_sellers_zones_active"] = 0
    out["dist_trapped_buyers_nearest_pct"] = np.nan
    out["dist_trapped_sellers_nearest_pct"] = np.nan
    out["n_trapped_buyers_cluster_within_0_2pct"] = 0
    out["n_trapped_sellers_cluster_within_0_2pct"] = 0

    h = _safe_float(out.get("high"))
    l = _safe_float(out.get("low"))
    op = _safe_float(out.get("open"))
    c = _safe_float(out.get("close"))
    delta = _safe_float(out.get("delta_bar"))
    if np.isnan(delta):
        delta = 0.0

    # Inputs niveaux (depuis LOT 4 absorb) - dependency check anti Pattern 11
    # LOT 4 add_stack_absorb_streaming DOIT etre appele AVANT LOT 5 dans le pipeline.
    # Sans LOT 4, near_*=0 silently -> at_resistance/at_support toujours 0 (silent fallback).
    if "near_resistance_level" not in row or "near_support_level" not in row:
        raise ValueError(
            "LOT 5 trapped_traders requires LOT 4 absorb to run first. "
            "Missing 'near_resistance_level' or 'near_support_level' in row. "
            "Chain order : LOT 1 (trades) -> LOT 4 (absorb) -> LOT 5 (trapped)."
        )
    near_res = int(out.get("near_resistance_level", 0)) if out.get("near_resistance_level") is not None else 0
    near_sup = int(out.get("near_support_level", 0)) if out.get("near_support_level") is not None else 0

    tick = state.tick
    threshold = state.threshold_vol
    bar_idx = state.bar_idx

    # ─── 1. UPDATE buffers : deactivate zones touchees par ce bar ───────────
    if not (np.isnan(l) or np.isnan(h)):
        state.buf_buy.update_with_bar(bar_idx, l, h)
        state.buf_sell.update_with_bar(bar_idx, l, h)

    # ─── 2. DETECT trapped (si OHLCV + cells dispo) ─────────────────────────
    trap_buy = 0
    trap_sell = 0
    if footprint_cells and not (np.isnan(h) or np.isnan(l) or np.isnan(op) or np.isnan(c)):
        bar_range = h - l
        finish_pct = (c - l) / bar_range * 100 if bar_range > 0 else 50.0

        # Trapped buyers : AskVol(top zone) seuil + finish<=30 + delta>0 + close<open
        ask_h = 0.0
        for k in (0, 1):
            p = round((h - tick * k) / tick) * tick
            cell_p = footprint_cells.get(p)
            if cell_p:
                ask_h += cell_p.get("ask_vol", 0)
        if (
            ask_h >= threshold
            and finish_pct <= TRAPPED_FINISH_PCT_BUYERS
            and delta > 0
            and c < op
        ):
            trap_buy = 1
            state.buf_buy.add_zone(bar_idx, [float(h)], "buy")

        # Trapped sellers : BidVol(bot zone) seuil + finish>=70 + delta<0 + close>open
        bid_l = 0.0
        for k in (0, 1):
            p = round((l + tick * k) / tick) * tick
            cell_p = footprint_cells.get(p)
            if cell_p:
                bid_l += cell_p.get("bid_vol", 0)
        if (
            bid_l >= threshold
            and finish_pct >= TRAPPED_FINISH_PCT_SELLERS
            and delta < 0
            and c > op
        ):
            trap_sell = 1
            state.buf_sell.add_zone(bar_idx, [float(l)], "sell")

    out["bn_trapped_buyers_raw"] = trap_buy
    out["bn_trapped_sellers_raw"] = trap_sell

    # ─── 3. at_resistance / at_support (raw AND near) ───────────────────────
    out["bn_trapped_buyers_at_resistance"] = 1 if (trap_buy == 1 and near_res == 1) else 0
    out["bn_trapped_sellers_at_support"] = 1 if (trap_sell == 1 and near_sup == 1) else 0

    # ─── 4. Features Extension Lines (count + nearest + cluster) ────────────
    out["n_trapped_buyers_zones_active"] = state.buf_buy.count_active("buy")
    out["n_trapped_sellers_zones_active"] = state.buf_sell.count_active("sell")

    if not np.isnan(c) and c > 0:
        d_buy = state.buf_buy.nearest_distance("buy", c)
        d_sell = state.buf_sell.nearest_distance("sell", c)
        out["dist_trapped_buyers_nearest_pct"] = (d_buy / c) * 100 if not np.isnan(d_buy) else np.nan
        out["dist_trapped_sellers_nearest_pct"] = (d_sell / c) * 100 if not np.isnan(d_sell) else np.nan

        cluster_range = c * (cluster_pct / 100)
        cluster_low = c - cluster_range
        cluster_high = c + cluster_range
        out["n_trapped_buyers_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_buy.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        out["n_trapped_sellers_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_sell.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )

    state.bar_idx += 1
    return out
