"""Tests Bot4V2Settings."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from bot4_v2.config.settings import (
    Bot4V2Settings,
    _env_bool,
    _env_float,
    _env_int,
    _env_path,
    _env_str,
    get_settings,
    reset_settings_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_env_bot4v2(monkeypatch):
    """Clear all BOT4V2_* env vars before each test."""
    for key in list(os.environ.keys()):
        if key.startswith("BOT4V2_"):
            monkeypatch.delenv(key, raising=False)
    reset_settings_for_tests()
    yield
    reset_settings_for_tests()


def test_default_values():
    cfg = Bot4V2Settings.from_env()
    assert cfg.trade_account == "Sim5"
    assert cfg.client_name == "MIA_Bot_4_v2"
    assert cfg.cid_prefix == "MIA4V2"
    assert cfg.n_micros_default == 1
    assert cfg.max_trades_per_day == 999
    assert cfg.daily_stop_loss_usd == -99999.0
    assert cfg.daily_stop_win_usd == 99999.0
    assert cfg.shadow_mode_enabled is True
    assert cfg.outcome_horizon_bars == 30
    assert cfg.confirmation_window_bars == 5
    assert cfg.bar_max_age_sec == 90
    assert cfg.poll_interval_sec == 15
    assert cfg.symbols == ("NQ", "ES")
    assert cfg.p_win_min == 0.55
    assert cfg.min_fires_per_day == 5


def test_immutable():
    cfg = Bot4V2Settings.from_env()
    with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
        cfg.trade_account = "OtherAccount"  # type: ignore


def test_env_override_int(monkeypatch):
    monkeypatch.setenv("BOT4V2_MAX_TRADES_PER_DAY", "5")
    cfg = Bot4V2Settings.from_env()
    assert cfg.max_trades_per_day == 5


def test_env_override_float_locale_french(monkeypatch):
    """Verifie support virgule francaise (locale aware)."""
    monkeypatch.setenv("BOT4V2_P_WIN_MIN", "0,65")
    cfg = Bot4V2Settings.from_env()
    assert cfg.p_win_min == 0.65


def test_env_override_bool_true(monkeypatch):
    monkeypatch.setenv("BOT4V2_SHADOW_MODE", "true")
    cfg = Bot4V2Settings.from_env()
    assert cfg.shadow_mode_enabled is True


def test_env_override_bool_false(monkeypatch):
    monkeypatch.setenv("BOT4V2_SHADOW_MODE", "false")
    cfg = Bot4V2Settings.from_env()
    assert cfg.shadow_mode_enabled is False


def test_env_override_invalid_int_fallback(monkeypatch):
    """Valeur invalide -> fallback default (PAS exception)."""
    monkeypatch.setenv("BOT4V2_MAX_TRADES_PER_DAY", "not_a_number")
    cfg = Bot4V2Settings.from_env()
    assert cfg.max_trades_per_day == 999  # default


def test_env_override_invalid_float_fallback(monkeypatch):
    monkeypatch.setenv("BOT4V2_P_WIN_MIN", "not_a_float")
    cfg = Bot4V2Settings.from_env()
    assert cfg.p_win_min == 0.55  # default


def test_env_helpers_int():
    assert _env_int("DOES_NOT_EXIST", 42) == 42


def test_env_helpers_float():
    assert _env_float("DOES_NOT_EXIST", 1.5) == 1.5


def test_env_helpers_bool():
    assert _env_bool("DOES_NOT_EXIST", True) is True
    assert _env_bool("DOES_NOT_EXIST", False) is False


def test_env_helpers_str():
    assert _env_str("DOES_NOT_EXIST", "default_value") == "default_value"


def test_env_helpers_path():
    result = _env_path("DOES_NOT_EXIST", "/tmp/test")
    assert isinstance(result, Path)
    assert result.is_absolute()


def test_get_settings_singleton():
    """get_settings retourne meme instance entre appels."""
    cfg1 = get_settings()
    cfg2 = get_settings()
    assert cfg1 is cfg2


def test_get_settings_singleton_reset_for_tests():
    """reset_settings_for_tests force re-creation."""
    cfg1 = get_settings()
    reset_settings_for_tests()
    cfg2 = get_settings()
    assert cfg1 is not cfg2


def test_paths_absolute():
    """Toutes les paths doivent etre absolues."""
    cfg = Bot4V2Settings.from_env()
    assert cfg.repo_root.is_absolute()
    assert cfg.shadow_logs_dir.is_absolute()
    assert cfg.calibration_models_dir.is_absolute()


def test_env_override_repo_root(monkeypatch, tmp_path):
    """R3 review : verifie que BOT4V2_REPO_ROOT override fonctionne."""
    monkeypatch.setenv("BOT4V2_REPO_ROOT", str(tmp_path))
    cfg = Bot4V2Settings.from_env()
    assert cfg.repo_root == tmp_path.resolve()


def test_env_override_shadow_logs_dir(monkeypatch, tmp_path):
    """Verifie override path shadow_logs_dir."""
    custom = tmp_path / "custom_shadow"
    monkeypatch.setenv("BOT4V2_SHADOW_LOGS_DIR", str(custom))
    cfg = Bot4V2Settings.from_env()
    assert cfg.shadow_logs_dir == custom.resolve()
