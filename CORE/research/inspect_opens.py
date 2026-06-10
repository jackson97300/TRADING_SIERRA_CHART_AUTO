import json
from pathlib import Path
fp = Path(r"C:/TRADING_SIERRA_CHART_AUTO/LOGS/bot3_v3/bot3_v3_v1_20260603.jsonl")
opens = []
closes = []
with open(fp,"r",encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
        except: continue
        if r.get("event") == "TRADE_OPEN":
            opens.append(r)
        elif r.get("event") == "TRADE_CLOSE":
            closes.append(r)
print("opens=", len(opens), "closes=", len(closes))
print("First 5 opens:")
for o in opens[:5]:
    print(" ", o.get("signal_id"), o.get("ts"), o.get("side"), "entry=", o.get("entry_price"), "sl_ticks=", o.get("sl_ticks"))
print("Unique signal_ids opens:", len(set(o["signal_id"] for o in opens)))
print("Unique signal_ids closes:", len(set(c["signal_id"] for c in closes)))
