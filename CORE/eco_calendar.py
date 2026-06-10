"""eco_calendar.py — calendrier economique + fenetres de session structurelles.

CALENDRIER UNIQUE qui regroupe TOUTES les regles "ne pas trader" du bot :
1. Events economiques (FOMC, NFP, CPI, PCE) via ForexFactory JSON
2. Fenetres de session structurelles (open US volatility, close US MOC, weekend)

Regroupement decide 29/04/2026 soir avec Jackson : 1 seul module = 1 seule
verite "blocked / not blocked". Le dashboard et les bots interrogent un
unique point d'entree (`is_blocked_combined()`).

==========================================================================
SECTION 1 — EVENTS ECO (ForexFactory)
==========================================================================
Source : `https://nfs.faireconomy.media/ff_calendar_thisweek.json`
Gratuit, hebdo, heberge Cloudflare.

Cree suite a perte -$1156 sur NQ pendant FOMC ce soir alors que le bot
tradait sans gate eco. La page `/calendar` existait mais etait DECORATIVE
(iframe TradingView, zero integration bot).

Regle :
- High impact + USD → BLOCK -15min / +30min
- Medium / Low / Holiday → ignore
- Cache local 6h, fallback gracieux si fetch fail

==========================================================================
SECTION 2 — FENETRES DE SESSION (structurelles)
==========================================================================
Decisions Jackson 29/04/2026 soir (cf DOCS/eco_session_blocks_design.md) :

  A. **Open US volatility** : 09:15-09:45 ET (= 15:15-15:45 Paris ete)
     Raison : volatilite ouverture RTH (gap fillers, stop runs MM).
     Trader pro consensus — Jackson conviction.

  B. **Post-MOC pause** : 15:30 ET → 18:15 ET (CME Asia open + buffer 15min)
     = 21:30 Paris ete → 00:15 Paris ete du lendemain.
     Raison : 30min MOC imbalance institutionnel (15:30-16:00 ET) +
     2h15 pause avant CME Asia futures session (18:00 ET).
     PILOT 30 JOURS (Jackson 30/04) : avant block_end = 21:30 ET (= 03:30 Paris,
     post Tokyo cash open + 30min). Pilot teste 18:15 ET = reprise CME Asia
     futures + 15min buffer = ~3h15 d'edge en plus a evaluer en paper. Si
     PSR>0.95 sur n>=15 trades dans la fenetre 18:15-21:30 ET au J+30
     (30/05/2026) → garder. Sinon rollback a 21:30 ET.

  C. **Weekend** : vendredi 15:30 ET → dimanche 18:15 ET (CME Asia open Sun + 15min)
     = vendredi 21:30 Paris → lundi 00:15 Paris.
     Raison : volume mort weekend, dimanche soir = trappe a amateurs.
     Coherence avec fenetre B (meme reprise CME Asia + 15min buffer).

  D. **Action** : pas de NEW trade pendant ces fenetres, laisser
     TP/SL en cours actifs (chirurgical, pas de flatten force).

PILOT 30 JOURS Jackson (30/04/2026) :
  Reprise CME Asia futures 18:15 ET (= 00:15 Paris ete). Avant : 21:30 ET (Tokyo
  cash open + 30min). Pilot teste si l'edge ~3h15 supplementaires est exploitable
  en paper. Critere J+30 (30/05/2026) : PSR>0.95 sur n>=15 trades dans la fenetre
  18:15-21:30 ET → garder 18:15. Sinon rollback 21:30.

NOTE historique : market-analyst avait initialement rejete 18:15 ET (28/04 :
  "n=12 noise, pas d'empirique"). Le pilot collecte maintenant l'empirique
  manquant en paper (0$ risque) avant decision finale.

==========================================================================
PUBLIC API
==========================================================================
    fetch_events(force_refresh=False) -> list[dict]
    is_blocked_now() -> (bool, str|None, datetime|None)         # eco only
    is_session_blocked() -> (bool, str|None)                    # session only
    is_blocked_combined() -> (bool, str|None, datetime|None)    # eco OR session
    today_events() -> list[dict]
    next_event_block() -> dict|None
    get_status() -> dict (pour endpoint API)
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Convention CME trading day : 18:00 ET J-1 -> 18:00 ET J (date de fin = trade date)
# Centralise dans CORE/constants.py (memoire feedback_config_centralise.md 17/04).
try:
    from constants import CME_DAY_ROLLOVER_HOUR_ET  # type: ignore
except ImportError:
    from CORE.constants import CME_DAY_ROLLOVER_HOUR_ET  # type: ignore

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")  # gere DST automatiquement
except ImportError as _zi_err:
    # FAIL LOUD (fix P1 code-reviewer 29/04 soir) : un fallback offset fixe
    # serait FAUX 6 mois/an au passage DST → bloquerait ou laisserait
    # passer 1h en plus/moins selon saison. Mieux vaut crash franc au boot
    # que corruption silencieuse de la logique session.
    raise ImportError(
        "zoneinfo required for eco_calendar.py (Python 3.9+). "
        f"Original error: {_zi_err}"
    )

ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "DATA" / "CALENDAR"
CACHE_FILE = CACHE_DIR / "ff_cache.json"
CACHE_TTL_SEC = 6 * 3600  # 6h

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FF_USER_AGENT = "Mozilla/5.0 (compatible; MIA-Bot/1.0)"

# Fenetres de blocage par impact (min avant / min apres)
BLOCK_WINDOWS = {
    "high": (15, 30),    # FOMC, NFP, CPI, PCE → -15/+30
    "medium": (0, 0),    # Pas de blocage par defaut
    "low": (0, 0),
    "holiday": (0, 0),
}

# Pays consideres comme impactants pour ES/NQ/RTY (futures US)
US_FUTURES_RELEVANT = {"USD"}

# Keywords pour identifier les events CRITIQUES affiches en rouge cote UI
# (parmi les High USD, ces events sont historiquement les plus volatils)
CRITICAL_KEYWORDS = [
    "FOMC", "Fed Chair", "Fed Funds Rate", "Federal Reserve",
    "Non-Farm Employment", "NFP", "Unemployment Rate",
    "CPI m/m", "Core CPI", "Core PCE Price Index", "PPI m/m",
    "GDP Advance", "Retail Sales m/m",
]


def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_age_sec() -> float:
    if not CACHE_FILE.exists():
        return float("inf")
    return time.time() - CACHE_FILE.stat().st_mtime


def _read_cache() -> Optional[list]:
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(events: list):
    _ensure_cache_dir()
    try:
        tmp = CACHE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False)
        tmp.replace(CACHE_FILE)
    except OSError:
        pass


def _download_ff() -> Optional[list]:
    """Download ForexFactory JSON. Return None on failure."""
    try:
        req = urllib.request.Request(FF_URL, headers={"User-Agent": FF_USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                return None
            data = r.read().decode("utf-8")
        events = json.loads(data)
        if not isinstance(events, list):
            return None
        return events
    except Exception:
        return None


def fetch_events(force_refresh: bool = False) -> list:
    """Retourne les events de la semaine courante.

    Strategie :
    1. Si force_refresh OR cache > TTL → tente download
    2. Si download OK → ecrit cache + return
    3. Sinon → lit cache (meme si vieux) → return
    4. Si pas de cache du tout → return []
    """
    use_cache = (not force_refresh) and _cache_age_sec() < CACHE_TTL_SEC
    if use_cache:
        cached = _read_cache()
        if cached is not None:
            return cached

    fresh = _download_ff()
    if fresh is not None:
        _write_cache(fresh)
        return fresh

    # Fallback : cache stale mieux que rien
    cached = _read_cache()
    return cached if cached is not None else []


def _parse_event_dt(ev: dict) -> Optional[datetime]:
    """Parse 'date' field ISO 8601 → aware datetime UTC."""
    raw = ev.get("date")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def _impact_normalized(ev: dict) -> str:
    return str(ev.get("impact", "")).strip().lower()


def _country_normalized(ev: dict) -> str:
    return str(ev.get("country", "")).strip().upper()


def is_critical(ev: dict) -> bool:
    """Event critique = High impact + USD + matching keyword critique."""
    if _impact_normalized(ev) != "high":
        return False
    if _country_normalized(ev) not in US_FUTURES_RELEVANT:
        return False
    title = ev.get("title", "")
    return any(kw.lower() in title.lower() for kw in CRITICAL_KEYWORDS)


def _is_blocking(ev: dict) -> bool:
    """Retourne True si l'event peut declencher un blocage trading."""
    if _country_normalized(ev) not in US_FUTURES_RELEVANT:
        return False
    impact = _impact_normalized(ev)
    return impact == "high"


