"""Tests config Bot MR."""
from __future__ import annotations

from CORE.bot_mean_revert.config import BotMRConfig


def test_default_config_values():
    cfg = BotMRConfig()
    assert cfg.TRADE_ACCOUNT == "Sim1"
    assert cfg.SD_LEVEL == "sd3"
    assert cfg.RR == 1.5
    assert cfg.SL_TICKS_ES == 20
    assert cfg.SL_TICKS_NQ == 35
    assert cfg.MAX_TRADES_PER_DAY == 5
    assert cfg.DAILY_STOP_LOSS_USD == -200.0
    assert cfg.DAILY_STOP_WIN_USD == 150.0
    assert cfg.REGIME_FILTER_MODE_ES == "trend_align_es"
    assert cfg.REGIME_FILTER_MODE_NQ == "contrarian_nq"
    assert cfg.SKIP_PREOPEN_US is True
    assert cfg.DRY_EVAL_NQ is True
    # Helpers
    assert cfg.sl_ticks("ES") == 20
    assert cfg.sl_ticks("NQ") == 35
    assert cfg.sl_ticks("MGC") == 50
    assert cfg.regime_filter_mode("ES") == "trend_align_es"
    assert cfg.regime_filter_mode("NQ") == "contrarian_nq"
    assert cfg.tradable_sessions("ES") == ("US",)
    assert cfg.tradable_sessions("NQ") == ("ASIA",)
    assert cfg.is_dry_eval("NQ") is True
    assert cfg.is_dry_eval("ES") is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("BOTMR_RR", "2.0")
    monkeypatch.setenv("BOTMR_SL_TICKS_ES", "15")
    monkeypatch.setenv("BOTMR_DRY_EVAL_NQ", "false")
    monkeypatch.setenv("BOTMR_TRADE_ACCOUNT", "Sim4")
    cfg = BotMRConfig.from_env()
    assert cfg.RR == 2.0
    assert cfg.SL_TICKS_ES == 15
    assert cfg.DRY_EVAL_NQ is False
    assert cfg.TRADE_ACCOUNT == "Sim4"
    assert cfg.is_dry_eval("NQ") is False
