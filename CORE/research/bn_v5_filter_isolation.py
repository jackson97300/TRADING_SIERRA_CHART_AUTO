"""bn_v5_filter_isolation.py — Isole l'impact de chaque filtre BN V5.

Configs testees (cumulatif, on retire 1 filtre a chaque step):
  A. FULL (defaults backtest valide 02/06)
  B. A sans require_long_bar_confirm
  C. B sans require_aggressor_confirm
  D. C avec range 0.10%
  E. D avec range 0.05%
  F. E avec confluence 0.50% (relâche confluence)
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
    init_trailing, update_trailing,
    TICK_BY_SYMBOL, TICK_VAL_USD_BY_SYMBOL, SIDE_LONG,
)
from CORE.research.bn_v5_threshold_backtest import load_symbol, simulate_setup


def run(symbol_data, sym, params: BNV5Params, label: str) -> dict:
    trades = []
    n_days = 0
    for date, df in symbol_data.items():
        if len(df) < 50: continue
        n_days += 1
        pl, ph = find_pivots(df, params.pivot_window)
        setups = []
        if params.enable_v_long:
            setups += detect_v_long(df, pl, sym, params, log_fn=None)
        if params.enable_w_long:
            setups += detect_w_long(df, pl, sym, params, log_fn=None)
        if params.enable_m_short:
            setups += detect_m_short(df, ph, sym, params, log_fn=None)
        active_until = -1
        for s in sorted(setups, key=lambda x: x.entry_idx):
            if s.entry_idx <= active_until: continue
            res = simulate_setup(df, s, params, sym)
            res["date"] = date
            trades.append(res)
            active_until = res["exit_idx"]

    n = len(trades)
    if n == 0:
        return {"label": label, "n_days": n_days, "n_trades": 0, "trades_per_day": 0,
                "wr_pct": 0, "pf": 0, "net_usd": 0, "avg_usd": 0,
                "max_win": 0, "max_loss": 0}
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    gw = sum(t["pnl_usd"] for t in wins)
    gl = abs(sum(t["pnl_usd"] for t in losses))
    pf = gw/gl if gl > 0 else 999.0
    net = sum(t["pnl_usd"] for t in trades)
    return {
        "label": label, "n_days": n_days, "n_trades": n,
        "trades_per_day": round(n/max(n_days,1), 2),
        "wr_pct": round(100*len(wins)/n, 2),
        "pf": round(pf, 2),
        "net_usd": round(net, 2),
        "avg_usd": round(net/n, 2),
        "max_win": round(max(t["pnl_usd"] for t in trades), 2),
        "max_loss": round(min(t["pnl_usd"] for t in trades), 2),
    }


CONFIGS = [
    ("A_FULL_default_0.20",  dict(range_drift_min_pct=0.20, confluence_max_dist_pct=0.20,
                                   require_aggressor_confirm=True, require_long_bar_confirm=True)),
    ("B_no_long_bar_0.20",   dict(range_drift_min_pct=0.20, confluence_max_dist_pct=0.20,
                                   require_aggressor_confirm=True, require_long_bar_confirm=False)),
    ("C_no_aggressor_0.20",  dict(range_drift_min_pct=0.20, confluence_max_dist_pct=0.20,
                                   require_aggressor_confirm=False, require_long_bar_confirm=False)),
    ("D_no_aggressor_0.10",  dict(range_drift_min_pct=0.10, confluence_max_dist_pct=0.20,
                                   require_aggressor_confirm=False, require_long_bar_confirm=False)),
    ("E_no_aggressor_0.05",  dict(range_drift_min_pct=0.05, confluence_max_dist_pct=0.20,
                                   require_aggressor_confirm=False, require_long_bar_confirm=False)),
    ("F_no_aggr_0.10_conf0.50", dict(range_drift_min_pct=0.10, confluence_max_dist_pct=0.50,
                                   require_aggressor_confirm=False, require_long_bar_confirm=False)),
    ("G_no_aggr_0.08_conf0.30", dict(range_drift_min_pct=0.08, confluence_max_dist_pct=0.30,
                                   require_aggressor_confirm=False, require_long_bar_confirm=False)),
]


def main():
    out = {}
    for sym in ("NQ", "ES"):
        print(f"\n{'='*70}\n  {sym}\n{'='*70}")
        data = load_symbol(sym, n_days=30)
        if not data: continue
        out[sym] = []
        for label, kw in CONFIGS:
            params = BNV5Params(
                enable_v_long=True, enable_w_long=True, enable_m_short=True,
                enable_inv_v_short=False, **kw,
            )
            r = run(data, sym, params, label)
            out[sym].append(r)
            print(f"  {r['label']:30s}  N={r['n_trades']:4d}  /d={r.get('trades_per_day',0):5.2f}  "
                  f"WR={r['wr_pct']:5.2f}%  PF={r['pf']:5.2f}  net=${r['net_usd']:+8.0f}  "
                  f"avg=${r['avg_usd']:+6.1f}  max+/-={r.get('max_win',0):+.0f}/{r.get('max_loss',0):+.0f}")
    (ROOT/"DATA"/"BN_V5_FILTER_ISOLATION.json").write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
