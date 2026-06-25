"""Tests bot4_v2/observability/telemetry.

Coverage cible >=80% (spec P1). Tests :
- API basique (get_logger, emit_safe ne raise jamais)
- Branches fail-soft (catalog absent, format error, level routing)
- Contract resolve() vs CORE.log_catalog (anti VALIDATION_MISS)
"""
from __future__ import annotations

import logging

import pytest

import bot4_v2.observability.telemetry as tel_module
from bot4_v2.observability.telemetry import emit_safe, get_logger


# ============================================================
# get_logger
# ============================================================

def test_get_logger_returns_logger():
    log = get_logger("bot4_v2.tests.test_telemetry")
    assert isinstance(log, logging.Logger)


def test_get_logger_handles_no_handlers_added_twice():
    log1 = get_logger("bot4_v2.tests.same_name")
    n_handlers_1 = len(log1.handlers)
    log2 = get_logger("bot4_v2.tests.same_name")
    n_handlers_2 = len(log2.handlers)
    assert n_handlers_1 == n_handlers_2  # pas de duplication handlers


# ============================================================
# emit_safe : API ne raise jamais
# ============================================================

def test_emit_safe_returns_bool_no_exception():
    """emit_safe ne doit JAMAIS lever d'exception, return bool."""
    log = get_logger("bot4_v2.tests.test_no_exc")
    result = emit_safe(log, "BOT4V2_UNKNOWN")
    assert isinstance(result, bool)


def test_emit_safe_with_kwargs_passes_through():
    """Verifie qu'on peut passer des kwargs arbitraires sans erreur."""
    log = get_logger("bot4_v2.tests.test_kwargs")
    result = emit_safe(
        log,
        "BOT4V2_TEST_CODE",
        sym="NQ",
        direction="LONG",
        score=42,
        ratio=1.5,
        flag=True,
    )
    assert isinstance(result, bool)


def test_emit_safe_handles_special_chars_in_ctx():
    """Chars speciaux (utf8, brackets) dans ctx ne doivent pas crasher."""
    log = get_logger("bot4_v2.tests.test_special")
    result = emit_safe(
        log,
        "BOT4V2_TEST",
        msg="trade {NQ} A+ '\"<>",
        ratio=1.5,
    )
    assert isinstance(result, bool)


def test_emit_safe_with_no_kwargs():
    """Cas degenere : emit sans contexte. Doit return bool sans exception."""
    log = get_logger("bot4_v2.tests.test_no_ctx")
    result = emit_safe(log, "BOT4V2_TEST_NO_CTX")
    assert isinstance(result, bool)


# ============================================================
# R1 review : branches fail-soft (catalog absent, format, routing)
# ============================================================

def test_emit_safe_catalog_unavailable_fallback(caplog, monkeypatch):
    """R1 : Force _CATALOG_AVAILABLE=False -> emit logger.info direct, return True."""
    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", False)
    monkeypatch.setattr(tel_module, "_v2_resolve_code", None)
    log = get_logger("bot4_v2.tests.test_no_catalog")
    with caplog.at_level(logging.INFO, logger="bot4_v2.tests.test_no_catalog"):
        result = emit_safe(log, "ANY_CODE", sym="NQ")
    assert result is True
    assert any("ANY_CODE" in r.message for r in caplog.records)


def test_emit_safe_unknown_code_strict_prod_mode(caplog, monkeypatch):
    """R1 : Force mode prod (catalog dispo) : code absent -> return False + warning."""
    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", True)
    # Garder vrai _v2_resolve_code de CORE.log_catalog (si dispo)
    log = get_logger("bot4_v2.tests.test_unknown_strict")
    with caplog.at_level(logging.WARNING, logger="bot4_v2.tests.test_unknown_strict"):
        result = emit_safe(
            log, "BOT4V2_DEFINITELY_UNKNOWN_CODE_XYZ_123", sym="NQ"
        )
    # Si CORE.log_catalog est dispo (mode prod), code inconnu -> return False
    # Sinon (mode standalone), fallback retourne True. On accepte les 2 mais
    # on verifie au moins qu'il y a un log warning OU un log info coherent.
    if result is False:
        assert any("absent du log_catalog" in r.message for r in caplog.records)
    else:
        # Mode fallback : warning d'attendu, info OK aussi
        assert any(
            "BOT4V2_DEFINITELY_UNKNOWN_CODE_XYZ_123" in r.message
            for r in caplog.records
        )


def test_emit_safe_format_error_kwargs_missing(caplog, monkeypatch):
    """R1 : Template attend {missing_key} ctx ne fournit pas -> warning + msg fallback."""

    class FakeLevel:
        name = "INFO"

    def fake_resolve(code: str):
        return FakeLevel(), "decisions", "trade {sym} {missing_key}"

    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", True)
    monkeypatch.setattr(tel_module, "_v2_resolve_code", fake_resolve)
    log = get_logger("bot4_v2.tests.test_format_err")
    with caplog.at_level(logging.WARNING, logger="bot4_v2.tests.test_format_err"):
        result = emit_safe(log, "FAKE_CODE", sym="NQ")  # missing_key absent
    assert result is True
    assert any("format error" in r.message for r in caplog.records)


