"""train_dmp_v2_quick.py — Test ML rapide sur DMP v2 dataset (Sierra Chart).

Created : 2026-05-02 dimanche soir post-V5 NO-GO + post-analyse Bot 1/Bot 2.
Hypothese Jackson : Bot 1 (DMP) WR 40.5% > Bot 2 (Databento V4) WR 23.8%
                    sur 5 jours paper => DMP brut peut avoir un edge ML
                    que V4/V5 Databento n'ont pas detecte.

Pipeline :
  1. Load ES_dataset_v2 + NQ_dataset_v2 (DMP-only, 75 jours, 281 features)
  2. Convert labels {-1,0,+1} en y_binary par cote (buy=1, sell=-1)
  3. Walk-forward purged k-fold 5 splits + embargo 60 bars
  4. Train 4 LightGBM binary models (ES_buy, ES_sell, NQ_buy, NQ_sell)
  5. Metrics par fold : AUC, PF, WR, EV/trade
  6. Verdict GO/NO-GO seuils Lopez

Run A : v2 entier (37k bars ES, 35k bars NQ, 75j) — Lopez minimum
Run B (si A non-NO-GO) : v2 filtre >= 17/04 (~3-5k bars) — data propre
"""
from __future__ import annotations
import sys
import time
import warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

import lightgbm as lgb
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "DATA" / "DATASETS"

# Cols meta a exclure des features
META_COLS = {"ts", "sym", "label", "div_forward_return_20b", "price"}

# Features mortes documentees memory feedback_dumper_live_validated_20260415.md
DEAD_FEATURES = {
    "delta_divergence",      # mort jusqu'au 07/04
    "bn_volume_up", "bn_volume_dn",
    "bar_long_dn_up", "bar_long_up_dn",  # Extension Lines off ES
}


