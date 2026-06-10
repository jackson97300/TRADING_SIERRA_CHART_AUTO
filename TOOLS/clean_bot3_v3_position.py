"""One-shot : nettoie position fantome Bot 3 v3 dans state file (10/06/2026).

Position fantome NQ LONG entry=28972 cause par cascade rejection TP+SL 07:05:50
suite au bug Price1 manquant sur ladder promotion. Position SC fermee manuellement
par Jackson mais state Python conservait la position.

Usage VPS apres backup :
  python -X utf8 C:\\TRADING_SIERRA_CHART_AUTO\\tools\\clean_bot3_v3_position.py
"""
import json
from datetime import datetime, timezone

STATE_PATH = "C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES/bot3_v3_state.json"

with open(STATE_PATH, "r", encoding="utf-8") as f:
    state = json.load(f)

print("Position NQ avant nettoyage :")
print(json.dumps(state.get("positions", {}).get("NQ"), indent=2))

# Clean position NQ
state["positions"]["NQ"] = None
state["last_update_ts"] = datetime.now(timezone.utc).isoformat()

with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)

# Verify
with open(STATE_PATH, "r", encoding="utf-8") as f:
    state_after = json.load(f)

print("\nPosition NQ apres nettoyage :")
print(json.dumps(state_after.get("positions", {}).get("NQ"), indent=2))
print(f"\nlast_update_ts = {state_after.get('last_update_ts')}")
print("\n[OK] Clean termine. Dashboard se rafraichira au prochain restart paper_trader.")
