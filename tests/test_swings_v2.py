"""Tests Phase 3.2 swings_v2.py (Sierra Migration 10/06/2026)."""
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


# ────────────────────────────────────────────────────────────────────────────
# Tests detection new_swing + compteurs
# ────────────────────────────────────────────────────────────────────────────

def test_new_swing_high_detecte_compteur_reset():
    """dist_swing_high passe de >0 a 0 -> bars_since_high=0 puis incremente."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25)

    # Bar 1 : dist_swing_high = 5 (pas sur swing)
    f1 = calc.update(dist_swing_high=5.0, dist_swing_low=10.0,
                     bar_high=100.0, bar_low=95.0, close=98.0)
    # Cold-start : pas encore swing detecte
    assert math.isnan(f1["bars_since_last_swing_high"])

    # Bar 2 : dist_swing_high = 0 (front montant -> new swing high)
    f2 = calc.update(dist_swing_high=0.0, dist_swing_low=15.0,
                     bar_high=105.0, bar_low=100.0, close=103.0)
    assert f2["bars_since_last_swing_high"] == 0

    # Bar 3-5 : compteur incremente
    f3 = calc.update(dist_swing_high=2.0, dist_swing_low=18.0,
                     bar_high=103.0, bar_low=100.0, close=101.0)
    assert f3["bars_since_last_swing_high"] == 1

    f4 = calc.update(dist_swing_high=3.0, dist_swing_low=20.0,
                     bar_high=102.0, bar_low=99.0, close=100.0)
    assert f4["bars_since_last_swing_high"] == 2


def test_new_swing_low_detecte_compteur_reset():
    """dist_swing_low passe de >0 a 0 -> bars_since_low=0 puis incremente."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25)

    f1 = calc.update(dist_swing_high=10.0, dist_swing_low=5.0,
                     bar_high=100.0, bar_low=95.0, close=98.0)
    assert math.isnan(f1["bars_since_last_swing_low"])

    f2 = calc.update(dist_swing_high=15.0, dist_swing_low=0.0,
                     bar_high=95.0, bar_low=90.0, close=92.0)
    assert f2["bars_since_last_swing_low"] == 0

    f3 = calc.update(dist_swing_high=18.0, dist_swing_low=3.0,
                     bar_high=96.0, bar_low=92.0, close=95.0)
    assert f3["bars_since_last_swing_low"] == 1


def test_multiple_new_swings_reset_correct():
    """2 swings highs successifs : compteur reset chaque fois."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25)

    calc.update(dist_swing_high=0.0, dist_swing_low=10.0,
                bar_high=100.0, bar_low=95.0, close=98.0)
    calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                bar_high=101.0, bar_low=98.0, close=100.0)
    calc.update(dist_swing_high=4.0, dist_swing_low=14.0,
                bar_high=99.0, bar_low=96.0, close=97.0)
    # Nouveau swing high
    f4 = calc.update(dist_swing_high=0.0, dist_swing_low=16.0,
                     bar_high=105.0, bar_low=100.0, close=104.0)
    assert f4["bars_since_last_swing_high"] == 0


# ────────────────────────────────────────────────────────────────────────────
# Tests equal_highs / equal_lows
# ────────────────────────────────────────────────────────────────────────────

def test_equal_highs_detected_within_tolerance():
    """2 swings highs a 100.0 et 100.25 (1 tick) avec tolerance 4 ticks -> True."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25, equal_tolerance_ticks=4)

    # Swing high #1 a 100.0
    f1 = calc.update(dist_swing_high=0.0, dist_swing_low=10.0,
                     bar_high=100.0, bar_low=98.0, close=99.0)
    assert f1["equal_highs_detected"] is False  # 1 seul

    # Bars intermediaires
    for _ in range(3):
        calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                    bar_high=99.0, bar_low=96.0, close=98.0)

    # Swing high #2 a 100.25 (1 tick au-dessus)
    f5 = calc.update(dist_swing_high=0.0, dist_swing_low=14.0,
                     bar_high=100.25, bar_low=99.0, close=100.0)
    assert f5["equal_highs_detected"] is True


