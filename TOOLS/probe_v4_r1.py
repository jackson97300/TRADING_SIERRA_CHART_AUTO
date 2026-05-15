import pandas as pd
import glob

paths = sorted(glob.glob("DATA/DATASETS/v4_enriched/symbol=NQ.c.0/year=2026/month=*/data*.parquet"))
if not paths:
    print("NO V4 PARQUET FOUND for ES")
    raise SystemExit

p = paths[-1]
df = pd.read_parquet(p)
print(f"File: {p}")
print(f"Rows: {len(df)}  Cols: {len(df.columns)}")

checks = [
    "diag_imbalance",
    "large_trader_ratio",
    "ctx_diag_imbalance_mean_5",
    "ctx_large_trader_slope_5",
    "diag_imbalance_ofi_proxy",
    "large_trader_max_size_proxy",
    "im_ltr_slope_diff",
    "large_trader_ratio_repro",
]
for c in checks:
    if c in df.columns:
        n_nan = int(df[c].isna().sum())
        n_nz = int((df[c] != 0).sum()) if df[c].dtype.kind in "iufc" else -1
        print(f"  [PRESENT] {c}  NaN={n_nan}/{len(df)}  non-zero={n_nz}")
    else:
        print(f"  [ABSENT]  {c}")
