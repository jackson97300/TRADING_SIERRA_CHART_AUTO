"""
Cleanup DATA/PAPER_TRADES/*_trades.jsonl (source dashboard stats).

Different de cleanup_phantom_trades.py qui traite LOGS/trading/ (audit log).
Ce script traite les FICHIERS LUS PAR LE DASHBOARD :
  DATA/PAPER_TRADES/20260425_trades.jsonl       (Bot 1 NQ 25/04)
  DATA/PAPER_TRADES/20260511_trades.jsonl       (Bot 1 ES 10/05)
  DATA/PAPER_TRADES/20260511_v6_trades.jsonl    (Bot 2 V6 ES 10/05)

Trade IDs identifies via grep :
  Bot 1 25/04 : 20260425_1, 20260425_2 (entry 27020.25 x 2 = bug freeze)
  Bot 1 10/05 : 20260511_1, 20260511_2, 20260511_3 (ES pollue Gold)
  Bot 2 V6 10/05 : tous trades du fichier (1 seul = fantome partage)

Actions :
  1. Backup en .bak_pre_cleanup
  2. Ajouter "invalidated": true + "invalidation_reason" + "invalidation_ts"
  3. Zero pnl_ticks, pnl_usd (defense en profondeur)
  4. Garder le trade dans le fichier pour audit, mais ignore par paper_tracker

Le dashboard paper_tracker.py sera patche pour filter `invalidated=true`.
"""
from __future__ import annotations
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

IS_VPS = Path("C:/TRADING_SIERRA_CHART_AUTO").exists()
ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO") if IS_VPS else Path("D:/TRADING_SIERRA_CHART_AUTO")
PAPER_TRADES_DIR = ROOT / "DATA" / "PAPER_TRADES"

NOW_UTC = datetime.now(timezone.utc).isoformat(timespec="seconds")

# Fichiers + trade_ids cibles + raison
TARGETS = [
    ("20260425_trades.jsonl", ["20260425_1", "20260425_2"],
     "NQ_PRICE_FREEZE_25_04 : entry 27020.25 identique sur 2 trades, exit +1678t = cache/source data bug"),
    ("20260511_trades.jsonl", ["20260511_1", "20260511_2", "20260511_3"],
     "DMP_GOLD_POLLUTION 10/05 : exit prices Gold (4697) sur trades ES, bug DMP C++ binary ES/NQ + chart MGC ajoute 09/05"),
    ("20260511_v6_trades.jsonl", None,  # None = tous les trades du fichier
     "DMP_GOLD_POLLUTION 10/05 : Bot 2 V6 partage signal_id Bot 1, meme fantome ES"),
]


def cleanup_file(jsonl_path: Path, target_trade_ids: list[str] | None, reason: str) -> dict:
    """Cleanup 1 fichier PAPER_TRADES.

    Args:
        jsonl_path : path
        target_trade_ids : liste des trade_id a invalider, OU None pour tous
        reason : raison invalidation

    Returns:
        stats dict.
    """
    if not jsonl_path.exists():
        return {"error": f"Not found: {jsonl_path}"}

    backup = jsonl_path.with_suffix(".jsonl.bak_pre_cleanup")
    if not backup.exists():
        shutil.copy2(jsonl_path, backup)
        print(f"  [BACKUP] {backup.name}")

    with open(jsonl_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    n_modified = 0
    n_total = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue
        try:
            trade = json.loads(stripped)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        n_total += 1
        tid = trade.get("trade_id", "")

        # Match condition
        if target_trade_ids is None or tid in target_trade_ids:
            # Mark invalidated
            original_pnl_ticks = trade.get("pnl_ticks")
            original_pnl_usd = trade.get("pnl_usd")
            trade["invalidated"] = True
            trade["invalidation_reason"] = reason
            trade["invalidation_ts"] = NOW_UTC
            if original_pnl_ticks is not None:
                trade["original_pnl_ticks"] = original_pnl_ticks
                trade["pnl_ticks"] = 0.0
            if original_pnl_usd is not None:
                trade["original_pnl_usd"] = original_pnl_usd
                trade["pnl_usd"] = 0.0
            new_lines.append(json.dumps(trade) + "\n")
            n_modified += 1
        else:
            new_lines.append(line)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return {"lines_total": n_total, "lines_modified": n_modified}


def main():
    print(f"=== Cleanup PAPER_TRADES phantom trades ===")
    print(f"NOW_UTC : {NOW_UTC}")
    print(f"PAPER_TRADES_DIR : {PAPER_TRADES_DIR}")
    print()

    for filename, trade_ids, reason in TARGETS:
        path = PAPER_TRADES_DIR / filename
        print(f"=== {filename} ===")
        print(f"  target trade_ids : {trade_ids if trade_ids else 'ALL'}")
        print(f"  reason : {reason[:80]}...")
        result = cleanup_file(path, trade_ids, reason)
        print(f"  result : {result}")
        print()

    print("=== Done ===")
    print("Patch paper_tracker.py necessaire pour filter `invalidated=true`")
    print("Apres : restart MIA-Dashboard ou attendre poll ~30s")


if __name__ == "__main__":
    main()
