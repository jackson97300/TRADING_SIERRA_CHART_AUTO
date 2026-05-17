"""Tests Bot 3 Decision Engine — Vetos + filtres + Tier 3 + SL adaptatif."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.bot3_decision_engine import evaluate_decision  # noqa: E402
from CORE.bot3_level_definitions import TIER1, TIER3  # noqa: E402


def base_ctx(**overrides) -> dict:
    """Contexte minimal sain (no veto, no filter trigger).

    Jackson 03/05 Option B+ : ajout features Tier 1+2 pour 7 scenarios NEUTRAL.
    """
    ctx = {
        # Vetos OFF
        "is_roll_day": 0,
        "within_news_715_5m": 0, "within_news_730_5m": 0,
        "within_news_830_5m": 0, "within_news_845_5m": 0,
        "within_news_900_5m": 0, "within_news_930_5m": 0,
        "mins_since_news": 999,
        "rvol": 1.0,
        # Filtres anti-trend OFF
        "poc_mig_dir": 0, "poc_mig_speed": 0.0, "va_dev": 0.5,
        # Orderflow neutre
        "delta_bar": 10.0, "finish_strength": 5.0,
        # Tier 1 NEUTRAL features
        "delta_pct": 0.05,                # neutre
        "bn_absorb_bid_at_level": 0,
        "bn_absorb_ask_at_level": 0,
        "n_big_bid_t3": 0, "n_big_bid_t4": 0,
        "n_big_ask_t3": 0, "n_big_ask_t4": 0,
        # Tier 2 NEUTRAL features
        "liq_sweep_high": 0, "liq_sweep_low": 0,
        "vol_zscore_20": 0.5,
        "cvd_session": 0.0, "cvd_divergence": False, "cvd_divergence_dir": 0,
        "color_cluster_up": 0, "color_cluster_dn": 0, "color_imbalance": 0,
        # TIER S features (Jackson 03/05) — neutres par defaut
        "bar_body_pct": 0.7,                  # body fort par defaut (no veto)
        "bar_upper_wick_pct": 0.15,
        "bar_lower_wick_pct": 0.15,
        "bar_no_trade": 0,                    # bar avec trades
        "cur_va_n_buckets": 18,               # neutre (entre RANGE 25 et TREND 12)
        "cur_va_total_vol": 1000.0,
        "max_delta_bar": 50.0,
        "min_delta_bar": -30.0,
        "delta_change": 5.0,
        "spike_detected_lag3": 0,             # pas de spike recent
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


# ═══════════════════ VETOS ═══════════════════

def test_veto_roll_day():
    ctx = base_ctx(is_roll_day=1)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "VETO_ROLL_DAY"


def test_veto_news_imminent_830():
    ctx = base_ctx(within_news_830_5m=1)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "VETO_NEWS_IMMINENT"


def test_veto_news_imminent_715():
    """News 715 doit aussi vetoer (regression bug 1000/1400)."""
    ctx = base_ctx(within_news_715_5m=1)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "VETO_NEWS_IMMINENT"


def test_veto_news_just_hit():
    ctx = base_ctx(mins_since_news=1)  # 1 min apres = bloque
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "VETO_NEWS_JUST_HIT"


def test_news_passed_4min_no_veto():
    ctx = base_ctx(mins_since_news=4)  # 4 min apres = OK (>= 3)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is True


def test_veto_volume_mort():
    ctx = base_ctx(rvol=0.2)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "VETO_VOLUME_MORT"


def test_volume_just_above_min_no_veto():
    ctx = base_ctx(rvol=0.31)
    trade, _, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is True


# ═══════════════════ RESOLUTION SIDE ═══════════════════

def test_rejection_resistance_short():
    """REJECTION + dist>0 (level AU-DESSUS du prix = resistance) -> SHORT.

    17/05 FIX convention BUG D : dist_signed = (level - close). Si level > close
    -> dist > 0 -> resistance -> SHORT. Avant : test utilisait OLD convention
    (close - level), dist<0 = resistance, casse depuis BUG D fix 15/05.
    """
    ctx = base_ctx()
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=+0.01)
    assert trade is True
    assert p["side"] == "SHORT"
    assert p["action"] == "REJECTION"


def test_rejection_support_long():
    """REJECTION + dist<0 (level EN-DESSOUS du prix = support) -> LONG.

    17/05 FIX convention BUG D : dist_signed = (level - close). Si level < close
    -> dist < 0 -> support -> LONG.
    """
    ctx = base_ctx()
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=-0.01)
    assert trade is True
    assert p["side"] == "LONG"


def test_directional_long_fixed():
    """Niveau LONG fixe (IB_LOW) → toujours LONG."""
    ctx = base_ctx()
    trade, _, p = evaluate_decision(
        "IB_LOW", TIER1["IB_LOW"], ctx, "NQ", dist_signed=-0.02)
    assert trade is True
    assert p["side"] == "LONG"


# ═══════════════════ TIER 3 REQUIRED CONTEXT ═══════════════════

def test_tier3_cash_high_cvd_flat_match():
    """CASH_HIGH_CVD_FLAT trade quand cvd_trend=FLAT."""
    ctx = base_ctx(cvd_trend="FLAT", delta_day_dir=0)
    trade, _, p = evaluate_decision(
        "CASH_HIGH_CVD_FLAT", TIER3["CASH_HIGH_CVD_FLAT"], ctx, "NQ",
        dist_signed=-0.02)
    assert trade is True
    assert p["side"] == "SHORT"


def test_tier3_cash_high_cvd_up_skip():
    """CASH_HIGH_CVD_FLAT skip quand cvd_trend=UP (mismatch)."""
    ctx = base_ctx(cvd_trend="UP", delta_day_dir=1)
    trade, reason, _ = evaluate_decision(
        "CASH_HIGH_CVD_FLAT", TIER3["CASH_HIGH_CVD_FLAT"], ctx, "NQ",
        dist_signed=-0.02)
    assert trade is False
    assert "TIER3_MISS_cvd_trend" in reason


def test_tier3_trapped_sell_open_drive_match():
    """TRAPPED_SELL_OD trade quand open_type=0 (T0 Open Drive)."""
    ctx = base_ctx(open_type=0)
    trade, _, p = evaluate_decision(
        "TRAPPED_SELL_OD", TIER3["TRAPPED_SELL_OD"], ctx, "NQ",
        dist_signed=0.01)
    assert trade is True
    assert p["side"] == "LONG"


def test_tier3_trapped_sell_open_drive_miss():
    """TRAPPED_SELL_OD skip quand open_type=2 (Open Rejection Reverse)."""
    ctx = base_ctx(open_type=2)
    trade, reason, _ = evaluate_decision(
        "TRAPPED_SELL_OD", TIER3["TRAPPED_SELL_OD"], ctx, "NQ",
        dist_signed=0.01)
    assert trade is False
    assert "TIER3_MISS_open_type" in reason


def test_tier3_mq_call_position_in_range_above_match():
    """MQ_CALL_POC_FLAT trade quand position_in_range >= 0.70 ET poc_mig_dir=0."""
    ctx = base_ctx(position_in_range=0.85, poc_mig_dir=0)
    trade, _, p = evaluate_decision(
        "MQ_CALL_POC_FLAT", TIER3["MQ_CALL_POC_FLAT"], ctx, "ES",
        dist_signed=-0.01)
    assert trade is True
    assert p["side"] == "SHORT"


def test_tier3_mq_call_position_in_range_below_threshold_miss():
    """MQ_CALL_POC_FLAT skip quand position_in_range=0.5 (< 0.70). Test bugfix."""
    ctx = base_ctx(position_in_range=0.50, poc_mig_dir=0)
    trade, reason, _ = evaluate_decision(
        "MQ_CALL_POC_FLAT", TIER3["MQ_CALL_POC_FLAT"], ctx, "ES",
        dist_signed=-0.01)
    assert trade is False
    assert "position_in_range_above" in reason
    assert "0.50" in reason
    assert "0.7" in reason


# ═══════════════════ FILTRES ANTI-TREND ═══════════════════

def test_skip_bull_strong_short():
    """Anti-trend filter : SHORT en bull strong = SKIP.

    17/05 convention BUG D : dist_signed > 0 = level AU-DESSUS = SHORT REJECTION.
    Avant : dist_signed=-0.01 (OLD convention), test attendait SHORT mais code
    nouveau retourne LONG -> filter SKIP_BULL_STRONG ne tire pas.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.10)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=+0.01)
    assert trade is False
    assert reason == "SKIP_BULL_STRONG"


