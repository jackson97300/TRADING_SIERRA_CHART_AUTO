"""Enrichit MGC_dataset_v5e_session avec features state-of-the-art Gold.

Workflow (post pull Databento auxiliaire) :
  1. Load V5e session (déjà avec 2 SESSION Phase D features)
  2. Load 6E, ZN, ZB, SI, HG, CL depuis DATA/databento/GLBX.MDP3/ohlcv-1m
  3. Appliquer :
     - Phase D INTERMARKET : im_dxy_corr_60d (via 6E), im_real_yields_proxy (via ZN+ZB)
     - Gold extra features (8) : ratios SI/HG/CL, London Fix windows, Asia breakout
  4. Audit qualité (% non-NaN, distributions)
  5. Save MGC_dataset_v5e_enriched.parquet

Usage : python -X utf8 CORE/research/enrich_gold_dataset_full.py
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
import numpy as np
from gold_phase_d_features import (
    apply_gold_phase_d, GOLD_PHASE_D_FEATURES, load_ohlcv_databento,
)
from gold_extra_features import apply_gold_extra_features, GOLD_EXTRA_FEATURES

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_session.parquet"
OUTPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_enriched.parquet"

print(f"=== ENRICH GOLD DATASET FULL ===\n")
print(f"  Input : {INPUT}")
df = pd.read_parquet(INPUT)
print(f"  Shape : {df.shape}")

# Range pour load auxiliaire
ts = pd.to_datetime(df["ts_event"], utc=True)
range_start = ts.min().tz_localize(None)
range_end = ts.max().tz_localize(None) + pd.Timedelta(days=1)
print(f"  Range : {range_start} -> {range_end}")

# Load auxiliaires
print(f"\n  Loading 6E...")
df_6e = load_ohlcv_databento("6E.c.0", range_start, range_end)
print(f"    6E : {len(df_6e):,} bars" if not df_6e.empty else "    6E : EMPTY")

print(f"  Loading ZN...")
df_zn = load_ohlcv_databento("ZN.c.0", range_start, range_end)
print(f"    ZN : {len(df_zn):,} bars" if not df_zn.empty else "    ZN : EMPTY")

print(f"  Loading ZB...")
df_zb = load_ohlcv_databento("ZB.c.0", range_start, range_end)
print(f"    ZB : {len(df_zb):,} bars" if not df_zb.empty else "    ZB : EMPTY")

print(f"  Loading SI...")
df_si = load_ohlcv_databento("SI.c.0", range_start, range_end)
print(f"    SI : {len(df_si):,} bars" if not df_si.empty else "    SI : EMPTY")

print(f"  Loading HG...")
df_hg = load_ohlcv_databento("HG.c.0", range_start, range_end)
print(f"    HG : {len(df_hg):,} bars" if not df_hg.empty else "    HG : EMPTY")

print(f"  Loading CL...")
df_cl = load_ohlcv_databento("CL.c.0", range_start, range_end)
print(f"    CL : {len(df_cl):,} bars" if not df_cl.empty else "    CL : EMPTY")

# Normaliser ts_event en datetime UTC naive (pour merge cohérent)
for name, dfx in [("MGC", df), ("6E", df_6e), ("ZN", df_zn), ("ZB", df_zb),
                  ("SI", df_si), ("HG", df_hg), ("CL", df_cl)]:
    if not dfx.empty and "ts_event" in dfx.columns:
        dfx["ts_event"] = pd.to_datetime(dfx["ts_event"], utc=True, errors="coerce")
        if dfx["ts_event"].dt.tz is not None:
            dfx["ts_event"] = dfx["ts_event"].dt.tz_localize(None)

# Apply Phase D INTERMARKET (im_dxy_corr_60d + im_real_yields_proxy)
print(f"\n  Applying Phase D INTERMARKET (im_dxy_corr_60d via 6E + im_real_yields_proxy via ZN+ZB)...")
df = apply_gold_phase_d(df, df_6e=df_6e, df_zn=df_zn, df_zb=df_zb)

# Apply Gold Extra Features (8)
print(f"  Applying Gold Extra Features (Gold/Silver, Copper/Gold, Oil/Gold, London Fix, Asia breakout)...")
df = apply_gold_extra_features(df, df_si=df_si, df_hg=df_hg, df_cl=df_cl)

# Audit qualité features ajoutées
print(f"\n=== AUDIT QUALITE FEATURES ENRICHIES ===\n")
all_new = GOLD_PHASE_D_FEATURES + GOLD_EXTRA_FEATURES
print(f"  Feature{'':<35}NaN%   Non-zero%   Mean       Std")
print("  " + "-" * 80)
for feat in all_new:
    if feat not in df.columns:
        print(f"  [ABSENT] {feat}")
        continue
    s = df[feat]
    nan_pct = s.isna().sum() / len(df) * 100
    valid = s.dropna()
    nonzero_pct = (valid != 0).sum() / len(df) * 100 if len(valid) > 0 else 0
    if len(valid) > 0:
        print(f"  {feat:<42} {nan_pct:5.1f}% {nonzero_pct:5.1f}%    {valid.mean():>10.4f} {valid.std():>10.4f}")
    else:
        print(f"  {feat:<42} {nan_pct:5.1f}% 100% NaN")

# Save
df.to_parquet(OUTPUT, index=False)
print(f"\n  Saved : {OUTPUT}")
print(f"  Shape final : {df.shape}")
print(f"\n  Next : re-train ML feature importance avec dataset enrichi")
