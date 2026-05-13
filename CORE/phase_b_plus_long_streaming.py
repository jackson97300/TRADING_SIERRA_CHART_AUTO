"""phase_b_plus_long_streaming.py

API streaming-aware Phase B+ LONG features (NON-LOOKAHEAD, 13 features).
Complement du commit 394db1b qui livrait phase_b_plus_streaming (74 features
NON-LOOKAHEAD). Cette extension porte les features LONG BAR + Extension Lines
+ long_updown formule NQ qui n'utilisent PAS de lookahead bar T+1.

Features (13) :
  Long bar (5) :
    long_up_bar, long_dn_bar, bar_body_ticks,
    range_h_minus_lprev_ticks, range_hprev_minus_l_ticks
  Long Extension Lines + clusters (6) :
    n_long_up_zones_active, n_long_dn_zones_active,
    dist_long_up_nearest_pct, dist_long_dn_nearest_pct,
    n_long_up_cluster_within_0_2pct, n_long_dn_cluster_within_0_2pct
  Long UpDown pattern formule NQ (2) :
    long_dn_up_pattern, long_up_dn_pattern

NB : formule ES de long_updown_pattern utilise O[+1], H[+1] (lookahead) ->
NON portable ici, sera dans le commit lag-1 suivant.

Convention pipeline :
  add_phase_b_plus_streaming (74 features, commit 394db1b)
  + add_phase_b_plus_long_streaming (13 features, CE COMMIT)
  + add_phase_b_plus_color_streaming (10 features lag-1, commit suivant)

Module batch INTOUCHE.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from phase_b_plus_engine import LONG_BAR_THRESHOLD_TICKS, LONG_UPDN_THRESHOLD_TICKS
from extension_lines_manager import ExtensionLineBuffer

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


@dataclass
class LongBarState:
    """State streaming Phase B+ LONG features.

    Pickle-safe : primitifs + 2 ExtensionLineBuffer + scalars config.
    """
    symbol: str = "ES"
    tick: float = 0.25
    long_threshold_ticks: int = 12     # ES default, NQ=24
    long_updn_threshold_ticks: int = 9  # ES default (lookahead), NQ=40 (no lookahead)

    # History 2 bars en arriere (long_updown_pattern NQ utilise [-2], [-1])
    # [-1] = prev bar
    prev_open: Optional[float] = None
    prev_high: Optional[float] = None
    prev_low: Optional[float] = None
    prev_close: Optional[float] = None
    # [-2] = prev_prev bar
    prev2_open: Optional[float] = None
    prev2_high: Optional[float] = None
    prev2_low: Optional[float] = None
    prev2_close: Optional[float] = None

    # Extension Line buffers
    buf_up: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    buf_dn: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)

    bar_idx: int = 0


def make_long_bar_state(symbol: str = "ES") -> "LongBarState":
    """Factory per-symbole : tick + thresholds."""
    sym = symbol.upper().split(".")[0]
    return LongBarState(
        symbol=sym,
        tick=_get_tick_size(sym),
        long_threshold_ticks=LONG_BAR_THRESHOLD_TICKS.get(sym, 24),
        long_updn_threshold_ticks=LONG_UPDN_THRESHOLD_TICKS.get(sym, 40),
        buf_up=ExtensionLineBuffer(),
        buf_dn=ExtensionLineBuffer(),
        bar_idx=0,
    )


def add_phase_b_plus_long_streaming(
    row: dict,
    state: LongBarState,
    cluster_pct: float = 0.2,
) -> dict:
    """Sub-engine streaming LONG features (13 features NON-LOOKAHEAD).

    Args:
        row : dict avec open, high, low, close.
        state : LongBarState mutable (prev bars + Extension Line buffers + bar_idx).
        cluster_pct : range autour du close (en %) pour cluster local (default 0.2%).

    Returns:
        dict row + 13 features.
    """
    out = dict(row)

    # ─── Extract inputs ────────────────────────────────────────────────────
    try:
        o = float(out["open"]) if out.get("open") is not None else np.nan
        h = float(out["high"]) if out.get("high") is not None else np.nan
        l = float(out["low"]) if out.get("low") is not None else np.nan
        c = float(out["close"]) if out.get("close") is not None else np.nan
    except (TypeError, ValueError):
        o = h = l = c = np.nan

    tick = state.tick
    threshold_long = state.long_threshold_ticks * tick
    threshold_updn = state.long_updn_threshold_ticks * tick

    # ═══════════════════════════════════════════════════════════════════════
    # 1. LONG UP / DN bar (utilise [-1], NON-lookahead)
    # ═══════════════════════════════════════════════════════════════════════
    # LONG UP   = O > C[-1] AND H > L[-1] + threshold
    # LONG DOWN = O < C[-1] AND H[-1] > L + threshold
    long_up = 0
    long_dn = 0
    if state.prev_close is not None and state.prev_low is not None and state.prev_high is not None:
        if not np.isnan(o) and not np.isnan(h):
            if o > state.prev_close and h > state.prev_low + threshold_long:
                long_up = 1
        if not np.isnan(o) and not np.isnan(l):
            if o < state.prev_close and state.prev_high > l + threshold_long:
                long_dn = 1
    out["long_up_bar"] = long_up
    out["long_dn_bar"] = long_dn

    # ═══════════════════════════════════════════════════════════════════════
    # 2. bar_body_ticks + range_h_minus_lprev + range_hprev_minus_l
    # ═══════════════════════════════════════════════════════════════════════
    # bar_body_ticks = |close - open| / tick (round)
    if not (np.isnan(o) or np.isnan(c)):
        out["bar_body_ticks"] = round(abs(c - o) / tick)
    else:
        out["bar_body_ticks"] = np.nan

    # range_h_minus_lprev = (H - L[-1]) / tick
    if state.prev_low is not None and not np.isnan(h):
        out["range_h_minus_lprev_ticks"] = round((h - state.prev_low) / tick)
    else:
        out["range_h_minus_lprev_ticks"] = np.nan

    # range_hprev_minus_l = (H[-1] - L) / tick
    if state.prev_high is not None and not np.isnan(l):
        out["range_hprev_minus_l_ticks"] = round((state.prev_high - l) / tick)
    else:
        out["range_hprev_minus_l_ticks"] = np.nan

    # ═══════════════════════════════════════════════════════════════════════
    # 3. LONG UPDOWN PATTERN formule NQ (sans lookahead, utilise [-2], [-1])
    # ═══════════════════════════════════════════════════════════════════════
    # NQ formule (Chart 23 NQ ID 23/24, threshold 40t) :
    #   LONG DOWN UP = O[-1]<C[-2], H[-2]>L[-1]+40t, O>C[-1], H>L[-1]+40t, H>H[-1]
    #   LONG UP DOWN = O[-1]>C[-2], H[-1]>L[-2]+40t, O<C[-1], H[-1]>L+40t, L<L[-1]
    long_dn_up_pattern = 0
    long_up_dn_pattern = 0
    if (
        state.prev_open is not None and state.prev_high is not None
        and state.prev_low is not None and state.prev_close is not None
        and state.prev2_close is not None and state.prev2_high is not None
        and state.prev2_low is not None
    ):
        # LONG DOWN UP (rejection bear -> bull continuation)
        cond1_dnup = state.prev_open < state.prev2_close
        cond2_dnup = state.prev2_high > state.prev_low + threshold_updn
        cond3_dnup = (not np.isnan(o)) and o > state.prev_close
        cond4_dnup = (not np.isnan(h)) and h > state.prev_low + threshold_updn
        cond5_dnup = (not np.isnan(h)) and h > state.prev_high
        if cond1_dnup and cond2_dnup and cond3_dnup and cond4_dnup and cond5_dnup:
            long_dn_up_pattern = 1

        # LONG UP DOWN (rejection bull -> bear continuation)
        cond1_updn = state.prev_open > state.prev2_close
        cond2_updn = state.prev_high > state.prev2_low + threshold_updn
        cond3_updn = (not np.isnan(o)) and o < state.prev_close
        cond4_updn = (not np.isnan(l)) and state.prev_high > l + threshold_updn
        cond5_updn = (not np.isnan(l)) and l < state.prev_low
        if cond1_updn and cond2_updn and cond3_updn and cond4_updn and cond5_updn:
            long_up_dn_pattern = 1

    out["long_dn_up_pattern"] = long_dn_up_pattern
    out["long_up_dn_pattern"] = long_up_dn_pattern

    # ═══════════════════════════════════════════════════════════════════════
    # 4. EXTENSION LINES long_up/dn (mirror add_long_extension_lines batch)
    # ═══════════════════════════════════════════════════════════════════════
    # 4a. UPDATE buffers : deactivate zones touchees par ce bar
    if not (np.isnan(l) or np.isnan(h)):
        state.buf_up.update_with_bar(state.bar_idx, l, h)
        state.buf_dn.update_with_bar(state.bar_idx, l, h)

    # 4b. ADD nouvelle zone si fire ce bar
    # LONG UP : zone au LOW de la bar (support)
    if long_up == 1 and not np.isnan(l):
        state.buf_up.add_zone(state.bar_idx, [float(l)], "buy")
    # LONG DOWN : zone au HIGH (resistance)
    if long_dn == 1 and not np.isnan(h):
        state.buf_dn.add_zone(state.bar_idx, [float(h)], "sell")

    # 4c. FEATURES count + nearest + cluster
    out["n_long_up_zones_active"] = state.buf_up.count_active("buy")
    out["n_long_dn_zones_active"] = state.buf_dn.count_active("sell")

    if not np.isnan(c) and c > 0:
        d_up = state.buf_up.nearest_distance("buy", c)
        d_dn = state.buf_dn.nearest_distance("sell", c)
        out["dist_long_up_nearest_pct"] = (d_up / c) * 100 if not np.isnan(d_up) else np.nan
        out["dist_long_dn_nearest_pct"] = (d_dn / c) * 100 if not np.isnan(d_dn) else np.nan

        # Cluster : count zones actives dans [close*(1-pct/100), close*(1+pct/100)]
        cluster_range = c * (cluster_pct / 100)
        cluster_low = c - cluster_range
        cluster_high = c + cluster_range
        out["n_long_up_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_up.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        out["n_long_dn_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_dn.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
    else:
        out["dist_long_up_nearest_pct"] = np.nan
        out["dist_long_dn_nearest_pct"] = np.nan
        out["n_long_up_cluster_within_0_2pct"] = 0
        out["n_long_dn_cluster_within_0_2pct"] = 0

    # ═══════════════════════════════════════════════════════════════════════
    # 5. Update history (shift bars : T-2 <- T-1, T-1 <- T)
    # ═══════════════════════════════════════════════════════════════════════
    state.prev2_open = state.prev_open
    state.prev2_high = state.prev_high
    state.prev2_low = state.prev_low
    state.prev2_close = state.prev_close
    state.prev_open = o if not np.isnan(o) else None
    state.prev_high = h if not np.isnan(h) else None
    state.prev_low = l if not np.isnan(l) else None
    state.prev_close = c if not np.isnan(c) else None

    state.bar_idx += 1

    return out
