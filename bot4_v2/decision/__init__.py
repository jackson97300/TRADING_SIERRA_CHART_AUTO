"""Bot 4 v2 decision : decision_router + routes (narrative, layered) + state machine.

Spec Phase P3 (sem 5-6) :
- narrative_state.py : State machine PENDING/ACTIVE/TRIGGERED/INVALIDATED/COMPLETED
- route_narrative.py : scenarios FIRST-CLASS
- route_layered.py : voie L2 mean reversion (OPTIONNEL)
- decision_router.py : orchestre routes + freshness gate

API publique exposee P3 batch 1 (state machine seul) :
- narrative_state : ScenarioState, ScenarioInstance, ScenarioTracker, Transition
"""
from bot4_v2.decision.narrative_state import (
    ScenarioInstance,
    ScenarioState,
    ScenarioTracker,
    Transition,
)
from bot4_v2.decision.scenario_registry import (
    ScenarioContext,
    ScenarioDetector,
    ScenarioFire,
    ScenarioRegistry,
    make_signal_id,
    make_timestamp_utc,
)
from bot4_v2.decision.decision_router import (
    ClosedSignal,
    DecisionRouter,
    DispatchedBracket,
    RouterSettings,
    RouterTickResult,
)

__all__ = [
    # narrative_state
    "ScenarioInstance",
    "ScenarioState",
    "ScenarioTracker",
    "Transition",
    # scenario_registry
    "ScenarioContext",
    "ScenarioDetector",
    "ScenarioFire",
    "ScenarioRegistry",
    "make_signal_id",
    "make_timestamp_utc",
    # decision_router
    "ClosedSignal",
    "DecisionRouter",
    "DispatchedBracket",
    "RouterSettings",
    "RouterTickResult",
]
