"""Tests Regime hard filter Bot MR (anti catch falling knife - 18/06/2026).

Reference : carnage 18/06 -$1025 broker E-mini sur 4 LONGs ES en descente
7568 -> 7533. Le mode trend_align_es existant bloque slope <= 0 mais ne dit
rien sur l'amplitude. Ce filtre ABSOLU est la ceinture-bretelles cas extreme.

Couvre :
  - Defaults config (4 fields + helper _env_bool)
  - Env var override SLOPE_30_MIN_LONG
  - SignalEngine : LONG bloque si slope_30 < -1.5
  - SignalEngine : SHORT bloque si slope_30 > +1.5
  - SignalEngine : VIX panic (mode pct vs open) bloque
  - SignalEngine : VIX panic absolu (fallback sans vix_open_session) bloque
  - SignalEngine : neutre passe (slope -0.5 > -1.5)
  - REGIME_FILTER_ENABLED=False -> bypass total
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import os

import pytest

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import SignalEngine


def _ts_now_us() -> int:
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=15, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _make_bar_es_long(**overrides) -> dict:
    """Bar ES en session US RTH avec extension SD3d (LONG MR).

    Defaults : slope_30 = 0.05 (passe trend_align_es), VIX 22 (passe VIX_MIN_SHORT).
    """
    bar = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 5800.0,
        "bar_high": 5801.0,
        "bar_low": 5799.0,
        "vix_level": 22.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": -0.10,
        "dist_vwap_d_sd3u_pct": -0.20,
        "vwap_slope_30": 0.05,
        # Phase 4 18/06 defaults neutres
        "delta_bar": 50.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": 0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }
    bar.update(overrides)
    return bar


def _make_bar_es_short(**overrides) -> dict:
    """Bar ES en session US RTH avec extension SD3u (SHORT MR).

    Defaults : slope_30 = -0.05 (passe trend_align_es), VIX 25 (passe VIX_MIN_SHORT).
    """
    bar = {
        "ts": _ts_now_us(),
        "session_id": "US",
        "is_in_us_cash": True,
        "close": 5800.0,
        "bar_high": 5801.0,
        "bar_low": 5799.0,
        "vix_level": 25.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3u_pct": 0.10,
        "dist_vwap_d_sd3d_pct": 0.20,
        "vwap_slope_30": -0.05,
        # Phase 4 18/06 defaults neutres
        "delta_bar": -50.0,
        "bars_since_last_swing_high": 30.0,
        "bars_since_last_swing_low": 30.0,
        "vwap_slope_10": -0.1,
        "dist_1d_max_ticks": -100.0,
        "dist_1d_min_ticks": 100.0,
    }
    bar.update(overrides)
    return bar


# ===========================================================================
# Config defaults + env override
# ===========================================================================


def test_default_regime_thresholds():
    """Defaults specs Jackson 18/06 - RECALIBRAGE post-carnage : -0.3 / 0.3."""
    cfg = BotMRConfig()
    assert cfg.REGIME_FILTER_ENABLED is True
    assert cfg.SLOPE_30_MIN_LONG == -0.3
    assert cfg.SLOPE_30_MAX_SHORT == 0.3
    assert cfg.VIX_INTRADAY_SPIKE_PCT == 15.0
    assert cfg.VIX_ABS_PANIC == 30.0


def test_default_regime_thresholds_per_symbol():
    """Phase 2 18/06 : seuils par symbole calibres empiriquement.

    Calibration empirique 9j ES+NQ : stdev NQ slope_30 = 8.54 vs ES 1.42.
    Seuils echelles : ES +/- 0.5, NQ +/- 3.0 (6x echelle).
    """
    cfg = BotMRConfig()
    assert cfg.SLOPE_30_MIN_LONG_ES == -0.5
    assert cfg.SLOPE_30_MAX_SHORT_ES == 0.5
    assert cfg.SLOPE_30_MIN_LONG_NQ == -3.0
    assert cfg.SLOPE_30_MAX_SHORT_NQ == 3.0


def test_slope_30_helpers_per_symbol():
    """Helpers slope_30_min_long / max_short retournent les bonnes valeurs par symbole."""
    cfg = BotMRConfig()
    # ES
    assert cfg.slope_30_min_long("ES") == -0.5
    assert cfg.slope_30_min_long("es") == -0.5  # case insensitive
    assert cfg.slope_30_max_short("ES") == 0.5
    # NQ
    assert cfg.slope_30_min_long("NQ") == -3.0
    assert cfg.slope_30_max_short("NQ") == 3.0
    # MGC -> fallback generique
    assert cfg.slope_30_min_long("MGC") == -0.3
    assert cfg.slope_30_max_short("MGC") == 0.3
    # Unknown -> fallback generique
    assert cfg.slope_30_min_long("ZZ") == -0.3
    assert cfg.slope_30_max_short("ZZ") == 0.3


def test_env_override_per_symbol_slope():
    """BOTMR_SLOPE_30_MIN_LONG_NQ=-5.0 override le default."""
    os.environ["BOTMR_SLOPE_30_MIN_LONG_NQ"] = "-5.0"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.SLOPE_30_MIN_LONG_NQ == -5.0
        assert cfg.slope_30_min_long("NQ") == -5.0
    finally:
        del os.environ["BOTMR_SLOPE_30_MIN_LONG_NQ"]


def test_env_override_slope_min_long():
    """BOTMR_SLOPE_30_MIN_LONG=-2.0 -> cfg.SLOPE_30_MIN_LONG == -2.0."""
    os.environ["BOTMR_SLOPE_30_MIN_LONG"] = "-2.0"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.SLOPE_30_MIN_LONG == -2.0
    finally:
        del os.environ["BOTMR_SLOPE_30_MIN_LONG"]


def test_env_override_regime_disabled():
    """BOTMR_REGIME_FILTER_ENABLED=0 -> cfg.REGIME_FILTER_ENABLED is False."""
    os.environ["BOTMR_REGIME_FILTER_ENABLED"] = "0"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.REGIME_FILTER_ENABLED is False
    finally:
        del os.environ["BOTMR_REGIME_FILTER_ENABLED"]


def test_env_override_vix_thresholds():
    os.environ["BOTMR_VIX_INTRADAY_SPIKE_PCT"] = "20.0"
    os.environ["BOTMR_VIX_ABS_PANIC"] = "35.0"
    try:
        cfg = BotMRConfig.from_env()
        assert cfg.VIX_INTRADAY_SPIKE_PCT == 20.0
        assert cfg.VIX_ABS_PANIC == 35.0
    finally:
        del os.environ["BOTMR_VIX_INTRADAY_SPIKE_PCT"]
        del os.environ["BOTMR_VIX_ABS_PANIC"]


# ===========================================================================
# SignalEngine : regime hard filter applique
# ===========================================================================


def test_signal_engine_blocks_bearish_long():
    """Slope -2.5 < -1.5 -> LONG bloque REGIME_BEARISH_TREND."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vwap_slope_30=-2.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert sig.direction == "LONG"
    assert "REGIME_BEARISH_TREND" in sig.skip_reason
    assert "-2.5" in sig.skip_reason


