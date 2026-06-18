"""Tests RegimeScorer Bot MR (Phase 3 alternative score continu).

Couvre :
  - Config defaults (REGIME_SCORER_ENABLED=True)
  - Normalisation slope par stdev symbole (ES=1.42, NQ=8.54)
  - Contributions individuelles (slope, swing, atr, delta, trend_day)
  - Panic flag (VIX, ATR z-score)
  - Classification score -> regime (5 niveaux + PANIC)
  - allows_direction (politique blocage TREND_*_STRONG + PANIC)
  - Robustesse fields manquants / corrompus
  - Integration SignalEngine via injection
"""
from __future__ import annotations

import math

import pytest

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.gates.regime_scorer import (
    RegimeScore,
    RegimeScorer,
    SLOPE_STDEV_BY_SYM,
)


# ============================================================
# Config defaults
# ============================================================

def test_default_enabled_false():
    """REGIME_SCORER_ENABLED False par defaut (decision 18/06 croisement 2 approches).

    Le scorer est trop permissif (laisse passer 3-4/4 LONGs carnage 18/06).
    Reste activable via BOTMR_REGIME_SCORER_ENABLED=1 apres recal empirique 30j+.
    RegimeClassifier KISS vote majoritaire est ACTIF par defaut et suffisant.
    """
    cfg = BotMRConfig()
    assert cfg.REGIME_SCORER_ENABLED is False
    assert cfg.REGIME_SCORE_STRONG_THRESHOLD == 60.0
    assert cfg.REGIME_SCORE_WEAK_THRESHOLD == 30.0


def test_env_override(monkeypatch):
    """Override via env vars."""
    monkeypatch.setenv("BOTMR_REGIME_SCORER_ENABLED", "false")
    monkeypatch.setenv("BOTMR_REGIME_SCORE_STRONG_THRESHOLD", "70")
    monkeypatch.setenv("BOTMR_REGIME_SCORE_WEAK_THRESHOLD", "25")
    cfg = BotMRConfig.from_env()
    assert cfg.REGIME_SCORER_ENABLED is False
    assert cfg.REGIME_SCORE_STRONG_THRESHOLD == 70.0
    assert cfg.REGIME_SCORE_WEAK_THRESHOLD == 25.0


# ============================================================
# Normalisation slope
# ============================================================

def test_normalize_slope_es_neutral():
    """Slope 0 ES -> normalisation 0."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._normalize_slope(0.0, "ES") == 0.0


def test_normalize_slope_nq_scaled():
    """Slope 6 NQ -> norm = 6 / 8.54 ~= 0.70 sigma."""
    scorer = RegimeScorer(BotMRConfig())
    result = scorer._normalize_slope(6.0, "NQ")
    expected = 6.0 / SLOPE_STDEV_BY_SYM["NQ"]
    assert abs(result - expected) < 1e-6


def test_normalize_slope_unknown_symbol_fallback():
    """Symbole inconnu -> stdev fallback 1.0."""
    scorer = RegimeScorer(BotMRConfig())
    # Symbole inconnu : stdev = 1.0
    assert scorer._normalize_slope(2.5, "ZZZ") == 2.5


# ============================================================
# Contributions individuelles
# ============================================================

def test_contrib_slope_bearish_es():
    """ES slope -1.5 = -1.06 sigma -> contrib ~ -10.6 (clip et scale)."""
    scorer = RegimeScorer(BotMRConfig())
    bar = {"vwap_slope_30": -1.5}
    contrib = scorer._contrib_slope(bar, "ES")
    # slope_norm = -1.5 / 1.42 = -1.056 ; clip [-3,3] ; scale (slope_norm/3)*30
    expected = (-1.5 / 1.42 / 3.0) * 30.0
    assert abs(contrib - expected) < 1e-3


def test_contrib_slope_clip_extreme():
    """Slope >> 3 sigma -> clip a +30."""
    scorer = RegimeScorer(BotMRConfig())
    bar = {"vwap_slope_30": 100.0}  # 70 sigma ES, clip 3 sigma
    assert scorer._contrib_slope(bar, "ES") == 30.0
    bar = {"vwap_slope_30": -100.0}
    assert scorer._contrib_slope(bar, "ES") == -30.0


def test_contrib_slope_missing_field():
    """Field absent -> contrib 0."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._contrib_slope({}, "ES") == 0.0
    assert scorer._contrib_slope({"vwap_slope_30": None}, "ES") == 0.0
    assert scorer._contrib_slope({"vwap_slope_30": "bad"}, "ES") == 0.0


