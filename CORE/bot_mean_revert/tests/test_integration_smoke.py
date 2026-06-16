"""Test integration smoke Bot MR : init dry-run sans crash."""
from __future__ import annotations

import logging

import pytest

from CORE.bot_mean_revert.config import BotMRConfig
from CORE.bot_mean_revert.main import BotMR


def test_botmr_init_dry_run(tmp_path, monkeypatch):
    """Le bot doit s'initialiser en dry-run sans crash, meme sans data dispo."""
    # Redirect MIA_ROOT vers tmp pour eviter pollution du repo
    monkeypatch.setenv("MIA_ROOT", str(tmp_path))
    monkeypatch.setenv("MIA_LOG_DIR", str(tmp_path / "LOGS"))

    cfg = BotMRConfig()
    bot = BotMR(symbols=["ES", "NQ"], cfg=cfg, dry_run=True, dtc_connector=None)
    assert bot.symbols == ["ES", "NQ"]
    assert bot.dry_run is True
    assert bot.cfg.TRADE_ACCOUNT == "Sim1"
    # Les engines doivent etre crees par symbole
    assert "ES" in bot.engines
    assert "NQ" in bot.engines
    # Data sources crees
    assert "ES" in bot.data_sources
    assert "NQ" in bot.data_sources
    # Daily gate initialise pour aujourd'hui
    assert bot.daily_gate.state.date_str != ""
    # Process_symbol sans data dispo retourne None sans crash
    res_es = bot._process_symbol("ES")
    res_nq = bot._process_symbol("NQ")
    assert res_es is None
    assert res_nq is None
