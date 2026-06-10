"""
Croise les 18 trades 24/04 avec les top features ML identifiees par le training POC.

Top features (training_report.txt 25/04 03:30) :
- momentum_3b (apparait dans 3 modeles)
- ctx_range_vs_atr_10 (apparait dans 3 modeles)
- ctx_price_slope_5
- ctx_vol_sell_buy_ratio_5
- volume_imbalance
- ctx_dist_vwap_velocity
- ctx_poc_migration_10

Charge NQ_dataset_v2.parquet (bars labellisees avec ctx_*) et merge avec les 18 trades.
Output : distribution des features par outcome (wins vs losses).
"""
import json
import pandas as pd
import numpy as np
from statistics import median, mean

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"
TRADES_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_trades.jsonl"
SNAPS_F = f"{ROOT}/DATA/PAPER_TRADES/20260424_snapshots.jsonl"
NQ_DS = f"{ROOT}/DATA/DATASETS/NQ_dataset_v2.parquet"

TOP_FEATURES = [
    "momentum_3b", "momentum_5b",
    "ctx_range_vs_atr_10",
    "ctx_price_slope_5",
    "ctx_vol_sell_buy_ratio_5",
    "volume_imbalance",
    "ctx_dist_vwap_velocity",
    "ctx_poc_migration_10",
]


