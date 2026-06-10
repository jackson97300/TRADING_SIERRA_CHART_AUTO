"""Exhaustive log dump pour trade NQ 02:54:51 - 03:02:35."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TARGET_START = "2026-05-12T02:54:00Z"
TARGET_END = "2026-05-12T03:03:00Z"

def scan(fp: Path, label: str):
    if not fp.exists():
        print(f"NOT FOUND: {fp}")
        return
    print(f"\n=== {label} : {fp.name} ===")
    cnt = 0
    with open(fp, encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except Exception:
                continue
            ts = j.get("ts", "")
            if not (TARGET_START <= ts <= TARGET_END):
                continue
            ctx = j.get("ctx", {})
            sym = ctx.get("sym", "")
            if sym not in ("NQ", "", None) and "NQ" not in str(ctx):
                continue
            code = j.get("code", "")
            # Focus sur trail/SL/TP/ladder/MFE/BE events
            if any(k in code for k in ("LADDER", "TRAIL", "SL", "TP", "BE", "MFE", "BRACKET", "EXIT", "FILL")):
                relevant = {k: v for k, v in ctx.items() if k not in ("trace",)}
                print(f"  {ts[11:19]} {code:<40} {json.dumps(relevant, default=str)[:200]}")
                cnt += 1
    print(f"  Total events filtres : {cnt}")


for name in ["execution", "events", "decisions", "trading", "errors"]:
    fp = ROOT / "LOGS" / name / f"{name}_20260512_paper_v2.jsonl"
    scan(fp, name.upper())
