"""Tests V_FINAL regime_classifier + integration signal_engine.

REFERENCE :
- Backtest market-analyst 24/06/2026 (sample 7j, 22929 bars, 67 trades).
- 5 regimes mutuellement exclusifs, seuils derives empiriquement.
- 3 regles blacklist : (PANIC,*), (CALM_RANGE,us_cash), (VOLATILE_RANGE,asia)
- Validation cross-period TRAIN/TEST/sans-FOMC : +$185/+$114/+$224 vs V1.
- Wins preserves 95% (sacrifice 1/20).

CES TESTS PROUVENT :
- Classification 5 regimes mutuellement exclusifs
- PANIC priorité absolue (VIX + ATR)
- TREND_DOWN/UP smoothing EWM persistance
- VOLATILE_RANGE / CALM_RANGE residuel
- Session UTC mapping (asia/london/us_cash/ah)
- Blacklist par défaut (V_FINAL)
- Multi-symbol isolation (ES EWM != NQ EWM)
- Backward compat REGIME_AWARE_ENABLED=False
- Features absentes fail-safe (default CALM_RANGE)
- Integration signal_engine : skip avec REGIME_SESSION_BLOCK
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.bot_mean_revert.regime_classifier import (
    Regime,
    RegimeClassifier,
    RegimeThresholds,
    detect_session_utc,
    parse_blacklist,
    is_blacklisted,
    DEFAULT_BLACKLIST_V_FINAL,
)


def _make_features(
    vix_level: float = 15.0,
    atr_14m_pct: float = 0.02,
    trend_day_probability: float = 0.1,
    vwap_slope_30: float = 0.0,
) -> dict:
    """Bar features minimales pour classifier."""
    return {
        "vix_level": vix_level,
        "atr_14m_pct": atr_14m_pct,
        "trend_day_probability": trend_day_probability,
        "vwap_slope_30": vwap_slope_30,
    }


# ==========================================================================
# RegimeThresholds defaults (correspondance backtest)
# ==========================================================================

def test_thresholds_defaults_include_vix_panic_extreme():
    """Fix audit 30/06 : ajout vix_panic_extreme = 25.0 (vrai event/crisis)."""
    t = RegimeThresholds()
    assert t.vix_panic_extreme == 25.0


def test_thresholds_defaults_match_backtest():
    """Default seuils == V_FINAL backtest market-analyst."""
    t = RegimeThresholds()
    assert t.vix_panic == 19.5
    assert t.atr_pct_panic == 0.076
    assert t.atr_pct_volatile == 0.048
    assert t.trend_probability_min == 0.35
    assert t.slope_smoothed_trend_down == -1.5
    assert t.slope_smoothed_trend_up == +1.5


# ==========================================================================
# Classification 5 regimes mutuellement exclusifs
# ==========================================================================

def test_panic_cross_feature_confirmed():
    """Fix audit 30/06 : VIX >= 19.5 ET atr_pct >= 0.076 (AND) -> PANIC."""
    clf = RegimeClassifier()
    feats = _make_features(vix_level=20.0, atr_14m_pct=0.08)
    assert clf.classify(feats, "ES") == Regime.PANIC


def test_panic_vix_extreme_alone():
    """Fix audit 30/06 : VIX >= 25.0 seul (event-driven crisis) -> PANIC.

    Fallback pour event news/crisis ou ATR n'a pas encore propage.
    """
    clf = RegimeClassifier()
    feats = _make_features(vix_level=26.0, atr_14m_pct=0.03)  # ATR calme
    assert clf.classify(feats, "ES") == Regime.PANIC


def test_panic_vix_alone_sub_extreme_NOT_panic():
    """Fix audit 30/06 : VIX >= 19.5 SEUL (sans ATR confirme) -> PAS PANIC.

    Anti-faux-positif. VIX 19.5-25 sans ATR confirme = haute vol mais
    pas illiquide. Le bot peut tradeer MR normalement.
    """
    clf = RegimeClassifier()
    feats = _make_features(vix_level=22.0, atr_14m_pct=0.03)  # ATR calme
    # VIX 22 sub-extreme + ATR calme = pas vrai PANIC
    result = clf.classify(feats, "ES")
    assert result != Regime.PANIC, f"Got {result}, expected non-PANIC"


def test_panic_atr_alone_NOT_panic():
    """Fix audit 30/06 : atr_pct >= 0.076 SEUL (sans VIX confirme) -> PAS PANIC.

    Anti-faux-positif critique. ATR cumul drift sans VIX = 91% des
    anciens faux positifs (cf audit weekend + 1583 bars/sem libres).
    """
    clf = RegimeClassifier()
    feats = _make_features(vix_level=15.0, atr_14m_pct=0.08)  # VIX calme
    # ATR cumul sans VIX = pas vrai PANIC (anti-drift)
    result = clf.classify(feats, "NQ")
    assert result != Regime.PANIC, f"Got {result}, expected non-PANIC"


def test_panic_priority_over_trend():
    """PANIC ecrase TREND meme si conditions trend remplies (via cross-confirm)."""
    clf = RegimeClassifier()
    feats = _make_features(
        vix_level=26.0,  # > 25 -> fallback extreme suffit seul
        trend_day_probability=0.8,
        vwap_slope_30=-3.0,
        atr_14m_pct=0.03,  # ATR calme mais VIX extreme prend priorite
    )
    # PANIC fallback via vix_panic_extreme (25) gagne sur TREND
    assert clf.classify(feats, "ES") == Regime.PANIC


def test_panic_AND_priority_over_trend():
    """Fix audit 30/06 R3 review : AND cross-confirmation ecrase TREND.

    Trou de coverage detecte par code-reviewer : test_panic_priority_over_trend
    utilise VIX 26 (fallback extreme). Ce test couvre le scenario AND
    (VIX 20 ET ATR 0.08 simultanement) vs conditions TREND fortes.
    """
    clf = RegimeClassifier()
    feats = _make_features(
        vix_level=20.0,  # < 25 -> fallback extreme PAS declenche
        atr_14m_pct=0.08,  # > 0.076 + VIX > 19.5 -> AND PANIC trigger
        trend_day_probability=0.8,  # conditions TREND fortes
        vwap_slope_30=-3.0,
    )
    # AND PANIC (VIX 20 ET ATR 0.08) gagne sur TREND
    assert clf.classify(feats, "ES") == Regime.PANIC


def test_trend_down_requires_probability():
    """slope tres negatif mais trend_prob faible → CALM_RANGE pas TREND_DOWN."""
    clf = RegimeClassifier()
    feats = _make_features(
        vwap_slope_30=-5.0,  # tres bearish
        trend_day_probability=0.1,  # mais probability bas
        atr_14m_pct=0.02,
    )
    # trend_prob 0.1 < 0.35 → pas TREND_DOWN
    assert clf.classify(feats, "ES") == Regime.CALM_RANGE


def test_trend_down_full_conditions():
    """trend_prob >= 0.35 + slope_smoothed <= -1.5 → TREND_DOWN."""
    clf = RegimeClassifier()
    # Premier appel : EWM = valeur brute
    feats = _make_features(
        vwap_slope_30=-2.0,
        trend_day_probability=0.5,
        atr_14m_pct=0.03,
    )
    assert clf.classify(feats, "ES") == Regime.TREND_DOWN


def test_trend_up_full_conditions():
    """trend_prob >= 0.35 + slope_smoothed >= +1.5 → TREND_UP."""
    clf = RegimeClassifier()
    feats = _make_features(
        vwap_slope_30=+2.0,
        trend_day_probability=0.5,
    )
    assert clf.classify(feats, "NQ") == Regime.TREND_UP


def test_volatile_range_no_trend():
    """atr_pct >= 0.048 mais pas trend → VOLATILE_RANGE."""
    clf = RegimeClassifier()
    feats = _make_features(
        atr_14m_pct=0.05,  # > 0.048 mais < 0.076 (panic)
        trend_day_probability=0.1,  # pas trend
    )
    assert clf.classify(feats, "ES") == Regime.VOLATILE_RANGE


def test_calm_range_default():
    """Aucune condition special → CALM_RANGE (residuel)."""
    clf = RegimeClassifier()
    feats = _make_features(
        vix_level=14.0,
        atr_14m_pct=0.02,
        trend_day_probability=0.1,
        vwap_slope_30=0.5,
    )
    assert clf.classify(feats, "ES") == Regime.CALM_RANGE


def test_classify_5_regimes_mutually_exclusive():
    """Verifier qu'aucune feature combination retourne 2 regimes simultanement."""
    clf = RegimeClassifier()
    # On teste tous les cas par sub-test (post-fix audit 30/06 AND cross-feature)
    test_cases = [
        # (vix, atr, trend_prob, slope, expected) - post-fix audit 30/06
        # PANIC cas valides post-fix
        (26.0, 0.02, 0.1, 0.0, Regime.PANIC),  # VIX extreme seul (>=25) -> PANIC fallback
        (20.0, 0.08, 0.1, 0.0, Regime.PANIC),  # AND cross-confirmation
        # Anti-faux-positif post-fix : ne doivent PAS etre PANIC
        # VIX 15 + ATR 0.08 = ancien faux positif -> maintenant VOLATILE_RANGE
        (15.0, 0.08, 0.1, 0.0, Regime.VOLATILE_RANGE),  # atr_pct > volatile=0.048
        (15.0, 0.03, 0.5, -2.0, Regime.TREND_DOWN),
        (15.0, 0.03, 0.5, +2.0, Regime.TREND_UP),
        (15.0, 0.05, 0.1, 0.0, Regime.VOLATILE_RANGE),
        (14.0, 0.02, 0.1, 0.5, Regime.CALM_RANGE),
    ]
    for vix, atr, prob, slope, expected in test_cases:
        clf.reset()  # Reset EWM pour chaque sub-case
        feats = _make_features(vix, atr, prob, slope)
        result = clf.classify(feats, "ES")
        assert result == expected, f"vix={vix} atr={atr} prob={prob} slope={slope}: expected {expected}, got {result}"


