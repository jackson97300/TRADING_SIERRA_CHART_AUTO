"""Tests bot4_v2/decision/narrative_state."""
from __future__ import annotations

import pytest

from bot4_v2.decision.narrative_state import (
    ScenarioInstance,
    ScenarioState,
    ScenarioTracker,
    Transition,
)


def _make_long_instance(**kwargs) -> ScenarioInstance:
    """Helper : LONG scenario, entry=20000, stop=19990, target=20020."""
    defaults = {
        "signal_id": "TEST_001",
        "scenario_name": "Bearish_Rejection",
        "symbol": "NQ",
        "direction": "LONG",
        "entry_price": 20000.0,
        "stop_loss": 19990.0,
        "target_1": 20020.0,
        "fire_ts": "2026-06-25T10:00:00+00:00",
        "confirmation_window_bars": 5,
        "timeout_bars": 30,
    }
    defaults.update(kwargs)
    return ScenarioInstance(**defaults)


def _make_short_instance(**kwargs) -> ScenarioInstance:
    """Helper : SHORT scenario, entry=20000, stop=20010, target=19980."""
    defaults = {
        "signal_id": "TEST_001",
        "scenario_name": "Bearish_Rejection",
        "symbol": "NQ",
        "direction": "SHORT",
        "entry_price": 20000.0,
        "stop_loss": 20010.0,
        "target_1": 19980.0,
        "fire_ts": "2026-06-25T10:00:00+00:00",
    }
    defaults.update(kwargs)
    return ScenarioInstance(**defaults)


def _bar(high: float, low: float, close: float | None = None,
         ts: str = "2026-06-25T10:01:00+00:00") -> dict:
    return {"high": high, "low": low, "close": close or (high + low) / 2,
            "ts_event": ts}


# ============================================================
# ScenarioState enum
# ============================================================

def test_scenario_state_values():
    assert ScenarioState.PENDING.value == "PENDING"
    assert ScenarioState.ACTIVE.value == "ACTIVE"
    assert ScenarioState.TRIGGERED.value == "TRIGGERED"
    assert ScenarioState.COMPLETED.value == "COMPLETED"
    assert ScenarioState.INVALIDATED.value == "INVALIDATED"


def test_scenario_state_is_terminal():
    assert ScenarioState.PENDING.is_terminal is False
    assert ScenarioState.ACTIVE.is_terminal is False
    assert ScenarioState.TRIGGERED.is_terminal is False
    assert ScenarioState.COMPLETED.is_terminal is True
    assert ScenarioState.INVALIDATED.is_terminal is True


# ============================================================
# Transition dataclass
# ============================================================

def test_transition_frozen():
    from dataclasses import FrozenInstanceError
    t = Transition(
        from_state=ScenarioState.PENDING, to_state=ScenarioState.ACTIVE,
        bar_ts="ts", bar_idx=1, reason="x",
    )
    with pytest.raises(FrozenInstanceError):
        t.reason = "modified"  # type: ignore


def test_transition_default_metadata():
    t = Transition(
        from_state=ScenarioState.PENDING, to_state=ScenarioState.ACTIVE,
        bar_ts="ts", bar_idx=1, reason="x",
    )
    assert t.metadata == {}


# ============================================================
# ScenarioInstance init validation
# ============================================================

def test_init_invalid_direction():
    with pytest.raises(ValueError, match="LONG.*SHORT"):
        _make_long_instance(direction="UP")


def test_init_invalid_window_zero():
    with pytest.raises(ValueError):
        _make_long_instance(confirmation_window_bars=0)


def test_init_invalid_timeout_zero():
    with pytest.raises(ValueError):
        _make_long_instance(timeout_bars=0)


def test_init_timeout_less_than_window():
    with pytest.raises(ValueError):
        _make_long_instance(confirmation_window_bars=10, timeout_bars=5)


def test_init_long_invalid_stop_above_entry():
    """LONG requires stop < entry < target."""
    with pytest.raises(ValueError, match="LONG"):
        _make_long_instance(stop_loss=20010.0)  # stop > entry


