"""backtest_bot3_1d_max_min_prediction.py — Idee Jackson 24/05/2026.

Question : peut-on PREDIRE en debut de journee RTH si le marche va aller
chercher le 1d_max MenthorQ (rally LONG) ou le 1d_min MenthorQ (chute SHORT) ?

Setup teste :
  - Entry a la 1ere bar RTH (proche 09:30 ET = 13:30 UTC)
  - Direction selon contexte debut journee :
    * Bias bullish (vwap_slope > 0 + delta_day > 0) -> LONG vers 1d_max
    * Bias bearish (vwap_slope < 0 + delta_day < 0) -> SHORT vers 1d_min
    * Sinon : SKIP
  - TP = touche du 1d_max (LONG) ou 1d_min (SHORT) predit
  - SL = 30 ticks NQ
  - Timeout = EOD (16:00 ET = 20:00 UTC)

Periode : 15/12/2025 -> 21/05/2026 (data MenthorQ dispo).

2 series testees :
  - SERIE A : entry au 1er bar RTH (forced direction selon bias)
  - SERIE B : entry SI confluence forte (bias + open_type + gex_sign aligned)
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TICK_NQ = 0.25
SL_TICKS = 30
TIMEOUT_BARS = 360    # 6h pour aller EOD depuis 09:30 ET
PERIOD_START = "2025-12-15"
PERIOD_END = "2026-05-22"


def load_v4_filtered(symbol: str = "NQ") -> pd.DataFrame:
    files = sorted(glob.glob(
        str(ROOT / f"DATA/datasets/v4_enriched/symbol={symbol}.c.0/year=*/month=*/data.parquet")))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    df["date"] = df["ts_event"].dt.strftime("%Y%m%d")
    start_dt = pd.to_datetime(PERIOD_START, utc=True)
    end_dt = pd.to_datetime(PERIOD_END, utc=True)
    df = df[(df["ts_event"] >= start_dt) & (df["ts_event"] <= end_dt)].reset_index(drop=True)
    return df


def find_first_rth_bar_per_day(df: pd.DataFrame) -> pd.DataFrame:
    """Identifie la 1ere bar RTH par jour (1ere bar ou is_in_us_cash == 1)."""
    if "is_in_us_cash" not in df.columns:
        # Fallback : bar a 13:30 UTC = 09:30 ET
        df_filt = df[df["ts_event"].dt.strftime("%H:%M") == "13:30"]
        return df_filt
    # 1ere bar RTH par jour
    df_rth = df[df["is_in_us_cash"] == 1].copy()
    first_per_day = df_rth.groupby("date").head(1)
    return first_per_day


def simulate_trade_to_target(df: pd.DataFrame, entry_idx: int, direction: str,
                              tp_target_pct: float) -> dict:
    """Simulate trade : SL 30t fixe, TP = touche du niveau (1d_max ou 1d_min),
    timeout = end of day (16:00 ET = 20:00 UTC).
    """
    if entry_idx >= len(df) - 1:
        return None
    entry_bar = df.iloc[entry_idx]
    entry_price = float(entry_bar["close"])
    entry_date = entry_bar["date"]

    if direction == "long":
        sl_price = entry_price - SL_TICKS * TICK_NQ
        # TP target : prix qui correspond au 1d_max
        # dist_1d_max_ticks_pct = (1d_max - close) / close * 100
        # 1d_max = close * (1 + dist_pct / 100)
        tp_price = entry_price * (1 + tp_target_pct / 100.0)
    else:
        sl_price = entry_price + SL_TICKS * TICK_NQ
        tp_price = entry_price * (1 + tp_target_pct / 100.0)    # dist negative

    end_idx = min(len(df), entry_idx + 1 + TIMEOUT_BARS)
    for j in range(entry_idx + 1, end_idx):
        bj = df.iloc[j]
        # EOD = changement de date
        if bj["date"] != entry_date:
            # Close at last bar before date change
            exit_price = float(df.iloc[j - 1]["close"])
            if direction == "long":
                pnl_pts = exit_price - entry_price
            else:
                pnl_pts = entry_price - exit_price
            return {
                "entry_price": entry_price, "exit_price": exit_price,
                "exit_cause": "eod", "pnl_pts": pnl_pts,
                "pnl_R": pnl_pts / (SL_TICKS * TICK_NQ),
                "duration": j - 1 - entry_idx,
            }
        hj = float(bj["high"])
        lj = float(bj["low"])
        if direction == "long":
            if lj <= sl_price:
                return {"entry_price": entry_price, "exit_price": sl_price,
                         "exit_cause": "sl", "pnl_pts": -SL_TICKS * TICK_NQ,
                         "pnl_R": -1.0, "duration": j - entry_idx}
            if hj >= tp_price:
                pnl_pts = tp_price - entry_price
                return {"entry_price": entry_price, "exit_price": tp_price,
                         "exit_cause": "tp_1d_max", "pnl_pts": pnl_pts,
                         "pnl_R": pnl_pts / (SL_TICKS * TICK_NQ),
                         "duration": j - entry_idx}
        else:
            if hj >= sl_price:
                return {"entry_price": entry_price, "exit_price": sl_price,
                         "exit_cause": "sl", "pnl_pts": -SL_TICKS * TICK_NQ,
                         "pnl_R": -1.0, "duration": j - entry_idx}
            if lj <= tp_price:
                pnl_pts = entry_price - tp_price
                return {"entry_price": entry_price, "exit_price": tp_price,
                         "exit_cause": "tp_1d_min", "pnl_pts": pnl_pts,
                         "pnl_R": pnl_pts / (SL_TICKS * TICK_NQ),
                         "duration": j - entry_idx}
    # Timeout : close at last bar
    last_bar = df.iloc[end_idx - 1]
    exit_price = float(last_bar["close"])
    if direction == "long":
        pnl_pts = exit_price - entry_price
    else:
        pnl_pts = entry_price - exit_price
    return {"entry_price": entry_price, "exit_price": exit_price,
             "exit_cause": "timeout", "pnl_pts": pnl_pts,
             "pnl_R": pnl_pts / (SL_TICKS * TICK_NQ),
             "duration": end_idx - 1 - entry_idx}


def _safe_float(v, default=0.0):
    try:
        f = float(v)
        if f != f or abs(f) == float("inf"):
            return default
        return f
    except (TypeError, ValueError):
        return default


def determine_direction(bar, mode: str) -> Optional[str]:
    """Determine direction (long/short/None) selon mode contexte.

    mode :
      - "always_long" : toujours LONG (baseline)
      - "always_short" : toujours SHORT (baseline)
      - "bias_vwap" : long si vwap_slope_10 > 0, short sinon
      - "bias_delta" : long si delta_day_dir > 0, short si < 0, sinon None
      - "bias_combine" : long si vwap_slope > 0 AND delta_day > 0, short si les deux <0, sinon None
      - "open_type" : long si open_type in {OPEN_DRIVE_UP=1, OD_UP=5}, short si {OPEN_DRIVE_DOWN=2}, sinon None
      - "gex_sign" : long si total_gex > 0 (suppressive market = stay range LONG VAH/HVL), short si < 0 (explosive)
    """
    if mode == "always_long":
        return "long"
    if mode == "always_short":
        return "short"
    if mode == "bias_vwap":
        slope = _safe_float(bar.get("vwap_slope_10"), 0.0)
        return "long" if slope > 0 else "short"
    if mode == "bias_delta":
        d = _safe_float(bar.get("delta_day_dir"), 0.0)
        if d > 0: return "long"
        if d < 0: return "short"
        return None
    if mode == "bias_combine":
        slope = _safe_float(bar.get("vwap_slope_10"), 0.0)
        d = _safe_float(bar.get("delta_day_dir"), 0.0)
        if slope > 0 and d > 0: return "long"
        if slope < 0 and d < 0: return "short"
        return None
    if mode == "open_type":
        ot = int(_safe_float(bar.get("open_type"), 0))
        if ot in (1, 5):    # OD_UP, OD_UP_strong
            return "long"
        if ot in (2, 6):    # OD_DOWN
            return "short"
        return None
    if mode == "gex_sign":
        gex = _safe_float(bar.get("mq_total_gex"), 0.0)
        if gex > 0: return "long"
        if gex < 0: return "short"
        return None
    if mode == "closest_target":
        # Direction du target le plus proche (predicteur naif distance pure)
        dmax = _safe_float(bar.get("dist_1d_max_ticks_pct"), 999.0)
        dmin = _safe_float(bar.get("dist_1d_min_ticks_pct"), -999.0)
        if abs(dmax) < abs(dmin):
            return "long"
        return "short"
    return None


def run_backtest_1d_max_min(symbol: str = "NQ") -> pd.DataFrame:
    print(f"\n{'='*70}")
    print(f"BACKTEST 1D_MAX/MIN PREDICTION — {symbol}")
    print(f"Periode : {PERIOD_START} -> {PERIOD_END}")
    print(f"{'='*70}\n")

    df = load_v4_filtered(symbol)
    print(f"Bars loaded : {len(df)} ({df['date'].nunique()} jours)")

    # 1ere bar RTH par jour
    first_rth = find_first_rth_bar_per_day(df)
    print(f"1ere bar RTH par jour : {len(first_rth)} candidats")

    modes = [
        "always_long", "always_short",
        "bias_vwap", "bias_delta", "bias_combine",
        "open_type", "gex_sign", "closest_target",
    ]

    results = []
    for mode in modes:
        trades = []
        skipped = 0
        for _, entry_bar in first_rth.iterrows():
            direction = determine_direction(entry_bar, mode)
            if direction is None:
                skipped += 1
                continue
            # Compute target dist
            if direction == "long":
                target_pct = _safe_float(entry_bar.get("dist_1d_max_ticks_pct"), 0.0)
                if target_pct <= 0:
                    skipped += 1
                    continue
            else:
                target_pct = _safe_float(entry_bar.get("dist_1d_min_ticks_pct"), 0.0)
                if target_pct >= 0:
                    skipped += 1
                    continue
            # Find entry_idx in df
            entry_idx = entry_bar.name
            trade = simulate_trade_to_target(df, entry_idx, direction, target_pct)
            if trade is None:
                skipped += 1
                continue
            trade["mode"] = mode
            trade["direction"] = direction
            trade["target_pct"] = round(target_pct, 4)
            trades.append(trade)

        if len(trades) == 0:
            continue
        # Stats
        n = len(trades)
        pnl_Rs = [t["pnl_R"] for t in trades]
        wins = sum(1 for r in pnl_Rs if r > 0)
        gains_R = sum(r for r in pnl_Rs if r > 0)
        losses_R = -sum(r for r in pnl_Rs if r < 0)
        pf = gains_R / max(losses_R, 0.01) if losses_R > 0 else None
        wr = wins / n * 100
        ev_R = sum(pnl_Rs) / n
        pnl_R_total = sum(pnl_Rs)
        exit_dist = {}
        for t in trades:
            c = t["exit_cause"]
            exit_dist[c] = exit_dist.get(c, 0) + 1
        long_trades = sum(1 for t in trades if t["direction"] == "long")
        results.append({
            "mode": mode,
            "n": n,
            "n_long": long_trades,
            "n_short": n - long_trades,
            "skipped": skipped,
            "wr": round(wr, 1),
            "pf": round(pf, 2) if pf is not None else None,
            "ev_R": round(ev_R, 3),
            "pnl_R_total": round(pnl_R_total, 2),
            "exits": exit_dist,
        })
        print(f"  {mode:18s} | n={n:3d} ({long_trades}L/{n-long_trades}S) | "
              f"WR={wr:5.1f}% PF={pf if pf else 'inf':<6} EV={ev_R:+.3f}R "
              f"PnL={pnl_R_total:+.2f}R | exits={exit_dist}")

    return pd.DataFrame(results)


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "NQ"
    df_res = run_backtest_1d_max_min(sym)
    print()
    print("=" * 70)
    print(f"SUMMARY 1D_MAX/MIN PREDICTION — {sym}")
    print("=" * 70)
    print(df_res[["mode", "n", "wr", "pf", "ev_R", "pnl_R_total"]].to_string(index=False))
