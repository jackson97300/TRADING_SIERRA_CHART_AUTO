"""
train_v5_lightgbm.py — Train 4 modèles LightGBM V5 walk-forward purged + DSR

Created : 2026-05-02 samedi V5 Step 4 GATE 17h verdict
Strategy : 4 modèles binaires (ES_BUY, ES_SELL, NQ_BUY, NQ_SELL) avec :
  - prepare_for_lightgbm (drop HOLD, binarise par side)
  - PurgedKFold Lopez ch.7 (embargo = horizon labels)
  - LightGBM params défaut (V1 baseline rapide; Optuna V2 si time)
  - Sample weights uniqueness Lopez ch.4 (déjà dans dataset)
  - DSR Bailey-Lopez via compute_dsr (n_trials=120 = 4 baselines × 30 Optuna trials anticipé)
  - Decision tree GATE 17h via v5_gate_evaluator.decision_tree_final

Output :
  - Metrics par modèle (AUC, PF, WR, DSR, max_dd)
  - Verdict global (GO clair / MARGINAL / NO-GO)
  - Sauvegarde rapport DOCS/V5_GATE_17H_RESULTS.md
"""

from __future__ import annotations
from pathlib import Path
import argparse
import time
import warnings
import pandas as pd
import numpy as np
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

import lightgbm as lgb
from sklearn.metrics import roc_auc_score
warnings.filterwarnings("ignore", category=UserWarning)


# ═════════════════════════════════════════════════════════════════════
# 1. PREPARE DATASET (drop META + non-numeric)
# ═════════════════════════════════════════════════════════════════════

META_COLS = {
    "ts", "ts_event", "label", "partial_session", "sample_weight",
    "barrier_type", "ts_t1_actual", "open", "high", "low", "close", "volume",
    "is_nq", "atr", "instrument_id", "publisher_id",
    "_last_swing_high_price", "_last_swing_low_price",  # helpers internes
    "session_id", "session_date", "mins_et",
    "rtype", "symbol",
    # === LEAK CRITIQUES detectes 02/05 (audit feature importance + grep) ===
    "realized_pts",      # PNL realise (correlation 0.67 avec label) → LEAK MASSIF
    # _fwd1 = forward 1 bar → info futur structurelle
    "long_dn_up_fwd1", "long_up_dn_fwd1",
    "bn_color_up_fwd1", "bn_color_dn_fwd1",
    "bn_color_up_2_fwd1", "bn_color_dn_2_fwd1",
    "mins_to_next_news",  # lookahead news event → leak temporel (bar courante voit news future)
}


def get_feature_cols(df: pd.DataFrame) -> list:
    """Retourne cols utilisables pour ML (exclut META + non-numeric)."""
    cols = []
    for c in df.columns:
        if c in META_COLS:
            continue
        # Skip cols categorielles non-encodees (object, datetime)
        if df[c].dtype == "object" or pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        cols.append(c)
    return cols


# ═════════════════════════════════════════════════════════════════════
# 2. WALK-FORWARD PURGED + LIGHTGBM TRAIN
# ═════════════════════════════════════════════════════════════════════

