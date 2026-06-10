"""
Test ultra-critique : a p_primary fixe (bucket), day_type ajoute-t-il un edge ?

Si a p_primary fixe, le WR ne change PAS selon day_type :
  → day_type est pure tautologie (selectionne juste des p_primary plus hauts)
Si a p_primary fixe, day_type ajoute +3-10 points WR :
  → vrai edge independant
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODELS_DIR = Path("DATA/MODELS")
DATASETS_DIR = Path("DATA/DATASETS")


def load_primary(symbol: str, side: str):
    path = MODELS_DIR / f"{symbol}_{side}_model.pkl"
    with open(path, "rb") as f:
        return pickle.load(f)


def load_config(symbol: str, side: str) -> dict:
    import json
    path = MODELS_DIR / f"{symbol}_{side}_config.json"
    with open(path, "r") as f:
        return json.load(f)


def load_dataset(symbol: str) -> pd.DataFrame:
    for version in ["v3", "v2"]:
        path = DATASETS_DIR / f"{symbol}_dataset_{version}.parquet"
        if path.exists():
            return pd.read_parquet(path)
    raise FileNotFoundError(f"No dataset for {symbol}")


def analyze_controlled(symbol: str, side: str):
    print(f"\n{'='*85}")
    print(f"  TEST CONTROLE DAY_TYPE — {symbol} {side.upper()}")
    print(f"{'='*85}")

    primary = load_primary(symbol, side)
    config = load_config(symbol, side)
    df = load_dataset(symbol)

    features = [f for f in config["features"] if f in df.columns]
    X = df[features]
    p_primary = primary.predict_proba(X)[:, 1]

    target = 1 if side == "buy" else -1
    y = (df["label"].values == target).astype(int)

    # day_type disponible ?
    if "day_type" not in df.columns:
        print(f"  day_type absent, abort")
        return
    day_type = df["day_type"].values

    # day_type high / low (p75 / p25)
    dt_p75 = np.quantile(day_type, 0.75)
    dt_p25 = np.quantile(day_type, 0.25)
    day_high = day_type >= dt_p75
    day_low = day_type <= dt_p25

    print(f"  day_type p75 = {dt_p75}, p25 = {dt_p25}")
    print(f"  Dataset : {len(df)} rows, baseline WR = {y.mean():.1%}")

    # Buckets p_primary
    buckets = [
        (0.30, 0.40),
        (0.40, 0.50),
        (0.50, 0.55),
        (0.55, 0.60),
        (0.60, 0.70),
    ]

    print(f"\n  Table : WR par bucket p_primary × day_type (hautes vs basses)")
    print(f"  {'p_primary bucket':<20s}  {'n_all':>6s} {'wr_all':>7s}  "
          f"{'n_hi':>5s} {'wr_hi':>7s}  {'n_lo':>5s} {'wr_lo':>7s}  "
          f"{'diff_hi_all':>12s}  {'diff_hi_lo':>12s}")
    print(f"  {'-'*100}")

    for p_low, p_high in buckets:
        mask_bucket = (p_primary >= p_low) & (p_primary < p_high)
        y_bucket = y[mask_bucket]
        n_all = mask_bucket.sum()
        if n_all < 30:
            continue
        wr_all = y_bucket.mean()

        mask_bucket_hi = mask_bucket & day_high
        mask_bucket_lo = mask_bucket & day_low
        n_hi = mask_bucket_hi.sum()
        n_lo = mask_bucket_lo.sum()
        wr_hi = y[mask_bucket_hi].mean() if n_hi >= 10 else np.nan
        wr_lo = y[mask_bucket_lo].mean() if n_lo >= 10 else np.nan

        diff_hi_all = wr_hi - wr_all if not np.isnan(wr_hi) else np.nan
        diff_hi_lo = wr_hi - wr_lo if not np.isnan(wr_hi) and not np.isnan(wr_lo) else np.nan

        print(f"  [{p_low:.2f}-{p_high:.2f}):{' ':>9s}"
              f"{n_all:>6d} {wr_all:>6.1%}  "
              f"{n_hi:>5d} {wr_hi:>6.1%}  "
              f"{n_lo:>5d} {wr_lo:>6.1%}  "
              f"{diff_hi_all*100:>+10.1f}pt  "
              f"{diff_hi_lo*100:>+10.1f}pt")

    # Distribution p_primary dans subset day_high vs day_low
    print(f"\n  Distribution p_primary dans day_type haut vs bas :")
    print(f"  day_high : mean p_primary = {p_primary[day_high].mean():.3f}, "
          f"median = {np.median(p_primary[day_high]):.3f}")
    print(f"  day_low  : mean p_primary = {p_primary[day_low].mean():.3f}, "
          f"median = {np.median(p_primary[day_low]):.3f}")

    # Verdict
    # Si a p_primary fixe, day_high ne change pas le WR → tautologie
    diffs_high_all = []
    for p_low, p_high in buckets:
        mask = (p_primary >= p_low) & (p_primary < p_high)
        if mask.sum() < 50:
            continue
        mask_hi = mask & day_high
        if mask_hi.sum() < 10:
            continue
        wr_all = y[mask].mean()
        wr_hi = y[mask_hi].mean()
        diffs_high_all.append(wr_hi - wr_all)

    mean_diff = np.mean(diffs_high_all) if diffs_high_all else 0
    print(f"\n  Moyenne diff (day_high - all) a p_primary fixe : {mean_diff*100:+.1f} points")
    if abs(mean_diff) < 0.02:
        print(f"  VERDICT : TAUTOLOGIE PURE — day_type ne fait que selectionner des "
              f"p_primary plus hauts")
    elif 0.02 <= abs(mean_diff) < 0.05:
        print(f"  VERDICT : EDGE MARGINAL — day_type ajoute un peu mais fragile")
    else:
        print(f"  VERDICT : EDGE REEL — day_type ajoute independamment +{mean_diff*100:.1f} pts")


def main():
    for symbol in ["ES"]:
        for side in ["buy", "sell"]:
            analyze_controlled(symbol, side)


if __name__ == "__main__":
    main()
