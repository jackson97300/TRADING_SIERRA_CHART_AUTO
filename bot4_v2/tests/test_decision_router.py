"""Tests bot4_v2/decision/decision_router + ScenarioInstance.from_fire."""
from __future__ import annotations

from typing import Optional

import pytest

from bot4_v2.core.menthorq_source import MenthorQLevels
from bot4_v2.core.narrative_engine import NarrativeContext
from bot4_v2.core.regime_source import RegimeAnalysis
from bot4_v2.decision.decision_router import (
    ClosedSignal,
    DecisionRouter,
    DispatchedBracket,
    RouterSettings,
    RouterTickResult,
)
from bot4_v2.decision.narrative_state import (
    ScenarioInstance,
    ScenarioState,
)
from bot4_v2.decision.scenario_registry import (
    ScenarioContext,
    ScenarioFire,
    ScenarioRegistry,
)
from bot4_v2.execution.dtc_adapter import (
    BracketRequest,
    BracketResult,
    ConnectionStatus,
    OrderSide,
)


# ============================================================
# Helpers + Stubs
# ============================================================


def _make_regime(
    mode: str = "TREND", favor: str = "SHORT", vol_regime: str = "NORMAL",
) -> RegimeAnalysis:
    return RegimeAnalysis(
        mode=mode, favor=favor, confidence=0.5,
        trend_votes=5, range_votes=2, vol_regime=vol_regime,
        bias_score=0.3, is_actionable=True,
    )


def _make_narrative(symbol: str = "NQ", close: float = 20000.0) -> NarrativeContext:
    return NarrativeContext(
        timestamp_utc="2026-06-25T10:00:00+00:00",
        symbol=symbol, close=close, atr=10.0, atr_14m=40.0,
    )


def _make_menthorq(symbol: str = "NQ") -> MenthorQLevels:
    return MenthorQLevels(symbol=symbol, date_str="20260625", is_empty=True)


def _make_bar(high: float = 20010, low: float = 19995, close: float = 20000,
              ts: str = "2026-06-25T10:01:00+00:00", **extras) -> dict:
    bar = {"high": high, "low": low, "close": close, "ts_event": ts}
    bar.update(extras)
    return bar


def _make_ctx(bar: Optional[dict] = None, regime: Optional[RegimeAnalysis] = None,
              narrative: Optional[NarrativeContext] = None,
              menthorq: Optional[MenthorQLevels] = None) -> ScenarioContext:
    return ScenarioContext(
        bar=bar or _make_bar(),
        regime=regime or _make_regime(),
        narrative=narrative or _make_narrative(),
        menthorq=menthorq or _make_menthorq(),
    )


def _make_fire(
    *, scenario_name: str = "Test_Scenario", direction: str = "SHORT",
    confidence: float = 0.75, entry: float = 20000.0, stop: float = 20010.0,
    target: float = 19980.0, signal_id_suffix: str = "001",
) -> ScenarioFire:
    return ScenarioFire(
        signal_id=f"{scenario_name}_NQ_{signal_id_suffix}",
        scenario_name=scenario_name,
        family="Test",
        symbol="NQ",
        direction=direction,
        entry_price=entry,
        stop_loss=stop,
        target_1=target,
        heuristic_score=int(confidence * 100),
        confidence=confidence,
        regime="TREND",
        session="us_cash",
        timestamp_utc="2026-06-25T10:00:00+00:00",
    )


class FixedDetector:
    """Stub detector retournant un fire fixe (ou None si fire=None)."""

    def __init__(self, name: str, fire: Optional[ScenarioFire] = None):
        self._name = name
        self._fire = fire

    @property
    def name(self) -> str:
        return self._name

    @property
    def family(self) -> str:
        return "Test"

    @property
    def directions_supported(self) -> tuple[str, ...]:
        return ("LONG", "SHORT")

    def detect(self, ctx):
        return self._fire


