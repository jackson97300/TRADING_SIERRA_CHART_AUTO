"""tools/check_bot3v2_structure.py V2.1 — Pre-commit hook PROJECT_STRUCTURE sync check.

Phase 1.0 Bot 3 v2 Pro Standard Foundation.

V2.1 fixes (review externe Claude 4.7 18/05) :
  - Bug 1 : status_raw preserve pour debug message [C] (V2 affichait 'None')
  - Bug 2 : single _git_staged_files() call (V2 double subprocess git, 20s pire cas)
  - [E] STATUS_INCOHERENT : Status=TODO/DEPRECATED + module modifie = mensonge tracker
  - Env var BOT3V2_STALE_DAYS override (vs hardcode 7j)
  - Markdown separator robustesse `|:---:|` (alignement centre)

V2 fixes (critique Jackson 18/05) :
  P1 : "entry a jour" reel = parse tableau + date ISO + status whitelist
       (vs V1 substring match faible : un module "DEPRECATED" 2024 passait)
  P2 : cross-check BOT3V2_PROJECT_STRUCTURE.md staged dans git diff --cached
  P3 : regex pattern unifie case-insensitive
  P4 reporte Phase 2 (commit-msg hook --no-verify justification)

Convention souveraine Jackson 18/05 :
  "Pas de modif fichier Bot 3 v2 sans update DOCS/BOT3V2_PROJECT_STRUCTURE.md"
  → Non-negociable.

Le hook bloque le commit si :
  [A] ENTRY_MISSING       : module modifie pas dans tableau
  [B] DATE_MISSING/STALE  : Status ACTIF (WIP/REVIEW/GO/NOGO) sans date ou > seuil
  [C] STATUS_INVALID      : Status pas dans whitelist
  [D] TRACKER_NOT_STAGED  : tracker non present dans git diff --cached
  [E] STATUS_INCOHERENT   : Status=TODO/DEPRECATED + module modifie (V2.1)

Format tableau standardise :

  | Fichier                              | Status  | Last-Updated | Commit  | Review            | Notes        |
  |--------------------------------------|---------|--------------|---------|-------------------|--------------|
  | CORE/bot3_narrative_state_machine.py | 🟢 GO   | 2026-05-18   | abc1234 | market-analyst GO | NSM 17 etats |

Status whitelist : TODO / WIP / REVIEW / GO / NOGO / DEPRECATED
Emoji prefix optionnel : ⬜ TODO / 🟡 WIP / 🔵 REVIEW / 🟢 GO / 🔴 NOGO / ⚫ DEPRECATED

Env vars :
  BOT3V2_STALE_DAYS : seuil staleness Last-Updated (default 7).

Bypass urgences :
  git commit --no-verify (documenter justification dans commit message).

Usage :
  python tools/check_bot3v2_structure.py CORE/bot3_narrative_state_machine.py [autres]
  python tools/check_bot3v2_structure.py  # fallback git diff --cached

Exit codes :
  0 : OK
  1 : BLOQUER commit (1+ findings [A-E])
  2 : Erreur runtime (file not found, parse error, git command failure)
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRUCTURE_FILE = ROOT / "DOCS" / "BOT3V2_PROJECT_STRUCTURE.md"
STRUCTURE_RELATIVE = "DOCS/BOT3V2_PROJECT_STRUCTURE.md"

# P3 unified pattern : accepte bot3_narrative.py ET bot3_narrative_state_machine.py
# Case-insensitive sur le suffixe pour edge cases (modules tests, etc.)
BOT3V2_FILE_PATTERN = re.compile(
    r"CORE/bot3_(?:narrative|story|plot|scenario|direction_resolver|shadow_mode)"
    r"(?:_[A-Za-z_0-9]+)?\.py$"
)

STATUS_WHITELIST = frozenset({"TODO", "WIP", "REVIEW", "GO", "NOGO", "DEPRECATED"})

# V2.1 : env var override anti-hardcode
STALE_DAYS_THRESHOLD = int(os.getenv("BOT3V2_STALE_DAYS", "7"))

# Regex parsing tableau standardise
TABLE_ROW_PATTERN = re.compile(
    r"^\|\s*"
    r"(?P<file>[^|]+?)\s*\|\s*"
    r"(?P<status_full>[^|]*?)\s*\|\s*"
    r"(?P<date>[^|]*?)\s*\|\s*"
    r"(?P<commit>[^|]*?)\s*\|\s*"
    r"(?P<review>[^|]*?)\s*\|\s*"
    r"(?P<notes>[^|]*?)\s*\|\s*$"
)


def _extract_status_keyword(status_full: str) -> str | None:
    """Extract status keyword from raw cell. Strip emoji prefix.

    Examples :
        "🟢 GO" → "GO"
        "⬜ TODO" → "TODO"
        "wip" → "WIP"
        "EN COURS" → None (pas whitelist)
    """
    s = status_full.strip()
    if not s:
        return None
    parts = s.split()
    if not parts:
        return None
    keyword = parts[-1].upper()
    return keyword if keyword in STATUS_WHITELIST else None


def _parse_iso_date(date_str: str) -> date | None:
    """Parse YYYY-MM-DD from cell. None si invalide ou placeholder '-'."""
    s = date_str.strip()
    if not s or s == "-":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _git_staged_files() -> list[str] | None:
    """Get list of files staged in current commit.

    Returns:
        list relative paths POSIX-style. None si git command fail.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
            timeout=10,
        )
        return [
            f.strip().replace("\\", "/")
            for f in result.stdout.splitlines()
            if f.strip()
        ]
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"WARN: git diff --cached fail : {e}", file=sys.stderr)
        return None


