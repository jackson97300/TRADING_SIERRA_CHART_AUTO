"""Tests bot4_v2/observability/discord_alerts."""
from __future__ import annotations

import json
import logging
from io import BytesIO
from typing import Optional

import pytest

from bot4_v2.observability.discord_alerts import (
    DiscordAlerter,
    DiscordAlertHandler,
    DiscordAlertSettings,
    install_handler,
    uninstall_handler,
)


# ============================================================
# Stubs urlopen
# ============================================================


class FakeResponse:
    """Stub HTTPResponse minimal."""

    def __init__(self, status: int = 204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def getcode(self):
        return self.status


def _make_opener(success: bool = True, status: int = 204,
                  raise_exc: Optional[Exception] = None):
    """Build fake url_opener."""
    calls = []

    def opener(request, timeout=None):
        calls.append({
            "url": request.full_url,
            "data": request.data,
            "timeout": timeout,
        })
        if raise_exc:
            raise raise_exc
        if not success:
            return FakeResponse(status=status)
        return FakeResponse(status=status)

    opener.calls = calls
    return opener


# ============================================================
# Settings validation
# ============================================================


def test_settings_defaults():
    s = DiscordAlertSettings()
    assert s.throttle_sec == 60.0
    assert s.timeout_sec == 5.0
    assert s.mention_at_here is True
    assert s.enabled is True


def test_settings_throttle_must_be_nonneg():
    with pytest.raises(ValueError, match="throttle_sec"):
        DiscordAlertSettings(throttle_sec=-1)


def test_settings_timeout_must_be_positive():
    with pytest.raises(ValueError, match="timeout_sec"):
        DiscordAlertSettings(timeout_sec=0)


def test_settings_max_chars_must_be_positive():
    with pytest.raises(ValueError, match="max_message_chars"):
        DiscordAlertSettings(max_message_chars=0)


def test_settings_frozen():
    from dataclasses import FrozenInstanceError
    s = DiscordAlertSettings()
    with pytest.raises(FrozenInstanceError):
        s.throttle_sec = 30  # type: ignore


# ============================================================
# DiscordAlerter init + enabled
# ============================================================


def test_alerter_disabled_if_no_webhook():
    alerter = DiscordAlerter(webhook_url=None)
    assert alerter.enabled is False


def test_alerter_disabled_if_empty_webhook():
    alerter = DiscordAlerter(webhook_url="")
    assert alerter.enabled is False


def test_alerter_disabled_via_settings():
    alerter = DiscordAlerter(
        webhook_url="https://example.com/hook",
        settings=DiscordAlertSettings(enabled=False),
    )
    assert alerter.enabled is False


def test_alerter_enabled_with_url():
    alerter = DiscordAlerter(webhook_url="https://example.com/hook")
    assert alerter.enabled is True


# ============================================================
# send_alert : envoi reussi
# ============================================================


def test_send_alert_success():
    opener = _make_opener(success=True, status=204)
    alerter = DiscordAlerter(
        webhook_url="https://example.com/hook",
        url_opener=opener,
    )
    ok = alerter.send_alert(
        code="BOT4V2_ROUTER_BRACKET_NAKED",
        msg="Test naked",
        ctx={"sym": "NQ"},
    )
    assert ok is True
    assert len(opener.calls) == 1
    assert opener.calls[0]["url"] == "https://example.com/hook"
    # Verify payload contient code + msg
    body = json.loads(opener.calls[0]["data"].decode("utf-8"))
    assert "content" in body
    assert "BOT4V2_ROUTER_BRACKET_NAKED" in body["content"]
    assert "Test naked" in body["content"]


def test_send_alert_disabled_returns_false():
    alerter = DiscordAlerter(webhook_url=None)
    ok = alerter.send_alert(code="X", msg="test")
    assert ok is False
    assert alerter.stats["n_sent"] == 0


def test_send_alert_increments_stats():
    opener = _make_opener(success=True, status=200)
    alerter = DiscordAlerter(
        webhook_url="https://x", url_opener=opener,
    )
    alerter.send_alert(code="A", msg="m1", now=100.0)
    alerter.send_alert(code="B", msg="m2", now=200.0)
    assert alerter.stats["n_sent"] == 2


# ============================================================
# send_alert : throttle
# ============================================================


def test_send_alert_throttles_within_window():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(
        webhook_url="https://x", url_opener=opener,
        settings=DiscordAlertSettings(throttle_sec=60.0),
    )
    alerter.send_alert(code="SPAM", msg="1", now=100.0)
    alerter.send_alert(code="SPAM", msg="2", now=110.0)
    alerter.send_alert(code="SPAM", msg="3", now=159.0)
    assert alerter.stats["n_sent"] == 1
    assert alerter.stats["n_throttled"] == 2
    assert len(opener.calls) == 1


def test_send_alert_passes_throttle_after_window():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(
        webhook_url="https://x", url_opener=opener,
        settings=DiscordAlertSettings(throttle_sec=60.0),
    )
    alerter.send_alert(code="X", msg="1", now=100.0)
    alerter.send_alert(code="X", msg="2", now=161.0)  # 61s > 60
    assert alerter.stats["n_sent"] == 2


def test_send_alert_throttle_per_code_independent():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(
        webhook_url="https://x", url_opener=opener,
        settings=DiscordAlertSettings(throttle_sec=60.0),
    )
    alerter.send_alert(code="A", msg="1", now=100.0)
    alerter.send_alert(code="B", msg="2", now=110.0)  # autre code
    assert alerter.stats["n_sent"] == 2
    assert alerter.stats["n_throttled"] == 0


# ============================================================
# send_alert : fail-soft
# ============================================================


def test_send_alert_http_error_no_crash():
    import urllib.error
    opener = _make_opener(
        raise_exc=urllib.error.HTTPError(
            url="https://x", code=500, msg="server error",
            hdrs=None, fp=None,  # type: ignore
        ),
    )
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    ok = alerter.send_alert(code="X", msg="m")
    assert ok is False
    assert alerter.stats["n_failed"] == 1


def test_send_alert_network_error_no_crash():
    import urllib.error
    opener = _make_opener(raise_exc=urllib.error.URLError("no DNS"))
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    ok = alerter.send_alert(code="X", msg="m")
    assert ok is False
    assert alerter.stats["n_failed"] == 1


def test_send_alert_timeout_no_crash():
    opener = _make_opener(raise_exc=TimeoutError("timeout"))
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    ok = alerter.send_alert(code="X", msg="m")
    assert ok is False


def test_send_alert_unexpected_exception_no_crash():
    """Defense en profondeur : exception inattendue -> fail-soft."""
    opener = _make_opener(raise_exc=KeyError("totally unexpected"))
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    ok = alerter.send_alert(code="X", msg="m")
    assert ok is False
    assert alerter.stats["n_failed"] == 1


def test_send_alert_http_4xx_returns_false():
    opener = _make_opener(success=True, status=400)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    ok = alerter.send_alert(code="X", msg="m")
    assert ok is False
    assert alerter.stats["n_failed"] == 1


# ============================================================
# Message formatting
# ============================================================


def test_send_alert_truncates_long_message():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(
        webhook_url="https://x", url_opener=opener,
        settings=DiscordAlertSettings(max_message_chars=100),
    )
    alerter.send_alert(code="X", msg="A" * 200)
    body = json.loads(opener.calls[0]["data"].decode("utf-8"))
    assert len(body["content"]) <= 100
    assert "truncated" in body["content"]


def test_send_alert_no_mention_if_disabled():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(
        webhook_url="https://x", url_opener=opener,
        settings=DiscordAlertSettings(mention_at_here=False),
    )
    alerter.send_alert(code="X", msg="m")
    body = json.loads(opener.calls[0]["data"].decode("utf-8"))
    assert "@here" not in body["content"]


def test_send_alert_mention_at_here_default():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    alerter.send_alert(code="X", msg="m")
    body = json.loads(opener.calls[0]["data"].decode("utf-8"))
    assert "@here" in body["content"]


def test_send_alert_includes_ctx_json():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    alerter.send_alert(
        code="X", msg="m",
        ctx={"sym": "NQ", "parent_cid": "P_123"},
    )
    body = json.loads(opener.calls[0]["data"].decode("utf-8"))
    assert "NQ" in body["content"]
    assert "P_123" in body["content"]


# ============================================================
# DiscordAlertHandler integration
# ============================================================


def test_handler_dispatches_critical_record():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    handler = DiscordAlertHandler(alerter, min_level=logging.CRITICAL)
    record = logging.LogRecord(
        name="test", level=logging.CRITICAL, pathname="x.py", lineno=1,
        msg="[BOT4V2_X] critical thing happened", args=None, exc_info=None,
    )
    handler.emit(record)
    assert alerter.stats["n_sent"] == 1


def test_handler_filters_info_records():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    handler = DiscordAlertHandler(alerter, min_level=logging.CRITICAL)
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="x.py", lineno=1,
        msg="just info", args=None, exc_info=None,
    )
    handler.emit(record)
    assert alerter.stats["n_sent"] == 0


