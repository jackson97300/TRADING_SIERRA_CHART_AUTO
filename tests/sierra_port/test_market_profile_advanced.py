"""Tests Phase A.3 MEDIUM features - market_profile_advanced.py.

Couvre Single Prints + Composite POC 5d/20d + Liquidity Sweep + Judas Swing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# 1. SINGLE PRINTS (Sierra DMP natif exploit)
# ════════════════════════════════════════════════════════════════════════════

def test_single_prints_present_above_close():
    from CORE.market_profile_advanced import detect_single_prints
    payload = {
        "single_print_count": 3,
        "single_print_mid": 110.0,
        "close": 100.0,
        "atr": 5.0,
        "range_size_ticks": 60.0,
    }
    out = detect_single_prints(payload)
    assert out["has_single_prints"] is True
    assert out["single_print_above"] is True
    assert out["single_print_below"] is False
    assert out["dist_single_print_atr"] == 2.0  # (110-100)/5
    assert out["single_print_density"] == 0.05  # 3/60


def test_single_prints_below_close():
    from CORE.market_profile_advanced import detect_single_prints
    payload = {"single_print_count": 2, "single_print_mid": 90.0, "close": 100.0, "atr": 5.0}
    out = detect_single_prints(payload)
    assert out["single_print_below"] is True
    assert out["dist_single_print_atr"] == -2.0


def test_single_prints_count_zero():
    from CORE.market_profile_advanced import detect_single_prints
    payload = {"single_print_count": 0, "single_print_mid": 110.0, "close": 100.0}
    out = detect_single_prints(payload)
    assert out["has_single_prints"] is False
    assert out["dist_single_print_atr"] is None


# ════════════════════════════════════════════════════════════════════════════
# 2. COMPOSITE POC 5d / 20d
# ════════════════════════════════════════════════════════════════════════════

def test_composite_poc_accumulates_daily():
    """Composite 5d = median des daily VPOCs finaux."""
    from CORE.market_profile_advanced import compute_composite_poc, CompositePOCState
    state = CompositePOCState()
    # Simule 3 jours consecutifs
    days = [
        (1781000000000, 100.0),  # day 1
        (1781086400000, 110.0),  # day 2 (+1 day)
        (1781172800000, 105.0),  # day 3 (+2 days)
    ]
    out = None
    for ts, vpoc in days:
        out = compute_composite_poc(
            {"ts": ts, "cur_vpoc": vpoc, "close": vpoc, "atr": 5.0},
            state,
        )
    # Apres 3 jours : 2 daily VPOCs figes (day 1 et 2) car day 3 en cours
    # Median(100, 110) = 105
    assert out["composite_poc_5d"] == 105.0


def test_composite_poc_preserves_history_when_substates_reset():
    """Fix INCIDENT #58 (15/06/2026) — pattern reset selectif cross-day.

    AVANT fix : `sierra_pipeline._maybe_cross_day_reset` reinstanciait
    `MarketProfileAdvancedState()` complet -> daily_vpocs_5d/20d effacees.
    APRES fix : reset selectif sweep + judas, composite_poc preserve.

    Ce test simule le pattern de reset selectif et verifie que :
      - daily_vpocs_5d/20d gardent leur historique
      - sweep et judas sont bien reinitialises
    """
    from CORE.market_profile_advanced import (
        MarketProfileAdvancedState, LiquiditySweepState, JudasSwingState,
        compute_composite_poc,
    )

    state = MarketProfileAdvancedState()
    # Simule 3 jours consecutifs : VPOC J1=100, J2=110, J3=105 (en cours)
    days = [
        (1781000000000, 100.0),
        (1781086400000, 110.0),
        (1781172800000, 105.0),
    ]
    for ts, vpoc in days:
        compute_composite_poc(
            {"ts": ts, "cur_vpoc": vpoc, "close": vpoc, "atr": 5.0},
            state.composite_poc,
        )

    # State avant reset : 2 daily VPOCs figes
    assert len(state.composite_poc.daily_vpocs_5d) == 2
    assert state.composite_poc.last_vpoc_today == 105.0

    # Simule le pattern reset selectif (= ce que fait sierra_pipeline.py:1310 apres fix)
    state.sweep = LiquiditySweepState(sweep_window_bars=5)
    state.judas = JudasSwingState()
    # composite_poc PRESERVE (pas reinstancie)

    # APRES reset selectif : composite_poc PRESERVES, sweep + judas reset
    assert len(state.composite_poc.daily_vpocs_5d) == 2, \
        "composite_poc.daily_vpocs_5d DOIT survivre au reset selectif"
    assert state.composite_poc.last_vpoc_today == 105.0
    assert len(state.sweep.active_sweeps_high) == 0  # sweep reset
    assert state.judas.in_london is False  # judas reset


def test_composite_poc_destructive_reset_loses_history():
    """Reproduit le bug AVANT fix : reinstancier MarketProfileAdvancedState() complet.

    Ce test DOCUMENTE l'anti-pattern. Si quelqu'un reintroduit le reset
    destructeur, ce test passe mais flag le risque dans docstring.
    """
    from CORE.market_profile_advanced import (
        MarketProfileAdvancedState, compute_composite_poc,
    )

    state = MarketProfileAdvancedState()
    days = [
        (1781000000000, 100.0),
        (1781086400000, 110.0),
    ]
    for ts, vpoc in days:
        compute_composite_poc(
            {"ts": ts, "cur_vpoc": vpoc, "close": vpoc, "atr": 5.0},
            state.composite_poc,
        )

    assert len(state.composite_poc.daily_vpocs_5d) == 1  # day 1 archive
    saved_vpocs = list(state.composite_poc.daily_vpocs_5d)

    # ANTI-PATTERN : reinstancie complet (= ce qui causait INCIDENT #58)
    state = MarketProfileAdvancedState()

    # Apres reset destructeur : historique perdu
    assert len(state.composite_poc.daily_vpocs_5d) == 0, \
        "daily_vpocs_5d devrait etre vide apres reset destructeur (bug AVANT fix)"
    assert state.composite_poc.last_vpoc_today is None
    # Documentation : saved_vpocs n'existent plus dans le state
    assert saved_vpocs == [100.0]  # On les avait, on les a perdus


def test_composite_poc_distance_in_atr():
    from CORE.market_profile_advanced import compute_composite_poc, CompositePOCState
    state = CompositePOCState()
    # Insere 5 daily VPOCs via transitions
    days = [(1781000000000 + i * 86400000, 100.0 + i) for i in range(5)]
    for ts, vpoc in days:
        compute_composite_poc({"ts": ts, "cur_vpoc": vpoc, "close": 110.0, "atr": 5.0}, state)
    # Bar de transition vers 6e jour
    out = compute_composite_poc(
        {"ts": 1781000000000 + 5 * 86400000, "cur_vpoc": 120.0, "close": 110.0, "atr": 5.0},
        state,
    )
    # 5 VPOCs accumules : 100, 101, 102, 103, 104 -> median = 102
    assert out["composite_poc_5d"] == 102.0
    # Distance (102 - 110) / 5 = -1.6
    assert out["dist_composite_poc_5d_atr"] == -1.6


def test_composite_poc_missing_inputs():
    from CORE.market_profile_advanced import compute_composite_poc, CompositePOCState
    state = CompositePOCState()
    out = compute_composite_poc({}, state)
    assert out["composite_poc_5d"] is None


# ════════════════════════════════════════════════════════════════════════════
# 3. LIQUIDITY SWEEP detector
# ════════════════════════════════════════════════════════════════════════════

def test_sweep_high_detected():
    """Sweep HIGH : high > max(N bars) PUIS close < max."""
    from CORE.market_profile_advanced import detect_liquidity_sweep, LiquiditySweepState
    state = LiquiditySweepState(sweep_window_bars=3)
    # 3 bars baseline (highs autour de 100)
    for h in [100, 102, 101]:
        detect_liquidity_sweep({"bar_high": h, "bar_low": 95, "close": 98}, state)
    # Bar de sweep : high=110 > max(100,102,101)=102, close=98 < 102
    out = detect_liquidity_sweep({"bar_high": 110, "bar_low": 95, "close": 98}, state)
    assert out["sweep_high_this_bar"] is True
    assert out["sweep_high_active"] == 1


def test_sweep_low_detected():
    """Sweep LOW : low < min(N bars) PUIS close > min."""
    from CORE.market_profile_advanced import detect_liquidity_sweep, LiquiditySweepState
    state = LiquiditySweepState(sweep_window_bars=3)
    for l in [95, 96, 94]:
        detect_liquidity_sweep({"bar_high": 100, "bar_low": l, "close": 98}, state)
    # Bar sweep : low=85 < min=94, close=98 > 94
    out = detect_liquidity_sweep({"bar_high": 100, "bar_low": 85, "close": 98}, state)
    assert out["sweep_low_this_bar"] is True
    assert out["sweep_low_active"] == 1


def test_sweep_not_triggered_when_close_above_max():
    """Pas de sweep si close reste au-dessus du max (= vrai breakout, pas sweep)."""
    from CORE.market_profile_advanced import detect_liquidity_sweep, LiquiditySweepState
    state = LiquiditySweepState(sweep_window_bars=3)
    for h in [100, 102, 101]:
        detect_liquidity_sweep({"bar_high": h, "bar_low": 95, "close": 98}, state)
    # high=110 > max=102 MAIS close=105 > 102 -> vrai breakout, pas sweep
    out = detect_liquidity_sweep({"bar_high": 110, "bar_low": 95, "close": 105}, state)
    assert out["sweep_high_this_bar"] is False


def test_sweep_fill_decrements_count():
    """Sweep actif disparait quand close re-traverse le price perce."""
    from CORE.market_profile_advanced import detect_liquidity_sweep, LiquiditySweepState
    state = LiquiditySweepState(sweep_window_bars=3)
    for h in [100, 102, 101]:
        detect_liquidity_sweep({"bar_high": h, "bar_low": 95, "close": 98}, state)
    # Sweep
    detect_liquidity_sweep({"bar_high": 110, "bar_low": 95, "close": 98}, state)
    # Close depasse le sweep level (102)
    out = detect_liquidity_sweep({"bar_high": 108, "bar_low": 100, "close": 105}, state)
    assert out["sweep_high_active"] == 0  # filled


# ════════════════════════════════════════════════════════════════════════════
# 4. JUDAS SWING detector
# ════════════════════════════════════════════════════════════════════════════

def test_judas_state_isolated_per_instance():
    from CORE.market_profile_advanced import detect_judas_swing, JudasSwingState
    state_a = JudasSwingState()
    state_b = JudasSwingState()
    detect_judas_swing(
        {"session": 1, "close": 100.0, "bar_high": 101, "bar_low": 99, "ts": 1781000000000},
        state_a,
    )
    assert state_a.in_london is True
    assert state_b.in_london is False


def test_judas_london_open_captured():
    from CORE.market_profile_advanced import detect_judas_swing, JudasSwingState
    state = JudasSwingState()
    out = detect_judas_swing(
        {"session": 1, "close": 100.0, "bar_high": 101, "bar_low": 99, "ts": 1781000000000},
        state,
    )
    assert state.london_open == 100.0
    assert out["london_open"] == 100.0


def test_judas_first_hour_direction_up():
    """First hour : close passe de 100 a 105 = direction UP."""
    from CORE.market_profile_advanced import detect_judas_swing, JudasSwingState
    state = JudasSwingState()
    # Open London
    detect_judas_swing(
        {"session": 1, "close": 100.0, "bar_high": 101, "bar_low": 99, "ts": 1781000000000},
        state,
    )
    # 60 minutes plus tard (3600 sec = 3600000 ms), close = 105
    out = detect_judas_swing(
        {"session": 1, "close": 105.0, "bar_high": 106, "bar_low": 104, "ts": 1781000000000 + 3700000},
        state,
    )
    assert state.first_hour_complete is True
    assert state.first_hour_direction == +1


def test_judas_swing_detected_when_direction_opposite():
    """Apres first hour UP, current close DOWN = Judas detected."""
    from CORE.market_profile_advanced import detect_judas_swing, JudasSwingState
    state = JudasSwingState()
    # Open London a 100
    detect_judas_swing(
        {"session": 1, "close": 100.0, "bar_high": 101, "bar_low": 99, "ts": 1781000000000},
        state,
    )
    # First hour UP (close 105 apres 60 min)
    detect_judas_swing(
        {"session": 1, "close": 105.0, "bar_high": 106, "bar_low": 104, "ts": 1781000000000 + 3700000},
        state,
    )
    # Plus tard : close descend a 99 = OPPOSITE direction
    out = detect_judas_swing(
        {"session": 1, "close": 99.0, "bar_high": 100, "bar_low": 98, "ts": 1781000000000 + 7200000},
        state,
    )
    assert out["judas_swing_active"] is True
    assert out["judas_swing_direction"] == -1


def test_judas_reset_on_exit_london():
    from CORE.market_profile_advanced import detect_judas_swing, JudasSwingState
    state = JudasSwingState()
    # Entre London
    detect_judas_swing(
        {"session": 1, "close": 100.0, "bar_high": 101, "bar_low": 99, "ts": 1781000000000},
        state,
    )
    # Sortie London
    out = detect_judas_swing(
        {"session": 2, "close": 100.0, "bar_high": 101, "bar_low": 99, "ts": 1781000000000 + 1000},
        state,
    )
    assert state.in_london is False
    assert state.london_open is None


# ════════════════════════════════════════════════════════════════════════════
# 5. API publique
# ════════════════════════════════════════════════════════════════════════════

def test_compute_market_profile_advanced_full():
    from CORE.market_profile_advanced import (
        compute_market_profile_advanced_features,
        MarketProfileAdvancedState,
    )
    state = MarketProfileAdvancedState()
    out = compute_market_profile_advanced_features(
        {
            "single_print_count": 2, "single_print_mid": 105.0,
            "ts": 1781000000000, "cur_vpoc": 100.0,
            "bar_high": 102, "bar_low": 98, "close": 100.0,
            "atr": 5.0, "session": 1,
        },
        state,
    )
    expected_keys = [
        "has_single_prints", "dist_single_print_atr",
        "composite_poc_5d", "composite_poc_20d",
        "sweep_high_active", "sweep_low_active",
        "judas_swing_active", "london_open",
    ]
    for k in expected_keys:
        assert k in out


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
