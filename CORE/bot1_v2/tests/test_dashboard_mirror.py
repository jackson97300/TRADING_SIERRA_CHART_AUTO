"""Tests dashboard_mirror.py - REFONTE Phase 4 (verdict souple + bonus k-of-n).

Nouvelle logique (19/06) :
  1. dir_score = bull_pts - bear_pts -> direction souple (LONG>=3, SHORT<=-3)
  2. 4 vetos hard (climax, rvol_zscore>3, gamma, vix) INCHANGES
  3. CORE : near_level direction-aware (support LONG / resistance SHORT)
  4. BONUS : compte k-of-3 (rvol, pullback, bar_confirmation) >= MIN_BONUS_COUNT

Cas critique #1 : Trade ES SHORT 15/06 -$967 DOIT etre SKIP (vetos).
Cas critique #2 : Trade de qualite DOIT PASSER (NO PARALYSIS).
"""
from __future__ import annotations

import pytest

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.dashboard_mirror import compute_verdict


# ============================================================
# HELPER : fabrique bar synthetique
# ============================================================

def _make_bar(**overrides):
    """Bar LONG synthetique : dir_score=+4 + near_level support OK + bonus 3/3.

    dir_score : cvd(+1) + delta(+1) + vwap_d_side(+1) + momentum_5b>1.0(+1) = 4.
    near_level : dist_vwap_d=-2 (support en-dessous, |2|<=8t ES).
    bonus : rvol>=1.1 + pullback (sess_high au-dessus) + bar verte.
    """
    base = {
        "sym": "ES",
        # dir_score = +4 (LONG fort)
        "cvd_day_dir": 1,
        "delta_day_dir": 1,
        "vwap_d_side": 1,
        "momentum_5b": 3.0,
        "momentum_3b": 1.5,  # m3 < m5 -> pullback via momentum OK aussi
        # bias diagnostic (ne gate plus)
        "bias_score": 0.6,
        "bias_label": "BULLISH",
        # MTF diagnostic
        "mtf_bulls": 4, "mtf_bears": 0, "mtf_neutres": 0,
        # CORE near_level : support en-dessous (dist < 0 = SUPPORT)
        "is_cash_session": True,
        "dist_vwap_d": -2,  # 2t sous le prix = support proche
        # BONUS 1 : rvol >= 1.1
        "rvol": 1.5,
        # BONUS 2 : pullback (prix retrace depuis high session)
        "close": 7600.0,
        "open": 7599.0,  # bar verte (bonus 3)
        "high": 7600.5,
        "sess_high": 7602.0,  # 2 pts = 8t de retracement
        "finish_strength": 5.0,
        # BONUS 3 : bar confirmation couleur up
        "bar_color_up": 1,
        # Vetos OFF
        "ctx_climax_signal": False,
        "rvol_zscore": 0.5,
        "gamma_block_long": False,
        "gamma_block_short": False,
        "vix_level": 17.0,
        "vix_regime_label": "NORMAL",
    }
    base.update(overrides)
    return base


def _make_bar_short(**overrides):
    """Bar SHORT synthetique : dir_score=-4 + near_level resistance OK + bonus 3/3."""
    base = {
        "sym": "ES",
        "cvd_day_dir": -1,
        "delta_day_dir": -1,
        "vwap_d_side": -1,
        "momentum_5b": -3.0,
        "momentum_3b": -1.5,  # m3 > m5 -> bounce OK
        "bias_score": -0.6,
        "bias_label": "BEARISH",
        "mtf_bulls": 0, "mtf_bears": 4, "mtf_neutres": 0,
        "is_cash_session": True,
        # near_level : resistance au-dessus (dist > 0 = RESISTANCE)
        "dist_vwap_d": 2,
        "rvol": 1.5,
        "close": 7600.0,
        "open": 7601.0,  # bar rouge (bonus)
        "low": 7599.5,
        "sess_low": 7598.0,  # 2 pts = 8t de bounce
        "finish_strength": -5.0,
        "bar_color_dn": 1,
        "ctx_climax_signal": False,
        "rvol_zscore": 0.5,
        "gamma_block_long": False,
        "gamma_block_short": False,
        "vix_level": 17.0,
        "vix_regime_label": "NORMAL",
    }
    base.update(overrides)
    return base


