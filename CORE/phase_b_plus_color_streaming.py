"""phase_b_plus_color_streaming.py

API streaming-aware Phase B+ COLOR features (LAG-1, 12 features).
Reproduit fidelement les COLOR Up/Dn + Extension Lines + COLOR Up 2 Dn 2 +
long_updown formule ES qui utilisent O[+1], H[+1] (lookahead bar T+1).

CONVENTION LAG-1 :
  Le batch utilise df.shift(-1) (= bar future). En streaming impossible
  d'acceder a T+1 au temps T.
  Solution : a chaque appel `add_phase_b_plus_color_streaming(row_T+1, state)`,
  on calcule color pour state.prev_bar (= bar T) avec inputs de la bar courante
  (= T+1 du point de vue de bar T). On emit la valeur de bar T DANS le row T+1.

  Convention :
    batch_df.iloc[T]["bn_color_up_fwd1"]  ==  stream_df.iloc[T+1]["bn_color_up_fwd1"]

  C'est EXACTEMENT le comportement Sierra Chart natif : le marker COLOR UP
  apparait sur bar T quand bar T+1 se ferme (rendu retroactif).

Features (12) :
  COLOR Up/Dn (4) :
    bn_color_up_fwd1, bn_color_dn_fwd1
    bn_color_up_2_fwd1, bn_color_dn_2_fwd1 (window 4 bars : T-2, T-1, T, T+1)
  COLOR Extension Lines + clusters (6) :
    n_color_up/dn_zones_active
    dist_color_up/dn_nearest_pct
    n_color_up/dn_cluster_within_0_2pct
  Long UpDown pattern formule ES (2 lookahead [+1]) :
    long_dn_up_pattern_es, long_up_dn_pattern_es

NB : long_updown_pattern formule ES utilise [+1] lookahead + sortie sous le
meme nom 'long_dn_up_pattern' et 'long_up_dn_pattern' que la formule NQ.
Convention : si symbol='ES', on emit ces 2 colonnes AVEC lag-1.

Convention pipeline :
  add_phase_b_plus_streaming (74 features non-lookahead)
  + add_phase_b_plus_long_streaming (13 features non-lookahead complement)
  + add_phase_b_plus_color_streaming (12 features lag-1, CE COMMIT)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from phase_b_plus_engine import COLOR_THRESHOLD_TICKS, LONG_UPDN_THRESHOLD_TICKS
from extension_lines_manager import ExtensionLineBuffer

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


@dataclass
class ColorBarState:
    """State streaming COLOR + Extension Lines.

    Garde history des 3 dernieres bars (T-3, T-2, T-1 du point de vue de bar
    courante T qui sera "next" pour color de T-1) pour COLOR UP 2 qui a un
    window 4 bars (i-2, i-1, i, i+1).
    """
    symbol: str = "ES"
    tick: float = 0.25
    color_threshold_ticks: int = 12       # ES default, NQ=60
    long_updn_threshold_ticks: int = 9    # ES default (lookahead lag-1), NQ=40 (direct)

    # History des bars T-1, T-2, T-3 (vus dans le passe). Bar courante = T (input row).
    # On calcule color pour state.prev1_bar (= T-1) en utilisant bar T (= row courant).
    prev1_open: Optional[float] = None    # T-1
    prev1_high: Optional[float] = None
    prev1_low: Optional[float] = None
    prev1_close: Optional[float] = None
    prev2_open: Optional[float] = None    # T-2
    prev2_high: Optional[float] = None
    prev2_low: Optional[float] = None
    prev2_close: Optional[float] = None
    prev3_open: Optional[float] = None    # T-3 (pour COLOR UP 2 : besoin de O[i-1], H[i-1] avec i = T-1)
    prev3_high: Optional[float] = None
    prev3_low: Optional[float] = None
    prev3_close: Optional[float] = None

    # Extension Line buffers
    buf_up: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    buf_dn: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)

    # bar_idx counter (incremente par bar reelle, pas par calcul lag-1)
    bar_idx: int = 0


def make_color_bar_state(symbol: str = "ES") -> "ColorBarState":
    """Factory per-symbole."""
    sym = symbol.upper().split(".")[0]
    return ColorBarState(
        symbol=sym,
        tick=_get_tick_size(sym),
        color_threshold_ticks=COLOR_THRESHOLD_TICKS.get(sym, 60),
        long_updn_threshold_ticks=LONG_UPDN_THRESHOLD_TICKS.get(sym, 40),
        buf_up=ExtensionLineBuffer(),
        buf_dn=ExtensionLineBuffer(),
        bar_idx=0,
    )


def add_phase_b_plus_color_streaming(
    row: dict,
    state: ColorBarState,
    cluster_pct: float = 0.2,
) -> dict:
    """Sub-engine streaming COLOR + Extension Lines + long_updown_ES (12 features, lag-1).

    CONVENTION LAG-1 : les features emitted dans le row courant (bar T)
    sont en realite la valeur de bar T-1 (calculee maintenant qu'on a vu T).

    batch_df.iloc[T-1]["bn_color_up_fwd1"]  ==  stream_df.iloc[T]["bn_color_up_fwd1"]

    Args:
        row : dict avec open, high, low, close de la bar COURANTE (T).
        state : ColorBarState mutable.
        cluster_pct : range cluster local (default 0.2%).

    Returns:
        dict row + 12 features (valeurs pour bar T-1).
    """
    out = dict(row)

    # ─── Extract inputs bar T (= "next" du point de vue de bar T-1) ─────────
    try:
        o_t = float(out["open"]) if out.get("open") is not None else np.nan
        h_t = float(out["high"]) if out.get("high") is not None else np.nan
        l_t = float(out["low"]) if out.get("low") is not None else np.nan
        c_t = float(out["close"]) if out.get("close") is not None else np.nan
    except (TypeError, ValueError):
        o_t = h_t = l_t = c_t = np.nan

    tick = state.tick
    threshold_color = state.color_threshold_ticks * tick
    threshold_updn = state.long_updn_threshold_ticks * tick

    # On va calculer color pour bar T-1 (= state.prev1_*)
    # avec inputs : O[T] = o_t, H[T] = h_t, L[T] = l_t (= O[+1], H[+1], L[+1] du pov T-1)
    # et C[T-1] = state.prev1_close, L[T-1] = state.prev1_low, H[T-1] = state.prev1_high.

    color_up = 0
    color_dn = 0
    color_up_2 = 0
    color_dn_2 = 0
    long_dn_up_es = 0
    long_up_dn_es = 0

    # ═══════════════════════════════════════════════════════════════════════
    # 1. COLOR UP / COLOR DN (lookahead [+1])
    # ═══════════════════════════════════════════════════════════════════════
    # COLOR UP @ bar T-1 = (O[T] > C[T-1]) ET (H[T] > L[T-1] + threshold) ET (H[T] > H[T-1])
    if (
        state.prev1_close is not None and state.prev1_low is not None
        and state.prev1_high is not None
        and not (np.isnan(o_t) or np.isnan(h_t))
    ):
        if (
            o_t > state.prev1_close
            and h_t > state.prev1_low + threshold_color
            and h_t > state.prev1_high
        ):
            color_up = 1

    # COLOR DN @ bar T-1 = (O[T] < C[T-1]) ET (H[T-1] > L[T] + threshold) ET (L[T] < L[T-1])
    if (
        state.prev1_close is not None and state.prev1_low is not None
        and state.prev1_high is not None
        and not (np.isnan(o_t) or np.isnan(l_t))
    ):
        if (
            o_t < state.prev1_close
            and state.prev1_high > l_t + threshold_color
            and l_t < state.prev1_low
        ):
            color_dn = 1

    # ═══════════════════════════════════════════════════════════════════════
    # 2. COLOR UP 2 / DN 2 : besoin de COLOR sur bar T-1 ET COLOR sur bar T-3
    # ═══════════════════════════════════════════════════════════════════════
    # COLOR UP 2 @ bar T-1 = COLOR UP[T-1] ET COLOR UP[T-3] ET L[T-1] > L[T-2]
    # COLOR UP @ bar T-3 = (O[T-2]>C[T-3]) ET (H[T-2]>L[T-3]+threshold) ET (H[T-2]>H[T-3])
    color_up_at_t3 = False
    if (
        state.prev3_close is not None and state.prev3_low is not None
        and state.prev3_high is not None
        and state.prev2_open is not None and state.prev2_high is not None
    ):
        if (
            state.prev2_open > state.prev3_close
            and state.prev2_high > state.prev3_low + threshold_color
            and state.prev2_high > state.prev3_high
        ):
            color_up_at_t3 = True
    if (
        color_up == 1 and color_up_at_t3
        and state.prev1_low is not None and state.prev2_low is not None
        and state.prev1_low > state.prev2_low
    ):
        color_up_2 = 1

    # COLOR DN 2 @ bar T-1 = COLOR DN[T-1] ET COLOR DN[T-3] ET H[T-1] < H[T-2]
    # COLOR DN @ bar T-3 = (O[T-2]<C[T-3]) ET (H[T-3]>L[T-2]+threshold) ET (L[T-2]<L[T-3])
    color_dn_at_t3 = False
    if (
        state.prev3_close is not None and state.prev3_high is not None
        and state.prev3_low is not None
        and state.prev2_open is not None and state.prev2_low is not None
    ):
        if (
            state.prev2_open < state.prev3_close
            and state.prev3_high > state.prev2_low + threshold_color
            and state.prev2_low < state.prev3_low
        ):
            color_dn_at_t3 = True
    if (
        color_dn == 1 and color_dn_at_t3
        and state.prev1_high is not None and state.prev2_high is not None
        and state.prev1_high < state.prev2_high
    ):
        color_dn_2 = 1

    out["bn_color_up_fwd1"] = color_up
    out["bn_color_dn_fwd1"] = color_dn
    out["bn_color_up_2_fwd1"] = color_up_2
    out["bn_color_dn_2_fwd1"] = color_dn_2

    # ═══════════════════════════════════════════════════════════════════════
    # 3. LONG UP DOWN / DOWN UP formule ES (lookahead [+1], pour bar T-1)
    # ═══════════════════════════════════════════════════════════════════════
    # ES formule (3 bars window : T-2, T-1, T pour bar T-1) :
    #   LONG DOWN UP @ T-1 = (O[T-1]<C[T-2], H[T-2]>L[T-1]+9t,
    #                         O[T]>C[T-1], H[T]>L[T-1]+9t, H[T]>H[T-2])
    #   LONG UP DOWN @ T-1 = (O[T-1]>C[T-2], H[T-1]>L[T-2]+9t,
    #                         O[T]<C[T-1], H[T-1]>L[T]+9t, L[T]<L[T-2])
    if (
        state.prev1_open is not None and state.prev1_high is not None
        and state.prev1_low is not None and state.prev1_close is not None
        and state.prev2_close is not None and state.prev2_high is not None
        and state.prev2_low is not None
    ):
        # LONG DOWN UP ES
        cond1 = state.prev1_open < state.prev2_close
        cond2 = state.prev2_high > state.prev1_low + threshold_updn
        cond3 = (not np.isnan(o_t)) and o_t > state.prev1_close
        cond4 = (not np.isnan(h_t)) and h_t > state.prev1_low + threshold_updn
        cond5 = (not np.isnan(h_t)) and h_t > state.prev2_high
        if cond1 and cond2 and cond3 and cond4 and cond5:
            long_dn_up_es = 1

        # LONG UP DOWN ES
        cond1u = state.prev1_open > state.prev2_close
        cond2u = state.prev1_high > state.prev2_low + threshold_updn
        cond3u = (not np.isnan(o_t)) and o_t < state.prev1_close
        cond4u = (not np.isnan(l_t)) and state.prev1_high > l_t + threshold_updn
        cond5u = (not np.isnan(l_t)) and l_t < state.prev2_low
        if cond1u and cond2u and cond3u and cond4u and cond5u:
            long_up_dn_es = 1

    out["long_dn_up_pattern_es"] = long_dn_up_es
    out["long_up_dn_pattern_es"] = long_up_dn_es

    # ═══════════════════════════════════════════════════════════════════════
    # 4. EXTENSION LINES COLOR (mirror batch)
    # ═══════════════════════════════════════════════════════════════════════
    # update buffers : deactivate zones touchees par bar T-1 (et toutes les
    # precedentes). Convention batch : update_with_bar(i, bar_low[i], bar_high[i]).
    # En lag-1, on update avec bar T-1 (= prev1) AVANT d'ajouter sa zone.
    # Le bar_idx utilise = state.bar_idx - 1 (= index de bar T-1 dans batch).
    bar_idx_for_t_minus_1 = state.bar_idx  # cf increment final : pre-increment, this is T-1's idx
    if state.prev1_low is not None and state.prev1_high is not None:
        state.buf_up.update_with_bar(bar_idx_for_t_minus_1,
                                      state.prev1_low, state.prev1_high)
        state.buf_dn.update_with_bar(bar_idx_for_t_minus_1,
                                      state.prev1_low, state.prev1_high)

    # ADD nouvelle zone si color fire pour bar T-1
    if color_up == 1 and state.prev1_low is not None:
        state.buf_up.add_zone(bar_idx_for_t_minus_1, [float(state.prev1_low)], "buy")
    if color_dn == 1 and state.prev1_high is not None:
        state.buf_dn.add_zone(bar_idx_for_t_minus_1, [float(state.prev1_high)], "sell")

    # FEATURES count + nearest + cluster — calculees au CLOSE de bar T-1
    # donc avec close de T-1 (= state.prev1_close)
    close_for_dist = state.prev1_close
    out["n_color_up_zones_active"] = state.buf_up.count_active("buy")
    out["n_color_dn_zones_active"] = state.buf_dn.count_active("sell")

    if close_for_dist is not None and close_for_dist > 0:
        d_up = state.buf_up.nearest_distance("buy", close_for_dist)
        d_dn = state.buf_dn.nearest_distance("sell", close_for_dist)
        out["dist_color_up_nearest_pct"] = (
            (d_up / close_for_dist) * 100 if not np.isnan(d_up) else np.nan
        )
        out["dist_color_dn_nearest_pct"] = (
            (d_dn / close_for_dist) * 100 if not np.isnan(d_dn) else np.nan
        )

        cluster_range = close_for_dist * (cluster_pct / 100)
        cluster_low = close_for_dist - cluster_range
        cluster_high = close_for_dist + cluster_range
        out["n_color_up_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_up.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        out["n_color_dn_cluster_within_0_2pct"] = sum(
            1 for z in state.buf_dn.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
    else:
        out["dist_color_up_nearest_pct"] = np.nan
        out["dist_color_dn_nearest_pct"] = np.nan
        out["n_color_up_cluster_within_0_2pct"] = 0
        out["n_color_dn_cluster_within_0_2pct"] = 0

    # ═══════════════════════════════════════════════════════════════════════
    # 5. Shift history bars (T-3 <- T-2, T-2 <- T-1, T-1 <- T)
    # ═══════════════════════════════════════════════════════════════════════
    state.prev3_open = state.prev2_open
    state.prev3_high = state.prev2_high
    state.prev3_low = state.prev2_low
    state.prev3_close = state.prev2_close
    state.prev2_open = state.prev1_open
    state.prev2_high = state.prev1_high
    state.prev2_low = state.prev1_low
    state.prev2_close = state.prev1_close
    state.prev1_open = o_t if not np.isnan(o_t) else None
    state.prev1_high = h_t if not np.isnan(h_t) else None
    state.prev1_low = l_t if not np.isnan(l_t) else None
    state.prev1_close = c_t if not np.isnan(c_t) else None

    state.bar_idx += 1

    return out
