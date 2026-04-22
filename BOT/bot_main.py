"""
bot_main.py — Boucle principale MIA Bot V2
=============================================

Orchestre : pre-trade gates → signal → risk → execution → monitor → journal.

Usage :
    python bot_main.py                    # Paper trading
    python bot_main.py --live             # Live (DANGEREUX)
    python bot_main.py --symbol ES        # Un seul instrument
    python bot_main.py --dry-run          # Simulation sans DTC

Auteur : MIA Trading System
Date   : 2026-04-01
"""

import sys
import time
import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# Ajouter BOT et CORE au path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "CORE"))
sys.path.insert(0, str(Path(__file__).parent.parent))  # Pour CORE.logging_v2

from bot_config import BotConfig, CONFIG
from risk_manager import RiskManager
from signal_engine import SignalEngine, Signal
from order_manager import OrderManager
from position_monitor import PositionMonitor
from trade_journal import TradeJournal, TradeRecord
from dtc_connector import DTCConnector
from discord_alerter import DiscordAlerter
from heartbeat_writer import HeartbeatWriter

# Modules CORE pour features
from dmp_reader import DmpReader
from rolling_features import RollingFeatures
from intermarket_features import IntermarketFeatures
from rule_engine import RuleEngine

# Systeme logs V2 (22/04/2026) : structure par categorie + codes stables
try:
    from CORE.logging_v2 import get_logger as _get_v2_logger
    _v2log = _get_v2_logger("bot_main", process="bot_legacy")
except Exception:
    _v2log = None

logger = logging.getLogger("MIA")


