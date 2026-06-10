"""
Pullback Entry Gate (01/05/2026)
================================

Apres signal BUY/SELL, attendre pullback OU proximite swing avant entree.
Permet d'entrer a un meilleur prix → SL plus loin du prix entree → trade plus protege.

Logique trader Jackson (10K h experience) :
  1. Signal BUY @ P
  2. Si dist_swing_low <= PROXIMITY_SWING_TICKS → entree IMMEDIATE (deja au support)
  3. Sinon : attendre pullback de PULLBACK_TICKS avant d'entrer (timeout 3 min)
  4. Si timeout → ANNULE signal (evite chase late entry)

Calibration empirique (audit MAE 19 TP historiques 7j) :
  NQ : MAE P25=5t, P50=10t, P75=23t → pullback=5t (capture 75% TP)
  ES : MAE P25=0t, P50=0.5t, P75=7t → pullback=0t (entry immediate, ES = trends propres)

Anti-pattern 11 :
  - Module isole, pas de cascade avec autres vetos
  - Config flag enabled/disabled par symbole
  - Backteste obligatoire avant deploy
  - Logger tous les events (PULLBACK_WAITING, PULLBACK_FILLED, PULLBACK_TIMEOUT)
"""

from dataclasses import dataclass, field
from typing import Optional, Literal
import time

# Cf databento_paper_trader.py:148 / mia_paper_trader.py
TICK_SIZE = 0.25

# ═════════════════════════════════════════════════════════════════════
# CONFIG (calibration empirique 01/05/2026)
# ═════════════════════════════════════════════════════════════════════

PULLBACK_CONFIG = {
    "NQ": {
        "enabled": True,
        "pullback_ticks": 5,           # P25 MAE NQ TP historiques
        "proximity_swing_ticks": 5,    # Si <= 5t swing → entry immediate
        "timeout_sec": 180,            # 3 min max attente
    },
    "ES": {
        "enabled": True,
        "pullback_ticks": 0,           # P25 MAE ES TP historiques (ES = trends propres)
        "proximity_swing_ticks": 3,
        "timeout_sec": 180,
    },
}


# ═════════════════════════════════════════════════════════════════════
# TYPES
# ═════════════════════════════════════════════════════════════════════

EntryAction = Literal["ENTER_NOW", "WAIT_PULLBACK", "TIMEOUT", "WAITING"]


@dataclass
class PendingEntry:
    """Signal en attente de pullback."""
    signal_id: str
    symbol: str
    direction: str           # "LONG" ou "SHORT"
    signal_price: float      # Prix au moment du signal
    pullback_target: float   # Prix a atteindre pour entrer
    timeout_at: float        # Unix timestamp deadline
    reason: str              # "pullback" ou "swing_proximity_skip"
    created_at: float = field(default_factory=time.time)


@dataclass
class EntryDecision:
    """Decision d'entree apres pullback gate."""
    action: EntryAction
    target_price: float        # Prix d'entree cible (= signal_price si ENTER_NOW)
    pullback_ticks_used: int   # 0 si entry immediate
    reason: str


# ═════════════════════════════════════════════════════════════════════
# PULLBACK ENTRY GATE
# ═════════════════════════════════════════════════════════════════════

class PullbackEntryGate:
    """Gate d'entree avec pullback ou proximity swing."""

    def __init__(self, config: dict = None):
        self.config = config if config is not None else PULLBACK_CONFIG

    def evaluate_signal(self,
                         symbol: str,
                         direction: str,
                         signal_price: float,
                         dist_swing_long_ticks: float,
                         dist_swing_short_ticks: float,
                         signal_id: str = "") -> tuple[EntryDecision, Optional[PendingEntry]]:
        """
        Evalue un signal directional.

        Args:
            symbol : "ES" ou "NQ"
            direction : "LONG" ou "SHORT"
            signal_price : prix close au moment du signal
            dist_swing_long_ticks : dist au swing low (pour LONG support) ou high (SHORT) en ticks signes
            dist_swing_short_ticks : symetrique pour SHORT
            signal_id : id pour traçabilite

        Returns:
            (EntryDecision, PendingEntry) :
              - EntryDecision.action ∈ {ENTER_NOW, WAIT_PULLBACK}
              - PendingEntry si WAIT_PULLBACK, None sinon
        """
        cfg = self.config.get(symbol, {})
        if not cfg.get("enabled", False):
            return EntryDecision(action="ENTER_NOW", target_price=signal_price,
                                 pullback_ticks_used=0,
                                 reason="pullback_disabled"), None

        pullback_ticks = cfg.get("pullback_ticks", 0)
        proximity_ticks = cfg.get("proximity_swing_ticks", 0)
        timeout_sec = cfg.get("timeout_sec", 180)

        # Cas 1 : pullback_ticks = 0 → entry immediate (ES typically)
        if pullback_ticks == 0:
            return EntryDecision(action="ENTER_NOW", target_price=signal_price,
                                 pullback_ticks_used=0,
                                 reason="pullback_zero_immediate"), None

        # Cas 2 : proche swing → entry immediate
        # Pour LONG : swing_low en-dessous = dist negative ; on regarde |dist|
        # Pour SHORT : swing_high au-dessus = dist positive ; on regarde |dist|
        if direction == "LONG":
            dist_to_swing = abs(dist_swing_long_ticks)
        else:
            dist_to_swing = abs(dist_swing_short_ticks)

        if dist_to_swing <= proximity_ticks:
            return EntryDecision(action="ENTER_NOW", target_price=signal_price,
                                 pullback_ticks_used=0,
                                 reason=f"proximity_swing_{int(dist_to_swing)}t"), None

        # Cas 3 : attendre pullback
        if direction == "LONG":
            target = signal_price - pullback_ticks * TICK_SIZE
        else:
            target = signal_price + pullback_ticks * TICK_SIZE

        pending = PendingEntry(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            signal_price=signal_price,
            pullback_target=target,
            timeout_at=time.time() + timeout_sec,
            reason=f"wait_pullback_{pullback_ticks}t",
        )
        return EntryDecision(action="WAIT_PULLBACK", target_price=target,
                              pullback_ticks_used=pullback_ticks,
                              reason=pending.reason), pending

    def check_pullback_status(self, pending: PendingEntry,
                                bar_high: float, bar_low: float,
                                bar_close: float, bar_open: float,
                                now: Optional[float] = None) -> EntryAction:
        """
        Verifie sur une nouvelle bar si le pullback est atteint.

        Args:
            pending : PendingEntry en cours
            bar_high, bar_low, bar_close, bar_open : OHLC de la bar
            now : current unix timestamp (default time.time())

        Returns:
            "ENTER" : pullback atteint + reverse confirme → declenche entry
            "TIMEOUT" : timeout depasse → annule signal
            "WAITING" : pullback pas encore atteint → continue d'attendre
        """
        if now is None:
            now = time.time()

        # Timeout check
        if now > pending.timeout_at:
            return "TIMEOUT"

        # Pullback check
        if pending.direction == "LONG":
            # Pour LONG : pullback atteint si bar.low <= target
            if bar_low <= pending.pullback_target:
                # Confirmation reverse : close > open (recovery sur pullback)
                if bar_close > bar_open:
                    return "ENTER"
                # Pullback atteint mais pas reverse → continue d'attendre la confirmation
        else:  # SHORT
            if bar_high >= pending.pullback_target:
                # Confirmation reverse : close < open (echec rebond apres push haut)
                if bar_close < bar_open:
                    return "ENTER"

        return "WAITING"