def test_handler_extracts_code_from_bracket_msg():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    handler = DiscordAlertHandler(alerter, min_level=logging.CRITICAL)
    record = logging.LogRecord(
        name="x", level=logging.CRITICAL, pathname="x.py", lineno=1,
        msg="[BOT4V2_KILL_SWITCH] consecutive_exc=5", args=None, exc_info=None,
    )
    handler.emit(record)
    body = json.loads(opener.calls[0]["data"].decode("utf-8"))
    assert "BOT4V2_KILL_SWITCH" in body["content"]


def test_handler_does_not_crash_on_exception():
    """Defense en profondeur : alerter.send_alert raise -> handler.emit OK."""

    class CrashingAlerter:
        def send_alert(self, **kw):
            raise RuntimeError("simulated crash")

    handler = DiscordAlertHandler(CrashingAlerter(), min_level=logging.CRITICAL)  # type: ignore
    record = logging.LogRecord(
        name="x", level=logging.CRITICAL, pathname="x.py", lineno=1,
        msg="m", args=None, exc_info=None,
    )
    # Pas de raise propagated
    handler.emit(record)


# ============================================================
# install_handler / uninstall_handler
# ============================================================


def test_install_handler_adds_to_logger():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    handler = install_handler(alerter, logger_name="bot4_v2.test_install")
    test_logger = logging.getLogger("bot4_v2.test_install")
    assert handler in test_logger.handlers
    # Cleanup
    uninstall_handler(handler, logger_name="bot4_v2.test_install")
    assert handler not in test_logger.handlers


def test_install_handler_logger_root_default():
    opener = _make_opener(success=True)
    alerter = DiscordAlerter(webhook_url="https://x", url_opener=opener)
    handler = install_handler(alerter)
    try:
        assert handler in logging.getLogger().handlers
    finally:
        uninstall_handler(handler)


# ============================================================
# Logs catalog codes registered
# ============================================================


def test_log_codes_discord_registered():
    from CORE.log_catalog import LOG_CODES
    expected = {
        "BOT4V2_DISCORD_PAYLOAD_FAIL",
        "BOT4V2_DISCORD_HTTP_FAIL",
        "BOT4V2_DISCORD_NETWORK_FAIL",
        "BOT4V2_DISCORD_UNEXPECTED_FAIL",
    }
    missing = expected - set(LOG_CODES.keys())
    assert missing == set(), f"Missing codes: {missing}"
