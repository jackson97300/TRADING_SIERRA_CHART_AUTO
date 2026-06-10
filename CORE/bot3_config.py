"""Bot 3 — Configuration centrale.

Garde-fous, risk management, DTC Sim1, et flags de phase.
Toute constante magique vit ici (cf regle V2CLEAN config centralise).
"""
from __future__ import annotations

# ════════════════════════════════════════════════════════════════════════
# Phase de deploiement
# ════════════════════════════════════════════════════════════════════════
# Phase 1 : OBSERVE-ONLY — detect contacts + log decisions, NE TRADE PAS
# Phase 2 : PAPER Tier 1 only
# Phase 3 : PAPER full (Tier 1 + 2 + 3)
# Jackson 03/05 soir : compte Sim1 demo, pas de risque → PAPER DIRECT
BOT3_OBSERVE_ONLY = False           # PAPER ACTIF (trade Sim1)
BOT3_ENABLE_TIER2 = True            # tier 2 actif (CUR_VPOC, GEX_DN, etc.)
BOT3_ENABLE_TIER3 = True            # tier 3 actif (required_context strict)
BOT3_ENABLE_TIER2_NEUTRAL = True    # 8 niveaux NEUTRAL via 7 scenarios

# 04/06/2026 (Jackson) — Blacklist levels backtest-validated.
# Audit 33j Bot 3 MP : 2 niveaux genemnt 100% pertes dans pires jours catastrophe :
#   - MQ_HVL : 9 trades 33j, WR 11.1%, PnL -$4500
#   - MQ_CALL_POC_FLAT : 5 trades 33j, WR 0.0%, PnL -$5784
# Cumul -$10,285 sur 14 trades (11% trades MP). Walk-forward MAI ET JUIN positifs
# apres blacklist (anti-overfitting OK). Edge concept : HVL = niveau consolidation
# (mauvais pour dip strategy), POC_FLAT = pas de structure (pas d'edge).
# Cf BOT_CHANGELOG 04/06/2026 entry blacklist + memory feedback audit_jackson.
BOT3_MP_LEVEL_BLACKLIST_ENABLED = True   # rollback rapide via flag

# Phase 1 : ACCEPTANCE + REJECTION (Jackson 03/05 — ADN conserve)
# Note : market-analyst (review 03/05) recommande False par defaut sur risque
# Wyckoff spring (Steidlmayer canon : acceptance multi-barres, pas reversal 1-bar).
# Decision Jackson : garder True. Phase 1 OBSERVE-only collecte les inversions reelles
# pour audit J+30. Si PF inversions live < 1.0 → reconsiderer.
BOT3_TRADE_REJECTIONS = True
BOT3_TRADE_BREAKOUTS = True

# ════════════════════════════════════════════════════════════════════════
# PHASE 4 Bot 3 v2 Narrative Layer - flags (Jackson 18/05)
# ════════════════════════════════════════════════════════════════════════
# Master plan : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md sect 187-191
# Kill switch principal : `BOT3_USE_NARRATIVE_DIRECTION`.
# - False = legacy Bot 3 v1 hardcoded `side` au level (comportement actuel)
# - True  = Bot 3 v2 DirectionResolver consume `narrative_direction` (post Phase 4d
#           backtest comparatif GO + Phase 5 DSR Lopez GO)
#
# Default False (kill switch) tant que Phase 4d + Phase 5 pas validees paper.
# Activation manuelle uniquement apres review Tier 1 + GO Jackson.
# ACTIVE 2026-05-19 02:30 (Jackson GO explicite) en mode SHADOW J+14 :
#   USE_NARRATIVE=True + TRACKING_ONLY=True -> NSM transit + DirectionResolver
#   register pendings + emit BOT3_V2_SHADOW_SIGNAL pour audit. V1 reste decideur.
#   Cf BOT_CHANGELOG entry 2026-05-19 02:30 Phase 4d MVP.
BOT3_USE_NARRATIVE_DIRECTION: bool = True

# Tracking-only Phase 1-3 : NSM + StoryTrackers + PlotTwist + Validator +
# DirectionResolver consument data MAIS ne MODIFIENT PAS le comportement legacy.
# Resolver fire decisions parallele logged en shadow JSONL pour audit Phase 4-5.
# Apres J+14 audit shadow signals -> flip False = V2 decideur (apres GO Jackson).
BOT3_NARRATIVE_TRACKING_ONLY: bool = True

# Bug 3 fix market-analyst : flag separe pour MIRROR_SHORT_OBSERVE levels.
# Default False = pas consume meme si BOT3_USE_NARRATIVE_DIRECTION=True.
# Active uniquement apres Phase 5 walk-forward DSR Lopez N>=100 sur 6 mois data.
# Permet test A/B isolement statistique : narrative SANS mirror vs AVEC mirror.
BOT3_ENABLE_MIRROR_SHORT_OBSERVE: bool = False

# Buffer sizes Phase 4 (limites mémoire prod multi-symbol).
# Si > N pending entries actives, log warning (potential pending leak).
BOT3_NARRATIVE_MAX_PENDING_ENTRIES: int = 50
BOT3_NARRATIVE_MAX_SHADOW_LOG_SIZE_MB: int = 100  # rotation JSONL

