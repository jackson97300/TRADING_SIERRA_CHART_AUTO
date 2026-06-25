"""Tests bot4_v2/core/regime_source.

Tests parite bit-for-bit avec CORE/regime_engine_v2.py + FIX V1 conserves :
- /votes_exprimes (vs /12.0) - anti pattern 11 V1 (27/05)
- range_pos default 0.5 (vs 50.0) - silent mort 18/05+ (03/06)
- mode TREND fallback votes directionnels (03/06)
- day_type INVALID guard Asia/London (06/06)
- atr_regime_zscore_60d (vs sess_range_atr NaN ES/MGC) (11/05)
- seuils bias_proxy +/-0.20 (vs +/-0.30) (03/06)
"""
from __future__ import annotations

import os

import pytest

import bot4_v2.core.regime_source as rs
from bot4_v2.core.regime_source import (
    REGIME_CALIB_VERSION,
    REGIME_MIN_VOTES_THRESHOLD,
    RegimeAnalysis,
    _compute_bias_proxy,
    compute_regime,
    compute_regime_dict,
)


def _make_bar_trend_up() -> dict:
    """Bar mode TREND bullish (forte directionnalite LONG)."""
    return {
        "ib_broken_up": 1, "ib_broken_down": 0, "ib_formed_bool": 1,
        "day_type": 4,  # Trend
        "single_print_count": 150,  # fort
        "vwap_slope_10": 5.0,  # > 3.5 + positif (UP)
        "sess_range_atr": 1.5,  # expansion
        "open_type": 1,  # OD up (LONG bias)
        "profile_shape": 1,  # P-shape (LONG)
        "poc_bar_dist": 20.0,  # distant
        "bars_in_va": 5.0,  # hors VA
        "trend_day_probability": 0.45,  # > 0.30
        # bias_proxy LONG
        "delta_day_dir": 1, "cvd_day_dir": 1,
        "range_pos": 0.20,  # bull bias [0,1]
        "vwap_d_side": 1,
        "delta_divergence": 1,
        "atr_regime_zscore_60d": 0.5,  # NORMAL
    }


def _make_bar_range() -> dict:
    """Bar mode RANGE (IB intacte + Day Type Normal + faible vol)."""
    return {
        "ib_broken_up": 0, "ib_broken_down": 0, "ib_formed_bool": 1,
        "day_type": 1,  # Normal (RANGE)
        "single_print_count": 20,  # faible
        "vwap_slope_10": 0.2,  # plat
        "sess_range_atr": 0.3,  # compression
        "open_type": 5,  # ORR (range)
        "profile_shape": 0,  # D (range)
        "poc_bar_dist": 2.0,  # proche
        "bars_in_va": 50.0,  # confine
        "trend_day_probability": 0.05,
        "range_pos": 0.50,
        "atr_regime_zscore_60d": 0.0,
    }


def _make_bar_empty() -> dict:
    return {}


# ============================================================
# RegimeAnalysis dataclass
# ============================================================

def test_regime_analysis_dataclass_fields():
    r = RegimeAnalysis(
        mode="TREND", favor="LONG", confidence=0.5,
        trend_votes=8, range_votes=2, vol_regime="NORMAL",
        bias_score=0.5, is_actionable=True,
    )
    assert r.mode == "TREND"
    assert r.favor == "LONG"
    assert r.confidence == 0.5
    assert r.details == []  # default factory
    assert r.bear_factors == 0  # default


# ============================================================
# compute_regime nominal cases
# ============================================================

def test_compute_regime_trend_up_actionable():
    """Trend UP bar -> mode TREND, favor LONG, is_actionable=True."""
    bar = _make_bar_trend_up()
    r = compute_regime(bar)
    assert r.mode == "TREND"
    assert r.favor == "LONG"
    assert r.is_actionable is True
    assert r.trend_votes >= 5
    assert r.confidence > 0.10
    assert r.trend_up_votes > r.trend_down_votes


def test_compute_regime_range_neutral():
    """Range bar -> mode RANGE, favor NEUTRE (range_pos=0.50)."""
    bar = _make_bar_range()
    r = compute_regime(bar)
    assert r.mode == "RANGE"
    assert r.range_votes >= r.trend_votes
    # range_pos=0.50 -> ni LONG (<0.30) ni SHORT (>=0.70) -> NEUTRE
    assert r.favor == "NEUTRE"


def test_compute_regime_empty_bar_safe():
    """Bar vide -> RegimeAnalysis NORMAL (pas de crash)."""
    r = compute_regime(_make_bar_empty())
    assert r.mode == "NORMAL"
    assert r.favor == "NEUTRE"
    assert r.confidence == 0.0
    assert r.is_actionable is False
    assert "empty_bar" in r.details