def test_equal_highs_not_detected_beyond_tolerance():
    """2 swings highs a 100.0 et 102.0 (8 ticks ecart) tolerance 4 ticks -> False."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25, equal_tolerance_ticks=4)

    calc.update(dist_swing_high=0.0, dist_swing_low=10.0,
                bar_high=100.0, bar_low=98.0, close=99.0)
    for _ in range(3):
        calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                    bar_high=99.0, bar_low=96.0, close=98.0)
    # Swing #2 a 102.0 (8 ticks > tolerance 4)
    f = calc.update(dist_swing_high=0.0, dist_swing_low=14.0,
                    bar_high=102.0, bar_low=99.0, close=101.0)
    assert f["equal_highs_detected"] is False


def test_equal_lows_detected():
    """2 swings lows quasi-egaux -> True."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25, equal_tolerance_ticks=4)

    calc.update(dist_swing_high=10.0, dist_swing_low=0.0,
                bar_high=98.0, bar_low=95.0, close=96.0)
    for _ in range(3):
        calc.update(dist_swing_high=12.0, dist_swing_low=2.0,
                    bar_high=99.0, bar_low=96.0, close=98.0)
    f = calc.update(dist_swing_high=14.0, dist_swing_low=0.0,
                    bar_high=99.0, bar_low=95.25, close=97.0)
    assert f["equal_lows_detected"] is True


# ────────────────────────────────────────────────────────────────────────────
# Tests ICT liquidity sweep
# ────────────────────────────────────────────────────────────────────────────

def test_liquidity_sweep_high_detected_in_lookback():
    """Bar a wick au-dessus swing high (101.0) puis close en-dessous (99.0) -> sweep True."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25, sweep_lookback=5)

    # Setup : swing high a 100.0
    calc.update(dist_swing_high=0.0, dist_swing_low=10.0,
                bar_high=100.0, bar_low=98.0, close=99.0)
    # Sweep bar : high=101 (wick au-dessus 100), close=99 (sous 100)
    f = calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                    bar_high=101.0, bar_low=98.0, close=99.0)
    assert f["liquidity_sweep_high_lag5"] is True


def test_liquidity_sweep_high_not_detected_si_close_au_dessus():
    """Wick au-dessus swing MAIS close au-dessus aussi -> pas un sweep (breakout)."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25, sweep_lookback=5)

    calc.update(dist_swing_high=0.0, dist_swing_low=10.0,
                bar_high=100.0, bar_low=98.0, close=99.0)
    # Breakout : high=102, close=101.5 (au-dessus swing 100)
    f = calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                    bar_high=102.0, bar_low=99.0, close=101.5)
    assert f["liquidity_sweep_high_lag5"] is False


def test_liquidity_sweep_low_detected():
    """Wick sous swing low puis close au-dessus -> sweep low True."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25, sweep_lookback=5)

    # Swing low a 95.0
    calc.update(dist_swing_high=10.0, dist_swing_low=0.0,
                bar_high=98.0, bar_low=95.0, close=96.0)
    # Sweep : low=94 (wick sous 95), close=96 (au-dessus 95)
    f = calc.update(dist_swing_high=12.0, dist_swing_low=2.0,
                    bar_high=97.0, bar_low=94.0, close=96.0)
    assert f["liquidity_sweep_low_lag5"] is True


def test_sweep_high_decay_after_lookback():
    """Sweep detecte se decay apres lookback bars."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator(tick_size=0.25, sweep_lookback=5)

    # Setup swing
    calc.update(dist_swing_high=0.0, dist_swing_low=10.0,
                bar_high=100.0, bar_low=98.0, close=99.0)
    # Sweep bar
    calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                bar_high=101.0, bar_low=98.0, close=99.0)
    # 5 bars suivantes normales -> sweep sort de la fenetre
    for _ in range(5):
        calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                    bar_high=99.5, bar_low=98.0, close=99.0)

    f = calc.update(dist_swing_high=3.0, dist_swing_low=13.0,
                    bar_high=99.5, bar_low=98.0, close=99.0)
    assert f["liquidity_sweep_high_lag5"] is False


# ────────────────────────────────────────────────────────────────────────────
# Tests defensive / cold-start / reset
# ────────────────────────────────────────────────────────────────────────────

