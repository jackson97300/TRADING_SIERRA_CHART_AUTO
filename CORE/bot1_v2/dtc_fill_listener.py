"""Bot 1 v2 DTC fill listener — ferme positions sur ORDER_UPDATE Type 301.

PROBLEME RESOLU (17/06/2026, Jackson + 2 agents Plan + code-reviewer) :
    Bot 1 v2 tradait sans ecouter les fills DTC. Quand SC envoyait
    ORDER_UPDATE Type 301 (status=7 Filled) pour un TP/SL, le bot
    ignorait l'event → position restait "OPEN" cote dashboard MIA
    paper_tracker indefiniment, MFE/PnL inexact.

    Trade reel observe le 17/06 17:01-17:02 UTC (ES SHORT Sim2) :
      - 17:01:07 parent fillee + bracket envoye
      - 17:02:06 SC fills TP @ 7578.25 (gain +9t = $11.25)
      - 17:02:08 OCO auto cancel SL (OCO_ORPHAN_DETECTED CRITIQUE)
      - Dashboard MIA : encore OPEN avec MFE +263t (FAUX)

SOLUTION (pattern Bot 3 v3 + BN V4 valides en prod) :
    Listener `handle_order_update(msg, cid)` enregistre dans
    `dtc.on_order_update`. Au fill TP/SL (status=7), lookup cid dans
    `_cid_index` → calcul PnL → appelle `state_bridge.close_position()`
    + `position_store.close_position()`.

REGLES CRITIQUES respectees :
    - .claude/rules/orphan-prevention.md H6 : filtre TradeAccount obligatoire
    - bn_v4_paper.py:799 GUARD #2 : fill_price <= 0 refuse close (ghost trade)
    - Thread safety : lock sur _cid_index + close (callback execute dans recv_loop)
    - Idempotence : close 2x → no-op
    - Anti-pattern silent fallback : emit BOT1V2_FILL_* dans tous les cas
    - OCO auto-cancel NE PAS RE-FAIRE (DTC connector gere deja via register_oco_pair)
"""
from __future__ import annotations

import threading
import time
from typing import Optional

try:
    from CORE.bot1_v2.config import Bot1V2Config
    from CORE.bot1_v2.state.position_store import PositionStore
    from CORE.bot1_v2.state_bridge import StateBridge
    from CORE.logging_v2 import get_logger as _get_v2_logger
except ImportError:  # pragma: no cover
    from bot1_v2.config import Bot1V2Config  # type: ignore
    from bot1_v2.state.position_store import PositionStore  # type: ignore
    from bot1_v2.state_bridge import StateBridge  # type: ignore
    from logging_v2 import get_logger as _get_v2_logger  # type: ignore


_log = _get_v2_logger("bot1_v2", process="bot1_v2")


# Bot 1 v2 trade en MICRO (cf main.py:174-182).
# ES MICRO (MES) : tick=0.25, $1.25/tick (=$5/point)
# NQ MICRO (MNQ) : tick=0.25, $0.50/tick (=$2/point)
# MGC Micro Gold : tick=0.10, $1.00/tick
def _micro_tick_specs(symbol: str) -> tuple:
    """Retourne (tick_size, usd_per_tick) MICRO pour le symbole."""
    sym = symbol.upper()
    if sym == "ES":
        return 0.25, 1.25
    if sym == "NQ":
        return 0.25, 0.50
    if sym == "MGC":
        return 0.10, 1.00
    return 0.25, 1.25  # default ES MICRO


