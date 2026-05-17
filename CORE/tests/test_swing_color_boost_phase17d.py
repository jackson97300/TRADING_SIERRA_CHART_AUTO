"""Tests Bot 3 v2 Phase 1.7d — SWING_COLOR_BOOSTED confluence boost.

Source : audit empirique tools/audit_color_vs_longbar_comparison.py
  - 11 GOOD_EDGE combos COLOR (DSR Lopez 1.0, n>=50, PF>=1.3)
  - COLOR seul superieur a LONG_BAR + COMBINE (cf DOCS/BOT3_V2_PHASE1_0_AUDIT_REPORT)

Verifie :
1. _compute_swing_color_consensus classifie correctement (CONFLUENCE_STRONG/OK/DIVERGENCE/NEUTRE)
2. 11 combos GOOD_EDGE recoivent le bon boost
3. Combos hors dict : no-op (pas de boost)
4. DIVERGENCE bucket = pas de boost meme si proche
5. params return contient swing_color_consensus + swing_color_boost_applied
6. log_catalog BOT3_SWING_COLOR_BOOST defini
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bot3_decision_engine import (  # noqa: E402
    evaluate_decision, _compute_swing_color_consensus,
)
from CORE.bot3_config import (  # noqa: E402
    SWING_COLOR_BOOSTED, SWING_COLOR_PROXIMITY_PCT,
)
from CORE.bot3_level_definitions import (  # noqa: E402
    TIER1, TIER2, TIER3, TIER2_LEVELS_NEUTRAL, SIDAK_LEVELS,
)


def base_ctx(session: str = "US_CASH", **overrides) -> dict:
    """Contexte minimal sain pour evaluer une decision."""
    ctx = {
        "session": session,
        "is_roll_day": 0,
        "within_news_715_5m": 0, "within_news_730_5m": 0,
        "within_news_830_5m": 0, "within_news_845_5m": 0,
        "within_news_900_5m": 0, "within_news_930_5m": 0,
        "mins_since_news": 999,
        "rvol": 1.0,
        "mq_levels_stale": False,
        "poc_mig_dir": 0, "poc_mig_speed": 0.0, "va_dev": 0.5,
        "delta_bar": 10.0, "finish_strength": 5.0,
        "delta_pct": 0.05,
        "bn_absorb_bid_at_level": 0, "bn_absorb_ask_at_level": 0,
        "n_big_bid_t3": 0, "n_big_bid_t4": 0,
        "n_big_ask_t3": 0, "n_big_ask_t4": 0,
        "liq_sweep_high": 0, "liq_sweep_low": 0,
        "vol_zscore_20": 0.5,
        "cvd_session": 0.0, "cvd_divergence": False, "cvd_divergence_dir": 0,
        "color_cluster_up": 0, "color_cluster_dn": 0, "color_imbalance": 0,
        "bar_body_pct": 0.7, "bar_upper_wick_pct": 0.15, "bar_lower_wick_pct": 0.15,
        "bar_no_trade": 0, "cur_va_n_buckets": 18, "cur_va_total_vol": 1000.0,
        "max_delta_bar": 50.0, "min_delta_bar": -30.0, "delta_change": 5.0,
        "spike_detected_lag3": 0, "vol_spike_up": 0, "vol_spike_dn": 0,
        "bn_stack_ask": 0, "bn_stack_bid": 0,
        "cvd_trend": "FLAT", "open_type": 0, "position_in_range": 0.8,
        "n_big_bid_t2": 0, "n_big_ask_t2": 0,
        "failed_auction": 0.0, "cross_delta_agree": 0.0,
        "smt_divergence": 0,
        "n_trapped_buy_cluster": 0, "n_trapped_sell_cluster": 0,
        "atr_14m_pct": 0.033,
        # Phase 1.7d : features color proximity (defaut = pas proche)
        "dist_color_up_nearest_pct": 0.20,   # > 0.05% threshold
        "dist_color_dn_nearest_pct": 0.20,
        "aggressor_imbalance": 0.0,
    }
    ctx.update(overrides)
    return ctx


def _level_def(name: str) -> dict:
    for d in (TIER1, TIER2, TIER3, TIER2_LEVELS_NEUTRAL, SIDAK_LEVELS):
        if name in d:
            return d[name]
    pytest.fail(f"level_def {name} introuvable")


# ═══════════════════ _compute_swing_color_consensus unit tests ═══════════════════

def test_consensus_long_confluence_strong():
    """LONG + color_up proche + imbalance >= 0 -> CONFLUENCE_STRONG."""
    ctx = {"dist_color_up_nearest_pct": 0.02, "dist_color_dn_nearest_pct": 1.0,
           "aggressor_imbalance": 0.3}
    assert _compute_swing_color_consensus("LONG", ctx) == "CONFLUENCE_STRONG"


def test_consensus_long_confluence_ok():
    """LONG + color_up proche + imbalance < 0 -> CONFLUENCE_OK (seul color)."""
    ctx = {"dist_color_up_nearest_pct": 0.03, "dist_color_dn_nearest_pct": 1.0,
           "aggressor_imbalance": -0.2}
    assert _compute_swing_color_consensus("LONG", ctx) == "CONFLUENCE_OK"


def test_consensus_long_divergence():
    """LONG + color_dn proche + imbalance < 0 -> DIVERGENCE (sellers crush)."""
    ctx = {"dist_color_up_nearest_pct": 1.0, "dist_color_dn_nearest_pct": 0.02,
           "aggressor_imbalance": -0.4}
    assert _compute_swing_color_consensus("LONG", ctx) == "DIVERGENCE"


def test_consensus_long_neutre():
    """LONG + aucune zone proche -> NEUTRE."""
    ctx = {"dist_color_up_nearest_pct": 0.5, "dist_color_dn_nearest_pct": 0.5,
           "aggressor_imbalance": 0.0}
    assert _compute_swing_color_consensus("LONG", ctx) == "NEUTRE"


def test_consensus_short_confluence_strong():
    """SHORT + color_dn proche + imbalance <= 0 -> CONFLUENCE_STRONG."""
    ctx = {"dist_color_up_nearest_pct": 1.0, "dist_color_dn_nearest_pct": 0.02,
           "aggressor_imbalance": -0.3}
    assert _compute_swing_color_consensus("SHORT", ctx) == "CONFLUENCE_STRONG"


def test_consensus_short_divergence():
    """SHORT + color_up proche + imbalance > 0 -> DIVERGENCE (buyers crush)."""
    ctx = {"dist_color_up_nearest_pct": 0.02, "dist_color_dn_nearest_pct": 1.0,
           "aggressor_imbalance": 0.4}
    assert _compute_swing_color_consensus("SHORT", ctx) == "DIVERGENCE"


def test_consensus_nan_safe():
    """NaN sur distances -> NEUTRE (pas de crash)."""
    import math
    ctx = {"dist_color_up_nearest_pct": math.nan,
           "dist_color_dn_nearest_pct": None,
           "aggressor_imbalance": 0.0}
    assert _compute_swing_color_consensus("LONG", ctx) == "NEUTRE"


# ═══════════════════ Integration : evaluate_decision applique le boost ═══════════════════

def test_boost_nq_sidak_color_up_zone_confluence_strong():
    """NQ SIDAK_COLOR_UP_zone + CONFLUENCE_STRONG -> +15 boost (PF 1.93 n=1279)."""
    ctx = base_ctx(
        session="LONDON",   # session Boost 1.7b aussi -> stack +15+15 = +30
        dist_color_up_nearest_pct=0.02,
        dist_color_dn_nearest_pct=1.0,
        aggressor_imbalance=0.3,
    )
    level_def = _level_def("SIDAK_COLOR_UP_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_UP_zone", level_def, ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert params["swing_color_consensus"] == "CONFLUENCE_STRONG"
    assert "swing_color_boost_applied" in params
    assert params["swing_color_boost_applied"]["boost"] == 15
    # Confidence = 50 baseline + 15 (1.7b session boost NQ LONDON) + 15 (1.7d swing color) = 80
    assert params["confidence"] == 80


def test_boost_nq_sidak_color_up_zone_confluence_ok():
    """NQ SIDAK_COLOR_UP_zone + CONFLUENCE_OK -> +20 boost (PF 3.40 n=429)."""
    ctx = base_ctx(
        session="US_CASH",   # pas LONDON donc pas de 1.7b session boost
        dist_color_up_nearest_pct=0.03,
        dist_color_dn_nearest_pct=1.0,
        aggressor_imbalance=-0.2,   # < 0 -> CONFLUENCE_OK (pas STRONG)
    )
    level_def = _level_def("SIDAK_COLOR_UP_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_UP_zone", level_def, ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert params["swing_color_consensus"] == "CONFLUENCE_OK"
    assert params["swing_color_boost_applied"]["boost"] == 20
    # Confidence = 50 + 20 = 70
    assert params["confidence"] == 70


def test_boost_nq_mq_put_0dte_confluence_strong():
    """NQ MQ_PUT_0DTE + CONFLUENCE_STRONG -> +15 (put_support Jackson)."""
    ctx = base_ctx(
        session="US_CASH",
        dist_color_up_nearest_pct=0.02,
        aggressor_imbalance=0.3,
    )
    level_def = _level_def("MQ_PUT_0DTE")
    trade, reason, params = evaluate_decision(
        "MQ_PUT_0DTE", level_def, ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert params["swing_color_consensus"] == "CONFLUENCE_STRONG"
    assert params["swing_color_boost_applied"]["boost"] == 15


def test_no_boost_nq_sidak_color_up_divergence():
    """NQ SIDAK_COLOR_UP_zone + DIVERGENCE -> pas de boost (Phase 2 BLOCK potentiel)."""
    ctx = base_ctx(
        session="US_CASH",
        dist_color_up_nearest_pct=1.0,
        dist_color_dn_nearest_pct=0.02,
        aggressor_imbalance=-0.3,
    )
    level_def = _level_def("SIDAK_COLOR_UP_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_UP_zone", level_def, ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert params["swing_color_consensus"] == "DIVERGENCE"
    assert "swing_color_boost_applied" not in params
    assert params["confidence"] == 50  # baseline seul


def test_no_boost_es_sidak_color_dn_zone():
    """ES SIDAK_COLOR_DN_zone PAS dans SWING_COLOR_BOOSTED -> pas de boost.

    (ES SHORT non valide DSR Lopez sur color, cf audit empirique 17/05.)
    """
    ctx = base_ctx(
        session="US_CASH",
        dist_color_up_nearest_pct=1.0,
        dist_color_dn_nearest_pct=0.02,
        aggressor_imbalance=-0.3,
    )
    level_def = _level_def("SIDAK_COLOR_DN_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_DN_zone", level_def, ctx, "ES", dist_signed=0.01)
    assert trade is True
    assert params["swing_color_consensus"] == "CONFLUENCE_STRONG"
    # ES n'est PAS dans SWING_COLOR_BOOSTED pour SIDAK_COLOR_DN_zone -> no boost
    assert "swing_color_boost_applied" not in params


# ═══════════════════ Sanity dict ═══════════════════

def test_swing_color_boosted_count_11():
    """11 combos GOOD_EDGE valides empiriquement."""
    assert len(SWING_COLOR_BOOSTED) == 11


def test_swing_color_boosted_mostly_nq():
    """NQ domine : 10/11 combos NQ + 1 ES."""
    nq = sum(1 for k in SWING_COLOR_BOOSTED if k[0] == "NQ")
    es = sum(1 for k in SWING_COLOR_BOOSTED if k[0] == "ES")
    assert nq == 10
    assert es == 1


def test_swing_color_boosted_no_divergence():
    """Aucune entree DIVERGENCE (anti-Pattern 11 : pas de penalite cumulable)."""
    for (_, _, bucket) in SWING_COLOR_BOOSTED:
        assert bucket in ("CONFLUENCE_STRONG", "CONFLUENCE_OK")


def test_swing_color_proximity_pct_value():
    """Seuil 0.05% du prix = ~12t NQ a 25k."""
    assert SWING_COLOR_PROXIMITY_PCT == 0.05


def test_log_catalog_has_swing_color_boost_code():
    """BOT3_SWING_COLOR_BOOST defini dans log_catalog (R1 obligatoire)."""
    from CORE.log_catalog import LOG_CODES
    assert "BOT3_SWING_COLOR_BOOST" in LOG_CODES
    _, _, tpl = LOG_CODES["BOT3_SWING_COLOR_BOOST"]
    for k in ("{sym}", "{level}", "{bucket}", "{boost}"):
        assert k in tpl


# ═══════════════════ INTEGRATION TESTS — anti VALIDATION_MISS (code-reviewer 17/05) ═══════════════════

def test_integration_bar_to_ctx_to_decision_boost_applied():
    """End-to-end : bar v4 enriched -> analyze_context -> evaluate_decision -> boost emis.

    Anti pattern VALIDATION_MISS (code-reviewer 17/05) : verifier que les 3 features
    Phase 1.7d sont REELLEMENT populees par analyze_context() et que le boost se
    declenche dans le pipeline complet, pas seulement avec ctx injecte.
    """
    from CORE.bot3_context_analyzer import analyze_context

    # Bar simule v4 enriched avec confluence COLOR_UP_zone (LONG, imbalance >= 0)
    bar = {
        # OHLCV basic
        "close": 27500.0, "open": 27490.0, "high": 27510.0, "low": 27485.0,
        # DIM 1-12 minimal
        "open_type": 0, "day_type": 0,
        "poc_migration_dir": 0, "ctx_poc_migration_10": 0.0, "ctx_va_developing_10": 0.5,
        "is_in_asia": 0, "is_in_london": 0, "is_in_us_cash": 1, "is_in_us_after": 0,
        "session_segment": 1, "time_to_session_close_norm": 0.5,
        "delta_bar": 10.0, "delta_pct": 0.05, "finish_strength": 5.0,
        "rvol": 1.0, "delta_day_dir": 1, "cvd_day_dir": 1,
        "cvd_session": 0.0, "cvd_day": 0.0, "cvd_5d_rolling": 0.0,
        "vol_zscore_20": 0.5,
        "n_big_bid_t1": 0, "n_big_bid_t2": 0, "n_big_bid_t3": 0, "n_big_bid_t4": 0,
        "n_big_ask_t1": 0, "n_big_ask_t2": 0, "n_big_ask_t3": 0, "n_big_ask_t4": 0,
        "n_trapped_buy_cluster": 0, "n_trapped_sell_cluster": 0,
        "liq_sweep_high": 0, "liq_sweep_low": 0,
        "smt_divergence": 0, "cross_delta_agree": 0.0,
        "atr_14m_pct": 0.033, "atr_regime_zscore_60d": 0.0,
        "is_roll_day": 0,
        "within_news_715_5m": 0, "within_news_730_5m": 0,
        "within_news_830_5m": 0, "within_news_845_5m": 0,
        "within_news_900_5m": 0, "within_news_930_5m": 0,
        "mins_since_news": 999,
        "failed_auction": 0.0, "position_in_range": 0.5,
        # MQ proche (pour eviter mq_levels_stale=True)
        "dist_mq_call_pct": 0.5, "dist_mq_put_pct": -0.5,
        "dist_mq_hvl_pct": 0.3,
        # Phase 1.7d FEATURES (le coeur du test integration) :
        "dist_color_up_nearest_pct": 0.02,   # PROCHE (< 0.05% threshold)
        "dist_color_dn_nearest_pct": 1.0,    # loin
        "aggressor_imbalance": 0.3,           # > 0 -> CONFLUENCE_STRONG sur LONG
    }

    ctx = analyze_context(bar)

    # VERIFICATION : les 3 features Phase 1.7d sont bien populees dans ctx
    assert "dist_color_up_nearest_pct" in ctx, \
        "VALIDATION_MISS : analyze_context ne populate pas dist_color_up_nearest_pct"
    assert "dist_color_dn_nearest_pct" in ctx, \
        "VALIDATION_MISS : analyze_context ne populate pas dist_color_dn_nearest_pct"
    assert "aggressor_imbalance" in ctx, \
        "VALIDATION_MISS : analyze_context ne populate pas aggressor_imbalance"
    assert ctx["dist_color_up_nearest_pct"] == 0.02
    assert ctx["aggressor_imbalance"] == 0.3

    # VERIFICATION : decision avec ce ctx declenche le boost en bout de chaine
    level_def = _level_def("SIDAK_COLOR_UP_zone")
    trade, reason, params = evaluate_decision(
        "SIDAK_COLOR_UP_zone", level_def, ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert params["swing_color_consensus"] == "CONFLUENCE_STRONG"
    assert "swing_color_boost_applied" in params, \
        "INTEGRATION FAIL : boost cense se declencher mais swing_color_boost_applied absent"
    assert params["swing_color_boost_applied"]["boost"] == 15


def test_integration_default_999_no_false_positive():
    """Default 999.0 pour distances (pas 0.0) evite faux positif CONFLUENCE.

    Anti R2 code-reviewer 17/05 : si bar.get('dist_color_up_nearest_pct') is None
    et default 0.0 -> _close(0.0) = True (|0| < 0.05) -> faux CONFLUENCE_STRONG.
    Default 999.0 -> _close(999) = False -> NEUTRE correct.
    """
    from CORE.bot3_context_analyzer import analyze_context
    bar = {
        "is_in_us_cash": 1,
        # Toutes les features Phase 1.7d absentes (cas reel bar v4 sans colonnes)
    }
    ctx = analyze_context(bar)
    # Defaults appliques
    assert ctx["dist_color_up_nearest_pct"] == 999.0
    assert ctx["dist_color_dn_nearest_pct"] == 999.0
    assert ctx["aggressor_imbalance"] == 0.0
    # Et le consensus retourne NEUTRE (pas faux positif)
    assert _compute_swing_color_consensus("LONG", ctx) == "NEUTRE"
    assert _compute_swing_color_consensus("SHORT", ctx) == "NEUTRE"
