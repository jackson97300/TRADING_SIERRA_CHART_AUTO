"""Tests scenario_tracker.py Foundation B.5.1.

Couvre :
- State machine 7 etats + transitions valides
- Dataclasses StateTransition + ScenarioInstance
- Constants timeout par setup_type + match_threshold
- make_scenario_id stable hash
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# State machine
# ════════════════════════════════════════════════════════════════════════════

def test_states_constants_exist():
    """7 etats constants + sets terminal/non_terminal exposes."""
    from CORE.scenario_tracker import (
        STATE_PENDING, STATE_ACTIVE_ENTRY_ZONE, STATE_TRIGGERED,
        STATE_VALIDATED, STATE_COMPLETED, STATE_INVALIDATED, STATE_EXPIRED,
        NON_TERMINAL_STATES, TERMINAL_STATES,
    )
    assert STATE_PENDING == "PENDING"
    assert STATE_ACTIVE_ENTRY_ZONE == "ACTIVE_ENTRY_ZONE"
    assert STATE_TRIGGERED == "TRIGGERED"
    assert STATE_VALIDATED == "VALIDATED"
    assert STATE_COMPLETED == "COMPLETED"
    assert STATE_INVALIDATED == "INVALIDATED"
    assert STATE_EXPIRED == "EXPIRED"
    # Disjoints
    assert NON_TERMINAL_STATES.isdisjoint(TERMINAL_STATES)
    # Union = 7 etats
    assert len(NON_TERMINAL_STATES) + len(TERMINAL_STATES) == 7


def test_valid_transitions_lifecycle_normal():
    """Lifecycle nominal : PENDING -> ACTIVE -> TRIGGERED -> VALIDATED -> COMPLETED."""
    from CORE.scenario_tracker import is_valid_transition
    assert is_valid_transition("PENDING", "ACTIVE_ENTRY_ZONE") is True
    assert is_valid_transition("ACTIVE_ENTRY_ZONE", "TRIGGERED") is True
    assert is_valid_transition("TRIGGERED", "VALIDATED") is True
    assert is_valid_transition("VALIDATED", "COMPLETED") is True


def test_valid_transitions_invalidation_each_state():
    """INVALIDATED accessible depuis tous les non-terminaux."""
    from CORE.scenario_tracker import is_valid_transition
    assert is_valid_transition("PENDING", "INVALIDATED") is True
    assert is_valid_transition("ACTIVE_ENTRY_ZONE", "INVALIDATED") is True
    assert is_valid_transition("TRIGGERED", "INVALIDATED") is True
    assert is_valid_transition("VALIDATED", "INVALIDATED") is True


def test_valid_transitions_expired_each_state():
    """EXPIRED accessible depuis tous les non-terminaux."""
    from CORE.scenario_tracker import is_valid_transition
    assert is_valid_transition("PENDING", "EXPIRED") is True
    assert is_valid_transition("ACTIVE_ENTRY_ZONE", "EXPIRED") is True
    assert is_valid_transition("TRIGGERED", "EXPIRED") is True
    assert is_valid_transition("VALIDATED", "EXPIRED") is True


def test_invalid_transitions_skip_states():
    """Pas de skip : PENDING ne peut pas aller direct vers TRIGGERED ou VALIDATED."""
    from CORE.scenario_tracker import is_valid_transition
    assert is_valid_transition("PENDING", "TRIGGERED") is False
    assert is_valid_transition("PENDING", "VALIDATED") is False
    assert is_valid_transition("PENDING", "COMPLETED") is False


def test_invalid_transitions_terminal_outbound():
    """Terminaux : aucune transition sortante autorisee."""
    from CORE.scenario_tracker import is_valid_transition
    for terminal in ("COMPLETED", "INVALIDATED", "EXPIRED"):
        assert is_valid_transition(terminal, "PENDING") is False
        assert is_valid_transition(terminal, "TRIGGERED") is False
        assert is_valid_transition(terminal, "COMPLETED") is False


def test_is_terminal_helper():
    """is_terminal() correct sur les 7 etats."""
    from CORE.scenario_tracker import is_terminal
    assert is_terminal("PENDING") is False
    assert is_terminal("ACTIVE_ENTRY_ZONE") is False
    assert is_terminal("TRIGGERED") is False
    assert is_terminal("VALIDATED") is False
    assert is_terminal("COMPLETED") is True
    assert is_terminal("INVALIDATED") is True
    assert is_terminal("EXPIRED") is True


# ════════════════════════════════════════════════════════════════════════════
# Constants timeout + matching
# ════════════════════════════════════════════════════════════════════════════

def test_max_bars_alive_by_setup_type():
    """Scalp (15) << swing (120). Default 60."""
    from CORE.scenario_tracker import get_max_bars_alive
    assert get_max_bars_alive("scalp") == 15
    assert get_max_bars_alive("swing") == 120
    assert get_max_bars_alive("unknown_type") == 60


def test_max_bars_in_zone_by_setup_type():
    """Scalp (5) << swing (20). Default 10."""
    from CORE.scenario_tracker import get_max_bars_in_zone
    assert get_max_bars_in_zone("scalp") == 5
    assert get_max_bars_in_zone("swing") == 20
    assert get_max_bars_in_zone("unknown_type") == 10


def test_match_threshold_per_name():
    """Range scenarios plus tolerants, FVG plus serres."""
    from CORE.scenario_tracker import get_match_threshold
    assert get_match_threshold("Range bound LONG fade") == 0.20
    assert get_match_threshold("Range bound SHORT fade") == 0.20
    assert get_match_threshold("FVG Magnet UP") == 0.05
    assert get_match_threshold("FVG Magnet DOWN") == 0.05
    assert get_match_threshold("Bullish continuation") == 0.10  # default


# ════════════════════════════════════════════════════════════════════════════
# UUID generator
# ════════════════════════════════════════════════════════════════════════════

def test_make_scenario_id_deterministic():
    """Meme inputs -> meme scenario_id (reproducibilite tests)."""
    from CORE.scenario_tracker import make_scenario_id
    id1 = make_scenario_id("Bullish continuation", "long", 29532.50, 1781256960000, "NQ")
    id2 = make_scenario_id("Bullish continuation", "long", 29532.50, 1781256960000, "NQ")
    assert id1 == id2
    assert len(id1) == 16


def test_make_scenario_id_distinct_on_different_inputs():
    """Inputs distincts -> ids distincts."""
    from CORE.scenario_tracker import make_scenario_id
    base = ("Bullish continuation", "long", 29532.50, 1781256960000, "NQ")
    id_base = make_scenario_id(*base)
    # Different name
    assert make_scenario_id("Bearish rejection", *base[1:]) != id_base
    # Different side
    assert make_scenario_id(base[0], "short", *base[2:]) != id_base
    # Different entry
    assert make_scenario_id(base[0], base[1], 29533.0, *base[3:]) != id_base
    # Different ts
    assert make_scenario_id(*base[:3], 1781256961000, base[4]) != id_base
    # Different symbol
    assert make_scenario_id(*base[:4], "ES") != id_base


# ════════════════════════════════════════════════════════════════════════════
# ScenarioInstance dataclass
# ════════════════════════════════════════════════════════════════════════════

def test_scenario_instance_default_state_pending():
    """Nouveau ScenarioInstance default state = PENDING."""
    from CORE.scenario_tracker import ScenarioInstance
    inst = ScenarioInstance(
        scenario_id="abc123",
        scenario_name="Bullish continuation",
        symbol="NQ",
        side="long",
        setup_type="swing",
        created_at_ts=1781256960000,
        last_update_ts=1781256960000,
    )
    assert inst.state == "PENDING"
    assert inst.bars_alive == 0
    assert inst.mfe_atr == 0.0
    assert inst.mae_atr == 0.0
    assert inst.is_terminal() is False


def test_scenario_instance_is_terminal_after_completion():
    """is_terminal() True quand state COMPLETED."""
    from CORE.scenario_tracker import ScenarioInstance
    inst = ScenarioInstance(
        scenario_id="abc123",
        scenario_name="Bullish continuation",
        symbol="NQ",
        side="long",
        setup_type="swing",
        created_at_ts=0,
        last_update_ts=0,
        state="COMPLETED",
    )
    assert inst.is_terminal() is True


def test_state_transition_dataclass():
    """StateTransition trace fields."""
    from CORE.scenario_tracker import StateTransition
    t = StateTransition(
        from_state="PENDING",
        to_state="ACTIVE_ENTRY_ZONE",
        ts_ms=1781256960000,
        bar_index=42,
        trigger="entry_zone_touch",
        bar_close=29532.5,
        matched_conditions=[],
    )
    assert t.from_state == "PENDING"
    assert t.to_state == "ACTIVE_ENTRY_ZONE"
    assert t.trigger == "entry_zone_touch"


# ════════════════════════════════════════════════════════════════════════════
# log_catalog integration (anti-VALIDATION_MISS regle souveraine 01/05)
# ════════════════════════════════════════════════════════════════════════════

def test_log_catalog_scenario_codes_exist():
    """Codes SCENARIO_* doivent etre definis dans log_catalog."""
    from CORE.log_catalog import resolve
    codes = [
        "SCENARIO_CREATED",
        "SCENARIO_ENTRY_ZONE_TOUCHED",
        "SCENARIO_TRIGGERED",
        "SCENARIO_TARGET_1_HIT",
        "SCENARIO_TARGET_2_HIT",
        "SCENARIO_STOP_HIT",
        "SCENARIO_INVALIDATED",
        "SCENARIO_EXPIRED",
        "SCENARIO_CONDITION_UNPARSABLE",
        "SCENARIO_SESSION_FLUSH",
        "SCENARIO_TRACKER_INIT",
        "SCENARIO_JSONL_WRITE_FAIL",
    ]
    for code in codes:
        level, category, template = resolve(code)
        assert level is not None
        assert category in ("decisions", "events")
        assert "{" in template, f"Code {code} template doit avoir placeholders"


def test_log_catalog_scenario_stop_hit_is_alerte():
    """SCENARIO_STOP_HIT doit etre niveau ALERTE (degrade narrative)."""
    from CORE.log_catalog import resolve, LogLevel
    level, _, _ = resolve("SCENARIO_STOP_HIT")
    assert level == LogLevel.ALERTE


def test_log_catalog_scenario_invalidated_is_alerte():
    """SCENARIO_INVALIDATED doit etre niveau ALERTE."""
    from CORE.log_catalog import resolve, LogLevel
    level, _, _ = resolve("SCENARIO_INVALIDATED")
    assert level == LogLevel.ALERTE


def test_log_catalog_scenario_target_2_is_info():
    """SCENARIO_TARGET_2_HIT (COMPLETED) doit etre INFO (succes attendu)."""
    from CORE.log_catalog import resolve, LogLevel
    level, _, _ = resolve("SCENARIO_TARGET_2_HIT")
    assert level == LogLevel.INFO


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
