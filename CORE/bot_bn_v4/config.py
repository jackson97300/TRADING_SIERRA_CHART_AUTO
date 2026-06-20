"""Configuration Bot BN V4 (Sim3).

Calque sur CORE.bot1_v2.config (frozen dataclass + env override BOTBN_*).
Source unique des magic numbers - PAS de hardcoded ailleurs (anti-pattern
legacy bn_v4_paper.py : TP_CAP_TICKS=200 et autres eparpilles).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(f"BOTBN_{name}")
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(f"BOTBN_{name}")
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(f"BOTBN_{name}")
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    return os.environ.get(f"BOTBN_{name}", default)


@dataclass(frozen=True)
class BotBNV4Config:
    """Configuration immutable Bot BN V4.

    Pattern : `cfg = BotBNV4Config.from_env()` au boot, puis read-only.
    """

    # ============================================================
    # COMPTE / EXEC
    # ============================================================
    # CRITIQUE : Sim3 explicite (Sim3 libre depuis kill Bot 3 v3 16/06).
    # Bot 1 v2 utilise Sim2, Bot 4 utilise Sim4. Pas de collision.
    TRADE_ACCOUNT: str = field(default_factory=lambda: _env_str("TRADE_ACCOUNT", "Sim3"))
    N_MICROS_DEFAULT: int = field(default_factory=lambda: _env_int("N_MICROS_DEFAULT", 1))

    # ============================================================
    # STRATEGIE BN V4 (port spec Jackson 23/05/2026)
    # ============================================================
    GRADE_MIN: str = field(default_factory=lambda: _env_str("GRADE_MIN", "A++"))
    # FIX B.4 audit ULTRATHINK 19/06 (decision Jackson 18/06 souveraine) :
    # Default "both" pour capturer SHORT en regime bearish (cf trade -$967 15/06
    # missed). Memory `project_bot3_bn_v4_audit_20260618.md` : "revenir both
    # directions + open_window elargi data-driven".
    # FIX MINEUR-4 review 2 code-reviewer 20/06 : env var = "DIRECTION_MODE" (sans
    # prefixe BOTBN_). Convention multi-bots assumee : env vars partagees sauf
    # collision. Si necessaire, prefixer plus tard avec migration explicite.
    # Decision Jackson NQ+ES garde les 2 symboles (override trading-strategy NOGO ES).
    DIRECTION_MODE: str = field(default_factory=lambda: _env_str("DIRECTION_MODE", "both"))

    # Filtre open window (Jackson recommande NQ A++)
    REQUIRE_OPEN_WINDOW: bool = field(default_factory=lambda: _env_bool("REQUIRE_OPEN_WINDOW", True))
    # SHORT only : exige trend large baissier (asymetrique)
    REQUIRE_LONG_TREND_ALIGNED: bool = field(default_factory=lambda: _env_bool("REQUIRE_LONG_TREND_ALIGNED", True))

    # Trend recent (gate 1 BN V4)
    TREND_LOOKBACK_BARS: int = field(default_factory=lambda: _env_int("TREND_LOOKBACK_BARS", 60))
    TREND_SLOPE_THRESHOLD: float = field(default_factory=lambda: _env_float("TREND_SLOPE_THRESHOLD", 0.005))

    # Bottom zone (gate 2 BN V4)
    BOTTOM_ZONE_PROXIMITY_PCT: float = field(default_factory=lambda: _env_float("BOTTOM_ZONE_PROXIMITY_PCT", 0.15))
    BOTTOM_ZONE_N_LEVELS_MIN: int = field(default_factory=lambda: _env_int("BOTTOM_ZONE_N_LEVELS_MIN", 2))

    # Edge buy (gate 4 BN V4)
    EDGE_BUY_MIN_ACTIVE: int = field(default_factory=lambda: _env_int("EDGE_BUY_MIN_ACTIVE", 1))

    # Confirmation volume (gate 5 BN V4) - seuils porte depuis spec
    VOLUME_CONFIRM_DELTA_MIN: float = field(default_factory=lambda: _env_float("VOLUME_CONFIRM_DELTA_MIN", 50.0))
    VOLUME_CONFIRM_BIG_DOM_MIN: float = field(default_factory=lambda: _env_float("VOLUME_CONFIRM_BIG_DOM_MIN", 0.6))
    VOLUME_CONFIRM_AGGRESSOR_MIN: float = field(default_factory=lambda: _env_float("VOLUME_CONFIRM_AGGRESSOR_MIN", 0.5))

    # ============================================================
    # SL / TRAILING DOW
    # ============================================================
    SL_INITIAL_BUFFER_TICKS: int = field(default_factory=lambda: _env_int("SL_INITIAL_BUFFER_TICKS", 6))
    SL_NEW_PIVOT_BUFFER_TICKS: int = field(default_factory=lambda: _env_int("SL_NEW_PIVOT_BUFFER_TICKS", 6))
    PULLBACK_DETECT_BARS: int = field(default_factory=lambda: _env_int("PULLBACK_DETECT_BARS", 3))
    TIMEOUT_BARS: int = field(default_factory=lambda: _env_int("TIMEOUT_BARS", 90))

    # Guards SL absurde (anti wick extreme) - alignes bn_v4_engine
    MAX_RISK_TICKS: int = field(default_factory=lambda: _env_int("MAX_RISK_TICKS", 80))
    MIN_RISK_TICKS: int = field(default_factory=lambda: _env_int("MIN_RISK_TICKS", 4))

    # ============================================================
    # SESSIONS (18/06 Jackson : TOUTES sessions en REEL - decision audit Bot 3)
    # ============================================================
    # FIX 18/06 M1 : source unique consommee par SessionGate (via main.py). Avant,
    # SessionGate lisait Bot1V2Config.TRADABLE_SESSIONS (sessions de Bot 2) -> BN V4
    # heritait silencieusement des sessions d'un autre bot. Inclut "us_cash" pour
    # matcher session_segment sierra ; "US" est de toute facon toujours tradable
    # (path is_in_us de SessionGate).
    TRADABLE_SESSIONS: tuple = field(
        default_factory=lambda: ("ASIA", "LONDON", "US", "us_cash")
    )
    # Shadow A/B grade (observation grade A vs A++) : orthogonal aux sessions.
    SHADOW_LOG_GRADES_AB: bool = field(default_factory=lambda: _env_bool("SHADOW_LOG_GRADES_AB", True))
    # Shadow London DESACTIVE (18/06) : toutes sessions tradees en reel -> plus de
    # hypothetical par session. is_shadow_session devient inerte (cf main.py).
    SHADOW_LOG_LONDON: bool = field(default_factory=lambda: _env_bool("SHADOW_LOG_LONDON", False))

    # EOD lockout (minutes avant 16:00 ET)
    EOD_LOCKOUT_MINUTES: int = field(default_factory=lambda: _env_int("EOD_LOCKOUT_MINUTES", 10))

    # ============================================================
    # LIMITS MARK DOUGLAS (souverain 04/06)
    # ============================================================
    MAX_TRADES_PER_DAY: int = field(default_factory=lambda: _env_int("MAX_TRADES_PER_DAY", 5))
    DAILY_STOP_LOSS_USD: float = field(default_factory=lambda: _env_float("DAILY_STOP_LOSS_USD", -200.0))
    DAILY_STOP_WIN_USD: float = field(default_factory=lambda: _env_float("DAILY_STOP_WIN_USD", 150.0))

    # ============================================================
    # POLL / FRESHNESS / WINDOW
    # ============================================================
    DMP_BAR_MAX_AGE_SEC: int = field(default_factory=lambda: _env_int("DMP_BAR_MAX_AGE_SEC", 90))
    POLL_INTERVAL_SEC: int = field(default_factory=lambda: _env_int("POLL_INTERVAL_SEC", 15))
    # Deque(maxlen=N) pour BNV4Engine.detect_setup (besoin lookback 60 et 240)
    SIGNAL_ROLLING_WINDOW_BARS: int = field(default_factory=lambda: _env_int("SIGNAL_ROLLING_WINDOW_BARS", 500))

    # ============================================================
    # DATA SOURCE
    # ============================================================
    SIERRA_ENRICHED_DIR_TEMPLATE: str = field(
        default_factory=lambda: _env_str(
            "SIERRA_DIR", "DATA/live_enriched/sierra/{symbol}",
        )
    )

    # ============================================================
    # HELPERS
    # ============================================================
    def tradable_sessions_for(self, symbol: str) -> tuple:
        # NQ et ES partagent la meme config sessions (toutes en reel).
        return self.TRADABLE_SESSIONS

    @classmethod
    def from_env(cls) -> "BotBNV4Config":
        """Construit depuis env vars (snapshot au boot)."""
        return cls()
