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

    def last_bar(self) -> Optional[dict]:
        """Retourne la derniere bar enrichie ou None si buffer vide.

        Cost O(1) (deque[-1]). Utilise pour cross-symbol access dans
        engines intermarket (ES <-> NQ partner bar) sans materialiser
        bars_df full (qui serait O(N) sur 60j buffer).

        Caller doit acquerir `state.lock` AVANT pour eviter race avec
        snapshot_loop / main loop concurrent mutation.
        """
        if not self._bars_deque:
            return None
        return self._bars_deque[-1]

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


def _seed_open_cash_price1030_from_warmup(
    state: LiveEnricherState, symbol: str, df: Optional[pd.DataFrame] = None,
) -> None:
    """R2 fix Pass 4 (15/05/2026) : seed OpenCashPrice1030State depuis bars_df warmup.

    Sans seed, cold start cycle (c) du R2 (boot apres 10:30 ET) =
    `cached_open_cash`/`cached_price_1030` vides -> classify_open_type UNKNOWN
    jusqu'a J+1 09:30. Reproduit Pattern V1 (silent feature dead).

    Strategie : lit derniere valeur non-nulle de `open_cash` + `price_1030`
    pour le `date_et` le plus recent dans bars_df, instancie
    OpenCashPrice1030State pre-rempli pour ce date_et.

    Args:
        state : LiveEnricherState a seeder.
        symbol : pour log emit.
        df : DataFrame deja en memoire (R2 fix code-reviewer : evite double
             materialization O(N) via state.bars_df property). Si None, fallback
             materialise depuis le deque (rare path test seul).

    Limite scenario edge : si cold start entre 09:30 et 10:30 ET et batch V4
    n'a pas encore capture J0 (delay Databento 15 min), seed = None et
    streaming captures normalement sur la prochaine bar reelle.
    """
    if df is None:
        df = state.bars_df
    if df.empty or "date_et" not in df.columns:
        return
    # Fix Jackson 15/05/2026 cold start : V4 batch peut avoir derniere bars
    # avec Phase B PAS ENCORE RUN (intra-day buffer). Ces bars ont date_et=None.
    # On prend la derniere bar AVEC date_et non-NaN (= Phase B done).
    df_valid = df[df["date_et"].notna()]
    if df_valid.empty:
        return
    try:
        today_et = df_valid["date_et"].iloc[-1]
    except (IndexError, KeyError):
        return
    df_today = df_valid[df_valid["date_et"] == today_et]
    if df_today.empty:
        return

    cached_oc = None
    cached_p1030 = None
    if "open_cash" in df_today.columns:
        valid = df_today["open_cash"].dropna()
        if len(valid):
            cached_oc = float(valid.iloc[-1])
    if "price_1030" in df_today.columns:
        valid = df_today["price_1030"].dropna()
        if len(valid):
            cached_p1030 = float(valid.iloc[-1])

    if cached_oc is None and cached_p1030 is None:
        return  # rien a seeder (J0 cold start pre-09:30 ou V4 obsolete)

    # Dual import path (fix R3 code-reviewer 15/05) : nssm service peut tourner
    # avec AppDirectory=ROOT (CORE/. dans sys.path) OU AppDirectory=CORE
    # (ROOT/. dans sys.path). Pattern aligne mia_paper_trader.py:33-36.
    try:
        from CORE.phase_b_helpers import OpenCashPrice1030State
    except ImportError:
        try:
            from phase_b_helpers import OpenCashPrice1030State
        except ImportError:
            _emit_log("ENRICHER_SEED_IMPORT_FAIL", sym=symbol)
            return

    seeded = OpenCashPrice1030State(
        current_date_et=today_et,
        cached_open_cash=cached_oc,
        cached_price_1030=cached_p1030,
    )
    state.engine_states["open_cash_price1030"] = seeded
    _emit_log(
        "ENRICHER_SEED_OPEN_CASH_FROM_V4",
        sym=symbol,
        date=str(today_et),
        open_cash=cached_oc,
        price_1030=cached_p1030,
    )


