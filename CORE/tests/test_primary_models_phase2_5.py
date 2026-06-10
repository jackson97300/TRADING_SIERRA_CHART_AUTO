"""
Tests unitaires Phase 2-5 — 8 primary models fixes apres review round 3.

Models couverts :
  - va_failure_fade (Phase 2a)
  - mq_level_bounce (Phase 2b)
  - trend_day_rider (Phase 2c)
  - orb (Phase 4a)
  - gap_fade (Phase 4b)
  - swing_rejection_fade (ex double_top_bottom, Phase 3)
  - poor_high_low_touch_fade (ex poor_high_low_retest, Phase 3)
  - swing_pullback (ex dow_trend_fractal, Phase 3)
  - CVR3VixFilter (Phase 5)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from CORE.primary_models.base import SignalType
from CORE.primary_models.double_top_bottom import DoubleTopBottomModel
from CORE.primary_models.dow_trend_fractal import DowTrendFractalModel
from CORE.primary_models.gap_fade import GapFadeModel
from CORE.primary_models.mq_level_bounce import MqLevelBounceModel
from CORE.primary_models.orb import OpeningRangeBreakoutModel
from CORE.primary_models.poor_high_low_retest import PoorHighLowRetestModel
from CORE.primary_models.trend_day_rider import TrendDayRiderModel
from CORE.primary_models.va_failure_fade import VaFailureFadeModel
from CORE.regime_filters.cvr3_vix import CVR3VixFilter


ES_DATASET = Path("DATA/DATASETS/ES_dataset_v2.parquet")


# ═══════════════════════════════════════════════════════════════════════
# VA FAILURE FADE
# ═══════════════════════════════════════════════════════════════════════

class TestVaFailureFade:
    """Convention DMP : dist_vah > 0 ET dist_val < 0 = prix DANS VA.
    vpoc_dist > 0 = prix SOUS VPOC (moitie basse) → LONG vers VAH."""

    def _row(self, open_in=0, inside=1, vpoc_dist=0.5, vah_dist=0.3, val_dist=-0.3):
        return pd.Series({
            "open_in_prev_va": open_in,
            "inside_prev_va": inside,
            "dist_prev_vpoc_atr": vpoc_dist,
            "dist_prev_vah_atr": vah_dist,
            "dist_prev_val_atr": val_dist,
        })

    def test_long_when_below_vpoc_after_open_outside(self):
        """vpoc_dist > 0 → prix sous VPOC → LONG vers VAH."""
        sig = VaFailureFadeModel().generate_signal(self._row(vpoc_dist=0.5))
        assert sig.type == SignalType.BUY

    def test_short_when_above_vpoc_after_open_outside(self):
        """vpoc_dist < 0 → prix au-dessus VPOC → SHORT vers VAL."""
        sig = VaFailureFadeModel().generate_signal(self._row(vpoc_dist=-0.5))
        assert sig.type == SignalType.SELL

    def test_hold_when_open_inside_va(self):
        sig = VaFailureFadeModel().generate_signal(self._row(open_in=1, vpoc_dist=0.5))
        assert sig.type == SignalType.HOLD

    def test_hold_when_still_outside_va(self):
        sig = VaFailureFadeModel().generate_signal(self._row(inside=0, vpoc_dist=0.5))
        assert sig.type == SignalType.HOLD

    def test_hold_when_vpoc_neutral(self):
        """Pas de BUY/SELL simultane si vpoc neutre."""
        sig = VaFailureFadeModel().generate_signal(self._row(vpoc_dist=0.05))
        assert sig.type == SignalType.HOLD

    def test_hold_when_sanity_check_fails_above_vah(self):
        """Si dist_vah < 0 (prix au-dessus VAH), pas dans VA → HOLD."""
        sig = VaFailureFadeModel().generate_signal(
            self._row(vpoc_dist=0.5, vah_dist=-0.2, val_dist=-0.5)
        )
        assert sig.type == SignalType.HOLD


# ═══════════════════════════════════════════════════════════════════════
# MQ LEVEL BOUNCE
# ═══════════════════════════════════════════════════════════════════════

class TestMqLevelBounce:

    def _row(self, call_res=1.0, put_0dte=1.0, call_0dte=1.0, hvl=1.0,
             sess_high=1.0, sess_low=100.0):
        return pd.Series({
            "mq_dist_call_res_atr": call_res,
            "mq_dist_put_0dte_atr": put_0dte,
            "mq_dist_call_0dte_atr": call_0dte,
            "mq_dist_hvl_atr": hvl,
            "dist_sess_high_atr": sess_high,
            "dist_sess_low": sess_low,
        })

    def test_short_at_call_resistance_top_range(self):
        sig = MqLevelBounceModel().generate_signal(
            self._row(call_res=0.1, sess_high=0.1)
        )
        assert sig.type == SignalType.SELL

    def test_long_at_put_0dte_bottom_range(self):
        sig = MqLevelBounceModel().generate_signal(
            self._row(put_0dte=0.1, sess_low=2.0)
        )
        assert sig.type == SignalType.BUY

    def test_hold_mid_range_even_at_level(self):
        sig = MqLevelBounceModel().generate_signal(
            self._row(call_res=0.1, sess_high=1.5, sess_low=200.0)
        )
        assert sig.type == SignalType.HOLD


# ═══════════════════════════════════════════════════════════════════════
# TREND DAY RIDER
# ═══════════════════════════════════════════════════════════════════════

class TestTrendDayRider:

    def _row(self, ib_complete=True, ib_up=False, ib_down=False,
             ext=2.0, vwap_dist=0.1):
        return pd.Series({
            "ib_complete": ib_complete,
            "ib_broken_up": ib_up,
            "ib_broken_down": ib_down,
            "ctx_ib_extension_ratio": ext,
            "dist_vwap_d_atr": vwap_dist,
        })

    def test_long_on_pullback_after_up_breakout(self):
        sig = TrendDayRiderModel().generate_signal(self._row(ib_up=True))
        assert sig.type == SignalType.BUY

    def test_short_on_pullback_after_down_breakout(self):
        sig = TrendDayRiderModel().generate_signal(self._row(ib_down=True))
        assert sig.type == SignalType.SELL

    def test_hold_when_extension_too_low(self):
        sig = TrendDayRiderModel().generate_signal(self._row(ext=1.0, ib_up=True))
        assert sig.type == SignalType.HOLD

    def test_hold_when_ib_not_complete(self):
        sig = TrendDayRiderModel().generate_signal(self._row(ib_complete=False, ib_up=True))
        assert sig.type == SignalType.HOLD


# ═══════════════════════════════════════════════════════════════════════
# ORB
# ═══════════════════════════════════════════════════════════════════════

class TestOrb:

    def _row(self, ib_complete=True, ib_range=1.0, up=False, down=False):
        return pd.Series({
            "ib_complete": ib_complete,
            "ib_range_atr": ib_range,
            "ib_broken_up": up,
            "ib_broken_down": down,
        })

    def test_long_when_broken_up(self):
        sig = OpeningRangeBreakoutModel().generate_signal(self._row(up=True))
        assert sig.type == SignalType.BUY

    def test_short_when_broken_down(self):
        sig = OpeningRangeBreakoutModel().generate_signal(self._row(down=True))
        assert sig.type == SignalType.SELL

    def test_hold_before_ib_complete(self):
        sig = OpeningRangeBreakoutModel().generate_signal(self._row(ib_complete=False, up=True))
        assert sig.type == SignalType.HOLD

    def test_hold_when_narrow_ib(self):
        """Avec min_ib_range_atr=0.25, 0.15 doit etre insuffisant."""
        sig = OpeningRangeBreakoutModel().generate_signal(self._row(ib_range=0.15, up=True))
        assert sig.type == SignalType.HOLD

    def test_hold_when_both_broken(self):
        """Ambiguous : both up and down broken (bracket) → hold."""
        sig = OpeningRangeBreakoutModel().generate_signal(self._row(up=True, down=True))
        assert sig.type == SignalType.HOLD


# ═══════════════════════════════════════════════════════════════════════
# GAP FADE
# ═══════════════════════════════════════════════════════════════════════

class TestGapFade:

    def _row(self, gap=-0.5, vix=18.0):
        return pd.Series({
            "open_gap_atr": gap,
            "vix_level": vix,
        })

    def test_long_gap_down(self):
        sig = GapFadeModel().generate_signal(self._row(gap=-0.5))
        assert sig.type == SignalType.BUY

    def test_short_gap_up(self):
        sig = GapFadeModel().generate_signal(self._row(gap=0.5))
        assert sig.type == SignalType.SELL

    def test_hold_gap_too_small(self):
        sig = GapFadeModel().generate_signal(self._row(gap=0.05))
        assert sig.type == SignalType.HOLD

    def test_hold_vix_too_high(self):
        sig = GapFadeModel().generate_signal(self._row(gap=-0.5, vix=30.0))
        assert sig.type == SignalType.HOLD

    def test_hold_when_gap_zero(self):
        sig = GapFadeModel().generate_signal(self._row(gap=0.0))
        assert sig.type == SignalType.HOLD


# ═══════════════════════════════════════════════════════════════════════
# SWING REJECTION / POOR HIGH / SWING PULLBACK (stateless proxies)
# ═══════════════════════════════════════════════════════════════════════

class TestSwingRejectionFade:

    def test_short_at_swing_high_top_range(self):
        row = pd.Series({
            "dist_swing_high_atr": 0.1,
            "dist_swing_low": 100.0,
            "swing_range_atr": 1.5,
            "dist_sess_high_atr": 0.1,
            "dist_sess_low": 100.0,
        })
        sig = DoubleTopBottomModel().generate_signal(row)
        assert sig.type == SignalType.SELL

    def test_hold_when_swing_range_too_small(self):
        row = pd.Series({
            "dist_swing_high_atr": 0.1,
            "dist_swing_low": 100.0,
            "swing_range_atr": 0.3,
            "dist_sess_high_atr": 0.1,
            "dist_sess_low": 100.0,
        })
        sig = DoubleTopBottomModel().generate_signal(row)
        assert sig.type == SignalType.HOLD


class TestPoorHighLowTouchFade:

    def test_short_at_poor_high_top_range(self):
        row = pd.Series({
            "ctx_poor_high": 1,
            "ctx_poor_low": 0,
            "dist_swing_high_atr": 0.1,
            "dist_swing_low": 100.0,
            "dist_sess_high_atr": 0.1,
            "dist_sess_low": 100.0,
        })
        sig = PoorHighLowRetestModel().generate_signal(row)
        assert sig.type == SignalType.SELL

    def test_hold_without_poor_high(self):
        row = pd.Series({
            "ctx_poor_high": 0,
            "ctx_poor_low": 0,
            "dist_swing_high_atr": 0.1,
            "dist_swing_low": 100.0,
            "dist_sess_high_atr": 0.1,
            "dist_sess_low": 100.0,
        })
        sig = PoorHighLowRetestModel().generate_signal(row)
        assert sig.type == SignalType.HOLD


class TestSwingPullback:

    def test_long_on_uptrend_pullback(self):
        row = pd.Series({
            "trend_day_probability": 0.65,
            "dist_swing_high_atr": 2.0,
            "dist_swing_low": 3.0,  # < pullback_zone_pts=5
            "swing_range_atr": 1.5,
            "ctx_trend_day_score": 0.65,
        })
        sig = DowTrendFractalModel().generate_signal(row)
        assert sig.type == SignalType.BUY

    def test_short_on_downtrend_pullback(self):
        row = pd.Series({
            "trend_day_probability": 0.35,
            "dist_swing_high_atr": 0.1,
            "dist_swing_low": 100.0,
            "swing_range_atr": 1.5,
            "ctx_trend_day_score": 0.35,
        })
        sig = DowTrendFractalModel().generate_signal(row)
        assert sig.type == SignalType.SELL

    def test_hold_neutral_trend(self):
        row = pd.Series({
            "trend_day_probability": 0.50,
            "dist_swing_high_atr": 0.1,
            "dist_swing_low": 5.0,
            "swing_range_atr": 1.5,
            "ctx_trend_day_score": 0.50,
        })
        sig = DowTrendFractalModel().generate_signal(row)
        assert sig.type == SignalType.HOLD


# ═══════════════════════════════════════════════════════════════════════
# CVR3 VIX FILTER
# ═══════════════════════════════════════════════════════════════════════

class TestCvr3VixFilter:

    def test_regime_calm(self):
        assert CVR3VixFilter().regime(12.0) == "calm"

    def test_regime_normal(self):
        assert CVR3VixFilter().regime(18.0) == "normal"

    def test_regime_stress(self):
        assert CVR3VixFilter().regime(27.0) == "stress"

    def test_regime_chaos(self):
        assert CVR3VixFilter().regime(35.0) == "chaos"

    def test_vwap_reversion_blocked_in_stress(self):
        f = CVR3VixFilter()
        row = pd.Series({"vix_level": 27.0})
        assert f.allows("vwap_reversion", row) is False

    def test_trend_day_rider_allowed_in_chaos(self):
        f = CVR3VixFilter()
        row = pd.Series({"vix_level": 35.0})
        assert f.allows("trend_day_rider", row) is True

    def test_size_multiplier_chaos_reduces_50pct(self):
        f = CVR3VixFilter()
        row = pd.Series({"vix_level": 35.0})
        assert f.size_multiplier("trend_day_rider", row) == 0.5

    def test_unknown_strategy_defaults_true(self):
        f = CVR3VixFilter()
        row = pd.Series({"vix_level": 18.0})
        assert f.allows("unknown_strategy", row) is True


# ═══════════════════════════════════════════════════════════════════════
# INTEGRATION SUR PARQUET REEL
# ═══════════════════════════════════════════════════════════════════════

class TestIntegrationRealDataset:

    @pytest.fixture(scope="class")
    def df(self):
        if not ES_DATASET.exists():
            pytest.skip("ES parquet absent")
        return pd.read_parquet(ES_DATASET)

    def test_all_models_run_without_crash(self, df):
        models = [
            VaFailureFadeModel(),
            MqLevelBounceModel(),
            TrendDayRiderModel(),
            OpeningRangeBreakoutModel(),
            GapFadeModel(),
            DoubleTopBottomModel(),
            PoorHighLowRetestModel(),
            DowTrendFractalModel(),
        ]
        for m in models:
            m.check_features(df)
            signals = m.run(df.head(200))
            assert len(signals) == 200, f"{m.name} len mismatch"
            # Au moins 1 type de signal doit exister (HOLD minimum)
            assert (signals["signal"] == "HOLD").sum() > 0
