"""Bot 4 v2 narrative_state — State machine multi-barres scenario lifecycle.

Module NEW Phase P3 Batch 1 (25/06/2026) — PIECE MAITRESSE conceptuelle Bot 4 v2.

Refonte fondamentale vs Bot 4 v1 :
- v1 = scenarios STATELESS (1 bar = 1 decision, anti-Wyckoff)
- v2 = scenarios STATEFUL multi-barres avec lifecycle PENDING -> ACTIVE
  -> TRIGGERED -> COMPLETED OR INVALIDATED

Justification methodologique (audit ULTRATHINK 24/06 trading-strategy-analyst) :
> "Les vrais setups se developpent sur 3-10 bars (Phase B accumulation, test,
> spring, sign of strength). Chaque bar = decision independante stateless
> est anti-Wyckoff/Dalton."

Architecture (spec section 4 P3) :

ScenarioState enum :
- PENDING      : Setup detecte bar N, attend confirmation N+1..N+window
- ACTIVE       : Conditions confirmees, entry zone valide (limit fill)
- TRIGGERED    : Entry executee, monitoring exit
- COMPLETED    : Target hit OR timeout normal
- INVALIDATED  : Stop hit OR conditions broken OR window expire

Transitions Markov-style :
    PENDING -> ACTIVE       : confirmation order-flow recue
    PENDING -> INVALIDATED  : stop_level breach OR window expire
    ACTIVE  -> TRIGGERED    : price reach entry_zone
    ACTIVE  -> INVALIDATED  : stop_level breach OR conditions cassees
    TRIGGERED -> COMPLETED  : target hit OR timeout normal
    TRIGGERED -> INVALIDATED: stop hit

Garde-fous :
- Tous Transition immutables (frozen dataclass)
- Tous ScenarioInstance changements traces dans transitions_log (audit)
- Pas de mutation state externe (encapsulation via methode evaluate)
- Fail-loud raise ValueError si bar invalide
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger(__name__)


# ============================================================
# ENUMS
# ============================================================


class ScenarioState(str, Enum):
    """Etat d'une instance scenario dans son lifecycle multi-barres."""

    PENDING = "PENDING"          # Fire bar N, attend confirmation
    ACTIVE = "ACTIVE"            # Conditions OK, entry zone valide
    TRIGGERED = "TRIGGERED"      # Entry executee, monitoring exit
    COMPLETED = "COMPLETED"      # Target hit OR timeout (succes)
    INVALIDATED = "INVALIDATED"  # Stop hit / conditions cassees / window expire

    @property
    def is_terminal(self) -> bool:
        """True si state final (plus de transition possible)."""
        return self in (ScenarioState.COMPLETED, ScenarioState.INVALIDATED)


# ============================================================
# TRANSITION (immutable trace audit)
# ============================================================


@dataclass(frozen=True)
class Transition:
    """Trace immutable d'une transition de state machine.

    Audit J+1 : reconstitue lifecycle complet d'une scenario instance.
    """

    from_state: ScenarioState
    to_state: ScenarioState
    bar_ts: str  # ISO 8601 UTC timestamp bar declenchant la transition
    bar_idx: int  # index bar depuis fire (0 = fire bar)
    reason: str  # ex "confirmation_received", "stop_hit", "timeout"
    metadata: dict = field(default_factory=dict)


# ============================================================
# SCENARIO INSTANCE (state machine d'un fire individuel)
# ============================================================


