"""Test connexion Databento + verifier acces aux symboles necessaires Phase D Gold."""
import os
from datetime import date, timedelta
from pathlib import Path

# Load .env
env_file = Path("C:/TRADING_SIERRA_CHART_AUTO/.env")
if env_file.exists():
    for line in env_file.read_text().split("\n"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

api_key = os.environ.get("DATABENTO_API_KEY")
if not api_key:
    print("ERROR: no DATABENTO_API_KEY")
    exit(1)

import databento as db
client = db.Historical(api_key)

GOLD_PHASE_D_SYMBOLS = ["DX.c.0", "6E.c.0", "SI.c.0", "ZN.c.0", "ZB.c.0", "MGC.v.0"]
DATASET = "GLBX.MDP3"

# Use Thursday 07/05/2026 (weekday CME open)
test_start = date(2026, 5, 7)
test_end = date(2026, 5, 8)

print(f"Testing {DATASET} for {test_start} -> {test_end}\n")
print(f"{'Symbol':<10}{'Status':<12}{'N bars':<10}{'Note'}")
print("-" * 70)

for sym in GOLD_PHASE_D_SYMBOLS:
    try:
        data = client.timeseries.get_range(
            dataset=DATASET,
            symbols=[sym],
            schema="ohlcv-1m",
            start=test_start.isoformat(),
            end=test_end.isoformat(),
            stype_in="continuous",
        )
        df = data.to_df()
        n_bars = len(df)
        if n_bars > 0:
            print(f"{sym:<10}{'OK':<12}{n_bars:<10}1d test successful")
        else:
            print(f"{sym:<10}{'EMPTY':<12}{0:<10}symbol exists but no data")
    except Exception as e:
        err_short = str(e)[:60]
        print(f"{sym:<10}{'FAIL':<12}{0:<10}{err_short}")
