"""backtest_rules_sltp.py — Backtest rules_trader_pd_attentiste + SLTPEngine.

Compare bot RULES (rules_trader signal direction + SLTPEngine SL/TP) vs paper ML 24/04 (PF 2.64).

Architecture :
  1. Pour chaque bar du dataset v5d :
     - Charge PDLevels J-1 depuis DATA/PD_LEVELS/
     - rules_trader.evaluate_scenarios() → signal direction (LONG/SHORT)
     - Si signal valide → SLTPEngine.evaluate_single(bar, direction) → SL/TP
     - Simule trade (entry close, exit TP/SL/timeout 60 bars)
  2. Cooldown 30 min apres exit
  3. Metrics : PF, WR, EV, Sharpe, MaxDD, n_trades

Usage : python -X utf8 CORE/research/backtest_rules_sltp.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.pd_levels_extractor import PDLevels
from CORE.rules_trader_pd_attentiste import evaluate_scenarios
from CORE.mia_sltp import SLTPEngine

TICK = 0.25
HORIZON = 60
COOLDOWN_BARS = 30
COST_TICKS = {"NQ": 0.5, "ES": 1.0}


def load_pd_levels(date_str: str, symbol: str) -> PDLevels | None:
    fp = ROOT / "DATA" / "PD_LEVELS" / f"{date_str}_{symbol}.json"
    if not fp.exists():
        return None
    with open(fp, "r") as f:
        d = json.load(f)
    return PDLevels(**d)


def simulate_trade(direction: int, entry: float, sl_ticks: float, tp_ticks: float,
                    bars_after: pd.DataFrame, symbol: str) -> dict:
    """Simule trade : entry close + suivi TP/SL/timeout 60 bars."""
    cost = COST_TICKS[symbol]
    sl_distance = sl_ticks * TICK
    tp_distance = tp_ticks * TICK

    if direction == 1:  # LONG
        sl_lvl = entry - sl_distance
        tp_lvl = entry + tp_distance
    else:  # SHORT
        sl_lvl = entry + sl_distance
        tp_lvl = entry - tp_distance

    high_col = "high" if "high" in bars_after.columns else "bar_high"
    low_col = "low" if "low" in bars_after.columns else "bar_low"
    close_col = "close"

    for k in range(min(HORIZON, len(bars_after))):
        h = bars_after.iloc[k][high_col]
        l = bars_after.iloc[k][low_col]
        if direction == 1:
            if l <= sl_lvl:
                return {"pnl": -sl_ticks - cost, "exit": "SL", "bars": k+1}
            if h >= tp_lvl:
                return {"pnl": tp_ticks - cost, "exit": "TP", "bars": k+1}
        else:
            if h >= sl_lvl:
                return {"pnl": -sl_ticks - cost, "exit": "SL", "bars": k+1}
            if l <= tp_lvl:
                return {"pnl": tp_ticks - cost, "exit": "TP", "bars": k+1}
    # Timeout
    last_close = bars_after.iloc[min(HORIZON, len(bars_after))-1][close_col]
    pnl_pts = (last_close - entry) if direction == 1 else (entry - last_close)
    return {"pnl": pnl_pts / TICK - cost, "exit": "TIMEOUT", "bars": HORIZON}


def backtest_symbol(symbol: str) -> dict:
    print(f"\n{'='*80}")
    print(f"  {symbol} — Backtest rules_trader + SLTPEngine")
    print(f"{'='*80}")

    fp = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5d.parquet"
    df = pd.read_parquet(fp)
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    df["ts_dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df["date_str"] = df["ts_dt"].dt.strftime("%Y%m%d")
    print(f"  RTH bars : {len(df):,}")

    sltp_engine = SLTPEngine(symbol=symbol)
    trades = []
    last_exit_bar = -COOLDOWN_BARS - 1

    # PD levels by date (cache)
    pdl_cache = {}

    n_signals = 0
    n_sltp_valid = 0
    n_no_pdl = 0

    print(f"  Backtest...", flush=True)
    t0 = time.perf_counter()

    for i, bar in enumerate(df.itertuples(index=False)):
        if i - last_exit_bar < COOLDOWN_BARS:
            continue
        if i + HORIZON >= len(df):
            break

        date_str = bar.date_str
        # Get PDL (cache)
        if date_str not in pdl_cache:
            pdl_dates = sorted(p.stem.split("_")[0] for p in (ROOT / "DATA" / "PD_LEVELS").glob(f"*_{symbol}.json"))
            prev_dates = [d for d in pdl_dates if d < date_str]
            if not prev_dates:
                pdl_cache[date_str] = None
            else:
                pdl_cache[date_str] = load_pd_levels(prev_dates[-1], symbol)

        pdl = pdl_cache[date_str]
        if pdl is None:
            n_no_pdl += 1
            continue

        bar_dict = bar._asdict()
        signals = evaluate_scenarios(bar_dict, pdl)
        if not signals:
            continue
        n_signals += 1

        # Take 1st signal
        signal = signals[0]
        direction = signal.direction

        # SLTPEngine for SL/TP
        try:
            sltp = sltp_engine.evaluate_single(bar_dict, direction)
        except Exception as e:
            continue
        if not sltp.valid:
            continue
        n_sltp_valid += 1

        entry = float(bar_dict.get("close", bar_dict.get("price", 0)))
        bars_after = df.iloc[i+1:i+HORIZON+1]
        result = simulate_trade(direction, entry, sltp.sl_ticks, sltp.tp1_ticks,
                                 bars_after, symbol)

        trades.append({
            "i": i, "ts": bar_dict["ts"],
            "scenario": signal.scenario, "direction": direction,
            "entry": entry, "sl_ticks": sltp.sl_ticks, "tp_ticks": sltp.tp1_ticks,
            "sl_wall": sltp.sl_wall, "tp_wall": sltp.tp1_wall,
            **result,
        })
        last_exit_bar = i + result["bars"]

    elapsed = time.perf_counter() - t0
    print(f"  Done in {elapsed:.1f}s")
    print(f"  Signals : {n_signals:,}, SLTP valid : {n_sltp_valid:,}, No PDL : {n_no_pdl:,}")
    print(f"  Trades executes : {len(trades):,}")

    if not trades:
        return {"symbol": symbol, "n_trades": 0}

    pnls = np.array([t["pnl"] for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    pf = float(wins.sum() / -losses.sum()) if len(losses) > 0 and losses.sum() < 0 else float("inf")
    wr = len(wins) / len(pnls)
    ev = pnls.mean()
    sharpe = pnls.mean() / pnls.std() * np.sqrt(252) if pnls.std() > 0 else 0
    cum = np.cumsum(pnls)
    max_dd = float(np.max(np.maximum.accumulate(cum) - cum))

    # Per scenario
    df_t = pd.DataFrame(trades)
    print(f"\n  RECAP {symbol} :")
    print(f"    n_trades   : {len(trades):,}")
    print(f"    WR         : {wr*100:.1f}%")
    print(f"    PF         : {pf:.2f}")
    print(f"    EV/trade   : {ev:+.1f}t")
    print(f"    Sharpe     : {sharpe:+.2f}")
    print(f"    MaxDD      : {max_dd:.0f}t")
    print(f"    Total PnL  : {pnls.sum():+.0f}t")
    print(f"    n_jours    : {df_t['ts'].apply(lambda t: pd.Timestamp(t,unit='ms').date()).nunique()}")
    print(f"    trades/jour: {len(trades) / max(1, df_t['ts'].apply(lambda t: pd.Timestamp(t,unit='ms').date()).nunique()):.1f}")
    print(f"\n  Par scenario :")
    for sc in df_t["scenario"].unique():
        sub = df_t[df_t["scenario"] == sc]
        sub_wins = sub[sub["pnl"] > 0]
        sub_pf = sub_wins["pnl"].sum() / -sub[sub["pnl"] < 0]["pnl"].sum() if len(sub[sub["pnl"]<0]) > 0 else float("inf")
        print(f"    {sc:35s} N={len(sub):>4} WR={len(sub_wins)/len(sub)*100:>5.1f}% PF={sub_pf:>5.2f} EV={sub['pnl'].mean():>+6.1f}t")

    return {
        "symbol": symbol, "n_trades": len(trades), "wr": wr, "pf": pf,
        "ev": ev, "sharpe": sharpe, "max_dd": max_dd, "trades_df": df_t,
    }


def main():
    print("=" * 80)
    print("  BACKTEST RULES + SLTP — comparison vs paper ML 24/04 (PF 2.64)")
    print("=" * 80)

    results = {}
    for sym in ["NQ", "ES"]:
        r = backtest_symbol(sym)
        results[sym] = r

    # Summary
    print(f"\n{'='*80}")
    print(f"  SUMMARY")
    print(f"{'='*80}")
    print(f"  {'Symbol':<8} {'N':>6} {'WR%':>6} {'PF':>6} {'EV':>6} {'Sharpe':>7} {'MaxDD':>7}")
    for sym, r in results.items():
        if r["n_trades"] == 0:
            print(f"  {sym:<8} 0 trades")
            continue
        print(f"  {sym:<8} {r['n_trades']:>6} {r['wr']*100:>6.1f} {r['pf']:>6.2f} "
              f"{r['ev']:>+6.1f} {r['sharpe']:>+7.2f} {r['max_dd']:>7.0f}")
    print()
    print(f"  Reference paper ML 24/04 NQ : PF 2.64, WR 61.5%, +312t/contract")


if __name__ == "__main__":
    main()
