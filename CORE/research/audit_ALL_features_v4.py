"""Audit COMPLET de toutes les features V4 enriched ES + NQ.

Pour chaque colonne :
- % NaN total
- % NaN sur les 100 dernieres bars (live)
- Status : OK / WARNING / CASSE
"""
import pyarrow.parquet as pq
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for sym in ["NQ", "ES"]:
    print(f"\n{'='*78}")
    print(f"  TOUTES FEATURES V4 ENRICHED — {sym}.c.0 mai 2026")
    print(f"{'='*78}")
    fp = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={sym}.c.0" / "year=2026" / "month=05" / "data.parquet"
    if not fp.exists():
        print(f"  NOT FOUND")
        continue
    df = pq.read_table(fp).to_pandas()
    print(f"  N bars: {len(df)}")
    print(f"  Cols total: {len(df.columns)}")
    last100 = df.tail(100)

    cols_casse = []      # >80% NaN
    cols_warning = []    # 30-80% NaN
    cols_ok = []         # <30% NaN

    for col in df.columns:
        if col in ("ts_event", "year", "month", "symbol"):
            continue
        n_nan = df[col].isna().sum()
        pct_nan = 100 * n_nan / len(df)
        n_nan_100 = last100[col].isna().sum()
        pct_nan_100 = 100 * n_nan_100 / 100
        if pct_nan > 80:
            cols_casse.append((col, pct_nan, pct_nan_100))
        elif pct_nan > 30:
            cols_warning.append((col, pct_nan, pct_nan_100))
        else:
            cols_ok.append((col, pct_nan, pct_nan_100))

    print(f"\n  COLS CASSE (>80% NaN total) : {len(cols_casse)}")
    print(f"  COLS WARNING (30-80% NaN)   : {len(cols_warning)}")
    print(f"  COLS OK (<30% NaN)          : {len(cols_ok)}")

    print(f"\n  === CASSE (>80% NaN) — top 50 ===")
    for col, pct, pct_100 in sorted(cols_casse, key=lambda x: -x[1])[:50]:
        last_val = df[col].dropna().iloc[-1] if not df[col].dropna().empty else "N/A"
        print(f"    {col:<45} total_nan={pct:.1f}% last100_nan={pct_100:.0f}% sample={str(last_val)[:30]}")

    if len(cols_casse) > 50:
        print(f"    ... et {len(cols_casse) - 50} autres cassees")

    print(f"\n  === WARNING (30-80% NaN) ===")
    for col, pct, pct_100 in sorted(cols_warning, key=lambda x: -x[1]):
        print(f"    {col:<45} total_nan={pct:.1f}% last100_nan={pct_100:.0f}%")
