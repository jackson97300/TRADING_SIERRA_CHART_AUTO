"""Tests bot4_v2/decision/scenario_registry + scenarios exemples."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from bot4_v2.core.menthorq_source import MenthorQLevels
from bot4_v2.core.narrative_engine import KeyLevel, NarrativeContext
from bot4_v2.core.regime_source import RegimeAnalysis
from bot4_v2.decision.scenario_registry import (
    ScenarioContext,
    ScenarioDetector,
    ScenarioFire,
    ScenarioRegistry,
    make_signal_id,
    make_timestamp_utc,
)
from bot4_v2.decision.scenarios.bearish_rejection import BearishRejectionDetector
from bot4_v2.decision.scenarios.sweep_reclaim_n1 import SweepReclaimN1Detector


# ============================================================
# Helpers
# ============================================================


def _make_regime(
    mode: str = "TREND", favor: str = "SHORT", vol_regime: str = "NORMAL",
) -> RegimeAnalysis:
    return RegimeAnalysis(
        mode=mode, favor=favor, confidence=0.5,
        trend_votes=5, range_votes=2, vol_regime=vol_regime,
        bias_score=0.3, is_actionable=True,
    )


def _make_narrative(
    *,
    symbol: str = "NQ",
    close: float = 20000.0,
    atr: float = 10.0,
    resistance_levels: Optional[list[KeyLevel]] = None,
) -> NarrativeContext:
    return NarrativeContext(
        timestamp_utc="2026-06-25T10:00:00+00:00",
        symbol=symbol,
        close=close,
        atr=atr,
        atr_14m=40.0,
        key_levels_resistance=resistance_levels or [],
    )


def _make_menthorq(symbol: str = "NQ") -> MenthorQLevels:
    return MenthorQLevels(symbol=symbol, date_str="20260625", is_empty=True)


def _make_bar(
    *,
    high: float = 20010.0, low: float = 19995.0, close: float = 20000.0,
    delta_bar: float = -100.0,
    bn_pressure_ask: float = 50.0, bn_pressure_bid: float = 30.0,
    **extras,
) -> dict:
    bar = {
        "high": high, "low": low, "close": close,
        "delta_bar": delta_bar,
        "bn_pressure_ask": bn_pressure_ask,
        "bn_pressure_bid": bn_pressure_bid,
    }
    bar.update(extras)
    return bar


def _make_ctx(
    *,
    bar: Optional[dict] = None,
    regime: Optional[RegimeAnalysis] = None,
    narrative: Optional[NarrativeContext] = None,
    menthorq: Optional[MenthorQLevels] = None,
) -> ScenarioContext:
    return ScenarioContext(
        bar=bar or _make_bar(),
        regime=regime or _make_regime(),
        narrative=narrative or _make_narrative(),
        menthorq=menthorq or _make_menthorq(),
    )


# ============================================================
# ScenarioFire dataclass
# ============================================================


def test_scenario_fire_r_r_ratio():
    """R:R = |target-entry| / |entry-stop|."""
    fire = ScenarioFire(
        signal_id="X", scenario_name="X", family="Y", symbol="NQ",
        direction="SHORT",
        entry_price=20000.0, stop_loss=20010.0, target_1=19980.0,
    )
    # risk = 10, reward = 20 -> RR = 2
    assert fire.r_r_ratio == 2.0


def test_scenario_fire_frozen():
    from dataclasses import FrozenInstanceError
    fire = ScenarioFire(
        signal_id="X", scenario_name="X", family="Y", symbol="NQ",
        direction="SHORT",
        entry_price=20000.0, stop_loss=20010.0, target_1=19980.0,
    )
    with pytest.raises(FrozenInstanceError):
        fire.entry_price = 0.0  # type: ignore


# ============================================================
# ScenarioContext properties
# ============================================================


def test_scenario_context_properties():
    ctx = _make_ctx()
    assert ctx.symbol == "NQ"
    assert ctx.close == 20000.0
    assert ctx.atr == 10.0


# ============================================================
# Helpers
# ============================================================


def test_make_signal_id_format():
    sid = make_signal_id("Bearish_Rejection", "NQ")
    assert sid.startswith("Bearish_Rejection_NQ_")
    assert len(sid.split("_")[-1]) == 8  # UUID hex 8 chars


def test_make_signal_id_unique():
    sid1 = make_signal_id("X", "NQ")
    sid2 = make_signal_id("X", "NQ")
    assert sid1 != sid2


def test_make_timestamp_utc_iso_format():
    ts = make_timestamp_utc()
    assert "T" in ts
    assert "+00:00" in ts or ts.endswith("Z")


# ============================================================
# ScenarioRegistry init & register
# ============================================================


def test_registry_init_empty():
    reg = ScenarioRegistry()
    assert reg.n_detectors == 0
    assert reg.detector_names == ()


def test_registry_register_detector():
    reg = ScenarioRegistry()
    reg.register(BearishRejectionDetector())
    assert reg.n_detectors == 1
    assert "Bearish_Rejection" in reg.detector_names


def test_registry_register_rejects_non_protocol():
    """Object qui n'implemente pas ScenarioDetector -> TypeError."""

    class BadDetector:
        pass

    reg = ScenarioRegistry()
    with pytest.raises(TypeError, match="ScenarioDetector"):
        reg.register(BadDetector())  # type: ignore


