"""Tests integration smoke - boot bot + 1 iteration sans crash."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from CORE.bot_bn_v4.config import BotBNV4Config
from CORE.bot_bn_v4.main import BotBNV4
from CORE.bot_bn_v4.execution.order_router import OrderRouter, OrderResult


def test_boot_dry_run(tmp_path, monkeypatch):
    """Boot BotBNV4 en dry-run, sans crash."""
    # Patch state_bridge path et position_store path vers tmp pour eviter polluer DATA/
    monkeypatch.setattr(
        "CORE.bot_bn_v4.state_bridge._bot_bn_state_path",
        lambda: tmp_path / "state_sim3.json",
    )
    # Patch PositionStore default path
    monkeypatch.setenv("MIA_ROOT", str(tmp_path))

    bot = BotBNV4(symbols=["NQ"], dry_run=True)
    assert bot.dry_run is True
    assert bot.cfg.TRADE_ACCOUNT == "Sim3"
    assert "NQ" in bot.symbols
    assert "NQ" in bot.signals
    assert "NQ" in bot.trails
    assert "NQ" in bot.data_sources


def test_process_symbol_no_data_does_not_crash(tmp_path, monkeypatch):
    """_process_symbol() sans fichier JSONL -> no-op (pas de crash)."""
    monkeypatch.setattr(
        "CORE.bot_bn_v4.state_bridge._bot_bn_state_path",
        lambda: tmp_path / "state_sim3.json",
    )
    # data_dir vide
    monkeypatch.setattr(
        "CORE.bot1_v2.data_source.SierraDataSource.data_dir",
        property(lambda self: tmp_path / "no_such_dir"),
    )
    bot = BotBNV4(symbols=["NQ"], dry_run=True)
    bot._process_symbol("NQ")  # ne raise pas


def test_day_rollover_works(tmp_path, monkeypatch):
    """_rotate_day_if_needed marche meme sans bar."""
    monkeypatch.setattr(
        "CORE.bot_bn_v4.state_bridge._bot_bn_state_path",
        lambda: tmp_path / "state_sim3.json",
    )
    bot = BotBNV4(symbols=["NQ"], dry_run=True)
    # date forcee a hier -> doit rotate au prochain check
    bot.daily_gate.reset_for_new_day("2026-01-01")
    bot._rotate_day_if_needed()
    # Apres rotate, date_str doit etre today
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert bot.daily_gate.state.date_str == today


def test_order_router_dry_run_simulates_fill():
    """OrderRouter dry-run renvoie success + fill_price=entry_price."""
    cfg = BotBNV4Config.from_env()
    router = OrderRouter(cfg=cfg, dry_run=True)
    res = router.send_entry(
        symbol="NQ", direction="long",
        entry_price=30000.0, sl_price=29990.0, n_micros=1,
    )
    assert res.success is True
    assert res.dry_run is True
    assert res.fill_price == 30000.0
    assert res.parent_cid.startswith("BOTBN_P_")
    assert res.sl_cid.startswith("BOTBN_SL_")


def test_order_router_dry_run_replace_sl_returns_synthetic_cid():
    """A3 : replace_sl en dry-run retourne nouveau CID synthetique (avant : bool True)."""
    cfg = BotBNV4Config.from_env()
    router = OrderRouter(cfg=cfg, dry_run=True)
    new_cid = router.replace_sl(
        symbol="NQ", sl_cid="BOTBN_SL_dummy", new_sl_price=29985.0,
        direction="long", n_micros=1,
    )
    assert isinstance(new_cid, str)
    assert new_cid.startswith("BOTBN_TRAIL_SL_")


def test_order_router_prod_replace_sl_returns_new_cid_from_dtc():
    """A3 prod mode : replace_sl appelle dtc.send_stop_order + retourne son CID."""
    from unittest.mock import MagicMock
    cfg = BotBNV4Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.send_stop_order.return_value = "MIA_TRAIL_SL_abc123"
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    new_cid = router.replace_sl(
        symbol="NQ", sl_cid="MIA_SL_old", new_sl_price=29985.0,
        direction="long", n_micros=1,
    )
    assert new_cid == "MIA_TRAIL_SL_abc123"
    mock_dtc.cancel_order.assert_called_once()
    mock_dtc.send_stop_order.assert_called_once()


def test_order_router_prod_replace_sl_returns_empty_if_send_fails():
    """A3 prod : si dtc.send_stop_order raise, replace_sl retourne '' (alert)."""
    from unittest.mock import MagicMock
    cfg = BotBNV4Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.send_stop_order.side_effect = ConnectionError("DTC down")
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    new_cid = router.replace_sl(
        symbol="NQ", sl_cid="MIA_SL_old", new_sl_price=29985.0,
        direction="long", n_micros=1,
    )
    # Empty = caller doit alerte (position nue)
    assert new_cid == ""


def test_order_router_prod_replace_sl_legacy_dtc_no_send_stop_order():
    """A3 prod : legacy DTC sans send_stop_order → '' (au lieu de True silencieux)."""
    from unittest.mock import MagicMock
    cfg = BotBNV4Config.from_env()
    mock_dtc = MagicMock(spec=["cancel_order"])  # PAS de send_stop_order
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    new_cid = router.replace_sl(
        symbol="NQ", sl_cid="MIA_SL_old", new_sl_price=29985.0,
        direction="long", n_micros=1,
    )
    # Avant fix : True silencieux = position nue masquee. Apres : "" = alert.
    assert new_cid == ""


def test_order_router_prod_replace_sl_require_sid_true_prevents_orphan():
    """A3 R1 BLOQUANT : cancel avec require_sid=True. Si cancel refuse (no SID),
    replace_sl retourne '' SANS appeler send_stop_order → pas de 2 SL actifs."""
    from unittest.mock import MagicMock
    cfg = BotBNV4Config.from_env()
    mock_dtc = MagicMock()
    # cancel_order refuse car SID pas dispo (require_sid=True effect)
    mock_dtc.cancel_order.return_value = False
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    new_cid = router.replace_sl(
        symbol="NQ", sl_cid="MIA_SL_old", new_sl_price=29985.0,
        direction="long", n_micros=1,
    )
    # Empty = ancien SL preserve, pas de nouveau SL envoye
    assert new_cid == ""
    mock_dtc.cancel_order.assert_called_once()
    # CRITIQUE : send_stop_order NE DOIT PAS etre appele
    mock_dtc.send_stop_order.assert_not_called()


def test_order_router_prod_replace_sl_cancel_uses_require_sid_true():
    """A3 R1 BLOQUANT : verifier que cancel_order est appele avec require_sid=True."""
    from unittest.mock import MagicMock
    cfg = BotBNV4Config.from_env()
    mock_dtc = MagicMock()
    mock_dtc.cancel_order.return_value = True
    mock_dtc.send_stop_order.return_value = "MIA_TRAIL_SL_ok"
    router = OrderRouter(cfg=cfg, dry_run=False, dtc_connector=mock_dtc)
    router.replace_sl(
        symbol="NQ", sl_cid="MIA_SL_old", new_sl_price=29985.0,
        direction="long", n_micros=1,
    )
    # Le call doit avoir require_sid=True (sinon race 2 SL)
    call_kwargs = mock_dtc.cancel_order.call_args.kwargs
    assert call_kwargs.get("require_sid") is True
