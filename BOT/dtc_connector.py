"""
dtc_connector.py — Connexion DTC Protocol vers Sierra Chart
=============================================================

Protocol JSON sur TCP, port 11099.
Sierra Chart → AMP broker via Teton CME Routing.

Base sur V1 (sierra_dtc_connector.py) simplifie.
Supporte : market orders, bracket OCO, cancel, position query.

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import json
import logging
import socket
import struct
import time
import threading
import uuid
from dataclasses import dataclass
from typing import Optional, Callable

from bot_config import DTCConfig

logger = logging.getLogger(__name__)

# Systeme logs V2 (22/04/2026) : codes stables cross-process
try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("dtc_connector", process="bot_legacy")
except Exception:
    _v2log = None


# DTC Message Types
DTC_LOGON_REQUEST = 1
DTC_LOGON_RESPONSE = 2
DTC_HEARTBEAT = 3
DTC_MARKET_DATA_REQUEST = 101
DTC_MARKET_DATA_REJECT = 103
DTC_MARKET_DATA_SNAPSHOT = 104
DTC_MARKET_DATA_UPDATE = 107
DTC_MARKET_ORDER = 208
DTC_CANCEL_ORDER = 203
DTC_OPEN_ORDERS_REQUEST = 300
DTC_POSITION_REQUEST = 305
DTC_ORDER_UPDATE = 301   # V1 valide — JSON mode
DTC_POSITION_UPDATE = 306

# Order actions
BUY = 1
SELL = 2

# Order types
MARKET = 1
LIMIT = 2
STOP = 3
STOP_LIMIT = 4


@dataclass
class OrderFill:
    """Resultat d'un fill."""
    order_id: str = ""
    symbol: str = ""
    side: int = 0               # BUY=1, SELL=2
    fill_price: float = 0.0
    quantity: int = 0
    timestamp: float = 0.0
    is_filled: bool = False