def test_registry_register_rejects_duplicate_name():
    reg = ScenarioRegistry()
    reg.register(BearishRejectionDetector())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(BearishRejectionDetector())


# ============================================================
# ScenarioRegistry evaluate_all
# ============================================================


def test_registry_evaluate_all_empty_returns_empty():
    reg = ScenarioRegistry()
    ctx = _make_ctx()
    fires = reg.evaluate_all(ctx)
    assert fires == []


def test_registry_evaluate_all_skips_detector_exception():
    """Si detector raise, log warning + skip (anti crash)."""

    class RaisingDetector:
        @property
        def name(self):
            return "Raiser"

        @property
        def family(self):
            return "X"

        @property
        def directions_supported(self):
            return ("LONG",)

        def detect(self, ctx):
            raise RuntimeError("simulated detector fail")

    reg = ScenarioRegistry()
    reg.register(RaisingDetector())
    ctx = _make_ctx()
    fires = reg.evaluate_all(ctx)
    assert fires == []  # no crash, just skip


def test_registry_evaluate_all_collects_multiple_fires():
    """2 detectors, 2 fires possibles."""

    class FixedDetector:
        def __init__(self, name):
            self._name = name

        @property
        def name(self):
            return self._name

        @property
        def family(self):
            return "Test"

        @property
        def directions_supported(self):
            return ("LONG",)

        def detect(self, ctx):
            return ScenarioFire(
                signal_id=f"X_{self._name}",
                scenario_name=self._name,
                family="Test",
                symbol="NQ",
                direction="LONG",
                entry_price=20000.0,
                stop_loss=19990.0,
                target_1=20020.0,
                heuristic_score=75,
            )

    reg = ScenarioRegistry()
    reg.register(FixedDetector("A"))
    reg.register(FixedDetector("B"))
    fires = reg.evaluate_all(_make_ctx())
    assert len(fires) == 2


# ============================================================
# Calibration enrichment (pre-P6 = heuristic/100)
# ============================================================


def test_registry_no_calibration_uses_heuristic_div_100():
    """calibration_dir=None -> confidence = heuristic_score / 100."""

    class HeuristicDetector:
        @property
        def name(self):
            return "H"

        @property
        def family(self):
            return "X"

        @property
        def directions_supported(self):
            return ("LONG",)

        def detect(self, ctx):
            return ScenarioFire(
                signal_id="X", scenario_name="H", family="X", symbol="NQ",
                direction="LONG",
                entry_price=20000.0, stop_loss=19990.0, target_1=20020.0,
                heuristic_score=75,
            )

    reg = ScenarioRegistry(calibration_dir=None)
    reg.register(HeuristicDetector())
    fires = reg.evaluate_all(_make_ctx())
    assert len(fires) == 1
    assert fires[0].confidence == 0.75  # 75 / 100


def test_registry_calibration_dir_no_file_uses_heuristic(tmp_path):
    """calibration_dir defined mais file absent -> fallback heuristic."""

    class HeuristicDetector:
        @property
        def name(self):
            return "H"

        @property
        def family(self):
            return "X"

        @property
        def directions_supported(self):
            return ("LONG",)

        def detect(self, ctx):
            return ScenarioFire(
                signal_id="X", scenario_name="H", family="X", symbol="NQ",
                direction="LONG",
                entry_price=20000.0, stop_loss=19990.0, target_1=20020.0,
                heuristic_score=60,
            )

    reg = ScenarioRegistry(calibration_dir=tmp_path)
    reg.register(HeuristicDetector())
    fires = reg.evaluate_all(_make_ctx())
    assert fires[0].confidence == 0.60


# ============================================================
# Bearish_Rejection detector
# ============================================================


def test_bearish_rejection_no_resistance_no_fire():
    """Pas de niveaux resistance -> no fire."""
    det = BearishRejectionDetector()
    ctx = _make_ctx()  # narrative.key_levels_resistance vide
    assert det.detect(ctx) is None


