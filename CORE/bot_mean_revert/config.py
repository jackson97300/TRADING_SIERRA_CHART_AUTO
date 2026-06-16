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
    # Threshold % au-dela du SD level (0.0 = just touch)
    SD_THRESHOLD_PCT: float = _env_float("SD_THRESHOLD_PCT", 0.0)
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
    # ES : US only (sweep best)
    TRADABLE_SESSIONS_ES: tuple = field(
        default_factory=lambda: _env_tuple("TRADABLE_SESSIONS_ES", ("US",))
    )
    # NQ : Asia only en dry-eval (Jackson 16/06 audit empirique)
    TRADABLE_SESSIONS_NQ: tuple = field(
        default_factory=lambda: _env_tuple("TRADABLE_SESSIONS_NQ", ("ASIA",))
    )
    # Skip pre-open US 11:30-13:30 UTC (bruit)
    SKIP_PREOPEN_US: bool = _env_bool("SKIP_PREOPEN_US", True)

    # ============================================================
    # DAILY LIMITS Mark Douglas
    # ============================================================
    MAX_TRADES_PER_DAY: int = _env_int("MAX_TRADES_PER_DAY", 5)
    DAILY_STOP_LOSS_USD: float = _env_float("DAILY_STOP_LOSS_USD", -200.0)
    DAILY_STOP_WIN_USD: float = _env_float("DAILY_STOP_WIN_USD", 150.0)

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
    DRY_EVAL_NQ: bool = _env_bool("DRY_EVAL_NQ", True)

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
            SD_THRESHOLD_PCT=_env_float("SD_THRESHOLD_PCT", 0.0),
            RVOL_ZSCORE_MIN=_env_float("RVOL_ZSCORE_MIN", 0.0),
            REQUIRE_EXHAUSTION=_env_bool("REQUIRE_EXHAUSTION", False),
            REQUIRE_DELTA_DIRECTION=_env_bool("REQUIRE_DELTA_DIRECTION", False),
            RR=_env_float("RR", 1.5),
            SL_TICKS_ES=_env_int("SL_TICKS_ES", 20),
            SL_TICKS_NQ=_env_int("SL_TICKS_NQ", 35),
            SL_TICKS_MGC=_env_int("SL_TICKS_MGC", 50),
            COOLDOWN_BARS=_env_int("COOLDOWN_BARS", 30),
            REGIME_FILTER_MODE_ES=os.environ.get("BOTMR_REGIME_FILTER_MODE_ES", "trend_align_es"),
            REGIME_FILTER_MODE_NQ=os.environ.get("BOTMR_REGIME_FILTER_MODE_NQ", "contrarian_nq"),
            VIX_MIN_FOR_SHORT=_env_float("VIX_MIN_FOR_SHORT", 20.0),
            NQ_TREND_DAY_MAX=_env_float("NQ_TREND_DAY_MAX", 0.65),
            TRADABLE_SESSIONS_ES=_env_tuple("TRADABLE_SESSIONS_ES", ("US",)),
            TRADABLE_SESSIONS_NQ=_env_tuple("TRADABLE_SESSIONS_NQ", ("ASIA",)),
            SKIP_PREOPEN_US=_env_bool("SKIP_PREOPEN_US", True),
            MAX_TRADES_PER_DAY=_env_int("MAX_TRADES_PER_DAY", 5),
            DAILY_STOP_LOSS_USD=_env_float("DAILY_STOP_LOSS_USD", -200.0),
            DAILY_STOP_WIN_USD=_env_float("DAILY_STOP_WIN_USD", 150.0),
            DMP_BAR_MAX_AGE_SEC=_env_int("DMP_BAR_MAX_AGE_SEC", 90),
            POLL_INTERVAL_SEC=_env_int("POLL_INTERVAL_SEC", 15),
            SIERRA_ENRICHED_DIR_TEMPLATE=os.environ.get(
                "BOTMR_SIERRA_DIR", "DATA/live_enriched/sierra/{symbol}",
            ),
            DRY_EVAL_NQ=_env_bool("DRY_EVAL_NQ", True),
        )
