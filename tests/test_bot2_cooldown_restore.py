"""Tests Bot 2 _restore_cooldown_state au boot.

Bug observe 30/04 (Jackson "BOT 2 IL A PAS ATTENDU LE COOLDOWN") :
- NQ exit 14:39:02 → restart bot 14:40 (deploy fix) → NQ entry 14:48:40
- 9min < 15min cooldown → cooldown bypass

Cause : RiskManager.last_close_time est in-memory only. Restart bot →
reset → cooldown 15min ignore.

Fix : _restore_cooldown_state() au boot scanne `_databento_trades.jsonl`
du day CME courant, set risk.last_close_time[sym] = exit_ts du dernier
trade close. Cooldown 15min applique correctement post-restart.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


def _build_mock_trader(snapshots_dir: Path):
    from CORE.databento_paper_trader import DatabentoPaperTrader as BotTrader, RiskManager
    trader = BotTrader.__new__(BotTrader)
    trader.risk = RiskManager()
    trader.cfg = MagicMock()
    return trader


def _write_trades_jsonl(fp: Path, trades: list[dict]):
    with open(fp, "w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")


# ── Tests ──────────────────────────────────────────────────────────


class TestRestoreCooldownState:
    """Verifie que last_close_time est restaure depuis trades.jsonl du jour."""

    def test_restore_last_close_time_per_symbol(self, tmp_path, monkeypatch):
        """Cas nominal : 2 trades ES + 3 trades NQ → restore le DERNIER exit
        par symbole."""
        from CORE import databento_paper_trader as dpt
        monkeypatch.setattr(dpt, "SNAPSHOTS_DIR", tmp_path)

        # Mock get_cme_trading_day pour retourner une date stable
        monkeypatch.setattr(dpt, "get_cme_trading_day", lambda: "20260430")

        trades = [
            {"symbol": "ES", "exit_time": "2026-04-30T10:00:00+00:00"},
            {"symbol": "ES", "exit_time": "2026-04-30T11:30:00+00:00"},  # dernier ES
            {"symbol": "NQ", "exit_time": "2026-04-30T09:00:00+00:00"},
            {"symbol": "NQ", "exit_time": "2026-04-30T12:00:00+00:00"},
            {"symbol": "NQ", "exit_time": "2026-04-30T14:39:02+00:00"},  # dernier NQ
        ]
        fp = tmp_path / "20260430_databento_trades.jsonl"
        _write_trades_jsonl(fp, trades)

        trader = _build_mock_trader(tmp_path)
        trader._restore_cooldown_state()

        # ES : dernier exit @ 11:30
        assert trader.risk.last_close_time.get("ES") == \
            datetime(2026, 4, 30, 11, 30, 0, tzinfo=timezone.utc)
        # NQ : dernier exit @ 14:39:02
        assert trader.risk.last_close_time.get("NQ") == \
            datetime(2026, 4, 30, 14, 39, 2, tzinfo=timezone.utc)

    def test_no_trades_today_no_op(self, tmp_path, monkeypatch):
        """Pas de trades.jsonl du jour → no-op, last_close_time reste vide."""
        from CORE import databento_paper_trader as dpt
        monkeypatch.setattr(dpt, "SNAPSHOTS_DIR", tmp_path)
        monkeypatch.setattr(dpt, "get_cme_trading_day", lambda: "20260430")

        trader = _build_mock_trader(tmp_path)
        trader._restore_cooldown_state()
        assert trader.risk.last_close_time == {}

    def test_invalid_iso_skipped_silent(self, tmp_path, monkeypatch):
        """Trade avec exit_time pourri → skip silencieusement."""
        from CORE import databento_paper_trader as dpt
        monkeypatch.setattr(dpt, "SNAPSHOTS_DIR", tmp_path)
        monkeypatch.setattr(dpt, "get_cme_trading_day", lambda: "20260430")

        trades = [
            {"symbol": "ES", "exit_time": "INVALID_DATE"},
            {"symbol": "ES", "exit_time": "2026-04-30T10:00:00+00:00"},
        ]
        fp = tmp_path / "20260430_databento_trades.jsonl"
        _write_trades_jsonl(fp, trades)

        trader = _build_mock_trader(tmp_path)
        trader._restore_cooldown_state()
        # Le trade valide est pris, le pourri ignore
        assert trader.risk.last_close_time.get("ES") == \
            datetime(2026, 4, 30, 10, 0, 0, tzinfo=timezone.utc)

    def test_cooldown_calculation_post_restore(self, tmp_path, monkeypatch):
        """Apres restore, can_trade() doit appliquer le cooldown 15min."""
        from datetime import timedelta
        from CORE import databento_paper_trader as dpt
        monkeypatch.setattr(dpt, "SNAPSHOTS_DIR", tmp_path)
        monkeypatch.setattr(dpt, "get_cme_trading_day", lambda: "20260430")

        # Mock STOP_FLAG complet (Path object) pour eviter false negative
        fake_stop_flag = MagicMock()
        fake_stop_flag.exists.return_value = False
        monkeypatch.setattr(dpt, "STOP_FLAG", fake_stop_flag)

        # Exit 5 min ago (toujours dans cooldown)
        recent_exit = datetime.now(timezone.utc) - timedelta(minutes=5)
        trades = [
            {"symbol": "NQ", "exit_time": recent_exit.isoformat()},
        ]
        fp = tmp_path / "20260430_databento_trades.jsonl"
        _write_trades_jsonl(fp, trades)

        trader = _build_mock_trader(tmp_path)
        trader._restore_cooldown_state()

        # can_trade NQ doit retourner False avec COOLDOWN
        ok, reason = trader.risk.can_trade("NQ")
        assert ok is False
        assert "COOLDOWN" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