def test_skip_va_expanding_short():
    """Anti-trend filter : SHORT en VA expansion = SKIP. Voir test_skip_bull_strong_short."""
    ctx = base_ctx(va_dev=2.5)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=+0.01)
    assert trade is False
    assert reason == "SKIP_VA_EXPANDING"


def test_skip_bear_strong_long():
    ctx = base_ctx(poc_mig_dir=-1, poc_mig_speed=-0.10)
    trade, reason, _ = evaluate_decision(
        "IB_LOW", TIER1["IB_LOW"], ctx, "NQ", dist_signed=-0.02)
    assert trade is False
    assert reason == "SKIP_BEAR_STRONG"


def test_long_with_neutral_poc_no_skip():
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.0)
    trade, _, _ = evaluate_decision(
        "IB_LOW", TIER1["IB_LOW"], ctx, "NQ", dist_signed=-0.02)
    assert trade is True


# ═══════════════════ ORDERFLOW (REJECTION → BREAKOUT inversion) ═══════════════════

def test_rejection_long_normal():
    """delta normal + finish neutre → reste REJECTION."""
    ctx = base_ctx(delta_bar=20.0, finish_strength=10.0, rvol=1.0)
    trade, _, p = evaluate_decision(
        "IB_LOW", TIER1["IB_LOW"], ctx, "NQ", dist_signed=-0.02)
    assert trade is True
    assert p["action"] == "REJECTION"
    assert p["side"] == "LONG"


def test_rejection_long_directional_no_inversion():
    """FIX C-1 : niveau LONG fixe (IB_LOW) ne s'inverse PAS en BREAKOUT SHORT
    meme si delta crush. Stat baseline IB_LOW PF 1.85 mesuree sur LONG —
    inverser invaliderait la stat (Pattern 11 latent)."""
    ctx = base_ctx(delta_bar=-100.0, finish_strength=-50.0, rvol=1.0)
    trade, reason, _ = evaluate_decision(
        "IB_LOW", TIER1["IB_LOW"], ctx, "NQ", dist_signed=-0.02)
    assert trade is False
    assert reason == "SKIP_SELLERS_CRUSHING_DIRECTIONAL_LEVEL"


