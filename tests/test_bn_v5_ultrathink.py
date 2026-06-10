"""Tests ULTRATHINK BN V5 — Sprint stabilite (10/06/2026).

Generalisation pattern Bot 3 v3 Sprint Phase 1 09/06 a BN V5.

Verifie :
1. Import OK + instanciation propre
2. _positions_persist instancie avec bot_name='bn_v5'
3. _signal_counter dict initialise pour chaque sym
4. _next_signal_id retourne BN_V5_{SYM}_{YYYYMMDD}_NNNN monotone
5. _make_pos_dict signal_id monotone (PAS uuid)
6. _make_pos_dict qty=3 pour TOUS les sym (PAS qty=1 ES)
7. boot_ready dry_run set _reconciled True
8. poll_cycle skip si halt_reason ou pas reconciled
9. save_position / remove_position via helper OK
"""
from __future__ import annotations
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))
sys.path.insert(0, str(_ROOT / "BOT"))


@pytest.fixture
def bn_v5_dry_run(tmp_path, monkeypatch):
    """BN V5 instance dry_run avec state path isole."""
    # Override PositionPersistance state path
    from CORE import bot_persistance
    monkeypatch.setattr(bot_persistance, "DEFAULT_STATE_DIR", tmp_path)
    # Override _STATE_FILE pour _load_state existant (BUG #1 09/06)
    from CORE import bn_v5_paper
    monkeypatch.setattr(bn_v5_paper, "_STATE_FILE",
                        tmp_path / "bn_v5_session_state.json")

    from CORE.bn_v5_paper import BNV5PaperTrader
    bot = BNV5PaperTrader(
        dtc=None,
        symbols=["NQ", "ES"],
        dry_run=True,
        trade_account="Sim2_TEST",
    )
    return bot


def test_import_bn_v5_ultrathink():
    """Import BNV5PaperTrader sans crash apres integration."""
    from CORE.bn_v5_paper import BNV5PaperTrader
    assert BNV5PaperTrader is not None


def test_positions_persist_instancie(bn_v5_dry_run):
    """_positions_persist existe + bot_name correct."""
    assert hasattr(bn_v5_dry_run, "_positions_persist")
    assert bn_v5_dry_run._positions_persist.bot_name == "bn_v5"


def test_signal_counter_initialise(bn_v5_dry_run):
    """_signal_counter dict initialise pour chaque sym (int >= 0)."""
    assert hasattr(bn_v5_dry_run, "_signal_counter")
    for sym in bn_v5_dry_run.symbols:
        assert isinstance(bn_v5_dry_run._signal_counter[sym], int)
        assert bn_v5_dry_run._signal_counter[sym] >= 0


def test_next_signal_id_format_monotone(bn_v5_dry_run):
    """_next_signal_id retourne format BN_V5_{SYM}_{DATE}_NNNN monotone croissant."""
    nq_start = bn_v5_dry_run._signal_counter["NQ"]
    es_start = bn_v5_dry_run._signal_counter["ES"]

    sid1 = bn_v5_dry_run._next_signal_id("NQ")
    sid2 = bn_v5_dry_run._next_signal_id("NQ")
    sid3 = bn_v5_dry_run._next_signal_id("ES")

    # Format check
    assert sid1.startswith("BN_V5_NQ_")
    assert sid3.startswith("BN_V5_ES_")

    # Monotone croissant
    assert bn_v5_dry_run._signal_counter["NQ"] == nq_start + 2
    assert bn_v5_dry_run._signal_counter["ES"] == es_start + 1
    # sid2 > sid1 lexicographiquement
    assert sid2 > sid1


def test_next_signal_id_persisted_in_meta(bn_v5_dry_run):
    """Counter persiste dans positions_persist meta apres _next_signal_id."""
    bn_v5_dry_run._next_signal_id("NQ")
    bn_v5_dry_run._next_signal_id("NQ")
    counter_meta = bn_v5_dry_run._positions_persist.get_meta("signal_counter_NQ")
    # Counter persiste = match self._signal_counter (peu importe valeur exacte)
    assert counter_meta == bn_v5_dry_run._signal_counter["NQ"]


