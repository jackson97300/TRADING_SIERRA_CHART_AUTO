"""Tests TREND DAY override pour ChaseTopGate (Bot 1 + Bot 2 V6).

Audit walk-forward 12 folds 07/05/2026 :
  - ChaseTopGate seuil 60% : DSR INSTABLE → pas d'edge stable
  - TREND LONG day (pct_in_range median 60bars >= 80%) : LONG @ range_pos 70-90% =
    +1.31t a +1.38t mean_pnl mieux que non-trend day
  - 9/12 folds NQ delta positif

Reference : CORE/research/audit_chasetop_trendday_walkforward.py

Tests valident la detection TREND DAY (3 conditions cumulatives) avant
implementer le bypass dans ChaseTopGate.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import pytest


# Force _TREND_DAY_OVERRIDE_ENABLED=True pour tous les tests sauf P0.2 default_off.
# P0.2 fix : default est OFF (env var unset → False) car backtest realiste pas fait.
@pytest.fixture(autouse=True)
def _force_trend_day_enabled(request):
    """Force enable pour les tests, sauf test_p02_default_off qui valide le default."""
    if request.node.name == "test_p02_default_off":
        yield
        return
    import CORE.mia_paper_trader as bot1_mod
    import CORE.mia2_brain_v6_databento as bot2_mod
    prev_b1 = bot1_mod._TREND_DAY_OVERRIDE_ENABLED
    prev_b2 = bot2_mod._TREND_DAY_OVERRIDE_ENABLED
    bot1_mod._TREND_DAY_OVERRIDE_ENABLED = True
    bot2_mod._TREND_DAY_OVERRIDE_ENABLED = True
    yield
    bot1_mod._TREND_DAY_OVERRIDE_ENABLED = prev_b1
    bot2_mod._TREND_DAY_OVERRIDE_ENABLED = prev_b2


# ─── Bot 1 _is_trend_day ────────────────────────────────────────────────

def test_bot1_trend_day_long_all_conditions_met():
    """LONG day confirme : trend_votes>=6, favor=LONG, median range_pos >= 80."""
    from CORE.mia_paper_trader import _is_trend_day

    regime_data = {
        "regime_trend_votes": 8,
        "regime_favor": "LONG",
    }
    # 60 bars avec range_pos eleve (median >= 80)
    rp_history = [85.0, 90.0, 88.0, 95.0, 80.0, 92.0] * 10  # 60 bars
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is True
    assert reason == "TREND_DAY_OK"


def test_bot1_trend_day_long_trend_votes_too_low():
    """trend_votes < 6 → NOT trend day."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 4, "regime_favor": "LONG"}
    rp_history = [90.0] * 60
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is False
    assert "trend_votes_4" in reason


def test_bot1_trend_day_long_favor_mismatch():
    """regime_favor=SHORT mais direction=LONG → NOT trend day."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 8, "regime_favor": "SHORT"}
    rp_history = [90.0] * 60
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is False
    assert "favor_SHORT_not_LONG" in reason


def test_bot1_trend_day_long_range_pos_too_low():
    """median range_pos < 80 → NOT LONG trend day."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 8, "regime_favor": "LONG"}
    rp_history = [50.0] * 60  # median 50 < 80
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is False
    assert "median_range_50.0" in reason


def test_bot1_trend_day_short_all_conditions_met():
    """SHORT day confirme : trend_votes>=6, favor=SHORT, median range_pos <= 20."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 7, "regime_favor": "SHORT"}
    rp_history = [10.0, 5.0, 18.0, 15.0, 8.0, 12.0] * 10
    is_td, reason = _is_trend_day("SHORT", regime_data, rp_history)
    assert is_td is True
    assert reason == "TREND_DAY_OK"


def test_bot1_trend_day_short_range_pos_too_high():
    """SHORT direction mais median range_pos > 20 → NOT SHORT trend day."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 8, "regime_favor": "SHORT"}
    rp_history = [50.0] * 60
    is_td, reason = _is_trend_day("SHORT", regime_data, rp_history)
    assert is_td is False
    assert "median_range_50.0" in reason


def test_bot1_trend_day_history_too_short():
    """Buffer < lookback / 2 → reject (insufficient data)."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 8, "regime_favor": "LONG"}
    rp_history = [90.0] * 5  # tres peu de data
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is False
    assert "insufficient" in reason or "too_short" in reason


def test_bot1_trend_day_empty_history():
    """Buffer vide → reject (insufficient)."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 8, "regime_favor": "LONG"}
    rp_history = []
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is False
    assert "insufficient" in reason


def test_bot1_trend_day_invalid_history_values():
    """Buffer avec valeurs non-float → reject."""
    from CORE.mia_paper_trader import _is_trend_day
    regime_data = {"regime_trend_votes": 8, "regime_favor": "LONG"}
    rp_history = ["invalid"] * 60
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is False
    # Apres filter None et conversion float fail → too_short
    assert "invalid" in reason or "too_short" in reason


def test_bot1_trend_day_disabled_via_env(monkeypatch):
    """MIA_TREND_DAY_OVERRIDE_ENABLED=0 → toujours False."""
    # Le module est deja import, on teste juste avec le flag actuel.
    # Pour vrai test env var, faut reload module (complique).
    # On valide juste la logique : si flag _TREND_DAY_OVERRIDE_ENABLED == False, return False.
    import CORE.mia_paper_trader as bot1_mod
    original = bot1_mod._TREND_DAY_OVERRIDE_ENABLED
    bot1_mod._TREND_DAY_OVERRIDE_ENABLED = False
    try:
        regime_data = {"regime_trend_votes": 8, "regime_favor": "LONG"}
        rp_history = [90.0] * 60
        is_td, reason = bot1_mod._is_trend_day("LONG", regime_data, rp_history)
        assert is_td is False
        assert reason == "TREND_DAY_DISABLED"
    finally:
        bot1_mod._TREND_DAY_OVERRIDE_ENABLED = original


