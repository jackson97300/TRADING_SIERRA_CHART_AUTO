"""Tests DtcFillListener Bot 1 v2 - ferme positions sur ORDER_UPDATE Type 301 fill.

Couvre :
  - TP fill status=7 → close_position avec exit_reason=TP + PnL correct
  - SL fill status=7 → close_position avec exit_reason=SL
  - OrderStatus != 7 (2=Open, 4=Working) → ignore
  - TradeAccount mismatch → ignore (filtre H6 orphan-prevention)
  - cid pas dans index → ignore
  - fill_price <= 0 → GUARD #2 ghost trade refuse close
  - Idempotence : close 2x → no-op
  - Threadsafe : lock sur _cid_index
  - Exception callback → no crash recv_loop
  - Recovery boot : rebuild _cid_index depuis store.positions
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
from CORE.bot1_v2.state.position_store import PositionStore
from CORE.bot1_v2.state_bridge import StateBridge


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def tmp_paths(tmp_path):
    """Chemins temporaires pour store + state_bridge."""
    return {
        "store": tmp_path / "bot1_v2_runtime_positions.json",
        "bridge": tmp_path / "bot1_v2_state.json",
    }


@pytest.fixture
def store(tmp_paths):
    """PositionStore vide."""
    return PositionStore(path=tmp_paths["store"])


@pytest.fixture
def state_bridge(tmp_paths):
    """StateBridge vide."""
    return StateBridge(path=tmp_paths["bridge"])


@pytest.fixture
def cfg():
    """Config Bot 1 v2 Sim2."""
    c = Bot1V2Config.from_env()
    # Force TRADE_ACCOUNT = Sim2 (peut etre Sim9 default en test)
    c2 = Bot1V2Config(**{**c.__dict__})
    object.__setattr__(c2, "TRADE_ACCOUNT", "Sim2")
    return c2


@pytest.fixture
def listener(cfg, store, state_bridge):
    """Listener avec store + state_bridge propres."""
    return DtcFillListener(cfg=cfg, store=store, state_bridge=state_bridge)


def _open_position(store, state_bridge, sym="ES", direction="SHORT"):
    """Helper : ouvre une position dans store + state_bridge + retourne CIDs."""
    parent_cid = "MIA_P_abc"
    tp_cid = "MIA_TP_def"
    sl_cid = "MIA_SL_ghi"
    pos_data = {
        "signal_id": "sig_test",
        "direction": direction,
        "entry_price": 7580.5,
        "entry_ts": 1781000000000,
        "sl_price": 7582.0,
        "tp_price": 7578.25,
        "sl_ticks": 6,
        "tp_ticks": 9,
        "n_micros": 1,
        "parent_cid": parent_cid,
        "tp_cid": tp_cid,
        "sl_cid": sl_cid,
    }
    store.open_position(sym, pos_data)
    state_bridge.open_position(
        sym, direction=direction, entry_price=7580.5,
        sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, signal_id="sig_test",
        sl_wall="CUR_VAH", n_micros=1,
    )
    return parent_cid, tp_cid, sl_cid


def _register(listener, sym, direction, parent_cid, tp_cid, sl_cid):
    listener.register_bracket(
        sym=sym, signal_id="sig_test", direction=direction,
        entry_price=7580.5, sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, n_micros=1,
        parent_cid=parent_cid, tp_cid=tp_cid, sl_cid=sl_cid,
    )


# ============================================================
# Tests : register + lookup basique
# ============================================================


def test_register_bracket_populates_index(listener):
    """register_bracket ajoute 3 entries (parent + tp + sl) dans _cid_index."""
    _register(listener, "ES", "SHORT", "MIA_P_a", "MIA_TP_b", "MIA_SL_c")
    assert listener.n_tracked_brackets() == 3


def test_register_bracket_skips_empty_cids(listener):
    """CIDs vides ne sont PAS enregistres (cas degrade : DTC retourne ("", "", ""))."""
    listener.register_bracket(
        sym="ES", signal_id="sig", direction="SHORT",
        entry_price=7580.5, sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, n_micros=1,
        parent_cid="", tp_cid="", sl_cid="",
    )
    assert listener.n_tracked_brackets() == 0


# ============================================================
# Tests : TP fill → close_position TP + PnL gain
# ============================================================


def test_tp_fill_closes_position_with_correct_pnl(listener, store, state_bridge):
    """ES SHORT entry 7580.5 → TP fill 7578.25 = gain 9t * $1.25/t = +$11.25."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge, "ES", "SHORT")
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": 7578.25,
    })
    # Store : position fermee
    assert store.has_position("ES") is False
    # State bridge : position dans closed_today
    closed = state_bridge.state["closed_today"]
    assert len(closed) == 1
    last = closed[-1]
    assert last["exit_price"] == 7578.25
    assert last["exit_reason"] == "TP"
    assert last["outcome"] == "WIN"
    assert last["pnl_ticks"] == 9.0
    assert last["pnl_usd"] == 11.25
    # cid_index : nettoye
    assert listener.n_tracked_brackets() == 0


