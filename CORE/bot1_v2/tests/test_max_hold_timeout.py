"""Tests Fix #1 MAX_HOLD audit 30/06 — anti trade qui dure 13h+.

Sequence anti-orphelin V2 (cf .claude/rules/orphan-prevention.md) :
  - close_position_market_safe : 9 etapes (cancel TP+SL, wait, verify, market close,
    flatten Type 209+210, verify post-cleanup).
  - _check_position_timeouts : boucle main appelle pour chaque pos.

Tests :
  - Config defaults (45 min, enabled)
  - close_position_market_safe dry_run = no-op
  - close_position_market_safe broker already flat (qty=0) = OK pas de market close
  - close_position_market_safe broker qty=-1 SHORT = BUY MARKET close emis
  - close_position_market_safe broker DTC freeze (qty=None) = warning + tentative
  - _check_position_timeouts no position = no-op
  - _check_position_timeouts position fresh = no-op (elapsed < max)
  - _check_position_timeouts position expired = trigger close + cleanup store
  - env var BOT1V2_MAX_HOLD_MINUTES override fonctionnel
  - env var BOT1V2_MAX_HOLD_ENABLED=0 disable feature
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.execution.order_router import OrderRouter


# ===== Config defaults =====

def test_config_max_hold_defaults():
    cfg = Bot1V2Config()
    assert cfg.MAX_HOLD_MINUTES == 45
    assert cfg.MAX_HOLD_ENABLED is True


def test_config_max_hold_env_override(monkeypatch):
    """Verifier que Bot1V2Config.from_env() lit BOT1V2_MAX_HOLD_* env vars."""
    monkeypatch.setenv("BOT1V2_MAX_HOLD_MINUTES", "30")
    monkeypatch.setenv("BOT1V2_MAX_HOLD_ENABLED", "0")
    cfg = Bot1V2Config.from_env()
    assert cfg.MAX_HOLD_MINUTES == 30
    assert cfg.MAX_HOLD_ENABLED is False


# ===== close_position_market_safe =====

def _make_router_with_mock_dtc(dry_run=False):
    cfg = Bot1V2Config()
    mock_dtc = MagicMock()
    router = OrderRouter(cfg=cfg, dry_run=dry_run, dtc_connector=mock_dtc)
    return router, mock_dtc


def test_close_dry_run_noop():
    cfg = Bot1V2Config()
    router = OrderRouter(cfg=cfg, dry_run=True, dtc_connector=None)
    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP", sl_cid="SL",
    )
    assert res["ok"] is True
    assert res["error"] == "DRY_RUN_NO_OP"


def test_close_broker_already_flat_no_market_close():
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=0)
    mock_dtc.send_close_market = MagicMock()
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP_CID", sl_cid="SL_CID",
    )
    assert res["ok"] is True
    assert res["qty_broker"] == 0
    # Cancel TP + SL appeles
    assert mock_dtc.cancel_order.call_count == 2
    # PAS de market close envoye (already flat)
    mock_dtc.send_close_market.assert_not_called()


def test_close_broker_short_position_buy_market_emitted():
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=-1)
    mock_dtc.send_close_market = MagicMock()
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP", sl_cid="SL",
    )
    assert res["ok"] is True
    assert res["qty_broker"] == -1
    # send_close_market called avec side=1 (BUY) car broker SHORT
    assert mock_dtc.send_close_market.call_count == 1
    call_kwargs = mock_dtc.send_close_market.call_args.kwargs
    assert call_kwargs["side"] == 1  # BUY
    assert call_kwargs["quantity"] == 1
    assert call_kwargs["symbol"] == "ESU26-CME"


def test_close_broker_long_position_sell_market_emitted():
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=2)
    mock_dtc.send_close_market = MagicMock()
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    res = router.close_position_market_safe(
        symbol="NQ", contract="NQU26-CME", direction="LONG",
        n_micros=2, parent_cid="P", tp_cid="TP", sl_cid="SL",
    )
    assert res["ok"] is True
    assert res["qty_broker"] == 2
    # send_close_market called avec side=2 (SELL) + qty=2
    call_kwargs = mock_dtc.send_close_market.call_args.kwargs
    assert call_kwargs["side"] == 2  # SELL
    assert call_kwargs["quantity"] == 2


def test_close_broker_dtc_freeze_skip_unsafe_close():
    """Fix D1 13/07 (INCIDENT #96) : si broker qty=None (DTC freeze OU broker flat),
    REFUSE d'emettre MARKET CLOSE aveugle.

    Regression : precedente version faisait fallback n_micros -> creait position
    INVERSE si broker deja flat -> cascade 9 SHORTs cumul ESU26 sur Sim2.
    """
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=None)
    mock_dtc.send_close_market = MagicMock()
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    emit_log = []
    def emit_fn(code, **ctx):
        emit_log.append((code, ctx))

    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP", sl_cid="SL",
        emit_fn=emit_fn,
    )
    # Fix D1 : SKIP - PAS de send_close_market emis
    assert res["qty_broker"] is None
    assert res["error"] == "BROKER_QTY_UNKNOWN_SKIP_UNSAFE_CLOSE"
    mock_dtc.send_close_market.assert_not_called()
    # Log CRITIQUE emis pour audit
    codes = [c for c, _ in emit_log]
    assert "BOT1V2_TIMEOUT_POSITION_UNKNOWN_SKIP_CLOSE" in codes


def test_close_cancel_brackets_failure_logged():
    """Si cancel_order retourne False, cancel_failed track sans crash."""
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=False)
    mock_dtc.request_position_blocking = MagicMock(return_value=0)
    mock_dtc.send_close_market = MagicMock()
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    emit_log = []
    def emit_fn(code, **ctx):
        emit_log.append((code, ctx))

    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP", sl_cid="SL",
        emit_fn=emit_fn,
    )
    assert "tp" in res["cancel_failed"]
    assert "sl" in res["cancel_failed"]
    # Log ORPHAN_RISK emis
    codes = [c for c, _ in emit_log]
    assert "BOT1V2_TIMEOUT_CANCEL_FAIL_ORPHAN_RISK" in codes


def test_close_etape_9_no_direct_recv_call():
    """Fix B1 review code-reviewer 30/06 (CRITIQUE) :

    Verify post-cleanup NE DOIT PLUS appeler self.dtc._recv directement
    (race avec _recv_loop daemon thread = steal fills + corruption buffer).
    """
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=0)
    mock_dtc.send_close_market = MagicMock()
    mock_dtc._send = MagicMock()
    # Si _recv est appele = CRASH le test (fail-loud)
    mock_dtc._recv = MagicMock(
        side_effect=AssertionError("B1: _recv interdit dans etape 9"),
    )

    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP", sl_cid="SL",
    )
    assert res["ok"] is True
    # _recv ne doit jamais avoir ete appele
    mock_dtc._recv.assert_not_called()


def test_close_emit_trade_account_explicit():
    """Verifier que cancel_order recoit trade_account=Sim2 (anti-fix-H6)."""
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=0)
    mock_dtc.send_close_market = MagicMock()
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP_CID", sl_cid="SL_CID",
    )
    # Verifier que cancel_order recoit trade_account=Sim2 explicit
    for call in mock_dtc.cancel_order.call_args_list:
        assert call.kwargs.get("trade_account") == "Sim2", \
            f"cancel_order sans trade_account Sim2 explicite: {call}"


# ===== FIX CID 04/09 — non-regression INCIDENT #70 rejoue sur bot1_v2 =====
# Contexte : send_close_market genere son propre ClientOrderID (MIA_CLOSE_<uuid>)
# et le RETOURNE. La valeur de retour etait ignoree => main.py enregistrait le cid
# local BOT1V2_CLOSE_* dans fill_listener._cid_index, le broker fillait MIA_CLOSE_*
# => fill jamais route => position jamais retiree du store => re-close au boot
# suivant. ~6000 MARKET CLOSE emis sur Sim2 entre le 13/07 et le 04/09.

def test_close_cid_is_broker_cid_not_local():
    """close_cid retourne DOIT etre celui du broker, pas le fallback local.

    C'est le test qui aurait attrape le bug : sans lui, le cid local
    BOT1V2_CLOSE_* est enregistre dans le listener et le fill MIA_CLOSE_*
    n'est jamais route.
    """
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=-1)  # SHORT broker
    mock_dtc.send_close_market = MagicMock(return_value="MIA_CLOSE_deadbeef")
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP", sl_cid="SL",
    )
    assert res["ok"] is True
    assert res["close_cid"] == "MIA_CLOSE_deadbeef", \
        "close_cid doit etre le ClientOrderID rendu par le broker"
    assert not res["close_cid"].startswith("BOT1V2_CLOSE_"), \
        "regression #70 : cid local renvoye au lieu du cid broker"


def test_close_not_sent_when_dtc_disconnected():
    """send_close_market retourne '' (non connecte) => ok=False, pas de mensonge.

    Avant le fix : result[ok]=True alors que l'ordre n'etait jamais parti.
    """
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=2)  # LONG broker
    mock_dtc.send_close_market = MagicMock(return_value="")  # non connecte
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    res = router.close_position_market_safe(
        symbol="NQ", contract="NQU26-CME", direction="LONG",
        n_micros=2, parent_cid="P", tp_cid="TP", sl_cid="SL",
    )
    assert res["ok"] is False, "ordre non emis ne doit PAS etre rapporte ok"
    assert res["error"] == "CLOSE_NOT_SENT_DTC_DISCONNECTED"
    # R1 review 04/09 : cid purge, sinon main.py enregistre une entree fantome
    # dans _cid_index a chaque tour de boucle (fuite + cid local non routable).
    assert res["close_cid"] == "", \
        "close_cid doit etre vide quand aucun ordre n'est parti"


def test_close_cid_unresolved_keeps_legacy_behaviour():
    """Retour non-str (None / double de test) => legacy ok=True + cid fallback.

    Garantit que le fix ne casse pas les mocks historiques sans return_value.
    """
    router, mock_dtc = _make_router_with_mock_dtc()
    mock_dtc.cancel_order = MagicMock(return_value=True)
    mock_dtc.request_position_blocking = MagicMock(return_value=-1)
    mock_dtc.send_close_market = MagicMock(return_value=None)
    mock_dtc._send = MagicMock()
    mock_dtc._recv = MagicMock(return_value=[])

    res = router.close_position_market_safe(
        symbol="ES", contract="ESU26-CME", direction="SHORT",
        n_micros=1, parent_cid="P", tp_cid="TP", sl_cid="SL",
    )
    assert res["ok"] is True
    assert res["close_cid"].startswith("BOT1V2_CLOSE_")