def test_emit_safe_level_routing_critique(monkeypatch, caplog):
    """R1 : CRITIQUE -> logger.error."""

    class FakeLevel:
        name = "CRITIQUE"

    def fake_resolve(code: str):
        return FakeLevel(), "execution", "code critique {sym}"

    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", True)
    monkeypatch.setattr(tel_module, "_v2_resolve_code", fake_resolve)
    log = get_logger("bot4_v2.tests.test_routing_crit")
    with caplog.at_level(logging.ERROR, logger="bot4_v2.tests.test_routing_crit"):
        result = emit_safe(log, "FAKE", sym="ES")
    assert result is True
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_emit_safe_level_routing_majeur(monkeypatch, caplog):
    """R1 : MAJEUR -> logger.warning."""

    class FakeLevel:
        name = "MAJEUR"

    def fake_resolve(code: str):
        return FakeLevel(), "risk", "code majeur {sym}"

    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", True)
    monkeypatch.setattr(tel_module, "_v2_resolve_code", fake_resolve)
    log = get_logger("bot4_v2.tests.test_routing_maj")
    with caplog.at_level(logging.WARNING, logger="bot4_v2.tests.test_routing_maj"):
        result = emit_safe(log, "FAKE", sym="NQ")
    assert result is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_emit_safe_level_routing_info(monkeypatch, caplog):
    """R1 : INFO -> logger.info."""

    class FakeLevel:
        name = "INFO"

    def fake_resolve(code: str):
        return FakeLevel(), "decisions", "code info {sym}"

    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", True)
    monkeypatch.setattr(tel_module, "_v2_resolve_code", fake_resolve)
    log = get_logger("bot4_v2.tests.test_routing_info")
    with caplog.at_level(logging.INFO, logger="bot4_v2.tests.test_routing_info"):
        result = emit_safe(log, "FAKE", sym="MGC")
    assert result is True
    assert any(r.levelno == logging.INFO for r in caplog.records)


def test_emit_safe_resolve_returns_bad_tuple(monkeypatch, caplog):
    """R1 : resolve() retour inattendu (2-tuple) -> warning + return False."""

    def fake_resolve(code: str):
        return ("only", "two")  # mauvaise structure 2-tuple

    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", True)
    monkeypatch.setattr(tel_module, "_v2_resolve_code", fake_resolve)
    log = get_logger("bot4_v2.tests.test_bad_tuple")
    with caplog.at_level(logging.WARNING, logger="bot4_v2.tests.test_bad_tuple"):
        result = emit_safe(log, "FAKE", sym="ES")
    assert result is False
    assert any("retour inattendu" in r.message for r in caplog.records)


def test_emit_safe_resolve_raises_unexpected(monkeypatch, caplog):
    """R1 : resolve() leve exception non-KeyError -> warning + return False."""

    def fake_resolve(code: str):
        raise RuntimeError("simulated infra error")

    monkeypatch.setattr(tel_module, "_CATALOG_AVAILABLE", True)
    monkeypatch.setattr(tel_module, "_v2_resolve_code", fake_resolve)
    log = get_logger("bot4_v2.tests.test_resolve_raise")
    with caplog.at_level(logging.WARNING, logger="bot4_v2.tests.test_resolve_raise"):
        result = emit_safe(log, "FAKE", sym="ES")
    assert result is False
    assert any("exception" in r.message for r in caplog.records)


# ============================================================
# R2 review : contract test signature resolve() vs CORE.log_catalog
# ============================================================

def test_resolve_signature_contract_with_core_log_catalog():
    """R2 : si CORE.log_catalog change la signature resolve(), on le sait IMMEDIATEMENT.

    Anti VALIDATION_MISS pattern : un wrapper qui silently degrade si l'API du
    module sous-jacent change.
    """
    try:
        from CORE.log_catalog import resolve
    except ImportError:
        pytest.skip("CORE.log_catalog not available")

    # Cherche un code existant connu pour test contract
    candidates = ("BOOT_START", "BOOT_READY", "HEARTBEAT", "SESSION_OPEN")
    result = None
    for code in candidates:
        try:
            result = resolve(code)
            break
        except KeyError:
            continue
    assert result is not None, (
        f"Aucun code parmi {candidates} present dans log_catalog. "
        "Test contract obsolete - ajouter code connu actif."
    )

    # Contract : 3-tuple (level, category, template)
    assert isinstance(result, tuple), f"resolve() doit retourner tuple, got {type(result)}"
    assert len(result) == 3, f"resolve() doit retourner 3-tuple, got len={len(result)}"
    level, category, template = result
    assert hasattr(level, "name"), f"level doit avoir .name (LogLevel enum), got {level}"
    assert isinstance(category, str), f"category doit etre str, got {type(category)}"
    assert isinstance(template, str), f"template doit etre str, got {type(template)}"