def main():
    trades = [json.loads(l) for l in open(TRADES_F, encoding="utf-8")]
    snaps = [json.loads(l) for l in open(SNAPS_F, encoding="utf-8")]
    snap_by_id = {s["trade_id"]: s for s in snaps}

    print(f"Loading NQ dataset v2...")
    df = pd.read_parquet(NQ_DS)
    print(f"  Rows: {len(df)}, Columns: {len(df.columns)}")
    avail = [f for f in TOP_FEATURES if f in df.columns]
    print(f"  Available top features in dataset : {avail}")
    missing = [f for f in TOP_FEATURES if f not in df.columns]
    if missing:
        print(f"  Missing : {missing}")
    print()

    # Identify ts column
    ts_col = None
    for c in ("ts", "ts_ms", "timestamp"):
        if c in df.columns:
            ts_col = c
            break
    if not ts_col:
        print("Error: no ts column in dataset")
        print("Cols sample:", list(df.columns)[:20])
        return
    print(f"Using ts column: {ts_col}")
    print()

    # Match trades to dataset rows by entry_ts
    rows = []
    for t in trades:
        s = snap_by_id.get(t["trade_id"], {})
        entry_ts_ms = s.get("dmp_bar", {}).get("ts")
        if not entry_ts_ms:
            continue
        # Find row in dataset matching this ts
        # Match exact (tolerance +/- 60s = 1 bar). Pas de fallback nearest car
        # dataset NQ_v2 filtre Asia (start ~7h UTC) → trades Asia auraient match
        # absurde sur 1ere bar London → biais d'analyse.
        row_match = df[(df[ts_col] >= entry_ts_ms - 60_000) & (df[ts_col] <= entry_ts_ms + 60_000)]
        if row_match.empty:
            continue  # trade hors dataset (Asia trades exclus)
        r = row_match.iloc[0]
        record = {
            "trade_id": t["trade_id"],
            "time": t["entry_time"][11:19],
            "dir": t["direction"],
            "outcome": t["outcome"],
            "pnl": t["pnl_ticks"],
            "mae": t["mae"],
            "mfe": t["mfe"],
        }
        for f in avail:
            v = r.get(f)
            if pd.isna(v):
                v = None
            else:
                v = float(v)
            record[f] = v
        rows.append(record)

    print(f"Matched {len(rows)}/{len(trades)} trades with dataset rows")
    print()

    # Display table
    print("=" * 130)
    print("18 TRADES x TOP FEATURES ML")
    print("=" * 130)
    cols_show = ["time", "dir", "outcome", "pnl"] + avail
    print(" | ".join(c[:18].ljust(18) for c in cols_show))
    print("-" * 130)
    for r in rows:
        line = []
        for c in cols_show:
            v = r.get(c, "")
            if c == "pnl":
                s = f"{v:+5.0f}t"
            elif isinstance(v, float):
                s = f"{v:+8.3f}"
            elif v is None:
                s = "  N/A"
            else:
                s = str(v)
            line.append(s[:18].ljust(18))
        print(" | ".join(line))
    print()

    # Wins vs Losses by feature
    wins = [r for r in rows if r["pnl"] > 0]
    losses = [r for r in rows if r["pnl"] <= 0]
    print(f"Wins: {len(wins)}  |  Losses: {len(losses)}")
    print()

    print("=" * 100)
    print("DISTRIBUTION FEATURES par OUTCOME (wins vs losses)")
    print("=" * 100)
    print(f"{'feature':<30}{'wins median':<14}{'losses median':<14}{'gap':<10}{'interpretation':<25}")
    print("-" * 100)
    for f in avail:
        w_vals = [r[f] for r in wins if r.get(f) is not None]
        l_vals = [r[f] for r in losses if r.get(f) is not None]
        if not w_vals or not l_vals:
            continue
        wm, lm = median(w_vals), median(l_vals)
        gap = wm - lm
        flag = ""
        denom = max(abs(wm), abs(lm), 0.01)
        if abs(gap) >= 0.3 * denom:
            flag = " <-- DIFF"
        print(f"{f:<30}{wm:<+14.3f}{lm:<+14.3f}{gap:<+10.3f}{flag}")

    # Bucket analysis on features showing gap
    print()
    print("=" * 100)
    print("REGLES CANDIDATES (extension de l'analyse precedente avec features ML)")
    print("=" * 100)
    print(f"{'regle':<55}{'n':<5}{'wins':<6}{'losses':<7}{'pnl':<8}{'WR':<6}")
    print("-" * 90)
    candidates = []
    for f in avail:
        w_vals = [r[f] for r in wins if r.get(f) is not None]
        l_vals = [r[f] for r in losses if r.get(f) is not None]
        if not w_vals or not l_vals: continue
        wm = median(w_vals)
        lm = median(l_vals)
        gap = wm - lm
        if abs(gap) < 0.3 * max(abs(wm), abs(lm), 0.01):
            continue
        # Threshold = milieu wins/losses
        thr = (wm + lm) / 2
        if gap > 0:
            candidates.append((f"{f} > {thr:+.3f} (wins typical)", lambda r, f=f, t=thr: r.get(f) is not None and r.get(f) > t))
            candidates.append((f"{f} <= {thr:+.3f} (losses typical)", lambda r, f=f, t=thr: r.get(f) is not None and r.get(f) <= t))
        else:
            candidates.append((f"{f} < {thr:+.3f} (wins typical)", lambda r, f=f, t=thr: r.get(f) is not None and r.get(f) < t))
            candidates.append((f"{f} >= {thr:+.3f} (losses typical)", lambda r, f=f, t=thr: r.get(f) is not None and r.get(f) >= t))

    for name, fn in candidates:
        match = [r for r in rows if fn(r)]
        if not match: continue
        w = sum(1 for r in match if r["pnl"] > 0)
        l = len(match) - w
        pnl = sum(r["pnl"] for r in match)
        wr = w / len(match) * 100
        flag = ""
        if len(match) >= 4:
            if wr >= 75: flag = " EDGE++"
            elif wr <= 25: flag = " WARNING"
            elif wr >= 65: flag = " edge"
            elif wr <= 35: flag = " warning"
        print(f"{name:<55}{len(match):<5}{w:<6}{l:<7}{pnl:+5.0f}t  {wr:.0f}%{flag}")

    print()
    print("=" * 100)
    print("CAVEAT : N=18 trades = MICRO-ECHANTILLON. Patterns = HYPOTHESES, pas verites.")


if __name__ == "__main__":
    main()
