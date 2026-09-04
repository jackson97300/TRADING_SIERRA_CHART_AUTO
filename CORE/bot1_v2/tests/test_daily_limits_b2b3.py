"""Tests B2/B3 (INCIDENT_LOG #67) : compteur trades a l'OUVERTURE + snapshot
persistance. Garantit que le plafond Mark Douglas mord avant tout close et que
le legacy Bot 1 v2 (update_after_trade) reste inchange.
"""
from __future__ import annotations

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate


def _gate():
    g = DailyLimitsGate(Bot1V2Config())
    g.reset_for_new_day("2026-06-18")
    return g


def test_register_open_increments_count_only():
    g = _gate()
    g.register_open()
    g.register_open()
    assert g.state.n_trades_today == 2
    assert g.state.cumul_pnl_usd == 0.0


def test_apply_pnl_does_not_increment_count():
    g = _gate()
    g.register_open()
    g.apply_pnl(-50.0)
    assert g.state.n_trades_today == 1  # PAS 2 (B2 : pas de double compte)
    assert g.state.cumul_pnl_usd == -50.0


def test_snapshot_restore_roundtrip():
    g = _gate()
    g.register_open()
    g.apply_pnl(30.0)
    snap = g.snapshot()
    g2 = DailyLimitsGate(Bot1V2Config())
    g2.restore(**snap)
    assert g2.state.n_trades_today == 1
    assert g2.state.cumul_pnl_usd == 30.0
    assert g2.state.date_str == "2026-06-18"


def test_legacy_update_after_trade_unchanged():
    # Bot 1 v2 (Sim2) utilise update_after_trade : compte + pnl ensemble.
    # Comportement legacy STRICTEMENT preserve (non touche par B2/B3).
    g = _gate()
    g.update_after_trade(-20.0)
    assert g.state.n_trades_today == 1
    assert g.state.cumul_pnl_usd == -20.0


def test_max_trades_cap_mords_a_l_ouverture():
    # B2 : le plafond doit mordre apres N ouvertures, AVANT tout close.
    cfg = Bot1V2Config()
    g = DailyLimitsGate(cfg)
    g.reset_for_new_day("2026-06-18")
    n_max = cfg.MAX_TRADES_PER_DAY
    for _ in range(n_max):
        assert g.check_allow_entry().allowed is True
        g.register_open()
    # Plafond atteint a l'ouverture, sans qu'aucun trade ne soit ferme.
    assert g.check_allow_entry().allowed is False