class DtcFillListener:
    """Ecoute ORDER_UPDATE Type 301 DTC + ferme positions Bot 1 v2 sur fill TP/SL.

    Pattern Bot 3 v3 (paper_v2.py:557) + BN V4 (bn_v4_paper.py:749).

    Args:
        cfg : Bot1V2Config (lit TRADE_ACCOUNT pour filtre)
        store : PositionStore (close_position + has_position)
        state_bridge : StateBridge (close_position pour dashboard)
        on_close_callback : optionnel — appele apres close avec (sym, pnl_usd).
            Utilise par main.py pour `daily_gate.register_close(pnl_usd)`.

    Usage :
        listener = DtcFillListener(cfg, store, state_bridge, on_close_callback)
        # Apres send_bracket success :
        listener.register_bracket(
            sym, signal_id, direction, entry_price, sl_price, tp_price,
            sl_ticks, tp_ticks, n_micros, parent_cid, tp_cid, sl_cid,
        )
        # Hook DTC :
        dtc.on_order_update = listener.handle_order_update
    """

    def __init__(
        self,
        cfg: Bot1V2Config,
        store: PositionStore,
        state_bridge: StateBridge,
        on_close_callback=None,
        bot_id: str = "bot1v2",
    ):
        """Args:
            bot_id: identifiant du bot ("bot1v2"/"bot_mr"/"bot_bn_v4") pour
                    code log MIA_FILL_* generique cross-bot. Permet audit J+1
                    grep MIA_DTC_FILL_TP pour voir tous les fills 3 bots.
        """
        self.cfg = cfg
        self.store = store
        self.state_bridge = state_bridge
        self.on_close_callback = on_close_callback
        self.bot_id = bot_id
        # cid -> {sym, kind: "parent"|"tp"|"sl", signal_id, ...details position...}
        self._cid_index: dict = {}
        self._lock = threading.Lock()
        # Persistance : si store load() recupere des positions au boot, on
        # reconstruit l'index depuis les parent_cid/tp_cid/sl_cid stockes.
        self._rebuild_from_store()

    def _rebuild_from_store(self) -> None:
        """Recovery boot : reconstruit _cid_index depuis store.positions.

        Cas : si Bot 1 v2 crashe entre send_bracket et le TP fill, au restart
        store.load() a recupere positions OPEN. Sans rebuild, le listener n'a
        pas de mapping cid → sym → fill ignore silencieux.

        FIX 17/06 review code-reviewer BLOQUANT 2 : reinjecte aussi entry_price
        + direction + n_micros + sl/tp_price + ticks → sinon PnL au prochain
        fill = ghost geant (entry_price=0 → 7578 * 1.25 = ~$9472 au lieu de $11).
        """
        with self._lock:
            for sym, pos in self.store.positions.items():
                parent_cid = pos.get("parent_cid")
                tp_cid = pos.get("tp_cid")
                sl_cid = pos.get("sl_cid")
                ctx_recov = {
                    "sym": sym,
                    "signal_id": pos.get("signal_id", ""),
                    "direction": pos.get("direction", "LONG"),
                    "entry_price": float(pos.get("entry_price", 0.0)),
                    "sl_price": float(pos.get("sl_price", 0.0)),
                    "tp_price": float(pos.get("tp_price", 0.0)),
                    "sl_ticks": int(pos.get("sl_ticks", 0)),
                    "tp_ticks": int(pos.get("tp_ticks", 0)),
                    "n_micros": int(pos.get("n_micros", 1)),
                    "ts_open": float(pos.get("entry_ts", 0)) / 1000.0,
                }
                for cid, kind in (
                    (parent_cid, "parent"),
                    (tp_cid, "tp"),
                    (sl_cid, "sl"),
                ):
                    if cid:
                        self._cid_index[cid] = {**ctx_recov, "kind": kind}

    def register_bracket(
        self,
        sym: str,
        signal_id: str,
        direction: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        sl_ticks: int,
        tp_ticks: int,
        n_micros: int,
        parent_cid: str,
        tp_cid: str,
        sl_cid: str,
    ) -> None:
        """Enregistre les CIDs DTC reels d'un bracket fraichement envoye.

        Doit etre appele juste apres OrderRouter.send_bracket() succes.
        """
        with self._lock:
            ctx = {
                "sym": sym, "signal_id": signal_id,
                "direction": direction,
                "entry_price": float(entry_price),
                "sl_price": float(sl_price),
                "tp_price": float(tp_price),
                "sl_ticks": int(sl_ticks),
                "tp_ticks": int(tp_ticks),
                "n_micros": int(n_micros),
                "ts_open": time.time(),
            }
            if parent_cid:
                self._cid_index[parent_cid] = {**ctx, "kind": "parent"}
            if tp_cid:
                self._cid_index[tp_cid] = {**ctx, "kind": "tp"}
            if sl_cid:
                self._cid_index[sl_cid] = {**ctx, "kind": "sl"}

    def handle_order_update(self, msg: dict) -> None:
        """Callback DTC : appele depuis dtc_connector._handle_order_update.

        Filtres :
          1. TradeAccount doit matcher cfg.TRADE_ACCOUNT (sinon = autre bot)
          2. ClientOrderID doit etre dans _cid_index (sinon = pas notre ordre)
          3. OrderStatus doit etre 7 (Filled). 2 (Open) / 4 (Working) → ignore.
          4. fill_price > 0 (GUARD #2 ghost trade $59542 BN V4)

        Try/except englobant pour ne JAMAIS crasher _recv_loop DTC.
        """
        try:
            self._handle_order_update_impl(msg)
        except Exception as e:  # noqa: BLE001
            self._emit_pair(
                "BOT1V2_FILL_LISTENER_EXCEPTION",
                "MIA_FILL_LISTENER_EXCEPTION",
                err=f"{type(e).__name__}:{str(e)[:200]}",
            )

    def _handle_order_update_impl(self, msg: dict) -> None:
        if not isinstance(msg, dict):
            return
        # 1. Filtre TradeAccount (anti-pattern orphan-prevention H6)
        msg_ta = str(msg.get("TradeAccount", "") or "")
        if msg_ta and msg_ta != self.cfg.TRADE_ACCOUNT:
            return
        # 2. Lookup CID
        cid = str(msg.get("ClientOrderID", "") or "")
        if not cid:
            return
        with self._lock:
            entry = self._cid_index.get(cid)
        if entry is None:
            return  # pas notre ordre
        sym = entry["sym"]
        kind = entry["kind"]
        signal_id = entry.get("signal_id", "")
        # 3. Filtre OrderStatus = 7 (Filled). 2=Open, 4=Working → ignore.
        try:
            order_status = int(msg.get("OrderStatus", 0))
        except (TypeError, ValueError):
            order_status = 0
        if order_status != 7:
            return
        # 4. Parent fill = ouverture, position deja register. Rien a faire.
        if kind == "parent":
            return
        # 5. Fill price (LastFillPrice prioritaire, sinon AverageFillPrice)
        try:
            fill_price = float(msg.get("LastFillPrice", 0)) or float(
                msg.get("AverageFillPrice", 0)
            )
        except (TypeError, ValueError):
            fill_price = 0.0
        # GUARD #2 (incident ghost trade $59542 24/05 BN V4)
        if fill_price <= 0:
            self._emit_pair(
                "BOT1V2_FILL_PRICE_INVALID",
                "MIA_FILL_PRICE_INVALID",
                sym=sym, cid=cid, kind=kind, signal_id=signal_id,
                msg_status=order_status,
                last_fill_price=msg.get("LastFillPrice"),
                avg_fill_price=msg.get("AverageFillPrice"),
            )
            return
        # 6. Close position (sous lock pour idempotence)
        with self._lock:
            # Re-check : position pas deja closed par autre fill
            if not self.store.has_position(sym):
                return
            entry_price = float(entry.get("entry_price", 0.0))
            direction = entry.get("direction", "LONG")
            n_micros = int(entry.get("n_micros", 1))
            # Calcul PnL
            if direction == "LONG":
                pnl_pts = fill_price - entry_price
            else:
                pnl_pts = entry_price - fill_price
            tick, tick_value = _micro_tick_specs(sym)
            pnl_ticks = pnl_pts / tick if tick else 0.0
            pnl_usd = pnl_ticks * tick_value * n_micros
            exit_reason = "TP" if kind == "tp" else "SL"
            outcome = "WIN" if pnl_usd > 0 else "LOSS"
            # Cleanup store + state_bridge
            self.store.close_position(sym)
            self.store.save()
            try:
                self.state_bridge.close_position(
                    sym,
                    exit_price=fill_price,
                    exit_reason=exit_reason,
                    outcome=outcome,
                    pnl_ticks=round(pnl_ticks, 2),
                    pnl_usd=round(pnl_usd, 2),
                )
            except Exception as e:  # noqa: BLE001
                self._emit_pair(
                    "BOT1V2_STATE_BRIDGE_CLOSE_EXCEPTION",
                    "MIA_FILL_STATE_BRIDGE_EXCEPTION",
                    sym=sym, err=str(e)[:200],
                )
            # Cleanup cid_index (les 3 cids de cette position)
            for c in list(self._cid_index.keys()):
                if self._cid_index[c].get("signal_id") == signal_id:
                    self._cid_index.pop(c, None)
        # 7. Emit close log + callback externe (hors lock pour eviter deadlock)
        self._emit_pair(
            f"BOT1V2_DTC_FILL_{exit_reason}",
            f"MIA_DTC_FILL_{exit_reason}",
            sym=sym, direction=direction,
            entry_price=entry_price, exit_price=fill_price,
            pnl_ticks=round(pnl_ticks, 2),
            pnl_usd=round(pnl_usd, 2),
            signal_id=signal_id,
            cid=cid,
        )
        if self.on_close_callback is not None:
            try:
                self.on_close_callback(sym, pnl_usd)
            except Exception as e:  # noqa: BLE001
                self._emit_pair(
                    "BOT1V2_ON_CLOSE_CALLBACK_EXCEPTION",
                    "MIA_FILL_ON_CLOSE_CALLBACK_EXCEPTION",
                    sym=sym, err=str(e)[:200],
                )

    def update_sl_cid(self, sym: str, old_sl_cid: str, new_sl_cid: str) -> bool:
        """Remplace l'ancien sl_cid par le nouveau dans _cid_index (trailing).

        FIX 17/06 Jackson zero-dette : Bot BN V4 fait du trailing SL via
        cancel-replace. Sans cette method, le listener garde l'ancien
        sl_cid et le nouveau SL (envoye par dtc.send_stop_order) n'est pas
        trace → fill du nouveau SL = no close → dashboard reste OPEN.

        Args:
            sym: symbole (pour traceability)
            old_sl_cid: ancien CID a retirer
            new_sl_cid: nouveau CID a ajouter avec kind="sl" + memes details
                (entry_price, direction, n_micros, etc. preserves).

        Returns:
            True si update reussi, False si old_sl_cid pas trouve dans index.
            Note : si new_sl_cid est vide ou None, l'ancien est juste retire
            (degraded mode = position nue mais listener informe).
        """
        with self._lock:
            old_entry = self._cid_index.pop(old_sl_cid, None)
            if old_entry is None:
                return False
            if new_sl_cid:
                # Preserve tous les details mais force kind=sl
                new_entry = {**old_entry, "kind": "sl"}
                self._cid_index[new_sl_cid] = new_entry
        # Emit hors lock pour eviter deadlock
        self._emit_pair(
            "BOT1V2_FILL_SL_CID_UPDATED",
            "MIA_FILL_SL_CID_UPDATED",
            sym=sym,
            old_sl_cid=old_sl_cid[:20] if old_sl_cid else "",
            new_sl_cid=new_sl_cid[:20] if new_sl_cid else "",
            signal_id=old_entry.get("signal_id", ""),
        )
        return True

    def _emit_pair(self, legacy_code: str, mia_code: str, **ctx) -> None:
        """Emit en parallele le code legacy `BOT1V2_*` ET le code generic `MIA_*`.

        Etape B (17/06 evening) : avant migration complete vers MIA_FILL_*, on
        emit les 2 pour preserver compat audit historique + permettre grep
        cross-bot MIA_DTC_FILL_TP des 3 bots Sim1/Sim2/Sim3.

        Le code MIA_* inclut `bot=self.bot_id` pour distinguer les processes.
        """
        try:
            _log.emit(legacy_code, **ctx)
        except Exception:  # noqa: BLE001
            pass
        try:
            _log.emit(mia_code, bot=self.bot_id, **ctx)
        except Exception:  # noqa: BLE001
            pass

    def n_tracked_brackets(self) -> int:
        """Pour tests / monitoring : nombre de CIDs actifs dans l'index."""
        with self._lock:
            return len(self._cid_index)
