"""
Databento — Telechargement historique avec Hive partitioning.

Usage:
    python CORE/databento_download.py --symbols ES.c.0 NQ.c.0 \
                                       --schemas mbp-10 trades ohlcv-1m \
                                       --date 2026-04-24

Layout cible:
    DATA/databento/<dataset>/<schema>/symbol=<sym>/year=<y>/month=<m>/day=<d>/data.dbn.zst
    DATA/databento/<dataset>/ohlcv-1m/symbol=<sym>/year=<y>/month=<m>/day=<d>/data.parquet
"""
import argparse
import os
import sys
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("DATABENTO_API_KEY")
if not API_KEY:
    print("[FATAL] DATABENTO_API_KEY manquant dans .env")
    sys.exit(1)

import databento as db


DATASET = "GLBX.MDP3"
DATA_ROOT = ROOT / "DATA" / "databento" / DATASET


def hive_path(schema: str, symbol: str, day: date_cls, ext: str = "dbn.zst") -> Path:
    """Construit le chemin Hive partitionned pour un (schema, symbol, day).

    CONVENTION (fix 26/04/2026) : month/day SANS padding ('month=4', 'day=24').
    Aligne sur la convention native DuckDB PARTITION_BY (utilisee par
    databento_backfill_batch.py). Avant : '02d' creait des dossiers vides
    'month=04/day=24/' a cote de 'month=4/day=24/' (dont les batches DuckDB).
    """
    return (
        DATA_ROOT
        / schema
        / f"symbol={symbol}"
        / f"year={day.year}"
        / f"month={day.month}"
        / f"day={day.day}"
        / f"data.{ext}"
    )


def download_one(client, schema: str, symbol: str, day: date_cls, force: bool = False,
                  partial_end: datetime | None = None):
    """Telecharge 1 (schema, symbol, day) en DBN.zst + Parquet (si OHLCV).

    partial_end : si fourni, override end (utile pour day-of dl avant data fully synced).
    """
    dbn_path = hive_path(schema, symbol, day, "dbn.zst")
    dbn_path.parent.mkdir(parents=True, exist_ok=True)

    if dbn_path.exists() and not force:
        size_mb = dbn_path.stat().st_size / 1024 / 1024
        print(f"  [SKIP] {schema:10s} {symbol:8s} {day} -> {size_mb:.2f} MB (deja telecharge)")
        return dbn_path

    start = datetime.combine(day, datetime.min.time())
    end = partial_end if partial_end is not None else start + timedelta(days=1)

    print(f"  [DL]   {schema:10s} {symbol:8s} {day} (end={end:%Y-%m-%d %H:%M}) ...", end=" ", flush=True)
    t0 = datetime.now()

    # 01/05/2026 (Jackson "33 MIN INADMISSIBLE") : DATABENTO_DELAY_MIN baisse
    # de 30 a 5 min cote live_pipeline. Si data_end_after_available_end
    # (Historical API pas encore prete pour bars trop recentes), retry 1x avec
    # end -= 5 min. Si encore en echec, raise pour que pipeline log + retry next cycle.
    def _try_get_range(_end):
        return client.timeseries.get_range(
            dataset=DATASET,
            schema=schema,
            symbols=[symbol],
            stype_in="continuous",
            start=start,
            end=_end,
        )
    try:
        data = _try_get_range(end)
    except Exception as exc:
        msg = str(exc).lower()
        is_data_not_avail = ("data_end_after_available_end" in msg
                             or "available_end" in msg
                             or "data not yet available" in msg)
        if is_data_not_avail and partial_end is not None:
            fallback_end = end - timedelta(minutes=5)
            print(f"FALLBACK ({fallback_end:%H:%M}) ...", end=" ", flush=True)
            data = _try_get_range(fallback_end)
            end = fallback_end  # met a jour pour log final coherent
        else:
            raise

    # Sauvegarde DBN.zst (format natif Databento, le plus compact)
    # FIX audit pipeline 29/04 : atomic write (tmp+replace) pour eviter
    # corruption si convert_trades lit pendant que --force re-ecrit.
    dbn_tmp = dbn_path.with_suffix(dbn_path.suffix + ".tmp")
    data.to_file(str(dbn_tmp))
    os.replace(dbn_tmp, dbn_path)
    elapsed = (datetime.now() - t0).total_seconds()
    size_mb = dbn_path.stat().st_size / 1024 / 1024
    print(f"OK ({size_mb:.2f} MB en {elapsed:.1f}s)")

    # Conversion Parquet pour OHLCV (utile pour ML/backtest direct)
    if schema.startswith("ohlcv"):
        parquet_path = hive_path(schema, symbol, day, "parquet")
        df = data.to_df()
        if not df.empty:
            # FIX audit 29/04 : atomic write parquet aussi
            parquet_tmp = parquet_path.with_suffix(parquet_path.suffix + ".tmp")
            df.to_parquet(parquet_tmp, compression="zstd", index=True)
            os.replace(parquet_tmp, parquet_path)
            psize_mb = parquet_path.stat().st_size / 1024 / 1024
            print(f"         -> Parquet: {psize_mb:.3f} MB ({len(df)} rows)")

    return dbn_path


def main():
    ap = argparse.ArgumentParser(description="Telechargement historique Databento")
    ap.add_argument("--symbols", nargs="+", default=["ES.c.0", "NQ.c.0"])
    ap.add_argument("--schemas", nargs="+", default=["mbp-10", "trades", "ohlcv-1m"])
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    ap.add_argument("--force", action="store_true", help="Re-download meme si deja present")
    ap.add_argument("--partial-end", default=None,
                    help="HH:MM UTC override end pour day-of dl avant data fully synced "
                         "(ex: '14:00' pour s'arreter avant le pre-market US)")
    args = ap.parse_args()

    day = datetime.strptime(args.date, "%Y-%m-%d").date()
    print("=" * 70)
    print(f" DATABENTO DOWNLOAD — {day}")
    print(f" Cle API: {API_KEY[:12]}...{API_KEY[-4:]}")
    print(f" Dataset: {DATASET}")
    print(f" Symbols: {', '.join(args.symbols)}")
    print(f" Schemas: {', '.join(args.schemas)}")
    print("=" * 70)

    client = db.Historical(API_KEY)
    total_start = datetime.now()
    total_size = 0

    partial_end_dt = None
    if args.partial_end:
        hh, mm = args.partial_end.split(":")
        partial_end_dt = datetime.combine(day, datetime.min.time()).replace(
            hour=int(hh), minute=int(mm)
        )
        print(f" Partial end UTC: {partial_end_dt:%Y-%m-%d %H:%M}")
        print("=" * 70)

    for symbol in args.symbols:
        for schema in args.schemas:
            try:
                p = download_one(client, schema, symbol, day, args.force,
                                  partial_end=partial_end_dt)
                total_size += p.stat().st_size
            except Exception as e:
                print(f"  [ERR]  {schema:10s} {symbol:8s} {day}: {e}")

    elapsed = (datetime.now() - total_start).total_seconds()
    print("=" * 70)
    print(f" Total: {total_size / 1024 / 1024:.2f} MB en {elapsed:.1f}s")
    print(f" Layout: {DATA_ROOT}")
    print("=" * 70)


if __name__ == "__main__":
    main()
