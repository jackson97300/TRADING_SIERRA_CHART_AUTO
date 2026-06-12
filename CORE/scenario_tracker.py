"""scenario_tracker.py - Phase B.5 lifecycle dynamique scenarios.

Tracker stateful cross-bar pour ScenarioInstance.
Transforme les `Scenario` STATELESS (re-emis from scratch par
scenario_generator.generate_scenarios() a chaque bar) en
`ScenarioInstance` STATEFUL avec :
- scenario_id UUID stable cross-bar
- State machine 7 etats (PENDING/ACTIVE/TRIGGERED/VALIDATED/COMPLETED/INVALIDATED/EXPIRED)
- Tracking MFE/MAE (Lopez AFML ch.3 Triple Barrier)
- Outcome labeling pour Phase C calibration (Platt scaling / isotonic)

# Decoupage Phase B.5

Ce fichier (B.5.1 - Foundation) contient :
- States constants + transitions valides
- ScenarioInstance + StateTransition dataclasses
- Constantes (timeouts par setup_type, match_threshold_atr, cooldown)

Composants suivants livres separement :
- B.5.2 : ConditionNode DSL + legacy parser
- B.5.3 : ScenarioTracker.update() + matching algorithm
- B.5.4 : JSONL serialization + integration pipeline
- B.5.5 : Tests E2E replay JSONL + smoke

# Reference design

Plan agent design 12/06 (~800 LOC total).
Reference Lopez AFML "Advances in Financial Machine Learning" ch.3-7.
Reference .claude/rules/critical-tasks-review.md (regle souveraine logs).

Auteur : MIA Trading V5 Phase B.5 Foundation
Date   : 2026-06-12
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ════════════════════════════════════════════════════════════════════════════
# STATE MACHINE - 7 etats + transitions valides
# ════════════════════════════════════════════════════════════════════════════

# Non-terminaux : actifs dans le tracker
STATE_PENDING            = "PENDING"             # emis, price hors entry_zone
STATE_ACTIVE_ENTRY_ZONE  = "ACTIVE_ENTRY_ZONE"   # price dans entry_zone, attente confirm
STATE_TRIGGERED          = "TRIGGERED"           # entry + validation match
STATE_VALIDATED          = "VALIDATED"           # target_1 hit (partial profit)

# Terminaux : serializes + retires du active set
STATE_COMPLETED          = "COMPLETED"           # target_2 hit ou full close
STATE_INVALIDATED        = "INVALIDATED"         # stop_loss hit OU conditions
STATE_EXPIRED            = "EXPIRED"             # bars_alive > max threshold

NON_TERMINAL_STATES = frozenset({
    STATE_PENDING,
    STATE_ACTIVE_ENTRY_ZONE,
    STATE_TRIGGERED,
    STATE_VALIDATED,
})

TERMINAL_STATES = frozenset({
    STATE_COMPLETED,
    STATE_INVALIDATED,
    STATE_EXPIRED,
})

# Transitions valides : from_state -> {to_state}
# Source : Plan agent design Phase B.5
VALID_TRANSITIONS = {
    STATE_PENDING: frozenset({
        STATE_ACTIVE_ENTRY_ZONE,
        STATE_INVALIDATED,  # gap beyond stop avant zone touchee
        STATE_EXPIRED,
    }),
    STATE_ACTIVE_ENTRY_ZONE: frozenset({
        STATE_TRIGGERED,
        STATE_INVALIDATED,
        STATE_EXPIRED,  # zone touchee mais pas validation conditions
    }),
    STATE_TRIGGERED: frozenset({
        STATE_VALIDATED,    # target_1 hit
        STATE_INVALIDATED,  # stop hit OR conditions
        STATE_EXPIRED,
    }),
    STATE_VALIDATED: frozenset({
        STATE_COMPLETED,    # target_2 hit OR full close
        STATE_INVALIDATED,  # stop trail hit
        STATE_EXPIRED,
    }),
    # Terminaux : aucune transition sortante
    STATE_COMPLETED:    frozenset(),
    STATE_INVALIDATED:  frozenset(),
    STATE_EXPIRED:      frozenset(),
}


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Verifie qu'une transition est autorisee par la state machine."""
    return to_state in VALID_TRANSITIONS.get(from_state, frozenset())


def is_terminal(state: str) -> bool:
    """True si le state est terminal (serialise + retire du active set)."""
    return state in TERMINAL_STATES


# ════════════════════════════════════════════════════════════════════════════
# CONSTANTES TIMEOUT + MATCHING
# ════════════════════════════════════════════════════════════════════════════

# Expiration timeout par setup_type (en bars 1min)
# Plan agent Q3 : differentier scalp/swing imperatif
# Lopez vertical barrier ~ 1.5x horizon median trade type.
MAX_BARS_ALIVE_PER_TYPE = {
    "scalp": 15,   # 15 min horizon
    "swing": 120,  # 2h horizon
    "default": 60, # fallback
}

# Bars max en ACTIVE_ENTRY_ZONE sans validation -> EXPIRED
MAX_BARS_IN_ZONE_PER_TYPE = {
    "scalp": 5,
    "swing": 20,
    "default": 10,
}

# Bars sans match fresh -> decay vers EXPIRED (Plan agent step 9)
NO_MATCH_DECAY_BARS = 15

