"""Tests RegimeClassifier (Phase 3 18/06 - vote majoritaire 3 signaux).

Couvre :
  - Defaults config (REGIME_CLASSIFIER_ENABLED=True, ATR_ZSCORE_PANIC=2.5)
  - Signal 1 (slope) : seuils per-symbole ES/NQ/MGC
  - Signal 2 (swing) : ratio bars_since_high / bars_since_low
  - Signal 3 (panic) : VIX absolu + ATR z-score
  - Vote majoritaire : RANGE / TREND / PANIC priority
  - allows_direction matrice complete

Reference design : carnage ES 18/06 -$1025 broker E-mini sur 4 LONGs en
descente. Ces tests garantissent que le classifier aurait detecte le regime
TREND_DOWN et bloque les LONGs (au moins via slope_30 si swing/panic
neutres).
"""
from __future__ import annotations

import os

import pytest

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.gates.regime_classifier import (
    REGIME_PANIC,
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
    RegimeClassifier,
    RegimeVerdict,
)


# ============================================================
# Config defaults
# ============================================================


def test_default_enabled_true():
    """REGIME_CLASSIFIER_ENABLED True par defaut + ATR_ZSCORE_PANIC=2.5."""
    cfg = BotMRConfig()
    assert cfg.REGIME_CLASSIFIER_ENABLED is True
    assert cfg.ATR_ZSCORE_PANIC == 2.5


def test_env_override_classifier_disabled():
    """BOTMR_REGIME_CLASSIFIER_ENABLED=0 -> disabled via from_env."""
    os.environ["BOTMR_REGIME_CLASSIFIER_ENABLED"] = "0"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.REGIME_CLASSIFIER_ENABLED is False
    finally:
        del os.environ["BOTMR_REGIME_CLASSIFIER_ENABLED"]


# ============================================================
# Signal 1 : SLOPE-BASED (per-symbole)
# ============================================================


def test_signal_slope_es_bearish():
    """slope=-1.0 sur ES (seuil -0.5) -> TREND_DOWN."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vwap_slope_30": -1.0}
    assert clf._signal_slope(bar, "ES") == REGIME_TREND_DOWN


def test_signal_slope_es_bullish():
    """slope=+1.0 sur ES (seuil +0.5) -> TREND_UP."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vwap_slope_30": 1.0}
    assert clf._signal_slope(bar, "ES") == REGIME_TREND_UP


def test_signal_slope_es_range():
    """slope=0.0 sur ES (|0| < 0.5) -> RANGE."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vwap_slope_30": 0.0}
    assert clf._signal_slope(bar, "ES") == REGIME_RANGE


def test_signal_slope_nq_seuils_proportionnes():
    """slope=-1.0 sur NQ (seuil -3.0) -> RANGE (pas TREND_DOWN car NQ stdev 6x).

    Test critique : seuils per-symbole evitent faux positifs NQ.
    """
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vwap_slope_30": -1.0}
    assert clf._signal_slope(bar, "NQ") == REGIME_RANGE


def test_signal_slope_nq_bearish_strong():
    """slope=-4.0 sur NQ (seuil -3.0) -> TREND_DOWN."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vwap_slope_30": -4.0}
    assert clf._signal_slope(bar, "NQ") == REGIME_TREND_DOWN


def test_signal_slope_absent_field():
    """slope_30 absent -> RANGE (fail-safe neutre)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {}
    assert clf._signal_slope(bar, "ES") == REGIME_RANGE


def test_signal_slope_non_castable():
    """slope_30=string non-numerique -> RANGE (fail-safe)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vwap_slope_30": "NaN_string"}
    assert clf._signal_slope(bar, "ES") == REGIME_RANGE


# ============================================================
# Signal 2 : SWING STRUCTURE (ratio)
# ============================================================


def test_signal_swing_ratio_lower_lows():
    """bars_since_high=50, bars_since_low=10 -> ratio 5.0 > 2.0 = TREND_DOWN."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "bars_since_last_swing_high": 50,
        "bars_since_last_swing_low": 10,
    }
    assert clf._signal_swing(bar) == REGIME_TREND_DOWN


def test_signal_swing_ratio_higher_highs():
    """bars_since_high=10, bars_since_low=50 -> ratio 0.2 < 0.5 = TREND_UP."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "bars_since_last_swing_high": 10,
        "bars_since_last_swing_low": 50,
    }
    assert clf._signal_swing(bar) == REGIME_TREND_UP


