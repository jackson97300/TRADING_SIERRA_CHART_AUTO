"""Tests bot4_v2/execution/position_reconciler."""
from __future__ import annotations

import time
from typing import Optional

import pytest

from bot4_v2.execution.dtc_adapter import DTCAdapter, DTCSettings, OrderSide
from bot4_v2.execution.position_reconciler import (
    BotPositionState,
    PositionReconciler,
    ReconcilerSettings,
    ReconcilerTickResult,
)


# ============================================================
# Stubs
# ============================================================


class FakeDTCBackend:
    """Backend DTC fake.

    close_success : True -> send_close_market retourne close_cid
                    False -> retourne ""
    raise_on_close : raise sur send_close_market
    """

    def __init__(self, *, close_success: bool = True, raise_on_close: bool = False):
        self._close_success = close_success
        self._raise_on_close = raise_on_close
        self._connected = True
        self.close_calls: list = []

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def send_market_with_stop_only(self, symbol, side, quantity, sl_price,
                                   trade_account, signal_ref_price=0.0):
        return ("P_CID_001", "SL_CID_001", 20000.0)

    def send_close_market(self, symbol, side, quantity, trade_account):
        if self._raise_on_close:
            raise RuntimeError("simulated close fail")
        self.close_calls.append({
            "symbol": symbol, "side": side, "quantity": quantity,
        })
        return "C_CID_001" if self._close_success else ""

    def cancel_order(self, client_order_id, server_order_id="", trade_account=None):
        return True


def _make_reconciler(
    backend: Optional[FakeDTCBackend] = None,
    settings: Optional[ReconcilerSettings] = None,
) -> tuple[PositionReconciler, FakeDTCBackend]:
    backend = backend or FakeDTCBackend()
    dtc = DTCAdapter(backend=backend, settings=DTCSettings(dry_run=False))
    dtc.ensure_connected()
    rec = PositionReconciler(dtc, settings or ReconcilerSettings())
    return rec, backend


# ============================================================
# ReconcilerSettings validation
# ============================================================


def test_settings_defaults():
    s = ReconcilerSettings()
    assert s.heartbeat_interval_sec == 30.0
    assert s.stale_threshold_sec == 7200.0
    assert s.force_close_naked is True
    assert s.max_close_retries == 3


def test_settings_heartbeat_must_be_nonneg():
    with pytest.raises(ValueError, match="heartbeat_interval_sec"):
        ReconcilerSettings(heartbeat_interval_sec=-1)


def test_settings_stale_must_be_positive():
    with pytest.raises(ValueError, match="stale_threshold_sec"):
        ReconcilerSettings(stale_threshold_sec=0)


def test_settings_retries_must_be_nonneg():
    with pytest.raises(ValueError, match="max_close_retries"):
        ReconcilerSettings(max_close_retries=-1)


def test_settings_frozen():
    from dataclasses import FrozenInstanceError
    s = ReconcilerSettings()
    with pytest.raises(FrozenInstanceError):
        s.heartbeat_interval_sec = 5  # type: ignore


# ============================================================
# Init
# ============================================================


def test_init_requires_dtc():
    with pytest.raises(ValueError, match="dtc_adapter"):
        PositionReconciler(None)  # type: ignore


def test_init_default_settings():
    rec, _ = _make_reconciler()
    assert rec.settings.heartbeat_interval_sec == 30.0
    assert rec.n_positions == 0


# ============================================================
# BotPositionState frozen + is_naked
# ============================================================


def test_position_state_frozen():
    from dataclasses import FrozenInstanceError
    s = BotPositionState(symbol="NQ", parent_cid="P", sl_cid="S",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=time.time())
    with pytest.raises(FrozenInstanceError):
        s.quantity = 5  # type: ignore


def test_position_state_is_naked_via_flag():
    s = BotPositionState(symbol="NQ", parent_cid="P", sl_cid="X",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=time.time(), naked=True)
    assert s.is_naked is True