# ============================================================
# CAS CRITIQUE #1 : Trade -$967 doit etre SKIP
# ============================================================

def test_skip_trade_es_short_967():
    """Le trade ES SHORT 15/06 qui a perdu $967 DOIT etre rejected.

    Snapshot reel : ctx_climax_signal=True, rvol_zscore=3.74, gamma_block_short=True.
    """
    bar = _make_bar_short(
        ctx_climax_signal=True,
        rvol_zscore=3.74,
        gamma_block_short=True,
        momentum_5b=-5.75,
        vix_level=16.23,
    )
    verdict = compute_verdict(bar)

    assert verdict.ready_to_arm is False, (
        f"BOT v2 DEVAIT REJECT ce trade. action={verdict.action} "
        f"vetos={verdict.vetos} misses={verdict.quality_misses}"
    )
    veto_names = {v.name for v in verdict.vetos}
    assert veto_names & {"CLIMAX_WYCKOFF", "RVOL_EXCEPTIONAL", "GAMMA_BLOCK_SHORT"}, (
        f"Rejet doit etre justifie par veto critique. skip={verdict.skip_reason}"
    )


# ============================================================
# CAS CRITIQUE #2 : NO PARALYSIS - trade de qualite doit passer
# ============================================================

def test_no_paralysis_quality_long_passes():
    """Un setup LONG de QUALITE DOIT passer (dir_score>=3 + near + bonus>=2)."""
    bar = _make_bar()
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is True, (
        f"DEVAIT ACCEPTER. action={verdict.action} vetos={verdict.vetos} "
        f"skip={verdict.skip_reason} bonus={verdict.stars_count}"
    )
    assert verdict.direction == "LONG"
    assert verdict.vetos == ()


def test_no_paralysis_quality_short_passes():
    """Un setup SHORT de QUALITE DOIT passer."""
    bar = _make_bar_short()
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is True, (
        f"SHORT qualite doit passer. skip={verdict.skip_reason} "
        f"bonus={verdict.stars_count}/{verdict.stars_total}"
    )
    assert verdict.direction == "SHORT"


# ============================================================
# VERDICT DIRECTIONNEL (dir_score)
# ============================================================

def test_dir_score_long_when_ge_3():
    """dir_score >= +3 ET bear_pts <= 1 -> LONG."""
    bar = _make_bar()  # dir_score = +4
    verdict = compute_verdict(bar)
    assert verdict.direction == "LONG"
    assert verdict.bull_pts - verdict.bear_pts >= 3


def test_dir_score_short_when_le_minus_3():
    """dir_score <= -3 ET bull_pts <= 1 -> SHORT."""
    bar = _make_bar_short()  # dir_score = -4
    verdict = compute_verdict(bar)
    assert verdict.direction == "SHORT"
    assert verdict.bull_pts - verdict.bear_pts <= -3


def test_dir_score_attendre_between():
    """dir_score entre -3 et +3 -> ATTENDRE (None)."""
    # cvd +1, delta -1, vwap_d 0, momentum 0 -> bull=1 bear=1 dir_score=0
    bar = _make_bar(
        cvd_day_dir=1,
        delta_day_dir=-1,
        vwap_d_side=0,
        momentum_5b=0.0,
        momentum_3b=0.0,
    )
    verdict = compute_verdict(bar)
    assert verdict.direction is None
    assert verdict.ready_to_arm is False
    assert verdict.skip_reason == "DASHBOARD_VERDICT_REJECTED:ATTENDRE"


def test_dir_score_mixed_blocks_direction():
    """dir_score = -1 (mixte) -> ATTENDRE, pas de SHORT force."""
    bar = _make_bar_short(
        cvd_day_dir=-1,
        delta_day_dir=-1,
        vwap_d_side=1,   # 1 contre
        momentum_5b=0.0,  # neutre
        momentum_3b=0.0,
    )
    # bear=2 bull=1 dir_score=-1 -> ATTENDRE
    verdict = compute_verdict(bar)
    assert verdict.direction is None


