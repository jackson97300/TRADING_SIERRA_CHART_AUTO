"""Check VIX features dans MGC V4 enriched."""
import pyarrow.parquet as pq
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]

fp = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=MGC.c.0" / "year=2026" / "month=04" / "data.parquet"
if not fp.exists():
    print(f"NOT FOUND: {fp}")
else:
    df = pq.read_table(fp).to_pandas()
    print(f"MGC avril 2026 : {len(df)} bars, {len(df.columns)} cols")
    vix_cols = [c for c in df.columns if "vix" in c.lower() or "VIX" in c]
    print(f"VIX cols dans MGC parquet : {vix_cols}")
    if vix_cols:
        for c in vix_cols:
            n_nan = df[c].isna().sum()
            pct_nan = round(100 * n_nan / len(df), 1)
            print(f"  {c}: nan={pct_nan}% sample={df[c].dropna().head(3).tolist()}")
    else:
        print("  Aucune feature VIX dans MGC parquet")
