"""Bot 3 — Market Profile Engine (orchestration).

Orchestre le pipeline complet :
  1. Detect contacts niveaux (Tier actifs selon phase + symbole)
  2. Anti double-trigger : last_bar_ts + cooldown bars
  3. Trading window UTC (heritee Bot 2)
  4. Pour chaque contact : context_analyzer → decision_engine
  5. Si GO + pas observe-only : Signal + snapshot entry record
  6. Log decision (GO/SKIP/VETO/TIER3_MISS) via log_catalog

Anti double-trigger : on ne re-evalue pas la meme bar 2x, et on impose
un cooldown N bars entre 2 contacts du meme niveau (anti tape-touch repete).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

try:
    from .bot3_config import (
        BOT3_ENABLE_TIER2,
        BOT3_ENABLE_TIER2_NEUTRAL,
        BOT3_ENABLE_TIER3,
        BOT3_OBSERVE_ONLY,
        BOT3_TRADE_BREAKOUTS,
        BOT3_USE_NARRATIVE_DIRECTION,
        BOT3_NARRATIVE_TRACKING_ONLY,
        GUARD_RAILS_BOT3,
        TRADING_WINDOW_END_UTC,
        TRADING_WINDOW_START_UTC,
    )
    try:
        from eco_calendar import is_blocked_combined as _eco_is_blocked
    except ImportError:
        from CORE.eco_calendar import is_blocked_combined as _eco_is_blocked
    from .bot3_context_analyzer import analyze_context
    from .bot3_decision_engine import evaluate_decision
    from .bot3_level_definitions import (
        get_active_levels,
        get_level_baseline_pf,
        get_level_baseline_rej,
        get_combos_boosted,
        is_sidak_level,
        is_combo_boosted,
        is_bucket_bypass_filter,
        COMBOS_BOOSTED,
    )
    from .bot3_breakout_retest import (
        BreakoutRetestStateMachine,
        BreakoutRetestSignal,
    )
except ImportError:
    from bot3_config import (
        BOT3_ENABLE_TIER2,
        BOT3_ENABLE_TIER2_NEUTRAL,
        BOT3_ENABLE_TIER3,
        BOT3_OBSERVE_ONLY,
        BOT3_TRADE_BREAKOUTS,
        BOT3_USE_NARRATIVE_DIRECTION,
        BOT3_NARRATIVE_TRACKING_ONLY,
        GUARD_RAILS_BOT3,
        TRADING_WINDOW_END_UTC,
        TRADING_WINDOW_START_UTC,
    )
    try:
        from eco_calendar import is_blocked_combined as _eco_is_blocked
    except ImportError:
        from CORE.eco_calendar import is_blocked_combined as _eco_is_blocked
    from bot3_context_analyzer import analyze_context
    from bot3_decision_engine import evaluate_decision
    from bot3_level_definitions import (
        get_active_levels,
        get_level_baseline_pf,
        get_level_baseline_rej,
        get_combos_boosted,
        is_sidak_level,
        is_combo_boosted,
        is_bucket_bypass_filter,
        COMBOS_BOOSTED,
    )
    from bot3_breakout_retest import (
        BreakoutRetestStateMachine,
        BreakoutRetestSignal,
    )

# ════════════════════════════════════════════════════════════════════════
# Phase 4d (2026-05-18 nuit Jackson directive) : import V2 narrative pour
# branchement Bot3Engine.evaluate() quand BOT3_USE_NARRATIVE_DIRECTION=True.
# Imports lazy en module-level pour eviter circular import si V2 modules
# importent indirectement bot3_mp_engine.
# ════════════════════════════════════════════════════════════════════════
try:
    from .bot3_narrative_state_machine import NarrativeStateMachine, NarrativeState
    from .bot3_direction_resolver import DirectionResolver
    _V2_NARRATIVE_AVAILABLE = True
except ImportError:
    try:
        from bot3_narrative_state_machine import NarrativeStateMachine, NarrativeState
        from bot3_direction_resolver import DirectionResolver
        _V2_NARRATIVE_AVAILABLE = True
    except ImportError:
        NarrativeStateMachine = None  # type: ignore[misc,assignment]
        NarrativeState = None  # type: ignore[misc,assignment]
        DirectionResolver = None  # type: ignore[misc,assignment]
        _V2_NARRATIVE_AVAILABLE = False


# Cooldown entre 2 contacts d'un meme niveau (en bars 1m)
# evite de retrigger sur des touch-touch-touch consecutifs (zone serree)
LEVEL_COOLDOWN_BARS = 5


# ════════════════════════════════════════════════════════════════════════
# Mapping reason (decision_engine) → log_catalog code (stable)
# ════════════════════════════════════════════════════════════════════════
# Le decision_engine retourne des reason strings (VETO_NEWS_IMMINENT, SKIP_BULL_STRONG...)
# Ces strings ne sont PAS des codes log_catalog, juste des etiquettes.
# Cette fonction map vers le code log canonique pour l'emission via emit_log.
# Empeche les KeyError sur resolve() pour codes inventes.
_REASON_TO_LOG_CODE: dict[str, str] = {
    "GO":                                     "BOT3_DECISION_GO",
    "VETO_ROLL_DAY":                          "BOT3_VETO_ROLL_DAY",
    "VETO_NEWS_IMMINENT":                     "BOT3_VETO_NEWS",
    "VETO_NEWS_JUST_HIT":                     "BOT3_VETO_NEWS",
    "VETO_VOLUME_MORT":                       "BOT3_VETO_VOL_DEAD",
    "VETO_MQ_STALE":                          "BOT3_VETO_MQ_STALE",
    "SKIP_DIST_ZERO":                         "BOT3_DECISION_SKIP",
    "SKIP_BULL_STRONG":                       "BOT3_DECISION_SKIP",
    "SKIP_VA_EXPANDING":                      "BOT3_DECISION_SKIP",
    "SKIP_BEAR_STRONG":                       "BOT3_DECISION_SKIP",
    "SKIP_SELLERS_CRUSHING_NO_BREAKOUT_MODE": "BOT3_DECISION_SKIP",
    "SKIP_BUYERS_CRUSHING_NO_BREAKOUT_MODE":  "BOT3_DECISION_SKIP",
    "SKIP_REJECTIONS_DISABLED":               "BOT3_DECISION_SKIP",
    "SKIP_BREAKOUTS_DISABLED":                "BOT3_DECISION_SKIP",
    "SKIP_NEUTRAL_NO_CONVERGENCE":            "BOT3_DECISION_SKIP",
    "SKIP_TREND_DAY_COUNTER_OR_NO_VOL_OR_NO_BIG": "BOT3_DECISION_SKIP",
    "SKIP_RANGE_INSTITUTIONAL_DRIVE":         "BOT3_DECISION_SKIP",
    # TIER S (Jackson 03/05)
    "SKIP_NEUTRAL_BAR_NO_TRADE":              "BOT3_DECISION_SKIP",
    "SKIP_NEUTRAL_SPIKE_RECENT_POLLUTED":     "BOT3_DECISION_SKIP",
}


def reason_to_log_code(reason: str) -> str:
    """Map une reason decision_engine vers un code log_catalog stable.

    Les reasons "TIER3_MISS_*" et "SKIP_SIDE_INVALID_*" sont dynamiques (suffixe variable),
    donc on les detecte par prefixe.
    """
    if reason in _REASON_TO_LOG_CODE:
        return _REASON_TO_LOG_CODE[reason]
    if reason.startswith("TIER3_MISS_"):
        return "BOT3_TIER3_MISS"
    if reason.startswith("BLOCK_COMBO_"):
        # Phase 1.7b (17/05) : BLOCK combos session × level (DSR Lopez audit)
        return "BOT3_BLOCK_COMBO"
    # GAP 3 audit log tracabilite 17/05 : route PENDING_BREAKOUT_REGISTERED
    # vers code dedie BOT3_BREAKOUT_REGISTER (PAS BOT3_BREAKOUT_PENDING qui est
    # deja utilise par _bot3_emit_breakout_events avec placeholders differents).
    # Sinon collision template {side} vs {side_break}/{delta}/{finish} -> KeyError.
    if reason == "PENDING_BREAKOUT_REGISTERED":
        return "BOT3_BREAKOUT_REGISTER"
    # GAP 4 audit log tracabilite 17/05 : SKIP_SIDE_INVALID_* = bug config
    # niveau (level["side"] non in LONG/SHORT/REJECTION/NEUTRAL). Route vers
    # code MAJEUR dedie au lieu de BOT3_DECISION_SKIP generique INFO.
    if reason.startswith("SKIP_SIDE_INVALID_"):
        return "BOT3_LEVEL_DEF_INVALID"
    if reason.startswith("SKIP_"):
        return "BOT3_DECISION_SKIP"
    if reason.startswith("VETO_"):
        return "BOT3_DECISION_SKIP"  # generique VETO inconnu
    # Fallback safe : SKIP generique. resolve() ne levera pas KeyError.
    return "BOT3_DECISION_SKIP"


@dataclass
class Bot3Signal:
    """Signal Bot 3 produit par evaluate(). Consomme par paper_trader."""
    signal_id: str
    symbol: str
    ts_event: str            # ISO8601 UTC
    bar_ts: str              # bar timestamp source
    level_name: str
    level_tier: int
    level_baseline_rej: Optional[float]
    level_baseline_pf: Optional[float]
    side: str                # "LONG" / "SHORT"
    action: str              # "REJECTION" / "BREAKOUT"
    confidence: int          # 0-100
    sl_ticks: int
    atr_multiplier: float
    n_contracts: int
    price_entry_ref: float   # close de la barre de touch (entry @ T+1 close)
    dist_pct_at_touch: float
    ctx: dict                # 12 dimensions complete pour audit
    bar_at_touch: dict       # bar entiere pour snapshot ulterieur
    # 🆕 09/05 (Bot 3 v2) : tag bucket pour routage SLTPEngine + bypass filter
    bucket: str = "HERITAGE"  # "HERITAGE" / "SIDAK" / "COMBO_BOOSTED"
    # 17/05 P3 audit dashboard : propager params decision (boost_applied,
    # swing_color_boost_applied, swing_color_consensus, atr_current) pour
    # afficher SETUP COMPLET dans onglet "Trade en cours" (Jackson Q3 17/05).
    # Cohesion avec Bot3DecisionLog.params (deja existant GAP 1).
    params: dict = field(default_factory=dict)


@dataclass
class Bot3DecisionLog:
    """Log d'une decision (GO ou SKIP) pour audit Phase 1 observe-only.

    FIX GAP 1 (audit log tracabilite 17/05) : ajout champ `params` pour
    transporter les metadata d'audit jusqu'au paper_trader (boost_applied,
    swing_color_boost_applied, BLOCK_COMBO metadata, funnel NEUTRAL).
    Sans ce champ, paper_trader.py:2746,2779 leveraient AttributeError au
    1er BOOST ou BLOCK_COMBO en production -> service crash + Phase 1.7b/d
    morte des activation.
    """
    signal_id: str
    symbol: str
    ts_event: str
    bar_ts: str
    level_name: str
    level_tier: int
    decision: str            # "GO", "SKIP_*", "VETO_*"
    reason: str              # detail
    ctx: dict
    params: dict = field(default_factory=dict)  # boost_applied, funnel, etc.


class Bot3Engine:
    """Orchestre le cycle de vie d'une decision Bot 3.

    Anti double-trigger :
      - last_bar_ts par symbole : skip si bar deja evaluee
      - last_contact_bar_idx par (symbole, niveau) : skip si < cooldown bars
    """

    def __init__(self) -> None:
        self.last_bar_ts: dict[str, Optional[str]] = {"NQ": None, "ES": None}
        # (symbol, level_name) -> bar_idx du dernier contact evalue
        self.last_contact_idx: dict[tuple[str, str], int] = {}
        # bar counter par symbole (incremente a chaque bar evaluee)
        self._bar_counter: dict[str, int] = {"NQ": 0, "ES": 0}
        # State machine BREAKOUT_RETEST (Steidlmayer/Dalton acceptance + retest)
        self.breakout_retest = BreakoutRetestStateMachine()
        # FIX #3 : events PENDING/ACCEPTED/CRUSH_ABSORBED/RETEST_TIMEOUT a emettre
        # Buffer rempli par update_on_bar, consomme par paper_trader pour _emit
        self._pending_breakout_events: list = []

        # ─── Phase 4d (2026-05-18) : V2 narrative integration ──────
        # Lazy init si BOT3_USE_NARRATIVE_DIRECTION=True ET modules dispo.
        # V1 (default) : nsm=None, resolver=None -> flow inchange.
        # V2 actif : NSM + DirectionResolver instances persistantes (state cross-bars).
        # Limites Phase 4d MVP :
        # - story_trackers minimal (bars_since_BOS=999 default) -> T17 RANGE_RESPECTED
        #   ne fire pas en pratique car requires evolution state machine. S07/S08
        #   RANGE_* scenarios attendent Phase 4e ulterieure pour story_trackers reels.
        # - swing_state = None (Wyckoff Spring/Upthrust T22-T27 attendent Phase 4e).
        # - Cible Phase 4d MVP : S01/S02/S03/S04 OD+TREND + S09/S10 EXHAUSTION.
        self._nsm: Optional["NarrativeStateMachine"] = None
        self._resolver: Optional["DirectionResolver"] = None
        if BOT3_USE_NARRATIVE_DIRECTION and _V2_NARRATIVE_AVAILABLE:
            self._nsm = NarrativeStateMachine()
            self._resolver = DirectionResolver()
        # P0.2 fix (code-reviewer NOGO 18/05) : circuit breaker NSM transition.
        # Si NSM leve a chaque bar (bug deserialisation, atr=0, etc.), le bot
        # retomberait V1 silencieusement (fail-silent pattern interdit cf
        # VALIDATION_MISS 11/05 Phase 1.7d boost morte production).
        # Apres N=10 exceptions consecutives par symbol -> disable V2 + emit
        # CRITIQUE BOT3_NSM_CIRCUIT_BREAKER_TRIPPED.
        # Heartbeat BOT3_NSM_TRANSITION_OK toutes les 100 bars pour confirmer
        # que NSM transit reellement (audit J+1 grep logs).
        self._nsm_consec_exceptions: dict[str, int] = {"NQ": 0, "ES": 0, "MGC": 0}
        self._nsm_circuit_breaker_tripped: dict[str, bool] = {"NQ": False, "ES": False, "MGC": False}
        self._nsm_transition_ok_count: dict[str, int] = {"NQ": 0, "ES": 0, "MGC": 0}

    def evaluate(
        self,
        bar: dict,
        symbol: str,
    ) -> tuple[Optional[Bot3Signal], list[Bot3DecisionLog]]:
        """Evalue les niveaux actifs sur une bar.

        Returns:
            (signal_or_none, decisions_log_list)
            - signal_or_none : Bot3Signal si GO trade, None sinon
            - decisions_log : liste de Bot3DecisionLog pour TOUS les niveaux
              evalues (GO + SKIP) — pour audit Phase 1
        """
        decisions: list[Bot3DecisionLog] = []

        # ─── Anti double-trigger bar identique ───
        bar_ts = bar.get("ts_event") if hasattr(bar, "get") else None
        bar_ts_str = str(bar_ts) if bar_ts is not None else "?"
        if self.last_bar_ts.get(symbol) == bar_ts_str:
            return None, decisions
        self.last_bar_ts[symbol] = bar_ts_str
        self._bar_counter[symbol] += 1
        cur_bar_idx = self._bar_counter[symbol]

        # ─── Trading window UTC ───
        if not self._in_trading_window(bar_ts_str):
            return None, decisions

        # ─── ECO CALENDAR BLOCK (Jackson 03/05 soir) ───
        # FIX #2 (review code-reviewer + market-analyst round 5) : fail-CLOSED.
        # Anti-pattern silent fallback interdit (regle V2 + .claude/rules).
        # Si lib casse → block conservatif + log CRITIQUE.
        from datetime import datetime as _dt, timezone as _tz
        try:
            now_utc = _dt.now(_tz.utc)
            blocked, eco_reason, eco_until = _eco_is_blocked(now_utc)
            if blocked:
                decisions.append(Bot3DecisionLog(
                    signal_id=uuid.uuid4().hex[:12],
                    symbol=symbol, ts_event=_now_iso(), bar_ts=bar_ts_str,
                    level_name="_ECO_GATE_", level_tier=0,
                    decision="VETO_ECO_BLOCK",
                    reason=f"ECO_{eco_reason}_until_{eco_until}",
                    ctx={},
                ))
                return None, decisions
        except Exception as e:
            # FAIL-CLOSED : block conservatif + log CRITIQUE (pas pass)
            try:
                from logging_v2 import get_logger as _get
                _get("bot3_mp_engine").emit("BOT3_ECO_EXCEPTION",
                                             err=type(e).__name__,
                                             msg=str(e)[:200])
            except Exception:
                pass
            decisions.append(Bot3DecisionLog(
                signal_id=uuid.uuid4().hex[:12],
                symbol=symbol, ts_event=_now_iso(), bar_ts=bar_ts_str,
                level_name="_ECO_GATE_", level_tier=0,
                decision="VETO_ECO_EXCEPTION",
                reason=f"eco_calendar_failed_fail_closed: {type(e).__name__}",
                ctx={},
            ))
            return None, decisions

        # ─── Niveaux actifs pour ce symbole ───
        # Jackson 03/05 : 8 niveaux ex-bannis reintegres en mode NEUTRAL.
        # En Phase 1 OBSERVE_ONLY, on les active pour log baseline_rej live
        # (decision_engine traite NEUTRAL via 7 scenarios, pas de trade).
        # En Phase 2+, BOT3_ENABLE_TIER2_NEUTRAL controle si on les trade.
        enable_neutral = BOT3_ENABLE_TIER2_NEUTRAL or BOT3_OBSERVE_ONLY
        active_levels = get_active_levels(
            enable_tier2=BOT3_ENABLE_TIER2,
            enable_tier3=BOT3_ENABLE_TIER3,
            symbol=symbol,
            enable_tier2_neutral=enable_neutral,
        )
        if not active_levels:
            return None, decisions

        # ─── Context une seule fois par bar ───
        ctx = analyze_context(bar)

        # ─── BREAKOUT_RETEST state machine update sur cette bar ───
        # FIX #5 (review code-reviewer 03/05) : close=0 / bar invalide → fail-loud skip
        try:
            close_now = float(bar.get("close", 0.0)) if hasattr(bar, "get") else 0.0
            high_now = float(bar.get("high", close_now)) if hasattr(bar, "get") else close_now
            low_now = float(bar.get("low", close_now)) if hasattr(bar, "get") else close_now
        except (TypeError, ValueError):
            close_now = 0.0
            high_now = 0.0
            low_now = 0.0
        if close_now <= 0:
            # Bar invalide : skip toute la logique pour eviter level_price absurde
            return None, decisions
        # ATR pour acceptance hybride (TPO printed wick)
        atr_now = bar.get("atr") if hasattr(bar, "get") else None
        try:
            atr_now = float(atr_now) if atr_now is not None else 0.0
        except (TypeError, ValueError):
            atr_now = 0.0

        retest_signal = self.breakout_retest.update_on_bar(
            symbol=symbol,
            bar=bar,
            bar_idx=cur_bar_idx,
            bar_ts=bar_ts_str,
            close=close_now,
            high=high_now,
            low=low_now,
            atr=atr_now,
        )

        # FIX #3 : emettre les events generes par la state machine
        for evt in self.breakout_retest.consume_events():
            self._pending_breakout_events.append(evt)

        # ─── Phase 4d (2026-05-18) : V2 NSM transition + pending lifecycle ──
        # Si V2 actif ET circuit breaker pas tripped, faire 1 transition NSM par
        # bar (avant loop niveaux) et advance les pending_entries existantes pour
        # confirmation pattern.
        # P0.2 fix : circuit breaker apres 10 exceptions consecutives par symbol.
        # Cf docstring Bot3Engine.__init__ pour limites Phase 4d MVP.
        nsm_snapshot = None
        v2_confirmed_trades: list[tuple[str, object]] = []
        # P1 re-review fix : breaker NSM transition vs advance pending split
        # (eviter faux-positif breaker NSM si bug est dans resolver advance).
        # Single-writer assumption : paper_trader sequentiel (pas multi-thread
        # sur Bot3Engine.evaluate()). Si demain multi-thread, ajouter lock.
        if (self._nsm is not None and self._resolver is not None
                and not self._nsm_circuit_breaker_tripped.get(symbol, False)):
            # Stage 1 : NSM transition (couvert par circuit breaker dedie)
            try:
                nsm_bar, nsm_ctx_v2 = self._build_v2_inputs(bar, ctx, symbol, bar_ts_str)
                # P1.10 fix : bars_since_last_BOS=30 (au lieu 999) -> T17 RANGE_RESPECTED
                # ne fire JAMAIS en MVP car requires >90. Conservatif Phase 4d :
                # S07/S08 RANGE_* desactives jusqu'a story_trackers reels Phase 4e.
                # Anti faux-positifs RANGE en trend day (cf market-analyst review).
                # TODO Phase 4e : brancher story_trackers reels (bars_since_BOS
                # calcule depuis NarrativeStoryTrackers) pour reactiver S07/S08.
                nsm_snapshot = self._nsm.transition(
                    symbol=symbol,
                    bar=nsm_bar,
                    ctx=nsm_ctx_v2,
                    regime=None,
                    story_trackers={"bars_since_last_BOS": 30},
                    swing_state=None,
                )
                # P0.2 fix : transition OK -> reset compteur exceptions consec
                self._nsm_consec_exceptions[symbol] = 0
                # P2 re-review fix : heartbeat 1/500 (au lieu 1/100) pour reduire
                # noise dans logs. Sur RTH 390 bars/sym/jour, ~1 heartbeat / 1.3j.
                self._nsm_transition_ok_count[symbol] = (
                    self._nsm_transition_ok_count.get(symbol, 0) + 1
                )
                if self._nsm_transition_ok_count[symbol] % 500 == 0:
                    try:
                        from logging_v2 import get_logger as _get
                        _get("bot3_mp_engine").emit(
                            "BOT3_NSM_TRANSITION_OK",
                            sym=symbol,
                            count_since_boot=self._nsm_transition_ok_count[symbol],
                        )
                    except Exception:
                        pass
            except Exception as e:
                # P0.2 fix : increment compteur exceptions consec + check breaker
                # SCOPE : NSM transition seulement (advance pending separe ci-dessous).
                self._nsm_consec_exceptions[symbol] = (
                    self._nsm_consec_exceptions.get(symbol, 0) + 1
                )
                try:
                    from logging_v2 import get_logger as _get
                    _logger = _get("bot3_mp_engine")
                    _logger.emit(
                        "BOT3_NSM_TRANSITION_EXCEPTION",
                        err=type(e).__name__, msg=str(e)[:200],
                        sym=symbol,
                        consec=self._nsm_consec_exceptions[symbol],
                    )
                    # Si 10 exceptions consec -> trip circuit breaker
                    if self._nsm_consec_exceptions[symbol] >= 10:
                        self._nsm_circuit_breaker_tripped[symbol] = True
                        _logger.emit(
                            "BOT3_NSM_CIRCUIT_BREAKER_TRIPPED",
                            sym=symbol,
                            consec=self._nsm_consec_exceptions[symbol],
                            msg="NSM disabled for symbol after 10 consec exceptions. V1 fallback active. Investigation requise.",
                        )
                except Exception:
                    pass
                nsm_snapshot = None

            # Stage 2 : advance pending (try/except dedie, ne pollue PAS breaker NSM)
            # ATTENTION : advance TOUJOURS (meme en tracking_only) pour que
            # les logs BOT3_RESOLVER_CONFIRMATION_OK soient emit en shadow
            # mode J+14. La consommation finale en signal Bot3 est gardee
            # plus bas (cf "if not BOT3_NARRATIVE_TRACKING_ONLY").
            # NOTE : en mode shadow, les pendings sont consommees DEFINITIVEMENT
            # par _check_pending_confirmation (del internal). Si on flip
            # tracking_only=False plus tard, les pendings deja consommees
            # en shadow ne reviennent pas. Comportement attendu.
            if nsm_snapshot is not None:
                try:
                    v2_confirmed_trades = self._advance_v2_pending_confirmations(
                        symbol, nsm_snapshot, nsm_bar,
                    )
                    # Si tracking_only, logger "V2 aurait pris X" pour audit shadow
                    # mais ne pas consommer le signal (V1 reste decideur).
                    if BOT3_NARRATIVE_TRACKING_ONLY and v2_confirmed_trades:
                        for lvl_nm, _resolved in v2_confirmed_trades:
                            try:
                                from logging_v2 import get_logger as _get
                                _get("bot3_mp_engine").emit(
                                    "BOT3_V2_SHADOW_SIGNAL",
                                    sym=symbol, level=lvl_nm,
                                    scenario=_resolved.scenario_id,
                                    side=_resolved.side,
                                    confidence=int(_resolved.confidence * 100),
                                    narrative_state=nsm_snapshot.state.value,
                                )
                            except Exception:
                                pass
                        # Vider la liste pour ne pas declencher la branche trade
                        v2_confirmed_trades = []
                except Exception as e:
                    # P1 re-review : advance exception loggee separement,
                    # ne pollue PAS le breaker NSM transition.
                    try:
                        from logging_v2 import get_logger as _get
                        _get("bot3_mp_engine").emit(
                            "BOT3_V2_ADVANCE_EXCEPTION",
                            err=type(e).__name__, msg=str(e)[:200],
                            sym=symbol,
                        )
                    except Exception:
                        pass
                    v2_confirmed_trades = []

        # ─── Loop niveaux ───
        signal: Optional[Bot3Signal] = None
        # Si la state machine a genere un retest signal, on le convertit en Bot3Signal
        if retest_signal is not None and not BOT3_OBSERVE_ONLY:
            signal = self._build_signal_from_retest(retest_signal, ctx, bar)

        # Phase 4d : si une pending V2 confirme sur cette bar, on prend trade
        # (priorite haute, AVANT loop niveaux car la pending = scenario deja fire,
        # confirmation pattern valide = signal de meilleure qualite que touch)
        # P1.8 fix : try/except autour construction signal pour eviter pending zombie.
        if signal is None and v2_confirmed_trades and not BOT3_OBSERVE_ONLY:
            for lvl_name_conf, resolved in v2_confirmed_trades:
                lvl_def = active_levels.get(lvl_name_conf)
                if lvl_def is None:
                    continue
                try:
                    dist_col = lvl_def["dist_col"]
                    dist_signed_conf = bar.get(dist_col) if hasattr(bar, "get") else None
                    try:
                        dist_signed_conf = float(dist_signed_conf or 0.0)
                    except (TypeError, ValueError):
                        dist_signed_conf = 0.0
                    tier_conf = lvl_def.get("tier", 1)
                    sig_id_v2 = uuid.uuid4().hex[:12]
                    params_v2 = {
                        "side": resolved.side,
                        "action": "REJECTION",
                        "confidence": int(resolved.confidence * 100),
                        "sl_ticks": 40 if symbol == "ES" else 80,
                        "atr_multiplier": 1.5,
                        "scenario_id": resolved.scenario_id,
                        "narrative_state": (nsm_snapshot.state.value
                                             if nsm_snapshot else "?"),
                        "v2_source": "phase_4d_pending_confirmed",
                    }
                    decisions.append(Bot3DecisionLog(
                        signal_id=sig_id_v2,
                        symbol=symbol,
                        ts_event=_now_iso(),
                        bar_ts=bar_ts_str,
                        level_name=lvl_name_conf,
                        level_tier=tier_conf,
                        decision="GO",
                        reason="V2_PENDING_CONFIRMED",
                        ctx=ctx,
                        params=params_v2,
                    ))
                    signal = self._build_signal(
                        sig_id=sig_id_v2,
                        symbol=symbol,
                        bar_ts_str=bar_ts_str,
                        level_name=lvl_name_conf,
                        level_def=lvl_def,
                        params=params_v2,
                        ctx=ctx,
                        bar=bar,
                        dist_signed=dist_signed_conf,
                    )
                    # P1.7 fix : marquer le bucket NARRATIVE pour distinguer V2 vs V1
                    if signal is not None:
                        signal.bucket = "NARRATIVE"
                    break  # 1 trade par bar
                except Exception as e:
                    # P1.8 fix : log construction failure + continue (ne pas crash bot)
                    try:
                        from logging_v2 import get_logger as _get
                        _get("bot3_mp_engine").emit(
                            "BOT3_V2_TRADE_CONSTRUCTION_FAILED",
                            sym=symbol, level=lvl_name_conf,
                            scenario=resolved.scenario_id if resolved else "?",
                            err=type(e).__name__,
                        )
                    except Exception:
                        pass
                    continue  # try next confirmed trade

        # ─── 🆕 PRIORITY 1 (Bot 3 v2 09/05) : COMBOS BOOSTED ───
        # Combos haute conviction validés Bonferroni (audit 09/05). Scan AVANT
        # les niveaux normaux pour capturer la "haute conviction".
        # bucket="COMBO_BOOSTED" → bypass filter regime + SLTPEngine wall-aware.
        # Si combo fire → signal pris, on continue scan niveaux pour audit logs only.
        if signal is None:
            combo_signal = self._scan_combos_boosted(
                bar=bar,
                symbol=symbol,
                ctx=ctx,
                bar_ts_str=bar_ts_str,
                cur_bar_idx=cur_bar_idx,
                decisions=decisions,
            )
            if combo_signal is not None:
                signal = combo_signal

        for level_name, level_def in active_levels.items():
            # Distance niveau (signe inclus)
            dist_col = level_def["dist_col"]
            dist_signed = bar.get(dist_col) if hasattr(bar, "get") else None
            if dist_signed is None:
                continue
            try:
                dist_signed = float(dist_signed)
            except (TypeError, ValueError):
                continue
            if dist_signed != dist_signed:  # NaN
                continue

            # Touch ?
            proximity = level_def["proximity_pct"]
            if abs(dist_signed) > proximity:
                continue

            # Cooldown : pas de retrigger meme niveau dans LEVEL_COOLDOWN_BARS bars
            cooldown_key = (symbol, level_name)
            last_idx = self.last_contact_idx.get(cooldown_key, -999)
            if cur_bar_idx - last_idx < LEVEL_COOLDOWN_BARS:
                continue
            self.last_contact_idx[cooldown_key] = cur_bar_idx

            tier = level_def.get("tier", 1)

            # Phase 4d (2026-05-18) : si V2 actif ET tracking_only=False, route
            # decision via V2 narrative. Sinon V1 evaluate_decision().
            # tracking_only=True permet d'avoir nsm/resolver instancies (logs)
            # SANS consommer les trades V2 (= shadow mode integre).
            if (self._nsm is not None and self._resolver is not None
                    and nsm_snapshot is not None
                    and not BOT3_NARRATIVE_TRACKING_ONLY):
                trade, reason, params = self._evaluate_v2_level(
                    level_name=level_name,
                    level_def=level_def,
                    ctx=ctx,
                    symbol=symbol,
                    dist_signed=dist_signed,
                    nsm_snapshot=nsm_snapshot,
                    bar=bar,
                )
            else:
                # V1 legacy (default) ou V2 tracking-only
                trade, reason, params = evaluate_decision(
                    level_name=level_name,
                    level_def=level_def,
                    ctx=ctx,
                    symbol=symbol,
                    dist_signed=dist_signed,
                )

            # PENDING_BREAKOUT_REGISTERED : ne pas trader, register dans state machine
            if not trade and reason == "PENDING_BREAKOUT_REGISTERED":
                # FIX #1 (CRITIQUE code-reviewer 03/05) : calculer level_price ICI
                # avec convention V4 dist_pct en % (formule (level - close)/close * 100)
                # → level = close * (1 + dist_signed / 100)
                # Plus de reconstruction approximative dans la state machine.
                level_price_at_touch = close_now * (1.0 + dist_signed / 100.0)
                self.breakout_retest.register_pending_breakout(
                    symbol=symbol,
                    level_name=level_name,
                    level_def=level_def,
                    side_break=params.get("side_break", "SHORT"),
                    touch_bar_idx=cur_bar_idx,
                    touch_bar_ts=bar_ts_str,
                    touch_price=close_now,
                    touch_dist_signed=dist_signed,
                    level_price=level_price_at_touch,
                    ctx_at_touch=ctx,
                )
                # FIX #3 : recuperer event PENDING genere par register
                for evt in self.breakout_retest.consume_events():
                    self._pending_breakout_events.append(evt)

            sig_id = uuid.uuid4().hex[:12]
            decisions.append(Bot3DecisionLog(
                signal_id=sig_id,
                symbol=symbol,
                ts_event=_now_iso(),
                bar_ts=bar_ts_str,
                level_name=level_name,
                level_tier=tier,
                decision="GO" if trade else reason,
                reason=reason,
                ctx=ctx,
                params=params,   # FIX GAP 1 17/05 : transporter boost_applied / BLOCK / funnel
            ))

            if trade and signal is None:
                # Premier GO de la bar = signal retenu
                # (les suivants sont logges mais pas tradés sur cette bar)
                signal = self._build_signal(
                    sig_id=sig_id,
                    symbol=symbol,
                    bar_ts_str=bar_ts_str,
                    level_name=level_name,
                    level_def=level_def,
                    params=params,
                    ctx=ctx,
                    bar=bar,
                    dist_signed=dist_signed,
                )
                # P1.7 fix : si reason=V2_TRADE -> marquer bucket NARRATIVE
                if signal is not None and reason == "V2_TRADE":
                    signal.bucket = "NARRATIVE"

        # En mode observe-only : on n'execute pas le trade mais on log tout
        if BOT3_OBSERVE_ONLY:
            return None, decisions

        return signal, decisions

    # ════════════════════════════════════════════════════════════════════════
    # Phase 4d (2026-05-18) — V2 narrative helpers
    # ════════════════════════════════════════════════════════════════════════

    def _build_v2_inputs(
        self,
        bar: dict,
        ctx: dict,
        symbol: str,
        bar_ts_str: str,
    ) -> tuple[dict, dict]:
        """Map (bar V4 enriched, ctx decision_engine) -> (nsm_bar, nsm_ctx).

        Phase 4d MVP : projection minimale des champs requis par NSM.transition().
        Fallback chain pour atr_intraday : atr_intraday -> atr_14m -> atr_14m_pct*close.
        """
        def _f(k):
            v = bar.get(k) if hasattr(bar, "get") else None
            try:
                f = float(v) if v is not None else None
                if f != f:  # NaN
                    return None
                return f
            except (TypeError, ValueError):
                return None

        close_v = _f("close")
        # atr_intraday calcul depuis live_enricher fields disponibles
        atr_intraday = _f("atr_intraday") or _f("atr_14m")
        if atr_intraday is None and close_v is not None:
            atr_pct = _f("atr_14m_pct")
            if atr_pct is not None:
                atr_intraday = atr_pct * close_v / 100.0

        nsm_bar = {
            "ts_event_iso": bar_ts_str,
            "ts_event": bar_ts_str,
            "close": close_v,
            "open": _f("open"),
            "high": _f("high"),
            "low": _f("low"),
            "atr": _f("atr"),
            "atr_intraday": atr_intraday,
            "vol_zscore_20": _f("vol_zscore_20"),
            "bar_idx_session": self._bar_counter.get(symbol, 0),
            "volume": _f("volume") or 1000,
            "session_date_trading": str(bar.get("session_date_trading", "")),
            "symbol": symbol,
            "ib_complete": int(bar.get("ib_complete") or 0),
            "ib_broken_up": int(bar.get("ib_broken_up") or 0),
            "ib_broken_dn": int(bar.get("ib_broken_dn") or 0),
        }

        # NSM ctx : session string + open_type + open_cash + ib_* + prev_va*
        session_id = bar.get("session_id")
        sess_map = {0: "ASIA", 1: "LONDON", 2: "NY", 3: "US_AH"}
        try:
            session = sess_map.get(int(session_id) if session_id is not None else -1, "OTHER")
        except (TypeError, ValueError):
            session = "OTHER"
        nsm_ctx = {
            "session": session,
            "open_type": int(bar.get("open_type") or 0),
            "open_cash": _f("open_cash") or close_v,
            "asia_close": _f("asia_close"),
            "asia_open": _f("asia_open"),
            "ib_complete": int(bar.get("ib_complete") or 0),
            "inside_value_area": int(bar.get("inside_value_area") or 0),
            "ib_range": _f("ib_range"),
            "ib_broken_up": int(bar.get("ib_broken_up") or 0),
            "ib_broken_dn": int(bar.get("ib_broken_dn") or 0),
            "prev_vah": _f("prev_vah"),
            "prev_val": _f("prev_val"),
            "tick_size": 0.25,
        }
        return nsm_bar, nsm_ctx

    def _advance_v2_pending_confirmations(
        self,
        symbol: str,
        snap,
        nsm_bar: dict,
    ) -> list[tuple[str, "object"]]:
        """Poll les pending_entries pour ce symbol -> advance confirmation pattern.

        Le DirectionResolver auto-route vers _check_pending_confirmation si une
        pending existe pour (symbol, level_name). Cet helper itere les pendings
        actives et appelle resolve() pour les faire avancer (timeout ou validation).
        Sans cet appel, les pendings restent infiniment en attente.

        FIX P0.1 + P0.3 (code-reviewer NOGO 18/05) : prend `self._resolver._lock`
        externalement pour :
        - Iter `_pending_entries.keys()` thread-safe (P0.1)
        - Copy snapshot des pendings AVANT release du lock (P0.1)
        - Cleanup pop sur exception persistante sous lock (P0.3)
        Le `RLock` permet reprise interne via `resolver.resolve()` (qui prend le
        meme lock RLock -> ok reentrant).

        Returns:
            list de (level_name, resolved_direction) pour les pendings qui ont
            valide la confirmation cette bar (resolved.side in LONG/SHORT).
            Caller doit construire Bot3Signal pour ces trades en utilisant
            les level_defs correspondants.
            Les timeouts/invalidations ne sont pas retournes (juste cleanup).
        """
        validated: list[tuple[str, object]] = []
        if self._resolver is None:
            return validated
        # P0.1 fix : acquire resolver lock pour iter+copy snapshot atomique
        with self._resolver._lock:
            pending_snapshot = [
                (k, self._resolver._pending_entries.get(k))
                for k in list(self._resolver._pending_entries.keys())
                if k[0] == symbol
            ]
        # Iter HORS lock pour appeler resolve() (qui reprend le lock RLock interne)
        for (sym_k, lvl_name_k), pending in pending_snapshot:
            if pending is None:
                continue
            # Resolver auto-routes vers _check_pending_confirmation
            try:
                resolved = self._resolver.resolve(
                    snapshot=snap,
                    level_name=lvl_name_k,
                    level_nature="support",  # ignore car pending existant
                    level_price=pending.target_price,
                    bar=nsm_bar,
                )
                if resolved is not None and resolved.side in ("LONG", "SHORT"):
                    validated.append((lvl_name_k, resolved))
            except Exception:
                # P0.3 fix : cleanup orphan pending UNDER LOCK
                with self._resolver._lock:
                    self._resolver._pending_entries.pop((sym_k, lvl_name_k), None)
        return validated

    def _evaluate_v2_level(
        self,
        level_name: str,
        level_def: dict,
        ctx: dict,
        symbol: str,
        dist_signed: float,
        nsm_snapshot,
        bar: dict,
    ) -> tuple[bool, str, dict]:
        """V2 narrative wrapper - retourne format compatible evaluate_decision V1.

        Returns:
            (trade : bool, reason : str, params : dict)
            params si trade=True : {side, action, confidence, sl_ticks,
                                    atr_multiplier, scenario_id, narrative_state}
        """
        # 1. Determine level_nature depuis level_def["side"]
        level_side = level_def.get("side", "REJECTION")
        if level_side == "LONG":
            nature = "support"
        elif level_side == "SHORT":
            nature = "resistance"
        elif level_side == "REJECTION":
            nature = "support" if dist_signed < 0 else "resistance"
        elif level_side == "NEUTRAL":
            # V2 ne gere pas NEUTRAL en MVP -> fallback V1.
            # P1.5 fix : emit log audit pour quantifier J+1.
            try:
                from logging_v2 import get_logger as _get
                _get("bot3_mp_engine").emit(
                    "BOT3_V2_FALLBACK_V1_NEUTRAL",
                    sym=symbol,
                    level=level_name,
                )
            except Exception:
                pass
            return evaluate_decision(level_name, level_def, ctx, symbol, dist_signed)
        else:
            return False, f"V2_SKIP_SIDE_INVALID_{level_side}", {}

        # 2. Compute level_price (convention V4 dist_signed = (level - close) / close * 100)
        close_v = float(bar.get("close", 0)) if hasattr(bar, "get") else 0.0
        if close_v <= 0:
            return False, "V2_SKIP_CLOSE_INVALID", {}
        level_price = close_v * (1.0 + dist_signed / 100.0) if dist_signed else close_v

        # 3. Build nsm_bar pour resolver (re-utiliser ou minimal)
        nsm_bar_min = {
            "close": close_v,
            "high": float(bar.get("high") or close_v),
            "low": float(bar.get("low") or close_v),
            "vol_zscore_20": float(bar.get("vol_zscore_20") or 0.0),
            "session_date_trading": str(bar.get("session_date_trading", "")),
            "atr_intraday": float(bar.get("atr_14m")
                                   or (float(bar.get("atr_14m_pct") or 0.024) * close_v / 100.0)),
        }

        # 4. Resolve via DirectionResolver
        try:
            resolved = self._resolver.resolve(
                snapshot=nsm_snapshot,
                level_name=level_name,
                level_nature=nature,
                level_price=level_price,
                bar=nsm_bar_min,
            )
        except Exception as e:
            return False, f"V2_RESOLVE_EXCEPTION_{type(e).__name__}", {}

        if resolved is None:
            return False, "V2_NO_RESOLVED", {}

        # 5. Si resolved.side == NO_TRADE ou pending registered, pas de trade
        if resolved.side in ("NO_TRADE", "PENDING", None):
            return False, f"V2_{resolved.side or 'NO_RESOLVE'}_{resolved.scenario_id}", {
                "narrative_state": nsm_snapshot.state.value if nsm_snapshot else "?",
                "scenario_id": resolved.scenario_id,
                "v2_confidence": resolved.confidence,
            }

        # 6. TRADE confirmé : map vers format V1 params
        side = resolved.side
        if side not in ("LONG", "SHORT"):
            return False, f"V2_UNEXPECTED_SIDE_{side}", {}

        # SL/atr_multiplier : default Phase 4d MVP (a raffiner Phase 4e via SLTPEngine)
        sl_ticks_default = 40 if symbol == "ES" else 80
        params = {
            "side": side,
            "action": "REJECTION",  # V2 default action
            "confidence": int(resolved.confidence * 100),
            "sl_ticks": sl_ticks_default,
            "atr_multiplier": 1.5,
            "scenario_id": resolved.scenario_id,
            "narrative_state": nsm_snapshot.state.value if nsm_snapshot else "?",
            "v2_source": "phase_4d_mvp",
        }
        return True, "V2_TRADE", params

    def _build_signal_from_retest(
        self,
        retest_signal: BreakoutRetestSignal,
        ctx: dict,
        bar: dict,
    ) -> Bot3Signal:
        """Convertit un BreakoutRetestSignal en Bot3Signal pour execution."""
        symbol = retest_signal.symbol
        level_name = retest_signal.level_name
        try:
            from .bot3_config import (
                ATR_BASELINE,
                ATR_MULTIPLIER_CLAMP,
                BREAKOUT_CONFIDENCE_BASELINE,
                BREAKOUT_RETEST_DEADLINE_BARS,
                BREAKOUT_RETEST_DELTA_BASE,
                GUARD_RAILS_BOT3 as GR,
            )
        except ImportError:
            from bot3_config import (
                ATR_BASELINE,
                ATR_MULTIPLIER_CLAMP,
                BREAKOUT_CONFIDENCE_BASELINE,
                BREAKOUT_RETEST_DEADLINE_BARS,
                BREAKOUT_RETEST_DELTA_BASE,
                GUARD_RAILS_BOT3 as GR,
            )
        atr_baseline = ATR_BASELINE.get(symbol, 0.030)
        atr_current = ctx.get("atr_14m_pct", 0.0) or atr_baseline
        if atr_current <= 0:
            atr_current = atr_baseline
        atr_ratio = atr_current / atr_baseline
        atr_multiplier = max(ATR_MULTIPLIER_CLAMP[0], min(ATR_MULTIPLIER_CLAMP[1], atr_ratio))
        base_sl = GR[symbol]["sl_ticks_base"]
        adjusted_sl = int(round(base_sl * atr_multiplier))
        n_contracts = GR[symbol]["n_contracts"]

        # FIX #7 (review code-reviewer + market-analyst 03/05) : confidence calculee
        # pour BREAKOUT_RETEST. Anciennement hardcode 70.
        confidence = _compute_breakout_retest_confidence(
            retest_signal=retest_signal,
            ctx=ctx,
            level_def_tier=1,  # filtre dans decision_engine
            baseline=BREAKOUT_CONFIDENCE_BASELINE,
            delta_base=BREAKOUT_RETEST_DELTA_BASE,
            deadline_bars=BREAKOUT_RETEST_DEADLINE_BARS,
        )

        # bar_at_touch : convertir la bar en dict pur
        if hasattr(bar, "to_dict"):
            bar_at_touch = bar.to_dict()
        elif isinstance(bar, dict):
            bar_at_touch = dict(bar)
        else:
            bar_at_touch = {}

        return Bot3Signal(
            signal_id=retest_signal.state_id,
            symbol=symbol,
            ts_event=_now_iso(),
            bar_ts=retest_signal.entry_bar_ts,
            level_name=level_name,
            level_tier=1,
            level_baseline_rej=get_level_baseline_rej(level_name, symbol),
            level_baseline_pf=get_level_baseline_pf(level_name, symbol),
            side=retest_signal.side,
            action="BREAKOUT_RETEST",
            confidence=confidence,
            sl_ticks=adjusted_sl,
            atr_multiplier=round(atr_multiplier, 3),
            n_contracts=n_contracts,
            price_entry_ref=retest_signal.entry_price,
            dist_pct_at_touch=retest_signal.retest_dist_signed,
            ctx=ctx,
            bar_at_touch=bar_at_touch,
            # 17/05 P3 audit dashboard : signal automatique retest n'a pas de
            # boost/swing_color (issu state machine, pas decision_engine).
            # Dict minimal pour cohesion API : bucket SIDAK si applicable.
            params={
                "action": "BREAKOUT_RETEST",
                "confidence": confidence,
                "atr_multiplier": round(atr_multiplier, 3),
            },
        )

    def _build_signal(
        self,
        sig_id: str,
        symbol: str,
        bar_ts_str: str,
        level_name: str,
        level_def: dict,
        params: dict,
        ctx: dict,
        bar: dict,
        dist_signed: float,
    ) -> Bot3Signal:
        n_contracts = GUARD_RAILS_BOT3[symbol]["n_contracts"]
        price_entry_ref = float(bar.get("close", 0.0)) if hasattr(bar, "get") else 0.0
        # bar_at_touch : convertir la bar (Series/dict) en dict pur
        if hasattr(bar, "to_dict"):
            bar_at_touch = bar.to_dict()
        elif isinstance(bar, dict):
            bar_at_touch = dict(bar)
        else:
            bar_at_touch = {}

        # 🆕 09/05 (Bot 3 v2) : tag bucket pour routage downstream
        # SIDAK_LEVELS validés Sidak strict cross-régime → bypass filter regime
        # + SLTPEngine wall-aware. HERITAGE = comportement actuel inchangé.
        bucket = "SIDAK" if is_sidak_level(level_name) else "HERITAGE"

        return Bot3Signal(
            signal_id=sig_id,
            symbol=symbol,
            ts_event=_now_iso(),
            bar_ts=bar_ts_str,
            level_name=level_name,
            level_tier=level_def["tier"],
            level_baseline_rej=get_level_baseline_rej(level_name, symbol),
            level_baseline_pf=get_level_baseline_pf(level_name, symbol),
            side=params["side"],
            action=params["action"],
            confidence=params["confidence"],
            sl_ticks=params["sl_ticks"],
            atr_multiplier=params["atr_multiplier"],
            n_contracts=n_contracts,
            price_entry_ref=price_entry_ref,
            dist_pct_at_touch=round(dist_signed, 6),
            ctx=ctx,
            bar_at_touch=bar_at_touch,
            bucket=bucket,
            # 17/05 P3 audit dashboard : propager params (boost_applied, swing_color_*).
            # Cle pour onglet "Trade en cours" SETUP COMPLET.
            params=params,
        )

    def _scan_combos_boosted(
        self,
        bar: dict,
        symbol: str,
        ctx: dict,
        bar_ts_str: str,
        cur_bar_idx: int,
        decisions: list,
    ) -> Optional[Bot3Signal]:
        """🆕 09/05 (Bot 3 v2) — Priority 1 scan combos boostés haute conviction.

        Combo = touche simultanée 2+ niveaux (cols) + filter contextuel optionnel.
        Si fire → signal Bot3Signal avec bucket="COMBO_BOOSTED".

        bucket="COMBO_BOOSTED" → routage downstream :
          - BYPASS filter regime_engine (cross-régime validé)
          - SLTPEngine wall-aware (mia_sltp.py)
          - Fallback standard si SLTPEngine reject

        Validation : audit `boost_marginal_combos.py` 09/05/2026 (Bonferroni-corrigé sur 4 tests).
        """
        combos = get_combos_boosted(symbol)
        if not combos:
            return None

        for combo_name, combo_def in combos.items():
            # Cooldown isolé par combo_name (cd_key unique vs SIDAK_*/TIER1*/TIER2*).
            # I2 fix code-reviewer 09/05 : empêche retrigger même combo dans
            # LEVEL_COOLDOWN_BARS, mais N'EMPÊCHE PAS qu'un Sidak simple
            # (cooldown séparé) trigge la bar suivante.
            cd_key = (symbol, combo_name)
            last_idx = self.last_contact_idx.get(cd_key, -999)
            if cur_bar_idx - last_idx < LEVEL_COOLDOWN_BARS:
                continue

            # ─── Check toutes les cols proche (touche simultanée) ───
            proximity = combo_def["proximity_pct"]
            all_touched = True
            for col in combo_def["cols"]:
                v = bar.get(col) if hasattr(bar, "get") else None
                if v is None:
                    all_touched = False
                    break
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    all_touched = False
                    break
                if v != v or abs(v) > proximity:  # NaN check + proximity
                    all_touched = False
                    break
            if not all_touched:
                continue

            # ─── Check filter contextuel (room_1dmax, aggr_buy, etc.) ───
            f_col = combo_def.get("filter_col")
            if f_col:
                f_op = combo_def["filter_op"]
                f_thr = combo_def["filter_thr"]
                v = bar.get(f_col) if hasattr(bar, "get") else None
                if v is None:
                    continue
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if v != v:  # NaN
                    continue
                if f_op == ">" and not (v > f_thr):
                    continue
                if f_op == "<" and not (v < f_thr):
                    continue
                if f_op == ">=" and not (v >= f_thr):
                    continue
                if f_op == "<=" and not (v <= f_thr):
                    continue

            # ─── COMBO FIRE ! ───
            self.last_contact_idx[cd_key] = cur_bar_idx
            sig_id = uuid.uuid4().hex[:12]
            side = combo_def["side"]

            n_contracts = GUARD_RAILS_BOT3[symbol]["n_contracts"]
            sl_ticks_base = GUARD_RAILS_BOT3[symbol].get(
                "sl_ticks_base", 32 if symbol == "ES" else 80
            )
            try:
                close_now = float(bar.get("close", 0.0))
            except (TypeError, ValueError):
                close_now = 0.0

            # 🆕 I1 fix code-reviewer 09/05 : adjusted_sl ATR-based (cohérent decision_engine)
            # Au lieu de sl_ticks_base fixe, applique multiplier ATR comme niveaux héritage.
            # Si SLTPEngine valide via wall-aware, sl_ticks sera override. Sinon fallback uses adjusted_sl.
            try:
                from .bot3_config import ATR_BASELINE, ATR_MULTIPLIER_CLAMP
            except ImportError:
                from bot3_config import ATR_BASELINE, ATR_MULTIPLIER_CLAMP
            atr_baseline = ATR_BASELINE.get(symbol, 0.030)
            atr_current = ctx.get("atr_14m_pct", 0.0) or atr_baseline
            if atr_current <= 0:
                atr_current = atr_baseline
            atr_ratio = atr_current / atr_baseline
            atr_multiplier = max(ATR_MULTIPLIER_CLAMP[0], min(ATR_MULTIPLIER_CLAMP[1], atr_ratio))
            adjusted_sl_combo = int(round(sl_ticks_base * atr_multiplier))

            # 🆕 B1 fix code-reviewer 09/05 : emit BOT3_COMBO_BOOSTED_FIRE pour audit J+1
            # Sinon code défini dans log_catalog mais jamais émis = VALIDATION_MISS.
            try:
                from logging_v2 import get_logger as _get
                _get("bot3_mp_engine").emit(
                    "BOT3_COMBO_BOOSTED_FIRE",
                    sym=symbol,
                    level=combo_name,
                    side=side,
                    cols_touched=",".join(combo_def["cols"]),
                    filter_passed=str(f_col or "none"),
                )
            except Exception:
                pass

            # Decision log GO
            decisions.append(Bot3DecisionLog(
                signal_id=sig_id,
                symbol=symbol,
                ts_event=_now_iso(),
                bar_ts=bar_ts_str,
                level_name=combo_name,
                level_tier=1,
                decision="GO",
                reason="COMBO_BOOSTED_FIRE",
                ctx={
                    **ctx,
                    "bucket": "COMBO_BOOSTED",
                    "combo_filter_col": f_col or "",
                    "combo_filter_thr": combo_def.get("filter_thr"),
                    "adjusted_sl_combo": adjusted_sl_combo,
                    "atr_multiplier": round(atr_multiplier, 3),
                },
            ))

            # En OBSERVE_ONLY : log mais pas de signal
            if BOT3_OBSERVE_ONLY:
                return None

            # bar_at_touch
            if hasattr(bar, "to_dict"):
                bar_at_touch = bar.to_dict()
            elif isinstance(bar, dict):
                bar_at_touch = dict(bar)
            else:
                bar_at_touch = {}

            # Signal COMBO_BOOSTED
            # NOTE : sl_ticks final sera RECALCULE par SLTPEngine dans
            # _bot3_execute_trade selon bucket=COMBO_BOOSTED. Si SLTPEngine
            # reject → fallback utilise sl_ticks ici (I1 fix : ATR-adjusted).
            return Bot3Signal(
                signal_id=sig_id,
                symbol=symbol,
                ts_event=_now_iso(),
                bar_ts=bar_ts_str,
                level_name=combo_name,
                level_tier=1,
                level_baseline_rej=None,
                level_baseline_pf=None,
                side=side,
                action="REJECTION",
                confidence=80,  # haute conviction par definition
                sl_ticks=adjusted_sl_combo,  # I1 fix : ATR-adjusted (pas sl_ticks_base fixe)
                atr_multiplier=atr_multiplier,
                n_contracts=n_contracts,
                price_entry_ref=close_now,
                dist_pct_at_touch=0.0,
                ctx=ctx,
                bar_at_touch=bar_at_touch,
                bucket="COMBO_BOOSTED",
            )

        return None

    @staticmethod
    def _in_trading_window(bar_ts_str: str) -> bool:
        """Verifie que bar_ts est dans la fenetre [TRADING_WINDOW_START_UTC, END_UTC[.

        FIX M-2 (review code-reviewer 03/05) : fail-CLOSED si parse echoue.
        Fail-OPEN avant = trade hors fenetre invisible (cf feedback_validation_miss_patterns.md).
        Maintenant : log + return False pour bloquer.
        """
        if not bar_ts_str or bar_ts_str == "?":
            # Pas de timestamp = on bloque + log unique (Phase 1 OBSERVE peu impacte)
            try:
                from logging_v2 import get_logger as _get
                _get("bot3_mp_engine").emit("BOT3_TRADING_WINDOW_PARSE_FAIL",
                                             ts="?", err="empty_or_marker")
            except Exception:
                pass
            return False  # fail-CLOSED
        try:
            ts = datetime.fromisoformat(bar_ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts = ts.astimezone(timezone.utc)
            h = ts.hour
            return TRADING_WINDOW_START_UTC <= h < TRADING_WINDOW_END_UTC
        except Exception as e:
            try:
                from logging_v2 import get_logger as _get
                _get("bot3_mp_engine").emit("BOT3_TRADING_WINDOW_PARSE_FAIL",
                                             ts=bar_ts_str, err=str(e))
            except Exception:
                pass
            return False  # fail-CLOSED


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_breakout_retest_confidence(
    retest_signal: BreakoutRetestSignal,
    ctx: dict,
    level_def_tier: int,
    baseline: int,
    delta_base: float,
    deadline_bars: int,
) -> int:
    """Confidence calculee pour BREAKOUT_RETEST signal (FIX #7).

    Anciennement hardcode 70. Maintenant fonction de :
      - acceptance_score (qualite de l'acceptance multi-barres)
      - n_bars_touch_to_retest (early retest = mieux)
      - delta magnitude au retest (vs delta_base)
      - bonus orderflow context (whales / sweep / SMT au retest)
      - penalty Tier 2

    Plage : [40, 95]. Documente comme tracking-only Phase 1 (cf
    feedback_lightgbm_no_composite_indicators.md). Audit J+30 + regression.
    """
    base = float(baseline)

    # Bonus acceptance qualite (score 2.5 = min, 5.0 = max si toutes closes confirms)
    acceptance_bonus = max(0.0, (retest_signal.acceptance_score - 2.5) * 4.0)
    base += min(10.0, acceptance_bonus)  # cap +10

    # Bonus retest timing (early = mieux)
    bars_to_retest = retest_signal.n_bars_touch_to_retest
    early_threshold = max(8, deadline_bars // 4)
    late_threshold = max(15, deadline_bars * 3 // 4)
    if bars_to_retest <= early_threshold:
        base += 8
    elif bars_to_retest >= late_threshold:
        base -= 5

    # Bonus rejection magnitude au retest
    delta_at_retest = abs(retest_signal.snapshot_retest.get("delta_bar", 0.0))
    if delta_base > 0:
        delta_ratio = delta_at_retest / delta_base
        # 1x delta_base = 0 boost, 2x = +5, 4x = +15
        base += min(15.0, max(0.0, 5.0 * (delta_ratio - 1.0)))

    # Bonus orderflow context (whales/sweep/SMT mesures au touch via ctx, pas retest)
    side = retest_signal.side
    if side == "LONG":
        whale_score = ctx.get("n_big_bid_t2", 0) + ctx.get("n_big_bid_t3", 0) * 3
    else:
        whale_score = ctx.get("n_big_ask_t2", 0) + ctx.get("n_big_ask_t3", 0) * 3
    base += min(8.0, whale_score * 3.0)

    if side == "LONG" and ctx.get("liq_sweep_low"):
        base += 5
    if side == "SHORT" and ctx.get("liq_sweep_high"):
        base += 5
    if ctx.get("smt_divergence"):
        base += 5

    # TIER S (Jackson 03/05) : delta_change forte = inflexion Douglas
    # "moment something breaks". Bonus si delta_change aligne avec direction.
    delta_change = ctx.get("delta_change", 0.0)
    if side == "LONG" and delta_change > 30.0:
        base += 5
    elif side == "SHORT" and delta_change < -30.0:
        base += 5

    # Penalty Tier 2 (vs Tier 1)
    if level_def_tier == 2:
        base -= 5

    # Clamp [40, 95]
    return int(round(max(40.0, min(95.0, base))))
