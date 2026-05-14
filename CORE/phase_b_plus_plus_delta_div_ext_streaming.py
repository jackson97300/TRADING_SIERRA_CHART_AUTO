"""phase_b_plus_plus_delta_div_ext_streaming.py

API streaming-aware phase_b_plus_plus_engine.py - LOT 6/6 FINAL (Delta Div
Extension Lines + clusters). Couvre add_delta_div_extension_lines().

Features (6) :
  n_delta_div_buy_zones_active, n_delta_div_sell_zones_active
  dist_delta_div_buy_nearest_pct, dist_delta_div_sell_nearest_pct
  n_delta_div_buy_cluster_within_0_2pct, n_delta_div_sell_cluster_within_0_2pct

Convention pipeline : LOT 1 (trades_aggregates) AVANT LOT 6 car
delta_div_buy/sell fire flags sont calcules dans LOT 1.

Logique Jackson : delta_div_buy fire bar i -> zone SUPPORT au LOW persistante.
Mirror pattern color/long extension lines : zone meurt a la touche.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from extension_lines_manager import ExtensionLineBuffer


@dataclass
class DeltaDivExtState:
    """State streaming Delta Div Extension Lines."""
    bar_idx: int = 0
    buf_buy: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    buf_sell: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)


def make_delta_div_ext_state() -> "DeltaDivExtState":
    """Factory."""
    return DeltaDivExtState(
        buf_buy=ExtensionLineBuffer(),
        buf_sell=ExtensionLineBuffer(),
    )


def _safe_float(x) -> float:
    if x is None:
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def add_delta_div_ext_streaming(
    row: dict,
    state: DeltaDivExtState,
    cluster_pct: float = 0.2,
) -> dict:
    """Sub-engine streaming LOT 6 Delta Div Extension Lines - 6 features.

    Args:
        row : dict avec high, low, close, delta_div_buy, delta_div_sell
              (depuis LOT 1 trades_aggregates).
        state : DeltaDivExtState mutable (2 ExtensionLineBuffer).
        cluster_pct : range cluster local (default 0.2%).

    Returns:
        dict row + 6 features.
    """
    out = dict(row)

    # Init defaults
    out["n_delta_div_buy_zones_active"] = 0
    out["n_delta_div_sell_zones_active"] = 0
    out["dist_delta_div_buy_nearest_pct"] = np.nan
    out["dist_delta_div_sell_nearest_pct"] = np.nan
    out["n_delta_div_buy_cluster_within_0_2pct"] = 0
    out["n_delta_div_sell_cluster_within_0_2pct"] = 0

    h = _safe_float(out.get("high"))
    l = _safe_float(out.get("low"))
    c = _safe_float(out.get("close"))

    # Fire flags depuis LOT 1
    fire_buy = int(out.get("delta_div_buy", 0)) if out.get("delta_div_buy") is not None else 0
    fire_sell = int(out.get("delta_div_sell", 0)) if out.get("delta_div_sell") is not None else 0

    bar_idx = state.bar_idx

    # ─── 1. UPDATE buffers : deactivate zones touchees ─────────────────────
    if not (np.isnan(l) or np.isnan(h)):
        state.buf_buy.update_with_bar(bar_idx, l, h)
        state.buf_sell.update_with_bar(bar_idx, l, h)

    # ─── 2. ADD nouvelle zone si fire ce bar ────────────────────────────────
    if fire_buy == 1 and not np.isnan(l):
        state.buf_buy.add_zone(bar_idx, [float(l)], "buy")
    if fire_sell == 1 and not np.isnan(h):
        state.buf_sell.add_zone(bar_idx, [float(h)], "sell")

    # ─── 3. FEATURES count + nearest + cluster ──────────────────────────────
    out["n_delta_div_buy_zones_active"] = state.buf_buy.count_active("buy")
    out["n_delta_div_sell_zones_active"] = state.buf_sell.count_active("sell")

    if not np.isnan(c) and c > 0:
        d_buy = state.buf_buy.nearest_distance("buy", c)
        d_sell = state.buf_sell.nearest_distance("sell", c)
        out["dist_delta_div_buy_nearest_pct"] = (d_buy / c) * 100 if not np.isnan(d_buy) else np.nan
        out["dist_delta_div_sell_nearest_pct"] = (d_sell / c) * 100 if not np.isnan(d_sell) else np.nan

        cluster_range = c * (cluster_pct / 100)
        cluster_low = c - cluster_range
        cluster_high = c + cluster_range
        out["n_delta_div_buy_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_buy.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        out["n_delta_div_sell_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_sell.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )

    state.bar_idx += 1
    return out