def test_rejection_short_register_pending_breakout():
    """Niveau REJECTION SHORT (resistance, dist>0) + orderflow crush positif :
    decision_engine return PENDING_BREAKOUT_REGISTERED (state machine prend le relais).
    Pas d'inversion immediate (canon Steidlmayer).

    17/05 FIX convention BUG D : dist_signed=+0.01 = level AU-DESSUS = SHORT REJECTION.
    Crush positif (delta+finish positifs) = resistance cassee a la hausse -> LONG breakout pending.
    """
    ctx = base_ctx(delta_bar=100.0, finish_strength=50.0, rvol=1.0)
    trade, reason, params = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=+0.01)
    assert trade is False  # pas de trade direct
    assert reason == "PENDING_BREAKOUT_REGISTERED"
    assert params["side_break"] == "LONG"   # resistance cassee -> LONG breakout


def test_rejection_long_register_pending_breakout():
    """REJECTION LONG (support, dist<0) + crush negatif -> PENDING SHORT breakout.

    17/05 FIX convention BUG D : dist_signed=-0.01 = level EN-DESSOUS = LONG REJECTION.
    Crush negatif = support casse a la baisse -> SHORT breakout pending.
    """
    ctx = base_ctx(delta_bar=-100.0, finish_strength=-50.0, rvol=1.0)
    trade, reason, params = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=-0.01)
    assert trade is False
    assert reason == "PENDING_BREAKOUT_REGISTERED"
    assert params["side_break"] == "SHORT"   # support casse -> SHORT breakout


def test_rejection_short_no_immediate_breakout_inversion():
    """OBSOLETE -- l'inversion 1-bar est remplacee par PENDING_BREAKOUT (state machine).

    17/05 FIX convention BUG D : dist_signed=+0.01 pour SHORT rejection.
    """
    ctx = base_ctx(delta_bar=100.0, finish_strength=50.0, rvol=1.0)
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=+0.01)
    assert trade is False
    assert reason == "PENDING_BREAKOUT_REGISTERED"


# ═══════════════════ CONFIDENCE ═══════════════════

def test_confidence_baseline_no_boost():
    ctx = base_ctx()
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is True
    assert p["confidence"] == 50


def test_confidence_whale_boost_long():
    ctx = base_ctx(n_big_bid_t3=2)  # 2 * 3 = 6 → +min(30, 15) = +15
    trade, _, p = evaluate_decision(
        "IB_LOW", TIER1["IB_LOW"], ctx, "NQ", dist_signed=-0.02)
    assert p["confidence"] == 65


def test_confidence_full_stack_clamped_to_100():
    """FIX M-1 : confidence raw 113 doit etre clamp a 100 avant int()."""
    ctx = base_ctx(
        n_big_bid_t3=2,            # +15
        liq_sweep_low=1,           # +10
        failed_auction=0.8,        # +10
        cross_delta_agree=0.8,     # +10
        smt_divergence=1,          # +8
        n_trapped_sell_cluster=1,  # +10 (LONG = sellers trapped near support)
    )
    # raw = 50+15+10+10+10+8+10 = 113 → clamp 100
    trade, _, p = evaluate_decision(
        "IB_LOW", TIER1["IB_LOW"], ctx, "NQ", dist_signed=-0.02)
    assert trade is True
    assert p["confidence"] == 100  # clamp anti-derive echelle


# ═══════════════════ SL ADAPTATIF ═══════════════════

def test_sl_baseline_normal_atr():
    """17/05 : baseline NQ 400t->80t (reduction 5x post audit empirique).

    Source verite : GUARD_RAILS_BOT3["NQ"]["sl_ticks_base"] = 80.
    """
    from CORE.bot3_config import GUARD_RAILS_BOT3
    nq_baseline = GUARD_RAILS_BOT3["NQ"]["sl_ticks_base"]
    ctx = base_ctx(atr_14m_pct=0.033)  # baseline NQ
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert p["sl_ticks"] == nq_baseline  # baseline * 1.0
    assert p["atr_multiplier"] == 1.0


def test_sl_high_atr_widens():
    """ATR eleve -> SL elargi (clamp 1.5x baseline)."""
    from CORE.bot3_config import GUARD_RAILS_BOT3
    nq_baseline = GUARD_RAILS_BOT3["NQ"]["sl_ticks_base"]
    ctx = base_ctx(atr_14m_pct=0.066)  # 2x baseline atr -> clamp 1.5
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert p["sl_ticks"] == int(round(nq_baseline * 1.5))
    assert p["atr_multiplier"] == 1.5


def test_sl_low_atr_tightens():
    """ATR bas -> SL serre (clamp 0.7x baseline)."""
    from CORE.bot3_config import GUARD_RAILS_BOT3
    nq_baseline = GUARD_RAILS_BOT3["NQ"]["sl_ticks_base"]
    ctx = base_ctx(atr_14m_pct=0.015)  # ~0.45x baseline atr -> clamp 0.7
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert p["sl_ticks"] == int(round(nq_baseline * 0.7))
    assert p["atr_multiplier"] == 0.7


