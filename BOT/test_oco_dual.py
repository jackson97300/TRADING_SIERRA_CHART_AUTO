"""
test_oco_dual.py — Test OCO persistant ES + NQ simultane
==========================================================

Connexion persistante + OCO manuel sur 2 instruments.

Usage (VPS uniquement) :
    python test_oco_dual.py --buy     # BUY ES + BUY NQ
    python test_oco_dual.py --sell    # SELL ES + SELL NQ

Auteur : MIA Trading System
"""

import json
import logging
import socket
import time
import threading
import uuid
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 11099
ACCOUNT = "Sim3"

INSTRUMENTS = {
    "ES": {"contract": "ESM26-CME", "tick_size": 0.25},
    "NQ": {"contract": "NQM26-CME", "tick_size": 0.25},
}

SL_TICKS = 15
TP_TICKS = 15

DTC_LOGON_REQUEST = 1
DTC_LOGON_RESPONSE = 2
DTC_HEARTBEAT = 3
DTC_MARKET_ORDER = 208
DTC_CANCEL_ORDER = 203
DTC_POSITION_REQUEST = 305
DTC_ORDER_UPDATE = 301
DTC_POSITION_UPDATE = 306

BUY = 1
SELL = 2
MARKET = 1
LIMIT = 2
STOP = 3


