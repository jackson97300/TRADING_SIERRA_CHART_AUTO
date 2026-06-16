"""Order router Bot BN V4 - DTC wrapper avec dry-run mode.

Fork minimaliste de CORE.bot1_v2.execution.order_router.OrderRouter avec :
  - ClientName = "MIA_BotBN" (anti-collision MIA_Bot1V2 / MIA_PaperTrader)
  - TradeAccount = Sim3 (PAS Sim2 = Bot 1 v2, PAS Sim4 = Bot 4)
  - PAS de TP_LIMIT (BN V4 = trailing SL Dow pivots, exit via SL hit ou timeout)
  - SL initial calcule via TrailingManager apres fill

Mode dry_run : pas de DTC, fill simule au prix d'entree.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from CORE.bot_bn_v4.config import BotBNV4Config


@dataclass(frozen=True)
class OrderResult:
    """Resultat envoi ordre."""
    success: bool
    parent_cid: str = ""
    sl_cid: str = ""
    fill_price: float = 0.0
    error_msg: str = ""
    dry_run: bool = False


class OrderRouter:
    """Routeur d'ordres pour Bot BN V4 via DTC connector.

    En mode dry_run, simule le fill au prix d'entree.
    """

    def __init__(
        self,
        cfg: BotBNV4Config,
        dry_run: bool = True,
        dtc_connector=None,
    ):
        self.cfg = cfg
        self.dry_run = dry_run
        self.dtc = dtc_connector

    def _make_cid(self, prefix: str) -> str:
        """ClientOrderID unique : BOTBN_{prefix}_{shorthash}.

        Prefix permet d'identifier P (parent), SL (trailing stop).
        Pas de TP (BN V4 = exit pivot Dow ou timeout 90b).
        """
        short = uuid.uuid4().hex[:8]
        return f"BOTBN_{prefix}_{short}"

    def send_entry(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        n_micros: int = 1,
    ) -> OrderResult:
        """Envoie un parent MARKET + SL STOP (PAS de TP).

        Args:
            symbol : ES / NQ / MGC
            direction : "long" / "short"
            entry_price : prix d'entree estime (pour signal_ref_price DTC)
            sl_price : prix SL initial calcule par TrailingManager
            n_micros : nb micros (default 1)

        Returns:
            OrderResult avec parent_cid + sl_cid + fill_price.
        """
        parent_cid = self._make_cid("P")
        sl_cid = self._make_cid("SL")

        if self.dry_run:
            # Simulation pure : fill au prix d'entree
            return OrderResult(
                success=True,
                parent_cid=parent_cid,
                sl_cid=sl_cid,
                fill_price=entry_price,
                dry_run=True,
            )

        # Mode prod : DTC connector
        if self.dtc is None:
            return OrderResult(
                success=False,
                error_msg="DTC_CONNECTOR_NULL_IN_PROD",
                dry_run=False,
            )

        try:
            # Mapping direction str -> side int (1=BUY, 2=SELL)
            side = 1 if direction == "long" else 2
            send_fn = getattr(self.dtc, "send_market_order", None)
            if send_fn is None:
                return OrderResult(
                    success=False,
                    error_msg="DTC_NO_SEND_MARKET_ORDER",
                    dry_run=False,
                )
            try:
                from CORE.constants import get_tick_size
            except ImportError:
                from constants import get_tick_size  # type: ignore
            tick = get_tick_size(symbol)

            # BN V4 : pas de TP, on passe tp_price=0 (= ignore cote DTC).
            # Le legacy connecteur signe (symbol, side, quantity, sl_price, tp_price,
            # trade_account, signal_ref_price, sl_ticks, tp_ticks, tick_size).
            sl_ticks_calc = abs(entry_price - sl_price) / tick
            result = send_fn(
                symbol=symbol,
                side=side,
                quantity=n_micros,
                sl_price=sl_price,
                tp_price=0.0,
                trade_account=self.cfg.TRADE_ACCOUNT,  # Sim3 explicite
                signal_ref_price=entry_price,
                sl_ticks=int(sl_ticks_calc),
                tp_ticks=0,
                tick_size=tick,
            )

            # Le DTC connector retourne tuple : (parent, tp, sl, fill)
            # Si tp non envoye, le slot 2 sera vide / ignore.
            if isinstance(result, tuple) and len(result) >= 4:
                parent_real, _tp_real, sl_real, fill_price = result[:4]
                if parent_real:
                    parent_cid = parent_real
                if sl_real:
                    sl_cid = sl_real
                try:
                    fill_price = float(fill_price) if fill_price else entry_price
                except (TypeError, ValueError):
                    fill_price = entry_price
                success = bool(parent_cid)
            elif isinstance(result, dict):
                success = bool(result.get("success", False))
                fill_price = float(result.get("fill_price", entry_price))
            else:
                success = bool(result)
                fill_price = entry_price

            return OrderResult(
                success=success,
                parent_cid=parent_cid,
                sl_cid=sl_cid,
                fill_price=fill_price,
                dry_run=False,
            )
        except Exception as e:  # noqa: BLE001
            return OrderResult(
                success=False,
                error_msg=f"DTC_EXCEPTION:{type(e).__name__}:{e}",
                dry_run=False,
            )

    def replace_sl(
        self,
        symbol: str,
        sl_cid: str,
        new_sl_price: float,
        direction: str,
        n_micros: int = 1,
    ) -> bool:
        """Cancel-replace SL pour trailing Dow pivots.

        Dry-run : log only.
        Prod : cancel le SL existant + send new SL STOP.
        """
        if self.dry_run or self.dtc is None:
            return True

        cancel_fn = getattr(self.dtc, "cancel_order", None)
        send_fn = getattr(self.dtc, "send_stop_order", None)
        if cancel_fn is None:
            return False
        try:
            cancel_fn(sl_cid, trade_account=self.cfg.TRADE_ACCOUNT)
        except Exception:
            return False
        if send_fn is None:
            # Pas de send_stop_order : best-effort cancel seul
            return True
        try:
            # Cote oppose SL = oppose direction
            side = 2 if direction == "long" else 1  # SELL si LONG / BUY si SHORT
            send_fn(
                symbol=symbol,
                side=side,
                quantity=n_micros,
                stop_price=new_sl_price,
                trade_account=self.cfg.TRADE_ACCOUNT,
            )
            return True
        except Exception:
            return False

    def cancel_brackets(self, parent_cid: str, sl_cid: str) -> bool:
        """Cancel les 2 ordres (parent + SL). Utilise pour close manual."""
        if self.dry_run or self.dtc is None:
            return True

        cancel_fn = getattr(self.dtc, "cancel_order", None)
        if cancel_fn is None:
            return False
        ok = True
        for cid in (parent_cid, sl_cid):
            if not cid:
                continue
            try:
                cancel_fn(cid, trade_account=self.cfg.TRADE_ACCOUNT)
            except Exception:
                ok = False
        return ok
