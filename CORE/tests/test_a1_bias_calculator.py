"""
Tests Plan A1 (08/06/2026) — refactor BLOC 5 bias_calculator.

Contexte : Bot 1 SIM1 a perdu -$2010 le 08/06 sur 7 trades 100% LONG. Cas
casseur identifie : delta_day_dir=+1 (achats agressifs intra-bar) AND
cvd_day_dir=-1 (distribution cumulative session) = signal de retournement
classique en orderflow analysis. Mais score calcul :
  + PTS_OF_STRONG (delta) = +0.25 vs - PTS_CVD (cvd) = -0.10
  → score net +0.15 → label BULLISH avec autres facteurs bullish (drift)

Plan A1 :
  1. PTS_CVD remontee 0.10 → 0.25 (symetrie anti silent override)
  2. delta_cvd_divergence_flag (qualite signal degradee)
  3. vwap_m_side veto vers NEUTRAL si signal contre ancrage long-terme

Justification PAS empirique : logique pure de symetrie orderflow.
Cf. .claude/rules/critical-tasks-review.md (interdiction calibration N<30).

Usage :
    pytest CORE/tests/test_a1_bias_calculator.py -v
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest  # noqa: E402

from CORE.bias_calculator import (  # noqa: E402
    PTS_CVD,
    PTS_OF_STRONG,
    BiasResult,
    compute_bias,
)


# ==============================================================================
# Test #1 — PTS_CVD == PTS_OF_STRONG (symetrie orderflow)
# ==============================================================================


def test_a1_cvd_weight_equal_delta():
    """PTS_CVD doit etre exactement egal a PTS_OF_STRONG apres Plan A1.

    Justification : delta_day_dir (intra-bar) et cvd_day_dir (cumulative session)
    mesurent tous deux la direction de l'orderflow. Aucune raison de ponderer
    delta 2.5x plus fort que cvd → silent override garanti (bug 08/06).
    """
    assert PTS_CVD == PTS_OF_STRONG == 0.25, (
        f"Plan A1 viole : PTS_CVD={PTS_CVD} != PTS_OF_STRONG={PTS_OF_STRONG}"
    )


# ==============================================================================
# Test #2 — Detection divergence delta vs cvd
# ==============================================================================


def test_a1_delta_cvd_divergence_flag():
    """Cas casseur 08/06 NQ : delta+1 cvd-1 → flag delta_cvd_divergence = True."""
    bar = {
        "range_pos": 50.0,  # middle, pas de contribution position
        "delta_day": 50.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,  # delta intra-bar acheteur
        "cvd_day_dir": -1,  # cvd cumule session distribution
        "dist_vwap_d": 0.0,
        "vwap_slope_10": 0.0,
        "delta_divergence": 0,
    }
    r = compute_bias(bar)
    assert isinstance(r, BiasResult)
    assert r.delta_cvd_divergence is True, "delta+1 cvd-1 doit declencher flag"
    # Verification : le score doit etre quasi-neutre car delta=+0.25 et cvd=-0.25
    # s'auto-attenuent (anti silent override = objectif clef du refactor)
    assert abs(r.score_signed) < 0.10, (
        f"score_signed={r.score_signed} : delta et cvd doivent s'attenuer"
    )
    # Raison observable
    assert any("DIVERGENCE" in reason for reason in r.reasons_neutral), (
        "Raison DIVERGENCE absente"
    )


def test_a1_delta_cvd_divergence_mirror():
    """Cas miroir : delta-1 cvd+1 → flag declenche aussi."""
    bar = {
        "range_pos": 50.0,
        "delta_day": -50.0,
        "delta_pct": -0.10,
        "delta_day_dir": -1,
        "cvd_day_dir": 1,
    }
    r = compute_bias(bar)
    assert r.delta_cvd_divergence is True


# ==============================================================================
# Test #3 — Signal aligne (preservation)
# ==============================================================================


def test_a1_aligned_signal_compat():
    """delta+1 cvd+1 → score = 0.50 (PTS_OF_STRONG + PTS_CVD).

    Regression positive : avant Plan A1 le score etait 0.25+0.10 = 0.35.
    Apres : 0.25+0.25 = 0.50. Pas de flag divergence.
    """
    bar = {
        "range_pos": 50.0,
        "delta_day": 50.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,
        "cvd_day_dir": 1,
        "dist_vwap_d": 0.0,
        "vwap_slope_10": 0.0,
    }
    r = compute_bias(bar)
    assert r.delta_cvd_divergence is False
    # PTS_OF_STRONG (delta+pct) + PTS_CVD (cvd ACC) = 0.25 + 0.25 = 0.50
    assert r.score_bull == pytest.approx(0.50, abs=0.01), (
        f"score_bull={r.score_bull} attendu 0.50"
    )
    assert r.score_bear == 0.0


# ==============================================================================
# Test #4 — Veto vwap_m_side BULL contraire
# ==============================================================================


def test_a1_vwap_m_side_veto_bullish():
    """Signal propose BULL + vwap_m_side<0 → veto vers NEUTRAL."""
    bar = {
        "range_pos": 15.0,  # BOTTOM (+0.30 bull)
        "new_swing_high": 0,
        "new_swing_low": 0,
        "delta_day": 50.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,
        "cvd_day_dir": 1,
        "dist_vwap_d": -30.0,  # +0.20 bull
        "vwap_slope_10": 4.0,  # +0.15 bull
        "vwap_m_side": -1,  # ANCRAGE long-terme bearish
    }
    r = compute_bias(bar)
    # Score serait BULL fort (>0.5) mais veto pousse NEUTRE
    assert r.score_bull > 0.5, f"score_bull={r.score_bull} doit etre fort (signal BULL pur)"
    assert r.vwap_m_veto_applied is True, "Flag veto manquant"
    assert r.direction == "NEUTRE", f"direction={r.direction} attendu NEUTRE (veto)"
    # Raison observable
    assert any("VWAP_M VETO" in reason for reason in r.reasons_neutral), (
        "Raison VWAP_M VETO absente"
    )


# ==============================================================================
# Test #5 — Veto vwap_m_side BEAR contraire
# ==============================================================================


def test_a1_vwap_m_side_veto_bearish():
    """Signal propose BEAR + vwap_m_side>0 → veto vers NEUTRAL."""
    bar = {
        "range_pos": 85.0,
        "new_swing_high": 0,
        "delta_day": -50.0,
        "delta_pct": -0.10,
        "delta_day_dir": -1,
        "cvd_day_dir": -1,
        "dist_vwap_d": 30.0,
        "vwap_slope_10": -4.0,
        "vwap_m_side": 1,  # ANCRAGE long-terme bullish
    }
    r = compute_bias(bar)
    assert r.score_bear > 0.5
    assert r.vwap_m_veto_applied is True
    assert r.direction == "NEUTRE"


# ==============================================================================
# Test #6 — Veto NON applique si aligne
# ==============================================================================


def test_a1_vwap_m_side_aligned():
    """Signal BULL + vwap_m_side>0 → preserve BULL (alignement long-terme)."""
    bar = {
        "range_pos": 15.0,
        "new_swing_low": 0,
        "delta_day": 50.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,
        "cvd_day_dir": 1,
        "dist_vwap_d": -30.0,
        "vwap_slope_10": 4.0,
        "vwap_m_side": 1,  # ANCRAGE aligne BULL
    }
    r = compute_bias(bar)
    assert r.vwap_m_veto_applied is False
    assert r.direction == "BULL"


# ==============================================================================
# Test #7 — Compat absence cvd_day_dir (Databento live_enriched)
# ==============================================================================


def test_a1_cvd_compat_absent():
    """cvd_day_dir absent (Databento) → ne PAS crasher, fallback default 0."""
    bar = {
        "range_pos": 50.0,
        "delta_day": 50.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,
        # cvd_day_dir absent
        "dist_vwap_d": 0.0,
        "vwap_slope_10": 0.0,
    }
    r = compute_bias(bar)
    assert isinstance(r, BiasResult)
    # Pas de divergence si cvd=0 (les deux conditions delta!=0 ET cvd!=0)
    assert r.delta_cvd_divergence is False, "divergence ne doit pas se declencher si cvd absent"
    # Score bull = PTS_OF_STRONG uniquement (pas de cvd ajoute)
    assert r.score_bull == pytest.approx(0.25, abs=0.01)


def test_a1_cvd_compat_absent_none():
    """cvd_day_dir = None → ne PAS crasher (helper _get_int gere None)."""
    bar = {
        "range_pos": 50.0,
        "delta_day_dir": 1,
        "delta_pct": 0.10,
        "cvd_day_dir": None,  # explicit None
    }
    r = compute_bias(bar)
    assert isinstance(r, BiasResult)
    assert r.delta_cvd_divergence is False


# ==============================================================================
# Test #8 — to_dashboard_dict expose les nouveaux flags
# ==============================================================================


def test_a1_dashboard_dict_exposes_flags():
    """to_dashboard_dict doit exposer delta_cvd_divergence + vwap_m_veto_applied."""
    bar = {
        "range_pos": 50.0,
        "delta_day_dir": 1,
        "delta_pct": 0.10,
        "cvd_day_dir": -1,
    }
    r = compute_bias(bar)
    d = r.to_dashboard_dict()
    assert "delta_cvd_divergence" in d
    assert "vwap_m_veto_applied" in d
    assert d["delta_cvd_divergence"] is True
    assert d["vwap_m_veto_applied"] is False


# ==============================================================================
# Test #9 — Cas casseur initial (snapshot Bot 1 trade #3 NQ 08/06)
# ==============================================================================


def test_a1_breaker_case_neutralised():
    """Cas casseur du snapshot trade #3 NQ 08/06.

    AVANT Plan A1 : bias=BULLISH bias_score=0.75 malgre CVD DISTRIBUTION.
    APRES Plan A1 : score attenue (delta et cvd s'auto-attenuent) + flag
    divergence visible. Si vwap_m_side<0 (probable apres -$2010 LONG drift)
    le veto coupe meme un signal qui resterait BULL.
    """
    # Bar approximative du cas casseur : delta+ cvd- + autres facteurs BULL
    bar = {
        "range_pos": 50.0,
        "delta_day": 50.0,
        "delta_pct": 0.10,
        "delta_day_dir": 1,  # achats agressifs intra-bar
        "cvd_day_dir": -1,  # distribution cumulative
        "dist_vwap_d": -20.0,  # prix au-dessus VWAP-d (bull)
        "vwap_slope_10": 3.0,  # slope positif (bull)
        "vwap_d_side": 1,
        "vwap_w_side": 1,
        "vwap_m_side": -1,  # MAIS ancrage mensuel bearish (drift LONG = anti-fond)
    }
    r = compute_bias(bar)
    # 1. Divergence detectee
    assert r.delta_cvd_divergence is True
    # 2. Veto applique (vwap_m_side opposite)
    assert r.vwap_m_veto_applied is True
    # 3. Direction finale NEUTRE (au lieu de BULL avant fix)
    assert r.direction == "NEUTRE", (
        f"Cas casseur encore en BULL : direction={r.direction}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
