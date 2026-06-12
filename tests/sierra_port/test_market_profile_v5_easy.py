"""Tests Phase A.2a - market_profile_v5.py EASY features (5 fonctions).

Couvre PSD+2/-2, Open Relation, Profile Overlap, Range Extension, FVG.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# 1. PSD+2 / PSD-2
# ════════════════════════════════════════════════════════════════════════════

def test_psd_sd2_basic_calculation():
    """sd_unit = sd1u - prev_vwap, sd2u = prev_vwap + 2*sd_unit."""
    from CORE.market_profile_v5 import compute_psd_sd2_levels
    payload = {
        "prev_vwap": 100.0,
        "prev_vwap_sd1u": 110.0,  # sd_unit = 10
        "prev_vwap_sd1d": 90.0,
    }
    out = compute_psd_sd2_levels(payload)
    assert out["prev_vwap_sd2u"] == 120.0  # 100 + 2*10
    assert out["prev_vwap_sd2d"] == 80.0   # 100 - 2*10


def test_psd_sd2_missing_inputs_returns_none():
    from CORE.market_profile_v5 import compute_psd_sd2_levels
    out = compute_psd_sd2_levels({})
    assert out["prev_vwap_sd2u"] is None
    assert out["prev_vwap_sd2d"] is None


def test_psd_sd2_invalid_types_returns_none():
    from CORE.market_profile_v5 import compute_psd_sd2_levels
    out = compute_psd_sd2_levels({"prev_vwap": "x", "prev_vwap_sd1u": 1, "prev_vwap_sd1d": 1})
    assert out["prev_vwap_sd2u"] is None


# ════════════════════════════════════════════════════════════════════════════
# 2. Open Relation Type
# ════════════════════════════════════════════════════════════════════════════

def test_open_relation_oair_within_va():
    """Open dans prev VA -> OAIR."""
    from CORE.market_profile_v5 import classify_open_relation
    payload = {
        "open_cash": 100.0, "prev_vah": 105.0, "prev_val": 95.0,
        "pdh": 110.0, "pdl": 90.0,
    }
    out = classify_open_relation(payload)
    assert out["open_within_prev_va"] is True
    assert out["open_relation_type"] == 1  # OAIR


def test_open_relation_oaor_above_va_within_range():
    """Open au-dessus VA mais dans prev range -> OAOR."""
    from CORE.market_profile_v5 import classify_open_relation
    payload = {
        "open_cash": 108.0, "prev_vah": 105.0, "prev_val": 95.0,
        "pdh": 110.0, "pdl": 90.0,
    }
    out = classify_open_relation(payload)
    assert out["open_above_prev_vah"] is True
    assert out["open_within_prev_va"] is False
    assert out["open_outside_prev_range"] is False
    assert out["open_relation_type"] == 2  # OAOR


def test_open_relation_oor_outside_range():
    """Open au-dessus PDH -> OOR."""
    from CORE.market_profile_v5 import classify_open_relation
    payload = {
        "open_cash": 115.0, "prev_vah": 105.0, "prev_val": 95.0,
        "pdh": 110.0, "pdl": 90.0,
    }
    out = classify_open_relation(payload)
    assert out["open_outside_prev_range"] is True
    assert out["open_relation_type"] == 3  # OOR


def test_open_relation_missing_returns_unknown():
    from CORE.market_profile_v5 import classify_open_relation
    out = classify_open_relation({})
    assert out["open_relation_type"] == 0


# ════════════════════════════════════════════════════════════════════════════
# 3. Profile Overlap
# ════════════════════════════════════════════════════════════════════════════

def test_profile_overlap_full_overlap():
    """Same VA = 100% overlap."""
    from CORE.market_profile_v5 import compute_profile_overlap
    payload = {
        "cur_vah": 105.0, "cur_val": 95.0,
        "prev_vah": 105.0, "prev_val": 95.0,
        "pdh": 110.0, "pdl": 90.0,
    }
    out = compute_profile_overlap(payload)
    assert out["profile_overlap_pct"] == 1.0


def test_profile_overlap_no_overlap():
    """VA disjoint = 0% overlap."""
    from CORE.market_profile_v5 import compute_profile_overlap
    payload = {
        "cur_vah": 120.0, "cur_val": 115.0,  # haut dans prev range
        "prev_vah": 105.0, "prev_val": 95.0,
        "pdh": 110.0, "pdl": 90.0,
    }
    out = compute_profile_overlap(payload)
    assert out["profile_overlap_pct"] == 0.0


def test_profile_overlap_partial():
    """Partial overlap = ratio."""
    from CORE.market_profile_v5 import compute_profile_overlap
    payload = {
        "cur_vah": 110.0, "cur_val": 100.0,  # chevauche le haut prev VA
        "prev_vah": 105.0, "prev_val": 95.0,  # prev range = 10
        "pdh": 110.0, "pdl": 90.0,
    }
    # Overlap = min(110, 105) - max(100, 95) = 105 - 100 = 5
    # Overlap_pct = 5 / 10 = 0.5
    out = compute_profile_overlap(payload)
    assert out["profile_overlap_pct"] == 0.5


def test_profile_overlap_missing_returns_none():
    from CORE.market_profile_v5 import compute_profile_overlap
    out = compute_profile_overlap({"cur_vah": 100})
    assert out["profile_overlap_pct"] is None


# ════════════════════════════════════════════════════════════════════════════
# 4. Range Extension vs IB
# ════════════════════════════════════════════════════════════════════════════

def test_range_extension_above_only():
    """sess_high > ib_high mais sess_low >= ib_low."""
    from CORE.market_profile_v5 import compute_range_extension
    payload = {
        "ib_high": 100.0, "ib_low": 90.0,
        "sess_high": 110.0, "sess_low": 95.0,  # extension above seulement
        "atr": 10.0,
    }
    out = compute_range_extension(payload)
    assert out["range_extension_above_ib_atr"] == 1.0  # (110-100)/10
    assert out["range_extension_below_ib_atr"] == 0.0
    assert out["range_extension_completed"] is False


def test_range_extension_both_completed():
    """sess depasse IB des 2 cotes."""
    from CORE.market_profile_v5 import compute_range_extension
    payload = {
        "ib_high": 100.0, "ib_low": 90.0,
        "sess_high": 105.0, "sess_low": 85.0,
        "atr": 10.0,
    }
    out = compute_range_extension(payload)
    assert out["range_extension_above_ib_atr"] == 0.5
    assert out["range_extension_below_ib_atr"] == 0.5
    assert out["range_extension_completed"] is True


def test_range_extension_no_extension():
    """sess contenu dans IB."""
    from CORE.market_profile_v5 import compute_range_extension
    payload = {
        "ib_high": 100.0, "ib_low": 90.0,
        "sess_high": 98.0, "sess_low": 92.0,
        "atr": 10.0,
    }
    out = compute_range_extension(payload)
    assert out["range_extension_above_ib_atr"] == 0.0
    assert out["range_extension_below_ib_atr"] == 0.0
    assert out["range_extension_completed"] is False


# ════════════════════════════════════════════════════════════════════════════
# 5. FVG detector
# ════════════════════════════════════════════════════════════════════════════

def test_fvg_up_created_3bar_pattern():
    """FVG UP : bar[t-2].high < bar[t].low."""
    from CORE.market_profile_v5 import detect_fvg, FVGState
    state = FVGState()
    # Bar 1: high=100, low=95 (t-2)
    detect_fvg({"bar_high": 100, "bar_low": 95, "close": 97, "atr": 5}, state)
    # Bar 2: high=110, low=98 (t-1, middle)
    detect_fvg({"bar_high": 110, "bar_low": 98, "close": 105, "atr": 5}, state)
    # Bar 3: high=115, low=105 (t, gap up : 100 < 105)
    out = detect_fvg({"bar_high": 115, "bar_low": 105, "close": 110, "atr": 5}, state)
    assert out["fvg_up_created_this_bar"] is True
    assert out["fvg_up_active"] == 1


def test_fvg_dn_created_3bar_pattern():
    """FVG DN : bar[t-2].low > bar[t].high."""
    from CORE.market_profile_v5 import detect_fvg, FVGState
    state = FVGState()
    detect_fvg({"bar_high": 110, "bar_low": 105, "close": 107, "atr": 5}, state)
    detect_fvg({"bar_high": 105, "bar_low": 95, "close": 100, "atr": 5}, state)
    out = detect_fvg({"bar_high": 100, "bar_low": 90, "close": 95, "atr": 5}, state)
    assert out["fvg_dn_created_this_bar"] is True
    assert out["fvg_dn_active"] == 1


def test_fvg_no_pattern_when_overlapping():
    """Pas de FVG si bars consecutives chevauchent."""
    from CORE.market_profile_v5 import detect_fvg, FVGState
    state = FVGState()
    detect_fvg({"bar_high": 100, "bar_low": 95, "close": 97, "atr": 5}, state)
    detect_fvg({"bar_high": 102, "bar_low": 96, "close": 100, "atr": 5}, state)
    out = detect_fvg({"bar_high": 99, "bar_low": 94, "close": 97, "atr": 5}, state)
    assert out["fvg_up_created_this_bar"] is False
    assert out["fvg_dn_created_this_bar"] is False


def test_fvg_state_isolated_per_instance():
    """2 FVGState distincts ne partagent pas l'etat (per-symbol isolation)."""
    from CORE.market_profile_v5 import detect_fvg, FVGState
    state_a = FVGState()
    state_b = FVGState()
    # Cree FVG dans state_a, pas dans state_b
    detect_fvg({"bar_high": 100, "bar_low": 95, "close": 97, "atr": 5}, state_a)
    detect_fvg({"bar_high": 110, "bar_low": 98, "close": 105, "atr": 5}, state_a)
    detect_fvg({"bar_high": 115, "bar_low": 105, "close": 110, "atr": 5}, state_a)
    out_b = detect_fvg({"bar_high": 200, "bar_low": 199, "close": 199, "atr": 5}, state_b)
    assert out_b["fvg_up_active"] == 0  # state_b vide


