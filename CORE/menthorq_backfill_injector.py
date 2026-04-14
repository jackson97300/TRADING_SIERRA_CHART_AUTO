"""
MenthorQ Backfill Injector — injecte les niveaux MenthorQ historiques
dans les fichiers JSONL backfilles par le DMP Backfill Dumper.

CONTEXTE :
    Quand le DMP tourne en mode backfill (Full Recalc sur chart historique),
    il lit les niveaux MenthorQ depuis l'etude SC "MenthorQ Gamma Levels" qui
    contient les valeurs ACTUELLES (celles du jour J), pas les valeurs historiques.
    Consequence : tous les mq_* du backfill sont faux (= valeur du jour system).

    Ce script post-processe les fichiers JSONL backfilles pour ecraser les mq_*
    et les dist_mq_* avec les valeurs historiques correctes, lues depuis les
    fichiers JSON MenthorQ scrappes manuellement (DATA/MENTHORQ/*.json).

FORMATS SUPPORTES :
    - Format ancien (dec 2025 - avril 2026, 80 fichiers) :
        top keys: date, source, scrape_time, ES, NQ, ES_swing, NQ_swing, ...
        niveaux : ES.structured.key_levels.resource.data
    - Format nouveau (apparu 13/04/2026, simplifie) :
        top keys: date, source, CTA, vol_model
        niveaux : vol_model.ES (iv_30d + gamma_wall_0dte + top_gex_strikes + bl_levels)
        NOTE : format nouveau n'a PAS Call Resistance ni Put Support directs,
               il faut derive depuis gamma_wall et top_gex_strikes.

FEATURES ECRASEES (niveaux + distances recalculees depuis price de chaque ligne) :
    mq_call, mq_put, mq_hvl, mq_call_0dte, mq_put_0dte, mq_1d_max, mq_1d_min
    dist_mq_call, dist_mq_put, dist_mq_hvl, dist_mq_call_0dte, dist_mq_put_0dte
    dist_1d_min_ticks, dist_1d_max_ticks
    bool_above_mq_hvl, bool_above_mq_call
    next_wall_dist_ticks, next_wall_is_call
    dist_blind_nearest_up, dist_blind_nearest_dn (depuis bl_levels)

FEATURES NON TOUCHEES (on garde les valeurs DMP) :
    vix_* : les niveaux VIX gamma ne sont pas dans les JSON MenthorQ
    gex_* : les GEX strikes (mq_gex[0..9]) ne sont pas completement dans les JSON
    CTA features : pas integres dans le JSONL DMP actuellement

USAGE :
    python -X utf8 CORE/menthorq_backfill_injector.py \\
        --input DATA_BACKFILL/ES \\
        --output DATA_BACKFILL_CLEAN/ES \\
        --menthorq DATA/MENTHORQ

    Si --output n'est pas fourni, ecrase les fichiers --input en place
    (avec backup .bak automatique).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

TICK_SIZE = 0.25  # ES et NQ (micro inclus)


# ─────────────────────────────────────────────────────────────────────────────
# PARSER MENTHORQ JSON — gere les 2 formats
# ─────────────────────────────────────────────────────────────────────────────

def parse_menthorq_json(json_path: Path, symbol: str) -> Optional[dict]:
    """Extrait les niveaux MenthorQ d'un fichier JSON, gere les 2 formats.

    Returns un dict avec les cles normalisees :
        mq_call, mq_put, mq_hvl, mq_call_0dte, mq_put_0dte,
        mq_1d_max, mq_1d_min, bl_levels (list of 10 floats)

    Retourne None si le fichier est invalide ou ne contient pas les niveaux.
    """
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] {json_path.name}: parse error {e}", file=sys.stderr)
        return None

    symbol = symbol.upper()
    top_keys = set(data.keys())

    # Format ancien : contient ES, NQ, structured...
    if symbol in top_keys and "structured" in data.get(symbol, {}):
        try:
            kl = data[symbol]["structured"]["key_levels"]["resource"]["data"]
        except (KeyError, TypeError):
            return None

        result = {
            "mq_call": _to_float(kl.get("Call Resistance")),
            "mq_put": _to_float(kl.get("Put Support")),
            "mq_hvl": _to_float(kl.get("High Vol Level")),
            "mq_call_0dte": _to_float(kl.get("Call Resistance 0DTE")),
            "mq_put_0dte": _to_float(kl.get("Put Support 0DTE")),
            "mq_1d_max": _to_float(kl.get("1D Max.")),
            "mq_1d_min": _to_float(kl.get("1D Min.")),
            "bl_levels": _parse_bl_levels(
                data[symbol]["structured"].get("bl_levels", {})
                .get("resource", {}).get("text_data", "")
            ),
        }
        return result

    # Format nouveau : vol_model.ES/NQ
    if "vol_model" in data and symbol in data["vol_model"]:
        vm = data["vol_model"][symbol]
        result = {
            "mq_call": None,  # pas directement dans le nouveau format
            "mq_put": None,
            "mq_hvl": None,
            "mq_call_0dte": None,
            "mq_put_0dte": None,
            "mq_1d_max": None,
            "mq_1d_min": None,
            "bl_levels": vm.get("bl_levels") or [],
            # On ajoute le gamma_wall_0dte comme proxy de call/put 0dte
            "gamma_wall_0dte": _to_float(vm.get("gamma_wall_0dte")),
        }
        return result

    return None


def _to_float(v) -> Optional[float]:
    """Convert to float. Returns None si str avec M/B/% suffixe ou si invalid."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s or s.endswith(("M", "B", "%", "K")):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _parse_bl_levels(text_data: str) -> list[float]:
    """Parse les 10 BL levels depuis text_data.

    Exemple input : '$ES1!: BL 1, 6538.42, BL 2, 6676.56, BL 3, 6702.34, ...'
    Retourne une liste de max 10 floats.
    """
    if not text_data:
        return []
    # Match 'BL N, VALUE' patterns
    matches = re.findall(r"BL\s*\d+\s*,\s*([\d.]+)", text_data)
    return [float(m) for m in matches[:10]]


