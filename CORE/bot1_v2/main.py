"""Main orchestrateur Bot 1 v2.

Boucle principale :
  1. Pour chaque symbole, read_last_bar() depuis sierra_enriched
  2. Check fraicheur (DMP_BAR_MAX_AGE_SEC)
  3. Session gate (US RTH only)
  4. Daily limits gate (5 trades, $200 loss, $150 win)
  5. Position check (1 position max par symbole)
  6. Cluster.evaluate -> ClusterDecision
  7. Si tradable -> OrderRouter.send_bracket
  8. Persist state

Logs (regle souveraine LOGS TRACABILITE 01/05) :
  - Codes catalog BOT1V2_* via CORE.logging_v2 (JSONL events/decisions/execution)
  - JSONL DEDIE decisions : LOGS/bot1_v2_decisions/*.jsonl append-only
    avec verdict mirror complet + sltp + decision pour CHAQUE evaluation
    (audit empirique : pourquoi 0 trade, distribution stars, tuning futur)

Usage :
  python -m CORE.bot1_v2.main --symbols ES,NQ --dry-run

Modes :
  --dry-run : pas de DTC, logging pur (paper simulation)
  (default) : send brackets via DTC Sim2 (prod paper Bot 1 v2)
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from CORE.bot1_v2.cluster import ClusterEngine, ClusterDecision
from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.data_source import SierraDataSource
from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
from CORE.bot1_v2.execution.order_router import OrderRouter
from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
from CORE.bot1_v2.gates.session import SessionGate
from CORE.bot1_v2.logger import bot_log, log_decision_jsonl
from CORE.bot1_v2.state.position_store import PositionStore
from CORE.bot1_v2.state_bridge import StateBridge


def _setup_logging(verbose: bool = False):
    """Setup stdlib logging (stderr) en plus du logger catalog.

    Le logger catalog (CORE.logging_v2) ecrit dans LOGS/<cat>/*.jsonl pour
    chaque code emis. Le stdlib logging garde le miroir stderr pour debug live
    via service nssm (LOGS/bot1_v2/stderr.log).
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class Bot1V2:
    """Bot 1 v2 orchestrateur."""

    def __init__(
        self,
        symbols: list[str],
        cfg: Optional[Bot1V2Config] = None,
        dry_run: bool = True,
        dtc_connector=None,
    ):
        self.symbols = [s.upper() for s in symbols]
        self.cfg = cfg or Bot1V2Config.from_env()
        self.dry_run = dry_run

        self.log = logging.getLogger("bot1_v2")

        # State load
        self.store = PositionStore()
        loaded = self.store.load()
        state_status = "OK" if loaded else "NEW_NO_FILE"
        self.log.info(f"State load: {state_status}")
        bot_log.emit("BOT1V2_STATE_LOAD", status=state_status)

        # Per-symbol engines
        self.clusters: dict[str, ClusterEngine] = {}
        self.data_sources: dict[str, SierraDataSource] = {}
        for sym in self.symbols:
            self.clusters[sym] = ClusterEngine(
                symbol=sym, cfg=self.cfg,
                traded_signal_ids=self.store.traded_signal_ids,
            )
            cooldown = self.store.get_cooldown(sym)
            if cooldown > 0:
                self.clusters[sym].cooldown_until_ts = cooldown
            self.data_sources[sym] = SierraDataSource(symbol=sym, cfg=self.cfg)

        self.session_gate = SessionGate(self.cfg)
        self.daily_gate = DailyLimitsGate(self.cfg)
        # Init daily gate today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily_gate.reset_for_new_day(today)

        self.router = OrderRouter(
            cfg=self.cfg, dry_run=dry_run, dtc_connector=dtc_connector,
        )

        # State bridge dashboard (DATA/PAPER_TRADES/state.json).
        # Sans bridge, le dashboard restait fige sur le dernier trade legacy
        # mia_paper_trader (15/06 -$967). Maintenant Bot 1 v2 maintient le
        # heartbeat updated_ts + open_by_symbol + day rotation.
        self.state_bridge = StateBridge()

        # FIX 17/06 Jackson : DtcFillListener ferme positions sur ORDER_UPDATE
        # Type 301 status=7 (TP/SL fill). Avant ce fix, le dashboard restait
        # OPEN avec MFE/PnL faux indefiniment apres cloture broker. Pattern
        # repris de Bot 3 v3 + BN V4. Branche sur dtc.on_order_update.
        # Callback on_close declenche daily_gate.register_close pour MAJ stats.
        if dtc_connector is not None:
            self.fill_listener = DtcFillListener(
                cfg=self.cfg, store=self.store, state_bridge=self.state_bridge,
                on_close_callback=self._on_fill_close,
                bot_id="bot1v2",
            )
            try:
                dtc_connector.on_order_update = self.fill_listener.handle_order_update
                bot_log.emit(
                    "BOT1V2_FILL_LISTENER_WIRED",
                    trade_account=self.cfg.TRADE_ACCOUNT,
                )
                # B (17/06 evening) : emit alias MIA_FILL_LISTENER_WIRED pour audit cross-bot
                try:
                    bot_log.emit(
                        "MIA_FILL_LISTENER_WIRED",
                        trade_account=self.cfg.TRADE_ACCOUNT,
                        bot="bot1v2",
                    )
                except Exception:  # noqa: BLE001
                    pass
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"dtc.on_order_update wire fail: {e}")
        else:
            self.fill_listener = None

        self._running = False
        self._last_heartbeat_ts = 0.0

    def _on_fill_close(self, sym: str, pnl_usd: float) -> None:
        """Callback DtcFillListener apres close TP/SL.

        Tient le daily_gate a jour (decompte trades + cumul PnL).
        CRITIQUE : sans ce maj, daily_stop_loss/win/max_trades ne se declenchent
        jamais → reproduit incident Douglas 04/06 (perte sans stop). Cf
        `feedback_douglas_consistency_principles.md`.
        """
        try:
            self.daily_gate.update_after_trade(pnl_usd)
        except Exception as e:  # noqa: BLE001
            self.log.error(f"daily_gate.update_after_trade fail: {e}")
        try:
            bot_log.emit(
                "BOT1V2_FILL_CLOSE",
                sym=sym, pnl_usd=round(float(pnl_usd), 2),
                trades_today=self.daily_gate.state.n_trades_today,
                cumul_pnl=round(self.daily_gate.state.cumul_pnl_usd, 2),
            )
        except Exception:  # noqa: BLE001
            pass

    def stop(self, *_):
        self.log.info("Stop signal received, gracefull shutdown...")
        self._running = False

    def _rotate_day_if_needed(self):
        """Rollover daily limits + state.json dashboard si nouveau jour."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old_date = self.daily_gate.state.date_str
        if old_date != today:
            self.log.info(f"Day rollover: {old_date} -> {today}")
            bot_log.emit("BOT1V2_DAY_ROLLOVER", old_date=old_date, new_date=today)
            self.daily_gate.reset_for_new_day(today)
            # Bridge dashboard : reset closed_today + date (archive l'ancien)
            try:
                self.state_bridge.rotate_day(today.replace("-", ""))
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"state_bridge rotate_day fail: {e}")

    def _process_symbol(self, sym: str) -> Optional[ClusterDecision]:
        """Process une iteration pour un symbole.

        Emit codes catalog + JSONL decisions a chaque chemin (skip/tradable).

        DRY-EVALUATE Asia/London (Jackson 16/06) :
          - Session non-RTH : on EVALUE le cluster malgre tout
          - On LOGUE le verdict hypothetique dans JSONL (hypothetical=True)
          - On N'EXECUTE PAS l'ordre (juste audit)
          - Apres 2-3 semaines : grep bot1_v2_decisions pour decider d'ouvrir
            Asia/London ou rester US RTH only (data-driven, pas vibes-driven)

        Returns:
            ClusterDecision si trade REEL envoye, None sinon (skip ou hypo).
        """
        ds = self.data_sources[sym]
        bar = ds.read_last_bar()
        if bar is None:
            return None  # pas de nouvelle bar (silent - dedup tail-follow)

        bar_ts = bar.get("ts")

        # Staleness check
        is_fresh, age_sec = ds.is_fresh(bar)
        if not is_fresh:
            self.log.warning(f"{sym} bar stale: age={age_sec:.0f}s")
            bot_log.emit(
                "BOT1V2_BAR_STALE",
                sym=sym, age_sec=age_sec, max_age=self.cfg.DMP_BAR_MAX_AGE_SEC,
            )
            return None

        # Position deja ouverte ? -> update live tracking (MFE/MAE/PnL unrealized)
        # pour visibility dashboard puis skip (pas de nouveau trade).
        if self.store.has_position(sym):
            bot_log.emit("BOT1V2_SKIP_HAS_POSITION", sym=sym)
            try:
                close_price = float(bar.get("close") or 0.0)
                if close_price > 0:
                    # Tick size + usd_per_tick par symbole
                    if sym == "ES":
                        tick, usd_t = 0.25, 1.25
                    elif sym == "NQ":
                        tick, usd_t = 0.25, 0.50
                    elif sym == "MGC":
                        tick, usd_t = 0.10, 1.00
                    else:
                        tick, usd_t = 0.25, 1.25
                    self.state_bridge.update_open_position_live(
                        sym, current_price=close_price,
                        tick_size=tick, usd_per_tick=usd_t,
                    )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"state_bridge update_open_position fail: {e}")
            return None

        # Session gate - DRY-EVALUATE : on n'arrete plus si non-RTH, on logue
        sess = self.session_gate.check_allow_entry(bar)
        session_allowed = sess.allowed
        session_phase = sess.session_phase or "?"
        if not session_allowed:
            bot_log.emit(
                "BOT1V2_GATE_SESSION_BLOCK",
                sym=sym,
                phase=session_phase,
                reason=sess.skip_reason or "?",
            )
            # PAS de return -> on continue pour dry-evaluate + audit JSONL

        # Daily limits gate - bloque uniquement les trades REELS (pas l'audit)
        daily = self.daily_gate.check_allow_entry()
        if session_allowed and not daily.allowed:
            self.log.info(f"{sym} daily limit: {daily.skip_reason}")
            bot_log.emit("BOT1V2_GATE_DAILY_BLOCK", sym=sym, reason=daily.skip_reason)
            return None

        # Cluster evaluate (TOUJOURS, meme hors RTH pour audit empirique)
        decision = self.clusters[sym].evaluate(bar)

        if not decision.tradable:
            vetos_str = ",".join(v.name for v in decision.vetos_active) if decision.vetos_active else ""
            bot_log.emit(
                "BOT1V2_NOT_TRADABLE",
                sym=sym,
                direction=decision.direction or "?",
                skip_reason=decision.skip_reason,
                stars_count=decision.stars_count,
                stars_total=decision.stars_total,
                vetos=vetos_str,
            )
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym,
                mirror=decision.mirror, sltp=decision.sltp,
                decision=decision, executed=False,
                session_phase=session_phase,
                hypothetical=not session_allowed,
            )
            return None

        # TRADABLE - 2 chemins selon session
        if not session_allowed:
            # HYPOTHETIQUE : cluster aurait trade mais Asia/London non execute
            self.log.info(
                f"{sym} TRADABLE_HYPO {decision.direction} @ {decision.entry_price:.2f} "
                f"session={session_phase} (Asia/London audit - non execute)"
            )
            bot_log.emit(
                "BOT1V2_TRADABLE_HYPOTHETICAL",
                sym=sym,
                direction=decision.direction,
                entry_price=decision.entry_price,
                session_phase=session_phase,
                signal_id=decision.signal_id,
            )
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym,
                mirror=decision.mirror, sltp=decision.sltp,
                decision=decision, executed=False,
                session_phase=session_phase,
                hypothetical=True,
            )
            return None

        # TRADABLE + session RTH = execution REELLE
        self.log.info(
            f"{sym} TRADABLE {decision.direction} @ {decision.entry_price:.2f} "
            f"SL {decision.sl_ticks}t({decision.sl_wall}) TP {decision.tp_ticks}t "
            f"RR {decision.rr_ratio:.1f} stars {decision.stars_count}/{decision.stars_total}"
        )
        bot_log.emit(
            "BOT1V2_TRADABLE",
            sym=sym,
            direction=decision.direction,
            entry_price=decision.entry_price,
            sl_ticks=decision.sl_ticks,
            sl_wall=decision.sl_wall,
            tp_ticks=decision.tp_ticks,
            rr_ratio=decision.rr_ratio,
            stars_count=decision.stars_count,
            stars_total=decision.stars_total,
            signal_id=decision.signal_id,
        )

        order_result = self.router.send_bracket(decision)
        if not order_result.success:
            self.log.error(f"{sym} ORDER FAIL: {order_result.error_msg}")
            bot_log.emit(
                "BOT1V2_ORDER_FAIL",
                sym=sym,
                direction=decision.direction,
                err_msg=order_result.error_msg,
                signal_id=decision.signal_id,
            )
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym,
                mirror=decision.mirror, sltp=decision.sltp,
                decision=decision, executed=False,
                order_error=order_result.error_msg,
                session_phase=session_phase,
                hypothetical=False,
            )
            return None

        bot_log.emit(
            "BOT1V2_ORDER_SENT",
            sym=sym,
            direction=decision.direction,
            n_micros=decision.n_micros,
            parent_cid=order_result.parent_cid,
            fill_price=order_result.fill_price,
            signal_id=decision.signal_id,
        )
        log_decision_jsonl(
            bar_ts=bar_ts, symbol=sym,
            mirror=decision.mirror, sltp=decision.sltp,
            decision=decision, executed=True,
            fill_price=order_result.fill_price,
            session_phase=session_phase,
            hypothetical=False,
        )

        # Persist position
        self.store.open_position(sym, {
            "signal_id": decision.signal_id,
            "direction": decision.direction,
            "entry_price": order_result.fill_price,
            "entry_ts": int(time.time() * 1000),
            "sl_price": decision.sl_price,
            "tp_price": decision.tp_price,
            "sl_ticks": decision.sl_ticks,
            "tp_ticks": decision.tp_ticks,
            "n_micros": decision.n_micros,
            "parent_cid": order_result.parent_cid,
            "tp_cid": order_result.tp_cid,
            "sl_cid": order_result.sl_cid,
            "dry_run": self.dry_run,
        })
        self.clusters[sym].register_trade(decision.signal_id)
        self.store.save()
        # FIX 17/06 review code-reviewer angle mort 7 : register_bracket AVANT
        # state_bridge.open_position pour eviter fenetre course si TP fill
        # ultra-rapide entre les 2 (rare mais documente en gap-through).
        if self.fill_listener is not None:
            try:
                self.fill_listener.register_bracket(
                    sym=sym, signal_id=decision.signal_id,
                    direction=decision.direction,
                    entry_price=order_result.fill_price,
                    sl_price=decision.sl_price,
                    tp_price=decision.tp_price,
                    sl_ticks=decision.sl_ticks,
                    tp_ticks=decision.tp_ticks,
                    n_micros=decision.n_micros,
                    parent_cid=order_result.parent_cid,
                    tp_cid=order_result.tp_cid,
                    sl_cid=order_result.sl_cid,
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"fill_listener register fail: {e}")
        # Bridge dashboard : ajoute open_by_symbol pour visibility instantanee
        try:
            self.state_bridge.open_position(
                sym,
                direction=decision.direction,
                entry_price=order_result.fill_price,
                sl_price=decision.sl_price,
                tp_price=decision.tp_price,
                sl_ticks=decision.sl_ticks,
                tp_ticks=decision.tp_ticks,
                signal_id=decision.signal_id,
                sl_wall=decision.sl_wall,
                n_micros=decision.n_micros,
            )
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"state_bridge open_position fail: {e}")
        return decision

    def _heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat_ts > 30:
            n_positions = len(self.store.positions)
            n_trades = self.daily_gate.state.n_trades_today
            pnl = self.daily_gate.state.cumul_pnl_usd
            self.log.info(
                f"HEARTBEAT positions={n_positions} "
                f"trades_today={n_trades} "
                f"pnl_today=${pnl:.2f}"
            )
            bot_log.emit(
                "BOT1V2_HEARTBEAT",
                n_positions=n_positions,
                n_trades_today=n_trades,
                pnl_today=pnl,
            )
            # Bridge dashboard : update updated_ts pour "Trader UP" visible
            try:
                self.state_bridge.heartbeat()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"state_bridge heartbeat fail: {e}")
            self._last_heartbeat_ts = now

    def run(self):
        """Boucle principale poll loop."""
        self.log.info(
            f"Bot 1 v2 starting (dry_run={self.dry_run}, "
            f"symbols={self.symbols}, "
            f"trade_account={self.cfg.TRADE_ACCOUNT})"
        )
        bot_log.emit(
            "BOT1V2_BOOT",
            dry_run=self.dry_run,
            symbols=",".join(self.symbols),
            trade_account=self.cfg.TRADE_ACCOUNT,
        )
        signal.signal(signal.SIGINT, self.stop)
        try:
            signal.signal(signal.SIGTERM, self.stop)
        except (AttributeError, ValueError):
            pass  # Windows / non-main thread

        self._running = True
        while self._running:
            try:
                self._rotate_day_if_needed()
                for sym in self.symbols:
                    self._process_symbol(sym)
                self._heartbeat()
            except Exception as e:
                self.log.exception(f"Loop error: {e}")
                bot_log.emit("BOT1V2_LOOP_EXCEPTION", err=repr(e), exc=e)
            time.sleep(self.cfg.POLL_INTERVAL_SEC)
        self.store.save()
        self.log.info("Bot 1 v2 stopped cleanly.")
        bot_log.emit("BOT1V2_SHUTDOWN")


def main():
    parser = argparse.ArgumentParser(description="Bot 1 v2 paper trader")
    parser.add_argument(
        "--symbols", default="ES,NQ",
        help="Comma-separated symbols (default: ES,NQ)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Mode dry-run (no DTC, log only). Default: True.",
    )
    parser.add_argument(
        "--prod", action="store_true",
        help="Mode prod (DTC Sim2). Default: dry-run.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    dry_run = not args.prod  # --prod overrides --dry-run

    cfg = Bot1V2Config.from_env()

    dtc_connector = None
    if not dry_run:
        # En prod : import DTC connector legacy.
        # BOT/dtc_connector.py fait `from bot_config import DTCConfig` (import
        # relatif au cwd BOT/). On ajoute BOT/ au sys.path AVANT l'import sinon
        # ModuleNotFoundError silent fallback dry-run.
        try:
            import sys as _sys
            from pathlib import Path as _P
            _bot_dir = str((_P(__file__).resolve().parents[2] / "BOT"))
            if _bot_dir not in _sys.path:
                _sys.path.insert(0, _bot_dir)
            from BOT.dtc_connector import DTCConnector
            from BOT.bot_config import DTCConfig
            # ClientName unique pour coexistence VPS (MIA_Bot_V2 utilise par
            # MIA-Paper legacy). TradeAccount=Sim2 explicite cote OrderRouter
            # via cfg.TRADE_ACCOUNT (PAS hardcode Sim3 piege orphan-prevention).
            dtc_cfg = DTCConfig(client_name="MIA_Bot1V2")
            dtc_connector = DTCConnector(config=dtc_cfg)
            dtc_connector.connect()
            logging.info(f"DTC connector connected (ClientName=MIA_Bot1V2, TA={cfg.TRADE_ACCOUNT})")
            bot_log.emit(
                "BOT1V2_DTC_CONNECTED",
                client_name="MIA_Bot1V2",
                trade_account=cfg.TRADE_ACCOUNT,
            )
        except Exception as e:
            logging.error(f"DTC connector failed: {e}. Falling back to dry-run.")
            bot_log.emit("BOT1V2_DTC_FALLBACK_DRYRUN", err=repr(e))
            dry_run = True

    bot = Bot1V2(
        symbols=symbols, cfg=cfg, dry_run=dry_run,
        dtc_connector=dtc_connector,
    )
    bot.run()


if __name__ == "__main__":
    main()
