"""
mega_battery_phase2_shap.py — Phase 2 SHAP analysis sur ML v5.

Objectif : extraire les conditions exactes que LightGBM ES BUY v5 (PF 1.11) a
apprises. Reverse-engineer les arbres en règles humaines lisibles.

Ordre Mega Battery (validation Plan agent 27/04 19:50) :
  Phase 2 SHAP (ICI)        — prior fort gratuit, 15 min
  Phase 1 Winner Cluster    — clusters sur features SHAP top 30, OOS 18/6m
  Phase 3 Aronson Universe  — 1500 règles bornées par features SHAP top 30
  Phase 4 Davey Stress      — top 10 stratégies survivantes
  Phase 5 CPCV Lopez        — N=50 paths sur top 5

Output : DOCS/MEGA_BATTERY_PHASE2_SHAP.md + features_shap_top30.json (input pour Phase 1+3)

Auteur : MIA Trading System V2
Date   : 2026-04-27 20:30
"""
from __future__ import annotations

import sys
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))


def main():
    print("=" * 70)
    print("MEGA BATTERY — Phase 2 SHAP Analysis sur ML v5 ES BUY")
    print("=" * 70)

    # 1. Charger modèle + features
    model_path = ROOT / "DATA/MODELS/ES_buy_model.pkl"
    importance_path = ROOT / "DATA/MODELS/ES_buy_importance.csv"
    if not model_path.exists():
        print(f"[ERROR] Model absent : {model_path}")
        return

    with open(model_path, "rb") as f:
        model = pickle.load(f)
    print(f"  [1/5] Model loaded : {type(model).__name__}")

    importance = pd.read_csv(importance_path)
    print(f"        Features : {len(importance)}")
    print(f"        Top 5 par MDI : {importance.nlargest(5, 'mdi')['feature'].tolist()}")

    # 2. Charger dataset v5 (sample pour SHAP, 50K bars)
    print("\n  [2/5] Loading dataset v5 (sample 50K bars pour SHAP)...")
    df = pd.read_parquet(ROOT / "DATA/datasets/ES_dataset_v5b.parquet")
    print(f"        Total {len(df):,} bars, sampling 50K...")
    rng = np.random.RandomState(42)
    sample_idx = rng.choice(len(df), size=min(50000, len(df)), replace=False)
    sample_idx.sort()
    df_sample = df.iloc[sample_idx].reset_index(drop=True)

    # Features attendues du modèle
    features = importance["feature"].tolist()
    missing = [f for f in features if f not in df_sample.columns]
    if missing:
        print(f"        [WARN] {len(missing)} features manquantes : {missing[:5]}")
        features = [f for f in features if f in df_sample.columns]

    X_sample = df_sample[features]
    print(f"        Features used : {len(features)}")

    # 3. SHAP TreeExplainer
    print("\n  [3/5] Computing SHAP values (TreeExplainer)...")
    try:
        import shap
    except ImportError:
        print("[ERROR] shap module non installe. Pip install shap.")
        return

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)

    # Pour binary : shap_values peut être [class_0, class_1] ou juste class_1
    if isinstance(shap_values, list) and len(shap_values) == 2:
        shap_pos = shap_values[1]
    else:
        shap_pos = shap_values
    print(f"        SHAP shape : {shap_pos.shape}")

    # 4. Top features par |SHAP| moyen
    print("\n  [4/5] Top features par importance SHAP...")
    mean_abs_shap = np.abs(shap_pos).mean(axis=0)
    shap_importance = pd.DataFrame({
        "feature": features,
        "mean_abs_shap": mean_abs_shap,
    }).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    print(f"\n  TOP 30 features par SHAP :")
    print(shap_importance.head(30).to_string(index=False))

    # 5. Conditions par feature (pour reverse-engineer règles)
    print("\n  [5/5] Conditions par feature (top 15) — distribution SHAP par range...")
    rules = []
    top_15 = shap_importance.head(15)["feature"].tolist()

    for feat in top_15:
        feat_idx = features.index(feat)
        feat_values = X_sample[feat].values
        feat_shap = shap_pos[:, feat_idx]

        # Quantile-based bucketing : voir où SHAP est positif (BUY) vs négatif
        try:
            # Garder seulement les valeurs finies
            mask = np.isfinite(feat_values)
            fv = feat_values[mask]
            fs = feat_shap[mask]
            if len(fv) < 100:
                continue

            # Bucket par décile
            quantiles = np.quantile(fv, [0.1, 0.25, 0.5, 0.75, 0.9])
            buckets = []
            for q_lo, q_hi in [
                (-np.inf, quantiles[0]),
                (quantiles[0], quantiles[1]),
                (quantiles[1], quantiles[2]),
                (quantiles[2], quantiles[3]),
                (quantiles[3], quantiles[4]),
                (quantiles[4], np.inf),
            ]:
                bm = (fv > q_lo) & (fv <= q_hi)
                if bm.sum() < 50:
                    continue
                mean_shap_bucket = fs[bm].mean()
                buckets.append({
                    "range": f"({q_lo:.4f}, {q_hi:.4f}]",
                    "n": int(bm.sum()),
                    "mean_shap": float(mean_shap_bucket),
                })
            # Direction du gradient SHAP
            best_bucket = max(buckets, key=lambda b: b["mean_shap"])
            worst_bucket = min(buckets, key=lambda b: b["mean_shap"])
            rules.append({
                "feature": feat,
                "shap_importance": float(shap_importance.iloc[shap_importance["feature"].tolist().index(feat)]["mean_abs_shap"]),
                "best_buy_range": best_bucket["range"],
                "best_buy_mean_shap": best_bucket["mean_shap"],
                "worst_buy_range": worst_bucket["range"],
                "worst_buy_mean_shap": worst_bucket["mean_shap"],
                "all_buckets": buckets,
            })
            direction = "↑" if best_bucket["mean_shap"] > 0 and abs(best_bucket["mean_shap"]) > abs(worst_bucket["mean_shap"]) else "↓"
            print(f"    {feat:<35s} {direction}  best_buy_range={best_bucket['range']:<30s} mean_shap={best_bucket['mean_shap']:+.4f}")
        except Exception as e:
            print(f"    [{feat}] error: {type(e).__name__}: {e}")

    # ─── SAVE outputs ────────────────────────────────────────────────────
    out_dir = ROOT / "DOCS"
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON top 30 features pour Phase 1+3
    features_top30 = shap_importance.head(30).to_dict(orient="records")
    with open(out_dir / "features_shap_top30.json", "w", encoding="utf-8") as f:
        json.dump({
            "model": "ES_buy_v5",
            "n_samples": len(X_sample),
            "n_features_total": len(features),
            "top30": features_top30,
            "rules_top15": rules,
        }, f, indent=2)
    print(f"\n  [SAVED] {out_dir / 'features_shap_top30.json'}")

    # Markdown report
    md_path = out_dir / "MEGA_BATTERY_PHASE2_SHAP.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Mega Battery Phase 2 — SHAP Analysis ML v5 ES BUY\n\n")
        f.write(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Model** : ES_buy_model.pkl (LightGBM v5, PF 1.11, Sharpe 0.84)\n")
        f.write(f"**Sample** : {len(X_sample):,} bars (random 50K du dataset v5 351K)\n")
        f.write(f"**Features analysées** : {len(features)}\n\n")

        f.write("## Pourquoi SHAP ?\n\n")
        f.write("Le ML LightGBM ES BUY v5 a appris quelque chose (PF 1.11 vs 1.0 random).\n")
        f.write("SHAP (Lundberg & Lee 2017) extrait les conditions exactes des arbres.\n")
        f.write("Output : règles humaines reproduisant l'edge ML (= prior pour Phase 1+3).\n\n")

        f.write("## TOP 30 features par |SHAP| moyen\n\n")
        f.write(shap_importance.head(30).to_string(index=False))
        f.write("\n\n## TOP 15 — direction du gradient SHAP par feature\n\n")
        f.write("Lecture : `best_buy_range` = range de la feature où le SHAP est le plus POSITIF (= modèle prédit BUY le plus fort)\n\n")
        f.write("| Feature | SHAP imp | Best BUY range | mean_shap best | Worst BUY range | mean_shap worst |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in rules:
            f.write(f"| {r['feature']} | {r['shap_importance']:.4f} | "
                    f"`{r['best_buy_range']}` | {r['best_buy_mean_shap']:+.4f} | "
                    f"`{r['worst_buy_range']}` | {r['worst_buy_mean_shap']:+.4f} |\n")

        f.write("\n## Règles candidates pour Phase 1+3\n\n")
        f.write("Les buckets `best_buy_range` constituent un prior trader : ces ranges sont les plus prédictifs.\n")
        f.write("Phase 1 (Winner Cluster) restreindra les features de clustering aux top 30 ci-dessus.\n")
        f.write("Phase 3 (Aronson Universe) bornera les 1500 règles random à combinaisons de top 30 features.\n")

    print(f"  [SAVED] {md_path}")
    print(f"\n  Top 30 features pretes pour Phase 1+3 (mega_battery)")


if __name__ == "__main__":
    main()
