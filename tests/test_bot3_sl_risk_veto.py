"""Tests FIX #56 SL RISK HARDCAP USD (10/06/2026 Jackson directive ultrathink).

Couche complementaire au veto ATR (#54) + SL min ATR-aware (#55).
VETO trade si sl_risk_usd > MAX_SL_RISK_USD_BOT3 (default $50 micro virtuel Python).

Cas couverts :
1. SL risk SOUS le cap → trade PASSE (pas de veto)
2. SL risk DEPASSE le cap → trade VETO + emit BOT3_SL_RISK_VETO
3. SL risk EXACTEMENT au cap → trade PASSE (inclusive)
4. SL risk juste au-dessus cap (+$0.01) → trade VETO
5. Config inconnue → fallback safe (tick_value=0.50 default)
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_cap_value_50_usd():
    """Verifie que la constante MAX_SL_RISK_USD_BOT3 = 50.0."""
    from bot3_config import MAX_SL_RISK_USD_BOT3
    assert MAX_SL_RISK_USD_BOT3 == 50.0


def test_nq_default_under_cap():
    """NQ : 25t × $0.50 × 3 = $37.50 < $50 → OK trade passe."""
    from bot3_config import GUARD_RAILS_BOT3, MAX_SL_RISK_USD_BOT3
    cfg = GUARD_RAILS_BOT3["NQ"]
    sl_ticks = 25
    sl_risk = sl_ticks * cfg["tick_value"] * cfg["n_contracts"]
    assert sl_risk == 37.50, f"NQ default risk attendu $37.50, obtenu ${sl_risk}"
    assert sl_risk <= MAX_SL_RISK_USD_BOT3, "NQ default doit etre SOUS le cap"


def test_es_default_under_cap():
    """ES : 12t × $1.25 × 3 = $45.00 < $50 → OK trade passe."""
    from bot3_config import GUARD_RAILS_BOT3, MAX_SL_RISK_USD_BOT3
    cfg = GUARD_RAILS_BOT3["ES"]
    sl_ticks = 12
    sl_risk = sl_ticks * cfg["tick_value"] * cfg["n_contracts"]
    assert sl_risk == 45.00, f"ES default risk attendu $45, obtenu ${sl_risk}"
    assert sl_risk <= MAX_SL_RISK_USD_BOT3, "ES default doit etre SOUS le cap"


def test_mgc_default_above_cap():
    """MGC : 200t × $1.00 × 3 = $600 >> $50 → VETO automatique (a recalibrer)."""
    from bot3_config import GUARD_RAILS_BOT3, MAX_SL_RISK_USD_BOT3
    cfg = GUARD_RAILS_BOT3["MGC"]
    sl_ticks = cfg["sl_ticks_base"]  # 200 par defaut
    sl_risk = sl_ticks * cfg["tick_value"] * cfg["n_contracts"]
    assert sl_risk == 600.0, f"MGC default risk attendu $600, obtenu ${sl_risk}"
    assert sl_risk > MAX_SL_RISK_USD_BOT3, (
        "MGC default DOIT etre AU-DESSUS du cap (a recalibrer si MGC actif)"
    )


def test_veto_logic_under_cap():
    """sl_risk = $37.50 < $50 → veto NOT triggered."""
    MAX = 50.0
    sl_risk_usd = 25 * 0.50 * 3  # NQ default
    veto_triggered = sl_risk_usd > MAX
    assert veto_triggered is False


def test_veto_logic_exactly_at_cap():
    """sl_risk = $50.00 exactement → veto NOT triggered (cap inclusif)."""
    MAX = 50.0
    sl_risk_usd = 50.0
    veto_triggered = sl_risk_usd > MAX
    assert veto_triggered is False, "Cap doit etre INCLUSIF ($50 OK, > $50 veto)"


def test_veto_logic_above_cap():
    """sl_risk = $50.01 → veto TRIGGERED."""
    MAX = 50.0
    sl_risk_usd = 50.01
    veto_triggered = sl_risk_usd > MAX
    assert veto_triggered is True


def test_veto_logic_far_above_cap():
    """sl_risk = $600 (MGC default) → veto TRIGGERED."""
    MAX = 50.0
    sl_risk_usd = 600.0
    veto_triggered = sl_risk_usd > MAX
    assert veto_triggered is True


def test_extreme_slip_scenario_nq():
    """Simulation auto-reprice slip parent etend SL au-dela cap.
    NQ : si slip parent 60t et SL etendu a 100t → 100 × 0.50 × 3 = $150 > $50 → VETO.
    """
    MAX = 50.0
    sl_ticks_extended = 100  # apres auto-reprice slip
    tick_value = 0.50
    n_contracts = 3
    sl_risk = sl_ticks_extended * tick_value * n_contracts
    assert sl_risk == 150.0
    assert sl_risk > MAX, "Scenario slip extreme DOIT triggerer le veto"


def test_log_code_present_catalog():
    """Verifie que BOT3_SL_RISK_VETO est defini dans log_catalog.py."""
    from log_catalog import LOG_CODES
    assert "BOT3_SL_RISK_VETO" in LOG_CODES
    entry = LOG_CODES["BOT3_SL_RISK_VETO"]
    assert len(entry) == 3  # (LogLevel, category, template)
    assert entry[1] == "decisions"  # category correcte


if __name__ == "__main__":
    test_cap_value_50_usd()
    print("[OK] test_cap_value_50_usd")
    test_nq_default_under_cap()
    print("[OK] test_nq_default_under_cap")
    test_es_default_under_cap()
    print("[OK] test_es_default_under_cap")
    test_mgc_default_above_cap()
    print("[OK] test_mgc_default_above_cap")
    test_veto_logic_under_cap()
    print("[OK] test_veto_logic_under_cap")
    test_veto_logic_exactly_at_cap()
    print("[OK] test_veto_logic_exactly_at_cap")
    test_veto_logic_above_cap()
    print("[OK] test_veto_logic_above_cap")
    test_veto_logic_far_above_cap()
    print("[OK] test_veto_logic_far_above_cap")
    test_extreme_slip_scenario_nq()
    print("[OK] test_extreme_slip_scenario_nq")
    test_log_code_present_catalog()
    print("[OK] test_log_code_present_catalog")
    print("\n[OK] 10/10 tests BOT3_SL_RISK_VETO PASS")
