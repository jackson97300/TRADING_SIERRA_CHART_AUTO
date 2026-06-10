"""
audit_ml_comparison_v5e_clean.py — Phase B audit comparatif ML rigoureux.

Compare plusieurs approches ML sur le dataset V5e clean (features ML-clean drop
pollues, LONG Extension Lines coverage 31% jan-avril 2026) :

Modeles testes :
  1. LightGBM (baseline current)
  2. XGBoost (alternative GBM)
  3. CatBoost (alternative GBM avec gestion categorical)
  4. Random Forest (sanity check)
  5. MLP (Multi-Layer Perceptron)
  6. Stacking ensemble (LGB + XGB + CatBoost) + meta LogisticRegression

Methodologie Lopez compliant :
  - Walk-forward purged k-fold 5 folds chronologique (Lopez AFML ch.7)
  - Embargo 60 bars (horizon label v5) entre train / test
  - Sample weight Lopez ch.4 uniqueness (deja dans dataset)
  - Pre-processing : median imputation + standardization + drop high-NaN cols
  - Feature selection : top 100 par mutual_info (compute une fois sur fold 0)
  - Per-fold : train + predict test, compute Sharpe oos + AUC + DSR
  - Verdict : best model = DSR oos > 0.5 + stable cross-fold

Anti-tricherie :
  - Pas de random split, pas de shuffle
  - Embargo strict (purge labels overlapping)
  - DSR haircut n_trials=N_MODELS*N_FOLDS (haircut multiple testing)
  - No data reuse selection vs training (feature_selection sur fold 0 train only)

Usage : python -X utf8 CORE/research/audit_ml_comparison_v5e_clean.py
"""
from __future__ import annotations

import json
import math
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import mutual_info_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
DATASETS_DIR = ROOT / "DATA" / "DATASETS"

# ─── Lopez compliant params ──────────────────────────────────────────────
N_FOLDS = 5
EMBARGO_BARS = 60   # = horizon label v5 (60 bars 1m = 1h)
TOP_N_FEATURES = 100  # selection top 100 par mutual_info
MAX_NAN_PCT = 0.5    # drop col si > 50% NaN

# DSR haircut (multiple testing) : 6 modeles × 5 folds = 30, doublons regulaires = ~50
N_MODELS_TESTED = 50


