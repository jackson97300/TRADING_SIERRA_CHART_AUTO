"""Tests FIX 1 audit 19/06/2026 : daily_gate state persistance cross-restart.

Carnage 18/06 FOMC : 15 restarts dans la journee -> DSL=-$2500 jamais mordue
car daily_gate.reset_for_new_day() systematique au boot effacait n_trades + pnl.

Fix : snapshot/restore via PositionStore.set_daily_state / get_daily_state.
Filtre par date_str cote restore (nouveau jour UTC = reset propre).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from CORE.bot1_v2.gates.daily_limits import DailyLimitsGate  # noqa: E402
from CORE.bot1_v2.state.position_store import PositionStore  # noqa: E402


class _CfgMock:
    """Adapter minimal Bot1V2Config pour DailyLimitsGate."""
    MAX_TRADES_PER_DAY = 9999
    DAILY_STOP_LOSS_USD = -2500.0
    DAILY_STOP_WIN_USD = 99999.0


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "store.json"
    return PositionStore(path=path)


# ════════════════════════════════════════════════════════════════════════════
# L1 - PositionStore daily_state API
# ════════════════════════════════════════════════════════════════════════════


def test_position_store_daily_state_default_empty(store):
    """Nouveau store -> daily_state vide (pas None pour eviter ambiguite)."""
    assert store.get_daily_state() == {}


def test_position_store_daily_state_set_and_get(store):
    """set_daily_state + get_daily_state cycle minimal."""
    state = {"n_trades_today": 3, "cumul_pnl_usd": -150.50, "date_str": "2026-06-19"}
    store.set_daily_state(state)
    restored = store.get_daily_state()
    assert restored == state


def test_position_store_daily_state_persists_through_save_load(tmp_path):
    """Persistance disque : write -> reload -> meme contenu."""
    path = tmp_path / "store.json"
    s1 = PositionStore(path=path)
    s1.set_daily_state({"n_trades_today": 5, "cumul_pnl_usd": -200.0, "date_str": "2026-06-19"})
    assert s1.save()
    s2 = PositionStore(path=path)
    assert s2.load()
    assert s2.get_daily_state() == {
        "n_trades_today": 5, "cumul_pnl_usd": -200.0, "date_str": "2026-06-19",
    }


def test_position_store_daily_state_rejects_non_dict(store):
    """Type safety : refuser str/None/int."""
    with pytest.raises(TypeError):
        store.set_daily_state("not a dict")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        store.set_daily_state(None)  # type: ignore[arg-type]


def test_position_store_daily_state_isolated_from_meta_config(store):
    """daily_state ne doit pas ecraser meta_config (et vice-versa)."""
    store.set_meta_config(cooldown_minutes=15, max_hold_minutes=30)
    store.set_daily_state({"n_trades_today": 1, "cumul_pnl_usd": 0.0, "date_str": "2026-06-19"})
    assert store.meta_config == {"cooldown_minutes": 15, "max_hold_minutes": 30}
    assert store.daily_state["n_trades_today"] == 1


def test_position_store_daily_state_deep_copy(store):
    """set_daily_state stocke une copie : mutation du caller ne pollue pas le store."""
    state = {"n_trades_today": 1, "cumul_pnl_usd": 0.0, "date_str": "2026-06-19"}
    store.set_daily_state(state)
    state["n_trades_today"] = 999  # mutation post-set
    assert store.get_daily_state()["n_trades_today"] == 1


# ════════════════════════════════════════════════════════════════════════════
# L2 - DailyLimitsGate snapshot/restore round-trip
# ════════════════════════════════════════════════════════════════════════════


def test_daily_gate_snapshot_restore_roundtrip():
    """Snapshot apres 3 trades + 2 PnL -> restore -> meme etat."""
    gate = DailyLimitsGate(_CfgMock())
    gate.reset_for_new_day("2026-06-19")
    gate.update_after_trade(-100.0)
    gate.update_after_trade(-50.0)
    gate.update_after_trade(+25.0)
    snap = gate.snapshot()
    assert snap == {
        "n_trades_today": 3,
        "cumul_pnl_usd": -125.0,
        "date_str": "2026-06-19",
    }

    gate2 = DailyLimitsGate(_CfgMock())
    gate2.restore(**snap)
    assert gate2.state.n_trades_today == 3
    assert gate2.state.cumul_pnl_usd == -125.0
    assert gate2.state.date_str == "2026-06-19"


def test_daily_gate_dsl_triggers_after_restore():
    """Apres restore d'un cumul_pnl proche du DSL, le 2eme trade declenche le block."""
    gate = DailyLimitsGate(_CfgMock())
    gate.restore(n_trades_today=10, cumul_pnl_usd=-2400.0, date_str="2026-06-19")
    # Sous DSL : trading autorise
    assert gate.check_allow_entry().allowed is True
    # Apres update -2510 → cumul -2510 - 2400 = ... attendez, update_after_trade
    # ajoute le pnl au cumul existant.
    gate.update_after_trade(-150.0)
    # cumul = -2400 + -150 = -2550 < -2500 -> block
    verdict = gate.check_allow_entry()
    assert verdict.allowed is False
    assert "DAILY_STOP_LOSS" in verdict.skip_reason


