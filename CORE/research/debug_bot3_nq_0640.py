"""Analyse complete du trade Bot 3 NQ BUY 06:40:57 UTC du 12/05/2026.

Cherche : niveau, tier, conseil, gates passes, raisonnement.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_TS = "2026-05-12T06:40"
TARGET_END = "2026-05-12T06:41"

print("=" * 80)
print("ANALYSE TRADE Bot 3 NQ BUY 06:40:57 UTC du 12/05/2026")
print("=" * 80)

# 1. TRADE_OPEN event
print("\n=== BOT3_TRADE_OPEN ===")
fp = ROOT / "LOGS" / "trading" / "trading_20260512_paper_v2.jsonl"
with open(fp, encoding="utf-8") as f:
    for line in f:
        if "BOT3_TRADE_OPEN" in line and TARGET_TS in line:
            j = json.loads(line)
            print(f"  ts: {j.get('ts')}")
            print(f"  msg: {j.get('msg_fr')}")
            print(f"  ctx: {json.dumps(j.get('ctx', {}), indent=2)}")

# 2. Decisions log
print("\n=== DECISIONS Bot 3 (06:38-06:41 UTC NQ) ===")
fp = ROOT / "LOGS" / "decisions" / "decisions_20260512_paper_v2.jsonl"
if fp.exists():
    with open(fp, encoding="utf-8") as f:
        for line in f:
            ts = line[8:27]
            if "2026-05-12T06:3" in line or "2026-05-12T06:40" in line or "2026-05-12T06:41" in line:
                try:
                    j = json.loads(line)
                    ctx = j.get("ctx", {})
                    if ctx.get("sym") == "NQ" or "NQ" in line:
                        code = j.get("code", "")
                        print(f"  {j.get('ts')[11:19]} {code}")
                        relevant = {k: v for k, v in ctx.items() if k != "trace"}
                        if relevant:
                            print(f"    {json.dumps(relevant, default=str)[:250]}")
                except Exception:
                    pass
else:
    print("  No decisions_paper_v2 file")

# 3. Events Bot 3 (TIER, GATE_*)
print("\n=== EVENTS Bot 3 NQ 06:38-06:41 UTC ===")
fp = ROOT / "LOGS" / "events" / "events_20260512_paper_v2.jsonl"
seen_codes = []
with open(fp, encoding="utf-8") as f:
    for line in f:
        if "2026-05-12T06:3" not in line and "2026-05-12T06:40" not in line and "2026-05-12T06:41" not in line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        ctx = j.get("ctx", {})
        code = j.get("code", "")
        if code == "BOT_HEARTBEAT":
            continue
        if ctx.get("sym") == "NQ" or code in ("BRAIN_V6_ACTIVE", "LIVE_REF_USED", "BOT_ENTRY_FILL_RECORDED"):
            relevant = {k: v for k, v in ctx.items() if k != "trace"}
            if relevant.get("sym") == "NQ" or not relevant:
                print(f"  {j.get('ts')[11:19]} {code}")
                print(f"    {json.dumps(relevant, default=str)[:300]}")
                seen_codes.append(code)

# 4. Execution events
print("\n=== EXECUTION Bot 3 NQ 06:40-06:41 UTC ===")
fp = ROOT / "LOGS" / "execution" / "execution_20260512_paper_v2.jsonl"
with open(fp, encoding="utf-8") as f:
    for line in f:
        if TARGET_TS not in line and "2026-05-12T06:41" not in line:
            continue
        try:
            j = json.loads(line)
        except Exception:
            continue
        ctx = j.get("ctx", {})
        if ctx.get("sym") != "NQ":
            continue
        code = j.get("code", "")
        if code == "BOT3_LADDER_TICK":
            continue
        print(f"  {j.get('ts')[11:19]} {code}")
        relevant = {k: v for k, v in ctx.items() if k != "trace"}
        print(f"    {json.dumps(relevant, default=str)[:300]}")
