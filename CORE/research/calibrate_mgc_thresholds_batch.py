"""Batterie de tests seuils MGC : trouve les seuils optimaux par dichotomie.

Test in-memory sur le footprint MGC (built from trades parquet Databento) :
  - EDGE_THRESHOLD_PCT : test [20, 30, 40, 50, 60, 80, 100, 120, 150]
  - BIG_ORDER_TIERS    : test plusieurs progressions

Output : tableau seuil vs fire_rate. Cible : fire 1-3% (signal rare actionnable).

Usage :
  python -X utf8 CORE/research/calibrate_mgc_thresholds_batch.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pyarrow.parquet as pq
import pandas as pd
import numpy as np
from datetime import datetime
import time


def build_footprint_from_trades(trades_df: pd.DataFrame, bar_minute_ts: pd.Series, tick: float = 0.10) -> dict:
    """Build footprint per bar from raw trades (ask/bid volumes per price cell)."""
    footprint = {}
    if trades_df.empty:
        return footprint
    # Grouper par minute (bar)
    trades_df = trades_df.copy()
    trades_df["bar_idx"] = trades_df["ts_event"].dt.floor("1min")
    # Map bar_idx -> i pour aligner avec df ohlc
    bar_to_i = {ts: i for i, ts in enumerate(bar_minute_ts)}
    for bar_ts, grp in trades_df.groupby("bar_idx"):
        i = bar_to_i.get(bar_ts)
        if i is None:
            continue
        # Pour chaque trade : prix arrondi au tick + side (A=ask aggressor, B=bid)
        cells = {}
        for _, row in grp.iterrows():
            price = round(round(row["price"] / tick) * tick, 4)
            side = row.get("side", "")
            size = row.get("size", 0)
            if price not in cells:
                cells[price] = {"ask_vol": 0, "bid_vol": 0}
            if side == "A":
                cells[price]["ask_vol"] += size
            elif side == "B":
                cells[price]["bid_vol"] += size
        footprint[i] = cells
    return footprint


def measure_edge_fire_rate(footprint: dict, threshold_pct: float, tick: float, n_bars: int) -> dict:
    """Simule apply_edge_zones (juste fire_rate, sans extension lines)."""
    from edge_zones_engine import _detect_stacks_for_bar
    n_fire_buy = 0
    n_fire_sell = 0
    n_zones_buy_total = 0
    n_zones_sell_total = 0
    for i, cells in footprint.items():
        stacks_buy = _detect_stacks_for_bar(cells, threshold_pct, tick, min_group_size=2, side="buy")
        stacks_sell = _detect_stacks_for_bar(cells, threshold_pct, tick, min_group_size=2, side="sell")
        if stacks_buy:
            n_fire_buy += 1
            n_zones_buy_total += len(stacks_buy)
        if stacks_sell:
            n_fire_sell += 1
            n_zones_sell_total += len(stacks_sell)
    return {
        "fire_buy_pct": round(n_fire_buy / n_bars * 100, 3),
        "fire_sell_pct": round(n_fire_sell / n_bars * 100, 3),
        "fire_total_pct": round((n_fire_buy + n_fire_sell) / (2 * n_bars) * 100, 3),
        "n_zones_buy": n_zones_buy_total,
        "n_zones_sell": n_zones_sell_total,
    }


def main():
    print("=" * 70)
    print(" BATTERIE TESTS SEUILS MGC — J3 Phase B Jackson directive")
    print("=" * 70)

    # 1. Charger OHLC MGC april 2026
    print("\n[1/3] Loading MGC OHLC april 2026...")
    ohlc_path = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=MGC.c.0" / "year=2026" / "month=04" / "data.parquet"
    if not ohlc_path.exists():
        # Fallback parquet local downloade
        ohlc_path = ROOT / "mgc_v4_apr_postfix.parquet"
        if not ohlc_path.exists():
            ohlc_path = ROOT / "mgc_v4_apr_raw.parquet"
    print(f"  Source: {ohlc_path}")
    df = pq.ParquetFile(str(ohlc_path)).read(columns=["ts_event"]).to_pandas()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True).dt.tz_localize(None)
    n_bars = len(df)
    print(f"  Loaded {n_bars:,} bars")

    # 2. Charger trades Databento MGC april
    print("\n[2/3] Loading MGC trades april 2026...")
    trades_dir = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "trades" / "symbol=MGC.v.0" / "year=2026" / "month=4"
    if not trades_dir.exists():
        print(f"  [WARN] trades dir absent: {trades_dir} -> fallback VPS recommended")
        return
    import glob
    files = sorted(glob.glob(str(trades_dir / "day=*" / "data.parquet")) +
                    glob.glob(str(trades_dir / "day=*" / "data_*.parquet")))
    if not files:
        print(f"  [WARN] aucun fichier trades trouve dans {trades_dir}")
        return
    t0 = time.time()
    all_trades = []
    for f in files:
        try:
            t_df = pq.ParquetFile(f).read(columns=["ts_event", "price", "size", "side"]).to_pandas()
            all_trades.append(t_df)
        except Exception as e:
            print(f"  [WARN] read fail {f}: {e}")
    if not all_trades:
        print(f"  [WARN] aucun trade lu")
        return
    trades_df = pd.concat(all_trades, ignore_index=True)
    trades_df["ts_event"] = pd.to_datetime(trades_df["ts_event"], utc=True).dt.tz_localize(None)
    elapsed = time.time() - t0
    print(f"  Loaded {len(trades_df):,} trades in {elapsed:.1f}s")

    # 3. Build footprint
    print("\n[3/3] Building footprint per bar (tick=0.10)...")
    t0 = time.time()
    footprint = build_footprint_from_trades(trades_df, df["ts_event"], tick=0.10)
    elapsed = time.time() - t0
    print(f"  Footprint built : {len(footprint):,} bars in {elapsed:.1f}s")

    # 4. Battery tests EDGE_THRESHOLD_PCT
    print("\n" + "=" * 70)
    print(" EDGE_THRESHOLD_PCT — Test dichotomie post-fix tick=tick")
    print("=" * 70)
    print(f"  {'threshold':>10s}  {'fire_buy':>10s}  {'fire_sell':>10s}  {'fire_total':>12s}  {'verdict':<15s}")
    print(f"  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*12}  {'-'*15}")
    best_threshold = None
    best_dist_to_target = 999
    target_fire = 2.0  # cible 1-3%
    # 11/05 J3 iter recalibration apres bug fix tick=tick :
    # Iter 4 (150)=93% / Iter 5 (600)=33%. Gold a vrais imbalances comme ES.
    # Test gamme haute pour cible 1-3% fire rate.
    for thr in [600, 800, 1000, 1200, 1500, 2000, 3000, 5000, 8000, 12000]:
        result = measure_edge_fire_rate(footprint, thr, tick=0.10, n_bars=n_bars)
        verdict = "OPTIMAL CIBLE" if 1 <= result["fire_total_pct"] <= 3 else (
            "trop bruyant" if result["fire_total_pct"] > 3 else "trop rare"
        )
        dist = abs(result["fire_total_pct"] - target_fire)
        if dist < best_dist_to_target and result["fire_total_pct"] >= 0.5:
            best_dist_to_target = dist
            best_threshold = thr
        print(f"  {thr:>10d}  {result['fire_buy_pct']:>10.3f}  {result['fire_sell_pct']:>10.3f}  {result['fire_total_pct']:>12.3f}  {verdict:<15s}")

    print()
    print(f"  RECOMMANDATION : EDGE_THRESHOLD_PCT['MGC'] = {best_threshold} (closest to {target_fire}% target)")
    print()


if __name__ == "__main__":
    main()
