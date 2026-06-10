"""bn_v5_threshold_backtest.py — Backtest end-to-end BN V5 sur live_enriched.

Charge live_enriched 30j NQ + ES, instancie BN V5, varie range_drift_min_pct
parmi [0.05, 0.08, 0.10, 0.12, 0.15, 0.20], calcule trades + PF + WR + freq.

Simulation entry/exit :
  - Entry : entry_price du Setup
  - SL    : pivot_price (LOW pour LONG, HIGH pour SHORT)
  - TP    : trailing Dow simplifié (3 bars sans new high/low confirme pullback)
  - Timeout : 90 bars
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
LIVE = ROOT / "DATA" / "live_enriched"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))

from CORE.bn_v5_engine import (
    BNV5Params, find_pivots,
    detect_v_long, detect_w_long, detect_inv_v_short, detect_m_short,
    init_trailing, update_trailing,
    TICK_BY_SYMBOL, TICK_VAL_USD_BY_SYMBOL,
    SIDE_LONG, SIDE_SHORT,
)


NEEDED_COLS = [
    "ts_event_iso", "open", "high", "low", "close",
    "delta_bar", "aggressor_imbalance",
    "long_up_bar", "long_dn_bar",
    "dist_blind_nearest_dn_pct", "dist_blind_nearest_up_pct",
    "dist_mq_hvl_pct", "dist_mq_put_pct", "dist_mq_call_pct", "dist_mq_call_0dte_pct",
    "dist_vwap_d_sd1d_pct", "dist_vwap_d_sd1u_pct",
    "dist_gex_nearest_dn_pct", "dist_gex_nearest_up_pct",
    "date_et",
]


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            rows.append({k: rec.get(k) for k in NEEDED_COLS})
    return pd.DataFrame(rows)


def load_symbol(sym: str, n_days: int = 30) -> dict[str, pd.DataFrame]:
    """Retourne dict {date_et: df}."""
    files = sorted((LIVE / sym).glob(f"*_{sym}.jsonl"))[-n_days:]
    out = {}
    for p in files:
        df = load_jsonl(p)
        if df.empty:
            continue
        if "date_et" not in df.columns or df["date_et"].isna().all():
            continue
        date = str(df["date_et"].iloc[len(df)//2])
        out[date] = df.reset_index(drop=True)
    return out


def simulate_setup(df: pd.DataFrame, setup, params: BNV5Params, sym: str) -> dict:
    """Simule entry -> trail -> exit pour 1 setup. Retourne dict de stats."""
    tick = TICK_BY_SYMBOL.get(sym, 0.25)
    tick_val = TICK_VAL_USD_BY_SYMBOL.get(sym, 5.0)

    state = init_trailing(setup)
    n = len(df)
    exit_idx = None
    exit_price = None
    exit_reason = None

    for i in range(setup.entry_idx + 1, min(setup.entry_idx + 1 + params.timeout_bars, n)):
        bar_high = float(df["high"].iloc[i])
        bar_low = float(df["low"].iloc[i])
        bar_close = float(df["close"].iloc[i])

        # Update trailing
        bar = df.iloc[i]
        update_trailing(state, bar, params.trail_pullback_bars)

        # Check SL hit
        if setup.side == SIDE_LONG:
            if bar_low <= state.sl_current:
                exit_idx = i
                exit_price = state.sl_current  # gap-protected? on simplifie au SL
                exit_reason = "SL"
                break
        else:
            if bar_high >= state.sl_current:
                exit_idx = i
                exit_price = state.sl_current
                exit_reason = "SL"
                break

    if exit_idx is None:
        # Timeout : exit at close of last bar
        last_idx = min(setup.entry_idx + params.timeout_bars, n - 1)
        exit_idx = last_idx
        exit_price = float(df["close"].iloc[last_idx])
        exit_reason = "TIMEOUT"

    # PnL
    if setup.side == SIDE_LONG:
        pnl_pts = exit_price - setup.entry_price
    else:
        pnl_pts = setup.entry_price - exit_price
    pnl_ticks = pnl_pts / tick
    pnl_usd = pnl_ticks * tick_val

    return {
        "pattern": setup.pattern,
        "side": setup.side,
        "entry_idx": setup.entry_idx,
        "entry_price": setup.entry_price,
        "sl_initial": setup.sl_price,
        "exit_idx": exit_idx,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_ticks": pnl_ticks,
        "pnl_usd": pnl_usd,
        "bars_held": exit_idx - setup.entry_idx,
    }


def run_backtest_for_threshold(symbol_data: dict[str, pd.DataFrame], sym: str, drift_thr: float,
                                conf_max: float = 0.20) -> dict:
    """Backtest BN V5 sur tous les jours pour 1 seuil drift."""
    params = BNV5Params(
        range_drift_min_pct=drift_thr,
        confluence_max_dist_pct=conf_max,
        enable_v_long=True,
        enable_w_long=True,
        enable_inv_v_short=False,
        enable_m_short=True,
    )

    trades = []
    n_days = 0
    for date, df in symbol_data.items():
        if len(df) < 50:
            continue
        n_days += 1
        pl, ph = find_pivots(df, params.pivot_window)
        setups = []
        if params.enable_v_long:
            setups += detect_v_long(df, pl, sym, params, log_fn=None)
        if params.enable_w_long:
            setups += detect_w_long(df, pl, sym, params, log_fn=None)
        if params.enable_m_short:
            setups += detect_m_short(df, ph, sym, params, log_fn=None)

        # 1 trade max actif a la fois (simplification)
        active_until = -1
        for s in sorted(setups, key=lambda x: x.entry_idx):
            if s.entry_idx <= active_until:
                continue
            res = simulate_setup(df, s, params, sym)
            res["date"] = date
            trades.append(res)
            active_until = res["exit_idx"]

    n_trades = len(trades)
    if n_trades == 0:
        return {
            "drift_thr": drift_thr, "n_days": n_days, "n_trades": 0,
            "trades_per_day": 0, "wr_pct": 0, "pf": 0, "net_usd": 0,
            "avg_usd": 0, "max_win": 0, "max_loss": 0,
        }

    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    gross_win = sum(t["pnl_usd"] for t in wins)
    gross_loss = abs(sum(t["pnl_usd"] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    net = sum(t["pnl_usd"] for t in trades)

    return {
        "drift_thr": drift_thr,
        "n_days": n_days,
        "n_trades": n_trades,
        "trades_per_day": round(n_trades / max(n_days, 1), 2),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "wr_pct": round(100 * len(wins) / n_trades, 2),
        "pf": round(pf, 2) if pf != float("inf") else 999.0,
        "net_usd": round(net, 2),
        "avg_usd": round(net / n_trades, 2),
        "gross_win_usd": round(gross_win, 2),
        "gross_loss_usd": round(gross_loss, 2),
        "max_win": round(max(t["pnl_usd"] for t in trades), 2),
        "max_loss": round(min(t["pnl_usd"] for t in trades), 2),
    }


def main():
    print("=" * 80)
    print("BN V5 THRESHOLD BACKTEST — 30j live_enriched")
    print("=" * 80)

    thresholds = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20]
    all_results = {}

    for sym in ("NQ", "ES"):
        print(f"\n>>> Loading {sym} ...")
        data = load_symbol(sym, n_days=30)
        print(f"   {len(data)} trading days loaded")
        if not data:
            continue

        results = []
        for thr in thresholds:
            r = run_backtest_for_threshold(data, sym, thr)
            results.append(r)
            print(f"   thr={thr:.2f}%  N={r['n_trades']:4d}  /day={r['trades_per_day']:.2f}  "
                  f"WR={r['wr_pct']:5.2f}%  PF={r['pf']:5.2f}  net=${r['net_usd']:+.0f}  "
                  f"avg=${r['avg_usd']:+.1f}")
        all_results[sym] = results

    out = ROOT / "DATA" / "BN_V5_THRESHOLD_BACKTEST.json"
    out.write_text(json.dumps(all_results, indent=2), encoding="utf-8")
    print(f"\nResults : {out}")


if __name__ == "__main__":
    main()
