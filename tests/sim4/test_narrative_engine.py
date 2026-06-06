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
