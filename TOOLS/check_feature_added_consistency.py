"""Lint guard : verifie qu'une feature ajoutee dans un sub-engine streaming/batch
est presente dans le SET *_GENERATED + path no-trades + log_catalog (si emit).

Source : Review #3 R3 GO NET 15/05/2026 + IDEAS_BACKLOG dette
`check_feature_added_consistency` + CHECKLIST_FEATURE_ADDED.md.

Pattern detecte (Pattern V1 cousin) :
  - `out["nouvelle_feat"] = ...` ajoute dans un sub-engine
  - PAS dans `MODULE_GENERATED = {...}`
  -> `apply_all_*` `drop_existing` ne le drop pas avant recalcul
  -> re-run = duplication silencieuse OU shift J-1 (cf game_changers fix 14/05)

Usage:
    python tools/check_feature_added_consistency.py [--strict] [--module X]

  --strict : exit 1 si violations critiques (pre-commit hook / CI).
  --module X : limiter au fichier X (debug).
"""
from __future__ import annotations

import ast
import argparse
import re
import sys
from pathlib import Path
from typing import Set

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "CORE"


# Modules a scanner (sub-engines + batch pipeline)
MODULES_TO_CHECK = [
    "phase_b_helpers.py",
    "phase_b_plus_engine.py",
    "phase_b_plus_streaming.py",
    "phase_b_plus_long_streaming.py",
    "phase_b_plus_color_streaming.py",
    "phase_b_plus_plus_engine.py",
    "phase_b_plus_plus_trades_streaming.py",
    "phase_b_plus_plus_big_v2_streaming.py",
    "phase_b_plus_plus_cluster_v2_streaming.py",
    "phase_b_plus_plus_absorb_streaming.py",
    "phase_b_plus_plus_trapped_streaming.py",
    "phase_b_plus_plus_delta_div_ext_streaming.py",
    "phase_b_rolling_inputs.py",
    "phase_b_rolling_inputs_streaming.py",
    "phase_b_vwap_diff.py",
    "phase_d_dalton_levels.py",
    "edge_zones_engine.py",
    "edge_zones_streaming.py",
    "sessions_swings_engine.py",
    "sessions_swings_simple_streaming.py",
    "sessions_swings_lag_streaming.py",
    "footprint_builder.py",
    "footprint_builder_streaming.py",
    "game_changers.py",
    "game_changers_streaming.py",
    "gold_phase_d_features.py",
    "gold_phase_d_streaming.py",
    "intermarket_features.py",
    "intermarket_streaming.py",
    "mia_amd.py",
    "mia_amd_streaming.py",
    "open_extension_lines_streaming.py",
    "rolling_features.py",
    "rolling_features_streaming.py",
    "rvol.py",
    "rvol_streaming.py",
    "vwap_diff_streaming.py",
]


# Cles ignorees (passthrough / mots-cles standard)
PASSTHROUGH_KEYS = {
    "ts_event", "ts_recv", "ts", "open", "high", "low", "close", "volume",
    "symbol", "session_id", "session_date_trading", "session_date",
    "date_et", "mins_et", "is_cash_session", "is_ib_window",
    "year", "month", "day", "hour", "minute",
}


def find_generated_sets(tree: ast.AST) -> Set[str]:
    """Trouve toutes les cles dans `*_GENERATED = {...}` set literals."""
    generated = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("_GENERATED"):
                    if isinstance(node.value, ast.Set):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                generated.add(elt.value)
                    elif isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                generated.add(elt.value)
    return generated


def find_dict_assignments(tree: ast.AST, dict_names: tuple = ("out", "row", "result")) -> Set[str]:
    """Trouve `out["X"] = ...` patterns dans toutes les fonctions du module.

    Ne regarde QUE les assignments litterales `out["X"] = expr` (Constant subscript),
    pas les assignments dynamiques `out[key] = ...`.
    """
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    # target.value = dict name (e.g., Name("out"))
                    if isinstance(target.value, ast.Name) and target.value.id in dict_names:
                        # target.slice = la cle
                        slice_val = target.slice
                        # Python 3.9+ : slice est directement le ast.Constant
                        if isinstance(slice_val, ast.Constant) and isinstance(slice_val.value, str):
                            assigned.add(slice_val.value)
    return assigned


def find_emit_log_codes(file_text: str) -> Set[str]:
    """Trouve `_emit_log("CODE_X", ...)` ou `_v2log.emit("CODE_X", ...)` patterns."""
    codes = set()
    patterns = [
        re.compile(r'_emit_log\(\s*[\'"]([A-Z_0-9]+)[\'"]'),
        re.compile(r'\.emit\(\s*[\'"]([A-Z_0-9]+)[\'"]'),
    ]
    for pat in patterns:
        for m in pat.finditer(file_text):
            codes.add(m.group(1))
    return codes


