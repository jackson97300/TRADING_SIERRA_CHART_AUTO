"""
Test leakage simple (agent ml-trainer 17/04/2026) :

Split 70/30 chronologique, train primary sur train ONLY, mesurer
WR(p_primary >= 0.55) in-sample vs OOS.

Gap in-sample - OOS :
  < 5pts  -> vrai edge (improbable)
  5-15pts -> borderline, tester meta OOS
  > 15pts -> leakage massif, strategy morte
"""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError:
    sys.exit("lightgbm required")

DATASETS_DIR = Path("DATA/DATASETS")
MODELS_DIR = Path("DATA/MODELS")


def load_config(symbol: str, side: str) -> dict:
    path = MODELS_DIR / f"{symbol}_{side}_config.json"
    with open(path, "r") as f:
        return json.load(f)


def load_dataset(symbol: str) -> pd.DataFrame:
    for v in ["v3", "v2"]:
        path = DATASETS_DIR / f"{symbol}_dataset_{v}.parquet"
        if path.exists():
            return pd.read_parquet(path)
    raise FileNotFoundError(symbol)


def run_test(symbol: str, side: str):
    print(f"\n{'='*85}")
    print(f"  TEST LEAKAGE — {symbol} {side.upper()}")
    print(f"{'='*85}")

    cfg = load_config(symbol, side)
    df = load_dataset(symbol)

    features = [f for f in cfg["features"] if f in df.columns]
    X = df[features]
    target = 1 if side == "buy" else -1
    y = (df["label"] == target).astype(int).values

    if "ts" in df.columns:
        df_sorted = df.sort_values("ts").reset_index(drop=True)
        X = df_sorted[features]
        y = (df_sorted["label"] == target).astype(int).values
    else:
        df_sorted = df

    split_idx = int(len(df_sorted) * 0.7)
    X_tr, y_tr = X.iloc[:split_idx], y[:split_idx]
    X_te, y_te = X.iloc[split_idx:], y[split_idx:]

    # Sample weights si dispo
    sw_tr = None
    if "sample_weight" in df_sorted.columns:
        sw_tr = df_sorted["sample_weight"].iloc[:split_idx].values

    print(f"  Dataset : {len(df_sorted)} rows")
    print(f"  Train (70%) : {len(X_tr)} rows | Test (30%) : {len(X_te)} rows")

    # Hyperparams from config
    params = cfg["params"]
    # Clean params (remove callables)
    params_clean = {k: v for k, v in params.items() if not callable(v)}
    params_clean["verbosity"] = -1

    print(f"\n  Training primary sur TRAIN only...")
    primary = lgb.LGBMClassifier(**params_clean)
    if sw_tr is not None:
        primary.fit(X_tr, y_tr, sample_weight=sw_tr)
    else:
        primary.fit(X_tr, y_tr)

    p_tr = primary.predict_proba(X_tr)[:, 1]
    p_te = primary.predict_proba(X_te)[:, 1]

    # Table comparative
    print(f"\n  {'Threshold':>10s}  {'N_in':>6s} {'WR_in':>7s}  {'N_oos':>6s} {'WR_oos':>7s}  "
          f"{'GAP':>8s}")
    print(f"  {'-'*65}")

    thresholds = [0.30, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    for t in thresholds:
        mask_in = p_tr >= t
        mask_oos = p_te >= t
        n_in = int(mask_in.sum())
        n_oos = int(mask_oos.sum())
        if n_in < 20:
            wr_in = np.nan
        else:
            wr_in = y_tr[mask_in].mean()
        if n_oos < 20:
            wr_oos = np.nan
        else:
            wr_oos = y_te[mask_oos].mean()
        gap = (wr_in - wr_oos) if not (np.isnan(wr_in) or np.isnan(wr_oos)) else np.nan

        print(f"  {t:>10.2f}  "
              f"{n_in:>6d} {wr_in:>6.1%}  "
              f"{n_oos:>6d} {wr_oos:>6.1%}  "
              f"{gap*100:>+7.1f}pt" if not np.isnan(gap) else
              f"  {t:>10.2f}  {n_in:>6d} {'n/a' if np.isnan(wr_in) else f'{wr_in:.1%}':>6s}  "
              f"{n_oos:>6d} {'n/a' if np.isnan(wr_oos) else f'{wr_oos:.1%}':>6s}  n/a")

    # Focus sur p >= 0.55 (le seuil critique)
    print(f"\n  ═══════════ ZOOM SUR p_primary >= 0.55 ═══════════")
    mask_in_055 = p_tr >= 0.55
    mask_oos_055 = p_te >= 0.55
    wr_in_055 = y_tr[mask_in_055].mean() if mask_in_055.sum() >= 20 else np.nan
    wr_oos_055 = y_te[mask_oos_055].mean() if mask_oos_055.sum() >= 20 else np.nan

    print(f"  WR in-sample  @ p>=0.55 : {wr_in_055:.1%} (n={mask_in_055.sum()})")
    print(f"  WR out-sample @ p>=0.55 : {wr_oos_055:.1%} (n={mask_oos_055.sum()})")
    gap_055 = (wr_in_055 - wr_oos_055) * 100
    print(f"  LEAKAGE GAP : {gap_055:+.1f} points")
    print(f"  VERDICT :", end=" ")
    if abs(gap_055) < 5:
        print("VRAI EDGE — primary calibre OOS")
    elif abs(gap_055) < 10:
        print("MARGINAL — leakage modere, edge peut-etre reel")
    elif abs(gap_055) < 15:
        print("BORDERLINE — leakage suspect, a investiguer")
    else:
        print(f"LEAKAGE MASSIF (>{15}pts) — strategy morte")

    # Test day_type sur OOS
    if "day_type" in df_sorted.columns:
        day_type_te = df_sorted["day_type"].iloc[split_idx:].values
        mask_combo = mask_oos_055 & (day_type_te >= 4)
        n_combo = mask_combo.sum()
        if n_combo >= 20:
            wr_combo = y_te[mask_combo].mean()
            print(f"\n  COMBO p>=0.55 AND day_type>=4 sur OOS : n={n_combo}, WR={wr_combo:.1%}")
            gap_combo = wr_oos_055 - wr_combo
            if wr_combo > wr_oos_055:
                print(f"    day_type ajoute +{(wr_combo - wr_oos_055)*100:.1f}pts sur OOS")
            else:
                print(f"    day_type perd {gap_combo*100:.1f}pts sur OOS (tautologie)")


def main():
    for symbol in ["ES"]:
        for side in ["buy", "sell"]:
            try:
                run_test(symbol, side)
            except Exception as e:
                print(f"[ERR] {symbol} {side}: {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    main()
