"""Main orchestrateur Bot BN V4 (Sim3).

Boucle principale :
  1. Pour chaque symbole, read_last_bar() depuis sierra_enriched
  2. Check fraicheur (DMP_BAR_MAX_AGE_SEC)
  3. Position existante ? Update trailing + skip new entry
  4. Session gate (US RTH only - sinon shadow log si SHADOW_LOG_LONDON=True)
  5. Daily limits gate (5 trades, $200 loss, $150 win - Mark Douglas)
  6. Regime gate (gamma/VIX/news)
  7. SignalEngine.on_bar(bar) -> SignalDecision
  8. Si tradable -> OrderRouter.send_entry + TrailingManager.start
  9. Persist state + emit logs

Reutilise Bot 1 v2 :
  - SierraDataSource (read_last_bar + is_fresh)
  - DailyLimitsGate + SessionGate
  - PositionStore (path override pour bot_bn_v4)
  - StateBridge (sub-classe pour state_sim3.json)

Usage :
  python -m CORE.bot_bn_v4.main --symbols NQ --dry-run --verbose
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Reuse Bot 1 v2 infra (data source + gates + position store)
from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.data_source import SierraDataSource
from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
from CORE.bot1_v2.gates.session import SessionGate
from CORE.bot1_v2.state.position_store import PositionStore

from CORE.bot_bn_v4.config import BotBNV4Config
from CORE.bot_bn_v4.execution.order_router import OrderRouter
from CORE.bot_bn_v4.gates.regime import RegimeGate
from CORE.bot_bn_v4.logger import bot_log, log_decision_jsonl
from CORE.bot_bn_v4.signal_engine import SignalEngine, SignalDecision
from CORE.bot_bn_v4.state_bridge import BotBNStateBridge
from CORE.bot_bn_v4.trailing import TrailingManager


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _bot_log_emit_safe(code: str, **ctx) -> None:
    """log_fn injectable dans BNV4Engine - safe wrapper.

    Le moteur appelle log_fn("BN_V4_GATE_TREND_BLOCK", ...). Ces codes sont
    deja definis dans CORE.log_catalog (cf bn_v4_paper.py). On emit via bot_log
    (process=botbn) pour qu'ils apparaissent dans LOGS/decisions/decisions_<date>.jsonl.

    Si un code n'existe pas (cas degraded), on swallow (PAS de raise dans la loop).
    """
    try:
        bot_log.emit(code, **ctx)
    except Exception:
        # Anti-blocker : un code inconnu ne doit pas arreter le bot
        pass


class BotBNV4:
    """Bot BN V4 orchestrateur (Sim3)."""

    def __init__(
        self,
        symbols: list[str],
        cfg: Optional[BotBNV4Config] = None,
        bot1v2_cfg: Optional[Bot1V2Config] = None,
        dry_run: bool = True,
        dtc_connector=None,
    ):
        self.symbols = [s.upper() for s in symbols]
        self.cfg = cfg or BotBNV4Config.from_env()
        # Bot1V2Config sert UNIQUEMENT a alimenter SierraDataSource (chemin JSONL)
        # et SessionGate (logique US RTH partagee). Pas de Sim2 leak : on
        # construit notre propre OrderRouter avec self.cfg.TRADE_ACCOUNT (Sim3).
        self.bot1v2_cfg = bot1v2_cfg or Bot1V2Config.from_env()
        self.dry_run = dry_run

        self.log = logging.getLogger("bot_bn_v4")

        # State load avec path dedie bot_bn_v4
        root = Path(__file__).resolve().parents[2]
        positions_path = root / "DATA" / "PAPER_TRADES" / "bot_bn_v4_runtime_positions.json"
        self.store = PositionStore(path=positions_path)
        loaded = self.store.load()
        state_status = "OK" if loaded else "NEW_NO_FILE"
        self.log.info(f"State load: {state_status}")
        try:
            bot_log.emit("BOTBN_STATE_LOAD", status=state_status)
        except Exception:
            pass

        # Per-symbol engines
        self.signals: dict[str, SignalEngine] = {}
        self.trails: dict[str, TrailingManager] = {}
        self.data_sources: dict[str, SierraDataSource] = {}
        for sym in self.symbols:
            self.signals[sym] = SignalEngine(
                symbol=sym, cfg=self.cfg, log_fn=_bot_log_emit_safe,
            )
            self.trails[sym] = TrailingManager(symbol=sym, cfg=self.cfg)
            self.data_sources[sym] = SierraDataSource(symbol=sym, cfg=self.bot1v2_cfg)

        # Gates : session + daily limits (reuse Bot 1 v2), regime (BN V4 dedie)
        self.session_gate = SessionGate(self.bot1v2_cfg)
        self.daily_gate = DailyLimitsGate(self.bot1v2_cfg)
        # Override seuils daily gate avec config Bot BN V4 (anti silent fallback)
        # On surcharge MAX_TRADES_PER_DAY/STOP_LOSS/STOP_WIN dans Bot1V2Config
        # via env vars BOT1V2_MAX_TRADES_PER_DAY etc., mais ici on les force depuis
        # BOTBN_* en re-initialisant l'objet pour bypass.
        # Plus simple : DailyLimitsGate lit cfg.MAX_TRADES_PER_DAY donc s'ils
        # correspondent c'est OK. On documente que les 2 configs doivent matcher.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily_gate.reset_for_new_day(today)

        self.regime_gate = RegimeGate(self.cfg)

        self.router = OrderRouter(
            cfg=self.cfg, dry_run=dry_run, dtc_connector=dtc_connector,
        )

        # State bridge dashboard dedie Sim3
        self.state_bridge = BotBNStateBridge()

        self._running = False
        self._last_heartbeat_ts = 0.0

    def stop(self, *_):
        self.log.info("Stop signal received, graceful shutdown...")
        self._running = False

    def _rotate_day_if_needed(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old_date = self.daily_gate.state.date_str
        if old_date != today:
            self.log.info(f"Day rollover: {old_date} -> {today}")
            try:
                bot_log.emit("BOTBN_DAY_ROLLOVER", old_date=old_date, new_date=today)
            except Exception:
                pass
            self.daily_gate.reset_for_new_day(today)
            try:
                self.state_bridge.rotate_day(today.replace("-", ""))
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"state_bridge rotate_day fail: {e}")

    def _process_open_position(self, sym: str, bar: dict) -> None:
        """Update trailing pour position ouverte + bridge dashboard live."""
        # Update trailing manager si actif
        trail = self.trails.get(sym)
        if trail is not None and trail.is_active():
            upd = trail.on_bar(bar)
            if upd.error:
                self.log.warning(f"{sym} trailing error: {upd.error}")
            if upd.new_sl is not None:
                pos = self.store.get_position(sym) if hasattr(self.store, "get_position") else self.store.positions.get(sym)
                if pos:
                    old_sl = pos.get("sl_price", 0.0)
                    try:
                        bot_log.emit(
                            "BOTBN_TRAIL_SL_UPDATE",
                            sym=sym, old_sl=old_sl, new_sl=upd.new_sl,
                            pivot_low=trail.state.pullback_low_running if trail.state else 0,
                        )
                    except Exception:
                        pass
                    pos["sl_price"] = upd.new_sl
                    pos["sl_pivots"] = trail.n_pivots()
                    self.store.save()
                    # Cancel-replace SL cote broker
                    self.router.replace_sl(
                        symbol=sym,
                        sl_cid=pos.get("sl_cid", ""),
                        new_sl_price=upd.new_sl,
                        direction=pos.get("direction", "long"),
                        n_micros=pos.get("n_micros", 1),
                    )
            # TODO Tier 2 : si is_timeout -> close position automatique
            # (necessite listener ORDER_UPDATE DTC ou close ordre manuel)

        # Bridge dashboard live tracking (MFE/MAE/PnL unrealized)
        try:
            close_price = float(bar.get("close") or 0.0)
            if close_price > 0:
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

    def _process_symbol(self, sym: str) -> None:
        """Process une iteration pour un symbole."""
        ds = self.data_sources[sym]
        bar = ds.read_last_bar()
        if bar is None:
            return

        bar_ts = bar.get("ts")

        # Staleness check
        is_fresh, age_sec = ds.is_fresh(bar)
        if not is_fresh:
            self.log.warning(f"{sym} bar stale: age={age_sec:.0f}s")
            try:
                bot_log.emit(
                    "BOTBN_BAR_STALE",
                    sym=sym, age_sec=age_sec, max_age=self.cfg.DMP_BAR_MAX_AGE_SEC,
                )
            except Exception:
                pass
            return

        # Position ouverte ? -> update trailing + skip new entry
        if self.store.has_position(sym):
            try:
                bot_log.emit("BOTBN_SKIP_HAS_POSITION", sym=sym)
            except Exception:
                pass
            self._process_open_position(sym, bar)
            return

        # Session gate - shadow log London si activated
        sess = self.session_gate.check_allow_entry(bar)
        session_allowed = sess.allowed
        session_phase = sess.session_phase or "?"
        is_shadow_session = (
            not session_allowed
            and self.cfg.SHADOW_LOG_LONDON
            and session_phase in ("LONDON", "ASIA")
        )
        if not session_allowed and not is_shadow_session:
            try:
                bot_log.emit(
                    "BOTBN_GATE_SESSION_BLOCK",
                    sym=sym, phase=session_phase,
                )
            except Exception:
                pass
            return

        # Daily limits gate (bloque trade REEL seul, pas shadow)
        daily = self.daily_gate.check_allow_entry()
        if session_allowed and not daily.allowed:
            self.log.info(f"{sym} daily limit: {daily.skip_reason}")
            try:
                bot_log.emit("BOTBN_GATE_DAILY_BLOCK", sym=sym, reason=daily.skip_reason)
            except Exception:
                pass
            return

        # Regime gate (gamma/VIX/news)
        # Direction proposee : selon DIRECTION_MODE config (defaut long)
        proposed_dir = self.cfg.DIRECTION_MODE if self.cfg.DIRECTION_MODE != "both" else "long"
        rg = self.regime_gate.check_allow_entry(bar, proposed_dir)
        if not rg.allowed:
            try:
                bot_log.emit(
                    "BOTBN_GATE_REGIME_BLOCK",
                    sym=sym, direction=proposed_dir, reason=rg.skip_reason,
                )
            except Exception:
                pass
            return

        # SignalEngine evaluation (TOUJOURS evalue, meme shadow session)
        decision: SignalDecision = self.signals[sym].on_bar(bar)

        if not decision.tradable:
            # Skip ou hypothetical (OBSERVE mode A grade par ex.)
            try:
                bot_log.emit(
                    "BOTBN_NOT_TRADABLE",
                    sym=sym, direction=(decision.direction or "?"),
                    skip_reason=decision.skip_reason or "?",
                    grade=(decision.grade or "?"),
                )
            except Exception:
                pass
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, direction=decision.direction,
                setup=decision.setup, tradable=False,
                skip_reason=decision.skip_reason,
                session_phase=session_phase,
                hypothetical=decision.hypothetical,
            )
            return

        # TRADABLE - distinguer trade REEL vs shadow session
        if is_shadow_session:
            # Shadow London/Asia : on EVALUE et LOG, mais on EXECUTE PAS
            self.log.info(
                f"{sym} TRADABLE_HYPO {decision.direction} grade={decision.grade} "
                f"session={session_phase} (shadow - non execute)"
            )
            try:
                bot_log.emit(
                    "BOTBN_TRADABLE_HYPOTHETICAL",
                    sym=sym, direction=decision.direction, grade=decision.grade,
                    session_phase=session_phase,
                )
            except Exception:
                pass
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, direction=decision.direction,
                setup=decision.setup, tradable=False,
                skip_reason=f"SHADOW_SESSION:{session_phase}",
                session_phase=session_phase,
                hypothetical=True,
            )
            return

        # TRADE REEL : compute SL + send order + start trailing
        setup = decision.setup or {}
        entry_price = float(setup.get("entry_price", 0.0))
        if entry_price <= 0:
            self.log.error(f"{sym} entry_price invalide dans setup: {entry_price}")
            return

        # Calcule SL via TrailingManager.start (qui appelle make_trailing_state)
        # mais on a besoin du sl_price AVANT d'envoyer l'ordre. On reproduit ici
        # la formule simple (low - 6 ticks LONG / high + 6 ticks SHORT) car la
        # logique trailing complete (state machine) demarre apres fill.
        last_bar = self.signals[sym].get_last_bar() or {}
        from CORE.bn_v4_engine import TICK_SIZE
        tick = TICK_SIZE.get(sym, 0.25)
        if decision.direction == "long":
            try:
                sl_price = float(last_bar.get("low", entry_price)) - self.cfg.SL_INITIAL_BUFFER_TICKS * tick
            except (TypeError, ValueError):
                sl_price = entry_price - self.cfg.SL_INITIAL_BUFFER_TICKS * tick
        else:
            try:
                sl_price = float(last_bar.get("high", entry_price)) + self.cfg.SL_INITIAL_BUFFER_TICKS * tick
            except (TypeError, ValueError):
                sl_price = entry_price + self.cfg.SL_INITIAL_BUFFER_TICKS * tick

        sl_ticks = int(abs(entry_price - sl_price) / tick)

        try:
            bot_log.emit(
                "BOTBN_TRADABLE",
                sym=sym, direction=decision.direction,
                grade=decision.grade or "?",
                entry_price=entry_price, sl_ticks=sl_ticks,
            )
        except Exception:
            pass

        order_result = self.router.send_entry(
            symbol=sym,
            direction=decision.direction or "long",
            entry_price=entry_price,
            sl_price=sl_price,
            n_micros=self.cfg.N_MICROS_DEFAULT,
        )
        if not order_result.success:
            self.log.error(f"{sym} ORDER FAIL: {order_result.error_msg}")
            try:
                bot_log.emit(
                    "BOTBN_ORDER_FAIL",
                    sym=sym, direction=decision.direction or "?",
                    err_msg=order_result.error_msg,
                )
            except Exception:
                pass
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, direction=decision.direction,
                setup=setup, tradable=True, executed=False,
                order_error=order_result.error_msg,
                session_phase=session_phase,
            )
            return

        try:
            bot_log.emit(
                "BOTBN_ORDER_SENT",
                sym=sym, direction=decision.direction or "?",
                n_micros=self.cfg.N_MICROS_DEFAULT,
                parent_cid=order_result.parent_cid,
                fill_price=order_result.fill_price,
            )
        except Exception:
            pass

        # Start trailing manager
        start_err = self.trails[sym].start(
            direction=decision.direction or "long",
            entry_bar=last_bar,
            entry_price=order_result.fill_price,
            entry_bar_idx=self.signals[sym].n_bars() - 1,
        )
        if start_err:
            self.log.warning(f"{sym} trailing start: {start_err}")

        # Persist position
        self.store.open_position(sym, {
            "signal_id": f"BOTBN_{sym}_{int(time.time())}",
            "direction": (decision.direction or "long").upper(),
            "entry_price": order_result.fill_price,
            "entry_ts": int(time.time() * 1000),
            "sl_price": sl_price,
            "sl_ticks": sl_ticks,
            "n_micros": self.cfg.N_MICROS_DEFAULT,
            "parent_cid": order_result.parent_cid,
            "sl_cid": order_result.sl_cid,
            "dry_run": self.dry_run,
            "grade": decision.grade,
            "sl_pivots": 0,
        })
        self.store.save()
        # Bridge dashboard
        try:
            self.state_bridge.open_position(
                sym,
                direction=(decision.direction or "long").upper(),
                entry_price=order_result.fill_price,
                sl_price=sl_price,
                tp_price=0.0,  # BN V4 : pas de TP fixe
                sl_ticks=sl_ticks,
                tp_ticks=0,
                signal_id=f"BOTBN_{sym}_{int(time.time())}",
                sl_wall=f"BN_V4_{decision.grade}",
                n_micros=self.cfg.N_MICROS_DEFAULT,
            )
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"state_bridge open_position fail: {e}")

        log_decision_jsonl(
            bar_ts=bar_ts, symbol=sym, direction=decision.direction,
            setup=setup, tradable=True, executed=True,
            fill_price=order_result.fill_price,
            sl_price=sl_price, sl_ticks=sl_ticks,
            session_phase=session_phase,
        )

    def _heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat_ts > 30:
            n_positions = len(self.store.positions)
            n_trades = self.daily_gate.state.n_trades_today
            pnl = self.daily_gate.state.cumul_pnl_usd
            self.log.info(
                f"HEARTBEAT positions={n_positions} "
                f"trades_today={n_trades} pnl_today=${pnl:.2f}"
            )
            try:
                bot_log.emit(
                    "BOTBN_HEARTBEAT",
                    n_positions=n_positions, n_trades_today=n_trades, pnl_today=pnl,
                )
            except Exception:
                pass
            try:
                self.state_bridge.heartbeat()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"state_bridge heartbeat fail: {e}")
            self._last_heartbeat_ts = now

    def run(self):
        """Boucle principale poll loop."""
        self.log.info(
            f"Bot BN V4 starting (dry_run={self.dry_run}, "
            f"symbols={self.symbols}, ta={self.cfg.TRADE_ACCOUNT}, "
            f"grade_min={self.cfg.GRADE_MIN})"
        )
        try:
            bot_log.emit(
                "BOTBN_BOOT",
                dry_run=self.dry_run,
                symbols=",".join(self.symbols),
                trade_account=self.cfg.TRADE_ACCOUNT,
                grade_min=self.cfg.GRADE_MIN,
            )
        except Exception:
            pass
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
            except Exception as e:  # noqa: BLE001
                self.log.exception(f"Loop error: {e}")
                try:
                    bot_log.emit("BOTBN_LOOP_EXCEPTION", err=repr(e))
                except Exception:
                    pass
            time.sleep(self.cfg.POLL_INTERVAL_SEC)
        self.store.save()
        self.log.info("Bot BN V4 stopped cleanly.")
        try:
            bot_log.emit("BOTBN_SHUTDOWN")
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Bot BN V4 paper trader (Sim3)")
    parser.add_argument(
        "--symbols", default="NQ",
        help="Comma-separated symbols (default: NQ)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Mode dry-run (no DTC, log only). Default: True.",
    )
    parser.add_argument(
        "--prod", action="store_true",
        help="Mode prod (DTC Sim3). Default: dry-run.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--max-iterations", type=int, default=0,
        help="Stop apres N iterations (smoke test). 0=infini.",
    )
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    dry_run = not args.prod

    cfg = BotBNV4Config.from_env()

    dtc_connector = None
    if not dry_run:
        try:
            import sys as _sys
            from pathlib import Path as _P
            _bot_dir = str((_P(__file__).resolve().parents[2] / "BOT"))
            if _bot_dir not in _sys.path:
                _sys.path.insert(0, _bot_dir)
            from BOT.dtc_connector import DTCConnector
            from BOT.bot_config import DTCConfig
            # ClientName unique : MIA_BotBN (anti-collision MIA_Bot1V2, MIA_PaperTrader)
            dtc_cfg = DTCConfig(client_name="MIA_BotBN")
            dtc_connector = DTCConnector(config=dtc_cfg)
            dtc_connector.connect()
            logging.info(f"DTC connector connected (ClientName=MIA_BotBN, TA={cfg.TRADE_ACCOUNT})")
            try:
                bot_log.emit(
                    "BOTBN_DTC_CONNECTED",
                    client_name="MIA_BotBN", trade_account=cfg.TRADE_ACCOUNT,
                )
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            logging.error(f"DTC connector failed: {e}. Falling back to dry-run.")
            try:
                bot_log.emit("BOTBN_DTC_FALLBACK_DRYRUN", err=repr(e))
            except Exception:
                pass
            dry_run = True

    bot = BotBNV4(
        symbols=symbols, cfg=cfg, dry_run=dry_run,
        dtc_connector=dtc_connector,
    )

    # Mode smoke test : limite N iterations
    if args.max_iterations > 0:
        bot._running = True
        for _ in range(args.max_iterations):
            try:
                bot._rotate_day_if_needed()
                for sym in bot.symbols:
                    bot._process_symbol(sym)
                bot._heartbeat()
            except Exception as e:  # noqa: BLE001
                logging.exception(f"Loop error: {e}")
            time.sleep(cfg.POLL_INTERVAL_SEC)
        bot.store.save()
        logging.info("Bot BN V4 smoke test done.")
    else:
        bot.run()


if __name__ == "__main__":
    main()
