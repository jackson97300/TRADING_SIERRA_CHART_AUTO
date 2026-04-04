"""
test_dtc_dual.py — Test bracket simultane ES + NQ avec OCO manuel
==================================================================

Envoie un BUY ES + BUY NQ en meme temps, chacun avec bracket TP/SL.
Gere l'OCO manuellement : quand TP ou SL est touche, annule l'opposé.

Usage (VPS uniquement) :
    python test_dtc_dual.py --buy     # BUY ES + BUY NQ
    python test_dtc_dual.py --sell    # SELL ES + SELL NQ
    python test_dtc_dual.py --mixed   # BUY ES + SELL NQ

Auteur : MIA Trading System
"""

import json
import socket
import sys
import time
import uuid


HOST = "127.0.0.1"
PORT = 11099
ACCOUNT = "Sim3"

# Instruments
INSTRUMENTS = {
    "ES": {
        "contract": "ESM26-CME",
        "tick_size": 0.25,
        "sl_ticks": 20,   # 5 pts
        "tp_ticks": 40,   # 10 pts
    },
    "NQ": {
        "contract": "NQM26-CME",
        "tick_size": 0.25,
        "sl_ticks": 40,   # 10 pts (NQ plus volatile)
        "tp_ticks": 80,   # 20 pts
    },
}

# DTC Types
LOGON_REQ = 1
LOGON_RESP = 2
HEARTBEAT = 3
SINGLE_ORDER = 208
CANCEL_ORDER = 203
ORDER_UPDATE = 301
POSITION_UPDATE = 306

BUY = 1
SELL = 2
MARKET = 1
LIMIT = 2
STOP = 3


