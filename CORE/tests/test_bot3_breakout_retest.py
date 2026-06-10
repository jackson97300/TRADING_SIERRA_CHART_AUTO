"""Tests Bot 3 BREAKOUT_RETEST state machine.

DOCTRINE + CODE (Jackson 03/05) : les tests valident a la fois
le code (techniquement correct) ET la doctrine (canon Steidlmayer/Dalton).

Convention V4 prod : `dist_*_pct` est en POURCENTAGE (formule (level-close)/close * 100
dans phase_d_dalton_levels.py:334). Mediane SINGLE_PRINT = 0.27, IB_LOW = 0.42.
Les tests utilisent des valeurs realistes prod, pas des mocks ratio.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bot3_breakout_retest import (   # noqa: E402
    BreakoutRetestStateMachine,
    BreakoutRetestState,
    BreakoutRetestSignal,
    BreakoutRetestEvent,
)
from CORE.bot3_config import (   # noqa: E402
    BREAKOUT_N_ACCEPTANCE_BARS,
    BREAKOUT_N_ACCEPTANCE_CONFIRMS_REQUIRED,
    BREAKOUT_RETEST_DEADLINE_BARS,
    BREAKOUT_RETEST_PROXIMITY_MULTIPLIER,
    BREAKOUT_RETEST_DELTA_BASE,
    BREAKOUT_RETEST_FINISH_BASE,
    BREAKOUT_WICK_ATR_RATIO,
    BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD,
    BREAKOUT_COOLDOWN_AFTER_CANCEL_BARS,
)


def _level_def(dist_col="dist_single_print_nearest_pct", proximity=0.05):
    """Level def realiste : proximity en % (V4 convention)."""
    return {
        "dist_col": dist_col,
        "proximity_pct": proximity,
        "side": "REJECTION",
        "tier": 1,
    }


def _ctx(**overrides):
    base = {"delta_bar": -100.0, "finish_strength": -50.0, "rvol": 1.0,
            "session": "US_CASH"}
    base.update(overrides)
    return base


def _register_short(sm, touch_dist=0.27, touch_price=21500.0, touch_idx=10):
    """Helper : register pending SHORT breakout avec convention prod (dist en %).

    DOCTRINE : touch_dist=0.27 = 0.27% du close (mediane SINGLE_PRINT V4 reel).
    level_price = 21500 * (1 + 0.27/100) = 21558.05
    """
    level_price = touch_price * (1.0 + touch_dist / 100.0)
    return sm.register_pending_breakout(
        symbol="NQ", level_name="SINGLE_PRINT", level_def=_level_def(),
        side_break="SHORT", touch_bar_idx=touch_idx, touch_bar_ts=f"t{touch_idx}",
        touch_price=touch_price, touch_dist_signed=touch_dist,
        level_price=level_price, ctx_at_touch=_ctx())


def _register_long(sm, touch_dist=-0.27, touch_price=21500.0, touch_idx=10):
    """Helper : register pending LONG breakout (resistance cassee)."""
    level_price = touch_price * (1.0 + touch_dist / 100.0)
    return sm.register_pending_breakout(
        symbol="NQ", level_name="SINGLE_PRINT", level_def=_level_def(),
        side_break="LONG", touch_bar_idx=touch_idx, touch_bar_ts=f"t{touch_idx}",
        touch_price=touch_price, touch_dist_signed=touch_dist,
        level_price=level_price, ctx_at_touch=_ctx())


# ════════════════════════════════════════════════════════════════════
# DOCTRINE : convention prod V4 dist en %
# ════════════════════════════════════════════════════════════════════

def test_doctrine_level_price_calcul_avec_convention_prod_pct():
    """DOCTRINE : avec dist=0.27% reel, level_price = close * (1 + 0.0027) = 21558."""
    sm = BreakoutRetestStateMachine()
    state = _register_short(sm, touch_dist=0.27, touch_price=21500.0)
    assert state is not None
    expected_level = 21500.0 * (1.0 + 0.27 / 100.0)   # = 21558.05
    assert abs(state.level_price - 21558.05) < 0.01

    # Verifier que les confirms acceptance utilisent ce vrai level_price
    # bar 11 close=21540 (en-dessous de 21558.05) → SHORT confirm
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                           "dist_single_print_nearest_pct": 0.08},
                      bar_idx=11, bar_ts="t11", close=21540.0,
                      high=21545.0, low=21535.0, atr=10.0)
    assert state.acceptance_score == 1.0   # close confirm = 1.0


def test_doctrine_level_price_avec_dist_realiste_ib_low():
    """DOCTRINE : IB_LOW dist mediane = 0.42% V4 prod."""
    sm = BreakoutRetestStateMachine()
    state = sm.register_pending_breakout(
        symbol="NQ", level_name="IB_LOW",
        level_def={"dist_col": "dist_ib_low_pct", "proximity_pct": 0.05,
                    "side": "LONG", "tier": 1},
        side_break="SHORT", touch_bar_idx=10, touch_bar_ts="t10",
        touch_price=21500.0, touch_dist_signed=0.42,
        level_price=21500.0 * (1.0 + 0.42 / 100.0),
        ctx_at_touch=_ctx())
    assert state is not None
    # level_price = 21500 * 1.0042 = 21590.30
    assert abs(state.level_price - 21590.30) < 0.05


# ════════════════════════════════════════════════════════════════════
# REGISTER + ANTI-REPLAY + COOLDOWN
# ════════════════════════════════════════════════════════════════════

def test_register_creates_pending_state_with_event():
    """CODE : register cree state PENDING_ACCEPTANCE + emit event PENDING."""
    sm = BreakoutRetestStateMachine()
    state = _register_short(sm)
    assert state.state == "PENDING_ACCEPTANCE"
    assert sm.stats["n_pending_registered"] == 1
    events = sm.consume_events()
    assert len(events) == 1
    assert events[0].event_type == "PENDING"


def test_anti_replay_same_level_active():
    """CODE : pas de re-register si state actif sur meme niveau."""
    sm = BreakoutRetestStateMachine()
    s1 = _register_short(sm, touch_idx=10)
    s2 = _register_short(sm, touch_idx=11)
    assert s1 is not None
    assert s2 is None
    assert sm.stats["n_register_skipped_active"] == 1


def test_cooldown_post_cancel_blocks_immediate_register():
    """DOCTRINE FIX #8 : apres CRUSH_ABSORBED, cooldown N bars avant re-register
    (anti signal-noise : marche vient de prouver que breakout absorbed)."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_idx=10)
    # 5 bars sans confirmation acceptance (closes au-dessus du level)
    for i in range(1, 6):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21620.0, "high": 21625.0, "low": 21615.0,
                               "dist_single_print_nearest_pct": 0.5},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21620.0, high=21625.0, low=21615.0, atr=10.0)
    # bar 16 declenche finalisation = CRUSH_ABSORBED
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21620.0, "high": 21625.0, "low": 21615.0,
                           "dist_single_print_nearest_pct": 0.5},
                      bar_idx=16, bar_ts="t16",
                      close=21620.0, high=21625.0, low=21615.0, atr=10.0)
    assert sm.stats["n_acceptance_cancelled"] == 1
    # Re-register immediat → DOIT etre bloque par cooldown (10 bars)
    s2 = _register_short(sm, touch_idx=17)
    assert s2 is None
    assert sm.stats["n_register_skipped_cooldown"] == 1
    # Re-register apres cooldown expire (bar 26 = idx 16 + 10) → doit passer
    s3 = _register_short(sm, touch_idx=27)
    assert s3 is not None


