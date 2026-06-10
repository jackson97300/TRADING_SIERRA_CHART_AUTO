"""Tests Phase 3.5 ctx_rolling.py (Sierra Migration 10/06/2026).

TESTS STRUCTURELS UNIQUEMENT.
Validation EDGE (DSR Lopez >= 0.5) reportee Phase 4 dual-run sur data reelle.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def _push_bars(calc, n: int, base_close: float = 100.0, base_vol: float = 1000.0,
               delta_bar: float = 0.0, atr: float = 2.0):
    """Helper : push N bars uniformes."""
    f = None
    for i in range(n):
        f = calc.update(
            close=base_close + i * 0.1,
            bar_high=base_close + 0.5 + i * 0.1,
            bar_low=base_close - 0.5 + i * 0.1,
            delta_bar=delta_bar,
            total_vol=base_vol,
            atr=atr,
        )
    return f


# ────────────────────────────────────────────────────────────────────────────
# Tests cold-start + outputs structure
# ────────────────────────────────────────────────────────────────────────────

def test_cold_start_under_window_short_empty_features():
    """Buffer < 5 bars -> empty features (NaN propre)."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)
    assert math.isnan(f["ctx_vol_z_20"])
    assert f["ctx_climax_signal"] is False


def test_output_structure_25_features():
    """Verifier que update() retourne exactement 25 keys."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    f = _push_bars(calc, 5)

    expected_keys = {
        "ctx_climax_signal", "ctx_failed_auction",
        "ctx_absorption_score_5", "ctx_absorption_streak_5",
        "ctx_instant_absorption",
        "ctx_delta_exhaustion", "ctx_momentum_exhaustion",
        "ctx_poor_high", "ctx_poor_low",
        "ctx_excess_high_bars", "ctx_excess_low_bars",
        "ctx_double_top_trap",
        "ctx_vol_sell_buy_ratio_5", "ctx_vol_slope_5", "ctx_vol_z_20",
        "ctx_finish_strength_mean_5", "ctx_dist_vwap_velocity",
        "ctx_vwap_slope_accel", "ctx_va_position_velocity",
        "ctx_side_flip_count_10", "ctx_range_vs_atr_10",
        "ctx_price_slope_5", "ctx_delta_sum_3",
        "ctx_delta_slope_5", "ctx_rvol_session",
    }
    assert set(f.keys()) == expected_keys
    assert len(expected_keys) == 25


# ────────────────────────────────────────────────────────────────────────────
# Tests features individuelles (semantique math)
# ────────────────────────────────────────────────────────────────────────────

def test_climax_signal_vol_spike_extreme_range_pos():
    """Volume spike (z>2) + range_pos extreme -> climax True."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # 5 bars volume normal 1000
    for i in range(5):
        calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0,
                    range_pos=0.5)

    # Bar 6 : volume spike 5000 (z >> 2) + range_pos = 0.95 (extreme high)
    f = calc.update(close=101.0, bar_high=101.5, bar_low=99.0,
                    delta_bar=0.0, total_vol=5000.0, atr=2.0,
                    range_pos=0.95)
    assert f["ctx_climax_signal"] is True


def test_climax_no_extreme_range_pos():
    """Volume spike SANS range_pos extreme -> climax False."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    for i in range(5):
        calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0,
                    range_pos=0.5)

    f = calc.update(close=101.0, bar_high=101.5, bar_low=99.0,
                    delta_bar=0.0, total_vol=5000.0, atr=2.0,
                    range_pos=0.5)  # middle range
    assert f["ctx_climax_signal"] is False


def test_failed_auction_new_high_small_body_middle():
    """New high + body middle (small) -> failed_auction True."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # 5 bars normales
    for i in range(5):
        calc.update(close=100.0, bar_high=100.5, bar_low=99.5,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)

    # Bar 6 : new high 105 mais close 100 (middle = milieu range 99-105)
    # body = 100 - (105+99)/2 = 100 - 102 = -2
    # bar_range = 6
    # abs(body)/range = 2/6 = 0.33 > 0.3 -> body_in_middle = False
    # Donc failed_auction = False. Ajustons.
    # Bar avec body plus petit : close = 102, bar_high=105, bar_low=99
    # body = 102 - 102 = 0, abs(body)/range = 0 < 0.3 -> middle OK
    f = calc.update(close=102.0, bar_high=105.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)
    assert f["ctx_failed_auction"] is True


