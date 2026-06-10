"""bn_v4_paper.py — Paper trader BN V4 (Bot 2 Sim2 Topstep).

Architecture :
  - Lit JSONL live_enriched (lag 60s) via LiveEnrichedReader
  - Detect setups via BNV4Engine (5 phases : trend + zone + density + edge + footprint)
  - Mode dual : grade A++ → TRADE (DTC Sim2), grade A → OBSERVE (log only)
  - DTC bracket OCO via BOT/dtc_connector (reutilise pattern Bot 3 valide)
  - Trail SL Dow pivots (cancel-replace via DTC)
  - Anti-orphelin V2 sequence 9 etapes (cf .claude/rules/orphan-prevention.md)
  - Logger JSONL dedie LOGS/bn_v4/ + log_catalog BN_V4_* via logging_v2

Kill switches ENV :
  MIA_BN_V4_ENABLED=0/1            (default 0 = process exit immediat)
  MIA_BN_V4_DRY_RUN=0/1            (default 1 = log only, pas DTC)
  MIA_BN_V4_TRADE_ACCOUNT=Sim2     (Topstep simulation)
  MIA_BN_V4_SYMBOLS=NQ             (NQ seul pour MVP)

Integration : ce module est instancie + wire depuis
`databento_paper_trader_v2.py` (qui heberge Bot 3 actif). Le paper trader
v2 appelle `bn_v4_trader.poll_cycle()` a chaque iteration de sa main loop.

Source unique de verite des donnees : JSONL live_enriched (decision Jackson
23/05). Cf `project_source_data_unique_jsonl_live_20260523.md`.

PHASE A v0.1 (23/05/2026 nuit) : SKELETON + emits lifecycle uniquement.
  - __init__ avec config + emit BN_V4_BOOT_START
  - load_config + emit BN_V4_CONFIG_LOADED (toutes constantes)
  - boot_ready + emit BN_V4_BOOT_READY
  - shutdown + emit BN_V4_SHUTDOWN
  - poll_cycle() : SKELETON (raise NotImplementedError, sera Phase B)

PHASES suivantes :
  B : poll_cycle reading JSONL + detect setup + emit SETUP_DETECTED
  C : DTC bracket OCO mode TRADE
  D : Trailing SL Dow pivots
  E : Trade close + risk gates
  F : Anti-orphelin sequence 9 etapes
  G : Wiring dans databento_paper_trader_v2.py

Auteur : MIA Trading V2
  v0.1 PHASE A (2026-05-23 nuit) : skeleton + lifecycle emits
"""
from __future__ import annotations

import os
import sys
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

from bot3_paper_common import check_post_trade_cooldown  # 24/05/2026 cooldown post-trade
from bn_v4_engine import (
    BNV4Engine, BNV4Params, TrailingState,
    GRADE_THRESHOLDS,
)
from bn_v4_logger import BNV4Logger
from live_enriched_reader import LiveEnrichedReader

# DTC constants (BUY=1, SELL=2 ; cf BOT/dtc_connector.py)
try:
    from dtc_connector import BUY as DTC_BUY, SELL as DTC_SELL
except ImportError:
    DTC_BUY = 1
    DTC_SELL = 2

# Symbol -> SC contract mapping
# 02/06 Jackson directive finale "TOUT EN MINI PLUS SIMPLE" :
# SC reçoit MINI partout (NQM26, ESM26). BN V4 = 1 E-mini par trade
# (quantity=1 hardcodé ligne ~669, design BN V4 "couper la poire en 2").
# Si Jackson veut sizing dynamique BN V4 : ajouter GUARD_RAILS_BN_V4
# dans bot3_config.py et propager. Dette R2 actuelle : qty hardcodé.
SYMBOL_TO_CONTRACT = {
    "NQ": "NQM26-CME",            # E-mini NQ $5.00/tick (rollback 03/06)
    "ES": "ESM26-CME",            # E-mini standard $12.50/tick
    "MGC": "MGCM26-CMECOMEX",     # Gold micro $1.00/tick
}

# Tick size par symbol (NQ/ES = 0.25, MGC = 0.10)
TICK_BY_SYMBOL = {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}

# Tick value $/tick (PER CONTRACT)
# 03/06 ROLLBACK : 1 NQ E-mini ($5/tick) + 1 ES E-mini ($12.50) + 1 MGC Micro.
TICK_VALUE_USD = {"NQ": 5.00, "ES": 12.50, "MGC": 1.00}

# TP cap securite distant (vraie sortie = trail Dow pivots)
TP_CAP_TICKS = 200

# 28/05 FIX P0/P1 bilan jour Bot 2 BN V4 : SL 8 ticks bruit pur (0/3 WIN -$40).
# Jackson directive : approche BN V4 = SL LARGES setups A++. SL < floor = bar entry
# trop etroite = noise → REJETER setup proprement via GATE_SL_RISK_BLOCK existant
# (make_trailing_state raise ValueError si risk_ticks < min_risk_ticks).
# Pattern lessons.md : NQ swing ~20t typique, ES swing ~16t typique sur entry_bar
# Battle Navale. Floor per-symbol via BNV4Params override per-engine (vs global=4).
SYMBOL_MIN_RISK_TICKS = {
    "NQ": 20,   # 5 pts NQ E-mini = ATR baseline 1m
    "ES": 16,   # 4 pts ES E-mini = ATR baseline 1m
    "MGC": 20,  # 2 USD GC = ATR baseline 1m Gold
}

# Logging v2 (codes log_catalog BN_V4_*)
try:
    from logging_v2 import get_logger
    _v2log = get_logger("bn_v4_paper", process="paper_v2")
except ImportError:
    _v2log = None


__version__ = "0.1.0-PHASE_A"


def _emit(code: str, **ctx) -> None:
    """Helper emit via logging_v2 (best-effort, no-op si module absent)."""
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception as e:
            # Fail-safe : print stderr (logging_v2 lui-meme casse)
            print(f"[BN_V4_EMIT_FAIL] code={code} err={e}", file=sys.stderr)