def test_nan_input_handling():
    """NaN dans inputs -> features par defaut (anti silent fallback)."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator()
    f = calc.update(dist_swing_high=float("nan"), dist_swing_low=10.0,
                    bar_high=100.0, bar_low=95.0, close=98.0)
    assert math.isnan(f["bars_since_last_swing_high"])
    assert math.isnan(f["bars_since_last_swing_low"])
    assert f["equal_highs_detected"] is False
    assert f["liquidity_sweep_high_lag5"] is False


def test_cold_start_no_swing_yet():
    """Aucun swing rencontre encore -> bars_since NaN."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator()
    f = calc.update(dist_swing_high=5.0, dist_swing_low=10.0,
                    bar_high=100.0, bar_low=95.0, close=98.0)
    assert math.isnan(f["bars_since_last_swing_high"])
    assert math.isnan(f["bars_since_last_swing_low"])
    assert f["equal_highs_detected"] is False


def test_reset_clears_state():
    """calc.reset() vide tout l'etat."""
    from CORE.swings_v2 import SwingsV2Calculator

    calc = SwingsV2Calculator()
    calc.update(dist_swing_high=0.0, dist_swing_low=10.0,
                bar_high=100.0, bar_low=95.0, close=98.0)
    f1 = calc.update(dist_swing_high=2.0, dist_swing_low=12.0,
                     bar_high=99.0, bar_low=96.0, close=98.0)
    assert f1["bars_since_last_swing_high"] == 1

    calc.reset()
    f2 = calc.update(dist_swing_high=5.0, dist_swing_low=15.0,
                     bar_high=99.0, bar_low=96.0, close=98.0)
    assert math.isnan(f2["bars_since_last_swing_high"])


# ────────────────────────────────────────────────────────────────────────────
# Tests batch mode
# ────────────────────────────────────────────────────────────────────────────

def test_batch_mode_dataframe():
    """compute_swings_v2_features batch sur DataFrame."""
    from CORE.swings_v2 import compute_swings_v2_features

    df = pd.DataFrame({
        "dist_swing_high": [5.0, 0.0, 2.0, 3.0, 4.0],
        "dist_swing_low": [10.0, 12.0, 14.0, 16.0, 18.0],
        "bar_high": [99.0, 105.0, 103.0, 102.0, 101.0],
        "bar_low": [95.0, 100.0, 100.0, 99.0, 98.0],
        "close": [98.0, 103.0, 101.0, 100.0, 99.0],
    })

    result = compute_swings_v2_features(df, tick_size=0.25)

    assert "bars_since_last_swing_high" in result.columns
    assert "equal_highs_detected" in result.columns
    assert "liquidity_sweep_high_lag5" in result.columns
    # Row 1 : new swing high -> bars_since = 0
    assert result["bars_since_last_swing_high"].iloc[1] == 0
    # Row 4 : 3 bars apres -> bars_since = 3
    assert result["bars_since_last_swing_high"].iloc[4] == 3


def test_batch_missing_column_raises():
    """Colonne manquante -> ValueError FAIL LOUD."""
    from CORE.swings_v2 import compute_swings_v2_features

    df = pd.DataFrame({"dist_swing_high": [1.0]})
    with pytest.raises(ValueError, match="colonnes manquantes"):
        compute_swings_v2_features(df)


def test_batch_tick_size_mgc():
    """tick_size 0.10 MGC : tolerance equal = 4 * 0.10 = 0.4 points."""
    from CORE.swings_v2 import compute_swings_v2_features

    # 2 swings highs a 2000.0 et 2000.3 (3 ticks MGC = 0.3 < tolerance 0.4)
    df = pd.DataFrame({
        "dist_swing_high": [0.0, 1.0, 2.0, 0.0, 1.0],
        "dist_swing_low": [10.0, 12.0, 14.0, 16.0, 18.0],
        "bar_high": [2000.0, 1999.0, 1998.5, 2000.3, 1999.5],
        "bar_low": [1998.0, 1997.0, 1996.5, 1998.5, 1997.5],
        "close": [1999.0, 1998.0, 1997.5, 1999.5, 1998.5],
    })
    result = compute_swings_v2_features(df, tick_size=0.10, equal_tolerance_ticks=4)
    # Row 4 : 2eme swing high a 2000.3, equal avec 2000.0 (diff 0.3 < 0.4)
    # Cast bool explicit (pandas retourne np.bool_) - lecon review code-reviewer
    assert bool(result["equal_highs_detected"].iloc[3]) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
