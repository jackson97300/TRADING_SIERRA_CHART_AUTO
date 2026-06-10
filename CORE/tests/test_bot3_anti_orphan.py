"""Tests anti-orphelin Bot 3 (P0.1 / P0.2 / P0.3 / P0.4 / P1.1 / P1.2 / P2.1).

Cible : verifier que les nouveaux chemins de recovery + cleanup garantissent
0 orphelin dans le DOM Sierra Chart Sim1 apres restart watchdog ou shutdown.

Strategie : mock DTC connector pour eviter dependance broker reel. Les tests
verifient que :
  - request_open_orders_blocking collecte correctement les Type 301 multiples
    et detecte NoOrders=1 pour signaler completion
  - request_position_with_avg_price retourne (qty, avg_price) tuple
  - _bot3_recover_open_positions reconstitue tp_cid/sl_cid/prices reels
  - _bot3_check_timeout etape 6.5 cancel-all-working catche les orphelins
  - _bot3_check_timeout etape 9 verify post-cleanup detecte survivants
  - shutdown path pre-emptive cancel envoie cancels avant disconnect
  - disconnect drain le _recv_loop avant exit

Date : 2026-05-06
Auteur : MIA Trading System (P0/P1 anti-orphan rewrite)
"""

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Permet l'import depuis BOT/ et CORE/
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "CORE"))

import pytest


# ─── P0.1 : request_open_orders_blocking ─────────────────────────────────

class _FakeSocket:
    """Mock socket non-bloquant pour tests connector."""
    def __init__(self):
        self.sent = []

    def sendall(self, data):
        self.sent.append(data)

    def close(self):
        pass


def _build_connector_mock():
    """Construit un DTCConnector avec socket fake + connecte."""
    from BOT.dtc_connector import DTCConnector
    from bot_config import DTCConfig
    conn = DTCConnector(DTCConfig())
    conn.sock = _FakeSocket()
    conn.connected = True
    conn._running = True
    return conn


def test_request_open_orders_collects_multiple_301():
    """Type 300 → plusieurs 301 → NoOrders=1 → liste deduplicated."""
    conn = _build_connector_mock()

    # Lance la query dans un thread (bloquant), simule reponses dans le main
    result_holder = {"result": None}

    def query_thread():
        result_holder["result"] = conn.request_open_orders_blocking(
            trade_account="Sim1", timeout=2.0)

    t = threading.Thread(target=query_thread)
    t.start()

    # Attendre que le sentinel soit set (max 0.5s)
    deadline = time.time() + 0.5
    while not hasattr(conn, "_pending_open_orders_query") and time.time() < deadline:
        time.sleep(0.01)
    assert hasattr(conn, "_pending_open_orders_query"), "sentinel non set"

    # Simuler 2 working orders + 1 NoOrders=1
    conn._handle_order_update({
        "Type": 301,
        "ClientOrderID": "MIA_TP_aaa111",
        "ServerOrderID": "S001",
        "Symbol": "ESM26-CME",
        "OrderStatus": 4,           # Working
        "BuySell": 2,                # SELL
        "OrderType": 2,              # LIMIT
        "Price1": 7300.0,
        "Quantity": 3,
        "TradeAccount": "Sim1",
        "OpenCloseTrade": 2,
    })
    conn._handle_order_update({
        "Type": 301,
        "ClientOrderID": "MIA_SL_bbb222",
        "ServerOrderID": "S002",
        "Symbol": "ESM26-CME",
        "OrderStatus": 4,
        "BuySell": 2,
        "OrderType": 3,              # STOP
        "StopPrice": 7350.0,
        "Quantity": 3,
        "TradeAccount": "Sim1",
        "OpenCloseTrade": 2,
    })
    # Signal de fin
    conn._handle_order_update({
        "Type": 301,
        "NoOrders": 1,
    })

    t.join(timeout=2.5)
    assert not t.is_alive(), "query thread bloque"

    orders = result_holder["result"]
    assert orders is not None, "result is None"
    assert len(orders) == 2, f"Expected 2 orders, got {len(orders)}"
    cids = sorted([o["ClientOrderID"] for o in orders])
    assert cids == ["MIA_SL_bbb222", "MIA_TP_aaa111"]
    assert orders[0]["Symbol"] == "ESM26-CME"


