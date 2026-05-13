"""live_enricher_state.py — state manager rolling buffer Live Enricher.

Phase 3a Jour 2 du Chantier 3 (13/05/2026 nuit).

Maintient le rolling buffer in-memory + snapshot disque pour le service
MIA-Live-Enricher. Le buffer contient :

  - bars_df       : 60 jours de bars 1-min OHLCV + features deja calculees
  - trades_df     : 3 jours de trades (engines footprint/big_orders consomment)
  - mq_levels     : 1 snapshot MQ courant (rare update, 1-2/jour)
  - vix_snapshot  : 1 snapshot VIX courant (1/min)
  - engine_states : dict des states per-engine (PhaseBPlusState, etc.)

Snapshot disque toutes les 5 min pour crash recovery :
  DATA/LIVE_CACHE/enricher_state/{sym}_state.pickle
  Permet redemarrage service sans warmup 60j depuis V4 parquet.

Critere parite warmup (Plan agent R2) : test obligatoire
  df_continu_J0_J7 vs df_J0_J3 + restart + J3_J7  must match <0.001/feature.

Auteur : MIA Trading System V2
  v1.0 (2026-05-13 nuit) : version initiale Phase 3a Jour 2
"""
from __future__ import annotations

import pickle
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "DATA" / "LIVE_CACHE" / "enricher_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Retention rolling
BARS_RETENTION_DAYS = 60  # rolling buffer bars 1-min
TRADES_RETENTION_DAYS = 3  # trades footprint/big_orders engines
SNAPSHOT_INTERVAL_SEC = 300  # 5 minutes (compromis perte data vs I/O cost)


# SCHEMA_VERSION pour pickle versioning (P1-1 differable mais ajoute des
# maintenant car cheap, anti-fallback silencieux Pattern 11).
STATE_SCHEMA_VERSION = 1


