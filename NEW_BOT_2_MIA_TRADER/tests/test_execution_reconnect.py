"""Tests ensure_connected() reconnect DTC (INCIDENT #77 19/06/2026).

Couvre :
- L1 : ensure_connected returns True si deja connecte
- L2 : ensure_connected tente connect() si pas connecte
- L3 : anti-spam 30s entre tentatives
- L4 : send_bracket utilise ensure_connected (regression check)
- L5 : telemetry emit codes appropries
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_HERE = Path(__file__).parent.parent
sys.path.insert(0, str(_HERE))

from src.execution import BracketResult, DTCExecutor
from src.execution_config import DTCSettings, ExecutionConfig


def _make_executor(dry_run: bool = False, telemetry=None) -> DTCExecutor:
    """Helper : factory DTCExecutor avec config minimale."""
    cfg = ExecutionConfig(dtc=DTCSettings(), dry_run=dry_run)
    return DTCExecutor(config=cfg, telemetry=telemetry)


# ════════════════════════════════════════════════════════════════════════════
# L1 - ensure_connected si deja connecte
# ════════════════════════════════════════════════════════════════════════════


def test_ensure_connected_returns_true_if_already_connected():
    """Si deja connecte, retourne True sans tenter reconnect."""
    ex = _make_executor(dry_run=True)
    ex._connected = True  # simule deja connecte

    assert ex.ensure_connected() is True
    # Aucune tentative compte
    assert ex._reconnect_attempts_count == 0


# ════════════════════════════════════════════════════════════════════════════
# L2 - ensure_connected tente connect si pas connecte
# ════════════════════════════════════════════════════════════════════════════


def test_ensure_connected_attempts_connect_if_disconnected():
    """Si pas connecte, tente connect() qui retourne True -> ensure OK."""
    ex = _make_executor(dry_run=True)
    ex._connected = False  # simule disconnect
    ex._last_reconnect_attempt_ts = 0.0  # aucune tentative recente

    result = ex.ensure_connected()
    assert result is True
    assert ex._reconnect_attempts_count == 1
    assert ex._connected is True  # connect() dry_run a set _connected=True


def test_ensure_connected_returns_false_if_connect_fails():
    """Si connect() echoue, ensure_connected retourne False."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    # Monkeypatch connect pour simuler echec
    ex.connect = lambda: False

    result = ex.ensure_connected()
    assert result is False
    assert ex._reconnect_attempts_count == 1


def test_ensure_connected_returns_false_if_connect_raises():
    """Si connect() leve exception, retourne False sans propager."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    ex.connect = lambda: (_ for _ in ()).throw(RuntimeError("DTC unreachable"))

    result = ex.ensure_connected()
    assert result is False
    assert ex._reconnect_attempts_count == 1


# ════════════════════════════════════════════════════════════════════════════
# L3 - Anti-spam 30s entre tentatives
# ════════════════════════════════════════════════════════════════════════════


def test_ensure_connected_throttle_within_30s():
    """2 appels en moins de 30s : 2eme appel skip throttle, attempts_count=1."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    ex.connect = lambda: False  # simule echec connect

    # 1er appel : tentative compte (mais echoue)
    ex.ensure_connected()
    assert ex._reconnect_attempts_count == 1
    ts_after_first = ex._last_reconnect_attempt_ts

    # 2eme appel immediat : skip throttle
    result = ex.ensure_connected()
    assert result is False
    assert ex._reconnect_attempts_count == 1  # PAS incremente
    assert ex._last_reconnect_attempt_ts == ts_after_first  # PAS update


def test_ensure_connected_allows_retry_after_30s():
    """Apres 30s, nouvelle tentative autorisee."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = time.time() - 31.0  # 31s passe
    ex.connect = lambda: False

    ex.ensure_connected()
    assert ex._reconnect_attempts_count == 1


def test_ensure_connected_custom_throttle_interval():
    """Argument min_retry_interval_sec permet personnaliser le throttle."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = time.time() - 5.0  # 5s passe
    ex.connect = lambda: False

    # Avec throttle 10s : skip
    result1 = ex.ensure_connected(min_retry_interval_sec=10.0)
    assert result1 is False
    assert ex._reconnect_attempts_count == 0

    # Avec throttle 3s : tente
    result2 = ex.ensure_connected(min_retry_interval_sec=3.0)
    assert ex._reconnect_attempts_count == 1


# ════════════════════════════════════════════════════════════════════════════
# L4 - send_bracket utilise ensure_connected (regression)
# ════════════════════════════════════════════════════════════════════════════


def test_send_bracket_calls_ensure_connected():
    """send_bracket() doit appeler ensure_connected (pas is_connected pur)."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    # connect() reussit en dry_run
    result = ex.send_bracket(
        symbol="NQU26-CME",
        side="BUY",
        quantity=3,
        sl_price=21441.75,
        tp_price=21465.00,
        tick_size=0.25,
        signal_ref_price=21450.00,
        sl_ticks=33,
        tp_ticks=60,
    )
    # Reconnect tente automatiquement, dry_run reussit -> bracket OK
    assert result.success is True
    assert result.reject_reason is None
    assert ex._reconnect_attempts_count == 1


def test_send_bracket_returns_not_connected_after_throttle():
    """send_bracket throttle : reject_reason=not_connected si throttle skip."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    # Forcer une tentative recente PUIS echec connect
    ex._last_reconnect_attempt_ts = time.time() - 2.0  # 2s = throttle 30s
    ex.connect = lambda: False  # connect echoue meme si tente

    result = ex.send_bracket(
        symbol="NQU26-CME",
        side="BUY",
        quantity=3,
        sl_price=21441.75,
        tp_price=21465.00,
        tick_size=0.25,
        signal_ref_price=21450.00,
        sl_ticks=33,
        tp_ticks=60,
    )
    assert result.success is False
    assert result.reject_reason == "not_connected"


