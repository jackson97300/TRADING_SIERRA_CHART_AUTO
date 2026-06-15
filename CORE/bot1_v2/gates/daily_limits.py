"""Daily limits gate Bot 1 v2 - Mark Douglas wrapper.

Wrapper minimaliste autour de CORE/daily_limits_guard.py existant.
"""
from __future__ import annotations

from dataclasses import dataclass

from CORE.bot1_v2.config import Bot1V2Config


@dataclass(frozen=True)
class DailyState:
    """Etat journalier (compteurs)."""
    n_trades_today: int = 0
    cumul_pnl_usd: float = 0.0
    date_str: str = ""


@dataclass(frozen=True)
class DailyVerdict:
    """Verdict du gate journalier."""
    allowed: bool
    skip_reason: str = ""
    n_trades_remaining: int = 0


class DailyLimitsGate:
    """Gate qui plafonne trades/jour + stop loss/win quotidien.

    Mark Douglas : "Consistency over intensity".
    - Max 5 trades/jour (defaut)
    - Stop loss quotidien : -$200 -> bot bloque
    - Stop win quotidien : +$150 -> lock-in profits
    """

    def __init__(self, cfg: Bot1V2Config):
        self.cfg = cfg
        self.state = DailyState()

    def reset_for_new_day(self, date_str: str) -> None:
        self.state = DailyState(date_str=date_str)

    def update_after_trade(self, pnl_usd: float) -> None:
        self.state = DailyState(
            n_trades_today=self.state.n_trades_today + 1,
            cumul_pnl_usd=self.state.cumul_pnl_usd + pnl_usd,
            date_str=self.state.date_str,
        )

    def check_allow_entry(self) -> DailyVerdict:
        s = self.state
        # Max trades/jour
        if s.n_trades_today >= self.cfg.MAX_TRADES_PER_DAY:
            return DailyVerdict(
                allowed=False,
                skip_reason=f"DAILY_MAX_TRADES:{s.n_trades_today}/{self.cfg.MAX_TRADES_PER_DAY}",
            )
        # Stop loss quotidien
        if s.cumul_pnl_usd <= self.cfg.DAILY_STOP_LOSS_USD:
            return DailyVerdict(
                allowed=False,
                skip_reason=f"DAILY_STOP_LOSS:${s.cumul_pnl_usd:.2f}<=${self.cfg.DAILY_STOP_LOSS_USD:.2f}",
            )
        # Stop win quotidien (lock-in profits)
        if s.cumul_pnl_usd >= self.cfg.DAILY_STOP_WIN_USD:
            return DailyVerdict(
                allowed=False,
                skip_reason=f"DAILY_STOP_WIN:${s.cumul_pnl_usd:.2f}>=${self.cfg.DAILY_STOP_WIN_USD:.2f}",
            )
        return DailyVerdict(
            allowed=True,
            n_trades_remaining=self.cfg.MAX_TRADES_PER_DAY - s.n_trades_today,
        )
