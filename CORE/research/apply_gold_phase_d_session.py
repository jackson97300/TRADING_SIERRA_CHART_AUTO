"""Applique les 2 features SESSION Phase D sur MGC_dataset_v5e_clean.parquet.

Étape 1a (12/05/2026) — Compléter données Gold sans dépendance Databento auxiliaire.

Features ajoutées (self-contained MGC) :
- mgc_asia_london_overlap_vol : ratio volume sur fenêtre 12:30-16:00 UTC
- mgc_session_break_acceleration : accélération prix 13:30-14:00 ET post-US-open

Features REPORTÉES (nécessitent pull Databento 6E/ZN/ZB) :
- im_dxy_corr_60d (needs 6E.c.0)
- im_real_yields_proxy (needs ZN.c.0 + ZB.c.0)

Output : DATA/DATASETS/MGC_dataset_v5e_session.parquet

Usage : python -X utf8 CORE/research/apply_gold_phase_d_session.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
import numpy as np
from gold_phase_d_features import (
    compute_mgc_asia_london_overlap_vol,
    compute_mgc_session_break_acceleration,
)

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_clean.parquet"
OUTPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_session.parquet"

print(f"=== Apply Phase D Session Features sur MGC V5e ===\n")
print(f"  Input : {INPUT}")
df = pd.read_parquet(INPUT)
print(f"  Shape : {df.shape}")

# Apply session-based features
print(f"\n  Computing mgc_asia_london_overlap_vol...")
df["mgc_asia_london_overlap_vol"] = compute_mgc_asia_london_overlap_vol(df).values

print(f"  Computing mgc_session_break_acceleration...")
df["mgc_session_break_acceleration"] = compute_mgc_session_break_acceleration(df).values

# Mark intermarket as NaN (reported)
df["im_dxy_corr_60d"] = np.nan
df["im_real_yields_proxy"] = np.nan

# === AUDIT QUALITÉ ===
print(f"\n=== AUDIT QUALITE ===\n")
for feat in ["mgc_asia_london_overlap_vol", "mgc_session_break_acceleration"]:
    s = df[feat]
    n_non_nan = s.notna().sum()
    n_nonzero = (s != 0).sum()
    pct_nz = 100 * n_nonzero / len(df)
    valid = s.dropna()
    valid_nz = valid[valid != 0]
    print(f"  {feat}:")
    print(f"    Non-NaN : {n_non_nan:,} / {len(df):,} = {100*n_non_nan/len(df):.1f}%")
    print(f"    Non-zero : {n_nonzero:,} = {pct_nz:.1f}%")
    if len(valid_nz) > 0:
        print(f"    Range valid_nz : [{valid_nz.min():.3f}, {valid_nz.max():.3f}]")
        print(f"    Median valid_nz : {valid_nz.median():.3f}")
        print(f"    Mean valid_nz : {valid_nz.mean():.3f}")
    print()

# === Save ===
df.to_parquet(OUTPUT, index=False)
print(f"  Saved : {OUTPUT}")
print(f"  Shape final : {df.shape}")
print(f"\n  Next : appliquer dans backtester + ML feature importance")
