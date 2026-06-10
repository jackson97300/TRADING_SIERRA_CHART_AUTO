"""bn_v5_paper.py — Paper trader BN V5 minimal (Sim2 Topstep).

Architecture simplifiee vs bn_v4_paper.py :
  - Lit JSONL live_enriched (lag 60s) via LiveEnrichedReader (reutilise infra)
  - Detect setups via BNV5Engine.check_zone (V/W/∧/M + conf + range + bar reversal)
  - DTC bracket OCO (reutilise dtc_connector)
  - Trail via update_trailing (Dow pullback 3 bars)
  - Anti-orphan basique (cancel TP+SL au close, pas Type 209/210 nuclear)
  - Logger v2 codes BN_V5_*

Kill switches ENV :
  MIA_BN_V5_ENABLED=0/1            (default 0 = process exit immediat)
  MIA_BN_V5_DRY_RUN=0/1            (default 1 = log only, pas DTC)
  MIA_BN_V5_TRADE_ACCOUNT=Sim2     (Topstep simulation)
  MIA_BN_V5_SYMBOLS=NQ,ES          (default NQ,ES)

Integration : instancie + wire depuis databento_paper_trader_v2.py
(comme BN V4). poll_cycle() appele a chaque iteration paper_v2 main loop.

Auteur : MIA Trading V2 v0.1 (2026-06-02 nuit)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
sys.path.insert(0, str(ROOT / "BOT"))

# 09/06 FIX BUG #1 persistance daily_stop (review code-reviewer 7 reserves) :
# State file persistant pour survivre aux restarts service Windows nssm.
# FAIL-CLOSED si corruption (no silent fallback init=0 = pattern 19/04 meta-labeler).
# Bypass explicite via env MIA_BN_V5_STATE_RESET=1.
_STATE_FILE = ROOT / "DATA" / "PAPER_TRADES" / "bn_v5_session_state.json"
_STATE_SCHEMA_VERSION = 1
_STATE_MAX_AGE_HOURS = 8  # rejette state si >8h (= nouvelle session probablement)
_STATE_HEARTBEAT_SAVE_MIN = 2  # save periodique (vs HEARTBEAT_INTERVAL_MIN 10 pour emit)
_STATE_REQUIRED_KEYS = frozenset({
    "schema_version", "session_date_utc", "n_bars_processed", "n_setups_detected",
    "n_trades_executed", "pnl_session_usd", "daily_stop_triggered",
    "daily_stop_reason", "last_update_ts",
})

from bn_v5_engine import (
    BNV5Engine, BNV5Params, Setup, TrailingStateV5,
    SIDE_LONG, SIDE_SHORT,
    TICK_BY_SYMBOL, TICK_VAL_USD_BY_SYMBOL,
    init_trailing, update_trailing, is_sl_hit, is_timeout,
)
from live_enriched_reader import LiveEnrichedReader

# 10/06 ULTRATHINK BN V5 — Chantier persistance positions cross-restart
# (parite Bot 3 v3 Sprint Phase 1 09/06 generalisee).
# State session existant (bn_v5_session_state.json) preserve (BUG #1 fix 09/06).
# Nouveau : bn_v5_positions_state.json pour positions + signal_counter + cooldown meta.
try:
    from bot_persistance import (
        PositionPersistance, BotStateLoadError, ReconcileReport,
    )
except ImportError:
    from CORE.bot_persistance import (
        PositionPersistance, BotStateLoadError, ReconcileReport,
    )

# DTC constants
try:
    from dtc_connector import BUY as DTC_BUY, SELL as DTC_SELL
except ImportError:
    DTC_BUY = 1
    DTC_SELL = 2

# Logging v2
try:
    from logging_v2 import get_logger
    _v2log = get_logger("bn_v5_paper", process="paper_v2")
except ImportError:
    _v2log = None


__version__ = "0.1.0"


# Symbol -> SC contract mapping (rollback 03/06 : 1 NQ E-mini + 1 ES E-mini)
SYMBOL_TO_CONTRACT = {
    "NQ": "NQM26-CME",           # E-mini NQ (1 contrat)
    "ES": "ESM26-CME",           # E-mini ES (1 contrat)
    "MGC": "MGCM26-CMECOMEX",    # Micro Gold (1 contrat)
}


def _emit(code: str, **ctx) -> None:
    """Helper emit via logging_v2 (best-effort, no-op si module absent)."""
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception:
            pass


# FIX R3 03/06 — marker heartbeat dedie pour watchdog Bot2_BN_V5.
# Apres suppression check obsolete Bot2_BN_V4 (15:23 UTC), gap couverture
# detecte par code-reviewer : si BN V5 plante silencieusement (Bot 1/3 OK),
# pas de detection. Ce marker permet au watchdog de surveiller specifiquement
# BN V5 via glob_mtime sur LOGS/bn_v5/bn_v5_v1_YYYYMMDD.jsonl.
# Append-only (1 ligne par heartbeat = ~6/h en RTH) -> taille negligeable.
# Skip silencieux si filesystem indisponible (best-effort, ne casse pas BN V5).
def _write_bn_v5_marker(uptime_min: float, n_bars: int, n_setups: int,
                        n_trades: int, pnl_usd: float) -> None:
    try:
        import json as _json
        from pathlib import Path as _Path
        root = _Path(__file__).resolve().parent.parent
        marker_dir = root / "LOGS" / "bn_v5"
        marker_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        marker_path = marker_dir / f"bn_v5_v1_{date_str}.jsonl"
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "code": "BN_V5_HEARTBEAT_MARKER",
            "uptime_min": round(uptime_min, 1),
            "n_bars": n_bars,
            "n_setups": n_setups,
            "n_trades": n_trades,
            "pnl_usd": round(pnl_usd, 2),
        }
        with open(marker_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(payload) + "\n")
    except Exception:
        # best-effort, ne jamais casser BN V5 sur erreur logging marker
        pass


# ════════════════════════════════════════════════════════════════════════════
# CLASS PAPER TRADER BN V5
# ════════════════════════════════════════════════════════════════════════════

class BNV5PaperTrader:
    """Paper trader BN V5 minimal.

    Lifecycle :
      __init__ -> boot_ready -> poll_cycle (~30s loop) -> shutdown
    """

    def __init__(
        self,
        dtc: Optional[Any] = None,
        symbols: Optional[List[str]] = None,
        dry_run: bool = True,
        trade_account: str = "Sim2",
        params: Optional[BNV5Params] = None,
    ) -> None:
        self.symbols = symbols or ["NQ", "ES"]
        self.dry_run = dry_run or (dtc is None)
        self.trade_account = trade_account
        self.dtc = dtc
        self.params = params or BNV5Params()

        _emit("BN_V5_BOOT_START",
              sym=",".join(self.symbols),
              dry_run=int(self.dry_run),
              trade_account=self.trade_account)

        # Engine par sym
        self._engine_by_sym: Dict[str, BNV5Engine] = {
            sym: BNV5Engine(symbol=sym, params=self.params, log_fn=_emit)
            for sym in self.symbols
        }

        # Reader JSONL live_enriched
        self._reader_by_sym: Dict[str, LiveEnrichedReader] = {
            sym: LiveEnrichedReader(symbol=sym, window_bars=200, warn_stale_sec=180)
            for sym in self.symbols
        }

        # Positions (1 max par sym sur Sim2)
        self._position: Dict[str, Optional[Dict[str, Any]]] = {sym: None for sym in self.symbols}
        self._trail: Dict[str, Optional[TrailingStateV5]] = {sym: None for sym in self.symbols}
        self._pos_lock = threading.Lock()

        # CID index pour _handle_dtc_fill
        self._cid_index: Dict[str, Dict[str, Any]] = {}

        # Stats lifecycle
        self._n_bars_processed: int = 0
        self._n_setups_detected: int = 0
        self._n_trades_executed: int = 0
        self._pnl_session_usd: float = 0.0
        self._boot_ts = datetime.now(timezone.utc)
        self._last_heartbeat: Optional[datetime] = None
        self.HEARTBEAT_INTERVAL_MIN = 10

        # Kill switch
        self._kill_switch_active = False
        self._kill_reason = ""

        # 🆕 FIX #A8 (08/06/2026) - Daily stop Mark Douglas tracking
        self._daily_stop_triggered: bool = False
        self._daily_stop_reason: str = ""
        # 🆕 FIX B8.1 (code-reviewer 08/06) - Rotate day obligatoire pour eviter
        # drift pnl_session_usd qui cumule depuis boot bot (jamais reset).
        self._last_session_date: Optional[str] = None  # YYYY-MM-DD UTC

        # 🆕 FIX BUG #1 (09/06) - Persistance state pour survivre restarts service.
        # Heartbeat save periodique (vs save_state apres chaque modif critique).
        self._last_state_save: Optional[datetime] = None
        # Load state apres TOUS attributs initialises (FAIL-CLOSED si corruption).
        self._load_state()

        # ════════════════════════════════════════════════════════════════════
        # 🆕 10/06 ULTRATHINK BN V5 — Chantier persistance positions.
        # Etend BUG #1 fix 09/06 (session_state) avec positions ouvertes
        # + signal_counter monotone + cooldown meta (pattern Bot 3 v3/v4).
        # ════════════════════════════════════════════════════════════════════
        self._positions_persist = PositionPersistance(
            bot_name="bn_v5", lock=self._pos_lock, emit_fn=_emit,
        )
        self._reconciled: bool = False
        self._halt_reason: Optional[str] = None
        self._halt_details: str = ""
        self._last_poll_skip_halt_emit_ts: Optional[datetime] = None
        self._last_poll_skip_reconcile_emit_ts: Optional[datetime] = None
        # Signal counter monotone per-sym (refactor uuid -> BN_V5_NQ_YYYYMMDD_NNNN)
        self._signal_counter: Dict[str, int] = {sym: 0 for sym in self.symbols}

        try:
            restored = self._positions_persist.restore()
            if restored:
                with self._pos_lock:
                    for sym, pos in restored.items():
                        self._position[sym] = pos
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
                _emit("BN_V5_POSITIONS_RESTORED",
                      n_positions=len(restored),
                      symbols=",".join(restored.keys()))
                _emit("BN_V5_CID_INDEX_REBUILT", n_cids=len(self._cid_index))

            # Restore signal_counter per-sym depuis meta (monotone cross-restart)
            for sym in self.symbols:
                counter_meta = self._positions_persist.get_meta(
                    f"signal_counter_{sym}", 0)
                try:
                    self._signal_counter[sym] = int(counter_meta or 0)
                except (TypeError, ValueError):
                    self._signal_counter[sym] = 0
                if self._signal_counter[sym] > 0:
                    _emit("BN_V5_SIGNAL_COUNTER_RESTORED",
                          sym=sym, counter=self._signal_counter[sym])
        except BotStateLoadError as e:
            _emit("BOT_STATE_LOAD_FAILED",
                  bot="bn_v5", err=str(e)[:200],
                  file=str(self._positions_persist._state_file.state_path))
            raise  # FAIL-CLOSED au __init__

    def _next_signal_id(self, sym: str) -> str:
        """Generate monotone signal_id : BN_V5_{SYM}_{YYYYMMDD}_{NNNN}.

        10/06 ULTRATHINK refactor : uuid.uuid4 -> counter persiste cross-restart.
        """
        self._signal_counter[sym] = self._signal_counter.get(sym, 0) + 1
        try:
            self._positions_persist.set_meta(
                f"signal_counter_{sym}", self._signal_counter[sym])
        except Exception as e:
            _emit("BN_V5_LOOP_ERROR",
                  sym=sym, err=f"signal_counter persist: {type(e).__name__}: {str(e)[:200]}")
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"BN_V5_{sym}_{date_str}_{self._signal_counter[sym]:04d}"

    # ────────────────────────────────────────────────────────────────────────
    # PERSISTANCE STATE (FIX BUG #1 09/06)
    # ────────────────────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        """Restaure etat session depuis disque. FAIL-CLOSED si corruption.

        Anti-pattern silent fallback (cf 19/04 meta-labeler) : si validation
        echoue, RAISE pour forcer Jackson a confirmer reset via env var
        MIA_BN_V5_STATE_RESET=1.

        Cas de NEW_SESSION (init normale vars=0/False) :
          - File absent (premier boot)
          - Date UTC stockee != aujourd'hui (rotation)
          - last_update_ts > _STATE_MAX_AGE_HOURS (= bot reste off plusieurs h)
          - Env MIA_BN_V5_STATE_RESET=1 (Jackson force reset)

        Cas FAIL-CLOSED (raise RuntimeError) :
          - JSON corrompu
          - Schema version mismatch
          - REQUIRED_KEYS manquantes (no .get with default = anti silent fallback)
          - last_update_ts invalide
        """
        # Override Jackson : force reset explicite
        if os.environ.get("MIA_BN_V5_STATE_RESET", "0") == "1":
            _emit("BN_V5_STATE_NEW_SESSION", reason="ENV_OVERRIDE_RESET")
            return

        if not _STATE_FILE.exists():
            _emit("BN_V5_STATE_NEW_SESSION", reason="FILE_ABSENT")
            return

        # Lecture + parse JSON (FAIL-CLOSED si corruption)
        try:
            raw = _STATE_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as e:
            _emit("BN_V5_STATE_LOAD_FAILED",
                  err=f"{type(e).__name__}: {str(e)[:200]}",
                  file=str(_STATE_FILE))
            raise RuntimeError(
                f"BN V5 state file corrompu ({_STATE_FILE}): {e}. "
                "Set MIA_BN_V5_STATE_RESET=1 pour bypass."
            )

        # Validation REQUIRED_KEYS (anti .get() silent fallback)
        if not isinstance(data, dict):
            _emit("BN_V5_STATE_LOAD_FAILED",
                  err=f"State file is not a dict: {type(data).__name__}",
                  file=str(_STATE_FILE))
            raise RuntimeError(f"BN V5 state file format invalide (pas un dict).")
        missing = _STATE_REQUIRED_KEYS - set(data.keys())
        if missing:
            _emit("BN_V5_STATE_LOAD_FAILED",
                  err=f"Keys manquantes: {sorted(missing)}",
                  file=str(_STATE_FILE))
            raise RuntimeError(
                f"BN V5 state file invalide : keys manquantes {sorted(missing)}. "
                "Set MIA_BN_V5_STATE_RESET=1 pour bypass."
            )

        # Schema version check
        if data["schema_version"] != _STATE_SCHEMA_VERSION:
            _emit("BN_V5_STATE_LOAD_FAILED",
                  err=f"Schema {data['schema_version']} != attendu {_STATE_SCHEMA_VERSION}",
                  file=str(_STATE_FILE))
            raise RuntimeError(
                f"BN V5 state file schema mismatch : {data['schema_version']} vs {_STATE_SCHEMA_VERSION}. "
                "Set MIA_BN_V5_STATE_RESET=1 pour bypass."
            )

        # Reject if state too old (>8h = bot off too long, probable nouvelle session)
        try:
            last_ts = datetime.fromisoformat(str(data["last_update_ts"]).replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - last_ts).total_seconds() / 3600
        except (ValueError, TypeError) as e:
            _emit("BN_V5_STATE_LOAD_FAILED",
                  err=f"last_update_ts invalide: {e}",
                  file=str(_STATE_FILE))
            raise RuntimeError(f"BN V5 last_update_ts format invalide : {e}")

        if age_hours > _STATE_MAX_AGE_HOURS:
            _emit("BN_V5_STATE_NEW_SESSION",
                  reason=f"AGE_{age_hours:.1f}h_GT_{_STATE_MAX_AGE_HOURS}h")
            return

        # Date UTC check (session simple, CME day = V5.1 chantier separe)
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if data["session_date_utc"] != today_utc:
            _emit("BN_V5_STATE_NEW_SESSION",
                  reason=f"DATE_{data['session_date_utc']}_to_{today_utc}")
            return

        # Restauration vars (toutes presentes par REQUIRED_KEYS)
        self._n_bars_processed = int(data["n_bars_processed"])
        self._n_setups_detected = int(data["n_setups_detected"])
        self._n_trades_executed = int(data["n_trades_executed"])
        self._pnl_session_usd = float(data["pnl_session_usd"])
        self._daily_stop_triggered = bool(data["daily_stop_triggered"])
        self._daily_stop_reason = str(data["daily_stop_reason"])
        self._last_session_date = str(data["session_date_utc"])

        _emit("BN_V5_STATE_RESTORED",
              session_date_utc=self._last_session_date,
              pnl_session_usd=round(self._pnl_session_usd, 2),
              daily_stop_triggered=self._daily_stop_triggered,
              daily_stop_reason=self._daily_stop_reason,
              n_trades_executed=self._n_trades_executed,
              age_hours=round(age_hours, 2))

    def _save_state(self, trigger: str = "manual") -> None:
        """Persiste etat session sur disque (atomic write thread-safe).

        Snapshot dict construit sous _pos_lock pour eviter race condition
        avec _exit_position (modifie _pnl_session_usd) ou daily_stop trigger
        depuis _poll_sym.

        Write tmp + os.replace = atomic NTFS depuis Python 3.3.
        Best-effort : exception -> emit ALERTE, pas de crash bot.

        Args:
            trigger: contexte d'appel pour traçabilite
                ("trade_close", "daily_stop", "trade_open", "heartbeat", "boot").
        """
        try:
            # Snapshot sous lock (Q1 race condition)
            with self._pos_lock:
                data = {
                    "schema_version": _STATE_SCHEMA_VERSION,
                    "session_date_utc": (
                        self._last_session_date
                        or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    ),
                    "n_bars_processed": self._n_bars_processed,
                    "n_setups_detected": self._n_setups_detected,
                    "n_trades_executed": self._n_trades_executed,
                    "pnl_session_usd": round(self._pnl_session_usd, 2),
                    "daily_stop_triggered": self._daily_stop_triggered,
                    "daily_stop_reason": self._daily_stop_reason,
                    "last_update_ts": datetime.now(timezone.utc).isoformat(),
                }
            # Write HORS lock (I/O lente, pas de partage etat)
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = _STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, _STATE_FILE)
            self._last_state_save = datetime.now(timezone.utc)
            _emit("BN_V5_STATE_SAVED",
                  pnl_session_usd=data["pnl_session_usd"],
                  daily_stop_triggered=data["daily_stop_triggered"],
                  n_trades_executed=data["n_trades_executed"],
                  trigger=trigger)
        except Exception as e:
            _emit("BN_V5_STATE_SAVE_FAILED",
                  err=f"{type(e).__name__}: {str(e)[:200]}",
                  file=str(_STATE_FILE))

    # ────────────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ────────────────────────────────────────────────────────────────────────

    def boot_ready(self) -> None:
        """Reconcile DTC + emit BOOT_READY (ou HALT_BOOT_REQUIRES_HUMAN selon resultat).
        10/06 ULTRATHINK BN V5 — pattern Bot 3 v3 Sprint Phase 1.

        Sequence :
          1. Check flag file STATE/bn_v5/force_flat.flag (consume-and-delete)
          2. Reconcile DTC 5 cas (skip si dry_run ou dtc None)
          3. Pour chaque report : action selon case + force_flat_override
          4. Si pas HALT : self._reconciled = True + emit BOOT_READY classique
          5. Si HALT : emit BN_V5_HALT_BOOT_REQUIRES_HUMAN (CRITIQUE)
        """
        force_flat = False
        force_flat_flag_path = ROOT / "STATE" / "bn_v5" / "force_flat.flag"
        if force_flat_flag_path.exists():
            force_flat = True
            try:
                force_flat_flag_path.unlink()
                _emit("BN_V5_FORCE_FLAT_FLAG_CONSUMED")
            except OSError as e:
                _emit("BN_V5_LOOP_ERROR",
                      err=f"force_flat_flag unlink: {str(e)[:200]}")

        env_force_flat = os.environ.get(
            "MIA_BN_V5_RECONCILE_FORCE_FLAT", "0") == "1"

        # Reconcile DTC (skip si dry_run ou pas de DTC)
        if not self.dry_run and self.dtc is not None:
            try:
                reports = self._positions_persist.reconcile_with_dtc(
                    dtc=self.dtc,
                    trade_account=self.trade_account,
                    symbol_to_contract=SYMBOL_TO_CONTRACT,
                    force_flat_override=force_flat or env_force_flat,
                )
                has_halt = False
                for r in reports:
                    if r.is_critical:
                        has_halt = True
                        self._halt_reason = r.case
                        self._halt_details = r.message
                        _emit("BN_V5_HALT_BOOT_REQUIRES_HUMAN",
                              case=r.case, symbol=r.symbol,
                              message=r.message)
                if not has_halt:
                    self._reconciled = True
            except Exception as e:
                _emit("BN_V5_LOOP_ERROR",
                      err=f"reconcile_with_dtc: {type(e).__name__}: {str(e)[:200]}")
                self._reconciled = True  # fallback : continue boot
        else:
            self._reconciled = True

        for sym in self.symbols:
            _emit("BN_V5_BOOT_READY",
                  sym=sym,
                  dtc_state="DRY_RUN" if self.dry_run else "CONNECTED",
                  reconciled=int(self._reconciled),
                  halt_reason=self._halt_reason or "")

    def shutdown(self, reason: str = "manual") -> None:
        # Flatten positions ouvertes
        for sym in list(self.symbols):
            pos = self._position.get(sym)
            if pos is not None:
                self._cleanup_position(sym, exit_reason=f"shutdown:{reason}")
        _emit("BN_V5_SHUTDOWN",
              sym=",".join(self.symbols),
              n_trades_executed=self._n_trades_executed,
              pnl_session_usd=round(self._pnl_session_usd, 2))

    def _heartbeat(self) -> None:
        now = datetime.now(timezone.utc)
        if (self._last_heartbeat is None
                or (now - self._last_heartbeat) > timedelta(minutes=self.HEARTBEAT_INTERVAL_MIN)):
            uptime_min = (now - self._boot_ts).total_seconds() / 60
            for sym in self.symbols:
                _emit("BN_V5_HEARTBEAT",
                      sym=sym,
                      uptime_min=round(uptime_min, 1),
                      n_bars=self._n_bars_processed,
                      n_setups=self._n_setups_detected,
                      n_trades=self._n_trades_executed,
                      pnl_usd=round(self._pnl_session_usd, 2))
            # FIX R3 03/06 : ecrit aussi fichier marker dedie LOGS/bn_v5/bn_v5_v1_*.jsonl
            # pour watchdog `Bot2_BN_V5` (cf BOT/mia_watchdog.py). Sinon BN V5 plante
            # silencieusement sans detection si Bot 1/3 OK (angle mort identifie
            # code-reviewer audit 03/06 post-fix Bot2_BN_V4 obsolete).
            _write_bn_v5_marker(uptime_min, self._n_bars_processed, self._n_setups_detected,
                                self._n_trades_executed, self._pnl_session_usd)
            self._last_heartbeat = now

        # FIX BUG #1 09/06 - Save state periodique safety net (vs heartbeat 10 min trop long).
        # Couvre cas crash entre TRADE_OPEN/CLOSE (pnl session deja modifie mais autres
        # vars compteurs pas encore sauvees). Decoupe du heartbeat principal pour 2 min.
        if (self._last_state_save is None
                or (now - self._last_state_save) > timedelta(minutes=_STATE_HEARTBEAT_SAVE_MIN)):
            self._save_state(trigger="heartbeat")

    # ────────────────────────────────────────────────────────────────────────
    # POLL CYCLE (appele depuis paper_v2 main loop)
    # ────────────────────────────────────────────────────────────────────────

    def poll_cycle(self) -> None:
        self._heartbeat()
        if self._kill_switch_active:
            return
        # 10/06 ULTRATHINK : halt_reason check (skip cycle si HALT post-reconcile)
        if self._halt_reason is not None:
            now = datetime.now(timezone.utc)
            if (self._last_poll_skip_halt_emit_ts is None or
                (now - self._last_poll_skip_halt_emit_ts).total_seconds() > 60):
                _emit("BN_V5_POLL_SKIP_HALT",
                      halt_reason=self._halt_reason,
                      halt_details=self._halt_details[:200])
                self._last_poll_skip_halt_emit_ts = now
            return
        if not self._reconciled:
            now = datetime.now(timezone.utc)
            if (self._last_poll_skip_reconcile_emit_ts is None or
                (now - self._last_poll_skip_reconcile_emit_ts).total_seconds() > 60):
                _emit("BN_V5_POLL_SKIP_RECONCILE")
                self._last_poll_skip_reconcile_emit_ts = now
            return
        for sym in self.symbols:
            try:
                self._poll_sym(sym)
            except Exception as e:
                _emit("BN_V5_LOOP_ERROR", sym=sym,
                      err=f"{type(e).__name__}: {str(e)[:300]}")

    def _poll_sym(self, sym: str) -> None:
        reader = self._reader_by_sym[sym]
        engine = self._engine_by_sym[sym]

        # 1. Lecture rolling window
        df = reader.load_rolling_window()
        if df is None or len(df) < (self.params.range_lookback_bars + self.params.pivot_window * 2 + 5):
            return  # warmup
        self._n_bars_processed += 1

        # 2. Check staleness
        try:
            last_ts = pd.Timestamp(df["ts_event"].iloc[-1])
            if last_ts.tzinfo is None:
                last_ts = last_ts.tz_localize("UTC")
            age_sec = (datetime.now(timezone.utc) - last_ts.to_pydatetime()).total_seconds()
            if age_sec > 180:
                _emit("BN_V5_BAR_STALE", sym=sym, age_sec=round(age_sec, 1), threshold_sec=180)
                return
        except Exception:
            pass

        # 3. Si position active : update trailing + check exits
        pos = self._position.get(sym)
        if pos is not None:
            self._update_position(sym, df)
            return  # 1 position max simultanee, pas de nouveau setup tant que ouverte

        # 🆕 FIX B8.1 (code-reviewer 08/06) - Rotate day OBLIGATOIRE
        # Sans ca, _pnl_session_usd cumule depuis boot bot (jamais reset).
        # Apres N sessions, freeze derive a tort. Compare date courante vs derniere.
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._last_session_date is None:
            self._last_session_date = today_utc
        elif self._last_session_date != today_utc:
            old_pnl = self._pnl_session_usd
            self._pnl_session_usd = 0.0
            self._daily_stop_triggered = False
            self._daily_stop_reason = ""
            # FIX BUG #1 09/06 : reset compteurs session pour persistance coherente
            self._n_trades_executed = 0
            self._n_setups_detected = 0
            self._n_bars_processed = 0
            _emit("BN_V5_SESSION_ROTATE",
                  sym=sym,
                  prev_date=self._last_session_date,
                  new_date=today_utc,
                  prev_pnl_usd=round(old_pnl, 2))
            self._last_session_date = today_utc
            # FIX BUG #1 : delete state file ancien + save nouveau (CME day rotate)
            try:
                if _STATE_FILE.exists():
                    _STATE_FILE.unlink()
            except OSError as e:
                _emit("BN_V5_STATE_SAVE_FAILED",
                      err=f"unlink old state: {e}", file=str(_STATE_FILE))
            self._save_state(trigger="session_rotate")

        # 🆕 FIX #A8 (08/06/2026) - Daily stop Mark Douglas check AVANT setup detection
        # Source : memoire feedback_douglas_consistency_principles.md
        # Pre-check : si daily stop deja triggered, on ne detecte meme pas de setup.
        if self.params.daily_stop_enabled and self._daily_stop_triggered:
            return
        if self.params.daily_stop_enabled:
            if self._pnl_session_usd >= self.params.daily_stop_win_usd:
                self._daily_stop_triggered = True
                self._daily_stop_reason = f"WIN_TARGET_{self._pnl_session_usd:.0f}usd"
                _emit("BN_V5_DAILY_STOP_TRIGGERED",
                      sym=sym, reason="WIN_TARGET",
                      pnl_session_usd=round(self._pnl_session_usd, 2),
                      threshold_usd=self.params.daily_stop_win_usd)
                self._save_state(trigger="daily_stop_win")  # FIX BUG #1 09/06
                return
            if self._pnl_session_usd <= -self.params.daily_stop_loss_usd:
                self._daily_stop_triggered = True
                self._daily_stop_reason = f"LOSS_LIMIT_{self._pnl_session_usd:.0f}usd"
                _emit("BN_V5_DAILY_STOP_TRIGGERED",
                      sym=sym, reason="LOSS_LIMIT",
                      pnl_session_usd=round(self._pnl_session_usd, 2),
                      threshold_usd=-self.params.daily_stop_loss_usd)
                self._save_state(trigger="daily_stop_loss")  # FIX BUG #1 09/06
                return

        # 4. Detection setup BN V5
        current_idx = len(df) - 1
        setup = engine.check_zone(df, current_idx)
        if setup is None:
            return
        self._n_setups_detected += 1

        # ════════════════════════════════════════════════════════════════════
        # 10/06 ULTRATHINK Phase 5 — COUCHES PROTECTION (parite Bot 3 v3)
        # FIX #54 ATR veto + FIX #55 SL Min ATR-aware + FIX #56 SL HARDCAP $50
        # ════════════════════════════════════════════════════════════════════
        try:
            last_bar = df.iloc[-1]
            _bar_atr = float(last_bar.get("atr", 0) or 0)
            if _bar_atr != _bar_atr:  # NaN
                _bar_atr = 0.0
        except (TypeError, ValueError, KeyError, IndexError):
            _bar_atr = 0.0

        # FIX #54 — ATR veto (BN V5 max ATR limits, env override)
        if _bar_atr > 0:
            if sym == "NQ":
                _max_atr = float(os.environ.get("BN_V5_MAX_ATR_TICKS_NQ", "600"))
            elif sym == "ES":
                _max_atr = float(os.environ.get("BN_V5_MAX_ATR_TICKS_ES", "150"))
            else:
                _max_atr = 0.0
            if _max_atr > 0 and _bar_atr > _max_atr:
                _emit("BN_V5_VOL_VETO_HIGH_ATR",
                      sym=sym, pattern=setup.pattern, side=setup.side,
                      atr_ticks=int(_bar_atr), limit_ticks=int(_max_atr))
                return

        # FIX #55 — SL Min ATR-aware (elargit SL si trop serre)
        try:
            from CORE.mia_sltp import get_sl_min_atr_aware as _get_sl_min_atr_aware
        except ImportError:
            _get_sl_min_atr_aware = None
        if _get_sl_min_atr_aware is not None and _bar_atr > 0:
            try:
                _tick = TICK_BY_SYMBOL[sym]
                _sl_ticks_orig = abs(setup.entry_price - setup.sl_price) / _tick
                _sl_min_eff = _get_sl_min_atr_aware(sym, _bar_atr)
                if _sl_ticks_orig < _sl_min_eff:
                    _dir_sign = 1 if setup.side == SIDE_LONG else -1
                    _new_sl_price = float(setup.entry_price) - _dir_sign * _sl_min_eff * _tick
                    _emit("BN_V5_SL_MIN_ATR_EXTENDED",
                          sym=sym, side=setup.side, pattern=setup.pattern,
                          sl_orig_ticks=int(_sl_ticks_orig),
                          sl_eff_ticks=int(_sl_min_eff),
                          atr_ticks=int(_bar_atr))
                    setup.sl_price = round(_new_sl_price, 4)
            except Exception as _e_sl_min:
                _emit("BN_V5_LOOP_ERROR",
                      sym=sym, err=f"sl_min_atr_aware: {type(_e_sl_min).__name__}: {str(_e_sl_min)[:200]}")

        # FIX #56 — SL HARDCAP $50 USD VIRTUAL MICRO (anti slip catastrophe)
        try:
            from bot3_config import (
                GUARD_RAILS_BOT3 as _GR_RISK,
                MAX_SL_RISK_USD_BOT3 as _MAX_SL_RISK,
            )
        except ImportError:
            from CORE.bot3_config import (
                GUARD_RAILS_BOT3 as _GR_RISK,
                MAX_SL_RISK_USD_BOT3 as _MAX_SL_RISK,
            )
        try:
            _tick_risk = TICK_BY_SYMBOL[sym]
            _sl_ticks_check = int(round(
                abs(setup.entry_price - setup.sl_price) / _tick_risk))
            _cfg_risk = _GR_RISK.get(sym, {})
            _tick_value_risk = float(_cfg_risk.get("tick_value", 0.50))
            _n_contracts_risk = int(_cfg_risk.get("n_contracts", 3))
            _sl_risk_usd = _sl_ticks_check * _tick_value_risk * _n_contracts_risk
            if _sl_risk_usd > _MAX_SL_RISK:
                _emit("BN_V5_SL_RISK_VETO",
                      sym=sym, pattern=setup.pattern, side=setup.side,
                      sl_ticks=_sl_ticks_check,
                      tick_value=_tick_value_risk,
                      n_contracts=_n_contracts_risk,
                      sl_risk_usd=round(_sl_risk_usd, 2),
                      max_allowed_usd=_MAX_SL_RISK,
                      reason="SL risk USD exceeds hardcap")
                return
        except Exception as _e_risk:
            _emit("BN_V5_LOOP_ERROR",
                  err=f"sl_risk_veto: {type(_e_risk).__name__}: {str(_e_risk)[:200]}")

        # ════════════════════════════════════════════════════════════════════
        # 10/06 ULTRATHINK Phase G — FILTRE REGIME (anti V LONG en bear market)
        # Audit market-analyst : V LONG PF 0.90 sur 7j car 50% contre trend daily.
        # Bloque entry si pattern contre-tendance regime_favor live_enriched.
        # Override : env BN_V5_REGIME_VETO_DISABLED=1
        # ════════════════════════════════════════════════════════════════════
        if os.environ.get("BN_V5_REGIME_VETO_DISABLED", "0") != "1":
            try:
                _regime_favor = str(last_bar.get("regime_favor", "")).upper()
                _trend_score = float(last_bar.get("ctx_trend_day_score", 0) or 0)
                # Detection contre-tendance
                # LONG patterns (V_LONG, W_LONG) : veto si regime SHORT ou trend < -0.3
                # SHORT patterns (M_SHORT, INV_V_SHORT) : veto si regime LONG ou trend > +0.3
                _veto = False
                _veto_reason = ""
                if setup.side == SIDE_LONG:
                    if _regime_favor == "SHORT":
                        _veto = True
                        _veto_reason = f"LONG pattern vs regime_favor=SHORT"
                    elif _trend_score < -0.3:
                        _veto = True
                        _veto_reason = f"LONG pattern vs trend_score={_trend_score:.2f}"
                elif setup.side == SIDE_SHORT:
                    if _regime_favor == "LONG":
                        _veto = True
                        _veto_reason = f"SHORT pattern vs regime_favor=LONG"
                    elif _trend_score > 0.3:
                        _veto = True
                        _veto_reason = f"SHORT pattern vs trend_score={_trend_score:.2f}"
                if _veto:
                    _emit("BN_V5_REGIME_VETO",
                          sym=sym, pattern=setup.pattern, side=setup.side,
                          regime_favor=_regime_favor,
                          trend_score=round(_trend_score, 3),
                          reason=_veto_reason)
                    return
            except Exception as _e_reg:
                _emit("BN_V5_LOOP_ERROR",
                      err=f"regime_veto: {type(_e_reg).__name__}: {str(_e_reg)[:200]}")

        # ════════════════════════════════════════════════════════════════════
        # 10/06 ULTRATHINK Phase H — DAILY STOP PREVENTIF (vs reactif)
        # Audit market-analyst : daily_stop existant declenche APRES trade perdant.
        # Si cumul=-150 et trade risk=-100, daily_stop -200 dois VETO le trade
        # AVANT (pas apres -250 deja realise).
        # Calcul : si (cumul_pnl - max_perte_potentielle) < -daily_stop_loss → VETO
        # ════════════════════════════════════════════════════════════════════
        if self.params.daily_stop_enabled:
            try:
                _perte_max_potentielle = float(_sl_risk_usd)  # de FIX #56 ci-dessus
                _cumul_apres_perte_max = self._pnl_session_usd - _perte_max_potentielle
                _limite_loss = -float(self.params.daily_stop_loss_usd)
                if _cumul_apres_perte_max < _limite_loss:
                    _emit("BN_V5_DAILY_STOP_PREVENTIF_VETO",
                          sym=sym, pattern=setup.pattern, side=setup.side,
                          pnl_session_usd=round(self._pnl_session_usd, 2),
                          perte_max_potentielle_usd=round(_perte_max_potentielle, 2),
                          cumul_apres_perte=round(_cumul_apres_perte_max, 2),
                          limite_loss_usd=round(_limite_loss, 2),
                          reason="trade rejette : perte max trade ferait depasser daily_stop_loss")
                    return
            except Exception as _e_prev:
                _emit("BN_V5_LOOP_ERROR",
                      err=f"daily_stop_preventif: {type(_e_prev).__name__}: {str(_e_prev)[:200]}")
        # ════════════════════════════════════════════════════════════════════

        # 5. Place bracket DTC (ou dry_run log only)
        if self.dry_run:
            qty = 3  # 10/06 SOIR DATA_COLLECTION : 3 micros Cross Chart Sierra (override 03/06 E-mini)
            _emit("BN_V5_TRADE_OPEN",
                  sym=sym, pattern=setup.pattern, side=setup.side,
                  entry_price=setup.entry_price, sl_price=setup.sl_price,
                  risk_ticks=abs(setup.entry_price - setup.sl_price) / TICK_BY_SYMBOL[sym],
                  qty=qty)
            # Simule position pour observer trailing
            self._position[sym] = self._make_pos_dict(sym, setup, parent_cid=None, tp_cid=None, sl_cid=None)
            self._trail[sym] = init_trailing(setup)
            self._n_trades_executed += 1
            self._save_state(trigger="trade_open_dry")  # FIX BUG #1 09/06
            # 10/06 ULTRATHINK : save_position pour cross-restart safety
            try:
                self._positions_persist.save_position(sym, self._position[sym])
            except Exception as e:
                _emit("BN_V5_LOOP_ERROR",
                      sym=sym, err=f"save_position dry_run: {type(e).__name__}: {str(e)[:200]}")
            return

        self._place_bracket_dtc(sym, setup)

    # ────────────────────────────────────────────────────────────────────────
    # DTC BRACKET
    # ────────────────────────────────────────────────────────────────────────

    def _make_pos_dict(self, sym: str, setup: Setup, parent_cid: Optional[str],
                       tp_cid: Optional[str], sl_cid: Optional[str]) -> Dict[str, Any]:
        # 10/06 ULTRATHINK : signal_id monotone (was str(uuid.uuid4())[:12])
        return {
            "signal_id": self._next_signal_id(sym),
            "sym": sym,
            "pattern": setup.pattern,
            "side": setup.side,
            "entry_price": setup.entry_price,
            "sl_initial": setup.sl_price,
            "sl_current": setup.sl_price,
            "pivot_price": setup.pivot_price,
            "neckline": setup.neckline,
            "parent_cid": parent_cid,
            "tp_cid": tp_cid,
            "sl_cid": sl_cid,
            "qty": 3,  # 10/06 FIX sizing : aligned avec _place_bracket_dtc qty=3 (DATA_COLLECTION)
            "entry_idx": setup.entry_idx,
            "entry_ts": datetime.now(timezone.utc).isoformat(),
            "ts_event_open": None,
            "bars_held": 0,
        }

    def _place_bracket_dtc(self, sym: str, setup: Setup) -> None:
        """Place bracket OCO via DTC.

        Pattern Bot 3 v3 valide :
          - 1 parent MARKET
          - 1 TP LIMIT loin (cap, vraie sortie = trailing)
          - 1 SL STOP au pivot direct
          - OCO manuel cote bot (cancel oppose au fill)
        """
        contract = SYMBOL_TO_CONTRACT.get(sym, f"{sym}M26-CME")
        side_dtc = DTC_BUY if setup.side == SIDE_LONG else DTC_SELL
        tick = TICK_BY_SYMBOL[sym]
        risk_ticks = abs(setup.entry_price - setup.sl_price) / tick

        # TP cap distant (=trailing fera le vrai exit)
        TP_CAP_TICKS = 200
        if setup.side == SIDE_LONG:
            tp_price = setup.entry_price + TP_CAP_TICKS * tick
        else:
            tp_price = setup.entry_price - TP_CAP_TICKS * tick

        qty = 3  # 10/06 SOIR DATA_COLLECTION : 3 micros Cross Chart Sierra (override 03/06 E-mini)
        try:
            parent_cid, tp_cid, sl_cid = self.dtc.send_market_order(
                symbol=contract,
                side=side_dtc,
                quantity=qty,
                sl_price=setup.sl_price,
                tp_price=tp_price,
                trade_account=self.trade_account,
                signal_ref_price=setup.entry_price,
                sl_ticks=int(round(risk_ticks)),
                tp_ticks=TP_CAP_TICKS,
                tick_size=tick,
                auto_reprice_threshold_ticks=5,
            )
        except Exception as e:
            _emit("BN_V5_LOOP_ERROR", sym=sym,
                  err=f"send_market_order: {type(e).__name__}: {str(e)[:200]}")
            return

        if not parent_cid:
            _emit("BN_V5_LOOP_ERROR", sym=sym,
                  err="parent_cid_empty (DTC down or fill timeout)")
            return

        # Register CIDs for fill handling
        pos = self._make_pos_dict(sym, setup, parent_cid, tp_cid, sl_cid)
        with self._pos_lock:
            self._cid_index[parent_cid] = {"sym": sym, "kind": "parent", "signal_id": pos["signal_id"]}
            self._cid_index[tp_cid] = {"sym": sym, "kind": "tp", "signal_id": pos["signal_id"]}
            self._cid_index[sl_cid] = {"sym": sym, "kind": "sl", "signal_id": pos["signal_id"]}
            self._position[sym] = pos
            self._trail[sym] = init_trailing(setup)
            self._n_trades_executed += 1

        _emit("BN_V5_BRACKET_PLACED",
              sym=sym,
              parent_cid=parent_cid[:20],
              tp_cid=tp_cid[:20],
              sl_cid=sl_cid[:20])
        self._save_state(trigger="trade_open_dtc")  # FIX BUG #1 09/06
        # 10/06 ULTRATHINK : save_position pour cross-restart safety
        try:
            self._positions_persist.save_position(sym, pos)
        except Exception as e:
            _emit("BN_V5_LOOP_ERROR",
                  sym=sym, err=f"save_position dtc: {type(e).__name__}: {str(e)[:200]}")
        _emit("BN_V5_TRADE_OPEN",
              sym=sym, pattern=setup.pattern, side=setup.side,
              entry_price=setup.entry_price, sl_price=setup.sl_price,
              risk_ticks=round(risk_ticks, 1), qty=qty)

    # ────────────────────────────────────────────────────────────────────────
    # TRAILING + EXIT
    # ────────────────────────────────────────────────────────────────────────

    def _update_position(self, sym: str, df: pd.DataFrame) -> None:
        pos = self._position.get(sym)
        trail = self._trail.get(sym)
        if pos is None or trail is None:
            return

        # Bar courante
        last_bar = df.iloc[-1].to_dict()
        pos["bars_held"] += 1

        # Update trailing
        prev_pullback = trail.last_confirmed_pullback
        new_sl = update_trailing(trail, last_bar, trail_pullback_bars=self.params.trail_pullback_bars)

        # Emit pullback confirme (nouveau pullback different du precedent)
        if trail.last_confirmed_pullback is not None and trail.last_confirmed_pullback != prev_pullback:
            _emit("BN_V5_TRAIL_PULLBACK_CONFIRMED",
                  sym=sym, side=pos["side"],
                  pullback_extreme=round(trail.last_confirmed_pullback, 2),
                  running_extreme=round(trail.running_high if pos["side"] == SIDE_LONG else trail.running_low, 2),
                  bars_since=trail.bars_since_new_extreme)

        if new_sl is not None and new_sl != pos["sl_current"]:
            old_sl = pos["sl_current"]
            pos["sl_current"] = new_sl
            # 🆕 FIX B1.2 (code-reviewer 08/06) - distinguer BE_ARMED vs trail Dow
            # pour audit post-trade. trail.breakeven_armed est True quand le SL
            # vient juste d'etre move a entry (Fix A1).
            if trail.breakeven_armed and new_sl == trail.entry_price:
                tick = TICK_BY_SYMBOL[sym]
                _emit("BN_V5_TRAIL_BE_ARMED",
                      sym=sym, side=pos["side"],
                      entry_price=round(trail.entry_price, 2),
                      sl_initial=round(trail.sl_initial, 2),
                      risk_ticks=round(abs(trail.entry_price - trail.sl_initial) / tick, 1),
                      mfe_ticks=round(trail.mfe_ticks / tick, 1),
                      bars_held=pos["bars_held"])
            _emit("BN_V5_TRAIL_SL_UPDATE",
                  sym=sym, side=pos["side"],
                  old_sl=round(old_sl, 2), new_sl=round(new_sl, 2),
                  pullback_extreme=round(trail.last_confirmed_pullback, 2) if trail.last_confirmed_pullback else None)

        # Periodic position update emit (toutes 10 bars)
        if pos["bars_held"] % 10 == 0:
            _emit("BN_V5_POSITION_UPDATE",
                  sym=sym, side=pos["side"],
                  bars_held=pos["bars_held"],
                  sl_current=round(pos["sl_current"], 2),
                  mfe_ticks=round(trail.mfe_ticks / TICK_BY_SYMBOL[sym], 1),
                  mae_ticks=round(trail.mae_ticks / TICK_BY_SYMBOL[sym], 1),
                  close=round(float(last_bar.get("close", 0)), 2))

        # 10/06 ULTRATHINK Phase E — TRAILING DTC REEL (cancel+replace SL)
        # Resolution TODO V5.1 : sans cancel+replace, le trailing etait
        # COSMETIQUE = tous les exits = SL initial fixe OU TIMEOUT 90 bars.
        # L'edge backtest (PF 1.58 ES) reposait sur trailing reel.
        # Pattern Bot 3 v3 ladder + post Price1 fix 10/06.
        if (new_sl is not None and new_sl != pos["sl_current"]
                and not self.dry_run and self.dtc is not None
                and pos.get("sl_cid")):
            try:
                self._modify_sl_via_dtc_trail(sym, pos, new_sl)
            except Exception as e_modify:
                _emit("BN_V5_TRAIL_DTC_MODIFY_FAIL",
                      sym=sym, err=f"{type(e_modify).__name__}: {str(e_modify)[:200]}")

        # Check timeout
        # FIX #A4 (08/06/2026) - audit BN V5 T2 = 310 bars sans force exit.
        # `is_timeout(trail, len(df)-1, ...)` compare entry_idx (capture au moment
        # de detection setup) avec current_idx du DataFrame rolling. Si df reste
        # rolling small (ex: window 60-480 bars), entry_idx peut etre obsolete et
        # diff < timeout_bars meme apres 310 bars reels. BUG.
        # Fix : utiliser `pos["bars_held"]` qui est incremente a chaque cycle =
        # vraie duree position en bars.
        # Check timeout + SL hit (memoire) inline (pre-refactor 10/06)
        if pos["bars_held"] >= self.params.timeout_bars:
            self._exit_position(sym, exit_price=float(last_bar.get("close", pos["entry_price"])),
                                cause="TIMEOUT")
            return
        if is_sl_hit(trail, last_bar):
            if self.dry_run:
                self._exit_position(sym, exit_price=trail.sl_current, cause="SL")

    def _modify_sl_via_dtc_trail(self, sym: str, pos: Dict[str, Any],
                                  new_sl_price: float) -> None:
        """10/06 ULTRATHINK Phase E — Cancel ancien SL + send nouveau (avec Price1).

        Pattern Bot 3 v3 ladder + Bot 4 trailing. Post Price1 fix 10/06.

        Sequence :
          1. Cancel old SL via dtc.cancel_order(sl_cid, trade_account)
          2. Generate new sl_cid (uuid)
          3. Pre-register trade_account + register_oco_pair (H6 anti-orphan)
          4. Send new STOP Type 208 OrderType=3 avec Price1+Price2=0+StopPrice
          5. Update pos["sl_cid"] + _cid_index
          6. Persist position update
        """
        STOP_DTC = 3
        old_sl_cid = pos.get("sl_cid")
        if not old_sl_cid:
            return
        contract = SYMBOL_TO_CONTRACT.get(sym, f"{sym}M26-CME")

        # Step 1 : Cancel old SL
        try:
            ok_cancel = self.dtc.cancel_order(
                old_sl_cid, trade_account=self.trade_account)
            if not ok_cancel:
                _emit("BN_V5_TRAIL_DTC_CANCEL_FAIL",
                      sym=sym, old_sl_cid=old_sl_cid[:20])
                return
        except Exception as e_cancel:
            _emit("BN_V5_TRAIL_DTC_CANCEL_FAIL",
                  sym=sym, old_sl_cid=old_sl_cid[:20],
                  err=f"{type(e_cancel).__name__}: {str(e_cancel)[:200]}")
            return

        # Step 2 : New sl_cid
        new_sl_cid = f"MIA_SL_BNV5_{uuid.uuid4().hex[:8]}"

        # Step 3 : Pre-register trade_account + OCO pair (H6 anti-orphan)
        try:
            if hasattr(self.dtc, "_order_trade_accounts"):
                self.dtc._order_trade_accounts[new_sl_cid] = self.trade_account
            tp_cid = pos.get("tp_cid")
            if tp_cid and hasattr(self.dtc, "register_oco_pair"):
                self.dtc.register_oco_pair(tp_cid, new_sl_cid)
        except Exception:
            pass  # best-effort pre-register (non bloquant)

        # Step 4 : Send new STOP avec Price1 (FIX 10/06 - 5 sites)
        side_dtc = DTC_SELL if pos["side"] == SIDE_LONG else DTC_BUY
        qty = int(pos.get("qty", 3))
        try:
            self.dtc._send({
                "Type": 208,
                "Symbol": contract,
                "ClientOrderID": new_sl_cid,
                "OrderType": STOP_DTC,
                "BuySell": side_dtc,
                "Quantity": qty,
                "Price1": float(new_sl_price),    # SPEC : trigger price STOP
                "Price2": 0.0,                     # default explicite (non STOP_LIMIT)
                "StopPrice": float(new_sl_price), # defensif compat V1
                "TimeInForce": 0,
                "TradeAccount": self.trade_account,
                "IsAutomatedOrder": 1,
                "OpenCloseTrade": 2,
            })
        except Exception as e_send:
            _emit("BN_V5_TRAIL_DTC_SEND_FAIL",
                  sym=sym, new_sl_cid=new_sl_cid[:20],
                  err=f"{type(e_send).__name__}: {str(e_send)[:200]}")
            return

        # Step 5 : Update pos + cid_index (sous lock)
        with self._pos_lock:
            if old_sl_cid in self._cid_index:
                del self._cid_index[old_sl_cid]
            pos["sl_cid"] = new_sl_cid
            self._cid_index[new_sl_cid] = {
                "sym": sym, "kind": "sl", "signal_id": pos["signal_id"],
            }

        # Step 6 : Persist position update (sl_cid change)
        try:
            self._positions_persist.save_position(sym, pos)
        except Exception as e_persist:
            _emit("BN_V5_LOOP_ERROR",
                  sym=sym, err=f"save_position trail: {type(e_persist).__name__}: {str(e_persist)[:200]}")

        _emit("BN_V5_TRAIL_DTC_MODIFY_OK",
              sym=sym, old_sl_cid=old_sl_cid[:20],
              new_sl_cid=new_sl_cid[:20],
              new_sl_price=round(new_sl_price, 4))

    def _exit_position(self, sym: str, exit_price: float, cause: str) -> None:
        pos = self._position.get(sym)
        if pos is None:
            return
        # Calcul PnL
        tick = TICK_BY_SYMBOL[sym]
        # 10/06 SOIR DATA_COLLECTION : tick_value MICROS via GUARD_RAILS_BOT3
        # (BN V5 qty=3 micros Cross Chart Sierra, pas qty=1 E-mini).
        # GUARD_RAILS_BOT3 NQ tick_value=0.50 / ES tick_value=1.25 / MGC tick_value=1.00.
        try:
            from bot3_config import GUARD_RAILS_BOT3 as _GR
        except ImportError:
            from CORE.bot3_config import GUARD_RAILS_BOT3 as _GR
        _tv_override = _GR.get(sym, {}).get("tick_value")
        tick_val = float(_tv_override) if (_tv_override is not None and _tv_override > 0) else TICK_VAL_USD_BY_SYMBOL[sym]
        # qty multiplie : BN V5 trade 3 micros
        n_ctr = int(pos.get("qty", 1))
        if pos["side"] == SIDE_LONG:
            d = exit_price - pos["entry_price"]
        else:
            d = pos["entry_price"] - exit_price
        pnl_ticks = d / tick
        pnl_usd = pnl_ticks * tick_val * n_ctr
        self._pnl_session_usd += pnl_usd
        # FIX BUG #1 09/06 - Save state IMMEDIATEMENT apres update pnl_session.
        # Sinon : crash entre pnl update et close emit = perte data session = re-trade post-stop.
        self._save_state(trigger="trade_close")

        # Emit + cleanup
        if cause == "SL":
            _emit("BN_V5_TRADE_CLOSE_SL",
                  sym=sym, side=pos["side"], exit_price=exit_price,
                  pnl_usd=round(pnl_usd, 2),
                  duration_bars=pos["bars_held"], pattern=pos["pattern"])
        else:
            _emit("BN_V5_TRADE_CLOSE_TIMEOUT",
                  sym=sym, side=pos["side"], exit_price=exit_price,
                  pnl_usd=round(pnl_usd, 2),
                  duration_bars=pos["bars_held"], pattern=pos["pattern"])

        # Cleanup CIDs + state
        self._cleanup_position(sym, exit_reason=cause)

    def _cleanup_position(self, sym: str, exit_reason: str) -> None:
        """Cleanup position : cancel TP+SL DTC orders + reset state."""
        pos = self._position.get(sym)
        if pos is None:
            return

        # Cancel TP + SL DTC (anti-orphan basique)
        if not self.dry_run and self.dtc is not None:
            for cid_kind in ("tp_cid", "sl_cid"):
                cid = pos.get(cid_kind)
                if cid:
                    try:
                        self.dtc.cancel_order(cid, trade_account=self.trade_account)
                    except Exception as e:
                        _emit("BN_V5_DTC_CANCEL_FAIL", sym=sym,
                              cid=cid[:20], kind=cid_kind,
                              err=f"{type(e).__name__}: {str(e)[:100]}")

        # Cleanup index
        with self._pos_lock:
            for cid_kind in ("parent_cid", "tp_cid", "sl_cid"):
                cid = pos.get(cid_kind)
                if cid and cid in self._cid_index:
                    del self._cid_index[cid]
            self._position[sym] = None
            self._trail[sym] = None

        # 10/06 ULTRATHINK : remove_position persistance + cooldown meta
        try:
            self._positions_persist.remove_position(sym)
            self._positions_persist.set_meta(
                f"last_trade_close_ts_{sym}",
                datetime.now(timezone.utc).isoformat())
        except Exception as e:
            _emit("BN_V5_LOOP_ERROR",
                  sym=sym, err=f"remove_position: {type(e).__name__}: {str(e)[:200]}")

    def _handle_dtc_fill_bn_v5(self, msg: dict, cid: str) -> bool:
        """Handler ORDER_UPDATE Type 301 status=7 (Filled).

        Appele depuis databento_paper_trader_v2._recv_dtc_msg.
        Returns True si CID matche un ordre BN V5 (consume), False sinon.
        """
        entry = self._cid_index.get(cid)
        if entry is None:
            return False
        sym = entry["sym"]
        kind = entry["kind"]
        pos = self._position.get(sym)
        if pos is None:
            return True  # consume mais position deja close

        fill_price = float(msg.get("AverageFillPrice") or msg.get("LastFillPrice") or 0)
        if fill_price <= 0:
            return True

        # Emit fill received pour traçabilité
        _emit("BN_V5_DTC_FILL_RECEIVED",
              sym=sym, cid=cid[:20], kind=kind,
              fill_price=fill_price, signal_id=pos.get("signal_id"))

        if kind == "tp":
            self._exit_position(sym, fill_price, cause="TP_CAP")
        elif kind == "sl":
            self._exit_position(sym, fill_price, cause="SL")
        return True

    def request_kill_switch(self, reason: str) -> None:
        self._kill_switch_active = True
        self._kill_reason = reason
        _emit("BN_V5_SHUTDOWN", sym=",".join(self.symbols),
              n_trades_executed=self._n_trades_executed,
              pnl_session_usd=round(self._pnl_session_usd, 2))


__all__ = ["BNV5PaperTrader", "BNV5Params"]