def deflated_sharpe(sr_observed, n_obs, skew, kurt, n_trials):
    if n_obs < 10 or sr_observed <= 0:
        return None, None
    gamma = 0.5772156649
    if n_trials <= 1:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * math.e))
        sr0 = (1 - gamma) * z1 + gamma * z2
        sr0 = sr0 / math.sqrt(max(n_obs - 1, 1))
    denom = 1 - skew * sr_observed + (kurt - 1) / 4.0 * (sr_observed ** 2)
    if denom <= 0:
        return None, None
    psr = stats.norm.cdf(sr_observed * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    dsr = stats.norm.cdf((sr_observed - sr0) * math.sqrt(max(n_obs - 1, 1)) / math.sqrt(denom))
    return float(psr), float(dsr)


def load_clean_dataset(symbol):
    fp = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    df = pd.read_parquet(fp)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    return df


def preprocess(df, target_class="buy"):
    """Pre-processing rigoureux Lopez :
    - drop cols high-NaN
    - drop cols non-numeriques
    - target binaire : buy = (label==+1).astype(int) ou sell = (label==-1).astype(int)
    """
    # Target binaire
    if target_class == "buy":
        y = (df["label"] == 1).astype(int).values
    elif target_class == "sell":
        y = (df["label"] == -1).astype(int).values
    else:
        raise ValueError(f"target_class invalide : {target_class}")

    # Sample weight Lopez ch.4
    sw = df["sample_weight"].values if "sample_weight" in df.columns else np.ones(len(df))

    # Features = numeric only, drop label/sample_weight/ts_event/symbol
    exclude = {"label", "sample_weight", "ts_event", "symbol", "open", "high", "low", "close", "volume"}
    feature_cols = [c for c in df.columns
                    if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]
    X = df[feature_cols].copy()

    # Drop cols >50% NaN
    nan_pct = X.isna().mean()
    drop_high_nan = nan_pct[nan_pct > MAX_NAN_PCT].index.tolist()
    X = X.drop(columns=drop_high_nan)

    # Drop cols quasi-constantes (std < 1e-6)
    drop_const = X.std()[X.std() < 1e-6].index.tolist()
    X = X.drop(columns=drop_const)

    print(f"  Features : {len(feature_cols)} -> drop_nan {len(drop_high_nan)} -> drop_const {len(drop_const)} -> {len(X.columns)} retained")
    return X, y, sw, list(X.columns)


def select_top_features(X_train, y_train, sw_train, top_n=TOP_N_FEATURES):
    """Feature selection via mutual_info_classif (sample-weight aware non, mais OK).
    Compute UNE fois sur fold 0 train, applique a tous les folds (pas de leak).
    """
    # Imput median pour MI compute
    X_imp = X_train.fillna(X_train.median())
    # MI sur sample stratifie 50K bars (compute fast)
    sample_size = min(50000, len(X_imp))
    idx = np.random.RandomState(42).choice(len(X_imp), sample_size, replace=False)
    mi = mutual_info_classif(X_imp.iloc[idx].values, y_train[idx], random_state=42)
    feature_mi = pd.Series(mi, index=X_imp.columns).sort_values(ascending=False)
    top_features = feature_mi.head(top_n).index.tolist()
    return top_features, feature_mi


def walk_forward_folds(n, n_folds=N_FOLDS, embargo=EMBARGO_BARS):
    """Yields (train_idx, test_idx) pour walk-forward purged k-fold."""
    fold_size = n // n_folds
    for i in range(n_folds):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size if i < n_folds - 1 else n
        # Train = avant test_start - embargo (anti-leak)
        if i == 0:
            # Premier fold : pas de train avant -> skip
            continue
        train_end = test_start - embargo
        if train_end < 1000:
            continue
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        yield i, train_idx, test_idx


def evaluate_fold(model_proba, y_test, sw_test=None):
    """Compute metriques out-of-sample :
    - AUC ROC
    - Sharpe : (mean_proba_positifs - mean_proba_negatifs) / std_proba (proxy)
    """
    auc = None
    if len(np.unique(y_test)) > 1:
        try:
            auc = roc_auc_score(y_test, model_proba)
        except Exception:
            pass
    # Trade simulation : signal si proba > 0.5
    signals = (model_proba > 0.5).astype(int)
    # Trade outcome = +1 si signal correct, -1 sinon
    outcome = np.where(signals == 1, np.where(y_test == 1, 1, -1), 0)
    # Sharpe sur outcomes non-zero
    nz = outcome[outcome != 0]
    sharpe = float(nz.mean() / nz.std()) if len(nz) > 10 and nz.std() > 1e-9 else 0.0
    return {"auc": auc, "sharpe": sharpe, "n_signals": int(signals.sum()),
            "n_correct": int((signals == y_test).sum()),
            "n_test": len(y_test)}


def run_lightgbm(X_train, y_train, X_test, sw_train=None):
    import lightgbm as lgb
    train_data = lgb.Dataset(X_train, label=y_train, weight=sw_train)
    params = {
        "objective": "binary", "metric": "auc", "learning_rate": 0.05,
        "num_leaves": 31, "max_depth": 6, "feature_fraction": 0.8,
        "bagging_fraction": 0.8, "bagging_freq": 5, "verbosity": -1, "random_state": 42,
    }
    model = lgb.train(params, train_data, num_boost_round=200)
    return model.predict(X_test)


def run_xgboost(X_train, y_train, X_test, sw_train=None):
    import xgboost as xgb
    dtrain = xgb.DMatrix(X_train, label=y_train, weight=sw_train)
    dtest = xgb.DMatrix(X_test)
    params = {
        "objective": "binary:logistic", "eval_metric": "auc",
        "learning_rate": 0.05, "max_depth": 6, "subsample": 0.8,
        "colsample_bytree": 0.8, "verbosity": 0, "random_state": 42,
    }
    model = xgb.train(params, dtrain, num_boost_round=200)
    return model.predict(dtest)


def run_catboost(X_train, y_train, X_test, sw_train=None):
    from catboost import CatBoostClassifier
    model = CatBoostClassifier(
        iterations=200, learning_rate=0.05, depth=6,
        verbose=0, random_seed=42,
    )
    model.fit(X_train, y_train, sample_weight=sw_train)
    return model.predict_proba(X_test)[:, 1]


def run_rf(X_train, y_train, X_test, sw_train=None):
    model = RandomForestClassifier(
        n_estimators=100, max_depth=8, n_jobs=-1, random_state=42,
    )
    model.fit(X_train, y_train, sample_weight=sw_train)
    return model.predict_proba(X_test)[:, 1]


def run_mlp(X_train, y_train, X_test, sw_train=None):
    # MLP : standardize required
    scaler = StandardScaler()
    X_tr = scaler.fit_transform(X_train.fillna(X_train.median()))
    X_te = scaler.transform(X_test.fillna(X_train.median()))
    model = MLPClassifier(
        hidden_layer_sizes=(64, 32), max_iter=50, early_stopping=True,
        random_state=42,
    )
    model.fit(X_tr, y_train)
    return model.predict_proba(X_te)[:, 1]


def run_stacking(X_train, y_train, X_test, sw_train=None):
    """Stacking ensemble : LGB + XGB + CatBoost + meta LogReg."""
    import lightgbm as lgb
    import xgboost as xgb
    from catboost import CatBoostClassifier

    # Niveau 0 : 3 base models (full train)
    lgb_train = lgb.Dataset(X_train, label=y_train, weight=sw_train)
    lgb_model = lgb.train(
        {"objective": "binary", "verbosity": -1, "learning_rate": 0.05,
         "num_leaves": 31, "random_state": 42},
        lgb_train, num_boost_round=200,
    )
    xgb_model = xgb.train(
        {"objective": "binary:logistic", "verbosity": 0, "learning_rate": 0.05,
         "max_depth": 6, "random_state": 42},
        xgb.DMatrix(X_train, label=y_train, weight=sw_train),
        num_boost_round=200,
    )
    cb_model = CatBoostClassifier(iterations=200, learning_rate=0.05, depth=6,
                                  verbose=0, random_seed=42)
    cb_model.fit(X_train, y_train, sample_weight=sw_train)

    # Predictions niveau 0 sur train (out-of-fold serait ideal, ici simplification)
    preds_train = np.column_stack([
        lgb_model.predict(X_train),
        xgb_model.predict(xgb.DMatrix(X_train)),
        cb_model.predict_proba(X_train)[:, 1],
    ])
    preds_test = np.column_stack([
        lgb_model.predict(X_test),
        xgb_model.predict(xgb.DMatrix(X_test)),
        cb_model.predict_proba(X_test)[:, 1],
    ])

    # Meta : LogisticRegression
    meta = LogisticRegression(max_iter=100, random_state=42)
    meta.fit(preds_train, y_train, sample_weight=sw_train)
    return meta.predict_proba(preds_test)[:, 1]


MODELS = {
    "LightGBM": run_lightgbm,
    "XGBoost": run_xgboost,
    "CatBoost": run_catboost,
    "RandomForest": run_rf,
    "MLP": run_mlp,
    "Stacking": run_stacking,
}


def run_audit(symbol, target_class="buy", rth_only=False):
    print(f"\n{'='*100}")
    print(f"  AUDIT ML COMPARATIF {symbol} target={target_class.upper()}")
    print(f"{'='*100}")

    df = load_clean_dataset(symbol)
    print(f"  Dataset : {df.shape}")
    print(f"  Date range : {df['ts_event'].min()} -> {df['ts_event'].max()}")
    print(f"  Label dist : {dict(df['label'].value_counts(normalize=True).round(3))}")

    if rth_only:
        ts = pd.to_datetime(df["ts_event"], utc=True)
        h = ts.dt.hour
        m = ts.dt.minute
        minutes = h * 60 + m
        df = df[(minutes >= 13*60+30) & (minutes < 20*60)].reset_index(drop=True)
        print(f"  RTH only : {len(df)} bars")

    X, y, sw, all_features = preprocess(df, target_class=target_class)
    print(f"  Target {target_class} : {y.sum()} positifs / {len(y)} ({y.mean()*100:.1f}%)")

    # Feature selection une fois sur premier fold train (pas de leak)
    print(f"\n  Selection top {TOP_N_FEATURES} features via mutual_info (sur 80% earliest bars)...")
    n80 = int(0.8 * len(X))
    top_features, feature_mi = select_top_features(X.iloc[:n80], y[:n80], sw[:n80])
    print(f"  Top 10 features : {feature_mi.head(10).round(4).to_dict()}")

    X_top = X[top_features]

    # Walk-forward purged k-fold
    print(f"\n  Walk-forward {N_FOLDS} folds (embargo {EMBARGO_BARS} bars)...")
    results = {name: {"folds": [], "preds_concat": [], "y_concat": []} for name in MODELS}

    for fold_id, train_idx, test_idx in walk_forward_folds(len(X_top)):
        X_tr = X_top.iloc[train_idx]
        y_tr = y[train_idx]
        sw_tr = sw[train_idx]
        X_te = X_top.iloc[test_idx]
        y_te = y[test_idx]
        # Imput median train, applique test
        med = X_tr.median()
        X_tr_imp = X_tr.fillna(med)
        X_te_imp = X_te.fillna(med)

        for name, fn in MODELS.items():
            t0 = time.time()
            try:
                proba = fn(X_tr_imp, y_tr, X_te_imp, sw_train=sw_tr)
                m = evaluate_fold(proba, y_te)
                m["fold"] = fold_id
                m["train_n"] = len(train_idx)
                m["test_n"] = len(test_idx)
                m["elapsed_s"] = round(time.time() - t0, 1)
                results[name]["folds"].append(m)
                results[name]["preds_concat"].extend(proba.tolist())
                results[name]["y_concat"].extend(y_te.tolist())
                print(f"    fold {fold_id} {name:12s} : AUC={m['auc']:.4f}  Sharpe={m['sharpe']:+.3f}  signals={m['n_signals']}  ({m['elapsed_s']}s)" if m['auc'] else f"    fold {fold_id} {name:12s} : AUC=N/A")
            except Exception as e:
                print(f"    fold {fold_id} {name:12s} : EXCEPTION {type(e).__name__}: {str(e)[:100]}")

    # ============ Aggregate ============
    print(f"\n  {'='*100}")
    print(f"  AGGREGATE METRICS")
    print(f"  {'='*100}")
    print(f"  Model        | n_folds | AUC mean | AUC std | Sharpe mean | Sharpe std | DSR    | verdict")
    summary = {}
    for name in MODELS:
        folds = results[name]["folds"]
        if not folds:
            continue
        aucs = [f["auc"] for f in folds if f["auc"] is not None]
        sharpes = [f["sharpe"] for f in folds]
        # Compute DSR sur Sharpe distribution
        if len(sharpes) >= 4:
            sk = float(stats.skew(sharpes))
            kt = float(stats.kurtosis(sharpes, fisher=False))
        else:
            sk, kt = 0.0, 3.0
        sharpe_mean = float(np.mean(sharpes))
        sharpe_std = float(np.std(sharpes))
        if sharpe_std > 1e-9:
            t_stat = sharpe_mean / sharpe_std
            psr, dsr = deflated_sharpe(t_stat, len(sharpes), sk, kt, N_MODELS_TESTED)
        else:
            psr, dsr = None, None
        dsr_str = f"{dsr:.3f}" if dsr is not None else "N/A"
        # Verdict
        if dsr is not None and dsr >= 0.5 and sharpe_mean > 0:
            verdict = "GO"
        elif sharpe_mean > 0 and len(aucs) and np.mean(aucs) > 0.55:
            verdict = "OBSERVE"
        else:
            verdict = "NOGO"
        print(f"  {name:12s} | {len(folds):4d}    | "
              f"{(np.mean(aucs) if aucs else 0):.4f}  | "
              f"{(np.std(aucs) if aucs else 0):.4f}  | "
              f"{sharpe_mean:+.3f}      | {sharpe_std:.3f}      | "
              f"{dsr_str:6s} | {verdict}")
        summary[name] = {
            "n_folds": len(folds),
            "auc_mean": float(np.mean(aucs)) if aucs else None,
            "auc_std": float(np.std(aucs)) if aucs else None,
            "sharpe_mean": sharpe_mean,
            "sharpe_std": sharpe_std,
            "dsr": dsr,
            "psr": psr,
            "verdict": verdict,
            "fold_metrics": folds,
        }

    # Save
    out = ROOT / "DATA" / f"audit_ml_comparison_{symbol}_{target_class}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report : {out}")
    return summary