class ScenarioInstance:
    """State machine d'un scenario fire individuel.

    Pattern :
        # Bar N : scenario detecte fire
        instance = ScenarioInstance(
            signal_id="uuid",
            scenario_name="Bearish_Rejection",
            symbol="NQ",
            direction="SHORT",
            entry_price=20000.0,
            stop_loss=20020.0,
            target_1=19960.0,
        )
        # Bar N+1..N+window : evaluation transitions
        transition = instance.evaluate(bar)
        if instance.is_terminal:
            # Archive (shadow_logger), free memory
            ...

    Garde-fous :
    - bar_idx auto-incremente a chaque evaluate (anti-mutation externe)
    - state ne peut pas backtracker (PENDING ne revient pas depuis ACTIVE)
    - transitions_log immutable apres add (append-only)
    """

    def __init__(
        self,
        signal_id: str,
        scenario_name: str,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        target_1: float,
        fire_ts: str,
        confirmation_window_bars: int = 5,
        timeout_bars: int = 30,
        target_2: Optional[float] = None,
        extra: Optional[dict] = None,
    ):
        """Init scenario instance en state PENDING.

        Args:
            signal_id : UUID unique
            scenario_name : ex "Bearish_Rejection"
            symbol : NQ / ES / MGC
            direction : "LONG" / "SHORT"
            entry_price : prix entry zone (limit fill cible)
            stop_loss : prix stop (declenche INVALIDATED)
            target_1 : prix TP1 (declenche COMPLETED)
            fire_ts : timestamp bar fire (ISO 8601 UTC)
            confirmation_window_bars : N+1..N+window pour PENDING -> ACTIVE
            timeout_bars : max bars avant INVALIDATED par expire
            target_2 : optionnel TP2
            extra : metadata supplementaire (regime, score, etc.)

        Raises:
            ValueError : si arguments invalides (anti VALIDATION_MISS)
        """
        if direction not in ("LONG", "SHORT"):
            raise ValueError(
                f"direction must be 'LONG' or 'SHORT', got {direction!r}"
            )
        if confirmation_window_bars <= 0 or timeout_bars <= 0:
            raise ValueError(
                "confirmation_window_bars and timeout_bars must be > 0"
            )
        if timeout_bars < confirmation_window_bars:
            raise ValueError(
                f"timeout_bars ({timeout_bars}) must be >= "
                f"confirmation_window_bars ({confirmation_window_bars})"
            )
        # Validation LONG : stop < entry < target
        # Validation SHORT : stop > entry > target
        if direction == "LONG":
            if not (stop_loss < entry_price < target_1):
                raise ValueError(
                    f"LONG requires stop_loss < entry < target_1, "
                    f"got stop={stop_loss} entry={entry_price} target={target_1}"
                )
        else:  # SHORT
            if not (target_1 < entry_price < stop_loss):
                raise ValueError(
                    f"SHORT requires target_1 < entry < stop_loss, "
                    f"got target={target_1} entry={entry_price} stop={stop_loss}"
                )

        self.signal_id = signal_id
        self.scenario_name = scenario_name
        self.symbol = symbol.upper()
        self.direction = direction
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.target_1 = target_1
        self.target_2 = target_2
        self.fire_ts = fire_ts
        self.confirmation_window_bars = confirmation_window_bars
        self.timeout_bars = timeout_bars
        self.extra = dict(extra) if extra else {}

        # State machine internal
        self._state = ScenarioState.PENDING
        self._bar_idx = 0  # 0 = fire bar, +1 per evaluate
        self._transitions: list[Transition] = []
        self._confirmed = False  # True si conditions confirmation_validation OK

    @classmethod
    def from_fire(
        cls,
        fire: "ScenarioFire",  # forward ref evite import cycle
        confirmation_window_bars: int = 5,
        timeout_bars: int = 30,
    ) -> "ScenarioInstance":
        """Construit ScenarioInstance depuis ScenarioFire (batch 3 P3 helper).

        Pont entre scenario_registry (detect/fire) et state machine (lifecycle).
        Le decision_router consomme registry.evaluate_all(ctx) -> list[fires] puis
        [ScenarioInstance.from_fire(f) for f in fires] -> tracker.add.

        Args:
            fire : ScenarioFire produit par detector
            confirmation_window_bars : surcharge defaut 5 bars
            timeout_bars : surcharge defaut 30 bars

        Returns:
            ScenarioInstance state=PENDING, prete pour tracker.add().

        Raises:
            ValueError : si fire incoherent (delegue a __init__ validation).
        """
        extra = dict(fire.extra) if fire.extra else {}
        # Enrich extra avec metadata fire pour audit shadow_logger
        extra.setdefault("scenario_family", fire.family)
        extra.setdefault("regime", fire.regime)
        extra.setdefault("session", fire.session)
        extra.setdefault("heuristic_score", fire.heuristic_score)
        extra.setdefault("confidence", fire.confidence)
        extra.setdefault("reasons", list(fire.reasons))
        return cls(
            signal_id=fire.signal_id,
            scenario_name=fire.scenario_name,
            symbol=fire.symbol,
            direction=fire.direction,
            entry_price=fire.entry_price,
            stop_loss=fire.stop_loss,
            target_1=fire.target_1,
            target_2=fire.target_2,
            fire_ts=fire.timestamp_utc,
            confirmation_window_bars=confirmation_window_bars,
            timeout_bars=timeout_bars,
            extra=extra,
        )

    @property
    def state(self) -> ScenarioState:
        return self._state

    @property
    def bar_idx(self) -> int:
        """Nb de bars depuis fire (0 au moment de l'init)."""
        return self._bar_idx

    @property
    def is_terminal(self) -> bool:
        return self._state.is_terminal

    @property
    def transitions_log(self) -> tuple[Transition, ...]:
        """Trace immutable des transitions (audit J+1)."""
        return tuple(self._transitions)

    def confirm(self, bar: dict) -> None:
        """Signale que les conditions de confirmation sont validees.

        Doit etre appele EXTERIEUREMENT (par le caller qui evalue les
        conditions order-flow specifiques au scenario). N'est PAS deduit du bar.
        Permet PENDING -> ACTIVE lors du prochain evaluate().

        PATCH #2 review batch 1 P3 : parametre `reason` retire (jamais utilise).
        Le transitions_log capture "confirmation_received" automatiquement.
        """
        if self._state != ScenarioState.PENDING:
            return  # No-op si pas PENDING
        self._confirmed = True

    def evaluate(self, bar: dict) -> Optional[Transition]:
        """Evalue transition pour la bar courante.

        Args:
            bar : dict avec au minimum keys 'high', 'low', 'close', 'ts_event'

        Returns:
            Transition emise OR None si pas de changement state.

        Raises:
            ValueError : si bar invalide (anti VALIDATION_MISS).
        """
        if not bar or not isinstance(bar, dict):
            raise ValueError(
                f"evaluate: bar must be non-empty dict, got {type(bar).__name__}"
            )

        # Si deja terminal, no-op
        if self._state.is_terminal:
            return None

        self._bar_idx += 1
        bar_ts = str(bar.get("ts_event", "unknown"))

        # Extract OHLC safely
        # PATCH #3 review batch 1 P3 : log warning sur OHLC non-castable
        # (anti silent fallback - audit J+1 si pipeline live emet bars corrompues)
        try:
            bar_high = float(bar.get("high", 0.0))
            bar_low = float(bar.get("low", 0.0))
        except (TypeError, ValueError):
            _LOG.warning(
                "evaluate: bar OHLC non-castable signal_id=%s ts=%s",
                self.signal_id, bar.get("ts_event", "?"),
            )
            return None  # Bar invalide, no transition

        # Check stop_loss hit (priorite : SL avant tout autre)
        if self._stop_hit(bar_high, bar_low):
            return self._transition_to(
                ScenarioState.INVALIDATED, bar_ts,
                reason="stop_loss_hit",
                metadata={"bar_high": bar_high, "bar_low": bar_low},
            )

        # Check timeout (TIMEOUT > confirmation_window mais < timeout_bars)
        if self._bar_idx > self.timeout_bars:
            # Si TRIGGERED -> COMPLETED (timeout normal)
            # Si pas TRIGGERED -> INVALIDATED (jamais entered)
            if self._state == ScenarioState.TRIGGERED:
                return self._transition_to(
                    ScenarioState.COMPLETED, bar_ts,
                    reason="timeout_normal",
                    metadata={"bar_idx": self._bar_idx},
                )
            return self._transition_to(
                ScenarioState.INVALIDATED, bar_ts,
                reason="timeout_no_entry",
                metadata={"bar_idx": self._bar_idx},
            )

        # State-specific transitions avec CASCADE meme bar (PATCH #1 review
        # batch 1 P3) : si squeeze rapide intra-bar PENDING -> ACTIVE ->
        # TRIGGERED -> COMPLETED meme bar (signal premium Wyckoff Spring + SOS).
        # Anti-Wyckoff = splitter sur 2 bars = rate le spring qui enchaine.
        # Retourne la DERNIERE transition emise (caller voit l'etat final).
        last_transition: Optional[Transition] = None

        if self._state == ScenarioState.PENDING:
            trans = self._evaluate_pending(bar_ts)
            if trans is not None:
                last_transition = trans
            if self._state != ScenarioState.ACTIVE:
                return last_transition
            # Fall-through : cascade vers ACTIVE meme bar

        if self._state == ScenarioState.ACTIVE:
            trans = self._evaluate_active(bar_high, bar_low, bar_ts)
            if trans is not None:
                last_transition = trans
            if self._state != ScenarioState.TRIGGERED:
                return last_transition
            # Fall-through : cascade vers TRIGGERED meme bar

        if self._state == ScenarioState.TRIGGERED:
            trans = self._evaluate_triggered(bar_high, bar_low, bar_ts)
            if trans is not None:
                last_transition = trans

        return last_transition

    def _stop_hit(self, bar_high: float, bar_low: float) -> bool:
        """Detecte stop hit selon direction (wick-based)."""
        if self.direction == "LONG":
            return bar_low <= self.stop_loss
        return bar_high >= self.stop_loss

    def _entry_touched(self, bar_high: float, bar_low: float) -> bool:
        """Detecte entry zone touchee (limit fill)."""
        if self.direction == "LONG":
            return bar_low <= self.entry_price
        return bar_high >= self.entry_price

    def _target_hit(self, bar_high: float, bar_low: float) -> bool:
        """Detecte target_1 hit (wick-based)."""
        if self.direction == "LONG":
            return bar_high >= self.target_1
        return bar_low <= self.target_1

    def _evaluate_pending(self, bar_ts: str) -> Optional[Transition]:
        """PENDING -> ACTIVE (confirmation) OR INVALIDATED (window expire)."""
        if self._confirmed:
            return self._transition_to(
                ScenarioState.ACTIVE, bar_ts,
                reason="confirmation_received",
            )
        if self._bar_idx >= self.confirmation_window_bars:
            return self._transition_to(
                ScenarioState.INVALIDATED, bar_ts,
                reason="confirmation_window_expired",
                metadata={"window": self.confirmation_window_bars},
            )
        return None

    def _evaluate_active(
        self, bar_high: float, bar_low: float, bar_ts: str,
    ) -> Optional[Transition]:
        """ACTIVE -> TRIGGERED (entry touched) OR stay ACTIVE."""
        if self._entry_touched(bar_high, bar_low):
            return self._transition_to(
                ScenarioState.TRIGGERED, bar_ts,
                reason="entry_zone_touched",
                metadata={
                    "entry_price": self.entry_price,
                    "bar_high": bar_high, "bar_low": bar_low,
                },
            )
        return None

    def _evaluate_triggered(
        self, bar_high: float, bar_low: float, bar_ts: str,
    ) -> Optional[Transition]:
        """TRIGGERED -> COMPLETED (target hit) OR stay TRIGGERED."""
        if self._target_hit(bar_high, bar_low):
            return self._transition_to(
                ScenarioState.COMPLETED, bar_ts,
                reason="target_1_hit",
                metadata={
                    "target_1": self.target_1,
                    "bar_high": bar_high, "bar_low": bar_low,
                },
            )
        return None

    def _transition_to(
        self,
        to_state: ScenarioState,
        bar_ts: str,
        reason: str,
        metadata: Optional[dict] = None,
    ) -> Transition:
        """Emet transition + met a jour state (encapsulation).

        R3 review batch 3 P3 : injecte signal_id dans metadata pour permettre
        au decision_router._dispatch_bracket de matcher l'instance source
        meme quand anti-pyramiding sera leve (>1 instance par symbol futur).
        """
        meta = dict(metadata) if metadata else {}
        meta.setdefault("signal_id", self.signal_id)
        transition = Transition(
            from_state=self._state,
            to_state=to_state,
            bar_ts=bar_ts,
            bar_idx=self._bar_idx,
            reason=reason,
            metadata=meta,
        )
        self._transitions.append(transition)
        self._state = to_state
        return transition

    def to_dict(self) -> dict[str, Any]:
        """Serialize state instance pour persistance / shadow_logger."""
        return {
            "signal_id": self.signal_id,
            "scenario_name": self.scenario_name,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "fire_ts": self.fire_ts,
            "state": self._state.value,
            "bar_idx": self._bar_idx,
            "confirmed": self._confirmed,
            "n_transitions": len(self._transitions),
            "extra": self.extra,
        }


