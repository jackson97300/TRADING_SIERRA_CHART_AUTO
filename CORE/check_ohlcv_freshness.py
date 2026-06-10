"""Check OHLCV-1m raw parquet freshness for ES + NQ today."""
import pandas as pd
from pathlib import Path

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/databento/GLBX.MDP3/ohlcv-1m")
for sym in ["ES.c.0", "NQ.c.0"]:
    p = ROOT / f"symbol={sym}" / "year=2026" / "month=4" / "day=28" / "data.parquet"
    if not p.exists():
        print(f"{sym}: MISSING {p}")
        continue
    df = pd.read_parquet(p)
    print(f"{sym}: shape={df.shape}")
    print(f"  cols={list(df.columns)}")
    print(f"  index: {df.index.name} dtype={df.index.dtype}")
    print(f"  index range: {df.index.min()} -> {df.index.max()}")
    print(f"  last 3 index:")
    for ts in df.index[-3:]:
        print(f"    {ts}")
    print(f"  file mtime: {pd.Timestamp(p.stat().st_mtime, unit='s', tz='UTC')}")
    print()
