"""Fonctions de lecture des donnees MIA depuis les fichiers JSONL et JSON.

Contient les helpers partages, constantes de labels et fonctions read_*.
"""
import json
import logging
import os
from datetime import datetime
from glob import glob

from DASHBOARD.config import DASHBOARD_JSON, DATA_DIR

logger = logging.getLogger(__name__)

TICK_SIZE = 0.25  # ES et NQ micro futures

# ═══════════════════════════════════════════════════════════════
# Labels
# ═══════════════════════════════════════════════════════════════

OPEN_TYPE_LABELS = {
    0: "UNKNOWN", 1: "OD UP", 2: "OD DOWN", 3: "OTD UP", 4: "OTD DOWN",
    5: "ORR UP", 6: "ORR DOWN", 7: "OAIR", 8: "OAOR UP", 9: "OAOR DOWN",
    10: "ODF UP", 11: "ODF DOWN",
}

DAY_TYPE_LABELS = {
    0: "NON TREND", 1: "NORMAL", 2: "NORM VARIATION", 3: "NEUTRAL", 4: "TREND",
}

PROFILE_SHAPE_LABELS = {
    0: "D-Shape", 1: "P-Shape", 2: "b-Shape", 3: "Double Dist",
}

RVOL_REGIME_LABELS = {0: "Low", 1: "Normal", 2: "High", 3: "Spike", 4: "Extreme"}

VIX_REGIME_LABELS = {0: "LOW", 1: "NORMAL", 2: "HIGH"}

SESSION_LABELS = {0: "Closed", 1: "Asia", 2: "London", 3: "US"}


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def get_field(bar: dict, field: str, default: float = 0.0) -> float:
    """Extrait un champ numerique avec fallback. Gere None et 'INVALID'."""
    val = bar.get(field, default)
    if val is None or val == "INVALID":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def get_nullable_field(bar: dict, field: str):
    """Extrait un champ numerique ou None (pour features avec sentinel null JSONL).

    A utiliser pour les features qui peuvent legitimement etre null dans le
    JSONL (ex: va_position_pct, ib_position_pct hors range post fix 16/04/2026).
    Le frontend JS gere null via fmtPct/fmtNum qui affichent "--".
    Retourne None si absent, None, 'INVALID', NaN, ou non convertible.
    """
    val = bar.get(field, None)
    if val is None or val == "INVALID":
        return None
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (ValueError, TypeError):
        return None


def get_int_field(bar: dict, field: str, default: int = 0) -> int:
    """Extrait un champ entier avec fallback."""
    val = bar.get(field, default)
    if val is None or val == "INVALID":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def get_str_field(bar: dict, field: str, default: str = "") -> str:
    """Extrait un champ texte avec fallback."""
    val = bar.get(field, default)
    if val is None or val == "INVALID":
        return default
    return str(val)


def dist_to_price(bar: dict, dist_field: str) -> float | None:
    """Convertit une distance en ticks vers un prix absolu.

    price + distance_ticks * TICK_SIZE
    Retourne None si la distance est nulle/invalide.
    """
    price = get_field(bar, "price", 0.0)
    if price == 0.0:
        return None
    val = bar.get(dist_field)
    if val is None or val == "INVALID":
        return None
    try:
        dist = float(val)
    except (ValueError, TypeError):
        return None
    return round(price + dist * TICK_SIZE, 2)


def vix_dist_to_price(bar: dict, dist_field: str) -> float | None:
    """Convertit une distance VIX en prix VIX absolu.

    VIX distances sont en points directs (pas en ticks).
    """
    vix = get_field(bar, "vix_level", 0.0)
    if vix == 0.0:
        return None
    val = bar.get(dist_field)
    if val is None or val == "INVALID":
        return None
    try:
        dist = float(val)
    except (ValueError, TypeError):
        return None
    return round(vix + dist, 2)


def rvol_to_regime(rvol: float) -> int:
    """Calcule le regime RVOL depuis la valeur brute."""
    if rvol < 0.5:
        return 0
    if rvol < 1.0:
        return 1
    if rvol < 2.0:
        return 2
    if rvol < 3.0:
        return 3
    return 4


# ═══════════════════════════════════════════════════════════════
# Sources de donnees
# ═══════════════════════════════════════════════════════════════


def get_latest_jsonl(symbol: str) -> str | None:
    """Trouve le fichier JSONL le plus recent par mtime."""
    pattern = os.path.join(DATA_DIR, symbol, f"*_{symbol}.jsonl")
    files = glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def read_bot_status() -> dict:
    """Lit le JSON de statut du bot. Retourne squelette offline si perime.

    FIX 30/04 v4 (Jackson "BOTS PAS LANCES — STANDBY") : le legacy V1
    `MIA_AutoTrader_Dashboard.json` n'est plus ecrit (mtime 04/04, last_hb
    janvier 2026 = 3 mois) → tout dashboard affichait "STANDBY" alors que
    Bot 1 V2 tourne. Fallback sur Bot 1 state.json (V2) qui est ecrit
    toutes les 30s par mia_paper_trader heartbeat.
    """
    # Tentative 1 : DASHBOARD_JSON (legacy V1, peut etre perime)
    legacy_data = None
    if os.path.exists(DASHBOARD_JSON):
        try:
            with open(DASHBOARD_JSON, "r", encoding="utf-8") as f:
                legacy_data = json.load(f)
            hb = legacy_data.get("bot_status", {}).get("last_heartbeat", "")
            if hb:
                try:
                    hb_time = datetime.strptime(hb, "%Y-%m-%d %H:%M:%S")
                    age_sec = (datetime.now() - hb_time).total_seconds()
                    if age_sec <= 86400:
                        return legacy_data  # legacy frais → utiliser direct
                    logger.warning("Dashboard legacy JSON perime: heartbeat %s "
                                   "(age %.0f sec) → fallback state.json V2", hb, age_sec)
                except ValueError:
                    pass
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Erreur lecture dashboard legacy JSON: %s", exc)

    # Tentative 2 : Bot 1 V2 state.json (mia_paper_trader, ecrit toutes 30s)
    state_path = os.path.join(DATA_DIR, "PAPER_TRADES", "state.json")
    if os.path.exists(state_path):
        try:
            mtime = os.path.getmtime(state_path)
            age_sec = (datetime.now().timestamp() - mtime)
            if age_sec <= 120:  # state.json frais (mia_paper_trader heartbeat 30s)
                return _build_v2_bot_status_from_state(state_path)
            logger.warning("Bot 1 state.json perime (age %.0fs > 120s)", age_sec)
        except OSError as exc:
            logger.error("Erreur lecture state.json V2: %s", exc)

    # Fallback offline
    return _build_offline_bot_status()


