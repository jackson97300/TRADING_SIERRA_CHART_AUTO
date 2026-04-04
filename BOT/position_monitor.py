"""
position_monitor.py — Monitoring des positions MIA V2
=======================================================

Surveille TP/SL hit, time-based exit, EOD flatten.
Phase 1 : TP/SL fixe. Phase 2 : trailing stop.

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import time
from dataclasses import dataclass
from typing import Optional

from bot_config import BotConfig, InstrumentConfig
from order_manager import OrderManager, Position
from trade_journal import TradeJournal, TradeRecord


@dataclass
class ExitDecision:
    """Decision de sortie."""
    should_exit: bool = False
    reason: str = ""            # TP / SL / TIME / EOD / TRAIL


class PositionMonitor:
    """Surveille les positions et decide des sorties."""

    def __init__(self, config: BotConfig, order_mgr: OrderManager,
                 journal: TradeJournal, risk_manager=None):
        self.cfg = config
        self.orders = order_mgr
        self.journal = journal
        self.risk_mgr = risk_manager

    def check_exit(self, symbol: str, current_price: float,
                    instrument: InstrumentConfig) -> ExitDecision:
        """
        Verifie si une position doit etre fermee.

        Checks dans l'ordre :
        1. SL hit
        2. TP hit
        3. Time exit (stagnant > 90 min)
        4. EOD flatten (15:55 ET)

        Returns:
            ExitDecision
        """
        pos = self.orders.get_position(symbol)
        if pos is None:
            return ExitDecision()

        ts = instrument.tick_size

        # ── 1. Stop Loss ──
        if pos.sl_price > 0:
            if pos.direction == 1 and current_price <= pos.sl_price:
                return ExitDecision(True, "SL")
            if pos.direction == -1 and current_price >= pos.sl_price:
                return ExitDecision(True, "SL")

        # ── 2. Take Profit ──
        if pos.tp_price > 0:
            if pos.direction == 1 and current_price >= pos.tp_price:
                return ExitDecision(True, "TP")
            if pos.direction == -1 and current_price <= pos.tp_price:
                return ExitDecision(True, "TP")

        # ── 3. Time-based exit ──
        elapsed = time.time() - pos.entry_time
        max_duration = self.cfg.session.time_exit_minutes * 60
        if elapsed > max_duration:
            return ExitDecision(True, f"TIME ({int(elapsed/60)}min)")

        # ── 4. EOD Flatten ──
        if self.risk_mgr and self.risk_mgr.should_flatten_eod():
            return ExitDecision(True, "EOD")

        return ExitDecision()

    def process_exit(self, symbol: str, current_price: float,
                      exit_reason: str, instrument: InstrumentConfig):
        """Execute la sortie et log dans le journal."""
        pos = self.orders.get_position(symbol)
        if pos is None:
            return

        # Fermer la position
        self.orders.close_position(symbol, exit_reason)

        # Calculer le P&L
        ts = instrument.tick_size
        tv = instrument.tick_value
        pnl_ticks = (current_price - pos.entry_price) / ts * pos.direction
        pnl_usd = pnl_ticks * tv * pos.quantity

        # Log dans le journal
        trade = TradeRecord(
            symbol=symbol,
            direction=pos.direction,
            entry_price=pos.entry_price,
            entry_time=time.strftime("%H:%M:%S", time.localtime(pos.entry_time)),
            exit_price=current_price,
            exit_time=time.strftime("%H:%M:%S"),
            exit_reason=exit_reason,
            sl_price=pos.sl_price,
            tp_price=pos.tp_price,
            position_size=pos.quantity,
            pnl_ticks=pnl_ticks,
            pnl_usd=pnl_usd,
            duration_seconds=time.time() - pos.entry_time,
            is_winner=pnl_usd > 0,
        )
        self.journal.log_trade(trade)

        # Retirer la position
        self.orders.remove_position(symbol)

        return trade