class DTCClient:
    """Client DTC synchrone avec buffer persistant."""

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
        """Recoit exactement UN message (readuntil \\x00)."""
        self.sock.settimeout(timeout)
        while True:
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
            try:
                chunk = self.sock.recv(8192)
                if not chunk:
                    return None
                self.buffer += chunk
            except socket.timeout:
                return None

    def recv_until_type(self, target_type, timeout=5):
        """Recoit des messages jusqu'au type cible."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            msg = self.recv_one(timeout=max(0.1, end_time - time.time()))
            if msg is None:
                return None
            t = msg.get("Type", 0)
            if t == HEARTBEAT:
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


def send_bracket(dtc, symbol, contract, side, fill_price, tick_size, sl_ticks, tp_ticks):
    """Envoie TP + SL pour un instrument. Retourne (tp_cid, sl_cid, oco_group)."""
    child_side = SELL if side == BUY else BUY

    if side == BUY:
        tp_price = fill_price + tp_ticks * tick_size
        sl_price = fill_price - sl_ticks * tick_size
    else:
        tp_price = fill_price - tp_ticks * tick_size
        sl_price = fill_price + sl_ticks * tick_size

    oco_group = f"MIA_OCO_{symbol}_{uuid.uuid4().hex[:6]}"
    tp_cid = f"MIA_TP_{symbol}_{uuid.uuid4().hex[:6]}"
    sl_cid = f"MIA_SL_{symbol}_{uuid.uuid4().hex[:6]}"

    # TP LIMIT
    dtc.send({
        "Type": SINGLE_ORDER,
        "Symbol": contract,
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

    time.sleep(0.2)

    # SL STOP
    dtc.send({
        "Type": SINGLE_ORDER,
        "Symbol": contract,
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

    print(f"  [{symbol}] TP LIMIT @ {tp_price} — {tp_cid}")
    print(f"  [{symbol}] SL STOP  @ {sl_price} — {sl_cid}")
    print(f"  [{symbol}] OCO: {oco_group}")

    return tp_cid, sl_cid, tp_price, sl_price


def main():
    # Parse arguments
    if "--buy" in sys.argv:
        sides = {"ES": BUY, "NQ": BUY}
    elif "--sell" in sys.argv:
        sides = {"ES": SELL, "NQ": SELL}
    elif "--mixed" in sys.argv:
        sides = {"ES": BUY, "NQ": SELL}
    else:
        print("Usage: python test_dtc_dual.py --buy | --sell | --mixed")
        return

    print(f"\n{'='*65}")
    print(f"  TEST DUAL BRACKET — ES + NQ simultane")
    for sym, side in sides.items():
        inst = INSTRUMENTS[sym]
        s = "BUY" if side == BUY else "SELL"
        print(f"  {sym}: {s}  SL={inst['sl_ticks']}t  TP={inst['tp_ticks']}t")
    print(f"{'='*65}\n")

    dtc = DTCClient()

    # ── 1. Connexion ──
    print("[1] Connexion DTC...")
    dtc.connect()
    dtc.send({
        "Type": LOGON_REQ,
        "ProtocolVersion": 8,
        "HeartbeatIntervalInSeconds": 10,
        "ClientName": "MIA_DUAL_TEST",
    })
    resp = dtc.recv_until_type(LOGON_RESP, timeout=5)
    if not resp or resp.get("Result") != 1:
        print(f"  ECHEC logon: {resp}")
        return
    print(f"  OK — {resp.get('ResultText', '')[:60]}")
    dtc.drain(timeout=1)

    # ── 2. Verifier flat ──
    print("\n[2] Verification positions...")
    dtc.send({"Type": 305, "RequestID": 1})
    time.sleep(1)
    msgs = dtc.drain(timeout=2)
    for m in msgs:
        if m.get("Type") == POSITION_UPDATE:
            qty = m.get("Quantity", 0)
            sym = m.get("Symbol", "")
            if qty != 0:
                print(f"  Position existante {sym} qty={qty} — FLATTEN d'abord!")
                dtc.close()
                return
    print("  OK — flat")

    # ── 3. Envoyer les 2 parents MARKET ──
    print("\n[3] Envoi parents MARKET...")
    parent_ids = {}
    for sym, side in sides.items():
        inst = INSTRUMENTS[sym]
        cid = f"MIA_P_{sym}_{uuid.uuid4().hex[:6]}"
        parent_ids[sym] = cid
        side_str = "BUY" if side == BUY else "SELL"

        dtc.send({
            "Type": SINGLE_ORDER,
            "Symbol": inst["contract"],
            "ClientOrderID": cid,
            "OrderType": MARKET,
            "BuySell": side,
            "Quantity": 1,
            "TradeAccount": ACCOUNT,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 1,
            "TimeInForce": 0,
        })
        print(f"  [{sym}] {side_str} MARKET — {cid}")
        time.sleep(0.1)

    # ── 4. Attendre les fills des 2 parents ──
    print("\n[4] Attente fills parents...")
    fill_prices = {}
    end_time = time.time() + 8

    while time.time() < end_time and len(fill_prices) < 2:
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

            # Identifier quel instrument
            for sym in ["ES", "NQ"]:
                if sym in str(cid) and cid == parent_ids.get(sym):
                    print(f"  [{sym}] OrderUpdate: status={status} fill={fp}")
                    if status in (2, 7) and fp and fp > 1000:
                        fill_prices[sym] = fp
                        print(f"  [{sym}] FILL @ {fp}")

        if t == POSITION_UPDATE:
            avg = msg.get("AveragePrice", 0)
            qty = msg.get("Quantity", 0)
            sym_pos = msg.get("Symbol", "")
            if avg and avg > 1000 and qty != 0:
                for sym, inst in INSTRUMENTS.items():
                    if inst["contract"] in sym_pos and sym not in fill_prices:
                        fill_prices[sym] = avg
                        print(f"  [{sym}] Position fill @ {avg}")

    if len(fill_prices) < 2:
        missing = [s for s in sides if s not in fill_prices]
        print(f"\n  ECHEC — pas de fill pour: {missing}")
        print(f"  Fills recus: {fill_prices}")
        print(f"  Flatten manuellement!")
        dtc.close()
        return

    # ── 5. Envoyer brackets TP/SL pour les 2 ──
    print(f"\n[5] Envoi brackets TP/SL...")

    # OCO tracking : {cid: opposite_cid}
    oco_pairs = {}
    server_ids = {}
    bracket_info = {}  # sym → {tp_cid, sl_cid, tp_price, sl_price}

    for sym, side in sides.items():
        inst = INSTRUMENTS[sym]
        tp_cid, sl_cid, tp_price, sl_price = send_bracket(
            dtc, sym, inst["contract"], side,
            fill_prices[sym], inst["tick_size"],
            inst["sl_ticks"], inst["tp_ticks"]
        )
        oco_pairs[tp_cid] = sl_cid
        oco_pairs[sl_cid] = tp_cid
        bracket_info[sym] = {
            "tp_cid": tp_cid, "sl_cid": sl_cid,
            "tp_price": tp_price, "sl_price": sl_price,
            "fill": fill_prices[sym],
        }
        time.sleep(0.3)

    # ── 6. Resume ──
    print(f"\n[6] Resume brackets:")
    for sym, info in bracket_info.items():
        side_str = "BUY" if sides[sym] == BUY else "SELL"
        print(f"  [{sym}] {side_str} @ {info['fill']:.2f}  "
              f"TP={info['tp_price']:.2f}  SL={info['sl_price']:.2f}")

    # ── 7. Confirmations ordres enfants ──
    print(f"\n[7] Confirmations enfants...")
    time.sleep(1)
    msgs = dtc.drain(timeout=2)
    for m in msgs:
        if m.get("Type") == ORDER_UPDATE:
            cid = m.get("ClientOrderID", "")
            sid = m.get("ServerOrderID", "")
            status = m.get("OrderStatus", 0)
            if cid and sid:
                server_ids[cid] = sid
            tag = ""
            for sym, info in bracket_info.items():
                if info["tp_cid"] in str(cid): tag = f"[{sym} TP]"
                elif info["sl_cid"] in str(cid): tag = f"[{sym} SL]"
            print(f"  {tag} status={status} SID={sid}")

    # ── 8. Monitoring OCO manuel (120s) ──
    print(f"\n[8] Monitoring OCO — attente fills (120s max)...")
    print(f"  Ctrl+C pour arreter\n")

    filled_syms = set()
    oco_cancels = []

    try:
        end_time = time.time() + 120
        while time.time() < end_time and len(filled_syms) < 2:
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

                # Identifier instrument + type
                tag = ""
                for sym, info in bracket_info.items():
                    if info["tp_cid"] in str(cid):
                        tag = f"[{sym} TP]"
                    elif info["sl_cid"] in str(cid):
                        tag = f"[{sym} SL]"

                if tag:
                    print(f"  {tag} status={status} fill={fp}")

                # Fill detecte → annuler l'oppose
                is_filled = status in (2, 7) and fp and fp > 1000
                if is_filled and cid in oco_pairs:
                    opposite = oco_pairs[cid]

                    # Quel instrument + exit type ?
                    exit_type = "?"
                    exit_sym = "?"
                    for sym, info in bracket_info.items():
                        if cid == info["tp_cid"]:
                            exit_type = "TP"
                            exit_sym = sym
                        elif cid == info["sl_cid"]:
                            exit_type = "SL"
                            exit_sym = sym

                    pnl = ""
                    if exit_sym in bracket_info:
                        entry = bracket_info[exit_sym]["fill"]
                        direction = 1 if sides[exit_sym] == BUY else -1
                        pnl_ticks = (fp - entry) / INSTRUMENTS[exit_sym]["tick_size"] * direction
                        pnl = f" P&L={pnl_ticks:+.0f} ticks"

                    print(f"\n  >>> [{exit_sym}] {exit_type} FILLED @ {fp}{pnl}")
                    print(f"      Annulation opposé: {opposite}")

                    # Cancel l'ordre oppose
                    cancel_msg = {
                        "Type": CANCEL_ORDER,
                        "ClientOrderID": opposite,
                        "TradeAccount": ACCOUNT,
                    }
                    if opposite in server_ids:
                        cancel_msg["ServerOrderID"] = server_ids[opposite]
                    dtc.send(cancel_msg)
                    oco_cancels.append({"sym": exit_sym, "exit": exit_type,
                                        "filled": cid, "cancelled": opposite})
                    filled_syms.add(exit_sym)

            if t == POSITION_UPDATE:
                qty = msg.get("Quantity", 0)
                sym_p = msg.get("Symbol", "")
                avg = msg.get("AveragePrice", 0)
                if sym_p:
                    print(f"  Position: {sym_p} qty={qty} avg={avg}")

    except KeyboardInterrupt:
        print("\n  Arret par Ctrl+C")

    # ── 9. Confirmation des cancels ──
    print(f"\n[9] Verification cancels...")
    time.sleep(1)
    cancel_msgs = dtc.drain(timeout=2)
    for cm in cancel_msgs:
        if cm.get("Type") == ORDER_UPDATE:
            cs = cm.get("OrderStatus", 0)
            cc = cm.get("ClientOrderID", "")
            tag = ""
            for sym, info in bracket_info.items():
                if info["tp_cid"] in str(cc): tag = f"[{sym} TP]"
                elif info["sl_cid"] in str(cc): tag = f"[{sym} SL]"
            # Status 6 = Cancelled
            status_str = "CANCELLED" if cs in (5, 6) else f"status={cs}"
            print(f"  {tag} {status_str} CID={cc}")

    # ── 10. Positions finales ──
    print(f"\n[10] Positions finales...")
    dtc.send({"Type": 305, "RequestID": 3})
    time.sleep(1)
    final_msgs = dtc.drain(timeout=2)
    for m in final_msgs:
        if m.get("Type") == POSITION_UPDATE:
            sym_f = m.get("Symbol", "")
            qty_f = m.get("Quantity", 0)
            avg_f = m.get("AveragePrice", 0)
            print(f"  {sym_f}: qty={qty_f} avg={avg_f}")

    # ── Resume final ──
    print(f"\n{'='*65}")
    print(f"  RESUME TEST DUAL")
    print(f"  Fills:   ES @ {fill_prices.get('ES', 0):.2f}  |  NQ @ {fill_prices.get('NQ', 0):.2f}")
    for c in oco_cancels:
        print(f"  OCO OK:  [{c['sym']}] {c['exit']} filled → oppose annule")
    if len(oco_cancels) == 0:
        print(f"  OCO:     Non teste (timeout ou ordres non touches)")
    print(f"  Resultat: {len(oco_cancels)}/2 brackets resolus")
    print(f"{'='*65}\n")

    dtc.close()


if __name__ == "__main__":
    main()
