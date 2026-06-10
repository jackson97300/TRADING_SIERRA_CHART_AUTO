"""flatten_bot3_sim1.py — Flatten urgent positions Bot 3 sur Sim1.

Suit sequence anti-orphelin V2 (orphan-prevention.md) :
  1. Query Type 300 OPEN_ORDERS pour chaque symbole + cancel via Type 203
  2. Query Type 305 position + MARKET CLOSE Type 208 si qty != 0
  3. Type 209 SUBMIT_FLATTEN_POSITION_ORDER par symbole avec ClientOrderID
  4. Verify qty_final == 0

Compte : Sim1 (Bot 3 MP dedie)
Symboles : ES, NQ, MGC
"""
import json
import socket
import time
import uuid

TRADE_ACCOUNT = "Sim1"
SYMBOLS = {
    "ES": "ESM26-CME",
    "NQ": "NQM26-CME",
    "MGC": "MGCM26-CME",
}

s = socket.socket()
s.settimeout(10)
s.connect(("127.0.0.1", 11099))


def send(m):
    s.sendall(json.dumps(m).encode() + b"\x00")


def recv(t=2):
    msgs, buf, end = [], b"", time.time() + t
    while time.time() < end:
        s.settimeout(max(0.1, end - time.time()))
        try:
            c = s.recv(65536)
            if not c:
                break
            buf += c
            while b"\x00" in buf:
                idx = buf.find(b"\x00")
                raw = buf[:idx]
                buf = buf[idx + 1:]
                if raw:
                    try:
                        msgs.append(json.loads(raw.decode("utf-8", "ignore")))
                    except json.JSONDecodeError:
                        pass
        except socket.timeout:
            break
    return msgs


# 1. Logon
send({"Type": 1, "ProtocolVersion": 8, "HeartbeatIntervalInSeconds": 10, "ClientName": "FLAT_BOT3"})
time.sleep(1)
recv(2)
print(f"\n=== FLATTEN BOT 3 ({TRADE_ACCOUNT}) ===\n")

# 2. Pour chaque symbole : cancel working orders + flatten position
for sym, contract in SYMBOLS.items():
    print(f"--- {sym} ({contract}) ---")

    # 2a. Query open orders Type 300 → cancel via Type 203
    send({"Type": 300, "RequestID": 100 + hash(sym) % 100, "TradeAccount": TRADE_ACCOUNT})
    time.sleep(1)
    working = []
    for m in recv(2):
        if m.get("Type") == 301:
            sym_msg = str(m.get("Symbol", ""))
            status = m.get("OrderStatus")
            if sym in sym_msg and status in (2, 4):  # Open or Working
                working.append({
                    "client_order_id": m.get("ClientOrderID"),
                    "server_order_id": m.get("ServerOrderID"),
                    "status": status,
                })
    print(f"  Working orders: {len(working)}")
    for w in working:
        cancel_cid = f"FLAT_CANCEL_{uuid.uuid4().hex[:6]}"
        send({
            "Type": 203,
            "ClientOrderID": w["client_order_id"],
            "ServerOrderID": w["server_order_id"],
            "TradeAccount": TRADE_ACCOUNT,
        })
        print(f"    cancel cid={w['client_order_id']} sid={w['server_order_id']}")
    time.sleep(1)

    # 2b. Query position Type 305 → flatten si qty != 0
    send({"Type": 305, "RequestID": 200 + hash(sym) % 100, "TradeAccount": TRADE_ACCOUNT})
    time.sleep(1)
    qty = 0
    for m in recv(2):
        if m.get("Type") == 306 and sym in str(m.get("Symbol", "")):
            qty = m.get("Quantity", 0)
    print(f"  Position {sym}: qty={qty}")

    if qty != 0:
        side = 1 if qty < 0 else 2  # SHORT→BUY, LONG→SELL
        abs_qty = abs(qty)
        flat_id = f"FLAT_BOT3_{sym}_{uuid.uuid4().hex[:6]}"
        print(f"  Sending {'BUY' if side == 1 else 'SELL'} MARKET {abs_qty} {contract}")
        send({
            "Type": 208,
            "Symbol": contract,
            "ClientOrderID": flat_id,
            "OrderType": 1,
            "BuySell": side,
            "Quantity": abs_qty,
            "TradeAccount": TRADE_ACCOUNT,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,
            "TimeInForce": 0,
        })
        time.sleep(2)
        for m in recv(3):
            if m.get("Type") == 301 and m.get("ClientOrderID") == flat_id:
                status = m.get("OrderStatus")
                fill_p = m.get("AverageFillPrice") or m.get("LastFillPrice")
                print(f"  Flat order: status={status} fill={fill_p}")

    # 2c. Type 209 SUBMIT_FLATTEN_POSITION_ORDER avec ClientOrderID (defense profondeur)
    flush_cid = f"FLAT_BOT3_FLUSH_{sym}_{int(time.time()) % 100000}"
    send({
        "Type": 209,
        "ClientOrderID": flush_cid,
        "Symbol": contract,
        "TradeAccount": TRADE_ACCOUNT,
        "Exchange": "CME",
        "IsAutomatedOrder": 1,
    })
    time.sleep(1)

    # 2d. Verify qty_final == 0
    send({"Type": 305, "RequestID": 300 + hash(sym) % 100, "TradeAccount": TRADE_ACCOUNT})
    time.sleep(1)
    final_qty = 0
    for m in recv(2):
        if m.get("Type") == 306 and sym in str(m.get("Symbol", "")):
            final_qty = m.get("Quantity", 0)
    status_str = "OK FLAT" if final_qty == 0 else f"FAIL qty={final_qty}"
    print(f"  Final {sym}: {status_str}\n")

# 3. Type 210 FLATTEN_POSITIONS_FOR_TRADE_ACCOUNT (nuclear option, defense en plus)
acct_cid = f"FLAT_BOT3_ACCT_{int(time.time()) % 100000}"
send({
    "Type": 210,
    "ClientOrderID": acct_cid,
    "TradeAccount": TRADE_ACCOUNT,
    "IsAutomatedOrder": 1,
})
time.sleep(2)
print(f"=== Type 210 sent (TradeAccount flush Sim1) ===\n")

s.close()
print("DONE.")
