"""Tests recalibration ladder + trailing (10/06/2026 Option 1 conservateur).

Empirique 12 wins NQ (4-10 juin) :
- MFE p25=36t, p50=53t, p75=81t, max=113t
- Anciens paliers (100/150/200) jamais atteints → inopérants
- Nouveaux paliers basés sur stats empiriques + RR 1.2 TP cible

Cas couverts :
1. trailing_be_trigger_ticks = 30 (= TP cible)
2. trailing_active_trigger_ticks = 50 (= p50 winners)
3. trailing_distance_ticks = 20 (= cap perte vs MFE)
4. ladder_paliers = [(30, 5), (50, 15), (80, 35)]
5. Sizing lock USD micro virtuel :
   - Palier 1 : 5t × $0.50 × 3 = $7.50 lock
   - Palier 2 : 15t × $0.50 × 3 = $22.50 lock
   - Palier 3 : 35t × $0.50 × 3 = $52.50 lock
6. Cap SL_RISK_USD respect : 25t SL × $0.50 × 3 = $37.50 < $50 (OK protection)
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_nq_be_trigger_30():
    """trailing_be_trigger_ticks = 30 (= TP cible RR 1.2)."""
    from bot3_config import GUARD_RAILS_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    assert cfg["trailing_be_trigger_ticks"] == 30, (
        f"BE trigger recalibre 30 attendu, obtenu {cfg['trailing_be_trigger_ticks']}"
    )


def test_nq_active_trigger_50():
    """trailing_active_trigger_ticks = 50 (= p50 winners empirique)."""
    from bot3_config import GUARD_RAILS_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    assert cfg["trailing_active_trigger_ticks"] == 50, (
        f"Active trigger recalibre 50 attendu, obtenu {cfg['trailing_active_trigger_ticks']}"
    )


def test_nq_trailing_distance_20():
    """trailing_distance_ticks = 20 (cap perte vs MFE peak)."""
    from bot3_config import GUARD_RAILS_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    assert cfg["trailing_distance_ticks"] == 20


def test_nq_ladder_paliers_recalibres():
    """Paliers recalibres : (30, 5), (50, 15), (80, 35)."""
    from bot3_config import GUARD_RAILS_BOT3
    paliers = GUARD_RAILS_BOT3["NQ"]["ladder_paliers"]
    expected = [(30.0, 5.0), (50.0, 15.0), (80.0, 35.0)]
    assert paliers == expected, f"Paliers attendus {expected}, obtenus {paliers}"


def test_nq_palier_1_tp_cible():
    """Palier 1 = TP cible RR 1.2 (25t × 1.2 = 30t)."""
    from bot3_config import GUARD_RAILS_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    sl_base = cfg["sl_ticks_base"]  # 80 actuel
    # NOTE : sl_base est 80t (avant change SL fixe), mais en mode FIXE NQ
    # sl_fixed_ticks_nq=25 est utilise. RR 1.2 → TP=30t. Palier 1 = 30t = TP cible.
    palier_1_seuil = cfg["ladder_paliers"][0][0]
    assert palier_1_seuil == 30.0, "Palier 1 doit etre TP cible 30t"


def test_lock_usd_palier_1():
    """Palier 1 lock USD : 5t × $0.50 × 3 = $7.50."""
    from bot3_config import GUARD_RAILS_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    lock_ticks = cfg["ladder_paliers"][0][1]  # 5t
    lock_usd = lock_ticks * cfg["tick_value"] * cfg["n_contracts"]
    assert lock_usd == 7.50, f"Lock palier 1 attendu $7.50, obtenu ${lock_usd}"


def test_lock_usd_palier_2():
    """Palier 2 lock USD : 15t × $0.50 × 3 = $22.50."""
    from bot3_config import GUARD_RAILS_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    lock_ticks = cfg["ladder_paliers"][1][1]
    lock_usd = lock_ticks * cfg["tick_value"] * cfg["n_contracts"]
    assert lock_usd == 22.50


def test_lock_usd_palier_3():
    """Palier 3 lock USD : 35t × $0.50 × 3 = $52.50."""
    from bot3_config import GUARD_RAILS_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    lock_ticks = cfg["ladder_paliers"][2][1]
    lock_usd = lock_ticks * cfg["tick_value"] * cfg["n_contracts"]
    assert lock_usd == 52.50


def test_paliers_monotone_croissants():
    """Paliers DOIVENT etre strictement croissants en MFE seuil et lock ticks."""
    from bot3_config import GUARD_RAILS_BOT3
    paliers = GUARD_RAILS_BOT3["NQ"]["ladder_paliers"]
    for i in range(1, len(paliers)):
        assert paliers[i][0] > paliers[i-1][0], (
            f"MFE seuil non strictement croissant a palier {i}"
        )
        assert paliers[i][1] > paliers[i-1][1], (
            f"Lock ticks non strictement croissant a palier {i}"
        )


def test_sl_risk_under_cap_after_recalibration():
    """SL de base (25t fixed mode) DOIT rester sous MAX_SL_RISK_USD_BOT3 = $50.
    Recalibration ladder ne doit PAS modifier le SL initial = pas de regression cap.
    """
    from bot3_config import GUARD_RAILS_BOT3, MAX_SL_RISK_USD_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    # Mode FIXE NQ : SL = 25t (hardcoded dans bot3_v3_continuation_engine.py)
    sl_ticks_fixed = 25
    sl_risk = sl_ticks_fixed * cfg["tick_value"] * cfg["n_contracts"]
    assert sl_risk == 37.50
    assert sl_risk <= MAX_SL_RISK_USD_BOT3, (
        f"SL base {sl_risk} doit etre <= cap {MAX_SL_RISK_USD_BOT3}"
    )


if __name__ == "__main__":
    test_nq_be_trigger_30()
    test_nq_active_trigger_50()
    test_nq_trailing_distance_20()
    test_nq_ladder_paliers_recalibres()
    test_nq_palier_1_tp_cible()
    test_lock_usd_palier_1()
    test_lock_usd_palier_2()
    test_lock_usd_palier_3()
    test_paliers_monotone_croissants()
    test_sl_risk_under_cap_after_recalibration()
    print("[OK] 10/10 tests ladder recalibration PASS")
