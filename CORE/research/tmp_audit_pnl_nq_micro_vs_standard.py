"""Audit forensique R3 : PnL Bot 1 NQ dashboard (calcul MICRO) vs broker reel (STANDARD).

Phase A plan sizing per-bot 02/06.

Le code Bot 3 v3 (bot3_paper_common.py:55) calcule PnL avec TICK_VALUE_USD['NQ']=0.50
(MICRO MNQ). Mais SC exec sur NQM26-CME (STANDARD, $1.25/tick). Donc tout le PnL
dashboard depuis 28/05 est divise par 2.5 vs realite broker Sim1.

Ce script :
1. Charge tous les TRADE_CLOSE Bot 3 v3 NQ depuis 28/05 (date du fix MES->ES standard)
2. Calcule PnL dashboard total + PnL broker reel (× 2.5)
3. Identifie les decisions strategiques basees sur cette data fausse
"""
from __future__ import annotations
import json
from pathlib import Path

DAYS = ["20260528", "20260529", "20260531", "20260601", "20260602"]
LOG_DIR = Path("C:/TRADING_SIERRA_CHART_AUTO/LOGS/bot3_v3")
MULTIPLIER = 2.5   # ratio standard/micro NQ ($1.25 / $0.50)


def main():
    print("=" * 80)
    print("AUDIT FORENSIQUE R3 — PnL Bot 1 NQ dashboard MICRO vs broker reel STANDARD")
    print("=" * 80)

    total_dashboard = 0.0
    trades = []
    for d in DAYS:
        fp = LOG_DIR / f"bot3_v3_v1_{d}.jsonl"
        if not fp.exists():
            print(f"  {d} : FILE MISSING")
            continue
        day_trades = 0
        day_pnl_dash = 0.0
        with open(fp, encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get("event") != "TRADE_CLOSE":
                        continue
                    pnl_dash = float(e.get("pnl_usd", 0))
                    total_dashboard += pnl_dash
                    day_pnl_dash += pnl_dash
                    day_trades += 1
                    trades.append({
                        "day": d, "ts": e.get("ts"), "side": e.get("side"),
                        "exit_cause": e.get("exit_cause"),
                        "pnl_dash": pnl_dash, "pnl_broker": pnl_dash * MULTIPLIER,
                    })
                except Exception:
                    pass
        print(f"  {d} : {day_trades} trades, PnL dashboard ${day_pnl_dash:+.2f}")

    print(f"\nTOTAL : {len(trades)} trades")
    print(f"  PnL dashboard (calcul MICRO 0.50)     : ${total_dashboard:+.2f}")
    print(f"  PnL broker reel Sim1 (STANDARD 1.25)   : ${total_dashboard * MULTIPLIER:+.2f}")
    print(f"  Difference cachee (sous-estimation)    : ${total_dashboard * MULTIPLIER - total_dashboard:+.2f}")
    print(f"  Ratio                                   : x{MULTIPLIER:.1f}")

    # Stats W/L
    wins = [t for t in trades if t["pnl_dash"] > 0.01]
    losses = [t for t in trades if t["pnl_dash"] < -0.01]
    print(f"\n  Distribution :")
    print(f"    Wins dashboard total : ${sum(t['pnl_dash'] for t in wins):+.2f} (n={len(wins)})")
    print(f"    Wins broker reel     : ${sum(t['pnl_broker'] for t in wins):+.2f}")
    print(f"    Losses dashboard     : ${sum(t['pnl_dash'] for t in losses):+.2f} (n={len(losses)})")
    print(f"    Losses broker reel   : ${sum(t['pnl_broker'] for t in losses):+.2f}")

    # Worst loss et best win
    if wins:
        best = max(wins, key=lambda t: t["pnl_dash"])
        print(f"\n  Best WIN dashboard : ${best['pnl_dash']:+.2f} -> broker reel ${best['pnl_broker']:+.2f} ({best['day']})")
    if losses:
        worst = min(losses, key=lambda t: t["pnl_dash"])
        print(f"  Worst LOSS dashboard : ${worst['pnl_dash']:+.2f} -> broker reel ${worst['pnl_broker']:+.2f} ({worst['day']})")

    print(f"\n=== IMPACT DECISIONS ===")
    print(f"Tous les bilans jour, dashboard Discord, audits 28/05 -> 02/06")
    print(f"basees sur PnL Bot 1 NQ sont SOUS-ESTIMES x2.5 vs realite broker Sim1.")
    print(f"Sur period 5 jours : ecart ${total_dashboard * MULTIPLIER - total_dashboard:+.2f}")


if __name__ == "__main__":
    main()
