"""Cherche tous les events ORDER_UPDATE / FILL pour le trade NQ 02:54:51-03:02:35."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TS_LO = "2026-05-12T02:54:00Z"
TS_HI = "2026-05-12T03:03:00Z"

print("=== Tous events execution 02:54-03:03 (NQ) ===")
fp = ROOT / "LOGS" / "execution" / "execution_20260512_paper_v2.jsonl"
n = 0
fill_count = 0
with open(fp, encoding="utf-8") as f:
    for line in f:
        try:
            j = json.loads(line)
        except Exception:
            continue
        ts = j.get("ts", "")
        if not (TS_LO <= ts <= TS_HI):
            continue
        ctx = j.get("ctx", {})
        if ctx.get("sym") != "NQ" and "NQ" not in json.dumps(ctx):
            continue
        code = j.get("code", "")
        if code == "BOT3_LADDER_TICK":
            continue
        n += 1
        if "FILL" in code or "ORDER" in code:
            fill_count += 1
        print(f"  {ts[11:19]} {code:<40} {json.dumps(ctx, default=str)[:250]}")

print(f"\nTotal non-ladder events : {n}")
print(f"FILL/ORDER events : {fill_count}")

print("\n=== events_paper_v2 (BOT3_*) 02:54-03:03 ===")
fp = ROOT / "LOGS" / "events" / "events_20260512_paper_v2.jsonl"
with open(fp, encoding="utf-8") as f:
    for line in f:
        try:
            j = json.loads(line)
        except Exception:
            continue
        ts = j.get("ts", "")
        if not (TS_LO <= ts <= TS_HI):
            continue
        code = j.get("code", "")
        if code == "BOT_HEARTBEAT":
            continue
        ctx = j.get("ctx", {})
        print(f"  {ts[11:19]} {code:<40} {json.dumps(ctx, default=str)[:200]}")
