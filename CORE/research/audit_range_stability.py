"""audit_range_stability.py — Stabilite walk-forward + V1 vs V2 detector.

Verifie :
  1. Median des top features par mois (anti drift)
  2. Detector V1 (ATR/ADX/Chop/Geo/NoBO) vs V2 (top features V4)
  3. Recall/Precision sur is_range_label canon
"""
from __future__ import annotations

import glob
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import sys
sys.path.insert(0, "D:/TRADING_SIERRA_CHART_AUTO/CORE/research")
from audit_range_features import build_label, load_v4

TOP_FEATURES = [
    "im_rolling_correlation_10",
    "trend_day_probability",
    "time_to_session_close_norm",
    "cur_va_total_vol",
    "bars_in_va",
    "rvol_zscore",
    "vol_zscore_20",
    "single_print_count",
    "cur_va_n_buckets",
    "dist_sess_low_pct",
    "ctx_va_developing_10",
    "rvol_regime",
]


def stability_check(df: pd.DataFrame, label: pd.Series):
    """Median par mois pour chaque feature top, verifie qu'il n'y a pas de drift."""
    df = df.copy()
    df["month"] = df["ts_event"].dt.to_period("M")
    df["_label"] = label.values

    print("\n=== Stabilite WALK-FORWARD : median(feature | range=1) par mois ===")
    print(f"{'feature':35s} | " + " | ".join([f"{m:>8s}" for m in sorted(df["month"].unique().astype(str))[-6:]]))
    print("-" * 100)
    months = sorted(df["month"].unique())[-6:]
    for f in TOP_FEATURES:
        if f not in df.columns:
            continue
        vals = []
        for m in months:
            sub = df[(df["month"] == m) & (df["_label"] == 1)]
            if len(sub) > 30:
                vals.append(f"{sub[f].median():>8.3f}")
            else:
                vals.append(f"{'n<30':>8s}")
        print(f"{f:35s} | " + " | ".join(vals))


def detector_v1(df: pd.DataFrame, label: pd.Series) -> tuple[float, float, float]:
    """V1 = ATR<baseline + ADX<25 + Chop>60 + Geo + NoBO (5 criteres, >=3)."""
    atr = df["_atr_calc"].values
    adx = df["_adx_calc"].values
    chop = df["_chop_calc"].values
    range_atr = df["_range_atr_calc"].values

    # Baseline ATR : median(atr) sur tout l'historique
    atr_baseline = np.nanmedian(atr)
    crit1 = atr < atr_baseline * 0.85   # ATR contracted
    crit2 = adx < 25
    crit3 = chop > 60
    crit4 = (range_atr > 4.0) & (range_atr < 12.0)
    # NoBreakout : plus complexe, on skip pour simple comparaison
    n_crit = crit1.astype(int) + crit2.astype(int) + crit3.astype(int) + crit4.astype(int)
    pred = n_crit >= 3

    return _metrics(label.values, pred, "V1 (ATR/ADX/Chop/Geo)")


def detector_v2_simple(df: pd.DataFrame, label: pd.Series) -> tuple[float, float, float]:
    """V2 = features V4 brutes (vol_zscore, im_corr, bars_in_va, time_to_close)."""
    if "im_rolling_correlation_10" not in df.columns:
        print("V2 unavailable")
        return None, None, None

    # 4 criteres simples, >=2/4
    crit1 = df["im_rolling_correlation_10"] < 0.92  # decorrelation ES/NQ
    crit2 = df["rvol_zscore"] < -0.2                 # volume relatif sous moyenne
    crit3 = df["time_to_session_close_norm"] > 0.3   # 2eme moitie session
    crit4 = df["cur_va_total_vol"] > df["cur_va_total_vol"].median()  # va construite (range)

    n_crit = crit1.astype(int) + crit2.astype(int) + crit3.astype(int) + crit4.astype(int)
    pred = n_crit >= 3

    return _metrics(label.values, pred.values, "V2 (im_corr/rvol_z/time/va_vol)")


def detector_v2_pure(df: pd.DataFrame, label: pd.Series) -> tuple[float, float, float]:
    """V2 PURE = im_correlation + rvol_zscore (les 2 plus discriminantes)."""
    crit1 = df["im_rolling_correlation_10"] < 0.92
    crit2 = df["rvol_zscore"] < -0.3
    pred = crit1 & crit2
    return _metrics(label.values, pred.values, "V2 PURE (im_corr & rvol_z)")


def detector_v3_combo(df: pd.DataFrame, label: pd.Series) -> tuple[float, float, float]:
    """V3 COMBO = V1 (ADX+Chop) + V2 (im_corr) hybride."""
    adx = df["_adx_calc"].values
    chop = df["_chop_calc"].values
    crit1 = adx < 22
    crit2 = chop > 60
    crit3 = df["im_rolling_correlation_10"].values < 0.93
    crit4 = df["rvol_zscore"].values < -0.2
    n = crit1.astype(int) + crit2.astype(int) + crit3.astype(int) + crit4.astype(int)
    pred = n >= 3
    return _metrics(label.values, pred, "V3 COMBO (ADX+Chop+im_corr+rvol)")


def _metrics(y, pred, name):
    y = np.asarray(y, dtype=bool)
    pred = np.asarray(pred, dtype=bool)
    valid = ~pd.isna(pred) & ~pd.isna(y)
    y, pred = y[valid], pred[valid]
    tp = ((y == 1) & (pred == 1)).sum()
    fp = ((y == 0) & (pred == 1)).sum()
    fn = ((y == 1) & (pred == 0)).sum()
    tn = ((y == 0) & (pred == 0)).sum()
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    fire_rate = (tp + fp) / max(len(y), 1)
    print(f"  {name:38s} prec={prec:.3f} rec={rec:.3f} f1={f1:.3f} fire={100*fire_rate:.1f}%")
    return prec, rec, f1


def main():
    nq = load_v4("NQ")
    es = load_v4("ES")

    nq_label = build_label(nq)
    es_label = build_label(es)
    print(f"NQ range rate: {100*nq_label.mean():.1f}%")
    print(f"ES range rate: {100*es_label.mean():.1f}%")

    print("\n=== NQ : Detectors V1 vs V2 ===")
    detector_v1(nq, nq_label)
    detector_v2_simple(nq, nq_label)
    detector_v2_pure(nq, nq_label)
    detector_v3_combo(nq, nq_label)

    print("\n=== ES : Detectors V1 vs V2 ===")
    detector_v1(es, es_label)
    detector_v2_simple(es, es_label)
    detector_v2_pure(es, es_label)
    detector_v3_combo(es, es_label)

    print("\n=== STABILITE WALK-FORWARD NQ ===")
    stability_check(nq, nq_label)
    print("\n=== STABILITE WALK-FORWARD ES ===")
    stability_check(es, es_label)


if __name__ == "__main__":
    main()
