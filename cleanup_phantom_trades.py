"""
Cleanup phantom trades — Option A (annotation soft) + B (zero PnL hard).

Identifie 5 trades fantomes dans les logs trading + applique :
  A. Ajoute champ "invalidated": true + "invalidation_reason" + "invalidation_ts"
  B. Met le pnl a 0 sur TRADE_CLOSE_* + change code en TRADE_CANCELLED_PHANTOM
  + Append ligne TRADE_INVALIDATED audit trail apres TRADE_CLOSE
  + Backup original .bak avant modif

Trades concernes :
  25/04 Bot 1 NQ :
    - ef8d2cc1 : LONG @ 27020.25 -> TP +1678t = +$2517 (entry+exit identiques 2x = bug)
    - 92ece0ec : LONG @ 27020.25 -> TP +1678t = +$2517 (idem)
  10/05 Bot 1 ES :
    - d3869d0c : SHORT @ 7396 -> TP @ 4697.3 (= prix Gold) = +$40,481 (bug DMP Gold)
    - 5d917fcf : SHORT @ 4701.2 (= prix Gold) -> SL @ 7405 = -$40,557 (bug DMP Gold inverse)
  10/05 Bot 2 V6 ES :
    - d3869d0c : meme trade que Bot 1 cote V6 = +$40,481

Usage : python -X utf8 cleanup_phantom_trades.py
"""
from __future__ import annotations
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

IS_VPS = Path("C:/TRADING_SIERRA_CHART_AUTO").exists()
ROOT = Path("C:/TRADING_SIERRA_CHART_AUTO") if IS_VPS else Path("D:/TRADING_SIERRA_CHART_AUTO")
LOGS_TRADING = ROOT / "LOGS" / "trading"

# Trades fantomes a invalider
PHANTOM_TRADES = [
    # (jsonl filename, signal_id, reason)
    ("trading_20260425_paper.jsonl", "ef8d2cc1",
     "NQ_PRICE_FREEZE_25_04 : entry 27020.25 et exit +1678t identiques sur 2 trades successifs - bug cache/source data"),
    ("trading_20260425_paper.jsonl", "92ece0ec",
     "NQ_PRICE_FREEZE_25_04 : idem ef8d2cc1 - meme entry/exit exact = bug"),
    ("trading_20260510_paper.jsonl", "d3869d0c",
     "DMP_GOLD_POLLUTION : exit price 4697.3 = prix Gold (entry ES 7396), bug DMP C++ binary ES/NQ + chart MGC ajoute 09/05"),
    ("trading_20260510_paper.jsonl", "5d917fcf",
     "DMP_GOLD_POLLUTION : entry price 4701.2 = prix Gold, bug DMP C++ inverse du fantome precedent"),
    ("trading_20260510_paper_v6.jsonl", "d3869d0c",
     "DMP_GOLD_POLLUTION : meme trade que Bot 1 cote V6 (signal_id partage)"),
]

NOW_UTC = datetime.now(timezone.utc).isoformat(timespec="seconds")


