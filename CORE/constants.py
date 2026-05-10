"""Constantes partagees MIA Trading.

Source unique pour eviter les duplications (violation DRY audit 2026-04-09).
"""
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)


# ====================================================================
# CME TRADING DAY — convention futures
# ====================================================================
# CME E-mini ES/NQ trading day = 18:00 ET (jour J-1) → 17:00 ET (jour J)
# Trade date = date de FIN (convention CME).
#
# UTC equivalent :
#   - ETE  (mars-novembre, EDT)  : 18:00 ET = 22:00 UTC
#   - HIVER (novembre-mars, EST) : 18:00 ET = 23:00 UTC
#
# FIX audit 29/04 (R2) : utilisation `ZoneInfo("America/New_York")`
# native pour gerer DST automatiquement (avant : 22 UTC hardcoded =
# bug garanti au passage hiver 02/11/2026).
#
# Sans cette convention, le bot rollover sur UTC midnight (00:00 UTC) et
# loggue dans 20260428_*.jsonl meme apres l'ouverture Asia (18:00 ET),
# donnant une vision biaisee du PnL "session" (incident Jackson 28/04 22:30 UTC).

CME_TZ = ZoneInfo("America/New_York")  # ET — reference futures CME ES/NQ
CME_DAY_ROLLOVER_HOUR_ET: int = 18     # 18:00 ET = ouverture CME daily session


def get_cme_trading_day(now_utc: datetime | None = None) -> str:
    """Retourne la trading day CME au format YYYYMMDD (DST-aware).

    Si l'heure ET >= 18:00, on est dans le trading day du JOUR SUIVANT
    (convention CME : trade date = date de fin de session).

    Exemples (heure d'ete EDT, ET = UTC-4) :
      28/04 17:30 ET (21:30 UTC) → "20260428"
      28/04 18:00 ET (22:00 UTC) → "20260429"  (bascule)
      29/04 17:30 ET (21:30 UTC) → "20260429"
      29/04 18:00 ET (22:00 UTC) → "20260430"

    Hiver EST (ET = UTC-5) : 18:00 ET = 23:00 UTC (geree par zoneinfo).
    """
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    now_et = now.astimezone(CME_TZ)
    if now_et.hour >= CME_DAY_ROLLOVER_HOUR_ET:
        return (now_et + timedelta(days=1)).strftime("%Y%m%d")
    return now_et.strftime("%Y%m%d")


# Tick size par instrument (ES, NQ, MGC micros)
# MGC ajoute 09/05/2026 : tick = 0.10 (vs 0.25 ES/NQ) — Gold structure differente
TICK_SIZE: dict[str, float] = {
    "ES": 0.25,
    "NQ": 0.25,
    "MGC": 0.10,
}

# Valeur d'un tick en USD (pour P&L)
# MGC : 1 tick = $1.00 (Micro Gold = 10 onces troy * $0.10)
TICK_VALUE: dict[str, float] = {
    "ES": 1.25,   # Micro ES : $1.25/tick
    "NQ": 0.50,   # Micro NQ : $0.50/tick
    "MGC": 1.00,  # Micro Gold : $1.00/tick (10oz troy * 0.10)
}

# Default tick size pour code generique (ES + NQ ont le meme)
# MGC est l'exception (0.10) — toujours utiliser get_tick_size("MGC") pour le Gold
DEFAULT_TICK_SIZE: float = 0.25


# ====================================================================
# SYMBOL_TO_FS_DIR — Mapping symbole Python → dossier filesystem (10/05/2026)
# ====================================================================
# Source unique de verite pour le mapping symbole-Python ↔ dossier filesystem.
# Necessaire car certains contrats Micro (MGC) partagent les chartbooks Sierra
# du contrat Standard (GC). MenthorQ ne distingue pas Micro/Standard pour les
# niveaux options-driven (memes call_resistance, put_support, hvl).
#
# Regle Lecons.md (centralisation duplique 5x avec TICK_SIZE) :
# UTILISER get_fs_dir(symbol) au lieu de mapper inline `if symbol == 'MGC'`.
#
# Exemples :
#   get_fs_dir("ES")  -> "ES"
#   get_fs_dir("MGC") -> "GC"   (chart Sierra basee sur ticker GC)
#   get_fs_dir("MNQ") -> "NQ"   (Micro NQ partage chart NQ — futur)
SYMBOL_TO_FS_DIR: dict[str, str] = {
    "ES": "ES",
    "NQ": "NQ",
    "MGC": "GC",   # 10/05/2026 : chart Sierra GCM26-COMEX, study MQ_Lite GC
    # "MNQ": "NQ",  # futur
    # "MES": "ES",  # futur
}


