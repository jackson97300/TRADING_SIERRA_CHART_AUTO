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
        # 04/05 Etape 2 (anti-slippage) : capture LastFillPrice parent pour slip metric
        # + reprice eventuel SL/TP. Lu par send_market_order apres parent_event.wait.
        self._parent_fill_prices: dict = {}  # {parent_id: fill_price}  (pop apres usage interne)
        # 12/05 FIX RACE CONDITION entry_price (cf INCIDENT_LOG 2026-05-12 03:30) :
        # _last_fill_prices conserve le fill_price APRES pop interne, accessible aux
        # bots callers via get_last_fill_price(parent_id). Resout le bug entry_price =
        # signal_price faux quand drift signal<->fill important (Bot 3 V4 stale 18min).
        self._last_fill_prices: dict = {}  # {parent_id: fill_price} (persistent, non-pop)
        self._last_fill_lock = threading.Lock()
        # 04/05 H5 : RequestID counter pour Type 203 cancel (projet 1 fait pareil).
        self._request_id_counter: int = 1
        # 04/05 H6 (CAUSE RACINE ORPHELINS BOT 3) : tracker trade_account par CID.
        # Bug avant fix : OCO auto cancel utilisait default "Sim3" alors que Bot 3
        # = Sim1 -> SC ignore silencieusement -> orphelins. Solution : capturer le TA
        # depuis msg ORDER_UPDATE et le passer aux cancels.
        self._order_trade_accounts: dict = {}  # {cid: trade_account}
        # 01/05 ROLLBACK : tentative fix CANCEL_FAILED_RETRY via _cancelled_order_ids
        # set. Soupcon d'avoir cause Bot 1 orphan post-fix (Jackson observed). Le faux
        # positif log etait inoffensif (juste bruyant). On preserve _verify_cancel
        # comportement original (re-cancel + log). Cf BACKLOG : Type 300 query Open Orders.
        self._cancelled_order_ids: set = set()  # vestigial, vide

        # P0-6 : Events pour attendre fill parent avant TP/SL
        self._parent_fill_events: dict = {}  # {parent_id: threading.Event}

        # P0-A (06/05) : lock pour serialiser les requests Type 300 OPEN_ORDERS.
        # 2 callers concurrents (boot recovery + check_timeout etape 6.5/9) peuvent
        # s'ecraser sur self._pending_open_orders_query -> corruption / events perdus.
        self._open_orders_query_lock = threading.Lock()

        # Market data — prix temps reel par symbole
        self._last_prices: dict = {}    # {symbol: {"bid": 0, "ask": 0, "last": 0, "ts": 0}}
        self._md_request_ids: dict = {} # {request_id: symbol}

        # Callbacks
        self.on_fill: Optional[Callable] = None
        self.on_position_update: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        # FIX 06/05 soir (BUG STRUCTUREL Bot 3 — Jackson "PAS DE DETTE") :
        # `on_order_update` callback expose le msg DICT brut (Type 301 ORDER_UPDATE)
        # pour permettre aux callers de parser eux-memes (cid_type routing, status
        # intermediaire, etc). Bot 3 hookera dessus pour capturer fills TP/SL/Type 209.
        # Bot 1/2 continuent a utiliser `on_fill(OrderFill)` — comportement inchange.
        # Avant ce fix : Bot 3 assignait self.dtc.on_order_update mais l'attribut
        # n'existait pas dans le connector → silently ignore → 100% des fills perdus.
        self.on_order_update: Optional[Callable] = None

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
                    self._cancelled_order_ids.clear()  # rollback 01/05 — vestigial
                    # Thread recv — P1.2 (06/05) : daemon=False + drain au disconnect
                    # pour ne pas tuer le thread net pendant le traitement d'un fill TP/SL.
                    # Sans ce fix, SIGTERM watchdog → main exit → daemon thread mort
                    # avant que _handle_order_update ait consume le 301 → OCO manuel rate
                    # → orphelin. Le drain est fait dans disconnect() (join timeout 3s).
                    if self._recv_thread is None or not self._recv_thread.is_alive():
                        self._recv_thread = threading.Thread(
                            target=self._recv_loop, daemon=False, name="DTC_recv_loop")
                        self._recv_thread.start()
                    return True

            return False

        except Exception as e:
            logger.error(f"DTC connect error: {e}")
            with self.lock:
                self.connected = False
            return False

    def disconnect(self, drain_timeout: float = 3.0):
        """Deconnexion propre.

        P1.2 (06/05) : drain le _recv_loop avant exit pour eviter de couper
        au milieu d'un Type 301 (TP/SL fill) qui arrive juste avant SIGTERM.
        Sans drain, OCO manuel ne s'execute pas → orphelin.

        Args:
            drain_timeout : seconds max d'attente du drain. 0 = pas de drain (pour
                             tests / cas catastrophiques). Default 3.0 sec.
        """
        self._running = False
        with self.lock:
            self.connected = False
        # Fermer le socket APRES avoir flag _running=False : le _recv_loop sortira
        # naturellement (via msg=None de _recv) au prochain tour.
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        # Drain du recv thread si vivant et drain_timeout > 0
        if drain_timeout > 0 and self._recv_thread is not None and self._recv_thread.is_alive():
            try:
                self._recv_thread.join(timeout=drain_timeout)
                if self._recv_thread.is_alive():
                    logger.warning(f"[DTC] recv_thread drain timeout ({drain_timeout}s) — thread still alive")
                    if _v2log:
                        try:
                            _v2log.emit("DTC_DISCONNECT_DRAIN_TIMEOUT", drain_sec=drain_timeout)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"[DTC] disconnect drain error: {e}")

    def send_market_order(self, symbol: str, side: int, quantity: int = 1,
                           sl_price: float = 0, tp_price: float = 0,
                           trade_account: str = "Sim3",
                           signal_ref_price: float = 0,
                           sl_ticks: int = 0,
                           tp_ticks: int = 0,
                           tick_size: float = 0.25,
                           auto_reprice_threshold_ticks: int = 5) -> tuple:
        """
        Envoie un ordre market + bracket SL/TP (3 ordres separes).

        04/05 Etape 2 anti-slippage long terme (Plan agent) :
          - Si signal_ref_price > 0 ET sl_ticks/tp_ticks > 0 : on capture le
            LastFillPrice du parent apres ACK et on calcule le slip vs ref.
          - Si slip > auto_reprice_threshold_ticks : on RECALCULE sl/tp depuis
            le fill_price reel AVANT d'envoyer les childs.
          - Pattern conforme FIX B-1 (02/05) : on intervient AVANT envoi childs,
            zone non couverte par l'interdiction de recalc post-childs.
          - Emet BRACKET_SLIP_METRIC systematiquement (slip mesure + ref_source).

        Args (compat retro Bot 1 V1 inchangee si nouveaux params absents) :
            sl_price, tp_price : prix absolus calcules par le caller (depuis ref).
            signal_ref_price : prix de reference utilise par le caller pour calc.
                               Si 0, pas de slip metric, pas de reprice.
            sl_ticks, tp_ticks : distances en ticks (utilises pour reprice).
                                  Si 0, pas de reprice possible (fallback prix donnes).
            tick_size : pour calcul slip + reprice. Default 0.25 (ES/NQ).
            auto_reprice_threshold_ticks : seuil declenchement reprice. 5 par default.

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

        # 04/05 H6 : pre-register trade_account pour parent (TP/SL ajoutes plus bas)
        self._order_trade_accounts[parent_id] = trade_account

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
                self._parent_fill_prices.pop(parent_id, None)
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

            # 04/05 Etape 2 : capture fill_price + slip metric + reprice eventuel
            fill_price = self._parent_fill_prices.pop(parent_id, 0.0)
            # 12/05 FIX : persister fill_price dans _last_fill_prices pour callers
            # (Bot 1/2 V6/3) qui appellent get_last_fill_price() apres return.
            # Resout race condition _handle_dtc_fill is_parent (code mort).
            # FIX R1 code-reviewer : LRU cap 1000 entries pour eviter fuite memoire
            # (worst case 100 trades/jour x 365j = 36500 entries ~2.9MB/an, mais
            # propre = cap explicite). Eviction FIFO de la plus ancienne.
            if fill_price > 0:
                with self._last_fill_lock:
                    if len(self._last_fill_prices) >= 1000:
                        # Pop oldest entry (FIFO eviction)
                        try:
                            oldest_key = next(iter(self._last_fill_prices))
                            self._last_fill_prices.pop(oldest_key, None)
                        except StopIteration:
                            pass
                    self._last_fill_prices[parent_id] = fill_price
            slip_t = 0.0
            reprice_done = False
            if signal_ref_price > 0 and fill_price > 0:
                slip_t = abs(fill_price - signal_ref_price) / tick_size
                # Emit slip metric systematique (tous les trades)
                if _v2log:
                    try:
                        _v2log.emit("BRACKET_SLIP_METRIC",
                                    sym=symbol, parent_id=parent_id,
                                    signal_ref_price=signal_ref_price,
                                    fill_price=fill_price,
                                    slip_ticks=round(slip_t, 1),
                                    side="LONG" if side == BUY else "SHORT")
                    except Exception:
                        pass
                # Reprice si slip excessif ET on a les ticks pour recalculer
                if slip_t > auto_reprice_threshold_ticks and sl_ticks > 0 and tp_ticks > 0:
                    side_str = "LONG" if side == BUY else "SHORT"
                    try:
                        from CORE.execution.tpsl_pricer import calc_bracket_prices
                    except ImportError:
                        from execution.tpsl_pricer import calc_bracket_prices  # type: ignore
                    new_sl, new_tp = calc_bracket_prices(
                        side_str, fill_price, sl_ticks, tp_ticks, tick_size
                    )
                    logger.info(
                        f"[DTC] AUTO_REPRICE slip={slip_t:.1f}t "
                        f"signal_ref={signal_ref_price} fill={fill_price} "
                        f"old_sl={sl_price} new_sl={new_sl} "
                        f"old_tp={tp_price} new_tp={new_tp}"
                    )
                    if _v2log:
                        try:
                            _v2log.emit("BRACKET_REPRICE",
                                        sym=symbol, parent_id=parent_id,
                                        slip_ticks=round(slip_t, 1),
                                        signal_ref=signal_ref_price,
                                        fill_price=fill_price,
                                        old_sl=sl_price, new_sl=new_sl,
                                        old_tp=tp_price, new_tp=new_tp)
                        except Exception:
                            pass
                    sl_price = new_sl
                    tp_price = new_tp
                    reprice_done = True

            # 04/05 H6 + race condition fix : pre-register TA + OCO pair AVANT envoi.
            # Sinon, si TP fill ultra-rapide (596ms observe NQ), le _handle_order_update
            # voit le fill avant que _order_trade_accounts/oco_pairs soient peuples
            # -> cancel auto OCO echoue silencieusement.
            self._order_trade_accounts[tp_cid] = trade_account
            self._order_trade_accounts[sl_cid] = trade_account
            self.register_oco_pair(tp_cid, sl_cid)

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

            logger.info(f"Bracket sent: parent={parent_id} "
                        f"TP={tp_cid}@{tp_price} SL={sl_cid}@{sl_price}")

            return (parent_id, tp_cid, sl_cid)

        return (parent_id, "", "")

    def get_last_fill_price(self, parent_id: str) -> float:
        """Retourne le fill_price reel broker (AverageFillPrice DTC) du parent ORDER.

        12/05 FIX (cf INCIDENT_LOG 2026-05-12 03:30) : appele par les bots APRES
        send_market_order() return pour obtenir le fill_price reel et stocker
        pos['entry_price'] = fill_price. Resout la race condition ou la branche
        is_parent de _handle_dtc_fill etait code mort (lookup _order_to_symbol
        vide car registration vient apres send_market_order return).

        Args:
            parent_id: ClientOrderID du parent (returne par send_market_order).

        Returns:
            fill_price: prix d'execution reel broker, ou 0.0 si non disponible
            (timeout, parent_id inconnu, fill_price=0 dans ORDER_UPDATE).

        Le caller doit gerer le cas fill_price=0.0 (fallback signal_price).
        """
        with self._last_fill_lock:
            return self._last_fill_prices.get(parent_id, 0.0)

    def request_position_blocking(self, symbol_contract: str,
                                    trade_account: str = "Sim3",
                                    timeout: float = 3.0) -> Optional[int]:
        """Demande la position broker via Type 305 + wait response Type 306.

        Bloquant avec timeout 3s. Retourne signed qty (>0=long, <0=short, 0=flat)
        ou None si timeout / pas connecte.

        FIX 30/04 (Jackson "pas de dette") : R3 review code-reviewer #1 — eviter
        FLIP si partial fill broker. Pattern flatten_nq_sim2.py:41-47.

        Args:
            symbol_contract : ex "ESM26-CME"
            trade_account : compte broker
            timeout : seconds max wait pour reponse Type 306

        Returns:
            signed qty broker, ou None si pas de reponse / pas connecte
        """
        # P2.1 (06/05) : delegue a request_position_with_avg_price puis ne retourne que qty
        # (compat retro avec les ~10 callers existants — Bot 1, Bot 2, _bot3_check_timeout).
        result = self.request_position_with_avg_price(symbol_contract, trade_account, timeout)
        if result is None:
            return None
        return result[0]

    def request_position_with_avg_price(self, symbol_contract: str,
                                          trade_account: str = "Sim3",
                                          timeout: float = 3.0) -> Optional[tuple]:
        """P2.1 (06/05) : version retournant (qty, avg_price) pour reconstruire entry_price reel
        au boot recovery. Pattern Type 305 + 306 (AverageFillPrice ou AveragePrice).

        Returns:
            (signed_qty, avg_fill_price) ou None si timeout / pas connecte.
            avg_fill_price = 0.0 si broker n'envoie pas le champ (defensif).
        """
        if not self.connected:
            return None

        # Setup callback temporaire avec Event pour capturer la reponse
        position_event = threading.Event()
        position_holder = {"qty": None, "avg_price": 0.0}
        original_callback = self.on_position_update

        def temp_callback(msg):
            try:
                msg_sym = str(msg.get("Symbol", ""))
                if symbol_contract == msg_sym or symbol_contract in msg_sym or msg_sym in symbol_contract:
                    qty = msg.get("Quantity", 0)
                    # SC envoie tantot AverageFillPrice tantot AveragePrice (DTC spec strict
                    # = AveragePrice, mais SC populate les 2). Defensif sur les 2.
                    avg_p = msg.get("AverageFillPrice") or msg.get("AveragePrice") or 0.0
                    if qty is not None:
                        position_holder["qty"] = int(qty)
                        try:
                            position_holder["avg_price"] = float(avg_p) if avg_p else 0.0
                        except (TypeError, ValueError):
                            position_holder["avg_price"] = 0.0
                        position_event.set()
            except (TypeError, ValueError):
                pass
            if original_callback:
                try:
                    original_callback(msg)
                except Exception:
                    pass

        self.on_position_update = temp_callback
        try:
            self._send({
                "Type": DTC_POSITION_REQUEST,  # 305
                "RequestID": int(time.time() * 1000) % 100000,
                "TradeAccount": trade_account,
            })
            if position_event.wait(timeout=timeout):
                return (position_holder["qty"], position_holder["avg_price"])
            return None
        finally:
            self.on_position_update = original_callback

    def request_open_orders_blocking(self, trade_account: str = "Sim3",
                                       symbol_filter: Optional[str] = None,
                                       timeout: float = 3.0) -> Optional[list]:
        """P0.1 (06/05) : query Type 300 REQUEST_OPEN_ORDERS, collecte 301 jusqu'a NoOrders=1.

        Critique pour anti-orphelin :
          - Au boot recovery : reconstitue tp_cid/sl_cid/sl_price/tp_cap_price reels
            depuis Working orders broker (sinon pos placeholder = None partout).
          - Avant Type 209/210 flatten : identifier les Working orders a cancel via 203
            (Type 209 ne cancel PAS les working orders sans position — observe 06/05).
          - Apres flatten : verifier 0 working orders restants, sinon BOT3_ORPHAN_DETECTED.

        Args:
            trade_account : compte broker (Sim1/Sim2/Sim3)
            symbol_filter : si fourni, ne retourne que les ordres matching ce contract (ex "ESM26-CME")
            timeout : seconds max wait pour reponses 301 (cumul, pas par msg)

        Returns:
            list[dict] avec champs au minimum :
              {ClientOrderID, ServerOrderID, Symbol, OrderStatus, BuySell,
               OrderType, Price1, StopPrice, Quantity, TradeAccount}
            Status pertinents : 2 (Open/Accepted), 4 (Working). Filles 7 + Cancelled 8 ignores.
            None si timeout / pas connecte.

        Note Sierra Chart : Type 300 envoie 1 message Type 301 par order, puis un dernier
        avec NoOrders=1. On collecte jusqu'a NoOrders ou jusqu'a expiration timeout.
        """
        if not self.connected:
            return None

        # P0-A (06/05) : serialiser les queries Type 300 concurrentes.
        # Le sentinel _pending_open_orders_query etait un attribut sur self —
        # 2 callers parallele s'ecrasaient mutuellement (events perdus, dict corrompu).
        # Tentative acquire non-bloquant — si une autre query est en cours, on
        # attend max `timeout` puis abandonne (None) plutot que de bloquer
        # le caller qui peut etre dans un hot path (etape 6.5 timeout).
        if not self._open_orders_query_lock.acquire(timeout=timeout):
            if _v2log:
                try:
                    _v2log.emit("OPEN_ORDERS_QUERY_LOCK_TIMEOUT",
                                trade_account=trade_account)
                except Exception:
                    pass
            return None

        # State partage entre callback et caller
        orders_collected: list = []
        completion_event = threading.Event()
        rid = self._request_id_counter
        self._request_id_counter += 1

        # Le _recv_loop appelle deja _handle_order_update sur Type 301.
        # On tape sur ce dispatch via un attribut temporaire que _handle_order_update
        # consultera. Pattern non-invasif (pas de modif du _recv_loop).
        # Sous lock : un seul query a la fois -> pas de corruption.
        sentinel_attr = "_pending_open_orders_query"
        setattr(self, sentinel_attr, {
            "request_id": rid,
            "trade_account": trade_account,
            "symbol_filter": symbol_filter,
            "orders": orders_collected,
            "event": completion_event,
        })

        try:
            # P0-C (06/05) : NE PAS envoyer "Symbol" dans le Type 300.
            # La spec DTC officielle (s_OpenOrdersRequest) ne reconnait que
            # RequestID + TradeAccount + ServerOrderID (optionnel). Ajouter Symbol
            # peut faire que SC retourne 0 orders silencieusement (interpretation
            # stricte). On filter cote client dans _handle_order_update + ici en
            # post-process pour garantir le bon scope.
            req = {
                "Type": DTC_OPEN_ORDERS_REQUEST,  # 300
                "RequestID": rid,
                "TradeAccount": trade_account,
            }
            self._send(req)

            # Attente que NoOrders=1 set le flag, OU timeout
            if completion_event.wait(timeout=timeout):
                # Dedup par ClientOrderID au cas ou SC envoie des updates multiples
                seen = set()
                deduped = []
                for o in orders_collected:
                    cid = o.get("ClientOrderID", "")
                    if cid and cid not in seen:
                        seen.add(cid)
                        deduped.append(o)
                return deduped
            # Timeout : retourne ce qu'on a collecte (peut etre incomplet mais utile)
            logger.warning(f"[DTC] request_open_orders timeout ({timeout}s) "
                           f"— returning {len(orders_collected)} partial orders")
            if _v2log:
                try:
                    _v2log.emit("OPEN_ORDERS_QUERY_TIMEOUT",
                                trade_account=trade_account, partial_count=len(orders_collected))
                except Exception:
                    pass
            return list(orders_collected) if orders_collected else None
        finally:
            # Nettoyer le sentinel meme en cas d'exception, puis release lock
            try:
                delattr(self, sentinel_attr)
            except AttributeError:
                pass
            try:
                self._open_orders_query_lock.release()
            except RuntimeError:
                pass  # Lock pas detenu (ex: si exception avant acquire reussi)

    def send_close_market(self, symbol: str, side: int, quantity: int,
                           trade_account: str = "Sim3") -> str:
        """Envoie un MARKET CLOSE (Type 208 + OpenCloseTrade=2).

        Pas de brackets associes (ferme une position existante). Utilise par
        _check_exit_dtc Bot 2 quand le live price touche TP/SL mais que le
        broker Sim2 ne fait pas fill (low volume Asia).

        Args:
            symbol : ex "ESM26-CME"
            side : BUY (1) ou SELL (2) — DOIT etre l'opposite de la position courante
            quantity : nombre de contrats (= n_micros position)
            trade_account : compte broker

        Returns:
            close_id : ClientOrderID genere ou "" si pas connecte

        FIX 30/04 (Jackson) : avant ce patch, _check_exit_dtc cancellait les
        brackets mais n'envoyait pas de market close → position orpheline
        si Sim2 sluggish (cas observe nuit du 30/04 sur ES SHORT 7197.50).
        """
        if not self.connected:
            return ""
        close_id = f"MIA_CLOSE_{uuid.uuid4().hex[:8]}"
        self._send({
            "Type": DTC_MARKET_ORDER,  # 208
            "Symbol": symbol,
            "ClientOrderID": close_id,
            "OrderType": MARKET,  # 1
            "BuySell": side,
            "Quantity": quantity,
            "TradeAccount": trade_account,
            "IsAutomatedOrder": 1,
            "OpenCloseTrade": 2,  # CLOSE
            "TimeInForce": 0,
        })
        logger.info(f"Close market sent: cid={close_id} side={side} qty={quantity} {symbol}")
        return close_id

    def cancel_order(self, order_id: str, trade_account: str = "Sim3") -> bool:
        """
        Annule un ordre par ClientOrderID + ServerOrderID.

        CRITIQUE : ServerOrderID est OBLIGATOIRE pour que Sierra Chart
        annule effectivement l'ordre. Sans lui, le cancel est ignore
        silencieusement. Valide en Sim3 le 02/04/2026.

        ROLLBACK 29/04 soir (verdict code-reviewer NOGO sur retry bloquant) :
        retirer le `time.sleep(1.0)` qui bloquait le `_recv_loop` thread,
        garantissant que le SID ne pouvait JAMAIS etre resolu pendant
        l'attente (le seul thread capable de peupler `_server_order_ids`
        etait endormi). Le mecanisme `_verify_cancel` Timer ligne 604 fait
        deja le retry SID 1s plus tard de maniere non-bloquante : si le
        SID est maintenant disponible, re-cancel avec SID. C'est le bon
        endroit pour la resolution tardive.

        Double envoi par securite (le 2e est ignore si le 1er a marche),
        avec re-check SID entre les deux envois pour capter un
        ORDER_UPDATE qui arriverait dans la fenetre 0.3s SANS bloquer.
        """
        if not self.connected:
            return False

        server_id = self._server_order_ids.get(order_id, "")
        # 04/05 H5 : RequestID requis pour SC Sim (projet 1 confirme le faisait).
        rid = self._request_id_counter
        self._request_id_counter += 1
        msg = {
            "Type": DTC_CANCEL_ORDER,
            "RequestID": rid,
            "ClientOrderID": order_id,
            "TradeAccount": trade_account,
        }
        if server_id:
            msg["ServerOrderID"] = server_id
        else:
            logger.warning(f"Cancel sans ServerOrderID: {order_id} — risque d'echec")

        self._send(msg)
        time.sleep(0.3)
        # Re-check SID entre les 2 envois (capter ORDER_UPDATE qui arrive
        # dans la fenetre 0.3s entre les 2 sends sans bloquer le thread).
        if not server_id:
            server_id = self._server_order_ids.get(order_id, "")
            if server_id:
                msg["ServerOrderID"] = server_id
                logger.info(f"Cancel SID resolved between sends: {order_id} -> {server_id}")
        # Nouveau RequestID pour le 2eme envoi (projet 1 incremente a chaque envoi)
        msg["RequestID"] = self._request_id_counter
        self._request_id_counter += 1
        self._send(msg)  # Double envoi securite
        logger.info(f"Cancel sent (x2 with RequestID): CID={order_id} SID={server_id} RID={rid}")
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

        FIX 06/05 soir (Jackson "PAS DE DETTE") : appel callback on_order_update
        EN AMONT pour permettre aux consumers (Bot 3) de router le msg DICT brut
        avant le traitement interne (parent_event, OCO, on_fill). Le callback
        recoit TOUS les Type 301 (status 2/4/7/8), c'est au consumer de filtrer.
        Pattern non-invasif : si callback throw, on log mais continue le flow normal.
        """
        # FIX 06/05 soir : callback on_order_update AVANT tout traitement interne.
        # Critique pour Bot 3 qui a besoin de cid_type routing (parent/tp/sl/flatten).
        # Try/except defensif : un crash callback ne doit JAMAIS casser le flow DTC.
        if self.on_order_update is not None:
            try:
                self.on_order_update(msg)
            except Exception as e:
                logger.error(f"on_order_update callback error: {e}")
                # Pas de re-raise : le callback ne doit pas casser _recv_loop.
                # _v2log si dispo pour traceabilite
                if _v2log:
                    try:
                        _v2log.emit("ON_ORDER_UPDATE_CALLBACK_ERR",
                                    cid=str(msg.get("ClientOrderID", ""))[:30],
                                    err=str(e)[:200])
                    except Exception:
                        pass

        try:
            order_status = msg.get("OrderStatus", 0)
            client_order_id = msg.get("ClientOrderID", "")
            server_order_id = msg.get("ServerOrderID", "")

            # P0.1 (06/05) : si une query Type 300 OPEN_ORDERS est en cours, collecte
            # les Type 301 working orders (status 2/4) dans le buffer dedie + detecte
            # NoOrders=1 (signal de fin) pour set l'event de completion.
            pending_query = getattr(self, "_pending_open_orders_query", None)
            if pending_query is not None:
                try:
                    no_orders = bool(msg.get("NoOrders", False) or msg.get("NoOrders", 0))
                    msg_ta = msg.get("TradeAccount", "")
                    msg_sym = str(msg.get("Symbol", ""))
                    sym_filter = pending_query.get("symbol_filter") or ""
                    # Si SC indique fin de stream → set event
                    if no_orders:
                        pending_query["event"].set()
                    elif client_order_id and order_status in (2, 4, "Open", "Working"):
                        ta_match = (not pending_query.get("trade_account")
                                    or msg_ta == pending_query["trade_account"])
                        sym_match = (not sym_filter
                                     or sym_filter == msg_sym
                                     or sym_filter in msg_sym
                                     or msg_sym in sym_filter)
                        if ta_match and sym_match:
                            pending_query["orders"].append({
                                "ClientOrderID": client_order_id,
                                "ServerOrderID": server_order_id,
                                "Symbol": msg_sym,
                                "OrderStatus": order_status,
                                "BuySell": msg.get("BuySell", 0),
                                "OrderType": msg.get("OrderType", 0),
                                "Price1": msg.get("Price1", 0) or 0,
                                "StopPrice": msg.get("StopPrice", 0) or 0,
                                "Quantity": msg.get("OrderQuantity") or msg.get("Quantity") or 0,
                                "TradeAccount": msg_ta,
                                "OpenCloseTrade": msg.get("OpenCloseTrade", 0),
                            })
                except Exception:
                    pass  # Toute exception ici NE doit PAS casser le flow normal _handle_order_update
            # FIX 29/04 : `or 0` au lieu de default param (defensif si SC
            # envoie "AverageFillPrice": null sur les ORDER_UPDATE intermediaires).
            fill_price = (msg.get("AverageFillPrice") or
                         msg.get("LastFillPrice") or
                         msg.get("Price1") or 0)

            # Tracker le ServerOrderID pour cancel ulterieur
            if client_order_id and server_order_id:
                self._server_order_ids[client_order_id] = server_order_id
            # 04/05 H6 : tracker TradeAccount pour cancels OCO/timeout corrects.
            msg_ta = msg.get("TradeAccount", "")
            if client_order_id and msg_ta:
                self._order_trade_accounts[client_order_id] = msg_ta

            # 01/05 ROLLBACK : tentative tracking cancels confirmes desactivee
            # apres observation orphan Bot 1 post-fix. Investigation requise avant
            # ré-implémenter (Type 300 query, ou Status code mapping precis).

            # Status 7 = Filled (PAS 2 — 2 = Open/Accepted)
            # Valide en Sim3 02/04/2026 : status passe 2→4→7
            # FIX 29/04 : `or 0` defensif identique
            is_filled = (order_status == 7 or
                         order_status == "Filled" or
                         ((msg.get("FilledQuantity") or 0) > 0 and
                          order_status not in (2, "Open")))

            # Fix audit logs V2 22/04 : detecter fill partiel (status != 7 MAIS
            # FilledQuantity > 0 ET < OrderQuantity). Bug silencieux classique
            # — si broker file 2/3 micros, bot place SL/TP pour 3 lots alors
            # que position = 2 → SL hit partiel → orphan.
            # FIX 29/04 (Jackson + audit forensique) : `dict.get(key, default)`
            # ne retourne PAS le default si la cle existe avec valeur null.
            # SC envoie ORDER_UPDATE intermediaires avec FilledQuantity: null
            # → `None > 0` = TypeError → _recv_loop plante → fills perdus →
            # position fantome (bug observe Bot 2 Sim2 28-29/04).
            filled_qty = msg.get("FilledQuantity") or 0
            expected_qty = msg.get("OrderQuantity") or 0
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
                # 🆕 01/05/2026 soir — DEBUG TEMPORAIRE (Jackson "DTC c'est special")
                # Verification empirique que Sierra Chart envoie TOUJOURS le Symbol
                # natif dans s_OrderUpdate Filled. Si confirme : Option 5 (utiliser
                # fill.symbol natif) au lieu de Option 4 (callback pre-register).
                # A retirer apres 5-10 trades observes (validation N>=3).
                dtc_symbol_raw = msg.get("Symbol", "")
                dtc_trade_account = msg.get("TradeAccount", "")
                if _v2log:
                    try:
                        _v2log.emit("DTC_FILL_SYMBOL_DEBUG",
                                    cid=client_order_id,
                                    symbol_raw=dtc_symbol_raw,
                                    symbol_present=bool(dtc_symbol_raw),
                                    trade_account=dtc_trade_account,
                                    fill_price=fill_price,
                                    is_parent=client_order_id.startswith("MIA_P_"),
                                    msg_keys=list(msg.keys()))
                    except Exception:
                        pass

                # P0-6 : signaler l'event parent si c'est un parent order
                if client_order_id.startswith("MIA_P_") and client_order_id in self._parent_fill_events:
                    # 04/05 Etape 2 : capture fill_price pour slip metric + reprice
                    fill_price_for_parent = float(fill_price or 0)
                    if fill_price_for_parent > 0:
                        self._parent_fill_prices[client_order_id] = fill_price_for_parent
                    self._parent_fill_events[client_order_id].set()

                # Notifier le bot du fill
                if self.on_fill:
                    fill = OrderFill(
                        order_id=client_order_id,
                        symbol=msg.get("Symbol", ""),
                        side=msg.get("BuySell", 0),
                        fill_price=fill_price,
                        quantity=(msg.get("FilledQuantity") or msg.get("OrderQuantity") or 0),
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

                        # 04/05 H6 FIX : passer le TradeAccount correct (Sim1/Sim2/Sim3)
                        # depuis le msg ORDER_UPDATE. Sans ce fix, default "Sim3" etait
                        # utilise -> SC ignorait cancel pour Sim1/Sim2 -> orphelins.
                        ta_for_cancel = (self._order_trade_accounts.get(opposite_cid)
                                         or msg.get("TradeAccount")
                                         or "Sim3")
                        self.cancel_order(opposite_cid, trade_account=ta_for_cancel)

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

        01/05 ROLLBACK fix _cancelled_order_ids : tentative skip silencieux
        sur cancels confirmes a possiblement cause orphan Bot 1 post-deploy.
        Comportement RESTAURE a etat pre-fix : re-cancel systematique + log.
        Le log CANCEL_FAILED_RETRY/OCO_ORPHAN_DETECTED est verbeux mais sans
        risque fonctionnel. Re-investiguer Type 300 Open Orders query au calme.
        """
        server_id = self._server_order_ids.get(order_id, "")
        # 04/05 H6 FIX : utiliser le TradeAccount tracke (Sim1/2/3) au lieu de "Sim3" hardcode.
        ta_for_cancel = self._order_trade_accounts.get(order_id, "Sim3")
        if server_id:
            # Re-envoyer le cancel par securite
            msg = {
                "Type": DTC_CANCEL_ORDER,
                "RequestID": self._request_id_counter,
                "ClientOrderID": order_id,
                "ServerOrderID": server_id,
                "TradeAccount": ta_for_cancel,
            }
            self._request_id_counter += 1
            self._send(msg)
            logger.info(f"Verify cancel (securite): {order_id} SID={server_id} TA={ta_for_cancel}")
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
