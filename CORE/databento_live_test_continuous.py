"""Test rapide : Live API avec stype_in=continuous + 2 symbols ES.c.0 + NQ.c.0.

Objectif : valider que notre cas d'usage prod (continuous symbology) fonctionne
avant de coder le module databento_live_stream.py.

Usage : python -X utf8 CORE/databento_live_test_continuous.py
"""
import os
import sys
import time
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import databento as db


def main():
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        print("FATAL: DATABENTO_API_KEY missing")
        sys.exit(1)

    print(f"=" * 70)
    print(f"TEST : Live API continuous + 2 symbols ES.c.0 + NQ.c.0")
    print(f"=" * 70)

    # Stats par symbole
    bars_by_sym = {"ES.c.0": [], "NQ.c.0": []}
    inst_to_sym = {}  # instrument_id -> symbol mapping
    start_time = time.time()

    def callback(record):
        # SDK databento 0.76.0 : attributs directs (pas via record.hd)
        # Map instrument_id to symbol via SymbolMappingMsg
        if isinstance(record, db.SymbolMappingMsg):
            inst_id = record.instrument_id
            sym = record.stype_in_symbol
            inst_to_sym[inst_id] = sym
            print(f"  MAPPING : instrument_id={inst_id} -> {sym}")
            return

        # Process OHLCV bar
        if isinstance(record, db.OHLCVMsg):
            inst_id = record.instrument_id
            sym = inst_to_sym.get(inst_id, f"unknown_id_{inst_id}")
            ts_dt = datetime.fromtimestamp(record.ts_event / 1e9, tz=timezone.utc)
            now = time.time()
            latency_s = now - record.ts_event / 1e9
            close = record.close / 1e9 if record.close else 0
            volume = record.volume

            bars_by_sym.setdefault(sym, []).append({
                "ts_event": ts_dt.isoformat(),
                "close": close,
                "volume": volume,
                "latency_s": latency_s,
            })
            print(f"  [{sym:>7s}] {ts_dt.strftime('%H:%M:%S')} close={close:.2f} vol={volume} lat={latency_s:.1f}s")

    try:
        client = db.Live(key=api_key)
        client.subscribe(
            dataset="GLBX.MDP3",
            schema="ohlcv-1m",
            stype_in="continuous",
            symbols=["ES.c.0", "NQ.c.0"],
        )
        client.add_callback(callback)
        client.start()
        print(f"  Subscribed. Waiting up to 120s for ES + NQ bars...")
        print()

        # Attendre au moins 1 bar par symbole, max 120s
        deadline = start_time + 120
        while (
            (len(bars_by_sym.get("ES.c.0", [])) < 1 or len(bars_by_sym.get("NQ.c.0", [])) < 1)
            and time.time() < deadline
        ):
            time.sleep(1)

        client.stop()

    except Exception as e:
        print(f"\nERROR : {type(e).__name__}: {e}")
        sys.exit(2)

    # Verdict
    print()
    print(f"=" * 70)
    print(f"VERDICT")
    print(f"=" * 70)
    n_es = len(bars_by_sym.get("ES.c.0", []))
    n_nq = len(bars_by_sym.get("NQ.c.0", []))
    print(f"  ES.c.0 bars : {n_es}")
    print(f"  NQ.c.0 bars : {n_nq}")
    print(f"  Mapping     : {inst_to_sym}")
    print(f"  Duration    : {time.time() - start_time:.1f}s")

    if n_es >= 1 and n_nq >= 1:
        print(f"\n  STATUS : SUCCESS - continuous symbology + dual symbol works")
        sys.exit(0)
    else:
        print(f"\n  STATUS : INCOMPLETE - missing bars (sym mapping ok ?)")
        sys.exit(3)


if __name__ == "__main__":
    main()