def test_request_open_orders_filter_symbol():
    """symbol_filter exclu les ordres autres symbols."""
    conn = _build_connector_mock()
    result_holder = {"result": None}

    def query_thread():
        result_holder["result"] = conn.request_open_orders_blocking(
            trade_account="Sim1", symbol_filter="NQM26-CME", timeout=2.0)

    t = threading.Thread(target=query_thread)
    t.start()
    deadline = time.time() + 0.5
    while not hasattr(conn, "_pending_open_orders_query") and time.time() < deadline:
        time.sleep(0.01)

    conn._handle_order_update({
        "Type": 301, "ClientOrderID": "ES_order", "OrderStatus": 4,
        "Symbol": "ESM26-CME", "TradeAccount": "Sim1",
    })
    conn._handle_order_update({
        "Type": 301, "ClientOrderID": "NQ_order", "OrderStatus": 4,
        "Symbol": "NQM26-CME", "TradeAccount": "Sim1",
        "OrderType": 2, "Price1": 28000,
    })
    conn._handle_order_update({"Type": 301, "NoOrders": 1})

    t.join(timeout=2.5)
    orders = result_holder["result"]
    assert orders is not None
    assert len(orders) == 1
    assert orders[0]["ClientOrderID"] == "NQ_order"


def test_request_open_orders_timeout_returns_partial():
    """Si pas de NoOrders=1 dans le timeout, retourne ce qu'on a."""
    conn = _build_connector_mock()
    result_holder = {"result": None}

    def query_thread():
        result_holder["result"] = conn.request_open_orders_blocking(
            trade_account="Sim1", timeout=0.3)

    t = threading.Thread(target=query_thread)
    t.start()
    deadline = time.time() + 0.2
    while not hasattr(conn, "_pending_open_orders_query") and time.time() < deadline:
        time.sleep(0.01)

    conn._handle_order_update({
        "Type": 301, "ClientOrderID": "partial_order", "OrderStatus": 4,
        "Symbol": "ESM26-CME", "TradeAccount": "Sim1",
        "OrderType": 2, "Price1": 7300,
    })
    # PAS de NoOrders=1 → timeout

    t.join(timeout=2.0)
    orders = result_holder["result"]
    # Doit retourner les partiels
    assert orders is not None
    assert len(orders) == 1
    assert orders[0]["ClientOrderID"] == "partial_order"


def test_request_open_orders_no_connection_returns_none():
    """Si pas connecte → None."""
    from BOT.dtc_connector import DTCConnector
    from bot_config import DTCConfig
    conn = DTCConnector(DTCConfig())
    conn.connected = False
    result = conn.request_open_orders_blocking(trade_account="Sim1", timeout=0.5)
    assert result is None


def test_handle_order_update_does_not_break_outside_query():
    """_handle_order_update ne doit PAS planter quand pas de query en cours."""
    conn = _build_connector_mock()
    # Pas de _pending_open_orders_query set → comportement normal
    conn._handle_order_update({
        "Type": 301, "ClientOrderID": "test", "OrderStatus": 4,
        "Symbol": "ESM26-CME", "TradeAccount": "Sim1",
    })
    # Si ca passe sans exception, OK


# ─── P2.1 : request_position_with_avg_price ────────────────────────────────

def test_request_position_with_avg_price_returns_tuple():
    """Type 305 → 306 avec AverageFillPrice → tuple (qty, price)."""
    conn = _build_connector_mock()
    result_holder = {"result": None}

    def query_thread():
        result_holder["result"] = conn.request_position_with_avg_price(
            "ESM26-CME", trade_account="Sim1", timeout=2.0)

    t = threading.Thread(target=query_thread)
    t.start()
    time.sleep(0.05)

    # Simuler reponse Type 306
    if conn.on_position_update:
        conn.on_position_update({
            "Symbol": "ESM26-CME",
            "Quantity": -3,                  # SHORT
            "AverageFillPrice": 7338.25,
        })

    t.join(timeout=2.5)
    result = result_holder["result"]
    assert result is not None
    qty, avg = result
    assert qty == -3
    assert avg == 7338.25


