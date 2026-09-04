"""
Tests unitaires pour CORE/bias_calculator.py

Couvre :
- Cas purs (tout bull / tout bear / neutre)
- Edge cases (NaN, None, missing keys, bar vide)
- Blocs individuels (position, orderflow, vwap, slope, cvd, divergence)
- Divergence + trending filter
- Format dashboard backward compat

Usage :
    pytest tests/test_bias_calculator.py -v
    pytest tests/test_bias_calculator.py::test_pure_bull -v
"""

from __future__ import annotations

import math
import os
import sys

# Ajout racine projet au path (pour pytest depuis tests/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from CORE.bias_calculator import (  # noqa: E402
    BiasResult,
    compute_bias,
)


# ==============================================================================
# FIXTURES — templates de barres
# ==============================================================================


@pytest.fixture
def bar_empty():
    """Bar vide — tous champs absents. Attendu : tout 0, NEUTRE."""
    return {}


@pytest.fixture
def bar_middle():
    """Bar 'neutre' — position middle, pas de direction forte."""
    return {
        "range_pos_va": 50.0,
        "delta_pct": 0.0,
        "delta_day_dir": 0,
        "dist_vwap_d": 0.0,
        "vwap_slope_10": 0.0,
        "cvd_day_dir": 0,
        "delta_divergence": 0,
    }


@pytest.fixture
def bar_pure_bull():
    """Bar 100% bull sur tous les blocs :
    - Position 80% mais pas breakout (new_high=0) → TOP bear ? Non.
    - Pour forcer position bull : position 15% (BOTTOM)
    - delta_day acheteur + delta_pct positif
    - prix au-dessus VWAP
    - slope positif
    - CVD accumulation
    """
    return {
        "range_pos_va": 15.0,  # BOTTOM → bullish rebound
        "new_swing_high": 0,
        "new_swing_low": 0,  # pas de breakdown
        "delta_day": 50.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,
        "dist_vwap_d": -30.0,  # prix 30t au-dessus VWAP (bull)
        "vwap_slope_10": 4.0,  # slope bull
        "cvd_day_dir": 1,
        "delta_divergence": 0,
        "vwap_d_side": 1,  # prix au-dessus
    }


@pytest.fixture
def bar_pure_bear():
    """Bar 100% bear miroir."""
    return {
        "range_pos_va": 85.0,  # proche top, pas breakout
        "new_swing_high": 0,
        "new_swing_low": 0,
        "delta_day": -50.0,
        "delta_pct": -0.10,
        "delta_day_dir": -1,
        "dist_vwap_d": 30.0,  # prix sous VWAP
        "vwap_slope_10": -4.0,
        "cvd_day_dir": -1,
        "delta_divergence": 0,
        "vwap_d_side": -1,
    }


@pytest.fixture
def bar_breakout_up():
    """Position 90% + new high + delta positif = BREAKOUT UP, bullish."""
    return {
        "range_pos_va": 90.0,
        "new_swing_high": 1,
        "new_swing_low": 0,
        "delta_day": 100.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,
        "dist_vwap_d": -50.0,
        "vwap_slope_10": 8.0,  # trending fort
        "cvd_day_dir": 1,
        "delta_divergence": 0,
    }


# ==============================================================================
# TESTS — cas de base
# ==============================================================================


