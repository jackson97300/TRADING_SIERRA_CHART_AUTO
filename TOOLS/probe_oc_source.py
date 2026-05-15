"""Trouve quelle bar V4 capture open_cash=6463.5 et son date_et."""
import pandas as pd

df = pd.read_parquet("DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet")
ts_et = pd.to_datetime(df["ts_event"]).dt.tz_convert("America/New_York")
df["date_et"] = ts_et.dt.date
df["mins_et_derived"] = ts_et.dt.hour * 60 + ts_et.dt.minute

# Bars proches mins_et_derived=570 (09:30 ET) avec close == 6463.5
mask = (df["mins_et_derived"].between(567, 575)) & (df["close"] == 6463.5)
print(f"Bars mins_et_derived ~570 avec close=6463.5: {mask.sum()}")
print(df.loc[mask, ["ts_event", "date_et", "mins_et_derived", "close", "open_cash", "session_date_trading"]].head(10).to_string())

# Bars April 1 9:30 ET = 13:30 UTC
mask2 = pd.to_datetime(df["ts_event"]).between("2026-04-01 13:25", "2026-04-01 13:35")
print(f"\nBars 2026-04-01 13:25-13:35 UTC ({mask2.sum()}):")
print(df.loc[mask2, ["ts_event", "session_date_trading", "close", "open_cash"]].to_string())
