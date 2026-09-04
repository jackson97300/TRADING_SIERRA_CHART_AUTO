"""Lint guard : interdit TICK_SIZE = 0.25 hardcode hors de constants.py.

Detecte les regressions du Chantier 1 MGC (10/05/2026) qui a centralise le
tick_size dans CORE/constants.py. Tout fichier qui declare `TICK_SIZE = 0.25`
ou `tick_size = 0.25` au top-level d'un module est un piege pour MGC=0.10.

Usage:
    python tools/check_tick_hardcode.py [--strict]

  --strict : exit 1 si violations (pour pre-commit hook / CI).

Whitelist :
- CORE/constants.py (source de verite)
- *_test.py / tests/* (tests legitimes)
- 15/, BAKUP/, New folder/, .git/, .venv/, archives (legacy non actifs)
- Modules avec commentaire MGC explicite (`MGC=0.10` dans le commentaire de la ligne)
- Modules residuels research/audit/backtest documentes IDEAS_BACKLOG.md
  -> a eliminer progressivement, mais pas bloquant pour le commit
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Patterns interdits
# (?!\d) = negative lookahead pour rejeter `0.250000` etc. (R2 fix code-reviewer 10/05)
PATTERNS = [
    re.compile(r"^TICK_SIZE\s*=\s*0\.25(?!\d)"),
    re.compile(r"^tick_size\s*=\s*0\.25(?!\d)"),
]

# Whitelist : ces chemins peuvent contenir TICK_SIZE = 0.25
WHITELIST_DIRS = {
    "15", "BAKUP", "New folder", ".git", ".venv", "venv",
    "node_modules", "__pycache__",
}
WHITELIST_FILES = {
    "constants.py",  # source unique de verite
    "check_tick_hardcode.py",  # ce fichier
}

# Modules pipeline V4+V5 actifs (CRITIQUE — toute violation ici = BLOCK)
# R3 fix code-reviewer 10/05 : ajout V5 step3+ + label_v4/v5 + signal_rules + phase_b_*
CRITICAL_MODULES = {
    # Pipeline V4 pivot
    "build_dataset_v4_dmp_databento.py",
    "build_dataset_v4_phase_b.py",
    # Phase B helpers/+/+++
    "phase_b_helpers.py",
    "phase_b_plus_engine.py",
    "phase_b_plus_plus_engine.py",
    "phase_b_rolling_inputs.py",
    "phase_b_option_c_plus.py",
    "phase_b_vwap_diff.py",
    # Phase D
    "phase_d_dalton_levels.py",
    # Rolling/contextual
    "rolling_features.py",
    "market_profile_rolling.py",
    "value_area_running.py",
    "footprint_builder.py",
    # Sessions/swings/edge
    "sessions_swings_engine.py",
    "edge_zones_engine.py",
    # Game changers / RVol / Intermarket
    "game_changers.py",
    "intermarket_features.py",
    "rvol.py",
    # Labelers
    "labeler.py",
    "labeler_v3.py",
    "label_v4_dataset.py",
    "label_v5_dataset.py",
    "label_validator.py",
    # AMD / SLTP
    "mia_amd.py",
    "mia_sltp.py",
    # V5 modules (Step 3c+ ajoutes 27/04)
    "enrich_dataset_v5_htf.py",
    "train_v5_lightgbm.py",
    "train_v5_5m.py",
    "train_v5_5m_holdout.py",
    "v5_gate_evaluator.py",
    "v5_hvn_lvn_features.py",
    "v5_signal_rules_per_tf.py",
    "v5_simple_features.py",
}


def is_whitelisted(path: Path) -> bool:
    """Returns True si le fichier est dans la whitelist (pas a checker)."""
    if path.name in WHITELIST_FILES:
        return True
    parts = set(path.parts)
    return bool(parts & WHITELIST_DIRS)


def has_mgc_aware_comment(line: str) -> bool:
    """Returns True si la ligne a un commentaire MGC=0.10 ou caller passe tick.

    R1 fix code-reviewer 10/05 : exiger BOTH 'default ES/NQ' ET ('MGC=0.10' OR
    'caller passe tick'). Sinon n'importe quel dev contourne en collant juste
    `# default ES/NQ`. La whitelist requiert l'explicit MGC awareness.

    Exemple acceptable :
        TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick explicitement
    """
    return ("MGC=0.10" in line) or ("caller passe tick" in line)


def scan_file(path: Path) -> list[tuple[int, str]]:
    """Returns liste (line_no, line_content) des violations."""
    violations = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    for line_no, line in enumerate(content.splitlines(), start=1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern in PATTERNS:
            if pattern.search(stripped):
                if has_mgc_aware_comment(line):
                    continue  # ligne deja MGC-aware
                violations.append((line_no, line.rstrip()))
                break
    return violations


def main():
    strict = "--strict" in sys.argv
    py_files = list(ROOT.rglob("*.py"))
    py_files = [p for p in py_files if not is_whitelisted(p)]

    critical_violations = []
    soft_violations = []

    for path in py_files:
        viols = scan_file(path)
        if not viols:
            continue
        rel = path.relative_to(ROOT)
        if path.name in CRITICAL_MODULES:
            critical_violations.append((rel, viols))
        else:
            soft_violations.append((rel, viols))

    n_critical = sum(len(v) for _, v in critical_violations)
    n_soft = sum(len(v) for _, v in soft_violations)

    if critical_violations:
        print("=" * 70)
        print(f"[CRITICAL] {n_critical} violations dans modules pipeline V4 actifs:")
        print("=" * 70)
        for rel, viols in critical_violations:
            for line_no, line in viols:
                print(f"  {rel}:{line_no} : {line.strip()}")
        print()
        print("ACTION : remplacer par get_tick_size(symbol) ou ajouter")
        print("        commentaire 'default ES/NQ. MGC=0.10 - caller passe tick'")

    if soft_violations:
        print("=" * 70)
        print(f"[WARN] {n_soft} violations dans modules legacy/research/audit:")
        print("=" * 70)
        for rel, viols in soft_violations:
            print(f"  {rel}: {len(viols)} violation(s)")
        print()
        print("Ces modules sont hors scope MGC actuel (cf DOCS/IDEAS_BACKLOG.md).")
        print("A migrer SI utilises pour MGC trading/backtest.")

    if not critical_violations and not soft_violations:
        print("[OK] Aucune violation TICK_SIZE = 0.25 hardcode trouvee.")
        return 0

    if strict and critical_violations:
        print()
        print(f"[FAIL] {n_critical} violations critiques. Commit BLOQUE.")
        return 1

    if strict and not critical_violations:
        print(f"\n[OK] Pas de violation critique. {n_soft} soft (non bloquant).")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
