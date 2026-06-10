"""Tests Phase 3.3 prev_levels.py (Sierra Migration 10/06/2026)."""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))

ET = ZoneInfo("America/New_York")


def _et_to_utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Helper : creer datetime UTC depuis heure ET (gere DST)."""
    return datetime(year, month, day, hour, minute, tzinfo=ET).astimezone(timezone.utc)


# ────────────────────────────────────────────────────────────────────────────
# Tests cold-start + PDH/PDL transition
# ────────────────────────────────────────────────────────────────────────────

def test_cold_start_pdh_pdl_nan():
    """Premier jour : pdh/pdl NaN (pas de jour precedent)."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    # Cash session premiere bar 10:00 ET
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=98.0,
                    close=99.0, atr=2.0)
    assert math.isnan(f["pdh"])
    assert math.isnan(f["pdl"])
    assert math.isnan(f["dist_pdh_atr"])


def test_pdh_pdl_snapshot_apres_18h_et():
    """Apres 18:00 ET, nouveau session_date_trading -> pdh/pdl snapshote."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # Jour 1 : bars 10:00, 14:00, 17:00 ET avec high=110, low=95
    ts1 = _et_to_utc(2026, 6, 10, 10, 0)
    calc.update(bar_ts_utc=ts1, bar_high=110.0, bar_low=95.0, close=100.0, atr=2.0)
    ts2 = _et_to_utc(2026, 6, 10, 14, 0)
    calc.update(bar_ts_utc=ts2, bar_high=108.0, bar_low=98.0, close=105.0, atr=2.0)
    ts3 = _et_to_utc(2026, 6, 10, 17, 0)
    calc.update(bar_ts_utc=ts3, bar_high=107.0, bar_low=99.0, close=103.0, atr=2.0)

    # Bar 18:30 ET = nouveau session_date_trading = 11/06
    ts4 = _et_to_utc(2026, 6, 10, 18, 30)
    f = calc.update(bar_ts_utc=ts4, bar_high=104.0, bar_low=102.0,
                    close=103.0, atr=2.0)

    # pdh = 110 (max jour 1), pdl = 95 (min jour 1)
    assert f["pdh"] == 110.0
    assert f["pdl"] == 95.0
    # dist_pdh_atr = (103 - 110) / 2.0 = -3.5 (signed negative)
    assert abs(f["dist_pdh_atr"] - (-3.5)) < 0.01
    assert abs(f["dist_pdl_atr"] - 4.0) < 0.01


# ────────────────────────────────────────────────────────────────────────────
# Tests cash session RTH (09:30-16:00 ET)
# ────────────────────────────────────────────────────────────────────────────

def test_open_cash_snapshot_a_930_et():
    """Premiere bar 09:30 ET -> open_cash snapshot."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # Bar pre-cash 09:00 ET
    ts_pre = _et_to_utc(2026, 6, 10, 9, 0)
    f_pre = calc.update(bar_ts_utc=ts_pre, bar_high=99.0, bar_low=97.0,
                        close=98.0, atr=2.0)
    assert math.isnan(f_pre["open_cash"])

    # Bar 09:30 ET = open RTH
    ts_open = _et_to_utc(2026, 6, 10, 9, 30)
    f_open = calc.update(bar_ts_utc=ts_open, bar_high=100.0, bar_low=99.0,
                         close=99.5, atr=2.0)
    assert f_open["open_cash"] == 99.5  # snapshot close
    assert f_open["cash_high"] == 100.0
    assert f_open["cash_low"] == 99.0


