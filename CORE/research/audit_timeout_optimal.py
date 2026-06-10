"""audit_timeout_optimal.py — Trouver le timeout optimal pour les 4 niveaux Sidak.

Jackson 09/05 : "trop de TIMEOUT hier, 30 min trop long".

Pour chaque niveau Sidak, simule plusieurs timeouts (10/15/20/30/45/60 bars)
et mesure :
  - % TP / SL / TIMEOUT
  - EV/trade par timeout
  - Sweet spot timeout (max EV)

Methodologie : TP=24t SL=12t path-dependent + costs ES 2t / NQ 3t.
Cooldown 45b global (anti chevauchement).
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_SIZE = {"NQ": 0.25, "ES": 0.25}
COSTS_TICKS = {"ES": 2.0, "NQ": 3.0}
TP_TICKS = 24
SL_TICKS = 12
COOLDOWN = 45
PROXIMITY_PCT = 0.02
TIMEOUTS_TO_TEST = [10, 15, 20, 30, 45, 60]

LEVELS = [
    {"name": "SWING_LOW",     "side": "LONG",  "col": "dist_last_swing_low_pct"},
    {"name": "SWING_HIGH",    "side": "SHORT", "col": "dist_last_swing_high_pct"},
    {"name": "COLOR_UP_zone", "side": "LONG",  "col": "dist_color_up_nearest_pct"},
    {"name": "COLOR_DN_zone", "side": "SHORT", "col": "dist_color_dn_nearest_pct"},
]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    return df


def simulate_trade_with_timeout(df, i, side, sym, timeout_bars):
    """Retourne (pnl, exit_reason, bars_held)."""
    n = len(df)
    if i + timeout_bars >= n:
        return None
    tick = TICK_SIZE[sym]; cost = COSTS_TICKS[sym]
    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    entry = closes[i]
    if side == "LONG":
        tp = entry + TP_TICKS * tick; sl = entry - SL_TICKS * tick
    else:
        tp = entry - TP_TICKS * tick; sl = entry + SL_TICKS * tick
    for k in range(i + 1, min(i + timeout_bars + 1, n)):
        bh = highs[k]; bl = lows[k]
        if side == "LONG":
            sl_hit = bl <= sl; tp_hit = bh >= tp
        else:
            sl_hit = bh >= sl; tp_hit = bl <= tp
        if sl_hit and tp_hit:
            return (-float(SL_TICKS) - cost, "SL_PESS", k - i)
        if sl_hit:
            return (-float(SL_TICKS) - cost, "SL", k - i)
        if tp_hit:
            return (float(TP_TICKS) - cost, "TP", k - i)
    final = closes[min(i + timeout_bars, n - 1)]
    pnl = float(((final - entry) if side == "LONG" else (entry - final)) / tick - cost)
    return (pnl, "TIMEOUT", timeout_bars)


def evaluate_level_timeout(df, sym, level, timeout_bars):
    if level["col"] not in df.columns:
        return None
    near = df[level["col"]].astype(float).abs() <= PROXIMITY_PCT
    indices = np.where(near)[0]
    n = len(df)
    last = -COOLDOWN
    trades = []
    for i in indices:
        if i - last < COOLDOWN: continue
        result = simulate_trade_with_timeout(df, i, level["side"], sym, timeout_bars)
        if result is None: continue
        pnl, exit_r, bars = result
        trades.append({"pnl": pnl, "exit": exit_r, "bars": bars})
        last = i
    if len(trades) < 30:
        return None
    pnls = np.array([t["pnl"] for t in trades])
    n_t = len(pnls)
    n_tp = sum(1 for t in trades if t["exit"] == "TP")
    n_sl = sum(1 for t in trades if t["exit"] in ("SL", "SL_PESS"))
    n_to = sum(1 for t in trades if t["exit"] == "TIMEOUT")
    avg_bars = np.mean([t["bars"] for t in trades])
    ev = pnls.mean()
    sw = pnls[pnls > 0].sum(); sl_sum = abs(pnls[pnls < 0].sum())
    pf = sw / sl_sum if sl_sum > 0 else float("inf")
    return {"n": n_t, "ev": float(ev), "pf": float(pf),
            "tp_pct": n_tp / n_t * 100, "sl_pct": n_sl / n_t * 100,
            "to_pct": n_to / n_t * 100, "avg_bars": float(avg_bars),
            "total": float(pnls.sum())}


def main():
    print(f"\n=== AUDIT TIMEOUT OPTIMAL — 4 niveaux Sidak ===")
    print(f"=== Timeouts testes : {TIMEOUTS_TO_TEST} minutes ===\n")
    for sym in ["ES", "NQ"]:
        df = load_v4(sym, 6)
        if df.empty: continue
        print(f"\n{'='*100}")
        print(f"=== {sym} ===")
        print(f"{'='*100}")
        for lvl in LEVELS:
            print(f"\n--- {lvl['name']} {lvl['side']} ---")
            print(f"  {'Timeout':<10} {'n':>5} {'TP%':>6} {'SL%':>6} {'TO%':>6} {'avg_b':>7} {'EV':>7} {'PF':>5} {'Total':>8}")
            best = None
            for to in TIMEOUTS_TO_TEST:
                m = evaluate_level_timeout(df, sym, lvl, to)
                if m is None: continue
                marker = ""
                if best is None or m["ev"] > best["ev"]:
                    best = {**m, "to": to}
                print(f"  {to}b ({to}m):    {m['n']:>5} {m['tp_pct']:>5.1f}% {m['sl_pct']:>5.1f}% "
                      f"{m['to_pct']:>5.1f}% {m['avg_bars']:>6.1f}b {m['ev']:>+6.2f} "
                      f"{m['pf']:>5.2f} {m['total']:>+7.0f}t{marker}")
            if best:
                print(f"  >>> OPTIMAL : {best['to']}b (EV {best['ev']:+.2f}t, total {best['total']:+.0f}t)")


if __name__ == "__main__":
    main()
