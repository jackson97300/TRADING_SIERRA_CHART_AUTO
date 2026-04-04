"""
test_dtc_bracket.py — Test bracket TP/SL identique au V1
==========================================================

Reproduit exactement le flow V1 qui fonctionnait :
1. Envoie parent MARKET
2. ATTEND le fill avec le vrai prix (readuntil \x00)
3. Envoie TP LIMIT + SL STOP en 2 SINGLE avec OCOGroup
4. Track les ordres enfants

Usage (VPS uniquement) :
    python test_dtc_bracket.py --buy    # BUY + bracket
    python test_dtc_bracket.py --sell   # SELL + bracket

Auteur : MIA Trading System — copie du flow V1
"""

import json
import socket
import sys
import time
import uuid


HOST = "127.0.0.1"
PORT = 11099
SYMBOL = "ESM26-CME"
ACCOUNT = "Sim3"
TICK_SIZE = 0.25
SL_TICKS = 20       # 5 pts
TP_TICKS = 40       # 10 pts

# DTC Types
LOGON_REQ = 1
LOGON_RESP = 2
HEARTBEAT = 3
SINGLE_ORDER = 208
ORDER_UPDATE = 301
POSITION_UPDATE = 306

BUY = 1
SELL = 2
MARKET = 1
LIMIT = 2
STOP = 3


class DTCClient:
    """Client DTC synchrone avec buffer persistant (comme V1 asyncio)."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.buffer = b""

    def connect(self):
        self.sock.connect((HOST, PORT))

    def send(self, msg):
        data = json.dumps(msg, separators=(',', ':')).encode('utf-8') + b'\x00'
        self.sock.sendall(data)

    def recv_one(self, timeout=5):
        """Recoit exactement UN message (readuntil \\x00 comme V1)."""
        self.sock.settimeout(timeout)
        while True:
            # Verifier si on a deja un message complet dans le buffer
            idx = self.buffer.find(b'\x00')
            if idx >= 0:
                raw = self.buffer[:idx]
                self.buffer = self.buffer[idx+1:]
                if raw:
                    try:
                        return json.loads(raw.decode('utf-8', 'ignore'))
                    except json.JSONDecodeError:
                        continue
                continue

            # Lire plus de donnees
            try:
                chunk = self.sock.recv(8192)
                if not chunk:
                    return None
                self.buffer += chunk
            except socket.timeout:
                return None

    def recv_until_type(self, target_type, timeout=5, respond_heartbeat=True):
        """Recoit des messages jusqu'a trouver le type cible."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            remaining = max(0.1, end_time - time.time())
            msg = self.recv_one(timeout=remaining)
            if msg is None:
                return None
            t = msg.get("Type", 0)
            if respond_heartbeat and t == HEARTBEAT:
                self.send({"Type": HEARTBEAT})
                continue
            if t == target_type:
                return msg
        return None

    def drain(self, timeout=1):
        """Vide les messages en attente."""
        msgs = []
        end_time = time.time() + timeout
        while time.time() < end_time:
            msg = self.recv_one(timeout=0.5)
            if msg is None:
                break
            if msg.get("Type") == HEARTBEAT:
                self.send({"Type": HEARTBEAT})
            else:
                msgs.append(msg)
        return msgs

    def close(self):
        self.sock.close()


