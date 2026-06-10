"""Converter : gold_history/*_gold_levels.json -> DATA/mq_levels/GC/year=Y/month=M/day=D/levels.jsonl

Permet à load_mq_levels.py + attach_mq_distances() de consommer l'historique Gold
comme s'il venait de MQ_Lite C++ live.

Mapping clés :
  key_levels.call_resistance      -> mq_call
  key_levels.put_support          -> mq_put
  key_levels.hvl                  -> mq_hvl
  key_levels.call_resistance_0dte -> mq_call_0dte
  key_levels.put_support_0dte     -> mq_put_0dte
  key_levels.hvl_0dte             -> mq_hvl_0dte
  key_levels.one_day_min          -> mq_1d_min
  key_levels.one_day_max          -> mq_1d_max
  bl_levels[10]                   -> mq_blind[10]
  (gamma_wall_0dte)               -> NON utilisé downstream (ignoré)
  (mq_gex)                        -> [null]*10 (slug netgex FAIL pour GC, valeurs manuelles)

Format output schema : "mq_levels_1.0" (compatible v2 MQ_Lite C++).

Trigger logique :
  - 1er fichier d'une date = "init"
  - jour suivant = "new_day"
  - sinon = "level_change" (mais on a 1 snapshot/jour seulement, donc init/new_day suffisent)

Usage :
  python -X utf8 CORE/research/convert_gold_history_to_mq_hive.py
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "DATA" / "MENTHORQ" / "gold_history"
TARGET_ROOT = ROOT / "DATA" / "mq_levels" / "GC"


def parse_date_from_filename(fn: str):
    """Extract date YYYY-MM-DD from filename like '20250512_gold_levels.json'."""
    stem = fn.replace("_gold_levels.json", "")
    return datetime.strptime(stem, "%Y%m%d").date()


def convert_one(source_file: Path) -> tuple[Path, dict] | None:
    with source_file.open(encoding="utf-8") as f:
        d = json.load(f)

    key_levels = d.get("key_levels", {})
    bl_levels = d.get("bl_levels", [])
    date_str = d.get("date", "")
    if not date_str:
        return None
    dt = datetime.strptime(date_str, "%Y-%m-%d")

    # ts = 09:00 UTC heure publication MenthorQ typique (proxy)
    # En vrai live, ts vient du moment où Sierra Chart détecte le changement.
    # Pour historique : on met une heure stable (09:00 UTC = ~05:00 ET avant pre-market)
    ts_dt = dt.replace(hour=9, minute=0, second=0, tzinfo=timezone.utc)
    ts_ms = int(ts_dt.timestamp() * 1000)

    # Build BL array (10 levels, sorted by rank)
    bl_sorted = sorted(bl_levels, key=lambda x: x.get("rank", 999))
    mq_blind = []
    for i in range(10):
        if i < len(bl_sorted):
            mq_blind.append(bl_sorted[i].get("level"))
        else:
            mq_blind.append(None)

    # Build mq_gex array (10 nulls car AJAX FAIL pour GC netgex)
    mq_gex = [None] * 10

    record = {
        "ts": ts_ms,
        "sym": "GC",
        "schema_version": "mq_levels_1.0",
        "trigger": "new_day",   # 1 snapshot/jour pour backfill historique
        "mq_call": key_levels.get("call_resistance"),
        "mq_put": key_levels.get("put_support"),
        "mq_hvl": key_levels.get("hvl"),
        "mq_call_0dte": key_levels.get("call_resistance_0dte"),
        "mq_put_0dte": key_levels.get("put_support_0dte"),
        "mq_hvl_0dte": key_levels.get("hvl_0dte"),
        "mq_1d_min": key_levels.get("one_day_min"),
        "mq_1d_max": key_levels.get("one_day_max"),
        "mq_gex": mq_gex,
        "mq_blind": mq_blind,
    }

    # Output path Hive
    out_dir = TARGET_ROOT / f"year={dt.year}" / f"month={dt.month}" / f"day={dt.day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "levels.jsonl"

    return out_file, record


def main():
    if not SOURCE_DIR.exists():
        print(f"Source absent : {SOURCE_DIR}")
        return

    source_files = sorted(SOURCE_DIR.glob("*_gold_levels.json"))
    print(f"=== Converter gold_history -> MQ_Lite Hive ===")
    print(f"  Source : {SOURCE_DIR} ({len(source_files)} fichiers)")
    print(f"  Target : {TARGET_ROOT}")

    n_ok = 0
    n_skip = 0

    for src in source_files:
        result = convert_one(src)
        if result is None:
            n_skip += 1
            continue
        out_file, record = result

        # Write JSONL (overwrite si existe — pour idempotence)
        with out_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        n_ok += 1

    print(f"\n=== RESUME ===")
    print(f"  Convertis : {n_ok}")
    print(f"  Skip      : {n_skip}")
    print(f"  Hive root : {TARGET_ROOT}")

    # Sample inspection
    if n_ok > 0:
        print(f"\n  Sample - premier fichier converti :")
        sample = sorted(TARGET_ROOT.rglob("*.jsonl"))[0]
        print(f"    {sample.relative_to(TARGET_ROOT.parent.parent)}")
        with sample.open() as f:
            print(f"    {f.read().strip()[:200]}...")


if __name__ == "__main__":
    main()
