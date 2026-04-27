"""mia_paper_trader.py — Paper trading bot qui suit le dashboard (v2 22/04/2026).

Suit les recommandations du dashboard MIA en temps reel :
- Prend un trade quand Conseil Global = ACHAT/VENTE AVEC freshness == "NEW"
  (state machine v1.5 fix 22/04 — evite signal persistent / FOMO)
- SL/TP via SLTPEngine (Tier 1/2 derriere mur + TP1 premier obstacle)
- Filtre expected_payoff_$ >= $2 (audit ES vs NQ 22/04)
- 3 micros tracking (realistic futur bot live)
- Cooldown 15 min post-close par symbol
- Circuit breaker 3 SL consec → pause 60 min par symbol
- Ecrit state.json pour consommation dashboard (endpoint /api/paper_trades)

Usage :
    python CORE/mia_paper_trader.py            # lance le paper trader
    python CORE/mia_paper_trader.py --stats
    python CORE/mia_paper_trader.py --stats --symbol NQ
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

# Import SLTPEngine (audit Tier1/2/3 sur 1349 barres, 07/03/2026)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from CORE.mia_sltp import SLTPEngine, SL_BUDGET  # SL_BUDGET pour kill-switch SELL asymetrique (R3 review 24/04)
from CORE.bias_calculator import compute_bias  # 3.7.9 (24/04) gate directionnel
from CORE.cross_instrument import compute_cross_bonus  # 24/04 mode OBSERVATION (log-only)

# Systeme logs V2 (22/04 session)
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("paper_trader", process="paper")
except Exception:
    _v2log = None

# Integration DTC Sim3 (22/04 soir - Jackson : visibilite Sierra Chart +
# test pipeline bout-en-bout). Feature flag MIA_DTC_ENABLE=1 pour activer.
# Sinon comportement paper pur memoire (inchange).
DTC_ENABLED = os.environ.get("MIA_DTC_ENABLE", "0") == "1"
_DTC_IMPORT_OK = False
if DTC_ENABLED:
    try:
        # BOT/ contient le dtc_connector eprouve (teste 02/04/2026 OCO manuel)
        _BOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BOT")
        if _BOT_DIR not in sys.path:
            sys.path.insert(0, _BOT_DIR)
        from dtc_connector import DTCConnector, OrderFill, BUY as DTC_BUY, SELL as DTC_SELL
        from bot_config import DTCConfig, INSTRUMENTS as DTC_INSTRUMENTS
        _DTC_IMPORT_OK = True
    except Exception as _e:
        print(f"  !!! DTC import failed : {_e} — fallback paper pur memoire")
        _DTC_IMPORT_OK = False

# Config
DASHBOARD_URL = "http://localhost:8503/api/dashboard"
POLL_INTERVAL = 10  # secondes entre chaque check
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA", "PAPER_TRADES")
STATE_FILE = os.path.join(DATA_DIR, "state.json")  # bridge pour dashboard endpoint
MENTHORQ_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA", "MENTHORQ")
# Kill-switch admin : cree/supprime par POST /api/bot/{stop,start} (admin_routes.py)
# Meme chemin que BOT/bot_main.py pour compat, mais seul paper_trader ecoute en prod.
STOP_FLAG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "DATA", "BOT_CONTROL", "STOP.flag"
)
TICK_SIZE = 0.25

# Ticks values par instrument
TICK_VALUE = {"ES": 1.25, "NQ": 0.50}

# Regles v2 (22/04) — consolidees apres audits agents
ENTRY_RULES = {
    "min_confidence": 0.50,
    "min_mtf_bears": 3,
    "min_mtf_bulls": 3,
    # 🆕 FIX 24/04 : accepter NEW + PERSISTENT (avant : NEW uniquement)
    #   Raison : 46 rejets `freshness_not_new` / 4026 polls sur 23/04. Cause :
    #   `_MAX_SIGNAL_AGE_BARS=2` dans builders.py → signal EXPIRED apres 2min.
    #   Dedup via signal_id (STEP 5) protege contre trade multiple meme signal.
    #   Permet au bot de rattraper si premier poll NEW etait rejete pour autre
    #   cause (SLTP temps reel, bias borderline), ou si bot restart mi-signal.
    "freshness_required": ("NEW", "PERSISTENT"),
    "max_positions_per_symbol": 1,
    "n_micros": 3,                          # 3 micros (realistic bot live futur)
    "min_expected_payoff_usd": 2.0,         # filtre audit ES vs NQ (22/04)
    # 22/04 soir Jackson : PAS de limite trades/jour en paper (collecte max
    # de donnees). Cooldown 15min post-close + circuit breaker 3 SL gardent
    # la safety. Reactivation cap en mode LIVE capital reel plus tard.
    "max_trades_per_day": 9999,
    "cooldown_post_close_sec": 900,         # 15 min
    "circuit_breaker_losses": 3,            # 3 SL consec
    "circuit_breaker_pause_sec": 3600,      # 60 min pause
    "estimated_wr_initial": 0.45,           # conservateur avant 30 trades empiriques (review R4)
    "estimated_wr_rolling_min": 30,         # apres N trades, switch vers WR rolling reel
    # 3.7.9 (24/04) — gate directionnel bias_calculator STEP 6bis
    # 🆕 24/04 soir (B.1) : `min_bias_clarity` utilise UNIQUEMENT comme seuil
    #   pour le soft-flag `bias_weak_but_aligned` (observabilite V2 log).
    #   Le gate strict ne rejette plus sur clarity, seulement sur opposite_direction.
    #   Cf. feedback_lightgbm_no_composite_indicators.md + audit market-analyst 24/04.
    "min_bias_clarity": 0.30,               # seuil soft-flag observabilite uniquement
    "enforce_bias_gate": True,              # si False, bias calcule mais gate desactive (observabilite only)
}

# Config DTC (valide Phase 1 paper uniquement, pas de compte LIVE)
TRADE_ACCOUNT = os.environ.get("MIA_TRADE_ACCOUNT", "Sim3")
_SIM_WHITELIST_PREFIX = ("SIM", "Sim", "sim")


# Funnel check_entry (23/04 Jackson) : mix compteurs bruts + funnel macro 8 STEPs.
# Expose `entry_funnel_today` dans state.json + snapshot EOD LOGS/funnel/funnel_YYYYMMDD.json.
# But : diagnostiquer "pourquoi bot 0 trade" en un coup d'oeil (V1 feature que Jackson kiffait).
#
# STEP 7 split (23/04 soir) : 4 sous-raisons pour savoir si mur absent, R:R faible, ou budget dep.
FUNNEL_STEPS = [
    ("1_position_day",  "Position+MaxDay",  ["already_position", "max_trades_day"]),
    ("2_cooldown_cb",   "Cooldown+Circuit", ["cooldown_active", "circuit_breaker"]),
    ("3_conseil",       "Conseil Global",   ["conseil_attendre", "conseil_conflit", "sell_auto_disabled"]),
    ("4_freshness",     "Freshness NEW",    ["freshness_not_new"]),
    ("5_dedup",         "Dedup signal_id",  ["signal_already_traded"]),
    ("6_conf_mtf",      "Conf+MTF",         ["confidence_too_low", "mtf_insufficient"]),
    ("6bis_bias",       "Prereq bar DMP (bias=soft-flag only)",
     ["bar_dmp_missing"]),  # 🆕 FIX 24/04 soir (B.1 audit market-analyst #2) :
     # `bias_opposite_direction` RETIRE (quasi-tautologie : conseil_global utilise deja
     # compute_bias sur meme bar). STEP 6bis garde uniquement check prereq bar DMP.
     # Soft-flag `bias_weak_but_aligned` continue d'etre loggue V2 pour observabilite.
    ("7_sltp",          "SLTP murs+budget",
     ["sltp_no_wall", "sltp_rr_low", "sltp_budget_exceeded", "sltp_out_of_range"]),
    ("8_payoff",        "Expected payoff",  ["expected_payoff_low"]),
]
FUNNEL_STEP_KEYS = [s[0] for s in FUNNEL_STEPS]
FUNNEL_REASONS = [r for (_, _, reasons) in FUNNEL_STEPS for r in reasons]
# Step 4+ : ce qu'on appelle "actionable" = polls ayant passe 1+2+3 (vrais signaux live).
# Permet % discriminants : 42% freshness_not_new sur ACTIONABLES, pas sur tous les polls (dont 85% ATTENDRE).
FUNNEL_ACTIONABLE_FROM_STEP = "3_conseil"
FUNNEL_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "LOGS", "funnel")

# Logs rejet enrichis (23/04 soir) — diagnostic "pourquoi cette raison exacte".
# STEP 1-3 = bruit (cooldown/ATTENDRE), pas de log detaille, juste counter funnel.
# STEP 4-8 = logs JSONL avec contexte metier. Rate limit 60s par (symbol, reason) anti-spam.
REJECTIONS_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "LOGS", "rejections")
REJECT_LOG_STEPS = {"3_conseil", "4_freshness", "5_dedup", "6_conf_mtf", "6bis_bias", "7_sltp", "8_payoff"}

# Mapping reason -> code catalog V2 pour emission unified LOGS/decisions/
# (cf DOCS/BOT_CHANGELOG.md 25/04 - enrichissement log systeme V2)
REJECT_TO_V2_CODE = {
    "conseil_attendre":      "GATE_CONSEIL_ATTENDRE",
    "conseil_conflit":       "GATE_CONSEIL_CONFLIT",
    "sell_auto_disabled":    "GATE_SELL_AUTO_DISABLED",
    "freshness_not_new":     "GATE_FRESHNESS_EXPIRED",
    "signal_already_traded": "GATE_SIGNAL_DEDUPED",
    "confidence_too_low":    "GATE_CONF_TOO_LOW",
    "mtf_insufficient":      "GATE_MTF_INSUFFICIENT",
    "mtf_bull_desert":       "GATE_MTF_BULL_DESERT",
    "bar_dmp_missing":       "GATE_BAR_DMP_MISSING",
    "sltp_no_wall":          "GATE_SLTP_REJECT",
    "sltp_out_of_range":     "GATE_SLTP_REJECT",
    "sltp_budget_exceeded":  "GATE_SLTP_REJECT",
    "sltp_rr_low":           "GATE_SLTP_REJECT",
    "payoff_too_low":        "GATE_PAYOFF_TOO_LOW",
}
REJECT_LOG_RATE_LIMIT_SEC = 60


# Fix CRITIQUE (22/04 soir) : sans auth, /api/dashboard retourne tier=free
# avec conseil_global.action toujours ATTENDRE → paper trader jamais ne trade.
# Solution : generer JWT owner interne (meme JWT_SECRET que le serveur, car
# meme process VPS/meme fichier .jwt_secret). Token regenere toutes les 13 min
# (access expiry 15 min, marge 2 min).
_SERVICE_TOKEN: str | None = None
_SERVICE_TOKEN_EXPIRY: float = 0.0


def _get_service_token() -> str:
    """JWT owner service pour fetch dashboard sans etre tier-gated."""
    global _SERVICE_TOKEN, _SERVICE_TOKEN_EXPIRY
    now = time.time()
    if _SERVICE_TOKEN is None or now >= _SERVICE_TOKEN_EXPIRY - 120:
        from DASHBOARD.api.auth import _create_token, ACCESS_EXPIRY
        _SERVICE_TOKEN = _create_token("paper_service@internal", "owner", "access")
        _SERVICE_TOKEN_EXPIRY = now + ACCESS_EXPIRY
    return _SERVICE_TOKEN


def get_dashboard():
    """Fetch le dashboard API avec JWT owner (bypass tier filter)."""
    import urllib.request
    try:
        token = _get_service_token()
        req = urllib.request.Request(DASHBOARD_URL)
        req.add_header("Authorization", f"Bearer {token}")
        r = urllib.request.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        print(f"  Erreur fetch dashboard: {e}")
        return None


class PaperTrader:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.positions = {}  # {symbol: position_dict}
        self.today_trades = []
        self.date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.log_file = os.path.join(DATA_DIR, f"{self.date_str}_trades.jsonl")
        self.snapshot_file = os.path.join(DATA_DIR, f"{self.date_str}_snapshots.jsonl")
        self.trade_count = 0

        # v2 (22/04) : SLTPEngine par instrument (Tier 1/2 murs audites)
        self.sltp_engines = {
            "ES": SLTPEngine(symbol="ES"),
            "NQ": SLTPEngine(symbol="NQ"),
        }

        # v2 (22/04) : state machine cooldown + circuit breaker par symbol
        self._last_close_ts = {}                # sym -> timestamp
        self._consec_losses = {"ES": 0, "NQ": 0}
        self._circuit_pause_until = {}          # sym -> timestamp fin pause

        # v2 (22/04) : tracker signal_ids deja consommes (dedup cross-restart VPS)
        # Persiste sur disque (review R3 : sinon restart = re-entry meme signal_id)
        self._traded_signals_file = os.path.join(DATA_DIR, f"{self.date_str}_traded_signals.txt")
        self._traded_signal_ids = set()

        # Cleanup state.json.tmp orphelin si crash mi-write (review R5)
        tmp_state = STATE_FILE + ".tmp"
        if os.path.exists(tmp_state):
            try:
                os.remove(tmp_state)
            except OSError:
                pass

        # Funnel check_entry (23/04) : diagnostic "pourquoi 0 trade"
        os.makedirs(FUNNEL_LOG_DIR, exist_ok=True)
        self._funnel = self._funnel_blank(self.date_str)
        # Logs rejet enrichis (23/04 soir) : rate limit 60s par (sym, reason)
        os.makedirs(REJECTIONS_LOG_DIR, exist_ok=True)
        self._reject_log_last_ts: dict = {}  # (sym, reason) -> last_emit_ts

        # Cross-instrument observation (24/04 mode log-only, pre-integration Option 2)
        # Stocke le dernier compute_cross_bonus pour expose dans state.json + logs V2
        self._last_cross_context: Optional[dict] = None

        # 🆕 FIX 24/04 : kill-switch auto SELL (re-activation SELL ce soir).
        # 🆕 FIX 24/04 soir (audit market-analyst #4) : par SYMBOLE, seuil DD
        #   asymetrique `max_sl_ticks[sym] * 1.5` (NQ 120t / ES 60t). Evite :
        #   - NQ : 1 seul SL plein (80t) ne doit PAS declencher kill
        #   - ES : 60t = 1.5 trades, equilibre safety
        # Reset EOD : _rotate_day_if_needed remet les compteurs a 0 par symbole.
        self._sell_trades_today: Dict[str, List[dict]] = {"ES": [], "NQ": []}
        self._sell_dd_intraday_ticks: Dict[str, float] = {"ES": 0.0, "NQ": 0.0}
        self._sell_disabled: Dict[str, bool] = {"ES": False, "NQ": False}
        self._sell_disable_reason: Dict[str, Optional[str]] = {"ES": None, "NQ": None}

        # Kill-switch admin (fix 24/04) : etat transition ACTIF <-> PAUSE via STOP.flag
        # Cree/supprime par POST /api/bot/{stop,start}. Lu dans la boucle run().
        self._stop_flag_active = False
        self._stop_flag_activated_at = 0.0   # epoch, pour alerte flatten pending
        self._stop_flag_stale_alerted = False  # evite spam log alerte stale

        # 24/04 : regime GEX MenthorQ — contexte daily (log + state.json, PAS gate)
        # Finding 15/04 : SELL -56% PF gap GEX+ vs GEX-. On log pour diagnostic,
        # pas pour bloquer (anti pattern 11 V1).
        # Thread safety : `_menthorq_regime` est REASSIGNE en bloc (atomique sous GIL
        # via `self._menthorq_regime = out`). NE JAMAIS muter in-place depuis un autre
        # thread (ex: `self._menthorq_regime["ES"]["regime"] = ...`) — casserait
        # l'atomicite pour le main thread qui lit dans `_build_state`.
        self._menthorq_regime: Optional[dict] = None
        self._load_menthorq_regime()

        # Integration DTC Sim3 (22/04 soir) : thread safety + mapping orders
        # `_pos_lock` : RLock protege positions / cooldown / consec_losses /
        # _order_to_symbol car `_recv_loop` DTC (daemon thread) peut toucher
        # ces structures via `_handle_dtc_fill` pendant que main fait check_exit.
        self._pos_lock = threading.RLock()
        # Mapping order CID -> symbol pour callback fill
        # {parent_id: "ES", tp_cid: "ES", sl_cid: "ES", ...}
        self._order_to_symbol: dict = {}
        # Cache dernier payload dashboard pour exit_context (close appele depuis
        # callback DTC n'a pas data en param, on utilise ce cache).
        self._last_dashboard_data: Optional[dict] = None

        # DTC connector (None si MIA_DTC_ENABLE=0 ou import failed)
        self.dtc = None
        self.trade_account = TRADE_ACCOUNT
        if DTC_ENABLED and _DTC_IMPORT_OK:
            # Hard check whitelist : refuse comptes live accidentels
            if not self.trade_account.lower().startswith("sim"):
                raise RuntimeError(
                    f"MIA_TRADE_ACCOUNT={self.trade_account!r} non autorise. "
                    f"Paper trader accepte uniquement Sim1/Sim2/Sim3 (safety Phase 1). "
                    f"Set MIA_TRADE_ACCOUNT=Sim3 ou similaire."
                )
            print(f"  DTC enabled -> account={self.trade_account}")
            try:
                self.dtc = DTCConnector(DTCConfig())
                self.dtc.on_fill = self._handle_dtc_fill
                if not self.dtc.connect():
                    raise RuntimeError("DTC connect() returned False")
                # NOTE (22/04 soir) : pas de subscribe_market_data ici — Sierra Chart
                # DTC server refuse ("Market data request not allowed"). Le bot lit
                # les prix via dashboard API (/api/dashboard banner) qui vient du
                # JSONL DMP, pas du DTC. send_market_order fonctionne sans subscribe
                # (le serveur utilise le dernier prix marche cote SC automatiquement).
                print(f"  DTC connected OK (host={self.dtc.cfg.host}:{self.dtc.cfg.port})")
                if _v2log:
                    try:
                        _v2log.emit("BOOT_READY",
                                    dtc="connected",
                                    model="paper",
                                    data=self.trade_account)
                    except Exception:
                        pass
            except Exception as e:
                # Fail-loud au boot : si DTC_ENABLE=1 mais connect echoue,
                # on crash plutot que silencieusement fallback (ambiguite dangereuse)
                print(f"  !!! DTC connect FAILED : {e}")
                raise
        else:
            if DTC_ENABLED and not _DTC_IMPORT_OK:
                print(f"  !!! DTC_ENABLE=1 mais import KO -> fallback simu pure")
            else:
                print(f"  DTC desactive (simu pure memoire)")

        self._load_existing()

    def _load_existing(self):
        """Charge les trades + signal_ids existants du jour (robuste post-restart)."""
        if os.path.exists(self.log_file):
            with open(self.log_file, "r") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        try:
                            self.today_trades.append(json.loads(s))
                        except json.JSONDecodeError:
                            pass
            self.trade_count = len(self.today_trades)

        # v2 (review R3) : reload signal_ids deja trades (cross-restart VPS)
        if os.path.exists(self._traded_signals_file):
            try:
                with open(self._traded_signals_file, "r") as f:
                    for line in f:
                        sid = line.strip()
                        if sid:
                            self._traded_signal_ids.add(sid)
            except OSError:
                pass

    def _rotate_day_if_needed(self):
        """Fix B4 (code-reviewer 22/04) : rollover quotidien pour bot VPS 24/7.

        Si UTC date change depuis init, reset tout ce qui est quotidien :
          - trade_count_today, today_trades (nouveau fichier log)
          - consec_losses, circuit_pause_until (fresh start)
          - traded_signal_ids (nouveau fichier dedup)
          - log_file, snapshot_file, _traded_signals_file paths

        Appele en tete de boucle `run()` avant toute autre logique.
        """
        current_date = datetime.now(timezone.utc).strftime("%Y%m%d")
        if current_date == self.date_str:
            return
        prev_date = self.date_str
        print(f"  === ROLLOVER DATE {prev_date} -> {current_date} ===")
        # Snapshot EOD funnel avant reset (23/04) — historique diagnostic par jour
        self._funnel_save_eod(prev_date)
        # Reset quotidien
        self.today_trades = []
        self.trade_count = 0
        self.date_str = current_date
        self.log_file = os.path.join(DATA_DIR, f"{self.date_str}_trades.jsonl")
        self.snapshot_file = os.path.join(DATA_DIR, f"{self.date_str}_snapshots.jsonl")
        self._traded_signals_file = os.path.join(DATA_DIR, f"{self.date_str}_traded_signals.txt")
        self._traded_signal_ids = set()
        self._funnel = self._funnel_blank(current_date)
        # Fix mineur #2 (code-reviewer 22/04) : ne PAS reset _last_close_ts ni
        # _circuit_pause_until — ce sont des timestamps absolus, le cooldown
        # expire naturellement sans devoir traverser la frontiere UTC. Seul
        # _consec_losses doit etre reset (compteur quotidien non-persistant).
        self._consec_losses = {"ES": 0, "NQ": 0}
        # 🆕 FIX 24/04 soir (audit #4) : reset EOD kill-switch SELL par symbole.
        # Chaque nouvelle journee UTC = compteurs DD/trades repartent a 0.
        self._sell_trades_today = {"ES": [], "NQ": []}
        self._sell_dd_intraday_ticks = {"ES": 0.0, "NQ": 0.0}
        self._sell_disabled = {"ES": False, "NQ": False}
        self._sell_disable_reason = {"ES": None, "NQ": None}
        # NE PAS toucher aux positions ouvertes (overnight possible) — on flatten eventuel EOD ailleurs
        if _v2log:
            try:
                _v2log.emit("SESSION_OPEN", component="paper_trader",
                            prev_date=prev_date, new_date=current_date)
            except Exception:
                pass
        # 24/04 : reload regime MenthorQ apres rollover (JSON du nouveau jour)
        self._load_menthorq_regime()

    # --- Regime MenthorQ (24/04) -----------------------------------------
    def _load_menthorq_regime(self) -> None:
        """Charge le regime GEX+/GEX- par symbole depuis le JSON MenthorQ du jour.

        Lit `DATA/MENTHORQ/YYYYMMDD_menthorq_complete.json`, extrait
        `key_levels.{ES,NQ}` (net_gex, total_gex, iv_30d, gamma_condition) et
        derive `regime = "GEX+" if net_gex > 0 else "GEX-"` + ratio normalise.

        Si JSON absent → regime = "UNKNOWN", pas d'echec.

        Stocke dans `self._menthorq_regime` (expose state.json + logs V2).

        IMPORTANT : ne touche PAS aux decisions du bot (pas de gate).
        C'est du contexte pour diagnostic + dashboard. Edge empirique
        documente (finding 15/04) : SELL -56% PF gap en GEX+ vs GEX-.
        """
        today_path = os.path.join(MENTHORQ_DIR, f"{self.date_str}_menthorq_complete.json")
        out = {
            "date": self.date_str,
            "json_path": today_path,
            "loaded": False,
            "loaded_ts": time.time(),
            "fallback_used": False,
            "fallback_date": None,
            "ES": {"regime": "UNKNOWN"},
            "NQ": {"regime": "UNKNOWN"},
        }
        # 🆕 Fix B2 (25/04 - cf DOCS/BOT_CHANGELOG.md) : fallback sur dernier
        # fichier MenthorQ VALIDE si today absent OU invalide. Un fichier peut
        # exister mais etre un echec scraper (raw_ajax + success:false, pas de
        # key_levels). On detecte et on fallback sur dernier fichier valide.
        # Max 7j pour eviter data trop stale.
        # Impact decisions trade : ZERO (features mq_* viennent DMP JSONL live).
        def _try_load_and_validate(path: str):
            """Retourne data si fichier valide (key_levels.ES/NQ dict present),
            None sinon. Un fichier scraper echoue (raw_ajax only) = None."""
            if not os.path.exists(path):
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception as e:
                if _v2log:
                    try:
                        _v2log.emit("MQ_INGESTION_FAIL", source=path, err=str(e))
                    except Exception:
                        pass
                return None
            kl = d.get("key_levels", {}) or {}
            has_es = isinstance(kl.get("ES"), dict) and kl.get("ES")
            has_nq = isinstance(kl.get("NQ"), dict) and kl.get("NQ")
            if not (has_es or has_nq):
                return None  # fichier present mais pas de key_levels valides
            return d

        # Build candidates list : today first, then fallbacks by recency <= 7j
        candidates = [(self.date_str, today_path, False)]  # (date, path, is_fallback)
        try:
            import glob as _glob
            pattern = os.path.join(MENTHORQ_DIR, "*_menthorq_complete.json")
            dated_fallback = []
            for p in _glob.glob(pattern):
                name = os.path.basename(p)
                date_prefix = name.split("_")[0]
                if (len(date_prefix) == 8 and date_prefix.isdigit()
                        and date_prefix != self.date_str):
                    dated_fallback.append((date_prefix, p))
            dated_fallback.sort(reverse=True)
            today_int = int(self.date_str)
            for d_str, p in dated_fallback:
                age = today_int - int(d_str)
                if 0 < age <= 7:
                    candidates.append((d_str, p, True))
        except Exception:
            pass

        # Try each candidate, stop at first VALID
        data = None
        for d_str, path, is_fallback in candidates:
            d = _try_load_and_validate(path)
            if d is not None:
                data = d
                out["json_path"] = path
                if is_fallback:
                    out["fallback_used"] = True
                    out["fallback_date"] = d_str
                    print(f"  [MQ] fallback : {self.date_str} absent/invalide, utilise {d_str}")
                    if _v2log:
                        try:
                            _v2log.emit("GENERIC_INFO",
                                        msg=f"mq_regime fallback : today={self.date_str} absent/invalide, loaded {d_str}")
                        except Exception:
                            pass
                break

        if data is None:
            self._menthorq_regime = out
            if _v2log:
                try:
                    _v2log.emit("MQ_REGIME_MISSING", date=self.date_str, sym="ES+NQ")
                except Exception:
                    pass
            return

        kl = data.get("key_levels", {}) or {}
        for sym in ("ES", "NQ"):
            kls = kl.get(sym)
            # Partial load : on emit MQ_REGIME_MISSING cible par symbole manquant
            # au lieu de fallback silencieux (review code-reviewer 24/04 point #3).
            if not isinstance(kls, dict):
                if _v2log:
                    try:
                        _v2log.emit("MQ_REGIME_MISSING", date=self.date_str, sym=sym)
                    except Exception:
                        pass
                continue
            net_gex = kls.get("net_gex")
            total_gex = kls.get("total_gex")
            if net_gex is None:
                if _v2log:
                    try:
                        _v2log.emit("MQ_REGIME_MISSING", date=self.date_str, sym=sym)
                    except Exception:
                        pass
                continue
            # Strict 2 etats : on collapse 0 -> GEX- (review code-reviewer 24/04
            # point #2 : evite 3e voie "NEUTRAL" non geree cote dashboard).
            try:
                net_gex_f = float(net_gex)
            except (TypeError, ValueError):
                if _v2log:
                    try:
                        _v2log.emit("MQ_INGESTION_FAIL", source=json_path,
                                    err=f"net_gex non numerique pour {sym}: {net_gex!r}")
                    except Exception:
                        pass
                continue
            regime = "GEX+" if net_gex_f > 0 else "GEX-"
            ratio = None
            if total_gex not in (None, 0):
                try:
                    ratio = round(net_gex_f / float(total_gex), 4)
                except (TypeError, ValueError, ZeroDivisionError):
                    ratio = None
            out[sym] = {
                "regime": regime,
                "net_gex": net_gex_f,
                "total_gex": float(total_gex) if total_gex is not None else None,
                "ratio": ratio,  # net/total : comparable ES vs NQ
                "iv_30d": kls.get("iv_30d"),
                "gamma_condition": kls.get("gamma_condition"),
                "gamma_wall_0dte": kls.get("gamma_wall_0dte"),
                "pc_gex": kls.get("pc_gex"),
            }
            if _v2log:
                try:
                    _v2log.emit("MQ_REGIME_LOADED", sym=sym, regime=regime,
                                net_gex=f"{net_gex_f:.2f}",
                                ratio=f"{ratio:.3f}" if ratio is not None else "nan")
                except Exception:
                    pass
        out["loaded"] = (out["ES"].get("regime") != "UNKNOWN"
                        or out["NQ"].get("regime") != "UNKNOWN")
        self._menthorq_regime = out

    # --- Funnel diagnostic (23/04) ---------------------------------------
    @staticmethod
    def _funnel_blank(date_str: str) -> dict:
        return {
            "date": date_str,
            "polls_total": 0,
            "steps": {k: {"passed": 0, "rejected": 0} for k in FUNNEL_STEP_KEYS},
            "reject_detail": {r: 0 for r in FUNNEL_REASONS},
        }

    def _funnel_new_poll(self) -> None:
        self._funnel["polls_total"] += 1

    def _funnel_pass(self, step_key: str) -> None:
        self._funnel["steps"][step_key]["passed"] += 1

    def _funnel_reject(self, step_key: str, reason: str, symbol: str = None, **ctx) -> None:
        """Incremente compteur funnel + emit log detaille (STEP 4-8 uniquement, rate limite 60s).

        STEP 1-3 = bruit (cooldown/ATTENDRE), on garde juste le counter.
        STEP 4-8 = signaux actionables qui meurent : log enrichi essentiel pour diagnostic.
        """
        self._funnel["steps"][step_key]["rejected"] += 1
        self._funnel["reject_detail"][reason] = self._funnel["reject_detail"].get(reason, 0) + 1
        if step_key in REJECT_LOG_STEPS and symbol:
            self._log_rejection_detailed(step_key, reason, symbol, ctx)

    def _log_rejection_detailed(self, step: str, reason: str, symbol: str, ctx: dict) -> None:
        """Log JSONL enrichi pour diagnostic. Rate limit 60s par (sym, reason).

        Fichier rotatif : LOGS/rejections/rejections_YYYYMMDD_paper.jsonl
        """
        now_ts = time.time()
        key = (symbol, reason)
        last_ts = self._reject_log_last_ts.get(key, 0)
        if now_ts - last_ts < REJECT_LOG_RATE_LIMIT_SEC:
            return  # anti-spam, counter deja incremente
        self._reject_log_last_ts[key] = now_ts

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "sym": symbol,
            "step": step,
            "reason": reason,
            **ctx,
        }
        fp = os.path.join(REJECTIONS_LOG_DIR, f"rejections_{self.date_str}_paper.jsonl")
        try:
            with open(fp, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError as e:
            if _v2log:
                try:
                    _v2log.emit("GENERIC_ALERTE", msg=f"rejection_log write failed: {e}")
                except Exception:
                    pass

        # 🆕 25/04 - Emit V2 vers LOGS/decisions/ pour tracage unified systeme V2
        # Rate limite deja applique ci-dessus (60s par sym+reason) -> pas de spam.
        # Cf DOCS/BOT_CHANGELOG.md 25/04 + .claude/rules/log-debug-protocol.md
        v2_code = REJECT_TO_V2_CODE.get(reason)
        if v2_code and _v2log:
            try:
                _v2log.emit(v2_code, sym=symbol, **ctx)
            except Exception:
                pass  # fail-safe : log V2 ne doit jamais bloquer le bot

    @staticmethod
    def _classify_sltp_reject(raw_reason: str) -> str:
        """Mappe le reject_reason SLTPResult vers une raison funnel granulaire.

        SLTPEngine emet 5 familles de rejets (mia_sltp.py:278-312) :
          - "Aucun mur T1/T2 derriere le prix"           -> sltp_no_wall
          - "T1 X trop loin (Yt > Zt)"                   -> sltp_no_wall (mur inaccessible)
          - "T2 X seul (pas de confluence)"              -> sltp_no_wall (manque confluence)
          - "SL hors limites (A-Bt)"                     -> sltp_out_of_range
          - "SL $X > budget $Y"                          -> sltp_budget_exceeded
          - "R:R X.XX < 0.8 (wall trop proche)"          -> sltp_rr_low
        """
        if not raw_reason:
            return "sltp_no_wall"
        up = raw_reason.upper()
        if "R:R" in up or "RR" in up.split() or "TROP PROCHE" in up:
            return "sltp_rr_low"
        if "BUDGET" in up:
            return "sltp_budget_exceeded"
        if "HORS LIMITES" in up:
            return "sltp_out_of_range"
        # Defaults : "aucun mur" / "T1 trop loin" / "T2 seul" / autre
        return "sltp_no_wall"

    def _funnel_snapshot(self) -> dict:
        """Serialise le funnel avec calculs % + drop + actionable pour state.json/dashboard."""
        polls = self._funnel["polls_total"]
        # Actionable = ce qui a passe le STEP 3 (conseil != ATTENDRE/CONFLIT)
        actionable = self._funnel["steps"].get(FUNNEL_ACTIONABLE_FROM_STEP, {}).get("passed", 0)
        steps_out = []
        for key, label, _ in FUNNEL_STEPS:
            s = self._funnel["steps"][key]
            passed = s["passed"]
            rejected = s["rejected"]
            attempted = passed + rejected
            drop_pct = round(rejected / polls * 100, 2) if polls else 0.0
            # rej_pct_of_actionable : valable uniquement pour STEP 4+ (post-actionable filter)
            rej_pct_act = None
            if key not in ("1_position_day", "2_cooldown_cb", "3_conseil") and actionable:
                rej_pct_act = round(rejected / actionable * 100, 2)
            # local_reject_rate : rejet / tentatives a ce step (utile pour regle isolee)
            local_reject_rate = round(rejected / attempted * 100, 2) if attempted else 0.0
            steps_out.append({
                "step": key,
                "label": label,
                "attempted": attempted,
                "passed": passed,
                "rejected": rejected,
                "drop_pct_of_polls": drop_pct,
                "local_reject_rate_pct": local_reject_rate,
                "rej_pct_of_actionable": rej_pct_act,
            })
        trades_taken = self._funnel["steps"]["8_payoff"]["passed"]
        conv = round(trades_taken / polls * 100, 3) if polls else 0.0
        return {
            "date": self._funnel["date"],
            "polls_total": polls,
            "actionable": actionable,
            "trades_taken": trades_taken,
            "conversion_rate_pct": conv,
            "steps": steps_out,
            "reject_detail": dict(self._funnel["reject_detail"]),
        }

    def _funnel_save_eod(self, date_str: str) -> None:
        """Ecrit un snapshot journalier avant rollover pour historique."""
        try:
            snap = self._funnel_snapshot()
            snap["saved_iso"] = datetime.now(timezone.utc).isoformat()
            fp = os.path.join(FUNNEL_LOG_DIR, f"funnel_{date_str}.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
        except Exception as e:
            if _v2log:
                try:
                    _v2log.emit("GENERIC_ALERTE", msg=f"funnel_save_eod failed: {e}")
                except Exception:
                    pass

    def check_entry(self, data, symbol):
        """Verifie si les conditions d'entree sont remplies (v2 22/04).

        Pipeline :
          1. Pas deja en position + max trades/jour
          2. Cooldown post-close + circuit breaker
          3. Conseil Global action != ATTENDRE
          4. freshness == "NEW" (state machine v1.5 fix)
          5. signal_id pas deja consomme (dedup)
          6. confidence + MTF passent
          7. SLTPEngine calcule SL/TP (mur Tier 1/2 derriere + TP1 avant obstacle)
          8. expected_payoff_$ >= seuil (filtre audit ES vs NQ)
        """
        sym = symbol.lower()
        instr = data.get(sym)
        if not instr:
            return None

        reg = instr.get("regime", {})
        banner = data.get("banner", {})
        price = banner.get(sym, {}).get("price", 0)
        if not price:
            return None

        # 🆕 25/04 - Enrichissement log V2 complet : market_ctx injecte dans TOUS les
        # rejets step 3-8 pour diagnostic pourquoi un poll meurt. Rate limite 60s
        # par (sym, reason) conserve (pas de spam).
        options = instr.get("options", {}) or {}
        market_ctx = {
            "dist_vwap_atr": round(reg.get("dist_vwap_atr", 0) or 0, 3),
            "atr": round(reg.get("atr", 0) or 0, 1),
            "session": reg.get("session_id") or "?",
            "vix_regime": reg.get("vix_regime"),
            "mq_dist_call_t": round(options.get("dist_mq_call", 0) or 0, 0),
            "mq_dist_put_t": round(options.get("dist_mq_put", 0) or 0, 0),
            "mq_dist_hvl_t": round(options.get("dist_mq_hvl", 0) or 0, 0),
            "mq_next_wall_t": round(options.get("next_wall_dist", 0) or 0, 0),
            "mq_next_wall_side": options.get("next_wall_side", "?"),
            "above_hvl": options.get("bool_above_mq_hvl", 0),
        }

        # Funnel : a partir d'ici on a un poll valide (data dashboard coherente).
        # On ne compte PAS les ticks sans prix/instrument car ce sont des erreurs
        # infra (dashboard down, symbol off), pas des rejets de regle metier.
        self._funnel_new_poll()

        # 1. Deja en position ? + max trades jour
        if symbol in self.positions:
            self._funnel_reject("1_position_day", "already_position")
            return None
        if self.trade_count >= ENTRY_RULES["max_trades_per_day"]:
            self._funnel_reject("1_position_day", "max_trades_day")
            return None
        self._funnel_pass("1_position_day")

        # 2. Cooldown post-close (anti re-entry contre-sens)
        now_ts = time.time()
        last_close = self._last_close_ts.get(symbol)
        if last_close and (now_ts - last_close) < ENTRY_RULES["cooldown_post_close_sec"]:
            self._funnel_reject("2_cooldown_cb", "cooldown_active")
            return None

        # 2bis. Circuit breaker (3 SL consec → pause 60min)
        pause_until = self._circuit_pause_until.get(symbol)
        if pause_until and now_ts < pause_until:
            self._funnel_reject("2_cooldown_cb", "circuit_breaker")
            return None
        self._funnel_pass("2_cooldown_cb")

        # 3. Conseil Global action
        conseil = data.get("conseil_global", {}).get(sym, {})
        action = conseil.get("action", "ATTENDRE")
        # 🆕 25/04 - context enrichi step 3 pour log V2 (audit ES 0 trade)
        # Capture les signaux qui auraient pu expliquer ATTENDRE : bull/bear pts,
        # MTF, bias, confidence, range_pos, dist_vwap. Rate limite 60s/sym/reason.
        bull_pts = conseil.get("bull_points", 0)
        bear_pts = conseil.get("bear_points", 0)
        step3_ctx = dict(
            action=action,
            bull_pts=bull_pts,
            bear_pts=bear_pts,
            bias=reg.get("bias", "?"),
            mtf_bulls=reg.get("mtf_bulls", 0),
            mtf_bears=reg.get("mtf_bears", 0),
            confidence=round(reg.get("bias_confidence", 0) or 0, 3),
            range_pos=reg.get("range_pos"),
            signal_id=conseil.get("signal_id"),
        )
        if action == "ATTENDRE":
            self._funnel_reject("3_conseil", "conseil_attendre",
                                symbol=symbol, **step3_ctx, **market_ctx)
            return None
        if action == "CONFLIT":
            self._funnel_reject("3_conseil", "conseil_conflit",
                                symbol=symbol, **step3_ctx, **market_ctx)
            return None
        self._funnel_pass("3_conseil")
        direction_int = 1 if "ACHAT" in action else -1
        direction = "LONG" if direction_int == 1 else "SHORT"
        prudent = "PRUDENT" in action

        # 🆕 FIX 24/04 : kill-switch auto SELL par symbole (audit #4 market-analyst)
        # Re-injection du blocage SELL si auto-disable declenche pour CE symbole.
        if direction == "SHORT" and self._sell_disabled.get(symbol, False):
            self._funnel_reject("3_conseil", "sell_auto_disabled",
                                symbol=symbol,
                                action=action,
                                reason=self._sell_disable_reason.get(symbol),
                                signal_id=conseil.get("signal_id"),
                                **market_ctx)
            return None

        # 4. freshness state machine v1.5 — NEW ou PERSISTENT (fix 24/04)
        # Dedup (STEP 5) protege contre trade multiple meme signal_id.
        freshness_v15 = conseil.get("freshness", "IDLE")
        required = ENTRY_RULES["freshness_required"]
        # Support backward compat : string (ancien format) ou tuple/list (nouveau).
        if isinstance(required, str):
            required = (required,)
        if freshness_v15 not in required:
            self._funnel_reject("4_freshness", "freshness_not_new",
                                symbol=symbol,
                                freshness_seen=freshness_v15,
                                required=list(required),
                                action=action,
                                signal_id=conseil.get("signal_id"),
                                **market_ctx)
            return None
        self._funnel_pass("4_freshness")

        # 5. Dedup via signal_id
        signal_id = conseil.get("signal_id")
        if signal_id and signal_id in self._traded_signal_ids:
            self._funnel_reject("5_dedup", "signal_already_traded",
                                symbol=symbol,
                                signal_id=signal_id,
                                action=action,
                                **market_ctx)
            return None
        self._funnel_pass("5_dedup")

        # 6. Confidence + MTF
        confidence = reg.get("bias_confidence", 0)
        min_conf = 0.40 if prudent else ENTRY_RULES["min_confidence"]
        if confidence < min_conf:
            self._funnel_reject("6_conf_mtf", "confidence_too_low",
                                symbol=symbol,
                                confidence=round(confidence, 3),
                                min_conf_required=min_conf,
                                action=action,
                                prudent=prudent,
                                **market_ctx)
            return None
        mtf_bulls = reg.get("mtf_bulls", 0)
        mtf_bears = reg.get("mtf_bears", 0)

        # 🆕 GATE MTF_BULL_DESERT (25/04 - cf DOCS/BOT_CHANGELOG.md 25/04)
        # Downside-only protection : SHORT dans "desert MTF" = ni bull clair ni bear clair
        # CONDITION : mtf_bulls<=1 ET mtf_bears<3 (sinon MTF est aligne bearish, SHORT legitime)
        # Backtest 24/04 : 18 trades mtf<=1 ET mtf_bears<3, WR 11%, PnL -372t (PF 0.23)
        # Fix regression : preserve SHORT execute 18:18 (mtf=0/3, MTF bearish aligne)
        # Market-analyst R2 confidence 4/5.
        # REDONDANCE : fonctionnellement redondant avec gate min_mtf_bears>=3 ci-dessous
        # (tout rejet ici serait aussi rejete par le gate suivant). Conserve pour :
        # (a) observabilite funnel — separe sous-bucket "desert" (18/j) du bucket
        #     generique "mtf_insufficient" (89/j sur jour 24/04)
        # (b) defense en profondeur si ENTRY_RULES['min_mtf_bears'] est relaxe un jour
        # REVERT : si backtest multi-jours (>=5j) montre WR>=40% sur bucket
        # mtf_bulls<=1 AND mtf_bears<3, retirer ce filtre (cf suivi post-deploy).
        if direction == "SHORT" and mtf_bulls <= 1 and mtf_bears < 3:
            self._funnel_reject("6_conf_mtf", "mtf_bull_desert",
                                symbol=symbol,
                                direction=direction,
                                mtf_bulls=mtf_bulls,
                                mtf_bears=mtf_bears,
                                confidence=round(confidence, 3),
                                action=action,
                                **market_ctx)
            return None

        if direction == "LONG" and mtf_bulls < ENTRY_RULES["min_mtf_bulls"]:
            self._funnel_reject("6_conf_mtf", "mtf_insufficient",
                                symbol=symbol,
                                direction=direction,
                                mtf_bulls=mtf_bulls,
                                mtf_bears=mtf_bears,
                                min_required=ENTRY_RULES["min_mtf_bulls"],
                                confidence=round(confidence, 3),
                                action=action,
                                **market_ctx)
            return None
        if direction == "SHORT" and mtf_bears < ENTRY_RULES["min_mtf_bears"]:
            self._funnel_reject("6_conf_mtf", "mtf_insufficient",
                                symbol=symbol,
                                direction=direction,
                                mtf_bulls=mtf_bulls,
                                mtf_bears=mtf_bears,
                                min_required=ENTRY_RULES["min_mtf_bears"],
                                confidence=round(confidence, 3),
                                action=action,
                                **market_ctx)
            return None
        self._funnel_pass("6_conf_mtf")

        # ─── Prerequis commun STEP 6bis + 7 : lecture bar DMP ────────────
        # Bar DMP complete OBLIGATOIRE (review agent R2 : reconstruct dashboard omet
        # ~30 murs MenthorQ/gamma/BL → SL biaise, verdict paper invalide). Si absent,
        # lire directement le dernier JSONL DMP (last line).
        bot_data = data.get("bot", {})
        bar_row_dict = bot_data.get("last_bars", {}).get(sym, {})
        if not bar_row_dict:
            bar_row_dict = self._read_last_jsonl_bar(symbol)
        if not bar_row_dict:
            # Pas de bar complete → skip trade (pas de fallback reconstruction biaise)
            # Attribue a STEP 6bis car bar est prereq commun pour bias + sltp (24/04)
            if _v2log:
                _v2log.emit("GENERIC_ALERTE",
                            msg=f"paper: skip {symbol} — bar DMP complete absente (bot.last_bars vide + JSONL unreadable)")
            self._funnel_reject("6bis_bias", "bar_dmp_missing",
                                symbol=symbol,
                                direction=direction,
                                action=action,
                                **market_ctx)
            return None

        # 6bis. BIAS GATE directionnel (3.7.9 — 24/04/2026 Jackson validation)
        # 🆕 FIX 24/04 soir (audit market-analyst Finding #2) : STEP 6bis supprimee
        # comme gate - bias devient soft-flag observabilite uniquement.
        #
        # Raison : `conseil_global.bias` (regime.get("bias") dans builders.py:151)
        # utilise deja compute_bias(bar) sur meme input. Rejet `bias_opposite_direction`
        # etait quasi-tautologique (meme fonction, meme bar → meme output).
        # Le scoring conseil_global integre deja bias comme 1/6 facteurs (poids 2/8).
        #
        # STEP 6bis conserve uniquement :
        #   - Prereq bar DMP (bar_row_dict non vide)
        #   - Soft-flag V2 log `bias_weak_but_aligned` pour observabilite
        bias = compute_bias(bar_row_dict)
        # Soft-flag observabilite : tracker performance des "weak but aligned"
        # pour decider post-N>=50 trades si on reintroduit un seuil empirique.
        if bias.bias_clarity < ENTRY_RULES["min_bias_clarity"]:
            if _v2log:
                try:
                    _v2log.emit("GENERIC_INFO",
                                msg=(f"bias_weak sym={symbol} dir={direction} "
                                     f"clarity={bias.bias_clarity:.2f} "
                                     f"bias={bias.direction} signal_id={signal_id}"))
                except Exception:
                    pass
        self._funnel_pass("6bis_bias")

        # ─── OBSERVATION cross-instrument (24/04 pre-Option 2, log-only) ───
        # Calcule le bonus/malus cross-instrument ES/NQ SANS IMPACTER la decision.
        # Objectif : collecter des stats empiriques sur 24-48h pour calibrer les
        # seuils (CONFIRM_BONUS=+2, CONFLICT_PENALTY=-4) avant integration dans
        # Phase Option 2 (confluence_score composite).
        # Anti-pattern 11 V1 : pas de gate bloquant, juste observation.
        try:
            other_sym = "ES" if symbol == "NQ" else "NQ"
            other_bar = self._read_last_jsonl_bar(other_sym)
            nq_bar_cross, es_bar_cross = (
                (bar_row_dict, other_bar)
                if symbol == "NQ"
                else (other_bar, bar_row_dict)
            )
            cross_result = compute_cross_bonus(nq_bar_cross, es_bar_cross)
            self._last_cross_context = {
                "ts_ms": int(time.time() * 1000),
                "triggered_by": symbol,
                "score_delta": cross_result.score_delta,
                "confirmed": cross_result.confirmed,
                "conflict": cross_result.conflict,
                "nq_direction": cross_result.nq_direction,
                "nq_clarity": round(cross_result.nq_clarity, 3),
                "es_direction": cross_result.es_direction,
                "es_clarity": round(cross_result.es_clarity, 3),
                "reasons": cross_result.reasons,
            }
            if _v2log:
                _v2log.emit(
                    "GENERIC_INFO",
                    msg=(
                        f"cross_obs {symbol}: delta={cross_result.score_delta:+d} "
                        f"NQ={cross_result.nq_direction}(cl={cross_result.nq_clarity:.2f}) "
                        f"ES={cross_result.es_direction}(cl={cross_result.es_clarity:.2f}) "
                        f"conf={cross_result.confirmed} confl={cross_result.conflict}"
                    ),
                )
        except Exception as e:
            # Mode observation ne doit JAMAIS faire echouer un trade
            if _v2log:
                _v2log.emit("GENERIC_ALERTE", msg=f"cross_obs failed: {e}")

        # 7. SLTPEngine — calcul intelligent Tier 1/2 murs + TP1
        engine = self.sltp_engines[symbol]
        sltp_result = engine.evaluate_single(bar_row_dict, direction_int)

        if not sltp_result.valid:
            # Granularite fine : classify reject_reason brut en 4 sous-raisons.
            sltp_rej = getattr(sltp_result, "reject_reason", "") or ""
            reason_fine = self._classify_sltp_reject(sltp_rej)
            self._funnel_reject("7_sltp", reason_fine,
                                symbol=symbol,
                                direction=direction,
                                price=price,
                                sltp_raw=sltp_rej,
                                sl_ticks_calc=getattr(sltp_result, "sl_ticks", 0),
                                sl_wall=getattr(sltp_result, "sl_wall", ""),
                                sl_n_walls=getattr(sltp_result, "sl_n_walls", 0),
                                tp1_ticks_calc=getattr(sltp_result, "tp1_ticks", 0),
                                tp1_wall=getattr(sltp_result, "tp1_wall", ""),
                                rr_calc=getattr(sltp_result, "rr_ratio", 0),
                                action=action,
                                signal_id=signal_id,
                                **market_ctx)
            return None
        self._funnel_pass("7_sltp")

        sl_ticks = sltp_result.sl_ticks
        tp_ticks = sltp_result.tp1_ticks  # Jackson choix : UN SEUL TP (pas trailing/runner)

        # 8. Filtre expected_payoff_$ (audit ES vs NQ 22/04) avec WR dynamique
        tv = TICK_VALUE[symbol]
        wr = self._get_dynamic_wr()   # 0.45 conservateur < 30 trades, puis rolling reel
        expected_payoff_usd = (wr * tp_ticks - (1 - wr) * sl_ticks) * tv * ENTRY_RULES["n_micros"]
        if expected_payoff_usd < ENTRY_RULES["min_expected_payoff_usd"]:
            self._funnel_reject("8_payoff", "expected_payoff_low",
                                symbol=symbol,
                                direction=direction,
                                sl_ticks=sl_ticks,
                                tp_ticks=tp_ticks,
                                rr=round(tp_ticks / sl_ticks, 2) if sl_ticks else 0,
                                wr_dynamic=round(wr, 3),
                                expected_payoff_usd=round(expected_payoff_usd, 2),
                                min_required_usd=ENTRY_RULES["min_expected_payoff_usd"],
                                sl_wall=sltp_result.sl_wall,
                                tp_wall=sltp_result.tp1_wall,
                                action=action,
                                signal_id=signal_id,
                                **market_ctx)
            return None
        self._funnel_pass("8_payoff")

        # Calcul prix
        if direction == "LONG":
            sl_price = round(price - sl_ticks * TICK_SIZE, 2)
            tp_price = round(price + tp_ticks * TICK_SIZE, 2)
        else:
            sl_price = round(price + sl_ticks * TICK_SIZE, 2)
            tp_price = round(price - tp_ticks * TICK_SIZE, 2)

        return {
            "direction": direction,
            "entry_price": price,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "sl_ticks": sl_ticks,
            "tp_ticks": tp_ticks,
            "sl_wall": sltp_result.sl_wall,
            "sl_tier": sltp_result.sl_wall_tier,
            "sl_reason": sltp_result.sl_reason,
            # Snapshot V2 ML-ready (22/04 soir Jackson) : full DMP bar + meta SLTP
            # pour permettre entrainement meta-labeler / primary avec la MEME vue
            # que le modele ML. Sans ca, snapshot = subset dashboard, ML aveugle.
            "dmp_bar": bar_row_dict,  # 266 features JSONL live
            "wr_dynamic_used": wr,
            "sltp_reject_reason": sltp_result.reject_reason if hasattr(sltp_result, "reject_reason") else None,
            "tp_wall": sltp_result.tp1_wall,
            "tp_reason": sltp_result.tp1_reason,
            "rr_ratio": sltp_result.rr_ratio,
            "sl_usd": sltp_result.sl_usd,
            "expected_payoff_usd": expected_payoff_usd,
            "confidence": confidence,
            "mtf_bulls": mtf_bulls,
            "mtf_bears": mtf_bears,
            "freshness": freshness_v15,
            "signal_id": signal_id,
            "conseil_action": action,
            "conseil_bull_pts": conseil.get("bull_points", 0),
            "conseil_bear_pts": conseil.get("bear_points", 0),
        }

    def _get_dynamic_wr(self) -> float:
        """WR conservateur 0.45 avant N trades, sinon WR rolling empirique (review R4).

        Evite biais initialisation : sans historique, assume setup peu performant
        (0.45) ce qui force filtre expected_payoff strict. Quand N >= 30 trades,
        switch vers WR reel des 30 derniers trades (adaptatif edge reel).
        """
        min_n = ENTRY_RULES["estimated_wr_rolling_min"]
        if len(self.today_trades) < min_n:
            # Charger trades historiques globaux pour accelerer convergence
            from glob import glob
            all_files = sorted(glob(os.path.join(DATA_DIR, "*_trades.jsonl")))
            all_trades = []
            for fp in all_files[-10:]:  # max 10 derniers jours
                try:
                    with open(fp, "r") as f:
                        for line in f:
                            s = line.strip()
                            if s:
                                try:
                                    all_trades.append(json.loads(s))
                                except json.JSONDecodeError:
                                    pass
                except OSError:
                    continue
            if len(all_trades) >= min_n:
                recent = all_trades[-min_n:]
                wins = sum(1 for t in recent if t.get("pnl_ticks", 0) > 0)
                return wins / len(recent)
            # Pas assez d'historique → conservateur
            return ENTRY_RULES["estimated_wr_initial"]

        # Rolling WR des 30 derniers trades du jour
        recent = self.today_trades[-min_n:]
        wins = sum(1 for t in recent if t.get("pnl_ticks", 0) > 0)
        return wins / len(recent)

    def _lookup_rules_tags(self, symbol: str, ts_event_open, ts_event_close) -> dict:
        """Lookup rules tags from parquet v5c for the given trade window.

        signal_engine_rules V1 integration (Plan B Jackson 27/04 soir).
        Reads parquet v5c (built nightly by batch_tagger), filters bars in trade
        window, returns max-strength fire per rule.

        Args:
            symbol: 'ES' or 'NQ'
            ts_event_open: open timestamp (epoch seconds, ms, or pd.Timestamp)
            ts_event_close: close timestamp (same)

        Returns:
            dict {rule_name: {'direction': int, 'strength': float}} per rule.
            Returns {} if parquet absent or no bars in window.
        """
        from pathlib import Path
        # v5d = v5b + 12 rules (9 V1 + 3 V2 pullback). Fallback v5c if missing.
        parquet_path = Path("DATA/datasets") / f"{symbol}_dataset_v5d.parquet"
        if not parquet_path.exists():
            parquet_path = Path("DATA/datasets") / f"{symbol}_dataset_v5c.parquet"
        if not parquet_path.exists():
            return {}
        try:
            import pandas as pd
            # Convert timestamps to UTC-aware
            def _to_ts(x):
                if isinstance(x, pd.Timestamp):
                    return x.tz_convert("UTC") if x.tz else x.tz_localize("UTC")
                if isinstance(x, (int, float)):
                    # Heuristic: if >= 1e12, treat as ms; else seconds
                    if x >= 1e12:
                        return pd.Timestamp(int(x), unit="ms", tz="UTC")
                    return pd.Timestamp(float(x), unit="s", tz="UTC")
                return pd.Timestamp(x).tz_localize("UTC")

            ts_open = _to_ts(ts_event_open)
            ts_close = _to_ts(ts_event_close)

            rule_names = [
                # V1 (9 rules)
                "long_up_bar", "long_dn_bar", "color_up_proximity",
                "color_dn_proximity", "color_zone_break", "cluster_at_high",
                "cluster_at_low", "failed_ib_poor_high", "edge_zone_fire",
                # V2 pullback (3 rules added 27/04)
                "pullback_continuation_buy", "pullback_continuation_sell",
                "pullback_mq_hvl_buy",
            ]
            cols_to_read = ["ts_event"] + [f"rule_{n}_dir" for n in rule_names] \
                + [f"rule_{n}_strength" for n in rule_names]
            df = pd.read_parquet(parquet_path, columns=cols_to_read)

            mask = (df["ts_event"] >= ts_open) & (df["ts_event"] <= ts_close)
            df_window = df[mask]
            if len(df_window) == 0:
                return {}

            result = {}
            for name in rule_names:
                dir_col = f"rule_{name}_dir"
                str_col = f"rule_{name}_strength"
                mask_fire = df_window[dir_col] != 0
                if mask_fire.any():
                    idx_max = df_window[mask_fire][str_col].idxmax()
                    result[name] = {
                        "direction": int(df_window.loc[idx_max, dir_col]),
                        "strength": float(df_window.loc[idx_max, str_col]),
                    }
                else:
                    result[name] = {"direction": 0, "strength": 0.0}
            return result
        except Exception as e:
            print(f"[WARN] _lookup_rules_tags failed: {type(e).__name__}: {e}")
            return {}

    def _read_last_jsonl_bar(self, symbol):
        """Lit la derniere ligne du JSONL DMP pour avoir bar complete (40+ features dist_*).

        Necessaire car dashboard expose seulement un sous-ensemble des features.
        SLTPEngine a besoin de tous les murs Tier 1/2/3 pour verdict fiable.
        """
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA", symbol)
        if not os.path.isdir(data_dir):
            return None
        # Dernier JSONL par mtime
        try:
            files = sorted(
                (f for f in os.listdir(data_dir) if f.endswith(".jsonl")),
                key=lambda n: os.path.getmtime(os.path.join(data_dir, n)),
                reverse=True,
            )
            if not files:
                return None
            latest = os.path.join(data_dir, files[0])
            # Lire derniere ligne (efficacement en scannant depuis la fin)
            with open(latest, "rb") as f:
                try:
                    f.seek(-2, os.SEEK_END)
                    while f.read(1) != b"\n":
                        f.seek(-2, os.SEEK_CUR)
                except OSError:
                    f.seek(0)
                last_line = f.readline().decode("utf-8")
            if last_line.strip():
                return json.loads(last_line)
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def _handle_dtc_fill(self, fill):
        """Callback DTC quand un ordre est Filled (status=7).

        Thread : daemon `_recv_loop` du DTCConnector. DOIT prendre le lock.

        3 cas :
          1. Fill parent : update position.entry_price avec vrai fill (slippage)
          2. Fill TP ou SL : close trade avec vrai exit price (broker-truth)
          3. CID inconnu : log, ignore
        """
        try:
            order_id = getattr(fill, "order_id", "")
            fill_price = getattr(fill, "fill_price", 0.0)
            if not order_id or not fill_price:
                return
            with self._pos_lock:
                symbol = self._order_to_symbol.get(order_id)
                if not symbol:
                    # CID inconnu (autre bot, anciens brackets, etc.)
                    return
                # Determiner le type de fill depuis le CID prefix
                is_parent = order_id.startswith("MIA_P_")
                is_tp = order_id.startswith("MIA_TP_")
                is_sl = order_id.startswith("MIA_SL_")

                pos = self.positions.get(symbol)

                if is_parent and pos:
                    # Update entry_price avec slippage reel broker + stocker slip_entry
                    old_entry = pos["entry_price"]
                    pos["entry_price"] = fill_price
                    # Signe oriente par direction : slip favorable (>0 gain) ou defavorable (<0)
                    dir_sign = 1 if pos["direction"] == "LONG" else -1
                    slip_ticks = round((fill_price - old_entry) / TICK_SIZE * dir_sign, 2)
                    pos["slip_entry_ticks"] = slip_ticks  # capture pour trade record ML
                    print(f"  >>> DTC FILL PARENT {symbol} @ {fill_price:.2f} (slip={slip_ticks:+.1f}t)")
                    if _v2log:
                        try:
                            _v2log.emit("ORDER_FILL", sym=symbol,
                                        fill_price=fill_price, slip_ticks=slip_ticks)
                        except Exception:
                            pass
                    return

                if (is_tp or is_sl) and pos:
                    # TP ou SL fill = close trade — capturer slip_exit + exit_order_id
                    outcome = "TP" if is_tp else "SL"
                    expected = pos.get("tp_price") if is_tp else pos.get("sl_price")
                    if expected:
                        # Pour LONG TP : fill >= tp_price = favorable positif
                        # Pour LONG SL : fill <= sl_price = bruit/slippage defavorable
                        dir_sign = 1 if pos["direction"] == "LONG" else -1
                        slip_exit = round((fill_price - expected) / TICK_SIZE * dir_sign, 2)
                    else:
                        slip_exit = 0.0
                    pos["slip_exit_ticks"] = slip_exit
                    pos["exit_order_id"] = order_id
                    print(f"  >>> DTC FILL {outcome} {symbol} @ {fill_price:.2f} (slip_exit={slip_exit:+.1f}t)")
                    self._close_trade(symbol, fill_price, outcome, from_dtc_callback=True)
                    return

                # Fill pour symbol qui n'est plus en position (ex: close simu apres race)
                if (is_tp or is_sl) and not pos:
                    # Fix B3 (code-reviewer 22/04) : `outcome` pas defini si pos is None
                    outcome_dbg = "TP" if is_tp else "SL"
                    print(f"  !!! DTC fill {outcome_dbg} {symbol} "
                          f"mais position deja closed en simu — OK (OCO a deja tout nettoye)")
                    if _v2log:
                        try:
                            _v2log.emit("GENERIC_ALERTE",
                                        msg=f"desync_simu_broker_fill_{symbol}",
                                        order_id=order_id)
                        except Exception:
                            pass
        except Exception as e:
            import traceback
            print(f"  !!! _handle_dtc_fill error: {e}\n{traceback.format_exc()}")

    def enter_trade(self, data, symbol, signal):
        """Ouvre une position paper.

        Si DTC actif : envoie bracket Sim3 (sync, attend fill parent <2s).
        Si bracket echoue : abort, aucune position memoire (coherence stricte).
        """
        sym = symbol.lower()
        instr = data.get(sym, {})
        reg = instr.get("regime", {})
        now = datetime.now(timezone.utc)

        # Integration DTC (22/04) : envoi bracket Sim3 AVANT creation position memoire
        parent_id = ""
        tp_cid = ""
        sl_cid = ""
        if self.dtc is not None:
            # Fix B1 (code-reviewer 22/04) : is_alive est @property dans dtc_connector,
            # pas une methode. Appel sans parentheses.
            if not self.dtc.is_alive:
                print(f"  !!! DTC disconnected -> skip {symbol} (retry next poll)")
                if _v2log:
                    try:
                        _v2log.emit("DTC_DISCONNECT_SESSION",
                                    sym=symbol, reason="is_alive=False")
                    except Exception:
                        pass
                return
            try:
                contract = DTC_INSTRUMENTS[symbol].contract
            except KeyError:
                print(f"  !!! contract inconnu pour {symbol} -> skip")
                return
            dtc_side = DTC_BUY if signal["direction"] == "LONG" else DTC_SELL
            print(f"  >>> DTC SUBMIT {symbol} {signal['direction']} qty={ENTRY_RULES['n_micros']} "
                  f"SL={signal['sl_price']:.2f} TP={signal['tp_price']:.2f} contract={contract}")
            parent_id, tp_cid, sl_cid = self.dtc.send_market_order(
                symbol=contract,
                side=dtc_side,
                quantity=ENTRY_RULES["n_micros"],
                sl_price=signal["sl_price"],
                tp_price=signal["tp_price"],
                trade_account=self.trade_account,
            )
            if not parent_id:
                print(f"  !!! DTC bracket FAIL {symbol} (parent timeout ou reject)")
                if _v2log:
                    try:
                        _v2log.emit("ORDER_REJECT",
                                    sym=symbol,
                                    reason="bracket_fail_parent_timeout_or_reject",
                                    signal_id=signal.get("signal_id"))
                    except Exception:
                        pass
                return
            print(f"  >>> DTC BRACKET OK parent={parent_id} tp={tp_cid} sl={sl_cid}")

        position = {
            "symbol": symbol,
            "direction": signal["direction"],
            "entry_price": signal["entry_price"],
            "entry_time": now.isoformat(),
            "entry_ts": now.timestamp(),
            "sl_price": signal["sl_price"],
            "tp_price": signal["tp_price"],
            "sl_ticks": signal["sl_ticks"],
            "tp_ticks": signal["tp_ticks"],
            # v2 (22/04) : enrichissement SL/TP intelligent
            "sl_wall": signal.get("sl_wall", ""),
            "sl_tier": signal.get("sl_tier", 0),
            "sl_reason": signal.get("sl_reason", ""),
            "tp_wall": signal.get("tp_wall", ""),
            "tp_reason": signal.get("tp_reason", ""),
            "rr_ratio": signal.get("rr_ratio", 0.0),
            "sl_usd": signal.get("sl_usd", 0.0),
            "expected_payoff_usd": signal.get("expected_payoff_usd", 0.0),
            "signal_id": signal.get("signal_id"),
            "n_micros": ENTRY_RULES["n_micros"],
            "mae": 0,  # max adverse excursion
            "mfe": 0,  # max favorable excursion
            "bars_held": 0,
            "current_price": signal["entry_price"],
            "unrealized_pnl_ticks": 0.0,
            "unrealized_pnl_usd": 0.0,
            # DTC bracket tracking
            "parent_id": parent_id,
            "tp_cid": tp_cid,
            "sl_cid": sl_cid,
            "dtc_enabled": self.dtc is not None,
        }

        # Dedup signal_id consomme (in-memory + persiste disque cross-restart)
        if signal.get("signal_id"):
            sid = signal["signal_id"]
            self._traded_signal_ids.add(sid)
            try:
                with open(self._traded_signals_file, "a", encoding="utf-8") as f:
                    f.write(f"{sid}\n")
            except OSError:
                pass

        # Snapshot V2 ML-ready (22/04 soir) : contient TOUT ce qu'il faut pour
        # entrainer primary/meta/filter ML a posteriori. Jackson : "crucial pour
        # amelioration bot". Taille ~15-20 KB / trade, ~30 MB / mois = negligeable.
        dmp_bar = signal.get("dmp_bar") or {}  # 266 features JSONL live
        snapshot = {
            "schema_version": "snapshot_v2_ml_2026_04_22",
            "trade_id": f"{self.date_str}_{self.trade_count + 1}",
            "signal_id": signal.get("signal_id"),
            "symbol": symbol,
            "direction": signal["direction"],
            "entry_price": signal["entry_price"],
            "entry_time": now.isoformat(),
            "entry_ts": now.timestamp(),
            "bar_ts_ms": dmp_bar.get("ts"),
            "sl_price": signal["sl_price"],
            "tp_price": signal["tp_price"],
            "sl_ticks": signal["sl_ticks"],
            "tp_ticks": signal["tp_ticks"],
            "n_micros": ENTRY_RULES["n_micros"],
            # SLTPEngine meta (walls + reason)
            "sl_wall": signal.get("sl_wall", ""),
            "sl_tier": signal.get("sl_tier", 0),
            "sl_reason": signal.get("sl_reason", ""),
            "tp_wall": signal.get("tp_wall", ""),
            "tp_reason": signal.get("tp_reason", ""),
            "rr_ratio": signal.get("rr_ratio", 0.0),
            "sl_usd": signal.get("sl_usd", 0.0),
            "sltp_reject_reason": signal.get("sltp_reject_reason"),
            # Decision meta
            "expected_payoff_usd": signal.get("expected_payoff_usd", 0.0),
            "wr_dynamic_used": signal.get("wr_dynamic_used"),
            "min_confidence_required": 0.40 if "PRUDENT" in signal.get("conseil_action", "") else ENTRY_RULES["min_confidence"],
            "confidence": signal["confidence"],
            "freshness": signal["freshness"],
            "mtf_bulls": signal["mtf_bulls"],
            "mtf_bears": signal["mtf_bears"],
            # Conseil Global
            "conseil_action": signal.get("conseil_action"),
            "conseil_bull_pts": signal.get("conseil_bull_pts"),
            "conseil_bear_pts": signal.get("conseil_bear_pts"),
            # DTC tracking
            "parent_id": parent_id,
            "tp_cid": tp_cid,
            "sl_cid": sl_cid,
            "dtc_enabled": self.dtc is not None,
            "trade_account": self.trade_account if self.dtc else None,
            # Full DMP bar (266 features — meme vue que le modele ML)
            "dmp_bar": dmp_bar,
            # Full instrument dashboard (regime, options, order_flow, battle_navale,
            # market_profile, initial_balance, levels, big_orders, suggestion, vix_gamma)
            "dashboard_instrument": instr,
            # Intermarket + narrative (contexte macro)
            "intermarket": data.get("intermarket", {}),
            "narrative": data.get("narrative", {}),
            # Patterns detail (pas juste bool)
            "patterns_daily": data.get("patterns", {}).get(sym, {}),
            "patterns_intraday": data.get("patterns_intraday", {}).get(sym, {}),
            # Fix P0-A ml-trainer (22/04 soir) : bloc ml_scores vide pour schema
            # stable. Permet au futur paper_trader Phase 2 (primary + meta models)
            # de remplir sans changer le format parquet. Snapshots pre-ML vs post-ML
            # identifiables par `ml_scores.model_version == None` OR pas None.
            "ml_scores": {
                "p_primary": None,
                "p_meta": None,
                "score_combined": None,
                "model_version": None,
                "kelly_f": None,
            },
        }

        # Thread-safe update : positions + order_to_symbol mapping
        with self._pos_lock:
            self.positions[symbol] = position
            self.trade_count += 1
            # Mapping CID -> symbol pour callback _handle_dtc_fill
            for cid in (parent_id, tp_cid, sl_cid):
                if cid:
                    self._order_to_symbol[cid] = symbol

        # Ecrire le snapshot
        with open(self.snapshot_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")

        print(f"  >>> ENTREE {signal['direction']} {symbol} @ {signal['entry_price']:.2f} | "
              f"SL={signal['sl_price']:.2f} [{signal.get('sl_wall','?')} T{signal.get('sl_tier','?')}] "
              f"TP={signal['tp_price']:.2f} [{signal.get('tp_wall','?')}] "
              f"RR={signal.get('rr_ratio',0):.2f} Exp=${signal.get('expected_payoff_usd',0):.1f} | "
              f"Conf={signal['confidence']*100:.0f}%")

        # V2 log
        if _v2log:
            _v2log.emit("TRADE_OPEN", sym=symbol, direction=signal["direction"],
                        size=ENTRY_RULES["n_micros"], price=signal["entry_price"],
                        signal_id=signal.get("signal_id"))

        # Write state.json pour dashboard bridge
        self._write_state()

    def check_exit(self, data, symbol):
        """Verifie SL/TP sur la position ouverte."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        sym = symbol.lower()
        banner = data.get("banner", {})
        price = banner.get(sym, {}).get("price", 0)
        if not price:
            return

        pos["bars_held"] += 1

        # Calculer MAE/MFE + PnL unrealized
        if pos["direction"] == "LONG":
            excursion = (price - pos["entry_price"]) / TICK_SIZE
        else:
            excursion = (pos["entry_price"] - price) / TICK_SIZE

        if excursion > pos["mfe"]:
            pos["mfe"] = round(excursion, 1)
        if excursion < pos["mae"]:
            pos["mae"] = round(excursion, 1)

        # PnL unrealized (pour state.json live)
        tv = TICK_VALUE.get(symbol, TICK_SIZE)
        pos["current_price"] = price
        pos["unrealized_pnl_ticks"] = round(excursion, 1)
        pos["unrealized_pnl_usd"] = round(excursion * tv * pos.get("n_micros", 3), 2)

        # Check SL
        hit_sl = False
        hit_tp = False
        if pos["direction"] == "LONG":
            if price <= pos["sl_price"]:
                hit_sl = True
            if price >= pos["tp_price"]:
                hit_tp = True
        else:
            if price >= pos["sl_price"]:
                hit_sl = True
            if price <= pos["tp_price"]:
                hit_tp = True

        # Timeout — 120 barres (2h)
        timeout = pos["bars_held"] >= 120

        if hit_tp or hit_sl or timeout:
            self._close_trade(symbol, price, "TP" if hit_tp else "SL" if hit_sl else "TIMEOUT")

    def _close_trade(self, symbol, exit_price, outcome, from_dtc_callback=False):
        """Ferme et enregistre le trade (v2 22/04 avec cooldown + circuit breaker).

        Si from_dtc_callback=True : fill broker deja recu, les brackets OCO sont
        deja canceled par DTCConnector._handle_order_update. On fait juste la
        comptabilite memoire + state.json.

        Si from_dtc_callback=False : fermeture declenchee par simu (check_exit
        detecte hit_sl/hit_tp/timeout). Il faut cancel les brackets Sim3 + envoyer
        un close market sinon position reste ouverte cote Sierra Chart.
        """
        with self._pos_lock:
            if symbol not in self.positions:
                # Deja close (idempotent)
                return
            pos = self.positions.pop(symbol)
            # Cleanup mapping order_to_symbol
            for cid_key in ("parent_id", "tp_cid", "sl_cid"):
                cid = pos.get(cid_key)
                if cid:
                    self._order_to_symbol.pop(cid, None)

        # Fix B2 (code-reviewer 22/04) : race destructrice si simu declenche close
        # avant que le callback broker fill n'arrive → reverse market creait une
        # position inverse fantome si les brackets etaient deja fill.
        # Solution retenue (Option C) : TRUST OCO BROKER. Quand la simu detecte un
        # hit (banner price), on cancel les 2 brackets (idempotent si deja fill).
        # Si les brackets sont encore live → OCO cancel le oppose au prochain fill.
        # Si les brackets sont deja fill → cancel = no-op silencieux, rien d'envoye.
        # Aucun "reverse market" : on ne cree JAMAIS une position inverse Sim3.
        # La seule source de verite pour la sortie Sim3 = fill broker via on_fill.
        # Exception : outcome=TIMEOUT → on force fermeture via close market (no SL/TP)
        # car aucun bracket n'aurait declenche naturellement.
        if not from_dtc_callback and self.dtc is not None and pos.get("dtc_enabled"):
            try:
                # Cancel TP + SL (idempotent si deja fill broker)
                for cid_key in ("tp_cid", "sl_cid"):
                    cid = pos.get(cid_key)
                    if cid:
                        try:
                            self.dtc.cancel_order(cid, trade_account=self.trade_account)
                        except Exception as e:
                            print(f"  warn cancel {cid}: {e}")

                # SEULEMENT pour TIMEOUT : broker n'a rien fill, on force close market
                if outcome == "TIMEOUT":
                    try:
                        contract = DTC_INSTRUMENTS[symbol].contract
                        reverse_side = DTC_SELL if pos["direction"] == "LONG" else DTC_BUY
                        close_id, _, _ = self.dtc.send_market_order(
                            symbol=contract,
                            side=reverse_side,
                            quantity=pos.get("n_micros", 3),
                            sl_price=0, tp_price=0,
                            trade_account=self.trade_account,
                        )
                        print(f"  >>> DTC CLOSE TIMEOUT {symbol} market cid={close_id}")
                        if not close_id and _v2log:
                            try:
                                _v2log.emit("ORDER_REJECT",
                                            sym=symbol, reason="timeout_close_market_fail")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"  !!! DTC TIMEOUT close FAIL {symbol}: {e}")
                else:
                    # TP/SL declenche par simu : on fait confiance au broker.
                    # Log descriptif pour traceabilite analyse desync ex-post.
                    print(f"  >>> DTC {outcome} simu-triggered {symbol}, brackets canceled, trust broker fill via on_fill")
            except Exception as e:
                print(f"  !!! DTC cleanup FAIL {symbol}: {e}")

        now = datetime.now(timezone.utc)

        if pos["direction"] == "LONG":
            pnl_ticks = round((exit_price - pos["entry_price"]) / TICK_SIZE, 1)
        else:
            pnl_ticks = round((pos["entry_price"] - exit_price) / TICK_SIZE, 1)

        # PnL $ (3 micros)
        tv = TICK_VALUE.get(symbol, TICK_SIZE)
        n_mic = pos.get("n_micros", 3)
        pnl_usd = round(pnl_ticks * tv * n_mic, 2)

        entry_ts_val = pos.get("entry_ts", 0) or now.timestamp()
        exit_ts_val = now.timestamp()
        duration_sec = round(max(0.0, exit_ts_val - entry_ts_val), 1)

        # Snapshot V2 ML-ready (22/04 soir) : exit_context minimal pour meta-labeler
        # timing + ML post-hoc analysis. Prend le cache dashboard (dernier payload).
        exit_context = None
        data_cache = self._last_dashboard_data or {}
        sym_lc = symbol.lower()
        instr_cache = data_cache.get(sym_lc, {}) or {}
        reg_cache = instr_cache.get("regime", {}) or {}
        flow_cache = instr_cache.get("order_flow", {}) or {}
        if data_cache:
            exit_context = {
                "bar_ts_ms": data_cache.get("banner", {}).get(sym_lc, {}).get("ts"),
                "price": data_cache.get("banner", {}).get(sym_lc, {}).get("price"),
                "vix": reg_cache.get("vix"),
                "atr": reg_cache.get("atr"),
                "rvol": flow_cache.get("rvol"),
                "delta_day_dir": flow_cache.get("delta_day_dir"),
                "regime_bias": reg_cache.get("bias"),
                "regime_mode": reg_cache.get("mode"),
                "regime_favor": reg_cache.get("favor"),
                "conseil_action": data_cache.get("conseil_global", {}).get(sym_lc, {}).get("action"),
            }

        # Fix P0-B ml-trainer (22/04 soir) : FULL snapshot au close pour meta-labeler
        # exit timing (Lopez ch.3 triple-barrier). Sans dmp_bar_at_exit + dashboard
        # complet, impossible d'entrainer "faut-il tenir malgre TP approchant" ou
        # "faut-il sortir avant SL sur divergence". +30 MB/mois acceptable.
        dmp_bar_at_exit = self._read_last_jsonl_bar(symbol) or {}
        intermarket_at_exit = data_cache.get("intermarket", {}) or {}

        expected_payoff = pos.get("expected_payoff_usd", 0.0)
        realized_vs_expected_pct = round(pnl_usd / expected_payoff * 100, 1) if expected_payoff else None

        trade = {
            "schema_version": "trade_v2_ml_2026_04_22",
            "trade_id": f"{self.date_str}_{len(self.today_trades) + 1}",
            "symbol": symbol,
            "direction": pos["direction"],
            "entry_price": pos["entry_price"],
            "entry_time": pos["entry_time"],
            "entry_ts": entry_ts_val,
            "exit_price": exit_price,
            "exit_time": now.isoformat(),
            "exit_ts": exit_ts_val,
            # Fix B2 (code-reviewer 22/04) : expose `exit_reason` + `outcome`
            "outcome": outcome,
            "exit_reason": outcome,
            "pnl_ticks": pnl_ticks,
            "pnl_usd": pnl_usd,
            "mae": pos["mae"],
            "mfe": pos["mfe"],
            "bars_held": pos["bars_held"],
            "duration_sec": duration_sec,
            # v2 enrichissement SL/TP
            "sl_wall": pos.get("sl_wall", ""),
            "sl_tier": pos.get("sl_tier", 0),
            "tp_wall": pos.get("tp_wall", ""),
            "rr_ratio": pos.get("rr_ratio", 0.0),
            "n_micros": n_mic,
            "signal_id": pos.get("signal_id"),
            # Snapshot V2 ML-ready : slippage + DTC link + expected vs realized
            "slip_entry_ticks": pos.get("slip_entry_ticks", 0.0),
            "slip_exit_ticks": pos.get("slip_exit_ticks", 0.0),
            "parent_id": pos.get("parent_id", ""),
            "tp_cid": pos.get("tp_cid", ""),
            "sl_cid": pos.get("sl_cid", ""),
            "exit_order_id": pos.get("exit_order_id", ""),
            "dtc_enabled": pos.get("dtc_enabled", False),
            "expected_payoff_usd": expected_payoff,
            "realized_vs_expected_pct": realized_vs_expected_pct,
            # Exit context (marche au moment du close) pour meta-labeler
            "exit_context": exit_context,
            # Fix P0-B ml-trainer (22/04 soir) : FULL snapshot close pour
            # meta-labeler exit timing. Contient les 266 features DMP + dashboard
            # complet au moment exact du close.
            "dmp_bar_at_exit": dmp_bar_at_exit,
            "dashboard_instrument_at_exit": instr_cache,
            "intermarket_at_exit": intermarket_at_exit,
            # Bloc ml_scores symetrique a entry (Phase 2 : exit model scoring)
            "ml_scores_exit": {
                "p_exit_early": None,
                "p_hold_longer": None,
                "exit_model_version": None,
            },
            # signal_engine_rules V1 integration (Plan B Jackson 27/04 soir).
            # Tags des 9 regles fired pendant la fenetre du trade (lookup parquet v5c).
            # Utile pour analyse comportementale + dataset re-training ML futur.
            "rules_fired": self._lookup_rules_tags(
                symbol=symbol,
                ts_event_open=entry_ts_val,
                ts_event_close=exit_ts_val,
            ),
            "rules_schema_version": "1.0",
        }

        self.today_trades.append(trade)

        # 🆕 FIX 24/04 : kill-switch auto SELL par symbole (audit #4 market-analyst).
        # 🆕 FIX 24/04 soir (R1 code-reviewer) : sous _pos_lock car close_position
        #   peut etre appelee depuis thread DTC (_handle_dtc_fill daemon).
        # Seuil DD = max_sl_ticks[symbol] * 1.5 pour etre symmetrique :
        #   NQ max_sl=80 → kill DD > 120t (1.5 trades plein)
        #   ES max_sl=40 → kill DD > 60t (1.5 trades plein)
        if pos.get("direction") == "SHORT":
            with self._pos_lock:
                sym_list = self._sell_trades_today.setdefault(symbol, [])
                sym_list.append(trade)
                if pnl_ticks < 0:
                    self._sell_dd_intraday_ticks[symbol] = (
                        self._sell_dd_intraday_ticks.get(symbol, 0.0) + abs(pnl_ticks)
                    )
                n_sell = len(sym_list)
                sell_wins = sum(1 for t in sym_list if t.get("pnl_ticks", 0) > 0)
                sell_wr = sell_wins / n_sell if n_sell else 0
                # Seuil DD asymmetrique par symbole (SL_BUDGET importe top-level).
                max_sl_sym = SL_BUDGET.get(symbol, {}).get("max_ticks", 50)
                dd_threshold = max_sl_sym * 1.5
                dd_intra = self._sell_dd_intraday_ticks.get(symbol, 0.0)
                if dd_intra > dd_threshold:
                    self._sell_disabled[symbol] = True
                    self._sell_disable_reason[symbol] = (
                        f"SELL auto-disabled {symbol}: DD intraday {dd_intra:.0f}t > "
                        f"{dd_threshold:.0f}t threshold (max_sl {max_sl_sym}t × 1.5)"
                    )
                elif n_sell >= 20 and sell_wr < 0.25:
                    self._sell_disabled[symbol] = True
                    self._sell_disable_reason[symbol] = (
                        f"SELL auto-disabled {symbol}: N={n_sell} trades "
                        f"WR={sell_wr:.2%} < 25% threshold"
                    )
                disabled_now = self._sell_disabled.get(symbol, False)
                reason_now = self._sell_disable_reason.get(symbol)
            # Emit V2 log hors lock (I/O potentiellement lent)
            if disabled_now and _v2log and reason_now:
                try:
                    _v2log.emit("GENERIC_MAJEUR", msg=reason_now)
                except Exception:
                    pass

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(trade, ensure_ascii=False) + "\n")

        color = "WIN" if pnl_ticks > 0 else "LOSS"
        print(f"  <<< SORTIE {outcome} {symbol} @ {exit_price:.2f} | "
              f"PnL={pnl_ticks:+.1f}t ${pnl_usd:+.2f} | "
              f"MAE={pos['mae']:.1f} MFE={pos['mfe']:.1f} | {color}")

        # V2 log + state
        if _v2log:
            code_map = {"TP": "TRADE_CLOSE_TP", "SL": "TRADE_CLOSE_SL", "TIMEOUT": "TRADE_CLOSE_TIMEOUT"}
            _v2log.emit(code_map.get(outcome, "TRADE_CLOSE_MANUAL"),
                        sym=symbol, pnl=pnl_ticks, signal_id=pos.get("signal_id"))

        # Cooldown post-close (anti re-entry contre-sens)
        self._last_close_ts[symbol] = time.time()

        # Circuit breaker : 3 SL consec → pause 60 min
        if outcome == "SL":
            self._consec_losses[symbol] = self._consec_losses.get(symbol, 0) + 1
            if self._consec_losses[symbol] >= ENTRY_RULES["circuit_breaker_losses"]:
                self._circuit_pause_until[symbol] = time.time() + ENTRY_RULES["circuit_breaker_pause_sec"]
                print(f"  !!! CIRCUIT BREAKER {symbol} : 3 SL consec → pause 60 min")
                if _v2log:
                    _v2log.emit("CIRCUIT_BREAKER_TRIP",
                                sym=symbol,
                                consec_losses=ENTRY_RULES["circuit_breaker_losses"],
                                pause_min=ENTRY_RULES["circuit_breaker_pause_sec"] // 60)
                self._consec_losses[symbol] = 0  # reset
        else:
            self._consec_losses[symbol] = 0  # win = reset

        self._write_state()

    def _write_state(self):
        """Ecrit state.json pour bridge dashboard (endpoint /api/paper_trades).

        Overwrite a chaque tick (live view). Contient :
          - open_by_symbol : positions en cours (PnL unrealized live)
          - closed_today : trades fermes du jour (last 20)
          - stats_today : WR, PF, pnl total, count par instrument
          - cooldown_status : info cooldown post-close + circuit breaker
        """
        now_ts = time.time()

        # Open positions avec PnL live
        open_by_symbol = {}
        for sym, pos in self.positions.items():
            open_by_symbol[sym] = {
                "trade_id": pos.get("trade_id"),
                "signal_id": pos.get("signal_id"),
                "direction": pos["direction"],
                "entry_price": pos["entry_price"],
                "entry_time": pos["entry_time"],
                "entry_ts": pos.get("entry_ts", 0),
                "sl_price": pos["sl_price"],
                "tp_price": pos["tp_price"],
                "sl_ticks": pos["sl_ticks"],
                "tp_ticks": pos["tp_ticks"],
                "sl_wall": pos.get("sl_wall", ""),
                "sl_tier": pos.get("sl_tier", 0),
                "tp_wall": pos.get("tp_wall", ""),
                "rr_ratio": pos.get("rr_ratio", 0),
                "n_micros": pos.get("n_micros", 3),
                "bars_held": pos["bars_held"],
                "mae": pos["mae"],
                "mfe": pos["mfe"],
                "current_price": pos.get("current_price", pos["entry_price"]),
                "unrealized_pnl_ticks": pos.get("unrealized_pnl_ticks", 0),
                "unrealized_pnl_usd": pos.get("unrealized_pnl_usd", 0),
                "expected_payoff_usd": pos.get("expected_payoff_usd", 0),
            }

        # Closed trades today (last 20 recent first)
        closed_today = list(reversed(self.today_trades[-20:]))

        # Stats today
        wins = [t for t in self.today_trades if t.get("pnl_ticks", 0) > 0]
        losses = [t for t in self.today_trades if t.get("pnl_ticks", 0) <= 0]
        win_ticks = sum(t["pnl_ticks"] for t in wins) if wins else 0
        loss_ticks = sum(abs(t["pnl_ticks"]) for t in losses) if losses else 0
        total_pnl_usd = sum(t.get("pnl_usd", 0) for t in self.today_trades)
        stats_today = {
            "trades": len(self.today_trades),
            "wins": len(wins),
            "losses": len(losses),
            "wr": round(len(wins) / max(1, len(self.today_trades)) * 100, 1),
            "pf": round(win_ticks / loss_ticks, 2) if loss_ticks > 0 else None,
            "pnl_usd": round(total_pnl_usd, 2),
            "pnl_ticks": round(sum(t["pnl_ticks"] for t in self.today_trades), 1),
        }

        # Stats par instrument
        stats_by_sym = {}
        for sym in ("ES", "NQ"):
            subset = [t for t in self.today_trades if t.get("symbol") == sym]
            sw = [t for t in subset if t.get("pnl_ticks", 0) > 0]
            sl = [t for t in subset if t.get("pnl_ticks", 0) <= 0]
            stats_by_sym[sym] = {
                "trades": len(subset),
                "wins": len(sw),
                "losses": len(sl),
                "wr": round(len(sw) / max(1, len(subset)) * 100, 1) if subset else 0,
                "pnl_usd": round(sum(t.get("pnl_usd", 0) for t in subset), 2),
            }

        # Cooldown + circuit breaker status
        cooldown_status = {}
        for sym in ("ES", "NQ"):
            last_close = self._last_close_ts.get(sym, 0)
            cooldown_remaining = max(0, ENTRY_RULES["cooldown_post_close_sec"] - (now_ts - last_close)) if last_close else 0
            pause_until = self._circuit_pause_until.get(sym, 0)
            circuit_remaining = max(0, pause_until - now_ts) if pause_until else 0
            cooldown_status[sym] = {
                "cooldown_remaining_sec": int(cooldown_remaining),
                "circuit_breaker_remaining_sec": int(circuit_remaining),
                "consec_losses": self._consec_losses.get(sym, 0),
            }

        state = {
            "updated_ts": now_ts,
            "updated_iso": datetime.now(timezone.utc).isoformat(),
            "date": self.date_str,
            "open_by_symbol": open_by_symbol,
            "closed_today": closed_today,
            "stats_today": stats_today,
            "stats_by_symbol": stats_by_sym,
            "cooldown_status": cooldown_status,
            "trade_count_today": self.trade_count,
            "max_trades_per_day": ENTRY_RULES["max_trades_per_day"],
            # Funnel check_entry (23/04 Jackson) — diagnostic "pourquoi 0 trade"
            "entry_funnel_today": self._funnel_snapshot(),
            # 24/04 observation cross-instrument (mode log-only, pre Option 2)
            "last_cross_context": self._last_cross_context,
            # 24/04 regime GEX MenthorQ (daily, PAS un gate — diagnostic + dashboard)
            "menthorq_regime": self._menthorq_regime,
            # 24/04 kill-switch admin (reserve #2 code-reviewer : expose etat au front)
            # Quand True : dashboard masque metriques stale + badge "KILL_SWITCH ACTIVE"
            "kill_switch": {
                "active": self._stop_flag_active,
                "activated_at": self._stop_flag_activated_at if self._stop_flag_active else None,
                "pending_flatten_sec": (
                    int(now_ts - self._stop_flag_activated_at)
                    if self._stop_flag_active and self.positions else 0
                ),
            },
        }

        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            if _v2log:
                _v2log.emit("GENERIC_MAJEUR", msg=f"write_state failed: {e}")

    def run(self):
        """Boucle principale du paper trader."""
        print(f"MIA Paper Trader - {self.date_str}")
        print(f"Regles v2: conf>{ENTRY_RULES['min_confidence']*100:.0f}% MTF>={ENTRY_RULES['min_mtf_bears']}/4 "
              f"freshness={ENTRY_RULES['freshness_required']} n_micros={ENTRY_RULES['n_micros']} "
              f"min_exp=${ENTRY_RULES['min_expected_payoff_usd']} "
              f"cooldown={ENTRY_RULES['cooldown_post_close_sec']//60}min "
              f"circuit_breaker={ENTRY_RULES['circuit_breaker_losses']}SL/{ENTRY_RULES['circuit_breaker_pause_sec']//60}min")
        print(f"Log: {self.log_file}")
        print(f"Poll: {POLL_INTERVAL}s")
        print("-" * 60)

        self._last_status_minute = -1  # Fix R7 : anti-spam prints
        consec_errors = 0

        while True:
            try:
                # Fix B4 (code-reviewer 22/04) : rollover date UTC si bot tourne > 24h
                self._rotate_day_if_needed()

                data = get_dashboard()
                if not data:
                    time.sleep(POLL_INTERVAL)
                    continue
                # Cache pour exit_context snapshot V2 (utilise par _close_trade
                # quand declenche depuis callback DTC sans data en param)
                self._last_dashboard_data = data

                now = datetime.now(timezone.utc).strftime("%H:%M:%S")

                # ==================== Kill-switch admin STOP.flag (24/04) ====================
                # POST /api/bot/stop cree le flag → on flatten + pause.
                # POST /api/bot/start supprime le flag → on reprend.
                # En pause : pas de check_entry/exit, juste _write_state + sleep + poll flag.
                # Resolve reserve #1 code-reviewer : retry flatten a CHAQUE tick pause
                # tant que positions ouvertes (couvre case banner price=0 transitoire).
                # Alerte MAJEUR si flatten pending > 30s.
                if os.path.exists(STOP_FLAG_FILE):
                    if not self._stop_flag_active:
                        self._stop_flag_active = True
                        self._stop_flag_activated_at = time.time()
                        self._stop_flag_stale_alerted = False
                        print(f"  [{now}] [KILL_SWITCH] STOP.flag detecte -> flatten + pause")
                        if _v2log:
                            _v2log.emit("BOT_KILL_SWITCH_ACTIVATED", n_closed=0)

                    # Retry flatten a chaque tick pause tant que positions ouvertes
                    with self._pos_lock:
                        symbols_open = list(self.positions.keys())
                    for sym in symbols_open:
                        banner = data.get("banner", {}).get(sym.lower(), {})
                        flatten_price = banner.get("price", 0)
                        if flatten_price > 0:
                            try:
                                self._close_trade(sym, flatten_price, "KILL_SWITCH")
                                print(f"  [{now}] [KILL_SWITCH] flatten {sym} @ {flatten_price}")
                            except Exception as exc:
                                print(f"  [{now}] [KILL_SWITCH] flatten {sym} fail: {exc}")
                                if _v2log:
                                    _v2log.emit("GENERIC_MAJEUR",
                                                msg=f"kill_switch flatten {sym} failed: {exc}")

                    # Alerte si flatten pending > 30s (banner price=0 persistant)
                    with self._pos_lock:
                        still_open = list(self.positions.keys())
                    pending_sec = time.time() - self._stop_flag_activated_at
                    if still_open and pending_sec > 30 and not self._stop_flag_stale_alerted:
                        self._stop_flag_stale_alerted = True
                        print(f"  [{now}] [KILL_SWITCH] ALERTE : flatten pending {pending_sec:.0f}s positions={still_open}")
                        if _v2log:
                            _v2log.emit("GENERIC_MAJEUR",
                                        msg=f"kill_switch flatten pending {pending_sec:.0f}s : {still_open} (banner price absent)")

                    self._write_state()
                    consec_errors = 0
                    time.sleep(5)
                    continue
                elif self._stop_flag_active:
                    # Transition PAUSE → ACTIF : flag supprime via /api/bot/start
                    self._stop_flag_active = False
                    self._stop_flag_activated_at = 0.0
                    self._stop_flag_stale_alerted = False
                    print(f"  [{now}] [KILL_SWITCH] STOP.flag supprime -> reprise trading")
                    if _v2log:
                        _v2log.emit("BOT_KILL_SWITCH_RELEASED")
                # ==============================================================================

                for symbol in ("ES", "NQ"):
                    # Check exit sur positions ouvertes
                    self.check_exit(data, symbol)

                    # Check entree si pas en position
                    signal = self.check_entry(data, symbol)
                    if signal:
                        self.enter_trade(data, symbol, signal)

                # Write state.json pour dashboard (chaque tick, live PnL unrealized)
                self._write_state()

                # Status toutes les 5 min (anti-spam via _last_status_minute)
                minute = datetime.now(timezone.utc).minute
                if minute % 5 == 0 and minute != self._last_status_minute:
                    self._last_status_minute = minute
                    wins = sum(1 for t in self.today_trades if t["pnl_ticks"] > 0)
                    losses = sum(1 for t in self.today_trades if t["pnl_ticks"] <= 0)
                    total_pnl = sum(t["pnl_ticks"] for t in self.today_trades)
                    open_pos = ", ".join(f"{s} {p['direction']}" for s, p in self.positions.items()) or "aucune"
                    print(f"  [{now}] Trades: {len(self.today_trades)} ({wins}W/{losses}L) PnL: {total_pnl:+.1f}t | Positions: {open_pos}")

                consec_errors = 0  # reset sur tick OK
                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                print("\nArret du paper trader.")
                self._print_stats()
                # Shutdown gracieux DTC (ne flatte PAS les positions Sim3 --
                # Jackson veut les garder visibles pour review visuelle)
                if self.dtc is not None:
                    try:
                        self.dtc.disconnect()
                        print("  DTC disconnected (positions Sim3 preservees)")
                    except Exception as e:
                        print(f"  warn DTC disconnect: {e}")
                break
            except Exception as e:
                # Fix B5 (code-reviewer 22/04) : cascade protection VPS 24/7
                consec_errors += 1
                import traceback
                print(f"  !!! ERREUR paper_trader (#{consec_errors}) : {type(e).__name__}: {e}")
                print(traceback.format_exc())
                if _v2log:
                    try:
                        _v2log.emit("GENERIC_MAJEUR",
                                    component="paper_trader",
                                    error_type=type(e).__name__,
                                    error_msg=str(e)[:200],
                                    consec=consec_errors)
                    except Exception:
                        pass
                if consec_errors >= 10:
                    print(f"  !!! 10 erreurs consecutives — arret paper_trader (watchdog nssm relance)")
                    if _v2log:
                        try:
                            _v2log.emit("BOT_CRASH", component="paper_trader", consec=consec_errors)
                        except Exception:
                            pass
                    raise
                time.sleep(POLL_INTERVAL)

    def _print_stats(self):
        """Affiche les stats de la session."""
        if not self.today_trades:
            print("Aucun trade aujourd'hui.")
            return

        # Fix mineur #3 (code-reviewer 22/04) : tolerance trades legacy sans `outcome`
        def _oc(t): return t.get("outcome") or t.get("exit_reason") or "?"
        wins = [t for t in self.today_trades if _oc(t) == "TP"]
        losses = [t for t in self.today_trades if _oc(t) == "SL"]
        timeouts = [t for t in self.today_trades if _oc(t) == "TIMEOUT"]
        total_pnl = sum(t["pnl_ticks"] for t in self.today_trades)
        win_pnl = sum(t["pnl_ticks"] for t in wins)
        loss_pnl = sum(abs(t["pnl_ticks"]) for t in losses)

        wr = len(wins) / len(self.today_trades) * 100
        pf = win_pnl / loss_pnl if loss_pnl > 0 else float("inf")
        ev = total_pnl / len(self.today_trades)

        print(f"\n{'='*50}")
        print(f"STATS SESSION {self.date_str}")
        print(f"{'='*50}")
        print(f"Trades: {len(self.today_trades)} ({len(wins)}W / {len(losses)}L / {len(timeouts)}T)")
        print(f"Win Rate: {wr:.1f}%")
        print(f"Profit Factor: {pf:.2f}")
        print(f"EV/trade: {ev:+.1f} ticks")
        print(f"Total PnL: {total_pnl:+.1f} ticks")
        if self.today_trades:
            avg_mae = sum(t["mae"] for t in self.today_trades) / len(self.today_trades)
            avg_mfe = sum(t["mfe"] for t in self.today_trades) / len(self.today_trades)
            print(f"MAE moyen: {avg_mae:.1f}t | MFE moyen: {avg_mfe:.1f}t")

        # Par instrument
        for sym in ("ES", "NQ"):
            subset = [t for t in self.today_trades if t["symbol"] == sym]
            if subset:
                w = sum(1 for t in subset if _oc(t) == "TP")
                pnl = sum(t["pnl_ticks"] for t in subset)
                print(f"  {sym}: {len(subset)} trades, WR={w/len(subset)*100:.0f}%, PnL={pnl:+.1f}t")


def show_stats(symbol=None):
    """Affiche les stats de tous les jours."""
    import glob as g
    files = sorted(g.glob(os.path.join(DATA_DIR, "*_trades.jsonl")))
    if not files:
        print("Aucun trade enregistre.")
        return

    all_trades = []
    for f in files:
        with open(f, "r") as fh:
            for line in fh:
                s = line.strip()
                if s:
                    try:
                        t = json.loads(s)
                        if symbol and t.get("symbol") != symbol:
                            continue
                        all_trades.append(t)
                    except json.JSONDecodeError:
                        pass

    if not all_trades:
        print(f"Aucun trade{' pour ' + symbol if symbol else ''}.")
        return

    # Fix mineur #3 (code-reviewer 22/04) : tolerance trades legacy
    def _oc(t): return t.get("outcome") or t.get("exit_reason") or "?"
    wins = [t for t in all_trades if _oc(t) == "TP"]
    losses = [t for t in all_trades if _oc(t) == "SL"]
    total_pnl = sum(t["pnl_ticks"] for t in all_trades)
    win_pnl = sum(t["pnl_ticks"] for t in wins)
    loss_pnl = sum(abs(t["pnl_ticks"]) for t in losses)

    wr = len(wins) / len(all_trades) * 100
    pf = win_pnl / loss_pnl if loss_pnl > 0 else float("inf")
    ev = total_pnl / len(all_trades)

    title = f"PAPER TRADING — {symbol or 'ALL'}"
    print(f"\n{'='*50}")
    print(title)
    print(f"{'='*50}")
    print(f"Sessions: {len(files)}")
    print(f"Trades: {len(all_trades)} ({len(wins)}W / {len(losses)}L)")
    print(f"Win Rate: {wr:.1f}%")
    print(f"Profit Factor: {pf:.2f}")
    print(f"EV/trade: {ev:+.1f} ticks")
    print(f"Total PnL: {total_pnl:+.1f} ticks")

    # Par jour
    print(f"\nPar jour:")
    dates = sorted(set(t.get("entry_time", "")[:10] for t in all_trades))
    for d in dates:
        day = [t for t in all_trades if t.get("entry_time", "").startswith(d)]
        w = sum(1 for t in day if t["outcome"] == "TP")
        pnl = sum(t["pnl_ticks"] for t in day)
        print(f"  {d}: {len(day)} trades, WR={w/len(day)*100:.0f}%, PnL={pnl:+.1f}t")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        sym = None
        if "--symbol" in sys.argv:
            idx = sys.argv.index("--symbol")
            if idx + 1 < len(sys.argv):
                sym = sys.argv[idx + 1].upper()
        show_stats(sym)
    else:
        trader = PaperTrader()
        trader.run()
