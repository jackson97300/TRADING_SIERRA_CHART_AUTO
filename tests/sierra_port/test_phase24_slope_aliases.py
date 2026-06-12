"""Tests Phase 2.4 - aliases canoniques delta_div_slope_* (additive non-breaking).

Verifie que :
  1. divergences_v2.update() emet 6 aliases delta_div_slope_* en plus
  2. Chaque alias = valeur identique au feature original equivalent
  3. _empty_features() emet aussi aliases avec defaults coherents
  4. Anciens noms preserve pour consumers existants (non-breaking)

Cf INCIDENT_LOG #51 + CORE/divergences_v2.py docstring complete.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# Mapping aliases : (ancien_nom, nouveau_alias_slope)
ALIASES_MAPPING = [
    ("delta_div_buy", "delta_div_slope_buy"),
    ("delta_div_sell", "delta_div_slope_sell"),
    ("delta_div_strength", "delta_div_slope_strength"),
    ("delta_div_buy_clean", "delta_div_slope_buy_clean"),
    ("delta_div_sell_clean", "delta_div_slope_sell_clean"),
    ("delta_divergence_clean", "delta_div_slope_clean"),
]


def test_aliases_emitted_in_update():
    """Phase 2.4 : update() emet 6 aliases delta_div_slope_* en plus."""
    from CORE.divergences_v2 import DivergencesV2Calculator
    calc = DivergencesV2Calculator()
    out = {}
    for i in range(15):
        out = calc.update(close=100.0 + i, delta_bar=10.0, atr=5.0)
    # 6 aliases doivent etre presents
    for old, new in ALIASES_MAPPING:
        assert new in out, f"Alias manquant : {new}"


def test_aliases_equal_originals():
    """Chaque alias slope_* doit avoir VALEUR IDENTIQUE au feature original."""
    from CORE.divergences_v2 import DivergencesV2Calculator
    calc = DivergencesV2Calculator()
    # Warmup + plusieurs barres pour avoir divergence active
    out = {}
    for i in range(30):
        # Buy div : price down, delta up
        out = calc.update(close=100.0 - i * 0.5, delta_bar=50.0 + i * 30.0, atr=5.0)

    for old, new in ALIASES_MAPPING:
        old_val = out.get(old)
        new_val = out.get(new)
        # Gestion NaN
        if isinstance(old_val, float) and math.isnan(old_val):
            assert isinstance(new_val, float) and math.isnan(new_val), \
                f"{new} doit etre NaN comme {old}"
        else:
            assert old_val == new_val, \
                f"Mismatch alias {new}={new_val!r} vs {old}={old_val!r}"


def test_aliases_in_empty_features():
    """_empty_features() doit aussi emettre les 6 aliases avec defaults."""
    from CORE.divergences_v2 import DivergencesV2Calculator
    out = DivergencesV2Calculator._empty_features()
    for old, new in ALIASES_MAPPING:
        assert new in out, f"Alias absent _empty_features : {new}"


def test_dict_count_21_keys():
    """Apres Phase 2.4 : dict update() doit avoir 21 keys (15 originales + 6 aliases)."""
    from CORE.divergences_v2 import DivergencesV2Calculator
    calc = DivergencesV2Calculator()
    out = {}
    for i in range(15):
        out = calc.update(close=100.0 + i, delta_bar=10.0, atr=5.0)
    assert len(out) == 21


def test_anciens_noms_preserves_non_breaking():
    """Phase 2.4 = non-breaking : anciens noms preserves pour consumers existants."""
    from CORE.divergences_v2 import DivergencesV2Calculator
    calc = DivergencesV2Calculator()
    out = {}
    for i in range(15):
        out = calc.update(close=100.0 + i, delta_bar=10.0, atr=5.0)
    # Tous les anciens noms doivent etre presents
    for old, _ in ALIASES_MAPPING:
        assert old in out, f"Ancien nom CASSE : {old}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