def test_open_830_et_snapshot_economic_releases():
    """Snapshot price a 08:30 ET (CPI/NFP/PCE releases)."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # Bar 08:00 ET (avant 08:30)
    ts_pre = _et_to_utc(2026, 6, 10, 8, 0)
    f_pre = calc.update(bar_ts_utc=ts_pre, bar_high=100.0, bar_low=99.0,
                        close=99.5, atr=2.0)
    assert math.isnan(f_pre["open_830_et"])

    # Bar 08:30 ET = release window
    ts_830 = _et_to_utc(2026, 6, 10, 8, 30)
    f_830 = calc.update(bar_ts_utc=ts_830, bar_high=100.5, bar_low=99.5,
                        close=100.0, atr=2.0)
    assert f_830["open_830_et"] == 100.0


def test_above_open_830_bool():
    """above_open_830 True si close > open_830_et."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    ts_830 = _et_to_utc(2026, 6, 10, 8, 30)
    calc.update(bar_ts_utc=ts_830, bar_high=100.5, bar_low=99.5,
                close=100.0, atr=2.0)

    # Bar 09:00 close=102 > open_830=100 -> True
    ts2 = _et_to_utc(2026, 6, 10, 9, 0)
    f = calc.update(bar_ts_utc=ts2, bar_high=102.5, bar_low=100.0,
                    close=102.0, atr=2.0)
    assert f["above_open_830"] is True


def test_above_open_cash():
    """close > open_cash -> above_open_cash True."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    ts_open = _et_to_utc(2026, 6, 10, 9, 30)
    calc.update(bar_ts_utc=ts_open, bar_high=100.0, bar_low=99.0,
                close=99.5, atr=2.0)

    # Bar 10:00 ET avec close=101 > open_cash 99.5
    ts2 = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts2, bar_high=101.5, bar_low=99.0,
                    close=101.0, atr=2.0)
    assert f["above_open_cash"] is True


def test_cash_high_low_running_max_min():
    """cash_high / cash_low s'updatent comme running max/min."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    ts_open = _et_to_utc(2026, 6, 10, 9, 30)
    calc.update(bar_ts_utc=ts_open, bar_high=100.0, bar_low=99.0,
                close=99.5, atr=2.0)

    # Bar 10:00 : high=105 nouveau cash_high
    ts2 = _et_to_utc(2026, 6, 10, 10, 0)
    f2 = calc.update(bar_ts_utc=ts2, bar_high=105.0, bar_low=100.0,
                     close=104.0, atr=2.0)
    assert f2["cash_high"] == 105.0
    assert f2["is_new_cash_high"] is True

    # Bar 11:00 : high=103 < 105 -> cash_high reste 105
    ts3 = _et_to_utc(2026, 6, 10, 11, 0)
    f3 = calc.update(bar_ts_utc=ts3, bar_high=103.0, bar_low=101.0,
                     close=102.0, atr=2.0)
    assert f3["cash_high"] == 105.0
    assert f3["is_new_cash_high"] is False


def test_is_new_cash_low():
    """is_new_cash_low True quand bar_low <= cash_low."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    ts_open = _et_to_utc(2026, 6, 10, 9, 30)
    calc.update(bar_ts_utc=ts_open, bar_high=100.0, bar_low=99.0,
                close=99.5, atr=2.0)

    ts2 = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts2, bar_high=99.5, bar_low=95.0,
                    close=96.0, atr=2.0)
    assert f["cash_low"] == 95.0
    assert f["is_new_cash_low"] is True


# ────────────────────────────────────────────────────────────────────────────
# Tests overnight session
# ────────────────────────────────────────────────────────────────────────────

def test_overnight_high_low_tracking():
    """Bars overnight (avant 09:30 OU apres 18:00 ET) trackees dans ovn_high/low."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # Bar 19:00 ET (overnight) = nouveau session_date_trading
    ts1 = _et_to_utc(2026, 6, 9, 19, 0)
    f1 = calc.update(bar_ts_utc=ts1, bar_high=105.0, bar_low=100.0,
                     close=102.0, atr=2.0)
    assert f1["ovn_high"] == 105.0
    assert f1["ovn_low"] == 100.0

    # Bar 23:00 ET : nouveau high overnight
    ts2 = _et_to_utc(2026, 6, 9, 23, 0)
    f2 = calc.update(bar_ts_utc=ts2, bar_high=108.0, bar_low=104.0,
                     close=106.0, atr=2.0)
    assert f2["ovn_high"] == 108.0

    # Bar 03:00 ET : low descend
    ts3 = _et_to_utc(2026, 6, 10, 3, 0)
    f3 = calc.update(bar_ts_utc=ts3, bar_high=107.0, bar_low=98.0,
                     close=99.0, atr=2.0)
    assert f3["ovn_low"] == 98.0


