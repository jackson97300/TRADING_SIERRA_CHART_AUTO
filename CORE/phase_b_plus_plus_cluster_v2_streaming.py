"""phase_b_plus_plus_cluster_v2_streaming.py

API streaming-aware phase_b_plus_plus_engine.py - LOT 3 (Cluster Volume V2).
Couvre add_cluster_volume_features : scan footprint cells par bar pour
detecter clusters de volume (>= min_group cellules consecutives avec total_vol
>= threshold).

Features (5) :
  n_cluster_groups       : nb de clusters dans la bar (groupes >= 2 cellules)
  max_cluster_size       : taille (nb cellules) du plus gros cluster
  max_cluster_volume_v2  : volume total du plus gros cluster
  cluster_at_high        : 1 si un cluster touche le HIGH du bar (resistance)
  cluster_at_low         : 1 si un cluster touche le LOW du bar (support)

Stateless. Mirror exact batch add_cluster_volume_features().

SC params Jackson 27/04 :
  ES Volume Threshold = 250, Min Group Size = 2
  NQ Volume Threshold = 20 (recalibre)
  MGC Volume Threshold = 50
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from phase_b_plus_plus_engine import CLUSTER_VOLUME_THRESHOLD, CLUSTER_VOLUME_MIN_GROUP

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


@dataclass
class ClusterV2State:
    """State streaming Cluster Volume V2 - stateless (config per-sym uniquement)."""
    symbol: str = "ES"
    tick: float = 0.25
    cluster_threshold: int = 250
    min_group: int = 2


def make_cluster_v2_state(symbol: str = "ES") -> "ClusterV2State":
    """Factory per-symbole."""
    sym = symbol.upper().split(".")[0]
    return ClusterV2State(
        symbol=sym,
        tick=_get_tick_size(sym),
        cluster_threshold=CLUSTER_VOLUME_THRESHOLD.get(sym, 250),
        min_group=CLUSTER_VOLUME_MIN_GROUP,
    )


def add_cluster_v2_streaming(
    row: dict,
    state: ClusterV2State,
    footprint_cells: Optional[Dict[float, Dict[str, float]]] = None,
) -> dict:
    """Sub-engine streaming LOT 3 cluster_volume_v2 - 5 features.

    Args:
        row : dict avec high, low (pour cluster_at_high/low detection).
        state : ClusterV2State (config per-sym).
        footprint_cells : dict[price -> {ask_vol, bid_vol, total_vol}].
                          None/{} = toutes features = 0.

    Returns:
        dict row + 5 features.

    Algorithme runs detection (mirror batch add_cluster_volume_features) :
      1. Trier les prix VAP cells par ordre croissant.
      2. Iterer : si total_vol(cell) >= threshold (ES=250, NQ=70, MGC=50),
         marquer 'hot', sinon 'cold'.
      3. Detecter runs consecutifs de 'hot' cells separes par <= 1 tick
         (adjacence : abs(price[i] - price[i-1] - tick) < 1e-6).
      4. Run = cluster si len(run) >= min_group (ES=2, NQ=2, MGC=2).
      5. Pour chaque cluster : compter size (nb cellules), sommer volume,
         noter prix min/max (start/end de la run).
      6. Features sortie :
         - n_cluster_groups       : nb total clusters
         - max_cluster_size       : taille du plus gros cluster (nb cellules)
         - max_cluster_volume_v2  : volume cumule du plus gros cluster
         - cluster_at_high        : 1 si cluster touche bar.high (tolerance tick/2)
         - cluster_at_low         : 1 si cluster touche bar.low (tolerance tick/2)
    """
    out = dict(row)

    # Init defaults
    out["n_cluster_groups"] = 0
    out["max_cluster_size"] = 0
    out["max_cluster_volume_v2"] = 0
    out["cluster_at_high"] = 0
    out["cluster_at_low"] = 0

    if not footprint_cells:
        return out

    try:
        bar_h = float(out["high"]) if out.get("high") is not None else None
        bar_l = float(out["low"]) if out.get("low") is not None else None
    except (TypeError, ValueError):
        bar_h = bar_l = None

    tick = state.tick
    threshold = state.cluster_threshold
    min_group = state.min_group

    # Mirror batch logic ligne 832-863
    prices_sorted = sorted(footprint_cells.keys())
    is_qualified = []
    for p in prices_sorted:
        tv = footprint_cells[p].get("total_vol", 0)
        is_qualified.append(tv >= threshold)

    # Detection runs >= min_group consecutives qualifiees (mirror batch)
    runs = []  # (start_idx, end_idx, total_vol)
    cur_start = None
    cur_total = 0
    for idx, q in enumerate(is_qualified):
        if q and (
            idx == 0
            or abs(prices_sorted[idx] - prices_sorted[idx - 1] - tick) < 1e-6
            or cur_start is None
        ):
            if cur_start is None:
                cur_start = idx
                cur_total = footprint_cells[prices_sorted[idx]]["total_vol"]
            else:
                cur_total += footprint_cells[prices_sorted[idx]]["total_vol"]
        else:
            if cur_start is not None and (idx - cur_start) >= min_group:
                runs.append((cur_start, idx - 1, cur_total))
            if q:
                cur_start = idx
                cur_total = footprint_cells[prices_sorted[idx]]["total_vol"]
            else:
                cur_start = None
                cur_total = 0
    # Final run
    if cur_start is not None:
        run_size = len(prices_sorted) - cur_start
        if run_size >= min_group:
            runs.append((cur_start, len(prices_sorted) - 1, cur_total))

    out["n_cluster_groups"] = len(runs)
    if runs:
        sizes = [r[1] - r[0] + 1 for r in runs]
        vols = [r[2] for r in runs]
        out["max_cluster_size"] = max(sizes)
        out["max_cluster_volume_v2"] = int(max(vols))

        # cluster_at_high / cluster_at_low : check si un cluster touche H ou L
        if bar_h is not None and bar_l is not None:
            for r_start, r_end, _ in runs:
                p_min = prices_sorted[r_start]
                p_max = prices_sorted[r_end]
                if p_min <= bar_h <= p_max + tick / 2:
                    out["cluster_at_high"] = 1
                if p_min - tick / 2 <= bar_l <= p_max:
                    out["cluster_at_low"] = 1

    return out