def test_contrib_swing_ratio_lower_lows():
    """Low recent (bs_low=10), high vieux (bs_high=100) -> log(0.1)=-2.3.

    log_ratio = log(bs_low / bs_high) = log(10/100) = log(0.1) = -2.3.
    Clip [-1.5, +1.5] -> -1.5. Scale [-25, +25] -> -25.
    Downtrend (high domine, low recent oblige le marche a faire des lows).
    """
    scorer = RegimeScorer(BotMRConfig())
    bar = {"bars_since_last_swing_high": 100, "bars_since_last_swing_low": 10}
    contrib = scorer._contrib_swing(bar)
    assert contrib == -25.0  # clipped


def test_contrib_swing_ratio_higher_highs():
    """High recent (bs_high=10), low vieux (bs_low=100) -> log(10)=+2.3 -> clip +25."""
    scorer = RegimeScorer(BotMRConfig())
    bar = {"bars_since_last_swing_high": 10, "bars_since_last_swing_low": 100}
    contrib = scorer._contrib_swing(bar)
    assert contrib == 25.0  # clipped


def test_contrib_swing_neutral_ratio():
    """bs_high = bs_low -> log(1) = 0 -> contrib 0."""
    scorer = RegimeScorer(BotMRConfig())
    bar = {"bars_since_last_swing_high": 30, "bars_since_last_swing_low": 30}
    assert scorer._contrib_swing(bar) == 0.0


def test_contrib_swing_zero_division_safe():
    """bs=0 ou negatif -> contrib 0 (defensive, evite ZeroDivision)."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._contrib_swing(
        {"bars_since_last_swing_high": 0, "bars_since_last_swing_low": 10}
    ) == 0.0
    assert scorer._contrib_swing(
        {"bars_since_last_swing_high": -5, "bars_since_last_swing_low": 10}
    ) == 0.0


def test_contrib_atr_z_neutral():
    """ATR z-score est neutre directionnellement -> contrib toujours 0."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._contrib_atr_z({"ctx_atr_zscore": 2.0}) == 0.0
    assert scorer._contrib_atr_z({"ctx_atr_zscore": -1.0}) == 0.0
    assert scorer._contrib_atr_z({}) == 0.0


def test_contrib_delta_day_bullish():
    """delta_day +50k -> contrib +7.5 (50/100 * 15)."""
    scorer = RegimeScorer(BotMRConfig())
    contrib = scorer._contrib_delta_day({"delta_day": 50_000})
    assert abs(contrib - 7.5) < 1e-6


def test_contrib_delta_day_cvd_fallback():
    """delta_day absent mais cvd present -> utilise cvd."""
    scorer = RegimeScorer(BotMRConfig())
    contrib = scorer._contrib_delta_day({"cvd": -100_000})
    assert contrib == -15.0  # -100k -> clip -1 -> -15


def test_contrib_delta_day_clip():
    """delta extreme -> clip [-15, +15]."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._contrib_delta_day({"delta_day": 999_999}) == 15.0
    assert scorer._contrib_delta_day({"delta_day": -999_999}) == -15.0


def test_contrib_trend_day_score():
    """trend_day_score 0.5 -> contrib 7.5."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._contrib_trend_day_score({"ctx_trend_day_score": 0.5}) == 7.5
    assert scorer._contrib_trend_day_score({"ctx_trend_day_score": -1.0}) == -15.0


def test_contrib_trend_day_clip():
    """trend_day_score > 1.0 -> clip 1.0."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._contrib_trend_day_score({"ctx_trend_day_score": 5.0}) == 15.0


# ============================================================
# Panic flag
# ============================================================

def test_panic_flag_vix():
    """VIX > 30 -> panic True."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._panic_flag({"vix_level": 35.0}) is True
    assert scorer._panic_flag({"vix_level": 28.0}) is False


def test_panic_flag_atr():
    """ATR z-score > 2.5 -> panic True."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._panic_flag({"ctx_atr_zscore": 3.0}) is True
    assert scorer._panic_flag({"ctx_atr_zscore": 1.5}) is False


def test_panic_flag_both_absent():
    """Pas VIX ni ATR -> pas panic."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer._panic_flag({}) is False


# ============================================================
# Classification score -> regime
# ============================================================