# ─────────────────────────────────────────────────────────────────────────────
# INJECT MENTHORQ INTO JSONL LINE
# ─────────────────────────────────────────────────────────────────────────────

def inject_levels_into_row(row: dict, levels: dict) -> dict:
    """Ecrase les features mq_* et dist_mq_* dans une ligne JSONL parsee.

    row : dict parsed depuis une ligne JSONL (1 barre)
    levels : dict retourne par parse_menthorq_json()

    Convention DMP : dist_X = (X - price) / tick_size
      → positif si X au-dessus du price
      → en TICKS (pas en points)
    """
    price = row.get("price")
    if price is None or isinstance(price, bool) or not isinstance(price, (int, float)):
        return row  # Pas de price valide, on touche a rien

    def dist_ticks(level: Optional[float]) -> Optional[float]:
        if level is None:
            return None
        return round((level - price) / TICK_SIZE, 1)

    # Niveaux principaux
    mq_call = levels.get("mq_call")
    mq_put = levels.get("mq_put")
    mq_hvl = levels.get("mq_hvl")
    mq_call_0dte = levels.get("mq_call_0dte")
    mq_put_0dte = levels.get("mq_put_0dte")
    mq_1d_max = levels.get("mq_1d_max")
    mq_1d_min = levels.get("mq_1d_min")

    # Distances (en ticks, convention DMP)
    if mq_call is not None:
        row["dist_mq_call"] = dist_ticks(mq_call)
        row["bool_above_mq_call"] = 1 if price > mq_call else 0
    if mq_put is not None:
        row["dist_mq_put"] = dist_ticks(mq_put)
    if mq_hvl is not None:
        row["dist_mq_hvl"] = dist_ticks(mq_hvl)
        row["bool_above_mq_hvl"] = 1 if price > mq_hvl else 0
    if mq_call_0dte is not None:
        row["dist_mq_call_0dte"] = dist_ticks(mq_call_0dte)
    if mq_put_0dte is not None:
        row["dist_mq_put_0dte"] = dist_ticks(mq_put_0dte)

    # 1D range targets
    if mq_1d_max is not None:
        row["dist_1d_max_ticks"] = dist_ticks(mq_1d_max)
    if mq_1d_min is not None:
        row["dist_1d_min_ticks"] = dist_ticks(mq_1d_min)

    # next_wall : plus proche entre call et put (absolu)
    if mq_call is not None and mq_put is not None:
        dc = abs(mq_call - price)
        dp = abs(mq_put - price)
        if dc < dp:
            row["next_wall_dist_ticks"] = round(dc / TICK_SIZE, 1)
            row["next_wall_is_call"] = 1
        else:
            row["next_wall_dist_ticks"] = round(dp / TICK_SIZE, 1)
            row["next_wall_is_call"] = 0

    # Blind spots (BL1-10) : plus proche au-dessus et en-dessous
    # Convention DMP C++ (DMP_Transform.h NearestAboveBelow + CalcDistTicks) :
    #   dist en TICKS signes (positif au-dessus, negatif en-dessous)
    #   Fix critique 2026-04-14 : avant ce commit, j'ecrivais en points non signes,
    #   ce qui creait une distribution incompatible live vs backfill sur les 2 features.
    bl_levels = levels.get("bl_levels") or []
    if bl_levels:
        above = [bl for bl in bl_levels if bl > price]
        below = [bl for bl in bl_levels if bl <= price]
        if above:
            nearest_up = min(above)
            row["dist_blind_nearest_up"] = round((nearest_up - price) / TICK_SIZE, 1)
        if below:
            nearest_dn = max(below)
            row["dist_blind_nearest_dn"] = round((nearest_dn - price) / TICK_SIZE, 1)

    return row


