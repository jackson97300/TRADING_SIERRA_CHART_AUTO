"""Verifie open_type ES+NQ avril 2026 apres rebuild trades 04-27 + 04-29 + 04-30."""
import pandas as pd
import glob

for sym in ("ES.c.0", "NQ.c.0"):
    p = f"DATA/datasets/v4_enriched/symbol={sym}/year=2026/month=04/data.parquet"
    df = pd.read_parquet(p)
    print(f"=== {sym} avril 2026 ===")
    print(f"  Rows: {len(df)}  Cols: {len(df.columns)}")
    if "ts" in df.columns:
        df["d"] = pd.to_datetime(df["ts"]).dt.date
    elif "ts_event" in df.columns:
        df["d"] = pd.to_datetime(df["ts_event"]).dt.date
    else:
        idx = df.index
        df["d"] = pd.to_datetime(idx).date
    days = sorted(df["d"].unique())
    print(f"  Days: {len(days)} ({days[0]} -> {days[-1]})")

    # Check open_type / day_type if present
    if "open_type" in df.columns:
        per_day = df.groupby("d")["open_type"].agg(lambda s: (s == "UNKNOWN").mean())
        unknown_days = (per_day == 1.0).sum()
        print(f"  open_type=UNKNOWN full-day: {unknown_days}/{len(per_day)}")
        # detail days 27-30
        for d in [pd.Timestamp("2026-04-27").date(),
                  pd.Timestamp("2026-04-28").date(),
                  pd.Timestamp("2026-04-29").date(),
                  pd.Timestamp("2026-04-30").date()]:
            if d in per_day.index:
                ratio = per_day.loc[d]
                print(f"    {d}: UNKNOWN ratio = {ratio:.2%}")
    else:
        print("  [WARN] open_type non present (raw V4 sans Phase B)")
    print()
