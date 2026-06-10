"""Test load MGC.v.0 07/05/2026 - debug ohlcv."""
import duckdb
from pathlib import Path

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
pattern = (ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"
           / "symbol=MGC.v.0" / "**" / "*.parquet").as_posix()
print(f"Pattern: {pattern}")

con = duckdb.connect()
con.execute("SET TimeZone='UTC';")

# Test 1 : count all
df1 = con.execute(f"SELECT COUNT(*) FROM read_parquet('{pattern}', union_by_name=True)").fetchdf()
print(f"Total bars MGC.v.0: {df1.iloc[0, 0]}")

# Test 2 : range ts_event
df2 = con.execute(f"""
    SELECT MIN(ts_event) as min_ts, MAX(ts_event) as max_ts
    FROM read_parquet('{pattern}', union_by_name=True)
""").fetchdf()
print(f"Range: {df2.iloc[0, 0]} → {df2.iloc[0, 1]}")

# Test 3 : 07/05 specifically
df3 = con.execute(f"""
    SELECT ts_event, open, high, low, close, volume
    FROM read_parquet('{pattern}', union_by_name=True)
    WHERE ts_event >= TIMESTAMP '2026-05-07 00:00:00'
      AND ts_event <  TIMESTAMP '2026-05-08 00:00:00'
    ORDER BY ts_event
    LIMIT 5
""").fetchdf()
print(f"\n07/05/2026 first 5 bars:")
print(df3)
n_07 = con.execute(f"""SELECT COUNT(*) FROM read_parquet('{pattern}', union_by_name=True)
    WHERE ts_event >= TIMESTAMP '2026-05-07' AND ts_event < TIMESTAMP '2026-05-08'""").fetchdf().iloc[0, 0]
print(f"  N total 07/05: {n_07}")
