"""scenario_tracker.py - Phase B.5 lifecycle dynamique scenarios.

# Phase B.5.3 - Tracker core (cette livraison) :
- ScenarioTracker class avec update() per-bar
- State machine transitions automatiques (stop hit, target hit, entry zone)
- Matching algorithm fresh vs active (anti-recreation cooldown)
- MFE/MAE tracking en ATR units (Lopez ch.3 Triple Barrier)
- Validation/invalidation conditions evaluation via ConditionNode DSL
- Decay actifs non-matched + expiration timeouts



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
        STATE_VALIDATED,   # target_1 hit avant validation conditions (skip TRIGGERED)
        STATE_INVALIDATED,
        STATE_EXPIRED,
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

_LogEmit = "Optional[Callable[[str, dict], None]]"


# ════════════════════════════════════════════════════════════════════════════
# SCENARIO TRACKER - Phase B.5.3
# ════════════════════════════════════════════════════════════════════════════

class ScenarioTracker:
    """Tracker stateful per-symbol pour ScenarioInstance lifecycle.

    Usage typique (1 tracker per symbol, instancie au boot du pipeline) :
        tracker = ScenarioTracker(symbol="NQ", log_emit=my_log_func)
        for bar in stream:
            ctx = build_narrative_context(bar)
            fresh = generate_scenarios(ctx)
            update = tracker.update(ctx, bar, fresh)
            # update.transitions = liste StateTransition cette bar
            # update.terminal_instances = ScenarioInstance terminees (a serializer)
            # update.active_snapshot = ScenarioInstance encore actifs

    Anti-PATTERN_11 : aucune decision trade. Lifecycle = observation only.
    Anti-VALIDATION_MISS : chaque transition emit un log_emit (si fourni).
    """

    def __init__(self,
                 symbol: str,
                 log_emit=None,
                 max_recent_terminals: int = 100):
        """Init tracker.

        Args:
            symbol : symbole tracke (ex "NQ", "ES", "MGC")
            log_emit : callable(code: str, ctx: dict) -> None (optionnel)
                       Si None, no-op. En tests, mock pour assert emits.
            max_recent_terminals : bounded queue terminaux pour debug rapide
        """
        self.symbol = symbol
        self._log_emit = log_emit
        self._active: dict = {}  # dict[scenario_id, ScenarioInstance]
        # Cooldown post-INVALIDATED : bloque recreation meme scenario sur meme niveau
        # dict[(name, side, entry_bucket), expires_at_bar_count]
        self._recently_invalidated: dict = {}
        self._bar_count: int = 0
        self._recent_terminals: list = []  # FIFO bounded
        self._max_recent = max_recent_terminals
        self._emit("SCENARIO_TRACKER_INIT", {
            "sym": symbol,
            "max_bars": MAX_BARS_ALIVE_PER_TYPE,
        })

    # ── API publique ───────────────────────────────────────────────────────

    def update(self, ctx, bar: dict, fresh_scenarios: list):
        """Update tracker apres reception nouveau bar + fresh scenarios.

        Args:
            ctx : NarrativeContext (ou None - utilise juste pour symbol check)
            bar : dict bar live_enriched
            fresh_scenarios : list[Scenario] retournes par generate_scenarios()

        Returns:
            TrackerUpdate (transitions, terminal_instances, active_snapshot)
        """
        self._bar_count += 1
        bar_ts = int(bar.get("ts", 0))
        bar_close = float(bar.get("close", 0.0))
        bar_high = float(bar.get("high", bar.get("bar_high", bar_close)))
        bar_low = float(bar.get("low", bar.get("bar_low", bar_close)))
        transitions = []

        # Step 1: tick bars_alive / bars_no_match sur actifs EXISTANTS
        # (les nouvelles instances creees au step 8 demarrent a 0).
        for inst in list(self._active.values()):
            if inst.is_terminal():
                continue
            inst.bars_alive += 1
            inst.bars_no_match += 1
            inst.last_update_ts = bar_ts

        # Step 8: match fresh scenarios avec actifs OR creer nouvelles instances
        # (avance avant les autres steps pour que les nouvelles instances soient
        # immediatement evaluees pour entry_zone touch / barriers)
        for fresh in fresh_scenarios:
            self._match_or_create(fresh, ctx, bar_ts, bar_close)

        # Step 2: update MFE/MAE (apres step 8, inclut nouvelles instances)
        for inst in self._active.values():
            if inst.is_terminal():
                continue
            self._update_mfe_mae(inst, bar_high, bar_low)

        # Step 3+4: check stop / target hits (inclut nouvelles instances)
        for inst in list(self._active.values()):
            if inst.is_terminal():
                continue
            t = self._check_barrier_hits(inst, bar_ts, bar_high, bar_low, bar_close)
            if t is not None:
                transitions.append(t)

        # Step 5: entry_zone touch PENDING -> ACTIVE_ENTRY_ZONE
        for inst in list(self._active.values()):
            if inst.state != STATE_PENDING:
                continue
            t = self._check_entry_zone_touch(inst, bar_ts, bar_high, bar_low, bar_close)
            if t is not None:
                transitions.append(t)

        # Step 5b: ACTIVE_ENTRY_ZONE tick bars_in_zone
        for inst in self._active.values():
            if inst.state == STATE_ACTIVE_ENTRY_ZONE:
                inst.bars_in_zone += 1

        # Step 6: ACTIVE -> TRIGGERED via validation_conditions
        for inst in list(self._active.values()):
            if inst.state != STATE_ACTIVE_ENTRY_ZONE:
                continue
            t = self._check_validation_conditions(inst, bar, bar_ts, bar_close)
            if t is not None:
                transitions.append(t)

        # Step 7: invalidation_conditions sur non-terminaux
        for inst in list(self._active.values()):
            if inst.is_terminal():
                continue
            t = self._check_invalidation_conditions(inst, bar, bar_ts, bar_close)
            if t is not None:
                transitions.append(t)

        # Step 9: decay actifs sans match -> EXPIRED
        for inst in list(self._active.values()):
            if inst.is_terminal():
                continue
            if inst.bars_no_match > NO_MATCH_DECAY_BARS \
                    and inst.state in (STATE_PENDING, STATE_ACTIVE_ENTRY_ZONE):
                t = self._transition(
                    inst, STATE_EXPIRED, bar_ts, "decay_no_match", bar_close,
                )
                inst.expiration_reason = "decay_no_match"
                if t is not None:
                    transitions.append(t)

        # Step 10: check expiration globale bars_alive
        for inst in list(self._active.values()):
            if inst.is_terminal():
                continue
            if inst.bars_alive > get_max_bars_alive(inst.setup_type):
                t = self._transition(
                    inst, STATE_EXPIRED, bar_ts, "max_bars_expired", bar_close,
                )
                inst.expiration_reason = "max_bars_expired"
                if t is not None:
                    transitions.append(t)
            elif (inst.state == STATE_ACTIVE_ENTRY_ZONE
                  and inst.bars_in_zone > get_max_bars_in_zone(inst.setup_type)):
                t = self._transition(
                    inst, STATE_EXPIRED, bar_ts, "max_bars_in_zone", bar_close,
                )
                inst.expiration_reason = "max_bars_in_zone"
                if t is not None:
                    transitions.append(t)

        # Step 11: serialize terminaux + retirer
        terminal_instances = self._flush_terminals()

        # Step 12: cooldown decrement
        self._tick_invalidation_cooldown()

        # Snapshot actifs
        active_snapshot = list(self._active.values())

        return TrackerUpdate(
            transitions=transitions,
            terminal_instances=terminal_instances,
            active_snapshot=active_snapshot,
        )

    def get_active(self) -> list:
        """Snapshot actuel des scenarios actifs (non-terminaux)."""
        return [i for i in self._active.values() if not i.is_terminal()]

    def get_recent_terminals(self) -> list:
        """Derniers ScenarioInstance terminaux (FIFO bounded)."""
        return list(self._recent_terminals)

    # ── Helpers internes ────────────────────────────────────────────────────

    def _emit(self, code: str, ctx: dict) -> None:
        """Emit log via callable inject. No-op si log_emit=None."""
        if self._log_emit is None:
            return
        try:
            self._log_emit(code, ctx)
        except Exception:  # noqa: BLE001
            pass  # fail-safe : log emit ne casse jamais le pipeline

    def _update_mfe_mae(self, inst, bar_high: float, bar_low: float) -> None:
        """Maj MFE/MAE en ATR units du moment de la creation (Lopez)."""
        if inst.atr_at_creation <= 0:
            return
        atr = inst.atr_at_creation
        if inst.side == "long":
            # MFE LONG = bar_high - entry (positif = favorable)
            fav = (bar_high - inst.entry_price) / atr
            adv = (bar_low - inst.entry_price) / atr  # negatif si bar_low < entry
        else:
            # MFE SHORT = entry - bar_low (positif = favorable)
            fav = (inst.entry_price - bar_low) / atr
            adv = (inst.entry_price - bar_high) / atr  # negatif si bar_high > entry
        if fav > inst.mfe_atr:
            inst.mfe_atr = round(fav, 4)
        if adv < inst.mae_atr:
            inst.mae_atr = round(adv, 4)

    def _check_barrier_hits(self, inst, bar_ts: int,
                             bar_high: float, bar_low: float, bar_close: float):
        """Step 3+4 : check stop / target hits selon state + side.

        Ordre : stop d'abord (priorite anti-fantome), puis target.
        Si bar fait both, on traite stop (cote securite Lopez convention).
        """
        # Check stop hit (priorite anti-fantome)
        stop_hit = False
        if inst.side == "long" and bar_low <= inst.stop_loss:
            stop_hit = True
        if inst.side == "short" and bar_high >= inst.stop_loss:
            stop_hit = True
        if stop_hit and inst.state in (STATE_TRIGGERED, STATE_VALIDATED,
                                       STATE_ACTIVE_ENTRY_ZONE, STATE_PENDING):
            inst.stop_hit_at_ts = bar_ts
            inst.invalidation_reason = "stop_hit"
            inst.outcome_pnl_atr = round(
                (inst.stop_loss - inst.entry_price) / inst.atr_at_creation
                if inst.side == "long"
                else (inst.entry_price - inst.stop_loss) / inst.atr_at_creation,
                4,
            )
            return self._transition(
                inst, STATE_INVALIDATED, bar_ts, "stop_hit", bar_close,
            )

        # Check target hits (TRIGGERED -> VALIDATED via target_1)
        if inst.state == STATE_TRIGGERED:
            if inst.side == "long" and bar_high >= inst.target_1:
                inst.target_1_hit_at_ts = bar_ts
                return self._transition(
                    inst, STATE_VALIDATED, bar_ts, "target_1_hit", bar_close,
                )
            if inst.side == "short" and bar_low <= inst.target_1:
                inst.target_1_hit_at_ts = bar_ts
                return self._transition(
                    inst, STATE_VALIDATED, bar_ts, "target_1_hit", bar_close,
                )

        # ACTIVE_ENTRY_ZONE -> VALIDATED direct si target_1 hit (skip TRIGGERED)
        # Cas usage : conditions_validation vides ou unparsable (trader decide manuel),
        # target_1 hit prouve empiriquement que le trade a marche.
        if inst.state == STATE_ACTIVE_ENTRY_ZONE:
            if inst.side == "long" and bar_high >= inst.target_1:
                inst.target_1_hit_at_ts = bar_ts
                return self._transition(
                    inst, STATE_VALIDATED, bar_ts, "target_1_hit_no_trigger", bar_close,
                )
            if inst.side == "short" and bar_low <= inst.target_1:
                inst.target_1_hit_at_ts = bar_ts
                return self._transition(
                    inst, STATE_VALIDATED, bar_ts, "target_1_hit_no_trigger", bar_close,
                )

        # VALIDATED -> COMPLETED via target_2 (si dispo)
        if inst.state == STATE_VALIDATED and inst.target_2 is not None:
            if inst.side == "long" and bar_high >= inst.target_2:
                inst.target_2_hit_at_ts = bar_ts
                inst.outcome_pnl_atr = round(
                    (inst.target_2 - inst.entry_price) / inst.atr_at_creation, 4
                )
                return self._transition(
                    inst, STATE_COMPLETED, bar_ts, "target_2_hit", bar_close,
                )
            if inst.side == "short" and bar_low <= inst.target_2:
                inst.target_2_hit_at_ts = bar_ts
                inst.outcome_pnl_atr = round(
                    (inst.entry_price - inst.target_2) / inst.atr_at_creation, 4
                )
                return self._transition(
                    inst, STATE_COMPLETED, bar_ts, "target_2_hit", bar_close,
                )
        return None

    def _check_entry_zone_touch(self, inst, bar_ts: int,
                                  bar_high: float, bar_low: float, bar_close: float):
        """Step 5 : PENDING -> ACTIVE_ENTRY_ZONE si bar overlap zone."""
        # Overlap = bar_low <= zone_high ET bar_high >= zone_low
        if bar_low <= inst.entry_zone_high and bar_high >= inst.entry_zone_low:
            inst.entry_touched_at_ts = bar_ts
            return self._transition(
                inst, STATE_ACTIVE_ENTRY_ZONE, bar_ts,
                "entry_zone_touch", bar_close,
            )
        return None

    def _check_validation_conditions(self, inst, bar: dict, bar_ts: int,
                                     bar_close: float):
        """Step 6 : ACTIVE -> TRIGGERED si conditions_validation evaluent True.

        Importation locale evaluate_conditions pour eviter circular import.
        """
        if not inst.conditions_validation:
            # Pas de conditions parsables = reste ACTIVE (observation only).
            # Trader decide manuellement. Si target_1 hit, transition direct VALIDATED.
            return None
        try:
            from CORE.scenario_conditions import evaluate_conditions
        except ImportError:
            from scenario_conditions import evaluate_conditions  # type: ignore
        all_pass, matched = evaluate_conditions(inst.conditions_validation, bar)
        if all_pass:
            inst.triggered_at_ts = bar_ts
            return self._transition(
                inst, STATE_TRIGGERED, bar_ts, "validation_match", bar_close,
                matched_conditions=matched,
            )
        return None

    def _check_invalidation_conditions(self, inst, bar: dict, bar_ts: int,
                                        bar_close: float):
        """Step 7 : INVALIDATED si conditions_invalidation evaluent True.

        Note : OR logic - une seule condition d'invalidation suffit.
        """
        if not inst.conditions_invalidation:
            return None
        try:
            from CORE.scenario_conditions import evaluate_conditions
        except ImportError:
            from scenario_conditions import evaluate_conditions  # type: ignore
        # Pour invalidation : ANY match suffit (OR cumule)
        for cond in inst.conditions_invalidation:
            try:
                if cond.evaluate(bar):
                    inst.invalidation_reason = cond.description or "cond_match"
                    return self._transition(
                        inst, STATE_INVALIDATED, bar_ts,
                        "invalidation_match", bar_close,
                        matched_conditions=[cond.description or "cond"],
                    )
            except Exception:  # noqa: BLE001
                continue  # fail-safe
        return None

    def _match_or_create(self, fresh, ctx, bar_ts: int, bar_close: float):
        """Step 8 : match fresh scenario avec actifs OR creer nouvelle instance."""
        if not fresh.setups:
            return
        setup = fresh.setups[0]
        sym = getattr(ctx, "symbol", self.symbol) if ctx is not None else self.symbol
        atr = float(getattr(ctx, "atr", 1.0)) if ctx is not None else 1.0
        if atr <= 0:
            atr = 1.0
        threshold = get_match_threshold(fresh.name) * atr
        # Match candidates
        matched = None
        for inst in self._active.values():
            if inst.is_terminal():
                continue
            if (inst.scenario_name == fresh.name
                    and inst.side == setup.side
                    and inst.symbol == sym
                    and abs(inst.entry_price - setup.entry_price) <= threshold):
                if matched is None or inst.created_at_ts < matched.created_at_ts:
                    matched = inst
        if matched is not None:
            matched.heuristic_score_current = int(fresh.heuristic_score)
            matched.bars_no_match = 0
            return
        # Pas de match -> verifier cooldown anti-recreation
        bucket = round(setup.entry_price / max(atr, 1e-6) / 0.5)
        cooldown_key = (fresh.name, setup.side, bucket)
        if cooldown_key in self._recently_invalidated:
            return  # cooldown actif
        # Creer nouvelle instance
        self._create_instance(fresh, setup, ctx, bar_ts, atr)

    def _create_instance(self, fresh, setup, ctx, bar_ts: int, atr: float) -> None:
        """Cree ScenarioInstance + emit SCENARIO_CREATED."""
        sym = getattr(ctx, "symbol", self.symbol) if ctx is not None else self.symbol
        regime = getattr(ctx, "macro_regime", "UNKNOWN") if ctx is not None else "UNKNOWN"
        # Parse conditions legacy si string
        try:
            from CORE.scenario_conditions import parse_legacy_conditions_list
        except ImportError:
            from scenario_conditions import parse_legacy_conditions_list  # type: ignore
        cond_val = parse_legacy_conditions_list(setup.conditions_validation or [])
        cond_inv = parse_legacy_conditions_list(setup.conditions_invalidation or [])
        sid = make_scenario_id(
            fresh.name, setup.side, setup.entry_price, bar_ts, sym,
        )
        inst = ScenarioInstance(
            scenario_id=sid,
            scenario_name=fresh.name,
            symbol=sym,
            side=setup.side,
            setup_type=getattr(setup, "setup_type", "swing"),
            created_at_ts=bar_ts,
            last_update_ts=bar_ts,
            entry_price=setup.entry_price,
            entry_zone_low=setup.entry_zone_low,
            entry_zone_high=setup.entry_zone_high,
            target_1=setup.target_1,
            target_2=setup.target_2,
            stop_loss=setup.stop_loss,
            conditions_validation=cond_val,
            conditions_invalidation=cond_inv,
            heuristic_score_at_creation=int(fresh.heuristic_score),
            heuristic_score_current=int(fresh.heuristic_score),
            regime_vix_at_creation=regime,
            atr_at_creation=atr,
            key_levels_used=[
                getattr(l, "label", str(l)) for l in fresh.key_levels_used
            ],
            rationale=getattr(setup, "rationale", ""),
        )
        self._active[sid] = inst
        self._emit("SCENARIO_CREATED", {
            "scenario_id": sid,
            "name": fresh.name,
            "sym": sym,
            "side": setup.side,
            "entry": setup.entry_price,
            "score": fresh.heuristic_score,
        })

    def _transition(self, inst, to_state: str, ts_ms: int, trigger: str,
                    bar_close: float, matched_conditions=None):
        """Effectue transition state + log + history append."""
        if not is_valid_transition(inst.state, to_state):
            return None  # transition refusee silencieusement (fail-safe)
        from_state = inst.state
        inst.state = to_state
        if to_state in TERMINAL_STATES and inst.terminal_ts is None:
            inst.terminal_ts = ts_ms
        t = StateTransition(
            from_state=from_state,
            to_state=to_state,
            ts_ms=ts_ms,
            bar_index=self._bar_count,
            trigger=trigger,
            bar_close=bar_close,
            matched_conditions=matched_conditions or [],
        )
        inst.state_history.append(t)
        # Emit logs selon transition
        if to_state == STATE_ACTIVE_ENTRY_ZONE:
            self._emit("SCENARIO_ENTRY_ZONE_TOUCHED", {
                "scenario_id": inst.scenario_id,
                "name": inst.scenario_name,
                "bar_low": bar_close,
                "bar_high": bar_close,
            })
        elif to_state == STATE_TRIGGERED:
            self._emit("SCENARIO_TRIGGERED", {
                "scenario_id": inst.scenario_id,
                "name": inst.scenario_name,
                "matched": ", ".join(matched_conditions or []),
                "bars_in_zone": inst.bars_in_zone,
            })
        elif to_state == STATE_VALIDATED:
            self._emit("SCENARIO_TARGET_1_HIT", {
                "scenario_id": inst.scenario_id,
                "name": inst.scenario_name,
                "target": inst.target_1,
                "bars_alive": inst.bars_alive,
            })
        elif to_state == STATE_COMPLETED:
            self._emit("SCENARIO_TARGET_2_HIT", {
                "scenario_id": inst.scenario_id,
                "name": inst.scenario_name,
                "target": inst.target_2,
                "bars_alive": inst.bars_alive,
                "mfe": inst.mfe_atr,
                "mae": inst.mae_atr,
            })
        elif to_state == STATE_INVALIDATED:
            code = "SCENARIO_STOP_HIT" if trigger == "stop_hit" else "SCENARIO_INVALIDATED"
            self._emit(code, {
                "scenario_id": inst.scenario_id,
                "name": inst.scenario_name,
                "stop": inst.stop_loss,
                "bars_alive": inst.bars_alive,
                "mae": inst.mae_atr,
                "reason": inst.invalidation_reason or trigger,
            })
        elif to_state == STATE_EXPIRED:
            self._emit("SCENARIO_EXPIRED", {
                "scenario_id": inst.scenario_id,
                "name": inst.scenario_name,
                "reason": inst.expiration_reason or trigger,
                "bars_alive": inst.bars_alive,
            })
        return t

    def _flush_terminals(self) -> list:
        """Step 11 : retire les terminaux du active set + ajoute au recent."""
        flushed = []
        keys_to_remove = []
        for sid, inst in self._active.items():
            if inst.is_terminal():
                # Calcul outcome_pnl_r (Lopez R-multiple) si pas deja set
                self._compute_outcome_r(inst)
                flushed.append(inst)
                keys_to_remove.append(sid)
                # Bucket cooldown si INVALIDATED
                if inst.state == STATE_INVALIDATED and inst.atr_at_creation > 0:
                    bucket = round(inst.entry_price / inst.atr_at_creation / 0.5)
                    self._recently_invalidated[(inst.scenario_name, inst.side, bucket)] = \
                        RECREATION_COOLDOWN_BARS
        for sid in keys_to_remove:
            del self._active[sid]
        # FIFO bounded recent_terminals
        for inst in flushed:
            self._recent_terminals.append(inst)
        if len(self._recent_terminals) > self._max_recent:
            self._recent_terminals = self._recent_terminals[-self._max_recent:]
        return flushed

    def _compute_outcome_r(self, inst) -> None:
        """Compute outcome_pnl_r (Lopez R-multiple) avant serialization."""
        if inst.outcome_pnl_r is not None:
            return
        if inst.atr_at_creation <= 0:
            return
        risk = abs(inst.entry_price - inst.stop_loss)
        if risk <= 0:
            return
        # Si target_2 hit -> pnl = target_2 - entry
        # Si stop hit -> pnl = stop - entry
        # Si target_1 hit puis EXPIRED -> pnl = target_1 - entry
        # Sinon EXPIRED sans hit -> pnl = 0 (fallback)
        if inst.target_2_hit_at_ts and inst.target_2 is not None:
            pnl = inst.target_2 - inst.entry_price
        elif inst.stop_hit_at_ts:
            pnl = inst.stop_loss - inst.entry_price
        elif inst.target_1_hit_at_ts:
            pnl = inst.target_1 - inst.entry_price
        else:
            pnl = 0.0
        if inst.side == "short":
            pnl = -pnl
        inst.outcome_pnl_r = round(pnl / risk, 4)

    def _tick_invalidation_cooldown(self) -> None:
        """Decrement cooldown bars-counter. Expired keys retires."""
        expired = [k for k, v in self._recently_invalidated.items() if v <= 1]
        for k in expired:
            del self._recently_invalidated[k]
        for k in list(self._recently_invalidated.keys()):
            self._recently_invalidated[k] -= 1

    def reset_session(self) -> int:
        """Flush tous les actifs en EXPIRED a session rollover.

        Returns nombre d'instances flushed.
        """
        n_active = len(self._active)
        for inst in self._active.values():
            if not inst.is_terminal():
                inst.state = STATE_EXPIRED
                inst.expiration_reason = "session_rollover"
                inst.terminal_ts = inst.last_update_ts
        flushed = self._flush_terminals()
        self._emit("SCENARIO_SESSION_FLUSH", {
            "n_active": n_active,
            "n_flushed": len(flushed),
        })
        return len(flushed)


@dataclass
class TrackerUpdate:
    """Resultat ScenarioTracker.update() pour une bar."""
    transitions: list = field(default_factory=list)  # List[StateTransition]
    terminal_instances: list = field(default_factory=list)  # List[ScenarioInstance]
    active_snapshot: list = field(default_factory=list)  # List[ScenarioInstance]


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