def test_sl_fill_closes_position_with_loss(listener, store, state_bridge):
    """ES SHORT entry 7580.5 → SL fill 7582.0 = perte 6t * $1.25 = -$7.5."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge, "ES", "SHORT")
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": sl_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": 7582.0,
    })
    assert store.has_position("ES") is False
    last = state_bridge.state["closed_today"][-1]
    assert last["exit_reason"] == "SL"
    assert last["outcome"] == "LOSS"
    assert last["pnl_ticks"] == -6.0
    assert last["pnl_usd"] == -7.5


def test_long_tp_fill_correct_pnl(listener, store, state_bridge):
    """NQ LONG → TP profit calcule correctement."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge, "NQ", "LONG")
    listener.register_bracket(
        sym="NQ", signal_id="sig_test", direction="LONG",
        entry_price=30000.0, sl_price=29995.0, tp_price=30010.0,
        sl_ticks=20, tp_ticks=40, n_micros=1,
        parent_cid=parent_cid, tp_cid=tp_cid, sl_cid=sl_cid,
    )
    listener.handle_order_update({
        "ClientOrderID": tp_cid, "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 30010.0,
    })
    last = state_bridge.state["closed_today"][-1]
    # NQ : tick=0.25, value=$0.50/tick — gain = (30010-30000)/0.25 = 40t × $0.50 = $20
    assert last["pnl_ticks"] == 40.0
    assert last["pnl_usd"] == 20.0


# ============================================================
# Tests : Filtres (TradeAccount, OrderStatus, CID inconnu)
# ============================================================


def test_filter_wrong_trade_account_ignored(listener, store, state_bridge):
    """TradeAccount Sim1 (Bot MR) ne doit PAS closer Bot 1 v2 Sim2."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid,
        "TradeAccount": "Sim1",  # autre compte !
        "OrderStatus": 7,
        "LastFillPrice": 7578.25,
    })
    assert store.has_position("ES") is True  # position intacte


def test_filter_status_2_ignored(listener, store, state_bridge):
    """OrderStatus=2 (Open) ne doit pas closer."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 2,
        "LastFillPrice": 7578.25,
    })
    assert store.has_position("ES") is True


def test_filter_unknown_cid_ignored(listener, store, state_bridge):
    """CID pas dans index = autre bot → no-op."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": "MIA_TP_OTHER_BOT",
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": 7578.25,
    })
    assert store.has_position("ES") is True


def test_filter_parent_fill_no_close(listener, store, state_bridge):
    """parent fill = OUVERTURE pas cloture. Ne pas closer la position."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": parent_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": 7580.5,
    })
    assert store.has_position("ES") is True


# ============================================================
# Tests : GUARD fill_price <= 0 (ghost trade)
# ============================================================


