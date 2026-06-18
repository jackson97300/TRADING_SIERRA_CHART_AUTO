"""Order router Bot 1 v2 - DTC wrapper avec dry-run mode.

Modes :
  - dry_run=True : log seul (paper simulation pure, pas de DTC)
  - dry_run=False : send bracket DTC (production paper Sim2)

Respecte rules orphan-prevention.md :
  - TradeAccount explicite Sim2 (PAS default Sim3)
  - ClientOrderID unique pour chaque envoi
  - OCO manuel (3 ordres Type 208 separes, pas Type 206)
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

from CORE.bot1_v2.cluster import ClusterDecision
from CORE.bot1_v2.config import Bot1V2Config


@dataclass(frozen=True)
class OrderResult:
    """Resultat envoi ordre."""
    success: bool
    parent_cid: str = ""
    tp_cid: str = ""
    sl_cid: str = ""
    fill_price: float = 0.0
    error_msg: str = ""
    dry_run: bool = False


class OrderRouter:
    """Routeur d'ordres via DTC connector existant.

    En mode dry_run, simule le fill au prix d'entree (paper backtest pur).
    """

    def __init__(
        self,
        cfg: Bot1V2Config,
        dry_run: bool = True,
        dtc_connector=None,  # CORE/dtc_connector.py instance (optional)
    ):
        self.cfg = cfg
        self.dry_run = dry_run
        self.dtc = dtc_connector  # None en dry_run

    def _make_cid(self, prefix: str) -> str:
        """ClientOrderID unique : BOT1V2_{prefix}_{shorthash}."""
        short = uuid.uuid4().hex[:8]
        return f"BOT1V2_{prefix}_{short}"

    def send_bracket(self, decision: ClusterDecision) -> OrderResult:
        """Envoie un bracket (parent MARKET + TP LIMIT + SL STOP).

        Args:
            decision : ClusterDecision tradable

        Returns:
            OrderResult avec CIDs + fill_price.
        """
        if not decision.tradable:
            return OrderResult(
                success=False,
                error_msg=f"DECISION_NOT_TRADABLE:{decision.skip_reason}",
                dry_run=self.dry_run,
            )

        parent_cid = self._make_cid("P")
        tp_cid = self._make_cid("TP")
        sl_cid = self._make_cid("SL")

        if self.dry_run:
            # Simulation pure : fill au prix d'entree
            return OrderResult(
                success=True,
                parent_cid=parent_cid,
                tp_cid=tp_cid,
                sl_cid=sl_cid,
                fill_price=decision.entry_price,
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
            # send_market_order legacy signature (BOT/dtc_connector.py:268) :
            #   send_market_order(symbol, side: int, quantity, sl_price, tp_price,
            #                     trade_account, signal_ref_price=0,
            #                     sl_ticks=0, tp_ticks=0, tick_size=0.25,
            #                     auto_reprice_threshold_ticks=5) -> tuple
            # Mapping direction str -> side int (1=BUY, 2=SELL)
            side = 1 if decision.direction == "LONG" else 2
            send_fn = getattr(self.dtc, "send_market_order", None)
            if send_fn is None:
                return OrderResult(
                    success=False,
                    error_msg="DTC_NO_SEND_MARKET_ORDER",
                    dry_run=False,
                )
            # tick_size par symbole
            try:
                from CORE.constants import get_tick_size
            except ImportError:
                from constants import get_tick_size  # type: ignore
            tick = get_tick_size(decision.symbol)

            result = send_fn(
                symbol=decision.symbol,
                side=side,
                quantity=decision.n_micros,
                sl_price=decision.sl_price,
                tp_price=decision.tp_price,
                trade_account=self.cfg.TRADE_ACCOUNT,  # Sim2 explicite
                signal_ref_price=decision.entry_price,
                sl_ticks=decision.sl_ticks,
                tp_ticks=decision.tp_ticks,
                tick_size=tick,
            )
            # FIX 17/06 (Jackson) : send_market_order legacy retourne tuple
            #   (parent_cid_real, tp_cid_real, sl_cid_real) — 3 elements.
            # AVANT ce fix : condition len(result) >= 4 jamais match → on tombait
            # dans le else final, success = bool(tuple_non_vide) = True meme si
            # send_market_order avait retourne ("", "", "") en abort. Et surtout
            # parent_cid / tp_cid / sl_cid restaient les CIDs GENERIC `BOT1V2_*`
            # generes par self._make_cid() au lieu des vrais CIDs `MIA_*` envoyes
            # par send_market_order. Resultat : paper_tracker ne detectait jamais
            # les TP/SL fills (CIDs mismatch DTC connector → Bot 1 v2 store).
            # Backward compat : on garde tolerance >= 4 si signature legacy evolue.
            # fill_price recupere via get_last_fill_price() (12/05 FIX persistance).
            if isinstance(result, tuple) and len(result) >= 3:
                parent_real = result[0] if result[0] else ""
                tp_real = result[1] if result[1] else ""
                sl_real = result[2] if result[2] else ""
                if parent_real:
                    parent_cid = parent_real
                if tp_real:
                    tp_cid = tp_real
                if sl_real:
                    sl_cid = sl_real
                # fill_price : si 4eme element (legacy futur), sinon get_last_fill_price
                if len(result) >= 4 and result[3]:
                    try:
                        fill_price = float(result[3])
                    except (TypeError, ValueError):
                        fill_price = decision.entry_price
                else:
                    fill_price = decision.entry_price
                    get_fill_fn = getattr(self.dtc, "get_last_fill_price", None)
                    if get_fill_fn is not None and parent_real:
                        try:
                            fp = get_fill_fn(parent_real)
                            if fp and float(fp) > 0:
                                fill_price = float(fp)
                        except Exception:  # noqa: BLE001
                            pass
                # success = parent_real non vide (abort = ("", "", "") → False)
                success = bool(parent_real)
            elif isinstance(result, dict):
                success = bool(result.get("success", False))
                fill_price = float(result.get("fill_price", decision.entry_price))
            else:
                success = bool(result)
                fill_price = decision.entry_price
            return OrderResult(
                success=success,
                parent_cid=parent_cid,
                tp_cid=tp_cid,
                sl_cid=sl_cid,
                fill_price=fill_price,
                dry_run=False,
            )
        except Exception as e:
            return OrderResult(
                success=False,
                error_msg=f"DTC_EXCEPTION:{type(e).__name__}:{e}",
                dry_run=False,
            )

    def cancel_brackets(self, parent_cid: str, tp_cid: str, sl_cid: str) -> bool:
        """Cancel les 3 ordres bracket (utilise pour close manual)."""
        if self.dry_run or self.dtc is None:
            return True  # no-op en dry-run

        cancel_fn = getattr(self.dtc, "cancel_order", None)
        if cancel_fn is None:
            return False
        ok = True
        for cid in (parent_cid, tp_cid, sl_cid):
            if not cid:
                continue
            try:
                # Sim2 explicite (PAS default Sim3 = piege)
                cancel_fn(cid, trade_account=self.cfg.TRADE_ACCOUNT)
            except Exception:
                ok = False
        return ok