# ==========================================================================
# EWM smoothing slope_30 (statefulness + isolation par-symbole)
# ==========================================================================

def test_ewm_first_call_equals_input():
    """1er appel : EWM = slope brut (pas d'historique)."""
    clf = RegimeClassifier()
    feats = _make_features(vwap_slope_30=-3.0)
    clf.classify(feats, "ES")
    assert clf.get_slope_smoothed("ES") == -3.0


def test_ewm_subsequent_smoothing():
    """EWM smoothe vers nouvelle valeur progressivement."""
    clf = RegimeClassifier(ewm_alpha=0.4)
    feats_1 = _make_features(vwap_slope_30=-3.0)
    feats_2 = _make_features(vwap_slope_30=+3.0)
    clf.classify(feats_1, "ES")  # EWM = -3.0
    clf.classify(feats_2, "ES")  # EWM = 0.4 * 3 + 0.6 * (-3) = 1.2 - 1.8 = -0.6
    assert abs(clf.get_slope_smoothed("ES") - (-0.6)) < 1e-6


def test_ewm_isolation_per_symbol():
    """ES et NQ ont des historiques EWM independants."""
    clf = RegimeClassifier()
    feats_es = _make_features(vwap_slope_30=-3.0)
    feats_nq = _make_features(vwap_slope_30=+5.0)
    clf.classify(feats_es, "ES")
    clf.classify(feats_nq, "NQ")
    assert clf.get_slope_smoothed("ES") == -3.0
    assert clf.get_slope_smoothed("NQ") == +5.0
    # No cross-contamination
    assert clf.get_slope_smoothed("ES") != clf.get_slope_smoothed("NQ")