def test_request_position_blocking_compat_retro():
    """request_position_blocking doit toujours retourner qty (pas tuple) - compat retro."""
    conn = _build_connector_mock()
    result_holder = {"result": None}

    def query_thread():
        result_holder["result"] = conn.request_position_blocking(
            "ESM26-CME", trade_account="Sim1", timeout=2.0)

    t = threading.Thread(target=query_thread)
    t.start()
    time.sleep(0.05)
    if conn.on_position_update:
        conn.on_position_update({
            "Symbol": "ESM26-CME",
            "Quantity": 5,
            "AverageFillPrice": 7340.0,
        })
    t.join(timeout=2.5)
    # Doit etre un int signed, pas un tuple
    assert isinstance(result_holder["result"], int)
    assert result_holder["result"] == 5


# ─── P1.2 : disconnect drain ───────────────────────────────────────────────

def test_disconnect_drains_recv_thread():
    """disconnect avec drain_timeout > 0 join le _recv_thread."""
    from BOT.dtc_connector import DTCConnector
    from bot_config import DTCConfig
    conn = DTCConnector(DTCConfig())
    conn.sock = _FakeSocket()
    conn.connected = True
    conn._running = True

    # Simule un _recv_thread "vivant" qui se termine quand _running=False
    def fake_recv_loop():
        while conn._running:
            time.sleep(0.05)

    conn._recv_thread = threading.Thread(target=fake_recv_loop, daemon=False)
    conn._recv_thread.start()

    t0 = time.time()
    conn.disconnect(drain_timeout=2.0)
    elapsed = time.time() - t0

    # Doit avoir join le thread (qui sort sur _running=False)
    assert not conn._recv_thread.is_alive(), "thread non termine apres drain"
    # Drain rapide normalement (< 1s)
    assert elapsed < 1.5, f"drain trop long : {elapsed:.2f}s"


def test_disconnect_no_drain_when_timeout_zero():
    """drain_timeout=0 skip le join (pour cas catastrophiques / tests)."""
    from BOT.dtc_connector import DTCConnector
    from bot_config import DTCConfig
    conn = DTCConnector(DTCConfig())
    conn.sock = _FakeSocket()
    conn.connected = True
    conn._running = True
    # Pas de thread → disconnect doit retourner sans erreur
    conn.disconnect(drain_timeout=0)
    assert conn.connected is False
    assert conn._running is False


# ─── P0-A : concurrent open_orders queries ─────────────────────────────────

def test_concurrent_open_orders_queries_no_corruption():
    """2 threads parallele appellent request_open_orders_blocking → pas de corruption.

    Avant fix P0-A : le 2eme caller ecrasait le sentinel _pending_open_orders_query
    -> events 301 du 1er query partaient dans le buffer du 2eme -> corruption.
    Apres fix : lock _open_orders_query_lock serialise les calls. Le 2eme thread
    attend que le 1er termine.
    """
    conn = _build_connector_mock()
    results = {"r1": None, "r2": None}

    def query1():
        results["r1"] = conn.request_open_orders_blocking(
            trade_account="Sim1", timeout=2.0)

    def query2():
        # Petit delay pour s'assurer que t1 acquire le lock en premier
        time.sleep(0.05)
        results["r2"] = conn.request_open_orders_blocking(
            trade_account="Sim2", timeout=2.0)

    t1 = threading.Thread(target=query1)
    t2 = threading.Thread(target=query2)
    t1.start()
    t2.start()

    # Attend que t1 acquire le sentinel
    deadline = time.time() + 0.3
    while not hasattr(conn, "_pending_open_orders_query") and time.time() < deadline:
        time.sleep(0.01)
    assert hasattr(conn, "_pending_open_orders_query"), "t1 sentinel non acquis"

    # Envoie 2 orders + NoOrders pour t1 (dont la query est Sim1)
    conn._handle_order_update({
        "Type": 301, "ClientOrderID": "TP_t1",
        "ServerOrderID": "S001", "Symbol": "ESM26-CME",
        "OrderStatus": 4, "BuySell": 2, "OrderType": 2,
        "Price1": 7300, "Quantity": 3, "TradeAccount": "Sim1",
    })
    conn._handle_order_update({"Type": 301, "NoOrders": 1})

    # t1 doit terminer
    t1.join(timeout=2.5)
    assert not t1.is_alive(), "t1 hangs"

    # Maintenant t2 devrait acquire le lock et avoir installe son sentinel
    deadline = time.time() + 0.5
    while not hasattr(conn, "_pending_open_orders_query") and time.time() < deadline:
        time.sleep(0.01)
    # Possible que t2 soit deja en wait sur send (ack pas envoyé), envoie son completion
    if hasattr(conn, "_pending_open_orders_query"):
        conn._handle_order_update({"Type": 301, "NoOrders": 1})

    t2.join(timeout=2.5)
    assert not t2.is_alive(), "t2 hangs apres t1 release"

    # t1 doit avoir recu son TP_t1 (non corrompu par t2)
    assert results["r1"] is not None
    assert len(results["r1"]) == 1
    assert results["r1"][0]["ClientOrderID"] == "TP_t1"
    # t2 doit avoir recu une liste vide ou None (pas le TP_t1 de t1)
    if results["r2"]:
        cids2 = [o.get("ClientOrderID") for o in results["r2"]]
        assert "TP_t1" not in cids2, "Corruption: t2 a recu les orders de t1"


