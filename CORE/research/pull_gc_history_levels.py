"""Backfill historique MenthorQ Gold (GC) levels — 12 mois weekdays via AJAX.

Mission (12/05/2026 Jackson) : reconstruire l'historique des niveaux MenthorQ Gold
sur 12 mois pour injection dans dataset ML.

Source AJAX (testé OK) :
  - `levels_tv` → text_data : Call Resist, Put Support, HVL, 1D Max/Min, 0DTE, Gamma Wall
  - `bl_levels` → text_data : BL 1-10 (Blind Spots)

Skip : netgex, key_levels, matrix_v1, netgex_multiexpiry (FAIL "Failed to retrieve" pour GC)
       → ces valeurs (gamma exposure, IV, etc.) seront collectées via prompt manuel séparé.

Output : DATA/MENTHORQ/gold_history/YYYYMMDD_gold_levels.json par date

Usage :
  python -X utf8 CORE/research/pull_gc_history_levels.py
  python -X utf8 CORE/research/pull_gc_history_levels.py --from 2025-05-12 --to 2026-05-12
  python -X utf8 CORE/research/pull_gc_history_levels.py --from 2025-05-12 --to 2026-05-12 --force
"""
import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

# Charge credentials .env.menthorq
env_file = ROOT / "CORE" / ".env.menthorq"
if not env_file.exists():
    env_file = Path("C:/TRADING_SIERRA_CHART_AUTO/CORE/.env.menthorq")
if not env_file.exists():
    print(f"ERROR: .env.menthorq introuvable")
    sys.exit(1)

