"""
audit_nan_temporal_drift.py — Detection features avec NaN drift temporel > 20%.

Mandate ml-trainer 28/04 : LightGBM peut creer split is_nan(MQ) = proxy
"post-2026-04" date = leak temporel deguise (SHAP ne le verra pas comme leaky).

Logique :
  1. Charge dataset v5d
  2. Split sur date_median
  3. Pour chaque feature, calcule NaN% sur (avant) vs (apres)
  4. Si delta > 20% → feature avec drift NaN temporel = leak temporel risque

Output : DOCS/AUDIT_NAN_TEMPORAL_DRIFT.md + liste features a drop/impute

Auteur : MIA Trading System V2
Date   : 2026-04-28 00:00 (Sprint 1 pre-Optuna)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

DRIFT_THRESHOLD_PCT = 20.0  # delta NaN% avant/apres date_median


def audit_symbol(symbol: str) -> dict:
    print(f"\n{'='*70}")
    print(f"  AUDIT NaN TEMPORAL DRIFT — {symbol}")
    print(f"{'='*70}")
    df = pd.read_parquet(ROOT / f"DATA/datasets/{symbol}_dataset_v5d.parquet")
    print(f"  Loaded {len(df):,} bars × {df.shape[1]} cols")

    # Split sur date_median (preserve tz UTC)
    ts_sorted = df["ts_event"].sort_values().reset_index(drop=True)
    median_idx = len(ts_sorted) // 2
    date_median = ts_sorted.iloc[median_idx]
    print(f"  Date median split : {date_median}")

    df_before = df[df["ts_event"] < date_median]
    df_after = df[df["ts_event"] >= date_median]
    print(f"  Before : {len(df_before):,} bars")
    print(f"  After  : {len(df_after):,} bars")

    # ML features (post-exclude)
    from build_dataset_v4_dmp_databento import get_ml_features
    ml_feats = get_ml_features(df)
    print(f"  ML features : {len(ml_feats)}")

    # Audit drift NaN par feature
    drift_results = []
    for feat in ml_feats:
        if feat not in df.columns:
            continue
        if df[feat].dtype == "object":
            continue
        nan_before = df_before[feat].isna().mean() * 100
        nan_after = df_after[feat].isna().mean() * 100
        delta = abs(nan_before - nan_after)
        drift_results.append({
            "feature": feat,
            "nan_before_pct": round(nan_before, 2),
            "nan_after_pct": round(nan_after, 2),
            "delta_pct": round(delta, 2),
        })

    df_drift = pd.DataFrame(drift_results)
    df_drift = df_drift.sort_values("delta_pct", ascending=False)

    # Classification
    high_drift = df_drift[df_drift["delta_pct"] > DRIFT_THRESHOLD_PCT]
    print(f"\n  Features avec drift NaN > {DRIFT_THRESHOLD_PCT}% : {len(high_drift)}")
    if len(high_drift) > 0:
        print(high_drift.head(20).to_string(index=False))

    return {
        "symbol": symbol,
        "n_features": len(ml_feats),
        "n_high_drift": len(high_drift),
        "high_drift_features": high_drift["feature"].tolist(),
        "all_results": df_drift,
    }


def main():
    print("=" * 70)
    print("AUDIT NaN TEMPORAL DRIFT — pre-Optuna validation")
    print("=" * 70)
    print(f"  Threshold : delta NaN% > {DRIFT_THRESHOLD_PCT}% before/after date median")

    all_results = {}
    for sym in ["ES", "NQ"]:
        all_results[sym] = audit_symbol(sym)

    # Union des features high-drift sur ES + NQ
    es_drift = set(all_results["ES"]["high_drift_features"])
    nq_drift = set(all_results["NQ"]["high_drift_features"])
    union = es_drift | nq_drift
    intersection = es_drift & nq_drift

    print("\n" + "=" * 70)
    print("RECAP")
    print("=" * 70)
    print(f"  ES high-drift features  : {len(es_drift)}")
    print(f"  NQ high-drift features  : {len(nq_drift)}")
    print(f"  Union (any symbol)      : {len(union)}")
    print(f"  Intersection (both)     : {len(intersection)}")

    # Save MD report
    out_path = ROOT / "DOCS" / "AUDIT_NAN_TEMPORAL_DRIFT.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Audit NaN Temporal Drift — pre-Optuna validation\n\n")
        f.write(f"**Date** : {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Threshold** : delta NaN % > {DRIFT_THRESHOLD_PCT}% before/after date median\n\n")
        f.write(f"**Mandate** : ml-trainer audit 28/04 — LightGBM peut creer split is_nan(MQ) = proxy date temporelle = leak.\n\n")
        f.write("## Features high-drift par symbole\n\n")
        for sym in ["ES", "NQ"]:
            r = all_results[sym]
            f.write(f"### {sym} ({r['n_high_drift']} features)\n\n")
            high_drift_df = r["all_results"][r["all_results"]["delta_pct"] > DRIFT_THRESHOLD_PCT]
            f.write(high_drift_df.to_string(index=False))
            f.write("\n\n")
        f.write("\n## Action recommandee\n\n")
        f.write("Ajouter les features de l'**UNION** ES + NQ a `ML_EXCLUDE_FEATURES` :\n\n```python\n")
        for feat in sorted(union):
            f.write(f'    "{feat}",\n')
        f.write("```\n")

    print(f"\n[SAVED] {out_path}")
    print(f"\nFeatures a ajouter a ML_EXCLUDE_FEATURES (union ES+NQ, {len(union)} features) :")
    for feat in sorted(union):
        print(f"    {feat}")


if __name__ == "__main__":
    main()