def test_position_state_is_naked_via_empty_sl_cid():
    s = BotPositionState(symbol="NQ", parent_cid="P", sl_cid="",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=time.time())
    assert s.is_naked is True


def test_position_state_not_naked_with_sl_cid():
    s = BotPositionState(symbol="NQ", parent_cid="P", sl_cid="SL_X",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=time.time())
    assert s.is_naked is False


# ============================================================
# register_bracket / mark_closed
# ============================================================


def test_register_bracket_basic():
    rec, _ = _make_reconciler()
    ok = rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                                direction="LONG", quantity=1, fill_price=20000.0)
    assert ok is True
    assert rec.n_positions == 1
    state = rec.positions()["P1"]
    assert state.symbol == "NQ"
    assert state.direction == "LONG"


def test_register_bracket_rejects_empty_parent_cid():
    rec, _ = _make_reconciler()
    with pytest.raises(ValueError, match="parent_cid"):
        rec.register_bracket(symbol="NQ", parent_cid="", sl_cid="S",
                              direction="LONG", quantity=1, fill_price=20000.0)


def test_register_bracket_rejects_invalid_direction():
    rec, _ = _make_reconciler()
    with pytest.raises(ValueError, match="direction"):
        rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                              direction="HOLD", quantity=1, fill_price=20000.0)


def test_register_bracket_rejects_zero_quantity():
    rec, _ = _make_reconciler()
    with pytest.raises(ValueError, match="quantity"):
        rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                              direction="LONG", quantity=0, fill_price=20000.0)


def test_register_bracket_duplicate_returns_false():
    rec, _ = _make_reconciler()
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0)
    ok = rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                                direction="LONG", quantity=1, fill_price=20000.0)
    assert ok is False
    assert rec.n_positions == 1  # still 1


def test_register_bracket_naked_flag():
    rec, _ = _make_reconciler()
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          naked=True)
    state = rec.positions()["P1"]
    assert state.is_naked is True


def test_mark_closed_removes_position():
    rec, _ = _make_reconciler()
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0)
    ok = rec.mark_closed("P1", reason="target_hit")
    assert ok is True
    assert rec.n_positions == 0


def test_mark_closed_absent_returns_false():
    rec, _ = _make_reconciler()
    ok = rec.mark_closed("NOT_EXIST")
    assert ok is False


# ============================================================
# reconcile_naked : force-close PRIORITY 1
# ============================================================


def test_reconcile_naked_empty_returns_zero():
    rec, _ = _make_reconciler()
    n = rec.reconcile_naked(naked_parent_cids=(), symbol="NQ")
    assert n == 0


def test_reconcile_naked_settings_disabled_returns_zero():
    settings = ReconcilerSettings(force_close_naked=False)
    rec, backend = _make_reconciler(settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="",
                          direction="LONG", quantity=1, fill_price=20000.0)
    n = rec.reconcile_naked(naked_parent_cids=("P1",), symbol="NQ")
    assert n == 0
    assert backend.close_calls == []


def test_reconcile_naked_skips_unregistered():
    """Position pas registered -> skip (anti close direction wrong)."""
    rec, backend = _make_reconciler()
    n = rec.reconcile_naked(naked_parent_cids=("UNKNOWN_CID",), symbol="NQ")
    assert n == 0
    assert backend.close_calls == []


def test_reconcile_naked_force_close_long():
    """LONG naked -> close avec side=SELL (inverse)."""
    rec, backend = _make_reconciler()
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="",
                          direction="LONG", quantity=2, fill_price=20000.0)
    n = rec.reconcile_naked(naked_parent_cids=("P1",), symbol="NQ")
    assert n == 1
    assert len(backend.close_calls) == 1
    assert backend.close_calls[0]["side"] == OrderSide.SELL.dtc_int
    assert backend.close_calls[0]["quantity"] == 2
    assert rec.n_positions == 0  # mark_closed apres force-close


