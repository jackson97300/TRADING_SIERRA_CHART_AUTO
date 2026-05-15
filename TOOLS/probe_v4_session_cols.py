"""Liste cols V4 ES avril 2026 pour designer V4 oracle test."""
import pandas as pd

df = pd.read_parquet("DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet")
print(f"Rows: {len(df)}  Cols: {len(df.columns)}")

# Categories pour V4 oracle
groups = {
    "session_meta": ["ts_event", "ts_recv", "date_et", "mins_et", "session_date_trading", "session_id", "is_rth"],
    "ohlcv": ["open", "high", "low", "close", "volume"],
    "ctx_basic": [c for c in df.columns if c.startswith("ctx_") and not c.endswith("_5") and not c.endswith("_10")][:5],
    "ctx_rolling": [c for c in df.columns if c.startswith("ctx_")][:15],
    "game_changers": [c for c in df.columns if c in ("open_type", "day_type", "profile_shape", "open_cash", "price_1030")],
    "regime": [c for c in df.columns if c.startswith("regime_")],
    "rvol": [c for c in df.columns if c.startswith("rvol_")][:5],
    "amd": [c for c in df.columns if c.startswith("amd_")][:8],
    "phase_b_plus": [c for c in df.columns if c.startswith("absorb_") or c.startswith("color_") or c.startswith("long_")][:8],
    "diag_proxy": [c for c in df.columns if "diag_imbalance" in c or "large_trader" in c],
}
for g, cols in groups.items():
    avail = [c for c in cols if c in df.columns]
    print(f"\n{g} ({len(avail)} present):")
    for c in avail[:10]:
        nn = df[c].notna().sum()
        print(f"  {c:35s} non-null={nn}/{len(df)}")