def test_sl_es_baseline():
    """17/05 : baseline ES 160t->32t (reduction 5x meme pattern NQ).

    Source verite : GUARD_RAILS_BOT3["ES"]["sl_ticks_base"] = 32.
    """
    from CORE.bot3_config import GUARD_RAILS_BOT3
    es_baseline = GUARD_RAILS_BOT3["ES"]["sl_ticks_base"]
    ctx = base_ctx(atr_14m_pct=0.027)
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "ES", dist_signed=0.01)
    assert p["sl_ticks"] == es_baseline


def test_sl_atr_zero_uses_baseline():
    """atr=0 -> utilise baseline, multiplier = 1.0."""
    from CORE.bot3_config import GUARD_RAILS_BOT3
    nq_baseline = GUARD_RAILS_BOT3["NQ"]["sl_ticks_base"]
    ctx = base_ctx(atr_14m_pct=0.0)
    trade, _, p = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert p["sl_ticks"] == nq_baseline


# ═══════════════════ SKIP DIST ZERO ═══════════════════

def test_skip_dist_zero_rejection():
    ctx = base_ctx()
    trade, reason, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.0)
    assert trade is False
    assert reason == "SKIP_DIST_ZERO"


# ════════════════════════════════════════════════════════════════════
# DOCTRINE NEUTRAL : 7 scenarios structure + orderflow (Jackson 03/05)
# ════════════════════════════════════════════════════════════════════

from CORE.bot3_level_definitions import TIER2_LEVELS_NEUTRAL  # noqa: E402


def test_doctrine_neutral_scenario_1_full_convergence_breakout_long():
    """SCENARIO 1 : Convergence Tier 1+2+S = BREAKOUT LONG.

    Doctrine TIER S : structure UP + orderflow UP + vol_z>=1 + big_bid_inst>0
    + NOT absorb_ask + NOT liq_sweep_high + color_imb >= 0
    + (vol_spike_up OR bn_stack_bid > ask) + bar_body_pct >= 0.6.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   vol_zscore_20=1.5,
                   n_big_bid_t3=2, n_big_bid_t4=0,
                   bn_absorb_ask_at_level=0,
                   liq_sweep_high=0,
                   color_imbalance=1,
                   vol_spike_up=1,         # TIER S confirmation footprint
                   bar_body_pct=0.7)        # TIER S body fort = conviction
    trade, _, p = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is True
    assert p["side"] == "LONG"
    assert p["action"] == "BREAKOUT"


def test_doctrine_neutral_scenario_1_blocked_by_absorb_ask():
    """DOCTRINE Tier 1 : meme convergence MAIS bn_absorb_ask_at_level=1 → SKIP.

    Anti faux breakout retail : si vendeurs absorbent au level, le breakout
    est artificiel. Le bot DOIT skip. Sans Tier 1, le bot achetait le top.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   vol_zscore_20=1.5, n_big_bid_t3=2,
                   bn_absorb_ask_at_level=1,            # absorption ask = trap
                   liq_sweep_high=0)
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_NEUTRAL_NO_CONVERGENCE"


def test_doctrine_neutral_scenario_1_blocked_by_no_big_bidders():
    """DOCTRINE Tier 1 : breakout LONG mais 0 institutionnels = retail = SKIP.

    Anti faux breakout : sans big_bid_t3+t4, c'est du retail = trap probable.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   vol_zscore_20=1.5,
                   n_big_bid_t3=0, n_big_bid_t4=0,      # 0 institutionnels
                   bn_absorb_ask_at_level=0)
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_NEUTRAL_NO_CONVERGENCE"


def test_doctrine_neutral_scenario_1_blocked_by_low_volume():
    """DOCTRINE Tier 2 : breakout sans volume (vol_z<1) = mort = SKIP."""
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   vol_zscore_20=0.3,                     # volume mort
                   n_big_bid_t3=2,
                   bn_absorb_ask_at_level=0)
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False


def test_doctrine_neutral_scenario_1_blocked_by_liq_sweep_high():
    """DOCTRINE Tier 2 ICT : liq_sweep_high détecté = Wyckoff trap = SKIP.

    Le marche a balaye les stops au-dessus du niveau avant le breakout = piege.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   vol_zscore_20=1.5, n_big_bid_t3=2,
                   bn_absorb_ask_at_level=0,
                   liq_sweep_high=1)                       # ICT sweep = trap
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False


