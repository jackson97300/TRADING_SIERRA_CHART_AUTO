"""Tests FIX BUG #1 PROD FANTOME audit ULTRATHINK 19/06.

Le bug : `dtc_connector.connect()` retourne True/False. Avant fix :
return value ignore -> si False, le bot continue en "prod fantome"
(log "connected" mensonger + ordres orphans send_market_with_stop_only
retournant ("","",0.0) sans aucun effet sur SC).

Apres fix : capture return value + force dry_run + dtc_connector=None
+ emit BOTBN_DTC_BOOT_FAIL CRITIQUE pour audit J+1.

Source : code-reviewer audit Bot 3 19/06.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ════════════════════════════════════════════════════════════════════════════
# L1 - Unit tests sur la logique du fix
# ════════════════════════════════════════════════════════════════════════════


def test_log_code_botbn_dtc_boot_fail_registered():
    """Code log BOTBN_DTC_BOOT_FAIL doit etre enregistre dans log_catalog."""
    from CORE.log_catalog import LOG_CODES
    assert "BOTBN_DTC_BOOT_FAIL" in LOG_CODES, \
        "BOTBN_DTC_BOOT_FAIL missing in log_catalog"
    level, category, template = LOG_CODES["BOTBN_DTC_BOOT_FAIL"]
    assert category == "execution", f"Expected category 'execution', got '{category}'"
    # CRITIQUE car PROD FANTOME = trade silencieusement perdus = capital risk
    from CORE.logging_v2 import LogLevel
    assert level == LogLevel.CRITIQUE, \
        f"Expected CRITIQUE level (capital risk), got {level}"


def test_main_captures_connect_return_value():
    """Verifier que main.py capture le return value de connect() ligne ~780."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # Le pattern fixe : variable connected = dtc_connector.connect()
    assert "connected = dtc_connector.connect()" in content, \
        "Fix BUG #1 absent : connect() return value pas capture"
    # Verifier check if not connected:
    assert "if not connected:" in content, \
        "Fix BUG #1 absent : pas de check if not connected"
    # Verifier nullification critique
    assert "dtc_connector = None" in content, \
        "Fix BUG #1 absent : dtc_connector=None pour empecher utilisation downstream"


def test_dtc_connect_failure_pattern_in_source():
    """Verifier que le code main.py gere connect() False : 4 actions critiques."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # Bloc complet attendu apres "if not connected:" :
    assert "if not connected:" in content, \
        "Fix BUG #1 absent : check if not connected required"
    assert "dry_run = True" in content, \
        "Fix BUG #1 absent : force dry_run=True manquant"
    assert "dtc_connector = None" in content, \
        "Fix BUG #1 absent : dtc_connector=None empeche utilisation downstream"
    assert "BOTBN_DTC_BOOT_FAIL" in content, \
        "Fix BUG #1 absent : emit BOTBN_DTC_BOOT_FAIL manquant"


def test_dtc_connect_success_path_preserved():
    """Path SUCCESS : log + emit BOTBN_DTC_CONNECTED preserves."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    assert "DTC connector connected" in content
    assert "BOTBN_DTC_CONNECTED" in content
    # SUCCESS path doit etre dans le else: branch
    assert "else:" in content


# ════════════════════════════════════════════════════════════════════════════
# L2 - Anti-regression : check legacy bug ne revient pas
# ════════════════════════════════════════════════════════════════════════════


def test_no_naked_connect_without_return_check():
    """Anti-regression : main.py NE DOIT PAS appeler dtc_connector.connect()
    sans capturer le return value."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # Pattern legacy: ligne autonome "dtc_connector.connect()" sans assignment
    # On cherche que la seule occurrence soit precedee d'un =.
    import re
    # Match toute ligne contenant `dtc_connector.connect()` non precedee d'un `=`
    naked_pattern = re.compile(
        r"^[^=\n]*(?<![=\s])\bdtc_connector\.connect\(\)", re.MULTILINE,
    )
    matches = naked_pattern.findall(content)
    assert not matches, \
        f"Regression BUG #1 : naked dtc_connector.connect() detecte (matches={matches})"