class DualDTCClient:
    """Client DTC persistant multi-instrument avec OCO manuel."""

    def __init__(self):
        self.sock = None
        self.connected = False
        self.lock = threading.Lock()
        self._recv_buffer = b""
        self._running = False
        self._recv_thread = None

        self._oco_pairs = {}
        self._oco_processed = set()
        self._server_order_ids = {}

        self.fills = []
        self.cancels_sent = []
        self.cancel_confirmations = []

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((HOST, PORT))

        self._send({
            "Type": DTC_LOGON_REQUEST,
            "ProtocolVersion": 8,
            "HeartbeatIntervalInSeconds": 10,
            "ClientName": "MIA_DUAL_OCO",
        })

        resp = self._recv_one(timeout=5)
        if not resp or resp.get("Type") != DTC_LOGON_RESPONSE or resp.get("Result") != 1:
            logger.error(f"Logon ECHEC: {resp}")
            return False

        logger.info(f"Logon OK")
        self.connected = True
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        return True

    def _send(self, msg):
        with self.lock:
            if not self.sock:
                return
            try:
                data = json.dumps(msg, separators=(',', ':')).encode('utf-8') + b'\x00'
                self.sock.sendall(data)
            except Exception as e:
                logger.error(f"Send error: {e}")

    def _recv_one(self, timeout=5):
        self.sock.settimeout(timeout)
        while True:
            idx = self._recv_buffer.find(b'\x00')
            if idx >= 0:
                raw = self._recv_buffer[:idx]
                self._recv_buffer = self._recv_buffer[idx+1:]
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
                self._recv_buffer += chunk
            except socket.timeout:
                return None

    def _recv_loop(self):
        while self._running:
            try:
                self.sock.settimeout(2)
                try:
                    chunk = self.sock.recv(8192)
                    if not chunk:
                        break
                    self._recv_buffer += chunk
                except socket.timeout:
                    continue

                while b'\x00' in self._recv_buffer:
                    idx = self._recv_buffer.find(b'\x00')
                    raw = self._recv_buffer[:idx]
                    self._recv_buffer = self._recv_buffer[idx+1:]
                    if not raw:
                        continue
                    try:
                        msg = json.loads(raw.decode('utf-8', 'ignore'))
                    except json.JSONDecodeError:
                        continue

                    t = msg.get("Type", 0)
                    if t == DTC_HEARTBEAT:
                        self._send({"Type": DTC_HEARTBEAT})
                    elif t == DTC_ORDER_UPDATE:
                        self._handle_order_update(msg)
                    elif t == DTC_POSITION_UPDATE:
                        sym = msg.get("Symbol", "")
                        qty = msg.get("Quantity", 0)
                        avg = msg.get("AveragePrice", 0)
                        if sym:
                            logger.info(f"POSITION: {sym} qty={qty} avg={avg}")

            except Exception as e:
                if self._running:
                    logger.error(f"recv_loop error: {e}")
                    time.sleep(1)

    def _handle_order_update(self, msg):
        status = msg.get("OrderStatus", 0)
        cid = msg.get("ClientOrderID", "")
        sid = msg.get("ServerOrderID", "")
        fp = msg.get("AverageFillPrice", 0) or msg.get("LastFillPrice", 0)

        if cid and sid:
            self._server_order_ids[cid] = sid

        tag = ""
        if "_TP_" in cid: tag = "[TP]"
        elif "_SL_" in cid: tag = "[SL]"
        elif "_P_" in cid: tag = "[PAR]"

        # Identifier instrument
        inst = ""
        for sym in ["ES", "NQ"]:
            if f"_{sym}_" in cid:
                inst = sym
                break

        prefix = f"[{inst}]{tag}" if inst else tag
        logger.info(f"ORDER {prefix}: status={status} fill={fp} CID={cid[:30]}")

        # Cancel confirm
        if status in (5, 6, 8):
            self.cancel_confirmations.append({"cid": cid, "status": status})
            if status in (6, 8):
                logger.info(f"  CANCEL OK {prefix}")

        # Fill
        if status == 7 and fp and fp > 1000:
            self.fills.append({"cid": cid, "price": fp, "inst": inst})

            if cid in self._oco_pairs and cid not in self._oco_processed:
                opposite = self._oco_pairs[cid]
                self._oco_processed.add(cid)
                self._oco_processed.add(opposite)

                exit_type = "TP" if "_TP_" in cid else "SL"
                opp_type = "SL" if exit_type == "TP" else "TP"

                logger.info(f"")
                logger.info(f"  *** [{inst}] {exit_type} FILLED @ {fp} ***")
                logger.info(f"  *** CANCEL {opp_type}: {opposite[:30]} ***")

                cancel_msg = {
                    "Type": DTC_CANCEL_ORDER,
                    "ClientOrderID": opposite,
                    "TradeAccount": ACCOUNT,
                }
                if opposite in self._server_order_ids:
                    cancel_msg["ServerOrderID"] = self._server_order_ids[opposite]

                self._send(cancel_msg)
                self.cancels_sent.append({
                    "inst": inst, "exit": exit_type,
                    "filled": cid, "cancelled": opposite
                })
                logger.info(f"")

    def register_oco(self, tp_cid, sl_cid):
        self._oco_pairs[tp_cid] = sl_cid
        self._oco_pairs[sl_cid] = tp_cid

    def disconnect(self):
        self._running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass


