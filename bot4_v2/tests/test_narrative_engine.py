"""Tests bot4_v2/core/narrative_engine."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bot4_v2.core.narrative_engine import (
    CONFLUENCE_ATR_FRAC,
    DAY_TYPE_MAP,
    OPEN_RELATION_MAP,
    PROFILE_SHAPE_MAP,
    KeyLevel,
    MarketStructureState,
    NarrativeContext,
    OrderFlowState,
    PatternsDetected,
    SessionState,
    _bias_from_value,
    _cluster_levels,
    _extract_market_structure,
    _extract_order_flow,
    _extract_patterns,
    _extract_session,
    _macro_regime_from_vix,
    _pvwap,
    _safe_bool,
    _safe_float,
    _safe_int,
    build_narrative_context,
)


# ============================================================
# _safe_* helpers
# ============================================================

def test_safe_float_missing_key_default():
    assert _safe_float({}, "x", default=42.0) == 42.0


def test_safe_float_none_value_default():
    assert _safe_float({"x": None}, "x", default=42.0) == 42.0


def test_safe_float_valid():
    assert _safe_float({"x": "1.5"}, "x") == 1.5


def test_safe_float_invalid_string_default():
    assert _safe_float({"x": "not_a_float"}, "x", default=7.7) == 7.7


def test_safe_int_missing_default():
    assert _safe_int({}, "x", default=10) == 10


def test_safe_int_valid():
    assert _safe_int({"x": "5"}, "x") == 5


def test_safe_int_invalid_default():
    assert _safe_int({"x": "abc"}, "x", default=99) == 99


def test_safe_bool_missing_default():
    assert _safe_bool({}, "x", default=True) is True


def test_safe_bool_truthy():
    assert _safe_bool({"x": 1}, "x") is True


def test_safe_bool_falsy():
    assert _safe_bool({"x": 0}, "x") is False


# ============================================================
# _pvwap helper
# ============================================================

def test_pvwap_uses_prev_vwap_first():
    assert _pvwap({"prev_vwap": 100.0, "pvwap": 200.0}) == 100.0


def test_pvwap_fallback_to_pvwap():
    assert _pvwap({"pvwap": 200.0}) == 200.0


def test_pvwap_filters_zero_prev_vwap():
    """prev_vwap=0.0 invalide -> fallback pvwap."""
    assert _pvwap({"prev_vwap": 0.0, "pvwap": 200.0}) == 200.0


def test_pvwap_none_returns_none():
    assert _pvwap({}) is None


# ============================================================
# _bias_from_value
# ============================================================

def test_bias_bull():
    assert _bias_from_value(5.0) == "BULL"


def test_bias_bear():
    assert _bias_from_value(-5.0) == "BEAR"


def test_bias_neutral_zero():
    assert _bias_from_value(0.0) == "NEUTRAL"


def test_bias_threshold_strict():
    """value == threshold -> NEUTRAL (>threshold strict)."""
    assert _bias_from_value(5.0, threshold=5.0) == "NEUTRAL"
    assert _bias_from_value(5.1, threshold=5.0) == "BULL"


# ============================================================
# _macro_regime_from_vix
# ============================================================

@pytest.mark.parametrize("vix, expected", [
    (10.0, "calm_vix_low"),
    (14.9, "calm_vix_low"),
    (15.0, "calm"),
    (19.9, "calm"),
    (20.0, "elevated"),
    (24.9, "elevated"),
    (25.0, "stressed"),
    (34.9, "stressed"),
    (35.0, "extreme"),
    (50.0, "extreme"),
])
def test_macro_regime_thresholds(vix, expected):
    assert _macro_regime_from_vix(vix) == expected


# ============================================================
# Constants & maps
# ============================================================

def test_day_type_map_complete():
    """5 day types Steidlmayer."""
    assert DAY_TYPE_MAP == {
        0: "NonTrend", 1: "Normal", 2: "NormVar", 3: "Neutral", 4: "Trend",
    }


def test_profile_shape_map_complete():
    assert PROFILE_SHAPE_MAP == {0: "D", 1: "P", 2: "b", 3: "B"}


def test_open_relation_map_complete():
    assert OPEN_RELATION_MAP == {
        0: "UNKNOWN", 1: "OAIR", 2: "OAOR", 3: "OOR",
    }


def test_confluence_atr_frac_reasonable():
    """10% ATR = ~18 pts NQ live (review 12/06 anti-merge agressif)."""
    assert 0.05 <= CONFLUENCE_ATR_FRAC <= 0.30


# ============================================================
# KeyLevel dataclass
# ============================================================

def test_key_level_dataclass():
    kl = KeyLevel(
        price=20000.0, label="PDH", level_type="resistance",
        distance_atr=0.5,
    )
    assert kl.price == 20000.0
    assert kl.sources == []  # default
    assert kl.confluence_count == 1  # default


# ============================================================
# _cluster_levels
# ============================================================

def test_cluster_levels_empty():
    assert _cluster_levels([], atr=10.0, close=20000.0) == []


def test_cluster_levels_zero_atr():
    """ATR=0 -> retourne levels tel quel (pas de cluster)."""
    levels = [KeyLevel(price=20000.0, label="A", level_type="resistance", distance_atr=0.5)]
    result = _cluster_levels(levels, atr=0, close=20000.0)
    assert result == levels


def test_cluster_levels_no_cluster_distant():
    """Levels distants -> pas de cluster."""
    levels = [
        KeyLevel(price=20000.0, label="A", level_type="resistance", distance_atr=0.5),
        KeyLevel(price=20100.0, label="B", level_type="resistance", distance_atr=1.5),
    ]
    result = _cluster_levels(levels, atr=10.0, close=19990.0)
    assert len(result) == 2
    assert result[0].confluence_count == 1
    assert result[1].confluence_count == 1


def test_cluster_levels_merges_close():
    """Levels proches (<10% ATR) -> cluster avec sources fusionnees."""
    levels = [
        KeyLevel(price=20000.0, label="A", level_type="resistance",
                 distance_atr=0.5, sources=["A"]),
        KeyLevel(price=20000.5, label="B", level_type="resistance",
                 distance_atr=0.55, sources=["B"]),  # diff=0.5, atr*0.10=1.0 -> cluster
    ]
    result = _cluster_levels(levels, atr=10.0, close=19990.0)
    assert len(result) == 1
    assert result[0].confluence_count == 2
    assert "A" in result[0].sources
    assert "B" in result[0].sources


# ============================================================
# _extract_market_structure
# ============================================================

def test_extract_market_structure_open_drive_up():
    """open_type=1 -> open_drive=True."""
    bar = {"open_type": 1}
    ms = _extract_market_structure(bar)
    assert ms.open_drive is True


def test_extract_market_structure_open_drive_down():
    bar = {"open_type": 2}
    ms = _extract_market_structure(bar)
    assert ms.open_drive is True


def test_extract_market_structure_no_open_drive():
    bar = {"open_type": 3}  # OTD, pas OD
    ms = _extract_market_structure(bar)
    assert ms.open_drive is False


def test_extract_market_structure_day_type_mapping():
    bar = {"day_type": 4}
    ms = _extract_market_structure(bar)
    assert ms.day_type == "Trend"


def test_extract_market_structure_unknown_day_type():
    bar = {"day_type": 99}
    ms = _extract_market_structure(bar)
    assert ms.day_type == "UNKNOWN"


def test_extract_market_structure_range_pos_va_pct_scale_pct():
    """range_pos_va > 1.5 -> echelle % donc / 100."""
    bar = {"range_pos_va": 50.0}
    ms = _extract_market_structure(bar)
    assert ms.range_pos_va_pct == 0.5


def test_extract_market_structure_range_pos_va_pct_scale_ratio():
    """range_pos_va <= 1.5 -> echelle ratio [0,1]."""
    bar = {"range_pos_va": 0.5}
    ms = _extract_market_structure(bar)
    assert ms.range_pos_va_pct == 0.5


def test_extract_market_structure_ib_broken_down_or_dn():
    """Tolere ib_broken_down OU ib_broken_dn."""
    bar = {"ib_broken_dn": 1}
    ms = _extract_market_structure(bar)
    assert ms.ib_broken_down is True


def test_extract_market_structure_open_type_is_int_contract():
    """R2 review batch 3b P2 : open_type stocke int (vs Optional[str] CORE)."""
    bar = {"open_type": 1}
    ms = _extract_market_structure(bar)
    assert ms.open_type == 1
    assert isinstance(ms.open_type, int)


# ============================================================
# _extract_order_flow
# ============================================================

def test_extract_order_flow_bn_bull_strength_count():
    """bn_bull_strength = count compteurs (anti-PATTERN_11)."""
    bar = {
        "bn_color_up": 1,
        "bn_long_up": 1,
        "bn_absorb_bid": 1,
        "bn_pressure_bid": 5.0,
        "bn_pressure_ask": 1.0,
    }
    of = _extract_order_flow(bar)
    assert of.bn_bull_strength == 4  # tous les 4 counts True


def test_extract_order_flow_bn_bear_strength_count():
    bar = {
        "bn_color_dn": 1,
        "bn_long_dn": 1,
        "bn_absorb_ask": 1,
        "bn_pressure_ask": 5.0,
        "bn_pressure_bid": 1.0,
    }
    of = _extract_order_flow(bar)
    assert of.bn_bear_strength == 4


def test_extract_order_flow_bn_signals_active_with_strength():
    bar = {"bn_color_up": 1}
    of = _extract_order_flow(bar)
    assert of.bn_signals_active is True


def test_extract_order_flow_bn_signals_active_with_score():
    """bn_score_raw != 0 -> active meme sans strength."""
    bar = {"bn_score_raw": 0.5}
    of = _extract_order_flow(bar)
    assert of.bn_signals_active is True


def test_extract_order_flow_macro_bias_bull():
    bar = {"cvd_day": 2000}  # > threshold 1000
    of = _extract_order_flow(bar)
    assert of.macro_bias == "BULL"


def test_extract_order_flow_macro_bias_bear():
    bar = {"cvd_day": -2000}
    of = _extract_order_flow(bar)
    assert of.macro_bias == "BEAR"


def test_extract_order_flow_macro_bias_neutral_under_threshold():
    bar = {"cvd_day": 500}  # < 1000
    of = _extract_order_flow(bar)
    assert of.macro_bias == "NEUTRAL"


# ============================================================
# _extract_session
# ============================================================

def test_extract_session_full():
    bar = {
        "session_segment": "us_cash",
        "is_in_london": False,
        "is_in_us_cash": True,
        "judas_swing_active": True,
        "judas_swing_direction": 1,
        "mins_et": 600,
    }
    s = _extract_session(bar)
    assert s.current_segment == "us_cash"
    assert s.is_in_us_cash is True
    assert s.judas_swing_active is True
    assert s.judas_swing_direction == 1
    assert s.mins_et == 600


def test_extract_session_defaults_when_missing():
    s = _extract_session({})
    assert s.current_segment == "unknown"
    assert s.is_in_london is False
    assert s.london_open is None


# ============================================================
# _extract_patterns
# ============================================================

def test_extract_patterns_single_prints_above():
    bar = {
        "has_single_prints": True,
        "single_print_above": True,
        "single_print_below": False,
    }
    p = _extract_patterns(bar)
    assert p.single_prints_present is True
    assert p.single_print_position == "above"


def test_extract_patterns_single_prints_below():
    bar = {
        "has_single_prints": True,
        "single_print_above": False,
        "single_print_below": True,
    }
    p = _extract_patterns(bar)
    assert p.single_print_position == "below"


def test_extract_patterns_no_single_prints():
    bar = {"has_single_prints": False}
    p = _extract_patterns(bar)
    assert p.single_prints_present is False
    assert p.single_print_position is None


def test_extract_patterns_fvg_counts():
    bar = {"fvg_up_active": 3, "fvg_dn_active": 1}
    p = _extract_patterns(bar)
    assert p.fvg_up_count == 3
    assert p.fvg_dn_count == 1


# ============================================================
# build_narrative_context — API publique
# ============================================================

def _make_minimal_bar(close: float = 20000.0, sym: str = "NQ") -> dict:
    """Bar minimal valide pour build_narrative_context."""
    return {
        "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
        "sym": sym,
        "close": close,
        "atr_14m": 40.0,  # ticks
        "vix_level": 20.0,
        "low": close - 10,
        "high": close + 10,
    }


def test_build_narrative_raises_on_none():
    """Anti VALIDATION_MISS : bar=None -> ValueError explicit."""
    with pytest.raises(ValueError, match="empty or invalid"):
        build_narrative_context(None)  # type: ignore


def test_build_narrative_raises_on_empty():
    with pytest.raises(ValueError):
        build_narrative_context({})


def test_build_narrative_raises_on_non_dict():
    with pytest.raises(ValueError):
        build_narrative_context("not a dict")  # type: ignore


def test_build_narrative_minimal_bar():
    bar = _make_minimal_bar()
    ctx = build_narrative_context(bar)
    assert isinstance(ctx, NarrativeContext)
    assert ctx.symbol == "NQ"
    assert ctx.close == 20000.0
    assert ctx.atr > 0
    assert ctx.atr_14m == 40.0  # ticks bruts
    assert ctx.macro_regime == "elevated"  # vix=20


def test_build_narrative_atr_unit_conversion():
    """ATR intraday = ticks * tick_size -> POINTS (fix Plan C 27/05)."""
    bar = _make_minimal_bar()
    bar["atr_14m"] = 40.0  # ticks
    ctx = build_narrative_context(bar)
    # NQ tick=0.25 -> atr_points = 40 * 0.25 = 10.0
    assert ctx.atr == 10.0
    assert ctx.atr_14m == 40.0  # ticks raw


def test_build_narrative_resistance_levels():
    bar = _make_minimal_bar(close=20000.0)
    bar["pdh"] = 20050.0
    bar["cash_high"] = 20060.0
    ctx = build_narrative_context(bar)
    assert len(ctx.key_levels_resistance) >= 2
    labels = [level.label for level in ctx.key_levels_resistance]
    # PDH ou Cash high doit etre present
    has_pdh_or_cash = any("PDH" in l or "Cash high" in l for l in labels)
    assert has_pdh_or_cash


def test_build_narrative_support_levels():
    bar = _make_minimal_bar(close=20000.0)
    bar["pdl"] = 19950.0
    bar["cash_low"] = 19940.0
    ctx = build_narrative_context(bar)
    assert len(ctx.key_levels_support) >= 2


def test_build_narrative_swing_reconstruction():
    """swing_low + swing_high reconstruction depuis dist_*."""
    bar = _make_minimal_bar(close=20000.0)
    bar["dist_swing_low"] = -50.0
    bar["dist_swing_high"] = 100.0
    ctx = build_narrative_context(bar)
    assert ctx.swing_low == 19950.0
    assert ctx.swing_high == 20100.0


def test_build_narrative_timestamp_iso():
    bar = _make_minimal_bar()
    ctx = build_narrative_context(bar)
    # ISO format timestamp avec timezone
    assert "T" in ctx.timestamp_utc
    assert "+00:00" in ctx.timestamp_utc or "Z" in ctx.timestamp_utc


def test_build_narrative_timestamp_invalid_fallback():
    """ts invalide -> 'unknown' (pas raise)."""
    bar = _make_minimal_bar()
    bar["ts"] = "invalid"
    ctx = build_narrative_context(bar)
    assert ctx.timestamp_utc == "unknown"


def test_build_narrative_default_symbol():
    """sym absent -> default NQ pour tick + symbol record."""
    bar = _make_minimal_bar()
    bar.pop("sym")
    ctx = build_narrative_context(bar)
    # symbol default UNKNOWN dans NarrativeContext mais tick utilise NQ
    assert ctx.symbol == "UNKNOWN"


def test_build_narrative_vwap_bands_pass_through():
    bar = _make_minimal_bar()
    bar["vwap_d"] = 19990.0
    bar["vwap_d_sd2u"] = 20050.0
    bar["vwap_d_sd2d"] = 19930.0
    ctx = build_narrative_context(bar)
    assert ctx.vwap_d == 19990.0
    assert ctx.vwap_d_sd2u == 20050.0
    assert ctx.vwap_d_sd2d == 19930.0


def test_build_narrative_full_e2e():
    """E2E avec bar complet : market_structure, order_flow, session, patterns tous OK."""
    bar = _make_minimal_bar()
    bar.update({
        "day_type": 4,
        "profile_shape": 1,
        "open_type": 1,
        "ib_complete": True,
        "ib_broken_up": True,
        "delta_day": 1500,
        "cvd_day": 2500,
        "bn_color_up": 1,
        "bn_long_up": 1,
        "is_in_us_cash": True,
        "session_segment": "us_cash",
        "fvg_up_active": 2,
        "has_single_prints": True,
        "single_print_above": True,
    })
    ctx = build_narrative_context(bar)
    assert ctx.market_structure.day_type == "Trend"
    assert ctx.market_structure.profile_shape == "P"
    assert ctx.market_structure.open_drive is True
    assert ctx.market_structure.ib_complete is True
    assert ctx.order_flow.macro_bias == "BULL"
    assert ctx.order_flow.bn_bull_strength >= 2
    assert ctx.session.is_in_us_cash is True
    assert ctx.session.current_segment == "us_cash"
    assert ctx.patterns.fvg_up_count == 2
    assert ctx.patterns.single_prints_present is True
    assert ctx.patterns.single_print_position == "above"
