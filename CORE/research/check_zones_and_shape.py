"""Verifie premium_zone/discount_zone + shape parquet."""
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
fp = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"
df = pq.read_table(fp).to_pandas()

print(f"SHAPE: {df.shape}")
print(f"TS range: {df['ts_event'].min()} -> {df['ts_event'].max()}")
print()

cols = ["premium_zone", "discount_zone", "position_in_range", "pct_in_range",
        "range_size", "range_size_pct"]
for c in cols:
    if c in df.columns:
        n_null = df[c].isna().sum()
        vals = df[c].dropna().unique()[:5].tolist()
        dtype = str(df[c].dtype)
        print(f"{c:<25} null={n_null}/{len(df)} dtype={dtype} sample_vals={vals}")
    else:
        print(f"{c:<25} ABSENT")
