import json
fp = r"C:/TRADING_SIERRA_CHART_AUTO/DATA/LIVE_ENRICHED/NQ/20260603_NQ.jsonl"
c = 0
with open(fp, "r") as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        ts = r.get("ts_event_iso", "")
        if "14:3" in ts or "14:4" in ts or "15:0" in ts:
            print(ts, "O=", r.get("open"), "H=", r.get("high"), "L=", r.get("low"), "C=", r.get("close"))
            c += 1
            if c > 30:
                break
