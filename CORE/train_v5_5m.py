"""
train_v5_5m.py — Test V5 sur bars 5m natifs (vs 1m baseline NO-GO)

Created : 2026-05-02 samedi soir post-NO-GO V5 1m
Hypothese : SNR meilleur sur 5m bars (bruit /sqrt(5) = -55%) → edge ML detectable
            la ou 1m bars donnent PF 1.15 < plafond JL2 (1.29).

Pipeline :
  1. Load V5 dataset 1m saved (deja enrichi 779 features clean)
  2. Resample 1m → 5m via groupby (last value cols, OHLCV agg approprie)
  3. Apply labeler_v3 tf='5m' pt_sl=(1.5, 1.0) horizon=8 (grid search ORIGINAL → 50/50)
  4. Train 4 modèles via train_oof_purged
  5. GATE verdict (re-utilise v5_gate_evaluator)

Note : approximation — features V5 1m moyennées en 5m, pas recalculées natif.
Pour test rapide samedi (~30 min) acceptable. Si edge → re-build natif dimanche.
"""

from __future__ import annotations
from pathlib import Path
import argparse
import time
import pandas as pd
import numpy as np
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from train_v5_lightgbm import get_feature_cols, train_oof_purged, META_COLS


def resample_v5_to_5m(df_v5: pd.DataFrame) -> pd.DataFrame:
    """Resample V5 1m bars → 5m bars.

    OHLCV agg :
      open : first
      high : max
      low : min
      close : last
      volume : sum
    Autres cols (features) : last value (snapshot fin de bar 5m).
    Cols binaires (rule_*_dir) : max (any fire dans la 5m bar).
    """
    df = df_v5.copy()
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(None)
    df = df.set_index("ts_event")

    # Identifier types de cols
    ohlcv_cols = ["open", "high", "low", "close", "volume"]
    binary_rule_cols = [c for c in df.columns
                         if c.startswith("rule_") and "_dir" in c]
    other_cols = [c for c in df.columns
                  if c not in ohlcv_cols and c not in binary_rule_cols]

    # Build agg dict
    agg = {}
    if "open" in df.columns:
        agg["open"] = "first"
    if "high" in df.columns:
        agg["high"] = "max"
    if "low" in df.columns:
        agg["low"] = "min"
    if "close" in df.columns:
        agg["close"] = "last"
    if "volume" in df.columns:
        agg["volume"] = "sum"
    for c in binary_rule_cols:
        agg[c] = "max"
    for c in other_cols:
        agg[c] = "last"

    # Resample 5min label='left' closed='left' (cohérent enrich_v5_htf)
    df_5m = df.resample("5min", label="left", closed="left").agg(agg).dropna(subset=["close"])
    df_5m = df_5m.reset_index()
    return df_5m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--es", default=str(ROOT / "DATA" / "DATASETS" / "v5" / "ES_v5_20251215_20260430.parquet"))
    parser.add_argument("--nq", default=str(ROOT / "DATA" / "DATASETS" / "v5" / "NQ_v5_20251215_20260430.parquet"))
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--embargo", type=int, default=12)  # 12 bars 5m = 1h embargo
    args = parser.parse_args()

    print("=" * 70)
    print("V5 TRAIN 4 MODELES BARS 5m NATIFS — Test post-NO-GO 1m")
    print("=" * 70)

    df_es_1m = pd.read_parquet(args.es)
    df_nq_1m = pd.read_parquet(args.nq)
    print(f"\nES 1m : {df_es_1m.shape}")
    print(f"NQ 1m : {df_nq_1m.shape}")

    # 1. Resample 1m → 5m
    print("\n[1/4] Resample 1m → 5m bars...")
    t0 = time.time()
    df_es_5m = resample_v5_to_5m(df_es_1m)
    df_nq_5m = resample_v5_to_5m(df_nq_1m)
    print(f"  ES 5m : {df_es_5m.shape}")
    print(f"  NQ 5m : {df_nq_5m.shape}")
    print(f"  Time : {time.time()-t0:.1f}s")

    # 2. Apply labeler_v3 tf='5m' (grid search ORIGINAL params)
    print("\n[2/4] Apply labeler_v3 tf='5m' (1.5, 1.0) horizon=8 = 40 min...")
    from labeler_v3 import label_dataset_v3
    for sym, df in [("ES", df_es_5m), ("NQ", df_nq_5m)]:
        df_for_label = df[["ts_event", "open", "high", "low", "close", "volume"]].copy()
        events = label_dataset_v3(
            df_for_label,
            tf_name="5m",
            pt_sl=(1.5, 1.0),
            horizon_bars=8,  # 8 bars 5m = 40 min cible (grid search original)
            rvol_threshold=0.3,
        )
        if events.empty:
            print(f"[{sym}] Labeler v3 5m : empty events")
            continue

        # Drop labels 1m precedents avant merge labels 5m
        cols_drop = [c for c in ["label", "sample_weight", "barrier_type", "ts_t1_actual"]
                      if c in df.columns]
        if cols_drop:
            df = df.drop(columns=cols_drop)

        df = df.set_index("ts_event").join(
            events[["label", "sample_weight", "barrier_type", "ts_t1_actual"]],
            how="inner",
        ).reset_index()
        if sym == "ES":
            df_es_5m = df
        else:
            df_nq_5m = df
        dist = df["label"].value_counts(normalize=True)
        print(f"  {sym} 5m labels : +1={dist.get(1, 0):.1%}, "
              f"0={dist.get(0, 0):.1%}, -1={dist.get(-1, 0):.1%}")

    # 3. Train 4 modèles purged k-fold
    print("\n[3/4] Train 4 modèles 5m...")
    from labeler_v3 import prepare_for_lightgbm
    from v5_gate_evaluator import evaluate_backtest_oos, decision_tree_final, print_report

    n_days_es = df_es_5m["ts_event"].dt.date.nunique() if "ts_event" in df_es_5m.columns else 100
    n_days_nq = df_nq_5m["ts_event"].dt.date.nunique() if "ts_event" in df_nq_5m.columns else 100

    results = {}
    for sym, df, n_days in [("ES", df_es_5m, n_days_es), ("NQ", df_nq_5m, n_days_nq)]:
        feature_cols = get_feature_cols(df)
        print(f"\n  {sym} 5m : {len(df)} bars × {len(feature_cols)} features")
        for side in ["buy", "sell"]:
            print(f"\n  Training {sym}_{side.upper()} 5m...")
            df_prepared = prepare_for_lightgbm(df, target_side=side)
            if len(df_prepared) < 200:
                print(f"  [{sym}_{side}] insufficient data, skip")
                continue
            t0 = time.time()
            train_result = train_oof_purged(
                df_prepared, feature_cols,
                n_splits=args.n_splits, embargo_bars=args.embargo,
            )
            elapsed = time.time() - t0
            n_folds = train_result["n_folds_completed"]
            mean_auc = np.nanmean(train_result["fold_aucs"]) if train_result["fold_aucs"] else np.nan
            mean_pf = np.nanmean(train_result["fold_pfs"]) if train_result["fold_pfs"] else np.nan
            print(f"  [{sym}_{side} 5m] {n_folds} folds, AUC={mean_auc:.3f}, "
                  f"PF={mean_pf:.2f}, time={elapsed:.0f}s")

            # Top 10 features
            fi = train_result.get("feature_importances")
            if fi:
                print(f"  TOP 10 :")
                for f, imp in fi[:10]:
                    print(f"    {imp:>5.0f}  {f}")

            returns = train_result["all_returns"]
            if len(returns) >= 30:
                eval_result = evaluate_backtest_oos(
                    returns, symbol=sym, side=side,
                    n_trials=120, n_days=n_days,
                    pf_per_fold=train_result["fold_pfs"],
                )
                eval_result["mean_auc"] = float(mean_auc) if not np.isnan(mean_auc) else None
                results[(sym, side)] = eval_result
            else:
                results[(sym, side)] = {"verdict": "INSUFFICIENT_DATA", "n_trades": len(returns)}

    # 4. GATE verdict
    print(f"\n{'='*70}\n[4/4] GATE VERDICT V5 5m\n{'='*70}")
    final = decision_tree_final(results)
    print_report(final, n_trials_declared=120)


if __name__ == "__main__":
    main()