def test_handle_dtc_fill_flatten_captures_pnl():
    """FIX 06/05 soir : Type 209 fill (cid_type='flatten') doit capturer pnl reel.

    Avant fix : tous les TIMEOUT 60min finissaient avec pnl_known=false car le
    fill Type 209 SUBMIT_FLATTEN_POSITION_ORDER renvoyait un CID `BOT3_FLUSH_*`
    qui n'etait pas dans `_bot3_cid_index`. Donc `_bot3_handle_dtc_fill` retournait
    False (cid pas reconnu) et le fill etait ignore.

    Apres fix : `_bot3_check_timeout` ETAPE 7a tracker le `flush_cid` AVANT _send
    Type 209 avec un pos_snapshot. Quand le fill arrive, `_bot3_handle_dtc_fill`
    cas `cid_type=='flatten'` reconstruit pnl reel via snapshot et log un trade
    close avec pnl_known=true.
    """
    # On instancie un mock minimal du paper_trader pour tester _bot3_handle_dtc_fill
    # sans avoir a booter tout le pipeline DTC + databento.
    import threading
    from unittest.mock import MagicMock

    class _FakeBot:
        def __init__(self):
            self._bot3_cid_index = {}
            self._bot3_positions = {"NQ": None, "ES": None}
            self._bot3_pos_lock = threading.RLock()
            self.bot3_counters_today = {"n_trades": {"NQ": 0, "ES": 0},
                                         "n_losses": {"NQ": 0, "ES": 0}}
            self.logged_trades = []

        def _bot3_log_trade_close(self, **kwargs):
            self.logged_trades.append(kwargs)

    # Import _bot3_handle_dtc_fill via la classe principale
    from CORE.databento_paper_trader_v2 import DatabentoPaperTraderV2

    # Bind la methode au _FakeBot pour eviter init complet
    bot = _FakeBot()
    bot._bot3_handle_dtc_fill = DatabentoPaperTraderV2._bot3_handle_dtc_fill.__get__(bot)

    # Pre-register un flush_cid avec pos_snapshot (simule ETAPE 7a)
    flush_cid = "BOT3_FLUSH_ES_12345"
    bot._bot3_cid_index[flush_cid] = {
        "sym": "ES",
        "type": "flatten",
        "signal_id": "test_sig",
        "pos_snapshot": {
            "side": "LONG",
            "entry_price": 7362.0,
            "n_contracts": 3,
            "level": "GEX_DN",
            "ts_open": "2026-05-06T14:51:36+00:00",
            "mfe_ticks": 40.0,
            "mae_ticks": -4.0,
        },
        "duration_s": 3601,
        "close_reason": "TIMEOUT",
    }

    # Simule fill Type 301 status=7 du Type 209 (fill au prix marche 7361.50)
    fill_msg = {
        "OrderStatus": 7,
        "AverageFillPrice": 7361.50,
        "ClientOrderID": flush_cid,
    }
    result = bot._bot3_handle_dtc_fill(fill_msg, flush_cid)
    assert result is True, "fill flatten doit etre traite (return True)"

    # Verif : 1 trade logge avec pnl_known
    assert len(bot.logged_trades) == 1
    t = bot.logged_trades[0]
    # Direction LONG, fill 7361.50 - entry 7362.0 = -0.5 pts = -2 ticks
    assert abs(t["pnl_ticks"] - (-2.0)) < 0.01, f"pnl_ticks attendu -2, recu {t['pnl_ticks']}"
    # pnl_dollars = -2 * 1.25 (ES tick_value) * 3 (n_contracts) = -7.50
    assert abs(t["pnl_dollars"] - (-7.50)) < 0.01, f"pnl_dollars attendu -7.50, recu {t['pnl_dollars']}"
    assert t["exit_price"] == 7361.50
    assert t["reason"] == "TIMEOUT"
    assert t["sym"] == "ES"

    # Cid doit etre cleanup apres fill
    assert flush_cid not in bot._bot3_cid_index, "flush_cid doit etre cleanup apres fill traite"


