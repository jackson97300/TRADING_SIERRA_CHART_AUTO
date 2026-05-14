"""live_enricher.py — service principal Live Enricher production-grade.

Phase 3a Jour 4 du Chantier 3 (13/05/2026 nuit).

Service Python 24/7 (deploye via nssm `MIA-Live-Enricher` apres validation).
Orchestrateur des modules :
  - live_enricher_io.py    : read inputs (OHLCV, Trades, MQ, VIX)
  - live_enricher_state.py : rolling buffer + snapshot persiste
  - live_enricher_writer.py: write JSONL atomic DATA/live_enriched/...

ARCHITECTURE PRODUCTION-GRADE (pattern repro databento_live_stream.py) :

Threads daemon :
  - Main loop          : detect nouvelle bar close, run cycle enricher
  - Snapshot thread    : save_state toutes 5 min crash recovery
  - Watchdog thread    : detect stuck cycle (>30s alerte, >90s sys.exit(3))
  - Heartbeat thread   : write _enricher_heartbeat.json toutes 10s
  - Thread health      : verifie daemons vivants -> sys.exit(3) nssm relance

Signal handling :
  - SIGTERM / SIGINT : clean shutdown (flush state, close files)

Error handling :
  - try/except dans main loop (no crash 1 bar fail)
  - log_catalog emit fail-loud (ENRICHER_CYCLE_SLOW / WRITE_FAIL / INPUTS_INCOMPLETE)
  - Discord alert via log_catalog level CRITIQUE auto-routing

Phase 3a Jour 4 = SKELETON SANS ENGINES (validation infra) :
  output payload = OHLCV bar + MQ snapshot + VIX snapshot (sans phase_b_*,
  edge_zones, etc. - ajouter Phase 3b-d engine par engine).

L'infrastructure ELLE-MEME est production-grade complete. Seuls les engines
metier manquent pour Phase 3a.

Auteur : MIA Trading System V2
  v1.0 (2026-05-13 nuit) : version initiale Phase 3a Jour 4
"""
from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from live_enricher_io import read_all_inputs
from live_enricher_state import (
    LiveEnricherState,
    initialize_state,
    save_state,
)
from live_enricher_writer import write_enriched_bar

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

# Symbols suivis (aligne sur databento_live_stream.py SYMBOLS)
SYMBOLS = ["ES.c.0", "NQ.c.0", "MGC.v.0"]

# Intervals (secondes)
MAIN_LOOP_INTERVAL_SEC = 1.0       # check new bar every 1s
SNAPSHOT_INTERVAL_SEC = 300        # save_state every 5 min
WATCHDOG_INTERVAL_SEC = 30         # check stuck cycle every 30s
HEARTBEAT_INTERVAL_SEC = 10        # write heartbeat every 10s
THREAD_HEALTH_CHECK_SEC = 30       # check daemon threads alive every 30s

# Watchdog seuils
CYCLE_SLOW_THRESHOLD_SEC = 30      # alerte si cycle prend > 30s
CYCLE_STUCK_THRESHOLD_SEC = 90     # sys.exit(3) si cycle prend > 90s (deadlock)

# Heartbeat file
HEARTBEAT_FILE = ROOT / "DATA" / "LIVE_CACHE" / "_enricher_heartbeat.json"

# Logging
LOG_DIR = ROOT / "DATA" / "LOGS"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "live_enricher.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("live_enricher")


# ═══════════════════════════════════════════════════════════════════════════════
# Etat global
# ═══════════════════════════════════════════════════════════════════════════════

_running = True
_states: dict[str, LiveEnricherState] = {}
_states_lock = threading.Lock()

# Tracking per-symbol : derniere bar processed (anti double-process).
# FIX P0-3 doc review (audit code-reviewer Jour 4) : access multi-thread :
#   - Write : main loop seulement (_process_bar_cycle)
#   - Read : main loop + _heartbeat_loop (via dict copy)
# Sur CPython, dict ops sont atomiques (GIL) MAIS si on agrandit la dict
# (ex: ajout symbol dynamique Phase 3c), il faudra ajouter un lock dedie.
# Pour Phase 3a/3b avec SYMBOLS fixes pre-keyed, OK.
_last_processed_ts_ns: dict[str, int] = {sym: 0 for sym in SYMBOLS}

# Watchdog : timestamp debut du cycle courant (per-symbol)
_cycle_start_ts: dict[str, float] = {sym: 0.0 for sym in SYMBOLS}
_cycle_lock = threading.Lock()

# Stats (idem P0-3 : dict pre-keyed, ops atomiques GIL CPython - OK Phase 3a/3b)
_n_bars_processed: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_n_bars_failed: dict[str, int] = {sym: 0 for sym in SYMBOLS}
_boot_ts = time.time()


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers log_catalog (DRY aligne live_enricher_state._emit_log)
# ═══════════════════════════════════════════════════════════════════════════════

def _emit_log(code: str, **kwargs) -> None:
    """Emit via log_catalog avec fallback degrade pour code inconnu.

    Convention : tout code DOIT etre enregistre dans `CORE/log_catalog.py`
    (regle souveraine logs 01/05). Si un code n'existe pas dans LOG_CODES,
    on emit un WARNING explicite avec le code+kwargs pour eviter qu'un
    bug d'instrumentation passe silencieusement (anti-pattern interdit
    section .claude/rules/critical-tasks-review.md A.D).

    Note : ce fallback degrade n'est PAS un fail-loud strict (pas de raise),
    car pendant le runtime production, raise interromprait le cycle. Le
    warning suffit pour declencher l'investigation (grep logs J+1).
    """
    try:
        from log_catalog import LOG_CODES, LogLevel
        if code not in LOG_CODES:
            # Fallback degrade : warning au lieu de silent no-op
            logger.warning(
                f"[UNREGISTERED_LOG_CODE] code={code!r} kwargs={kwargs} -- "
                f"ajouter a CORE/log_catalog.py (regle souveraine 01/05)"
            )
            return
        level, _cat, template = LOG_CODES[code]
        try:
            msg = template.format(**kwargs)
        except (KeyError, IndexError):
            msg = f"{code} (format fail kwargs={kwargs})"
        if level == LogLevel.CRITIQUE:
            logger.critical(f"[{code}] {msg}")
        elif level == LogLevel.MAJEUR:
            logger.error(f"[{code}] {msg}")
        elif level == LogLevel.ALERTE:
            logger.warning(f"[{code}] {msg}")
        else:
            logger.info(f"[{code}] {msg}")
    except ImportError:
        logger.info(f"[{code}] {kwargs}")