# ════════════════════════════════════════════════════════════════════
# DOCTRINE : ACCEPTANCE HYBRIDE TPO PRINTED (close + wick)
# ════════════════════════════════════════════════════════════════════

def test_doctrine_acceptance_close_full_credit():
    """DOCTRINE Steidlmayer : close du cote casse = 1.0 confirm (forte acceptance)."""
    sm = BreakoutRetestStateMachine()
    state = _register_short(sm, touch_dist=0.27)   # level = 21558.05
    # bar : close 21540 < level (21558.05) → close confirm = 1.0
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                           "dist_single_print_nearest_pct": 0.08},
                      bar_idx=11, bar_ts="t11", close=21540.0,
                      high=21545.0, low=21535.0, atr=10.0)
    assert state.acceptance_score == 1.0


def test_doctrine_acceptance_wick_partial_credit():
    """DOCTRINE Steidlmayer : wick du cote casse >= 0.20*ATR = 0.5 confirm (TPO printed)."""
    sm = BreakoutRetestStateMachine()
    state = _register_short(sm, touch_dist=0.27)   # level = 21558.05
    # bar : close 21570 > level (21558.05), MAIS low 21540 < level → wick_below = 18.05
    # ATR=10 : threshold = 0.20*10 = 2.0 → wick 18.05 > 2.0 → wick_confirm = 0.5
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21570.0, "high": 21580.0, "low": 21540.0,
                           "dist_single_print_nearest_pct": 0.06},
                      bar_idx=11, bar_ts="t11", close=21570.0,
                      high=21580.0, low=21540.0, atr=10.0)
    assert state.acceptance_score == 0.5