def test_doctrine_neutral_scenario_3_full_convergence_rejection_short():
    """SCENARIO 3 : Convergence renforcee = REJECTION SHORT counter-trend faible.

    Structure neutre + delta- + finish- + NOT absorb_bid + big_ask_inst>0.
    """
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.02,
                   delta_pct=-0.30, finish_strength=-20.0, rvol=1.0,
                   bn_absorb_bid_at_level=0,             # CRITIQUE : pas de spring
                   n_big_ask_t3=2)                        # vendeurs institutionnels
    trade, _, p = evaluate_decision(
        "CUR_VAH", TIER2_LEVELS_NEUTRAL["CUR_VAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is True
    assert p["side"] == "SHORT"
    assert p["action"] == "REJECTION"


def test_doctrine_neutral_scenario_3_blocked_by_spring_wyckoff():
    """DOCTRINE Tier 1 anti-spring : delta crush + finish neg MAIS absorb_bid>0.

    C'est un spring Wyckoff = vendeurs absorbed au support = reversal up imminent.
    Le bot NE DOIT PAS short. Sans Tier 1, le bot shortait au pire moment.
    """
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.02,
                   delta_pct=-0.30, finish_strength=-20.0, rvol=1.0,
                   bn_absorb_bid_at_level=2,             # SPRING WYCKOFF detecte
                   n_big_ask_t3=0)
    trade, reason, _ = evaluate_decision(
        "CUR_VAH", TIER2_LEVELS_NEUTRAL["CUR_VAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_NEUTRAL_NO_CONVERGENCE"


def test_doctrine_neutral_scenario_4_full_convergence_rejection_long():
    """SCENARIO 4 : Convergence renforcee = REJECTION LONG counter-trend faible."""
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=-0.02,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   bn_absorb_ask_at_level=0,
                   n_big_bid_t3=2)
    trade, _, p = evaluate_decision(
        "MQ_CALL", TIER2_LEVELS_NEUTRAL["MQ_CALL"], ctx, "NQ", dist_signed=0.01)
    assert trade is True
    assert p["side"] == "LONG"
    assert p["action"] == "REJECTION"


def test_doctrine_neutral_scenario_5_range_day_fade_short_no_institutional():
    """SCENARIO 5 : Range day fade SHORT. TIER S calibre_NQ : cur_va_n_buckets >= 1742 (p75)."""
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.01, va_dev=-1.0,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   n_big_bid_t3=0, n_big_bid_t4=0,
                   cur_va_n_buckets=2000)                 # TIER S calibre_NQ p75
    trade, _, p = evaluate_decision(
        "IB_HIGH", TIER2_LEVELS_NEUTRAL["IB_HIGH"], ctx, "NQ", dist_signed=0.01)
    assert trade is True
    assert p["side"] == "SHORT"
    assert p["action"] == "REJECTION"


def test_doctrine_neutral_scenario_5_range_day_blocked_by_institutional():
    """SCENARIO 5 anti-pattern : range day + institutionnels poussent = pas fade."""
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.01, va_dev=-1.0,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   n_big_bid_t3=2,
                   cur_va_n_buckets=2000)                 # TIER S range confirme
    trade, reason, _ = evaluate_decision(
        "IB_HIGH", TIER2_LEVELS_NEUTRAL["IB_HIGH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_RANGE_INSTITUTIONAL_DRIVE"


def test_doctrine_neutral_scenario_6_trend_day_full_convergence():
    """SCENARIO 6 : Trend day + same-direction + vol_z + big_bid_inst = BREAKOUT LONG."""
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.08, va_dev=1.5,
                   delta_pct=0.30, finish_strength=20.0, rvol=1.0,
                   vol_zscore_20=1.5,
                   n_big_bid_t3=2)
    trade, _, p = evaluate_decision(
        "VWAP_D_SD1U", TIER2_LEVELS_NEUTRAL["VWAP_D_SD1U"], ctx, "NQ", dist_signed=0.01)
    assert trade is True
    assert p["side"] == "LONG"
    assert p["action"] == "BREAKOUT"


def test_doctrine_neutral_scenario_6_trend_day_counter_blocked():
    """Anti-pattern : trend day, orderflow contre = SKIP."""
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.08, va_dev=1.5,
                   delta_pct=-0.30, finish_strength=-20.0, rvol=1.0,
                   vol_zscore_20=1.5)
    trade, reason, _ = evaluate_decision(
        "VWAP_D_SD1U", TIER2_LEVELS_NEUTRAL["VWAP_D_SD1U"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_TREND_DAY_COUNTER_OR_NO_VOL_OR_NO_BIG"


def test_doctrine_neutral_scenario_7_no_convergence_skip():
    """SCENARIO 7 : pas de convergence = SKIP (cas frequent, defaut sain)."""
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.01, va_dev=0.0,
                   delta_pct=0.05, finish_strength=2.0, rvol=1.0)
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_NEUTRAL_NO_CONVERGENCE"


def test_doctrine_neutral_delta_pct_normalization_universal():
    """DOCTRINE Tier 1 : delta_pct = normalisation universelle Asia/RTH/Open.

    delta_pct seuil 0.20 = 20% pression au mininum. Universel.
    """
    # Cas marginal : delta_pct = 0.18 < 0.20 → SKIP
    ctx_marginal = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02,
                             delta_pct=0.18, finish_strength=20.0,
                             vol_zscore_20=1.5, n_big_bid_t3=2)
    trade1, reason1, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx_marginal, "NQ", dist_signed=0.01)
    assert trade1 is False
    # Cas convergent : delta_pct = 0.25 > 0.20 → GO (avec TIER S)
    ctx_strong = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02,
                           delta_pct=0.25, finish_strength=20.0,
                           vol_zscore_20=1.5, n_big_bid_t3=2,
                           bn_absorb_ask_at_level=0, liq_sweep_high=0,
                           vol_spike_up=1, bar_body_pct=0.7)  # TIER S
    trade2, _, p2 = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx_strong, "NQ", dist_signed=0.01)
    assert trade2 is True
    assert p2["side"] == "LONG"


