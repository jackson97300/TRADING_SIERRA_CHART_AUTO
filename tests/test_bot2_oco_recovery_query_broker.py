"""Tests Bot 2 OCO recovery au boot — fix 30/04/2026 query broker DTC.

Bug observe 30/04 (screen Jackson "ORDRE ORPHELIN BOT 2") :
- ES SHORT @ 7206.50 ouvert avant 13:19 UTC
- 3 restarts successifs aujourd'hui pour deploys
- A chaque restart : `_oco_recovery_boot` annule brackets + archive state.json
- MAIS la position broker reste ACTIVE → orphelin total (sans tracking + sans
  protection)

Fix v2 : avant cancel brackets, query broker via Type 305 (request_position_blocking) :
- broker_qty != 0 → restaurer tracking, NE PAS cancel
- broker_qty == 0 → vraie orphelin → cancel + archive
- broker_qty None (timeout) → conservateur : NE PAS cancel
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


@pytest.fixture
def fake_state_file(tmp_path):
    """Cree un state.json avec 1 position ES."""
    state = {
        "ES": {
            "parent_id": "MIA_P_test",
            "tp_cid": "MIA_TP_test",
            "sl_cid": "MIA_SL_test",
            "tp_sid": "20001",
            "sl_sid": "20002",
            "parent_sid": "20000",
            "side": "SELL",
            "entry": 7200.0,
            "sl_price": 7210.0,
            "tp_price": 7180.0,
            "ts_open": "2026-04-30T13:00:00+00:00",
        }
    }
    fp = tmp_path / "databento_active_positions.json"
    fp.write_text(json.dumps(state), encoding="utf-8")
    return fp


def _build_mock_trader(state_file: Path, broker_qty_response):
    """Mock minimal d'un BotTrader pour tester _reload_active_positions_or_cancel_orphans.

    broker_qty_response : valeur retournee par request_position_blocking
        - int (eg -3) : position active broker
        - 0 : flat broker
        - None : timeout DTC
        - Exception : exception sur query
    """
    from CORE.databento_paper_trader import DatabentoPaperTrader as BotTrader

    trader = BotTrader.__new__(BotTrader)
    trader._active_positions_state_file = state_file
    trader.cfg = MagicMock()
    trader.cfg.trade_account = "Sim2"
    trader.cfg.quantity = 3
    trader.active_positions = {}
    import threading
    trader._pos_lock = threading.Lock()

    # Mock DTC
    trader.dtc = MagicMock()
    trader.dtc._server_order_ids = {}
    if isinstance(broker_qty_response, Exception):
        trader.dtc.request_position_blocking.side_effect = broker_qty_response
    else:
        trader.dtc.request_position_blocking.return_value = broker_qty_response
    trader.dtc.cancel_order = MagicMock()

    # Patch register_oco_pair (pour case position active)
    trader.dtc.register_oco_pair = MagicMock()

    return trader


# ── Tests ──────────────────────────────────────────────────────────


class TestOcoRecoveryQueryBrokerActive:
    """Cas 1 : broker confirme position ACTIVE → restaurer tracking, pas cancel."""

    def test_position_active_restored_no_cancel(self, fake_state_file, monkeypatch):
        # Patch BOT_INSTRUMENTS pour avoir un contract pour ES
        from CORE import databento_paper_trader as dpt
        mock_inst = MagicMock()
        mock_inst.contract = "ESM26-CME"
        monkeypatch.setattr(dpt, "BOT_INSTRUMENTS", {"ES": mock_inst})

        # Broker retourne -3 (SHORT 3 micros, match cfg.quantity)
        trader = _build_mock_trader(fake_state_file, broker_qty_response=-3)

        trader._reload_active_positions_or_cancel_orphans()

        # Position restauree dans active_positions
        assert "ES" in trader.active_positions
        assert trader.active_positions["ES"]["side"] == "SELL"

        # AUCUN cancel envoye
        trader.dtc.cancel_order.assert_not_called()

        # State.json toujours present (pas archive)
        assert fake_state_file.exists()

        # SIDs repopules
        assert trader.dtc._server_order_ids.get("MIA_TP_test") == "20001"
        assert trader.dtc._server_order_ids.get("MIA_SL_test") == "20002"

        # OCO pair re-registered
        trader.dtc.register_oco_pair.assert_called_once_with("MIA_TP_test", "MIA_SL_test")

    def test_position_active_quantity_mismatch_still_restored(self, fake_state_file, monkeypatch):
        """Si broker quantity != expected (partial fill ?), on restaure quand
        meme et on emet STATE_VS_BROKER_MISMATCH."""
        from CORE import databento_paper_trader as dpt
        mock_inst = MagicMock()
        mock_inst.contract = "ESM26-CME"
        monkeypatch.setattr(dpt, "BOT_INSTRUMENTS", {"ES": mock_inst})

        # State dit SELL qty 3 -> expected -3. Broker retourne -2 (partial)
        trader = _build_mock_trader(fake_state_file, broker_qty_response=-2)

        trader._reload_active_positions_or_cancel_orphans()

        # Position restauree quand meme
        assert "ES" in trader.active_positions
        # Pas de cancel
        trader.dtc.cancel_order.assert_not_called()


class TestOcoRecoveryQueryBrokerFlat:
    """Cas 2 : broker FLAT → vraie orphelin → cancel + archive."""

    def test_position_flat_cancel_brackets_archive(self, fake_state_file, monkeypatch):
        from CORE import databento_paper_trader as dpt
        mock_inst = MagicMock()
        mock_inst.contract = "ESM26-CME"
        monkeypatch.setattr(dpt, "BOT_INSTRUMENTS", {"ES": mock_inst})

        # Broker retourne 0 (flat) → vraie orphelin
        trader = _build_mock_trader(fake_state_file, broker_qty_response=0)

        trader._reload_active_positions_or_cancel_orphans()

        # PAS de restauration tracking
        assert "ES" not in trader.active_positions

        # 2 cancels envoyes (tp_cid + sl_cid)
        assert trader.dtc.cancel_order.call_count == 2

        # State.json archive (renomme en .processed.<ts>)
        assert not fake_state_file.exists()
        # Verifier qu'un fichier .processed existe
        archives = list(fake_state_file.parent.glob("*.json.processed.*"))
        assert len(archives) == 1


class TestOcoRecoveryQueryBrokerTimeout:
    """Cas 3 : timeout DTC → conservateur, NE PAS cancel + alerte."""

    def test_position_timeout_skip_cancel_keep_state(self, fake_state_file, monkeypatch):
        from CORE import databento_paper_trader as dpt
        mock_inst = MagicMock()
        mock_inst.contract = "ESM26-CME"
        monkeypatch.setattr(dpt, "BOT_INSTRUMENTS", {"ES": mock_inst})

        # Broker timeout (None)
        trader = _build_mock_trader(fake_state_file, broker_qty_response=None)

        trader._reload_active_positions_or_cancel_orphans()

        # PAS de restauration (etat unknown)
        assert "ES" not in trader.active_positions

        # PAS de cancel (conservateur)
        trader.dtc.cancel_order.assert_not_called()

        # State.json preserve (re-ecrit avec position unknown)
        assert fake_state_file.exists()


class TestOcoRecoveryQueryBrokerException:
    """Cas 4 : exception sur query → conservateur, skip."""

    def test_query_exception_treated_as_unknown(self, fake_state_file, monkeypatch):
        from CORE import databento_paper_trader as dpt
        mock_inst = MagicMock()
        mock_inst.contract = "ESM26-CME"
        monkeypatch.setattr(dpt, "BOT_INSTRUMENTS", {"ES": mock_inst})

        trader = _build_mock_trader(
            fake_state_file,
            broker_qty_response=ConnectionError("DTC down"),
        )
        trader._reload_active_positions_or_cancel_orphans()

        # Exception traitee comme unknown : pas de cancel, state preserve
        trader.dtc.cancel_order.assert_not_called()
        assert fake_state_file.exists()


class TestOcoRecoveryEmptyState:
    """Cas 5 : state.json vide / absent → no-op."""

    def test_empty_state_noop(self, tmp_path):
        # state.json absent
        state_file = tmp_path / "no_state.json"
        from CORE.databento_paper_trader import DatabentoPaperTrader as BotTrader
        trader = BotTrader.__new__(BotTrader)
        trader._active_positions_state_file = state_file
        trader.dtc = MagicMock()

        # Ne doit rien faire (return early)
        trader._reload_active_positions_or_cancel_orphans()
        trader.dtc.request_position_blocking.assert_not_called()
        trader.dtc.cancel_order.assert_not_called()


class TestOcoRecoveryMultiSymMix:
    """Cas 6 (R5 code-reviewer) : multi-symboles mix : ES active + NQ timeout
    → preserve les 2 dans state, restaure ES, NQ reste unknown."""

    def test_es_active_nq_timeout_state_preserves_both(self, tmp_path, monkeypatch):
        """State avec 2 positions ES+NQ : ES broker active, NQ broker timeout.
        Resultat attendu : ES dans active_positions, NQ skip cancel,
        state.json re-ecrit avec les 2."""
        # State avec 2 positions
        state = {
            "ES": {"parent_id": "P_ES", "tp_cid": "TP_ES", "sl_cid": "SL_ES",
                   "tp_sid": "1", "sl_sid": "2", "side": "SELL",
                   "entry": 7200.0, "sl_price": 7210.0, "tp_price": 7180.0,
                   "ts_open": "2026-04-30T13:00:00+00:00"},
            "NQ": {"parent_id": "P_NQ", "tp_cid": "TP_NQ", "sl_cid": "SL_NQ",
                   "tp_sid": "3", "sl_sid": "4", "side": "BUY",
                   "entry": 27000.0, "sl_price": 26980.0, "tp_price": 27040.0,
                   "ts_open": "2026-04-30T13:00:00+00:00"},
        }
        state_file = tmp_path / "databento_active_positions.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")

        # Patch BOT_INSTRUMENTS pour ES + NQ
        from CORE import databento_paper_trader as dpt
        mock_es, mock_nq = MagicMock(), MagicMock()
        mock_es.contract = "ESM26-CME"
        mock_nq.contract = "NQM26-CME"
        monkeypatch.setattr(dpt, "BOT_INSTRUMENTS", {"ES": mock_es, "NQ": mock_nq})

        from CORE.databento_paper_trader import DatabentoPaperTrader as BotTrader
        trader = BotTrader.__new__(BotTrader)
        trader._active_positions_state_file = state_file
        trader.cfg = MagicMock()
        trader.cfg.trade_account = "Sim2"
        trader.cfg.quantity = 3
        trader.active_positions = {}
        import threading
        trader._pos_lock = threading.Lock()
        trader.dtc = MagicMock()
        trader.dtc._server_order_ids = {}
        trader.dtc.cancel_order = MagicMock()
        trader.dtc.register_oco_pair = MagicMock()
        # ES active (-3), NQ timeout (None) — side_effect par symbole_contract
        def mock_query(symbol_contract, **kw):
            if "ESM" in symbol_contract:
                return -3
            elif "NQM" in symbol_contract:
                return None
            return 0
        trader.dtc.request_position_blocking.side_effect = mock_query

        trader._reload_active_positions_or_cancel_orphans()

        # ES restauree (active broker)
        assert "ES" in trader.active_positions
        # NQ NON restauree (timeout = unknown)
        assert "NQ" not in trader.active_positions
        # AUCUN cancel sur ES ni NQ (active + unknown = ne pas cancel)
        trader.dtc.cancel_order.assert_not_called()
        # State.json re-ecrit avec les 2 (active + unknown)
        with open(state_file, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert "ES" in saved
        assert "NQ" in saved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
