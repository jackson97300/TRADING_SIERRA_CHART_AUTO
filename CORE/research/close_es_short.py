"""close_es_short.py — Force close ES Sim1 SHORT 3 contracts via MARKET BUY."""
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
print(f"ES Sim1 position: {qty}")
if qty and qty != 0:
    side = 1 if qty < 0 else 2  # BUY si SHORT, SELL si LONG
    n = abs(qty)
    print(f"MARKET CLOSE: side={side} qty={n}")
    dtc._send({
        "Type": 208,
        "Symbol": "ESM26-CME",
        "ClientOrderID": f"FORCE_CLOSE_ES_{int(time.time()) % 100000}",
        "OrderType": 1,
        "BuySell": side,
        "Quantity": n,
        "TradeAccount": "Sim1",
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2,
        "TimeInForce": 0,
    })
    time.sleep(3.0)
    qty2 = dtc.request_position_blocking("ESM26-CME", trade_account="Sim1", timeout=2.0)
    print(f"ES Sim1 position apres MARKET CLOSE: {qty2}")
# Re-flush total
dtc._send({"Type": 210, "TradeAccount": "Sim1", "IsAutomatedOrder": 1})
time.sleep(1.5)
dtc._send({"Type": 209, "Symbol": "ESM26-CME", "TradeAccount": "Sim1", "Exchange": "CME", "IsAutomatedOrder": 1})
time.sleep(1.0)
dtc._send({"Type": 209, "Symbol": "NQM26-CME", "TradeAccount": "Sim1", "Exchange": "CME", "IsAutomatedOrder": 1})
time.sleep(2.0)
for s in ("ESM26-CME", "NQM26-CME"):
    q = dtc.request_position_blocking(s, trade_account="Sim1", timeout=2.0)
    print(f"FINAL {s}: qty={q}")
dtc.disconnect()
