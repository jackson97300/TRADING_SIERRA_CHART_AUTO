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


# Annualization assumes daily returns. For backtests on N days,
# we want a comparable Sharpe across narratives, so use a common factor.
TRADING_DAYS_PER_YEAR = 252


def sharpe_ratio(returns: list[float]) -> float:
    """Annualized Sharpe ratio assuming daily returns and zero risk-free rate.

    Returns 0.0 for empty, single-value, or zero-variance input.
    Annualization factor: sqrt(252).
    """
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0.0:
        return 0.0
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)