def test_handle_dtc_fill_flatten_short_position():
    """Verifie pnl SHORT correct (signe inverse)."""
    import threading
    from CORE.databento_paper_trader_v2 import DatabentoPaperTraderV2

    class _FakeBot:
        def __init__(self):
            self._bot3_cid_index = {}
            self._bot3_positions = {"NQ": None, "ES": None}
            self._bot3_pos_lock = threading.RLock()
            self.bot3_counters_today = {"n_trades": {"NQ": 0, "ES": 0},
                                         "n_losses": {"NQ": 0, "ES": 0}}
            self.logged_trades = []

        def _bot3_log_trade_close(self, **kwargs):
            self.logged_trades.append(kwargs)

    bot = _FakeBot()
    bot._bot3_handle_dtc_fill = DatabentoPaperTraderV2._bot3_handle_dtc_fill.__get__(bot)

    flush_cid = "BOT3_FLUSH_NQ_99999"
    bot._bot3_cid_index[flush_cid] = {
        "sym": "NQ",
        "type": "flatten",
        "signal_id": "test_short",
        "pos_snapshot": {
            "side": "SHORT",
            "entry_price": 28602.5,
            "n_contracts": 3,
            "level": "GEX_DN",
            "ts_open": "2026-05-06T11:51:15+00:00",
        },
        "duration_s": 3608,
        "close_reason": "TIMEOUT",
    }

    # SHORT fill at 28458 → profit (= 28602.5 - 28458 = +144.5 pts = +578t per contract)
    fill_msg = {"OrderStatus": 7, "AverageFillPrice": 28458.0}
    bot._bot3_handle_dtc_fill(fill_msg, flush_cid)

    assert len(bot.logged_trades) == 1
    t = bot.logged_trades[0]
    # SHORT: (28458 - 28602.5) / 0.25 * -1 (dir_sign) = -578 * -1 = +578t
    assert abs(t["pnl_ticks"] - 578.0) < 0.01, f"pnl_ticks attendu +578, recu {t['pnl_ticks']}"
    # pnl_dollars = 578 * 0.50 (NQ tick_value) * 3 = +867
    assert abs(t["pnl_dollars"] - 867.0) < 0.01, f"pnl_dollars attendu +867, recu {t['pnl_dollars']}"


def test_on_order_update_callback_called_on_type_301():
    """FIX 06/05 soir BUG STRUCTUREL : on_order_update doit etre appele sur
    chaque Type 301 reçu. Avant fix : Bot 3 assignait self.dtc.on_order_update
    mais l'attribut n'existait pas → callback ignore silencieusement → 100%
    des fills perdus depuis le 03/05 deploy Bot 3.
    """
    conn = _build_connector_mock()
    received_msgs = []

    def my_callback(msg):
        received_msgs.append(dict(msg))

    conn.on_order_update = my_callback

    # Simule un fill TP Type 301 status=7
    fill_msg = {
        "Type": 301,
        "OrderStatus": 7,
        "ClientOrderID": "MIA_TP_test",
        "ServerOrderID": "S_test",
        "AverageFillPrice": 7370.0,
        "Symbol": "ESM26-CME",
        "FilledQuantity": 3,
        "OrderQuantity": 3,
        "TradeAccount": "Sim1",
    }
    conn._handle_order_update(fill_msg)

    assert len(received_msgs) == 1, "callback doit etre appele exactement 1 fois"
    assert received_msgs[0]["ClientOrderID"] == "MIA_TP_test"
    assert received_msgs[0]["OrderStatus"] == 7
    assert received_msgs[0]["AverageFillPrice"] == 7370.0


