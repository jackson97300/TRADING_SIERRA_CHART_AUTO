# tests/sim4/test_fixtures.py
"""Smoke tests for fixtures themselves."""

from tests.sim4.fixtures import make_bar, make_day_bars


def test_make_bar_returns_dict_with_required_fields():
    bar = make_bar()
    assert isinstance(bar, dict)
    assert bar["open"] == 30000.0
    assert bar["close"] == 30005.0
    assert "day_type" in bar
    assert "profile_shape" in bar


def test_make_bar_overrides_work():
    bar = make_bar(open=30100.0, day_type=2)
    assert bar["open"] == 30100.0
    assert bar["day_type"] == 2
    assert bar["close"] == 30005.0  # unchanged


def test_make_day_bars_returns_n_bars():
    bars = make_day_bars(n=10)
    assert len(bars) == 10
    assert all(isinstance(b, dict) for b in bars)
    assert bars[0]["ts"] < bars[-1]["ts"]
