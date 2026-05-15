"""Probe V4 NQ last bar to verify seed sessions inputs."""
import pandas as pd
import sys
from pathlib import Path

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=05/data.parquet")
df = pd.read_parquet(path)
print(f"V4 rows={len(df)} ts range {df['ts_event'].min()} -> {df['ts_event'].max()}")
print(f"Cols ALL : {len(df.columns)}")
print(f"\nasia_*/london_*/us_* in V4 :")
for c in ["asia_high","asia_low","london_high","london_low","us_high","us_low","after_high","after_low","asia_open","london_open","ny_open","after_open","open_cash","price_1030"]:
    if c in df.columns:
        nn = df[c].notna().sum()
        print(f"  {c:20s} non-null={nn}/{len(df)}")
    else:
        print(f"  {c:20s} ABSENT")

# Check last bar values
print(f"\nDerniere bar V4 ({df.iloc[-1]['ts_event']}):")
last = df.iloc[-1]
for c in ["session_date_trading","asia_high","asia_low","london_open","ny_open","open_cash","price_1030"]:
    v = last.get(c, "ABSENT")
    print(f"  {c:25s} = {v}")