class TestBasicCases:
    def test_bar_empty_returns_neutral(self, bar_empty):
        """Bar vide : range_pos default 50 → MIDDLE, tous blocs neutres → score 0."""
        r = compute_bias(bar_empty)
        assert isinstance(r, BiasResult)
        assert r.direction == "NEUTRE"
        assert r.score_bull == 0.0
        assert r.score_bear == 0.0
        assert r.score_signed == 0.0
        assert r.bias_clarity == 0.0
        # Position 50 par defaut est middle (entre 20 et 80) → pas de contribution
        # OrderFlow neutre (delta_day_dir=0) → pas de contribution
        # VWAP 0 entre -15 et +15 → PROCHE, pas de contribution
        # Slope 0 entre -2 et +2 → PLAT, pas de contribution
        # CVD 0 → pas de contribution
        # Total = 0.0 → NEUTRE
        assert len(r.reasons_neutral) >= 3  # au moins position, OF, VWAP, slope en neutral

    def test_bar_middle_neutral(self, bar_middle):
        """Bar middle : tous les blocs neutres → score 0, NEUTRE."""
        r = compute_bias(bar_middle)
        assert r.score_bull == 0.0
        assert r.score_bear == 0.0
        assert r.direction == "NEUTRE"
        assert r.bias_clarity == 0.0
        assert len(r.reasons_neutral) >= 3  # position, orderflow, vwap, slope

    def test_pure_bull(self, bar_pure_bull):
        """Bar tout bull : score_bull > 0, direction BULL, bear quasi 0."""
        r = compute_bias(bar_pure_bull)
        assert r.direction == "BULL"
        assert r.score_bull > 0.5
        assert r.score_bear == 0.0
        assert r.score_signed > 0.25
        assert r.bias_clarity > 0.5
        # Verification des raisons
        assert any("BOTTOM" in reason for reason in r.reasons_bull)
        assert any("ACHETEUR" in reason for reason in r.reasons_bull)

    def test_pure_bear(self, bar_pure_bear):
        """Miroir exact."""
        r = compute_bias(bar_pure_bear)
        assert r.direction == "BEAR"
        assert r.score_bear > 0.5
        assert r.score_bull == 0.0
        assert r.score_signed < -0.25

    def test_breakout_up_bullish(self, bar_breakout_up):
        """Position 90 + new_high + delta>0 → BREAKOUT UP, pas TOP.

        Regression critique : eviter de fader un breakout (bug V1).
        """
        r = compute_bias(bar_breakout_up)
        assert r.direction == "BULL"
        assert any("BREAKOUT UP" in reason for reason in r.reasons_bull)
        assert not any("TOP" in reason for reason in r.reasons_bear)


# ==============================================================================
# TESTS — edge cases
# ==============================================================================


class TestEdgeCases:
    def test_none_values_no_crash(self):
        """Valeurs None n'affectent pas le calcul."""
        bar = {
            "range_pos_va": None,
            "delta_pct": None,
            "delta_day_dir": None,
            "dist_vwap_d": None,
            "vwap_slope_10": None,
            "cvd_day_dir": None,
        }
        r = compute_bias(bar)
        assert isinstance(r, BiasResult)
        # Pas de crash, score coherent avec defaults

    def test_nan_values_no_crash(self):
        """NaN doit etre traite comme manquant (0)."""
        bar = {
            "range_pos_va": float("nan"),
            "delta_pct": float("nan"),
            "dist_vwap_d": float("nan"),
            "vwap_slope_10": float("nan"),
        }
        r = compute_bias(bar)
        assert isinstance(r, BiasResult)
        # Pas de crash

    def test_string_in_numeric_field(self):
        """Valeurs str dans champs numeriques → default."""
        bar = {
            "range_pos_va": "abc",
            "delta_day_dir": "xyz",
        }
        r = compute_bias(bar)
        assert isinstance(r, BiasResult)

    def test_score_bounded_negative(self, bar_pure_bear):
        """Score signed ne descend jamais sous -1.0."""
        r = compute_bias(bar_pure_bear)
        assert r.score_signed >= -1.0

    def test_score_bounded_positive(self, bar_pure_bull):
        """Score signed ne monte jamais au-dessus de +1.0."""
        r = compute_bias(bar_pure_bull)
        assert r.score_signed <= 1.0


# ==============================================================================
# TESTS — blocs individuels
# ==============================================================================


