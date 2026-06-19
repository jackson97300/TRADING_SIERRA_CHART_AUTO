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
from CORE.bot_mean_revert.gates.intermarket import IntermarketGate
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

        # Persiste config active pour consumers externes (dashboard countdown).
        # Source unique de verite : evite la decorrelation env vars cross-process nssm.
        self.store.set_meta_config(
            cooldown_minutes=self.cfg.COOLDOWN_BARS,
            max_hold_minutes=self.cfg.MAX_HOLD_MINUTES,
        )
        self.store.save()

        # Per-symbol engines / data sources
        self.engines: dict[str, SignalEngine] = {}
        self.data_sources: dict[str, SierraDataSource] = {}
        from CORE.bot1_v2.config import Bot1V2Config
        ds_cfg = Bot1V2Config.from_env()
        # R1 code-reviewer 18/06 : callback emit pour ISO corrompu
        # (fail-open visible, anti silent fallback 19/04 meta-labeler).
        def _emit_iso_corrupted(sym: str, iso: str) -> None:
            try:
                bot_log.emit("BOTMR_COOLDOWN_ISO_CORRUPTED", sym=sym, iso=iso or "")
            except Exception as exc:  # noqa: BLE001
                # Safe-fail : un fail emit ne doit jamais propager dans la
                # decision de trading. On log via logger Python en derniere ligne.
                self.log.warning(f"emit BOTMR_COOLDOWN_ISO_CORRUPTED fail: {exc}")

        # Phase 3 18/06 : RegimeClassifier vote majoritaire 3 signaux.
        # Instance unique partagee entre tous les SignalEngine (stateless safe).
        # Bypass possible via cfg.REGIME_CLASSIFIER_ENABLED=False (kill-switch).
        from CORE.bot_mean_revert.gates.regime_classifier import RegimeClassifier
        self.regime_classifier = RegimeClassifier(self.cfg)

        # Phase 3 18/06 (alternative) : RegimeScorer score continu pondere.
        # Approche complementaire au classifier binaire vote majoritaire.
        # Capture la non-monotonie observee dans calibration empirique deciles
        # slope_30 -> EV (vote binaire perd l'info, score pondere la garde).
        # Stateless safe (cfg en read-only) -> 1 instance partagee.
        # Kill-switch : cfg.REGIME_SCORER_ENABLED=False.
        from CORE.bot_mean_revert.gates.regime_scorer import RegimeScorer
        self.regime_scorer = RegimeScorer(self.cfg)

        for sym in self.symbols:
            # store passe au SignalEngine pour cooldown time-based persistant
            # (fix bug 18/06 : restart ne bypass plus le cooldown).
            self.engines[sym] = SignalEngine(
                symbol=sym,
                cfg=self.cfg,
                traded_signal_ids=self.store.traded_signal_ids,
                store=self.store,
                on_corrupted_state=_emit_iso_corrupted,
                regime_classifier=self.regime_classifier,
                regime_scorer=self.regime_scorer,
            )
            # Reuse SierraDataSource avec Bot1V2Config (compatible : meme DMP_BAR_MAX_AGE_SEC + dir).
            self.data_sources[sym] = SierraDataSource(symbol=sym, cfg=ds_cfg)

        # Intermarket gate (Jackson 16/06) : NQ utilise ES leader.
        # On s'assure que tous les leaders requis sont presents comme data sources
        # (sinon on les ajoute en peek-only - pas dans self.symbols)
        self.intermarket_gate = IntermarketGate(self.cfg)
        if self.cfg.INTERMARKET_GATE_ENABLED:
            for sym in self.symbols:
                leader = self.cfg.INTERMARKET_LEADER_BY_SYM.get(sym)
                if leader and leader not in self.data_sources:
                    self.log.info(
                        f"IntermarketGate : ajout data source leader '{leader}' (peek-only) pour '{sym}'"
                    )
                    self.data_sources[leader] = SierraDataSource(symbol=leader, cfg=ds_cfg)

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

        # FIX 17/06 Jackson : DtcFillListener (shared Bot 1 v2) ferme positions
        # sur ORDER_UPDATE Type 301 status=7. Sans ce fix, dashboard reste OPEN
        # apres TP/SL fill indefiniment (meme bug que Bot 1 v2 trade 17:01).
        # Note duck-typing : listener utilise seulement cfg.TRADE_ACCOUNT.
        from CORE.bot1_v2.dtc_fill_listener import DtcFillListener
        if dtc_connector is not None:
            self.fill_listener = DtcFillListener(
                cfg=self.cfg, store=self.store, state_bridge=self.state_bridge,
                on_close_callback=self._on_fill_close,
                bot_id="bot_mr",
            )
            try:
                dtc_connector.on_order_update = self.fill_listener.handle_order_update
                # B review R1 : retire emit BOT1V2_FILL_LISTENER_WIRED (legacy
                # specifique Bot 1 v2). Bot MR emit UNIQUEMENT le code generique.
                from CORE.bot1_v2.logger import bot_log as _bot1v2_log
                _bot1v2_log.emit(
                    "MIA_FILL_LISTENER_WIRED",
                    trade_account=self.cfg.TRADE_ACCOUNT,
                    bot="bot_mr",
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"dtc.on_order_update wire fail: {e}")
        else:
            self.fill_listener = None

        self._running = False
        self._last_heartbeat_ts = 0.0
        # FIX 18/06 BOUCLE INFINIE MAX_HOLD : tracker le dernier force_close
        # par symbole pour eviter ressayer dans la fenetre cooldown (fill listener
        # peut prendre >1min a confirmer status=7 sur Sim slow). Reference incident
        # 18/06 : 9 close markets en 8 min sur meme position = cumul SHORTs sans SL/TP.
        self._last_max_hold_close_ts_by_sym: dict[str, float] = {}
        # FIX 18/06 BOOT WARMUP : ne pas declencher MAX_HOLD dans les N secondes
        # apres boot. Permet au DtcFillListener de detecter d'eventuels fills
        # orphelins via ORDER_UPDATE avant qu'on envoie un nouveau close market.
        self._boot_ts = time.time()

    def _on_fill_close(
        self, sym: str, pnl_usd: float, exit_reason: str = "UNKNOWN",
    ) -> None:
        """Callback DtcFillListener post-close : maj daily_gate + circuit breaker.

        Circuit breaker (18/06) : track N SL consecutives par symbole, halt trading
        si threshold atteint, reset au prochain TP. Reference carnage 18/06 (-$1025
        broker E-mini sur 4 SL LONG ES sans halt = pas d'auto-correction).

        Convention exit_reason (RESERVE #4 fix 18/06) :
          - "TIMEOUT" : MAX_HOLD force close. PnL peut etre legerement negatif
            (slippage market close) mais c'est une sortie TEMPORELLE, pas une SL
            signal-driven. NE PAS polluer circuit breaker SL consec (sinon halt
            60min sur 3 timeouts d'affilee = halt injustifie).
          - "TP" : signal-driven win (pnl >= 0) -> reset compteur SL consec.
          - "SL" : signal-driven loss (pnl < 0) -> increment compteur SL consec.
          - "UNKNOWN" : signature ancienne (2 args), fallback sur convention pnl-based
            (>=0 = reset, <0 = increment).

        Args:
            sym: symbole ("ES", "NQ", "MGC")
            pnl_usd: PnL en USD du trade ferme.
            exit_reason: "TP" / "SL" / "TIMEOUT" / "UNKNOWN" (default backward compat).
        """
        try:
            self.daily_gate.update_after_trade(pnl_usd)
        except Exception as e:  # noqa: BLE001
            self.log.error(f"daily_gate.update_after_trade fail: {e}")

        # RESERVE #4 fix 18/06 : MAX_HOLD timeout ne pollue PAS le circuit breaker.
        # Sortie temporelle != SL signal-driven. Cleanup tracker anti-boucle ici
        # car aucune logique SL consec a appliquer.
        if exit_reason == "TIMEOUT":
            bot_log.emit(
                "BOTMR_TIMEOUT_NO_SL_CONSEC_IMPACT",
                sym=sym, pnl_usd=round(pnl_usd, 2),
            )
            # Cleanup tracker anti-boucle in-memory (pos deja supprime par close_position)
            self._last_max_hold_close_ts_by_sym.pop(sym, None)
            return

        # Circuit breaker : track SL consecutives par symbole
        if self.cfg.CIRCUIT_BREAKER_ENABLED:
            try:
                if pnl_usd < 0:  # SL hit
                    n_consec = self.store.increment_sl_consec(sym)
                    bot_log.emit(
                        "BOTMR_SL_CONSEC_INCREMENTED",
                        sym=sym, n_consec=n_consec, pnl_usd=round(pnl_usd, 2),
                    )
                    if n_consec >= self.cfg.SL_CONSEC_HALT_THRESHOLD:
                        halt_until_ts = time.time() + (
                            self.cfg.HALT_DURATION_MINUTES * 60
                        )
                        self.store.set_halt_until_ts(sym, halt_until_ts)
                        halt_iso = datetime.fromtimestamp(
                            halt_until_ts, tz=timezone.utc,
                        ).isoformat()
                        self.log.warning(
                            f"{sym} CIRCUIT BREAKER HALT: {n_consec} SL consec, "
                            f"halt until {halt_iso}"
                        )
                        bot_log.emit(
                            "BOTMR_CIRCUIT_BREAKER_HALT_TRIGGERED",
                            sym=sym, n_consec=n_consec,
                            halt_minutes=self.cfg.HALT_DURATION_MINUTES,
                        )
                else:  # TP hit (pnl_usd >= 0 traite comme reset, conservateur)
                    cur = self.store.get_n_sl_consec(sym)
                    if cur > 0:
                        self.store.reset_sl_consec(sym)
                        bot_log.emit(
                            "BOTMR_SL_CONSEC_RESET",
                            sym=sym, was=cur, reason="TP",
                        )
                # Persist immediat apres mutation (atomique store.save).
                try:
                    self.store.save()
                except Exception as e:  # noqa: BLE001
                    self.log.warning(
                        f"store.save fail after circuit breaker update: {e}"
                    )
            except Exception as e:  # noqa: BLE001
                # Defense : un fail circuit breaker ne doit pas casser le close trade.
                self.log.error(f"circuit_breaker update fail: {e}")

        # Cleanup tracker anti-boucle in-memory pour TP/SL legitime aussi.
        # Si une position avait deja eu un timeout retry partiel mais finit par
        # toucher SL/TP, on doit nettoyer le tracker sinon le prochain trade
        # voit un last_max_hold_close_ts fantome (pas critique mais propre).
        self._last_max_hold_close_ts_by_sym.pop(sym, None)

    def _force_close_timeout(self, sym: str, pos: dict, elapsed_min: float) -> None:
        """Force close a market d'une position ouverte depuis > MAX_HOLD_MINUTES.

        Lopez AFML Ch.3 triple barrier : la 3e barriere temporelle (max hold)
        force la sortie si ni TP ni SL n'ont fire avant. Standard pro MR intraday.

        Sequence anti-orphan (cf .claude/rules/orphan-prevention.md) :
          1. Cancel TP via cancel_order(cid, trade_account=Sim1)
          2. Cancel SL idem
          3. Wait 1s propagation
          4. MARKET CLOSE Type 208 OpenCloseTrade=2 (send_close_market connector)
          5. Wait 2s pour fill
          6. SUBMIT_FLATTEN_POSITION_ORDER (Type 209) bouclier defense
          7. Cleanup LOCAL minimal : le DtcFillListener fera close_position complet
             sur ORDER_UPDATE status=7 du MARKET CLOSE (anti double-close).

        Args:
            sym : symbole brut ("ES" / "NQ" / "MGC")
            pos : dict position depuis self.store.positions[sym]
            elapsed_min : duree d'ouverture (minutes)
        """
        direction = pos.get("direction")
        tp_cid = pos.get("tp_cid")
        sl_cid = pos.get("sl_cid")
        n_micros = pos.get("n_micros", 1)
        entry_price = pos.get("entry_price", 0.0)

        self.log.warning(
            f"{sym} MAX_HOLD timeout: {elapsed_min:.1f}min >= {self.cfg.MAX_HOLD_MINUTES}min, "
            f"force close at market (entry={entry_price}, dir={direction})"
        )
        bot_log.emit(
            "BOTMR_TIMEOUT_CLOSE_START",
            sym=sym, direction=direction, elapsed_min=round(elapsed_min, 1),
            max_hold_min=self.cfg.MAX_HOLD_MINUTES,
            entry_price=entry_price, n_micros=n_micros,
        )

        if self.router is None or getattr(self.router, "dtc", None) is None:
            # Pas de DTC -> pas de close possible, alerte critique orphan risk
            bot_log.emit(
                "BOTMR_TIMEOUT_DTC_DOWN_ORPHAN_RISK",
                sym=sym, direction=direction,
            )
            return

        dtc = self.router.dtc
        ta = self.cfg.TRADE_ACCOUNT

        # Step 1-2 : cancel TP + SL (trade_account explicite, regle orphan-prevention)
        for label, cid in [("TP", tp_cid), ("SL", sl_cid)]:
            if not cid:
                continue
            try:
                ok = dtc.cancel_order(cid, trade_account=ta)
                if not ok:
                    bot_log.emit(
                        "BOTMR_TIMEOUT_CANCEL_FAIL",
                        sym=sym, leg=label, cid=cid,
                    )
            except Exception as e:  # noqa: BLE001
                bot_log.emit(
                    "BOTMR_TIMEOUT_CANCEL_EXCEPTION",
                    sym=sym, leg=label, cid=cid, err=str(e)[:200],
                )

        # Step 3 : wait propagation cancels (cf orphan-prevention.md latences mesurees)
        time.sleep(1.0)

        # Step 4 : MARKET CLOSE (opposite side, OpenCloseTrade=2 dans send_close_market).
        # Mapping symbole -> contract Sierra (source unique : BOT/dtc_connector.SYMBOL_TO_CONTRACT).
        # Le connector send_close_market envoie Symbol brut, donc on doit passer le
        # contract complet ici (pas comme send_market_order qui fait _to_contract).
        contract = pos.get("contract") or self._sym_to_contract(sym)
        # LONG -> SELL (2) pour fermer ; SHORT -> BUY (1)
        close_side = 2 if direction == "LONG" else 1
        try:
            close_cid = dtc.send_close_market(
                symbol=contract,
                side=close_side,
                quantity=abs(int(n_micros)),
                trade_account=ta,
            )
            bot_log.emit(
                "BOTMR_TIMEOUT_MARKET_CLOSE_SENT",
                sym=sym, side=("SELL" if close_side == 2 else "BUY"),
                qty=abs(int(n_micros)), cid=close_cid or "",
                ok=bool(close_cid),
            )
            # RESERVE #1 fix 18/06 : register close_cid dans DtcFillListener.
            # Sans ca, le fill du close market (ORDER_UPDATE status=7 ClientOrderID=
            # close_cid) arrive avec un CID inconnu -> listener retourne sans
            # cleanup -> position reste OPEN -> MAX_HOLD re-declenche -> boucle
            # infinie (carnage 18/06 = 9 closes en 8 min cumul SHORTs).
            # Convention kind="timeout" -> exit_reason="TIMEOUT" propage au callback.
            if close_cid and self.fill_listener is not None:
                try:
                    self.fill_listener.register_close_cid(sym, close_cid, pos)
                except Exception as e:  # noqa: BLE001
                    bot_log.emit(
                        "BOTMR_TIMEOUT_REGISTER_CLOSE_CID_FAIL",
                        sym=sym, cid=close_cid, err=str(e)[:200],
                    )
        except Exception as e:  # noqa: BLE001
            bot_log.emit(
                "BOTMR_TIMEOUT_MARKET_CLOSE_EXCEPTION",
                sym=sym, err=str(e)[:200],
            )

        # Step 5 : wait fill MARKET CLOSE
        time.sleep(2.0)

        # Step 6 : Type 209 flatten defense (inoffensif si deja flat)
        # ClientOrderID OBLIGATOIRE (cf orphan-prevention.md : SC rejette
        # silencieusement Type 209/210 sans CID).
        flatten_cid = f"BOTMR_TIMEOUT_FLUSH_{sym[:2]}_{int(time.time()) % 100000}"
        try:
            dtc._send({
                "Type": 209,
                "ClientOrderID": flatten_cid,
                "Symbol": contract,
                "TradeAccount": ta,
                "Exchange": "CME",
                "IsAutomatedOrder": 1,
            })
            bot_log.emit("BOTMR_TIMEOUT_FLATTEN_SENT", sym=sym, cid=flatten_cid)
        except Exception as e:  # noqa: BLE001
            bot_log.emit("BOTMR_TIMEOUT_FLATTEN_EXCEPTION", sym=sym, err=str(e)[:200])

        # Step 7 : on NE SUPPRIME PAS la position du store ici.
        # Le DtcFillListener sur ORDER_UPDATE status=7 du MARKET CLOSE fera le
        # close_position complet (store + state_bridge + daily_gate). Faire un
        # double cleanup ici = double comptage PnL + race condition.
        bot_log.emit("BOTMR_TIMEOUT_CLOSE_DONE", sym=sym)

    @staticmethod
    def _sym_to_contract(sym: str) -> str:
        """Map symbole brut -> contract Sierra complet.

        Source unique : BOT/dtc_connector.py:SYMBOL_TO_CONTRACT (16/06 rollover U26).
        Fallback hardcode ici si import echoue (defense). NE PAS divergeur la
        source de verite : si rollover change, modifier dtc_connector.py.
        """
        try:
            from BOT.dtc_connector import SYMBOL_TO_CONTRACT
            return SYMBOL_TO_CONTRACT.get(sym.upper(), sym)
        except Exception:  # noqa: BLE001
            # Fallback hardcode (aligne avec dtc_connector.py:112-117 au 16/06/2026)
            fallback = {
                "ES": "ESU26-CME",
                "NQ": "NQU26-CME",
                "MGC": "MGCQ26-CMECOMEX",
            }
            return fallback.get(sym.upper(), sym)

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
            # Check MAX_HOLD timeout (Lopez AFML Ch.3 triple barrier).
            # Si position ouverte depuis >= MAX_HOLD_MINUTES sans toucher TP/SL,
            # force close a market. Standard pro MR intraday 1-min.
            # FIX 18/06 ANTI-BOUCLE :
            #  (1) BOOT_WARMUP : skip dans les N sec apres boot (laisse temps
            #      DtcFillListener de detecter fills orphelins via ORDER_UPDATE).
            #  (2) RETRY_COOLDOWN : skip si dernier close envoye il y a < N sec.
            # Sans ces guards, bug 18/06 = 9 close markets en 8 min sur meme
            # position = cumul SHORTs sans SL/TP (carnage).
            pos = self.store.positions.get(sym)
            if pos is not None:
                now_ts = time.time()
                # Guard 1 : boot warmup
                if (now_ts - self._boot_ts) < self.cfg.MAX_HOLD_BOOT_WARMUP_SEC:
                    bot_log.emit(
                        "BOTMR_MAX_HOLD_BOOT_WARMUP_SKIP",
                        sym=sym,
                        age_sec=round(now_ts - self._boot_ts, 1),
                        warmup_sec=self.cfg.MAX_HOLD_BOOT_WARMUP_SEC,
                    )
                else:
                    entry_ts_ms = pos.get("entry_ts", 0)
                    if entry_ts_ms > 0:
                        elapsed_min = (now_ts * 1000 - entry_ts_ms) / 60_000.0
                        if elapsed_min >= self.cfg.MAX_HOLD_MINUTES:
                            # Guard 3 RESERVE #3 : max retries halt (defense pathologique).
                            # Si N timeouts envoyes mais position toujours OPEN (DTC down,
                            # Sim refuse, sequence cancel+close orpheline) -> halt symbole,
                            # intervention manuelle requise. Sans ce plafond, une position
                            # bloquee declenche des closes infinis toute la session.
                            n_timeouts = int(pos.get("n_max_hold_timeouts", 0))
                            if n_timeouts >= self.cfg.MAX_HOLD_MAX_RETRIES:
                                if not pos.get("halted_by_max_hold", False):
                                    pos["halted_by_max_hold"] = True
                                    try:
                                        self.store.save()
                                    except Exception as e:  # noqa: BLE001
                                        self.log.warning(
                                            f"store.save fail after halt set: {e}"
                                        )
                                    self.log.critical(
                                        f"{sym} MAX_HOLD MAX RETRIES EXHAUSTED: "
                                        f"{n_timeouts} timeouts envoyes mais position "
                                        f"TOUJOURS OPEN. Position halted. "
                                        f"INTERVENTION MANUELLE REQUISE."
                                    )
                                    bot_log.emit(
                                        "BOTMR_MAX_HOLD_RETRIES_EXHAUSTED_HALT",
                                        sym=sym, n_timeouts=n_timeouts,
                                        max_retries=self.cfg.MAX_HOLD_MAX_RETRIES,
                                    )
                                # Halt persistant : pas de close, operateur doit Flatten.
                                bot_log.emit("BOTMR_SKIP_HAS_POSITION", sym=sym)
                                return None

                            # Guard 2 : retry cooldown anti-boucle.
                            # RESERVE #2 fix 18/06 : last_close_ts persiste dans pos (cross-restart).
                            # In-memory dict reste comme fallback degrade (cas pos absent au restart).
                            last_close_ts = (
                                float(pos.get("last_max_hold_close_ts", 0.0))
                                or self._last_max_hold_close_ts_by_sym.get(sym, 0.0)
                            )
                            if last_close_ts > 0 and (now_ts - last_close_ts) < self.cfg.MAX_HOLD_RETRY_COOLDOWN_SEC:
                                bot_log.emit(
                                    "BOTMR_MAX_HOLD_RETRY_COOLDOWN_SKIP",
                                    sym=sym,
                                    secs_since_last=round(now_ts - last_close_ts, 1),
                                    cooldown_sec=self.cfg.MAX_HOLD_RETRY_COOLDOWN_SEC,
                                )
                            else:
                                self._force_close_timeout(sym, pos, elapsed_min)
                                # In-memory tracker (fallback).
                                self._last_max_hold_close_ts_by_sym[sym] = now_ts
                                # RESERVE #2 : persister dans pos pour cross-restart.
                                # Le bot peut crasher entre 2 retries -> sans persistance,
                                # n_max_hold_timeouts repart de 0 au reboot -> bypass plafond.
                                pos["last_max_hold_close_ts"] = now_ts
                                pos["n_max_hold_timeouts"] = int(pos.get("n_max_hold_timeouts", 0)) + 1
                                try:
                                    self.store.save()
                                except Exception as e:  # noqa: BLE001
                                    self.log.warning(
                                        f"store.save fail after force_close persist: {e}"
                                    )
                                return None  # position fermee (cleanup via fill listener)

            bot_log.emit("BOTMR_SKIP_HAS_POSITION", sym=sym)
            # Update live tracking MFE/MAE/PnL unrealized pour visibility dashboard
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
            # Emit code dedie pour anti-clustering (tracabilite J+1 grep).
            # Format skip_reason : "REENTRY_TOO_CLOSE:3t<20t last=7547.25"
            if signal_result.skip_reason.startswith("REENTRY_TOO_CLOSE"):
                try:
                    # Parse robust : "REENTRY_TOO_CLOSE:{dist}t<{min}t last={price}"
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    left, right = payload.split("<", 1)
                    dist_ticks = left.replace("t", "").strip()
                    parts = right.split(" ", 1)
                    min_ticks = parts[0].replace("t", "").strip()
                    last_price = parts[1].split("=", 1)[1] if len(parts) > 1 else "?"
                except (IndexError, ValueError):
                    dist_ticks, min_ticks, last_price = "?", "?", "?"
                bot_log.emit(
                    "BOTMR_NO_REENTRY_TOO_CLOSE",
                    sym=sym,
                    direction=signal_result.direction or "?",
                    dist_ticks=dist_ticks,
                    min_ticks=min_ticks,
                    last_price=last_price,
                )
            # 🆕 18/06 Regime hard filter blocks (anti catch falling knife).
            # Format skip_reason :
            #   "REGIME_BEARISH_TREND:slope_30=-2.30<-1.5"
            #   "REGIME_BULLISH_TREND:slope_30=2.50>1.5"
            #   "REGIME_VIX_PANIC:18.5%>15.0"
            #   "REGIME_VIX_PANIC_ABS:32.1>=30.0"
            elif signal_result.skip_reason.startswith("REGIME_BEARISH_TREND"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    slope_str, thr_str = payload.split("<", 1)
                    slope_val = slope_str.split("=", 1)[1].strip()
                    thr_val = thr_str.strip()
                except (IndexError, ValueError):
                    slope_val, thr_val = "?", "?"
                bot_log.emit(
                    "BOTMR_REGIME_BEARISH_BLOCK",
                    sym=sym, slope_30=slope_val, threshold=thr_val,
                )
            elif signal_result.skip_reason.startswith("REGIME_BULLISH_TREND"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    slope_str, thr_str = payload.split(">", 1)
                    slope_val = slope_str.split("=", 1)[1].strip()
                    thr_val = thr_str.strip()
                except (IndexError, ValueError):
                    slope_val, thr_val = "?", "?"
                bot_log.emit(
                    "BOTMR_REGIME_BULLISH_BLOCK",
                    sym=sym, slope_30=slope_val, threshold=thr_val,
                )
            elif signal_result.skip_reason.startswith("REGIME_VIX_PANIC"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    # Format pct : "18.5%>15.0" ; format abs : "32.1>=30.0"
                    sep = ">=" if ">=" in payload else ">"
                    left, right = payload.split(sep, 1)
                    vix_val = left.replace("%", "").strip()
                    thr_val = right.strip()
                except (IndexError, ValueError):
                    vix_val, thr_val = "?", "?"
                bot_log.emit(
                    "BOTMR_REGIME_VIX_PANIC_BLOCK",
                    sym=sym, vix_change_pct=vix_val, threshold=thr_val,
                )
            # 18/06 Regime scorer continu (alternative score pondere multi-features).
            # Format skip_reason : "REGIME_SCORE_BLOCKED:{regime}_blocks_{direction} "
            #                      "score={score} features={features_dict}"
            elif signal_result.skip_reason.startswith("REGIME_SCORE_BLOCKED"):
                try:
                    # Parse minimal robust : on extrait regime + score, features
                    # restent dans skip_reason brut (deja stocke via log_decision_jsonl).
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    # payload = "TREND_DOWN_STRONG_blocks_LONG score=-72.0 features=..."
                    head, _sep, rest = payload.partition(" ")
                    regime_val = head.split("_blocks_", 1)[0]
                    score_token = rest.split(" ", 1)[0] if rest else ""
                    score_val = score_token.replace("score=", "").strip() or "?"
                    features_part = rest.split("features=", 1)[1] if "features=" in rest else "?"
                except (IndexError, ValueError):
                    regime_val, score_val, features_part = "?", "?", "?"
                bot_log.emit(
                    "BOTMR_REGIME_SCORE_BLOCK",
                    sym=sym,
                    direction=signal_result.direction or "?",
                    regime=regime_val,
                    score=score_val,
                    features=features_part[:200],
                )
            # 🆕 18/06 Confluence filter (anti entry isolee dans le vide).
            # Format skip_reason : "NO_CONFLUENCE:{n}<{min}_levels_in_{rad}t"
            elif signal_result.skip_reason.startswith("NO_CONFLUENCE"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    # payload = "1<2_levels_in_10t"
                    left, right = payload.split("<", 1)
                    n_levels_val = left.strip()
                    # right = "2_levels_in_10t"
                    min_part, _sep, rad_part = right.partition("_levels_in_")
                    min_levels_val = min_part.strip()
                    radius_ticks_val = rad_part.replace("t", "").strip()
                except (IndexError, ValueError):
                    n_levels_val, min_levels_val, radius_ticks_val = "?", "?", "?"
                bot_log.emit(
                    "BOTMR_NO_CONFLUENCE_BLOCK",
                    sym=sym,
                    direction=signal_result.direction or "?",
                    n_levels=n_levels_val,
                    min_levels=min_levels_val,
                    radius_ticks=radius_ticks_val,
                )
            # 🆕 18/06 Phase 4 Orderflow / Anti-top / Momentum cap.
            # 7 codes emit selon prefixe skip_reason.
            elif signal_result.skip_reason.startswith("ORDERFLOW_NO_DATA"):
                bot_log.emit(
                    "BOTMR_ORDERFLOW_NO_DATA_BLOCK",
                    sym=sym,
                    direction=signal_result.direction or "?",
                )
            elif signal_result.skip_reason.startswith("ORDERFLOW_NO_BUYERS_LONG"):
                # Format : "ORDERFLOW_NO_BUYERS_LONG:delta={d} rvol_z={r}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    delta_val = payload.split("delta=", 1)[1].split(" ", 1)[0]
                    rvol_val = payload.split("rvol_z=", 1)[1].strip()
                except (IndexError, ValueError):
                    delta_val, rvol_val = "?", "?"
                bot_log.emit(
                    "BOTMR_ORDERFLOW_NO_BUYERS_BLOCK",
                    sym=sym, delta=delta_val, rvol_z=rvol_val,
                )
            elif signal_result.skip_reason.startswith("ORDERFLOW_NO_SELLERS_SHORT"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    delta_val = payload.split("delta=", 1)[1].split(" ", 1)[0]
                    rvol_val = payload.split("rvol_z=", 1)[1].strip()
                except (IndexError, ValueError):
                    delta_val, rvol_val = "?", "?"
                bot_log.emit(
                    "BOTMR_ORDERFLOW_NO_SELLERS_BLOCK",
                    sym=sym, delta=delta_val, rvol_z=rvol_val,
                )
            elif signal_result.skip_reason.startswith("ANTI_TOP_LONG"):
                # Format : "ANTI_TOP_LONG:bs_high={n} dist_1d_max={d}t"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    bs_val = payload.split("bs_high=", 1)[1].split(" ", 1)[0]
                    dist_val = payload.split("dist_1d_max=", 1)[1].replace("t", "").strip()
                except (IndexError, ValueError):
                    bs_val, dist_val = "?", "?"
                bot_log.emit(
                    "BOTMR_ANTI_TOP_LONG_BLOCK",
                    sym=sym, bs_high=bs_val, dist_hod=dist_val,
                )
            elif signal_result.skip_reason.startswith("ANTI_BOTTOM_SHORT"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    bs_val = payload.split("bs_low=", 1)[1].split(" ", 1)[0]
                    dist_val = payload.split("dist_1d_min=", 1)[1].replace("t", "").strip()
                except (IndexError, ValueError):
                    bs_val, dist_val = "?", "?"
                bot_log.emit(
                    "BOTMR_ANTI_BOTTOM_SHORT_BLOCK",
                    sym=sym, bs_low=bs_val, dist_lod=dist_val,
                )
            elif signal_result.skip_reason.startswith("MOMENTUM_CAP_LONG"):
                # Format : "MOMENTUM_CAP_LONG:slope_10={s}>{thr}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    slope_val, thr_val = payload.split(">", 1)
                    slope_val = slope_val.replace("slope_10=", "").strip()
                    thr_val = thr_val.strip()
                except (IndexError, ValueError):
                    slope_val, thr_val = "?", "?"
                bot_log.emit(
                    "BOTMR_MOMENTUM_CAP_LONG_BLOCK",
                    sym=sym, slope_10=slope_val, threshold=thr_val,
                )
            elif signal_result.skip_reason.startswith("MOMENTUM_CAP_SHORT"):
                # Format : "MOMENTUM_CAP_SHORT:slope_10={s}<-{thr}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    slope_val, thr_val = payload.split("<-", 1)
                    slope_val = slope_val.replace("slope_10=", "").strip()
                    thr_val = thr_val.strip()
                except (IndexError, ValueError):
                    slope_val, thr_val = "?", "?"
                bot_log.emit(
                    "BOTMR_MOMENTUM_CAP_SHORT_BLOCK",
                    sym=sym, slope_10=slope_val, threshold=thr_val,
                )
            elif signal_result.skip_reason.startswith("ULTRATHINK_BLOCK_DELTA_BAR_LONG"):
                # Format : ULTRATHINK_BLOCK_DELTA_BAR_LONG:delta={d}>={t} (MSG)
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    parts = payload.split(" ", 1)[0]
                    delta_v, thr_v = parts.split(">=", 1)
                    delta_v = delta_v.replace("delta=", "").strip()
                except (IndexError, ValueError):
                    delta_v, thr_v = "?", "?"
                bot_log.emit(
                    "BOTMR_ULTRATHINK_BLOCK_DELTA_BAR_LONG",
                    sym=sym, delta_bar=delta_v, threshold=thr_v,
                )
            elif signal_result.skip_reason.startswith("ULTRATHINK_BLOCK_DELTA_BAR_SHORT"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    parts = payload.split(" ", 1)[0]
                    delta_v, thr_v = parts.split("<=", 1)
                    delta_v = delta_v.replace("delta=", "").strip()
                except (IndexError, ValueError):
                    delta_v, thr_v = "?", "?"
                bot_log.emit(
                    "BOTMR_ULTRATHINK_BLOCK_DELTA_BAR_SHORT",
                    sym=sym, delta_bar=delta_v, threshold=thr_v,
                )
            elif signal_result.skip_reason.startswith("ULTRATHINK_BLOCK_FINISH_STRENGTH_LONG"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    parts = payload.split(" ", 1)[0]
                    fs_v, thr_v = parts.split("<=", 1)
                    fs_v = fs_v.replace("finish=", "").strip()
                except (IndexError, ValueError):
                    fs_v, thr_v = "?", "?"
                bot_log.emit(
                    "BOTMR_ULTRATHINK_BLOCK_FINISH_STRENGTH_LONG",
                    sym=sym, finish_strength=fs_v, threshold=thr_v,
                )
            elif signal_result.skip_reason.startswith("ULTRATHINK_BLOCK_FINISH_STRENGTH_SHORT"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    parts = payload.split(" ", 1)[0]
                    fs_v, thr_v = parts.split(">=", 1)
                    fs_v = fs_v.replace("finish=", "").strip()
                except (IndexError, ValueError):
                    fs_v, thr_v = "?", "?"
                bot_log.emit(
                    "BOTMR_ULTRATHINK_BLOCK_FINISH_STRENGTH_SHORT",
                    sym=sym, finish_strength=fs_v, threshold=thr_v,
                )
            elif signal_result.skip_reason.startswith("ULTRATHINK_NO_DATA"):
                bot_log.emit(
                    "BOTMR_ULTRATHINK_NO_DATA",
                    sym=sym, direction=signal_result.direction,
                    delta_bar="?", finish_strength="?",
                )
            log_decision_jsonl(
                bar_ts=bar_ts, symbol=sym, signal=signal_result,
                executed=False, session_phase=session_phase,
                hypothetical=is_dry_eval,
            )
            return None

        # 🆕 Intermarket gate (Jackson 16/06) : confirmation leader (ES pour NQ).
        # Si pas de leader configure pour ce sym -> transparent.
        leader_sym = self.intermarket_gate.leader_for(sym)
        if leader_sym is not None:
            leader_ds = self.data_sources.get(leader_sym)
            leader_bar = leader_ds.peek_last_bar() if leader_ds is not None else None
            if leader_bar is None:
                bot_log.emit(
                    "BOTMR_INTERMARKET_LEADER_MISSING",
                    sym=sym,
                    leader_sym=leader_sym,
                )
            inter_verdict = self.intermarket_gate.confirm(sym, signal_result.direction, leader_bar)
            if not inter_verdict.allowed:
                self.log.info(
                    f"{sym} INTERMARKET BLOCK {signal_result.direction} : {inter_verdict.reason}"
                )
                bot_log.emit(
                    "BOTMR_GATE_INTERMARKET_BLOCK",
                    sym=sym,
                    direction=signal_result.direction,
                    reason=inter_verdict.reason,
                )
                log_decision_jsonl(
                    bar_ts=bar_ts, symbol=sym, signal=signal_result,
                    executed=False,
                    order_error=f"INTERMARKET_BLOCK:{inter_verdict.reason}",
                    session_phase=session_phase, hypothetical=is_dry_eval,
                )
                return None
            bot_log.emit(
                "BOTMR_INTERMARKET_CONFIRM",
                sym=sym,
                direction=signal_result.direction,
                reason=inter_verdict.reason,
            )

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
            # + anti-clustering (entry_price = signal planifie pour dry-eval)
            self.engines[sym].register_trade(
                signal_result.signal_id,
                direction=signal_result.direction,
                entry_price=signal_result.entry_price,
            )
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

        # FIX R2 code-reviewer 18/06 : register_trade AVANT open_position pour
        # garantir que last_trade_ts est dans l'objet store quand save() persiste.
        # Sinon : crash entre register_trade et save -> last_trade_ts en memoire
        # mais NON persiste -> restart bypass cooldown (le bug qu'on veut fix).
        # Avec ce reorder, le save() unique en fin de bloc atomise les 2 mutations.
        # 18/06 ajout : direction + entry_price (= fill reel) pour NO_REENTRY anti-clustering.
        self.engines[sym].register_trade(
            signal_result.signal_id,
            direction=signal_result.direction,
            entry_price=order_result.fill_price,
        )
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
        self.store.save()
        # FIX 17/06 : register CIDs DTC reels avant state_bridge open (anti-race)
        if self.fill_listener is not None:
            try:
                self.fill_listener.register_bracket(
                    sym=sym, signal_id=signal_result.signal_id,
                    direction=signal_result.direction,
                    entry_price=order_result.fill_price,
                    sl_price=signal_result.sl_price,
                    tp_price=signal_result.tp_price,
                    sl_ticks=signal_result.sl_ticks,
                    tp_ticks=signal_result.tp_ticks,
                    n_micros=self.cfg.N_MICROS_DEFAULT,
                    parent_cid=order_result.parent_cid,
                    tp_cid=order_result.tp_cid,
                    sl_cid=order_result.sl_cid,
                )
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"fill_listener register fail: {e}")
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