def test_signal_swing_ratio_range():
    """bars_since_high=15, bars_since_low=20 -> ratio 0.75 in [0.5, 2.0] = RANGE."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "bars_since_last_swing_high": 15,
        "bars_since_last_swing_low": 20,
    }
    assert clf._signal_swing(bar) == REGIME_RANGE


def test_signal_swing_absent_fields():
    """Fields absents -> RANGE (fail-safe)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {}
    assert clf._signal_swing(bar) == REGIME_RANGE


def test_signal_swing_zero_division_safe():
    """bars_since_low=0 (swing instantane) -> RANGE (eviter ZeroDivisionError)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "bars_since_last_swing_high": 0,
        "bars_since_last_swing_low": 73,
    }
    assert clf._signal_swing(bar) == REGIME_RANGE


def test_signal_swing_both_zero():
    """Les deux fields a 0 -> RANGE."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "bars_since_last_swing_high": 0,
        "bars_since_last_swing_low": 0,
    }
    assert clf._signal_swing(bar) == REGIME_RANGE


# ============================================================
# Signal 3 : PANIC DETECTION
# ============================================================


def test_signal_panic_vix():
    """vix_level=35 > VIX_ABS_PANIC=30 -> PANIC."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vix_level": 35.0}
    assert clf._signal_panic(bar) == REGIME_PANIC


def test_signal_panic_atr_zscore():
    """ctx_atr_zscore=3.0 > ATR_ZSCORE_PANIC=2.5 -> PANIC."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"ctx_atr_zscore": 3.0, "vix_level": 15.0}
    assert clf._signal_panic(bar) == REGIME_PANIC


def test_signal_panic_neither():
    """VIX 20 + ATR z 1.5 = pas de panic -> RANGE."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {"vix_level": 20.0, "ctx_atr_zscore": 1.5}
    assert clf._signal_panic(bar) == REGIME_RANGE


def test_signal_panic_atr_absent_fallback_vix_seul():
    """ctx_atr_zscore ABSENT (cas live actuel) -> verifie VIX seul.

    Test critique : ce field n'est pas dans sierra_enriched 18/06.
    Le classifier doit fonctionner sans, en lisant vix_level uniquement.
    """
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    # VIX panic seul
    assert clf._signal_panic({"vix_level": 35.0}) == REGIME_PANIC
    # VIX safe seul (pas de field atr)
    assert clf._signal_panic({"vix_level": 18.0}) == REGIME_RANGE


def test_signal_panic_vix_absent():
    """Aucun field vix/atr -> RANGE (fail-safe complet)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    assert clf._signal_panic({}) == REGIME_RANGE


# ============================================================
# Vote majoritaire
# ============================================================


def test_vote_majority_range():
    """3 votes RANGE -> verdict RANGE."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "vwap_slope_30": 0.0,
        "bars_since_last_swing_high": 15,
        "bars_since_last_swing_low": 20,
        "vix_level": 18.0,
    }
    verdict = clf.classify(bar, "ES")
    assert verdict.regime == REGIME_RANGE
    assert verdict.votes[REGIME_RANGE] == 3
    assert verdict.signals == {
        "slope": REGIME_RANGE,
        "swing": REGIME_RANGE,
        "panic": REGIME_RANGE,
    }


def test_vote_majority_trend_down():
    """2 votes TREND_DOWN + 1 RANGE -> verdict TREND_DOWN.

    Scenario : slope bearish + swing LL + panic neutre.
    """
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "vwap_slope_30": -1.0,  # ES seuil -0.5 -> TREND_DOWN
        "bars_since_last_swing_high": 50,  # ratio 5.0 -> TREND_DOWN
        "bars_since_last_swing_low": 10,
        "vix_level": 18.0,  # neutre -> RANGE
    }
    verdict = clf.classify(bar, "ES")
    assert verdict.regime == REGIME_TREND_DOWN
    assert verdict.votes[REGIME_TREND_DOWN] == 2
    assert verdict.votes[REGIME_RANGE] == 1


def test_vote_majority_trend_up():
    """2 votes TREND_UP + 1 RANGE -> verdict TREND_UP."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "vwap_slope_30": 1.0,  # ES seuil +0.5 -> TREND_UP
        "bars_since_last_swing_high": 10,  # ratio 0.2 -> TREND_UP
        "bars_since_last_swing_low": 50,
        "vix_level": 18.0,  # RANGE
    }
    verdict = clf.classify(bar, "ES")
    assert verdict.regime == REGIME_TREND_UP
    assert verdict.votes[REGIME_TREND_UP] == 2


