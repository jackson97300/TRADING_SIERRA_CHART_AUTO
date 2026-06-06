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


def day_pnl_long(bars: list[dict[str, Any]]) -> float:
    """Theoretical PnL of buying close[0] and selling close[-1].

    Returns 0.0 for empty list or single bar.
    Points (not USD).
    """
    if len(bars) < 2:
        return 0.0
    first = bars[0].get("close")
    last = bars[-1].get("close")
    if first is None or last is None:
        return 0.0
    return float(last) - float(first)


def day_pnl_short(bars: list[dict[str, Any]]) -> float:
    """Theoretical PnL of shorting close[0] and covering close[-1].

    Returns -day_pnl_long(bars).
    """
    return -day_pnl_long(bars)


def list_enriched_days(directory: Path, symbol: str) -> list[Path]:
    """Return sorted list of JSONL files matching `YYYYMMDD_<symbol>.jsonl`.

    Files are sorted chronologically by filename.
    """
    if not directory.exists():
        return []
    suffix = f"_{symbol}.jsonl"
    files = [p for p in directory.iterdir() if p.is_file() and p.name.endswith(suffix)]
    return sorted(files, key=lambda p: p.name)


from SIM4.research.narrative_engine_v1 import classify_day_first_hour


def backtest_one_day(path: Path) -> tuple[str, float, float]:
    """For one day file, return (narrative_label, pnl_long, pnl_short).

    PnL is in price points (not USD). Long = buy first close, sell last close.
    Short = inverse.
    """
    bars = load_day_bars(path)
    if not bars:
        return ("NONE", 0.0, 0.0)
    label, _ = classify_day_first_hour(bars)
    pnl_long = day_pnl_long(bars)
    pnl_short = day_pnl_short(bars)
    return (label, pnl_long, pnl_short)