def test_halt_reason_default_none(bn_v5_dry_run):
    """_halt_reason = None par defaut + _reconciled False avant boot_ready."""
    assert bn_v5_dry_run._halt_reason is None
    assert bn_v5_dry_run._reconciled is False


def test_boot_ready_dry_run_sets_reconciled(bn_v5_dry_run):
    """boot_ready en dry_run set _reconciled = True (skip reconcile)."""
    bn_v5_dry_run.boot_ready()
    assert bn_v5_dry_run._reconciled is True


def test_poll_cycle_skip_if_halt_reason(bn_v5_dry_run):
    """poll_cycle skip immediatement si _halt_reason set."""
    bn_v5_dry_run._halt_reason = "test_halt"
    bn_v5_dry_run._halt_details = "test"
    bn_v5_dry_run.poll_cycle()  # Should return early sans exception


def test_poll_cycle_skip_if_not_reconciled(bn_v5_dry_run):
    """poll_cycle skip si _reconciled = False (avant boot_ready)."""
    assert bn_v5_dry_run._reconciled is False
    bn_v5_dry_run.poll_cycle()  # Should return early sans exception


def test_make_pos_dict_qty_3_partout(bn_v5_dry_run):
    """_make_pos_dict qty=3 pour TOUS les sym (NQ et ES) - FIX 10/06."""
    from CORE.bn_v5_engine import Setup, SIDE_LONG

    setup_nq = Setup(
        pattern="V_LONG", side=SIDE_LONG,
        entry_idx=12, entry_price=29011.0, sl_price=28995.0,
        pivot_price=29000.0, neckline=29010.0,
    )
    setup_es = Setup(
        pattern="V_LONG", side=SIDE_LONG,
        entry_idx=12, entry_price=7403.0, sl_price=7395.0,
        pivot_price=7400.0, neckline=7402.0,
    )

    pos_nq = bn_v5_dry_run._make_pos_dict("NQ", setup_nq, None, None, None)
    pos_es = bn_v5_dry_run._make_pos_dict("ES", setup_es, None, None, None)

    assert pos_nq["qty"] == 3, f"NQ qty doit etre 3, obtenu {pos_nq['qty']}"
    assert pos_es["qty"] == 3, f"ES qty doit etre 3 (FIX 10/06, plus 1), obtenu {pos_es['qty']}"


def test_make_pos_dict_signal_id_monotone(bn_v5_dry_run):
    """_make_pos_dict signal_id monotone via _next_signal_id (PAS uuid)."""
    from CORE.bn_v5_engine import Setup, SIDE_LONG

    setup = Setup(
        pattern="V_LONG", side=SIDE_LONG,
        entry_idx=12, entry_price=29011.0, sl_price=28995.0,
        pivot_price=29000.0, neckline=29010.0,
    )

    pos1 = bn_v5_dry_run._make_pos_dict("NQ", setup, None, None, None)
    pos2 = bn_v5_dry_run._make_pos_dict("NQ", setup, None, None, None)

    # Format monotone, PAS uuid hexdigest
    assert pos1["signal_id"].startswith("BN_V5_NQ_")
    assert pos2["signal_id"].startswith("BN_V5_NQ_")
    assert pos1["signal_id"] != pos2["signal_id"]
    # pos2 counter > pos1 counter (lexicographique car format NNNN padded)
    assert pos2["signal_id"] > pos1["signal_id"]


def test_save_remove_position_via_persistance(bn_v5_dry_run):
    """save_position et remove_position via helper sans crash."""
    pos = {"signal_id": "BN_V5_NQ_TEST_0001", "entry_price": 29000.0}
    bn_v5_dry_run._positions_persist.save_position("NQ", pos)
    bn_v5_dry_run._positions_persist.remove_position("NQ")


if __name__ == "__main__":
    print("[INFO] Run with pytest tests/test_bn_v5_ultrathink.py -v")