class MIABot:
    """Bot de trading MIA V2."""

    def _setup_logging(self):
        """Configure le logging fichier + console."""
        log_dir = Path(__file__).parent.parent / "DATA" / "LOGS"
        log_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        log_file = log_dir / f"{today}_bot.log"

        # Logger racine MIA
        mia_logger = logging.getLogger("MIA")
        mia_logger.setLevel(logging.DEBUG)

        # Eviter les doublons si deja configure
        if mia_logger.handlers:
            return

        # Format
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(message)s",
            datefmt="%H:%M:%S"
        )

        # Handler fichier (tout)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        mia_logger.addHandler(fh)

        # Handler console (INFO+)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        mia_logger.addHandler(ch)

        # Aussi capturer les loggers des sous-modules
        for name in ["dtc_connector", "order_manager", "risk_manager",
                      "signal_engine", "trade_journal", "rule_engine"]:
            sub = logging.getLogger(name)
            sub.setLevel(logging.DEBUG)
            sub.addHandler(fh)

        logger.info(f"Logs: {log_file}")

    def __init__(self, config: BotConfig = None, dry_run: bool = True):
        self.cfg = config or CONFIG
        self.dry_run = dry_run

        # Modules
        self.journal = TradeJournal(self.cfg.trade_journal_path)
        self.risk = RiskManager(self.cfg)
        self.signal_engine = SignalEngine(self.cfg)

        # DTC (desactive en dry-run)
        if not self.dry_run:
            self.dtc = DTCConnector(self.cfg.dtc)
        else:
            self.dtc = None

        self.orders = None  # Initialise au start
        self.monitor = None

        # Monitoring V2 : Discord alerts + heartbeat (repris du V1)
        self.alerter = DiscordAlerter()
        self.heartbeat = HeartbeatWriter(
            interval_seconds=30,
            stats_provider=self._get_heartbeat_stats,
        )

        self._running = False
        self._symbols = []
        self._stats_start_time = time.time()
        self._trades_today_count = 0
        self._pnl_today_usd = 0.0

        # RuleEngine — utilise quand pas de modele ML
        self.rule_engine = RuleEngine()
        self._rule_sltp_cache: dict = {}   # {symbol: (sl_ticks, tp_ticks)}
        self._pending_snapshot: dict = {}  # {symbol: features_dict}

        # Data feed DMP — cache des barres par symbole
        self._data_dir = Path(__file__).parent.parent / "DATA"
        self._dmp_reader = DmpReader(str(self._data_dir))
        self._rolling = RollingFeatures()
        self._intermarket = IntermarketFeatures()
        self._last_bar_count: dict = {}  # {symbol: nb barres vues}
        self._features_cache: dict = {}  # {symbol: dernier dict features}
        self._last_bar_time: dict = {}   # {symbol: timestamp derniere barre}

        # Dashboard JSON
        self._dashboard_path = (
            Path(__file__).parent.parent / "DASHBOARD"
            / "MIA_AutoTrader_Dashboard.json"
        )

    def start(self, symbols: list = None):
        """Demarre le bot."""
        self._symbols = symbols or ["ES", "NQ"]

        # Setup logging fichier + console
        self._setup_logging()

        mode = "DRY RUN" if self.dry_run else "PAPER" if self.cfg.paper_trading else "LIVE"
        logger.info(f"{'='*60}")
        logger.info(f"  MIA BOT V2 — {mode}")
        logger.info(f"  Symbols: {', '.join(self._symbols)}")
        logger.info(f"  Max trades/jour: {self.cfg.risk.max_daily_trades}")
        logger.info(f"  Max loss/jour: ${self.cfg.risk.max_daily_loss_usd}")
        logger.info(f"  Position max: {self.cfg.risk.max_positions_total}")
        logger.info(f"{'='*60}")

        # V2 log structure : boot signal
        if _v2log:
            _v2log.emit("BOOT_START", component=f"MIA_BOT_{mode}", version="V2", pid=os.getpid())

        # Charger les modeles ML
        for sym in self._symbols:
            if self.signal_engine.load_models(sym):
                logger.info(f"[ML] {sym}: modeles charges")
                if _v2log:
                    _v2log.emit("ML_MODEL_LOADED", version=sym, n_features=0)
            else:
                logger.info(f"[ML] {sym}: pas de modele -> RuleEngine actif")
                if _v2log:
                    _v2log.emit("ML_MODEL_LOAD_FAIL", path=sym, err="fallback_rule_engine")

        # Connexion DTC
        if not self.dry_run:
            logger.info("[DTC] Connexion a Sierra Chart...")
            if self.dtc.connect():
                logger.info("[DTC] Connecte")
                if _v2log:
                    _v2log.emit("DTC_CONNECT", host=self.cfg.dtc.host, port=self.cfg.dtc.port)
                self.orders = OrderManager(self.cfg, self.dtc)
                self.monitor = PositionMonitor(self.cfg, self.orders, self.journal)

                # CRITIQUE : brancher le callback de fermeture pour journal + risk
                self.orders.on_trade_close = self._on_trade_close

                # Prix via JSONL (DTC market data non supporte par SC serveur)
                logger.info("[PRIX] Via derniere barre JSONL (fallback DTC)")
            else:
                logger.info("[DTC] ECHEC — passage en dry-run")
                if _v2log:
                    _v2log.emit("DTC_DISCONNECT", reason="connect_failed_fallback_dry_run")
                self.dry_run = True

        self.journal.log_event("BOT_START", f"symbols={self._symbols} dry_run={self.dry_run}")

        # Demarre le heartbeat writer (thread daemon)
        self._stats_start_time = time.time()
        self.heartbeat.start()

        # Alerte Discord : bot demarre
        self.alerter.send_bot_start({
            "pid": os.getpid(),
            "version": "V2",
            "mode": mode,
            "symbols": ",".join(self._symbols),
            "session": "SIM3" if self.cfg.paper_trading else "LIVE",
        })

        # Boucle principale
        self._running = True
        self._main_loop()

    def stop(self, reason: str = "manual"):
        """Arrete le bot proprement."""
        self._running = False

        # Flatten toutes les positions
        if self.orders and self.orders.total_positions > 0:
            logger.info("[STOP] Flatten toutes les positions...")
            self.orders.flatten_all("BOT_STOP")

        # Deconnexion
        if self.dtc:
            self.dtc.disconnect()

        # Arret heartbeat
        try:
            self.heartbeat.stop()
        except Exception:
            pass

        # Rapport
        summary = self.journal.daily_summary()
        logger.info(summary)
        self.journal.log_event("BOT_STOP", summary)

        # Alerte Discord : bot arrete
        try:
            self.alerter.send_bot_stop(reason)
        except Exception:
            pass

        logger.info("=" * 60)
        logger.info("  MIA BOT V2 ARRETE")
        logger.info("=" * 60)

    def _main_loop(self):
        """Boucle principale — execute a chaque barre (1 min)."""
        logger.info("[LOOP] Boucle principale demarree (Ctrl+C pour arreter)")
        self._tick_count = 0
        self._last_status_log = 0

        # Kill switch flag file (check chaque tick)
        self._stop_flag_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "DATA", "BOT_CONTROL", "STOP.flag"
        )

        consecutive_errors = 0
        try:
            while self._running:
                # Kill switch check — prioritaire sur tout
                if os.path.exists(self._stop_flag_file):
                    reason = "unknown"
                    try:
                        with open(self._stop_flag_file, "r", encoding="utf-8") as f:
                            info = json.loads(f.read())
                            reason = info.get("reason", "manual")
                    except Exception:
                        pass
                    logger.warning(f"[KILL_SWITCH] STOP.flag detecte (reason={reason}) — flatten + arret")
                    # V2 log structure : kill-switch manuel
                    if _v2log:
                        _v2log.emit("KILL_DD_DAILY", pnl=0.0, limit=0.0,
                                    signal_id=f"manual_stop_{reason}")
                    self.journal.log_event("KILL_SWITCH", f"STOP.flag reason={reason}")
                    positions_before = 0
                    if self.orders:
                        positions_before = self.orders.total_positions
                        if positions_before > 0:
                            logger.info("[KILL_SWITCH] Flatten toutes positions...")
                            self.orders.flatten_all("KILL_SWITCH")
                            time.sleep(3)  # laisser le temps aux cancels
                    try:
                        self.alerter.send_kill_switch(reason, positions_before)
                    except Exception:
                        pass
                    break  # sort de la boucle

                try:
                    self._tick()
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(f"[TICK_ERROR] {e}")
                    if consecutive_errors >= 10:
                        logger.error(f"[FATAL] {consecutive_errors} erreurs consecutives — arret")
                        if _v2log:
                            _v2log.emit("BOT_CRASH", exc_type="ConsecutiveErrors",
                                        exc_msg=f"{consecutive_errors} erreurs consecutives")
                        break
                    time.sleep(5)  # Pause avant retry
                    continue

                self._tick_count += 1

                # Dashboard JSON a chaque tick
                self._write_dashboard()

                # Log status toutes les 5 minutes (300 ticks)
                now = time.time()
                if now - self._last_status_log >= 300:
                    self._log_status()
                    self._last_status_log = now

                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("[CTRL+C] Arret demande...")
            self._stop_reason = "KeyboardInterrupt"
            if _v2log:
                _v2log.emit("BOT_SHUTDOWN", reason="KeyboardInterrupt")
        except Exception as e:
            logger.error(f"[CRASH] Exception non geree: {e}", exc_info=True)
            # V2 log structure : crash avec stacktrace capturee
            if _v2log:
                _v2log.emit("BOT_CRASH", exc_type=e.__class__.__name__,
                            exc_msg=str(e)[:200], exc=e)
            self.journal.log_event("CRASH", str(e))
            try:
                self.alerter.send_crash("bot_main._main_loop", str(e))
            except Exception:
                pass
            self._stop_reason = f"crash: {str(e)[:200]}"
        finally:
            # TOUJOURS fermer les positions, meme en cas de crash
            if self.orders and self.orders.total_positions > 0:
                logger.info("[SAFETY] Flatten d'urgence...")
                self.orders.flatten_all("CRASH_FLATTEN")
            self.stop(reason=getattr(self, "_stop_reason", "manual"))

    def _log_status(self):
        """Log periodique de l'etat du bot."""
        for sym in self._symbols:
            price = self._get_current_price(sym)
            bars = self._last_bar_count.get(sym, 0)
            daily = self.rule_engine._daily_signals.get(sym, 0)
            pos = "FLAT"
            if self.orders and self.orders.has_position(sym):
                p = self.orders.get_position(sym)
                pos = f"{'LONG' if p.direction==1 else 'SHORT'} @{p.entry_price:.2f}"
            logger.info(f"[STATUS] {sym} price={price:.2f} bars={bars} "
                        f"signals_today={daily} pos={pos}")

    def _get_dashboard_features(self, symbol: str) -> dict:
        """Extrait les features pertinentes pour le dashboard web."""
        cache = self._features_cache.get(symbol, {})
        if not cache:
            return {}
        return {
            # Order Flow
            "delta_bar": cache.get("delta_bar", 0),
            "delta_pct": cache.get("delta_pct", 0),
            "cvd_day": cache.get("cvd_day", 0),
            "cvd_day_dir": cache.get("cvd_day_dir", 0),
            "rvol": cache.get("rvol", 1.0),
            "rvol_regime": cache.get("rvol_regime", 1),
            "ctx_absorption_score_5": cache.get("ctx_absorption_score_5", 0),
            "ctx_absorption_streak_5": cache.get("ctx_absorption_streak_5", 0),
            "ctx_price_delta_div_3": cache.get("ctx_price_delta_div_3", 0),
            "ctx_climax_signal": cache.get("ctx_climax_signal", 0),
            "large_trader_ratio": cache.get("large_trader_ratio", 0),
            "ask_bid_imbalance": cache.get("ask_bid_imbalance", 0),
            "finish_strength": cache.get("finish_strength", 0),
            # Options Gamma
            "dist_mq_call": cache.get("dist_mq_call", 0),
            "dist_mq_put": cache.get("dist_mq_put", 0),
            "dist_mq_hvl": cache.get("dist_mq_hvl", 0),
            "dist_mq_call_0dte": cache.get("dist_mq_call_0dte", 0),
            "dist_mq_put_0dte": cache.get("dist_mq_put_0dte", 0),
            "dist_gex_nearest_up": cache.get("dist_gex_nearest_up", 0),
            "dist_gex_nearest_dn": cache.get("dist_gex_nearest_dn", 0),
            "gex_cluster_count": cache.get("gex_cluster_count", 0),
            "bool_gex_flip_zone": cache.get("bool_gex_flip_zone", False),
            "vix_level": cache.get("vix_level", 0),
            "vix_regime": cache.get("vix_regime", 0),
            "dist_vix_call": cache.get("dist_vix_call", 0),
            "dist_vix_put": cache.get("dist_vix_put", 0),
            "next_wall_dist_ticks": cache.get("next_wall_dist_ticks", 0),
            "next_wall_is_call": cache.get("next_wall_is_call", False),
            # Intermarket + AMD
            "im_cross_delta_agreement_5": cache.get(
                "im_cross_delta_agreement_5", 0
            ),
            "im_smt_divergence": cache.get("im_smt_divergence", 0),
            "im_rolling_correlation_10": cache.get(
                "im_rolling_correlation_10", 1.0
            ),
            "im_price_ratio_slope_10": cache.get(
                "im_price_ratio_slope_10", 0
            ),
            "im_volume_lead": cache.get("im_volume_lead", 0),
            "im_ltr_slope_diff": cache.get("im_ltr_slope_diff", 0),
            "amd_phase": cache.get("amd_phase", 0),
            "amd_session_bias": cache.get("amd_session_bias", 0),
            "amd_po3_score": cache.get("amd_po3_score", 0),
            "amd_po3_bullish": cache.get("amd_po3_bullish", False),
            "amd_po3_bearish": cache.get("amd_po3_bearish", False),
            "amd_judas_swing": cache.get("amd_judas_swing", False),
            "amd_manip_score": cache.get("amd_manip_score", 0),
            # Market Context
            "open_type": cache.get("open_type", 0),
            "open_zone": cache.get("open_zone", 0),
            "day_type": cache.get("day_type", 2),
            "profile_shape": cache.get("profile_shape", 0),
            "poc_position": cache.get("poc_position", 0),
            "ib_range_ticks": cache.get("ib_range_ticks", 0),
            "ib_broken_up": cache.get("ib_broken_up", False),
            "ib_broken_down": cache.get("ib_broken_down", False),
            "trend_day_probability": cache.get("trend_day_probability", 0),
            "vwap_triple_align": cache.get("vwap_triple_align", 0),
            "vwap_d_side": cache.get("vwap_d_side", 0),
            "session_id": cache.get("session_id", ""),
        }

    def _write_dashboard(self):
        """Ecrit le JSON dashboard pour le frontend web."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode = (
            "DRY RUN" if self.dry_run
            else "PAPER" if self.cfg.paper_trading
            else "LIVE"
        )

        # Statut par instrument
        instruments = {}
        for sym in self._symbols:
            in_pos = (
                self.orders and self.orders.has_position(sym)
                if self.orders else False
            )
            pos_status = "FLAT"
            if in_pos:
                p = self.orders.get_position(sym)
                direction = "LONG" if p.direction == 1 else "SHORT"
                pos_status = f"{direction} @{p.entry_price:.2f}"

            price = self._get_current_price(sym)
            daily_signals = self.rule_engine._daily_signals.get(sym, 0)

            instruments[sym.lower()] = {
                "enabled": sym in self._symbols,
                "in_position": in_pos,
                "status": pos_status,
                "price": round(price, 2),
                "trades_today": daily_signals,
                "wins": 0,
                "losses": 0,
                "pnl_today": 0.0,
                "consecutive_losses": 0,
                "last_rejected": "",
                "signals_rejected": 0,
            }

        dashboard = {
            "bot_status": {
                "running": self._running,
                "last_heartbeat": now_str,
                "global_status": mode,
            },
            **instruments,
            "market_live": {
                "vix": self._features_cache.get("ES", {}).get(
                    "vix_level", 0
                ),
                "vix_regime": self._features_cache.get("ES", {}).get(
                    "vix_regime", 0
                ),
                "atr_es": self._features_cache.get("ES", {}).get(
                    "atr_14", 0
                ),
                "atr_nq": self._features_cache.get("NQ", {}).get(
                    "atr_14", 0
                ),
                "vwap_slope_es": self._features_cache.get("ES", {}).get(
                    "vwap_slope", 0
                ),
                "vwap_slope_nq": self._features_cache.get("NQ", {}).get(
                    "vwap_slope", 0
                ),
            },
            "features_es": self._get_dashboard_features("ES"),
            "features_nq": self._get_dashboard_features("NQ"),
        }

        try:
            self._dashboard_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._dashboard_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dashboard, f, indent=2, default=str)
            tmp.replace(self._dashboard_path)
        except Exception as e:
            logger.warning(f"Erreur ecriture dashboard: {e}")

    def _tick(self):
        """Un cycle de la boucle — verifie signaux et positions."""
        now = datetime.now(timezone.utc)

        for sym in self._symbols:
            instrument = self.cfg.get_instrument(sym)

            # ── 1. Construire les features (alimente le dashboard) ──
            self._build_features(sym)

            # ── 2. Verifier les positions existantes ──
            if self.orders and self.orders.has_position(sym):
                if not self.dry_run:
                    self._check_position(sym, instrument)
                continue

            # ── 3. Pre-trade gates ──
            allowed, reason = self.risk.can_trade(sym, 0, instrument)
            if not allowed:
                continue

            # P0-4 : Check fraicheur de la derniere barre DMP (< 90s)
            last_bar_age = time.time() - self._last_bar_time.get(sym, 0)
            if last_bar_age > 90:
                self.journal.log_rejection(sym, f"Barre DMP stale ({last_bar_age:.0f}s)", 0)
                continue

            # En dry-run, pas de signaux ni d'execution
            if self.dry_run:
                continue

            signal = self._get_signal(sym)
            if signal.direction == 0:
                continue

            # ── 4. MenthorQ gate — FAIL-CLOSED si pas de donnee ──
            features = self._features_cache.get(sym, {})
            if "mq_gamma_condition" not in features or features.get("mq_gamma_condition") is None:
                self.journal.log_rejection(sym, "Pas de donnee gamma MQ (fail-closed)", signal.score)
                continue
            gamma = float(features["mq_gamma_condition"])
            mq_ok, mq_reason = self.signal_engine.check_menthorq_gate(
                signal.direction, gamma)
            if not mq_ok:
                self.journal.log_rejection(sym, mq_reason, signal.score)
                continue

            # ── 5. Risk check final ──
            allowed, reason = self.risk.can_trade(sym, signal.direction, instrument)
            if not allowed:
                self.journal.log_rejection(sym, reason, signal.score)
                continue

            # ── 6. Position sizing (SL/TP du RuleEngine ou ATR-based) ──
            if sym in self._rule_sltp_cache:
                sl_ticks, tp_ticks = self._rule_sltp_cache.pop(sym)
            else:
                features = self._features_cache.get(sym, {})
                # ATR dans le JSONL = atr_daily en TICKS (verifie 09/04)
                atr_ticks = features.get("atr", 0) or features.get("atr_14", 0)
                if atr_ticks > 0:
                    # SL = ATR_ticks * 0.08 (coherent paper trader + ML labeler)
                    sl_ticks = max(10, atr_ticks * instrument.atr_sl_mult)
                else:
                    sl_ticks = 20
                tp_ticks = sl_ticks * instrument.rr_ratio

            position_size = self.risk.compute_position_size(
                instrument, sl_ticks)

            # ── 7. Execution ──
            self._execute_trade(sym, signal, instrument, position_size,
                                 sl_ticks, tp_ticks)

    def _get_current_price(self, symbol: str) -> float:
        """Obtient le prix courant. DTC market data → fallback JSONL."""
        # Essayer DTC d'abord
        if self.dtc:
            contract = self.cfg.get_instrument(symbol).contract
            price = self.dtc.get_current_price(contract)
            if price > 0:
                return price

        # Fallback : derniere barre du JSONL
        features = self._features_cache.get(symbol, {})
        price = features.get("price", 0)
        if price and price > 0:
            return float(price)

        return 0.0

    def _get_signal(self, symbol: str) -> Signal:
        """
        Obtient le signal pour un symbole.

        Mode 1 (ML) : Si modeles charges → SignalEngine.predict()
        Mode 2 (Rules) : Sinon → RuleEngine.evaluate()

        Chaque signal est snapshote avec les 262 features DMP.
        """
        features = self._build_features(symbol)
        if features is None:
            return Signal(direction=0, reason="Pas de features disponibles")

        # Mode ML si modeles disponibles
        has_model = (symbol in self.signal_engine.models
                     if hasattr(self.signal_engine, 'models') else False)

        if has_model:
            signal = self.signal_engine.predict(symbol, features)
        else:
            # Mode Rules
            rule_sig = self.rule_engine.evaluate(features, symbol=symbol)
            signal = Signal(
                direction=rule_sig.direction,
                score=abs(rule_sig.score),
                confidence=rule_sig.confidence,
                reason=self.rule_engine.summary(rule_sig),
            )
            # SL/TP du RuleEngine (adaptatif aux murs)
            if rule_sig.direction != 0:
                self._rule_sltp_cache[symbol] = (rule_sig.sl_ticks, rule_sig.tp_ticks)

        # Snapshot sera logged dans _execute_trade (quand on a le SL/TP final)
        if signal.direction != 0:
            self._pending_snapshot[symbol] = features

        return signal

    def _log_snapshot(self, symbol: str, features: dict, signal: Signal,
                      sl_ticks: float = 0, tp_ticks: float = 0):
        """
        Sauvegarde un snapshot complet pour le ML futur.
        Contient : signal + TOUTES les features DMP de la barre + SL/TP.
        Le resultat (win/loss/flat) sera ajoute par trade_journal apres cloture.
        """
        snapshot = {
            "snapshot_ts": time.time(),
            "symbol": symbol,
            "signal_direction": signal.direction,
            "signal_score": signal.score,
            "signal_confidence": signal.confidence,
            "signal_reason": signal.reason,
            "sl_ticks": sl_ticks,
            "tp_ticks": tp_ticks,
        }
        # TOUTES les features DMP brutes (la ligne complete qui a declenche)
        for k, v in features.items():
            if isinstance(v, (int, float)):
                snapshot[f"f_{k}"] = v
            elif isinstance(v, str) and len(v) < 50:
                snapshot[f"f_{k}"] = v

        # Sauvegarder en JSONL
        snap_dir = self._data_dir / "SNAPSHOTS"
        snap_dir.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y%m%d")
        snap_file = snap_dir / f"{today}_{symbol}_trades.jsonl"
        try:
            with open(snap_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot, default=str) + "\n")
            logger.info(f"Snapshot sauve: {snap_file.name} "
                        f"{'BUY' if signal.direction==1 else 'SELL'} "
                        f"score={signal.score:.2f}")
        except Exception as e:
            logger.warning(f"Erreur snapshot {symbol}: {e}")

    def _build_features(self, symbol: str) -> dict:
        """
        Construit le vecteur de features pour la derniere barre DMP.
        Retourne None si pas de nouvelle barre.
        """
        # Lire le JSONL le plus RECEMMENT MODIFIE (pas par nom — la date
        # session DMP peut etre en avance sur la date systeme)
        sym_dir = self._data_dir / symbol
        if not sym_dir.exists():
            return None
        jsonl_files = list(sym_dir.glob(f"*_{symbol}.jsonl"))
        if not jsonl_files:
            return None
        jsonl_path = max(jsonl_files, key=lambda f: f.stat().st_mtime)

        # Lire toutes les barres du jour
        try:
            df = self._dmp_reader.load_file(str(jsonl_path))
        except Exception as e:
            logger.warning(f"Erreur lecture DMP {jsonl_path}: {e}")
            return None

        if df is None or len(df) == 0:
            return None

        # Detecter nouvelle barre (eviter de recalculer si pas de changement)
        bar_count = len(df)
        if bar_count == self._last_bar_count.get(symbol, 0):
            return None  # Pas de nouvelle barre

        prev_count = self._last_bar_count.get(symbol, 0)
        self._last_bar_count[symbol] = bar_count
        price = df.iloc[-1].get("price", 0)
        logger.debug(f"[BAR] {symbol} nouvelle barre #{bar_count} price={price} (+{bar_count - prev_count})")

        # Features rolling (ctx_*)
        try:
            df = self._rolling.compute(df)
        except Exception as e:
            logger.warning(f"Erreur rolling features {symbol}: {e}")

        # Features intermarket (im_*) — necessite les 2 symboles
        other = "NQ" if symbol == "ES" else "ES"
        other_dir = self._data_dir / other
        other_files = list(other_dir.glob(f"*_{other}.jsonl")) if other_dir.exists() else []
        other_path = max(other_files, key=lambda f: f.stat().st_mtime) if other_files else None
        if other_path and other_path.exists():
            try:
                df_other = self._dmp_reader.load_file(str(other_path))
                if df_other is not None and len(df_other) > 0:
                    df = self._intermarket.compute(df, df_other)
            except Exception as e:
                logger.warning(f"Erreur intermarket {symbol}: {e}")

        # Features MenthorQ (mq_*) — données daily du scraper
        try:
            from mia_menthorq_reader import MenthorQReader
            mq_dir = self._data_dir / "MENTHORQ"
            if mq_dir.exists():
                mq = MenthorQReader(str(mq_dir))
                # Trouver la date de trading depuis le nom du fichier JSONL
                trading_date = jsonl_path.stem.split("_")[0]  # "20260402"
                tick = self.cfg.get_instrument(symbol).tick_size
                df = mq.enrich(df, trading_date, symbol, tick_size=tick)
                logger.debug(f"[MQ] {symbol} enrichi ({len([c for c in df.columns if c.startswith('mq_')])} features mq_*)")
        except Exception as e:
            logger.warning(f"Erreur MenthorQ {symbol}: {e}")

        # Extraire la derniere ligne comme dict
        last_row = df.iloc[-1].to_dict()
        self._features_cache[symbol] = last_row
        self._last_bar_time[symbol] = time.time()

        return last_row

    def _on_trade_close(self, symbol: str, exit_type: str, exit_price: float,
                         pnl_ticks: float, pnl_usd: float, position):
        """Callback critique appele quand un trade se ferme (TP/SL/manuel).

        - Decremente open_positions dans le risk manager
        - Met a jour consecutive_losses / daily_pnl
        - Ecrit un TradeRecord complet dans le journal
        """
        from datetime import datetime, timezone

        logger.info(f"[TRADE_CLOSE] {symbol} {exit_type} @ {exit_price:.2f} "
                    f"PnL={pnl_ticks:+.0f}t ${pnl_usd:+.2f}")
        # V2 log structure : trade close avec code selon exit_type
        if _v2log:
            code_map = {"TP": "TRADE_CLOSE_TP", "SL": "TRADE_CLOSE_SL",
                         "TRAIL": "TRADE_CLOSE_TRAIL", "BE": "TRADE_CLOSE_BE",
                         "MANUAL": "TRADE_CLOSE_MANUAL", "KILL_SWITCH": "TRADE_CLOSE_KILL",
                         "TIMEOUT": "TRADE_CLOSE_TIMEOUT"}
            v2_code = code_map.get(exit_type, "TRADE_CLOSE_MANUAL")
            if v2_code == "TRADE_CLOSE_MANUAL":
                _v2log.emit(v2_code, sym=symbol, reason=exit_type)
            else:
                _v2log.emit(v2_code, sym=symbol, pnl=pnl_ticks)

        # 1. Risk manager — decrementer open_positions
        try:
            self.risk.on_trade_close(symbol, pnl_usd)
        except Exception as e:
            logger.error(f"risk.on_trade_close error: {e}")

        # 2. Journal — enregistrer le trade complet
        try:
            now = datetime.now(timezone.utc)
            entry_time_str = datetime.fromtimestamp(position.entry_time, tz=timezone.utc).isoformat() if position.entry_time else ""
            duration = (now.timestamp() - position.entry_time) if position.entry_time else 0.0

            trade = TradeRecord(
                symbol=symbol,
                date=now.strftime("%Y%m%d"),
                direction=position.direction,
                entry_price=position.entry_price,
                entry_time=entry_time_str,
                exit_price=exit_price,
                exit_time=now.isoformat(),
                exit_reason=exit_type,
                sl_price=position.sl_price,
                tp_price=position.tp_price,
                position_size=position.quantity,
                pnl_ticks=pnl_ticks,
                pnl_usd=pnl_usd,
                duration_seconds=duration,
                is_winner=pnl_usd > 0,
                paper_trade=self.dry_run,
            )
            self.journal.log_trade(trade)
        except Exception as e:
            logger.error(f"journal.log_trade error: {e}")

        # 3. Mise a jour stats globales + heartbeat
        self._trades_today_count += 1
        self._pnl_today_usd += pnl_usd

        # 4. Alerte Discord : trade ferme
        try:
            direction_str = "LONG" if position.direction == 1 else "SHORT"
            self.alerter.send_trade_closed(
                symbol=symbol,
                direction=direction_str,
                exit_reason=exit_type,
                pnl_ticks=pnl_ticks,
                pnl_usd=pnl_usd,
            )
        except Exception as e:
            logger.debug(f"alerter.send_trade_closed: {e}")

    def _get_heartbeat_stats(self) -> dict:
        """Callback pour le HeartbeatWriter — retourne l'etat courant du bot."""
        dtc_ok = None
        try:
            if self.dtc is not None:
                dtc_ok = bool(getattr(self.dtc, "connected", False)) and (
                    self.dtc.is_alive() if hasattr(self.dtc, "is_alive") else True
                )
        except Exception:
            dtc_ok = None

        # Age de la derniere barre (max sur symbols)
        last_bar_age = None
        if self._last_bar_time:
            now = time.time()
            ages = [now - t for t in self._last_bar_time.values()]
            last_bar_age = round(max(ages), 1) if ages else None

        positions_open = 0
        if self.orders:
            try:
                positions_open = self.orders.total_positions
            except Exception:
                pass

        return {
            "status": "running" if self._running else "stopped",
            "cycles": getattr(self, "_tick_count", 0),
            "trades_today": self._trades_today_count,
            "pnl_today": self._pnl_today_usd,
            "positions_open": positions_open,
            "last_bar_age": last_bar_age,
            "dtc_connected": dtc_ok,
            "symbols": list(self._symbols),
            "start_time": self._stats_start_time,
        }

    def _check_position(self, symbol: str, instrument):
        """Verifie une position ouverte — P&L et time exit."""
        if not self.monitor:
            return
        current_price = self._get_current_price(symbol)
        if current_price <= 0:
            return

        # Mettre a jour le P&L non realise
        self.orders.update_unrealized_pnl(symbol, current_price)

    def _execute_trade(self, symbol: str, signal: Signal,
                        instrument, position_size: int,
                        sl_ticks: float, tp_ticks: float):
        """Execute un trade et sauvegarde le snapshot."""
        dir_str = "BUY" if signal.direction == 1 else "SELL"
        logger.info(f"[TRADE] {symbol} {dir_str} "
                    f"score={signal.score:.3f} conf={signal.confidence} "
                    f"size={position_size} SL={sl_ticks:.0f}t TP={tp_ticks:.0f}t")
        logger.info(f"  -> {signal.reason[:100]}")
        # V2 log structure : signal recu + trade open
        if _v2log:
            _v2log.emit("SIGNAL_RECEIVED", sym=symbol, direction=dir_str, score=signal.score)
            _v2log.emit("TRADE_OPEN", sym=symbol, direction=dir_str,
                        size=position_size, price=0.0)  # price fill callback later

        # Sauvegarder le snapshot (TOUTES les features DMP de la barre)
        features = self._pending_snapshot.pop(symbol, {})
        if features:
            self._log_snapshot(symbol, features, signal, sl_ticks, tp_ticks)

        if self.dry_run:
            self.journal.log_event("DRY_TRADE",
                f"{symbol} {dir_str} score={signal.score:.2f} "
                f"SL={sl_ticks:.0f}t TP={tp_ticks:.0f}t | {signal.reason[:60]}")
            return

        # Obtenir le prix reel (CRITIQUE: jamais envoyer avec price=0)
        current_price = self._get_current_price(symbol)
        if current_price <= 0:
            self.journal.log_rejection(symbol, "Prix invalide (<=0)", signal.score)
            return

        # Envoyer l'ordre
        order_id = self.orders.open_position(
            symbol=symbol,
            direction=signal.direction,
            instrument=instrument,
            quantity=position_size,
            sl_ticks=sl_ticks,
            tp_ticks=tp_ticks,
            current_price=current_price,
        )

        if order_id:
            self.risk.on_trade_open(symbol)
            self.journal.log_event("TRADE_SENT",
                f"{symbol} {dir_str} {order_id} @ {current_price} "
                f"SL={sl_ticks:.0f}t TP={tp_ticks:.0f}t | {signal.reason[:60]}")
        else:
            self.journal.log_event("TRADE_FAILED", f"{symbol} order rejected")


# ─── CLI ─────────────────────────────────────────────────────

def main():
    config = BotConfig()

    dry_run = "--dry-run" in sys.argv or "--test" in sys.argv

    if "--live" in sys.argv:
        # Protection: confirmation obligatoire pour le mode live
        print("\n  ⚠️  MODE LIVE DEMANDE — ARGENT REEL EN JEU")
        print("  Tapez 'LIVE' pour confirmer:")
        confirm = input("  > ").strip()
        if confirm != "LIVE":
            print("  Annule. Utilisation en paper trading.")
        else:
            config.paper_trading = False
            print("  ✅ Mode LIVE confirme")

    symbols = ["ES", "NQ"]
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbols = [sys.argv[idx + 1].upper()]

    bot = MIABot(config=config, dry_run=dry_run)
    bot.start(symbols=symbols)


if __name__ == "__main__":
    main()
