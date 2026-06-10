"""Tests REVERT 10/06/2026 : SL STOP envoye AVEC Price1 (spec officielle DTC).

Ce fichier REMPLACE test_dtc_stop_no_price1.py (renommage + asserts inverses).

Cause racine du revert :
- Patch 01/06 avait RETIRE Price1 du SL STOP en croyant que "OrderType=3 (STOP)
  utilise UNIQUEMENT StopPrice". Affirmation jamais verifiee contre la spec.
- Preuve empirique 10/06 : SL STOP sans Price1 = NON arme cote Sierra Chart
  (chart ne materialise pas le SL, Trade Manager Sim le voit Open sans trigger,
  comportements aleatoires : fill instantane @ mid bid/ask OU jamais trigger).
- 5+ trades casses en 48h (Bot 3 v3, Bot 3 v4, BN V5).
- Pattern V1 valide Nov 2024 = belt-and-suspenders Price1 + Price2=0 + StopPrice.

Spec officielle DTC s_SubmitNewSingleOrder :
- Price1 = stop trigger price pour OrderType=STOP (3)
- Price2 = limit price pour OrderType=STOP_LIMIT (4)
- StopPrice : N'EXISTE PAS dans la spec officielle (mais SC accepte en alias)

Verifie :
1. SL STOP envoye AVEC champ Price1 = sl_price (FIX 10/06)
2. SL STOP envoye AVEC Price2 = 0.0 explicite (default safe)
3. SL STOP envoye AVEC StopPrice = sl_price (defensif compat V1)
4. TP LIMIT envoye AVEC Price1 (pas regresse)
5. Parent MARKET envoye sans Price1/Price2/StopPrice (correct)
6. ClientOrderID + TradeAccount + IsAutomatedOrder preserves (anti-orphan compat)
7. OCO pair register + H6 trade_account pre-register preserves
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "BOT"))  # pour bot_config import


class _MockDTC:
    """Mock minimal DTCConnector pour intercepter _send."""

    def __init__(self):
        self.sent_msgs: list[dict] = []
        self.connected = True
        self._parent_fill_events: dict = {}
        self._parent_fill_prices: dict = {}
        self._server_order_ids: dict = {}
        self._order_trade_accounts: dict = {}
        self._oco_pairs: dict = {}
        self._last_fill_lock = threading.Lock()
        self._last_fill_prices: dict = {}
        self._request_id_counter = 1

    def _send(self, msg: dict):
        self.sent_msgs.append(dict(msg))

    def register_oco_pair(self, tp_cid: str, sl_cid: str):
        self._oco_pairs[tp_cid] = sl_cid
        self._oco_pairs[sl_cid] = tp_cid


def _setup_mock_with_parent_fill(mock_dtc, fill_price: float, parent_id: str):
    """Simule le parent fill : trigger event + populate fill_price."""
    def _simulate_fill_after_delay():
        import time
        time.sleep(0.1)
        for pid, evt in list(mock_dtc._parent_fill_events.items()):
            mock_dtc._parent_fill_prices[pid] = fill_price
            evt.set()

    t = threading.Thread(target=_simulate_fill_after_delay, daemon=True)
    t.start()


def _send_bracket(mock):
    from BOT.dtc_connector import DTCConnector, BUY
    send_market = DTCConnector.send_market_order.__get__(mock, DTCConnector)
    _setup_mock_with_parent_fill(mock, fill_price=30250.25, parent_id="dummy")
    return send_market(
        symbol="NQM26-CME",
        side=BUY,
        quantity=1,
        sl_price=30246.50,
        tp_price=30255.875,
        trade_account="Sim1",
        signal_ref_price=30250.25,
        sl_ticks=15,
        tp_ticks=22,
        tick_size=0.25,
    )


def test_sl_stop_has_price1_in_payload():
    """1. SL STOP order envoye AVEC champ Price1 = sl_price (FIX 10/06)."""
    from BOT.dtc_connector import STOP

    mock = _MockDTC()
    parent_cid, tp_cid, sl_cid = _send_bracket(mock)

    sl_msg = None
    for msg in mock.sent_msgs:
        if msg.get("ClientOrderID") == sl_cid and msg.get("OrderType") == STOP:
            sl_msg = msg
            break

    assert sl_msg is not None, f"SL STOP message not found. Sent: {mock.sent_msgs}"

    # CRITIQUE : Price1 doit etre PRESENT et egal a sl_price (spec DTC officielle)
    assert "Price1" in sl_msg, (
        f"Price1 MANQUANT dans SL STOP payload (regression patch 01/06) : {sl_msg}. "
        f"Spec DTC s_SubmitNewSingleOrder : Price1 = stop trigger pour OrderType=3 (STOP)."
    )
    assert sl_msg["Price1"] == 30246.50, (
        f"Price1 attendu 30246.50 (= sl_price), obtenu {sl_msg['Price1']}"
    )


def test_sl_stop_has_price2_zero_default():
    """2. SL STOP envoye AVEC Price2 = 0.0 explicite (default safe non STOP_LIMIT)."""
    from BOT.dtc_connector import STOP

    mock = _MockDTC()
    parent_cid, tp_cid, sl_cid = _send_bracket(mock)

    sl_msg = next(
        m for m in mock.sent_msgs
        if m.get("ClientOrderID") == sl_cid and m.get("OrderType") == STOP
    )

    assert "Price2" in sl_msg, f"Price2 manquant dans SL STOP : {sl_msg}"
    assert sl_msg["Price2"] == 0.0, (
        f"Price2 attendu 0.0 (default explicite non STOP_LIMIT), obtenu {sl_msg['Price2']}"
    )


def test_sl_stop_has_stop_price_defensif():
    """3. SL STOP envoye AVEC StopPrice = sl_price (defensif compat V1 Nov 2024)."""
    from BOT.dtc_connector import STOP

    mock = _MockDTC()
    parent_cid, tp_cid, sl_cid = _send_bracket(mock)

    sl_msg = next(
        m for m in mock.sent_msgs
        if m.get("ClientOrderID") == sl_cid and m.get("OrderType") == STOP
    )

    assert "StopPrice" in sl_msg, "StopPrice manquant (defensif compat V1)"
    assert sl_msg["StopPrice"] == 30246.50, (
        f"StopPrice attendu 30246.50, obtenu {sl_msg['StopPrice']}"
    )


def test_tp_limit_still_has_price1():
    """4. TP LIMIT envoye AVEC Price1 (specs DTC OrderType=2) - pas regresse."""
    from BOT.dtc_connector import LIMIT

    mock = _MockDTC()
    parent_cid, tp_cid, sl_cid = _send_bracket(mock)

    tp_msg = None
    for msg in mock.sent_msgs:
        if msg.get("ClientOrderID") == tp_cid and msg.get("OrderType") == LIMIT:
            tp_msg = msg
            break

    assert tp_msg is not None, f"TP LIMIT message not found. Sent: {mock.sent_msgs}"

    assert "Price1" in tp_msg, (
        f"Price1 MANQUANT dans TP LIMIT payload (regression) : {tp_msg}. "
        f"Spec DTC OrderType=2 (LIMIT) UTILISE Price1."
    )
    assert tp_msg["Price1"] == 30255.875, (
        f"TP Price1 attendu 30255.875, obtenu {tp_msg['Price1']}"
    )


def test_parent_market_no_price_fields():
    """5. Parent MARKET envoye sans Price1/Price2/StopPrice (correct)."""
    from BOT.dtc_connector import MARKET

    mock = _MockDTC()
    parent_cid, tp_cid, sl_cid = _send_bracket(mock)

    parent_msg = next(
        m for m in mock.sent_msgs
        if m.get("ClientOrderID") == parent_cid and m.get("OrderType") == MARKET
    )

    # MARKET order : aucun prix
    assert "Price1" not in parent_msg, f"Parent MARKET ne doit pas avoir Price1 : {parent_msg}"
    assert "Price2" not in parent_msg, f"Parent MARKET ne doit pas avoir Price2 : {parent_msg}"
    assert "StopPrice" not in parent_msg, f"Parent MARKET ne doit pas avoir StopPrice : {parent_msg}"
    assert parent_msg.get("OpenCloseTrade") == 1, "Parent doit avoir OpenCloseTrade=1"


def test_sl_stop_anti_orphan_fields_preserved():
    """6. Anti-orphan compat : ClientOrderID + TradeAccount + IsAutomatedOrder preserves."""
    from BOT.dtc_connector import STOP

    mock = _MockDTC()
    parent_cid, tp_cid, sl_cid = _send_bracket(mock)

    sl_msg = next(
        m for m in mock.sent_msgs
        if m.get("ClientOrderID") == sl_cid and m.get("OrderType") == STOP
    )

    assert sl_msg["ClientOrderID"] == sl_cid, "ClientOrderID manquant/incorrect"
    assert sl_msg["TradeAccount"] == "Sim1", "TradeAccount manquant/incorrect"
    assert sl_msg.get("IsAutomatedOrder") == 1, "IsAutomatedOrder requis"
    assert sl_msg.get("OpenCloseTrade") == 2, "OpenCloseTrade=2 requis (close trade)"


def test_sl_stop_pre_registered_for_oco_h6():
    """7. Pre-register TradeAccount H6 fix (anti-orphan)."""
    mock = _MockDTC()
    parent_cid, tp_cid, sl_cid = _send_bracket(mock)

    assert mock._order_trade_accounts.get(tp_cid) == "Sim1", (
        "TP cid pas pre-register pour TradeAccount (fix H6 regression)"
    )
    assert mock._order_trade_accounts.get(sl_cid) == "Sim1", (
        "SL cid pas pre-register pour TradeAccount (fix H6 regression)"
    )

    assert mock._oco_pairs.get(tp_cid) == sl_cid, "OCO pair tp->sl manquant"
    assert mock._oco_pairs.get(sl_cid) == tp_cid, "OCO pair sl->tp manquant"


if __name__ == "__main__":
    test_sl_stop_has_price1_in_payload()
    print("[OK] test_sl_stop_has_price1_in_payload")
    test_sl_stop_has_price2_zero_default()
    print("[OK] test_sl_stop_has_price2_zero_default")
    test_sl_stop_has_stop_price_defensif()
    print("[OK] test_sl_stop_has_stop_price_defensif")
    test_tp_limit_still_has_price1()
    print("[OK] test_tp_limit_still_has_price1")
    test_parent_market_no_price_fields()
    print("[OK] test_parent_market_no_price_fields")
    test_sl_stop_anti_orphan_fields_preserved()
    print("[OK] test_sl_stop_anti_orphan_fields_preserved")
    test_sl_stop_pre_registered_for_oco_h6()
    print("[OK] test_sl_stop_pre_registered_for_oco_h6")
    print("\n[OK] 7/7 tests REVERT Price1 PASS")
