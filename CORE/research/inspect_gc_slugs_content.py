"""Inspecter le contenu des 7 slugs GC qui marchent (levels_tv critique)."""
import sys, json
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

from mia_menthorq_scraper import create_session, get_nonce, fetch_all_slugs

session = create_session(creds.get("MENTHORQ_EMAIL"), creds.get("MENTHORQ_PASSWORD"))
nonce = get_nonce(session, "2026-05-08", "gc1!")

SLUGS_OK = ["levels_tv", "bl_levels", "future_curve",
            "qscore_option", "qscore_momentum", "qscore_volatility", "qscore_seasonality"]
raw = fetch_all_slugs(session, nonce, SLUGS_OK, "gc1!", "2026-05-08")

for slug, data in raw.items():
    print(f"\n{'='*60}")
    print(f"=== {slug} ===")
    print(f"{'='*60}")
    if not isinstance(data, dict) or not data.get("success"):
        print(f"  FAIL")
        continue
    d_val = data.get("data")
    if isinstance(d_val, dict):
        print(f"  Keys: {list(d_val.keys())}")
        for k, v in d_val.items():
            if isinstance(v, (str, int, float)):
                print(f"  {k}: {str(v)[:150]}")
            elif isinstance(v, list):
                print(f"  {k}: LIST len={len(v)}")
                if v and len(v) > 0:
                    print(f"    first: {str(v[0])[:200]}")
            elif isinstance(v, dict):
                print(f"  {k}: DICT keys={list(v.keys())[:8]}")
                if 'resource' in k.lower():
                    for kk, vv in list(v.items())[:5]:
                        print(f"    {kk}: {str(vv)[:200]}")
