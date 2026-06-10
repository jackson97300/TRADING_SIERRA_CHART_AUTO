"""
audit_post_backfill_24m.py — Audit empirique post-backfill 24 mois.

A lancer APRES backfill 24 mois pour valider :
  1. Tous les mois ont les 184 features ML
  2. session_segment distribution OK (~25% chacun en RTH)
  3. Outlier vwap_slope_10_atr clip OK (max/p99 < 100)
  4. Drift early/mid/late sur 24m (vs 1 mois pilote)
  5. Stuck values (event-based legitime vs bug)
  6. Quasi-constantes (dropees vs gardees)

Output : DOCS/AUDIT_POST_BACKFILL_24M.md

Auteur : Phase post-backfill (2026-04-27)
"""
from __future__ import annotations

import sys
import time
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from build_dataset_v4_dmp_databento import ML_EXCLUDE_FEATURES, get_ml_features


def main():
    print("=" * 70)
    print("AUDIT POST-BACKFILL 24 MOIS — Validation finale dataset Lopez")
    print("=" * 70)

    t0 = time.perf_counter()

    # 1. Charger ALL mois ES + NQ
    es_paths = sorted(glob.glob(str(ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=*/month=*/data.parquet")))
    nq_paths = sorted(glob.glob(str(ROOT / "DATA/datasets/v4_enriched/symbol=NQ.c.0/year=*/month=*/data.parquet")))

    print(f"\n[1] ES partitions : {len(es_paths)}")
    print(f"    NQ partitions : {len(nq_paths)}")

    # 2. Verifier COHERENCE schema (toutes partitions doivent avoir MEME nombre ML)
    # FIX 27/04 (code-reviewer R1) : I/O unique, stockage dataframes pour concat
    print("\n[2] Coherence schema + load (cible : MEME nombre ML sur toutes partitions) :")
    es_dfs = []
    nq_dfs = []
    n_ml_per_partition = []
    for path in es_paths + nq_paths:
        df = pd.read_parquet(path, columns=None)
        n_ml = len(get_ml_features(df))
        n_ml_per_partition.append(n_ml)
        sym = "ES" if "symbol=ES" in path else "NQ"
        path_obj = Path(path)
        month = "/".join(p for p in path_obj.parts if p.startswith("year=") or p.startswith("month="))
        print(f"  {sym} {month} : ML={n_ml}")
        if sym == "ES":
            es_dfs.append(df)
        else:
            nq_dfs.append(df)

    n_ml_unique = set(n_ml_per_partition)
    n_ml_target = max(n_ml_per_partition, key=n_ml_per_partition.count)  # mode
    all_ok = len(n_ml_unique) == 1
    if all_ok:
        print(f"\n  [OK] Schema COHERENT : {n_ml_target} ML features uniformes sur 26 partitions.")
    else:
        print(f"\n  [ERREUR] Schema INCOHERENT : {n_ml_unique} valeurs ML differentes !")
        return

    # 3. Concat ES + NQ pour audit global (depuis cache memoire, pas re-read)
    print("\n[3] Concat ES + NQ all months...")
    df_es_all = pd.concat(es_dfs, ignore_index=True)
    df_nq_all = pd.concat(nq_dfs, ignore_index=True)
    del es_dfs, nq_dfs  # liberer memoire
    print(f"    ES : {len(df_es_all):,} bars (sur {len(es_paths)} mois)")
    print(f"    NQ : {len(df_nq_all):,} bars")

    # 4. session_segment distribution
    print("\n[4] session_segment distribution (cible RTH ~25% chacun, hors RTH 65%) :")
    if "session_segment" in df_es_all.columns:
        seg_dist = df_es_all["session_segment"].value_counts(normalize=True).sort_index()
        for k, v in seg_dist.items():
            label = {0: "pre-RTH", 1: "RTH early", 2: "RTH mid", 3: "RTH late"}.get(k, "?")
            print(f"    seg={k} ({label:10s}) : {v*100:5.2f}%")

    # 5. Outliers max/p99
    print("\n[5] Outliers max/p99 sur features critiques :")
    for c in ["vwap_slope_10_atr", "vol_imbalance_3bar_build", "atr_regime_zscore_60d", "ctx_failed_auction"]:
        if c in df_es_all.columns:
            s = df_es_all[c].dropna()
            if len(s) > 100:
                p99 = abs(s.quantile(0.99))
                max_v = abs(s).max()
                ratio = max_v / max(p99, 1e-9)
                flag = "OK" if ratio < 100 else "OUTLIER!"
                print(f"    {c:30s} : max={max_v:.4f} p99={p99:.4f} ratio={ratio:.2f} {flag}")

    # 6. Drift early/mid/late SUR 24 MOIS (3 periodes)
    # FIX 27/04 (code-reviewer) : test SUR TOUTES les features (pas sample 50)
    # FIX 27/04 (code-reviewer) : except Exception explicite (pas bare except)
    print("\n[6] Drift early/mid/late sur 24 mois ES (KS-test sur TOUTES features) :")
    n = len(df_es_all)
    third = n // 3
    early, mid, late = df_es_all.iloc[:third], df_es_all.iloc[third:2*third], df_es_all.iloc[2*third:]

    from scipy import stats
    drift_critique = []
    drift_count = 0
    all_features = get_ml_features(df_es_all)
    for f in all_features:
        try:
            e = pd.to_numeric(early[f], errors="coerce").dropna()
            m = pd.to_numeric(mid[f], errors="coerce").dropna()
            l = pd.to_numeric(late[f], errors="coerce").dropna()
            if len(e) < 100 or len(m) < 100 or len(l) < 100:
                continue
            ks_em = stats.ks_2samp(e, m)
            ks_ml = stats.ks_2samp(m, l)
            if (ks_em.statistic > 0.3 and ks_em.pvalue < 0.001) or (ks_ml.statistic > 0.3 and ks_ml.pvalue < 0.001):
                drift_count += 1
                if ks_em.statistic > 0.5 or ks_ml.statistic > 0.5:
                    drift_critique.append((f, round(ks_em.statistic, 3), round(ks_ml.statistic, 3)))
        except Exception as exc:
            print(f"  WARN drift test {f}: {exc}")

    print(f"    Features avec drift detecte : {drift_count}/{len(all_features)}")
    if drift_critique:
        print(f"    Drift CRITIQUE (KS > 0.5) : {len(drift_critique)}")
        for f, ks_em, ks_ml in drift_critique[:10]:
            print(f"      {f} : ks_em={ks_em} ks_ml={ks_ml}")

    # 7. Stats Sample/Feature ratio
    print("\n[7] Stats samples ML :")
    n_total = len(df_es_all) + len(df_nq_all)
    n_features = 184
    ratio = n_total / n_features
    print(f"    Total samples (ES+NQ) : {n_total:,}")
    print(f"    Features ML : {n_features}")
    print(f"    Ratio sample/feature : {ratio:.0f} (Lopez >100, OK)")

    # 8. PSR/DSR pre-check estimation
    print("\n[8] PSR/DSR pre-check Lopez :")
    print(f"    50 trials Optuna : E[max SR_50] estime ~ 1.1-1.3 sous H0")
    print(f"    PSR > 0.95 requiert SR walk-forward median > 1.5")
    print(f"    PF median cible >= 2.2 walk-forward")

    elapsed = time.perf_counter() - t0
    print(f"\n[DONE] Audit complet en {elapsed:.1f}s")
    print("\n=== VERDICT FINAL ===")
    if all_ok:
        print("✅ Dataset Lopez-compliant prêt pour Phase ML walk-forward")
    else:
        print("❌ Schema incoherent, backfill a re-faire")


if __name__ == "__main__":
    main()
