"""Test attach_mq_distances sur MGC pour valider le pipeline Gold features."""
import sys
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

import pandas as pd
from load_mq_levels import load_mq_levels, attach_mq_distances

# Sample bars MGC (juste 5 bars dummy pour test)
sample_close = 4707.0   # prix Gold ~ 12/05/2026

# Load 5 jours backfill convertis
print("=== TEST load_mq_levels GC ===")
levels_df = load_mq_levels("MGC", date(2026, 5, 4), date(2026, 5, 8))
print(f"  levels_df shape: {levels_df.shape}")
if not levels_df.empty:
    print(f"  cols: {list(levels_df.columns)}")
    print(f"  trigger counts: {levels_df['trigger'].value_counts().to_dict()}")
    print()
    print("  Sample row 1:")
    print(levels_df.iloc[0].to_dict())

# Test attach_mq_distances sur 5 bars dummy
print("\n=== TEST attach_mq_distances ===")
fake_bars = pd.DataFrame({
    "ts_event": pd.date_range("2026-05-04 09:00", periods=5, freq="D"),
    "close": [4707.0, 4708.5, 4705.2, 4710.0, 4712.5],
})
enriched = attach_mq_distances(fake_bars, levels_df, tick_size=0.10)

print(f"  Enriched shape: {enriched.shape}")
dist_cols = sorted([c for c in enriched.columns if c.startswith(("dist_", "bool_", "gex_"))])
print(f"  Features MQ ajoutees: {len(dist_cols)}")
for c in dist_cols:
    print(f"    {c}")

print("\n  Sample row 1 (5/5/2026 14:00 close=4708.5):")
row = enriched.iloc[1]
for c in dist_cols:
    val = row[c]
    if pd.isna(val):
        print(f"    {c}: NaN")
    else:
        print(f"    {c}: {val}")
