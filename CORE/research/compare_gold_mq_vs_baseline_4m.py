"""Comparaison Gold edge : V5e_enriched (4m subset) vs V5e_MQ_enriched (4m).

Mesure le gain réel des features MQ Gold (dist_mq_*, blind, gex, bool_*).

Méthodologie :
  - Baseline = V5e_enriched filtré jan-mai 2026 (même range)
  - Enriched = V5e_MQ_enriched (V5e + 16 features MQ Gold)
  - Train 80% chronologique, test 20%
  - Métriques OOS : R², Spearman rho, edge LONG/SHORT
  - Verdict : si Δrho > +0.03 → MQ Gold apporte vraiment
"""
import sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import json
import pandas as pd
import numpy as np
import lightgbm as lgb
from scipy.stats import spearmanr

ENRICHED = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_enriched.parquet"
MQ_ENRICHED = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_mq_enriched.parquet"

TICK_SIZE = 0.10
FWD_WINDOW = 30
P_LONG = 0.90
P_SHORT = 0.10
DATE_START = date(2026, 1, 12)
DATE_END = date(2026, 5, 8)

LEAK = {"close", "open", "high", "low", "close_fwd30", "atr_for_norm",
        "ts_event", "ts_recv", "target",
        "cvd_session", "cvd_day", "delta_day", "delta_session",
        "session_date", "session_date_trading", "_date", "vix_level"}


def prepare(df, filter_date=False):
    df = df.copy()
    if filter_date:
        ts = pd.to_datetime(df["ts_event"], errors="coerce")
        mask = (ts.dt.date >= DATE_START) & (ts.dt.date <= DATE_END)
        df = df[mask].reset_index(drop=True)
    df["close_fwd30"] = df["close"].shift(-FWD_WINDOW)
    df["atr_for_norm"] = df["atr"].replace(0, np.nan).fillna(17.3)
    df["target"] = (df["close_fwd30"] - df["close"]) / (df["atr_for_norm"] * TICK_SIZE)
    df = df.dropna(subset=["target"]).reset_index(drop=True)
    features = []
    for c in df.columns:
        if c in LEAK:
            continue
        if df[c].dtype.kind in "biufc":
            if df[c].isna().sum() / len(df) > 0.95:
                continue
            if df[c].nunique(dropna=True) < 5:
                continue
            features.append(c)
    return df, features