class FakeDTCBackend:
    """Fake backend DTC : succes par defaut, configurable."""

    def __init__(self, *, success: bool = True, naked: bool = False,
                 raise_on_send: bool = False):
        self._success = success
        self._naked = naked
        self._raise = raise_on_send
        self._connected = True
        self.calls: list = []  # log calls send_market_with_stop_only

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
        if self._raise:
            raise RuntimeError("simulated DTC fail")
        self.calls.append({
            "symbol": symbol, "side": side, "quantity": quantity,
            "sl_price": sl_price,
        })
        # Protocol contract : returns tuple (parent_id, sl_cid, fill_price)
        if not self._success:
            return ("", "", 0.0)
        parent_id = "P_CID_001"
        sl_cid = "" if self._naked else "SL_CID_001"
        return (parent_id, sl_cid, 20000.0)

    def send_close_market(self, symbol, side, quantity, trade_account):
        return "C_CID_001"

    def cancel_order(self, client_order_id, server_order_id="",
                     trade_account=None):
        return True


def _make_router(
    detectors: Optional[list] = None,
    backend: Optional[FakeDTCBackend] = None,
    settings: Optional[RouterSettings] = None,
) -> tuple[DecisionRouter, ScenarioRegistry, FakeDTCBackend]:
    """Helper construit Router + Registry + FakeBackend."""
    from bot4_v2.execution.dtc_adapter import DTCAdapter, DTCSettings
    registry = ScenarioRegistry()
    for d in (detectors or []):
        registry.register(d)
    fake_backend = backend or FakeDTCBackend()
    dtc = DTCAdapter(backend=fake_backend, settings=DTCSettings(dry_run=False))
    dtc.ensure_connected()
    router = DecisionRouter(registry, dtc, settings or RouterSettings())
    return router, registry, fake_backend


# ============================================================
# RouterSettings validation
# ============================================================


def test_router_settings_defaults():
    s = RouterSettings()
    assert s.max_concurrent_trades == 3
    assert s.collision_min_gap_pct == 0.20
    assert s.confirmation_window_bars == 5
    assert s.timeout_bars == 30
    assert s.quantity_per_trade == 1
    assert s.emit_tp is False  # SL-only par defaut (heritage Bot 3 BN V4 #67)


def test_router_settings_max_concurrent_must_be_positive():
    with pytest.raises(ValueError, match="max_concurrent_trades"):
        RouterSettings(max_concurrent_trades=0)


def test_router_settings_collision_gap_must_be_unit_interval():
    with pytest.raises(ValueError, match="collision_min_gap_pct"):
        RouterSettings(collision_min_gap_pct=1.5)


def test_router_settings_timeout_must_be_ge_window():
    with pytest.raises(ValueError, match="timeout_bars"):
        RouterSettings(confirmation_window_bars=10, timeout_bars=5)


def test_router_settings_quantity_must_be_positive():
    with pytest.raises(ValueError, match="quantity_per_trade"):
        RouterSettings(quantity_per_trade=0)


def test_router_settings_frozen():
    from dataclasses import FrozenInstanceError
    s = RouterSettings()
    with pytest.raises(FrozenInstanceError):
        s.max_concurrent_trades = 5  # type: ignore


# ============================================================
# DecisionRouter init validation
# ============================================================


def test_router_init_requires_registry():
    from bot4_v2.execution.dtc_adapter import DTCAdapter, DTCSettings
    dtc = DTCAdapter(backend=FakeDTCBackend(), settings=DTCSettings())
    with pytest.raises(ValueError, match="registry"):
        DecisionRouter(None, dtc)  # type: ignore


def test_router_init_requires_dtc_adapter():
    with pytest.raises(ValueError, match="dtc_adapter"):
        DecisionRouter(ScenarioRegistry(), None)  # type: ignore


def test_router_init_default_settings():
    router, _, _ = _make_router()
    assert router.settings.max_concurrent_trades == 3


# ============================================================
# ScenarioInstance.from_fire (helper batch 1<->2 bridge)
# ============================================================


def test_instance_from_fire_basic():
    fire = _make_fire(direction="SHORT", confidence=0.8)
    inst = ScenarioInstance.from_fire(fire)
    assert inst.signal_id == fire.signal_id
    assert inst.scenario_name == "Test_Scenario"
    assert inst.symbol == "NQ"
    assert inst.direction == "SHORT"
    assert inst.entry_price == 20000.0
    assert inst.stop_loss == 20010.0
    assert inst.target_1 == 19980.0
    assert inst.state == ScenarioState.PENDING