def test_ewm_reset_clears_state():
    """reset() clear EWM history."""
    clf = RegimeClassifier()
    clf.classify(_make_features(vwap_slope_30=-2.0), "ES")
    assert clf.get_slope_smoothed("ES") is not None
    clf.reset()
    assert clf.get_slope_smoothed("ES") is None


def test_ewm_invalid_alpha_raises():
    """alpha out of (0, 1] raise ValueError."""
    with pytest.raises(ValueError):
        RegimeClassifier(ewm_alpha=0.0)
    with pytest.raises(ValueError):
        RegimeClassifier(ewm_alpha=1.5)
    with pytest.raises(ValueError):
        RegimeClassifier(ewm_alpha=-0.1)


# ==========================================================================
# Sessions UTC
# ==========================================================================

@pytest.mark.parametrize("hour,expected", [
    (0, "asia"), (3, "asia"), (6, "asia"),
    (7, "london"), (10, "london"), (12, "london"),
    (13, "us_cash"), (15, "us_cash"), (20, "us_cash"),
    (21, "ah"), (22, "ah"), (23, "ah"),
])
def test_detect_session_utc(hour, expected):
    """Mapping heure UTC → session."""
    assert detect_session_utc(hour) == expected


# ==========================================================================
# Blacklist parse + check
# ==========================================================================

