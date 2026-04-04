"""
test_dtc_live.py — Test de connexion DTC + ordre simulation
==============================================================

ATTENTION : Ce script envoie un VRAI ordre a Sierra Chart.
Verifier que le mode SIM3 est actif avant de lancer.

Usage (sur le VPS uniquement) :
    python test_dtc_live.py              # Test connexion seulement
    python test_dtc_live.py --buy-test   # Envoie un achat test (SIM3)
    python test_dtc_live.py --sell-test  # Envoie une vente test (SIM3)

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import json
import socket
import struct
import sys
import time


DTC_HOST = "127.0.0.1"
DTC_PORT = 11099

# DTC Message Types
DTC_LOGON_REQUEST = 1
DTC_LOGON_RESPONSE = 2
DTC_HEARTBEAT = 3
DTC_SUBMIT_NEW_SINGLE_ORDER = 208
DTC_ORDER_UPDATE = 304
DTC_OPEN_ORDERS_REQUEST = 300
DTC_CURRENT_POSITIONS_REQUEST = 305
DTC_POSITION_UPDATE = 306
DTC_MARKET_DATA_REQUEST = 101
DTC_MARKET_DATA_SNAPSHOT = 104

# Order sides
BUY = 1
SELL = 2

# Order types
MARKET = 1


def send_msg(sock, msg):
    """Envoie un message DTC JSON (format SC: JSON + null byte)."""
    data = json.dumps(msg).encode("utf-8") + b"\x00"
    sock.sendall(data)


def recv_all_raw(sock, timeout=3):
    """Recoit tous les messages DTC disponibles (multi-messages dans un buffer)."""
    sock.settimeout(timeout)
    msgs = []
    buf = b""
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
            # Chaque message est termine par \x00
            while b"\x00" in buf:
                idx = buf.index(b"\x00")
                json_str = buf[:idx].decode("utf-8", errors="ignore").strip()
                buf = buf[idx+1:]
                if json_str:
                    try:
                        msgs.append(json.loads(json_str))
                    except json.JSONDecodeError:
                        pass
    except socket.timeout:
        # Parser ce qui reste dans le buffer
        if buf:
            parts = buf.split(b"\x00")
            for p in parts:
                s = p.decode("utf-8", errors="ignore").strip()
                if s:
                    try:
                        msgs.append(json.loads(s))
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        print(f"  Erreur recv: {e}")
    return msgs


def main():
    print("=" * 60)
    print("  TEST DTC LIVE — Connexion Sierra Chart")
    print("=" * 60)

    buy_test = "--buy-test" in sys.argv
    sell_test = "--sell-test" in sys.argv

    # ── 1. Connexion ──
    print(f"\n[1] Connexion a {DTC_HOST}:{DTC_PORT}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((DTC_HOST, DTC_PORT))
        print("  ✅ Socket connecte")
    except Exception as e:
        print(f"  ❌ Connexion echouee: {e}")
        return

    # ── 2. Logon ──
    print("\n[2] Logon DTC...")
    logon = {
        "Type": DTC_LOGON_REQUEST,
        "ProtocolVersion": 8,
        "Username": "",
        "Password": "",
        "HeartbeatIntervalInSeconds": 10,
        "ClientName": "MIA_Bot_V2_TEST",
    }
    send_msg(sock, logon)

    responses = recv_all_raw(sock, timeout=5)
    response = responses[0] if responses else None
    if response:
        print(f"  Type: {response.get('Type')}")
        if response.get("Type") == DTC_LOGON_RESPONSE:
            result = response.get("Result", 0)
            text = response.get("ResultText", "")
            server = response.get("ServerName", "")
            print(f"  Result: {result} ({text})")
            print(f"  Server: {server}")
            if result == 1:
                print("  ✅ Logon reussi")
            else:
                print(f"  ❌ Logon echoue: {text}")
                sock.close()
                return
        else:
            print(f"  Reponse inattendue: {response}")
    else:
        print("  ❌ Pas de reponse au logon")
        sock.close()
        return

    # Vider les messages en attente
    msgs = recv_all_raw(sock, timeout=2)
    for m in msgs:
        t = m.get("Type", "?")
        if t == DTC_HEARTBEAT:
            send_msg(sock, {"Type": DTC_HEARTBEAT})

    # ── 3. Demander les positions ──
    print("\n[3] Positions ouvertes...")
    send_msg(sock, {"Type": DTC_CURRENT_POSITIONS_REQUEST, "RequestID": 1})
    time.sleep(1)
    msgs = recv_all_raw(sock, timeout=3)
    positions = [m for m in msgs if m.get("Type") == DTC_POSITION_UPDATE]
    if positions:
        for p in positions:
            sym = p.get("Symbol", "?")
            qty = p.get("Quantity", 0)
            avg = p.get("AveragePrice", 0)
            print(f"  Position: {sym} qty={qty} avg={avg}")
    else:
        print("  Pas de position ouverte")

    # ── 4. Ordre test (seulement si demande) ──
    if buy_test or sell_test:
        side = BUY if buy_test else SELL
        side_str = "BUY" if buy_test else "SELL"
        symbol = "ESM26-CME"

        print(f"\n[4] ENVOI ORDRE {side_str} {symbol} (1 micro)...")
        print("  ⚠️  VERIFIEZ QUE SIM3 EST ACTIF !")
        print("  Envoi dans 3 secondes... (Ctrl+C pour annuler)")

        try:
            time.sleep(3)
        except KeyboardInterrupt:
            print("  Annule.")
            sock.close()
            return

        # TradeAccount: nom du compte Sim dans Sierra Chart
        # Changer si le compte sim a un nom different
        trade_account = "Sim3"

        parent_cid = f"MIA_P_{int(time.time())}"
        tp_cid = f"MIA_TP_{int(time.time())}"
        sl_cid = f"MIA_SL_{int(time.time())}"

        # Étape 1 : Ordre parent (market)
        parent_order = {
            "Type": DTC_SUBMIT_NEW_SINGLE_ORDER,
            "Symbol": "ESM26-CME",
            "ClientOrderID": parent_cid,
            "OrderType": MARKET,
            "BuySell": side,
            "Quantity": 1,
            "TradeAccount": trade_account,
            "IsAutomatedOrder": 1,
            "OpenOrClose": 1,  # OPEN
            "TimeInForce": 0,
        }
        send_msg(sock, parent_order)
        print(f"  Parent envoye: {parent_cid}")

        # Attendre le fill du parent
        time.sleep(2)
        fill_price = 0
        msgs = recv_all_raw(sock, timeout=3)
        for m in msgs:
            t = m.get("Type", 0)
            if t == DTC_HEARTBEAT:
                send_msg(sock, {"Type": DTC_HEARTBEAT})
            elif t == DTC_ORDER_UPDATE:
                status = m.get("OrderStatus", "")
                fp = m.get("AverageFillPrice", 0) or m.get("Price1", 0)
                oid = m.get("ClientOrderID", "")
                print(f"  OrderUpdate: status={status} fill={fp} id={oid}")
                if fp and fp > 1000:
                    fill_price = fp
            elif t == DTC_POSITION_UPDATE:
                avg = m.get("AveragePrice", 0)
                if avg and avg > 1000:
                    fill_price = avg
                    print(f"  PositionUpdate: avg={avg}")

        if fill_price <= 0:
            # Fallback: lire le dernier prix depuis les updates reçus
            for m in msgs:
                lp = m.get("LastPrice", 0) or m.get("Price", 0) or m.get("AverageFillPrice", 0)
                if lp > 1000:
                    fill_price = lp
                    break
            if fill_price <= 0:
                print("  ❌ Pas de fill price — ABANDON (pas de bracket)")
                print("  Flatten manuellement dans Sierra Chart!")
                sock.close()
                return

        # Calculer TP et SL (5 ticks pour test = 1.25 pts ES)
        tick_size = 0.25
        sl_ticks = 5
        tp_ticks = 10
        if side == BUY:
            tp_price = fill_price + tp_ticks * tick_size
            sl_price = fill_price - sl_ticks * tick_size
            child_side = SELL
        else:
            tp_price = fill_price - tp_ticks * tick_size
            sl_price = fill_price + sl_ticks * tick_size
            child_side = BUY

        print(f"  Fill: {fill_price} → TP={tp_price} SL={sl_price}")

        # Étape 2 : TP + SL en 2 ordres SINGLE séparés liés par OCOGroup
        # ❌ NE PAS utiliser SUBMIT_NEW_OCO_ORDER (206) — rejet silencieux
        # ❌ NE PAS utiliser ParentTriggerClientOrderID — ne fonctionne pas
        # ✅ Utiliser 2x SUBMIT_NEW_SINGLE_ORDER avec OCOGroup1 commun
        oco_group = f"MIA_OCO_{int(time.time())}"

        # TP = LIMIT order
        tp_msg = {
            "Type": DTC_SUBMIT_NEW_SINGLE_ORDER,
            "Symbol": "ESM26-CME",
            "ClientOrderID": tp_cid,
            "OrderType": 2,        # LIMIT
            "BuySell": child_side,
            "Quantity": 1,
            "Price1": float(tp_price),
            "Price2": 0.0,
            "TimeInForce": 0,      # DAY
            "TradeAccount": trade_account,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,   # CLOSE position
            "OCOGroup1": oco_group,
        }
        send_msg(sock, tp_msg)
        print(f"  TP envoye: {tp_cid} LIMIT @ {tp_price}")

        time.sleep(0.5)

        # SL = STOP order
        sl_msg = {
            "Type": DTC_SUBMIT_NEW_SINGLE_ORDER,
            "Symbol": "ESM26-CME",
            "ClientOrderID": sl_cid,
            "OrderType": 3,        # STOP
            "BuySell": child_side,
            "Quantity": 1,
            "Price1": float(sl_price),
            "Price2": 0.0,
            "StopPrice": float(sl_price),
            "TimeInForce": 0,      # DAY
            "TradeAccount": trade_account,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,   # CLOSE position
            "OCOGroup1": oco_group,
        }
        send_msg(sock, sl_msg)
        print(f"  SL envoye: {sl_cid} STOP @ {sl_price}")
        print(f"  OCO Group: {oco_group}")

        # Attendre les confirmations
        print("  Attente des confirmations...")
        for _ in range(5):
            msgs = recv_all_raw(sock, timeout=2)
            for m in msgs:
                t = m.get("Type", 0)
                if t == DTC_ORDER_UPDATE:
                    status = m.get("OrderStatus", "")
                    fill_price = m.get("AverageFillPrice", 0)
                    oid = m.get("ClientOrderID", "")
                    print(f"  OrderUpdate: status={status} "
                          f"fill={fill_price} id={oid}")
                    if status == "Filled":
                        print(f"\n  ✅ FILL CONFIRME @ {fill_price}")
                        break
                elif t == DTC_HEARTBEAT:
                    send_msg(sock, {"Type": DTC_HEARTBEAT})
            else:
                continue
            break

        # Verifier la position
        time.sleep(1)
        send_msg(sock, {"Type": DTC_CURRENT_POSITIONS_REQUEST, "RequestID": 2})
        time.sleep(1)
        msgs = recv_all_raw(sock, timeout=3)
        for m in msgs:
            if m.get("Type") == DTC_POSITION_UPDATE:
                sym = m.get("Symbol", "?")
                qty = m.get("Quantity", 0)
                print(f"  Position apres trade: {sym} qty={qty}")

    else:
        print("\n[4] Pas d'ordre envoye (ajouter --buy-test ou --sell-test)")

    # ── Fermeture ──
    print(f"\n{'='*60}")
    print("  TEST TERMINE")
    print(f"{'='*60}")
    sock.close()


if __name__ == "__main__":
    main()
