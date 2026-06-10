"""audit_positions.py — Inventaire ES/NQ sur Sim1/Sim2/Sim3."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BOT"))
from BOT.dtc_connector import DTCConnector, DTCConfig

cfg = DTCConfig(host="localhost", port=11099, heartbeat_interval_seconds=10)
dtc = DTCConnector(cfg)
dtc.connect()
for ta in ("Sim1", "Sim2", "Sim3"):
    for sym in ("ESM26-CME", "NQM26-CME"):
        q = dtc.request_position_blocking(sym, trade_account=ta, timeout=2.0)
        print(f"  {ta} {sym}: qty={q}")
dtc.disconnect()
