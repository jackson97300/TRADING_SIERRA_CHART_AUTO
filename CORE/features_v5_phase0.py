"""features_v5_phase0.py - Phase 0 V5 : features manquantes a cout zero.

Sortie audit cross-agents 12/06/2026 (market-analyst ULTRATHINK) :
3 dimensions empiriques manquantes pipeline MIA pour selection V5 :

  1. Time-of-day fine (Hasbrouck 2018 intraday U-shape volatility)
  2. Calendar countdown FOMC/NFP/CPI (Lucca/Moench 2015 FOMC drift)
  3. OPEX week (3e vendredi options expiration)

Features ajoutees (7) :

  Time-of-day RTH :
    1. tod_bucket_rth     : int 0-14, 0=pre-RTH, 1-13=buckets 30min RTH, 14=post-RTH
                             (RTH = 09:30-16:00 ET = mins_et 570-960)

  Calendar context :
    2. week_of_month      : int 1-5, semaine calendaire du mois (day // 7 + 1)
    3. is_opex_week       : bool, semaine du 3e vendredi (OPEX day)

  Event countdown (fractional days, NaN si event hors semaine en cours) :
    4. days_to_next_fomc          : float, NaN si pas de FOMC cette semaine
    5. days_to_next_nfp           : float
    6. days_to_next_cpi           : float
    7. days_to_next_critical_ev   : float, plus proche event critique tous types

Source dependances :
  - `eco_calendar.fetch_events()` : events ForexFactory thisweek
  - `eco_calendar.is_critical(ev)` : detection FOMC/NFP/CPI/PCE/PPI/GDP/Retail
  - `eco_calendar.CRITICAL_KEYWORDS` : keywords match titre event

Limitation cache thisweek :
  ForexFactory JSON = events semaine en cours seulement. days_to_next_fomc
  retourne NaN si prochain FOMC est dans 2+ semaines. LightGBM apprend
  semantique "NaN = >1 semaine before event".

Auteur : MIA Trading V5 (Phase 0 cross-agents validation)
Date   : 2026-06-12
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import numpy as np

# Import gracieux : permet test isole + integration sierra_pipeline future
try:
    from CORE.eco_calendar import (
        CRITICAL_KEYWORDS, US_FUTURES_RELEVANT,
        fetch_events, is_critical,
        _country_normalized, _impact_normalized, _parse_event_dt,
    )
except ImportError:
    try:
        from eco_calendar import (  # type: ignore
            CRITICAL_KEYWORDS, US_FUTURES_RELEVANT,
            fetch_events, is_critical,
            _country_normalized, _impact_normalized, _parse_event_dt,
        )
    except ImportError:
        CRITICAL_KEYWORDS = []
        US_FUTURES_RELEVANT = {"USD"}
        fetch_events = None
        is_critical = None
        _country_normalized = None
        _impact_normalized = None
        _parse_event_dt = None


# RTH bucket constants
RTH_START_MINS_ET = 570  # 09:30 ET
RTH_END_MINS_ET = 960    # 16:00 ET
BUCKET_SIZE_MIN = 30
N_RTH_BUCKETS = 13       # (960-570)/30 = 13 buckets [1-13]

# OPEX week : 3e vendredi du mois = semaine 3 (day 15-21)
OPEX_WEEK_MIN_DAY = 15
OPEX_WEEK_MAX_DAY = 21

# Keywords countdown specifiques (sous-ensemble CRITICAL_KEYWORDS)
FOMC_KEYWORDS = ("FOMC", "Fed Chair", "Fed Funds Rate", "Federal Reserve")
NFP_KEYWORDS = ("Non-Farm Employment", "NFP", "Unemployment Rate")
CPI_KEYWORDS = ("CPI m/m", "Core CPI", "Core PCE Price Index", "PPI m/m")


def compute_tod_bucket_rth(mins_et: Optional[int]) -> int:
    """Time-of-day bucket RTH 30min.

    Args:
        mins_et : minutes since midnight ET (de bar live_enriched)

    Returns:
        0  = pre-RTH (mins_et < 570 = avant 09:30 ET)
        1  = 09:30-09:59 ET (premier 30min RTH)
        2  = 10:00-10:29 ET
        ...
        13 = 15:30-15:59 ET (dernier 30min RTH avant close)
        14 = post-RTH (mins_et >= 960 = apres 16:00 ET)

    Returns 0 si mins_et None/NaN (gracieux).
    """
    if mins_et is None:
        return 0
    if isinstance(mins_et, float) and np.isnan(mins_et):
        return 0
    m = int(mins_et)
    if m < RTH_START_MINS_ET:
        return 0
    if m >= RTH_END_MINS_ET:
        return 14
    return 1 + (m - RTH_START_MINS_ET) // BUCKET_SIZE_MIN


def compute_week_of_month(now_utc: datetime) -> int:
    """Semaine du mois 1-5 base day_of_month.

    Convention : (day - 1) // 7 + 1
    Day 1-7 = sem 1, 8-14 = sem 2, 15-21 = sem 3 (OPEX), 22-28 = sem 4, 29-31 = sem 5
    """
    return (now_utc.day - 1) // 7 + 1


def compute_is_opex_week(now_utc: datetime) -> bool:
    """True si jour 15-21 (semaine du 3e vendredi = OPEX)."""
    return OPEX_WEEK_MIN_DAY <= now_utc.day <= OPEX_WEEK_MAX_DAY


def _days_until_next_matching_event(
    now_utc: datetime,
    match_keywords: tuple,
    require_high_usd: bool = True,
) -> float:
    """Calcule jours fractionnaires jusqu'au prochain event match.

    Args:
        now_utc : timestamp UTC tz-aware
        match_keywords : tuple keywords a matcher dans le titre event
        require_high_usd : si True (defaut), filtre AUSSI impact=high + country=USD
                           pour coherence avec is_critical() (anti CPI etranger).
                           Mettre False pour matching keyword pur.

    Returns NaN si aucun event match dans le cache thisweek.
    """
    if fetch_events is None or _parse_event_dt is None:
        return float("nan")

    try:
        events = fetch_events()
    except Exception:  # noqa: BLE001
        return float("nan")

    upcoming_dts = []
    for ev in events:
        # Filtre coherence is_critical() : high impact + USD
        if require_high_usd:
            if _impact_normalized is not None and _impact_normalized(ev) != "high":
                continue
            if _country_normalized is not None and _country_normalized(ev) not in US_FUTURES_RELEVANT:
                continue
        title = (ev.get("title") or ev.get("name") or "").lower()
        if not any(kw.lower() in title for kw in match_keywords):
            continue
        ev_dt = _parse_event_dt(ev)
        if ev_dt is None or ev_dt <= now_utc:
            continue
        upcoming_dts.append(ev_dt)

    if not upcoming_dts:
        return float("nan")

    nearest = min(upcoming_dts)
    delta_sec = (nearest - now_utc).total_seconds()
    return delta_sec / 86400.0  # secondes -> jours fractionnaires


def compute_days_to_next_fomc(now_utc: datetime) -> float:
    """Jours fractionnaires jusqu'au prochain FOMC (NaN si pas cette semaine)."""
    return _days_until_next_matching_event(now_utc, FOMC_KEYWORDS)


