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
import os
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


# Sentinelle direction pour les gates qui bloquent AVANT que la direction soit
# calculee (signal_engine.py:638 `direction = None`, assignee seulement en 640/642).
# Ces gates (COOLDOWN, REGIME_SESSION_BLOCK, RVOL_TOO_LOW, NO_EXTENSION) sont
# direction-agnostiques PAR CONCEPTION : ils bloquent les deux sens indifferemment.
# Loguer `None` nu ferait croire a un trou de logging (cf review code-reviewer 09/07).
# Pour NO_EXTENSION, la direction VISEE se derive de d_low/d_high, deja loggees.
_PRE_DIR = "PRE_DIR"


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

        # V_FINAL audit market-analyst 24/06 : RegimeClassifier mutuellement exclusif
        # (5 regimes) + 3 regles blacklist (PANIC, CALM_RANGE us_cash, VOLATILE asia).
        # Backtest 7j empirique +$299, 95% wins preserves. Distinct du
        # RegimeClassifier 18/06 (vote majoritaire - autre semantique).
        # Stateful par-symbol (EWM slope smoothing) - une instance partagee
        # entre tous les SignalEngine, isolation symbole via dict interne.
        from CORE.bot_mean_revert.regime_classifier import (
            RegimeClassifier as RegimeClassifierVFinal,
            RegimeThresholds,
        )
        # Fix audit 30/06 R4 : env vars override pour tuner sans redeploy
        # (BOTMR_VIX_PANIC, BOTMR_ATR_PCT_PANIC, BOTMR_VIX_PANIC_EXTREME).
        _thresholds = RegimeThresholds(
            vix_panic=self.cfg.VIX_PANIC,
            atr_pct_panic=self.cfg.ATR_PCT_PANIC,
            vix_panic_extreme=self.cfg.VIX_PANIC_EXTREME,
        )
        self.regime_classifier_v_final = RegimeClassifierVFinal(
            thresholds=_thresholds,
        )

        # Callback emit BOTMR_REGIME_DETECTED (decoupe bot_log du engine).
        def _emit_regime_detected(sym: str, regime_str: str, session_str: str) -> None:
            try:
                bot_log.emit(
                    "BOTMR_REGIME_DETECTED",
                    sym=sym, regime=regime_str, session=session_str,
                )
            except Exception as exc:  # noqa: BLE001
                self.log.warning(f"emit BOTMR_REGIME_DETECTED fail: {exc}")

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
                regime_classifier_v_final=self.regime_classifier_v_final,
                on_regime_detected=_emit_regime_detected,
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
        # FIX audit 19/06 : restaurer daily_gate cross-restart si meme date UTC.
        # Sans ca, DSL=-$2500 / DSW / MAX_TRADES sont effaces a chaque restart =
        # carnage 18/06 FOMC root cause (15 restarts -> DSL jamais mordue).
        # Filtre par date_str : nouveau jour UTC -> reset propre.
        prior = self.store.get_daily_state()
        if prior and prior.get("date_str") == today:
            self.daily_gate.restore(
                n_trades_today=int(prior.get("n_trades_today", 0)),
                cumul_pnl_usd=float(prior.get("cumul_pnl_usd", 0.0)),
                date_str=today,
            )
            bot_log.emit(
                "BOTMR_DAILY_STATE_RESTORED",
                date_str=today,
                n_trades_today=int(prior.get("n_trades_today", 0)),
                cumul_pnl_usd=round(float(prior.get("cumul_pnl_usd", 0.0)), 2),
            )
        else:
            self.daily_gate.reset_for_new_day(today)
            reason = "NEW_DAY" if prior else "NO_PRIOR_STATE"
            bot_log.emit("BOTMR_DAILY_STATE_RESET", date_str=today, reason=reason)
            # Persiste immediatement le nouveau snapshot vide pour le prochain boot.
            try:
                self.store.set_daily_state(self.daily_gate.snapshot())
                self.store.save()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"daily_state init persist fail: {e}")

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
            # FIX audit 19/06 : persister daily_state apres maj pour survivre
            # cross-restart (carnage 18/06 FOMC root cause).
            try:
                self.store.set_daily_state(self.daily_gate.snapshot())
                self.store.save()
            except Exception as persist_err:  # noqa: BLE001
                # FIX bug #5 review : escalade CRITIQUE (Discord) au lieu de
                # warning silencieux. Si persist fail = restart suivant aura
                # daily_state stale = DSL inoperante = carnage 18/06 reproduit.
                self.log.critical(
                    f"daily_state persist after trade FAIL: {persist_err}. "
                    f"DSL inoperante au prochain restart."
                )
                bot_log.emit(
                    "BOTMR_DAILY_STATE_PERSIST_FAIL",
                    context="on_fill_close",
                    err=str(persist_err)[:200],
                )
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
                    # FIX review A3 IMPORTANT-1 23/06 : persist IMMEDIAT apres
                    # increment pour fermer la fenetre crash (~5-10 LOC entre
                    # increment et save() ligne 313 plus bas). Si crash dans
                    # cette fenetre, le compteur n_sl_consec est perdu au
                    # restart suivant = cooldown progressif inoperant = carnage
                    # type FOMC reproduit. Atomicite critique.
                    try:
                        self.store.save()
                    except Exception as save_err:  # noqa: BLE001
                        self.log.warning(
                            f"store.save FAIL after increment_sl_consec: "
                            f"{save_err}"
                        )
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
        # FIX observabilite 09/07 : le DONE ne loggait que {sym} -> les trades fermes
        # par MAX_HOLD etaient invisibles en audit (ni direction, ni entry, ni duree),
        # violation regle LOGS TRACABILITE. exit_price/pnl ne sont PAS connus ici : ils
        # arrivent via DtcFillListener sur le fill du MARKET CLOSE (cf. Step 7 ci-dessus).
        # signal_id (R2 review 09/07) : c'est le fil qui permet de recoller ce DONE au
        # fill/pnl asynchrone qui arrive plus tard. Sans lui, correlation heuristique.
        bot_log.emit(
            "BOTMR_TIMEOUT_CLOSE_DONE",
            signal_id=pos.get("signal_id"),
            sym=sym, direction=direction, entry_price=entry_price,
            elapsed_min=round(elapsed_min, 1), n_micros=n_micros,
        )

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

    def _force_flatten_broker(
        self, sym: str, contract: str, ta: str, reason: str,
    ) -> None:
        """Envoie Type 209 SUBMIT_FLATTEN_POSITION_ORDER pour ce symbole.

        Utilise quand MIA_BOT_MR_RECONCILE_FORCE_FLAT=1 + cas
        UNKNOWN_BROKER_POS ou DIVERGENCE detecte au boot. Reset broker
        a flat pour eviter le mode aveugle (sinon nouvelle entry =
        double position = orphelin garanti).

        ClientOrderID OBLIGATOIRE (orphan-prevention.md : SC rejette
        silencieusement Type 209/210 sans CID).
        """
        if self.router is None or self.router.dtc is None:
            bot_log.emit(
                "BOTMR_RECONCILE_FORCE_FLAT_DTC_DOWN",
                sym=sym, reason=reason,
            )
            return
        dtc = self.router.dtc
        flatten_cid = (
            f"BOTMR_RECONCILE_FFLAT_{sym[:2]}_{int(time.time()) % 100000}"
        )
        try:
            dtc._send({
                "Type": 209,
                "ClientOrderID": flatten_cid,
                "Symbol": contract,
                "TradeAccount": ta,
                "Exchange": "CME",
                "IsAutomatedOrder": 1,
            })
            bot_log.emit(
                "BOTMR_RECONCILE_FORCE_FLAT_SENT",
                sym=sym, contract=contract, ta=ta,
                cid=flatten_cid, reason=reason,
            )
        except Exception as e:  # noqa: BLE001
            bot_log.emit(
                "BOTMR_RECONCILE_FORCE_FLAT_EXCEPTION",
                sym=sym, err=str(e)[:200], reason=reason,
            )

    def _reconcile_with_dtc_at_boot(self) -> bool:
        """Reconcilie store.positions avec broker DTC apres connect.

        FIX audit 19/06 code-reviewer : sans reconcile, une desync Sierra Chart
        (cas 19/06 PARENT_NOT_FILLED_TIMEOUT apres restart) laisse Bot MR
        croire pos OPEN alors que broker est FLAT (ou inverse). Resultat :
          - Python pos + broker flat = position fantome eternelle (skip trades)
          - Python flat + broker pos = bot ignore une position reelle exposee
          - divergence direction/qty = trade reel sur mauvaise hypothese

        5 cas explicites (extraits de bot_persistance.PositionPersistance) :
          OK_FLAT          : python flat + broker flat -> OK (no-op)
          OK_RESTORED      : python pos + broker match (direction + qty) -> OK
          PYTHON_GHOST     : python pos + broker flat -> auto-purge + ALERTE
          UNKNOWN_BROKER   : python flat + broker pos -> HALT BOOT
          DIVERGENCE       : python pos + broker pos mismatch -> HALT BOOT

        Bypass HALT via env var MIA_BOT_MR_RECONCILE_FORCE_FLAT=1 (Jackson explicite).

        Returns:
            True si reconcile OK (boot peut proceder). False si HALT critique.
        """
        # Dry-run ou pas de DTC : skip reconcile (rien a verifier)
        if self.router is None or getattr(self.router, "dtc", None) is None:
            bot_log.emit("BOTMR_RECONCILE_SKIPPED", reason="NO_DTC_DRY_RUN")
            return True

        dtc = self.router.dtc
        ta = self.cfg.TRADE_ACCOUNT
        force_flat = os.environ.get(
            "MIA_BOT_MR_RECONCILE_FORCE_FLAT", "0"
        ) == "1"
        has_critical = False

        # Union des symboles a verifier : tous ceux configures + ceux ayant
        # une position persistee (au cas ou rollover/config change post-restart).
        # FIX bug #4 review : snapshot list explicit avant la boucle pour eviter
        # race condition avec fill_listener.handle_order_update qui peut muter
        # self.store.positions en parallele depuis _recv_loop thread DTC.
        # `sorted(list(...))` materialise une copie -> safe iteration.
        syms_to_check = sorted(list(
            set(s.upper() for s in self.symbols)
            | set(s.upper() for s in list(self.store.positions.keys()))
        ))

        for sym in syms_to_check:
            contract = self._sym_to_contract(sym)
            try:
                broker_qty = dtc.request_position_blocking(
                    contract, trade_account=ta, timeout=3.0,
                )
            except Exception as e:  # noqa: BLE001
                self.log.error(f"{sym} reconcile query FAIL: {e}")
                bot_log.emit(
                    "BOTMR_RECONCILE_QUERY_FAILED",
                    sym=sym, contract=contract, err=str(e)[:200],
                )
                has_critical = True
                continue

            py_pos = self.store.positions.get(sym)
            py_flat = py_pos is None
            # broker_qty = None => DTC pas de reponse, considere critique (cf orphan-prevention R3)
            if broker_qty is None:
                # FIX 24/06/2026 Jackson directive : ES + NQ simultaneous trading.
                # Avant : BROKER_QTY_NONE -> has_critical=True -> HALT bot ENTIER.
                # Probleme : si ES n'a aucune position chez le broker, DTC ne repond
                # pas et le bot halt -> impossible de trader ES (le service tournait
                # avec --symbols NQ seul justement a cause de ca).
                # Apres : si MIA_BOT_MR_RECONCILE_FORCE_FLAT=1 ET Python state flat,
                # on accepte broker_qty=None comme equivalent "flat" (consistant Python).
                # Reasoning : DTC sans reply = soit pas de position soit DTC freeze.
                # Avec force_flat=1 + py_flat=True, on traite comme OK_FLAT et continue.
                if force_flat and py_flat:
                    self.log.warning(
                        f"{sym} reconcile : broker_qty=None + force_flat=1 + py_flat "
                        f"-> traite comme OK_FLAT (bypass HALT)."
                    )
                    bot_log.emit(
                        "BOTMR_RECONCILE_QUERY_FAILED_BYPASS_FLAT",
                        sym=sym, contract=contract,
                    )
                    continue
                # Sinon : halt critique (orphan-prevention R3)
                self.log.error(
                    f"{sym} reconcile : broker_qty=None (DTC freeze ou no reply). HALT."
                )
                bot_log.emit(
                    "BOTMR_RECONCILE_QUERY_FAILED",
                    sym=sym, contract=contract, err="BROKER_QTY_NONE",
                )
                has_critical = True
                continue
            br_flat = broker_qty == 0

            # Cas a : OK_FLAT
            if py_flat and br_flat:
                bot_log.emit("BOTMR_RECONCILE_OK_FLAT", sym=sym)
                continue

            # Cas c : python flat + broker pos -> UNKNOWN_BROKER_POS
            if py_flat and not br_flat:
                br_side = "LONG" if broker_qty > 0 else "SHORT"
                action = "FORCE_FLATTEN_BROKER" if force_flat else "HALT_BOOT"
                self.log.critical(
                    f"{sym} RECONCILE_UNKNOWN_BROKER_POS: broker has {br_side} "
                    f"qty={abs(broker_qty)} but Python state flat. action={action}"
                )
                bot_log.emit(
                    "BOTMR_RECONCILE_UNKNOWN_BROKER_POS",
                    sym=sym,
                    broker_qty=broker_qty,
                    broker_side=br_side,
                    action=action,
                )
                if force_flat:
                    # FIX bug #2 review 19/06 : force_flat=1 doit ACTIVEMENT
                    # flatten le broker, sinon mode aveugle dangereux (bot va
                    # trader croit flat alors que broker a deja une pos = double
                    # position au prochain entry). Type 209 + ClientOrderID
                    # obligatoire (orphan-prevention.md).
                    self._force_flatten_broker(sym, contract, ta, reason="UNKNOWN_BROKER_POS")
                else:
                    has_critical = True
                continue

            # Cas d : python pos + broker flat -> PYTHON_GHOST (auto-purge)
            if (not py_flat) and br_flat:
                self.log.warning(
                    f"{sym} RECONCILE_PYTHON_GHOST: Python pos "
                    f"{py_pos.get('direction')} entry={py_pos.get('entry_price')} "
                    f"but broker flat. Cancel TP/SL orphans + purge."
                )
                bot_log.emit(
                    "BOTMR_RECONCILE_PYTHON_GHOST",
                    sym=sym,
                    py_direction=py_pos.get("direction"),
                    py_entry=py_pos.get("entry_price"),
                )
                # FIX bug #1 review 19/06 : orphan-prevention.md exige cancel
                # des CIDs TP/SL connus AVANT purge store. Sans ca, ordres restent
                # Working dans le DOM Sim1 -> fire 2h plus tard = trade fantome
                # = perte capital. Reference incident production Bot 3 04/05.
                tp_cid = py_pos.get("tp_cid")
                sl_cid = py_pos.get("sl_cid")
                for leg_label, cid in [("TP", tp_cid), ("SL", sl_cid)]:
                    if not cid:
                        continue
                    try:
                        ok = dtc.cancel_order(cid, trade_account=ta)
                        if not ok:
                            bot_log.emit(
                                "BOTMR_RECONCILE_GHOST_CANCEL_FAIL",
                                sym=sym, leg=leg_label, cid=cid,
                            )
                    except Exception as cancel_err:  # noqa: BLE001
                        bot_log.emit(
                            "BOTMR_RECONCILE_GHOST_CANCEL_EXCEPTION",
                            sym=sym, leg=leg_label, cid=cid,
                            err=str(cancel_err)[:200],
                        )
                # Propagation cancels avant flatten defensif
                time.sleep(1.0)
                # Type 209 flatten symbole = defense en profondeur (cf orphan-prevention
                # step 7) au cas ou des Working orders sans CID connus existent encore.
                # ClientOrderID OBLIGATOIRE (SC rejette sans).
                flatten_cid = (
                    f"BOTMR_RECONCILE_GHOST_{sym[:2]}_"
                    f"{int(time.time()) % 100000}"
                )
                try:
                    dtc._send({
                        "Type": 209,
                        "ClientOrderID": flatten_cid,
                        "Symbol": contract,
                        "TradeAccount": ta,
                        "Exchange": "CME",
                        "IsAutomatedOrder": 1,
                    })
                    bot_log.emit(
                        "BOTMR_RECONCILE_GHOST_FLATTEN_SENT",
                        sym=sym, cid=flatten_cid,
                    )
                except Exception as flatten_err:  # noqa: BLE001
                    bot_log.emit(
                        "BOTMR_RECONCILE_GHOST_FLATTEN_EXCEPTION",
                        sym=sym, err=str(flatten_err)[:200],
                    )
                # Purge store + state_bridge (audit P&L manuel a faire cote Sierra)
                self.store.close_position(sym)
                try:
                    self.store.save()
                except Exception as e:  # noqa: BLE001
                    self.log.warning(
                        f"store.save fail after ghost purge {sym}: {e}"
                    )
                try:
                    self.state_bridge.close_position(
                        sym, exit_reason="RECONCILE_GHOST",
                    )
                except Exception as e:  # noqa: BLE001
                    self.log.warning(
                        f"state_bridge close on ghost fail: {e}"
                    )
                continue

            # Cas b ou e : python pos + broker pos -> match ou divergence
            py_dir = str(py_pos.get("direction") or "").upper()
            py_qty = int(py_pos.get("n_micros", 0))
            br_side = "LONG" if broker_qty > 0 else "SHORT"
            br_qty = abs(int(broker_qty))

            if py_dir == br_side and py_qty == br_qty:
                bot_log.emit(
                    "BOTMR_RECONCILE_OK_RESTORED",
                    sym=sym, direction=py_dir, qty=py_qty,
                )
                continue

            # Cas e : divergence
            action = "FORCE_FLATTEN_BROKER" if force_flat else "HALT_BOOT"
            self.log.critical(
                f"{sym} RECONCILE_DIVERGENCE: Python {py_dir} {py_qty} vs "
                f"Broker {br_side} {br_qty}. action={action}"
            )
            bot_log.emit(
                "BOTMR_RECONCILE_DIVERGENCE",
                sym=sym,
                py_direction=py_dir, py_qty=py_qty,
                br_direction=br_side, br_qty=br_qty,
                action=action,
            )
            if force_flat:
                # FIX bug #2 review 19/06 : flatten broker ET purge store pour
                # reset propre. Sinon le bot continue avec un tracking incorrect.
                self._force_flatten_broker(sym, contract, ta, reason="DIVERGENCE")
                self.store.close_position(sym)
                try:
                    self.store.save()
                except Exception as e:  # noqa: BLE001
                    self.log.warning(
                        f"store.save fail after divergence flatten {sym}: {e}"
                    )
                try:
                    self.state_bridge.close_position(
                        sym, exit_reason="RECONCILE_FORCE_FLAT",
                    )
                except Exception as e:  # noqa: BLE001
                    self.log.warning(
                        f"state_bridge close on divergence flatten fail: {e}"
                    )
            else:
                has_critical = True

        if has_critical:
            self.log.critical(
                "Reconcile DTC : cas CRITIQUE detecte. Boot halt. "
                "Bypass via MIA_BOT_MR_RECONCILE_FORCE_FLAT=1 (decision Jackson)."
            )
            bot_log.emit("BOTMR_RECONCILE_HALT_BOOT", force_flat_available="1")
            return False

        bot_log.emit("BOTMR_RECONCILE_OK")
        return True

    def _rotate_day_if_needed(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        old_date = self.daily_gate.state.date_str
        if old_date != today:
            self.log.info(f"Day rollover: {old_date} -> {today}")
            bot_log.emit("BOTMR_DAY_ROLLOVER", old_date=old_date, new_date=today)
            self.daily_gate.reset_for_new_day(today)
            # FIX audit 19/06 : persister snapshot reset pour eviter restore
            # ancien jour au prochain restart cross-rollover.
            try:
                self.store.set_daily_state(self.daily_gate.snapshot())
                self.store.save()
            except Exception as e:  # noqa: BLE001
                self.log.warning(f"daily_state rotate persist fail: {e}")
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
            # 18/06 Regime classifier vote majoritaire 3 signaux (Phase 3).
            # Format skip_reason : "REGIME_CLASSIFIER_BLOCKED:{regime}_blocks_{direction} "
            #                      "votes={votes} signals={signals}"
            # FIX bug #3 review 19/06 : ce prefixe tombait en BOTMR_NOT_TRADABLE
            # catch-all (manquait dispatch). Maintenant emit code dedie deja
            # present dans log_catalog (BOTMR_REGIME_CLASSIFIER_BLOCK).
            elif signal_result.skip_reason.startswith("REGIME_CLASSIFIER_BLOCKED"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    head, _sep, rest = payload.partition(" ")
                    regime_val = head.split("_blocks_", 1)[0]
                    votes_part = (
                        rest.split("votes=", 1)[1].split(" ", 1)[0]
                        if "votes=" in rest else "?"
                    )
                except (IndexError, ValueError):
                    regime_val, votes_part = "?", "?"
                bot_log.emit(
                    "BOTMR_REGIME_CLASSIFIER_BLOCK",
                    sym=sym,
                    direction=signal_result.direction or "?",
                    regime=regime_val,
                    votes=votes_part,
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
                    sym=sym, direction=signal_result.direction,
                    delta_bar=delta_v, threshold=thr_v,
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
                    sym=sym, direction=signal_result.direction,
                    delta_bar=delta_v, threshold=thr_v,
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
            # ════════════════════════════════════════════════════════════════
            # FIX 3 audit 19/06 : dispatch codes specifiques pour les ~12 prefixes
            # qui tombaient dans BOTMR_NOT_TRADABLE catch-all (5111/6861 events
            # = 74.5% des skips opaque a l'analyse cf audit market-analyst).
            # ════════════════════════════════════════════════════════════════
            elif signal_result.skip_reason.startswith("CIRCUIT_BREAKER_HALT"):
                # Format : "CIRCUIT_BREAKER_HALT:{N}s_remaining"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    remaining = payload.replace("s_remaining", "").strip()
                except (IndexError, ValueError):
                    remaining = "?"
                bot_log.emit(
                    "BOTMR_CIRCUIT_BREAKER_ACTIVE",
                    sym=sym, remaining_sec=remaining,
                )
            elif signal_result.skip_reason.startswith("COOLDOWN_PROGRESSIVE"):
                # FIX A3 23/06 : Format "COOLDOWN_PROGRESSIVE:{elapsed}s/{cooldown}s n_sl_consec={n}"
                # Code dedie au cooldown progressif post-LOSS (vs COOLDOWN standard).
                # Note : ce elif DOIT etre AVANT "COOLDOWN" car startswith("COOLDOWN")
                # matcherait aussi "COOLDOWN_PROGRESSIVE" et stealerait l'emit.
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    parts = payload.split(" n_sl_consec=", 1)
                    timing_part = parts[0]
                    n_sl_str = parts[1].strip() if len(parts) > 1 else "0"
                    elapsed_str, cool_str = timing_part.split("/", 1)
                    elapsed_val = float(elapsed_str.replace("s", "").strip())
                    cool_val = float(cool_str.replace("s", "").strip())
                    n_sl_val = int(n_sl_str)
                except (IndexError, ValueError) as parse_err:
                    # FIX review A3 IMPORTANT-2 23/06 : log warning au lieu de
                    # silent fallback. Si format skip_reason change accidentellement
                    # (regression signal_engine), emit silencieux avec valeurs 0 =
                    # invisible J+1 (anti-pattern VALIDATION_MISS regle log B).
                    elapsed_val, cool_val, n_sl_val = 0.0, 0.0, 0
                    self.log.warning(
                        f"COOLDOWN_PROGRESSIVE skip_reason parse FAIL: "
                        f"{signal_result.skip_reason!r} ({parse_err})"
                    )
                bot_log.emit(
                    "BOTMR_COOLDOWN_PROGRESSIVE_ACTIVE",
                    sym=sym, direction=_PRE_DIR,
                    elapsed=elapsed_val,
                    cooldown=cool_val, n_sl_consec=n_sl_val,
                )
            elif signal_result.skip_reason.startswith("COOLDOWN"):
                # Format : "COOLDOWN:{elapsed}s/{cooldown}s" (time-based)
                # ou "COOLDOWN:{n}/{N}" (legacy counter)
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    elapsed_val, cool_val = payload.split("/", 1)
                    elapsed_val = elapsed_val.replace("s", "").strip()
                    cool_val = cool_val.replace("s", "").strip()
                except (IndexError, ValueError):
                    elapsed_val, cool_val = "?", "?"
                bot_log.emit(
                    "BOTMR_COOLDOWN_ACTIVE",
                    sym=sym, elapsed=elapsed_val, cooldown_sec=cool_val,
                )
            elif signal_result.skip_reason.startswith("SESSION_NOT_ALLOWED"):
                # Format : "SESSION_NOT_ALLOWED:{phase}"
                try:
                    phase_val = signal_result.skip_reason.split(":", 1)[1].strip()
                except (IndexError, ValueError):
                    phase_val = "?"
                allowed = ",".join(self.cfg.tradable_sessions(sym))
                bot_log.emit(
                    "BOTMR_SESSION_NOT_ALLOWED",
                    sym=sym, phase=phase_val, allowed=allowed,
                )
            elif signal_result.skip_reason.startswith("PREOPEN_US_SKIP"):
                bot_log.emit("BOTMR_PREOPEN_US_SKIP", sym=sym)
            elif signal_result.skip_reason.startswith("RVOL_TOO_LOW"):
                # Format : "RVOL_TOO_LOW:{rvol_z}<{min_z}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    rvol_val, min_val = payload.split("<", 1)
                except (IndexError, ValueError):
                    rvol_val, min_val = "?", "?"
                bot_log.emit(
                    "BOTMR_RVOL_TOO_LOW",
                    sym=sym, direction=_PRE_DIR,
                    rvol_z=rvol_val, min_z=min_val,
                )
            elif signal_result.skip_reason.startswith("NO_EXTENSION"):
                # Format : "NO_EXTENSION:d_low={x} d_high={y} thr={z}"
                # 75% des skips d'apres audit market-analyst — code dedicated CRITIQUE
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    d_low_val = payload.split("d_low=", 1)[1].split(" ", 1)[0]
                    d_high_val = payload.split("d_high=", 1)[1].split(" ", 1)[0]
                    thr_val = payload.split("thr=", 1)[1].strip()
                except (IndexError, ValueError):
                    d_low_val, d_high_val, thr_val = "?", "?", "?"
                bot_log.emit(
                    "BOTMR_NO_EXTENSION",
                    sym=sym, direction=_PRE_DIR,
                    d_low=d_low_val, d_high=d_high_val, thr=thr_val,
                )
            # FIX BUG #2 review code-reviewer 23/06 : 3 dispatchers manquants
            # pour codes Phase A. Sans ces branches, codes definis log_catalog.py
            # mais jamais emis = VALIDATION_MISS J+1 (pattern 8+ occurrences).
            elif signal_result.skip_reason.startswith("LONG_BELOW_VWAP_INTRADAY"):
                # Format : "LONG_BELOW_VWAP_INTRADAY:dist={x}<{thr}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    dist_str, thr_str = payload.split("<", 1)
                    dist_val = float(dist_str.replace("dist=", "").strip())
                    thr_val_f = float(thr_str.strip())
                except (IndexError, ValueError):
                    dist_val, thr_val_f = 0.0, 0.0
                bot_log.emit(
                    "BOTMR_LONG_BELOW_VWAP_BLOCK",
                    sym=sym, dist=dist_val, thr=thr_val_f,
                )
            elif signal_result.skip_reason.startswith("SHORT_ABOVE_VWAP_INTRADAY"):
                # Format : "SHORT_ABOVE_VWAP_INTRADAY:dist={x}>{thr}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    dist_str, thr_str = payload.split(">", 1)
                    dist_val = float(dist_str.replace("dist=", "").strip())
                    thr_val_f = float(thr_str.strip())
                except (IndexError, ValueError):
                    dist_val, thr_val_f = 0.0, 0.0
                bot_log.emit(
                    "BOTMR_SHORT_ABOVE_VWAP_BLOCK",
                    sym=sym, dist=dist_val, thr=thr_val_f,
                )
            elif signal_result.skip_reason.startswith("NEWS_GATE_FAIL_CLOSED"):
                # FIX A4 23/06 : Format "NEWS_GATE_FAIL_CLOSED:err={msg}"
                # Module eco_calendar HS = fail-closed (mieux rater trade que FOMC).
                try:
                    err_val = signal_result.skip_reason.split(":", 1)[1]
                    err_val = err_val.replace("err=", "").strip()
                except (IndexError, ValueError):
                    err_val = "?"
                bot_log.emit(
                    "BOTMR_NEWS_GATE_FAIL_CLOSED",
                    sym=sym, err=err_val[:200],
                )
            elif signal_result.skip_reason.startswith("NEWS_BLOCK"):
                # FIX A4 23/06 : Format "NEWS_BLOCK:event={x} until={iso} buffer_min={n}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    event_val = payload.split("event=", 1)[1].split(" until=", 1)[0]
                    until_val = payload.split("until=", 1)[1].split(" buffer_min=", 1)[0]
                    buffer_str = payload.split("buffer_min=", 1)[1].strip()
                    buffer_val = int(buffer_str)
                except (IndexError, ValueError) as parse_err:
                    event_val, until_val, buffer_val = "?", "?", 0
                    self.log.warning(
                        f"NEWS_BLOCK skip_reason parse FAIL: "
                        f"{signal_result.skip_reason!r} ({parse_err})"
                    )
                bot_log.emit(
                    "BOTMR_NEWS_WINDOW_BLOCK",
                    sym=sym, event=event_val, until_iso=until_val,
                    buffer_min=buffer_val,
                )
            elif signal_result.skip_reason.startswith("REGIME_SESSION_BLOCK"):
                # Format : "REGIME_SESSION_BLOCK:regime={r} session={s}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    regime_val = payload.split("regime=", 1)[1].split(" ", 1)[0]
                    session_val = payload.split("session=", 1)[1].strip()
                except (IndexError, ValueError):
                    regime_val, session_val = "?", "?"
                bot_log.emit(
                    "BOTMR_REGIME_SESSION_BLOCK",
                    sym=sym, direction=_PRE_DIR,
                    regime=regime_val, session=session_val,
                )
            elif signal_result.skip_reason.startswith("MOMENTUM_5B_TOO_BEAR_LONG"):
                # Format : "MOMENTUM_5B_TOO_BEAR_LONG:mom_5b={x}<{thr} (ANTI_...)"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    val_part = payload.split("(", 1)[0].strip()
                    mom_str, thr_str = val_part.split("<", 1)
                    mom_val = float(mom_str.replace("mom_5b=", "").strip())
                    thr_val = float(thr_str.strip())
                except (IndexError, ValueError):
                    mom_val, thr_val = 0.0, 0.0
                bot_log.emit(
                    "BOTMR_MOMENTUM_5B_BLOCK_LONG",
                    sym=sym, mom_5b=mom_val, thr=thr_val,
                )
            elif signal_result.skip_reason.startswith("MOMENTUM_5B_TOO_BULL_SHORT"):
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    val_part = payload.split("(", 1)[0].strip()
                    mom_str, thr_str = val_part.split(">", 1)
                    mom_val = float(mom_str.replace("mom_5b=", "").strip())
                    thr_val = float(thr_str.strip())
                except (IndexError, ValueError):
                    mom_val, thr_val = 0.0, 0.0
                bot_log.emit(
                    "BOTMR_MOMENTUM_5B_BLOCK_SHORT",
                    sym=sym, mom_5b=mom_val, thr=thr_val,
                )
            elif signal_result.skip_reason.startswith("SESSION_AH_BLOCK"):
                # Format : "SESSION_AH_BLOCK:hour={h}h in [{s}-{e}h] UTC"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    hour_str = payload.split("hour=", 1)[1].split("h", 1)[0]
                    bracket = payload.split("[", 1)[1].split("]", 1)[0]
                    start_str, end_str = bracket.replace("h", "").split("-", 1)
                    hour_val = int(hour_str)
                    start_val = int(start_str)
                    end_val = int(end_str)
                except (IndexError, ValueError):
                    hour_val, start_val, end_val = 0, 0, 0
                bot_log.emit(
                    "BOTMR_SESSION_AH_BLOCK",
                    sym=sym, hour=hour_val, start=start_val, end=end_val,
                )
            elif signal_result.skip_reason.startswith("SD_FEATURE_MISSING"):
                # Format : "SD_FEATURE_MISSING:level={x} d_low={y} d_high={z}"
                # Fail-loud anti-pattern Gamma=0.0 (BUG #3 review 23/06)
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    level_val = payload.split("level=", 1)[1].split(" ", 1)[0]
                    d_low_val = payload.split("d_low=", 1)[1].split(" ", 1)[0]
                    d_high_val = payload.split("d_high=", 1)[1].strip()
                except (IndexError, ValueError):
                    level_val, d_low_val, d_high_val = "?", "?", "?"
                bot_log.emit(
                    "BOTMR_SD_FEATURE_MISSING",
                    sym=sym, level=level_val, d_low=d_low_val, d_high=d_high_val,
                )
            elif signal_result.skip_reason.startswith(
                ("REGIME_TREND_ES", "REGIME_CONTRA_NQ")
            ):
                # Format : "REGIME_TREND_ES_LONG_BLOCKED:slope_30={x}"
                # ou      "REGIME_CONTRA_NQ_SHORT_BLOCKED:slope_30={x}"
                prefix = signal_result.skip_reason.split(":", 1)[0]
                mode = (
                    "trend_align_es"
                    if "TREND_ES" in prefix
                    else "contrarian_nq"
                )
                bot_log.emit(
                    "BOTMR_REGIME_MODE_BLOCK",
                    sym=sym,
                    direction=signal_result.direction or "?",
                    mode=mode,
                    reason=signal_result.skip_reason,
                )
            elif signal_result.skip_reason.startswith("VIX_TOO_LOW_FOR_SHORT"):
                # Format : "VIX_TOO_LOW_FOR_SHORT:{vix}<={min_vix}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    vix_val, min_val = payload.split("<=", 1)
                except (IndexError, ValueError):
                    vix_val, min_val = "?", "?"
                bot_log.emit(
                    "BOTMR_VIX_TOO_LOW_FOR_SHORT",
                    sym=sym, vix=vix_val, min_vix=min_val,
                )
            elif signal_result.skip_reason.startswith("NQ_TREND_DAY_TOO_HIGH"):
                # Format : "NQ_TREND_DAY_TOO_HIGH:{score}>{max_score}"
                try:
                    payload = signal_result.skip_reason.split(":", 1)[1]
                    score_val, max_val = payload.split(">", 1)
                except (IndexError, ValueError):
                    score_val, max_val = "?", "?"
                bot_log.emit(
                    "BOTMR_NQ_TREND_DAY_TOO_HIGH",
                    score=score_val, max_score=max_val,
                )
            elif signal_result.skip_reason.startswith("EXHAUSTION_REQUIRED"):
                bot_log.emit(
                    "BOTMR_EXHAUSTION_REQUIRED",
                    sym=sym, direction=signal_result.direction or "?",
                )
            elif signal_result.skip_reason.startswith(
                ("DELTA_NEG_FOR_LONG", "DELTA_POS_FOR_SHORT")
            ):
                # Format : "DELTA_NEG_FOR_LONG:{val}" / "DELTA_POS_FOR_SHORT:{val}"
                try:
                    delta_val = signal_result.skip_reason.split(":", 1)[1].strip()
                except (IndexError, ValueError):
                    delta_val = "?"
                bot_log.emit(
                    "BOTMR_DELTA_DIRECTION_BLOCK",
                    sym=sym,
                    direction=signal_result.direction or "?",
                    delta=delta_val,
                )
            elif signal_result.skip_reason.startswith("INVALID_CLOSE_PRICE"):
                bot_log.emit(
                    "BOTMR_INVALID_CLOSE_PRICE",
                    sym=sym, direction=signal_result.direction or "?",
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

        # FIX audit 19/06 : reconcile DTC AVANT d'entrer dans la boucle.
        # Si cas CRITIQUE (UNKNOWN_BROKER_POS ou DIVERGENCE), halt boot pour
        # forcer intervention manuelle Jackson (set env force_flat ou flatten SC).
        if not self._reconcile_with_dtc_at_boot():
            self.log.critical(
                "Boot HALTE par reconcile DTC. "
                "Set MIA_BOT_MR_RECONCILE_FORCE_FLAT=1 pour bypass."
            )
            bot_log.emit("BOTMR_BOOT_HALT_RECONCILE")
            return  # Exit clean sans entrer dans la loop

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
