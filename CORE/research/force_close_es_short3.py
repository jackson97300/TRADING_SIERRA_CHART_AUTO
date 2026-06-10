"""force_close_es_short3.py — MARKET BUY 3 ES Sim1 pour fermer SHORT residuel."""
from __future__ import annotations
import sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BOT"))
from BOT.dtc_connector import DTCConnector, DTCConfig

cfg = DTCConfig(host="localhost", port=11099, heartbeat_interval_seconds=10)
dtc = DTCConnector(cfg)
dtc.connect()
qty = dtc.request_position_blocking("ESM26-CME", trade_account="Sim1", timeout=2.0)
print(f"ES Sim1 position avant: {qty}")
if qty is None or qty == 0:
    print("  Pas de position SHORT a fermer")
else:
    side = 1 if qty < 0 else 2  # BUY si SHORT (qty<0), SELL si LONG
    n = abs(qty)
    cid = f"FORCE_CLOSE_{int(time.time() * 1000) % 1000000}"
    print(f"  MARKET CLOSE: side={side} qty={n} cid={cid}")
    dtc._send({
        "Type": 208,
        "Symbol": "ESM26-CME",
        "ClientOrderID": cid,
        "OrderType": 1,            # MARKET
        "BuySell": side,
        "Quantity": n,
        "TradeAccount": "Sim1",
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2,       # CLOSE
        "TimeInForce": 0,
    })
    time.sleep(3.0)
qty2 = dtc.request_position_blocking("ESM26-CME", trade_account="Sim1", timeout=2.0)
print(f"ES Sim1 position apres: {qty2}")
# Cleanup ordres residuels
cid2 = f"CLEANUP_{int(time.time() * 1000) % 1000000}"
dtc._send({"Type": 209, "ClientOrderID": cid2, "Symbol": "ESM26-CME",
           "TradeAccount": "Sim1", "Exchange": "CME", "IsAutomatedOrder": 1})
time.sleep(1.5)
qty3 = dtc.request_position_blocking("ESM26-CME", trade_account="Sim1", timeout=2.0)
print(f"ES Sim1 final apres Type 209: {qty3}")
dtc.disconnect()
