# tests/sim4/test_backtest_helpers.py
"""Tests for backtest helpers (loaders, stats)."""

import json
from pathlib import Path

from SIM4.research.backtest_helpers import load_day_bars


def test_load_day_bars_returns_list_of_dicts(tmp_path: Path):
    fp = tmp_path / "20260115_NQ.jsonl"
    bars_in = [
        {"ts": 1, "close": 30000.0},
        {"ts": 2, "close": 30005.0},
        {"ts": 3, "close": 30010.0},
    ]
    fp.write_text("\n".join(json.dumps(b) for b in bars_in), encoding="utf-8")

    result = load_day_bars(fp)

    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0]["close"] == 30000.0
    assert result[2]["close"] == 30010.0


def test_load_day_bars_skips_invalid_lines(tmp_path: Path):
    fp = tmp_path / "bad.jsonl"
    fp.write_text('{"ts": 1, "close": 30000.0}\nINVALID LINE\n{"ts": 2, "close": 30005.0}\n', encoding="utf-8")

    result = load_day_bars(fp)
    assert len(result) == 2


def test_load_day_bars_returns_empty_when_file_missing(tmp_path: Path):
    fp = tmp_path / "does_not_exist.jsonl"
    assert load_day_bars(fp) == []


from SIM4.research.backtest_helpers import sharpe_ratio


def test_sharpe_ratio_positive_returns():
    returns = [0.01, 0.02, 0.015, 0.018, 0.012]
    s = sharpe_ratio(returns)
    assert s > 0
    assert isinstance(s, float)


def test_sharpe_ratio_zero_returns_returns_zero():
    assert sharpe_ratio([0.0, 0.0, 0.0]) == 0.0


def test_sharpe_ratio_empty_returns_zero():
    assert sharpe_ratio([]) == 0.0


def test_sharpe_ratio_single_value_returns_zero():
    assert sharpe_ratio([0.05]) == 0.0


def test_sharpe_ratio_negative_returns():
    returns = [-0.01, -0.02, -0.015, -0.018]
    s = sharpe_ratio(returns)
    assert s < 0
