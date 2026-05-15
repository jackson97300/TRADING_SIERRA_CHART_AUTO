"""Verifie directement V4 sur quelques bars Sunday March 31."""
import pandas as pd
df = pd.read_parquet("DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet")

# Le V4 a une colonne date_et ? Re-verifier
print("Cols contenant 'date':", [c for c in df.columns if 'date' in c.lower()])

# Sur les bars 2026-04-01 UTC, regarder date_et selon V4 (et NOT my derived)
mask = (pd.to_datetime(df["ts_event"]) >= "2026-04-01 00:00") & (pd.to_datetime(df["ts_event"]) < "2026-04-01 04:00")
sub = df.loc[mask, ["ts_event", "session_date_trading", "open_cash", "price_1030"]].head(20)
print("\nFirst 20 rows 2026-04-01 UTC 00:00-04:00:")
print(sub.to_string())

# Verifier le min/max ts_event de V4
print(f"\nV4 ts_event range : {df['ts_event'].min()} -> {df['ts_event'].max()}")

# Existe-t-il une bar 2026-03-31 09:30 ET = 13:30 UTC ?
mask2 = (pd.to_datetime(df["ts_event"]) >= "2026-03-31 13:30") & (pd.to_datetime(df["ts_event"]) < "2026-03-31 13:35")
sub2 = df.loc[mask2, ["ts_event", "session_date_trading", "open_cash", "price_1030", "close"]]
print(f"\nBars 2026-03-31 13:30-13:35 UTC (= 09:30-09:35 ET): {len(sub2)}")
print(sub2.to_string())
