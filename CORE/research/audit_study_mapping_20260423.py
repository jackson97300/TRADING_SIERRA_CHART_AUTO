"""Audit complet study_mapping.json vs dumps chart_*.json (actifs).

Objectif : identifier quelles entrees du mapping pointent vers des etudes
reelles et quelles sont cassees/absentes.

Pour chaque entree du mapping :
  - Verifier que le chart existe (chart_N.json present)
  - Verifier que le Study ID existe dans ce chart
  - Recuperer le nom de l'etude mappee (pour validation manuelle)
  - Flagger si le nom ne matche pas le label attendu

Usage :
  python -X utf8 CORE/research/audit_study_mapping_20260423.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MAPPING_FILE = ROOT / "CPP" / "MIA_REFACTORED" / "study_mapping.json"
STUDIES_DIR = ROOT / "STUDIES"


def load_mapping():
    with open(MAPPING_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_chart_dump(chart_num: int):
    fp = STUDIES_DIR / f"chart_{chart_num}.json"
    if not fp.exists():
        return None
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


def find_study_by_id(chart_dump, study_id):
    """Trouve une etude dans le dump par son study_id (ou study_index)."""
    if not chart_dump:
        return None
    for s in chart_dump.get("studies", []):
        # Le field peut s'appeler study_id ou study_index ou id
        sid = s.get("study_id") or s.get("study_index") or s.get("id")
        if sid == study_id or str(sid) == str(study_id):
            return s
    return None


# Labels qui peuvent matcher (tolerant : le nom d'etude SC peut etre plus long)
LABEL_KEYWORDS = {
    "EDGE_BUY": ["EDGE", "BUY", "IMBALANCE"],
    "EDGE_SELL": ["EDGE", "SELL", "IMBALANCE"],
    "COLOR_UP": ["COLOR", "UP"],
    "COLOR_DOWN": ["COLOR", "DOWN"],
    "ABSORB_ASK": ["ABSORB", "ASK"],
    "ABSORB_BID": ["ABSORB", "BID"],
    "ROTATION_UP": ["ROTATION", "UP"],
    "ROTATION_DOWN": ["ROTATION", "DOWN"],
    "FPBS": ["FPBS"],
    "TRIPLE_ASK": ["TRIPLE", "ASK"],
    "TRIPLE_BID": ["TRIPLE", "BID"],
    "DOUBLE_ASK": ["DOUBLE", "ASK"],
    "DOUBLE_BID": ["DOUBLE", "BID"],
    "VOLUME_UP": ["VOLUME", "UP"],
    "VOLUME_DOWN": ["VOLUME", "DOWN"],
    "CLUSTER_VOL": ["CLUSTER"],
    "LONG_UP_BAR": ["LONG", "UP", "BAR"],
    "LONG_DOWN_BAR": ["LONG", "DOWN", "BAR"],
    "LONG_DOWN_UP": ["LONG", "DOWN", "UP"],
    "LONG_UP_DOWN": ["LONG", "UP", "DOWN"],
    "MQ_GAMMA": ["GAMMA"],
    "MQ_BLIND": ["BLIND"],
    "VWAP": ["VWAP"],
    "VP": ["VOLUME PROFILE", "VP"],
    "ASK_10": ["ASK", "10"],
    "BID_10": ["BID", "10"],
    "ASK_30": ["ASK", "30"],
    "BID_30": ["BID", "30"],
    "ASK_100": ["ASK", "100"],
    "BID_100": ["BID", "100"],
    "ASK_150": ["ASK", "150"],
    "BID_150": ["BID", "150"],
    "ASK_400": ["ASK", "400"],
    "BID_400": ["BID", "400"],
    "ASK_1000": ["ASK", "1000"],
    "BID_1000": ["BID", "1000"],
}


def check_label_match(label: str, study_name: str) -> bool:
    """Verifie si le nom d'etude contient les keywords attendus du label."""
    name_up = (study_name or "").upper()
    keywords = LABEL_KEYWORDS.get(label, [label])
    return all(kw.upper() in name_up for kw in keywords)


def audit():
    mapping = load_mapping()

    print("=" * 90)
    print("AUDIT STUDY_MAPPING.JSON vs DUMPS CHART_*.JSON (local, 22/04 22:55)")
    print("=" * 90)

    total_ok = total_missing_chart = total_missing_study = total_mismatch = 0

    for group_key, group_data in mapping.items():
        if group_key.startswith("_"):
            continue
        chart_num = group_data.get("chart_number", -1)
        desc = group_data.get("description", "")
        studies = group_data.get("studies", {})

        chart_dump = load_chart_dump(chart_num)

        print(f"\n{'=' * 90}")
        print(f"{group_key} — chart #{chart_num} — {desc}")
        print(f"{'=' * 90}")
        if chart_dump is None:
            print(f"  ❌ Chart #{chart_num} : fichier chart_{chart_num}.json ABSENT")
            total_missing_chart += len(studies)
            continue

        chart_sym = chart_dump.get("chart_symbol", "?")
        n_studies = len(chart_dump.get("studies", []))
        print(f"  Chart dump : symbol={chart_sym}, {n_studies} studies dans dump")
        print(f"  {'Label':<22} {'ID':>4} {'Short Name':<40} {'Match':<6} {'Verdict'}")
        print(f"  {'-'*22} {'-'*4} {'-'*40} {'-'*6} {'-'*20}")

        for label, study_id in studies.items():
            st = find_study_by_id(chart_dump, study_id)
            if st is None:
                print(f"  {label:<22} {study_id:>4} {'???':<40} {'❌':<6} ID absent du chart")
                total_missing_study += 1
                continue
            name = st.get("name", "")
            short = st.get("short_name", "") or name
            short_trunc = short[:38] + ".." if len(short) > 40 else short
            match = check_label_match(label, name) or check_label_match(label, short)
            if match:
                print(f"  {label:<22} {study_id:>4} {short_trunc:<40} {'✅':<6} OK")
                total_ok += 1
            else:
                print(f"  {label:<22} {study_id:>4} {short_trunc:<40} {'⚠️':<6} Mismatch nom")
                total_mismatch += 1

    # Summary
    print(f"\n{'=' * 90}")
    print(f"SUMMARY")
    print(f"{'=' * 90}")
    print(f"  OK               : {total_ok}")
    print(f"  Mismatch nom     : {total_mismatch}")
    print(f"  Study ID absent  : {total_missing_study}")
    print(f"  Chart absent     : {total_missing_chart}")
    print(f"  Total mappings   : {total_ok + total_mismatch + total_missing_study + total_missing_chart}")


if __name__ == "__main__":
    audit()
