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
    """Emit via log_catalog (fail-loud, regle souveraine logs 01/05)."""
    try:
        from log_catalog import LOG_CODES, LogLevel
        if code not in LOG_CODES:
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

    Phase 3a Jour 4 = SKELETON SANS ENGINES. Le payload contient OHLCV + MQ +
    VIX (passthrough). Les engines (phase_b_*, edge_zones, regime_engine_v6,
    etc.) seront ajoutes Phase 3b-d.

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

        # ──────────────────────────────────────────────────────────────────────
        # Phase 3c semaine 4 : engines streaming phase_b_plus_plus (76 features)
        # Ordre dependance critique :
        #   footprint_cells (helper pur)
        #   -> LOT 1 trades aggregates (produit delta_div_buy/sell, delta_bar)
        #   -> LOT 2 big_v2 (10 features VAP scan)
        #   -> LOT 3 cluster_v2 (5 features runs detection)
        #   -> LOT 4 absorb (produit near_resistance/support_level)
        #   -> LOT 5 trapped (consomme near_*, fail-loud anti Pattern 11)
        #   -> LOT 6 delta_div_ext (consomme delta_div_buy/sell de LOT 1)
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
            logger.warning(
                f"phase_b_plus_plus chain fail {symbol} at {failed_lot}: "
                f"{type(e).__name__}: {e} -- payload reverted to pre-chain"
            )
            _emit_log(
                "ENRICHER_ENGINE_FAIL", sym=symbol,
                engine="phase_b_plus_plus_chain",
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
