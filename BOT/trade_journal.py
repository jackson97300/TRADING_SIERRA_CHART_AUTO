"""
trade_journal.py — Journal automatique des trades MIA V2
=========================================================

Log chaque trade avec : raison, score ML, entree, sortie, P&L, duree.
Sauvegarde en JSONL pour analyse post-mortem.

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class TradeRecord:
    """Un enregistrement de trade complet."""
    # Identifiant
    trade_id: str = ""
    symbol: str = ""
    date: str = ""

    # Signal
    direction: int = 0              # +1 = BUY, -1 = SELL
    ml_score: float = 0.0           # Score LightGBM
    signal_reason: str = ""         # Raison du signal

    # MenthorQ context
    gamma_condition: float = 0.0    # -1 / +1
    net_gex_m: float = 0.0
    iv_30d: float = 0.0

    # Entree
    entry_price: float = 0.0
    entry_time: str = ""
    entry_bar_index: int = 0

    # Sortie
    exit_price: float = 0.0
    exit_time: str = ""
    exit_reason: str = ""           # TP / SL / TIME / EOD / MANUAL / TRAIL

    # Risk
    sl_price: float = 0.0
    tp_price: float = 0.0
    position_size: int = 1          # Nombre de contrats
    risk_usd: float = 0.0           # Risque en $

    # Resultat
    pnl_ticks: float = 0.0
    pnl_usd: float = 0.0
    duration_seconds: float = 0.0
    is_winner: bool = False

    # Meta
    paper_trade: bool = True
    session_id: str = ""


class TradeJournal:
    """Journal de trades avec sauvegarde JSONL."""

    def __init__(self, journal_dir: str = "DATA/JOURNAL"):
        self.dir = Path(journal_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.trade_count = 0
        self.daily_pnl = 0.0
        self.daily_trades: list = []
        self.consecutive_losses = 0

    def _filepath(self) -> Path:
        date = datetime.now(timezone.utc).strftime("%Y%m%d")
        return self.dir / f"{date}_trades.jsonl"

    def log_trade(self, trade: TradeRecord):
        """Enregistre un trade dans le journal (thread-safe)."""
        with self._lock:
            trade.trade_id = f"{trade.symbol}_{trade.date}_{self.trade_count:03d}"
            self.trade_count += 1

        # Le PnL doit etre deja calcule par position_monitor.process_exit()
        # On ne recalcule PAS ici — eviter la duplication (audit architecture)
        if trade.pnl_usd == 0 and trade.direction != 0 and trade.entry_price > 0 and trade.exit_price > 0:
            # Fallback si le PnL n'a pas ete pre-calcule
            tick_size = 0.25
            tick_value = 1.25 if trade.symbol == "ES" else 0.50
            trade.pnl_ticks = (trade.exit_price - trade.entry_price) / tick_size * trade.direction
            trade.pnl_usd = trade.pnl_ticks * tick_value * trade.position_size
            trade.is_winner = trade.pnl_usd > 0

        # Update stats
        self.daily_pnl += trade.pnl_usd
        self.daily_trades.append(trade)

        if trade.is_winner:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1

        # Sauvegarder
        with open(self._filepath(), "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(trade), default=str) + "\n")

    def log_rejection(self, symbol: str, reason: str, ml_score: float = 0.0):
        """Log un signal rejeté (pour analyse)."""
        record = {
            "type": "rejection",
            "symbol": symbol,
            "reason": reason,
            "ml_score": ml_score,
            "time": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._filepath(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_event(self, event: str, details: str = ""):
        """Log un evenement systeme (kill switch, circuit breaker, etc.)."""
        record = {
            "type": "event",
            "event": event,
            "details": details,
            "time": datetime.now(timezone.utc).isoformat(),
            "daily_pnl": self.daily_pnl,
            "trade_count": self.trade_count,
        }
        with open(self._filepath(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    @property
    def win_rate(self) -> float:
        if not self.daily_trades:
            return 0.0
        winners = sum(1 for t in self.daily_trades if t.is_winner)
        return winners / len(self.daily_trades)

    @property
    def profit_factor(self) -> float:
        gains = sum(t.pnl_usd for t in self.daily_trades if t.pnl_usd > 0)
        losses = abs(sum(t.pnl_usd for t in self.daily_trades if t.pnl_usd < 0))
        return gains / max(losses, 0.01)

    def daily_summary(self) -> str:
        n = len(self.daily_trades)
        if n == 0:
            return "Pas de trades aujourd'hui"
        return (f"{n} trades | P&L: ${self.daily_pnl:+.2f} | "
                f"WR: {self.win_rate*100:.0f}% | PF: {self.profit_factor:.2f} | "
                f"Consec losses: {self.consecutive_losses}")

    def reset_daily(self):
        """Reset les stats journalieres (appeler chaque matin)."""
        self.trade_count = 0
        self.daily_pnl = 0.0
        self.daily_trades = []
        self.consecutive_losses = 0
