"""Trailing SL Dow pivots Bot BN V4.

Wrapper safe autour de CORE.bn_v4_engine.TrailingState + update_trailing.
Le moteur pur est inchange - on encapsule la creation initiale + propagation
de l'eventuel new_sl vers le router DTC (cancel-replace SL).

Spec Jackson 22/05/2026 :
  - SL initial : low(entry_bar) - 6 ticks (LONG) / high + 6 ticks (SHORT)
  - A chaque cassure du dernier high (close > prev_attack_high), SL monte
    au low du pullback precedent - 6 ticks
  - Detection pullback : 3 bars consecutives sans new high (LONG)
  - Exit : SL hit OU timeout 90 bars
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from CORE.bn_v4_engine import (
    BNV4Engine,
    TrailingState,
    make_trailing_state,
    update_trailing as engine_update_trailing,
)
from CORE.bot_bn_v4.config import BotBNV4Config


@dataclass
class TrailingUpdate:
    """Resultat d'un update trailing."""
    new_sl: Optional[float] = None     # None si pas de change
    is_timeout: bool = False           # True si timeout 90 bars atteint
    error: Optional[str] = None        # message si raise (OHLC NaN par ex)


class TrailingManager:
    """Wrapper safe de TrailingState pour Bot BN V4.

    Pattern :
        trail = TrailingManager(symbol="NQ", cfg=cfg)
        # Apres fill du parent :
        trail.start(direction="long", entry_bar=bar_at_fill, entry_price=fill_px)
        # A chaque tick :
        upd = trail.on_bar(bar)
        if upd.new_sl is not None:
            router.replace_sl(upd.new_sl)
        if upd.is_timeout:
            router.close_position(reason="TIMEOUT_90")
    """

    def __init__(self, symbol: str, cfg: BotBNV4Config):
        self.symbol = symbol.upper()
        self.cfg = cfg
        from CORE.bn_v4_engine import TICK_SIZE
        self.tick = TICK_SIZE.get(self.symbol, 0.25)
        self.state: Optional[TrailingState] = None

    def is_active(self) -> bool:
        return self.state is not None

    def start(
        self,
        direction: str,
        entry_bar: dict,
        entry_price: float,
        entry_bar_idx: int = 0,
    ) -> Optional[str]:
        """Demarre le trailing pour une position ouverte.

        Returns:
            None si OK, message d'erreur si OHLC invalide / risk hors bornes.
        """
        try:
            self.state = make_trailing_state(
                direction=direction,
                entry_bar=entry_bar,
                entry_price=entry_price,
                tick=self.tick,
                entry_bar_idx=entry_bar_idx,
                max_risk_ticks=self.cfg.MAX_RISK_TICKS,
                min_risk_ticks=self.cfg.MIN_RISK_TICKS,
            )
            return None
        except ValueError as exc:
            return f"TRAILING_START_FAIL:{exc}"

    def on_bar(self, bar: dict) -> TrailingUpdate:
        """Update trailing avec une nouvelle bar (close).

        Returns:
            TrailingUpdate(new_sl, is_timeout, error).
        """
        if self.state is None:
            return TrailingUpdate(error="TRAILING_INACTIVE")

        try:
            new_sl = engine_update_trailing(self.state, bar)
        except ValueError as exc:
            return TrailingUpdate(error=f"OHLC_INVALID:{exc}")

        # Check timeout via ts_event_ns
        cur_ts_ns = int(bar.get("ts_event_ns") or 0)
        is_timeout = False
        if cur_ts_ns > 0 and self.state.entry_ts_ns > 0:
            delta_min = (cur_ts_ns - self.state.entry_ts_ns) / 60_000_000_000
            is_timeout = delta_min >= self.cfg.TIMEOUT_BARS

        return TrailingUpdate(new_sl=new_sl, is_timeout=is_timeout)

    def get_current_sl(self) -> Optional[float]:
        if self.state is None:
            return None
        return self.state.sl_current

    def stop(self) -> None:
        """Reset state quand la position ferme."""
        self.state = None

    def n_pivots(self) -> int:
        """Nb pivots Dow confirmes (pour stats post-trade)."""
        if self.state is None:
            return 0
        return self.state.n_pivots_confirmed
