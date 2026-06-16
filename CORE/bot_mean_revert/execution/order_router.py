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
            if isinstance(result, tuple) and len(result) >= 4:
                parent_real, tp_real, sl_real, fill_price = result[:4]
                if parent_real:
                    parent_cid = parent_real
                if tp_real:
                    tp_cid = tp_real
                if sl_real:
                    sl_cid = sl_real
                # Fix bug position fantome 16/06 : DTC retourne parent_cid meme
                # quand bracket abort (parent NOT FILLED in 2s) avec fill_price=0.
                # Le bot appelait open_position alors qu'aucun ordre n'etait actif
                # sur Sim1 -> position fantome persistante. Fix : success EXIGE
                # fill_price > 0 (= confirmation parent fill effectif).
                fill_price_raw = fill_price
                try:
                    fill_price = float(fill_price) if fill_price else 0.0
                except (TypeError, ValueError):
                    fill_price = 0.0
                if fill_price <= 0 and parent_cid:
                    return OrderResult(
                        success=False,
                        parent_cid=parent_cid,
                        tp_cid=tp_cid, sl_cid=sl_cid,
                        fill_price=0.0,
                        error_msg=f"PARENT_NOT_FILLED_TIMEOUT (raw={fill_price_raw!r})",
                        dry_run=False,
                    )
                success = bool(parent_cid) and fill_price > 0
            elif isinstance(result, dict):
                success = bool(result.get("success", False))
                fill_price = float(result.get("fill_price", signal.entry_price))
            else:
                success = bool(result)
                fill_price = signal.entry_price
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
