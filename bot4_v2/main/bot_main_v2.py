"""Bot 4 v2 bot_main_v2 — BotMainLoop boucle principale orchestratrice.

Module NEW Phase P5.2 (25/06/2026) — Top-level Bot 4 v2 main loop.

Architecture :

```
JSONL stream -> BotMainLoop.run()
                  -> per bar :
                     1. build ScenarioContext via callable
                     2. router.route_bar(ctx)
                     3. for db in result.dispatched_brackets :
                          reconciler.register_bracket(...) (P4 hook)
                     4. if result.naked_brackets_pending :
                          reconciler.reconcile_naked(...) (force-close)
                     5. for cs in result.closed_signals :
                          if cs.parent_cid : reconciler.mark_closed(...)
                     6. if heartbeat_due : reconciler.tick()
```

SRP strict :
- BotMainLoop = orchestrateur loop + signal handling, PAS de business logic
- ContextBuilder = callable injecte (testabilite) qui produit ScenarioContext
  depuis bar dict + regime_engine + narrative_engine (delegue P0-P3 modules)
- JSONLStream Protocol = abstraction streaming (production : tail -F sur fichier
  live_enriched, tests : stub list de bars)

Garde-fous :
- Tous logs via emit_safe (regle souveraine TRACABILITE)
- Cycle exception caught + log + continue (anti crash bot sur 1 bar polluee)
- Graceful shutdown via stop() (signal handler caller's responsibility)
- Heartbeat reconciler decouple du bar rate (anti starvation si pas de bars)

EXCLU scope P5.2 (backlog P5.3+) :
- Tail -F file watcher production (impl pure-Python long mais straightforward)
- DTC fill event callback (caller doit hook DTC live events si pas paper Sim4 (reuse compte Bot 4 v1 stopped INCIDENT_LOG #83+#91)
  qui fait auto-fill)
- Signal handler SIGINT/SIGTERM (caller invoque .stop())
- Service nssm packaging
"""
from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable

from bot4_v2.decision.decision_router import (
    ClosedSignal,
    DecisionRouter,
    DispatchedBracket,
    RouterTickResult,
)
from bot4_v2.decision.scenario_registry import ScenarioContext
from bot4_v2.execution.position_reconciler import PositionReconciler
from bot4_v2.observability.telemetry import emit_safe, get_logger

_LOG = get_logger(__name__)


# ============================================================
# JSONL STREAM PROTOCOL
# ============================================================


class StreamEnded(Exception):
    """Levee quand le stream est ferme (fin de fichier sim / EOF reload)."""


@runtime_checkable
class JSONLStream(Protocol):
    """Interface streaming bar JSONL live_enriched.

    Production : implementation tail -F sur fichier (P5.3 backlog).
    Tests : stub list-backed iterator.
    """

    def next_bar(self) -> Optional[dict]:
        """Retourne next bar dict ou None si pas de bar disponible maintenant.

        Returns:
            dict bar JSONL parsed, OU None si pas de bar (boucle attend).

        Raises:
            StreamEnded : si stream definitivement clos (caller arrete loop).
        """
        ...


# ============================================================
# SETTINGS frozen
# ============================================================


@dataclass(frozen=True)
class BotMainSettings:
    """Settings BotMainLoop. Frozen anti-mutation runtime."""

    symbols: tuple[str, ...] = ("NQ",)
    heartbeat_interval_sec: float = 30.0  # call reconciler.tick() toutes les Xs
    poll_idle_sec: float = 1.0            # delay si stream.next_bar() == None
    max_cycles: int = 0                   # 0 = infini, >0 = stop apres N bars (tests)
    build_id: str = "bot4_v2_p5"          # tag boot log
    # R3 ULTRATHINK P5 review : default False = fail-loud (aligne lessons.md
    # regle souveraine). True = silent fallback risky en prod live.
    catch_cycle_exceptions: bool = False
    # Kill switch : si N exceptions consecutives meme bar -> shutdown bot
    # (anti silent crash loop). 0 = disabled.
    max_consecutive_exceptions: int = 5
    # Auto-register signal handlers SIGINT/SIGTERM dans run() (R5.2 review)
    install_signal_handlers: bool = True

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("symbols cannot be empty")
        if self.heartbeat_interval_sec < 0:
            raise ValueError("heartbeat_interval_sec must be >= 0")
        if self.poll_idle_sec < 0:
            raise ValueError("poll_idle_sec must be >= 0")
        if self.max_cycles < 0:
            raise ValueError("max_cycles must be >= 0")
        if self.max_consecutive_exceptions < 0:
            raise ValueError("max_consecutive_exceptions must be >= 0")


