"""Tests config Bot BN V4."""
from __future__ import annotations

import os
from unittest.mock import patch

from CORE.bot_bn_v4.config import BotBNV4Config


def test_default_config():
    """Defaults critiques : Sim3 + A++ + 1 micro + 5 trades/jour."""
    cfg = BotBNV4Config.from_env()
    assert cfg.TRADE_ACCOUNT == "Sim3", "Sim3 obligatoire (anti-collision Bot 1 v2 Sim2)"
    assert cfg.GRADE_MIN == "A++", "Grade A++ par defaut (Jackson 23/05 PF 4.66)"
    assert cfg.N_MICROS_DEFAULT == 1
    assert cfg.MAX_TRADES_PER_DAY == 5
    assert cfg.DAILY_STOP_LOSS_USD == -200.0
    assert cfg.DAILY_STOP_WIN_USD == 150.0
    assert cfg.SL_INITIAL_BUFFER_TICKS == 6
    assert cfg.PULLBACK_DETECT_BARS == 3
    assert cfg.TIMEOUT_BARS == 90
    assert cfg.REQUIRE_OPEN_WINDOW is True
    assert cfg.REQUIRE_LONG_TREND_ALIGNED is True


def test_env_override():
    """Surcharge via env vars BOTBN_* fonctionne."""
    with patch.dict(os.environ, {
        "BOTBN_TRADE_ACCOUNT": "Sim9",
        "BOTBN_GRADE_MIN": "B",
        "BOTBN_MAX_TRADES_PER_DAY": "10",
        "BOTBN_DAILY_STOP_LOSS_USD": "-500.0",
        "BOTBN_REQUIRE_OPEN_WINDOW": "false",
    }):
        cfg = BotBNV4Config.from_env()
        assert cfg.TRADE_ACCOUNT == "Sim9"
        assert cfg.GRADE_MIN == "B"
        assert cfg.MAX_TRADES_PER_DAY == 10
        assert cfg.DAILY_STOP_LOSS_USD == -500.0
        assert cfg.REQUIRE_OPEN_WINDOW is False


def test_tradable_sessions_helper():
    cfg = BotBNV4Config.from_env()
    assert cfg.tradable_sessions_for("NQ") == ("US",)
    assert cfg.tradable_sessions_for("ES") == ("US",)