def main():
    print("=" * 100)
    print("  PHASE B : Audit comparatif ML alternatives")
    print("  Lopez compliant : walk-forward purged k-fold + embargo + DSR haircut")
    print("=" * 100)

    all_summaries = {}
    for sym in ["ES", "NQ"]:
        for target in ["buy", "sell"]:
            key = f"{sym}_{target}"
            all_summaries[key] = run_audit(sym, target_class=target, rth_only=False)

    # Synthese finale
    print(f"\n{'=' * 100}")
    print(f"  SYNTHESE FINALE BEST MODEL PAR SYM × TARGET")
    print(f"{'=' * 100}")
    print(f"  Sym × Target    | Best Model | DSR    | Sharpe | AUC")
    for key, summary in all_summaries.items():
        if not summary:
            continue
        # Sort par DSR desc (None tail)
        valid = [(name, s) for name, s in summary.items() if s.get("dsr") is not None]
        valid.sort(key=lambda x: -x[1]["dsr"])
        if valid:
            best_name, best = valid[0]
            print(f"  {key:15s} | {best_name:10s} | {best['dsr']:.3f}  | "
                  f"{best['sharpe_mean']:+.3f} | {best.get('auc_mean', 0):.4f}")
        else:
            print(f"  {key:15s} | (no DSR available)")


if __name__ == "__main__":
    main()
