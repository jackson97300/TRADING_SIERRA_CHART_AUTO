"""Sanity check du meta-labeling NQ_buy v5d : test bias + random filter."""
from __future__ import annotations
import json
import pickle
from pathlib import Path
import numba
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


@numba.njit(cache=True)
def sim(highs, lows, closes, atrs, k_sl, k_tp_ratio, h, tick, cost):
    n = len(closes)
    pnl = np.zeros(n, dtype=np.float64)
    for i in range(n - h - 1):
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue
        sl_t = k_sl * atr_t
        tp_t = k_tp_ratio * sl_t
        e = closes[i]
        sl_l = e - sl_t * tick
        tp_l = e + tp_t * tick
        out = 0.0
        hit = False
        for k in range(1, h + 1):
            j = i + k
            if j >= n:
                break
            if lows[j] <= sl_l:
                out = -sl_t - cost
                hit = True
                break
            if highs[j] >= tp_l:
                out = tp_t - cost
                hit = True
                break
        if not hit:
            j = i + h
            if j < n:
                out = (closes[j] - e) / tick - cost
            else:
                out = -cost
        pnl[i] = out
    return pnl


def main():
    df = pd.read_parquet(ROOT / "DATA/datasets/NQ_dataset_v5d.parquet")
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    n = len(df)
    split_idx = int(n * 0.7)
    df_test = df.iloc[split_idx:].reset_index(drop=True)
    print(f"Test bars: {len(df_test):,}")

    closes = df_test["close"].values.astype(np.float64) if "close" in df_test.columns else df_test["price"].values.astype(np.float64)
    highs = df_test["high"].values.astype(np.float64) if "high" in df_test.columns else closes
    lows = df_test["low"].values.astype(np.float64) if "low" in df_test.columns else closes
    atrs = df_test["atr"].values.astype(np.float64)
    pnl_test = sim(highs, lows, closes, atrs, 1.5, 2.0, 60, 0.25, 0.5)

    nz = pnl_test[pnl_test != 0]
    wins = nz[nz > 0]
    losses = nz[nz < 0]
    print(f"\n=== SYSTEMATIC NQ_buy (TOUS les bars test, no filter, BUY a chaque bar) ===")
    print(f"  N={len(nz):,} WR={len(wins)/len(nz)*100:.2f}% PF={wins.sum()/-losses.sum():.3f} EV={nz.mean():+.2f}t")

    # Random filter sample comparable a meta_thr=0.60
    np.random.seed(42)
    target_ns = [13599, 12373, 10823, 9474, 8343]
    print(f"\n=== RANDOM FILTER (30 iter, varying sample size) ===")
    for target_n in target_ns:
        if target_n > len(pnl_test):
            continue
        results = []
        for _ in range(30):
            idx = np.random.choice(len(pnl_test), size=target_n, replace=False)
            pnl_sub = pnl_test[idx]
            nz_sub = pnl_sub[pnl_sub != 0]
            if len(nz_sub) < 100:
                continue
            wins_s = nz_sub[nz_sub > 0]
            losses_s = nz_sub[nz_sub < 0]
            pf_s = wins_s.sum() / (-losses_s.sum()) if losses_s.sum() < 0 else 0
            wr_s = len(wins_s) / len(nz_sub) * 100
            results.append((wr_s, pf_s))
        arr = np.array(results)
        print(f"  N={target_n:6,d}: WR={arr[:,0].mean():5.2f}% [{arr[:,0].min():5.2f}-{arr[:,0].max():5.2f}]  PF={arr[:,1].mean():.3f} [{arr[:,1].min():.3f}-{arr[:,1].max():.3f}]")

    # MFE / MAE distribution
    print(f"\n=== Mouvement net du marche test ===")
    p0 = closes[0]
    p1 = closes[-1]
    print(f"  Close start={p0:.0f} end={p1:.0f} ({(p1-p0)/p0*100:+.2f}%)")
    # Peak / trough
    max_p = closes.max()
    min_p = closes.min()
    print(f"  Range: {min_p:.0f} - {max_p:.0f} ({(max_p-min_p)/p0*100:.1f}% spread)")

    # Distribution labels
    if "label" in df_test.columns:
        print(f"\n=== Labels distribution test ===")
        n_buy = int((df_test["label"] == 1).sum())
        n_sell = int((df_test["label"] == -1).sum())
        n_hold = int((df_test["label"] == 0).sum())
        print(f"  BUY={n_buy:6,d}  SELL={n_sell:6,d}  HOLD={n_hold:6,d}")
        print(f"  Balance BUY/(BUY+SELL) = {n_buy/(n_buy+n_sell):.3f}")


if __name__ == "__main__":
    main()
