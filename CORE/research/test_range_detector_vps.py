"""Test range_detector_v3 sur NQ live VPS — bars fraiches.

Pour run sur VPS : lit directement le parquet V4 NQ dans DATA/datasets/v4_enriched.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).parent.parent.parent
_CORE = _ROOT / "CORE"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from CORE.range_detector_v3 import RangeDetectorV3  # noqa


def main():
    parquet_path = _ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=NQ.c.0" / "year=2026" / "month=05" / "data.parquet"
    if not parquet_path.exists():
        print(f"PARQUET ABSENT: {parquet_path}")
        return

    df = pd.read_parquet(parquet_path)
    print(f"Loaded NQ V4 mai 2026 : shape={df.shape}")

    ts_col = None
    for c in ("ts_utc", "ts_event"):
        if c in df.columns:
            ts_col = c
            break
    if ts_col:
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
        today = pd.Timestamp("2026-05-11", tz="UTC")
        df_today = df[df[ts_col] >= today].copy()
        if len(df_today) >= 60:
            print(f"Bars aujourd'hui : {len(df_today)}")
            print(f"Range temporel : {df_today[ts_col].iloc[0]} -> {df_today[ts_col].iloc[-1]}")
        else:
            df_today = df.tail(240).copy()
            print(f"Fallback 240 bars : {df_today[ts_col].iloc[0]} -> {df_today[ts_col].iloc[-1]}")
    else:
        df_today = df.tail(240).copy()
        print(f"No ts col, fallback 240 bars")

    print(f"Stats prix today :")
    print(f"  open  : {df_today['open'].iloc[0]:.2f}")
    print(f"  high  : {df_today['high'].max():.2f}")
    print(f"  low   : {df_today['low'].min():.2f}")
    print(f"  close : {df_today['close'].iloc[-1]:.2f}")

    det = RangeDetectorV3(sym="NQ")
    result = det.detect(df_today)

    print()
    print(f"=== VERDICT RANGE DETECTOR V3 ===")
    print(f"is_range          : {result.is_range}")
    print(f"is_range_macro    : {result.is_range_macro}")
    print(f"is_range_micro    : {result.is_range_micro}")
    print(f"n_macro_ok        : {result.n_macro_ok}/7 (seuil {det.min_macro_criteres})")
    print(f"reason            : {result.reason}")
    print()
    print(f"range_high_zone   : {result.range_high_zone}")
    print(f"range_low_zone    : {result.range_low_zone}")
    print(f"range_high_raw    : {result.range_high_raw}")
    print(f"range_low_raw     : {result.range_low_raw}")
    print(f"range_size_ticks  : {result.range_size_ticks}")
    print(f"range_pos         : {result.range_pos:.3f}")
    print()
    print(f"signal_hint       : {result.signal_hint}")
    print(f"range_break_risk  : {result.range_break_risk}")


if __name__ == "__main__":
    main()
