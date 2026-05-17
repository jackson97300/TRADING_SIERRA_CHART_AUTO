"""Linter anti ghost feature names V4 enriched.

Origine : audit 17/05/2026 a revele 2 ghost names dans brain_v6 + entry_quality_gate :
  - `dist_big_ask_nearest_up` / `dist_big_bid_nearest_dn` (gate BIG_ORDER mort 100%)
  - `cvd_bar_delta` (gate ENTRY_QUALITY degrade)

Ces noms ont semble exister depuis ~10 jours sans detection car `.get()` retourne
None silencieusement quand cle absente. Pattern VALIDATION_MISS + COMMENT_FALSE.

Ce linter scan tous les `.get("string")` dans CORE/ et :
1. Verifie si la cle existe dans le schema v4 enriched parquet
2. Pour chaque ghost potentiel, valide si lecture legit (state, dmp_bar nested, conseil_*, etc)
3. Flag les vrais ghost names = bug a fixer

Usage :
    python -X utf8 tools/check_ghost_features.py [--strict]

Limites :
- Peut avoir faux positifs (cles legit non-V4 : config, state, dashboard nested)
- Whitelist a maintenir au fil du temps
- Pas de check sur `bar["key"]` (KeyError loud, plus difficile a tromper)

Exit codes :
    0 : aucun ghost suspect detecte (ou tous whitelist)
    1 : ghost names suspects (a investiguer)
    2 : erreur scan
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ["CORE"]
V4_SAMPLE_PARQUET = ROOT / "DATA" / "V4_TEMP" / "ES_mai_v4_VPS_now.parquet"

# Whitelist : cles legitimement absentes du schema v4 enriched
# (state, dashboard nested, config, etc)
WHITELIST_KEYS = {
    # State/runtime tracking
    "signal_id", "trade_id", "parent_id", "tp_cid", "sl_cid",
    "ts", "ts_ms", "ts_event", "bar_ts_ms", "bar_ts", "entry_ts", "exit_ts",
    "entry_time", "exit_time",
    # Position state (post-execution)
    "sl_price", "tp_price", "sl_ticks_initial", "sltp_reject_reason",
    "wr_dynamic_used", "exit_reason", "pnl_ticks", "pnl_usd",
    "n_micros", "tp_wall", "sl_wall", "sl_tier", "sl_reason", "tp_reason",
    "rr_ratio", "sl_usd", "sl_anchor", "tp_anchor",
    # Dashboard nested
    "conseil_action", "conseil_bull_pts", "conseil_bear_pts",
    "executable_action", "freshness",
    # Sub-dicts (lus par .get() mais sont des conteneurs)
    "dmp_bar", "bot", "manual_indicators", "last_bars",
    "banner", "regime", "reg",
    # Config flags
    "dtc_enabled", "phase_1_free_run", "kill_switch",
    # Computed in-code (pas V4 native)
    "direction_sign", "contra_momentum", "contra_cvd",
    # Top-level dashboard fields
    "name", "symbol", "sym", "level", "action", "side", "direction",
    "mode", "favor", "tier", "reason", "phase", "date", "date_str",
}


def load_v4_schema() -> set[str]:
    """Charge schema v4 enriched depuis parquet sample."""
    if not V4_SAMPLE_PARQUET.exists():
        print(f"WARN : {V4_SAMPLE_PARQUET} introuvable - lance pull VPS d'abord")
        return set()
    df = pd.read_parquet(V4_SAMPLE_PARQUET)
    return set(df.columns)


def scan_get_calls() -> dict[str, list[tuple[Path, int]]]:
    """Scan tous les .get("string") dans SCAN_DIRS, return {key: [(file, line), ...]}."""
    pattern = re.compile(r'\.get\(["\']([a-z_][a-z_0-9]+)["\']\)')
    found: dict[str, list[tuple[Path, int]]] = {}
    for d in SCAN_DIRS:
        dir_path = ROOT / d
        if not dir_path.exists():
            continue
        for py in dir_path.glob("*.py"):
            try:
                lines = py.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                for m in pattern.finditer(line):
                    key = m.group(1)
                    found.setdefault(key, []).append((py, i))
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 si suspects non-whitelist")
    args = ap.parse_args()

    print("=" * 70)
    print("LINTER ghost feature names V4 enriched")
    print("=" * 70)
    v4_cols = load_v4_schema()
    print(f"V4 schema : {len(v4_cols)} colonnes")
    found = scan_get_calls()
    print(f".get() calls scannes : {len(found)} cles uniques\n")

    suspects = []
    for key, locs in sorted(found.items()):
        if key in v4_cols:
            continue
        if key in WHITELIST_KEYS:
            continue
        # Filtres heuristiques sur cles legit non-V4
        if len(key) < 7 or "_" not in key:
            continue
        suspects.append((key, locs))

    if not suspects:
        print("OK : aucun ghost suspect non-whitelist")
        return 0

    print(f"{len(suspects)} ghost names SUSPECTS (a investiguer) :\n")
    for key, locs in suspects:
        files = sorted({str(l[0].relative_to(ROOT)) for l in locs})
        n_occ = len(locs)
        # Cherche nom proche dans schema V4 (helper diagnostic)
        candidates = [c for c in v4_cols if key in c or c in key]
        cand_str = f" (candidats V4 : {candidates[:3]})" if candidates else " (no near match V4)"
        print(f"  {key:45s} x{n_occ}  files={files}{cand_str}")

    if args.strict:
        return 1
    print(f"\n--strict pour exit 1. Default = exit 0 (info only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
