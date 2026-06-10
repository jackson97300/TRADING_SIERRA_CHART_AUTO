"""bn_v5_walkforward.py — Stabilite seuil drift sur 2 fenetres 30j.

Compare W1 (Avril 09 -> 30) vs W2 (Mai 15 -> 29) pour eviter
data mining trap (cf rule data-mining + memoire feedback_data_mining_trap).

Si PF s'effondre sur W2 (ES last 5d max=0.57%) avec le meme seuil,
le finding n'est pas stable.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
LIVE = ROOT / "DATA" / "live_enriched"
sys.path.insert(0, str(ROOT))

from CORE.bn_v5_engine import (
    BNV5Params, find_pivots,
    detect_v_long, detect_w_long, detect_m_short,
)
from CORE.research.bn_v5_threshold_backtest import load_jsonl, simulate_setup


def load_window(sym: str, date_min: str, date_max: str) -> dict:
    files = sorted((LIVE / sym).glob(f"*_{sym}.jsonl"))
    out = {}
    for p in files:
        d = p.stem.split("_")[0]  # YYYYMMDD
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        if not (date_min <= iso <= date_max):
            continue
        df = load_jsonl(p)
        if df.empty: continue
        out[iso] = df.reset_index(drop=True)
    return out


def run(data, sym, drift_thr, conf_max=0.20):
    params = BNV5Params(
        range_drift_min_pct=drift_thr,
        confluence_max_dist_pct=conf_max,
        require_aggressor_confirm=False,
        require_long_bar_confirm=False,
        enable_v_long=True, enable_w_long=True, enable_m_short=True,
        enable_inv_v_short=False,
    )
    trades = []
    n_days = 0
    for date, df in data.items():
        if len(df) < 50: continue
        n_days += 1
        pl, ph = find_pivots(df, params.pivot_window)
        setups = []
        setups += detect_v_long(df, pl, sym, params, log_fn=None)
        setups += detect_w_long(df, pl, sym, params, log_fn=None)
        setups += detect_m_short(df, ph, sym, params, log_fn=None)
        active_until = -1
        for s in sorted(setups, key=lambda x: x.entry_idx):
            if s.entry_idx <= active_until: continue
            r = simulate_setup(df, s, params, sym)
            r["date"] = date
            trades.append(r)
            active_until = r["exit_idx"]
    n = len(trades)
    if n == 0:
        return {"n_trades": 0, "n_days": n_days, "pf": 0, "wr": 0, "net": 0, "tpd": 0}
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    gw = sum(t["pnl_usd"] for t in wins)
    gl = abs(sum(t["pnl_usd"] for t in losses))
    pf = gw/gl if gl > 0 else 999.0
    net = sum(t["pnl_usd"] for t in trades)
    return {"n_trades": n, "n_days": n_days, "pf": round(pf,2), "wr": round(100*len(wins)/n,1),
            "net": round(net,0), "tpd": round(n/max(n_days,1), 2)}


def main():
    WINDOWS = [
        ("W1_avril",   "2026-04-07", "2026-04-30"),
        ("W2_mai",     "2026-05-15", "2026-05-29"),
    ]
    THRS_NQ = [0.05, 0.08, 0.10]
    THRS_ES = [0.08, 0.10, 0.12]

    for sym, thrs in (("NQ", THRS_NQ), ("ES", THRS_ES)):
        print(f"\n{'='*70}\n  {sym} walk-forward\n{'='*70}")
        for win_name, dmin, dmax in WINDOWS:
            data = load_window(sym, dmin, dmax)
            print(f"  [{win_name}] {dmin} -> {dmax}  ({len(data)} days)")
            for thr in thrs:
                r = run(data, sym, thr)
                print(f"     thr={thr:.2f}%  N={r['n_trades']:3d}  /d={r['tpd']:5.2f}  "
                      f"WR={r['wr']:5.1f}%  PF={r['pf']:5.2f}  net=${r['net']:+.0f}")


if __name__ == "__main__":
    main()
