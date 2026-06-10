"""bot2_ml_threshold_sweep.py — Sweep proba threshold pour reduire les trades.

Le ML H15 baseline genere 3000+ trades/fold = trop. Veut tester si filtre
plus strict (threshold 0.60, 0.65, 0.70) ameliore EV/trade et reduit nombre.
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
    compute_sample_weights, walk_forward_split, simulate_trades_from_proba,
)


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

    THRESHOLDS = [0.55, 0.60, 0.65, 0.70]
    results = {f"th_{t:.2f}": [] for t in THRESHOLDS}

    print(f"NQ samples binary: {len(sub)} folds: {len(splits)}")
    for fold_id, (tr, te) in enumerate(splits):
        if len(tr) < 500 or len(te) < 100:
            continue
        model = lgb.LGBMClassifier(
            n_estimators=200, learning_rate=0.05, num_leaves=31,
            max_depth=6, min_child_samples=20,
            reg_alpha=0.1, reg_lambda=0.1, random_state=42, verbose=-1,
        )
        model.fit(X[tr], y[tr], sample_weight=sw[tr])
        proba = model.predict_proba(X[te])[:, 1]
        global_te = sub.index.values[te]

        for t in THRESHOLDS:
            sim = simulate_trades_from_proba(df, proba, global_te, horizon,
                                              proba_threshold=t, sl_ticks=20)
            sim["fold"] = fold_id
            results[f"th_{t:.2f}"].append(sim)
        print(f"Fold {fold_id}: " + " | ".join(
            [f"th{t}: n={sim['n_trades']} PF={sim['pf']:.2f}"
             for t, sim in zip(THRESHOLDS, [results[f'th_{t:.2f}'][-1] for t in THRESHOLDS])]
        ))

    summary = {}
    for k, folds in results.items():
        pfs = [m["pf"] for m in folds if m["pf"] != float("inf")]
        wrs = [m["wr"] for m in folds]
        evs = [m["ev_ticks"] for m in folds]
        ntr = [m["n_trades"] for m in folds]
        summary[k] = {
            "n_folds": len(folds),
            "n_trades_total": int(sum(ntr)),
            "n_trades_per_fold_median": float(np.median(ntr)),
            "pf_median": float(np.median(pfs)) if pfs else 0,
            "wr_median": float(np.median(wrs)),
            "ev_median_ticks": float(np.median(evs)),
            "stability_pf_above_1_3": float(np.mean([p >= 1.3 for p in pfs])),
        }
        s = summary[k]
        print(f"\n{k}:")
        for kk, vv in s.items():
            print(f"  {kk}: {vv}")

    out = ROOT / "LOGS/bot2_research/ml_threshold_sweep.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
