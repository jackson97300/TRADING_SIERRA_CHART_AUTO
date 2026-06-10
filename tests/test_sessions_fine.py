"""Tests Phase 3.4 sessions_fine.py (Sierra Migration 10/06/2026)."""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))

ET = ZoneInfo("America/New_York")


def _et_to_utc(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET).astimezone(timezone.utc)


# ────────────────────────────────────────────────────────────────────────────
# Tests session segments
# ────────────────────────────────────────────────────────────────────────────

def test_segment_asia_avant_03h_et():
    """01:00 ET -> asia (suite Asia debutee veille 18:00 ET)."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 1, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_segment"] == "asia"
    assert f["is_in_asia"] is True
    assert f["is_in_london"] is False
    assert f["is_in_us_cash"] is False


def test_segment_london_apres_03h_et():
    """05:00 ET -> london (03:00-09:30 ET)."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 5, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_segment"] == "london"
    assert f["is_in_london"] is True


def test_segment_us_cash_a_10h_et():
    """10:00 ET -> us_cash (09:30-16:00 ET)."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_segment"] == "us_cash"
    assert f["is_in_us_cash"] is True
    assert f["is_cash_session"] is True


def test_segment_us_after_a_17h_et():
    """17:00 ET -> us_after (16:00-18:00 ET)."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 17, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_segment"] == "us_after"
    assert f["is_in_us_after"] is True


def test_segment_asia_apres_18h_et_nouveau_trading_date():
    """18:30 ET -> asia (debut nouveau session_date_trading)."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 18, 30)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_segment"] == "asia"
    assert f["is_in_asia"] is True


# ────────────────────────────────────────────────────────────────────────────
# Tests IB window
# ────────────────────────────────────────────────────────────────────────────

def test_is_ib_window_a_10h_et():
    """09:45 ET -> dans IB window (premiere heure RTH)."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 9, 45)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["is_ib_window"] is True


def test_is_ib_window_false_apres_1030_et():
    """10:45 ET -> hors IB window."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 10, 45)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["is_ib_window"] is False
    assert f["is_in_us_cash"] is True


def test_is_ib_window_false_hors_us_cash():
    """05:00 ET (London) -> is_ib_window False."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 5, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["is_ib_window"] is False


# ────────────────────────────────────────────────────────────────────────────
# Tests per-session highs/lows + opens
# ────────────────────────────────────────────────────────────────────────────

def test_ny_open_snapshot_a_930_et():
    """Premiere bar 09:30 ET RTH -> ny_open = close."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()

    # Pre-cash 09:00 ET
    ts_pre = _et_to_utc(2026, 6, 10, 9, 0)
    f_pre = calc.update(bar_ts_utc=ts_pre, bar_high=99.0, bar_low=97.0, close=98.0)
    assert math.isnan(f_pre["ny_open"])

    # 09:30 ET open
    ts_open = _et_to_utc(2026, 6, 10, 9, 30)
    f_open = calc.update(bar_ts_utc=ts_open, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f_open["ny_open"] == 99.5
    assert f_open["us_high"] == 100.0
    assert f_open["us_low"] == 99.0


def test_london_high_running():
    """London high/low tracke en running max/min sur la session."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()

    # London 05:00 ET
    ts1 = _et_to_utc(2026, 6, 10, 5, 0)
    calc.update(bar_ts_utc=ts1, bar_high=100.0, bar_low=99.0, close=99.5)

    ts2 = _et_to_utc(2026, 6, 10, 7, 0)
    f2 = calc.update(bar_ts_utc=ts2, bar_high=102.0, bar_low=100.0, close=101.0)
    assert f2["london_high"] == 102.0

    ts3 = _et_to_utc(2026, 6, 10, 9, 0)
    f3 = calc.update(bar_ts_utc=ts3, bar_high=101.5, bar_low=99.5, close=100.0)
    assert f3["london_high"] == 102.0
    assert f3["london_low"] == 99.0


def test_dist_ny_open_pct():
    """dist_ny_open_pct = (close - ny_open) / ny_open * 100."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()

    # Open a 100
    ts1 = _et_to_utc(2026, 6, 10, 9, 30)
    calc.update(bar_ts_utc=ts1, bar_high=100.5, bar_low=99.5, close=100.0)

    # Bar suivante close=101 -> dist = (101-100)/100*100 = 1.0
    ts2 = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts2, bar_high=101.5, bar_low=100.0, close=101.0)
    assert abs(f["dist_ny_open_pct"] - 1.0) < 0.01


# ────────────────────────────────────────────────────────────────────────────
# Tests cross-day reset
# ────────────────────────────────────────────────────────────────────────────

def test_cross_day_reset_a_18h_et():
    """Nouveau session_date_trading a 18:00 ET -> sessions reset."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()

    # Jour 1 RTH high = 110
    ts1 = _et_to_utc(2026, 6, 10, 10, 0)
    calc.update(bar_ts_utc=ts1, bar_high=110.0, bar_low=99.0, close=105.0)
    f1 = calc.update(bar_ts_utc=_et_to_utc(2026, 6, 10, 12, 0),
                     bar_high=108.0, bar_low=100.0, close=104.0)
    assert f1["us_high"] == 110.0

    # 18:30 ET = nouveau trading day
    ts_reset = _et_to_utc(2026, 6, 10, 18, 30)
    f_reset = calc.update(bar_ts_utc=ts_reset,
                          bar_high=103.0, bar_low=102.0, close=102.5)
    # Sessions reset, us_high revient a NaN (pas encore en RTH)
    assert math.isnan(f_reset["us_high"])
    # Mais asia_high commence a 103 (premiere bar Asia nouveau jour)
    assert f_reset["asia_high"] == 103.0