def test_signal_engine_blocks_bullish_short():
    """Slope +2.5 > +1.5 -> SHORT bloque REGIME_BULLISH_TREND.

    NB : pour SHORT on doit passer ctx_trend_day_score bas (sinon NQ regime peut
    aussi rejeter). ES trend_align_es n'a pas ce check sur trend_day.
    """
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_short(vwap_slope_30=2.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert sig.direction == "SHORT"
    # 2 chemins valides : soit le hard filter SHORT (slope > 1.5), soit le mode
    # trend_align_es (slope > 0 deja). On veut prouver que le hard filter agit.
    # En l'occurrence step 4ter execute AVANT step 7 regime mode, donc REGIME_BULLISH_TREND
    # doit etre raison vue.
    assert "REGIME_BULLISH_TREND" in sig.skip_reason


def test_signal_engine_allows_neutral_slope():
    """Slope -0.2 > -0.3 -> hard filter passe (recalibrage 18/06)."""
    cfg = BotMRConfig()
    object.__setattr__(cfg, "REGIME_FILTER_MODE_ES", "off")
    object.__setattr__(cfg, "CONFLUENCE_FILTER_ENABLED", False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vwap_slope_30=-0.2)
    sig = eng.evaluate(bar)
    assert sig.tradable is True, f"skip_reason={sig.skip_reason}"
    assert sig.direction == "LONG"


def test_signal_engine_allows_at_boundary():
    """Slope = -0.3 EXACTEMENT -> LONG accepte (test strict < pas <=)."""
    cfg = BotMRConfig()
    object.__setattr__(cfg, "REGIME_FILTER_MODE_ES", "off")
    object.__setattr__(cfg, "CONFLUENCE_FILTER_ENABLED", False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vwap_slope_30=-0.3)
    sig = eng.evaluate(bar)
    # -0.3 < -0.3 == False donc passe le hard filter
    assert sig.tradable is True, f"skip_reason={sig.skip_reason}"


def test_regime_disabled_bypass_total():
    """REGIME_FILTER_ENABLED=False -> hard filter bypass meme slope -10.0.

    Desactive aussi REGIME_FILTER_MODE_ES + confluence pour isoler le bypass.
    """
    cfg = BotMRConfig()
    object.__setattr__(cfg, "REGIME_FILTER_ENABLED", False)
    object.__setattr__(cfg, "REGIME_FILTER_MODE_ES", "off")
    object.__setattr__(cfg, "CONFLUENCE_FILTER_ENABLED", False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vwap_slope_30=-10.0)
    sig = eng.evaluate(bar)
    # Aucun filtre regime actif -> trade passe meme slope extreme bearish
    assert sig.tradable is True, f"skip_reason={sig.skip_reason}"


# ===========================================================================
# VIX panic
# ===========================================================================


def test_vix_panic_intraday_blocks():
    """VIX 25 vs vix_open_session 20 = +25% > 15% -> blocked."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    # Le mode trend_align_es passe avec slope=0.05 ; LONG ok base
    bar = _make_bar_es_long(vix_level=25.0, vix_open_session=20.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "REGIME_VIX_PANIC" in sig.skip_reason
    # Verifie format pct (pas absolu)
    assert "%" in sig.skip_reason


def test_vix_panic_intraday_allows_small_spike():
    """VIX 21 vs vix_open_session 20 = +5% < 15% -> passe le regime hard filter.

    On desactive confluence (orthogonal) pour isoler le check VIX.
    """
    cfg = BotMRConfig()
    object.__setattr__(cfg, "CONFLUENCE_FILTER_ENABLED", False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vix_level=21.0, vix_open_session=20.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is True, f"skip_reason={sig.skip_reason}"


def test_vix_panic_absolute_fallback():
    """Pas de vix_open_session -> VIX 32 >= 30.0 -> blocked REGIME_VIX_PANIC_ABS."""
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    # vix_open_session absent (=0.0 default _f)
    bar = _make_bar_es_long(vix_level=32.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "REGIME_VIX_PANIC_ABS" in sig.skip_reason


def test_vix_panic_absolute_fallback_below_threshold():
    """VIX 22 sans vix_open_session -> passe le regime hard filter (< 30 absolu).

    On desactive confluence (orthogonal au scope regime).
    """
    cfg = BotMRConfig()
    object.__setattr__(cfg, "CONFLUENCE_FILTER_ENABLED", False)
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es_long(vix_level=22.0)  # < 30
    sig = eng.evaluate(bar)
    assert sig.tradable is True, f"skip_reason={sig.skip_reason}"
