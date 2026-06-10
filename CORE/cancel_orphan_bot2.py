"""cancel_orphan_bot2.py — Cancel manuel d'un ordre orphelin Bot 2 (Sim2).

Usage : python -X utf8 CORE/cancel_orphan_bot2.py <CLIENT_ORDER_ID>
        ou avec defaut MIA_TP_994ab3e (NQ TP orphelin trade #15 19:08 UTC)

Strategie :
  1. Logon DTC port 11099
  2. Demande la liste des ordres ouverts (Type 300 OPEN_ORDERS_REQUEST)
  3. Trouve le ClientOrderID match → recupere ServerOrderID
  4. Envoie cancel avec ClientOrderID + ServerOrderID + TradeAccount=Sim2
  5. Verifie statut

CRITIQUE : sans ServerOrderID, SC ignore silencieusement le cancel.
"""
import socket
import json
import time
import sys

HOST = "127.0.0.1"
PORT = 11099
TRADE_ACCOUNT = "Sim2"


def main():
    target_cid = sys.argv[1] if len(sys.argv) > 1 else "MIA_TP_994ab3e"
    print(f"=" * 70)
    print(f"  CANCEL ORPHAN BOT 2 (Sim2) — target CID = {target_cid}")
    print(f"=" * 70)

    s = socket.socket()
    s.settimeout(10)
    try:
        s.connect((HOST, PORT))
    except Exception as e:
        print(f"FATAL connect : {e}")
        sys.exit(1)

    def send(msg):
        s.sendall(json.dumps(msg).encode("utf-8") + b"\x00")

    def recv_all(timeout=3):
        msgs = []
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            s.settimeout(max(0.1, end - time.time()))
            try:
                chunk = s.recv(16384)
                if not chunk:
                    break
                buf += chunk
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
    print("\n[1] Logon...")
    send({
        "Type": 1,
        "ProtocolVersion": 8,
        "HeartbeatIntervalInSeconds": 10,
        "ClientName": "CANCEL_ORPHAN_BOT2",
    })
    time.sleep(1)
    msgs = recv_all(2)
    logon_ok = False
    for m in msgs:
        if m.get("Type") == 2:
            print(f"  Logon : Result={m.get('Result')} Text={m.get('ResultText','')[:80]}")
            if m.get("Result") == 1:
                logon_ok = True
    if not logon_ok:
        print("FATAL : logon failed")
        sys.exit(2)

    # 2. Request open orders
    print("\n[2] Request open orders (Type 300)...")
    send({
        "Type": 300,  # OPEN_ORDERS_REQUEST
        "RequestID": 1,
        "RequestAllOrders": 1,
        "TradeAccount": TRADE_ACCOUNT,
    })
    time.sleep(2)
    msgs = recv_all(3)
    server_id_found = None
    matching_order = None
    n_orders_seen = 0
    for m in msgs:
        if m.get("Type") == 301:  # ORDER_UPDATE
            n_orders_seen += 1
            cid = m.get("ClientOrderID", "")
            sid = m.get("ServerOrderID", "")
            sym = m.get("Symbol", "")
            qty = m.get("OrderQuantity", 0)
            status = m.get("OrderStatus", 0)
            buy_sell = m.get("BuySell", 0)
            order_type = m.get("OrderType", 0)
            price1 = m.get("Price1", 0)
            print(f"  Order : CID={cid:<20s} SID={sid:<15s} {sym} qty={qty} "
                  f"BS={buy_sell} type={order_type} price1={price1} status={status}")
            if cid == target_cid:
                server_id_found = sid
                matching_order = m
    print(f"\n  Total orders received : {n_orders_seen}")

    if matching_order is None:
        print(f"\n  WARN : ClientOrderID '{target_cid}' NOT FOUND in open orders.")
        print(f"  Possible : order deja cancelle, ou nom CID different")
        # Try fallback : send cancel without SID
        print(f"\n[FALLBACK] Send cancel without SID (best effort)...")
        send({
            "Type": 203,
            "ClientOrderID": target_cid,
            "TradeAccount": TRADE_ACCOUNT,
        })
        time.sleep(1)
        for m in recv_all(2):
            print(f"  Response: {m}")
        s.close()
        sys.exit(3)

    # 3. Send cancel with SID
    print(f"\n[3] Send cancel : CID={target_cid} SID={server_id_found}")
    cancel_msg = {
        "Type": 203,  # CANCEL_ORDER
        "ClientOrderID": target_cid,
        "TradeAccount": TRADE_ACCOUNT,
    }
    if server_id_found:
        cancel_msg["ServerOrderID"] = server_id_found
    send(cancel_msg)
    time.sleep(1)
    # Send 2x for safety (comme dtc_connector)
    send(cancel_msg)
    time.sleep(2)

    print(f"\n[4] Verify cancel result...")
    for m in recv_all(3):
        if m.get("Type") == 301:
            cid = m.get("ClientOrderID", "")
            status = m.get("OrderStatus", 0)
            text = m.get("InfoText", "")
            if cid == target_cid:
                print(f"  RESULT : CID={cid} status={status} text={text}")

    s.close()
    print(f"\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