# ============================================================
# KILL SWITCH BOT4V2_REGIME_SKIP_ENABLED
# ============================================================

def test_compute_regime_kill_switch_disabled(monkeypatch):
    """KILL SWITCH=0 -> retourne NEUTRE force avec detail."""
    monkeypatch.setattr(rs, "REGIME_SKIP_ENABLED", False)
    r = compute_regime(_make_bar_trend_up())
    assert r.mode == "NORMAL"
    assert r.favor == "NEUTRE"
    assert r.is_actionable is False
    assert "KILL_SWITCH_REGIME_DISABLED" in r.details


# ============================================================
# FIX V1 confidence /votes_exprimes (anti pattern 11 V1)
# ============================================================

def test_fix_confidence_uses_votes_exprimes_not_12():
    """FIX V1 27/05 : conf = net/total_votes (vs /12.0).

    Bar avec 5 trend / 2 range -> net=3, total=7 -> conf=3/7=0.43 (NOT 3/12=0.25).
    """
    # Construit bar pour exactement 5 trend / 2 range votes.
    # IB cassee (+2 trend), Day Type Trend (+2 trend), SinglePrints fort (+1 trend) = 5 trend
    # Pas de range votes naturels -> ajouter 2 range votes via day_type Normal?
    # Mais day_type est exclusive (1 valeur). On force via Profile + POC = 2 range.
    # Construit bar pour exactement 5 trend / 2 range votes.
    # ATTENTION : tous les fields qui ont default 0 -> contribuent (ex vwap_slope=0 -> range).
    # Donc OBLIGATOIRE specifier toutes les features dans plage neutre.
    bar = {
        "ib_broken_up": 1, "ib_broken_down": 0, "ib_formed_bool": 1,  # +2 trend
        "day_type": 4,  # +2 trend = 4 trend cumule
        "single_print_count": 50,  # neutre (30 < x < 100) -> 0 vote
        "profile_shape": 0,  # +1 range D
        "poc_bar_dist": 10.0,  # neutre (3 < x < 15) -> 0 vote
        "vwap_slope_10": 2.0,  # neutre (0.5 < x < 3.5) -> 0 vote, +1 trend via single_print_count > 100 ? NON
        "sess_range_atr": 0.7,  # neutre (0.4 < x < 1.0) -> 0 vote
        "open_type": 0,  # 0 -> rien
        "bars_in_va": 20.0,  # neutre (10 < x < 30) -> 0 vote
        "trend_day_probability": 0.20,  # neutre (0.10 < x < 0.30) -> 0 vote
        "atr_regime_zscore_60d": 0.0,
    }
    # Pour atteindre 5 trend votes : il faut single_print 150 (>100) au lieu de 50
    bar["single_print_count"] = 150  # +1 trend
    # Maintenant 5 trend (2 IB + 2 DayType + 1 SinglePrints)
    # range votes : 1 Profile D + ??
    # Besoin +1 range. Bars_in_va > 30 -> +1 range
    bar["bars_in_va"] = 40.0  # +1 range
    r = compute_regime(bar)
    assert r.trend_votes == 5
    assert r.range_votes == 2
    # net = |5-2| = 3, total = 7 -> conf = 3/7 = 0.42857... -> rounded 0.43
    assert r.confidence == 0.43  # NOT 0.25 (/12.0 bug)


def test_fix_confidence_total_zero_safe():
    """confidence safe quand total_votes=0 (division par max(total, 1))."""
    r = compute_regime({})  # bar vide -> 0 votes
    assert r.confidence == 0.0  # net=0 / max(0,1)=1 = 0


# ============================================================
# FIX V1 range_pos echelle [0,1] default 0.5
# ============================================================

def test_fix_range_pos_default_05_not_50():
    """Bar sans range_pos en mode RANGE -> favor NEUTRE (vs SHORT default 50.0)."""
    bar = _make_bar_range()
    bar.pop("range_pos", None)  # absent
    r = compute_regime(bar)
    # default 0.5 -> ni < 0.30 ni >= 0.70 -> NEUTRE
    assert r.favor == "NEUTRE"


def test_fix_range_pos_high_short():
    """range_pos=0.80 en RANGE -> favor SHORT."""
    bar = _make_bar_range()
    bar["range_pos"] = 0.80
    r = compute_regime(bar)
    assert r.mode == "RANGE"
    assert r.favor == "SHORT"


def test_fix_range_pos_low_long():
    """range_pos=0.10 en RANGE -> favor LONG."""
    bar = _make_bar_range()
    bar["range_pos"] = 0.10
    r = compute_regime(bar)
    assert r.mode == "RANGE"
    assert r.favor == "LONG"


