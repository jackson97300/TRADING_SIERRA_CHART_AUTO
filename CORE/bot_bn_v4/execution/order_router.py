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
            # FIX 16/06 : reproduit bug Bot MR fix matin. JAMAIS bool(result)
            # comme fallback - tuple non-vide != fill reussi = position fantome.
            # Tuple len=3 (parent, tp, sl) sans fill = abort confirme cote DTC.
            parent_real, sl_real, fill_price = None, None, 0.0
            if isinstance(result, tuple) and len(result) >= 4:
                parent_real, _tp_real, sl_real, fill_price = result[:4]
            elif isinstance(result, tuple) and len(result) == 3:
                # Detection abort DTC : tp_cid="" + sl_cid="" => echec parent fill
                p, t, s = result[:3]
                if not p or (not t and not s):
                    return OrderResult(
                        success=False,
                        error_msg=f"DTC_PARENT_FILL_ABORT:tuple3_no_brackets",
                        dry_run=False,
                    )
                parent_real, sl_real = p, s
            elif isinstance(result, dict):
                fill_price = float(result.get("fill_price", 0.0))
                parent_real = result.get("parent_cid")
                sl_real = result.get("sl_cid")
            else:
                # Type non reconnu = abort (anti-pattern bool(result))
                return OrderResult(
                    success=False,
                    error_msg=f"DTC_UNKNOWN_RESULT_TYPE:{type(result).__name__}",
                    dry_run=False,
                )

            if parent_real:
                parent_cid = parent_real
            if sl_real:
                sl_cid = sl_real

            # Verification fill_price reel via get_last_fill_price (fix Bot MR 16/06)
            try:
                fp = float(fill_price) if fill_price else 0.0
            except (TypeError, ValueError):
                fp = 0.0
            if fp <= 0 and parent_cid and hasattr(self.dtc, "get_last_fill_price"):
                try:
                    fp = float(self.dtc.get_last_fill_price(parent_cid) or 0.0)
                except Exception:  # noqa: BLE001
                    fp = 0.0

            # Success exige fill_price > 0 confirme (anti position fantome)
            if fp <= 0:
                return OrderResult(
                    success=False,
                    error_msg=f"DTC_NO_FILL_CONFIRMED:parent={parent_cid}",
                    dry_run=False,
                )

            return OrderResult(
                success=True,
                parent_cid=parent_cid,
                sl_cid=sl_cid,
                fill_price=fp,
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
        parent_cid_link: str = "",
    ) -> str:
        """Cancel-replace SL pour trailing Dow pivots.

        FIX 17/06 Jackson zero-dette : retourne maintenant le NOUVEAU sl_cid
        (au lieu de bool). Caller (bot_bn_v4/main.py) doit utiliser ce CID pour
        update fill_listener._cid_index + pos["sl_cid"] dans le store.

        Avant ce fix : `send_stop_order` n'existait pas, `replace_sl` cancellait
        seulement → position NUE pendant trailing → perte non bornee (bug latent
        non manifeste car BN V4 grade A++ = 0 trades en 5j paper).

        Dry-run : retourne un CID synthetique pour traceability tests.
        Prod : cancel ancien + send new STOP via dtc.send_stop_order.

        Args:
            symbol, sl_cid, new_sl_price, direction, n_micros : signature standard.
            parent_cid_link : optionnel pour traceability log.

        Returns:
            new_sl_cid : nouveau ClientOrderID si succes complet (cancel + send OK).
            Chaine vide si :
              - dtc indisponible (None)
              - cancel_order absent (legacy DTC)
              - send_stop_order absent (legacy DTC sans patch 17/06)
              - exception cancel ou send
            Le caller doit ABSOLUMENT verifier le retour. Si vide :
              - Soit position nue (cancel OK, send fail) → ALERT MAJEUR
              - Soit operation no-op (dtc down) → degradé acceptable
        """
        if self.dry_run:
            # Synthetic CID for tests + dry-run traceability
            import uuid as _uuid
            return f"BOTBN_TRAIL_SL_{_uuid.uuid4().hex[:8]}"
        if self.dtc is None:
            return ""

        cancel_fn = getattr(self.dtc, "cancel_order", None)
        send_fn = getattr(self.dtc, "send_stop_order", None)
        if cancel_fn is None:
            return ""
        # 1. Cancel ancien SL — FIX 17/06 review R1 BLOQUANT : require_sid=True.
        # Sans ce flag, SC ignore silencieusement le cancel si SID pas encore
        # propage (race ~200ms post-fill ORDER_UPDATE) → on envoie nouveau SL
        # → 2 SL actifs sur position 1 micro → orphan garanti.
        # Avec require_sid=True : si SID absent, cancel echoue → on return "" →
        # send_stop_order NON appele → ancien SL reste actif (protection legacy
        # preservee, plus protectrice que le nouveau dans le pire cas).
        try:
            cancel_ok = cancel_fn(
                sl_cid, trade_account=self.cfg.TRADE_ACCOUNT, require_sid=True,
            )
            if not cancel_ok:
                # SID pas dispo → SC ignorerait. Ancien SL reste actif.
                # Caller distingue ce mode via emit dedie (cf main.py).
                return ""
        except Exception:
            return ""
        # 2. Send nouveau SL via send_stop_order (ajoute dans le meme PR)
        if send_fn is None:
            # Legacy DTC sans patch 17/06 : position nue ! Caller doit alert.
            return ""
        try:
            # Cote oppose SL = oppose direction (SELL pour LONG, BUY pour SHORT)
            side = 2 if direction == "long" else 1
            new_sl_cid = send_fn(
                symbol=symbol,
                side=side,
                quantity=n_micros,
                stop_price=new_sl_price,
                trade_account=self.cfg.TRADE_ACCOUNT,
                parent_cid_link=parent_cid_link,
            )
            return new_sl_cid or ""
        except Exception:
            return ""

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