def compute_days_to_next_nfp(now_utc: datetime) -> float:
    """Jours fractionnaires jusqu'au prochain NFP (NaN si pas cette semaine)."""
    return _days_until_next_matching_event(now_utc, NFP_KEYWORDS)


def compute_days_to_next_cpi(now_utc: datetime) -> float:
    """Jours fractionnaires jusqu'au prochain CPI/PPI/PCE (NaN si pas cette semaine)."""
    return _days_until_next_matching_event(now_utc, CPI_KEYWORDS)


def compute_days_to_next_critical_event(now_utc: datetime) -> float:
    """Jours fractionnaires jusqu'au plus proche event critique TOUS TYPES.

    Utilise is_critical() = match sur CRITICAL_KEYWORDS complet (FOMC + NFP + CPI + Retail + GDP).
    Returns NaN si aucun event critique cette semaine.
    """
    if fetch_events is None or is_critical is None or _parse_event_dt is None:
        return float("nan")

    try:
        events = fetch_events()
    except Exception:  # noqa: BLE001
        return float("nan")

    upcoming_dts = []
    for ev in events:
        if not is_critical(ev):
            continue
        ev_dt = _parse_event_dt(ev)
        if ev_dt is None or ev_dt <= now_utc:
            continue
        upcoming_dts.append(ev_dt)

    if not upcoming_dts:
        return float("nan")

    nearest = min(upcoming_dts)
    delta_sec = (nearest - now_utc).total_seconds()
    return delta_sec / 86400.0


def compute_phase0_features(
    now_utc: Optional[datetime] = None,
    mins_et: Optional[int] = None,
) -> dict:
    """API publique : compute 7 features Phase 0 V5.

    Args:
        now_utc : timestamp UTC tz-aware. None -> datetime.now(timezone.utc).
        mins_et : minutes since midnight ET (de bar live_enriched).
                  Si None, tod_bucket_rth = 0.

    Returns:
        dict avec 7 keys (cf docstring module).

    Raises:
        ValueError : now_utc naive (DST hell).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    if now_utc.tzinfo is None:
        raise ValueError(
            f"compute_phase0_features : now_utc doit etre tz-aware UTC, "
            f"obtenu naive {now_utc}"
        )

    return {
        "tod_bucket_rth": compute_tod_bucket_rth(mins_et),
        "week_of_month": compute_week_of_month(now_utc),
        "is_opex_week": compute_is_opex_week(now_utc),
        "days_to_next_fomc": compute_days_to_next_fomc(now_utc),
        "days_to_next_nfp": compute_days_to_next_nfp(now_utc),
        "days_to_next_cpi": compute_days_to_next_cpi(now_utc),
        "days_to_next_critical_ev": compute_days_to_next_critical_event(now_utc),
    }


def _empty_features() -> dict:
    """Features par defaut pour batch processing avec ts invalide."""
    return {
        "tod_bucket_rth": 0,
        "week_of_month": 1,
        "is_opex_week": False,
        "days_to_next_fomc": float("nan"),
        "days_to_next_nfp": float("nan"),
        "days_to_next_cpi": float("nan"),
        "days_to_next_critical_ev": float("nan"),
    }