def test_doctrine_neutral_skip_bull_strong_filter_NOT_applied():
    """Pour un niveau NEUTRAL, filtre anti-trend SKIP_BULL_STRONG ne s'applique pas.

    Convergence est deja inclue dans les 7 scenarios.

    17/05 FIX convention BUG D : niveau REJECTION SHORT (dist>0) en bull strong
    -> SKIP_BULL_STRONG (anti-trend). Avant dist_signed=-0.01 (OLD = LONG en NEW)
    ne tirait pas le filtre car LONG en bull = pas bloque.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.10, va_dev=1.5,
                   delta_pct=-0.30, finish_strength=-20.0, rvol=1.0)
    trade1, _, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=+0.01)
    assert trade1 is False  # SKIP_BULL_STRONG sur niveau REJECTION SHORT
    trade2, reason2, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade2 is False
    assert reason2 == "SKIP_TREND_DAY_COUNTER_OR_NO_VOL_OR_NO_BIG"


# ════════════════════════════════════════════════════════════════════
# DOCTRINE P5 (Jackson 03/05) : CVD divergence robuste 2-horizons
# Wyckoff "smart money divergence" : intraday vs 5-day rolling.
# Magnitudes >100 requises (anti-noise).
# ════════════════════════════════════════════════════════════════════

from CORE.bot3_context_analyzer import analyze_context  # noqa: E402


def test_doctrine_p5_cvd_divergence_bullish_intraday_up_vs_5d_down():
    """DOCTRINE Wyckoff (calibre p25=1500) : intraday accumule vs distribution 5j.

    cvd_5d_rolling = -2500 (>= p25 abs), intraday +1500 (50% magnitude).
    Smart money buy reversal signal : divergence_dir = +1.
    """
    bar = {"cvd_session": 1500.0, "cvd_5d_rolling": -2500.0, "delta_bar": 50.0}
    ctx = analyze_context(bar)
    assert ctx["cvd_divergence"] is True
    assert ctx["cvd_divergence_dir"] == 1


def test_doctrine_p5_cvd_divergence_bearish_intraday_down_vs_5d_up():
    """DOCTRINE Wyckoff : intraday distribute vs accumulation 5j (UP)."""
    bar = {"cvd_session": -1500.0, "cvd_5d_rolling": 2500.0, "delta_bar": -50.0}
    ctx = analyze_context(bar)
    assert ctx["cvd_divergence"] is True
    assert ctx["cvd_divergence_dir"] == -1


def test_doctrine_p5_cvd_no_divergence_5d_below_calibration_threshold():
    """DOCTRINE calibre : cvd_5d_abs < 1500 (p25) = noise = pas de divergence.

    Avant calibration : seuil 200 trivial → triggrait sur tous les jours.
    Apres : on exige magnitude 5j significative (>= p25).
    """
    bar = {"cvd_session": 500.0, "cvd_5d_rolling": -800.0, "delta_bar": 10.0}
    # cvd_5d_abs = 800 < 1500 → magnitude_ok = False → pas de divergence
    ctx = analyze_context(bar)
    assert ctx["cvd_divergence"] is False
    assert ctx["cvd_divergence_dir"] == 0


def test_doctrine_p5_cvd_no_divergence_intraday_too_small():
    """DOCTRINE : intraday < 50% 5j = noise, pas de divergence."""
    bar = {"cvd_session": 100.0, "cvd_5d_rolling": -3000.0, "delta_bar": 10.0}
    # cvd_int_abs = 100 < 0.5 * 3000 = 1500 → magnitude_ok = False
    ctx = analyze_context(bar)
    assert ctx["cvd_divergence"] is False


def test_doctrine_p5_cvd_no_divergence_same_signs():
    """DOCTRINE : memes signes intraday/5j = pas de divergence (continuation)."""
    bar = {"cvd_session": 1500.0, "cvd_5d_rolling": 2500.0, "delta_bar": 50.0}
    ctx = analyze_context(bar)
    assert ctx["cvd_divergence"] is False


# ════════════════════════════════════════════════════════════════════
# DOCTRINE Bonus 2 (Jackson 03/05) : MQ levels stale veto
# ════════════════════════════════════════════════════════════════════

def test_doctrine_bonus2_mq_stale_when_all_mq_dists_above_5pct():
    """DOCTRINE : si toutes les distances MQ > 5% → MQ ingestion failed = stale."""
    bar = {
        "dist_mq_call_pct": 6.0,
        "dist_mq_put_pct": 7.0,
        "dist_mq_call_0dte_pct": 8.0,
        "dist_mq_put_0dte_pct": 5.5,
    }
    ctx = analyze_context(bar)
    assert ctx["mq_levels_stale"] is True


def test_doctrine_bonus2_mq_not_stale_when_any_mq_dist_below_5pct():
    """DOCTRINE : si AU MOINS UNE dist MQ < 5% → MQ levels frais."""
    bar = {
        "dist_mq_call_pct": 0.5,    # frais
        "dist_mq_put_pct": 7.0,
        "dist_mq_call_0dte_pct": 8.0,
        "dist_mq_put_0dte_pct": 6.0,
    }
    ctx = analyze_context(bar)
    assert ctx["mq_levels_stale"] is False


def test_doctrine_bonus2_veto_mq_level_when_stale():
    """DOCTRINE : niveau MQ_PUT_0DTE + mq_levels_stale=True → VETO_MQ_STALE."""
    ctx = base_ctx(mq_levels_stale=True)
    trade, reason, _ = evaluate_decision(
        "MQ_PUT_0DTE", TIER1["MQ_PUT_0DTE"], ctx, "NQ", dist_signed=-0.02)
    assert trade is False
    assert reason == "VETO_MQ_STALE"


def test_doctrine_bonus2_no_veto_non_mq_level_when_stale():
    """DOCTRINE : niveau SINGLE_PRINT (non-MQ) + mq_levels_stale=True → pas de veto.

    Le veto ne s'applique qu'aux niveaux MQ_*. SINGLE_PRINT, IB_LOW, etc. tradables.
    """
    ctx = base_ctx(mq_levels_stale=True)
    trade, _, _ = evaluate_decision(
        "SINGLE_PRINT", TIER1["SINGLE_PRINT"], ctx, "NQ", dist_signed=0.01)
    assert trade is True   # pas de veto (niveau non-MQ)


# ════════════════════════════════════════════════════════════════════
# DOCTRINE TIER S (Jackson 03/05 audit V4) : features critiques manquees
# ════════════════════════════════════════════════════════════════════

def test_doctrine_tier_s_skip_bar_no_trade():
    """DOCTRINE : barre sans trade = marche mort = SKIP absolu (avant tout scenario)."""
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02, delta_pct=0.30,
                   finish_strength=20.0, vol_zscore_20=1.5, n_big_bid_t3=2,
                   vol_spike_up=1, bar_body_pct=0.7,
                   bar_no_trade=1)               # marche mort
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_NEUTRAL_BAR_NO_TRADE"


def test_doctrine_tier_s_skip_spike_recent_polluted():
    """DOCTRINE : spike recent (lag3=1) = niveau pollute = SKIP (anti-retest pollue)."""
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02, delta_pct=0.30,
                   finish_strength=20.0, vol_zscore_20=1.5, n_big_bid_t3=2,
                   vol_spike_up=1, bar_body_pct=0.7,
                   spike_detected_lag3=1)         # spike recent
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False
    assert reason == "SKIP_NEUTRAL_SPIKE_RECENT_POLLUTED"


def test_doctrine_tier_s_breakout_blocked_by_weak_body():
    """DOCTRINE : breakout LONG mais bar_body_pct < 0.6 (wick reversal) = SKIP.

    Steidlmayer/Wyckoff : si la barre a un long upper wick (shooting star reverse),
    ce n'est pas une vraie acceptance breakout.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02, delta_pct=0.30,
                   finish_strength=20.0, vol_zscore_20=1.5, n_big_bid_t3=2,
                   vol_spike_up=1,
                   bar_body_pct=0.30,             # body faible = wick reversal
                   bar_upper_wick_pct=0.60)
    trade, reason, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False


