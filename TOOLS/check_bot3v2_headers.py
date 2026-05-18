"""tools/check_bot3v2_headers.py — Pre-commit hook docstring convention check.

Phase 1.0 Bot 3 v2 Pro Standard Foundation.

Convention souveraine Jackson 18/05 :
  Modules NEW Bot 3 v2 doivent commencer par docstring conforme master plan
  (data source, phase, dates, mirror pattern, review trace, memory feedback)
  + section HISTORY commentee mise a jour a chaque modif >20 LOC.

Cf DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md section "Headers fichiers Python".

Usage :
  python tools/check_bot3v2_headers.py CORE/bot3_narrative_state_machine.py [autres]

Exit codes :
  0 : OK, docstring conforme + HISTORY section
  1 : BLOQUER commit, docstring incomplet (manque champs obligatoires)
  2 : Erreur runtime
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Champs OBLIGATOIRES dans docstring module Bot 3 v2 NEW
# (cf master plan section "Headers Python")
REQUIRED_DOCSTRING_PATTERNS = [
    r"Data source\s*:\s*Databento",  # Convention souveraine
    r"(Architecture|Phase)\s*:.*Bot\s*3\s*v2.*Narrative\s*Layer",  # Context phase
    r"Created\s*:\s*\d{4}-\d{2}-\d{2}",  # Date creation YYYY-MM-DD
    r"Last\s*modified\s*:\s*\d{4}-\d{2}-\d{2}",  # Date last modif
    r"Phase\s*tracker\s*:\s*DOCS/plans/",  # Link master plan
]

# Section HISTORY commentee obligatoire pour modifs >20 LOC
HISTORY_SECTION_PATTERN = re.compile(
    r"#\s*[─-]+\s*HISTORY\s*[─-]+", re.MULTILINE
)


def check_module_header(file_path: Path) -> tuple[int, list[str]]:
    """Verifie docstring module + section HISTORY.

    Args:
        file_path: Path absolu ou relatif fichier .py.

    Returns:
        (exit_code, list_of_findings)
    """
    if not file_path.exists():
        return 2, [f"FILE_NOT_FOUND: {file_path}"]

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return 2, [f"READ_ERROR: {e}"]

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        return 2, [f"SYNTAX_ERROR: {e}"]

    docstring = ast.get_docstring(tree)
    if not docstring:
        return 1, [
            f"MISSING_DOCSTRING: module {file_path.name} sans docstring",
            "  → Ajouter docstring module conforme convention "
            "DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md section "
            '"Headers fichiers Python"',
        ]

    findings = []
    for pattern in REQUIRED_DOCSTRING_PATTERNS:
        if not re.search(pattern, docstring, re.IGNORECASE):
            findings.append(f"MISSING_DOCSTRING_FIELD: '{pattern}'")

    # HISTORY section : check si module > 20 LOC ET section absente
    n_lines = len(source.splitlines())
    if n_lines > 20 and not HISTORY_SECTION_PATTERN.search(source):
        findings.append(
            f"MISSING_HISTORY_SECTION: module {n_lines} LOC > 20 sans "
            f"section commentee `# ─── HISTORY ───`"
        )

    if findings:
        return 1, findings

    return 0, []


def main() -> int:
    """CLI entry."""
    if len(sys.argv) < 2:
        return 0

    modified = sys.argv[1:]
    # Filter only Bot 3 v2 modules NEW (pas refactor existants)
    bot3v2_new_pattern = re.compile(
        r"CORE/bot3_(narrative_|story_|plot_|scenario_|direction_resolver|shadow_mode).*\.py$"
    )

    any_block = False
    for raw_path in modified:
        path_str = raw_path.replace("\\", "/")
        if not bot3v2_new_pattern.search(path_str):
            continue

        file_path = Path(raw_path)
        code, findings = check_module_header(file_path)

        if code == 0:
            continue

        if code == 1:
            any_block = True
            print(
                f"BLOQUER commit {file_path} :",
                file=sys.stderr,
            )
            for f in findings:
                print(f"  - {f}", file=sys.stderr)
            print(
                f"\n  Convention souveraine Jackson 18/05 - cf master plan "
                f"section 'Headers fichiers Python'.\n",
                file=sys.stderr,
            )
        else:
            # code == 2 : erreur runtime
            print(f"ERREUR runtime {file_path}:", file=sys.stderr)
            for f in findings:
                print(f"  - {f}", file=sys.stderr)
            any_block = True

    return 1 if any_block else 0


if __name__ == "__main__":
    sys.exit(main())