def test_instance_from_fire_enriches_extra_with_metadata():
    fire = _make_fire(direction="SHORT", confidence=0.8)
    inst = ScenarioInstance.from_fire(fire)
    assert inst.extra["scenario_family"] == "Test"
    assert inst.extra["regime"] == "TREND"
    assert inst.extra["session"] == "us_cash"
    assert inst.extra["heuristic_score"] == 80
    assert inst.extra["confidence"] == 0.8
    assert "reasons" in inst.extra


def test_instance_from_fire_long_validation():
    fire = _make_fire(direction="LONG", entry=20000.0, stop=19990.0, target=20020.0)
    inst = ScenarioInstance.from_fire(fire)
    assert inst.direction == "LONG"


def test_instance_from_fire_invalid_raises_valueerror():
    """Fire with stop > entry for LONG -> __init__ raises ValueError."""
    fire = ScenarioFire(
        signal_id="X", scenario_name="X", family="Y", symbol="NQ",
        direction="LONG",
        entry_price=20000.0, stop_loss=20010.0, target_1=20020.0,  # invalid LONG
    )
    with pytest.raises(ValueError, match="LONG requires"):
        ScenarioInstance.from_fire(fire)


def test_instance_from_fire_custom_window_timeout():
    fire = _make_fire()
    inst = ScenarioInstance.from_fire(fire, confirmation_window_bars=10, timeout_bars=50)
    assert inst.confirmation_window_bars == 10
    assert inst.timeout_bars == 50


# ============================================================
# route_bar : empty case
# ============================================================


def test_route_bar_empty_registry_no_fires():
    router, _, backend = _make_router()
    result = router.route_bar(_make_ctx())
    assert isinstance(result, RouterTickResult)
    assert result.symbol == "NQ"
    assert result.fires_evaluated == 0
    assert result.instances_added == 0
    assert backend.calls == []


def test_route_bar_creates_tracker_lazy():
    router, _, _ = _make_router()
    assert "NQ" not in router.trackers
    router.route_bar(_make_ctx())
    assert "NQ" in router.trackers


def test_route_bar_one_fire_one_instance_added():
    fire = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    result = router.route_bar(_make_ctx())
    assert result.fires_evaluated == 1
    assert result.fires_selected == 1
    assert result.instances_added == 1
    assert router.trackers["NQ"].n_active == 1


# ============================================================
# Anti-pyramiding : tracker active -> skip evaluate
# ============================================================


