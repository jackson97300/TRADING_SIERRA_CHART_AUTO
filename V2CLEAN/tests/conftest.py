"""Fixtures pytest V2CLEAN — isolation LOGS/ obligatoire (22/04).

Raison : `CORE/logging_v2.py` cree `LOGS/` au import. Sans isolation les tests
ecriraient dans `LOGS/events/events_YYYYMMDD_v2clean.jsonl` de prod (pollution).

Fix : autouse fixture override MIA_LOG_DIR → tmp_path unique par test.
"""

import os
import pytest


@pytest.fixture(autouse=True)
def _isolate_v2_logs(tmp_path, monkeypatch):
    """Isole LOGS/ V2 par test (evite pollution LOGS/ prod)."""
    test_logs_dir = tmp_path / "LOGS"
    test_logs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MIA_LOG_DIR", str(test_logs_dir))
    # Invalider cache des loggers module-level si deja initialisees
    try:
        from CORE import logging_v2 as _lg2
        _lg2._LOGGERS.clear()
        _lg2._COMPAT_LOGGERS.clear()
        _lg2.LOG_BASE_DIR = test_logs_dir
    except Exception:
        pass
    yield