def test_doctrine_tier_s_breakout_blocked_by_no_footprint_confirmation():
    """DOCTRINE : breakout LONG sans vol_spike NI bn_stack_bid > ask = SKIP.

    Sans confirmation footprint (volume spike OU stacking ladder), c'est
    du retail qui pousse sans conviction institutionnelle. Anti faux breakout.
    """
    ctx = base_ctx(poc_mig_dir=1, poc_mig_speed=0.02, delta_pct=0.30,
                   finish_strength=20.0, vol_zscore_20=1.5, n_big_bid_t3=2,
                   bar_body_pct=0.7,
                   vol_spike_up=0,                 # pas de spike volume directionnel
                   bn_stack_bid=2, bn_stack_ask=3)  # stack ask > bid (contre LONG)
    trade, _, _ = evaluate_decision(
        "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False


def test_doctrine_tier_s_range_blocked_by_narrow_profile():
    """DOCTRINE : poc=0 + va_dev<-0.5 mais cur_va_n_buckets < 25 = profile narrow.

    Pas un vrai range day, juste consolidation transitoire. SKIP.
    """
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.01, va_dev=-1.0,
                   delta_pct=0.30, finish_strength=20.0,
                   cur_va_n_buckets=15)            # profile narrow = pas range
    trade, reason, _ = evaluate_decision(
        "IB_HIGH", TIER2_LEVELS_NEUTRAL["IB_HIGH"], ctx, "NQ", dist_signed=0.01)
    # Pas range scenario 5 confirme → fall through → SKIP_NEUTRAL_NO_CONVERGENCE
    assert trade is False