def test_classify_range():
    """Score 0 -> RANGE."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer.classify_to_regime(0.0, False) == "RANGE"
    assert scorer.classify_to_regime(15.0, False) == "RANGE"
    assert scorer.classify_to_regime(-25.0, False) == "RANGE"


def test_classify_trend_down_weak():
    """Score -40 -> TREND_DOWN_WEAK (entre -60 et -30)."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer.classify_to_regime(-40.0, False) == "TREND_DOWN_WEAK"
    assert scorer.classify_to_regime(-31.0, False) == "TREND_DOWN_WEAK"


def test_classify_trend_down_strong():
    """Score -70 -> TREND_DOWN_STRONG (< -60)."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer.classify_to_regime(-70.0, False) == "TREND_DOWN_STRONG"
    assert scorer.classify_to_regime(-100.0, False) == "TREND_DOWN_STRONG"


def test_classify_trend_up_weak():
    """Score +40 -> TREND_UP_WEAK."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer.classify_to_regime(40.0, False) == "TREND_UP_WEAK"
    assert scorer.classify_to_regime(31.0, False) == "TREND_UP_WEAK"


def test_classify_trend_up_strong():
    """Score +70 -> TREND_UP_STRONG."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer.classify_to_regime(70.0, False) == "TREND_UP_STRONG"
    assert scorer.classify_to_regime(100.0, False) == "TREND_UP_STRONG"


def test_classify_panic_priority():
    """Panic override toute classification score."""
    scorer = RegimeScorer(BotMRConfig())
    # Score positif extreme mais panic -> PANIC
    assert scorer.classify_to_regime(90.0, True) == "PANIC"
    # Score negatif extreme mais panic -> PANIC
    assert scorer.classify_to_regime(-90.0, True) == "PANIC"
    # Score neutre mais panic -> PANIC
    assert scorer.classify_to_regime(0.0, True) == "PANIC"


def test_classify_boundary_weak():
    """Score == +30 (boundary inclusif) -> RANGE, +31 -> WEAK."""
    scorer = RegimeScorer(BotMRConfig())
    assert scorer.classify_to_regime(30.0, False) == "RANGE"
    assert scorer.classify_to_regime(30.01, False) == "TREND_UP_WEAK"


def test_classify_boundary_strong():
    """Score == -60 (boundary) -> TREND_DOWN_STRONG, -59 -> WEAK."""
    scorer = RegimeScorer(BotMRConfig())
    # Note : seuil < -60 strict pour STRONG, donc -60 exact = WEAK
    assert scorer.classify_to_regime(-60.0, False) == "TREND_DOWN_WEAK"
    assert scorer.classify_to_regime(-60.01, False) == "TREND_DOWN_STRONG"


# ============================================================
# allows_direction (politique blocage)
# ============================================================

def test_allows_direction_strong_trend_blocks():
    """TREND_DOWN_STRONG bloque LONG. TREND_UP_STRONG bloque SHORT."""
    scorer = RegimeScorer(BotMRConfig())
    rs_down = RegimeScore(
        score=-70.0, regime="TREND_DOWN_STRONG", panic=False,
        features={}, reason="test",
    )
    rs_up = RegimeScore(
        score=70.0, regime="TREND_UP_STRONG", panic=False,
        features={}, reason="test",
    )
    assert scorer.allows_direction(rs_down, "LONG") is False
    assert scorer.allows_direction(rs_down, "SHORT") is True
    assert scorer.allows_direction(rs_up, "SHORT") is False
    assert scorer.allows_direction(rs_up, "LONG") is True


def test_allows_direction_weak_trend_permits():
    """TREND_DOWN_WEAK autorise LONG (MR pertinent contre trend faible)."""
    scorer = RegimeScorer(BotMRConfig())
    rs = RegimeScore(
        score=-40.0, regime="TREND_DOWN_WEAK", panic=False,
        features={}, reason="test",
    )
    assert scorer.allows_direction(rs, "LONG") is True
    assert scorer.allows_direction(rs, "SHORT") is True


def test_allows_direction_range_permits_both():
    """RANGE autorise tout (zone neutre MR ideale)."""
    scorer = RegimeScorer(BotMRConfig())
    rs = RegimeScore(
        score=0.0, regime="RANGE", panic=False,
        features={}, reason="test",
    )
    assert scorer.allows_direction(rs, "LONG") is True
    assert scorer.allows_direction(rs, "SHORT") is True


def test_allows_direction_panic_blocks_all():
    """PANIC bloque tout (no MR en regime panic)."""
    scorer = RegimeScorer(BotMRConfig())
    rs = RegimeScore(
        score=90.0, regime="PANIC", panic=True,
        features={}, reason="test",
    )
    assert scorer.allows_direction(rs, "LONG") is False
    assert scorer.allows_direction(rs, "SHORT") is False


# ============================================================
# classify() integration end-to-end
# ============================================================

def test_classify_bullish_aligned_features():
    """Bar bullish align : slope+, swing+, delta+, trend+ -> score positif -> TREND_UP."""
    scorer = RegimeScorer(BotMRConfig())
    bar = {
        "vwap_slope_30": 1.5,  # ES bullish (~1 sigma)
        "bars_since_last_swing_high": 5,  # high recent
        "bars_since_last_swing_low": 80,  # low vieux
        "delta_day": 75_000,
        "ctx_trend_day_score": 0.7,
        "vix_level": 16.0,
        "ctx_atr_zscore": 1.0,
    }
    rs = scorer.classify(bar, "ES")
    assert rs.score > 30.0  # au moins TREND_UP_WEAK
    assert rs.regime in ("TREND_UP_WEAK", "TREND_UP_STRONG")
    assert rs.panic is False


def test_classify_bearish_aligned_features():
    """Bar bearish align : slope-, swing-, delta-, trend- -> score negatif -> TREND_DOWN."""
    scorer = RegimeScorer(BotMRConfig())
    bar = {
        "vwap_slope_30": -2.5,  # ES bearish (~1.8 sigma)
        "bars_since_last_swing_high": 90,  # high vieux
        "bars_since_last_swing_low": 5,  # low recent
        "delta_day": -80_000,
        "ctx_trend_day_score": -0.6,
        "vix_level": 22.0,
        "ctx_atr_zscore": 1.5,
    }
    rs = scorer.classify(bar, "ES")
    assert rs.score < -30.0
    assert rs.regime in ("TREND_DOWN_WEAK", "TREND_DOWN_STRONG")
    assert rs.panic is False


def test_classify_panic_overrides_score():
    """VIX panic override toute classification score."""
    scorer = RegimeScorer(BotMRConfig())
    # Bar bullish mais VIX panic
    bar = {
        "vwap_slope_30": 2.0,
        "vix_level": 35.0,  # > 30 -> panic
        "delta_day": 50_000,
    }
    rs = scorer.classify(bar, "ES")
    assert rs.regime == "PANIC"
    assert rs.panic is True


def test_classify_empty_bar_neutral():
    """Bar vide -> score 0 -> RANGE."""
    scorer = RegimeScorer(BotMRConfig())
    rs = scorer.classify({}, "ES")
    assert rs.score == 0.0
    assert rs.regime == "RANGE"
    assert rs.panic is False
    assert rs.features == {
        "slope": 0.0, "swing": 0.0, "atr": 0.0,
        "delta": 0.0, "trend_day": 0.0,
    }


def test_classify_partial_features():
    """Bar avec seulement quelques fields -> score reduit mais coherent."""
    scorer = RegimeScorer(BotMRConfig())
    # Only slope dispo (ES bullish 1.5)
    bar = {"vwap_slope_30": 1.5}
    rs = scorer.classify(bar, "ES")
    # Contribution slope = (1.5 / 1.42 / 3) * 30 ~= 10.6
    assert 5.0 < rs.score < 15.0
    assert rs.regime == "RANGE"  # score <30
    assert rs.features["slope"] > 0
    assert rs.features["delta"] == 0.0
    assert rs.features["swing"] == 0.0


def test_classify_score_clipped_100():
    """Score ne depasse jamais +/- 100."""
    scorer = RegimeScorer(BotMRConfig())
    # Bar avec features toutes extremes positives
    bar = {
        "vwap_slope_30": 100.0,
        "bars_since_last_swing_high": 1,
        "bars_since_last_swing_low": 1000,
        "delta_day": 999_999,
        "ctx_trend_day_score": 5.0,
    }
    rs = scorer.classify(bar, "ES")
    assert rs.score <= 100.0
    assert rs.score >= -100.0


def test_classify_robust_to_bad_types():
    """Fields type bizarre (string non-castable) -> contrib 0 silencieux."""
    scorer = RegimeScorer(BotMRConfig())
    bar = {
        "vwap_slope_30": "abc",
        "bars_since_last_swing_high": "x",
        "delta_day": None,
        "ctx_trend_day_score": [],
        "vix_level": "bad",
    }
    rs = scorer.classify(bar, "ES")
    assert rs.score == 0.0
    assert rs.regime == "RANGE"


# ============================================================
# Integration SignalEngine
# ============================================================

def test_signal_engine_blocks_long_in_trend_down_strong():
    """SignalEngine integre : LONG bloque si TREND_DOWN_STRONG."""
    from CORE.bot_mean_revert.signal_engine import SignalEngine

    cfg = BotMRConfig()
    scorer = RegimeScorer(cfg)
    engine = SignalEngine(
        symbol="ES", cfg=cfg, regime_scorer=scorer,
    )
    # Force cooldown=0
    engine._bars_since_last_trade = cfg.COOLDOWN_BARS
    # Bar setup LONG (dist_vwap_d_sd3d_pct < 0) en regime TREND_DOWN_STRONG
    bar = {
        "ts": 1718726400000,
        "session_id": "US",
        "is_in_us_cash": True,
        "vwap_slope_30": -3.0,  # tres bearish ES (~2.1 sigma)
        "bars_since_last_swing_high": 100,
        "bars_since_last_swing_low": 5,
        "delta_day": -90_000,
        "ctx_trend_day_score": -0.8,
        "rvol_zscore": 1.5,
        "dist_vwap_d_sd3d_pct": -0.1,  # extension SD3
        "dist_vwap_d_sd3u_pct": 0.0,
        "close": 7500.0,
        "vix_level": 18.0,  # pas panic
        # Phase 4 18/06 : injecte delta_bar et anti-top defaults neutres pour
        # que le bar passe les nouveaux filtres et atteigne le scorer.
        # bars_since_last_swing_low=5 ci-dessus + dist_1d_min loin => anti-bottom OK
        # vu qu'on est LONG (l'anti-bottom est mirror pour SHORT).
        "delta_bar": 50.0,
        "vwap_slope_10": 0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }
    result = engine.evaluate(bar)
    assert result.tradable is False
    # Le scorer bloque AVANT regime hard filter (4bis-scorer execute en premier)
    # mais regime hard filter pourrait aussi bloquer. On verifie l'un OU l'autre.
    assert (
        "REGIME_SCORE_BLOCKED" in result.skip_reason
        or "REGIME_BEARISH_TREND" in result.skip_reason
        or "REGIME_TREND_ES_LONG_BLOCKED" in result.skip_reason
    )


def test_signal_engine_bypass_when_scorer_none():
    """SignalEngine sans scorer -> pas de check score (backward compat)."""
    from CORE.bot_mean_revert.signal_engine import SignalEngine

    cfg = BotMRConfig()
    engine = SignalEngine(symbol="ES", cfg=cfg)  # pas de regime_scorer
    assert engine.regime_scorer is None


def test_signal_engine_bypass_when_disabled(monkeypatch):
    """SignalEngine avec scorer mais REGIME_SCORER_ENABLED=False -> bypass."""
    from CORE.bot_mean_revert.signal_engine import SignalEngine

    monkeypatch.setenv("BOTMR_REGIME_SCORER_ENABLED", "false")
    cfg = BotMRConfig.from_env()
    assert cfg.REGIME_SCORER_ENABLED is False
    # Instancie scorer quand meme (kill-switch runtime, instance restee)
    scorer = RegimeScorer(cfg)
    engine = SignalEngine(symbol="ES", cfg=cfg, regime_scorer=scorer)
    # Cooldown ready
    engine._bars_since_last_trade = cfg.COOLDOWN_BARS
    # Bar TREND_DOWN_STRONG : devrait etre bloque par scorer si enabled
    bar = {
        "ts": 1718726400000,
        "session_id": "US",
        "is_in_us_cash": True,
        "vwap_slope_30": -3.0,
        "bars_since_last_swing_high": 100,
        "bars_since_last_swing_low": 5,
        "delta_day": -90_000,
        "ctx_trend_day_score": -0.8,
        "rvol_zscore": 1.5,
        "dist_vwap_d_sd3d_pct": -0.1,
        "dist_vwap_d_sd3u_pct": 0.0,
        "close": 7500.0,
        "vix_level": 18.0,
    }
    result = engine.evaluate(bar)
    # Scorer disabled -> ne doit PAS apparaitre dans skip_reason
    assert "REGIME_SCORE_BLOCKED" not in result.skip_reason