def test_bearish_rejection_extreme_vol_no_fire():
    det = BearishRejectionDetector()
    res = [KeyLevel(price=20015.0, label="PDH", level_type="resistance",
                    distance_atr=1.5, sources=["PDH", "VAH"], confluence_count=2)]
    ctx = _make_ctx(
        regime=_make_regime(vol_regime="EXTREME"),
        narrative=_make_narrative(resistance_levels=res),
    )
    assert det.detect(ctx) is None


def test_bearish_rejection_single_confluence_no_fire():
    """Confluence count = 1 -> not major resistance, no fire."""
    det = BearishRejectionDetector()
    res = [KeyLevel(price=20015.0, label="PDH", level_type="resistance",
                    distance_atr=1.5, sources=["PDH"], confluence_count=1)]
    ctx = _make_ctx(narrative=_make_narrative(resistance_levels=res))
    assert det.detect(ctx) is None


def test_bearish_rejection_distance_too_far_no_fire():
    """Niveau distant > 0.15% du close -> not major proximity."""
    det = BearishRejectionDetector()
    # close=20000, level=20100 = 0.5% > 0.15%
    res = [KeyLevel(price=20100.0, label="PDH", level_type="resistance",
                    distance_atr=10.0, sources=["PDH", "VAH"], confluence_count=2)]
    ctx = _make_ctx(narrative=_make_narrative(resistance_levels=res))
    assert det.detect(ctx) is None


def test_bearish_rejection_close_not_top_no_fire():
    """Close pas dans top 50% bar -> no rejection PA."""
    det = BearishRejectionDetector()
    res = [KeyLevel(price=20015.0, label="PDH", level_type="resistance",
                    distance_atr=1.5, sources=["PDH", "VAH"], confluence_count=2)]
    # close=19998 dans bar [19995, 20010] -> position = 3/15 = 20% (pas dans top 50%)
    bar = _make_bar(high=20010, low=19995, close=19998)
    ctx = _make_ctx(bar=bar, narrative=_make_narrative(resistance_levels=res))
    assert det.detect(ctx) is None


def test_bearish_rejection_no_bearish_of_no_fire():
    """delta_bar > 0 ET pressure_ask < pressure_bid -> no OF bearish."""
    det = BearishRejectionDetector()
    res = [KeyLevel(price=20015.0, label="PDH", level_type="resistance",
                    distance_atr=1.5, sources=["PDH", "VAH"], confluence_count=2)]
    bar = _make_bar(high=20010, low=19995, close=20008,
                     delta_bar=100.0,
                     bn_pressure_ask=10.0, bn_pressure_bid=50.0)
    ctx = _make_ctx(bar=bar, narrative=_make_narrative(resistance_levels=res))
    assert det.detect(ctx) is None


def test_bearish_rejection_full_setup_fires():
    """Setup complet : resistance confluence 2 + close top + OF bearish."""
    det = BearishRejectionDetector()
    res = [KeyLevel(price=20015.0, label="PDH+VAH", level_type="resistance",
                    distance_atr=1.5, sources=["PDH", "VAH"], confluence_count=2)]
    # close=20008 dans bar [19995, 20010] -> position = 13/15 = 87% (top)
    bar = _make_bar(high=20010, low=19995, close=20008,
                     delta_bar=-150.0,
                     bn_pressure_ask=80.0, bn_pressure_bid=20.0)
    ctx = _make_ctx(bar=bar, narrative=_make_narrative(resistance_levels=res))
    fire = det.detect(ctx)
    assert fire is not None
    assert fire.scenario_name == "Bearish_Rejection"
    assert fire.direction == "SHORT"
    assert fire.entry_price == 20008.0
    assert fire.stop_loss > 20010.0  # high + buffer
    assert fire.target_1 < 20008.0  # SHORT target below entry
    # R:R = (entry - target_1) / (stop - entry) = 2.0
    assert abs(fire.r_r_ratio - 2.0) < 0.01
    assert fire.heuristic_score >= 50
    assert fire.regime == "TREND"


def test_bearish_rejection_implements_protocol():
    det = BearishRejectionDetector()
    assert isinstance(det, ScenarioDetector)


# ============================================================
# Sweep_Reclaim_N1 detector
# ============================================================


def test_sweep_reclaim_no_sweep_features_no_fire():
    """Bar sans sweep_*_lag1 ni sweep_*_active -> no fire."""
    det = SweepReclaimN1Detector()
    ctx = _make_ctx()  # bar default no sweep
    assert det.detect(ctx) is None