# ============================================================
# BOT MAIN LOOP
# ============================================================


class BotMainLoop:
    """Boucle principale Bot 4 v2 (P5.2).

    Pattern usage :
        loop = BotMainLoop(
            router=router,
            reconciler=reconciler,
            stream=jsonl_stream,
            context_builder=build_ctx_from_bar,
            settings=BotMainSettings(symbols=("NQ",), max_cycles=100),
        )
        loop.run()  # bloquant jusqu'a stop() ou max_cycles atteint

    context_builder est un callable (bar dict, symbol) -> ScenarioContext
    qui delegue aux modules P0-P3 (regime_source.detect, narrative_engine.build,
    menthorq_source.load).
    """

    def __init__(
        self,
        router: DecisionRouter,
        reconciler: PositionReconciler,
        stream: JSONLStream,
        context_builder: Callable[[dict, str], ScenarioContext],
        settings: Optional[BotMainSettings] = None,
    ):
        if router is None:
            raise ValueError("router is required")
        if reconciler is None:
            raise ValueError("reconciler is required")
        if stream is None:
            raise ValueError("stream is required")
        if not callable(context_builder):
            raise ValueError("context_builder must be callable")
        self._router = router
        self._reconciler = reconciler
        self._stream = stream
        self._build_context = context_builder
        self._settings = settings or BotMainSettings()
        self._stop_requested = False
        self._processed_bars = 0
        self._total_dispatches = 0
        # R4 ULTRATHINK P5 review : init a -inf via 0.0 puis re-init au boot run()
        # (avant : 0.0 garantit que premier heartbeat se declenche TOUJOURS car
        # time.time() - 0.0 ~= 1.78e9 >> any interval, comportement non-documente)
        self._last_heartbeat_ts: float = 0.0
        # R3 ULTRATHINK : compteur kill-switch consecutive exceptions
        self._consecutive_exceptions = 0

    @property
    def settings(self) -> BotMainSettings:
        return self._settings

    @property
    def processed_bars(self) -> int:
        return self._processed_bars

    @property
    def total_dispatches(self) -> int:
        return self._total_dispatches

    def stop(self) -> None:
        """Demande arret propre (signal handler caller / test pattern)."""
        self._stop_requested = True

    # ------------------------------------------------------------
    # MAIN LOOP
    # ------------------------------------------------------------

    def run(self) -> None:
        """Boucle principale. Bloquant jusqu'a stop() / max_cycles / StreamEnded."""
        emit_safe(
            _LOG, "BOT4V2_MAIN_BOOT",
            build_id=self._settings.build_id,
            symbols=",".join(self._settings.symbols),
        )
        # R4 ULTRATHINK : init heartbeat au boot (anti first-tick wrong-trigger)
        self._last_heartbeat_ts = time.time()
        # R5.2 ULTRATHINK : install SIGINT/SIGTERM handlers (graceful shutdown
        # sur nssm/systemd kill). install_signal_handlers=False pour tests +
        # contextes ou caller gere les signaux (eviter clash subprocess).
        if self._settings.install_signal_handlers:
            self._install_signal_handlers()

        shutdown_reason = "unknown"
        try:
            while not self._stop_requested:
                if (
                    self._settings.max_cycles > 0
                    and self._processed_bars >= self._settings.max_cycles
                ):
                    shutdown_reason = "max_cycles_reached"
                    break

                try:
                    bar = self._stream.next_bar()
                except StreamEnded:
                    emit_safe(
                        _LOG, "BOT4V2_MAIN_STREAM_END",
                        n_bars=self._processed_bars,
                    )
                    shutdown_reason = "stream_ended"
                    break

                if bar is None:
                    self._maybe_heartbeat()
                    time.sleep(self._settings.poll_idle_sec)
                    continue

                self._process_bar(bar)
                self._processed_bars += 1
                self._maybe_heartbeat()

                # R3 ULTRATHINK : kill-switch sur consecutive exceptions
                if (
                    self._settings.max_consecutive_exceptions > 0
                    and self._consecutive_exceptions
                    >= self._settings.max_consecutive_exceptions
                ):
                    emit_safe(
                        _LOG, "BOT4V2_MAIN_KILL_SWITCH",
                        n_exc=self._consecutive_exceptions,
                        threshold=self._settings.max_consecutive_exceptions,
                    )
                    shutdown_reason = "kill_switch_consecutive_exc"
                    break
            else:
                shutdown_reason = "stop_requested"
        finally:
            emit_safe(
                _LOG, "BOT4V2_MAIN_SHUTDOWN",
                reason=shutdown_reason,
                n_bars=self._processed_bars,
                n_disp=self._total_dispatches,
            )

    def _install_signal_handlers(self) -> None:
        """Install SIGINT + SIGTERM handlers (graceful shutdown)."""
        def _handler(signum, _frame):
            sig_name = signal.Signals(signum).name
            emit_safe(
                _LOG, "BOT4V2_MAIN_SIGNAL_HANDLER",
                signal=sig_name,
            )
            self._stop_requested = True

        try:
            signal.signal(signal.SIGINT, _handler)
            signal.signal(signal.SIGTERM, _handler)
        except (ValueError, AttributeError):
            # ValueError : pas dans main thread (tests pytest subprocess)
            # AttributeError : Windows ne supporte pas tous les signaux
            pass

    # ------------------------------------------------------------
    # PER-BAR PROCESSING
    # ------------------------------------------------------------

    def _process_bar(self, bar: dict) -> Optional[RouterTickResult]:
        """Process 1 bar pour chaque symbole configure.

        Pour chaque symbol :
        - build_context(bar, symbol) -> ScenarioContext
        - router.route_bar(ctx) -> RouterTickResult
        - hook reconciler (register / naked / closed)

        Returns:
            Dernier RouterTickResult (utile tests). En multi-symbol, retourne le
            dernier mais audit complet via _LOG codes.
        """
        last_result: Optional[RouterTickResult] = None
        cycle_had_exception = False
        for symbol in self._settings.symbols:
            try:
                ctx = self._build_context(bar, symbol)
            except Exception as exc:  # noqa: BLE001
                cycle_had_exception = True
                emit_safe(
                    _LOG, "BOT4V2_MAIN_CYCLE_EXC",
                    sym=symbol, exc_type=type(exc).__name__,
                )
                if not self._settings.catch_cycle_exceptions:
                    raise
                continue

            try:
                result = self._router.route_bar(ctx)
            except Exception as exc:  # noqa: BLE001
                cycle_had_exception = True
                emit_safe(
                    _LOG, "BOT4V2_MAIN_CYCLE_EXC",
                    sym=symbol, exc_type=type(exc).__name__,
                )
                if not self._settings.catch_cycle_exceptions:
                    raise
                continue

            self._hook_dispatched(symbol, result.dispatched_brackets)
            self._hook_naked(
                symbol, result.naked_brackets_pending,
            )
            self._hook_closed(symbol, result.closed_signals)
            self._total_dispatches += result.brackets_dispatched
            last_result = result

        # R3 ULTRATHINK : maintenir compteur consecutive_exceptions
        if cycle_had_exception:
            self._consecutive_exceptions += 1
        else:
            self._consecutive_exceptions = 0
        return last_result

    # ------------------------------------------------------------
    # HOOKS RECONCILER
    # ------------------------------------------------------------

    def _hook_dispatched(
        self,
        symbol: str,
        dispatched: tuple[DispatchedBracket, ...],
    ) -> None:
        """Hook chaque DispatchedBracket -> reconciler.register_bracket()."""
        for db in dispatched:
            self._reconciler.register_bracket(
                symbol=db.symbol,
                parent_cid=db.parent_cid,
                sl_cid=db.sl_cid,
                direction=db.direction,
                quantity=db.quantity,
                fill_price=db.fill_price,
                naked=db.naked,
            )
            emit_safe(
                _LOG, "BOT4V2_MAIN_DISPATCHED_REGISTER",
                sym=symbol, parent_cid=db.parent_cid,
                direction=db.direction,
            )

    def _hook_naked(
        self, symbol: str, naked_cids: tuple[str, ...],
    ) -> None:
        """Hook naked_brackets_pending -> reconciler.reconcile_naked()."""
        if not naked_cids:
            return
        n_closed = self._reconciler.reconcile_naked(
            naked_parent_cids=naked_cids, symbol=symbol,
        )
        emit_safe(
            _LOG, "BOT4V2_MAIN_NAKED_RECONCILED",
            sym=symbol, n=len(naked_cids), ok=n_closed,
        )

    def _hook_closed(
        self, symbol: str, closed: tuple[ClosedSignal, ...],
    ) -> None:
        """Hook closed_signals -> reconciler.mark_closed() si parent_cid non-vide."""
        for cs in closed:
            if not cs.parent_cid:
                # PENDING -> INVALIDATED sans dispatch prealable : pas d'entree
                # dans le reconciler tracker. Skip silencieux (pas un bug).
                continue
            self._reconciler.mark_closed(
                parent_cid=cs.parent_cid,
                reason=cs.reason,
            )
            emit_safe(
                _LOG, "BOT4V2_MAIN_SIGNAL_CLOSED",
                sym=symbol, parent_cid=cs.parent_cid,
                final_state=cs.final_state, reason=cs.reason,
            )

    # ------------------------------------------------------------
    # HEARTBEAT
    # ------------------------------------------------------------

    def _maybe_heartbeat(self, now: Optional[float] = None) -> None:
        """Call reconciler.tick() si interval ecoule."""
        ts = now if now is not None else time.time()
        if ts - self._last_heartbeat_ts < self._settings.heartbeat_interval_sec:
            return
        self._last_heartbeat_ts = ts
        tick_result = self._reconciler.tick(now=ts)
        emit_safe(
            _LOG, "BOT4V2_MAIN_HEARTBEAT_TICK",
            n_pos=tick_result.n_positions_tracked,
            n_stale=tick_result.n_stale_force_closed,
        )