# ============================================================
# SCENARIO TRACKER (multi-instances par symbole)
# ============================================================


class ScenarioTracker:
    """Gestion multiple ScenarioInstance lifecycle par symbole.

    Pattern :
        tracker = ScenarioTracker(symbol="NQ")
        # Bar N : scenario A fire
        tracker.add(instance_a)
        # Bar N+1..N+30 : update tous les pending/active/triggered
        transitions = tracker.update_all(bar)
        # Purge terminal vers archive
        terminal = tracker.pop_terminal()
        for inst in terminal:
            shadow_logger.log_outcome(inst)

    Thread-safety : NON. Single-thread main loop bot4_v2.
    """

    def __init__(self, symbol: str):
        self.symbol = symbol.upper()
        self._instances: list[ScenarioInstance] = []

    @property
    def n_instances(self) -> int:
        """Nb instances trackees (PENDING + ACTIVE + TRIGGERED)."""
        return len(self._instances)

    @property
    def n_active(self) -> int:
        """Nb instances non-terminales."""
        return sum(1 for inst in self._instances if not inst.is_terminal)

    def add(self, instance: ScenarioInstance) -> None:
        """Ajoute une instance fire au tracker.

        Garde-fou : refuse instance pour autre symbol.
        """
        if instance.symbol != self.symbol:
            raise ValueError(
                f"Instance symbol {instance.symbol!r} != tracker symbol "
                f"{self.symbol!r}"
            )
        self._instances.append(instance)

    def update_all(self, bar: dict) -> list[Transition]:
        """Evalue toutes les instances non-terminales sur la bar courante.

        Returns:
            Liste des transitions emises cette bar (peut etre vide).
        """
        transitions = []
        for instance in self._instances:
            if instance.is_terminal:
                continue
            t = instance.evaluate(bar)
            if t is not None:
                transitions.append(t)
        return transitions

    def active_instances(self) -> list[ScenarioInstance]:
        """Snapshot instances non-terminales."""
        return [inst for inst in self._instances if not inst.is_terminal]

    def terminal_instances(self) -> list[ScenarioInstance]:
        """Snapshot instances COMPLETED ou INVALIDATED."""
        return [inst for inst in self._instances if inst.is_terminal]

    def pop_terminal(self) -> list[ScenarioInstance]:
        """Retourne et retire les instances terminales du tracker.

        Pattern : archive vers shadow_logger pour calibration P6.
        """
        terminal = [inst for inst in self._instances if inst.is_terminal]
        self._instances = [
            inst for inst in self._instances if not inst.is_terminal
        ]
        return terminal

    def find_by_signal_id(self, signal_id: str) -> Optional[ScenarioInstance]:
        """Cherche instance par signal_id (None si absent)."""
        for inst in self._instances:
            if inst.signal_id == signal_id:
                return inst
        return None
