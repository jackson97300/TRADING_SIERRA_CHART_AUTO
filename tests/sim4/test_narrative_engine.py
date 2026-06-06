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
