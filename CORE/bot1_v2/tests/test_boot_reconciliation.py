"""Tests Fix D3 boot reconciliation broker vs state (INCIDENT #96 13/07).

Contexte incident : Bot 2 (bot1_v2 Sim2) state file avait ES LONG entry 09/07,
mais broker etait FLAT depuis 10/07 (fill listener freeze avait rate le fill).
Chaque restart, D1 _check_position_timeouts detectait "position 13 jours old" et
emettait MARKET CLOSE aveugle -> cascade 9 SHORTs cumul avg 7596.36.

Fix D3 : compare positions store vs broker au BOOT. 4 cas :
  - broker=0 alors state=pos -> clean state (ALIGNED_TO_FLAT)
  - broker=match -> MATCH log INFO
  - broker=mismatch -> CRITICAL emit, PAS d'auto-fix (human review)
  - broker=None (DTC freeze) -> DTC_DOWN log ALERTE, pas d'action

Design : NEVER auto-flatten aveuglement. Si mismatch : STOP + human review.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

# Stub BOT.dtc_connector pour eviter deps sur bot_config.py (module top-level du dir BOT/).
# En prod, le bot est lance depuis la racine avec sys.path incluant BOT/, mais pytest
# tourne depuis la racine sans BOT/ dans sys.path.
import types as _types
_fake_bot_pkg = _types.ModuleType("BOT")
_fake_dtc_module = _types.ModuleType("BOT.dtc_connector")
_fake_dtc_module._to_contract = lambda sym: f"{sym.upper()}U26-CME"  # default stub
sys.modules.setdefault("BOT", _fake_bot_pkg)
sys.modules.setdefault("BOT.dtc_connector", _fake_dtc_module)

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.main import Bot1V2
from CORE.bot1_v2.state.position_store import PositionStore


def _make_fake_bot(state_path: Path, store_positions: dict, broker_qty):
    """Construit un objet minimal ayant les attributs necessaires a
    Bot1V2._reconcile_broker_at_boot, sans instancier tout __init__ (dashboard,
    fill listener, sierra data source, etc.).
    """
    import logging

    cfg = Bot1V2Config()

    store = PositionStore(path=state_path)
    store.load()
    for sym, pos in store_positions.items():
        store.positions[sym] = pos

    mock_dtc = MagicMock()
    mock_dtc.request_position_blocking = MagicMock(return_value=broker_qty)

    mock_router = MagicMock()
    mock_router.dtc = mock_dtc

    mock_state_bridge = MagicMock()

    fake = SimpleNamespace(
        cfg=cfg,
        store=store,
        router=mock_router,
        state_bridge=mock_state_bridge,
        log=logging.getLogger("test_bot1v2_reconcile"),
    )
    return fake, mock_dtc, mock_router, mock_state_bridge


def test_reconcile_dtc_down_skip():
    """Router.dtc None -> emit DTC_DOWN, pas d'action sur store."""
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, _, mock_router, _ = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "LONG", "n_micros": 1}},
            broker_qty=0,
        )
        mock_router.dtc = None

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            Bot1V2._reconcile_broker_at_boot(fake)

        # DTC_DOWN emis
        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_DTC_DOWN" in emitted_codes
        # Store position pas touchee (pas cleanee)
        assert "ES" in fake.store.positions


def test_reconcile_broker_flat_cleans_state():
    """Broker=0 alors state=LONG -> clean state (fill listener freeze scenario)."""
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, mock_dtc, _, mock_state_bridge = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "LONG", "n_micros": 1}},
            broker_qty=0,
        )

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="ESU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        # ALIGNED_TO_FLAT emis
        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT" in emitted_codes
        # Position store cleanee
        assert "ES" not in fake.store.positions or fake.store.positions.get("ES") is None
        # state_bridge.close_position appele avec exit_reason=BOOT_RECONCILE_FLAT
        assert mock_state_bridge.close_position.called
        call_kwargs = mock_state_bridge.close_position.call_args.kwargs
        assert call_kwargs["exit_reason"] == "BOOT_RECONCILE_FLAT"
        assert call_kwargs["outcome"] == "ORPHAN_CLEANED"


def test_reconcile_broker_match_no_action():
    """Broker qty match state (LONG 1 micro -> +1) -> emit MATCH, pas de nettoyage."""
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, _, _, mock_state_bridge = _make_fake_bot(
            state_path=state_path,
            store_positions={"NQ": {"direction": "LONG", "n_micros": 2}},
            broker_qty=2,  # match expected_qty=+2
        )

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="NQU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_MATCH" in emitted_codes
        # Position PAS cleanee
        assert "NQ" in fake.store.positions
        # state_bridge.close_position PAS appele
        mock_state_bridge.close_position.assert_not_called()


def test_reconcile_mismatch_critical_no_auto_fix():
    """Broker qty DIFFERENT du state (SHORT 1 attendu = -1, mais broker=+3 LONG).

    Cas cauchemar : cascade cumul en cours. Fix D3 doit emit CRITIQUE et
    ne PAS auto-fix (intervention humaine requise via flatten_bot.py).
    """
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, _, _, mock_state_bridge = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "SHORT", "n_micros": 1}},
            broker_qty=3,  # mismatch violent (expected=-1)
        )

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="ESU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_MISMATCH_CRITICAL" in emitted_codes
        # Position PAS cleanee (safety net, human review requis)
        assert "ES" in fake.store.positions
        # state_bridge.close_position PAS appele (pas d'auto-fix)
        mock_state_bridge.close_position.assert_not_called()


