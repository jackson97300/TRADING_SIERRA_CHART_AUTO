"""Tests EntryQualityGate — 3 conditions order flow + wall.

Findings 30/04 (n=50, 2 jours) :
- BOTH_PRO (mom + cvd aligned) : WR 50% n=20
- BOTH_CONTRA                   : WR 0% n=17 (12 SL, 0 TP) <-- catastrophe
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from CORE.entry_quality_gate import evaluate_entry_quality_gate  # noqa: E402


class TestContraMomentum:
    def test_buy_with_negative_momentum_only_no_skip_default(self):
        """Mode default BOTH_CONTRA : momentum seul contra ne skip pas."""
        bar = {"momentum_5b": -10.0, "cvd_bar_delta": 50.0, "next_wall_dist_ticks": 60.0}
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False
        assert result.contra_momentum is True

    def test_buy_with_negative_momentum_strict_mode_skip(self):
        """Mode strict : momentum seul contra suffit a skip."""
        bar = {"momentum_5b": -10.0, "cvd_bar_delta": 50.0, "next_wall_dist_ticks": 60.0}
        result = evaluate_entry_quality_gate(bar, "BUY", strict_mode=True)
        assert result.skip is True
        assert result.contra_momentum is True
        assert "STRICT" in result.skip_reason

    def test_buy_with_aligned_momentum_passes(self):
        bar = {"momentum_5b": +5.0, "cvd_bar_delta": +30.0, "next_wall_dist_ticks": 60.0}
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False


class TestContraCVDOnlyDefaultNoSkip:
    """Mode default BOTH_CONTRA : CVD seul contra ne skip pas."""

    def test_buy_with_negative_cvd_only_no_skip(self):
        bar = {"momentum_5b": +5.0, "cvd_bar_delta": -100.0, "next_wall_dist_ticks": 60.0}
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False
        assert result.contra_cvd is True


class TestWallDistance:
    def test_wall_too_close_default_no_skip(self):
        """Mode default : wall close seul ne skip pas."""
        bar = {"momentum_5b": +5.0, "cvd_bar_delta": +30.0, "next_wall_dist_ticks": 15.0}
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False
        assert result.wall_too_close is True

    def test_wall_too_close_strict_mode_skip(self):
        bar = {"momentum_5b": +5.0, "cvd_bar_delta": +30.0, "next_wall_dist_ticks": 15.0}
        result = evaluate_entry_quality_gate(bar, "BUY", strict_mode=True)
        assert result.skip is True
        assert result.wall_too_close is True

    def test_wall_in_ideal_range_passes(self):
        bar = {"momentum_5b": +5.0, "cvd_bar_delta": +30.0, "next_wall_dist_ticks": 60.0}
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False


class TestGracefulDegradation:
    def test_bot2_only_momentum_no_cvd_no_wall_passes_if_aligned(self):
        """Bot 2 V4 manque cvd_bar_delta + next_wall_dist_ticks.
        Si momentum aligned → no skip (degradation gracieuse)."""
        bar = {"momentum_5b": +5.0}  # cvd + wall absents
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False

    def test_bot2_contra_momentum_only_default_no_skip(self):
        """Mode default BOTH_CONTRA : momentum seul contra (Bot 2 manque cvd)
        ne skip pas. Logique : sans confirmation CVD, on n'a pas de signal
        clair de retournement."""
        bar = {"momentum_5b": -10.0}  # cvd + wall absents
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False
        assert result.contra_momentum is True

    def test_bot2_contra_momentum_strict_mode_skip(self):
        bar = {"momentum_5b": -10.0}
        result = evaluate_entry_quality_gate(bar, "BUY", strict_mode=True)
        assert result.skip is True

    def test_all_features_missing_no_skip(self):
        result = evaluate_entry_quality_gate({}, "BUY")
        assert result.skip is False

    def test_features_nan_no_skip(self):
        import numpy as np
        bar = {"momentum_5b": np.nan, "cvd_bar_delta": np.nan, "next_wall_dist_ticks": np.nan}
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is False


class TestBothContraDeath:
    def test_both_contra_skip(self):
        """Killer empirique : BOTH_CONTRA WR 0% n=17 (12 SL, 0 TP)."""
        bar = {"momentum_5b": -8.0, "cvd_bar_delta": -200.0, "next_wall_dist_ticks": 60.0}
        result = evaluate_entry_quality_gate(bar, "BUY")
        assert result.skip is True
        assert result.contra_momentum is True
        assert result.contra_cvd is True


class TestDisabledFlag:
    def test_disabled_no_skip_even_extreme(self):
        bar = {"momentum_5b": -10.0, "cvd_bar_delta": -200.0, "next_wall_dist_ticks": 5.0}
        result = evaluate_entry_quality_gate(bar, "BUY", enabled=False)
        assert result.skip is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
