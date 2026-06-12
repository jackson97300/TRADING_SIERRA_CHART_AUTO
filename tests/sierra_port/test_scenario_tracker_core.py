"""Tests scenario_tracker.py Phase B.5.3 Tracker core.

Couvre :
- ScenarioTracker.update() lifecycle complet (PENDING -> ACTIVE -> TRIGGERED -> VALIDATED -> COMPLETED)
- INVALIDATED via stop hit
- EXPIRED via timeout
- MFE/MAE tracking
- Matching algorithm (fresh vs active)
- Cooldown anti-recreation post-INVALIDATED
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# Fixtures : fakes Scenario + TradingSetup + NarrativeContext
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class FakeSetup:
    side: str
    entry_price: float
    entry_zone_low: float
    entry_zone_high: float
    target_1: float
    target_2: Optional[float]
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


def _make_fresh_bullish(entry=29500, target=29700, stop=29400, score=65):
    """Fresh Bullish continuation scenario pour tests."""
    setup = FakeSetup(
        side="long",
        entry_price=entry,
        entry_zone_low=entry - 10,
        entry_zone_high=entry + 10,
        target_1=target,
        target_2=target + 100,
        stop_loss=stop,
        setup_type="swing",
    )
    return FakeScenario(
        name="Bullish continuation",
        direction="bullish",
        heuristic_score=score,
        setups=[setup],
    )


def _bar(ts, close, high=None, low=None):
    """Bar minimal pour tests."""
    return {
        "ts": ts,
        "close": close,
        "high": high if high is not None else close,
        "low": low if low is not None else close,
    }


# ════════════════════════════════════════════════════════════════════════════
# Test instanciation + premier update
# ════════════════════════════════════════════════════════════════════════════

def test_tracker_init_emits_log():
    from CORE.scenario_tracker import ScenarioTracker
    emits = []
    tracker = ScenarioTracker(symbol="NQ", log_emit=lambda c, ctx: emits.append((c, ctx)))
    assert any(code == "SCENARIO_TRACKER_INIT" for code, _ in emits)
    assert tracker.symbol == "NQ"


def test_tracker_update_creates_pending_instance():
    """1er update avec fresh scenario -> instance PENDING."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    ctx = FakeCtx()
    bar = _bar(1000, 29450)  # close hors entry_zone
    fresh = _make_fresh_bullish(entry=29500)
    update = tracker.update(ctx, bar, [fresh])
    active = tracker.get_active()
    assert len(active) == 1
    assert active[0].state == "PENDING"
    assert active[0].scenario_name == "Bullish continuation"
    assert active[0].bars_alive == 0  # bars_alive ticke avant create


def test_tracker_creates_emits_scenario_created():
    from CORE.scenario_tracker import ScenarioTracker
    emits = []
    tracker = ScenarioTracker(symbol="NQ",
                              log_emit=lambda c, ctx: emits.append((c, ctx)))
    fresh = _make_fresh_bullish()
    tracker.update(FakeCtx(), _bar(1000, 29450), [fresh])
    assert any(code == "SCENARIO_CREATED" for code, _ in emits)


# ════════════════════════════════════════════════════════════════════════════
# Lifecycle PENDING -> ACTIVE -> TRIGGERED
# ════════════════════════════════════════════════════════════════════════════

