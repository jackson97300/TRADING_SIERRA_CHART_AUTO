"""Check sante bots session Asia (12-13/05/2026)."""
import json
from datetime import datetime, timezone
from pathlib import Path

logs = Path(r"C:\TRADING_SIERRA_CHART_AUTO\LOGS")
now = datetime.now(timezone.utc)

print(f"=== HEURE UTC actuelle : {now.isoformat(timespec='seconds')} ===")
print()

# Vérifie heartbeats et exceptions pour chaque bot
checks = [
    ("Bot 1 (paper)", "paper"),
    ("Bot 2 V6 (paper_v6)", "paper_v6"),
    ("Bot 2 V2 + Bot 3 (paper_v2)", "paper_v2"),
]

for name, suffix in checks:
    # Try today (13) then yesterday (12)
    found_log = None
    for day in ("20260513", "20260512"):
        fp = logs / "events" / f"events_{day}_{suffix}.jsonl"
        if fp.exists():
            found_log = fp
            day_label = day
            break
    if not found_log:
        print(f"### {name} : pas de fichier event recent")
        continue
    last_hb = None
    last_exc = None
    n_hb = 0
    n_exc_5min = 0
    cutoff = now.timestamp() - 300
    with open(found_log, "r", encoding="utf-8") as f:
        for line in f:
            try:
                evt = json.loads(line)
            except Exception:
                continue
            code = evt.get("code", "")
            ts = evt.get("ts", "")
            try:
                ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts_sec = ts_dt.timestamp()
            except Exception:
                continue
            if code == "BOT_HEARTBEAT":
                last_hb = evt
                n_hb += 1
            if "EXCEPTION" in code or code.startswith("PY_"):
                last_exc = evt
                if ts_sec >= cutoff:
                    n_exc_5min += 1
    print(f"### {name} (log : {day_label})")
    print(f"  Total heartbeats : {n_hb}")
    if last_hb:
        ts_dt = datetime.fromisoformat(last_hb["ts"].replace("Z", "+00:00"))
        age_sec = (now - ts_dt).total_seconds()
        ctx = last_hb.get("ctx") or {}
        print(f"  Last heartbeat : {last_hb['ts']} (il y a {int(age_sec)}s) — last_bar_age={ctx.get('last_bar_age')}")
    print(f"  Exceptions derniers 5 min : {n_exc_5min}")
    if last_exc:
        ts_dt = datetime.fromisoformat(last_exc["ts"].replace("Z", "+00:00"))
        age_min = (now - ts_dt).total_seconds() / 60
        ctx = last_exc.get("ctx") or {}
        print(f"  Last exception : {last_exc['ts']} (il y a {age_min:.1f} min)")
        print(f"    code={last_exc.get('code')} ctx={dict((k, str(v)[:60]) for k, v in ctx.items())}")
    print()

# Bot 3 Gold MGC : compter BOT3G_* aujourd'hui + hier
print("=== Bot 3 Gold MGC — derniers BOT3G_* ===")
for day in ("20260513", "20260512"):
    fp = logs / "decisions" / f"decisions_{day}_paper_v2.jsonl"
    if not fp.exists():
        continue
    bot3g_codes = {}
    last_bot3g = None
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            try:
                evt = json.loads(line)
            except Exception:
                continue
            code = evt.get("code", "")
            if code.startswith("BOT3G_"):
                bot3g_codes[code] = bot3g_codes.get(code, 0) + 1
                last_bot3g = evt
    print(f"\n  Day {day} :")
    for c, n in bot3g_codes.items():
        print(f"    {c}: {n}")
    if last_bot3g:
        ts_dt = datetime.fromisoformat(last_bot3g["ts"].replace("Z", "+00:00"))
        age_min = (now - ts_dt).total_seconds() / 60
        print(f"  Last BOT3G_ : {last_bot3g['ts']} (il y a {age_min:.1f} min) — {last_bot3g['code']}")

# Latest trades par bot
print("\n=== Derniers trades (toutes sessions, hier+aujourd'hui) ===")
for suffix_label, suffix in [("Bot 1", "paper"), ("Bot 2 V6", "paper_v6"), ("Bot 3 MP", "paper_v2")]:
    last_trade = None
    for day in ("20260513", "20260512"):
        fp = logs / "trading" / f"trading_{day}_{suffix}.jsonl"
        if not fp.exists():
            continue
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                if evt.get("code", "").startswith("TRADE_"):
                    last_trade = evt
    if last_trade:
        ts_dt = datetime.fromisoformat(last_trade["ts"].replace("Z", "+00:00"))
        age_h = (now - ts_dt).total_seconds() / 3600
        print(f"  {suffix_label}: {last_trade['ts']} (il y a {age_h:.2f}h) — {last_trade.get('code')} — {last_trade.get('msg_fr', '')[:80]}")
    else:
        print(f"  {suffix_label}: pas de trade trouve")
