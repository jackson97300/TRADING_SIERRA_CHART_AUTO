"""Check derniers logs Bot 1 (paper)."""
import json
from datetime import datetime, timezone
from pathlib import Path

logs = Path(r"C:\TRADING_SIERRA_CHART_AUTO\LOGS")
now = datetime.now(timezone.utc)
print(f"=== HEURE UTC actuelle : {now.isoformat(timespec='seconds')} ===")
print()

def load_recent(filepath, n=15):
    """Load n derniers events d'un fichier JSONL."""
    if not filepath.exists():
        return []
    events = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events[-n:]

# Last 15 events de chaque categorie pour Bot 1
for day in ("20260513", "20260512"):
    print(f"### Day {day}")
    for cat in ("events", "decisions", "trading", "execution"):
        fp = logs / cat / f"{cat}_{day}_paper.jsonl"
        if not fp.exists():
            continue
        recent = load_recent(fp, 10)
        if not recent:
            continue
        print(f"\n--- {cat} (last 10) ---")
        for evt in recent:
            ts = evt.get("ts", "")
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_min = (now - ts_dt).total_seconds() / 60
                age_str = f"il y a {age_min:.1f}min"
            except Exception:
                age_str = "?"
            code = evt.get("code", "")
            level = evt.get("level", "")
            msg = evt.get("msg_fr", "")[:130]
            print(f"  [{level}] {ts} ({age_str}) {code} : {msg}")
    print()
