"""Bot 4 v2 settings — Pydantic Settings centralisee.

Source unique de TOUS les magic numbers Bot 4 v2. Anti-pattern v1 :
70 hyperparametres disperses dans scenario_generator + decide + sltp_engine
+ env vars hardcoded -> impossible audit calibration Lopez.

Pattern v2 : frozen dataclass + env override BOT4V2_*. Tous les seuils,
buffers, fenetres, paths -> ici. Caller fait `cfg = get_settings()` au boot
puis read-only.

Garde-fou interdiction (spec section 7) :
- Pas de magic numbers ailleurs dans bot4_v2/
- Pas d'env var lue ailleurs que dans cette classe
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    """Lit env var BOT4V2_{name} en int. Fallback default si absent/invalide."""
    val = os.environ.get(f"BOT4V2_{name}")
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Lit env var BOT4V2_{name} en float. Fallback default si absent/invalide.

    Locale-aware : remplace ',' par '.' (gestion virgule francaise).
    """
    val = os.environ.get(f"BOT4V2_{name}")
    if val is None:
        return default
    try:
        return float(val.replace(",", "."))
    except (TypeError, ValueError, AttributeError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    """Lit env var BOT4V2_{name} en bool. Accepte 1/true/yes/on (case-insensitive)."""
    val = os.environ.get(f"BOT4V2_{name}")
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    """Lit env var BOT4V2_{name} en str. Fallback default si absent."""
    return os.environ.get(f"BOT4V2_{name}", default)


def _env_path(name: str, default: str) -> Path:
    """Lit env var BOT4V2_{name} en Path absolu. Fallback default."""
    return Path(_env_str(name, default)).resolve()


@dataclass(frozen=True)
class Bot4V2Settings:
    """Configuration immutable Bot 4 v2.

    Pattern : `cfg = Bot4V2Settings.from_env()` au boot, puis read-only.
    Tous les fields sont overridables via env var `BOT4V2_{FIELD_NAME}`.
    """

    # ============================================================
    # COMPTE / EXEC
    # ============================================================
    trade_account: str = field(default_factory=lambda: _env_str("TRADE_ACCOUNT", "Sim4"))
    client_name: str = field(default_factory=lambda: _env_str("CLIENT_NAME", "MIA_Bot_4_v2"))
    cid_prefix: str = field(default_factory=lambda: _env_str("CID_PREFIX", "MIA4V2"))

    # ============================================================
    # PATHS (toutes les paths relatives au repo root)
    # ============================================================
    repo_root: Path = field(
        default_factory=lambda: _env_path(
            "REPO_ROOT",
            str(Path(__file__).resolve().parents[2]),
        )
    )
    shadow_logs_dir: Path = field(
        default_factory=lambda: _env_path(
            "SHADOW_LOGS_DIR",
            str(Path(__file__).resolve().parents[2] / "LOGS" / "shadow_scenarios"),
        )
    )
    calibration_models_dir: Path = field(
        default_factory=lambda: _env_path(
            "CALIBRATION_MODELS_DIR",
            str(
                Path(__file__).resolve().parents[2]
                / "DATA"
                / "MODELS"
                / "scenario_calibrators"
            ),
        )
    )

    # ============================================================
    # OBSERVABILITY
    # ============================================================
    # Mode shadow : capture EVERY scenario fire + outcome (sans impact prod)
    shadow_mode_enabled: bool = field(default_factory=lambda: _env_bool("SHADOW_MODE", True))
    # Outcome horizon (bars apres entry pour evaluer TP/SL/timeout)
    outcome_horizon_bars: int = field(
        default_factory=lambda: _env_int("OUTCOME_HORIZON_BARS", 30)
    )
    # Confirmation window state machine (bars N+1 a N+max pour PENDING -> ACTIVE)
    confirmation_window_bars: int = field(
        default_factory=lambda: _env_int("CONFIRMATION_WINDOW_BARS", 5)
    )

    # ============================================================
    # POLL / FRESHNESS
    # ============================================================
    bar_max_age_sec: int = field(default_factory=lambda: _env_int("BAR_MAX_AGE_SEC", 90))
    poll_interval_sec: int = field(default_factory=lambda: _env_int("POLL_INTERVAL_SEC", 15))

    # ============================================================
    # SYMBOLS (NQ / ES uniquement v2 - MGC backlog Phase P3+)
    # ============================================================
    symbols: tuple[str, ...] = field(default_factory=lambda: ("NQ", "ES"))
    n_micros_default: int = field(default_factory=lambda: _env_int("N_MICROS_DEFAULT", 1))

    # ============================================================
    # MARK DOUGLAS (kill switches - 99999 = neutralise paper)
    # ============================================================
    max_trades_per_day: int = field(default_factory=lambda: _env_int("MAX_TRADES_PER_DAY", 999))
    daily_stop_loss_usd: float = field(
        default_factory=lambda: _env_float("DAILY_STOP_LOSS_USD", -99999.0)
    )
    daily_stop_win_usd: float = field(
        default_factory=lambda: _env_float("DAILY_STOP_WIN_USD", 99999.0)
    )

    # ============================================================
    # SCENARIO REGISTRY (P3+)
    # ============================================================
    # Seuil minimum P(win) calibre pour scenario tradable (post-calibration P6)
    p_win_min: float = field(default_factory=lambda: _env_float("P_WIN_MIN", 0.55))
    # Densite minimum fires/jour pour scenario actif (sinon DROP)
    min_fires_per_day: int = field(
        default_factory=lambda: _env_int("MIN_FIRES_PER_DAY", 5)
    )

    @classmethod
    def from_env(cls) -> Bot4V2Settings:
        """Construit settings depuis env vars (snapshot au boot)."""
        return cls()


_SINGLETON: Bot4V2Settings | None = None


def get_settings() -> Bot4V2Settings:
    """Retourne settings singleton (cache premier appel)."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = Bot4V2Settings.from_env()
    return _SINGLETON


def reset_settings_for_tests() -> None:
    """Reset singleton pour tests (force re-read env vars)."""
    global _SINGLETON
    _SINGLETON = None