# ============================================================
# FIX V1 mode TREND fallback votes directionnels
# ============================================================

def test_fix_trend_mode_uses_directional_votes_for_favor():
    """Mode TREND : favor depend de trend_up_votes vs trend_down_votes."""
    bar = _make_bar_trend_up()  # tous votes UP
    r = compute_regime(bar)
    assert r.mode == "TREND"
    assert r.favor == "LONG"
    assert r.trend_up_votes > 0
    assert r.trend_down_votes == 0


def test_fix_trend_mode_no_directional_votes_neutre():
    """Mode TREND mais aucun vote directionnel -> NEUTRE (anti faux positifs 03/06)."""
    bar = {
        # Trend votes neutres (sans direction)
        "ib_broken_up": 0, "ib_broken_down": 0, "ib_formed_bool": 1,
        "day_type": 2,  # NormVar +1 trend (pas directionnel)
        "single_print_count": 150,  # +1 trend (pas directionnel)
        "vwap_slope_10": 0.0,
        "sess_range_atr": 2.0,  # +1 trend expansion (pas directionnel)
        "open_type": 0,
        "profile_shape": -1,
        "poc_bar_dist": 20.0,  # +1 trend distant (pas directionnel)
        "bars_in_va": 5.0,  # +1 trend hors VA (pas directionnel)
        "trend_day_probability": 0.45,
        "atr_regime_zscore_60d": 0.0,
    }
    r = compute_regime(bar)
    assert r.mode == "TREND"
    assert r.trend_up_votes == 0
    assert r.trend_down_votes == 0
    assert r.favor == "NEUTRE"
    assert any("no_directional_votes" in d for d in r.details)


# ============================================================
# FIX V1 day_type INVALID guard
# ============================================================

def test_fix_day_type_invalid_skip_vote():
    """day_type=null/NaN/negatif (Asia/London) -> skip vote (vs trend systematique pre-fix)."""
    bar = _make_bar_range()
    bar["day_type"] = None
    r = compute_regime(bar)
    assert any("Day Type: INVALID" in d for d in r.details)


def test_fix_day_type_nan_skip_vote():
    bar = _make_bar_range()
    bar["day_type"] = float("nan")
    r = compute_regime(bar)
    assert any("Day Type: INVALID" in d for d in r.details)


def test_fix_day_type_negative_skip_vote():
    bar = _make_bar_range()
    bar["day_type"] = -1
    r = compute_regime(bar)
    assert any("Day Type: INVALID" in d for d in r.details)


# ============================================================
# FIX V1 atr_regime_zscore_60d cross-instrument
# ============================================================

def test_vol_regime_extreme():
    bar = _make_bar_range()
    bar["atr_regime_zscore_60d"] = 3.0
    r = compute_regime(bar)
    assert r.vol_regime == "EXTREME"
    assert r.is_actionable is False  # vol EXTREME -> NOT actionable


def test_vol_regime_high():
    bar = _make_bar_range()
    bar["atr_regime_zscore_60d"] = 1.8
    r = compute_regime(bar)
    assert r.vol_regime == "HIGH"


def test_vol_regime_low():
    bar = _make_bar_range()
    bar["atr_regime_zscore_60d"] = -1.0
    r = compute_regime(bar)
    assert r.vol_regime == "LOW"


def test_vol_regime_nan_normal():
    """NaN (premiers 60j rolling) -> NORMAL (neutralite explicite)."""
    bar = _make_bar_range()
    bar["atr_regime_zscore_60d"] = float("nan")
    r = compute_regime(bar)
    assert r.vol_regime == "NORMAL"


# ============================================================
# FIX V1 bias_proxy seuils +/-0.20
# ============================================================

def test_bias_proxy_bullish_at_021():
    """bias_proxy score 0.21 -> BULLISH (vs NEUTRE pre-fix avec +/-0.30)."""
    bar = {
        "vwap_slope_10": 1.5,  # +0.25 bull
        "delta_day_dir": 0, "cvd_day_dir": 0,
        "range_pos": 0.5,  # neutre
        "vwap_d_side": 0,
        "delta_divergence": 0,
    }
    score, label, bear, bull = _compute_bias_proxy(bar)
    assert score == 0.25
    assert label == "BULLISH"
    assert bull == 1
    assert bear == 0


def test_bias_proxy_bearish_at_minus_021():
    bar = {
        "vwap_slope_10": -1.5,  # -0.25 bear
        "delta_day_dir": 0, "cvd_day_dir": 0,
        "range_pos": 0.5,
        "vwap_d_side": 0,
        "delta_divergence": 0,
    }
    score, label, bear, bull = _compute_bias_proxy(bar)
    assert score == -0.25
    assert label == "BEARISH"


