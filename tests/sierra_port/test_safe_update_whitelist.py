"""Tests Phase 0 _safe_update whitelist (B3+B5 BN + game_changers placeholders)."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_whitelist_contains_bn_score():
    """B3 - bn_score_* dans whitelist."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    wl = SierraPipelineOrchestrator.SIERRA_ZERO_NEVER_CALCULATED
    assert "bn_score_raw" in wl
    assert "bn_score_bull" in wl
    assert "bn_score_bear" in wl


def test_whitelist_contains_bn_pressure():
    """B3 - bn_pressure_* dans whitelist."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    wl = SierraPipelineOrchestrator.SIERRA_ZERO_NEVER_CALCULATED
    assert "bn_pressure_ask" in wl
    assert "bn_pressure_bid" in wl


def test_whitelist_contains_game_changers():
    """B5 - trend_day_probability + open_direction dans whitelist."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    wl = SierraPipelineOrchestrator.SIERRA_ZERO_NEVER_CALCULATED
    assert "trend_day_probability" in wl
    assert "open_direction" in wl


def test_whitelist_override_zero_to_python():
    """Whitelist override : Sierra=0.0 + Python=valeur -> Python wins."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    enriched = {"bn_score_raw": 0.0}
    phase3_feats = {"bn_score_raw": 0.42}
    SierraPipelineOrchestrator._safe_update(enriched, phase3_feats)
    assert enriched["bn_score_raw"] == 0.42


def test_whitelist_preserves_sierra_if_python_nan():
    """Whitelist NE override pas si Python retourne NaN."""
    import math
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    enriched = {"bn_score_raw": 0.0}
    phase3_feats = {"bn_score_raw": math.nan}
    SierraPipelineOrchestrator._safe_update(enriched, phase3_feats)
    # Phase 3 NaN + Sierra existant (0.0) = garde Sierra
    assert enriched["bn_score_raw"] == 0.0


def test_standard_update_for_non_whitelisted():
    """Features pas dans whitelist : politique standard."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    enriched = {"open_type": 7}
    phase3_feats = {"open_type": 8}  # Python ecrase
    SierraPipelineOrchestrator._safe_update(enriched, phase3_feats)
    assert enriched["open_type"] == 8


def test_standard_preserves_sierra_if_python_none():
    """Politique standard : Sierra preserve si Phase 3 None."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator
    enriched = {"vix_level": 20.5}
    phase3_feats = {"vix_level": None}
    SierraPipelineOrchestrator._safe_update(enriched, phase3_feats)
    # Sierra existant preserve
    assert enriched["vix_level"] == 20.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
