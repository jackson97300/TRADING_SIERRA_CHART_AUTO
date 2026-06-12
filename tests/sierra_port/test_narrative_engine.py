"""Tests narrative_engine.py + scenario_generator.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# Fixture : bar realiste NQ (inspired by audit 12/06 10:17 UTC)
# ════════════════════════════════════════════════════════════════════════════

def _build_realistic_nq_bar() -> dict:
    """Bar NQ realiste pour tests."""
    return {
        "ts": 1781256960000,
        "sym": "NQ",
        "close": 29594.50,
        "atr": 186.0,
        "atr_14m": 15.0,
        "vix_level": 18.85,
        # Niveaux veille
        "pdh": 29544.25,
        "pdl": 28265.75,
        "prev_vah": 28883.75,
        "prev_val": 28582.75,
        "prev_vpoc": 28600.00,
        "prev_vwap": 28850.00,
        "prev_vwap_sd1u": 29150.00,
        "prev_vwap_sd1d": 28550.00,
        "prev_vwap_sd2u": 29450.00,
        "prev_vwap_sd2d": 28250.00,
        "cash_high": 29675.00,
        "cash_low": 28678.50,
        # VWAP
        "vwap_d": 29304.67,
        "vwap_d_sd1u": 29532.84,
        "vwap_d_sd1d": 29076.49,
        "vwap_d_sd2u": 29761.02,
        "vwap_d_sd2d": 28848.32,
        "vwap_w": 29094.28,
        "vwap_m": 29672.09,
        # Session courante
        "cur_vah": 29495.25,
        "cur_val": 29082.00,
        "cur_vpoc": 29196.50,
        "sess_high": 29675.00,
        "sess_low": 29260.00,
        "ovn_high": 29675.00,
        "ovn_low": 29260.00,
        "range_pos_va": 100.0,
        "inside_cur_va": 0,
        # Phase A.2a
        "open_relation_type": 2,  # OAOR
        "profile_overlap_pct": 0.0,
        "range_extension_completed": False,
        # Phase A.3
        "has_single_prints": True,
        "single_print_above": False,
        "single_print_below": True,
        "dist_single_print_atr": -0.56,
        "single_print_density": 0.51,
        "fvg_up_active": 16,
        "fvg_dn_active": 3,
        "dist_fvg_up_nearest_atr": 0.5,
        "dist_fvg_dn_nearest_atr": -0.3,
        "sweep_high_active": 0,
        "sweep_low_active": 0,
        "sweep_high_this_bar": False,
        "sweep_low_this_bar": False,
        "judas_swing_active": False,
        "judas_swing_direction": 0,
        "london_open": 29350.0,
        "london_first_hour_direction": 1,
        "bars_since_london_open": 254,
        # Profile Dalton
        "profile_shape": 1,  # P-shape
        "day_type": 2,  # NormVar
        "trend_day_probability": 0.0,
        # Order flow
        "delta_day": 6818,
        "cvd_day": 16188,
        "cvd_session": -223,
        "finish_strength": -20,
        "bn_color_up": 0,
        "bn_color_dn": 0,
        "bn_absorb_ask": 0,
        "bn_absorb_bid": 0,
        "bn_score_raw": 0.0,
        "delta_div_slope_strength": 0.0035,
        "delta_divergence": 0,
        # Session
        "session_segment": "london",
        "is_in_london": True,
        "is_in_us_cash": False,
        "is_in_us_after": False,
        "is_in_asia": False,
        "mins_et": 377,
        "tod_bucket_rth": 0,
        # Swing
        "dist_swing_high": 252.0,
        "dist_swing_low": -62.0,
    }


# ════════════════════════════════════════════════════════════════════════════
# narrative_engine
# ════════════════════════════════════════════════════════════════════════════

def test_build_context_returns_valid_struct():
    """API publique retourne NarrativeContext avec champs critiques."""
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    assert ctx.symbol == "NQ"
    assert ctx.close == 29594.50
    assert ctx.atr == 186.0
    assert ctx.vix_level == 18.85


def test_context_macro_regime_calm():
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    assert ctx.macro_regime == "calm"  # VIX 18.85 < 20


def test_context_market_structure_OAOR():
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    assert ctx.market_structure.open_relation == "OAOR"
    assert ctx.market_structure.profile_shape == "P"
    assert ctx.market_structure.day_type == "NormVar"


def test_context_order_flow_macro_bull_session_bear():
    """CVD day +16188 = BULL, cvd_session -223 = neutre."""
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    assert ctx.order_flow.macro_bias == "BULL"
    # cvd_session -223 sous threshold |200| -> bias BEAR (en valeur absolue dans threshold)
    # NEUTRAL si abs < threshold, BEAR si < -threshold
    assert ctx.order_flow.session_bias in ("NEUTRAL", "BEAR")


def test_context_session_london_active():
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    assert ctx.session.is_in_london is True
    assert ctx.session.london_open == 29350.0
    assert ctx.session.london_first_hour_direction == 1


def test_context_patterns_single_prints_below():
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    assert ctx.patterns.single_prints_present is True
    assert ctx.patterns.single_print_position == "below"
    assert ctx.patterns.fvg_up_count == 16
    assert ctx.patterns.fvg_dn_count == 3


def test_context_key_levels_resistance_above_close():
    """Tous les niveaux resistance doivent etre > close."""
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    for lvl in ctx.key_levels_resistance:
        assert lvl.price > ctx.close
        assert lvl.distance_atr > 0


def test_context_key_levels_support_below_close():
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    for lvl in ctx.key_levels_support:
        assert lvl.price < ctx.close
        assert lvl.distance_atr < 0


def test_context_resistance_clustering_finds_confluence():
    """Cluster 29672-29675 (VWAP month + cash high + sess high + OVN high) = 1 niveau confluence."""
    from CORE.narrative_engine import build_narrative_context
    ctx = build_narrative_context(_build_realistic_nq_bar())
    # Cherche niveau confluence >= 2 sources autour de 29675
    confluences = [
        lvl for lvl in ctx.key_levels_resistance
        if 29650 <= lvl.price <= 29700 and lvl.confluence_count >= 2
    ]
    assert len(confluences) >= 1, f"Expected confluence around 29672-29675, got {[(l.price, l.confluence_count) for l in ctx.key_levels_resistance[:5]]}"


# ════════════════════════════════════════════════════════════════════════════
# scenario_generator
# ════════════════════════════════════════════════════════════════════════════

def test_generate_scenarios_returns_at_least_one():
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    ctx = build_narrative_context(_build_realistic_nq_bar())
    scenarios = generate_scenarios(ctx)
    assert len(scenarios) >= 1


def test_scenarios_sorted_by_probability():
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    ctx = build_narrative_context(_build_realistic_nq_bar())
    scenarios = generate_scenarios(ctx)
    probas = [s.probability_pct for s in scenarios]
    assert probas == sorted(probas, reverse=True), f"Not sorted: {probas}"


def test_scenarios_contain_setups_with_rr():
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    ctx = build_narrative_context(_build_realistic_nq_bar())
    scenarios = generate_scenarios(ctx)
    for sc in scenarios:
        assert sc.name
        assert sc.direction in ("bullish", "bearish", "range")
        assert 0 <= sc.probability_pct <= 100
        for setup in sc.setups:
            assert setup.side in ("long", "short")
            assert setup.r_r_ratio >= 0
            assert setup.entry_price > 0


def test_bullish_continuation_present_when_cvd_day_strong():
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    ctx = build_narrative_context(_build_realistic_nq_bar())
    scenarios = generate_scenarios(ctx)
    names = [s.name for s in scenarios]
    # CVD day +16188 -> bull continuation devrait etre present
    assert any("Bullish continuation" in n for n in names)


def test_bearish_rejection_present_when_confluence():
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    ctx = build_narrative_context(_build_realistic_nq_bar())
    scenarios = generate_scenarios(ctx)
    names = [s.name for s in scenarios]
    assert any("Bearish rejection" in n for n in names)


def test_range_bound_present_when_normvar():
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    ctx = build_narrative_context(_build_realistic_nq_bar())
    scenarios = generate_scenarios(ctx)
    names = [s.name for s in scenarios]
    # day_type = NormVar + trend_day_prob = 0 -> Range bound devrait etre present
    assert any("Range bound" in n for n in names)


def test_judas_scenario_absent_when_judas_not_active():
    """Bar realiste : judas_swing_active = False -> Judas scenario absent."""
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    ctx = build_narrative_context(_build_realistic_nq_bar())
    scenarios = generate_scenarios(ctx)
    names = [s.name for s in scenarios]
    assert not any("Judas Swing" in n for n in names)


def test_judas_scenario_present_when_activated():
    """Modifier bar : judas_swing_active = True + direction = -1 -> Judas SHORT present."""
    from CORE.narrative_engine import build_narrative_context
    from CORE.scenario_generator import generate_scenarios
    bar = _build_realistic_nq_bar()
    bar["judas_swing_active"] = True
    bar["judas_swing_direction"] = -1
    ctx = build_narrative_context(bar)
    scenarios = generate_scenarios(ctx)
    names = [s.name for s in scenarios]
    assert any("Judas Swing reversal SHORT" in n for n in names)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