def test_parse_blacklist_v_final_defaults():
    """V_FINAL blacklist expansion."""
    blacklist = parse_blacklist(DEFAULT_BLACKLIST_V_FINAL)
    # PANIC:* → expansé à toutes les sessions
    assert ("PANIC", "asia") in blacklist
    assert ("PANIC", "london") in blacklist
    assert ("PANIC", "us_cash") in blacklist
    assert ("PANIC", "ah") in blacklist
    # CALM_RANGE:us_cash exact
    assert ("CALM_RANGE", "us_cash") in blacklist
    # VOLATILE_RANGE:asia exact
    assert ("VOLATILE_RANGE", "asia") in blacklist
    # Pas dans blacklist
    assert ("CALM_RANGE", "asia") not in blacklist
    assert ("TREND_DOWN", "us_cash") not in blacklist


def test_parse_blacklist_ignores_invalid_format():
    """Format invalide ignore silencieusement."""
    blacklist = parse_blacklist(["INVALID", "CALM_RANGE:asia", "BAD_FORMAT_NO_COLON"])
    assert ("CALM_RANGE", "asia") in blacklist
    assert len(blacklist) == 1  # seul le valide


def test_parse_blacklist_case_insensitive_session():
    """Sessions tolerent case mixte (assure normalisation)."""
    blacklist = parse_blacklist(["CALM_RANGE:US_CASH", "PANIC:Asia"])
    assert ("CALM_RANGE", "us_cash") in blacklist
    assert ("PANIC", "asia") in blacklist


def test_is_blacklisted_v_final():
    """V_FINAL : 3 règles d'exclusion match."""
    blacklist = parse_blacklist(DEFAULT_BLACKLIST_V_FINAL)
    # PANIC bloque toute session
    assert is_blacklisted(Regime.PANIC, "asia", blacklist)
    assert is_blacklisted(Regime.PANIC, "us_cash", blacklist)
    # CALM_RANGE bloque seulement us_cash
    assert is_blacklisted(Regime.CALM_RANGE, "us_cash", blacklist)
    assert not is_blacklisted(Regime.CALM_RANGE, "asia", blacklist)
    # VOLATILE_RANGE bloque seulement asia
    assert is_blacklisted(Regime.VOLATILE_RANGE, "asia", blacklist)
    assert not is_blacklisted(Regime.VOLATILE_RANGE, "us_cash", blacklist)
    # TREND_DOWN/UP pas dans blacklist
    assert not is_blacklisted(Regime.TREND_DOWN, "us_cash", blacklist)
    assert not is_blacklisted(Regime.TREND_UP, "asia", blacklist)


# ==========================================================================
# Features absentes (fail-safe)
# ==========================================================================

def test_classify_no_features_default_calm():
    """Aucune feature → CALM_RANGE (default conservateur)."""
    clf = RegimeClassifier()
    result = clf.classify({}, "ES")
    assert result == Regime.CALM_RANGE


