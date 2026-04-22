"""catalog_coverage.py — Detecte les codes catalog definis mais jamais emis.

Usage :
    python -X utf8 CORE/catalog_coverage.py          # rapport synthetique
    python -X utf8 CORE/catalog_coverage.py --verbose # detail par fichier

Rationale : le log catalog ment sur les capacites systeme quand un code
est defini mais aucun emit(code) n'existe dans la codebase. Au 22/04,
audit manuel a identifie 8 codes "dead" (TRAILING_ACTIVATED, BE_HIT,
MQ_LEVELS_STALE, MQ_INGESTION_FAIL, ML_DRIFT_DETECTED,
RISK_REJECT_ATR_BOUNDS, CONFIG_RELOAD, FUNDED_FLATTEN).

Ce script doit tourner en CI pour flagger les codes morts des qu'ils
apparaissent. Pattern incident_log : VALIDATION_MISS (code defini !=
code emis en prod).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Set

ROOT = Path(__file__).resolve().parent.parent

# Dossiers a scanner (pas de scan dans VENV, DATA, DOCS)
SCAN_DIRS = ["CORE", "BOT", "V2CLEAN", "DASHBOARD"]

# Pattern pour capturer les emits LITTERAUX : _v2log.emit("X_CODE", ...)
EMIT_PATTERN = re.compile(r'\.emit\(\s*["\']([A-Z][A-Z0-9_]+)["\']')

# Pattern pour capturer les codes dans des dict/mapping dispatches
# Ex: {"TP": "TRADE_CLOSE_TP", "SL": "TRADE_CLOSE_SL"} puis emit(code_map[outcome])
# On match les strings dans des lignes type `"KEY": "CODE_NAME"` ou `'KEY': 'CODE_NAME'`
MAPPING_PATTERN = re.compile(r'["\']([A-Z][A-Z0-9_]{4,})["\']')
# Heuristique : si une fonction appelle emit(variable) ET un dict proche contient
# des strings qui matchent un code catalog, considerer comme "probablement emis"


def load_catalog_codes() -> Set[str]:
    """Charge les codes du catalog V2."""
    from CORE.log_catalog import LOG_CODES
    return set(LOG_CODES.keys())


def find_emitted_codes(verbose: bool = False) -> dict[str, list[str]]:
    """Scan la codebase pour les emit(code, ...).

    Returns: {code: [file1:line1, file2:line2, ...]}
    """
    emits: dict[str, list[str]] = {}
    for scan_dir in SCAN_DIRS:
        dir_path = ROOT / scan_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            # Skip fichiers de test + scripts ad-hoc
            if any(part in ("tests", "research", "V1_ARCHIVE") for part in py_file.parts):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            # 1. Emits litteraux
            has_dynamic_emit = False
            for line_no, line in enumerate(content.splitlines(), 1):
                for match in EMIT_PATTERN.finditer(line):
                    code = match.group(1)
                    emits.setdefault(code, []).append(
                        f"{py_file.relative_to(ROOT)}:{line_no}"
                    )
                # Detect dispatch dynamique : emit(var) avec variable
                if re.search(r"\.emit\(\s*(code_map|_code_map|code|_code)\s*[\.\[\(]", line):
                    has_dynamic_emit = True

            # 2. Si fichier utilise emit(variable), scanner les mappings de strings
            #    et marquer les codes qui matchent catalog comme "probable emit"
            if has_dynamic_emit:
                for line_no, line in enumerate(content.splitlines(), 1):
                    for match in MAPPING_PATTERN.finditer(line):
                        code = match.group(1)
                        # Heuristique : cette ligne ressemble a un dict mapping vers un code
                        if ":" in line or "=>" in line:
                            emits.setdefault(code, []).append(
                                f"{py_file.relative_to(ROOT)}:{line_no} [dynamic]"
                            )
    return emits


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="Detail fichiers emit")
    parser.add_argument("--fail-on-dead", action="store_true",
                        help="Exit 1 si codes morts detectes (pour CI)")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))

    catalog = load_catalog_codes()
    emitted = find_emitted_codes(verbose=args.verbose)

    # Codes dans catalog ET emis quelque part : OK
    # Codes dans catalog MAIS jamais emis : DEAD
    # Codes emis MAIS pas dans catalog : ORPHAN (typo ou code manquant catalog)
    dead_codes = sorted(catalog - set(emitted.keys()))
    orphan_codes = sorted(set(emitted.keys()) - catalog)
    live_codes = sorted(catalog & set(emitted.keys()))

    print(f"{'=' * 70}")
    print(f"CATALOG COVERAGE REPORT")
    print(f"{'=' * 70}")
    print(f"  Codes catalog total  : {len(catalog)}")
    print(f"  Codes emis en code   : {len(emitted)}")
    print(f"  Codes LIVE (OK)      : {len(live_codes)}")
    print(f"  Codes DEAD (mort)    : {len(dead_codes)}")
    print(f"  Codes ORPHAN (typo?) : {len(orphan_codes)}")
    print()

    if dead_codes:
        print(f"=== DEAD CODES (catalog definis, jamais emis) ===")
        for c in dead_codes:
            print(f"  [DEAD] {c}")
        print()

    if orphan_codes:
        print(f"=== ORPHAN CODES (emis sans etre au catalog — typo ?) ===")
        for c in orphan_codes:
            places = emitted.get(c, [])
            print(f"  [ORPHAN] {c} -> {places[0] if places else '?'}")
        print()

    if args.verbose:
        print(f"=== LIVE CODES (catalog + emis) ===")
        for c in live_codes:
            places = emitted.get(c, [])
            print(f"  [LIVE] {c} ({len(places)}x)")
            for p in places[:3]:
                print(f"         {p}")
            if len(places) > 3:
                print(f"         ... +{len(places) - 3} autres")

    if args.fail_on_dead and dead_codes:
        print(f"\n!!! {len(dead_codes)} codes morts detectes. CI fail.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
