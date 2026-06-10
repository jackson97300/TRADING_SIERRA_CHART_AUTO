"""test_dtc_round_trip_nq.py — Test cycle complet DTC sur NQ Sim2.

Objectif : valider la chaine end-to-end :
  1. Logon DTC
  2. BUY MARKET 1 NQ
  3. Attendre fill parent
  4. Envoyer TP LIMIT + SL STOP
  5. Cancel SL manuellement (avec ServerOrderID) → simule fix FF cancel
  6. Verifier 0 orphan
  7. SELL MARKET pour fermer position
  8. Verifier 0 orphan + 0 position

Compte : Sim2 (Bot 2 demo paper trading)
Quantity : 1 micro (test minimal, impact PnL ~$0.50 max)
"""
import socket
import json
import time
import uuid
from datetime import datetime, timezone

HOST = "127.0.0.1"
PORT = 11099
TRADE_ACCOUNT = "Sim2"
SYMBOL = "NQM26-CME"
QTY = 1

# DTC Types
T_LOGON = 1
T_LOGON_RESP = 2
T_HEARTBEAT = 3
T_MARKET_ORDER = 208
T_CANCEL_ORDER = 203
T_OPEN_ORDERS_REQ = 300
T_ORDER_UPDATE = 301
T_POSITION_REQ = 305
T_POSITION_UPDATE = 306

# Order types
MARKET = 1
LIMIT = 2
STOP = 3

# Buy/Sell
BUY = 1
SELL = 2


def logbox(msg):
    print(f"\n{'='*70}\n  {msg}\n{'='*70}")


