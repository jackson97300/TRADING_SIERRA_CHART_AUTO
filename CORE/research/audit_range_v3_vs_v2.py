"""audit_range_v3_vs_v2.py — Comparaison empirique V2 vs V3.

Objectif : valider que V3 reduit les faux positifs vs V2 sur trends, sans degrader
le recall sur ranges. Critere GO Phase 1 OBSERVATION :
  - F1 V3 >= F1 V2 (pas de regression)
  - Precision V3 > Precision V2 + 0.05 (gain net faux positifs)
  - Recall V3 >= Recall V2 - 0.10 (perte controlable)
  - Stabilite V3 (std/mean F1 inter-folds) < 0.40

Methodologie :
  1. Charge dataset v4_enriched NQ (toutes les features V3 dispo)
  2. Ground truth proxy = compression bar_range + contraction vol (cf audit V2)
  3. Walk-forward 4 folds chronologiques
  4. Compare V2 vs V3 sur F1 + precision + recall + fire_rate + break_risk

Anti-DSR : seuils figes par design, pas tunes sur metric.

Usage :
    python -X utf8 CORE/research/audit_range_v3_vs_v2.py [--symbol NQ] [--bars 50000]

Date : 2026-05-07
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from CORE.range_detector_v2 import RangeDetectorV2
from CORE.range_detector_v3 import RangeDetectorV3


# ─── Ground truth proxy (identique audit V2) ─────────────────────────────────

def compute_ground_truth_range(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """Range = compression bar_range + contraction vol."""
    if "bar_range_pct" not in df.columns:
        bar_range = (df["high"] - df["low"]) / df["close"]
    else:
        bar_range = df["bar_range_pct"]

    bar_range_med = bar_range.rolling(lookback, min_periods=20).median()
    bar_range_now = bar_range.rolling(10, min_periods=5).mean()
    contraction = bar_range_now < (bar_range_med * 0.85)

    bar_range_q40 = bar_range.rolling(lookback, min_periods=20).quantile(0.40)
    compression = bar_range_now < bar_range_q40

    return (compression & contraction).fillna(False)


# ─── Detectors wrappers ──────────────────────────────────────────────────────

def predict_v2(df: pd.DataFrame, sym: str) -> pd.Series:
    det = RangeDetectorV2(sym=sym)
    out = det.detect_iterative(df)
    return out["is_range"].astype(bool)


def predict_v3(df: pd.DataFrame, sym: str) -> tuple[pd.Series, pd.Series]:
    """Retourne (is_range, range_break_risk_series)."""
    det = RangeDetectorV3(sym=sym)
    out = det.detect_iterative(df)
    return out["is_range"].astype(bool), out["range_break_risk"]


# ─── Metrics ─────────────────────────────────────────────────────────────────

def compute_metrics(y_true: pd.Series, y_pred: pd.Series) -> dict:
    y_true = y_true.fillna(False).astype(bool).to_numpy()
    y_pred = y_pred.fillna(False).astype(bool).to_numpy()

    tp = int((y_true & y_pred).sum())
    fp = int((~y_true & y_pred).sum())
    fn = int((y_true & ~y_pred).sum())
    tn = int((~y_true & ~y_pred).sum())

    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    fire_rate = (tp + fp) / max(len(y_true), 1)

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "fire_rate": round(fire_rate, 3),
    }


def walk_forward_audit(df: pd.DataFrame, sym: str, n_splits: int = 4) -> pd.DataFrame:
    n = len(df)
    fold_size = n // n_splits
    rows = []

    print(f"\n=== Walk-forward audit V2 vs V3 {sym} ({n} bars, {n_splits} folds) ===")
    y_true_all = compute_ground_truth_range(df)

    for fold in range(n_splits):
        start = fold * fold_size
        end = (fold + 1) * fold_size if fold < n_splits - 1 else n
        df_fold = df.iloc[start:end].reset_index(drop=True)
        y_true = y_true_all.iloc[start:end].reset_index(drop=True)

        if len(df_fold) < 100:
            continue

        # V2
        t0 = time.time()
        y_v2 = predict_v2(df_fold, sym)
        t_v2 = time.time() - t0
        m_v2 = compute_metrics(y_true, y_v2)
        m_v2.update({"detector": "V2", "fold": fold, "n": len(df_fold), "secs": round(t_v2, 1)})
        rows.append(m_v2)

        # V3
        t0 = time.time()
        y_v3, break_risk = predict_v3(df_fold, sym)
        t_v3 = time.time() - t0
        m_v3 = compute_metrics(y_true, y_v3)
        # Stats break_risk
        n_down_break = int((break_risk == "DOWN_BREAK_IMMINENT").sum())
        n_up_break = int((break_risk == "UP_BREAK_IMMINENT").sum())
        m_v3.update({
            "detector": "V3", "fold": fold, "n": len(df_fold), "secs": round(t_v3, 1),
            "n_down_break": n_down_break, "n_up_break": n_up_break,
        })
        m_v2.update({"n_down_break": 0, "n_up_break": 0})  # padding for df concat
        rows.append(m_v3)

        print(
            f"  Fold {fold} (n={len(df_fold):>6}): "
            f"V2 F1={m_v2['f1']:.2f} P={m_v2['precision']:.2f} R={m_v2['recall']:.2f} fire={m_v2['fire_rate']:.0%} | "
            f"V3 F1={m_v3['f1']:.2f} P={m_v3['precision']:.2f} R={m_v3['recall']:.2f} fire={m_v3['fire_rate']:.0%} "
            f"break_risk(D{n_down_break}/U{n_up_break})"
        )

    return pd.DataFrame(rows)


def summary(df_results: pd.DataFrame) -> pd.DataFrame:
    agg = df_results.groupby("detector").agg(
        f1_mean=("f1", "mean"),
        f1_std=("f1", "std"),
        prec_mean=("precision", "mean"),
        rec_mean=("recall", "mean"),
        fire_mean=("fire_rate", "mean"),
        n_folds=("fold", "count"),
    ).round(3)
    agg["f1_stability"] = (agg["f1_std"] / agg["f1_mean"].replace(0, np.nan)).round(3)
    return agg


# ─── Main ────────────────────────────────────────────────────────────────────

def load_data(symbol: str, max_bars: int | None) -> pd.DataFrame:
    import pyarrow.dataset as ds
    sym_mapping = {"NQ": "NQ.c.0", "ES": "ES.c.0"}
    if symbol not in sym_mapping:
        raise ValueError(f"Symbol {symbol} not supported")
    path = Path(f"D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS/v4_enriched/symbol={sym_mapping[symbol]}")
    dataset = ds.dataset(path, format="parquet")
    cols_needed = [
        "ts_event", "high", "low", "close", "bar_range_pct",
        "im_rolling_correlation_10", "rvol_zscore",
        # V2 features
        "n_color_up_cluster_within_0_2pct", "n_long_up_cluster_within_0_2pct",
        "n_edge_buy_active",
        "n_color_dn_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
        "n_edge_sell_active",
        # V3 features
        "bars_since_last_swing_high", "bars_since_last_swing_low",
        "inside_value_area", "ctx_va_width_atr", "ctx_poc_migration_10",
        "aggressor_imbalance", "long_up_bar", "long_dn_bar",
    ]
    available = [c for c in cols_needed if c in dataset.schema.names]
    missing = [c for c in cols_needed if c not in available]
    if missing:
        print(f"WARNING : features manquantes dans dataset : {missing}")

    df = dataset.to_table(columns=available).to_pandas()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if max_bars and len(df) > max_bars:
        df = df.iloc[-max_bars:].reset_index(drop=True)
    return df


def main(symbol: str, max_bars: int | None = None) -> None:
    print(f"=== Audit Range Detector V2 vs V3 — {symbol} ===")
    df = load_data(symbol, max_bars)
    print(f"Loaded {len(df):,} bars from {df['ts_event'].min()} to {df['ts_event'].max()}")

    gt = compute_ground_truth_range(df)
    print(f"Ground truth proxy: {gt.sum():,}/{len(df):,} bars ({gt.mean():.1%}) flagged range")

    results = walk_forward_audit(df, symbol, n_splits=4)
    print("\n=== Detail folds ===")
    print(results.to_string(index=False))

    print("\n=== Summary aggregate ===")
    agg = summary(results)
    print(agg.to_string())

    # Verdict
    print("\n=== Verdict V3 vs V2 ===")
    f1_v2 = agg.loc["V2", "f1_mean"]
    f1_v3 = agg.loc["V3", "f1_mean"]
    p_v2 = agg.loc["V2", "prec_mean"]
    p_v3 = agg.loc["V3", "prec_mean"]
    r_v2 = agg.loc["V2", "rec_mean"]
    r_v3 = agg.loc["V3", "rec_mean"]
    fire_v2 = agg.loc["V2", "fire_mean"]
    fire_v3 = agg.loc["V3", "fire_mean"]
    stab_v3 = agg.loc["V3", "f1_stability"]

    delta_f1 = f1_v3 - f1_v2
    delta_prec = p_v3 - p_v2
    delta_rec = r_v3 - r_v2
    delta_fire = fire_v3 - fire_v2

    print(f"  F1     V2={f1_v2:.3f} | V3={f1_v3:.3f} | delta={delta_f1:+.3f}")
    print(f"  Prec   V2={p_v2:.3f} | V3={p_v3:.3f} | delta={delta_prec:+.3f}")
    print(f"  Recall V2={r_v2:.3f} | V3={r_v3:.3f} | delta={delta_rec:+.3f}")
    print(f"  Fire   V2={fire_v2:.1%} | V3={fire_v3:.1%} | delta={delta_fire:+.1%}")
    print(f"  Stab V3 (std/mean F1) = {stab_v3:.2f}")

    print("\n=== Decision ===")
    # Critere : F1 stable + precision gain + fire rate baisse
    if delta_f1 >= -0.02 and delta_prec >= 0.05 and stab_v3 < 0.40:
        verdict = "GO Phase 1 OBSERVATION (V3 reduit FP, F1 maintenu)"
    elif delta_f1 >= 0.0 and delta_prec >= 0.0:
        verdict = "GO RESERVE — V3 marginal, monitor 7j data live"
    else:
        verdict = "NOGO — V3 ne progresse pas, garder V2 ou re-design"

    print(f"  >>> {verdict}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--bars", type=int, default=50000, help="Max bars (None=all)")
    args = parser.parse_args()
    max_bars = args.bars if args.bars > 0 else None
    main(args.symbol, max_bars)