def test_guard_fill_price_zero_refuses_close(listener, store, state_bridge):
    """fill_price = 0 → GUARD #2 (incident ghost trade $59542 BN V4)."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": 0.0,
        "AverageFillPrice": 0.0,
    })
    assert store.has_position("ES") is True


def test_guard_fill_price_negative_refuses_close(listener, store, state_bridge):
    """fill_price < 0 → GUARD #2."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": -1.0,
    })
    assert store.has_position("ES") is True


def test_average_fill_price_fallback(listener, store, state_bridge):
    """Si LastFillPrice=0 mais AverageFillPrice>0 → utilise AverageFillPrice."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": 0,
        "AverageFillPrice": 7578.25,
    })
    assert store.has_position("ES") is False
    last = state_bridge.state["closed_today"][-1]
    assert last["exit_price"] == 7578.25


# ============================================================
# Tests : Idempotence et exceptions
# ============================================================


def test_idempotence_double_tp_fill(listener, store, state_bridge):
    """Double TP fill (race condition) → 1 seul close."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    msg = {
        "ClientOrderID": tp_cid, "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 7578.25,
    }
    listener.handle_order_update(msg)
    listener.handle_order_update(msg)  # 2eme appel
    assert len(state_bridge.state["closed_today"]) == 1


def test_callback_exception_no_crash(listener, store, state_bridge):
    """state_bridge.close_position raise → no crash listener."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    state_bridge.close_position = MagicMock(side_effect=RuntimeError("disk full"))
    # Ne doit pas raise
    listener.handle_order_update({
        "ClientOrderID": tp_cid, "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 7578.25,
    })
    # Position retiree du store malgre erreur bridge (les 2 actions independantes)
    assert store.has_position("ES") is False


def test_on_close_callback_invoked_with_pnl(cfg, store, state_bridge):
    """on_close_callback est appele apres close avec (sym, pnl_usd)."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    captured = []
    def cb(sym, pnl_usd):
        captured.append((sym, pnl_usd))
    listener = DtcFillListener(cfg, store, state_bridge, on_close_callback=cb)
    listener.register_bracket(
        sym="ES", signal_id="sig_test", direction="SHORT",
        entry_price=7580.5, sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, n_micros=1,
        parent_cid=parent_cid, tp_cid=tp_cid, sl_cid=sl_cid,
    )
    listener.handle_order_update({
        "ClientOrderID": tp_cid, "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 7578.25,
    })
    assert captured == [("ES", 11.25)]


