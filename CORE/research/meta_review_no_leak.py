"""Test meta-labeling NQ_buy v5d en retirant les features POTENTIELLEMENT leaky.

Le bug : `day_type` est calcule via sess_high/sess_low FINAUX (fin de journee) et
broadcast sur toute la journee. Idem open_type est calcule a 10:30 ET.

Test : retirer day_type, voir si l'edge survit avec features safe.
Test 2 : ne garder que p_primary + im_*, voir si l'edge meta vient des im_*.
"""
from __future__ import annotations
import json
import pickle
import time
from pathlib import Path

import numba
import numpy as np
import pandas as pd
from scipy.stats import skew as _sk, kurtosis as _ku, norm

ROOT = Path(__file__).resolve().parents[2]


@numba.njit(cache=True)
def sim_buy(highs, lows, closes, atrs, k_sl, k_tp_ratio, h, tick, cost):
    n = len(closes)
    pnl = np.zeros(n, dtype=np.float64)
    for i in range(n - h - 1):
        atr_t = atrs[i]
        if atr_t <= 0 or np.isnan(atr_t):
            continue
        sl_t = k_sl * atr_t
        tp_t = k_tp_ratio * sl_t
        e = closes[i]
        sl_l = e - sl_t * tick
        tp_l = e + tp_t * tick
        out = 0.0
        hit = False
        for k in range(1, h + 1):
            j = i + k
            if j >= n:
                break
            if lows[j] <= sl_l:
                out = -sl_t - cost
                hit = True
                break
            if highs[j] >= tp_l:
                out = tp_t - cost
                hit = True
                break
        if not hit:
            j = i + h
            if j < n:
                out = (closes[j] - e) / tick - cost
            else:
                out = -cost
        pnl[i] = out
    return pnl