def test_classify_corrupted_features_default_calm():
    """Features corrompues → CALM_RANGE (fail-safe pas PANIC)."""
    clf = RegimeClassifier()
    feats = {
        "vix_level": "not_a_number",
        "atr_14m_pct": None,
        "trend_day_probability": [1, 2, 3],
        "vwap_slope_30": "?",
    }
    result = clf.classify(feats, "ES")
    assert result == Regime.CALM_RANGE


# ==========================================================================
# Configuration thresholds custom
# ==========================================================================

def test_classify_custom_thresholds():
    """Override RegimeThresholds custom."""
    custom = RegimeThresholds(
        vix_panic=30.0,  # Plus laxe
        atr_pct_panic=0.20,
        vix_panic_extreme=35.0,  # Aussi remonte (sinon default 22.0 declenche)
        atr_pct_volatile=0.10,
        trend_probability_min=0.50,
        slope_smoothed_trend_down=-3.0,
        slope_smoothed_trend_up=+3.0,
    )
    clf = RegimeClassifier(thresholds=custom)
    feats = _make_features(vix_level=22.0)  # < 30 custom + < 35 extreme custom
    # Avec default → PANIC ; avec custom 30 → pas PANIC
    assert clf.classify(feats, "ES") != Regime.PANIC


# ==========================================================================
# Integration signal_engine (backward compat + skip BLOCK)
# ==========================================================================

