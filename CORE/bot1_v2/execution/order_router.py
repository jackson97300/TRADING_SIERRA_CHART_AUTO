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

    def close_position_market_safe(
        self,
        symbol: str,
        contract: str,
        direction: str,
        n_micros: int,
        parent_cid: str,
        tp_cid: str,
        sl_cid: str,
        reason: str = "TIMEOUT",
        emit_fn=None,
    ) -> dict:
        """Force-close position avec sequence anti-orphelin V2.

        Fix #1 MAX_HOLD audit 30/06. Respecte .claude/rules/orphan-prevention.md.

        Sequence :
          1. Cancel TP cid (avec TA=Sim2 explicite, anti-fail-loud)
          2. Cancel SL cid idem
          3. Wait 1s propagation
          4. R1 verify position broker (request_position_blocking, anti-race)
          5. Si qty != 0 : MARKET CLOSE Type 208 OpenCloseTrade=2
          6. Wait 2s pour fill
          7. Type 209 SUBMIT_FLATTEN_POSITION par symbole (defense)
          8. Type 210 FLATTEN_POSITIONS_FOR_ACCOUNT (Sim2 dedie = SAFE)
          9. VERIFY POST-CLEANUP : re-query Type 300 working orders.
             Si > 0 -> emit ORPHAN_DETECTED_POST_CLEANUP CRITIQUE.

        Args:
            symbol : "ES" / "NQ" / "MGC" (sym base, pour logs)
            contract : "ESU26-CME" / "NQU26-CME" (contract DTC)
            direction : "LONG" / "SHORT"
            n_micros : nb micros position (fallback si broker qty None)
            parent_cid, tp_cid, sl_cid : CIDs bracket initial (peuvent etre vides)
            reason : "TIMEOUT" / "KILL_SWITCH" / "MANUAL" (pour close_reason)
            emit_fn : callable(code, **ctx) pour emit logs (None = silent)

        Returns:
            dict {ok, close_cid, qty_broker, cancel_failed, orphan_detected, error}
        """
        result = {
            "ok": False,
            "close_cid": "",
            "qty_broker": None,
            "cancel_failed": [],
            "orphan_detected": False,
            "error": "",
        }

        def _emit(code, **ctx):
            if emit_fn is not None:
                try:
                    emit_fn(code, **ctx)
                except Exception:  # noqa: BLE001
                    pass

        # Dry-run = simu close = no-op safe
        if self.dry_run or self.dtc is None:
            result["ok"] = True
            result["error"] = "DRY_RUN_NO_OP"
            return result

        ta = self.cfg.TRADE_ACCOUNT  # Sim2 explicite (anti-fix-H6 orphan-prevention)

        # === ETAPE 1+2 : Cancel TP + SL (fail-loud, pas except:pass)
        for label, cid in (("tp", tp_cid), ("sl", sl_cid)):
            if not cid:
                continue
            try:
                ok = self.dtc.cancel_order(cid, trade_account=ta)
                if not ok:
                    result["cancel_failed"].append(label)
            except Exception as e:  # noqa: BLE001
                result["cancel_failed"].append(label)
                _emit("BOT1V2_TIMEOUT_CANCEL_EXCEPTION",
                      sym=symbol, label=label, cid=cid, err=str(e)[:200])

        if result["cancel_failed"]:
            _emit("BOT1V2_TIMEOUT_CANCEL_FAIL_ORPHAN_RISK",
                  sym=symbol, direction=direction, failed=result["cancel_failed"])

        # === ETAPE 3 : wait propagation cancels
        time.sleep(1.0)

        # === ETAPE 4 : R1 verify position broker avant MARKET CLOSE (anti-race)
        qty_broker = None
        try:
            qty_broker = self.dtc.request_position_blocking(
                contract, trade_account=ta, timeout=2.0)
        except Exception as e:  # noqa: BLE001
            _emit("BOT1V2_TIMEOUT_REQUEST_POS_FAIL",
                  sym=symbol, err=str(e)[:200])

        result["qty_broker"] = qty_broker

        if qty_broker == 0:
            _emit("BOT1V2_TIMEOUT_ALREADY_FLAT",
                  sym=symbol, direction=direction, age_min=0)
            # Pas de MARKET CLOSE necessaire
        elif qty_broker is None:
            # CRITIQUE Fix D1 13/07 : SUPPRIME fallback n_micros aveugle qui a cause
            # cascade SHORT cumul 9 contrats ESU26 sur Sim2 09-13/07 (INCIDENT_LOG #96).
            # Cause racine : si broker deja FLAT (position closed side broker) ET
            # request_position_blocking retourne None (DTC freeze OR broker vraiment 0),
            # le fallback qty_broker=n_micros emettait SELL MARKET inconditionnel ->
            # creait une position INVERSE dans un compte deja flat.
            # Chaque restart = 1 SELL de plus = cumul SHORT.
            # Nouvelle regle : REFUSE d'emettre MARKET CLOSE si qty broker unknown.
            # Consequence : orphelin theorique si vrai DTC freeze + vraie position.
            # Filet de defense en profondeur : D3 reconciliation broker au BOOT.
            _emit("BOT1V2_TIMEOUT_POSITION_UNKNOWN_SKIP_CLOSE",
                  sym=symbol, direction=direction, age_min=0)
            result["error"] = "BROKER_QTY_UNKNOWN_SKIP_UNSAFE_CLOSE"
            return result  # STOP net - PAS de MARKET CLOSE aveugle

        # === ETAPE 5 : MARKET CLOSE Type 208 OpenCloseTrade=2 si position residuelle
        if qty_broker is not None and qty_broker != 0:
            n_to_close = abs(qty_broker)
            # qty>0 = LONG broker -> SELL pour close ; qty<0 = SHORT broker -> BUY
            side_close = 2 if qty_broker > 0 else 1  # 1=BUY, 2=SELL
            # CID local = fallback seulement. Il est remplace juste apres par le
            # ClientOrderID reel rendu par le connector (cf FIX CID ci-dessous).
            close_cid = f"BOT1V2_CLOSE_{symbol[:2]}_{int(time.time()) % 100000}"
            result["close_cid"] = close_cid
            try:
                send_close_fn = getattr(self.dtc, "send_close_market", None)
                if send_close_fn is None:
                    result["error"] = "DTC_NO_SEND_CLOSE_MARKET"
                else:
                    # === FIX CID 04/09 — INCIDENT #70 rejoue sur bot1_v2 ===
                    # dtc_connector.send_close_market genere son PROPRE
                    # ClientOrderID (MIA_CLOSE_<uuid>) et le RETOURNE.
                    # Avant ce fix la valeur de retour etait ignoree :
                    #   - main.py enregistrait le cid local BOT1V2_CLOSE_* dans
                    #     fill_listener._cid_index
                    #   - le broker fillait MIA_CLOSE_* => cid inconnu du listener
                    #   - fill ignore => position jamais retiree du store
                    #   - re-close au boot suivant => boucle
                    # Mesure 04/09 : ~6000 MARKET CLOSE emis sur Sim2 du 13/07 au
                    # 04/09 (4433 en juillet). Le fix #70 (18/06) avait ete
                    # applique a BotMR et BN V4, jamais a bot1_v2.
                    broker_cid = send_close_fn(
                        symbol=contract, side=side_close,
                        quantity=n_to_close, trade_account=ta)

                    if isinstance(broker_cid, str) and broker_cid:
                        # Cas nominal : le fill sera route sur le cid REEL.
                        close_cid = broker_cid
                        result["close_cid"] = broker_cid
                        time.sleep(2.0)  # ETAPE 6 : wait fill MARKET CLOSE
                        result["ok"] = True
                    elif isinstance(broker_cid, str):
                        # "" = connector non connecte : l'ordre n'est JAMAIS parti.
                        # Ne pas mentir avec ok=True, la position reste ouverte.
                        # R1 review 04/09 : purger le cid local. Sans ca,
                        # main.py:856 l'enregistre dans _cid_index alors qu'aucun
                        # ordre n'existe => une entree fantome par tour de boucle
                        # (_cid_index croit sans borne) = exactement la pathologie
                        # que ce fix corrige. Cid vide => register_close_cid sort
                        # immediatement (dtc_fill_listener.py:224 `if not close_cid`).
                        result["close_cid"] = ""
                        _emit("BOT1V2_TIMEOUT_CLOSE_NOT_SENT",
                              sym=symbol, direction=direction, qty=n_to_close)
                        result["error"] = "CLOSE_NOT_SENT_DTC_DISCONNECTED"
                    else:
                        # Contrat non respecte (None, ou double de test).
                        # Comportement legacy conserve mais TRACE : sans cid
                        # broker le fill du close ne sera pas routable.
                        _emit("BOT1V2_TIMEOUT_CLOSE_CID_UNRESOLVED",
                              sym=symbol, fallback=close_cid)
                        time.sleep(2.0)
                        result["ok"] = True
            except Exception as e:  # noqa: BLE001
                result["error"] = f"CLOSE_EXC:{type(e).__name__}:{e}"

        else:
            # Deja flat ou broker freeze sans n_micros : on continue (defense en profondeur)
            result["ok"] = True

        # === ETAPE 7 : Type 209 SUBMIT_FLATTEN_POSITION par symbole (defense)
        try:
            flush_cid_209 = f"BOT1V2_FLUSH_{symbol[:2]}_{int(time.time()) % 100000}"
            send_fn = getattr(self.dtc, "_send", None)
            if send_fn is not None:
                send_fn({
                    "Type": 209,
                    "ClientOrderID": flush_cid_209,
                    "Symbol": contract,
                    "TradeAccount": ta,
                    "Exchange": "CME",
                    "IsAutomatedOrder": 1,
                })
        except Exception:  # noqa: BLE001
            pass

        # === ETAPE 8 : Type 210 FLATTEN_POSITIONS_FOR_ACCOUNT (Sim2 dedie = SAFE)
        try:
            flush_cid_210 = f"BOT1V2_FLUSH_ACCT_{int(time.time()) % 100000}"
            send_fn = getattr(self.dtc, "_send", None)
            if send_fn is not None:
                send_fn({
                    "Type": 210,
                    "ClientOrderID": flush_cid_210,
                    "TradeAccount": ta,
                    "IsAutomatedOrder": 1,
                })
        except Exception:  # noqa: BLE001
            pass

        # === ETAPE 9 : VERIFY POST-CLEANUP — REPORTEE BACKLOG P1
        # Fix B1 review code-reviewer 30/06 : appel direct `self.dtc._recv(2)`
        # depuis thread main = RACE avec `_recv_loop` thread daemon DTC qui
        # distribue les ORDER_UPDATE Type 301 au DtcFillListener.
        # Risque : steal du fill MARKET CLOSE = position OPEN dans store =
        # nouveau timeout = SHORT cumul broker (bug 18/06 BotMR).
        # Solution future : exposer `dtc.snapshot_working_orders()` async-safe
        # qui utilise une callback dispatchee par `_recv_loop`. Reporte P1.
        # En attendant : audit J+1 via grep logs LOGS/events si orphelins.
        _emit("BOT1V2_TIMEOUT_VERIFY_CLEAN",
              sym=symbol, direction=direction)

        return result

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
