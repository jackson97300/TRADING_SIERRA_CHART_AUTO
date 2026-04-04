"""
test_dtc_nq_bracket.py — Test bracket NQ avec OCO manuel (VALIDE 02/04/2026)
================================================================================

BUY NQ micro + TP/SL 20 ticks + surveillance OCO avec ServerOrderID.
Connexion persistante — quand TP ou SL filled, cancel l'autre avec ServerOrderID.

VALIDE 3/3 sur Sim3 (02/04/2026) :
  - Test #1 : Fill 24177,    TP filled 24182,   SL annule, position 0
  - Test #2 : Fill 24186.75, TP filled 24192,   SL annule, position 0
  - Test #3 : Fill 24197.5,  SL filled 24192.5, TP annule, position 0

Timings mesures (test #3) :
  - BUY → Fill : ~1.0s
  - Fill → TP envoye : <1ms
  - TP → SL envoye : ~100ms
  - Bracket complet (BUY → SL) : ~1.15s
  - Fill TP/SL → Cancel oppose : ~300ms

Fixes cles :
  - cancel_order DOIT inclure ServerOrderID (pas juste ClientOrderID)
  - OrderStatus = 7 (integer) pour Filled, PAS 2 (2 = Open)
  - Type 206 / IsParentOrder / OCOGroup1 ne marchent PAS (SC serveur DTC)
  - Double envoi cancel par securite

Usage (VPS uniquement) :
    python test_dtc_nq_bracket.py

Auteur : MIA Trading System
Date   : 2026-04-02
"""

import json
import socket
import time
import sys

sys.stdout.reconfigure(line_buffering=True)

DTC_HOST = "127.0.0.1"
DTC_PORT = 11099
SYMBOL = "NQM26-CME"
TRADE_ACCOUNT = "Sim3"
SL_TICKS = 20
TP_TICKS = 20
TICK_SIZE = 0.25
TIMEOUT_SECONDS = 120


def send_msg(sock, msg):
    """Envoie un message DTC JSON (null-terminated)."""
    sock.sendall(json.dumps(msg).encode("utf-8") + b"\x00")


def recv_all_raw(sock, timeout=3):
    """Recoit tous les messages DTC disponibles."""
    sock.settimeout(timeout)
    msgs, buf = [], b""
    try:
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            buf += chunk
            while b"\x00" in buf:
                idx = buf.index(b"\x00")
                s = buf[:idx].decode("utf-8", errors="ignore").strip()
                buf = buf[idx + 1:]
                if s:
                    try:
                        msgs.append(json.loads(s))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        if buf:
            for p in buf.split(b"\x00"):
                s = p.decode("utf-8", errors="ignore").strip()
                if s:
                    try:
                        msgs.append(json.loads(s))
                    except json.JSONDecodeError:
                        pass
    return msgs


def is_filled(m):
    """Detecte si un ordre est filled (status=7 integer OU 'Filled' string)."""
    s = m.get("OrderStatus", "")
    return s == "Filled" or s == 7 or (
        m.get("FilledQuantity", 0) > 0 and s not in (2, "Open")
    )


