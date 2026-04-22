"""Volatility Spike Gate — protection news imprevues.

Origine 22/04/2026 : Jackson a bust compte Topstep sur news imprevue
(mouvement violent non calendrier). Gate proxy `bar_range / atr > N`
detecte ces spikes et bloque trades + cooldown N barres.

Usage :
    from CORE.volatility_gate import VolatilitySpikeGate
    gate = VolatilitySpikeGate(threshold_ratio=3.0, cooldown_bars=10)
    allowed, reason = gate.check(symbol="ES", bar=bar_dict, bar_count=N)
    if not allowed:
        # skip trade, log VOLATILITY_SPIKE
        pass

Logique :
  bar_range_ticks = (bar_high - bar_low) / tick_size
  ratio = bar_range_ticks / atr_ticks
  IF ratio > threshold → spike detecte → VETO + lance cooldown
  IF cooldown actif (bars_since_spike < cooldown_bars) → VETO persist
  SINON → ALLOW

Threshold 3.0 standard (news FOMC typiques: 4-6x, crash: 8x+).
Cooldown 10 bars = ~10 min pour laisser le spread normaliser post-news.

Integration :
- Appele par bot_main._tick() AVANT _execute_trade()
- Compatible BOT legacy + V2CLEAN + V2-BIS (bridge C++ P1)
- Log V2 code : VOLATILITY_SPIKE ALERTE (risk)
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# Tick sizes (centralises CORE/constants.py si dispo, sinon hardcoded)
_TICK_SIZE = {"ES": 0.25, "NQ": 0.25}


class VolatilitySpikeGate:
    """Gate volatilite anormale via proxy range/ATR ratio."""

    def __init__(
        self,
        threshold_ratio: float = 3.0,
        cooldown_bars: int = 10,
    ):
        self.threshold = threshold_ratio
        self.cooldown_bars = cooldown_bars
        # sym -> bar_count au moment du spike (pour cooldown)
        self._spike_bar: Dict[str, int] = {}
        self._last_ratio: Dict[str, float] = {}

    def check(
        self,
        symbol: str,
        bar: dict,
        bar_count: int,
    ) -> Tuple[bool, str]:
        """Evalue si trading autorise sur cette barre.

        Args:
            symbol: "ES" ou "NQ"
            bar: dict JSONL avec bar_high, bar_low, atr (ticks)
            bar_count: compteur barre courant (pour cooldown)

        Returns:
            (allowed: bool, reason: str)
        """
        atr_ticks = self._get_atr(bar)
        if atr_ticks <= 0:
            return True, "no_atr_data"

        bar_range_ticks = self._get_range_ticks(bar, symbol)
        if bar_range_ticks <= 0:
            return True, "no_range_data"

        ratio = bar_range_ticks / atr_ticks
        self._last_ratio[symbol] = ratio

        # Spike detection
        if ratio > self.threshold:
            self._spike_bar[symbol] = bar_count
            return False, f"volatility_spike_{ratio:.1f}x_atr"

        # Cooldown post-spike
        spike_at = self._spike_bar.get(symbol)
        if spike_at is not None:
            bars_since = bar_count - spike_at
            if bars_since < self.cooldown_bars:
                remaining = self.cooldown_bars - bars_since
                return False, f"post_spike_cooldown_{remaining}b"

        return True, "ok"

    def _get_atr(self, bar: dict) -> float:
        """ATR en ticks depuis le bar JSONL."""
        atr = bar.get("atr", 0.0)
        try:
            return float(atr) if atr is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _get_range_ticks(self, bar: dict, symbol: str) -> float:
        """Range de la barre en ticks."""
        bar_high = bar.get("bar_high", 0.0)
        bar_low = bar.get("bar_low", 0.0)
        try:
            bh = float(bar_high) if bar_high is not None else 0.0
            bl = float(bar_low) if bar_low is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
        if bh <= 0 or bl <= 0 or bh < bl:
            return 0.0
        tick = _TICK_SIZE.get(symbol, 0.25)
        return (bh - bl) / tick

    def last_ratio(self, symbol: str) -> Optional[float]:
        """Ratio range/atr dernier check (pour dashboard / debug)."""
        return self._last_ratio.get(symbol)

    def is_in_cooldown(self, symbol: str, bar_count: int) -> bool:
        """True si sym en cooldown post-spike."""
        spike_at = self._spike_bar.get(symbol)
        if spike_at is None:
            return False
        return (bar_count - spike_at) < self.cooldown_bars

    def reset(self, symbol: Optional[str] = None) -> None:
        """Reset state (tous symbols si symbol=None, sinon 1 seul)."""
        if symbol is None:
            self._spike_bar.clear()
            self._last_ratio.clear()
        else:
            self._spike_bar.pop(symbol, None)
            self._last_ratio.pop(symbol, None)