def train_eval(df, features, label):
    n_train = int(len(df) * 0.80)
    df_train = df.iloc[:n_train]
    df_test = df.iloc[n_train:]
    X_train = df_train[features].astype(float).fillna(0).values
    y_train = df_train["target"].astype(float).values
    X_test = df_test[features].astype(float).fillna(0).values
    y_test = df_test["target"].astype(float).values

    params = {
        "objective": "regression", "metric": "rmse",
        "learning_rate": 0.05, "num_leaves": 31,
        "feature_fraction": 0.85, "bagging_fraction": 0.85, "bagging_freq": 5,
        "min_data_in_leaf": 100, "verbose": -1,
    }
    dtrain = lgb.Dataset(X_train, label=y_train, free_raw_data=False)
    dtest = lgb.Dataset(X_test, label=y_test, reference=dtrain, free_raw_data=False)
    model = lgb.train(params, dtrain, num_boost_round=200,
                      valid_sets=[dtest], valid_names=["test"],
                      callbacks=[lgb.early_stopping(20), lgb.log_evaluation(0)])
    y_pred = model.predict(X_test)

    ss_res = ((y_test - y_pred) ** 2).sum()
    ss_tot = ((y_test - y_test.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot
    rho, pval = spearmanr(y_test, y_pred)

    p_long = np.quantile(y_pred, P_LONG)
    p_short = np.quantile(y_pred, P_SHORT)
    long_targets = y_test[y_pred >= p_long]
    short_targets = y_test[y_pred <= p_short]
    edge_long = float(long_targets.mean()) if len(long_targets) > 0 else 0.0
    edge_short = float(-short_targets.mean()) if len(short_targets) > 0 else 0.0
    edge_combined = (long_targets.sum() - short_targets.sum()) / (len(long_targets) + len(short_targets)) \
                    if (len(long_targets) + len(short_targets)) > 0 else 0.0

    importance = pd.DataFrame({
        "feature": features,
        "gain": model.feature_importance(importance_type="gain"),
    }).sort_values("gain", ascending=False).reset_index(drop=True)

    return {
        "label": label,
        "n_train": len(df_train), "n_test": len(df_test),
        "n_features": len(features),
        "r2": r2, "rho": rho, "pval": pval,
        "edge_long": edge_long, "edge_short": edge_short,
        "edge_combined": edge_combined,
        "top10": importance.head(10),
    }


def main():
    print(f"=== Comparaison Gold edge : V5e_enriched (4m) vs V5e_MQ_enriched (4m) ===\n")
    print(f"  Loading V5e_enriched...")
    df_b = pd.read_parquet(ENRICHED)
    df_b, feat_b = prepare(df_b, filter_date=True)
    print(f"    Shape : {df_b.shape}, features : {len(feat_b)}")

    print(f"\n  Loading V5e_MQ_enriched...")
    df_e = pd.read_parquet(MQ_ENRICHED)
    df_e, feat_e = prepare(df_e, filter_date=False)  # déjà filtré jan-mai
    print(f"    Shape : {df_e.shape}, features : {len(feat_e)}")

    print(f"\n--- Training BASELINE V5e_enriched (4m subset) ---")
    res_b = train_eval(df_b, feat_b, "BASELINE_4m")

    print(f"\n--- Training MQ_ENRICHED ---")
    res_e = train_eval(df_e, feat_e, "MQ_ENRICHED_4m")

    print(f"\n\n=== RESULTATS COMPARAISON ===\n")
    print(f"  Metric{'':<20}{res_b['label']:<22}{res_e['label']:<22}Delta")
    print("  " + "-" * 95)
    for metric in ["n_features", "r2", "rho", "edge_long", "edge_short", "edge_combined"]:
        v_b = res_b[metric]
        v_e = res_e[metric]
        delta = v_e - v_b
        marker = "[+]" if delta > 0 else "[-]"
        if isinstance(v_b, float):
            print(f"  {metric:<26}{v_b:>15.4f}{'':<10}{v_e:>15.4f}{'':<10}{marker} {delta:+.4f}")
        else:
            print(f"  {metric:<26}{v_b:>15}{'':<10}{v_e:>15}{'':<10}{marker} {delta:+}")

    print(f"\n=== TOP 10 features BASELINE 4m ===")
    print(res_b["top10"].to_string(index=False))

    print(f"\n=== TOP 10 features MQ_ENRICHED 4m ===")
    print(res_e["top10"].to_string(index=False))

    # Quelles features MQ_Gold dans le top 30 ?
    print(f"\n=== Features MQ Gold dans TOP 30 enriched ===")
    importance_e = pd.DataFrame({
        "feature": [c for c in res_e["top10"].columns if c == "feature"][0:0] or res_e["top10"]["feature"].tolist(),
    })
    # Recompute full importance
    from lightgbm import Dataset
    full_imp = res_e
    # Just identify mq_* in top 30 via top10 already shown — bring more
    # Re-train rapid for top 30 :
    n_train = int(len(df_e) * 0.80)
    X_train = df_e.iloc[:n_train][feat_e].astype(float).fillna(0).values
    y_train = df_e.iloc[:n_train]["target"].astype(float).values
    params = {"objective": "regression", "metric": "rmse", "learning_rate": 0.05,
              "num_leaves": 31, "verbose": -1}
    m = lgb.train(params, lgb.Dataset(X_train, label=y_train, free_raw_data=False),
                  num_boost_round=30)
    imp = pd.DataFrame({"feature": feat_e, "gain": m.feature_importance(importance_type="gain")})
    imp = imp.sort_values("gain", ascending=False).reset_index(drop=True)
    mq_features = imp[imp["feature"].str.startswith(("dist_mq_", "dist_1d_", "dist_blind_",
                                                       "dist_gex_", "gex_cluster", "bool_above_mq",
                                                       "bool_gex"))].head(15)
    print(mq_features.to_string(index=False))
    print(f"\n  Rang max d'une feature MQ : {mq_features.index.min() if len(mq_features) > 0 else 'N/A'}")

    delta_rho = res_e["rho"] - res_b["rho"]
    delta_edge = res_e["edge_combined"] - res_b["edge_combined"]

    print(f"\n=== VERDICT ===")
    print(f"  Δrho : {delta_rho:+.4f}")
    print(f"  Δedge_combined : {delta_edge:+.4f} ATR")

    if delta_rho > 0.05:
        verdict = "GO STRONG — MQ Gold apporte uplift significatif, walk-forward final + paper test"
    elif delta_rho > 0.02:
        verdict = "GO MARGINAL — MQ Gold ajoute peu mais positif, garder + walk-forward DSR"
    elif delta_rho > -0.005:
        verdict = "NEUTRAL — MQ Gold pas discriminant (probablement substitut features existantes)"
    else:
        verdict = "NEGATIVE — MQ Gold ajoute bruit, audit individuel"
    print(f"  {verdict}")

    OUTPUT = ROOT / "DATA" / "BACKTEST" / "GOLD" / "gold_mq_vs_baseline_4m.json"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "baseline_4m": {k: v for k, v in res_b.items() if k != "top10"},
        "mq_enriched_4m": {k: v for k, v in res_e.items() if k != "top10"},
        "delta_rho": delta_rho, "delta_edge_combined": delta_edge,
        "verdict": verdict,
    }
    OUTPUT.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\n  Saved : {OUTPUT}")


if __name__ == "__main__":
    main()