def parse_structure_entries(structure_content: str) -> dict[str, dict[str, str | date | None]]:
    """Parse PROJECT_STRUCTURE.md - extract toutes entries tableau Bot 3 v2.

    Returns:
        dict path → {"status": keyword OR None, "status_raw": raw,
                     "date": date OR None, "commit": str, "review": str, "notes": str}
    """
    entries: dict[str, dict[str, str | date | None]] = {}

    for line in structure_content.splitlines():
        m = TABLE_ROW_PATTERN.match(line)
        if not m:
            continue

        file_col = m.group("file").strip()
        # Skip header rows (col1 = "Fichier") et separators (commencent par - ou :)
        # V2.1 : `(":---", "-")` rattrape alignement centre `|:------:|`
        if file_col in ("Fichier", "") or file_col.startswith(("-", ":")):
            continue
        if not BOT3V2_FILE_PATTERN.search(file_col):
            continue

        status_full_raw = m.group("status_full").strip()
        status_kw = _extract_status_keyword(status_full_raw)
        date_parsed = _parse_iso_date(m.group("date"))

        entries[file_col] = {
            "status": status_kw,
            "status_raw": status_full_raw,  # V2.1 fix bug 1 : preserve raw pour debug
            "date": date_parsed,
            "commit": m.group("commit").strip(),
            "review": m.group("review").strip(),
            "notes": m.group("notes").strip(),
        }

    return entries


