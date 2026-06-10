"""Test sample uniqueness sur les trades distincts du meta filter."""
from __future__ import annotations
import json
import pickle
from pathlib import Path
import numba
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


@numba.njit(cache=True)
def sim_buy(highs, lows, closes, atrs, k_sl, k_tp_ratio, h, tick, cost):
    n = len(closes)
    pnl = np.zeros(n, dtype=np.float64)
    exit_offsets = np.zeros(n, dtype=np.int32)
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
        last_k = h
        for k in range(1, h + 1):
            j = i + k
            if j >= n:
                break
            if lows[j] <= sl_l:
                out = -sl_t - cost
                hit = True
                last_k = k
                break
            if highs[j] >= tp_l:
                out = tp_t - cost
                hit = True
                last_k = k
                break
        if not hit:
            j = i + h
            if j < n:
                out = (closes[j] - e) / tick - cost
            else:
                out = -cost
        pnl[i] = out
        exit_offsets[i] = last_k
    return pnl, exit_offsets


def main():
    print("=" * 100)
    print("  Test sample uniqueness — overlap des trades dans meta-labeling")
    print("=" * 100)

    primary_path = ROOT / "DATA/MODELS/BASELINE_27042026/NQ_buy_v5d_model.pkl"
    config_path = ROOT / "DATA/MODELS/BASELINE_27042026/NQ_buy_v5d_pf159_no.json"
    with open(primary_path, "rb") as f:
        primary_model = pickle.load(f)
    with open(config_path, "r") as f:
        config = json.load(f)
    primary_features = config["features"]
    primary_threshold = config["threshold"]

    df = pd.read_parquet(ROOT / "DATA/datasets/NQ_dataset_v5d.parquet")
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    df = df.sort_values("ts").reset_index(drop=True)

    closes = df["close"].values.astype(np.float64) if "close" in df.columns else df["price"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64) if "high" in df.columns else closes
    lows = df["low"].values.astype(np.float64) if "low" in df.columns else closes
    atrs = df["atr"].values.astype(np.float64)
    pnl_all, exit_off = sim_buy(highs, lows, closes, atrs, 1.5, 2.0, 60, 0.25, 0.5)

    n = len(df)
    split_idx = int(n * 0.7)
    df_test = df.iloc[split_idx:].reset_index(drop=True)
    pnl_test = pnl_all[split_idx:]
    exit_test = exit_off[split_idx:]

    primary_features_avail = [f for f in primary_features if f in df.columns]
    for m in set(primary_features) - set(primary_features_avail):
        df[m] = 0
    primary_features_avail = primary_features
    X_test = df_test[primary_features_avail].fillna(0)
    p_test = primary_model.predict_proba(X_test)[:, 1]

    print(f"\n  Pure p_primary thresholds — TRADES DISTINCTS (sequentiel non overlap) :")
    print(f"  {'thr':>6}  {'N_signal':>9}  {'N_distinct':>11}  {'overlap_ratio':>13}")
    for thr in [0.45, 0.50, 0.55, 0.60]:
        sig = p_test > thr
        idx_signals = np.where(sig)[0]
        # Trades distincts = on prend le 1er signal puis on saute jusqu'a la fin du trade (exit_offset)
        distinct = []
        i = 0
        while i < len(idx_signals):
            cur = idx_signals[i]
            distinct.append(cur)
            # Skip jusqu'a fin du trade (cur + exit_offset)
            end = cur + exit_test[cur]
            j = i + 1
            while j < len(idx_signals) and idx_signals[j] < end:
                j += 1
            i = j
        n_sig = sig.sum()
        n_dist = len(distinct)
        ratio = n_sig / max(1, n_dist)
        # Metrique sur trades distincts
        pnl_dist = pnl_test[distinct]
        nz = pnl_dist[pnl_dist != 0]
        if len(nz) > 0:
            wins = nz[nz > 0]
            losses = nz[nz < 0]
            pf = float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf")
            wr = len(wins) / len(nz) * 100
            ev = nz.mean()
        else:
            pf, wr, ev = 0, 0, 0
        print(f"  {thr:>6.2f}  {n_sig:>9,d}  {n_dist:>11,d}  {ratio:>13.1f}x   |  N_dist={len(nz)} WR={wr:.1f}% PF={pf:.2f} EV={ev:+.1f}t")

    # Combien de jours distinctes le test couvre ?
    df_test["date"] = pd.to_datetime(df_test["ts"], unit="ms").dt.date
    n_days = df_test["date"].nunique()
    print(f"\n  N jours dans test : {n_days}")
    print(f"  Si N_distinct=200 trades sur {n_days} jours = {200/n_days:.1f} trades/jour")


if __name__ == "__main__":
    main()