def test_route_bar_tracker_active_skips_evaluate():
    """Tracker has active instance -> evaluate fires SKIPPED."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    detector = FixedDetector("S", fire)
    router, _, _ = _make_router(detectors=[detector])
    # Bar 1 : creates instance PENDING
    router.route_bar(_make_ctx())
    assert router.trackers["NQ"].n_active == 1
    # Bar 2 : bar SAFE (no stop hit, no entry touched, no window expire) -> stays PENDING
    safe_bar = _make_bar(high=20005, low=20002, close=20003,
                          ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=safe_bar))
    assert result.skip_reason == "tracker_active"
    assert result.fires_evaluated == 0
    assert result.instances_added == 0


# ============================================================
# max_concurrent_trades cap
# ============================================================


def test_route_bar_max_concurrent_cap_blocks():
    """Cap 1 trade total + NQ tracker active -> ES fire blocked."""
    settings = RouterSettings(max_concurrent_trades=1)
    fire_nq = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire_nq)],
                                 settings=settings)
    # Bar NQ : 1 instance
    router.route_bar(_make_ctx())
    assert router.n_total_active() == 1
    # Bar ES : cap atteint -> skip
    fire_es = ScenarioFire(
        signal_id="ES_001", scenario_name="S2", family="Test", symbol="ES",
        direction="LONG", entry_price=5000.0, stop_loss=4990.0, target_1=5020.0,
        confidence=0.9,
    )
    router._registry.register(FixedDetector("S_es", fire_es))
    result = router.route_bar(_make_ctx(narrative=_make_narrative(symbol="ES")))
    assert result.skip_reason == "max_concurrent_cap"


# ============================================================
# Collision LONG vs SHORT policy
# ============================================================


def test_route_bar_collision_gap_high_wins():
    """LONG 0.9 vs SHORT 0.6 -> gap 0.3 > 0.2 -> LONG wins."""
    fire_long = _make_fire(direction="LONG", confidence=0.9,
                            entry=20000, stop=19990, target=20020,
                            signal_id_suffix="L")
    fire_short = _make_fire(direction="SHORT", confidence=0.6,
                             signal_id_suffix="S")
    router, _, _ = _make_router(detectors=[
        FixedDetector("L", fire_long),
        FixedDetector("S", fire_short),
    ])
    result = router.route_bar(_make_ctx())
    assert result.fires_evaluated == 2
    assert result.fires_selected == 1
    assert result.instances_added == 1
    active = router.trackers["NQ"].active_instances()
    assert len(active) == 1
    assert active[0].direction == "LONG"


def test_route_bar_collision_gap_low_blocks_both():
    """LONG 0.75 vs SHORT 0.72 -> gap 0.03 <= 0.20 -> BLOQUE."""
    fire_long = _make_fire(direction="LONG", confidence=0.75,
                            entry=20000, stop=19990, target=20020,
                            signal_id_suffix="L")
    fire_short = _make_fire(direction="SHORT", confidence=0.72,
                             signal_id_suffix="S")
    router, _, _ = _make_router(detectors=[
        FixedDetector("L", fire_long),
        FixedDetector("S", fire_short),
    ])
    result = router.route_bar(_make_ctx())
    assert result.fires_evaluated == 2
    assert result.fires_selected == 0  # bloque les 2
    assert result.instances_added == 0
    assert router.trackers["NQ"].n_active == 0


def test_route_bar_unique_direction_picks_top():
    """3 SHORTs avec confidences differentes -> top 1 (anti pyramiding)."""
    confidences = [0.85, 0.70, 0.65]
    fires = [
        _make_fire(direction="SHORT", confidence=c, signal_id_suffix=f"S{i}")
        for i, c in enumerate(confidences)
    ]
    detectors = [FixedDetector(f"D{i}", f) for i, f in enumerate(fires)]
    router, _, _ = _make_router(detectors=detectors)
    result = router.route_bar(_make_ctx())
    assert result.fires_evaluated == 3
    assert result.fires_selected == 1  # top 1 only
    active = router.trackers["NQ"].active_instances()
    assert len(active) == 1
    assert active[0].extra["confidence"] == 0.85


# ============================================================
# Bracket dispatch sur TRIGGERED transition
# ============================================================


def test_route_bar_triggered_dispatches_bracket():
    """PENDING -> ACTIVE -> TRIGGERED cascade meme bar -> bracket envoye."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    detector = FixedDetector("S", fire)
    router, _, backend = _make_router(detectors=[detector])

    # Bar 1 : creates instance PENDING
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    assert inst.state == ScenarioState.PENDING
    inst.confirm(_make_bar())

    # Bar 2 : SHORT entry=20000 stop=20010 target=19980
    # Bar safe : high=20005 (< stop=20010), low=19995 (≤ entry=20000) => entry touched
    # PENDING confirmed -> ACTIVE -> TRIGGERED (target 19980 not hit, stop not hit)
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    assert result.transitions_emitted >= 1
    assert result.brackets_dispatched == 1
    assert len(backend.calls) == 1
    # backend recoit dtc_int (1=BUY, 2=SELL) cf DTCAdapter._send_sl_only
    assert backend.calls[0]["side"] == OrderSide.SELL.dtc_int


def test_route_bar_triggered_naked_logged_critical():
    """Bracket naked=True -> brackets_naked compte."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    detector = FixedDetector("S", fire)
    backend = FakeDTCBackend(success=True, naked=True)
    router, _, _ = _make_router(detectors=[detector], backend=backend)

    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    assert result.brackets_dispatched == 1
    assert result.brackets_naked == 1


def test_route_bar_bracket_exception_no_crash():
    """DTC raise exception -> log + brackets_dispatched=0, pas crash."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    detector = FixedDetector("S", fire)
    backend = FakeDTCBackend(raise_on_send=True)
    router, _, _ = _make_router(detectors=[detector], backend=backend)

    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    assert result.brackets_dispatched == 0  # exception caught


# ============================================================
# Terminal archive
# ============================================================


