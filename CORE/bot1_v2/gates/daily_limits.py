"""Daily limits gate Bot 1 v2 - Mark Douglas wrapper.

Wrapper minimaliste autour de CORE/daily_limits_guard.py existant.
"""
from __future__ import annotations

import threading
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
        # FIX 18/06 review B2/B3 MAJEUR-1 : protege le read-modify-write de state
        # contre la race entre register_open (thread poll) et apply_pnl (thread
        # DTC recv_loop). Lock local au gate = inoffensif pour Bot 1 v2 / Bot 2
        # (non contendu chez eux : mutation thread DTC seul).
        self._lock = threading.Lock()

    def reset_for_new_day(self, date_str: str) -> None:
        with self._lock:
            self.state = DailyState(date_str=date_str)

    def update_after_trade(self, pnl_usd: float) -> None:
        with self._lock:
            self.state = DailyState(
                n_trades_today=self.state.n_trades_today + 1,
                cumul_pnl_usd=self.state.cumul_pnl_usd + pnl_usd,
                date_str=self.state.date_str,
            )

    # ── FIX 18/06 B2/B3 (INCIDENT_LOG #67) ──────────────────────────────────
    # update_after_trade compte le trade au CLOSE -> le plafond ne mord qu'apres
    # fermeture (un bot peut ouvrir N positions avant qu'aucune ne ferme). Les
    # methodes ci-dessous separent ouverture (compteur) et close (pnl), pour les
    # bots qui plafonnent a l'OUVERTURE (BN V4). NON utilisees par Bot 1 v2 ->
    # comportement legacy strictement preserve (close-based).

    def register_open(self) -> None:
        """Incremente n_trades_today a l'OUVERTURE (fix B2). A coupler avec
        apply_pnl (close), JAMAIS avec update_after_trade (double compte)."""
        with self._lock:
            self.state = DailyState(
                n_trades_today=self.state.n_trades_today + 1,
                cumul_pnl_usd=self.state.cumul_pnl_usd,
                date_str=self.state.date_str,
            )

    def apply_pnl(self, pnl_usd: float) -> None:
        """Ajoute le PnL au cumul SANS incrementer n_trades (le trade est deja
        compte a l'ouverture via register_open)."""
        with self._lock:
            self.state = DailyState(
                n_trades_today=self.state.n_trades_today,
                cumul_pnl_usd=self.state.cumul_pnl_usd + pnl_usd,
                date_str=self.state.date_str,
            )

    def snapshot(self) -> dict:
        """Etat serialisable pour persistance cross-restart (fix B3).
        Lit sous lock pour un snapshot coherent (n_trades + pnl atomiques)."""
        with self._lock:
            return {
                "n_trades_today": self.state.n_trades_today,
                "cumul_pnl_usd": self.state.cumul_pnl_usd,
                "date_str": self.state.date_str,
            }

    def restore(self, n_trades_today: int, cumul_pnl_usd: float,
                date_str: str) -> None:
        """Restaure l'etat depuis un snapshot persiste (fix B3)."""
        with self._lock:
            self.state = DailyState(
                n_trades_today=int(n_trades_today),
                cumul_pnl_usd=float(cumul_pnl_usd),
                date_str=str(date_str),
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
