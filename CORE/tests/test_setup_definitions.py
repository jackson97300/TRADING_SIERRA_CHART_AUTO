"""test_setup_definitions.py — Tests TDD des 11 setups + dispatcher.

Created : 2026-05-02 dimanche soir.

Approach :
  - 1 test "trigger" par setup (conditions exactes match)
  - 1 test "no_trigger" par setup (1 condition fail)
  - Tests filtrage symbole (NQ-only, ES-only)
  - Tests dispatcher evaluate_all_setups
  - Tests NaN/None safety
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest
from CORE.setup_definitions import (
    SETUP_REGISTRY,
    SETUP_CHECKERS,
    evaluate_all_setups,
    get_setups_for_symbol,
    check_sell_top_range,
    check_buy_cross_delta_agree,
    check_sell_late_session_fade,
    check_sell_1d_max_reject,
    check_buy_cvd_divergence,
    check_buy_bottom_range,
    check_sell_delta_exhaustion,
    check_sell_cvd_divergence,
    check_buy_vwap_reclaim,
    check_buy_mq_put_support,
    check_buy_naked_poc_magnet,
)


# ═══════════════════════════════════════════════════════════════════
# REGISTRY INTEGRITY
# ═══════════════════════════════════════════════════════════════════

def test_registry_has_11_setups():
    assert len(SETUP_REGISTRY) == 11


def test_registry_checkers_match():
    assert set(SETUP_REGISTRY.keys()) == set(SETUP_CHECKERS.keys())


def test_setups_per_symbol():
    # FIX B-5 (02/05) : BUY_NAKED_POC_MAGNET disabled Phase 1 mais reste dans REGISTRY
    # get_setups_for_symbol retourne TOUS les setups applicables (registry-level),
    # le filtre phase_1_disabled est dans evaluate_all_setups.
    assert len(get_setups_for_symbol("NQ")) == 9   # 6 univ + 3 NQ-only
    assert len(get_setups_for_symbol("ES")) == 8   # 6 univ + 2 ES-only
    assert len(get_setups_for_symbol("XX")) == 0   # symbole inconnu


def test_b5_naked_poc_phase1_disabled():
    """FIX B-5 : BUY_NAKED_POC_MAGNET marque phase_1_disabled = ne trigger pas live."""
    from CORE.setup_definitions import SETUP_REGISTRY, evaluate_all_setups
    assert SETUP_REGISTRY["BUY_NAKED_POC_MAGNET"].get("phase_1_disabled") == True
    # Bar avec conditions match BUY_NAKED_POC_MAGNET ES
    bar = {
        "n_naked_poc_within_0_5pct": 1,
        "position_in_range": 0.30,
        "delta_bar": 5,
    }
    triggered = evaluate_all_setups(bar, "ES")
    names = [t["name"] for t in triggered]
    assert "BUY_NAKED_POC_MAGNET" not in names, "Phase 1 disabled doit skip"


def test_invalid_symbol_returns_empty():
    assert evaluate_all_setups({"position_in_range": 0.95}, "INVALID") == []


# ═══════════════════════════════════════════════════════════════════
# TESTS PAR SETUP — UNIVERSELS
# ═══════════════════════════════════════════════════════════════════

class TestSellTopRange:
    def test_trigger(self):
        bar = {"position_in_range": 0.95, "finish_strength": -20}
        assert check_sell_top_range(bar, "NQ") is not None
        assert check_sell_top_range(bar, "ES") is not None

    def test_no_trigger_pos_too_low(self):
        bar = {"position_in_range": 0.85, "finish_strength": -20}
        assert check_sell_top_range(bar, "NQ") is None

    def test_no_trigger_finish_too_high(self):
        bar = {"position_in_range": 0.95, "finish_strength": -10}
        assert check_sell_top_range(bar, "NQ") is None

    def test_no_trigger_missing_feature(self):
        assert check_sell_top_range({}, "NQ") is None

    def test_no_trigger_nan(self):
        bar = {"position_in_range": float("nan"), "finish_strength": -20}
        assert check_sell_top_range(bar, "NQ") is None


class TestBuyCrossDeltaAgree:
    def test_trigger(self):
        bar = {"im_cross_delta_agreement_5": 0.8, "position_in_range": 0.20, "delta_bar": 5}
        assert check_buy_cross_delta_agree(bar, "NQ") is not None

    def test_no_trigger_low_agree(self):
        bar = {"im_cross_delta_agreement_5": 0.5, "position_in_range": 0.20, "delta_bar": 5}
        assert check_buy_cross_delta_agree(bar, "NQ") is None

    def test_no_trigger_high_pos(self):
        bar = {"im_cross_delta_agreement_5": 0.8, "position_in_range": 0.50, "delta_bar": 5}
        assert check_buy_cross_delta_agree(bar, "NQ") is None

    def test_no_trigger_negative_delta(self):
        bar = {"im_cross_delta_agreement_5": 0.8, "position_in_range": 0.20, "delta_bar": -5}
        assert check_buy_cross_delta_agree(bar, "NQ") is None


class TestSellLateSessionFade:
    def test_trigger(self):
        bar = {"time_to_session_close_norm": 0.10, "position_in_range": 0.85, "finish_strength": -10}
        assert check_sell_late_session_fade(bar, "ES") is not None

    def test_no_trigger_too_early(self):
        bar = {"time_to_session_close_norm": 0.50, "position_in_range": 0.85, "finish_strength": -10}
        assert check_sell_late_session_fade(bar, "ES") is None

    def test_no_trigger_low_pos(self):
        bar = {"time_to_session_close_norm": 0.10, "position_in_range": 0.50, "finish_strength": -10}
        assert check_sell_late_session_fade(bar, "ES") is None


class TestSell1dMaxReject:
    def test_trigger_above(self):
        bar = {"dist_1d_max_ticks_pct": 0.03, "finish_strength": -5}
        assert check_sell_1d_max_reject(bar, "NQ") is not None

    def test_trigger_below(self):
        bar = {"dist_1d_max_ticks_pct": -0.03, "finish_strength": -5}
        assert check_sell_1d_max_reject(bar, "NQ") is not None

    def test_no_trigger_too_far(self):
        bar = {"dist_1d_max_ticks_pct": 0.10, "finish_strength": -5}
        assert check_sell_1d_max_reject(bar, "NQ") is None


class TestBuyCvdDivergence:
    def test_trigger(self):
        bar = {"delta_day_dir": 1, "position_in_range": 0.20, "dist_vwap_d_pct": 0.10}
        assert check_buy_cvd_divergence(bar, "NQ") is not None
        assert check_buy_cvd_divergence(bar, "ES") is not None

    def test_no_trigger_wrong_ddd(self):
        bar = {"delta_day_dir": -1, "position_in_range": 0.20, "dist_vwap_d_pct": 0.10}
        assert check_buy_cvd_divergence(bar, "NQ") is None

    def test_no_trigger_dvwap_negative(self):
        # prix au-dessus VWAP (positif) requis
        bar = {"delta_day_dir": 1, "position_in_range": 0.20, "dist_vwap_d_pct": -0.10}
        assert check_buy_cvd_divergence(bar, "NQ") is None


class TestBuyBottomRange:
    def test_trigger(self):
        bar = {"position_in_range": 0.05, "rvol": 1.5, "delta_bar": 10}
        assert check_buy_bottom_range(bar, "NQ") is not None

    def test_no_trigger_low_rvol(self):
        bar = {"position_in_range": 0.05, "rvol": 0.8, "delta_bar": 10}
        assert check_buy_bottom_range(bar, "NQ") is None


# ═══════════════════════════════════════════════════════════════════
# TESTS PAR SETUP — NQ EXCLUSIFS
# ═══════════════════════════════════════════════════════════════════

class TestSellDeltaExhaustion:
    def test_trigger_nq_only(self):
        bar = {"ctx_delta_exhaustion": 0.7, "position_in_range": 0.85}
        assert check_sell_delta_exhaustion(bar, "NQ") is not None
        assert check_sell_delta_exhaustion(bar, "ES") is None  # filtree symbole

    def test_no_trigger_low_exhaustion(self):
        bar = {"ctx_delta_exhaustion": 0.3, "position_in_range": 0.85}
        assert check_sell_delta_exhaustion(bar, "NQ") is None


class TestSellCvdDivergence:
    def test_trigger_nq_only(self):
        bar = {"delta_day_dir": -1, "position_in_range": 0.85, "dist_vwap_d_pct": -0.10}
        assert check_sell_cvd_divergence(bar, "NQ") is not None
        assert check_sell_cvd_divergence(bar, "ES") is None  # filtree symbole

    def test_no_trigger_dvwap_positive(self):
        bar = {"delta_day_dir": -1, "position_in_range": 0.85, "dist_vwap_d_pct": 0.10}
        assert check_sell_cvd_divergence(bar, "NQ") is None


class TestBuyVwapReclaim:
    def test_trigger_nq_only(self):
        bar = {"dist_vwap_d_pct": 0.02, "vwap_slope_10": 2.5, "rvol": 0.8}
        assert check_buy_vwap_reclaim(bar, "NQ") is not None
        assert check_buy_vwap_reclaim(bar, "ES") is None

    def test_no_trigger_flat_slope(self):
        bar = {"dist_vwap_d_pct": 0.02, "vwap_slope_10": 0.5, "rvol": 0.8}
        assert check_buy_vwap_reclaim(bar, "NQ") is None


# ═══════════════════════════════════════════════════════════════════
# TESTS PAR SETUP — ES EXCLUSIFS
# ═══════════════════════════════════════════════════════════════════

class TestBuyMqPutSupport:
    def test_trigger_es_only(self):
        bar = {"dist_mq_put_pct": -0.5, "delta_bar": 10, "rvol": 0.8}
        assert check_buy_mq_put_support(bar, "ES") is not None
        assert check_buy_mq_put_support(bar, "NQ") is None  # filtree symbole

    def test_no_trigger_too_far(self):
        bar = {"dist_mq_put_pct": -2.0, "delta_bar": 10, "rvol": 0.8}
        assert check_buy_mq_put_support(bar, "ES") is None


class TestBuyNakedPocMagnet:
    def test_checker_still_works_es_only(self):
        """Checker pure function continue de retourner conditions matched
        (pour test logique). Le skip phase_1_disabled est dans evaluate_all_setups."""
        bar = {"n_naked_poc_within_0_5pct": 1, "position_in_range": 0.30, "delta_bar": 5}
        assert check_buy_naked_poc_magnet(bar, "ES") is not None
        assert check_buy_naked_poc_magnet(bar, "NQ") is None

    def test_no_trigger_no_naked(self):
        bar = {"n_naked_poc_within_0_5pct": 0, "position_in_range": 0.30, "delta_bar": 5}
        assert check_buy_naked_poc_magnet(bar, "ES") is None


# ═══════════════════════════════════════════════════════════════════
# TESTS DISPATCHER evaluate_all_setups
# ═══════════════════════════════════════════════════════════════════

class TestDispatcher:
    def test_no_match_empty_list(self):
        bar = {"position_in_range": 0.50, "finish_strength": 0}
        result = evaluate_all_setups(bar, "NQ")
        assert result == []

    def test_single_match(self):
        bar = {"position_in_range": 0.95, "finish_strength": -20,
               "delta_day_dir": 0, "dist_vwap_d_pct": 0,
               "im_cross_delta_agreement_5": 0.0, "delta_bar": 0,
               "time_to_session_close_norm": 0.50,
               "dist_1d_max_ticks_pct": 0.20, "rvol": 1.0,
               "ctx_delta_exhaustion": 0.0, "vwap_slope_10": 0.0,
               "n_naked_poc_within_0_5pct": 0, "dist_mq_put_pct": -10}
        result = evaluate_all_setups(bar, "NQ")
        # SELL_TOP_RANGE seul devrait trigger (les autres ont pos > 0.70 mais
        # SELL_DELTA_EXH a exh=0, SELL_CVD_DIV a dvwap=0 not < -0.05)
        names = [t["name"] for t in result]
        assert "SELL_TOP_RANGE" in names

    def test_confluence_multiple_short(self):
        # SELL_TOP_RANGE + SELL_LATE_SESSION_FADE devraient trigger ensemble
        bar = {"position_in_range": 0.95, "finish_strength": -20,
               "time_to_session_close_norm": 0.20,
               "delta_day_dir": 0, "dist_vwap_d_pct": 0,
               "im_cross_delta_agreement_5": 0.0, "delta_bar": 0,
               "dist_1d_max_ticks_pct": 0.20, "rvol": 1.0,
               "ctx_delta_exhaustion": 0.0, "vwap_slope_10": 0.0}
        result = evaluate_all_setups(bar, "ES")
        names = [t["name"] for t in result]
        assert "SELL_TOP_RANGE" in names
        assert "SELL_LATE_SESSION_FADE" in names
        # Tous SHORT
        assert all(t["side"] == "SHORT" for t in result)

    def test_filtre_es_only_setup_not_in_nq_eval(self):
        bar = {"dist_mq_put_pct": -0.5, "delta_bar": 10, "rvol": 0.8,
               "position_in_range": 0.50, "finish_strength": 0}
        result_nq = evaluate_all_setups(bar, "NQ")
        result_es = evaluate_all_setups(bar, "ES")
        names_nq = [t["name"] for t in result_nq]
        names_es = [t["name"] for t in result_es]
        assert "BUY_MQ_PUT_SUPPORT" not in names_nq
        assert "BUY_MQ_PUT_SUPPORT" in names_es


# ═══════════════════════════════════════════════════════════════════
# NaN / None SAFETY
# ═══════════════════════════════════════════════════════════════════

class TestNaNSafety:
    def test_all_setups_handle_empty_dict(self):
        for name, checker in SETUP_CHECKERS.items():
            for sym in ("NQ", "ES"):
                # ne doit jamais crasher
                result = checker({}, sym)
                assert result is None, f"{name}/{sym}: empty dict should return None"

    def test_all_setups_handle_nan_values(self):
        bar_nan = {k: float("nan") for k in [
            "position_in_range", "finish_strength", "im_cross_delta_agreement_5",
            "delta_bar", "time_to_session_close_norm", "dist_1d_max_ticks_pct",
            "delta_day_dir", "dist_vwap_d_pct", "rvol", "ctx_delta_exhaustion",
            "vwap_slope_10", "dist_mq_put_pct", "n_naked_poc_within_0_5pct",
        ]}
        for name, checker in SETUP_CHECKERS.items():
            for sym in ("NQ", "ES"):
                result = checker(bar_nan, sym)
                assert result is None, f"{name}/{sym}: NaN should return None"

    def test_evaluate_all_handles_empty_bar(self):
        assert evaluate_all_setups({}, "NQ") == []
        assert evaluate_all_setups({}, "ES") == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