# ════════════════════════════════════════════════════════════════════════
# Connexion DTC Bot 3 — Sim1 isole via TradeAccount (Jackson 03/05 DEFINITIF)
# ════════════════════════════════════════════════════════════════════════
# Mapping bots : Bot 1 = Sim3, Bot 2 = Sim2, Bot 3 = Sim1.
# Sierra Chart ecoute UN seul port DTC (11099). Le routage vers les comptes
# Sim1/Sim2/Sim3 se fait via le champ TradeAccount dans CHAQUE ordre.
# Donc Bot 3 partage le DTC connector avec Bot 2 (meme port) MAIS envoie
# ses ordres avec TRADE_ACCOUNT_BOT3 = "Sim1" → routage natif SC.
TRADE_ACCOUNT_BOT3 = "Sim1"         # routage compte Sim1 isole

# ════════════════════════════════════════════════════════════════════════
# Drift reject (12/05 FIX entry_price race condition)
# ════════════════════════════════════════════════════════════════════════
# Si drift signal_price <-> live_ref > MAX_DRIFT_TICKS au moment du trade,
# le bot REFUSE le signal (skip + emit BOT_DRIFT_REJECT) au lieu de fill
# au prix actuel (qui creerait un trade au mauvais prix vs signal calcule).
#
# Calibration empirique (review market-analyst 12/05 sur 83 events LIVE_REF_USED) :
#   - NQ : median drift=47t, p75=72t, p90=173t. Seuil initial 20t aurait bloque
#          77.4% des trades = kill-switch deguise. Corrige a 60t (p75) = bloque
#          ~32% (acceptable, retire les chase post-breakout >75% SL).
#   - ES : median=7t, p75=10t, p90=23t. Seuil initial 8t aurait bloque 30.8%.
#          Corrige a 16t (p75 x 1.6) = bloque ~19% (acceptable).
#   - MGC : pas de data Bot 3 MGC encore. Garde 30t par defaut, recalibrer
#          apres 20 trades Bot 3 MGC.
#
# Justification :
#   - Au-dela du seuil, le setup MenthorQ Tier1 est "casse" (zone influence
#     ~10-15t depasse). Trader = chase, pas le setup.
#   - SL initial calcule sur signal_price devient incoherent (drift > 50% SL).
#   - Compte eval prop firm rejette si entry rapporte ≠ entry broker reel.
#
# DETTE TECH : ce gate est un patch sur cause racine (V4 enriched stale 18min).
# A retirer une fois pipeline incremental deploye (cf project_pipeline_incremental_backlog).
MAX_DRIFT_TICKS: dict[str, int] = {
    "NQ": 60,    # p75 corrige (~$120/micro, ~75% SL typique 80t)
    "ES": 16,    # p75 x 1.6 corrige (~$40/micro, ~50% SL typique 32t)
    "MGC": 30,   # default, recalibrer apres 20 trades empiriques
}