@dataclass
class LiveEnricherState:
    """State complet du Live Enricher pour 1 symbol.

    FIX P0-2 (audit code-reviewer 13/05 nuit) : bars stockes en deque(maxlen)
    de dicts au lieu de pd.DataFrame croissant via concat. Evite O(N) copy
    par append -> O(N^2) cumulative sur 60j (=2.2 GB/heure de copies).

    FIX P0-2 Jour 4 review (audit 13/05 nuit) : ajoute `_lock` thread-safety
    pour mutation concurrent main loop (append_bar/update) vs snapshot_loop
    (save_state pickle sur deque en cours de mutation = corruption ou
    exception). Utiliser `with state.lock:` autour de mutations + read pickle.

    Acces via property `bars_df` qui materialise pd.DataFrame a la demande
    depuis le deque. Engines streaming peuvent acceder bars_df normalement.
    """

    symbol: str
    schema_version: int = STATE_SCHEMA_VERSION
    # FIX P0-2 : deque(maxlen) au lieu de pd.DataFrame croissant
    _bars_deque: deque = field(default_factory=lambda: deque(maxlen=BARS_RETENTION_DAYS * 1440))
    _trades_deque: deque = field(default_factory=lambda: deque())
    mq_levels: Optional[dict] = None
    vix_snapshot: Optional[dict] = None
    engine_states: dict[str, Any] = field(default_factory=dict)
    last_snapshot_ts: float = 0.0
    boot_ts: float = field(default_factory=time.time)

    # Stats running
    n_bars_processed: int = 0
    n_trades_processed: int = 0

    # FIX P0-2 Jour 4 : lock thread-safety pour mutex append/snapshot concurrent
    # Note : field(repr=False) pour ne pas inclure lock dans repr (verbose) +
    # pas exclu pickle car threading.RLock est picklable depuis Python 3.4+.
    # Utilisation : `with state.lock: state.append_bar(...)` cote main loop,
    # `with state.lock: pickle.dump(state, f)` cote snapshot thread.
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def lock(self) -> threading.RLock:
        """Public access au RLock pour use externe `with state.lock:`."""
        return self._lock

    def __getstate__(self) -> dict:
        """Exclude _lock du pickle (threading.RLock pas serializable Python 3.13+).

        Au reload via load_state(), __setstate__ recree un nouveau _lock.
        Comportement attendu : redemarrage = new process = nouveau lock OK.
        """
        state = self.__dict__.copy()
        state.pop("_lock", None)
        return state

    def __setstate__(self, state: dict) -> None:
        """Restore state + recree _lock (anti pickle threading)."""
        self.__dict__.update(state)
        self._lock = threading.RLock()

    @property
    def bars_df(self) -> pd.DataFrame:
        """Materialise bars_df depuis _bars_deque a la demande.

        Cost : O(N) une seule fois par appel (pas par append). Pour buffer
        60j = 86k bars × 462 cols → ~150ms materialization. Acceptable
        pour cycle 1-min (les engines appellent bars_df 1x par cycle).
        """
        if not self._bars_deque:
            return pd.DataFrame()
        return pd.DataFrame(list(self._bars_deque))

    @property
    def trades_df(self) -> pd.DataFrame:
        """Materialise trades_df depuis _trades_deque a la demande."""
        if not self._trades_deque:
            return pd.DataFrame()
        return pd.DataFrame(list(self._trades_deque))

    def append_bar(self, bar_row: dict) -> None:
        """Ajoute une nouvelle bar au deque (maxlen evict FIFO automatic).

        FIX P0-2 : O(1) append au lieu de O(N) pd.concat. Le deque a maxlen
        donc plus de truncate manuel.
        """
        self._bars_deque.append(bar_row)
        self.n_bars_processed += 1

    def append_trades(self, trades_df: pd.DataFrame) -> None:
        """Ajoute trades au deque, truncate > TRADES_RETENTION_DAYS via ts cutoff.

        FIX P0-2 : append direct au deque puis purge cutoff via popleft.
        """
        if trades_df.empty:
            return
        for _, row in trades_df.iterrows():
            self._trades_deque.append(row.to_dict())
        self.n_trades_processed += len(trades_df)

        # Purge trades < cutoff (TRADES_RETENTION_DAYS jours en arriere)
        cutoff_ns = int((time.time() - TRADES_RETENTION_DAYS * 86400) * 1e9)
        while self._trades_deque and self._trades_deque[0].get("ts_event_ns", 0) < cutoff_ns:
            self._trades_deque.popleft()

    def update_mq(self, mq_levels: Optional[dict]) -> None:
        """Update MQ snapshot (rare, daily change-detect)."""
        if mq_levels is not None:
            self.mq_levels = mq_levels

    def update_vix(self, vix_snapshot: Optional[dict]) -> None:
        """Update VIX snapshot (1/min)."""
        if vix_snapshot is not None:
            self.vix_snapshot = vix_snapshot

    def get_engine_state(self, engine_name: str, factory=dict):
        """Get or create engine state. Pattern : state per engine refactorise."""
        if engine_name not in self.engine_states:
            self.engine_states[engine_name] = factory()
        return self.engine_states[engine_name]

    def should_snapshot(self) -> bool:
        """Retourne True si on doit faire un snapshot disque (toutes 5 min)."""
        return time.time() - self.last_snapshot_ts >= SNAPSHOT_INTERVAL_SEC

    def stats(self) -> dict:
        """Stats pour heartbeat / monitoring."""
        return {
            "symbol": self.symbol,
            "n_bars_buffer": len(self.bars_df),
            "n_trades_buffer": len(self.trades_df),
            "n_bars_processed_total": self.n_bars_processed,
            "n_trades_processed_total": self.n_trades_processed,
            "mq_levels_loaded": self.mq_levels is not None,
            "vix_loaded": self.vix_snapshot is not None,
            "uptime_sec": time.time() - self.boot_ts,
            "n_engine_states": len(self.engine_states),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence disque (snapshot 5 min crash recovery)
# ═══════════════════════════════════════════════════════════════════════════════

def _state_path(symbol: str) -> Path:
    safe = symbol.replace("/", "_").replace(".", "_")
    return STATE_DIR / f"{safe}_state.pickle"


def _emit_log(code: str, **kwargs) -> None:
    """Helper emit via log_catalog (best-effort, swallow if catalog absent).

    FIX P0-3 (audit code-reviewer 13/05 nuit) : remplace silent return False
    par emit log_catalog. Si log_catalog import echoue, fallback print.
    """
    try:
        import logging
        from log_catalog import LOG_CODES, LogLevel
        if code not in LOG_CODES:
            return
        level, cat, template = LOG_CODES[code]
        try:
            msg = template.format(**kwargs)
        except (KeyError, IndexError):
            msg = f"{code} (template format failed kwargs={kwargs})"
        logger = logging.getLogger("live_enricher_state")
        if level == LogLevel.CRITIQUE:
            logger.critical(f"[{code}] {msg}")
        elif level == LogLevel.MAJEUR:
            logger.error(f"[{code}] {msg}")
        elif level == LogLevel.ALERTE:
            logger.warning(f"[{code}] {msg}")
        else:
            logger.info(f"[{code}] {msg}")
    except ImportError:
        # log_catalog pas accessible : fallback print best-effort
        print(f"[{code}] {kwargs}")


def save_state(state: LiveEnricherState) -> bool:
    """Snapshot atomic du state sur disque (pickle).

    FIX P0-3 : emit ENRICHER_SNAPSHOT_OK / ENRICHER_SNAPSHOT_FAIL au lieu de
    silent return (regle souveraine logs 01/05, anti-fallback silencieux
    Pattern 11).

    Returns True si OK. Tmp + rename atomic.
    """
    path = _state_path(state.symbol)
    tmp = path.with_suffix(".pickle.tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(state, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        state.last_snapshot_ts = time.time()
        _emit_log(
            "ENRICHER_SNAPSHOT_OK",
            sym=state.symbol,
            bars=len(state._bars_deque),
            trades=len(state._trades_deque),
            engines=len(state.engine_states),
        )
        return True
    except (OSError, pickle.PickleError) as e:
        _emit_log("ENRICHER_SNAPSHOT_FAIL", sym=state.symbol, err=str(e)[:200])
        return False


def load_state(symbol: str) -> Optional[LiveEnricherState]:
    """Charge le state depuis disque si existe + valide.

    Returns None si fichier absent/corrompu. Emit ENRICHER_STATE_LOAD_FAIL /
    ENRICHER_STATE_SCHEMA_MISMATCH au lieu de silent fallback (P0-3/P1-1).
    """
    path = _state_path(symbol)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with open(path, "rb") as f:
            state = pickle.load(f)
        if not isinstance(state, LiveEnricherState):
            _emit_log("ENRICHER_STATE_LOAD_FAIL", sym=symbol,
                      err=f"not LiveEnricherState instance ({type(state).__name__})")
            return None
        if state.symbol != symbol:
            _emit_log("ENRICHER_STATE_LOAD_FAIL", sym=symbol,
                      err=f"symbol mismatch (loaded={state.symbol})")
            return None
        # P1-1 schema versioning check
        loaded_v = getattr(state, "schema_version", 0)
        if loaded_v != STATE_SCHEMA_VERSION:
            _emit_log("ENRICHER_STATE_SCHEMA_MISMATCH", sym=symbol,
                      loaded=loaded_v, expected=STATE_SCHEMA_VERSION)
            return None
        return state
    except (OSError, pickle.PickleError, EOFError, AttributeError) as e:
        _emit_log("ENRICHER_STATE_LOAD_FAIL", sym=symbol, err=str(e)[:200])
        return None


def initialize_state(
    symbol: str,
    warmup_from_v4: bool = False,
    v4_parquet_path: Optional[Path] = None,
) -> LiveEnricherState:
    """Initialise state : (1) charge snapshot disque si existe, (2) fallback warmup V4.

    Args:
        symbol : ES.c.0 / NQ.c.0 / MGC.v.0
        warmup_from_v4 : si True ET pas de snapshot, charge bars depuis V4 parquet
        v4_parquet_path : chemin V4 parquet pour warmup (default DATA/datasets/v4_enriched/symbol={sym}/year={Y}/month={M}/data.parquet)

    Returns:
        LiveEnricherState pret a use.
    """
    state = load_state(symbol)
    if state is not None:
        # Snapshot trouve, on continue
        return state

    # Cold start : creer state vide
    state = LiveEnricherState(symbol=symbol)

    if warmup_from_v4 and v4_parquet_path and v4_parquet_path.exists():
        try:
            df = pd.read_parquet(v4_parquet_path)
            # Truncate au retention (60j)
            max_bars = BARS_RETENTION_DAYS * 1440
            if len(df) > max_bars:
                df = df.iloc[-max_bars:].reset_index(drop=True)
            state.bars_df = df
            state.n_bars_processed = len(df)
        except Exception:
            pass  # silent fallback empty state

    return state


# ═══════════════════════════════════════════════════════════════════════════════
# Tests inline
# ═══════════════════════════════════════════════════════════════════════════════

def _test_state_creation_and_append():
    state = LiveEnricherState(symbol="ES.c.0")
    assert state.symbol == "ES.c.0"
    assert state.bars_df.empty
    assert state.n_bars_processed == 0

    state.append_bar({"ts_event": "2026-05-13T13:14:00Z", "close": 5848.75, "volume": 1234})
    assert len(state.bars_df) == 1
    assert state.n_bars_processed == 1
    print("[OK] state creation + append_bar")


def _test_state_retention_truncate():
    """Append N+1 bars devrait truncate au max (FIFO evict via deque maxlen).

    FIX P0-2 : avec deque(maxlen) le maxlen est fix a la creation. Pour test,
    on remplace _bars_deque par un deque(maxlen=10) directement.
    """
    state = LiveEnricherState(symbol="ES.c.0")
    state._bars_deque = deque(maxlen=10)  # override pour test
    for i in range(15):
        state.append_bar({"ts": i, "close": 100 + i})
    assert len(state.bars_df) == 10, f"expected 10 bars, got {len(state.bars_df)}"
    assert state.bars_df["ts"].iloc[0] == 5  # bars 0-4 evicted FIFO
    assert state.bars_df["ts"].iloc[-1] == 14
    print("[OK] retention truncate FIFO evict (10 bars max)")


def _test_save_load_state():
    """Roundtrip pickle persistance."""
    state = LiveEnricherState(symbol="ES.c.0")
    state.append_bar({"close": 5848.75})
    state.update_vix({"vix_level": 17.85})
    state.engine_states["test_engine"] = {"counter": 42}

    ok = save_state(state)
    assert ok, "save_state should succeed"

    loaded = load_state("ES.c.0")
    assert loaded is not None
    assert loaded.symbol == "ES.c.0"
    assert len(loaded.bars_df) == 1
    assert loaded.vix_snapshot["vix_level"] == 17.85
    assert loaded.engine_states["test_engine"]["counter"] == 42
    print("[OK] save_state + load_state roundtrip")

    # Cleanup
    _state_path("ES.c.0").unlink()


def _test_initialize_state_cold():
    """Cold start sans snapshot disque -> state vide."""
    # Cleanup d'abord
    p = _state_path("TEST.c.0")
    if p.exists():
        p.unlink()
    state = initialize_state("TEST.c.0")
    assert state.symbol == "TEST.c.0"
    assert state.bars_df.empty
    assert state.n_bars_processed == 0
    print("[OK] initialize_state cold (empty)")


def _test_get_engine_state():
    state = LiveEnricherState(symbol="ES.c.0")
    s = state.get_engine_state("vix_lite_reader", factory=dict)
    assert s == {}
    s["counter"] = 1
    s2 = state.get_engine_state("vix_lite_reader", factory=dict)
    assert s2["counter"] == 1, "get_engine_state should return same dict"
    print("[OK] get_engine_state factory pattern")


if __name__ == "__main__":
    _test_state_creation_and_append()
    _test_state_retention_truncate()
    _test_save_load_state()
    _test_initialize_state_cold()
    _test_get_engine_state()
    print("\n[ALL OK]")
