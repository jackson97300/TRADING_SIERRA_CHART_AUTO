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
from pathlib import Path
from typing import Optional, Set

from bot_config import BotConfig, InstrumentConfig
from order_manager import OrderManager, Position
from trade_journal import TradeJournal, TradeRecord

# Systeme logs V2 (22/04/2026)
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("position_monitor", process="bot_legacy")
except Exception:
    _v2log = None


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
        # V2 anti-spam guards : check_exit appele chaque bar → re-emit sans guard.
        # Reset via _clear_exit_guards() quand position fermee.
        self._time_exit_logged: Set[str] = set()
        self._eod_exit_logged: Set[str] = set()

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
            # V2 log : POSITION_EXPIRED (anti-spam guard par symbol)
            if _v2log and symbol not in self._time_exit_logged:
                # kwargs `bars` = conversion minutes→barres (timeframe 1min = 1 bar/min)
                _v2log.emit("POSITION_EXPIRED", bars=int(elapsed / 60))
                self._time_exit_logged.add(symbol)
            return ExitDecision(True, f"TIME ({int(elapsed/60)}min)")

        # ── 4. EOD Flatten ──
        if self.risk_mgr and self.risk_mgr.should_flatten_eod():
            # V2 log : SESSION_FLATTEN_WINDOW (anti-spam guard par symbol)
            if _v2log and symbol not in self._eod_exit_logged:
                _v2log.emit("SESSION_FLATTEN_WINDOW")
                self._eod_exit_logged.add(symbol)
            return ExitDecision(True, "EOD")

        return ExitDecision()

    def process_exit(self, symbol: str, current_price: float,
                      exit_reason: str, instrument: InstrumentConfig):
        """Execute la sortie et log dans le journal."""
        pos = self.orders.get_position(symbol)
        if pos is None:
            # V2 log : race condition (check_exit detecte TIME/EOD, position fermee
            # broker entre-temps par SL — silencieux sans ce log, debug impossible)
            if _v2log:
                _v2log.emit("GENERIC_ALERTE",
                            msg=f"process_exit sur position deja fermee : {symbol} reason={exit_reason}")
            # Reset guards pour cette position (disparue)
            self._time_exit_logged.discard(symbol)
            self._eod_exit_logged.discard(symbol)
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

        # Reset V2 anti-spam guards (position fermee, prochain trade demarre propre)
        self._time_exit_logged.discard(symbol)
        self._eod_exit_logged.discard(symbol)

        return trade
