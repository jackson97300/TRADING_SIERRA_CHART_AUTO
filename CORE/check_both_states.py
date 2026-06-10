"""Verifier l'etat reel des 2 bots."""
import json
from pathlib import Path

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")

# === BOT 1 Sim3 ===
print("="*70)
print("  BOT 1 Sim3 (mia_paper_trader) — state.json")
print("="*70)
fp1 = PAPER_DIR / "state.json"
s1 = json.loads(fp1.read_text(encoding="utf-8"))
obs = s1.get("open_by_symbol", {})
print(f"\nopen_by_symbol : {len(obs)} positions")
for sym, p in obs.items():
    print(f"\n  {sym}:")
    for k, v in p.items():
        print(f"    {k} = {v}")

# === BOT 2 Sim2 ===
print()
print("="*70)
print("  BOT 2 Sim2 (databento_paper_trader) — databento_paper_state.json")
print("="*70)
fp2 = PAPER_DIR / "databento_paper_state.json"
s2 = json.loads(fp2.read_text(encoding="utf-8"))
ap = s2.get("active_positions", {})
print(f"\nactive_positions : {len(ap)} positions")
for sym, p in ap.items():
    print(f"\n  {sym}:")
    for k, v in p.items():
        if k == "checks":
            print(f"    {k} = {v[:3] if isinstance(v, list) else v}")
        else:
            print(f"    {k} = {v}")
