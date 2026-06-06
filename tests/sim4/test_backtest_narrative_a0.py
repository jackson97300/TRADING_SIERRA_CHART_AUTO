# tests/sim4/test_backtest_narrative_a0.py
"""Tests for Phase A.0 runner."""

import json
from pathlib import Path

from SIM4.research.backtest_narrative_a0 import run_phase_a0, PhaseA0Result


def _write_day(directory: Path, day: str, symbol: str, bars: list[dict]) -> Path:
    fp = directory / f"{day}_{symbol}.jsonl"
    fp.write_text("\n".join(json.dumps(b) for b in bars), encoding="utf-8")
    return fp


def test_run_phase_a0_returns_phase_a0_result(tmp_path: Path):
    # Create 3 days of TREND_DAY_UP triggers
    for d in ["20260101", "20260102", "20260103"]:
        bars = [
            {
                "open": 30000.0, "high": 30010.0, "low": 29995.0,
                "close": 30000.0 + i * 0.5,
                "open_type": 1, "profile_shape": 1, "cvd_session": 300.0 + i * 10,
            }
            for i in range(60)
        ]
        _write_day(tmp_path, d, "NQ", bars)

    result = run_phase_a0(tmp_path, symbol="NQ")

    assert isinstance(result, PhaseA0Result)
    assert result.n_days_total == 3
    assert result.n_days_classified > 0
    assert "TREND_DAY_UP" in result.per_narrative_stats


def test_run_phase_a0_empty_dir(tmp_path: Path):
    result = run_phase_a0(tmp_path, symbol="NQ")
    assert result.n_days_total == 0
    assert result.per_narrative_stats == {}


from SIM4.research.backtest_narrative_a0 import (
    format_verdict,
    SHARPE_GO_THRESHOLD,
    NarrativeStats,
)


def test_format_verdict_marks_go_when_sharpe_above_threshold():
    stats = NarrativeStats(
        n_days=50,
        pnl_long_total=100.0,
        returns_long=[2.0, 3.0, -1.0, 2.5, 1.0],
        sharpe_long=1.5,
    )
    result = PhaseA0Result(symbol="NQ", n_days_total=100, n_days_classified=80)
    result.per_narrative_stats["TREND_DAY_UP"] = stats

    report = format_verdict(result)

    assert "TREND_DAY_UP" in report
    assert "GO" in report
    assert "1.5" in report or "1.50" in report


def test_format_verdict_marks_nogo_when_sharpe_below_threshold():
    stats = NarrativeStats(
        n_days=50,
        sharpe_long=0.5,
    )
    result = PhaseA0Result(symbol="NQ", n_days_total=100, n_days_classified=80)
    result.per_narrative_stats["TREND_DAY_UP"] = stats

    report = format_verdict(result)
    assert "NOGO" in report


def test_format_verdict_threshold_constant_is_one():
    assert SHARPE_GO_THRESHOLD == 1.0