def test_on_close_callback_exception_no_crash(cfg, store, state_bridge):
    """Callback externe raise → no crash."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    def bad_cb(sym, pnl_usd):
        raise ConnectionError("dashboard down")
    listener = DtcFillListener(cfg, store, state_bridge, on_close_callback=bad_cb)
    listener.register_bracket(
        sym="ES", signal_id="sig_test", direction="SHORT",
        entry_price=7580.5, sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, n_micros=1,
        parent_cid=parent_cid, tp_cid=tp_cid, sl_cid=sl_cid,
    )
    # Pas d'exception
    listener.handle_order_update({
        "ClientOrderID": tp_cid, "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 7578.25,
    })
    assert store.has_position("ES") is False


def test_handle_invalid_msg_type_no_crash(listener):
    """msg non-dict → no-op, no crash."""
    listener.handle_order_update(None)  # type: ignore
    listener.handle_order_update("garbage")  # type: ignore


# ============================================================
# Tests : Recovery boot (rebuild _cid_index depuis store)
# ============================================================


def test_rebuild_from_store_on_init(cfg, tmp_paths):
    """Si store contient des positions au boot → listener rebuild _cid_index."""
    # Pre-populer store AVANT init listener
    pre_store = PositionStore(path=tmp_paths["store"])
    pre_store.open_position("ES", {
        "signal_id": "sig_recovery", "direction": "SHORT",
        "entry_price": 7580.5, "entry_ts": 1781000000000,
        "sl_price": 7582.0, "tp_price": 7578.25,
        "sl_ticks": 6, "tp_ticks": 9, "n_micros": 1,
        "parent_cid": "MIA_P_recov", "tp_cid": "MIA_TP_recov",
        "sl_cid": "MIA_SL_recov",
    })
    pre_store.save()
    # Reload store + init listener
    store2 = PositionStore(path=tmp_paths["store"])
    store2.load()
    bridge2 = StateBridge(path=tmp_paths["bridge"])
    listener = DtcFillListener(cfg, store2, bridge2)
    # _cid_index doit contenir 3 entries (parent + tp + sl)
    assert listener.n_tracked_brackets() == 3


def test_recovery_then_tp_fill_correct_pnl(cfg, tmp_paths):
    """Review BLOQUANT 2 : apres restart, fill TP doit calc PnL correct (pas ghost)."""
    pre_store = PositionStore(path=tmp_paths["store"])
    pre_store.open_position("ES", {
        "signal_id": "sig_recov", "direction": "SHORT",
        "entry_price": 7580.5, "entry_ts": 1781000000000,
        "sl_price": 7582.0, "tp_price": 7578.25,
        "sl_ticks": 6, "tp_ticks": 9, "n_micros": 1,
        "parent_cid": "MIA_P_recov", "tp_cid": "MIA_TP_recov",
        "sl_cid": "MIA_SL_recov",
    })
    pre_store.save()
    store2 = PositionStore(path=tmp_paths["store"])
    store2.load()
    bridge2 = StateBridge(path=tmp_paths["bridge"])
    # Bridge necessite open_by_symbol AVANT close — simule l'etat persisté.
    bridge2.open_position(
        "ES", direction="SHORT", entry_price=7580.5,
        sl_price=7582.0, tp_price=7578.25,
        sl_ticks=6, tp_ticks=9, signal_id="sig_recov",
        sl_wall="CUR_VAH", n_micros=1,
    )
    listener = DtcFillListener(cfg, store2, bridge2)
    listener.handle_order_update({
        "ClientOrderID": "MIA_TP_recov", "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 7578.25,
    })
    # AVANT fix : pnl_usd = ghost ~$9472 (entry_price=0)
    # APRES fix : pnl_usd = (7580.5 - 7578.25)/0.25 * 1.25 = 9t * $1.25 = $11.25
    assert store2.has_position("ES") is False
    last = bridge2.state["closed_today"][-1]
    assert abs(last["pnl_usd"] - 11.25) < 0.01, f"Got ghost PnL: {last['pnl_usd']}"
    assert last["pnl_ticks"] == 9.0


def test_bot_id_default_and_custom():
    """B : bot_id default = 'bot1v2', surchargeable au constructor."""
    cfg = Bot1V2Config.from_env()
    object.__setattr__(cfg, "TRADE_ACCOUNT", "Sim2")
    store = PositionStore()
    bridge = StateBridge()
    l1 = DtcFillListener(cfg, store, bridge)
    assert l1.bot_id == "bot1v2"
    l2 = DtcFillListener(cfg, store, bridge, bot_id="bot_mr")
    assert l2.bot_id == "bot_mr"
    l3 = DtcFillListener(cfg, store, bridge, bot_id="bot_bn_v4")
    assert l3.bot_id == "bot_bn_v4"


def test_emit_pair_double_legacy_and_mia(listener, store, state_bridge, monkeypatch):
    """B : _emit_pair emit legacy + MIA simultanement (1 trade = 2 logs)."""
    import CORE.bot1_v2.dtc_fill_listener as listener_module
    captured = []
    class FakeLog:
        def emit(self, code, **ctx):
            captured.append((code, ctx))
    monkeypatch.setattr(listener_module, "_log", FakeLog())
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid, "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 7578.25,
    })
    # On doit trouver BOTH BOT1V2_DTC_FILL_TP AND MIA_DTC_FILL_TP
    codes = [c for c, _ in captured]
    assert "BOT1V2_DTC_FILL_TP" in codes
    assert "MIA_DTC_FILL_TP" in codes
    # Le MIA_* doit inclure le bot field
    for code, ctx in captured:
        if code == "MIA_DTC_FILL_TP":
            assert ctx.get("bot") == "bot1v2"


def test_update_sl_cid_replaces_old_entry(listener, store, state_bridge):
    """A2 : update_sl_cid retire l'ancien CID + ajoute le nouveau avec memes details."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    new_sl_cid = "MIA_TRAIL_SL_xyz"
    ok = listener.update_sl_cid(sym="ES", old_sl_cid=sl_cid, new_sl_cid=new_sl_cid)
    assert ok is True
    # Ancien CID retire
    assert listener._cid_index.get(sl_cid) is None
    # Nouveau CID present avec kind=sl + details preserves
    new_entry = listener._cid_index.get(new_sl_cid)
    assert new_entry is not None
    assert new_entry["kind"] == "sl"
    assert new_entry["sym"] == "ES"
    assert new_entry["direction"] == "SHORT"
    assert new_entry["entry_price"] == 7580.5
    assert new_entry["n_micros"] == 1