def load_dataset(symbol: str) -> pd.DataFrame:
    fp = DATA / f"{symbol}_dataset_v2.parquet"
    df = pd.read_parquet(fp)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def get_feature_cols(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        if c in META_COLS or c in DEAD_FEATURES:
            continue
        if not pd.api.types.is_numeric_dtype(df[c]):
            continue
        # Exclude quasi-constants
        if df[c].nunique(dropna=True) < 2:
            continue
        cols.append(c)
    return cols


def prepare_binary(df: pd.DataFrame, side: str) -> tuple[pd.DataFrame, np.ndarray]:
    """side='buy' -> y=1 si label==+1; side='sell' -> y=1 si label==-1."""
    target_label = 1 if side == "buy" else -1
    df = df.copy()
    df["y_binary"] = (df["label"] == target_label).astype(int)
    return df, df["y_binary"].values


def purged_kfold_splits(n: int, n_splits: int = 5, embargo: int = 60) -> list[tuple[np.ndarray, np.ndarray]]:
    """Walk-forward expanding window + embargo (Lopez ch.7)."""
    fold_size = n // (n_splits + 1)
    splits = []
    for i in range(n_splits):
        train_end = fold_size * (i + 1)
        test_start = train_end + embargo
        test_end = min(test_start + fold_size, n)
        if test_end - test_start < 100:
            continue
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        splits.append((train_idx, test_idx))
    return splits


def compute_pf(returns: np.ndarray) -> float:
    pos = returns[returns > 0].sum()
    neg = -returns[returns < 0].sum()
    return float(pos / neg) if neg > 1e-9 else (999.0 if pos > 0 else 0.0)


def train_eval_one_side(df: pd.DataFrame, sym: str, side: str,
                          feature_cols: list[str], n_splits: int = 5,
                          embargo: int = 60, threshold: float = 0.5) -> dict:
    df_prep, y = prepare_binary(df, side)
    n = len(df_prep)
    splits = purged_kfold_splits(n, n_splits=n_splits, embargo=embargo)
    fold_aucs, fold_pfs, fold_wrs, fold_ntrades, fold_ev = [], [], [], [], []
    all_returns = []

    for fold_idx, (tr, te) in enumerate(splits):
        X_tr = df_prep[feature_cols].iloc[tr].fillna(0).astype(np.float32).values
        y_tr = y[tr]
        X_te = df_prep[feature_cols].iloc[te].fillna(0).astype(np.float32).values
        y_te = y[te]

        # Skip si fold deg
        if len(set(y_tr)) < 2 or len(set(y_te)) < 2:
            continue

        model = lgb.LGBMClassifier(
            objective="binary", metric="auc",
            learning_rate=0.05, num_leaves=31, max_depth=-1,
            min_data_in_leaf=20, n_estimators=200, n_jobs=-1, verbose=-1,
            force_col_wise=True,
        )
        model.fit(X_tr, y_tr)
        proba = model.predict_proba(X_te)[:, 1]

        try:
            auc = roc_auc_score(y_te, proba)
        except ValueError:
            auc = np.nan

        # Trades = quand proba > threshold. Return = forward 20-bar return existant
        triggers = proba > threshold
        n_trades = int(triggers.sum())
        if "div_forward_return_20b" in df_prep.columns and n_trades >= 5:
            fwd = df_prep["div_forward_return_20b"].iloc[te].values
            # Pour SELL : retourne inversee (short = profit si retour negatif)
            sign = 1 if side == "buy" else -1
            r = fwd[triggers] * sign
            r = r[~np.isnan(r)]
            if len(r) >= 5:
                pf = compute_pf(r)
                wr = float((r > 0).mean())
                ev = float(r.mean())
                fold_pfs.append(pf)
                fold_wrs.append(wr)
                fold_ntrades.append(n_trades)
                fold_ev.append(ev)
                all_returns.extend(r.tolist())
        fold_aucs.append(auc)

    return {
        "sym": sym, "side": side,
        "n_folds": len(fold_aucs),
        "n_total_bars": n,
        "fold_aucs": fold_aucs,
        "fold_pfs": fold_pfs,
        "fold_wrs": fold_wrs,
        "fold_ntrades": fold_ntrades,
        "fold_ev": fold_ev,
        "all_returns": all_returns,
        "mean_auc": float(np.nanmean(fold_aucs)) if fold_aucs else np.nan,
        "mean_pf": float(np.nanmean(fold_pfs)) if fold_pfs else np.nan,
        "median_pf": float(np.nanmedian(fold_pfs)) if fold_pfs else np.nan,
        "mean_wr": float(np.nanmean(fold_wrs)) if fold_wrs else np.nan,
        "total_trades": int(sum(fold_ntrades)) if fold_ntrades else 0,
    }


def verdict(result: dict) -> str:
    """GO/MARGINAL/NO-GO selon seuils Lopez et CLAUDE.md."""
    pf = result.get("median_pf", np.nan)
    auc = result.get("mean_auc", np.nan)
    wr = result.get("mean_wr", np.nan)
    n_trades = result.get("total_trades", 0)
    if pd.isna(pf) or n_trades < 30:
        return "INSUFFICIENT_DATA"
    if pf >= 1.5 and auc >= 0.55 and wr >= 0.45 and n_trades >= 100:
        return "GO_STRONG"
    if pf >= 1.3 and auc >= 0.53:
        return "GO_MARGINAL"
    if pf >= 1.1:
        return "MARGINAL"
    return "NO-GO"


def print_summary(results: list[dict], run_label: str):
    print(f"\n{'=' * 70}")
    print(f"RUN {run_label} — VERDICT FINAL")
    print(f"{'=' * 70}")
    print(f"{'Combo':14} | {'N bars':>8} | {'Folds':>5} | {'AUC':>5} | "
          f"{'PF med':>7} | {'WR':>5} | {'Trades':>6} | Verdict")
    print("-" * 90)
    for r in results:
        v = verdict(r)
        n_bars = r.get("n_total_bars", 0)
        print(f"{r['sym']}_{r['side']:5} | {n_bars:>8} | "
              f"{r.get('n_folds',0):>5} | "
              f"{r.get('mean_auc', np.nan):>5.3f} | "
              f"{r.get('median_pf', np.nan):>7.2f} | "
              f"{r.get('mean_wr', np.nan):>5.1%} | "
              f"{r.get('total_trades', 0):>6} | {v}")


def run_train(label: str, df_es: pd.DataFrame, df_nq: pd.DataFrame, embargo: int = 60):
    print(f"\n[Run {label}] ES bars : {len(df_es)} | NQ bars : {len(df_nq)}")

    feature_cols_es = get_feature_cols(df_es)
    feature_cols_nq = get_feature_cols(df_nq)
    print(f"[Run {label}] Features ES : {len(feature_cols_es)} | NQ : {len(feature_cols_nq)}")

    results = []
    for sym, df, fcols in [("ES", df_es, feature_cols_es), ("NQ", df_nq, feature_cols_nq)]:
        for side in ["buy", "sell"]:
            t0 = time.time()
            r = train_eval_one_side(df, sym, side, fcols, n_splits=5, embargo=embargo)
            elapsed = time.time() - t0
            print(f"  {sym}_{side.upper()}: AUC={r['mean_auc']:.3f} PF_med={r['median_pf']:.2f} "
                  f"WR={r['mean_wr']:.1%} N_tr={r['total_trades']} "
                  f"folds={r['n_folds']} time={elapsed:.0f}s")
            results.append(r)

    print_summary(results, label)
    return results


def main():
    print("=" * 70)
    print("TRAIN ML DMP v2 — Test pre-refacto Bot 2 (post V5 NO-GO)")
    print("=" * 70)

    # ─── LOAD ────────────────────────────────────────────────
    print("\n[load] Loading datasets v2...")
    df_es = load_dataset("ES")
    df_nq = load_dataset("NQ")
    print(f"  ES : {df_es.shape} | period {df_es['ts'].min()} -> {df_es['ts'].max()}")
    print(f"  NQ : {df_nq.shape} | period {df_nq['ts'].min()} -> {df_nq['ts'].max()}")

    # ─── RUN A : v2 entier (75 jours, max data) ──────────────
    print(f"\n{'#' * 70}")
    print(f"# RUN A : v2 ENTIER (75 jours, ~37k bars) — max data Lopez")
    print(f"{'#' * 70}")
    res_a = run_train("A", df_es, df_nq, embargo=60)

    # ─── DECISION RUN B ─────────────────────────────────────
    has_signal_a = any(verdict(r) in ("GO_STRONG", "GO_MARGINAL", "MARGINAL") for r in res_a)

    if has_signal_a:
        print(f"\n{'#' * 70}")
        print(f"# RUN A montre signal -> RUN B : verif data PROPRE >= 17/04")
        print(f"{'#' * 70}")
        cutoff = pd.Timestamp("2026-04-17", tz="UTC")
        df_es_clean = df_es[df_es["ts"] >= cutoff].reset_index(drop=True)
        df_nq_clean = df_nq[df_nq["ts"] >= cutoff].reset_index(drop=True)
        if len(df_es_clean) >= 1000 and len(df_nq_clean) >= 1000:
            res_b = run_train("B", df_es_clean, df_nq_clean, embargo=20)
        else:
            print(f"  Trop peu de bars >= 17/04 (ES {len(df_es_clean)}, NQ {len(df_nq_clean)}), Run B skip")
    else:
        print(f"\n{'#' * 70}")
        print(f"# RUN A NO-GO clair -> Run B inutile")
        print(f"{'#' * 70}")

    print("\nDONE")


if __name__ == "__main__":
    main()
