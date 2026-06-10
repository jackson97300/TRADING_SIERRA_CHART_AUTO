"""
audit_clustering_spearman.py — FIX 2 audit ml-trainer (27/04).

Clustering hierarchique Spearman pour identifier doublons ML SUR 24 MOIS.
Pour chaque paire |rho|>0.95, garder le representant avec :
  - Plus de variance (std brut)
  - Moins de NaN

Output : DOCS/CLUSTERING_SPEARMAN_FINAL.md + liste DROP additionnels

FIX 27/04 (code-reviewer review) :
  - Bug critique : chargeait 1 mois (avril 2026), maintenant charge 24 mois
  - Bug critique : std_norm = CV explosait sur features centrees (mean~0)
  - Symetrie matrice forcee avant squareform
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from build_dataset_v4_dmp_databento import ML_EXCLUDE_FEATURES, get_ml_features


def main():
    print("=" * 70)
    print("CLUSTERING SPEARMAN — 24 MOIS ES + NQ")
    print("=" * 70)

    # FIX BUG CRITIQUE #1 (code-reviewer) : charger 24 mois ES + NQ, pas 1 mois
    es_paths = sorted(glob.glob(str(ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=*/month=*/data.parquet")))
    nq_paths = sorted(glob.glob(str(ROOT / "DATA/datasets/v4_enriched/symbol=NQ.c.0/year=*/month=*/data.parquet")))
    print(f"\n[0] Loading {len(es_paths)} ES + {len(nq_paths)} NQ partitions...")

    if not es_paths or not nq_paths:
        print("  [ERREUR] Aucune partition trouvee. Run backfill d'abord.")
        return

    df_list = []
    for p in es_paths + nq_paths:
        df_list.append(pd.read_parquet(p))
    df = pd.concat(df_list, ignore_index=True)
    print(f"    Total : {len(df):,} bars (ES+NQ 24m)")

    ml_features = sorted(get_ml_features(df))
    print(f"\n[1] ML features : {len(ml_features)}")

    # Garder seulement features avec >100 valid + non-constantes
    df_ml = df[ml_features].apply(pd.to_numeric, errors="coerce")
    keep = []
    for f in ml_features:
        s = df_ml[f]
        if s.notna().sum() > 100 and s.std() > 1e-9:
            keep.append(f)
    df_ml = df_ml[keep]
    print(f"[2] Features non-constantes : {len(keep)}")

    # Compute Spearman correlation matrix
    print("[3] Compute matrice Spearman...")
    corr = df_ml.corr(method="spearman")
    n = len(corr)

    # FIX 27/04 : threshold 0.95 (au lieu de 0.85) - conservateur trading
    # Le 0.85 dropait pVWAP/pdh/poc_position qui sont des concepts distincts
    # malgre forte correlation sur 1 mois. Sur 24m ils diverge.
    THRESHOLD_CORR = 0.95

    # Identifier paires |rho| > THRESHOLD
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            c = corr.iloc[i, j]
            if not pd.isna(c) and abs(c) > THRESHOLD_CORR:
                pairs.append((corr.columns[i], corr.columns[j], round(c, 3)))
    print(f"[4] Pairs |rho|>{THRESHOLD_CORR} : {len(pairs)}")

    # Clustering hierarchique : convertir corr -> distance
    # FIX BUG CRITIQUE #2 (code-reviewer) : symetrie + NaN handling
    corr_arr = corr.values.copy()
    corr_arr[np.isnan(corr_arr)] = 0  # NaN -> distance max
    dist = 1 - np.abs(corr_arr)
    # Forcer symetrie (micro-asymetries flottantes)
    dist = (dist + dist.T) / 2
    np.fill_diagonal(dist, 0)
    # squareform veut distance condensee symetrique
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method="average")
    # Cluster avec threshold conservateur
    clusters = fcluster(Z, t=1 - THRESHOLD_CORR, criterion="distance")

    # Pour chaque cluster avec >= 2 features, choisir le representant (plus de variance)
    cluster_to_features = {}
    for feat, cid in zip(corr.columns, clusters):
        cluster_to_features.setdefault(cid, []).append(feat)

    drop_features = set()
    keep_features = set()
    for cid, feats in cluster_to_features.items():
        if len(feats) == 1:
            keep_features.add(feats[0])
            continue
        # Multi-feature cluster : garder celle avec plus de std (variance ML signal)
        # FIX BUG CRITIQUE #3 (code-reviewer) : CV explose pour mean~0 (delta, slope)
        # On utilise std brut + n_valid pour scoring
        scores = {}
        for f in feats:
            s = df_ml[f]
            std_raw = s.std()  # brut, pas normalise (evite CV explosion)
            n_valid = s.notna().sum()
            scores[f] = (n_valid, std_raw)
        # Tri : plus de valid, puis plus de std absolue
        sorted_feats = sorted(feats, key=lambda f: (scores[f][0], scores[f][1]), reverse=True)
        keep_features.add(sorted_feats[0])
        for f in sorted_feats[1:]:
            drop_features.add(f)

    print(f"\n[5] Clusters identifies : {len(cluster_to_features)}")
    print(f"    Clusters multi-feature : {sum(1 for v in cluster_to_features.values() if len(v) > 1)}")
    print(f"    Features KEEP (representants) : {len(keep_features)}")
    print(f"    Features DROP (redondants) : {len(drop_features)}")

    # Output detail
    out_path = ROOT / "DOCS" / "CLUSTERING_SPEARMAN_FINAL.md"
    lines = [
        "# Clustering Spearman FINAL — Option C+ post fixes (27/04/2026)",
        "",
        f"**Features ML in** : {len(ml_features)}",
        f"**Features non-constantes** : {len(keep)}",
        f"**Pairs |rho|>{THRESHOLD_CORR}** : {len(pairs)}",
        f"**Features KEEP** : {len(keep_features)}",
        f"**Features DROP** : {len(drop_features)}",
        f"**Total ML apres clustering** : {len(keep_features)} (+ {len(ml_features) - len(keep)} constantes/NaN)",
        "",
        "---",
        "",
        "## DROP recommandes (a ajouter ML_EXCLUDE_FEATURES)",
        "",
    ]
    for f in sorted(drop_features):
        # Trouver son cluster
        cid = clusters[list(corr.columns).index(f)]
        cluster_members = cluster_to_features[cid]
        rep = [m for m in cluster_members if m in keep_features][0]
        lines.append(f"- `{f}` (cluster {cid}, kept = `{rep}`)")

    lines.extend(["", "## Clusters multi-feature detail", ""])
    for cid, feats in sorted(cluster_to_features.items()):
        if len(feats) <= 1:
            continue
        rep = [m for m in feats if m in keep_features][0]
        others = [m for m in feats if m != rep]
        lines.append(f"### Cluster {cid} : keep `{rep}`, drop {others}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OUTPUT] Rapport : {out_path}")
    print(f"\nDROP additionnel recommande : {len(drop_features)} features")
    print("Liste pour ML_EXCLUDE_FEATURES (copier-coller) :")
    print()
    drop_str = ",\n    ".join(f'"{f}"' for f in sorted(drop_features))
    print(f"    {drop_str},")


if __name__ == "__main__":
    main()
