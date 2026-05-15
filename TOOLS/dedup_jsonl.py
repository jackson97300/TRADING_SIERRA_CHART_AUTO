"""Dedup one-shot des fichiers JSONL live_enriched par ts_event_ns.

Strategy : last-write-wins par `written_at_ts` max (la version la plus
recente d'un meme ts_event_ns).

Usage:
  python tools/dedup_jsonl.py <path_to_jsonl>
  python tools/dedup_jsonl.py --all  (tous les fichiers DATA/live_enriched)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def dedup_file(path: Path) -> dict:
    """Dedup 1 fichier. Returns stats dict."""
    if not path.exists():
        return {"status": "missing", "path": str(path)}

    rows = []
    bad_lines = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                rows.append((d.get("ts_event_ns"), d.get("written_at_ts", 0), line))
            except json.JSONDecodeError:
                bad_lines += 1

    n_in = len(rows)
    if n_in == 0:
        return {"status": "empty", "path": str(path)}

    # Group by ts_event_ns, garder celle avec written_at_ts max
    by_ts: dict = {}
    for ts_ns, written, line in rows:
        if ts_ns is None:
            continue
        existing = by_ts.get(ts_ns)
        if existing is None or written > existing[0]:
            by_ts[ts_ns] = (written, line)

    # Tri chronologique
    lines_out = [lst[1] for ts, lst in sorted(by_ts.items())]
    n_out = len(lines_out)
    n_dup = n_in - n_out

    if n_dup == 0:
        return {"status": "no_dup", "n_in": n_in, "path": str(path)}

    # Backup + reecrire
    backup = path.with_suffix(".jsonl.bak_dedup")
    shutil.copy(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines_out:
            f.write(line + "\n")

    return {
        "status": "dedup_done",
        "n_in": n_in,
        "n_out": n_out,
        "n_dup": n_dup,
        "bad_lines": bad_lines,
        "backup": str(backup.name),
        "path": str(path),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="JSONL file (or --all)")
    ap.add_argument("--all", action="store_true", help="Process all DATA/live_enriched/*/*.jsonl")
    args = ap.parse_args()

    if args.all:
        paths = sorted((ROOT / "DATA" / "live_enriched").rglob("*.jsonl"))
    elif args.path:
        paths = [Path(args.path)]
    else:
        ap.print_help()
        sys.exit(1)

    for p in paths:
        # Skip backups
        if ".bak" in p.name:
            continue
        rep = dedup_file(p)
        if rep["status"] == "dedup_done":
            print(f"[OK]   {p.name}: {rep['n_in']} -> {rep['n_out']} ({rep['n_dup']} doublons, backup={rep['backup']})")
        elif rep["status"] == "no_dup":
            print(f"[CLEAN] {p.name}: {rep['n_in']} bars (0 doublon)")
        elif rep["status"] == "empty":
            print(f"[SKIP] {p.name}: empty")
        else:
            print(f"[ERR]  {p.name}: {rep['status']}")


if __name__ == "__main__":
    main()
