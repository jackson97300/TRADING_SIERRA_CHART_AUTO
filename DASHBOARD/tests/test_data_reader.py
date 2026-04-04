"""Tests unitaires data_reader MIA Dashboard."""
import pytest

from DASHBOARD.api.data_reader import (
    get_field,
    get_int_field,
    get_str_field,
    build_bot_status_basic,
    build_instrument_status,
    build_market_context_basic,
    build_market_context_full,
    build_order_flow,
    build_options_gamma,
    build_intermarket,
    build_signals_journal,
    OPEN_TYPE_LABELS,
    DAY_TYPE_LABELS,
    PROFILE_SHAPE_LABELS,
    RVOL_REGIME_LABELS,
    AMD_PHASE_LABELS,
)


# --- get_field ---


def test_get_field_normal():
    assert get_field({"x": 42.0}, "x") == 42.0


def test_get_field_missing():
    assert get_field({}, "x", 99.0) == 99.0


def test_get_field_invalid():
    assert get_field({"x": "INVALID"}, "x", 0.0) == 0.0


def test_get_field_none():
    assert get_field({"x": None}, "x", 5.0) == 5.0


def test_get_field_string_number():
    assert get_field({"x": "3.14"}, "x") == 3.14


def test_get_field_non_numeric_string():
    assert get_field({"x": "abc"}, "x", -1.0) == -1.0


# --- get_int_field ---


def test_get_int_field_normal():
    assert get_int_field({"y": 7}, "y") == 7


def test_get_int_field_float():
    assert get_int_field({"y": 3.9}, "y") == 3


def test_get_int_field_invalid():
    assert get_int_field({"y": "INVALID"}, "y", -1) == -1


def test_get_int_field_none():
    assert get_int_field({"y": None}, "y", 0) == 0


# --- get_str_field ---


def test_get_str_field_normal():
    assert get_str_field({"s": "hello"}, "s") == "hello"


def test_get_str_field_missing():
    assert get_str_field({}, "s", "default") == "default"


def test_get_str_field_invalid():
    assert get_str_field({"s": "INVALID"}, "s", "N/A") == "N/A"


def test_get_str_field_none():
    assert get_str_field({"s": None}, "s", "fallback") == "fallback"


# --- Labels ---


def test_labels_open_type():
    assert len(OPEN_TYPE_LABELS) == 12
    assert OPEN_TYPE_LABELS[0] == "UNKNOWN"
    assert OPEN_TYPE_LABELS[1] == "OD UP"


def test_labels_day_type():
    assert len(DAY_TYPE_LABELS) == 5
    assert DAY_TYPE_LABELS[4] == "TREND"


def test_labels_profile_shape():
    assert len(PROFILE_SHAPE_LABELS) == 4
    assert PROFILE_SHAPE_LABELS[0] == "D-Shape"


def test_labels_rvol_regime():
    assert len(RVOL_REGIME_LABELS) == 5
    assert RVOL_REGIME_LABELS[4] == "Extreme"


def test_labels_amd_phase():
    assert len(AMD_PHASE_LABELS) == 3
    assert AMD_PHASE_LABELS[0] == "Asia"
    assert AMD_PHASE_LABELS[2] == "US"


# --- build_bot_status_basic ---


def test_build_bot_status_basic():
    bot_data = {
        "bot_status": {
            "running": True,
            "global_status": "ACTIVE",
            "last_heartbeat": "2026-04-04T10:00:00Z",
        }
    }
    result = build_bot_status_basic(bot_data)
    assert result["running"] is True
    assert result["global_status"] == "ACTIVE"
    assert result["last_heartbeat"] == "2026-04-04T10:00:00Z"


def test_build_bot_status_basic_empty():
    result = build_bot_status_basic({})
    assert result["running"] is False
    assert result["global_status"] == "UNKNOWN"


# --- build_instrument_status ---


def test_build_instrument_status():
    bot_data = {
        "es": {
            "enabled": True,
            "in_position": False,
            "status": "IDLE",
            "trades_today": 2,
            "wins": 1,
            "losses": 1,
            "pnl_today": 25.0,
            "consecutive_losses": 0,
            "last_rejected": "",
            "signals_rejected": 3,
        }
    }
    result = build_instrument_status(bot_data, "ES")
    assert result is not None
    assert result["enabled"] is True
    assert result["trades_today"] == 2
    assert result["pnl_today"] == 25.0


