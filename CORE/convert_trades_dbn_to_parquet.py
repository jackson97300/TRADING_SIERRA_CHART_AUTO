"""convert_trades_dbn_to_parquet.py — Helper pour convertir tous les data.dbn.zst trades en parquet.

Le databento_download.py ne convertit en parquet QUE pour OHLCV. Pour les trades,
on doit convertir manuellement (necessaire pour aggregate_trades_1min via DuckDB).

Usage :
    python -X utf8 CORE/convert_trades_dbn_to_parquet.py
    python -X utf8 CORE/convert_trades_dbn_to_parquet.py --date 2026-04-27 --symbol ES.c.0
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import databento as db

ROOT = Path(__file__).resolve().parents[1]
TRADES_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "trades"


def convert_one(symbol: str, day: date, force: bool = False) -> bool:
    fp = (TRADES_ROOT / f"symbol={symbol}" /
          f"year={day.year}" / f"month={day.month}" / f"day={day.day}" /
          "data.dbn.zst")
    if not fp.exists():
        print(f"  [SKIP] {symbol} {day} : dbn.zst not found")
        return False
    out = fp.with_name("data.parquet")
    if out.exists() and not force and out.stat().st_mtime >= fp.stat().st_mtime:
        print(f"  [SKIP] {symbol} {day} : parquet up-to-date")
        return True
    try:
        print(f"  [CONV] {symbol} {day} ...", end=" ", flush=True)
        store = db.DBNStore.from_file(str(fp))
        df = store.to_df()
        df.to_parquet(out, compression="zstd", index=True)
        size_kb = out.stat().st_size / 1024
        print(f"OK {len(df)} trades -> {size_kb:.0f} KB")
        return True
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default = all)")
    ap.add_argument("--symbol", default=None, help="ES.c.0 / NQ.c.0 (default = both)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    symbols = [args.symbol] if args.symbol else ["ES.c.0", "NQ.c.0"]
    if args.date:
        days = [date.fromisoformat(args.date)]
    else:
        # All days present in dirs
        days = set()
        for sym in symbols:
            sym_root = TRADES_ROOT / f"symbol={sym}"
            if not sym_root.exists():
                continue
            for fp in sym_root.glob("year=*/month=*/day=*/data.dbn.zst"):
                # Parse year/month/day from path (skip symbol= part)
                parts = {}
                for p in fp.parts:
                    if "=" in p and p.split("=")[0] in ("year", "month", "day"):
                        try:
                            parts[p.split("=")[0]] = int(p.split("=")[1])
                        except ValueError:
                            pass
                if "year" in parts and "month" in parts and "day" in parts:
                    days.add(date(parts["year"], parts["month"], parts["day"]))
        days = sorted(days)

    print(f"Convert {len(symbols)} symbols x {len(days)} days")
    n_ok = n_fail = 0
    for sym in symbols:
        for d in days:
            if convert_one(sym, d, args.force):
                n_ok += 1
            else:
                n_fail += 1
    print(f"\nDone : {n_ok} OK, {n_fail} fail")


if __name__ == "__main__":
    main()