def test_reconcile_broker_returns_none_open_orders_query_fail_skip():
    """Broker request_position_blocking retourne None + open_orders query fail
    (both DTC freeze) -> DTC_DOWN skip safe (R2 tiebreaker fail).
    """
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, mock_dtc, _, mock_state_bridge = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "LONG", "n_micros": 1}},
            broker_qty=None,
        )
        # Tiebreaker fail aussi (DTC completement freeze)
        mock_dtc.request_open_orders_blocking = MagicMock(return_value=None)

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="ESU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_DTC_DOWN" in emitted_codes
        # Position pas touchee (safe fallback)
        assert "ES" in fake.store.positions
        mock_state_bridge.close_position.assert_not_called()


def test_reconcile_empty_store_no_action():
    """Store vide -> boucle vide, aucun emit."""
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, _, _, _ = _make_fake_bot(
            state_path=state_path,
            store_positions={},
            broker_qty=0,
        )

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            Bot1V2._reconcile_broker_at_boot(fake)

        # Aucun emit (store vide)
        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_START" not in emitted_codes
        assert "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT" not in emitted_codes


def test_reconcile_r1_orphan_working_orders_cancelled_on_flat():
    """R1 code-reviewer 13/07 : path broker=0 doit cancel les Working orders
    orphelins avant clean state (fill_listener freeze scenario).
    """
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, mock_dtc, _, _ = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "LONG", "n_micros": 1}},
            broker_qty=0,
        )
        # Simule 2 orphelins TP + SL residuels
        mock_dtc.request_open_orders_blocking = MagicMock(return_value=[
            {"ClientOrderID": "MIA_TP_ORPH_1", "OrderStatus": 4},
            {"ClientOrderID": "MIA_SL_ORPH_2", "OrderStatus": 4},
        ])
        mock_dtc.cancel_order = MagicMock(return_value=True)

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="ESU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        # 2 orphelins cancelles
        assert mock_dtc.cancel_order.call_count == 2
        for call in mock_dtc.cancel_order.call_args_list:
            assert call.kwargs.get("trade_account") == "Sim2"
        # Codes log R1 emis
        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert emitted_codes.count("BOT1V2_BOOT_RECONCILE_ORPHAN_CANCELLED") == 2
        assert "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT" in emitted_codes


def test_reconcile_r2_tiebreaker_no_working_orders_aligns_flat():
    """R2 code-reviewer 13/07 : broker_qty=None + 0 Working orders -> tiebreaker
    haute confiance broker flat, aligne state. Empirique cascade #96 : SC ne
    repond pas Type 306 pour compte flat.
    """
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, mock_dtc, _, mock_state_bridge = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "LONG", "n_micros": 1}},
            broker_qty=None,  # SC silent
        )
        # 0 Working orders -> confirme broker flat
        mock_dtc.request_open_orders_blocking = MagicMock(return_value=[])

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="ESU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT" in emitted_codes
        # Position store cleanee via tiebreaker
        assert "ES" not in fake.store.positions or fake.store.positions.get("ES") is None
        # state_bridge close appelee
        assert mock_state_bridge.close_position.called
        # Le kwargs tiebreaker doit etre trace dans l'emit
        aligned_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT"
        ]
        assert len(aligned_calls) == 1
        assert aligned_calls[0][1].get("tiebreaker") == "no_working_orders"


def test_reconcile_r2_tiebreaker_working_orders_present_skip():
    """R2 code-reviewer 13/07 : broker_qty=None + Working orders presents ->
    ambiguite reelle DTC freeze -> DTC_DOWN skip (safe).
    """
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, mock_dtc, _, mock_state_bridge = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "LONG", "n_micros": 1}},
            broker_qty=None,
        )
        mock_dtc.request_open_orders_blocking = MagicMock(return_value=[
            {"ClientOrderID": "MIA_SL_XXX", "OrderStatus": 4},
        ])

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="ESU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        # PAS d'ALIGNED_TO_FLAT (Working orders indiquent position possible)
        assert "BOT1V2_BOOT_RECONCILE_ALIGNED_TO_FLAT" not in emitted_codes
        # DTC_DOWN emis
        assert "BOT1V2_BOOT_RECONCILE_DTC_DOWN" in emitted_codes
        # Store PAS touche
        assert "ES" in fake.store.positions
        mock_state_bridge.close_position.assert_not_called()


def test_reconcile_short_position_broker_short_match():
    """Store SHORT 2 -> expected_qty=-2, broker=-2 -> MATCH."""
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        fake, _, _, mock_state_bridge = _make_fake_bot(
            state_path=state_path,
            store_positions={"ES": {"direction": "SHORT", "n_micros": 2}},
            broker_qty=-2,  # match expected_qty=-2
        )

        with patch("CORE.bot1_v2.main.bot_log.emit") as mock_emit:
            with patch("BOT.dtc_connector._to_contract", return_value="ESU26-CME"):
                Bot1V2._reconcile_broker_at_boot(fake)

        emitted_codes = [c[0][0] for c in mock_emit.call_args_list]
        assert "BOT1V2_BOOT_RECONCILE_MATCH" in emitted_codes
        assert "BOT1V2_BOOT_RECONCILE_MISMATCH_CRITICAL" not in emitted_codes
