"""audit_regime_robustness.py — Verifie robustesse cross-regime des 4 niveaux GO + 5 combos.

Question Jackson 09/05 : "Cette semaine marche haussier mais patterns doivent
fonctionner en marche baissier" -> tester chaque niveau GO sur 3 regimes :
  - HAUSSIER (close > SMA200 ET SMA50 > SMA200)
  - BAISSIER (close < SMA200 ET SMA50 < SMA200)
  - RANGE (mixed signals)

Si EV > 0 sur LES 3 regimes -> vrai edge robuste.
Si EV positif uniquement BAISSIER (rebonds) -> bias regime, pas tradable.

Methodologie stricte conservee : TP=24t, SL=12t, costs, path-dependent.
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

# Les 4 niveaux GO + 5 combos prometteurs
TARGETS = [
    {"name": "SWING_LOW", "kind": "single", "side": "LONG",
     "cols": ["dist_last_swing_low_pct"]},
    {"name": "SWING_HIGH", "kind": "single", "side": "SHORT",
     "cols": ["dist_last_swing_high_pct"]},
    {"name": "COLOR_UP_zone", "kind": "single", "side": "LONG",
     "cols": ["dist_color_up_nearest_pct"]},
    {"name": "COLOR_DN_zone", "kind": "single", "side": "SHORT",
     "cols": ["dist_color_dn_nearest_pct"]},
    # Combos
    {"name": "LONG_DN_x_COLOR_DN", "kind": "combo", "side": "SHORT",
     "cols": ["dist_long_dn_nearest_pct", "dist_color_dn_nearest_pct"]},
    {"name": "LONG_UP_x_SWING_LOW", "kind": "combo", "side": "LONG",
     "cols": ["dist_long_up_nearest_pct", "dist_last_swing_low_pct"]},
    {"name": "PVAL_x_SWING_LOW", "kind": "combo", "side": "LONG",
     "cols": ["dist_prev_val_pct", "dist_last_swing_low_pct"]},
    {"name": "COLOR_UP_x_PVAL", "kind": "combo", "side": "LONG",
     "cols": ["dist_color_up_nearest_pct", "dist_prev_val_pct"]},
    {"name": "PVAH_x_SWING_HIGH", "kind": "combo", "side": "SHORT",
     "cols": ["dist_prev_vah_pct", "dist_last_swing_high_pct"]},
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def compute_regime(df, sma_fast=50, sma_slow=200):
    """Regime par bar :
      HAUSSIER : close > sma200 ET sma50 > sma200
      BAISSIER : close < sma200 ET sma50 < sma200
      RANGE : autre
    SMA en bars 1m. 200 bars = ~3.3h, 50 bars = ~50min. Pour 1m ca capture le micro-trend.
    Pour macro-regime hebdomadaire utiliser 200*60=12000 bars ? Trop. On reste bar-level."""
    closes = df["close"].to_numpy()
    sma_f = pd.Series(closes).rolling(sma_fast, min_periods=1).mean().to_numpy()
    sma_s = pd.Series(closes).rolling(sma_slow, min_periods=1).mean().to_numpy()
    regime = np.full(len(closes), "RANGE", dtype=object)
    haussier = (closes > sma_s) & (sma_f > sma_s)
    baissier = (closes < sma_s) & (sma_f < sma_s)
    regime[haussier] = "HAUSSIER"
    regime[baissier] = "BAISSIER"
    return regime


def compute_macro_regime(df, win_bars=1500):
    """Regime macro : sur fenetre rolling de win_bars (1500 bars 1m = ~25h),
    direction = sign(close[i] - close[i-win])."""
    closes = df["close"].to_numpy()
    n = len(closes)
    regime = np.full(n, "RANGE", dtype=object)
    for i in range(win_bars, n):
        ret = (closes[i] - closes[i - win_bars]) / closes[i - win_bars]
        if ret >= 0.005:   # +0.5% = haussier
            regime[i] = "HAUSSIER"
        elif ret <= -0.005:
            regime[i] = "BAISSIER"
    return regime


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
        tp = entry + TP_TICKS * tick
        sl = entry - SL_TICKS * tick
    else:
        tp = entry - TP_TICKS * tick
        sl = entry + SL_TICKS * tick
    for k in range(i + 1, min(i + FWD_BARS + 1, n)):
        bh = highs[k]; bl = lows[k]
        if direction == "LONG":
            sl_hit = bl <= sl; tp_hit = bh >= tp
        else:
            sl_hit = bh >= sl; tp_hit = bl <= tp
        if sl_hit and tp_hit:
            return {"pnl": -float(SL_TICKS) - cost, "exit": "SL_PESS"}
        if sl_hit:
            return {"pnl": -float(SL_TICKS) - cost, "exit": "SL"}
        if tp_hit:
            return {"pnl": float(TP_TICKS) - cost, "exit": "TP"}
    final = closes[min(i + FWD_BARS, n - 1)]
    pnl = ((final - entry) if direction == "LONG" else (entry - final)) / tick - cost
    return {"pnl": float(pnl), "exit": "TIMEOUT"}


def evaluate_per_regime(df, sym, target, regime_arr):
    """Retourne metrics par regime."""
    cols = target["cols"]
    side = target["side"]
    masks = [df[c].astype(float).abs() <= PROXIMITY_PCT for c in cols if c in df.columns]
    if not masks:
        return None
    near = masks[0]
    for m in masks[1:]:
        near = near & m
    indices = np.where(near)[0]
    n = len(df)
    last = -COOLDOWN
    trades_by_regime = {"HAUSSIER": [], "BAISSIER": [], "RANGE": []}
    for i in indices:
        if i - last < COOLDOWN:
            continue
        if i + FWD_BARS >= n:
            continue
        tr = simulate_trade(df, i, side, sym)
        if tr is None:
            continue
        reg = regime_arr[i]
        trades_by_regime[reg].append(tr["pnl"])
        last = i
    out = {}
    for reg, pnls in trades_by_regime.items():
        if not pnls:
            out[reg] = {"n": 0, "ev": 0, "wr": 0, "pf": 0}
            continue
        arr = np.array(pnls)
        n_t = len(arr)
        wr = (arr > 0).mean()
        sw = arr[arr > 0].sum()
        sl = abs(arr[arr < 0].sum())
        pf = sw / sl if sl > 0 else float("inf")
        out[reg] = {"n": n_t, "ev": float(arr.mean()), "wr": float(wr), "pf": float(pf)}
    return out


def report(sym, results, regime_label):
    print(f"\n=== ROBUSTESSE CROSS-REGIME {sym} ({regime_label}) ===")
    print(f"\n{'Niveau':<25} {'Side':<6} {'HAUS':>20} {'BAIS':>20} {'RANGE':>20}")
    print(f"{' ':<25} {' ':<6} {'n     EV    PF':>20} {'n     EV    PF':>20} {'n     EV    PF':>20}")
    print("-" * 110)
    for name, side, perregime in results:
        h = perregime["HAUSSIER"]; b = perregime["BAISSIER"]; r = perregime["RANGE"]
        h_str = f"{h['n']:>4} {h['ev']:>+5.2f} {h['pf']:>4.2f}" if h["n"] > 0 else "-- 0  -- --"
        b_str = f"{b['n']:>4} {b['ev']:>+5.2f} {b['pf']:>4.2f}" if b["n"] > 0 else "-- 0  -- --"
        r_str = f"{r['n']:>4} {r['ev']:>+5.2f} {r['pf']:>4.2f}" if r["n"] > 0 else "-- 0  -- --"
        # Verdict cross-regime
        evs = [h["ev"], b["ev"], r["ev"]]
        ns = [h["n"], b["n"], r["n"]]
        all_pos = all(e > 0 for e, n in zip(evs, ns) if n >= 30)
        verdict = " ROBUSTE" if all_pos else " BIAS"
        print(f"  {name:<23} {side:<6} {h_str:>20} {b_str:>20} {r_str:>20}{verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    ap.add_argument("--months", type=int, default=6)
    args = ap.parse_args()
    sym = args.symbol
    df = load_v4(sym, args.months)
    print(f"[{sym}] Loaded {len(df)} bars")

    # Regime micro (SMA50 vs SMA200 1-min)
    regime_micro = compute_regime(df, sma_fast=50, sma_slow=200)
    n_haus = (regime_micro == "HAUSSIER").sum()
    n_bais = (regime_micro == "BAISSIER").sum()
    n_range = (regime_micro == "RANGE").sum()
    print(f"[{sym}] Regime MICRO (SMA50/200) : HAUSSIER={n_haus} ({n_haus*100/len(df):.0f}%), "
          f"BAISSIER={n_bais} ({n_bais*100/len(df):.0f}%), RANGE={n_range} ({n_range*100/len(df):.0f}%)")

    # Regime macro (rolling 1500 bars = ~25h)
    regime_macro = compute_macro_regime(df, win_bars=1500)
    n_haus_m = (regime_macro == "HAUSSIER").sum()
    n_bais_m = (regime_macro == "BAISSIER").sum()
    n_range_m = (regime_macro == "RANGE").sum()
    print(f"[{sym}] Regime MACRO (rolling 1500b) : HAUSSIER={n_haus_m} ({n_haus_m*100/len(df):.0f}%), "
          f"BAISSIER={n_bais_m} ({n_bais_m*100/len(df):.0f}%), RANGE={n_range_m} ({n_range_m*100/len(df):.0f}%)")

    # Audit micro
    results_micro = []
    for tgt in TARGETS:
        per = evaluate_per_regime(df, sym, tgt, regime_micro)
        if per:
            results_micro.append((tgt["name"], tgt["side"], per))
    report(sym, results_micro, "MICRO 50/200 SMA")

    # Audit macro
    results_macro = []
    for tgt in TARGETS:
        per = evaluate_per_regime(df, sym, tgt, regime_macro)
        if per:
            results_macro.append((tgt["name"], tgt["side"], per))
    report(sym, results_macro, "MACRO rolling 1500b")


if __name__ == "__main__":
    main()
