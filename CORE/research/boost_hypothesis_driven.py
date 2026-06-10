"""boost_hypothesis_driven.py — Tests cibles hypothese-driven (anti pattern 11).

Au lieu de tester 22 features par combo (data mining), on teste UNE hypothese
trader-justifiee par combo. Total 4 tests cibles -> Bonferroni alpha 0.0125 ->
seuil PSR 0.988 acceptable.

Hypotheses :
  1. LONG_DN_x_COLOR_DN ES + cvd_bear : SHORT continuation Wyckoff downtrend
  2. COLOR_UP_x_PVAL ES + range_low : Spring Wyckoff double-touche bottom range
  3. COLOR_UP_x_PVAL NQ + range_low : idem
  4. PVAH_x_SWING_HIGH NQ + cvd_bear : SHORT resistance + flux baissier confirme

Methodologie stricte : TP=24t, SL=12t, costs, path-dependent, WF 12 folds, PSR Bailey.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}
TP_TICKS = 24
SL_TICKS = 12
FWD_BARS = 30
COOLDOWN = 45
PROXIMITY_PCT = 0.02

# Tests hypothese-driven : (sym, name, side, base_cols, hypothesis_filter)
HYPOTHESIS_TESTS = [
    {"sym": "ES", "name": "LONG_DN_x_COLOR_DN + cvd_bear", "side": "SHORT",
     "cols": ["dist_long_dn_nearest_pct", "dist_color_dn_nearest_pct"],
     "filter_col": "cvd_5d_rolling_ffd", "op": "<", "thr": -50,
     "rationale": "ES baissier confirme + retouche LONG_DN+COLOR_DN = continuation Wyckoff downtrend"},
    {"sym": "ES", "name": "COLOR_UP_x_PVAL + range_low", "side": "LONG",
     "cols": ["dist_color_up_nearest_pct", "dist_prev_val_pct"],
     "filter_col": "position_in_range", "op": "<", "thr": 0.30,
     "rationale": "Double touche support COLOR_UP + PVAL en bas range = Spring Wyckoff haute conviction"},
    {"sym": "NQ", "name": "COLOR_UP_x_PVAL + range_low", "side": "LONG",
     "cols": ["dist_color_up_nearest_pct", "dist_prev_val_pct"],
     "filter_col": "position_in_range", "op": "<", "thr": 0.30,
     "rationale": "Idem ES — Spring Wyckoff bottom range"},
    {"sym": "NQ", "name": "PVAH_x_SWING_HIGH + cvd_bear", "side": "SHORT",
     "cols": ["dist_prev_vah_pct", "dist_last_swing_high_pct"],
     "filter_col": "cvd_5d_rolling_ffd", "op": "<", "thr": -50,
     "rationale": "SHORT resistance double + flux baissier = double convergence"},
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def simulate_trade(df, i, direction, sym):
    n = len(df)
    if i + FWD_BARS >= n:
        return None
    tick = TICK_SIZE[sym]; cost = COSTS_TICKS[sym]
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    entry = closes[i]
    if direction == "LONG":
        tp = entry + TP_TICKS * tick; sl = entry - SL_TICKS * tick
    else:
        tp = entry - TP_TICKS * tick; sl = entry + SL_TICKS * tick
    for k in range(i + 1, min(i + FWD_BARS + 1, n)):
        bh = highs[k]; bl = lows[k]
        if direction == "LONG":
            sl_hit = bl <= sl; tp_hit = bh >= tp
        else:
            sl_hit = bh >= sl; tp_hit = bl <= tp
        if sl_hit and tp_hit: return -float(SL_TICKS) - cost
        if sl_hit:            return -float(SL_TICKS) - cost
        if tp_hit:            return float(TP_TICKS) - cost
    final = closes[min(i + FWD_BARS, n - 1)]
    return float(((final - entry) if direction == "LONG" else (entry - final)) / tick - cost)


def evaluate(df, sym, cols, side, filter_col=None, op=None, thr=None):
    masks = []
    for c in cols:
        if c not in df.columns:
            return None
        masks.append(df[c].astype(float).abs() <= PROXIMITY_PCT)
    near = masks[0]
    for m in masks[1:]:
        near = near & m
    if filter_col:
        if filter_col not in df.columns:
            return None
        s = df[filter_col].astype(float)
        if op == ">":   f_mask = s > thr
        elif op == "<": f_mask = s < thr
        elif op == ">=":f_mask = s >= thr
        elif op == "<=":f_mask = s <= thr
        elif op == "==":f_mask = s == thr
        else: return None
        near = near & f_mask
    indices = np.where(near)[0]
    n = len(df)
    last = -COOLDOWN
    pnls = []
    for i in indices:
        if i - last < COOLDOWN:
            continue
        if i + FWD_BARS >= n:
            continue
        pnl = simulate_trade(df, i, side, sym)
        if pnl is None:
            continue
        pnls.append(pnl); last = i
    if len(pnls) < 30:
        return {"n": len(pnls), "ev": 0, "pf": 0, "wr": 0, "psr": 0, "pos_folds": 0}
    arr = np.array(pnls)
    n_t = len(arr)
    wr = (arr > 0).mean()
    sw = arr[arr > 0].sum(); sl = abs(arr[arr < 0].sum())
    pf = sw / sl if sl > 0 else float("inf")
    ev = arr.mean()
    if arr.std() > 0 and n_t > 1:
        from scipy.stats import skew, kurtosis, norm
        sk = skew(arr); kt = kurtosis(arr, fisher=False)
        sr = arr.mean() / arr.std()
        denom = max(1e-9, np.sqrt(1 - sk * sr + (kt - 1) / 4 * sr**2))
        psr = float(norm.cdf(sr * np.sqrt(n_t - 1) / denom))
    else:
        psr = 0.5
    cuts = np.linspace(0, n_t, 13, dtype=int)
    pos_folds = 0
    for k in range(12):
        sub = arr[cuts[k]:cuts[k + 1]]
        if len(sub) >= 1 and sub.sum() >= 0:
            pos_folds += 1
    return {"n": n_t, "ev": float(ev), "pf": float(pf), "wr": float(wr),
            "psr": float(psr), "pos_folds": pos_folds}


def main():
    BONF_ALPHA = 0.05 / len(HYPOTHESIS_TESTS)
    PSR_TH = 1 - BONF_ALPHA
    print(f"\n=== TESTS HYPOTHESIS-DRIVEN (anti pattern 11) ===")
    print(f"=== {len(HYPOTHESIS_TESTS)} tests, Bonferroni alpha={BONF_ALPHA:.4f}, PSR seuil={PSR_TH:.4f} ===\n")

    cache = {}
    for test in HYPOTHESIS_TESTS:
        sym = test["sym"]
        if sym not in cache:
            cache[sym] = load_v4(sym)
            print(f"[{sym}] Loaded {len(cache[sym])} bars")
        df = cache[sym]
        print(f"\n--- {test['name']} ({sym}) ---")
        print(f"  Rationale : {test['rationale']}")

        # Baseline (combo seul)
        base = evaluate(df, sym, test["cols"], test["side"])
        if base is None or base["n"] < 30:
            print(f"  BASELINE : sample insuffisant"); continue
        print(f"  BASELINE : n={base['n']}, EV={base['ev']:+.2f}, PF={base['pf']:.2f}, "
              f"WF={base['pos_folds']}/12, PSR={base['psr']:.3f}")

        # Avec hypothese
        h = evaluate(df, sym, test["cols"], test["side"],
                      test["filter_col"], test["op"], test["thr"])
        if h is None or h["n"] < 30:
            print(f"  HYPOTHESIS : sample insuffisant (n={h['n'] if h else 0})"); continue
        delta = h["ev"] - base["ev"]
        is_go = (h["n"] >= 30 and h["ev"] >= 3.0 and h["pf"] >= 1.4 and
                 h["pos_folds"] >= 10 and h["psr"] >= PSR_TH)
        verdict = "GO" if is_go else ("BOOST" if delta > 1.0 else "—")
        print(f"  WITH FILTER : n={h['n']}, EV={h['ev']:+.2f} (dEV={delta:+.2f}), "
              f"PF={h['pf']:.2f}, WF={h['pos_folds']}/12, PSR={h['psr']:.3f} -> {verdict}")


if __name__ == "__main__":
    main()