class BNV4PaperTrader:
    """Paper trader BN V4 (Bot 2 Sim2).

    Lifecycle :
        1. __init__(config) : load config, valide Params (fail-loud)
        2. boot() : init DTC + reader + emit BOOT_*
        3. poll_cycle() : appele depuis main loop paper_v2 (~30s interval)
        4. shutdown(reason) : flatten Sim2 + cancel orders + emit SHUTDOWN

    Etat persistant :
        - position : Optional[dict] (1 position max Sim2)
        - trail_state : Optional[TrailingState]
        - signal_id : str (lifecycle linkage logger JSONL)
        - risk : DD intra-session, SL consecutifs

    PHASE A : seulement init + lifecycle emits. poll_cycle = NotImplementedError.
    """

    def __init__(
        self,
        dtc: Optional[Any] = None,
        symbols: Optional[list] = None,
        dry_run: bool = True,
        trade_account: str = "Sim2",
        params: Optional[BNV4Params] = None,
    ):
        """
        Args:
            dtc : DTCConnector instance (depuis paper_v2). None = dry_run force.
            symbols : list symboles ("NQ" pour MVP).
            dry_run : True = log only, pas DTC.
            trade_account : compte cible ("Sim2" Topstep).
            params : BNV4Params override (None = defaults config 23/05).
        """
        _emit("BN_V4_BOOT_START",
              sym=",".join(symbols) if symbols else "NQ",
              dry_run=int(dry_run),
              trade_account=trade_account,
              mode="paper")

        # Config (default = 23/05 optimal : A++ + open + trend_aligned)
        if params is None:
            params = BNV4Params(
                grade_min="A++",
                observation_grade_min="A",  # Mode dual : A++ trade, A observe
                require_open_window=True,
                require_long_trend_aligned=True,
                footprint_min_signals=1,
                max_risk_ticks=40,
                min_risk_ticks=4,
            )
        # __post_init__ validation deja effectue par dataclass

        # 29/05 FIX BETA Jackson : kill switch env var pour disable runtime sans redeploy.
        # Si BN_V4_SLOPE_60_THRESHOLD set, override le seuil. Valeur >= 999.0 desactive
        # effectivement le gate (slope mean ne peut jamais depasser 999 en pratique).
        # Permet rollback rapide si overfitting J+7 confirme : nssm restart MIA-Bot2-Paper
        # avec BN_V4_SLOPE_60_THRESHOLD=999.0 sans redeploy code.
        _slope_60_env = os.environ.get("BN_V4_SLOPE_60_THRESHOLD")
        if _slope_60_env:
            try:
                override_val = float(_slope_60_env)
                params.slope_mean_60_veto_threshold = override_val
                _emit("BN_V4_PARAM_OVERRIDE_ENV",
                      param="slope_mean_60_veto_threshold",
                      override_value=override_val,
                      source="env_BN_V4_SLOPE_60_THRESHOLD")
            except ValueError:
                _emit("BN_V4_PARAM_OVERRIDE_ENV_FAIL",
                      param="slope_mean_60_veto_threshold",
                      raw_value=_slope_60_env,
                      err="not a valid float")

        self.params = params
        self.symbols = symbols or ["NQ"]
        self.dry_run = dry_run or (dtc is None)
        self.trade_account = trade_account
        self.dtc = dtc

        # Engine BN V4 avec log_fn injection (gates emit vers logging_v2)
        self._engine_by_sym: dict[str, BNV4Engine] = {}
        for sym in self.symbols:
            self._engine_by_sym[sym] = BNV4Engine(
                params=self.params,
                symbol=sym,
                log_fn=_emit,
            )

        # Reader JSONL live_enriched (1 par symbol)
        self._reader_by_sym: dict[str, LiveEnrichedReader] = {}
        for sym in self.symbols:
            self._reader_by_sym[sym] = LiveEnrichedReader(
                symbol=sym,
                window_bars=480,
                warn_stale_sec=180,
            )

        # Logger JSONL dedie (1 par symbol -> LOGS/bn_v4/)
        self._logger_by_sym: dict[str, BNV4Logger] = {}
        for sym in self.symbols:
            self._logger_by_sym[sym] = BNV4Logger(symbol=sym)

        # Etat positions (protege par _pos_lock contre race conditions DTC fill)
        self._position: dict[str, Optional[dict]] = {sym: None for sym in self.symbols}
        self._trail_state: dict[str, Optional[TrailingState]] = {sym: None for sym in self.symbols}
        self._current_signal_id: dict[str, Optional[str]] = {sym: None for sym in self.symbols}
        self._pos_lock = threading.Lock()

        # Index ClientOrderID -> {sym, kind, signal_id} pour _handle_dtc_fill
        # Pattern Bot 3 _bot3_cid_index (cf paper_v2.py:463).
        self._bn_v4_cid_index: dict[str, dict] = {}

        # Risk session (RAZ par boot, persiste si state file ajoute Phase E)
        self._n_sl_consec: dict[str, int] = {sym: 0 for sym in self.symbols}
        self._pnl_session_usd: float = 0.0
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""

        # PHASE E : risk gates state
        # Cooldown apres 3 SL consec : cooldown_until[sym] = datetime ou None
        self._cooldown_until: dict[str, Optional[datetime]] = {sym: None for sym in self.symbols}
        # Config risk (overridable)
        # 24/05/2026 PM (Jackson directive paper phase) : cooldown SL consec OFF
        # (seuil 999 effectif). DD elargi -5000 (paper = max data collection).
        # Re-activer 3 / -200 quand passe live AMP.
        self.RISK_MAX_SL_CONSEC = 999            # PAPER : cooldown SL consec off
        self.RISK_COOLDOWN_MIN = 60              # vestigial
        self.RISK_MAX_DD_USD = -5000.0           # PAPER : DD large (collecte max)

        # Cooldown global post-trade per-sym (24/05/2026 PM Jackson directive).
        # 10min apres gain, 15min apres perte. Empeche back-to-back trades.
        self._last_close_ts: dict[str, Optional[datetime]] = {sym: None for sym in self.symbols}
        self._last_close_pnl_R: dict[str, Optional[float]] = {sym: None for sym in self.symbols}

        # Heartbeat / data stats periodic
        self._last_heartbeat_ts: Optional[datetime] = None
        self.HEARTBEAT_INTERVAL_MIN = 10

        # Stats lifecycle
        self._n_bars_processed: int = 0
        self._n_setups_detected: int = 0
        self._n_trades_executed: int = 0
        self._boot_ts = datetime.now(timezone.utc)

        # Emit CONFIG_LOADED avec TOUTES les constantes (fix P0 reviewer : constantes
        # retirees des gate templates -> recapitulees ici 1 fois au boot)
        _emit("BN_V4_CONFIG_LOADED",
              grade_min=self.params.grade_min,
              observation_grade_min=self.params.observation_grade_min,
              require_open=int(self.params.require_open_window),
              require_trend_align=int(self.params.require_long_trend_aligned),
              footprint_min=self.params.footprint_min_signals,
              n_levels_min=self.params.n_levels_min,
              vol_ratio_min=self.params.vol_ratio_min,
              max_risk_ticks=self.params.max_risk_ticks,
              min_risk_ticks=self.params.min_risk_ticks)

    def boot_ready(self) -> None:
        """Confirme boot ready apres validation pre-flight (DTC, etc.)."""
        for sym in self.symbols:
            _emit("BN_V4_BOOT_READY",
                  sym=sym,
                  dtc_state=("DRY_RUN" if self.dry_run else "CONNECTED"),
                  reader_state="ready")

    def poll_cycle(self) -> None:
        """Cycle principal BN V4 (appele depuis paper_v2 main loop).

        PHASE B : detection setups + lifecycle logging. Pas de DTC (Phase C).

        Pour chaque symbol :
          1. reader.load_rolling_window() -> df rolling
          2. Si pas de data ou stale (> 180s) -> emit BAR_STALE + skip
          3. Si feature critique NaN 3 bars consec -> emit FEATURE_DEGRADED + skip
          4. Si position active -> skip (trail viendra Phase D)
          5. Sinon : detect_setup LONG + SHORT
             - mode TRADE -> log_setup_detected (Phase C placera bracket DTC)
             - mode OBSERVE -> log_setup_detected mode OBSERVE (jamais DTC)
          6. Increment compteurs
        """
        # Fix P1#1 reviewer iter3 23/05 : heartbeat AVANT check kill_switch.
        # Sans ce fix : apres activate_kill_switch, plus aucun BN_V4_HEARTBEAT
        # = watchdog ne sait pas si process tourne encore. Loss telemetry total.
        # Solution : heartbeat continue meme sous kill switch.
        self.heartbeat_check()

        if self._kill_switch_active:
            return

        for sym in self.symbols:
            try:
                self._poll_cycle_symbol(sym)
            except Exception as e:
                # Loop error fail-soft : un crash sur sym A ne tue pas sym B
                _emit("BN_V4_LOOP_ERROR", sym=sym, err=f"{type(e).__name__}: {str(e)[:300]}")
                self._logger_by_sym[sym].log_error(
                    self._current_signal_id.get(sym),
                    error_code="POLL_CYCLE_EXCEPTION",
                    error_msg=f"{type(e).__name__}: {str(e)[:500]}",
                )

    def _poll_cycle_symbol(self, sym: str) -> None:
        """Poll cycle pour 1 symbol."""
        reader = self._reader_by_sym[sym]
        engine = self._engine_by_sym[sym]
        logger = self._logger_by_sym[sym]

        # 1. Lecture rolling window JSONL
        df = reader.load_rolling_window()
        if df is None:
            # Reader pas pret (aucune bar disponible) — pas de heartbeat possible
            return

        # 24/05/2026 PM (Jackson "BOT 2 ETAINT") : warmup ne doit plus return silent.
        # Le watchdog + dashboard regardaient le mtime du JSONL bn_v4 pour
        # detecter paper_trader_alive. Pendant le warmup 240 bars (~4h Asia),
        # le bot ne loggue rien → STATE FROZEN apparent. Fix : log heartbeat
        # warmup pour que le JSONL soit ecrit en continu meme avant l'edge.
        if len(df) < self.params.trend_long_lookback:
            last_bar_warmup = df.iloc[-1]
            ts_event_ns_w = int(last_bar_warmup.get("ts_event_ns", 0))
            logger.log_bar_processed(sym, ts_event_ns_w,
                                       float(last_bar_warmup.get("close", 0.0)),
                                       ctx={"warmup": True,
                                            "bars": int(len(df)),
                                            "target": int(self.params.trend_long_lookback)})
            # Emit warmup status toutes les 30 bars (anti spam)
            if int(len(df)) % 30 == 0:
                _emit("BN_V4_WARMUP_IN_PROGRESS",
                      sym=sym, bars=int(len(df)),
                      target=int(self.params.trend_long_lookback),
                      pct=round(100.0 * len(df) / self.params.trend_long_lookback, 1))
            return

        # 2. Check staleness derniere bar
        age_sec = reader.get_last_bar_age_seconds()
        if age_sec > reader.warn_stale_sec:
            _emit("BN_V4_BAR_STALE",
                  sym=sym, age_sec=round(age_sec, 1),
                  threshold_sec=reader.warn_stale_sec)
            return

        # 3. Check feature critique non-NaN sur derniere bar
        last_bar = df.iloc[-1]
        critical_features = [
            "vwap_slope_10",
            "n_color_up_cluster_within_0_2pct",
            "n_edge_buy_active",
            "close", "high", "low",
        ]
        nan_features = [
            f for f in critical_features
            if f in df.columns and bool(df[f].iloc[-1] != df[f].iloc[-1])  # NaN check
        ]
        if nan_features:
            # Compter consec NaN sur les 3 dernieres bars pour eviter spam
            n_consec_nan = 0
            for f in nan_features:
                last3 = df[f].iloc[-3:]
                n_nan = int((last3 != last3).sum())
                n_consec_nan = max(n_consec_nan, n_nan)
            if n_consec_nan >= 3:
                _emit("BN_V4_FEATURE_DEGRADED",
                      sym=sym, feature=",".join(nan_features[:3]),
                      bars_nan=n_consec_nan)
                return
            # 1-2 NaN consec : skip silencieux ce cycle (recovery probable)
            return

        # 4. Increment counter bars
        self._n_bars_processed += 1
        ts_event_ns = int(last_bar.get("ts_event_ns", 0))
        logger.log_bar_processed(sym, ts_event_ns,
                                   float(last_bar.get("close", 0.0)))

        # 5. Si position active : update trailing + check timeout (Phase D)
        if self._position.get(sym) is not None:
            self._update_trail_if_needed(sym, last_bar)
            return

        # 6. Detection setup LONG puis SHORT (1 max par cycle pour anti double)
        for direction in ("long", "short"):
            setup = engine.detect_setup(df, len(df) - 1, direction)
            if setup is None:
                continue

            mode = setup.get("mode", "TRADE")
            self._handle_setup_detected(sym, setup, mode)
            break    # 1 setup max par cycle (anti double-tirage LONG+SHORT)

    def _handle_setup_detected(self, sym: str, setup: dict, mode: str) -> None:
        """Traitement setup detecte (TRADE ou OBSERVE).

        PHASE B : log only (pas de DTC). Phase C ajoutera bracket DTC pour mode=TRADE.
        """
        self._n_setups_detected += 1
        logger = self._logger_by_sym[sym]

        # Score breakdown pour audit J+1
        score_breakdown = {
            "grade": setup.get("grade"),
            "density": setup.get("density"),
            "n_levels": setup.get("n_levels"),
            "direction": setup.get("direction"),
            "mode": mode,
        }

        # Generer signal_id via logger JSONL dedie
        signal_id = logger.log_setup_detected(setup, score_breakdown=score_breakdown)
        self._current_signal_id[sym] = signal_id

        # Emit log_catalog
        _emit("BN_V4_SETUP_DETECTED",
              sym=sym,
              direction=setup.get("direction"),
              grade=setup.get("grade"),
              density=setup.get("density"),
              n_levels=setup.get("n_levels"),
              mode=mode,
              entry_price=setup.get("entry_price"))

        if mode == "TRADE":
            # Veto eco_calendar (24/05 Jackson : aligner sur Bot 1 legacy regle 15min RTH).
            # is_blocked_combined() couvre eco events (FOMC/NFP/CPI/PCE), Open US
            # 09:15-09:45 ET, Post-MOC 15:30-18:15 ET (lun-jeu), weekend.
            # Mode OBSERVE continue a logger sans trader (passe ce gate volontairement).
            # R1 code-reviewer 24/05 : fail-CLOSED si module HS (mieux rater un trade
            # que trader pendant FOMC). Diverge volontairement de Bot 1 legacy fail-open.
            try:
                from CORE import eco_calendar as _eco
                _blocked, _reason, _until = _eco.is_blocked_combined()
            except Exception as _e:
                _emit("ECO_CALENDAR_FAIL_FAILCLOSED",
                      sym=sym, bot="bn_v4", err=str(_e)[:200])
                _blocked, _reason = True, "eco_calendar_module_error"
            if _blocked:
                _emit("BN_V4_SKIP_ECO_BLOCK",
                      sym=sym, direction=setup.get("direction"),
                      grade=setup.get("grade"), reason=_reason or "?")
                return

            # Veto cooldown post-trade global (24/05/2026 PM Jackson : 10min win, 15min loss).
            _cd_blocked, _cd_rem, _cd_reason = check_post_trade_cooldown(
                self._last_close_ts.get(sym),
                self._last_close_pnl_R.get(sym),
                datetime.now(timezone.utc),
            )
            if _cd_blocked:
                _emit("BN_V4_SKIP_POST_TRADE_COOLDOWN",
                      sym=sym, direction=setup.get("direction"),
                      grade=setup.get("grade"),
                      reason=_cd_reason, remaining_sec=_cd_rem)
                return

            # PHASE E : risk gates AVANT bracket (Jackson directive "TOUT TRAKER")
            if not self._check_risk_gates_for_trade(sym, setup):
                # _check_risk_gates_for_trade emit deja BN_V4_SKIP_* approprie
                return

            # Position deja ouverte sur ce sym ?
            if self._position.get(sym) is not None:
                pos_dir = self._position[sym].get("direction", "?")
                _emit("BN_V4_SKIP_POSITION_ACTIVE",
                      sym=sym,
                      direction=setup.get("direction"),
                      direction_pos=pos_dir)
                return

            # PHASE C : place bracket DTC (sauf dry_run = log only)
            if self.dry_run or self.dtc is None:
                # Dry run : log skip + simul ouverture (anti spam, INFO niveau)
                _emit("BN_V4_SKIP_DRY_RUN",
                      sym=sym, direction=setup.get("direction"),
                      entry_price=setup.get("entry_price"))
                self._n_trades_executed += 1
                _emit("BN_V4_TRADE_OPEN",
                      sym=sym, direction=setup.get("direction"),
                      grade=setup.get("grade"),
                      entry_price=setup.get("entry_price"),
                      sl="DRY_RUN", risk_ticks="DRY_RUN", qty=1)
            else:
                self._place_bracket_dtc(sym, setup, signal_id)
        elif mode == "OBSERVE":
            # Mode observation : log only, jamais DTC.
            _emit("BN_V4_OBSERVATION_LOG",
                  sym=sym,
                  direction=setup.get("direction"),
                  density=setup.get("density"),
                  entry_price=setup.get("entry_price"),
                  pnl_simul_R=None)    # rempli au close simul (Phase D)
        elif mode == "OBSERVE_WINDOW":
            # WINDOW_OBSERVE (27/05) : setup A++ HORS open_windows. Loggue dans
            # JSONL dedie pour collecte 30j (decision data-driven d'elargir
            # OPEN_WINDOWS). Pas d'ordre DTC, pas de gates eco/cooldown/risk
            # ni anti-orphelin. Strictement isole du flow TRADE.
            _emit("BN_V4_OUTSIDE_WINDOW_LOG",
                  sym=sym,
                  direction=setup.get("direction"),
                  grade=setup.get("grade"),
                  density=setup.get("density"),
                  entry_price=setup.get("entry_price"),
                  signal_id=signal_id)
            try:
                self._log_outside_window_setup(sym, setup, signal_id)
            except Exception as _e:
                # Defensif : si helper crash, on ne casse PAS le bot.
                _emit("BN_V4_OUTSIDE_WINDOW_LOG_FAIL",
                      sym=sym, err=str(_e)[:200])
        # mode inconnu : ignore (shouldnt happen apres __post_init__ validation)

    def shutdown(self, reason: str = "normal") -> None:
        """Cleanup propre. PHASE F ajoutera anti-orphelin V2 sequence."""
        positions_open = sum(
            1 for sym in self.symbols if self._position.get(sym) is not None
        )
        _emit("BN_V4_SHUTDOWN", reason=reason, positions_open=positions_open)

    # ────────────────────────────────────────────────────────────────────
    # WINDOW_OBSERVE (27/05) : log setups A++ hors-fenetres pour analyse 30j
    # ────────────────────────────────────────────────────────────────────

    def _log_outside_window_setup(self, sym: str, setup: dict, signal_id: str) -> None:
        """Log setup A++ hors OPEN_WINDOWS dans JSONL dedie (mode OBSERVE_WINDOW).

        Isole strictement du flow TRADE : pas de DTC, pas de gates eco/cooldown,
        pas d'anti-orphelin. Si crash -> defensif (caller catch). Objectif :
        constituer un dataset 30j pour comparer PF in-window vs out-of-window
        avant decision d'elargir OPEN_WINDOWS_MIN_ET.

        Fichier : LOGS/bn_v4_window_observe/bn_v4_observe_YYYYMMDD.jsonl
        Format : 1 ligne JSON par setup avec ts, sym, direction, grade, density,
        n_levels, entry_price, signal_id (pour join future simul PnL).
        """
        import json
        import os
        from pathlib import Path
        from datetime import datetime, timezone

        # R1 code-reviewer 27/05 : path via MIA_LOG_DIR env var (existant nssm
        # config Bot 2/Bot 4). Fallback relatif si var absente (= cas backtest
        # local D:\ ou dev) -> evite crash silencieux sur mauvais drive.
        log_dir_env = os.environ.get("MIA_LOG_DIR", "")
        if log_dir_env:
            log_root = Path(log_dir_env) / "bn_v4_window_observe"
        else:
            # Fallback : relatif au CWD (dev local sans env var)
            log_root = Path("LOGS") / "bn_v4_window_observe"
        log_root.mkdir(parents=True, exist_ok=True)
        ts_utc = datetime.now(timezone.utc)
        date_str = ts_utc.strftime("%Y%m%d")
        log_path = log_root / f"bn_v4_observe_{date_str}.jsonl"

        record = {
            "ts": ts_utc.isoformat(),
            "sym": sym,
            "signal_id": signal_id,
            "direction": setup.get("direction"),
            "grade": setup.get("grade"),
            "density": setup.get("density"),
            "n_levels": setup.get("n_levels"),
            "entry_price": setup.get("entry_price"),
            "top_level": setup.get("top_level"),
            "outside_window": True,
            "mode": "OBSERVE_WINDOW",
            # PnL simul rempli en post-process via script offline (Phase D-like).
            # Pas calcule ici pour eviter dependance circulaire avec params SL/TP.
            "pnl_simul_R": None,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    # ────────────────────────────────────────────────────────────────────
    # PHASE C : DTC bracket OCO (mode TRADE)
    # ────────────────────────────────────────────────────────────────────

    def _place_bracket_dtc(self, sym: str, setup: dict, signal_id: str) -> None:
        """Place bracket OCO DTC pour setup mode TRADE.

        Pattern Bot 3 valide (cf paper_v2.py:2223 _bot3_execute_trade) :
          1. compute SL initial + init TrailingState (fail-loud P0.2/P0.3)
          2. dtc.send_market_order (parent + TP + SL OCO atomique)
          3. Register tracking interne _bn_v4_cid_index
          4. Emit BN_V4_BRACKET_PLACED + BN_V4_TRADE_OPEN
          5. Log JSONL dedie via BNV4Logger

        Pas d'appel direct a register_oco_pair : send_market_order le fait
        deja (dtc_connector.py:384).

        Anti-orphelin : si send_market_order retourne ("", "", "") (parent fill
        timeout 2s ou DTC down), pas de tracking interne ouvert.
        """
        direction = setup["direction"]
        entry_price_signal = float(setup["entry_price"])
        engine = self._engine_by_sym[sym]
        tick = TICK_BY_SYMBOL.get(sym, 0.25)

        # 1. Recuperer entry_bar depuis reader pour OHLC SL/risk calc
        df = self._reader_by_sym[sym].load_rolling_window()
        if df is None or len(df) == 0:
            _emit("BN_V4_LOOP_ERROR", sym=sym,
                  err="bracket_failed: df None apres setup detect (race?)")
            return
        entry_bar = df.iloc[-1]    # derniere bar = celle qui a fire le setup
        entry_ts_ns = int(entry_bar.get("ts_event_ns", 0) or 0)

        # 2. Compute SL initial + trail state (fail-loud)
        # 26/05/2026 fix B Jackson : ValueError sl_guard etait emit LOOP_ERROR
        # CRITIQUE -> polluait dashboard. Maintenant emit GATE_SL_RISK_BLOCK
        # MAJEUR/decisions (coherent avec autres GATE_*_BLOCK BN V4). Bot skip
        # le setup proprement sans crash, et continue de processer les bars.
        try:
            sl_initial = engine.compute_initial_sl(setup, entry_bar)
            trail = engine.make_trailing_state(
                direction, entry_bar, entry_price_signal,
                entry_bar_idx=len(df) - 1,
            )
        except ValueError as e:
            _emit("BN_V4_GATE_SL_RISK_BLOCK", sym=sym,
                  direction=direction,
                  entry=entry_price_signal,
                  err=f"{type(e).__name__}: {str(e)[:200]}")
            self._logger_by_sym[sym].log_error(
                signal_id, error_code="SL_GUARD_FAIL",
                error_msg=f"{type(e).__name__}: {e}",
            )
            return

        risk_ticks = abs(entry_price_signal - sl_initial) / tick

        # 3. TP cap securite distant (200 ticks)
        if direction == "long":
            tp_cap = entry_price_signal + TP_CAP_TICKS * tick
            side = DTC_BUY
        else:
            tp_cap = entry_price_signal - TP_CAP_TICKS * tick
            side = DTC_SELL

        sl_ticks_int = int(round(risk_ticks))
        contract = SYMBOL_TO_CONTRACT.get(sym, f"{sym}M26-CME")

        # 4. send_market_order pattern Bot 3 (avec anti-slip + parent_fill wait)
        try:
            parent_id, tp_cid, sl_cid = self.dtc.send_market_order(
                symbol=contract,
                side=side,
                quantity=1,
                sl_price=sl_initial,
                tp_price=tp_cap,
                trade_account=self.trade_account,    # "Sim2" EXPLICITE
                signal_ref_price=entry_price_signal,
                sl_ticks=sl_ticks_int,
                tp_ticks=TP_CAP_TICKS,
                tick_size=tick,
                auto_reprice_threshold_ticks=5,
            )
        except Exception as e:
            _emit("BN_V4_LOOP_ERROR", sym=sym,
                  err=f"dtc_send_market_order_exception: {type(e).__name__}: {str(e)[:200]}")
            return

        if not parent_id:
            # Parent fill timeout 2s OU DTC down (cf dtc_connector ligne 290-311)
            # Fix P0#2 reviewer iter3 23/05 : wire BN_V4_SETUP_DTC_ABORT (etait
            # code orphelin sans emit). Trace critique anti-orphelin J+1.
            _emit("BN_V4_SETUP_DTC_ABORT",
                  sym=sym, direction=direction,
                  reason="parent_id_empty_fill_timeout_or_dtc_down")
            self._logger_by_sym[sym].log_error(
                signal_id, error_code="BRACKET_PARENT_FILL_FAILED",
                error_msg=f"send_market_order returned empty parent_id (DTC down or 2s timeout) dir={direction}",
            )
            return

        # 5. Register tracking interne sous lock (anti race avec _handle_dtc_fill)
        with self._pos_lock:
            self._bn_v4_cid_index[parent_id] = {
                "sym": sym, "kind": "parent", "signal_id": signal_id,
            }
            self._bn_v4_cid_index[tp_cid] = {
                "sym": sym, "kind": "tp", "signal_id": signal_id,
            }
            self._bn_v4_cid_index[sl_cid] = {
                "sym": sym, "kind": "sl", "signal_id": signal_id,
            }

            self._position[sym] = {
                "parent_cid": parent_id,
                "tp_cid": tp_cid,
                "sl_cid": sl_cid,
                "direction": direction,
                "entry_price": entry_price_signal,
                "sl_initial": sl_initial,
                "sl_current": sl_initial,
                "tp_cap": tp_cap,
                "risk_ticks": risk_ticks,
                "qty": 1,
                "signal_id": signal_id,
                "ts_open": datetime.now(timezone.utc).isoformat(),
                "ts_open_ns": entry_ts_ns,
            }
            self._trail_state[sym] = trail
            self._current_signal_id[sym] = signal_id
            self._n_trades_executed += 1

        # 6. Emit logs
        _emit("BN_V4_BRACKET_PLACED",
              sym=sym, parent_cid=parent_id[:20],
              sl_cid=sl_cid[:20], tp_cid=tp_cid[:20])
        _emit("BN_V4_TRADE_OPEN",
              sym=sym, direction=direction,
              grade=setup.get("grade"),
              entry_price=entry_price_signal,
              sl=sl_initial,
              risk_ticks=round(risk_ticks, 1),
              qty=1)

        # 7. Logger JSONL dedie
        self._logger_by_sym[sym].log_trade_open(
            signal_id, entry_ts_ns,
            entry_price_signal, sl_initial, risk_ticks, qty=1,
        )

    def _handle_dtc_fill_bn_v4(self, msg: dict, cid: str) -> bool:
        """Hook ORDER_UPDATE Type 301 status=7 (Filled) pour ordres BN V4.

        Pattern Bot 3 _bot3_handle_dtc_fill (paper_v2.py:557).

        NB : dtc_connector._handle_order_update cancel deja le TP/SL oppose
        via OCO manuel (register_oco_pair). Notre role ici = cleanup state
        interne + emit close logs + logger JSONL.

        Args:
            msg : dict Type 301 ORDER_UPDATE (LastFillPrice, AverageFillPrice,
                  OrderStatus, ClientOrderID, etc.)
            cid : ClientOrderID extrait du msg

        Returns:
            True si cid traite (etait dans notre index), False sinon (laisse
            les autres handlers traiter).
        """
        if cid not in self._bn_v4_cid_index:
            return False

        entry = self._bn_v4_cid_index[cid]
        sym = entry["sym"]
        kind = entry["kind"]
        signal_id = entry["signal_id"]

        # GUARD #1 (code-reviewer action #3) : filtrer status != 7 (Filled).
        try:
            order_status = int(msg.get("OrderStatus", 0))
        except (TypeError, ValueError):
            order_status = 0
        if order_status != 7:
            _emit("BN_V4_FILL_PRICE_INVALID",
                  sym=sym, cid=cid, kind=kind, signal_id=signal_id,
                  msg_status=order_status,
                  last_fill_price=msg.get("LastFillPrice"),
                  avg_fill_price=msg.get("AverageFillPrice"),
                  order_type=msg.get("OrderType"),
                  qty_filled=msg.get("FilledQuantity"),
                  msg_keys=list(msg.keys())[:15])
            return True

        # Fill price (LastFillPrice > AverageFillPrice > 0 fallback)
        try:
            fill_price = float(msg.get("LastFillPrice", 0)) or float(msg.get("AverageFillPrice", 0))
        except (TypeError, ValueError):
            fill_price = 0.0

        # GUARD #2 24/05/2026 PM (incident ghost trade $59542 Bot 3 v4) :
        # fill_price=0 produit un PnL aberrant. Refuser close + emit ctx complet.
        if fill_price <= 0:
            _emit("BN_V4_FILL_PRICE_INVALID",
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
                # Race condition : position deja cleanup (autre fill plus tot)
                return True

            if kind == "parent":
                # Parent fill = ouverture, position deja registered. Nothing to do.
                # (anti-slip metric est gere par send_market_order interne)
                return True

            # SL ou TP fill = trade close
            ts_close_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
            ts_open_ns = pos.get("ts_open_ns", 0)
            duration_bars = max(1, int((ts_close_ns - ts_open_ns) / 60_000_000_000)) if ts_open_ns else 0

            risk_pts = abs(pos["entry_price"] - pos["sl_initial"])
            if pos["direction"] == "long":
                pnl_pts = fill_price - pos["entry_price"]
            else:
                pnl_pts = pos["entry_price"] - fill_price
            pnl_R = pnl_pts / max(risk_pts, 0.01)
            if sym not in TICK_VALUE_USD:
                raise ValueError(
                    f"BN V4 pnl_usd: unknown symbol '{sym}' (supported: {list(TICK_VALUE_USD.keys())}). "
                    "Fail-loud post-rollback 02/06 MINI."
                )
            qty = int(pos.get("qty") or 1)
            pnl_usd = pnl_pts * TICK_VALUE_USD[sym] / TICK_BY_SYMBOL[sym] * qty
            self._pnl_session_usd += pnl_usd

            # Update cooldown state post-trade (24/05/2026 PM Jackson directive).
            self._last_close_ts[sym] = datetime.now(timezone.utc)
            self._last_close_pnl_R[sym] = pnl_R

            if kind == "sl":
                # SL hit : initial vs trailing
                # Fix P0#1 reviewer iter3 23/05 : n_pivots_confirmed vit dans
                # self._trail_state[sym] (TrailingState), pas pos dict.
                # Avant fix : tous SL trailing logges sl_trail_0 = audit degradee.
                if pos.get("sl_current") != pos.get("sl_initial"):
                    trail = self._trail_state.get(sym)
                    n_piv = trail.n_pivots_confirmed if trail is not None else 0
                    cause = f"sl_trail_{n_piv}"
                else:
                    cause = "sl_initial"
                log_code = "BN_V4_TRADE_CLOSE_SL"
                # SL hit = compteur consec
                self._n_sl_consec[sym] = self._n_sl_consec.get(sym, 0) + 1
            elif kind == "tp":
                cause = "tp_cap"   # rare (cap 200 ticks)
                log_code = "BN_V4_TRADE_CLOSE_SL"   # convention
                self._n_sl_consec[sym] = 0    # reset compteur SL consec
            else:
                # kind inconnu : log warning + cleanup
                _emit("BN_V4_LOOP_ERROR", sym=sym,
                      err=f"handle_fill_unknown_kind: {kind}")
                return True

            # Emit logs
            _emit(log_code,
                  sym=sym, direction=pos["direction"],
                  exit_price=fill_price,
                  pnl_R=round(pnl_R, 3),
                  duration_bars=duration_bars)

            # Logger JSONL dedie
            self._logger_by_sym[sym].log_trade_close(
                signal_id, ts_close_ns, fill_price, cause,
                pnl_R=round(pnl_R, 4),
                pnl_usd=round(pnl_usd, 2),
                duration_bars=duration_bars,
            )

            # Cleanup state interne (OCO oppose deja cancelled par dtc_connector)
            for c in (pos.get("parent_cid"), pos.get("tp_cid"), pos.get("sl_cid")):
                if c:
                    self._bn_v4_cid_index.pop(c, None)
            self._position[sym] = None
            self._trail_state[sym] = None
            self._current_signal_id[sym] = None

        # Check post-close risk gates (hors lock) : 3 SL consec -> cooldown
        self._check_post_close_risk(sym, cause)

        # Check DD session (peut declencher kill switch global)
        if self._pnl_session_usd <= self.RISK_MAX_DD_USD and not self._kill_switch_active:
            _emit("BN_V4_RISK_MAX_DD_HIT",
                  pnl_session=round(self._pnl_session_usd, 2),
                  threshold=self.RISK_MAX_DD_USD,
                  kill_switch="ON")
            self.activate_kill_switch(reason="max_dd_session_exceeded")

        return True

    # ────────────────────────────────────────────────────────────────────
    # PHASE D : Trailing SL Dow pivots (cancel-replace DTC)
    # ────────────────────────────────────────────────────────────────────

    def _update_trail_if_needed(self, sym: str, last_bar: Any) -> None:
        """Update trailing SL si state machine Dow pivots propose un nouveau SL.

        Appele depuis poll_cycle quand position active.

        Logique :
          1. engine.update_trailing(state, bar) -> Optional[new_sl]
          2. Check is_timeout via ts_event_ns
          3. Si new_sl ET diff > 1 tick : _modify_sl_via_dtc_bn_v4
          4. Si timeout : _force_close_market_bn_v4 (Phase E skeleton ci-dessous)
        """
        engine = self._engine_by_sym[sym]
        trail = self._trail_state[sym]
        pos = self._position[sym]
        if trail is None or pos is None:
            return

        # 1. Update state machine Dow pivots
        try:
            new_sl = engine.update_trailing(trail, last_bar)
        except ValueError as e:
            # OHLC NaN fail-loud → emit + skip cycle (recovery probable bar suivante)
            _emit("BN_V4_FEATURE_DEGRADED",
                  sym=sym, feature="OHLC", bars_nan=1)
            return

        tick = TICK_BY_SYMBOL.get(sym, 0.25)

        # 2. Check timeout 90 bars via ts_event_ns (P1.1 fix)
        current_ts_ns = int(last_bar.get("ts_event_ns", 0) or 0)
        if engine.is_timeout(trail, current_ts_ns):
            self._force_close_market_bn_v4(sym, pos, reason="timeout_90_bars")
            return

        # 3. Si nouveau SL propose ET diff > 1 tick : cancel-replace DTC
        if new_sl is None:
            return
        diff_ticks = abs(new_sl - pos["sl_current"]) / tick
        if diff_ticks < 1.0:
            return    # mouvement < 1 tick, pas la peine de re-placer

        # En dry_run : log only
        if self.dry_run or self.dtc is None:
            old_sl = pos["sl_current"]
            with self._pos_lock:
                pos["sl_current"] = new_sl
            _emit("BN_V4_TRAIL_SL_UPDATED",
                  sym=sym, direction=pos["direction"],
                  old_sl=round(old_sl, 4), new_sl=round(new_sl, 4),
                  n_pivots=trail.n_pivots_confirmed)
            self._logger_by_sym[sym].log_trail_update(
                pos["signal_id"], current_ts_ns,
                old_sl, new_sl, trail.n_pivots_confirmed,
            )
            return

        # Live : cancel-replace DTC
        self._modify_sl_via_dtc_bn_v4(sym, pos, new_sl, trail.n_pivots_confirmed,
                                         current_ts_ns)

    def _modify_sl_via_dtc_bn_v4(self, sym: str, pos: dict, new_sl_price: float,
                                    n_pivots: int, current_ts_ns: int) -> bool:
        """Cancel old SL + send new SL STOP.

        Pattern Bot 3 _bot3_modify_sl_via_dtc (paper_v2.py:1826) :
          1. ABORT si DTC down
          2. Cancel old SL avec require_sid=True (refuse si SID manque)
          3. Cleanup _oco_pairs bidirectionnel (tp <-> old_sl)
          4. Wait 0.3s propagation cancel
          5. Verify position broker qty != 0 (anti trade inverse race)
          6. Generate new_sl_cid + pre-register TradeAccount (H6) + OCO (anti-orphan)
          7. Send Type 208 OrderType=STOP avec StopPrice + TradeAccount Sim2 explicit
          8. Update pos + _bn_v4_cid_index sous lock
          9. Emit BN_V4_TRAIL_SL_CANCEL_REPLACE

        Returns:
            True si modify reussi, False sinon (caller log warning, retry au cycle suivant).
        """
        if self.dtc is None or not self.dtc.connected:
            _emit("BN_V4_LOOP_ERROR", sym=sym,
                  err="modify_sl_dtc_down_or_disconnected")
            return False

        old_sl_cid = pos.get("sl_cid")
        tp_cid = pos.get("tp_cid")
        if not old_sl_cid:
            _emit("BN_V4_ORPHAN_DETECTED",
                  sym=sym, order_cid="None",
                  order_type="sl_cid_missing_from_pos")
            return False

        # STEP A : Cancel old SL (require_sid=True = anti silent fail)
        try:
            cancel_ok = self.dtc.cancel_order(
                old_sl_cid,
                trade_account=self.trade_account,
                require_sid=True,
            )
        except Exception as e:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"modify_sl_cancel_exception: {type(e).__name__}: {str(e)[:200]}")
            return False
        if not cancel_ok:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"modify_sl_cancel_failed_cid={old_sl_cid[:20]}")
            return False

        # STEP B : Cleanup OCO mapping bidirectionnel (fix #3 code-reviewer 11/05)
        try:
            self.dtc._oco_pairs.pop(old_sl_cid, None)
            if tp_cid:
                self.dtc._oco_pairs.pop(tp_cid, None)
        except (AttributeError, KeyError):
            pass

        # STEP C : Wait 0.3s propagation cancel + SID resolution
        import time as _time
        _time.sleep(0.3)

        # STEP D : Verify position broker qty != 0 (anti trade inverse race)
        # Pendant les 0.3s, market peut traverser old SL -> SC fill -> position close
        # Si on send new STOP sans verify, on cree TRADE INVERSE (catastrophique).
        contract = SYMBOL_TO_CONTRACT.get(sym, f"{sym}M26-CME")
        try:
            qty = self.dtc.request_position_blocking(
                contract, trade_account=self.trade_account, timeout=2.0
            )
        except Exception as e:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"modify_sl_pos_verify_exception: {type(e).__name__}: {str(e)[:200]}")
            return False
        if qty is None:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym, err="modify_sl_pos_verify_timeout")
            return False
        if qty == 0:
            # Position close pendant wait -> on annule modify, on signale
            _emit("BN_V4_ORPHAN_DETECTED",
                  sym=sym, order_cid=old_sl_cid[:20],
                  order_type="pos_closed_during_modify_sl_anti_inverse")
            with self._pos_lock:
                pos["sl_cid"] = None    # signaler que SL n'existe plus
            return False

        # STEP E : Generate new_sl_cid + pre-register TA + OCO
        import uuid as _uuid
        new_sl_cid = f"BN_V4_SL_{sym[:2]}_{_uuid.uuid4().hex[:8]}"
        self.dtc._order_trade_accounts[new_sl_cid] = self.trade_account
        if tp_cid:
            self.dtc.register_oco_pair(tp_cid, new_sl_cid)

        # STEP F : Send new STOP order (Type 208 + OrderType=STOP)
        try:
            from dtc_connector import STOP as DTC_STOP, DTC_MARKET_ORDER
        except ImportError:
            from BOT.dtc_connector import STOP as DTC_STOP, DTC_MARKET_ORDER

        new_sl_side_int = DTC_SELL if pos["direction"] == "long" else DTC_BUY
        quantity = int(pos.get("qty", 1))

        try:
            # 10/06/2026 REVERT FIX C4 (cf BOT_CHANGELOG entry 2026-06-10) :
            # Spec officielle DTC : Price1 = stop trigger STOP (3).
            # Pattern V1 valide Nov 2024 - belt-and-suspenders.
            self.dtc._send({
                "Type": DTC_MARKET_ORDER,
                "Symbol": contract,
                "ClientOrderID": new_sl_cid,
                "OrderType": DTC_STOP,
                "BuySell": new_sl_side_int,
                "Quantity": quantity,
                "Price1": float(new_sl_price),       # SPEC : trigger price STOP
                "Price2": 0.0,                        # Default explicite (non STOP_LIMIT)
                "StopPrice": float(new_sl_price),    # Defensif compat
                "TimeInForce": 0,
                "TradeAccount": self.trade_account,
                "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2,
            })
            # 01/06 LOG TRACEABILITY patch SL STOP no Price1
            _emit("SL_STOP_PATCHED_V1",
                  kind="sl_bn_v4_modify",
                  sl_cid=new_sl_cid,
                  sl_price=float(new_sl_price),
                  trade_account=self.trade_account)
        except Exception as e:
            # Cleanup bidirectionnel pour eviter orphan mapping
            self.dtc._order_trade_accounts.pop(new_sl_cid, None)
            self.dtc._oco_pairs.pop(new_sl_cid, None)
            if tp_cid:
                self.dtc._oco_pairs.pop(tp_cid, None)
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"modify_sl_send_exception: {type(e).__name__}: {str(e)[:200]}")
            return False

        # STEP G : Update pos + cid_index sous lock (anti race avec _handle_dtc_fill)
        old_sl = pos["sl_current"]
        with self._pos_lock:
            self._bn_v4_cid_index.pop(old_sl_cid, None)
            self._bn_v4_cid_index[new_sl_cid] = {
                "sym": sym, "kind": "sl", "signal_id": pos["signal_id"],
            }
            pos["sl_cid"] = new_sl_cid
            pos["sl_current"] = new_sl_price

        # STEP H : Emit logs
        _emit("BN_V4_TRAIL_SL_UPDATED",
              sym=sym, direction=pos["direction"],
              old_sl=round(old_sl, 4),
              new_sl=round(new_sl_price, 4),
              n_pivots=n_pivots)
        _emit("BN_V4_TRAIL_SL_CANCEL_REPLACE",
              sym=sym,
              old_sl_cid=old_sl_cid[:20],
              new_sl_cid=new_sl_cid[:20],
              new_sl_price=round(new_sl_price, 4))

        # STEP I : Logger JSONL dedie
        self._logger_by_sym[sym].log_trail_update(
            pos["signal_id"], current_ts_ns,
            old_sl, new_sl_price, n_pivots,
        )

        return True

    def _force_close_market_bn_v4(self, sym: str, pos: dict, reason: str) -> bool:
        """PHASE F : sequence anti-orphelin V2 (cf .claude/rules/orphan-prevention.md).

        Pattern Bot 3 `_bot3_force_close_market` (paper_v2.py:1701) etendu avec
        etape 9 VERIFY POST-CLEANUP (defense ultime J+1 audit).

        Sequence 9 etapes (Sim2 - PAS Type 210 car compte potentiellement partage) :
          1. Cancel TP via dtc.cancel_order(tp_cid, trade_account=Sim2)
          2. Cancel SL idem
          3. Wait 1s propagation cancels
          4. R1 verify position broker via request_position_blocking
          5. Si qty != 0 : MARKET CLOSE Type 208 OpenCloseTrade=2 + register cid
          6. Wait 2s pour fill MARKET CLOSE
          6.5. CANCEL-ALL-WORKING : query Type 300 OPEN_ORDERS + cancel survivants
          7. Type 209 SUBMIT_FLATTEN (ClientOrderID OBLIGATOIRE - rejet silent sinon)
          8. [SKIP Type 210 pour Sim2 partage]
          9. VERIFY POST-CLEANUP : wait 2s + re-query Type 300, emit ORPHAN_DETECTED si > 0

        Returns:
            True si flatten propre (qty=0 verifie ou Type 209 envoye), False si DTC down.
        """
        if self.dry_run or self.dtc is None:
            # Dry run : log close + cleanup state in-memory
            current_ts_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
            ts_open_ns = pos.get("ts_open_ns", 0)
            duration_bars = max(1, int((current_ts_ns - ts_open_ns) / 60_000_000_000)) if ts_open_ns else 0
            _emit("BN_V4_TRADE_CLOSE_TIMEOUT",
                  sym=sym, direction=pos["direction"],
                  exit_price=pos["entry_price"],    # placeholder dry_run
                  pnl_R=0.0)
            self._logger_by_sym[sym].log_trade_close(
                pos["signal_id"], current_ts_ns,
                pos["entry_price"], f"timeout_dry_run_{reason}",
                pnl_R=0.0, pnl_usd=0.0, duration_bars=duration_bars,
            )
            with self._pos_lock:
                for c in (pos.get("parent_cid"), pos.get("tp_cid"), pos.get("sl_cid")):
                    if c:
                        self._bn_v4_cid_index.pop(c, None)
                self._position[sym] = None
                self._trail_state[sym] = None
                self._current_signal_id[sym] = None
            return True

        # LIVE : sequence anti-orphelin V2 complete (9 etapes)
        if not self.dtc.connected:
            _emit("BN_V4_DTC_DOWN",
                  sym=sym, action="skip_cycle_until_reconnect")
            return False

        contract = SYMBOL_TO_CONTRACT.get(sym, f"{sym}M26-CME")
        tp_cid = pos.get("tp_cid")
        sl_cid = pos.get("sl_cid")

        # ETAPE 1 : Cancel TP (skip si None = recovery boot ou deja close)
        if tp_cid:
            try:
                self.dtc.cancel_order(tp_cid, trade_account=self.trade_account)
            except Exception as e:
                _emit("BN_V4_LOOP_ERROR",
                      sym=sym, err=f"force_close_cancel_tp_exc: {type(e).__name__}")

        # ETAPE 2 : Cancel SL
        if sl_cid:
            try:
                self.dtc.cancel_order(sl_cid, trade_account=self.trade_account)
            except Exception as e:
                _emit("BN_V4_LOOP_ERROR",
                      sym=sym, err=f"force_close_cancel_sl_exc: {type(e).__name__}")

        # ETAPE 3 : Wait 1s propagation cancels
        import time as _time
        _time.sleep(1.0)

        # ETAPE 4 : R1 Verify position broker (anti race condition)
        try:
            qty = self.dtc.request_position_blocking(
                contract, trade_account=self.trade_account, timeout=2.0,
            )
        except Exception as e:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"force_close_pos_query_exc: {type(e).__name__}: {str(e)[:200]}")
            qty = None

        flush_no_pos = False
        if qty is None:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym, err="force_close_pos_verify_timeout")
            qty = 0    # proceed with Type 209 anyway
            flush_no_pos = True

        # ETAPE 5 : MARKET CLOSE si qty != 0
        if qty != 0:
            n_to_close = abs(qty)
            side_close = DTC_SELL if qty > 0 else DTC_BUY
            import uuid as _uuid
            close_cid = f"BN_V4_CLOSE_{sym[:2]}_{_uuid.uuid4().hex[:8]}"
            self.dtc._order_trade_accounts[close_cid] = self.trade_account
            # Register pour routage fill via _handle_dtc_fill_bn_v4
            with self._pos_lock:
                self._bn_v4_cid_index[close_cid] = {
                    "sym": sym, "kind": "sl",    # treat as SL fill (close)
                    "signal_id": pos.get("signal_id"),
                }
            try:
                self.dtc._send({
                    "Type": 208, "Symbol": contract,
                    "ClientOrderID": close_cid, "OrderType": 1,    # MARKET
                    "BuySell": side_close, "Quantity": n_to_close,
                    "TradeAccount": self.trade_account, "IsAutomatedOrder": 1,
                    "OpenCloseTrade": 2, "TimeInForce": 0,
                })
                _emit("BN_V4_TRADE_CLOSE_MANUAL",
                      sym=sym, direction=pos["direction"],
                      exit_price=0.0,    # rempli au fill via _handle_dtc_fill_bn_v4
                      pnl_R=0.0,
                      reason=f"force_close_{reason}")
            except Exception as e:
                _emit("BN_V4_LOOP_ERROR",
                      sym=sym,
                      err=f"force_close_send_market_exc: {type(e).__name__}: {str(e)[:200]}")
                with self._pos_lock:
                    self._bn_v4_cid_index.pop(close_cid, None)
                # On continue quand meme avec Type 209

        # ETAPE 6 : Wait 2s pour fill MARKET CLOSE
        _time.sleep(2.0)

        # ETAPE 6.5 : CANCEL-ALL-WORKING (query OPEN_ORDERS + cancel survivants)
        # Pattern P0.3 anti-orphelin V2 (06/05) : Type 209 NE CANCEL PAS les Working
        # orders sans position attachee. Donc explicit cancel via Type 300 query.
        try:
            working_orders = self._query_open_orders_by_symbol(contract)
            for working_cid, working_sid in working_orders:
                try:
                    self.dtc.cancel_order(
                        working_cid, trade_account=self.trade_account,
                    )
                except Exception as e:
                    _emit("BN_V4_LOOP_ERROR",
                          sym=sym,
                          err=f"cancel_working_orphan_exc: {type(e).__name__}")
        except Exception as e:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"query_open_orders_exc: {type(e).__name__}: {str(e)[:200]}")

        # ETAPE 7 : Type 209 SUBMIT_FLATTEN (ClientOrderID OBLIGATOIRE)
        flush_cid = f"BN_V4_FLUSH_{sym[:2]}_{int(_time.time()) % 100000}"
        try:
            self.dtc._send({
                "Type": 209, "ClientOrderID": flush_cid,
                "Symbol": contract, "TradeAccount": self.trade_account,
                "Exchange": "CME", "IsAutomatedOrder": 1,
            })
        except Exception as e:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"flush_209_exc: {type(e).__name__}: {str(e)[:200]}")

        # ETAPE 8 : SKIP Type 210 (Sim2 partage potentiellement avec autres bots)

        # ETAPE 9 : VERIFY POST-CLEANUP (wait 2s + re-query, emit ORPHAN si > 0)
        _time.sleep(2.0)
        try:
            survivors = self._query_open_orders_by_symbol(contract)
            if survivors:
                for surv_cid, surv_sid in survivors:
                    _emit("BN_V4_ORPHAN_DETECTED",
                          sym=sym,
                          order_cid=surv_cid[:30],
                          order_type=f"working_post_cleanup_{reason}")
                    # Re-cancel chaque survivant
                    try:
                        self.dtc.cancel_order(
                            surv_cid, trade_account=self.trade_account,
                        )
                    except Exception:
                        pass
        except Exception as e:
            _emit("BN_V4_LOOP_ERROR",
                  sym=sym,
                  err=f"verify_post_cleanup_exc: {type(e).__name__}")

        # Cleanup state interne (le fill ORDER_UPDATE de close_cid via
        # _handle_dtc_fill_bn_v4 finira le cleanup officiel + pnl calc)
        # Ici on ne touche pas le state pour eviter race condition.
        return True

    def _query_open_orders_by_symbol(self, contract: str) -> list:
        """Query DTC Type 300 OPEN_ORDERS + filter par symbol.

        Returns:
            list of (client_order_id, server_order_id) tuples pour les
            Working orders matchant contract.

        Best-effort : si DTC API differente que Bot 3 connector, retourne [].
        """
        try:
            # Bot 3 utilise query_open_orders_blocking ; on essaye plusieurs
            # signatures pour robustesse cross-version dtc_connector.
            if hasattr(self.dtc, "query_open_orders_blocking"):
                orders = self.dtc.query_open_orders_blocking(
                    trade_account=self.trade_account, timeout=2.0,
                ) or []
                return [
                    (o.get("ClientOrderID", ""), o.get("ServerOrderID", ""))
                    for o in orders
                    if o.get("Symbol", "") == contract
                    and o.get("OrderStatus") in (2, 4)    # Open/Working
                ]
        except Exception:
            pass
        return []

    # ────────────────────────────────────────────────────────────────────
    # PHASE E : Risk gates + kill switch + heartbeat (Jackson "TOUT TRAKER")
    # ────────────────────────────────────────────────────────────────────

    def _check_risk_gates_for_trade(self, sym: str, setup: dict) -> bool:
        """Verifie risk gates AVANT autorisation TRADE.

        Returns True si trade autorise, False sinon. Emit BN_V4_SKIP_*
        approprie sur chaque rejet (TOUT trackable J+1 via grep).

        Gates :
          1. Kill switch global active -> SKIP + emit BN_V4_SKIP_KILL_SWITCH
          2. Cooldown 3 SL consec actif -> SKIP + emit BN_V4_SKIP_COOLDOWN
          3. PnL session < MAX_DD_USD -> activate kill switch + emit RISK_MAX_DD_HIT
        """
        direction = setup.get("direction", "?")

        # Gate 1 : kill switch global
        if self._kill_switch_active:
            _emit("BN_V4_SKIP_KILL_SWITCH",
                  sym=sym, direction=direction,
                  reason=self._kill_switch_reason or "manual_or_max_dd")
            return False

        # Gate 2 : cooldown 3 SL consec actif
        cooldown_until = self._cooldown_until.get(sym)
        if cooldown_until is not None:
            now = datetime.now(timezone.utc)
            if now < cooldown_until:
                remaining_min = (cooldown_until - now).total_seconds() / 60
                _emit("BN_V4_SKIP_COOLDOWN",
                      sym=sym, direction=direction,
                      remaining_min=round(remaining_min, 1))
                return False
            else:
                # Cooldown expire : reset + emit
                self._cooldown_until[sym] = None
                self._n_sl_consec[sym] = 0    # reset compteur a expiry
                _emit("BN_V4_RISK_COOLDOWN_EXPIRED", sym=sym)

        # Gate 3 : PnL session < MAX_DD_USD -> activate kill switch
        if self._pnl_session_usd <= self.RISK_MAX_DD_USD:
            _emit("BN_V4_RISK_MAX_DD_HIT",
                  pnl_session=round(self._pnl_session_usd, 2),
                  threshold=self.RISK_MAX_DD_USD,
                  kill_switch="ON")
            self.activate_kill_switch(reason="max_dd_session_exceeded")
            return False

        return True

    def _check_post_close_risk(self, sym: str, cause: str) -> None:
        """Check risk gates POST trade close. Active cooldown si 3 SL consec.

        Appele depuis _handle_dtc_fill_bn_v4 apres mise a jour _n_sl_consec.

        Si _n_sl_consec[sym] >= RISK_MAX_SL_CONSEC : active cooldown +
        emit BN_V4_RISK_3_SL_CONSEC + BN_V4_RISK_COOLDOWN_ACTIVATED.
        """
        if not cause.startswith("sl"):
            return
        if self._n_sl_consec.get(sym, 0) < self.RISK_MAX_SL_CONSEC:
            return
        # 3 SL consec hit : activate cooldown
        from datetime import timedelta
        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.RISK_COOLDOWN_MIN)
        self._cooldown_until[sym] = cooldown_until
        _emit("BN_V4_RISK_3_SL_CONSEC",
              sym=sym, direction="any",
              cooldown_min=self.RISK_COOLDOWN_MIN)
        _emit("BN_V4_RISK_COOLDOWN_ACTIVATED",
              sym=sym,
              consec_sl=self._n_sl_consec[sym],
              cooldown_min=self.RISK_COOLDOWN_MIN,
              expires_iso=cooldown_until.isoformat())

    def activate_kill_switch(self, reason: str) -> None:
        """Active kill switch global : skip toutes les nouvelles actions DTC.

        Force close positions actives (Phase F sequence anti-orphelin complete).
        Pour Phase E : marque kill_switch + emit, force_close skeleton.
        """
        if self._kill_switch_active:
            return    # idempotent
        self._kill_switch_active = True
        self._kill_switch_reason = reason

        positions_open = sum(
            1 for sym in self.symbols if self._position.get(sym) is not None
        )
        orders_canceled = 0

        # Pour chaque position active : force close (Phase F sera complet)
        for sym in self.symbols:
            pos = self._position.get(sym)
            if pos is not None:
                # Phase E : utilise _force_close_market_bn_v4 (skeleton Phase D)
                self._force_close_market_bn_v4(sym, pos, reason=f"kill_switch_{reason}")
                orders_canceled += 1

        _emit("BN_V4_KILL_SWITCH_ACTIVATED",
              reason=reason,
              positions_flat=positions_open,
              orders_canceled=orders_canceled)

        # Logger JSONL dedie (separe du log_catalog)
        for sym in self.symbols:
            self._logger_by_sym[sym].log_kill_switch(
                reason=reason,
                positions_flat=positions_open,
                orders_canceled=orders_canceled,
            )

    def heartbeat_check(self) -> None:
        """Emit heartbeat periodic (toutes HEARTBEAT_INTERVAL_MIN minutes).

        A appeler depuis poll_cycle. Stats globales pour monitoring J+1.
        """
        now = datetime.now(timezone.utc)
        if self._last_heartbeat_ts is not None:
            elapsed_min = (now - self._last_heartbeat_ts).total_seconds() / 60
            if elapsed_min < self.HEARTBEAT_INTERVAL_MIN:
                return
        self._last_heartbeat_ts = now
        uptime_min = (now - self._boot_ts).total_seconds() / 60
        for sym in self.symbols:
            _emit("BN_V4_HEARTBEAT",
                  sym=sym,
                  uptime_min=round(uptime_min, 1),
                  n_bars=self._n_bars_processed,
                  n_setups=self._n_setups_detected,
                  n_trades=self._n_trades_executed,
                  pnl_usd=round(self._pnl_session_usd, 2))

            # Fix P0#2 reviewer iter3 23/05 : wire BN_V4_DATA_STATS (orphelin
            # avant fix). Emis 1x/heartbeat avec stats reader (bars buffer size,
            # last close, last bar age). Permet audit pipeline data J+1.
            try:
                reader = self._reader_by_sym.get(sym)
                if reader is not None:
                    df = reader.load_rolling_window()
                    n_bars_buf = len(df) if df is not None else 0
                    last_close = float(df.iloc[-1]["close"]) if (df is not None and n_bars_buf > 0) else None
                    age_sec = reader.get_last_bar_age_seconds()
                    _emit("BN_V4_DATA_STATS",
                          sym=sym,
                          bars_buffer=n_bars_buf,
                          last_close=last_close,
                          age_sec=round(age_sec, 1) if age_sec < 999999 else None)
            except Exception as e:
                # Fail-soft : data_stats est informatif, pas critique
                pass

    def register_dtc_callback(self) -> None:
        """Register _handle_dtc_fill_bn_v4 sur dtc connector pour intercepter
        Type 301 ORDER_UPDATE status=7 (Filled).

        A appeler depuis paper_v2 apres init DTC.

        Pattern Bot 3 (paper_v2.py:556) : le DTC connector appelle ce callback
        sur chaque ORDER_UPDATE status=7. Si cid match notre index, traite ;
        sinon retourne False et laisse Bot 3 ou autre traiter.
        """
        if self.dtc is None or self.dry_run:
            return
        # Pattern : self.dtc.add_fill_handler(self._handle_dtc_fill_bn_v4)
        # Implementation depend de l'API du dtc_connector existant. A wirer
        # phase G integration paper_v2 (besoin verif API).

    # ────────────────────────────────────────────────────────────────────
    # Getters / introspection (utile pour dashboard + tests)
    # ────────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Stats lifecycle pour dashboard / monitoring."""
        return {
            "version": __version__,
            "boot_ts": self._boot_ts.isoformat(),
            "uptime_sec": (datetime.now(timezone.utc) - self._boot_ts).total_seconds(),
            "symbols": self.symbols,
            "dry_run": self.dry_run,
            "trade_account": self.trade_account,
            "n_bars_processed": self._n_bars_processed,
            "n_setups_detected": self._n_setups_detected,
            "n_trades_executed": self._n_trades_executed,
            "n_positions_active": sum(
                1 for sym in self.symbols if self._position.get(sym) is not None
            ),
            "pnl_session_usd": self._pnl_session_usd,
            "kill_switch_active": self._kill_switch_active,
        }

    def is_position_active(self, symbol: str) -> bool:
        """True si position active sur ce symbol."""
        return self._position.get(symbol) is not None


