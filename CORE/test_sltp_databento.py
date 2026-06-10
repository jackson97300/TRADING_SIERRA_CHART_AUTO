"""Test rapide SLTPEngine sur bar Databento enrichi."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

import pandas as pd
from mia_sltp import SLTPEngine

df = pd.read_parquet(ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet")
last = df.iloc[-1]
print(f"Bar ts={last.get('ts_event')} close={last.get('close')}")
print(f"Cols dans bar : {len(last.index)}")
key_dist = [c for c in last.index if c.startswith('dist_')][:10]
print(f"Sample dist_* cols : {key_dist}")

sltp = SLTPEngine(symbol="ES")
for direction, name in [(-1, "SHORT"), (1, "LONG")]:
    try:
        result = sltp.evaluate_single(last.to_dict(), direction)
        print(f"\nSLTP {name}:")
        print(f"  valid: {result.valid}")
        if result.valid:
            print(f"  sl_ticks: {result.sl_ticks}")
            print(f"  tp1_ticks: {result.tp1_ticks}")
            print(f"  sl_wall: {result.sl_wall}")
            print(f"  tp1_wall: {result.tp1_wall}")
        else:
            print(f"  reason: {getattr(result, 'reason', 'no reason')}")
    except Exception as e:
        print(f"\nSLTP {name} FAILED: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
