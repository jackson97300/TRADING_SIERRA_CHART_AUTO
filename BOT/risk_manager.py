"""
risk_manager.py — Gestion du risque MIA V2
============================================

Half-Kelly position sizing, circuit breaker, kill switch, daily limits.
Chaque trade passe par can_trade() avant execution.

Referencesbest practices :
  - Ernest Chan: Half-Kelly (ch.8 Algorithmic Trading)
  - Robert Carver: Conservative position sizing
  - Industrie: Circuit breaker 3 niveaux

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    ET_ZONE = ZoneInfo("America/New_York")
except ImportError:
    ET_ZONE = None

from bot_config import BotConfig, InstrumentConfig


@dataclass
class RiskState:
    """Etat courant du risk manager."""
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_peak_pnl: float = 0.0
    consecutive_losses: int = 0
    last_trade_time: float = 0.0        # timestamp
    is_paused: bool = False
    pause_until: float = 0.0            # timestamp fin de pause
    is_killed: bool = False
    kill_reason: str = ""
    open_positions: int = 0


class RiskManager:
    """Gestionnaire de risque avec kill switch et circuit breaker."""

    def __init__(self, config: BotConfig):
        self.cfg = config.risk
        self.session_cfg = config.session
        self.state = RiskState()

    def can_trade(self, symbol: str, direction: int,
                  instrument: InstrumentConfig) -> tuple:
        """
        Verifie si un trade est autorise.

        Returns:
            (allowed: bool, reason: str)
        """
        now = time.time()

        # ── Kill Switch ──
        if self.state.is_killed:
            return False, f"KILLED: {self.state.kill_reason}"

        # ── Daily loss limit ──
        # Wrappe par flag : desactive en phase collecte, a reactiver avant live reel
        if self.cfg.daily_loss_check_enabled:
            if self.state.daily_pnl <= -self.cfg.max_daily_loss_usd:
                self._kill(f"Daily loss limit ${self.cfg.max_daily_loss_usd}")
                return False, f"Daily loss limit atteint (${self.state.daily_pnl:.2f})"

        # ── Max trades/jour ──
        if self.state.daily_trades >= self.cfg.max_daily_trades:
            return False, f"Max trades/jour ({self.cfg.max_daily_trades})"

        # ── Drawdown intraday ──
        drawdown = self.state.daily_peak_pnl - self.state.daily_pnl
        if drawdown > self.cfg.max_drawdown_intraday_usd:
            self._kill(f"Intraday drawdown ${drawdown:.2f}")
            return False, f"Drawdown intraday ${drawdown:.2f} > ${self.cfg.max_drawdown_intraday_usd}"

        # ── Davey kill rule : live DD > N x backtest max DD ──
        # (Kevin Davey, Building Winning Algo Systems ch.Risk Mgmt)
        # Active seulement si backtest_max_dd_usd > 0 (config manuelle apres training)
        if self.cfg.backtest_max_dd_usd > 0.0:
            kill_threshold = self.cfg.backtest_max_dd_usd * self.cfg.kill_dd_multiplier
            if drawdown > kill_threshold:
                self._kill(
                    f"Davey rule: live DD ${drawdown:.2f} > "
                    f"{self.cfg.kill_dd_multiplier}x backtest max DD "
                    f"(${self.cfg.backtest_max_dd_usd:.2f}) = ${kill_threshold:.2f}"
                )
                return False, (
                    f"Davey kill: DD ${drawdown:.2f} > "
                    f"{self.cfg.kill_dd_multiplier}x backtest DD"
                )

        # ── Circuit breaker (pause apres pertes consecutives) ──
        if self.state.is_paused:
            if now < self.state.pause_until:
                remaining = int(self.state.pause_until - now)
                return False, f"Circuit breaker actif ({remaining}s restantes)"
            else:
                self.state.is_paused = False
                self.state.consecutive_losses = 0  # Reset apres la pause

        if self.state.consecutive_losses >= self.cfg.consecutive_losses_pause:
            self._pause()
            return False, f"Circuit breaker: {self.state.consecutive_losses} pertes consecutives"

        # ── Cooldown entre les trades ──
        elapsed = now - self.state.last_trade_time
        if elapsed < self.cfg.cooldown_after_win_seconds and self.state.last_trade_time > 0:
            return False, f"Cooldown ({int(self.cfg.cooldown_after_win_seconds - elapsed)}s)"

        # ── Position limits ──
        if self.state.open_positions >= self.cfg.max_positions_total:
            return False, f"Max positions ({self.cfg.max_positions_total})"

        # ── Session check ──
        if getattr(self.session_cfg, 'all_sessions', False):
            # H24 — toutes sessions autorisees
            return True, "OK"

        now_utc = datetime.now(timezone.utc)
        if ET_ZONE:
            now_et = now_utc.astimezone(ET_ZONE)
            h_et = now_et.hour
            m_et = now_et.minute
        else:
            h_et = (now_utc.hour - 4) % 24  # Fallback sans zoneinfo
            m_et = now_utc.minute
        t_et = h_et * 60 + m_et

        rth_start = self.session_cfg.rth_start_hour * 60 + self.session_cfg.rth_start_minute
        rth_end = self.session_cfg.rth_end_hour * 60 + self.session_cfg.rth_end_minute

        if t_et < rth_start + self.session_cfg.no_trade_first_minutes:
            return False, "Trop tot (premiere minutes)"

        eod_cutoff = rth_end - self.session_cfg.eod_flatten_minutes_before
        if t_et >= eod_cutoff:
            return False, "Trop tard (EOD flatten zone)"

        if t_et < rth_start or t_et >= rth_end:
            return False, "Hors session RTH"

        return True, "OK"

    def compute_position_size(self, instrument: InstrumentConfig,
                               sl_ticks: float,
                               win_rate: float = 0.55) -> int:
        """
        Calcule la taille de position avec Half-Kelly.

        Kelly% = W - (1-W)/R  ou W=win_rate, R=reward/risk ratio
        Half-Kelly = Kelly% / 2

        Returns:
            Nombre de contrats (minimum 1, maximum max_contracts)
        """
        rr = instrument.rr_ratio
        kelly_pct = win_rate - (1 - win_rate) / rr

        if kelly_pct <= 0:
            return 1  # Minimum 1 micro

        half_kelly = kelly_pct * self.cfg.kelly_fraction

        # Risque max par trade
        max_risk = self.cfg.account_size_usd * (self.cfg.max_risk_per_trade_pct / 100)

        # Risque par contrat = SL_ticks × tick_value
        risk_per_contract = sl_ticks * instrument.tick_value

        if risk_per_contract <= 0:
            return 1

        # Nombre de contrats
        contracts_kelly = int(half_kelly * self.cfg.account_size_usd / risk_per_contract)
        contracts_max_risk = int(max_risk / risk_per_contract)

        contracts = min(contracts_kelly, contracts_max_risk, instrument.max_contracts)
        return max(1, contracts)  # Minimum 1

    def on_trade_open(self, symbol: str):
        """Appelé quand un trade est ouvert."""
        self.state.open_positions += 1
        self.state.daily_trades += 1
        self.state.last_trade_time = time.time()

    def on_trade_close(self, symbol: str, pnl_usd: float):
        """Appelé quand un trade est fermé."""
        self.state.open_positions = max(0, self.state.open_positions - 1)
        self.state.daily_pnl += pnl_usd

        # Peak tracking
        if self.state.daily_pnl > self.state.daily_peak_pnl:
            self.state.daily_peak_pnl = self.state.daily_pnl

        # Consecutive losses
        if pnl_usd < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

    def should_flatten_eod(self) -> bool:
        """Verifie si on doit tout fermer (fin de journee)."""
        now_utc = datetime.now(timezone.utc)
        if ET_ZONE:
            now_et = now_utc.astimezone(ET_ZONE)
            h_et, m_et = now_et.hour, now_et.minute
        else:
            h_et = (now_utc.hour - 4) % 24
            m_et = now_utc.minute
        t_et = h_et * 60 + m_et

        eod_cutoff = (self.session_cfg.rth_end_hour * 60 +
                      self.session_cfg.rth_end_minute -
                      self.session_cfg.eod_flatten_minutes_before)

        return t_et >= eod_cutoff

    def _pause(self):
        """Active le circuit breaker."""
        self.state.is_paused = True
        self.state.pause_until = time.time() + self.cfg.pause_duration_minutes * 60

    def _kill(self, reason: str):
        """Active le kill switch — plus aucun trade possible."""
        self.state.is_killed = True
        self.state.kill_reason = reason

    def reset_daily(self):
        """Reset l'etat pour une nouvelle journee."""
        self.state = RiskState()

    def summary(self) -> str:
        return (f"P&L: ${self.state.daily_pnl:+.2f} | "
                f"Trades: {self.state.daily_trades}/{self.cfg.max_daily_trades} | "
                f"Positions: {self.state.open_positions} | "
                f"ConsecLoss: {self.state.consecutive_losses} | "
                f"{'KILLED' if self.state.is_killed else 'PAUSED' if self.state.is_paused else 'ACTIVE'}")