def main():
    side = BUY if "--buy" in sys.argv else SELL if "--sell" in sys.argv else None
    if side is None:
        print("Usage: python test_oco_dual.py --buy | --sell")
        return

    side_str = "BUY" if side == BUY else "SELL"
    child_side = SELL if side == BUY else BUY

    print(f"\n{'='*65}")
    print(f"  TEST OCO DUAL — {side_str} ES + NQ")
    print(f"  SL={SL_TICKS}t  TP={TP_TICKS}t  Connexion persistante")
    print(f"{'='*65}\n")

    dtc = DualDTCClient()
    if not dtc.connect():
        return

    time.sleep(1)

    # Verifier flat
    dtc._send({"Type": DTC_POSITION_REQUEST, "RequestID": 1})
    time.sleep(2)

    # Envoyer 2 parents MARKET
    parent_ids = {}
    for sym, inst in INSTRUMENTS.items():
        cid = f"MIA_P_{sym}_{uuid.uuid4().hex[:6]}"
        parent_ids[sym] = cid
        dtc._send({
            "Type": DTC_MARKET_ORDER,
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
        logger.info(f"[{sym}] {side_str} MARKET: {cid}")
        time.sleep(0.1)

    # Attendre fills
    logger.info("Attente fills (10s)...")
    fill_prices = {}
    end = time.time() + 10
    while time.time() < end and len(fill_prices) < 2:
        for f in dtc.fills:
            for sym in ["ES", "NQ"]:
                if f"_{sym}_" in f["cid"] and "_P_" in f["cid"] and sym not in fill_prices:
                    fill_prices[sym] = f["price"]
        time.sleep(0.2)

    if len(fill_prices) < 2:
        logger.error(f"Fills incomplets: {fill_prices} — flatten manuellement!")
        dtc.disconnect()
        return

    # Brackets
    bracket_info = {}
    for sym, inst in INSTRUMENTS.items():
        fp = fill_prices[sym]
        ts = inst["tick_size"]

        if side == BUY:
            tp_price = fp + TP_TICKS * ts
            sl_price = fp - SL_TICKS * ts
        else:
            tp_price = fp - TP_TICKS * ts
            sl_price = fp + SL_TICKS * ts

        tp_cid = f"MIA_TP_{sym}_{uuid.uuid4().hex[:6]}"
        sl_cid = f"MIA_SL_{sym}_{uuid.uuid4().hex[:6]}"
        oco = f"MIA_OCO_{sym}_{uuid.uuid4().hex[:6]}"

        # TP
        dtc._send({
            "Type": DTC_MARKET_ORDER,
            "Symbol": inst["contract"],
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
            "OCOGroup1": oco,
        })
        time.sleep(0.2)

        # SL
        dtc._send({
            "Type": DTC_MARKET_ORDER,
            "Symbol": inst["contract"],
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
            "OCOGroup1": oco,
        })

        dtc.register_oco(tp_cid, sl_cid)
        bracket_info[sym] = {"fill": fp, "tp": tp_price, "sl": sl_price,
                             "tp_cid": tp_cid, "sl_cid": sl_cid}
        logger.info(f"[{sym}] entry={fp}  TP={tp_price}  SL={sl_price}")
        time.sleep(0.3)

    # Attente persistante
    logger.info("")
    logger.info("=" * 55)
    logger.info("  CONNEXION PERSISTANTE — OCO auto sur ES + NQ")
    logger.info("  Ctrl+C pour arreter (5 min max)")
    logger.info("=" * 55)
    logger.info("")

    try:
        end = time.time() + 300
        while time.time() < end:
            time.sleep(1)
            # Check si les 2 brackets sont resolus
            resolved = set(c["inst"] for c in dtc.cancels_sent)
            if len(resolved) >= 2:
                logger.info("Les 2 brackets resolus!")
                time.sleep(3)
                break
    except KeyboardInterrupt:
        logger.info("Arret Ctrl+C")

    # Rapport
    print(f"\n{'='*65}")
    print(f"  RAPPORT DUAL OCO")
    print(f"{'='*65}")
    for sym, info in bracket_info.items():
        print(f"  [{sym}] {side_str} @ {info['fill']}  TP={info['tp']}  SL={info['sl']}")
    print()

    for c in dtc.cancels_sent:
        exit_type = c["exit"]
        opp = "SL" if exit_type == "TP" else "TP"
        print(f"  [{c['inst']}] {exit_type} touched → {opp} CANCELLED")

    resolved = set(c["inst"] for c in dtc.cancels_sent)
    print(f"\n  Resultat: {len(resolved)}/2 OCO resolus")

    if len(resolved) == 2:
        print(f"  >>> SUCCES COMPLET — OCO manuel fonctionne sur ES + NQ")
    elif len(resolved) == 1:
        print(f"  >>> PARTIEL — 1/2 resolu, l'autre en attente")
    else:
        print(f"  >>> NON TESTE (timeout)")

    print(f"{'='*65}\n")
    dtc.disconnect()


if __name__ == "__main__":
    main()
