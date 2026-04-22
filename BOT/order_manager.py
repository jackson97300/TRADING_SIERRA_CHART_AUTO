"""
order_manager.py — Gestion des ordres MIA V2
===============================================

Envoie les ordres via DTC, gere les brackets SL/TP,
track les fills et le statut des positions.

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from bot_config import BotConfig, InstrumentConfig
from dtc_connector import DTCConnector, OrderFill, BUY, SELL

# Systeme logs V2 (22/04/2026)
try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("order_manager", process="bot_legacy")
except Exception:
    _v2log = None


@dataclass
class Position:
    """Position ouverte."""
    symbol: str = ""
    direction: int = 0          # +1 = LONG, -1 = SHORT
    entry_price: float = 0.0
    entry_time: float = 0.0
    quantity: int = 1
    sl_price: float = 0.0
    tp_price: float = 0.0
    order_id: str = ""
    sl_order_id: str = ""
    tp_order_id: str = ""
    unrealized_pnl: float = 0.0
    max_favorable: float = 0.0     # MFE
    max_adverse: float = 0.0       # MAE


class OrderManager:
    """Gestionnaire d'ordres et positions."""

    def __init__(self, config: BotConfig, dtc: DTCConnector):
        self.cfg = config
        self.dtc = dtc
        self.positions: Dict[str, Position] = {}  # symbol → Position
        self._pending_opens: Dict[str, dict] = {}   # order_id → {symbol, position}
        self._pending_closes: Dict[str, str] = {}    # order_id → symbol
        self._confirmed_closes: Dict[str, float] = {}  # symbol → fill_price
        self._bracket_orders: Dict[str, str] = {}  # tp_cid/sl_cid → symbol

        # Callback externe quand un trade se ferme (TP/SL/manuel)
        # Signature : on_trade_close(symbol, exit_type, exit_price, pnl_ticks, pnl_usd, position)
        self.on_trade_close: Optional[callable] = None

        # Callback fills
        self.dtc.on_fill = self._on_fill

    def open_position(self, symbol: str, direction: int,
                       instrument: InstrumentConfig,
                       quantity: int = 1,
                       sl_ticks: float = 0,
                       tp_ticks: float = 0,
                       current_price: float = 0) -> Optional[str]:
        """
        Ouvre une position avec bracket SL/TP.

        Args:
            symbol: "ES" ou "NQ"
            direction: +1 (LONG) ou -1 (SHORT)
            instrument: config instrument
            quantity: nombre de contrats
            sl_ticks: stop loss en ticks depuis l'entree
            tp_ticks: take profit en ticks depuis l'entree

        Returns:
            order_id ou None si echec
        """
        if symbol in self.positions:
            return None  # Deja en position

        # Calculer SL/TP prix
        ts = instrument.tick_size
        if direction == 1:  # LONG
            sl_price = current_price - sl_ticks * ts if sl_ticks > 0 else 0
            tp_price = current_price + tp_ticks * ts if tp_ticks > 0 else 0
            side = BUY
        else:  # SHORT
            sl_price = current_price + sl_ticks * ts if sl_ticks > 0 else 0
            tp_price = current_price - tp_ticks * ts if tp_ticks > 0 else 0
            side = SELL

        # Envoyer l'ordre
        result = self.dtc.send_market_order(
            symbol=instrument.contract,
            side=side,
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        parent_id, tp_cid, sl_cid = result

        if not parent_id:
            # V2 log : ordre refuse par broker au submit
            if _v2log:
                _v2log.emit("ORDER_REJECT", sym=symbol, err_code=0,
                            err_msg="no_parent_id_returned")
            return None

        # V2 log : ordre envoye (bracket parent + SL + TP)
        if _v2log:
            dir_str = "BUY" if direction == 1 else "SELL"
            _v2log.emit("ORDER_SUBMIT", sym=symbol, type="MARKET_BRACKET",
                        direction=dir_str, qty=quantity)

        # Creer la position (sera confirmee au fill)
        pos = Position(
            symbol=symbol,
            direction=direction,
            entry_price=current_price,
            entry_time=time.time(),
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
            order_id=parent_id,
            tp_order_id=tp_cid,
            sl_order_id=sl_cid,
        )
        self.positions[symbol] = pos
        self._pending_opens[parent_id] = {"symbol": symbol, "position": pos}

        # Tracker les bracket IDs pour detecter le fill TP/SL
        if tp_cid:
            self._bracket_orders[tp_cid] = symbol
        if sl_cid:
            self._bracket_orders[sl_cid] = symbol

        return parent_id

    def close_position(self, symbol: str, reason: str = "MANUAL") -> Optional[str]:
        """Ferme une position ouverte."""
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        instrument = self.cfg.get_instrument(symbol)

        # Ordre inverse pour fermer
        if pos.direction == 1:
            side = SELL
        else:
            side = BUY

        result = self.dtc.send_market_order(
            symbol=instrument.contract,
            side=side,
            quantity=pos.quantity,
        )
        order_id = result[0] if isinstance(result, tuple) else result

        # Tracker le fill de fermeture
        if order_id:
            self._pending_closes[order_id] = symbol

        # Annuler les ordres bracket
        if pos.sl_order_id:
            self.dtc.cancel_order(pos.sl_order_id)
        if pos.tp_order_id:
            self.dtc.cancel_order(pos.tp_order_id)

        return order_id

    def flatten_all(self, reason: str = "FLATTEN"):
        """Ferme toutes les positions (EOD ou kill switch)."""
        for symbol in list(self.positions.keys()):
            self.close_position(symbol, reason)

    def update_unrealized_pnl(self, symbol: str, current_price: float):
        """Met a jour le P&L non realise d'une position."""
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]
        instrument = self.cfg.get_instrument(symbol)
        ts = instrument.tick_size
        tv = instrument.tick_value

        pnl_ticks = (current_price - pos.entry_price) / ts * pos.direction
        pos.unrealized_pnl = pnl_ticks * tv * pos.quantity

        # MFE / MAE tracking
        if pnl_ticks > pos.max_favorable:
            pos.max_favorable = pnl_ticks
        if pnl_ticks < -pos.max_adverse:
            pos.max_adverse = abs(pnl_ticks)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def _on_fill(self, fill: OrderFill):
        """Callback quand un ordre est rempli (ouverture, fermeture, ou TP/SL)."""
        import logging
        log = logging.getLogger("MIA")

        # Fill d'ouverture (parent order)
        pending = self._pending_opens.get(fill.order_id)
        if pending:
            pos = pending["position"]
            pos.entry_price = fill.fill_price
            del self._pending_opens[fill.order_id]
            log.info(f"[FILL] Ouverture {pending['symbol']} @ {fill.fill_price}")
            # V2 log : fill parent order
            if _v2log:
                _v2log.emit("ORDER_FILL", order_id=fill.order_id,
                            price=fill.fill_price, slip=0.0)
            return

        # Fill de fermeture manuelle (close_position)
        symbol = self._pending_closes.get(fill.order_id)
        if symbol:
            self._confirmed_closes[symbol] = fill.fill_price
            pos = self.positions.get(symbol)
            if pos:
                pnl_ticks = (fill.fill_price - pos.entry_price) / 0.25 * pos.direction
                tick_value = 1.25 if symbol == "ES" else 0.50
                pnl_usd = pnl_ticks * tick_value * pos.quantity
                self.positions.pop(symbol)
                log.info(f"[FILL] Fermeture manuelle {symbol} @ {fill.fill_price} "
                         f"PnL={pnl_ticks:+.0f}t ${pnl_usd:+.2f}")
                # Callback externe (journal + risk)
                if self.on_trade_close:
                    try:
                        self.on_trade_close(symbol, "MANUAL", fill.fill_price,
                                            pnl_ticks, pnl_usd, pos)
                    except Exception as e:
                        log.error(f"on_trade_close callback error: {e}")
            del self._pending_closes[fill.order_id]
            return

        # Fill TP ou SL (bracket OCO) — CRITIQUE
        symbol = self._bracket_orders.get(fill.order_id)
        if symbol:
            is_tp = "_TP_" in fill.order_id
            exit_type = "TP" if is_tp else "SL"
            pos = self.positions.get(symbol)
            pnl_ticks = 0.0
            pnl_usd = 0.0
            if pos:
                pnl_ticks = (fill.fill_price - pos.entry_price) / 0.25 * pos.direction
                tick_value = 1.25 if symbol == "ES" else 0.50
                pnl_usd = pnl_ticks * tick_value * pos.quantity
            log.info(f"[FILL] {exit_type} {symbol} @ {fill.fill_price} "
                     f"PnL={pnl_ticks:+.0f}t ${pnl_usd:+.2f}")
            # V2 log : fill TP/SL bracket (le trade_close sera emis par bot_main callback)
            if _v2log:
                _v2log.emit("ORDER_FILL", order_id=fill.order_id,
                            price=fill.fill_price, slip=0.0)

            # Retirer la position
            self.positions.pop(symbol, None)
            self._bracket_orders.pop(fill.order_id, None)

            # Nettoyer l'autre bracket ID aussi (cancel oppose OCO manuel)
            for cid, sym in list(self._bracket_orders.items()):
                if sym == symbol:
                    self._bracket_orders.pop(cid, None)
                    # V2 log : OCO cancel oppose (TP fill → cancel SL ou SL fill → cancel TP)
                    if _v2log:
                        _v2log.emit("OCO_CANCEL_OPPOSITE", order_id=cid)

            # CRITIQUE : Callback externe pour journal + risk manager
            if self.on_trade_close and pos:
                try:
                    self.on_trade_close(symbol, exit_type, fill.fill_price,
                                        pnl_ticks, pnl_usd, pos)
                except Exception as e:
                    log.error(f"on_trade_close callback error: {e}")

            return

    def is_close_confirmed(self, symbol: str) -> bool:
        """Verifie si la fermeture a ete confirmee par un fill."""
        return symbol in self._confirmed_closes

    def get_close_fill_price(self, symbol: str) -> float:
        """Retourne le prix de fill de fermeture. 0 si pas confirme."""
        return self._confirmed_closes.pop(symbol, 0.0)

    def remove_position(self, symbol: str) -> Optional[Position]:
        """Retire une position du tracking."""
        self._confirmed_closes.pop(symbol, None)
        return self.positions.pop(symbol, None)

    @property
    def total_positions(self) -> int:
        return len(self.positions)

    def summary(self) -> str:
        if not self.positions:
            return "Pas de position ouverte"
        parts = []
        for sym, pos in self.positions.items():
            dir_str = "LONG" if pos.direction == 1 else "SHORT"
            parts.append(f"{sym} {dir_str} @{pos.entry_price:.2f} "
                         f"P&L=${pos.unrealized_pnl:+.2f}")
        return " | ".join(parts)