def test_panic_priority():
    """1 vote PANIC + 2 RANGE -> verdict PANIC (priorite absolue)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "vwap_slope_30": 0.0,  # RANGE
        "bars_since_last_swing_high": 15,  # RANGE
        "bars_since_last_swing_low": 20,
        "vix_level": 35.0,  # PANIC
    }
    verdict = clf.classify(bar, "ES")
    assert verdict.regime == REGIME_PANIC
    assert verdict.votes[REGIME_PANIC] == 1
    assert "PANIC priority" in verdict.reason


def test_panic_priority_over_trend():
    """PANIC l'emporte meme si TREND_DOWN majoritaire (2 votes)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "vwap_slope_30": -2.0,  # ES TREND_DOWN
        "bars_since_last_swing_high": 50,  # TREND_DOWN
        "bars_since_last_swing_low": 10,
        "vix_level": 35.0,  # PANIC
    }
    verdict = clf.classify(bar, "ES")
    assert verdict.regime == REGIME_PANIC


def test_vote_egalite_range_wins():
    """3 votes differents (TREND_DOWN, TREND_UP, RANGE) -> RANGE par ordre insertion.

    Convention conservative : en cas d'egalite parfaite, RANGE prevaut
    (= trade autorise normal, ne bloque pas par defaut).
    """
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    # Construction artificielle : slope TREND_DOWN, swing TREND_UP, panic RANGE
    bar = {
        "vwap_slope_30": -2.0,  # ES -> TREND_DOWN
        "bars_since_last_swing_high": 10,  # ratio 0.2 -> TREND_UP
        "bars_since_last_swing_low": 50,
        "vix_level": 18.0,  # RANGE
    }
    verdict = clf.classify(bar, "ES")
    # Egalite 1-1-1 sur RANGE/TREND_DOWN/TREND_UP. max() retourne RANGE (insere 1er).
    assert verdict.regime == REGIME_RANGE


# ============================================================
# allows_direction : matrice complete
# ============================================================


def _verdict(regime: str) -> RegimeVerdict:
    return RegimeVerdict(regime=regime, votes={}, signals={}, reason="test")


def test_allows_direction_range():
    """RANGE -> autorise LONG et SHORT."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    v = _verdict(REGIME_RANGE)
    assert clf.allows_direction(v, "LONG") is True
    assert clf.allows_direction(v, "SHORT") is True


def test_allows_direction_trend_down_blocks_long():
    """TREND_DOWN -> bloque LONG (catch falling knife), autorise SHORT."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    v = _verdict(REGIME_TREND_DOWN)
    assert clf.allows_direction(v, "LONG") is False
    assert clf.allows_direction(v, "SHORT") is True


def test_allows_direction_trend_up_blocks_short():
    """TREND_UP -> bloque SHORT (contre-trend), autorise LONG."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    v = _verdict(REGIME_TREND_UP)
    assert clf.allows_direction(v, "LONG") is True
    assert clf.allows_direction(v, "SHORT") is False


def test_allows_direction_panic_blocks_all():
    """PANIC -> bloque TOUT (LONG + SHORT)."""
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    v = _verdict(REGIME_PANIC)
    assert clf.allows_direction(v, "LONG") is False
    assert clf.allows_direction(v, "SHORT") is False


# ============================================================
# Integration scenario carnage 18/06 (regression check)
# ============================================================


def test_carnage_18_06_es_long_trend_down_blocked():
    """Simule bar ES en pleine descente 18/06 -> LONG bloque par classifier.

    Profil reel : slope_30 environ -0.72 (bar 20260615 18:21 UTC observe),
    bars_since_low recent (73 bars car nouveau swing low en cours), swing_high
    vieux. Le classifier doit voter TREND_DOWN au moins 1 fois -> bloque LONG.
    """
    cfg = BotMRConfig()
    clf = RegimeClassifier(cfg)
    bar = {
        "vwap_slope_30": -0.72,  # < -0.5 -> TREND_DOWN
        # Bars since high VIEUX, low RECENT (LL chain)
        "bars_since_last_swing_high": 100,
        "bars_since_last_swing_low": 5,
        "vix_level": 16.2,  # neutre
    }
    verdict = clf.classify(bar, "ES")
    # Au moins 1 vote TREND_DOWN (slope) + swing -> majoritaire
    assert verdict.regime == REGIME_TREND_DOWN, f"verdict={verdict}"
    # LONG bloque (catch falling knife)
    assert clf.allows_direction(verdict, "LONG") is False
    # SHORT autorise (alignement trend)
    assert clf.allows_direction(verdict, "SHORT") is True
