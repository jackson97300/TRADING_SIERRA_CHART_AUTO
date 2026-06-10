"""Inspect decisions MGC contenu."""
import json
from pathlib import Path

log = Path(r"C:\TRADING_SIERRA_CHART_AUTO\LOGS\decisions\decisions_20260512_paper_v2.jsonl")
mgc_decisions = []
with open(log, "r", encoding="utf-8") as f:
    for line in f:
        try:
            evt = json.loads(line)
        except Exception:
            continue
        ctx = evt.get("ctx") or {}
        if ctx.get("sym") == "MGC":
            mgc_decisions.append(evt)

print(f"Total MGC decisions : {len(mgc_decisions)}")
print()
for e in mgc_decisions[-10:]:
    print(f"  {e['ts']} {e['code']}")
    print(f"    msg : {e.get('msg_fr', '')[:160]}")
    ctx = e.get("ctx") or {}
    print(f"    ctx : {dict((k, v) for k, v in ctx.items() if k != 'sym')}")
    print()
