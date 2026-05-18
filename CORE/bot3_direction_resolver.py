"""CORE/bot3_direction_resolver.py - Direction Resolver Bot 3 v2 (Phase 3).

Module : 10+ scenarios table-driven `(narrative_state, level_nature) → side`.
Consume NSM snapshot + plot twists + scenario validity pour produire :
  ResolvedDirection(side, confidence, rationale, scenario_id, wait_for)

Architecture : Bot 3 v2 Narrative Layer (Phase 3 SHADOW MODE).
Pattern : ConfirmationGate integre via state machine `_pending_entries`
(cf master plan Phase 0.5 correction).

Anti-pattern : pas de hardcoded gate (table-driven uniquement, anti pattern 11 V1).
Anti-data-mining : scenarios pre-ecrits canon Dalton/Wyckoff/ICT (pas tunes data).

Data source : NSM snapshot (Phase 1) + PlotTwists (Phase 2) + LevelNature.

Created : 2026-05-18 by Jackson + Claude (Phase 3 J+2 base ZERO DETTE Phase 2)
Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md (sect 259-270)

Auteur : Bot 3 v2 Narrative Layer Phase 3
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 PM : creation Phase 3 J+2 - 10+ scenarios + ConfirmationGate integre
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from CORE.bot3_narrative_logging import emit
    from CORE.bot3_narrative_state_machine import NarrativeState, NarrativeStateSnapshot
except ModuleNotFoundError:
    from bot3_narrative_logging import emit  # type: ignore[no-redef]
    from bot3_narrative_state_machine import (  # type: ignore[no-redef]
        NarrativeState, NarrativeStateSnapshot,
    )

DIRECTION_RESOLVER_SCHEMA_VERSION: str = "3.0.0"

# Confiance levels (calibre Dalton/Wyckoff/ICT canon, aligned Phase 1 NSM)
CONF_HIGH: float = 0.85       # OD/OAOR (Dalton highest-confidence directional)
CONF_TREND_FOLLOW: float = 0.80  # TREND continuation post-OD/Wyckoff
CONF_REVERSAL: float = 0.65   # Wyckoff Spring/Upthrust pre-SOS (Pruden)
CONF_RANGE_PLAY: float = 0.60  # RANGE rebounds
CONF_LOW: float = 0.50        # OPEN_ROTATION/TEST baseline
CONF_NO_TRADE: float = 0.0

# Pattern validation thresholds (R6 fix : extracted magic numbers).
# Aligne avec NSM Phase 1 constantes (cf bot3_narrative_state_machine.py:101-143).
WICK_REJECTION_MIN_RATIO: float = 0.30   # Dalton MOM Ch.7 "strong rejection" (30% bar_range)
VOL_Z_REJECTION_MIN: float = 1.0         # R3 fix : aligne NSM VOL_Z_OPEN_DRIVE_MIN
                                          # (etait 0.5 trop laxiste - Pruden canon climax >= 1.5,
                                          # confirm rejection 1.0 = entre Open Drive et Spring)


@dataclass
class ResolvedDirection:
    """Output DirectionResolver. Consume par mp_engine.evaluate_decision."""
    side: str                        # "LONG" / "SHORT" / "NO_TRADE"
    confidence: float                # [0.0, 1.0]
    rationale: str                   # Citation canon (Dalton MOM Ch.X / Pruden Ch.Y)
    scenario_id: str                 # ID pour audit + DSR walk-forward Lopez
    wait_for: dict[str, Any] = field(default_factory=dict)
    # wait_for : {"pattern": "...", "min_bars": N, "max_bars": M, ...}
    triggering_features: dict[str, Any] = field(default_factory=dict)


@dataclass
class PendingEntry:
    """Entry en attente de confirmation (ConfirmationGate integre).

    Created quand resolve() detecte un scenario valid mais besoin de
    confirmation pattern (ex: break_below_strike_confirmed = 2 bars).

    R1 fix market-analyst : `prev_close` tracker pour acceptance Dalton 2 bars
    (close ET prev_close beyond target avant fire).
    """
    scenario_id: str
    side: str
    level_name: str
    start_bar_idx: int
    min_bars: int
    max_bars: int
    pattern: str                    # "break_below_strike_confirmed", etc.
    target_price: float = 0.0
    bars_waited: int = 0
    final_confidence: float = 0.0
    # R1 fix : track close bar precedente pour acceptance Dalton 2 bars.
    # Mis a jour a chaque _check_pending_confirmation call avant validation.
    prev_close: float | None = None
    triggering_features: dict[str, Any] = field(default_factory=dict)


# ─── Scenarios table-driven (12 scenarios canon) ─────────────────────────
# Format : key = (NarrativeState, level_nature) → resolved dict
# level_nature : "support" / "resistance" / "structural" (cf bot3_level_definitions)
# Si pas de match : retourne NO_TRADE (fallback safe, anti pattern 11 surengineering)

@dataclass(frozen=True)
class ScenarioRule:
    """Rule entry pour table-driven resolver."""
    scenario_id: str
    side: str                      # "LONG" / "SHORT"
    confidence: float
    rationale: str
    wait_for_pattern: str          # "" si pas de confirmation needed
    min_bars: int = 0
    max_bars: int = 0


# Table-driven scenarios (12 entries Phase 3 J+2, extensible J+3+)
# Cle = (NarrativeState, level_nature_str)
_SCENARIOS: dict[tuple[NarrativeState, str], ScenarioRule] = {
    # ─── OPEN_DRIVE momentum continuation (Dalton MOM Ch.7) ────────────
    (NarrativeState.OPEN_DRIVE_UP, "support"): ScenarioRule(
        scenario_id="S01_OD_UP_support_bounce",
        side="LONG", confidence=CONF_HIGH,
        rationale="Dalton MOM Ch.7 : Open Drive Up + support pullback = high conviction long continuation",
        wait_for_pattern="rejection_with_volume", min_bars=1, max_bars=2,
    ),
    (NarrativeState.OPEN_DRIVE_DOWN, "resistance"): ScenarioRule(
        scenario_id="S02_OD_DOWN_resistance_rejection",
        side="SHORT", confidence=CONF_HIGH,
        rationale="Dalton MOM Ch.7 : Open Drive Down + resistance bounce = high conviction short continuation",
        wait_for_pattern="rejection_with_volume", min_bars=1, max_bars=2,
    ),

    # ─── TREND continuation (Dalton MOM Ch.10 Trend Day) ────────────────
    (NarrativeState.TREND_UP_CONTINUATION, "support"): ScenarioRule(
        scenario_id="S03_TREND_UP_support_pullback",
        side="LONG", confidence=CONF_TREND_FOLLOW,
        rationale="Dalton Trend Day : pullback to support = continuation entry",
        wait_for_pattern="rejection_with_volume", min_bars=1, max_bars=2,
    ),
    (NarrativeState.TREND_DOWN_CONTINUATION, "resistance"): ScenarioRule(
        scenario_id="S04_TREND_DOWN_resistance_pullback",
        side="SHORT", confidence=CONF_TREND_FOLLOW,
        rationale="Dalton Trend Day : pullback to resistance = continuation short",
        wait_for_pattern="rejection_with_volume", min_bars=1, max_bars=2,
    ),

    # ─── Wyckoff Phase C reversal (Pruden Three Skills Ch.7) ────────────
    (NarrativeState.WYCKOFF_SPRING_LONG, "support"): ScenarioRule(
        scenario_id="S05_SPRING_recovery_long",
        side="LONG", confidence=CONF_REVERSAL,
        rationale="Wyckoff Phase C : Spring on support + recovery = bullish reversal pre-SOS",
        wait_for_pattern="spring_recovery", min_bars=2, max_bars=3,
    ),
    (NarrativeState.WYCKOFF_UPTHRUST_SHORT, "resistance"): ScenarioRule(
        scenario_id="S06_UPTHRUST_rejection_short",
        side="SHORT", confidence=CONF_REVERSAL,
        rationale="Wyckoff Phase C : Upthrust on resistance + rejection = bearish reversal pre-SOS",
        wait_for_pattern="spring_recovery", min_bars=2, max_bars=3,
    ),

    # ─── RANGE plays (Dalton MOM Ch.9 Range Day) ────────────────────────
    (NarrativeState.RANGE_RESPECTED, "support"): ScenarioRule(
        scenario_id="S07_RANGE_support_long",
        side="LONG", confidence=CONF_RANGE_PLAY,
        rationale="Dalton Range Day : long at range floor support",
        wait_for_pattern="rejection_with_volume", min_bars=2, max_bars=3,
    ),
    (NarrativeState.RANGE_RESPECTED, "resistance"): ScenarioRule(
        scenario_id="S08_RANGE_resistance_short",
        side="SHORT", confidence=CONF_RANGE_PLAY,
        rationale="Dalton Range Day : short at range top resistance",
        wait_for_pattern="rejection_with_volume", min_bars=2, max_bars=3,
    ),

    # ─── EXHAUSTION reversal (Pruden Ch.7 climax) ────────────────────────
    # Mismatch 3 Claude 4.7 fix : max_bars bump 2 → 4 car R1 fix acceptance 2 bars
    # consomme deja la 1ere bar pour set prev_close. Avant : 1 chance unique de
    # confirm (bar 2 = last). Apres : 2-3 chances (bars 2/3/4). Cf review : "Donc
    # tu as exactement UNE bar pour confirmer en marche bruyant = timeout premature".
    (NarrativeState.EXHAUSTION_TOP, "resistance"): ScenarioRule(
        scenario_id="S09_EXHAUSTION_TOP_short",
        side="SHORT", confidence=CONF_REVERSAL,
        rationale="Wyckoff buying climax (Pruden Ch.7) : short at exhaustion top",
        wait_for_pattern="break_below_strike_confirmed", min_bars=2, max_bars=4,
    ),
    (NarrativeState.EXHAUSTION_BOTTOM, "support"): ScenarioRule(
        scenario_id="S10_EXHAUSTION_BOTTOM_long",
        side="LONG", confidence=CONF_REVERSAL,
        rationale="Wyckoff selling climax (Pruden Ch.7) : long at exhaustion bottom",
        wait_for_pattern="break_below_strike_confirmed", min_bars=2, max_bars=4,
    ),

    # ─── OPEN_ROTATION/TEST_DRIVE = pas de bias directionnel fort ──────
    # → fallback NO_TRADE (cf resolve() default)
}


class DirectionResolver:
    """State machine resolver + pending entries (ConfirmationGate integre).

    1 instance, dict[(symbol, level_name) -> PendingEntry] pour multi-symbol
    multi-level concurrent pending entries.
    Pattern reference : NarrativeStateMachine (Phase 1) for threading + pickle.
    """

    def __init__(self) -> None:
        self._pending_entries: dict[tuple[str, str], PendingEntry] = {}
        self._lock: threading.RLock = threading.RLock()

    def resolve(
        self,
        snapshot: NarrativeStateSnapshot,
        level_name: str,
        level_nature: str,
        level_price: float,
        bar: dict,
        log_fn: Callable[..., None] | None = None,
    ) -> ResolvedDirection:
        """Resolve direction from narrative + level touched.

        Args:
            snapshot : NarrativeStateSnapshot NSM (post .transition()).
            level_name : ex "MQ_PUT_5800", "IB_LOW", "VPOC" (identifier).
            level_nature : "support" / "resistance" / "structural".
            level_price : prix du niveau touche (pour wait_for target).
            bar : bar courante (close, vol_z, etc. pour confirmation pattern).
            log_fn : callable optionnel pour log capture en tests.

        Returns:
            ResolvedDirection avec side LONG/SHORT/NO_TRADE.
        """
        symbol = snapshot.symbol
        key = (symbol, level_name)

        with self._lock:
            # 1. Check pending entry pour ce (symbol, level) ?
            pending = self._pending_entries.get(key)
            if pending is not None:
                return self._check_pending_confirmation(pending, snapshot, bar, log_fn)

            # 2. Lookup scenario table
            rule_key = (snapshot.state, level_nature)
            rule = _SCENARIOS.get(rule_key)

            if rule is None:
                emit(
                    "BOT3_RESOLVER_NO_TRADE",
                    log_fn=log_fn, sym=symbol,
                    reason=f"no_scenario_state={snapshot.state.value}_nature={level_nature}",
                    state=snapshot.state.value,
                )
                return ResolvedDirection(
                    side="NO_TRADE", confidence=CONF_NO_TRADE,
                    rationale=f"No scenario match for state={snapshot.state.value} nature={level_nature}",
                    scenario_id="NO_MATCH",
                )

            # 3. Scenario match → besoin de confirmation ?
            if not rule.wait_for_pattern:
                # Pas de confirmation requise (cas rare, scenario direct)
                emit(
                    "BOT3_RESOLVER_DIRECTION_RESOLVED",
                    log_fn=log_fn, sym=symbol,
                    side=rule.side, confidence=rule.confidence,
                    scenario_id=rule.scenario_id, state=snapshot.state.value,
                )
                return ResolvedDirection(
                    side=rule.side, confidence=rule.confidence,
                    rationale=rule.rationale, scenario_id=rule.scenario_id,
                    triggering_features={
                        "narrative_state": snapshot.state.value,
                        "level_name": level_name, "level_nature": level_nature,
                    },
                )

            # 4. Confirmation requise → register pending entry
            pending = PendingEntry(
                scenario_id=rule.scenario_id,
                side=rule.side,
                level_name=level_name,
                start_bar_idx=snapshot.bar_idx_current,
                min_bars=rule.min_bars,
                max_bars=rule.max_bars,
                pattern=rule.wait_for_pattern,
                target_price=level_price,
                bars_waited=0,
                final_confidence=rule.confidence,
                triggering_features={
                    "narrative_state": snapshot.state.value,
                    "level_name": level_name, "level_nature": level_nature,
                },
            )
            self._pending_entries[key] = pending
            emit(
                "BOT3_RESOLVER_PENDING_ENTRY",
                log_fn=log_fn, sym=symbol,
                scenario_id=rule.scenario_id,
                pattern=rule.wait_for_pattern,
                bars_to_wait=rule.min_bars,
            )
            return ResolvedDirection(
                side="NO_TRADE",  # En attente confirmation
                confidence=CONF_NO_TRADE,
                rationale=f"Pending confirmation : {rule.wait_for_pattern}",
                scenario_id=rule.scenario_id,
                wait_for={
                    "pattern": rule.wait_for_pattern,
                    "min_bars": rule.min_bars,
                    "max_bars": rule.max_bars,
                    "target_price": level_price,
                },
            )

    def _check_pending_confirmation(
        self,
        pending: PendingEntry,
        snapshot: NarrativeStateSnapshot,
        bar: dict,
        log_fn: Callable[..., None] | None,
    ) -> ResolvedDirection:
        """Verifie pattern confirmation pour entry pending.

        Returns ResolvedDirection :
        - side=LONG/SHORT si pattern confirme dans [min_bars, max_bars]
        - side=NO_TRADE si pas encore confirme (continue d'attendre)
        - side=NO_TRADE + cleanup si invalidated (state change) ou timeout (max_bars)

        R1 code-reviewer fix : bars_waited negatif (pickle epoch mismatch apres
        reboot VPS) = abort defensif + emit (anti-zombie permanent).
        """
        symbol = snapshot.symbol
        key = (symbol, pending.level_name)
        pending.bars_waited = snapshot.bar_idx_current - pending.start_bar_idx

        # R1 code-reviewer fix : pickle epoch mismatch detection
        # Apres restart NSM (bar_idx_current reset 0), pending.start_bar_idx
        # est de l'epoch precedent. bars_waited devient negatif = zombie.
        if pending.bars_waited < 0:
            del self._pending_entries[key]
            emit(
                "BOT3_RESOLVER_CONFIRMATION_INVALIDATED",
                log_fn=log_fn, sym=symbol,
                scenario_id=pending.scenario_id,
                reason="pickle_epoch_mismatch_negative_bars_waited",
            )
            return ResolvedDirection(
                side="NO_TRADE", confidence=CONF_NO_TRADE,
                rationale="Pending zombie cleanup (NSM bar_idx_current reset post-restart)",
                scenario_id=pending.scenario_id,
            )

        # 1. State change mid-wait = invalidated (narrative shift)
        # Approximation : si state n'est plus dans les scenarios qui ont cree
        # cet entry, on abort. Pour Phase 3 J+2, simple check : si state =
        # INVALIDATED, on abort.
        if snapshot.state == NarrativeState.INVALIDATED:
            del self._pending_entries[key]
            emit(
                "BOT3_RESOLVER_CONFIRMATION_INVALIDATED",
                log_fn=log_fn, sym=symbol,
                scenario_id=pending.scenario_id,
                reason="narrative_INVALIDATED",
            )
            return ResolvedDirection(
                side="NO_TRADE", confidence=CONF_NO_TRADE,
                rationale="Pending invalidated : narrative INVALIDATED mid-wait",
                scenario_id=pending.scenario_id,
            )

        # 2. Timeout ? bars_waited > max_bars
        if pending.bars_waited > pending.max_bars:
            del self._pending_entries[key]
            emit(
                "BOT3_RESOLVER_CONFIRMATION_TIMEOUT",
                log_fn=log_fn, sym=symbol,
                scenario_id=pending.scenario_id, max_bars=pending.max_bars,
            )
            return ResolvedDirection(
                side="NO_TRADE", confidence=CONF_NO_TRADE,
                rationale=f"Pending timeout : max_bars={pending.max_bars} reached",
                scenario_id=pending.scenario_id,
            )

        # 3. Pattern check
        if pending.bars_waited < pending.min_bars:
            # Pas encore atteint min_bars, continuer d'attendre
            return ResolvedDirection(
                side="NO_TRADE", confidence=CONF_NO_TRADE,
                rationale=f"Waiting confirmation : bars_waited={pending.bars_waited}/{pending.min_bars}",
                scenario_id=pending.scenario_id,
                wait_for={
                    "pattern": pending.pattern,
                    "min_bars": pending.min_bars, "max_bars": pending.max_bars,
                    "bars_waited": pending.bars_waited,
                },
            )

        # 4. Pattern validation (canon Dalton/Wyckoff/ICT)
        confirmed = self._validate_pattern(pending, bar)
        # Update prev_close pour next bar (R1 fix acceptance Dalton 2 bars).
        # Capture APRES validation pour preserver l'historique au moment du fire.
        close_now = _safe_float(bar.get("close"))
        if not confirmed and close_now is not None:
            pending.prev_close = close_now
        if confirmed:
            del self._pending_entries[key]
            emit(
                "BOT3_RESOLVER_CONFIRMATION_OK",
                log_fn=log_fn, sym=symbol,
                scenario_id=pending.scenario_id, side=pending.side,
                bars_waited=pending.bars_waited,
            )
            emit(
                "BOT3_RESOLVER_DIRECTION_RESOLVED",
                log_fn=log_fn, sym=symbol,
                side=pending.side, confidence=pending.final_confidence,
                scenario_id=pending.scenario_id, state=snapshot.state.value,
            )
            return ResolvedDirection(
                side=pending.side, confidence=pending.final_confidence,
                rationale=f"Confirmed pattern {pending.pattern} after {pending.bars_waited} bars",
                scenario_id=pending.scenario_id,
                triggering_features=pending.triggering_features,
            )

        # Pas encore confirme dans la fenetre, continuer
        return ResolvedDirection(
            side="NO_TRADE", confidence=CONF_NO_TRADE,
            rationale=f"Pattern {pending.pattern} not yet confirmed (bars={pending.bars_waited})",
            scenario_id=pending.scenario_id,
            wait_for={
                "pattern": pending.pattern,
                "min_bars": pending.min_bars, "max_bars": pending.max_bars,
                "bars_waited": pending.bars_waited,
            },
        )

    def _validate_pattern(self, pending: PendingEntry, bar: dict) -> bool:
        """Verifie pattern de confirmation selon canon.

        Patterns supportes Phase 3 J+2 (R1/R3/R6 fixes Tier 1) :
        - "rejection_with_volume" : lower_wick > 30% bar_range + vol_z > VOL_Z_REJECTION_MIN
        - "break_below_strike_confirmed" : close ET prev_close beyond target (Dalton
          MOM Ch.5 p.61-63 "two TPOs of acceptance" canonique, R1 market-analyst fix)
        - "spring_recovery" : low/high penetration + close recovery (Wyckoff Pruden Ch.7)
        """
        close = _safe_float(bar.get("close"))
        high = _safe_float(bar.get("high"))
        low = _safe_float(bar.get("low"))
        open_ = _safe_float(bar.get("open"))
        vol_z = _safe_float(bar.get("vol_zscore_20"))

        if pending.pattern == "rejection_with_volume":
            # R2 code-reviewer fix : check open_ aussi (silent fallback bug avant)
            if any(v is None for v in (close, high, low, vol_z, open_)):
                return False
            bar_range = high - low
            if bar_range <= 0:
                return False
            # Rejection LONG : lower wick fort + vol confirm
            # Lower wick = body_bottom - low = min(close, open) - low (body bottom au low)
            if pending.side == "LONG":
                lower_wick = min(close, open_) - low
                return (
                    (lower_wick / bar_range) > WICK_REJECTION_MIN_RATIO
                    and vol_z > VOL_Z_REJECTION_MIN
                )
            else:  # SHORT : upper wick fort = high - body_top
                upper_wick = high - max(close, open_)
                return (
                    (upper_wick / bar_range) > WICK_REJECTION_MIN_RATIO
                    and vol_z > VOL_Z_REJECTION_MIN
                )

        elif pending.pattern == "break_below_strike_confirmed":
            # R1 market-analyst fix : Dalton MOM Ch.5 p.61-63 "two TPOs of acceptance".
            # Avant : close < target seul = pseudo-BOS retail (sweep trap ICT).
            # Apres : close ET prev_close beyond target = acceptance canon 2 bars.
            if close is None or pending.prev_close is None:
                return False  # bar precedente requise pour acceptance
            if pending.side == "SHORT":
                return (close < pending.target_price
                        and pending.prev_close < pending.target_price)
            else:  # LONG
                return (close > pending.target_price
                        and pending.prev_close > pending.target_price)

        elif pending.pattern == "spring_recovery":
            if low is None or high is None or close is None:
                return False
            # Wyckoff Spring : low penetre swing_low (target_price) + close recovery
            if pending.side == "LONG":
                return low < pending.target_price and close > pending.target_price
            else:  # SHORT (Upthrust mirror)
                return high > pending.target_price and close < pending.target_price

        # Bug 5 Claude 4.7 fix : pattern inconnu = vrai silent fail avant.
        # Si typo dans _SCENARIOS (wait_for_pattern="rejection_with_volumes"),
        # tous les pendings timeout silencieusement = invisible debug Phase 3.
        # Maintenant emit log warning pour traceabilite.
        emit(
            "BOT3_RESOLVER_CONFIRMATION_INVALIDATED",
            log_fn=None,  # log_fn pas dispo ici, emit niveau MAJEUR via logger root
            sym=pending.scenario_id.split("_")[0] if "_" in pending.scenario_id else "UNKNOWN",
            scenario_id=pending.scenario_id,
            reason=f"unknown_pattern_{pending.pattern}",
        )
        return False

    def pending_count(self) -> int:
        """Helper test : combien d'entries actuellement en attente."""
        with self._lock:
            return len(self._pending_entries)

    def __getstate__(self) -> dict:
        """Exclude _lock du pickle.

        Bug 6 Claude 4.7 fix : acquire lock pendant copy pour anti-race vs resolve()
        concurrent. Avant : __dict__.copy() pendant resolve() en cours pouvait
        capturer _pending_entries dans etat intermediaire (entry deja del mais
        cleanup pas fait sur autre thread).
        """
        with self._lock:
            state = self.__dict__.copy()
            state.pop("_lock", None)
            return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._lock = threading.RLock()


# ─── Helpers ──────────────────────────────────────────────────────────────


def _safe_float(v: Any) -> float | None:
    """Cast safe en float, retourne None si invalide/NaN.

    Bug 4 Claude 4.7 fix : `import math` deplace au top du module (etait dans
    le try block, sys.modules cache mais code smell + import duplicate evalue).
    """
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None
