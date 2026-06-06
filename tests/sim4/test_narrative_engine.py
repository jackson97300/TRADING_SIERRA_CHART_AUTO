# tests/sim4/test_narrative_engine.py
"""Tests for narrative classifiers."""

from SIM4.research.narrative_engine_v1 import classify_trend_day, NARRATIVE_NONE
from tests.sim4.fixtures import make_bar


def test_trend_day_up_when_all_triggers_aligned():
    # open_type=1 (OD), profile_shape=1 (P-shape), cvd_session>0 (buyers)
    bar = make_bar(open_type=1, profile_shape=1, cvd_session=500.0)
    label, confidence = classify_trend_day(bar)
    assert label == "TREND_DAY_UP"
    assert confidence >= 0.7


def test_trend_day_down_when_all_triggers_aligned():
    bar = make_bar(open_type=1, profile_shape=2, cvd_session=-500.0)
    label, confidence = classify_trend_day(bar)
    assert label == "TREND_DAY_DOWN"
    assert confidence >= 0.7


def test_trend_day_none_when_open_type_not_trigger():
    bar = make_bar(open_type=0, profile_shape=1, cvd_session=500.0)
    label, confidence = classify_trend_day(bar)
    assert label == NARRATIVE_NONE
    assert confidence == 0.0


def test_trend_day_none_when_profile_shape_not_trigger():
    bar = make_bar(open_type=1, profile_shape=0, cvd_session=500.0)
    label, confidence = classify_trend_day(bar)
    assert label == NARRATIVE_NONE


def test_trend_day_none_when_cvd_session_small():
    # cvd small = no clear direction
    bar = make_bar(open_type=1, profile_shape=1, cvd_session=50.0)
    label, confidence = classify_trend_day(bar)
    assert label == NARRATIVE_NONE


def test_trend_day_handles_missing_fields():
    bar = make_bar()
    del bar["cvd_session"]
    label, confidence = classify_trend_day(bar)
    assert label == NARRATIVE_NONE
    assert confidence == 0.0


from SIM4.research.narrative_engine_v1 import (
    classify_range_rejection,
    NARRATIVE_RANGE_REJECTION,
)


def test_range_rejection_when_all_triggers_aligned():
    bar = make_bar(profile_shape=0, inside_value_area=1, day_type=0, cvd_session=50.0)
    label, confidence = classify_range_rejection(bar)
    assert label == NARRATIVE_RANGE_REJECTION
    assert confidence >= 0.6


def test_range_rejection_works_for_b_shape():
    bar = make_bar(profile_shape=3, inside_value_area=1, day_type=0, cvd_session=50.0)
    label, _ = classify_range_rejection(bar)
    assert label == NARRATIVE_RANGE_REJECTION


def test_range_rejection_none_when_outside_va():
    bar = make_bar(profile_shape=0, inside_value_area=0, day_type=0, cvd_session=50.0)
    label, confidence = classify_range_rejection(bar)
    assert label == NARRATIVE_NONE
    assert confidence == 0.0


def test_range_rejection_none_when_day_type_trend():
    bar = make_bar(profile_shape=0, inside_value_area=1, day_type=2, cvd_session=50.0)
    label, _ = classify_range_rejection(bar)
    assert label == NARRATIVE_NONE


def test_range_rejection_none_when_cvd_large():
    # cvd > threshold = clear direction = not a range
    bar = make_bar(profile_shape=0, inside_value_area=1, day_type=0, cvd_session=500.0)
    label, _ = classify_range_rejection(bar)
    assert label == NARRATIVE_NONE


def test_range_rejection_handles_missing_fields():
    bar = make_bar(profile_shape=0)
    del bar["inside_value_area"]
    label, _ = classify_range_rejection(bar)
    assert label == NARRATIVE_NONE


from SIM4.research.narrative_engine_v1 import (
    classify_failed_breakout_reversal,
    NARRATIVE_FAILED_BREAKOUT_REVERSAL,
    FBR_PDH_PDL_PROXIMITY_TICKS,
)


def test_fbr_reversal_short_after_failed_break_pdh():
    # close just above cur_pdh, failed_auction, delta_div_sell_clean
    bar = make_bar(
        close=30100.5,
        cur_pdh=30100.0,
        cur_pdl=29900.0,
        ctx_failed_auction=1,
        delta_div_sell_clean=1,
        delta_div_buy_clean=0,
    )
    label, confidence = classify_failed_breakout_reversal(bar)
    assert label == "FAILED_BREAKOUT_REVERSAL_SHORT"
    assert confidence >= 0.6