def test_bias_proxy_neutre_at_015():
    """score 0.15 -> NEUTRE (sous seuil 0.20)."""
    bar = {
        "vwap_slope_10": 0.0,
        "delta_day_dir": 0, "cvd_day_dir": 0,
        "range_pos": 0.5,
        "vwap_d_side": 1,  # +0.15 bull
        "delta_divergence": 0,
    }
    score, label, _, _ = _compute_bias_proxy(bar)
    assert score == 0.15
    assert label == "NEUTRE"  # sous seuil +0.20


def test_bias_proxy_range_pos_low_bullish():
    """range_pos < 0.30 -> bull factor +0.20."""
    bar = {
        "vwap_slope_10": 0.0,
        "delta_day_dir": 0, "cvd_day_dir": 0,
        "range_pos": 0.20,
        "vwap_d_side": 0,
        "delta_divergence": 0,
    }
    score, _, _, bull = _compute_bias_proxy(bar)
    assert score == 0.20
    assert bull == 1


def test_bias_proxy_range_pos_high_bearish():
    bar = {
        "vwap_slope_10": 0.0,
        "delta_day_dir": 0, "cvd_day_dir": 0,
        "range_pos": 0.80,
        "vwap_d_side": 0,
        "delta_divergence": 0,
    }
    score, _, bear, _ = _compute_bias_proxy(bar)
    assert score == -0.20
    assert bear == 1


# ============================================================
# Override coherence
# ============================================================

def test_override_long_to_neutre_with_3_bear_factors():
    """favor=LONG mais bear_factors>=3 -> override NEUTRE."""
    bar = {
        # mode TREND LONG via IB UP + open_type 1
        "ib_broken_up": 1, "ib_broken_down": 0, "ib_formed_bool": 1,
        "day_type": 4,
        "vwap_slope_10": 4.0,  # +1 trend UP
        "open_type": 1,
        # bias proxy 3 bear factors
        "delta_day_dir": -1, "cvd_day_dir": -1,
        "range_pos": 0.80,  # bear
        "vwap_d_side": -1,
        "delta_divergence": -1,
        "atr_regime_zscore_60d": 0.0,
    }
    r = compute_regime(bar)
    assert r.bear_factors >= 3
    assert r.favor == "NEUTRE"
    assert any("Override" in d for d in r.details)


# ============================================================
# INSUFFICIENT_FEATURES flag
# ============================================================

def test_insufficient_features_flag():
    """Bar avec <4 votes total -> flag INSUFFICIENT_FEATURES.

    Doit FORCER toutes les features en zone neutre pour eviter votes auto.
    """
    bar = {
        "ib_formed_bool": 1, "ib_broken_up": 0, "ib_broken_down": 0,  # +1 range IB intacte
        "day_type": 1,  # +1 range Normal
        "single_print_count": 50,  # neutre (30-100)
        "vwap_slope_10": 2.0,  # neutre (0.5-3.5)
        "sess_range_atr": 0.7,  # neutre (0.4-1.0)
        "open_type": 0,  # rien
        "profile_shape": -1,  # rien
        "poc_bar_dist": 10.0,  # neutre (3-15)
        "bars_in_va": 20.0,  # neutre (10-30)
        "trend_day_probability": 0.20,  # neutre (0.10-0.30)
        "atr_regime_zscore_60d": 0.0,
        "range_pos": 0.5,
    }
    r = compute_regime(bar)
    total = r.trend_votes + r.range_votes
    assert total < REGIME_MIN_VOTES_THRESHOLD, f"total={total} votes={r}"
    assert any("INSUFFICIENT_FEATURES" in d for d in r.details)


# ============================================================
# compute_regime_dict wrapper
# ============================================================

def test_compute_regime_dict_keys_complete():
    """Dict wrapper contient 7 keys cles pour pipeline V4."""
    d = compute_regime_dict(_make_bar_trend_up())
    expected_keys = {
        "regime_mode", "regime_favor", "regime_confidence",
        "regime_trend_votes", "regime_range_votes",
        "regime_vol", "regime_actionable",
    }
    assert set(d.keys()) == expected_keys
    assert d["regime_actionable"] in (0, 1)
    assert d["regime_mode"] in ("TREND", "RANGE", "NORMAL")


# ============================================================
# Calib version traceability
# ============================================================

def test_calib_version_is_v4_fork():
    """Bot 4 v2 fork = v4 (post v3 27/05 CORE/regime_engine_v2)."""
    assert REGIME_CALIB_VERSION.startswith("v4_bot4v2_fork_")


def test_min_votes_threshold_reasonable():
    assert 3 <= REGIME_MIN_VOTES_THRESHOLD <= 6