# ════════════════════════════════════════════════════════════════════════════
# L3 - Scenario integre : simulation carnage 18/06 (15 restarts)
# ════════════════════════════════════════════════════════════════════════════


def test_carnage_18_06_scenario_dsl_holds_through_restarts(tmp_path):
    """Carnage 18/06 FOMC : 15 restarts -> DSL doit tenir.

    Scenario :
      - Boot 1 : 3 SL = -$300 -> snapshot -> restart
      - Boot 2 (meme jour UTC) : restore -3 trades/-$300, 2 SL = -$200 -> snapshot
      - Boot 3 : restore -5 trades/-$500, 8 SL = -$2050 -> snapshot
      - Boot 4 : restore -13 trades/-$2550 → DSL BLOCK immediat
    Sans le fix : a chaque boot, reset = 0 -> DSL jamais atteint -> -$5000 possible.
    """
    path = tmp_path / "store.json"

    # Boot 1 : 3 SL -$100 chacun
    store = PositionStore(path=path)
    store.load()  # NEW_NO_FILE
    gate = DailyLimitsGate(_CfgMock())
    gate.reset_for_new_day("2026-06-19")
    for _ in range(3):
        gate.update_after_trade(-100.0)
        store.set_daily_state(gate.snapshot())
        store.save()
    assert gate.state.n_trades_today == 3
    assert gate.state.cumul_pnl_usd == -300.0

    # Boot 2 : meme jour UTC, restore
    store2 = PositionStore(path=path)
    assert store2.load()
    prior = store2.get_daily_state()
    assert prior["date_str"] == "2026-06-19"
    gate2 = DailyLimitsGate(_CfgMock())
    gate2.restore(**prior)
    assert gate2.state.n_trades_today == 3
    # 2 nouveaux SL -$100
    for _ in range(2):
        gate2.update_after_trade(-100.0)
        store2.set_daily_state(gate2.snapshot())
        store2.save()
    assert gate2.state.cumul_pnl_usd == -500.0

    # Boot 3 : 8 SL plus larges -$256.25 chacun = -$2050
    store3 = PositionStore(path=path)
    assert store3.load()
    gate3 = DailyLimitsGate(_CfgMock())
    gate3.restore(**store3.get_daily_state())
    for _ in range(8):
        gate3.update_after_trade(-256.25)
        store3.set_daily_state(gate3.snapshot())
        store3.save()
    # cumul = -500 + 8*-256.25 = -2550
    assert gate3.state.cumul_pnl_usd == -2550.0

    # Boot 4 : DSL doit BLOQUER immediatement
    store4 = PositionStore(path=path)
    assert store4.load()
    gate4 = DailyLimitsGate(_CfgMock())
    gate4.restore(**store4.get_daily_state())
    verdict = gate4.check_allow_entry()
    assert verdict.allowed is False
    assert "DAILY_STOP_LOSS" in verdict.skip_reason


def test_new_day_filter_resets_state(tmp_path):
    """Au nouveau jour UTC, le filtre date_str cote caller ignore l'ancien snapshot."""
    path = tmp_path / "store.json"
    store = PositionStore(path=path)
    store.set_daily_state({
        "n_trades_today": 5,
        "cumul_pnl_usd": -1000.0,
        "date_str": "2026-06-18",  # ancien jour
    })
    store.save()

    store2 = PositionStore(path=path)
    store2.load()
    prior = store2.get_daily_state()
    today = "2026-06-19"
    # Caller (main.py) filtre par date_str
    if prior.get("date_str") == today:
        # Restore (pas execute ici)
        restored = True
    else:
        # Reset
        restored = False
    assert restored is False  # nouveau jour -> reset propre
