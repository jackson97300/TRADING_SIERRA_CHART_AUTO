"""Check parquet latency on VPS — called once for diagnostic, not used by bot."""
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

root = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/datasets/v4_enriched")
for sym in ["ES.c.0", "NQ.c.0"]:
    files = sorted(
        (root / f"symbol={sym}").glob("year=*/month=*/data.parquet"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        print(f"{sym}: no parquet")
        continue
    p = files[0]
    df = pd.read_parquet(p)
    if df.empty:
        print(f"{sym}: empty")
        continue
    last_ts = df.iloc[-1].get("ts_event")
    last_dt = pd.to_datetime(last_ts, utc=True)
    now = datetime.now(timezone.utc)
    delta_min = (now - last_dt).total_seconds() / 60
    file_age_sec = (now.timestamp() - p.stat().st_mtime)
    print(f"{sym}: last_bar_ts={last_dt} age_bar={delta_min:.1f}min file_modified_age={file_age_sec:.0f}s")
