"""Tests unitaires sierra_atr_regime.AtrRegimeStreaming + derive_ib_formed_bool.

P0.A audit weekend 28/06/2026 — 3 features regime manquantes Bot 4 v2.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# Permet import depuis racine repo
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from CORE.sierra_atr_regime import (
    AtrRegimeStreaming,
    derive_ib_formed_bool,
    _ATR_Z_MIN_PERIODS,
    _ATR_Z_WINDOW_BARS,
    _STALE_FEATURE_THRESHOLD_BARS,
)


class TestAtrRegimeStreaming:
    def test_init_empty(self):
        h = AtrRegimeStreaming()
        assert h.buffer_size == 0
        assert h.consec_none == 0
        assert h.is_stale is False

    def test_update_none_returns_none(self):
        h = AtrRegimeStreaming()
        assert h.update(None) is None
        assert h.consec_none == 1

    def test_update_nan_returns_none(self):
        h = AtrRegimeStreaming()
        assert h.update(float("nan")) is None
        assert h.consec_none == 1

    def test_consec_none_reset_on_valid(self):
        h = AtrRegimeStreaming()
        h.update(None)
        h.update(None)
        assert h.consec_none == 2
        h.update(100.0)
        assert h.consec_none == 0

    def test_warm_up_returns_none(self):
        """Tant que < MIN_PERIODS bars, retourne None."""
        h = AtrRegimeStreaming()
        for _ in range(_ATR_Z_MIN_PERIODS - 1):
            r = h.update(100.0)
            assert r is None
        assert h.buffer_size == _ATR_Z_MIN_PERIODS - 1

    def test_emission_after_warm_up(self):
        """A MIN_PERIODS atteint, emission valide si variance > 0."""
        h = AtrRegimeStreaming()
        # Alimente avec valeurs variees pour avoir variance > 0
        import random
        rng = random.Random(42)
        for _ in range(_ATR_Z_MIN_PERIODS):
            h.update(100.0 + rng.uniform(-5.0, 5.0))
        # Une valeur extreme apres warm-up -> z proche d'une valeur sensible
        z = h.update(200.0)
        assert z is not None
        assert isinstance(z, float)
        assert z > 5.0, f"z=({z}) devrait etre > 5 pour valeur extreme 200 vs ~100 mean"

    def test_zero_variance_returns_none(self):
        """Variance degeneree (constantes) -> None pas crash."""
        h = AtrRegimeStreaming()
        for _ in range(_ATR_Z_MIN_PERIODS):
            h.update(100.0)  # toutes identiques
        z = h.update(100.0)
        assert z is None  # var = 0

    def test_is_stale_threshold(self):
        h = AtrRegimeStreaming()
        for _ in range(_STALE_FEATURE_THRESHOLD_BARS - 1):
            h.update(None)
        assert h.is_stale is False
        h.update(None)
        assert h.is_stale is True

    def test_buffer_cap_enforced(self):
        """Buffer ne croit pas au-dela de WINDOW_BARS."""
        h = AtrRegimeStreaming()
        for i in range(_ATR_Z_WINDOW_BARS + 100):
            h.update(100.0 + (i % 20))
        assert h.buffer_size == _ATR_Z_WINDOW_BARS

    def test_reset(self):
        h = AtrRegimeStreaming()
        for _ in range(100):
            h.update(100.0)
        assert h.buffer_size == 100
        h.reset()
        assert h.buffer_size == 0
        assert h.consec_none == 0


class TestDeriveIbFormedBool:
    def test_ib_complete_1(self):
        assert derive_ib_formed_bool({"ib_complete": 1}) == 1

    def test_ib_complete_0(self):
        assert derive_ib_formed_bool({"ib_complete": 0}) == 0

    def test_fallback_ib_range_ticks_positive(self):
        assert derive_ib_formed_bool({"ib_range_ticks": 12.5}) == 1

    def test_fallback_ib_range_ticks_zero(self):
        assert derive_ib_formed_bool({"ib_range_ticks": 0}) == 0

    def test_no_field_returns_zero(self):
        assert derive_ib_formed_bool({}) == 0

    def test_invalid_ib_complete_falls_back(self):
        """Si ib_complete non-castable, fallback ib_range_ticks."""
        assert derive_ib_formed_bool({
            "ib_complete": "BAD",
            "ib_range_ticks": 5.0,
        }) == 1

    def test_ib_complete_priority_over_range_ticks(self):
        """ib_complete prioritaire meme si ib_range_ticks present."""
        # ib_complete=0 (IB pas formee) mais ib_range_ticks > 0 (bruit)
        assert derive_ib_formed_bool({
            "ib_complete": 0,
            "ib_range_ticks": 12.5,
        }) == 0


class TestIntegrationSierraPipeline:
    """Test end-to-end : verifier que les 3 features sortent du payload enriched."""

    def test_three_features_emitted(self, tmp_path):
        # Import dans le test pour eviter cascade imports si pytest collect skip
        sys.path.insert(0, str(ROOT / "CORE"))
        from sierra_pipeline import SierraPipelineOrchestrator

        pipe = SierraPipelineOrchestrator(symbol="NQ")
        sample_bar = {
            "ts_event_ns": 1782385200000000000,
            "close": 29870.75, "price": 29870.75,
            "bar_high": 29891.25, "bar_low": 29866.5,
            "high": 29891.25, "low": 29866.5,
            "total_vol": 1000, "volume": 1000,
            "delta_bar": 50, "atr": 976.55,
            "dist_swing_high": 5.5,
            "dist_swing_low": -8.0,
            "dist_cur_vpoc": 1.5,
            "range_pos_va": 100.0,
            "ib_complete": 1,
            "ib_range_ticks": 32.0,
            "instrument_id": 1001,
        }
        enriched = pipe.enrich_bar(sample_bar)

        # P0.A — les 3 features doivent etre presentes (cle)
        assert "range_pos" in enriched, "range_pos absent du payload"
        assert "ib_formed_bool" in enriched, "ib_formed_bool absent du payload"
        assert "atr_regime_zscore_60d" in enriched, "atr_regime_zscore_60d absent"

        # Valeurs attendues
        assert enriched["range_pos"] == 1.0, f"range_pos={enriched['range_pos']}"
        assert enriched["ib_formed_bool"] == 1, f"ib_formed_bool={enriched['ib_formed_bool']}"
        # warm-up incomplet sur 1 bar -> None
        assert enriched["atr_regime_zscore_60d"] is None
