"""Tests regression BUG #3 (08/06/2026) — separation delta/cvd dans regime_engine.

R3 code-reviewer ac988048c9c6bff6b : ajout 4 tests pytest pour valider la fix
delta_or_cvd court-circuit. Couvre v1 et v6 (jumeaux).

Couvre :
- Divergence delta=+1 cvd=-1 (cas casseur 78% bars NQ V4)
- Aligne delta=+1 cvd=+1 (retrocompat ancien comportement)
- cvd absent (pipeline Databento, compat pre-fix poids 0.25)
- cvd seul delta=0 (modulation pure, pas vote structurel)
"""
import pytest

from CORE.regime_engine import _compute_bias_proxy as proxy_v1
from CORE.regime_engine_v6 import _compute_bias_proxy as proxy_v6


@pytest.mark.parametrize("proxy", [proxy_v1, proxy_v6])
def test_bug3_delta_cvd_divergence(proxy):
    """Divergence delta+1 cvd-1 : delta wins attenue (0.15), bull_factors=1 seul.

    AVANT bug : OR booleen → score=0.25 bull_factors=1 (cvd ignore silencieusement)
    APRES fix : score=0.15 bull_factors=1 (delta priorite 0.20, cvd modulation -0.05)
    """
    bar = {"delta_day_dir": 1, "cvd_day_dir": -1, "range_pos": 50.0}
    s, lbl, bear, bull = proxy(bar, "NORMAL")
    assert abs(s - 0.15) < 1e-6, f"Score divergence attendu 0.15, recu {s}"
    assert bull == 1, f"bull_factors attendu 1 (delta seul vote), recu {bull}"
    assert bear == 0, f"bear_factors attendu 0 (cvd modulation pas vote), recu {bear}"
    assert lbl == "NEUTRE", f"Label attendu NEUTRE (score < 0.30), recu {lbl}"


@pytest.mark.parametrize("proxy", [proxy_v1, proxy_v6])
def test_bug3_delta_cvd_aligned(proxy):
    """Aligne delta+1 cvd+1 : score=0.25 (compat ancien comportement)."""
    bar = {"delta_day_dir": 1, "cvd_day_dir": 1, "range_pos": 50.0}
    s, _, bear, bull = proxy(bar, "NORMAL")
    assert abs(s - 0.25) < 1e-6, f"Score aligne attendu 0.25, recu {s}"
    assert bull == 1, f"bull_factors attendu 1, recu {bull}"
    assert bear == 0


@pytest.mark.parametrize("proxy", [proxy_v1, proxy_v6])
def test_bug3_cvd_absent_databento_compat(proxy):
    """cvd_day_dir absent (Databento pipeline) : delta poids 0.25 compat pre-fix.

    R1 code-reviewer : eviter regression -20% signal sur 50% des consommateurs prod
    (pipeline Databento ne contient JAMAIS cvd_day_dir).
    """
    bar = {"delta_day_dir": 1, "range_pos": 50.0}  # PAS de cvd_day_dir
    s, _, bear, bull = proxy(bar, "NORMAL")
    assert abs(s - 0.25) < 1e-6, f"cvd absent : delta=0.25 compat attendu, recu {s}"
    assert bull == 1
    assert bear == 0


@pytest.mark.parametrize("proxy", [proxy_v1, proxy_v6])
def test_bug3_cvd_only_modulation(proxy):
    """delta=0 cvd=+1 : modulation 0.05, PAS de vote structurel.

    Changement volontaire vs ancien (qui votait +0.25 bull_factors=1).
    Cas marginal empirique (0% sample 14k bars V4) : acceptable.
    """
    bar = {"delta_day_dir": 0, "cvd_day_dir": 1, "range_pos": 50.0}
    s, _, bear, bull = proxy(bar, "NORMAL")
    assert abs(s - 0.05) < 1e-6, f"cvd seul attendu 0.05, recu {s}"
    assert bull == 0, f"cvd seul ne doit PAS voter (modulation), recu bull={bull}"
    assert bear == 0


@pytest.mark.parametrize("proxy", [proxy_v1, proxy_v6])
def test_bug3_mode_required_fail_loud(proxy):
    """R2 code-reviewer : mode est OBLIGATOIRE (fail-loud anti silent fallback)."""
    with pytest.raises(TypeError, match="mode"):
        proxy({"delta_day_dir": 1, "range_pos": 50.0})  # mode manquant
