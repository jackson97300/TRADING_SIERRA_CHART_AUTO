# SIM4/research/backtest_narrative_a0.py
"""Phase A.0 backtest runner : classify days + compute Sharpe per narrative.

Output : PhaseA0Result with per-narrative stats.
Critere GO : Sharpe par narrative > 1.0 (cf design doc section 2sexies Phase A.0).
"""

from dataclasses import dataclass, field
from pathlib import Path

from SIM4.research.backtest_helpers import (
    backtest_one_day,
    list_enriched_days,
    sharpe_ratio,
)


@dataclass
class NarrativeStats:
    """Aggregated stats for one narrative label."""

    n_days: int = 0
    pnl_long_total: float = 0.0
    pnl_short_total: float = 0.0
    returns_long: list[float] = field(default_factory=list)
    returns_short: list[float] = field(default_factory=list)
    sharpe_long: float = 0.0
    sharpe_short: float = 0.0


@dataclass
class PhaseA0Result:
    """Result of Phase A.0 backtest for one symbol."""

    symbol: str
    n_days_total: int
    n_days_classified: int
    per_narrative_stats: dict[str, NarrativeStats] = field(default_factory=dict)


def run_phase_a0(directory: Path, symbol: str) -> PhaseA0Result:
    """Iterate over all enriched days, classify, aggregate per narrative.

    Returns PhaseA0Result with sharpe_long / sharpe_short per narrative.
    """
    days = list_enriched_days(directory, symbol)
    result = PhaseA0Result(symbol=symbol, n_days_total=len(days), n_days_classified=0)

    for day_path in days:
        label, pnl_long, pnl_short = backtest_one_day(day_path)
        if label == "NONE":
            continue
        result.n_days_classified += 1
        stats = result.per_narrative_stats.setdefault(label, NarrativeStats())
        stats.n_days += 1
        stats.pnl_long_total += pnl_long
        stats.pnl_short_total += pnl_short
        stats.returns_long.append(pnl_long)
        stats.returns_short.append(pnl_short)

    # Compute Sharpe per narrative
    for stats in result.per_narrative_stats.values():
        stats.sharpe_long = sharpe_ratio(stats.returns_long)
        stats.sharpe_short = sharpe_ratio(stats.returns_short)

    return result