def test_fbr_reversal_long_after_failed_break_pdl():
    bar = make_bar(
        close=29899.5,
        cur_pdh=30100.0,
        cur_pdl=29900.0,
        ctx_failed_auction=1,
        delta_div_buy_clean=1,
        delta_div_sell_clean=0,
    )
    label, confidence = classify_failed_breakout_reversal(bar)
    assert label == "FAILED_BREAKOUT_REVERSAL_LONG"
    assert confidence >= 0.6


def test_fbr_none_when_no_failed_auction():
    bar = make_bar(
        close=30100.5,
        cur_pdh=30100.0,
        cur_pdl=29900.0,
        ctx_failed_auction=0,  # not failed
        delta_div_sell_clean=1,
    )
    label, _ = classify_failed_breakout_reversal(bar)
    assert label == NARRATIVE_NONE


def test_fbr_none_when_no_proximity_to_levels():
    # close well in the middle
    bar = make_bar(
        close=30000.0,
        cur_pdh=30100.0,
        cur_pdl=29900.0,
        ctx_failed_auction=1,
        delta_div_sell_clean=1,
    )
    label, _ = classify_failed_breakout_reversal(bar)
    assert label == NARRATIVE_NONE


def test_fbr_none_when_no_divergence():
    bar = make_bar(
        close=30100.5,
        cur_pdh=30100.0,
        cur_pdl=29900.0,
        ctx_failed_auction=1,
        delta_div_sell_clean=0,
        delta_div_buy_clean=0,
    )
    label, _ = classify_failed_breakout_reversal(bar)
    assert label == NARRATIVE_NONE


def test_fbr_handles_missing_pdh():
    bar = make_bar(close=30100.5, ctx_failed_auction=1, delta_div_sell_clean=1)
    del bar["cur_pdh"]
    label, _ = classify_failed_breakout_reversal(bar)
    assert label == NARRATIVE_NONE


def test_fbr_proximity_constant_is_in_ticks():
    # Sanity: this is a number > 0
    assert FBR_PDH_PDL_PROXIMITY_TICKS > 0


from SIM4.research.narrative_engine_v1 import classify_day_first_hour


def test_classify_day_first_hour_returns_trend_when_all_bars_say_trend():
    bars = [
        make_bar(open_type=1, profile_shape=1, cvd_session=300.0),
        make_bar(open_type=1, profile_shape=1, cvd_session=400.0),
        make_bar(open_type=1, profile_shape=1, cvd_session=500.0),
    ]
    label, confidence = classify_day_first_hour(bars)
    assert label == "TREND_DAY_UP"
    assert 0.0 < confidence <= 1.0


def test_classify_day_first_hour_returns_majority():
    bars = [
        make_bar(open_type=1, profile_shape=1, cvd_session=300.0),
        make_bar(open_type=1, profile_shape=1, cvd_session=300.0),
        make_bar(open_type=0, profile_shape=0, cvd_session=0.0),  # NONE
    ]
    label, _ = classify_day_first_hour(bars)
    assert label == "TREND_DAY_UP"


def test_classify_day_first_hour_returns_none_when_no_bars():
    label, confidence = classify_day_first_hour([])
    assert label == NARRATIVE_NONE
    assert confidence == 0.0


def test_classify_day_first_hour_returns_none_when_all_bars_none():
    # inside_value_area=0 prevents RANGE_REJECTION from triggering on the
    # default fixture (which has inside_value_area=1, day_type=0)
    bars = [
        make_bar(open_type=0, profile_shape=0, cvd_session=0.0, inside_value_area=0)
    ] * 3
    label, _ = classify_day_first_hour(bars)
    assert label == NARRATIVE_NONE


def test_classify_day_first_hour_takes_first_n_bars():
    # 60 mixed bars: first 30 say TREND_UP, next 30 say RANGE
    trend_bars = [make_bar(open_type=1, profile_shape=1, cvd_session=300.0)] * 30
    range_bars = [
        make_bar(profile_shape=0, inside_value_area=1, day_type=0, cvd_session=50.0)
    ] * 30
    bars = trend_bars + range_bars
    # Only look at first 30 -> TREND
    label, _ = classify_day_first_hour(bars, max_bars=30)
    assert label == "TREND_DAY_UP"