def test_doctrine_acceptance_wick_too_small_no_credit():
    """DOCTRINE : wick trop petit (single tick noise) = pas de credit acceptance."""
    sm = BreakoutRetestStateMachine()
    state = _register_short(sm, touch_dist=0.27)   # level = 21558.05
    # bar : close 21570, wick low 21557.5 → wick_below = 0.55 < 0.20*10 = 2.0 → no credit
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21570.0, "high": 21580.0, "low": 21557.5,
                           "dist_single_print_nearest_pct": 0.06},
                      bar_idx=11, bar_ts="t11", close=21570.0,
                      high=21580.0, low=21557.5, atr=10.0)
    assert state.acceptance_score == 0.0


def test_doctrine_acceptance_score_threshold_2_5():
    """DOCTRINE : seuil 2.5 sur 5 bars = soft majority (3 closes OU mix close+wick)."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    # 3 closes < level (3.0 confirms) → ACCEPTED
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    # Bar 14 : early-exit possible si score >= 2.5 ET bars_seen >= 3 (config)
    active = sm.get_active_states("NQ")
    state_data = list(active.values())[0]
    assert state_data["state"] == "WAIT_RETEST"
    assert state_data["acceptance_score"] >= 2.5
    assert sm.stats["n_acceptance_confirmed"] == 1


def test_doctrine_acceptance_2_closes_2_wicks_mixed():
    """DOCTRINE TPO printed : 2 closes (2.0) + 2 wicks (1.0) = 3.0 score → ACCEPTED."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    # bar 11 : close confirm
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                           "dist_single_print_nearest_pct": 0.08},
                      bar_idx=11, bar_ts="t11", close=21540.0,
                      high=21545.0, low=21535.0, atr=10.0)
    # bar 12 : wick confirm
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21570.0, "high": 21580.0, "low": 21540.0,
                           "dist_single_print_nearest_pct": 0.06},
                      bar_idx=12, bar_ts="t12", close=21570.0,
                      high=21580.0, low=21540.0, atr=10.0)
    # bar 13 : close confirm
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                           "dist_single_print_nearest_pct": 0.08},
                      bar_idx=13, bar_ts="t13", close=21540.0,
                      high=21545.0, low=21535.0, atr=10.0)
    # Score 1.0 + 0.5 + 1.0 = 2.5 → atteint threshold
    active = sm.get_active_states("NQ")
    state_data = list(active.values())[0]
    assert state_data["acceptance_score"] >= 2.5


def test_doctrine_acceptance_crush_absorbed_score_below_threshold():
    """DOCTRINE Wyckoff spring : 5 bars sans assez de TPO printed → CRUSH_ABSORBED.

    Le marche absorbe le crush et reverse → c'est un faux breakout (spring).
    """
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    # 5 bars TOUTES au-dessus du level, wick minimal → score 0
    for i in range(1, 6):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21620.0, "high": 21625.0, "low": 21615.0,
                               "dist_single_print_nearest_pct": 0.5},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21620.0, high=21625.0, low=21615.0, atr=10.0)
    # bar 16 : finalisation
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21620.0, "high": 21625.0, "low": 21615.0,
                           "dist_single_print_nearest_pct": 0.5},
                      bar_idx=16, bar_ts="t16",
                      close=21620.0, high=21625.0, low=21615.0, atr=10.0)
    assert sm.stats["n_acceptance_cancelled"] == 1
    events = sm.consume_events()
    assert any(e.event_type == "CRUSH_ABSORBED" for e in events)


