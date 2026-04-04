"""
test_oco_persistent.py — Test OCO manuel avec connexion PERSISTANTE
====================================================================

Utilise DTCConnector avec _recv_loop (thread permanent) pour prouver
que quand TP ou SL est touche, l'oppose est annule automatiquement.

C'est le test DEFINITIF : meme architecture que le vrai bot.

Usage (VPS uniquement) :
    python test_oco_persistent.py --buy     # BUY ES micro
    python test_oco_persistent.py --sell    # SELL ES micro

Auteur : MIA Trading System
"""

import json
import logging
import socket
import time
import threading
import uuid
import sys

# ── Logging visible ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Config ──
HOST = "127.0.0.1"
PORT = 11099
SYMBOL = "ESM26-CME"
ACCOUNT = "Sim3"
TICK_SIZE = 0.25
SL_TICKS = 20    # 5 pts
TP_TICKS = 40    # 10 pts

# DTC Message Types
DTC_LOGON_REQUEST = 1
DTC_LOGON_RESPONSE = 2
DTC_HEARTBEAT = 3
DTC_MARKET_ORDER = 208
DTC_CANCEL_ORDER = 203
DTC_OPEN_ORDERS_REQUEST = 300
DTC_POSITION_REQUEST = 305
DTC_ORDER_UPDATE = 301
DTC_POSITION_UPDATE = 306

BUY = 1
SELL = 2
MARKET = 1
LIMIT = 2
STOP = 3


