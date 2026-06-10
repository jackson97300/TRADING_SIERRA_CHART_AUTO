"""flatten_nq_sim2.py — Flatten urgent NQ position Sim2."""
import socket, json, time, uuid

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
            c = s.recv(16384)
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


send({"Type": 1, "ProtocolVersion": 8, "HeartbeatIntervalInSeconds": 10, "ClientName": "FLAT_NQ"})
time.sleep(1)
recv(2)

# Position request
send({"Type": 305, "RequestID": 1, "TradeAccount": "Sim2"})
time.sleep(1)
qty = 0
for m in recv(2):
    if m.get("Type") == 306 and "NQ" in str(m.get("Symbol", "")):
        qty = m.get("Quantity", 0)
        print(f"  Position NQ : qty={qty}")

if qty == 0:
    print("  Already flat")
    s.close()
    exit(0)

# Send opposite to flatten
side = 1 if qty < 0 else 2  # if SHORT (qty<0), BUY ; if LONG (qty>0), SELL
abs_qty = abs(qty)
flat_id = f"FLAT_{uuid.uuid4().hex[:6]}"
print(f"  Sending {'BUY' if side == 1 else 'SELL'} MARKET {abs_qty} NQM26-CME")
send({
    "Type": 208, "Symbol": "NQM26-CME",
    "ClientOrderID": flat_id, "OrderType": 1,
    "BuySell": side, "Quantity": abs_qty,
    "TradeAccount": "Sim2", "IsAutomatedOrder": 1,
    "OpenCloseTrade": 2, "TimeInForce": 0,
})
time.sleep(2)
for m in recv(3):
    if m.get("Type") == 301 and m.get("ClientOrderID") == flat_id:
        status = m.get("OrderStatus")
        fill_p = m.get("AverageFillPrice") or m.get("LastFillPrice")
        print(f"  Flat order : status={status} fill={fill_p}")

# Verify
send({"Type": 305, "RequestID": 2, "TradeAccount": "Sim2"})
time.sleep(1)
final_qty = 0
for m in recv(2):
    if m.get("Type") == 306 and "NQ" in str(m.get("Symbol", "")):
        final_qty = m.get("Quantity", 0)
print(f"  Final NQ qty : {final_qty}")
s.close()
print("FLATTEN DONE" if final_qty == 0 else f"⚠️ STILL {final_qty}")