class TestIndividualBlocks:
    def test_position_top_without_breakout(self):
        """Position 85% sans new_high → TOP bearish."""
        bar = {"range_pos_va": 85.0, "new_swing_high": 0, "delta_day": 10.0}
        r = compute_bias(bar)
        assert r.score_bear >= 0.30
        assert any("TOP" in reason for reason in r.reasons_bear)

    def test_position_bottom_without_breakdown(self):
        """Position 15% sans new_low → BOTTOM bullish."""
        bar = {"range_pos_va": 15.0, "new_swing_low": 0, "delta_day": -10.0}
        r = compute_bias(bar)
        assert r.score_bull >= 0.30
        assert any("BOTTOM" in reason for reason in r.reasons_bull)

    def test_breakdown_down(self):
        """Position 10% + new_low + delta<0 → BREAKDOWN bearish (pas BOTTOM rebond)."""
        bar = {
            "range_pos_va": 10.0,
            "new_swing_low": 1,
            "new_swing_high": 0,
            "delta_day": -100.0,
        }
        r = compute_bias(bar)
        assert r.score_bear >= 0.10
        assert any("BREAKDOWN" in reason for reason in r.reasons_bear)

    def test_orderflow_strong_bull(self):
        """delta_day_dir=1 ET delta_pct>0.05 → OF fort bull (+0.25)."""
        bar = {"delta_day_dir": 1, "delta_pct": 0.15, "range_pos_va": 50.0}
        r = compute_bias(bar)
        assert r.score_bull >= 0.25

    def test_orderflow_weak_bull(self):
        """delta_day_dir=1 mais delta_pct<0.05 → OF faible bull (+0.10)."""
        bar = {"delta_day_dir": 1, "delta_pct": 0.02, "range_pos_va": 50.0}
        r = compute_bias(bar)
        assert r.score_bull == pytest.approx(0.10, abs=0.01)

    def test_vwap_position_bull(self):
        """dist_vwap_d < -15 → prix 15t+ au-dessus VWAP → +0.20 bull."""
        bar = {"dist_vwap_d": -30.0, "range_pos_va": 50.0}
        r = compute_bias(bar)
        assert r.score_bull >= 0.20

    def test_vwap_slope_bull(self):
        """slope > 2 → +0.15 bull."""
        bar = {"vwap_slope_10": 5.0, "range_pos_va": 50.0}
        r = compute_bias(bar)
        assert r.score_bull >= 0.15

    def test_cvd_accumulation(self):
        """cvd_day_dir=1 → +0.10 bull."""
        bar = {"cvd_day_dir": 1, "range_pos_va": 50.0}
        r = compute_bias(bar)
        assert r.score_bull >= 0.10


# ==============================================================================
# TESTS — divergence
# ==============================================================================


class TestDivergence:
    def test_divergence_ignored_when_trending(self):
        """Div extreme + trending fort → div ignoree (ne pas fader breakout)."""
        bar = {
            "range_pos_va": 90.0,
            "new_swing_high": 1,
            "delta_day": 100.0,
            "delta_day_dir": 1,
            "delta_pct": 0.10,
            "vwap_slope_10": 10.0,  # trending
            "dist_vwap_d": -250.0,  # VWAP stretch extreme
            "delta_divergence": 1,
            "vix_level": 30.0,
        }
        r = compute_bias(bar)
        assert r.is_trending is True
        # La raison "DIV ... ignoree" doit apparaitre
        assert any(
            "ignoree" in reason.lower() or "DIV" in reason and "trending" in reason.lower()
            for reason in r.reasons_neutral
        )

    def test_divergence_bearish_mean_reversion(self):
        """Overextended haut (pos>70, dist_vwap<-50) + div forte → bear bonus."""
        bar = {
            "range_pos_va": 85.0,
            "new_swing_high": 0,  # pas breakout
            "dist_vwap_d": -100.0,
            "vwap_slope_10": 1.0,  # pas trending
            "delta_day_dir": 1,
            "delta_day": 50.0,
            "delta_pct": 0.05,
            "delta_divergence": 1,
            "sess_range_atr": 1.5,
            "vix_level": 22.0,
        }
        r = compute_bias(bar)
        assert r.div_quality >= 5.0
        assert r.is_trending is False
        # Bonus div bear present
        assert any("DIV" in reason and "overextended" in reason for reason in r.reasons_bear)