def test_ovn_broken_up_after_cash_open():
    """Apres cash open, close > ovn_high -> ovn_broken_up True."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # Overnight setup : ovn_high = 105
    ts1 = _et_to_utc(2026, 6, 9, 19, 0)
    calc.update(bar_ts_utc=ts1, bar_high=105.0, bar_low=100.0,
                close=102.0, atr=2.0)
    ts2 = _et_to_utc(2026, 6, 10, 3, 0)
    calc.update(bar_ts_utc=ts2, bar_high=104.0, bar_low=99.0,
                close=101.0, atr=2.0)

    # RTH open 09:30 : close < ovn_high -> pas cassure
    ts3 = _et_to_utc(2026, 6, 10, 9, 30)
    f3 = calc.update(bar_ts_utc=ts3, bar_high=103.0, bar_low=100.0,
                     close=102.0, atr=2.0)
    assert f3["ovn_broken_up"] is False

    # RTH 11:00 : close = 108 > ovn_high 105 -> cassure
    ts4 = _et_to_utc(2026, 6, 10, 11, 0)
    f4 = calc.update(bar_ts_utc=ts4, bar_high=109.0, bar_low=106.0,
                     close=108.0, atr=2.0)
    assert f4["ovn_broken_up"] is True


def test_ovn_broken_dn_persistent():
    """ovn_broken_dn reste True jusqu'au reset cross-day."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # Overnight : ovn_low = 100
    ts1 = _et_to_utc(2026, 6, 9, 19, 0)
    calc.update(bar_ts_utc=ts1, bar_high=105.0, bar_low=100.0,
                close=102.0, atr=2.0)

    # RTH cassure baissiere
    ts2 = _et_to_utc(2026, 6, 10, 10, 0)
    f2 = calc.update(bar_ts_utc=ts2, bar_high=101.0, bar_low=97.0,
                     close=98.0, atr=2.0)
    assert f2["ovn_broken_dn"] is True

    # Bar suivante : close remonte au-dessus, broken_dn doit rester True
    ts3 = _et_to_utc(2026, 6, 10, 11, 0)
    f3 = calc.update(bar_ts_utc=ts3, bar_high=103.0, bar_low=101.0,
                     close=102.5, atr=2.0)
    assert f3["ovn_broken_dn"] is True


# ────────────────────────────────────────────────────────────────────────────
# Tests defensive / FAIL LOUD
# ────────────────────────────────────────────────────────────────────────────

def test_naive_timestamp_raises():
    """ts naive (sans tz) -> ValueError FAIL LOUD anti DST hell."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    with pytest.raises(ValueError, match="tz-aware"):
        calc.update(bar_ts_utc=datetime(2026, 6, 10, 14, 0),
                    bar_high=100.0, bar_low=99.0, close=99.5, atr=2.0)


def test_nan_inputs_empty_features():
    """NaN dans inputs -> empty features (False/NaN)."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=float("nan"),
                    bar_low=99.0, close=99.5, atr=2.0)
    assert math.isnan(f["pdh"])
    assert f["is_new_cash_high"] is False


