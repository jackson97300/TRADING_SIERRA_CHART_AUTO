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
from CORE.bot1_v2.execution.order_router import OrderRouter
from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
from CORE.bot1_v2.gates.session import SessionGate
from CORE.bot1_v2.state.position_store import PositionStore


def _setup_logging(verbose: bool = False):
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
        self.log.info(f"State load: {'OK' if loaded else 'NEW (no file)'}")

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

        self._running = False
        self._last_heartbeat_ts = 0.0

    def stop(self, *_):
        self.log.info("Stop signal received, gracefull shutdown...")
        self._running = False

    def _rotate_day_if_needed(self):
        """Rollover daily limits si nouveau jour."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.daily_gate.state.date_str != today:
            self.log.info(f"Day rollover: {self.daily_gate.state.date_str} -> {today}")
            self.daily_gate.reset_for_new_day(today)

    def _process_symbol(self, sym: str) -> Optional[ClusterDecision]:
        """Process une iteration pour un symbole.

        Returns:
            ClusterDecision si trade envoye, None sinon.
        """
        ds = self.data_sources[sym]
        bar = ds.read_last_bar()
        if bar is None:
            return None  # pas de nouvelle bar

        # Staleness check
        is_fresh, age_sec = ds.is_fresh(bar)
        if not is_fresh:
            self.log.warning(f"{sym} bar stale: age={age_sec:.0f}s")
            return None

        # Position deja ouverte ?
        if self.store.has_position(sym):
            return None  # skip silently

        # Session gate
        sess = self.session_gate.check_allow_entry(bar)
        if not sess.allowed:
            return None  # skip silently (loggue dans verbose)

        # Daily limits gate
        daily = self.daily_gate.check_allow_entry()
        if not daily.allowed:
            self.log.info(f"{sym} daily limit: {daily.skip_reason}")
            return None

        # Cluster evaluate
        decision = self.clusters[sym].evaluate(bar)

        if not decision.tradable:
            return None  # silent skip (verbose loggue)

        # Tradable ! Send order
        self.log.info(
            f"{sym} TRADABLE {decision.direction} @ {decision.entry_price:.2f} "
            f"SL {decision.sl_ticks}t({decision.sl_wall}) TP {decision.tp_ticks}t "
            f"RR {decision.rr_ratio:.1f} stars {decision.stars_count}/{decision.stars_total}"
        )
        order_result = self.router.send_bracket(decision)
        if not order_result.success:
            self.log.error(f"{sym} ORDER FAIL: {order_result.error_msg}")
            return None

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
        return decision

    def _heartbeat(self):
        now = time.time()
        if now - self._last_heartbeat_ts > 30:
            n_positions = len(self.store.positions)
            self.log.info(
                f"HEARTBEAT positions={n_positions} "
                f"trades_today={self.daily_gate.state.n_trades_today} "
                f"pnl_today=${self.daily_gate.state.cumul_pnl_usd:.2f}"
            )
            self._last_heartbeat_ts = now

    def run(self):
        """Boucle principale poll loop."""
        self.log.info(
            f"Bot 1 v2 starting (dry_run={self.dry_run}, "
            f"symbols={self.symbols}, "
            f"trade_account={self.cfg.TRADE_ACCOUNT})"
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
            time.sleep(self.cfg.POLL_INTERVAL_SEC)
        self.store.save()
        self.log.info("Bot 1 v2 stopped cleanly.")


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
        # En prod : import DTC connector legacy
        try:
            from BOT.dtc_connector import DTCConnector
            dtc_connector = DTCConnector(
                host="127.0.0.1", port=11099,
                trade_account=cfg.TRADE_ACCOUNT,
            )
            dtc_connector.connect()
            logging.info(f"DTC connector connected (Sim2)")
        except Exception as e:
            logging.error(f"DTC connector failed: {e}. Falling back to dry-run.")
            dry_run = True

    bot = Bot1V2(
        symbols=symbols, cfg=cfg, dry_run=dry_run,
        dtc_connector=dtc_connector,
    )
    bot.run()


if __name__ == "__main__":
    main()
