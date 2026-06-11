"""Tests Phase 0 sierra_format_adapters.py."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


SAMPLE_BAR = {
    "ts": 1781170560000,
    "sym": "NQ",
    "contract": "NQM26-CME",
    "close": 28869.0,
    "price": 28869.0,
    "bar_high": 28874.75,
    "bar_low": 28866.0,
    "open": 28873.0,
    "total_vol": 42.0,
    "buy_vol": 19.0,
    "sell_vol": 23.0,
    "vix_level": 20.64,
    "vix_regime": 1,
    "dist_vix_call": 4.36,
    "mq_call": 28900.0,
    "mq_put": 28500.0,
    "mq_hvl": 28850.0,
    "instrument_id": 12345,
}


def test_ohlcv_basic_conversion():
    """OHLCV adapter retourne champs essentiels."""
    from CORE.sierra_format_adapters import sierra_bar_to_databento_ohlcv
    ohlcv = sierra_bar_to_databento_ohlcv(SAMPLE_BAR)
    assert ohlcv["close"] == 28869.0
    assert ohlcv["high"] == 28874.75
    assert ohlcv["low"] == 28866.0
    assert ohlcv["volume"] == 42.0
    assert ohlcv["_source"] == "sierra"


def test_ohlcv_ts_conversion_ms_to_ns():
    """ts ms → ts_event_ns conversion correcte."""
    from CORE.sierra_format_adapters import sierra_bar_to_databento_ohlcv
    ohlcv = sierra_bar_to_databento_ohlcv(SAMPLE_BAR)
    assert ohlcv["ts_event_ns"] == 1781170560000 * 1_000_000


def test_ohlcv_ts_pd_timestamp_utc():
    """ts_event est pd.Timestamp tz=UTC."""
    import pandas as pd
    from CORE.sierra_format_adapters import sierra_bar_to_databento_ohlcv
    ohlcv = sierra_bar_to_databento_ohlcv(SAMPLE_BAR)
    assert isinstance(ohlcv["ts_event"], pd.Timestamp)
    assert ohlcv["ts_event"].tz is not None


def test_ohlcv_raises_on_missing_ts():
    """Raise ValueError si ts absent."""
    from CORE.sierra_format_adapters import sierra_bar_to_databento_ohlcv
    bar_no_ts = {k: v for k, v in SAMPLE_BAR.items() if k != "ts"}
    with pytest.raises(ValueError, match="missing 'ts'"):
        sierra_bar_to_databento_ohlcv(bar_no_ts)


def test_ohlcv_raises_on_invalid_ts_range():
    """Raise ValueError si ts hors plage realiste."""
    from CORE.sierra_format_adapters import sierra_bar_to_databento_ohlcv
    bar_bad_ts = dict(SAMPLE_BAR)
    bar_bad_ts["ts"] = 999  # trop petit
    with pytest.raises(ValueError, match="out of realistic"):
        sierra_bar_to_databento_ohlcv(bar_bad_ts)


def test_mq_levels_reconstruct():
    """MQ levels dict reconstruit depuis champs plats."""
    from CORE.sierra_format_adapters import sierra_bar_to_mq_levels
    mq = sierra_bar_to_mq_levels(SAMPLE_BAR)
    assert mq is not None
    assert mq["mq_call"] == 28900.0
    assert mq["mq_put"] == 28500.0
    assert mq["mq_hvl"] == 28850.0


def test_mq_levels_returns_none_if_absent():
    """MQ levels = None si tous absents."""
    from CORE.sierra_format_adapters import sierra_bar_to_mq_levels
    bar_no_mq = {k: v for k, v in SAMPLE_BAR.items() if not k.startswith("mq_")}
    assert sierra_bar_to_mq_levels(bar_no_mq) is None


def test_vix_dict_reconstruct():
    """VIX dict reconstruit depuis champs plats."""
    from CORE.sierra_format_adapters import sierra_bar_to_vix
    vix = sierra_bar_to_vix(SAMPLE_BAR)
    assert vix is not None
    assert vix["vix_level"] == 20.64
    assert vix["vix_regime"] == 1


def test_vix_returns_none_if_no_level():
    """VIX = None si vix_level absent."""
    from CORE.sierra_format_adapters import sierra_bar_to_vix
    bar_no_vix = {k: v for k, v in SAMPLE_BAR.items() if k != "vix_level"}
    assert sierra_bar_to_vix(bar_no_vix) is None


def test_composition_inputs():
    """Composition complete : inputs dict complet."""
    from CORE.sierra_format_adapters import sierra_inputs_to_enricher_inputs
    inputs = sierra_inputs_to_enricher_inputs(SAMPLE_BAR, tick=0.25)
    assert "ohlcv" in inputs
    assert "trades_df" in inputs
    assert "mq_levels" in inputs
    assert "vix" in inputs
    assert inputs["stream_alive"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
