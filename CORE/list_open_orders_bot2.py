"""list_open_orders_bot2.py — Liste tous les ordres ouverts Sim2."""
import socket, json, time

s = socket.socket()
s.settimeout(10)
s.connect(("127.0.0.1", 11099))


def send(m):
    s.sendall(json.dumps(m).encode() + b"\x00")


def recv(t=3):
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


send({"Type": 1, "ProtocolVersion": 8, "HeartbeatIntervalInSeconds": 10,
      "ClientName": "LIST_ORDERS_SIM2"})
time.sleep(1)
recv(2)

# Request all open orders for Sim2
send({"Type": 300, "RequestID": 1, "RequestAllOrders": 1, "TradeAccount": "Sim2"})
time.sleep(2)
print("=" * 70)
print("  Sim2 OPEN ORDERS")
print("=" * 70)
for m in recv(3):
    if m.get("Type") == 301:
        cid = m.get("ClientOrderID", "")
        sid = m.get("ServerOrderID", "")
        sym = m.get("Symbol", "")
        qty = m.get("OrderQuantity")
        status = m.get("OrderStatus", 0)
        price = m.get("Price1")
        bs = m.get("BuySell", 0)
        typ = m.get("OrderType", 0)
        if cid or sym:
            print(f"  CID={cid:<22s} SID={sid:<15s} {sym:>10s} qty={qty} "
                  f"BS={bs} type={typ} price={price} status={status}")
s.close()
print("=" * 70)
print("  Done")
