"""TEST CRITIQUE : si meta = juste threshold appris sur p_primary,
alors un threshold optimise directement sur p_primary devrait donner les memes resultats.

Si oui : meta-labeling = COMPLEXITE INUTILE, simple grid search threshold optimal.
"""
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


def metrics(pnl):
    nz = pnl[pnl != 0]
    if len(nz) == 0:
        return dict(n=0, wr=0, pf=0, ev=0)
    wins = nz[nz > 0]
    losses = nz[nz < 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    return dict(n=len(nz), wr=len(wins) / len(nz), pf=float(pf), ev=float(nz.mean()))


def main():
    print("=" * 100)
    print("  TEST : meta-labeling vs simple p_primary threshold")
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
    pnl_all = sim_buy(highs, lows, closes, atrs, 1.5, 2.0, 60, 0.25, 0.5)

    n = len(df)
    split_idx = int(n * 0.7)
    df_test = df.iloc[split_idx:].reset_index(drop=True)
    pnl_test = pnl_all[split_idx:]

    primary_features_avail = [f for f in primary_features if f in df.columns]
    for m in set(primary_features) - set(primary_features_avail):
        df[m] = 0
    primary_features_avail = primary_features

    X_test = df_test[primary_features_avail].fillna(0)
    p_test = primary_model.predict_proba(X_test)[:, 1]

    print(f"\n  p_primary distribution sur TEST :")
    print(f"    min={p_test.min():.3f}  max={p_test.max():.3f}  mean={p_test.mean():.3f}")
    print(f"    pct: 10%={np.percentile(p_test, 10):.3f}  50%={np.percentile(p_test, 50):.3f}  90%={np.percentile(p_test, 90):.3f}")

    print(f"\n  GRID THRESHOLD sur p_primary directement :")
    print(f"  {'thr':>6}  {'N':>7}  {'WR%':>5}  {'PF':>5}  {'EV':>6}")
    for thr in [primary_threshold, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
        sig = p_test > thr
        m = metrics(pnl_test[sig])
        print(f"  {thr:>6.3f}  {m['n']:>7,d}  {m['wr']*100:>5.1f}  {m['pf']:>5.2f}  {m['ev']:>+6.1f}")

    # Distribution p_primary sur train pour voir quelle fraction des bars depasse 0.85
    df_train = df.iloc[:split_idx].reset_index(drop=True)
    X_train = df_train[primary_features_avail].fillna(0)
    p_train = primary_model.predict_proba(X_train)[:, 1]
    print(f"\n  p_primary distribution sur TRAIN :")
    print(f"    min={p_train.min():.3f}  max={p_train.max():.3f}  mean={p_train.mean():.3f}")
    print(f"    pct: 10%={np.percentile(p_train, 10):.3f}  50%={np.percentile(p_train, 50):.3f}  90%={np.percentile(p_train, 90):.3f}")
    print(f"    %>0.85 train = {(p_train > 0.85).mean()*100:.1f}%")
    print(f"    %>0.85 test = {(p_test > 0.85).mean()*100:.1f}%")


if __name__ == "__main__":
    main()
