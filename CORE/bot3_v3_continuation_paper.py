"""bot3_v3_continuation_paper.py — Paper trader Bot 3 v3 Continuation NQ Sim1.

Backtest baseline (130j MenthorQ propre) : n=1611 WR43% PF1.045 DSR0.21
PF_min_fold=0.75. Pattern Wyckoff phase E breakout+retest+confirmation.

Architecture :
  - Lit JSONL live_enriched (lag 60s) via LiveEnrichedReader
  - Engine Bot3V3Engine (state machine 4 etats, 22 levels V1+V4)
  - DTC bracket OCO via dtc_connector (pattern Bot 3 valide)
  - Anti-orphan V2 (9 etapes) via bot3_paper_common.force_close_market
  - Logger JSONL dedie LOGS/bot3_v3/ via Bot3V3Logger
  - Codes log_catalog BOT3_V3_* via logging_v2

Kill switches ENV :
  MIA_BOT3_V3_ENABLED=0/1            (default 0 = process exit immediat)
  MIA_BOT3_V3_DRY_RUN=0/1            (default 1 = log only, pas DTC)
  MIA_BOT3_V3_TRADE_ACCOUNT=Sim1     (Bot 3 v3 dedie)
  MIA_BOT3_V3_SYMBOLS=NQ             (NQ only en MVP, ES NOGO empirique)

Integration :
  Instancie + wire depuis databento_paper_trader_v2.py.
  paper_v2 appelle bot3_v3.poll_cycle() a chaque iteration main loop.

Source data : JSONL live_enriched (decision Jackson 23/05).

Cycle de vie trade :
  1. process_bar(row) → engine.process_bar → Optional[EntryDecision]
  2. Si EntryDecision : check risk gates → place_bracket_dtc(Sim1)
  3. Register cid_index pour routage fills via _handle_dtc_fill
  4. ORDER_UPDATE Type 301 SL/TP fill → handle_dtc_fill → close logs
  5. Timeout 360 bars : force_close_market (sequence anti-orphan V2 9 etapes)

Auteur : MIA Trading V2 v1.0 (2026-05-24)
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

from bot3_v3_continuation_engine import (
    Bot3V3Engine, Bot3V3Params, EntryDecision,
    build_default_level_defs,
)
from bot3_v3v4_logger import Bot3V3Logger
from bot3_paper_common import (
    SYMBOL_TO_CONTRACT, TICK_BY_SYMBOL, TICK_VALUE_USD,
    DTC_BUY, DTC_SELL,
    place_bracket_dtc, force_close_market, query_open_orders_by_symbol,
    check_risk_gates, should_emit_heartbeat, compute_pnl_R_usd,
    check_post_trade_cooldown,
    DEFAULT_RISK_MAX_SL_CONSEC, DEFAULT_RISK_COOLDOWN_MIN,
    DEFAULT_RISK_MAX_DD_USD, DEFAULT_HEARTBEAT_INTERVAL_MIN,
)

# Etape 2 sprint stabilite Bot 3 v3 (09/06 soir) : persistance positions + reconcile DTC
from bot_persistance import (
    PositionPersistance, BotStateLoadError, ReconcileReport,
)

# Constantes etape 2 sprint stabilite
FORCE_FLAT_FLAG_PATH = ROOT / "STATE" / "bot3_v3" / "force_flat.flag"
POLL_SKIP_HALT_EMIT_INTERVAL_SEC = 300  # rate-limit emit 5 min
POLL_SKIP_RECONCILE_EMIT_INTERVAL_SEC = 60  # rate-limit emit 1 min

# Source data switch (2026-06-07 Phase 1 cutover Sierra).
# MIA_BOT3_V3_SOURCE = "live_enriched" (default, lag 60s + bug delta_bar Databento)
#                       | "sierra"     (cutover Sierra DMP direct, lag 5-10s, INCIDENT_LOG 37)
# Bot3V3SierraReader mimique l'interface LiveEnrichedReader (load_rolling_window,
# get_last_bar_age_seconds, is_stale, warn_stale_sec attr). Switch transparent
# pour l'engine + le paper code en aval.
_SOURCE = os.environ.get("MIA_BOT3_V3_SOURCE", "live_enriched").strip().lower()
if _SOURCE == "sierra":
    from bot3_v3_sierra_reader import Bot3V3SierraReader as LiveEnrichedReader
else:
    from live_enriched_reader import LiveEnrichedReader

try:
    from logging_v2 import get_logger
    _v2log = get_logger("bot3_v3_paper", process="paper_v2")
except ImportError:
    _v2log = None


__version__ = "1.0.0"

BOT_LABEL = "BOT3_V3"
CID_PREFIX = "BOT3_V3"

# Timeout position post-entry (360 bars = 6h en 1-min, conservateur)
TIMEOUT_BARS_POSITION = 360


def _emit(code: str, **ctx) -> None:
    """Helper emit log_catalog via logging_v2 (fail-soft)."""
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception as e:
            print(f"[BOT3_V3_EMIT_FAIL] code={code} err={e}", file=sys.stderr)


class Bot3V3ContinuationPaper:
    """Paper trader Bot 3 v3 Continuation NQ Sim1.

    Lifecycle :
        1. __init__(config) : load config + init engine + reader + logger
        2. boot_ready() : emit BOT3_V3_BOOT_READY apres validation pre-flight
        3. poll_cycle() : appele depuis paper_v2 main loop
        4. shutdown(reason) : force_close positions + cancel orders

    Etat persistant :
        - position : Optional[dict] (1 position max NQ)
        - current_signal_id : str (lifecycle linkage logger JSONL)
        - risk : DD intra-session, SL consecutifs, kill switch
    """

    def __init__(
        self,
        dtc: Optional[Any] = None,
        symbols: Optional[List[str]] = None,
        dry_run: bool = True,
        trade_account: str = "Sim1",
        params: Optional[Bot3V3Params] = None,
        count_same_side_callback: Optional[Any] = None,
    ):
        """Args:
            count_same_side_callback : Optional callable(side: str) -> int
              retourne nb positions same-side ouvertes cross-bot
              (Bot 1 + BN V4 + Bot 3 v3 + Bot 3 v4). Fix R1 market-analyst :
              gate max 2 positions same-side pour eviter corr exposure x4
              sur 4 bots NQ simultanes (paper Sim1+Sim3+Sim2+prod).
              Si None : pas de gate (back-compat / tests isolated).
        """
        symbols = symbols or ["NQ"]
        _emit("BOT3_V3_BOOT_START",
              sym=",".join(symbols), dry_run=int(dry_run),
              trade_account=trade_account, mode="paper")

        # Config
        if params is None:
            params = Bot3V3Params()  # defaults = backtester valide
        self.params = params
        self.symbols = symbols
        self.dry_run = dry_run or (dtc is None)
        self.trade_account = trade_account
        self.dtc = dtc
        self.count_same_side_callback = count_same_side_callback
        self.MAX_SAME_SIDE_CROSS_BOT = 2  # gate market-analyst R1

        # Engine par symbol (log_fn=_emit pour tracability transitions state machine)
        self._engine_by_sym: Dict[str, Bot3V3Engine] = {}
        level_defs = build_default_level_defs()
        for sym in self.symbols:
            self._engine_by_sym[sym] = Bot3V3Engine(
                symbol=sym, level_defs=level_defs, params=self.params,
                log_fn=_emit,
            )

        # Reader JSONL live_enriched
        self._reader_by_sym: Dict[str, LiveEnrichedReader] = {}
        for sym in self.symbols:
            self._reader_by_sym[sym] = LiveEnrichedReader(
                symbol=sym, window_bars=480, warn_stale_sec=180,
            )

        # Logger JSONL dedie
        self._logger_by_sym: Dict[str, Bot3V3Logger] = {}
        for sym in self.symbols:
            self._logger_by_sym[sym] = Bot3V3Logger(symbol=sym)

        # Etat positions + lock
        self._position: Dict[str, Optional[dict]] = {s: None for s in self.symbols}
        self._current_signal_id: Dict[str, Optional[str]] = {s: None for s in self.symbols}
        self._pos_lock = threading.Lock()

        # Index ClientOrderID → {sym, kind, signal_id} pour _handle_dtc_fill
        self._cid_index: Dict[str, dict] = {}

        # Risk session
        self._n_sl_consec: Dict[str, int] = {s: 0 for s in self.symbols}
        self._pnl_session_usd: float = 0.0
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
        self._cooldown_until: Dict[str, Optional[datetime]] = {s: None for s in self.symbols}
        self.RISK_MAX_SL_CONSEC = DEFAULT_RISK_MAX_SL_CONSEC
        self.RISK_COOLDOWN_MIN = DEFAULT_RISK_COOLDOWN_MIN
        self.RISK_MAX_DD_USD = DEFAULT_RISK_MAX_DD_USD

        # Cooldown global post-trade per-sym (24/05/2026 PM Jackson directive).
        # 10min apres gain, 15min apres perte. Empeche back-to-back trades.
        self._last_close_ts: Dict[str, Optional[datetime]] = {s: None for s in self.symbols}
        self._last_close_pnl_R: Dict[str, Optional[float]] = {s: None for s in self.symbols}

        # Heartbeat
        self._last_heartbeat_ts: Optional[datetime] = None
        self.HEARTBEAT_INTERVAL_MIN = DEFAULT_HEARTBEAT_INTERVAL_MIN

        # Stats lifecycle
        self._n_bars_processed: int = 0
        self._n_entries_emitted: int = 0
        self._n_trades_executed: int = 0
        self._boot_ts = datetime.now(timezone.utc)

        # ====================================================================
        # Etape 2 sprint stabilite Bot 3 v3 (09/06 soir) :
        # persistance positions + reconcile DTC + halt_reason pattern.
        # ====================================================================
        self._positions_persist = PositionPersistance(
            bot_name="bot3_v3", lock=self._pos_lock, emit_fn=_emit,
        )
        self._reconciled: bool = False
        self._halt_reason: Optional[str] = None
        self._halt_details: str = ""
        self._pnl_session_usd_uncertain: bool = False
        # Rate-limit emit pour POLL_SKIP_* (eviter spam logs en cas HALT)
        self._last_poll_skip_halt_emit_ts: Optional[datetime] = None
        self._last_poll_skip_reconcile_emit_ts: Optional[datetime] = None

        # PnL ack lecture UNE fois au boot (decision D1 plan ULTRATHINK 09/06).
        # Si Jackson set MIA_BOT3_V3_PNL_ACK=1 puis restart, le flag uncertain
        # est reset au boot. Sinon il persiste cross-restart via state meta.
        pnl_ack = os.environ.get("MIA_BOT3_V3_PNL_ACK", "0") == "1"

        try:
            restored = self._positions_persist.restore()
            # Si flag uncertain etait set + Jackson ACK -> reset
            if pnl_ack:
                self._positions_persist.set_meta("pnl_session_usd_uncertain", False)
            else:
                stored_uncertain = self._positions_persist.get_meta(
                    "pnl_session_usd_uncertain", False)
                if stored_uncertain:
                    self._pnl_session_usd_uncertain = True

            if restored:
                with self._pos_lock:
                    for sym, pos in restored.items():
                        self._position[sym] = pos
                        if pos.get("signal_id"):
                            self._current_signal_id[sym] = pos["signal_id"]
                        # Rebuild _cid_index depuis positions restaurees
                        cid_kind_map = {
                            "parent_cid": "parent", "tp_cid": "tp", "sl_cid": "sl",
                        }
                        for cid_key, kind in cid_kind_map.items():
                            cid = pos.get(cid_key)
                            if cid:
                                self._cid_index[cid] = {
                                    "sym": sym, "kind": kind,
                                    "signal_id": pos.get("signal_id"),
                                }
                _emit("BOT3_V3_POSITIONS_RESTORED",
                      n_positions=len(restored),
                      symbols=",".join(restored.keys()),
                      signal_counter_restored=False)
                _emit("BOT3_V3_CID_INDEX_REBUILT", n_cids=len(self._cid_index))

            # Restore cooldown per-sym depuis meta
            for sym in self.symbols:
                last_close_ts_str = self._positions_persist.get_meta(
                    f"last_trade_close_ts_{sym}")
                last_close_pnl_R = self._positions_persist.get_meta(
                    f"last_trade_close_pnl_R_{sym}")
                if not last_close_ts_str:
                    continue
                try:
                    last_close_ts = datetime.fromisoformat(
                        str(last_close_ts_str).replace("Z", "+00:00"))
                    if last_close_ts.tzinfo is None:
                        last_close_ts = last_close_ts.replace(tzinfo=timezone.utc)
                    self._last_close_ts[sym] = last_close_ts
                    if last_close_pnl_R is not None:
                        self._last_close_pnl_R[sym] = float(last_close_pnl_R)
                    # D6 plan ULTRATHINK : pnl_R None ou negatif -> LOSS cooldown (15min)
                    pnl_r = self._last_close_pnl_R[sym]
                    cooldown_min = 15 if (pnl_r is None or pnl_r < 0) else 10
                    self._cooldown_until[sym] = (
                        last_close_ts + timedelta(minutes=cooldown_min))
                    _emit("BOT3_V3_COOLDOWN_RESTORED",
                          symbol=sym,
                          last_trade_close_ts=last_close_ts_str,
                          cooldown_until=self._cooldown_until[sym].isoformat())
                except (ValueError, TypeError) as e:
                    _emit("BOT3_V3_LOOP_ERROR",
                          sym=sym, err=f"cooldown_restore: {str(e)[:200]}")

            # Inject persistance dans loggers pour signal_counter cross-restart
            for sym in self.symbols:
                self._logger_by_sym[sym].set_persistance(self._positions_persist)
                self._logger_by_sym[sym].restore_counter()

        except BotStateLoadError as e:
            _emit("BOT_STATE_LOAD_FAILED",
                  bot="bot3_v3", err=str(e)[:200],
                  file=str(self._positions_persist._state_file.state_path))
            raise  # FAIL-CLOSED au __init__ : bot refuse boot

        # Emit CONFIG_LOADED
        _emit("BOT3_V3_CONFIG_LOADED",
              touch_buf=self.params.touch_buffer_pct,
              breakout_buf=self.params.breakout_buffer_pct,
              retest_buf=self.params.retest_buffer_pct,
              w1=self.params.window_touch_to_breakout,
              w2=self.params.window_breakout_to_retest,
              w3=self.params.window_retest_confirm,
              target_R=self.params.target_R,
              sl_fallback=(self.params.sl_fallback_ticks_nq if "NQ" in symbols
                            else self.params.sl_fallback_ticks_es),
              max_risk_t=(self.params.sl_max_ticks_nq if "NQ" in symbols
                            else self.params.sl_max_ticks_es))

    def boot_ready(self) -> None:
        """Reconcile DTC + emit BOOT_READY (ou HALT_BOOT_REQUIRES_HUMAN selon resultat).

        Etape 2 sprint stabilite Bot 3 v3 (09/06 soir).

        Sequence :
          1. Check flag file STATE/bot3_v3/force_flat.flag (consume-and-delete)
          2. Reconcile DTC 5 cas (skip si dry_run ou dtc None)
          3. Pour chaque report : action selon case + force_flat_override
          4. Si pas HALT : self._reconciled = True + emit BOOT_READY classique
          5. Si HALT : emit BOT3_V3_HALT_BOOT_REQUIRES_HUMAN (CRITIQUE)
        """
        # 1. Flag file force_flat (consume-and-delete)
        force_flat = False
        if FORCE_FLAT_FLAG_PATH.exists():
            force_flat = True
            try:
                FORCE_FLAT_FLAG_PATH.unlink()
            except OSError as e:
                _emit("BOT_STATE_SAVE_FAILED",
                      bot="bot3_v3",
                      err=f"flag unlink: {type(e).__name__}: {str(e)[:200]}",
                      file=str(FORCE_FLAT_FLAG_PATH))

        # 2. Reconcile DTC (skip si dry_run)
        if self.dry_run or self.dtc is None:
            # Mode dry_run : skip reconcile, marquer reconciled
            self._reconciled = True
            for sym in self.symbols:
                _emit("BOT3_V3_BOOT_READY",
                      sym=sym,
                      dtc_state="DRY_RUN",
                      reader_state="ready",
                      n_levels=len(self._engine_by_sym[sym].level_defs))
            return

        # D4 plan ULTRATHINK : DTC non disponible apres init -> halt sans retry
        # (paper_v2 main loop gere le bootstrap DTC AVANT d'appeler boot_ready)
        try:
            symbol_to_contract = {
                s: SYMBOL_TO_CONTRACT.get(s, f"{s}M26-CME") for s in self.symbols
            }
            reports = self._positions_persist.reconcile_with_dtc(
                dtc=self.dtc,
                trade_account=self.trade_account,
                symbol_to_contract=symbol_to_contract,
                force_flat_override=force_flat,
                position_query_timeout_sec=3.0,
            )
        except Exception as e:
            _emit("BOT3_V3_LOOP_ERROR",
                  sym=",".join(self.symbols),
                  err=f"reconcile_with_dtc_exc: {type(e).__name__}: {str(e)[:200]}")
            self._halt_reason = "RECONCILE_EXCEPTION"
            self._halt_details = str(e)[:200]
            _emit("BOT3_V3_HALT_BOOT_REQUIRES_HUMAN",
                  reason=self._halt_reason,
                  symbol="",
                  details=self._halt_details)
            return

        # 3. Process chaque report
        for report in reports:
            self._handle_reconcile_report(report, force_flat)

        # 4. Verdict final
        if self._halt_reason is None:
            self._reconciled = True
            for sym in self.symbols:
                _emit("BOT3_V3_BOOT_READY",
                      sym=sym,
                      dtc_state="CONNECTED",
                      reader_state="ready",
                      n_levels=len(self._engine_by_sym[sym].level_defs))
        else:
            _emit("BOT3_V3_HALT_BOOT_REQUIRES_HUMAN",
                  reason=self._halt_reason,
                  symbol="",
                  details=self._halt_details)

    def _handle_reconcile_report(
        self, report: ReconcileReport, force_flat_active: bool,
    ) -> None:
        """Process 1 ReconcileReport selon case (a/b/c/d/e/QUERY_FAILED)."""
        sym = report.symbol
        if report.case in ("OK_FLAT", "OK_RESTORED"):
            return  # nominal, emit deja fait par helper

        if report.case == "PYTHON_GHOST":
            # Cas d : position Python sans broker = fermee externe
            self._handle_python_ghost(report)
            return

        if report.case in ("UNKNOWN_BROKER_POS", "DIVERGENCE", "QUERY_FAILED"):
            if report.action_taken == "force_flat" and force_flat_active:
                # Reutiliser force_close_market via wrapper _execute_force_flat
                ok = self._execute_force_flat(report)
                if not ok:
                    # Force flat failed -> halt
                    self._halt_reason = f"{report.case}_FORCE_FLAT_FAILED"
                    self._halt_details = (
                        f"{report.symbol} force_close_market returned False"
                    )
            else:
                # halt_boot : set _halt_reason
                self._halt_reason = report.case
                self._halt_details = (
                    f"{report.symbol} case={report.case} "
                    f"python={report.python_state} broker={report.broker_position}. "
                    f"Reset : creer flag STATE/bot3_v3/force_flat.flag puis restart"
                )
            return

    def _handle_python_ghost(self, report: ReconcileReport) -> None:
        """Cas d : emit TRADE_CLOSE_EXTERNAL + flag pnl_uncertain.

        D2 plan ULTRATHINK : exit_price estimee depuis reader.load_rolling_window
        derniere bar close. PnL estime via compute_pnl_R_usd existant.
        Bloquera trades futurs jusqu'a Jackson ACK via MIA_BOT3_V3_PNL_ACK=1.
        """
        sym = report.symbol
        py_state = report.python_state or {}
        signal_id = py_state.get("signal_id", "")
        # Estimateur exit_price : last bar close du reader
        exit_price_est = None
        pnl_est = None
        try:
            reader = self._reader_by_sym.get(sym)
            if reader is not None:
                df = reader.load_rolling_window()
                if df is not None and len(df) > 0:
                    exit_price_est = float(df.iloc[-1].get("close", 0.0) or 0.0)
        except Exception as e:
            _emit("BOT3_V3_LOOP_ERROR",
                  sym=sym,
                  err=f"ghost_estimate_exit_exc: {type(e).__name__}: {str(e)[:200]}")
        # PnL estime si exit_price dispo
        if exit_price_est is not None and "entry_price" in py_state:
            try:
                # 09/06 BUG #5 fix : tick_value depuis GUARD_RAILS_BOT3
                try:
                    from bot3_config import GUARD_RAILS_BOT3 as _GR_ghost
                except ImportError:
                    from CORE.bot3_config import GUARD_RAILS_BOT3 as _GR_ghost
                _tv_override = _GR_ghost.get(sym, {}).get("tick_value")
                _, pnl_est = compute_pnl_R_usd(
                    direction=str(py_state.get("direction", "LONG")),
                    entry_price=float(py_state.get("entry_price", 0.0)),
                    sl_initial=float(py_state.get("sl_initial", 0.0)),
                    exit_price=exit_price_est,
                    symbol=sym,
                    n_contracts=int(py_state.get("n_contracts", 1)),
                    tick_value_override=_tv_override,
                )
            except Exception as e:
                _emit("BOT3_V3_LOOP_ERROR",
                      sym=sym,
                      err=f"ghost_estimate_pnl_exc: {type(e).__name__}: {str(e)[:200]}")
        _emit("BOT3_V3_TRADE_CLOSE_EXTERNAL",
              symbol=sym, signal_id=signal_id,
              exit_price_estimated=(
                  round(exit_price_est, 4) if exit_price_est is not None else None),
              pnl_estimated_usd=(
                  round(pnl_est, 2) if pnl_est is not None else None))
        self._pnl_session_usd_uncertain = True
        # Persiste flag pour cross-restart
        try:
            self._positions_persist.set_meta("pnl_session_usd_uncertain", True)
        except Exception:
            pass
        _emit("BOT3_V3_PNL_UNCERTAIN", reason="cas_d_reconcile_python_ghost")

    def _execute_force_flat(self, report: ReconcileReport) -> bool:
        """Reutilise force_close_market pour cas c/e force_flat.

        Construit dict pos minimal depuis broker_position + emit appropries.
        Return True si force_close OK, False sinon (halt boot).
        """
        sym = report.symbol
        broker_pos = report.broker_position or {}
        broker_qty = broker_pos.get("qty", 0)
        broker_side = broker_pos.get("side", "LONG")
        ts_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
        # Pos minimal : pas de cid (positions trackees externalement)
        pos_min = {
            "parent_cid": None,
            "tp_cid": None,
            "sl_cid": None,
            "direction": broker_side,
            "qty": abs(int(broker_qty)),
            "n_contracts": abs(int(broker_qty)),
            "signal_id": f"reconcile_force_flat_{sym}_{ts_ns}",
            "entry_price": 0.0,  # inconnu, force_close_market n'utilise pas
            "sl_initial": 0.0,
            "level_name": "RECONCILE_FORCE_FLAT",
        }
        try:
            ok = force_close_market(
                dtc=self.dtc, symbol=sym, pos=pos_min,
                trade_account=self.trade_account,
                reason=f"reconcile_{report.case}",
                bot_label=BOT_LABEL, emit_fn=_emit,
                cid_prefix=CID_PREFIX, cid_index=self._cid_index,
                cid_index_lock=self._pos_lock,
            )
            return ok
        except Exception as e:
            _emit("BOT3_V3_LOOP_ERROR",
                  sym=sym,
                  err=f"execute_force_flat_exc: {type(e).__name__}: {str(e)[:200]}")
            return False

    def poll_cycle(self) -> None:
        """Cycle principal Bot 3 v3 (appele depuis paper_v2 main loop).

        Pour chaque symbol :
          1. heartbeat_check
          2. reader.load_rolling_window → df
          3. Si position active : check timeout 360 bars
          4. Sinon : engine.process_bar(last_bar) → Optional[EntryDecision]
          5. Si EntryDecision : check risk gates + place_bracket_dtc
        """
        # Heartbeat AVANT kill switch check (telemetry continue meme en HALT)
        self._heartbeat_check_emit()

        # Etape 2 sprint stabilite : gate HALT_BOOT
        if self._halt_reason is not None:
            now = datetime.now(timezone.utc)
            if (self._last_poll_skip_halt_emit_ts is None or
                (now - self._last_poll_skip_halt_emit_ts).total_seconds()
                    > POLL_SKIP_HALT_EMIT_INTERVAL_SEC):
                _emit("BOT3_V3_POLL_SKIP_HALT_BOOT",
                      halt_reason=self._halt_reason)
                self._last_poll_skip_halt_emit_ts = now
            return

        # Etape 2 sprint stabilite : gate not reconciled
        if not self._reconciled:
            now = datetime.now(timezone.utc)
            if (self._last_poll_skip_reconcile_emit_ts is None or
                (now - self._last_poll_skip_reconcile_emit_ts).total_seconds()
                    > POLL_SKIP_RECONCILE_EMIT_INTERVAL_SEC):
                _emit("BOT3_V3_POLL_SKIP_NOT_RECONCILED")
                self._last_poll_skip_reconcile_emit_ts = now
            return

        if self._kill_switch_active:
            return

        for sym in self.symbols:
            try:
                self._poll_cycle_symbol(sym)
            except Exception as e:
                _emit("BOT3_V3_LOOP_ERROR",
                      sym=sym,
                      err=f"{type(e).__name__}: {str(e)[:300]}")

    def _poll_cycle_symbol(self, sym: str) -> None:
        """Poll cycle pour 1 symbol."""
        reader = self._reader_by_sym[sym]
        engine = self._engine_by_sym[sym]
        logger = self._logger_by_sym[sym]

        # 1. Lecture rolling window
        df = reader.load_rolling_window()
        if df is None or len(df) < 5:
            return  # warmup

        # 2. Check staleness derniere bar
        age_sec = reader.get_last_bar_age_seconds()
        if age_sec > reader.warn_stale_sec:
            _emit("BOT3_V3_BAR_STALE",
                  sym=sym, age_sec=round(age_sec, 1),
                  threshold_sec=reader.warn_stale_sec)
            return

        # 3. Extract last bar
        last_bar = df.iloc[-1]
        bar_ts_iso = self._extract_ts_iso(last_bar)
        bar_day = self._extract_day(last_bar)
        if bar_day is None:
            return  # bar invalide

        self._n_bars_processed += 1
        ts_event_ns = int(last_bar.get("ts_event_ns", 0) or 0)
        logger.log_bar_processed(
            ts_event_ns=ts_event_ns,
            close=float(last_bar.get("close", 0.0) or 0.0),
            regime_mode=str(last_bar.get("regime_mode", "")),
        )

        # 4. Si position active : check timeout
        pos = self._position.get(sym)
        if pos is not None:
            self._check_position_timeout(sym, pos, bar_ts_iso)
            return

        # 5. Engine process_bar → Optional[EntryDecision]
        decision = engine.process_bar(last_bar, bar_ts_iso, bar_day)
        if decision is None:
            return

        # Decision emise par engine → handle entry
        self._handle_entry_decision(sym, decision, last_bar)

    def _handle_entry_decision(
        self, sym: str, decision: EntryDecision, last_bar: Any,
    ) -> None:
        """Traitement EntryDecision : risk gates + DTC bracket OR dry_run log."""
        self._n_entries_emitted += 1
        logger = self._logger_by_sym[sym]

        # Etape 2 sprint stabilite : gate PnL session uncertain (cas d reconcile)
        # Bloque trades futurs jusqu'a Jackson ACK via MIA_BOT3_V3_PNL_ACK=1 + restart.
        if self._pnl_session_usd_uncertain:
            _emit("BOT3_V3_PNL_UNCERTAIN", reason="entry_blocked_need_ack")
            return

        # Generate signal_id via logger helper
        signal_id = logger.next_signal_id()

        # News veto delegated a engine ? Non, engine fait dejà long_up_bar check,
        # mais news veto ici en sécurité (engine pure logic ne fait pas veto news).
        # → On confie a la check critical: bars/news. Mais en realite news_veto
        # est applique au niveau backtester. Engine v3 n'a pas de filter_news.
        # → Pour cohérence : on applique news veto ici en wrapper paper.
        mins_since = last_bar.get("mins_since_news", 999)
        mins_to_next = last_bar.get("mins_to_next_news", 999)
        try:
            ms = float(mins_since) if mins_since is not None else 999
            mt = float(mins_to_next) if mins_to_next is not None else 999
        except (TypeError, ValueError):
            ms, mt = 999, 999
        if (mins_since is None or mins_to_next is None or
                (0 <= ms <= 5) or (0 <= mt <= 5)):
            _emit("BOT3_V3_ENTRY_VETO_NEWS",
                  sym=sym, level=decision.level_name, side=decision.side,
                  mins_since=ms, mins_to_next=mt)
            logger.log_entry_signal(
                signal_id=signal_id, level=decision.level_name,
                side=decision.side, entry_price=decision.entry_close,
                sl_price=decision.sl_price, tp_price=decision.tp_price,
                sl_ticks=decision.sl_ticks, tp_mode="R15",
                executed=False, veto_reason="news_window",
            )
            return

        # Veto eco_calendar (24/05 Jackson : aligner sur Bot 1 legacy regle 15min RTH).
        # is_blocked_combined() couvre : eco events (FOMC/NFP/CPI/PCE -15/+30min),
        # Open US 09:15-09:45 ET, Post-MOC 15:30-18:15 ET (lun-jeu), weekend.
        # R1 code-reviewer 24/05 : fail-CLOSED si module HS (mieux rater un trade
        # que trader pendant FOMC). Diverge volontairement de Bot 1 legacy fail-open.
        try:
            from CORE import eco_calendar as _eco
            _blocked, _reason, _until = _eco.is_blocked_combined()
        except Exception as _e:
            _emit("ECO_CALENDAR_FAIL_FAILCLOSED",
                  sym=sym, bot="bot3_v3", err=str(_e)[:200])
            _blocked, _reason = True, "eco_calendar_module_error"
        if _blocked:
            _emit("BOT3_V3_ENTRY_VETO_ECO_BLOCK",
                  sym=sym, level=decision.level_name, side=decision.side,
                  reason=_reason or "?")
            logger.log_entry_signal(
                signal_id=signal_id, level=decision.level_name,
                side=decision.side, entry_price=decision.entry_close,
                sl_price=decision.sl_price, tp_price=decision.tp_price,
                sl_ticks=decision.sl_ticks, tp_mode="R15",
                executed=False, veto_reason=f"eco_block:{_reason or '?'}",
            )
            return

        # Veto cooldown post-trade Bot 1 (DEFAULT 10min win, 15min loss).
        # 02/06 SOIR : tentative cooldown 20/30 ROLLBACK suite market-analyst
        # test isolation = "cooldown 20/30 DETRUIT l'edge" :
        #   - SL/TP fixe seul : PF 1.57 Net +$406
        #   - + cooldown 20/30 seul : PF 1.27 Net +$188 (DEGRADE)
        #   - + slope 0.10 seul : PF 1.64 Net +$438 (AMELIORE)
        #   - combo cooldown 20/30 + slope : PF 1.33 Net +$219 (degrade vs slope seul)
        # Le cooldown enleve 5 trades dont le PnL net est POSITIF -> revert.
        _cd_blocked, _cd_rem, _cd_reason = check_post_trade_cooldown(
            self._last_close_ts.get(sym),
            self._last_close_pnl_R.get(sym),
            datetime.now(timezone.utc),
        )
        if _cd_blocked:
            _emit("BOT3_V3_ENTRY_VETO_POST_TRADE_COOLDOWN",
                  sym=sym, level=decision.level_name, side=decision.side,
                  reason=_cd_reason, remaining_sec=_cd_rem)
            logger.log_entry_signal(
                signal_id=signal_id, level=decision.level_name,
                side=decision.side, entry_price=decision.entry_close,
                sl_price=decision.sl_price, tp_price=decision.tp_price,
                sl_ticks=decision.sl_ticks, tp_mode="R15",
                executed=False,
                veto_reason=f"post_trade_cooldown:{_cd_reason}:{_cd_rem}s",
            )
            return

        # Risk gates
        state = {
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "cooldown_until": self._cooldown_until,
            "pnl_session_usd": self._pnl_session_usd,
            "n_sl_consec": self._n_sl_consec,
            "RISK_MAX_DD_USD": self.RISK_MAX_DD_USD,
        }
        if not check_risk_gates(state, sym, decision.side, _emit, BOT_LABEL):
            # Si DD dépassé, activate kill switch
            if self._pnl_session_usd <= self.RISK_MAX_DD_USD:
                self.activate_kill_switch(reason="max_dd_session_exceeded")
            logger.log_entry_signal(
                signal_id=signal_id, level=decision.level_name,
                side=decision.side, entry_price=decision.entry_close,
                sl_price=decision.sl_price, tp_price=decision.tp_price,
                sl_ticks=decision.sl_ticks, tp_mode="R15",
                executed=False, veto_reason="risk_gates",
            )
            return

        # Position deja ouverte ?
        if self._position.get(sym) is not None:
            pos_dir = self._position[sym].get("direction", "?")
            _emit("BOT3_V3_ENTRY_VETO_POSITION",
                  sym=sym, level=decision.level_name,
                  side=decision.side, side_pos=pos_dir)
            return

        # Fix R1 market-analyst : gate cross-bot same-side max 2 (anti corr exposure)
        if self.count_same_side_callback is not None:
            try:
                n_same = int(self.count_same_side_callback(decision.side))
            except Exception:
                n_same = 0  # fail-soft, on n'empeche pas le trade si callback bug
            if n_same >= self.MAX_SAME_SIDE_CROSS_BOT:
                _emit("BOT3_V3_ENTRY_VETO_KILL_SWITCH",
                      sym=sym, level=decision.level_name, side=decision.side,
                      reason=f"cross_bot_same_side_{n_same}_ge_{self.MAX_SAME_SIDE_CROSS_BOT}")
                logger.log_entry_signal(
                    signal_id=signal_id, level=decision.level_name,
                    side=decision.side, entry_price=decision.entry_close,
                    sl_price=decision.sl_price, tp_price=decision.tp_price,
                    sl_ticks=decision.sl_ticks, tp_mode="R15",
                    executed=False, veto_reason=f"cross_bot_same_side_{n_same}",
                )
                return

        # Execute trade (dry_run ou DTC)
        if self.dry_run or self.dtc is None:
            _emit("BOT3_V3_ENTRY_VETO_DRY_RUN",
                  sym=sym, level=decision.level_name, side=decision.side,
                  entry_close=decision.entry_close,
                  sl=decision.sl_price, tp=decision.tp_price)
            logger.log_entry_signal(
                signal_id=signal_id, level=decision.level_name,
                side=decision.side, entry_price=decision.entry_close,
                sl_price=decision.sl_price, tp_price=decision.tp_price,
                sl_ticks=decision.sl_ticks, tp_mode="R15", executed=False,
                veto_reason="dry_run",
            )
            self._n_trades_executed += 1
            return

        # DTC bracket
        self._place_bracket_dtc(sym, decision, signal_id, last_bar)

    def _place_bracket_dtc(
        self, sym: str, decision: EntryDecision, signal_id: str, last_bar: Any,
    ) -> None:
        """Place bracket OCO DTC pour entry signal.

        02/06 FIX C2 sizing per-bot : qty lue depuis GUARD_RAILS_BOT3[sym]["n_contracts"]
        au lieu de hardcoded 1. Aligne tracking interne + log + journal avec broker.
        """
        # 02/06 FIX C2 : sizing dynamic per-bot
        try:
            from bot3_config import GUARD_RAILS_BOT3 as GR
        except ImportError:
            from CORE.bot3_config import GUARD_RAILS_BOT3 as GR
        qty = int(GR.get(sym, {}).get("n_contracts", 1))

        try:
            parent_id, tp_cid, sl_cid = place_bracket_dtc(
                dtc=self.dtc, symbol=sym, side=decision.side,
                entry_price=decision.entry_close, sl_price=decision.sl_price,
                tp_price=decision.tp_price, sl_ticks=decision.sl_ticks,
                tp_ticks=int(decision.sl_ticks * self.params.target_R),
                trade_account=self.trade_account, qty=qty,
            )
        except Exception as e:
            _emit("BOT3_V3_LOOP_ERROR", sym=sym,
                  err=f"dtc_send_market_exc: {type(e).__name__}: {str(e)[:200]}")
            return

        if not parent_id:
            _emit("BOT3_V3_SETUP_DTC_ABORT",
                  sym=sym, level=decision.level_name, side=decision.side,
                  reason="parent_id_empty_fill_timeout_or_dtc_down")
            return

        # Register tracking interne
        ts_open_ns = int(last_bar.get("ts_event_ns", 0) or 0)
        with self._pos_lock:
            self._cid_index[parent_id] = {
                "sym": sym, "kind": "parent", "signal_id": signal_id,
            }
            self._cid_index[tp_cid] = {
                "sym": sym, "kind": "tp", "signal_id": signal_id,
            }
            self._cid_index[sl_cid] = {
                "sym": sym, "kind": "sl", "signal_id": signal_id,
            }
            self._position[sym] = {
                "parent_cid": parent_id, "tp_cid": tp_cid, "sl_cid": sl_cid,
                "direction": decision.side,
                "entry_price": decision.entry_close,
                "sl_initial": decision.sl_price,
                "sl_current": decision.sl_price,
                "tp_price": decision.tp_price,
                "sl_ticks": decision.sl_ticks,
                "level_name": decision.level_name,
                "level_family": decision.level_family,
                "qty": qty,                  # 02/06 FIX C2 : dynamic
                "n_contracts": qty,           # 02/06 FIX C1 : passe a compute_pnl_R_usd
                "signal_id": signal_id,
                "ts_open": datetime.now(timezone.utc).isoformat(),
                "ts_open_ns": ts_open_ns,
                "bar_idx_open": decision.bar_idx,
            }
            self._current_signal_id[sym] = signal_id
            self._n_trades_executed += 1
            # D9 plan ULTRATHINK : capture snapshot SOUS lock pour save HORS lock
            pos_snapshot = dict(self._position[sym])

        # Etape 2 sprint stabilite : persiste position HORS lock (D9 anti-deadlock)
        try:
            self._positions_persist.save_position(sym, pos_snapshot)
        except Exception as e:
            _emit("BOT_STATE_SAVE_FAILED",
                  bot="bot3_v3",
                  err=f"save_position_open: {type(e).__name__}: {str(e)[:200]}",
                  file="bot3_v3_state.json")

        _emit("BOT3_V3_BRACKET_PLACED",
              sym=sym, parent_cid=parent_id[:20],
              tp_cid=tp_cid[:20], sl_cid=sl_cid[:20],
              trade_account=self.trade_account)
        _emit("BOT3_V3_TRADE_OPEN",
              sym=sym, level=decision.level_name, side=decision.side,
              entry_price=decision.entry_close,
              sl_price=decision.sl_price, tp_price=decision.tp_price,
              sl_ticks=decision.sl_ticks, qty=qty)

        # Logger JSONL
        self._logger_by_sym[sym].log_trade_open(
            signal_id=signal_id, level=decision.level_name,
            side=decision.side, entry_price=decision.entry_close,
            sl_price=decision.sl_price, tp_price=decision.tp_price,
            sl_ticks=decision.sl_ticks, qty=qty,
            parent_cid=parent_id, tp_cid=tp_cid, sl_cid=sl_cid,
            trade_account=self.trade_account,
            ts_event_ns=ts_open_ns,
        )

    def handle_dtc_fill(self, msg: dict, cid: str) -> bool:
        """Hook ORDER_UPDATE Type 301 status=7 (Filled).

        Returns True si cid traite (etait dans cid_index), False sinon.
        Caller (paper_v2) doit appeler ce hook + autres bots en chaine.
        """
        if cid not in self._cid_index:
            return False

        entry = self._cid_index[cid]
        sym = entry["sym"]
        kind = entry["kind"]
        signal_id = entry["signal_id"]

        # GUARD #1 (FIX 03/06 agent code-reviewer apres 28 faux CRITIQUE / 6h) :
        # DTC OrderStatus : 2=Open (ACK), 4=Working (en attente trigger), 6=Rejected,
        # 7=Filled, 8=Cancelled. Seul 7 declenche le close logic.
        # AVANT ce fix : emit FILL_PRICE_INVALID CRITIQUE sur tout status != 7
        #   - Or status=2/4 sont NORMAUX pour un SL STOP en attente trigger price
        #   - 28 faux positifs en 6h ce matin -> cascade crashes process
        #   - Cf regle souveraine CLAUDE.md "OrderStatus=2 n'est PAS Filled.
        #     Sequence normale : 2 -> 4 -> 7"
        # APRES : status non-7 = update legitime cycle de vie ordre, NE PAS flagger.
        # status=6/8 = etat terminal a tracer (info) pour audit OCO cancel + rejects.
        try:
            order_status = int(msg.get("OrderStatus", 0))
        except (TypeError, ValueError):
            order_status = 0
        if order_status != 7:
            if order_status in (6, 8):
                _emit("BOT3_V3_ORDER_TERMINAL",
                      sym=sym, cid=cid, kind=kind, signal_id=signal_id,
                      msg_status=order_status)
            return True  # consume update legitime, aucune action close

        try:
            fill_price = float(msg.get("LastFillPrice", 0)) or float(msg.get("AverageFillPrice", 0))
        except (TypeError, ValueError):
            fill_price = 0.0

        # GUARD #2 24/05/2026 PM (incident ghost trade $59542 Bot 3 v4) :
        # fill_price=0 produit un PnL aberrant. Refuser close + emit ctx complet.
        if fill_price <= 0:
            _emit("BOT3_V3_FILL_PRICE_INVALID",
                  sym=sym, cid=cid, kind=kind, signal_id=signal_id,
                  msg_status=order_status,
                  last_fill_price=msg.get("LastFillPrice"),
                  avg_fill_price=msg.get("AverageFillPrice"),
                  order_type=msg.get("OrderType"),
                  qty_filled=msg.get("FilledQuantity"),
                  msg_keys=list(msg.keys())[:15])
            return True

        with self._pos_lock:
            pos = self._position.get(sym)
            if pos is None:
                return True  # race condition, position deja cleanup

            if kind == "parent":
                # Parent fill = ouverture. Capture entry_filled_price pour
                # instrumentation slippage (Phase 1 28/05).
                pos["entry_filled_price"] = fill_price
                pos["ts_entry_fill_ns"] = int(datetime.now(timezone.utc).timestamp() * 1e9)
                # Calcul slip entry immediat (audit forensique)
                tick = TICK_BY_SYMBOL.get(sym, 0.25)
                sign = 1 if pos["direction"] == "LONG" else -1
                entry_slip_t = (fill_price - pos["entry_price"]) / tick * sign
                if abs(entry_slip_t) > 2.0:
                    # Slip entry anormal (> 2t) : emit ALERTE
                    _emit("BOT3_V3_ENTRY_SLIP_ANOMALY",
                          sym=sym, signal_id=signal_id,
                          direction=pos["direction"],
                          entry_planned=round(pos["entry_price"], 4),
                          entry_filled=round(fill_price, 4),
                          slip_ticks=round(entry_slip_t, 2))
                return True

            # SL ou TP fill = trade close
            ts_close_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
            ts_open_ns = pos.get("ts_open_ns", 0)
            duration_bars = max(1, int((ts_close_ns - ts_open_ns) / 60_000_000_000)) if ts_open_ns else 0

            # 02/06 FIX C1 : passer n_contracts pour PnL USD = sizing reel
            n_ctr = int(pos.get("n_contracts", 1))
            # 09/06 BUG #5 fix : passer tick_value depuis GUARD_RAILS_BOT3
            # (Bot 3 v3 trade en Cross Chart Micro $0.50/tick NQ, pas $5.00/tick E-mini)
            try:
                from bot3_config import GUARD_RAILS_BOT3 as _GR
            except ImportError:
                from CORE.bot3_config import GUARD_RAILS_BOT3 as _GR
            _tick_value_override = _GR.get(sym, {}).get("tick_value")
            pnl_R, pnl_usd = compute_pnl_R_usd(
                direction=pos["direction"], entry_price=pos["entry_price"],
                sl_initial=pos["sl_initial"], exit_price=fill_price,
                symbol=sym, n_contracts=n_ctr,
                tick_value_override=_tick_value_override,
            )
            self._pnl_session_usd += pnl_usd

            # Update cooldown state post-trade (24/05/2026 PM Jackson directive).
            self._last_close_ts[sym] = datetime.now(timezone.utc)
            self._last_close_pnl_R[sym] = pnl_R

            if kind == "sl":
                log_code = "BOT3_V3_TRADE_CLOSE_SL"
                cause = "SL"
                self._n_sl_consec[sym] = self._n_sl_consec.get(sym, 0) + 1
            elif kind == "tp":
                log_code = "BOT3_V3_TRADE_CLOSE_TP"
                cause = "TP"
                self._n_sl_consec[sym] = 0
            else:
                _emit("BOT3_V3_LOOP_ERROR", sym=sym,
                      err=f"handle_fill_unknown_kind: {kind}")
                return True

            # =================================================================
            # PHASE 1 INSTRUMENTATION SLIPPAGE (28/05 audit agent code-reviewer)
            # Mesure : entry_slip + exit_slip + pnl_real vs pnl_planned
            # Necessaire pour decision Phase 2 (STOP_LIMIT vs status quo).
            # =================================================================
            tick = TICK_BY_SYMBOL.get(sym, 0.25)
            sign = 1 if pos["direction"] == "LONG" else -1
            entry_planned = pos["entry_price"]
            entry_filled = pos.get("entry_filled_price", entry_planned)  # fallback si capture rate
            entry_slip_t = (entry_filled - entry_planned) / tick * sign

            # Exit planned = sl_initial (si kind=sl) ou tp_price (si kind=tp)
            if kind == "sl":
                exit_planned = pos["sl_initial"]
                # Slip SL favorable si exit_filled > sl_planned cote LONG (= moins de perte)
                # ou exit_filled < sl_planned cote SHORT
                sl_slip_t = (fill_price - exit_planned) / tick * sign  # negatif = slip defavorable
                tp_slip_t = None
            else:  # tp
                exit_planned = pos.get("tp_price", fill_price)
                tp_slip_t = (fill_price - exit_planned) / tick * sign  # negatif = slip defavorable
                sl_slip_t = None

            # PnL planned (si fill PARFAIT a entry_planned + exit_planned) vs real
            pnl_R_planned, _ = compute_pnl_R_usd(
                direction=pos["direction"], entry_price=entry_planned,
                sl_initial=pos["sl_initial"], exit_price=exit_planned,
                symbol=sym,
            )
            pnl_R_slip_delta = pnl_R - pnl_R_planned

            try:
                _emit("BOT3_V3_FILL_SLIPPAGE_REPORT",
                      sym=sym, signal_id=signal_id, direction=pos["direction"],
                      kind=kind,
                      entry_planned=round(entry_planned, 4),
                      entry_filled=round(entry_filled, 4),
                      entry_slip_t=round(entry_slip_t, 2),
                      exit_planned=round(exit_planned, 4),
                      exit_filled=round(fill_price, 4),
                      sl_slip_t=(round(sl_slip_t, 2) if sl_slip_t is not None else None),
                      tp_slip_t=(round(tp_slip_t, 2) if tp_slip_t is not None else None),
                      pnl_R_planned=round(pnl_R_planned, 3),
                      pnl_R_real=round(pnl_R, 3),
                      pnl_R_slip_delta=round(pnl_R_slip_delta, 3))
            except Exception:
                pass  # defensif : ne JAMAIS casser le close trade pour un log slip

            _emit(log_code, sym=sym, level=pos.get("level_name", "?"),
                  side=pos["direction"], exit_price=round(fill_price, 4),
                  pnl_R=round(pnl_R, 3), pnl_usd=round(pnl_usd, 2),
                  duration_bars=duration_bars)

            # Logger JSONL
            self._logger_by_sym[sym].log_trade_close(
                signal_id=signal_id, level=pos.get("level_name", "?"),
                side=pos["direction"], exit_price=fill_price,
                exit_cause=cause, pnl_R=pnl_R, pnl_usd=pnl_usd,
                duration_bars=duration_bars, ts_event_ns=ts_close_ns,
            )

            # Cleanup state interne (OCO oppose deja cancel par dtc_connector)
            for c in (pos.get("parent_cid"), pos.get("tp_cid"), pos.get("sl_cid")):
                if c:
                    self._cid_index.pop(c, None)
            self._position[sym] = None
            self._current_signal_id[sym] = None

        # Etape 2 sprint stabilite : persiste close + cooldown HORS lock (D9)
        try:
            self._positions_persist.remove_position(sym)
            close_ts_iso = self._last_close_ts[sym].isoformat() if self._last_close_ts[sym] else None
            if close_ts_iso:
                self._positions_persist.set_meta(
                    f"last_trade_close_ts_{sym}", close_ts_iso)
                self._positions_persist.set_meta(
                    f"last_trade_close_pnl_R_{sym}", float(pnl_R))
        except Exception as e:
            _emit("BOT_STATE_SAVE_FAILED",
                  bot="bot3_v3",
                  err=f"remove_position_close: {type(e).__name__}: {str(e)[:200]}",
                  file="bot3_v3_state.json")

        # Post-close risk checks (hors lock)
        self._check_post_close_risk(sym, cause)
        if self._pnl_session_usd <= self.RISK_MAX_DD_USD and not self._kill_switch_active:
            _emit("BOT3_V3_KILL_DD_DAILY",
                  pnl_session=round(self._pnl_session_usd, 2),
                  threshold=self.RISK_MAX_DD_USD, kill_switch="ON")
            self.activate_kill_switch(reason="max_dd_session_exceeded")

        return True

    def _check_position_timeout(
        self, sym: str, pos: dict, bar_ts_iso: str,
    ) -> None:
        """Check si position ouverte depuis > TIMEOUT_BARS_POSITION."""
        bar_idx_open = pos.get("bar_idx_open", -1)
        if bar_idx_open < 0:
            return
        current_bar_idx = self._engine_by_sym[sym]._bar_idx
        bars_elapsed = current_bar_idx - bar_idx_open
        if bars_elapsed >= TIMEOUT_BARS_POSITION:
            # Force close
            self._force_close_position(sym, pos, reason="timeout_360_bars")

    def _force_close_position(self, sym: str, pos: dict, reason: str) -> None:
        """Force close position via anti-orphan V2 sequence."""
        # FIX 03/06 (audit cooldown bypass) : MAJ _last_close_ts/_pnl_R sur tout
        # path de close (timeout / kill_switch / shutdown) — sinon cooldown 10/15min
        # jamais declenche -> bot reouvre immediatement.
        self._last_close_ts[sym] = datetime.now(timezone.utc)
        self._last_close_pnl_R[sym] = 0.0  # timeout/force_close = treat as loss for cooldown

        if self.dry_run or self.dtc is None:
            # Dry run cleanup
            ts_close_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
            _emit("BOT3_V3_TRADE_CLOSE_TIMEOUT",
                  sym=sym, level=pos.get("level_name", "?"),
                  side=pos["direction"], exit_price=pos["entry_price"],
                  pnl_R=0.0, timeout_bars=TIMEOUT_BARS_POSITION)
            self._logger_by_sym[sym].log_trade_close(
                signal_id=pos.get("signal_id"), level=pos.get("level_name", "?"),
                side=pos["direction"], exit_price=pos["entry_price"],
                exit_cause="TIMEOUT", pnl_R=0.0, pnl_usd=0.0,
                duration_bars=TIMEOUT_BARS_POSITION, ts_event_ns=ts_close_ns,
            )
            with self._pos_lock:
                for c in (pos.get("parent_cid"), pos.get("tp_cid"), pos.get("sl_cid")):
                    if c:
                        self._cid_index.pop(c, None)
                self._position[sym] = None
                self._current_signal_id[sym] = None
            # Etape 2 sprint stabilite : persiste close + cooldown HORS lock (D9)
            try:
                self._positions_persist.remove_position(sym)
                self._positions_persist.set_meta(
                    f"last_trade_close_ts_{sym}",
                    self._last_close_ts[sym].isoformat() if self._last_close_ts[sym] else None)
                self._positions_persist.set_meta(
                    f"last_trade_close_pnl_R_{sym}", 0.0)
            except Exception as e:
                _emit("BOT_STATE_SAVE_FAILED",
                      bot="bot3_v3",
                      err=f"remove_position_timeout_dryrun: {type(e).__name__}: {str(e)[:200]}",
                      file="bot3_v3_state.json")
            return

        # LIVE : sequence anti-orphan V2 9 etapes
        force_close_market(
            dtc=self.dtc, symbol=sym, pos=pos,
            trade_account=self.trade_account, reason=reason,
            bot_label=BOT_LABEL, emit_fn=_emit,
            cid_prefix=CID_PREFIX, cid_index=self._cid_index,
            cid_index_lock=self._pos_lock,
        )
        # NB : ne touche pas le state interne. handle_dtc_fill fera cleanup
        # via le close_cid fill.

    def _check_post_close_risk(self, sym: str, cause: str) -> None:
        """Active cooldown si 3 SL consec."""
        if cause != "SL":
            return
        if self._n_sl_consec.get(sym, 0) < self.RISK_MAX_SL_CONSEC:
            return
        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.RISK_COOLDOWN_MIN)
        self._cooldown_until[sym] = cooldown_until

    def activate_kill_switch(self, reason: str) -> None:
        """Active kill switch global + force close positions."""
        if self._kill_switch_active:
            return  # idempotent
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        positions_open = sum(1 for s in self.symbols if self._position.get(s) is not None)
        orders_canceled = 0
        for sym in self.symbols:
            pos = self._position.get(sym)
            if pos is not None:
                self._force_close_position(sym, pos, reason=f"kill_switch_{reason}")
                orders_canceled += 1
        _emit("BOT3_V3_KILL_MANUAL",
              reason=reason, positions_flat=positions_open,
              orders_canceled=orders_canceled)

    def _heartbeat_check_emit(self) -> None:
        """Emit heartbeat periodique."""
        if not should_emit_heartbeat(self._last_heartbeat_ts, self.HEARTBEAT_INTERVAL_MIN):
            return
        now = datetime.now(timezone.utc)
        uptime_min = (now - self._boot_ts).total_seconds() / 60
        # Per symbol heartbeat
        for sym in self.symbols:
            engine = self._engine_by_sym[sym]
            engine_stats = engine.get_stats()
            _emit("BOT3_V3_HEARTBEAT",
                  sym=sym,
                  uptime_min=round(uptime_min, 1),
                  n_bars=engine_stats.get("n_bars_processed", 0),
                  n_touches=engine_stats.get("n_touches_detected", 0),
                  n_entries=self._n_entries_emitted,
                  n_trades=self._n_trades_executed,
                  pnl_usd=round(self._pnl_session_usd, 2))
        self._last_heartbeat_ts = now

    def shutdown(self, reason: str = "normal") -> None:
        """Cleanup propre : force_close positions + cancel orders."""
        positions_open = sum(1 for s in self.symbols if self._position.get(s) is not None)
        # Force close si positions actives
        for sym in self.symbols:
            pos = self._position.get(sym)
            if pos is not None:
                self._force_close_position(sym, pos, reason=f"shutdown_{reason}")
        _emit("BOT3_V3_SHUTDOWN",
              reason=reason, positions_open=positions_open)

    # ─────────────────────────────────────────────────────────────────────
    # Helpers extract row
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_ts_iso(row: Any) -> str:
        """Extract ISO timestamp from row."""
        try:
            ts = row.get("ts_event") if hasattr(row, "get") else row["ts_event"]
            if ts is None:
                return ""
            # ts peut etre pd.Timestamp / str / int (ns)
            if hasattr(ts, "isoformat"):
                return ts.isoformat()
            return str(ts)
        except Exception:
            return ""

    @staticmethod
    def _extract_day(row: Any) -> Optional[str]:
        """Extract YYYYMMDD day string for engine day boundary.

        Fix R2 review iter1 : validation stricte regex ^\\d{8}$ + plausibilite
        annee (>= 2020, <= 2030) pour eviter faux YYYYMMDD si ts_event arrive
        en epoch_ns int (str(1748185200000000000)[:8] = "17481852" silencieux).
        """
        import re as _re
        _DAY_RE = _re.compile(r"^(\d{4})(\d{2})(\d{2})$")

        def _validate(s: str) -> Optional[str]:
            """Validate s = "YYYYMMDD" + annee plausible 2020-2030."""
            m = _DAY_RE.match(s)
            if not m:
                return None
            yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not (2020 <= yyyy <= 2030):
                return None
            if not (1 <= mm <= 12):
                return None
            if not (1 <= dd <= 31):
                return None
            return s

        try:
            # session_date_trading prioritaire (UTC-aware session)
            sdt = row.get("session_date_trading") if hasattr(row, "get") else None
            if sdt:
                s = str(sdt).replace("-", "").replace("/", "")
                if len(s) >= 8:
                    validated = _validate(s[:8])
                    if validated:
                        return validated
            # Fallback : ts_event date
            ts = row.get("ts_event") if hasattr(row, "get") else None
            if ts is None:
                return None
            if hasattr(ts, "strftime"):
                return ts.strftime("%Y%m%d")
            # str ISO "2026-05-25T..." -> "20260525..." -> [:8]
            s = str(ts).replace("-", "").replace("/", "")
            if len(s) >= 8:
                validated = _validate(s[:8])
                if validated:
                    return validated
        except Exception:
            pass
        return None


# ════════════════════════════════════════════════════════════════════════
# Factory pour integration paper_v2 (ENV-gated)
# ════════════════════════════════════════════════════════════════════════

def create_from_env(dtc: Optional[Any] = None) -> Optional[Bot3V3ContinuationPaper]:
    """Factory ENV-gated : retourne instance si MIA_BOT3_V3_ENABLED=1.

    ENV vars :
        MIA_BOT3_V3_ENABLED    : 0/1 (default 0 = None retourne)
        MIA_BOT3_V3_DRY_RUN    : 0/1 (default 1)
        MIA_BOT3_V3_TRADE_ACCOUNT : Sim1 (default)
        MIA_BOT3_V3_SYMBOLS    : "NQ" (default, comma-sep si multi)
    """
    enabled = os.environ.get("MIA_BOT3_V3_ENABLED", "0").strip().lower() in ("1", "true", "yes")
    if not enabled:
        return None

    dry_run = os.environ.get("MIA_BOT3_V3_DRY_RUN", "1").strip().lower() in ("1", "true", "yes")
    trade_account = os.environ.get("MIA_BOT3_V3_TRADE_ACCOUNT", "Sim1").strip()
    symbols_str = os.environ.get("MIA_BOT3_V3_SYMBOLS", "NQ").strip()
    symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]

    return Bot3V3ContinuationPaper(
        dtc=dtc, symbols=symbols, dry_run=dry_run,
        trade_account=trade_account,
    )
