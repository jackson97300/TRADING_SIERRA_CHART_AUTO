"""Analyse : si filtre regime avait fonctionne, aurait-il bloque les 6 trades Bot 3 aujourd'hui ?

+ Verifie que les features regime sont VIVANTES et SAINES (pas NaN/defaults).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Trades Bot 3 du 12/05 (heures depuis screenshot Jackson + investigation)
TRADES = [
    ("2026-05-12T02:50:46Z", "ES", "LONG", "TIMEOUT", "+25t"),
    ("2026-05-12T03:02:35Z", "NQ", "LONG", "SL", "+95t (bug entry_price)"),
    ("2026-05-12T04:04:29Z", "NQ", "LONG", "SL", "-56t"),
    ("2026-05-12T04:19:12Z", "ES", "LONG", "TIMEOUT", "-6t"),
    ("2026-05-12T04:53:24Z", "ES", "LONG", "SL", "-23t"),
    ("2026-05-12T06:40:57Z", "NQ", "LONG", "EN_COURS", "MFE+51t actuel -132t"),
]


def parse_ts(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


print("=" * 100)
print("ANALYSE : Le filtre regime aurait-il bloque les 6 trades Bot 3 aujourd'hui ?")
print("=" * 100)

# Charger tous les BOT3_REGIME_OBSERVE
events = []
fp = ROOT / "LOGS" / "decisions" / "decisions_20260512_paper_v2.jsonl"
with open(fp, encoding="utf-8") as f:
    for line in f:
        try:
            j = json.loads(line)
        except Exception:
            continue
        if j.get("code") == "BOT3_REGIME_OBSERVE":
            events.append(j)

print(f"\nTotal BOT3_REGIME_OBSERVE today : {len(events)}")

print(f"\n{'Trade heure':<25}{'Sym':<5}{'Dir':<6}{'Issue':<25}{'Regime au trade':<70}{'Filter bloque?'}")
print("-" * 150)

for trade_ts, sym, direction, issue, pnl in TRADES:
    target = parse_ts(trade_ts)
    # Trouver l'event regime LE PLUS PROCHE AVANT le trade (dans 60s)
    best = None
    best_dt = 99999
    for e in events:
        ctx = e.get("ctx", {})
        if ctx.get("sym") != sym:
            continue
        try:
            e_ts = parse_ts(e["ts"])
        except Exception:
            continue
        if e_ts > target:
            continue
        dt = (target - e_ts).total_seconds()
        if dt < best_dt and dt < 90:
            best_dt = dt
            best = e

    if not best:
        regime_str = "[no regime event in last 90s]"
        would_block = "?"
    else:
        ctx = best.get("ctx", {})
        mode = ctx.get("regime_mode", "?")
        favor = ctx.get("regime_favor", "?")
        vol = ctx.get("regime_vol", "?")
        actionable = ctx.get("regime_actionable", "?")
        conf = ctx.get("regime_confidence", 0)
        regime_str = f"mode={mode} favor={favor} vol={vol} act={actionable} conf={conf:.2f}"
        # Logique filter actuelle : skip si actionable=1 ET favor != NEUTRE ET favor != direction
        if actionable == 1:
            if favor == "NEUTRE":
                would_block = "NO (NEUTRE)"
            elif (direction == "LONG" and favor == "SHORT") or (direction == "SHORT" and favor == "LONG"):
                would_block = "YES (favor!=direction)"
            else:
                would_block = "NO (favor=direction)"
        else:
            would_block = "NO (actionable=0)"

    print(f"{trade_ts[11:19]+' '+pnl[:14]:<25}{sym:<5}{direction:<6}{issue:<25}{regime_str:<70}{would_block}")

# Si on ASSUME que filter etait actionable=1 sur tous (cas hypothetique apres fix V4 rebuild)
print(f"\n\n=== HYPOTHESE : si actionable=1 partout (fix V4 actif), filtrage selon regime_favor ===")
print(f"{'Trade heure':<25}{'Sym':<5}{'Dir':<6}{'Regime favor':<15}{'Decision hypothetique'}")
print("-" * 100)
for trade_ts, sym, direction, issue, pnl in TRADES:
    target = parse_ts(trade_ts)
    best = None
    best_dt = 99999
    for e in events:
        ctx = e.get("ctx", {})
        if ctx.get("sym") != sym:
            continue
        try:
            e_ts = parse_ts(e["ts"])
        except Exception:
            continue
        if e_ts > target or (target - e_ts).total_seconds() > 90:
            continue
        dt = (target - e_ts).total_seconds()
        if dt < best_dt:
            best_dt = dt
            best = e
    if not best:
        continue
    ctx = best.get("ctx", {})
    favor = ctx.get("regime_favor", "?")
    if favor == "NEUTRE":
        decision = "TAKE (regime NEUTRE = pas de bias)"
    elif favor == direction:
        decision = "TAKE (regime favor=direction)"
    else:
        decision = "BLOCK (regime favor!=direction)"
    print(f"{trade_ts[11:19]:<25}{sym:<5}{direction:<6}{favor:<15}{decision}")

# Bonus : distribution regime_favor sur la journee
print(f"\n=== Distribution regime_favor sur la journee Bot 3 NQ ===")
from collections import Counter
nq_events = [e for e in events if e.get("ctx", {}).get("sym") == "NQ"]
es_events = [e for e in events if e.get("ctx", {}).get("sym") == "ES"]
for label, evs in [("NQ", nq_events), ("ES", es_events)]:
    c = Counter([e.get("ctx", {}).get("regime_favor") for e in evs])
    print(f"  {label}: {dict(c)} (total {len(evs)})")

# Verif freshness features regime
print(f"\n=== Verification freshness features regime (last sample) ===")
if nq_events:
    last_nq = nq_events[-1]
    ctx = last_nq.get("ctx", {})
    print(f"  Last NQ regime event {last_nq.get('ts')[11:19]}")
    for k, v in ctx.items():
        print(f"    {k}: {v}")