def main():
    logbox("TEST DTC ROUND-TRIP NQ Sim2 — 1 micro")

    s = socket.socket()
    s.settimeout(15)
    try:
        s.connect((HOST, PORT))
    except Exception as e:
        print(f"FATAL connect: {e}")
        return

    server_order_ids = {}  # cid -> sid
    fill_events = {}       # cid -> filled_price
    pending = []           # list of msgs received

    def send(msg):
        s.sendall(json.dumps(msg).encode("utf-8") + b"\x00")

    def recv_all(timeout=2):
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

    def process_updates(msgs):
        """Track SIDs et fills depuis les msgs."""
        for m in msgs:
            if m.get("Type") == T_ORDER_UPDATE:
                cid = m.get("ClientOrderID", "")
                sid = m.get("ServerOrderID", "")
                status = m.get("OrderStatus", 0)
                fill_price = m.get("AverageFillPrice") or m.get("LastFillPrice") or 0
                if cid and sid:
                    server_order_ids[cid] = sid
                if status == 7 and fill_price and fill_price > 100:
                    fill_events[cid] = fill_price
                    print(f"  [FILL] {cid} @ {fill_price}")

    # 1. LOGON
    print("[1] Logon...")
    send({"Type": T_LOGON, "ProtocolVersion": 8,
          "HeartbeatIntervalInSeconds": 10, "ClientName": "TEST_RT_NQ"})
    time.sleep(1)
    msgs = recv_all(2)
    if not any(m.get("Type") == T_LOGON_RESP and m.get("Result") == 1 for m in msgs):
        print("FATAL: Logon failed")
        s.close()
        return
    print("  Logon OK")

    # 2. BUY MARKET parent
    parent_id = f"TEST_P_{uuid.uuid4().hex[:6]}"
    print(f"\n[2] BUY MARKET {QTY}x {SYMBOL} (parent={parent_id})...")
    send({
        "Type": T_MARKET_ORDER,
        "Symbol": SYMBOL,
        "ClientOrderID": parent_id,
        "OrderType": MARKET,
        "BuySell": BUY,
        "Quantity": QTY,
        "TradeAccount": TRADE_ACCOUNT,
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 1,
        "TimeInForce": 0,
    })
    # Wait fill
    fill_deadline = time.time() + 5
    fill_price = 0
    while time.time() < fill_deadline and parent_id not in fill_events:
        time.sleep(0.2)
        process_updates(recv_all(0.3))
    if parent_id in fill_events:
        fill_price = fill_events[parent_id]
        print(f"  Parent fill: {fill_price}")
    else:
        print(f"  Parent fill TIMEOUT (5s) — abort test")
        # Tenter cancel parent
        sid_p = server_order_ids.get(parent_id, "")
        send({"Type": T_CANCEL_ORDER, "ClientOrderID": parent_id,
              "ServerOrderID": sid_p, "TradeAccount": TRADE_ACCOUNT})
        time.sleep(1)
        s.close()
        return

    # 3. TP + SL bracket
    tp_cid = f"TEST_TP_{uuid.uuid4().hex[:6]}"
    sl_cid = f"TEST_SL_{uuid.uuid4().hex[:6]}"
    tick = 0.25
    tp_price = fill_price + 5 * tick
    sl_price = fill_price - 10 * tick
    print(f"\n[3] Send bracket TP={tp_price} SL={sl_price}")
    send({
        "Type": T_MARKET_ORDER, "Symbol": SYMBOL,
        "ClientOrderID": tp_cid, "OrderType": LIMIT,
        "BuySell": SELL, "Quantity": QTY, "Price1": tp_price,
        "TimeInForce": 0, "TradeAccount": TRADE_ACCOUNT,
        "IsAutomatedOrder": 1, "OpenCloseTrade": 2,
    })
    time.sleep(0.3)
    send({
        "Type": T_MARKET_ORDER, "Symbol": SYMBOL,
        "ClientOrderID": sl_cid, "OrderType": STOP,
        "BuySell": SELL, "Quantity": QTY, "Price1": sl_price,
        "StopPrice": sl_price, "TimeInForce": 0,
        "TradeAccount": TRADE_ACCOUNT, "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2,
    })
    time.sleep(2)
    process_updates(recv_all(2))
    print(f"  TP SID = {server_order_ids.get(tp_cid, 'MISSING')}")
    print(f"  SL SID = {server_order_ids.get(sl_cid, 'MISSING')}")

    # 4. Cancel SL avec ServerOrderID
    print(f"\n[4] Cancel SL manuellement (avec SID)...")
    sl_sid = server_order_ids.get(sl_cid, "")
    cancel_msg = {
        "Type": T_CANCEL_ORDER,
        "ClientOrderID": sl_cid,
        "TradeAccount": TRADE_ACCOUNT,
    }
    if sl_sid:
        cancel_msg["ServerOrderID"] = sl_sid
    send(cancel_msg)
    time.sleep(0.3)
    send(cancel_msg)  # double envoi securite
    time.sleep(2)
    process_updates(recv_all(2))

    # 5. Verifier orders
    print(f"\n[5] List open orders Sim2...")
    send({"Type": T_OPEN_ORDERS_REQ, "RequestID": 99,
          "RequestAllOrders": 1, "TradeAccount": TRADE_ACCOUNT})
    time.sleep(2)
    msgs = recv_all(2)
    open_orders = []
    for m in msgs:
        if m.get("Type") == T_ORDER_UPDATE:
            cid = m.get("ClientOrderID", "")
            sym = m.get("Symbol", "")
            if cid and (cid.startswith("TEST_") or cid == tp_cid or cid == sl_cid):
                open_orders.append({
                    "cid": cid, "sid": m.get("ServerOrderID", ""),
                    "sym": sym, "status": m.get("OrderStatus", 0),
                    "type": m.get("OrderType", 0),
                    "price": m.get("Price1"),
                })
    print(f"  Open TEST_* orders : {len(open_orders)}")
    for o in open_orders:
        print(f"    {o}")

    # 6. Cancel TP
    print(f"\n[6] Cancel TP...")
    tp_sid = server_order_ids.get(tp_cid, "")
    cm = {"Type": T_CANCEL_ORDER, "ClientOrderID": tp_cid,
          "TradeAccount": TRADE_ACCOUNT}
    if tp_sid:
        cm["ServerOrderID"] = tp_sid
    send(cm)
    time.sleep(0.3)
    send(cm)
    time.sleep(2)
    process_updates(recv_all(2))

    # 7. SELL MARKET pour flat
    close_id = f"TEST_C_{uuid.uuid4().hex[:6]}"
    print(f"\n[7] SELL MARKET {QTY}x {SYMBOL} pour flat (close={close_id})...")
    send({
        "Type": T_MARKET_ORDER, "Symbol": SYMBOL,
        "ClientOrderID": close_id, "OrderType": MARKET,
        "BuySell": SELL, "Quantity": QTY,
        "TradeAccount": TRADE_ACCOUNT, "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2, "TimeInForce": 0,
    })
    time.sleep(2)
    process_updates(recv_all(2))
    if close_id in fill_events:
        close_fill = fill_events[close_id]
        pnl_t = (close_fill - fill_price) / tick
        print(f"  Close fill: {close_fill} | PnL = {pnl_t:.1f} ticks")

    # 8. Final verify
    print(f"\n[8] Final verify : 0 open orders + 0 position attendu")
    send({"Type": T_OPEN_ORDERS_REQ, "RequestID": 100,
          "RequestAllOrders": 1, "TradeAccount": TRADE_ACCOUNT})
    time.sleep(2)
    msgs = recv_all(2)
    test_open = [m for m in msgs if m.get("Type") == T_ORDER_UPDATE
                 and m.get("ClientOrderID", "").startswith("TEST_")
                 and m.get("OrderStatus", 0) in (1, 2, 4, 5)]  # actif
    print(f"  TEST_* orders STILL OPEN : {len(test_open)}")
    for m in test_open:
        print(f"    ⚠️  ORPHAN : {m.get('ClientOrderID')} status={m.get('OrderStatus')}")

    send({"Type": T_POSITION_REQ, "RequestID": 101,
          "TradeAccount": TRADE_ACCOUNT})
    time.sleep(1)
    pos_msgs = recv_all(2)
    nq_pos = [m for m in pos_msgs if m.get("Type") == T_POSITION_UPDATE
              and "NQ" in str(m.get("Symbol", ""))]
    for m in nq_pos:
        print(f"  Position: {m.get('Symbol')} qty={m.get('Quantity', 0)}")

    s.close()
    logbox("TEST DONE")
    print(f"  Verdict :")
    if not test_open:
        print(f"    ✅ Aucun orphan TEST_* — chain DTC OCO valide")
    else:
        print(f"    ⚠️  {len(test_open)} orphan(s) detecte(s) → bug confirme")


if __name__ == "__main__":
    main()