def check_structure_sync(
    modified_files: list[str],
    staged_files: list[str] | None = None,
) -> tuple[int, list[str]]:
    """Verifie integrite tracker pour modules Bot 3 v2 modifies.

    Check 5 conditions :
      [A] ENTRY_MISSING       : module pas dans tableau
      [B] DATE_MISSING/STALE  : Status ACTIF sans date OR date > BOT3V2_STALE_DAYS
      [C] STATUS_INVALID      : Status pas dans whitelist
      [D] TRACKER_NOT_STAGED  : BOT3V2_PROJECT_STRUCTURE.md non staged
      [E] STATUS_INCOHERENT   : Status=TODO/DEPRECATED + module modifie (V2.1)
    """
    if not STRUCTURE_FILE.exists():
        return 2, [
            f"FILE_NOT_FOUND: {STRUCTURE_RELATIVE} introuvable. "
            "Phase 0 doit etre livre avant tout module Bot 3 v2."
        ]

    try:
        structure_content = STRUCTURE_FILE.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return 2, [f"READ_ERROR: {e}"]

    entries = parse_structure_entries(structure_content)
    findings: list[str] = []

    # [D] Tracker staged check
    if staged_files is not None and modified_files:
        if STRUCTURE_RELATIVE not in staged_files:
            findings.append(
                f"[D] TRACKER_NOT_STAGED: {STRUCTURE_RELATIVE} non present dans "
                f"git diff --cached. Modules Bot 3 v2 modifies SANS update tracker. "
                f"Convention souveraine Jackson 18/05 : update tracker = obligatoire."
            )

    today = date.today()
    stale_threshold = today - timedelta(days=STALE_DAYS_THRESHOLD)

    for raw_path in modified_files:
        path_norm = raw_path.replace("\\", "/")
        entry = entries.get(path_norm)

        # V2.1 : fallback path-matching STRICT (raise si collision)
        if entry is None:
            fname = Path(path_norm).name
            candidates = [k for k in entries if k.endswith(fname)]
            if len(candidates) == 1:
                entry = entries[candidates[0]]
            elif len(candidates) > 1:
                findings.append(
                    f"[A] ENTRY_PATH_AMBIGUOUS: {path_norm} matche {len(candidates)} "
                    f"entries dans tracker (fname={fname}): {candidates}. "
                    f"Refactor tracker pour path unique."
                )
                continue

        if entry is None:
            findings.append(
                f"[A] ENTRY_MISSING: {path_norm} pas trouve dans tableau "
                f"PROJECT_STRUCTURE.md. Ajouter ligne |...|... avec Status + "
                f"Last-Updated + Commit + Review + Notes."
            )
            continue

        # [C] Status whitelist check
        if entry["status"] is None:
            findings.append(
                f"[C] STATUS_INVALID: {path_norm} Status pas dans whitelist "
                f"{sorted(STATUS_WHITELIST)}. Status brut: '{entry['status_raw']}'"
            )
            continue

        # V2.1 [E] STATUS_INCOHERENT : module modifie mais marque TODO/DEPRECATED
        # Si le module est dans staged_files (= modifie), Status TODO/DEPRECATED ment.
        is_in_staged = (
            staged_files is not None and (path_norm in staged_files or any(
                s.endswith(Path(path_norm).name) for s in staged_files
            ))
        )
        if is_in_staged:
            if entry["status"] == "TODO":
                findings.append(
                    f"[E] STATUS_INCOHERENT: {path_norm} Status=TODO mais module "
                    f"modifie dans git diff --cached. Passer a WIP/REVIEW/GO avant "
                    f"commit (le tracker doit refleter la realite)."
                )
                continue
            if entry["status"] == "DEPRECATED":
                findings.append(
                    f"[E] STATUS_INCOHERENT: {path_norm} Status=DEPRECATED mais "
                    f"module modifie. Si revival : passer a WIP + nouvelle date. "
                    f"Sinon retirer modif du commit."
                )
                continue

        # Skip stale check pour TODO/DEPRECATED non-modifies (legitime)
        if entry["status"] in ("TODO", "DEPRECATED"):
            continue

        # [B] Stale Last-Updated check pour modules ACTIFS
        d = entry["date"]
        if d is None:
            findings.append(
                f"[B] DATE_MISSING: {path_norm} Status={entry['status']} (ACTIF) "
                f"mais Last-Updated invalide ou absent ('-'). "
                f"Format requis: YYYY-MM-DD."
            )
        elif d < stale_threshold:
            age_days = (today - d).days
            findings.append(
                f"[B] DATE_STALE: {path_norm} Last-Updated={d.isoformat()} "
                f"({age_days} jours, seuil={STALE_DAYS_THRESHOLD}j env BOT3V2_STALE_DAYS). "
                f"Update entry avant commit si modif du module."
            )

    if findings:
        return 1, findings
    return 0, []


def main() -> int:
    """CLI entry. Single git call shared between mode CLI et fallback."""
    # V2.1 fix bug 2 : single git call partage
    staged = _git_staged_files()

    if len(sys.argv) >= 2:
        modified = sys.argv[1:]
    else:
        # Fallback : aucun args = lire git staged
        if staged is None:
            return 2
        modified = staged

    # Filter only Bot 3 v2 modules
    bot3v2_files = [
        f for f in modified if BOT3V2_FILE_PATTERN.search(f.replace("\\", "/"))
    ]

    if not bot3v2_files:
        return 0  # Aucun module Bot 3 v2 dans commit, pass-through

    code, findings = check_structure_sync(bot3v2_files, staged_files=staged or [])

    if findings:
        print(
            f"BLOQUER commit Bot 3 v2 ({len(findings)} finding(s)) :",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print(
            "\nConvention souveraine Jackson 18/05 : "
            "DOCS/BOT3V2_PROJECT_STRUCTURE.md sync = non-negociable.\n"
            "Bypass urgences : git commit --no-verify (documenter justification).",
            file=sys.stderr,
        )

    return code


if __name__ == "__main__":
    sys.exit(main())