def metrics(pnl):
    nz = pnl[pnl != 0]
    if len(nz) == 0:
        return dict(n=0, wr=0, pf=0, ev=0, sharpe=0, dd=0)
    wins = nz[nz > 0]
    losses = nz[nz < 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    return dict(
        n=len(nz),
        wr=len(wins) / len(nz),
        pf=float(pf),
        ev=float(nz.mean()),
        sharpe=float(nz.mean() / nz.std() * np.sqrt(252)) if nz.std() > 0 else 0.0,
        dd=float(np.max(np.maximum.accumulate(np.cumsum(nz)) - np.cumsum(nz))),
    )


def run_meta(df, primary_model, primary_features, primary_threshold,
             pnl_test, meta_features_list, label_col, train_test_idx, label_name):
    """Run meta-labeling experiment with given meta features list."""
    purge_train_end, split_idx = train_test_idx
    df_train = df.iloc[:purge_train_end].reset_index(drop=True)
    df_test = df.iloc[split_idx:].reset_index(drop=True)
    pnl_test_local = pnl_test[split_idx:]

    primary_features_avail = [f for f in primary_features if f in df.columns]
    for m in set(primary_features) - set(primary_features_avail):
        df[m] = 0
        df_train[m] = 0
        df_test[m] = 0
    primary_features_avail = primary_features

    X_train = df_train[primary_features_avail].fillna(0)
    X_test = df_test[primary_features_avail].fillna(0)
    p_primary_train = primary_model.predict_proba(X_train)[:, 1]
    p_primary_test = primary_model.predict_proba(X_test)[:, 1]

    label_train = df_train["label"].astype(np.int8)
    primary_active = p_primary_train > primary_threshold
    correct = label_train.values == 1
    y_meta_train = pd.Series(np.where(primary_active, correct.astype(float), np.nan),
                              index=df_train.index, name="meta_label", dtype=np.float64)

    avail_meta = [f for f in meta_features_list if f in df.columns]
    print(f"  Meta features used : {avail_meta}")

    X_meta_train = df_train[avail_meta].copy().fillna(0)
    X_meta_train["p_primary"] = p_primary_train
    X_meta_test = df_test[avail_meta].copy().fillna(0)
    X_meta_test["p_primary"] = p_primary_test

    mask = ~y_meta_train.isna()
    X = X_meta_train.loc[mask].copy()
    y = y_meta_train.loc[mask].astype(int).values
    sw_train = df_train["sample_weight"].values[mask.values] if "sample_weight" in df_train.columns else None

    import lightgbm as lgb
    params = dict(objective="binary", metric="binary_logloss", boosting_type="gbdt",
                   verbosity=-1, seed=42, num_leaves=15, max_depth=4, learning_rate=0.05,
                   n_estimators=200, min_child_samples=20, subsample=0.8,
                   colsample_bytree=0.8, reg_alpha=0.1, reg_lambda=0.1, is_unbalance=True)
    meta = lgb.LGBMClassifier(**params)
    meta.fit(X, y, sample_weight=sw_train)

    p_meta_test = meta.predict_proba(X_meta_test)[:, 1]
    primary_signal_test = p_primary_test > primary_threshold

    print(f"\n  [{label_name}] meta_thr   N      WR%   PF    EV    Sharpe  DD")
    for thr in [0.40, 0.45, 0.50, 0.55, 0.60]:
        sig = primary_signal_test & (p_meta_test > thr)
        m = metrics(pnl_test_local[sig])
        print(f"           {thr:.2f}  {m['n']:6d}  {m['wr']*100:5.1f} {m['pf']:5.2f} {m['ev']:+6.1f}  {m['sharpe']:+6.2f}  {m['dd']:6.0f}")

    # Feature importance
    fi = pd.DataFrame({"feature": list(X.columns), "imp": meta.feature_importances_})
    fi = fi.sort_values("imp", ascending=False)
    print(f"\n  [{label_name}] Top features (importance) :")
    print(fi.head(10).to_string(index=False))


def main():
    print("=" * 100)
    print("  META-LABELING NQ BUY — Test data leak isolation")
    print("=" * 100)

    primary_path = ROOT / "DATA/MODELS/BASELINE_27042026/NQ_buy_v5d_model.pkl"
    config_path = ROOT / "DATA/MODELS/BASELINE_27042026/NQ_buy_v5d_pf159_no.json"
    with open(primary_path, "rb") as f:
        primary_model = pickle.load(f)
    with open(config_path, "r") as f:
        config = json.load(f)
    primary_features = config["features"]
    primary_threshold = config["threshold"]

    df = pd.read_parquet(ROOT / "DATA/datasets/NQ_dataset_v5d.parquet")
    if "mins_et" in df.columns:
        df = df[(df["mins_et"] >= 570) & (df["mins_et"] <= 960)].copy()
    df = df.sort_values("ts").reset_index(drop=True)
    print(f"\nRTH bars : {len(df):,}")

    closes = df["close"].values.astype(np.float64) if "close" in df.columns else df["price"].values.astype(np.float64)
    highs = df["high"].values.astype(np.float64) if "high" in df.columns else closes
    lows = df["low"].values.astype(np.float64) if "low" in df.columns else closes
    atrs = df["atr"].values.astype(np.float64)
    pnl_all = sim_buy(highs, lows, closes, atrs, 1.5, 2.0, 60, 0.25, 0.5)

    n = len(df)
    split_idx = int(n * 0.7)
    purge_train_end = split_idx - 60
    train_test_idx = (purge_train_end, split_idx)

    # Experiment 1 : ALL features (replication baseline annoncé)
    print("\n" + "=" * 100)
    print("  EXP 1 — Baseline replication (ALL meta features incl. day_type LEAKY)")
    print("=" * 100)
    META_ALL = ["open_type", "open_bias_conf", "day_type",
                "im_rolling_correlation_10", "im_cross_delta_agreement_5",
                "im_open_type_agreement", "ib_range_atr", "is_in_us_after"]
    run_meta(df.copy(), primary_model, primary_features, primary_threshold,
             pnl_all, META_ALL, "label",
             train_test_idx, "ALL_FEATURES")

    # Experiment 2 : SANS day_type (le plus leaky)
    print("\n" + "=" * 100)
    print("  EXP 2 — SANS day_type (utilise sess_high/low finaux = leak pur)")
    print("=" * 100)
    META_NO_DAYTYPE = ["open_type", "open_bias_conf",
                       "im_rolling_correlation_10", "im_cross_delta_agreement_5",
                       "im_open_type_agreement", "ib_range_atr", "is_in_us_after"]
    run_meta(df.copy(), primary_model, primary_features, primary_threshold,
             pnl_all, META_NO_DAYTYPE, "label",
             train_test_idx, "NO_DAYTYPE")

    # Experiment 3 : SANS day_type ET SANS open_type (open_type fixe a 10:30 + price_1030 deja "future")
    print("\n" + "=" * 100)
    print("  EXP 3 — SANS day_type ET sans open_type (price_1030 = futur pour bars < 10:30)")
    print("=" * 100)
    META_NO_OPENDAY = ["open_bias_conf",
                       "im_rolling_correlation_10", "im_cross_delta_agreement_5",
                       "im_open_type_agreement", "ib_range_atr", "is_in_us_after"]
    run_meta(df.copy(), primary_model, primary_features, primary_threshold,
             pnl_all, META_NO_OPENDAY, "label",
             train_test_idx, "NO_OPEN_DAY")

    # Experiment 4 : SEUL p_primary + im_* (les im_* ne sont pas leak)
    print("\n" + "=" * 100)
    print("  EXP 4 — SEULES im_* + ib_range_atr + is_in_us_after (no game_changers leak)")
    print("=" * 100)
    META_SAFE = ["im_rolling_correlation_10", "im_cross_delta_agreement_5",
                 "im_open_type_agreement", "ib_range_atr", "is_in_us_after"]
    run_meta(df.copy(), primary_model, primary_features, primary_threshold,
             pnl_all, META_SAFE, "label",
             train_test_idx, "SAFE_ONLY")

    # Experiment 5 : SEUL p_primary
    print("\n" + "=" * 100)
    print("  EXP 5 — SEUL p_primary comme feature meta (test si meta = monotone primary)")
    print("=" * 100)
    META_PRIM_ONLY = []  # vide -> seul p_primary sera ajoute
    # On ne peut pas appeler run_meta avec liste vide, on cree un placeholder
    META_DUMMY = ["is_in_us_after"]  # 1 feature triviale
    run_meta(df.copy(), primary_model, primary_features, primary_threshold,
             pnl_all, META_DUMMY, "label",
             train_test_idx, "P_PRIMARY_ONLY")


if __name__ == "__main__":
    main()
