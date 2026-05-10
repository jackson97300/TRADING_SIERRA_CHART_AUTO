"""Concat tous les parquets MGC enriched -> MGC_dataset_v5e_clean.parquet."""
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=MGC.c.0")
OUT = Path(r"C:/TRADING_SIERRA_CHART_AUTO/DATA/DATASETS/MGC_dataset_v5e_clean.parquet")
OUT.parent.mkdir(parents=True, exist_ok=True)

parquets = sorted(ROOT.rglob("data.parquet"))
print(f"Concat {len(parquets)} parquets MGC")
dfs = []
for p in parquets:
    df = pd.read_parquet(p)
    # Normaliser ts_event en tz-naive UTC pour eviter mix tz-aware/tz-naive
    if "ts_event" in df.columns:
        ts = pd.to_datetime(df["ts_event"])
        if hasattr(ts.dt, "tz") and ts.dt.tz is not None:
            df["ts_event"] = ts.dt.tz_convert("UTC").dt.tz_localize(None)
        else:
            df["ts_event"] = ts
    dfs.append(df)
    print(f"  {p.relative_to(ROOT)}: {len(df)} bars x {len(df.columns)} cols")

big = pd.concat(dfs, ignore_index=True).sort_values("ts_event")
big = big.drop_duplicates(subset=["ts_event"])
print(f"\nTotal apres concat: {len(big)} bars x {len(big.columns)} cols")
print(f"Range: {big['ts_event'].min()} -> {big['ts_event'].max()}")

big.to_parquet(OUT, compression="zstd", index=False)
size_mb = OUT.stat().st_size / 1024 / 1024
print(f"Wrote {OUT} ({size_mb:.1f} MB)")