def load_log_catalog_codes() -> Set[str]:
    """Parse log_catalog.py pour extraire toutes les cles LOG_CODES."""
    catalog_path = CORE / "log_catalog.py"
    if not catalog_path.exists():
        return set()
    text = catalog_path.read_text(encoding="utf-8")
    # LOG_CODES = {"CODE_NAME": ...} keys
    codes = set()
    for m in re.finditer(r'"([A-Z_][A-Z_0-9]*)"\s*:', text):
        codes.add(m.group(1))
    return codes


def check_module(path: Path, catalog_codes: Set[str]) -> dict:
    """Run checks sur 1 module. Returns dict report."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return {"path": str(path.name), "status": "PARSE_ERROR", "error": str(e)}

    generated = find_generated_sets(tree)
    assigned = find_dict_assignments(tree)
    emit_codes = find_emit_log_codes(text)

    # Diff : keys assignees `out["X"] = ...` qui ne sont PAS dans *_GENERATED
    # ni dans passthrough (legitimate re-assigns).
    missing_in_generated = assigned - generated - PASSTHROUGH_KEYS

    # Codes emit qui ne sont PAS dans log_catalog
    missing_in_catalog = emit_codes - catalog_codes

    # Severity : CRITICAL si missing_in_catalog (silent KeyError runtime),
    # MEDIUM si missing_in_generated (re-run duplication risk).
    has_generated_set = len(generated) > 0

    return {
        "path": str(path.name),
        "n_assigned": len(assigned),
        "n_generated": len(generated),
        "has_generated_set": has_generated_set,
        "missing_in_generated": sorted(missing_in_generated),
        "n_emit_codes": len(emit_codes),
        "missing_in_catalog": sorted(missing_in_catalog),
        "status": (
            "FAIL" if missing_in_catalog
            else ("WARN" if has_generated_set and missing_in_generated
                  else "OK")
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit 1 si violations FAIL")
    ap.add_argument("--module", help="limiter au fichier module (debug)")
    ap.add_argument("--verbose", action="store_true", help="affiche tous les modules, meme OK")
    args = ap.parse_args()

    catalog_codes = load_log_catalog_codes()
    print(f"[INFO] log_catalog.py : {len(catalog_codes)} codes enregistres")

    modules = MODULES_TO_CHECK
    if args.module:
        modules = [m for m in modules if args.module in m]

    n_ok = 0
    n_warn = 0
    n_fail = 0
    reports = []
    for module_name in modules:
        path = CORE / module_name
        if not path.exists():
            continue
        rep = check_module(path, catalog_codes)
        reports.append(rep)
        if rep["status"] == "OK":
            n_ok += 1
            if args.verbose:
                print(f"[OK]   {module_name} ({rep['n_assigned']} keys / {rep['n_generated']} in GENERATED)")
        elif rep["status"] == "WARN":
            n_warn += 1
            print(f"[WARN] {module_name}")
            print(f"       has GENERATED set ({rep['n_generated']} keys)")
            print(f"       keys assignees mais ABSENTES du SET :")
            for k in rep["missing_in_generated"][:10]:
                print(f"         - {k}")
            if len(rep["missing_in_generated"]) > 10:
                print(f"         ... ({len(rep['missing_in_generated']) - 10} more)")
        elif rep["status"] == "FAIL":
            n_fail += 1
            print(f"[FAIL] {module_name}")
            print(f"       codes emit ABSENTS de log_catalog.py (KeyError silent runtime) :")
            for c in rep["missing_in_catalog"]:
                print(f"         - {c}")
            if rep["missing_in_generated"]:
                print(f"       + keys assignees absentes du SET :")
                for k in rep["missing_in_generated"][:5]:
                    print(f"         - {k}")
        elif rep["status"] == "PARSE_ERROR":
            n_fail += 1
            print(f"[ERR]  {module_name} : {rep['error']}")

    print(f"\n=== SUMMARY ===")
    print(f"  OK   : {n_ok}")
    print(f"  WARN : {n_warn}  (features manquantes dans *_GENERATED — risk re-run duplication)")
    print(f"  FAIL : {n_fail}  (codes emit manquants log_catalog — silent runtime error)")

    if args.strict and n_fail > 0:
        print(f"\n[STRICT] {n_fail} violations CRITIQUES -> exit 1")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
