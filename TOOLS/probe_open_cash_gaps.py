"""Identifie les 240 bars stream=NaN apres us_start - probable date_et mismatch."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "CORE"))

import pandas as pd
import numpy as np
from phase_b_helpers import OpenCashPrice1030State, add_open_cash_price1030_streaming

df = pd.read_parquet("DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet")
ts_et = pd.to_datetime(df["ts_event"]).dt.tz_convert("America/New_York")
df["date_et"] = ts_et.dt.date
df["mins_et"] = ts_et.dt.hour * 60 + ts_et.dt.minute

state = OpenCashPrice1030State()
streams = []
for row in df.to_dict(orient="records"):
    streams.append(add_open_cash_price1030_streaming(row, state).get("open_cash"))
df["stream_oc"] = streams

# Filter POST us_start avec V4 non-NaN et stream NaN
gap_mask = (df["mins_et"] >= 570) & df["open_cash"].notna() & df["stream_oc"].isna()
gaps = df.loc[gap_mask, ["ts_event", "date_et", "mins_et", "open_cash", "session_date_trading"]].copy()
gaps["session_date_trading"] = pd.to_datetime(gaps["session_date_trading"]).dt.date
gaps["date_et_str"] = gaps["date_et"].astype(str)

print(f"GAPS POST-us_start : {len(gaps)}")
print(f"Days uniques avec gap : {gaps['date_et_str'].nunique()}")
print("\nTop 5 days with gaps:")
top = gaps.groupby("date_et_str").size().sort_values(ascending=False).head(5)
print(top)

print("\nSample 10 gap rows:")
print(gaps.head(10).to_string())

# Pour 1 jour gap : verifie si bar mins_et=570 existe dans V4
day = gaps["date_et"].iloc[0]
day_bars = df[df["date_et"] == day][["mins_et", "session_date_trading"]]
print(f"\nDay {day} : mins_et values around 570: {sorted(day_bars[(day_bars['mins_et'] >= 565) & (day_bars['mins_et'] <= 580)]['mins_et'].tolist())}")
print(f"  session_date_trading: {day_bars['session_date_trading'].iloc[0]}")
