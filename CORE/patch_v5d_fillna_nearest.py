"""patch_v5d_fillna_nearest.py — Fillna sentinelle 100.0 sur `dist_*_nearest_pct`.

Bug 27/04 : NQ trapped_buyers/sellers_nearest_pct 97% NaN -> Preflight FATAL.
Cause : zones trapped traders rares sur NQ (rare event). NaN = "pas de zone proche".

Fix : fillna(100.0) = "tres loin" semantiquement correct (100% = hors range).
Preserve l'info "absence de zone" comme signal binaire dominant pour LightGBM.

Patches :
  - dist_*_nearest_pct (12 colonnes ES, 13 NQ)

Auteur : MIA Trading System V2
Date   : 2026-04-27 23:30 (fix post-Optuna v3)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = 100.0  # 100% = tres loin (hors range raisonnable)


def patch_symbol(sym: str) -> None:
    path = ROOT / f"DATA/datasets/{sym}_dataset_v5d.parquet"
    print(f"\n[{sym}] Loading {path.name}...")
    df = pd.read_parquet(path)
    print(f"  {len(df):,} bars x {df.shape[1]} cols")

    cols = sorted([c for c in df.columns if "nearest_pct" in c])
    print(f"  Found {len(cols)} dist_*_nearest_pct cols")

    n_changes = 0
    for c in cols:
        n_nan = int(df[c].isna().sum())
        if n_nan == 0:
            continue
        df[c] = df[c].fillna(SENTINEL)
        n_changes += n_nan
        print(f"    {c:50s} fillna={n_nan:>7,} ({n_nan/len(df)*100:5.1f}%)")

    print(f"  Total NaN filled : {n_changes:,}")
    print(f"  Saving {path.name}...")
    df.to_parquet(path, index=False)
    print(f"  [OK] Patched {sym}")


def main():
    print("=" * 70)
    print("PATCH v5d : fillna(100.0) on dist_*_nearest_pct")
    print("=" * 70)
    for sym in ["ES", "NQ"]:
        patch_symbol(sym)

    print("\n" + "=" * 70)
    print("DONE — datasets v5d patched in-place")
    print("=" * 70)


if __name__ == "__main__":
    main()
