"""Bot 4 MIA Trader — main.py boucle principale.

Orchestre M1 → M2 → M4 → M3 → M5 → M3.5 selon architecture scellee 26/05.

Architecture flow :
    1. M1 Reader (live_enriched JSONL + MenthorQ + eco_calendar)
       → emit ReaderEvent
       → produit ReadResult (bar dict, menthorq_fresh, eco_status, data_actionable_hard)
    2. M2 Decide (4 Layers L1/L2/L4/L5 + pre-gates + threshold)
       → emit DecisionEvent
       → produit DecideResult (action ACHAT/VENTE/ATTENDRE, direction, conviction)
    3. M4 Risk Gate (HARD GATE avant SLTP/Execution)
       → emit RiskEvent
       → produit (allow, blocking_reason)
    4. M3 SLTPEngine (calcul SL/TP statiques)
       → emit SLTPEvent
       → produit SLTPDecision (sl_price, tp1_price, rr_ratio)
    5. M5 DTCExecutor (envoie bracket DTC Sim4)
       → emit ExecutionEvent
       → produit BracketResult (parent_id, tp_cid, sl_cid)
    6. M3.5 PositionMonitor (polling poll 10s)
       → update trailing TR40 + MFE-TP
       → emit ExecutionEvent (update SL ou close TRAILING_TP)
    7. Au close → M4.on_trade_close (update PnL, cooldown, daily counters)

Convention Bot 4 :
- ClientName="MIA_Bot_4", TradeAccount="Sim4"
- Mode phase 7.1 SAFE COLLECT (1 micro) → debug runtime sans douleur
- Mode phase 7.2 PAPER AGGRESSIVE (3 micros) → collecte data Lopez

Fixes review J10 appliques :
- C1 : tp_cid/sl_cid trackes dans PositionState + passes a flatten
- C2 : trade_account="Sim4" passe explicitement a flatten
- C3 : get_tick_size + get_tick_value via CORE/constants (anti-pattern tick hardcode)
- C4 : threading.Lock autour open_positions (race callbacks DTC vs polling)
- C5 : Telemetry.close() public au lieu de _drain_and_close()
- I4 : lock file LOGS/bot4.lock boot check + atexit unlink (process unique)
"""
from __future__ import annotations

import atexit
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Literal, Optional

try:
    from CORE.constants import get_tick_size, get_tick_value  # type: ignore
except ImportError:
    # Fallback strict : on tente import relatif (script lance depuis racine)
    try:
        from constants import get_tick_size, get_tick_value  # type: ignore
    except ImportError:
        # Last resort default (devrait jamais arriver en prod)
        def get_tick_size(symbol: str) -> float:
            return {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}.get(symbol, 0.25)

        def get_tick_value(symbol: str) -> float:
            return {"NQ": 0.50, "ES": 1.25, "MGC": 1.00}.get(symbol, 0.50)

from .bot4_logger import emit_safe, get_bot4_logger
from .decide import DecideResult, SignalState, decide_action
from .execution import DTCExecutor, OrderUpdateRaw
from .execution_config import ExecutionConfig
from .position_monitor import PositionMonitor, PositionState, TrailingConfig
from .reader import M1Pipeline, ReadResult
from .risk import RiskConfig, RiskManager
from .sltp_engine import SLTPDecision, SLTPEngine
from .telemetry import Telemetry, get_telemetry


# =============================================================================
# Constantes Bot 4
# =============================================================================

BOT_NAME = "MIA_Bot_4"
SYMBOLS_DEFAULT = ["NQ", "ES"]  # MGC ajout futur
LOCK_FILE_NAME = "bot4.lock"
HEARTBEAT_INTERVAL_SEC = 60  # J11 fix P0-4 : 1/min independant poll_interval


# =============================================================================
# Lock file process unique (fix I4 review J10)
# =============================================================================


class Bot4LockError(RuntimeError):
    """Lock file deja present : autre instance Bot 4 active."""

    pass