def test_init_long_invalid_target_below_entry():
    with pytest.raises(ValueError, match="LONG"):
        _make_long_instance(target_1=19995.0)  # target < entry


def test_init_short_invalid_stop_below_entry():
    """SHORT requires target < entry < stop."""
    with pytest.raises(ValueError, match="SHORT"):
        _make_short_instance(stop_loss=19990.0)  # stop < entry


def test_init_short_invalid_target_above_entry():
    with pytest.raises(ValueError, match="SHORT"):
        _make_short_instance(target_1=20020.0)


def test_init_starts_in_pending():
    inst = _make_long_instance()
    assert inst.state == ScenarioState.PENDING
    assert inst.bar_idx == 0
    assert inst.is_terminal is False
    assert inst.transitions_log == ()


def test_init_symbol_uppercase():
    inst = _make_long_instance(symbol="nq")
    assert inst.symbol == "NQ"


# ============================================================
# evaluate invalid bar
# ============================================================

def test_evaluate_none_bar_raises():
    inst = _make_long_instance()
    with pytest.raises(ValueError):
        inst.evaluate(None)  # type: ignore


def test_evaluate_empty_bar_raises():
    inst = _make_long_instance()
    with pytest.raises(ValueError):
        inst.evaluate({})


def test_evaluate_non_dict_raises():
    inst = _make_long_instance()
    with pytest.raises(ValueError):
        inst.evaluate("not a dict")  # type: ignore


# ============================================================
# PENDING -> ACTIVE (confirmation)
# ============================================================

def test_pending_to_active_on_confirmation():
    """PATCH #1 : bar avec confirm + low > entry -> stays ACTIVE (pas cascade)."""
    inst = _make_long_instance()
    inst.confirm({"any": 1})
    # entry=20000, low=20005 > entry (LONG) -> entry pas touchee, reste ACTIVE
    t = inst.evaluate(_bar(high=20010, low=20005))
    assert t is not None
    assert t.from_state == ScenarioState.PENDING
    assert t.to_state == ScenarioState.ACTIVE
    assert inst.state == ScenarioState.ACTIVE


def test_pending_stays_pending_without_confirm():
    inst = _make_long_instance()
    t = inst.evaluate(_bar(high=20005, low=19995))
    assert t is None  # no transition
    assert inst.state == ScenarioState.PENDING


# ============================================================
# PENDING -> INVALIDATED (window expire)
# ============================================================

def test_pending_to_invalidated_on_window_expire():
    inst = _make_long_instance(confirmation_window_bars=3)
    # 3 bars sans confirm -> expire
    for _ in range(3):
        t = inst.evaluate(_bar(high=20005, low=19995))
    assert inst.state == ScenarioState.INVALIDATED
    # Derniere transition = expire
    last = inst.transitions_log[-1]
    assert last.to_state == ScenarioState.INVALIDATED
    assert "window_expired" in last.reason


# ============================================================
# PENDING -> INVALIDATED (stop hit)
# ============================================================

def test_pending_to_invalidated_on_stop_hit_long():
    """LONG : low <= stop_loss -> INVALIDATED."""
    inst = _make_long_instance()
    t = inst.evaluate(_bar(high=20005, low=19985))  # low < stop=19990
    assert t.to_state == ScenarioState.INVALIDATED
    assert t.reason == "stop_loss_hit"


def test_pending_to_invalidated_on_stop_hit_short():
    inst = _make_short_instance()
    t = inst.evaluate(_bar(high=20015, low=19995))  # high > stop=20010
    assert t.to_state == ScenarioState.INVALIDATED


# ============================================================
# ACTIVE -> TRIGGERED (entry touched)
# ============================================================

def test_active_to_triggered_long_entry_touched():
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # PENDING -> ACTIVE
    assert inst.state == ScenarioState.ACTIVE
    # Bar suivante : low touche entry=20000
    t = inst.evaluate(_bar(high=20005, low=19998))  # low <= entry=20000
    assert t.to_state == ScenarioState.TRIGGERED
    assert t.reason == "entry_zone_touched"