# ==============================================================================
# TESTS — format retrocompat dashboard
# ==============================================================================


class TestDashboardFormat:
    def test_to_dashboard_dict_bull(self, bar_pure_bull):
        """Format dashboard BULLISH pour un bar bull."""
        r = compute_bias(bar_pure_bull)
        d = r.to_dashboard_dict()
        assert d["bias"] == "BULLISH"
        assert d["bias_label"] == "HAUSSIER"
        assert d["bias_score"] > 0.25
        assert isinstance(d["bias_factors"], list)
        assert all("icon" in f and "text" in f for f in d["bias_factors"])

    def test_to_dashboard_dict_bear(self, bar_pure_bear):
        """Format dashboard BEARISH."""
        r = compute_bias(bar_pure_bear)
        d = r.to_dashboard_dict()
        assert d["bias"] == "BEARISH"
        assert d["bias_label"] == "BAISSIER"
        assert d["bias_score"] < -0.25

    def test_to_dashboard_dict_neutral(self, bar_middle):
        """Format dashboard NEUTRAL."""
        r = compute_bias(bar_middle)
        d = r.to_dashboard_dict()
        assert d["bias"] == "NEUTRAL"
        assert d["bias_label"] == "NEUTRE"
        assert abs(d["bias_score"]) <= 0.25


# ==============================================================================
# TESTS — clarity et direction
# ==============================================================================


class TestClarityAndDirection:
    def test_clarity_nonzero_when_directional(self, bar_pure_bull):
        """Bar directionnel → bias_clarity > 0."""
        r = compute_bias(bar_pure_bull)
        assert r.bias_clarity > 0

    def test_clarity_zero_when_truly_neutral(self, bar_middle):
        """Bar complètement neutre → bias_clarity = 0."""
        r = compute_bias(bar_middle)
        assert r.bias_clarity == 0.0

    def test_clarity_symmetric_signals(self):
        """Bar avec bull+bear equivalents → bias_clarity faible, direction NEUTRE."""
        bar = {
            "range_pos_va": 50.0,
            "dist_vwap_d": -20.0,  # bull +0.20
            "delta_day_dir": -1,
            "delta_pct": -0.10,  # bear +0.25
            "vwap_slope_10": 0.0,
        }
        r = compute_bias(bar)
        # bull=0.20, bear=0.25, clarity=0.05
        assert r.bias_clarity < 0.1
        # Direction depend du score signed
        # score_signed = 0.20 - 0.25 = -0.05 → NEUTRE (|0.05| < 0.25)
        assert r.direction == "NEUTRE"


class TestDashboardConfidence:
    def test_confidence_present_in_dashboard_dict(self, bar_pure_bull):
        """bias_confidence doit etre present dans to_dashboard_dict (ne pas
        regresser apres branchement sur builders.py)."""
        r = compute_bias(bar_pure_bull)
        d = r.to_dashboard_dict()
        assert "bias_confidence" in d
        assert 0.0 <= d["bias_confidence"] <= 1.0

    def test_confidence_zero_empty_factors(self, bar_empty):
        """Bar vide : factors contient uniquement neutral (ni bull ni bear actifs) →
        confidence = 0 (consensus / active impossible)."""
        r = compute_bias(bar_empty)
        d = r.to_dashboard_dict()
        # Bar vide → tout neutre → pas de bull/bear actifs → confidence = 0
        assert d["bias_confidence"] == 0.0

    def test_confidence_less_than_3_factors_penalty(self):
        """Confidence penalisee (×active/3) si < 3 factors actifs."""
        # Un seul facteur bull → active=1, malus ×1/3
        bar = {"range_pos_va": 50.0, "delta_day_dir": 1, "delta_pct": 0.02}
        r = compute_bias(bar)
        d = r.to_dashboard_dict()
        # Devrait avoir confidence reduite (pas plein consensus)
        assert d["bias_confidence"] < 0.5


