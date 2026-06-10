"""Test comparaison Live OHLCV cache vs Historical parquet enrichi."""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO")
TICK_SIZE = 0.25
TICK_VALUE = {"ES": 1.25, "NQ": 0.5}

print("=" * 80)
print("  COMPARAISON LIVE CACHE vs HISTORICAL PARQUET")
print("=" * 80)

now = datetime.now(timezone.utc)

for sym in ["ES", "NQ"]:
    sym_full = f"{sym}.c.0"

    # Live cache
    live_path = ROOT / "DATA" / "LIVE_CACHE" / f"{sym}_c_0_last.json"
    if live_path.exists():
        with open(live_path, "r", encoding="utf-8") as f:
            live = json.load(f)
        live_close = live.get("close")
        live_ts = live.get("ts_event_iso")
        live_latency = live.get("latency_s")
    else:
        live_close = None
        live_ts = "N/A"
        live_latency = None

    # Historical parquet (dernier disponible)
    root_data = ROOT / "DATA" / "datasets" / "v4_enriched"
    files = sorted(
        (root_data / f"symbol={sym_full}").glob("year=*/month=*/data.parquet"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    hist_close = None
    hist_ts = "N/A"
    hist_age_min = None
    if files:
        df = pd.read_parquet(files[0])
        if not df.empty:
            last = df.iloc[-1]
            hist_close = float(last["close"])
            hist_ts_raw = last["ts_event"]
            hist_dt = pd.to_datetime(hist_ts_raw, utc=True)
            hist_ts = hist_dt.isoformat()
            hist_age_min = (now - hist_dt).total_seconds() / 60

    # Calcul delta
    if live_close is not None and hist_close is not None:
        delta_pts = live_close - hist_close
        delta_ticks = delta_pts / TICK_SIZE
        delta_usd = delta_ticks * TICK_VALUE.get(sym, 1) * 3  # 3 micros
    else:
        delta_pts = None
        delta_ticks = None
        delta_usd = None

    print(f"\n{sym} :")
    print(f"  HISTORICAL parquet : close={hist_close} ts={hist_ts}")
    print(f"                       age={hist_age_min:.1f}min" if hist_age_min else "                       age=N/A")
    print(f"  LIVE cache         : close={live_close} ts={live_ts}")
    print(f"                       latency={live_latency}s")
    if delta_pts is not None:
        print(f"  DELTA              : {delta_pts:+.2f} pts = {delta_ticks:+.1f} ticks = ${delta_usd:+.2f} (3 micros)")
        print(f"  → Slippage entry POTENTIEL evite avec Live : {abs(delta_ticks):.1f} ticks")

print("\n" + "=" * 80)
print("  Si DELTA > 5 ticks : Live OHLCV cache va resoudre le slippage 23t")
print("  Si DELTA < 2 ticks : marche calme, gain marginal")
print("=" * 80)