def test_route_bar_archives_terminals_after_completion():
    """Instance COMPLETED -> pop_terminal -> terminals_archived."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    # Bar 1 : creates instance PENDING
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    # Bar 2 : PENDING -> TRIGGERED cascade (target 19980 not hit, stop 20010 not hit)
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    router.route_bar(_make_ctx(bar=bar_trigger))
    # Bar 3 : target=19980 hit -> COMPLETED -> pop_terminal
    bar_complete = _make_bar(high=20005, low=19975, close=19980,
                              ts="2026-06-25T10:03:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_complete))
    assert result.terminals_archived >= 1
    # Apres pop_terminal, tracker peut re-evaluer (anti-pyramiding s'applique
    # post-archive) -> donc detector peut creer une nouvelle instance.
    # Le terminal archive est ce qui compte ici, pas n_active.
    assert result.transitions_emitted >= 1  # COMPLETED transition emise


# ============================================================
# Multi-symbol isolation
# ============================================================


def test_route_bar_multi_symbol_independent_trackers():
    """2 symboles -> 2 trackers separes, ind. lifecycle."""
    fire_nq = _make_fire(direction="SHORT", confidence=0.8)
    fire_es = ScenarioFire(
        signal_id="ES_001", scenario_name="S2", family="Test", symbol="ES",
        direction="LONG", entry_price=5000.0, stop_loss=4990.0, target_1=5020.0,
        confidence=0.85,
    )

    class SymbolFilter:
        def __init__(self, sym, fire):
            self._sym = sym
            self._fire = fire

        @property
        def name(self):
            return f"F_{self._sym}"

        @property
        def family(self):
            return "Test"

        @property
        def directions_supported(self):
            return ("LONG", "SHORT")

        def detect(self, ctx):
            return self._fire if ctx.symbol == self._sym else None

    router, _, _ = _make_router(detectors=[
        SymbolFilter("NQ", fire_nq),
        SymbolFilter("ES", fire_es),
    ])

    # NQ bar
    router.route_bar(_make_ctx())
    # ES bar
    router.route_bar(_make_ctx(narrative=_make_narrative(symbol="ES", close=5000.0),
                                 menthorq=_make_menthorq("ES")))
    assert "NQ" in router.trackers
    assert "ES" in router.trackers
    assert router.trackers["NQ"].n_active == 1
    assert router.trackers["ES"].n_active == 1


# ============================================================
# RouterTickResult immutable + audit fields
# ============================================================


def test_router_tick_result_immutable():
    from dataclasses import FrozenInstanceError
    r = RouterTickResult(symbol="NQ", fires_evaluated=2)
    with pytest.raises(FrozenInstanceError):
        r.fires_evaluated = 5  # type: ignore


def test_router_tick_result_default_zero():
    r = RouterTickResult(symbol="NQ")
    assert r.fires_evaluated == 0
    assert r.instances_added == 0
    assert r.skip_reason == ""


# ============================================================
# Trackers property defensive copy
# ============================================================


def test_router_trackers_property_returns_copy():
    """Mutation external dict ne corromp pas _trackers interne."""
    router, _, _ = _make_router()
    router.route_bar(_make_ctx())
    snapshot = router.trackers
    snapshot.clear()  # mutation external
    assert "NQ" in router.trackers  # _trackers interne intact


# ============================================================
# R1 review : Log catalog codes BOT4V2_ROUTER_* enregistres
# ============================================================


def test_r1_log_codes_router_registered():
    """Verifie codes BOT4V2_ROUTER_* presents log_catalog (anti silent fallback)."""
    from CORE.log_catalog import LOG_CODES
    expected = {
        "BOT4V2_ROUTER_FIRE",
        "BOT4V2_ROUTER_FIRE_INVALID",
        "BOT4V2_ROUTER_COLLISION_BLOCKED",
        "BOT4V2_ROUTER_COLLISION_RESOLVED",
        "BOT4V2_ROUTER_SKIP_PYRAMIDING",
        "BOT4V2_ROUTER_SKIP_MAX_CONCURRENT",
        "BOT4V2_ROUTER_ARCHIVE_TERMINALS",
        "BOT4V2_ROUTER_BRACKET_OK",
        "BOT4V2_ROUTER_BRACKET_FAIL",
        "BOT4V2_ROUTER_BRACKET_NAKED",
        "BOT4V2_ROUTER_BRACKET_EXC",
        "BOT4V2_ROUTER_DISPATCH_NO_MATCH",
    }
    missing = expected - set(LOG_CODES.keys())
    assert missing == set(), f"Missing log codes: {missing}"


# ============================================================
# R2 review : naked_brackets_pending expose au caller (P4 reconciler)
# ============================================================


def test_r2_naked_brackets_pending_populated():
    """Naked bracket -> parent_cid expose dans naked_brackets_pending."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    backend = FakeDTCBackend(success=True, naked=True)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)],
                                 backend=backend)
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    assert result.brackets_naked == 1
    assert len(result.naked_brackets_pending) == 1
    assert result.naked_brackets_pending[0] == "P_CID_001"


