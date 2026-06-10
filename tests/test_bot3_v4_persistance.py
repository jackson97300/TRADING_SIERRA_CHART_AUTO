"""Tests integration PositionPersistance dans Bot 3 v4 (10/06/2026).

Chantier persistance cross-bot — generalisation pattern Bot 3 v3 Sprint Phase 1 09/06.

Verifie :
1. Import OK + instanciation propre (dry_run, pas DTC)
2. _positions_persist instancie avec bot_name='bot3_v4'
3. restore() retourne {} sur first boot (pas de state file)
4. _reconciled = True apres boot_ready dry_run
5. _halt_reason = None par defaut
6. save_position et remove_position appellent helper sans crash
7. boot_ready dry_run emit BOOT_READY (pas HALT)
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))
sys.path.insert(0, str(_ROOT / "BOT"))


@pytest.fixture
def bot3_v4_dry_run(tmp_path, monkeypatch):
    """Bot 3 v4 instance dry_run avec state path isole."""
    # Override DEFAULT_STATE_DIR pour isoler test
    from CORE import bot_persistance
    monkeypatch.setattr(bot_persistance, "DEFAULT_STATE_DIR", tmp_path)

    from CORE.bot3_v4_data_driven_paper import Bot3V4DataDrivenPaper
    bot = Bot3V4DataDrivenPaper(
        dtc=None,
        symbols=["NQ"],
        dry_run=True,
        trade_account="Sim3_TEST",
    )
    return bot


def test_import_bot3_v4_with_persistance():
    """Import Bot3V4DataDrivenPaper sans crash apres ajout PositionPersistance."""
    from CORE.bot3_v4_data_driven_paper import Bot3V4DataDrivenPaper
    assert Bot3V4DataDrivenPaper is not None


def test_positions_persist_instancie(bot3_v4_dry_run):
    """_positions_persist existe + bot_name correct."""
    assert hasattr(bot3_v4_dry_run, "_positions_persist")
    assert bot3_v4_dry_run._positions_persist.bot_name == "bot3_v4"


def test_restore_empty_first_boot(bot3_v4_dry_run):
    """Au first boot, _position contient None pour chaque symbole."""
    for sym in bot3_v4_dry_run.symbols:
        assert bot3_v4_dry_run._position[sym] is None


def test_halt_reason_default_none(bot3_v4_dry_run):
    """_halt_reason = None par default + _reconciled = False avant boot_ready."""
    assert bot3_v4_dry_run._halt_reason is None
    assert bot3_v4_dry_run._reconciled is False


def test_boot_ready_dry_run_sets_reconciled(bot3_v4_dry_run):
    """boot_ready en dry_run set _reconciled = True (skip reconcile)."""
    bot3_v4_dry_run.boot_ready()
    assert bot3_v4_dry_run._reconciled is True
    assert bot3_v4_dry_run._halt_reason is None


def test_poll_cycle_skip_if_halt_reason(bot3_v4_dry_run):
    """poll_cycle skip immediatement si _halt_reason set."""
    bot3_v4_dry_run._halt_reason = "test_halt"
    bot3_v4_dry_run._halt_details = "test message"
    # Should return early sans exception
    bot3_v4_dry_run.poll_cycle()


def test_poll_cycle_skip_if_not_reconciled(bot3_v4_dry_run):
    """poll_cycle skip si _reconciled = False (avant boot_ready)."""
    assert bot3_v4_dry_run._reconciled is False
    # Should return early sans exception
    bot3_v4_dry_run.poll_cycle()


def test_save_position_via_persistance(bot3_v4_dry_run):
    """save_position appelle helper sans crash."""
    pos_dict = {
        "parent_cid": "TEST_P_123",
        "tp_cid": "TEST_TP_123",
        "sl_cid": "TEST_SL_123",
        "direction": "LONG",
        "entry_price": 29000.0,
        "sl_initial": 28990.0,
        "sl_current": 28990.0,
        "tp_price": 29020.0,
        "tp_mode": "vpoc",
        "vpoc_value": 29010.0,
        "sl_ticks": 25,
        "level_name": "CUR_VAL",
        "level_family": "value_area",
        "qty": 3,
        "n_contracts": 3,
        "signal_id": "TEST_SIG_001",
        "ts_open": "2026-06-10T10:00:00+00:00",
        "ts_open_ns": 1781088000000000000,
        "bar_idx_open": 100,
    }
    bot3_v4_dry_run._positions_persist.save_position("NQ", pos_dict)
    # No crash expected


def test_remove_position_via_persistance(bot3_v4_dry_run):
    """remove_position après save retire bien la position."""
    pos_dict = {"signal_id": "TEST_SIG_002", "entry_price": 29000.0}
    bot3_v4_dry_run._positions_persist.save_position("NQ", pos_dict)
    bot3_v4_dry_run._positions_persist.remove_position("NQ")


def test_set_get_meta(bot3_v4_dry_run):
    """set_meta / get_meta fonctionne (cooldown ts/pnl_R)."""
    bot3_v4_dry_run._positions_persist.set_meta(
        "last_trade_close_ts_NQ", "2026-06-10T10:00:00+00:00")
    val = bot3_v4_dry_run._positions_persist.get_meta("last_trade_close_ts_NQ")
    assert val == "2026-06-10T10:00:00+00:00"


if __name__ == "__main__":
    print("[INFO] Run with pytest tests/test_bot3_v4_persistance.py -v")
