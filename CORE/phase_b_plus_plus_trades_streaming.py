"""phase_b_plus_plus_trades_streaming.py

API streaming-aware phase_b_plus_plus_engine.py - LOT 1 (trades aggregates).
Couvre toutes les features qui derivent de l'aggregation trades par bar :

Features (~34) :
  BIG ORDERS multi-tier (12) :
    n_big_t1, n_big_t2, n_big_t3, n_big_t4
    n_big_buy_t1-t4, n_big_sell_t1-t4

  TRADE SIZE STATS (3) :
    max_size_buy, max_size_sell, p99_trade_size

  AGGRESSOR + CLUSTERS (3) :
    aggressor_imbalance, n_clusters, max_cluster_volume

  FPBS INTRA-BAR (4) :
    max_delta_bar, min_delta_bar, n_ticks_bar
    delta_change (= delta_bar - prev_delta_bar)

  DISTANCES nearest (4) :
    dist_big_ask/bid_nearest_pct
    dist_cluster_nearest_up/dn_pct

  DERIVEES (5) :
    big_buy/sell_dominance (ratio tier 1)
    finish_pct_up, finish_strong_up, finish_strong_dn

  DELTA DIVERGENCE DAILY (2) :
    delta_div_buy, delta_div_sell (depend running daily high/low + prev_day)

LOTS suivants (sub-engines separes) :
  LOT 2 : big_orders_v2 (scan VAP cells footprint)
  LOT 3 : cluster_volume_v2 (footprint cells)
  LOT 4 : stack + absorption (footprint cells + niveaux key)
  LOT 5 : trapped_traders + Extension Lines
  LOT 6 : delta_div_buy/sell Extension Lines + clusters

Auteur : Phase 3c semaine 4 (2026-05-14)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from phase_b_plus_plus_engine import BIG_ORDER_TIERS, CLUSTER_THRESHOLDS

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size

ET = ZoneInfo("America/New_York")


@dataclass
class PhaseBPlusPlusTradesState:
    """State streaming phase_b_plus_plus trades aggregates.

    Pickle-safe : tous primitifs + dict daily ohlc.
    """
    symbol: str = "ES"
    tick: float = 0.25
    tier_thresholds: List[int] = field(default_factory=lambda: [100, 150, 400, 1000])
    cluster_threshold: int = 250

    # FPBS state : prev delta_bar pour delta_change
    prev_delta_bar: Optional[float] = None

    # Delta divergence state : daily running high/low + previous day
    current_date_local: Optional[Any] = None  # date_et
    daily_high_running: Optional[float] = None
    daily_low_running: Optional[float] = None
    # Previous day OHLC (figes au changement date_et)
    prev_day_high: Optional[float] = None
    prev_day_low: Optional[float] = None


def make_phase_b_plus_plus_trades_state(
    symbol: str = "ES",
) -> "PhaseBPlusPlusTradesState":
    """Factory per-symbole avec tier thresholds + cluster threshold."""
    sym = symbol.upper().split(".")[0]
    return PhaseBPlusPlusTradesState(
        symbol=sym,
        tick=_get_tick_size(sym),
        tier_thresholds=list(BIG_ORDER_TIERS.get(sym, BIG_ORDER_TIERS["ES"])),
        cluster_threshold=CLUSTER_THRESHOLDS.get(sym, CLUSTER_THRESHOLDS["ES"]),
    )


def _ts_to_et_date(ts_event) -> Optional[Any]:
    """Convert ts_event -> date ET."""
    if ts_event is None:
        return None
    if isinstance(ts_event, pd.Timestamp):
        ts = ts_event
    else:
        try:
            ts = pd.Timestamp(ts_event)
        except (TypeError, ValueError):
            return None
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(ET).date()


def add_phase_b_plus_plus_trades_streaming(
    row: dict,
    state: PhaseBPlusPlusTradesState,
    trades_in_window: Optional[List[dict]] = None,
) -> dict:
    """Sub-engine streaming LOT 1 phase_b_plus_plus - ~34 features.

    Args:
        row : dict avec ts_event, high, low, close, delta_bar.
              delta_bar = delta agrégé de la bar (depuis Databento ou DMP).
        state : PhaseBPlusPlusTradesState mutable.
        trades_in_window : list[dict] trades dans la bar courante
                            ({price, size, side='A'|'B'|'N'}).
                            None ou [] = toutes features = 0/NaN.

    Contract:
      - trades_in_window doit etre tri par ts_event ASC (oldest -> newest).
      - Chaque trade : dict avec keys 'price', 'size', 'side'
        ('A'=BUY aggressor, 'B'=SELL aggressor, 'N'=ignore) et optionnellement
        'ts_event' (pour sanity check debug).
      - Le caller (Live Enricher) est responsable du tri. Le streaming ne re-trie
        pas pour des raisons de performance (eviter O(n log n) par bar).
      - L'ordre est critique pour le calcul cumdelta (max_delta_bar / min_delta_bar) :
        un tri incorrect produit des valeurs differentes du batch.

    Returns:
        dict row + 34 features phase_b_plus_plus trades aggregates.
    """
    out = dict(row)

    # Sanity check debug-only : verifier tri ts_event ASC (caller contract).
    # Skip en non-debug (-O / python -OO) pour zero overhead production.
    if __debug__ and trades_in_window and len(trades_in_window) >= 2:
        first_ts = trades_in_window[0].get("ts_event")
        last_ts = trades_in_window[-1].get("ts_event")
        if first_ts is not None and last_ts is not None and first_ts > last_ts:
            import warnings
            warnings.warn(
                f"trades_in_window not sorted ts_event ASC : "
                f"first={first_ts} > last={last_ts}. "
                f"Caller must sort. Skipping assertion in non-debug mode.",
                RuntimeWarning,
                stacklevel=2,
            )

    # ─── Inputs OHLC ───────────────────────────────────────────────────────
    try:
        h = float(out["high"]) if out.get("high") is not None else np.nan
        l = float(out["low"]) if out.get("low") is not None else np.nan
        c = float(out["close"]) if out.get("close") is not None else np.nan
    except (TypeError, ValueError):
        h = l = c = np.nan
    try:
        delta_bar = float(out.get("delta_bar", 0)) if out.get("delta_bar") is not None else 0.0
    except (TypeError, ValueError):
        delta_bar = 0.0

    # ─── Init output values (defaults si pas de trades) ────────────────────
    # Big orders multi-tier (12)
    for tier in (1, 2, 3, 4):
        out[f"n_big_t{tier}"] = 0
        out[f"n_big_buy_t{tier}"] = 0
        out[f"n_big_sell_t{tier}"] = 0
    # Trade size stats (3)
    out["max_size_buy"] = 0
    out["max_size_sell"] = 0
    out["p99_trade_size"] = 0
    # Aggressor + clusters (3)
    out["aggressor_imbalance"] = 0.0
    out["n_clusters"] = 0
    out["max_cluster_volume"] = 0
    # FPBS intra-bar (3 + delta_change calc later)
    out["max_delta_bar"] = 0
    out["min_delta_bar"] = 0
    out["n_ticks_bar"] = 0
    # Distances (4)
    out["dist_big_ask_nearest_pct"] = np.nan
    out["dist_big_bid_nearest_pct"] = np.nan
    out["dist_cluster_nearest_up_pct"] = np.nan
    out["dist_cluster_nearest_dn_pct"] = np.nan

    # ═══════════════════════════════════════════════════════════════════════
    # 1. AGGREGATION TRADES (si trades_in_window fourni)
    # ═══════════════════════════════════════════════════════════════════════
    if trades_in_window:
        tick = state.tick
        tier_thresholds = state.tier_thresholds
        cluster_threshold = state.cluster_threshold

        # Parse trades + bucket prix
        trades_data = []  # list de (price_bucket, size, side, signed_size)
        for t in trades_in_window:
            price = t.get("price")
            size = t.get("size")
            side = t.get("side")
            if price is None or size is None or side not in ("A", "B", "N"):
                continue
            try:
                pf = float(price)
                sf = float(size)
                if pf <= 0 or sf <= 0:
                    continue
            except (TypeError, ValueError):
                continue
            bucket = round((pf / tick), 0) * tick
            bucket = round(bucket, 4)
            signed = int(sf) if side == "A" else (-int(sf) if side == "B" else 0)
            trades_data.append((bucket, int(sf), side, signed))

        if trades_data:
            # Big orders multi-tier counts
            for tier_idx, thresh in enumerate(tier_thresholds, start=1):
                if thresh is None:
                    continue
                n_big = sum(1 for _, sz, _, _ in trades_data if sz >= thresh)
                n_big_buy = sum(1 for _, sz, sd, _ in trades_data if sz >= thresh and sd == "A")
                n_big_sell = sum(1 for _, sz, sd, _ in trades_data if sz >= thresh and sd == "B")
                out[f"n_big_t{tier_idx}"] = n_big
                out[f"n_big_buy_t{tier_idx}"] = n_big_buy
                out[f"n_big_sell_t{tier_idx}"] = n_big_sell

            # Max size per side
            sizes_buy = [sz for _, sz, sd, _ in trades_data if sd == "A"]
            sizes_sell = [sz for _, sz, sd, _ in trades_data if sd == "B"]
            out["max_size_buy"] = max(sizes_buy) if sizes_buy else 0
            out["max_size_sell"] = max(sizes_sell) if sizes_sell else 0

            # p99 trade size
            all_sizes = [sz for _, sz, _, _ in trades_data]
            if all_sizes:
                out["p99_trade_size"] = float(np.quantile(all_sizes, 0.99))

            # Aggressor imbalance (exclut side='N')
            n_a = sum(1 for _, _, sd, _ in trades_data if sd == "A")
            n_b = sum(1 for _, _, sd, _ in trades_data if sd == "B")
            n_dir = n_a + n_b
            out["aggressor_imbalance"] = (n_a - n_b) / n_dir if n_dir > 0 else 0.0

            # Clusters par price_bucket (sum size par bucket)
            cluster_dict = {}
            for bucket, sz, _, _ in trades_data:
                cluster_dict[bucket] = cluster_dict.get(bucket, 0) + sz
            cluster_count = sum(1 for v in cluster_dict.values() if v >= cluster_threshold)
            out["n_clusters"] = cluster_count
            out["max_cluster_volume"] = max(cluster_dict.values()) if cluster_dict else 0

            # FPBS intra-bar (max/min cumdelta) :
            # On simule un cumsum signed_size dans l'ordre d'arrivee.
            # FIX P0 audit : init max/min a None pour matcher batch
            # (batch.groupby.cumsum.max ne renvoie pas 0 par defaut, mais
            # la valeur max reelle qui peut etre negative).
            cumdelta = 0
            max_cumdelta = None
            min_cumdelta = None
            for _, _, _, signed in trades_data:
                cumdelta += signed
                if max_cumdelta is None or cumdelta > max_cumdelta:
                    max_cumdelta = cumdelta
                if min_cumdelta is None or cumdelta < min_cumdelta:
                    min_cumdelta = cumdelta
            out["max_delta_bar"] = max_cumdelta if max_cumdelta is not None else 0
            out["min_delta_bar"] = min_cumdelta if min_cumdelta is not None else 0
            out["n_ticks_bar"] = len(cluster_dict)  # n distinct price buckets

            # Distances big ASK/BID + clusters nearest (depend close)
            if not np.isnan(c) and c > 0 and tier_thresholds[0] is not None:
                t1 = tier_thresholds[0]
                big_ask_prices = [b for b, sz, sd, _ in trades_data if sz >= t1 and sd == "A"]
                big_bid_prices = [b for b, sz, sd, _ in trades_data if sz >= t1 and sd == "B"]
                cluster_prices = [b for b, v in cluster_dict.items() if v >= cluster_threshold]

                if big_ask_prices:
                    out["dist_big_ask_nearest_pct"] = (
                        min(abs(p - c) for p in big_ask_prices) / c * 100
                    )
                if big_bid_prices:
                    out["dist_big_bid_nearest_pct"] = (
                        min(abs(p - c) for p in big_bid_prices) / c * 100
                    )
                ups = [p for p in cluster_prices if p > c]
                dns = [p for p in cluster_prices if p < c]
                if ups:
                    out["dist_cluster_nearest_up_pct"] = (min(ups) - c) / c * 100
                if dns:
                    out["dist_cluster_nearest_dn_pct"] = (c - max(dns)) / c * 100

    # ═══════════════════════════════════════════════════════════════════════
    # 2. DERIVEES : big_buy/sell_dominance (ratio tier 1)
    # ═══════════════════════════════════════════════════════════════════════
    total_big = out["n_big_buy_t1"] + out["n_big_sell_t1"]
    if total_big > 0:
        out["big_buy_dominance"] = out["n_big_buy_t1"] / total_big
        out["big_sell_dominance"] = out["n_big_sell_t1"] / total_big
    else:
        out["big_buy_dominance"] = 0.5
        out["big_sell_dominance"] = 0.5

    # ═══════════════════════════════════════════════════════════════════════
    # 3. delta_change = delta_bar - prev_delta_bar (state)
    # ═══════════════════════════════════════════════════════════════════════
    if state.prev_delta_bar is None:
        out["delta_change"] = 0.0  # mirror batch fillna(0)
    else:
        out["delta_change"] = delta_bar - state.prev_delta_bar
    state.prev_delta_bar = delta_bar

    # ═══════════════════════════════════════════════════════════════════════
    # 4. FPBS finish (stateless, depend high/low/close)
    # ═══════════════════════════════════════════════════════════════════════
    if not (np.isnan(h) or np.isnan(l) or np.isnan(c)):
        bar_range = h - l
        if bar_range > 0:
            finish_pct = (c - l) / bar_range * 100
        else:
            finish_pct = 50.0
    else:
        finish_pct = 50.0
    out["finish_pct_up"] = finish_pct
    out["finish_strong_up"] = 1 if finish_pct >= 80 else 0
    out["finish_strong_dn"] = 1 if finish_pct <= 20 else 0

    # ═══════════════════════════════════════════════════════════════════════
    # 5. DELTA DIVERGENCE DAILY (state running + previous day)
    # ═══════════════════════════════════════════════════════════════════════
    date_local = _ts_to_et_date(out.get("ts_event"))

    # Detection nouveau jour : fige prev_day high/low + reset running
    if date_local is not None and date_local != state.current_date_local:
        if state.current_date_local is not None:
            # Fige prev_day OHLC depuis running
            state.prev_day_high = state.daily_high_running
            state.prev_day_low = state.daily_low_running
        state.current_date_local = date_local
        state.daily_high_running = None
        state.daily_low_running = None

    # Update running daily high/low avec bar courante
    if not np.isnan(h):
        if state.daily_high_running is None or h > state.daily_high_running:
            state.daily_high_running = h
    if not np.isnan(l):
        if state.daily_low_running is None or l < state.daily_low_running:
            state.daily_low_running = l

    # Compute delta_div_buy / delta_div_sell
    delta_div_buy = 0
    delta_div_sell = 0
    if (
        state.daily_low_running is not None
        and state.prev_day_low is not None
        and state.daily_low_running < state.prev_day_low
        and delta_bar >= 0
    ):
        delta_div_buy = 1
    if (
        state.daily_high_running is not None
        and state.prev_day_high is not None
        and state.daily_high_running > state.prev_day_high
        and delta_bar <= 0
    ):
        delta_div_sell = 1
    out["delta_div_buy"] = delta_div_buy
    out["delta_div_sell"] = delta_div_sell

    return out
