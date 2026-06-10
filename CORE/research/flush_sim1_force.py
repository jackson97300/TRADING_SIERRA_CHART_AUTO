"""flush_sim1_force.py — Force flush Sim1 via Type 210 + Type 209 ES + NQ.

Anti-orphelin systemique : envoie tous les types de flatten DTC pour s'assurer
qu'aucun ordre TP/SL/MARKET ne reste Working sur Sim1.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BOT"))

from BOT.dtc_connector import DTCConnector, DTCConfig

cfg = DTCConfig(host="localhost", port=11099, heartbeat_interval_seconds=10)
dtc = DTCConnector(cfg)
if not dtc.connect():
    print("FAIL connect")
    sys.exit(1)

print("=== AVANT FLUSH ===")
for sym in ("ESM26-CME", "NQM26-CME"):
    q = dtc.request_position_blocking(sym, trade_account="Sim1", timeout=2.0)
    print(f"  {sym}: qty={q}")

print("\n=== Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT Sim1 ===")
# BUG FIX 04/05 : ClientOrderID OBLIGATOIRE sinon SC rejette
cid_acct = f"FLUSH_ACCT_{int(time.time() * 1000) % 1000000}"
dtc._send({"Type": 210, "ClientOrderID": cid_acct, "TradeAccount": "Sim1", "IsAutomatedOrder": 1})
print(f"  CID={cid_acct}")
time.sleep(2.0)

print("=== Type 209 SUBMIT_FLATTEN_POSITION_ORDER ESM26-CME Sim1 ===")
cid_es = f"FLUSH_ES_{int(time.time() * 1000) % 1000000}"
dtc._send({"Type": 209, "ClientOrderID": cid_es, "Symbol": "ESM26-CME",
           "TradeAccount": "Sim1", "Exchange": "CME", "IsAutomatedOrder": 1})
print(f"  CID={cid_es}")
time.sleep(1.5)

print("=== Type 209 SUBMIT_FLATTEN_POSITION_ORDER NQM26-CME Sim1 ===")
cid_nq = f"FLUSH_NQ_{int(time.time() * 1000) % 1000000}"
dtc._send({"Type": 209, "ClientOrderID": cid_nq, "Symbol": "NQM26-CME",
           "TradeAccount": "Sim1", "Exchange": "CME", "IsAutomatedOrder": 1})
print(f"  CID={cid_nq}")
time.sleep(2.0)

print("\n=== APRES FLUSH ===")
for sym in ("ESM26-CME", "NQM26-CME"):
    q = dtc.request_position_blocking(sym, trade_account="Sim1", timeout=2.0)
    print(f"  {sym}: qty={q}")

dtc.disconnect()
print("\nVerifier GUI Sim1 : ordre NQ TP @ 27900.50 doit avoir disparu.")
