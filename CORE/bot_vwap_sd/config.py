"""Configuration Bot 5 VWAP-SD (Sim3 emplacement).

Source unique des magic numbers - PAS de hardcoded ailleurs.
Convention : env override via BOTVWAPSD_*.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(f"BOTVWAPSD_{name}")
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(f"BOTVWAPSD_{name}")
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(f"BOTVWAPSD_{name}")
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    return os.environ.get(f"BOTVWAPSD_{name}", default)


@dataclass(frozen=True)
class VwapSdConfig:
    """Configuration immutable Bot 5 VWAP-SD."""

    # ============================================================
    # COMPTE / EXEC
    # ============================================================
    TRADE_ACCOUNT: str = field(default_factory=lambda: _env_str("TRADE_ACCOUNT", "Sim3"))
    N_MICROS_DEFAULT: int = field(default_factory=lambda: _env_int("N_MICROS_DEFAULT", 1))

    # ============================================================
    # SETUPS ACTIFS (verdict empirique 8j live 20/06 — SEUL A tient)
    # ============================================================
    # Setup A NQ SHORT (champion + filtre confluence niveau)
    # Empirique 8j : sans filtre PF 2.26 / avec filtre confluence 500t PF 26.00
    # Decouverte 20/06 : sans niveau resistance au-dessus PROCHE = trader au milieu
    # de nulle part. Filtre =>1 niveau resistance au-dessus dans 500 ticks NQ.
    SETUP_A_ENABLED: bool = field(default_factory=lambda: _env_bool("SETUP_A_ENABLED", True))
    SETUP_A_TP_TICKS: int = field(default_factory=lambda: _env_int("SETUP_A_TP_TICKS", 80))
    SETUP_A_SL_TICKS: int = field(default_factory=lambda: _env_int("SETUP_A_SL_TICKS", 40))
    # Filtre confluence niveau institutionnel au-dessus (resistance pour SHORT)
    # Threshold ticks NQ (1 tick = 0.25 points)
    SETUP_A_CONFLUENCE_ENABLED: bool = field(default_factory=lambda: _env_bool("SETUP_A_CONFLUENCE_ENABLED", True))
    SETUP_A_CONFLUENCE_THRESHOLD_TICKS: int = field(default_factory=lambda: _env_int("SETUP_A_CONFLUENCE_THRESHOLD_TICKS", 500))

    # Filtre anti-trend-day (decouverte empirique 20/06) :
    # Sur 8j NQ, jour 12/06 etait trend day directionnel (ib_atr=2.11, slope+35,
    # delta_day+454) = 1 seul SL. Skip Setup A SHORT si volatility expansion
    # signale = IB > N ATR.
    # Verdict empirique : ib_atr<2.0 = 8/10 trades, WR 87.5%, PF 13.00 (+$252)
    # vs baseline 10/10 WR 80% PF 7.43.
    SETUP_A_ANTITREND_ENABLED: bool = field(default_factory=lambda: _env_bool("SETUP_A_ANTITREND_ENABLED", True))
    SETUP_A_MAX_IB_RANGE_ATR: float = field(default_factory=lambda: _env_float("SETUP_A_MAX_IB_RANGE_ATR", 2.0))

    # Setup B NQ LONG - DESACTIVE par defaut (verdict empirique : PF 0.52, -$304/8j)
    # Market-analyst hier disait PF 2.16 mais simulation avec cooldown 5min montre
    # EDGE INVERSE. Garde possibilite override env si Jackson veut tester.
    SETUP_B_ENABLED: bool = field(default_factory=lambda: _env_bool("SETUP_B_ENABLED", False))
    SETUP_B_SHADOW: bool = field(default_factory=lambda: _env_bool("SETUP_B_SHADOW", True))
    SETUP_B_TP_TICKS: int = field(default_factory=lambda: _env_int("SETUP_B_TP_TICKS", 40))
    SETUP_B_SL_TICKS: int = field(default_factory=lambda: _env_int("SETUP_B_SL_TICKS", 20))

    # Setup C ES LONG - DESACTIVE par defaut (verdict empirique : PF 1.18, marginal)
    # Market-analyst hier disait PF 1.84 mais simulation montre +$42 sur 35 trades.
    # Trop marginal pour deploy. Mode SHADOW collecte pour reevaluation 30j.
    SETUP_C_ENABLED: bool = field(default_factory=lambda: _env_bool("SETUP_C_ENABLED", False))
    SETUP_C_SHADOW: bool = field(default_factory=lambda: _env_bool("SETUP_C_SHADOW", True))
    SETUP_C_TP_TICKS: int = field(default_factory=lambda: _env_int("SETUP_C_TP_TICKS", 16))
    SETUP_C_SL_TICKS: int = field(default_factory=lambda: _env_int("SETUP_C_SL_TICKS", 8))
    SETUP_C_MIN_SLOPE: float = field(default_factory=lambda: _env_float("SETUP_C_MIN_SLOPE", 0.0))

    # Setup D ES SHORT - SHADOW (n=12 insuffisant statistiquement)
    SETUP_D_ENABLED: bool = field(default_factory=lambda: _env_bool("SETUP_D_ENABLED", False))
    SETUP_D_SHADOW: bool = field(default_factory=lambda: _env_bool("SETUP_D_SHADOW", True))
    SETUP_D_TP_TICKS: int = field(default_factory=lambda: _env_int("SETUP_D_TP_TICKS", 12))
    SETUP_D_SL_TICKS: int = field(default_factory=lambda: _env_int("SETUP_D_SL_TICKS", 6))

    # ============================================================
    # TIMING / COOLDOWN
    # ============================================================
    # Skip 15 minutes apres open RTH (anti-volatility open Mark Douglas)
    SKIP_FIRST_MINUTES_RTH: int = field(default_factory=lambda: _env_int("SKIP_FIRST_MINUTES_RTH", 15))
    # Cooldown 5 minutes apres entry OR exit (anti-overlap)
    COOLDOWN_MINUTES: int = field(default_factory=lambda: _env_int("COOLDOWN_MINUTES", 5))

    # ============================================================
    # SESSIONS (RTH US uniquement)
    # ============================================================
    TRADABLE_SESSIONS: tuple[str, ...] = field(
        default_factory=lambda: ("US", "us_cash")
    )
    EOD_LOCKOUT_MINUTES: int = field(default_factory=lambda: _env_int("EOD_LOCKOUT_MINUTES", 10))

    # ============================================================
    # LIMITS MARK DOUGLAS (souverain 04/06)
    # ============================================================
    MAX_TRADES_PER_DAY: int = field(default_factory=lambda: _env_int("MAX_TRADES_PER_DAY", 5))
    DAILY_STOP_LOSS_USD: float = field(default_factory=lambda: _env_float("DAILY_STOP_LOSS_USD", -200.0))
    DAILY_STOP_WIN_USD: float = field(default_factory=lambda: _env_float("DAILY_STOP_WIN_USD", 150.0))

    # ============================================================
    # POLL / FRESHNESS
    # ============================================================
    DMP_BAR_MAX_AGE_SEC: int = field(default_factory=lambda: _env_int("DMP_BAR_MAX_AGE_SEC", 90))
    POLL_INTERVAL_SEC: int = field(default_factory=lambda: _env_int("POLL_INTERVAL_SEC", 15))

    # ============================================================
    # DATA SOURCE
    # ============================================================
    SIERRA_ENRICHED_DIR_TEMPLATE: str = field(
        default_factory=lambda: _env_str(
            "SIERRA_DIR", "DATA/live_enriched/sierra/{symbol}",
        )
    )

    # ============================================================
    # SYMBOLS
    # ============================================================
    SYMBOLS: tuple[str, ...] = field(default_factory=lambda: ("NQ", "ES"))

    @classmethod
    def from_env(cls) -> "VwapSdConfig":
        """Construit depuis env vars (snapshot au boot)."""
        return cls()
