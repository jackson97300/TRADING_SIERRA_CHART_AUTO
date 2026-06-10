"""Clean Bot 2 state.json apres Flatten manuel Sierra Chart Sim2.

Wipe active_positions du state + archive l'ancien databento_active_positions.json
pour eviter OCO recovery au prochain boot (les ordres sont deja cancel manuellement).
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

PAPER_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/PAPER_TRADES")

# 1. Wipe active_positions dans databento_paper_state.json (consume par dashboard)
state_fp = PAPER_DIR / "databento_paper_state.json"
if state_fp.exists():
    s = json.loads(state_fp.read_text(encoding="utf-8"))
    n_before = len(s.get("active_positions", {}))
    s["active_positions"] = {}
    s["ts"] = datetime.now(timezone.utc).isoformat()
    s["_clean_reason"] = "manual_flatten_sim2_post_desync_29042026"
    state_fp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(f"[OK] {state_fp.name} : active_positions {n_before} -> 0")
else:
    print(f"[SKIP] {state_fp.name} not found")

# 2. Archive databento_active_positions.json (recovery boot file)
recovery_fp = PAPER_DIR / "databento_active_positions.json"
if recovery_fp.exists():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    archive = recovery_fp.with_suffix(f".json.processed.{ts}.manual_clean")
    shutil.move(str(recovery_fp), str(archive))
    print(f"[OK] Archive {recovery_fp.name} -> {archive.name}")
else:
    print(f"[SKIP] {recovery_fp.name} not found (deja absent)")

print("\nDashboard va voir 0 positions Bot 2 dans 5s (prochain fetch).")