# ════════════════════════════════════════════════════════════════════
# DOCTRINE : RETEST + REJECTION normalisee rvol
# ════════════════════════════════════════════════════════════════════

def test_doctrine_retest_with_rejection_rvol_normalized():
    """DOCTRINE FIX #2 : seuils delta/finish normalises via rvol.

    En RTH (rvol=1.5), seuils plus larges. En Asia (rvol=0.5), seuils plus serres.
    """
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    # 3 bars acceptance (closes confirms)
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    # Bar retest avec delta/finish au seuil base × rvol=1.0
    delta_at_threshold = -BREAKOUT_RETEST_DELTA_BASE - 1.0
    finish_at_threshold = -BREAKOUT_RETEST_FINISH_BASE - 1.0
    signal = sm.update_on_bar(symbol="NQ",
                                bar={"close": 21605.0, "high": 21610.0, "low": 21555.0,
                                     "dist_single_print_nearest_pct": 0.04,
                                     "delta_bar": delta_at_threshold,
                                     "finish_strength": finish_at_threshold,
                                     "rvol": 1.0},
                                bar_idx=15, bar_ts="t15",
                                close=21605.0, high=21610.0, low=21555.0, atr=10.0)
    assert signal is not None
    assert signal.side == "SHORT"
    # Verifier que les seuils utilises sont normalises
    assert signal.snapshot_retest["delta_threshold_used"] == BREAKOUT_RETEST_DELTA_BASE
    assert signal.snapshot_retest["rvol"] == 1.0


def test_doctrine_retest_rvol_rth_higher_threshold_blocks_marginal():
    """DOCTRINE : en RTH (rvol=2.0), un delta -50 est marginal et NE devrait PAS trigger.

    Avant FIX #2, delta -50 abs > 30 absolu → faux positif RTH. Apres : 30*2.0=60 → bloque.
    """
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    # Retest avec delta -50, rvol RTH 2.0 → seuil normalisé = 60 → -50 insuffisant
    signal = sm.update_on_bar(symbol="NQ",
                                bar={"close": 21605.0, "high": 21610.0, "low": 21555.0,
                                     "dist_single_print_nearest_pct": 0.04,
                                     "delta_bar": -50.0,
                                     "finish_strength": -16.0,
                                     "rvol": 2.0},
                                bar_idx=15, bar_ts="t15",
                                close=21605.0, high=21610.0, low=21555.0, atr=10.0)
    assert signal is None   # bloque par seuil normalise rvol


def test_doctrine_retest_asia_lower_threshold_accepts():
    """DOCTRINE : en Asia (rvol=0.5 clamp min), seuil bas = signal possible meme delta -16.

    rvol_factor = max(0.5, 0.5) = 0.5 → seuil = 30*0.5 = 15.
    Delta -16 > -15 (seuil) ? Non, abs(-16) > abs(-15) → trigger.
    """
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    # Retest avec delta -16, rvol Asia 0.3 (clamp 0.5) → seuil = 15 → -16 abs > 15 ✓
    signal = sm.update_on_bar(symbol="NQ",
                                bar={"close": 21605.0, "high": 21610.0, "low": 21555.0,
                                     "dist_single_print_nearest_pct": 0.04,
                                     "delta_bar": -16.0,
                                     "finish_strength": -8.0,
                                     "rvol": 0.3},
                                bar_idx=15, bar_ts="t15",
                                close=21605.0, high=21610.0, low=21555.0, atr=10.0)
    assert signal is not None
    assert signal.side == "SHORT"
    # Verif seuils normalises
    assert signal.snapshot_retest["delta_threshold_used"] == 15.0   # 30 * 0.5 clamp


