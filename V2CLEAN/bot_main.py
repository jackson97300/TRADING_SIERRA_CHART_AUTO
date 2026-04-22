"""
V2CLEAN — Bot Main (17/04/2026) — Phase 1 DRY-RUN DECISION LOGGER
==================================================================

Orchestrateur pipeline V2CLEAN Phase 1 :
  JSONL DMP → signal_engine → gate_layer → risk_manager (lecture seule) → journal

**IMPORTANT (reviewer-validated)** : Phase 1 = DECISION LOGGER uniquement.
  - PAS d'appel `risk_manager.on_trade_open/on_trade_close` (eviterait fake trades)
  - PAS de DTC connection (Day 6+)
  - PAS de backtest realiste (module separe)
  - Just loggue les decisions PASS / rejections pour valider le pipeline

Garanties :
  - Schema version check fail-loud au 1er bar (3.7.7 attendu)
  - try/except par barre + 3 exceptions consecutives → trip CATASTROPHE
  - Heartbeat 60s (thread daemon) → journal events
  - Signal handlers SIGINT (Win+Linux) / SIGBREAK (Win) / SIGTERM (Linux)
  - Graceful shutdown : trip DAILY + journal.close() + sys.exit(0)
  - Startup event : schema, config, cwd, pid, git_sha si dispo
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except ImportError:
    import pytz
    _ET = pytz.timezone("America/New_York")

from V2CLEAN.common.atr_normalize_live import normalize_atr_features
from V2CLEAN.common.discord_alerter import DiscordAlerter
from V2CLEAN.common.im_features_live import IMBuffer
from V2CLEAN.config import CONFIG, CONFIG_SCHEMA_VERSION, Symbol
from V2CLEAN.gate_layer import GateLayer, GateState
from V2CLEAN.journal.event_journal import EventJournal
from V2CLEAN.risk.kill_switch import KillSwitch, KillSwitchLevel
from V2CLEAN.risk.risk_manager import RiskManager
from V2CLEAN.signal_engine import ModelRegistry, SignalEngine

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from V2CLEAN.execution.order_manager import OrderManager


log = logging.getLogger(__name__)

# Systeme logs V2 projet-wide (Chantier 3 22/04) : emits additionnels
# cote CORE.logging_v2 process="v2clean" (EventJournal natif V2CLEAN garde pour
# compat tests/research, dual write accepte).
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("v2clean_bot_main", process="v2clean")
except Exception:
    _v2log = None


class BotMain:
    """Orchestrateur Phase 1. Decision logger only."""

    MAX_CONSEC_BAR_ERRORS = 3       # Seuil trip CATASTROPHE si pipeline crash
    HEARTBEAT_INTERVAL_SEC = 60      # Thread daemon heartbeat

    MAX_CONSEC_LIVE_SUBMIT_ERRORS = 3   # 3 submits DTC echecs → trip DAILY (reviewer)

    def __init__(
        self,
        clock: Optional[Callable[[], datetime]] = None,
        execution: Optional["OrderManager"] = None,
        # Prebuild pour factory build_live_bot (injection depuis l'exterieur)
        _prebuilt: Optional[tuple] = None,
    ):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._shutdown_requested = threading.Event()

        # Core components — soit crees localement (dry-run), soit injectes (live factory)
        if _prebuilt is not None:
            self.journal, self.kill_switch, self.risk = _prebuilt
        else:
            self.journal = EventJournal(clock=clock)
            self.kill_switch = KillSwitch(
                clock=clock,
                journal=self.journal.as_callback(),
            )
            self.risk = RiskManager(
                kill_switch=self.kill_switch,
                clock=clock,
                journal=self.journal.as_callback(),
            )

        self.registry = ModelRegistry()
        self.signal = SignalEngine(self.registry)
        self.gate_layer = GateLayer()

        # Execution layer (None = dry-run / shadow uniquement)
        self.execution = execution

        # FIX P1 (17/04) : buffer cross-instrument pour calculer les 3 im_*
        # features manquantes dans JSONL live (im_rolling_correlation_10,
        # im_cross_delta_agreement_5, im_open_type_agreement).
        # Sans ca, meta_predict_proba fail en live → bot mode primary-only.
        self.im_buffer = IMBuffer()

        # P0.8 : Discord alerter pour degradation (meta KO, DTC slow, etc.)
        self.discord = DiscordAlerter(username="MIA-V2CLEAN-Bot")

        # P0.2 : counter meta None consecutifs (fail-closed si depasse)
        self._meta_none_consec = 0
        self.MAX_META_NONE_CONSEC = 50      # ~50 bars = ~50 min session active

        # Stats
        self._bars_processed = 0
        self._decisions_pass = 0
        self._decisions_reject = 0
        self._consec_bar_errors = 0
        self._consec_live_submit_errors = 0
        self._last_bar_ts_utc: Optional[datetime] = None
        self._schema_checked = False
        self._kill_switch_flatten_done = False  # flatten unique quand kill trip

        # Heartbeat thread (daemon)
        self._heartbeat_thread: Optional[threading.Thread] = None

        # Install signal handlers
        self._install_signal_handlers()

        # Startup event
        self._log_startup_event()

    # ═════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═════════════════════════════════════════════════════════════════════════

    def start(self) -> None:
        """Demarre heartbeat thread. Idempotent."""
        if self._heartbeat_thread is not None:
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="bot_heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        log.info("bot started, heartbeat thread active")

    def process_bar(self, symbol: Symbol, bar: Mapping[str, Any]) -> None:
        """Traite 1 barre JSONL. Jamais crash — exception = log + continue.

        Apres MAX_CONSEC_BAR_ERRORS consecutives → trip CATASTROPHE.
        """
        try:
            self._process_bar_inner(symbol, bar)
            self._consec_bar_errors = 0  # reset sur success
        except Exception as e:
            self._consec_bar_errors += 1
            log.error(
                "process_bar error for %s (consec=%d): %s",
                symbol.value, self._consec_bar_errors, e,
                exc_info=True,
            )
            self.journal.log_event("bar_processing_error", {
                "symbol": symbol.value,
                "error": str(e),
                "error_type": type(e).__name__,
                "consec_errors": self._consec_bar_errors,
            })
            # V2 log structure (22/04 Chantier 3)
            if _v2log:
                _v2log.emit("BAR_PROCESSING_ERROR", sym=symbol.value,
                            err=f"{type(e).__name__}: {str(e)[:100]}", exc=e)
            if self._consec_bar_errors >= self.MAX_CONSEC_BAR_ERRORS:
                self.kill_switch.trip(
                    KillSwitchLevel.CATASTROPHE,
                    f"{self._consec_bar_errors} consec bar processing errors "
                    f"(last: {type(e).__name__}: {e})",
                    tripped_by="auto",
                )

    # ═════════════════════════════════════════════════════════════════════════
    # TAIL LIVE MODE (Day 7 - reviewer validated)
    # ═════════════════════════════════════════════════════════════════════════

    TAIL_MAX_LINES_PER_POLL = 20              # reviewer : 20 pas 100 (shutdown reactivite)
    TAIL_PERMISSION_RETRY_DELAY_SEC = 0.5     # Windows share violation retry
    TAIL_OFFSETS_RETENTION_HOURS = 48         # purge offsets files > 48h
    TAIL_HEARTBEAT_FILE_INTERVAL_SEC = 30     # healthcheck externe
    TAIL_PREFLIGHT_DMP_STALE_SEC = 120        # si DMP > 2min silent au boot = WARN

    def run_tail_live(
        self,
        es_dir: Optional[Path] = None,
        nq_dir: Optional[Path] = None,
        poll_interval_sec: float = 1.0,
        offset_state_path: Optional[Path] = None,
    ) -> None:
        """Mode tail -f live : lit JSONL DMP au fur et a mesure qu'ils grandissent.

        Reviewer protections Phase 1 :
          - PermissionError Windows retry (race read/write)
          - Shutdown check entre chaque ligne (reactivite < 5s)
          - max_lines=20 per poll (catch-up sans blocage)
          - Offsets retention 48h (robuste aux crashes autour de minuit)
          - Healthcheck file V2CLEAN/LOGS/heartbeat.txt (monitoring externe)
          - Pre-flight models + DMP freshness
        """
        self.start()

        es_dir = Path(es_dir) if es_dir else Path(CONFIG.paths.data_jsonl_es)
        nq_dir = Path(nq_dir) if nq_dir else Path(CONFIG.paths.data_jsonl_nq)
        offset_state_path = (
            Path(offset_state_path) if offset_state_path
            else Path(CONFIG.paths.v2clean_state) / "tail_offsets.json"
        )
        healthcheck_path = Path(CONFIG.paths.v2clean_logs) / "heartbeat.txt"

        # Pre-flight checks (reviewer manque #4 + #5)
        if not self._preflight_checks(es_dir, nq_dir):
            log.error("pre-flight checks failed — aborting tail_live")
            # V2 log : preflight fail = CRITIQUE (ne peut pas demarrer)
            if _v2log:
                _v2log.emit("BOOT_FAIL_PREFLIGHT", check="preflight_tail_live")
            self.shutdown(reason="preflight_failed")
            return

        offsets = self._load_tail_offsets(offset_state_path)
        last_heartbeat_file_write = 0.0

        self.journal.log_event("tail_live_started", {
            "es_dir": str(es_dir),
            "nq_dir": str(nq_dir),
            "poll_interval_sec": poll_interval_sec,
            "live_execution": self.execution is not None,
            "shadow_symbols": [s.value for s in CONFIG.shadow_symbols],
        })
        # V2 log : BOOT_START V2CLEAN tail live mode
        if _v2log:
            _v2log.emit("BOOT_START", component="v2clean_tail_live",
                        version="V2CLEAN", pid=os.getpid())

        try:
            while not self._shutdown_requested.is_set():
                ts_utc = self._clock()
                ts_et = ts_utc.astimezone(_ET)
                date_str = ts_et.strftime("%Y%m%d")

                # Boucle sur ES + NQ
                for symbol, dir_path in ((Symbol.ES, es_dir), (Symbol.NQ, nq_dir)):
                    if self._shutdown_requested.is_set():
                        break
                    jsonl_path = dir_path / f"{date_str}_{symbol.value}.jsonl"
                    if not jsonl_path.exists():
                        continue

                    path_key = str(jsonl_path)
                    offset = offsets.get(path_key, 0)
                    new_offset = self._process_tail_lines(jsonl_path, symbol, offset)

                    if new_offset != offset:
                        offsets[path_key] = new_offset
                        self._save_tail_offsets(offset_state_path, offsets)

                # Healthcheck file (toutes 30s)
                now = time.time()
                if now - last_heartbeat_file_write >= self.TAIL_HEARTBEAT_FILE_INTERVAL_SEC:
                    self._write_healthcheck(healthcheck_path)
                    last_heartbeat_file_write = now

                # Purge offsets anciens (>48h)
                if self._bars_processed % 1000 == 0:
                    offsets = self._purge_stale_offsets(offsets)

                # Wait interruptible
                if self._shutdown_requested.wait(timeout=poll_interval_sec):
                    break

        except KeyboardInterrupt:
            log.info("KeyboardInterrupt received")
        except Exception as e:
            log.error("run_tail_live fatal: %s", e, exc_info=True)
            self.journal.log_event("tail_live_fatal", {
                "error": str(e), "error_type": type(e).__name__,
            })
            # V2 log : crash fatal tail live (CRITIQUE + stacktrace)
            if _v2log:
                _v2log.emit("BOT_CRASH", exc_type=type(e).__name__,
                            exc_msg=str(e)[:200], exc=e)
        finally:
            # Sauvegarder offsets finals avant shutdown
            try:
                self._save_tail_offsets(offset_state_path, offsets)
            except Exception as e:
                log.error("final offset save failed: %s", e)
            self.shutdown(reason="tail_live_exit")

    def _preflight_checks(self, es_dir: Path, nq_dir: Path) -> bool:
        """Verifications critiques avant de demarrer tail_live."""
        # 1. Models .pkl presents (reviewer manque #5)
        try:
            # ModelRegistry deja instancie dans __init__ ; verifier qu'il a les fichiers
            models_dir = Path(CONFIG.paths.models_dir)
            for sym in CONFIG.enabled_symbols:
                if sym in CONFIG.shadow_symbols:
                    continue  # shadow : pas d'execution, pas besoin de models
                for side in ("buy", "sell"):
                    model_path = models_dir / f"{sym.value}_{side}_model.pkl"
                    if not model_path.exists():
                        log.error("missing model: %s", model_path)
                        return False
            log.info("models preflight OK")
        except Exception as e:
            log.error("models preflight check failed: %s", e)
            return False

        # 2. DMP freshness : dernier JSONL ES existe et recent (reviewer manque #4)
        try:
            ts_et = self._clock().astimezone(_ET)
            date_str = ts_et.strftime("%Y%m%d")
            es_path = es_dir / f"{date_str}_ES.jsonl"
            if es_path.exists():
                mtime = es_path.stat().st_mtime
                age_sec = time.time() - mtime
                if age_sec > self.TAIL_PREFLIGHT_DMP_STALE_SEC:
                    log.warning(
                        "DMP JSONL stale: %s age=%.1fs (> %ds) — DMP down?",
                        es_path.name, age_sec, self.TAIL_PREFLIGHT_DMP_STALE_SEC,
                    )
                    # Ne pas abort : peut etre hors-session
            else:
                log.warning("no ES JSONL for today yet (%s)", es_path.name)
        except Exception as e:
            log.warning("DMP freshness check failed: %s", e)

        return True

    def _process_tail_lines(
        self, path: Path, symbol: Symbol, offset: int,
    ) -> int:
        """Lit les nouvelles lignes depuis offset, process chaque.

        Reviewer protections :
          - max_lines=20 per poll (catch-up mais reactivite shutdown)
          - check shutdown entre CHAQUE ligne (reviewer defaut #3)
          - PermissionError retry Windows (reviewer defaut #1)
          - Ligne incomplete (no \\n) → stop sans increment offset
        """
        for retry in range(3):
            try:
                with path.open("rb") as f:
                    f.seek(offset)
                    lines_processed = 0
                    while lines_processed < self.TAIL_MAX_LINES_PER_POLL:
                        # Check shutdown entre chaque ligne (reviewer obligatoire)
                        if self._shutdown_requested.is_set():
                            break

                        line = f.readline()
                        if not line:
                            break
                        if not line.endswith(b"\n"):
                            # Ligne incomplete (DMP en train d'ecrire) → stop ici
                            break

                        offset = f.tell()
                        try:
                            bar = json.loads(line.decode("utf-8", errors="replace"))
                        except json.JSONDecodeError as e:
                            log.warning(
                                "skip malformed line %s offset=%d: %s",
                                path.name, offset, e,
                            )
                            continue

                        self.process_bar(symbol, bar)
                        lines_processed += 1
                return offset
            except PermissionError as e:
                # Windows : DMP est en train d'ecrire, le file est locked exclusive
                # Retry apres courte pause (reviewer defaut #1)
                log.debug(
                    "PermissionError on %s (retry %d/3): %s",
                    path.name, retry + 1, e,
                )
                if self._shutdown_requested.wait(timeout=self.TAIL_PERMISSION_RETRY_DELAY_SEC):
                    break
            except OSError as e:
                log.error("read error on %s: %s", path, e)
                break
        return offset

    def _load_tail_offsets(self, state_path: Path) -> dict:
        if not state_path.exists():
            return {}
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("tail_offsets corrupted (%s), starting fresh", e)
            return {}

    def _save_tail_offsets(self, state_path: Path, offsets: dict) -> None:
        """Atomic save : tmp + os.replace."""
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(offsets, indent=2), encoding="utf-8")
            os.replace(tmp, state_path)
        except OSError as e:
            log.error("save tail_offsets failed: %s", e)

    def _purge_stale_offsets(self, offsets: dict) -> dict:
        """Retire les offsets de fichiers > 48h (reviewer defaut #2)."""
        now = time.time()
        threshold = self.TAIL_OFFSETS_RETENTION_HOURS * 3600
        cleaned = {}
        for path_str, off in offsets.items():
            try:
                p = Path(path_str)
                if p.exists() and (now - p.stat().st_mtime) < threshold:
                    cleaned[path_str] = off
            except (OSError, ValueError):
                continue
        if len(cleaned) < len(offsets):
            log.info("purged %d stale offset entries", len(offsets) - len(cleaned))
        return cleaned

    def _write_healthcheck(self, path: Path) -> None:
        """Healthcheck externe : fichier contenant ts + stats."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            active, reason = self.risk.is_kill_switch_active()
            content = json.dumps({
                "ts_utc": self._clock().isoformat(),
                "bars_processed": self._bars_processed,
                "decisions_pass": self._decisions_pass,
                "decisions_reject": self._decisions_reject,
                "kill_switch_active": active,
                "kill_switch_reason": reason,
                "last_bar_ts_utc": (
                    self._last_bar_ts_utc.isoformat()
                    if self._last_bar_ts_utc else None
                ),
                "journal_degraded": self.journal.degraded,
                "execution_wired": self.execution is not None,
            }, indent=2)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            log.warning("healthcheck write failed: %s", e)

    def run_from_jsonl(
        self,
        es_path: Optional[Path] = None,
        nq_path: Optional[Path] = None,
    ) -> None:
        """Stream 2 JSONL ES/NQ par timestamp, process chaque barre.

        Batch EOF-terminated. Live tail -f = Phase 2.
        """
        self.start()
        try:
            for symbol, bar in _merge_jsonl_by_timestamp(es_path, nq_path):
                if self._shutdown_requested.is_set():
                    log.info("shutdown requested, stopping bar stream")
                    break
                self.process_bar(symbol, bar)
        finally:
            self.shutdown(reason="run_from_jsonl EOF")

    def shutdown(self, reason: str = "manual") -> None:
        """Graceful shutdown : stop heartbeat + log + close journal."""
        if self._shutdown_requested.is_set():
            return
        self._shutdown_requested.set()

        log.info("shutdown initiated: %s", reason)

        # REVIEWER : flatten positions si execution live active avant close journal
        if self.execution is not None:
            try:
                n = self.execution.close_all_positions(reason=f"shutdown:{reason}")
                if n > 0:
                    log.warning("shutdown flatten %d positions", n)
            except Exception as e:
                log.error("shutdown flatten failed: %s", e)

        # Stop heartbeat thread avant close journal (evite write apres close)
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
            if self._heartbeat_thread.is_alive():
                log.warning("heartbeat thread did not stop within 2s")

        try:
            self.journal.log_event("bot_shutdown", {
                "reason": reason,
                "bars_processed": self._bars_processed,
                "decisions_pass": self._decisions_pass,
                "decisions_reject": self._decisions_reject,
            })
        except Exception as e:
            log.error("shutdown journal log failed: %s", e)

        try:
            self.journal.close()
        except Exception as e:
            log.error("journal close failed: %s", e)

    # ═════════════════════════════════════════════════════════════════════════
    # INTERNAL
    # ═════════════════════════════════════════════════════════════════════════

    def _process_bar_inner(self, symbol: Symbol, bar: Mapping[str, Any]) -> None:
        # 1. Schema check au 1er bar (fail-loud)
        if not self._schema_checked:
            self._check_schema(bar)
            self._schema_checked = True

        # 2. Extract ts + price
        ts_utc = _extract_ts_utc(bar)
        price = _extract_price(bar)
        if ts_utc is None or price is None:
            raise ValueError(f"bar missing ts or price: keys={list(bar)[:10]}")

        self._last_bar_ts_utc = ts_utc

        # 3. Risk manager: bar tick (daily reset + current_price)
        self.risk.on_bar_tick(symbol, price, ts_utc)

        # 3b. FIX P1 : enrichir bar avec im_* features cross-instrument.
        # Buffer update + compute avant predict pour que meta_labeler fonctionne.
        self.im_buffer.update(symbol.value, bar)
        im_features = self.im_buffer.compute(symbol.value)
        # Bar est dict mutable (parse JSON), on enrichit in-place
        if isinstance(bar, dict):
            for k, v in im_features.items():
                if k not in bar or bar.get(k) is None:
                    bar[k] = v

            # 3c. FIX P0bis.7 (17/04) : recalcul dist_*_atr depuis dist_*_ticks + atr.
            # Feature-engineer audit : dist_1d_min/max_atr (ρ=0.28, 0.24 top modele)
            # absentes live → 30% edge perdu. Division triviale.
            normalize_atr_features(bar)

        # 4. Kill switch check
        active, reason = self.risk.is_kill_switch_active()
        if active:
            # REVIEWER BLOCKER funded : si execution active et positions ouvertes
            # → close_all_positions (eviter positions residuelles quand kill_switch trip)
            if self.execution is not None and not self._kill_switch_flatten_done:
                try:
                    n = self.execution.close_all_positions(
                        reason=f"kill_switch_active: {reason}"
                    )
                    if n > 0:
                        log.warning("kill_switch active → flatten %d positions", n)
                    self._kill_switch_flatten_done = True
                except Exception as e:
                    log.error("kill_switch flatten failed: %s", e)

            # Log rarement (evite spam). On loggue 1 fois toutes les 100 bars.
            if self._bars_processed % 100 == 0:
                self.journal.log_event("bar_skipped_kill_switch", {
                    "symbol": symbol.value,
                    "reason": reason,
                    "ts_utc": ts_utc.isoformat(),
                })
            self._bars_processed += 1
            return

        # Reset kill_switch_flatten flag quand kill_switch relifte (auto daily reset)
        self._kill_switch_flatten_done = False

        # 4b. SYNCHRO #4 : flatten funded window (16:55-17:00 ET)
        # Force close positions ouvertes, bloque nouveaux trades dans la fenetre.
        ts_et = ts_utc.astimezone(_ET)
        ts_et_minute = ts_et.hour * 60 + ts_et.minute
        if _is_funded_flatten_window(ts_et_minute):
            pos_state = self.risk.build_position_state(symbol)
            if pos_state.has_open_position:
                if self.execution is not None:
                    # Mode LIVE : force close via DTC
                    try:
                        ok = self.execution.close_position_market(
                            symbol, reason="funded_flatten_1655_ET",
                        )
                        self.journal.log_event("funded_flatten_executed", {
                            "symbol": symbol.value,
                            "ts_et": ts_et.strftime("%H:%M"),
                            "success": ok,
                        })
                    except Exception as e:
                        log.error("funded flatten failed: %s", e)
                else:
                    # Mode dry-run : log only
                    self.journal.log_event("funded_flatten_required", {
                        "symbol": symbol.value,
                        "ts_et": ts_et.strftime("%H:%M"),
                        "direction": (pos_state.open_position_direction.value
                                      if pos_state.open_position_direction else None),
                        "phase": "dry_run (no execution wired)",
                    })
            # Bloquer tout nouveau trade dans la fenetre
            self._bars_processed += 1
            return

        # 5. Predict ML (peut raise PredictionError → catch externe)
        ml_scores = self.signal.predict(symbol, bar)

        # P0.2 FAIL-CLOSED : si meta attendu mais None, compter streak.
        # Si > MAX_META_NONE_CONSEC → trip kill_switch + alerte Discord
        bundle = self.signal.registry.get(symbol, "buy")
        if bundle.has_meta and ml_scores.p_meta is None:
            self._meta_none_consec += 1
            if self._meta_none_consec >= self.MAX_META_NONE_CONSEC:
                reason = (
                    f"META KO silencieux : p_meta=None depuis "
                    f"{self._meta_none_consec} bars consecutifs (symbol={symbol.value})"
                )
                log.error(reason)
                self.kill_switch.trip(
                    KillSwitchLevel.DAILY, reason=reason, tripped_by="auto",
                )
                self.discord.send_async(
                    "alertes", "BOT META KO — TRIP DAILY", reason, level="CRITICAL",
                    fields={"symbol": symbol.value, "n_missing_buy": ml_scores.n_missing_buy},
                )
                self._meta_none_consec = 0  # reset apres trip (evite spam)
        else:
            self._meta_none_consec = 0

        # 6. Build GateState
        pos_state = self.risk.build_position_state(symbol)
        vix_level = float(bar.get("vix_level", 0.0) or 0.0)

        gate_state = GateState(
            timestamp=ts_utc,
            symbol=symbol,
            features_row=bar,
            ml_scores=ml_scores.to_dict(),
            position_state=pos_state,
            vix_level=vix_level,
        )

        # 7. Evaluate gates
        gate_result = self.gate_layer.evaluate(gate_state)

        # 8. Log result + regime GEX metadata (SYNCHRO #6)
        gex_metadata = _extract_gex_metadata(bar)
        shadow = symbol in CONFIG.shadow_symbols
        live_exec_active = self.execution is not None and not shadow

        if gate_result.all_passed:
            self._decisions_pass += 1

            if live_exec_active:
                # MODE LIVE : submit bracket reel via DTC
                self._submit_live_bracket(
                    symbol=symbol,
                    direction=gate_result.decision,
                    entry_price_hint=price,
                    ts_utc=ts_utc,
                    ml_scores=ml_scores,
                    gate_result=gate_result,
                    gex_metadata=gex_metadata,
                )
            else:
                # Mode dry-run ou shadow : log only
                self.journal.log_trade({
                    "mode": "shadow_decision_only" if shadow else "dry_run_decision_only",
                    "shadow": shadow,
                    "trade_id": f"{'shadow' if shadow else 'dry'}_{symbol.value}_{int(ts_utc.timestamp())}",
                    "symbol": symbol.value,
                    "direction": gate_result.decision.value,
                    "entry_price": price,
                    "entry_ts_utc": ts_utc.isoformat(),
                    "ml_scores": ml_scores.to_dict(),
                    "gate_result": gate_result.to_json(),
                    "gex_regime": gex_metadata,
                })
        else:
            self._decisions_reject += 1
            self.journal.log_rejection(gate_result, {
                "symbol": symbol.value,
                "shadow": shadow,
                "ts_utc": ts_utc.isoformat(),
                "price": price,
                "gex_regime": gex_metadata,
            })

        self._bars_processed += 1

    def _submit_live_bracket(
        self,
        symbol: Symbol,
        direction,
        entry_price_hint: float,
        ts_utc: datetime,
        ml_scores,
        gate_result,
        gex_metadata: dict,
    ) -> None:
        """Submit bracket reel via OrderManager. Gere 3 submits DTC echec consec → trip DAILY."""
        assert self.execution is not None
        tp_cfg = CONFIG.tp_sl[symbol]
        try:
            result = self.execution.submit_bracket(
                symbol=symbol,
                direction=direction,
                qty=1,                                  # Phase 1 : 1 contract micro
                tp_ticks=tp_cfg.tp_ticks,
                sl_ticks=tp_cfg.sl_ticks,
                timeout_fill_sec=15,
            )
        except Exception as e:
            self._consec_live_submit_errors += 1
            log.error(
                "live bracket submit failed (%s consec): %s",
                self._consec_live_submit_errors, e,
            )
            self.journal.log_event("live_submit_failed", {
                "symbol": symbol.value,
                "direction": direction.value,
                "error": str(e),
                "error_type": type(e).__name__,
                "consec_errors": self._consec_live_submit_errors,
            })
            # 3 erreurs consec → trip DAILY (pas CATASTROPHE, DTC peut rebondir)
            if self._consec_live_submit_errors >= self.MAX_CONSEC_LIVE_SUBMIT_ERRORS:
                self.kill_switch.trip(
                    KillSwitchLevel.DAILY,
                    f"{self._consec_live_submit_errors} consec live submit failures",
                    tripped_by="auto",
                )
            return

        # Success : reset consec counter
        self._consec_live_submit_errors = 0

        if result.parent_filled:
            self.journal.log_trade({
                "mode": "live",
                "trade_id": result.trade_id,
                "symbol": symbol.value,
                "direction": direction.value,
                "entry_price": result.entry_price,
                "entry_ts_utc": result.entry_ts.isoformat(),
                "tp_cid": result.tp_cid,
                "sl_cid": result.sl_cid,
                "ml_scores": ml_scores.to_dict(),
                "gate_result": gate_result.to_json(),
                "gex_regime": gex_metadata,
            })
        else:
            # Parent pas fillé (timeout) — deja loggé dans journal par OrderManager
            log.warning("live bracket parent not filled: trade_id=%s", result.trade_id)

    def _check_schema(self, bar: Mapping[str, Any]) -> None:
        """Fail-loud si schema version JSONL != CONFIG.data.expected_schema_version."""
        expected = CONFIG.data.expected_schema_version
        actual = bar.get("schema_version") or bar.get("dmp_schema") or bar.get("version")
        if actual is None:
            log.warning("bar has no schema_version field — proceeding (pre-3.7.x bar?)")
            return
        if str(actual) != expected:
            raise RuntimeError(
                f"schema mismatch: JSONL has {actual!r}, config expects {expected!r}. "
                f"Fail-loud to avoid silent feature drift."
            )
        log.info("schema version OK: %s", actual)

    def _log_startup_event(self) -> None:
        """Event startup : PID, cwd, schema, git sha, config snapshot."""
        try:
            git_sha = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode().strip()
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            git_sha = "unknown"

        self.journal.log_event("bot_startup", {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "expected_dmp_schema": CONFIG.data.expected_schema_version,
            "mode": CONFIG.mode.value,
            "session_mode": CONFIG.session.mode,
            "enabled_symbols": [s.value for s in CONFIG.enabled_symbols],
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "python_version": sys.version.split()[0],
            "git_sha": git_sha,
            "ts_utc": self._clock().isoformat(),
        })

    def _heartbeat_loop(self) -> None:
        """Daemon thread : 1 heartbeat toutes les 60s."""
        while not self._shutdown_requested.is_set():
            if self._shutdown_requested.wait(timeout=self.HEARTBEAT_INTERVAL_SEC):
                break
            try:
                # Uniformise avec process_bar() : toujours passer par risk_manager
                active, reason = self.risk.is_kill_switch_active()
                self.journal.log_event("heartbeat", {
                    "bars_processed": self._bars_processed,
                    "decisions_pass": self._decisions_pass,
                    "decisions_reject": self._decisions_reject,
                    "last_bar_ts_utc": (
                        self._last_bar_ts_utc.isoformat()
                        if self._last_bar_ts_utc else None
                    ),
                    "kill_switch_active": active,
                    "kill_switch_reason": reason,
                    "journal_degraded": self.journal.degraded,
                })
                # V2 log : heartbeat V2CLEAN (consomme par BOT/mia_watchdog externe)
                if _v2log:
                    _v2log.emit("HEARTBEAT_V2CLEAN")
            except Exception as e:
                log.error("heartbeat failed: %s", e)

    def _install_signal_handlers(self) -> None:
        """SIGINT + SIGTERM (Linux) / SIGBREAK (Windows) → graceful shutdown."""
        def handler(signum, frame):
            log.warning("signal %d received, shutting down", signum)
            self.shutdown(reason=f"signal_{signum}")

        try:
            signal.signal(signal.SIGINT, handler)
        except (ValueError, AttributeError):
            pass
        # SIGTERM (Linux)
        if hasattr(signal, "SIGTERM"):
            try:
                signal.signal(signal.SIGTERM, handler)
            except (ValueError, AttributeError):
                pass
        # SIGBREAK (Windows Ctrl+Break)
        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, handler)
            except (ValueError, AttributeError):
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_ts_utc(bar: Mapping[str, Any]) -> Optional[datetime]:
    """Extract timestamp UTC from bar dict (multiple key conventions)."""
    for key in ("ts", "timestamp", "t"):
        val = bar.get(key)
        if val is None:
            continue
        try:
            # ms epoch
            if isinstance(val, (int, float)):
                return datetime.fromtimestamp(val / 1000, tz=timezone.utc)
            # ISO string
            if isinstance(val, str):
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
        except (ValueError, OSError):
            continue
    return None


def _extract_price(bar: Mapping[str, Any]) -> Optional[float]:
    """Extract close/last price from bar dict."""
    for key in ("close", "c", "last_price", "price", "bar_close"):
        val = bar.get(key)
        if val is None:
            continue
        try:
            v = float(val)
            if v > 0:
                return v
        except (ValueError, TypeError):
            continue
    return None


def _extract_gex_metadata(bar: Mapping[str, Any]) -> dict:
    """SYNCHRO #6 : extract regime GEX pour logging post-paper analysis.

    Finding 15/04 (feedback_regime_gex_finding.md) :
    SELL ES +56% PF gap GEX- (3.68) vs GEX+ (2.36).
    En Phase 1 on LOG seulement, on ne gate pas encore.
    """
    gex_net = bar.get("mq_net_gex") or bar.get("gex_net") or bar.get("net_gex")
    total_gex = bar.get("mq_total_gex") or bar.get("total_gex")
    bool_flip = bar.get("bool_gex_flip_zone")
    gamma_cond = bar.get("mq_gamma_condition") or bar.get("gamma_condition")

    regime: Optional[str] = None
    if isinstance(gex_net, (int, float)):
        try:
            v = float(gex_net)
            regime = "positive" if v > 0 else ("negative" if v < 0 else "zero")
        except (TypeError, ValueError):
            pass

    return {
        "gex_net": float(gex_net) if isinstance(gex_net, (int, float)) else None,
        "gex_total": float(total_gex) if isinstance(total_gex, (int, float)) else None,
        "gex_regime": regime,
        "flip_zone": bool(bool_flip) if bool_flip is not None else None,
        "gamma_condition": gamma_cond,
    }


def _is_funded_flatten_window(ts_et_minute: int) -> bool:
    """SYNCHRO #4 : detecte si on est dans la fenetre de flatten force funded.

    16:55 ET et au-dela jusqu'a halt (17:00 ET) → force close positions.
    Meme en mode 24h, obligatoire pour safety TopStep funded (gap halt CME 17-18 ET).
    """
    sess = CONFIG.session
    if not sess.funded_force_flatten:
        return False
    # Fenetre : [funded_flatten_minute_et, daily_halt_start_minute_et[
    return sess.funded_flatten_minute_et <= ts_et_minute < sess.daily_halt_start_minute_et


def _merge_jsonl_by_timestamp(
    es_path: Optional[Path],
    nq_path: Optional[Path],
) -> Iterator[tuple[Symbol, dict]]:
    """Heap-merge 2 JSONL files par timestamp (ts ms epoch).

    Yields (symbol, bar_dict) dans l'ordre chronologique.
    Skip lignes malformees (log warning).
    """
    import heapq

    def _iter_jsonl(path: Path, symbol: Symbol):
        with path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    bar = json.loads(line)
                except json.JSONDecodeError as e:
                    log.warning("skip malformed line %s:%d: %s", path, line_no, e)
                    continue
                ts = _extract_ts_utc(bar)
                if ts is None:
                    continue
                yield (ts, symbol, bar)

    streams = []
    if es_path and es_path.exists():
        streams.append(_iter_jsonl(es_path, Symbol.ES))
    if nq_path and nq_path.exists():
        streams.append(_iter_jsonl(nq_path, Symbol.NQ))

    if not streams:
        log.warning("no JSONL streams to merge")
        return

    # heapq.merge requires key on items
    for ts, symbol, bar in heapq.merge(*streams, key=lambda x: x[0]):
        yield (symbol, bar)


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def build_dryrun_bot(clock: Optional[Callable[[], datetime]] = None) -> "BotMain":
    """Factory : bot en mode decision-logger-only (pas d'execution DTC)."""
    return BotMain(clock=clock, execution=None)


def build_live_bot(
    dtc_host: str = "127.0.0.1",
    dtc_port: int = 11099,
    dtc_username: str = "MIA_V2CLEAN",
    dtc_password: str = "",
    trade_account: str = "SIM-PAPER",
    clock: Optional[Callable[[], datetime]] = None,
) -> "BotMain":
    """Factory : bot en mode LIVE avec OrderManager + DTC connection.

    REVIEWER Q-A : factory externe necessaire car OrderManager a besoin de
    risk/journal deja crees. On construit les composants dans l'ordre puis
    on injecte dans BotMain via _prebuilt.

    P0.7 (17/04) : SIM whitelist. Phase 1-2 : refuse LIVE-CASH accidentel.
    """
    # SAFETY : whitelist trade_account Phase 1-2 paper uniquement
    # Accepte uniquement "SIM*", "Sim*", "SIM-PAPER", "Sim3", etc.
    if not (trade_account.upper().startswith("SIM")):
        raise RuntimeError(
            f"REFUSING START : trade_account={trade_account!r} not a SIM account. "
            f"Phase 1-2 paper only. Set MIA_TRADE_ACCOUNT=Sim3 or similar."
        )
    log.warning("build_live_bot : trade_account=%s (SIM whitelisted)", trade_account)
    from V2CLEAN.execution.dtc_connector import DTCConfig, DTCConnector
    from V2CLEAN.execution.order_manager import OrderManager

    # 1. Core components
    journal = EventJournal(clock=clock)
    kill_switch = KillSwitch(clock=clock, journal=journal.as_callback())
    risk = RiskManager(
        kill_switch=kill_switch, clock=clock, journal=journal.as_callback(),
    )

    # 2. DTC + OrderManager (connect avant de wrapper)
    dtc_cfg = DTCConfig(
        host=dtc_host,
        port=dtc_port,
        username=dtc_username,
        password=dtc_password,
    )
    dtc = DTCConnector(dtc_cfg)
    dtc.connect()

    execution_state_path = Path(CONFIG.paths.v2clean_state) / "execution_state.json"
    execution = OrderManager(
        dtc=dtc,
        risk=risk,
        journal=journal,
        trade_account=trade_account,
        state_path=execution_state_path,
    )

    # 3. BotMain avec prebuild injection (evite chicken-and-egg)
    return BotMain(clock=clock, execution=execution,
                   _prebuilt=(journal, kill_switch, risk))


def main() -> int:
    """Entry point CLI.

    Usage :
        # Mode batch (EOF-terminated) :
        python -m V2CLEAN.bot_main [es_jsonl] [nq_jsonl]

        # Mode tail live (Day 7) :
        python -m V2CLEAN.bot_main --tail

    Mode LIVE execution si env MIA_BOT_LIVE_EXECUTION=1 (sinon dry-run).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    args = sys.argv[1:]
    tail_mode = "--tail" in args
    if tail_mode:
        args = [a for a in args if a != "--tail"]

    live = os.getenv("MIA_BOT_LIVE_EXECUTION", "0") == "1"
    if live:
        log.warning("=== MODE LIVE EXECUTION (DTC will submit real orders) ===")
        bot = build_live_bot(
            dtc_host=os.getenv("MIA_DTC_HOST", "127.0.0.1"),
            dtc_password=os.getenv("MIA_DTC_PASSWORD", ""),
            trade_account=os.getenv("MIA_TRADE_ACCOUNT", "SIM-PAPER"),
        )
    else:
        log.info("=== MODE DRY-RUN (decision logger only) ===")
        bot = build_dryrun_bot()

    try:
        if tail_mode:
            log.info("=== MODE TAIL LIVE (reads JSONL as DMP writes) ===")
            bot.run_tail_live()
        else:
            es_path = Path(args[0]) if len(args) > 0 else None
            nq_path = Path(args[1]) if len(args) > 1 else None
            bot.run_from_jsonl(es_path=es_path, nq_path=nq_path)
    except KeyboardInterrupt:
        bot.shutdown(reason="keyboard_interrupt")
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["BotMain"]