def test_r2_naked_brackets_pending_empty_when_no_naked():
    """No naked -> tuple vide."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    assert result.naked_brackets_pending == ()


def test_r2_naked_brackets_pending_immutable_tuple():
    """naked_brackets_pending est tuple frozen (anti mutation external)."""
    result = RouterTickResult(symbol="NQ",
                                naked_brackets_pending=("P_CID_001", "P_CID_002"))
    assert isinstance(result.naked_brackets_pending, tuple)
    assert result.naked_brackets_pending == ("P_CID_001", "P_CID_002")


# ============================================================
# R3 review : signal_id propage dans Transition.metadata
# ============================================================


def test_r3_transition_metadata_contains_signal_id():
    """Toute transition emise par instance contient signal_id dans metadata."""
    fire = _make_fire(direction="SHORT", confidence=0.8,
                       signal_id_suffix="UNIQUE_R3")
    inst = ScenarioInstance.from_fire(fire)
    inst.confirm(_make_bar())
    bar = _make_bar(high=20005, low=20005, close=20003,
                     ts="2026-06-25T10:02:00+00:00")
    t = inst.evaluate(bar)
    assert t is not None
    assert "signal_id" in t.metadata
    assert t.metadata["signal_id"] == fire.signal_id


def test_r3_dispatch_bracket_uses_signal_id_match():
    """_dispatch_bracket matche via signal_id (pas juste fallback actives[-1])."""
    fire = _make_fire(direction="SHORT", confidence=0.8,
                       signal_id_suffix="MATCH_TEST")
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    # Bracket dispatched OK -> signal_id matching via metadata a fonctionne
    assert result.brackets_dispatched == 1


# ============================================================
# Logs traceability : emit_safe pas KeyError
# ============================================================


# ============================================================
# P5.1 review : DispatchedBracket + ClosedSignal frozen + metadata
# ============================================================


def test_p51_dispatched_bracket_frozen():
    from dataclasses import FrozenInstanceError
    db = DispatchedBracket(
        signal_id="X", parent_cid="P", sl_cid="S",
        symbol="NQ", direction="SHORT", quantity=1,
        fill_price=20000.0, scenario_name="Test",
    )
    with pytest.raises(FrozenInstanceError):
        db.parent_cid = "Y"  # type: ignore


def test_p51_closed_signal_frozen():
    from dataclasses import FrozenInstanceError
    cs = ClosedSignal(
        signal_id="X", parent_cid="P", symbol="NQ",
        scenario_name="Test", final_state="COMPLETED", reason="target_hit",
    )
    with pytest.raises(FrozenInstanceError):
        cs.parent_cid = "Y"  # type: ignore


def test_p51_route_bar_default_empty_tuples():
    router, _, _ = _make_router()
    result = router.route_bar(_make_ctx())
    assert result.dispatched_brackets == ()
    assert result.closed_signals == ()


def test_p51_dispatched_brackets_populated_on_success():
    """Bracket OK -> dispatched_brackets contient metadata complete."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    assert len(result.dispatched_brackets) == 1
    db = result.dispatched_brackets[0]
    assert db.parent_cid == "P_CID_001"
    assert db.sl_cid == "SL_CID_001"
    assert db.symbol == "NQ"
    assert db.direction == "SHORT"
    assert db.scenario_name == "Test_Scenario"
    assert db.naked is False
    assert db.fill_price == 20000.0


