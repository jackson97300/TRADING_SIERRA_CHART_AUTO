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


def test_order_router_dry_run_replace_sl_no_op():
    """replace_sl en dry-run no-op (True silencieux)."""
    cfg = BotBNV4Config.from_env()
    router = OrderRouter(cfg=cfg, dry_run=True)
    ok = router.replace_sl(
        symbol="NQ", sl_cid="BOTBN_SL_dummy", new_sl_price=29985.0,
        direction="long", n_micros=1,
    )
    assert ok is True
