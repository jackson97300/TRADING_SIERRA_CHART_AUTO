"""Tests Bot 3 v2 Phase 1.7b — BLOCKED_COMBOS_BOT3 + SESSION_BOOST_CONFIDENCE.

Source : audit Phase 1.0 post-enrichissement v4 enriched (17/05/2026).
  - DATA/BACKTEST/BOT3/combos_session_level_post_fix_6m_v4_enriched.csv
  - DOCS/BOT3_V2_PHASE1_0_AUDIT_REPORT.md
Reviews : ml-trainer GO + market-analyst GO + code-reviewer GO.

Verifie :
1. 5 combos BLOCK ES (ASIA SIDAK_SWING_HIGH/SWING_LOW/VWAP_W_SD1D + LONDON CUR_VPOC/SINGLE_PRINT)
2. 1 combo BOOST NQ LONDON SIDAK_COLOR_UP_zone (confidence +15)
3. Cas hors-combo : no-op (pas de BLOCK ni BOOST)
4. ES US_CASH SIDAK_COLOR_DN_zone : HOLD (pas de BOOST applique, decision ml-trainer)
5. Reason format `BLOCK_COMBO_{symbol}_{session}_{level_name}` → mapping log_catalog OK
6. params BLOCK contient pf_observed + n_calibration + dsr_block pour audit
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bot3_decision_engine import evaluate_decision  # noqa: E402
from CORE.bot3_config import BLOCKED_COMBOS_BOT3, SESSION_BOOST_CONFIDENCE  # noqa: E402
from CORE.bot3_level_definitions import (  # noqa: E402
    TIER1, TIER2, TIER3, TIER2_LEVELS_NEUTRAL, SIDAK_LEVELS,
)
from CORE.bot3_mp_engine import reason_to_log_code  # noqa: E402


# Re-use base_ctx pattern from test_bot3_decision_engine.py
def base_ctx(session: str = "US_CASH", **overrides) -> dict:
    """Contexte minimal sain pour evaluer une decision."""
    ctx = {
        "session": session,
        # Vetos OFF
        "is_roll_day": 0,
        "within_news_715_5m": 0, "within_news_730_5m": 0,
        "within_news_830_5m": 0, "within_news_845_5m": 0,
        "within_news_900_5m": 0, "within_news_930_5m": 0,
        "mins_since_news": 999,
        "rvol": 1.0,
        "mq_levels_stale": False,
        # Filtres anti-trend OFF
        "poc_mig_dir": 0, "poc_mig_speed": 0.0, "va_dev": 0.5,
        # Orderflow neutre
        "delta_bar": 10.0, "finish_strength": 5.0,
        # Tier 1 NEUTRAL features
        "delta_pct": 0.05,
        "bn_absorb_bid_at_level": 0,
        "bn_absorb_ask_at_level": 0,
        "n_big_bid_t3": 0, "n_big_bid_t4": 0,
        "n_big_ask_t3": 0, "n_big_ask_t4": 0,
        # Tier 2 NEUTRAL features
        "liq_sweep_high": 0, "liq_sweep_low": 0,
        "vol_zscore_20": 0.5,
        "cvd_session": 0.0, "cvd_divergence": False, "cvd_divergence_dir": 0,
        "color_cluster_up": 0, "color_cluster_dn": 0, "color_imbalance": 0,
        # TIER S features neutres
        "bar_body_pct": 0.7,
        "bar_upper_wick_pct": 0.15,
        "bar_lower_wick_pct": 0.15,
        "bar_no_trade": 0,
        "cur_va_n_buckets": 18,
        "cur_va_total_vol": 1000.0,
        "max_delta_bar": 50.0,
        "min_delta_bar": -30.0,
        "delta_change": 5.0,
        "spike_detected_lag3": 0,
        "vol_spike_up": 0, "vol_spike_dn": 0,
        "bn_stack_ask": 0, "bn_stack_bid": 0,
        # Tier 3 vars
        "cvd_trend": "FLAT", "open_type": 0, "position_in_range": 0.8,
        # Confidence boosts OFF
        "n_big_bid_t2": 0, "n_big_ask_t2": 0,
        "failed_auction": 0.0, "cross_delta_agree": 0.0,
        "smt_divergence": 0,
        "n_trapped_buy_cluster": 0, "n_trapped_sell_cluster": 0,
        # ATR
        "atr_14m_pct": 0.033,
    }
    ctx.update(overrides)
    return ctx


# Level_def minimaux pour les combos testes (cherche dans bot3_level_definitions)
def _level_def(name: str) -> dict:
    """Recupere le level_def depuis tous les buckets (TIER1/2/3 + NEUTRAL + SIDAK)."""
    for d in (TIER1, TIER2, TIER3, TIER2_LEVELS_NEUTRAL, SIDAK_LEVELS):
        if name in d:
            return d[name]
    pytest.fail(f"level_def {name} introuvable")


# ═══════════════════ BLOCK 5 combos ES ═══════════════════

def test_block_es_asia_sidak_swing_high():
    ctx = base_ctx(session="ASIA")
    level_def = _level_def("SIDAK_SWING_HIGH")
    trade, reason, params = evaluate_decision(
        "SIDAK_SWING_HIGH", level_def, ctx, "ES", dist_signed=0.01)
    assert trade is False
    assert reason == "BLOCK_COMBO_ES_ASIA_SIDAK_SWING_HIGH"
    assert params["pf_observed"] == 0.46
    assert params["n_calibration"] == 306
    assert params["dsr_block"] == 1.0
    assert params["session"] == "ASIA"
    assert params["level"] == "SIDAK_SWING_HIGH"


def test_block_es_asia_vwap_w_sd1d():
    ctx = base_ctx(session="ASIA")
    level_def = _level_def("VWAP_W_SD1D")
    trade, reason, params = evaluate_decision(
        "VWAP_W_SD1D", level_def, ctx, "ES", dist_signed=0.01)
    assert trade is False
    assert reason == "BLOCK_COMBO_ES_ASIA_VWAP_W_SD1D"
    assert params["pf_observed"] == 0.52


def test_block_es_asia_sidak_swing_low():
    ctx = base_ctx(session="ASIA")
    level_def = _level_def("SIDAK_SWING_LOW")
    trade, reason, params = evaluate_decision(
        "SIDAK_SWING_LOW", level_def, ctx, "ES", dist_signed=-0.01)
    assert trade is False
    assert reason == "BLOCK_COMBO_ES_ASIA_SIDAK_SWING_LOW"
    assert params["pf_observed"] == 0.53


def test_block_es_london_cur_vpoc():
    ctx = base_ctx(session="LONDON")
    level_def = _level_def("CUR_VPOC")
    trade, reason, params = evaluate_decision(
        "CUR_VPOC", level_def, ctx, "ES", dist_signed=0.01)
    assert trade is False
    assert reason == "BLOCK_COMBO_ES_LONDON_CUR_VPOC"
    assert params["pf_observed"] == 0.45


def test_block_es_london_single_print():
    ctx = base_ctx(session="LONDON")
    level_def = _level_def("SINGLE_PRINT")
    trade, reason, params = evaluate_decision(
        "SINGLE_PRINT", level_def, ctx, "ES", dist_signed=0.01)
    assert trade is False
    assert reason == "BLOCK_COMBO_ES_LONDON_SINGLE_PRINT"
    assert params["pf_observed"] == 0.66


# ═══════════════════ BOOST NQ LONDON COLOR_UP_zone ═══════════════════

def test_boost_nq_london_sidak_color_up():
    ctx = base_ctx(session="LONDON")
    level_def = _level_def("SIDAK_COLOR_UP_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_UP_zone", level_def, ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert reason == "GO"
    # Baseline 50 + 15 (boost) = 65 minimum (autres boosts neutres dans base_ctx)
    assert params["confidence"] >= 65
    assert params["confidence"] <= 100  # clamp


# ═══════════════════ HOLD ES US_CASH SIDAK_COLOR_DN_zone (decision ml-trainer) ═══════════════════

def test_hold_es_us_cash_sidak_color_dn_no_boost():
    """ES US_CASH SIDAK_COLOR_DN_zone NE DOIT PAS avoir de boost.
    ml-trainer HOLD : n=189 + CI [1.21, 2.71] trop large. Re-eval J+30.
    """
    ctx = base_ctx(session="US_CASH")
    level_def = _level_def("SIDAK_COLOR_DN_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_DN_zone", level_def, ctx, "ES", dist_signed=0.01)
    assert trade is True
    assert reason == "GO"
    # Confidence baseline 50 sans boost = 50 (autres bonus neutres base_ctx)
    assert params["confidence"] == 50  # exactement, pas de boost ES US_CASH


# ═══════════════════ HORS combo (pas de BLOCK ni BOOST) ═══════════════════

def test_no_block_no_boost_when_combo_not_present():
    """IB_LOW NQ ASIA n'est PAS dans BLOCKED_COMBOS ni SESSION_BOOST → trade normal."""
    ctx = base_ctx(session="ASIA")
    level_def = _level_def("IB_LOW")
    trade, reason, params = evaluate_decision(
        "IB_LOW", level_def, ctx, "NQ", dist_signed=-0.01)
    # Trade pourrait etre False par d'autres raisons (TIER3, anti-trend, etc.)
    # mais reason ne DOIT PAS commencer par BLOCK_COMBO_
    assert not reason.startswith("BLOCK_COMBO_")


