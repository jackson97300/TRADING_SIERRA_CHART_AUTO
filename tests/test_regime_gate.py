"""Tests RegimeGate — skip empirique categories LOSERS.

Findings 30/04 (n=50, 2 jours) :
- profile_shape=0 (D Range) : mPnL -19.4t → SKIP
- day_type=1 (Normal)       : mPnL -19.6t → SKIP
- profile_shape=3 (B Breakout) : mPnL +18.2t → PASS
- day_type=2 (NormVar)      : mPnL +7.6t → PASS
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from CORE.regime_gate import evaluate_regime_gate  # noqa: E402


class TestRegimeGateLosers:
    def test_skip_profile_shape_d_range(self):
        bar = {"profile_shape": 0, "day_type": 2, "open_type": 7}
        result = evaluate_regime_gate(bar, "BUY")
        assert result.skip is True
        assert "PROFILE_SHAPE_0" in result.skip_reason

    def test_skip_day_type_normal(self):
        bar = {"profile_shape": 3, "day_type": 1, "open_type": 0}
        result = evaluate_regime_gate(bar, "BUY")
        assert result.skip is True
        assert "DAY_TYPE_1" in result.skip_reason

    def test_pass_profile_shape_breakout(self):
        bar = {"profile_shape": 3, "day_type": 2, "open_type": 0}
        result = evaluate_regime_gate(bar, "BUY")
        assert result.skip is False

    def test_pass_normvar(self):
        bar = {"profile_shape": 2, "day_type": 2, "open_type": 7}
        result = evaluate_regime_gate(bar, "SELL")
        assert result.skip is False


class TestRegimeGateEdgeCases:
    def test_disabled_no_skip_even_loser(self):
        bar = {"profile_shape": 0, "day_type": 1}
        result = evaluate_regime_gate(bar, "BUY", enabled=False)
        assert result.skip is False

    def test_features_missing_no_skip(self):
        result = evaluate_regime_gate({}, "BUY")
        assert result.skip is False

    def test_features_nan_no_skip(self):
        import numpy as np
        bar = {"profile_shape": np.nan, "day_type": np.nan}
        result = evaluate_regime_gate(bar, "BUY")
        assert result.skip is False

    def test_observability_fields_set(self):
        bar = {"profile_shape": 3, "day_type": 2, "open_type": 0}
        result = evaluate_regime_gate(bar, "BUY")
        assert result.profile_shape == 3
        assert result.day_type == 2
        assert result.open_type == 0


class TestRegimeGateRealCase:
    def test_bot1_es_long_profile_2_passe(self):
        """Bar Bot 1 reelle vue 30/04 : profile_shape=2 (b bearish), day_type=2.
        Pas dans LOSERS → PASS. Verifie que le filtre n'est pas trop large."""
        bar = {
            "profile_shape": 2,    # b bearish — pas dans LOSERS (mais n trop petit)
            "day_type": 2,         # NormVar OK
            "open_type": 0,
        }
        result = evaluate_regime_gate(bar, "BUY")
        # Pas dans les 2 catégories LOSERS → PASS
        assert result.skip is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