# ============================================================
# JSONL TAIL STREAM (production-grade R5.1)
# ============================================================


class JSONLTailStream:
    """Tail -F production stream JSONL live_enriched (R5.1 ULTRATHINK P5).

    Pattern : suit le fichier via mtime + lecture incremental. Reload sur
    rotation (new inode detected). Anti-blocage : next_bar() returns None
    immediatement si pas de nouvelle ligne disponible (caller poll).

    Production :
        stream = JSONLTailStream(
            path=Path("DATA/live_enriched/sierra/NQ/20260625_NQ_sierra_enriched.jsonl"),
        )
        # Dans BotMainLoop.run() :
        bar = stream.next_bar()

    Garde-fous :
    - Fail-soft sur ligne JSON parse error (log + skip)
    - Re-open auto si fichier rotate (nouvelle date)
    - StreamEnded jamais leve (live stream est infini par construction)
    """

    def __init__(self, path: Path, encoding: str = "utf-8"):
        self._path = Path(path)
        self._encoding = encoding
        self._file = None  # type: Optional[object]
        self._inode = None  # type: Optional[int]
        self._lines_read = 0

    def _open_or_reopen(self) -> bool:
        """Ouvre le fichier ou reopen si rotation detected. Returns True si OK."""
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            return False
        current_inode = stat.st_ino
        if self._file is None or self._inode != current_inode:
            if self._file is not None:
                try:
                    self._file.close()  # type: ignore
                except Exception:  # noqa: BLE001
                    pass
            self._file = open(self._path, "r", encoding=self._encoding)  # noqa: SIM115
            # Si re-open (rotation), reset au debut. Si premier open, idem.
            self._inode = current_inode
            self._lines_read = 0
        return True

    def next_bar(self) -> Optional[dict]:
        """Retourne next bar OU None si pas de nouvelle ligne.

        StreamEnded n'est JAMAIS leve (live stream perpetuel by design).
        Le caller arrete via stop() ou max_cycles.
        """
        if not self._open_or_reopen():
            return None
        line = self._file.readline()  # type: ignore
        if not line:
            return None
        try:
            bar = json.loads(line.strip())
        except (json.JSONDecodeError, ValueError):
            # Ligne corrompue (partielle car ecriture en cours ?) : skip
            return None
        if not isinstance(bar, dict):
            return None
        self._lines_read += 1
        return bar

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()  # type: ignore
            except Exception:  # noqa: BLE001
                pass
            self._file = None

    @property
    def lines_read(self) -> int:
        return self._lines_read
