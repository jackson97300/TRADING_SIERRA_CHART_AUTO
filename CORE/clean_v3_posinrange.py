"""
Nettoyage parquet v3 — Fix sentinel PosInRange -1 (2026-04-16)
===============================================================

CONTEXTE
--------
Decouvert 2026-04-16 en analysant ES_dataset_v3.parquet :
la fonction C++ `PosInRange()` dans DMP_Transform.h retournait `-1.0f` comme
sentinel "hors range" au lieu de `DMP_INVALID`. Le sentinel -1 est une valeur
numerique finie que LightGBM traite comme une vraie position, corrompant
l'apprentissage.

Impact empirique sur le parquet v3 existant :
  - va_position_pct : 98.4% ES / 98.7% NQ a -1 (polluent la mean)
  - ib_position_pct : 66.3% ES / 65.1% NQ a -1

En plus, `ib_recalc.py` multipliait ib_position_pct par 100 (echelle [0, 100])
avant le fix du 2026-04-16 qui aligne sur la convention C++ [0, 1].

Ce script corrige les parquets v3 existants pour les aligner avec la
convention post-fix (null = NaN hors range, echelle [0, 1]).

USAGE
-----
    # Dry-run : affiche les modifs sans toucher aux fichiers
    python -X utf8 CORE/clean_v3_posinrange.py

    # Apply : ecrit les .bak puis remplace les parquets en place
    python -X utf8 CORE/clean_v3_posinrange.py --apply

SECURITE
--------
- Cree un backup `.pre_v3clean.bak` pour chaque parquet avant modification
- Dry-run par defaut (passer --apply pour ecrire)
- Idempotent : detecte si deja nettoye via max(ib_position_pct) <= 1.5
- Sauvegarde un marqueur dans le parquet via une colonne meta
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Chemin racine projet (parent de CORE/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Parquets v3 a traiter
DEFAULT_PARQUETS = [
    "DATA/DATASETS/ES_dataset_v3.parquet",
    "DATA/DATASETS/NQ_dataset_v3.parquet",
]

BACKUP_SUFFIX = ".pre_v3clean.bak"
CLEAN_MARKER_COL = "_v3_posinrange_cleaned"


def is_already_cleaned(df: pd.DataFrame) -> bool:
    """Detecte si le parquet a deja ete nettoye.

    Heuristique :
      1. Marker column present -> cleaned
      2. Sinon : si ib_position_pct max <= 1.5 ET pas de -1 dans va/ib,
         probablement deja nettoye.
    """
    if CLEAN_MARKER_COL in df.columns:
        return True
    ib = df.get("ib_position_pct")
    if ib is None:
        return False
    # Non-NaN values
    ib_valid = ib.dropna()
    if len(ib_valid) == 0:
        return True  # tout NaN = deja propre
    # Si max > 1.5, c'est probablement encore en [0, 100]
    if ib_valid.max() > 1.5:
        return False
    # Si on a des -1 encore, pas cleaned
    if (ib == -1).any():
        return False
    return True


def clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Nettoie va_position_pct et ib_position_pct du parquet.

    Operations :
      1. va_position_pct : remplace -1 par NaN (deja en [0, 1])
      2. ib_position_pct : remplace -1 par NaN, puis divise par 100 pour
         passer de [0, 100] a [0, 1] (aligne sur la nouvelle convention C++)
      3. Ajoute le marker CLEAN_MARKER_COL = 1

    Retourne (df_modifie, stats_dict).
    """
    stats = {
        "va_sentinels_replaced": 0,
        "ib_sentinels_replaced": 0,
        "ib_scaled": 0,
        "va_before_min": None,
        "va_before_max": None,
        "va_before_mean": None,
        "va_after_min": None,
        "va_after_max": None,
        "va_after_mean": None,
        "ib_before_min": None,
        "ib_before_max": None,
        "ib_before_mean": None,
        "ib_after_min": None,
        "ib_after_max": None,
        "ib_after_mean": None,
    }

    # ── va_position_pct : -1 -> NaN (deja en [0, 1]) ──
    if "va_position_pct" in df.columns:
        va = df["va_position_pct"]
        stats["va_before_min"] = float(va.min())
        stats["va_before_max"] = float(va.max())
        stats["va_before_mean"] = float(va.mean())
        mask_sentinel = va == -1
        stats["va_sentinels_replaced"] = int(mask_sentinel.sum())
        df.loc[mask_sentinel, "va_position_pct"] = np.nan
        va_after = df["va_position_pct"]
        va_after_clean = va_after.dropna()
        if len(va_after_clean) > 0:
            stats["va_after_min"] = float(va_after_clean.min())
            stats["va_after_max"] = float(va_after_clean.max())
            stats["va_after_mean"] = float(va_after_clean.mean())

    # ── ib_position_pct : -1 -> NaN, puis /100 ──
    if "ib_position_pct" in df.columns:
        ib = df["ib_position_pct"]
        stats["ib_before_min"] = float(ib.min())
        stats["ib_before_max"] = float(ib.max())
        stats["ib_before_mean"] = float(ib.mean())
        # Etape 1 : sentinel -> NaN
        mask_sentinel = ib == -1
        stats["ib_sentinels_replaced"] = int(mask_sentinel.sum())
        df.loc[mask_sentinel, "ib_position_pct"] = np.nan
        # Etape 2 : divise par 100 uniquement si max > 1.5 (pas deja scale)
        ib_notna = df["ib_position_pct"].dropna()
        if len(ib_notna) > 0 and ib_notna.max() > 1.5:
            df["ib_position_pct"] = df["ib_position_pct"] / 100.0
            stats["ib_scaled"] = int(len(ib_notna))
        ib_after = df["ib_position_pct"]
        ib_after_clean = ib_after.dropna()
        if len(ib_after_clean) > 0:
            stats["ib_after_min"] = float(ib_after_clean.min())
            stats["ib_after_max"] = float(ib_after_clean.max())
            stats["ib_after_mean"] = float(ib_after_clean.mean())

    # Marker d'idempotence
    df[CLEAN_MARKER_COL] = 1

    return df, stats


