"""Deduplication des JSONL live_enriched (source de verite unique).

Probleme traite (audit 04/09/2026) :
  - ~30 500 barres dupliquees par symbole entre le 10/07 et le 04/09
  - 3 jours sinistres (31/07, 05/08, 10/08) : jusqu'a 41 copies de la meme barre
  - motif recurrent de 479-480 doublons/jour (= 8h de barres re-dumpees)
  - les lignes dupliquees portent parfois 621 cles au lieu de 626 (schema partiel)

Pourquoi c'est bloquant : une barre dupliquee peut atterrir des DEUX cotes d'un
split walk-forward => fuite train/test => PF gonfle artificiellement. C'est le
meme genre d'artefact que le backfill v5e (PF 2.32 backtest -> 0.88 live).

Regle de resolution : pour un `ts` donne, on garde la ligne au schema le PLUS
COMPLET (max nb de cles). A egalite, la DERNIERE rencontree (etat le plus recent).

Usage :
    python -X utf8 CORE/dedup_live_enriched.py --dry-run
    python -X utf8 CORE/dedup_live_enriched.py --out DATA/live_enriched_clean
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

DEFAULT_ROOT = Path("DATA/live_enriched/sierra")
SYMBOLS = ("ES", "NQ")
SCHEMA_REFERENCE_KEYS = 626  # schema nominal observe au 04/09/2026


class DedupError(RuntimeError):
    """Echec de deduplication : fichier illisible ou barre sans timestamp."""


def dedup_file(path: Path) -> tuple[list[str], dict]:
    """Deduplique un JSONL par `ts`. Retourne (lignes_propres, stats).

    Leve DedupError si une ligne JSON valide n'a pas de `ts` exploitable :
    on refuse de deviner (pas de fallback silencieux).
    """
    best: dict[int, tuple[int, str]] = {}   # ts -> (nb_cles, ligne)
    order: list[int] = []                   # ordre d'apparition des ts
    n_lines = n_bad_json = n_no_ts = 0
    key_counts: Counter = Counter()

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            n_lines += 1
            try:
                bar = json.loads(raw)
            except json.JSONDecodeError:
                n_bad_json += 1
                continue

            ts = bar.get("ts")
            if not isinstance(ts, int):
                n_no_ts += 1
                continue

            n_keys = len(bar)
            key_counts[n_keys] += 1
            previous = best.get(ts)
            if previous is None:
                order.append(ts)
                best[ts] = (n_keys, raw)
            elif n_keys >= previous[0]:
                # >= : a egalite de schema on prefere la derniere occurrence
                best[ts] = (n_keys, raw)

    if n_no_ts:
        raise DedupError(f"{path.name} : {n_no_ts} lignes sans `ts` entier — refus de deviner")

    order.sort()  # remet les barres en ordre chronologique strict
    clean = [best[ts][1] for ts in order]

    stats = {
        "lines_in": n_lines,
        "lines_out": len(clean),
        "removed": n_lines - len(clean) - n_bad_json,
        "bad_json": n_bad_json,
        "schemas": dict(sorted(key_counts.items())),
    }
    return clean, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplique les JSONL live_enriched par ts.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="racine sierra/")
    parser.add_argument("--out", default="DATA/live_enriched_clean", help="dossier de sortie")
    parser.add_argument("--since", default="20260101", help="jour minimum YYYYMMDD")
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--dry-run", action="store_true", help="n'ecrit rien, affiche le rapport")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"ERREUR : racine introuvable : {root}", file=sys.stderr)
        return 2

    grand_in = grand_out = grand_bad = 0
    touched: list[str] = []

    for sym in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        files = sorted((root / sym).glob("2026*_sierra_enriched.jsonl"))
        files = [f for f in files if f.name[:8] >= args.since]
        if not files:
            print(f"[{sym}] aucun fichier depuis {args.since}")
            continue

        out_dir = Path(args.out) / sym
        if not args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'=' * 78}\n{sym} — {len(files)} fichiers\n{'=' * 78}")
        print(f"{'jour':<10}{'in':>8}{'out':>8}{'retire':>9}  schemas")

        sym_in = sym_out = 0
        for path in files:
            clean, st = dedup_file(path)
            sym_in += st["lines_in"]
            sym_out += st["lines_out"]
            grand_bad += st["bad_json"]

            flag = ""
            if st["removed"]:
                flag = f"  <== {st['removed']} retirees"
                touched.append(f"{sym}/{path.name[:8]}")
            schemas = ",".join(f"{k}x{v}" for k, v in st["schemas"].items())
            print(f"{path.name[:8]:<10}{st['lines_in']:>8}{st['lines_out']:>8}"
                  f"{st['removed']:>9}  {schemas}{flag}")

            if not args.dry_run:
                (out_dir / path.name).write_text("\n".join(clean) + "\n", encoding="utf-8")

        print(f">>> {sym} : {sym_in} -> {sym_out} barres ({sym_in - sym_out} retirees)")
        grand_in += sym_in
        grand_out += sym_out

    print(f"\n{'=' * 78}")
    print(f"TOTAL : {grand_in} -> {grand_out} barres  ({grand_in - grand_out} doublons retires)")
    print(f"JSON invalides ignores : {grand_bad}")
    print(f"Jours modifies : {len(touched)}")
    if args.dry_run:
        print("\n[DRY-RUN] aucun fichier ecrit.")
    else:
        print(f"\nEcrit dans : {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