# ─── Bot 2 V6 _is_trend_day (meme logique, duplication module) ─────────

def test_bot2_v6_trend_day_long_all_conditions_met():
    """Bot 2 V6 : meme logique que Bot 1, doit produire meme resultat."""
    from CORE.mia2_brain_v6_databento import _is_trend_day
    regime_data = {"regime_trend_votes": 8, "regime_favor": "LONG"}
    rp_history = [90.0] * 60
    is_td, reason = _is_trend_day("LONG", regime_data, rp_history)
    assert is_td is True
    assert reason == "TREND_DAY_OK"


def test_bot2_v6_trend_day_short_at_bottom():
    """Bot 2 V6 SHORT trend day."""
    from CORE.mia2_brain_v6_databento import _is_trend_day
    regime_data = {"regime_trend_votes": 7, "regime_favor": "SHORT"}
    rp_history = [10.0] * 60
    is_td, reason = _is_trend_day("SHORT", regime_data, rp_history)
    assert is_td is True
    assert reason == "TREND_DAY_OK"


# ─── Edge cases reels (depuis logs Bot 1 06/05) ─────────────────────────

def test_real_case_06_05_trade_blocked_should_pass_with_trend_day():
    """Cas reel observe 06/05 : ES LONG range_pos=96.9% bloque par ChaseTopGate.
    Avec 8 trend_votes + favor=LONG + sustained range_pos > 80 → bypass.
    """
    import CORE.mia_paper_trader as bot1_mod
    bot1_mod._TREND_DAY_OVERRIDE_ENABLED = True  # force enable pour test
    try:
        regime_data = {
            "regime_trend_votes": 8,
            "regime_favor": "LONG",
        }
        rp_history = [70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 96.0, 97.0, 96.9, 100.0] * 6
        is_td, reason = bot1_mod._is_trend_day("LONG", regime_data, rp_history)
        assert is_td is True, f"Reel cas 06/05 doit etre TREND_DAY_OK, recu : {reason}"
    finally:
        bot1_mod._TREND_DAY_OVERRIDE_ENABLED = False


# ─── P0.1 INTEGRATION TESTS — verifie cles NATIVES dict reg dashboard ─────

def test_p01_native_keys_mode_trend_votes_and_favor_work():
    """P0.1 fix : le dict `reg` du dashboard utilise `mode_trend_votes` et `favor`.
    Sans le lookup defensif, _is_trend_day lirait les mauvaises cles → bypass mort.
    Test : passe le dict EXACTEMENT comme il vient de instr['regime'] du dashboard.
    """
    import CORE.mia_paper_trader as bot1_mod
    bot1_mod._TREND_DAY_OVERRIDE_ENABLED = True
    try:
        # Cas reproduisant exactement instr["regime"] reel (cf mia_paper_trader:1175-1177)
        reg_native = {
            "mode_trend_votes": 8,         # cle native
            "favor": "LONG",                # cle native
            "range_pos": 95.0,
            # NOTA : pas de cles `regime_trend_votes` ni `regime_favor` ici !
        }
        rp_history = [88.0] * 60
        is_td, reason = bot1_mod._is_trend_day("LONG", reg_native, rp_history)
        assert is_td is True, \
            f"P0.1 fix doit accepter cles natives : recu {reason}"
    finally:
        bot1_mod._TREND_DAY_OVERRIDE_ENABLED = False


def test_p01_normalized_keys_still_work():
    """Backward compat : les cles normalisees (regime_trend_votes/regime_favor) marchent encore."""
    import CORE.mia_paper_trader as bot1_mod
    bot1_mod._TREND_DAY_OVERRIDE_ENABLED = True
    try:
        reg_normalized = {
            "regime_trend_votes": 7,
            "regime_favor": "LONG",
        }
        rp_history = [85.0] * 60
        is_td, _ = bot1_mod._is_trend_day("LONG", reg_normalized, rp_history)
        assert is_td is True
    finally:
        bot1_mod._TREND_DAY_OVERRIDE_ENABLED = False


def test_p01_priority_normalized_over_native():
    """Si les 2 cles presentes, normalisee gagne (P0.1 lookup chain)."""
    import CORE.mia_paper_trader as bot1_mod
    bot1_mod._TREND_DAY_OVERRIDE_ENABLED = True
    try:
        reg = {
            "regime_trend_votes": 8,    # priority
            "mode_trend_votes": 2,      # ignored
            "regime_favor": "LONG",
            "favor": "SHORT",            # ignored
        }
        rp_history = [85.0] * 60
        is_td, _ = bot1_mod._is_trend_day("LONG", reg, rp_history)
        assert is_td is True


    finally:
        bot1_mod._TREND_DAY_OVERRIDE_ENABLED = False


def test_p02_default_off():
    """P0.2 fix : default OFF jusqu'a backtest TP/SL realistes confirme edge.

    Verifie que le bot reload module avec env var unset (default) → flag OFF.
    """
    import importlib
    import os as _os
    # Save state actuel
    prev_env = _os.environ.pop("MIA_TREND_DAY_OVERRIDE_ENABLED", None)
    try:
        import CORE.mia_paper_trader as bot1_mod
        importlib.reload(bot1_mod)
        assert bot1_mod._TREND_DAY_OVERRIDE_ENABLED is False, \
            "Default doit etre OFF (P0.2 fix data mining trap)"
    finally:
        if prev_env is not None:
            _os.environ["MIA_TREND_DAY_OVERRIDE_ENABLED"] = prev_env
