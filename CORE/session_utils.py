"""session_utils.py — Helpers session-tracking commun Sierra Migration.

Phase 3.3.5 Sierra Full Migration (10/06/2026).
Cree apres review batch 3.3+3.4 (agentId a29ed1d3858b5d53e) - point D
duplication cross-module.

Utilities partagees par :
  - CORE/prev_levels.py (Phase 3.3)
  - CORE/sessions_fine.py (Phase 3.4)
  - CORE/ctx_rolling.py (Phase 3.5 future)
  - tout autre module session-aware

Convention CME pivot :
  - Reset session_date_trading a 18:00 ET (= 22:00/23:00 UTC selon DST)
  - Timezone ET via zoneinfo (auto bascule ete/hiver)
  - JAMAIS hardcode offset (lecon Phase 3.4 DST hell)

Anti-pattern interdit :
  - Silent fallback ts naive -> raise ValueError (FAIL LOUD)
  - Hardcode +5h/-5h offset (= bug 2x/an)

Auteur : MIA Trading V2 (Phase 3.3.5 Sierra Migration refactor)
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# Source unique de verite timezone ET
ET = ZoneInfo("America/New_York")

# CME daily reset = 18:00 ET (nouveau session_date_trading)
CME_DAILY_RESET_ET = time(18, 0)


def utc_to_et(ts_utc: datetime) -> datetime:
    """Convertit datetime UTC tz-aware en ET.

    FAIL LOUD : raise ValueError si ts naive.

    Args:
        ts_utc : datetime UTC tz-aware.

    Returns:
        datetime ET (DST handled by zoneinfo).

    Raises:
        ValueError : si ts_utc naive (tzinfo None).
    """
    if ts_utc.tzinfo is None:
        raise ValueError(
            f"utc_to_et : ts_utc doit etre tz-aware, obtenu naive {ts_utc}"
        )
    return ts_utc.astimezone(ET)


def compute_trading_date(ts_et: datetime) -> date:
    """Determine session_date_trading CME (reset 18:00 ET).

    Convention :
      - Si heure ET >= 18:00 : session_date_trading = J+1 (ex Vendredi 19:00 ET
        -> samedi).
      - Sinon : session_date_trading = J.

    Note : pendant le week-end (vendredi 18:00 ET -> dimanche 18:00 ET),
    trading_date peut etre samedi ou dimanche meme si marche CME ferme.
    C'est volontaire : le reset PDH/PDL se fera dimanche 18:00 ET.

    Args:
        ts_et : datetime ET tz-aware.

    Returns:
        session_date_trading (date civile CME).
    """
    if ts_et.time() >= CME_DAILY_RESET_ET:
        return (ts_et + timedelta(days=1)).date()
    return ts_et.date()


def get_trading_date_from_utc(ts_utc: datetime) -> date:
    """Helper : UTC -> ET -> trading_date en une etape.

    Args:
        ts_utc : datetime UTC tz-aware.

    Returns:
        session_date_trading.

    Raises:
        ValueError : si ts_utc naive.
    """
    return compute_trading_date(utc_to_et(ts_utc))
