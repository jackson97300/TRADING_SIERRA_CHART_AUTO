"""bot2_ml_proper_baseline.py — Tests anti-leakage corrects.

Verifie :
1. PF baseline RANDOM proba (uniforme [0,1]) avec meme threshold 0.65 : doit etre ~1
2. PF baseline meme modele mais sur OOS chronologique severement (pas anti-leakage)
3. PF avec proba threshold tres haut : doit reduire trade count mais garder PF

Le vrai test : si je remplace `proba` par random uniforme, PF doit s'effondrer.
"""
from __future__ import annotations

import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
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

    print("=== TEST 1 : Modele vrai (baseline) ===")
    folds_true = []
    folds_random = []
    folds_const = []
    for fold_id, (tr, te) in enumerate(splits):
        if len(tr) < 500 or len(te) < 100:
            continue
        model = lgb.LGBMClassifier(
            n_estimators=200, learning_rate=0.05, num_leaves=31, max_depth=6,
            min_child_samples=20, reg_alpha=0.1, reg_lambda=0.1,
            random_state=42, verbose=-1,
        )
        model.fit(X[tr], y[tr], sample_weight=sw[tr])
        proba_true = model.predict_proba(X[te])[:, 1]

        rng = np.random.RandomState(fold_id)
        proba_random = rng.uniform(0, 1, len(te))

        # Proba constante = mean(y_train) -> tous trades meme cote
        mean_train = y[tr].mean()
        proba_const = np.full(len(te), mean_train)

        global_te = sub.index.values[te]
        sim_true = simulate_trades_from_proba(df, proba_true, global_te, horizon, 0.65)
        sim_random = simulate_trades_from_proba(df, proba_random, global_te, horizon, 0.65)
        sim_const = simulate_trades_from_proba(df, proba_const, global_te, horizon, 0.65)

        folds_true.append(sim_true)
        folds_random.append(sim_random)
        folds_const.append(sim_const)
        print(f"Fold {fold_id}: "
              f"TRUE  n={sim_true['n_trades']:5d} PF={sim_true['pf']:.2f} EV={sim_true['ev_ticks']:+.1f}t | "
              f"RANDOM n={sim_random['n_trades']:5d} PF={sim_random['pf']:.2f} EV={sim_random['ev_ticks']:+.1f}t | "
              f"CONST n={sim_const['n_trades']:5d} PF={sim_const['pf']:.2f} EV={sim_const['ev_ticks']:+.1f}t")

    def stats(folds):
        pfs = [m["pf"] for m in folds if m["pf"] != float("inf")]
        evs = [m["ev_ticks"] for m in folds]
        wrs = [m["wr"] for m in folds]
        ntot = sum(m["n_trades"] for m in folds)
        return {
            "pf_median": float(np.median(pfs)) if pfs else 0,
            "ev_median": float(np.median(evs)),
            "wr_median": float(np.median(wrs)),
            "n_trades_total": ntot,
            "stability_pf_ge_1_3": float(np.mean([p >= 1.3 for p in pfs])) if pfs else 0,
        }

    s_true = stats(folds_true)
    s_random = stats(folds_random)
    s_const = stats(folds_const)

    print("\n=== SUMMARY ===")
    for name, s in [("TRUE", s_true), ("RANDOM", s_random), ("CONST", s_const)]:
        print(f"  {name}: PF={s['pf_median']:.2f} EV={s['ev_median']:+.1f}t "
              f"WR={s['wr_median']:.1f}% n_trades={s['n_trades_total']} "
              f"stab={s['stability_pf_ge_1_3']:.2f}")

    edge_pf = s_true["pf_median"] - s_random["pf_median"]
    edge_ev = s_true["ev_median"] - s_random["ev_median"]
    print(f"\n  EDGE TRUE vs RANDOM: PF={edge_pf:+.2f} EV={edge_ev:+.1f}t")
    if edge_pf > 0.5 and edge_ev > 5:
        verdict = "EDGE_REEL"
    elif edge_pf > 0.2 and edge_ev > 2:
        verdict = "EDGE_FAIBLE"
    else:
        verdict = "PAS_EDGE"
    print(f"  VERDICT: {verdict}")

    out = ROOT / "LOGS/bot2_research/ml_proper_baseline.json"
    out.write_text(json.dumps({
        "true": s_true,
        "random_uniform": s_random,
        "constant_mean": s_const,
        "edge_pf": float(edge_pf),
        "edge_ev_ticks": float(edge_ev),
        "verdict": verdict,
    }, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
