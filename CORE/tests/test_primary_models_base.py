"""
Tests unitaires pour CORE/primary_models/base.py — MIA V2
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from CORE.primary_models.base import PrimaryModel, Signal, SignalType


class MockModel(PrimaryModel):
    name = "mock"
    def __init__(self, required=None, signal_fn=None, context_valid=True):
        self._required = required or ["feat_a"]
        self._signal_fn = signal_fn or (lambda row, ctx: Signal(type=SignalType.HOLD))
        self._context_valid = context_valid

    def required_features(self):
        return self._required

    def generate_signal(self, row, context=None):
        return self._signal_fn(row, context)

    def validate_context(self, context):
        return self._context_valid


class TestPrimaryModelBase:

    def test_check_features_missing_raises(self):
        """Test : feature manquante → ValueError avec nom explicite."""
        model = MockModel(required=["feat_a", "feat_missing"])
        df = pd.DataFrame({"feat_a": [1, 2, 3], "ts": [1, 2, 3]})
        with pytest.raises(ValueError, match="feat_missing"):
            model.check_features(df)

    def test_validate_context_veto_in_run(self):
        """Test : validate_context=False → aucun signal BUY/SELL genere."""
        model = MockModel(
            required=["feat_a"],
            signal_fn=lambda row, ctx: Signal(type=SignalType.BUY, sl_ticks=20, tp_ticks=36),
            context_valid=False,
        )
        df = pd.DataFrame({"feat_a": [1, 2, 3], "ts": [1, 2, 3]})
        result = model.run(df, context={})
        assert (result["signal"] == "HOLD").all(), \
            "validate_context=False should force all signals to HOLD"

    def test_meta_serialized_in_run_output(self):
        """Test : signal.meta est bien propage dans le DataFrame de sortie."""
        model = MockModel(
            required=["feat_a"],
            signal_fn=lambda row, ctx: Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                meta={"confluence_count": 3, "regime": "range"}
            ),
            context_valid=True,
        )
        df = pd.DataFrame({"feat_a": [1, 2], "ts": [1, 2]})
        result = model.run(df)
        assert "meta" in result.columns, "meta column should be in run() output"
        assert result.iloc[0]["meta"] == {"confluence_count": 3, "regime": "range"}