# ────────────────────────────────────────────────────────────────────────
# Standalone main pour test direct (sans paper_v2 wrapper)
# ────────────────────────────────────────────────────────────────────────

def _read_env_kill_switches() -> dict:
    """Lit les ENV vars MIA_BN_V4_*. Retourne dict config."""
    return {
        "enabled": os.environ.get("MIA_BN_V4_ENABLED", "0") == "1",
        "dry_run": os.environ.get("MIA_BN_V4_DRY_RUN", "1") == "1",
        "trade_account": os.environ.get("MIA_BN_V4_TRADE_ACCOUNT", "Sim2"),
        "symbols": os.environ.get("MIA_BN_V4_SYMBOLS", "NQ").split(","),
    }


if __name__ == "__main__":
    # Standalone test mode : verifie boot + shutdown sans poll_cycle
    cfg = _read_env_kill_switches()
    if not cfg["enabled"]:
        print("[BN_V4_PAPER] MIA_BN_V4_ENABLED != 1 -> exit (kill switch)")
        sys.exit(0)

    print(f"[BN_V4_PAPER] Boot standalone test mode")
    print(f"  symbols      : {cfg['symbols']}")
    print(f"  dry_run      : {cfg['dry_run']}")
    print(f"  trade_account: {cfg['trade_account']}")

    trader = BNV4PaperTrader(
        dtc=None,    # standalone test = dry_run force
        symbols=cfg["symbols"],
        dry_run=True,
        trade_account=cfg["trade_account"],
    )
    trader.boot_ready()
    print("  boot OK + emits BN_V4_BOOT_START / CONFIG_LOADED / BOOT_READY")
    print()
    print("  Stats :")
    for k, v in trader.get_stats().items():
        print(f"    {k:25s} : {v}")
    trader.shutdown(reason="standalone_test_complete")
    print("  shutdown OK + emit BN_V4_SHUTDOWN")
    print()
    print("[BN_V4_PAPER] Standalone test PHASE A complete.")
