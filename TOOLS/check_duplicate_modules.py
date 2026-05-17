"""Linter anti-pattern doublons modules Python (CORE/ vs BOT/).

Origine : incident DEPLOY_UNSAFE 17/05/2026 — `databento_paper_trader_v2.py:49-51`
  - sys.path.insert(0, "CORE") + sys.path.insert(0, "BOT") -> BOT prioritaire
  - bot3_config.py existait en 2 versions (BOT/ 12/05, CORE/ 17/05 a jour)
  - Python charge BOT/ vieux -> ImportError BLOCKED_COMBOS_BOT3 absent
  - Service VPS en SERVICE_PAUSED apres restart -> crash loop
  - 1h debug avant detection -> palliatif SCP BOT/ + fix permanent Option B

Ce linter detecte tout fichier .py qui existe a 2 emplacements dans le repo,
avec comparison de taille (proxy contenu) et hash MD5 (verification stricte).

Si doublons detectes :
  - WARNING : meme contenu (identiques)
  - ERROR : contenus differents (drift = bombe a retardement)

Usage :
    python -X utf8 tools/check_duplicate_modules.py [--strict]

Exit codes :
    0 : aucun doublon (ou tous identiques en mode non-strict)
    1 : doublons avec drift contenu (--strict OU defaut)
    2 : erreur scan
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Dossiers a scanner pour doublons (eviter CORE/__pycache__, .git, etc.)
SCAN_DIRS = ["CORE", "BOT"]

# Files autorises a etre dupliques (legitimes, ex: __init__.py vide, conftest.py)
WHITELIST = {
    "__init__.py",
    "conftest.py",   # R1 code-reviewer 17/05 : fixtures tests legitimement dupliques
}


def file_hash(path: Path) -> str:
    """MD5 du contenu (proxy comparaison stricte)."""
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_modules() -> dict[str, list[Path]]:
    """Scan tous les .py dans SCAN_DIRS, retourne dict {filename: [path, ...]}.

    Detecte uniquement TOP-LEVEL (pas les subdirs comme primary_models/) car
    le bug source du DEPLOY_UNSAFE etait top-level only.
    """
    by_name: dict[str, list[Path]] = defaultdict(list)
    for d in SCAN_DIRS:
        dir_path = ROOT / d
        if not dir_path.exists():
            continue
        for py in dir_path.glob("*.py"):
            if py.name in WHITELIST:
                continue
            by_name[py.name].append(py)
    return by_name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 meme si doublons identiques (force unicite source)")
    args = ap.parse_args()

    print("=" * 70)
    print("LINTER doublons modules Python (anti DEPLOY_UNSAFE)")
    print(f"Scan dirs : {SCAN_DIRS}")
    print("=" * 70)

    by_name = scan_modules()
    duplicates = {name: paths for name, paths in by_name.items() if len(paths) > 1}

    if not duplicates:
        print("\nOK : aucun doublon detecte")
        return 0

    has_drift = False
    print(f"\n{len(duplicates)} doublons detectes :\n")
    for name, paths in sorted(duplicates.items()):
        hashes = {file_hash(p): p for p in paths}
        sizes = {p: p.stat().st_size for p in paths}
        identical = len(hashes) == 1
        marker = "OK_IDENTIQUE" if identical else "DRIFT_DIFFERENT"
        if not identical:
            has_drift = True
        print(f"  [{marker}] {name}")
        for p in paths:
            rel = p.relative_to(ROOT)
            sz = sizes[p]
            print(f"    {rel} ({sz} bytes)")
        if not identical:
            print(f"    !!! Contenus DIFFERENTS — risque DEPLOY_UNSAFE !!!")
            print(f"    !!! Forcer source unique (supprimer doublon obsolete)")
        print()

    if has_drift or args.strict:
        print("=" * 70)
        if has_drift:
            print("ERREUR : doublons avec contenus DIFFERENTS detectes")
            print("Fix : forcer source unique (supprimer le doublon obsolete)")
            print("Sinon : risque DEPLOY_UNSAFE recurrent (cf INCIDENT_LOG 17/05)")
        else:
            print("STRICT MODE : doublons identiques mais source unique exigee")
        return 1

    print("=" * 70)
    print(f"OK_NON_STRICT : {len(duplicates)} doublons identiques (acceptables)")
    print("Pour exiger source unique : --strict")
    return 0


if __name__ == "__main__":
    sys.exit(main())
