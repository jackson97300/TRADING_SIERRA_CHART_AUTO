"""Audit features long_bars + dist_long_* + n_long_* post-rebuild VPS."""
import pyarrow.parquet as pq
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

LONG_FEATURES = [
    "long_up_bar", "long_dn_bar",
    "n_long_up_zones_active", "n_long_dn_zones_active",
    "dist_long_up_nearest_pct", "dist_long_dn_nearest_pct",
    "n_long_up_cluster_within_0_2pct", "n_long_dn_cluster_within_0_2pct",
    "long_up_dn_pattern", "long_dn_up_pattern",
]

for sym in ["NQ", "ES"]:
    print(f"\n=== {sym} long_bars features ===")
    fp = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={sym}.c.0" / "year=2026" / "month=05" / "data.parquet"
    if not fp.exists():
        print(f"  NOT FOUND")
        continue
    df = pq.read_table(fp).to_pandas()
    print(f"  N bars: {len(df)}")
    for feat in LONG_FEATURES:
        if feat not in df.columns:
            print(f"    {feat:<42} ABSENT")
            continue
        n_nan = df[feat].isna().sum()
        pct_nan = round(100 * n_nan / len(df), 1)
        non_null = df[feat].dropna()
        if len(non_null) > 0:
            sample = non_null.head(3).tolist()
            n_non_zero = (non_null != 0).sum()
            print(f"    {feat:<42} nan={pct_nan}% non_zero_count={n_non_zero}/{len(non_null)} sample={sample}")
        else:
            print(f"    {feat:<42} 100% NaN ❌")
