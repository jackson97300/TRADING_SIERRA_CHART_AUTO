"""Debrief journee 12/05/2026 par bot."""
import json
from collections import Counter, defaultdict
from pathlib import Path

logs = Path(r"C:\TRADING_SIERRA_CHART_AUTO\LOGS")

# Mapping bot -> trading log file
bots = {
    "Bot 1 (paper)": logs / "trading" / "trading_20260512_paper.jsonl",
    "Bot 2 V6 (paper_v6)": logs / "trading" / "trading_20260512_paper_v6.jsonl",
    "Bot 2 V2 + Bot 3 (paper_v2)": logs / "trading" / "trading_20260512_paper_v2.jsonl",
}

print("=" * 78)
print("DEBRIEF JOURNEE 12/05/2026 — TRADING ACTIVITY")
print("=" * 78)

for bot_name, log_file in bots.items():
    print(f"\n### {bot_name}")
    if not log_file.exists():
        print(f"  Pas de log : {log_file.name}")
        continue
    trades_open = []
    trades_close = []
    by_sym_close = Counter()
    pnl_total = defaultdict(float)
    pnl_total_all = 0.0
    n_open = Counter()
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                evt = json.loads(line)
            except Exception:
                continue
            code = evt.get("code", "")
            ctx = evt.get("ctx") or {}
            sym = ctx.get("sym", "?")
            if code == "TRADE_OPEN":
                trades_open.append(evt)
                n_open[sym] += 1
            elif code.startswith("TRADE_CLOSE"):
                trades_close.append(evt)
                pnl = ctx.get("pnl")
                if pnl is not None:
                    try:
                        pnl_total[sym] += float(pnl)
                        pnl_total_all += float(pnl)
                    except (TypeError, ValueError):
                        pass
                close_type = code.replace("TRADE_CLOSE_", "")
                by_sym_close[(sym, close_type)] += 1
    print(f"  TRADE_OPEN  : {len(trades_open)} ({dict(n_open)})")
    print(f"  TRADE_CLOSE : {len(trades_close)}")
    if pnl_total_all != 0:
        print(f"  PnL ticks total : {pnl_total_all:+.1f}t")
        for sym, pnl in pnl_total.items():
            print(f"    {sym}: {pnl:+.1f}t")
    if by_sym_close:
        print(f"  Exits par type :")
        for (sym, exit_type), n in by_sym_close.most_common():
            print(f"    {sym} {exit_type}: {n}")
    if trades_open:
        print(f"  Premier trade : {trades_open[0]['ts']} {trades_open[0].get('msg_fr', '')[:80]}")
        print(f"  Dernier trade : {trades_open[-1]['ts']} {trades_open[-1].get('msg_fr', '')[:80]}")
    if trades_close:
        print(f"  Dernier close : {trades_close[-1]['ts']} {trades_close[-1].get('msg_fr', '')[:80]}")

# Decisions par bot (volume)
print("\n" + "=" * 78)
print("DECISIONS VOLUME (evaluations gates par symbole)")
print("=" * 78)
for bot_name, suffix in [("Bot 1", "paper"), ("Bot 2 V6", "paper_v6"), ("Bot 2 V2 + Bot 3", "paper_v2")]:
    log_file = logs / "decisions" / f"decisions_20260512_{suffix}.jsonl"
    if not log_file.exists():
        continue
    counts = Counter()
    by_sym = Counter()
    bot3g_counts = Counter()
    last_ts = None
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                evt = json.loads(line)
            except Exception:
                continue
            code = evt.get("code", "")
            ctx = evt.get("ctx") or {}
            counts[code] += 1
            sym = ctx.get("sym") or ctx.get("symbol")
            if sym:
                by_sym[sym] += 1
            if code.startswith("BOT3G_"):
                bot3g_counts[code] += 1
            last_ts = evt.get("ts")
    print(f"\n### {bot_name} ({suffix})")
    print(f"  Total decisions : {sum(counts.values())}")
    print(f"  Par symbole : {dict(by_sym)}")
    print(f"  Last ts : {last_ts}")
    print(f"  Top 5 codes :")
    for c, n in counts.most_common(5):
        print(f"    {c}: {n}")
    if bot3g_counts:
        print(f"  Codes BOT3G_* (Gold) :")
        for c, n in bot3g_counts.most_common():
            print(f"    {c}: {n}")

print("\n" + "=" * 78)
print("EVENTS NOTABLES (CRITIQUE / MAJEUR / ALERTE)")
print("=" * 78)
for bot_name, suffix in [("Bot 1", "paper"), ("Bot 2 V6", "paper_v6"), ("Bot 2 V2 + Bot 3", "paper_v2")]:
    log_file = logs / "events" / f"events_20260512_{suffix}.jsonl"
    if not log_file.exists():
        continue
    notable = Counter()
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                evt = json.loads(line)
            except Exception:
                continue
            lvl = evt.get("level", "")
            if lvl in ("CRITIQUE", "MAJEUR", "ALERTE"):
                notable[(lvl, evt.get("code", ""))] += 1
    if notable:
        print(f"\n### {bot_name}")
        for (lvl, code), n in notable.most_common(8):
            print(f"  [{lvl}] {code}: {n}")
