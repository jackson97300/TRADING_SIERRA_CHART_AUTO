"""Bot 4 v2 scenario_registry — Registry container + Detector Protocol pour 17 scenarios v2.

Module NEW Phase P3 Batch 2 (25/06/2026) — refonte propre scenarios Bot 4 v1.

ELIMINATION dette Bot 4 v1 (audit ULTRATHINK 24/06) :
- v1 = 13 scenarios disperses dans scenario_generator.py 1663 LOC monolithique
- v1 = 85% trades absurdes (R:R < 0.25), 3 scenarios morts (features dead),
  Pattern 11 V1 textbook (Range_Bound LONG+SHORT firent simultanees 76% des bars)
- v2 = chaque scenario = module dedie + ScenarioDetector Protocol + calibration
  P(win) persistee (link P1 calibration_persistence)

Architecture (spec section 3 P3) :

ScenarioFire (frozen dataclass) :
- Signal emis par un detector au moment du fire (PENDING)
- Consommable par ScenarioInstance (narrative_state batch 1 P3)

ScenarioContext (frozen dataclass) :
- Bar + RegimeAnalysis + NarrativeContext + MenthorQLevels
- Input commun a tous les detectors

ScenarioDetector (Protocol runtime_checkable) :
- `detect(context) -> Optional[ScenarioFire]`
- `name`, `family`, `direction_supported` properties
- Implementation par-scenario dans sous-module `scenarios/`

ScenarioRegistry :
- Container ordered detectors
- `evaluate_all(context) -> list[ScenarioFire]`
- Calibration P(win) link P1 via `calibration_persistence.load_calibration`

Scenarios cibles v2 (17 final) :
- KEEP (1) : Bearish_Rejection (seul edge credible PF 5.05)
- REFONDRE (6) : Bullish_Continuation, Range_Bound LONG/SHORT, IB_Break,
  Single_Print_Magnet, BN_Fired_Confluence, Failed_Breakout
- AJOUTER (10) : Sweep+Reclaim_N+1, Liquidity_Run_Continuation,
  Open_Drive_RECODE, News_Aware_Mute, VWAP_Reclaim, Trend_Day_Cont,
  Wyckoff_Phase_CD, 0DTE_Pin_Defense, Failed_Auction, Cross_Instrument_Trap
- DROP (3) : FVG_Magnet, Open_Type_Driven, Holy_Grail (features dead 14j live)

Implementation phasee : batch 2 P3 = infrastructure + 2 scenarios exemples
(Bearish_Rejection KEEP + Sweep_Reclaim_N1 nouveau). Les 15 autres = batches
suivants apres validation infrastructure.

Garde-fous :
- Detectors stateless : pas d'etat interne, prennent context, retournent ScenarioFire
- Le state lifecycle est gere par ScenarioInstance (narrative_state batch 1 P3)
- Calibration P(win) lue read-only depuis disque (post-P6 30j shadow)
- Fail-soft : detector exception -> log warning + skip (anti crash registry)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from bot4_v2.core.menthorq_source import MenthorQLevels
from bot4_v2.core.narrative_engine import NarrativeContext
from bot4_v2.core.regime_source import RegimeAnalysis
from bot4_v2.observability.calibration_persistence import (
    Calibration,
    CalibrationError,
    load_calibration,
)
from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger(__name__)


# ============================================================
# SCENARIO FIRE (signal emis par detector)
# ============================================================


@dataclass(frozen=True)
class ScenarioFire:
    """Signal scenario fire (state=PENDING dans ScenarioInstance lifecycle).

    Frozen dataclass : audit J+1 + persistance shadow_logger compatible.
    """

    # Identite
    signal_id: str  # UUID auto-genere si non fourni
    scenario_name: str
    family: str  # "Wyckoff" / "Dalton" / "ICT" / "MenthorQ" / "Classic"
    symbol: str
    direction: str  # "LONG" / "SHORT"

    # Prix
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: Optional[float] = None

    # Metadata methodologique
    heuristic_score: int = 50  # [0, 100] non-calibre (P6 -> P(win))
    confidence: float = 0.0  # P(win) calibree post-P6 OU heuristique pre-P6
    regime: str = "UNKNOWN"  # CALM_RANGE / VOLATILE_RANGE / TREND_UP / TREND_DOWN / PANIC
    session: str = "UNKNOWN"  # asia / london / us / us_ah
    timestamp_utc: str = ""  # ISO 8601 UTC fire bar

    # Audit
    reasons: tuple[str, ...] = field(default_factory=tuple)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def r_r_ratio(self) -> float:
        """Reward/Risk ratio = |target_1 - entry| / |entry - stop_loss|."""
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.target_1 - self.entry_price)
        return reward / max(risk, 1e-9)


# ============================================================
# SCENARIO CONTEXT (input commun)
# ============================================================


@dataclass(frozen=True)
class ScenarioContext:
    """Contexte commun input des detectors. Frozen pour eviter mutations."""

    bar: dict  # live_enriched JSONL bar courante
    regime: RegimeAnalysis
    narrative: NarrativeContext
    menthorq: MenthorQLevels  # peut etre is_empty=True

    @property
    def symbol(self) -> str:
        return self.narrative.symbol

    @property
    def close(self) -> float:
        return self.narrative.close

    @property
    def atr(self) -> float:
        return self.narrative.atr

    @property
    def session_segment(self) -> str:
        return self.narrative.session.current_segment


# ============================================================
# SCENARIO DETECTOR PROTOCOL
# ============================================================


@runtime_checkable
class ScenarioDetector(Protocol):
    """Interface Protocol pour les detectors scenario.

    Implementation : sous-module `bot4_v2/decision/scenarios/{name}.py`
    avec class implementant ScenarioDetector.

    Anti-dette v1 : DETECTORS STATELESS. State lifecycle = ScenarioInstance
    (narrative_state.py). Detector retourne fire ou None, jamais d'etat interne.
    """

    @property
    def name(self) -> str:
        """Nom unique scenario (ex 'Bearish_Rejection')."""
        ...

    @property
    def family(self) -> str:
        """Famille methodologique ('Wyckoff' / 'Dalton' / 'ICT' / ...)."""
        ...

    @property
    def directions_supported(self) -> tuple[str, ...]:
        """Directions supportees ('LONG', 'SHORT', ou both)."""
        ...

    def detect(self, ctx: ScenarioContext) -> Optional[ScenarioFire]:
        """Evalue context et retourne ScenarioFire si setup detecte.

        Args:
            ctx : contexte commun (bar + regime + narrative + menthorq)

        Returns:
            ScenarioFire si setup detecte, None sinon.

        Garde-fou : detector NE DOIT PAS lever d'exception (fail-soft).
        Si exception, registry catch + log warning + skip ce scenario.
        """
        ...


# ============================================================
# REGISTRY
# ============================================================


class ScenarioRegistry:
    """Container ordered detectors + evaluation registry-wide.

    Pattern :
        registry = ScenarioRegistry(calibration_dir=Path("DATA/MODELS/scenario_calibrators"))
        registry.register(BearishRejectionDetector())
        registry.register(SweepReclaimN1Detector())
        ...
        # Per bar :
        fires = registry.evaluate_all(context)
        for fire in fires:
            instance = ScenarioInstance(...fire data...)
            tracker.add(instance)

    Thread-safety : NON. Single-thread main loop bot4_v2.
    """

    def __init__(self, calibration_dir: Optional[Path] = None):
        """Init registry.

        Args:
            calibration_dir : repertoire calibrations isotonic regression
                              (P6 shadow data 30j+). None = pas de calibration
                              (heuristic_score brut utilise comme confidence).
        """
        self._detectors: list[ScenarioDetector] = []
        self._calibration_dir = calibration_dir
        self._calibration_cache: dict[str, Optional[Calibration]] = {}

    @property
    def n_detectors(self) -> int:
        return len(self._detectors)

    @property
    def detector_names(self) -> tuple[str, ...]:
        return tuple(d.name for d in self._detectors)

    def register(self, detector: ScenarioDetector) -> None:
        """Ajoute un detector au registry.

        Garde-fou : verifie implementation Protocol (runtime_checkable) +
        unicite name (anti collision config).
        """
        if not isinstance(detector, ScenarioDetector):
            raise TypeError(
                f"detector must implement ScenarioDetector Protocol, "
                f"got {type(detector).__name__}"
            )
        if detector.name in self.detector_names:
            raise ValueError(
                f"Detector name {detector.name!r} already registered "
                "(unicite enforcement anti collision)"
            )
        self._detectors.append(detector)

    def evaluate_all(self, ctx: ScenarioContext) -> list[ScenarioFire]:
        """Evalue tous les detectors sur le contexte courant.

        Pattern fail-soft : si un detector raise, log warning + skip.
        Le registry continue avec les autres detectors.

        Returns:
            Liste ScenarioFire (peut etre vide).
        """
        fires: list[ScenarioFire] = []
        for detector in self._detectors:
            try:
                fire = detector.detect(ctx)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning(
                    "scenario_registry: detector %s raised %s (skipped)",
                    detector.name, type(exc).__name__,
                )
                continue
            if fire is not None:
                # Enrich confidence via calibration P(win) si dispo
                enriched = self._enrich_confidence(fire, ctx)
                fires.append(enriched)
        return fires

    def _enrich_confidence(
        self, fire: ScenarioFire, ctx: ScenarioContext,
    ) -> ScenarioFire:
        """Enrichit confidence via calibration P(win) post-P6 si dispo.

        Pre-P6 (calibration_dir None ou pas de fichier) : confidence =
        heuristic_score / 100 (proxy linear, sera remplace par isotonic regression
        apres 30j shadow data).

        Post-P6 : `P(win) = isotonic.predict(heuristic_score)` per (scenario,
        regime, symbol). Frozen ScenarioFire => return new instance.
        """
        if self._calibration_dir is None:
            # Pre-P6 : confidence = heuristic_score / 100
            return _replace_confidence(fire, fire.heuristic_score / 100.0)

        cal = self._load_calibration(
            scenario=fire.scenario_name,
            regime=fire.regime,
            symbol=fire.symbol,
        )
        if cal is None:
            # Calibration absente -> fallback heuristic
            return _replace_confidence(fire, fire.heuristic_score / 100.0)

        try:
            p_win = float(cal.model.predict(fire.heuristic_score))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "scenario_registry: calibration predict fail scenario=%s "
                "exc=%s -> fallback heuristic",
                fire.scenario_name, type(exc).__name__,
            )
            return _replace_confidence(fire, fire.heuristic_score / 100.0)

        # Clamp [0, 1]
        p_win = max(0.0, min(1.0, p_win))
        return _replace_confidence(fire, p_win)

    def _load_calibration(
        self, scenario: str, regime: str, symbol: str,
    ) -> Optional[Calibration]:
        """Charge calibration P(win) cache. Returns None si introuvable / stale."""
        if self._calibration_dir is None:
            return None
        cache_key = f"{symbol}_{scenario}_{regime}"
        if cache_key in self._calibration_cache:
            return self._calibration_cache[cache_key]
        try:
            cal = load_calibration(
                self._calibration_dir, symbol, scenario, regime,
            )
        except (FileNotFoundError, CalibrationError) as exc:
            # Pas de calibration ou stale = OK pre-P6, log debug seulement
            _LOG.debug(
                "scenario_registry: calibration absent %s reason=%s",
                cache_key, type(exc).__name__,
            )
            self._calibration_cache[cache_key] = None
            return None
        self._calibration_cache[cache_key] = cal
        return cal

    def clear_calibration_cache(self) -> None:
        """Force reload calibrations au prochain detect (post-P6 hot-reload)."""
        self._calibration_cache.clear()


# ============================================================
# HELPERS
# ============================================================


def _replace_confidence(fire: ScenarioFire, confidence: float) -> ScenarioFire:
    """Cree nouvelle ScenarioFire avec confidence remplace (frozen)."""
    return ScenarioFire(
        signal_id=fire.signal_id,
        scenario_name=fire.scenario_name,
        family=fire.family,
        symbol=fire.symbol,
        direction=fire.direction,
        entry_price=fire.entry_price,
        stop_loss=fire.stop_loss,
        target_1=fire.target_1,
        target_2=fire.target_2,
        heuristic_score=fire.heuristic_score,
        confidence=round(confidence, 4),
        regime=fire.regime,
        session=fire.session,
        timestamp_utc=fire.timestamp_utc,
        reasons=fire.reasons,
        extra=fire.extra,
    )


def make_signal_id(scenario_name: str, symbol: str) -> str:
    """Helper unique signal_id : SCENARIO_SYMBOL_uuid8."""
    short = uuid.uuid4().hex[:8]
    return f"{scenario_name}_{symbol}_{short}"


def make_timestamp_utc() -> str:
    """Helper timestamp UTC ISO 8601."""
    return datetime.now(timezone.utc).isoformat()