# ════════════════════════════════════════════════════════════════════════
# Garde-fous execution
# ════════════════════════════════════════════════════════════════════════
GUARD_RAILS_BOT3: dict[str, dict] = {
    "NQ": {
        # 03/06 ROLLBACK migration MNQM26 (pas configure dans Sierra Chart).
        # Option A pure : 1 NQ E-mini + 1 ES E-mini broker + dashboard cohérent.
        # Si NQ trop volatile -> resserrer SL ticks, pas changer sizing.
        "n_contracts": 3,                # 3 MNQM26-CME Micro NQ (Couche 2 Jackson 09/06)
        # 04/05 SOIR ROUND 1 (Jackson + agent code-reviewer) : recalibration TP/SL
        # Empirique 29 trades aujourd'hui = 100% TIMEOUT pnl=0t car SL=200t/TP=300t
        # inatteignables en 60min. MFE peak observe 121t < TP 300t.
        # Cible : SL 80t (20 pts) clamp 0.7-1.5x ATR = 56-120t, TP 120t (RR 1.5).
        "sl_ticks_base": 80,             # 20 pts (etait 200t = 50 pts trop large)
        "trailing_activation": 48,       # +12 pts NQ (etait 120 = 30 pts)
        "trailing_distance": 32,         # trail a 8 pts (etait 80 = 20 pts)
        # 08/05 Jackson directive "30 MN PARTOUT" apres incident 75% TIMEOUT le 08/05
        # (3/4 trades timeout 60min sur ES). Aligne literature pro Raschke/Brooks/Sperandeo
        # mean-reversion rejection : 5-15 bars max, jamais 60 bars. Bot 3 archetype mean
        # reversion (vs Bot 1 trend-following 2h timeout legitime).
        "timeout_minutes": 30,
        "tp_cap_ticks": 160,             # cap securite 40 pts (RR max 2)
        # 09/05 Jackson "ET SI ON REDUIT LEGEREMENT LE TP" + backtest TP RR sweep
        # Sample 25 trades 06-08/05 : RR=1.0 +$120 / RR=1.2 +$72 / RR=1.5 baseline.
        # Decision : RR=1.2 = compromis pragmatique (TP plus atteignable Asia/London,
        # RR conservateur). 1 ligne reversible si NOGO J+7. SL INCHANGE (sl_ticks_base=80).
        # Cas observes : trade #3 ES MFE 35t TIMEOUT, #4 ES MFE 40t TIMEOUT
        # auraient ete TP avec RR<=1.2 (TP=38t). Reduit faux TIMEOUT.
        "tp_rr_ratio": 1.2,              # TP = sl_ticks * 1.2 = 96t (24 pts) - etait 1.5 (120t)
        # 03/06 ROLLBACK : E-mini NQM26 $5.00/tick PER CONTRACT (1 contrat).
        # compute_pnl_R_usd multiplie par n_contracts=1 -> $5.00/tick total.
        "tick_value": 0.50,              # Micro MNQM26 $0.50/tick (Couche 2 09/06)
        "tick_size": 0.25,
        # 10/06 RECALIBRATION JACKSON (Option 1 conservateur + SHADOW 24h puis ACTION).
        # Empirique 12 wins NQ (4-10 juin) : MFE p25=36t, p50=53t, p75=81t, max=113t.
        # Paliers anciens (100/150/200) JAMAIS atteints → ladder inopérant. Recalibrage :
        # - Palier 1 = TP cible (30t = RR 1.2 × 25t SL) → si retrace post-TP, lock +$7.50
        # - Palier 2 = p50 winners (50t) → lock 1R favorable = +$22.50
        # - Palier 3 = p75 winners (80t) → lock 1.4R favorable = +$52.50
        # NQ tick_value $0.50 micro × 3 micros = $1.50/tick total.
        # Trailing BE/Active aussi recalibre vers MFE empirique réel.
        # Mode initial : SHADOW (MIA_BOT3_LADDER_MODE=OBSERVE) audit 24h, puis ACTION.
        "trailing_be_trigger_ticks": 30,        # MFE >= 30t (TP cible) → SL hypothetique = entry (BE)
        "trailing_active_trigger_ticks": 50,    # MFE >= 50t (p50 winners) → trailing actif
        "trailing_distance_ticks": 20,          # SL trailing = MFE_price - 20t (cap perte vs MFE)
        "ladder_paliers": [
            (30.0, 5.0),    # palier 1 : MFE +30t (TP cible) → SL +5t (lock $7.50)
            (50.0, 15.0),   # palier 2 : MFE +50t (p50)     → SL +15t (lock $22.50)
            (80.0, 35.0),   # palier 3 : MFE +80t (p75)     → SL +35t (lock $52.50)
        ],
    },
    "ES": {
        # 28/05 DIRECTIVE Jackson : 1 contrat ES standard en COLLECTE Sim1
        # (au lieu de 3 contrats avec tick_value MES). Le mapping symbole reste
        # "ES" -> "ESM26-CME" (E-mini standard) cf databento_paper_trader_v2.py:212.
        # tick_value passe de 1.25 (MES) a 12.50 (ES standard, $50/pt -> $12.50/tick).
        # n_contracts 3 -> 1 : reduction 3x du nb contrats. Combine au tick_value
        # corrige : USD/tick reel = 1 x 12.50 = $12.50 (avant 3 x 1.25 = $3.75 bot
        # pensait, mais broker exec 3 x 12.50 = $37.50 reel = sur-sizing 10x). Nouveau
        # = bot pense $12.50, broker exec $12.50 = aligned.
        "n_contracts": 3,                # 3 MESM26 Micro ES (Couche 2 Jackson 09/06)
        # 02/06 OPTION B Jackson "STRICT $150 USD partout, RR 1:1" :
        # Analyse empirique 147 trades ES (PF 1.04, WR 48.2%, TIMEOUT 67%) :
        # - MFE p75 winners = 15t, p90 = 25t
        # - MAE p90 losers = 17.5t (= $219 USD, jamais touche SL 32t)
        # - Old SL=32t ($400) sur-dimensionne (loser typique sort par TIMEOUT a -11t)
        # Setup symetrique propre :
        # - SL_base = 12t = $150 USD (= cap perte par trade)
        # - TP_cap = 12t = $150 USD (= cap gain par trade)
        # - RR 1:1 = coherent avec edge marginal (PF~1)
        # - Timeout 30min = revert baseline pre-02/06 matin
        # Trailing BE (32t) + Trailing actif (48t) + Ladder (40/60/80t) restent
        # configures mais effectif DESACTIVE car triggers > TP cap (jamais atteint).
        # A nettoyer en J+7 review apres observation.
        "sl_ticks_base": 12,             # 32 -> 12 ($150 USD strict Jackson 02/06)
        "trailing_activation": 20,       # legacy
        "trailing_distance": 12,         # legacy
        "timeout_minutes": 30,           # 60 -> 30 (revert baseline)
        "tp_cap_ticks": 12,              # 150 -> 12 ($150 USD pour 1 ES std)
        "tp_rr_ratio": 1.0,              # 1.5 -> 1.0 (RR symetrique 1:1)
        "tick_value": 1.25,              # Micro MESM26 $1.25/tick (Couche 2 09/06)
        "tick_size": 0.25,
        # 07/05 PHASE 1 OBSERVATION trailing + BE (calibrage symetrique NQ).
        # ES MFE peak observe 06/05 : 35-40t/contract → 1R 32t deja au seuil profit.
        # BE @ 1R (32t) — trailing actif @ 1.5R (48t) — distance 0.5R (16t).
        "trailing_be_trigger_ticks": 32,        # MFE >= 32t → BE
        "trailing_active_trigger_ticks": 48,    # MFE >= 48t → trailing
        "trailing_distance_ticks": 16,          # SL trailing = MFE_price - 16t
        # 11/05 LADDER PROFIT-LOCKING (Solution D2 Jackson directive).
        # 28/05 RECALCUL POST-FIX : ES standard $12.50/tick × 1 contrat = $12.50/tick total.
        # Palier 1 MFE 40t = $500 peak  -> lock $200 (SL +16t).
        # Palier 2 MFE 60t = $750 peak  -> lock $375 (SL +30t).
        # Palier 3 MFE 80t = $1000 peak -> lock $625 (SL +50t).
        # Niveaux de ticks ladder INCHANGES (la logique de tick reste valide,
        # seul le mapping ticks->USD bouge avec le tick_value corrige).
        "ladder_paliers": [
            (40.0, 16.0),    # palier 1 : MFE +40t (=$500) -> SL +16t (lock $200)
            (60.0, 30.0),    # palier 2 : MFE +60t (=$750) -> SL +30t (lock $375)
            (80.0, 50.0),    # palier 3 : MFE +80t (=$1000) -> SL +50t (lock $625)
        ],
    },
    # ────────────────────────────────────────────────────────────────────
    # MGC (Micro Gold COMEX) — ajoute 12/05/2026 Bot 3 Gold integration
    # ────────────────────────────────────────────────────────────────────
    # Specs : tick=0.10, $1/tick × 3 micros = $3/tick total.
    # ATR median 17 ticks/bar (~1.7 pts Gold). SL 200t = 20 pts = $600 (3 MGC).
    # Source : DOCS/PROMPT_CLAUDE_CODE_BOT3_GOLD.md + bot3_gold_config.py.
    # Phase 1 OBSERVE-ONLY → ces valeurs ne servent qu'a logger would_GO,
    # pas d'execution DTC. Phase 2+ : recalibrer apres 20 trades empiriques.
    "MGC": {
        "n_contracts": 3,                       # 3 MGC = $3/tick
        "sl_ticks_base": 200,                   # 20 pts Gold (= $600 risque 3 MGC)
        "trailing_activation": 80,              # +8 pts pour armer trailing
        "trailing_distance": 50,                # trail a 5 pts du best
        "timeout_minutes": 60,                  # Gold = mouvements plus lents que ES/NQ
        "tp_cap_ticks": 400,                    # cap 40 pts Gold (RR max 2)
        "tp_rr_ratio": 2.0,                     # R:R 2.0 (recalibrer apres data)
        "tick_value": 1.00,                     # $1/tick MGC
        "tick_size": 0.10,                      # tick Gold
        # Trailing + BE (alignes spec PROMPT Gold)
        "trailing_be_trigger_ticks": 200,       # MFE >= 1R (200t) → BE
        "trailing_active_trigger_ticks": 300,   # MFE >= 1.5R → trailing actif
        "trailing_distance_ticks": 100,         # SL trailing = MFE_price - 100t (0.5R)
        # Ladder profit-locking (calibre conservateur Phase 1, ajuster apres data)
        "ladder_paliers": [
            (250.0, 100.0),  # palier 1 : MFE +25 pts → lock +10 pts ($30)
            (350.0, 200.0),  # palier 2 : MFE +35 pts → lock +20 pts ($60)
            (450.0, 300.0),  # palier 3 : MFE +45 pts → lock +30 pts ($90)
        ],
    },
}