def get_fs_dir(symbol: str) -> str:
    """Retourne le dossier filesystem (DATA/mq_levels/, DATA/<sym>/...) pour un symbole.

    Fail-loud si symbole inconnu.
    """
    sym = symbol.upper()
    if sym not in SYMBOL_TO_FS_DIR:
        _logger.warning(
            "get_fs_dir: symbole inconnu '%s' — fallback identite. "
            "Ajouter une entree SYMBOL_TO_FS_DIR['%s'] dans constants.py.",
            symbol, sym,
        )
        return sym
    return SYMBOL_TO_FS_DIR[sym]


def get_mq_json_key(symbol: str) -> str:
    """Retourne la cle dans les fichiers JSON MenthorQ (YYYYMMDD_menthorq_complete.json).

    Le scraper produit data["GC"] / data["GC_swing"] / data["GC_intraday"] pour
    le Gold (MenthorQ ne distingue pas Micro vs Standard). Mapping identique
    a get_fs_dir() : MGC -> GC, ES -> ES, NQ -> NQ.

    Helper dedie pour clarifier l'intention : cle JSON != dossier filesystem
    par essence, meme si les valeurs coincident actuellement.
    """
    return get_fs_dir(symbol)


# ====================================================================
# SESSION BOUNDARIES PER SYMBOL — Chantier 4 (10/05/2026)
# ====================================================================
# Sessions de trading par instrument (mins ET = minutes since midnight ET).
# ES/NQ : convention equity NYSE/Nasdaq. MGC : convention COMEX gold.
#
# Cause racine du Chantier 4 : avant 10/05/2026, sessions hardcodees ES dans
# sessions_swings_engine.py (US Cash 09:30-16:00). Sur MGC, ca causait :
# - cash_high/low : 71.9% NaN (filtre RTH 09:30-16:00 trop tard pour Gold)
# - us_* features : 67.6% NaN
# - london : 39.4% NaN (incoherent avec liquidite Gold London)
# - ovn : 40.6% NaN (concept overnight equity inadapte Gold)
#
# Fix : SESSION_BOUNDARIES_BY_SYMBOL[symbol] dispatch per-instrument.
SESSION_BOUNDARIES_BY_SYMBOL: dict[str, dict[str, int]] = {
    "ES": {
        "asia_start":     18 * 60,         # 18:00 ET (re-ouverture Globex)
        "london_start":    3 * 60,         # 03:00 ET (LDN cash open)
        "us_start":        9 * 60 + 30,    # 09:30 ET (NYSE cash open)
        "us_after_start": 16 * 60,         # 16:00 ET (NYSE close)
    },
    "NQ": {  # Identique ES (NYSE/Nasdaq mêmes horaires equity)
        "asia_start":     18 * 60,
        "london_start":    3 * 60,
        "us_start":        9 * 60 + 30,
        "us_after_start": 16 * 60,
    },
    "MGC": {  # COMEX gold : RTH 08:30-13:30 ET, Asia gold 19:00 ET (TOCOM/SHFE)
        "asia_start":     19 * 60,         # 19:00 ET (Asian gold open)
        "london_start":    3 * 60,         # 03:00 ET (London Bullion AM)
        "us_start":        8 * 60 + 30,    # 08:30 ET (COMEX RTH gold open)
        "us_after_start": 13 * 60 + 30,    # 13:30 ET (COMEX settle, after-hours)
        # Note : MGC a aussi pause maintenance 17:00-18:00 ET, geree par Globex.
        # Asia start 19:00 vs ES 18:00 = liquidite Gold demarre 1h plus tard.
    },
}