# ────────────────────────────────────────────────────────────────────────────
# Tests pct_in_range + mins_et
# ────────────────────────────────────────────────────────────────────────────

def test_pct_in_range_au_milieu():
    """close au milieu range -> pct_in_range = 0.5."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=110.0, bar_low=100.0, close=105.0)
    assert abs(f["pct_in_range"] - 0.5) < 0.01


def test_pct_in_range_au_high():
    """close = high -> pct_in_range = 1.0."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=110.0, bar_low=100.0, close=110.0)
    assert abs(f["pct_in_range"] - 1.0) < 0.01


def test_mins_et_correct():
    """mins_et = heures_et * 60 + minutes_et."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    # 14:30 ET = 14*60 + 30 = 870
    ts = _et_to_utc(2026, 6, 10, 14, 30)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["mins_et"] == 870


# ────────────────────────────────────────────────────────────────────────────
# Tests DST hell + defensive
# ────────────────────────────────────────────────────────────────────────────

def test_dst_spring_forward_2026():
    """DST spring forward 8 mars 2026 (02:00 -> 03:00 ET) ne crash pas."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    # Lundi 9 mars 2026 09:30 ET (apres DST spring forward)
    ts = _et_to_utc(2026, 3, 9, 9, 30)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_segment"] == "us_cash"
    assert f["ny_open"] == 99.5


def test_dst_fall_back_2025():
    """DST fall back 2 novembre 2025 (02:00 ET -> 01:00 ET) ne crash pas."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    # Lundi 3 novembre 2025 14:00 ET (apres DST fall back)
    ts = _et_to_utc(2025, 11, 3, 14, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_segment"] == "us_cash"


def test_naive_timestamp_raises():
    """ts naive -> ValueError FAIL LOUD."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    with pytest.raises(ValueError, match="tz-aware"):
        calc.update(bar_ts_utc=datetime(2026, 6, 10, 14, 0),
                    bar_high=100.0, bar_low=99.0, close=99.5)


def test_nan_inputs():
    """NaN inputs -> empty features."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=float("nan"),
                    bar_low=99.0, close=99.5)
    assert f["session_segment"] == "off"
    assert math.isnan(f["us_high"])


# ────────────────────────────────────────────────────────────────────────────
# Tests batch mode
# ────────────────────────────────────────────────────────────────────────────

def test_dist_us_high_pct_signed():
    """dist_us_high_pct SIGNED : negatif si close < us_high."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    # us_cash open 09:30 ET bar high=110
    ts1 = _et_to_utc(2026, 6, 10, 9, 30)
    calc.update(bar_ts_utc=ts1, bar_high=110.0, bar_low=99.0, close=105.0)

    # Bar 10:00 close=100 < us_high=110 -> dist = (100-110)/110*100 ~ -9.09 (negatif)
    ts2 = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts2, bar_high=102.0, bar_low=99.0, close=100.0)
    assert f["dist_us_high_pct"] < 0
    assert abs(f["dist_us_high_pct"] - (-9.09)) < 0.1


def test_dist_london_low_pct_positive_apres_remontee():
    """dist_london_low_pct positif si close > london_low."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    # London 05:00 ET low=95
    ts1 = _et_to_utc(2026, 6, 10, 5, 0)
    calc.update(bar_ts_utc=ts1, bar_high=98.0, bar_low=95.0, close=96.0)

    # Bar 07:00 close=100 > london_low=95 -> dist positif
    ts2 = _et_to_utc(2026, 6, 10, 7, 0)
    f = calc.update(bar_ts_utc=ts2, bar_high=101.0, bar_low=99.0, close=100.0)
    assert f["dist_london_low_pct"] > 0


def test_session_date_exposed():
    """Q2 : session_date expose en ISO YYYY-MM-DD."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    ts = _et_to_utc(2026, 6, 10, 14, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_date"] == "2026-06-10"


def test_session_date_trading_exposed():
    """Q2 : session_date_trading expose, J+1 si >= 18:00 ET."""
    from CORE.sessions_fine import SessionsFineCalculator

    calc = SessionsFineCalculator()
    # 18:30 ET = J+1 trading_date
    ts = _et_to_utc(2026, 6, 10, 18, 30)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0, close=99.5)
    assert f["session_date_trading"] == "2026-06-11"
    # Mais session_date (UTC civil) reste 10 (ou 11 selon convert UTC->ET)
    assert f["session_date"] == "2026-06-10"


def test_batch_mode_dataframe():
    """compute_sessions_fine_features batch sur DataFrame."""
    from CORE.sessions_fine import compute_sessions_fine_features

    df = pd.DataFrame({
        "ts_utc": [
            _et_to_utc(2026, 6, 10, 5, 0).isoformat(),    # London
            _et_to_utc(2026, 6, 10, 10, 0).isoformat(),   # US cash
            _et_to_utc(2026, 6, 10, 17, 0).isoformat(),   # US after
        ],
        "bar_high": [100.0, 102.0, 103.0],
        "bar_low": [99.0, 100.0, 101.0],
        "close": [99.5, 101.5, 102.5],
    })
    result = compute_sessions_fine_features(df)

    assert result["session_segment"].iloc[0] == "london"
    assert result["session_segment"].iloc[1] == "us_cash"
    assert result["session_segment"].iloc[2] == "us_after"
    assert bool(result["is_in_us_cash"].iloc[1]) is True


def test_batch_missing_column_raises():
    """Colonne manquante -> ValueError."""
    from CORE.sessions_fine import compute_sessions_fine_features

    df = pd.DataFrame({"ts_utc": ["2026-06-10T10:00:00+00:00"]})
    with pytest.raises(ValueError, match="manquantes"):
        compute_sessions_fine_features(df)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