# ════════════════════════════════════════════════════════════════════════
# Ladder safety params (FIX 19/05 incident #10 fix 4 — race condition T+1s)
# ════════════════════════════════════════════════════════════════════════
# Avant ce fix : palier 1 declenchait en 1 seconde apres fill bracket initial
# (8:39:53 fill → 8:39:54 BOT3_LADDER_SL_MODIFIED). ServerOrderID ancien SL
# pas encore propage de _recv_loop → cancel Type 203 ignore silencieusement
# (cf cancel_order require_sid=True qui maintenant return False dans ce cas).
# Solution : refuser tout palier ladder tant que age trade < LADDER_MIN_AGE_SECONDS.
# Permet propagation Server IDs des brackets initiaux avant tout modify.
LADDER_MIN_AGE_SECONDS = 10


# ════════════════════════════════════════════════════════════════════════
# PROTECTION SL HARDCAP USD (10/06/2026 Jackson directive — anti slip catastrophe)
# ════════════════════════════════════════════════════════════════════════
# Cap dur sur le risk maximum par trade en USD VIRTUEL MICRO (Python compute).
# Si le SL calculé dépasse ce seuil, le trade est VETO (rejeté sans envoi DTC)
# avec emit BOT3_SL_RISK_VETO. Couche complémentaire au BOT3_VOL_VETO_HIGH_ATR
# (FIX #54 09/06) et BOT3_SL_MIN_ATR_EXTENDED (FIX #55 09/06).
#
# Calcul : sl_risk_usd = sl_ticks * GR[sym]["tick_value"] * GR[sym]["n_contracts"]
#
# Configurations actuelles (USD virtuel micro Python) :
#   - NQ : 25t × $0.50 × 3 = $37.50 (sous cap, OK)
#   - ES : 12t × $1.25 × 3 = $45.00 (sous cap, OK)
#   - MGC : 200t × $1.00 × 3 = $600.00 (CAP HIT → VETO automatique, à recalibrer si MGC actif)
#
# ⚠️ DECOUPLING avec SC (cf SYMBOL_TO_CONTRACT bot3_paper_common.py) :
# SC exécute E-mini réel ($5/$12.50/tick), Python calcule en micro virtuel.
# Le cap $50 USD est en VIRTUAL micro Python. Risk SC réel = x10 (= $500 max
# en E-mini SC). Acceptable en paper unlimited, à revoir avant Live AMP.
#
# Trigger : auto-reprice slip étend SL → si nouveau SL_USD > $50, veto.
# Aucune modif du calcul SL/TP existant (anti-régression).
MAX_SL_RISK_USD_BOT3 = 50.0


