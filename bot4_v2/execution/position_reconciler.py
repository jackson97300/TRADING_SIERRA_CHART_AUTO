"""Bot 4 v2 position_reconciler — Force-close NAKED + stale detection + heartbeat.

Module NEW Phase P4 (25/06/2026) — Couche reconciliation positions.

Responsabilites strictes (SRP) :
1. **NAKED force-close PRIORITY 1** : consommer `RouterTickResult.naked_brackets_pending`
   du router (R2 review P3 batch 3) et appeler `dtc.send_close(...)` immediatement.
   Heritage Bot 3 BN V4 R1 INCIDENT_LOG #67 : position nue infinie = capital perdu.

2. **State tracking RAM** : enregistrement bracket opened (`register_bracket`) et
   closed (`mark_closed`) par caller (bot_main loop). Pas de couplage tracker
   state machine (les responsabilites sont differentes : tracker = setup
   lifecycle, reconciler = position broker-side).

3. **Stale detection** : positions ouvertes depuis > stale_threshold_sec sans
   `mark_closed` -> heartbeat force-close (anti position fantome bot crash).

4. **Heartbeat tick** : intervalle 30s defaut. Verifie n_positions tracked.

EXCLU du scope P4 (backlog P6) :
- ORPHAN broker detection (broker a position non trackee) : necessite extension
  IDTCBackend.get_open_positions() qui modifie Protocol gelé P2. Reporte P6.
- GHOST tracker detection (tracker TRIGGERED sans position broker) : meme raison.

Anti-patterns interdits :
- Pas de couplage direct au DecisionRouter (independance testabilite)
- Pas de timer/thread interne (caller gere heartbeat schedule)
- Pas de modification IDTCBackend Protocol (P2 gele)
- Tous logs via emit_safe (regle souveraine TRACABILITE)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from bot4_v2.execution.dtc_adapter import (
    DTCAdapter,
    OrderSide,
)
from bot4_v2.observability.telemetry import emit_safe, get_logger

_LOG = get_logger(__name__)


# ============================================================
# DATACLASSES (frozen)
# ============================================================


@dataclass(frozen=True)
class BotPositionState:
    """Etat d'une position trackee par le reconciler.

    Frozen : immuabilite + audit J+1 friendly. Cle = parent_cid (unique broker).
    """

    symbol: str
    parent_cid: str
    sl_cid: str          # vide si naked
    direction: str       # "LONG" / "SHORT"
    quantity: int
    fill_price: float
    opened_ts: float     # epoch UTC
    naked: bool = False  # True si pas de SL pose

    @property
    def is_naked(self) -> bool:
        return self.naked or not self.sl_cid


@dataclass(frozen=True)
class ReconcilerSettings:
    """Settings PositionReconciler. Frozen anti-mutation runtime."""

    heartbeat_interval_sec: float = 30.0  # intervalle minimum entre tick()
    stale_threshold_sec: float = 7200.0   # 2h sans mark_closed -> stale
    force_close_naked: bool = True         # PRIORITY 1 : auto-close naked
    max_close_retries: int = 3             # nb tentatives send_close avant abandon
    close_retry_delay_sec: float = 0.5     # delai entre tentatives

    def __post_init__(self) -> None:
        if self.heartbeat_interval_sec < 0:
            raise ValueError("heartbeat_interval_sec must be >= 0")
        if self.stale_threshold_sec <= 0:
            raise ValueError("stale_threshold_sec must be > 0")
        if self.max_close_retries < 0:
            raise ValueError("max_close_retries must be >= 0")
        if self.close_retry_delay_sec < 0:
            raise ValueError("close_retry_delay_sec must be >= 0")


@dataclass(frozen=True)
class ReconcilerTickResult:
    """Resultat 1 heartbeat tick(). Frozen + audit J+1 friendly."""

    n_positions_tracked: int = 0
    n_stale_detected: int = 0
    n_stale_force_closed: int = 0
    n_naked_force_closed: int = 0  # cumul cross-tick (via reconcile_naked separe)
    skipped_heartbeat: bool = False
    parent_cids_force_closed: tuple[str, ...] = field(default_factory=tuple)


# ============================================================
# RECONCILER (state machine independante)
# ============================================================


class PositionReconciler:
    """Couche reconciliation positions opened par le router.

    Pattern usage :
        reconciler = PositionReconciler(dtc_adapter, settings)
        # Per route_bar cycle :
        tick_result = router.route_bar(ctx)
        if tick_result.naked_brackets_pending:
            reconciler.reconcile_naked(
                naked_parent_cids=tick_result.naked_brackets_pending,
                symbol=tick_result.symbol,
            )
        # Register brackets dispatched OK pour state tracking
        # (caller via bot_main hooks)
        reconciler.register_bracket(symbol="NQ", parent_cid="X", ...)
        # Quand exit confirme :
        reconciler.mark_closed(parent_cid="X", reason="target_hit")
        # Heartbeat 30s :
        result = reconciler.tick()

    Thread-safety : NON (single-thread main loop bot4_v2).
    """

    def __init__(
        self,
        dtc_adapter: DTCAdapter,
        settings: Optional[ReconcilerSettings] = None,
    ):
        """Init reconciler.

        Args:
            dtc_adapter : DTCAdapter pour send_close emissions
            settings : ReconcilerSettings (defauts 30s heartbeat / 2h stale)
        """
        if dtc_adapter is None:
            raise ValueError("dtc_adapter is required")
        self._dtc = dtc_adapter
        self._settings = settings or ReconcilerSettings()
        self._positions: dict[str, BotPositionState] = {}  # parent_cid -> state
        self._last_heartbeat_ts: float = 0.0
        self._cumul_naked_closed: int = 0

    @property
    def settings(self) -> ReconcilerSettings:
        return self._settings

    @property
    def n_positions(self) -> int:
        return len(self._positions)

    def positions(self) -> dict[str, BotPositionState]:
        """Snapshot defensive copy positions trackees."""
        return dict(self._positions)

    # ------------------------------------------------------------
    # State tracking : register / mark_closed
    # ------------------------------------------------------------

    def register_bracket(
        self,
        symbol: str,
        parent_cid: str,
        sl_cid: str,
        direction: str,
        quantity: int,
        fill_price: float,
        naked: bool = False,
        opened_ts: Optional[float] = None,
    ) -> bool:
        """Enregistre un bracket nouvellement opened pour tracking stale.

        Args:
            symbol, parent_cid, sl_cid, direction, quantity, fill_price : metadata
            naked : True si fill OK mais SL non pose (caller verifie cf router)
            opened_ts : epoch UTC ouverture (defaut time.time())

        Returns:
            True si registered, False si parent_cid deja present (duplicate).
        """
        if not parent_cid:
            raise ValueError("parent_cid required for register_bracket")
        if direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction must be LONG/SHORT, got {direction!r}")
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")

        if parent_cid in self._positions:
            emit_safe(
                _LOG, "BOT4V2_RECONCILER_REGISTER_DUPLICATE",
                sym=symbol, parent_cid=parent_cid,
            )
            return False

        state = BotPositionState(
            symbol=symbol.upper(),
            parent_cid=parent_cid,
            sl_cid=sl_cid,
            direction=direction,
            quantity=quantity,
            fill_price=fill_price,
            opened_ts=opened_ts if opened_ts is not None else time.time(),
            naked=naked,
        )
        self._positions[parent_cid] = state
        emit_safe(
            _LOG, "BOT4V2_RECONCILER_REGISTER_BRACKET",
            sym=symbol, parent_cid=parent_cid,
            direction=direction, fill=fill_price,
        )
        return True

    def mark_closed(self, parent_cid: str, reason: str = "exit_confirmed") -> bool:
        """Retire une position trackee (exit confirme par caller).

        Args:
            parent_cid : ID broker de la position fermee
            reason : motif (target_hit / stop_hit / timeout / manual / naked_auto / stale_auto)

        Returns:
            True si retiree, False si parent_cid absent.
        """
        if parent_cid not in self._positions:
            return False
        state = self._positions.pop(parent_cid)
        emit_safe(
            _LOG, "BOT4V2_RECONCILER_MARK_CLOSED",
            sym=state.symbol, parent_cid=parent_cid, reason=reason,
        )
        return True

    # ------------------------------------------------------------
    # NAKED force-close (PRIORITY 1)
    # ------------------------------------------------------------

    def reconcile_naked(
        self,
        naked_parent_cids: tuple[str, ...],
        symbol: str,
    ) -> int:
        """Force-close positions naked detectees par le router.

        Consume RouterTickResult.naked_brackets_pending pour le symbol.
        Heritage Bot 3 BN V4 R1 (INCIDENT_LOG #67) : SL non pose = risque
        capital infini si bot crash. Force-close immediat via send_close.

        Args:
            naked_parent_cids : tuple parent_cid des brackets fillis sans SL
            symbol : symbol du router tick (toutes les positions du tuple)

        Returns:
            Nb positions effectivement closed.
        """
        if not self._settings.force_close_naked:
            return 0
        n_closed = 0
        for parent_cid in naked_parent_cids:
            ok = self._force_close_naked(symbol, parent_cid)
            if ok:
                n_closed += 1
        self._cumul_naked_closed += n_closed
        return n_closed

    def _force_close_naked(self, symbol: str, parent_cid: str) -> bool:
        """NAKED force-close. Retourne True si OK."""
        state = self._positions.get(parent_cid)
        if state is None:
            # Caller a oublie register_bracket avant reconcile_naked -> skip
            # (anti close direction wrong sans info quantity/direction)
            emit_safe(
                _LOG, "BOT4V2_RECONCILER_NAKED_SKIP_UNREGISTERED",
                sym=symbol, parent_cid=parent_cid,
            )
            return False

        emit_safe(
            _LOG, "BOT4V2_RECONCILER_NAKED_FORCE_CLOSE",
            sym=symbol, parent_cid=parent_cid,
            direction=state.direction, qty=state.quantity,
        )
        return self._send_close_with_retries(
            state,
            ok_code="BOT4V2_RECONCILER_NAKED_CLOSE_OK",
            fail_code="BOT4V2_RECONCILER_NAKED_CLOSE_FAIL",
            mark_reason="naked_auto_close",
        )

    # ------------------------------------------------------------
    # HEARTBEAT : stale detection + force-close
    # ------------------------------------------------------------

    def tick(self, now: Optional[float] = None) -> ReconcilerTickResult:
        """Heartbeat tick. Detecte stales + force-close.

        Args:
            now : epoch UTC (defaut time.time())

        Returns:
            ReconcilerTickResult metrics.
        """
        ts = now if now is not None else time.time()

        # Throttle : skip si dernier heartbeat trop recent
        elapsed = ts - self._last_heartbeat_ts
        if elapsed < self._settings.heartbeat_interval_sec:
            emit_safe(
                _LOG, "BOT4V2_RECONCILER_HEARTBEAT_SKIP",
                last_age=elapsed,
                interval=self._settings.heartbeat_interval_sec,
            )
            return ReconcilerTickResult(
                n_positions_tracked=self.n_positions,
                skipped_heartbeat=True,
            )
        self._last_heartbeat_ts = ts

        # Detect stales (age > stale_threshold)
        stale_cids = [
            cid for cid, state in self._positions.items()
            if (ts - state.opened_ts) > self._settings.stale_threshold_sec
        ]
        n_stale = len(stale_cids)
        n_stale_closed = 0
        closed_cids: list[str] = []

        for cid in stale_cids:
            state = self._positions[cid]
            age_sec = ts - state.opened_ts
            emit_safe(
                _LOG, "BOT4V2_RECONCILER_STALE_DETECTED",
                sym=state.symbol, parent_cid=cid, age_sec=age_sec,
            )
            ok = self._force_close_stale(state, age_sec)
            if ok:
                n_stale_closed += 1
                closed_cids.append(cid)

        emit_safe(
            _LOG, "BOT4V2_RECONCILER_HEARTBEAT",
            n_pos=self.n_positions, n_stale=n_stale,
        )

        return ReconcilerTickResult(
            n_positions_tracked=self.n_positions,
            n_stale_detected=n_stale,
            n_stale_force_closed=n_stale_closed,
            n_naked_force_closed=self._cumul_naked_closed,
            parent_cids_force_closed=tuple(closed_cids),
        )

    def _force_close_stale(self, state: BotPositionState, age_sec: float) -> bool:
        """STALE force-close. Retourne True si OK.

        R2 review : meme retry policy que naked (factorize DRY).
        R1 review : utilise code STALE_CLOSE_FAIL (pas NAKED_CLOSE_FAIL).
        """
        emit_safe(
            _LOG, "BOT4V2_RECONCILER_STALE_FORCE_CLOSE",
            sym=state.symbol, parent_cid=state.parent_cid,
            direction=state.direction, age_sec=age_sec,
        )
        return self._send_close_with_retries(
            state,
            ok_code="BOT4V2_RECONCILER_NAKED_CLOSE_OK",
            fail_code="BOT4V2_RECONCILER_STALE_CLOSE_FAIL",
            mark_reason="stale_auto_close",
        )

    def _send_close_with_retries(
        self,
        state: BotPositionState,
        ok_code: str,
        fail_code: str,
        mark_reason: str,
    ) -> bool:
        """Helper retries DRY pour naked + stale force-close (R2 review P4).

        Args:
            state : position broker-side a fermer
            ok_code : log catalog code emis si succes
            fail_code : log catalog code emis si echec final (apres N retries)
            mark_reason : motif pour mark_closed (audit J+1)

        Returns:
            True si close OK, False si echec apres max_close_retries.
        """
        close_side = (
            OrderSide.SELL if state.direction == "LONG" else OrderSide.BUY
        )
        last_reason = "unknown"
        for retry in range(self._settings.max_close_retries):
            try:
                close_cid = self._dtc.send_close(
                    symbol=state.symbol,
                    side=close_side,
                    quantity=state.quantity,
                )
            except Exception as exc:  # noqa: BLE001
                last_reason = f"exc:{type(exc).__name__}"
                close_cid = None
            if close_cid:
                emit_safe(
                    _LOG, ok_code,
                    sym=state.symbol, parent_cid=state.parent_cid,
                    close_cid=close_cid,
                )
                self.mark_closed(state.parent_cid, reason=mark_reason)
                return True
            if not close_cid and last_reason == "unknown":
                last_reason = "send_close_returned_none"
            if retry + 1 < self._settings.max_close_retries:
                time.sleep(self._settings.close_retry_delay_sec)
        emit_safe(
            _LOG, fail_code,
            sym=state.symbol, parent_cid=state.parent_cid,
            retry=self._settings.max_close_retries,
            reason=last_reason,
        )
        return False