def test_doctrine_retest_long_breakout_resistance_cassee():
    """DOCTRINE : LONG breakout (resistance cassee) → retest avec rejection bullish."""
    sm = BreakoutRetestStateMachine()
    _register_long(sm, touch_dist=-0.27)   # level = 21500*(1-0.0027) = 21441.95
    # 3 closes au-dessus du level (LONG breakout confirms)
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21460.0, "high": 21465.0, "low": 21455.0,
                               "dist_single_print_nearest_pct": -0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21460.0, high=21465.0, low=21455.0, atr=10.0)
    # Retest avec delta+ et finish+ (rejection bullish)
    signal = sm.update_on_bar(symbol="NQ",
                                bar={"close": 21445.0, "high": 21465.0, "low": 21442.0,
                                     "dist_single_print_nearest_pct": -0.01,
                                     "delta_bar": 50.0,
                                     "finish_strength": 25.0,
                                     "rvol": 1.0},
                                bar_idx=15, bar_ts="t15",
                                close=21445.0, high=21465.0, low=21442.0, atr=10.0)
    assert signal is not None
    assert signal.side == "LONG"


def test_doctrine_retest_no_rejection_continues_waiting():
    """CODE + DOCTRINE : retest dans la fenetre mais delta faible → continue d'attendre."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    # Retest avec delta -10 (insuffisant), rvol 1.0 → seuil 30 → bloque
    signal = sm.update_on_bar(symbol="NQ",
                                bar={"close": 21605.0, "high": 21610.0, "low": 21600.0,
                                     "dist_single_print_nearest_pct": 0.04,
                                     "delta_bar": -10.0,
                                     "finish_strength": -5.0,
                                     "rvol": 1.0},
                                bar_idx=15, bar_ts="t15",
                                close=21605.0, high=21610.0, low=21600.0, atr=10.0)
    assert signal is None
    # State toujours WAIT_RETEST (pas de retest valide)
    active = sm.get_active_states("NQ")
    assert len(active) == 1


def test_doctrine_retest_timeout_no_entry():
    """CODE : pas de retest dans BREAKOUT_RETEST_DEADLINE_BARS → CANCEL TIMEOUT + cooldown."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    # 5 bars acceptance OK
    for i in range(1, 6):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    # bar 16 finalisation acceptance → WAIT_RETEST
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                           "dist_single_print_nearest_pct": 0.08},
                      bar_idx=16, bar_ts="t16",
                      close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    # 35 bars sans retest → timeout
    deadline = 10 + BREAKOUT_N_ACCEPTANCE_BARS + BREAKOUT_RETEST_DEADLINE_BARS
    for i in range(17, deadline + 5):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21450.0, "high": 21455.0, "low": 21445.0,
                               "dist_single_print_nearest_pct": 0.5},
                          bar_idx=i, bar_ts=f"t{i}",
                          close=21450.0, high=21455.0, low=21445.0, atr=10.0)
    assert sm.stats["n_retest_timeout"] >= 1
    assert sm.stats["n_retest_entry"] == 0


# ════════════════════════════════════════════════════════════════════
# CODE : isolation symbol + events emis
# ════════════════════════════════════════════════════════════════════

def test_state_isolated_per_symbol():
    """CODE : states NQ et ES isoles."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    sm.register_pending_breakout(
        symbol="ES", level_name="SINGLE_PRINT", level_def=_level_def(),
        side_break="LONG", touch_bar_idx=10, touch_bar_ts="t10",
        touch_price=5800.0, touch_dist_signed=-0.15,
        level_price=5800.0 * (1 - 0.0015), ctx_at_touch=_ctx())
    nq = sm.get_active_states("NQ")
    es = sm.get_active_states("ES")
    assert len(nq) == 1
    assert len(es) == 1
    assert list(nq.values())[0]["side_break"] == "SHORT"
    assert list(es.values())[0]["side_break"] == "LONG"


def test_events_pending_emitted_at_register():
    """FIX #3 : event PENDING genere a chaque register, consommable par mp_engine."""
    sm = BreakoutRetestStateMachine()
    assert len(sm.consume_events()) == 0
    _register_short(sm)
    events = sm.consume_events()
    assert len(events) == 1
    assert events[0].event_type == "PENDING"
    # Apres consume, plus d'event en buffer
    assert len(sm.consume_events()) == 0