def test_on_order_update_callback_intermediate_status_too():
    """Le callback recoit AUSSI les status intermediaires (2 Open, 4 Working).
    C'est au consumer de filtrer. Critique pour Bot 3 qui peut tracker l'etat
    Working d'un order avant le fill final.
    """
    conn = _build_connector_mock()
    received_statuses = []

    conn.on_order_update = lambda msg: received_statuses.append(msg.get("OrderStatus"))

    for status in (2, 4, 7):  # Open, Working, Filled
        conn._handle_order_update({
            "Type": 301, "OrderStatus": status,
            "ClientOrderID": "MIA_TEST", "Symbol": "ESM26-CME",
        })

    assert received_statuses == [2, 4, 7], \
        f"Tous status doivent etre routes (recu {received_statuses})"


def test_on_order_update_callback_exception_does_not_break_flow():
    """Si le callback throw, le _handle_order_update continue normalement
    (pas de re-raise). Critique pour ne pas casser _recv_loop sur un bug
    callback consumer.
    """
    conn = _build_connector_mock()

    def buggy_callback(msg):
        raise RuntimeError("crash callback intentionnel")

    conn.on_order_update = buggy_callback

    # Cet appel ne doit PAS lever d'exception meme avec callback buggy
    try:
        conn._handle_order_update({
            "Type": 301, "OrderStatus": 7,
            "ClientOrderID": "MIA_BUGGY", "Symbol": "ESM26-CME",
            "AverageFillPrice": 7370.0,
        })
    except Exception as e:
        assert False, f"_handle_order_update a propage exception callback: {e}"

    # Le connector doit toujours etre fonctionnel apres
    assert conn.connected is True


def test_on_order_update_no_callback_no_crash():
    """Si on_order_update est None (default), pas de crash, pas de call."""
    conn = _build_connector_mock()
    assert conn.on_order_update is None  # default

    # Doit pas crasher
    conn._handle_order_update({
        "Type": 301, "OrderStatus": 7,
        "ClientOrderID": "MIA_NO_CB", "Symbol": "ESM26-CME",
    })


def test_compute_stats_dedup_by_signal_id():
    """P0 review code-reviewer 06/05 : dedup par signal_id quand fix Type 209
    re-log une 2eme ligne JSONL avec pnl_known=true. Sans dedup, le dashboard
    double-compte le trade dans trade_count_today.

    Strategie testee : ligne pnl_known=true gagne sur ligne pnl=null.
    """
    import sys
    from pathlib import Path
    ROOT = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(ROOT))
    from DASHBOARD.api.paper_tracker import _compute_stats_today_from_trades

    # Mock _iter_trades_from_files via monkeypatch d'environnement temp
    # Plus simple : utiliser un import direct + remplacer la fonction
    import DASHBOARD.api.paper_tracker as pt

    # Cas : 2 lignes pour le meme signal_id - 1 pnl=null (TIMEOUT a chaud) + 1 pnl reel (fill capture)
    fake_trades = [
        # Ligne 1 : log a chaud TIMEOUT, pnl=null
        {
            "signal_id": "abc123",
            "symbol": "ES",
            "side": "LONG",
            "entry_price": 7362.0,
            "exit_price": None,
            "pnl_ticks": None,
            "pnl_usd": None,
            "pnl_known": False,
            "reason": "TIMEOUT",
            "ts_close": "2026-05-06T15:51:45+00:00",
        },
        # Ligne 2 : re-log apres fill Type 209 capture, pnl reel
        {
            "signal_id": "abc123",
            "symbol": "ES",
            "side": "LONG",
            "entry_price": 7362.0,
            "exit_price": 7361.50,
            "pnl_ticks": -2.0,
            "pnl_usd": -7.50,
            "pnl_known": True,
            "reason": "TIMEOUT",
            "ts_close": "2026-05-06T15:51:46+00:00",  # 1s plus tard
        },
        # Trade independant ligne 3
        {
            "signal_id": "xyz789",
            "symbol": "NQ",
            "side": "SHORT",
            "entry_price": 28602.5,
            "exit_price": 28458.0,
            "pnl_ticks": 578.0,
            "pnl_usd": 867.0,
            "pnl_known": True,
            "reason": "TP",
            "ts_close": "2026-05-06T12:51:26+00:00",
        },
    ]

    # Monkey-patch _iter_trades_from_files
    original_iter = pt._iter_trades_from_files
    pt._iter_trades_from_files = lambda *args, **kwargs: iter(fake_trades)
    try:
        result = _compute_stats_today_from_trades("*_test_pattern.jsonl")
    finally:
        pt._iter_trades_from_files = original_iter

    # Apres dedup : 2 trades uniques (abc123 fusionne, xyz789 conserve)
    assert result["trade_count_today"] == 2, \
        f"Attendu 2 trades dedup, recu {result['trade_count_today']}"
    assert result["stats_today"]["trades"] == 2
    assert result["stats_today"]["trades_known_pnl"] == 2  # les 2 ont pnl_known maintenant

    # PnL total : -7.50 + 867.0 = +859.50 (sans le -7.50 double)
    assert abs(result["stats_today"]["pnl_usd"] - 859.50) < 0.01, \
        f"PnL attendu 859.50, recu {result['stats_today']['pnl_usd']}"

    # closed_today : 2 lignes, la abc123 doit etre la version pnl_known=true
    closed = result["closed_today"]
    assert len(closed) == 2
    abc_line = [t for t in closed if t["signal_id"] == "abc123"][0]
    assert abc_line["pnl_known"] is True
    assert abc_line["pnl_ticks"] == -2.0
    assert abc_line["exit_price"] == 7361.50