# ─────────────────────────────────────────────────────────────────────────────
# PROCESS JSONL FILE
# ─────────────────────────────────────────────────────────────────────────────

def extract_date_from_filename(filename: str) -> Optional[str]:
    """Extract YYYYMMDD from filename like '20260410_ES.jsonl'."""
    m = re.match(r"^(\d{8})_(ES|NQ).*\.jsonl$", filename)
    return m.group(1) if m else None


# Liste EXHAUSTIVE des features derivees de MenthorQ qui doivent etre
# nullifiees si le JSON historique manque (sinon elles contiennent les valeurs
# LIVE d'aujourd'hui = contamination temporelle du training set).
# Fix critique 2026-04-14 : sans cette nullification, les 65 jours sept-nov 2025
# polluaient le dataset avec les mq_* du 14/04/2026.
MENTHORQ_FEATURES_TO_NULLIFY = [
    # Niveaux cles (pas ecrits dans le JSONL directement mais utilises pour distances)
    # Distances mq_* principales (features training)
    "dist_mq_call",
    "dist_mq_put",
    "dist_mq_hvl",
    "dist_mq_call_0dte",
    "dist_mq_put_0dte",
    # 1D range targets
    "dist_1d_max_ticks",
    "dist_1d_min_ticks",
    # Next wall (derive de mq_call/mq_put)
    "next_wall_dist_ticks",
    "next_wall_is_call",
    # Bool above niveaux
    "bool_above_mq_call",
    "bool_above_mq_hvl",
    # Blind spots (derive de bl_levels)
    "dist_blind_nearest_up",
    "dist_blind_nearest_dn",
    # GEX nearest (derive de top_gex_strikes) - garder si existait deja mais pas
    # touche par l'injector car on n'a pas les 10 strikes pour tous les formats
    # "dist_gex_nearest_up", "dist_gex_nearest_dn", "gex_cluster_count",
]


def nullify_menthorq_features(row: dict) -> dict:
    """Met a None toutes les features derivees de MenthorQ.

    Utilise quand le JSON MenthorQ est absent pour ce jour : on ne peut pas
    connaitre les vraies valeurs historiques, donc on met NaN pour eviter que
    le DMP live aie ecrit des valeurs du JOUR COURANT (qui seraient des fuites
    temporelles vers le futur dans le training set).
    """
    for key in MENTHORQ_FEATURES_TO_NULLIFY:
        if key in row:
            row[key] = None
    return row


