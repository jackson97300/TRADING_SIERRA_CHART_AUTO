"""Diagnostic : load MQ_Lite + asof merge avec OHLCV pour voir pourquoi mq=0.0%."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pandas as pd

from load_mq_levels import load_mq_levels, attach_mq_distances

today = date(2026, 4, 28)
for sym in ["ES", "NQ"]:
    print(f"\n=== {sym} ===")
    levels = load_mq_levels(sym, today, today)
    print(f"  levels rows: {len(levels)}")
    if not levels.empty:
        print(f"  ts range: {levels['ts_event'].min()} -> {levels['ts_event'].max()}")
        print(f"  cols: {list(levels.columns)[:8]}...")
        # Check NaN sur mq_call
        non_null = levels['mq_call'].notna().sum()
        print(f"  mq_call non-null: {non_null}/{len(levels)}")

    # Charger OHLCV pour merge
    ohlcv_path = (Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/databento/GLBX.MDP3/ohlcv-1m") /
                  f"symbol={sym}.c.0/year=2026/month=4/day=28/data.parquet")
    if not ohlcv_path.exists():
        print(f"  OHLCV missing: {ohlcv_path}")
        continue
    bars = pd.read_parquet(ohlcv_path)
    bars = bars.reset_index()
    bars["ts_event"] = pd.to_datetime(bars["ts_event"]).dt.tz_localize(None)
    print(f"  bars: {len(bars)}, ts range: {bars['ts_event'].min()} -> {bars['ts_event'].max()}")

    # Tester attach
    try:
        merged = attach_mq_distances(bars, levels, tick_size=0.25)
        if "dist_mq_call" in merged.columns:
            n_filled = merged["dist_mq_call"].notna().sum()
            print(f"  AFTER attach: dist_mq_call non-null = {n_filled}/{len(merged)}")
        else:
            print(f"  AFTER attach: dist_mq_call COLUMN MISSING")
            print(f"  cols added: {set(merged.columns) - set(bars.columns)}")
    except Exception as e:
        print(f"  attach FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
