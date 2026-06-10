"""Build MGC dataset enrichi avec features MQ Gold pour subset 4 mois (jan-mai 2026).

Workflow :
  1. Load MGC_dataset_v5e_enriched.parquet (V5e + Phase D SESSION + Phase D INTERMARKET + Gold Extra)
  2. Filter date range jan-mai 2026 (couverture backfill MQ Gold)
  3. load_mq_levels("MGC", start, end) → levels.jsonl Hive
  4. attach_mq_distances → +16 features MQ Gold
  5. Save MGC_dataset_v5e_mq_enriched.parquet

Output : DATA/DATASETS/MGC_dataset_v5e_mq_enriched.parquet (subset 4 mois MQ-enriched)
"""
import sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
from load_mq_levels import load_mq_levels, attach_mq_distances

INPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_enriched.parquet"
OUTPUT = ROOT / "DATA" / "DATASETS" / "MGC_dataset_v5e_mq_enriched.parquet"

# Range MQ Gold backfill
DATE_START = date(2026, 1, 12)
DATE_END = date(2026, 5, 8)

print(f"=== Build MGC dataset enrichi MQ Gold (subset jan-mai 2026) ===\n")
print(f"  Input : {INPUT}")
df = pd.read_parquet(INPUT)
print(f"  Shape full : {df.shape}")

# Filter date range
ts = pd.to_datetime(df["ts_event"], errors="coerce")
mask = (ts.dt.date >= DATE_START) & (ts.dt.date <= DATE_END)
df = df[mask].copy().reset_index(drop=True)
print(f"  Shape filtered (jan-mai 2026) : {df.shape}")

# Load MQ Gold levels
print(f"\n  Loading MQ levels MGC {DATE_START} -> {DATE_END}...")
levels_df = load_mq_levels("MGC", DATE_START, DATE_END)
print(f"  Levels : {len(levels_df)} rows")

if levels_df.empty:
    print("  ERREUR : pas de niveaux MQ Gold dans la range demandée")
    sys.exit(1)

# Attach distances (tick_size Gold = 0.10)
print(f"\n  Attaching MQ distances (tick=0.10)...")
df = attach_mq_distances(df, levels_df, tick_size=0.10)
print(f"  Shape final : {df.shape}")

# Audit features ajoutées
mq_features = [c for c in df.columns if c.startswith(("dist_mq_", "dist_1d_", "dist_gex_",
                                                       "dist_blind_", "gex_cluster", "bool_above_mq",
                                                       "bool_gex"))]
print(f"\n  Features MQ Gold ajoutées : {len(mq_features)}")
for c in mq_features:
    nan_pct = df[c].isna().sum() / len(df) * 100
    valid = df[c].dropna()
    if len(valid) > 0:
        print(f"    {c:30s} NaN={nan_pct:5.1f}% range=[{valid.min():.1f}, {valid.max():.1f}]")
    else:
        print(f"    {c:30s} NaN={nan_pct:5.1f}% (100% NaN)")

# Save
df.to_parquet(OUTPUT, index=False)
print(f"\n  Saved : {OUTPUT}")
print(f"  Shape final : {df.shape}")
