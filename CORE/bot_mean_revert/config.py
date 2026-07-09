"""Configuration Bot Mean Revert VWAP.

Pattern : `cfg = BotMRConfig.from_env()` au boot, puis read-only.
Surcharge env vars via BOTMR_* (idem pattern Bot 1 v2).

Config validee empiriquement par sweep_bot_mean_revert_v2 sur 4 jours data :
  - ES : SD3 + RR 1.5 + US-only + slope_30>0 + skip London + skip pre-open
    -> PF 1.69 sur 70 trades, +$520
  - NQ : dry-evaluate Asia (n=23 hypothetical pour decision J+14)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(f"BOTMR_{name}")
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(f"BOTMR_{name}")
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(f"BOTMR_{name}")
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_tuple(name: str, default: tuple) -> tuple:
    val = os.environ.get(f"BOTMR_{name}")
    if val is None:
        return default
    return tuple(s.strip().upper() for s in val.split(",") if s.strip())


@dataclass(frozen=True)
class BotMRConfig:
    """Configuration immutable Bot Mean Revert."""

    # ============================================================
    # EXECUTION
    # ============================================================
    # CRITIQUE Sim1 explicite (sweep validation, eviter collision Sim2/Sim3)
    TRADE_ACCOUNT: str = os.environ.get("BOTMR_TRADE_ACCOUNT", "Sim1")
    N_MICROS_DEFAULT: int = _env_int("N_MICROS_DEFAULT", 1)

    # ============================================================
    # DETECTION SIGNAL (sweep v2 baseline best)
    # ============================================================
    # SD level : sd3 (extension extreme) vs sd2 (extension simple)
    # Sweep ES : sd3 PF 1.69 vs sd2 PF 1.23
    SD_LEVEL: str = os.environ.get("BOTMR_SD_LEVEL", "sd3")
    # Threshold % au-dela du SD level (0.0 = just touch, 0.1 = vrai extension)
    # FIX A1 audit forensique 22-23/06 : default 0.0 mais recommande 0.1 apres
    # fix condition SD inversee. Avec 0.1 : LONG si sd3d_pct >= -0.1 (proche SD3d).
    SD_THRESHOLD_PCT: float = _env_float("SD_THRESHOLD_PCT", 0.1)

    # FIX A2 audit forensique 22-23/06 - VWAP INTRADAY GATE
    # ============================================================
    # 9/12 LOSS Bot 1 18/06 avec MFE=0 (75%) = bot fade un mouvement immediat
    # adverse. vwap_slope_30 inutile (LAG VWAP-day cumulative). Solution :
    # filtrer LONG si prix sous VWAP-d intraday + SHORT si prix au-dessus.
    # Empirique : seuil 0.3% bloque la plupart des fades intraday catastrophiques.
    VWAP_INTRADAY_LONG_BLOCK_PCT: float = _env_float("VWAP_INTRADAY_LONG_BLOCK_PCT", 0.3)
    VWAP_INTRADAY_SHORT_BLOCK_PCT: float = _env_float("VWAP_INTRADAY_SHORT_BLOCK_PCT", 0.3)
    # RVOL zscore min (capitulation volume) - sweep baseline best : 0.0
    RVOL_ZSCORE_MIN: float = _env_float("RVOL_ZSCORE_MIN", 0.0)
    # Exhaustion ctx (climax / failed_auction / delta_exhaustion) - off baseline
    REQUIRE_EXHAUSTION: bool = _env_bool("REQUIRE_EXHAUSTION", False)
    # Delta direction (delta_bar > 0 LONG, < 0 SHORT) - off baseline
    REQUIRE_DELTA_DIRECTION: bool = _env_bool("REQUIRE_DELTA_DIRECTION", False)

    # ============================================================
    # SL / TP / RR (mean revert tight)
    # ============================================================
    # RR : 1.5 (sweep best ES vs 2.0)
    RR: float = _env_float("RR", 1.5)
    # SL fixe ticks (calibre extension SD)
    SL_TICKS_ES: int = _env_int("SL_TICKS_ES", 20)
    SL_TICKS_NQ: int = _env_int("SL_TICKS_NQ", 35)
    SL_TICKS_MGC: int = _env_int("SL_TICKS_MGC", 50)

    # Cooldown bars apres trade (anti-overtrade)
    COOLDOWN_BARS: int = _env_int("COOLDOWN_BARS", 30)

    # FIX A3 audit forensique 22-23/06 (PHASE A) - COOLDOWN PROGRESSIF POST-LOSS
    # ============================================================
    # Empirique 18/06 FOMC : 16 trades Bot 1 sur 1 journee, 12 LOSS dont 9 avec
    # MFE=0 (75% fade adverse immediat). Spirale carnage type "revenge trade".
    # SOLUTION : cooldown progressif selon n_sl_consec (reuse circuit breaker).
    #   - 1 SL consec → COOLDOWN_POST_LOSS_BARS (default 45 min)
    #   - 2 SL consec → COOLDOWN_POST_2LOSS_BARS (default 90 min)
    #   - 3+ SL consec → circuit breaker HALT 60 min existant prend le relais
    # Mark Douglas "consistency beats intensity" sans tuer le volume data
    # (Jackson directive 23/06 : pas de MAX_TRADES=5, besoin data).
    COOLDOWN_POST_LOSS_BARS: int = _env_int("COOLDOWN_POST_LOSS_BARS", 45)
    COOLDOWN_POST_2LOSS_BARS: int = _env_int("COOLDOWN_POST_2LOSS_BARS", 90)

    # FIX A4 audit forensique 22-23/06 (PHASE A) - GATE NEWS/FOMC
    # ============================================================
    # Empirique 18/06 FOMC : Bot 1 a fait 16 trades pendant FOMC day 14:00 ET
    # (carnage 12 LOSS). News calendar deja en place dans CORE/eco_calendar.py
    # (utilise par Bot 3 v3) avec windows BLOCK_WINDOWS configurees pour
    # FOMC/NFP/CPI/PCE. SOLUTION : reuse is_blocked_now() dans signal_engine
    # AVANT trade. Fail-CLOSED si module HS (mieux rater un trade qu'etre dans
    # un FOMC). Convention Bot 3 v3 24/05 (R1 code-reviewer).
    NEWS_GATE_ENABLED: bool = _env_bool("NEWS_GATE_ENABLED", True)
    NEWS_GATE_FAIL_CLOSED: bool = _env_bool("NEWS_GATE_FAIL_CLOSED", True)

    # FIX PROP #1 audit market-analyst 24/06 - MOMENTUM_5B FILTER (anti catch falling knife)
    # ============================================================
    # Empirique 7 jours 16-24/06 (67 trades) :
    # - momentum_5b <= -5  : WR 6.7% (1 TP / 21 SL+MH) sur n=22
    # - momentum_5b <= -10 : WR 0% (0/7) - catch falling knife garanti
    # - momentum_5b >= 0   : WR 51.7% - bull bar = signal
    # Solution : pour LONG bloquer si momentum_5b < MIN_LONG.
    #             pour SHORT bloquer si momentum_5b > MAX_SHORT.
    # Backtest 67 trades : sacrifie 1 win (4.5%), PnL +$1912 (delta retroactif).
    # Wins preserves : 95.5% (directive Jackson >= 70% wins).
    MOMENTUM_5B_FILTER_ENABLED: bool = _env_bool("MOMENTUM_5B_FILTER_ENABLED", True)
    MOMENTUM_5B_MIN_LONG: float = _env_float("MOMENTUM_5B_MIN_LONG", -5.0)
    MOMENTUM_5B_MAX_SHORT: float = _env_float("MOMENTUM_5B_MAX_SHORT", 5.0)

    # FIX PROP #2 audit market-analyst 24/06 - SKIP SESSION AH (After Hours 21-24h UTC)
    # ============================================================
    # Empirique 7 jours 16-24/06 :
    # - Session AH (21:00-24:00 UTC) : 0/10 TP - CARNAGE TOTAL (0% WR)
    # - Notamment 23/06 NQ 22:34-23:48 : 4 SL -$700 en 1h15 (revenge trade)
    # Cause probable : liquidite faible + news asiatiques imminentes + gap risk.
    # Backtest 67 trades : sacrifie 0 win, evite 5 SL, +$875.
    # Wins preserves : 100%.
    SKIP_AH_SESSION_ENABLED: bool = _env_bool("SKIP_AH_SESSION_ENABLED", True)
    AH_SESSION_START_UTC_HOUR: int = _env_int("AH_SESSION_START_UTC_HOUR", 21)
    AH_SESSION_END_UTC_HOUR: int = _env_int("AH_SESSION_END_UTC_HOUR", 24)

    # FIX V_FINAL audit market-analyst 24/06 - REGIME-AWARE ARCHITECTURE
    # ============================================================
    # Directive Jackson 24/06 soir : "TOUT DOIT ETRE DYNAMIQUE SELON LE REGIME".
    # Backtest empirique 22929 bars 7j : 5 regimes + 3 regles d'exclusion =
    # PnL +$299 retroactif (de -$269 a +$30), wins preserves 95%.
    # Validation cross-period : TRAIN 5j, TEST 2j, sans-FOMC : tous positifs.
    # Cf CORE/bot_mean_revert/regime_classifier.py pour seuils + logic.
    REGIME_AWARE_ENABLED: bool = _env_bool("REGIME_AWARE_ENABLED", True)
    # Blacklist format "REGIME:session", "REGIME:*" = any session.
    # V_FINAL = 3 regles backtest validees :
    #   PANIC:*               -> event-driven, illiquide
    #   CALM_RANGE:us_cash    -> chop institutionnel (0% WR sample N=7)
    #   VOLATILE_RANGE:asia   -> panic post-news Asia (11% WR sample N=9)
    REGIME_AWARE_BLACKLIST: tuple = field(
        default_factory=lambda: _env_tuple(
            "REGIME_AWARE_BLACKLIST",
            ("PANIC:*", "CALM_RANGE:us_cash", "VOLATILE_RANGE:asia"),
        )
    )

    # Fix audit 30/06 (OR -> AND cross-confirmation) : env vars override pour
    # tuner sans redeploy. Default = valeurs RegimeThresholds dataclass.
    # Utilisation : BOTMR_VIX_PANIC=19.5 BOTMR_ATR_PCT_PANIC=0.076
    #               BOTMR_VIX_PANIC_EXTREME=25.0
    VIX_PANIC: float = _env_float("VIX_PANIC", 19.5)
    ATR_PCT_PANIC: float = _env_float("ATR_PCT_PANIC", 0.076)
    VIX_PANIC_EXTREME: float = _env_float("VIX_PANIC_EXTREME", 25.0)

    # ============================================================
    # REGIME HARD FILTER (anti catch falling knife - 18/06/2026)
    # ============================================================
    # Garde-fou ABSOLU en complement du regime mode (trend_align_es / contrarian_nq).
    # Calibre carnage 18/06 (-$1025 broker E-mini sur 4 LONGs ES en pleine descente
    # 7568 -> 7533) : le mode trend_align_es bloque slope <= 0 mais ne dit rien sur
    # l'amplitude. Si slope_30 est faiblement positif malgre une chute prix rapide
    # (lag MA cumulative VWAP day), le bot peut spammer LONGs en descente.
    # vwap_slope_30 = (vwap_now - vwap_30bars_ago) / 10 pts/barre (ES median 0.45).
    # Seuil -1.5 = bornes empiriques live (min historique observe -1.06).
    # RECALIBRAGE 18/06 (apres carnage -$1025) : seuils tightener base sur
    # distribution empirique sierra_enriched 5j (slope_30 median=0.45, P5=0.16).
    # Threshold initial -1.5 etait JAMAIS atteint = filtre dormant. Nouveau -0.3
    # bloque LONG quand slope franchement bearish (sous P5 sample, regime cassant).
    #
    # PHASE 2 18/06 SEUILS PAR SYMBOLE (Option A) :
    # Calibration empirique 9j ES+NQ revele que stdev slope_30 NQ=8.54 vs ES=1.42
    # (6x plus). Seuils identiques 0.3 bloquent 78% des SHORT NQ legitimes.
    # Solution : seuils echelles par symbole. Fallback gentle generique pour MGC.
    REGIME_FILTER_ENABLED: bool = _env_bool("REGIME_FILTER_ENABLED", True)
    # Seuils generiques (fallback si pas d'override symbole - utilises MGC)
    SLOPE_30_MIN_LONG: float = _env_float("SLOPE_30_MIN_LONG", -0.3)
    SLOPE_30_MAX_SHORT: float = _env_float("SLOPE_30_MAX_SHORT", 0.3)
    # Seuils ES : stdev 1.42 -> +/- 0.5 (sous P25-P75 mediane)
    SLOPE_30_MIN_LONG_ES: float = _env_float("SLOPE_30_MIN_LONG_ES", -0.5)
    SLOPE_30_MAX_SHORT_ES: float = _env_float("SLOPE_30_MAX_SHORT_ES", 0.5)
    # Seuils NQ : stdev 8.54 = 6x ES -> +/- 3.0 (echelle proportionnee)
    SLOPE_30_MIN_LONG_NQ: float = _env_float("SLOPE_30_MIN_LONG_NQ", -3.0)
    SLOPE_30_MAX_SHORT_NQ: float = _env_float("SLOPE_30_MAX_SHORT_NQ", 3.0)
    # VIX spike intraday : si VIX up > X% vs open session = regime panic = no MR.
    # Fallback : si vix_open_session absent du bar, check absolu VIX_ABS_PANIC (30).
    VIX_INTRADAY_SPIKE_PCT: float = _env_float("VIX_INTRADAY_SPIKE_PCT", 15.0)
    VIX_ABS_PANIC: float = _env_float("VIX_ABS_PANIC", 30.0)

    # ============================================================
    # NO RE-ENTRY DISTANCE (anti-clustering spatial - 18/06/2026)
    # ============================================================
    # Eviter clustering d'entries meme direction au meme prix.
    # Pattern observe 18/06 : 5 LONGs ES dans 13 ticks (7547.25 -> 7560.75)
    # -> -$237.50 sur l'entry @ 7558.25 (zone deja over-tradee).
    # 3e garde-fou en plus du COOLDOWN_BARS (temporel) et MAX_HOLD_MINUTES.
    NO_REENTRY_TICKS_ES: int = _env_int("NO_REENTRY_TICKS_ES", 20)
    NO_REENTRY_TICKS_NQ: int = _env_int("NO_REENTRY_TICKS_NQ", 50)
    NO_REENTRY_TICKS_MGC: int = _env_int("NO_REENTRY_TICKS_MGC", 30)

    # ============================================================
    # MAX HOLD TIMEOUT (Lopez AFML Ch.3 Triple Barrier Method)
    # ============================================================
    # Hard timeout sur position ouverte : si elapsed >= MAX_HOLD_MINUTES sans
    # toucher TP ni SL, force close a market. Standard pro MR intraday 1-min.
    # 18/06/2026 ajoute pour eviter trades qui trainent toute la journee.
    MAX_HOLD_MINUTES: int = _env_int("MAX_HOLD_MINUTES", 30)
    # FIX 18/06 ANTI-BOUCLE INFINIE MAX_HOLD :
    #  BOOT_WARMUP : skip MAX_HOLD pendant N sec apres boot bot. Permet au
    #  DtcFillListener de detecter fills orphelins via ORDER_UPDATE avant
    #  qu'on envoie un nouveau close market.
    MAX_HOLD_BOOT_WARMUP_SEC: int = _env_int("MAX_HOLD_BOOT_WARMUP_SEC", 60)
    #  RETRY_COOLDOWN : apres un force close envoye, ne pas re-declencher
    #  MAX_HOLD pendant N sec. Sinon = 9 close markets en 8 min (cumul SHORTs).
    #  Default 180s = avec bars 1min, max 3 closes en 9 ticks (vs 9 sans guard).
    MAX_HOLD_RETRY_COOLDOWN_SEC: int = _env_int("MAX_HOLD_RETRY_COOLDOWN_SEC", 180)
    # RESERVE #3 code-reviewer 18/06 : plafond retries MAX_HOLD.
    # Si N timeouts envoyes mais position toujours OPEN (DTC down, Sim refuse,
    # sequence cancel+market_close orpheline), on halt le symbole et on attend
    # intervention manuelle. Sans ce plafond, une position bloquee genere des
    # closes infinis tout au long de la session.
    # Default 3 retries : avec retry_cooldown=180s, c'est 9 min de tentatives
    # avant halt -> garde-fou pour cas pathologique.
    MAX_HOLD_MAX_RETRIES: int = _env_int("MAX_HOLD_MAX_RETRIES", 3)

    # ============================================================
    # REGIME FILTERS (asymetrique ES vs NQ)
    # ============================================================
    # Mode : trend_align_es / contrarian_nq / off
    #   - trend_align_es : LONG si slope_30>0, SHORT si slope_30<0
    #   - contrarian_nq  : LONG si slope_30<0, SHORT si slope_30>0
    REGIME_FILTER_MODE_ES: str = os.environ.get("BOTMR_REGIME_FILTER_MODE_ES", "trend_align_es")
    REGIME_FILTER_MODE_NQ: str = os.environ.get("BOTMR_REGIME_FILTER_MODE_NQ", "contrarian_nq")
    # VIX min pour SHORT (ES only) : eviter SHORT en regime calm
    VIX_MIN_FOR_SHORT: float = _env_float("VIX_MIN_FOR_SHORT", 20.0)
    # NQ trend_day_score max (contrarian_nq) : eviter SHORT en strong trend day
    NQ_TREND_DAY_MAX: float = _env_float("NQ_TREND_DAY_MAX", 0.65)

    # ============================================================
    # SESSIONS (par-symbol asymetrique)
    # ============================================================
    # 17/06 Jackson : TOUTES sessions pour commencer (Asia + London + US)
    # Override env BOTMR_TRADABLE_SESSIONS_ES / NQ si besoin restriction future
    TRADABLE_SESSIONS_ES: tuple = field(
        default_factory=lambda: _env_tuple("TRADABLE_SESSIONS_ES", ("ASIA", "LONDON", "US"))
    )
    TRADABLE_SESSIONS_NQ: tuple = field(
        default_factory=lambda: _env_tuple("TRADABLE_SESSIONS_NQ", ("ASIA", "LONDON", "US"))
    )
    # Skip pre-open US 11:30-13:30 UTC : DESACTIVE 17/06 (toutes sessions ouvertes)
    SKIP_PREOPEN_US: bool = _env_bool("SKIP_PREOPEN_US", False)

    # ============================================================
    # DAILY LIMITS — DIRECTIVE JACKSON 19/06/2026
    # ============================================================
    # CHANGEMENT : illimite + perte max -$2500 (vs ancien 5/-$200 Douglas).
    # Raison : phase paper Sim1, BESOIN DE DATA pour analyse. Selectivite
    # imposee par filtres qualite signaux PAS par limit hard. Reflexion long
    # terme : ameliorer signal_engine pour qu'il sorte SEULEMENT trades de
    # qualite (rvol range, cvd_session non-epuise, dist_prev_val positif BUY,
    # etc.) au lieu de couper artificiellement le bot.
    MAX_TRADES_PER_DAY: int = _env_int("MAX_TRADES_PER_DAY", 9999)
    DAILY_STOP_LOSS_USD: float = _env_float("DAILY_STOP_LOSS_USD", -2500.0)
    DAILY_STOP_WIN_USD: float = _env_float("DAILY_STOP_WIN_USD", 99999.0)

    # ============================================================
    # CIRCUIT BREAKER (anti-stubbornness 18/06/2026)
    # ============================================================
    # Halt trading PAR SYMBOLE apres N SL consecutives. Reset compteur au prochain TP.
    # Reference carnage 18/06 : -$1025 broker E-mini sur 4 SL LONG ES d'affilee sans
    # mecanisme d'auto-correction (bot continue meme apres 3 SL = signal manque /
    # regime change). Trader pro stoppe a 3 SL pour reassesser.
    # Granularite : par symbole (ES halt -> NQ continue independamment).
    # Persiste cross-restart via PositionStore (n_sl_consec + halt_until_ts).
    CIRCUIT_BREAKER_ENABLED: bool = _env_bool("CIRCUIT_BREAKER_ENABLED", True)
    SL_CONSEC_HALT_THRESHOLD: int = _env_int("SL_CONSEC_HALT", 3)
    HALT_DURATION_MINUTES: int = _env_int("HALT_DURATION_MIN", 60)

    # ============================================================
    # ULTRATHINK QUALITY FILTER (19/06/2026)
    # ============================================================
    # Apres analyse 37 trades (16-19/06) : filtres "intuitifs" (delta_bar > 0
    # pour BUY) etaient TOUS INVERSES vs realite empirique. Vraie philosophie
    # MEAN REVERT = "acheter quand barre BEAR + recovery acheteurs fin de barre"
    # (Wyckoff spring / low rejection).
    #
    # COMBINAISON GAGNANTE empirique :
    #   LONG  : delta_bar < -10 AND finish_strength > 0
    #   SHORT : delta_bar > +10 AND finish_strength < 0
    #
    # Resultat backtest 37 trades :
    #   - 12 trades kept (32% selectif)
    #   - WR 58.3% (vs 32% baseline)
    #   - PF 2.62 (vs 0.93 baseline)
    #   - PnL +$1637.50 (vs -$679 baseline) = AMELIORATION +$2316
    #
    # Sample 37 trades < 100 DSR Lopez : effet enorme mais pas validation
    # statistique formelle. Feature flag pour rollback rapide.
    #
    # Codes log dedies pour audit J+1 :
    #   - BOTMR_ULTRATHINK_BLOCK_DELTA_BAR (raison: delta hors range)
    #   - BOTMR_ULTRATHINK_BLOCK_FINISH_STRENGTH (raison: no recovery)
    #   - BOTMR_ULTRATHINK_PASS (passe le filtre)
    ULTRATHINK_FILTER_ENABLED: bool = _env_bool("ULTRATHINK_FILTER", True)
    DELTA_BAR_BEAR_LONG_MAX: float = _env_float("DELTA_BAR_BEAR_LONG_MAX", -10.0)
    DELTA_BAR_BULL_SHORT_MIN: float = _env_float("DELTA_BAR_BULL_SHORT_MIN", 10.0)
    FINISH_STRENGTH_LONG_MIN: float = _env_float("FINISH_STRENGTH_LONG_MIN", 0.0)
    FINISH_STRENGTH_SHORT_MAX: float = _env_float("FINISH_STRENGTH_SHORT_MAX", 0.0)

    # ============================================================
    # REGIME SCORER CONTINU (18/06/2026 - Phase 3 alternative score)
    # ============================================================
    # Approche score continu pondere multi-features. Alternative au vote
    # majoritaire binaire qui rate la non-monotonie observee deciles
    # slope_30 -> EV (calibration empirique 9j).
    # Score [-100, +100] mappe vers 5 regimes + PANIC override.
    # Features ponderees : slope (30%) + swings (25%) + delta (15%) + trend_day (15%).
    # Bloque uniquement TREND_*_STRONG + PANIC. TREND_*_WEAK et RANGE autorises.
    #
    # DECISION 18/06 (croisement 2 approches) : DEFAULT FALSE.
    # Le scorer est trop permissif (laisse passer 3-4/4 LONGs carnage 18/06).
    # Activable via env BOTMR_REGIME_SCORER_ENABLED=1 apres recalibration
    # empirique sur 30j+ incluant jours trending. RegimeClassifier (KISS vote
    # majoritaire) est ACTIF par defaut et suffisant pour bloquer le carnage.
    REGIME_SCORER_ENABLED: bool = _env_bool("REGIME_SCORER_ENABLED", False)
    # Seuils mapping score -> regime (override env BOTMR_REGIME_SCORE_*)
    REGIME_SCORE_STRONG_THRESHOLD: float = _env_float("REGIME_SCORE_STRONG_THRESHOLD", 60.0)
    REGIME_SCORE_WEAK_THRESHOLD: float = _env_float("REGIME_SCORE_WEAK_THRESHOLD", 30.0)

    # ============================================================
    # CONFLUENCE NIVEAU MENTHORQ (18/06/2026)
    # ============================================================
    # Require N niveaux structurels (MenthorQ HVL/Call/Put, GEX nearest,
    # 1d max/min, VWAP D/W SD bands) dans un rayon de X ticks de l'entry
    # candidate. Sinon entry "isolated" = skip.
    # Calibre carnage 18/06 : 4 LONGs ES dans le vide entre 2 niveaux
    # (7548, 7554, 7558, 7533) sans confluence = -$1025 broker.
    # Garde-fou : un trader pro entre uniquement quand 2-3 niveaux alignent
    # un cluster <10t (HVL+GEX+VWAP SD = vraie zone d'absorption attendue).
    # Implementation : consomme les `dist_*_pct` ET `dist_*_ticks` deja
    # pre-calcules par le DMP/enricher cote Sierra. Pas de mq_<level> absolu
    # dans le bar (sierra_enriched fournit les distances directement).
    # DECISION 18/06 PHASE 2 : DEFAULT FALSE (apres incident NQ 100% bloque).
    # Niveaux MenthorQ sont en distance % du prix. Prix NQ ~30598 = 1 niveau pres
    # = 392t (vs prix ES ~7550 = 1 niveau pres = 33t). Asymetrie d'echelle 12x.
    # Solution radius en ticks ne marche pas cross-instrument.
    # Vrais refactor : utiliser % du prix au lieu de ticks. A faire post 60j data.
    # En attendant : disable. On a 6 autres garde-fous (cooldown + max_hold +
    # no_reentry + circuit_breaker + regime_hard_per_symbol + regime_classifier KISS).
    CONFLUENCE_FILTER_ENABLED: bool = _env_bool("CONFLUENCE_FILTER_ENABLED", False)
    # Seuils gardes au cas ou activation env override (test/debug).
    CONFLUENCE_MIN_LEVELS: int = _env_int("CONFLUENCE_MIN_LEVELS", 1)
    CONFLUENCE_RADIUS_TICKS_ES: int = _env_int("CONFLUENCE_RADIUS_ES", 100)
    CONFLUENCE_RADIUS_TICKS_NQ: int = _env_int("CONFLUENCE_RADIUS_NQ", 250)
    CONFLUENCE_RADIUS_TICKS_MGC: int = _env_int("CONFLUENCE_RADIUS_MGC", 20)

    # ============================================================
    # PHASE 4 18/06 : ORDERFLOW CONFIRMATION + ANTI-TOP + MOMENTUM CAP
    # ============================================================
    # Calibration empirique 6 trades post-deploy 18/06 :
    #  LOSS 3/3 : delta_bar negatif + slope_10>0.77 + bars_since_HH<=5 + pres HOD
    #  WIN 3/3 : delta_bar positif OU rvol_z>=2 (exhaustion vendeur claire)
    # Variable la + discriminante : delta_bar (ecart WIN-LOSS = +210)
    # Order : AVANT regime_classifier (filtres deterministes peu couteux d'abord)
    # Validate market-analyst tour 2 : SLOPE_10_MAX bump 1.0->1.1, HOD bump 20->25.
    ORDERFLOW_CONFIRM_ENABLED: bool = _env_bool("ORDERFLOW_CONFIRM_ENABLED", True)
    ORDERFLOW_RVOL_EXHAUSTION_MIN: float = _env_float("ORDERFLOW_RVOL_EXHAUSTION_MIN", 2.0)
    ANTI_TOP_ENABLED: bool = _env_bool("ANTI_TOP_ENABLED", True)
    ANTI_TOP_BARS_SINCE_HH_MAX: int = _env_int("ANTI_TOP_BARS_SINCE_HH_MAX", 5)
    ANTI_TOP_DIST_HOD_MAX_TICKS: int = _env_int("ANTI_TOP_DIST_HOD_MAX_TICKS", 25)
    MOMENTUM_CAP_ENABLED: bool = _env_bool("MOMENTUM_CAP_ENABLED", True)
    SLOPE_10_MAX_LONG: float = _env_float("SLOPE_10_MAX_LONG", 1.1)

    # ============================================================
    # DATA SOURCE / POLLING
    # ============================================================
    DMP_BAR_MAX_AGE_SEC: int = _env_int("DMP_BAR_MAX_AGE_SEC", 90)
    POLL_INTERVAL_SEC: int = _env_int("POLL_INTERVAL_SEC", 15)
    SIERRA_ENRICHED_DIR_TEMPLATE: str = os.environ.get(
        "BOTMR_SIERRA_DIR",
        "DATA/live_enriched/sierra/{symbol}",
    )

    # ============================================================
    # DRY-EVALUATE NQ (audit empirique sans execution)
    # ============================================================
    # 16/06/2026 : NQ trade LIVE avec IntermarketGate active (decision Jackson souveraine).
    # Backtest 4j REJETE comme oracle (sample trop petit + ne capture pas le setup pro
    # de Jackson observe en manuel meme journee). Paper = test live = pas de risque.
    # Observation 14j sur Sim1 = vraie validation.
    DRY_EVAL_NQ: bool = _env_bool("DRY_EVAL_NQ", False)

    # ============================================================
    # INTERMARKET GATE (ES leader pour NQ - Jackson 16/06/2026)
    # ============================================================
    # Methodologie : NQ LONG seulement si ES touche niveau structurel
    # (VWAP_W principal) + bias bar coherent (vert pour LONG, rouge pour SHORT).
    # Souveraine Jackson 16/06 : ACTIVE par defaut. Backtest 4j ne fait pas autorite
    # sur ce setup intermarket. Paper live = test reel sans risque financier.
    INTERMARKET_GATE_ENABLED: bool = _env_bool("INTERMARKET_GATE", True)
    # Mapping trade_sym -> leader_sym (NQ utilise ES, MGC pas de leader)
    INTERMARKET_LEADER_BY_SYM: dict = field(default_factory=lambda: {"NQ": "ES"})
    # Proximity threshold % au niveau leader (0.10 = 0.1% de distance)
    INTERMARKET_LEVEL_PROXIMITY_PCT: float = _env_float("INTERMARKET_PROXIMITY_PCT", 0.10)

    # ============================================================
    # REGIME CLASSIFIER (Phase 3 18/06 - vote majoritaire 3 signaux)
    # ============================================================
    # Approche KISS : 3 signaux INDEPENDANTS (slope / swing structure / panic),
    # vote majoritaire decide. PANIC prioritaire (1 vote suffit).
    # Bloque MR en dehors du regime RANGE.
    # Implementation : CORE/bot_mean_revert/gates/regime_classifier.py
    #
    # Coexiste avec REGIME_FILTER_ENABLED (filtre scalaire slope_30) et
    # REGIME_FILTER_MODE_ES/NQ (trend_align / contrarian). Le classifier est
    # une COUCHE supplementaire, executee APRES detection direction.
    # Defense en profondeur : si carnage 18/06 se repete, le classifier
    # detecte TREND_DOWN via swing structure meme si slope marginal.
    REGIME_CLASSIFIER_ENABLED: bool = _env_bool("REGIME_CLASSIFIER_ENABLED", True)
    # Seuil ATR z-score panic (utilise par signal_panic OR avec VIX_ABS_PANIC).
    # ctx_atr_zscore actuellement ABSENT du bar sierra_enriched : ce seuil est
    # dormant tant que le field n'est pas calcule cote DMP. Fallback gracieux
    # (signal_panic verifie VIX absolu seul).
    ATR_ZSCORE_PANIC: float = _env_float("ATR_ZSCORE_PANIC", 2.5)

    # ============================================================
    # HELPERS
    # ============================================================
    def sl_ticks(self, symbol: str) -> int:
        s = symbol.upper()
        if s == "ES":
            return self.SL_TICKS_ES
        if s == "NQ":
            return self.SL_TICKS_NQ
        if s == "MGC":
            return self.SL_TICKS_MGC
        return self.SL_TICKS_ES

    def slope_30_min_long(self, symbol: str) -> float:
        """Retourne le seuil MIN slope_30 pour LONG MR sur ce symbole.

        Phase 2 18/06 : calibre par symbole car stdev NQ=8.54 vs ES=1.42 (6x).
        Seuils identiques 0.3 = bug NQ SHORT bloque 78% records empiriquement.
        Fallback generique SLOPE_30_MIN_LONG pour MGC ou symboles inconnus.
        """
        s = symbol.upper()
        if s == "ES":
            return self.SLOPE_30_MIN_LONG_ES
        if s == "NQ":
            return self.SLOPE_30_MIN_LONG_NQ
        return self.SLOPE_30_MIN_LONG  # default generique

    def slope_30_max_short(self, symbol: str) -> float:
        """Retourne le seuil MAX slope_30 pour SHORT MR sur ce symbole.

        Symetrique slope_30_min_long. NQ +3.0 vs ES +0.5 (6x echelle).
        """
        s = symbol.upper()
        if s == "ES":
            return self.SLOPE_30_MAX_SHORT_ES
        if s == "NQ":
            return self.SLOPE_30_MAX_SHORT_NQ
        return self.SLOPE_30_MAX_SHORT  # default generique

    def no_reentry_ticks(self, symbol: str) -> int:
        """Retourne le seuil ticks de distance min entre 2 entries meme direction.

        Si nouvelle candidate dans `no_reentry_ticks(sym)` ticks du dernier entry
        meme direction sur ce symbol -> skip (anti-clustering).
        """
        s = symbol.upper()
        if s == "ES":
            return self.NO_REENTRY_TICKS_ES
        if s == "NQ":
            return self.NO_REENTRY_TICKS_NQ
        if s == "MGC":
            return self.NO_REENTRY_TICKS_MGC
        return 20  # default raisonnable (= ES)

    def confluence_radius_ticks(self, symbol: str) -> int:
        """Retourne le rayon ticks pour le filtre confluence niveaux MenthorQ.

        Si entry candidate a moins de `CONFLUENCE_MIN_LEVELS` niveaux dans
        ce rayon -> skip (eviter entry dans le vide entre 2 niveaux).
        """
        s = symbol.upper()
        if s == "ES":
            return self.CONFLUENCE_RADIUS_TICKS_ES
        if s == "NQ":
            return self.CONFLUENCE_RADIUS_TICKS_NQ
        if s == "MGC":
            return self.CONFLUENCE_RADIUS_TICKS_MGC
        return self.CONFLUENCE_RADIUS_TICKS_ES  # default = ES

    def regime_filter_mode(self, symbol: str) -> str:
        s = symbol.upper()
        if s == "ES":
            return self.REGIME_FILTER_MODE_ES
        if s == "NQ":
            return self.REGIME_FILTER_MODE_NQ
        return "off"

    def tradable_sessions(self, symbol: str) -> tuple:
        s = symbol.upper()
        if s == "ES":
            return self.TRADABLE_SESSIONS_ES
        if s == "NQ":
            return self.TRADABLE_SESSIONS_NQ
        return ("US",)

    def is_dry_eval(self, symbol: str) -> bool:
        """True ssi symbole en mode dry-evaluate (log hypothetical, pas execute)."""
        return symbol.upper() == "NQ" and self.DRY_EVAL_NQ

    @classmethod
    def from_env(cls) -> "BotMRConfig":
        """Construit depuis env vars (snapshot au boot).

        Les env vars sont re-lues a chaque from_env() pour permettre override
        via monkeypatch en tests (pattern bot1_v2/config.py).
        """
        return cls(
            TRADE_ACCOUNT=os.environ.get("BOTMR_TRADE_ACCOUNT", "Sim1"),
            N_MICROS_DEFAULT=_env_int("N_MICROS_DEFAULT", 1),
            SD_LEVEL=os.environ.get("BOTMR_SD_LEVEL", "sd3"),
            SD_THRESHOLD_PCT=_env_float("SD_THRESHOLD_PCT", 0.1),
            VWAP_INTRADAY_LONG_BLOCK_PCT=_env_float("VWAP_INTRADAY_LONG_BLOCK_PCT", 0.3),
            VWAP_INTRADAY_SHORT_BLOCK_PCT=_env_float("VWAP_INTRADAY_SHORT_BLOCK_PCT", 0.3),
            RVOL_ZSCORE_MIN=_env_float("RVOL_ZSCORE_MIN", 0.0),
            REQUIRE_EXHAUSTION=_env_bool("REQUIRE_EXHAUSTION", False),
            REQUIRE_DELTA_DIRECTION=_env_bool("REQUIRE_DELTA_DIRECTION", False),
            RR=_env_float("RR", 1.5),
            SL_TICKS_ES=_env_int("SL_TICKS_ES", 20),
            SL_TICKS_NQ=_env_int("SL_TICKS_NQ", 35),
            SL_TICKS_MGC=_env_int("SL_TICKS_MGC", 50),
            COOLDOWN_BARS=_env_int("COOLDOWN_BARS", 30),
            COOLDOWN_POST_LOSS_BARS=_env_int("COOLDOWN_POST_LOSS_BARS", 45),
            COOLDOWN_POST_2LOSS_BARS=_env_int("COOLDOWN_POST_2LOSS_BARS", 90),
            NEWS_GATE_ENABLED=_env_bool("NEWS_GATE_ENABLED", True),
            NEWS_GATE_FAIL_CLOSED=_env_bool("NEWS_GATE_FAIL_CLOSED", True),
            MOMENTUM_5B_FILTER_ENABLED=_env_bool("MOMENTUM_5B_FILTER_ENABLED", True),
            MOMENTUM_5B_MIN_LONG=_env_float("MOMENTUM_5B_MIN_LONG", -5.0),
            MOMENTUM_5B_MAX_SHORT=_env_float("MOMENTUM_5B_MAX_SHORT", 5.0),
            SKIP_AH_SESSION_ENABLED=_env_bool("SKIP_AH_SESSION_ENABLED", True),
            AH_SESSION_START_UTC_HOUR=_env_int("AH_SESSION_START_UTC_HOUR", 21),
            AH_SESSION_END_UTC_HOUR=_env_int("AH_SESSION_END_UTC_HOUR", 24),
            REGIME_AWARE_ENABLED=_env_bool("REGIME_AWARE_ENABLED", True),
            REGIME_AWARE_BLACKLIST=_env_tuple(
                "REGIME_AWARE_BLACKLIST",
                ("PANIC:*", "CALM_RANGE:us_cash", "VOLATILE_RANGE:asia"),
            ),
            REGIME_FILTER_ENABLED=_env_bool("REGIME_FILTER_ENABLED", True),
            SLOPE_30_MIN_LONG=_env_float("SLOPE_30_MIN_LONG", -0.3),
            SLOPE_30_MAX_SHORT=_env_float("SLOPE_30_MAX_SHORT", 0.3),
            SLOPE_30_MIN_LONG_ES=_env_float("SLOPE_30_MIN_LONG_ES", -0.5),
            SLOPE_30_MAX_SHORT_ES=_env_float("SLOPE_30_MAX_SHORT_ES", 0.5),
            SLOPE_30_MIN_LONG_NQ=_env_float("SLOPE_30_MIN_LONG_NQ", -3.0),
            SLOPE_30_MAX_SHORT_NQ=_env_float("SLOPE_30_MAX_SHORT_NQ", 3.0),
            VIX_INTRADAY_SPIKE_PCT=_env_float("VIX_INTRADAY_SPIKE_PCT", 15.0),
            VIX_ABS_PANIC=_env_float("VIX_ABS_PANIC", 30.0),
            NO_REENTRY_TICKS_ES=_env_int("NO_REENTRY_TICKS_ES", 20),
            NO_REENTRY_TICKS_NQ=_env_int("NO_REENTRY_TICKS_NQ", 50),
            NO_REENTRY_TICKS_MGC=_env_int("NO_REENTRY_TICKS_MGC", 30),
            MAX_HOLD_MINUTES=_env_int("MAX_HOLD_MINUTES", 30),
            MAX_HOLD_BOOT_WARMUP_SEC=_env_int("MAX_HOLD_BOOT_WARMUP_SEC", 60),
            MAX_HOLD_RETRY_COOLDOWN_SEC=_env_int("MAX_HOLD_RETRY_COOLDOWN_SEC", 180),
            MAX_HOLD_MAX_RETRIES=_env_int("MAX_HOLD_MAX_RETRIES", 3),
            REGIME_FILTER_MODE_ES=os.environ.get("BOTMR_REGIME_FILTER_MODE_ES", "trend_align_es"),
            REGIME_FILTER_MODE_NQ=os.environ.get("BOTMR_REGIME_FILTER_MODE_NQ", "contrarian_nq"),
            VIX_MIN_FOR_SHORT=_env_float("VIX_MIN_FOR_SHORT", 20.0),
            NQ_TREND_DAY_MAX=_env_float("NQ_TREND_DAY_MAX", 0.65),
            # 17/06 Jackson : TOUTES sessions ouvertes (aligne avec defaults field).
            # Bug detecte : from_env() avait HARDCODE old defaults ("US",)/("ASIA",)
            # alors que les field default_factory etaient deja modifies. Le bot
            # charge BotMRConfig.from_env() qui ecrasait silencieusement les nouveaux defaults.
            TRADABLE_SESSIONS_ES=_env_tuple("TRADABLE_SESSIONS_ES", ("ASIA", "LONDON", "US")),
            TRADABLE_SESSIONS_NQ=_env_tuple("TRADABLE_SESSIONS_NQ", ("ASIA", "LONDON", "US")),
            SKIP_PREOPEN_US=_env_bool("SKIP_PREOPEN_US", False),
            # DIRECTIVE JACKSON 19/06 : illimite + -$2500 (cf docstring L188-)
            MAX_TRADES_PER_DAY=_env_int("MAX_TRADES_PER_DAY", 9999),
            DAILY_STOP_LOSS_USD=_env_float("DAILY_STOP_LOSS_USD", -2500.0),
            DAILY_STOP_WIN_USD=_env_float("DAILY_STOP_WIN_USD", 99999.0),
            DMP_BAR_MAX_AGE_SEC=_env_int("DMP_BAR_MAX_AGE_SEC", 90),
            POLL_INTERVAL_SEC=_env_int("POLL_INTERVAL_SEC", 15),
            SIERRA_ENRICHED_DIR_TEMPLATE=os.environ.get(
                "BOTMR_SIERRA_DIR", "DATA/live_enriched/sierra/{symbol}",
            ),
            DRY_EVAL_NQ=_env_bool("DRY_EVAL_NQ", False),
            INTERMARKET_GATE_ENABLED=_env_bool("INTERMARKET_GATE", True),
            INTERMARKET_LEADER_BY_SYM={"NQ": "ES"},
            INTERMARKET_LEVEL_PROXIMITY_PCT=_env_float("INTERMARKET_PROXIMITY_PCT", 0.10),
            REGIME_CLASSIFIER_ENABLED=_env_bool("REGIME_CLASSIFIER_ENABLED", True),
            ATR_ZSCORE_PANIC=_env_float("ATR_ZSCORE_PANIC", 2.5),
            CIRCUIT_BREAKER_ENABLED=_env_bool("CIRCUIT_BREAKER_ENABLED", True),
            SL_CONSEC_HALT_THRESHOLD=_env_int("SL_CONSEC_HALT", 3),
            HALT_DURATION_MINUTES=_env_int("HALT_DURATION_MIN", 60),
            # ULTRATHINK QUALITY FILTER (19/06/2026 - cf docstring L213-)
            ULTRATHINK_FILTER_ENABLED=_env_bool("ULTRATHINK_FILTER", True),
            DELTA_BAR_BEAR_LONG_MAX=_env_float("DELTA_BAR_BEAR_LONG_MAX", -10.0),
            DELTA_BAR_BULL_SHORT_MIN=_env_float("DELTA_BAR_BULL_SHORT_MIN", 10.0),
            FINISH_STRENGTH_LONG_MIN=_env_float("FINISH_STRENGTH_LONG_MIN", 0.0),
            FINISH_STRENGTH_SHORT_MAX=_env_float("FINISH_STRENGTH_SHORT_MAX", 0.0),
            CONFLUENCE_FILTER_ENABLED=_env_bool("CONFLUENCE_FILTER_ENABLED", False),
            CONFLUENCE_MIN_LEVELS=_env_int("CONFLUENCE_MIN_LEVELS", 1),
            CONFLUENCE_RADIUS_TICKS_ES=_env_int("CONFLUENCE_RADIUS_ES", 100),
            CONFLUENCE_RADIUS_TICKS_NQ=_env_int("CONFLUENCE_RADIUS_NQ", 250),
            CONFLUENCE_RADIUS_TICKS_MGC=_env_int("CONFLUENCE_RADIUS_MGC", 20),
            REGIME_SCORER_ENABLED=_env_bool("REGIME_SCORER_ENABLED", False),
            REGIME_SCORE_STRONG_THRESHOLD=_env_float("REGIME_SCORE_STRONG_THRESHOLD", 60.0),
            REGIME_SCORE_WEAK_THRESHOLD=_env_float("REGIME_SCORE_WEAK_THRESHOLD", 30.0),
            # Phase 4 18/06 Orderflow + Anti-top + Momentum cap
            ORDERFLOW_CONFIRM_ENABLED=_env_bool("ORDERFLOW_CONFIRM_ENABLED", True),
            ORDERFLOW_RVOL_EXHAUSTION_MIN=_env_float("ORDERFLOW_RVOL_EXHAUSTION_MIN", 2.0),
            ANTI_TOP_ENABLED=_env_bool("ANTI_TOP_ENABLED", True),
            ANTI_TOP_BARS_SINCE_HH_MAX=_env_int("ANTI_TOP_BARS_SINCE_HH_MAX", 5),
            ANTI_TOP_DIST_HOD_MAX_TICKS=_env_int("ANTI_TOP_DIST_HOD_MAX_TICKS", 25),
            MOMENTUM_CAP_ENABLED=_env_bool("MOMENTUM_CAP_ENABLED", True),
            SLOPE_10_MAX_LONG=_env_float("SLOPE_10_MAX_LONG", 1.1),
        )