# ════════════════════════════════════════════════════════════════════════
# Risk management — INDEPENDANTS par instrument
# ════════════════════════════════════════════════════════════════════════
# Jackson 03/05 soir round 5 : cap data quality (pas risque PnL).
# Reviews market-analyst : "sans cap, trades correlees → variance PF enorme +
# biais haussier sur strats asymetriques wins/losses → audit J+30 inexploitable
# (PF 1.45 sur 250 trades = en realite PF 1.15 +- 0.3 = nul statistique)".
# Recommandation Lopez : 20 trades/jour + 10 losses/jour pour qualite OOS.
RISK_BOT3: dict[str, dict] = {
    "NQ": {
        # 03/05 soir Jackson : "ALIGNE LE BOT 3 AU BOT 2 POUR CES PARAMETRES" —
        # alignement Phase 1 free-run (PHASE_1_FREE_RUN=True dans setup_engine.py).
        # Bot 2 RISK_PER_SYMBOL : max_losses=None, kill_switch=None.
        # Bot 3 idem : suppression cap data quality (was 20/10) pour Phase 1 paper.
        # En LIVE capital reel : reactiver cap (recommandation Lopez 20 trades/jour).
        "max_trades_per_day": None,         # PAS de limite (aligne Bot 2)
        "max_losses_per_day": None,         # PAS de limite (aligne Bot 2)
        "kill_switch_daily_pnl": None,      # PnL illimite (Sim1 demo)
        # 02/06 FINALE "TOUT EN MINI" : alignement avec GUARD_RAILS_BOT3 NQ
        # n_contracts=1 (1 E-mini NQM26 standard).
        "position_size": 1,                 # 1 E-mini NQM26 standard
    },
    "ES": {
        "max_trades_per_day": None,         # PAS de limite (aligne Bot 2)
        "max_losses_per_day": None,         # PAS de limite (aligne Bot 2)
        "kill_switch_daily_pnl": None,
        # 28/05 FIX RESERVE #2 review : idem NQ, dead code aligne sur GUARD_RAILS=1.
        "position_size": 1,
    },
    # MGC ajoute 12/05/2026 Bot 3 Gold integration.
    # Phase 1 OBSERVE-ONLY : caps actifs (data quality), aligne sur Gold spec
    # PROMPT (max 3 trades/jour, max 2 losses, kill switch -$600 = 2 × $300).
    # Phase 2+ : aligner sur ES/NQ (PHASE_1_FREE_RUN=True = None) si paper GO.
    "MGC": {
        "max_trades_per_day": 3,            # cap data quality Phase 1
        "max_losses_per_day": 2,            # circuit breaker
        "kill_switch_daily_pnl": -600.0,    # 2 × $300 max loss/jour Gold
        "position_size": 3,
    },
}

# 07/05/2026 Jackson directive "ANALYSE LE COOLDOWN DES AUTRES BOT ET APLIQUE LE MEME"
# Suite incident : 2 SL consecutifs en 4 min (17:15 et 17:19 UTC) avec MAE/pnl
# incoherents (-105t/-298t et -45t/-298t). Pas de cooldown ni circuit breaker
# = re-entry immediate apres SL = compounding pertes.
#
# Alignement Bot 1 (mia_paper_trader.py:121-123) + Bot 2 (databento_paper_trader.py:134-141)
# - cooldown 15 min post-close anti re-entry contre-sens
# - circuit breaker 3 SL consec → pause 60 min
COOLDOWN_BOT3_MIN = 15                  # 15 min anti re-entry contre-sens (post-close)
MAX_CONSECUTIVE_SL_BOT3 = 3             # 3 SL consec → circuit breaker
PAUSE_AFTER_BREAKER_BOT3_MIN = 60       # pause 60 min apres breaker triggered

# ════════════════════════════════════════════════════════════════════════
# ATR baselines pour SL adaptatif
# ════════════════════════════════════════════════════════════════════════
ATR_BASELINE = {"NQ": 0.033, "ES": 0.027, "MGC": 0.035}  # atr_14m_pct mediane (MGC = spec Gold prompt)
ATR_MULTIPLIER_CLAMP = (0.7, 1.5)              # clamp ratio atr_current / baseline

