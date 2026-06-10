"""audit_range_v2_vs_v1.py — Comparaison empirique V1 vs V3 COMBO vs V2.

Methodologie :
  1. Charge dataset v4_enriched (ES + NQ, 318 jours, ~350K bars)
  2. Definit un "ground truth" range proxy = bar_range_pct < median ET ADX < median
     (proxy heuristique, pas labelise par humain — limite mais consistent)
  3. Calcule predictions V1, V3 COMBO, V2 sur 4 splits chronologiques (walk-forward)
  4. Rapporte precision, recall, F1, fire rate, stabilite cross-folds

Anti-DSR : pas de selection de seuils sur le test set (hyperparams figes par design,
pas tunes sur metric). Les seuils V2 sont copies des canons web research (ADX 22,
Chop 60, atr_ratio 0.85). Si F1 V2 > F1 V1 ET stabilite folds < 30% relative range,
verdict GO Phase 1 OBSERVATION (pas decision trading).

Usage :
    python -X utf8 CORE/research/audit_range_v2_vs_v1.py [--symbol NQ] [--bars 50000]

Date : 2026-05-07
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Path resolution
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from CORE.range_detector import RangeDetector  # V1
from CORE.range_detector_v2 import RangeDetectorV2


# ─── Ground truth proxy ──────────────────────────────────────────────────────

def compute_ground_truth_range(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """Proxy range : bar_range_pct < quantile 40 ET volatility ratio < 0.9 sur lookback.

    Logique :
      - Une vraie "range" se caracterise par des bars individuelles plus petites que
        la mediane (compression) et une vol_now < vol_baseline (contraction).
      - Pas de labelisation humaine : on utilise un proxy data-driven qui devrait
        ETRE detecte par les criteres macro V2 (ADX/Chop/ATR).

    NB : ce proxy n'est PAS la verite absolue. Il sert uniquement a comparer
    V1/V2/V3 sur la MEME definition consistente (egalite a la base).
    """
    if "bar_range_pct" not in df.columns:
        # Fallback : calculer (high-low)/close
        bar_range = (df["high"] - df["low"]) / df["close"]
    else:
        bar_range = df["bar_range_pct"]

    # Rolling stats
    bar_range_med = bar_range.rolling(lookback, min_periods=20).median()
    bar_range_now = bar_range.rolling(10, min_periods=5).mean()  # smoothed
    contraction = bar_range_now < (bar_range_med * 0.85)

    # Compression : bar_range_pct < quantile 40 sur lookback
    bar_range_q40 = bar_range.rolling(lookback, min_periods=20).quantile(0.40)
    compression = bar_range_now < bar_range_q40

    return (compression & contraction).fillna(False)


# ─── Detectors wrappers ──────────────────────────────────────────────────────

def predict_v1(df: pd.DataFrame, sym: str) -> pd.Series:
    """V1 RangeDetector — 5 criteres."""
    det = RangeDetector(sym=sym)
    out = det.detect_iterative(df)
    return out["is_range"].astype(bool)


def predict_v3_combo(df: pd.DataFrame, sym: str) -> pd.Series:
    """V3 COMBO : ADX<22 + Chop>60 + im_corr<0.93 + rvol_z<-0.2 (4/4).

    Implementation simple sur features deja calculees ou re-calc rolling.
    """
    # Calc ADX + Chop iterativement via V1 (qui les expose dans detect_iterative)
    det = RangeDetector(sym=sym, lookback=60)
    out = det.detect_iterative(df)
    adx_ok = out["adx"] < 22
    chop_ok = out["choppiness"] > 60

    if "im_rolling_correlation_10" in df.columns:
        im_corr_ok = df["im_rolling_correlation_10"].fillna(1.0) < 0.93
    else:
        im_corr_ok = pd.Series([True] * len(df), index=df.index)

    if "rvol_zscore" in df.columns:
        rvol_ok = df["rvol_zscore"].fillna(0.0) < -0.2
    else:
        rvol_ok = pd.Series([True] * len(df), index=df.index)

    # 4/4 strict
    return (adx_ok & chop_ok & im_corr_ok & rvol_ok).fillna(False)


def predict_v2(df: pd.DataFrame, sym: str) -> pd.Series:
    """V2 RangeDetectorV2."""
    det = RangeDetectorV2(sym=sym)
    out = det.detect_iterative(df)
    return out["is_range"].astype(bool)


# ─── Metrics ─────────────────────────────────────────────────────────────────

def compute_metrics(y_true: pd.Series, y_pred: pd.Series) -> dict:
    """Precision, Recall, F1, fire rate."""
    y_true = y_true.fillna(False).astype(bool).to_numpy()
    y_pred = y_pred.fillna(False).astype(bool).to_numpy()

    tp = int(((y_true) & (y_pred)).sum())
    fp = int(((~y_true) & (y_pred)).sum())
    fn = int(((y_true) & (~y_pred)).sum())
    tn = int(((~y_true) & (~y_pred)).sum())

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
    """4 splits chronologiques. Stabilite F1 inter-folds = critere Lopez."""
    n = len(df)
    fold_size = n // n_splits
    rows = []

    print(f"\n=== Walk-forward audit {sym} ({n} bars, {n_splits} folds) ===")
    y_true_all = compute_ground_truth_range(df)

    for fold in range(n_splits):
        start = fold * fold_size
        end = (fold + 1) * fold_size if fold < n_splits - 1 else n
        df_fold = df.iloc[start:end].reset_index(drop=True)
        y_true = y_true_all.iloc[start:end].reset_index(drop=True)

        if len(df_fold) < 100:
            continue

        t0 = time.time()
        y_v1 = predict_v1(df_fold, sym)
        t_v1 = time.time() - t0
        m_v1 = compute_metrics(y_true, y_v1)
        m_v1.update({"detector": "V1", "fold": fold, "n": len(df_fold), "secs": round(t_v1, 1)})
        rows.append(m_v1)

        t0 = time.time()
        y_v3 = predict_v3_combo(df_fold, sym)
        t_v3 = time.time() - t0
        m_v3 = compute_metrics(y_true, y_v3)
        m_v3.update({"detector": "V3", "fold": fold, "n": len(df_fold), "secs": round(t_v3, 1)})
        rows.append(m_v3)

        t0 = time.time()
        y_v2 = predict_v2(df_fold, sym)
        t_v2 = time.time() - t0
        m_v2 = compute_metrics(y_true, y_v2)
        m_v2.update({"detector": "V2", "fold": fold, "n": len(df_fold), "secs": round(t_v2, 1)})
        rows.append(m_v2)

        print(f"  Fold {fold} (n={len(df_fold):>6}): V1 F1={m_v1['f1']:.2f} fire={m_v1['fire_rate']:.0%} "
              f"| V3 F1={m_v3['f1']:.2f} fire={m_v3['fire_rate']:.0%} "
              f"| V2 F1={m_v2['f1']:.2f} fire={m_v2['fire_rate']:.0%}")

    return pd.DataFrame(rows)


def summary(df_results: pd.DataFrame) -> pd.DataFrame:
    """Aggregate par detector : F1 mean/std, precision/recall mean, stabilite."""
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
    """Load v4_enriched dataset."""
    import pyarrow.dataset as ds
    sym_mapping = {"NQ": "NQ.c.0", "ES": "ES.c.0"}
    if symbol not in sym_mapping:
        raise ValueError(f"Symbol {symbol} not supported")
    path = Path(f"D:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS/v4_enriched/symbol={sym_mapping[symbol]}")
    dataset = ds.dataset(path, format="parquet")
    cols_needed = [
        "ts_event", "high", "low", "close", "bar_range_pct",
        "im_rolling_correlation_10", "rvol_zscore",
        "n_color_up_cluster_within_0_2pct", "n_long_up_cluster_within_0_2pct",
        "n_edge_buy_active",
        "n_color_dn_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
        "n_edge_sell_active",
    ]
    available = [c for c in cols_needed if c in dataset.schema.names]
    df = dataset.to_table(columns=available).to_pandas()
    df = df.sort_values("ts_event").reset_index(drop=True)
    if max_bars and len(df) > max_bars:
        # Prendre les `max_bars` derniers (plus recents = plus pertinents)
        df = df.iloc[-max_bars:].reset_index(drop=True)
    return df


def main(symbol: str, max_bars: int | None = None) -> None:
    print(f"=== Audit Range Detector V1 vs V3 COMBO vs V2 — {symbol} ===")
    df = load_data(symbol, max_bars)
    print(f"Loaded {len(df):,} bars from {df['ts_event'].min()} to {df['ts_event'].max()}")

    # Ground truth distribution
    gt = compute_ground_truth_range(df)
    print(f"Ground truth proxy: {gt.sum():,}/{len(df):,} bars ({gt.mean():.1%}) flagged range")

    results = walk_forward_audit(df, symbol, n_splits=4)
    print("\n=== Detail folds ===")
    print(results.to_string(index=False))

    print("\n=== Summary aggregate ===")
    agg = summary(results)
    print(agg.to_string())

    # Verdict
    print("\n=== Verdict ===")
    f1_v1 = agg.loc["V1", "f1_mean"]
    f1_v3 = agg.loc["V3", "f1_mean"]
    f1_v2 = agg.loc["V2", "f1_mean"]
    stab_v2 = agg.loc["V2", "f1_stability"]

    delta_v2_v1 = f1_v2 - f1_v1
    delta_v2_v3 = f1_v2 - f1_v3

    print(f"  F1 V1 = {f1_v1:.3f} | V3 = {f1_v3:.3f} | V2 = {f1_v2:.3f}")
    print(f"  Delta V2 vs V1 = {delta_v2_v1:+.3f}")
    print(f"  Delta V2 vs V3 = {delta_v2_v3:+.3f}")
    print(f"  Stabilite V2 (std/mean) = {stab_v2:.2f}")

    # Decision
    if delta_v2_v1 > 0.03 and delta_v2_v3 > 0.0 and stab_v2 < 0.30:
        verdict = "GO Phase 1 OBSERVATION (V2 > V1 + V3, stabilite OK)"
    elif delta_v2_v1 > 0.0 and stab_v2 < 0.40:
        verdict = "GO RESERVE — V2 marginal vs V1, monitor 7j data live"
    elif delta_v2_v3 < -0.02:
        verdict = "NOGO — V3 COMBO suffit, V2 ajoute complexite sans gain"
    else:
        verdict = "NOGO — V2 sous V1 ou instable cross-folds"
    print(f"  --> Verdict: {verdict}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ", choices=["NQ", "ES"])
    parser.add_argument("--bars", type=int, default=80000, help="Max bars (recents)")
    args = parser.parse_args()
    main(args.symbol, args.bars)