def process_jsonl(
    jsonl_path: Path,
    menthorq_dir: Path,
    symbol: str,
    output_path: Optional[Path] = None,
) -> dict:
    """Traite un fichier JSONL : inject les niveaux MenthorQ historiques.

    Returns stats : {lines, injected, no_json, nullified, errors}

    Si JSON MenthorQ absent pour ce jour → les mq_* sont NULLIFIEES
    (pour eviter contamination temporelle du training set).
    """
    date_str = extract_date_from_filename(jsonl_path.name)
    if not date_str:
        return {"lines": 0, "injected": 0, "no_json": 0, "nullified": 0,
                "errors": 0, "status": "skip_bad_filename"}

    json_path = menthorq_dir / f"{date_str}_menthorq_complete.json"
    if not json_path.exists():
        json_path = None

    levels = None
    if json_path:
        levels = parse_menthorq_json(json_path, symbol)

    stats = {"lines": 0, "injected": 0, "no_json": 0, "nullified": 0,
             "errors": 0, "date": date_str,
             "json": json_path.name if json_path else None}

    out_lines = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        stats["lines"] += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            stats["errors"] += 1
            continue

        if levels is not None:
            row = inject_levels_into_row(row, levels)
            stats["injected"] += 1
        else:
            # Pas de JSON → NULLIFIER pour eviter contamination
            row = nullify_menthorq_features(row)
            stats["nullified"] += 1

        out_lines.append(json.dumps(row, ensure_ascii=False))

    # Ecrire le resultat
    target = output_path if output_path else jsonl_path
    if output_path is None:
        backup = jsonl_path.with_suffix(jsonl_path.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(jsonl_path, backup)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    if levels is not None:
        stats["status"] = "ok_injected"
    else:
        stats["status"] = "ok_nullified"
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path,
                    help="Dossier source des JSONL backfilles (ex: DATA_BACKFILL/ES)")
    ap.add_argument("--output", type=Path, default=None,
                    help="Dossier destination (si None, ecrase --input avec backup .bak)")
    ap.add_argument("--menthorq", required=True, type=Path,
                    help="Dossier DATA/MENTHORQ avec les JSON scrappes")
    ap.add_argument("--symbol", required=True, choices=["ES", "NQ"],
                    help="Symbole a traiter")
    ap.add_argument("--glob", default="*.jsonl",
                    help="Pattern de fichiers (defaut *.jsonl)")
    args = ap.parse_args()

    input_dir: Path = args.input
    if not input_dir.is_dir():
        print(f"ERREUR : {input_dir} n'existe pas ou n'est pas un dossier", file=sys.stderr)
        sys.exit(1)
    if not args.menthorq.is_dir():
        print(f"ERREUR : {args.menthorq} n'existe pas", file=sys.stderr)
        sys.exit(1)

    files = sorted(input_dir.glob(args.glob))
    print(f"=== MenthorQ Backfill Injector ===")
    print(f"  symbol       : {args.symbol}")
    print(f"  input dir    : {input_dir}")
    print(f"  output dir   : {args.output or '(in-place avec .bak)'}")
    print(f"  menthorq dir : {args.menthorq}")
    print(f"  files found  : {len(files)}")
    print()

    total_lines = 0
    total_injected = 0
    total_nullified = 0
    n_ok_injected = 0
    n_ok_nullified = 0

    for jsonl_path in files:
        output_path = None
        if args.output:
            output_path = args.output / jsonl_path.name

        stats = process_jsonl(
            jsonl_path, args.menthorq, args.symbol, output_path
        )

        total_lines += stats["lines"]
        total_injected += stats["injected"]
        total_nullified += stats.get("nullified", 0)
        if stats["status"] == "ok_injected":
            n_ok_injected += 1
        elif stats["status"] == "ok_nullified":
            n_ok_nullified += 1

        if stats["status"] == "ok_injected":
            flag = "OK  "
        elif stats["status"] == "ok_nullified":
            flag = "NULL"
        else:
            flag = "????"
        print(f"  [{flag}] {jsonl_path.name:25s} lines={stats['lines']:5d} "
              f"inj={stats['injected']:5d} nul={stats.get('nullified',0):5d} "
              f"json={stats.get('json') or '-'}")

    print()
    print(f"=== SUMMARY ===")
    print(f"  Files injected (JSON OK)   : {n_ok_injected}")
    print(f"  Files nullified (no JSON)  : {n_ok_nullified}")
    print(f"  Total lines                : {total_lines}")
    print(f"  Lines with MenthorQ inject : {total_injected}")
    print(f"  Lines with mq_* nullified  : {total_nullified}")
    if total_lines > 0:
        pct_ok = 100.0 * total_injected / total_lines
        print(f"  Pct usable for ML (mq ok)  : {pct_ok:.1f}%")


if __name__ == "__main__":
    main()
