"""Tests cluster.py ClusterEngine.

Smoke tests :
  - evaluate() integre verdict + sl_tp + cooldown + dedup
  - register_trade() + dedup
  - cooldown anti-revenge
"""
from __future__ import annotations

import time

import pytest

from CORE.bot1_v2.cluster import ClusterEngine, ClusterDecision
from CORE.bot1_v2.config import Bot1V2Config


def _make_quality_bar(**overrides):
    """Bar quality 7/7 etoiles + mur SL valide proche."""
    base = {
        "ts": 1781000000000,
        "sym": "ES",
        "close": 7600.0,
        "open": 7599.0,
        "high": 7600.5,
        "conseil_action": "ACHAT",
        "bull_pts": 6, "bear_pts": 0,
        "bias_score": 0.6, "bias_label": "BULLISH",
        "mtf_bulls": 4, "mtf_bears": 0,
        "cvd_day_dir": 1, "delta_day_dir": 1, "vwap_d_side": 1,
        "rvol": 1.5,
        "momentum_5b": 3.0, "momentum_3b": 1.5,
        "dist_vwap_d": 2,
        "sess_high": 7602.0,
        "finish_strength": 5.0,
        "bar_color_up": 1,
        "ctx_climax_signal": False,
        "rvol_zscore": 0.5,
        "gamma_block_long": False, "gamma_block_short": False,
        "vix_level": 17.0,
        # Mur SL valide : VWAP D SD1 SOUS entry (LONG)
        "vwap_d_sd1d": 7598.0,  # = entry - 2 points = 8 ticks
    }
    base.update(overrides)
    return base


def test_cluster_evaluate_tradable_quality_bar():
    """Bar qualite 7/7 + mur valide -> tradable."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar()
    decision = engine.evaluate(bar)
    assert decision.tradable is True, (
        f"Expected tradable. skip={decision.skip_reason} stars={decision.stars_count}"
    )
    assert decision.direction == "LONG"
    assert decision.entry_price == 7600.0
    assert decision.sl_price > 0
    assert decision.tp_price > decision.entry_price  # LONG TP > entry


def test_cluster_evaluate_skip_climax():
    """Climax veto = skip non-tradable."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar(ctx_climax_signal=True)
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert "CLIMAX" in decision.skip_reason


def test_cluster_evaluate_skip_no_dashboard_action():
    """ATTENDRE = skip."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar(conseil_action="ATTENDRE")
    decision = engine.evaluate(bar)
    assert decision.tradable is False


def test_cluster_dedup_signal_id():
    """Meme signal_id = skip 2eme evaluation."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar()
    d1 = engine.evaluate(bar)
    assert d1.tradable is True
    # Register le trade
    engine.register_trade(d1.signal_id)
    # 2eme evaluation meme bar = dedup
    d2 = engine.evaluate(bar)
    assert d2.tradable is False
    assert "SIGNAL_ALREADY_TRADED" in d2.skip_reason


def test_cluster_cooldown_blocks():
    """Cooldown actif = skip meme si verdict OK."""
    engine = ClusterEngine(symbol="ES")
    engine.cooldown_until_ts = time.time() + 60  # 60s dans le futur
    bar = _make_quality_bar()
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert "COOLDOWN" in decision.skip_reason


def test_cluster_register_close_sets_cooldown():
    """register_close(was_loss=True) = cooldown plus strict."""
    engine = ClusterEngine(symbol="ES")
    now = time.time()
    engine.register_close(exit_ts=now, was_loss=True)
    # Cooldown should be COOLDOWN_POST_LOSS_MIN (default 90) minutes from now
    expected = now + engine.cfg.COOLDOWN_POST_LOSS_MIN * 60
    assert abs(engine.cooldown_until_ts - expected) < 1.0


def test_cluster_skip_invalid_entry_price():
    """close <= 0 = ENTRY_PRICE_INVALID."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar(close=0)
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert "ENTRY_PRICE_INVALID" in decision.skip_reason or "NOT_AT_LEVEL" in decision.skip_reason


def test_cluster_skip_no_sl_wall():
    """Pas de mur SL = SLTP_REJECT."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar()
    # Retire tous les murs candidats LONG (en-dessous entry)
    for k in list(bar.keys()):
        v = bar.get(k)
        if isinstance(v, (int, float)) and 0 < v < 7600.0:
            bar.pop(k)
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert "SLTP_REJECT" in decision.skip_reason or "NOT_AT_LEVEL" in decision.skip_reason
