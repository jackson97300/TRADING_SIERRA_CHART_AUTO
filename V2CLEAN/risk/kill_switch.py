"""
V2CLEAN — Kill Switch (17/04/2026)
===================================

Lockfile IPC partage entre bot et dashboard. Source of truth du kill switch global.

Architecture :
  - Lockfile JSON ecrit atomiquement (tmp + os.replace, POSIX/NTFS atomic)
  - Dashboard peut ecrire le fichier pour declencher manuel (Jackson)
  - Bot lit le fichier a chaque polling (CONFIG.kill_switch.poll_interval_sec)
  - Pas de locking OS (portalocker) Phase 1 — race accepte + log conflict

Niveaux (Jackson 17/04/2026) :
  - DAILY        : auto-lift au reset session (bar.date change en ET)
  - CATASTROPHE  : manuel only (dashboard) — safety net inconditionnel

Champ `tripped_by` separe le LEVEL (gravite) du DECLENCHEMENT (auto/manual).

Persistance : CONFIG.kill_switch.lockfile_path (default V2CLEAN/STATE/.kill_switch)
Journal : events.jsonl injectable via callback (Day 5 pour wiring complet)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from V2CLEAN.config import CONFIG


log = logging.getLogger(__name__)

# Systeme logs V2 (Chantier 3 22/04) : emits additionnels process="v2clean"
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("v2clean_kill_switch", process="v2clean")
except Exception:
    _v2log = None


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class KillSwitchLevel(str, Enum):
    """Gravite du kill switch.

    DAILY       : perte journaliere >= daily_loss_usd → auto-lift au reset
    CATASTROPHE : perte catastrophe >= catastrophe_loss_usd → manuel only
    """
    DAILY = "daily"
    CATASTROPHE = "catastrophe"


# Event callback type : (event_type, payload) -> None
# Phase 1 : optionnel. Day 5 : wiring EventJournal.log_event
EventJournalCallback = Callable[[str, dict], None]


# ═══════════════════════════════════════════════════════════════════════════════
# STATE DATACLASS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class KillSwitchState:
    """Snapshot state lockfile, deserialise du JSON."""
    active: bool
    level: Optional[KillSwitchLevel]
    reason: str
    tripped_at: Optional[datetime]           # UTC
    tripped_by: Optional[Literal["auto", "manual"]]
    lifted_at: Optional[datetime]            # UTC, dernier lift
    lifted_by: Optional[Literal["auto_reset", "manual"]]
    history: tuple[dict, ...] = field(default_factory=tuple)

    @classmethod
    def inactive(cls) -> "KillSwitchState":
        return cls(
            active=False, level=None, reason="",
            tripped_at=None, tripped_by=None,
            lifted_at=None, lifted_by=None, history=(),
        )

    def to_json(self) -> dict:
        return {
            "active": self.active,
            "level": self.level.value if self.level else None,
            "reason": self.reason,
            "tripped_at": self.tripped_at.isoformat() if self.tripped_at else None,
            "tripped_by": self.tripped_by,
            "lifted_at": self.lifted_at.isoformat() if self.lifted_at else None,
            "lifted_by": self.lifted_by,
            "history": list(self.history),
        }

    @classmethod
    def from_json(cls, data: dict) -> "KillSwitchState":
        level_raw = data.get("level")
        level = KillSwitchLevel(level_raw) if level_raw else None
        tripped_at = _parse_dt(data.get("tripped_at"))
        lifted_at = _parse_dt(data.get("lifted_at"))
        history = tuple(data.get("history", []))
        return cls(
            active=bool(data.get("active", False)),
            level=level,
            reason=data.get("reason", ""),
            tripped_at=tripped_at,
            tripped_by=data.get("tripped_by"),
            lifted_at=lifted_at,
            lifted_by=data.get("lifted_by"),
            history=history,
        )


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Handle Z suffix (UTC)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# KILL SWITCH
# ═══════════════════════════════════════════════════════════════════════════════

class KillSwitch:
    """Lockfile manager. Lecture/ecriture atomic.

    Usage :
      ks = KillSwitch()
      if ks.is_active()[0]:  # fast path bool
          return REJECT
      ks.trip(KillSwitchLevel.DAILY, "daily_pnl -$523 <= -$500", tripped_by="auto")
      ks.try_auto_lift_daily()  # appele au reset session
    """

    MAX_HISTORY = 50  # Eviter croissance infinie

    def __init__(
        self,
        lockfile_path: Optional[Path] = None,
        clock: Optional[Callable[[], datetime]] = None,
        journal: Optional[EventJournalCallback] = None,
    ):
        self.lockfile_path = Path(lockfile_path or CONFIG.kill_switch.lockfile_path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._journal = journal
        # Garantir le dossier parent
        self.lockfile_path.parent.mkdir(parents=True, exist_ok=True)

    # ─── Public API ───────────────────────────────────────────────────────────

    def state(self) -> KillSwitchState:
        """Lit et parse le lockfile. Retourne `inactive()` si absent ou corrompu."""
        if not self.lockfile_path.exists():
            return KillSwitchState.inactive()
        try:
            with self.lockfile_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return KillSwitchState.from_json(data)
        except (OSError, json.JSONDecodeError) as e:
            log.error(
                "kill_switch lockfile corrupted (%s): %s — backing up + fresh start",
                self.lockfile_path, e,
            )
            self._backup_corrupt()
            return KillSwitchState.inactive()

    def is_active(self) -> tuple[bool, str]:
        """Fast path bool : (active, reason)."""
        st = self.state()
        return st.active, st.reason

    def trip(
        self,
        level: KillSwitchLevel,
        reason: str,
        tripped_by: Literal["auto", "manual"] = "auto",
    ) -> bool:
        """Declenche le kill switch. Ecrit lockfile atomiquement.

        Si deja actif avec level plus haut (CATASTROPHE > DAILY), pas d'ecrasement.
        Log dans history + notifie journal si injecte.

        Returns:
            True si trip applique, False si no-op (deja actif avec level superieur).
        """
        current = self.state()
        # Si deja CATASTROPHE, un DAILY ne degrade pas
        if current.active and current.level == KillSwitchLevel.CATASTROPHE \
                and level == KillSwitchLevel.DAILY:
            log.info(
                "kill_switch already CATASTROPHE, ignoring DAILY trip (%s)", reason
            )
            return False

        now = self._clock()
        history = list(current.history)
        history.append({
            "at": now.isoformat(),
            "action": "trip",
            "level": level.value,
            "tripped_by": tripped_by,
            "reason": reason,
        })
        history = history[-self.MAX_HISTORY:]  # cap

        new_state = KillSwitchState(
            active=True,
            level=level,
            reason=reason,
            tripped_at=now,
            tripped_by=tripped_by,
            lifted_at=current.lifted_at,    # garde dernier lift pour audit
            lifted_by=current.lifted_by,
            history=tuple(history),
        )
        self._write_atomic(new_state)
        self._emit_event("kill_switch_trip", {
            "level": level.value,
            "reason": reason,
            "tripped_by": tripped_by,
            "at": now.isoformat(),
        })
        log.warning(
            "KILL SWITCH TRIPPED: level=%s tripped_by=%s reason=%s",
            level.value, tripped_by, reason,
        )
        # V2 log : emit code selon niveau (CRITIQUE, transition unique)
        if _v2log:
            level_val = level.value if hasattr(level, "value") else str(level)
            if "CATASTROPHE" in level_val.upper():
                _v2log.emit("KILL_CATASTROPHE", pnl=0.0)
            elif "DAILY" in level_val.upper():
                _v2log.emit("KILL_DD_DAILY", pnl=0.0, limit=0.0)
            elif "INTRADAY" in level_val.upper():
                _v2log.emit("KILL_INTRADAY_DD", dd=0.0, limit=0.0)
            elif "MAX_TRADE" in level_val.upper():
                _v2log.emit("KILL_MAX_TRADES", n=0, limit=0)
            else:
                _v2log.emit("KILL_CATASTROPHE", pnl=0.0)
        return True

    def lift(
        self,
        lifted_by: Literal["auto_reset", "manual"] = "manual",
    ) -> bool:
        """Lift le kill switch. CATASTROPHE ne peut pas etre auto-reset.

        Returns:
            True si effectivement lifted, False si refuse/no-op.
        """
        current = self.state()
        if not current.active:
            return False

        # Catastrophe = manuel only
        if current.level == KillSwitchLevel.CATASTROPHE \
                and lifted_by == "auto_reset":
            log.info("kill_switch CATASTROPHE refuse auto_reset (manuel only)")
            return False

        now = self._clock()
        history = list(current.history)
        history.append({
            "at": now.isoformat(),
            "action": "lift",
            "lifted_by": lifted_by,
            "previous_level": current.level.value if current.level else None,
        })
        history = history[-self.MAX_HISTORY:]

        new_state = KillSwitchState(
            active=False,
            level=None,
            reason="",
            tripped_at=None,
            tripped_by=None,
            lifted_at=now,
            lifted_by=lifted_by,
            history=tuple(history),
        )
        self._write_atomic(new_state)
        self._emit_event("kill_switch_lift", {
            "lifted_by": lifted_by,
            "previous_level": current.level.value if current.level else None,
            "at": now.isoformat(),
        })
        log.info("kill_switch LIFTED by %s", lifted_by)
        return True

    def try_auto_lift_daily(self) -> bool:
        """Lift UNIQUEMENT si level=DAILY. Appele au reset session."""
        current = self.state()
        if current.active and current.level == KillSwitchLevel.DAILY:
            return self.lift(lifted_by="auto_reset")
        return False

    # ─── Internals ────────────────────────────────────────────────────────────

    def _write_atomic(self, state: KillSwitchState) -> None:
        """Ecrit lockfile JSON atomiquement (tmp + os.replace)."""
        payload = json.dumps(state.to_json(), indent=2, ensure_ascii=False)
        dir_ = self.lockfile_path.parent
        # tempfile dans meme dir pour que os.replace soit cross-device safe
        fd, tmp_path = tempfile.mkstemp(
            prefix=".kill_switch_", suffix=".tmp", dir=str(dir_)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.lockfile_path)  # atomic
        except OSError as e:
            # Cleanup tmp si rename echoue
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            log.error("kill_switch atomic write failed: %s", e)
            raise

    def _backup_corrupt(self) -> None:
        """Rename lockfile corrompu en .corrupt pour audit."""
        try:
            backup = self.lockfile_path.with_suffix(
                self.lockfile_path.suffix + ".corrupt"
            )
            os.replace(self.lockfile_path, backup)
            log.warning("lockfile corrupt backed up to %s", backup)
        except OSError as e:
            log.error("cannot backup corrupt lockfile: %s", e)

    def _emit_event(self, event_type: str, payload: dict) -> None:
        """Notifie journal callback si injecte. Phase 1 : logging.info si absent."""
        if self._journal is None:
            log.info("event[%s]: %s", event_type, payload)
            return
        try:
            self._journal(event_type, payload)
        except Exception as e:
            log.error("journal callback failed for %s: %s", event_type, e)


__all__ = [
    "KillSwitch",
    "KillSwitchLevel",
    "KillSwitchState",
    "EventJournalCallback",
]