def test_reconcile_naked_force_close_short():
    """SHORT naked -> close avec side=BUY."""
    rec, backend = _make_reconciler()
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="",
                          direction="SHORT", quantity=1, fill_price=20000.0)
    n = rec.reconcile_naked(naked_parent_cids=("P1",), symbol="NQ")
    assert n == 1
    assert backend.close_calls[0]["side"] == OrderSide.BUY.dtc_int


def test_reconcile_naked_close_fail_retries():
    """Close fail -> retries max_close_retries fois."""
    backend = FakeDTCBackend(close_success=False)
    settings = ReconcilerSettings(max_close_retries=3, close_retry_delay_sec=0.0)
    rec, _ = _make_reconciler(backend=backend, settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="",
                          direction="LONG", quantity=1, fill_price=20000.0)
    n = rec.reconcile_naked(naked_parent_cids=("P1",), symbol="NQ")
    assert n == 0
    assert len(backend.close_calls) == 3  # 3 retries
    assert rec.n_positions == 1  # PAS retire


def test_reconcile_naked_close_exception_caught():
    """Exception close -> retry, no crash."""
    backend = FakeDTCBackend(raise_on_close=True)
    settings = ReconcilerSettings(max_close_retries=2, close_retry_delay_sec=0.0)
    rec, _ = _make_reconciler(backend=backend, settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="",
                          direction="LONG", quantity=1, fill_price=20000.0)
    n = rec.reconcile_naked(naked_parent_cids=("P1",), symbol="NQ")
    assert n == 0  # all fail
    assert rec.n_positions == 1


def test_reconcile_naked_multiple_brackets():
    rec, backend = _make_reconciler()
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="",
                          direction="LONG", quantity=1, fill_price=20000.0)
    rec.register_bracket(symbol="NQ", parent_cid="P2", sl_cid="",
                          direction="SHORT", quantity=1, fill_price=20010.0)
    n = rec.reconcile_naked(naked_parent_cids=("P1", "P2"), symbol="NQ")
    assert n == 2
    assert len(backend.close_calls) == 2


# ============================================================
# tick() heartbeat + stale detection
# ============================================================


def test_tick_first_call_runs_immediate():
    """Premier tick (last_heartbeat=0) -> run immediat."""
    rec, _ = _make_reconciler()
    result = rec.tick(now=100.0)
    assert isinstance(result, ReconcilerTickResult)
    assert result.skipped_heartbeat is False


def test_tick_throttle_within_interval():
    """Tick a t=10 puis t=20 < interval=30 -> skip."""
    settings = ReconcilerSettings(heartbeat_interval_sec=30.0,
                                    stale_threshold_sec=7200.0)
    rec, _ = _make_reconciler(settings=settings)
    rec.tick(now=10.0)
    result2 = rec.tick(now=20.0)
    assert result2.skipped_heartbeat is True


def test_tick_runs_after_interval():
    settings = ReconcilerSettings(heartbeat_interval_sec=30.0,
                                    stale_threshold_sec=7200.0)
    rec, _ = _make_reconciler(settings=settings)
    rec.tick(now=10.0)
    result2 = rec.tick(now=50.0)  # 40s elapsed > 30s
    assert result2.skipped_heartbeat is False


def test_tick_no_positions_no_stale():
    rec, _ = _make_reconciler()
    result = rec.tick(now=100.0)
    assert result.n_positions_tracked == 0
    assert result.n_stale_detected == 0


def test_tick_detects_stale_position():
    """Position ouverte > stale_threshold -> detected."""
    settings = ReconcilerSettings(heartbeat_interval_sec=0.0,
                                    stale_threshold_sec=60.0,
                                    close_retry_delay_sec=0.0)
    rec, _ = _make_reconciler(settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=100.0)
    # Tick a t=200 -> age=100s > stale=60s
    result = rec.tick(now=200.0)
    assert result.n_stale_detected == 1