def _seed_sessions_swings_from_warmup(
    state: LiveEnricherState, symbol: str, df: Optional[pd.DataFrame] = None,
) -> None:
    """Audit Pass 4 multi-bars (15/05/2026) : seed SessionsSwingsSimpleState depuis V4.

    Sans seed, cold start mid-London (boot 06:30 ET) =
    asia_high/low/open + london_open + ny_open vides puisque sessions Asia
    deja passees. Le streaming reset state sur session_date_trading change
    et n'a aucun mecanisme de catch-up sessions historiques.

    V4 batch a 1109/1109 asia_*/asia_open via add_session_high_low + capture
    1ere bar. On lit la derniere bar V4 du session_date_trading courant qui
    contient les running highs/lows broadcast.
    """
    if df is None:
        df = state.bars_df
    if df.empty:
        return
    # Today's session_date_trading = derniere valeur AVEC session_date_trading
    # non-None (V4 batch peut avoir bars Phase B PAS ENCORE RUN ou la valeur
    # est None — cas observe 15/05 cold start).
    if "session_date_trading" not in df.columns:
        return
    df_sdt_valid = df[df["session_date_trading"].notna()]
    if df_sdt_valid.empty:
        return
    try:
        today_sdt = df_sdt_valid["session_date_trading"].iloc[-1]
    except (IndexError, KeyError):
        return
    df_today = df_sdt_valid[df_sdt_valid["session_date_trading"] == today_sdt]
    if df_today.empty:
        return

    # Fix Jackson 15/05/2026 cold start : V4 batch peut avoir derniere bars
    # avec Phase B PAS ENCORE RUN (intra-day buffer, live_pipeline 5 min cron).
    # Ces bars ont asia_high=NaN, session_date_trading=None.
    # On prend la DERNIERE bar AVEC asia_high non-NaN (= bar Phase B done).
    if "asia_high" in df_today.columns:
        df_valid = df_today[df_today["asia_high"].notna()]
        if df_valid.empty:
            return  # aucune bar Phase B valide today (rebuild pipeline needed)
        last_row = df_valid.iloc[-1].to_dict()
    else:
        last_row = df_today.iloc[-1].to_dict()
    sessions_cols = [
        "asia_high", "asia_low", "london_high", "london_low",
        "us_high", "us_low", "after_high", "after_low",
        "asia_open", "london_open", "ny_open", "after_open",
    ]
    seed_values = {}
    for c in sessions_cols:
        v = last_row.get(c)
        if v is not None and not (isinstance(v, float) and v != v):
            seed_values[c] = float(v)
    if not seed_values:
        return  # rien a seeder

    try:
        from CORE.sessions_swings_simple_streaming import (
            make_sessions_swings_simple_state,
        )
    except ImportError:
        try:
            from sessions_swings_simple_streaming import (
                make_sessions_swings_simple_state,
            )
        except ImportError:
            _emit_log("ENRICHER_SEED_IMPORT_FAIL", sym=symbol)
            return

    # Factory cree state per-symbole avec bounds
    sym_pure = symbol.split(".")[0]  # ES.c.0 -> ES, MGC.v.0 -> MGC
    seeded = make_sessions_swings_simple_state(symbol=sym_pure)
    seeded.current_session_date = today_sdt
    for c, v in seed_values.items():
        if hasattr(seeded, c):
            setattr(seeded, c, v)

    state.engine_states["sessions_swings_simple"] = seeded
    _emit_log(
        "ENRICHER_SEED_SESSIONS_FROM_V4",
        sym=symbol,
        sdt=str(today_sdt),
        n_values=len(seed_values),
        keys=",".join(sorted(seed_values.keys()))[:200],
    )


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
            # FIX R2 Pass 4 (15/05/2026) : bars_df est @property read-only depuis
            # FIX P0-2 (deque). L'ancien `state.bars_df = df` levait AttributeError
            # silencieusement avale par except: pass = warmup completement mort.
            # Pattern V1 cousin (silent fallback). On append au deque via API.
            for row in df.to_dict(orient="records"):
                state._bars_deque.append(row)
            state.n_bars_processed = len(df)
            _emit_log(
                "ENRICHER_WARMUP_OK",
                sym=symbol, n_bars=len(df), path=str(v4_parquet_path),
            )
            # R2 seed: pre-fill OpenCashPrice1030State depuis derniere bar today.
            # On passe df directement (eviter double-materialization via property).
            _seed_open_cash_price1030_from_warmup(state, symbol, df=df)
            # Audit Pass 4 (15/05) : seed SessionsSwingsSimpleState asia_*/opens
            # depuis V4. Sans ce seed, boot mid-London = asia jamais traque.
            _seed_sessions_swings_from_warmup(state, symbol, df=df)
        except Exception as e:
            # Non-silent : emit + log (anti-Pattern V1 reglesouveraine logs 01/05)
            _emit_log("ENRICHER_WARMUP_FAIL", sym=symbol, err=str(e)[:200])

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
