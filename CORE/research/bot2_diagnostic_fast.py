"""bot2_diagnostic_fast.py — Diagnostic accelere (echantillonage / mai seul).

Approche : utiliser df complet sans rolling window (engine.detect_setup
appele avec i sur df global). Plus rapide car evite copie/reset.
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bn_v4_engine import BNV4Engine, BNV4Params


def simulate_trade(df, entry_idx, direction, sl_ticks=20, rr=2.0,
                    trailing_be_R=1.0, timeout_bars=90, tick_size=0.25):
    entry_price = df.iloc[entry_idx]["close"]
    sl_offset = sl_ticks * tick_size
    if direction == "long":
        sl = entry_price - sl_offset
        tp = entry_price + sl_offset * rr
        be_trigger = entry_price + sl_offset * trailing_be_R
    else:
        sl = entry_price + sl_offset
        tp = entry_price - sl_offset * rr
        be_trigger = entry_price - sl_offset * trailing_be_R

    be_active = False
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values

    for j in range(entry_idx + 1, min(entry_idx + 1 + timeout_bars, len(df))):
        h, l = highs[j], lows[j]
        if direction == "long":
            if not be_active and h >= be_trigger:
                sl = entry_price
                be_active = True
            if l <= sl:
                pnl_ticks = (sl - entry_price) / tick_size
                return {"exit_cause": "be" if be_active else "sl",
                        "pnl_R": pnl_ticks / sl_ticks, "pnl_ticks": pnl_ticks,
                        "duration_bars": j - entry_idx}
            if h >= tp:
                pnl_ticks = (tp - entry_price) / tick_size
                return {"exit_cause": "tp",
                        "pnl_R": pnl_ticks / sl_ticks, "pnl_ticks": pnl_ticks,
                        "duration_bars": j - entry_idx}
        else:
            if not be_active and l <= be_trigger:
                sl = entry_price
                be_active = True
            if h >= sl:
                pnl_ticks = (entry_price - sl) / tick_size
                return {"exit_cause": "be" if be_active else "sl",
                        "pnl_R": pnl_ticks / sl_ticks, "pnl_ticks": pnl_ticks,
                        "duration_bars": j - entry_idx}
            if l <= tp:
                pnl_ticks = (entry_price - tp) / tick_size
                return {"exit_cause": "tp",
                        "pnl_R": pnl_ticks / sl_ticks, "pnl_ticks": pnl_ticks,
                        "duration_bars": j - entry_idx}
    last_idx = min(entry_idx + timeout_bars, len(df) - 1)
    pnl_ticks = ((closes[last_idx] - entry_price) if direction == "long"
                 else (entry_price - closes[last_idx])) / tick_size
    return {"exit_cause": "timeout", "pnl_R": pnl_ticks / sl_ticks,
            "pnl_ticks": pnl_ticks, "duration_bars": timeout_bars}


def main():
    print("Loading parquets...")
    base = ROOT / "DATA/datasets/v4_enriched/symbol=NQ.c.0"
    parts = []
    for ydir in sorted(base.iterdir()):
        for mdir in sorted(ydir.iterdir()):
            pq = mdir / "data.parquet"
            if pq.exists():
                parts.append(pd.read_parquet(pq))
    df = pd.concat(parts, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
    print(f"Total: {len(df)} bars")

    configs = {
        "A++_strict": BNV4Params(grade_min="A++", require_open_window=True,
                                  require_long_trend_aligned=True),
        "A_observe": BNV4Params(grade_min="A", require_open_window=True,
                                 require_long_trend_aligned=True),
        "A_no_window": BNV4Params(grade_min="A", require_open_window=False,
                                   require_long_trend_aligned=False),
        "B_loose": BNV4Params(grade_min="B", require_open_window=False,
                               require_long_trend_aligned=False),
    }

    results = {}
    for name, params in configs.items():
        print(f"\n=== Config {name} ===")
        engine = BNV4Engine(params)
        n_short = 0
        n_long = 0
        trades = []
        min_i = max(params.trend_long_lookback + 10, 250)
        # echantillonage : 1 bar sur 1 sinon trop lent ? On essaye full speed
        for i in range(min_i, len(df) - 100):
            try:
                s = engine.detect_setup(df, i, "short")
                if s is not None:
                    n_short += 1
                    sim = simulate_trade(df, i, "short")
                    sim["direction"] = "short"
                    sim["grade"] = s.get("grade", "?")
                    sim["density"] = s.get("density", 0)
                    sim["ts_event"] = df.iloc[i]["ts_event"]
                    trades.append(sim)
            except Exception:
                pass
            try:
                s = engine.detect_setup(df, i, "long")
                if s is not None:
                    n_long += 1
                    sim = simulate_trade(df, i, "long")
                    sim["direction"] = "long"
                    sim["grade"] = s.get("grade", "?")
                    sim["density"] = s.get("density", 0)
                    sim["ts_event"] = df.iloc[i]["ts_event"]
                    trades.append(sim)
            except Exception:
                pass

        if not trades:
            print(f"  0 setups")
            results[name] = {"n_short": 0, "n_long": 0, "n_trades": 0}
            continue
        pnls = [t["pnl_R"] for t in trades]
        wins = [t for t in trades if t["pnl_R"] > 0]
        losses = [t for t in trades if t["pnl_R"] <= 0]
        sum_w = sum(t["pnl_R"] for t in wins)
        sum_l = -sum(t["pnl_R"] for t in losses) if losses else 1e-9
        pf = sum_w / sum_l if sum_l > 0 else float("inf")
        wr = len(wins) / len(trades) * 100
        ev_R = np.mean(pnls)
        results[name] = {
            "n_short": n_short, "n_long": n_long, "n_trades": len(trades),
            "wr": float(wr), "ev_R": float(ev_R),
            "ev_ticks": float(ev_R * 20), "pf": float(pf),
            "sum_R": float(sum(pnls)),
        }
        # Stats SHORT vs LONG separes
        ts = [t for t in trades if t["direction"] == "short"]
        tl = [t for t in trades if t["direction"] == "long"]
        ts_pf = (sum(t["pnl_R"] for t in ts if t["pnl_R"] > 0) /
                 max(-sum(t["pnl_R"] for t in ts if t["pnl_R"] <= 0), 1e-9))
        tl_pf = (sum(t["pnl_R"] for t in tl if t["pnl_R"] > 0) /
                 max(-sum(t["pnl_R"] for t in tl if t["pnl_R"] <= 0), 1e-9))
        results[name]["short_n"] = len(ts)
        results[name]["short_pf"] = float(ts_pf) if len(ts) > 0 else 0
        results[name]["short_ev_R"] = float(np.mean([t["pnl_R"] for t in ts])) if ts else 0
        results[name]["long_n"] = len(tl)
        results[name]["long_pf"] = float(tl_pf) if len(tl) > 0 else 0
        results[name]["long_ev_R"] = float(np.mean([t["pnl_R"] for t in tl])) if tl else 0
        print(f"  setups SHORT={n_short} LONG={n_long}")
        print(f"  trades={len(trades)} WR={wr:.1f}% EV={ev_R:+.2f}R PF={pf:.2f}")
        print(f"  SHORT: n={len(ts)} PF={ts_pf:.2f} EV={results[name]['short_ev_R']:+.2f}R")
        print(f"  LONG:  n={len(tl)} PF={tl_pf:.2f} EV={results[name]['long_ev_R']:+.2f}R")

    out = ROOT / "LOGS/bot2_research/diagnostic_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved: {out}")
    return results


if __name__ == "__main__":
    main()