def train_oof_purged(df_prepared: pd.DataFrame, feature_cols: list,
                       n_splits: int = 5, embargo_bars: int = 60,
                       lgb_params: dict = None) -> dict:
    """Walk-forward purged k-fold + LightGBM train + OOF predictions.

    Args:
        df_prepared : output prepare_for_lightgbm() avec y_binary + sample_weight
        feature_cols : list cols features ML
        n_splits : nb folds purged (default 5)
        embargo_bars : embargo bars Lopez (default = horizon labels = 60)
        lgb_params : LightGBM params (None = défauts)

    Returns:
        Dict avec :
          oof_predictions : array proba prediction par sample
          y_true : labels true
          fold_aucs : AUC par fold
          fold_pfs : PF par fold (returns trade-par-trade)
          all_returns : returns array OOS (pour DSR final)
    """
    from labeler_v3 import get_purged_train_test_indices

    if lgb_params is None:
        lgb_params = {
            "objective": "binary",
            "metric": "auc",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": -1,
            "min_data_in_leaf": 20,
            "n_estimators": 200,
            "n_jobs": -1,
            "verbose": -1,
            "force_col_wise": True,
        }

    X = df_prepared[feature_cols].fillna(0).astype(float).values
    y = df_prepared["y_binary"].values
    sw = df_prepared["sample_weight"].values

    # Construire events df pour purged k-fold (besoin ts_event + ts_t1_actual)
    events = df_prepared.set_index("ts_event")[["ts_t1_actual"]].copy()

    oof_preds = np.full(len(df_prepared), np.nan)
    fold_aucs = []
    fold_pfs = []
    all_returns = []

    fold_idx = 0
    for train_idx, test_idx in get_purged_train_test_indices(
        events, n_splits=n_splits, embargo_bars=embargo_bars
    ):
        fold_idx += 1
        # Convert ts_event index → integer positions
        train_pos = df_prepared["ts_event"].isin(train_idx).values
        test_pos = df_prepared["ts_event"].isin(test_idx).values

        if train_pos.sum() < 100 or test_pos.sum() < 30:
            print(f"[fold {fold_idx}] insufficient data, skip")
            continue

        X_tr, y_tr, sw_tr = X[train_pos], y[train_pos], sw[train_pos]
        X_te, y_te = X[test_pos], y[test_pos]

        model = lgb.LGBMClassifier(**lgb_params)
        model.fit(X_tr, y_tr, sample_weight=sw_tr)

        proba = model.predict_proba(X_te)[:, 1]
        oof_preds[test_pos] = proba

        # AUC OOS
        try:
            auc = roc_auc_score(y_te, proba)
        except Exception:
            auc = np.nan
        fold_aucs.append(auc)

        # PF & returns OOS : trade SI proba > 0.5
        triggers = proba > 0.5
        n_trades = int(triggers.sum())
        if n_trades >= 5:
            # Returns approximatif : +pt_sl[0] * vol si y=1, -pt_sl[1] * vol si y=0 (label !=side)
            # Approximation : utilise return_at_t1 du labeler_v3 si dispo, sinon binary signed
            if "return_at_t1" in df_prepared.columns:
                returns = df_prepared.loc[test_pos, "return_at_t1"].values[triggers]
            else:
                # Fallback : binary (+1 si correct, -1 sinon)
                returns = np.where(y_te[triggers] == 1, 1.0, -1.0)

            pf = (returns[returns > 0].sum() / -returns[returns < 0].sum()
                  if (returns < 0).any() else 999.0)
            fold_pfs.append(pf)
            all_returns.extend(returns.tolist())
        else:
            print(f"[fold {fold_idx}] N trades = {n_trades} < 5, skip PF")

    # Feature importance du DERNIER fold (pour audit leak/overfit)
    feature_importances = None
    try:
        if "model" in dir() and hasattr(model, "feature_importances_"):
            feature_importances = list(zip(feature_cols, model.feature_importances_))
            feature_importances.sort(key=lambda x: x[1], reverse=True)
    except Exception:
        pass

    return {
        "oof_predictions": oof_preds,
        "y_true": y,
        "fold_aucs": fold_aucs,
        "fold_pfs": fold_pfs,
        "all_returns": np.array(all_returns),
        "n_folds_completed": len(fold_aucs),
        "feature_importances": feature_importances,
    }


# ═════════════════════════════════════════════════════════════════════
# 3. ORCHESTRATEUR 4 MODELES
# ═════════════════════════════════════════════════════════════════════

