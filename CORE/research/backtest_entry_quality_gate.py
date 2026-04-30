"""Backtest empirique EntryQualityGate sur trades Bot 1 historiques.

LOT 2B (Jackson "ON APPLIQUE PAPER DIRECT").
Mesure rejection rate + PnL bloque vs passe + WR pre/post gate.
"""
from __future__ import annotations

import json
import os
import sys
from glob import glob
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from CORE.entry_quality_gate import evaluate_entry_quality_gate  # noqa: E402


def replay():
    files = sorted(glob(str(ROOT / "DATA" / "PAPER_TRADES" / "20*_trades.jsonl")))
    files = [f for f in files if "databento" not in f]  # exclu Bot 2
    if not files:
        print("Aucun trade trouve")
        return

    total = 0
    blocked = 0
    pnl_blocked = 0.0
    pnl_passed = 0.0
    tp_passed = 0
    sl_passed = 0
    skip_reasons = {}

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
                bar = rec.get("dmp_bar_at_exit") or {}
                if not bar:
                    continue
                direction = rec.get("direction", "")
                pnl_usd = rec.get("pnl_usd", 0.0)
                outcome = rec.get("outcome", "")
                rg = evaluate_entry_quality_gate(bar, direction, enabled=True)
                total += 1
                if rg.skip:
                    blocked += 1
                    pnl_blocked += pnl_usd
                    # Compte categories
                    for cond, flag in [
                        ("contra_momentum", rg.contra_momentum),
                        ("contra_cvd", rg.contra_cvd),
                        ("wall_too_close", rg.wall_too_close),
                        ("wall_too_far", rg.wall_too_far),
                    ]:
                        if flag:
                            skip_reasons[cond] = skip_reasons.get(cond, 0) + 1
                else:
                    pnl_passed += pnl_usd
                    if outcome == "TP":
                        tp_passed += 1
                    elif outcome == "SL":
                        sl_passed += 1

    if total == 0:
        print("Aucun trade avec dmp_bar_at_exit valide")
        return

    print(f"\n{'='*60}")
    print(f"BACKTEST EntryQualityGate Bot 1 historique")
    print(f"{'='*60}")
    print(f"Total trades       : {total}")
    print(f"Trades bloques     : {blocked} ({100*blocked/total:.1f}%)")
    print(f"PnL bloque (eviter): {pnl_blocked:+.2f}$")
    print(f"PnL passe (garde)  : {pnl_passed:+.2f}$")
    print(f"Trades passes      : TP={tp_passed} SL={sl_passed}")
    if (tp_passed + sl_passed) > 0:
        wr_post = 100 * tp_passed / (tp_passed + sl_passed)
        print(f"WR post-gate       : {wr_post:.1f}%")
    print(f"Skip categories    :")
    for cat, count in sorted(skip_reasons.items(), key=lambda x: -x[1]):
        print(f"  - {cat}: {count}")

    # Verdict
    if (100 * blocked / total) < 50 and pnl_blocked < 0:
        print(f"\nVERDICT GO : rejection {100*blocked/total:.1f}% < 50% + PnL bloque < 0")
    else:
        print(f"\nVERDICT REVIEW : rejection {100*blocked/total:.1f}% + PnL {pnl_blocked:+.0f}$")


if __name__ == "__main__":
    replay()