def test_active_to_triggered_short_entry_touched():
    inst = _make_short_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=19995, low=19990))  # PENDING -> ACTIVE
    assert inst.state == ScenarioState.ACTIVE
    # high touche entry=20000
    t = inst.evaluate(_bar(high=20005, low=19995))
    assert t.to_state == ScenarioState.TRIGGERED


def test_active_stays_active_if_entry_not_touched():
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    # entry=20000, low=20002 ne touche pas
    t = inst.evaluate(_bar(high=20018, low=20002))
    assert t is None
    assert inst.state == ScenarioState.ACTIVE


# ============================================================
# ACTIVE -> INVALIDATED (stop hit avant entry)
# ============================================================

def test_active_to_invalidated_on_stop_hit_before_entry():
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    # Stop hit avant entry
    t = inst.evaluate(_bar(high=20015, low=19985))  # low <= stop=19990
    assert t.to_state == ScenarioState.INVALIDATED
    assert t.reason == "stop_loss_hit"


# ============================================================
# TRIGGERED -> COMPLETED (target hit)
# ============================================================

def test_triggered_to_completed_long_target_hit():
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    inst.evaluate(_bar(high=20005, low=19998))  # -> TRIGGERED
    # target=20020 hit
    t = inst.evaluate(_bar(high=20025, low=20010))
    assert t.to_state == ScenarioState.COMPLETED
    assert t.reason == "target_1_hit"


def test_triggered_to_completed_short_target_hit():
    inst = _make_short_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=19995, low=19990))  # -> ACTIVE
    inst.evaluate(_bar(high=20005, low=19995))  # -> TRIGGERED
    # target=19980 hit
    t = inst.evaluate(_bar(high=19990, low=19975))
    assert t.to_state == ScenarioState.COMPLETED


# ============================================================
# TRIGGERED -> INVALIDATED (stop hit apres entry)
# ============================================================

def test_triggered_to_invalidated_on_stop_hit():
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    inst.evaluate(_bar(high=20005, low=19998))  # -> TRIGGERED
    # Stop hit
    t = inst.evaluate(_bar(high=20010, low=19985))
    assert t.to_state == ScenarioState.INVALIDATED


# ============================================================
# TIMEOUT
# ============================================================

def test_timeout_invalidates_pending_no_entry():
    inst = _make_long_instance(timeout_bars=10)
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    # 10 bars sans entry hit ni stop hit
    for _ in range(11):
        inst.evaluate(_bar(high=20012, low=20002))  # no entry touch
    assert inst.state == ScenarioState.INVALIDATED
    last = inst.transitions_log[-1]
    assert "timeout" in last.reason


def test_timeout_completes_triggered():
    inst = _make_long_instance(timeout_bars=10)
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    inst.evaluate(_bar(high=20005, low=19998))  # -> TRIGGERED
    # Bars suivantes sans target ni stop
    for _ in range(15):
        inst.evaluate(_bar(high=20015, low=20002))
    assert inst.state == ScenarioState.COMPLETED  # timeout normal
    last = inst.transitions_log[-1]
    assert last.reason == "timeout_normal"


# ============================================================
# Terminal no-op
# ============================================================

def test_terminal_evaluate_no_op():
    """Une fois terminal, evaluate ne fait rien."""
    inst = _make_long_instance()
    t1 = inst.evaluate(_bar(high=20010, low=19985))  # stop hit -> INVALIDATED
    assert t1 is not None
    assert inst.is_terminal
    n_transitions_before = len(inst.transitions_log)
    # Evaluate apres terminal
    t2 = inst.evaluate(_bar(high=20025, low=20010))
    assert t2 is None
    assert len(inst.transitions_log) == n_transitions_before


# ============================================================
# Transitions log audit
# ============================================================

def test_transitions_log_immutable_tuple():
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))
    log = inst.transitions_log
    assert isinstance(log, tuple)


def test_transitions_log_records_full_lifecycle():
    """PENDING -> ACTIVE -> TRIGGERED -> COMPLETED."""
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    inst.evaluate(_bar(high=20005, low=19998))  # -> TRIGGERED
    inst.evaluate(_bar(high=20025, low=20010))  # -> COMPLETED
    log = inst.transitions_log
    assert len(log) == 3
    assert log[0].to_state == ScenarioState.ACTIVE
    assert log[1].to_state == ScenarioState.TRIGGERED
    assert log[2].to_state == ScenarioState.COMPLETED