creds = {}
for line in env_file.read_text().split("\n"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()

from mia_menthorq_scraper import create_session, get_nonce, fetch_all_slugs

OUT_DIR = ROOT / "DATA" / "MENTHORQ" / "gold_history"
OUT_DIR.mkdir(parents=True, exist_ok=True)

GC_TICKER_POST = "gc1!"
GC_SLUGS_OK = ["levels_tv", "bl_levels"]   # validés OK pour GC weekday

# Slugs bonus (images PNG, optionnel pour metadata)
GC_SLUGS_IMG = ["qscore_option", "qscore_momentum", "qscore_volatility",
                "qscore_seasonality", "future_curve"]


# ─────────────────────────────────────────────────────────────────────────────
# PARSERS text_data
# ─────────────────────────────────────────────────────────────────────────────

def parse_levels_tv(text_data: str) -> dict:
    """Parse levels_tv.text_data Gold pour extraire les key levels.

    Format observé (08/05/2026) :
      "$GC1!: Call Resistance, 4789.55, Put Support, 4440.31, HVL, 4585,
       1D Min, 4652.65, 1D Max, 4788.15,
       Call Resistance 0DTE, 4689.77, Put Support 0DTE, 4679.79,
       HVL 0DTE, 4684.78, Gamma Wall 0DTE, 4689.7..."

    Returns dict avec keys mappées (snake_case).
    """
    if not text_data or not isinstance(text_data, str):
        return {}

    # Mapping label → key snake_case
    LABEL_MAP = {
        "Call Resistance 0DTE": "call_resistance_0dte",
        "Put Support 0DTE": "put_support_0dte",
        "HVL 0DTE": "hvl_0dte",
        "Gamma Wall 0DTE": "gamma_wall_0dte",
        "Call Resistance": "call_resistance",
        "Put Support": "put_support",
        "HVL": "hvl",
        "1D Min": "one_day_min",
        "1D Max": "one_day_max",
    }

    result = {}
    # Strip prefix $GC1!: si présent
    cleaned = text_data.replace("$GC1!:", "").strip()

    # Stratégie : parser par tokens "Label, Value" sequentiellement.
    # Le format MenthorQ est : "Label1, Value1, Label2, Value2, ..."
    # Mais "Call Resistance 0DTE" contient une virgule potentielle ? Non, juste "0DTE".
    # Splitter par "," strict.
    tokens = [t.strip() for t in cleaned.split(",")]

    # Itérer : on cherche chaque label dans LABEL_MAP, puis on prend la valeur juste après.
    # On itère sur les labels les plus longs d'abord (anti collision "Call Resistance" vs "Call Resistance 0DTE").
    labels_sorted = sorted(LABEL_MAP.keys(), key=lambda x: -len(x))

    i = 0
    while i < len(tokens):
        matched = False
        for label in labels_sorted:
            # Check si tokens[i] commence par le label (espaces normalisés)
            if tokens[i] == label and i + 1 < len(tokens):
                key = LABEL_MAP[label]
                if key not in result:  # ne pas override (premier match seulement)
                    try:
                        result[key] = float(tokens[i + 1])
                    except (ValueError, TypeError):
                        result[key] = None
                    i += 2
                    matched = True
                    break
        if not matched:
            i += 1

    return result


def parse_bl_levels(text_data: str) -> list:
    """Parse bl_levels.text_data Gold pour extraire les 10 Blind Spots.

    Format observé : "$GC1!: BL 1, 4418.15, BL 2, 4642.18, BL 3, 4840.77, ..."

    Returns list de 10 dicts {level, type, rank}.
    """
    if not text_data or not isinstance(text_data, str):
        return []

    cleaned = text_data.replace("$GC1!:", "").strip()
    # Regex pour extraire "BL N, value"
    matches = re.findall(r"BL\s+(\d+),\s*([0-9.]+)", cleaned)
    result = []
    for rank_str, val_str in matches:
        try:
            result.append({
                "level": float(val_str),
                "type": "blind_spot",
                "rank": int(rank_str),
            })
        except (ValueError, TypeError):
            continue
    # Sort par rank
    result.sort(key=lambda x: x["rank"])
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PULL 1 DATE
# ─────────────────────────────────────────────────────────────────────────────

def pull_gc_date(session, date_str: str) -> dict | None:
    """Pull GC levels pour 1 date. Returns dict structuré ou None si fail."""
    nonce = get_nonce(session, date_str, GC_TICKER_POST)
    if not nonce:
        return None

    # Pull les 2 slugs critiques
    raw = fetch_all_slugs(session, nonce, GC_SLUGS_OK, GC_TICKER_POST, date_str)

    # Vérifier success
    levels_tv = raw.get("levels_tv", {})
    bl_levels = raw.get("bl_levels", {})

    levels_success = levels_tv.get("success") is True
    bl_success = bl_levels.get("success") is True

    if not levels_success and not bl_success:
        # Date probablement weekend / data unavailable
        return None

    # Parse text_data
    parsed_levels = {}
    if levels_success:
        text = levels_tv.get("data", {}).get("resource", {}).get("text_data", "")
        parsed_levels = parse_levels_tv(text)

    parsed_bl = []
    if bl_success:
        text = bl_levels.get("data", {}).get("resource", {}).get("text_data", "")
        parsed_bl = parse_bl_levels(text)

    # Pull image_urls (qscore + future_curve) - bonus metadata
    image_urls = {}
    raw_img = fetch_all_slugs(session, nonce, GC_SLUGS_IMG, GC_TICKER_POST, date_str)
    for slug, dat in raw_img.items():
        if isinstance(dat, dict) and dat.get("success"):
            url = dat.get("data", {}).get("resource", {}).get("image_url", "")
            if url:
                image_urls[slug] = url

    return {
        "date": date_str,
        "source": "MenthorQ AJAX scraper backfill - GC",
        "scrape_time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ticker": "GC (gc1!)",
        "key_levels": parsed_levels,
        "bl_levels": parsed_bl,
        "image_urls": image_urls,
        "raw_success": {
            "levels_tv": levels_success,
            "bl_levels": bl_success,
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# BATCH
# ─────────────────────────────────────────────────────────────────────────────

def iter_weekdays(start: date, end: date):
    """Yield weekdays (Mon-Fri) entre start et end."""
    cur = start
    while cur <= end:
        if cur.weekday() < 5:   # 0=Mon, 4=Fri
            yield cur
        cur += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="date_from", default=None,
                        help="Date début YYYY-MM-DD (default = 12 mois avant aujourd'hui)")
    parser.add_argument("--to", dest="date_to", default=None,
                        help="Date fin YYYY-MM-DD (default = aujourd'hui)")
    parser.add_argument("--force", action="store_true",
                        help="Re-pull même si fichier existe")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit N dates (debug)")
    args = parser.parse_args()

    today = date.today()
    if args.date_from:
        d_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
    else:
        d_from = today - timedelta(days=365)
    if args.date_to:
        d_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()
    else:
        d_to = today - timedelta(days=1)   # hier (today souvent pas encore publié)

    print(f"=== Backfill historique Gold MenthorQ levels ===")
    print(f"  Range : {d_from} -> {d_to}")
    print(f"  Output : {OUT_DIR}")
    print(f"  Slugs OK : {GC_SLUGS_OK} (validés AJAX)")
    print()

    # Login
    session = create_session(creds.get("MENTHORQ_EMAIL"), creds.get("MENTHORQ_PASSWORD"))
    if not session:
        print("ECHEC LOGIN")
        sys.exit(1)

    dates = list(iter_weekdays(d_from, d_to))
    if args.limit:
        dates = dates[:args.limit]
    print(f"  Weekdays à pull : {len(dates)}")
    print()

    n_ok = 0
    n_skip = 0
    n_fail = 0
    n_existing = 0

    for i, d in enumerate(dates, 1):
        date_str = d.strftime("%Y-%m-%d")
        out_file = OUT_DIR / f"{d.strftime('%Y%m%d')}_gold_levels.json"

        if out_file.exists() and not args.force:
            n_existing += 1
            continue

        result = pull_gc_date(session, date_str)
        if result is None:
            n_fail += 1
            print(f"  [{i:3d}/{len(dates)}] {date_str} FAIL (probably no data)")
            continue

        # Vérifier qualité
        has_levels = bool(result["key_levels"])
        has_bl = len(result["bl_levels"]) > 0
        if not has_levels and not has_bl:
            n_skip += 1
            continue

        with out_file.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        n_ok += 1

        if i % 20 == 0 or i == len(dates):
            n_keys = len(result["key_levels"])
            n_bls = len(result["bl_levels"])
            print(f"  [{i:3d}/{len(dates)}] {date_str} OK "
                  f"(keys={n_keys}, bl={n_bls})", flush=True)

        # Rate limit anti-ban MenthorQ
        time.sleep(0.5)

    print()
    print(f"=== RESUME ===")
    print(f"  OK    : {n_ok}")
    print(f"  Skip empty : {n_skip}")
    print(f"  Fail  : {n_fail}")
    print(f"  Existing (skipped) : {n_existing}")
    print(f"  Total processed : {n_ok + n_skip + n_fail + n_existing} / {len(dates)}")
    print(f"  Output : {OUT_DIR}")


if __name__ == "__main__":
    main()