def test_build_instrument_status_missing():
    result = build_instrument_status({}, "ES")
    assert result is None


# --- build_market_context_basic ---


def test_build_market_context_basic():
    bot_data = {
        "market_live": {
            "vix": 16.5,
            "vix_regime": "NORMAL",
            "atr_es": 70.0,
            "atr_nq": 350.0,
            "vwap_slope_es": 0.001,
            "vwap_slope_nq": -0.002,
        }
    }
    result = build_market_context_basic(bot_data)
    assert result["vix"] == 16.5
    assert result["vix_regime"] == "NORMAL"
    assert result["atr_es"] == 70.0
    assert result["vwap_slope_nq"] == -0.002


def test_build_market_context_basic_empty():
    result = build_market_context_basic({})
    assert result["vix"] == 0.0
    assert result["vix_regime"] == "UNKNOWN"


# --- build_market_context_full ---


def test_build_market_context_full():
    bot_data = {"market_live": {"vix": 20.0, "vix_regime": "HIGH"}}
    bar_es = {
        "open_type": 1,
        "day_type": 4,
        "profile_shape": 2,
        "ib_range_ticks": 40.0,
        "sess_range_ticks": 80.0,
    }
    result = build_market_context_full(bot_data, bar_es, {})
    assert result["vix"] == 20.0
    assert result["open_type_label"] == "OD UP"
    assert result["day_type_label"] == "TREND"
    assert result["profile_shape_label"] == "b-Shape"
    assert result["ib_range_ticks"] == 40.0
    # Extension ratio = (80-40)/40 = 1.0
    assert result["ib_extension_ratio"] == 1.0


def test_build_market_context_full_zero_ib():
    """IB range zero ne doit pas causer de division par zero."""
    result = build_market_context_full({}, {"ib_range_ticks": 0.0}, {})
    assert result["ib_extension_ratio"] == 0.0


# --- build_order_flow ---


def test_build_order_flow():
    bar = {
        "delta_bar": 150.0,
        "delta_pct": 0.25,
        "cvd_day": 5000.0,
        "rvol": 2.5,
        "finish_strength": 0.8,
    }
    result = build_order_flow(bar)
    assert result["delta_bar"] == 150.0
    assert result["rvol"] == 2.5
    assert result["finish_strength"] == 0.8
    # rvol 2.5 -> regime 3 (Spike) : < 0.5=Low, < 1.0=Normal, < 2.0=High, < 3.0=Spike
    assert result["rvol_regime"] == 3
    assert result["rvol_regime_label"] == "Spike"


def test_build_order_flow_empty():
    """bar vide retourne dict vide (pas de defaults)."""
    result = build_order_flow({})
    assert result == {}


def test_build_order_flow_climax_positive():
    """Climax signal quand rvol >= 3 et delta_pct extreme."""
    bar = {"rvol": 4.0, "delta_pct": 0.8}
    result = build_order_flow(bar)
    assert result["climax_signal"] == 1.0


def test_build_order_flow_climax_negative():
    bar = {"rvol": 3.5, "delta_pct": -0.7}
    result = build_order_flow(bar)
    assert result["climax_signal"] == -1.0


def test_build_order_flow_no_climax():
    bar = {"rvol": 1.0, "delta_pct": 0.8}
    result = build_order_flow(bar)
    assert result["climax_signal"] == 0.0


def test_build_order_flow_rvol_regimes():
    """Verifie le mapping rvol -> regime."""
    assert build_order_flow({"rvol": 0.3})["rvol_regime"] == 0  # Low
    assert build_order_flow({"rvol": 0.7})["rvol_regime"] == 1  # Normal
    assert build_order_flow({"rvol": 1.5})["rvol_regime"] == 2  # High
    assert build_order_flow({"rvol": 2.5})["rvol_regime"] == 3  # Spike
    assert build_order_flow({"rvol": 5.0})["rvol_regime"] == 4  # Extreme


# --- build_options_gamma ---