def test_update_sl_cid_unknown_old_returns_false(listener):
    """update_sl_cid avec old_sl_cid inconnu → False, no-op."""
    ok = listener.update_sl_cid(sym="ES", old_sl_cid="UNKNOWN", new_sl_cid="MIA_NEW")
    assert ok is False
    assert listener.n_tracked_brackets() == 0


def test_update_sl_cid_empty_new_removes_only(listener, store, state_bridge):
    """update_sl_cid avec new_sl_cid vide → retire ancien sans ajouter (mode degrade alert)."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    n_before = listener.n_tracked_brackets()
    ok = listener.update_sl_cid(sym="ES", old_sl_cid=sl_cid, new_sl_cid="")
    assert ok is True
    assert listener.n_tracked_brackets() == n_before - 1


def test_new_sl_fill_closes_position_after_trailing_update(listener, store, state_bridge):
    """A4 integration : apres update_sl_cid, fill du nouveau SL ferme la position."""
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    # Trailing : nouveau SL @ 7581 (move 1t profitable pour SHORT)
    new_sl_cid = "MIA_TRAIL_SL_new"
    listener.update_sl_cid(sym="ES", old_sl_cid=sl_cid, new_sl_cid=new_sl_cid)
    # SL trailing touche : ORDER_UPDATE arrive avec le NOUVEAU CID
    listener.handle_order_update({
        "ClientOrderID": new_sl_cid,
        "TradeAccount": "Sim2",
        "OrderStatus": 7,
        "LastFillPrice": 7581.0,
    })
    # Position fermee, PnL = (7580.5 - 7581) / 0.25 = -2 ticks
    assert store.has_position("ES") is False
    last = state_bridge.state["closed_today"][-1]
    assert last["exit_reason"] == "SL"
    assert last["pnl_ticks"] == -2.0
    assert last["pnl_usd"] == -2.5  # -2t * $1.25 MICRO


def test_on_fill_close_updates_daily_gate(cfg, store, state_bridge):
    """Review BLOQUANT 3 : daily_gate.update_after_trade callé apres close.

    Sans ce maj, daily_stop_loss/win/max_trades ne se declenchent jamais
    (incident Douglas 04/06 reproduit).
    """
    from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
    gate = DailyLimitsGate(cfg)
    gate.reset_for_new_day("2026-06-17")
    captured = []
    def cb(sym, pnl_usd):
        gate.update_after_trade(pnl_usd)
        captured.append((sym, pnl_usd))
    parent_cid, tp_cid, sl_cid = _open_position(store, state_bridge)
    listener = DtcFillListener(cfg, store, state_bridge, on_close_callback=cb)
    _register(listener, "ES", "SHORT", parent_cid, tp_cid, sl_cid)
    listener.handle_order_update({
        "ClientOrderID": tp_cid, "TradeAccount": "Sim2",
        "OrderStatus": 7, "LastFillPrice": 7578.25,
    })
    assert gate.state.n_trades_today == 1
    assert abs(gate.state.cumul_pnl_usd - 11.25) < 0.01
    assert captured == [("ES", 11.25)]
