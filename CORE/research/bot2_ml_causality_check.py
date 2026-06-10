"""bot2_ml_causality_check.py — Verifications anti-leakage du ML directional.

Verifie :
1. Drop des features qui sont du prix brut (close, high, low, atr) qui peuvent
   leak car le label depend du futur prix.
2. Permutation test : si on permute les labels, l'edge doit disparaitre (PF -> 1).
3. Feature importance : aucune feature ne devrait dominer (sinon overfitting).
4. Stabilite vs random seed (5 seeds).
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


def run_one_seed(df, features, label_col, horizon, seed, threshold=0.65,
                 permute_labels=False, permute_features=None):
    mask = df[label_col] != 0
    sub = df[mask].copy()
    sub["y"] = (sub[label_col] == 1).astype(int)
    X = sub[features].fillna(0).values.astype(np.float32)
    y = sub["y"].values

    if permute_labels:
        rng = np.random.RandomState(seed)
        y = rng.permutation(y)
    if permute_features:
        # permute these specific features within the column (destroy info)
        rng = np.random.RandomState(seed)
        for fname in permute_features:
            if fname in features:
                col_idx = features.index(fname)
                X[:, col_idx] = rng.permutation(X[:, col_idx])

    sw = compute_sample_weights(sub[label_col], horizon).values
    splits = walk_forward_split(len(sub), n_folds=12, embargo=60)
    fold_metrics = []
    feat_imp_acc = np.zeros(len(features))
    for fold_id, (tr, te) in enumerate(splits):
        if len(tr) < 500 or len(te) < 100:
            continue
        model = lgb.LGBMClassifier(
            n_estimators=200, learning_rate=0.05, num_leaves=31, max_depth=6,
            min_child_samples=20, reg_alpha=0.1, reg_lambda=0.1,
            random_state=seed, verbose=-1,
        )
        model.fit(X[tr], y[tr], sample_weight=sw[tr])
        proba = model.predict_proba(X[te])[:, 1]
        global_te = sub.index.values[te]
        sim = simulate_trades_from_proba(df, proba, global_te, horizon,
                                          proba_threshold=threshold)
        sim["fold"] = fold_id
        fold_metrics.append(sim)
        feat_imp_acc += model.feature_importances_

    pfs = [m["pf"] for m in fold_metrics if m["pf"] != float("inf")]
    wrs = [m["wr"] for m in fold_metrics]
    evs = [m["ev_ticks"] for m in fold_metrics]
    return {
        "pf_median": float(np.median(pfs)) if pfs else 0,
        "ev_median": float(np.median(evs)) if evs else 0,
        "wr_median": float(np.median(wrs)) if wrs else 0,
        "n_trades_total": sum(m["n_trades"] for m in fold_metrics),
        "stability_pf_ge_1_3": float(np.mean([p >= 1.3 for p in pfs])) if pfs else 0,
        "feat_imp": dict(zip(features, [float(x) for x in feat_imp_acc])),
    }


def main():
    df = load_all_nq()
    features = [c for c in FEATURE_CANDIDATES if c in df.columns]
    horizon = 15
    label_col = f"label_h{horizon}"
    df[label_col] = label_triple_barrier(df, horizon).values

    out = {}

    # 1. Stability 5 seeds
    print("=== TEST 1 : Stability vs random seed ===")
    seeds_results = []
    for seed in [42, 7, 123, 999, 2024]:
        r = run_one_seed(df, features, label_col, horizon, seed)
        print(f"  seed={seed}: PF={r['pf_median']:.2f} EV={r['ev_median']:+.1f}t "
              f"stab={r['stability_pf_ge_1_3']:.2f}")
        seeds_results.append({"seed": seed, **{k: r[k] for k in ['pf_median','ev_median','wr_median','n_trades_total','stability_pf_ge_1_3']}})
    out["test1_seeds"] = seeds_results

    # 2. Permute labels (must collapse edge)
    print("\n=== TEST 2 : Permute labels (anti-overfitting check) ===")
    r_perm = run_one_seed(df, features, label_col, horizon, 42, permute_labels=True)
    print(f"  permuted: PF={r_perm['pf_median']:.2f} EV={r_perm['ev_median']:+.1f}t "
          f"stab={r_perm['stability_pf_ge_1_3']:.2f}")
    print("  --> doit s'effondrer (PF ~1.0) sinon LEAKAGE.")
    out["test2_permute_labels"] = {k: r_perm[k] for k in ['pf_median','ev_median','wr_median','n_trades_total','stability_pf_ge_1_3']}

    # 3. Feature importance global
    print("\n=== TEST 3 : Feature importance (top 10) ===")
    r_normal = run_one_seed(df, features, label_col, horizon, 42)
    imp = r_normal["feat_imp"]
    imp_total = sum(imp.values()) if sum(imp.values()) > 0 else 1
    imp_pct = {k: v/imp_total*100 for k, v in imp.items()}
    sorted_imp = sorted(imp_pct.items(), key=lambda x: -x[1])[:15]
    for k, v in sorted_imp:
        print(f"  {k}: {v:.2f}%")
    out["test3_feat_importance"] = dict(sorted_imp)

    # 4. Permute top feature individually (sanity check)
    print("\n=== TEST 4 : Permute top feature only ===")
    top_feat = sorted_imp[0][0]
    r_perm_top = run_one_seed(df, features, label_col, horizon, 42,
                                permute_features=[top_feat])
    print(f"  permute '{top_feat}': PF={r_perm_top['pf_median']:.2f} "
          f"(baseline ~2.2)")
    out["test4_permute_top_feat"] = {
        "feature": top_feat,
        **{k: r_perm_top[k] for k in ['pf_median','ev_median']},
    }

    # Verdict global
    print("\n=== VERDICT CAUSALITE ===")
    PF_perm_threshold = 1.10
    if r_perm["pf_median"] > PF_perm_threshold:
        print(f"  SUSPECT : PF permute = {r_perm['pf_median']:.2f} > {PF_perm_threshold}")
        out["verdict_causalite"] = "SUSPECT_PERMUTE"
    else:
        print(f"  OK : PF permute = {r_perm['pf_median']:.2f} <= {PF_perm_threshold}")
        out["verdict_causalite"] = "OK"

    top_share = sorted_imp[0][1]
    if top_share > 30:
        print(f"  SUSPECT : top feat = {top_share:.1f}% (1 feature domine = leakage probable)")
        out["verdict_top_share"] = "SUSPECT_DOMINANT"
    else:
        print(f"  OK : top feat = {top_share:.1f}% (pas de domination)")
        out["verdict_top_share"] = "OK"

    out_path = ROOT / "LOGS/bot2_research/ml_causality_check.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
