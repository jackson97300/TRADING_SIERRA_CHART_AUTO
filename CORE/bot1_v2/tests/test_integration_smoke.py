"""Tests integration smoke Bot 1 v2.

Verifie que main + cluster + gates + execution chain s'integrent :
  - Init Bot1V2 OK
  - Process une bar synthetic OK
  - State persistence cycle (save -> load)
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate
from CORE.bot1_v2.gates.session import SessionGate
from CORE.bot1_v2.execution.order_router import OrderRouter
from CORE.bot1_v2.state.position_store import PositionStore


def test_daily_limits_max_trades():
    cfg = Bot1V2Config(MAX_TRADES_PER_DAY=2)
    gate = DailyLimitsGate(cfg)
    gate.reset_for_new_day("2026-06-16")
    assert gate.check_allow_entry().allowed is True
    gate.update_after_trade(10.0)
    assert gate.check_allow_entry().allowed is True
    gate.update_after_trade(-5.0)
    # 2 trades atteint
    verdict = gate.check_allow_entry()
    assert verdict.allowed is False
    assert "DAILY_MAX_TRADES" in verdict.skip_reason


def test_daily_limits_stop_loss():
    cfg = Bot1V2Config(DAILY_STOP_LOSS_USD=-100.0)
    gate = DailyLimitsGate(cfg)
    gate.reset_for_new_day("2026-06-16")
    gate.update_after_trade(-100.0)
    verdict = gate.check_allow_entry()
    assert verdict.allowed is False
    assert "DAILY_STOP_LOSS" in verdict.skip_reason


def test_daily_limits_stop_win_lockin():
    cfg = Bot1V2Config(DAILY_STOP_WIN_USD=150.0)
    gate = DailyLimitsGate(cfg)
    gate.reset_for_new_day("2026-06-16")
    gate.update_after_trade(150.0)
    verdict = gate.check_allow_entry()
    assert verdict.allowed is False
    assert "DAILY_STOP_WIN" in verdict.skip_reason


def test_session_us_rth_allowed():
    from datetime import datetime, timezone
    cfg = Bot1V2Config()
    gate = SessionGate(cfg)
    # 14:00 UTC = 10:00 ET (UTC-4) = mid-RTH session
    dt = datetime(2026, 6, 16, 14, 0, 0, tzinfo=timezone.utc)
    ts_ms = int(dt.timestamp() * 1000)
    bar = {
        "ts": ts_ms,
        "is_in_us_cash": True,
        "session_id": "US",
    }
    verdict = gate.check_allow_entry(bar)
    assert verdict.allowed is True, f"skip={verdict.skip_reason}"
    assert verdict.session_phase == "US_RTH"


def test_session_asia_blocked():
    cfg = Bot1V2Config()
    gate = SessionGate(cfg)
    bar = {
        "ts": 1781000000000,
        "is_in_us_cash": False,
        "session_id": "ASIA",
    }
    verdict = gate.check_allow_entry(bar)
    assert verdict.allowed is False
    assert "ASIA" in verdict.skip_reason or "NOT_TRADABLE" in verdict.skip_reason


def test_session_news_blocked():
    cfg = Bot1V2Config()
    gate = SessionGate(cfg)
    bar = {
        "ts": 1781000000000,
        "is_in_us_cash": True,
        "session_id": "US",
        "is_news_5m": True,
    }
    verdict = gate.check_allow_entry(bar)
    assert verdict.allowed is False
    assert "NEWS_LOCKOUT" in verdict.skip_reason


def test_order_router_dry_run():
    """Dry-run renvoie success + fill_price = entry_price (simulation)."""
    from CORE.bot1_v2.cluster import ClusterDecision

    cfg = Bot1V2Config()
    router = OrderRouter(cfg=cfg, dry_run=True)
    decision = ClusterDecision(
        tradable=True,
        signal_id="abc123",
        direction="LONG",
        entry_price=7600.0,
        sl_price=7596.0,
        tp_price=7610.0,
        n_micros=1,
        symbol="ES",
    )
    result = router.send_bracket(decision)
    assert result.success is True
    assert result.dry_run is True
    assert result.fill_price == 7600.0
    assert result.parent_cid.startswith("BOT1V2_P_")
    assert result.tp_cid.startswith("BOT1V2_TP_")
    assert result.sl_cid.startswith("BOT1V2_SL_")


def test_order_router_skip_non_tradable():
    from CORE.bot1_v2.cluster import ClusterDecision

    router = OrderRouter(cfg=Bot1V2Config(), dry_run=True)
    decision = ClusterDecision(tradable=False, skip_reason="TEST_SKIP")
    result = router.send_bracket(decision)
    assert result.success is False
    assert "NOT_TRADABLE" in result.error_msg


class _MockDTC:
    """Mock DTC connector pour test signature legacy."""

    def __init__(self):
        self.calls = []

    def send_market_order(
        self, symbol, side, quantity, sl_price, tp_price,
        trade_account, signal_ref_price=0, sl_ticks=0, tp_ticks=0,
        tick_size=0.25, auto_reprice_threshold_ticks=5,
    ):
        self.calls.append({
            "symbol": symbol, "side": side, "quantity": quantity,
            "sl_price": sl_price, "tp_price": tp_price,
            "trade_account": trade_account,
            "signal_ref_price": signal_ref_price,
            "sl_ticks": sl_ticks, "tp_ticks": tp_ticks,
        })
        # Retourne tuple legacy : (parent_cid, tp_cid, sl_cid, fill_price)
        return ("PARENT_REAL_123", "TP_REAL_456", "SL_REAL_789", signal_ref_price)


def test_order_router_prod_legacy_signature_long():
    """Prod mode : adapte LONG -> side=1 et appelle send_market_order legacy."""
    from CORE.bot1_v2.cluster import ClusterDecision

    mock_dtc = _MockDTC()
    cfg = Bot1V2Config(TRADE_ACCOUNT="Sim2")
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    decision = ClusterDecision(
        tradable=True,
        signal_id="abc",
        direction="LONG",
        entry_price=7600.0,
        sl_price=7596.0,
        sl_ticks=16,
        tp_price=7610.0,
        tp_ticks=40,
        n_micros=1,
        symbol="ES",
    )
    result = router.send_bracket(decision)
    assert result.success is True
    assert result.dry_run is False
    # Verifie signature legacy
    assert len(mock_dtc.calls) == 1
    call = mock_dtc.calls[0]
    assert call["symbol"] == "ES"
    assert call["side"] == 1  # LONG -> 1
    assert call["quantity"] == 1
    assert call["trade_account"] == "Sim2"  # PAS Sim3 default piege
    assert call["signal_ref_price"] == 7600.0
    assert call["sl_ticks"] == 16
    assert call["tp_ticks"] == 40
    # CIDs retournes par DTC remplacent les locaux
    assert result.parent_cid == "PARENT_REAL_123"
    assert result.tp_cid == "TP_REAL_456"
    assert result.sl_cid == "SL_REAL_789"


def test_order_router_prod_legacy_signature_short():
    """SHORT -> side=2."""
    from CORE.bot1_v2.cluster import ClusterDecision

    mock_dtc = _MockDTC()
    cfg = Bot1V2Config(TRADE_ACCOUNT="Sim2")
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    decision = ClusterDecision(
        tradable=True, signal_id="xyz",
        direction="SHORT", entry_price=7600.0,
        sl_price=7604.0, sl_ticks=16,
        tp_price=7590.0, tp_ticks=40,
        n_micros=1, symbol="ES",
    )
    result = router.send_bracket(decision)
    assert result.success is True
    assert mock_dtc.calls[0]["side"] == 2  # SHORT -> 2
    assert mock_dtc.calls[0]["trade_account"] == "Sim2"


def test_position_store_save_load_cycle():
    """Save -> Load -> donnees preservees."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8",
    ) as f:
        tmp_path = Path(f.name)

    try:
        store = PositionStore(path=tmp_path)
        store.open_position("ES", {
            "signal_id": "abc",
            "direction": "LONG",
            "entry_price": 7600.0,
            "sl_price": 7596.0,
        })
        store.set_cooldown("NQ", 1781234567.0)
        assert store.save() is True

        # Load fresh instance
        store2 = PositionStore(path=tmp_path)
        assert store2.load() is True
        assert store2.has_position("ES") is True
        assert store2.get_position("ES")["entry_price"] == 7600.0
        assert store2.get_cooldown("NQ") == 1781234567.0
        assert "abc" in store2.traded_signal_ids
    finally:
        tmp_path.unlink(missing_ok=True)


def test_bot_init_dry_run():
    """Bot1V2 init dry_run = OK."""
    from CORE.bot1_v2.main import Bot1V2

    bot = Bot1V2(symbols=["ES"], dry_run=True)
    assert bot.dry_run is True
    assert bot.symbols == ["ES"]
    assert "ES" in bot.clusters
    assert "ES" in bot.data_sources
