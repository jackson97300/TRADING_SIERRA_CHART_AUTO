"""Session filter gate Bot 1 v2.

Bloque trades :
  - Hors session US (Asia OK pour observation mais pas trade)
  - Pendant news lockout (5 min avant/apres CPI/FOMC/NFP)
  - EOD lockout (10 min avant 16:00 ET)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from CORE.bot1_v2.config import Bot1V2Config


@dataclass(frozen=True)
class SessionVerdict:
    allowed: bool
    skip_reason: str = ""
    session_phase: str = ""  # "US_RTH" / "ASIA" / "LONDON" / "PRE_RTH" / "POST_RTH"


def _ts_to_et_datetime(ts_ms: Optional[int]) -> Optional[datetime]:
    """Convert ts_ms UTC -> ET datetime (UTC-5 EST, UTC-4 EDT).

    Pour bot 1 v2 ete (juin-novembre) : EDT UTC-4.
    Simplification : on prend UTC-4 toute l'annee (acceptable pour session boundaries).
    """
    if ts_ms is None:
        return None
    try:
        dt_utc = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return dt_utc + timedelta(hours=-4)


class SessionGate:
    """Filtre session : trade UNIQUEMENT en US RTH (09:30 - 16:00 ET)."""

    def __init__(self, cfg: Bot1V2Config):
        self.cfg = cfg

    def check_allow_entry(self, bar: dict) -> SessionVerdict:
        # Read session info depuis sierra_enriched si dispo
        session_id = (bar.get("session_id") or "").upper()
        session_segment = (bar.get("session_segment") or "").lower()
        is_in_us = bar.get("is_in_us_cash")
        is_news_5m = bar.get("is_news_5m")
        is_eco_blocked = bar.get("is_eco_blocked")

        # News lockout : si bar contient flag eco
        if bool(is_eco_blocked):
            return SessionVerdict(
                allowed=False, skip_reason="NEWS_LOCKOUT_ECO_BLOCKED",
            )
        if bool(is_news_5m):
            return SessionVerdict(
                allowed=False, skip_reason="NEWS_LOCKOUT_5MIN",
            )

        # Session : exiger US RTH
        if bool(is_in_us) or session_id == "US" or "us_cash" in session_segment:
            # EOD lockout : check minutes restantes avant 16:00 ET
            ts_ms = bar.get("ts")
            dt_et = _ts_to_et_datetime(ts_ms)
            if dt_et is not None:
                # 16:00 ET = 960 minutes from midnight ET
                mins_et = dt_et.hour * 60 + dt_et.minute
                eod_mins = 16 * 60  # 16:00 ET
                if mins_et > eod_mins - self.cfg.EOD_LOCKOUT_MINUTES:
                    return SessionVerdict(
                        allowed=False,
                        skip_reason=f"EOD_LOCKOUT:{mins_et}>{eod_mins - self.cfg.EOD_LOCKOUT_MINUTES}",
                        session_phase="US_RTH",
                    )
                # Pre-RTH lockout : avant 09:30 ET
                rth_open = 9 * 60 + 30  # 09:30 ET = 570
                if mins_et < rth_open:
                    return SessionVerdict(
                        allowed=False,
                        skip_reason=f"PRE_RTH:{mins_et}<{rth_open}",
                        session_phase="PRE_RTH",
                    )
            return SessionVerdict(allowed=True, session_phase="US_RTH")

        # Hors US : determiner phase
        phase = "?"
        if session_id == "ASIA":
            phase = "ASIA"
        elif session_id == "LONDON":
            phase = "LONDON"
        elif session_id == "US_AFTER":
            phase = "POST_RTH"
        # FIX 17/06 Jackson : check si phase est dans TRADABLE_SESSIONS configure.
        # Avant ce fix : SessionGate HARDCODE "US uniquement" + ignore cfg.TRADABLE_SESSIONS
        # -> ASIA/LONDON toujours rejetes meme si configures. Bug silencieux qui empechait
        # de tester en hors-RTH (audit empirique 17/06 matin Londres : 0 trade).
        if phase in self.cfg.TRADABLE_SESSIONS:
            return SessionVerdict(allowed=True, session_phase=phase)
        return SessionVerdict(
            allowed=False,
            skip_reason=f"SESSION_NOT_TRADABLE:{phase}",
            session_phase=phase,
        )
