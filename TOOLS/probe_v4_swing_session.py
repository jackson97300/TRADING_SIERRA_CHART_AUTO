"""Probe V4 batch swing session columns + last bar."""
import pandas as pd
df = pd.read_parquet("DATA/datasets/v4_enriched/symbol=NQ.c.0/year=2026/month=05/data.parquet")
swing_cols = [c for c in df.columns if 'swing' in c.lower()]
print(f"V4 NQ rows={len(df)}, swing cols : {swing_cols}")

# Derniere bar valide avec _last_swing_high_price
df_valid = df[df["_last_swing_high_price"].notna() if "_last_swing_high_price" in df.columns else False]
if len(df_valid):
    last = df_valid.iloc[-1]
    print(f"\nDerniere V4 valide ts={last.get('ts_event')}")
    for c in swing_cols:
        print(f"  {c:40s} = {last.get(c)}")
    # Asia + sessions ranges
    for c in ["asia_high","asia_low","asia_open","london_high","london_low","us_high","us_low","session_date_trading","session_id"]:
        if c in df.columns:
            print(f"  {c:40s} = {last.get(c)}")
    # Today's bars (sdt = 2026-05-15)
    today = df[df["session_date_trading"] == pd.Timestamp("2026-05-15").date()]
    print(f"\n\nBars session_date_trading=2026-05-15 : {len(today)}")
    if len(today):
        print(f"asia_low range (today) : {today['asia_low'].min()} - {today['asia_low'].max()}")
        print(f"asia_high range : {today['asia_high'].min()} - {today['asia_high'].max()}")
        print(f"_last_swing_low_price range : {today['_last_swing_low_price'].dropna().min()} - {today['_last_swing_low_price'].dropna().max()}")
