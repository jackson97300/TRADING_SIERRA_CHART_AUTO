"""bot2_baseline_test.py — Test baseline marche (asymetrie hi/lo).

Si on entre LONG ou SHORT au hasard sur chaque bar avec SL=20t TP=N/A (timeout 15 bars),
quel est le PF ?
Cela isole l'effet de la simulation elle-meme vs un vrai edge ML.
"""
from __future__ import annotations

import sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.bot2_ml_directional import load_all_nq

def simulate_baseline(df, horizon=15, sl_ticks=20, tick_size=0.25,
                      direction="long", strategy="all"):
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    pnls = []
    for i in range(n - horizon):
        entry = closes[i]
        sl_off = sl_ticks * tick_size
        if direction == "long":
            sl_price = entry - sl_off
        else:
            sl_price = entry + sl_off
        exit_price = None
        for k in range(1, horizon + 1):
            tk = i + k
            if direction == "long":
                if lows[tk] <= sl_price:
                    exit_price = sl_price
                    break
            else:
                if highs[tk] >= sl_price:
                    exit_price = sl_price
                    break
        if exit_price is None:
            exit_price = closes[i + horizon]
        if direction == "long":
            pnls.append((exit_price - entry) / tick_size)
        else:
            pnls.append((entry - exit_price) / tick_size)
    pnls = np.array(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    sum_w = wins.sum() if len(wins) else 0
    sum_l = -losses.sum() if len(losses) else 1e-9
    return {
        "n": int(len(pnls)),
        "wr": float((pnls > 0).mean() * 100),
        "ev_ticks": float(pnls.mean()),
        "pf": float(sum_w / sum_l) if sum_l > 0 else float("inf"),
        "sum_ticks": float(pnls.sum()),
    }

df = load_all_nq()

print("Baseline TOUTES bars, h=15, sl=20t, exit timeout/SL")
for direction in ("long", "short"):
    r = simulate_baseline(df, horizon=15, sl_ticks=20, direction=direction)
    print(f"  {direction}: n={r['n']} WR={r['wr']:.1f}% EV={r['ev_ticks']:+.2f}t PF={r['pf']:.2f}")

print("\nBaseline RANDOM direction par bar (seed=42)")
rng = np.random.RandomState(42)
n = len(df)
random_dirs = rng.choice(["long","short"], size=n)
closes = df["close"].values
highs = df["high"].values
lows = df["low"].values
horizon = 15
sl_ticks = 20
tick_size = 0.25
pnls = []
for i in range(n - horizon):
    direction = random_dirs[i]
    entry = closes[i]
    sl_off = sl_ticks * tick_size
    if direction == "long":
        sl_price = entry - sl_off
    else:
        sl_price = entry + sl_off
    exit_price = None
    for k in range(1, horizon + 1):
        tk = i + k
        if direction == "long":
            if lows[tk] <= sl_price:
                exit_price = sl_price
                break
        else:
            if highs[tk] >= sl_price:
                exit_price = sl_price
                break
    if exit_price is None:
        exit_price = closes[i + horizon]
    if direction == "long":
        pnls.append((exit_price - entry) / tick_size)
    else:
        pnls.append((entry - exit_price) / tick_size)
pnls = np.array(pnls)
wins = pnls[pnls > 0]
losses = pnls[pnls <= 0]
sum_w = wins.sum() if len(wins) else 0
sum_l = -losses.sum() if len(losses) else 1e-9
print(f"  random: n={len(pnls)} WR={(pnls>0).mean()*100:.1f}% EV={pnls.mean():+.2f}t PF={sum_w/sum_l:.2f}")
