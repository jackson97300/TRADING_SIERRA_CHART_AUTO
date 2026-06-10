"""Test direct MenthorQ AJAX pour GC sur date weekday (validation backfill auto).

Hypothese : MenthorQ retourne 422 'date_unavailable' sur 09/05 (samedi). Si l'API
marche en weekday (08/05 vendredi), backfill auto Gold possible.

Sinon : MenthorQ AJAX bloque Gold globalement → backfill manuel obligatoire.
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

# Charge credentials
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

email = creds.get("MENTHORQ_EMAIL")
password = creds.get("MENTHORQ_PASSWORD")
session = create_session(email, password)
if not session:
    print("ECHEC LOGIN")
    sys.exit(1)

# Test plusieurs dates : weekdays récents
DATES_TO_TEST = [
    "2026-05-08",  # vendredi
    "2026-05-07",  # jeudi
    "2026-05-06",  # mercredi
    "2026-05-05",  # mardi
    "2026-05-04",  # lundi
    "2026-05-12",  # today lundi
]

for date in DATES_TO_TEST:
    print(f"\n=== TEST GC sur {date} ===")
    nonce = get_nonce(session, date, "gc1!")
    if not nonce:
        print(f"  ECHEC nonce")
        continue
    # Test 3 slugs : key_levels, netgex, bl_levels
    raw = fetch_all_slugs(session, nonce, ["key_levels", "netgex", "bl_levels"], "gc1!", date)
    for slug, data in raw.items():
        if isinstance(data, dict):
            if data.get("success") is True:
                d_val = data.get("data")
                if isinstance(d_val, dict) and d_val:
                    print(f"  {slug}: SUCCESS keys={list(d_val.keys())[:5]}")
                else:
                    print(f"  {slug}: SUCCESS but empty data")
            else:
                err = data.get("data", {}).get("message", "?") if isinstance(data.get("data"), dict) else "?"
                print(f"  {slug}: FAIL — {err[:80]}")
        else:
            print(f"  {slug}: unexpected type {type(data).__name__}")