def test_lifecycle_pending_to_active_on_zone_touch():
    """PENDING -> ACTIVE_ENTRY_ZONE quand bar overlap zone."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    # Bar 1 : hors zone
    tracker.update(FakeCtx(), _bar(1000, 29450), [fresh])
    assert tracker.get_active()[0].state == "PENDING"
    # Bar 2 : entry zone touchee (entry 29500 + zone [-10, +10])
    tracker.update(FakeCtx(), _bar(60000, 29495, high=29505), [fresh])
    assert tracker.get_active()[0].state == "ACTIVE_ENTRY_ZONE"


def test_lifecycle_active_stays_active_when_no_conditions():
    """Si conditions_validation vide : reste ACTIVE (observation only).

    Decision design : pas d'auto-trigger sur conditions vides (over-engineering).
    Trader decide manuellement. target_1 hit -> direct VALIDATED (skip TRIGGERED).
    """
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    fresh.setups[0].conditions_validation = []
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])
    state = tracker.get_active()[0].state
    assert state == "ACTIVE_ENTRY_ZONE"


def test_lifecycle_active_to_triggered_with_conditions_match():
    """TRIGGERED si conditions_validation match."""
    from CORE.scenario_tracker import ScenarioTracker
    from CORE.scenario_conditions import AtomicCondition
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    fresh.setups[0].conditions_validation = [
        AtomicCondition("delta_bar", ">", 0),
    ]
    # Zone touchee + delta_bar > 0
    bar = _bar(1000, 29500, high=29505)
    bar["delta_bar"] = 10
    tracker.update(FakeCtx(), bar, [fresh])
    assert tracker.get_active()[0].state == "TRIGGERED"


def test_lifecycle_active_stays_if_validation_fails():
    """ACTIVE reste ACTIVE si conditions_validation match pas."""
    from CORE.scenario_tracker import ScenarioTracker
    from CORE.scenario_conditions import AtomicCondition
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    fresh.setups[0].conditions_validation = [
        AtomicCondition("delta_bar", ">", 0),
    ]
    bar = _bar(1000, 29500, high=29505)
    bar["delta_bar"] = -10  # fail
    tracker.update(FakeCtx(), bar, [fresh])
    assert tracker.get_active()[0].state == "ACTIVE_ENTRY_ZONE"


# ════════════════════════════════════════════════════════════════════════════
# Target hits TRIGGERED -> VALIDATED -> COMPLETED
# ════════════════════════════════════════════════════════════════════════════

def test_target_1_hit_validates_long():
    """target_1 hit -> VALIDATED (direct, skip TRIGGERED si pas de conditions).

    Path : PENDING -> ACTIVE_ENTRY_ZONE -> VALIDATED (target_1)
    """
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500, target=29700, stop=29400)
    # Bar 1 : zone touchee (sans conditions = reste ACTIVE)
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])
    assert tracker.get_active()[0].state == "ACTIVE_ENTRY_ZONE"
    # Bar 2 : target_1 hit -> VALIDATED direct
    tracker.update(FakeCtx(), _bar(60000, 29710, high=29710), [fresh])
    assert tracker.get_active()[0].state == "VALIDATED"


def test_target_2_completed_long():
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500, target=29700, stop=29400)
    # target_2 = 29800 (target + 100)
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])
    tracker.update(FakeCtx(), _bar(60000, 29710), [fresh])  # validates
    update = tracker.update(FakeCtx(), _bar(120000, 29810, high=29810), [fresh])
    # COMPLETED -> retire actifs, present dans terminal_instances
    assert len(tracker.get_active()) == 0
    assert len(update.terminal_instances) == 1
    assert update.terminal_instances[0].state == "COMPLETED"
    assert update.terminal_instances[0].outcome_pnl_r is not None
    assert update.terminal_instances[0].outcome_pnl_r > 0  # profit


# ════════════════════════════════════════════════════════════════════════════
# Stop hit -> INVALIDATED
# ════════════════════════════════════════════════════════════════════════════

def test_stop_hit_invalidates_long():
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500, target=29700, stop=29400)
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])  # zone + trigger
    update = tracker.update(FakeCtx(), _bar(60000, 29380, low=29380), [fresh])
    assert len(tracker.get_active()) == 0
    assert update.terminal_instances[0].state == "INVALIDATED"
    assert update.terminal_instances[0].invalidation_reason == "stop_hit"
    assert update.terminal_instances[0].outcome_pnl_r < 0


def test_stop_hit_emits_alerte_log():
    """SCENARIO_STOP_HIT (ALERTE) emit."""
    from CORE.scenario_tracker import ScenarioTracker
    emits = []
    tracker = ScenarioTracker(symbol="NQ",
                              log_emit=lambda c, ctx: emits.append((c, ctx)))
    fresh = _make_fresh_bullish(entry=29500, stop=29400)
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])
    tracker.update(FakeCtx(), _bar(60000, 29380, low=29380), [fresh])
    assert any(code == "SCENARIO_STOP_HIT" for code, _ in emits)


# ════════════════════════════════════════════════════════════════════════════
# MFE / MAE tracking
# ════════════════════════════════════════════════════════════════════════════

def test_mfe_mae_long_tracked():
    """MFE = max favorable / MAE = max adverse en ATR units."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    ctx = FakeCtx(atr=100.0)
    tracker.update(ctx, _bar(1000, 29500, high=29505), [fresh])  # zone touched
    # Bar 2 : excursion favorable +50 ticks, adverse -20
    tracker.update(ctx, _bar(60000, 29530, high=29550, low=29480), [fresh])
    inst = tracker.get_active()[0]
    # MFE = (29550 - 29500) / 100 = 0.5
    assert inst.mfe_atr >= 0.5
    # MAE = (29480 - 29500) / 100 = -0.2
    assert inst.mae_atr <= -0.2


# ════════════════════════════════════════════════════════════════════════════
# Matching algorithm
# ════════════════════════════════════════════════════════════════════════════

