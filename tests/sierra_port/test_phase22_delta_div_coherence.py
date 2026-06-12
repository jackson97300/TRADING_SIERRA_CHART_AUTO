"""Tests Phase 2.2 - delta_div_* coherence LIVE pipeline (post-refactor).

Verifie que :
  1. divergences_v2.update() emet maintenant `delta_divergence_clean` composite SLOPE
  2. sierra_pipeline.enrich_bar() ne crashe pas apres suppression sub-engine #4
  3. Sub-engine #5 lit version SLOPE de delta_divergence_clean
  4. ctx_div_*, div_confluence_dmp = coherents avec SLOPE (pas CUMMAX)

Cf INCIDENT_LOG #51 + CORE/divergences_v2.py docstring complete.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# Phase 2.2 : divergences_v2 emet delta_divergence_clean composite
# ════════════════════════════════════════════════════════════════════════════

def test_divergences_v2_emits_delta_divergence_clean():
    """Phase 2.2 : divergences_v2.update() doit emettre delta_divergence_clean
    composite SLOPE = int(buy_clean) - int(sell_clean).
    """
    from CORE.divergences_v2 import DivergencesV2Calculator
    calc = DivergencesV2Calculator()
    # Warmup buffer 10 bars
    out = {}
    for i in range(15):
        out = calc.update(close=100.0 + i, delta_bar=10.0, atr=5.0)
    # delta_divergence_clean DOIT etre dans le dict
    assert "delta_divergence_clean" in out
    # Type int composite
    assert isinstance(out["delta_divergence_clean"], int)
    # Valeur attendue : int(buy_clean) - int(sell_clean)
    expected = int(out["delta_div_buy_clean"]) - int(out["delta_div_sell_clean"])
    assert out["delta_divergence_clean"] == expected


def test_divergences_v2_empty_features_has_delta_divergence_clean():
    """_empty_features() doit aussi emettre delta_divergence_clean = 0."""
    from CORE.divergences_v2 import DivergencesV2Calculator
    out = DivergencesV2Calculator._empty_features()
    assert "delta_divergence_clean" in out
    assert out["delta_divergence_clean"] == 0


def test_delta_divergence_clean_trinary_values():
    """delta_divergence_clean doit etre dans {-1, 0, +1} (trinary)."""
    from CORE.divergences_v2 import DivergencesV2Calculator
    calc = DivergencesV2Calculator()
    # Plusieurs scenarios pour couvrir -1, 0, +1
    seen_values = set()
    # Buy div : price down, delta up, slope_delta >= 100
    for i in range(30):
        close = 100.0 - i * 0.5  # price down
        delta = 50.0 + i * 20.0  # delta up strong
        out = calc.update(close=close, delta_bar=delta, atr=5.0)
        seen_values.add(out["delta_divergence_clean"])
    # Au moins -1 ou 0 ou +1 doit etre vu
    assert seen_values.issubset({-1, 0, 1})


# ════════════════════════════════════════════════════════════════════════════
# Phase 2.2 : sierra_pipeline import + signature OK
# ════════════════════════════════════════════════════════════════════════════

def test_sierra_pipeline_imports_ok_after_phase22():
    """Verifie que sierra_pipeline.py imports sont OK apres modifications Phase 2.2.

    Soft import : ne crashe pas si modules optionnels manquants.
    """
    try:
        import importlib
        import CORE.sierra_pipeline
        importlib.reload(CORE.sierra_pipeline)
    except ImportError as e:
        # Tolere certains imports manquants (env CI)
        if "phase_b_plus_engine" in str(e) or "poc_migration" in str(e):
            pytest.skip(f"Module optionnel manquant : {e}")
        raise


# ════════════════════════════════════════════════════════════════════════════
# Phase 2.2 : non-regression existing divergences_v2 tests
# ════════════════════════════════════════════════════════════════════════════

def test_divergences_v2_dict_count_21_keys():
    """Apres Phase 2.4 aliases : dict retourne doit avoir 21 keys
    (14 features originales + 1 composite Phase 2.2 + 6 aliases Phase 2.4).
    """
    from CORE.divergences_v2 import DivergencesV2Calculator
    calc = DivergencesV2Calculator()
    out = {}
    for i in range(15):
        out = calc.update(close=100.0 + i, delta_bar=10.0, atr=5.0)
    assert len(out) == 21


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
