"""mia2_brain_v6_databento.py — Bot V6 (Sim2) cerveau enrichi Databento V4.

CONTEXTE 04/05/2026 (Jackson) :
  - Copie autonome de mia_paper_trader.py (Bot 1 sur Sim3) qui reste INCHANGE.
  - Memes infrastructure (DTC connector, OCO manuel, SLTPEngine, logs V2,
    risk manager, kill-switch, anti-orphelin 7 etapes, retry os.replace,
    LEVIER #1 skip NEUTRAL, LEVIER #2 circuit breaker, LEVIER A trailing TP,
    Phase 1 OBSERVE V4 widgets, _get_dynamic_wr Bayesien shrunk).
  - Cerveau ENRICHI via les imports _v6 :
      from CORE.bias_calculator_v6 import compute_bias
      from CORE.regime_engine_v6 import compute_regime
  - Cible Sim2 (remplace Bot 2 V2 SetupEngine).

Architecture Plan refonte V6 (10 buckets V4 mappes) :
  Phase 0 — Foundation (copies + tests parite avec Bot 1)
  Phase 1 — Bucket #3 Absorption / Trapped (max impact ⭐⭐⭐ x4)
  Phase 2 — Bucket #1 SMT cross-instrument (im_*)
  Phase 3 — Bucket #5 Multi-session + wr session-conditionnel
  Phase 4 — Bucket #6 Liquidity / SMC
  Phase 5-10 — Buckets #8 #2 #9 #4 #7 #10
  Audit final : moi + agent en parallele sur Bot V6 complet

Pondération + lissage (Jackson 04/05) :
  - Anti flip-flop conseil global (1H>15M>5M>1M)
  - Hysteresis temporel (N bars confirmation avant flip)
  - Reviews entre buckets : code-reviewer + market-analyst selon impact

Suit les recommandations du dashboard MIA en temps reel :
- Prend un trade quand Conseil Global = ACHAT/VENTE AVEC freshness == "NEW"
- SL/TP via SLTPEngine (Tier 1/2 derriere mur + TP1 premier obstacle)
- Filtre expected_payoff_$ >= $2 avec wr Bayesien shrunk + cellule
- 1 micro tracking (coherent ENTRY_RULES)
- Cooldown 15 min post-close par symbol
- Circuit breaker 3 SL consec → pause 60 min par symbol
- Ecrit state.json pour consommation dashboard

Usage :
    python CORE/mia2_brain_v6_databento.py     # lance le bot V6
    python CORE/mia2_brain_v6_databento.py --stats
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
# FIX 29/04 (R3 audit) : import top-level avec fallback (Bot 1 run depuis racine,
# Bot 2 depuis CORE/ → 2 conventions a supporter).
try:
    from CORE.constants import get_cme_trading_day, TRAILING_TR40_NQ_ENABLED
except ImportError:
    from constants import get_cme_trading_day, TRAILING_TR40_NQ_ENABLED
from CORE.bias_calculator_v6 import compute_bias  # V6 (04/05) cerveau enrichi V4 — Phase 0 = identique au standard
from CORE.cross_instrument import compute_cross_bonus  # 24/04 mode OBSERVATION (log-only)

# Systeme logs V2 (22/04 session)
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("mia2_brain_v6", process="paper_v6")
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
# V6 (Sim2) state file dedie pour ne pas ecraser Bot 1 (Sim3) state.json
STATE_FILE = os.path.join(DATA_DIR, "state_v6.json")  # bridge pour dashboard endpoint Bot V6

# V4 ENRICHED Databento parquet root (Bot 2 V2 pattern - REQUIS pour V6 brain enrichi)
# Sans ca les blocs 7-16 bias_v6 + votes 11-16 regime_v6 sont INERTES (features V4 absentes du DMP).
# Cache de la lecture parquet : 1x par minute (le pipeline V4 update toutes 5 min).
V4_DATASET_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "DATA", "datasets", "v4_enriched"
)
MENTHORQ_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DATA", "MENTHORQ")
# Kill-switch admin : cree/supprime par POST /api/bot/{stop,start} (admin_routes.py)
# Meme chemin que BOT/bot_main.py pour compat, mais seul paper_trader ecoute en prod.
STOP_FLAG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "DATA", "BOT_CONTROL", "STOP.flag"
)
# 🆕 LEVIER A Trailing TP MFE-based (04/05 soir Jackson — Option 2 sweet spot)
# Audit 28 TIMEOUT : 13 trades MFE>=20t mais final capture 30-50% seulement.
# Activation : si MFE atteint le seuil par symbol -> trailing s'arme.
# Trigger close : si drawback (MFE_peak - current) >= TRAILING_TP_DRAWBACK_TICKS.
#
# Calibrations testees sur 5j 111 trades :
#   Option 1 (initiale)     : ES=40 NQ=60 db=25 -> 3 triggers, +$222, PF 1.06->1.12
#   Option 2 (ACTIVE)       : ES=30 NQ=50 db=20 -> 6 triggers, +$437, PF 1.06->1.15
#   Note : ES seuil 40 jamais atteint (MFE max ES TIMEOUT = 39t).
TRAILING_TP_MFE_THRESHOLD_TICKS = {"ES": 30, "NQ": 50}   # Option 2 sweet spot
TRAILING_TP_DRAWBACK_TICKS = 20                           # drawback peak MFE

# 🆕 OBSERVATION parallele : Option 1 conservatrice (40/60/25) loggee sans action
# pour comparer empiriquement les 2 calibrations sur data live a J+7.
TRAILING_TP_OBS_MFE_THRESHOLD_TICKS = {"ES": 40, "NQ": 60}
TRAILING_TP_OBS_DRAWBACK_TICKS = 25

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
    # de donnees).
    # 03/05 soir Jackson : "ON FERA COMME BOT 2 ET 3 PAS DE LIMITE TRADE PAS DE
    # LIMITE PERTE TOUTES LES SESSIONS". Desactive circuit breaker SL consec.
    # 04/05 soir LEVIER #2 (backtest 110 trades) : 10 streaks >=3 SL → DD $1003
    # Reactivation circuit breaker : 3 SL consecutifs → pause 60 min. Impact
    # estime DD -50% selon backtest (Jackson valide).
    "max_trades_per_day": 9999,             # PAS de limite trades
    "cooldown_post_close_sec": 900,         # 15 min anti re-entry contre-sens
    "circuit_breaker_losses": 3,            # LEVIER #2 (04/05) : 3 SL consec → pause
    "circuit_breaker_pause_sec": 3600,      # LEVIER #2 : 60 min pause
    # ============================================================
    # WR DYNAMIQUE — RESET 04/05 SOIR (Jackson)
    # ============================================================
    # Refonte _get_dynamic_wr : avant = wr global rolling 30 trades sans
    # conditionnement. En Asia avec wr_obs=0.30, EV negatif -> bot bloque
    # (cf rejet step_8 expected_payoff_low du 23:01 UTC NQ SHORT).
    #
    # Nouvelle logique :
    #   1. Shrinkage Bayesien : combiner wr_obs avec prior=0.50, k=15
    #      -> stabilise petits echantillons (N=15 wr=0.30 -> 0.40)
    #   2. Conditionnement cellule (symbol x direction x session)
    #      -> evite que LONG ES London 30% bloque SHORT NQ Asia
    #   3. Min N reduit 30 -> 15 pour reagir plus vite
    # Reviews croises 04/05 soir (code-reviewer + ml-trainer + audit indep) :
    # - prior=0.40 : break-even RR=2:1 = 0.333. Prior 0.50 etait pro-trade
    #   (encourage trades EV-). 0.40 = legerement optimiste vs break-even.
    # - k_global=30 : k=15 trop faible quand n_glob<50 (regime initial pure prior).
    # - k_cell=10 : laisse cellule diverger plus vite quand evidence empirique.
    # - cell_min_n=15 : avec CI Wilson [N=5,p=0.4]=[0.12,0.77] inutilisable.
    #   N=15 -> CI~+/-0.15, fiable pour decision. Ml-trainer R4.
    "estimated_wr_initial": 0.40,           # break-even RR=2 = 0.333, +marge
    "estimated_wr_rolling_min": 15,         # 15 au lieu de 30 (reagir plus vite)
    "wr_shrinkage_prior": 0.40,             # legerement optimiste vs break-even
    "wr_shrinkage_k": 30,                   # k_global - shrink fort si n_glob faible
    "wr_cell_shrinkage_k": 10,              # k_cell - laisse diverger plus vite
    "wr_cell_min_n": 15,                    # CI Wilson fiable a partir N=15
    # 3.7.9 (24/04) — gate directionnel bias_calculator STEP 6bis
    # 🆕 24/04 soir (B.1) : `min_bias_clarity` utilise UNIQUEMENT comme seuil
    #   pour le soft-flag `bias_weak_but_aligned` (observabilite V2 log).
    #   Le gate strict ne rejette plus sur clarity, seulement sur opposite_direction.
    #   Cf. feedback_lightgbm_no_composite_indicators.md + audit market-analyst 24/04.
    "min_bias_clarity": 0.30,               # seuil soft-flag observabilite uniquement
    "enforce_bias_gate": True,              # si False, bias calcule mais gate desactive (observabilite only)
    # 30/04 v3 (Jackson "ON A ACHETE HAUT DE RANGE") — RangeGate confluence
    # 4 metriques (VA + IB + DAY + MQ_1D). Reversibilite via flag.
    "range_gate_enabled": True,             # toggle desactivable (anti pattern 11 V1)
    "range_gate_min_confluence": 2,         # >= 2/4 metriques en zone extreme = SKIP
    "range_gate_mode": "observe",           # "observe" (log only) ou "skip" (mutation)
    # Backtest 30/04 : mode skip = 65% rejection + PnL bloque +753$ → observe
    # par defaut (R1+S3 code-reviewer). Bench 5j puis switch skip.
    # 30/04 v4 (Jackson "ON APPLIQUE EN PAPER DIRECT") — RegimeGate skip empirique
    # Backtest empirique 80 trades Bot 1 (24+29+30/04) : 22.5% bloques, PnL
    # bloque -354$ (=eviter), PnL passe +401$ (=garde), WR 23%→37.8%.
    # Filtre LOSERS empiriques : profile_shape==0 (D Range -19t) + day_type==1 (Normal -19t).
    "regime_gate_enabled": True,            # mode skip direct (Jackson directive)
    # 30/04 v4 LOT 2B (Jackson "ON APPLIQUE PAPER DIRECT") — EntryQualityGate
    # Backtest 104 trades Bot 1 mode BOTH_CONTRA :
    #   32.7% rejection, PnL bloque -1803$, PnL passe +7274$, WR 53.8%.
    # Filtre golden empirique : skip si momentum_5b ET cvd_bar_delta both contra.
    "entry_quality_gate_enabled": True,     # toggle desactivable
    "entry_quality_gate_strict": False,     # False = BOTH_CONTRA, True = AT_LEAST_1
}

# Config DTC (valide Phase 1 paper uniquement, pas de compte LIVE)
TRADE_ACCOUNT = os.environ.get("MIA_TRADE_ACCOUNT", "Sim2")  # V6 cible Sim2 (remplace Bot 2)
_SIM_WHITELIST_PREFIX = ("SIM", "Sim", "sim")


# Funnel check_entry (23/04 Jackson) : mix compteurs bruts + funnel macro 8 STEPs.
# Expose `entry_funnel_today` dans state.json + snapshot EOD LOGS/funnel/funnel_YYYYMMDD.json.
# But : diagnostiquer "pourquoi bot 0 trade" en un coup d'oeil (V1 feature que Jackson kiffait).
#
# STEP 7 split (23/04 soir) : 4 sous-raisons pour savoir si mur absent, R:R faible, ou budget dep.
FUNNEL_STEPS = [
    # 🆕 03/05 (Plan B Action 3 — Jackson "FILTRE LE PLUS HAUT NIVEAU") :
    # STEP 0 regime gate STRICT : skip si pas regime actionable (pas TREND/RANGE clair
    # OU favor NEUTRE OU vol EXTREME OU confidence < 0.10). Bot 1 = beaucoup faux
    # signaux dashboard, filtre regime cap les plus mauvais. Bot 2 + Bot 3 restent
    # sur filtre directionnel SOFT (different criteres). Calibration optimale via
    # regime_engine.compute_regime() (grid search 14j NQ).
    ("0_regime",        "Regime Gate STRICT (full skip)",
     ["regime_not_actionable", "regime_neutre", "regime_contraire_signal",
      "regime_bias_neutral"]),  # 🆕 LEVIER #1 04/05 backtest +$855
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
    ("6ter_range",      "RangeGate haut/bas",
     ["range_extreme"]),  # 🆕 30/04 v3 (Jackson "ON A ACHETE HAUT DE RANGE")
     # Confluence 4 metriques (VA + IB + DAY + MQ_1D) : skip si >=2/4 en zone
     # extreme. Plus cas BREAKOUT_VA (range_pos extreme + inside_cur_va=0).
    ("6quart_regime",   "RegimeGate Profile/Day",
     ["regime_loser_profile_shape", "regime_loser_day_type"]),  # 🆕 30/04 v4
     # Skip empirique : profile_shape==0 (D Range -19t) + day_type==1 (Normal -19t).
     # Backtest 80 trades : 22.5% bloques, PnL eviter -354$, WR 23%→37.8%.
    ("6cinq_entry_quality", "EntryQualityGate BOTH_CONTRA",
     ["entry_quality_both_contra"]),  # 🆕 30/04 LOT 2B
     # Skip si momentum_5b ET cvd_bar_delta BOTH contra direction.
     # Backtest 104 trades : 32.7% bloques, PnL eviter -1803$, WR 23%→53.8%.
    ("6six_chase_top",  "ChaseTopGate LONG range_pos",
     ["chase_top_long_range_high"]),  # 🆕 05/05 walk-forward Lopez DSR=0.72
     # Bloque LONG si range_pos>=60 (chase top du range RTH).
     # Backtest 90 trades LONG-only : delta +$1264, ratio 5.5x SL/TP, DSR=0.72.
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
REJECT_LOG_STEPS = {"3_conseil", "4_freshness", "5_dedup", "6_conf_mtf", "6bis_bias",
                     "6cinq_entry_quality", "6six_chase_top", "7_sltp", "8_payoff"}

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
    "chase_top_long_range_high": "GATE_CHASE_TOP_LONG_BLOCK",
}
REJECT_LOG_RATE_LIMIT_SEC = 60


# Fix CRITIQUE (22/04 soir) : sans auth, /api/dashboard retourne tier=free
# avec conseil_global.action toujours ATTENDRE → paper trader jamais ne trade.
# Solution : generer JWT owner interne (meme JWT_SECRET que le serveur, car
# meme process VPS/meme fichier .jwt_secret). Token regenere toutes les 13 min
# (access expiry 15 min, marge 2 min).
_SERVICE_TOKEN: str | None = None
_SERVICE_TOKEN_EXPIRY: float = 0.0


# 🆕 03/05 (Plan B Action 3) — Bot 1 STEP 0 regime gate STRICT
# Import REGIME_SKIP_ENABLED au top du module (1 fois) avec fail-OPEN si plante.
# Q5 code-reviewer : si ImportError, REGIME_SKIP_ENABLED=False = Bot 1 continue
# sans gate (pas paralyse 100%). Logging error visible dans LOGS/errors.
try:
    from CORE.regime_engine_v6 import REGIME_SKIP_ENABLED as _REGIME_SKIP_ENABLED
except Exception as _e:
    import logging as _logging
    _logging.error(f"regime_engine_v6 import fail in mia2_brain_v6: {_e} - fail-open (gate disabled)")
    _REGIME_SKIP_ENABLED = False  # fail-OPEN : Bot V6 continue sans gate

# ChaseTopGate kill-switch (R3 code-reviewer 05/05). Env var MIA_CHASE_TOP_GATE_ENABLED.
_CHASE_TOP_GATE_ENABLED = os.environ.get("MIA_CHASE_TOP_GATE_ENABLED", "1") == "1"
_CHASE_TOP_THRESHOLD = float(os.environ.get("MIA_CHASE_TOP_THRESHOLD", "60"))

# ─── Mode TREND DAY override (07/05 audit walk-forward) ──────────────────
# Audit walk-forward 12 folds : ChaseTopGate seuil 60% DSR INSTABLE par fold.
# Mais TREND LONG day (pct_in_range median 60bars >=80%) : LONG @ range_pos 70-90% =
# +1.31t a +1.38t mean_pnl mieux que non-trend. Detail : CORE/research/audit_chasetop_trendday_walkforward.py
# 3 conditions cumulatives pour bypass :
#   (1) regime_trend_votes >= 6
#   (2) regime_favor == direction du signal
#   (3) median pct_in_range sur lookback bars >= 80% (LONG) OU <= 20% (SHORT)
_TREND_DAY_OVERRIDE_ENABLED = os.environ.get("MIA_TREND_DAY_OVERRIDE_ENABLED", "0") == "1"  # P0.2 default OFF
_TREND_DAY_LOOKBACK_BARS = int(os.environ.get("MIA_TREND_DAY_LOOKBACK_BARS", "60"))
_TREND_DAY_LONG_THRESHOLD = float(os.environ.get("MIA_TREND_DAY_LONG_THRESHOLD", "80.0"))
_TREND_DAY_SHORT_THRESHOLD = float(os.environ.get("MIA_TREND_DAY_SHORT_THRESHOLD", "20.0"))
_TREND_DAY_MIN_TREND_VOTES = int(os.environ.get("MIA_TREND_DAY_MIN_TREND_VOTES", "6"))


def _is_trend_day(direction: str, regime_data: dict, range_pos_history: list) -> tuple:
    """Detection TREND DAY pour bypass ChaseTopGate Bot 2 V6 (cf mia_paper_trader.py).

    P0.1 fix code-reviewer 07/05 : lookup defensif `mode_trend_votes`/`favor` (cles
    natives du dict `instr["regime"]` du dashboard) avec fallback `regime_trend_votes`/
    `regime_favor` (cles normalisees). Sans ce fallback le bypass ne s'activait jamais.
    """
    if not _TREND_DAY_OVERRIDE_ENABLED:
        return (False, "TREND_DAY_DISABLED")
    trend_votes = (regime_data.get("regime_trend_votes")
                   or regime_data.get("mode_trend_votes")
                   or 0)
    try:
        trend_votes = int(trend_votes)
    except (TypeError, ValueError):
        trend_votes = 0
    if trend_votes < _TREND_DAY_MIN_TREND_VOTES:
        return (False, f"trend_votes_{trend_votes}_lt_{_TREND_DAY_MIN_TREND_VOTES}")
    regime_favor = (regime_data.get("regime_favor")
                    or regime_data.get("favor")
                    or "").upper()
    expected_favor = "LONG" if direction == "LONG" else "SHORT"
    if regime_favor != expected_favor:
        return (False, f"favor_{regime_favor}_not_{expected_favor}")
    if not range_pos_history or len(range_pos_history) < _TREND_DAY_LOOKBACK_BARS // 2:
        return (False, f"range_pos_history_insufficient_{len(range_pos_history) if range_pos_history else 0}")
    try:
        valid_history = [float(x) for x in range_pos_history if x is not None]
    except (TypeError, ValueError):
        return (False, "range_pos_history_invalid")
    if len(valid_history) < _TREND_DAY_LOOKBACK_BARS // 2:
        return (False, "range_pos_history_too_short")
    import statistics as _stats
    median_range = _stats.median(valid_history)
    if direction == "LONG":
        if median_range < _TREND_DAY_LONG_THRESHOLD:
            return (False, f"median_range_{median_range:.1f}_lt_{_TREND_DAY_LONG_THRESHOLD}")
    else:
        if median_range > _TREND_DAY_SHORT_THRESHOLD:
            return (False, f"median_range_{median_range:.1f}_gt_{_TREND_DAY_SHORT_THRESHOLD}")
    return (True, "TREND_DAY_OK")


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
        # FIX 29/04 (Jackson) : convention CME trading day (rollover 18:00 ET =
        # ouverture Asia/CME futures, DST-aware), pas UTC midnight. Aligne le
        # PnL "session" avec la realite des sessions de trading reelles.
        self.date_str = get_cme_trading_day()
        # FIX 05/05 cohérence Bot 2 V6 : suffixe _v6 pour ne pas hériter des trades Bot 1
        # qui écrit dans {date}_trades.jsonl (sans suffixe). Sans ça, _load_existing()
        # au boot V6 charge les trades Bot 1 dans state_v6.json — incohérent.
        self.log_file = os.path.join(DATA_DIR, f"{self.date_str}_v6_trades.jsonl")
        self.snapshot_file = os.path.join(DATA_DIR, f"{self.date_str}_v6_snapshots.jsonl")
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
        self._traded_signals_file = os.path.join(DATA_DIR, f"{self.date_str}_v6_traded_signals.txt")
        self._traded_signal_ids = set()

        # 07/05 — buffer range_pos history pour TREND DAY override (audit walk-forward)
        from collections import deque as _deque
        self._range_pos_history = {
            "ES": _deque(maxlen=_TREND_DAY_LOOKBACK_BARS),
            "NQ": _deque(maxlen=_TREND_DAY_LOOKBACK_BARS),
        }

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

        # V6 brain (04/05) : fix R1 code-reviewer re-audit
        # Initialise pour eviter AttributeError si acces externe avant 1er check_entry
        self._latest_v6_bias = None

        # V4 enriched bar cache (FIX critique 05/05 Jackson "branche V6 a Databento")
        # Le parquet V4 contient 456 features (bars_since_swing, wick_pct, im_smt,
        # cluster_at_*, naked_poc, ctx_*) ABSENTES du DMP. Sans ca les blocs 7-16
        # de bias_v6 + votes 11-16 de regime_v6 sont dead code. Cache 60s pour eviter
        # read_parquet a chaque poll (lourd I/O).
        self._v4_bar_cache: Dict[str, dict] = {}  # sym -> bar dict
        self._v4_bar_cache_ts: Dict[str, float] = {}  # sym -> last load epoch
        # Tracking source bar pour audit J+1 (R3 code-reviewer)
        self._latest_v6_bar_source: str = "INIT"
        # 17/05 (Jackson "voyant flux source") : tracking PAR SYMBOLE pour
        # voyant dashboard. Avant : variable globale ecrasee a chaque check_entry
        # = on ne sait pas si NQ etait V4 ou DMP quand ES affiche autre source.
        # bar_source_per_sym persiste dans state_v6.json (cf _write_state).
        self._latest_v6_bar_source_per_sym: Dict[str, str] = {"ES": "INIT", "NQ": "INIT"}
        self._latest_v6_bar_source_ts_per_sym: Dict[str, float] = {}  # epoch derniere maj par sym

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

        # 🆕 04/05 Phase 1 OBSERVE-ONLY widgets V4 (audit market-analyst)
        # Compteurs cumulatifs par symbol/signal pour audit J+7 et J+14.
        # Pas de modification du verdict tant que n>=100 + DSR>=0.95 (Lopez).
        # Les codes log_catalog *_OBSERVED tracent les occurrences pour stat.
        self._v4_obs_counts: dict = {
            "ES": {"vwap_align": 0, "rvol_excep": 0, "div_buy": 0, "div_sell": 0,
                   "wall_react": 0, "trap_buy": 0, "trap_sell": 0, "poc_up": 0,
                   "poc_dn": 0, "absorb_bid": 0, "absorb_ask": 0,
                   "cluster_trap_buy": 0, "cluster_trap_sell": 0,
                   "big_buy_agg": 0, "big_sell_agg": 0,
                   "smt_bull": 0, "smt_bear": 0,
                   "npoc_magnet_strong": 0, "v4_stale": 0},
            "NQ": {"vwap_align": 0, "rvol_excep": 0, "div_buy": 0, "div_sell": 0,
                   "wall_react": 0, "trap_buy": 0, "trap_sell": 0, "poc_up": 0,
                   "poc_dn": 0, "absorb_bid": 0, "absorb_ask": 0,
                   "cluster_trap_buy": 0, "cluster_trap_sell": 0,
                   "big_buy_agg": 0, "big_sell_agg": 0,
                   "smt_bull": 0, "smt_bear": 0,
                   "npoc_magnet_strong": 0, "v4_stale": 0},
        }
        self._load_existing()

    def _load_existing(self):
        """Charge les trades + signal_ids existants du jour (robuste post-restart).

        Fix 11/05 : skip trades `invalidated=True` (cleanup phantom DMP Gold 10/05).
        Convention alignee avec `DASHBOARD/api/paper_tracker.py` qui filtre les
        invalidated du dashboard. Sans ce filtre, stats_today recompte le trade
        fantome (meme avec pnl_usd=0 apres cleanup) = 1 trade comptabilise.
        """
        if os.path.exists(self.log_file):
            with open(self.log_file, "r") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        try:
                            trade = json.loads(s)
                            if trade.get("invalidated"):
                                continue
                            self.today_trades.append(trade)
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

    def _compute_last_bar_age_for_heartbeat(self, data) -> float:
        """FIX 06/05 + review code-reviewer : age (sec) derniere bar pour BOT_HEARTBEAT.

        Lecture dashboard data.banner. Fallback **99999.0** (pas 0.0) si dashboard
        mort / banner manquant = sentinel CRIT force watchdog kill.
        Pattern aligne `check_stream_subscribe_alive` (mia_watchdog.py:354).
        """
        try:
            from datetime import datetime, timezone
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            ages = []
            banner = data.get("banner", {}) if isinstance(data, dict) else {}
            for sym in ("ES", "NQ"):
                b = banner.get(sym.lower(), {})
                # FIX 08/05: meme bug que Bot 1 (mia_paper_trader.py:594) - banner field
                # actuel = "ts" (pas "ts_ms"/"bar_ts_ms"). Sans cet alias = fallback 99999
                # = STALE CRITICAL faux + watchdog restart loop sans fin.
                ts_ms = b.get("ts") or b.get("ts_ms") or b.get("bar_ts_ms")
                if ts_ms:
                    age = (now_ms - float(ts_ms)) / 1000
                    if 0 <= age < 86400:
                        ages.append(age)
            return float(max(ages)) if ages else 99999.0
        except Exception:
            return 99999.0

    def _rotate_day_if_needed(self):
        """Fix B4 (code-reviewer 22/04) : rollover quotidien pour bot VPS 24/7.

        Si UTC date change depuis init, reset tout ce qui est quotidien :
          - trade_count_today, today_trades (nouveau fichier log)
          - consec_losses, circuit_pause_until (fresh start)
          - traded_signal_ids (nouveau fichier dedup)
          - log_file, snapshot_file, _traded_signals_file paths

        Appele en tete de boucle `run()` avant toute autre logique.
        """
        # FIX 29/04 (Jackson) : convention CME (18:00 ET = nouveau trading day, DST-aware)
        current_date = get_cme_trading_day()
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
        self.log_file = os.path.join(DATA_DIR, f"{self.date_str}_v6_trades.jsonl")
        self.snapshot_file = os.path.join(DATA_DIR, f"{self.date_str}_v6_snapshots.jsonl")
        self._traded_signals_file = os.path.join(DATA_DIR, f"{self.date_str}_v6_traded_signals.txt")
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

    def _observe_v4_widgets(self, sym: str, data: dict, action: str) -> None:
        """Phase 1 OBSERVE-ONLY widgets V4 (audit market-analyst 04/05).

        Logge les 13 widgets dashboard (8 manual_indicators + 4 order_flow_advanced
        + 1 setup) sans modifier le verdict trading. Compteurs cumulatifs dans
        `self._v4_obs_counts[sym]` pour audit empirique J+7 / J+14.

        Le verdict reste celui de `conseil_global.action`. SLTPEngine intact.

        Args:
            sym : "ES" ou "NQ"
            data : payload /api/dashboard complet
            action : verdict conseil_global ("ACHAT", "VENTE", "ATTENDRE PRUDENT"...)
        """
        if _v2log is None:
            return
        instr = data.get(sym.lower()) or {}
        mi = instr.get("manual_indicators") or {}
        ofa = instr.get("order_flow_advanced") or {}
        if not mi and not ofa:
            return
        cnt = self._v4_obs_counts.get(sym)
        if cnt is None:
            return
        try:
            # ── Manual indicators (8 widgets) ─────────────────────────────
            # A. VWAP triple align (D+W+M unanime)
            if mi.get("vwap_triple_align") == 1:
                cnt["vwap_align"] += 1
                _v2log.emit("MANUAL_VWAP_TRIPLE_ALIGN_OBSERVED",
                            sym=sym, direction="UP" if mi.get("vwap_d_side", 0) > 0 else "DN",
                            d=mi.get("vwap_d_side"), w=mi.get("vwap_w_side"),
                            m=mi.get("vwap_m_side"), slope_dir=mi.get("vwap_slope_10_dir"),
                            action=action)
            # B. RVOL exceptionnel (z>=2)
            if mi.get("rvol_zone") == "EXCEPTIONAL":
                cnt["rvol_excep"] += 1
                _v2log.emit("MANUAL_RVOL_EXCEPTIONAL_OBSERVED",
                            sym=sym, zscore=mi.get("rvol_zscore"),
                            zone=mi.get("rvol_zone"), action=action)
            # C. Delta divergence (BUY/SELL)
            div_sig = mi.get("div_signal", "OFF")
            if div_sig == "BUY":
                cnt["div_buy"] += 1
                _v2log.emit("MANUAL_DIVERGENCE_OBSERVED",
                            sym=sym, signal="BUY",
                            strength=mi.get("div_strength"), action=action)
            elif div_sig == "SELL":
                cnt["div_sell"] += 1
                _v2log.emit("MANUAL_DIVERGENCE_OBSERVED",
                            sym=sym, signal="SELL",
                            strength=mi.get("div_strength"), action=action)
            # D. Next wall reaction zone (<=8 ticks)
            if mi.get("wall_reaction_zone"):
                cnt["wall_react"] += 1
                _v2log.emit("MANUAL_NEXT_WALL_REACTION_OBSERVED",
                            sym=sym, side=mi.get("next_wall_side"),
                            dist=mi.get("next_wall_dist_ticks"), action=action)
            # E. Trapped traders @ niveau
            trap_sig = mi.get("trapped_signal", "OFF")
            if trap_sig == "TRAPPED_BUYERS":
                cnt["trap_buy"] += 1
                _v2log.emit("MANUAL_TRAP_OBSERVED",
                            sym=sym, signal=trap_sig,
                            buy=mi.get("trapped_zones_buy"),
                            sell=mi.get("trapped_zones_sell"), action=action)
            elif trap_sig == "TRAPPED_SELLERS":
                cnt["trap_sell"] += 1
                _v2log.emit("MANUAL_TRAP_OBSERVED",
                            sym=sym, signal=trap_sig,
                            buy=mi.get("trapped_zones_buy"),
                            sell=mi.get("trapped_zones_sell"), action=action)
            # F. POC migration (UP/DN)
            poc_state = mi.get("poc_state", "STABLE")
            if poc_state == "MIGRATING_UP":
                cnt["poc_up"] += 1
                _v2log.emit("MANUAL_POC_MIGRATING_OBSERVED",
                            sym=sym, state=poc_state,
                            speed=mi.get("poc_migration_speed"),
                            pos=mi.get("poc_position"), action=action)
            elif poc_state == "MIGRATING_DN":
                cnt["poc_dn"] += 1
                _v2log.emit("MANUAL_POC_MIGRATING_OBSERVED",
                            sym=sym, state=poc_state,
                            speed=mi.get("poc_migration_speed"),
                            pos=mi.get("poc_position"), action=action)
            # G. Absorption @ niveau
            abs_sig = mi.get("absorb_signal", "OFF")
            if abs_sig == "BID_DEFENDED":
                cnt["absorb_bid"] += 1
                _v2log.emit("MANUAL_ABSORB_OBSERVED",
                            sym=sym, signal=abs_sig, action=action)
            elif abs_sig == "ASK_DEFENDED":
                cnt["absorb_ask"] += 1
                _v2log.emit("MANUAL_ABSORB_OBSERVED",
                            sym=sym, signal=abs_sig, action=action)
            # ── Order Flow Avance V4 (4 widgets) ──────────────────────────
            # H. Cluster acheteur/vendeur (TRAP haute conviction)
            cl_sig = ofa.get("cluster_signal", "OFF")
            if cl_sig == "TRAP_BUY_AT_RES":
                cnt["cluster_trap_buy"] += 1
                _v2log.emit("OFA_CLUSTER_TRAP_OBSERVED",
                            sym=sym, signal=cl_sig,
                            side=ofa.get("cluster_nearest_side"),
                            dist_pct=ofa.get("cluster_nearest_dist_pct"),
                            trap_buy=ofa.get("cluster_trap_buy"),
                            trap_sell=ofa.get("cluster_trap_sell"), action=action)
            elif cl_sig == "TRAP_SELL_AT_SUP":
                cnt["cluster_trap_sell"] += 1
                _v2log.emit("OFA_CLUSTER_TRAP_OBSERVED",
                            sym=sym, signal=cl_sig,
                            side=ofa.get("cluster_nearest_side"),
                            dist_pct=ofa.get("cluster_nearest_dist_pct"),
                            trap_buy=ofa.get("cluster_trap_buy"),
                            trap_sell=ofa.get("cluster_trap_sell"), action=action)
            # I. Gros ordres aggressive (T1+ dominance >= 0.65)
            big_sig = ofa.get("big_signal", "BALANCED")
            if big_sig == "BUY_AGGRESSIVE":
                cnt["big_buy_agg"] += 1
                _v2log.emit("OFA_BIG_AGGRESSIVE_OBSERVED",
                            sym=sym, signal=big_sig, side="BUY",
                            buy_dom=ofa.get("big_buy_dom"),
                            sell_dom=ofa.get("big_sell_dom"),
                            t1_buy=ofa.get("big_buy_t1"),
                            t1_sell=ofa.get("big_sell_t1"), action=action)
            elif big_sig == "SELL_AGGRESSIVE":
                cnt["big_sell_agg"] += 1
                _v2log.emit("OFA_BIG_AGGRESSIVE_OBSERVED",
                            sym=sym, signal=big_sig, side="SELL",
                            buy_dom=ofa.get("big_buy_dom"),
                            sell_dom=ofa.get("big_sell_dom"),
                            t1_buy=ofa.get("big_buy_t1"),
                            t1_sell=ofa.get("big_sell_t1"), action=action)
            # J. SMT divergence ES/NQ (audit market-analyst : 100% OFF sur ES Apr → suspect)
            smt_sig = ofa.get("smt_signal", "OFF")
            if smt_sig == "BULL":
                cnt["smt_bull"] += 1
                _v2log.emit("OFA_SMT_DIVERGENCE_OBSERVED",
                            sym=sym, signal=smt_sig, value=ofa.get("smt_value"),
                            delta_day=ofa.get("smt_delta_day"), action=action)
            elif smt_sig == "BEAR":
                cnt["smt_bear"] += 1
                _v2log.emit("OFA_SMT_DIVERGENCE_OBSERVED",
                            sym=sym, signal=smt_sig, value=ofa.get("smt_value"),
                            delta_day=ofa.get("smt_delta_day"), action=action)
            # K. Naked POC magnet (age >= 5j + dist <= 0.2%)
            npoc_sig = ofa.get("npoc_signal", "OFF")
            if npoc_sig == "MAGNET_STRONG":
                cnt["npoc_magnet_strong"] += 1
                _v2log.emit("OFA_NPOC_MAGNET_OBSERVED",
                            sym=sym, signal=npoc_sig,
                            dist_pct=ofa.get("npoc_dist_pct"),
                            age_days=ofa.get("npoc_age_max_days"), action=action)
        except Exception as e:
            # Phase 1 OBSERVE-ONLY ne doit JAMAIS casser le bot
            if _v2log:
                _v2log.emit("PY_EXCEPTION_HOT_PATH",
                            sym=sym, fn_name="_observe_v4_widgets",
                            exc_type=type(e).__name__, exc_msg=str(e)[:200])

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
        """Ecrit un snapshot journalier avant rollover pour historique.

        Fix 11/05 : suffix `_v6` pour ne pas ecraser le funnel Bot 1
        (mia_paper_trader.py partage `FUNNEL_LOG_DIR` mais ecrit `funnel_{date}.json`).
        Sans suffix, le dernier qui sauvegarde au EOD CME (18:00 ET) ecrasait
        l'autre = perte historique funnel V6.
        """
        try:
            snap = self._funnel_snapshot()
            snap["saved_iso"] = datetime.now(timezone.utc).isoformat()
            fp = os.path.join(FUNNEL_LOG_DIR, f"funnel_{date_str}_v6.json")
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

        # 07/05 — Update range_pos history pour TREND DAY detection (audit walk-forward)
        try:
            _rp_now = reg.get("range_pos")
            if _rp_now is not None:
                _rp_val = float(_rp_now)
                if 0.0 <= _rp_val <= 100.0:
                    self._range_pos_history[symbol].append(_rp_val)
        except (TypeError, ValueError):
            pass


        # 🆕 04/05 Phase 1 OBSERVE-ONLY widgets V4 (FIX position 04/05 soir) :
        # observation AVANT les gates pour collecter sur TOUS les polls (meme
        # quand action=ATTENDRE), sinon 0 data pour audit J+7. Le verdict reste
        # 100% conseil_global, SLTPEngine intact. action_at_observation
        # capture l'etat conseil pour cross-tab signal x trade_taken plus tard.
        try:
            _conseil_pre = (data.get("conseil_global", {}) or {}).get(symbol, {})
            _action_at_obs = _conseil_pre.get("action", "ATTENDRE")
            self._observe_v4_widgets(symbol, data, _action_at_obs)
        except Exception:
            pass  # phase 1 ne doit jamais casser le bot

        # 🆕 25/04 - Enrichissement log V2 complet : market_ctx injecte dans TOUS les
        # rejets step 3-8 pour diagnostic pourquoi un poll meurt. Rate limite 60s
        # par (sym, reason) conserve (pas de spam).
        options = instr.get("options", {}) or {}
        # 🆕 03/05 (Plan B regime_engine MODE OBSERVE) : log regime dashboard
        # pour calibration empirique J+1. Pas de skip = pas de risque trading.
        market_ctx = {
            "dist_vwap_atr": round(reg.get("dist_vwap_atr", 0) or 0, 3),
            "atr": round(reg.get("atr", 0) or 0, 1),
            "session": reg.get("session_id") or "?",
            "vix_regime": reg.get("vix_regime"),
            # Plan B regime engine (mode observe) : 4 champs pour audit J+1
            "regime_mode": reg.get("mode", "?"),
            "regime_favor": reg.get("favor", "?"),
            "regime_vol": reg.get("vol_regime", "?"),
            "regime_trend_votes": reg.get("mode_trend_votes", -1),
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

        # 🆕 V6 BRAIN OVERRIDE (04/05 fix P1-1+P1-2 + 05/05 fix V4 source)
        # PRIORITE V4 ENRICHED PARQUET (456 features Databento) — Jackson 05/05
        # "branche V6 a Databento". Sans cette lecture, les blocs 7-16 bias_v6 +
        # votes 11-16 regime_v6 sont dead code (features V4 specifiques absentes du DMP).
        # Fallback : DMP JSONL si V4 indispo (latence accept).
        _v6_bar_v4 = self._load_last_bar_v4(symbol)  # V4 ENRICHED parquet (456 cols)
        _v6_source = "V4"
        if not _v6_bar_v4:
            # FIX R3 code-reviewer : emit FALLBACK pour visibilite prod
            # Sans cet emit, les decisions V6 sont prises sur DMP sans warning =
            # dead code 10 buckets V4 silencieux comme avant le fix V4 source.
            _v6_bot_data = data.get("bot", {})
            _v6_bar_v4 = _v6_bot_data.get("last_bars", {}).get(sym, {})
            _v6_source = "DMP_BOT"
            if not _v6_bar_v4:
                _v6_bar_v4 = self._read_last_jsonl_bar(symbol)
                _v6_source = "DMP_JSONL"
            if _v2log and _v6_bar_v4:
                _v2log.emit("V6_V4_FALLBACK_DMP",
                            sym=symbol,
                            fallback_source=_v6_source,
                            reason="V4_parquet_unavailable_or_stale")
        self._latest_v6_bias = None  # reset chaque check_entry
        self._latest_v6_bar_source = _v6_source  # tracking pour state.json + audit J+1
        # 17/05 : tracking PAR SYMBOLE pour voyant dashboard (Jackson)
        self._latest_v6_bar_source_per_sym[symbol] = _v6_source
        self._latest_v6_bar_source_ts_per_sym[symbol] = time.time()
        if _v6_bar_v4:
            try:
                from CORE.regime_engine_v6 import compute_regime as _compute_regime_v6
                from CORE.bias_calculator_v6 import compute_bias as _compute_bias_v6
                _r6 = _compute_regime_v6(_v6_bar_v4)
                _b6 = _compute_bias_v6(_v6_bar_v4)
                # Override regime avec V6 enrichi (16 votes : 10 standard + Votes 11-16)
                reg["mode"] = _r6.mode
                reg["favor"] = _r6.favor
                reg["regime_actionable"] = int(_r6.is_actionable)
                reg["regime_confidence"] = _r6.confidence
                reg["mode_trend_votes"] = _r6.trend_votes
                reg["mode_range_votes"] = _r6.range_votes
                reg["vol_regime"] = _r6.vol_regime
                # Expose bias V6 dans reg (consumable par market_ctx logs + gate)
                reg["bias_v6_score"] = round(_b6.score_signed, 3)
                reg["bias_v6_clarity"] = round(_b6.bias_clarity, 3)
                reg["bias_v6_direction"] = _b6.direction
                # Stocke bias_v6 sur self pour gate downstream
                self._latest_v6_bias = _b6
                # Log first-time visibilite (rate limited 60s)
                if _v2log:
                    _v2log.emit("BRAIN_V6_ACTIVE", sym=symbol,
                                regime_mode=_r6.mode, regime_favor=_r6.favor,
                                bias_v6_score=round(_b6.score_signed, 3),
                                bias_v6_dir=_b6.direction)
            except Exception as _e:
                if _v2log:
                    _v2log.emit("GENERIC_MAJEUR",
                                msg=f"V6 brain override fail (fallback V1): {_e}")

        # 🆕 STEP 0 (03/05 Jackson "FILTRE LE PLUS HAUT NIVEAU") — REGIME GATE STRICT
        # Bot 1 dashboard-follower = beaucoup faux signaux. Filtre regime cap les
        # plus mauvais. Skip FULL si regime non-actionable (pas TREND/RANGE clair OU
        # favor NEUTRE OU vol EXTREME). Egalement skip si signal contraire favor.
        # Kill switch : env var MIA_REGIME_SKIP_ENABLED=0 pour desactiver.
        # FIX CRITIQUE Q5 code-reviewer : fail-OPEN si import echoue (False par default)
        # Sinon Bot 1 paralyse 100% si regime_engine introuvable.
        if _REGIME_SKIP_ENABLED:
            regime_actionable_local = int(reg.get("regime_actionable", 0))
            regime_favor_local = reg.get("favor", "NEUTRE")
            regime_bias_local = reg.get("bias", "NEUTRAL")
            if not regime_actionable_local:
                self._funnel_reject("0_regime", "regime_not_actionable",
                                    symbol=symbol, **market_ctx)
                return None
            if regime_favor_local == "NEUTRE":
                self._funnel_reject("0_regime", "regime_neutre",
                                    symbol=symbol, **market_ctx)
                return None
            # 🆕 LEVIER #1 (04/05 soir backtest 110 trades) : skip bias NEUTRAL.
            # Backtest empirique 5j : NEUTRAL=N=26, WR=11.5%, PnL=-684t (vs
            # BULLISH/BEARISH 48-50% WR). 23% du volume = 100% des pertes
            # catastrophiques. Skipper = recuperer +684t (+$855) sur 5j.
            # `regime.bias` (build_regime_context) different de `regime.favor`
            # (regime_engine) — couvre les cas bias=NEUTRAL favor=LONG/SHORT.
            if regime_bias_local == "NEUTRAL":
                self._funnel_reject("0_regime", "regime_bias_neutral",
                                    symbol=symbol, **market_ctx)
                return None
            # Direction match check : signal direction doit etre coherent avec regime favor
            # Note : action sera connu apres STEP 3 (conseil_global). On check ici la direction
            # potentielle via conseil_action.
            # FIX 05/05 Option B : executable_action (gate freshness 4 bars vs UI 2 bars).
            _conseil = data.get("conseil_global", {}).get(sym, {})
            conseil_action_pre = _conseil.get("executable_action", _conseil.get("action", "ATTENDRE"))
            if conseil_action_pre == "ACHAT" and regime_favor_local == "SHORT":
                self._funnel_reject("0_regime", "regime_contraire_signal",
                                    symbol=symbol, **market_ctx)
                return None
            if conseil_action_pre == "VENTE" and regime_favor_local == "LONG":
                self._funnel_reject("0_regime", "regime_contraire_signal",
                                    symbol=symbol, **market_ctx)
                return None
            self._funnel_pass("0_regime")

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

        # 2ter. ECO CALENDAR + SESSION gate (29/04 soir)
        # Calendrier UNIFIE qui regroupe :
        #   1. Events eco High USD (FOMC, NFP, CPI, PCE) : -15min/+30min
        #   2. Open US volatility 09:15-09:45 ET (lun-ven)
        #   3. Post-MOC pause 15:30-18:15 ET (lun-jeu) — PILOT 30j 30/04
        #   4. Weekend : vendredi 15:30 ET → dimanche 18:15 ET (CME Asia reopen)
        # Source : CORE/eco_calendar.py.
        try:
            from CORE import eco_calendar as _eco
            _blocked, _reason, _until = _eco.is_blocked_combined()
            if _blocked:
                self._funnel_reject("2_cooldown_cb", f"eco_block:{_reason or '?'}")
                return None
        except Exception:
            pass  # fail-safe : si module plante, ne pas bloquer le bot

        # 3. Conseil Global action
        # FIX 05/05 Option B : `executable_action` (gate freshness 4 bars) au lieu
        # de `action` (UI freshness 2 bars). Audit empirique 188 raw=ACHAT PRUDENT
        # NQ etouffes par limite 2 bars. Fallback `action` pour backward compat.
        conseil = data.get("conseil_global", {}).get(sym, {})
        display_action = conseil.get("action", "ATTENDRE")
        action = conseil.get("executable_action", display_action)
        # R4 code-reviewer 05/05 : trace RESCUED pour audit J+1.
        if action != "ATTENDRE" and display_action == "ATTENDRE" and _v2log:
            try:
                _v2log.emit("GATE_CONSEIL_EXEC_RESCUED",
                            sym=sym, direction=("LONG" if "ACHAT" in action else "SHORT"),
                            bull_pts=conseil.get("bull_points", 0),
                            bear_pts=conseil.get("bear_points", 0),
                            age_bars=conseil.get("age_bars", 0))
            except Exception:
                pass
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
        # NOTE 04/05 : `_observe_v4_widgets` deplace en debut de check_entry pour
        # collecter sur TOUS les polls (audit J+7 cross-tab signal x action).
        direction_int = 1 if "ACHAT" in action else -1
        direction = "LONG" if direction_int == 1 else "SHORT"
        prudent = "PRUDENT" in action

        # 🆕 FIX 24/04 : kill-switch auto SELL par symbole (audit #4 market-analyst)
        # Re-injection du blocage SELL si auto-disable declenche pour CE symbole.
        if direction == "SHORT" and self._sell_disabled.get(symbol, False):
            self._funnel_reject("3_conseil", "sell_auto_disabled",
                                symbol=symbol,
                                action=action,
                                disable_reason=self._sell_disable_reason.get(symbol),
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

        # 🆕 V6 GATE BIAS_V6_CONTRADICTION (04/05 fix code-reviewer P1-2 NOGO)
        # Si bias_v6 enrichi V4 contredit fortement la direction du signal,
        # rejeter. Tolerance : score_v6 doit etre dans le sens du signal OU
        # dans la zone neutre |score| < 0.20 (apres normalisation FACTOR=0.5).
        # Cette gate transforme `bias_v6` de DEAD CODE en gate decisionnel reel.
        # Anti-flip-flop : seuil 0.20 absolu (pas 0.10) pour eviter rejection
        # sur barres ambivalentes.
        b6 = self._latest_v6_bias  # set par V6 brain override AVANT STEP 0
        BIAS_V6_CONTRA_THRESHOLD = 0.20
        if b6 is not None:
            b6_score = b6.score_signed
            if direction == "LONG" and b6_score < -BIAS_V6_CONTRA_THRESHOLD:
                self._funnel_reject("6_conf_mtf", "v6_bias_contradicts_long",
                                    symbol=symbol,
                                    direction=direction,
                                    v6_score=round(b6_score, 3),
                                    v6_clarity=round(b6.bias_clarity, 3),
                                    v6_direction=b6.direction,
                                    threshold=-BIAS_V6_CONTRA_THRESHOLD,
                                    action=action,
                                    signal_id=signal_id,
                                    **market_ctx)
                return None
            if direction == "SHORT" and b6_score > BIAS_V6_CONTRA_THRESHOLD:
                self._funnel_reject("6_conf_mtf", "v6_bias_contradicts_short",
                                    symbol=symbol,
                                    direction=direction,
                                    v6_score=round(b6_score, 3),
                                    v6_clarity=round(b6.bias_clarity, 3),
                                    v6_direction=b6.direction,
                                    threshold=BIAS_V6_CONTRA_THRESHOLD,
                                    action=action,
                                    signal_id=signal_id,
                                    **market_ctx)
                return None

        # 🆕 V6 GATE BIG ORDER OPPOSITE AT PRICE (05/05 backtest +$155 / +0.078 PF)
        # Decouverte 05/05 : Trade #2 Bot 1 -$87 entry @ 27931 avec
        # `dist_big_ask_nearest_up = 0` = vendeur institutionnel PILE au prix.
        # Backtest 111 trades historiques : reject si big_*_nearest <= 0t (TOL=0 strict)
        # Cumule avec V6 bias gate : PnL +193 -> +605 ($, +213%), PF 1.05 -> 1.24, WR 40.5% -> 44.3%.
        # TOL=0 strict : a TOL>=1, on tue trop de wins (le big order proche est utile comme S/R).
        # Source : bar_row_dict.dist_big_ask_nearest_up / dist_big_bid_nearest_dn
        # MAIS le bar est lu plus bas (ligne 1349). Pour ce gate, utiliser _v6_bar_v4
        # capture en debut check_entry (override block).
        TOL_BIG_AT_PRICE = 0
        big_dist_ask_up = (_v6_bar_v4 or {}).get("dist_big_ask_nearest_up")
        big_dist_bid_dn = (_v6_bar_v4 or {}).get("dist_big_bid_nearest_dn")
        if direction == "LONG" and big_dist_ask_up is not None:
            try:
                d = float(big_dist_ask_up)
                if 0 <= d <= TOL_BIG_AT_PRICE:
                    self._funnel_reject("6_conf_mtf", "v6_big_ask_at_price",
                                        symbol=symbol, direction=direction,
                                        big_ask_dist=d,
                                        threshold=TOL_BIG_AT_PRICE,
                                        action=action, signal_id=signal_id,
                                        **market_ctx)
                    return None
            except (TypeError, ValueError):
                pass
        if direction == "SHORT" and big_dist_bid_dn is not None:
            try:
                d = float(big_dist_bid_dn)
                if -TOL_BIG_AT_PRICE <= d <= 0:
                    self._funnel_reject("6_conf_mtf", "v6_big_bid_at_price",
                                        symbol=symbol, direction=direction,
                                        big_bid_dist=d,
                                        threshold=-TOL_BIG_AT_PRICE,
                                        action=action, signal_id=signal_id,
                                        **market_ctx)
                    return None
            except (TypeError, ValueError):
                pass

        # 🆕 V6 GATE NO CHASING — anti stop-hunt (05/05 backtest +$551 / +0.19 PF)
        # Stat empirique 111 trades :
        #   LONG  CHASE (d_swH 0..15t)  : N=16  WR=31.2%  PnL=-$168
        #   LONG  PULLBACK (d_swH > 15) : N=63  WR=41.3%  PnL=+$212
        #   SHORT CHASE (d_swL -15..0)  : N=7   WR=14.3%  PnL=-$373 (N FAIBLE = R6)
        #   SHORT PULLBACK (d_swL <-15) : N=25  WR=52.0%  PnL=+$522
        # FIX R6 code-reviewer : SHORT CHASE N=7 = data mining trap. TOL=15
        # plus conservateur sur SHORT (au lieu de 20) jusqu'a N>=20.
        # FIX R8 code-reviewer (HIGH PRIO) : skip CHASE si higher_low recent
        # (bars_since_last_swing_low <= 10) = stair-step setup valide.
        # Idem skip si wick rejection (bar_lower_wick_pct > 0.4).
        # Ces 2 features sont MAINTENANT dispo via V4 enriched (avant: ABSENT du DMP).
        TOL_CHASE_LONG = 20
        TOL_CHASE_SHORT = 15  # plus conservateur (R6: N=7 non-significatif)
        WICK_THRESHOLD = 0.4
        BARS_SINCE_HL_THRESHOLD = 10

        d_swH = (_v6_bar_v4 or {}).get("dist_swing_high") or (_v6_bar_v4 or {}).get("dist_last_swing_high_pct")
        d_swL = (_v6_bar_v4 or {}).get("dist_swing_low") or (_v6_bar_v4 or {}).get("dist_last_swing_low_pct")

        # Skip CHASE conditions (raffinement V4)
        # FIX agent re-audit : emit V6_CHASE_SKIPPED INFO pour audit J+1.
        # Sans emit, impossible de tracer combien de CHASE sont evites par R8.
        skip_chase = False
        skip_reason = None
        if direction == "LONG":
            bars_since_low = (_v6_bar_v4 or {}).get("bars_since_last_swing_low")
            if bars_since_low is not None:
                try:
                    if float(bars_since_low) <= BARS_SINCE_HL_THRESHOLD:
                        skip_chase = True; skip_reason = "hl_recent"  # higher low recent = stair-step OK
                except (TypeError, ValueError):
                    pass
            if not skip_chase:
                wick_low = (_v6_bar_v4 or {}).get("bar_lower_wick_pct")
                if wick_low is not None:
                    try:
                        if float(wick_low) > WICK_THRESHOLD:
                            skip_chase = True; skip_reason = "wick_rejection"  # wick rejection support = entry valide
                    except (TypeError, ValueError):
                        pass
        elif direction == "SHORT":
            bars_since_high = (_v6_bar_v4 or {}).get("bars_since_last_swing_high")
            if bars_since_high is not None:
                try:
                    if float(bars_since_high) <= BARS_SINCE_HL_THRESHOLD:
                        skip_chase = True; skip_reason = "hl_recent"
                except (TypeError, ValueError):
                    pass
            if not skip_chase:
                wick_up = (_v6_bar_v4 or {}).get("bar_upper_wick_pct")
                if wick_up is not None:
                    try:
                        if float(wick_up) > WICK_THRESHOLD:
                            skip_chase = True; skip_reason = "wick_rejection"
                    except (TypeError, ValueError):
                        pass

        if skip_chase and _v2log:
            _v2log.emit("V6_CHASE_SKIPPED",
                        sym=symbol, direction=direction,
                        reason=skip_reason)

        # 🆕 V6 GATE VOL_Z LOW (Phase 11 PEPITE #2 — anti-faux-breakout)
        # Trade #1 ce matin : RVOL 0.23 = volume_z ~ -1.4 = breakout sans volume
        # = faux breakout systematique. Ce gate filtre les entries ou volume_z<-1.5.
        # FIX R2 re-audit code-reviewer (05/05) : seuil -1.0 trop sensible
        # (16% bars rejetees sur distribution standard). -1.5 cible la queue
        # (6.7%, alignee sur cas reel motivant z=-1.4). Re-tester apres 100
        # trades validation, descendre vers -1.0 si trop permissif.
        # Densite volume_z : 100% sur V4 enriched.
        VOL_Z_THRESHOLD = -1.5
        volume_z = (_v6_bar_v4 or {}).get("volume_z")
        if volume_z is not None:
            try:
                v = float(volume_z)
                if v < VOL_Z_THRESHOLD:
                    self._funnel_reject("6_conf_mtf", "v6_volume_z_too_low",
                                        symbol=symbol, direction=direction,
                                        volume_z=round(v, 2),
                                        threshold=VOL_Z_THRESHOLD,
                                        action=action, signal_id=signal_id,
                                        **market_ctx)
                    return None
            except (TypeError, ValueError):
                pass

        if not skip_chase:
            if direction == "LONG" and d_swH is not None:
                try:
                    d = float(d_swH)
                    if 0 <= d <= TOL_CHASE_LONG:
                        self._funnel_reject("6_conf_mtf", "v6_chase_long_near_swing_high",
                                            symbol=symbol, direction=direction,
                                            dist_swing_high=d,
                                            threshold=TOL_CHASE_LONG,
                                            action=action, signal_id=signal_id,
                                            **market_ctx)
                        return None
                except (TypeError, ValueError):
                    pass
            if direction == "SHORT" and d_swL is not None:
                try:
                    d = float(d_swL)
                    if -TOL_CHASE_SHORT <= d <= 0:
                        self._funnel_reject("6_conf_mtf", "v6_chase_short_near_swing_low",
                                            symbol=symbol, direction=direction,
                                            dist_swing_low=d,
                                            threshold=-TOL_CHASE_SHORT,
                                            action=action, signal_id=signal_id,
                                            **market_ctx)
                        return None
                except (TypeError, ValueError):
                    pass

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

        # ─── 6ter. RangeGate (30/04 v3 Jackson "ON A ACHETE HAUT DE RANGE") ──
        # Confluence 4 metriques (VA + IB + DAY + MQ_1D) : skip si >=2/4 en
        # zone extreme. Plus cas special BREAKOUT_VA (range_pos extreme +
        # inside_cur_va=0). Reproduction trade ES LONG @ 7197.75 → SL hit -30t.
        # Reversibilite via ENTRY_RULES['range_gate_enabled'] (default True).
        if ENTRY_RULES.get("range_gate_enabled", True):
            try:
                from CORE.range_gate import evaluate_range_gate
            except ImportError:
                from range_gate import evaluate_range_gate
            # Conversion direction Bot 1 ("LONG"/"SHORT") -> "BUY"/"SELL"
            rg_dir = "BUY" if direction == "LONG" else "SELL"
            rg_result = evaluate_range_gate(
                bar_row_dict, rg_dir, symbol,
                enabled=True,
                min_confluence=ENTRY_RULES.get("range_gate_min_confluence", 2),
                mode=ENTRY_RULES.get("range_gate_mode", "observe"),
            )
            # Log would_skip meme en mode observe (bench 5j R1 code-reviewer)
            if rg_result.would_skip and _v2log:
                try:
                    _v2log.emit("GENERIC_INFO",
                                msg=(f"range_gate [{rg_result.mode}] {symbol} "
                                     f"{direction}: {rg_result.skip_reason}"))
                except Exception:
                    pass
            if rg_result.skip:
                self._funnel_reject("6ter_range", "range_extreme",
                                    symbol=symbol,
                                    direction=direction,
                                    skip_reason=rg_result.skip_reason,
                                    high_count=rg_result.high_count,
                                    low_count=rg_result.low_count,
                                    **market_ctx)
                return None
            self._funnel_pass("6ter_range")

        # ─── 6quart. RegimeGate (30/04 v4 Jackson "ON APPLIQUE PAPER DIRECT") ──
        # Skip empirique categories LOSERS : profile_shape==0 (D Range -19t)
        # + day_type==1 (Normal -19t). Backtest 80 trades Bot 1 : 22.5%
        # bloques, PnL eviter -354$, PnL garde +401$, WR 23%→37.8%.
        # ml-trainer NOGO sur dataset v3 mais profile_shape ABSENT du v3 →
        # validation empirique paper = seul recours. Reversibilite via flag.
        if ENTRY_RULES.get("regime_gate_enabled", True):
            try:
                from CORE.regime_gate import evaluate_regime_gate
            except ImportError:
                from regime_gate import evaluate_regime_gate
            reg_result = evaluate_regime_gate(bar_row_dict, direction, enabled=True)
            if reg_result.skip:
                # Reason fine : profile_shape ou day_type ?
                reason_key = ("regime_loser_profile_shape"
                              if "PROFILE_SHAPE" in reg_result.skip_reason
                              else "regime_loser_day_type")
                self._funnel_reject("6quart_regime", reason_key,
                                    symbol=symbol,
                                    direction=direction,
                                    skip_reason=reg_result.skip_reason,
                                    profile_shape=reg_result.profile_shape,
                                    day_type=reg_result.day_type,
                                    open_type=reg_result.open_type,
                                    **market_ctx)
                return None
            self._funnel_pass("6quart_regime")

        # ─── 6cinq. EntryQualityGate (LOT 2B Jackson "ON APPLIQUE") ───────
        # Skip si momentum_5b ET cvd_bar_delta BOTH contra direction.
        # Backtest 104 trades : 32.7% bloques, PnL eviter -1803$, WR 23→53.8%.
        if ENTRY_RULES.get("entry_quality_gate_enabled", True):
            try:
                from CORE.entry_quality_gate import evaluate_entry_quality_gate
            except ImportError:
                from entry_quality_gate import evaluate_entry_quality_gate
            eq_result = evaluate_entry_quality_gate(
                bar_row_dict, direction,
                enabled=True,
                strict_mode=ENTRY_RULES.get("entry_quality_gate_strict", False),
            )
            if eq_result.skip:
                self._funnel_reject("6cinq_entry_quality", "entry_quality_both_contra",
                                    symbol=symbol,
                                    direction=direction,
                                    skip_reason=eq_result.skip_reason,
                                    momentum_5b=eq_result.momentum_5b,
                                    cvd_bar_delta=eq_result.cvd_bar_delta,
                                    next_wall_dist_ticks=eq_result.next_wall_dist_ticks,
                                    **market_ctx)
                return None
            self._funnel_pass("6cinq_entry_quality")

        # ─── 6six. ChaseTopGate (05/05/2026 — walk-forward Lopez DSR=0.72) ────
        # Bloque LONG si range_pos >= 60 (chase top du range RTH).
        # Audit empirique 90 trades + walk-forward 5-fold LONG-only :
        # delta +$1264, ratio 5.5x SL/TP evites, DSR=0.72 > Lopez seuil 0.5.
        # SHORT non filtre (filter symetrique casse les SHORT).
        # R3 kill-switch + R2 enriched log (price_ref pour audit RESCUED J+7).
        if _CHASE_TOP_GATE_ENABLED and direction == "LONG":
            range_pos_check = reg.get("range_pos", 50)
            try:
                range_pos_val = float(range_pos_check) if range_pos_check is not None else 50
            except (TypeError, ValueError):
                range_pos_val = 50
            if range_pos_val >= _CHASE_TOP_THRESHOLD:
                # 07/05 TREND DAY OVERRIDE (audit walk-forward) : bypass si trend confirmed
                rp_history = list(getattr(self, "_range_pos_history", {}).get(symbol, []))
                td_ok, td_reason = _is_trend_day(direction, reg, rp_history)
                if td_ok:
                    if _v2log:
                        try:
                            _v2log.emit("GATE_CHASE_TOP_TREND_DAY_BYPASS",
                                        symbol=symbol, direction=direction,
                                        range_pos=round(range_pos_val, 1),
                                        threshold=_CHASE_TOP_THRESHOLD,
                                        reason=td_reason,
                                        trend_votes=reg.get("regime_trend_votes"),
                                        regime_favor=reg.get("regime_favor"),
                                        median_range_pos=round(
                                            sum(rp_history) / max(len(rp_history), 1), 1)
                                            if rp_history else None,
                                        n_history=len(rp_history))
                        except Exception:
                            pass
                    self._funnel_pass("6six_chase_top")
                else:
                    price_ref = bar_row_dict.get("price") or bar_row_dict.get("close") or 0
                    self._funnel_reject("6six_chase_top", "chase_top_long_range_high",
                                        symbol=symbol, direction=direction,
                                        range_pos=round(range_pos_val, 1),
                                        threshold=_CHASE_TOP_THRESHOLD,
                                        price_ref=price_ref,
                                        block_ts=time.time(),
                                        trend_day_check=td_reason,
                                        **market_ctx)
                    return None
            else:
                self._funnel_pass("6six_chase_top")

        # ─── Observe-only tracker SHORT au bottom (audit J+14) ────────────────
        # Risque miroir : SHORT au low pourrait etre piege. Audit n=32 dit NOGO
        # block mais sample sous Lopez n>=100. Track sans bloquer.
        if direction == "SHORT" and _v2log:
            try:
                rp_short = reg.get("range_pos", 50)
                rp_short_val = float(rp_short) if rp_short is not None else 50
                if rp_short_val <= 30:
                    _v2log.emit("SHORT_AT_BOTTOM_OBSERVED",
                                sym=symbol, direction=direction,
                                range_pos=round(rp_short_val, 1),
                                entry_price=bar_row_dict.get("price") or bar_row_dict.get("close") or 0,
                                obs_ts=time.time())
            except (TypeError, ValueError, Exception):
                pass

        # ─── Observe-only EDGE RETEST tracker (06/05 — V4 Phase B+++ Edge Zones)
        # Setup ICT : push violent cree zone edge -> retest 70% chance.
        # Tracker SHORT vers edge_sell + LONG vers edge_buy (touche < 0.10%).
        # Audit J+14 : WR vs baseline pour decider integration future setup actif.
        if _v2log:
            try:
                price_now = bar_row_dict.get("price") or bar_row_dict.get("close") or 0
                d_sell = bar_row_dict.get("dist_edge_sell_nearest_pct")
                n_sell = bar_row_dict.get("n_edge_sell_active", 0) or 0
                if d_sell is not None and not pd.isna(d_sell) and abs(float(d_sell)) <= 0.10 and float(n_sell) >= 1 and direction == "SHORT":
                    _v2log.emit("EDGE_SELL_RETEST_OBSERVED",
                                sym=symbol, direction=direction,
                                dist_pct=round(float(d_sell), 3),
                                n_active=int(n_sell),
                                entry_price=price_now,
                                obs_ts=time.time())
                d_buy = bar_row_dict.get("dist_edge_buy_nearest_pct")
                n_buy = bar_row_dict.get("n_edge_buy_active", 0) or 0
                if d_buy is not None and not pd.isna(d_buy) and abs(float(d_buy)) <= 0.10 and float(n_buy) >= 1 and direction == "LONG":
                    _v2log.emit("EDGE_BUY_RETEST_OBSERVED",
                                sym=symbol, direction=direction,
                                dist_pct=round(float(d_buy), 3),
                                n_active=int(n_buy),
                                entry_price=price_now,
                                obs_ts=time.time())
            except (TypeError, ValueError, Exception):
                pass

        # 7. SLTPEngine — calcul intelligent Tier 1/2 murs + TP1
        engine = self.sltp_engines[symbol]
        sltp_result = engine.evaluate_single(bar_row_dict, direction_int)

        if not sltp_result.valid:
            # Granularite fine : classify reject_reason brut en 4 sous-raisons.
            sltp_rej = getattr(sltp_result, "reject_reason", "") or ""
            reason_fine = self._classify_sltp_reject(sltp_rej)
            # 🆕 v6 30/04 : tracking CAS 4 capot T1+T2_STRUCTUREL qui force rejet
            # (Jackson "enrichis logs pour tracker rejets fix"). Permet grep
            # ex-post pour audit fire rate du fix v6 + identifier murs offenders.
            cas4_kwargs = {}
            if getattr(sltp_result, "cas4_caused_reject", False):
                cas4_kwargs = {
                    "cas4_caused_reject": True,
                    "cas4_subtier": getattr(sltp_result, "cas4_subtier", ""),
                    "cas4_blocked_wall": getattr(sltp_result, "cas4_blocked_wall", ""),
                    "cas4_blocked_col": getattr(sltp_result, "cas4_blocked_wall_col", ""),
                    "cas4_blocked_dist": getattr(sltp_result, "cas4_blocked_wall_dist", 0.0),
                    "cas4_blocked_tier": getattr(sltp_result, "cas4_blocked_wall_tier", 0),
                    "cas4_rr_pre": getattr(sltp_result, "cas4_rr_pre", 0.0),
                    "cas4_rr_post": getattr(sltp_result, "cas4_rr_post", 0.0),
                    "cas4_tp_pre": getattr(sltp_result, "cas4_tp_standard_pre", 0.0),
                }
                # Surcharger reason_fine pour granularite "cas4_capot"
                reason_fine = f"cas4_capot_{cas4_kwargs['cas4_subtier'].lower()}"
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
                                **cas4_kwargs,
                                **market_ctx)
            return None
        self._funnel_pass("7_sltp")

        sl_ticks = sltp_result.sl_ticks
        tp_ticks = sltp_result.tp1_ticks  # Jackson choix : UN SEUL TP (pas trailing/runner)

        # 8. Filtre expected_payoff_$ (audit ES vs NQ 22/04) avec WR dynamique
        # 04/05 SOIR (Jackson reset) : wr Bayesien conditionnel par cellule
        # symbol x direction x session_id (au lieu de wr global).
        tv = TICK_VALUE[symbol]
        sess_id_ctx = bar_row_dict.get("session_id") if isinstance(bar_row_dict, dict) else None
        wr = self._get_dynamic_wr(
            symbol=symbol,
            direction=direction,
            session_id=sess_id_ctx,
        )
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

        # FIX 29/04 (Jackson) : SL ancre au bar_low (LONG) / bar_high (SHORT).
        # Avant : SL relatif au close = stoppe sur n'importe quel wick adverse
        # (cf 5 trades 0min Bot 1 le 28/04 NQ : -$335 perdu sur wicks).
        # Apres : SL sous le bar_low (LONG) = sous le mouvement adverse deja
        # vu = protection structurelle + TP stretch pour preserver R/R.
        # DMP schema 3.7.1+ fournit `bar_low`/`bar_high` (CLAUDE.md).
        # FIX audit R2 (29/04) : fail-loud emit si bar_low/high manquant
        # (regression DMP schema = signal a investiguer, pas masquer).
        bar_low_v = bar_row_dict.get("bar_low")
        bar_high_v = bar_row_dict.get("bar_high")
        bar_anchor_fallback = False
        try:
            if bar_low_v is None or bar_high_v is None:
                raise ValueError("bar_low or bar_high missing in DMP bar")
            bar_low_v = float(bar_low_v)
            bar_high_v = float(bar_high_v)
        except (TypeError, ValueError) as e:
            bar_low_v, bar_high_v = price, price
            bar_anchor_fallback = True
            if _v2log:
                _v2log.emit("SL_ANCHOR_BAR_MISSING", sym=symbol,
                            err=type(e).__name__, msg=str(e)[:80])

        if direction == "LONG":
            sl_anchor = min(bar_low_v, price)  # plus bas (low ou price si marubozu up)
            sl_price = round(sl_anchor - sl_ticks * TICK_SIZE, 2)
            tp_price = round(price + tp_ticks * TICK_SIZE, 2)
        else:
            sl_anchor = max(bar_high_v, price)  # plus haut
            sl_price = round(sl_anchor + sl_ticks * TICK_SIZE, 2)
            tp_price = round(price - tp_ticks * TICK_SIZE, 2)
        sl_extra_ticks = abs(sl_anchor - price) / TICK_SIZE

        # Re-cap budget post-ancrage : si SL ancre fait depasser max_sl_usd
        # ($75 par sym), fallback ancre au price (close) + log warn.
        # Sans ca : ancrage silencieux peut violer le budget config.
        max_sl_usd_eng = engine.max_sl_usd
        tick_value_sym = engine.tick_value
        n_micros_sym = engine.n_micros
        risk_usd_post = abs(price - sl_price) * tick_value_sym * n_micros_sym
        if risk_usd_post > max_sl_usd_eng:
            if _v2log:
                _v2log.emit("SL_ANCHOR_BUDGET_OVERFLOW", sym=symbol,
                            risk_usd=round(risk_usd_post, 2),
                            budget=max_sl_usd_eng,
                            sl_extra_ticks=int(sl_extra_ticks))
            if direction == "LONG":
                sl_price = round(price - sl_ticks * TICK_SIZE, 2)
            else:
                sl_price = round(price + sl_ticks * TICK_SIZE, 2)
            sl_extra_ticks = 0  # reset car ancrage abandonne

        # TP stretch : etirer TP de meme sl_extra_ticks pour preserver R/R
        # initial (sinon R/R degrade silencieusement).
        if sl_extra_ticks > 0:
            if direction == "LONG":
                tp_price = round(tp_price + sl_extra_ticks * TICK_SIZE, 2)
            else:
                tp_price = round(tp_price - sl_extra_ticks * TICK_SIZE, 2)
            # tp_ticks reflete le nouveau TP pour traçabilite signal output
            tp_ticks = tp_ticks + int(sl_extra_ticks)
            # FIX audit R1 (29/04) : recalculer expected_payoff_usd avec tp_ticks
            # ajuste (sinon snapshot logge payoff obsolete = bruit ML training).
            expected_payoff_usd = (wr * tp_ticks - (1 - wr) * sl_ticks) * tv * ENTRY_RULES["n_micros"]

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
            # 🆕 v6 30/04 tracking CAS 4 sur trades qui PASSENT (capot mute mais
            # R:R reste >= MIN_RR_RATIO). Permet audit ex-post : trades pris
            # avec TP capote vs trades pris sans capot.
            "cas4_triggered": getattr(sltp_result, "cas4_triggered", False),
            "cas4_subtier": getattr(sltp_result, "cas4_subtier", ""),
            "cas4_blocked_wall": getattr(sltp_result, "cas4_blocked_wall", ""),
            "cas4_blocked_col": getattr(sltp_result, "cas4_blocked_wall_col", ""),
            "cas4_blocked_dist": getattr(sltp_result, "cas4_blocked_wall_dist", 0.0),
            "cas4_blocked_tier": getattr(sltp_result, "cas4_blocked_wall_tier", 0),
            "cas4_rr_pre": getattr(sltp_result, "cas4_rr_pre", 0.0),
            "cas4_rr_post": getattr(sltp_result, "cas4_rr_post", 0.0),
            "cas4_tp_pre": getattr(sltp_result, "cas4_tp_standard_pre", 0.0),
            "cas4_observed_t2": getattr(sltp_result, "cas4_observed_tier2", False),
            "cas4_observed_t2_wall": getattr(sltp_result, "cas4_observed_wall_t2", ""),
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

    def _load_last_bar_v4(self, symbol: str, cache_ttl_sec: float = 60.0) -> Optional[dict]:
        """Charge la derniere barre V4 ENRICHIED (Databento 456 features) pour le symbol.

        FIX CRITIQUE 05/05 (Jackson "branche V6 a Databento") : sans cette lecture,
        les blocs 7-16 bias_v6 + votes 11-16 regime_v6 sont dead code (les features
        V4 specifiques type bars_since_swing, wick_pct, im_smt, cluster_at_*, naked_poc,
        ctx_* sont ABSENTES du DMP JSONL Sierra Chart).

        Pattern copie de databento_paper_trader_v2.py:load_last_bar (Bot 2 V2).
        Cache 60s pour eviter read_parquet I/O a chaque poll (V4 update toutes 5 min).

        Args:
            symbol: 'NQ' ou 'ES'
            cache_ttl_sec: max age cache local avant relecture (defaut 60s)

        Returns:
            dict bar V4 enrichi (456 features) ou None si parquet indisponible.
        """
        # Cache hit ?
        last_load = self._v4_bar_cache_ts.get(symbol, 0)
        if time.time() - last_load < cache_ttl_sec:
            cached = self._v4_bar_cache.get(symbol)
            if cached:
                return cached

        # Lecture parquet
        try:
            import pandas as pd
            now_utc = datetime.now(timezone.utc)
            candidates = []
            for offset in (0, -1):  # mois courant + mois precedent
                m = now_utc.month + offset
                y = now_utc.year
                if m < 1:
                    m += 12
                    y -= 1
                fp = os.path.join(
                    V4_DATASET_ROOT,
                    f"symbol={symbol}.c.0",
                    f"year={y}",
                    f"month={m:02d}",
                    "data.parquet",
                )
                if os.path.exists(fp):
                    candidates.append(fp)
            if not candidates:
                return None
            df = pd.read_parquet(candidates[0])
            if df.empty:
                return None
            df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
            df = df.dropna(subset=["ts_event"]).sort_values("ts_event")
            bar = df.iloc[-1].to_dict()
            # Convertir Timestamp pandas en str ISO pour JSON safety downstream
            ts_ev = bar.get("ts_event")
            if hasattr(ts_ev, "isoformat"):
                bar["ts_event_iso"] = ts_ev.isoformat()

            # FIX 17/05 (Jackson "brancher Bot 2 V6 comme Bot 3") : threshold
            # aligne Bot 3 (databento_paper_trader_v2.py:187 DATA_CRIT_THR_SEC=2700).
            # Avant : 600s -> fallback DMP 100% du temps (12692 emits V6_V4_BAR_STALE
            # le 15/05 = pipeline V4 stale 1266s = 21min, jamais < 600s en pratique).
            # Apres : 2700s (45 min) = Bot 2 V6 utilise V4 enriched comme Bot 3 le fait.
            # Le fallback DMP reste safety net mais devient rare (pipeline normalement
            # < 30 min stale, > 45 min = bug pipeline a investiguer via watchdog).
            STALE_THRESHOLD_SEC = 2700
            try:
                if hasattr(ts_ev, "timestamp"):
                    bar_age_sec = (datetime.now(timezone.utc) - ts_ev.to_pydatetime()).total_seconds()
                else:
                    bar_age_sec = 0
                if bar_age_sec > STALE_THRESHOLD_SEC:
                    if _v2log:
                        _v2log.emit("V6_V4_BAR_STALE",
                                    sym=symbol,
                                    age_sec=int(bar_age_sec),
                                    threshold=STALE_THRESHOLD_SEC)
                    # FIX agent re-audit : invalider cache aussi pour ne pas
                    # retourner cached stale au prochain appel < 60s.
                    self._v4_bar_cache.pop(symbol, None)
                    self._v4_bar_cache_ts.pop(symbol, None)
                    return None  # force fallback DMP
                bar["v4_bar_age_sec"] = round(bar_age_sec, 1)
            except Exception:
                pass

            # Cache (uniquement si bar fresh)
            self._v4_bar_cache[symbol] = bar
            self._v4_bar_cache_ts[symbol] = time.time()
            return bar
        except Exception as e:
            if _v2log:
                _v2log.emit("GENERIC_MAJEUR",
                            msg=f"V4 enriched bar load fail {symbol}: {e}")
            return None

    def _load_recent_trades(self, days: int = 10, post_levier_only: bool = True) -> list:
        """Helper : charge trades historiques des N derniers jours (incl today).

        Lit *_trades.jsonl, parse JSON, retourne liste triee par fichier.
        Robuste aux fichiers corrompus / lignes invalides (skip silent).

        Args:
            days: nombre de jours a charger (max).
            post_levier_only: si True, ne garde que les trades post-deploy LEVIER #1
                (>= 2026-05-04). Avant cette date, distribution wr biaisee par
                bias regime non filtre (cf ml-trainer R3 stationarity).
        """
        from glob import glob
        from datetime import date as _date
        # Date pivot LEVIER #1 deploy (Jackson 04/05 soir)
        LEVIER_PIVOT_DATE = _date(2026, 5, 4)

        # FIX 05/05 cohérence Bot 2 V6 : ne charger QUE les trades V6
        # (pattern {date}_v6_trades.jsonl) pour ne pas calculer wr_dynamic
        # avec les trades Bot 1 — ils ont des bias/regime/feature tracking
        # différents (signal_engine vs bias_v6).
        all_files = sorted(glob(os.path.join(DATA_DIR, "*_v6_trades.jsonl")))
        all_files = all_files[-days:]
        all_trades = []
        for fp in all_files:
            # Filter par date fichier si post_levier_only
            if post_levier_only:
                fname = os.path.basename(fp)
                try:
                    file_date = _date(int(fname[:4]), int(fname[4:6]), int(fname[6:8]))
                    if file_date < LEVIER_PIVOT_DATE:
                        continue
                except (ValueError, IndexError):
                    pass
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            all_trades.append(json.loads(s))
                        except json.JSONDecodeError:
                            pass
            except OSError:
                continue
        # Append today_trades non encore persistes en JSONL
        all_trades.extend(self.today_trades)
        return all_trades

    def _wr_shrinkage(self, n: int, wins: int, prior: float, k: int) -> float:
        """Shrinkage Bayesien : combine wr_observed avec prior pondere par k.

        Formule : (n * wr_obs + k * prior) / (n + k)
        - n=0 -> prior pur
        - n=15, wr=0.30, prior=0.50, k=15 -> 0.400 (au lieu de 0.300 brut)
        - n=100, wr=0.30, prior=0.50, k=15 -> 0.326 (poids fort sur observe)
        """
        if n <= 0:
            return prior
        wr_obs = wins / n
        return (n * wr_obs + k * prior) / (n + k)

    def _get_dynamic_wr(
        self,
        symbol: str = None,
        direction: str = None,
        session_id: str = None,
    ) -> float:
        """WR Bayesien conditionnel par cellule (symbol x direction x session).

        RESET 04/05 SOIR (Jackson + reviews croises code-reviewer + ml-trainer) :
        refonte complete du _get_dynamic_wr.

        Avant : wr global rolling 30 trades sans conditionnement -> 0.30 en Asia
        bloquait tous les SHORT NQ par EV negatif.

        Apres : shrinkage Bayesien hierarchique :
          1. wr_global = shrink(global_obs, prior=0.40, k=30)
             - prior=0.40 (break-even RR=2 = 0.333, +marge) au lieu de 0.50 pro-trade
             - k=30 shrink fort tant que n_glob<50 (regime initial = mostly prior)
          2. Si N_cell (sym x dir [x session]) >= 15 :
             wr_cell = shrink(cell_obs, prior=wr_global, k=10)
             - cell_min_n=15 pour CI Wilson fiable [+/-0.15 vs [0.12,0.77] sur N=5]
             - k_cell=10 plus permissif que k_global (laisse cellule diverger)
          3. Sinon : wr = wr_global (fallback)

        Filtre stationarity : `_load_recent_trades(post_levier_only=True)` ne
        garde que les trades >= 2026-05-04 (deploy LEVIER #1) pour eviter biais
        distribution pre-LEVIER (ml-trainer R3).

        Args:
            symbol: 'ES' ou 'NQ' (cellule). None -> wr global.
            direction: 'LONG' ou 'SHORT' (cellule). None -> wr global.
            session_id: session courante (ignore si pas dans data historique).

        Returns:
            wr [0.0, 1.0] shrunk Bayesien.

        Note : `session_id` peut etre fourni mais sera ignore si la persistance
        des trades historiques ne contient pas ce champ (cas actuel 04/05).
        Fallback automatique sur cellule (symbol x direction) sans session.
        Long-term TODO : ajouter session_id au dict trade dans _close_trade.
        """
        prior = ENTRY_RULES.get("wr_shrinkage_prior", 0.40)
        k_global = ENTRY_RULES.get("wr_shrinkage_k", 30)
        k_cell = ENTRY_RULES.get("wr_cell_shrinkage_k", 10)
        cell_min_n = ENTRY_RULES.get("wr_cell_min_n", 15)

        # Filter post-LEVIER pour stationarity (ml-trainer R3)
        all_trades = self._load_recent_trades(days=10, post_levier_only=True)

        # Helper safe : pnl_ticks=None possible si trade non close (code-reviewer R3)
        def _is_win(t: dict) -> bool:
            v = t.get("pnl_ticks")
            return v is not None and v > 0

        # 1. WR global shrunk (toujours calcule, sert de fallback)
        n_glob = len(all_trades)
        wins_glob = sum(1 for t in all_trades if _is_win(t))
        wr_global = self._wr_shrinkage(n_glob, wins_glob, prior, k_global)

        # 2. Conditionnement cellule (si contexte fourni)
        if symbol and direction:
            # Tentative cellule sym x dir x session
            cell_trades = [
                t for t in all_trades
                if t.get("symbol") == symbol
                and t.get("direction") == direction
                and (session_id is None or t.get("session_id") == session_id)
            ]
            # Audit indep 04/05 soir : session_id manquant dans 100% trades
            # historiques pre-deploy. Fallback : si session_id passe mais pas
            # assez de data, retomber sur cellule sym x dir (sans session) pour
            # ne pas perdre le conditionnement principal.
            # Long-term : logger session_id dans _close_trade (TODO ouvert).
            if session_id and len(cell_trades) < cell_min_n:
                cell_trades = [
                    t for t in all_trades
                    if t.get("symbol") == symbol
                    and t.get("direction") == direction
                ]
            n_cell = len(cell_trades)
            if n_cell >= cell_min_n:
                wins_cell = sum(1 for t in cell_trades if _is_win(t))
                # Shrinkage hierarchique : prior = wr_global (pas constant 0.40)
                # Permet a la cellule de coller au global si pas assez de data,
                # et de diverger quand assez d'evidence empirique.
                # k_cell=10 (separe de k_global=30) pour reactivite cellule.
                wr_cell = self._wr_shrinkage(n_cell, wins_cell, wr_global, k_cell)
                return wr_cell

        return wr_global

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

        # 12/05 FIX entry_price (cf INCIDENT_LOG 2026-05-12 03:30) : recuperer
        # fill_price REEL broker via get_last_fill_price() au lieu de signal_price.
        fill_price_real = 0.0
        if not getattr(self, "dry_run", False) and parent_id:
            try:
                fill_price_real = self.dtc.get_last_fill_price(parent_id) or 0.0
            except Exception:
                fill_price_real = 0.0
        entry_price_effective = fill_price_real if fill_price_real > 0 else signal["entry_price"]
        entry_drift_ticks = 0.0
        if fill_price_real > 0:
            _dir_sign = 1 if signal["direction"] == "LONG" else -1
            entry_drift_ticks = round((fill_price_real - signal["entry_price"]) / TICK_SIZE * _dir_sign, 1)
            if _v2log:
                try:
                    _v2log.emit("BOT_ENTRY_FILL_RECORDED",
                                sym=symbol, direction=signal["direction"],
                                signal_price=signal["entry_price"],
                                fill_price=fill_price_real,
                                drift_ticks=entry_drift_ticks,
                                bot="bot2_v6")
                except Exception:
                    pass

        position = {
            "symbol": symbol,
            "direction": signal["direction"],
            "entry_price": entry_price_effective,  # 12/05 FIX : fill_price reel
            "signal_price": signal["entry_price"],  # 12/05 FIX : tracking signal separe
            "entry_drift_ticks": entry_drift_ticks,  # 12/05 FIX : audit drift
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
            # FIX code-reviewer R1 (04/05 soir) : capture session_id au moment
            # entry pour persistance dans le trade JSONL (cellule wr conditionnelle).
            # Source : signal["dmp_bar"]["session_id"] qui contient "Asia"/"London"/"US"/"AH".
            "session_id": (signal.get("dmp_bar") or {}).get("session_id", ""),
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

        # ─── TRAILING STOP TR40_20 (FIX 30/04 audit market-analyst) ─────────
        # Pilot NQ only (audit : ES marginal F2 fold PF 0.88 < 1.0).
        # Trail s'arme quand MFE >= 40% du SL initial.
        # Give back 20% du SL initial → trail SL = entry +/- (MFE - 20% × SL_init) ticks.
        # SL ne va QUE dans le sens favorable (LONG : monte, SHORT : descend).
        # Validation backtest 4 mois : PF 0.99 → 1.32, walk-forward 3/3, CI95 [1.15, 1.51].
        # NOTE paper Sim3 : on update pos["sl_price"] (simu only). Le bracket SL broker
        # reste a l'ancien prix mais ne fait jamais fill car la simu close en premier.
        # Pour LIVE : ajouter cancel + replace SL bracket via DTC (TODO).
        # 🔴 P0 SECURITE 01/05 : flag TRAILING_TR40_NQ_ENABLED desactive en attendant
        # implementation cancel+replace broker (refacto Chemin B). Cf constants.py.
        if symbol == "NQ" and TRAILING_TR40_NQ_ENABLED:
            sl_dist_ticks_init = pos.get("sl_ticks_initial")
            if sl_dist_ticks_init is None:
                sl_dist_ticks_init = pos.get("sl_ticks")
                if sl_dist_ticks_init:
                    pos["sl_ticks_initial"] = sl_dist_ticks_init  # snapshot a la 1ere passe
            if sl_dist_ticks_init and sl_dist_ticks_init > 0:
                arming_thr = 0.40 * sl_dist_ticks_init
                give_back = 0.20 * sl_dist_ticks_init
                if pos.get("mfe", 0) >= arming_thr:
                    # Emit ARM uniquement a la PREMIERE fois (sl_trailed pas encore True)
                    if not pos.get("sl_trailed", False) and _v2log:
                        try:
                            _v2log.emit("TRAILING_TR40_ARMED", sym=symbol,
                                        mfe=round(pos["mfe"], 1),
                                        arming_thr=round(arming_thr, 1),
                                        sl_init=round(sl_dist_ticks_init, 1))
                        except Exception:
                            pass

                    new_sl_price = None
                    if pos["direction"] == "LONG":
                        candidate = pos["entry_price"] + (pos["mfe"] - give_back) * TICK_SIZE
                        if candidate > pos["sl_price"]:  # SL monte uniquement
                            new_sl_price = candidate
                    else:  # SHORT
                        candidate = pos["entry_price"] - (pos["mfe"] - give_back) * TICK_SIZE
                        if candidate < pos["sl_price"]:  # SL descend uniquement
                            new_sl_price = candidate
                    if new_sl_price is not None:
                        # FIX C1 (review code-reviewer 30/04) : alignement sur tick
                        # NQ tick=0.25. round(price/tick)*tick garantit multiple valide.
                        # Sans ce fix : 7209.55 sortait au lieu de 7209.50 (= rejet broker live).
                        aligned_sl = round(round(new_sl_price / TICK_SIZE) * TICK_SIZE, 2)

                        # Emit TICK_MISALIGN si delta > 0.5 tick (anomalie : prix
                        # candidate enormement loin de la grille tick — bug calcul ?)
                        delta_ticks = abs(new_sl_price - aligned_sl) / TICK_SIZE
                        if delta_ticks > 0.5 and _v2log:
                            try:
                                _v2log.emit("TRAILING_TR40_NOT_ALIGNED", sym=symbol,
                                            sl_raw=round(new_sl_price, 4),
                                            sl_aligned=round(aligned_sl, 2),
                                            delta_ticks=round(delta_ticks, 2))
                            except Exception:
                                pass

                        # SL ne doit toujours aller que dans le sens favorable apres alignement
                        old_sl = pos["sl_price"]  # capturer AVANT branchement (fix bug NameError)
                        if (pos["direction"] == "LONG" and aligned_sl > old_sl) or \
                           (pos["direction"] == "SHORT" and aligned_sl < old_sl):
                            pos["sl_price"] = aligned_sl
                            pos["sl_trailed"] = True
                            pos["sl_trail_count"] = pos.get("sl_trail_count", 0) + 1
                            # FIX I1 backlog LIVE : persister sl_ticks_initial pour
                            # que reload state.json ne re-snapshot pas avec un sl_ticks modifie.
                            # (deja fait via pos["sl_ticks_initial"] set au-dessus)
                            print(f"[{symbol}] SL TRAIL: {old_sl:.2f} → {pos['sl_price']:.2f} "
                                  f"(MFE={pos['mfe']:.0f}t, SL_init={sl_dist_ticks_init:.0f}t, "
                                  f"arm={arming_thr:.0f}t, gb={give_back:.0f}t)")
                            if _v2log:
                                try:
                                    _v2log.emit("TRAILING_TR40_UPDATED", sym=symbol,
                                                old_sl=round(old_sl, 2),
                                                new_sl=round(pos["sl_price"], 2),
                                                give_back=round(give_back, 1),
                                                count=pos["sl_trail_count"])
                                except Exception:
                                    pass
                        else:
                            # Aligned price ne progresse pas en faveur (cas rare).
                            # Track pour diagnostic : si frequent → arming_thr/give_back
                            # mal calibre OU bug calcul.
                            if _v2log:
                                try:
                                    _v2log.emit("TRAILING_TR40_LOOSEN_BLOCK", sym=symbol,
                                                new_sl=round(aligned_sl, 2),
                                                current_sl=round(old_sl, 2),
                                                direction=pos["direction"])
                                except Exception:
                                    pass

        # ─── LEVIER A : Trailing TP MFE-based (Jackson 04/05 soir Option 2) ─
        # Audit 28 TIMEOUT : MFE peak rendu au marche (capture 30-50% seulement).
        # Option 2 ACTIVE : ES=30, NQ=50, drawback=20 (sweet spot backtest +$437).
        # Option 1 OBSERVATION : ES=40, NQ=60, drawback=25 (logge sans action pour
        # comparer J+7 sur data live).
        trailing_threshold = TRAILING_TP_MFE_THRESHOLD_TICKS.get(symbol, 30)
        if pos.get("mfe", 0) >= trailing_threshold:
            if not pos.get("trailing_tp_armed", False):
                pos["trailing_tp_armed"] = True
                if _v2log:
                    try:
                        _v2log.emit("TRAILING_TP_ARMED", sym=symbol,
                                    mfe=round(pos["mfe"], 1),
                                    threshold=trailing_threshold)
                    except Exception:
                        pass
            drawback = pos["mfe"] - excursion
            if drawback >= TRAILING_TP_DRAWBACK_TICKS:
                captured_pct = round(100 * excursion / pos["mfe"], 1) if pos["mfe"] > 0 else 0
                if _v2log:
                    try:
                        _v2log.emit("TRAILING_TP_TRIGGERED", sym=symbol,
                                    mfe=round(pos["mfe"], 1),
                                    current=round(excursion, 1),
                                    drawback=round(drawback, 1),
                                    captured_pct=captured_pct)
                    except Exception:
                        pass
                self._close_trade(symbol, price, "TRAILING_TP")
                return

        # ─── OBSERVATION parallele Option 1 (40/60/25) — log only ──────────
        # But : comparer empiriquement Option 2 (active) vs Option 1 sur live data.
        # Permet a J+7 de mesurer combien de fois Option 1 aurait triggered
        # (avec quel pnl) vs Option 2. Decision finale calibration apres audit.
        obs_threshold = TRAILING_TP_OBS_MFE_THRESHOLD_TICKS.get(symbol, 40)
        if pos.get("mfe", 0) >= obs_threshold:
            obs_drawback = pos["mfe"] - excursion
            if obs_drawback >= TRAILING_TP_OBS_DRAWBACK_TICKS:
                if not pos.get("trailing_tp_obs_logged", False):
                    pos["trailing_tp_obs_logged"] = True  # 1 log par trade max
                    obs_captured = round(100 * excursion / pos["mfe"], 1) if pos["mfe"] > 0 else 0
                    if _v2log:
                        try:
                            _v2log.emit("TRAILING_TP_OBSERVED_VALIDATED", sym=symbol,
                                        mfe=round(pos["mfe"], 1),
                                        current=round(excursion, 1),
                                        drawback=round(obs_drawback, 1),
                                        captured_pct=obs_captured)
                        except Exception:
                            pass

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

        # Timeout — 11/05 Jackson "30 MN PARTOUT" Option A alignement Bot 1+2+3.
        # AVANT : 120 bars (2h). APRES : 30 bars (30 min) cohérent Bot 3 + literature
        # pro mean-reversion (Raschke/Brooks 5-15 bars max).
        # DESACTIVE en session Asia (faible volatilite, setups longs OK).
        try:
            from CORE import eco_calendar as _eco
            _is_asia = _eco.current_session_label() == "Asia"
        except Exception:
            _is_asia = False  # fail-safe : timeout 30 bars actif si import casse
        # 11/05 J3 REVERT defense (R2 agent backtest Bot 1 NOGO timeout=30).
        # Bot 2 V6 NOT backteste = revert prudent a 120 bars (origine) en attendant
        # R2b dedie. R2 verdict Bot 1 : timeout=30 -$386 / timeout=60 +$583 / timeout=120 baseline.
        # Bot 2 V6 archetype V6 brain enrichi = potentiellement different.
        timeout = (not _is_asia) and pos["bars_held"] >= 120

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

        # 🔴 FIX P0 v2 01/05/2026 (Jackson : "trade ES SHORT TP/SL DISPARUS = position naked")
        # Historique :
        #   B2 (code-reviewer 22/04) : "TRUST OCO BROKER" → mensonge logique car
        #     brackets cancellés = broker ne peut plus fill. Position naked.
        #   v1 (01/05 13:00) : send_market_order(sl=0, tp=0) → REJETÉ code-reviewer
        #     (OpenCloseTrade=1 = OPEN, pas CLOSE → reverse fantôme bug B2 reproduit).
        #   v2 (01/05) : pattern Bot 2 `_check_exit_dtc` (databento_paper_trader.py:1494) :
        #     1. request_position_blocking() poll broker via Type 305 (timeout 3s)
        #     2. Si broker_qty == 0 → skip close (déjà flat) + cleanup local
        #     3. Sinon → send_close_market (OpenCloseTrade=2 = CLOSE, pas OPEN)
        #     4. Cancel brackets (idempotent)
        # Anti reverse fantôme : send_close_market avec OpenCloseTrade=2 force le
        # broker à FERMER une position existante, jamais ouvrir.
        # Anti FLIP partial fill : request_position_blocking lit la qty broker réelle
        # (pas la qty bot mémoire qui peut diverger).
        if not from_dtc_callback and self.dtc is not None and pos.get("dtc_enabled"):
            try:
                contract = DTC_INSTRUMENTS[symbol].contract
                close_side = DTC_SELL if pos["direction"] == "LONG" else DTC_BUY
                bot_qty = pos.get("n_micros", 3)

                # Etape 1 : poll broker pour position réelle (anti FLIP)
                broker_qty = None
                try:
                    broker_qty = self.dtc.request_position_blocking(
                        symbol_contract=contract,
                        trade_account=self.trade_account,
                        timeout=3.0,
                    )
                except Exception as e:
                    print(f"  warn request_position {symbol}: {e}")

                # Etape 2 : décider de la suite selon broker_qty
                if broker_qty is not None and abs(broker_qty) == 0:
                    # Broker déjà flat (TP/SL fill arrivé avant simu) → skip close
                    # Sinon on créerait position fantôme (bug B2 reproduit).
                    print(f"  >>> DTC {outcome} {symbol} broker DEJA FLAT — skip close (anti-fantome)")
                    if _v2log:
                        try:
                            _v2log.emit("CLOSE_TRADE_ALREADY_FLAT",
                                        sym=symbol,
                                        outcome=outcome,
                                        bot_qty=bot_qty,
                                        broker_qty=broker_qty)
                        except Exception:
                            pass
                    # Cancel brackets quand même (idempotent, par sécurité)
                    for cid_key in ("tp_cid", "sl_cid"):
                        cid = pos.get(cid_key)
                        if cid:
                            try:
                                self.dtc.cancel_order(cid, trade_account=self.trade_account)
                            except Exception as e:
                                print(f"  warn cancel {cid}: {e}")
                else:
                    # broker_qty None (timeout) ou |qty| > 0 → fermer position
                    # Sequence anti-orphelin 8 etapes (Option B 04/05 — port Bot 2/3) :
                    #   3a. Cancel brackets (TP+SL) avec trade_account explicite (fix H6)
                    #   3b. Wait 1s propagation cancels
                    #   3c. send_close_market Type 208 OpenCloseTrade=2
                    #   3d. Wait 2s pour fill MARKET CLOSE
                    #   3e. Type 209 SUBMIT_FLATTEN_POSITION_ORDER par symbole (fallback)
                    #   3f. Verify qty_final = 0 via request_position_blocking
                    # PAS Type 210 (Sim3 multi-positions ES+NQ -> dangereux).
                    # Cf .claude/rules/orphan-prevention.md
                    actual_qty = abs(broker_qty) if broker_qty is not None else bot_qty
                    if broker_qty is None:
                        print(f"  >>> DTC {outcome} {symbol} request_position TIMEOUT → "
                              f"fallback bot_qty={bot_qty}")

                    # ETAPE 3a : Cancel brackets (TP + SL)
                    cancel_failed = []
                    for label, cid_key in (("tp", "tp_cid"), ("sl", "sl_cid")):
                        cid = pos.get(cid_key)
                        if not cid:
                            continue
                        try:
                            ok = self.dtc.cancel_order(cid, trade_account=self.trade_account)
                            if ok is False:
                                cancel_failed.append(label)
                        except Exception as e:
                            cancel_failed.append(label)
                            print(f"  warn cancel {cid}: {e}")
                    if cancel_failed and _v2log:
                        try:
                            _v2log.emit("BOT1_CLEANUP_CANCEL_FAIL",
                                        sym=symbol, failed=",".join(cancel_failed))
                        except Exception:
                            pass

                    # ETAPE 3b : wait 1s propagation cancels (anti race condition)
                    time.sleep(1.0)

                    # ETAPE 3c : send_close_market Type 208 OpenCloseTrade=2
                    try:
                        close_cid = self.dtc.send_close_market(
                            symbol=contract,
                            side=close_side,
                            quantity=actual_qty,
                            trade_account=self.trade_account,
                        )
                        print(f"  >>> DTC CLOSE {outcome} {symbol} qty={actual_qty} "
                              f"close_cid={close_cid} (broker_qty={broker_qty})")
                        if not close_cid and _v2log:
                            try:
                                _v2log.emit("ORDER_REJECT",
                                            sym=symbol,
                                            reason=f"close_market_{outcome.lower()}_fail")
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"  !!! DTC CLOSE {outcome} FAIL {symbol}: {e}")
                        if _v2log:
                            try:
                                _v2log.emit("ORDER_DTC_ERROR",
                                            sym=symbol,
                                            error=f"close_market_{outcome}_exc_{type(e).__name__}")
                            except Exception:
                                pass

                    # ETAPE 3d : wait 2s pour fill MARKET CLOSE
                    time.sleep(2.0)

                    # ETAPE 3e : Type 209 SUBMIT_FLATTEN_POSITION_ORDER (fallback)
                    # Defense en profondeur : si Trade Manager Sim desync DTC server,
                    # cleanup garanti par symbole. ClientOrderID OBLIGATOIRE (sinon SC
                    # rejette silencieusement, cf orphan-prevention.md decouvert 04/05).
                    try:
                        flush_cid = f"BOT1_FLUSH_{symbol[:2]}_{int(time.time()) % 100000}"
                        self.dtc._send({
                            "Type": 209,
                            "ClientOrderID": flush_cid,
                            "Symbol": contract,
                            "TradeAccount": self.trade_account,
                            "Exchange": "CME",
                            "IsAutomatedOrder": 1,
                        })
                        if _v2log:
                            try:
                                _v2log.emit("BOT1_CLEANUP_FLATTEN_SYM",
                                            sym=symbol, cid=flush_cid)
                            except Exception:
                                pass
                    except Exception as e:
                        if _v2log:
                            try:
                                _v2log.emit("BOT1_CLEANUP_FLATTEN_FAIL",
                                            sym=symbol, err=str(e)[:200])
                            except Exception:
                                pass

                    # ETAPE 3f : Verify qty_final = 0 (defense en profondeur ultime)
                    qty_final = None
                    try:
                        qty_final = self.dtc.request_position_blocking(
                            symbol_contract=contract,
                            trade_account=self.trade_account,
                            timeout=2.0,
                        )
                    except Exception as e:
                        print(f"  warn verify qty_final {symbol}: {e}")
                    if qty_final is None:
                        if _v2log:
                            try:
                                _v2log.emit("BOT1_CLEANUP_VERIFY_TIMEOUT", sym=symbol)
                            except Exception:
                                pass
                    elif abs(qty_final) == 0:
                        if _v2log:
                            try:
                                _v2log.emit("BOT1_CLEANUP_VERIFY_OK",
                                            sym=symbol, qty=qty_final)
                            except Exception:
                                pass
                    else:
                        # CRITIQUE : position residuelle malgre cleanup -> ORPHAN_RISK
                        print(f"  !!! ORPHAN RISK {symbol} qty_final={qty_final} (apres Type 209)")
                        if _v2log:
                            try:
                                _v2log.emit("BOT1_CLEANUP_VERIFY_FAIL",
                                            sym=symbol, qty=qty_final)
                            except Exception:
                                pass
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

        # FIX 29/04 (Jackson Action #1) : instrumenter sl_ticks/tp_ticks +
        # calculer slip_exit_ticks pour audit comparatif Bot 1 vs Bot 2.
        # Slippage convention : negatif = fill plus mauvais que prevu.
        sl_ticks_val = pos.get("sl_ticks", 0) or 0
        tp_ticks_val = pos.get("tp_ticks", 0) or 0
        sl_price_val = pos.get("sl_price")
        tp_price_val = pos.get("tp_price")
        slip_exit_calc = 0.0
        if outcome == "SL" and sl_ticks_val:
            # SL prevu = -sl_ticks. Slip = pnl_real - pnl_theo
            # pnl_real = pnl_ticks (negatif). pnl_theo = -sl_ticks.
            # Slip = pnl_ticks - (-sl_ticks) = pnl_ticks + sl_ticks
            slip_exit_calc = float(pnl_ticks + sl_ticks_val)
        elif outcome == "TP" and tp_ticks_val:
            # TP prevu = +tp_ticks. Slip = pnl_real - pnl_theo
            slip_exit_calc = float(pnl_ticks - tp_ticks_val)

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
            # v2 enrichissement SL/TP (FIX 29/04 : sl_ticks/tp_ticks ajoutes)
            "sl_ticks": sl_ticks_val,
            "tp_ticks": tp_ticks_val,
            "sl_price": sl_price_val,
            "tp_price": tp_price_val,
            "sl_wall": pos.get("sl_wall", ""),
            "sl_tier": pos.get("sl_tier", 0),
            "tp_wall": pos.get("tp_wall", ""),
            "rr_ratio": pos.get("rr_ratio", 0.0),
            "n_micros": n_mic,
            "signal_id": pos.get("signal_id"),
            # Snapshot V2 ML-ready : slippage + DTC link + expected vs realized
            # FIX 29/04 : slip_exit_ticks calcule depuis pnl vs sl/tp_ticks
            "slip_entry_ticks": pos.get("slip_entry_ticks", 0.0),
            "slip_exit_ticks": slip_exit_calc,
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
            # FIX code-reviewer R1 (04/05 soir) : persiste session_id pour
            # le _get_dynamic_wr conditionnel cellule (sym x dir x session).
            # Avant : session_id absent -> cellule fallback sur (sym x dir).
            # Source : pos["session_id"] capture au moment de l'entry depuis
            # bar_row_dict.get("session_id"). Fallback "" si absent.
            "session_id": pos.get("session_id", ""),
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
            # 04/05 SOIR FIX : ajout TRAILING_TP (LEVIER A) + KILL_SWITCH dans code_map.
            # Avant : outcome=TRAILING_TP -> fallback TRADE_CLOSE_MANUAL avec template
            # mismatch (attend `reason`, code passe `pnl/signal_id`) -> emit fail silent.
            code_map = {
                "TP":           "TRADE_CLOSE_TP",
                "SL":           "TRADE_CLOSE_SL",
                "TIMEOUT":      "TRADE_CLOSE_TIMEOUT",
                "TRAILING_TP":  "TRADE_CLOSE_TRAIL",   # 04/05 LEVIER A
                "KILL_SWITCH":  "TRADE_CLOSE_KILL",
            }
            code = code_map.get(outcome, "TRADE_CLOSE_MANUAL")
            kwargs = {"sym": symbol, "pnl": pnl_ticks, "signal_id": pos.get("signal_id")}
            if code == "TRADE_CLOSE_MANUAL":
                # Template attend `reason` + outcome non-mappe = trace pour audit
                kwargs["reason"] = outcome
            elif code == "TRADE_CLOSE_TIMEOUT":
                kwargs["bars"] = pos.get("bars_held", 0)
            _v2log.emit(code, **kwargs)

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
            # 🆕 04/05 LEVIER #2 : expose config circuit breaker pour dashboard.
            # Permet affichage "Config: 3 SL → 60 min" + compteur progressif consec_losses.
            "circuit_breaker_config": {
                "losses_threshold": ENTRY_RULES["circuit_breaker_losses"],
                "pause_min": ENTRY_RULES["circuit_breaker_pause_sec"] // 60,
                "active": ENTRY_RULES["circuit_breaker_losses"] < 9999,
            },
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
            # 04/05 Phase 1 OBSERVE-ONLY : compteurs cumulatifs widgets V4 du jour.
            # Audit J+7 (mardi prochain) : decision Phase 2 -> 3 (gate selectif).
            # Le verdict trading reste 100% conseil_global, SLTPEngine intact.
            "v4_widgets_observed": {
                "ES": dict(self._v4_obs_counts.get("ES", {})),
                "NQ": dict(self._v4_obs_counts.get("NQ", {})),
            },
            # 17/05 (Jackson "voyant flux source") : VISIBILITE source data Bot 2 V6.
            # bar_source possibles : "V4" (parquet enriched fresh), "DMP_BOT" (DMP via
            # last_bars dashboard), "DMP_JSONL" (DMP via JSONL live fallback), "INIT"
            # (jamais evalue). Avant ce voyant : on a perdu 5 jours sans le savoir
            # (V4 stale -> fallback DMP 100% du temps depuis le 11/05).
            # Le frontend affiche voyant vert (V4) / orange (DMP) / gris (INIT).
            "bar_source": {
                "global": self._latest_v6_bar_source,
                "per_symbol": dict(self._latest_v6_bar_source_per_sym),
                "ts_per_symbol": {
                    sym: ts for sym, ts in self._latest_v6_bar_source_ts_per_sym.items()
                },
            },
        }

        # Fix WinError 5 (race lock state.json 04/05) : retry avec backoff
        # exponentiel. Cause : MIA-Dashboard lit state.json en parallele -> handle
        # Windows ouvert -> os.replace echoue ~1.5x/h. Retry court masque la race.
        tmp = STATE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            if _v2log:
                _v2log.emit("GENERIC_MAJEUR", msg=f"write_state tmp failed: {e}")
            return
        last_err = None
        for attempt in range(3):
            try:
                os.replace(tmp, STATE_FILE)
                last_err = None
                break
            except PermissionError as e:
                last_err = e
                if attempt < 2:
                    time.sleep(0.05 * (2 ** attempt))  # 50ms, 100ms
            except Exception as e:
                last_err = e
                break
        if last_err is not None and _v2log:
            _v2log.emit("GENERIC_MAJEUR",
                        msg=f"write_state replace failed after 3 retries: {last_err}")

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
        # FIX URGENT 06/05 (Jackson "TROP DE REDEMARAGE") : track last_heartbeat
        # pour emit BOT_HEARTBEAT toutes 30s (watchdog mia_watchdog.py).
        last_heartbeat = 0

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

                # FIX URGENT 06/05 (Jackson "TROP DE REDEMARAGE") : emit BOT_HEARTBEAT
                # toutes 30s. Sans ca, mia_watchdog ne trouve pas l'event dans
                # events_*_paper_v6.jsonl -> SOURCE_CRIT -> restart cyclique
                # 15-25 min (34 restarts/jour observe).
                hb_now = time.time()
                if hb_now - last_heartbeat > 30:
                    try:
                        last_bar_age = self._compute_last_bar_age_for_heartbeat(data)
                    except Exception:
                        last_bar_age = 0.0
                    if _v2log:
                        _v2log.emit("BOT_HEARTBEAT", last_bar_age=last_bar_age, bot="bot2_v6_brain")
                    last_heartbeat = hb_now

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
    files = sorted(g.glob(os.path.join(DATA_DIR, "*_v6_trades.jsonl")))
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