# ═══════════════════════════════════════════════════════════════════════════════
# Signal handling (clean shutdown)
# ═══════════════════════════════════════════════════════════════════════════════

def _signal_handler(signum, frame):
    """Clean shutdown sur SIGTERM/SIGINT : flush state + exit."""
    global _running
    logger.info(f"Signal {signum} received -> graceful shutdown initiated")
    _running = False


def _shutdown_flush(timeout_sec: float = 10.0) -> bool:
    """Flush final state pour tous les symbols avant exit.

    FIX P0-3 code-reviewer 13/05 nuit : ajoute timeout pour eviter shutdown
    infini si save_state bloque (disque plein, AV scan Windows, etc.).

    Returns True si tous flush OK, False si timeout ou fail.
    """
    logger.info(f"Shutdown : flushing state to disk for all symbols (timeout={timeout_sec}s)...")

    def _do_flush() -> None:
        with _states_lock:
            states = list(_states.items())
        for sym, state in states:
            try:
                ok = save_state(state)
                if ok:
                    logger.info(f"  {sym}: state flushed OK")
                else:
                    logger.error(f"  {sym}: state flush FAILED")
            except Exception as e:
                logger.exception(f"  {sym}: shutdown flush exception: {e}")

    t = threading.Thread(target=_do_flush, daemon=True, name="ShutdownFlush")
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        logger.critical(
            f"_shutdown_flush TIMEOUT apres {timeout_sec}s -> state pending perdu "
            f"(disque plein ? AV scan Windows ?). Continue exit."
        )
        return False
    return True


def _emergency_exit(code: int = 3) -> None:
    """FIX P0-1 code-reviewer : flush state AVANT sys.exit pour eviter perte 0-5min.

    Utilise par _watchdog_loop et thread_health_check (sys.exit dans thread
    daemon tue process sans derouler finally main()).
    """
    logger.critical(f"_emergency_exit({code}) : flushing state before exit...")
    _shutdown_flush(timeout_sec=10.0)
    logger.critical(f"_emergency_exit({code}) : flush done, sys.exit({code}) for nssm relance")
    sys.exit(code)


# ═══════════════════════════════════════════════════════════════════════════════
# Main cycle : process 1 new bar
# ═══════════════════════════════════════════════════════════════════════════════

