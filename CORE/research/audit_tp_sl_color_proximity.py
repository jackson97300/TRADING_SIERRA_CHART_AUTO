"""
audit_tp_sl_color_proximity.py — Audit empirique TP/SL ratios pour rules
color_proximity (Phase 1.6 GO_RIGOROUS).

CONTEXTE Jackson 06/05 : "TP TROP ELOIGNER, AUDIT SUR LE TP SL"

Approche : pour chaque fire des 3 rules GO_RIGOROUS, compute path-aware via
high/low forward 60 bars :
  - Distance forward au plus haut (high_max[t+1:t+60] - close[t])
  - Distance forward au plus bas (close[t] - low_min[t+1:t+60])
  - Pour chaque candidat R:R {1.0, 1.5, 2.0, 2.5, 3.0} :
    - Calculer TP/SL ticks selon ratio
    - Tester si TP touche avant SL (path-aware via high/low offset_first_touch)
    - Outcome : TP / SL / TIMEOUT
  - Compute mean_pnl, WR, Sharpe pour chaque ratio

Output : meilleure R:R par rule × instrument × direction.

Run : python -X utf8 CORE/research/audit_tp_sl_color_proximity.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
sys.path.insert(0, str(ROOT))
DATASETS_DIR = ROOT / "DATA" / "DATASETS"

from CORE.signal_engine_rules.rules import RULES_V1

# ─── Config audit ────────────────────────────────────────────────────────
HORIZON_BARS = 60   # = label v5 horizon
SLIPPAGE_TICKS = 2.0
TICK_SIZE = 0.25

# Ratios R:R a tester (TP_ratio = R:R × SL_ratio)
RR_CANDIDATES = [1.0, 1.5, 2.0, 2.5, 3.0]
SL_TICKS_BASE = {"ES": 32, "NQ": 80}  # de bot3_config.py

# 4 directions audit elargi (Jackson 06/05 : "TP SL RAISONNABLE POUR TOUT BOT 3")
# Les 3 GO_RIGOROUS + ES BUY (proxy color_up_proximity_ES) pour completer la matrice.
# Les rules color_proximity sont representatives des setups proximity-based Bot 3
# (la majorite des 13 niveaux MP : MQ_*, GEX_*, VWAP_*, BL_*, CUR_VAH/VAL).
SETUPS = [
    {"sym": "ES", "rule": "color_up_proximity", "direction": "BUY",  "dir_value":  1},
    {"sym": "ES", "rule": "color_dn_proximity", "direction": "SELL", "dir_value": -1},
    {"sym": "NQ", "rule": "color_up_proximity", "direction": "BUY",  "dir_value":  1},
    {"sym": "NQ", "rule": "color_dn_proximity", "direction": "SELL", "dir_value": -1},
]


def load_dataset(symbol):
    fp_clean = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    df = pd.read_parquet(fp_clean)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def apply_rule(df, rule_name):
    fn = RULES_V1[rule_name]
    records = df.to_dict("records")
    dirs = np.zeros(len(records), dtype=np.int8)
    for i, features in enumerate(records):
        try:
            tag = fn(features)
            dirs[i] = tag.direction
        except Exception:
            pass
    return dirs


def compute_path_outcomes(df, fires_idx, dir_value, sl_ticks, tp_ticks):
    """Pour chaque fire bar, simule trade avec sl_ticks/tp_ticks.

    Path-aware : scan bars i+1..i+HORIZON, identifier first touch SL/TP via high/low.

    Returns dict avec outcomes counts + pnl array.
    """
    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values

    sl_pts = sl_ticks * TICK_SIZE
    tp_pts = tp_ticks * TICK_SIZE

    n_tp = 0
    n_sl = 0
    n_timeout = 0
    pnl_ticks_list = []
    duration_bars_list = []

    for i in fires_idx:
        if i + HORIZON_BARS >= n:
            continue
        entry = close[i]
        if dir_value == 1:  # LONG
            tp_target = entry + tp_pts
            sl_target = entry - sl_pts
        else:  # SHORT
            tp_target = entry - tp_pts
            sl_target = entry + sl_pts

        outcome = "TIMEOUT"
        offset = HORIZON_BARS
        for k in range(1, HORIZON_BARS + 1):
            h = high[i + k]
            l = low[i + k]
            if dir_value == 1:  # LONG : SL bas, TP haut
                if l <= sl_target:
                    outcome = "SL"
                    offset = k
                    break
                if h >= tp_target:
                    outcome = "TP"
                    offset = k
                    break
            else:  # SHORT : SL haut, TP bas
                if h >= sl_target:
                    outcome = "SL"
                    offset = k
                    break
                if l <= tp_target:
                    outcome = "TP"
                    offset = k
                    break

        if outcome == "TP":
            n_tp += 1
            pnl_ticks_list.append(tp_ticks - SLIPPAGE_TICKS)
        elif outcome == "SL":
            n_sl += 1
            pnl_ticks_list.append(-sl_ticks - SLIPPAGE_TICKS)
        else:
            n_timeout += 1
            # Timeout : pnl = close[t+H] - close[t] signed
            timeout_pnl_pts = (close[i + HORIZON_BARS] - entry) * dir_value
            timeout_pnl_ticks = timeout_pnl_pts / TICK_SIZE - SLIPPAGE_TICKS
            pnl_ticks_list.append(timeout_pnl_ticks)
        duration_bars_list.append(offset)

    pnl_arr = np.array(pnl_ticks_list)
    n_total = len(pnl_arr)
    if n_total == 0:
        return None

    return {
        "n_total": n_total,
        "n_tp": n_tp,
        "n_sl": n_sl,
        "n_timeout": n_timeout,
        "pct_tp": n_tp / n_total,
        "pct_sl": n_sl / n_total,
        "pct_timeout": n_timeout / n_total,
        "mean_pnl_ticks": float(pnl_arr.mean()),
        "median_pnl_ticks": float(np.median(pnl_arr)),
        "wr": float((pnl_arr > 0).mean()),
        "sharpe": float(pnl_arr.mean() / (pnl_arr.std() + 1e-9)),
        "total_pnl_ticks": float(pnl_arr.sum()),
        "mean_duration_bars": float(np.mean(duration_bars_list)),
        "median_duration_bars": float(np.median(duration_bars_list)),
    }


def run_setup(setup, df):
    sym = setup["sym"]
    rule = setup["rule"]
    direction = setup["direction"]
    dir_value = setup["dir_value"]
    sl_ticks = SL_TICKS_BASE[sym]

    print(f"\n{'='*100}")
    print(f"  SETUP : {sym} {rule} {direction} (SL_base={sl_ticks}t)")
    print(f"{'='*100}")

    # Apply rule
    print(f"  Apply {rule}...")
    t0 = time.time()
    dirs = apply_rule(df, rule)
    print(f"  Done in {time.time()-t0:.1f}s")

    fires_idx = np.where(dirs == dir_value)[0]
    print(f"  Fires {direction} : {len(fires_idx)}")

    if len(fires_idx) < 30:
        print(f"  SKIP (n<30)")
        return None

    # Test chaque R:R candidat
    print(f"\n  Test R:R candidats (SL fixe={sl_ticks}t):")
    print(f"  R:R   | TP    | n_TP   | n_SL   | n_TO   | %TP  | %SL  | %TO  | WR    | Mean PnL | Sharpe | Total PnL | Avg dur (bars)")
    results = []
    for rr in RR_CANDIDATES:
        tp_ticks = int(round(sl_ticks * rr))
        out = compute_path_outcomes(df, fires_idx, dir_value, sl_ticks, tp_ticks)
        if out is None:
            continue
        out["rr"] = rr
        out["sl_ticks"] = sl_ticks
        out["tp_ticks"] = tp_ticks
        results.append(out)
        print(f"  {rr:4.1f}  | {tp_ticks:3d}t  | {out['n_tp']:>4d}   | {out['n_sl']:>4d}   | {out['n_timeout']:>4d}   | "
              f"{out['pct_tp']*100:4.0f}% | {out['pct_sl']*100:4.0f}% | {out['pct_timeout']*100:4.0f}% | "
              f"{out['wr']*100:4.1f}% | {out['mean_pnl_ticks']:+7.2f}t  | {out['sharpe']:+.3f} | "
              f"{out['total_pnl_ticks']:+8.0f}t  | {out['mean_duration_bars']:>4.1f}")

    # Best R:R par mean_pnl
    if results:
        best = max(results, key=lambda r: r["mean_pnl_ticks"])
        print(f"\n  BEST R:R : {best['rr']:.1f} (TP={best['tp_ticks']}t)  mean_pnl={best['mean_pnl_ticks']:+.2f}t  "
              f"%TIMEOUT={best['pct_timeout']*100:.0f}%")
    return {"setup": setup, "results": results}


def main():
    print("=" * 100)
    print("  AUDIT TP/SL ratios pour 3 rules color_proximity GO_RIGOROUS")
    print("  Path-aware via high/low forward 60 bars (label v5 horizon)")
    print("=" * 100)

    es_df = load_dataset("ES")
    nq_df = load_dataset("NQ")

    all_results = {}
    for setup in SETUPS:
        df = es_df if setup["sym"] == "ES" else nq_df
        r = run_setup(setup, df)
        if r is not None:
            key = f"{setup['sym']}_{setup['rule']}_{setup['direction']}"
            all_results[key] = r

    # Synthese
    print(f"\n{'='*100}")
    print(f"  SYNTHESE : Best R:R par setup")
    print(f"{'='*100}")
    print(f"  Setup                              | Best R:R | TP ticks | %TIMEOUT | Mean PnL | Total PnL")
    for key, r in all_results.items():
        if not r["results"]:
            continue
        best = max(r["results"], key=lambda x: x["mean_pnl_ticks"])
        print(f"  {key:36s} | {best['rr']:.1f}      | {best['tp_ticks']:>4d}t    | {best['pct_timeout']*100:>4.0f}%    | "
              f"{best['mean_pnl_ticks']:+7.2f}t | {best['total_pnl_ticks']:+8.0f}t")

    # Compare R:R 1.5 (deploy actuel) vs best
    print(f"\n  Compare R:R 1.5 (deploy actuel) vs Best :")
    print(f"  Setup                              | Current 1.5 mean_pnl | Best mean_pnl | Delta | %TIMEOUT 1.5 | Best R:R")
    for key, r in all_results.items():
        if not r["results"]:
            continue
        rr_15 = next((x for x in r["results"] if x["rr"] == 1.5), None)
        best = max(r["results"], key=lambda x: x["mean_pnl_ticks"])
        if rr_15:
            delta = best["mean_pnl_ticks"] - rr_15["mean_pnl_ticks"]
            print(f"  {key:36s} | {rr_15['mean_pnl_ticks']:+7.2f}t          | {best['mean_pnl_ticks']:+7.2f}t   | "
                  f"{delta:+5.2f}t | {rr_15['pct_timeout']*100:>4.0f}%       | {best['rr']:.1f}")

    # Save
    out = ROOT / "DATA" / f"audit_tp_sl_color_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json"
    payload = {key: {"setup": r["setup"], "results": r["results"]} for key, r in all_results.items()}
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report : {out}")


if __name__ == "__main__":
    main()