# ════════════════════════════════════════════════════════════════════════
# Vetos absolus
# ════════════════════════════════════════════════════════════════════════
VETO_RVOL_MIN = 0.3                  # rvol < 0.3 = volume mort
VETO_NEWS_BUFFER_MIN = 5             # bloquer 5min avant + 3min apres news macro
VETO_NEWS_AFTER_MIN = 3
VETO_ROLL_DAY = True                 # is_roll_day == 1 = bloque

# ════════════════════════════════════════════════════════════════════════
# Trading window (UTC) — heritee Bot 2
# ════════════════════════════════════════════════════════════════════════
TRADING_WINDOW_START_UTC = 2         # 02h UTC = 04h FR
TRADING_WINDOW_END_UTC = 21          # 21h UTC = 23h FR

# ════════════════════════════════════════════════════════════════════════
# Logging
# ════════════════════════════════════════════════════════════════════════
LOG_CATEGORY_BOT3 = "bot3"           # nouvelle categorie LOGS/bot3/
SNAPSHOT_BAR_BY_BAR = True           # capture chaque barre durant le trade
SNAPSHOT_MAX_BARS = 30               # cap (= timeout_minutes 30 min Jackson 08/05)

# ════════════════════════════════════════════════════════════════════════
# BREAKOUT_RETEST state machine (Steidlmayer/Dalton, Option B Jackson 03/05)
# ════════════════════════════════════════════════════════════════════════
# FIX #6 (review code-reviewer 03/05) : centralisation config (regle V2CLEAN
# config-centralise 17/04). Anciennes constantes au top de bot3_breakout_retest.py
# importees depuis ici.
#
# FIX #9 (review market-analyst 03/05) : ajustement TPO scaling.
# Steidlmayer "2-3 TPO" = 60-90 min en barres 1-min. Compromis pratique :
# 5 barres acceptance (assez pour eviter bruit micro-3min), 30 barres deadline retest
# (1-2 TPO). Plus que 3/10 mais moins que canon strict 30/60.
BREAKOUT_N_ACCEPTANCE_BARS = 5                    # bars apres touch pour acceptance
BREAKOUT_N_ACCEPTANCE_CONFIRMS_REQUIRED = 3       # >=3/5 (60%) pour ACCEPTED
BREAKOUT_RETEST_DEADLINE_BARS = 30                # max bars apres ACCEPTED pour retest
BREAKOUT_RETEST_PROXIMITY_MULTIPLIER = 1.5        # retest si dist <= 1.5*proximity
# FIX #2 (review market-analyst 03/05) : magnitudes delta/finish au retest
# normalisees via rvol pour adapter Asia/RTH/Open. Seuils en BASELINE rvol=1.0.
BREAKOUT_RETEST_DELTA_BASE = 30.0                 # delta abs min (rvol=1) → multiplie par max(rvol, 0.5)
BREAKOUT_RETEST_FINISH_BASE = 15.0                # finish abs min (rvol=1) → idem
# FIX #10 (review market-analyst 03/05) : TPO printed (close OU wick) hybride.
# Si close du cote casse → 1.0 confirm. Si wick > BREAKOUT_WICK_ATR_RATIO * atr → 0.5 confirm.
BREAKOUT_WICK_ATR_RATIO = 0.20                    # wick acceptance fraction d'ATR
BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD = 2.5      # somme confirms (close=1.0, wick=0.5) sur 5 bars
# FIX #8 (review code-reviewer 03/05) : cooldown post-cancel anti signal-noise.
# Apres CRUSH_ABSORBED ou RETEST_TIMEOUT, on attend N bars avant re-register.
BREAKOUT_COOLDOWN_AFTER_CANCEL_BARS = 10
# FIX #7 (review code-reviewer 03/05) : confidence breakout_retest plage calculee.
# Plus utilise hardcode 70.
BREAKOUT_CONFIDENCE_BASELINE = 60                 # base avant boosts

# ════════════════════════════════════════════════════════════════════════
# NEUTRAL levels — 7 scenarios decision (Jackson 03/05 Option B+)
# ════════════════════════════════════════════════════════════════════════
# Structure (poc_dir, poc_speed, va_dev) + Orderflow renforce (delta_pct,
# finish, rvol, absorb_at_level, big_traders, liq_sweep, vol_z, cvd_div,
# color_imbalance) convergent pour determiner BREAKOUT / REJECTION / SKIP.
#
# Tier 1 features (delta_pct + absorb + big_traders) = anti spring Wyckoff
# + anti faux breakout retail. Tier 2 (liq_sweep + vol_z + cvd_div) =
# qualite signal supplementaire.
NEUTRAL_DELTA_PCT_THRESHOLD = 0.20                # delta_pct (delta/total_vol) min |0.20| = 20% pression
NEUTRAL_FINISH_THRESHOLD = 10.0                   # finish absolu min
# Scenario 3 + 4 : structure faible si abs(poc_speed) < seuil
NEUTRAL_POC_SPEED_WEAK = 0.05
# Scenario 5 : range day si va_dev sous seuil contract
NEUTRAL_VA_CONTRACT_THRESHOLD = -0.5
# Scenario 6 : trend day si poc_speed fort + va_dev expand
NEUTRAL_POC_SPEED_STRONG = 0.05
NEUTRAL_VA_EXPAND_THRESHOLD = 1.0
# Tier 2 : breakout doit etre confirme par volume vivant
NEUTRAL_VOL_ZSCORE_BREAKOUT_MIN = 1.0             # vol_zscore_20 min pour scenarios BREAKOUT
# Color imbalance : > 0 buyers dominent zone, < 0 sellers dominent
# Scenario LONG breakout veut color_imbalance >= 0, SHORT veut <= 0 (pas neutralite forte contre)
NEUTRAL_COLOR_IMBALANCE_BLOCK_MIN = 2             # |imbalance| >= 2 = signal strong directionnel