def test_no_block_es_us_cash_sidak_swing_high():
    """SIDAK_SWING_HIGH ES US_CASH (pas ASIA) → pas BLOCK. Seul ES ASIA est BLOCKE."""
    ctx = base_ctx(session="US_CASH")
    level_def = _level_def("SIDAK_SWING_HIGH")
    trade, reason, params = evaluate_decision(
        "SIDAK_SWING_HIGH", level_def, ctx, "ES", dist_signed=0.01)
    assert not reason.startswith("BLOCK_COMBO_")


def test_no_boost_nq_us_cash_sidak_color_up():
    """NQ US_CASH SIDAK_COLOR_UP_zone (pas LONDON) → pas de boost.
    Seul NQ LONDON est BOOSTE.
    """
    ctx = base_ctx(session="US_CASH")
    level_def = _level_def("SIDAK_COLOR_UP_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_UP_zone", level_def, ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert reason == "GO"
    assert params["confidence"] == 50  # baseline exact, pas de boost US_CASH NQ


# ═══════════════════ Compatibilite log_catalog (R1 code-reviewer) ═══════════════════

def test_block_reason_maps_to_log_catalog_code():
    """Le reason BLOCK_COMBO_* doit etre route vers BOT3_BLOCK_COMBO via reason_to_log_code."""
    assert reason_to_log_code("BLOCK_COMBO_ES_ASIA_SIDAK_SWING_HIGH") == "BOT3_BLOCK_COMBO"
    assert reason_to_log_code("BLOCK_COMBO_ES_LONDON_CUR_VPOC") == "BOT3_BLOCK_COMBO"
    assert reason_to_log_code("BLOCK_COMBO_XX_YYY_ZZZ") == "BOT3_BLOCK_COMBO"


def test_log_catalog_has_block_and_boost_codes():
    """log_catalog.py doit avoir les 2 codes definis (R1 obligatoire)."""
    from CORE.log_catalog import LOG_CODES
    assert "BOT3_BLOCK_COMBO" in LOG_CODES
    assert "BOT3_BOOST_APPLIED" in LOG_CODES
    # Verifier que les templates contiennent les placeholders attendus
    _, _, tpl_block = LOG_CODES["BOT3_BLOCK_COMBO"]
    assert "{sym}" in tpl_block and "{session}" in tpl_block and "{level}" in tpl_block
    _, _, tpl_boost = LOG_CODES["BOT3_BOOST_APPLIED"]
    assert "{boost}" in tpl_boost


# ═══════════════════ Config sanity ═══════════════════

def test_blocked_combos_count_5():
    """Le dict BLOCKED_COMBOS_BOT3 contient exactement 5 combos (audit nuit 17/05)."""
    assert len(BLOCKED_COMBOS_BOT3) == 5
    # Tous ES (pas NQ ni MGC)
    for (sym, _, _) in BLOCKED_COMBOS_BOT3:
        assert sym == "ES"


def test_session_boost_count_1():
    """Le dict SESSION_BOOST_CONFIDENCE contient 1 combo (NQ LONDON, ES US_CASH HOLD)."""
    assert len(SESSION_BOOST_CONFIDENCE) == 1
    assert ("NQ", "LONDON", "SIDAK_COLOR_UP_zone") in SESSION_BOOST_CONFIDENCE
    # ES US_CASH NE DOIT PAS etre dans le dict (HOLD ml-trainer)
    assert ("ES", "US_CASH", "SIDAK_COLOR_DN_zone") not in SESSION_BOOST_CONFIDENCE


def test_blocked_combos_metadata_complete():
    """Chaque combo BLOCK doit avoir pf_observed + n + dsr_block + folds + pnl_evite."""
    required = {"pf_observed", "n", "dsr_block", "folds_lt_0_7", "pnl_evite_ticks"}
    for k, v in BLOCKED_COMBOS_BOT3.items():
        assert required.issubset(v.keys()), f"Missing keys for {k}: {required - v.keys()}"
        assert v["pf_observed"] < 0.7, f"PF observed {v['pf_observed']} >= 0.7 pour {k}"
        assert v["dsr_block"] >= 0.95
        assert v["n"] >= 100


def test_session_boost_metadata_complete():
    """Le combo BOOST doit avoir boost + pf_observed + n + dsr_boost + folds + pnl_gain."""
    required = {"boost", "pf_observed", "n", "dsr_boost", "folds_ge_1_3", "pnl_gain_ticks"}
    for k, v in SESSION_BOOST_CONFIDENCE.items():
        assert required.issubset(v.keys())
        assert v["pf_observed"] >= 1.3
        assert v["dsr_boost"] >= 0.95
        assert v["n"] >= 100
        assert v["boost"] > 0
