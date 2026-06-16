"""Main orchestrateur Bot Mean Revert VWAP (Sim1).

Boucle principale (pattern bot1_v2/main.py) :
  1. Pour chaque symbole, read_last_bar() depuis sierra_enriched
  2. Check fraicheur (DMP_BAR_MAX_AGE_SEC)
  3. Position check (1 position max par symbole)
  4. Daily limits gate (5 trades, $200 loss, $150 win)
  5. SignalEngine.evaluate -> SignalResult (cooldown + session + regime inclus)
  6. Si tradable + non dry-eval -> OrderRouter.send_bracket_signal
  7. Si tradable + NQ dry-eval -> log BOTMR_TRADABLE_HYPOTHETICAL
  8. Persist state + bridge dashboard state_sim1.json

Usage :
  python -m CORE.bot_mean_revert.main --symbols ES,NQ --dry-run
  python -m CORE.bot_mean_revert.main --symbols ES,NQ --prod   # DTC Sim1
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from CORE.bot1_v2.data_source import SierraDataSource
from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
from CORE.bot1_v2.state.position_store import PositionStore
from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.execution.order_router import OrderRouter
from CORE.bot_mean_revert.logger import bot_log, log_decision_jsonl
from CORE.bot_mean_revert.signal_engine import SignalEngine, SignalResult
from CORE.bot_mean_revert.state_bridge import BotMRStateBridge


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class BotMR:
    """Bot Mean Revert VWAP orchestrateur."""

    def __init__(
        self,
        symbols: list[str],
        cfg: Optional[BotMRConfig] = None,
        dry_run: bool = True,
        dtc_connector=None,
    ):
        self.symbols = [s.upper() for s in symbols]
        self.cfg = cfg or BotMRConfig.from_env()
        self.dry_run = dry_run
        self.log = logging.getLogger("bot_mr")

        # PositionStore dedie (path different de bot1_v2)
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        store_path = root / "DATA" / "PAPER_TRADES" / "bot_mr_runtime_positions.json"
        self.store = PositionStore(path=store_path)
        loaded = self.store.load()
        state_status = "OK" if loaded else "NEW_NO_FILE"
        self.log.info(f"State load: {state_status}")
        bot_log.emit("BOTMR_STATE_LOAD", status=state_status)

        # Per-symbol engines / data sources
        self.engines: dict[str, SignalEngine] = {}
        self.data_sources: dict[str, SierraDataSource] = {}
        for sym in self.symbols:
            self.engines[sym] = SignalEngine(symbol=sym, cfg=self.cfg)
            # Reuse SierraDataSource avec Bot1V2Config (compatible : meme DMP_BAR_MAX_AGE_SEC + dir).
            from CORE.bot1_v2.config import Bot1V2Config
            ds_cfg = Bot1V2Config.from_env()
            self.data_sources[sym] = SierraDataSource(symbol=sym, cfg=ds_cfg)

        # Daily limits gate (reuse bot1_v2). Bot1V2Config attendu, mais on bridge
        # via un adapter minimal (seuls 3 champs lus : MAX_TRADES_PER_DAY +
        # DAILY_STOP_LOSS_USD + DAILY_STOP_WIN_USD).
        self.daily_gate = DailyLimitsGate(self._daily_cfg_adapter())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily_gate.reset_for_new_day(today)

        # Order router dedie (ClientName MIA_BotMR, Sim1)
        self.router = OrderRouter(
            cfg=self.cfg, dry_run=dry_run, dtc_connector=dtc_connector,
        )

        # State bridge dashboard (state_sim1.json)
        self.state_bridge = BotMRStateBridge()

        self._running = False
        self._last_heartbeat_ts = 0.0

    def _daily_cfg_adapter(self):
        """Adapter minimal pour passer cfg Bot MR a DailyLimitsGate (qui attend
        Bot1V2Config). On duck-type avec les 3 champs lus."""
        class _CfgAdapter:
            MAX_TRADES_PER_DAY = self.cfg.MAX_TRADES_PER_DAY
            DAILY_STOP_LOSS_USD = self.cfg.DAILY_STOP_LOSS_USD
            DAILY_STOP_WIN_USD = self.cfg.DAILY_STOP_WIN_USD
        return _CfgAdapter()

    def stop(self, *_):
        self.log.info("Stop signal received, graceful shutdown...")
        self._running = False

    def _rotate_day_if_needed(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old_date = self.daily_gate.state.date_str
        if old_date != today:
            self.log.info(f"Day rollover: {old_date} -> {today}")
            bot_log.emit("BOTMR_DAY_ROLLOVER", old_date=old_date, new_date=today)
            self.daily_gate.reset_for_new_day(today)
            try:
                self.state_bridge.rotate_day(today.replace("-", ""))
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"state_bridge rotate_day fail: {e}")

    def _process_symbol(self, sym: str) -> Optional[SignalResult]:
        """Process une iteration pour un symbole."""
        ds = self.data_sources[sym]
        bar = ds.read_last_bar()
        if bar is None:
            return None

        bar_ts = bar.get("ts")
        is_fresh, age_sec = ds.is_fresh(bar)
        if not is_fresh:
            self.log.warning(f"{sym} bar stale: age={age_sec:.0f}s")
            bot_log.emit(
                "BOTMR_BAR_STALE",
                sym=sym, age_sec=age_sec, max_age=self.cfg.DMP_BAR_MAX_AGE_SEC,
            )
            return None

        if self.store.has_position(sym):
            bot_log.emit("BOTMR_SKIP_HAS_POSITION", sym=sym)
            return None

        # Evaluate signal (SignalEngine fait session + cooldown + regime + sizing)
        signal_result = self.engines[sym].evaluate(bar)
        session_phase = signal_result.session_id or "?"
        is_dry_eval = self.cfg.is_dry_eval(sym)

        if not signal_result.tradable:
            bot_log.emit(
                "BOTMR_NOT_TRADABLE",
                sym=sym,
                direction=signal_result.direction or "?",
                skip_reason=signal_result.skip_reason,
            )
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, signal=signal_result,
                executed=False, session_phase=session_phase,
                hypothetical=is_dry_eval,
            )
            return None

        # Daily limits (bloque uniquement les trades REELS)
        daily = self.daily_gate.check_allow_entry()
        if not is_dry_eval and not daily.allowed:
            self.log.info(f"{sym} daily limit: {daily.skip_reason}")
            bot_log.emit("BOTMR_GATE_DAILY_BLOCK", sym=sym, reason=daily.skip_reason)
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, signal=signal_result,
                executed=False, order_error=daily.skip_reason,
                session_phase=session_phase, hypothetical=False,
            )
            return None

        # TRADABLE + NQ dry-eval -> log hypothetical, pas d'execution
        if is_dry_eval:
            self.log.info(
                f"{sym} TRADABLE_HYPO {signal_result.direction} @ {signal_result.entry_price:.2f} "
                f"session={session_phase} (NQ dry-eval - non execute)"
            )
            bot_log.emit(
                "BOTMR_TRADABLE_HYPOTHETICAL",
                sym=sym,
                direction=signal_result.direction,
                session_phase=session_phase,
                signal_id=signal_result.signal_id,
            )
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, signal=signal_result,
                executed=False, session_phase=session_phase, hypothetical=True,
            )
            # On register quand meme le trade pour respecter le cooldown
            self.engines[sym].register_trade(signal_result.signal_id)
            return None

        # TRADABLE + execution REELLE
        self.log.info(
            f"{sym} TRADABLE {signal_result.direction} @ {signal_result.entry_price:.2f} "
            f"SL {signal_result.sl_ticks}t TP {signal_result.tp_ticks}t RR {signal_result.rr_ratio:.1f}"
        )
        bot_log.emit(
            "BOTMR_TRADABLE",
            sym=sym,
            direction=signal_result.direction,
            entry_price=signal_result.entry_price,
            sl_ticks=signal_result.sl_ticks,
            tp_ticks=signal_result.tp_ticks,
            rr_ratio=signal_result.rr_ratio,
        )

        order_result = self.router.send_bracket_signal(
            signal_result, symbol=sym, n_micros=self.cfg.N_MICROS_DEFAULT,
        )
        if not order_result.success:
            self.log.error(f"{sym} ORDER FAIL: {order_result.error_msg}")
            bot_log.emit(
                "BOTMR_ORDER_FAIL",
                sym=sym,
                direction=signal_result.direction,
                err_msg=order_result.error_msg,
            )
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, signal=signal_result,
                executed=False, order_error=order_result.error_msg,
                session_phase=session_phase, hypothetical=False,
            )
            return None

        bot_log.emit(
            "BOTMR_ORDER_SENT",
            sym=sym,
            direction=signal_result.direction,
            n_micros=self.cfg.N_MICROS_DEFAULT,
            parent_cid=order_result.parent_cid,
            fill_price=order_result.fill_price,
        )
        log_decision_jsonl(
            bar_ts=bar_ts, symbol=sym, signal=signal_result,
            executed=True, fill_price=order_result.fill_price,
            session_phase=session_phase, hypothetical=False,
        )

        # Persist position
        self.store.open_position(sym, {
            "signal_id": signal_result.signal_id,
            "direction": signal_result.direction,
            "entry_price": order_result.fill_price,
            "entry_ts": int(time.time() * 1000),
            "sl_price": signal_result.sl_price,
            "tp_price": signal_result.tp_price,
            "sl_ticks": signal_result.sl_ticks,
            "tp_ticks": signal_result.tp_ticks,
            "n_micros": self.cfg.N_MICROS_DEFAULT,
            "parent_cid": order_result.parent_cid,
            "tp_cid": order_result.tp_cid,
            "sl_cid": order_result.sl_cid,
            "dry_run": self.dry_run,
        })
        self.engines[sym].register_trade(signal_result.signal_id)
        self.store.save()
        try:
            self.state_bridge.open_position(
                sym,
                direction=signal_result.direction,
                entry_price=order_result.fill_price,
                sl_price=signal_result.sl_price,
                tp_price=signal_result.tp_price,
                sl_ticks=signal_result.sl_ticks,
                tp_ticks=signal_result.tp_ticks,
                signal_id=signal_result.signal_id,
                n_micros=self.cfg.N_MICROS_DEFAULT,
            )
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"state_bridge open_position fail: {e}")
        return signal_result

    def _heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat_ts > 30:
            n_positions = len(self.store.positions)
            n_trades = self.daily_gate.state.n_trades_today
            pnl = self.daily_gate.state.cumul_pnl_usd
            self.log.info(
                f"HEARTBEAT positions={n_positions} trades_today={n_trades} pnl_today=${pnl:.2f}"
            )
            bot_log.emit(
                "BOTMR_HEARTBEAT",
                n_positions=n_positions, n_trades_today=n_trades, pnl_today=pnl,
            )
            try:
                self.state_bridge.heartbeat()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"state_bridge heartbeat fail: {e}")
            self._last_heartbeat_ts = now

    def run(self):
        self.log.info(
            f"Bot MR starting (dry_run={self.dry_run}, "
            f"symbols={self.symbols}, trade_account={self.cfg.TRADE_ACCOUNT})"
        )
        bot_log.emit(
            "BOTMR_BOOT",
            dry_run=self.dry_run,
            symbols=",".join(self.symbols),
            trade_account=self.cfg.TRADE_ACCOUNT,
        )
        signal.signal(signal.SIGINT, self.stop)
        try:
            signal.signal(signal.SIGTERM, self.stop)
        except (AttributeError, ValueError):
            pass

        self._running = True
        while self._running:
            try:
                self._rotate_day_if_needed()
                for sym in self.symbols:
                    self._process_symbol(sym)
                self._heartbeat()
            except Exception as e:  # noqa: BLE001
                self.log.exception(f"Loop error: {e}")
                bot_log.emit("BOTMR_LOOP_EXCEPTION", err=repr(e))
            time.sleep(self.cfg.POLL_INTERVAL_SEC)
        self.store.save()
        self.log.info("Bot MR stopped cleanly.")
        bot_log.emit("BOTMR_SHUTDOWN")


def main():
    parser = argparse.ArgumentParser(description="Bot Mean Revert paper trader (Sim1)")
    parser.add_argument("--symbols", default="ES,NQ")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--prod", action="store_true",
                        help="Mode prod (DTC Sim1). Default: dry-run.")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    dry_run = not args.prod

    cfg = BotMRConfig.from_env()

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
            dtc_cfg = DTCConfig(client_name="MIA_BotMR")
            dtc_connector = DTCConnector(config=dtc_cfg)
            dtc_connector.connect()
            logging.info(f"DTC connector connected (ClientName=MIA_BotMR, TA={cfg.TRADE_ACCOUNT})")
            bot_log.emit(
                "BOTMR_DTC_CONNECTED",
                client_name="MIA_BotMR",
                trade_account=cfg.TRADE_ACCOUNT,
            )
        except Exception as e:  # noqa: BLE001
            logging.error(f"DTC connector failed: {e}. Falling back to dry-run.")
            bot_log.emit("BOTMR_DTC_FALLBACK_DRYRUN", err=repr(e))
            dry_run = True

    bot = BotMR(symbols=symbols, cfg=cfg, dry_run=dry_run, dtc_connector=dtc_connector)
    bot.run()


if __name__ == "__main__":
    main()
