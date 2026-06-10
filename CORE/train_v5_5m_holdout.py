"""
train_v5_5m_holdout.py — Hold-out strict 70/30 chronologique sur V5 5m

Created : 2026-05-02 samedi soir post-finding edge SELL 5m (Jackson flag biais régime baissier)

Goal : tester si edge SELL ES_sell PF 1.54 / NQ_sell PF 1.59 tient sur 30%
derniers jours JAMAIS vus pendant train.

LIMITATION HONNETE (Jackson 02/05) :
  Tous les 7 mois (déc 2025 - avr 2026) = régime baissier (tensions geopolitiques).
  Hold-out chronologique 30% derniers jours = MEME régime baissier.
  → Ne teste PAS la robustesse cross-régime, JUSTE stabilité temporelle.
  → Pour vrai test régime, paper trading futur (lundi+) sur régime different requis.

Pipeline :
  1. Load V5 dataset 1m saved (32K bars, 7 mois)
  2. Resample en 5m (~6500 bars)
  3. Apply labeler_v3 tf='5m' (1.5, 1.0) horizon=8
  4. Split chronologique 70/30 (train sur premiers 70%, hold-out sur 30% derniers)
  5. Train 4 modèles sur train, predict sur hold-out
  6. Compare metrics hold-out vs walk-forward 5 folds (PF 1.54/1.59)
  7. Verdict : si hold-out PF > 1.30 et degradation < 0.20 vs WF → robuste
              si hold-out PF < 1.10 → overfit local
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

import lightgbm as lgb
import warnings
from sklearn.metrics import roc_auc_score
warnings.filterwarnings("ignore", category=UserWarning)

from train_v5_lightgbm import get_feature_cols, META_COLS
from train_v5_5m import resample_v5_to_5m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--es", default=str(ROOT / "DATA" / "DATASETS" / "v5" / "ES_v5_20251215_20260430.parquet"))
    parser.add_argument("--nq", default=str(ROOT / "DATA" / "DATASETS" / "v5" / "NQ_v5_20251215_20260430.parquet"))
    parser.add_argument("--holdout-pct", type=float, default=0.30)
    args = parser.parse_args()

    print("=" * 70)
    print("V5 5m HOLD-OUT STRICT 70/30 chronologique")
    print(f"Hold-out : {args.holdout_pct:.0%} derniers jours")
    print("=" * 70)
    print("\n⚠️  LIMITATION : tous 7 mois = régime baissier. Hold-out teste")
    print("    juste stabilité temporelle, PAS robustesse cross-régime.")

    df_es_1m = pd.read_parquet(args.es)
    df_nq_1m = pd.read_parquet(args.nq)

    # 1. Resample 1m → 5m
    print("\n[1/3] Resample 1m → 5m...")
    df_es_5m = resample_v5_to_5m(df_es_1m)
    df_nq_5m = resample_v5_to_5m(df_nq_1m)
    print(f"  ES 5m : {df_es_5m.shape}")
    print(f"  NQ 5m : {df_nq_5m.shape}")

    # 2. Apply labeler_v3 5m
    print("\n[2/3] Labeler v3 5m...")
    from labeler_v3 import label_dataset_v3
    for sym, df in [("ES", df_es_5m), ("NQ", df_nq_5m)]:
        df_for_label = df[["ts_event", "open", "high", "low", "close", "volume"]].copy()
        events = label_dataset_v3(
            df_for_label,
            tf_name="5m", pt_sl=(1.5, 1.0), horizon_bars=8, rvol_threshold=0.3,
        )
        if events.empty:
            continue
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

    # 3. Split chronologique 70/30 + train/test
    print(f"\n[3/3] Split 70/30 + train/predict + compare...")
    from labeler_v3 import prepare_for_lightgbm

    results = {}
    for sym, df in [("ES", df_es_5m), ("NQ", df_nq_5m)]:
        feature_cols = get_feature_cols(df)
        for side in ["buy", "sell"]:
            print(f"\n  {sym}_{side.upper()} 5m :")
            df_prepared = prepare_for_lightgbm(df, target_side=side)
            n = len(df_prepared)
            split_idx = int(n * (1 - args.holdout_pct))

            df_prepared = df_prepared.sort_values("ts_event").reset_index(drop=True)
            train_df = df_prepared.iloc[:split_idx]
            holdout_df = df_prepared.iloc[split_idx:]

            train_dates = pd.to_datetime(train_df["ts_event"])
            holdout_dates = pd.to_datetime(holdout_df["ts_event"])
            print(f"    Train : {len(train_df)} bars ({train_dates.min().date()} → {train_dates.max().date()})")
            print(f"    Hold-out : {len(holdout_df)} bars ({holdout_dates.min().date()} → {holdout_dates.max().date()})")

            X_tr = train_df[feature_cols].fillna(0).astype(float).values
            y_tr = train_df["y_binary"].values
            sw_tr = train_df["sample_weight"].values

            X_ho = holdout_df[feature_cols].fillna(0).astype(float).values
            y_ho = holdout_df["y_binary"].values

            # LightGBM defaut params
            model = lgb.LGBMClassifier(
                objective="binary", metric="auc",
                learning_rate=0.05, num_leaves=31, max_depth=-1,
                min_data_in_leaf=20, n_estimators=200, n_jobs=-1, verbose=-1,
                force_col_wise=True,
            )
            t0 = time.time()
            model.fit(X_tr, y_tr, sample_weight=sw_tr)
            elapsed = time.time() - t0

            # Predict hold-out
            proba_ho = model.predict_proba(X_ho)[:, 1]
            auc_ho = roc_auc_score(y_ho, proba_ho) if len(set(y_ho)) > 1 else np.nan

            # PF hold-out
            triggers = proba_ho > 0.5
            n_trades_ho = int(triggers.sum())
            if n_trades_ho >= 5:
                returns_ho = holdout_df.loc[triggers.tolist(), "return_at_t1"].values \
                    if "return_at_t1" in holdout_df.columns \
                    else np.where(y_ho[triggers] == 1, 1.0, -1.0)
                pf_ho = (returns_ho[returns_ho > 0].sum() / -returns_ho[returns_ho < 0].sum()
                         if (returns_ho < 0).any() else 999.0)
                wr_ho = (returns_ho > 0).mean()
            else:
                pf_ho = np.nan
                wr_ho = np.nan

            print(f"    HOLD-OUT : AUC={auc_ho:.3f}, PF={pf_ho:.2f}, WR={wr_ho:.1%}, "
                  f"N_trades={n_trades_ho}, time={elapsed:.0f}s")

            results[(sym, side)] = {
                "auc_ho": auc_ho, "pf_ho": pf_ho, "wr_ho": wr_ho,
                "n_trades_ho": n_trades_ho,
            }

    # Compare WF (référence) vs hold-out
    print(f"\n{'='*70}\nCOMPARAISON WALK-FORWARD vs HOLD-OUT\n{'='*70}")
    wf_reference = {
        ("ES", "buy"):  {"pf": 0.93, "auc": 0.573},
        ("ES", "sell"): {"pf": 1.54, "auc": 0.573},
        ("NQ", "buy"):  {"pf": 0.92, "auc": 0.578},
        ("NQ", "sell"): {"pf": 1.59, "auc": 0.578},
    }
    print(f"{'Combo':12} | {'WF PF':>6} | {'HO PF':>6} | {'Δ PF':>6} | {'WF AUC':>7} | {'HO AUC':>7} | Verdict")
    print("-" * 80)
    for (sym, side), wf in wf_reference.items():
        ho = results.get((sym, side), {})
        pf_wf = wf["pf"]
        pf_ho = ho.get("pf_ho", np.nan)
        delta = pf_ho - pf_wf if not np.isnan(pf_ho) else np.nan
        auc_wf = wf["auc"]
        auc_ho = ho.get("auc_ho", np.nan)

        if np.isnan(pf_ho) or pf_ho < 1.0:
            verdict = "OVERFIT" if not np.isnan(pf_wf) and pf_wf > 1.3 else "NO-EDGE"
        elif abs(delta) < 0.20 and pf_ho > 1.3:
            verdict = "ROBUSTE"
        elif pf_ho > 1.0:
            verdict = "DEGRADE_OK"
        else:
            verdict = "FAIL"

        print(f"{sym}_{side:5} | {pf_wf:>6.2f} | {pf_ho:>6.2f} | {delta:>+6.2f} | "
              f"{auc_wf:>7.3f} | {auc_ho:>7.3f} | {verdict}")


if __name__ == "__main__":
    main()