class TestDivGrade:
    def test_div_grade_none_when_no_divergence(self, bar_middle):
        """Sans divergence active, grade = NONE."""
        r = compute_bias(bar_middle)
        assert r.div_grade == "NONE"
        assert r.div_quality == 0.0

    def test_div_grade_faible_low_quality(self):
        """delta_divergence=1 mais quality < 3 → FAIBLE."""
        bar = {
            "range_pos_va": 50.0,
            "delta_divergence": 1,
            "dist_vwap_d": -20.0,  # stretch modeste
            # pos milieu, pas d'ajout
            # atr_ratio default 1.0 → pas d'ajout
            # vix default 0 → pas d'ajout
        }
        r = compute_bias(bar)
        # Quality = 0 + 0 + 0 + 0 = 0 → pas de bonus
        # Mais div_grade se base sur quality, pas delta_div seul
        # Si quality < 3 mais delta_div=1 → FAIBLE
        assert r.div_grade in ("FAIBLE", "NONE")

    def test_div_grade_moderee(self):
        """Quality entre 3 et 4 → MODEREE."""
        bar = {
            "range_pos_va": 85.0,  # range eleve +1
            "delta_divergence": 1,
            "dist_vwap_d": -100.0,  # stretch fort +2
            "vwap_slope_10": 1.0,
        }
        r = compute_bias(bar)
        # Quality = 2 (stretch>80) + 1 (pos>=80) = 3 → MODEREE
        assert r.div_quality >= 3.0
        assert r.div_grade == "MODEREE"

    def test_div_grade_forte(self):
        """Quality entre 4 et 6 → FORTE."""
        bar = {
            "range_pos_va": 95.0,  # range extreme +2
            "delta_divergence": 1,
            "dist_vwap_d": -100.0,  # stretch fort +2
            "sess_range_atr": 1.5,  # +1.5
            "vwap_slope_10": 1.0,
        }
        r = compute_bias(bar)
        # Quality = 2 + 2 + 1.5 = 5.5 → FORTE
        assert r.div_quality >= 4.0
        assert r.div_quality < 6.0
        assert r.div_grade == "FORTE"

    def test_div_grade_extreme(self):
        """Quality >= 6 → EXTREME."""
        bar = {
            "range_pos_va": 95.0,  # +2
            "delta_divergence": 1,
            "dist_vwap_d": -250.0,  # stretch extreme +3
            "sess_range_atr": 1.5,  # +1.5
            "vix_level": 30.0,  # +1
            "vwap_slope_10": 1.0,
        }
        r = compute_bias(bar)
        # Quality = 3 + 2 + 1.5 + 1 = 7.5 → EXTREME
        assert r.div_quality >= 6.0
        assert r.div_grade == "EXTREME"


