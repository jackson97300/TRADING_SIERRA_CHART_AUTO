"""Test exhaustif quels slugs MenthorQ marchent pour GC sur 1 weekday récent."""
import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CORE"))

env_file = ROOT / "CORE" / ".env.menthorq"
if not env_file.exists():
    env_file = Path("C:/TRADING_SIERRA_CHART_AUTO/CORE/.env.menthorq")
creds = {}
for line in env_file.read_text().split("\n"):
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        creds[k.strip()] = v.strip()

from mia_menthorq_scraper import create_session, get_nonce, fetch_all_slugs, FUTURES_SLUGS

session = create_session(creds.get("MENTHORQ_EMAIL"), creds.get("MENTHORQ_PASSWORD"))
if not session:
    sys.exit(1)

DATE = "2026-05-08"  # vendredi récent où bl_levels marche
print(f"\n=== Test ALL 11 GC slugs sur {DATE} (vendredi) ===\n")
nonce = get_nonce(session, DATE, "gc1!")
raw = fetch_all_slugs(session, nonce, FUTURES_SLUGS, "gc1!", DATE)

success = []
fail_failed_retrieve = []
fail_date_unavail = []
fail_other = []

for slug, data in raw.items():
    if not isinstance(data, dict):
        fail_other.append(slug)
        continue
    if data.get("success") is True:
        d_val = data.get("data")
        n_keys = len(d_val) if isinstance(d_val, dict) else 0
        success.append((slug, n_keys))
    else:
        err_data = data.get("data", {})
        msg = err_data.get("message", "?") if isinstance(err_data, dict) else "?"
        if "Failed to retrieve" in msg:
            fail_failed_retrieve.append(slug)
        elif "date_unavailable" in str(err_data.get("error_type", "")):
            fail_date_unavail.append(slug)
        else:
            fail_other.append((slug, msg[:60]))

print(f"\n=== RESUME ===")
print(f"\nSUCCESS ({len(success)} slugs) :")
for slug, n in success:
    print(f"  ✓ {slug:25s} (n_keys={n})")

print(f"\nFAIL 'Failed to retrieve' ({len(fail_failed_retrieve)} slugs) :")
for slug in fail_failed_retrieve:
    print(f"  ✗ {slug}")

print(f"\nFAIL date_unavailable ({len(fail_date_unavail)} slugs) :")
for slug in fail_date_unavail:
    print(f"  ✗ {slug}")

print(f"\nOTHER fail ({len(fail_other)}) :")
for x in fail_other:
    print(f"  ? {x}")