def clean_parquet(parquet_path: Path, dry_run: bool) -> dict:
    """Nettoie un parquet v3 en place (avec backup)."""
    result = {
        "file": parquet_path.name,
        "total_lines": 0,
        "already_cleaned": False,
        "error": None,
        "stats": None,
    }

    try:
        df = pd.read_parquet(parquet_path)
    except Exception as e:
        result["error"] = f"read error: {e}"
        return result

    result["total_lines"] = len(df)

    if is_already_cleaned(df):
        result["already_cleaned"] = True
        return result

    df_clean, stats = clean_dataframe(df)
    result["stats"] = stats

    if dry_run:
        return result

    # Backup avant ecriture
    backup_path = parquet_path.with_suffix(parquet_path.suffix + BACKUP_SUFFIX)
    if not backup_path.exists():
        try:
            shutil.copy2(parquet_path, backup_path)
        except OSError as e:
            result["error"] = f"backup failed: {e}"
            return result

    # Ecriture atomique : temp + rename
    tmp_path = parquet_path.with_suffix(parquet_path.suffix + ".tmp")
    try:
        df_clean.to_parquet(tmp_path, index=False)
        tmp_path.replace(parquet_path)
    except Exception as e:
        result["error"] = f"write error: {e}"
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return result

    return result


def print_stats(stats: dict):
    """Affiche les stats avant/apres pour un parquet."""
    def _fmt(v):
        return f"{v:+.4f}" if v is not None else "—"

    print(f"    va_position_pct :")
    print(f"      before : min={_fmt(stats['va_before_min'])}  "
          f"max={_fmt(stats['va_before_max'])}  mean={_fmt(stats['va_before_mean'])}")
    print(f"      after  : min={_fmt(stats['va_after_min'])}  "
          f"max={_fmt(stats['va_after_max'])}  mean={_fmt(stats['va_after_mean'])}")
    print(f"      sentinels replaced : {stats['va_sentinels_replaced']}")
    print(f"    ib_position_pct :")
    print(f"      before : min={_fmt(stats['ib_before_min'])}  "
          f"max={_fmt(stats['ib_before_max'])}  mean={_fmt(stats['ib_before_mean'])}")
    print(f"      after  : min={_fmt(stats['ib_after_min'])}  "
          f"max={_fmt(stats['ib_after_max'])}  mean={_fmt(stats['ib_after_mean'])}")
    print(f"      sentinels replaced : {stats['ib_sentinels_replaced']}")
    print(f"      scaled /100        : {stats['ib_scaled']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Nettoie les parquets v3 : remplace sentinel -1 par NaN et "
                    "realigne ib_position_pct sur [0, 1]. Dry-run par defaut.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Applique les modifs (avec backup .pre_v3clean.bak). Sans ce flag : dry-run.",
    )
    parser.add_argument(
        "--parquets",
        nargs="+",
        default=DEFAULT_PARQUETS,
        help=f"Parquets a traiter (defaut: {DEFAULT_PARQUETS})",
    )
    args = parser.parse_args()

    dry_run = not args.apply

    print("=" * 72)
    print("NETTOYAGE V3 PARQUET — PosInRange sentinel -1 -> NaN + rescale ib [0,1]")
    print("=" * 72)
    print(f"  mode          : {'DRY-RUN' if dry_run else 'APPLY'}")
    print(f"  project root  : {PROJECT_ROOT}")
    print(f"  parquets      : {args.parquets}")
    print()

    total_ok = 0
    total_skipped = 0
    total_err = 0

    for rel in args.parquets:
        p = PROJECT_ROOT / rel
        if not p.exists():
            print(f"  [MISS]         {rel}  (fichier absent)")
            total_err += 1
            continue

        result = clean_parquet(p, dry_run=dry_run)
        if result["error"]:
            print(f"  [ERR ]         {rel}  -> {result['error']}")
            total_err += 1
            continue
        if result["already_cleaned"]:
            print(f"  [SKIP cleaned] {rel}  ({result['total_lines']} lignes, deja nettoye)")
            total_skipped += 1
            continue

        action = "[DRY  ]" if dry_run else "[OK   ]"
        print(f"  {action}        {rel}  ({result['total_lines']} lignes)")
        if result["stats"]:
            print_stats(result["stats"])
        print()
        total_ok += 1

    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"  parquets traites : {total_ok}")
    print(f"  deja nettoyes    : {total_skipped}")
    print(f"  erreurs          : {total_err}")
    if dry_run and total_ok > 0:
        print()
        print("  Mode DRY-RUN : aucun fichier modifie.")
        print("  Pour appliquer : python -X utf8 CORE/clean_v3_posinrange.py --apply")
    elif not dry_run and total_ok > 0:
        print()
        print(f"  Backups crees avec suffixe : {BACKUP_SUFFIX}")
        print("  Rollback : cp <parquet>.pre_v3clean.bak <parquet>")

    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
