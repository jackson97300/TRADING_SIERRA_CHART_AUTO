"""Tests sierra_compat - reconstruction des 6 features absentes."""
from __future__ import annotations

from CORE.bot_bn_v4.sierra_compat import (
    enrich_sierra_bar_for_bn_v4,
    detect_missing_features,
    list_required_features,
)


def test_dist_pvwap_pct_reconstruction():
    """dist_pvwap_pct = (pvwap - close) / close * 100. Positif si pvwap > close."""
    row = {"close": 30000.0, "pvwap": 30150.0}
    out = enrich_sierra_bar_for_bn_v4(row)
    assert "dist_pvwap_pct" in out
    # (30150 - 30000) / 30000 * 100 = 0.5
    assert abs(out["dist_pvwap_pct"] - 0.5) < 1e-6


def test_dist_pvwap_sd_reconstruction():
    """Reconstruct dist_pvwap_sd1u_pct + sd1d_pct."""
    row = {"close": 30000.0, "pvwap_sd1u": 30300.0, "pvwap_sd1d": 29700.0}
    out = enrich_sierra_bar_for_bn_v4(row)
    assert "dist_pvwap_sd1u_pct" in out
    assert "dist_pvwap_sd1d_pct" in out
    assert abs(out["dist_pvwap_sd1u_pct"] - 1.0) < 1e-6
    assert abs(out["dist_pvwap_sd1d_pct"] - (-1.0)) < 1e-6


def test_dist_vwap_w_sd2_reconstruction():
    """Reconstruct dist_vwap_w_sd2u_pct + sd2d_pct."""
    row = {"close": 30000.0, "vwap_w_sd2u": 31000.0, "vwap_w_sd2d": 29000.0}
    out = enrich_sierra_bar_for_bn_v4(row)
    # (31000-30000)/30000*100 = ~3.333
    assert abs(out["dist_vwap_w_sd2u_pct"] - 3.333333) < 1e-3
    assert abs(out["dist_vwap_w_sd2d_pct"] - (-3.333333)) < 1e-3


def test_big_buy_dominance_v2_source():
    """big_buy_dominance / big_sell_dominance via n_big_ask_v2_t1 + n_big_bid_v2_t1."""
    row = {"n_big_ask_v2_t1": 60, "n_big_bid_v2_t1": 40}
    out = enrich_sierra_bar_for_bn_v4(row)
    assert abs(out["big_buy_dominance"] - 0.6) < 1e-6
    assert abs(out["big_sell_dominance"] - 0.4) < 1e-6


def test_big_dominance_neutral_when_no_data():
    """Pas de big orders -> neutral 0.5 / 0.5."""
    row = {"n_big_ask_v2_t1": 0, "n_big_bid_v2_t1": 0}
    out = enrich_sierra_bar_for_bn_v4(row)
    assert out["big_buy_dominance"] == 0.5
    assert out["big_sell_dominance"] == 0.5


def test_existing_fields_not_overwritten():
    """Si dist_pvwap_pct deja present, NE PAS l'ecraser."""
    row = {"close": 30000.0, "pvwap": 30150.0, "dist_pvwap_pct": 99.0}
    out = enrich_sierra_bar_for_bn_v4(row)
    assert out["dist_pvwap_pct"] == 99.0  # preserve


def test_detect_missing_features():
    """detect_missing_features liste les fields critiques absents."""
    full = {"close": 1, "high": 1, "low": 1, "vwap_slope_10": 0.1, "ts_event_ns": 123}
    assert detect_missing_features(full) == []

    incomplete = {"close": 1, "high": 1}
    missing = detect_missing_features(incomplete)
    assert "low" in missing
    assert "vwap_slope_10" in missing


def test_list_required_features_includes_essentials():
    """list_required_features couvre les fields BN V4 essentiels."""
    feats = list_required_features()
    assert "close" in feats
    assert "vwap_slope_10" in feats
    assert "n_color_up_cluster_within_0_2pct" in feats
    assert "n_edge_buy_active" in feats
    assert "dist_pvwap_pct" in feats
    assert "big_buy_dominance" in feats