# ====================================================================
# DATABENTO CONTINUOUS TICKER PER SYMBOL — Chantier 5bis (10/05/2026)
# ====================================================================
# `MGC.c.0` (date-based front-month rollover) a un bug Databento : tronque
# 50-99% des bars sur les mois d'expiration GC futures (jun, aug, oct, dec,
# fev, avr). Verification empirique 02/06/2025 :
#   MGC.c.0 = 49 bars  (vs 1380 attendus, -97%)
#   MGC.v.0 = 1380 bars (volume-based rollover, OK)
#   MGC.n.0 = 1380 bars (open-interest based, OK)
# ES/NQ : MGC.c.0 fonctionne correctement (rollover March/Jun/Sep/Dec quarterly).
# Decision design : Gold = .v.0, ES/NQ = .c.0.
SYMBOL_TO_DATABENTO_TICKER: dict[str, str] = {
    "ES":  "ES.c.0",   # quarterly rollover, pas de bug observe
    "NQ":  "NQ.c.0",   # idem
    "MGC": "MGC.v.0",  # volume-based, evite bug rollover GC futures monthly
}


def get_databento_ticker(symbol: str) -> str:
    """Retourne le ticker Databento continuous pour un symbole.

    Fail-loud : warning + fallback `{sym}.c.0` si symbole inconnu, mais loggue
    visiblement pour qu'un test/audit puisse detecter l'usage (anti silent fallback).
    Pour les contrats avec rollover MENSUEL (Gold, Silver), `.c.0` peut etre
    bugue (cf lessons.md). Ajouter explicitement dans SYMBOL_TO_DATABENTO_TICKER
    pour ces cas.
    """
    sym = symbol.upper()
    if sym not in SYMBOL_TO_DATABENTO_TICKER:
        _logger.warning(
            "get_databento_ticker: symbole inconnu '%s' — fallback '%s.c.0'. "
            "Ajouter SYMBOL_TO_DATABENTO_TICKER['%s'] dans constants.py si "
            "rollover mensuel (.v.0 ou .n.0 recommande).",
            symbol, sym, sym,
        )
        return f"{sym}.c.0"
    return SYMBOL_TO_DATABENTO_TICKER[sym]


def get_session_boundaries(symbol: str) -> dict[str, int]:
    """Retourne les bornes de sessions (mins ET) pour un symbole.

    Fail-loud si symbole inconnu (anti silent fallback).

    Returns:
        dict avec keys: asia_start, london_start, us_start, us_after_start
        (toutes en mins depuis minuit ET).
    """
    sym = symbol.upper()
    if sym not in SESSION_BOUNDARIES_BY_SYMBOL:
        _logger.warning(
            "get_session_boundaries: symbole inconnu '%s' — fallback ES (NYSE 09:30 RTH). "
            "Ajouter SESSION_BOUNDARIES_BY_SYMBOL['%s'] dans constants.py.",
            symbol, sym,
        )
        return SESSION_BOUNDARIES_BY_SYMBOL["ES"]
    return SESSION_BOUNDARIES_BY_SYMBOL[sym]

# Schema DMP version courante
DMP_SCHEMA_VERSION: str = "3.7.2"
DMP_SCHEMA_COLS: int = 262


# ====================================================================
# FEATURE FLAGS — desactivation runtime sans modifier le code metier
# ====================================================================

# 🔴 P0 SECURITE 01/05/2026 — TRAILING TR40 NQ DESACTIVE
# Raison : trailing update virtual `pos["sl_price"]` SEULEMENT en memoire,
#   PAS de cancel+replace broker (TODO ligne 1792 mia_paper_trader.py jamais code).
#   Consequence : state.json / SC desync. Trade NQ SHORT 01/05 : state.sl=27540.50
#   alors que broker SL = 27570.25. Backtest PF 0.99->1.32 = mensonge statistique
#   (calcule sur simu, pas fills broker reels).
# Re-activer SEULEMENT apres implementation cancel+replace via DTC + tests Sim2.
# Cf REFACTO Chemin B (DOCS/ORDER_LIFECYCLE_CONTRACT.md).
TRAILING_TR40_NQ_ENABLED: bool = False  # 01/05/2026 P0 disable