class TestRealBarsParite:
    """Tests de parite sur barres JSONL reelles pour protection regression."""

    @pytest.fixture(scope="class")
    def real_bars(self):
        """Load 10 barres JSONL NQ recentes pour tests empiriques."""
        import json as _json
        fp = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "DATA", "NQ", "20260423_NQ_v2.jsonl"
        )
        if not os.path.exists(fp):
            pytest.skip("Pas de JSONL NQ 23/04 disponible pour tests parite")
        bars = []
        with open(fp, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s:
                    try:
                        bars.append(_json.loads(s))
                    except _json.JSONDecodeError:
                        pass
        # Dernieres 10 bars (plus fraiches)
        return bars[-10:]

    def test_no_crash_on_real_bars(self, real_bars):
        """compute_bias ne doit pas crasher sur 10 barres reelles."""
        assert len(real_bars) > 0, "Pas de barres chargees"
        for bar in real_bars:
            r = compute_bias(bar)
            assert isinstance(r, BiasResult)
            assert -1.0 <= r.score_signed <= 1.0
            assert r.score_bull >= 0
            assert r.score_bear >= 0

    def test_real_bars_direction_coherent_with_vwap(self, real_bars):
        """Sur barres reelles, la direction doit etre coherente avec bool_above_vwap_d
        (si au-dessus VWAP daily, biais tend BULL, et vice-versa) — check sanity."""
        for bar in real_bars:
            r = compute_bias(bar)
            # Si delta_day fort et vwap pente forte concordant, direction devrait
            # suivre. Sinon, bias NEUTRE acceptable.
            # On verifie juste que le score est coherent avec les raisons.
            if r.direction == "BULL":
                assert r.score_bull > r.score_bear
            elif r.direction == "BEAR":
                assert r.score_bear > r.score_bull

    def test_real_bars_dashboard_dict_format(self, real_bars):
        """Format dashboard complet sur barres reelles."""
        for bar in real_bars:
            r = compute_bias(bar)
            d = r.to_dashboard_dict()
            assert set(d.keys()) >= {"bias", "bias_label", "bias_score",
                                      "bias_confidence", "bias_factors"}
            assert d["bias"] in ("BULLISH", "BEARISH", "NEUTRAL")
            assert -1.0 <= d["bias_score"] <= 1.0
            assert 0.0 <= d["bias_confidence"] <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ===== Non-regression INCIDENT #99 — inversion d'echelle range_pos =====
# La 1ere version du helper multipliait par 100 toute valeur <= 1.5. Or
# range_pos_va = 0.8 signifie "prix a 0,8 % du BAS de la Value Area". La regle
# le transformait en 80.0 => lu comme HAUT de VA => signal INVERSE au point de
# decision le plus critique. 380 barres reelles concernees.

class TestRangePosScaleIncident99:

    def test_bas_de_va_non_inverse(self):
        """range_pos_va=0.8 = BAS de VA. Ne doit JAMAIS etre lu comme un top."""
        from CORE.constants import range_pos_pct
        assert range_pos_pct({"range_pos_va": 0.8}) == 0.8

    def test_range_pos_seul_ne_devine_pas_l_echelle(self):
        """`range_pos` seul est ambigu ([0,1] live vs [0,100] parquet).

        On refuse de deviner : defaut neutre plutot qu'un signal potentiellement
        inverse (cf INCIDENT #97 : "refuser d'agir plutot qu'inventer").
        """
        from CORE.constants import range_pos_pct
        assert range_pos_pct({"range_pos": 0.706}) == 50.0
        assert range_pos_pct({"range_pos": 85.0}) == 50.0

    def test_va_prioritaire_sur_range_pos(self):
        """Si les deux cles existent (cas live_enriched), `range_pos_va` gagne."""
        from CORE.constants import range_pos_pct
        assert range_pos_pct({"range_pos_va": 70.6, "range_pos": 0.706}) == 70.6

    def test_valeur_absurde_neutralisee(self):
        from CORE.constants import range_pos_pct
        assert range_pos_pct({"range_pos_va": 9999.0}) == 50.0

    def test_hors_va_preserve(self):
        """>100 = prix sorti de la VA : information, pas anomalie. Pas de clamp."""
        from CORE.constants import range_pos_pct
        assert range_pos_pct({"range_pos_va": 149.25}) == 149.25

    def test_bas_de_va_produit_un_signal_bull_pas_bear(self):
        """Bout-en-bout : 0.8 % de VA doit donner BOTTOM (bull), jamais TOP."""
        from CORE.bias_calculator import compute_bias
        r = compute_bias({"range_pos_va": 0.8, "sym": "ES"})
        assert any("BOTTOM" in x for x in r.reasons_bull), r.reasons_bull
        assert not any("TOP" in x for x in r.reasons_bear), r.reasons_bear