def test_build_options_gamma():
    bar = {
        "dist_mq_call": 50.0,
        "dist_mq_put": -30.0,
        "dist_mq_hvl": 10.0,
        "vix_level": 18.0,
    }
    result = build_options_gamma(bar)
    assert result["dist_mq_call"] == 50.0
    assert result["vix_level"] == 18.0


def test_build_options_gamma_empty():
    """bar vide retourne dict vide."""
    result = build_options_gamma({})
    assert result == {}


def test_build_options_gamma_all_fields():
    bar = {
        "dist_mq_call": 1.0,
        "dist_mq_put": 2.0,
        "dist_mq_hvl": 3.0,
        "dist_mq_call_0dte": 4.0,
        "dist_mq_put_0dte": 5.0,
        "dist_gex_nearest_up": 6.0,
        "dist_gex_nearest_dn": 7.0,
        "gex_cluster_count": 3,
        "bool_gex_flip_zone": 1,
        "vix_level": 20.0,
        "vix_regime": 2,
        "dist_vix_call": 8.0,
        "dist_vix_put": 9.0,
        "next_wall_dist_ticks": 10.0,
        "next_wall_is_call": 1,
    }
    result = build_options_gamma(bar)
    assert len(result) == 15
    assert result["gex_cluster_count"] == 3
    assert result["bool_gex_flip_zone"] == 1


# --- build_intermarket ---


def test_build_intermarket():
    bar_es = {
        "delta_day_dir": 1,
        "new_swing_high": 1,
        "new_swing_low": 0,
        "rvol": 2.0,
        "large_trader_ratio": 0.5,
        "price_vs_swing_mid": 0.3,
        "price": 5500.0,
        "session": 3,
        "open_bias_conf": 0.7,
        "trend_day_probability": 0.6,
        "vwap_triple_align": 1,
        "diag_imbalance": 0.1,
    }
    bar_nq = {
        "delta_day_dir": 1,
        "new_swing_high": 1,
        "new_swing_low": 0,
        "rvol": 1.5,
        "large_trader_ratio": 0.4,
        "price_vs_swing_mid": 0.2,
        "price": 20000.0,
    }
    result = build_intermarket(bar_es, bar_nq)
    assert result["cross_delta_agreement"] == 1  # meme direction
    assert result["smt_divergence"] == 0  # meme swings
    assert result["amd_phase"] == 2  # session 3 -> mapped 2 (US)
    assert result["amd_phase_label"] == "US"
    assert result["volume_lead"] == 1  # ES rvol > NQ * 1.2


def test_build_intermarket_smt_divergence():
    """ES new high, NQ non -> SMT divergence."""
    bar_es = {"new_swing_high": 1, "new_swing_low": 0}
    bar_nq = {"new_swing_high": 0, "new_swing_low": 0}
    result = build_intermarket(bar_es, bar_nq)
    assert result["smt_divergence"] == 1


def test_build_intermarket_both_empty():
    """Deux barres vides retourne dict vide."""
    result = build_intermarket({}, {})
    assert result == {}


def test_build_intermarket_es_only():
    bar_es = {"session": 2, "price_vs_swing_mid": 0.5, "price": 5500.0}
    result = build_intermarket(bar_es, None)
    assert result["amd_phase"] == 1  # session 2 -> mapped 1 (London)
    assert result["amd_phase_label"] == "London"


# --- build_signals_journal ---


def test_build_signals_journal():
    bot_data = {
        "signals_journal": {
            "current_signal": "BUY",
            "signal_score": 0.85,
            "signal_reason": "LightGBM score > 0.7",
            "sl_ticks": 8.0,
            "tp_ticks": 16.0,
            "rr_ratio": 2.0,
            "recent_trades": [{"ts": "10:00", "symbol": "ES", "direction": "BUY"}],
            "recent_rejections": ["VIX too high"],
        }
    }
    result = build_signals_journal(bot_data)
    assert result["current_signal"] == "BUY"
    assert result["signal_score"] == 0.85
    assert len(result["recent_trades"]) == 1
    assert len(result["recent_rejections"]) == 1


def test_build_signals_journal_empty():
    result = build_signals_journal({})
    assert result["current_signal"] is None
    assert result["recent_trades"] == []