def test_integration_signal_engine_blocks_panic(tmp_path):
    """SignalEngine bloque trade si regime=PANIC + REGIME_AWARE_ENABLED."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore
    from CORE.bot_mean_revert.regime_classifier import RegimeClassifier

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_panic_block.json")
    clf = RegimeClassifier()
    eng = SignalEngine(
        "ES", cfg, store=store,
        regime_classifier_v_final=clf,
    )

    # Bar avec VIX 25 = PANIC
    bar_dt = datetime(2026, 6, 24, 15, 30, 0, tzinfo=timezone.utc)
    bar = {
        "ts": int(bar_dt.timestamp() * 1000),
        "ts_event": bar_dt.isoformat(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 5800.0,
        "bar_high": 5801.0, "bar_low": 5799.0,
        "vix_level": 25.0,  # PANIC trigger
        "atr_14m_pct": 0.02,
        "trend_day_probability": 0.1,
        "vwap_slope_30": 0.0,
        "rvol_zscore": 1.0,
        "dist_vwap_d_sd3d_pct": -0.05,
        "dist_vwap_d_sd3u_pct": 0.5,
        "dist_vwap_d_pct": 0.1,
        "delta_bar": -50.0,
        "finish_strength": 1.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "momentum_5b": 0.0,
        "dist_mq_hvl_pct": 5.0,
        "dist_mq_hvl_0dte_pct": 5.0,
        "dist_mq_call_pct": 5.0,
        "dist_mq_call_0dte_pct": 5.0,
        "dist_mq_put_pct": -5.0,
        "dist_mq_put_0dte_pct": -5.0,
        "dist_gex_nearest_up_pct": 5.0,
        "dist_gex_nearest_dn_pct": -5.0,
        "dist_1d_max_ticks": 200.0,
        "dist_1d_min_ticks": -200.0,
        "dist_vwap_d_sd1d_pct": -3.0,
        "dist_vwap_w_sd1d_pct": -3.0,
    }
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "REGIME_SESSION_BLOCK" in sig.skip_reason
    assert "PANIC" in sig.skip_reason


def test_integration_backward_compat_disabled(tmp_path, monkeypatch):
    """REGIME_AWARE_ENABLED=False → comportement identique (skip gate)."""
    monkeypatch.setenv("BOTMR_REGIME_AWARE_ENABLED", "false")
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore
    from CORE.bot_mean_revert.regime_classifier import RegimeClassifier

    cfg = BotMRConfig.from_env()
    assert cfg.REGIME_AWARE_ENABLED is False

    store = PositionStore(path=tmp_path / "test_disabled.json")
    clf = RegimeClassifier()
    eng = SignalEngine(
        "ES", cfg, store=store,
        regime_classifier_v_final=clf,
    )

    bar_dt = datetime(2026, 6, 24, 15, 30, 0, tzinfo=timezone.utc)
    bar = {
        "ts": int(bar_dt.timestamp() * 1000),
        "ts_event": bar_dt.isoformat(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 5800.0, "bar_high": 5801.0, "bar_low": 5799.0,
        "vix_level": 25.0,  # PANIC (mais gate disabled)
        "atr_14m_pct": 0.02,
        "trend_day_probability": 0.1,
        "vwap_slope_30": 0.0,
        "rvol_zscore": 1.0,
        "dist_vwap_d_sd3d_pct": -0.05,
        "dist_vwap_d_sd3u_pct": 0.5,
        "dist_vwap_d_pct": 0.1,
        "delta_bar": -50.0, "finish_strength": 1.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "momentum_5b": 0.0,
        "dist_mq_hvl_pct": 5.0, "dist_mq_hvl_0dte_pct": 5.0,
        "dist_mq_call_pct": 5.0, "dist_mq_call_0dte_pct": 5.0,
        "dist_mq_put_pct": -5.0, "dist_mq_put_0dte_pct": -5.0,
        "dist_gex_nearest_up_pct": 5.0, "dist_gex_nearest_dn_pct": -5.0,
        "dist_1d_max_ticks": 200.0, "dist_1d_min_ticks": -200.0,
        "dist_vwap_d_sd1d_pct": -3.0, "dist_vwap_w_sd1d_pct": -3.0,
    }
    sig = eng.evaluate(bar)
    # Gate disabled : pas de REGIME_SESSION_BLOCK
    assert "REGIME_SESSION_BLOCK" not in sig.skip_reason


def test_integration_signal_engine_no_classifier_skip(tmp_path):
    """SignalEngine sans regime_classifier_v_final → skip gate (backward compat)."""
    from CORE.bot_mean_revert.config import BotMRConfig
    from CORE.bot_mean_revert.signal_engine import SignalEngine
    from CORE.bot1_v2.state.position_store import PositionStore

    cfg = BotMRConfig()
    store = PositionStore(path=tmp_path / "test_no_clf.json")
    # PAS de regime_classifier_v_final injecte
    eng = SignalEngine("ES", cfg, store=store)

    bar_dt = datetime(2026, 6, 24, 15, 30, 0, tzinfo=timezone.utc)
    bar = {
        "ts": int(bar_dt.timestamp() * 1000),
        "ts_event": bar_dt.isoformat(),
        "session_id": "US", "is_in_us_cash": True,
        "close": 5800.0, "bar_high": 5801.0, "bar_low": 5799.0,
        "vix_level": 25.0,  # PANIC mais pas de classifier
        "atr_14m_pct": 0.02, "trend_day_probability": 0.1,
        "vwap_slope_30": 0.0, "rvol_zscore": 1.0,
        "dist_vwap_d_sd3d_pct": -0.05, "dist_vwap_d_sd3u_pct": 0.5,
        "dist_vwap_d_pct": 0.1,
        "delta_bar": -50.0, "finish_strength": 1.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1, "momentum_5b": 0.0,
        "dist_mq_hvl_pct": 5.0, "dist_mq_hvl_0dte_pct": 5.0,
        "dist_mq_call_pct": 5.0, "dist_mq_call_0dte_pct": 5.0,
        "dist_mq_put_pct": -5.0, "dist_mq_put_0dte_pct": -5.0,
        "dist_gex_nearest_up_pct": 5.0, "dist_gex_nearest_dn_pct": -5.0,
        "dist_1d_max_ticks": 200.0, "dist_1d_min_ticks": -200.0,
        "dist_vwap_d_sd1d_pct": -3.0, "dist_vwap_w_sd1d_pct": -3.0,
    }
    sig = eng.evaluate(bar)
    # Pas de classifier → pas de REGIME_SESSION_BLOCK
    assert "REGIME_SESSION_BLOCK" not in sig.skip_reason
