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

# 11/05 Jackson "nos garde-fous nous permettront de deceler rapidement" :
# brancher logging_v2 pour que codes DOWNLOAD_* remontent dans LOGS/errors/
# et soient visibles via dashboard widget "Erreurs recentes" (health_checker).
sys.path.insert(0, str(ROOT))
try:
    from CORE.logging_v2 import get_logger
    _v2log = get_logger("databento_download", process="pipeline")
except Exception:
    _v2log = None

def _emit(code: str, **ctx):
    """Wrapper safe pour emit log_catalog code via logging_v2."""
    if _v2log is None:
        return
    try:
        _v2log.emit(code, **ctx)
    except Exception:
        pass  # log emit ne doit jamais planter le pipeline


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

    # Garde frontiere de journee (bug 422 frontiere minuit UTC) : si la fenetre
    # [start, end] est vide/inversee (debut de journee CME, end <= start), il
    # n'y a rien a telecharger. Ce n'est PAS une erreur -> skip propre en INFO,
    # pas de DOWNLOAD_NON_RETRY_EXC CRITIQUE (faux [CRIT] dashboard chaque nuit).
    if end <= start:
        print(f"  [TOO_EARLY] {schema:10s} {symbol:8s} {day}: fenetre vide "
              f"(end={end:%H:%M} <= start={start:%H:%M})")
        _emit("DOWNLOAD_TOO_EARLY", schema=schema, symbol=symbol, day=str(day),
              start=f"{start:%H:%M}", end=f"{end:%H:%M}")
        raise RuntimeError(f"too_early: {schema} {symbol} {day} fenetre vide")

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
            # Garde frontiere de journee : le fallback -5min peut faire passer
            # end sous start (debut de journee CME). Tenter = 422 garanti
            # ("start on or after end"). Skip propre en INFO.
            if fallback_end <= start:
                print(f"\n  [TOO_EARLY] {schema} {symbol} {day}: fallback "
                      f"({fallback_end:%H:%M}) <= start ({start:%H:%M})")
                _emit("DOWNLOAD_TOO_EARLY", schema=schema, symbol=symbol,
                      day=str(day), start=f"{start:%H:%M}",
                      end=f"{fallback_end:%H:%M}")
                raise RuntimeError(f"too_early: {schema} {symbol} {day} fallback vide")
            print(f"FALLBACK ({fallback_end:%H:%M}) ...", end=" ", flush=True)
            try:
                data = _try_get_range(fallback_end)
                end = fallback_end  # met a jour pour log final coherent
            except Exception as exc2:
                # FIX 11/05 code-reviewer : fallback FAIL = log explicit avec context
                # Avant : raise nu, main loop [ERR] perdait stack trace
                import traceback as _tb
                print(f"\n  [EXC]  {schema} {symbol} {day}: FALLBACK FAIL "
                      f"{type(exc2).__name__}: {exc2!r}", flush=True)
                _tb.print_exc()
                _emit("DOWNLOAD_NON_RETRY_EXC",
                      schema=schema, symbol=symbol, day=str(day),
                      exc_type=type(exc2).__name__,
                      exc_msg=f"FALLBACK FAIL {repr(exc2)[:200]}")
                raise
        else:
            # FIX 11/05 code-reviewer : exception non-retry = log avec type + repr + traceback
            import traceback as _tb
            print(f"\n  [EXC]  {schema} {symbol} {day}: NON-RETRY "
                  f"{type(exc).__name__}: {exc!r}", flush=True)
            _tb.print_exc()
            _emit("DOWNLOAD_NON_RETRY_EXC",
                  schema=schema, symbol=symbol, day=str(day),
                  exc_type=type(exc).__name__,
                  exc_msg=repr(exc)[:200])
            raise

    # FIX 11/05 code-reviewer : valider que data n'est PAS vide avant d'ecraser
    # le DBN existant. Sans ce check, l'API peut renvoyer 0 records (e.g. bars
    # recentes pas encore dispo) et on overwrite un DBN valide avec un DBN vide.
    # Symptome incident 11/05/2026 ES ohlcv-1m stuck depuis 13:36 UTC.
    try:
        record_count = sum(1 for _ in data)
    except Exception:
        # data peut etre non-iterable selon DBN format; on continue prudemment
        record_count = -1
    if record_count == 0:
        print(f"\n  [EMPTY] {schema:10s} {symbol:8s} {day}: API returned 0 records "
              f"(keep previous DBN, no overwrite)", flush=True)
        # NE PAS overwrite avec un DBN vide — preserve fichier existant
        # Le DBN sera re-tente au prochain cycle (lag temporaire suppose).
        # Emit pour visibilite dashboard widget "Erreurs recentes".
        _emit("DOWNLOAD_EMPTY_RESPONSE",
              schema=schema, symbol=symbol, day=str(day),
              end=f"{end:%H:%M}")
        raise RuntimeError(f"empty_response: {schema} {symbol} {day} 0 records "
                           f"end={end:%H:%M}")

    # Sauvegarde DBN.zst (format natif Databento, le plus compact)
    # FIX audit pipeline 29/04 : atomic write (tmp+replace) pour eviter
    # corruption si convert_trades lit pendant que --force re-ecrit.
    dbn_tmp = dbn_path.with_suffix(dbn_path.suffix + ".tmp")
    data.to_file(str(dbn_tmp))
    os.replace(dbn_tmp, dbn_path)
    elapsed = (datetime.now() - t0).total_seconds()
    size_mb = dbn_path.stat().st_size / 1024 / 1024
    print(f"OK ({size_mb:.2f} MB en {elapsed:.1f}s, {record_count if record_count >= 0 else '?'} records)")

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
                # FIX 11/05 code-reviewer : ERR log avec type + repr + newline lead
                # Avant : print sans \n + sans type concatenait avec [DL] partiel
                # = ligne perdue dans buffer subprocess capture.
                import traceback as _tb
                print(f"\n  [ERR]  {schema:10s} {symbol:8s} {day}: "
                      f"{type(e).__name__}: {e!r}", flush=True)
                _tb.print_exc(file=sys.stdout)

    elapsed = (datetime.now() - total_start).total_seconds()
    print("=" * 70)
    print(f" Total: {total_size / 1024 / 1024:.2f} MB en {elapsed:.1f}s")
    print(f" Layout: {DATA_ROOT}")
    print("=" * 70)


if __name__ == "__main__":
    main()
