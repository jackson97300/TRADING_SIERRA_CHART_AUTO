import json
from pathlib import Path
dates = ["20260603","20260602","20260601"]
ldir = Path(r"C:/TRADING_SIERRA_CHART_AUTO/LOGS/bot3_v3")
for d in dates:
    fp = ldir / f"bot3_v3_v1_{d}.jsonl"
    if not fp.exists():
        continue
    with open(fp,"r",encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except: continue
            if r.get("event") == "TRADE_CLOSE":
                print(d, r.get("signal_id"), "side=", r.get("side"), "cause=", r.get("exit_cause"), "outcome=", r.get("outcome"), "pnl_R=", r.get("pnl_R"))