def test_absorption_score_streak():
    """Absorption sur plusieurs bars -> streak incremente."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # 5 bars warmup
    _push_bars(calc, 5)

    # 3 bars avec absorption
    for i in range(3):
        f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                        delta_bar=0.0, total_vol=1000.0, atr=2.0,
                        bn_absorb_ask=0.8)
    assert f["ctx_instant_absorption"] is True
    assert f["ctx_absorption_streak_5"] == 3

    # 1 bar sans absorption -> streak reset
    f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0,
                    bn_absorb_ask=0.0)
    assert f["ctx_instant_absorption"] is False
    assert f["ctx_absorption_streak_5"] == 0


def test_poor_high_new_high_with_rejet():
    """New high MAIS close pres du bar_low -> poor_high True (rejet)."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    _push_bars(calc, 5)

    # New high 105, close 99 (pres bar_low)
    # body_bullish = close > bar_low + range*0.6 ? 99 > 99 + 6*0.6 = 102.6 ? False
    # poor_high = new_high AND NOT body_bullish = True
    f = calc.update(close=99.0, bar_high=105.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)
    assert f["ctx_poor_high"] is True


def test_poor_low_new_low_with_rejet():
    """New low MAIS close pres bar_high -> poor_low True."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    _push_bars(calc, 5)

    # New low 90, close 99 (pres bar_high 99)
    f = calc.update(close=99.0, bar_high=99.0, bar_low=90.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)
    assert f["ctx_poor_low"] is True


def test_excess_high_bars_count():
    """Count bars > EMA20 sur buffer."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # 10 bars croissantes (donc derniere bars > EMA20 lagged)
    for i in range(10):
        f = calc.update(close=100.0 + i * 2,
                        bar_high=101.0 + i * 2,
                        bar_low=99.0 + i * 2,
                        delta_bar=0.0, total_vol=1000.0, atr=2.0)

    # Quelques bars au-dessus EMA20 (qui lag)
    assert f["ctx_excess_high_bars"] >= 1


def test_vol_slope_positive_increasing_volume():
    """Volume croissant sur 5 bars -> vol_slope > 0."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    for i in range(5):
        f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                        delta_bar=0.0, total_vol=1000.0 + i * 200,
                        atr=2.0)
    assert f["ctx_vol_slope_5"] > 0


def test_vol_z_20_signed():
    """Volume > rolling mean -> vol_z positif (SIGNED feature)."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # 5 bars vol normal 1000
    for i in range(5):
        calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)

    # Bar 6 : vol 3000 (spike)
    f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=3000.0, atr=2.0)
    assert f["ctx_vol_z_20"] > 0


def test_price_slope_5_negative_decreasing():
    """Price decroit -> slope < 0 (SIGNED)."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    for i in range(5):
        f = calc.update(close=100.0 - i,
                        bar_high=100.5 - i,
                        bar_low=99.5 - i,
                        delta_bar=0.0, total_vol=1000.0, atr=2.0)
    assert f["ctx_price_slope_5"] < 0


def test_dist_vwap_velocity_signed_positive():
    """dist_vwap_velocity positif si dist_vwap croit (close monte vs vwap).

    Fix review B5 : test signed manquant.
    """
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # 5 bars : dist_vwap = 0, 1, 2, 3, 4 (close monte vs vwap fixe)
    for i in range(5):
        f = calc.update(close=100.0 + i, bar_high=100.5 + i, bar_low=99.5 + i,
                        delta_bar=0.0, total_vol=1000.0, atr=2.0,
                        vwap_d=100.0)
    # dist_vwap_velocity = dist[-1] - dist[-3] = 4 - 2 = 2 (positif)
    assert f["ctx_dist_vwap_velocity"] > 0


def test_va_position_velocity_signed_negative():
    """va_position_velocity negatif si va_position descend (close dans VA inferieure)."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # va_position descend de 0.8 a 0.2
    for i, va in enumerate([0.8, 0.7, 0.5, 0.3, 0.2]):
        f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                        delta_bar=0.0, total_vol=1000.0, atr=2.0,
                        va_position_pct=va)
    # vel = va[-1] - va[-3] = 0.2 - 0.5 = -0.3 (negatif)
    assert f["ctx_va_position_velocity"] < 0


def test_delta_slope_5_signed_positive():
    """delta_slope_5 positif si delta_bar croit sur 5 bars."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # delta croit 100 -> 500
    for d in [100.0, 200.0, 300.0, 400.0, 500.0]:
        f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                        delta_bar=d, total_vol=1000.0, atr=2.0)
    # slope > 0
    assert f["ctx_delta_slope_5"] > 0


def test_vwap_slope_accel_signed_positive():
    """vwap_slope_accel positif si VWAP accelere a la hausse."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # VWAP : 100, 100.1, 100.3, 100.6, 101.0, 101.5, 102.1 (accelere)
    vwaps = [100.0, 100.1, 100.3, 100.6, 101.0, 101.5, 102.1]
    f = None
    for v in vwaps:
        f = calc.update(close=v, bar_high=v + 0.5, bar_low=v - 0.5,
                        delta_bar=0.0, total_vol=1000.0, atr=2.0,
                        vwap_d=v)
    # slope_recent (3 dernieres) > slope_prev (3 avant-dernieres)
    # vwap accelere a la hausse -> slope_accel > 0
    assert f["ctx_vwap_slope_accel"] > 0


