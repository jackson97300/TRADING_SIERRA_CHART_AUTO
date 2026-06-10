"""bot2_setup_counter.py — Compte setups BN V4 + simul rapide.

Approche minimaliste : on charge le parquet, on ne fait PAS de rolling window
(vectorise au possible). On compte setups par config et simul minimum.
"""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bn_v4_engine import (
    BNV4Params, GRADE_THRESHOLDS,
    INSTITUTIONAL_LEVELS_LONG, INSTITUTIONAL_LEVELS_SHORT,
    OPEN_WINDOWS_MIN_ET,
    density_clusters, assign_grade, in_open_window,
    edge_buy_active, find_top_level_price, count_levels_proche,
)


def load_data():
    base = ROOT / "DATA/datasets/v4_enriched/symbol=NQ.c.0"
    parts = []
    for ydir in sorted(base.iterdir()):
        for mdir in sorted(ydir.iterdir()):
            pq = mdir / "data.parquet"
            if pq.exists():
                parts.append(pd.read_parquet(pq))
    return pd.concat(parts, ignore_index=True).sort_values("ts_event").reset_index(drop=True)


def count_setups_vectorized(df, params: BNV4Params, direction: str):
    """Compte setups en vectorise (sans rolling window).

    Approximation : utilise les valeurs precalculees, fait les checks
    sur des slices df.iloc[lo:i+1] uniquement pour trend_recent/long.
    """
    n = len(df)
    # 1. Open window mask
    if params.require_open_window:
        et_offset_min = pd.to_datetime(df["ts_event"]).dt.tz_convert("America/New_York")
        et_min = et_offset_min.dt.hour * 60 + et_offset_min.dt.minute
        open_mask = np.zeros(n, dtype=bool)
        for ws, we in OPEN_WINDOWS_MIN_ET:
            open_mask |= (et_min >= ws) & (et_min < we)
    else:
        open_mask = np.ones(n, dtype=bool)

    # 2. Trend recent : rolling mean(vwap_slope_10) sur trend_lookback
    slope = df["vwap_slope_10"].fillna(0).values
    if direction == "long":
        threshold_recent = -params.trend_slope_min
    else:
        threshold_recent = params.trend_slope_min
    # rolling mean
    cumsum = np.concatenate([[0], np.cumsum(slope)])
    lo_idx = np.maximum(0, np.arange(n) - params.trend_lookback)
    counts = np.arange(n) - lo_idx + 1
    sums = cumsum[np.arange(n) + 1] - cumsum[lo_idx]
    means_recent = sums / np.maximum(counts, 1)
    if direction == "long":
        trend_recent_ok = means_recent < threshold_recent
    else:
        trend_recent_ok = means_recent > threshold_recent

    # 3. Trend long aligned (seulement SHORT si require_long_trend_aligned)
    lo_idx_long = np.maximum(0, np.arange(n) - params.trend_long_lookback)
    counts_long = np.arange(n) - lo_idx_long + 1
    sums_long = cumsum[np.arange(n) + 1] - cumsum[lo_idx_long]
    means_long = sums_long / np.maximum(counts_long, 1)
    if params.require_long_trend_aligned and direction == "short":
        trend_long_ok = means_long < 0
    else:
        trend_long_ok = np.ones(n, dtype=bool)
    # LONG : pas de filtre asymetrique
    if direction == "long" and params.require_long_trend_aligned:
        # selon code engine LONG n'a pas le filtre asymetrique sauf si reverse
        pass

    # 4. n_levels niveaux institutionnels proches
    levels = INSTITUTIONAL_LEVELS_LONG if direction == "long" else INSTITUTIONAL_LEVELS_SHORT
    levels_present = [c for c in levels if c in df.columns]
    n_levels_arr = np.zeros(n, dtype=np.int8)
    for c in levels_present:
        v = df[c].abs().values
        n_levels_arr += (v < params.prox_pct).astype(np.int8)
    levels_ok = n_levels_arr >= params.n_levels_min

    # 5. Density clusters
    if direction == "long":
        a = df["n_color_up_cluster_within_0_2pct"].fillna(0).values
        b = df["n_long_up_cluster_within_0_2pct"].fillna(0).values
    else:
        a = df["n_color_dn_cluster_within_0_2pct"].fillna(0).values
        b = df["n_long_dn_cluster_within_0_2pct"].fillna(0).values
    density = (a + b).astype(np.int32)
    grade_threshold = GRADE_THRESHOLDS[params.grade_min]
    density_ok = density >= grade_threshold

    # 6. Edge active
    if direction == "long":
        edge_col = "n_edge_buy_active"
    else:
        edge_col = "n_edge_sell_active"
    edge_ok = df[edge_col].fillna(0).values >= 1

    # 7. Top level identifie (au moins 1 level dans la bonne direction et range)
    # Approximation : utilise n_levels_arr > 0 (skip top_level_max_dist_pct exact)
    top_level_ok = n_levels_arr >= 1

    # Trend lookback minimum
    min_i_mask = np.arange(n) >= max(params.trend_lookback, params.trend_long_lookback)

    setup_mask = (open_mask & trend_recent_ok & trend_long_ok &
                  levels_ok & density_ok & edge_ok & top_level_ok &
                  min_i_mask)

    return setup_mask, {
        "n_min_i_ok": int(min_i_mask.sum()),
        "n_open_ok": int(open_mask.sum()),
        "n_trend_recent_ok": int((trend_recent_ok & min_i_mask).sum()),
        "n_trend_long_ok": int((trend_long_ok & min_i_mask).sum()),
        "n_levels_ok": int(levels_ok.sum()),
        "n_density_ok": int(density_ok.sum()),
        "n_edge_ok": int(edge_ok.sum()),
        "n_setup_final": int(setup_mask.sum()),
    }


