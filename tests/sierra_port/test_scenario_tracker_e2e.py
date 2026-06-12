"""Tests E2E Phase B.5.5 - replay bars + smoke live integration.

Verifie la chaine complete :
- bar live_enriched -> NarrativeContext -> Scenario list -> ScenarioTracker.update()
- -> ScenarioInstance lifecycle -> JSONLSerializer (terminaux)

Replay simule pour reproduire le flow live_pipeline_loop sans dependance
externe (pas d'intégration sierra_pipeline.py dans ce test, voir backlog).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# Bar live Jackson 12/06 13:09 UTC (schema 3.7.22+) - smoke fixture
# ════════════════════════════════════════════════════════════════════════════

def _bar_jackson_12_06_13_09() -> dict:
    """Bar live NQ 12/06 13:09 UTC (extrait Jackson partage)."""
    return {
        "ts": 1781269740000, "sym": "NQ",
        "close": 29444.25, "high": 29449.0, "low": 29439.0,
        "atr": 743.14, "atr_14m": 93.43,
        "vix_level": 19.39, "mins_et": 549,
        "is_in_us_cash": False, "is_in_london": True,
        "session_segment": "london",
        # Niveaux veille
        "pdh": 29544.25, "pdl": 28265.75,
        "cash_high": 29675.0, "cash_low": 28678.5,
        "prev_vah": 28883.75, "prev_val": 28582.75, "prev_vpoc": 28600.0,
        "pvwap": 28727.94,
        "prev_vwap_sd1u": 28876.31, "prev_vwap_sd1d": 28580.43,
        # VWAP day
        "vwap_d": 29321.6, "vwap_d_sd1u": 29548.61, "vwap_d_sd1d": 29094.59,
        "vwap_d_sd2u": 29775.62, "vwap_d_sd2d": 28867.58,
        "vwap_d_sd3u": 30002.63, "vwap_d_sd3d": 28640.57,
        "vwap_w": 29097.6, "vwap_m": 29671.5,
        "vwap_triple_align": 0, "bool_above_vwap_d": 1,
        # Session courante
        "cur_vah": 29504.5, "cur_val": 29082.0, "cur_vpoc": 29196.5,
        "sess_high": 29675.0, "sess_low": 29260.0,
        "ovn_high": 29675.0, "ovn_low": 29260.0,
        "range_pos_va": 85.7396, "inside_cur_va": 1,
        # Dalton
        "open_type": 0, "open_zone": 0, "open_direction": 0,
        "open_bias_conf": 0.0, "open_relation_type": 2,
        "profile_overlap_pct": 0.0, "range_extension_completed": False,
        "day_type": 2, "trend_day_probability": 0.0, "profile_shape": 1,
        # IB (null en pre-RTH)
        "ib_complete": 0, "ib_broken_up": 0, "ib_broken_down": 0,
        "ib_range_atr": None, "ib_high": None, "ib_low": None, "ib_is_narrow": 0,
        # Patterns
        "has_single_prints": True, "single_print_above": False,
        "single_print_below": True, "dist_single_print_atr": -0.36,
        "single_print_density": 0.513,
        "fvg_up_active": 9, "fvg_dn_active": 13,
        "dist_fvg_up_nearest_atr": None, "dist_fvg_dn_nearest_atr": None,
        "sweep_high_active": 1, "sweep_low_active": 1,
        "sweep_high_this_bar": True, "sweep_low_this_bar": False,
        "judas_swing_active": False, "judas_swing_direction": 0,
        "london_open": 29350.0, "london_first_hour_direction": 1,
        "bars_since_london_open": 368,
        # Order flow
        "delta_day": 6915, "cvd_day": 16285, "cvd_session": -150,
        "finish_strength": -27, "delta_bar": 4,
        "bn_color_up": 0, "bn_color_dn": 0,
        "bn_long_up": 0, "bn_long_dn": 1,
        "bn_absorb_ask": 0, "bn_absorb_bid": 0,
        "bn_pressure_ask": 0.0, "bn_pressure_bid": 0.0,
        "bn_score_raw": -0.428571,
        "delta_divergence": 0, "delta_div_slope_strength": -0.002455,
        # Swing
        "dist_swing_high": 863.0, "dist_swing_low": 608.0,
    }


# ════════════════════════════════════════════════════════════════════════════
# E2E lifecycle complet : bar -> ctx -> scenarios -> tracker -> serializer
# ════════════════════════════════════════════════════════════════════════════

def test_e2e_smoke_jackson_bar_creates_instances():
    """Smoke E2E : bar Jackson reel -> scenarios -> tracker cree instances."""
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    from CORE.scenario_tracker import ScenarioTracker
    bar = _bar_jackson_12_06_13_09()
    ctx = build_narrative_context(bar)
    fresh = generate_scenarios(ctx, apply_filter=False)
    assert len(fresh) >= 1, "Devrait emettre au moins 1 scenario"
    tracker = ScenarioTracker(symbol="NQ")
    update = tracker.update(ctx, bar, fresh)
    # Pas de target/stop hit ici (1ere bar)
    active = tracker.get_active()
    assert len(active) >= 1, "Tracker doit avoir cree au moins 1 ScenarioInstance"


def test_e2e_replay_progresses_through_lifecycle(tmp_path):
    """Replay 3 bars : create -> zone touch -> target_1 hit."""
    from CORE.scenario_tracker import ScenarioTracker
    from CORE.scenario_serializer import JSONLSerializer

    # Bar 1 : creation scenario (hors zone)
    # Bar 2 : zone touchee
    # Bar 3 : target_1 hit -> VALIDATED
    # Bar 4 : target_2 hit -> COMPLETED
    from dataclasses import dataclass, field

    @dataclass
    class FakeSetup:
        side: str
        entry_price: float
        entry_zone_low: float
        entry_zone_high: float
        target_1: float
        target_2: float
        stop_loss: float
        setup_type: str = "swing"
        conditions_validation: list = field(default_factory=list)
        conditions_invalidation: list = field(default_factory=list)
        rationale: str = ""

    @dataclass
    class FakeScenario:
        name: str
        direction: str
        heuristic_score: int
        description: str = ""
        key_levels_used: list = field(default_factory=list)
        setups: list = field(default_factory=list)
        primary: bool = False

    @dataclass
    class FakeCtx:
        symbol: str = "NQ"
        atr: float = 100.0
        macro_regime: str = "calm"

    setup = FakeSetup(
        side="long",
        entry_price=29500,
        entry_zone_low=29490,
        entry_zone_high=29510,
        target_1=29700,
        target_2=29800,
        stop_loss=29400,
    )
    fresh = FakeScenario(
        name="Bullish continuation",
        direction="bullish",
        heuristic_score=65,
        setups=[setup],
    )

    tracker = ScenarioTracker(symbol="NQ")
    serializer = JSONLSerializer(symbol="NQ", logs_dir=str(tmp_path))

    # Bar 1 : hors zone
    bar1 = {"ts": 1781256960000, "close": 29450, "high": 29450, "low": 29450}
    update1 = tracker.update(FakeCtx(), bar1, [fresh])
    assert tracker.get_active()[0].state == "PENDING"
    assert len(update1.terminal_instances) == 0

    # Bar 2 : zone touchee
    bar2 = {"ts": 1781257020000, "close": 29495, "high": 29505, "low": 29495}
    tracker.update(FakeCtx(), bar2, [fresh])
    assert tracker.get_active()[0].state == "ACTIVE_ENTRY_ZONE"

    # Bar 3 : target_1 hit -> VALIDATED
    bar3 = {"ts": 1781257080000, "close": 29710, "high": 29710, "low": 29495}
    tracker.update(FakeCtx(), bar3, [fresh])
    assert tracker.get_active()[0].state == "VALIDATED"

    # Bar 4 : target_2 hit -> COMPLETED + flush
    bar4 = {"ts": 1781257140000, "close": 29810, "high": 29810, "low": 29710}
    update4 = tracker.update(FakeCtx(), bar4, [fresh])
    assert len(tracker.get_active()) == 0
    assert len(update4.terminal_instances) == 1
    assert update4.terminal_instances[0].state == "COMPLETED"

    # Serializer write
    inst = update4.terminal_instances[0]
    ok = serializer.write(inst)
    assert ok is True

    # Vérif fichier JSONL contient bien la ligne
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    with open(files[0], "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["terminal_state"] == "COMPLETED"
    assert payload["scenario_name"] == "Bullish continuation"
    assert payload["outcome_pnl_r"] > 0  # profit


def test_e2e_replay_stop_hit_invalidates_and_serialize(tmp_path):
    """Replay : create -> zone touch -> stop hit -> JSONL INVALIDATED."""
    from CORE.scenario_tracker import ScenarioTracker
    from CORE.scenario_serializer import JSONLSerializer
    from dataclasses import dataclass, field

    @dataclass
    class FakeSetup:
        side: str = "long"
        entry_price: float = 29500
        entry_zone_low: float = 29490
        entry_zone_high: float = 29510
        target_1: float = 29700
        target_2: float = 29800
        stop_loss: float = 29400
        setup_type: str = "swing"
        conditions_validation: list = field(default_factory=list)
        conditions_invalidation: list = field(default_factory=list)
        rationale: str = ""

    @dataclass
    class FakeScenario:
        name: str = "Bullish continuation"
        direction: str = "bullish"
        heuristic_score: int = 65
        description: str = ""
        key_levels_used: list = field(default_factory=list)
        setups: list = field(default_factory=list)
        primary: bool = False

    @dataclass
    class FakeCtx:
        symbol: str = "NQ"
        atr: float = 100.0
        macro_regime: str = "calm"

    fresh = FakeScenario(setups=[FakeSetup()])

    tracker = ScenarioTracker(symbol="NQ")
    serializer = JSONLSerializer(symbol="NQ", logs_dir=str(tmp_path))

    # Bar 1 : create + zone touch
    bar1 = {"ts": 1781256960000, "close": 29495, "high": 29505, "low": 29495}
    tracker.update(FakeCtx(), bar1, [fresh])

    # Bar 2 : stop hit
    bar2 = {"ts": 1781257020000, "close": 29380, "high": 29490, "low": 29380}
    update = tracker.update(FakeCtx(), bar2, [fresh])
    assert len(update.terminal_instances) == 1
    inst = update.terminal_instances[0]
    assert inst.state == "INVALIDATED"
    assert inst.invalidation_reason == "stop_hit"

    serializer.write(inst)
    files = list(tmp_path.glob("*.jsonl"))
    with open(files[0], "r", encoding="utf-8") as f:
        payload = json.loads(f.readline())
    assert payload["terminal_state"] == "INVALIDATED"
    assert payload["invalidation_reason"] == "stop_hit"
    assert payload["outcome_pnl_r"] < 0  # perte


# ════════════════════════════════════════════════════════════════════════════
# Multi-symbol isolation
# ════════════════════════════════════════════════════════════════════════════

def test_e2e_multi_symbol_isolation():
    """ScenarioTracker per-symbol : NQ et ES isoles, scenario_id distincts."""
    from CORE.scenario_tracker import ScenarioTracker, make_scenario_id

    id_nq = make_scenario_id("Bullish continuation", "long", 29500.0,
                              1781256960000, "NQ")
    id_es = make_scenario_id("Bullish continuation", "long", 29500.0,
                              1781256960000, "ES")
    assert id_nq != id_es, "Scenario IDs doivent etre distincts par symbol"

    tracker_nq = ScenarioTracker(symbol="NQ")
    tracker_es = ScenarioTracker(symbol="ES")
    assert tracker_nq is not tracker_es


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
