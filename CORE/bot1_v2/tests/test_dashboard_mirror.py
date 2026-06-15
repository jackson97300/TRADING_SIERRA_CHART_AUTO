"""Tests dashboard_mirror.py - VETOS HARD + ETOILE-MERE.

Cas critique #1 : Trade ES SHORT 15/06 -$967 DOIT etre SKIP.
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
    """Bar synthetique avec valeurs QUALITE par defaut (6/6 etoiles + 0 veto).

    Permet de tester : bar de base passe (qualite forte conviction),
    puis on degrade une etoile/ajoute veto pour tester rejet.
    """
    base = {
        # Dashboard verdict FORT (ACHAT, pas ACHAT PRUDENT)
        "conseil_action": "ACHAT",
        "bull_pts": 6,
        "bear_pts": 0,
        # ETOILE 1 : bias score absolu fort + signe correct
        "bias_score": 0.6,
        "bias_label": "BULLISH",
        # ETOILE 2 : MTF aligne 4/4
        "mtf_bulls": 4,
        "mtf_bears": 0,
        "mtf_neutres": 0,
        # Order flow coherent
        "cvd_day_dir": 1,
        "delta_day_dir": 1,
        "vwap_d_side": 1,
        # ETOILE 3 : RVOL >= 1.3 (volume confirme)
        "rvol": 1.5,
        # ETOILE 4 : momentum fort dans direction (mais m3 < m5 = pullback)
        "momentum_5b": 3.0,
        "momentum_3b": 1.5,  # m3 < m5 -> pullback OK
        # ETOILE 5 : sur niveau de confluence
        "bool_near_level": 1,
        # ETOILE 6 : pullback - prix retrace depuis high
        "close": 7600.0,
        "sess_high": 7602.0,  # 2 pts = 8 ticks de retracement
        # Vetos -> tous OFF par defaut (qualite bar)
        "ctx_climax_signal": False,
        "rvol_zscore": 0.5,
        "gamma_block_long": False,
        "gamma_block_short": False,
        "vix_level": 17.0,  # NORMAL
        "vix_regime_label": "NORMAL",
    }
    base.update(overrides)
    return base


def _make_bar_short(**overrides):
    """Bar synthetique SHORT qualite (miroir de _make_bar pour SHORT)."""
    base = {
        "conseil_action": "VENTE",
        "bull_pts": 0,
        "bear_pts": 6,
        "bias_score": -0.6,
        "bias_label": "BEARISH",
        "mtf_bulls": 0,
        "mtf_bears": 4,
        "mtf_neutres": 0,
        "cvd_day_dir": -1,
        "delta_day_dir": -1,
        "vwap_d_side": -1,
        "rvol": 1.5,
        "momentum_5b": -3.0,
        "momentum_3b": -1.5,  # m3 > m5 -> bounce OK
        "bool_near_level": 1,
        # ETOILE 6 : bounce - prix remonte depuis low
        "close": 7600.0,
        "sess_low": 7598.0,  # 2 pts = 8 ticks de bounce
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
    """Le trade ES SHORT 15/06 17:55:00 UTC qui a perdu $967 DOIT etre rejected.

    Snapshot reel (DATA/_AUDIT/trades_20260615.jsonl) :
      - close=7633.75
      - cvd_day_dir=-1
      - ctx_climax_signal=True (Wyckoff)
      - rvol_zscore=3.74 (Dalton exceptional)
      - gamma_block_short=True (MenthorQ)
      - conseil_action="VENTE PRUDENTE"
    """
    bar = _make_bar(
        conseil_action="VENTE PRUDENTE",
        direction_hint="SHORT",
        bull_pts=0,
        bear_pts=4,
        bias_label="BEARISH",
        # Anti-SHORT signaux IGNORES par Bot 1 actuel :
        ctx_climax_signal=True,
        rvol_zscore=3.74,
        gamma_block_short=True,
        # Pro-SHORT signaux :
        cvd_day_dir=-1,
        delta_day_dir=-1,
        vwap_d_side=-1,
        momentum_5b=-5.75,
        vix_level=16.23,
    )
    verdict = compute_verdict(bar)

    # Le trade DOIT etre rejete (soit etoile-mere VENTE PRUDENTE eteinte,
    # soit vetos hard climax/rvol/gamma, soit quality misses).
    assert verdict.ready_to_arm is False, (
        f"BOT v2 DEVAIT REJECT ce trade. Got ready_to_arm=True. "
        f"action={verdict.action} vetos={verdict.vetos} "
        f"quality_misses={verdict.quality_misses}"
    )
    # Verifier que c'est rejete pour UNE bonne raison :
    veto_names = {v.name for v in verdict.vetos}
    is_veto_critique = bool(veto_names & {"CLIMAX_WYCKOFF", "RVOL_EXCEPTIONAL", "GAMMA_BLOCK_SHORT"})
    is_etoile_mere_eteinte = "DASHBOARD_VERDICT_REJECTED" in verdict.skip_reason
    assert is_veto_critique or is_etoile_mere_eteinte, (
        f"Rejet doit etre justifie par veto critique OR etoile-mere eteinte. "
        f"skip_reason={verdict.skip_reason}"
    )


# ============================================================
# CAS CRITIQUE #2 : NO PARALYSIS - trade de qualite doit passer
# ============================================================

def test_no_paralysis_quality_long_passes():
    """Un setup LONG de QUALITE (etoile-mere + tous vetos OFF) DOIT passer.

    Jackson souverain : "DES TRADES DE QUALITE DOIVENT PASSER, PAS TOUT BLOQUER"
    """
    bar = _make_bar(
        conseil_action="ACHAT",
        bull_pts=6,
        bear_pts=0,
        bias_label="BULLISH",
        mtf_bulls=4,
        mtf_bears=0,
        # Tous vetos OFF :
        ctx_climax_signal=False,
        rvol_zscore=0.3,
        gamma_block_long=False,
        gamma_block_short=False,
        vix_level=17.0,  # NORMAL
    )
    verdict = compute_verdict(bar)

    assert verdict.ready_to_arm is True, (
        f"BOT v2 DEVAIT ACCEPTER ce setup de qualite. "
        f"action={verdict.action} vetos={verdict.vetos} skip={verdict.skip_reason}"
    )
    assert verdict.direction == "LONG"
    assert verdict.vetos == ()


def test_no_paralysis_quality_short_passes():
    """Un setup SHORT de QUALITE FORTE CONVICTION (5/5 etoiles) DOIT passer."""
    bar = _make_bar_short()
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is True, (
        f"SHORT qualite doit passer. skip={verdict.skip_reason} "
        f"misses={verdict.quality_misses} stars={verdict.stars_count}/{verdict.stars_total}"
    )
    assert verdict.direction == "SHORT"
    assert verdict.stars_count == verdict.stars_total  # 6/6


def test_achat_prudent_rejected_force_conviction():
    """ACHAT PRUDENT rejected (FORTE CONVICTION : seulement ACHAT/VENTE fort)."""
    bar = _make_bar(conseil_action="ACHAT PRUDENT")
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False, (
        f"ACHAT PRUDENT doit etre REJETE (force conviction only)"
    )
    assert "DASHBOARD_VERDICT_REJECTED" in verdict.skip_reason


def test_vente_prudente_rejected():
    """VENTE PRUDENTE rejected."""
    bar = _make_bar_short(conseil_action="VENTE PRUDENTE")
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False


# ============================================================
# VETOS INDIVIDUELS
# ============================================================

def test_veto_climax_blocks_short():
    """Wyckoff climax + SHORT = veto hard."""
    bar = _make_bar(
        conseil_action="VENTE",
        bear_pts=5,
        ctx_climax_signal=True,
        cvd_day_dir=-1,
        delta_day_dir=-1,
        vwap_d_side=-1,
        mtf_bears=3,
    )
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
    """RVOL z = 2.5 PASSE (calibration NO PARALYSIS : seuil 3.0, pas 2.5)."""
    bar = _make_bar(rvol_zscore=2.5)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is True, (
        f"rvol_zscore=2.5 doit passer (seuil 3.0 NO PARALYSIS). "
        f"vetos={verdict.vetos}"
    )


def test_veto_gamma_blocks_short():
    """gamma_block_short=True + SHORT = veto hard (root cause -$967)."""
    bar = _make_bar(
        conseil_action="VENTE",
        bear_pts=5,
        gamma_block_short=True,
        cvd_day_dir=-1,
        delta_day_dir=-1,
        vwap_d_side=-1,
        mtf_bears=3,
    )
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
    bar = _make_bar(
        conseil_action="ACHAT",
        gamma_block_short=True,  # bloque SHORT seulement
        gamma_block_long=False,
    )
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


def test_etoile_mere_attendre_blocks():
    """Dashboard verdict ATTENDRE = SKIP (etoile-mere eteinte)."""
    bar = _make_bar(conseil_action="ATTENDRE")
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert "DASHBOARD_VERDICT_REJECTED" in verdict.skip_reason


# ============================================================
# ETOILES QUALITE INDIVIDUELLES (FORTE CONVICTION)
# ============================================================

def test_quality_bias_weak_rejects():
    """bias_score absolu < 0.5 -> quality miss BIAS_WEAK."""
    bar = _make_bar(bias_score=0.3)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "BIAS_WEAK" for m in verdict.quality_misses)


def test_quality_bias_opposite_rejects():
    """LONG mais bias_score negatif -> BIAS_OPPOSITE."""
    bar = _make_bar(bias_score=-0.6, bias_label="BULLISH")
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "BIAS_OPPOSITE" for m in verdict.quality_misses)


def test_quality_mtf_insufficient_rejects():
    """MTF aligne < 3 -> MTF_INSUFFICIENT."""
    bar = _make_bar(mtf_bulls=2, mtf_bears=0, mtf_neutres=2)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "MTF_INSUFFICIENT" for m in verdict.quality_misses)


def test_quality_mtf_conflict_rejects():
    """MTF aligne 3 mais 1 TF opposee -> MTF_CONFLICT."""
    bar = _make_bar(mtf_bulls=3, mtf_bears=1, mtf_neutres=0)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "MTF_CONFLICT" for m in verdict.quality_misses)


def test_quality_rvol_low_rejects():
    """RVOL < 1.3 -> RVOL_LOW."""
    bar = _make_bar(rvol=1.0)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "RVOL_LOW" for m in verdict.quality_misses)


def test_quality_momentum_weak_rejects():
    """momentum_5b absolu < 2.0 -> MOMENTUM_WEAK."""
    bar = _make_bar(momentum_5b=1.0)
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "MOMENTUM_WEAK" for m in verdict.quality_misses)


def test_quality_no_level_near_rejects():
    """bool_near_level=0 et pas niveau key proche -> NO_LEVEL_NEAR."""
    bar = _make_bar(
        bool_near_level=0,
        dist_cur_vpoc=20,  # trop loin
        dist_vwap_d=15,
        dist_cur_vah=12,
        dist_cur_val=18,
    )
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "NO_LEVEL_NEAR" for m in verdict.quality_misses)


def test_quality_partial_5_of_6_still_rejects():
    """5/6 etoiles allumees = rejet (FORTE CONVICTION = 6/6 strict)."""
    bar = _make_bar(rvol=1.0)  # 1 etoile manquante : RVOL_LOW
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False, "5/6 etoiles ne suffit pas (force conviction)"
    assert verdict.stars_count == 5
    assert verdict.stars_total == 6


def test_quality_pullback_long_required():
    """LONG sans pullback (close = sess_high) -> NO_PULLBACK_LONG."""
    bar = _make_bar(
        close=7602.0,  # AU high = pas de pullback
        sess_high=7602.0,
        momentum_3b=3.0,  # m3 = m5 = push, pas pullback
        momentum_5b=3.0,
    )
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "NO_PULLBACK_LONG" for m in verdict.quality_misses)


def test_quality_pullback_long_via_momentum_decline():
    """LONG : si pas sess_high, fallback momentum (m3 < m5 = pullback OK)."""
    bar = _make_bar(
        close=7600.0,
        momentum_5b=3.0,
        momentum_3b=1.0,  # m3 < m5 = pullback (momentum declining)
    )
    # Retire sess_high pour forcer fallback
    bar.pop("sess_high", None)
    verdict = compute_verdict(bar)
    # Si autre etoile ne fail pas
    assert verdict.stars_count >= 5  # pullback OK au moins


def test_quality_pullback_short_required():
    """SHORT sans bounce (close = sess_low) -> NO_PULLBACK_SHORT."""
    bar = _make_bar_short(
        close=7598.0,  # AU low = pas de bounce
        sess_low=7598.0,
        momentum_3b=-3.0,
        momentum_5b=-3.0,
    )
    verdict = compute_verdict(bar)
    assert verdict.ready_to_arm is False
    assert any(m.name == "NO_PULLBACK_SHORT" for m in verdict.quality_misses)


# ============================================================
# OVERRIDES ENV (toggle vetos pour debugging / backtest)
# ============================================================

def test_veto_climax_disabled_via_env(monkeypatch):
    """Si BOT1V2_CLIMAX_VETO_ENABLED=false, climax ne bloque pas."""
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
