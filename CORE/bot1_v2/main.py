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
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # FIX audit 19/06 (pattern Bot MR FIX 1 deja deploye) :
        # restaurer daily_gate cross-restart si meme date UTC.
        # Sans ca, DSL/DSW/MAX_TRADES sont effaces a chaque restart
        # = carnage 18/06 FOMC root cause (15 restarts -> DSL inoperante).
        # Filtre par date_str : nouveau jour UTC -> reset propre.
        prior = self.store.get_daily_state()
        if prior and prior.get("date_str") == today:
            self.daily_gate.restore(
                n_trades_today=int(prior.get("n_trades_today", 0)),
                cumul_pnl_usd=float(prior.get("cumul_pnl_usd", 0.0)),
                date_str=today,
            )
            bot_log.emit(
                "BOT1V2_DAILY_STATE_RESTORED",
                date_str=today,
                n_trades_today=int(prior.get("n_trades_today", 0)),
                cumul_pnl_usd=round(float(prior.get("cumul_pnl_usd", 0.0)), 2),
            )
        else:
            self.daily_gate.reset_for_new_day(today)
            reason = "NEW_DAY" if prior else "NO_PRIOR_STATE"
            bot_log.emit("BOT1V2_DAILY_STATE_RESET", date_str=today, reason=reason)
            try:
                self.store.set_daily_state(self.daily_gate.snapshot())
                self.store.save()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"daily_state init persist fail: {e}")

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
        # FIX Phase 1C audit ULTRATHINK 24/06 : injection trade_journal pour
        # persistance JSONL trades fermes (bloquant DSR Lopez J+30).
        # Journal dedie path DATA/JOURNAL/{date}_trades.jsonl (TradeJournal default).
        try:
            from BOT.trade_journal import TradeJournal
            self.trade_journal = TradeJournal(journal_dir="DATA/JOURNAL/bot1v2")
            bot_log.emit("BOT1V2_TRADE_JOURNAL_WIRED", path="DATA/JOURNAL/bot1v2")
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"TradeJournal init fail (audit J+30 a risque): {e}")
            self.trade_journal = None

        # FIX Phase 2 audit ULTRATHINK 24/06 : RegimeClassifier V_FINAL Bot MR
        # adopte par Bot 2. Stateful par-symbole (EWM slope smoothing) -
        # une instance partagee pour ES + NQ via dict interne.
        try:
            from CORE.bot_mean_revert.regime_classifier import (
                RegimeClassifier as _RegimeClassifierVFinal,
                parse_blacklist as _parse_blacklist,
            )
            self.regime_classifier_v_final = _RegimeClassifierVFinal()
            # Cache blacklist parse au boot (perfformance)
            self._regime_blacklist_cache = _parse_blacklist(
                self.cfg.REGIME_AWARE_BLACKLIST,
            )
            # State throttle emit BOTMR_REGIME_DETECTED par symbole
            self._last_regime_emit: dict = {}
            bot_log.emit(
                "BOT1V2_REGIME_CLASSIFIER_WIRED",
                blacklist=str(list(self._regime_blacklist_cache)),
            )
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"RegimeClassifier V_FINAL init fail: {e}")
            self.regime_classifier_v_final = None
            self._regime_blacklist_cache = frozenset()
            self._last_regime_emit = {}

        if dtc_connector is not None:
            self.fill_listener = DtcFillListener(
                cfg=self.cfg, store=self.store, state_bridge=self.state_bridge,
                on_close_callback=self._on_fill_close,
                bot_id="bot1v2",
                trade_journal=self.trade_journal,
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

        # Fix D3 13/07 : reconciliation broker au BOOT (anti INCIDENT #96 SHORT cumul).
        # Si state file dit position ouverte mais broker deja flat -> clean state.
        # Cause originelle #96 : state file avait ES LONG entry 09/07, broker flat depuis
        # 10/07 (fill listener freeze avait rate le fill). Chaque restart, D1 timeout
        # detectait "position 13 jours old" et emettait MARKET CLOSE aveugle -> cascade
        # 9 SHORTs cumul avg 7596.36. Fix D3 catche le mismatch avant le premier
        # _check_position_timeouts.
        if not self.dry_run:
            self._reconcile_broker_at_boot()

    def _reconcile_broker_at_boot(self) -> None:
        """Compare positions in store vs broker via DTC au boot.

        3 cas :
          - store=vide, broker=?  -> rien a faire
          - store=pos, broker=0   -> clean state (fill listener freeze pre-restart)
          - store=pos, broker=pos mismatched dir/qty -> emit CRITIQUE, PAS d'auto-fix
            (intervention humaine requise via flatten_bot.py + clean state.json)
          - store=pos, broker=pos match  -> log INFO OK

        NEVER auto-flatten aveuglement. Si mismatch : STOP + human review.
        """
        if not self.router or not self.router.dtc:
            for sym in list(self.store.positions.keys()):
                bot_log.emit("BOT1V2_BOOT_RECONCILE_DTC_DOWN", sym=sym)
            return

        try:
            from BOT.dtc_connector import _to_contract
        except Exception as e:  # noqa: BLE001
            # R4 code-reviewer 13/07 : fail-loud sur import fail (n'ete silent).
            self.log.warning(f"reconcile import _to_contract fail: {e}")
            bot_log.emit(
                "BOT1V2_BOOT_RECONCILE_DTC_DOWN", sym="ALL",
            )
            return

        def _cancel_working_orders(sym: str, contract: str) -> None:
            """R1 code-reviewer 13/07 : cancel les Working orders orphelins avant
            clean state (INCIDENT #96 fill_listener freeze scenario). Sinon un SL
            orphelin reste dans le DOM et peut fire au prochain gap.
            """
            try:
                open_orders = self.router.dtc.request_open_orders_blocking(
                    trade_account=self.cfg.TRADE_ACCOUNT,
                    symbol_filter=contract,
                    timeout=3.0,
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"reconcile open_orders query {sym} fail: {e}")
                bot_log.emit(
                    "BOT1V2_BOOT_RECONCILE_OPEN_ORDERS_FAIL", sym=sym,
                )
                return
            if not open_orders:
                return
            for order in open_orders:
                cid = str(order.get("ClientOrderID") or "")
                if not cid:
                    continue
                try:
                    self.router.dtc.cancel_order(
                        cid, trade_account=self.cfg.TRADE_ACCOUNT,
                    )
                    bot_log.emit(
                        "BOT1V2_BOOT_RECONCILE_ORPHAN_CANCELLED",
                        sym=sym, cid=cid,
                    )
                except Exception as e:  # noqa: BLE001
                    self.log.warning(
                        f"reconcile orphan cancel {cid} fail: {e}",
                    )

        def _clean_state_to_flat(sym: str, direction: str) -> None:
            """R4 code-reviewer 13/07 : fail-loud sur state_bridge exception."""
            try:
                self.store.close_position(sym)
                self.store.save()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"reconcile store cleanup {sym}: {e}")
            try:
                self.state_bridge.close_position(
                    sym, exit_price=0.0, exit_reason="BOOT_RECONCILE_FLAT",
                    outcome="ORPHAN_CLEANED", pnl_ticks=0.0, pnl_usd=0.0,
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(
                    f"reconcile state_bridge close_position {sym} fail: {e}",
                )

        for sym in list(self.store.positions.keys()):
            pos = self.store.positions.get(sym) or {}
            direction = str(pos.get("direction") or "")
            n_micros = int(pos.get("n_micros") or 1)
            expected_qty = n_micros if direction == "LONG" else -n_micros
            bot_log.emit(
                "BOT1V2_BOOT_RECONCILE_START",
                sym=sym, state_dir=direction, state_qty=expected_qty,
            )

            try:
                contract = _to_contract(sym)
                broker_qty = self.router.dtc.request_position_blocking(
                    contract, trade_account=self.cfg.TRADE_ACCOUNT, timeout=3.0,
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"reconcile query fail {sym}: {e}")
                bot_log.emit(
                    "BOT1V2_BOOT_RECONCILE_DTC_DOWN", sym=sym,
                )
                continue

            if broker_qty is None:
                # R2 code-reviewer 13/07 : tiebreaker via working orders.
                # SC ne repond pas Type 306 pour compte flat (empirique cascade #96).
                # Si 0 working orders pour ce symbole -> confiance haute broker flat.
                try:
                    open_orders = self.router.dtc.request_open_orders_blocking(
                        trade_account=self.cfg.TRADE_ACCOUNT,
                        symbol_filter=contract,
                        timeout=3.0,
                    )
                except Exception as e:  # noqa: BLE001
                    self.log.warning(f"reconcile tiebreaker fail {sym}: {e}")
                    open_orders = None

                if open_orders is not None and len(open_orders) == 0:
                    # Tiebreaker OK : broker probablement flat + SC silent.
                    bot_log.emit(
                        "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT",
                        sym=sym, state_dir=direction, tiebreaker="no_working_orders",
                    )
                    _clean_state_to_flat(sym, direction)
                    continue

                # Aucun tiebreaker fiable : safe = DTC_DOWN skip
                bot_log.emit(
                    "BOT1V2_BOOT_RECONCILE_DTC_DOWN", sym=sym,
                )
                continue

            if broker_qty == 0:
                # Broker flat mais state avait position = fill non propage OU
                # cascade cumul precedente qu'on vient de nettoyer manuellement.
                # SAFE : clean state (aligne sur broker) + cancel orphan working orders.
                bot_log.emit(
                    "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT",
                    sym=sym, state_dir=direction,
                )
                _cancel_working_orders(sym, contract)  # R1 : cancel orphelins SL/TP
                _clean_state_to_flat(sym, direction)
                continue

            if broker_qty == expected_qty:
                bot_log.emit(
                    "BOT1V2_BOOT_RECONCILE_MATCH", sym=sym, qty=broker_qty,
                )
                continue

            # Mismatch dangereux : broker a une position DIFFERENTE (direction ou qty)
            # NO AUTO-FIX. Emit CRITIQUE + laisser tel quel = arret volontaire.
            bot_log.emit(
                "BOT1V2_BOOT_RECONCILE_MISMATCH_CRITICAL",
                sym=sym, state_dir=direction,
                state_qty=expected_qty, broker_qty=broker_qty,
            )
            self.log.critical(
                f"BOOT RECONCILE MISMATCH {sym} : state {direction} qty={expected_qty}"
                f" vs broker qty={broker_qty} - HUMAN INTERVENTION REQUIRED"
            )

    def _on_fill_close(self, sym: str, pnl_usd: float) -> None:
        """Callback DtcFillListener apres close TP/SL.

        Tient le daily_gate a jour (decompte trades + cumul PnL).
        CRITIQUE : sans ce maj, daily_stop_loss/win/max_trades ne se declenchent
        jamais → reproduit incident Douglas 04/06 (perte sans stop). Cf
        `feedback_douglas_consistency_principles.md`.

        Fix #2 audit 30/06 : BUG CRITIQUE — `register_close` n'etait JAMAIS
        appele = cooldown POST_LOSS/POST_CLOSE jamais active. Reproduit cluster
        4 SHORT ES 22-23h 29/06 (-$67.50 en 1h05 + 1 manual flat -$62.50).
        Backtest empirique 29/06 : activation cooldown = +$101.25 net (3 trades
        evites). Cf cluster.py:171 pour logic.
        """
        # Fix #2 30/06 (BUG FIX) : appel register_close pour activer cooldown
        # POST_LOSS (90 min) ou POST_CLOSE (60 min) selon pnl.
        # Persistance dans store pour cross-restart (sans cette persist,
        # restart bot pendant cooldown = bypass garde-fou).
        try:
            cluster = self.clusters.get(sym)
            if cluster is not None:
                was_loss = pnl_usd < 0
                exit_ts_sec = time.time()
                cluster.register_close(exit_ts=exit_ts_sec, was_loss=was_loss)
                # Persist cross-restart (R1 review : save immediat defensif)
                self.store.set_cooldown(sym, cluster.cooldown_until_ts)
                self.store.save()
                bot_log.emit(
                    "BOT1V2_COOLDOWN_ACTIVATED",
                    sym=sym,
                    was_loss=was_loss,
                    cooldown_until_ts=cluster.cooldown_until_ts,
                    cooldown_min=int(
                        (cluster.cooldown_until_ts - exit_ts_sec) / 60
                    ),
                    pnl_usd=round(float(pnl_usd), 2),
                )
        except Exception as cd_err:  # noqa: BLE001
            self.log.warning(f"register_close cooldown fail: {cd_err}")

        try:
            self.daily_gate.update_after_trade(pnl_usd)
            # FIX audit 19/06 : persister daily_state cross-restart (pattern Bot MR).
            try:
                self.store.set_daily_state(self.daily_gate.snapshot())
                self.store.save()
            except Exception as persist_err:  # noqa: BLE001
                self.log.critical(
                    f"daily_state persist after trade FAIL: {persist_err}"
                )
                bot_log.emit(
                    "BOT1V2_DAILY_STATE_PERSIST_FAIL",
                    context="on_fill_close",
                    err=str(persist_err)[:200],
                )
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
            # FIX audit 19/06 : persister snapshot reset cross-rollover.
            try:
                self.store.set_daily_state(self.daily_gate.snapshot())
                self.store.save()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"daily_state rotate persist fail: {e}")
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

        # FIX Phase 2 audit ULTRATHINK 24/06 - REGIME-AWARE BLACKLIST
        # ============================================================
        # Architecture partagee Bot 1 MR (CORE/bot_mean_revert/regime_classifier.py).
        # Backtest empirique 7j Bot MR : +$299 retroactif, 95% wins preserves.
        # Adoption Bot 2 = applique meme philosophie regime-aware (V_FINAL).
        # Blacklist par defaut : PANIC:*, CALM_RANGE:us_cash, VOLATILE_RANGE:asia
        # Kill switch : BOT1V2_REGIME_AWARE_ENABLED=false
        if (self.cfg.REGIME_AWARE_ENABLED
                and self.regime_classifier_v_final is not None):
            bar_ts_us = bar.get("ts")
            if bar_ts_us is not None:
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    from CORE.bot_mean_revert.regime_classifier import (
                        detect_session_utc, is_blacklisted,
                    )
                    bar_dt = _dt.fromtimestamp(float(bar_ts_us) / 1000.0, tz=_tz.utc)
                    session_utc = detect_session_utc(bar_dt.hour)
                    regime = self.regime_classifier_v_final.classify(bar, sym)
                    # Emit info pour audit J+1 (throttle sur changement regime)
                    cur_key = f"{regime.value}:{session_utc}"
                    last_key = self._last_regime_emit.get(sym)
                    if last_key != cur_key:
                        bot_log.emit(
                            "BOT1V2_REGIME_DETECTED",
                            sym=sym, regime=regime.value, session=session_utc,
                        )
                        self._last_regime_emit[sym] = cur_key
                    # Check blacklist (cache au boot)
                    if is_blacklisted(regime, session_utc, self._regime_blacklist_cache):
                        bot_log.emit(
                            "BOT1V2_REGIME_SESSION_BLOCK",
                            sym=sym, regime=regime.value, session=session_utc,
                        )
                        return None
                except (TypeError, ValueError, OSError):
                    pass  # fail-open : ne casse pas le trading sur ts bug

        # Daily limits gate - bloque uniquement les trades REELS (pas l'audit)
        daily = self.daily_gate.check_allow_entry()
        if session_allowed and not daily.allowed:
            self.log.info(f"{sym} daily limit: {daily.skip_reason}")
            bot_log.emit("BOT1V2_GATE_DAILY_BLOCK", sym=sym, reason=daily.skip_reason)
            return None

        # Cluster evaluate (TOUJOURS, meme hors RTH pour audit empirique)
        decision = self.clusters[sym].evaluate(bar)

        # FIX audit ULTRATHINK 19/06 : detecter divorce silencieux Mirror.
        # Si bull_pts/bear_pts dashboard absents -> fallback derive utilise.
        # Cf agents convergents : le bot N'EST PAS un Mirror reel mais un fork
        # avec 4 features hardcoded (cvd/delta/vwap_d/momentum). Emit MAJEUR
        # pour tracer J+1. Si > 5% des bars en fallback -> Mirror divorce
        # officiel a documenter (INCIDENT_LOG).
        mirror = getattr(decision, "mirror", None)
        if mirror is not None:
            if getattr(mirror, "fallback_pts_used", False):
                bot_log.emit(
                    "BOT1V2_PTS_FALLBACK_FORCED",
                    sym=sym,
                    reason="bull_pts_bear_pts_NULL_in_bar",
                    bull=mirror.bull_pts,
                    bear=mirror.bear_pts,
                )
            if getattr(mirror, "fallback_mtf_used", False):
                bot_log.emit(
                    "BOT1V2_MTF_FALLBACK_FORCED",
                    sym=sym,
                    reason="mtf_bulls_bears_neutres_NULL_in_bar",
                    bulls=mirror.mtf_bulls,
                    bears=mirror.mtf_bears,
                )

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

    def _check_position_timeouts(self) -> None:
        """Fix #1 audit 30/06 — MAX_HOLD anti trade qui dure 13h+.

        Pour chaque position ouverte, si elapsed >= MAX_HOLD_MINUTES :
          1. close_position_market_safe (sequence anti-orphelin V2)
          2. Cleanup store/state_bridge
          3. emit BOT1V2_POSITION_TIMEOUT_CLOSE

        Cf orphan-prevention.md pour sequence DTC anti-orphelin.
        """
        if not getattr(self.cfg, "MAX_HOLD_ENABLED", True):
            return
        max_hold_min = int(getattr(self.cfg, "MAX_HOLD_MINUTES", 45))
        if max_hold_min <= 0:
            return
        try:
            from BOT.dtc_connector import _to_contract
        except Exception:  # noqa: BLE001
            return  # Pas de DTC ou contract resolver -> skip safety

        now_ms = int(time.time() * 1000)
        for sym in list(self.store.positions.keys()):
            pos = self.store.positions.get(sym)
            if not pos:
                continue
            entry_ts = pos.get("entry_ts") or 0
            if entry_ts <= 0:
                continue
            elapsed_min = (now_ms - int(entry_ts)) / 60000.0
            if elapsed_min < max_hold_min:
                continue

            # Position timeout : sequence anti-orphelin
            try:
                contract = _to_contract(sym)
                direction = str(pos.get("direction") or "")
                n_micros = int(pos.get("n_micros") or 1)
                parent_cid = str(pos.get("parent_cid") or "")
                tp_cid = str(pos.get("tp_cid") or "")
                sl_cid = str(pos.get("sl_cid") or "")
                signal_id = str(pos.get("signal_id") or "")
                entry_price = float(pos.get("entry_price") or 0.0)

                # DTC down -> ORPHAN_RISK emit + skip (manual intervention required)
                if not self.dry_run and self.router and not self.router.dtc:
                    try:
                        bot_log.emit(
                            "BOT1V2_TIMEOUT_DTC_DOWN_ORPHAN_RISK",
                            sym=sym, direction=direction,
                            age_min=round(elapsed_min, 1),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    continue

                # Fix R1 review code-reviewer 30/06 : prendre lock fill_listener
                # AVANT close + cleanup pour eviter race avec fill TP/SL parallele.
                # Si fill arrive entre check elapsed et MARKET CLOSE -> SHORT cumul.
                # Si fill_listener None (dry_run / disabled) -> pas de lock dispo.
                listener_lock = None
                if self.fill_listener is not None:
                    listener_lock = getattr(self.fill_listener, "_lock", None)

                def _do_timeout_close():
                    # Re-check position toujours en RAM (peut etre close pendant
                    # acquisition du lock). Idempotence safety.
                    if not self.store.has_position(sym):
                        return None

                    # === Sequence anti-orphelin V2 ===
                    res = self.router.close_position_market_safe(
                        symbol=sym, contract=contract, direction=direction,
                        n_micros=n_micros, parent_cid=parent_cid,
                        tp_cid=tp_cid, sl_cid=sl_cid,
                        reason="TIMEOUT", emit_fn=bot_log.emit,
                    )

                    # Fix B2 review code-reviewer 30/06 (CRITIQUE) :
                    # register close_cid dans fill_listener._cid_index AVANT
                    # qu'un fill MARKET CLOSE n'arrive avec CID inconnu.
                    # Sans cela : fill ignore silencieusement, position reste
                    # OPEN dans store, re-timeout, SHORT cumul broker (bug 18/06).
                    close_cid_x = res.get("close_cid", "")
                    if close_cid_x and self.fill_listener is not None:
                        try:
                            pos_snapshot = dict(pos)  # snapshot avant cleanup
                            self.fill_listener.register_close_cid(
                                sym, close_cid_x, pos_snapshot,
                            )
                        except Exception as e:  # noqa: BLE001
                            self.log.warning(
                                f"register_close_cid fail: {e}"
                            )
                    return res

                if listener_lock is not None:
                    with listener_lock:
                        close_res = _do_timeout_close()
                else:
                    close_res = _do_timeout_close()

                # Position deja closed pendant lock acquisition -> nothing to do
                if close_res is None:
                    continue

                # Emit log close (toujours, meme si already_flat)
                try:
                    bot_log.emit(
                        "BOT1V2_POSITION_TIMEOUT_CLOSE",
                        sym=sym, direction=direction,
                        entry_price=entry_price,
                        age_min=round(elapsed_min, 1),
                        close_cid=close_res.get("close_cid", ""),
                        qty=close_res.get("qty_broker"),
                    )
                except Exception:  # noqa: BLE001
                    pass

                # Fix B2 review : cleanup defensif store/state_bridge UNIQUEMENT
                # si broker confirme deja flat (qty=0). Sinon laisse fill_listener
                # faire le cleanup au fill MARKET CLOSE (PnL correct, exit_reason
                # TIMEOUT propage via register_close_cid kind="timeout").
                # Sans ce guard : SHORT cumul broker si fill arrive apres cleanup.
                if close_res.get("qty_broker") == 0:
                    try:
                        self.store.close_position(sym)
                        self.store.save()
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(
                            f"timeout cleanup store fail: {e}"
                        )
                    try:
                        self.state_bridge.close_position(
                            sym, exit_price=0.0,
                            exit_reason="TIMEOUT_ALREADY_FLAT",
                            outcome="TIMEOUT", pnl_ticks=0.0, pnl_usd=0.0,
                        )
                    except Exception as e:  # noqa: BLE001
                        self.log.warning(
                            f"timeout cleanup state_bridge fail: {e}"
                        )

            except Exception as e:  # noqa: BLE001
                self.log.exception(f"position timeout check fail {sym}: {e}")

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
                # Fix #1 audit 30/06 : check MAX_HOLD timeout AVANT process
                # (anti trade qui dure 13h+ sans SL/TP). Cf orphan-prevention V2.
                self._check_position_timeouts()
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
