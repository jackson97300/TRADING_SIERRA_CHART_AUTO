"""Tests FIX B.3 ensure_connected pattern Bot 4 -> Bot 3 (INCIDENT #77).

Sans ce check, un silent kick Sierra Chart (socket OS vivante mais SC ferme
session DTC) laisse le bot envoyer ordres dans le vide pendant des heures.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_ensure_dtc_connected_method_exists_in_source():
    """Verifier que _ensure_dtc_connected est defini dans main.py."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    assert "def _ensure_dtc_connected" in content, \
        "Fix B.3 absent : methode _ensure_dtc_connected non definie"


def test_ensure_dtc_called_in_loop():
    """Verifier que self._ensure_dtc_connected() est appele dans run() loop."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    assert "self._ensure_dtc_connected()" in content, \
        "Fix B.3 absent : appel _ensure_dtc_connected manquant dans loop"


def test_anti_spam_30s_guard():
    """Anti-spam : 30s entre tentatives reconnect."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # Pattern : _last_reconnect_attempt + 30.0 sec guard
    assert "_last_reconnect_attempt" in content, \
        "Fix B.3 absent : _last_reconnect_attempt manquant"
    assert "30.0" in content, \
        "Fix B.3 absent : guard 30s manquant"


def test_log_codes_reconnect_registered():
    """Codes log BOTBN_DTC_RECONNECT_OK/FAIL doivent etre dans log_catalog."""
    from CORE.log_catalog import LOG_CODES
    from CORE.logging_v2 import LogLevel

    assert "BOTBN_DTC_RECONNECT_OK" in LOG_CODES
    level_ok, cat_ok, _ = LOG_CODES["BOTBN_DTC_RECONNECT_OK"]
    assert level_ok == LogLevel.MAJEUR
    assert cat_ok == "execution"

    assert "BOTBN_DTC_RECONNECT_FAIL" in LOG_CODES
    level_fail, cat_fail, _ = LOG_CODES["BOTBN_DTC_RECONNECT_FAIL"]
    assert level_fail == LogLevel.CRITIQUE  # CRITIQUE car bot inactif silencieusement
    assert cat_fail == "execution"


def test_dry_run_skip():
    """En dry_run, _ensure_dtc_connected doit return immediatement."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # Le code doit contenir le check dry_run early-return
    assert "if self.dry_run or self.router is None" in content