# ============================================================
# BONUS k-of-n
# ============================================================

def test_bonus_3_of_3_passes():
    """3/3 dimensions bonus -> ready (avec near + dir_score OK)."""
    bar = _make_bar()
    verdict = compute_verdict(bar)
    assert verdict.stars_count == 3
    assert verdict.ready_to_arm is True


def test_bonus_2_of_3_passes():
    """2/3 dimensions bonus (>= MIN_BONUS_COUNT=2) -> ready."""
    # Casse 1 bonus : rvol trop bas (1.0 < 1.1). pullback + bar OK = 2/3.
    bar = _make_bar(rvol=1.0)
    verdict = compute_verdict(bar)
    assert verdict.stars_count == 2, f"bonus={verdict.stars_count} misses={verdict.quality_misses}"
    assert verdict.ready_to_arm is True


def test_bonus_1_of_3_rejects():
    """1/3 dimensions bonus (< MIN_BONUS_COUNT=2) -> reject."""
    # Casse 2 bonus : rvol bas (1.0) + bar rouge (pas de confirmation LONG).
    # Reste : pullback via sess_high = 1/3.
    bar = _make_bar(
        rvol=1.0,
        open=7601.0, close=7600.0,  # bar rouge
        bar_color_up=0,
        sess_high=7602.0,  # pullback OK (1/3)
    )
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert verdict.stars_count == 1, f"bonus={verdict.stars_count}"
    assert "BONUS_INSUFFICIENT" in verdict.skip_reason


def test_bonus_count_via_env_override(monkeypatch):
    """MIN_BONUS_COUNT=3 via env : 2/3 ne suffit plus."""
    monkeypatch.setenv("BOT1V2_MIN_BONUS_COUNT", "3")
    cfg = Bot1V2Config.from_env()
    bar = _make_bar(rvol=1.0)  # 2/3
    verdict = compute_verdict(bar, cfg=cfg)
    assert verdict.ready_to_arm is False
    assert "BONUS_INSUFFICIENT" in verdict.skip_reason


# ============================================================
# CORE near_level (direction-aware)
# ============================================================

def test_core_near_level_long_needs_support():
    """LONG sans support proche -> NOT_AT_SUPPORT (skip_reason garde le nom)."""
    bar = _make_bar(dist_vwap_d=20)  # support trop loin
    for k in list(bar.keys()):
        if k.startswith("dist_") and k != "dist_vwap_d":
            bar.pop(k)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert verdict.skip_reason == "NOT_AT_SUPPORT"
    assert any(m.name == "NOT_AT_SUPPORT" for m in verdict.quality_misses)


def test_core_near_level_short_needs_resistance():
    """SHORT sans resistance proche -> NOT_AT_RESISTANCE."""
    bar = _make_bar_short(dist_vwap_d=-20)  # support en-dessous, pas resistance
    for k in list(bar.keys()):
        if k.startswith("dist_") and k != "dist_vwap_d":
            bar.pop(k)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert verdict.skip_reason == "NOT_AT_RESISTANCE"


def test_core_near_level_long_at_support_passes():
    """LONG proche d'un support (dist_vwap_d=-3) -> near OK."""
    bar = _make_bar(dist_vwap_d=-3)
    verdict = compute_verdict(bar)
    assert not any(
        m.name in ("NOT_AT_SUPPORT", "NOT_AT_RESISTANCE")
        for m in verdict.quality_misses
    )


# ============================================================
# VETOS HARD (inchanges)
# ============================================================

def test_veto_climax_blocks():
    """Wyckoff climax = veto hard."""
    bar = _make_bar_short(ctx_climax_signal=True)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(v.name == "CLIMAX_WYCKOFF" for v in verdict.vetos)


def test_veto_rvol_blocks_extreme():
    """RVOL z > 3.0 = veto hard."""
    bar = _make_bar(rvol_zscore=3.5)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(v.name == "RVOL_EXCEPTIONAL" for v in verdict.vetos)