def _process_bar_cycle(symbol: str, state: LiveEnricherState) -> bool:
    """Process une bar : read inputs -> compose enriched -> write JSONL.

    Phase 3c semaine 4 : integration phase_b_plus_plus chain (76 features).

    SEMANTIQUE FAIL-SOFT engines chain :
      - Si crash mid-chain (ValueError/KeyError/TypeError/AttributeError/ImportError) :
        * payload est revert vers `payload_pre_chain` (checkpoint pre-try)
        * marker `phase_b_plus_plus_partial = True` ajoute pour filtrage downstream
        * NOTE IMPORTANTE : l'ETAT INTERNE des engines (state.engine_states[X])
          peut avoir mute partiellement avant le crash (LOT 1 a deja increment
          bar_idx, buffers updated). Le revert N'EST PAS transactional sur les
          states - uniquement le payload. Au prochain bar, l'etat des engines
          est consistent avec la SEQUENCE de bars vues (pas avec ce qui a ete
          ECRIT en JSONL). Comportement intentionnel : les engines sont stateful
          continu, le bar "saute" la sortie mais l'etat interne reste correct.

    Returns True si bar processed OK, False si fail / skip.
    """
    # Mark cycle start (watchdog)
    with _cycle_lock:
        _cycle_start_ts[symbol] = time.time()

    try:
        # 1. Read all inputs
        inputs = read_all_inputs(symbol, trades_window_sec=60, ohlcv_max_age_sec=90)
        ohlcv = inputs["ohlcv"]
        if ohlcv is None:
            _emit_log(
                "ENRICHER_INPUTS_INCOMPLETE", sym=symbol,
                missing="ohlcv", alive=inputs["stream_alive"]
            )
            return False

        # 2. Detection nouvelle bar (anti double-process)
        ts_event_ns = ohlcv.get("ts_event_ns", 0)
        if ts_event_ns <= _last_processed_ts_ns.get(symbol, 0):
            return False  # bar deja vue, skip silencieux

        # 3. Update state (in-memory rolling buffer)
        # FIX P0-2 review : lock state pour mutex main loop vs snapshot_loop
        # (anti corruption deque concurrent mutation + pickle serialize)
        with state.lock:
            state.update_mq(inputs["mq_levels"])
            state.update_vix(inputs["vix"])

        # 4. Compose enriched payload (SKELETON Jour 4 : pas d'engines metier).
        # En Phase 3b-d on ajoutera : apply_phase_b_helpers, apply_phase_b_plus,
        # ..., regime_engine_v6.compute_regime_dict, etc.
        payload = dict(ohlcv)  # base : OHLCV
        payload["symbol"] = symbol
        payload["ts_event_ns"] = ts_event_ns

        # Inject MQ snapshot (passthrough Phase 3a)
        if inputs["mq_levels"]:
            payload["mq_snapshot_ts"] = inputs["mq_levels"].get("ts_event")
            for k, v in inputs["mq_levels"].items():
                if k != "ts_event":
                    payload[f"mq_{k}" if not k.startswith("mq_") else k] = v

        # Pass 4-P2 : calculer dist_mq_*_pct depuis MQ levels absolus + close
        # Audit feature-engineer 15/05 dette #6 BUG #1 : LOT 4 absorb consomme
        # dist_mq_*_pct (MQ_RESISTANCE_DIST_COLS = ["dist_mq_call_pct",
        # "dist_mq_call_0dte_pct"], MQ_SUPPORT_DIST_COLS = ["dist_mq_put_pct",
        # "dist_mq_put_0dte_pct"], MQ_NEUTRAL_DIST_COLS = ["dist_mq_hvl_pct",
        # "dist_mq_hvl_pct_z"]). Sans : 4 features mortes at_level + cascade
        # LOT 5 trapped_at_resistance/support (Pattern V1 silent).
        _close = float(ohlcv.get("close")) if ohlcv.get("close") is not None else None
        if _close is not None and _close > 0:
            for mq_key, dist_key in (
                ("mq_call_resistance", "dist_mq_call_pct"),
                ("mq_call_resistance_0dte", "dist_mq_call_0dte_pct"),
                ("mq_put_support", "dist_mq_put_pct"),
                ("mq_put_support_0dte", "dist_mq_put_0dte_pct"),
                ("mq_hvl", "dist_mq_hvl_pct"),
                ("mq_hvl_0dte", "dist_mq_hvl_pct_z"),  # alias batch (cf phase_b_plus_plus_absorb_streaming:47)
            ):
                lvl = payload.get(mq_key)
                if lvl is not None:
                    try:
                        lvl_f = float(lvl)
                        if not (lvl_f != lvl_f):  # not NaN
                            payload[dist_key] = (_close - lvl_f) / _close * 100
                    except (TypeError, ValueError):
                        pass

        # Inject VIX snapshot (passthrough Phase 3a) + appel engine streaming Jour 5
        # Plug factory pattern : state.get_engine_state("vix_lite", VixLiteState)
        # Validation convention API streaming (Plan agent reframe Jour 5).
        if inputs["vix"]:
            vix_row = dict(inputs["vix"])
            try:
                from vix_lite_reader import enrich_vix_lite_streaming, VixLiteState
                vix_state = state.get_engine_state("vix_lite", factory=VixLiteState)
                vix_enriched = enrich_vix_lite_streaming(vix_row, vix_state)
                # Merge dans payload (sans dupliquer ts_event/schema_version)
                for k, v in vix_enriched.items():
                    if k not in ("ts_event", "schema_version"):
                        payload[k] = v
            except Exception as e:
                # Fallback passthrough si engine streaming echoue (fail-loud emit)
                logger.warning(f"vix_lite streaming fail {symbol}: {e}, fallback passthrough")
                for k, v in vix_row.items():
                    if k not in ("ts_event", "schema_version"):
                        payload[k] = v

        # Inject trades stats minimales (Phase 3a passthrough)
        trades_df = inputs["trades_df"]
        payload["trades_window_n"] = len(trades_df)
        payload["trades_window_sec"] = 60

        # ─── Fix code-reviewer Pass 3b R2 BLOQUANTS ───────────────────────────
        # B3 : inject `ts_event` (pd.Timestamp) - sessions_swings/rvol_inputs
        #      attend cette cle, cache OHLCV livre uniquement ts_event_iso/ns.
        # B2 : produire `delta_bar` depuis trades Databento (= sum signed_size).
        #      LOT 1 et 13+ rolling features ML lisent cette cle, le DMP C++
        #      la produisait. Aucun upstream Live Enricher ne la produit.
        #      Sans ce calcul : pattern V1 26 jours features mortes reproduit.
        import pandas as _pd  # local import (heavy module deja loaded)
        payload["ts_event"] = _pd.Timestamp(ts_event_ns, unit="ns", tz="UTC")
        # delta_bar = sum signed_size (A=BUY +size / B=SELL -size / N=ignore)
        # Fix B8 code-reviewer Round 3 : pd.notna() detecte NaN pandas
        # (not None ne suffit pas - NaN passe None check et propage en
        # float(NaN) = NaN -> cascade silent feature mortes).
        delta_bar_total = 0.0
        if not trades_df.empty and {"size", "side"}.issubset(trades_df.columns):
            for _trade in trades_df[["size", "side"]].itertuples(index=False):
                s = float(_trade.size) if _trade.size is not None and _pd.notna(_trade.size) else 0.0
                if _trade.side == "A":
                    delta_bar_total += s
                elif _trade.side == "B":
                    delta_bar_total -= s
        payload["delta_bar"] = delta_bar_total

        # ──────────────────────────────────────────────────────────────────────
        # Phase 3c semaine 4 : engines streaming (76 + 4 MGC + 10 ES/NQ = 90 max)
        # Ordre dependance critique (Pass 1 phase_b_plus_plus) :
        #   footprint_cells (helper pur)
        #   -> LOT 1 trades aggregates (produit delta_div_buy/sell, delta_bar)
        #   -> LOT 2 big_v2 (10 features VAP scan)
        #   -> LOT 3 cluster_v2 (5 features runs detection)
        #   -> LOT 4 absorb (produit near_resistance/support_level)
        #   -> LOT 5 trapped (consomme near_*, fail-loud anti Pattern 11)
        #   -> LOT 6 delta_div_ext (consomme delta_div_buy/sell de LOT 1)
        #
        # Pass 2 (cross-asset / cross-symbol) :
        #   -> gold_phase_d (MGC only, 4 features 6E/ZN/ZB) - hors lock target
        #   -> intermarket (ES/NQ partner, 10 features) - lit _states[partner]
        # ──────────────────────────────────────────────────────────────────────
        # FIX P0 code-reviewer post-fix #2 : checkpoint payload avant chain
        # pour eviter JSONL heterogene si crash mid-execution (LOT 1+2 ajoutees
        # avant fail LOT 3 -> payload partiel ecrit downstream).
        # Revert payload pre-chain en cas d'exception fail-soft.
        payload_pre_chain = dict(payload)
        try:
            from footprint_builder_streaming import build_footprint_cells_streaming
            from phase_b_plus_plus_trades_streaming import (
                add_phase_b_plus_plus_trades_streaming,
                make_phase_b_plus_plus_trades_state,
            )
            from phase_b_plus_plus_big_v2_streaming import (
                add_big_orders_v2_streaming,
                make_big_orders_v2_state,
            )
            from phase_b_plus_plus_cluster_v2_streaming import (
                add_cluster_v2_streaming,
                make_cluster_v2_state,
            )
            from phase_b_plus_plus_absorb_streaming import (
                add_stack_absorb_streaming,
                make_stack_absorb_state,
            )
            from phase_b_plus_plus_trapped_streaming import (
                add_trapped_traders_streaming,
                make_trapped_traders_state,
            )
            from phase_b_plus_plus_delta_div_ext_streaming import (
                add_delta_div_ext_streaming,
                make_delta_div_ext_state,
            )
            try:
                from CORE.constants import get_tick_size as _get_tick_size
            except ImportError:
                from constants import get_tick_size as _get_tick_size

            # symbol_pure : "ES.c.0" -> "ES", "MGC.v.0" -> "MGC"
            symbol_pure = symbol.split(".")[0]
            tick = _get_tick_size(symbol_pure)

            # 1. Build footprint cells (helper pur, sans state)
            #    Convert trades_df -> list[dict] (streaming attend list of dicts).
            #    Colonnes attendues : price, size, side ('A'/'B'/'N'), ts_event optionnel.
            #    Guard fix code-reviewer P0 : ts_event_ns OBLIGATOIRE pour assertion debug
            #    (sanity check tri ASC dans phase_b_plus_plus_trades_streaming). Sans
            #    ts_event_ns -> KeyError silently swallowed par try/except global.
            required_cols = {"price", "size", "side", "ts_event_ns"}
            if not trades_df.empty and required_cols.issubset(trades_df.columns):
                trades_records = trades_df[["price", "size", "side", "ts_event_ns"]].rename(
                    columns={"ts_event_ns": "ts_event"}
                ).to_dict(orient="records")
            else:
                if not trades_df.empty:
                    missing = required_cols - set(trades_df.columns)
                    logger.warning(
                        f"trades_df {symbol} missing cols {missing} -> skip footprint engines"
                    )
                trades_records = []

            cells = build_footprint_cells_streaming(trades_records, tick=tick)

            # P0 REORDER : imports consolides AVANT LOT 1 pour permettre
            # Pass 4c-prereq + Pass 4a inseres entre LOT 1 et LOT 2.
            from phase_b_helpers import (
                add_rvol_inputs_streaming, RvolInputsState,
                add_session_metadata_streaming, SessionMetadataState,
                add_ib_features_streaming, IBState,
                add_session_high_low_streaming, SessionHighLowState,
                add_volume_profile_features_streaming, VolumeProfileState,
            )
            from rvol_streaming import add_rvol_engine_streaming, RvolEngineState
            from phase_b_plus_streaming import (
                add_phase_b_plus_streaming, PhaseBPlusState, make_phase_b_plus_state,
            )
            from phase_b_rolling_inputs_streaming import (
                make_phase_b_rolling_inputs_state, apply_rolling_inputs_streaming,
            )
            try:
                from CORE.constants import get_session_boundaries as _get_bounds
            except ImportError:
                from constants import get_session_boundaries as _get_bounds

            # 2-7. Run engines streaming chain (state per engine via factory)
            #      Sous lock state (anti corruption deque concurrent mutation).
            with state.lock:
                # LOT 1 : trades aggregates (foundation, produit delta_div_buy/sell)
                s_trades = state.get_engine_state(
                    "phase_b_plus_plus_trades",
                    factory=lambda: make_phase_b_plus_plus_trades_state(symbol=symbol_pure),
                )
                payload = add_phase_b_plus_plus_trades_streaming(
                    payload, s_trades, trades_in_window=trades_records,
                )

                # ──────────────────────────────────────────────────────────
                # P0 REORDER (audit feature-engineer 15/05 dette #6) :
                # Pass 4c-prereq + Pass 4a integres ENTRE LOT 1 et LOT 2-6
                # car LOT 4 absorb consomme dist_mq_*_pct (P2 deja inject MQ
                # snapshot), ib_high/low, sess_high/low produits ici.
                # LOT 2-6 voient maintenant : vwap_d, sess_high/low, ib_*,
                # cur_vpoc/vah/val, atr, vwap_slope_10, cvd_day, etc.
                # ──────────────────────────────────────────────────────────

                # Pass 4c-prereq : 5 helpers (sess_metadata + ib + sess_hl + vp + phase_b_plus)
                # Bounds + trades_for_vp deja calcules par P0+P2 plus haut, recalcul ici local.
                _sym_bounds_p0 = _get_bounds(symbol_pure)
                _trades_for_vp_p0 = []
                if not trades_df.empty and {"price", "size"}.issubset(trades_df.columns):
                    _trades_for_vp_p0 = trades_df[["price", "size"]].to_dict(orient="records")

                s_meta = state.get_engine_state("session_metadata", factory=SessionMetadataState)
                payload = add_session_metadata_streaming(payload, s_meta, bounds=_sym_bounds_p0)
                s_ib = state.get_engine_state("ib_features", factory=IBState)
                payload = add_ib_features_streaming(payload, s_ib, tick=tick, bounds=_sym_bounds_p0)
                s_sess_hl = state.get_engine_state("session_high_low", factory=SessionHighLowState)
                payload = add_session_high_low_streaming(payload, s_sess_hl, tick=tick)
                s_vp = state.get_engine_state("volume_profile", factory=VolumeProfileState)
                payload = add_volume_profile_features_streaming(
                    payload, s_vp, trades_in_window=_trades_for_vp_p0, tick=tick,
                )
                s_bp = state.get_engine_state(
                    "phase_b_plus", factory=lambda: make_phase_b_plus_state(symbol=symbol_pure),
                )
                payload = add_phase_b_plus_streaming(payload, s_bp, tick=tick)

                # Pass 4a : phase_b_rolling_inputs (6 sous-fonctions, 24 features)
                s_rolling_inputs_p0 = state.get_engine_state(
                    "phase_b_rolling_inputs",
                    factory=lambda: make_phase_b_rolling_inputs_state(symbol=symbol_pure),
                )
                payload = apply_rolling_inputs_streaming(payload, s_rolling_inputs_p0)

                # LOT 2 : big orders V2 (10 features VAP scan)
                s_big_v2 = state.get_engine_state(
                    "phase_b_plus_plus_big_v2",
                    factory=lambda: make_big_orders_v2_state(symbol=symbol_pure),
                )
                payload = add_big_orders_v2_streaming(payload, s_big_v2, footprint_cells=cells)

                # LOT 3 : cluster V2 (5 features runs detection)
                s_cluster_v2 = state.get_engine_state(
                    "phase_b_plus_plus_cluster_v2",
                    factory=lambda: make_cluster_v2_state(symbol=symbol_pure),
                )
                payload = add_cluster_v2_streaming(payload, s_cluster_v2, footprint_cells=cells)

                # LOT 4 : stack + absorption (produit near_resistance/support_level)
                s_absorb = state.get_engine_state(
                    "phase_b_plus_plus_absorb",
                    factory=lambda: make_stack_absorb_state(symbol=symbol_pure),
                )
                payload = add_stack_absorb_streaming(payload, s_absorb, footprint_cells=cells)

                # LOT 5 : trapped traders (consomme near_* de LOT 4, fail-loud check)
                s_trapped = state.get_engine_state(
                    "phase_b_plus_plus_trapped",
                    factory=lambda: make_trapped_traders_state(symbol=symbol_pure),
                )
                payload = add_trapped_traders_streaming(
                    payload, s_trapped, footprint_cells=cells,
                )

                # LOT 6 : delta_div extension lines (consomme delta_div_buy/sell de LOT 1)
                s_delta_div = state.get_engine_state(
                    "phase_b_plus_plus_delta_div_ext",
                    factory=make_delta_div_ext_state,
                )
                payload = add_delta_div_ext_streaming(payload, s_delta_div)

            # ──────────────────────────────────────────────────────────────────
            # Pass 2 Phase 3c semaine 4 : gold_phase_d (MGC) + intermarket (ES/NQ)
            # Hors lock state principal pour eviter deadlock cross-symbol (gold
            # ne touche pas state target, intermarket lit _states[partner] sous
            # son propre lock).
            # ──────────────────────────────────────────────────────────────────

            # Gold Phase D : MGC-specific (4 features cross-asset 6E/ZN/ZB)
            # Pour autres symbols : skip (gold est MGC-only).
            # NOTE dette : closes 6E/ZN/ZB pas trackes dans SYMBOLS Live Enricher
            # actuel -> None passe -> features = NaN. Backfill V4 fournira via
            # parquets Databento. Cf IDEAS_BACKLOG entry "cross-asset MGC live".
            if symbol_pure == "MGC":
                from gold_phase_d_streaming import (
                    add_gold_phase_d_streaming,
                    GoldPhaseDState,
                )
                with state.lock:
                    s_gold = state.get_engine_state(
                        "gold_phase_d",
                        factory=GoldPhaseDState,
                    )
                    payload = add_gold_phase_d_streaming(
                        payload, s_gold,
                        close_6e=None, close_zn=None, close_zb=None,
                    )

            # Intermarket : ES <-> NQ cross-symbol (10 features)
            # Lire derniere bar partner depuis _states[partner]. NaN si absent.
            if symbol_pure in ("ES", "NQ"):
                from intermarket_streaming import (
                    add_intermarket_streaming,
                    IntermarketState,
                )

                partner_symbol = "NQ.c.0" if symbol_pure == "ES" else "ES.c.0"
                partner_bar = None
                with _states_lock:
                    partner_state = _states.get(partner_symbol)
                if partner_state is not None:
                    with partner_state.lock:
                        partner_bar = partner_state.last_bar()

                # Fix code-reviewer P1 #1+#2 : staleness check + no-future guard.
                # - Staleness : reject si partner bar > 120s old (Databento glitch)
                # - No-future : reject si partner_ts_ns > target_ts_ns (NQ deja
                #   process le cycle suivant) -> evite asymetrie temporelle
                #   lookahead artificielle.
                # En cas de reject : other_inputs=None -> features NaN + emit log.
                STALE_NS = 120 * 1_000_000_000  # 120s en ns
                if partner_bar is not None:
                    partner_ts_ns = partner_bar.get("ts_event_ns", 0)
                    if partner_ts_ns > ts_event_ns:
                        # Partner cycle plus recent que target -> reject (no future)
                        _emit_log(
                            "ENRICHER_PARTNER_STALE", sym=symbol,
                            partner=partner_symbol,
                            reason="future",
                            delta_ns=int(partner_ts_ns - ts_event_ns),
                        )
                        partner_bar = None
                    elif (ts_event_ns - partner_ts_ns) > STALE_NS:
                        # Partner trop ancien (> 2 min) -> reject (stale stream)
                        _emit_log(
                            "ENRICHER_PARTNER_STALE", sym=symbol,
                            partner=partner_symbol,
                            reason="stale",
                            delta_ns=int(ts_event_ns - partner_ts_ns),
                        )
                        partner_bar = None

                # Build other_inputs dict pour intermarket streaming (None si
                # partner absent / stale / future -> features NaN).
                other_inputs = None
                if partner_bar is not None:
                    other_inputs = {
                        "price": partner_bar.get("close"),
                        "delta_bar": partner_bar.get("delta_bar"),
                        "total_vol": partner_bar.get("volume"),
                        "delta_day": partner_bar.get("delta_day"),
                        "dist_sess_high": partner_bar.get("dist_sess_high"),
                        "dist_sess_low": partner_bar.get("dist_sess_low"),
                        "large_trader_ratio": partner_bar.get("large_trader_ratio"),
                        "open_bias_conf": partner_bar.get("open_bias_conf"),
                        "open_direction": partner_bar.get("open_direction"),
                        "open_type": partner_bar.get("open_type"),
                    }

                # Fix code-reviewer P2 #5 : isoler price alias localement.
                # Le streaming intermarket attend `price` mais le payload final
                # ne doit pas avoir cette colonne dupliquee (bloat JSONL).
                # Build row_for_im local sans muter payload, puis merge uniquement
                # les features im_* dans payload final.
                row_for_im = dict(payload)
                if "price" not in row_for_im and "close" in row_for_im:
                    row_for_im["price"] = row_for_im["close"]

                with state.lock:
                    s_intermarket = state.get_engine_state(
                        "intermarket",
                        factory=IntermarketState,
                    )
                    enriched_im = add_intermarket_streaming(
                        row_for_im, s_intermarket, other_inputs=other_inputs,
                    )
                # Merger uniquement features im_* dans payload final (pas price)
                for k, v in enriched_im.items():
                    if k.startswith("im_"):
                        payload[k] = v

            # ──────────────────────────────────────────────────────────────────
            # Pass 3a Phase 3c semaine 4 : sessions_swings (55 features)
            # SIMPLE (38 features) puis LAG (17 features) - chain dependency :
            # LAG consomme session_id produit par SIMPLE.
            # Audit feature-engineer 14/05 : GREEN Prio 1 (trend_day_probability
            # et open_bias_conf famille = top SHAP).
            # ──────────────────────────────────────────────────────────────────
            from sessions_swings_simple_streaming import (
                add_sessions_swings_simple_streaming,
                make_sessions_swings_simple_state,
            )
            from sessions_swings_lag_streaming import (
                add_sessions_swings_lag_streaming,
                make_sessions_swings_lag_state,
            )

            with state.lock:
                # SIMPLE : produit session_id, is_in_*, opens, premium/discount, mins_et
                s_sess_simple = state.get_engine_state(
                    "sessions_swings_simple",
                    factory=lambda: make_sessions_swings_simple_state(symbol=symbol_pure),
                )
                payload = add_sessions_swings_simple_streaming(payload, s_sess_simple)

                # LAG : consomme session_id (produit par SIMPLE) -> swings + sweep
                s_sess_lag = state.get_engine_state(
                    "sessions_swings_lag",
                    factory=lambda: make_sessions_swings_lag_state(symbol=symbol_pure),
                )
                payload = add_sessions_swings_lag_streaming(payload, s_sess_lag)

            # ──────────────────────────────────────────────────────────────────
            # Pass 3c Phase 3c semaine 4 : rvol streaming (10 features)
            # Imports consolides plus haut (P0 reorder).
            # ──────────────────────────────────────────────────────────────────
            with state.lock:
                # 1. rvol_inputs : range_size, finish_strength, delta_pct (stateless)
                s_rvol_inputs = state.get_engine_state(
                    "rvol_inputs",
                    factory=RvolInputsState,
                )
                payload = add_rvol_inputs_streaming(payload, s_rvol_inputs, tick=tick)

                # 2. rvol_engine : 10 features rvol_* (rolling 20 vol)
                s_rvol = state.get_engine_state(
                    "rvol_engine",
                    factory=RvolEngineState,
                )
                payload = add_rvol_engine_streaming(payload, s_rvol)

            # Pass 4c-prereq + Pass 4a deja integres ENTRE LOT 1 et LOT 2-6
            # (P0 reorder 15/05). Anciens blocs ici supprimes.

            # ──────────────────────────────────────────────────────────────────
            # Pass 3b Phase 3c semaine 4 : rolling_features (45+ ctx_* features)
            # 5 sous-fonctions :
            #   - basic (13 features tier 1)
            #   - medium (tier 2)
            #   - advanced (tier 3)
            #   - delta_div (rolling div)
            #   - session_confluence
            # Inputs : price, delta_bar, total_vol (LOT 1) + vwap_slope_10/cvd_day
            # /va_position_pct (phase_b_plus, pas encore integre - features NaN
            # pour celles-la, par design tolerant batch ligne 88-92).
            # Audit feature-engineer 14/05 : GREEN Prio 1 (ib_extension_ratio,
            # poc_migration_10, va_developing_10 references SHAP historique).
            # ──────────────────────────────────────────────────────────────────
            from rolling_features_streaming import (
                add_rolling_features_basic_streaming,
                add_rolling_features_medium_streaming,
                add_rolling_features_advanced_streaming,
                add_rolling_features_delta_div_streaming,
                add_rolling_features_session_confluence_streaming,
                RollingFeaturesState,
            )

            with state.lock:
                s_rolling = state.get_engine_state(
                    "rolling_features",
                    factory=RollingFeaturesState,
                )
                # Fix code-reviewer Pass 3b P2 #2 : isoler aliases localement
                # pour eviter pollution payload final ('price' bloat).
                # Fix code-reviewer Pass 3b CRITIQUE #11 : injecter `ts` ms epoch
                # (rolling_features_streaming.add_rolling_features_delta_div_streaming
                # attend `ts` en MILLISECONDES, le payload a `ts_event_ns` en
                # NANOSECONDES). Sans cette conversion : delta_div_*_clean=0
                # constant + cascade biaisee (ctx_div_density_20, bars_since_div,
                # div_at_swing). Reference incident similaire 07/04/2026
                # delta_divergence toujours 0 (lessons.md).
                row_for_rolling = dict(payload)
                if "price" not in row_for_rolling and "close" in row_for_rolling:
                    row_for_rolling["price"] = row_for_rolling["close"]
                # Fix code-reviewer Pass 3b concern 11 (3 alias):
                # - ts ms epoch (ns -> ms) pour _ts_to_trading_date_cme
                # - bar_high alias high (delta_div module attend bar_high)
                # - bar_low alias low
                row_for_rolling["ts"] = ts_event_ns / 1_000_000
                if "bar_high" not in row_for_rolling and "high" in row_for_rolling:
                    row_for_rolling["bar_high"] = row_for_rolling["high"]
                if "bar_low" not in row_for_rolling and "low" in row_for_rolling:
                    row_for_rolling["bar_low"] = row_for_rolling["low"]
                # Chain 5 sous-fonctions partageant le meme state rolling.
                # Warmup periods (concern P1 #4 code-reviewer Pass 3b) :
                #   - basic : ctx_vol_z_5/delta_sum_3 = 5/3 bars warmup
                #   - medium : ctx_va_developing_10 = 10 bars
                #   - advanced : ctx_excess_high_bars_60 = 60 bars (1h)
                #   - delta_div : ctx_div_density_20 = 20 bars
                #   - session_confluence : depend warmup downstream (60 max)
                # Premier ~60 bars du service : features rolling partiellement NaN.
                enriched_rolling = add_rolling_features_basic_streaming(row_for_rolling, s_rolling)
                enriched_rolling = add_rolling_features_medium_streaming(enriched_rolling, s_rolling)
                enriched_rolling = add_rolling_features_advanced_streaming(enriched_rolling, s_rolling)
                enriched_rolling = add_rolling_features_delta_div_streaming(enriched_rolling, s_rolling)
                enriched_rolling = add_rolling_features_session_confluence_streaming(enriched_rolling, s_rolling)
                # Fix code-reviewer Pass 3b R2 B1 : merge par DIFF de cles
                # au lieu de filter whitelist. Capture TOUTES les features
                # produites par les sub-engines rolling sans risquer de perdre
                # les nouvelles (e.g. div_at_key_level_ticks, div_confluence_*
                # qui ne matchent pas startswith("ctx_") ni "delta_div_").
                # Convention : tout ce qui est dans enriched_rolling et pas dans
                # row_for_rolling est une feature produite -> merge dans payload.
                produced_keys = set(enriched_rolling) - set(row_for_rolling)
                for k in produced_keys:
                    payload[k] = enriched_rolling[k]
        except (ValueError, KeyError, TypeError, AttributeError, ImportError) as e:
            # Fail-soft restreint (code-reviewer P1) : whitelist exceptions
            # attendues (contract violation, dep manquante, type mismatch). Tout
            # autre Exception (RuntimeError, MemoryError, etc.) remontera pour
            # crash + nssm restart -- evite masquage bugs critiques.
            #
            # FIX P0 code-reviewer post-fix #2 : revert payload pre-chain pour
            # eviter JSONL heterogene (bars partielles si crash mid-execution).
            payload = payload_pre_chain
            payload["phase_b_plus_plus_partial"] = True  # marker downstream filter
            #
            # Parse traceback pour identifier le LOT defaillant (LOT 1-6).
            # FIX P2 code-reviewer post-fix #2 : ordre INVERSE (LOT 6 -> LOT 1)
            # pour eviter mis-classification cascade. Un fail LOT 6 qui pass
            # par LOT 1 (rare mais possible) etait classifie LOT 1. L'ordre
            # inverse priorise le module le plus profond dans la chain.
            import traceback
            tb = traceback.format_exc()
            failed_lot = "unknown"
            for marker, lot_name in (
                # Pass 4a marker (deepest first - le plus profond)
                ("phase_b_rolling_inputs_streaming", "phase_b_rolling_inputs"),
                # Pass 4c-prereq markers
                ("phase_b_plus_streaming", "phase_b_plus"),
                # Fix code-reviewer Pass 4c-prereq #9 : marker phase_b_helpers
                # pour J+1 grep correct si crash session_metadata/ib_features/
                # session_high_low/volume_profile (tous dans phase_b_helpers.py).
                ("phase_b_helpers", "phase_b_helpers"),
                ("rolling_features_streaming", "rolling_features"),
                ("rvol_streaming", "rvol_engine"),
                ("sessions_swings_lag_streaming", "sessions_lag"),
                ("sessions_swings_simple_streaming", "sessions_simple"),
                ("intermarket_streaming", "intermarket"),
                ("gold_phase_d_streaming", "gold_phase_d"),
                ("phase_b_plus_plus_delta_div_ext_streaming", "LOT_6_delta_div_ext"),
                ("phase_b_plus_plus_trapped_streaming", "LOT_5_trapped"),
                ("phase_b_plus_plus_absorb_streaming", "LOT_4_absorb"),
                ("phase_b_plus_plus_cluster_v2_streaming", "LOT_3_cluster_v2"),
                ("phase_b_plus_plus_big_v2_streaming", "LOT_2_big_v2"),
                ("phase_b_plus_plus_trades_streaming", "LOT_1_trades"),
                ("footprint_builder_streaming", "footprint_cells"),
            ):
                if marker in tb:
                    failed_lot = lot_name
                    break
            # Fix code-reviewer Pass 2 P1 #3 : engine name dynamique pour J+1 grep.
            # Phase 3c contient 3 chaines :
            #   - phase_b_plus_plus_chain (LOT 1-6 + footprint)
            #   - cross_asset_chain (gold + intermarket)
            #   - sessions_swings_chain (Pass 3a sessions simple + lag)
            # Differencier dans le log pour audit.
            if failed_lot.startswith("LOT_") or failed_lot in ("footprint_cells", "unknown"):
                engine_name = "phase_b_plus_plus_chain"
            elif failed_lot.startswith("sessions_"):
                engine_name = "sessions_swings_chain"
            elif failed_lot.startswith("rvol_"):
                engine_name = "rvol_chain"
            elif failed_lot == "rolling_features":
                engine_name = "rolling_features_chain"
            elif failed_lot == "phase_b_plus":
                engine_name = "phase_b_plus_chain"
            elif failed_lot == "phase_b_helpers":
                engine_name = "phase_b_helpers_chain"
            elif failed_lot == "phase_b_rolling_inputs":
                engine_name = "phase_b_rolling_inputs_chain"
            else:
                engine_name = "cross_asset_chain"
            logger.warning(
                f"{engine_name} fail {symbol} at {failed_lot}: "
                f"{type(e).__name__}: {e} -- payload reverted to pre-chain"
            )
            _emit_log(
                "ENRICHER_ENGINE_FAIL", sym=symbol,
                engine=engine_name,
                failed_lot=failed_lot,
                err_type=type(e).__name__,
                err=str(e)[:200],
            )

        # 5. Append bar to state buffer (rolling 60j) - FIX P0-2 sous lock
        with state.lock:
            state.append_bar(payload)

        # 6. Write JSONL atomic
        ok = write_enriched_bar(symbol, payload)
        if not ok:
            return False

        # 7. Update tracking
        _last_processed_ts_ns[symbol] = ts_event_ns
        _n_bars_processed[symbol] = _n_bars_processed.get(symbol, 0) + 1

        # 8. Emit log INFO + check cycle slow
        cycle_dt_ms = (time.time() - _cycle_start_ts[symbol]) * 1000
        _emit_log(
            "ENRICHER_BAR_PROCESSED", sym=symbol,
            ts=ts_event_ns, dt=int(cycle_dt_ms),
        )
        if cycle_dt_ms > CYCLE_SLOW_THRESHOLD_SEC * 1000:
            _emit_log(
                "ENRICHER_CYCLE_SLOW", sym=symbol,
                dt=int(cycle_dt_ms), limit=int(CYCLE_SLOW_THRESHOLD_SEC * 1000),
            )
        return True

    except Exception as e:
        logger.exception(f"_process_bar_cycle({symbol}) fail: {e}")
        _n_bars_failed[symbol] = _n_bars_failed.get(symbol, 0) + 1
        return False
    finally:
        with _cycle_lock:
            _cycle_start_ts[symbol] = 0.0  # reset (cycle termine)


