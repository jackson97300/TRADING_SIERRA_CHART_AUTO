"""Tests RegimeGate - gamma/VIX/news filters."""
from __future__ import annotations

from CORE.bot_bn_v4.config import BotBNV4Config
from CORE.bot_bn_v4.gates.regime import RegimeGate


def test_gamma_block_long_rejected():
    """mq_gamma_block_long=True -> reject LONG."""
    gate = RegimeGate(BotBNV4Config.from_env())
    bar = {"mq_gamma_block_long": True, "vix_level": 20.0}
    v = gate.check_allow_entry(bar, "long")
    assert v.allowed is False
    assert "GAMMA_BLOCK_LONG" in v.skip_reason


def test_vix_extreme_rejected():
    """VIX > 35 -> reject."""
    gate = RegimeGate(BotBNV4Config.from_env())
    bar = {"vix_level": 40.0}
    v = gate.check_allow_entry(bar, "long")
    assert v.allowed is False
    assert "VIX_EXTREME" in v.skip_reason


def test_news_lockout_rejected():
    """is_news_5m=True -> reject."""
    gate = RegimeGate(BotBNV4Config.from_env())
    bar = {"is_news_5m": True}
    v = gate.check_allow_entry(bar, "long")
    assert v.allowed is False
    assert "NEWS_LOCKOUT" in v.skip_reason


def test_allowed_normal_conditions():
    """Pas de gamma/VIX/news -> allowed."""
    gate = RegimeGate(BotBNV4Config.from_env())
    bar = {"vix_level": 18.0, "vwap_slope_10": -0.015}
    v = gate.check_allow_entry(bar, "long")
    assert v.allowed is True
    # vwap_slope_10 < -0.005 -> proposed = long
    assert v.proposed_direction == "long"
