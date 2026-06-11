"""Tests Phase 0 log_catalog 61 codes Sierra Port."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# 13 modules x 3 codes (OK/FAIL/DEGRADED) = 39 codes
EXPECTED_MODULES = (
    "FOOTPRINT_BUILDER", "LOT1_TRADES", "LOT2_BIG_V2", "LOT3_CLUSTER_V2",
    "LOT4_ABSORB", "LOT5_TRAPPED", "LOT6_DELTA_DIV_EXT",
    "PHASE_B_HELPERS", "PHASE_B_PLUS_LONG", "GAME_CHANGERS",
    "RVOL", "ROLLING_FEATURES", "EDGE_ZONES", "COLOR_BARS",
    "INTERMARKET", "BN_COMPOSITES",
)


def test_all_modules_have_3_codes():
    """Chaque module a OK/FAIL/DEGRADED dans log_catalog."""
    from CORE.log_catalog import LOG_CODES
    for module in EXPECTED_MODULES:
        for suffix in ("OK", "FAIL", "DEGRADED"):
            code = f"SIERRA_PORT_{module}_{suffix}"
            assert code in LOG_CODES, f"Missing code: {code}"


def test_meta_codes_present():
    """13 codes meta state/format/harness present."""
    from CORE.log_catalog import LOG_CODES
    meta_codes = (
        "SIERRA_STATE_SNAPSHOT_OK",
        "SIERRA_STATE_SNAPSHOT_FAIL",
        "SIERRA_STATE_LOAD_FAIL",
        "SIERRA_STATE_SCHEMA_MISMATCH",
        "SIERRA_STATE_COLLISION_DETECTED",
        "SIERRA_FORMAT_ADAPTER_OK",
        "SIERRA_FORMAT_ADAPTER_DROPPED",
        "SIERRA_FORMAT_TS_INCONSISTENT",
        "SIERRA_VAP_TO_CELLS_OK",
        "SIERRA_VAP_TO_CELLS_EMPTY",
        "SIERRA_INTERMARKET_PARTNER_MISSING",
        "SIERRA_INTERMARKET_PARTNER_STALE",
        "SIERRA_HARNESS_DRIFT_DETECTED",
    )
    for code in meta_codes:
        assert code in LOG_CODES, f"Missing meta code: {code}"


def test_critical_codes_level():
    """Codes CRITIQUE : collision + snapshot fail."""
    from CORE.log_catalog import LOG_CODES, LogLevel
    assert LOG_CODES["SIERRA_STATE_COLLISION_DETECTED"][0] == LogLevel.CRITIQUE
    assert LOG_CODES["SIERRA_STATE_SNAPSHOT_FAIL"][0] == LogLevel.CRITIQUE


def test_majeur_codes_level():
    """Codes MAJEUR : FAIL + schema mismatch + drift."""
    from CORE.log_catalog import LOG_CODES, LogLevel
    assert LOG_CODES["SIERRA_PORT_FOOTPRINT_BUILDER_FAIL"][0] == LogLevel.MAJEUR
    assert LOG_CODES["SIERRA_STATE_SCHEMA_MISMATCH"][0] == LogLevel.MAJEUR
    assert LOG_CODES["SIERRA_HARNESS_DRIFT_DETECTED"][0] == LogLevel.MAJEUR


def test_alerte_codes_level():
    """Codes ALERTE : DEGRADED + ADAPTER_DROPPED + PARTNER_MISSING."""
    from CORE.log_catalog import LOG_CODES, LogLevel
    assert LOG_CODES["SIERRA_PORT_FOOTPRINT_BUILDER_DEGRADED"][0] == LogLevel.ALERTE
    assert LOG_CODES["SIERRA_FORMAT_ADAPTER_DROPPED"][0] == LogLevel.ALERTE
    assert LOG_CODES["SIERRA_INTERMARKET_PARTNER_MISSING"][0] == LogLevel.ALERTE


def test_total_sierra_codes_count():
    """Total >= 52 codes Sierra (16 modules x 3 + 13 meta)."""
    from CORE.log_catalog import LOG_CODES
    sierra_codes = [k for k in LOG_CODES if k.startswith((
        "SIERRA_PORT_", "SIERRA_STATE_", "SIERRA_FORMAT_",
        "SIERRA_VAP_", "SIERRA_INTERMARKET_", "SIERRA_HARNESS_",
    ))]
    assert len(sierra_codes) >= 52, f"Only {len(sierra_codes)} codes"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
