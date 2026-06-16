"""Order router Bot MR - fork minimal Bot 1 v2 OrderRouter.

Differences vs Bot 1 v2 :
  - ClientName : MIA_BotMR (vs MIA_Bot1V2)
  - ClientOrderID prefix : BOTMR_ (vs BOT1V2_)
  - TradeAccount : Sim1 explicite (vs Sim2)

Logique DTC + dry-run identique : reutilise OrderRouter parent.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional

from CORE.bot1_v2.execution.order_router import OrderResult, OrderRouter as Bot1V2OrderRouter
from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.signal_engine import SignalResult


class OrderRouter(Bot1V2OrderRouter):
    """OrderRouter Bot MR - sub-class avec ClientOrderID prefix BOTMR_.

    Reutilise toute la logique DTC bracket (send_market_order + dry-run sim)
    de Bot 1 v2. Override seulement le prefix CID + accepte SignalResult au
    lieu de ClusterDecision (interface differente, meme structure SL/TP).
    """

    def __init__(
        self,
        cfg: BotMRConfig,
        dry_run: bool = True,
        dtc_connector=None,
    ):
        # Parent attend Bot1V2Config, mais utilise seulement TRADE_ACCOUNT.
        # On passe self.cfg via attribut puis on duck-type.
        self.cfg = cfg
        self.dry_run = dry_run
        self.dtc = dtc_connector

    def _make_cid(self, prefix: str) -> str:
        """ClientOrderID unique : BOTMR_{prefix}_{shorthash}."""
        short = uuid.uuid4().hex[:8]
        return f"BOTMR_{prefix}_{short}"

    def send_bracket_signal(self, signal: SignalResult, symbol: str, n_micros: int) -> OrderResult:
        """Envoie un bracket pour un SignalResult mean revert.

        Wrap autour de send_bracket parent avec adapter SignalResult -> ClusterDecision-like.
        """
        if not signal.tradable:
            return OrderResult(
                success=False,
                error_msg=f"SIGNAL_NOT_TRADABLE:{signal.skip_reason}",
                dry_run=self.dry_run,
            )

        parent_cid = self._make_cid("P")
        tp_cid = self._make_cid("TP")
        sl_cid = self._make_cid("SL")

        if self.dry_run:
            return OrderResult(
                success=True,
                parent_cid=parent_cid,
                tp_cid=tp_cid,
                sl_cid=sl_cid,
                fill_price=signal.entry_price,
                dry_run=True,
            )

        # Mode prod : appel DTC connector existant
        if self.dtc is None:
            return OrderResult(
                success=False,
                error_msg="DTC_CONNECTOR_NULL_IN_PROD",
                dry_run=False,
            )

        try:
            side = 1 if signal.direction == "LONG" else 2
            send_fn = getattr(self.dtc, "send_market_order", None)
            if send_fn is None:
                return OrderResult(
                    success=False,
                    error_msg="DTC_NO_SEND_MARKET_ORDER",
                    dry_run=False,
                )
            try:
                from CORE.constants import get_tick_size
            except ImportError:  # pragma: no cover
                from constants import get_tick_size  # type: ignore
            tick = get_tick_size(symbol)

            result = send_fn(
                symbol=symbol,
                side=side,
                quantity=n_micros,
                sl_price=signal.sl_price,
                tp_price=signal.tp_price,
                trade_account=self.cfg.TRADE_ACCOUNT,  # Sim1 explicite
                signal_ref_price=signal.entry_price,
                sl_ticks=signal.sl_ticks,
                tp_ticks=signal.tp_ticks,
                tick_size=tick,
            )
            # Fix 16/06 bug #1 : legacy send_market_order retourne tuple len=3
            # (parent_id, tp_cid, sl_cid). Mon premier patch testait len>=4 -> JAMAIS
            # pris, branche `else success = bool(result)` toujours True avec tuple
            # non vide -> position fantome systematique sur abort DTC.
            # Fix : gerer tuple len>=3 + recuperer fill_price via get_last_fill_price().
            # Si tp_cid="" ET sl_cid="" -> signal d'abort (l. 545 dtc_connector.py).
            if isinstance(result, tuple) and len(result) >= 3:
                parent_real = result[0]
                tp_real = result[1] if len(result) > 1 else ""
                sl_real = result[2] if len(result) > 2 else ""
                if parent_real:
                    parent_cid = parent_real
                if tp_real:
                    tp_cid = tp_real
                if sl_real:
                    sl_cid = sl_real
                # Recupere fill_price reel depuis _last_fill_prices du DTC connector
                fill_price = 0.0
                try:
                    getter = getattr(self.dtc, "get_last_fill_price", None)
                    if getter is not None and parent_cid:
                        fill_price = float(getter(parent_cid) or 0.0)
                except (TypeError, ValueError):
                    fill_price = 0.0
                # Detection abort : tp_cid="" ET sl_cid="" (signal legacy abort, l.545)
                abort_signal = (tp_real == "" and sl_real == "")
                if abort_signal or fill_price <= 0:
                    return OrderResult(
                        success=False,
                        parent_cid=parent_cid,
                        tp_cid=tp_cid, sl_cid=sl_cid,
                        fill_price=0.0,
                        error_msg=f"PARENT_NOT_FILLED_TIMEOUT (abort={abort_signal}, fill={fill_price})",
                        dry_run=False,
                    )
                success = True
            elif isinstance(result, dict):
                success = bool(result.get("success", False))
                fill_price = float(result.get("fill_price", 0.0))
                if fill_price <= 0:
                    success = False
            else:
                # Cas degradede : on n'a pas pu confirmer un fill, fail-closed
                success = False
                fill_price = 0.0
            return OrderResult(
                success=success,
                parent_cid=parent_cid,
                tp_cid=tp_cid,
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
