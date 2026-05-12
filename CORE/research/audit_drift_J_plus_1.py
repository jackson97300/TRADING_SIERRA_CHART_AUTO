"""Audit horaire automatique du fix entry_price drift (12/05 03:30 fix).

Lance ce script J+1 (13/05 matin) ou via cron horaire pour valider que :
1. BOT_ENTRY_FILL_RECORDED est emis sur chaque trade (sinon fix pas actif)
2. drift_ticks reste sous seuil (60 NQ / 16 ES / 30 MGC)
3. BOT_DRIFT_WARNING (50% seuil) emis si drift eleve - alerte precoce
4. BOT_DRIFT_REJECT (>seuil) emis si refus - investigation requise

Usage :
    python -X utf8 CORE/research/audit_drift_J_plus_1.py
    python -X utf8 CORE/research/audit_drift_J_plus_1.py --date 2026-05-13
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default = today UTC)")
    args = ap.parse_args()

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_compact = date_str.replace("-", "")

    print("=" * 78)
    print(f"  AUDIT FIX ENTRY_PRICE J+1 — {date_str}")
    print("=" * 78)

    # 1. BOT_ENTRY_FILL_RECORDED
    fp_exec = ROOT / "LOGS" / "execution" / f"execution_{date_compact}_paper_v2.jsonl"
    fp_exec_b1 = ROOT / "LOGS" / "execution" / f"execution_{date_compact}_paper.jsonl"
    fp_exec_v6 = ROOT / "LOGS" / "execution" / f"execution_{date_compact}_paper_v6.jsonl"

    bots_files = {"bot1": fp_exec_b1, "bot2_v6": fp_exec_v6, "bot3": fp_exec}

    fill_records = defaultdict(list)
    drift_warnings = defaultdict(int)
    drift_rejects = defaultdict(int)

    for bot, fp in bots_files.items():
        if not fp.exists():
            print(f"\n[{bot}] No log file: {fp.name}")
            continue
        with open(fp, encoding="utf-8") as f:
            for line in f:
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                code = j.get("code", "")
                ctx = j.get("ctx", {})
                ctx_bot = ctx.get("bot", "")
                if code == "BOT_ENTRY_FILL_RECORDED":
                    fill_records[ctx_bot or bot].append(ctx)
                elif code == "BOT_DRIFT_WARNING":
                    drift_warnings[ctx_bot or bot] += 1
                elif code == "BOT_DRIFT_REJECT":
                    drift_rejects[ctx_bot or bot] += 1

    print(f"\n=== BOT_ENTRY_FILL_RECORDED (validation fix actif) ===")
    total_fills = 0
    for bot, records in fill_records.items():
        total_fills += len(records)
        drifts = [abs(r.get("drift_ticks", 0)) for r in records]
        if drifts:
            mean_d = round(sum(drifts) / len(drifts), 1)
            max_d = round(max(drifts), 1)
            print(f"  {bot:<12} N={len(records):<4} mean_drift={mean_d}t max_drift={max_d}t")
        else:
            print(f"  {bot:<12} N=0")
    print(f"  TOTAL fills J+1 : {total_fills}")
    if total_fills == 0:
        print("  ⚠️ AUCUN BOT_ENTRY_FILL_RECORDED — fix peut-etre inactif (verifier service restart)")

    print(f"\n=== BOT_DRIFT_WARNING (50-100% seuil = alerte precoce) ===")
    if drift_warnings:
        for bot, n in drift_warnings.items():
            print(f"  {bot:<12} N={n}")
    else:
        print("  Aucun BOT_DRIFT_WARNING (drift typique < 50% seuil = normal)")

    print(f"\n=== BOT_DRIFT_REJECT (> seuil = trade refuse) ===")
    if drift_rejects:
        for bot, n in drift_rejects.items():
            print(f"  {bot:<12} N={n}  ⚠️ INVESTIGUER (V4 stale ? pipeline retard ?)")
    else:
        print("  Aucun BOT_DRIFT_REJECT — drift sous seuil tous trades")

    # 2. Sanity check : trades open vs fills
    print(f"\n=== Trades pris vs fills enregistres (coherence) ===")
    for bot, suffix in [("bot1", "paper"), ("bot2_v6", "paper_v6"), ("bot3", "paper_v2")]:
        fp_trading = ROOT / "LOGS" / "trading" / f"trading_{date_compact}_{suffix}.jsonl"
        if not fp_trading.exists():
            continue
        n_open = 0
        with open(fp_trading, encoding="utf-8") as f:
            for line in f:
                if '"TRADE_OPEN"' in line or '"BOT3_TRADE_OPEN"' in line:
                    n_open += 1
        n_fills = len(fill_records.get(bot, []))
        # bot ctx key adjustment
        if bot == "bot1":
            n_fills = len(fill_records.get("bot1_dmp", []))
        elif bot == "bot2_v6":
            n_fills = len(fill_records.get("bot2_v6", []))
        elif bot == "bot3":
            n_fills = len(fill_records.get("bot3_mp", []))
        status = "OK" if n_open == n_fills else "⚠️ MISMATCH"
        print(f"  {bot:<12} trades_open={n_open}  fills_recorded={n_fills}  {status}")

    # 3. Distribution drift par symbol
    print(f"\n=== Distribution drift par symbol (last 24h) ===")
    by_sym = defaultdict(list)
    for bot_records in fill_records.values():
        for r in bot_records:
            sym = r.get("sym", "?")
            by_sym[sym].append(abs(float(r.get("drift_ticks", 0))))
    for sym, drifts in sorted(by_sym.items()):
        if not drifts:
            continue
        drifts.sort()
        n = len(drifts)
        p50 = drifts[n // 2]
        p75 = drifts[int(n * 0.75)] if n > 1 else drifts[-1]
        p90 = drifts[int(n * 0.90)] if n > 1 else drifts[-1]
        max_d = drifts[-1]
        threshold = {"NQ": 60, "ES": 16, "MGC": 30}.get(sym, 60)
        flag = "✓" if max_d < threshold else "⚠️"
        print(f"  {sym:<5} N={n:<3} p50={p50}t p75={p75}t p90={p90}t max={max_d}t threshold={threshold}t {flag}")

    print("\n" + "=" * 78)
    print("  Verdict :")
    if total_fills > 0 and not drift_rejects:
        print("  ✅ Fix actif, aucun trade refuse drift. Bot 3 trade au prix reel.")
    elif total_fills > 0 and drift_rejects:
        print(f"  ⚠️ Fix actif MAIS {sum(drift_rejects.values())} trades refuse drift → pipeline V4 stale ?")
    elif total_fills == 0:
        print("  ❌ Fix INACTIF (aucun fill recorded). Investiguer immediatement.")
    print("=" * 78)


if __name__ == "__main__":
    main()