# ── ROLLING FEATURES seuils (centralises 18/04/2026 audit code-reviewer) ──
# Avant : seuils absolus hardcodes dans rolling_features.py (risque feature morte
# sur sessions calmes NQ Asia/pre-FOMC avec delta_bar median ~10-15).
# Apres : seuils relatifs multipliant un rolling_std(delta_bar, 50).
INSTANT_ABSORPTION_DELTA_K: float = 1.5   # multiplicateur rolling_std(delta_bar, 50)
INSTANT_ABSORPTION_WINDOW: int = 50       # bars de lookback pour rolling_std


def get_tick_size(symbol: str) -> float:
    """Retourne le tick size d'un instrument.

    Fail-loud si symbole inconnu (anti silent fallback — interdit lessons.md).
    """
    sym = symbol.upper()
    if sym not in TICK_SIZE:
        _logger.warning(
            "get_tick_size: symbole inconnu '%s' — fallback DEFAULT %s. "
            "Ajouter une entree TICK_SIZE['%s'] dans constants.py.",
            symbol, DEFAULT_TICK_SIZE, sym,
        )
        return DEFAULT_TICK_SIZE
    return TICK_SIZE[sym]


def get_tick_value(symbol: str) -> float:
    """Retourne la valeur d'un tick en USD.

    Fail-loud si symbole inconnu (anti silent fallback — interdit lessons.md).
    Avant 09/05/2026 : fallback silencieux 1.25 (= ES) sans warning, piege en cas
    de nouvel instrument. Maintenant log warning + fallback explicite.
    """
    sym = symbol.upper()
    if sym not in TICK_VALUE:
        _logger.warning(
            "get_tick_value: symbole inconnu '%s' — fallback ES (1.25) USD. "
            "Ajouter une entree TICK_VALUE['%s'] dans constants.py.",
            symbol, sym,
        )
        return 1.25
    return TICK_VALUE[sym]


# ====================================================================
# CONTRACT SPECS — MGC Micro Gold (ajoute 09/05/2026)
# ====================================================================
# Tick size      : 0.10 (vs 0.25 ES/NQ)
# Tick value     : $1.00 (Micro 10oz Gold)
# Sessions       : 23h/24 (lun 18:00 ET → ven 17:00 ET, 1h pause maintenance)
# Liquidite      : ~5x moins que ES (vol jour MGC ~376k vs ES ~2M)
# Plage prix     : ~$4700/oz (mai 2026), tick MGC = 0.0021% prix vs ES 0.0043%
#                  -> distances en ticks doivent etre ~2x plus larges qu'ES
#                     pour meme % move (ATR plus volatile en ticks)
# Symbole live   : MGCM26-CMECOMEX (avr→jun 2026), front contract roulant
# Dataset Databento : MGC.c.0 (continuous front-month, GLBX.MDP3)
# Plan Standard couvre : ohlcv-1m toute histoire + trades 12 mois roulants

# Plage horaire RTH MGC (COMEX gold) en heure ET (DST-aware via ZoneInfo)
# Avant 09/05/2026 : entiers UTC hardcodes (bug DST garanti au passage hiver/ete)
# Apres : objets time() + helper qui retourne datetime UTC dynamiquement
# Pattern aligne sur get_cme_trading_day() pour CME_TZ (audit 29/04 R2)
MGC_RTH_OPEN_ET: time = time(8, 30)   # 08:30 ET (open COMEX RTH gold)
MGC_RTH_CLOSE_ET: time = time(13, 30)  # 13:30 ET (close COMEX RTH gold, settle)


def is_in_mgc_rth(now_utc: datetime | None = None) -> bool:
    """Retourne True si l'instant courant est dans le RTH MGC (08:30-13:30 ET).

    DST-aware : utilise ZoneInfo("America/New_York") pour gerer EDT/EST automatiquement.
    Filtre weekend (sat/sun) ou COMEX ferme. Holidays COMEX (Memorial Day,
    Labor Day, Thanksgiving, Christmas, July 4) NON geres pour l'instant —
    a ajouter via un calendar package (pandas_market_calendars) en V2 si
    la fonction est utilisee pour gater des trades en prod.

    Args:
        now_utc: instant a tester (UTC). Si None, utilise datetime.now(timezone.utc).

    Returns:
        True si dans la fenetre RTH gold COMEX (jour business), False sinon.
    """
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    now_et = now.astimezone(CME_TZ)
    if now_et.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    return MGC_RTH_OPEN_ET <= now_et.time() < MGC_RTH_CLOSE_ET
