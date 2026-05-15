"""Probe V4 mai VPS pour debug seed."""
import pandas as pd
df = pd.read_parquet("DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=05/data.parquet")
print(f"rows={len(df)} ts range {df['ts_event'].min()} -> {df['ts_event'].max()}")
print(f"date_et range: {df['date_et'].min()} -> {df['date_et'].max()}")
print(f"\nDate counts last 10:")
print(df['date_et'].astype(str).value_counts().sort_index().tail(10))

# Today filter
import datetime
today = datetime.datetime.now(datetime.timezone.utc).date()
mask_today = df['date_et'] == today
print(f"\nToday ({today}): {mask_today.sum()} bars")
if mask_today.sum() > 0:
    last_today = df[mask_today].iloc[-1]
    for c in ['ts_event','date_et','mins_et','asia_high','asia_low','asia_open','london_open','ny_open','open_cash','price_1030','session_date_trading']:
        v = last_today.get(c, 'ABSENT')
        print(f"  {c:25s} = {v}")
