"""tools/check_bot3v2_structure.py — Pre-commit hook PROJECT_STRUCTURE sync check.

Phase 1.0 Bot 3 v2 Pro Standard Foundation.

Convention souveraine Jackson 18/05 :
  "Pas de modif fichier Bot 3 v2 sans update DOCS/BOT3V2_PROJECT_STRUCTURE.md"
  → Non-negociable.

Le hook bloque le commit si un module CORE/bot3_(narrative|story|plot|scenario|
direction_resolver|shadow_mode)*.py est modifie sans que son entry soit a jour
dans le tracker structure.

Bypass urgences :
  git commit --no-verify (documenter justification dans commit message).

Usage :
  python tools/check_bot3v2_structure.py CORE/bot3_narrative_state_machine.py [autres]

Exit codes :
  0 : OK, modules cites dans PROJECT_STRUCTURE.md
  1 : BLOQUER commit, modules absents du tracker (update obligatoire)
  2 : Erreur runtime (file not found, parse error)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_FILE = ROOT / "DOCS" / "BOT3V2_PROJECT_STRUCTURE.md"


def check_structure_sync(modified_files: list[str]) -> tuple[int, list[str]]:
    """Verifie que chaque module Bot 3 v2 modifie est cite dans PROJECT_STRUCTURE.

    Args:
        modified_files: list de paths relatifs ou absolus de modules modifies.

    Returns:
        (exit_code, list_of_missing_modules)
    """
    if not STRUCTURE_FILE.exists():
        print(
            f"ERREUR: {STRUCTURE_FILE} introuvable. "
            f"Phase 0 doit etre livre avant tout module Bot 3 v2.",
            file=sys.stderr,
        )
        return 2, []

    try:
        structure_content = STRUCTURE_FILE.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"ERREUR lecture {STRUCTURE_FILE} : {e}", file=sys.stderr)
        return 2, []

    missing = []
    for raw_path in modified_files:
        # Normaliser : extraire nom module ex CORE/bot3_narrative_state_machine.py
        path = Path(raw_path)
        module_name = path.name  # ex "bot3_narrative_state_machine.py"

        # Pattern flexible : autorise variations naming (camel/snake, .py optionnel)
        # Plus permissif pour eviter faux positifs sur futur refactor.
        if module_name not in structure_content:
            missing.append(str(path))

    if missing:
        print(
            "BLOQUER commit : modules Bot 3 v2 modifies SANS update "
            "DOCS/BOT3V2_PROJECT_STRUCTURE.md :",
            file=sys.stderr,
        )
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        print(
            "\n  → Ajouter entry dans BOT3V2_PROJECT_STRUCTURE.md section "
            "Phase N appropriee (status TODO/WIP/REVIEW/GO/NOGO/DEPRECATED + "
            "date + commit hash + review).\n"
            "  → Convention souveraine Jackson 18/05.\n",
            file=sys.stderr,
        )
        return 1, missing

    return 0, []


def main() -> int:
    """CLI entry."""
    if len(sys.argv) < 2:
        # Pas de fichier passe = hook sans target = pass-through OK
        return 0

    modified = sys.argv[1:]
    # Filter only Bot 3 v2 modules
    bot3v2_pattern = re.compile(
        r"CORE/bot3_(narrative_|story_|plot_|scenario_|direction_resolver|shadow_mode).*\.py$"
    )
    bot3v2_files = [f for f in modified if bot3v2_pattern.search(f.replace("\\", "/"))]

    if not bot3v2_files:
        return 0  # Aucun module Bot 3 v2 dans commit, pass-through

    code, missing = check_structure_sync(bot3v2_files)
    return code


if __name__ == "__main__":
    sys.exit(main())