# ════════════════════════════════════════════════════════════════════════════
# 6. API publique
# ════════════════════════════════════════════════════════════════════════════

def test_compute_market_profile_v5_full_returns_dict():
    """API publique retourne dict avec toutes les features."""
    from CORE.market_profile_v5 import compute_market_profile_v5_features, FVGState
    payload = {
        "prev_vwap": 100.0, "prev_vwap_sd1u": 110.0, "prev_vwap_sd1d": 90.0,
        "open_cash": 105.0, "prev_vah": 108.0, "prev_val": 95.0,
        "pdh": 110.0, "pdl": 90.0,
        "cur_vah": 108.0, "cur_val": 100.0,
        "ib_high": 105.0, "ib_low": 95.0,
        "sess_high": 108.0, "sess_low": 92.0,
        "atr": 10.0,
        "bar_high": 106.0, "bar_low": 104.0, "close": 105.0,
    }
    state = FVGState()
    out = compute_market_profile_v5_features(payload, state)
    # Verifie keys essentielles
    expected_keys = [
        "prev_vwap_sd2u", "prev_vwap_sd2d",
        "open_relation_type", "open_within_prev_va",
        "profile_overlap_pct",
        "range_extension_above_ib_atr", "range_extension_completed",
        "fvg_up_active", "fvg_dn_active",
    ]
    for k in expected_keys:
        assert k in out, f"Missing key {k} in output"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