def cleanup_file(jsonl_path: Path, target_signal_ids: dict[str, str]) -> dict:
    """Cleanup 1 jsonl pour les signal_id donnes.

    Args:
        jsonl_path : path vers le fichier jsonl trading log
        target_signal_ids : {signal_id: invalidation_reason}

    Returns:
        dict de stats (lines_total, lines_modified, lines_appended, etc.)
    """
    if not jsonl_path.exists():
        return {"error": f"File not found: {jsonl_path}"}

    # Backup
    backup_path = jsonl_path.with_suffix(".jsonl.bak_pre_cleanup")
    if not backup_path.exists():
        shutil.copy2(jsonl_path, backup_path)
        print(f"  [BACKUP] {backup_path.name}")

    # Read
    with open(jsonl_path, "r", encoding="utf-8") as f:
        original_lines = f.readlines()

    new_lines = []
    n_modified = 0
    n_close_lines_per_sigid = {}  # track which close lines we modified
    invalidation_to_append = []  # TRADE_INVALIDATED audit lines

    for line in original_lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue

        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue

        sig_id = entry.get("signal_id")
        if sig_id and sig_id in target_signal_ids:
            reason = target_signal_ids[sig_id]
            code = entry.get("code", "")

            # Mark line as invalidated (Option A : annotation soft)
            entry["invalidated"] = True
            entry["invalidation_reason"] = reason
            entry["invalidation_ts"] = NOW_UTC

            # Option B : hard cleanup - zero pnl + rename code
            if code.startswith("TRADE_CLOSE"):
                ctx = entry.get("ctx", {}) or {}
                original_pnl = ctx.get("pnl")
                if original_pnl is not None:
                    entry["original_pnl"] = original_pnl
                    ctx["pnl"] = 0.0
                    entry["ctx"] = ctx
                # Rename code to TRADE_CANCELLED_PHANTOM (alias pour dashboard)
                entry["original_code"] = code
                entry["code"] = "TRADE_CANCELLED_PHANTOM"
                # Update msg_fr
                sym = ctx.get("sym", "?")
                entry["msg_fr"] = f"[INVALIDATED] Trade fantome annule : {sym} - {reason[:60]}"
                n_close_lines_per_sigid[sig_id] = n_close_lines_per_sigid.get(sig_id, 0) + 1

            elif code == "TRADE_OPEN":
                entry["original_code"] = code
                entry["code"] = "TRADE_CANCELLED_PHANTOM_OPEN"

            new_lines.append(json.dumps(entry) + "\n")
            n_modified += 1
        else:
            new_lines.append(line)

    # Append TRADE_INVALIDATED audit lines (Option A complement)
    for sig_id, reason in target_signal_ids.items():
        audit_line = {
            "ts": NOW_UTC + "Z",
            "level": "MAJEUR",
            "cat": "trading",
            "code": "TRADE_INVALIDATED",
            "msg_fr": f"Trade {sig_id} marque INVALIDATED (cleanup retroactif)",
            "host_process": "cleanup_script",
            "module": "cleanup_phantom_trades.py",
            "signal_id": sig_id,
            "ctx": {
                "signal_id": sig_id,
                "reason": reason,
                "cleanup_ts": NOW_UTC,
                "audit_trail": "voir .bak_pre_cleanup pour version originale",
            },
        }
        new_lines.append(json.dumps(audit_line) + "\n")

    # Write back
    with open(jsonl_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return {
        "lines_total": len(original_lines),
        "lines_modified": n_modified,
        "audit_lines_appended": len(target_signal_ids),
        "close_lines_per_sigid": n_close_lines_per_sigid,
    }


def main():
    print(f"=== Cleanup phantom trades ===")
    print(f"NOW_UTC : {NOW_UTC}")
    print(f"LOGS_TRADING : {LOGS_TRADING}")
    print()

    # Grouper par fichier
    by_file = {}
    for filename, sig_id, reason in PHANTOM_TRADES:
        by_file.setdefault(filename, {})[sig_id] = reason

    for filename, signal_ids in by_file.items():
        path = LOGS_TRADING / filename
        print(f"=== {filename} ===")
        print(f"  signal_ids : {list(signal_ids.keys())}")
        result = cleanup_file(path, signal_ids)
        print(f"  Result : {result}")
        print()

    print("=== Done ===")
    print("Backup files : *.bak_pre_cleanup")
    print("Dashboard cache sera refresh au prochain poll (~30s).")
    print()
    print("NOTE : si paper_tracker.py compute stats sur code == 'TRADE_CLOSE_*' ")
    print("uniquement, les fantomes (renames en TRADE_CANCELLED_PHANTOM) seront ")
    print("auto-skip. Verifier dashboard /api/dashboard apres 1 min.")


if __name__ == "__main__":
    main()
