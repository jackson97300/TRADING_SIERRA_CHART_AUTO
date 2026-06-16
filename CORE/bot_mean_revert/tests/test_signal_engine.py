"""Tests SignalEngine Bot MR."""
from __future__ import annotations

import time

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import SignalEngine


def _ts_now_us() -> int:
    """ts ms en plein milieu RTH US (15:00 UTC = 11:00 ET).

    15:00 UTC pour eviter le pre-open 11:30-13:30 UTC.
    """
    import datetime as _dt
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=15, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _ts_asia() -> int:
    """ts ms en pleine session Asia (02:00 UTC)."""
    import datetime as _dt
    today = _dt.datetime.now(tz=_dt.timezone.utc).replace(
        hour=2, minute=0, second=0, microsecond=0,
    )
    return int(today.timestamp() * 1000)


def _make_bar_es(direction: str, **overrides) -> dict:
    """Bar ES synthetique en session US RTH avec extension SD3.

    SignalEngine teste d_low <= -thr AVANT d_high >= thr donc avec thr=0.0
    le d_low par defaut (0.0) declenche LONG meme pour SHORT. On met une valeur
    strictement positive sur le cote NON utilise pour garantir le bon side.
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
        # SD3 extensions defaults : valeurs positives strictes pour eviter
        # detection LONG fortuite (d_low <= -0 == True si 0.0 default)
        "dist_vwap_d_sd3d_pct": 0.10,
        "dist_vwap_d_sd3u_pct": -0.10,
    }
    if direction == "LONG":
        bar["dist_vwap_d_sd3d_pct"] = -0.10  # prix sous SD3d
        bar["dist_vwap_d_sd3u_pct"] = -0.20
        bar["vwap_slope_30"] = 0.05  # trend up (trend_align_es LONG)
    elif direction == "SHORT":
        bar["dist_vwap_d_sd3u_pct"] = 0.10  # prix au-dessus SD3u
        bar["dist_vwap_d_sd3d_pct"] = 0.20
        bar["vwap_slope_30"] = -0.05  # trend down (trend_align_es SHORT)
    bar.update(overrides)
    return bar


def _make_bar_nq(direction: str, **overrides) -> dict:
    """Bar NQ synthetique en session Asia avec extension SD3."""
    bar = {
        "ts": _ts_asia(),
        "session_id": "ASIA",
        "is_in_us_cash": False,
        "close": 21000.0,
        "bar_high": 21002.0,
        "bar_low": 20998.0,
        "vix_level": 18.0,
        "rvol_zscore": 1.0,
        "ctx_trend_day_score": 0.3,
        "dist_vwap_d_sd3d_pct": 0.10,
        "dist_vwap_d_sd3u_pct": -0.10,
    }
    if direction == "LONG":
        bar["dist_vwap_d_sd3d_pct"] = -0.10
        bar["dist_vwap_d_sd3u_pct"] = -0.20
        bar["vwap_slope_30"] = -0.04  # NQ contrarian : LONG si slope<0
    elif direction == "SHORT":
        bar["dist_vwap_d_sd3u_pct"] = 0.10
        bar["dist_vwap_d_sd3d_pct"] = 0.20
        bar["vwap_slope_30"] = 0.04  # NQ contrarian : SHORT si slope>0
    bar.update(overrides)
    return bar


def test_long_es_sd3_baseline():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es("LONG")
    sig = eng.evaluate(bar)
    assert sig.tradable is True
    assert sig.direction == "LONG"
    assert sig.sl_ticks == 20
    assert sig.tp_ticks == 30  # 20 * 1.5
    assert sig.entry_price == 5800.0
    # SL = entry - 20*0.25 = 5795.0
    assert abs(sig.sl_price - 5795.0) < 1e-6
    # TP = entry + 30*0.25 = 5807.5
    assert abs(sig.tp_price - 5807.5) < 1e-6


def test_short_es_sd3_with_vix_floor():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    # VIX < 20 -> blocked
    bar = _make_bar_es("SHORT", vix_level=15.0)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "VIX_TOO_LOW" in sig.skip_reason
    # VIX >= 20 -> allowed (reset cooldown puisque previous emit a bump compteur)
    eng2 = SignalEngine("ES", cfg)
    bar2 = _make_bar_es("SHORT", vix_level=25.0)
    sig2 = eng2.evaluate(bar2)
    assert sig2.tradable is True
    assert sig2.direction == "SHORT"


def test_rvol_filter_blocks_low_volume():
    cfg = BotMRConfig()
    # Set RVOL_ZSCORE_MIN = 1.5 via monkeypatch dans dataclass via env
    import dataclasses
    cfg2 = dataclasses.replace(cfg, RVOL_ZSCORE_MIN=1.5)
    eng = SignalEngine("ES", cfg2)
    bar = _make_bar_es("LONG", rvol_zscore=0.5)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "RVOL_TOO_LOW" in sig.skip_reason


def test_regime_blocks_es_long_when_slope_negative():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es("LONG", vwap_slope_30=-0.05)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "REGIME_TREND_ES_LONG_BLOCKED" in sig.skip_reason


def test_regime_blocks_nq_short_when_trend_day_too_high():
    cfg = BotMRConfig()
    eng = SignalEngine("NQ", cfg)
    bar = _make_bar_nq("SHORT", ctx_trend_day_score=0.9)
    sig = eng.evaluate(bar)
    assert sig.tradable is False
    assert "NQ_TREND_DAY_TOO_HIGH" in sig.skip_reason


def test_cooldown_blocks_consecutive_signals():
    cfg = BotMRConfig()
    eng = SignalEngine("ES", cfg)
    bar = _make_bar_es("LONG")
    sig1 = eng.evaluate(bar)
    assert sig1.tradable is True
    eng.register_trade(sig1.signal_id)
    # Immediate next bar -> cooldown
    sig2 = eng.evaluate(bar)
    assert sig2.tradable is False
    assert "COOLDOWN" in sig2.skip_reason