def test_atr_zero_empty_features():
    """ATR = 0 -> empty features (anti division zero)."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0,
                    bar_low=99.0, close=99.5, atr=0.0)
    assert math.isnan(f["dist_pdh_atr"])


def test_atr_zero_does_not_block_cross_day_reset():
    """Fix A4 review batch : ATR=0 ne doit PAS court-circuiter reset cross-day.

    Scenario : 1ere bar 18:30 ET nouveau jour arrive avec ATR=0 (cold-start ATR
    apres gap data). Le reset PDH/PDL doit s'effectuer malgre tout.
    """
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # Jour 1 : bars valides
    ts1 = _et_to_utc(2026, 6, 10, 10, 0)
    calc.update(bar_ts_utc=ts1, bar_high=110.0, bar_low=95.0, close=105.0, atr=2.0)
    ts2 = _et_to_utc(2026, 6, 10, 14, 0)
    calc.update(bar_ts_utc=ts2, bar_high=108.0, bar_low=98.0, close=105.0, atr=2.0)

    # Bar 18:30 ET avec ATR=0 (cold-start ATR) -> empty features MAIS reset OK
    ts_reset = _et_to_utc(2026, 6, 10, 18, 30)
    f_reset = calc.update(bar_ts_utc=ts_reset, bar_high=104.0,
                          bar_low=102.0, close=103.0, atr=0.0)
    # empty features sur cette bar
    assert math.isnan(f_reset["pdh"])

    # Bar suivante 19:00 ET avec ATR valide -> doit voir PDH/PDL jour 1
    ts3 = _et_to_utc(2026, 6, 10, 19, 0)
    f3 = calc.update(bar_ts_utc=ts3, bar_high=104.0, bar_low=102.0,
                     close=103.0, atr=2.0)
    # PDH=110 (jour 1 high), PDL=95 (jour 1 low) - reset s'est effectue malgre ATR=0
    assert f3["pdh"] == 110.0, (
        f"Reset cross-day a echoue suite ATR=0, attendu pdh=110, "
        f"obtenu {f3['pdh']} (regression bug A4)"
    )
    assert f3["pdl"] == 95.0


# ────────────────────────────────────────────────────────────────────────────
# Tests batch mode
# ────────────────────────────────────────────────────────────────────────────

def test_batch_mode_dataframe():
    """compute_prev_levels_features batch sur DataFrame."""
    from CORE.prev_levels import compute_prev_levels_features

    df = pd.DataFrame({
        "ts_utc": [
            _et_to_utc(2026, 6, 10, 10, 0).isoformat(),
            _et_to_utc(2026, 6, 10, 14, 0).isoformat(),
            _et_to_utc(2026, 6, 10, 18, 30).isoformat(),  # new trading day
            _et_to_utc(2026, 6, 10, 19, 0).isoformat(),
        ],
        "bar_high": [110.0, 108.0, 104.0, 105.0],
        "bar_low": [95.0, 98.0, 102.0, 103.0],
        "close": [100.0, 105.0, 103.0, 104.0],
        "atr": [2.0, 2.0, 2.0, 2.0],
    })

    result = compute_prev_levels_features(df)

    # Row 2 (18:30 ET) = new trading day -> pdh/pdl snapshote
    assert result["pdh"].iloc[2] == 110.0  # max high jour 1 (rows 0,1)
    assert result["pdl"].iloc[2] == 95.0


def test_batch_missing_column_raises():
    """Colonne manquante -> ValueError FAIL LOUD."""
    from CORE.prev_levels import compute_prev_levels_features

    df = pd.DataFrame({"ts_utc": ["2026-06-10T10:00:00+00:00"]})
    with pytest.raises(ValueError, match="colonnes manquantes"):
        compute_prev_levels_features(df)


def test_dst_transition_no_crash():
    """Transition DST (mars/novembre) ne crash pas zoneinfo handling."""
    from CORE.prev_levels import PrevLevelsCalculator

    calc = PrevLevelsCalculator()

    # DST spring forward 2026 : dimanche 8 mars 02:00 ET -> 03:00 ET
    # Bar a 09:30 ET le lendemain (lundi 9 mars 2026)
    ts = _et_to_utc(2026, 3, 9, 9, 30)
    f = calc.update(bar_ts_utc=ts, bar_high=100.0, bar_low=99.0,
                    close=99.5, atr=2.0)
    assert f["open_cash"] == 99.5  # OK pas crash


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