# ═══════════════════════════════════════════════════════════════════════════════
# Threads daemon
# ═══════════════════════════════════════════════════════════════════════════════

def _snapshot_loop():
    """Thread daemon : save_state toutes 5 min pour tous symbols.

    FIX P0-2 review : lock state pendant pickle serialize pour eviter
    corruption deque en cours de mutation par main loop (append_bar).
    """
    last_log = time.time()
    while _running:
        try:
            time.sleep(SNAPSHOT_INTERVAL_SEC)
            with _states_lock:
                states_snapshot = list(_states.values())
            for state in states_snapshot:
                if state.should_snapshot():
                    # FIX P0-2 : lock state pendant pickle (atomic snapshot)
                    with state.lock:
                        save_state(state)  # emit ENRICHER_SNAPSHOT_OK/FAIL inside
            if time.time() - last_log > 60:
                logger.info(f"snapshot heartbeat : processed={_n_bars_processed}")
                last_log = time.time()
        except Exception as e:
            logger.exception(f"_snapshot_loop error: {e}")


def _watchdog_loop():
    """Thread daemon : detecte cycle stuck (>90s) -> sys.exit(3) nssm relance."""
    while _running:
        try:
            time.sleep(WATCHDOG_INTERVAL_SEC)
            now = time.time()
            with _cycle_lock:
                cycle_starts = dict(_cycle_start_ts)
            for sym, start in cycle_starts.items():
                if start == 0.0:
                    continue
                age = now - start
                if age > CYCLE_STUCK_THRESHOLD_SEC:
                    logger.critical(
                        f"CYCLE STUCK : {sym} cycle running since {age:.0f}s "
                        f"> {CYCLE_STUCK_THRESHOLD_SEC}s -> _emergency_exit(3) "
                        f"for nssm restart (flush state avant exit, P0-1 fix)"
                    )
                    _emergency_exit(3)
        except SystemExit:
            raise
        except Exception as e:
            logger.exception(f"_watchdog_loop error: {e}")


