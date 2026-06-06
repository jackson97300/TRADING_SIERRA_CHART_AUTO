# SIM4/research/backtest_helpers.py
"""Helpers for SIM4 Phase A backtests : I/O JSONL + stats."""

import json
import math
from pathlib import Path
from typing import Any


def load_day_bars(path: Path) -> list[dict[str, Any]]:
    """Load all bars from a single live_enriched JSONL file.

    Skips lines that fail JSON parsing. Returns [] if file missing.
    Bars returned in file order (chronological).
    """
    if not path.exists():
        return []
    bars: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                bars.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return bars
