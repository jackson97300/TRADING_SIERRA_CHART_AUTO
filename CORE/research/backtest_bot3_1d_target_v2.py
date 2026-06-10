"""backtest_bot3_1d_target_v2.py — Round 4 Jackson 24/05/2026.

Extensions Round 3 :
  1. Multi-entry par jour : 3 fenetres open (Asia/London/NY) au lieu de 1
  2. Variantes SL : 20 / 30 / 40 / 60 ticks
  3. Variantes proximity target : skip si dist_1d_max < 0.5%/0.3%/0.1% (target deja proche)
  4. Test sur NQ + ES combine

Hypothese Jackson : sur 1ere bar de fenetre open, en bias LONG, on peut
predire qu'on va aller chercher le 1d_max MenthorQ. Edge confirme Round 3
sur NQ+ES (PF combine ~3.5, n=29). Extension : multiplier sample x3 via
3 windows opens.

Periode : 15/12/2025 -> 21/05/2026.
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_NQ = 0.25
# 2026-05-24 : Jackson "on part sur 15/12" — MenthorQ propre depuis cette date
PERIOD_START = "2025-12-15"
PERIOD_END = "2026-05-22"

# Fenetres open ET (UTC = ET+4) :
# Asia : 20:00 ET = 00:00 UTC (J+1)
# London : 03:00 ET = 07:00 UTC
# NY : 09:30 ET = 13:30 UTC
OPEN_WINDOWS_UTC = [
    ("ASIA", "00:00", "00:30"),
    ("LONDON", "07:00", "07:30"),
    ("NY", "13:30", "14:00"),
]


def load_v4(symbol: str) -> pd.DataFrame:
    # AUDIT 2026-05-24 : v4_enriched -> v4_pure (avril complet)
    files = sorted(glob.glob(
        str(ROOT / f"DATA/datasets/v4_pure/symbol={symbol}.c.0/year=*/month=*/data.parquet")))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["date"] = df["ts_event"].dt.strftime("%Y%m%d")
    df["time_utc"] = df["ts_event"].dt.strftime("%H:%M")
    start_dt = pd.to_datetime(PERIOD_START, utc=True)
    end_dt = pd.to_datetime(PERIOD_END, utc=True)
    df = df[(df["ts_event"] >= start_dt) & (df["ts_event"] <= end_dt)].reset_index(drop=True)
    df["symbol"] = symbol
    return df


def find_first_bar_per_window(df: pd.DataFrame) -> list:
    """Retourne list de (window_name, idx) : 1ere bar de chaque (date, window)."""
    results = []
    for win_name, start, end in OPEN_WINDOWS_UTC:
        mask = (df["time_utc"] >= start) & (df["time_utc"] <= end)
        sub = df[mask]
        first_per_day_win = sub.groupby("date").head(1)
        for idx in first_per_day_win.index:
            results.append((win_name, idx))
    return results


def _safe_float(v, default=0.0):
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):
            return default
        return f
    except (TypeError, ValueError):
        return default


def simulate_trade(df: pd.DataFrame, entry_idx: int, direction: str,
                    target_pct: float, sl_ticks: int, tick: float,
                    timeout_bars: int = 360) -> dict:
    """SL fixe, TP = target_pct (1d_max ou 1d_min), timeout EOD ou 360 bars."""
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    entry_date = entry_bar["date"]
    if direction == "long":
        sl_price = entry_price - sl_ticks * tick
        tp_price = entry_price * (1 + target_pct / 100.0)
    else:
        sl_price = entry_price + sl_ticks * tick
        tp_price = entry_price * (1 + target_pct / 100.0)
    end_idx = min(len(df), entry_idx + 1 + timeout_bars)
    for j in range(entry_idx + 1, end_idx):
        bj = df.iloc[j]
        if bj["date"] != entry_date:
            exit_price = float(df.iloc[j - 1]["close"])
            pnl_pts = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
            return {"entry_price": entry_price, "exit_price": exit_price,
                     "exit_cause": "eod", "pnl_pts": pnl_pts,
                     "pnl_R": pnl_pts / (sl_ticks * tick)}
        hj = float(bj["high"]); lj = float(bj["low"])
        if direction == "long":
            if lj <= sl_price:
                return {"entry_price": entry_price, "exit_price": sl_price,
                         "exit_cause": "sl", "pnl_pts": -sl_ticks * tick, "pnl_R": -1.0}
            if hj >= tp_price:
                pnl = tp_price - entry_price
                return {"entry_price": entry_price, "exit_price": tp_price,
                         "exit_cause": "tp", "pnl_pts": pnl, "pnl_R": pnl / (sl_ticks * tick)}
        else:
            if hj >= sl_price:
                return {"entry_price": entry_price, "exit_price": sl_price,
                         "exit_cause": "sl", "pnl_pts": -sl_ticks * tick, "pnl_R": -1.0}
            if lj <= tp_price:
                pnl = entry_price - tp_price
                return {"entry_price": entry_price, "exit_price": tp_price,
                         "exit_cause": "tp", "pnl_pts": pnl, "pnl_R": pnl / (sl_ticks * tick)}
    last_bar = df.iloc[end_idx - 1]
    exit_price = float(last_bar["close"])
    pnl_pts = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    return {"entry_price": entry_price, "exit_price": exit_price,
             "exit_cause": "timeout", "pnl_pts": pnl_pts,
             "pnl_R": pnl_pts / (sl_ticks * tick)}


def stats_of(trades: list) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "wr": None, "pf": None, "ev_R": None, "pnl_R": 0.0}
    rs = [t["pnl_R"] for t in trades]
    wins = sum(1 for r in rs if r > 0)
    gains = sum(r for r in rs if r > 0)
    losses = -sum(r for r in rs if r < 0)
    pf = gains / max(losses, 0.01) if losses > 0 else None
    return {
        "n": n, "wr": round(wins / n * 100, 1),
        "pf": round(pf, 2) if pf is not None else None,
        "ev_R": round(sum(rs) / n, 3),
        "pnl_R": round(sum(rs), 2),
    }


def run_v2(symbols: list = ["NQ", "ES"]) -> pd.DataFrame:
    print(f"\n{'='*80}")
    print(f"ROUND 4 — 1D_TARGET MULTI-WINDOW + variantes SL")
    print(f"{'='*80}\n")

    # Load + concat
    dfs = {}
    for sym in symbols:
        dfs[sym] = load_v4(sym)
        print(f"{sym} : {len(dfs[sym])} bars / {dfs[sym]['date'].nunique()} jours")

    # Variants
    sl_ticks_list = [20, 30, 40, 60]
    target_min_pct_list = [0.0, 0.1, 0.3, 0.5]    # skip si target deja a moins de X%
    modes_test = ["always_long", "always_short", "closest_target", "bias_vwap"]

    results = []
    for sym in symbols:
        df = dfs[sym]
        tick = 0.25
        windows = find_first_bar_per_window(df)
        print(f"\n{sym} : {len(windows)} entry candidates (3 windows x {df['date'].nunique()} jours)")
        for sl_ticks in sl_ticks_list:
            for target_min_pct in target_min_pct_list:
                for mode in modes_test:
                    trades = []
                    for win_name, idx in windows:
                        bar = df.iloc[idx]
                        dmax = _safe_float(bar.get("dist_1d_max_ticks_pct"), 0.0)
                        dmin = _safe_float(bar.get("dist_1d_min_ticks_pct"), 0.0)

                        if mode == "always_long":
                            direction = "long"
                            target = dmax
                        elif mode == "always_short":
                            direction = "short"
                            target = dmin
                        elif mode == "closest_target":
                            if abs(dmax) < abs(dmin):
                                direction = "long"; target = dmax
                            else:
                                direction = "short"; target = dmin
                        elif mode == "bias_vwap":
                            slope = _safe_float(bar.get("vwap_slope_10"), 0.0)
                            if slope > 0:
                                direction = "long"; target = dmax
                            else:
                                direction = "short"; target = dmin
                        else:
                            continue

                        # Filtre target trop proche (deja collé)
                        if abs(target) < target_min_pct:
                            continue
                        # Direction coherente avec sens target
                        if direction == "long" and target <= 0: continue
                        if direction == "short" and target >= 0: continue

                        trade = simulate_trade(df, idx, direction, target, sl_ticks, tick)
                        if trade is None: continue
                        trade["window"] = win_name
                        trade["sym"] = sym
                        trades.append(trade)

                    s = stats_of(trades)
                    if s["n"] >= 5:    # min 5 pour reporter
                        results.append({
                            "sym": sym, "sl_ticks": sl_ticks,
                            "target_min_pct": target_min_pct, "mode": mode,
                            **s,
                        })

    df_res = pd.DataFrame(results)
    if df_res.empty:
        print("\nAucun resultat (sample trop petit)")
        return df_res

    # Top 20 by PnL_R
    print()
    print("=" * 80)
    print(f"TOP 20 by PnL_R (n>=5 trades)")
    print("=" * 80)
    print(df_res.sort_values("pnl_R", ascending=False).head(20).to_string(index=False))

    # Best per mode
    print()
    print("=" * 80)
    print(f"BEST CONFIG par mode (max PF avec n >= 10)")
    print("=" * 80)
    qualified = df_res[df_res["n"] >= 10]
    if not qualified.empty:
        best = qualified.loc[qualified.groupby("mode")["pf"].idxmax()]
        print(best.to_string(index=False))

    # Aggregate par mode (somme tous sl/target/sym)
    print()
    print("=" * 80)
    print(f"AGGREGATE par mode (somme sl/target/sym)")
    print("=" * 80)
    by_mode = df_res.groupby("mode").agg(
        n_total=("n", "sum"),
        n_buckets=("n", "size"),
        pf_median=("pf", "median"),
        pnl_R_median=("pnl_R", "median"),
        pnl_R_sum=("pnl_R", "sum"),
    ).round(2)
    print(by_mode.to_string())

    return df_res


if __name__ == "__main__":
    df = run_v2()
    df.to_csv(ROOT / "DATA" / "bot3_1d_target_v2_results.csv", index=False)