class PersistentDTCClient:
    """
    Client DTC avec connexion persistante et _recv_loop en thread.
    Meme architecture que dtc_connector.py du bot.
    """

    def __init__(self):
        self.sock = None
        self.connected = False
        self.lock = threading.Lock()
        self._recv_buffer = b""
        self._running = False
        self._recv_thread = None
        self._last_heartbeat = 0.0

        # OCO manuel
        self._oco_pairs = {}          # {tp_cid: sl_cid, sl_cid: tp_cid}
        self._oco_processed = set()
        self._server_order_ids = {}   # {cid: server_id}

        # Resultats
        self.fills = []               # Liste des fills recus
        self.cancels_sent = []        # Cancels envoyes
        self.cancel_confirmations = [] # Confirmations de cancel

    def connect(self):
        """Connecte + logon + lance _recv_loop."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((HOST, PORT))

        # Logon
        self._send({
            "Type": DTC_LOGON_REQUEST,
            "ProtocolVersion": 8,
            "HeartbeatIntervalInSeconds": 10,
            "ClientName": "MIA_OCO_TEST",
        })

        # Attendre reponse
        resp = self._recv_one(timeout=5)
        if not resp or resp.get("Type") != DTC_LOGON_RESPONSE or resp.get("Result") != 1:
            logger.error(f"Logon ECHEC: {resp}")
            return False

        logger.info(f"Logon OK: {resp.get('ResultText', '')[:50]}")
        self.connected = True

        # Lancer recv_loop en thread (comme le vrai bot)
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        logger.info("_recv_loop thread demarre — connexion PERSISTANTE")

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
        """Recoit UN message (readuntil \\x00)."""
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
        """Boucle de reception PERMANENTE (comme dtc_connector.py)."""
        logger.info("_recv_loop: en ecoute...")
        while self._running:
            try:
                self.sock.settimeout(2)
                # Lire donnees brutes
                try:
                    chunk = self.sock.recv(8192)
                    if not chunk:
                        logger.warning("_recv_loop: connexion fermee")
                        break
                    self._recv_buffer += chunk
                except socket.timeout:
                    continue

                # Parser tous les messages complets dans le buffer
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

                    msg_type = msg.get("Type", 0)

                    if msg_type == DTC_HEARTBEAT:
                        self._last_heartbeat = time.time()
                        self._send({"Type": DTC_HEARTBEAT})

                    elif msg_type == DTC_ORDER_UPDATE:
                        self._handle_order_update(msg)

                    elif msg_type == DTC_POSITION_UPDATE:
                        qty = msg.get("Quantity", 0)
                        sym = msg.get("Symbol", "")
                        avg = msg.get("AveragePrice", 0)
                        if sym:
                            logger.info(f"POSITION: {sym} qty={qty} avg={avg}")

            except Exception as e:
                if self._running:
                    logger.error(f"_recv_loop error: {e}")
                    time.sleep(1)

        logger.info("_recv_loop: arrete")

    def _handle_order_update(self, msg):
        """Traite OrderUpdate — GERE OCO MANUEL."""
        order_status = msg.get("OrderStatus", 0)
        cid = msg.get("ClientOrderID", "")
        sid = msg.get("ServerOrderID", "")
        fp = msg.get("AverageFillPrice", 0) or msg.get("LastFillPrice", 0)
        info = msg.get("InfoText", "")

        # Tracker ServerOrderID
        if cid and sid:
            self._server_order_ids[cid] = sid

        # Identifier le type d'ordre
        tag = ""
        if "_TP_" in cid: tag = "[TP]"
        elif "_SL_" in cid: tag = "[SL]"
        elif "_P_" in cid: tag = "[PARENT]"

        # Log tout
        logger.info(f"ORDER_UPDATE {tag}: status={order_status} CID={cid} "
                     f"fill={fp} SID={sid} {info}")

        # Status cancelled (5, 6, 8)
        if order_status in (5, 6, 8):
            self.cancel_confirmations.append({
                "cid": cid, "status": order_status, "time": time.time()
            })
            logger.info(f"  CANCEL CONFIRME {tag}: {cid}")
            return

        # Status FILLED (7)
        is_filled = order_status == 7 and fp and fp > 1000
        if is_filled:
            self.fills.append({
                "cid": cid, "price": fp, "time": time.time()
            })

            # ── OCO MANUEL : annuler l'oppose ──
            if cid in self._oco_pairs and cid not in self._oco_processed:
                opposite_cid = self._oco_pairs[cid]
                self._oco_processed.add(cid)
                self._oco_processed.add(opposite_cid)

                exit_type = "TP" if "_TP_" in cid else "SL"
                opp_type = "SL" if exit_type == "TP" else "TP"

                logger.info(f"")
                logger.info(f"  *** OCO TRIGGER: {exit_type} FILLED @ {fp} ***")
                logger.info(f"  *** CANCEL {opp_type}: {opposite_cid} ***")
                logger.info(f"")

                # Envoyer cancel
                cancel_msg = {
                    "Type": DTC_CANCEL_ORDER,
                    "ClientOrderID": opposite_cid,
                    "TradeAccount": ACCOUNT,
                }
                if opposite_cid in self._server_order_ids:
                    cancel_msg["ServerOrderID"] = self._server_order_ids[opposite_cid]
                    logger.info(f"  (avec ServerOrderID: {self._server_order_ids[opposite_cid]})")

                self._send(cancel_msg)
                self.cancels_sent.append({
                    "filled": cid, "cancelled": opposite_cid, "time": time.time()
                })

    def register_oco_pair(self, tp_cid, sl_cid):
        self._oco_pairs[tp_cid] = sl_cid
        self._oco_pairs[sl_cid] = tp_cid
        logger.info(f"OCO pair: {tp_cid} <-> {sl_cid}")

    def disconnect(self):
        self._running = False
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass


def main():
    side = BUY if "--buy" in sys.argv else SELL if "--sell" in sys.argv else None
    if side is None:
        print("Usage: python test_oco_persistent.py --buy | --sell")
        return

    side_str = "BUY" if side == BUY else "SELL"
    child_side = SELL if side == BUY else BUY

    print(f"\n{'='*65}")
    print(f"  TEST OCO PERSISTANT — {side_str} {SYMBOL}")
    print(f"  Connexion permanente + OCO manuel automatique")
    print(f"  SL={SL_TICKS}t ({SL_TICKS*TICK_SIZE}pts)  TP={TP_TICKS}t ({TP_TICKS*TICK_SIZE}pts)")
    print(f"{'='*65}\n")

    dtc = PersistentDTCClient()

    # ── 1. Connexion persistante ──
    if not dtc.connect():
        return

    time.sleep(1)

    # ── 2. Verifier flat ──
    logger.info("[2] Verification positions...")
    dtc._send({"Type": DTC_POSITION_REQUEST, "RequestID": 1})
    time.sleep(2)

    # ── 3. Parent MARKET ──
    parent_cid = f"MIA_P_{uuid.uuid4().hex[:8]}"
    logger.info(f"[3] Envoi {side_str} MARKET: {parent_cid}")
    dtc._send({
        "Type": DTC_MARKET_ORDER,
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

    # ── 4. Attendre fill parent ──
    logger.info("[4] Attente fill parent (10s max)...")
    fill_price = 0
    end_time = time.time() + 10
    while time.time() < end_time and fill_price == 0:
        for f in dtc.fills:
            if parent_cid in f["cid"]:
                fill_price = f["price"]
                break
        time.sleep(0.2)

    if fill_price <= 0:
        logger.error("Pas de fill! Flatten manuellement.")
        dtc.disconnect()
        return

    # ── 5. Bracket TP/SL ──
    if side == BUY:
        tp_price = fill_price + TP_TICKS * TICK_SIZE
        sl_price = fill_price - SL_TICKS * TICK_SIZE
    else:
        tp_price = fill_price - TP_TICKS * TICK_SIZE
        sl_price = fill_price + SL_TICKS * TICK_SIZE

    tp_cid = f"MIA_TP_{uuid.uuid4().hex[:8]}"
    sl_cid = f"MIA_SL_{uuid.uuid4().hex[:8]}"
    oco_group = f"MIA_OCO_{uuid.uuid4().hex[:8]}"

    logger.info(f"[5] Bracket: entry={fill_price} TP={tp_price} SL={sl_price}")

    # TP LIMIT
    dtc._send({
        "Type": DTC_MARKET_ORDER,
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

    time.sleep(0.3)

    # SL STOP
    dtc._send({
        "Type": DTC_MARKET_ORDER,
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

    # Enregistrer paire OCO
    dtc.register_oco_pair(tp_cid, sl_cid)

    logger.info(f"  TP: {tp_cid}")
    logger.info(f"  SL: {sl_cid}")

    # ── 6. ATTENTE — connexion reste ouverte, _recv_loop gere tout ──
    logger.info("")
    logger.info("=" * 50)
    logger.info("  CONNEXION PERSISTANTE — en attente de TP ou SL")
    logger.info("  _recv_loop gere l'OCO automatiquement")
    logger.info("  Ctrl+C pour arreter")
    logger.info("=" * 50)
    logger.info("")

    try:
        timeout = 300  # 5 minutes max
        end_time = time.time() + timeout
        while time.time() < end_time:
            time.sleep(1)

            # Verifier si OCO s'est declenche
            if dtc.cancels_sent:
                logger.info("OCO cancel envoye! Attente confirmation (5s)...")
                time.sleep(5)
                break

    except KeyboardInterrupt:
        logger.info("Arret par Ctrl+C")

    # ── 7. Rapport ──
    print(f"\n{'='*65}")
    print(f"  RAPPORT OCO PERSISTANT")
    print(f"{'='*65}")
    print(f"  Entry: {side_str} @ {fill_price}")
    print(f"  TP: {tp_price}  SL: {sl_price}")
    print(f"")
    print(f"  Fills recus: {len(dtc.fills)}")
    for f in dtc.fills:
        tag = ""
        if "_TP_" in f["cid"]: tag = "TP"
        elif "_SL_" in f["cid"]: tag = "SL"
        elif "_P_" in f["cid"]: tag = "PARENT"
        print(f"    {tag}: {f['cid'][:25]} @ {f['price']}")
    print(f"")
    print(f"  OCO cancels envoyes: {len(dtc.cancels_sent)}")
    for c in dtc.cancels_sent:
        print(f"    Filled: {c['filled'][:25]}")
        print(f"    Cancel: {c['cancelled'][:25]}")
    print(f"")
    print(f"  Cancel confirmations: {len(dtc.cancel_confirmations)}")
    for c in dtc.cancel_confirmations:
        print(f"    {c['cid'][:25]} status={c['status']}")
    print(f"")

    if dtc.cancels_sent and dtc.cancel_confirmations:
        print(f"  >>> OCO MANUEL: OK — ordre oppose annule automatiquement")
    elif dtc.cancels_sent:
        print(f"  >>> OCO MANUEL: ENVOYE mais pas de confirmation cancel")
    else:
        print(f"  >>> OCO MANUEL: NON TESTE (timeout ou Ctrl+C)")

    print(f"{'='*65}\n")

    dtc.disconnect()


if __name__ == "__main__":
    main()
