"""Bot 3 Meta-Labeler — Lopez de Prado AFML chapitre 3.

Architecture inverse du data mining trap :
    PRIMARY MODEL (rules-based) : 24 niveaux Bot 3 MP → genere signaux
    META MODEL (LightGBM)       : pour chaque signal primary, predit P(win)
                                  → filtre TAKE/SKIP

Le ML ne CHERCHE PAS d'edges. Il VALIDE/FILTRE des edges qu'on connait.

Usage :
    python -X utf8 CORE/research/bot3_meta_labeler.py --build-dataset
    python -X utf8 CORE/research/bot3_meta_labeler.py --train --symbol NQ
    python -X utf8 CORE/research/bot3_meta_labeler.py --train --symbol ES
    python -X utf8 CORE/research/bot3_meta_labeler.py --evaluate

Output :
    DATA/META_LABEL/bot3_meta_dataset_<symbol>.parquet
    DATA/MODELS/bot3_meta_<symbol>_model.pkl
    DATA/META_LABEL/bot3_meta_walkforward_<symbol>.csv
    DOCS/BOT3_META_LABELER_REPORT.md
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BACKTEST_DIR = ROOT / "DATA" / "BACKTEST" / "BOT3"
META_DIR = ROOT / "DATA" / "META_LABEL"
MODELS_DIR = ROOT / "DATA" / "MODELS"
META_DIR.mkdir(parents=True, exist_ok=True)

V4_BASE = ROOT / "DATA" / "DATASETS" / "v4_enriched"

# Features meta-labeler (max 30 anti-overfit)
META_FEATURES = [
    # Bot 3 trade-specific
    "confidence", "level_tier", "sl_ticks", "atr_multiplier",
    "rvol_at_entry", "vix_at_entry", "acceptance_score",
    # Regime macro Game Changers
    "open_type", "day_type", "profile_shape", "open_bias_conf",
    "trend_day_probability",
    # GEX regime (gamma walls)
    "mq_total_gex", "mq_gamma_condition", "mq_iv_30d",
    # Context structure
    "ctx_ib_extension_ratio", "ctx_poc_migration_10",
    "ctx_trend_day_score", "ctx_session_phase",
    # Volatility
    "atr_14m_pct", "rvol_zscore", "bar_range_pct",
    # Position structure (anti-leakage : abs distances at T close)
    "dist_ib_high_pct", "dist_ib_low_pct",
    # Session timing
    "bool_session_early", "time_to_session_close_norm",
    # Cross-instrument
    "im_rolling_correlation_10", "im_cross_delta_agreement_5",
    "im_open_type_agreement",
]

CATEGORICAL_FEATURES = [
    "level_tier", "open_type", "day_type", "profile_shape",
    "ctx_session_phase", "mq_gamma_condition",
]


def load_trades(symbol: str, run_id: str = "full_14m_v3") -> pd.DataFrame:
    """Charge trades JSONL Bot 3 backtest."""
    f = BACKTEST_DIR / f"trades_{symbol}_{run_id}.jsonl"
    rows = []
    with f.open(encoding="utf-8") as fp:
        for line in fp:
            rows.append(json.loads(line.strip()))
    df = pd.DataFrame(rows)
    df["entry_bar_ts"] = pd.to_datetime(df["entry_bar_ts"])
    df["label"] = (df["pnl_ticks_net"] > 0).astype(int)
    print(f"[{symbol}] {len(df)} trades, {df['label'].mean()*100:.1f}% wins")
    return df


def load_v4_features(symbol: str, ts_list: pd.Series) -> pd.DataFrame:
    """Charge features v4_enriched aux timestamps des trades."""
    sym_label = f"{symbol}.c.0"
    pattern = str(V4_BASE / f"symbol={sym_label}" / "**" / "*.parquet")

    available_cols_query = f"""
        SELECT * FROM read_parquet('{pattern.replace(chr(92), '/')}', hive_partitioning=true)
        LIMIT 1
    """
    con = duckdb.connect()
    sample = con.execute(available_cols_query).fetchdf()
    available = set(sample.columns)
    cols_to_load = [c for c in META_FEATURES if c in available]
    missing = [c for c in META_FEATURES if c not in available]
    if missing:
        print(f"[WARN] {len(missing)} features absentes v4: {missing[:5]}...")

    cols_select = ", ".join(["ts_event"] + cols_to_load)
    ts_min = pd.Timestamp(ts_list.min()).strftime("%Y-%m-%d")
    ts_max = pd.Timestamp(ts_list.max()).strftime("%Y-%m-%d")

    q = f"""
        SELECT {cols_select}
        FROM read_parquet('{pattern.replace(chr(92), '/')}', hive_partitioning=true)
        WHERE CAST(ts_event AS DATE) BETWEEN DATE '{ts_min}' AND DATE '{ts_max}'
    """
    df_v4 = con.execute(q).fetchdf()
    df_v4["ts_event"] = pd.to_datetime(df_v4["ts_event"]).dt.tz_localize(None)
    print(f"[{symbol}] v4_enriched : {len(df_v4)} rows, {len(cols_to_load)} features dispo")
    return df_v4


def build_dataset(symbol: str) -> pd.DataFrame:
    """Build dataset meta-label : trades + features context au T close."""
    trades = load_trades(symbol)
    df_v4 = load_v4_features(symbol, trades["entry_bar_ts"])

    # Anti-leakage : on prend les features AT T CLOSE (entry_bar_ts).
    # entry_bar_ts du backtest = bar de touch ; entry happens at T close.
    # v4_enriched ts_event = bar close ts. Donc match exact.

    # Normalisation tz : trades en naive (UTC), v4 en naive aussi
    if trades["entry_bar_ts"].dt.tz is not None:
        trades["entry_bar_ts"] = trades["entry_bar_ts"].dt.tz_localize(None)

    merged = trades.merge(
        df_v4, left_on="entry_bar_ts", right_on="ts_event", how="left"
    )

    n_unmatched = merged["ts_event"].isna().sum()
    print(f"[{symbol}] merge : {len(merged)} trades, {n_unmatched} unmatched ({n_unmatched/len(merged)*100:.1f}%)")

    # Drop unmatched (data missing)
    merged = merged.dropna(subset=["ts_event"]).reset_index(drop=True)

    out = META_DIR / f"bot3_meta_dataset_{symbol}.parquet"
    merged.to_parquet(out, index=False)
    print(f"[{symbol}] saved : {out} ({len(merged)} rows)")
    return merged


def walkforward_train(symbol: str, n_folds: int = 12, embargo_days: int = 1) -> dict:
    """Walk-forward purged 12-fold Lopez ch.7 + LightGBM meta-labeler."""
    try:
        import lightgbm as lgb
    except ImportError:
        print("ERROR: lightgbm not installed")
        return {}

    df = pd.read_parquet(META_DIR / f"bot3_meta_dataset_{symbol}.parquet")
    df = df.sort_values("entry_bar_ts").reset_index(drop=True)

    # Features dispo apres merge
    feats_avail = [c for c in META_FEATURES if c in df.columns]
    cats_avail = [c for c in CATEGORICAL_FEATURES if c in feats_avail]

    print(f"\n=== {symbol} walk-forward {n_folds} folds, embargo {embargo_days}d ===")
    print(f"Features used : {len(feats_avail)} ({len(cats_avail)} categorical)")

    # Encoding categorical
    df_x = df[feats_avail].copy()
    for c in cats_avail:
        df_x[c] = df_x[c].astype("category")
    y = df["label"].values
    pnl = df["pnl_ticks_net"].values

    # Split chronologique 12 folds
    n = len(df)
    fold_size = n // n_folds
    embargo_bars = int(embargo_days * 24 * 60)  # ~ 1 jour en bars 1m

    fold_results = []
    oos_preds_all = np.zeros(n)
    oos_mask_all = np.zeros(n, dtype=bool)

    for fold_idx in range(n_folds):
        test_start = fold_idx * fold_size
        test_end = (fold_idx + 1) * fold_size if fold_idx < n_folds - 1 else n

        # Embargo : exclure embargo_bars autour du test set du training
        train_idx = np.concatenate([
            np.arange(0, max(0, test_start - embargo_bars)),
            np.arange(min(n, test_end + embargo_bars), n)
        ])
        test_idx = np.arange(test_start, test_end)

        if len(train_idx) < 50 or len(test_idx) < 10:
            continue

        # Anti-leakage strict Lopez : val DOIT etre chronologique pre-test only.
        # Si train contient des indices post-test (folds intermediaires), les exclure
        # de val car threshold post-test = look-ahead bias.
        train_pre_test = train_idx[train_idx < test_start]
        if len(train_pre_test) < 100:
            # Fold trop tot, skip
            continue
        val_size = max(50, int(len(train_pre_test) * 0.2))
        train_idx_inner = np.concatenate([
            train_pre_test[:-val_size],
            train_idx[train_idx >= test_end]  # post-test data OK pour train (pas pour val)
        ])
        val_idx = train_pre_test[-val_size:]

        x_train = df_x.iloc[train_idx_inner]
        y_train = y[train_idx_inner]
        x_val = df_x.iloc[val_idx]
        y_val = y[val_idx]
        pnl_val = pnl[val_idx]

        x_test = df_x.iloc[test_idx]
        y_test = y[test_idx]
        pnl_test = pnl[test_idx]

        # LightGBM training avec val set pour early stopping
        train_set = lgb.Dataset(x_train, label=y_train, categorical_feature=cats_avail)
        val_set = lgb.Dataset(x_val, label=y_val, categorical_feature=cats_avail, reference=train_set)
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "min_data_in_leaf": 20,
            "verbose": -1,
            "seed": 42,
        }
        model = lgb.train(
            params, train_set, num_boost_round=200,
            callbacks=[lgb.early_stopping(20, verbose=False)],
            valid_sets=[val_set],
        )

        # Calibrer best_thr SUR VAL (pas sur test = anti-leakage)
        preds_val = model.predict(x_val)
        best_pf_val = 0.0
        best_thr = 0.5
        for thr in np.arange(0.3, 0.8, 0.05):
            mask_v = preds_val >= thr
            if mask_v.sum() < 5:
                continue
            wins_v = pnl_val[mask_v][pnl_val[mask_v] > 0].sum()
            losses_v = abs(pnl_val[mask_v][pnl_val[mask_v] < 0].sum())
            if losses_v > 0:
                pf_v = wins_v / losses_v
                if pf_v > best_pf_val:
                    best_pf_val = pf_v
                    best_thr = thr

        # Predict + apply threshold FIXE (calibre val) sur TEST
        preds = model.predict(x_test)
        oos_preds_all[test_idx] = preds
        oos_mask_all[test_idx] = True

        # PF brut (sans filtre)
        wins_brut = pnl_test[pnl_test > 0].sum()
        losses_brut = abs(pnl_test[pnl_test < 0].sum())
        pf_brut = wins_brut / losses_brut if losses_brut > 0 else 0

        # PF meta-filtered avec best_thr (calibre val)
        mask = preds >= best_thr
        if mask.sum() > 0 and pnl_test[mask][pnl_test[mask] < 0].sum() < 0:
            pf_meta = pnl_test[mask][pnl_test[mask] > 0].sum() / abs(pnl_test[mask][pnl_test[mask] < 0].sum())
        else:
            pf_meta = 0.0

        fold_results.append({
            "fold": fold_idx + 1,
            "n_train": len(train_idx_inner),
            "n_val": len(val_idx),
            "n_test": len(test_idx),
            "n_test_kept": int(mask.sum()),
            "kept_pct": round(mask.sum() / len(test_idx) * 100, 1),
            "best_thr_val": round(best_thr, 2),
            "pf_val": round(best_pf_val, 2),
            "pf_brut": round(pf_brut, 2),
            "pf_meta": round(pf_meta, 2),
            "pf_uplift": round(pf_meta - pf_brut, 2),
        })

    # Sauvegarde results
    df_folds = pd.DataFrame(fold_results)
    out_csv = META_DIR / f"bot3_meta_walkforward_{symbol}.csv"
    df_folds.to_csv(out_csv, index=False)
    print(f"\n{df_folds.to_string(index=False)}")

    # Stats globales
    pf_brut_med = df_folds["pf_brut"].median()
    pf_meta_med = df_folds["pf_meta"].median()
    n_uplift_pos = (df_folds["pf_uplift"] > 0).sum()
    print(f"\n{symbol} stats:")
    print(f"  PF brut median : {pf_brut_med:.2f}")
    print(f"  PF meta median : {pf_meta_med:.2f}")
    print(f"  Uplift folds   : {n_uplift_pos}/{len(df_folds)} positifs")

    # DSR Bailey 2014 sur PF meta
    if len(df_folds) >= 4:
        from statistics import median, stdev
        med = pf_meta_med
        std_pf = df_folds["pf_meta"].std()
        if std_pf > 0:
            sharpe = med / std_pf
            n_trials = 21  # 21 niveaux Bot 3
            gamma = 0.5772
            e_max = math.sqrt((1 - gamma) * math.sqrt(2 * math.log(n_trials))
                             + gamma * math.sqrt(2 * math.log(n_trials) - 1))
            z = (sharpe - e_max) / 1.0
            dsr = 0.5 * (1 + math.erf(z / math.sqrt(2)))
            print(f"  DSR (sharpe-based proxy): {dsr:.3f}")

    return {"folds": fold_results, "pf_brut_med": pf_brut_med, "pf_meta_med": pf_meta_med}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dataset", action="store_true")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--symbol", choices=["NQ", "ES", "BOTH"], default="BOTH")
    args = parser.parse_args()

    symbols = ["NQ", "ES"] if args.symbol == "BOTH" else [args.symbol]

    if args.build_dataset or args.all:
        for s in symbols:
            print(f"\n{'='*60}\n  BUILD DATASET {s}\n{'='*60}")
            build_dataset(s)

    if args.train or args.all:
        for s in symbols:
            print(f"\n{'='*60}\n  WALK-FORWARD TRAIN {s}\n{'='*60}")
            walkforward_train(s)


if __name__ == "__main__":
    main()
