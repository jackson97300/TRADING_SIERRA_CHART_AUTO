"""Check parquet v4_enriched : combien de cols + categories de features."""
import pandas as pd
from pathlib import Path

BASE = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched")

for sym in ["ES", "NQ"]:
    p = BASE / f"symbol={sym}.c.0/year=2026/month=04/data.parquet"
    if not p.exists():
        print(f"{sym}: MISSING {p}")
        continue
    df = pd.read_parquet(p)
    print(f"\n=== {sym} ===")
    print(f"  shape: {df.shape}")
    print(f"  ts_event range: {df['ts_event'].min()} -> {df['ts_event'].max()}")

    # Filter today only
    df_today = df[pd.to_datetime(df['ts_event']).dt.date == pd.Timestamp("2026-04-28").date()]
    print(f"  TODAY ({sym}): {df_today.shape}")

    # Last 3 bars
    last_3 = df_today.tail(3)
    print(f"  last 3 ts_event:")
    for ts in last_3['ts_event']:
        print(f"    {ts}")

    # Features categories (count cols by prefix)
    cats = {}
    for col in df.columns:
        parts = col.split('_')
        if len(parts) >= 2:
            prefix = parts[0]
        else:
            prefix = col
        cats[prefix] = cats.get(prefix, 0) + 1
    print(f"  cols categories (top 15):")
    for prefix, cnt in sorted(cats.items(), key=lambda x: -x[1])[:15]:
        print(f"    {prefix:20s} : {cnt}")

    # Phase B specific cols expected
    phase_b_markers = [
        'absorb', 'aggressor', 'bn_', 'cluster', 'edge_', 'edge_zone',
        'footprint', 'game_changer', 'mp_', 'open_type', 'rvol_',
        'session_', 'swing_', 'value_area', 'vwap_diff',
        'long_up', 'long_dn', 'big_'
    ]
    print(f"  Phase B markers presence (sample):")
    for m in phase_b_markers:
        matching = [c for c in df.columns if m in c.lower()]
        if matching:
            non_null = df[matching[0]].notna().sum()
            print(f"    {m:20s} : {len(matching)} cols (1st={matching[0]} non-null={non_null}/{len(df)})")
        else:
            print(f"    {m:20s} : ABSENT")
