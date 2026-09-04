"""Tests Fix #2 BUG FIX 30/06 — cooldown register_close activation.

BUG : _on_fill_close ne appelait PAS clusters[sym].register_close() ->
cooldown POST_LOSS (90 min) / POST_CLOSE (60 min) jamais active.
Cluster 4 SHORT ES 22-23h 29/06 = -$67.50 en 1h05.

Backtest empirique 29/06 (6 trades) :
  Real PnL : -$97.50
  Sim avec cooldown active : +$3.75
  Impact : +$101.25 net (3 trades evites)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from CORE.bot1_v2.config import Bot1V2Config


def _make_fake_self():
    fake_self = MagicMock()
    fake_self.cfg = Bot1V2Config()
    fake_self.clusters = {"ES": MagicMock(), "NQ": MagicMock()}
    fake_self.clusters["ES"].cooldown_until_ts = 0.0
    fake_self.clusters["NQ"].cooldown_until_ts = 0.0
    fake_self.store = MagicMock()
    fake_self.daily_gate = MagicMock()
    fake_self.daily_gate.state.n_trades_today = 0
    fake_self.daily_gate.state.cumul_pnl_usd = 0.0
    fake_self.daily_gate.snapshot.return_value = {"date_str": "2026-06-30"}
    fake_self.log = MagicMock()
    return fake_self


def test_on_fill_close_calls_register_close_on_loss():
    """Apres SL (pnl_usd < 0), register_close(was_loss=True)."""
    fake_self = _make_fake_self()

    def fake_register_close(exit_ts, was_loss=False):
        cd_min = 90 if was_loss else 60
        fake_self.clusters["ES"].cooldown_until_ts = exit_ts + cd_min * 60

    fake_self.clusters["ES"].register_close = MagicMock(
        side_effect=fake_register_close,
    )

    with patch("CORE.bot1_v2.main.bot_log"):
        from CORE.bot1_v2.main import Bot1V2
        Bot1V2._on_fill_close(fake_self, "ES", -25.00)

    fake_self.clusters["ES"].register_close.assert_called_once()
    call_kwargs = fake_self.clusters["ES"].register_close.call_args.kwargs
    assert call_kwargs["was_loss"] is True
    assert call_kwargs["exit_ts"] > 0

    fake_self.store.set_cooldown.assert_called_once()
    args = fake_self.store.set_cooldown.call_args.args
    assert args[0] == "ES"
    assert args[1] > 0


def test_on_fill_close_calls_register_close_on_win():
    fake_self = _make_fake_self()

    def fake_register_close(exit_ts, was_loss=False):
        cd_min = 90 if was_loss else 60
        fake_self.clusters["ES"].cooldown_until_ts = exit_ts + cd_min * 60

    fake_self.clusters["ES"].register_close = MagicMock(
        side_effect=fake_register_close,
    )

    with patch("CORE.bot1_v2.main.bot_log"):
        from CORE.bot1_v2.main import Bot1V2
        Bot1V2._on_fill_close(fake_self, "ES", 37.50)

    call_kwargs = fake_self.clusters["ES"].register_close.call_args.kwargs
    assert call_kwargs["was_loss"] is False


def test_on_fill_close_emits_BOT1V2_COOLDOWN_ACTIVATED():
    fake_self = _make_fake_self()

    def fake_register_close(exit_ts, was_loss=False):
        cd_min = 90 if was_loss else 60
        fake_self.clusters["ES"].cooldown_until_ts = exit_ts + cd_min * 60

    fake_self.clusters["ES"].register_close = MagicMock(
        side_effect=fake_register_close,
    )

    with patch("CORE.bot1_v2.main.bot_log") as mock_bot_log:
        from CORE.bot1_v2.main import Bot1V2
        Bot1V2._on_fill_close(fake_self, "ES", -20.00)
        cooldown_calls = [
            c for c in mock_bot_log.emit.call_args_list
            if c.args and c.args[0] == "BOT1V2_COOLDOWN_ACTIVATED"
        ]
        assert len(cooldown_calls) == 1
        ctx = cooldown_calls[0].kwargs
        assert ctx["sym"] == "ES"
        assert ctx["was_loss"] is True
        assert ctx["pnl_usd"] == -20.00


def test_on_fill_close_no_crash_if_cluster_missing():
    fake_self = _make_fake_self()
    fake_self.clusters = {}

    with patch("CORE.bot1_v2.main.bot_log"):
        from CORE.bot1_v2.main import Bot1V2
        Bot1V2._on_fill_close(fake_self, "MGC", -10.00)


def test_on_fill_close_exception_in_register_close_does_not_crash():
    """Si register_close raise, on continue (daily_gate.update_after_trade)."""
    fake_self = _make_fake_self()
    fake_self.clusters["ES"].register_close = MagicMock(
        side_effect=RuntimeError("test fail"),
    )

    with patch("CORE.bot1_v2.main.bot_log"):
        from CORE.bot1_v2.main import Bot1V2
        Bot1V2._on_fill_close(fake_self, "ES", -15.00)

    fake_self.daily_gate.update_after_trade.assert_called_once_with(-15.00)


def test_config_cooldown_post_loss_stricter_than_close():
    cfg = Bot1V2Config()
    assert cfg.COOLDOWN_POST_LOSS_MIN == 90
    assert cfg.COOLDOWN_POST_CLOSE_MIN == 60
    assert cfg.COOLDOWN_POST_LOSS_MIN > cfg.COOLDOWN_POST_CLOSE_MIN
