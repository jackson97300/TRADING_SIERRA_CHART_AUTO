"""Verifier features color_* dans le parquet V4 Bot 2."""
import pandas as pd

df = pd.read_parquet(
    "C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=04/data.parquet"
)
cols = list(df.columns)
print(f"Total cols: {len(cols)}")
color_cols = [c for c in cols if "color" in c.lower()]
print(f"\nCOLOR features ({len(color_cols)}):")
for c in color_cols:
    print(f"  {c}")

print(f"\ndist_color_dn_nearest_pct exists: {'dist_color_dn_nearest_pct' in cols}")
print(f"dist_color_up_nearest_pct exists: {'dist_color_up_nearest_pct' in cols}")

# Si existe, sample values
if "dist_color_dn_nearest_pct" in cols:
    s = df["dist_color_dn_nearest_pct"].dropna()
    print(f"\ndist_color_dn_nearest_pct stats: n_non_null={len(s)}, min={s.min()}, max={s.max()}, mean={s.mean():.4f}")
    print(f"  % values in (0, 0.05]: {((s > 0) & (s <= 0.05)).sum() / len(s) * 100:.1f}%")