# ════════════════════════════════════════════════════════════════════════
# TIER S features (Jackson 03/05 audit V4 — calibration empirique)
# ════════════════════════════════════════════════════════════════════════
# IMPORTANT (review market-analyst round 4) : tous les seuils ci-dessous sont
# # heuristic_calibrated_NQ. Calibrage empirique sur parquet V4 NQ uniquement.
# Seuils ES potentiellement differents (TODO calibration ES separee Phase 2).
# Audit J+30 obligatoire avec bootstrap CI avant Phase 2 paper actif.
# Cf data-quality.md regle souveraine + feedback_backtest_before_gate.md (17/04).
#
# Bar structure (Steidlmayer TPO + hammer/shooting heuristique 1-bar Nison)
NEUTRAL_HAMMER_LOWER_WICK_MIN = 0.50      # heuristic — pas de bootstrap CI
NEUTRAL_SHOOTING_STAR_UPPER_WICK_MIN = 0.50
NEUTRAL_BAR_BODY_STRONG = 0.60            # heuristic_calibrated — Dalton "strong bar" qualitatif
# Volume profile structure (calibrage empirique NQ V4 03/05)
# NQ p25=690 / p50=1116 / p75=1742 / p90=2465 sur 29614 bars 03/2026.
# Seuils initiaux 25/12 (PROMPT initial) etaient triviaux (toujours True).
NEUTRAL_VA_BUCKETS_RANGE = 1742           # heuristic_calibrated_NQ p75 (profile large)
NEUTRAL_VA_BUCKETS_TREND = 690            # heuristic_calibrated_NQ p25 (profile narrow)
# Wyckoff effort/result : pic delta intra-bar (extraits pour audit Phase 1,
# PAS branches en filtre — Pattern 11 V1 evite, cf review round 4)
NEUTRAL_DELTA_PEAK_RATIO_ABSORB = 2.0     # NON UTILISE actuellement
# Spike confirmation BREAKOUT
NEUTRAL_SPIKE_LAG_BLOCK = True             # spike_detected_lag3=1 → veto retest pollue


# ════════════════════════════════════════════════════════════════════════
# BLOCKED COMBOS + SESSION BOOSTS — Phase 1.7b Bot 3 v2 (17/05/2026)
# ════════════════════════════════════════════════════════════════════════
# Source : audit Phase 1.0 post-enrichissement v4 (454 cols).
# Methodologie : DSR Lopez Bonferroni n_trials=1064 (28 sessions × 19 levels × 2 dirs),
# walk-forward 12-fold (Pardo 1992), bootstrap CI 95% n_boot=1000, n>=100/combo.
# Cf :
#   - DATA/BACKTEST/BOT3/combos_session_level_post_fix_6m_v4_enriched.csv
#   - DOCS/BOT3_V2_PHASE1_0_AUDIT_REPORT.md
#   - DOCS/BOT3_V2_CHANGES.md (AXE 5 BLOCK + AXE 6 BOOST)
# Reviews : ml-trainer GO + market-analyst GO + code-reviewer GO.

# 5 combos avec DSR_block=1.0 (Bonferroni 1064 trials), walk-forward 8-10/12 folds
# avec PF<0.7 stable. Edge negatif structurel ES marche bull persistant 2026.
# Cle : (symbol, session, level_name). Session resolu par bot3_context_analyzer.
BLOCKED_COMBOS_BOT3 = {
    ("ES", "ASIA", "SIDAK_SWING_HIGH"): {
        "pf_observed": 0.46, "n": 306, "dsr_block": 1.0,
        "folds_lt_0_7": 10, "pnl_evite_ticks": -1577.0,
    },
    ("ES", "ASIA", "VWAP_W_SD1D"): {
        "pf_observed": 0.52, "n": 128, "dsr_block": 1.0,
        "folds_lt_0_7": 9, "pnl_evite_ticks": -681.5,
    },
    ("ES", "ASIA", "SIDAK_SWING_LOW"): {
        "pf_observed": 0.53, "n": 230, "dsr_block": 1.0,
        "folds_lt_0_7": 9, "pnl_evite_ticks": -1255.7,
    },
    ("ES", "LONDON", "CUR_VPOC"): {
        "pf_observed": 0.45, "n": 236, "dsr_block": 1.0,
        "folds_lt_0_7": 10, "pnl_evite_ticks": -1645.7,
    },
    ("ES", "LONDON", "SINGLE_PRINT"): {
        "pf_observed": 0.66, "n": 127, "dsr_block": 1.0,
        "folds_lt_0_7": 8, "pnl_evite_ticks": -467.4,
    },
}