def test_tick_stale_force_close_success():
    """Stale + close OK -> mark_closed automatique."""
    settings = ReconcilerSettings(heartbeat_interval_sec=0.0,
                                    stale_threshold_sec=60.0,
                                    close_retry_delay_sec=0.0)
    rec, backend = _make_reconciler(settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=100.0)
    result = rec.tick(now=200.0)
    assert result.n_stale_force_closed == 1
    assert "P1" in result.parent_cids_force_closed
    assert rec.n_positions == 0
    assert len(backend.close_calls) == 1


def test_tick_stale_force_close_failure_keeps_position():
    """Stale + close FAIL -> position garde trackee pour prochain heartbeat."""
    settings = ReconcilerSettings(heartbeat_interval_sec=0.0,
                                    stale_threshold_sec=60.0,
                                    close_retry_delay_sec=0.0)
    backend = FakeDTCBackend(close_success=False)
    rec, _ = _make_reconciler(backend=backend, settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=100.0)
    result = rec.tick(now=200.0)
    assert result.n_stale_detected == 1
    assert result.n_stale_force_closed == 0
    assert rec.n_positions == 1


def test_tick_non_stale_positions_untouched():
    """Position recente (age < stale) -> pas touche."""
    settings = ReconcilerSettings(heartbeat_interval_sec=0.0,
                                    stale_threshold_sec=7200.0)
    rec, backend = _make_reconciler(settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=100.0)
    result = rec.tick(now=200.0)  # age=100 < 7200
    assert result.n_stale_detected == 0
    assert rec.n_positions == 1
    assert backend.close_calls == []


# ============================================================
# ReconcilerTickResult immutable
# ============================================================


def test_tick_result_immutable():
    from dataclasses import FrozenInstanceError
    r = ReconcilerTickResult(n_positions_tracked=2)
    with pytest.raises(FrozenInstanceError):
        r.n_positions_tracked = 5  # type: ignore


def test_tick_result_defaults():
    r = ReconcilerTickResult()
    assert r.n_positions_tracked == 0
    assert r.skipped_heartbeat is False
    assert r.parent_cids_force_closed == ()


# ============================================================
# Logs catalog : codes BOT4V2_RECONCILER_* registered
# ============================================================


def test_log_codes_reconciler_registered():
    """Verifie codes BOT4V2_RECONCILER_* presents log_catalog."""
    from CORE.log_catalog import LOG_CODES
    expected = {
        "BOT4V2_RECONCILER_NAKED_FORCE_CLOSE",
        "BOT4V2_RECONCILER_NAKED_CLOSE_OK",
        "BOT4V2_RECONCILER_NAKED_CLOSE_FAIL",
        "BOT4V2_RECONCILER_NAKED_SKIP_UNREGISTERED",  # R1 review P4
        "BOT4V2_RECONCILER_REGISTER_BRACKET",
        "BOT4V2_RECONCILER_MARK_CLOSED",
        "BOT4V2_RECONCILER_STALE_DETECTED",
        "BOT4V2_RECONCILER_STALE_FORCE_CLOSE",
        "BOT4V2_RECONCILER_STALE_CLOSE_FAIL",  # R1 review P4 (separe de naked)
        "BOT4V2_RECONCILER_HEARTBEAT",
        "BOT4V2_RECONCILER_HEARTBEAT_SKIP",
        "BOT4V2_RECONCILER_REGISTER_DUPLICATE",
    }
    missing = expected - set(LOG_CODES.keys())
    assert missing == set(), f"Missing log codes: {missing}"


# ============================================================
# R1 review : NAKED_SKIP_UNREGISTERED distinct de NAKED_CLOSE_FAIL
# ============================================================


def test_r1_unregistered_naked_emits_skip_code(caplog):
    """Position not registered -> emit NAKED_SKIP_UNREGISTERED, pas NAKED_CLOSE_FAIL."""
    import logging
    rec, _ = _make_reconciler()
    with caplog.at_level(logging.INFO,
                          logger="bot4_v2.execution.position_reconciler"):
        rec.reconcile_naked(naked_parent_cids=("UNKNOWN_CID",), symbol="NQ")
    # Le code emis doit etre SKIP, pas CLOSE_FAIL (anti silent fail R1)
    msgs = [r.message for r in caplog.records]
    assert any("NAKED skip" in m or "position_not_registered" in m for m in msgs), msgs


