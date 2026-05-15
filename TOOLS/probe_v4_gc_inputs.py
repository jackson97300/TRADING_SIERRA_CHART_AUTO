"""Verifie inputs game_changers + rolling features dans V4 ES avril."""
import pandas as pd

df = pd.read_parquet("DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet")

inputs_gc = [
    "date_et", "mins_et", "session_date_trading",
    "open_cash", "price_1030",
    "ib_high", "ib_low", "ib_atr",
    "sess_high", "sess_low", "close",
    "prev_vah", "prev_val", "prev_vpoc",
    "pdh", "pdl",
]
outputs_gc = ["open_type", "open_zone", "open_direction", "open_bias_conf", "day_type", "profile_shape"]

inputs_rolling = [
    "ts_event", "close", "high", "low", "volume",
    "delta_long", "vwap_slope_10", "dist_vwap_d", "cvd_day", "atr",
    "finish_strength", "va_position_pct", "ib_position_pct",
    "vwap_d_side", "ib_range_atr", "ib_broken_up", "ib_broken_down",
    "dist_vwap_d_atr", "delta_day_dir", "dist_sess_high", "dist_sess_low",
    "ib_range_ticks",
]

print("=== INPUTS GAME_CHANGERS ===")
for c in inputs_gc:
    if c in df.columns:
        nn = df[c].notna().sum()
        print(f"  [OK]  {c:25s} non-null={nn}/{len(df)}")
    else:
        print(f"  [MISS] {c}")

print("\n=== OUTPUTS GAME_CHANGERS (oracle) ===")
for c in outputs_gc:
    if c in df.columns:
        nn = df[c].notna().sum()
        if df[c].dtype.kind in "iufc":
            uniq = df[c].nunique()
            print(f"  [OK]  {c:25s} non-null={nn}/{len(df)} unique={uniq}")
        else:
            print(f"  [OK]  {c:25s} non-null={nn}/{len(df)}")
    else:
        print(f"  [MISS] {c}")

print("\n=== INPUTS ROLLING_FEATURES_BASIC ===")
for c in inputs_rolling:
    if c in df.columns:
        nn = df[c].notna().sum()
        print(f"  [OK]  {c:25s} non-null={nn}/{len(df)}")
    else:
        print(f"  [MISS] {c}")
