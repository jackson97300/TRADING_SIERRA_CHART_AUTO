"""Tests RegimeGate Bot MR."""
from __future__ import annotations

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.gates.regime import RegimeGate


def test_es_trend_align_long_requires_positive_slope():
    cfg = BotMRConfig()
    gate = RegimeGate(cfg)
    # LONG slope_30 > 0 -> allowed
    v = gate.check("ES", "LONG", slope_30=0.05, vix=22.0)
    assert v.allowed is True
    # LONG slope_30 <= 0 -> blocked
    v = gate.check("ES", "LONG", slope_30=-0.01, vix=22.0)
    assert v.allowed is False
    assert "TREND_ALIGN_LONG_SLOPE_NEG" in v.reason


def test_es_trend_align_short_requires_negative_slope_and_high_vix():
    cfg = BotMRConfig()
    gate = RegimeGate(cfg)
    # SHORT slope<0 + VIX>20 -> allowed
    v = gate.check("ES", "SHORT", slope_30=-0.03, vix=25.0)
    assert v.allowed is True
    # SHORT slope>0 -> blocked
    v = gate.check("ES", "SHORT", slope_30=0.02, vix=25.0)
    assert v.allowed is False
    assert "TREND_ALIGN_SHORT_SLOPE_POS" in v.reason
    # SHORT slope<0 mais VIX trop bas -> blocked
    v = gate.check("ES", "SHORT", slope_30=-0.03, vix=15.0)
    assert v.allowed is False
    assert "VIX_TOO_LOW_FOR_SHORT" in v.reason


def test_nq_contrarian_long_requires_negative_slope():
    cfg = BotMRConfig()
    gate = RegimeGate(cfg)
    v = gate.check("NQ", "LONG", slope_30=-0.04)
    assert v.allowed is True
    v = gate.check("NQ", "LONG", slope_30=0.04)
    assert v.allowed is False
    assert "CONTRA_LONG_SLOPE_POS" in v.reason


def test_nq_contrarian_short_requires_low_trend_day():
    cfg = BotMRConfig()
    gate = RegimeGate(cfg)
    # SHORT slope_30>0 + trend_day < 0.65 -> allowed
    v = gate.check("NQ", "SHORT", slope_30=0.02, trend_day_score=0.3)
    assert v.allowed is True
    # SHORT trend_day > 0.65 -> blocked
    v = gate.check("NQ", "SHORT", slope_30=0.02, trend_day_score=0.8)
    assert v.allowed is False
    assert "NQ_TREND_DAY_TOO_HIGH" in v.reason
