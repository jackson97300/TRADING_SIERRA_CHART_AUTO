"""Bot 4 v2 decision_router — Orchestrateur per-bar fires + state machine + execution.

Module NEW Phase P3 Batch 3 (25/06/2026) — Voie finale chaine decision Bot 4 v2.

Architecture (spec section 3 P3) :

```
JSONL bar -> regime_source -> narrative_engine -> ScenarioContext
                                                    |
                                                    v
                            DecisionRouter.route_bar(ctx)
                              |
                              +--> 1. ScenarioTracker per symbol :
                              |     a) update_all(bar) -> transitions
                              |     b) TRIGGERED transitions -> dtc_adapter.send_bracket
                              |     c) pop_terminal -> shadow_logger (optional)
                              |
                              +--> 2. Si tracker.n_active==0 :
                                    a) registry.evaluate_all(ctx) -> fires
                                    b) Resolution collisions LONG+SHORT
                                    c) Top-N par confidence
                                    d) ScenarioInstance.from_fire -> tracker.add
```

SRP strict (responsabilites borneees) :
- DOIT : consommer fires, appliquer politique tier+collision, emettre BracketRequest
- NE DOIT PAS : computing regime (regime_source), calibration P(win) (registry),
  persistance shadow (shadow_logger via injection optionnelle)

Policy collision LONG+SHORT meme bar (Jackson decision auto-mode 25/06) :
- Gap confidence > collision_min_gap_pct (defaut 20%) -> top confidence wins
- Gap <= collision_min_gap_pct -> bloque les 2 (Douglas anti-confusion)

Policy pyramiding (Mark Douglas "consistency beats intensity") :
- Si tracker.n_active > 0 (PENDING/ACTIVE/TRIGGERED) sur un symbole, AUCUN nouveau
  fire evalue pour ce symbole jusqu'a exit complete.

Policy max concurrent trades (Bot 1+2+3 V_FINAL):
- max_concurrent_trades cross-symbol (defaut 3) - apres ca, fires skipped meme
  si symbole libre.

Garde-fous :
- Frozen RouterSettings (anti mutation runtime)
- Fail-soft sur dtc_adapter.send_bracket exception (log CRITIQUE, pas crash bot)
- naked=True dans BracketResult -> log CRITIQUE (heritage Bot 3 BN V4 R1)
- Logs traceability obligatoire (incident-protocol.md regle souveraine Jackson 01/05)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from bot4_v2.decision.narrative_state import (
    ScenarioInstance,
    ScenarioState,
    ScenarioTracker,
    Transition,
)
from bot4_v2.decision.scenario_registry import (
    ScenarioContext,
    ScenarioFire,
    ScenarioRegistry,
)
from bot4_v2.execution.dtc_adapter import (
    BracketRequest,
    BracketResult,
    DTCAdapter,
    OrderSide,
)
from bot4_v2.observability.telemetry import emit_safe, get_logger

_LOG = get_logger(__name__)


# ============================================================
# SETTINGS (frozen)
# ============================================================


@dataclass(frozen=True)
class RouterSettings:
    """Settings DecisionRouter. Frozen anti-mutation runtime.

    Attributs :
        max_concurrent_trades : cap nb total trades actifs cross-symbol
        collision_min_gap_pct : seuil gap confidence resolve collision LONG/SHORT
                                (0.20 = 20%). Si gap <= seuil, bloque les 2.
        confirmation_window_bars : N+1..N+window PENDING -> ACTIVE
        timeout_bars : max bars avant INVALIDATED expire (>= confirmation_window)
        quantity_per_trade : nb contrats par bracket (defaut 1 micro)
        trade_account : compte Sim DTC (None = injecte depuis dtc_adapter)
        emit_tp : True -> bracket TP+SL classique (DTC adapter P3+ requis).
                  False -> flux SL-only (heritage Bot 3 BN V4 INCIDENT_LOG #67,
                  defaut P3 batch 3 car dtc_adapter P2 ne supporte que SL-only).
    """

    max_concurrent_trades: int = 3
    collision_min_gap_pct: float = 0.20
    confirmation_window_bars: int = 5
    timeout_bars: int = 30
    quantity_per_trade: int = 1
    trade_account: Optional[str] = None
    emit_tp: bool = False

    def __post_init__(self) -> None:
        if self.max_concurrent_trades <= 0:
            raise ValueError(
                f"max_concurrent_trades must be > 0, got {self.max_concurrent_trades}"
            )
        if not (0.0 <= self.collision_min_gap_pct <= 1.0):
            raise ValueError(
                f"collision_min_gap_pct must be in [0, 1], "
                f"got {self.collision_min_gap_pct}"
            )
        if self.confirmation_window_bars <= 0 or self.timeout_bars <= 0:
            raise ValueError(
                "confirmation_window_bars and timeout_bars must be > 0"
            )
        if self.timeout_bars < self.confirmation_window_bars:
            raise ValueError(
                f"timeout_bars ({self.timeout_bars}) must be >= "
                f"confirmation_window_bars ({self.confirmation_window_bars})"
            )
        if self.quantity_per_trade <= 0:
            raise ValueError(
                f"quantity_per_trade must be > 0, got {self.quantity_per_trade}"
            )


# ============================================================
# TICK RESULT (frozen, audit J+1 friendly)
# ============================================================


@dataclass(frozen=True)
class DispatchedBracket:
    """Metadata bracket dispatched OK (P5.1 extension).

    Caller bot_main_v2 doit appeler `reconciler.register_bracket(**fields)` pour
    tracker stale + naked detection downstream. Si `naked=True`, la position est
    aussi exposee dans `naked_brackets_pending` pour force-close immediat.

    Frozen : audit J+1 + tests friendly.
    """

    signal_id: str
    parent_cid: str
    sl_cid: str          # vide si naked=True
    symbol: str
    direction: str
    quantity: int
    fill_price: float
    scenario_name: str
    naked: bool = False


@dataclass(frozen=True)
class ClosedSignal:
    """Metadata signal terminal archived (P5.1 extension).

    Caller bot_main_v2 doit appeler `reconciler.mark_closed(parent_cid, reason)`
    SI `parent_cid` est non-vide (sinon = scenario archived sans dispatch
    prealable - ex INVALIDATED en PENDING avant ACTIVE/TRIGGERED).
    """

    signal_id: str
    parent_cid: str  # vide si scenario archived sans dispatch (PENDING->INVALIDATED)
    symbol: str
    scenario_name: str
    final_state: str  # "COMPLETED" | "INVALIDATED"
    reason: str       # raison derniere transition


@dataclass(frozen=True)
class RouterTickResult:
    """Resultat 1 cycle route_bar. Audit J+1 + tests friendly.

    naked_brackets_pending : R2 review batch 3 P3 - liste parent_cid des
    brackets fillis SANS SL (position nue). Caller (Position Reconciler P4 ou
    bot_main) DOIT call dtc.send_close pour chaque cid -> evite position nue
    infinie.

    dispatched_brackets (P5.1) : metadata complete des brackets dispatched
    cette tick (success OR naked). Caller -> reconciler.register_bracket().

    closed_signals (P5.1) : metadata signals archives cette tick. Caller ->
    reconciler.mark_closed() si parent_cid non-vide.
    """

    symbol: str
    fires_evaluated: int = 0           # nb fires retournes par registry
    fires_selected: int = 0            # nb fires apres collision + cap
    instances_added: int = 0           # nb tracker.add() call
    transitions_emitted: int = 0       # nb transitions de tracker.update_all
    brackets_dispatched: int = 0       # nb BracketRequest envoyes
    brackets_naked: int = 0            # nb naked=True (CRITIQUE)
    terminals_archived: int = 0        # nb pop_terminal
    skip_reason: str = ""              # ex "tracker_active", "max_concurrent_cap"
    naked_brackets_pending: tuple[str, ...] = field(default_factory=tuple)
    dispatched_brackets: tuple[DispatchedBracket, ...] = field(default_factory=tuple)
    closed_signals: tuple[ClosedSignal, ...] = field(default_factory=tuple)


# ============================================================
# DECISION ROUTER
# ============================================================


class DecisionRouter:
    """Orchestrateur per-bar fires registry + state machine + execution.

    Pattern :
        router = DecisionRouter(registry, dtc_adapter, settings)
        # Per bar pour chaque symbole :
        result = router.route_bar(ctx)
        # result : audit metrics
    """

    def __init__(
        self,
        registry: ScenarioRegistry,
        dtc_adapter: DTCAdapter,
        settings: Optional[RouterSettings] = None,
    ):
        """Init router.

        Args:
            registry : ScenarioRegistry pre-configured (detectors registered)
            dtc_adapter : DTCAdapter pour emission ordres bracket
            settings : RouterSettings (defaut anti pyramiding + Douglas collision)
        """
        if registry is None:
            raise ValueError("registry is required")
        if dtc_adapter is None:
            raise ValueError("dtc_adapter is required")

        self._registry = registry
        self._dtc = dtc_adapter
        self._settings = settings or RouterSettings()
        self._trackers: dict[str, ScenarioTracker] = {}
        # P5.1 : map signal_id -> DispatchedBracket pour matcher archives
        # (caller bot_main lookup parent_cid lors mark_closed).
        # Cle ajoutee on dispatch OK, retiree on close (pop_terminal flow).
        # R1 ULTRATHINK P5 review : cap defensif 5000 entries + FIFO eviction
        # (anti-leak si instance TRIGGERED stuck forever sans transition terminale).
        self._signal_to_dispatch: dict[str, DispatchedBracket] = {}
        self._dispatch_map_cap = 5000

    @property
    def settings(self) -> RouterSettings:
        return self._settings

    @property
    def trackers(self) -> dict[str, ScenarioTracker]:
        return dict(self._trackers)  # copy defensive

    def n_total_active(self) -> int:
        """Nb instances actives cross-symbol (cap max_concurrent_trades)."""
        return sum(t.n_active for t in self._trackers.values())

    # ------------------------------------------------------------
    # MAIN LOOP per bar
    # ------------------------------------------------------------

    def route_bar(self, ctx: ScenarioContext) -> RouterTickResult:
        """Boucle principale per-bar.

        Args:
            ctx : ScenarioContext (bar + regime + narrative + menthorq)

        Returns:
            RouterTickResult audit metrics.
        """
        symbol = ctx.symbol
        tracker = self._get_or_create_tracker(symbol)

        # 1. Update existing instances (multi-bar lifecycle)
        transitions = tracker.update_all(ctx.bar)

        # 2. Dispatch BracketRequest sur transitions TRIGGERED
        n_brackets = 0
        n_naked = 0
        naked_cids: list[str] = []  # R2 review : caller doit force-close
        dispatched: list[DispatchedBracket] = []  # P5.1 metadata complete
        for t in transitions:
            if t.to_state == ScenarioState.TRIGGERED:
                bracket_meta = self._dispatch_bracket(symbol, t, tracker)
                if bracket_meta is not None:
                    dispatched.append(bracket_meta)
                    n_brackets += 1
                    if bracket_meta.naked:
                        n_naked += 1
                        naked_cids.append(bracket_meta.parent_cid)
                    # Memorize signal_id -> dispatch pour archive lookup
                    # R1 ULTRATHINK : eviction FIFO si cap atteint (anti leak)
                    if len(self._signal_to_dispatch) >= self._dispatch_map_cap:
                        evicted_key = next(iter(self._signal_to_dispatch))
                        del self._signal_to_dispatch[evicted_key]
                        emit_safe(
                            _LOG, "BOT4V2_ROUTER_DISPATCH_MAP_OVERFLOW",
                            cap=self._dispatch_map_cap, evicted=evicted_key,
                        )
                    self._signal_to_dispatch[bracket_meta.signal_id] = bracket_meta

        # 3. Archive terminals + construire closed_signals (P5.1)
        terminals = tracker.pop_terminal()
        closed_signals = self._build_closed_signals(terminals)
        n_terminals = len(terminals)
        if n_terminals > 0:
            emit_safe(
                _LOG, "BOT4V2_ROUTER_ARCHIVE_TERMINALS",
                sym=symbol, n=n_terminals,
            )

        # 4. Evaluate fires UNIQUEMENT si pas d'active sur ce symbole
        # (anti-pyramiding Douglas "consistency beats intensity")
        if tracker.n_active > 0:
            emit_safe(
                _LOG, "BOT4V2_ROUTER_SKIP_PYRAMIDING",
                sym=symbol, n_active=tracker.n_active,
            )
            return RouterTickResult(
                symbol=symbol,
                transitions_emitted=len(transitions),
                brackets_dispatched=n_brackets,
                brackets_naked=n_naked,
                terminals_archived=n_terminals,
                skip_reason="tracker_active",
                naked_brackets_pending=tuple(naked_cids),
                dispatched_brackets=tuple(dispatched),
                closed_signals=tuple(closed_signals),
            )

        # 4b. Cap max_concurrent_trades cross-symbol
        if self.n_total_active() >= self._settings.max_concurrent_trades:
            emit_safe(
                _LOG, "BOT4V2_ROUTER_SKIP_MAX_CONCURRENT",
                sym=symbol, cap=self._settings.max_concurrent_trades,
            )
            return RouterTickResult(
                symbol=symbol,
                transitions_emitted=len(transitions),
                brackets_dispatched=n_brackets,
                brackets_naked=n_naked,
                terminals_archived=n_terminals,
                skip_reason="max_concurrent_cap",
                naked_brackets_pending=tuple(naked_cids),
                dispatched_brackets=tuple(dispatched),
                closed_signals=tuple(closed_signals),
            )

        # 5. Evaluate registry
        fires = self._registry.evaluate_all(ctx)
        n_fires_eval = len(fires)
        if not fires:
            return RouterTickResult(
                symbol=symbol,
                transitions_emitted=len(transitions),
                brackets_dispatched=n_brackets,
                brackets_naked=n_naked,
                terminals_archived=n_terminals,
                naked_brackets_pending=tuple(naked_cids),
                dispatched_brackets=tuple(dispatched),
                closed_signals=tuple(closed_signals),
            )

        # 6. Resolve collisions + top-N
        selected = self._select_fires(fires, symbol)
        n_selected = len(selected)

        # 7. Convert fires -> ScenarioInstance -> tracker.add
        n_added = 0
        for fire in selected:
            try:
                instance = ScenarioInstance.from_fire(
                    fire,
                    confirmation_window_bars=self._settings.confirmation_window_bars,
                    timeout_bars=self._settings.timeout_bars,
                )
            except ValueError as exc:
                emit_safe(
                    _LOG, "BOT4V2_ROUTER_FIRE_INVALID",
                    sym=symbol, scenario=fire.scenario_name,
                    reason=str(exc),
                )
                continue
            tracker.add(instance)
            n_added += 1
            emit_safe(
                _LOG, "BOT4V2_ROUTER_FIRE",
                sym=symbol, scenario=fire.scenario_name,
                direction=fire.direction, confidence=fire.confidence,
                score=fire.heuristic_score,
                regime=fire.regime, session=fire.session,
            )

        return RouterTickResult(
            symbol=symbol,
            fires_evaluated=n_fires_eval,
            fires_selected=n_selected,
            instances_added=n_added,
            transitions_emitted=len(transitions),
            brackets_dispatched=n_brackets,
            brackets_naked=n_naked,
            terminals_archived=n_terminals,
            naked_brackets_pending=tuple(naked_cids),
            dispatched_brackets=tuple(dispatched),
            closed_signals=tuple(closed_signals),
        )

    # ------------------------------------------------------------
    # PRIVATE HELPERS
    # ------------------------------------------------------------

    def _get_or_create_tracker(self, symbol: str) -> ScenarioTracker:
        """Lazy create tracker per symbol (1 par instrument)."""
        sym = symbol.upper()
        if sym not in self._trackers:
            self._trackers[sym] = ScenarioTracker(sym)
        return self._trackers[sym]

    def _select_fires(
        self, fires: list[ScenarioFire], symbol: str = "",
    ) -> list[ScenarioFire]:
        """Resolve collisions LONG+SHORT + top-N par confidence.

        Policy collision :
        - Si tous fires meme direction -> top 1 par confidence (anti pyramiding)
        - Si mix LONG+SHORT :
            * Gap top_long vs top_short > collision_min_gap_pct -> top wins
            * Gap <= collision_min_gap_pct -> bloque les 2 (Douglas)
        """
        if not fires:
            return []

        # Trier par confidence desc
        sorted_fires = sorted(fires, key=lambda f: f.confidence, reverse=True)
        longs = [f for f in sorted_fires if f.direction == "LONG"]
        shorts = [f for f in sorted_fires if f.direction == "SHORT"]

        # Cas 1 : direction unique -> top 1 (anti pyramiding meme symbole)
        if not longs:
            return [shorts[0]]
        if not shorts:
            return [longs[0]]

        # Cas 2 : collision LONG vs SHORT
        top_long = longs[0]
        top_short = shorts[0]
        gap = abs(top_long.confidence - top_short.confidence)
        sym = symbol or top_long.symbol

        if gap > self._settings.collision_min_gap_pct:
            # Top confidence wins (porte de sortie evidente)
            winner = top_long if top_long.confidence > top_short.confidence else top_short
            emit_safe(
                _LOG, "BOT4V2_ROUTER_COLLISION_RESOLVED",
                sym=sym, gap=gap,
                min_gap=self._settings.collision_min_gap_pct,
                direction=winner.direction,
            )
            return [winner]

        # Gap insuffisant -> bloque les 2 (Douglas anti confusion)
        emit_safe(
            _LOG, "BOT4V2_ROUTER_COLLISION_BLOCKED",
            sym=sym, gap=gap,
            min_gap=self._settings.collision_min_gap_pct,
            long_conf=top_long.confidence, short_conf=top_short.confidence,
        )
        return []

    def _dispatch_bracket(
        self,
        symbol: str,
        transition: Transition,
        tracker: ScenarioTracker,
    ) -> Optional[DispatchedBracket]:
        """Dispatch BracketRequest via dtc_adapter sur transition TRIGGERED.

        P5.1 : retourne metadata complete pour bot_main_v2 hook reconciler.

        Returns:
            DispatchedBracket si dispatch parti (success OR naked).
            None si fail business (rejet broker / exception / no match).
        """
        # R3 review : signal_id propagation via metadata
        signal_id = transition.metadata.get("signal_id", "")
        instance = tracker.find_by_signal_id(signal_id) if signal_id else None
        if instance is None:
            # Fallback anti-pyramiding : 1 instance max TRIGGERED par symbol
            # R2 ULTRATHINK P5 review : emit ALERTE explicite (anti silent fallback).
            # Si > 1 instance TRIGGERED (anti-pyramiding leve futur), `actives[-1]`
            # est arbitraire -> latent bug. Le log permet de detecter J+1.
            actives = [
                i for i in tracker.active_instances()
                if i.state == ScenarioState.TRIGGERED
            ]
            if not actives:
                emit_safe(
                    _LOG, "BOT4V2_ROUTER_DISPATCH_NO_MATCH",
                    sym=symbol, signal_id=signal_id or "(empty)",
                )
                return None
            instance = actives[-1]
            emit_safe(
                _LOG, "BOT4V2_ROUTER_DISPATCH_FALLBACK",
                sym=symbol, signal_id=signal_id or "(empty)",
            )

        side = OrderSide.BUY if instance.direction == "LONG" else OrderSide.SELL
        request = BracketRequest(
            symbol=symbol,
            side=side,
            quantity=self._settings.quantity_per_trade,
            sl_price=instance.stop_loss,
            tp_price=instance.target_1 if self._settings.emit_tp else None,
            trade_account=self._settings.trade_account,
            signal_ref_price=instance.entry_price,
        )

        try:
            result: BracketResult = self._dtc.send_bracket(request)
        except Exception as exc:  # noqa: BLE001
            emit_safe(
                _LOG, "BOT4V2_ROUTER_BRACKET_EXC",
                sym=symbol, scenario=instance.scenario_name,
                exc_type=type(exc).__name__,
            )
            return None

        # IMPORTANT : naked=True a success=False (cf dtc_adapter contract).
        # Check naked AVANT success pour compter le bracket "parti" + CRITIQUE.
        if result.naked:
            emit_safe(
                _LOG, "BOT4V2_ROUTER_BRACKET_NAKED",
                sym=symbol, scenario=instance.scenario_name,
                parent_cid=result.parent_cid, fill=result.fill_price,
            )
            return DispatchedBracket(
                signal_id=instance.signal_id,
                parent_cid=result.parent_cid,
                sl_cid="",
                symbol=symbol,
                direction=instance.direction,
                quantity=self._settings.quantity_per_trade,
                fill_price=result.fill_price,
                scenario_name=instance.scenario_name,
                naked=True,
            )

        if not result.success:
            emit_safe(
                _LOG, "BOT4V2_ROUTER_BRACKET_FAIL",
                sym=symbol, scenario=instance.scenario_name,
                error=result.error_msg,
            )
            return None

        emit_safe(
            _LOG, "BOT4V2_ROUTER_BRACKET_OK",
            sym=symbol, scenario=instance.scenario_name,
            direction=instance.direction,
            fill=result.fill_price,
            parent_cid=result.parent_cid,
            sl_cid=result.sl_cid,
        )
        return DispatchedBracket(
            signal_id=instance.signal_id,
            parent_cid=result.parent_cid,
            sl_cid=result.sl_cid,
            symbol=symbol,
            direction=instance.direction,
            quantity=self._settings.quantity_per_trade,
            fill_price=result.fill_price,
            scenario_name=instance.scenario_name,
            naked=False,
        )

    def _build_closed_signals(
        self, terminals: list[ScenarioInstance],
    ) -> list[ClosedSignal]:
        """Construit ClosedSignal metadata depuis instances terminales (P5.1).

        Pour chaque instance archive :
        - Recupere parent_cid depuis _signal_to_dispatch (vide si jamais
          dispatched - cas PENDING->INVALIDATED stop loss avant ACTIVE)
        - Recupere reason depuis transitions_log[-1] (derniere transition)
        - Retire l'entree _signal_to_dispatch (libere memoire post-archive)
        """
        closed: list[ClosedSignal] = []
        for inst in terminals:
            dispatch = self._signal_to_dispatch.pop(inst.signal_id, None)
            parent_cid = dispatch.parent_cid if dispatch else ""
            # Derniere transition reason (None si pas de transition - cas rare)
            log = inst.transitions_log
            reason = log[-1].reason if log else "unknown"
            closed.append(ClosedSignal(
                signal_id=inst.signal_id,
                parent_cid=parent_cid,
                symbol=inst.symbol,
                scenario_name=inst.scenario_name,
                final_state=inst.state.value,
                reason=reason,
            ))
        return closed