def train_v5_4_models(es_path: Path, nq_path: Path,
                        n_splits: int = 5, embargo_bars: int = 60) -> dict:
    """Entraine 4 modèles binaires + applique decision tree GATE 17h."""
    from labeler_v3 import prepare_for_lightgbm
    from v5_gate_evaluator import evaluate_backtest_oos, decision_tree_final, print_report

    print("=" * 70)
    print("V5 TRAIN 4 MODELES — Walk-forward purged + DSR + GATE 17h")
    print("=" * 70)

    df_es = pd.read_parquet(es_path)
    df_nq = pd.read_parquet(nq_path)
    print(f"\nES dataset : {df_es.shape}")
    print(f"NQ dataset : {df_nq.shape}")

    feature_cols_es = get_feature_cols(df_es)
    feature_cols_nq = get_feature_cols(df_nq)
    print(f"Features ES : {len(feature_cols_es)}, NQ : {len(feature_cols_nq)}")

    # Compute n_days estime pour trades_per_day
    n_days_es = (pd.to_datetime(df_es["ts_event"]).dt.date.nunique()
                 if "ts_event" in df_es.columns else 30)
    n_days_nq = (pd.to_datetime(df_nq["ts_event"]).dt.date.nunique()
                 if "ts_event" in df_nq.columns else 30)
    print(f"N jours uniques : ES={n_days_es}, NQ={n_days_nq}")

    results = {}
    for sym, df, feats, n_days in [
        ("ES", df_es, feature_cols_es, n_days_es),
        ("NQ", df_nq, feature_cols_nq, n_days_nq),
    ]:
        for side in ["buy", "sell"]:
            print(f"\n{'─'*60}")
            print(f"Training {sym}_{side.upper()}")
            print(f"{'─'*60}")
            t0 = time.time()

            df_prepared = prepare_for_lightgbm(df, target_side=side)
            if len(df_prepared) < 200:
                print(f"[{sym}_{side}] {len(df_prepared)} samples < 200, skip")
                results[(sym, side)] = {"verdict": "INSUFFICIENT_DATA"}
                continue

            train_result = train_oof_purged(
                df_prepared, feats,
                n_splits=n_splits, embargo_bars=embargo_bars,
            )
            elapsed = time.time() - t0

            n_folds = train_result["n_folds_completed"]
            mean_auc = np.nanmean(train_result["fold_aucs"]) if train_result["fold_aucs"] else np.nan
            mean_pf = np.nanmean(train_result["fold_pfs"]) if train_result["fold_pfs"] else np.nan
            print(f"[{sym}_{side}] {n_folds} folds, AUC mean={mean_auc:.3f}, "
                  f"PF mean={mean_pf:.2f}, time={elapsed:.0f}s")

            # AUDIT LEAK/OVERFIT : top 10 features importance
            fi = train_result.get("feature_importances")
            if fi:
                print(f"\n[{sym}_{side}] TOP 15 FEATURES IMPORTANCES :")
                for feat_name, imp in fi[:15]:
                    print(f"  {imp:>6.0f}  {feat_name}")

            # GATE 17h evaluation
            returns = train_result["all_returns"]
            if len(returns) >= 30:
                eval_result = evaluate_backtest_oos(
                    returns, symbol=sym, side=side,
                    n_trials=120, n_days=n_days,
                    pf_per_fold=train_result["fold_pfs"],
                )
                eval_result["n_features"] = len(feats)
                eval_result["mean_auc"] = float(mean_auc) if not np.isnan(mean_auc) else None
                results[(sym, side)] = eval_result
            else:
                results[(sym, side)] = {
                    "verdict": "INSUFFICIENT_DATA",
                    "n_trades": len(returns),
                }

    # Decision tree global
    print(f"\n{'='*70}")
    print("DECISION TREE GLOBAL — GATE 17h")
    print(f"{'='*70}")
    final = decision_tree_final(results)
    print_report(final, n_trials_declared=120)

    return final


# ═════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--es", default=str(ROOT / "DATA" / "DATASETS" / "v5" / "ES_v5_20260401_20260430.parquet"))
    parser.add_argument("--nq", default=str(ROOT / "DATA" / "DATASETS" / "v5" / "NQ_v5_20260401_20260430.parquet"))
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--embargo", type=int, default=60)
    args = parser.parse_args()

    train_v5_4_models(
        es_path=Path(args.es),
        nq_path=Path(args.nq),
        n_splits=args.n_splits,
        embargo_bars=args.embargo,
    )