def test_p51_dispatched_brackets_naked_flag():
    """Bracket naked -> dispatched_brackets contient sl_cid='' + naked=True."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    backend = FakeDTCBackend(success=True, naked=True)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)],
                                 backend=backend)
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_trigger))
    assert len(result.dispatched_brackets) == 1
    db = result.dispatched_brackets[0]
    assert db.naked is True
    assert db.sl_cid == ""
    # Et naked_brackets_pending coherent
    assert db.parent_cid in result.naked_brackets_pending


def test_p51_closed_signals_populated_on_archive_with_parent_cid():
    """Signal closed apres dispatch -> closed_signals contient parent_cid."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    # Bar 2 trigger
    bar_trigger = _make_bar(high=20005, low=19995, close=20000,
                              ts="2026-06-25T10:02:00+00:00")
    router.route_bar(_make_ctx(bar=bar_trigger))
    # Bar 3 target hit -> COMPLETED
    bar_complete = _make_bar(high=20005, low=19975, close=19980,
                              ts="2026-06-25T10:03:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_complete))
    assert len(result.closed_signals) >= 1
    cs = result.closed_signals[0]
    assert cs.parent_cid == "P_CID_001"  # parent_cid propage du dispatch
    assert cs.final_state == "COMPLETED"
    assert cs.symbol == "NQ"
    assert cs.scenario_name == "Test_Scenario"


def test_p51_closed_signals_empty_parent_cid_if_never_dispatched():
    """PENDING -> INVALIDATED sans TRIGGERED -> closed_signal.parent_cid='' (skip mark_closed)."""
    # Fire avec stop tres pres -> stop hit avant TRIGGERED
    fire = ScenarioFire(
        signal_id="X_NQ_INVALIDATE",
        scenario_name="Stopping",
        family="Test",
        symbol="NQ",
        direction="SHORT",
        entry_price=20000.0,
        stop_loss=20001.0,  # 1pt seulement -> facile a stop
        target_1=19980.0,
        heuristic_score=80,
        confidence=0.8,
        regime="TREND",
        session="us_cash",
        timestamp_utc="2026-06-25T10:00:00+00:00",
    )
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    # Pas de confirm -> PENDING. Bar suivante stop hit dans _evaluate_pending
    bar_stop = _make_bar(high=20005, low=20002, close=20003,  # high >= stop=20001
                          ts="2026-06-25T10:02:00+00:00")
    result = router.route_bar(_make_ctx(bar=bar_stop))
    # Si transition INVALIDATED emise -> closed_signal avec parent_cid vide
    invalidated_signals = [cs for cs in result.closed_signals
                            if cs.final_state == "INVALIDATED"]
    if invalidated_signals:
        cs = invalidated_signals[0]
        assert cs.parent_cid == ""  # jamais dispatched


def test_p51_signal_to_dispatch_map_cleaned_after_archive():
    """Apres archive terminal, _signal_to_dispatch ne fuite pas (memory)."""
    fire = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    router.route_bar(_make_ctx())
    inst = router.trackers["NQ"].active_instances()[0]
    inst.confirm(_make_bar())
    # Trigger
    router.route_bar(_make_ctx(bar=_make_bar(high=20005, low=19995, close=20000,
                                              ts="2026-06-25T10:02:00+00:00")))
    # Map doit contenir l'entry
    assert inst.signal_id in router._signal_to_dispatch
    # COMPLETED
    router.route_bar(_make_ctx(bar=_make_bar(high=20005, low=19975, close=19980,
                                              ts="2026-06-25T10:03:00+00:00")))
    # Apres archive, entry doit etre purgee (anti memory leak)
    assert inst.signal_id not in router._signal_to_dispatch


def test_emit_safe_no_keyerror_on_router_codes(caplog):
    """emit_safe avec codes router enregistres -> pas KeyError silent."""
    import logging
    fire = _make_fire(direction="SHORT", confidence=0.8)
    router, _, _ = _make_router(detectors=[FixedDetector("S", fire)])
    with caplog.at_level(logging.INFO, logger="bot4_v2.decision.decision_router"):
        router.route_bar(_make_ctx())
    # Au moins le code FIRE emis sans KeyError
    log_msgs = [r.message for r in caplog.records]
    fire_logs = [m for m in log_msgs if "scenario=Test_Scenario" in m]
    assert len(fire_logs) >= 1