def test_matching_same_scenario_updates_score():
    """Fresh re-emis avec score different -> active mis a jour (pas duplique)."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    f1 = _make_fresh_bullish(entry=29500, score=65)
    tracker.update(FakeCtx(), _bar(1000, 29450), [f1])  # > stop 29400
    # Bar 2 : meme scenario emit avec score 75 (boost)
    f2 = _make_fresh_bullish(entry=29500, score=75)
    tracker.update(FakeCtx(), _bar(60000, 29450), [f2])
    active = tracker.get_active()
    assert len(active) == 1
    assert active[0].heuristic_score_at_creation == 65
    assert active[0].heuristic_score_current == 75


def test_matching_different_entry_creates_new():
    """Fresh avec entry tres different -> nouvelle instance."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    f1 = _make_fresh_bullish(entry=29500)
    tracker.update(FakeCtx(), _bar(1000, 29450), [f1])  # > stop 29400
    # Entry decale de 200 ticks = >> threshold 0.10 ATR * 100 = 10
    f2 = _make_fresh_bullish(entry=29700)
    tracker.update(FakeCtx(), _bar(60000, 29450), [f2])
    assert len(tracker.get_active()) == 2


# ════════════════════════════════════════════════════════════════════════════
# Expiration / decay
# ════════════════════════════════════════════════════════════════════════════

def test_expiration_scalp_after_15_bars():
    """Scalp expire apres 15 bars sans hit ni trigger."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    fresh.setups[0].setup_type = "scalp"
    # Bar 1 : create
    tracker.update(FakeCtx(), _bar(0, 29450), [fresh])
    # Repete 15 bars sans match (price reste hors zone)
    # Le scenario doit etre EXPIRED via decay (bars_no_match > 15)
    # OU via timeout scalp (bars_alive > 15)
    for i in range(20):
        tracker.update(FakeCtx(), _bar((i + 1) * 60000, 29000), [])  # pas de fresh
    assert len(tracker.get_active()) == 0


def test_decay_no_match_expires_pending():
    """PENDING sans match fresh pendant > NO_MATCH_DECAY_BARS -> EXPIRED."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    tracker.update(FakeCtx(), _bar(0, 29450), [fresh])  # creates
    # 16 bars sans fresh -> decay
    for i in range(16):
        tracker.update(FakeCtx(), _bar((i + 1) * 60000, 29000), [])
    assert len(tracker.get_active()) == 0


# ════════════════════════════════════════════════════════════════════════════
# Cooldown anti-recreation post-INVALIDATED
# ════════════════════════════════════════════════════════════════════════════

def test_cooldown_blocks_recreation_after_stop():
    """Apres stop hit, meme scenario meme niveau bloque pendant cooldown."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500, stop=29400)
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])  # zone + trig
    tracker.update(FakeCtx(), _bar(60000, 29380, low=29380), [fresh])  # stop hit -> INVALIDATED
    assert len(tracker.get_active()) == 0
    # Tentative recreation immediate sur meme niveau -> cooldown bloque
    fresh2 = _make_fresh_bullish(entry=29500)
    tracker.update(FakeCtx(), _bar(120000, 29000), [fresh2])
    assert len(tracker.get_active()) == 0  # toujours bloque


# ════════════════════════════════════════════════════════════════════════════
# Session rollover
# ════════════════════════════════════════════════════════════════════════════

def test_reset_session_flushes_all():
    """reset_session() expire tous les actifs."""
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500)
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])
    assert len(tracker.get_active()) == 1
    n = tracker.reset_session()
    assert n == 1
    assert len(tracker.get_active()) == 0


def test_reset_session_emits_flush_log():
    from CORE.scenario_tracker import ScenarioTracker
    emits = []
    tracker = ScenarioTracker(symbol="NQ",
                              log_emit=lambda c, ctx: emits.append((c, ctx)))
    fresh = _make_fresh_bullish()
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])
    tracker.reset_session()
    assert any(code == "SCENARIO_SESSION_FLUSH" for code, _ in emits)


# ════════════════════════════════════════════════════════════════════════════
# Recent terminals bounded FIFO
# ════════════════════════════════════════════════════════════════════════════

def test_recent_terminals_after_completion():
    from CORE.scenario_tracker import ScenarioTracker
    tracker = ScenarioTracker(symbol="NQ")
    fresh = _make_fresh_bullish(entry=29500, target=29700, stop=29400)
    tracker.update(FakeCtx(), _bar(1000, 29500, high=29505), [fresh])
    tracker.update(FakeCtx(), _bar(60000, 29710), [fresh])  # VALIDATED
    tracker.update(FakeCtx(), _bar(120000, 29810, high=29810), [fresh])  # COMPLETED
    recent = tracker.get_recent_terminals()
    assert len(recent) == 1
    assert recent[0].state == "COMPLETED"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
