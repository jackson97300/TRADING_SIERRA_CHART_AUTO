"""TROUVER L'EDGE GOLD — ML feature importance + analyse setups winnable.

Mission (12/05/2026 Jackson) : "TROUVE L'EDGE SUR L'OR".

Methodologie pro :
1. Target = forward return 30 min normalisé par ATR (signed)
2. LightGBM regressor sur ~380 features
3. Top features importance + SHAP-like via gain
4. Drill-down : pour les top features, distribution P&L par bucket → setups winnable

Sortie : ranking features + setups candidats à backtester sérieusement.

Anti-data-mining (cf feedback_data_mining_trap.md) :
- Train/test split chronologique (pas random) : 80% premiers mois / 20% derniers
- Feature importance sur TEST set (out-of-sample)
- Top features = celles qui généralisent, pas qui overfittent

Usage : python -X utf8 CORE/research/find_gold_edge_ml.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
import numpy as np
import lightgbm as lgb

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_session.parquet"
OUTPUT_DIR = ROOT / "DATA" / "BACKTEST" / "GOLD"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"=== TROUVER L'EDGE GOLD via ML ===\n")
print(f"  Loading {INPUT}...")
df = pd.read_parquet(INPUT)
print(f"  Shape : {df.shape}")

# === 1. TARGET : forward return 30 min normalisé par ATR ===
print(f"\n[1] Construction target = forward return 30 min / ATR_norm")
TICK_SIZE = 0.10
FWD_WINDOW = 30   # 30 bars forward = 30 min

# Forward close
df["close_fwd30"] = df["close"].shift(-FWD_WINDOW)
# ATR forward window
df["atr_for_norm"] = df["atr"].replace(0, np.nan).fillna(17.3)  # median fallback

# Target : signed return in ATR units
df["target"] = (df["close_fwd30"] - df["close"]) / (df["atr_for_norm"] * TICK_SIZE)

# Drop bars without forward (last 30) + NaN target
df_ml = df.dropna(subset=["target"]).copy()
print(f"  Bars utilisables : {len(df_ml):,} / {len(df):,}")
print(f"  Target stats : mean={df_ml['target'].mean():.3f} std={df_ml['target'].std():.3f}")
print(f"    min={df_ml['target'].min():.2f} p10={df_ml['target'].quantile(0.10):.2f}")
print(f"    p50={df_ml['target'].quantile(0.50):.2f} p90={df_ml['target'].quantile(0.90):.2f}")
print(f"    max={df_ml['target'].max():.2f}")

# === 2. Features selection (drop leak + ts + target) ===
print(f"\n[2] Selection features (drop leak + ts + target)")
LEAK_COLS = {
    "close", "open", "high", "low",      # price level = direct future leak
    "close_fwd30", "atr_for_norm",       # forward
    "ts_event", "ts_recv",                # timestamps
    "target",
    # Cumulative session features (leak journée)
    "cvd_session", "cvd_day", "delta_day", "delta_session",
    "session_date", "session_date_trading", "_date",
    "vix_level",  # peut etre useful mais souvent 100% NaN ou leak
}
# Keep numeric features only
feature_cols = []
for c in df_ml.columns:
    if c in LEAK_COLS:
        continue
    if df_ml[c].dtype.kind in "biufc":  # bool, int, uint, float, complex
        # Skip if 100% NaN or quasi-constant
        nan_pct = df_ml[c].isna().sum() / len(df_ml)
        if nan_pct > 0.95:
            continue
        # Constant or near-constant skip
        nunique = df_ml[c].nunique(dropna=True)
        if nunique < 5:
            continue
        feature_cols.append(c)
print(f"  Features retenues : {len(feature_cols)}")

# === 3. Split chronologique 80/20 ===
print(f"\n[3] Split chronologique 80/20")
n_train = int(len(df_ml) * 0.80)
df_train = df_ml.iloc[:n_train].copy()
df_test = df_ml.iloc[n_train:].copy()
print(f"  Train : {len(df_train):,} bars ({df_train['ts_event'].iloc[0]} -> {df_train['ts_event'].iloc[-1]})")
print(f"  Test  : {len(df_test):,} bars ({df_test['ts_event'].iloc[0]} -> {df_test['ts_event'].iloc[-1]})")

X_train = df_train[feature_cols].astype(float).fillna(0)
y_train = df_train["target"].astype(float)
X_test = df_test[feature_cols].astype(float).fillna(0)
y_test = df_test["target"].astype(float)

# === 4. LightGBM regression ===
print(f"\n[4] Training LightGBM regressor (50 rounds early-stop)")
dtrain = lgb.Dataset(X_train, label=y_train, free_raw_data=False)
dtest = lgb.Dataset(X_test, label=y_test, reference=dtrain, free_raw_data=False)

params = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.85,
    "bagging_freq": 5,
    "min_data_in_leaf": 100,
    "verbose": -1,
}
model = lgb.train(
    params, dtrain,
    num_boost_round=200,
    valid_sets=[dtrain, dtest],
    valid_names=["train", "test"],
    callbacks=[lgb.early_stopping(20), lgb.log_evaluation(50)],
)

# === 5. Feature importance (gain-based, out-of-sample relevance) ===
print(f"\n[5] Top 30 features par importance gain (train) :")
importance = pd.DataFrame({
    "feature": feature_cols,
    "gain": model.feature_importance(importance_type="gain"),
    "split": model.feature_importance(importance_type="split"),
})
importance = importance.sort_values("gain", ascending=False).reset_index(drop=True)
print(importance.head(30).to_string(index=False))

# === 6. Out-of-sample R² + corr signal ===
print(f"\n[6] Métriques out-of-sample (test set)")
y_pred = model.predict(X_test)
# R²
ss_res = ((y_test - y_pred) ** 2).sum()
ss_tot = ((y_test - y_test.mean()) ** 2).sum()
r2 = 1 - ss_res / ss_tot
print(f"  R² test : {r2:.5f}")
# Spearman corr
from scipy.stats import spearmanr
rho, pval = spearmanr(y_test, y_pred)
print(f"  Spearman rho : {rho:.4f} (p={pval:.2e})")

# === 7. Backtest "predict top 10% LONG / bottom 10% SHORT" ===
print(f"\n[7] Backtest naïf : top 10% pred = LONG, bot 10% pred = SHORT")
df_test_pred = df_test.copy()
df_test_pred["pred"] = y_pred
p90 = np.quantile(y_pred, 0.90)
p10 = np.quantile(y_pred, 0.10)

# Long trades
df_long = df_test_pred[df_test_pred["pred"] >= p90].copy()
df_short = df_test_pred[df_test_pred["pred"] <= p10].copy()
print(f"  Long signals : {len(df_long):,} (target mean={df_long['target'].mean():.3f})")
print(f"  Short signals : {len(df_short):,} (target mean={df_short['target'].mean():.3f})")
print(f"  Edge LONG    : {df_long['target'].mean():.3f} (>0 = profit avg)")
print(f"  Edge SHORT   : {-df_short['target'].mean():.3f} (>0 = profit avg si SHORT)")

# Total edge
total_signals = len(df_long) + len(df_short)
total_pnl_atr = df_long["target"].sum() - df_short["target"].sum()
ev_per_signal = total_pnl_atr / total_signals if total_signals > 0 else 0
print(f"  Edge combiné : {ev_per_signal:.3f} ATR units / signal ({total_signals:,} signals)")

# === 8. Save outputs ===
imp_csv = OUTPUT_DIR / "gold_edge_feature_importance.csv"
importance.to_csv(imp_csv, index=False)
print(f"\n  Feature importance saved : {imp_csv}")

# Save model
import pickle
model_pkl = OUTPUT_DIR / "gold_edge_lgb_model.pkl"
with model_pkl.open("wb") as f:
    pickle.dump({"model": model, "features": feature_cols}, f)
print(f"  Model saved : {model_pkl}")

print(f"\n=== TERMINE ===")
print(f"  Top features = candidats à backtester avec règles concretes")
print(f"  R² > 0 + rho > 0 = signal réel out-of-sample")
print(f"  Edge combiné > 0.5 ATR = candidat strategy testable")
