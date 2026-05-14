"""phase_b_plus_plus_absorb_streaming.py

API streaming-aware phase_b_plus_plus_engine.py - LOT 4 (Stack + Absorption).
Couvre add_stack_features + add_absorption_features.

Features (8) :
  STACK (2) :
    bn_stack_ask : N cellules pures ASK consecutives au top (Double ES / Triple NQ)
    bn_stack_bid : N cellules pures BID consecutives au bottom

  ABSORPTION (6) :
    bn_absorb_ask_raw       : O>C[-1] + AskVol(top zone) > 3*BidVol + > seuil
    bn_absorb_bid_raw       : O<C[-1] + BidVol(bot zone) > 3*AskVol + > seuil
    near_resistance_level   : close +/- proximity d'un niveau cle resistance
    near_support_level      : idem support
    bn_absorb_ask_at_level  : raw AND near_resistance
    bn_absorb_bid_at_level  : raw AND near_support

Convention : le row doit deja contenir les niveaux key (depuis phase_b_plus +
sessions_swings + helpers MenthorQ). Si absents -> near_*=0.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from phase_b_plus_plus_engine import (
    STACK_N_CELLS,
    ABSORPTION_THRESHOLD_ASK_BY_SYM,
    ABSORPTION_THRESHOLD_BID_BY_SYM,
    ABSORPTION_RATIO,
    ABSORPTION_PROXIMITY_TICKS,
    ABSORPTION_RESISTANCE_LEVELS,
    ABSORPTION_SUPPORT_LEVELS,
)

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size

# MQ distance columns (dist_*_pct)
MQ_RESISTANCE_DIST_COLS = ["dist_mq_call_pct", "dist_mq_call_0dte_pct"]
MQ_SUPPORT_DIST_COLS = ["dist_mq_put_pct", "dist_mq_put_0dte_pct"]
MQ_NEUTRAL_DIST_COLS = ["dist_mq_hvl_pct", "dist_mq_hvl_pct_z"]


@dataclass
class StackAbsorbState:
    """State streaming Stack + Absorption.

    Minimal state : prev_close pour O><C[-1] check.
    """
    symbol: str = "ES"
    tick: float = 0.25
    n_cells_stack: int = 2  # ES=2, NQ=3, MGC=2
    threshold_ask: int = 10
    threshold_bid: int = 20
    proximity_ticks: int = 5
    prev_close: Optional[float] = None


def make_stack_absorb_state(symbol: str = "ES") -> "StackAbsorbState":
    """Factory per-symbole."""
    sym = symbol.upper().split(".")[0]
    return StackAbsorbState(
        symbol=sym,
        tick=_get_tick_size(sym),
        n_cells_stack=STACK_N_CELLS.get(sym, 2),
        threshold_ask=ABSORPTION_THRESHOLD_ASK_BY_SYM.get(sym, 10),
        threshold_bid=ABSORPTION_THRESHOLD_BID_BY_SYM.get(sym, 20),
        proximity_ticks=ABSORPTION_PROXIMITY_TICKS.get(sym, 5),
    )


def _safe_float(x) -> float:
    if x is None:
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def add_stack_absorb_streaming(
    row: dict,
    state: StackAbsorbState,
    footprint_cells: Optional[Dict[float, Dict[str, float]]] = None,
) -> dict:
    """Sub-engine streaming LOT 4 stack + absorption - 8 features.

    Args:
        row : dict avec open, high, low, close + niveaux key (mq_*, prev_vah,
              pdh, cur_*, sess_*, ib_*, vwap_d_sd*) + dist_mq_*_pct.
        state : StackAbsorbState mutable (prev_close).
        footprint_cells : dict[price -> {ask_vol, bid_vol, total_vol}].

    Returns:
        dict row + 8 features.
    """
    out = dict(row)

    # Init defaults
    out["bn_stack_ask"] = 0
    out["bn_stack_bid"] = 0
    out["bn_absorb_ask_raw"] = 0
    out["bn_absorb_bid_raw"] = 0
    out["near_resistance_level"] = 0
    out["near_support_level"] = 0
    out["bn_absorb_ask_at_level"] = 0
    out["bn_absorb_bid_at_level"] = 0

    # Inputs OHLC
    o = _safe_float(out.get("open"))
    h = _safe_float(out.get("high"))
    l = _safe_float(out.get("low"))
    c = _safe_float(out.get("close"))

    if state.prev_close is None or np.isnan(o) or np.isnan(h) or np.isnan(l) or np.isnan(c):
        # Update prev_close avant return
        if not np.isnan(c):
            state.prev_close = c
        return out

    c_prev = state.prev_close
    tick = state.tick
    proximity = state.proximity_ticks * tick

    # ═══════════════════════════════════════════════════════════════════════
    # 1. STACK ASK / BID (N cellules pures consecutives)
    # ═══════════════════════════════════════════════════════════════════════
    if footprint_cells:
        n_cells = state.n_cells_stack
        # STACK ASK : O>C[-1] AND N cellules pures ASK au TOP (H, H-tick, ...)
        if o > c_prev:
            stack_ask_ok = True
            for k in range(n_cells):
                p = round((h - tick * k) / tick) * tick
                cell = footprint_cells.get(p)
                if cell is None:
                    stack_ask_ok = False
                    break
                ask_v = cell.get("ask_vol", 0)
                bid_v = cell.get("bid_vol", 0)
                if not (ask_v >= 1 and bid_v == 0):
                    stack_ask_ok = False
                    break
            if stack_ask_ok:
                out["bn_stack_ask"] = 1

        # STACK BID : O<C[-1] AND N cellules pures BID au BOT (L, L+tick, ...)
        if o < c_prev:
            stack_bid_ok = True
            for k in range(n_cells):
                p = round((l + tick * k) / tick) * tick
                cell = footprint_cells.get(p)
                if cell is None:
                    stack_bid_ok = False
                    break
                ask_v = cell.get("ask_vol", 0)
                bid_v = cell.get("bid_vol", 0)
                if not (ask_v == 0 and bid_v >= 1):
                    stack_bid_ok = False
                    break
            if stack_bid_ok:
                out["bn_stack_bid"] = 1

    # ═══════════════════════════════════════════════════════════════════════
    # 2. ABSORPTION raw ASK / BID (scan top zone [H, H-tick] et bot zone [L, L+tick])
    # ═══════════════════════════════════════════════════════════════════════
    if footprint_cells and o > c_prev:
        ask_h = 0.0
        bid_h = 0.0
        for k in (0, 1):
            p = round((h - tick * k) / tick) * tick
            cell_p = footprint_cells.get(p)
            if cell_p:
                ask_h += cell_p.get("ask_vol", 0)
                bid_h += cell_p.get("bid_vol", 0)
        if ask_h > bid_h * ABSORPTION_RATIO and ask_h > state.threshold_ask:
            out["bn_absorb_ask_raw"] = 1

    if footprint_cells and o < c_prev:
        ask_l = 0.0
        bid_l = 0.0
        for k in (0, 1):
            p = round((l + tick * k) / tick) * tick
            cell_p = footprint_cells.get(p)
            if cell_p:
                ask_l += cell_p.get("ask_vol", 0)
                bid_l += cell_p.get("bid_vol", 0)
        if bid_l > ask_l * ABSORPTION_RATIO and bid_l > state.threshold_bid:
            out["bn_absorb_bid_raw"] = 1

    # ═══════════════════════════════════════════════════════════════════════
    # 3. NEAR resistance / support (proximity niveaux key)
    # ═══════════════════════════════════════════════════════════════════════
    # Niveaux ABSOLUS (mq_call_resistance, prev_vah, pdh, etc.)
    near_res = 0
    near_sup = 0
    for col in ABSORPTION_RESISTANCE_LEVELS:
        lvl = _safe_float(out.get(col))
        if not np.isnan(lvl) and abs(lvl - c) <= proximity:
            near_res = 1
            break
    for col in ABSORPTION_SUPPORT_LEVELS:
        lvl = _safe_float(out.get(col))
        if not np.isnan(lvl) and abs(lvl - c) <= proximity:
            near_sup = 1
            break

    # MenthorQ via dist_pct (proximity en %)
    proximity_pct_bar = (proximity / c) * 100 if c > 0 else 0.0
    if near_res == 0:
        for col in MQ_RESISTANCE_DIST_COLS:
            d = _safe_float(out.get(col))
            if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                near_res = 1
                break
        if near_res == 0:
            for col in MQ_NEUTRAL_DIST_COLS:
                d = _safe_float(out.get(col))
                if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                    near_res = 1
                    break
    if near_sup == 0:
        for col in MQ_SUPPORT_DIST_COLS:
            d = _safe_float(out.get(col))
            if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                near_sup = 1
                break
        if near_sup == 0:
            for col in MQ_NEUTRAL_DIST_COLS:
                d = _safe_float(out.get(col))
                if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                    near_sup = 1
                    break

    out["near_resistance_level"] = near_res
    out["near_support_level"] = near_sup

    # ═══════════════════════════════════════════════════════════════════════
    # 4. ABSORPTION at_level (raw AND near)
    # ═══════════════════════════════════════════════════════════════════════
    out["bn_absorb_ask_at_level"] = 1 if (out["bn_absorb_ask_raw"] == 1 and near_res == 1) else 0
    out["bn_absorb_bid_at_level"] = 1 if (out["bn_absorb_bid_raw"] == 1 and near_sup == 1) else 0

    # Update state pour prochaine bar
    state.prev_close = c

    return out
