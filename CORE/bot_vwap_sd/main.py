"""Main orchestrateur Bot 5 VWAP-SD (Sim3 emplacement, swap Bot 3 BN V4).

Boucle principale :
  1. Pour chaque symbole, read_last_bar() depuis sierra_enriched
  2. Check fraicheur (DMP_BAR_MAX_AGE_SEC)
  3. Position existante ? Skip new entry (1 position max par symbole)
  4. Session gate (RTH only US, skip 15min post-open)
  5. Cooldown gate (5min apres entry/exit)
  6. Daily limits gate (Mark Douglas : 5 trades, -$200/+$150)
  7. VwapSdSignalEngine.on_bar(bar) -> SignalDecision
  8. Si tradable -> OrderRouter.send_bracket (TP/SL fixe en ticks)
  9. Log decision JSONL + emit bot_log

Reutilise infra Bot 3 BN V4 (saine) :
  - SierraDataSource (read_last_bar + freshness)
  - DailyLimitsGate + SessionGate (via SimpleNamespace adapter)
  - PositionStore + StateBridge sub-class Sim3
  - OrderRouter + DtcConnector (OCO bracket TP/SL fixe)
  - DtcFillListener pour fermeture position au fill

DIFFERENCES vs Bot 3 BN V4 :
  - PAS de RegimeGate (pas necessaire pour VWAP-SD simple)
  - PAS de TrailingManager (TP/SL fixe, simple bracket)
  - PAS de warmup_from_disk (signal_engine stateless)
  - 1 setup champion (Setup A) actif par defaut, B/C/D en SHADOW

Usage :
  python -m CORE.bot_vwap_sd.main --symbols NQ --dry-run --verbose
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Reuse Bot 1 v2 / Bot BN V4 infra
from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.data_source import SierraDataSource
from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
from CORE.bot1_v2.gates.session import SessionGate
from CORE.bot1_v2.state.position_store import PositionStore

from CORE.bot_bn_v4.execution.order_router import OrderRouter

from CORE.bot_vwap_sd.config import VwapSdConfig
from CORE.bot_vwap_sd.logger import bot_log, log_decision_jsonl
from CORE.bot_vwap_sd.signal_engine import VwapSdSignalEngine, SignalDecision
from CORE.bot_vwap_sd.state_bridge import VwapSdStateBridge


def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _bot_log_emit_safe(code: str, **ctx) -> None:
    """Wrapper safe pour bot_log.emit (jamais raise)."""
    try:
        bot_log.emit(code, **ctx)
    except Exception:  # noqa: BLE001
        pass


class BotVwapSd:
    """Orchestrateur Bot 5 VWAP-SD."""

    def __init__(
        self,
        symbols: tuple = ("NQ", "ES"),
        dry_run: bool = False,
        cfg: VwapSdConfig = None,
        dtc_connector=None,
    ):
        self.cfg = cfg or VwapSdConfig.from_env()
        self.symbols = tuple(s.upper() for s in symbols)
        self.dry_run = dry_run
        self.log = logging.getLogger("bot_vwap_sd")

        # State persistence
        root = Path(__file__).resolve().parents[2]
        positions_path = root / "DATA" / "PAPER_TRADES" / "bot_vwap_sd_runtime_positions.json"
        self.store = PositionStore(path=positions_path)
        loaded = self.store.load()
        state_status = "OK" if loaded else "NEW_NO_FILE"
        self.log.info(f"State load: {state_status}")
        _bot_log_emit_safe("BOTVWAPSD_STATE_LOAD", status=state_status)

        # Per-symbol engines
        self.signals: dict[str, VwapSdSignalEngine] = {}
        self.data_sources: dict[str, SierraDataSource] = {}

        # Bot1V2Config minimal pour SierraDataSource (duck-type)
        self.bot1v2_cfg = Bot1V2Config()

        for sym in self.symbols:
            self.signals[sym] = VwapSdSignalEngine(
                symbol=sym, cfg=self.cfg, log_fn=_bot_log_emit_safe,
            )
            self.data_sources[sym] = SierraDataSource(symbol=sym, cfg=self.bot1v2_cfg)

        # SessionGate adapter (duck-type SimpleNamespace, eviter heritage Bot 2)
        _session_cfg = SimpleNamespace(
            TRADABLE_SESSIONS=self.cfg.TRADABLE_SESSIONS,
            EOD_LOCKOUT_MINUTES=self.cfg.EOD_LOCKOUT_MINUTES,
        )
        self.session_gate = SessionGate(_session_cfg)

        # DailyLimitsGate adapter (force seuils VwapSd, anti silent fallback)
        _daily_cfg = SimpleNamespace(
            MAX_TRADES_PER_DAY=self.cfg.MAX_TRADES_PER_DAY,
            DAILY_STOP_LOSS_USD=self.cfg.DAILY_STOP_LOSS_USD,
            DAILY_STOP_WIN_USD=self.cfg.DAILY_STOP_WIN_USD,
        )
        self.daily_gate = DailyLimitsGate(_daily_cfg)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily_gate.reset_for_new_day(today)

        # OrderRouter (reuse Bot 3 BN V4 - same DTC OCO logic)
        self.router = OrderRouter(
            cfg=self.cfg, dry_run=dry_run, dtc_connector=dtc_connector,
        )

        # State bridge dashboard Sim3 VWAP-SD
        self.state_bridge = VwapSdStateBridge()

        # Fill listener (shared Bot 1 v2)
        from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
        if dtc_connector is not None:
            self.fill_listener = DtcFillListener(
                cfg=self.cfg, store=self.store, state_bridge=self.state_bridge,
                on_close_callback=self._on_fill_close,
                bot_id="bot_vwap_sd",
            )
            try:
                dtc_connector.on_order_update = self.fill_listener.handle_order_update
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"dtc.on_order_update wire fail: {e}")
        else:
            self.fill_listener = None

        # Cooldown tracking : timestamp ms du prochain trade autorise par symbole
        self._cooldown_until_ms: dict[str, int] = {sym: 0 for sym in self.symbols}

        self._running = False
        self._last_heartbeat_ts = 0.0
        self._last_reconnect_attempt = 0.0
        self._current_day = today

    def _on_fill_close(self, sym: str, pnl_usd: float) -> None:
        """Callback DtcFillListener post-close : apply PnL + cooldown."""
        try:
            self.daily_gate.apply_pnl(pnl_usd)
            # Cooldown apres exit
            cooldown_ms = int(self.cfg.COOLDOWN_MINUTES * 60 * 1000)
            self._cooldown_until_ms[sym] = int(time.time() * 1000) + cooldown_ms
            _bot_log_emit_safe(
                "BOTVWAPSD_FILL_CLOSE",
                sym=sym, pnl_usd=pnl_usd,
                daily_pnl=self.daily_gate.state.cumul_pnl_usd,
            )
        except Exception as e:  # noqa: BLE001
            self.log.error(f"_on_fill_close error: {e}")

    def _rotate_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_day:
            self.log.info(f"Day rotation: {self._current_day} -> {today}")
            self.daily_gate.reset_for_new_day(today)
            self._current_day = today
            _bot_log_emit_safe("BOTVWAPSD_DAY_ROTATE", new_day=today)

    def _in_cooldown(self, sym: str) -> bool:
        return int(time.time() * 1000) < self._cooldown_until_ms[sym]

    def _check_skip_first_minutes_rth(self, bar: dict) -> bool:
        """True si on doit skip (15min apres open RTH 13:30 UTC)."""
        if self.cfg.SKIP_FIRST_MINUTES_RTH <= 0:
            return False
        ts = bar.get("ts_event")
        if ts is None:
            return False
        try:
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                dt = ts
            # RTH open = 13:30 UTC (= 09:30 ET)
            open_dt = dt.replace(hour=13, minute=30, second=0, microsecond=0)
            elapsed_min = (dt - open_dt).total_seconds() / 60.0
            return 0 <= elapsed_min < self.cfg.SKIP_FIRST_MINUTES_RTH
        except Exception:  # noqa: BLE001
            return False

    def _process_symbol(self, sym: str) -> None:
        """Boucle 1 symbole : poll bar -> gates -> signal -> bracket."""
        bar = self.data_sources[sym].read_last_bar()
        if bar is None:
            return

        # Freshness
        if not self.data_sources[sym].is_fresh(bar, self.cfg.DMP_BAR_MAX_AGE_SEC):
            return

        bar_ts = bar.get("ts_event", "?")
        session_phase = bar.get("session_segment", "?")

        # Position deja ouverte ? Skip (1 position max par symbole)
        if self.store.has_open_position(sym):
            return

        # Cooldown ?
        if self._in_cooldown(sym):
            return

        # Session gate (RTH only US)
        sg = self.session_gate.check_allow_entry(bar)
        if not sg.allowed:
            return

        # Skip first 15min RTH (anti-volatility open)
        if self._check_skip_first_minutes_rth(bar):
            _bot_log_emit_safe(
                "BOTVWAPSD_SKIP_FIRST_15MIN_RTH",
                sym=sym, bar_ts=bar_ts,
            )
            return

        # Daily limits (Mark Douglas)
        dg = self.daily_gate.check_allow_entry()
        if not dg.allowed:
            _bot_log_emit_safe(
                "BOTVWAPSD_GATE_DAILY_BLOCK",
                sym=sym, reason=dg.skip_reason,
            )
            return

        # SignalEngine evaluation
        decision: SignalDecision = self.signals[sym].on_bar(bar)

        # Logger TOUTES les decisions (audit + dashboard)
        log_decision_jsonl(
            bar_ts=bar_ts, symbol=sym,
            direction=decision.direction,
            setup_id=decision.setup_id,
            tradable=decision.tradable,
            skip_reason=decision.skip_reason or "",
            session_phase=session_phase,
            shadow=decision.shadow,
            snapshot=decision.snapshot,
        )

        # Shadow detecte mais pas trade : emit dedie
        if decision.shadow and decision.setup_id:
            _bot_log_emit_safe(
                "BOTVWAPSD_SHADOW_DETECTED",
                sym=sym, setup_id=decision.setup_id,
                direction=decision.direction,
                skip_reason=decision.skip_reason,
            )
            return

        if not decision.tradable:
            return

        # Setup TRADABLE : envoi bracket TP/SL fixe
        entry_price = bar.get("close")
        if entry_price is None:
            _bot_log_emit_safe(
                "BOTVWAPSD_SKIP_NO_CLOSE", sym=sym, bar_ts=bar_ts,
            )
            return

        _bot_log_emit_safe(
            "BOTVWAPSD_TRADABLE",
            sym=sym, setup_id=decision.setup_id,
            direction=decision.direction,
            entry_price=entry_price,
            tp_ticks=decision.tp_ticks,
            sl_ticks=decision.sl_ticks,
        )

        # OrderRouter.send_entry : interface Bot 3 BN V4
        # SLTP fixe = on n'utilise pas le trailing
        try:
            from CORE.bot_bn_v4.execution.order_router import EntrySetup
            entry_setup = EntrySetup(
                direction=decision.direction,
                entry_price=entry_price,
                sl_ticks=decision.sl_ticks,
                tp_ticks=decision.tp_ticks,
                n_micros=self.cfg.N_MICROS_DEFAULT,
                grade=decision.setup_id,  # Reuse grade field pour setup_id
            )
            result = self.router.send_entry(sym, entry_setup)
        except Exception as e:  # noqa: BLE001
            self.log.error(f"send_entry error sym={sym}: {e}")
            _bot_log_emit_safe(
                "BOTVWAPSD_ORDER_FAIL",
                sym=sym, setup_id=decision.setup_id, err=str(e)[:200],
            )
            return

        if not result.success:
            _bot_log_emit_safe(
                "BOTVWAPSD_ORDER_FAIL",
                sym=sym, setup_id=decision.setup_id, err=result.error or "?",
            )
            return

        # Position ouverte
        self.daily_gate.register_open()
        cooldown_ms = int(self.cfg.COOLDOWN_MINUTES * 60 * 1000)
        self._cooldown_until_ms[sym] = int(time.time() * 1000) + cooldown_ms

        _bot_log_emit_safe(
            "BOTVWAPSD_ORDER_SENT",
            sym=sym, setup_id=decision.setup_id,
            direction=decision.direction,
            parent_cid=result.parent_cid,
            fill_price=result.fill_price or 0.0,
        )

    def run(self, dtc_connector=None) -> None:
        """Boucle principale."""
        # Connect DTC
        if dtc_connector is not None:
            connected = dtc_connector.connect()
            if not connected:
                self.log.error("DTC connect FAILED - fallback dry_run")
                self.dry_run = True
                dtc_connector = None
                _bot_log_emit_safe("BOTVWAPSD_DTC_BOOT_FAIL")
            else:
                self.log.info(f"DTC connector connected (TA={self.cfg.TRADE_ACCOUNT})")
                _bot_log_emit_safe(
                    "BOTVWAPSD_DTC_CONNECTED",
                    trade_account=self.cfg.TRADE_ACCOUNT,
                )

        signal.signal(signal.SIGINT, self.stop)
        try:
            signal.signal(signal.SIGTERM, self.stop)
        except (AttributeError, ValueError):
            pass

        self._running = True
        _bot_log_emit_safe(
            "BOTVWAPSD_BOOT_READY",
            symbols=list(self.symbols),
            dry_run=self.dry_run,
            setups_active=[k for k, v in self.signals[self.symbols[0]].describe_setups().items() if v.get("enabled")],
        )

        while self._running:
            try:
                self._rotate_day_if_needed()
                for sym in self.symbols:
                    self._process_symbol(sym)
                # Heartbeat (every 30s)
                now = time.time()
                if now - self._last_heartbeat_ts > 30:
                    self._last_heartbeat_ts = now
                    _bot_log_emit_safe(
                        "BOTVWAPSD_HEARTBEAT",
                        symbols=list(self.symbols),
                        daily_pnl=self.daily_gate.state.cumul_pnl_usd,
                        n_trades_today=self.daily_gate.state.n_trades,
                    )
                time.sleep(self.cfg.POLL_INTERVAL_SEC)
            except KeyboardInterrupt:
                break
            except Exception as e:  # noqa: BLE001
                self.log.error(f"loop error: {e}", exc_info=True)
                _bot_log_emit_safe("BOTVWAPSD_LOOP_ERROR", err=str(e)[:200])
                time.sleep(self.cfg.POLL_INTERVAL_SEC)

        self.log.info("Bot stop.")
        _bot_log_emit_safe("BOTVWAPSD_SHUTDOWN")

    def stop(self, *args, **kwargs) -> None:
        self.log.info("Stop signal received.")
        self._running = False


def main():
    parser = argparse.ArgumentParser(description="Bot 5 VWAP-SD (Sim3 emplacement)")
    parser.add_argument(
        "--symbols", type=str, default="NQ",
        help="Comma-separated symbols (defaut: NQ - champion Setup A only)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Pas de DTC, log only")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--prod", action="store_true", help="Connect DTC reel")
    args = parser.parse_args()

    _setup_logging(verbose=args.verbose)
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())

    cfg = VwapSdConfig.from_env()

    dtc_connector = None
    if args.prod and not args.dry_run:
        try:
            from CORE.bot1_v2.dtc_factory import build_dtc_connector
            dtc_connector = build_dtc_connector(
                cfg.TRADE_ACCOUNT,
                client_name="MIA_BotVwapSd",
            )
        except Exception as e:  # noqa: BLE001
            logging.error(f"DTC build fail: {e}")
            sys.exit(1)

    bot = BotVwapSd(
        symbols=symbols, dry_run=args.dry_run,
        cfg=cfg, dtc_connector=dtc_connector,
    )
    bot.run(dtc_connector=dtc_connector)


if __name__ == "__main__":
    main()