def is_blocked_now(now_utc: Optional[datetime] = None) -> tuple[bool, Optional[str], Optional[datetime]]:
    """Verifie si on est dans la fenetre de blocage d'un event critique.

    Returns:
        (blocked: bool, reason: str | None, blocked_until_utc: datetime | None)
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    events = fetch_events()
    for ev in events:
        if not _is_blocking(ev):
            continue
        ev_dt = _parse_event_dt(ev)
        if ev_dt is None:
            continue
        impact = _impact_normalized(ev)
        before_min, after_min = BLOCK_WINDOWS.get(impact, (0, 0))
        block_start = ev_dt - timedelta(minutes=before_min)
        block_end = ev_dt + timedelta(minutes=after_min)
        if block_start <= now_utc <= block_end:
            return (True,
                    f"{ev.get('title','?')} ({_country_normalized(ev)})",
                    block_end)
    return (False, None, None)


def cme_trading_day_window(now_utc: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """Retourne (start_utc, end_utc) du CME trading day courant.

    CME trading day = 18:00 ET J-1 → 18:00 ET J (convention futures).
    Exemples (EDT, ET = UTC-4) :
      29/04 17:30 ET (21:30 UTC) → start=28/04 22:00 UTC / end=29/04 22:00 UTC
      29/04 22:30 ET (jeudi 02:30 UTC) → start=29/04 22:00 UTC / end=30/04 22:00 UTC

    FIX 30/04 (Jackson "session Asia jeudi 30") : avant on filtrait par
    date ET civile (ex 29/04 ET) mais a 22:30 ET mercredi le bot trade
    deja le CME day "20260430" (= session Asia + London + US RTH du 30).
    Cette fonction donne la window correspondante.
    """
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    et_dt = now.astimezone(_ET)
    if et_dt.hour >= CME_DAY_ROLLOVER_HOUR_ET:
        # On est apres 18:00 ET → CME day = aujourd'hui+1, start = aujourd'hui 18:00 ET
        start_et = et_dt.replace(hour=CME_DAY_ROLLOVER_HOUR_ET,
                                  minute=0, second=0, microsecond=0)
    else:
        # Avant 18:00 ET → CME day = aujourd'hui, start = hier 18:00 ET
        start_et = (et_dt - timedelta(days=1)).replace(
            hour=CME_DAY_ROLLOVER_HOUR_ET, minute=0, second=0, microsecond=0)
    end_et = start_et + timedelta(days=1)
    return (start_et.astimezone(timezone.utc), end_et.astimezone(timezone.utc))


def cme_trading_day_label(now_utc: Optional[datetime] = None) -> str:
    """Retourne YYYYMMDD du CME trading day courant (= date de FIN de session).

    Exemple : mercredi 22:30 ET → CME day "20260430" (= jeudi 30 avril).
    """
    _, end_utc = cme_trading_day_window(now_utc)
    # End = J 18:00 ET. La date du CME day = la date ET de end - 1 minute.
    return (end_utc.astimezone(_ET) - timedelta(minutes=1)).strftime("%Y%m%d")


# Constantes session window (ET, US Eastern)
# Standard trading sessions futures CME ES/NQ :
#  - Asia       : 18:00 ET J-1 → 03:00 ET J  (Tokyo + Hong Kong + Singapore)
#  - London     : 03:00 ET J   → 09:30 ET J  (Frankfurt + London)
#  - US RTH     : 09:30 ET J   → 16:00 ET J  (NYSE + NASDAQ cash)
#  - Close US   : 16:00 ET J   → 18:00 ET J  (close MOC + pause overnight)
SESSIONS = [
    ("Close US",  16, 0,  18, 0),   # 16:00-18:00 ET
    ("Asia",      18, 0,  24+3, 0), # 18:00 ET J-1 → 03:00 ET J (wrap)
    ("London",     3, 0,   9, 30),  # 03:00-09:30 ET
    ("US RTH",     9, 30, 16, 0),   # 09:30-16:00 ET
]


def current_session_label(now_utc: Optional[datetime] = None) -> str:
    """Retourne le label de la session futures CME courante.

    Returns: "Asia" | "London" | "US RTH" | "Close US"
    """
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    et_dt = now.astimezone(_ET)
    h, m = et_dt.hour, et_dt.minute
    cur_min = h * 60 + m
    # Asia wrap : 18:00 ET J-1 → 03:00 ET J = [1080, 1440) ∪ [0, 180)
    if cur_min >= 18 * 60 or cur_min < 3 * 60:
        return "Asia"
    if cur_min < 9 * 60 + 30:
        return "London"
    if cur_min < 16 * 60:
        return "US RTH"
    return "Close US"  # 16:00-18:00 ET


def today_events(now_utc: Optional[datetime] = None) -> list:
    """Retourne les events du CME trading day courant (18:00 ET J-1 → 18:00 ET J).

    FIX 30/04 (Jackson "session Asia jeudi 30 avril") : avant filtrage par
    date ET civile. A 22:30 ET mercredi (session Asia, CME day = jeudi 30/04),
    le calendrier affichait "29/04 ET" alors que le trader regarde la session
    en cours qui appartient au CME day "30/04". Maintenant filter par CME
    trading day window pour aligner avec ce que Bot 2 trade.

    Exemple : mercredi 22:30 ET (CME day = "20260430") retourne les events
    entre mercredi 18:00 ET et jeudi 18:00 ET = Asia + London + US RTH
    + Close US de la journee de trading 30/04.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    start_utc, end_utc = cme_trading_day_window(now_utc)
    events = fetch_events()
    today_evs = []
    for ev in events:
        ev_dt = _parse_event_dt(ev)
        if ev_dt is None:
            continue
        # Filter par window CME [start, end)
        if start_utc <= ev_dt < end_utc:
            today_evs.append({
                **ev,
                "ts_utc": ev_dt.isoformat(),
                "is_blocking": _is_blocking(ev),
                "is_critical": is_critical(ev),
            })
    today_evs.sort(key=lambda e: e["ts_utc"])
    return today_evs


