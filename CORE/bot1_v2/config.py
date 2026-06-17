"""Configuration Bot 1 v2.

Toutes les constantes calibrables ici (pas de magic numbers ailleurs).
Surcharge env vars via BOT1V2_* (pattern daily_limits_guard.load_config_from_env).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(f"BOT1V2_{name}")
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(f"BOT1V2_{name}")
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(f"BOT1V2_{name}")
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Bot1V2Config:
    """Configuration immutable Bot 1 v2.

    Pattern : `cfg = Bot1V2Config.from_env()` au boot, puis read-only.
    """

    # ============================================================
    # CLUSTER & ETOILES
    # ============================================================
    # Etoile-mere : dashboard verdict accepte
    # JACKSON souverain : FORTE CONVICTION seulement (pas PRUDENT = signal faible)
    DASHBOARD_VERDICTS_ACCEPTED: tuple = field(default_factory=lambda: (
        "ACHAT", "VENTE",
    ))

    # ============================================================
    # ETOILES QUALITE (FORTE CONVICTION cluster)
    # ============================================================
    # Bias score absolu minimum (conviction directionnelle claire)
    BIAS_SCORE_MIN_ABS: float = _env_float("BIAS_SCORE_MIN_ABS", 0.5)

    # MTF : nombre min de TF alignees (cluster confluence)
    MTF_MIN_ALIGNED: int = _env_int("MTF_MIN_ALIGNED", 3)
    # MTF : tolerance opposes max (0 = aucune TF contraire acceptee)
    MTF_MAX_OPPOSED: int = _env_int("MTF_MAX_OPPOSED", 0)

    # RVOL minimum (volume confirme le mouvement - mais pas > 3 deja veto)
    RVOL_MIN: float = _env_float("RVOL_MIN", 1.3)

    # Momentum 5b minimum absolu (direction confirmation)
    MOMENTUM_5B_MIN_ABS: float = _env_float("MOMENTUM_5B_MIN_ABS", 2.0)

    # Sur niveau de confluence : price action AU NIVEAU pro (pas dans le vide)
    # Jackson souverain : "ON DOIT AVOIR DES ZONES OU INTERVENIR
    #                      ON NE DOIS PAS TRADER A TOUT VAS"
    REQUIRE_NEAR_LEVEL: bool = _env_bool("REQUIRE_NEAR_LEVEL", True)
    # Distance maximale en ticks pour considerer "AU niveau" (strict)
    NEAR_LEVEL_MAX_TICKS_ES: int = _env_int("NEAR_LEVEL_MAX_TICKS_ES", 4)
    NEAR_LEVEL_MAX_TICKS_NQ: int = _env_int("NEAR_LEVEL_MAX_TICKS_NQ", 8)
    NEAR_LEVEL_MAX_TICKS_MGC: int = _env_int("NEAR_LEVEL_MAX_TICKS_MGC", 8)

    # Confirmation bar N+1 : OFF en v1 (BN V4 trade SUR la bar, edge intraday)
    # Activable si trop de faux signaux apres backtest 14j.
    CONFIRMATION_BARS: int = _env_int("CONFIRMATION_BARS", 0)

    # ============================================================
    # HARD VETOS (calibres NO-PARALYSIS : seuils EXTREMES uniquement)
    # ============================================================
    # Wyckoff climax : True = epuisement confirme (rare event)
    CLIMAX_VETO_ENABLED: bool = _env_bool("CLIMAX_VETO_ENABLED", True)

    # Dalton RVOL exceptional : > 3.0 = catastrophe (market-analyst 2.5 trop strict)
    RVOL_ZSCORE_VETO_THRESHOLD: float = _env_float("RVOL_ZSCORE_VETO_THRESHOLD", 3.0)

    # MenthorQ gamma block : hard veto (root cause trade -$967 ignore by Bot 1)
    GAMMA_BLOCK_VETO_ENABLED: bool = _env_bool("GAMMA_BLOCK_VETO_ENABLED", True)

    # VIX regime : bloque EXTREME (>35) et CALM (<13)
    VIX_REGIME_VETO_ENABLED: bool = _env_bool("VIX_REGIME_VETO_ENABLED", True)
    VIX_LEVEL_MAX: float = _env_float("VIX_LEVEL_MAX", 35.0)
    VIX_LEVEL_MIN: float = _env_float("VIX_LEVEL_MIN", 13.0)

    # ============================================================
    # RISK HARD CAPS (root cause trade -$967 : SL Tier1 trop loin)
    # ============================================================
    # SL maximum en ticks (par symbole). Si mur Tier1 > cap = REJECT trade.
    # SL HARD CAP : empeche trades avec SL trop loin (root cause -$967)
    # Cap relaxe pour absorber le BUFFER anti stop-hunter.
    SL_HARD_CAP_TICKS_ES: int = _env_int("SL_HARD_CAP_TICKS_ES", 20)
    SL_HARD_CAP_TICKS_NQ: int = _env_int("SL_HARD_CAP_TICKS_NQ", 30)
    SL_HARD_CAP_TICKS_MGC: int = _env_int("SL_HARD_CAP_TICKS_MGC", 35)

    # SL minimum en ticks (plancher anti-bruit micro-mouvement)
    SL_MIN_TICKS_ES: int = _env_int("SL_MIN_TICKS_ES", 6)
    SL_MIN_TICKS_NQ: int = _env_int("SL_MIN_TICKS_NQ", 10)
    SL_MIN_TICKS_MGC: int = _env_int("SL_MIN_TICKS_MGC", 12)

    # SL BUFFER anti stop-hunter (Jackson : "SL qui laisse respirer le prix")
    # Place le SL DERRIERE le mur Tier1, pas AU mur exact (= cible des hunters).
    SL_BUFFER_TICKS_ES: int = _env_int("SL_BUFFER_TICKS_ES", 3)
    SL_BUFFER_TICKS_NQ: int = _env_int("SL_BUFFER_TICKS_NQ", 5)
    SL_BUFFER_TICKS_MGC: int = _env_int("SL_BUFFER_TICKS_MGC", 5)

    # PULLBACK ENTRY : entrer sur retracement, pas sur extremum local
    # Critere : prix doit avoir retrace au moins X ticks depuis high/low recent
    PULLBACK_REQUIRED: bool = _env_bool("PULLBACK_REQUIRED", True)
    PULLBACK_LOOKBACK_BARS: int = _env_int("PULLBACK_LOOKBACK_BARS", 5)
    PULLBACK_MIN_TICKS_ES: int = _env_int("PULLBACK_MIN_TICKS_ES", 3)
    PULLBACK_MIN_TICKS_NQ: int = _env_int("PULLBACK_MIN_TICKS_NQ", 5)
    PULLBACK_MIN_TICKS_MGC: int = _env_int("PULLBACK_MIN_TICKS_MGC", 5)

    # BAR CONFIRMATION (Wyckoff "test bar") : la bar d'entry doit etre
    # bullish pour LONG (close > open + finish_strength positif)
    # bearish pour SHORT (close < open + finish_strength negatif)
    # Sinon : on entre au mauvais moment du pullback (=dans la chute)
    BAR_CONFIRMATION_REQUIRED: bool = _env_bool("BAR_CONFIRMATION_REQUIRED", True)
    BAR_FINISH_STRENGTH_MIN: float = _env_float("BAR_FINISH_STRENGTH_MIN", 30.0)

    # ============================================================
    # PATIENCE & RISK MANAGEMENT (Mark Douglas)
    # ============================================================
    MAX_TRADES_PER_DAY: int = _env_int("MAX_TRADES_PER_DAY", 5)
    COOLDOWN_POST_CLOSE_MIN: int = _env_int("COOLDOWN_POST_CLOSE_MIN", 60)
    COOLDOWN_POST_LOSS_MIN: int = _env_int("COOLDOWN_POST_LOSS_MIN", 90)  # plus strict apres SL

    DAILY_STOP_LOSS_USD: float = _env_float("DAILY_STOP_LOSS_USD", -200.0)
    DAILY_STOP_WIN_USD: float = _env_float("DAILY_STOP_WIN_USD", 150.0)

    # ============================================================
    # FLOOR ANTI-PARALYSIE (Jackson souverain : "des trades doivent passer")
    # ============================================================
    # Si N jours consecutifs sans trade > seuil -> log ALERTE + propose recalibration
    PARALYSIS_ALERT_DAYS: int = _env_int("PARALYSIS_ALERT_DAYS", 3)
    # Si N jours consecutifs sans trade > seuil critique -> auto-relax (decremente MIN_STARS)
    # Pas implemente en v1 : observation seulement, decision humaine
    PARALYSIS_AUTO_RELAX_DAYS: int = _env_int("PARALYSIS_AUTO_RELAX_DAYS", 7)

    # ============================================================
    # SESSIONS & EXEC
    # ============================================================
    # 17/06 Jackson : TOUTES sessions pour commencer (Asia + London + US + us_cash)
    TRADABLE_SESSIONS: tuple = field(default_factory=lambda: ("US", "us_cash", "ASIA", "LONDON"))
    EOD_LOCKOUT_MINUTES: int = _env_int("EOD_LOCKOUT_MINUTES", 10)
    NEWS_LOCKOUT_BEFORE_MIN: int = _env_int("NEWS_LOCKOUT_BEFORE_MIN", 5)
    NEWS_LOCKOUT_AFTER_MIN: int = _env_int("NEWS_LOCKOUT_AFTER_MIN", 5)

    # ============================================================
    # SIGNAL FRESHNESS
    # ============================================================
    MAX_SIGNAL_AGE_BARS: int = _env_int("MAX_SIGNAL_AGE_BARS", 4)

    # ============================================================
    # EXECUTION
    # ============================================================
    # CRITIQUE : Sim2 explicite (PAS default Sim3, cf orphan-prevention.md)
    TRADE_ACCOUNT: str = os.environ.get("BOT1V2_TRADE_ACCOUNT", "Sim2")
    N_MICROS_DEFAULT: int = _env_int("N_MICROS_DEFAULT", 1)  # conservateur v1
    N_MICROS_MAX: int = _env_int("N_MICROS_MAX", 3)

    # ============================================================
    # DATA SOURCE
    # ============================================================
    SIERRA_ENRICHED_DIR_TEMPLATE: str = os.environ.get(
        "BOT1V2_SIERRA_DIR",
        "DATA/live_enriched/sierra/{symbol}",
    )
    POLL_INTERVAL_SEC: int = _env_int("POLL_INTERVAL_SEC", 10)
    DMP_BAR_MAX_AGE_SEC: int = _env_int("DMP_BAR_MAX_AGE_SEC", 90)

    # ============================================================
    # OBSERVABILITY
    # ============================================================
    LOG_SKIPPED_TRADES: bool = _env_bool("LOG_SKIPPED_TRADES", True)
    SNAPSHOT_INTERVAL_BARS: int = _env_int("SNAPSHOT_INTERVAL_BARS", 30)

    # ============================================================
    # HELPERS
    # ============================================================
    def sl_hard_cap_ticks(self, symbol: str) -> int:
        """Cap SL maximum par symbole (NO-PARALYSIS exception : Tier1 too far = reject)."""
        s = symbol.upper()
        if s == "ES":
            return self.SL_HARD_CAP_TICKS_ES
        if s == "NQ":
            return self.SL_HARD_CAP_TICKS_NQ
        if s == "MGC":
            return self.SL_HARD_CAP_TICKS_MGC
        return self.SL_HARD_CAP_TICKS_ES  # default

    def sl_min_ticks(self, symbol: str) -> int:
        """Plancher SL minimum (anti-bruit micro)."""
        s = symbol.upper()
        if s == "ES":
            return self.SL_MIN_TICKS_ES
        if s == "NQ":
            return self.SL_MIN_TICKS_NQ
        if s == "MGC":
            return self.SL_MIN_TICKS_MGC
        return self.SL_MIN_TICKS_ES

    def sl_buffer_ticks(self, symbol: str) -> int:
        """Buffer SL anti stop-hunter (place SL DERRIERE le mur, pas au mur)."""
        s = symbol.upper()
        if s == "ES":
            return self.SL_BUFFER_TICKS_ES
        if s == "NQ":
            return self.SL_BUFFER_TICKS_NQ
        if s == "MGC":
            return self.SL_BUFFER_TICKS_MGC
        return self.SL_BUFFER_TICKS_ES

    def pullback_min_ticks(self, symbol: str) -> int:
        """Minimum retracement requis pour entry sur pullback."""
        s = symbol.upper()
        if s == "ES":
            return self.PULLBACK_MIN_TICKS_ES
        if s == "NQ":
            return self.PULLBACK_MIN_TICKS_NQ
        if s == "MGC":
            return self.PULLBACK_MIN_TICKS_MGC
        return self.PULLBACK_MIN_TICKS_ES

    def near_level_max_ticks(self, symbol: str) -> int:
        """Distance maximale en ticks pour considerer 'AU niveau' pro."""
        s = symbol.upper()
        if s == "ES":
            return self.NEAR_LEVEL_MAX_TICKS_ES
        if s == "NQ":
            return self.NEAR_LEVEL_MAX_TICKS_NQ
        if s == "MGC":
            return self.NEAR_LEVEL_MAX_TICKS_MGC
        return self.NEAR_LEVEL_MAX_TICKS_ES

    @classmethod
    def from_env(cls) -> "Bot1V2Config":
        """Construit depuis env vars (snapshot au boot).

        Important : les env vars sont lues a chaque from_env() (pas seulement
        a l'import), pour permettre override via monkeypatch en tests.
        """
        return cls(
            CONFIRMATION_BARS=_env_int("CONFIRMATION_BARS", 0),
            BIAS_SCORE_MIN_ABS=_env_float("BIAS_SCORE_MIN_ABS", 0.5),
            MTF_MIN_ALIGNED=_env_int("MTF_MIN_ALIGNED", 3),
            MTF_MAX_OPPOSED=_env_int("MTF_MAX_OPPOSED", 0),
            RVOL_MIN=_env_float("RVOL_MIN", 1.3),
            MOMENTUM_5B_MIN_ABS=_env_float("MOMENTUM_5B_MIN_ABS", 2.0),
            REQUIRE_NEAR_LEVEL=_env_bool("REQUIRE_NEAR_LEVEL", True),
            CLIMAX_VETO_ENABLED=_env_bool("CLIMAX_VETO_ENABLED", True),
            RVOL_ZSCORE_VETO_THRESHOLD=_env_float("RVOL_ZSCORE_VETO_THRESHOLD", 3.0),
            GAMMA_BLOCK_VETO_ENABLED=_env_bool("GAMMA_BLOCK_VETO_ENABLED", True),
            VIX_REGIME_VETO_ENABLED=_env_bool("VIX_REGIME_VETO_ENABLED", True),
            VIX_LEVEL_MAX=_env_float("VIX_LEVEL_MAX", 35.0),
            VIX_LEVEL_MIN=_env_float("VIX_LEVEL_MIN", 13.0),
            SL_HARD_CAP_TICKS_ES=_env_int("SL_HARD_CAP_TICKS_ES", 20),
            SL_HARD_CAP_TICKS_NQ=_env_int("SL_HARD_CAP_TICKS_NQ", 30),
            SL_HARD_CAP_TICKS_MGC=_env_int("SL_HARD_CAP_TICKS_MGC", 35),
            SL_MIN_TICKS_ES=_env_int("SL_MIN_TICKS_ES", 6),
            SL_MIN_TICKS_NQ=_env_int("SL_MIN_TICKS_NQ", 10),
            SL_MIN_TICKS_MGC=_env_int("SL_MIN_TICKS_MGC", 12),
            SL_BUFFER_TICKS_ES=_env_int("SL_BUFFER_TICKS_ES", 3),
            SL_BUFFER_TICKS_NQ=_env_int("SL_BUFFER_TICKS_NQ", 5),
            SL_BUFFER_TICKS_MGC=_env_int("SL_BUFFER_TICKS_MGC", 5),
            PULLBACK_REQUIRED=_env_bool("PULLBACK_REQUIRED", True),
            PULLBACK_LOOKBACK_BARS=_env_int("PULLBACK_LOOKBACK_BARS", 5),
            PULLBACK_MIN_TICKS_ES=_env_int("PULLBACK_MIN_TICKS_ES", 3),
            PULLBACK_MIN_TICKS_NQ=_env_int("PULLBACK_MIN_TICKS_NQ", 5),
            PULLBACK_MIN_TICKS_MGC=_env_int("PULLBACK_MIN_TICKS_MGC", 5),
            BAR_CONFIRMATION_REQUIRED=_env_bool("BAR_CONFIRMATION_REQUIRED", True),
            BAR_FINISH_STRENGTH_MIN=_env_float("BAR_FINISH_STRENGTH_MIN", 30.0),
            NEAR_LEVEL_MAX_TICKS_ES=_env_int("NEAR_LEVEL_MAX_TICKS_ES", 4),
            NEAR_LEVEL_MAX_TICKS_NQ=_env_int("NEAR_LEVEL_MAX_TICKS_NQ", 8),
            NEAR_LEVEL_MAX_TICKS_MGC=_env_int("NEAR_LEVEL_MAX_TICKS_MGC", 8),
            MAX_TRADES_PER_DAY=_env_int("MAX_TRADES_PER_DAY", 5),
            COOLDOWN_POST_CLOSE_MIN=_env_int("COOLDOWN_POST_CLOSE_MIN", 60),
            COOLDOWN_POST_LOSS_MIN=_env_int("COOLDOWN_POST_LOSS_MIN", 90),
            DAILY_STOP_LOSS_USD=_env_float("DAILY_STOP_LOSS_USD", -200.0),
            DAILY_STOP_WIN_USD=_env_float("DAILY_STOP_WIN_USD", 150.0),
            PARALYSIS_ALERT_DAYS=_env_int("PARALYSIS_ALERT_DAYS", 3),
            PARALYSIS_AUTO_RELAX_DAYS=_env_int("PARALYSIS_AUTO_RELAX_DAYS", 7),
            EOD_LOCKOUT_MINUTES=_env_int("EOD_LOCKOUT_MINUTES", 10),
            NEWS_LOCKOUT_BEFORE_MIN=_env_int("NEWS_LOCKOUT_BEFORE_MIN", 5),
            NEWS_LOCKOUT_AFTER_MIN=_env_int("NEWS_LOCKOUT_AFTER_MIN", 5),
            MAX_SIGNAL_AGE_BARS=_env_int("MAX_SIGNAL_AGE_BARS", 4),
            N_MICROS_DEFAULT=_env_int("N_MICROS_DEFAULT", 1),
            N_MICROS_MAX=_env_int("N_MICROS_MAX", 3),
            POLL_INTERVAL_SEC=_env_int("POLL_INTERVAL_SEC", 10),
            DMP_BAR_MAX_AGE_SEC=_env_int("DMP_BAR_MAX_AGE_SEC", 90),
            LOG_SKIPPED_TRADES=_env_bool("LOG_SKIPPED_TRADES", True),
            SNAPSHOT_INTERVAL_BARS=_env_int("SNAPSHOT_INTERVAL_BARS", 30),
        )