def test_delta_sum_3():
    """delta_sum_3 = sum 3 dernieres bars delta_bar."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # 5 bars setup
    _push_bars(calc, 5)

    # 3 bars deltas 100, 200, 300
    for d in [100.0, 200.0, 300.0]:
        f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                        delta_bar=d, total_vol=1000.0, atr=2.0)

    assert f["ctx_delta_sum_3"] == 600.0


def test_side_flip_count_10():
    """Alternances bull/bear bars sur 10 -> count flips."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()

    # 10 bars alternantes (close above mid, then below, ...)
    for i in range(10):
        if i % 2 == 0:
            # Bull bar : close pres bar_high
            f = calc.update(close=100.8, bar_high=101.0, bar_low=99.0,
                            delta_bar=0.0, total_vol=1000.0, atr=2.0)
        else:
            # Bear bar : close pres bar_low
            f = calc.update(close=99.2, bar_high=101.0, bar_low=99.0,
                            delta_bar=0.0, total_vol=1000.0, atr=2.0)

    # 10 alternances -> ~9 flips
    assert f["ctx_side_flip_count_10"] >= 5


def test_rvol_session_first_bar_is_1():
    """1ere bar session : total_vol / mean session = 1.0 (lui-meme)."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    # Apres warmup, mean_session_vol stabilise
    _push_bars(calc, 5)
    # rvol_session = total_vol / mean(self._session_vol_sum / count)
    # Si toutes les bars ont vol=1000, rvol = 1.0
    f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)
    assert abs(f["ctx_rvol_session"] - 1.0) < 0.01


# ────────────────────────────────────────────────────────────────────────────
# Tests defensive
# ────────────────────────────────────────────────────────────────────────────

def test_nan_close_empty_features():
    """close NaN -> empty features."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    f = calc.update(close=float("nan"), bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)
    assert f["ctx_climax_signal"] is False
    assert math.isnan(f["ctx_vol_z_20"])


def test_atr_zero_empty_features():
    """ATR=0 -> empty features (anti div zero)."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=0.0)
    assert math.isnan(f["ctx_vol_z_20"])


def test_reset_clears_state():
    """calc.reset() vide tout."""
    from CORE.ctx_rolling import CtxRollingCalculator

    calc = CtxRollingCalculator()
    _push_bars(calc, 10)
    calc.reset()
    f = calc.update(close=100.0, bar_high=101.0, bar_low=99.0,
                    delta_bar=0.0, total_vol=1000.0, atr=2.0)
    # Apres reset, cold-start
    assert math.isnan(f["ctx_vol_z_20"])


# ────────────────────────────────────────────────────────────────────────────
# Tests batch mode
# ────────────────────────────────────────────────────────────────────────────

def test_batch_mode_dataframe():
    """compute_ctx_rolling_features batch."""
    from CORE.ctx_rolling import compute_ctx_rolling_features

    df = pd.DataFrame({
        "close": [100.0 + i for i in range(10)],
        "bar_high": [101.0 + i for i in range(10)],
        "bar_low": [99.0 + i for i in range(10)],
        "delta_bar": [100.0] * 10,
        "total_vol": [1000.0] * 10,
        "atr": [2.0] * 10,
    })
    result = compute_ctx_rolling_features(df)

    # 25 colonnes ajoutees
    ctx_cols = [c for c in result.columns if c.startswith("ctx_")]
    assert len(ctx_cols) == 25


def test_batch_missing_required_column_raises():
    """Colonne requise manquante -> ValueError."""
    from CORE.ctx_rolling import compute_ctx_rolling_features

    df = pd.DataFrame({"close": [100.0]})
    with pytest.raises(ValueError, match="requises manquantes"):
        compute_ctx_rolling_features(df)


def test_batch_optional_columns_default():
    """Colonnes optionnelles absentes -> NaN propre, pas crash."""
    from CORE.ctx_rolling import compute_ctx_rolling_features

    # df sans buy_vol/sell_vol/vwap_d/finish_strength/...
    df = pd.DataFrame({
        "close": [100.0 + i for i in range(10)],
        "bar_high": [101.0 + i for i in range(10)],
        "bar_low": [99.0 + i for i in range(10)],
        "delta_bar": [100.0] * 10,
        "total_vol": [1000.0] * 10,
        "atr": [2.0] * 10,
    })
    result = compute_ctx_rolling_features(df)

    # ctx_vol_sell_buy_ratio_5 doit etre NaN (pas de buy_vol/sell_vol)
    # mais pas crash
    assert "ctx_vol_sell_buy_ratio_5" in result.columns
    last = result.iloc[-1]
    assert pd.isna(last["ctx_vol_sell_buy_ratio_5"])


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
