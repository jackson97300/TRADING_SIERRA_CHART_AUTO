"""Backtest empirique RangeGate sur trades historiques (R1 code-reviewer 30/04 v3).

Reproduit le RangeGate sur les `dmp_bar_at_exit` des trades fermes recents
pour mesurer :
  - Rejection rate : % trades qui auraient ete bloques par le gate
  - PnL bloque : sum PnL des trades qui auraient ete skipes
  - Repartition skip_reason (BREAKOUT_VA vs CONFLUENCE_2of4 vs autres)

Verdict GO si :
  - rejection_rate < 30%
  - sum_PnL_bloque <= 0 (gate bloque des trades perdants en majorite)

Usage VPS :
  python -X utf8 CORE/research/backtest_range_gate.py
"""
from __future__ import annotations

import json
import os
import sys
from glob import glob
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from CORE.range_gate import evaluate_range_gate  # noqa: E402


def replay_trades(jsonl_pattern: str, label: str) -> dict:
    """Replay les trades d'un fichier JSONL et evalue RangeGate sur
    `dmp_bar_at_entry` ou fallback `dmp_bar_at_exit`."""
    files = sorted(glob(jsonl_pattern))
    if not files:
        print(f"[{label}] AUCUN fichier trouve : {jsonl_pattern}")
        return {}

    total = 0
    blocked = 0
    pnl_blocked_ticks = 0.0
    pnl_blocked_usd = 0.0
    pnl_passed_ticks = 0.0
    pnl_passed_usd = 0.0
    skip_reasons = {}
    blocked_trades = []

    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Bar features : prefere entry, fallback exit (Bot 2 schema)
                bar = rec.get("dmp_bar_at_entry") or rec.get("dmp_bar_at_exit") or {}
                if not bar:
                    continue
                direction = rec.get("direction", "")
                if direction == "LONG":
                    rg_dir = "BUY"
                elif direction == "SHORT":
                    rg_dir = "SELL"
                else:
                    continue
                symbol = rec.get("symbol", "ES")
                pnl_t = rec.get("pnl_ticks", 0.0)
                pnl_usd = rec.get("pnl_usd", 0.0)

                # Test en mode skip pour mesurer impact reel sur trades historiques
                rg = evaluate_range_gate(
                    bar, rg_dir, symbol,
                    enabled=True, min_confluence=2, mode="skip",
                )
                total += 1
                if rg.skip:
                    blocked += 1
                    pnl_blocked_ticks += pnl_t
                    pnl_blocked_usd += pnl_usd
                    skip_reasons[rg.skip_reason.split("(")[0].strip()] = \
                        skip_reasons.get(rg.skip_reason.split("(")[0].strip(), 0) + 1
                    blocked_trades.append({
                        "trade_id": rec.get("trade_id"),
                        "sym": symbol,
                        "dir": direction,
                        "entry": rec.get("entry_price"),
                        "outcome": rec.get("outcome"),
                        "pnl_t": pnl_t,
                        "pnl_usd": pnl_usd,
                        "skip_reason": rg.skip_reason,
                    })
                else:
                    pnl_passed_ticks += pnl_t
                    pnl_passed_usd += pnl_usd

    if total == 0:
        return {"label": label, "total": 0}

    return {
        "label": label,
        "total": total,
        "blocked": blocked,
        "rejection_rate_pct": round(100.0 * blocked / total, 1),
        "pnl_blocked_ticks": pnl_blocked_ticks,
        "pnl_blocked_usd": pnl_blocked_usd,
        "pnl_passed_ticks": pnl_passed_ticks,
        "pnl_passed_usd": pnl_passed_usd,
        "skip_reasons": skip_reasons,
        "blocked_trades": blocked_trades,
    }


def print_report(stats: dict):
    if not stats or stats.get("total", 0) == 0:
        print(f"[{stats.get('label', '?')}] aucun trade replay")
        return
    label = stats["label"]
    total = stats["total"]
    blocked = stats["blocked"]
    print(f"\n{'='*60}")
    print(f"BACKTEST RangeGate — {label}")
    print(f"{'='*60}")
    print(f"Trades total       : {total}")
    print(f"Trades bloques     : {blocked} ({stats['rejection_rate_pct']}%)")
    print(f"Trades passes      : {total - blocked}")
    print(f"PnL bloque         : {stats['pnl_blocked_ticks']:+.0f}t / {stats['pnl_blocked_usd']:+.2f} USD")
    print(f"PnL passe          : {stats['pnl_passed_ticks']:+.0f}t / {stats['pnl_passed_usd']:+.2f} USD")
    if stats.get("skip_reasons"):
        print(f"Skip reasons       :")
        for r, c in sorted(stats["skip_reasons"].items(), key=lambda x: -x[1]):
            print(f"  - {r}: {c}")
    if stats.get("blocked_trades"):
        print(f"\nTrades bloques (detail) :")
        for t in stats["blocked_trades"]:
            print(f"  - #{t['trade_id']} {t['sym']} {t['dir']} @ {t['entry']} "
                  f"-> {t['outcome']} {t['pnl_t']:+.0f}t ({t['pnl_usd']:+.2f}$) "
                  f"| {t['skip_reason']}")

    # Verdict
    gate_ok = stats['rejection_rate_pct'] < 30.0 and stats['pnl_blocked_usd'] <= 0
    if gate_ok:
        print(f"\n✅ VERDICT GO : rejection {stats['rejection_rate_pct']}% < 30% "
              f"+ PnL bloque {stats['pnl_blocked_usd']:+.2f}$ <= 0")
    else:
        print(f"\n⚠️  VERDICT REVIEW : rejection {stats['rejection_rate_pct']}% "
              f"+ PnL bloque {stats['pnl_blocked_usd']:+.2f}$")


if __name__ == "__main__":
    # Bot 2 (Databento Sim2)
    bot2 = replay_trades(
        str(ROOT / "DATA" / "PAPER_TRADES" / "*_databento_trades.jsonl"),
        "Bot 2 DataBento (Sim2)",
    )
    print_report(bot2)

    # Bot 1 (mia_paper Sim3)
    bot1 = replay_trades(
        str(ROOT / "DATA" / "PAPER_TRADES" / "20*_trades.jsonl"),  # exclu databento
        "Bot 1 mia_paper (Sim3)",
    )
    # Filter Bot 1 : exclure les fichiers databento
    print_report(bot1)
