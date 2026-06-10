"""bot2_ml_long_short_split.py — Verifier symetrie LONG/SHORT du ML directional.

Le baseline ML donne PF 2.12 mais on ne sait pas si l'edge est dans LONG, SHORT,
ou les deux. Important car Jackson veut SHORT (config Bot 2 asymetrique).
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd
import lightgbm as lgb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.research.bot2_ml_directional import (
    FEATURE_CANDIDATES, load_all_nq, label_triple_barrier,
    compute_sample_weights, walk_forward_split,
)


def simulate_long_short_split(df, proba, test_idx, horizon_bars,
                                proba_threshold=0.55, sl_ticks=20, tick_size=0.25):
    closes = df["close"].values
    highs = df["high"].values
    lows = df["low"].values
    long_pnls = []
    short_pnls = []
    for j, i in enumerate(test_idx):
        if i + horizon_bars >= len(df):
            continue
        p = proba[j]
        if p > proba_threshold:
            direction = "long"
        elif p < (1 - proba_threshold):
            direction = "short"
        else:
            continue
        entry = closes[i]
        sl_off = sl_ticks * tick_size
        if direction == "long":
            sl_price = entry - sl_off
        else:
            sl_price = entry + sl_off
        exit_price = None
        for k in range(1, horizon_bars + 1):
            tk = i + k
            if direction == "long":
                if lows[tk] <= sl_price:
                    exit_price = sl_price
                    break
            else:
                if highs[tk] >= sl_price:
                    exit_price = sl_price
                    break
        if exit_price is None:
            exit_price = closes[i + horizon_bars]
        if direction == "long":
            pnl_ticks = (exit_price - entry) / tick_size
            long_pnls.append(pnl_ticks)
        else:
            pnl_ticks = (entry - exit_price) / tick_size
            short_pnls.append(pnl_ticks)
    return long_pnls, short_pnls


def stats_pnls(pnls):
    if not pnls:
        return {"n": 0, "wr": 0, "ev_ticks": 0, "pf": 0, "sum_ticks": 0}
    pnls = np.array(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    sum_w = wins.sum() if len(wins) else 0
    sum_l = -losses.sum() if len(losses) else 1e-9
    return {
        "n": len(pnls),
        "wr": float((pnls > 0).mean() * 100),
        "ev_ticks": float(pnls.mean()),
        "pf": float(sum_w / sum_l) if sum_l > 0 else float("inf"),
        "sum_ticks": float(pnls.sum()),
    }


def main():
    df = load_all_nq()
    features = [c for c in FEATURE_CANDIDATES if c in df.columns]

    horizon = 15
    label_col = f"label_h{horizon}"
    df[label_col] = label_triple_barrier(df, horizon).values

    mask = df[label_col] != 0
    sub = df[mask].copy()
    sub["y"] = (sub[label_col] == 1).astype(int)
    X = sub[features].fillna(0).values.astype(np.float32)
    y = sub["y"].values
    sw = compute_sample_weights(sub[label_col], horizon).values
    splits = walk_forward_split(len(sub), n_folds=12, embargo=60)

    long_results = []
    short_results = []
    threshold = 0.65

    for fold_id, (tr, te) in enumerate(splits):
        if len(tr) < 500 or len(te) < 100:
            continue
        model = lgb.LGBMClassifier(
            n_estimators=200, learning_rate=0.05, num_leaves=31, max_depth=6,
            min_child_samples=20, reg_alpha=0.1, reg_lambda=0.1,
            random_state=42, verbose=-1,
        )
        model.fit(X[tr], y[tr], sample_weight=sw[tr])
        proba = model.predict_proba(X[te])[:, 1]
        global_te = sub.index.values[te]
        long_pnls, short_pnls = simulate_long_short_split(
            df, proba, global_te, horizon, proba_threshold=threshold
        )
        ls = stats_pnls(long_pnls)
        ss = stats_pnls(short_pnls)
        ls["fold"] = fold_id
        ss["fold"] = fold_id
        long_results.append(ls)
        short_results.append(ss)
        print(f"Fold {fold_id}: LONG n={ls['n']:4d} PF={ls['pf']:.2f} EV={ls['ev_ticks']:+.1f}t  "
              f"SHORT n={ss['n']:4d} PF={ss['pf']:.2f} EV={ss['ev_ticks']:+.1f}t")

    def summary(results, name):
        pfs = [m["pf"] for m in results if m["pf"] != float("inf") and m["n"] > 10]
        wrs = [m["wr"] for m in results if m["n"] > 10]
        evs = [m["ev_ticks"] for m in results if m["n"] > 10]
        ntot = sum(m["n"] for m in results)
        print(f"\n{name} (threshold={threshold}):")
        print(f"  n_total: {ntot}")
        print(f"  PF median: {float(np.median(pfs)) if pfs else 0:.2f}")
        print(f"  WR median: {float(np.median(wrs)) if wrs else 0:.1f}%")
        print(f"  EV median: {float(np.median(evs)) if evs else 0:+.2f}t")
        print(f"  Stability PF>=1.3: {sum(1 for p in pfs if p >= 1.3)}/{len(pfs)}")
        return {
            "n_total": ntot,
            "pf_median": float(np.median(pfs)) if pfs else 0,
            "wr_median": float(np.median(wrs)) if wrs else 0,
            "ev_median": float(np.median(evs)) if evs else 0,
            "stability": float(np.mean([p >= 1.3 for p in pfs])) if pfs else 0,
            "pfs": pfs,
        }

    long_s = summary(long_results, "LONG-only")
    short_s = summary(short_results, "SHORT-only")

    out = ROOT / "LOGS/bot2_research/ml_long_short_split.json"
    out.write_text(json.dumps({
        "threshold": threshold,
        "horizon": horizon,
        "long": long_s,
        "short": short_s,
        "long_folds": long_results,
        "short_folds": short_results,
    }, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