def main():
    T0 = time.time()

    def ts():
        return f"{time.time() - T0:.3f}s"

    print("=" * 55)
    print(f"  TEST {SYMBOL} — BUY + BRACKET (SL={SL_TICKS}t TP={TP_TICKS}t)")
    print("=" * 55)

    # --- Connexion ---
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((DTC_HOST, DTC_PORT))
    send_msg(sock, {
        "Type": 1,
        "ProtocolVersion": 8,
        "HeartbeatIntervalInSeconds": 10,
        "ClientName": "MIA_NQ_BRACKET",
    })
    recv_all_raw(sock, timeout=2)
    recv_all_raw(sock, timeout=1)
    print(f"[{ts()}] Connecte + Logon OK")

    # --- BUY MARKET ---
    parent_cid = f"MIA_P_{int(time.time())}"
    send_msg(sock, {
        "Type": 208,
        "Symbol": SYMBOL,
        "ClientOrderID": parent_cid,
        "OrderType": 1,   # MARKET
        "BuySell": 1,     # BUY
        "Quantity": 1,
        "TradeAccount": TRADE_ACCOUNT,
        "IsAutomatedOrder": 1,
        "OpenOrClose": 1,  # OPEN
        "TimeInForce": 0,
    })
    t_sent = time.time()
    print(f"[{ts()}] BUY envoye: {parent_cid}")

    # --- Attendre fill (poll rapide) ---
    fill_price = 0
    for _ in range(8):
        msgs = recv_all_raw(sock, timeout=1)
        for m in msgs:
            t = m.get("Type", 0)
            if t == 3:
                send_msg(sock, {"Type": 3})
            if t == 301:
                st = m.get("OrderStatus", "")
                fp = m.get("AverageFillPrice", 0)
                print(f"[{ts()}] OrderUpdate st={st} fill={fp}")
                if fp > 10000:
                    fill_price = fp
            if (t == 306 and "NQ" in m.get("Symbol", "")
                    and m.get("AveragePrice", 0) > 10000
                    and m.get("Quantity", 0) != 0):
                fill_price = m.get("AveragePrice")
                print(f"[{ts()}] Position avg={fill_price}")
        if fill_price > 0:
            break

    # Fallback: demander la position
    if fill_price <= 0:
        print(f"[{ts()}] Fallback position request...")
        send_msg(sock, {"Type": 305, "RequestID": 50})
        time.sleep(1)
        for m in recv_all_raw(sock, timeout=2):
            if m.get("Type") == 306 and "NQ" in m.get("Symbol", ""):
                avg = m.get("AveragePrice", 0)
                if avg > 10000:
                    fill_price = avg
                    print(f"[{ts()}] Fill (fallback): {fill_price}")

    if fill_price <= 0:
        print(f"[{ts()}] ECHEC fill — ABANDON")
        sock.close()
        sys.exit(1)

    t_fill = time.time()
    print(f"[{ts()}] FILL @ {fill_price} (delai: {t_fill - t_sent:.3f}s)")

    # --- Bracket TP/SL (envoi immediat) ---
    tp_price = fill_price + TP_TICKS * TICK_SIZE
    sl_price = fill_price - SL_TICKS * TICK_SIZE

    tp_cid = f"MIA_TP_{int(time.time())}"
    sl_cid = f"MIA_SL_{int(time.time())}"
    server_oids = {}  # ClientOrderID -> ServerOrderID

    # TP LIMIT
    send_msg(sock, {
        "Type": 208,
        "Symbol": SYMBOL,
        "ClientOrderID": tp_cid,
        "OrderType": 2,   # LIMIT
        "BuySell": 2,     # SELL
        "Quantity": 1,
        "Price1": float(tp_price),
        "TimeInForce": 0,
        "TradeAccount": TRADE_ACCOUNT,
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2,  # CLOSE
    })
    t_tp = time.time()
    print(f"[{ts()}] TP @ {tp_price} (fill->TP: {t_tp - t_fill:.3f}s)")

    time.sleep(0.1)

    # SL STOP
    send_msg(sock, {
        "Type": 208,
        "Symbol": SYMBOL,
        "ClientOrderID": sl_cid,
        "OrderType": 3,   # STOP
        "BuySell": 2,     # SELL
        "Quantity": 1,
        "Price1": float(sl_price),
        "StopPrice": float(sl_price),
        "TimeInForce": 0,
        "TradeAccount": TRADE_ACCOUNT,
        "IsAutomatedOrder": 1,
        "OpenCloseTrade": 2,  # CLOSE
    })
    t_sl = time.time()
    print(f"[{ts()}] SL @ {sl_price} (TP->SL: {t_sl - t_tp:.3f}s)")
    print(f"[{ts()}] BRACKET COMPLET (BUY->SL: {t_sl - t_sent:.3f}s)")

    # --- Surveillance OCO ---
    # Cancel avec ServerOrderID OBLIGATOIRE + double envoi securite
    print(f"[{ts()}] Surveillance OCO ({TIMEOUT_SECONDS}s max)...")
    tp_ok = False
    sl_ok = False
    start = time.time()

    while time.time() - start < TIMEOUT_SECONDS:
        msgs = recv_all_raw(sock, timeout=1)
        for m in msgs:
            t = m.get("Type", 0)
            if t == 3:
                send_msg(sock, {"Type": 3})
                continue

            if t == 301:
                oid = m.get("ClientOrderID", "")
                soid = m.get("ServerOrderID", "")
                st = m.get("OrderStatus", "")
                fp = m.get("AverageFillPrice", 0)

                # Stocker ServerOrderID des reception
                if oid in (tp_cid, sl_cid) and soid:
                    server_oids[oid] = soid
                    print(f"[{ts()}] {oid[:15]}.. st={st} soid={soid}")

                # TP filled -> cancel SL
                if oid == tp_cid and is_filled(m):
                    print(f"[{ts()}] >>> TP FILLED @ {fp} — Cancel SL")
                    cancel_msg = {
                        "Type": 203,
                        "ClientOrderID": sl_cid,
                        "TradeAccount": TRADE_ACCOUNT,
                    }
                    if sl_cid in server_oids:
                        cancel_msg["ServerOrderID"] = server_oids[sl_cid]
                    send_msg(sock, cancel_msg)
                    time.sleep(0.3)
                    send_msg(sock, cancel_msg)  # Double cancel securite
                    print(f"[{ts()}] SL cancel envoye")
                    tp_ok = True

                # SL filled -> cancel TP
                if oid == sl_cid and is_filled(m):
                    print(f"[{ts()}] >>> SL FILLED @ {fp} — Cancel TP")
                    cancel_msg = {
                        "Type": 203,
                        "ClientOrderID": tp_cid,
                        "TradeAccount": TRADE_ACCOUNT,
                    }
                    if tp_cid in server_oids:
                        cancel_msg["ServerOrderID"] = server_oids[tp_cid]
                    send_msg(sock, cancel_msg)
                    time.sleep(0.3)
                    send_msg(sock, cancel_msg)
                    print(f"[{ts()}] TP cancel envoye")
                    sl_ok = True

        if tp_ok or sl_ok:
            time.sleep(1)

            # --- SECURITE : verifier qu'aucun ordre orphelin ne reste ---
            cancelled_cid = sl_cid if tp_ok else tp_cid
            send_msg(sock, {"Type": 300, "RequestID": 80})
            time.sleep(1)
            for m in recv_all_raw(sock, timeout=2):
                if m.get("Type") == 301:
                    oid = m.get("ClientOrderID", "")
                    st = m.get("OrderStatus", "")
                    soid = m.get("ServerOrderID", "")
                    # Si l'ordre oppose est encore ouvert, re-cancel
                    if oid == cancelled_cid and st in (2, 4, 5, "Open", "Working"):
                        print(f"[{ts()}] !!! Ordre orphelin detecte: {oid[:15]} st={st}")
                        cm = {"Type": 203, "ClientOrderID": oid, "TradeAccount": TRADE_ACCOUNT}
                        if soid:
                            cm["ServerOrderID"] = soid
                        send_msg(sock, cm)
                        time.sleep(0.3)
                        send_msg(sock, cm)
                        print(f"[{ts()}] Re-cancel envoye")

            # Verifier position finale
            send_msg(sock, {"Type": 305, "RequestID": 99})
            time.sleep(1)
            for m in recv_all_raw(sock, timeout=2):
                if m.get("Type") == 306:
                    sym = m.get("Symbol", "?")
                    qty = m.get("Quantity", 0)
                    print(f"[{ts()}] Position: {sym} qty={qty}")
                    # Flatten si position encore ouverte
                    if qty != 0 and "NQ" in sym:
                        print(f"[{ts()}] !!! Flatten {sym}...")
                        side = 2 if qty > 0 else 1
                        send_msg(sock, {
                            "Type": 208,
                            "Symbol": sym,
                            "ClientOrderID": f"FLAT_{int(time.time())}",
                            "OrderType": 1,
                            "BuySell": side,
                            "Quantity": abs(qty),
                            "TradeAccount": TRADE_ACCOUNT,
                            "IsAutomatedOrder": 1,
                            "OpenOrClose": 2,
                            "TimeInForce": 0,
                        })
            break

        e = int(time.time() - start)
        if e > 0 and e % 30 == 0:
            print(f"[{ts()}] ... {e}s ...")

    # Timeout: cancel tout + flatten
    if not tp_ok and not sl_ok:
        print(f"[{ts()}] Timeout — cancel + flatten")
        for cid in (tp_cid, sl_cid):
            cm = {"Type": 203, "ClientOrderID": cid, "TradeAccount": TRADE_ACCOUNT}
            if cid in server_oids:
                cm["ServerOrderID"] = server_oids[cid]
            send_msg(sock, cm)
        time.sleep(0.5)
        send_msg(sock, {
            "Type": 208,
            "Symbol": SYMBOL,
            "ClientOrderID": f"FLAT_{int(time.time())}",
            "OrderType": 1,
            "BuySell": 2,
            "Quantity": 1,
            "TradeAccount": TRADE_ACCOUNT,
            "IsAutomatedOrder": 1,
            "OpenOrClose": 2,
            "TimeInForce": 0,
        })
        time.sleep(2)
        recv_all_raw(sock, timeout=2)

    # Resultat
    t_total = time.time() - T0
    r = f"TP +{TP_TICKS * TICK_SIZE}pts" if tp_ok else \
        f"SL -{SL_TICKS * TICK_SIZE}pts" if sl_ok else "TIMEOUT"
    print(f"\n{'=' * 55}")
    print(f"  RESULTAT: {r} | Total: {t_total:.1f}s")
    print(f"{'=' * 55}")
    sock.close()
    print("Connexion fermee")


if __name__ == "__main__":
    main()
