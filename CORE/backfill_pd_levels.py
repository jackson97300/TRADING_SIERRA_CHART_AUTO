"""backfill_pd_levels.py — Backfill historique des niveaux Previous Day.

Itere sur tous les JSONL DATA/{ES,NQ}/YYYYMMDD_*.jsonl et ecrit
DATA/PD_LEVELS/YYYYMMDD_{symbol}.json pour chaque jour.

Usage : python -X utf8 CORE/backfill_pd_levels.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from CORE.pd_levels_extractor import extract_pd_levels, write_pd_levels

ROOT = Path(__file__).resolve().parents[1]


def main():
    print("=" * 70)
    print("BACKFILL PD_LEVELS — Voie 2 Bloc 1.3")
    print("=" * 70)
    out_dir = ROOT / "DATA" / "PD_LEVELS"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_total, n_ok, n_skip = 0, 0, 0
    for sym in ["ES", "NQ"]:
        d = ROOT / "DATA" / sym
        files = sorted(d.glob("2026*_*.jsonl"))
        # Filtre : exclure backups (_PRE_FIX, _v2)
        files = [f for f in files if re.match(r"^\d{8}_(ES|NQ)\.jsonl$", f.name)]
        print(f"\n[{sym}] {len(files)} files to process")
        for fp in files:
            n_total += 1
            pdl = extract_pd_levels(str(fp), sym)
            if pdl is None:
                n_skip += 1
                continue
            write_pd_levels(pdl, str(out_dir))
            n_ok += 1
        print(f"[{sym}] OK={n_ok} SKIP={n_skip}")

    print("\n" + "=" * 70)
    print(f"DONE — Total: {n_total}, OK: {n_ok}, Skip: {n_skip}")
    print(f"Output: {out_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
