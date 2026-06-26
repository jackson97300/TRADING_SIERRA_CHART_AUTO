"""Tests tools/bot4v2_replay_metrics.py - validation pipeline cross-day."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).parent.parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from bot4v2_replay_metrics import (  # noqa: E402
    aggregate_metrics,
    date_range,
    main,
    replay_one_day,
)


# ============================================================
# date_range (reuse logic)
# ============================================================


def test_date_range_basic():
    dates = date_range("20260620", "20260622")
    assert dates == ["20260620", "20260621", "20260622"]


def test_date_range_single_day():
    assert date_range("20260626", "20260626") == ["20260626"]


def test_date_range_reversed_returns_empty():
    assert date_range("20260626", "20260620") == []


# ============================================================
# replay_one_day
# ============================================================


def test_replay_one_day_missing_file(tmp_path):
    """Fichier absent -> exists=False, bars=0, pas crash."""
    result = replay_one_day(tmp_path / "missing.jsonl", "NQ")
    assert result["exists"] is False
    assert result["bars_processed"] == 0
    assert result["crashed"] is False


def test_replay_one_day_sample_file(tmp_path):
    """Sample JSONL crafted -> replay OK + metrics."""
    sample = tmp_path / "20260626_NQ_sierra_enriched.jsonl"
    sample.write_text(
        '{"sym": "NQ", "ts_event": "2026-06-26T14:00:00+00:00", '
        '"high": 20010, "low": 19995, "close": 20000, '
        '"atr": 10, "atr_14m": 40, "vix_level": 18}\n'
        '{"sym": "NQ", "ts_event": "2026-06-26T14:01:00+00:00", '
        '"high": 20012, "low": 19998, "close": 20005, '
        '"atr": 10, "atr_14m": 40, "vix_level": 18}\n',
        encoding="utf-8",
    )
    result = replay_one_day(sample, "NQ")
    assert result["exists"] is True
    assert result["crashed"] is False
    assert result["bars_processed"] == 2


def test_replay_one_day_with_crafted_sweep_setup(tmp_path):
    """Sweep_Reclaim_N1 setup -> instance creee."""
    import json as _json
    sample = tmp_path / "crafted.jsonl"
    bars = [
        {"sym": "NQ", "ts_event": f"2026-06-26T14:0{i}:00+00:00",
         "high": 20020.0, "low": 19990.0, "close": 19998.0,
         "atr": 10.0, "atr_14m": 40.0,
         "vix_level": 18.0, "vwap_d": 20000.0,
         "delta_bar": -200.0,
         "sweep_high_lag1": 1}
        for i in range(3)
    ]
    sample.write_text(
        "\n".join(_json.dumps(b) for b in bars) + "\n",
        encoding="utf-8",
    )
    result = replay_one_day(sample, "NQ")
    assert result["exists"] is True
    assert result["crashed"] is False
    assert result["bars_processed"] == 3
    # Setup garanti = au moins 1 instance ou dispatch
    has_signal = (
        result.get("tracker_total_instances", 0) > 0
        or result.get("total_dispatches", 0) > 0
    )
    assert has_signal, f"Setup crafted devrait produire signal : {result}"


# ============================================================
# aggregate_metrics
# ============================================================


def test_aggregate_empty():
    agg = aggregate_metrics([])
    assert agg["n_days"] == 0
    assert agg["status"] == "RESERVE"
    assert "Aucun fire" in agg["status_reason"]


def test_aggregate_no_fires_returns_reserve():
    per_day = [
        {"exists": True, "bars_processed": 100, "crashed": False,
         "total_dispatches": 0, "tracker_total_instances": 0,
         "dispatch_map_size": 0},
    ]
    agg = aggregate_metrics(per_day)
    assert agg["status"] == "RESERVE"
    assert agg["has_fire"] is False


def test_aggregate_with_fires_returns_go():
    per_day = [
        {"exists": True, "bars_processed": 100, "crashed": False,
         "total_dispatches": 5, "tracker_total_instances": 3,
         "dispatch_map_size": 5},
    ]
    agg = aggregate_metrics(per_day)
    assert agg["status"] == "GO"
    assert agg["has_fire"] is True


def test_aggregate_with_crash_returns_reserve():
    per_day = [
        {"exists": True, "bars_processed": 50, "crashed": True,
         "total_dispatches": 5},
    ]
    agg = aggregate_metrics(per_day)
    assert agg["status"] == "RESERVE"
    assert agg["n_crashed"] == 1


# ============================================================
# main() CLI
# ============================================================


def test_main_json_output(tmp_path, capsys):
    """JSON output parseable."""
    data_dir = tmp_path / "data" / "NQ"
    data_dir.mkdir(parents=True)
    sample = data_dir / "20260626_NQ_sierra_enriched.jsonl"
    sample.write_text(
        '{"sym": "NQ", "ts_event": "2026-06-26T14:00:00+00:00", '
        '"high": 20010, "low": 19995, "close": 20000, "atr": 10, "atr_14m": 40}\n',
        encoding="utf-8",
    )
    rc = main([
        "--symbol", "NQ",
        "--since", "20260626", "--until", "20260626",
        "--data-dir", str(tmp_path / "data"),
        "--json",
    ])
    # Exit code 1 car no fire (sample minimal)
    assert rc in (0, 1)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "per_day" in data
    assert "aggregate" in data


def test_main_invalid_date_range_returns_2(capsys):
    rc = main([
        "--symbol", "NQ",
        "--since", "20260626", "--until", "20260620",
        "--data-dir", "DATA/live_enriched/sierra",
    ])
    assert rc == 2
