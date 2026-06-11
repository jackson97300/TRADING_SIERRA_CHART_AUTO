"""Tests Phase 0 sierra_enricher_state.py."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_make_sierra_enricher_state_new():
    """Factory create fresh state si pas existant."""
    from CORE.sierra_enricher_state import make_sierra_enricher_state
    state = make_sierra_enricher_state("TEST_FRESH_NEW")
    assert state.symbol == "TEST_FRESH_NEW"
    assert state.n_bars_processed == 0


def test_sierra_state_dir_isolation():
    """SIERRA_STATE_DIR distinct de Databento STATE_DIR."""
    from CORE.sierra_enricher_state import SIERRA_STATE_DIR
    from CORE.live_enricher_state import STATE_DIR
    assert SIERRA_STATE_DIR != STATE_DIR
    assert "enricher_state_sierra" in str(SIERRA_STATE_DIR)


def test_sierra_state_path_format():
    """Path snapshot suit pattern sierra_{sym}_state.pickle."""
    from CORE.sierra_enricher_state import _sierra_state_path
    path = _sierra_state_path("NQ.c.0")
    assert "sierra_NQ_c_0_state.pickle" in str(path)


def test_validate_path_isolation_rejects_databento():
    """Defense profondeur : reject path Databento STATE_DIR."""
    from CORE.sierra_enricher_state import _validate_path_isolation
    from CORE.live_enricher_state import STATE_DIR
    bad_path = STATE_DIR / "ES_state.pickle"
    assert _validate_path_isolation(bad_path) is False


def test_save_load_roundtrip():
    """Smoke save + reload retourne state equivalent."""
    from CORE.sierra_enricher_state import (
        make_sierra_enricher_state, save_sierra_state, load_sierra_state,
    )
    state = make_sierra_enricher_state("TEST_ROUNDTRIP_SYM")
    state.n_bars_processed = 42
    assert save_sierra_state(state) is True
    loaded = load_sierra_state("TEST_ROUNDTRIP_SYM")
    assert loaded is not None
    assert loaded.symbol == "TEST_ROUNDTRIP_SYM"
    assert loaded.n_bars_processed == 42


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
