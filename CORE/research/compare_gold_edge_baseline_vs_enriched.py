"""Comparaison empirique edge Gold : baseline (V5e session) vs enrichi (V5e + Phase D + extra).

Run après pull Databento + enrich_gold_dataset_full.py.

Méthodologie :
  1. Train LightGBM sur 80% chronologique de CHAQUE dataset
  2. Predict sur 20% test
  3. Métriques OOS : R², Spearman rho, edge LONG, edge SHORT
  4. Diff = quantification gain features state-of-the-art

Verdict :
  - Si Δrho > +0.05 → enrichissement vaut le coup, continuer
  - Si Δrho < +0.02 → features non discriminantes, MenthorQ Gold pipeline obligatoire
  - Si Δrho négatif → overfit ou features bruit, audit individuel

Usage : python -X utf8 CORE/research/compare_gold_edge_baseline_vs_enriched.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
import numpy as np
import lightgbm as lgb
from scipy.stats import spearmanr

BASELINE = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_session.parquet"
ENRICHED = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_enriched.parquet"
OUTPUT_DIR = ROOT / "DATA" / "BACKTEST" / "GOLD"

TICK_SIZE = 0.10
FWD_WINDOW = 30
P_LONG = 0.90
P_SHORT = 0.10

LEAK = {"close", "open", "high", "low", "close_fwd30", "atr_for_norm",
        "ts_event", "ts_recv", "target",
        "cvd_session", "cvd_day", "delta_day", "delta_session",
        "session_date", "session_date_trading", "_date", "vix_level"}


def prepare(df):
    df = df.copy()
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


def train_and_eval(df, features, label):
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

    p_long_val = np.quantile(y_pred, P_LONG)
    p_short_val = np.quantile(y_pred, P_SHORT)
    long_targets = y_test[y_pred >= p_long_val]
    short_targets = y_test[y_pred <= p_short_val]
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
        "n_train": len(df_train),
        "n_test": len(df_test),
        "n_features": len(features),
        "r2": r2,
        "rho": rho,
        "pval": pval,
        "edge_long": edge_long,
        "edge_short": edge_short,
        "edge_combined": edge_combined,
        "n_long_signals": len(long_targets),
        "n_short_signals": len(short_targets),
        "top10": importance.head(10),
    }


def main():
    print(f"=== COMPARAISON BASELINE vs ENRICHI ===\n")

    if not BASELINE.exists():
        print(f"  ERREUR : baseline absent {BASELINE}")
        return
    if not ENRICHED.exists():
        print(f"  ERREUR : enrichi absent {ENRICHED}")
        print(f"    Run d'abord : python CORE/research/enrich_gold_dataset_full.py")
        return

    print(f"  Loading baseline {BASELINE}...")
    df_b = pd.read_parquet(BASELINE)
    df_b, feat_b = prepare(df_b)
    print(f"    Shape : {df_b.shape}, features : {len(feat_b)}")

    print(f"\n  Loading enrichi {ENRICHED}...")
    df_e = pd.read_parquet(ENRICHED)
    df_e, feat_e = prepare(df_e)
    print(f"    Shape : {df_e.shape}, features : {len(feat_e)}")

    print(f"\n--- Training BASELINE ---")
    res_b = train_and_eval(df_b, feat_b, "BASELINE (V5e session)")

    print(f"\n--- Training ENRICHI ---")
    res_e = train_and_eval(df_e, feat_e, "ENRICHI (V5e + Phase D + extra)")

    print(f"\n\n=== RESULTATS COMPARAISON ===\n")
    print(f"  Metric{'':<25}{res_b['label']:<35}{res_e['label']:<35}Delta")
    print("  " + "-" * 110)
    for metric in ["n_features", "r2", "rho", "edge_long", "edge_short", "edge_combined"]:
        v_b = res_b[metric]
        v_e = res_e[metric]
        delta = v_e - v_b
        marker = "[+]" if delta > 0 else "[-]"
        if isinstance(v_b, float):
            print(f"  {metric:<32}{v_b:>15.4f}{'':<20}{v_e:>15.4f}{'':<20}{marker} {delta:+.4f}")
        else:
            print(f"  {metric:<32}{v_b:>15}{'':<20}{v_e:>15}{'':<20}{marker} {delta:+}")

    print(f"\n=== TOP 10 FEATURES BASELINE ===")
    print(res_b["top10"].to_string(index=False))

    print(f"\n=== TOP 10 FEATURES ENRICHI ===")
    print(res_e["top10"].to_string(index=False))

    delta_rho = res_e["rho"] - res_b["rho"]
    delta_edge = res_e["edge_combined"] - res_b["edge_combined"]

    print(f"\n=== VERDICT ===")
    print(f"  Δrho : {delta_rho:+.4f}")
    print(f"  Δedge_combined : {delta_edge:+.4f} ATR")

    if delta_rho > 0.05:
        verdict = "GO — features enrichies apportent significant uplift, continuer walk-forward + DSR"
    elif delta_rho > 0.02:
        verdict = "MARGINAL — uplift modeste, consider MenthorQ Gold pipeline aussi"
    elif delta_rho > -0.005:
        verdict = "NEUTRAL — pas d'uplift, features intermarket peu discriminantes, MenthorQ Gold obligatoire"
    else:
        verdict = "NEGATIVE — features ajoutent du bruit, audit individuel + drop des moins utiles"
    print(f"  {verdict}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    import json
    summary = {
        "baseline": {k: v for k, v in res_b.items() if k != "top10"},
        "enriched": {k: v for k, v in res_e.items() if k != "top10"},
        "delta_rho": delta_rho,
        "delta_edge_combined": delta_edge,
        "verdict": verdict,
    }
    (OUTPUT_DIR / "gold_edge_comparison.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )
    res_b["top10"].to_csv(OUTPUT_DIR / "gold_top10_baseline.csv", index=False)
    res_e["top10"].to_csv(OUTPUT_DIR / "gold_top10_enriched.csv", index=False)
    print(f"\n  Saved : {OUTPUT_DIR}/gold_edge_comparison.json")


if __name__ == "__main__":
    main()