# ============================================================
# to_dict serialization
# ============================================================

def test_to_dict_complete():
    inst = _make_long_instance(extra={"score": 75})
    d = inst.to_dict()
    assert d["signal_id"] == "TEST_001"
    assert d["state"] == "PENDING"
    assert d["bar_idx"] == 0
    assert d["confirmed"] is False
    assert d["extra"] == {"score": 75}


# ============================================================
# ScenarioTracker
# ============================================================

def test_tracker_init():
    t = ScenarioTracker(symbol="nq")
    assert t.symbol == "NQ"
    assert t.n_instances == 0
    assert t.n_active == 0


def test_tracker_add_instance():
    tracker = ScenarioTracker(symbol="NQ")
    inst = _make_long_instance()
    tracker.add(inst)
    assert tracker.n_instances == 1
    assert tracker.n_active == 1


def test_tracker_add_wrong_symbol_raises():
    tracker = ScenarioTracker(symbol="NQ")
    inst = _make_long_instance(symbol="ES")
    with pytest.raises(ValueError, match="symbol"):
        tracker.add(inst)


def test_tracker_update_all_returns_transitions():
    tracker = ScenarioTracker(symbol="NQ")
    inst1 = _make_long_instance(signal_id="S1")
    inst2 = _make_long_instance(signal_id="S2")
    inst1.confirm({})
    inst2.confirm({})
    tracker.add(inst1)
    tracker.add(inst2)
    transitions = tracker.update_all(_bar(high=20015, low=20005))
    assert len(transitions) == 2


def test_tracker_skips_terminal_in_update():
    tracker = ScenarioTracker(symbol="NQ")
    inst = _make_long_instance()
    inst.evaluate(_bar(high=20015, low=19985))  # stop hit -> INVALIDATED
    tracker.add(inst)
    # update_all ne doit pas crash (terminal skipped)
    transitions = tracker.update_all(_bar(high=20015, low=20005))
    assert transitions == []


def test_tracker_active_instances_filters_terminal():
    tracker = ScenarioTracker(symbol="NQ")
    inst1 = _make_long_instance(signal_id="S1")
    inst2 = _make_long_instance(signal_id="S2")
    inst2.evaluate(_bar(high=20015, low=19985))  # stop hit
    tracker.add(inst1)
    tracker.add(inst2)
    active = tracker.active_instances()
    assert len(active) == 1
    assert active[0].signal_id == "S1"


def test_tracker_terminal_instances():
    tracker = ScenarioTracker(symbol="NQ")
    inst1 = _make_long_instance(signal_id="S1")
    inst2 = _make_long_instance(signal_id="S2")
    inst2.evaluate(_bar(high=20015, low=19985))
    tracker.add(inst1)
    tracker.add(inst2)
    terminal = tracker.terminal_instances()
    assert len(terminal) == 1
    assert terminal[0].signal_id == "S2"


def test_tracker_pop_terminal_removes_from_tracker():
    tracker = ScenarioTracker(symbol="NQ")
    inst1 = _make_long_instance(signal_id="S1")
    inst2 = _make_long_instance(signal_id="S2")
    inst2.evaluate(_bar(high=20015, low=19985))
    tracker.add(inst1)
    tracker.add(inst2)
    popped = tracker.pop_terminal()
    assert len(popped) == 1
    assert tracker.n_instances == 1  # only S1 remains


def test_tracker_find_by_signal_id():
    tracker = ScenarioTracker(symbol="NQ")
    inst = _make_long_instance(signal_id="UNIQUE_ID")
    tracker.add(inst)
    found = tracker.find_by_signal_id("UNIQUE_ID")
    assert found is inst


def test_tracker_find_by_signal_id_not_found():
    tracker = ScenarioTracker(symbol="NQ")
    assert tracker.find_by_signal_id("MISSING") is None


# ============================================================
# confirm() ne fait rien si pas PENDING
# ============================================================

