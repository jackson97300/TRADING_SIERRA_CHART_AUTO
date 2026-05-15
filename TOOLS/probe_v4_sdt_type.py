"""Probe types sdt + date_et pour valider seed IB."""
import pandas as pd

df = pd.read_parquet("C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=05/data.parquet")
sdt = df[df["session_date_trading"].notna()]["session_date_trading"].iloc[-1]
print(f"sdt type: {type(sdt).__name__}, value: {sdt}, repr: {sdt!r}")
df_t = df[df["session_date_trading"] == sdt]
df_ib = df_t[df_t["ib_high"].notna()]
last = df_ib.iloc[-1]
if "date_et" in df.columns:
    de = last["date_et"]
    print(f"date_et type: {type(de).__name__}, value: {de}, repr: {de!r}")
else:
    print("date_et col MISSING from V4 batch")
print(f"sdt == date_et : {sdt == last.get('date_et') if 'date_et' in df.columns else 'N/A'}")
