"""live_to_dataset_parquet.py - Convertit live_enriched/*.jsonl -> dataset parquet Hive.

REFACTOR Option B (2026-05-16) etape 8 - module appender continu.

Architecture :
  - Source : DATA/live_enriched/{SYM_SAFE}/{YYYYMMDD}.jsonl (output live_enricher
    + replay_enricher_batch, meme format ~430 cols par bar)
  - Output : DATA/datasets/v5_enriched/symbol={sym}/year=YYYY/month=MM/data.parquet
    (partitionne Hive, 1 parquet par mois)
  - Idempotent : peut etre rerun, fusionne avec parquet existant par dedup ts_event_ns

Usage :
  # Convert tous les JSONL dispo (one-shot full)
  python -X utf8 CORE/live_to_dataset_parquet.py

  # Convert dates specifiques
  python -X utf8 CORE/live_to_dataset_parquet.py \
    --start 2026-04-14 --end 2026-04-30

  # Convert 1 symbole only
  python -X utf8 CORE/live_to_dataset_parquet.py --symbols ES.c.0

Deploy continu (cron daily VPS post-RTH close) :
  # crontab.txt (16:30 ET = 20:30 UTC =~ 21:30 Europe)
  30 20 * * * cd /path/to/MIA && python CORE/live_to_dataset_parquet.py >> LOGS/live_to_dataset.log 2>&1

Garanties :
  - Conserve historique : append vs overwrite (merge sur ts_event_ns unique)
  - Detection drift : log si nb colonnes JSONL change vs parquet (schema evolve)
  - Robuste : skip JSONL corrompus (log + continue)

Auteur : MIA Trading System V2
  v1.0 (2026-05-16) : version initiale Phase REFACTOR Option B etape 8.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Logger
LOG_DIR = ROOT / "DATA" / "LOGS"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "live_to_dataset_parquet.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("live_to_dataset_parquet")

SOURCE_BASE = ROOT / "DATA" / "live_enriched"
OUTPUT_BASE = ROOT / "DATA" / "datasets" / "v5_enriched"

SYMBOLS_DEFAULT = ["ES.c.0", "NQ.c.0", "MGC.v.0"]


def _safe_sym_dir(symbol: str) -> str:
    """Convertit symbole Live -> dossier filesystem aligne live_enricher_writer.

    FIX CRITIQUE 16/05/2026 (Plan agent review) : aligne sur
    `live_enricher_writer._safe_sym_dir` qui mappe MGC -> GC (alignement DMP C++
    filesystem). Sans cette alignement, le scan `DATA/live_enriched/MGC/` etait
    VIDE -> conversion parquet MGC = 0 bar -> modele MGC entraine sur rien.

    Mapping :
      ES.c.0  -> 'ES'
      NQ.c.0  -> 'NQ'
      MGC.v.0 -> 'GC' (Micro Gold, cf live_enricher_writer.py:218-235)
    """
    pure = symbol.split(".")[0]
    if pure == "MGC":
        return "GC"
    return pure


def _safe_sym_file(symbol: str) -> str:
    """ES.c.0 -> ES_c_0 (cf live_enricher_io._safe_sym_dir)."""
    return symbol.replace("/", "_").replace(".", "_")


def parse_jsonl_day(fpath: Path) -> pd.DataFrame:
    """Parse 1 fichier JSONL daily -> DataFrame.

    Args:
        fpath : DATA/live_enriched/{SYM_SAFE}/{YYYYMMDD}.jsonl

    Returns:
        DataFrame avec toutes les colonnes du JSONL ou DataFrame vide.
    """
    if not fpath.exists() or fpath.stat().st_size == 0:
        return pd.DataFrame()

    rows = []
    n_corrupt = 0
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    rows.append(d)
                except json.JSONDecodeError:
                    n_corrupt += 1
                    continue
    except OSError as e:
        logger.warning(f"OSError reading {fpath}: {e}")
        return pd.DataFrame()

    if n_corrupt > 0:
        logger.warning(f"{fpath.name}: {n_corrupt} lignes JSONL corrompues skipees")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Dedup intra-fichier sur ts_event_ns (defense vs doublons live writer)
    if "ts_event_ns" in df.columns:
        df = df.drop_duplicates(subset=["ts_event_ns"], keep="last").reset_index(drop=True)
        df = df.sort_values("ts_event_ns").reset_index(drop=True)
    return df


def merge_into_parquet(
    df_new: pd.DataFrame,
    out_parquet: Path,
) -> tuple[int, int]:
    """Merge df_new avec parquet existant (dedup ts_event_ns).

    Args:
        df_new : DataFrame nouveau (du JSONL daily)
        out_parquet : path parquet existant (peut ne pas exister)

    Returns:
        (n_total_after_merge, n_added)
    """
    if df_new.empty:
        return (0, 0)

    if not out_parquet.exists():
        # Premier write
        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        df_new.to_parquet(out_parquet, index=False)
        return (len(df_new), len(df_new))

    # Merge avec existant
    try:
        df_existing = pd.read_parquet(out_parquet)
    except Exception as e:
        logger.error(f"read_parquet fail {out_parquet}: {e} - skip merge, overwrite")
        out_parquet.parent.mkdir(parents=True, exist_ok=True)
        df_new.to_parquet(out_parquet, index=False)
        return (len(df_new), len(df_new))

    # Schema drift check
    cols_existing = set(df_existing.columns)
    cols_new = set(df_new.columns)
    if cols_existing != cols_new:
        added = cols_new - cols_existing
        removed = cols_existing - cols_new
        if added:
            logger.info(f"  schema evolve {out_parquet.name}: +{len(added)} cols ({list(added)[:5]}...)")
        if removed:
            logger.warning(f"  schema regression {out_parquet.name}: -{len(removed)} cols ({list(removed)[:5]}...)")

    # Concat + dedup
    df_combined = pd.concat([df_existing, df_new], ignore_index=True, sort=False)
    n_before = len(df_combined)
    if "ts_event_ns" in df_combined.columns:
        df_combined = df_combined.drop_duplicates(subset=["ts_event_ns"], keep="last")
        df_combined = df_combined.sort_values("ts_event_ns").reset_index(drop=True)
    n_added = len(df_combined) - len(df_existing)

    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df_combined.to_parquet(out_parquet, index=False)
    return (len(df_combined), n_added)


def discover_jsonl_files(
    symbols: list[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[tuple[str, date, Path]]:
    """Liste tous les JSONL daily a convertir.

    Returns:
        list of (symbol, target_date, jsonl_path)
    """
    out = []
    for sym in symbols:
        sym_dir = _safe_sym_dir(sym)
        src_dir = SOURCE_BASE / sym_dir
        if not src_dir.exists():
            logger.warning(f"Source dir absent : {src_dir}")
            continue

        # FIX P0 : pattern actual = "{YYYYMMDD}_{SYM_SHORT}.jsonl"
        # (cf DATA/live_enriched/ES/20260515_ES.jsonl)
        for fpath in sorted(src_dir.glob("*.jsonl")):
            name = fpath.stem  # 20260515_ES
            # Parse YYYYMMDD prefix
            if len(name) < 8:
                continue
            date_str = name[:8]
            try:
                d = datetime.strptime(date_str, "%Y%m%d").date()
            except ValueError:
                continue

            if start_date and d < start_date:
                continue
            if end_date and d > end_date:
                continue

            out.append((sym, d, fpath))
    return out


def run_conversion(
    symbols: list[str],
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """Run conversion JSONL -> parquet Hive partitionne.

    Returns:
        dict stats {symbol: {n_files, n_bars_total, n_bars_added, n_parquet_files}}
    """
    files_to_process = discover_jsonl_files(symbols, start_date, end_date)
    logger.info(f"{len(files_to_process)} fichiers JSONL a convertir")

    stats: dict[str, dict] = {sym: {"n_files": 0, "n_bars_total": 0, "n_bars_added": 0} for sym in symbols}

    # Group by (sym, year, month) pour minimiser les writes
    by_partition: dict[tuple[str, int, int], list[Path]] = {}
    for sym, d, fpath in files_to_process:
        key = (sym, d.year, d.month)
        by_partition.setdefault(key, []).append(fpath)

    for (sym, year, month), jsonl_files in sorted(by_partition.items()):
        sym_dir = _safe_sym_dir(sym)
        out_parquet = OUTPUT_BASE / f"symbol={sym}" / f"year={year}" / f"month={month}" / "data.parquet"

        # Concat tous les JSONL du mois
        dfs = []
        for fpath in jsonl_files:
            df = parse_jsonl_day(fpath)
            if not df.empty:
                dfs.append(df)
                stats[sym]["n_files"] += 1
        if not dfs:
            continue

        df_month = pd.concat(dfs, ignore_index=True, sort=False)
        # Dedup intra-month sur ts_event_ns
        if "ts_event_ns" in df_month.columns:
            df_month = df_month.drop_duplicates(subset=["ts_event_ns"], keep="last")
            df_month = df_month.sort_values("ts_event_ns").reset_index(drop=True)

        n_total, n_added = merge_into_parquet(df_month, out_parquet)
        stats[sym]["n_bars_total"] += n_total
        stats[sym]["n_bars_added"] += n_added
        logger.info(
            f"  {sym} {year}-{month:02d} : +{n_added} bars (total {n_total}) "
            f"-> {out_parquet}"
        )

    return stats


def main():
    parser = argparse.ArgumentParser(description="Convertit live_enriched JSONL -> dataset parquet")
    parser.add_argument(
        "--symbols", nargs="+", default=SYMBOLS_DEFAULT,
        help="Symboles a convertir (default: ES + NQ + MGC)"
    )
    parser.add_argument(
        "--start", default=None,
        help="Date debut YYYY-MM-DD (default: tout)"
    )
    parser.add_argument(
        "--end", default=None,
        help="Date fin YYYY-MM-DD inclusive (default: tout)"
    )
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start) if args.start else None
    end_date = date.fromisoformat(args.end) if args.end else None

    logger.info(f"Conversion JSONL -> parquet : symbols={args.symbols}")
    if start_date or end_date:
        logger.info(f"  Date range : {start_date} -> {end_date}")

    stats = run_conversion(args.symbols, start_date, end_date)
    logger.info(f"=== DONE ===")
    for sym, s in stats.items():
        logger.info(
            f"  {sym} : {s['n_files']} JSONL files, +{s['n_bars_added']} bars added "
            f"(total {s['n_bars_total']})"
        )


if __name__ == "__main__":
    main()