def _build_v2_bot_status_from_state(state_path: str) -> dict:
    """Construit un bot_status compatible legacy V1 depuis Bot 1 V2 state.json.

    Mapping :
        running        : True si state.json mtime < 120s (heartbeat actif)
        global_status  : "ACTIF — V2 paper trading" / "EN POSITION" / "PAUSE eco"
        last_heartbeat : updated_iso de state.json
        es/nq stats    : derives de state.stats_today + open_by_symbol
    """
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Erreur parse state.json V2: %s", exc)
        return _build_offline_bot_status()

    open_by_symbol = state.get("open_by_symbol") or {}
    stats_by_symbol = state.get("stats_by_symbol") or {}
    closed_today = state.get("closed_today") or []

    # Heartbeat ISO
    updated_iso = state.get("updated_iso", "")
    if updated_iso:
        try:
            hb_dt = datetime.fromisoformat(updated_iso.replace("Z", "+00:00"))
            hb_str = hb_dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            hb_str = ""
    else:
        hb_str = ""

    # Status global
    in_position = bool(open_by_symbol)
    kill = state.get("kill_switch", {})
    if kill.get("active"):
        global_status = "KILL SWITCH ACTIVE"
    elif in_position:
        n_pos = len(open_by_symbol)
        global_status = f"EN POSITION ({n_pos})"
    else:
        global_status = "ACTIF — V2 paper trading"

    # Per-symbol stats
    def _build_instr_v2(sym: str) -> dict:
        s = stats_by_symbol.get(sym, {}) or {}
        n_trades = s.get("trades", 0)
        n_wins = s.get("wins", 0)
        n_losses = s.get("losses", 0)
        pnl = s.get("pnl_usd", 0.0)
        return {
            "enabled": True,
            "in_position": sym in open_by_symbol,
            "status": "Active" if sym in open_by_symbol else "Wait signal",
            "trades_today": n_trades,
            "wins": n_wins,
            "losses": n_losses,
            "pnl_today": pnl,
            "consecutive_losses": 0,
            "last_rejected": "",
            "signals_rejected": 0,
        }

    return {
        "bot_status": {
            "running": True,
            "global_status": global_status,
            "last_heartbeat": hb_str,
            "schema_source": "v2_state_json",  # observability
        },
        "es": _build_instr_v2("ES"),
        "nq": _build_instr_v2("NQ"),
        "schedule": {"current_session": "US", "next_event": ""},
        "warnings": {"news_detected": False, "news_message": ""},
        "market_live": {},
    }


def _build_offline_bot_status() -> dict:
    """Squelette quand le bot n'ecrit pas de JSON."""
    instr = {
        "enabled": False, "in_position": False, "status": "Bot offline",
        "trades_today": 0, "wins": 0, "losses": 0, "pnl_today": 0.0,
        "consecutive_losses": 0, "last_rejected": "", "signals_rejected": 0,
    }
    return {
        "bot_status": {
            "running": False,
            "global_status": "OFFLINE — Bot non deploye",
            "last_heartbeat": "",
        },
        "es": {**instr},
        "nq": {**instr},
        "schedule": {"current_session": "N/A", "next_event": ""},
        "warnings": {"news_detected": False, "news_message": ""},
        "market_live": {},
    }


# FIX 11/05/2026 (defense en profondeur bug DMP C++ Phase A2 GC) :
# Le DMP C++ DMP_Main.cpp:215 est hardcoded binaire ES/NQ
# (`sym_name = is_nq ? "NQ" : "ES"`). Si l'etude DMP est attachee a un chart
# non-NQ (ex: chart MGC Gold ajoute 09/05), elle ecrit ses bars dans
# DATA/ES/{date}_ES.jsonl avec sym=ES mais contract=GCM26-COMEX et prix Gold.
# -> banner.es.price = prix Gold (~4700) au lieu de prix ES (~7400)
# -> Bot 1 check_exit declenche TP/SL fantome
# Fix : filtrer par contract attendu, skip les lignes cross-symbol.
# Cf audit code-reviewer 11/05/2026 + DOCS/INCIDENT_LOG.md.
EXPECTED_CONTRACT = {
    # ROLLOVER 15/06/2026 : Jackson rollover Sierra Chart M26 -> U26
    # (Jun 2026 -> Sep 2026). DMP brut + sierra_enriched ecrivent U26.
    # Avant fix : filtre cross-symbol skip TOUTES bars -> banner={price:0}
    # -> Bot 1 reçoit data vide -> heartbeat fallback 99999 + 0 trade.
    "ES": "ESU26-CME",
    "NQ": "NQU26-CME",
    # 11/05 J2b — MGC integration foundation
    # MGC = Micro Gold COMEX, contract front-month. Calendar Gold = bi-mensuel
    # (jun, aug, oct, dec, feb, apr). M26 (juin) -> Q26 (aout) au rollover Gold.
    # A reverifier quand Jackson rolloverra Sierra Chart MGC (FND ~ avant-dernier
    # business day juin 2026).
    "MGC": "MGCM26-COMEX",
    # Note rollover : ES/NQ quarterly (Mar/Jun/Sep/Dec).
    # MGC bi-mensuel (jun, aug, oct, dec, feb, apr) — cf CORE/constants.py.
}