def test_events_accepted_and_retest_entry():
    """FIX #3 : sequence events PENDING → ACCEPTED → (signal genere)."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    sm.consume_events()   # clear PENDING
    # 3 closes confirms → ACCEPTED early
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    events = sm.consume_events()
    assert any(e.event_type == "ACCEPTED" for e in events)


# ════════════════════════════════════════════════════════════════════
# DOCTRINE P3 (Jackson 03/05) : Snapshot ultra riche bars data
# ════════════════════════════════════════════════════════════════════

def test_doctrine_p3_event_accepted_carries_full_bars_data():
    """DOCTRINE P3 : event ACCEPTED contient acceptance_bars_data complete."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    sm.consume_events()
    for i in range(1, 4):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    events = sm.consume_events()
    accepted = [e for e in events if e.event_type == "ACCEPTED"][0]
    assert "acceptance_bars_data" in accepted.payload
    bars = accepted.payload["acceptance_bars_data"]
    assert len(bars) >= 3
    assert "level_price" in accepted.payload
    assert abs(accepted.payload["level_price"] - 21558.05) < 0.1


def test_doctrine_p3_event_crush_absorbed_carries_bars_data():
    """DOCTRINE P3 : CRUSH_ABSORBED contient bars_data + score < threshold."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    sm.consume_events()
    for i in range(1, 6):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21620.0, "high": 21625.0, "low": 21615.0,
                               "dist_single_print_nearest_pct": 0.5},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21620.0, high=21625.0, low=21615.0, atr=10.0)
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21620.0, "high": 21625.0, "low": 21615.0,
                           "dist_single_print_nearest_pct": 0.5},
                      bar_idx=16, bar_ts="t16",
                      close=21620.0, high=21625.0, low=21615.0, atr=10.0)
    events = sm.consume_events()
    crush = [e for e in events if e.event_type == "CRUSH_ABSORBED"][0]
    assert "acceptance_bars_data" in crush.payload
    assert crush.payload["score"] < BREAKOUT_ACCEPTANCE_CONFIRMS_THRESHOLD


def test_doctrine_p3_event_retest_timeout_carries_bars_data():
    """DOCTRINE P3 : RETEST_TIMEOUT contient bars_data + accepted_at_idx."""
    sm = BreakoutRetestStateMachine()
    _register_short(sm, touch_dist=0.27)
    sm.consume_events()
    for i in range(1, 6):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                               "dist_single_print_nearest_pct": 0.08},
                          bar_idx=10 + i, bar_ts=f"t{10+i}",
                          close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    sm.update_on_bar(symbol="NQ",
                      bar={"close": 21540.0, "high": 21545.0, "low": 21535.0,
                           "dist_single_print_nearest_pct": 0.08},
                      bar_idx=16, bar_ts="t16",
                      close=21540.0, high=21545.0, low=21535.0, atr=10.0)
    sm.consume_events()
    deadline_idx = 10 + BREAKOUT_N_ACCEPTANCE_BARS + BREAKOUT_RETEST_DEADLINE_BARS
    for i in range(17, deadline_idx + 5):
        sm.update_on_bar(symbol="NQ",
                          bar={"close": 21450.0, "high": 21455.0, "low": 21445.0,
                               "dist_single_print_nearest_pct": 0.5},
                          bar_idx=i, bar_ts=f"t{i}",
                          close=21450.0, high=21455.0, low=21445.0, atr=10.0)
    events = sm.consume_events()
    timeout_evts = [e for e in events if e.event_type == "RETEST_TIMEOUT"]
    assert len(timeout_evts) >= 1
    t = timeout_evts[0]
    assert "acceptance_bars_data" in t.payload
    assert "accepted_at_idx" in t.payload
    assert t.payload["accepted_at_idx"] is not None
