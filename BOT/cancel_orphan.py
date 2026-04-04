"""cancel_orphan.py — Annule un ordre orphelin par ClientOrderID."""
import socket, json, time, sys

HOST = "127.0.0.1"
PORT = 11099

def main():
    cid = sys.argv[1] if len(sys.argv) > 1 else "MIA_SL_NQ_052c75"
    print(f"Cancel ordre: {cid}")

    s = socket.socket()
    s.settimeout(10)
    s.connect((HOST, PORT))

    def send(msg):
        s.sendall(json.dumps(msg).encode('utf-8') + b'\x00')

    def recv_all(timeout=2):
        msgs = []
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            s.settimeout(max(0.1, end - time.time()))
            try:
                chunk = s.recv(8192)
                if not chunk:
                    break
                buf += chunk
                while b'\x00' in buf:
                    idx = buf.find(b'\x00')
                    raw = buf[:idx]
                    buf = buf[idx+1:]
                    if raw:
                        try:
                            msgs.append(json.loads(raw.decode('utf-8','ignore')))
                        except:
                            pass
            except socket.timeout:
                break
        return msgs

    # Logon
    send({"Type": 1, "ProtocolVersion": 8, "HeartbeatIntervalInSeconds": 10,
          "ClientName": "CANCEL_ORPHAN"})
    time.sleep(1)
    for m in recv_all(2):
        if m.get("Type") == 2:
            print(f"  Logon OK: {m.get('ResultText','')[:50]}")

    # Cancel
    send({"Type": 203, "ClientOrderID": cid, "TradeAccount": "Sim3"})
    print(f"  Cancel envoye")
    time.sleep(1)
    for m in recv_all(2):
        t = m.get("Type", 0)
        if t == 301:
            print(f"  OrderUpdate: status={m.get('OrderStatus',0)} "
                  f"CID={m.get('ClientOrderID','')} "
                  f"text={m.get('InfoText','')}")

    # Positions
    send({"Type": 305, "RequestID": 1})
    time.sleep(1)
    for m in recv_all(2):
        if m.get("Type") == 306:
            print(f"  Position: {m.get('Symbol','')} qty={m.get('Quantity',0)} "
                  f"avg={m.get('AveragePrice',0)}")

    s.close()
    print("Done")

if __name__ == "__main__":
    main()