def _pid_alive(pid: int) -> bool:
    """Cross-platform PID alive check.

    Windows : os.kill(pid, 0) raise OSError si PID dead, OK si alive.
    Linux/Mac : meme comportement.

    Returns False sur tout echec (defensive : si on ne sait pas, considerer mort
    pour permettre auto-cleanup orphelin).
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except Exception:
        return False


def acquire_lock_file(lock_dir: Path) -> Path:
    """Cree lock file `bot4.lock`. Raise si deja present (process unique).

    Fix I4 review J10 : empeche double-instance Bot 4 (2 logons DTC = chaos).

    Fix 28/05 v2 (diag agent bilan P2#7) : AUTO-CLEANUP lock orphelin si le PID
    inscrit dans le lock n'est plus vivant. Avant ce fix, un crash brutal
    laissait le lock en place et bloquait tous les reboots suivants (12
    BOOT_START / 5 BOOT_READY = 58% echec observe 28/05). Pattern lessons.md
    "DTC pythonw / Task Scheduler pour process persistant — python.exe detache
    meurt".

    Args:
        lock_dir: dossier ou creer le lock (typiquement LOGS/).

    Returns:
        Path du lock file cree.

    Raises:
        Bot4LockError si lock file deja present ET PID toujours vivant
        (double-instance reelle). Auto-cleanup silencieux sinon (avec emit
        BOT4_LOCK_ORPHAN_CLEANED via stderr car logger pas encore init au boot).
    """
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / LOCK_FILE_NAME
    if lock_path.exists():
        try:
            content = lock_path.read_text(encoding="utf-8").strip()
        except OSError:
            content = "<unreadable>"
        # 28/05 v2 : parse pid= du contenu, check liveness
        orphan_pid = None
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("pid="):
                try:
                    orphan_pid = int(line.split("=", 1)[1])
                except (ValueError, IndexError):
                    pass
                break
        if orphan_pid is not None and not _pid_alive(orphan_pid):
            # Orphan : process mort, on nettoie + on recrée
            try:
                lock_path.unlink()
                print(
                    f"[Bot4] BOT4_LOCK_ORPHAN_CLEANED: pid={orphan_pid} dead, "
                    f"removed stale lock at {lock_path}",
                    file=sys.stderr,
                )
            except OSError as e:
                raise Bot4LockError(
                    f"Lock orphan detected (pid={orphan_pid} dead) but unlink "
                    f"failed: {e}. Path: {lock_path}"
                )
        else:
            # PID toujours vivant (vraie double-instance) OU PID illisible (refus prudent)
            raise Bot4LockError(
                f"Lock file present: {lock_path} (contenu: {content!r}, "
                f"pid={orphan_pid} alive). Autre instance Bot 4 active. "
                f"Si crash precedent, supprimer le fichier ou attendre auto-clean."
            )
    # 28/05 v2 FIX R4 review boot : O_EXCL atomique anti race condition entre
    # unlink orphelin et write_text. Si un autre process arrive entre unlink et
    # write_text → 2 Bot 4 actifs silencieusement. O_EXCL garantit creation
    # atomique : si fichier reapparait entre unlink et open, OSError EEXIST.
    payload = (
        f"pid={os.getpid()}\nstart_ts={time.time()}\nbot={BOT_NAME}\n"
    )
    try:
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
    except FileExistsError:
        # Race : un autre process Bot4 a cree le lock entre unlink et open.
        # Refus prudent : ne pas overwrite, raise pour declencher restart nssm
        # (la prochaine tentative auto-cleanera si PID dead, ou raise si alive).
        raise Bot4LockError(
            f"Lock race detected: {lock_path} reapparu entre orphan unlink et "
            f"O_EXCL open. Autre process Bot4 demarre simultanement. "
            f"Restart nssm dans 30s reessayera le check orphan."
        )
    return lock_path


def release_lock_file(lock_path: Path) -> None:
    """Supprime lock file (atexit ou shutdown propre)."""
    try:
        if lock_path.exists():
            lock_path.unlink()
    except OSError:
        pass  # silent : on n'a plus rien a logger ici (atexit)


# =============================================================================
# Bot4Main
# =============================================================================


class Bot4Main:
    """Boucle principale Bot 4. Orchestre M1-M5 + M3.5.

    Usage :
        bot = Bot4Main(
            data_root=Path("D:/.../DATA"),
            symbols=["NQ"],
            risk_config=RiskConfig.collect_mode(),       # Phase 7.1 SAFE
            execution_config=ExecutionConfig.sim4_default(),
            trailing_config=TrailingConfig.paper_mode(),
            telemetry_logs_root=Path("D:/.../LOGS"),
            dry_run=False,
        )
        bot.connect()
        bot.run()  # bloquant
    """

    def __init__(
        self,
        *,
        data_root: Path,
        symbols: list[str] = None,
        risk_config: Optional[RiskConfig] = None,
        execution_config: Optional[ExecutionConfig] = None,
        trailing_config: Optional[TrailingConfig] = None,
        telemetry_logs_root: Optional[Path] = None,
        dry_run: bool = False,
        poll_interval_sec: float = 10.0,
        acquire_lock: bool = True,
    ):
        self.data_root = Path(data_root)
        self.symbols = symbols or SYMBOLS_DEFAULT
        self.dry_run = dry_run
        self.poll_interval_sec = poll_interval_sec
        self._running = False

        # J11 instrumentation log_catalog (50 codes BOT4_*)
        self._log = get_bot4_logger("main")
        self._boot_ts: float = 0.0
        self._bars_processed: int = 0
        self._last_heartbeat_ts: float = 0.0

        emit_safe(self._log, "BOT4_BOOT_START",
                  symbols=self.symbols, dry_run=dry_run,
                  trade_account=(execution_config or ExecutionConfig.sim4_default()).dtc.trade_account)

        # Lock file process unique (fix I4)
        # Skip si tests inline (acquire_lock=False) pour permettre tests paralleles.
        self._lock_path: Optional[Path] = None
        if acquire_lock and telemetry_logs_root is not None:
            try:
                self._lock_path = acquire_lock_file(telemetry_logs_root)
            except Bot4LockError as e:
                emit_safe(self._log, "BOT4_LOCK_FAIL",
                          lock_path=str(telemetry_logs_root / LOCK_FILE_NAME),
                          content=str(e))
                raise
            atexit.register(release_lock_file, self._lock_path)

        # Telemetry singleton (M6)
        if telemetry_logs_root is not None:
            self.telemetry: Optional[Telemetry] = get_telemetry(telemetry_logs_root)
        else:
            self.telemetry = None

        # M1 Reader (live_enriched JSONL + MenthorQ + eco_calendar)
        # Migration Sierra (16/06) : source = live_enriched/sierra (databento mort
        # depuis 12/06). Reader glob *_{SYM}*.jsonl -> fichiers _sierra_enriched.
        self.reader = M1Pipeline(
            live_root=self.data_root / "live_enriched" / "sierra",
            menthorq_root=self.data_root / "MENTHORQ",
            telemetry=self.telemetry,
        )

        # M4 Risk
        self.risk = RiskManager(config=risk_config or RiskConfig.collect_mode())

        # M3 SLTPEngine (un par symbole)
        self.sltp_engines: Dict[str, SLTPEngine] = {
            sym: SLTPEngine(symbol=sym) for sym in self.symbols  # type: ignore
        }

        # M5 DTCExecutor (un singleton, multi-symbol via trade_account/symbol)
        exec_cfg = execution_config or ExecutionConfig.sim4_default()
        if dry_run:
            exec_cfg = ExecutionConfig.dry_run_test()
        self.executor = DTCExecutor(config=exec_cfg, telemetry=self.telemetry)

        # M3.5 PositionMonitor (singleton, gere state par signal_id)
        self.monitor = PositionMonitor(
            config=trailing_config or TrailingConfig.paper_mode(),
        )

        # Snapshot trade_account pour flatten (fix C2)
        self._trade_account = exec_cfg.dtc.trade_account

        # Fix P2-3 review J10 : compteur get_current_price echec cumule
        # Si DTC market data refuse 100% du temps (cf incident historique
        # CLAUDE.md "DTC market data refuse par SC"), les positions restent
        # ouvertes silencieusement. Alerte au seuil pour visibilite J11.
        self._price_fail_consecutive: int = 0
        self._price_fail_alert_threshold: int = 10

        # State machines freshness (un par symbole)
        self.signal_states: Dict[str, SignalState] = {
            sym: SignalState(expiration_n_bars=5) for sym in self.symbols
        }

        # Positions ouvertes (per signal_id pour PositionMonitor)
        # Fix C4 review J10 : Lock obligatoire pour synchroniser :
        #   - _process_symbol (thread main) : ajoute apres send_bracket
        #   - _monitor_open_positions (thread main) : retire apres close
        #   - _on_filled/_on_cancelled (thread _recv_loop DTC) : lecture/maj
        # Sans lock : race condition possible (KeyError ou pop pendant iteration).
        self._positions_lock = threading.Lock()
        self.open_positions: Dict[str, PositionState] = {}

        # Fix 28/05 BUG critique : state persistant open_positions pour ne pas
        # perdre les positions actives quand Bot 4 restart (RAM only avant). Sans ca,
        # restart entre OPEN et fill TP/SL = `_on_filled` voit target_pos=None ->
        # BOT4_FILL_UNKNOWN_CID + CLOSE jamais emis + ghost dashboard eternel
        # (cf incident matin 04:22 LONG NQ TP +$24.50 non traque).
        # Path : LOGS/bot4_open_positions.json (cote du lock file existant).
        # Reload uniquement si fichier < 24h (eviter reload corruption ancienne).
        self._positions_persist_path: Optional[Path] = None
        if telemetry_logs_root is not None:
            self._positions_persist_path = telemetry_logs_root / "bot4_open_positions.json"
            self._reload_open_positions_from_disk()

        # Fix 05/06 (incident SL fantome 04/06 23:13 UTC) : re-injecter CIDs
        # reloaded dans executor._my_cids pour que recv_loop DTC reconnaisse les
        # fills de nos propres positions apres restart. Sans ca, tous les fills
        # post-restart sont rejetes avec BOT4_FILL_UNKNOWN_CID (filtre broadcast
        # pollution 03/06 lignes execution.py:405-413), trade orphelin invisible.
        n_recovered = 0
        with self._positions_lock:
            for pos in self.open_positions.values():
                self.executor.register_recovered_cids(
                    pos.signal_id, pos.tp_cid, pos.sl_cid
                )
                n_recovered += 1
        if n_recovered > 0:
            emit_safe(self._log, "BOT4_RECOVERY_CIDS_REINJECTED",
                      n_positions=n_recovered)

        # Hook callbacks executor → handlers Bot 4
        self.executor.on_filled_callback = self._on_filled
        self.executor.on_cancelled_callback = self._on_cancelled

        # J11 : config loaded summary
        _risk_cfg = risk_config or RiskConfig.collect_mode()
        _trail_cfg = trailing_config or TrailingConfig.paper_mode()
        emit_safe(self._log, "BOT4_CONFIG_LOADED",
                  risk_mode=_risk_cfg.mode,
                  sizing_mode=_risk_cfg.sizing_mode,
                  tr40_enabled=_trail_cfg.tr40_enabled,
                  mfe_tp_enabled=_trail_cfg.mfe_tp_enabled,
                  dry_run=dry_run)

    # -------------------------------------------------------------------------
    # Connexion / shutdown
    # -------------------------------------------------------------------------

    def connect(self) -> bool:
        """Connecte DTC (ou dry_run). Returns True si OK."""
        ok = self.executor.connect()
        if ok:
            self._boot_ts = time.time()
            # J12 P1.1 fix : publier phase pour que dashboard lise depuis events JSONL
            # (pas depuis son propre ENV qui peut diverger du service Bot 4)
            phase = os.environ.get("MIA_BOT4_PHASE", "P7.1_SAFE_COLLECT")
            emit_safe(self._log, "BOT4_BOOT_READY",
                      dtc_state="connected" if not self.dry_run else "dry_run",
                      reader_state="ready",
                      risk_mode=self.risk.config.mode,
                      phase=phase)
        else:
            emit_safe(self._log, "BOT4_BOOT_FAIL",
                      reason="executor.connect() returned False",
                      dtc_connected=False)
        return ok

    def shutdown(self) -> None:
        """Shutdown propre : drain telemetry + disconnect DTC + release lock."""
        emit_safe(self._log, "BOT4_SHUTDOWN",
                  reason="explicit shutdown() call",
                  positions_open=len(self.open_positions))
        self._running = False
        try:
            self.executor.disconnect()
        except Exception as e:
            print(f"[Bot4] executor.disconnect error: {e}", file=sys.stderr)
        # Fix C5 review J10 : API publique close() au lieu de _drain_and_close()
        if self.telemetry:
            try:
                self.telemetry.close()
            except Exception as e:
                print(f"[Bot4] telemetry.close error: {e}", file=sys.stderr)
        # Fix I4 review J10 : release lock file
        if self._lock_path is not None:
            release_lock_file(self._lock_path)
            self._lock_path = None

    # -------------------------------------------------------------------------
    # Boucle principale
    # -------------------------------------------------------------------------

    def run(self) -> None:
        """Boucle principale. Poll les bars + decide + execute."""
        if not self.executor.is_connected():
            raise RuntimeError("Executor not connected. Appel connect() avant run()")
        self._running = True

        print(f"[Bot4] Demarrage boucle (symbols={self.symbols}, dry_run={self.dry_run})")

        while self._running:
            try:
                for symbol in self.symbols:
                    self._process_symbol(symbol)
                    self._bars_processed += 1
                self._monitor_open_positions()
                # J11 fix P0-4 : heartbeat 1/min independant poll_interval
                now = time.time()
                if now - self._last_heartbeat_ts >= HEARTBEAT_INTERVAL_SEC:
                    uptime_min = int((now - self._boot_ts) / 60) if self._boot_ts > 0 else 0
                    emit_safe(self._log, "BOT4_HEARTBEAT",
                              uptime_min=uptime_min,
                              bars_processed=self._bars_processed,
                              trades_today=0,  # TODO : aggreger depuis risk states
                              positions=len(self.open_positions))
                    self._last_heartbeat_ts = now
            except KeyboardInterrupt:
                print("[Bot4] KeyboardInterrupt - shutdown propre")
                break
            except Exception as e:
                # J11 : remplace silent print stderr par code log CRITIQUE
                emit_safe(self._log, "BOT4_LOOP_EXCEPTION",
                          symbol="<unknown>",
                          exc_type=type(e).__name__,
                          exc_msg=str(e))
                print(
                    f"[Bot4] Erreur boucle: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
            time.sleep(self.poll_interval_sec)

        self.shutdown()

    def process_one_bar(self, symbol: str) -> Dict[str, Any]:
        """Process 1 barre pour 1 symbole (utilise pour tests + 1-shot calls).

        Returns dict avec summary actions prises.

        Note (I5 review) : exceptions ne sont PAS catchees ici (visibilite tests).
        En production via run(), la boucle wrap dans try/except.
        """
        return self._process_symbol(symbol)

    # -------------------------------------------------------------------------
    # Pipeline M1 → M2 → M4 → M3 → M5
    # -------------------------------------------------------------------------

    def _process_symbol(self, symbol: str) -> Dict[str, Any]:
        """Process 1 barre pour 1 symbole. Pipeline complet."""
        summary: Dict[str, Any] = {
            "symbol": symbol,
            "action": "ATTENDRE",
            "blocking_gate": None,
            "trade_taken": False,
        }

        # ─── M1 Reader ────────────────────────────────────────────────────
        read_result: Optional[ReadResult] = self.reader.read_and_emit(symbol)
        if read_result is None:
            summary["blocking_gate"] = "reader_no_bar"
            return summary

        # ─── M2 Decide ────────────────────────────────────────────────────
        decide_result: DecideResult = decide_action(
            bar=read_result.bar,
            decision_id=read_result.decision_id,
            symbol=symbol,
            menthorq_fresh=read_result.menthorq_fresh,
            eco_status=read_result.eco_status,
            eco_reason=read_result.eco_reason,
            signal_state=self.signal_states[symbol],
            session_date_trading=read_result.reader_event.session_date_trading,
        )
        if self.telemetry:
            try:
                self.telemetry.emit(decide_result.decision_event)
            except Exception as e:
                # J11 : remplace silent pass par emit_safe code log (Jackson 01/05)
                emit_safe(self._log, "BOT4_LOOP_EXCEPTION",
                          symbol=symbol,
                          exc_type=type(e).__name__,
                          exc_msg=f"telemetry.emit(decision_event): {e}")

        summary["action"] = decide_result.action
        summary["direction"] = decide_result.direction
        summary["score_total"] = decide_result.score_total
        summary["conviction"] = decide_result.conviction
        summary["binding_gate"] = decide_result.binding_gate

        if decide_result.action == "ATTENDRE":
            return summary

        # ─── M4 Risk Gate ─────────────────────────────────────────────────
        allow, risk_reason, risk_event = self.risk.check_pre_entry(
            symbol=symbol,  # type: ignore
            direction=decide_result.direction,  # type: ignore
            conviction=decide_result.conviction,
            decision_id=read_result.decision_id,
            bar_ts_event_ns=read_result.reader_event.bar_ts_event_ns,
            session_date_trading=read_result.reader_event.session_date_trading,
        )
        if self.telemetry:
            try:
                self.telemetry.emit(risk_event)
            except Exception as e:
                emit_safe(self._log, "BOT4_LOOP_EXCEPTION",
                          symbol=symbol,
                          exc_type=type(e).__name__,
                          exc_msg=f"telemetry.emit(risk_event): {e}")

        if not allow:
            summary["blocking_gate"] = risk_event.blocking_gate
            summary["blocking_reason"] = risk_reason
            return summary

        # ─── M3 SLTPEngine ────────────────────────────────────────────────
        engine = self.sltp_engines[symbol]
        sltp_decision: SLTPDecision = engine.evaluate(
            bar=read_result.bar,
            direction=decide_result.direction,  # type: ignore
        )

        if not sltp_decision.valid:
            summary["blocking_gate"] = "sltp_reject"
            summary["blocking_reason"] = sltp_decision.reject_reason
            # FIX 17/06 BUG SILENCIEUX : Bot 4 a 15 decisions ACHAT/VENTE
            # passees Risk ALLOW depuis hier soir mais 0 trade execute, car
            # SLTPEngine rejette ici sans aucun log -> impossible de diagnostiquer
            # la cause (sl_wall introuvable / SL > budget / RR < min_rr).
            # Ajout emit_safe MAJEUR pour rendre la cause visible.
            try:
                emit_safe(self._log, "BOT4_SLTP_VALID_FALSE",
                          sym=symbol,
                          direction=decide_result.direction,
                          reject_reason=sltp_decision.reject_reason or "unknown",
                          score=decide_result.score_total,
                          conviction=decide_result.conviction)
            except Exception:
                pass
            return summary

        entry_price = float(read_result.bar.get("close", 0.0))
        sltp_event = engine.build_event(
            sltp_decision,
            decision_id=read_result.decision_id,
            bar_ts_event_ns=read_result.reader_event.bar_ts_event_ns,
            session_date_trading=read_result.reader_event.session_date_trading,
            entry_price=entry_price,
        )
        if self.telemetry and sltp_event is not None:
            try:
                self.telemetry.emit(sltp_event)
            except Exception as e:
                emit_safe(self._log, "BOT4_LOOP_EXCEPTION",
                          symbol=symbol,
                          exc_type=type(e).__name__,
                          exc_msg=f"telemetry.emit(sltp_event): {e}")

        # ─── M5 Execution DTC ─────────────────────────────────────────────
        # Fix C3 review J10 : get_tick_size centralise (anti-pattern hardcode 0.25/0.10)
        tick = get_tick_size(symbol)

        sign = 1 if decide_result.direction == "LONG" else -1
        sl_price = entry_price - sign * sltp_decision.sl_ticks * tick
        tp1_price = entry_price + sign * sltp_decision.tp1_ticks * tick
        sl_ticks_eff = float(sltp_decision.sl_ticks)
        tp_ticks_eff = float(sltp_decision.tp1_ticks)
        _override_applied = False

        # ─── Greffe scenarios (16/06) : NOS stops structurels (decision Jackson).
        # sltp_engine.evaluate ci-dessus reste en GARDE-FOU (gate valid + zone
        # walls). On OVERRIDE les prix avec ceux du scenario s'ils sont (a) du
        # bon cote de l'entry ET (b) dans une plage SL sanity (I1 review :
        # evite SL 0.5 tick instant-stop ou SL 300 ticks aberrant qui polluerait
        # la calibration). Sinon fallback sltp_engine + emit.
        # I2 : entry executee = close barre (entry_price). sl_ticks_eff recalcule
        # contre entry_price -> R:R EXECUTE honnete (peut differer du R:R conçu
        # famille A si close != niveau ; accepte en v1, calibration mesurera).
        _ssl = decide_result.scenario_sl_price
        _stp = decide_result.scenario_tp_price
        if _ssl is not None and _stp is not None and tick > 0:
            _ssl = float(_ssl)
            _stp = float(_stp)
            _sl_ok = (_ssl < entry_price) if sign > 0 else (_ssl > entry_price)
            _tp_ok = (_stp > entry_price) if sign > 0 else (_stp < entry_price)
            _sl_t = abs(entry_price - _ssl) / tick
            _tp_t = abs(_stp - entry_price) / tick
            _SL_MIN_TICKS, _SL_MAX_TICKS = 3.0, 250.0  # sanity (NQ struct ~40-60t)
            _bounds_ok = (_SL_MIN_TICKS <= _sl_t <= _SL_MAX_TICKS and _tp_t >= 1.0)
            if _sl_ok and _tp_ok and _bounds_ok:
                sl_price = _ssl
                tp1_price = _stp
                sl_ticks_eff = _sl_t
                tp_ticks_eff = _tp_t
                _override_applied = True
            else:
                # FIX 16/06 : raison precise du reject. Code log conserve pour
                # compat retro audit. Avant : "SLTP_REJECT_SIDE" generique
                # trompeur (signalait "mauvais cote" meme quand le vrai bug etait
                # TP_TOO_TIGHT ou SL_OUT_OF_BOUNDS).
                _reasons = []
                if not _sl_ok:
                    _reasons.append("sl_wrong_side")
                if not _tp_ok:
                    _reasons.append("tp_wrong_side")
                if not _bounds_ok:
                    if _sl_t < _SL_MIN_TICKS:
                        _reasons.append(f"sl_too_tight({_sl_t:.1f}t<{_SL_MIN_TICKS})")
                    elif _sl_t > _SL_MAX_TICKS:
                        _reasons.append(f"sl_too_wide({_sl_t:.1f}t>{_SL_MAX_TICKS})")
                    if _tp_t < 1.0:
                        _reasons.append(f"tp_too_tight({_tp_t:.1f}t<1.0)")
                emit_safe(self._log, "BOT4_SCENARIO_SLTP_REJECT_SIDE",
                          sym=symbol, scenario=decide_result.scenario_name,
                          entry=entry_price, sl=_ssl, tp=_stp,
                          reasons=",".join(_reasons) or "unknown")

        n_micros = risk_event.sizing_decision.n_micros if risk_event.sizing_decision else 1
        # Contrat = celui du feed sierra (bar["contract"]) en priorite -> execute
        # sur le MEME contrat que la decision (auto-rollover, fix 16/06 NQM->NQU
        # qui faisait fill a 30590 au lieu de 30900). Fallback mapping si absent.
        contract = read_result.bar.get("contract") or self._symbol_to_contract(symbol)
        side: Literal["BUY", "SELL"] = "BUY" if decide_result.direction == "LONG" else "SELL"

        bracket = self.executor.send_bracket(
            symbol=contract,
            side=side,
            quantity=n_micros,
            sl_price=sl_price,
            tp_price=tp1_price,
            tick_size=tick,
            signal_ref_price=entry_price,
            sl_ticks=int(round(sl_ticks_eff)),
            tp_ticks=int(round(tp_ticks_eff)),
        )

        if not bracket.success:
            # J11 : code log MAJEUR (rétrogradé de CRITIQUE pour anti-flood)
            emit_safe(self._log, "BOT4_EXEC_BRACKET_FAIL",
                      sym=symbol, side=side, qty=n_micros,
                      reject_reason=bracket.reject_reason or "unknown")
            summary["blocking_gate"] = "execution_failed"
            summary["blocking_reason"] = bracket.reject_reason
            return summary

        # J11 : bracket sent OK
        emit_safe(self._log, "BOT4_EXEC_BRACKET_SENT",
                  sym=symbol, side=side, qty=n_micros,
                  parent_id=bracket.parent_id,
                  tp_cid=bracket.tp_cid, sl_cid=bracket.sl_cid,
                  signal_ref_price=entry_price)
        # Reprice detecte
        if bracket.reprice_done:
            emit_safe(self._log, "BOT4_EXEC_REPRICE_DONE",
                      sym=symbol, parent_id=bracket.parent_id,
                      slip_ticks=bracket.slip_ticks,
                      signal_ref=entry_price,
                      fill_price=bracket.fill_price)

        # Register OCO pair (TP/SL cancel automatique au fill opposite)
        self.executor.register_oco_pair(bracket.tp_cid, bracket.sl_cid)
        emit_safe(self._log, "BOT4_EXEC_OCO_REGISTERED",
                  sym=symbol, tp_cid=bracket.tp_cid, sl_cid=bracket.sl_cid)

        # M4 : marquer position open
        self.risk.on_trade_open(
            symbol=symbol,
            signal_id=bracket.parent_id,
            ts_event_ns=read_result.reader_event.bar_ts_event_ns,
            session_date_trading=read_result.reader_event.session_date_trading,
        )
        # J11 : trade_open transition
        # Fix 28/05 (dashboard BUG #3) : enrichir ctx avec side/entry/SL/TP/qty
        # pour que paper_tracker dashboard puisse afficher correctement la
        # position active (avant : ctx minimal -> dashboard ? SELL Entry/SL/TP vides).
        _state = self.risk.states.get(symbol)
        actual_entry = bracket.fill_price or entry_price
        emit_safe(self._log, "BOT4_RISK_TRADE_OPEN",
                  sym=symbol, signal_id=bracket.parent_id,
                  positions_open=_state.positions_open if _state else 1,
                  side=decide_result.direction,
                  entry_price=round(actual_entry, 2),
                  sl_price=round(sl_price, 2),
                  tp_price=round(tp1_price, 2),
                  sl_ticks=round(sl_ticks_eff, 1),
                  qty=n_micros,
                  trade_account="Sim4")

        # M3.5 PositionMonitor : init state
        # Fix C1 review J10 : tracker tp_cid/sl_cid dans PositionState
        actual_entry = bracket.fill_price or entry_price
        # Fix C1 review greffe (16/06) : si override scenario actif, PositionState
        # DOIT tracker NOS prix/ticks (envoyes au broker), pas ceux de sltp_engine
        # -> sinon MAE/MFE/exit/outcomes calcules sur mauvais niveaux = data
        # calibration faussee (but de Sim4). Ticks recalcules contre le fill reel.
        if _override_applied and tick > 0:
            tp1_price_final = tp1_price
            sl_ticks_state = abs(sl_price - actual_entry) / tick
            tp1_ticks_state = abs(tp1_price - actual_entry) / tick
        else:
            # Fix 05/06 : recalcul tp1_price depuis tp1_ticks FINAL (source unique
            # sltp_decision) sinon desynchro state file (incident 04/06).
            tp1_price_final = actual_entry + sign * float(sltp_decision.tp1_ticks) * tick
            sl_ticks_state = float(sltp_decision.sl_ticks)
            tp1_ticks_state = float(sltp_decision.tp1_ticks)
        pos_state = PositionState(
            signal_id=bracket.parent_id,
            symbol=symbol,  # type: ignore
            direction=decide_result.direction,  # type: ignore
            entry_price=actual_entry,
            entry_ts_ns=read_result.reader_event.bar_ts_event_ns,
            n_micros=n_micros,
            sl_price=sl_price,
            sl_ticks_initial=sl_ticks_state,
            tp1_price=tp1_price_final,
            tp1_ticks=tp1_ticks_state,
            tp_cid=bracket.tp_cid,
            sl_cid=bracket.sl_cid,
        )
        # Fix C4 review J10 : lock pour eviter race avec callbacks DTC
        with self._positions_lock:
            self.open_positions[bracket.parent_id] = pos_state
            # Fix 28/05 BUG#1 : persiste apres mutation pour survivre aux restarts
            self._persist_open_positions()

        summary["trade_taken"] = True
        summary["parent_id"] = bracket.parent_id
        summary["tp_cid"] = bracket.tp_cid
        summary["sl_cid"] = bracket.sl_cid
        summary["entry_price"] = actual_entry
        summary["sl_price"] = sl_price
        summary["tp_price"] = tp1_price
        summary["n_micros"] = n_micros
        summary["slip_ticks"] = bracket.slip_ticks
        return summary

    # -------------------------------------------------------------------------
    # M3.5 PositionMonitor (poll polling apres entries)
    # -------------------------------------------------------------------------

    def _monitor_open_positions(self) -> None:
        """Pour chaque position ouverte, update trailing + close si MFE-TP.

        Fix C4 review J10 : on snapshot la liste sous lock pour eviter race
        avec _on_filled/_on_cancelled callbacks (thread DTC _recv_loop).
        Le snapshot evite RuntimeError dict modifie pendant iteration.
        """
        # Snapshot atomique sous lock
        with self._positions_lock:
            snapshot = list(self.open_positions.items())

        for signal_id, pos in snapshot:
            # Re-check sous lock que position toujours active (callback peut l'avoir retiree)
            with self._positions_lock:
                if signal_id not in self.open_positions:
                    continue
            contract = self._symbol_to_contract(pos.symbol)
            try:
                current_price = self.executor.get_current_price(contract)
            except Exception as e:
                self._price_fail_consecutive += 1
                emit_safe(self._log, "BOT4_EXEC_PRICE_UNAVAILABLE",
                          sym=pos.symbol, contract=contract,
                          consec_failures=self._price_fail_consecutive,
                          exc=f"{type(e).__name__}: {e}")
                # J11 : alerte CRITIQUE au seuil cumule
                if self._price_fail_consecutive == self._price_fail_alert_threshold:
                    emit_safe(self._log, "BOT4_EXEC_MARKET_DATA_DOWN",
                              contract=contract,
                              consec_failures=self._price_fail_consecutive,
                              threshold=self._price_fail_alert_threshold,
                              positions_unmonitored=len(self.open_positions))
                continue
            if current_price <= 0:
                continue
            # Reset compteur sur succes
            self._price_fail_consecutive = 0
            now_ns = time.time_ns()
            update = self.monitor.update(
                pos, current_price=current_price, bar_ts_ns=now_ns,
            )
            # J11 : drain events accumules par PositionMonitor (signal_id deja dans evt)
            for evt in update.events:
                code = evt.pop("code", None)
                if code:
                    emit_safe(self._log, code, **evt)
            # MFE-TP close → cancel TP/SL + flatten
            if update.close_now:
                self._close_position_via_flatten(
                    pos, close_reason=update.close_reason or "TRAILING_TP",
                    close_price=update.close_price or current_price,
                )
            # TR40 SL update → cancel+replace SL bracket (TODO Phase 8 cancel+replace)
            elif update.sl_changed and update.new_sl_price:
                # Bot 4 v1 : skip cancel+replace (legacy comme paper). Log only.
                pass

    def _close_position_via_flatten(
        self, pos: PositionState, close_reason: str, close_price: float,
    ) -> None:
        """Close position via flatten_position_safely 9 etapes.

        Fix C1 + C2 review J10 :
        - tp_cid/sl_cid pris directement depuis PositionState (plus de None hardcode)
        - trade_account explicite (self._trade_account = "Sim4" snapshot init)
        """
        contract = self._symbol_to_contract(pos.symbol)
        emit_safe(self._log, "BOT4_FLATTEN_START",
                  sym=pos.symbol, direction=pos.direction,
                  signal_id=pos.signal_id, n_contracts=pos.n_micros,
                  tp_cid=pos.tp_cid, sl_cid=pos.sl_cid)
        result = self.executor.flatten_position_safely(
            symbol_contract=contract,
            direction=pos.direction,
            tp_cid=pos.tp_cid,
            sl_cid=pos.sl_cid,
            n_contracts=pos.n_micros,
            trade_account=self._trade_account,
        )
        # J11 : Fix P1-1 instrumente via code log (remplace print stderr)
        if not result.sequence_completed or result.orphan_detected_post_cleanup:
            emit_safe(self._log, "BOT4_MONITOR_OCO_ORPHAN_DETECTED",
                      sym=pos.symbol, signal_id=pos.signal_id,
                      direction=pos.direction,
                      completed=result.sequence_completed,
                      orphan_post=result.orphan_detected_post_cleanup)
            if not result.sequence_completed:
                emit_safe(self._log, "BOT4_FLATTEN_INCOMPLETE",
                          sym=pos.symbol, signal_id=pos.signal_id,
                          final_qty_broker=result.final_qty_broker)
            if result.orphan_detected_post_cleanup:
                emit_safe(self._log, "BOT4_FLATTEN_ORPHAN_DETECTED",
                          sym=pos.symbol, signal_id=pos.signal_id,
                          qty_residual=result.final_qty_broker,
                          working_orders="see executor logs")
            # Keep stderr for human debug live (Jackson reads tail logs)
            print(
                f"[Bot4][CRITIQUE] Flatten incomplet/orphan {pos.signal_id} "
                f"({pos.symbol} {pos.direction}) VERIFIER BROKER MANUEL.",
                file=sys.stderr,
            )
        else:
            emit_safe(self._log, "BOT4_FLATTEN_COMPLETE",
                      sym=pos.symbol, signal_id=pos.signal_id,
                      duration_total_ms=result.duration_total_ms,
                      critical_failed=result.critical_steps_failed,
                      cleanup_failed=result.cleanup_steps_failed)

        # Fix C3 review J10 : get_tick_size + get_tick_value centralises
        tick = get_tick_size(pos.symbol)
        tick_value = get_tick_value(pos.symbol)
        sign = 1 if pos.direction == "LONG" else -1
        pnl_ticks = (close_price - pos.entry_price) * sign / tick
        pnl_usd = pnl_ticks * tick_value * pos.n_micros

        # M4 : update cooldown + daily PnL
        self.risk.on_trade_close(
            symbol=pos.symbol, signal_id=pos.signal_id, pnl_usd=pnl_usd,
            exit_reason=close_reason, ts_event_ns=time.time_ns(),
        )
        # J11 : trade_close transition
        _state = self.risk.states.get(pos.symbol)
        emit_safe(self._log, "BOT4_RISK_TRADE_CLOSE",
                  sym=pos.symbol, signal_id=pos.signal_id,
                  pnl_usd=round(pnl_usd, 2), exit_reason=close_reason,
                  consec_sl=_state.consec_sl_count if _state else 0)
        # Fix C4 review J10 : remove sous lock (atomic avec ajout dans _process_symbol)
        with self._positions_lock:
            self.open_positions.pop(pos.signal_id, None)
            # Fix 28/05 BUG#1 : persiste apres pop pour survivre restart
            self._persist_open_positions()

    # -------------------------------------------------------------------------
    # Callbacks DTC (thread _recv_loop legacy)
    # -------------------------------------------------------------------------

    def _on_filled(self, raw: OrderUpdateRaw) -> None:
        """Callback fill DTC TP/SL : comptabilite memoire SANS flatten broker.

        Fix 28/05 (BUG #1 audit) :
        - Le legacy BOT/dtc_connector.py:284,310-311 hardcode prefixes
          MIA_P_/MIA_TP_/MIA_SL_ (send_market_order ne prend pas argument prefix).
          On matche donc sur MIA_TP_ / MIA_SL_ comme Bot 1, pas MIA4_*.
        - Pattern Bot 1 (mia_paper_trader.py:_close_trade from_dtc_callback=True) :
          fill TP/SL = broker deja flat (OCO auto cancel ligne 1173-1194 du legacy).
          NE PAS appeler flatten_position_safely depuis ce callback :
            * deadlock garanti (execution.py:622-623) : flatten utilise blocking
              DTC calls qui attendent _recv_loop, lui-meme bloque dans ce callback.
            * redondant : broker deja flat.

        Sequence :
          1. Match CID -> trouver PositionState (sous _positions_lock)
          2. Compute PnL (tick + tick_value)
          3. risk.on_trade_close (cooldown + daily counters)
          4. emit BOT4_RISK_TRADE_CLOSE (J11 traceability)
          5. pop self.open_positions sous lock

        ATTENTION : execute dans thread _recv_loop legacy. Toute mutation de
        self.open_positions DOIT etre sous self._positions_lock (fix C4).
        """
        cid = raw.client_order_id
        is_tp = cid.startswith("MIA_TP_")
        is_sl = cid.startswith("MIA_SL_")
        if not (is_tp or is_sl):
            return  # parent fill ou autre cid, ignore

        # Trouver position cible sous lock (snapshot atomique)
        with self._positions_lock:
            target_pos: Optional[PositionState] = None
            for pos in self.open_positions.values():
                if (is_tp and pos.tp_cid == cid) or (is_sl and pos.sl_cid == cid):
                    target_pos = pos
                    break

        if target_pos is None:
            # CID inconnu : recovery post-restart, autre bot, re-livraison fill
            emit_safe(self._log, "BOT4_FILL_UNKNOWN_CID",
                      cid=cid, fill_price=raw.fill_price,
                      is_tp=is_tp, is_sl=is_sl)
            return

        close_reason = "TP" if is_tp else "SL"
        close_price = float(raw.fill_price)

        # Comptabilite PnL (broker deja flat via OCO auto-cancel legacy, pas de flatten)
        tick = get_tick_size(target_pos.symbol)
        tick_value = get_tick_value(target_pos.symbol)
        sign = 1 if target_pos.direction == "LONG" else -1
        pnl_ticks = (close_price - target_pos.entry_price) * sign / tick
        pnl_usd = pnl_ticks * tick_value * target_pos.n_micros

        # M4 : update cooldown + daily PnL
        self.risk.on_trade_close(
            symbol=target_pos.symbol, signal_id=target_pos.signal_id,
            pnl_usd=pnl_usd, exit_reason=close_reason,
            ts_event_ns=time.time_ns(),
        )
        # J11 : trade_close transition (source=dtc_fill_callback discrimine du flatten)
        _state = self.risk.states.get(target_pos.symbol)
        emit_safe(self._log, "BOT4_RISK_TRADE_CLOSE",
                  sym=target_pos.symbol, signal_id=target_pos.signal_id,
                  pnl_usd=round(pnl_usd, 2), exit_reason=close_reason,
                  consec_sl=_state.consec_sl_count if _state else 0,
                  source="dtc_fill_callback")
        # Fix C4 review J10 : pop sous lock (atomic avec ajout dans _process_symbol)
        with self._positions_lock:
            self.open_positions.pop(target_pos.signal_id, None)
            # Fix 28/05 BUG#1 : persiste apres pop (callback DTC thread) pour
            # garantir disk = RAM avant prochain restart.
            self._persist_open_positions()

    def _on_cancelled(self, raw: OrderUpdateRaw) -> None:
        """Callback cancel DTC. Log only.

        ATTENTION : execute dans thread _recv_loop legacy.
        """
        pass

    # -------------------------------------------------------------------------
    # State persistant open_positions (fix BUG#1 28/05 : restart-safe)
    # -------------------------------------------------------------------------

    def _persist_open_positions(self) -> None:
        """Sauvegarde self.open_positions sur disque (JSON).

        Appele SOUS self._positions_lock apres chaque mutation (set/pop).
        Best-effort : log warning si echec mais ne casse pas Bot 4.

        Fix 28/05 v2 (diag agent bilan P1#6) : ajout emit BOT4_OPEN_POSITIONS_PERSISTED
        success pour distinguer "jamais appele" de "appele mais 0 positions" cote
        audit J+1. Sans cette trace, impossible de prouver que le patch persistant
        tourne en runtime (cf bilan jour 28/05 : fichier absent VPS, hypothese 0 trade).
        """
        if self._positions_persist_path is None:
            return
        try:
            from dataclasses import asdict
            snapshot = {
                sid: asdict(pos) for sid, pos in self.open_positions.items()
            }
            tmp = self._positions_persist_path.with_suffix(".tmp")
            tmp.write_text(
                __import__("json").dumps(snapshot, indent=2, default=str),
                encoding="utf-8",
            )
            tmp.replace(self._positions_persist_path)
            # 28/05 v2 : trace success pour audit J+1
            emit_safe(self._log, "BOT4_OPEN_POSITIONS_PERSISTED",
                      n_positions=len(self.open_positions),
                      path=str(self._positions_persist_path))
        except Exception as e:
            emit_safe(self._log, "BOT4_PERSIST_FAIL",
                      err=str(e)[:200], n_positions=len(self.open_positions))

    def _reload_open_positions_from_disk(self) -> None:
        """Reload open_positions depuis disk au boot.

        Filtres :
        - Skip si fichier absent (1er boot ou cleanup)
        - Skip si fichier > 24h (corruption ancienne, ne pas re-injecter)
        - Best-effort sur deserialization : warning si fail mais ne crash pas.

        N'effectue PAS de recovery broker query (deadlock risk + complexite).
        Si broker etait flat pendant downtime, le close arrivera via _on_filled
        callback ou via timeout cleanup `_monitor_open_positions`.
        """
        if self._positions_persist_path is None:
            return
        p = self._positions_persist_path
        if not p.exists():
            return
        try:
            age_sec = time.time() - p.stat().st_mtime
            if age_sec > 24 * 3600:
                emit_safe(self._log, "BOT4_RELOAD_SKIP_STALE",
                          age_sec=int(age_sec), path=str(p))
                p.unlink(missing_ok=True)  # cleanup pour eviter re-trigger
                return
            import json as _json
            # FIX 16/06 : utf-8-sig au lieu utf-8 pour gerer BOM silencieusement.
            # Incident : 2 BOT4_RELOAD_FAIL CRITIQUE 16/06 (08:48 + 09:44) cause
            # "Unexpected UTF-8 BOM (decode using utf-8-sig)" sur bot4_open_positions.json
            # ecrit par script PowerShell externe avec BOM. utf-8-sig :
            #   - Avec BOM : strip silencieux
            #   - Sans BOM : comportement identique a utf-8 (backward compat)
            snapshot = _json.loads(p.read_text(encoding="utf-8-sig"))
            n_loaded = 0
            for sid, pos_dict in snapshot.items():
                try:
                    pos = PositionState(**{
                        k: v for k, v in pos_dict.items()
                        if k in PositionState.__dataclass_fields__
                    })
                    self.open_positions[sid] = pos
                    n_loaded += 1
                except Exception as e:
                    emit_safe(self._log, "BOT4_RELOAD_ITEM_FAIL",
                              sid=str(sid)[:40], err=str(e)[:200])
            if n_loaded > 0:
                emit_safe(self._log, "BOT4_OPEN_POSITIONS_RELOADED",
                          n_loaded=n_loaded, age_sec=int(age_sec))
        except Exception as e:
            emit_safe(self._log, "BOT4_RELOAD_FAIL",
                      err=str(e)[:200], path=str(p))

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _symbol_to_contract(self, symbol: str) -> str:
        """Symbol → Sierra Chart contract string.

        TODO Phase 7 (R5 plan) : config dynamique current_contract pour rollover.
        Hardcode juin 2026 (NQM26 / ESM26 / MGCM26).

        02/06 Jackson directive finale "TOUT EN MINI PLUS SIMPLE" :
        Bot 4 trade 1 E-mini NQM26 standard ($1.25/tick) sur Sim4. constants.py
        TICK_VALUE migré MICRO → MINI pour cohérence broker/code (cf INCIDENT_LOG
        entry 27). Bug latent PnL ×2.5 sous-estimé corrigé par migration.
        """
        # Rollover 16/06 : M (juin) -> U (septembre) pour NQ/ES (quarterly).
        # Confirme via le champ `contract` de la data sierra (NQU26/ESU26).
        # NB : l'execution prefere bar["contract"] (auto-rollover) ; ce mapping
        # = fallback si absent. MGC (Gold, cycle different) a verifier au
        # prochain trade MGC (non trade par Bot 4 actuellement).
        mapping = {
            "NQ": "NQU26-CME",          # E-mini NQ septembre 2026 (rollover 16/06)
            "ES": "ESU26-CME",          # E-mini ES septembre 2026 (rollover 16/06)
            "MGC": "MGCM26-CMECOMEX",   # Gold micro - A VERIFIER (cycle non quarterly)
        }
        return mapping.get(symbol, symbol)