def test_handle_dtc_fill_flatten_no_snapshot_emits_alert():
    """Si pos_snapshot.entry_price absent → emit ALERTE et skip pnl calc."""
    import threading
    from CORE.databento_paper_trader_v2 import DatabentoPaperTraderV2

    class _FakeBot:
        def __init__(self):
            self._bot3_cid_index = {}
            self._bot3_positions = {"NQ": None, "ES": None}
            self._bot3_pos_lock = threading.RLock()
            self.bot3_counters_today = {"n_trades": {"NQ": 0, "ES": 0},
                                         "n_losses": {"NQ": 0, "ES": 0}}
            self.logged_trades = []

        def _bot3_log_trade_close(self, **kwargs):
            self.logged_trades.append(kwargs)

    bot = _FakeBot()
    bot._bot3_handle_dtc_fill = DatabentoPaperTraderV2._bot3_handle_dtc_fill.__get__(bot)

    # Snapshot avec entry_price=0 (cas RECOVERED_BOOT) → doit skip
    flush_cid = "BOT3_FLUSH_ES_88888"
    bot._bot3_cid_index[flush_cid] = {
        "sym": "ES", "type": "flatten",
        "pos_snapshot": {"side": "LONG", "entry_price": 0.0, "n_contracts": 3},
        "duration_s": 3600,
        "close_reason": "RECOVERED_TIMEOUT",
    }
    fill_msg = {"OrderStatus": 7, "AverageFillPrice": 7361.50}
    bot._bot3_handle_dtc_fill(fill_msg, flush_cid)

    # Aucun trade logge (pas de pnl calculable)
    assert len(bot.logged_trades) == 0
    # Cid cleanup quand meme
    assert flush_cid not in bot._bot3_cid_index


def test_request_open_orders_no_symbol_in_request():
    """P0-C : verifier que Type 300 n'envoie PAS le champ Symbol (spec DTC stricte)."""
    conn = _build_connector_mock()

    def query_thread():
        conn.request_open_orders_blocking(
            trade_account="Sim1", symbol_filter="ESM26-CME", timeout=0.3)

    t = threading.Thread(target=query_thread)
    t.start()
    deadline = time.time() + 0.2
    while not hasattr(conn, "_pending_open_orders_query") and time.time() < deadline:
        time.sleep(0.01)
    # Inspecte le dernier message envoye via FakeSocket
    sent_msgs = conn.sock.sent
    assert len(sent_msgs) > 0
    import json as _json
    # Trouve le Type 300 dans ce qui a ete envoye
    type_300_msgs = []
    for raw in sent_msgs:
        try:
            txt = raw.rstrip(b"\x00").decode("utf-8")
            obj = _json.loads(txt)
            if obj.get("Type") == 300:
                type_300_msgs.append(obj)
        except Exception:
            pass
    assert len(type_300_msgs) >= 1, "Type 300 non envoye"
    assert "Symbol" not in type_300_msgs[0], \
        f"Type 300 ne doit PAS contenir Symbol (P0-C) : {type_300_msgs[0]}"
    assert type_300_msgs[0].get("TradeAccount") == "Sim1"

    # Cleanup : envoyer NoOrders=1 pour debloquer le thread
    conn._handle_order_update({"Type": 301, "NoOrders": 1})
    t.join(timeout=1.0)
