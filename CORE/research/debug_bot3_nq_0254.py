"""Debug trade NQ BUY 02:54:51 — incoherence dashboard vs Sierra."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

print("=== BOT3_TRADE events 02:50-03:10 UTC ===")
fp = ROOT / "LOGS" / "trading" / "trading_20260512_paper_v2.jsonl"
if fp.exists():
    with open(fp, encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            ts = j.get("ts", "")
            code = j.get("code", "")
            if "BOT3_TRADE" in code and "2026-05-12T02:5" in ts or "2026-05-12T03:0" in ts:
                print(f"{ts[11:19]} {code}")
                print(f"  ctx: {json.dumps(j.get('ctx', {}), default=str)}")
                print(f"  msg: {j.get('msg_fr', '')}")
                print()

print()
print("=== EXECUTION events NQ 02:54-03:10 UTC ===")
fp = ROOT / "LOGS" / "execution" / "execution_20260512_paper_v2.jsonl"
if fp.exists():
    with open(fp, encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            ts = j.get("ts", "")
            ctx = j.get("ctx", {})
            if ("2026-05-12T02:5" in ts or "2026-05-12T03:0" in ts) and ctx.get("sym") == "NQ":
                code = j.get("code", "")
                print(f"{ts[11:19]} {code}")
                relevant = {k: v for k, v in ctx.items() if k in (
                    "sym", "direction", "level", "tier", "entry", "sl", "tp",
                    "price", "qty", "pnl", "mfe", "mae", "reason", "tp_cid", "sl_cid"
                )}
                if relevant:
                    print(f"  {json.dumps(relevant, default=str)}")
