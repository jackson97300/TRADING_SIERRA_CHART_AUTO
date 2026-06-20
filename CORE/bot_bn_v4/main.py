"""Main orchestrateur Bot BN V4 (Sim3).

Boucle principale :
  1. Pour chaque symbole, read_last_bar() depuis sierra_enriched
  2. Check fraicheur (DMP_BAR_MAX_AGE_SEC)
  3. Position existante ? Update trailing + skip new entry
  4. Session gate (toutes sessions en reel - config BN V4 TRADABLE_SESSIONS, 18/06)
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
        # FIX 18/06 B3 : persistance compteurs daily (anti reset au restart)
        self._daily_state_path = root / "DATA" / "PAPER_TRADES" / "bot_bn_v4_daily_state.json"
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

            # FIX 17/06 ULTRATHINK : warmup persistant via lecture JSONL sierra_enriched
            # Evite les 4h de WARMUP_x/240 a chaque restart. Source unique = JSONL deja
            # persiste par le pipeline DMP. Pas de fichier de buffer dedie.
            # Review B1 : target = trend_long_lookback (240), pas rolling window (500).
            warmup_target = self.signals[sym]._params.trend_long_lookback
            try:
                n_loaded = self.signals[sym].warmup_from_disk(target=warmup_target)
            except Exception as e:  # noqa: BLE001
                n_loaded = 0
                try:
                    bot_log.emit(
                        "BOTBN_WARMUP_PRELOAD",
                        sym=sym, n_loaded=0, target=warmup_target,
                        is_ready=False, err=str(e)[:200],
                    )
                except Exception:  # noqa: BLE001
                    pass
            else:
                try:
                    bot_log.emit(
                        "BOTBN_WARMUP_PRELOAD",
                        sym=sym, n_loaded=n_loaded,
                        target=warmup_target,
                        is_ready=self.signals[sym].is_ready(),
                    )
                except Exception:  # noqa: BLE001
                    pass
                # Aligner SierraDataSource.last_ts_seen pour eviter double-consommation
                # de la derniere bar deja chargee dans le buffer.
                # Review I2 : utiliser last_bar_ts_ms() (privilegie bar["ts"] int natif)
                # plutot que double conversion iso → ms.
                if n_loaded > 0:
                    last_ts_ms = self.signals[sym].last_bar_ts_ms()
                    if last_ts_ms is not None:
                        self.data_sources[sym].last_ts_seen = last_ts_ms

        # Gates : session + daily limits (reuse Bot 1 v2), regime (BN V4 dedie)
        # FIX 18/06 M1 : SessionGate pilote par la config BN V4 (PAS Bot 2). Avant,
        # SessionGate(self.bot1v2_cfg) lisait les sessions de Bot 2 -> BN V4 heritait
        # silencieusement. SessionGate duck-type .TRADABLE_SESSIONS + .EOD_LOCKOUT_MINUTES.
        from types import SimpleNamespace
        _session_cfg = SimpleNamespace(
            TRADABLE_SESSIONS=self.cfg.TRADABLE_SESSIONS,
            EOD_LOCKOUT_MINUTES=self.cfg.EOD_LOCKOUT_MINUTES,
        )
        self.session_gate = SessionGate(_session_cfg)
        # FIX BUG #6 audit ULTRATHINK 19/06 (code-reviewer) - Silent fallback Mark Douglas.
        # AVANT : DailyLimitsGate(self.bot1v2_cfg) -> lit MAX_TRADES_PER_DAY +
        # DAILY_STOP_LOSS_USD + DAILY_STOP_WIN_USD de Bot1V2Config, jamais de
        # BotBNV4Config. Si env BOTBN_DAILY_STOP_LOSS_USD=-300 set, SILENT IGNORE.
        # Viole data-quality.md Rechute #2. Le commentaire legacy avouait le bug :
        # "On documente que les 2 configs doivent matcher" = silent fallback DOC.
        # APRES : adapter SimpleNamespace force les 3 seuils BotBNV4Config sur
        # DailyLimitsGate, pattern coherent avec SessionGate ligne 162-164.
        _daily_cfg = SimpleNamespace(
            MAX_TRADES_PER_DAY=self.cfg.MAX_TRADES_PER_DAY,
            DAILY_STOP_LOSS_USD=self.cfg.DAILY_STOP_LOSS_USD,
            DAILY_STOP_WIN_USD=self.cfg.DAILY_STOP_WIN_USD,
        )
        self.daily_gate = DailyLimitsGate(_daily_cfg)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.daily_gate.reset_for_new_day(today)
        # FIX 18/06 B3 : restaurer les compteurs du jour si restart le meme jour
        self._load_daily_state(today)

        self.regime_gate = RegimeGate(self.cfg)

        self.router = OrderRouter(
            cfg=self.cfg, dry_run=dry_run, dtc_connector=dtc_connector,
        )

        # State bridge dashboard dedie Sim3
        self.state_bridge = BotBNStateBridge()

        # FIX 17/06 Jackson : DtcFillListener (shared Bot 1 v2) ferme positions
        # sur ORDER_UPDATE Type 301 status=7. Sans ce fix, dashboard reste OPEN
        # apres SL fill indefiniment. NB : BN V4 fait trailing SL → seul le SL
        # INITIAL est detecte par le listener (le cancel-replace post-trailing
        # change le sl_cid sans rappel a register_bracket = BACKLOG).
        from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
        if dtc_connector is not None:
            self.fill_listener = DtcFillListener(
                cfg=self.cfg, store=self.store, state_bridge=self.state_bridge,
                on_close_callback=self._on_fill_close,
                bot_id="bot_bn_v4",
            )
            try:
                dtc_connector.on_order_update = self.fill_listener.handle_order_update
                # B review R1 : retire emit BOT1V2_FILL_LISTENER_WIRED (legacy
                # specifique Bot 1 v2). Bot BN V4 emit UNIQUEMENT le code generique.
                from CORE.bot1_v2.logger import bot_log as _bot1v2_log
                _bot1v2_log.emit(
                    "MIA_FILL_LISTENER_WIRED",
                    trade_account=self.cfg.TRADE_ACCOUNT,
                    bot="bot_bn_v4",
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"dtc.on_order_update wire fail: {e}")
        else:
            self.fill_listener = None

        self._running = False
        self._last_heartbeat_ts = 0.0
        # FIX BUG #3 review code-reviewer 19/06 IMPORTANT : init defensif.
        # _last_reconnect_attempt etait init seulement dans run() -> AttributeError
        # si _ensure_dtc_connected() appele hors run() (tests, future on_demand).
        self._last_reconnect_attempt = 0.0

    def _on_fill_close(self, sym: str, pnl_usd: float) -> None:
        """Callback DtcFillListener post-close : ajoute le PnL au cumul daily.

        FIX 18/06 B2 : apply_pnl (PAS update_after_trade) — le trade est deja
        compte a l'ouverture via register_open. update_after_trade double-compterait.
        """
        try:
            self.daily_gate.apply_pnl(pnl_usd)
            self._save_daily_state()
        except Exception as e:  # noqa: BLE001
            self.log.error(f"daily_gate.apply_pnl fail: {e}")

    def _load_daily_state(self, today: str) -> None:
        """Restaure les compteurs daily persistes (fix B3). Restore SEULEMENT si
        le snapshot date du jour courant (sinon nouveau jour = compteurs a zero)."""
        try:
            import json
            if self._daily_state_path.exists():
                data = json.loads(self._daily_state_path.read_text(encoding="utf-8"))
                if data.get("date_str") == today:
                    self.daily_gate.restore(
                        n_trades_today=data.get("n_trades_today", 0),
                        cumul_pnl_usd=data.get("cumul_pnl_usd", 0.0),
                        date_str=today,
                    )
            try:
                bot_log.emit(
                    "BOTBN_DAILY_STATE_LOAD",
                    n_trades=self.daily_gate.state.n_trades_today,
                    pnl=self.daily_gate.state.cumul_pnl_usd,
                    date=today,
                )
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"daily_state load fail: {e}")

    def _save_daily_state(self) -> None:
        """Persiste les compteurs daily (fix B3) — write ATOMIQUE tmp+rename
        (MAJEUR-2 review) : evite la corruption si crash en plein write ou si
        2 threads (poll + DTC) ecrivent en concurrence. tmp unique par appel."""
        try:
            import json
            import os
            from uuid import uuid4
            self._daily_state_path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps(self.daily_gate.snapshot())
            tmp = self._daily_state_path.with_name(
                f"{self._daily_state_path.name}.{uuid4().hex[:8]}.tmp"
            )
            tmp.write_text(data, encoding="utf-8")
            os.replace(str(tmp), str(self._daily_state_path))
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"daily_state save fail: {e}")

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
            self._save_daily_state()  # FIX 18/06 B3 : persister le reset du nouveau jour
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
                    old_sl_cid = pos.get("sl_cid", "")
                    pos["sl_price"] = upd.new_sl
                    pos["sl_pivots"] = trail.n_pivots()
                    # Cancel-replace SL cote broker. FIX 17/06 Jackson zero-dette :
                    # replace_sl retourne maintenant le NOUVEAU sl_cid (avant : bool).
                    new_sl_cid = self.router.replace_sl(
                        symbol=sym,
                        sl_cid=old_sl_cid,
                        new_sl_price=upd.new_sl,
                        direction=pos.get("direction", "long"),
                        n_micros=pos.get("n_micros", 1),
                        parent_cid_link=pos.get("parent_cid", ""),
                    )
                    if new_sl_cid:
                        # Update store + propagate au listener (sinon fill du
                        # nouveau SL = pas detecte → dashboard reste OPEN).
                        pos["sl_cid"] = new_sl_cid
                        self.store.save()
                        if self.fill_listener is not None:
                            try:
                                self.fill_listener.update_sl_cid(
                                    sym=sym,
                                    old_sl_cid=old_sl_cid,
                                    new_sl_cid=new_sl_cid,
                                )
                            except Exception as e:  # noqa: BLE001
                                self.log.warning(f"fill_listener.update_sl_cid fail: {e}")
                    else:
                        # Echec cancel ou send → position NUE ! Alert MAJEUR.
                        # On save quand meme (sl_price mis a jour memoire) mais
                        # le SL n'est plus actif cote broker → operateur doit close.
                        self.store.save()
                        try:
                            bot_log.emit(
                                "BOTBN_TRAILING_SL_REPLACE_FAIL",
                                sym=sym, old_sl_cid=old_sl_cid[:20],
                                new_sl_price=upd.new_sl,
                                signal_id=pos.get("signal_id", ""),
                            )
                        except Exception:  # noqa: BLE001
                            pass
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

        # FIX BUG #4 review code-reviewer 19/06 BLOQUANT : RegimeGate appele avec
        # proposed_dir='long' meme quand DIRECTION_MODE='both' sabotait B.4. Si
        # regime bearish + DIRECTION_MODE=both : RegimeGate bloquait 'long' et on
        # ratait le SHORT (scenario trade -$967 15/06 manque). Pattern VALIDATION_MISS.
        # FIX : si DIRECTION_MODE != 'both', check classique. Si 'both', deferred
        # check APRES SignalEngine confirme la direction (lignes suivantes).
        if self.cfg.DIRECTION_MODE != "both":
            proposed_dir = self.cfg.DIRECTION_MODE
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

        # FIX BUG #4 (suite) : deferred RegimeGate check si DIRECTION_MODE=both
        # ET SignalEngine a propose une direction. Permet d'evaluer LONG et SHORT
        # independamment vs un seul check biaise vers 'long'.
        if (
            self.cfg.DIRECTION_MODE == "both"
            and decision.direction is not None
        ):
            rg = self.regime_gate.check_allow_entry(bar, decision.direction)
            if not rg.allowed:
                try:
                    bot_log.emit(
                        "BOTBN_GATE_REGIME_BLOCK_POST_SIGNAL",
                        sym=sym, direction=decision.direction,
                        reason=rg.skip_reason,
                    )
                except Exception:
                    pass
                # FIX MINEUR-1 review 2 code-reviewer 20/06 : early return apres
                # log_decision_jsonl pour eviter double emit BOTBN_NOT_TRADABLE.
                # Volume estime sans early return : 10-50 doubles emits/jour/sym =
                # pollution audit (count blocks regime via grep = 2x vraie valeur).
                log_decision_jsonl(
                    bar_ts=bar_ts, symbol=sym, direction=decision.direction,
                    setup=decision.setup, tradable=False,
                    skip_reason=f"REGIME_POST_SIGNAL:{rg.skip_reason}",
                    session_phase=session_phase,
                    hypothetical=False,
                )
                return

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
            # R1 (review B1) : position nue (fill OK, SL non pose). order_router
            # a deja tente un flatten MARKET inverse. On alerte CRITIQUE.
            if getattr(order_result, "naked", False):
                self.log.error(
                    f"{sym} POSITION NUE @ {order_result.fill_price} "
                    f"-> flatten ({order_result.error_msg})"
                )
                try:
                    bot_log.emit(
                        "BOTBN_POSITION_NAKED",
                        sym=sym, direction=decision.direction or "?",
                        fill_price=order_result.fill_price,
                        parent_cid=order_result.parent_cid,
                    )
                except Exception:
                    pass
            else:
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

        # FIX 17/06 review code-reviewer R2 : extraire signal_id UNE FOIS pour
        # eviter desync sur rollover seconde (3 appels f"BOTBN_..._{time.time()}"
        # peuvent produire 3 IDs differents si la seconde change entre les calls).
        signal_id_bn = f"BOTBN_{sym}_{int(time.time())}"
        direction_upper = (decision.direction or "long").upper()
        # Persist position
        self.store.open_position(sym, {
            "signal_id": signal_id_bn,
            "direction": direction_upper,
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
        # FIX 18/06 B2 : compter le trade a l'OUVERTURE (plafond Mark Douglas
        # effectif avant tout close) + persister (anti reset au restart).
        try:
            self.daily_gate.register_open()
            self._save_daily_state()
        except Exception as e:  # noqa: BLE001
            self.log.warning(f"daily register_open fail: {e}")
        # FIX 17/06 : register CIDs DTC reels avant state_bridge open (anti-race)
        # BN V4 : pas de TP fixe, donc tp_cid sera "". Le SL initial est detecte
        # par le listener ; le SL post-trailing est propage via
        # fill_listener.update_sl_cid (cf _process_open_position). Cas residuel :
        # replace_sl en echec -> position nue, gere par alerte (cf B1/M4).
        if self.fill_listener is not None:
            try:
                self.fill_listener.register_bracket(
                    sym=sym,
                    signal_id=signal_id_bn,
                    direction=direction_upper,
                    entry_price=order_result.fill_price,
                    sl_price=sl_price, tp_price=0.0,
                    sl_ticks=sl_ticks, tp_ticks=0,
                    n_micros=self.cfg.N_MICROS_DEFAULT,
                    parent_cid=order_result.parent_cid,
                    tp_cid="",
                    sl_cid=order_result.sl_cid,
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"fill_listener register fail: {e}")
        # Bridge dashboard
        try:
            self.state_bridge.open_position(
                sym,
                direction=direction_upper,
                entry_price=order_result.fill_price,
                sl_price=sl_price,
                tp_price=0.0,  # BN V4 : pas de TP fixe
                sl_ticks=sl_ticks,
                tp_ticks=0,
                signal_id=signal_id_bn,
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

    def _ensure_dtc_connected(self) -> None:
        """FIX B.3 audit ULTRATHINK 19/06 : check DTC alive + auto-reconnect.

        Pattern Bot 4 INCIDENT #77 portage : sans ce check, un silent kick
        Sierra Chart (socket OS vivante mais SC ferme la session DTC) laisse
        le bot envoyer ordres dans le vide pendant des heures.

        Strategie :
          - Check `self.router.dtc.connected` (flag DTCConnector interne)
          - Si False : tenter reconnect (anti-spam 30s entre tentatives)
          - Emit BOTBN_DTC_RECONNECT_OK ou BOTBN_DTC_RECONNECT_FAIL

        Dry-run : skip silencieusement (pas de DTC).
        """
        if self.dry_run or self.router is None or self.router.dtc is None:
            return
        dtc = self.router.dtc
        if dtc.connected:
            return  # OK, connecte
        # Anti-spam : 30s minimum entre tentatives
        now = time.time()
        if now - self._last_reconnect_attempt < 30.0:
            return
        self._last_reconnect_attempt = now
        self.log.warning("DTC disconnected, attempting reconnect...")
        try:
            ok = dtc.connect()
            if ok:
                self.log.info("DTC reconnected successfully")
                try:
                    bot_log.emit("BOTBN_DTC_RECONNECT_OK")
                except Exception:
                    pass
            else:
                self.log.error("DTC reconnect FAILED (return False)")
                try:
                    bot_log.emit("BOTBN_DTC_RECONNECT_FAIL", reason="connect_returned_false")
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            self.log.error(f"DTC reconnect exception: {e}")
            try:
                bot_log.emit("BOTBN_DTC_RECONNECT_FAIL", reason=repr(e)[:200])
            except Exception:
                pass

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

        # FIX BUG #B.3 audit ULTRATHINK 19/06 (code-reviewer) - ensure_connected.
        # Pattern Bot 4 INCIDENT #77 : sans check periodique de dtc.connected,
        # un silent kick SC (socket vivante cote OS mais morte cote SC) laisse
        # le bot envoyer des ordres dans le vide. Anti-spam 30s.
        # NOTE BUG #3 review 19/06 : self._last_reconnect_attempt = 0.0 init
        # deja fait dans __init__ (ligne ~227). Pas besoin de re-init ici.

        self._running = True
        while self._running:
            try:
                # FIX B.3 : ensure_connected check periodique avant chaque cycle
                self._ensure_dtc_connected()
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
            # FIX BUG #1 audit ULTRATHINK 19/06 (code-reviewer) - PROD FANTOME.
            # AVANT : connect() return value IGNORE. Si LOGON refuse ou socket
            # timeout, le bot continue en "prod fantome" : send_market_with_stop_only
            # retourne ("","",0.0), ordres jamais envoyes a SC, signal_id orphan.
            # Cf BOT/dtc_connector.py:233-286 : return False si Result!=1 ou exception.
            # APRES : capture return value + force dry_run + emit BOOT_FAIL + nullify
            # dtc_connector pour empecher utilisation downstream (cf Bot 2 pattern).
            connected = dtc_connector.connect()
            if not connected:
                logging.error(
                    f"DTC connect FAILED (LOGON refused or socket error) - "
                    f"fallback dry_run. host={dtc_cfg.host} port={dtc_cfg.port}"
                )
                try:
                    bot_log.emit(
                        "BOTBN_DTC_BOOT_FAIL",
                        host=dtc_cfg.host, port=dtc_cfg.port,
                        client_name="MIA_BotBN",
                        trade_account=cfg.TRADE_ACCOUNT,
                    )
                except Exception:
                    pass
                dry_run = True
                dtc_connector = None  # CRITIQUE : empeche utilisation downstream
            else:
                logging.info(
                    f"DTC connector connected "
                    f"(ClientName=MIA_BotBN, TA={cfg.TRADE_ACCOUNT})"
                )
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
            dtc_connector = None  # FIX BUG #1 : meme protection exception path

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
