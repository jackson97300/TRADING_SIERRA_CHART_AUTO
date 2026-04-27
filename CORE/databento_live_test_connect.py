"""
databento_live_test_connect.py — Sprint 0 Action 1 : test connect Databento Live API.

Objectif : verifier que l'abonnement Databento Live est ACTIF sur le compte
Jackson AVANT de coder le pipeline live (mandate Plan agent ULTRATHINK 27/04 23h).

Si auth 401/403 : Standard $179/mo couvre Historical only. Live = upgrade
~+$199/mo requis. STOP migration jusqu'a upgrade.

Usage :
  python -X utf8 CORE/databento_live_test_connect.py
  python -X utf8 CORE/databento_live_test_connect.py --duration 30 --symbol ESM6

Output :
  - Connection status (success / auth_error / network_error)
  - 5 premieres bars OHLCV-1m recues (ts, OHLCV)
  - Latence mesuree (delta ts_event vs reception time)

Auteur : MIA Trading System V2
Date   : 2026-04-27 23:00
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Charger .env si python-dotenv installe (pour DATABENTO_API_KEY)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=120,
                        help="Max seconds to wait for bars (default 120)")
    parser.add_argument("--symbol", default="ESM6",
                        help="CME symbol to subscribe (default ESM6 = ES juin 2026)")
    parser.add_argument("--n-bars", type=int, default=5,
                        help="Stop after N bars received (default 5)")
    args = parser.parse_args()

    print("=" * 70)
    print("SPRINT 0 ACTION 1 - Test connect Databento Live API")
    print("=" * 70)

    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        print("[FATAL] DATABENTO_API_KEY missing in env or .env")
        print("       Set via: export DATABENTO_API_KEY=db-... or add to .env")
        sys.exit(1)
    print(f"  API key found : {api_key[:8]}...{api_key[-4:] if len(api_key) > 12 else ''}")

    try:
        import databento as db
    except ImportError:
        print("[FATAL] databento SDK not installed. Run: pip install databento")
        sys.exit(1)
    print(f"  databento SDK : {db.__version__}")

    print(f"  Subscribe target : dataset=GLBX.MDP3 schema=ohlcv-1m symbols=[{args.symbol}]")
    print(f"  Duration max : {args.duration}s, stop after {args.n_bars} bars")
    print()

    bars_received = []
    auth_error = False
    other_error = None
    start_time = time.time()
    first_bar_time = None

    try:
        client = db.Live(key=api_key)

        def callback(record):
            """Callback per record received."""
            nonlocal first_bar_time
            now = time.time()
            if first_bar_time is None:
                first_bar_time = now

            # Extract OHLCV bar fields (databento Live records have specific schema)
            try:
                ts_event = record.ts_event  # nanoseconds since epoch UTC
                ts_dt = datetime.fromtimestamp(ts_event / 1e9, tz=timezone.utc)
                latency_ms = (now - ts_event / 1e9) * 1000
                bar_info = {
                    "ts_event": ts_dt.isoformat(),
                    "open": getattr(record, "open", None),
                    "high": getattr(record, "high", None),
                    "low": getattr(record, "low", None),
                    "close": getattr(record, "close", None),
                    "volume": getattr(record, "volume", None),
                    "latency_ms": round(latency_ms, 1),
                    "symbol": getattr(record, "instrument_id", None),
                }
                bars_received.append(bar_info)
                print(f"  [BAR {len(bars_received)}] {bar_info['ts_event']} "
                      f"O={bar_info['open']} H={bar_info['high']} L={bar_info['low']} "
                      f"C={bar_info['close']} V={bar_info['volume']} "
                      f"lat={bar_info['latency_ms']}ms")
            except AttributeError as e:
                # Probably a SymbolMappingMsg or system message, skip
                pass

        # Subscribe
        client.subscribe(
            dataset="GLBX.MDP3",
            schema="ohlcv-1m",
            symbols=[args.symbol],
            stype_in="raw_symbol",
        )
        client.add_callback(callback)
        client.start()
        print("  Connection initiated, waiting for bars...")
        print()

        # Wait until duration elapsed or n_bars received
        deadline = start_time + args.duration
        while len(bars_received) < args.n_bars and time.time() < deadline:
            time.sleep(0.5)

        client.stop()

    except db.common.error.BentoAuthenticationError as e:
        print()
        print(f"[AUTH ERROR] {e}")
        print()
        print("  DIAGNOSTIC : Live tier likely NOT activated on your subscription.")
        print("  Standard $179/mo = Historical only. Live = +$199/mo upgrade.")
        print("  ACTION : Visit https://databento.com/portal/billing to upgrade Live tier.")
        auth_error = True
    except db.common.error.BentoError as e:
        print(f"[DATABENTO ERROR] {type(e).__name__}: {e}")
        other_error = str(e)
    except Exception as e:
        print(f"[UNEXPECTED ERROR] {type(e).__name__}: {e}")
        other_error = str(e)

    # Verdict
    print()
    print("=" * 70)
    print("VERDICT SPRINT 0 ACTION 1")
    print("=" * 70)
    print(f"  Bars received    : {len(bars_received)} / {args.n_bars}")
    print(f"  Duration elapsed : {time.time() - start_time:.1f}s")
    if first_bar_time:
        print(f"  Time to 1st bar  : {first_bar_time - start_time:.1f}s")
    if bars_received:
        latencies = [b["latency_ms"] for b in bars_received if b["latency_ms"] is not None]
        if latencies:
            print(f"  Latency median   : {sorted(latencies)[len(latencies)//2]:.1f}ms")
            print(f"  Latency max      : {max(latencies):.1f}ms")

    if auth_error:
        print()
        print("  STATUS : AUTH_FAIL - Live tier NOT activated")
        print("  NEXT   : Jackson upgrade subscription, re-run this test")
        sys.exit(2)
    elif len(bars_received) > 0:
        print()
        print("  STATUS : SUCCESS - Live tier ACTIVE, bars received")
        print("  NEXT   : Sprint 0 Action 2 (parite batch vs streaming)")
        sys.exit(0)
    elif other_error:
        print()
        print(f"  STATUS : ERROR - {other_error}")
        print("  NEXT   : Investigate (network, symbol invalid, etc.)")
        sys.exit(3)
    else:
        print()
        print("  STATUS : TIMEOUT - No bars received")
        print(f"  Possible : market closed (current UTC: {datetime.now(timezone.utc)}),")
        print(f"             symbol expired, or subscription pending.")
        print("  NEXT   : Re-run during RTH hours OR check symbol validity")
        sys.exit(4)


if __name__ == "__main__":
    main()
