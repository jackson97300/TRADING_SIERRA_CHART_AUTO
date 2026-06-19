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
    """Bar LONG qualite Phase 4 : dir_score>=3 + near_level + bonus 3/3 + mur SL.

    dir_score derive de cvd/delta/vwap_d_side/momentum (PAS bull_pts injecte,
    pour tester le vrai chemin _compute_pts). near_level : support dist_vwap_d=-2.
    """
    base = {
        "ts": 1781000000000,
        "sym": "ES",
        "is_cash_session": True,  # setup qualite = RTH (gate vwap_d overnight)
        "close": 7600.0,
        "open": 7599.0,
        "high": 7600.5,
        # dir_score = +4 (cvd+delta+vwap+momentum)
        "cvd_day_dir": 1, "delta_day_dir": 1, "vwap_d_side": 1,
        "momentum_5b": 3.0, "momentum_3b": 1.5,
        # diagnostic
        "bias_score": 0.6, "bias_label": "BULLISH",
        "mtf_bulls": 4, "mtf_bears": 0,
        # BONUS
        "rvol": 1.5,
        "dist_vwap_d": -2,  # support 2t sous le prix = AU niveau pour LONG (fix D-2)
        "sess_high": 7602.0,
        "finish_strength": 5.0,
        "bar_color_up": 1,
        # Vetos OFF
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
    """Bar qualite Phase 4 + mur valide -> tradable."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar()
    decision = engine.evaluate(bar)
    assert decision.tradable is True, (
        f"Expected tradable. skip={decision.skip_reason} bonus={decision.stars_count}"
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


def test_cluster_evaluate_skip_attendre():
    """dir_score neutre -> ATTENDRE = skip (Phase 4 : conseil_action ignore)."""
    engine = ClusterEngine(symbol="ES")
    # bull=1 (cvd) bear=1 (delta) dir_score=0 -> ATTENDRE
    bar = _make_quality_bar(
        cvd_day_dir=1, delta_day_dir=-1, vwap_d_side=0,
        momentum_5b=0.0, momentum_3b=0.0,
    )
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert "ATTENDRE" in decision.skip_reason


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


def test_cluster_propagates_direction_on_core_skip():
    """F-1 : un skip CORE (near_level) conserve la direction du mirror (pas None)."""
    engine = ClusterEngine(symbol="ES")
    # Eloigne tous les niveaux -> NOT_AT_SUPPORT, mais direction LONG connue.
    bar = _make_quality_bar(dist_vwap_d=20)
    for k in list(bar.keys()):
        if k.startswith("dist_") and k != "dist_vwap_d":
            bar.pop(k)
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert "NOT_AT_SUPPORT" in decision.skip_reason
    assert decision.direction == "LONG", (
        f"direction doit etre propagee depuis mirror, got {decision.direction}"
    )


def test_cluster_attendre_keeps_direction_none():
    """Anti-regression F-1 : ATTENDRE (pas de direction mirror) garde direction=None."""
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar(
        cvd_day_dir=1, delta_day_dir=-1, vwap_d_side=0,
        momentum_5b=0.0, momentum_3b=0.0,
    )
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert decision.direction is None


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
    assert "ENTRY_PRICE_INVALID" in decision.skip_reason or "NOT_AT_SUPPORT" in decision.skip_reason


def test_cluster_skip_no_sl_wall():
    """Verdict ready OK mais aucun mur SL valide -> SLTP_REJECT.

    On retire UNIQUEMENT le mur SL du fixture (vwap_d_sd1d), en gardant le
    verdict qualite intact, pour atteindre reellement l'etape sl_tp.
    """
    engine = ClusterEngine(symbol="ES")
    bar = _make_quality_bar()
    bar.pop("vwap_d_sd1d", None)  # seul mur SL LONG du fixture
    decision = engine.evaluate(bar)
    assert decision.tradable is False
    assert "SLTP_REJECT" in decision.skip_reason