# 1 combo BOOST validee. Boost +15 sur confidence_raw (avant clamp 0-100).
# NQ LONDON SIDAK_COLOR_UP_zone uniquement : PF 2.02 n=459 CI[1.59, 2.63] 9/12 folds.
#
# HOLD ES US_CASH SIDAK_COLOR_DN_zone (PF 1.78 n=189 CI[1.21, 2.71]) :
# ml-trainer NOGO Phase 1.7b — CI plus large + concentration bull regime
# possible. Re-evaluer J+30 sur audit 8m enriched complets (replay 657k bars).
SESSION_BOOST_CONFIDENCE = {
    ("NQ", "LONDON", "SIDAK_COLOR_UP_zone"): {
        "boost": 15, "pf_observed": 2.02, "n": 459, "dsr_boost": 1.0,
        "folds_ge_1_3": 9, "pnl_gain_ticks": 8769.7,
    },
}


# ════════════════════════════════════════════════════════════════════════
# SWING_COLOR_BOOSTED — Phase 1.7d Bot 3 v2 (17/05/2026)
# ════════════════════════════════════════════════════════════════════════
# Pattern Jackson 17/05 : "retour sur niveau defendu par color_up a beaucoup
# de chances de monter, RESPECTER LA TENDANCE pour qualite du rebond".
#
# Audit empirique tools/audit_color_vs_longbar_comparison.py sur trades
# phase17b_validation (11356 trades directionnels 6m v4 enriched).
# Methodologie : DSR Lopez Bonferroni n_trials=96 (12 levels × 4 buckets × 2 sym),
# n>=50 par (sym, level, bucket), PF>=1.3, DSR>=0.95.
#
# Comparaison empirique 3 approches :
#   - COLOR seul         : 11 GOOD_EDGE, PnL/trade +12.9t, DIVERGENCE -15.7t
#   - LONG_BAR seul      :  7 GOOD_EDGE, PnL/trade +7.6t, DIVERGENCE +2.8t (anormal)
#   - COMBINE (any-of)   :  6 GOOD_EDGE, PnL/trade +9.2t (dilution)
# -> COLOR seul retenu (signal net + DIVERGENCE asymetrique).
#
# Anti Pattern 11 V1 : 1 seule feature derivee `swing_color_consensus`
# (4 buckets : CONFLUENCE_STRONG/OK/DIVERGENCE/NEUTRE) calculee dans
# bot3_decision_engine apres resolution side. 0 gate, 0 penalite,
# juste +X confidence si combo GOOD_EDGE valide DSR=1.0.
#
# Bucket classification (dans evaluate_decision) :
#   side=LONG  + dist_color_up_nearest_pct proche (<0.05%) + imb >=0 -> CONFLUENCE_STRONG
#   side=LONG  + dist_color_up_nearest_pct proche                   -> CONFLUENCE_OK
#   side=LONG  + dist_color_dn_nearest_pct proche + imb < 0          -> DIVERGENCE (no boost)
#   side=SHORT symetrique
#
# DIVERGENCE actuellement non-bloquante (447 trades sur 12 levels = ~37/level,
# sous n>=100 requis pour DSR Lopez strict). Backlog Phase 2 audit J+30 8m.

SWING_COLOR_BOOSTED = {
    # (symbol, level_name, bucket) -> boost
    # Tries par PnL_sum 6m decroissant (les plus rentables d'abord)
    ("NQ", "SIDAK_COLOR_UP_zone", "CONFLUENCE_STRONG"): 15,   # PF 1.93 n=1279 +25781t
    ("NQ", "SIDAK_COLOR_DN_zone", "CONFLUENCE_STRONG"): 15,   # PF 1.87 n=865  +16498t
    ("NQ", "SIDAK_COLOR_UP_zone", "CONFLUENCE_OK"):     20,   # PF 3.40 n=429  +13416t
    ("NQ", "SIDAK_COLOR_DN_zone", "CONFLUENCE_OK"):     20,   # PF 3.48 n=272  +8754t
    ("NQ", "SIDAK_SWING_HIGH",    "CONFLUENCE_STRONG"): 15,   # PF 1.62 n=268  +3816t
    ("NQ", "SIDAK_SWING_LOW",     "CONFLUENCE_STRONG"): 15,   # PF 1.40 n=313  +3154t
    ("NQ", "MQ_PUT_0DTE",         "CONFLUENCE_STRONG"): 15,   # PF 1.64 n=149  +2508t (put_support)
    ("NQ", "MQ_PUT_0DTE",         "CONFLUENCE_OK"):     10,   # PF 1.45 n=96   +1226t
    ("NQ", "SIDAK_SWING_LOW",     "CONFLUENCE_OK"):     10,   # PF 1.42 n=87   +875t
    ("NQ", "SIDAK_SWING_HIGH",    "CONFLUENCE_OK"):     10,   # PF 1.44 n=69   +855t
    ("ES", "SIDAK_SWING_LOW",     "CONFLUENCE_STRONG"): 10,   # PF 1.55 n=77   +356t
}

# Seuil de proximite COLOR (en % du prix). 0.05% = ~12t NQ a 25k / ~3t ES a 6k.
SWING_COLOR_PROXIMITY_PCT = 0.05