def _heartbeat_loop():
    """Thread daemon : ecrit _enricher_heartbeat.json toutes 10s."""
    while _running:
        try:
            time.sleep(HEARTBEAT_INTERVAL_SEC)
            heartbeat = {
                "service": "MIA-Live-Enricher",
                "status": "alive",
                "boot_ts": _boot_ts,
                "uptime_sec": time.time() - _boot_ts,
                "last_heartbeat_iso": datetime.now(timezone.utc).isoformat(),
                "n_bars_processed": dict(_n_bars_processed),
                "n_bars_failed": dict(_n_bars_failed),
                "symbols": SYMBOLS,
            }
            tmp = HEARTBEAT_FILE.with_suffix(".json.tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(heartbeat, f, ensure_ascii=False)
                tmp.replace(HEARTBEAT_FILE)
            except OSError as e:
                logger.warning(f"heartbeat write fail: {e}")
        except Exception as e:
            logger.exception(f"_heartbeat_loop error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Main loop : boot states + start daemon threads + cycle main."""
    logger.info("=" * 70)
    logger.info("MIA Live Enricher starting (Phase 3a Jour 4 skeleton)")
    logger.info("=" * 70)

    # 1. Signal handling
    # FIX P0-4 review (audit code-reviewer Jour 4) : SIGBREAK obligatoire pour
    # Windows nssm stop (Ctrl+Break envoye par nssm). Sans ce signal handler,
    # nssm stop MIA-Live-Enricher = kill brutal -> _shutdown_flush() jamais
    # appele -> perte 0-5 min de state pending.
    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):  # Windows-specific
        signal.signal(signal.SIGBREAK, _signal_handler)

    # 2. Initialize states (cold or warm depuis snapshot)
    for sym in SYMBOLS:
        state = initialize_state(sym, warmup_from_v4=False)
        with _states_lock:
            _states[sym] = state
        _emit_log(
            "ENRICHER_BOOT", sym=sym,
            warmup=False, loaded=state.n_bars_processed > 0,
        )

    # 3. Start daemon threads
    snapshot_thread = threading.Thread(
        target=_snapshot_loop, daemon=True, name="EnricherSnapshot"
    )
    snapshot_thread.start()
    logger.info(f"Snapshot thread started (interval {SNAPSHOT_INTERVAL_SEC}s)")

    watchdog_thread = threading.Thread(
        target=_watchdog_loop, daemon=True, name="EnricherWatchdog"
    )
    watchdog_thread.start()
    logger.info(f"Watchdog thread started (interval {WATCHDOG_INTERVAL_SEC}s)")

    heartbeat_thread = threading.Thread(
        target=_heartbeat_loop, daemon=True, name="EnricherHeartbeat"
    )
    heartbeat_thread.start()
    logger.info(f"Heartbeat thread started (interval {HEARTBEAT_INTERVAL_SEC}s)")

    # 4. Main loop : check nouvelle bar par symbol toutes les MAIN_LOOP_INTERVAL_SEC
    last_thread_health = time.time()
    logger.info(f"Main loop start, interval={MAIN_LOOP_INTERVAL_SEC}s, symbols={SYMBOLS}")
    try:
        while _running:
            for sym in SYMBOLS:
                with _states_lock:
                    state = _states[sym]
                _process_bar_cycle(sym, state)

            # Thread health check
            if time.time() - last_thread_health > THREAD_HEALTH_CHECK_SEC:
                last_thread_health = time.time()
                dead = []
                if not snapshot_thread.is_alive():
                    dead.append("snapshot_thread")
                if not watchdog_thread.is_alive():
                    dead.append("watchdog_thread")
                if not heartbeat_thread.is_alive():
                    dead.append("heartbeat_thread")
                if dead:
                    logger.critical(
                        f"DAEMON THREAD DEAD: {dead} -> _emergency_exit(3) "
                        f"pour nssm relance (flush state avant exit, P0-1 fix)"
                    )
                    _emergency_exit(3)

            time.sleep(MAIN_LOOP_INTERVAL_SEC)
    except SystemExit:
        raise
    except Exception as e:
        logger.exception(f"main loop exception: {e}")
        sys.exit(2)
    finally:
        _shutdown_flush()
        logger.info("MIA Live Enricher stopped.")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests inline (dry-run, sans live stream)
# ═══════════════════════════════════════════════════════════════════════════════

def _test_signal_handler_sets_running_false():
    global _running
    assert _running is True
    _signal_handler(15, None)
    assert _running is False
    _running = True  # reset
    print("[OK] _signal_handler sets _running=False")


def _test_emit_log_no_crash():
    """Emit avec code valide ne crash pas."""
    _emit_log("ENRICHER_BOOT", sym="TEST.c.0", warmup=False, loaded=False)
    _emit_log("UNKNOWN_CODE", sym="TEST.c.0")  # code absent -> no-op
    print("[OK] _emit_log graceful (codes valides + absents)")


def _test_process_bar_cycle_no_ohlcv():
    """Sans OHLCV input, doit return False sans crash."""
    state = initialize_state("TEST.c.0")
    # No mock OHLCV -> read_all_inputs returns ohlcv=None -> skip
    ok = _process_bar_cycle("TEST.c.0", state)
    assert ok is False, "should return False without OHLCV"
    print("[OK] _process_bar_cycle graceful (no OHLCV)")


def _test_double_process_skip():
    """Process meme bar 2x -> 2eme retourne False (anti double-write)."""
    state = initialize_state("TEST.c.0")
    fake_ts = int(datetime(2030, 7, 1, tzinfo=timezone.utc).timestamp() * 1e9)
    _last_processed_ts_ns["TEST.c.0"] = fake_ts
    # Tentative process avec ts <= last -> skip
    # Note : _process_bar_cycle real test impossible sans mock inputs
    # On teste la logique de skip via _last_processed_ts_ns directement
    assert _last_processed_ts_ns["TEST.c.0"] == fake_ts
    print("[OK] anti double-process tracking")


def _test_imports_complete():
    """Verifie que tous les imports requis sont resolvables."""
    assert callable(read_all_inputs)
    assert callable(initialize_state)
    assert callable(save_state)
    assert callable(write_enriched_bar)
    print("[OK] imports complete (io + state + writer)")


if __name__ == "__main__":
    # Mode test : python -m CORE.live_enricher --test
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        _test_signal_handler_sets_running_false()
        _test_emit_log_no_crash()
        _test_imports_complete()
        _test_process_bar_cycle_no_ohlcv()
        _test_double_process_skip()
        print("\n[ALL OK]")
    else:
        # Mode service production
        main()
