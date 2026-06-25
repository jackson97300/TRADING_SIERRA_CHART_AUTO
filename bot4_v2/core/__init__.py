"""Bot 4 v2 core : sources isolation (regime, MenthorQ, narrative, bar_freshness, scenario_conditions).

FORK de CORE/* (regime_engine_v2, bar_freshness, narrative_engine,
scenario_conditions) avec adaptations bot4_v2 :
- Params explicites (pas de hardcoded path/env var)
- Telemetry via bot4_v2.observability.telemetry
- Isolation totale vs CORE/* (modifications bot4_v2 ne cassent pas Bot 1/2/3)

Spec Phase P2 (sem 3-4) sources isolation.

API publique exposee :
- bar_freshness : check_bar_freshness
- regime_source : compute_regime, RegimeAnalysis, REGIME_CALIB_VERSION
- scenario_conditions : ConditionNode DSL (Atomic/Composite + parser legacy)
- narrative_engine : build_narrative_context, NarrativeContext + 5 states
"""
from bot4_v2.core.bar_freshness import check_bar_freshness
from bot4_v2.core.narrative_engine import (
    CONFLUENCE_ATR_FRAC,
    DAY_TYPE_MAP,
    OPEN_RELATION_MAP,
    PROFILE_SHAPE_MAP,
    KeyLevel,
    MarketStructureState,
    NarrativeContext,
    OrderFlowState,
    PatternsDetected,
    SessionState,
    build_narrative_context,
)
from bot4_v2.core.menthorq_source import (
    MenthorQLevels,
    load_menthorq_levels,
    menthorq_levels_to_key_levels,
)
from bot4_v2.core.regime_source import (
    REGIME_CALIB_VERSION,
    REGIME_MIN_VOTES_THRESHOLD,
    RegimeAnalysis,
    compute_regime,
    compute_regime_dict,
)
from bot4_v2.core.scenario_conditions import (
    KNOWN_FIELDS,
    UNPARSABLE_FIELD,
    VALID_COMPOSITE_OPS,
    VALID_OPERATORS,
    AtomicCondition,
    CompositeCondition,
    ConditionNode,
    evaluate_conditions,
    parse_legacy_condition,
    parse_legacy_conditions_list,
)

__all__ = [
    # bar_freshness
    "check_bar_freshness",
    # narrative_engine
    "CONFLUENCE_ATR_FRAC",
    "DAY_TYPE_MAP",
    "OPEN_RELATION_MAP",
    "PROFILE_SHAPE_MAP",
    "KeyLevel",
    "MarketStructureState",
    "NarrativeContext",
    "OrderFlowState",
    "PatternsDetected",
    "SessionState",
    "build_narrative_context",
    # menthorq_source
    "MenthorQLevels",
    "load_menthorq_levels",
    "menthorq_levels_to_key_levels",
    # regime_source
    "REGIME_CALIB_VERSION",
    "REGIME_MIN_VOTES_THRESHOLD",
    "RegimeAnalysis",
    "compute_regime",
    "compute_regime_dict",
    # scenario_conditions
    "AtomicCondition",
    "CompositeCondition",
    "ConditionNode",
    "KNOWN_FIELDS",
    "UNPARSABLE_FIELD",
    "VALID_COMPOSITE_OPS",
    "VALID_OPERATORS",
    "evaluate_conditions",
    "parse_legacy_condition",
    "parse_legacy_conditions_list",
]