def _read_live_cache_minimal(symbol: str) -> dict:
    """11/05 J2b MGC : fallback LIVE_CACHE Databento pour symboles sans DMP JSONL.

    Le DMP C++ est hardcoded ES/NQ binary (BACKLOG : refactor Input symbol string).
    MGC n'a pas de DATA/MGC/*.jsonl mais a DATA/LIVE_CACHE/{sym}_v_0_last.json
    alimente par service MIA-Live-OHLCV (databento_live_stream.py).

    Retourne un bar dict minimal (OHLC + volume + ts) compatible builders qui
    lisent via get_field/dist_to_price (champs absents -> 0 default, no crash).

    11/05 J2c FIX B1 (code-reviewer) : ts retourne ms INT (pas ISO string).
    Sans ce fix, banner.mgc.ts_ms = string ISO -> consommateurs Bot/frontend
    qui font `now_ms - bar_ts_ms` lèvent TypeError (incident pattern 08/05).
    Source unique : aligne sur convention DMP JSONL bars (ts = ms int).

    11/05 J2c FIX I4 (code-reviewer) : utilise CORE/constants.get_databento_ticker
    au lieu de hardcoder ticker_map. Anti-pattern V1 "TICK_SIZE duplique 5x".
    """
    try:
        import os.path as _osp
        import json as _json
        from datetime import datetime as _dt
        # Source unique resolution ticker (.c.0 ES/NQ, .v.0 MGC).
        try:
            from CORE.constants import get_databento_ticker
            ticker_full = get_databento_ticker(symbol)  # "MGC.v.0", "ES.c.0", etc.
        except (ImportError, KeyError, ValueError):
            ticker_full = f"{symbol.upper()}.c.0"
        # LIVE_CACHE filename = ticker avec dots remplaces par underscores + "_last"
        ticker_filename = ticker_full.replace(".", "_") + "_last"
        cache_path = _osp.join(
            _osp.dirname(_osp.dirname(_osp.dirname(_osp.abspath(__file__)))),
            "DATA", "LIVE_CACHE", f"{ticker_filename}.json"
        )
        if not _osp.exists(cache_path):
            logger.debug("LIVE_CACHE absent pour %s : %s", symbol, cache_path)
            return {}
        with open(cache_path, "r", encoding="utf-8") as f:
            live = _json.load(f)
        # Convert ts_event_iso -> ts_ms int (compat DMP JSONL convention).
        ts_iso = live.get("ts_event_iso", "")
        ts_ms = 0
        if ts_iso:
            try:
                _dt_obj = _dt.fromisoformat(ts_iso.replace("Z", "+00:00"))
                ts_ms = int(_dt_obj.timestamp() * 1000)
            except (ValueError, TypeError) as exc:
                logger.warning("LIVE_CACHE ts parse fail %s: %s", symbol, exc)
        # 11/05 J2c FIX I7 (code-reviewer round 2) : staleness check LIVE_CACHE.
        # Si service MIA-Live-OHLCV down, le fichier reste mais ts vieillit.
        # Sans check, banner MGC afficherait prix d'il y a 30+ min sans alerte.
        # Seuil 5 min = generosite (Databento live latence cible 60s).
        # Marque `_stale=True` pour que frontend puisse badger "data ancienne".
        _is_stale = False
        age_sec = 0.0
        if ts_ms > 0:
            try:
                from datetime import timezone as _tz_utc
                age_sec = (_dt.now(_tz_utc.utc).timestamp() * 1000 - ts_ms) / 1000
                if age_sec > 300:  # 5 min seuil
                    _is_stale = True
                    logger.warning(
                        "LIVE_CACHE %s stale : age=%.0fs > 300s (service MIA-Live-OHLCV down ?)",
                        symbol, age_sec,
                    )
            except (ValueError, TypeError):
                pass
        # Adapter format LIVE_CACHE -> format bar_dict legacy (compat builders).
        return {
            "ts": ts_ms,                # INT ms (compat DMP JSONL bars)
            "ts_event": ts_iso,         # ISO string (debug + V4 staleness check)
            "open": live.get("open"),
            "high": live.get("high"),
            "low": live.get("low"),
            "close": live.get("close"),
            "volume": live.get("volume", 0),
            "price": live.get("close"),  # alias utilise par builders
            "symbol": symbol.upper(),
            "_source": "LIVE_CACHE_DATABENTO",  # marker pour audit
            "_stale": _is_stale,        # I7 : frontend peut badger "data ancienne"
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {}


def read_last_bar(symbol: str) -> dict:
    """Lit la derniere ligne du JSONL en partant de la fin (rapide).

    FIX 11/05 (defense bug DMP C++ cross-symbol contamination) :
    Skip les lignes ou bar.contract != EXPECTED_CONTRACT[symbol].

    11/05 J2b MGC : si DMP JSONL absent (cas MGC, DMP C++ hardcoded ES/NQ),
    fallback automatique sur LIVE_CACHE Databento (websocket temps reel).
    """
    path = get_latest_jsonl(symbol)
    if not path:
        # 11/05 J2b : fallback LIVE_CACHE pour symboles sans DMP JSONL (MGC).
        # ES/NQ ne tombent JAMAIS dans ce fallback (DMP JSONL toujours present).
        return _read_live_cache_minimal(symbol)
    expected = EXPECTED_CONTRACT.get(symbol.upper())
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)  # fin du fichier
            size = f.tell()
            # Lire les derniers 64KB max (anti-pollution : ouvre fenetre + large
            # pour scanner plusieurs bars si les dernieres sont polluees Gold).
            chunk = min(size, 65536)
            f.seek(size - chunk)
            data = f.read().decode("utf-8", errors="replace")
        lines = data.strip().split("\n")
        for line in reversed(lines):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                bar = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            # Filtre cross-symbol contamination
            if expected:
                bar_contract = bar.get("contract", "")
                if bar_contract and bar_contract != expected:
                    # Bar pollue (ex: GCM26-COMEX ecrit dans DATA/ES/)
                    continue
            return bar
        return {}
    except OSError as exc:
        logger.error("Erreur lecture derniere barre %s: %s", symbol, exc)
        return {}