# ============================================================
# R2 review : Stale a meme retry policy que NAKED (DRY)
# ============================================================


def test_r2_stale_close_fail_retries_full_max():
    """Stale close fail -> retries jusqu'a max_close_retries (DRY avec naked)."""
    settings = ReconcilerSettings(
        heartbeat_interval_sec=0.0,
        stale_threshold_sec=60.0,
        max_close_retries=3,
        close_retry_delay_sec=0.0,
    )
    backend = FakeDTCBackend(close_success=False)
    rec, _ = _make_reconciler(backend=backend, settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=100.0)
    result = rec.tick(now=200.0)
    assert result.n_stale_detected == 1
    assert result.n_stale_force_closed == 0
    # 3 retries effectues par send_close_with_retries (DRY)
    assert len(backend.close_calls) == 3


def test_r2_stale_close_fail_emits_stale_code(caplog):
    """Stale fail -> emit STALE_CLOSE_FAIL (R1 fix anti pollution metriques J+1)."""
    import logging
    settings = ReconcilerSettings(
        heartbeat_interval_sec=0.0,
        stale_threshold_sec=60.0,
        max_close_retries=1,
        close_retry_delay_sec=0.0,
    )
    backend = FakeDTCBackend(close_success=False)
    rec, _ = _make_reconciler(backend=backend, settings=settings)
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0,
                          opened_ts=100.0)
    with caplog.at_level(logging.INFO,
                          logger="bot4_v2.execution.position_reconciler"):
        rec.tick(now=200.0)
    # STALE_CLOSE_FAIL code emis, PAS NAKED_CLOSE_FAIL
    msgs = [r.message for r in caplog.records]
    assert any("STALE close FAIL" in m for m in msgs), msgs
    assert not any("NAKED close FAIL" in m for m in msgs), msgs


# ============================================================
# Defensive copy positions()
# ============================================================


def test_positions_returns_defensive_copy():
    rec, _ = _make_reconciler()
    rec.register_bracket(symbol="NQ", parent_cid="P1", sl_cid="S1",
                          direction="LONG", quantity=1, fill_price=20000.0)
    snapshot = rec.positions()
    snapshot.clear()  # mutation external
    assert rec.n_positions == 1  # interne intact


# ============================================================
# Integration : router naked_brackets_pending -> reconciler force-close
# ============================================================


def test_integration_router_to_reconciler_naked_flow():
    """E2E : router naked detected -> reconciler force-close."""
    from bot4_v2.decision.decision_router import (
        DecisionRouter, RouterSettings,
    )
    from bot4_v2.decision.scenario_registry import ScenarioRegistry
    from bot4_v2.decision.scenarios.bearish_rejection import BearishRejectionDetector

    # Build router avec backend naked
    class NakedBackend(FakeDTCBackend):
        def send_market_with_stop_only(self, symbol, side, quantity, sl_price,
                                        trade_account, signal_ref_price=0.0):
            # Naked : parent OK, sl_cid empty
            return ("P_NAKED_001", "", 20000.0)

    backend = NakedBackend()
    dtc = DTCAdapter(backend=backend, settings=DTCSettings(dry_run=False))
    dtc.ensure_connected()

    # Reconciler
    reconciler = PositionReconciler(dtc)
    # Register la position simulee (router emit naked + caller register)
    reconciler.register_bracket(
        symbol="NQ", parent_cid="P_NAKED_001", sl_cid="",
        direction="SHORT", quantity=1, fill_price=20000.0, naked=True,
    )
    # Simule RouterTickResult.naked_brackets_pending
    naked_cids = ("P_NAKED_001",)
    n = reconciler.reconcile_naked(naked_parent_cids=naked_cids, symbol="NQ")
    assert n == 1
    assert len(backend.close_calls) == 1
    assert reconciler.n_positions == 0
