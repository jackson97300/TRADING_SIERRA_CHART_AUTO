"""Coverage par jour 2026-05 pour ES/NQ/MGC."""
import pandas as pd

ROOT = "C:/TRADING_SIERRA_CHART_AUTO" if __import__("os").name == "nt" else "."

for sym in ["ES.c.0", "NQ.c.0", "MGC.c.0"]:
    p = f"{ROOT}/DATA/datasets/v4_enriched/symbol={sym}/year=2026/month=05/data.parquet"
    df = pd.read_parquet(p)
    df["day"] = pd.to_datetime(df["ts_event"]).dt.date
    print(f"\n=== {sym} total_bars={len(df)} ===")
    for day, grp in df.groupby("day"):
        bars = len(grp)
        has_ny = grp["ny_open"].notna().sum() if "ny_open" in grp.columns else 0
        has_lon = grp["london_open"].notna().sum() if "london_open" in grp.columns else 0
        has_asia = grp["asia_high"].notna().sum() if "asia_high" in grp.columns else 0
        print(f"  {day}: bars={bars:4d}  asia_n={has_asia:4d}  london_n={has_lon:4d}  ny_n={has_ny:4d}")
