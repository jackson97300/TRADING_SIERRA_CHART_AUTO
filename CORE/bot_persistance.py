"""bot_persistance.py — Helper centralise persistance etat bots de trading.

Pattern extrait du fix BN V5 (09/06 BUG #1) et generalise pour les 4 bots
paper trading : Bot 3 v3 NQ Wyckoff (priorite Jackson 09/06 soir), Bot 3 v4
data-driven, BN V5 patterns, Bot 1 PAPER Sierra.

Sprint stabilite Bot 3 v3 — Phase 1 (Jackson 09/06 soir).

Decision design (review code-reviewer + Plan agent 09/06) :
  - Helper centralise (DRY, BN V5 pattern eprouve 2 restarts empiriques)
  - 3 classes : BotStateFile (IO atomic) + PositionPersistance + ReconcileReport
  - SignalIdCounter reste cote logging_v2 (extension separee, hors scope etape 1.1)
  - Lock externe injecte (eviter double lock, aligne BN V5 self._pos_lock)
  - FAIL-CLOSED si corruption (anti-pattern silent fallback 19/04 meta-labeler)
  - Schema major.minor : major mismatch = RAISE, minor mismatch = WARN+accept
  - Reconciliation DTC en 5 cas explicites (a/b/c/d/e)
  - Cas c (Python flat + Broker pos) et e (divergence) = HALT BOOT par defaut
    Override env var MIA_{BOT_UPPER}_RECONCILE_FORCE_FLAT=1 (Jackson explicite)
  - Cas d (Python ghost) = purge silent + emit ALERTE + event TRADE_CLOSE_EXTERNAL
    (audit P&L journal)

Architecture cible (etape 2+) :
  bot.py
    self._positions_persist = PositionPersistance(
        bot_name="bot3_v3", lock=self._pos_lock, emit_fn=_emit)
    restored = self._positions_persist.restore()  # dans __init__ (rapide local)
    # ... boot_ready :
    reports = self._positions_persist.reconcile_with_dtc(
        dtc=self.dtc, trade_account=self.trade_account,
        symbol_to_contract=SYMBOL_TO_CONTRACT,
        force_flat_override=os.environ.get(
            f"MIA_{bot_name.upper()}_RECONCILE_FORCE_FLAT", "0") == "1")
    # halt_boot si reports has CRITIQUE

Codes log_catalog requis (registered avant ce module) :
  BOT_STATE_LOAD_FAILED, BOT_STATE_SAVE_FAILED, BOT_STATE_RESTORED, BOT_STATE_NEW,
  BOT_STATE_SCHEMA_MAJOR_MISMATCH, BOT_STATE_SCHEMA_MINOR_MISMATCH,
  RECONCILE_OK_FLAT, RECONCILE_OK_RESTORED, RECONCILE_UNKNOWN_BROKER_POS,
  RECONCILE_PYTHON_GHOST, RECONCILE_DIVERGENCE, RECONCILE_FORCE_FLAT_OVERRIDE,
  SIGNAL_ID_COUNTER_LOADED, SIGNAL_ID_COLLISION_DETECTED.

Auteur : MIA Trading V2 (sprint stabilite 09/06/2026).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional

__version__ = "0.1.0"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_DIR = ROOT / "DATA" / "PAPER_TRADES"
DEFAULT_MAX_AGE_HOURS = 48.0


# ════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ════════════════════════════════════════════════════════════════════════════

class BotStateLoadError(Exception):
    """Levee si state file corrompu/invalide. FAIL-CLOSED.

    Bypass possible via env var MIA_{BOT_NAME_UPPER}_STATE_RESET=1 (Jackson
    confirme explicitement le reset).
    """


# ════════════════════════════════════════════════════════════════════════════
# CONFIG + REPORT
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StateFileConfig:
    """Configuration immutable pour un BotStateFile.

    Attributes:
        bot_name: identifiant bot (ex "bot3_v3", "bn_v5"). Utilise dans
            le path par defaut + env var override + emit ctx.
        schema_version_major: version majeure du schema. Major mismatch =
            FAIL-CLOSED (RAISE BotStateLoadError).
        schema_version_minor: version mineure. Minor mismatch = WARN + accept
            (le code utilise des defauts explicites pour clees nouvelles).
        state_path: chemin du fichier JSON. Default = DEFAULT_STATE_DIR /
            f"{bot_name}_state.json".
        required_keys: keys obligatoires dans le state (anti-pattern silent
            fallback .get() : on assert presence, sinon RAISE).
        max_age_hours: age max avant NEW_SESSION (ex bot down >48h = vieille
            session, vars vierges).
        session_date_check: callable(session_date_str) -> bool. Default :
            match today UTC. Override pour CME day logic (V5.1 chantier).
    """
    bot_name: str
    required_keys: FrozenSet[str]
    schema_version_major: int = 1
    schema_version_minor: int = 0
    state_path: Optional[Path] = None
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS
    session_date_check: Optional[Callable[[str], bool]] = None

    def __post_init__(self) -> None:
        # Validation
        if not self.bot_name:
            raise ValueError("bot_name cannot be empty")
        if self.schema_version_major < 1:
            raise ValueError("schema_version_major must be >= 1")
        if self.max_age_hours <= 0:
            raise ValueError("max_age_hours must be > 0")
        # state_path default (immutable workaround)
        if self.state_path is None:
            object.__setattr__(
                self, "state_path",
                DEFAULT_STATE_DIR / f"{self.bot_name}_state.json",
            )


@dataclass
class ReconcileReport:
    """Rapport reconciliation Python state vs broker DTC.

    Attributes:
        case: identifiant du cas parmi {OK_FLAT, OK_RESTORED,
            UNKNOWN_BROKER_POS, PYTHON_GHOST, DIVERGENCE, QUERY_FAILED}.
        symbol: symbole concerne (ex "NQ").
        python_state: dict de la position cote Python state file (None si
            flat).
        broker_position: dict avec qty/side cote broker (None si flat ou
            query failed).
        action_taken: action effectuee parmi {none, restored, halt_boot,
            purge, force_flat}.
        severity: niveau de severite parmi {INFO, ALERTE, CRITIQUE}.
        note: message libre pour debug.
    """
    case: str
    symbol: str
    python_state: Optional[Dict[str, Any]] = None
    broker_position: Optional[Dict[str, Any]] = None
    action_taken: str = "none"
    severity: str = "INFO"
    note: str = ""

    @property
    def is_critical(self) -> bool:
        return self.severity == "CRITIQUE"


# ════════════════════════════════════════════════════════════════════════════
# BOT STATE FILE — IO atomic FAIL-CLOSED
# ════════════════════════════════════════════════════════════════════════════

class BotStateFile:
    """Atomic load/save state file avec lock externe injecte.

    Pattern :
      - load() : return state dict si valide, None si NEW (file absent,
        env override, vieux state, session date differente), RAISE
        BotStateLoadError si corruption.
      - save() : atomic write (tmp + os.replace). Snapshot SOUS lock,
        write HORS lock. Best-effort (no raise, emit BOT_STATE_SAVE_FAILED).

    Thread safety : le lock est INJECTE par le bot proprietaire (ex
    self._pos_lock de BN V5). Eviter double lock = ne PAS utiliser
    de lock interne au helper.

    Usage :
        config = StateFileConfig(
            bot_name="bot3_v3",
            required_keys=frozenset({"schema_version", "session_date_utc",
                                     "positions", "last_update_ts"}),
        )
        file = BotStateFile(config, lock=self._pos_lock, emit_fn=_emit)

        data = file.load()  # None si NEW, raise si corrompu
        if data is None:
            # init vierge
        else:
            # restore from data
            ...

        file.save({"key": "value"})  # atomic
    """

    def __init__(
        self,
        config: StateFileConfig,
        lock: threading.Lock,
        emit_fn: Optional[Callable[..., None]] = None,
    ) -> None:
        self._config = config
        self._lock = lock
        self._emit = emit_fn if emit_fn is not None else self._noop_emit

    @staticmethod
    def _noop_emit(*args: Any, **kwargs: Any) -> None:
        """Default emit_fn : no-op. Utilise si logger pas disponible."""

    @property
    def state_path(self) -> Path:
        # state_path est garanti non-None par __post_init__
        assert self._config.state_path is not None
        return self._config.state_path

    @property
    def env_reset_var(self) -> str:
        return f"MIA_{self._config.bot_name.upper()}_STATE_RESET"

    def load(self) -> Optional[Dict[str, Any]]:
        """Restaure state si valide, return None si NEW, RAISE si corrompu.

        Return None (NEW_SESSION + init vierge) si :
          - Env var MIA_{BOT}_STATE_RESET=1 (Jackson force reset)
          - File absent (premier boot)
          - last_update_ts > max_age_hours (bot off trop longtemps)
          - session_date_check returns False (session UTC differente)

        Raise BotStateLoadError si :
          - JSON corrompu (parse error, IO error)
          - State pas un dict
          - REQUIRED_KEYS manquantes
          - schema_version_major mismatch
          - last_update_ts format invalide
        """
        # Env override Jackson explicite
        if os.environ.get(self.env_reset_var, "0") == "1":
            self._emit("BOT_STATE_NEW",
                       bot=self._config.bot_name,
                       reason=f"ENV_OVERRIDE_{self.env_reset_var}")
            return None

        if not self.state_path.exists():
            self._emit("BOT_STATE_NEW",
                       bot=self._config.bot_name,
                       reason="FILE_ABSENT")
            return None

        # Read + parse JSON (FAIL-CLOSED si corruption)
        try:
            raw = self.state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as e:
            self._emit("BOT_STATE_LOAD_FAILED",
                       bot=self._config.bot_name,
                       err=f"{type(e).__name__}: {str(e)[:200]}",
                       file=str(self.state_path))
            raise BotStateLoadError(
                f"{self._config.bot_name} state file corrompu "
                f"({self.state_path}): {e}. "
                f"Set {self.env_reset_var}=1 pour bypass."
            ) from e

        # Validation type
        if not isinstance(data, dict):
            self._emit("BOT_STATE_LOAD_FAILED",
                       bot=self._config.bot_name,
                       err=f"State file pas un dict: {type(data).__name__}",
                       file=str(self.state_path))
            raise BotStateLoadError(
                f"{self._config.bot_name} state file format invalide "
                f"(pas un dict)."
            )

        # Required keys (anti-pattern silent fallback)
        missing = self._config.required_keys - set(data.keys())
        if missing:
            self._emit("BOT_STATE_LOAD_FAILED",
                       bot=self._config.bot_name,
                       err=f"Keys manquantes: {sorted(missing)}",
                       file=str(self.state_path))
            raise BotStateLoadError(
                f"{self._config.bot_name} state file keys manquantes : "
                f"{sorted(missing)}. Set {self.env_reset_var}=1 pour bypass."
            )

        # Schema version (major.minor)
        major, minor = self._parse_schema_version(data)
        if major != self._config.schema_version_major:
            self._emit("BOT_STATE_SCHEMA_MAJOR_MISMATCH",
                       bot=self._config.bot_name,
                       file_major=major,
                       expected_major=self._config.schema_version_major,
                       file=str(self.state_path))
            raise BotStateLoadError(
                f"{self._config.bot_name} schema major mismatch : "
                f"file={major} expected={self._config.schema_version_major}. "
                f"Set {self.env_reset_var}=1 pour bypass."
            )
        if minor != self._config.schema_version_minor:
            self._emit("BOT_STATE_SCHEMA_MINOR_MISMATCH",
                       bot=self._config.bot_name,
                       file_minor=minor,
                       expected_minor=self._config.schema_version_minor)
            # WARN + accept (defauts explicites cote code consommateur)

        # Age check (last_update_ts)
        try:
            last_ts_str = str(data["last_update_ts"])
            last_ts = datetime.fromisoformat(last_ts_str.replace("Z", "+00:00"))
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - last_ts).total_seconds() / 3600
        except (ValueError, TypeError, KeyError) as e:
            self._emit("BOT_STATE_LOAD_FAILED",
                       bot=self._config.bot_name,
                       err=f"last_update_ts invalide: {e}",
                       file=str(self.state_path))
            raise BotStateLoadError(
                f"last_update_ts invalide : {e}"
            ) from e

        if age_hours > self._config.max_age_hours:
            self._emit("BOT_STATE_NEW",
                       bot=self._config.bot_name,
                       reason=f"AGE_{age_hours:.1f}h_GT_{self._config.max_age_hours}h")
            return None

        # Session date check (callable override-able pour CME day futur)
        session_check = self._config.session_date_check or self._default_session_check
        session_date_str = str(data.get("session_date_utc", ""))
        if not session_check(session_date_str):
            self._emit("BOT_STATE_NEW",
                       bot=self._config.bot_name,
                       reason=f"SESSION_DATE_{session_date_str}_NOT_CURRENT")
            return None

        # State valide -> restauration
        self._emit("BOT_STATE_RESTORED",
                   bot=self._config.bot_name,
                   session_date_utc=session_date_str,
                   age_hours=round(age_hours, 2))
        return data

    @staticmethod
    def _parse_schema_version(data: Dict[str, Any]) -> tuple[int, int]:
        """Parse schema_version : accepte int (compat BN V5) ou dict major.minor."""
        schema_data = data.get("schema_version", 1)
        if isinstance(schema_data, int):
            return schema_data, 0
        if isinstance(schema_data, dict):
            try:
                major = int(schema_data["major"])
                minor = int(schema_data.get("minor", 0))
                return major, minor
            except (KeyError, TypeError, ValueError) as e:
                raise BotStateLoadError(
                    f"schema_version format invalide : {e}"
                ) from e
        raise BotStateLoadError(
            f"schema_version type invalide : {type(schema_data).__name__}"
        )

    @staticmethod
    def _default_session_check(session_date_str: str) -> bool:
        """Default : match today UTC simple."""
        today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return session_date_str == today_utc

    def save(self, data: Dict[str, Any]) -> None:
        """Atomic write avec snapshot SOUS lock + write HORS lock.

        Best-effort : exception ne raise pas, emit BOT_STATE_SAVE_FAILED.

        Inject automatiquement schema_version + last_update_ts dans le snapshot.

        Args:
            data: payload (sans schema_version ni last_update_ts qui sont
                injectes par le helper).
        """
        try:
            # Snapshot SOUS lock (eviter race avec autres ecritures du bot)
            with self._lock:
                snapshot = dict(data)  # shallow copy
                snapshot["schema_version"] = {
                    "major": self._config.schema_version_major,
                    "minor": self._config.schema_version_minor,
                }
                snapshot["last_update_ts"] = datetime.now(timezone.utc).isoformat()

            # Write HORS lock (I/O lente, pas de partage etat)
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(snapshot, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self.state_path)
        except Exception as e:
            self._emit("BOT_STATE_SAVE_FAILED",
                       bot=self._config.bot_name,
                       err=f"{type(e).__name__}: {str(e)[:200]}",
                       file=str(self.state_path))


# ════════════════════════════════════════════════════════════════════════════
# POSITION PERSISTANCE — wrapper BotStateFile pour positions ouvertes
# ════════════════════════════════════════════════════════════════════════════

class PositionPersistance:
    """Tracking positions ouvertes par bot + reconciliation DTC.

    Compose BotStateFile pour la couche IO. Expose une API metier pour
    save/restore/remove de positions par symbole.

    La reconciliation DTC au boot compare Python state vs broker positions
    en 5 cas (a/b/c/d/e), retourne ReconcileReport pour chaque symbole.

    Usage :
        persist = PositionPersistance(
            bot_name="bot3_v3", lock=self._pos_lock, emit_fn=_emit)
        restored = persist.restore()
        for sym, pos in restored.items():
            self._position[sym] = pos

        # Plus tard, apres TRADE_OPEN :
        persist.save_position("NQ", {"entry": 29593, "sl": 29604, ...})

        # Apres TRADE_CLOSE :
        persist.remove_position("NQ")

        # boot_ready apres DTC connect :
        reports = persist.reconcile_with_dtc(
            dtc=self.dtc, trade_account="Sim1",
            symbol_to_contract={"NQ": "NQM26-CME"},
            force_flat_override=False)
        for r in reports:
            if r.is_critical:
                # HALT BOOT
                ...
    """

    REQUIRED_KEYS: FrozenSet[str] = frozenset({
        "schema_version", "session_date_utc", "positions", "last_update_ts",
    })

    def __init__(
        self,
        bot_name: str,
        lock: threading.Lock,
        emit_fn: Optional[Callable[..., None]] = None,
        state_path: Optional[Path] = None,
        schema_version_major: int = 1,
        schema_version_minor: int = 0,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> None:
        config = StateFileConfig(
            bot_name=bot_name,
            required_keys=self.REQUIRED_KEYS,
            schema_version_major=schema_version_major,
            schema_version_minor=schema_version_minor,
            state_path=state_path,
            max_age_hours=max_age_hours,
        )
        self._state_file = BotStateFile(config, lock=lock, emit_fn=emit_fn)
        self._lock = lock
        self._emit = emit_fn if emit_fn is not None else BotStateFile._noop_emit
        self._bot_name = bot_name
        # Positions: {symbol: {entry_price, sl_price, tp_price, side, qty,
        #                     parent_cid, tp_cid, sl_cid, ts_open, level, ...}}
        self._positions: Dict[str, Dict[str, Any]] = {}
        # Meta : namespace key/value horsplane positions (signal_counter,
        # last_trade_close_ts, pnl_uncertain flag, etc.)
        # Etape 2.A Bot 3 v3 integration (09/06).
        self._meta: Dict[str, Any] = {}

    @property
    def bot_name(self) -> str:
        return self._bot_name

    def restore(self) -> Dict[str, Dict[str, Any]]:
        """Restaure positions ET meta du JSON. {} si NEW_SESSION.

        Raise BotStateLoadError si corruption (FAIL-CLOSED).
        Le namespace `meta` (signal_counter, last_trade_close_ts, etc.) est
        aussi restaure ; accessible via get_meta(key, default).
        """
        data = self._state_file.load()
        if data is None:
            with self._lock:
                self._positions = {}
                self._meta = {}
            return {}
        # Charge positions du payload (deja valide par BotStateFile.load)
        raw_positions = data.get("positions", {})
        if not isinstance(raw_positions, dict):
            raise BotStateLoadError(
                f"positions field n'est pas un dict : "
                f"{type(raw_positions).__name__}"
            )
        # Charge meta (optionnel, default {})
        raw_meta = data.get("meta", {})
        if not isinstance(raw_meta, dict):
            # Tolerant : meta corrompu = reset, ne fait pas raise
            raw_meta = {}
        with self._lock:
            self._positions = {
                sym: dict(pos) for sym, pos in raw_positions.items()
            }
            self._meta = dict(raw_meta)
        return {sym: dict(pos) for sym, pos in self._positions.items()}

    def get_positions(self) -> Dict[str, Dict[str, Any]]:
        """Return snapshot des positions courantes (deep copy)."""
        with self._lock:
            return {sym: dict(pos) for sym, pos in self._positions.items()}

    def save_position(self, symbol: str, position: Dict[str, Any]) -> None:
        """Ajoute/met a jour une position et persiste sur disque."""
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("symbol doit etre un str non vide")
        if not isinstance(position, dict):
            raise TypeError(
                f"position doit etre un dict, recu {type(position).__name__}"
            )
        with self._lock:
            self._positions[symbol] = dict(position)
        self._persist()

    def remove_position(self, symbol: str) -> None:
        """Retire une position (TRADE_CLOSE) et persiste."""
        with self._lock:
            self._positions.pop(symbol, None)
        self._persist()

    def _persist(self) -> None:
        """Snapshot + save via BotStateFile."""
        with self._lock:
            positions_snapshot = {
                sym: dict(pos) for sym, pos in self._positions.items()
            }
            meta_snapshot = dict(self._meta)
        data = {
            "session_date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "positions": positions_snapshot,
            "meta": meta_snapshot,
        }
        self._state_file.save(data)

    # ────────────────────────────────────────────────────────────────────────
    # META API — namespace dedie pour key/value horsplane positions
    # ────────────────────────────────────────────────────────────────────────

    def set_meta(self, key: str, value: Any) -> None:
        """Persiste une cle/valeur dans le namespace meta du state file.

        Use case (etape 2.A Bot 3 v3) :
          - signal_counter_NQ : compteur signal_id persistant cross-restart
          - last_trade_close_ts_NQ : pour restore cooldown post-trade
          - last_shutdown_ts : audit
          - pnl_session_usd_uncertain : flag etat divergent (cas d reconcile)

        Args:
            key: identifiant string non vide.
            value: serialisable JSON (str/int/float/bool/None/dict/list).
        """
        if not isinstance(key, str) or not key:
            raise ValueError("key doit etre un str non vide")
        with self._lock:
            self._meta[key] = value
        self._persist()

    def get_meta(self, key: str, default: Any = None) -> Any:
        """Recupere une cle du namespace meta. Default si absent."""
        with self._lock:
            return self._meta.get(key, default)

    def get_all_meta(self) -> Dict[str, Any]:
        """Snapshot (deep copy) du namespace meta complet."""
        with self._lock:
            return dict(self._meta)

    # ────────────────────────────────────────────────────────────────────────
    # RECONCILIATION DTC (5 cas a/b/c/d/e)
    # ────────────────────────────────────────────────────────────────────────

    def reconcile_with_dtc(
        self,
        dtc: Any,
        trade_account: str,
        symbol_to_contract: Dict[str, str],
        force_flat_override: bool = False,
        position_query_timeout_sec: float = 3.0,
    ) -> List[ReconcileReport]:
        """Compare Python state vs broker DTC en 5 cas explicites.

        Args:
            dtc: DTCConnector (doit avoir methode request_position_blocking).
            trade_account: ex "Sim1" pour Bot 3 v3, "Sim2" pour BN V5/Bot 1.
            symbol_to_contract: mapping ex {"NQ": "NQM26-CME"}.
            force_flat_override: si True, autorise MARKET CLOSE sur cas c/e.
                Sinon HALT BOOT (action_taken="halt_boot", severity=CRITIQUE).
            position_query_timeout_sec: timeout DTC query position.

        Return:
            Liste de ReconcileReport, 1 par symbole.

        Side effects :
            - Emit code log selon cas (RECONCILE_*).
            - Cas d (Python ghost) : auto-purge Python state silent.
            - Cas c/e : NE FAIT PAS de MARKET CLOSE ici (le bot decide
              selon report.action_taken et force_flat_override).
        """
        reports: List[ReconcileReport] = []
        for symbol, contract in symbol_to_contract.items():
            report = self._reconcile_symbol(
                dtc=dtc,
                symbol=symbol,
                contract=contract,
                trade_account=trade_account,
                force_flat_override=force_flat_override,
                timeout_sec=position_query_timeout_sec,
            )
            reports.append(report)
        return reports

    def _reconcile_symbol(
        self,
        dtc: Any,
        symbol: str,
        contract: str,
        trade_account: str,
        force_flat_override: bool,
        timeout_sec: float,
    ) -> ReconcileReport:
        """Reconcilie 1 symbole."""
        # Query broker position
        try:
            broker_qty = dtc.request_position_blocking(
                contract, trade_account, timeout=timeout_sec,
            )
        except Exception as e:
            self._emit("BOT_STATE_LOAD_FAILED",
                       bot=self._bot_name,
                       err=f"reconcile query: {type(e).__name__}: {e}",
                       file=symbol)
            return ReconcileReport(
                case="QUERY_FAILED",
                symbol=symbol,
                python_state=self._positions.get(symbol),
                broker_position=None,
                action_taken="halt_boot",
                severity="CRITIQUE",
                note=f"DTC query failed: {type(e).__name__}",
            )

        python_pos = self._positions.get(symbol)
        python_flat = python_pos is None
        broker_flat = broker_qty is None or broker_qty == 0

        # Cas a : Python flat + Broker flat
        if python_flat and broker_flat:
            self._emit("RECONCILE_OK_FLAT",
                       bot=self._bot_name, symbol=symbol)
            return ReconcileReport(
                case="OK_FLAT", symbol=symbol,
                action_taken="none", severity="INFO",
            )

        # Cas c : Python flat + Broker pos (PAS de tracking)
        if python_flat and not broker_flat:
            br_side = "LONG" if broker_qty > 0 else "SHORT"
            action = "force_flat" if force_flat_override else "halt_boot"
            self._emit("RECONCILE_UNKNOWN_BROKER_POS",
                       bot=self._bot_name, symbol=symbol,
                       broker_qty=broker_qty, broker_side=br_side,
                       action=action)
            if force_flat_override:
                self._emit("RECONCILE_FORCE_FLAT_OVERRIDE",
                           bot=self._bot_name, symbol=symbol, action=action)
            return ReconcileReport(
                case="UNKNOWN_BROKER_POS", symbol=symbol,
                python_state=None,
                broker_position={"qty": broker_qty, "side": br_side},
                action_taken=action, severity="CRITIQUE",
                note=(
                    "Broker a une position que Python ne connait pas. "
                    "Peut etre legitime (autre bot meme compte) ou "
                    "fantome. Jackson decide via env var "
                    f"MIA_{self._bot_name.upper()}_RECONCILE_FORCE_FLAT=1"
                ),
            )

        # Cas d : Python pos + Broker flat (ghost = fermee externalement)
        if (not python_flat) and broker_flat:
            self._emit("RECONCILE_PYTHON_GHOST",
                       bot=self._bot_name, symbol=symbol,
                       py_pos=python_pos)
            # Auto-purge silent
            self.remove_position(symbol)
            return ReconcileReport(
                case="PYTHON_GHOST", symbol=symbol,
                python_state=dict(python_pos),
                broker_position=None,
                action_taken="purge", severity="ALERTE",
                note=(
                    "Position fermee externalement (flatten manuel Sierra "
                    "Chart, OCO orphan, etc.). Python state purged. "
                    "P&L audit a verifier manuellement."
                ),
            )

        # Cas b ou e : Python pos + Broker pos -> match ou divergence
        py_qty = int(python_pos.get("qty", 0))
        # Compat convention : "side" (BN V5) ou "direction" (Bot 3 v3 legacy)
        py_side = str(
            python_pos.get("side") or python_pos.get("direction", "")
        ).upper()
        br_side = "LONG" if broker_qty > 0 else "SHORT"
        br_qty_abs = abs(broker_qty)

        if py_side == br_side and py_qty == br_qty_abs:
            # Cas b : OK restored
            self._emit("RECONCILE_OK_RESTORED",
                       bot=self._bot_name, symbol=symbol,
                       py_qty=py_qty, py_side=py_side,
                       broker_qty=broker_qty)
            return ReconcileReport(
                case="OK_RESTORED", symbol=symbol,
                python_state=dict(python_pos),
                broker_position={"qty": broker_qty, "side": br_side},
                action_taken="restored", severity="INFO",
            )

        # Cas e : divergence (direction OU qty diff)
        action = "force_flat" if force_flat_override else "halt_boot"
        self._emit("RECONCILE_DIVERGENCE",
                   bot=self._bot_name, symbol=symbol,
                   py_qty=py_qty, py_side=py_side,
                   broker_qty=broker_qty, broker_side=br_side,
                   action=action)
        if force_flat_override:
            self._emit("RECONCILE_FORCE_FLAT_OVERRIDE",
                       bot=self._bot_name, symbol=symbol, action=action)
        return ReconcileReport(
            case="DIVERGENCE", symbol=symbol,
            python_state=dict(python_pos),
            broker_position={"qty": broker_qty, "side": br_side},
            action_taken=action, severity="CRITIQUE",
            note=(
                f"Python {py_side} {py_qty} vs Broker {br_side} "
                f"{br_qty_abs}. Divergence critique."
            ),
        )