def main():
    side = BUY if "--buy" in sys.argv else SELL if "--sell" in sys.argv else None
    if side is None:
        print("Usage: python test_dtc_bracket.py --buy  ou  --sell")
        return

    side_str = "BUY" if side == BUY else "SELL"
    child_side = SELL if side == BUY else BUY

    print(f"\n{'='*60}")
    print(f"  TEST BRACKET — {side_str} {SYMBOL}")
    print(f"  SL={SL_TICKS} ticks ({SL_TICKS*TICK_SIZE} pts)")
    print(f"  TP={TP_TICKS} ticks ({TP_TICKS*TICK_SIZE} pts)")
    print(f"{'='*60}\n")

    dtc = DTCClient()

    # ── 1. Connexion + Logon ──
    print("[1] Connexion...")
    dtc.connect()
    dtc.send({
        "Type": LOGON_REQ,
        "ProtocolVersion": 8,
        "HeartbeatIntervalInSeconds": 10,
        "ClientName": "MIA_BRACKET_TEST",
    })
    resp = dtc.recv_until_type(LOGON_RESP, timeout=5)
    if not resp or resp.get("Result") != 1:
        print(f"  ECHEC logon: {resp}")
        return
    print(f"  OK — {resp.get('ResultText', '')[:60]}")

    dtc.drain(timeout=1)

    # ── 2. Verifier position flat ──
    print("\n[2] Verification position...")
    dtc.send({"Type": 305, "RequestID": 1})
    pos_msg = dtc.recv_until_type(POSITION_UPDATE, timeout=3)
    if pos_msg:
        qty = pos_msg.get("Quantity", 0)
        if qty != 0:
            print(f"  Position existante qty={qty} — FLATTEN d'abord!")
            return
    print("  OK — flat")

    # ── 3. Envoyer le parent MARKET ──
    parent_cid = f"MIA_P_{uuid.uuid4().hex[:8]}"
    print(f"\n[3] Envoi parent {side_str} MARKET...")
    print(f"  CID: {parent_cid}")

    dtc.send({
        "Type": SINGLE_ORDER,
        "Symbol": SYMBOL,
        "ClientOrderID": parent_cid,
        "OrderType": MARKET,
        "BuySell": side,
        "Quantity": 1,
        "TradeAccount": ACCOUNT,
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 1,
        "TimeInForce": 0,
    })

    # ── 4. ATTENDRE LE FILL (comme V1) ──
    print("\n[4] Attente du fill parent...")
    fill_price = 0
    for attempt in range(30):  # 30 x 0.2s = 6s max
        time.sleep(0.2)
        msg = dtc.recv_one(timeout=0.5)
        if msg is None:
            continue
        t = msg.get("Type", 0)
        if t == HEARTBEAT:
            dtc.send({"Type": HEARTBEAT})
            continue

        if t == ORDER_UPDATE:
            status = msg.get("OrderStatus", 0)
            cid = msg.get("ClientOrderID", "")
            fp = msg.get("AverageFillPrice", 0) or msg.get("LastFillPrice", 0) or msg.get("Price1", 0)
            print(f"  OrderUpdate: status={status} CID={cid} fill={fp}")
            if status in (2, 7) and fp and fp > 1000:  # 2=Filled, 7=Filled
                fill_price = fp
                print(f"  FILL @ {fill_price}")
                break

        if t == POSITION_UPDATE:
            avg = msg.get("AveragePrice", 0)
            qty = msg.get("Quantity", 0)
            if avg and avg > 1000 and qty != 0:
                fill_price = avg
                print(f"  Position opened: qty={qty} avg={avg}")
                break

    if fill_price <= 0:
        print("  ECHEC — pas de fill price!")
        print("  Flatten manuellement dans Sierra Chart.")
        dtc.close()
        return

    # ── 5. Calculer TP/SL ──
    if side == BUY:
        tp_price = fill_price + TP_TICKS * TICK_SIZE
        sl_price = fill_price - SL_TICKS * TICK_SIZE
    else:
        tp_price = fill_price - TP_TICKS * TICK_SIZE
        sl_price = fill_price + SL_TICKS * TICK_SIZE

    print(f"\n[5] Bracket:")
    print(f"  Entry:  {fill_price}")
    print(f"  TP:     {tp_price} ({TP_TICKS} ticks)")
    print(f"  SL:     {sl_price} ({SL_TICKS} ticks)")

    # ── 6. Envoyer TP + SL (2 SINGLE + OCOGroup — methode V1) ──
    oco_group = f"MIA_OCO_{uuid.uuid4().hex[:8]}"
    tp_cid = f"MIA_TP_{uuid.uuid4().hex[:8]}"
    sl_cid = f"MIA_SL_{uuid.uuid4().hex[:8]}"

    print(f"\n[6] Envoi TP + SL...")

    # TP = LIMIT
    dtc.send({
        "Type": SINGLE_ORDER,
        "Symbol": SYMBOL,
        "ClientOrderID": tp_cid,
        "OrderType": LIMIT,
        "BuySell": child_side,
        "Quantity": 1,
        "Price1": float(tp_price),
        "Price2": 0.0,
        "TimeInForce": 0,
        "TradeAccount": ACCOUNT,
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2,
        "OCOGroup1": oco_group,
    })
    print(f"  TP LIMIT @ {tp_price} — {tp_cid}")

    time.sleep(0.3)

    # SL = STOP
    dtc.send({
        "Type": SINGLE_ORDER,
        "Symbol": SYMBOL,
        "ClientOrderID": sl_cid,
        "OrderType": STOP,
        "BuySell": child_side,
        "Quantity": 1,
        "Price1": float(sl_price),
        "Price2": 0.0,
        "StopPrice": float(sl_price),
        "TimeInForce": 0,
        "TradeAccount": ACCOUNT,
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2,
        "OCOGroup1": oco_group,
    })
    print(f"  SL STOP  @ {sl_price} — {sl_cid}")
    print(f"  OCO Group: {oco_group}")

    # ── 7. Confirmations + Monitoring OCO manuel ──
    print(f"\n[7] Confirmations ordres enfants...")
    time.sleep(1)
    msgs = dtc.drain(timeout=2)

    # Track ServerOrderID pour cancel
    server_ids = {}  # cid → server_id
    for m in msgs:
        t = m.get("Type", 0)
        if t == ORDER_UPDATE:
            cid = m.get("ClientOrderID", "")
            sid = m.get("ServerOrderID", "")
            status = m.get("OrderStatus", 0)
            text = m.get("OrderStatusText", "")
            tag = ""
            if tp_cid in str(cid): tag = "[TP]"
            elif sl_cid in str(cid): tag = "[SL]"
            if cid and sid:
                server_ids[cid] = sid
            print(f"  {tag} status={status} SID={sid} {text}")

    print(f"\n[8] Monitoring OCO — attente TP ou SL fill (60s max)...")
    print(f"  TP={tp_price}  SL={sl_price}")
    print(f"  Ctrl+C pour arreter\n")

    oco_done = False
    try:
        end_time = time.time() + 60
        while time.time() < end_time:
            msg = dtc.recv_one(timeout=1)
            if msg is None:
                continue
            t = msg.get("Type", 0)
            if t == HEARTBEAT:
                dtc.send({"Type": HEARTBEAT})
                continue

            if t == ORDER_UPDATE:
                cid = msg.get("ClientOrderID", "")
                sid = msg.get("ServerOrderID", "")
                status = msg.get("OrderStatus", 0)
                fp = msg.get("AverageFillPrice", 0) or msg.get("LastFillPrice", 0)

                if cid and sid:
                    server_ids[cid] = sid

                tag = ""
                if tp_cid in str(cid): tag = "[TP]"
                elif sl_cid in str(cid): tag = "[SL]"
                print(f"  {tag} status={status} fill={fp} CID={cid}")

                # Fill detecte (status 2 ou 7) → annuler l'opposé
                is_filled = status in (2, 7) and fp and fp > 1000
                if is_filled:
                    if tp_cid in str(cid):
                        print(f"\n  TP FILLED @ {fp} → annulation SL...")
                        cancel_msg = {
                            "Type": 203,
                            "ClientOrderID": sl_cid,
                            "TradeAccount": ACCOUNT,
                        }
                        if sl_cid in server_ids:
                            cancel_msg["ServerOrderID"] = server_ids[sl_cid]
                        dtc.send(cancel_msg)
                        print(f"  Cancel SL envoye: {sl_cid}")
                        oco_done = True

                    elif sl_cid in str(cid):
                        print(f"\n  SL FILLED @ {fp} → annulation TP...")
                        cancel_msg = {
                            "Type": 203,
                            "ClientOrderID": tp_cid,
                            "TradeAccount": ACCOUNT,
                        }
                        if tp_cid in server_ids:
                            cancel_msg["ServerOrderID"] = server_ids[tp_cid]
                        dtc.send(cancel_msg)
                        print(f"  Cancel TP envoye: {tp_cid}")
                        oco_done = True

                    if oco_done:
                        # Attendre confirmation cancel
                        time.sleep(1)
                        cancel_msgs = dtc.drain(timeout=2)
                        for cm in cancel_msgs:
                            if cm.get("Type") == ORDER_UPDATE:
                                cs = cm.get("OrderStatus", 0)
                                cc = cm.get("ClientOrderID", "")
                                print(f"  Cancel confirm: status={cs} CID={cc}")
                        break

            if t == POSITION_UPDATE:
                qty = msg.get("Quantity", 0)
                avg = msg.get("AveragePrice", 0)
                print(f"  Position: qty={qty} avg={avg}")

    except KeyboardInterrupt:
        print("\n  Arret par Ctrl+C")

    # ── 9. Position finale ──
    print(f"\n[9] Position finale...")
    dtc.send({"Type": 305, "RequestID": 2})
    pos = dtc.recv_until_type(POSITION_UPDATE, timeout=3)
    if pos:
        qty = pos.get("Quantity", 0)
        avg = pos.get("AveragePrice", 0)
        print(f"  {SYMBOL}: qty={qty} avg={avg}")
        if qty != 0:
            print(f"\n  Position OUVERTE — bracket actif")
            print(f"  Verifiez dans Sierra Chart: Trade Manager (Ctrl+T)")
        else:
            if oco_done:
                print(f"\n  Position FERMEE — OCO manuel OK !")
            else:
                print(f"\n  Position fermee (TP/SL touche)")
    else:
        print("  Pas de reponse position")

    print(f"\n{'='*60}")
    print(f"  TEST TERMINE — OCO manuel {'OK' if oco_done else 'non teste (timeout)'}")
    print(f"{'='*60}\n")

    dtc.close()


if __name__ == "__main__":
    main()
