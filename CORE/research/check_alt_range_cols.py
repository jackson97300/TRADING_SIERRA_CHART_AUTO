"""Vérifie colonnes alternatives V4 pour range_pos."""
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
fp = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"
df = pq.read_table(fp).to_pandas()

cols_to_check = [
    "position_in_range", "pct_in_range", "range_size", "range_size_pct",
    "range_pos", "premium_zone", "discount_zone",
    "dist_last_swing_low_pct", "dist_last_swing_high_pct",
    "dist_sess_low_pct", "dist_sess_high_pct",
    "profile_shape", "trend_day_probability", "bars_in_va", "cvd_day_dir",
    "dist_mq_call_0dte",
]

print(f"{'Column':<35}{'Null':<15}{'Non-null sample'}")
print("-" * 100)
for c in cols_to_check:
    if c in df.columns:
        n_null = df[c].isna().sum()
        n_total = len(df)
        pct = round(100 * n_null / n_total, 1)
        sample = df[c].dropna().head(3).tolist()
        status = "100% NaN ❌" if pct == 100 else f"{pct}% NaN"
        print(f"{c:<35}{status:<15}{sample}")
    else:
        print(f"{c:<35}ABSENT ❌")
