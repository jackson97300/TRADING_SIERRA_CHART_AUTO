"""Check coverage historique sur tous les datasets v3/v4/v5e."""
import pandas as pd
from pathlib import Path

DSDIR = Path("DATA/datasets")

datasets = [
    "ES_dataset_v3.parquet",
    "NQ_dataset_v3.parquet",
    "ES_dataset_v4.parquet",
    "NQ_dataset_v4.parquet",
    "ES_dataset_v5e.parquet",
    "NQ_dataset_v5e.parquet",
]

for ds in datasets:
    p = DSDIR / ds
    if not p.exists():
        print(f"{ds}: MISSING")
        continue
    df = pd.read_parquet(p)
    ts_col = None
    for cand in ['ts_event', 'ts', 'datetime', 'timestamp']:
        if cand in df.columns:
            ts_col = cand
            break
    if ts_col is None and isinstance(df.index, pd.DatetimeIndex):
        ts_col = 'index'
        ts_min = df.index.min()
        ts_max = df.index.max()
    elif ts_col:
        ts_min = pd.to_datetime(df[ts_col]).min()
        ts_max = pd.to_datetime(df[ts_col]).max()
    else:
        ts_min = ts_max = "N/A"

    n_days = "?"
    if ts_col:
        try:
            unique_dates = pd.to_datetime(df[ts_col] if ts_col != 'index' else df.index).dt.date.nunique()
            n_days = unique_dates
        except Exception:
            pass

    print(f"\n{ds}")
    print(f"  shape: {df.shape}, ts_col={ts_col}")
    print(f"  range: {ts_min} -> {ts_max}")
    print(f"  unique days: {n_days}")
