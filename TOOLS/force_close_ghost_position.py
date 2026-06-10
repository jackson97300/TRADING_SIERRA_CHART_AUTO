"""Force close ghost position dashboard (10/06/2026).

Append un event TRADE_CLOSE synthetique dans LOGS/bot3_v3/bot3_v3_v1_YYYYMMDD.jsonl
pour le signal_id BOT3_V3_NQ_20260610_0004 (position fantome cause par cascade
rejection TP+SL 07:05:50 suite au bug Price1 manquant ladder promotion).

Position fermee cote SC manuellement par Jackson, mais dashboard lit l'absence
de TRADE_CLOSE matching dans le JSONL events.

Usage VPS :
  python -X utf8 C:\\TRADING_SIERRA_CHART_AUTO\\tools\\force_close_ghost_position.py
"""
import json
import time
from datetime import datetime, timezone

GHOST_SIGNAL_ID = "BOT3_V3_NQ_20260610_0004"
LOG_PATH = "C:/TRADING_SIERRA_CHART_AUTO/LOGS/bot3_v3/bot3_v3_v1_20260610.jsonl"

now_utc = datetime.now(timezone.utc)
ts_iso = now_utc.isoformat()
ts_event_ns = int(time.time() * 1e9)

# Event synthetique compatible format Bot 3 v3 logger
close_event = {
    "ts": ts_iso,
    "ts_event_ns": ts_event_ns,
    "bot": "v3",
    "event": "TRADE_CLOSE",
    "signal_id": GHOST_SIGNAL_ID,
    "symbol": "NQ",
    "side": "LONG",
    "level": "MQ_HVL",
    "exit_price": 28965.75,           # Approximation SL price (sortie manuelle SC)
    "exit_cause": "EXTERNAL_CLEANUP_PRICE1_FIX_10_06",
    "pnl_R": 0.0,                      # Neutralise
    "pnl_usd": 0.0,                    # Neutralise (position cleared SC manuel)
    "duration_bars": 25,
    "parent_cid": "MIA_P_e3b5c355",
    "tp_cid": "MIA_TP_caa17ef0",
    "sl_cid": "MIA_SL_8c7e82dc",
    "trade_account": "Sim1",
    "ctx": {
        "reason": "Position fantome dashboard - bug Price1 cascade rejection 07:05:50 UTC",
        "ghost_cleanup": True,
        "fix_ref": "BOT_CHANGELOG entry 2026-06-10 revert Price1",
    },
}

# Append au JSONL
with open(LOG_PATH, "a", encoding="utf-8") as f:
    f.write(json.dumps(close_event) + "\n")

print(f"[OK] Event TRADE_CLOSE synthetique appendu pour signal_id={GHOST_SIGNAL_ID}")
print(f"     File: {LOG_PATH}")
print(f"     Exit cause: EXTERNAL_CLEANUP_PRICE1_FIX_10_06")
print(f"     pnl_usd=0 (neutralise pour pas polluer stats)")
print("")
print("Dashboard prochaine refresh devrait NE PLUS afficher la position en cours.")
