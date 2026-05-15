"""Installe automatiquement le pre-commit hook tick_size guard.

Usage:
    python tools/install_precommit_hook.py

Cree `.git/hooks/pre-commit` qui execute `tools/check_tick_hardcode.py --strict`
avant chaque commit. Si une violation CRITIQUE est detectee, le commit est
bloque.

R4 fix code-reviewer 10/05 : auto-installation au lieu de doc optionnelle.
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = ROOT / ".git" / "hooks" / "pre-commit"

HOOK_CONTENT = """#!/bin/sh
# Auto-installed pre-commit hook : MIA Trading System guards
# (1) tick_size policy guard (TICK_SIZE = 0.25 hardcode)
# (2) feature consistency guard (R5 Pass 4 15/05) — emit codes manquants
#     du log_catalog (FAIL silent runtime) + features manquantes
#     d'un *_GENERATED set existant (WARN re-run duplication).
#
# Cf .claude/rules/tick-size-policy.md + DOCS/CHECKLIST_FEATURE_ADDED.md
# Pour bypasser (urgences) : git commit --no-verify

cd "$(git rev-parse --show-toplevel)"

python tools/check_tick_hardcode.py --strict
TICK_EXIT=$?

python tools/check_feature_added_consistency.py --strict
FEAT_EXIT=$?

if [ $TICK_EXIT -ne 0 ]; then
    echo ""
    echo "=========================================================="
    echo "[PRE-COMMIT BLOQUE] Violation TICK_SIZE policy detectee"
    echo "Cf .claude/rules/tick-size-policy.md pour fix patterns"
    echo "Bypass urgent : git commit --no-verify"
    echo "=========================================================="
    exit 1
fi

if [ $FEAT_EXIT -ne 0 ]; then
    echo ""
    echo "=========================================================="
    echo "[PRE-COMMIT BLOQUE] Violation feature consistency detectee"
    echo "Codes emit manquants log_catalog OU features hors *_GENERATED"
    echo "Cf DOCS/CHECKLIST_FEATURE_ADDED.md pour fix patterns"
    echo "Bypass urgent : git commit --no-verify"
    echo "=========================================================="
    exit 1
fi

exit 0
"""


def main() -> int:
    git_dir = ROOT / ".git"
    if not git_dir.exists():
        print(f"[FAIL] Pas de repo git : {git_dir} introuvable")
        return 1

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    if HOOK_PATH.exists():
        existing = HOOK_PATH.read_text(encoding="utf-8", errors="replace")
        if "tick_size policy guard" in existing:
            print(f"[OK] pre-commit hook deja installe : {HOOK_PATH}")
            return 0
        print(f"[WARN] {HOOK_PATH} existe deja (autre hook). Backup -> .pre-commit.bak")
        backup = HOOK_PATH.with_suffix(".pre-commit.bak")
        backup.write_text(existing, encoding="utf-8")

    HOOK_PATH.write_text(HOOK_CONTENT, encoding="utf-8")

    # chmod +x (Unix) — sur Windows Git ignore mais ne plante pas
    try:
        st = HOOK_PATH.stat()
        os.chmod(HOOK_PATH, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    except Exception as e:
        print(f"[WARN] chmod failed (Windows OK) : {e}")

    print(f"[OK] pre-commit hook installe : {HOOK_PATH}")
    print()
    print("Test : git commit -am 'test' devrait declencher le scan.")
    print("Pour bypasser temporairement : git commit --no-verify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
