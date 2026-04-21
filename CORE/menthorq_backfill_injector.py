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

    # Format nouveau : vol_model.ES/NQ (et key_levels.ES/NQ pour Claude extension format)
    if "vol_model" in data and symbol in data["vol_model"]:
        vm = data["vol_model"][symbol]
        kl = data.get("key_levels", {}).get(symbol, {}) if isinstance(data.get("key_levels"), dict) else {}

        # Normalize bl_levels : accepte liste de floats OU liste de dicts {"level": X, ...}
        bl_raw = vm.get("bl_levels") or []
        bl_levels_norm: list[float] = []
        for item in bl_raw:
            if isinstance(item, dict):
                lvl = item.get("level")
                if isinstance(lvl, (int, float)):
                    bl_levels_norm.append(float(lvl))
            elif isinstance(item, (int, float)):
                bl_levels_norm.append(float(item))

        # [21/04/2026] Derivation mq_gamma_condition + features regime (review code-reviewer).
        # Regle : gamma_condition = 1 si net_gex > 0 (dealer long gamma, stabilisant),
        #                           0 si net_gex <= 0 (dealer short gamma, amplifiant).
        # Finding 15/04 (feedback_regime_gex_finding.md) : +56% PF gap ES SELL
        # GEX- (3.68) vs GEX+ (2.36). Critique pour regime switching ML.
        #
        # data-quality.md compliance : net_gex/total_gex ABSOLUS (113M ES vs 3.9M NQ)
        # violent la regle souveraine "pas d'absolus non normalises". Donc :
        #   - DROP net_gex / total_gex bruts
        #   - ADD net_gex_norm = net_gex / total_gex (ratio ES=NQ comparable)
        # gamma_condition binaire 0/1 = normalise par nature (ES/NQ comparable).
        #
        # Null handling : seuil bruit 1M pour eviter flip pres de zero (signal faible).
        import math
        mq_net_gex_raw = _parse_suffix_number(vm.get("net_gex"))
        mq_total_gex_raw = _parse_suffix_number(vm.get("total_gex"))

        # Guard NaN (edge case : JSON "NaN" → float('nan') qui passe isinstance check)
        if mq_net_gex_raw is not None and math.isnan(mq_net_gex_raw):
            mq_net_gex_raw = None
        if mq_total_gex_raw is not None and math.isnan(mq_total_gex_raw):
            mq_total_gex_raw = None

        if mq_net_gex_raw is None or abs(mq_net_gex_raw) < 1e6:
            mq_gamma_condition = None
        else:
            mq_gamma_condition = 1 if mq_net_gex_raw > 0 else 0

        if mq_net_gex_raw is not None and mq_total_gex_raw is not None and mq_total_gex_raw > 0:
            mq_net_gex_norm = mq_net_gex_raw / mq_total_gex_raw
        else:
            mq_net_gex_norm = None

        result = {
            "mq_call": _to_float(kl.get("call_resistance")),
            "mq_put": _to_float(kl.get("put_support")),
            "mq_hvl": _to_float(kl.get("hvl")),
            "mq_call_0dte": _to_float(kl.get("call_resistance_0dte")),
            "mq_put_0dte": _to_float(kl.get("put_support_0dte")),
            "mq_1d_max": _to_float(kl.get("1d_max")),
            "mq_1d_min": _to_float(kl.get("1d_min")),
            "bl_levels": bl_levels_norm,
            "gamma_wall_0dte": _to_float(vm.get("gamma_wall_0dte")),
            # [NEW 21/04] Regime switching features (NORMALISEES, post review)
            "mq_gamma_condition": mq_gamma_condition,   # binaire 0/1
            "mq_net_gex_norm": mq_net_gex_norm,         # net/total [-1, 1] ratio
            "mq_iv_30d": _to_float(vm.get("iv_30d")),   # exempter NATURALLY_DIFFERENT
            "mq_pc_gex": _to_float(vm.get("pc_gex")),   # ratio [0, ~5]
            "mq_pc_dex": _to_float(vm.get("pc_dex")),   # ratio [0, ~5]
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


def _parse_suffix_number(v) -> Optional[float]:
    """Parse '523.99M' -> 523990000.0, '-12.5B' -> -1.25e10, '100K' -> 100000.0.

    Gere les suffixes M/B/K (multiplicateurs 1e6/1e9/1e3). Le signe est dans
    la partie numerique (ex: '-214.04M'). Retourne None si invalid.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    mult = 1.0
    if s.endswith("M"):
        mult = 1e6
        s = s[:-1]
    elif s.endswith("B"):
        mult = 1e9
        s = s[:-1]
    elif s.endswith("K"):
        mult = 1e3
        s = s[:-1]
    elif s.endswith("%"):
        return None
    try:
        return float(s) * mult
    except ValueError:
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

    # [NEW 21/04] Scalaires regime daily (post review code-reviewer)
    # Ces features sont NORMALISEES (ratios ou binaires) donc ES/NQ comparables.
    # Injection directe sans transformation (pas de distances/ticks).
    for scalar_feat in ["mq_gamma_condition", "mq_net_gex_norm", "mq_iv_30d",
                        "mq_pc_gex", "mq_pc_dex"]:
        val = levels.get(scalar_feat)
        if val is not None:
            row[scalar_feat] = val

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
    # [NEW 21/04] Regime switching scalaires daily
    "mq_gamma_condition",
    "mq_net_gex_norm",
    "mq_iv_30d",
    "mq_pc_gex",
    "mq_pc_dex",
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