def read_bars(symbol: str, n: int = 200) -> list[dict]:
    """Lit les N dernieres barres OHLC + niveaux depuis le JSONL le plus recent.

    Retourne une liste de dicts {time, open, high, low, close, volume, levels}.
    Optimise : lit le fichier une fois, garde les N dernieres lignes.
    """
    path = get_latest_jsonl(symbol)
    if not path:
        return []
    try:
        lines = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
        # Garder les N dernieres
        lines = lines[-n:]
        bars = []
        for line in lines:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("ts")
            if not ts:
                continue
            price = get_field(d, "price", 0.0)
            bar_high = get_field(d, "bar_high", price)
            bar_low = get_field(d, "bar_low", price)
            # OHLC : open = premiere valeur estimee, close = price
            # On n'a pas l'open exact, on utilise le mid du range
            # comme proxy (bar_low + bar_high) / 2 n'est pas l'open.
            # Meilleure approche : open = close de la barre precedente
            bars.append({
                "time": int(ts) // 1000,  # secondes unix pour Lightweight Charts
                "high": bar_high,
                "low": bar_low,
                "close": price,
                "volume": get_field(d, "total_vol", 0.0),
                "delta": get_field(d, "delta_bar", 0.0),
                "buy_vol": get_field(d, "buy_vol", 0.0),
                "sell_vol": get_field(d, "sell_vol", 0.0),
            })
        # Calculer l'open de chaque barre = close de la precedente
        for i in range(len(bars)):
            if i == 0:
                bars[i]["open"] = bars[i]["low"]  # premiere barre: estimation
            else:
                bars[i]["open"] = bars[i - 1]["close"]
        # Extraire les niveaux de la derniere barre pour overlay
        if lines:
            try:
                last = json.loads(lines[-1])
                levels = []

                def add_level(name, dist_field, color, style="solid", group="other"):
                    p = dist_to_price(last, dist_field)
                    if p and p > 0:
                        levels.append({"price": p, "title": name, "color": color, "style": style, "group": group})

                # Options
                add_level("CALL WALL", "dist_mq_call", "#ff5252", "solid", "options")
                add_level("PUT WALL", "dist_mq_put", "#00c853", "solid", "options")
                add_level("HVL", "dist_mq_hvl", "#00b4dc", "solid", "options")
                add_level("0DTE CALL", "dist_mq_call_0dte", "#ff8a80", "dashed", "0dte")
                add_level("0DTE PUT", "dist_mq_put_0dte", "#69f0ae", "dashed", "0dte")
                # GEX
                add_level("GEX UP", "dist_gex_nearest_up", "#ff6e40", "dashed", "gex")
                add_level("GEX DN", "dist_gex_nearest_dn", "#ffd740", "dashed", "gex")
                # VWAP
                add_level("VWAP D", "dist_vwap_d", "#00b4dc", "solid", "vwap")
                add_level("SD1+", "dist_vwap_d_sd1u", "#4fc3f7", "dashed", "sd12")
                add_level("SD1-", "dist_vwap_d_sd1d", "#4fc3f7", "dashed", "sd12")
                add_level("SD2+", "dist_vwap_d_sd2u", "#ff9800", "dashed", "sd12")
                add_level("SD2-", "dist_vwap_d_sd2d", "#ff9800", "dashed", "sd12")
                add_level("SD3+", "dist_vwap_d_sd3u", "#f44336", "dashed", "sd3")
                add_level("SD3-", "dist_vwap_d_sd3d", "#f44336", "dashed", "sd3")
                # Market Profile
                add_level("VPOC", "dist_cur_vpoc", "#e040fb", "solid", "profile")
                add_level("VAH", "dist_cur_vah", "#ce93d8", "dashed", "profile")
                add_level("VAL", "dist_cur_val", "#ce93d8", "dashed", "profile")
                add_level("Prev VPOC", "dist_prev_vpoc", "#7c4dff", "dashed", "prev")
                add_level("Prev VAH", "dist_prev_vah", "#9575cd", "dashed", "prev")
                add_level("Prev VAL", "dist_prev_val", "#9575cd", "dashed", "prev")
                add_level("Prev VWAP", "dist_prev_vwap", "#0090b0", "dashed", "prev")
                # Swing
                add_level("Swing H", "dist_swing_high", "#ffffff", "dashed", "swing")
                add_level("Swing L", "dist_swing_low", "#ffffff", "dashed", "swing")
                # Session
                add_level("Sess H", "dist_sess_high", "#546e7a", "dashed", "session")
                add_level("Sess L", "dist_sess_low", "#546e7a", "dashed", "session")
                # IB
                add_level("IB H", "dist_ib_high", "#ffc107", "dashed", "ib")
                add_level("IB L", "dist_ib_low", "#ffc107", "dashed", "ib")
                # OVN
                add_level("OVN H", "dist_ovn_high", "#607d8b", "dashed", "ovn")
                add_level("OVN L", "dist_ovn_low", "#607d8b", "dashed", "ovn")
                # Open
                add_level("Open Cash", "dist_open_cash", "#b0bec5", "dashed", "ovn")

                return {"bars": bars, "levels": levels}
            except json.JSONDecodeError:
                pass
        return {"bars": bars, "levels": []}
    except OSError as exc:
        logger.error("Erreur lecture barres %s: %s", symbol, exc)
        return {"bars": [], "levels": []}