def next_event_block(now_utc: Optional[datetime] = None) -> Optional[dict]:
    """Retourne le prochain event blocking (High USD) a venir."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    events = fetch_events()
    upcoming = []
    for ev in events:
        if not _is_blocking(ev):
            continue
        ev_dt = _parse_event_dt(ev)
        if ev_dt is None or ev_dt < now_utc:
            continue
        upcoming.append((ev_dt, ev))
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x[0])
    ev_dt, ev = upcoming[0]
    return {
        **ev,
        "ts_utc": ev_dt.isoformat(),
        "in_seconds": int((ev_dt - now_utc).total_seconds()),
        "is_critical": is_critical(ev),
    }


# ==========================================================================
# SECTION 2 — FENETRES DE SESSION STRUCTURELLES
# ==========================================================================
# Decisions Jackson 29/04/2026 soir.
# Toutes les heures sont en ET (America/New_York) pour gerer le DST
# automatiquement via zoneinfo.
#
# ATTENTION : NE PAS coder en heure Paris. Le passage ete/hiver decalerait
# tout 2 fois par an. ET avec zoneinfo = source de verite stable.
# ==========================================================================

# Fenetre A : volatilite ouverture US (open RTH NYSE/NASDAQ)
SESSION_OPEN_US = {
    "name": "open_us_volatility",
    "block_start_et": (9, 15),   # 09:15 ET = 15:15 Paris ete
    "block_end_et": (9, 45),     # 09:45 ET = 15:45 Paris ete
    "weekday_only": True,
    "label": "Open US volatilite",
}

# Fenetre B : pause post-MOC jusqu'a CME Asia futures open + buffer 15min
# 15:30 ET → 18:15 ET (= 21:30 Paris ete → 00:15 Paris ete du lendemain)
# Couvre : 30min MOC imbalance + 2h15 pause avant CME Asia session.
# PILOT 30 JOURS (Jackson 30/04) : avant block_end=21:30 ET (post Tokyo cash open),
# maintenant 18:15 ET (post CME Asia open). Review J+30 = 30/05/2026.
SESSION_CLOSE_US = {
    "name": "post_moc_to_asia",
    "block_start_et": (15, 30),  # 15:30 ET = 21:30 Paris ete
    "block_end_et": (18, 15),    # 18:15 ET = 00:15 Paris ete (lendemain) — CME Asia + 15min
    "weekday_only": False,       # actif aussi le weekend (recouvre dimanche)
    "label": "Post-MOC pause (jusqu'a CME Asia +15min)",
}

# Fenetre C : weekend (samedi entier + dimanche jusqu'a 18:15 ET CME Asia)
# Couverture complementaire a SESSION_CLOSE_US :
#  - Vendredi : SESSION_CLOSE_US bloque 15:30 → 18:15 ET MAIS le vendredi soir
#    le CME ferme totalement a 17:00 ET (pas de reopen avant dimanche). Donc
#    bloquer vendredi soir entier (ne pas s'arreter a 18:15).
#  - Samedi : entier bloque (CME ferme).
#  - Dimanche : bloque jusqu'a 18:15 ET (CME Asia Sun reopen + buffer 15min).
# Encode comme un booleen complet weekend_blocked() ci-dessous.


def _now_et(now_utc: Optional[datetime] = None) -> datetime:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    return now_utc.astimezone(_ET)


def _hm_in_window(hm: tuple, start: tuple, end: tuple) -> bool:
    """True si (h, m) est dans la fenetre [start, end). Wrap minuit non gere
    (les fenetres SESSION ci-dessus traversent minuit ET, traitement special
    dans is_session_blocked).
    """
    cur_min = hm[0] * 60 + hm[1]
    start_min = start[0] * 60 + start[1]
    end_min = end[0] * 60 + end[1]
    return start_min <= cur_min < end_min


def _is_weekend_blocked_et(et_dt: datetime) -> tuple[bool, Optional[str]]:
    """Verifie blocage weekend en ET.

    Logique :
    - Vendredi >= 15:30 ET → bloque (close US weekly, CME ferme jusqu'a dim soir)
    - Samedi entier → bloque (CME ferme)
    - Dimanche < 18:15 ET → bloque (avant CME Asia Sun reopen + buffer 15min)

    PILOT 30 JOURS (Jackson 30/04) : end Sunday 21:30 → 18:15 ET pour
    coherence avec fenetre B. Reprise CME Asia futures Sun 18:00 ET + buffer.
    """
    weekday = et_dt.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hm = (et_dt.hour, et_dt.minute)

    # Friday >= 15:30 ET (close US weekly)
    if weekday == 4 and (hm[0] > 15 or (hm[0] == 15 and hm[1] >= 30)):
        return (True, "Vendredi soir (close US weekly)")
    # Saturday : tout bloque
    if weekday == 5:
        return (True, "Samedi (CME ferme)")
    # Sunday avant 18:15 ET (CME Asia Sun reopen + 15min)
    if weekday == 6 and (hm[0] < 18 or (hm[0] == 18 and hm[1] < 15)):
        return (True, "Dimanche avant CME Asia +15min (18:15 ET)")
    return (False, None)


def is_session_blocked(now_utc: Optional[datetime] = None) -> tuple[bool, Optional[str]]:
    """Verifie blocage par fenetres structurelles (open US, close US, weekend).

    Returns:
        (blocked: bool, reason: str | None)
    """
    et_dt = _now_et(now_utc)
    weekday = et_dt.weekday()
    hm = (et_dt.hour, et_dt.minute)

    # 1. Weekend (samedi entier + vendredi soir + dimanche avant CME Asia)
    weekend_blocked, weekend_reason = _is_weekend_blocked_et(et_dt)
    if weekend_blocked:
        return (True, weekend_reason)

    # 2. Open US volatility 09:15 - 09:45 ET (lundi-vendredi)
    rule = SESSION_OPEN_US
    if (not rule["weekday_only"] or weekday < 5):
        if _hm_in_window(hm, rule["block_start_et"], rule["block_end_et"]):
            return (True, rule["label"])

    # 3. Post-MOC pause 15:30 - 18:15 ET (lundi-jeudi) — PILOT 30j Jackson 30/04
    # Lundi-jeudi seulement car vendredi gere par weekend_blocked au-dessus.
    if weekday < 4:
        rule = SESSION_CLOSE_US
        if _hm_in_window(hm, rule["block_start_et"], rule["block_end_et"]):
            return (True, rule["label"])

    return (False, None)


def is_blocked_combined(now_utc: Optional[datetime] = None) -> tuple[bool, Optional[str], Optional[datetime]]:
    """Verifie si bloque par EITHER eco event OR session structurelle.

    Returns:
        (blocked: bool, reason: str | None, blocked_until_utc: datetime | None)

    Priorite : eco event si actif (a une heure de fin precise), sinon
    session block (heure de fin precise calculee via _session_block_end_utc).

    FIX P1 code-reviewer 29/04 soir : capture `now_utc` une seule fois en
    haut pour eviter incoherence si le tick traverse une seconde entre les
    2 sub-calls (eco_blocked et session_blocked).

    FIX 30/04 (Jackson "ON AURAIS DU A VOIR UN TIMER") : retourner
    blocked_until_utc aussi pour les session blocks (pas seulement eco
    events) afin que le dashboard puisse afficher un timer "Bot reprend
    dans HH:MM".
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    eco_blocked, eco_reason, eco_until = is_blocked_now(now_utc)
    if eco_blocked:
        return (True, f"ECO: {eco_reason}", eco_until)
    sess_blocked, sess_reason = is_session_blocked(now_utc)
    if sess_blocked:
        sess_until = _session_block_end_utc(now_utc)
        return (True, f"SESSION: {sess_reason}", sess_until)
    return (False, None, None)


def _session_block_end_utc(now_utc: datetime) -> Optional[datetime]:
    """Calcule la fin UTC de la fenetre de session block courante.

    Retourne le prochain moment ou is_session_blocked() devient False.
    Logique speculaire de is_session_blocked() :
      - Open US 09:15-09:45 ET : fin = 09:45 ET aujourd'hui
      - Post-MOC 15:30-18:15 ET (lun-jeu) : fin = 18:15 ET aujourd'hui
      - Vendredi >= 15:30 ET : fin = dimanche 18:15 ET (CME Asia Sun + buffer)
      - Samedi : fin = dimanche 18:15 ET
      - Dimanche < 18:15 ET : fin = aujourd'hui 18:15 ET

    Returns datetime UTC du prochain unblock, ou None si calcul echoue.
    """
    et_dt = now_utc.astimezone(_ET)
    weekday = et_dt.weekday()  # 0=Mon ... 6=Sun
    hm = (et_dt.hour, et_dt.minute)

    # Helper : construire datetime ET (h, m) avec offset jours
    def _et_at(h: int, m: int, day_offset: int = 0) -> datetime:
        target = et_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if day_offset:
            target = target + timedelta(days=day_offset)
        return target.astimezone(timezone.utc)

    # Fenetre A : Open US 09:15-09:45 ET (lundi-vendredi uniquement)
    # FIX C1 code-reviewer 30/04 : simplification booleenne. La version
    # precedente avait `or (hm[0] == 9 and hm[1] >= 15)` qui rendait le
    # bloc externe vrai pour toute minute >= 09:15, masque par un inner
    # `if` correct mais logique morte = pattern 11 ("marche par hasard").
    if weekday < 5 and hm[0] == 9 and 15 <= hm[1] < 45:
        return _et_at(9, 45)

    # Vendredi soir / samedi / dimanche : reprise dimanche 18:15 ET (CME Asia + buffer)
    # Vendredi >= 15:30 ET
    if weekday == 4 and (hm[0] > 15 or (hm[0] == 15 and hm[1] >= 30)):
        return _et_at(18, 15, day_offset=2)  # vendredi+2 = dimanche
    # Samedi : reprise dimanche 18:15 ET
    if weekday == 5:
        return _et_at(18, 15, day_offset=1)
    # Dimanche < 18:15 ET : reprise aujourd'hui 18:15 ET
    if weekday == 6 and (hm[0] < 18 or (hm[0] == 18 and hm[1] < 15)):
        return _et_at(18, 15)

    # Fenetre B : Post-MOC 15:30-18:15 ET (lun-jeu, deja exclu vendredi)
    # PILOT 30 JOURS (Jackson 30/04) : end 21:30 → 18:15 ET (CME Asia + 15min)
    if weekday < 4:
        in_post_moc = (hm[0] > 15 or (hm[0] == 15 and hm[1] >= 30)) and \
                       (hm[0] < 18 or (hm[0] == 18 and hm[1] < 15))
        if in_post_moc:
            return _et_at(18, 15)

    return None


# ==========================================================================
# STATUS endpoint
# ==========================================================================

def get_status(now_utc: Optional[datetime] = None) -> dict:
    """Statut complet pour le dashboard.

    Returns:
        {
          "ts": iso_now,
          "blocked": bool,
          "block_reason": str | None,
          "blocked_until_utc": iso_str | None,
          "next_event": {...} | None,
          "today_events_count": int,
          "cache_age_sec": float,
        }
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    eco_blocked, eco_reason, eco_until = is_blocked_now(now_utc)
    sess_blocked, sess_reason = is_session_blocked(now_utc)
    blocked = eco_blocked or sess_blocked
    if eco_blocked:
        reason = f"ECO: {eco_reason}"
        until = eco_until
    elif sess_blocked:
        reason = f"SESSION: {sess_reason}"
        until = None
    else:
        reason = None
        until = None
    nxt = next_event_block(now_utc)
    return {
        "ts": now_utc.isoformat(),
        "blocked": blocked,
        "block_reason": reason,
        "blocked_until_utc": until.isoformat() if until else None,
        # Detail des sources
        "eco_blocked": eco_blocked,
        "eco_reason": eco_reason,
        "session_blocked": sess_blocked,
        "session_reason": sess_reason,
        "next_event": nxt,
        "today_events_count": len(today_events(now_utc)),
        "cache_age_sec": int(_cache_age_sec()) if CACHE_FILE.exists() else None,
    }


if __name__ == "__main__":
    # Smoke test
    print("=" * 60)
    print("  ECO CALENDAR SMOKE TEST")
    print("=" * 60)
    events = fetch_events()
    print(f"N events fetched : {len(events)}")
    if events:
        print(f"First event : {events[0]}")
    print(f"\nCache age : {_cache_age_sec():.0f}s")
    today = today_events()
    print(f"\nToday events ({len(today)}) :")
    for e in today:
        marker = " [CRITICAL]" if e.get("is_critical") else (" [BLOCK]" if e.get("is_blocking") else "")
        print(f"  {e['ts_utc'][11:16]} UTC {e.get('country','?'):3s} {e.get('impact','?'):8s} {e.get('title','?')}{marker}")
    print(f"\nStatus : {get_status()}")