# ════════════════════════════════════════════════════════════════════════════
# L5 - Telemetry codes emit
# ════════════════════════════════════════════════════════════════════════════


def test_telemetry_emit_reconnect_ok():
    """Telemetry recoit BOT4_DTC_RECONNECT_OK quand succes."""
    tel = MagicMock()
    ex = _make_executor(dry_run=True, telemetry=tel)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0

    ex.ensure_connected()
    # tel.emit doit avoir ete appele avec ATTEMPT puis OK
    codes_called = [call.args[0] for call in tel.emit.call_args_list]
    assert "BOT4_DTC_RECONNECT_ATTEMPT" in codes_called
    assert "BOT4_DTC_RECONNECT_OK" in codes_called


def test_telemetry_emit_reconnect_fail():
    """Telemetry recoit BOT4_DTC_RECONNECT_FAIL quand echec."""
    tel = MagicMock()
    ex = _make_executor(dry_run=True, telemetry=tel)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    ex.connect = lambda: False

    ex.ensure_connected()
    codes_called = [call.args[0] for call in tel.emit.call_args_list]
    assert "BOT4_DTC_RECONNECT_FAIL" in codes_called


def test_telemetry_emit_skip_throttle():
    """Telemetry recoit BOT4_DTC_RECONNECT_SKIP_THROTTLE quand throttle."""
    tel = MagicMock()
    ex = _make_executor(dry_run=True, telemetry=tel)
    ex._connected = False
    ex._last_reconnect_attempt_ts = time.time() - 5.0  # recent

    ex.ensure_connected(min_retry_interval_sec=30.0)
    codes_called = [call.args[0] for call in tel.emit.call_args_list]
    assert "BOT4_DTC_RECONNECT_SKIP_THROTTLE" in codes_called


def test_telemetry_no_emit_if_telemetry_none():
    """Telemetry None : pas de crash, silent (fallback logger interne)."""
    ex = _make_executor(dry_run=True, telemetry=None)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    # Pas de crash meme sans telemetry (voie 2 logger interne fallback)
    result = ex.ensure_connected()
    assert result is True


# ════════════════════════════════════════════════════════════════════════════
# L6 - Concurrency (Q3 code-reviewer)
# ════════════════════════════════════════════════════════════════════════════


def test_ensure_connected_concurrent_threads_no_race():
    """Q3 code-reviewer : threading.Lock evite double tentative simultanee.

    Verif : 10 threads paralleles appellent ensure_connected, doit y avoir
    UNE SEULE tentative compte (les autres skip throttle ou attendent lock).
    """
    import threading

    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    # connect simule : prend 50ms
    connect_calls = [0]
    original_connect = ex.connect

    def slow_connect():
        connect_calls[0] += 1
        time.sleep(0.05)
        return original_connect()

    ex.connect = slow_connect

    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        ex.ensure_connected()

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Attendu : 1 tentative reussit (incremente _reconnect_attempts_count
    # de 0 a 1), les 9 autres skip throttle.
    assert ex._reconnect_attempts_count == 1, \
        f"Race condition : {ex._reconnect_attempts_count} tentatives au lieu de 1"
    # connect() appelle 1 seule fois (les autres skip throttle)
    assert connect_calls[0] == 1


# ════════════════════════════════════════════════════════════════════════════
# L7 - Leak threads prevention (R-NEW-1 code-reviewer)
# ════════════════════════════════════════════════════════════════════════════


def test_ensure_connected_calls_disconnect_before_reconnect():
    """R-NEW-1 code-reviewer : disconnect() AVANT reconnect pour cleanup
    legacy _recv_loop thread daemon.
    """
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    # Simuler _legacy existant (pas None)
    ex._legacy = MagicMock()

    disconnect_called = [0]
    original_disconnect = ex.disconnect

    def tracking_disconnect():
        disconnect_called[0] += 1
        original_disconnect()

    ex.disconnect = tracking_disconnect

    ex.ensure_connected()
    assert disconnect_called[0] == 1, \
        "disconnect() doit etre appele avant reconnect pour cleanup"


def test_ensure_connected_skips_disconnect_if_legacy_none():
    """Si _legacy=None (cold start), pas besoin de disconnect()."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    ex._legacy = None  # cold start

    disconnect_called = [0]
    original_disconnect = ex.disconnect

    def tracking_disconnect():
        disconnect_called[0] += 1
        original_disconnect()

    ex.disconnect = tracking_disconnect

    ex.ensure_connected()
    # disconnect() NON appele si _legacy=None
    assert disconnect_called[0] == 0


def test_ensure_connected_continues_if_disconnect_raises():
    """Si disconnect() leve exception, ensure_connected doit continuer
    avec connect() (legacy peut etre dans etat corrompu)."""
    ex = _make_executor(dry_run=True)
    ex._connected = False
    ex._last_reconnect_attempt_ts = 0.0
    ex._legacy = MagicMock()

    def failing_disconnect():
        raise RuntimeError("disconnect failed corrupt state")

    ex.disconnect = failing_disconnect
    # connect doit toujours etre appele
    result = ex.ensure_connected()
    assert result is True  # dry_run connect succes
    assert ex._reconnect_attempts_count == 1