def read_cta_data() -> dict:
    """Lit les 2 derniers fichiers CTA (aujourd'hui + hier)."""
    mq_dir = os.path.join(DATA_DIR, "MENTHORQ")
    pattern = os.path.join(mq_dir, "*_cta.json")
    files = sorted(glob(pattern))
    if not files:
        return {"today": None, "yesterday": None}

    def load_cta(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    today = load_cta(files[-1])
    yesterday = load_cta(files[-2]) if len(files) >= 2 else None

    # Generer la conclusion automatique
    conclusion = _generate_cta_conclusion(today, yesterday)

    return {
        "today": today,
        "yesterday": yesterday,
        "conclusion": conclusion,
    }


def _generate_cta_conclusion(today: dict | None, yesterday: dict | None) -> dict:
    """Genere un decryptage et des conseils a partir des positions CTA."""
    if not today or "CTA" not in today:
        return {"summary": "Pas de donnees CTA disponibles", "signals": [], "advice": []}

    cta = today["CTA"]
    signals = []
    advice = []

    # Analyser ES
    es = cta.get("ES", {})
    es_pos = es.get("position_today", 0)
    es_prev = es.get("position_yesterday", 0)
    es_1m = es.get("position_1m_ago", 0)
    es_z = es.get("zscore_3m", 0)

    if es_pos < -0.5:
        signals.append({"instrument": "ES", "signal": "SHORT", "strength": abs(es_pos),
                        "text": f"CTA shorts ES a {es_pos:.2f} (z-score {es_z:.2f})"})
    elif es_pos > 0.5:
        signals.append({"instrument": "ES", "signal": "LONG", "strength": es_pos,
                        "text": f"CTA longs ES a {es_pos:.2f} (z-score {es_z:.2f})"})
    else:
        signals.append({"instrument": "ES", "signal": "NEUTRE", "strength": abs(es_pos),
                        "text": f"CTA neutres sur ES a {es_pos:.2f}"})

    # Analyser NQ
    nq = cta.get("NQ", {})
    nq_pos = nq.get("position_today", 0)
    nq_z = nq.get("zscore_3m", 0)

    if nq_pos < -0.5:
        signals.append({"instrument": "NQ", "signal": "SHORT", "strength": abs(nq_pos),
                        "text": f"CTA shorts NQ a {nq_pos:.2f} (z-score {nq_z:.2f})"})
    elif nq_pos > 0.5:
        signals.append({"instrument": "NQ", "signal": "LONG", "strength": nq_pos,
                        "text": f"CTA longs NQ a {nq_pos:.2f} (z-score {nq_z:.2f})"})

    # Gold
    gold = cta.get("GOLD", {})
    gold_pos = gold.get("position_today", 0)
    if gold_pos > 1:
        signals.append({"instrument": "GOLD", "signal": "LONG", "strength": gold_pos,
                        "text": f"CTA longs Gold fort a {gold_pos:.2f} — risk-off"})

    # Treasuries
    t10 = cta.get("TREASURY_10Y", {})
    t10_pos = t10.get("position_today", 0)
    if t10_pos < -1:
        signals.append({"instrument": "10Y", "signal": "SHORT", "strength": abs(t10_pos),
                        "text": f"CTA shorts 10Y a {t10_pos:.2f} — taux montent"})

    # Changement de position ES
    es_delta = es_pos - es_prev
    if abs(es_delta) > 0.1:
        if es_delta < 0:
            direction = "vendent" if es_pos > 0 else "augmentent les shorts"
        else:
            direction = "achetent" if es_pos < 0 else "augmentent les longs"
        advice.append({"type": "warn" if es_delta < 0 else "ok",
                       "text": f"ES: Les CTA {direction} ({es_delta:+.2f} en 1 jour)"})

    # Z-score extreme ES
    if abs(es_z) > 1.5:
        advice.append({"type": "danger",
                       "text": f"ES z-score extreme ({es_z:.2f}) — position crowded, risque de squeeze"})

    # Z-score extreme NQ
    if abs(nq_z) > 1.5:
        advice.append({"type": "danger",
                       "text": f"NQ z-score extreme ({nq_z:.2f}) — position crowded, risque de squeeze"})

    # Treasuries 2Y
    t2 = cta.get("TREASURY_2Y", {})
    t2_pos = t2.get("position_today", 0)
    if abs(t2_pos) > 1:
        t2_dir = "SHORT" if t2_pos < 0 else "LONG"
        advice.append({"type": "info",
                       "text": f"CTA {t2_dir} 2Y ({t2_pos:+.2f}) — sensible politique Fed"})

    # Tendance 1 mois
    es_trend = es_pos - es_1m
    if abs(es_trend) > 0.5:
        trend_dir = "SHORT" if es_trend < 0 else "LONG"
        advice.append({"type": "info",
                       "text": f"ES tendance 1 mois : shift vers {trend_dir} ({es_trend:+.2f})"})

    # Divergence ES/NQ
    if (es_pos > 0 and nq_pos < 0) or (es_pos < 0 and nq_pos > 0):
        advice.append({"type": "warn",
                       "text": f"Divergence CTA : ES={es_pos:+.2f} vs NQ={nq_pos:+.2f} — attention"})

    # Commodities vs Equities
    brent = cta.get("BRENT", {}).get("position_today", 0)
    if brent > 2 and es_pos < 0:
        advice.append({"type": "info",
                       "text": "CTA long commodites + short equities = regime inflation"})

    # Summary (memes seuils que les signals : 0.5)
    es_label = "SHORT" if es_pos < -0.5 else "LONG" if es_pos > 0.5 else "NEUTRE"
    nq_label = "SHORT" if nq_pos < -0.5 else "LONG" if nq_pos > 0.5 else "NEUTRE"
    summary = f"Les gros sont {es_label} ES ({es_pos:+.2f}) et {nq_label} NQ ({nq_pos:+.2f})"

    return {
        "summary": summary,
        "signals": signals,
        "advice": advice,
    }


def read_menthorq_detail() -> dict:
    """Lit le dernier fichier menthorq_complete.json et extrait les donnees structurees."""
    mq_dir = os.path.join(DATA_DIR, "MENTHORQ")
    pattern = os.path.join(mq_dir, "*_menthorq_complete.json")
    files = sorted(glob(pattern))
    if not files:
        return {"date": None, "es": {}, "nq": {}}

    try:
        with open(files[-1], "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"date": None, "es": {}, "nq": {}}

    result = {"date": raw.get("date", ""), "source": raw.get("source", "")}

    for sym in ("ES", "NQ"):
        sym_data = raw.get(sym, {})
        structured = sym_data.get("structured", {})
        out = {}

        # Key Levels
        kl_res = structured.get("key_levels", {}).get("resource", {})
        kl_data = kl_res.get("data", {}) if isinstance(kl_res, dict) else {}
        out["key_levels"] = kl_data

        # BL Levels (parse text_data)
        bl_res = structured.get("bl_levels", {}).get("resource", {})
        bl_text = bl_res.get("text_data", "") if isinstance(bl_res, dict) else ""
        bl_levels = []
        if bl_text:
            parts = bl_text.split(",")
            for i in range(0, len(parts) - 1, 2):
                name = parts[i].strip().split(":")[-1].strip()
                try:
                    price = float(parts[i + 1].strip())
                    bl_levels.append({"name": name, "price": price})
                except (ValueError, IndexError):
                    pass
        out["bl_levels"] = bl_levels

        # Net GEX
        ng_res = structured.get("netgex", {}).get("resource", {})
        ng_data = ng_res.get("data", {}) if isinstance(ng_res, dict) else {}
        out["netgex"] = ng_data
        out["netgex_image"] = ng_res.get("image_url", "") if isinstance(ng_res, dict) else ""

        # Levels TV (parse text_data -> GEX 1-10 + Gamma Wall)
        lt_res = structured.get("levels_tv", {}).get("resource", {})
        lt_text = lt_res.get("text_data", "") if isinstance(lt_res, dict) else ""
        gex_strikes = []
        gamma_wall_0dte = None
        if lt_text:
            parts = lt_text.split(",")
            for i in range(0, len(parts) - 1, 2):
                name = parts[i].strip().split(":")[-1].strip()
                try:
                    price = float(parts[i + 1].strip())
                except (ValueError, IndexError):
                    continue
                if name.startswith("GEX"):
                    gex_strikes.append({"name": name, "price": price})
                elif name == "Gamma Wall 0DTE":
                    gamma_wall_0dte = price
        out["gex_strikes"] = gex_strikes
        out["gamma_wall_0dte"] = gamma_wall_0dte

        # QScores (from CTA yesterday data if available)
        cta_files = sorted(glob(os.path.join(mq_dir, "*_cta.json")))
        qscores = {}
        for cf in reversed(cta_files):
            try:
                with open(cf, "r", encoding="utf-8") as qf:
                    cdata = json.load(qf)
                qs = cdata.get("qscores", {}).get(sym, {})
                if qs:
                    qscores = qs
                    break
            except (json.JSONDecodeError, OSError):
                continue
        out["qscores"] = qscores

        # Gamma condition + P/C OI depuis CTA key_levels
        for cf in reversed(cta_files):
            try:
                with open(cf, "r", encoding="utf-8") as gf:
                    gdata = json.load(gf)
                ckl = gdata.get("key_levels", {}).get(sym, {})
                if ckl:
                    out["gamma_condition"] = ckl.get("gamma_condition", "")
                    out["pc_oi"] = ckl.get("pc_oi", 0)
                    out["iv_30d"] = ckl.get("iv_30d", 0)
                    # Top GEX strikes depuis vol_model
                    vm = gdata.get("vol_model", {}).get(sym, {})
                    if vm:
                        out["top_gex_strikes_cta"] = vm.get("top_gex_strikes", [])
                    break
            except (json.JSONDecodeError, OSError):
                continue

        # Blind spots
        for cf in reversed(cta_files):
            try:
                with open(cf, "r", encoding="utf-8") as bf:
                    bdata = json.load(bf)
                bs = bdata.get("blind_spots", {}).get(sym, [])
                if bs:
                    out["blind_spots"] = bs
                    break
            except (json.JSONDecodeError, OSError):
                continue
        if "blind_spots" not in out:
            out["blind_spots"] = []

        result[sym.lower()] = out

    return result


def read_ib_bars(symbol: str) -> dict:
    """Lit les barres de l'IB (09:30-10:30 ET = 13:30-14:30 UTC).

    Retourne les barres IB du jour + de la veille (dernier vrai jour).
    """
    data_dir = os.path.join(DATA_DIR, symbol)
    pattern = os.path.join(data_dir, f"*_{symbol}.jsonl")
    files = sorted(glob(pattern), key=os.path.getmtime)
    if not files:
        return {"today": [], "yesterday": [], "today_ib": {}, "yesterday_ib": {}}

    # Heures IB en UTC : 13:30-14:30 (ET = UTC-4 pendant DST)
    # IB standard Market Profile = 60 minutes (09:30-10:30 ET)
    IB_START_H, IB_START_M = 13, 30
    IB_END_H, IB_END_M = 14, 30

    def extract_ib(filepath):
        """Extrait les barres entre 13:30 et 14:30 UTC (IB 60 min)."""
        bars = []
        last_bar = None
        ib_high = None
        ib_low = None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        d = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    ts = d.get("ts")
                    if not ts:
                        continue
                    dt = datetime.utcfromtimestamp(int(ts) / 1000)
                    h, m = dt.hour, dt.minute
                    # Entre 13:30 et 14:29 UTC (IB 60 min)
                    in_ib = (h == IB_START_H and m >= IB_START_M) or (h == IB_END_H and m < IB_END_M)
                    if not in_ib:
                        last_bar = d
                        continue
                    price = get_field(d, "price", 0.0)
                    bar_high = get_field(d, "bar_high", price)
                    bar_low = get_field(d, "bar_low", price)
                    if ib_high is None or bar_high > ib_high:
                        ib_high = bar_high
                    if ib_low is None or bar_low < ib_low:
                        ib_low = bar_low
                    bars.append({
                        "time": int(ts) // 1000,
                        "high": bar_high,
                        "low": bar_low,
                        "close": price,
                        "volume": get_field(d, "total_vol", 0.0),
                        "delta": get_field(d, "delta_bar", 0.0),
                    })
                    last_bar = d
        except OSError:
            pass

        # Open = close precedente
        for i in range(len(bars)):
            if i == 0:
                bars[i]["open"] = bars[i]["low"]
            else:
                bars[i]["open"] = bars[i - 1]["close"]

        ib_info = {}
        if ib_high is not None and ib_low is not None:
            ib_info = {
                "ib_high": ib_high,
                "ib_low": ib_low,
                "ib_range": round((ib_high - ib_low) / TICK_SIZE, 0),
            }
            # Session high/low pour extension
            if last_bar:
                sh = dist_to_price(last_bar, "dist_sess_high")
                sl = dist_to_price(last_bar, "dist_sess_low")
                if sh:
                    ib_info["sess_high"] = sh
                if sl:
                    ib_info["sess_low"] = sl

        return bars, ib_info

    # Chercher les 2 derniers jours avec des barres IB
    # (les fichiers JSONL couvrent des sessions qui chevauchent les jours)
    found = []
    for i in range(len(files) - 1, max(-1, len(files) - 10), -1):
        try:
            if os.path.getsize(files[i]) < 50000:
                continue  # weekend
        except OSError:
            continue
        bars, ib_info = extract_ib(files[i])
        if bars:
            found.append({"bars": bars, "ib": ib_info})
            if len(found) >= 2:
                break

    today_bars = found[0]["bars"] if found else []
    today_ib = found[0]["ib"] if found else {}
    yesterday_bars = found[1]["bars"] if len(found) > 1 else []
    yesterday_ib = found[1]["ib"] if len(found) > 1 else {}

    return {
        "today": today_bars,
        "yesterday": yesterday_bars,
        "today_ib": today_ib,
        "yesterday_ib": yesterday_ib,
    }


def read_mtf_bias(symbol: str) -> dict:
    """Calcule le bias directionnel sur 4 timeframes (1m, 5m, 15m, 1h).

    Pour chaque TF, analyse les N dernieres barres agregees :
    - Position vs VWAP (au-dessus = bull, en-dessous = bear)
    - Direction delta cumule (positif = bull)
    - Momentum prix (close vs open des N barres = direction)
    Retourne un score -1 a +1 par TF + score confluence global.
    """
    path = get_latest_jsonl(symbol)
    if not path:
        return {"timeframes": {}, "confluence": 0, "verdict": "N/A"}

    # Lire toutes les barres du jour
    all_bars = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    d = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                ts = d.get("ts")
                if not ts:
                    continue
                price = get_field(d, "price", 0.0)
                # VWAP = prix + distance en ticks * tick_size (dist = (VWAP-prix)/tick)
                dist_vwap = get_field(d, "dist_vwap_d", 0.0)
                vwap_price = price + dist_vwap * TICK_SIZE if dist_vwap != 0 else 0.0
                all_bars.append({
                    "time": int(ts) // 1000,
                    "open": price,
                    "high": get_field(d, "bar_high", price),
                    "low": get_field(d, "bar_low", price),
                    "close": price,
                    "delta": get_field(d, "delta_bar", 0.0),
                    "vwap": vwap_price,
                    "volume": get_field(d, "total_vol", 0.0),
                })
    except OSError:
        return {"timeframes": {}, "confluence": 0, "verdict": "N/A"}

    # Fix open : open = close precedente
    for i in range(1, len(all_bars)):
        all_bars[i]["open"] = all_bars[i - 1]["close"]

    if len(all_bars) < 5:
        return {"timeframes": {}, "confluence": 0, "verdict": "N/A"}

    def aggregate(bars, tf_min):
        if tf_min <= 1:
            return bars
        interval = tf_min * 60
        agg = []
        cur = None
        for b in bars:
            bucket = (b["time"] // interval) * interval
            if cur is None or cur["time"] != bucket:
                if cur:
                    agg.append(cur)
                cur = dict(b)
                cur["time"] = bucket
            else:
                cur["high"] = max(cur["high"], b["high"])
                cur["low"] = min(cur["low"], b["low"])
                cur["close"] = b["close"]
                cur["delta"] = cur.get("delta", 0) + b.get("delta", 0)
                cur["volume"] = cur.get("volume", 0) + b.get("volume", 0)
                cur["vwap"] = b["vwap"]  # dernier VWAP
        if cur:
            agg.append(cur)
        return agg

    def calc_bias(bars, n_bars, tf_name="1m"):
        """Calcule le bias sur les N dernieres barres agregees."""
        subset = bars[-n_bars:] if len(bars) >= n_bars else bars
        if not subset:
            return {"score": 0.0, "label": "NEUTRE", "factors": {}}

        last = subset[-1]
        # 1. Position vs VWAP — normalise a 60 ticks (pas 20)
        vwap = last.get("vwap", 0)
        price = last["close"]
        vwap_score = 0.0
        if vwap > 0:
            dist_ticks = (price - vwap) / TICK_SIZE
            vwap_score = max(-1, min(1, dist_ticks / 60))

        # 2. Delta cumule sur les N barres
        total_delta = sum(b.get("delta", 0) for b in subset)
        total_vol = sum(b.get("volume", 1) for b in subset)
        delta_pct = total_delta / max(total_vol, 1)
        delta_score = max(-1, min(1, delta_pct * 5))

        # 3. Momentum — normalisation adaptee au TF
        mom_norm = {"1m": 0.1, "5m": 0.2, "15m": 0.3, "1h": 0.5}
        first_open = subset[0]["open"]
        last_close = subset[-1]["close"]
        if first_open > 0:
            change_pct = (last_close - first_open) / first_open * 100
            momentum_score = max(-1, min(1, change_pct / mom_norm.get(tf_name, 0.3)))
        else:
            momentum_score = 0.0

        # Score composite (40% VWAP + 30% delta + 30% momentum)
        score = round(0.4 * vwap_score + 0.3 * delta_score + 0.3 * momentum_score, 3)
        if score > 0.25:
            label = "BULL"
        elif score < -0.25:
            label = "BEAR"
        else:
            label = "NEUTRE"

        return {
            "score": score,
            "label": label,
            "factors": {
                "vwap": round(vwap_score, 2),
                "delta": round(delta_score, 2),
                "momentum": round(momentum_score, 2),
            },
        }

    # Calculer pour chaque TF
    tfs = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
    n_bars_per_tf = {"1m": 10, "5m": 6, "15m": 4, "1h": 4}
    results = {}
    scores = []
    for tf_name, tf_min in tfs.items():
        agg = aggregate(all_bars, tf_min)
        n = n_bars_per_tf[tf_name]
        bias = calc_bias(agg, n, tf_name)
        results[tf_name] = bias
        scores.append(bias["score"])

    # Score confluence : moyenne des 4 TF
    confluence = round(sum(scores) / len(scores), 3) if scores else 0.0

    # Comptage alignement
    bulls = sum(1 for s in scores if s > 0.25)
    bears = sum(1 for s in scores if s < -0.25)

    if bulls == 4:
        verdict = "ACHAT FORT (4/4)"
    elif bulls == 3:
        verdict = "ACHAT (3/4)"
    elif bears == 4:
        verdict = "VENTE FORT (4/4)"
    elif bears == 3:
        verdict = "VENTE (3/4)"
    elif bulls >= 2 and bears == 0:
        verdict = "ACHAT MODERE (2/4)"
    elif bears >= 2 and bulls == 0:
        verdict = "VENTE MODEREE (2/4)"
    else:
        verdict = "CONFLIT (" + str(bulls) + "B/" + str(bears) + "S)"

    return {
        "timeframes": results,
        "confluence": confluence,
        "bulls": bulls,
        "bears": bears,
        "verdict": verdict,
    }


def read_volume_profile(symbol: str) -> dict:
    """Calcule le volume profile (histogramme volume par prix) pour aujourd'hui et hier.

    Distribue le volume de chaque barre 1min sur son range de prix.
    Retourne {today: [{price, vol, pct}], yesterday: [...], today_levels, yesterday_levels}.
    """
    data_dir = os.path.join(DATA_DIR, symbol)
    pattern = os.path.join(data_dir, f"*_{symbol}.jsonl")
    files = sorted(glob(pattern), key=os.path.getmtime)
    if not files:
        return {"today": [], "yesterday": [], "today_levels": {}, "yesterday_levels": {}}

    def compute_profile(filepath):
        """Lit un JSONL et calcule le profil de volume."""
        vol_by_price = {}
        last_bar = None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        d = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue
                    high = get_field(d, "bar_high", 0.0)
                    low = get_field(d, "bar_low", 0.0)
                    vol = get_field(d, "total_vol", 0.0)
                    if high <= 0 or low <= 0 or vol <= 0:
                        continue
                    last_bar = d
                    # Distribuer le volume sur le range
                    tick = TICK_SIZE
                    price = low
                    n_ticks = max(1, int((high - low) / tick) + 1)
                    vol_per_tick = vol / n_ticks
                    while price <= high + 0.001:
                        rounded = round(price / tick) * tick
                        rounded = round(rounded, 2)
                        vol_by_price[rounded] = vol_by_price.get(rounded, 0) + vol_per_tick
                        price += tick
        except OSError:
            pass

        if not vol_by_price:
            return [], {}, None

        # Trier par prix decroissant
        sorted_prices = sorted(vol_by_price.keys(), reverse=True)
        max_vol = max(vol_by_price.values())

        # POC = prix avec le plus de volume
        poc_price = max(vol_by_price, key=vol_by_price.get)

        # Value Area (70% du volume total)
        total_vol = sum(vol_by_price.values())
        target = total_vol * 0.70
        # Expand from POC
        prices_asc = sorted(vol_by_price.keys())
        poc_idx = prices_asc.index(poc_price)
        va_vol = vol_by_price[poc_price]
        low_idx = poc_idx
        high_idx = poc_idx
        while va_vol < target and (low_idx > 0 or high_idx < len(prices_asc) - 1):
            low_vol = vol_by_price[prices_asc[low_idx - 1]] if low_idx > 0 else 0
            high_vol = vol_by_price[prices_asc[high_idx + 1]] if high_idx < len(prices_asc) - 1 else 0
            if low_vol >= high_vol and low_idx > 0:
                low_idx -= 1
                va_vol += low_vol
            elif high_idx < len(prices_asc) - 1:
                high_idx += 1
                va_vol += high_vol
            else:
                low_idx -= 1
                va_vol += low_vol

        vah = prices_asc[high_idx]
        val_price = prices_asc[low_idx]

        profile = []
        for p in sorted_prices:
            v = vol_by_price[p]
            in_va = val_price <= p <= vah
            is_poc = abs(p - poc_price) < TICK_SIZE * 0.5
            profile.append({
                "price": p,
                "vol": round(v, 1),
                "pct": round(v / max_vol * 100, 1),
                "in_va": in_va,
                "is_poc": is_poc,
            })

        levels = {
            "poc": poc_price,
            "vah": vah,
            "val": val_price,
        }

        # Extraire les niveaux additionnels de la derniere barre
        if last_bar:
            levels["vpoc_prev"] = dist_to_price(last_bar, "dist_prev_vpoc")
            levels["vah_prev"] = dist_to_price(last_bar, "dist_prev_vah")
            levels["val_prev"] = dist_to_price(last_bar, "dist_prev_val")
            # VWAP
            levels["vwap_d"] = dist_to_price(last_bar, "dist_vwap_d")
            levels["vwap_sd1u"] = dist_to_price(last_bar, "dist_vwap_d_sd1u")
            levels["vwap_sd1d"] = dist_to_price(last_bar, "dist_vwap_d_sd1d")
            levels["vwap_sd2u"] = dist_to_price(last_bar, "dist_vwap_d_sd2u")
            levels["vwap_sd2d"] = dist_to_price(last_bar, "dist_vwap_d_sd2d")
            levels["vwap_sd3u"] = dist_to_price(last_bar, "dist_vwap_d_sd3u")
            levels["vwap_sd3d"] = dist_to_price(last_bar, "dist_vwap_d_sd3d")
            # Previous VWAP
            levels["prev_vwap"] = dist_to_price(last_bar, "dist_prev_vwap")
            # Session High/Low
            levels["sess_high"] = dist_to_price(last_bar, "dist_sess_high")
            levels["sess_low"] = dist_to_price(last_bar, "dist_sess_low")
            # IB
            levels["ib_high"] = dist_to_price(last_bar, "dist_ib_high")
            levels["ib_low"] = dist_to_price(last_bar, "dist_ib_low")
            levels["ib_range"] = get_field(last_bar, "ib_range_ticks", 0.0)
            levels["ib_broken_up"] = get_int_field(last_bar, "ib_broken_up", 0)
            levels["ib_broken_down"] = get_int_field(last_bar, "ib_broken_down", 0)
            # OVN
            levels["ovn_high"] = dist_to_price(last_bar, "dist_ovn_high")
            levels["ovn_low"] = dist_to_price(last_bar, "dist_ovn_low")

        return profile, levels, last_bar

    # Aujourd'hui = dernier fichier, hier = avant-dernier
    today_profile, today_levels, _ = compute_profile(files[-1])
    # "Hier" = dernier fichier de vraie session (> 100KB, pas weekend)
    yesterday_profile, yesterday_levels = [], {}
    for i in range(len(files) - 2, -1, -1):
        try:
            size = os.path.getsize(files[i])
        except OSError:
            continue
        if size > 100000:  # > 100KB = vrai jour de trading
            yesterday_profile, yesterday_levels, _ = compute_profile(files[i])
            break

    return {
        "today": today_profile,
        "yesterday": yesterday_profile,
        "today_levels": today_levels,
        "yesterday_levels": yesterday_levels,
    }