def test_veto_rvol_lets_pass_25():
    """RVOL z = 2.5 PASSE (seuil 3.0 NO PARALYSIS)."""
    bar = _make_bar(rvol_zscore=2.5)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is True, f"vetos={verdict.vetos}"


def test_veto_gamma_blocks_short():
    """gamma_block_short=True + SHORT = veto hard (root cause -$967)."""
    bar = _make_bar_short(gamma_block_short=True)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(v.name == "GAMMA_BLOCK_SHORT" for v in verdict.vetos)


def test_veto_gamma_blocks_long():
    """gamma_block_long=True + LONG = veto hard."""
    bar = _make_bar(gamma_block_long=True)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(v.name == "GAMMA_BLOCK_LONG" for v in verdict.vetos)


def test_veto_gamma_does_not_block_opposite_direction():
    """gamma_block_short=True NE bloque PAS un LONG (asymetrie)."""
    bar = _make_bar(gamma_block_short=True, gamma_block_long=False)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is True
    assert not any("GAMMA" in v.name for v in verdict.vetos)


def test_veto_vix_extreme_blocks():
    """VIX > 35 = veto hard."""
    bar = _make_bar(vix_level=40.0)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(v.name == "VIX_EXTREME" for v in verdict.vetos)


def test_veto_vix_calm_blocks():
    """VIX < 13 = veto hard."""
    bar = _make_bar(vix_level=11.0)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(v.name == "VIX_CALM" for v in verdict.vetos)


def test_veto_vix_normal_pass():
    """VIX = 18 (NORMAL) PASSE."""
    bar = _make_bar(vix_level=18.0)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is True


# ============================================================
# MOMENTUM SYMBOL-AWARE (point dir_score)
# ============================================================

def test_momentum_symbol_aware_nq_threshold_10():
    """NQ : momentum_5b=5 NE compte PAS comme point (seuil NQ = 10)."""
    # NQ : cvd+1, delta+1, vwap+1, momentum=5 (< 10 -> pas de point) = bull 3.
    bar_nq = _make_bar(sym="NQ", momentum_5b=5.0, momentum_3b=2.0)
    verdict = compute_verdict(bar_nq, symbol="NQ")
    assert verdict.bull_pts == 3, f"bull_pts={verdict.bull_pts} (momentum 5<10 NQ ne compte pas)"


def test_momentum_symbol_aware_nq_threshold_passes_above_10():
    """NQ : momentum_5b=12 compte comme point (> seuil NQ 10)."""
    bar_nq = _make_bar(sym="NQ", momentum_5b=12.0, momentum_3b=6.0)
    verdict = compute_verdict(bar_nq, symbol="NQ")
    assert verdict.bull_pts == 4, f"bull_pts={verdict.bull_pts} (momentum 12>10 NQ compte)"


def test_momentum_symbol_aware_es_threshold_1():
    """ES : momentum_5b=2 compte (seuil ES = 1.0)."""
    bar_es = _make_bar(sym="ES", momentum_5b=2.0, momentum_3b=1.0)
    verdict = compute_verdict(bar_es, symbol="ES")
    assert verdict.bull_pts == 4


# ============================================================
# OVERRIDES ENV
# ============================================================

def test_veto_climax_disabled_via_env(monkeypatch):
    """BOT1V2_CLIMAX_VETO_ENABLED=false : climax ne bloque pas."""
    monkeypatch.setenv("BOT1V2_CLIMAX_VETO_ENABLED", "false")
    cfg = Bot1V2Config.from_env()
    bar = _make_bar(ctx_climax_signal=True)
    verdict = compute_verdict(bar, cfg=cfg)
    assert not any(v.name == "CLIMAX_WYCKOFF" for v in verdict.vetos)


def test_rvol_threshold_override_via_env(monkeypatch):
    """Override threshold rvol via env."""
    monkeypatch.setenv("BOT1V2_RVOL_ZSCORE_VETO_THRESHOLD", "2.0")
    cfg = Bot1V2Config.from_env()
    bar = _make_bar(rvol_zscore=2.5)
    verdict = compute_verdict(bar, cfg=cfg)
    assert any(v.name == "RVOL_EXCEPTIONAL" for v in verdict.vetos)
