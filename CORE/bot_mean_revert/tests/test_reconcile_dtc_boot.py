"""Tests FIX 2 audit 19/06/2026 : reconcile DTC au boot Bot MR.

5 cas valides (extraits bot_persistance.PositionPersistance):
  OK_FLAT          : Python flat + broker flat -> OK
  OK_RESTORED      : Python pos + broker match -> OK
  PYTHON_GHOST     : Python pos + broker flat -> auto-purge + ALERTE
  UNKNOWN_BROKER   : Python flat + broker pos -> HALT BOOT
  DIVERGENCE       : Python pos + broker mismatch -> HALT BOOT

Bypass HALT via env MIA_BOT_MR_RECONCILE_FORCE_FLAT=1.

Tests fonctionnels via stub DTC (eviter dependance DTC reel pour CI).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.bot_mean_revert.config import BotMRConfig  # noqa: E402
from CORE.bot_mean_revert.main import BotMR  # noqa: E402


class _StubDTC:
    """Stub DTC : retourne qty configure par symbole."""

    def __init__(self, positions: dict | None = None):
        # positions = {"ESU26-CME": 1, "NQU26-CME": -2, ...}
        self._positions = positions or {}
        self.queries: list = []

    def request_position_blocking(
        self, symbol_contract: str, trade_account: str = "Sim3",
        timeout: float = 3.0,
    ):
        self.queries.append((symbol_contract, trade_account))
        return self._positions.get(symbol_contract)


def _build_bot_minimal(tmp_path, dtc_positions=None, store_positions=None):
    """Construit un BotMR fictif minimal sans DTC reel.

    Le constructeur normal cree des SignalEngines + IntermarketGate. On bypass
    en patchant les internals critiques apres construction. Plus simple : on
    instancie via __new__ + on monte la main les attributs necessaires.
    """
    cfg = BotMRConfig()
    # Bypass __init__ et builder a la main les attributs reconcile-relevants
    bot = BotMR.__new__(BotMR)
    bot.cfg = cfg
    bot.symbols = ["ES", "NQ"]
    bot.dry_run = False
    bot.log = MagicMock()

    # Store stub
    from CORE.bot1_v2.state.position_store import PositionStore
    store_path = tmp_path / "store.json"
    bot.store = PositionStore(path=store_path)
    if store_positions:
        for sym, pos in store_positions.items():
            bot.store.open_position(sym, pos)

    # Router stub avec DTC stub
    bot.router = MagicMock()
    bot.router.dtc = _StubDTC(positions=dtc_positions)

    # state_bridge stub
    bot.state_bridge = MagicMock()

    return bot


# ════════════════════════════════════════════════════════════════════════════
# Cas a : OK_FLAT (python flat + broker flat)
# ════════════════════════════════════════════════════════════════════════════


def test_reconcile_ok_flat(tmp_path):
    """ES+NQ tous flat des 2 cotes -> OK, pas de halt."""
    bot = _build_bot_minimal(tmp_path, dtc_positions={"ESU26-CME": 0, "NQU26-CME": 0})
    assert bot._reconcile_with_dtc_at_boot() is True


# ════════════════════════════════════════════════════════════════════════════
# Cas b : OK_RESTORED (python pos match broker)
# ════════════════════════════════════════════════════════════════════════════


def test_reconcile_ok_restored_long(tmp_path):
    """Python ES LONG 1 + broker ES LONG 1 -> OK."""
    store_pos = {
        "ES": {"direction": "LONG", "n_micros": 1, "entry_price": 6000.0}
    }
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={"ESU26-CME": 1, "NQU26-CME": 0},
        store_positions=store_pos,
    )
    assert bot._reconcile_with_dtc_at_boot() is True
    # Position toujours en place apres reconcile OK
    assert "ES" in bot.store.positions


def test_reconcile_ok_restored_short(tmp_path):
    """Python NQ SHORT 2 + broker NQ qty=-2 -> OK."""
    store_pos = {
        "NQ": {"direction": "SHORT", "n_micros": 2, "entry_price": 22000.0}
    }
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={"ESU26-CME": 0, "NQU26-CME": -2},
        store_positions=store_pos,
    )
    assert bot._reconcile_with_dtc_at_boot() is True


# ════════════════════════════════════════════════════════════════════════════
# Cas c : UNKNOWN_BROKER_POS (python flat + broker pos)
# ════════════════════════════════════════════════════════════════════════════


def test_reconcile_unknown_broker_pos_halts(tmp_path, monkeypatch):
    """Python flat mais broker ES LONG 1 -> HALT BOOT (sans force_flat)."""
    monkeypatch.delenv("MIA_BOT_MR_RECONCILE_FORCE_FLAT", raising=False)
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={"ESU26-CME": 1, "NQU26-CME": 0},
    )
    assert bot._reconcile_with_dtc_at_boot() is False


def test_reconcile_unknown_broker_pos_bypass_force_flat(tmp_path, monkeypatch):
    """Avec MIA_BOT_MR_RECONCILE_FORCE_FLAT=1, bypass HALT (Jackson decision)."""
    monkeypatch.setenv("MIA_BOT_MR_RECONCILE_FORCE_FLAT", "1")
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={"ESU26-CME": 1, "NQU26-CME": 0},
    )
    assert bot._reconcile_with_dtc_at_boot() is True


# ════════════════════════════════════════════════════════════════════════════
# Cas d : PYTHON_GHOST (python pos + broker flat) -> auto-purge
# ════════════════════════════════════════════════════════════════════════════


def test_reconcile_python_ghost_auto_purge(tmp_path):
    """Python ES LONG 1 + broker flat -> auto-purge + boot ok (ALERTE)."""
    store_pos = {
        "ES": {"direction": "LONG", "n_micros": 1, "entry_price": 6000.0}
    }
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={"ESU26-CME": 0, "NQU26-CME": 0},
        store_positions=store_pos,
    )
    assert "ES" in bot.store.positions  # avant
    assert bot._reconcile_with_dtc_at_boot() is True
    assert "ES" not in bot.store.positions  # purge silent
    # state_bridge.close_position appele avec exit_reason RECONCILE_GHOST
    bot.state_bridge.close_position.assert_called_once_with(
        "ES", exit_reason="RECONCILE_GHOST",
    )


# ════════════════════════════════════════════════════════════════════════════
# Cas e : DIVERGENCE (direction OU qty diff)
# ════════════════════════════════════════════════════════════════════════════


def test_reconcile_divergence_direction_halts(tmp_path, monkeypatch):
    """Python LONG 1 + broker SHORT 1 -> HALT BOOT."""
    monkeypatch.delenv("MIA_BOT_MR_RECONCILE_FORCE_FLAT", raising=False)
    store_pos = {
        "ES": {"direction": "LONG", "n_micros": 1, "entry_price": 6000.0}
    }
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={"ESU26-CME": -1, "NQU26-CME": 0},
        store_positions=store_pos,
    )
    assert bot._reconcile_with_dtc_at_boot() is False


def test_reconcile_divergence_qty_halts(tmp_path, monkeypatch):
    """Python LONG 1 + broker LONG 3 -> HALT BOOT."""
    monkeypatch.delenv("MIA_BOT_MR_RECONCILE_FORCE_FLAT", raising=False)
    store_pos = {
        "ES": {"direction": "LONG", "n_micros": 1, "entry_price": 6000.0}
    }
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={"ESU26-CME": 3, "NQU26-CME": 0},
        store_positions=store_pos,
    )
    assert bot._reconcile_with_dtc_at_boot() is False


# ════════════════════════════════════════════════════════════════════════════
# Edge cases : DTC query failed, dry_run skip
# ════════════════════════════════════════════════════════════════════════════


def test_reconcile_dtc_query_returns_none_halts(tmp_path):
    """broker_qty=None (DTC pas de reponse) -> CRITIQUE HALT (cf orphan R3)."""
    bot = _build_bot_minimal(
        tmp_path,
        dtc_positions={},  # ESU26 et NQU26 absents -> stub retourne None
    )
    assert bot._reconcile_with_dtc_at_boot() is False


def test_reconcile_no_dtc_dry_run_skips(tmp_path):
    """Pas de DTC (dry_run) -> skip reconcile, boot OK."""
    bot = _build_bot_minimal(tmp_path)
    bot.router = None  # dry-run
    assert bot._reconcile_with_dtc_at_boot() is True


def test_reconcile_dtc_exception_halts(tmp_path):
    """Si request_position_blocking raise -> CRITIQUE HALT."""
    bot = _build_bot_minimal(tmp_path)

    def _raises(*_args, **_kw):
        raise ConnectionError("DTC dead")

    bot.router.dtc.request_position_blocking = _raises
    assert bot._reconcile_with_dtc_at_boot() is False
