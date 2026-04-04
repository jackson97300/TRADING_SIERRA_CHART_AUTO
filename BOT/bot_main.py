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

from bot_config import BotConfig, CONFIG
from risk_manager import RiskManager
from signal_engine import SignalEngine, Signal
from order_manager import OrderManager
from position_monitor import PositionMonitor
from trade_journal import TradeJournal
from dtc_connector import DTCConnector

# Modules CORE pour features
from dmp_reader import DmpReader
from rolling_features import RollingFeatures
from intermarket_features import IntermarketFeatures
from rule_engine import RuleEngine

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

        self._running = False
        self._symbols = []

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

        # Charger les modeles ML
        for sym in self._symbols:
            if self.signal_engine.load_models(sym):
                logger.info(f"[ML] {sym}: modeles charges")
            else:
                logger.info(f"[ML] {sym}: pas de modele -> RuleEngine actif")

        # Connexion DTC
        if not self.dry_run:
            logger.info("[DTC] Connexion a Sierra Chart...")
            if self.dtc.connect():
                logger.info("[DTC] Connecte")
                self.orders = OrderManager(self.cfg, self.dtc)
                self.monitor = PositionMonitor(self.cfg, self.orders, self.journal)

                # Prix via JSONL (DTC market data non supporte par SC serveur)
                logger.info("[PRIX] Via derniere barre JSONL (fallback DTC)")
            else:
                logger.info("[DTC] ECHEC — passage en dry-run")
                self.dry_run = True

        self.journal.log_event("BOT_START", f"symbols={self._symbols} dry_run={self.dry_run}")

        # Boucle principale
        self._running = True
        self._main_loop()

    def stop(self):
        """Arrete le bot proprement."""
        self._running = False

        # Flatten toutes les positions
        if self.orders and self.orders.total_positions > 0:
            logger.info("[STOP] Flatten toutes les positions...")
            self.orders.flatten_all("BOT_STOP")

        # Deconnexion
        if self.dtc:
            self.dtc.disconnect()

        # Rapport
        logger.info(self.journal.daily_summary())
        self.journal.log_event("BOT_STOP", self.journal.daily_summary())

        logger.info("=" * 60)
        logger.info("  MIA BOT V2 ARRETE")
        logger.info("=" * 60)

    def _main_loop(self):
        """Boucle principale — execute a chaque barre (1 min)."""
        logger.info("[LOOP] Boucle principale demarree (Ctrl+C pour arreter)")
        self._tick_count = 0
        self._last_status_log = 0

        consecutive_errors = 0
        try:
            while self._running:
                try:
                    self._tick()
                    consecutive_errors = 0
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(f"[TICK_ERROR] {e}")
                    if consecutive_errors >= 10:
                        logger.error(f"[FATAL] {consecutive_errors} erreurs consecutives — arret")
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
        except Exception as e:
            logger.error(f"[CRASH] Exception non geree: {e}", exc_info=True)
            self.journal.log_event("CRASH", str(e))
        finally:
            # TOUJOURS fermer les positions, meme en cas de crash
            if self.orders and self.orders.total_positions > 0:
                logger.info("[SAFETY] Flatten d'urgence...")
                self.orders.flatten_all("CRASH_FLATTEN")
            self.stop()

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

            # En dry-run, pas de signaux ni d'execution
            if self.dry_run:
                continue

            signal = self._get_signal(sym)
            if signal.direction == 0:
                continue

            # ── 4. MenthorQ gate ──
            # Gamma condition depuis les features MQ enrichies
            features = self._features_cache.get(sym, {})
            gamma = features.get("mq_gamma_condition", 0.0)
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
                atr_value = features.get("atr_14", 0)
                if atr_value > 0:
                    sl_ticks = max(10, atr_value / instrument.tick_size * instrument.atr_sl_mult)
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