def simulate_simple(df, setup_indices, direction, sl_ticks=20, rr=2.0,
                     timeout_bars=90, tick_size=0.25):
    """Simul rapide vectorise (TP=R2.0 fixe / SL fixe / timeout)."""
    if len(setup_indices) == 0:
        return None
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    pnls = []
    n = len(df)

    for i in setup_indices:
        if i + timeout_bars >= n:
            continue
        entry = closes[i]
        sl_off = sl_ticks * tick_size
        if direction == "long":
            sl = entry - sl_off
            tp = entry + sl_off * rr
        else:
            sl = entry + sl_off
            tp = entry - sl_off * rr
        h = highs[i+1:i+1+timeout_bars]
        l = lows[i+1:i+1+timeout_bars]
        if direction == "long":
            sl_hit_at = np.argmax(l <= sl) if np.any(l <= sl) else timeout_bars + 1
            tp_hit_at = np.argmax(h >= tp) if np.any(h >= tp) else timeout_bars + 1
        else:
            sl_hit_at = np.argmax(h >= sl) if np.any(h >= sl) else timeout_bars + 1
            tp_hit_at = np.argmax(l <= tp) if np.any(l <= tp) else timeout_bars + 1

        if sl_hit_at < tp_hit_at:
            pnls.append(-sl_ticks)  # SL hit first
        elif tp_hit_at < sl_hit_at:
            pnls.append(sl_ticks * rr)  # TP first
        else:
            # Both never hit -> close at timeout
            exit_price = closes[i + timeout_bars]
            if direction == "long":
                pnls.append((exit_price - entry) / tick_size)
            else:
                pnls.append((entry - exit_price) / tick_size)
    if not pnls:
        return None
    pnls = np.array(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    sum_w = wins.sum() if len(wins) else 0
    sum_l = -losses.sum() if len(losses) else 1e-9
    return {
        "n_trades": len(pnls),
        "wr": float((pnls > 0).mean() * 100),
        "ev_ticks": float(pnls.mean()),
        "ev_R": float(pnls.mean() / sl_ticks),
        "pf": float(sum_w / sum_l) if sum_l > 0 else float("inf"),
        "sum_ticks": float(pnls.sum()),
    }


def main():
    t0 = time.time()
    print("Loading...")
    df = load_data()
    print(f"  {len(df)} bars  ({time.time()-t0:.1f}s)")

    configs = {
        "A++_strict": BNV4Params(grade_min="A++", require_open_window=True,
                                  require_long_trend_aligned=True),
        "A": BNV4Params(grade_min="A", require_open_window=True,
                         require_long_trend_aligned=True),
        "A_no_trend": BNV4Params(grade_min="A", require_open_window=True,
                                  require_long_trend_aligned=False),
        "A_no_window": BNV4Params(grade_min="A", require_open_window=False,
                                   require_long_trend_aligned=False),
        "B_no_filter": BNV4Params(grade_min="B", require_open_window=False,
                                   require_long_trend_aligned=False),
    }

    results = {}
    for name, params in configs.items():
        print(f"\n=== {name} ===")
        out = {"short": {}, "long": {}}
        for direction in ("short", "long"):
            setup_mask, stats = count_setups_vectorized(df, params, direction)
            setup_idx = np.where(setup_mask)[0]
            sim = simulate_simple(df, setup_idx, direction)
            out[direction] = {"stats_funnel": stats, "sim": sim}
            print(f"  {direction}: n_setup={stats['n_setup_final']}", end="")
            if sim:
                print(f" trades={sim['n_trades']} WR={sim['wr']:.1f}% "
                      f"PF={sim['pf']:.2f} EV={sim['ev_ticks']:+.1f}t")
            else:
                print()
        results[name] = out

    out_path = ROOT / "LOGS/bot2_research/setup_counter_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nSaved: {out_path}  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
