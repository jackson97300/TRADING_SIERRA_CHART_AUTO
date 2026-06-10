"""
Migration JSONL — Fix bug ATR x4 (2026-04-15)
==============================================

CONTEXTE
--------
Decouvert le 15/04/2026 en analysant une ligne live ES :
le code C++ DMP_Transform.h faisait `atr_ticks = r.atr_daily / tick_size`
alors que `r.atr_daily` est DEJA en ticks (etude SC ATR sur chart ES en mode ticks).

Consequence : 8 features normalisees ATR etaient 4x trop petites :

    dist_vwap_d_atr, dist_vwap_w_atr, dist_vwap_m_atr,
    dist_prev_vpoc_atr, dist_comp_20d_vpoc_atr, dist_comp_50d_vpoc_atr,
    ib_range_atr, sess_range_atr

Le fix C++ (commit du 15/04/2026, DMP_Transform.h + DMP_OpenType.h) corrige le
bug pour toute nouvelle barre produite par le DMP. Mais l'historique (146 jours
ES + 140 jours NQ dans DATA_BACKFILL + DATA) a ete ecrit avec les valeurs
buggees.

Ce script multiplie par 4.0 les 8 features concernees dans TOUS les fichiers
JSONL existants, pour qu'ils soient coherents avec les futures barres produites
par le DMP corrige.

USAGE
-----
    # Dry-run : affiche les modifs sans toucher aux fichiers
    python -X utf8 CORE/migrate_atr_x4.py --dry-run

    # Apply : ecrit les .bak puis remplace les fichiers en place
    python -X utf8 CORE/migrate_atr_x4.py --apply

    # Sur un sous-ensemble
    python -X utf8 CORE/migrate_atr_x4.py --apply --dirs DATA_BACKFILL/ES

SECURITE
--------
- Cree un backup `.atr_x4.bak` pour chaque fichier avant modification
- Dry-run par defaut
- Idempotent : ajoute un marqueur `_atr_x4_migrated` dans chaque ligne traitee,
  et saute les fichiers deja migres
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Iterable

# Chemin racine projet (parent de CORE/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Dossiers par defaut a migrer
DEFAULT_DIRS = [
    "DATA_BACKFILL/ES",
    "DATA_BACKFILL/NQ",
    "DATA/ES",
    "DATA/NQ",
]

# Features a multiplier par 4.0 — passent par CalcDistATR() en C++ qui CLAMP a ±5.
# Source : DMP_Transform.h:502-510 (fonction CalcDistATR).
# Le script Python doit reproduire le clamp pour rester coherent avec le live post-fix.
FEATURES_X4_CLAMPED = [
    "dist_vwap_d_atr",
    "dist_vwap_w_atr",
    "dist_vwap_m_atr",
    "dist_prev_vpoc_atr",
    "dist_comp_20d_vpoc_atr",
    "dist_comp_50d_vpoc_atr",
]

# Features a multiplier par 4.0 — SANS clamp en C++.
# Source : DMP_Transform.h lignes 800-801 (ib_range_atr) et 824-825 (sess_range_atr)
# qui font une division directe ib_range / atr_ticks sans passer par CalcDistATR.
FEATURES_X4_NOCLAMP = [
    "ib_range_atr",
    "sess_range_atr",
]

# Toutes les features migrees (utilise pour le reporting)
FEATURES_X4 = FEATURES_X4_CLAMPED + FEATURES_X4_NOCLAMP

# Clamp identique au C++ : DMP_Transform.h:37 `DMP_ATR_CLIP = 5.0f`
DMP_ATR_CLIP = 5.0

# Seuils IB narrow/wide en fonction de ib_range_atr (cf. DMP_Transform.h:44-45)
# Les booleens ib_is_narrow / ib_is_wide sont derives de ib_range_atr.
# Apres le x4 de ib_range_atr, ils doivent etre RECALCULES pour rester
# coherents avec la nouvelle convention.
IB_NARROW_RATIO = 0.40
IB_WIDE_RATIO = 0.80

MIGRATION_MARKER = "_atr_x4_migrated"
BACKUP_SUFFIX = ".atr_x4.bak"


def is_already_migrated(jsonl_path: Path, max_lines_checked: int = 5) -> bool:
    """Retourne True si au moins une ligne du fichier contient le marqueur."""
    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= max_lines_checked:
                    break
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get(MIGRATION_MARKER) == 1:
                    return True
    except OSError:
        return False
    return False


def _safe_numeric(v) -> bool:
    """True si v est numerique finite non-bool.
    Filtre None, bool, non-numeriques, NaN, inf, -inf.
    Aligne sur std::isfinite du C++ DMP_Reader.h.
    """
    if v is None:
        return False
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    if not math.isfinite(v):  # filtre NaN, inf, -inf d'un coup
        return False
    return True


def migrate_row(row: dict) -> tuple[dict, int]:
    """Multiplie par 4.0 les 8 features ATR (6 clampees + 2 non-clampees)
    et recalcule les booleens ib_is_narrow / ib_is_wide depuis le nouveau
    ib_range_atr pour preserver la coherence semantique.

    Reproduit fidelement le comportement du C++ post-fix :
      - FEATURES_X4_CLAMPED : *4 puis clamp a +- DMP_ATR_CLIP (identique a CalcDistATR)
      - FEATURES_X4_NOCLAMP : *4 sans clamp (identique a ib_range/atr_ticks direct)

    Retourne (row_modifie, nb_features_touchees).
    Valeurs None / NaN / absentes / bool sont laissees tel quel.
    """
    touched = 0

    # Features clampees (6 items) — reproduit CalcDistATR()
    for k in FEATURES_X4_CLAMPED:
        v = row.get(k)
        if not _safe_numeric(v):
            continue
        new_v = v * 4.0
        # Clamp identique a DMP_Transform.h:507-508
        if new_v > DMP_ATR_CLIP:
            new_v = DMP_ATR_CLIP
        elif new_v < -DMP_ATR_CLIP:
            new_v = -DMP_ATR_CLIP
        row[k] = new_v
        touched += 1

    # Features non-clampees (2 items) — ib_range_atr, sess_range_atr
    for k in FEATURES_X4_NOCLAMP:
        v = row.get(k)
        if not _safe_numeric(v):
            continue
        row[k] = v * 4.0
        touched += 1

    # Recalcul ib_is_narrow / ib_is_wide depuis le nouveau ib_range_atr.
    # Ces 2 booleens sont ecrits par DMP_Transform.h lignes 803-804 a partir des
    # seuils DMP_IB_NARROW_RATIO / DMP_IB_WIDE_RATIO, appliques au ib_range_atr
    # 4x trop petit (bug). Apres x4 sur ib_range_atr, il faut re-evaluer.
    ib_atr = row.get("ib_range_atr")
    if _safe_numeric(ib_atr):
        row["ib_is_narrow"] = 1 if ib_atr < IB_NARROW_RATIO else 0
        row["ib_is_wide"] = 1 if ib_atr > IB_WIDE_RATIO else 0
    else:
        # Coherence C++ post-fix : si ib_range_atr est None/NaN/inf, forcer les
        # booleens derives a 0 pour eviter toute dérive d'anciens fichiers avec
        # des valeurs heritees non-zero. Aligne sur DMP_Transform.h:807-808 qui
        # laisse ces booleens a leur init (0) quand ib_range_atr invalide.
        if "ib_is_narrow" in row:
            row["ib_is_narrow"] = 0
        if "ib_is_wide" in row:
            row["ib_is_wide"] = 0

    row[MIGRATION_MARKER] = 1
    return row, touched


def migrate_file(jsonl_path: Path, dry_run: bool) -> dict:
    """Migre un fichier JSONL en place (avec .bak)."""
    stats = {
        "file": jsonl_path.name,
        "lines_total": 0,
        "lines_touched": 0,
        "features_touched": 0,
        "skipped_already_migrated": False,
        "error": None,
    }

    if is_already_migrated(jsonl_path):
        stats["skipped_already_migrated"] = True
        return stats

    try:
        new_lines: list[str] = []
        with jsonl_path.open("r", encoding="utf-8") as f:
            for line in f:
                stats["lines_total"] += 1
                stripped = line.strip()
                if not stripped:
                    new_lines.append(line)
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError as e:
                    stats["error"] = f"JSONDecodeError line {stats['lines_total']}: {e}"
                    return stats
                row, touched = migrate_row(row)
                if touched > 0:
                    stats["lines_touched"] += 1
                    stats["features_touched"] += touched
                new_lines.append(json.dumps(row, separators=(",", ":")) + "\n")
    except OSError as e:
        stats["error"] = f"read error: {e}"
        return stats

    if dry_run:
        return stats

    # Backup avant ecrasement
    backup_path = jsonl_path.with_suffix(jsonl_path.suffix + BACKUP_SUFFIX)
    if not backup_path.exists():
        try:
            shutil.copy2(jsonl_path, backup_path)
        except OSError as e:
            stats["error"] = f"backup failed: {e}"
            return stats

    # Ecriture atomique : temp file puis remplacement
    tmp_path = jsonl_path.with_suffix(jsonl_path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            f.writelines(new_lines)
        tmp_path.replace(jsonl_path)
    except OSError as e:
        stats["error"] = f"write error: {e}"
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return stats

    return stats


def find_jsonl_files(dirs: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        dir_path = PROJECT_ROOT / d
        if not dir_path.is_dir():
            print(f"  [WARN] dossier absent : {dir_path}", file=sys.stderr)
            continue
        for p in sorted(dir_path.glob("*.jsonl")):
            # Skip backups et fichiers pollues
            name = p.name
            if name.endswith(BACKUP_SUFFIX):
                continue
            if ".POLLUE" in name:
                continue
            files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migration JSONL : multiplie par 4.0 les 8 features dist_*_atr / ib_range_atr / sess_range_atr "
                    "et recalcule ib_is_narrow/wide pour corriger le bug C++ ATR x4 (fix 2026-04-15). "
                    "Dry-run par defaut : passer --apply pour ecrire les modifs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Applique les modifs aux fichiers (avec backup .atr_x4.bak). Sans ce flag : dry-run.",
    )
    parser.add_argument(
        "--dirs",
        nargs="+",
        default=DEFAULT_DIRS,
        help=f"Dossiers a traiter (defaut: {DEFAULT_DIRS})",
    )
    args = parser.parse_args()

    dry_run = not args.apply

    print("=" * 72)
    print("MIGRATION ATR x4 — JSONL historique")
    print("=" * 72)
    print(f"  mode          : {'DRY-RUN' if dry_run else 'APPLY'}")
    print(f"  project root  : {PROJECT_ROOT}")
    print(f"  dirs          : {args.dirs}")
    print(f"  features x4   : {len(FEATURES_X4)} ({', '.join(FEATURES_X4)})")
    print()

    files = find_jsonl_files(args.dirs)
    print(f"  fichiers trouves : {len(files)}")
    if not files:
        print("  Rien a faire.")
        return 0

    total_files_touched = 0
    total_files_skipped = 0
    total_files_error = 0
    total_lines_touched = 0
    total_features_touched = 0

    for p in files:
        rel = p.relative_to(PROJECT_ROOT)
        stats = migrate_file(p, dry_run=dry_run)
        if stats["skipped_already_migrated"]:
            print(f"  [SKIP migre]   {rel}")
            total_files_skipped += 1
            continue
        if stats["error"]:
            print(f"  [ERR  ]        {rel}  -> {stats['error']}")
            total_files_error += 1
            continue
        action = "[DRY  ]" if dry_run else "[OK   ]"
        print(
            f"  {action}        {rel}  "
            f"lines={stats['lines_total']} touched={stats['lines_touched']} "
            f"features={stats['features_touched']}"
        )
        if stats["lines_touched"] > 0:
            total_files_touched += 1
            total_lines_touched += stats["lines_touched"]
            total_features_touched += stats["features_touched"]

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  fichiers modifies          : {total_files_touched}")
    print(f"  fichiers skippes (migre)   : {total_files_skipped}")
    print(f"  fichiers en erreur         : {total_files_error}")
    print(f"  lignes touchees            : {total_lines_touched}")
    print(f"  valeurs x4 appliquees      : {total_features_touched}")
    if dry_run:
        print()
        print("  Mode DRY-RUN : aucun fichier n'a ete modifie.")
        print("  Pour appliquer : python -X utf8 CORE/migrate_atr_x4.py --apply")
    else:
        print()
        print(f"  Backups crees avec suffixe : {BACKUP_SUFFIX}")
        print("  Pour rollback : restaurer les .atr_x4.bak")

    return 0 if total_files_error == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