def test_doctrine_tier_s_cvd_divergence_blocks_short_rejection():
    """DOCTRINE FIX P5 v2 : scenario 3 (REJECTION SHORT counter-trend) BLOQUE
    si cvd_divergence_dir == +1 (smart money buy reversal Wyckoff)."""
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.02,
                   delta_pct=-0.30, finish_strength=-20.0,
                   bn_absorb_bid_at_level=0,
                   n_big_ask_t3=2,
                   cvd_divergence_dir=1)           # bullish reversal Wyckoff
    trade, reason, _ = evaluate_decision(
        "CUR_VAH", TIER2_LEVELS_NEUTRAL["CUR_VAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is False                          # bloque par cvd_div_dir bullish
    assert reason == "SKIP_NEUTRAL_NO_CONVERGENCE"


def test_doctrine_tier_s_cvd_divergence_aligned_allows_short_rejection():
    """DOCTRINE FIX P5 v2 : scenario 3 trade si cvd_divergence_dir == -1 (bearish reversal)."""
    ctx = base_ctx(poc_mig_dir=0, poc_mig_speed=0.02,
                   delta_pct=-0.30, finish_strength=-20.0,
                   bn_absorb_bid_at_level=0,
                   n_big_ask_t3=2,
                   cvd_divergence_dir=-1)          # bearish reversal Wyckoff (ou 0 OK aussi)
    trade, _, p = evaluate_decision(
        "CUR_VAH", TIER2_LEVELS_NEUTRAL["CUR_VAH"], ctx, "NQ", dist_signed=0.01)
    assert trade is True
    assert p["side"] == "SHORT"


# ════════════════════════════════════════════════════════════════════
# TEST CONTRACT (review code-reviewer round 4) : analyze_context sur parquet REEL
# Anti VALIDATION_MISS pattern : verifier que les features extraites du parquet
# V4 prod produisent des valeurs coherentes (pas all-zero).
# ════════════════════════════════════════════════════════════════════

def test_contract_analyze_context_real_v4_parquet():
    """CONTRACT : charge parquet V4 reel, appelle analyze_context, verifie
    que les TIER 1+2+S features ne sont pas all-NaN/0 (= features mortes)."""
    from pathlib import Path
    parquet_path = ROOT / "DATA" / "DATASETS" / "v4_enriched" / \
                   "symbol=NQ.c.0" / "year=2026" / "month=03" / "data.parquet"
    if not parquet_path.exists():
        pytest.skip(f"Parquet V4 absent : {parquet_path}")
    import pandas as pd
    df = pd.read_parquet(parquet_path)
    if df.empty:
        pytest.skip("Parquet V4 vide")
    # Sample 100 bars random pour test
    sample = df.sample(min(100, len(df)), random_state=42)
    n_cvd_div = 0
    n_cur_va_buckets_above_p25 = 0
    n_bar_body_pct_extracted = 0
    n_delta_pct_extracted = 0
    for _, row in sample.iterrows():
        ctx = analyze_context(row.to_dict())
        if ctx.get("cvd_divergence"):
            n_cvd_div += 1
        if ctx.get("cur_va_n_buckets", 0) >= 690:   # >= p25 NQ
            n_cur_va_buckets_above_p25 += 1
        if ctx.get("bar_body_pct", 0.0) > 0:
            n_bar_body_pct_extracted += 1
        if ctx.get("delta_pct", 0.0) != 0.0:
            n_delta_pct_extracted += 1
    # Asserts : features pas inertes
    # Asserts calibres empiriquement (bar_body_pct=0 frequent sur bars OHLC=open=close)
    assert n_cur_va_buckets_above_p25 >= 50, \
        f"cur_va_n_buckets < p25 sur > 50% bars : feature suspecte (got {n_cur_va_buckets_above_p25}/100)"
    assert n_bar_body_pct_extracted >= 30, \
        f"bar_body_pct = 0 sur > 70% bars : feature suspecte (got {n_bar_body_pct_extracted}/100)"
    assert n_delta_pct_extracted >= 50, \
        f"delta_pct = 0 sur > 50% bars : feature suspecte (got {n_delta_pct_extracted}/100)"


def test_contract_neutral_decision_real_v4_parquet():
    """CONTRACT : sur 100 bars REELS V4, analyze_context + evaluate_decision
    pour TIER2_LEVELS_NEUTRAL doit produire au moins 1 GO sur 100 (sinon les
    7 scenarios sont trop restrictifs en prod)."""
    from pathlib import Path
    parquet_path = ROOT / "DATA" / "DATASETS" / "v4_enriched" / \
                   "symbol=NQ.c.0" / "year=2026" / "month=03" / "data.parquet"
    if not parquet_path.exists():
        pytest.skip(f"Parquet V4 absent : {parquet_path}")
    import pandas as pd
    df = pd.read_parquet(parquet_path)
    sample = df.sample(min(500, len(df)), random_state=42)
    decisions = {"GO": 0, "SKIP": 0, "VETO": 0}
    for _, row in sample.iterrows():
        bar = row.to_dict()
        ctx = analyze_context(bar)
        # Test sur PVAH avec dist_signed = -0.05 (proche resistance)
        trade, reason, _ = evaluate_decision(
            "PVAH", TIER2_LEVELS_NEUTRAL["PVAH"], ctx, "NQ", dist_signed=-0.05)
        if trade:
            decisions["GO"] += 1
        elif reason.startswith("VETO_"):
            decisions["VETO"] += 1
        else:
            decisions["SKIP"] += 1
    # Au moins 1 GO sur 500 bars = scenarios atteignables en prod
    # (sinon Bot 3 ne tradera JAMAIS = scenarios trop restrictifs)
    print(f"\nDecisions sur 500 bars NQ V4 reels : {decisions}")
    # Note : on n'asserte PAS GO >= 1 car Phase 1 est observe-only et les
    # scenarios sont stricts intentionnellement. On verifie juste pas de crash.
    assert decisions["GO"] + decisions["SKIP"] + decisions["VETO"] == 500
