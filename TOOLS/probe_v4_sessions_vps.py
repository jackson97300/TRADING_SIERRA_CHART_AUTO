"""Probe V4 batch VPS : verifier coverage colonnes sessions par symbole.

But : comprendre pourquoi seed _seed_sessions_swings_from_warmup donne n_values=3
sur NQ/MGC mais n=9 sur ES sur le meme timestamp (V4 partial Phase B).
"""
import pandas as pd

ROOT = "C:/TRADING_SIERRA_CHART_AUTO" if __import__("os").name == "nt" else "."

SESSIONS_COLS = [
    "asia_high", "asia_low", "london_high", "london_low",
    "us_high", "us_low", "after_high", "after_low",
    "asia_open", "london_open", "ny_open", "after_open",
]

for sym in ["ES.c.0", "NQ.c.0", "MGC.c.0"]:
    p = f"{ROOT}/DATA/datasets/v4_enriched/symbol={sym}/year=2026/month=05/data.parquet"
    try:
        df = pd.read_parquet(p)
    except FileNotFoundError:
        print(f"{sym}: parquet absent")
        continue
    if "session_date_trading" not in df.columns:
        print(f"{sym}: pas de session_date_trading col")
        continue
    df_sdt = df[df["session_date_trading"].notna()]
    if df_sdt.empty:
        print(f"{sym}: 0 bars avec sdt")
        continue
    last_sdt = df_sdt["session_date_trading"].iloc[-1]
    df_today = df_sdt[df_sdt["session_date_trading"] == last_sdt]
    print(f"\n=== {sym} sdt={last_sdt} bars_today={len(df_today)} total_bars={len(df)} ===")
    # Simulate seed actuel
    df_valid = df_today[df_today["asia_high"].notna()] if "asia_high" in df_today.columns else df_today
    if len(df_valid):
        last = df_valid.iloc[-1]
        seed_n = sum(
            1 for c in SESSIONS_COLS
            if c in df_today.columns
            and last.get(c) is not None
            and not (isinstance(last.get(c), float) and pd.isna(last.get(c)))
        )
        print(f"  SEED ACTUEL (last_row asia_high non-NaN) : n_values={seed_n}")
        print(f"  >> seed values : ny_open={last.get('ny_open')}, london_open={last.get('london_open')}")
    # Coverage par colonne (le potentiel max si on prenait MAX non-NaN par col)
    print(f"  COVERAGE coupole par colonne :")
    for c in SESSIONS_COLS:
        if c in df_today.columns:
            nonnan = df_today[c].dropna()
            if len(nonnan):
                print(f"    {c:20s} n_non_nan={len(nonnan):4d}/{len(df_today):4d}  last_val={nonnan.iloc[-1]}")
            else:
                print(f"    {c:20s} ALL NaN today")