class DTCConnector:
    """Connexion DTC JSON vers Sierra Chart."""

    def __init__(self, config: DTCConfig = None):
        self.cfg = config or DTCConfig()
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.lock = threading.Lock()
        self._recv_thread: Optional[threading.Thread] = None
        self._running = False
        self._recv_buffer = b""
        self._last_heartbeat = 0.0

        # OCO manuel (comme V1 — Sierra Chart OCOGroup pas fiable)
        self._oco_pairs: dict = {}       # {tp_cid: sl_cid, sl_cid: tp_cid}
        self._oco_processed: set = set() # Ordres déjà traités
        self._server_order_ids: dict = {} # {client_order_id: server_order_id}

        # P0-6 : Events pour attendre fill parent avant TP/SL
        self._parent_fill_events: dict = {}  # {parent_id: threading.Event}

        # Market data — prix temps reel par symbole
        self._last_prices: dict = {}    # {symbol: {"bid": 0, "ask": 0, "last": 0, "ts": 0}}
        self._md_request_ids: dict = {} # {request_id: symbol}

        # Callbacks
        self.on_fill: Optional[Callable] = None
        self.on_position_update: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None

    def connect(self) -> bool:
        """Connecte au serveur DTC de Sierra Chart."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.cfg.timeout_seconds)
            self.sock.connect((self.cfg.host, self.cfg.port))

            # Logon
            logon = {
                "Type": DTC_LOGON_REQUEST,
                "ProtocolVersion": 8,
                "Username": "",
                "Password": "",
                "HeartbeatIntervalInSeconds": self.cfg.heartbeat_interval_seconds,
                "ClientName": "MIA_Bot_V2",
            }
            self._send(logon)

            # Attendre la reponse
            response = self._recv()
            if response and response.get("Type") == DTC_LOGON_RESPONSE:
                if response.get("Result") == 1:  # Success
                    self.connected = True
                    self._running = True
                    # P0-3 : init heartbeat pour eviter is_alive=False au demarrage
                    self._last_heartbeat = time.time()
                    # Reset OCO state pour nouvelle session
                    self._oco_processed.clear()
                    # Thread recv
                    if self._recv_thread is None or not self._recv_thread.is_alive():
                        self._recv_thread = threading.Thread(
                            target=self._recv_loop, daemon=True)
                        self._recv_thread.start()
                    return True

            return False

        except Exception as e:
            logger.error(f"DTC connect error: {e}")
            with self.lock:
                self.connected = False
            return False

    def disconnect(self):
        """Deconnexion propre."""
        self._running = False
        with self.lock:
            self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def send_market_order(self, symbol: str, side: int, quantity: int = 1,
                           sl_price: float = 0, tp_price: float = 0,
                           trade_account: str = "Sim3") -> tuple:
        """
        Envoie un ordre market + bracket SL/TP (3 ordres separes).

        Returns:
            (parent_id, tp_cid, sl_cid) ou ("", "", "") si echec
        """
        if not self.connected:
            return ("", "", "")

        parent_id = f"MIA_P_{uuid.uuid4().hex[:8]}"
        child_side = SELL if side == BUY else BUY

        # P0-6 : creer event pour attendre fill parent
        parent_event = threading.Event()
        self._parent_fill_events[parent_id] = parent_event

        # 1. Parent MARKET
        self._send({
            "Type": DTC_MARKET_ORDER,
            "Symbol": symbol,
            "ClientOrderID": parent_id,
            "OrderType": MARKET,
            "BuySell": side,
            "Quantity": quantity,
            "TradeAccount": trade_account,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 1,
            "TimeInForce": 0,
        })

        # 2. Bracket TP/SL (si specifies)
        if tp_price > 0 and sl_price > 0:
            tp_cid = f"MIA_TP_{uuid.uuid4().hex[:8]}"
            sl_cid = f"MIA_SL_{uuid.uuid4().hex[:8]}"

            # P0-6 : attendre que le parent soit Filled (status=7) avec timeout 2s
            if not parent_event.wait(timeout=2.0):
                logger.warning(f"[DTC] Parent {parent_id} NOT FILLED in 2s — abort bracket")
                # Fix audit logs V2 22/04 : emit PARENT_FILL_TIMEOUT (avant silencieux)
                if _v2log:
                    try:
                        _v2log.emit("PARENT_FILL_TIMEOUT",
                                    order_id=parent_id, timeout=2.0)
                    except Exception:
                        pass
                self._parent_fill_events.pop(parent_id, None)
                # Tenter de cancel le parent au cas ou
                sid = self._server_order_ids.get(parent_id)
                if sid:
                    self._send({
                        "Type": DTC_CANCEL_ORDER,
                        "ClientOrderID": parent_id,
                        "ServerOrderID": sid,
                        "TradeAccount": trade_account,
                    })
                return ("", "", "")
            self._parent_fill_events.pop(parent_id, None)

            # TP LIMIT (pas d'OCOGroup1 — ne marche pas)
            self._send({
                "Type": DTC_MARKET_ORDER,
                "Symbol": symbol,
                "ClientOrderID": tp_cid,
                "OrderType": LIMIT,
                "BuySell": child_side,
                "Quantity": quantity,
                "Price1": float(tp_price),
                "TimeInForce": 0,
                "TradeAccount": trade_account,
                "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2,
            })

            time.sleep(0.2)

            # SL STOP
            self._send({
                "Type": DTC_MARKET_ORDER,
                "Symbol": symbol,
                "ClientOrderID": sl_cid,
                "OrderType": STOP,
                "BuySell": child_side,
                "Quantity": quantity,
                "Price1": float(sl_price),
                "StopPrice": float(sl_price),
                "TimeInForce": 0,
                "TradeAccount": trade_account,
                "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2,
            })

            # Enregistrer la paire OCO pour annulation manuelle
            self.register_oco_pair(tp_cid, sl_cid)

            logger.info(f"Bracket sent: parent={parent_id} "
                        f"TP={tp_cid}@{tp_price} SL={sl_cid}@{sl_price}")

            return (parent_id, tp_cid, sl_cid)

        return (parent_id, "", "")

    def cancel_order(self, order_id: str, trade_account: str = "Sim3") -> bool:
        """
        Annule un ordre par ClientOrderID + ServerOrderID.

        CRITIQUE : ServerOrderID est OBLIGATOIRE pour que Sierra Chart
        annule effectivement l'ordre. Sans lui, le cancel est ignore
        silencieusement. Valide en Sim3 le 02/04/2026.

        Double envoi par securite (le 2e est ignore si le 1er a marche).
        """
        if not self.connected:
            return False

        msg = {
            "Type": DTC_CANCEL_ORDER,
            "ClientOrderID": order_id,
            "TradeAccount": trade_account,
        }
        # ServerOrderID OBLIGATOIRE pour cancel effectif
        server_id = self._server_order_ids.get(order_id, "")
        if server_id:
            msg["ServerOrderID"] = server_id
        else:
            logger.warning(f"Cancel sans ServerOrderID: {order_id} — risque d'echec")

        self._send(msg)
        time.sleep(0.3)
        self._send(msg)  # Double envoi securite
        logger.info(f"Cancel sent (x2): CID={order_id} SID={server_id}")
        return True

    def subscribe_market_data(self, symbol: str, request_id: int = None):
        """
        Souscrit au market data temps reel pour un symbole.
        Apres souscription, _recv_loop met a jour _last_prices automatiquement.
        """
        if not self.connected:
            return
        rid = request_id or hash(symbol) % 10000
        self._md_request_ids[rid] = symbol
        self._last_prices[symbol] = {"bid": 0, "ask": 0, "last": 0, "ts": 0}
        self._send({
            "Type": DTC_MARKET_DATA_REQUEST,
            "RequestAction": 1,   # SUBSCRIBE
            "SymbolID": rid,
            "Symbol": symbol,
            "Exchange": "",
        })
        logger.info(f"Market data subscribe: {symbol} (rid={rid})")

    def get_current_price(self, symbol: str) -> float:
        """
        Retourne le dernier prix connu pour un symbole.
        Priorite : last > ask > bid. Retourne 0 si pas de donnee.
        """
        data = self._last_prices.get(symbol, {})
        price = data.get("last", 0) or data.get("ask", 0) or data.get("bid", 0)
        return price

    def get_bid_ask(self, symbol: str) -> tuple:
        """Retourne (bid, ask) pour un symbole."""
        data = self._last_prices.get(symbol, {})
        return data.get("bid", 0), data.get("ask", 0)

    def request_positions(self):
        """Demande les positions ouvertes."""
        if not self.connected:
            return
        self._send({"Type": DTC_POSITION_REQUEST})

    def request_open_orders(self):
        """Demande les ordres ouverts."""
        if not self.connected:
            return
        self._send({"Type": DTC_OPEN_ORDERS_REQUEST})

    def _send(self, msg: dict):
        """Envoie un message DTC JSON (format SC: JSON + null byte)."""
        with self.lock:
            if not self.sock:
                return
            try:
                data = json.dumps(msg).encode("utf-8") + b"\x00"
                self.sock.sendall(data)
            except Exception as e:
                logger.error(f"DTC send error: {e}")
                self.connected = False

    def _recv(self) -> Optional[dict]:
        """Recoit UN message DTC JSON (buffer persistant, readuntil \\x00)."""
        try:
            while True:
                # Verifier si un message complet est deja dans le buffer
                idx = self._recv_buffer.find(b'\x00')
                if idx >= 0:
                    raw = self._recv_buffer[:idx]
                    self._recv_buffer = self._recv_buffer[idx+1:]
                    if raw:
                        msg = json.loads(raw.decode('utf-8', 'ignore'))
                        if isinstance(msg, dict):
                            return msg
                    continue

                # Lire plus de donnees
                chunk = self.sock.recv(8192)
                if not chunk:
                    return None
                self._recv_buffer += chunk

        except json.JSONDecodeError as e:
            logger.warning(f"DTC JSON invalide: {e}")
            return None
        except socket.timeout:
            return None
        except Exception as e:
            logger.error(f"DTC recv error: {e}")
            with self.lock:
                self.connected = False
            return None

    def _recv_loop(self):
        """Boucle de reception en arriere-plan avec reconnexion auto."""
        reconnect_attempts = 0
        while self._running:
            try:
                msg = self._recv()
            except Exception as e:
                logger.error(f"DTC recv_loop error: {e}")
                with self.lock:
                    self.connected = False
                time.sleep(self.cfg.reconnect_delay_seconds)
                continue

            if msg is None:
                if not self._running:
                    break
                # Socket mort — tenter reconnexion
                with self.lock:
                    was_connected = self.connected
                    self.connected = False

                if was_connected:
                    logger.warning("[DTC] Connexion perdue — tentative de reconnexion")
                    # V2 log : DTC deconnecte (niveau ALERTE si reconnect possible,
                    # CRITIQUE si pendant session — caller peut distinguer)
                    if _v2log:
                        _v2log.emit("DTC_DISCONNECT", reason="socket_dead_trying_reconnect")
                    reconnect_attempts = 0

                if reconnect_attempts < 10:
                    reconnect_attempts += 1
                    # Fermer l'ancien socket
                    try:
                        if self.sock:
                            self.sock.close()
                    except Exception:
                        pass
                    self.sock = None

                    delay = min(self.cfg.reconnect_delay_seconds * reconnect_attempts, 30)
                    logger.info(f"[DTC] Reconnect tentative {reconnect_attempts} dans {delay}s")
                    time.sleep(delay)

                    # Reconnect (sans recreer le thread)
                    try:
                        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        self.sock.settimeout(self.cfg.timeout_seconds)
                        self.sock.connect((self.cfg.host, self.cfg.port))
                        logon = {
                            "Type": DTC_LOGON_REQUEST,
                            "ProtocolVersion": 8,
                            "Username": "", "Password": "",
                            "HeartbeatIntervalInSeconds": self.cfg.heartbeat_interval_seconds,
                            "ClientName": "MIA_Bot_V2",
                        }
                        self._send(logon)
                        response = self._recv()
                        if response and response.get("Type") == DTC_LOGON_RESPONSE and response.get("Result") == 1:
                            with self.lock:
                                self.connected = True
                            self._last_heartbeat = time.time()
                            # V2 log : reconnect succes
                            if _v2log:
                                _v2log.emit("DTC_RECONNECT", attempts=reconnect_attempts)
                            reconnect_attempts = 0
                            logger.info("[DTC] Reconnecte avec succes")
                    except Exception as e:
                        logger.error(f"[DTC] Reconnect echec: {e}")
                else:
                    logger.error("[DTC] Max reconnect atteint — abandon")
                    # V2 log : deconnexion pendant session trading = CRITIQUE
                    if _v2log:
                        _v2log.emit("DTC_DISCONNECT_SESSION", reason="max_reconnect_attempts")
                    break
                continue
            else:
                reconnect_attempts = 0  # reset sur message valide

            msg_type = msg.get("Type", 0)

            if msg_type == DTC_HEARTBEAT:
                self._last_heartbeat = time.time()
                self._send({"Type": DTC_HEARTBEAT})

            elif msg_type == DTC_ORDER_UPDATE:
                self._handle_order_update(msg)

            elif msg_type == DTC_POSITION_UPDATE:
                if self.on_position_update:
                    self.on_position_update(msg)

            elif msg_type in (DTC_MARKET_DATA_SNAPSHOT, DTC_MARKET_DATA_UPDATE):
                self._handle_market_data(msg)

            elif msg_type == DTC_MARKET_DATA_REJECT:
                sym_id = msg.get("SymbolID", 0)
                sym = self._md_request_ids.get(sym_id, "?")
                logger.warning(f"Market data reject: {sym} — {msg.get('RejectText','')}")

    def _handle_order_update(self, msg: dict):
        """
        Traite un update d'ordre (fill, cancel, etc.).
        Gere l'OCO manuel : quand TP ou SL est filled, annule l'opposé.
        """
        try:
            order_status = msg.get("OrderStatus", 0)
            client_order_id = msg.get("ClientOrderID", "")
            server_order_id = msg.get("ServerOrderID", "")
            fill_price = (msg.get("AverageFillPrice", 0) or
                         msg.get("LastFillPrice", 0) or
                         msg.get("Price1", 0))

            # Tracker le ServerOrderID pour cancel ulterieur
            if client_order_id and server_order_id:
                self._server_order_ids[client_order_id] = server_order_id

            # Status 7 = Filled (PAS 2 — 2 = Open/Accepted)
            # Valide en Sim3 02/04/2026 : status passe 2→4→7
            is_filled = (order_status == 7 or
                         order_status == "Filled" or
                         (msg.get("FilledQuantity", 0) > 0 and
                          order_status not in (2, "Open")))

            # Fix audit logs V2 22/04 : detecter fill partiel (status != 7 MAIS
            # FilledQuantity > 0 ET < OrderQuantity). Bug silencieux classique
            # — si broker file 2/3 micros, bot place SL/TP pour 3 lots alors
            # que position = 2 → SL hit partiel → orphan.
            filled_qty = msg.get("FilledQuantity", 0)
            expected_qty = msg.get("OrderQuantity", 0)
            if (filled_qty > 0 and expected_qty > 0 and
                    filled_qty < expected_qty and not is_filled):
                if _v2log:
                    try:
                        pct = 100.0 * filled_qty / expected_qty
                        _v2log.emit("ORDER_PARTIAL_FILL",
                                    sym=msg.get("Symbol", ""),
                                    filled=filled_qty,
                                    expected=expected_qty,
                                    pct=pct,
                                    order_id=client_order_id)
                    except Exception:
                        pass

            if is_filled and fill_price and fill_price > 100:
                # P0-6 : signaler l'event parent si c'est un parent order
                if client_order_id.startswith("MIA_P_") and client_order_id in self._parent_fill_events:
                    self._parent_fill_events[client_order_id].set()

                # Notifier le bot du fill
                if self.on_fill:
                    fill = OrderFill(
                        order_id=client_order_id,
                        symbol=msg.get("Symbol", ""),
                        side=msg.get("BuySell", 0),
                        fill_price=fill_price,
                        quantity=msg.get("FilledQuantity", 0) or msg.get("OrderQuantity", 0),
                        timestamp=time.time(),
                        is_filled=True,
                    )
                    self.on_fill(fill)

                # OCO MANUEL : annuler l'ordre opposé (comme V1)
                if client_order_id in self._oco_pairs:
                    if client_order_id not in self._oco_processed:
                        opposite_cid = self._oco_pairs[client_order_id]
                        self._oco_processed.add(client_order_id)
                        self._oco_processed.add(opposite_cid)

                        exit_type = "TP" if "_TP_" in client_order_id else "SL"
                        logger.info(f"OCO: {exit_type} {client_order_id} filled @ {fill_price}"
                                    f" → Cancel {opposite_cid}")

                        # Annuler l'ordre oppose immediatement
                        self.cancel_order(opposite_cid)

                        # Securite : verifier apres 1s que le cancel a marche
                        threading.Timer(1.0, self._verify_cancel,
                                        args=[opposite_cid]).start()

        except Exception as e:
            logger.error(f"DTC order update error: {e}")

    def _verify_cancel(self, order_id: str):
        """Verifie qu'un ordre a bien ete annule, re-cancel sinon.

        v1.4.3 (22/04) R2 code-reviewer : ce re-cancel est le dernier rempart
        contre orphan OCO (DNA V1 02/04 bug). Si malgre 2 cancels + verify
        un fill arrive pour cet order_id plus tard, c'est un orphan reel.

        [TODO P3] Vraie detection orphan necessite :
          1. Apres cancel, demander Open Orders (Type 300) au broker
          2. Si order_id present dans response → cancel has not worked
          3. Emettre OCO_ORPHAN_DETECTED CRITIQUE + retry N fois
        Pour l'instant : emit ALERTE "cancel incertain" (re-cancel en cours).
        """
        server_id = self._server_order_ids.get(order_id, "")
        if server_id:
            # Re-envoyer le cancel par securite
            msg = {
                "Type": DTC_CANCEL_ORDER,
                "ClientOrderID": order_id,
                "ServerOrderID": server_id,
                "TradeAccount": "Sim3",
            }
            self._send(msg)
            logger.info(f"Verify cancel (securite): {order_id} SID={server_id}")
            # V2 log : cancel incertain, signal de vigilance operateur
            if _v2log:
                # CANCEL_FAILED_RETRY : re-cancel lance car cancel initial incertain
                _v2log.emit("CANCEL_FAILED_RETRY",
                            order_id=order_id, retry_count=2)
                # OCO_ORPHAN_DETECTED conserve pour compat traceabilite cascade
                _v2log.emit("OCO_ORPHAN_DETECTED", order_id=order_id)

    def _handle_market_data(self, msg: dict):
        """Traite un snapshot ou update de market data."""
        sym_id = msg.get("SymbolID", 0)
        symbol = self._md_request_ids.get(sym_id)
        if not symbol:
            return

        data = self._last_prices.setdefault(symbol, {"bid": 0, "ask": 0, "last": 0, "ts": 0})

        # Mettre a jour seulement les champs presents (updates partiels)
        bid = msg.get("BidPrice", 0)
        ask = msg.get("AskPrice", 0)
        last = msg.get("LastTradePrice", 0)

        if bid and bid > 0:
            data["bid"] = bid
        if ask and ask > 0:
            data["ask"] = ask
        if last and last > 0:
            data["last"] = last
        data["ts"] = time.time()

    def register_oco_pair(self, tp_cid: str, sl_cid: str):
        """Enregistre une paire OCO manuelle (TP ↔ SL)."""
        self._oco_pairs[tp_cid] = sl_cid
        self._oco_pairs[sl_cid] = tp_cid
        logger.info(f"OCO pair registered: {tp_cid} <-> {sl_cid}")

    def send_heartbeat(self):
        """Envoie un heartbeat manuellement."""
        self._send({"Type": DTC_HEARTBEAT})

    @property
    def is_alive(self) -> bool:
        """Verifie si la connexion est vivante."""
        if not self.connected:
            return False
        if time.time() - self._last_heartbeat > self.cfg.heartbeat_interval_seconds * 3:
            return False
        return True
