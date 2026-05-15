"""Probe V4 batch coverage IB columns par symbole pour fix BUG #2."""
import pandas as pd

ROOT = "C:/TRADING_SIERRA_CHART_AUTO" if __import__("os").name == "nt" else "."

for sym in ["ES.c.0", "NQ.c.0", "MGC.c.0"]:
    p = f"{ROOT}/DATA/datasets/v4_enriched/symbol={sym}/year=2026/month=05/data.parquet"
    try:
        df = pd.read_parquet(p)
    except FileNotFoundError:
        print(f"{sym}: parquet absent")
        continue
    df_sdt = df[df["session_date_trading"].notna()]
    if df_sdt.empty:
        continue
    last_sdt = df_sdt["session_date_trading"].iloc[-1]
    df_t = df_sdt[df_sdt["session_date_trading"] == last_sdt]
    ib_cols = [c for c in df_t.columns if c.startswith("ib_")]
    print(f"\n=== {sym} sdt={last_sdt} bars={len(df_t)} ib_cols={ib_cols} ===")
    for c in ib_cols:
        nonnan = df_t[c].dropna()
        if len(nonnan):
            print(f"  {c:25s} : n_non_nan={len(nonnan):4d}/{len(df_t):4d}  last={nonnan.iloc[-1]}")
        else:
            print(f"  {c:25s} : ALL NaN today")