def test_sweep_reclaim_extreme_vol_no_fire():
    """vol_regime EXTREME -> no trade ICT (volatilite trop elevee)."""
    det = SweepReclaimN1Detector()
    bar = _make_bar(sweep_high_lag1=1)
    ctx = _make_ctx(bar=bar, regime=_make_regime(vol_regime="EXTREME"))
    assert det.detect(ctx) is None


def test_sweep_reclaim_short_setup_fires():
    """Sweep high lag1 + close < high -> SHORT fire."""
    det = SweepReclaimN1Detector()
    bar = _make_bar(
        high=20020, low=19995, close=20005,
        sweep_high_lag1=1,
        delta_bar=-100,
    )
    ctx = _make_ctx(bar=bar, regime=_make_regime(favor="SHORT"))
    fire = det.detect(ctx)
    assert fire is not None
    assert fire.direction == "SHORT"
    assert fire.entry_price == 20005.0
    assert fire.stop_loss > 20020.0  # high + buffer
    assert "sweep_high_lag1_detected" in fire.reasons


def test_sweep_reclaim_long_setup_fires():
    """Sweep low lag1 + close > low -> LONG fire."""
    det = SweepReclaimN1Detector()
    bar = _make_bar(
        high=20015, low=19980, close=20000,
        sweep_low_lag1=1,
        delta_bar=100,
    )
    ctx = _make_ctx(bar=bar, regime=_make_regime(favor="LONG"))
    fire = det.detect(ctx)
    assert fire is not None
    assert fire.direction == "LONG"
    assert fire.entry_price == 20000.0
    assert fire.stop_loss < 19980.0  # low - buffer
    assert "sweep_low_lag1_detected" in fire.reasons


def test_sweep_reclaim_fallback_to_active_compteur():
    """Si lag1 features absentes, fallback sweep_*_active."""
    det = SweepReclaimN1Detector()
    bar = _make_bar(
        high=20020, low=19995, close=20005,
        sweep_high_active=2,  # fallback (lag1 absent)
        delta_bar=-100,
    )
    ctx = _make_ctx(bar=bar)
    fire = det.detect(ctx)
    assert fire is not None
    assert fire.direction == "SHORT"


def test_sweep_reclaim_short_close_above_high_no_fire():
    """Si close >= high, pas de reclaim (price didn't come back)."""
    det = SweepReclaimN1Detector()
    bar = _make_bar(
        high=20020, low=19995, close=20020,  # close = high
        sweep_high_lag1=1,
    )
    ctx = _make_ctx(bar=bar)
    assert det.detect(ctx) is None


def test_sweep_reclaim_score_bonus_regime_aligned():
    """Bonus +15 si regime favor aligne direction."""
    det = SweepReclaimN1Detector()
    bar = _make_bar(
        high=20020, low=19995, close=20005,
        sweep_high_lag1=1,
        delta_bar=-100,
    )
    ctx_aligned = _make_ctx(bar=bar, regime=_make_regime(favor="SHORT"))
    fire_aligned = det.detect(ctx_aligned)
    ctx_neutral = _make_ctx(bar=bar, regime=_make_regime(favor="NEUTRE"))
    fire_neutral = det.detect(ctx_neutral)
    assert fire_aligned.heuristic_score > fire_neutral.heuristic_score


def test_sweep_reclaim_implements_protocol():
    det = SweepReclaimN1Detector()
    assert isinstance(det, ScenarioDetector)


# ============================================================
# Integration : Registry + 2 scenarios
# ============================================================


def test_integration_registry_with_2_real_detectors():
    """Registry avec BearishRejection + SweepReclaim, contexte qui fire les 2."""
    reg = ScenarioRegistry()
    reg.register(BearishRejectionDetector())
    reg.register(SweepReclaimN1Detector())

    # Context qui satisfait BearishRejection + Sweep_Reclaim simultanement
    res = [KeyLevel(price=20015.0, label="PDH", level_type="resistance",
                    distance_atr=1.5, sources=["PDH", "VAH"], confluence_count=2)]
    bar = _make_bar(
        high=20010, low=19995, close=20008,
        delta_bar=-150,
        bn_pressure_ask=80.0, bn_pressure_bid=20.0,
        sweep_high_lag1=1,
    )
    ctx = _make_ctx(bar=bar, narrative=_make_narrative(resistance_levels=res))
    fires = reg.evaluate_all(ctx)
    # 2 fires possibles (Bearish_Rejection + Sweep_Reclaim_N1)
    assert len(fires) >= 1
    scenario_names = [f.scenario_name for f in fires]
    # Au moins un des deux
    assert any(name in scenario_names for name in
                ("Bearish_Rejection", "Sweep_Reclaim_N1"))