def test_confirm_noop_when_not_pending():
    """confirm() apres state != PENDING n'a aucun effet."""
    inst = _make_long_instance()
    inst.confirm({})
    inst.evaluate(_bar(high=20015, low=20005))  # -> ACTIVE
    assert inst.state == ScenarioState.ACTIVE
    inst.confirm({})  # no-op
    assert inst.state == ScenarioState.ACTIVE


# ============================================================
# Bar idx tracking
# ============================================================

def test_bar_idx_increments_per_evaluate():
    inst = _make_long_instance()
    assert inst.bar_idx == 0
    inst.evaluate(_bar(high=20015, low=20005))
    assert inst.bar_idx == 1
    inst.evaluate(_bar(high=20018, low=20002))
    assert inst.bar_idx == 2


# ============================================================
# PATCH #1 review batch 1 P3 : cascade transitions meme bar
# ============================================================

def test_cascade_pending_to_triggered_same_bar():
    """PATCH #1 : bar avec confirm + entry touched -> cascade PENDING->ACTIVE->TRIGGERED."""
    inst = _make_long_instance()
    inst.confirm({})
    # entry=20000, low=19998 touche entry direct, high=20015 ne touche pas target=20020
    trans = inst.evaluate(_bar(high=20015, low=19998))
    # Doit cascade meme bar : ACTIVE puis TRIGGERED
    assert inst.state == ScenarioState.TRIGGERED
    assert len(inst.transitions_log) == 2
    assert inst.transitions_log[0].to_state == ScenarioState.ACTIVE
    assert inst.transitions_log[1].to_state == ScenarioState.TRIGGERED


def test_cascade_pending_to_completed_same_bar():
    """PATCH #1 : bar squeeze tres rapide PENDING -> ACTIVE -> TRIGGERED -> COMPLETED."""
    inst = _make_long_instance()
    inst.confirm({})
    # entry=20000, target=20020. Bar low=19998 touche entry ET high=20025 touche target
    trans = inst.evaluate(_bar(high=20025, low=19998))
    assert inst.state == ScenarioState.COMPLETED
    # 3 transitions cascade : ACTIVE + TRIGGERED + COMPLETED
    assert len(inst.transitions_log) == 3
    assert inst.transitions_log[-1].to_state == ScenarioState.COMPLETED


def test_cascade_does_not_skip_when_no_entry_touch():
    """PATCH #1 : si confirm valide mais entry pas touchee -> stay ACTIVE (pas cascade artificielle)."""
    inst = _make_long_instance()
    inst.confirm({})
    # entry=20000, low=20005 ne touche pas entry
    inst.evaluate(_bar(high=20018, low=20005))
    assert inst.state == ScenarioState.ACTIVE
    assert len(inst.transitions_log) == 1
    assert inst.transitions_log[0].to_state == ScenarioState.ACTIVE


# ============================================================
# PATCH #3 review batch 1 P3 : OHLC non-castable + log warning
# ============================================================

def test_evaluate_non_numeric_ohlc_returns_none(caplog):
    """PATCH #3 : OHLC string non-castable -> return None + warning (anti silent fallback)."""
    import logging
    inst = _make_long_instance()
    with caplog.at_level(logging.WARNING, logger="bot4_v2.decision.narrative_state"):
        t = inst.evaluate({"high": "abc", "low": "def", "ts_event": "ts"})
    assert t is None
    assert any("non-castable" in r.message for r in caplog.records)


def test_evaluate_non_numeric_ohlc_increments_bar_idx():
    """bar_idx incremente meme si bar invalide (consume slot)."""
    inst = _make_long_instance()
    assert inst.bar_idx == 0
    inst.evaluate({"high": "abc", "low": "def", "ts_event": "ts"})
    assert inst.bar_idx == 1  # consume slot meme si invalid


# ============================================================
# PATCH #2 review batch 1 P3 : confirm() sans reason param
# ============================================================

def test_confirm_signature_no_reason_param():
    """PATCH #2 : confirm() ne prend plus de param 'reason' (jamais utilise dans v1)."""
    inst = _make_long_instance()
    inst.confirm({})  # 1 seul param bar OK
    assert inst._confirmed is True