# Match threshold par scenario_name (Plan agent Q2)
# Range scenarios plus tolerants, FVG plus serres (zones precises Steidlmayer)
MATCH_THRESHOLD_ATR_DEFAULT = 0.10
MATCH_THRESHOLD_ATR_PER_NAME = {
    "Range bound LONG fade": 0.20,
    "Range bound SHORT fade": 0.20,
    "FVG Magnet UP": 0.05,
    "FVG Magnet DOWN": 0.05,
    "Failed Breakout LONG (Spring)": 0.15,
    "Failed Breakout SHORT (UTAD)": 0.15,
}


def get_match_threshold(scenario_name: str) -> float:
    """Retourne le seuil match (ATR fraction) par scenario_name."""
    return MATCH_THRESHOLD_ATR_PER_NAME.get(scenario_name, MATCH_THRESHOLD_ATR_DEFAULT)


def get_max_bars_alive(setup_type: str) -> int:
    """Retourne max_bars_alive par setup_type."""
    return MAX_BARS_ALIVE_PER_TYPE.get(setup_type, MAX_BARS_ALIVE_PER_TYPE["default"])


def get_max_bars_in_zone(setup_type: str) -> int:
    """Retourne max_bars_in_zone par setup_type."""
    return MAX_BARS_IN_ZONE_PER_TYPE.get(setup_type, MAX_BARS_IN_ZONE_PER_TYPE["default"])


# Recreation cooldown apres INVALIDATED (Plan agent matching algorithm edge case)
RECREATION_COOLDOWN_BARS = 10


# ════════════════════════════════════════════════════════════════════════════
# DATACLASSES
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class StateTransition:
    """Trace d'une transition d'etat (audit + log JSONL)."""
    from_state: str
    to_state: str
    ts_ms: int
    bar_index: int
    trigger: str  # "entry_zone_touch", "target_1_hit", "stop_hit",
                  # "validation_match", "max_bars_expired", "decay_no_match"
    bar_close: float
    matched_conditions: list = field(default_factory=list)


@dataclass
class ScenarioInstance:
    """Scenario tracke a travers le temps avec lifecycle complet.

    scenario_id : UUID stable cross-bar (hash signature stable
                  basee sur created_at_ts + scenario_name + side + entry_price).
    state : un des 7 etats VALID_TRANSITIONS.
    """
    # Identite stable
    scenario_id: str
    scenario_name: str
    symbol: str
    side: str         # "long" / "short"
    setup_type: str   # "scalp" / "swing"

    # Timing
    created_at_ts: int
    last_update_ts: int
    bars_alive: int = 0
    bars_in_zone: int = 0
    bars_no_match: int = 0    # decay quand scenario_generator ne re-emet plus

    # State machine
    state: str = STATE_PENDING
    state_history: list = field(default_factory=list)  # List[StateTransition]
    invalidation_reason: Optional[str] = None
    expiration_reason: Optional[str] = None

    # Prix / niveaux (snapshot creation, immutable apres)
    entry_price: float = 0.0
    entry_zone_low: float = 0.0
    entry_zone_high: float = 0.0
    target_1: float = 0.0
    target_2: Optional[float] = None
    stop_loss: float = 0.0

    # Conditions (B.5.2 ConditionNode List - placeholder list[str] pour B.5.1)
    conditions_validation: list = field(default_factory=list)
    conditions_invalidation: list = field(default_factory=list)

    # Scoring heuristique
    heuristic_score_at_creation: int = 0
    heuristic_score_current: int = 0
    regime_vix_at_creation: str = "UNKNOWN"
    atr_at_creation: float = 1.0

    # Outcome tracking (Lopez Triple Barrier)
    entry_touched_at_ts: Optional[int] = None
    triggered_at_ts: Optional[int] = None
    target_1_hit_at_ts: Optional[int] = None
    target_2_hit_at_ts: Optional[int] = None
    stop_hit_at_ts: Optional[int] = None
    terminal_ts: Optional[int] = None
    mfe_atr: float = 0.0   # Max favorable excursion en ATR units (signed)
    mae_atr: float = 0.0   # Max adverse excursion (signed - LONG = negatif si bar.low < entry)
    outcome_pnl_atr: Optional[float] = None
    outcome_pnl_r: Optional[float] = None  # pnl / risk_initial (Lopez R-multiple)

    # Cross-link narrative (Phase C calibration)
    key_levels_used: list = field(default_factory=list)  # List[str] labels stables
    rationale: str = ""

    def is_terminal(self) -> bool:
        """True si scenario en etat terminal (a serializer)."""
        return is_terminal(self.state)


# ════════════════════════════════════════════════════════════════════════════
# UUID GENERATOR
# ════════════════════════════════════════════════════════════════════════════

def make_scenario_id(scenario_name: str, side: str, entry_price: float,
                     created_at_ts: int, symbol: str) -> str:
    """Genere scenario_id stable hash signature.

    Format : 16 hex chars (= 64 bits).
    Inputs deterministes : meme bar + meme scenario = meme id.

    Permet :
    - Reproducibilite tests
    - Dedup si scenario_generator re-emit le meme scenario sans tracker
    - Phase C : join JSONL outcomes ↔ snapshot live unique
    """
    import hashlib
    key = f"{symbol}|{scenario_name}|{side}|{entry_price:.4f}|{created_at_ts}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return h[:16]
