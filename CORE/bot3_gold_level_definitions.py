"""Bot 3 Gold — Niveaux NEUTRAL (selon PROMPT_CLAUDE_CODE_BOT3_GOLD).

Architecture dynamique : tous niveaux NEUTRAL, side décidé par 8 scenarios.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# NIVEAUX GOLD-SPÉCIFIQUES (en TICKS, validés edge discovery RTH)
# ─────────────────────────────────────────────────────────────────────────────
GOLD_LEVELS_SPECIFIC = {
    "MQ_CALL_0DTE": {
        "col": "dist_mq_call_0dte", "proximity_ticks": 50,
        "side": "NEUTRAL", "tier": 1,
        "edge_rth_pf": 1.60, "edge_rth_n": 373,
        "note": "Call wall 0DTE gamma. RTH PF 1.60.",
    },
    "MQ_PUT_0DTE": {
        "col": "dist_mq_put_0dte", "proximity_ticks": 50,
        "side": "NEUTRAL", "tier": 1,
        "edge_rth_pf": 1.18, "edge_rth_n": 1277,
        "note": "Put wall 0DTE support gamma.",
    },
    "MQ_HVL_0DTE": {
        "col": "dist_mq_hvl_0dte", "proximity_ticks": 50,
        "side": "NEUTRAL", "tier": 2,
        "note": "HVL 0DTE pivot.",
    },
    "BLIND_SPOT_UP": {
        "col": "dist_blind_nearest_up", "proximity_ticks": 30,
        "side": "NEUTRAL", "tier": 2,
        "edge_rth_pf": 1.58, "edge_rth_n": 226,
        "note": "Blind spot up = accélération.",
    },
    "BLIND_SPOT_DN": {
        "col": "dist_blind_nearest_dn", "proximity_ticks": 30,
        "side": "NEUTRAL", "tier": 2,
        "note": "Blind spot dn = accélération.",
    },
    "MQ_CALL_DAILY": {
        # FIX 19/05 PM (Jackson "MGC dead-on-arrival") : proximity 100->200 ticks
        # (= 20 pts MGC vs 10 pts avant). Justification : Gold ATR daily ~50-100 pts,
        # 10 pts proximity trop strict (MGC 4511.7 vs mq_put 4500 = 11.7 pts JUSTE
        # au-dela du seuil = 1934 SKIP NO_LEVEL_TOUCH aujourd'hui). 20 pts ≈ 0.44% prix.
        # 0DTE reste serre (50 ticks = 5 pts) car options 0DTE plus proches du prix.
        "col": "dist_mq_call", "proximity_ticks": 200,
        "side": "NEUTRAL", "tier": 2,
        "note": "Call wall daily macro (proximity elargie 100->200 ticks 19/05).",
    },
    "MQ_PUT_DAILY": {
        "col": "dist_mq_put", "proximity_ticks": 200,
        "side": "NEUTRAL", "tier": 2,
        "note": "Put wall daily macro (proximity elargie 100->200 ticks 19/05).",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# NIVEAUX MARKET PROFILE STANDARD (en PCT)
# ─────────────────────────────────────────────────────────────────────────────
GOLD_LEVELS_MP = {
    "SINGLE_PRINT":  {"col": "dist_single_print_nearest_pct", "proximity_pct": 0.0002, "side": "NEUTRAL", "tier": 1},
    "IB_LOW":        {"col": "dist_ib_low_pct",  "proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 1},
    "IB_HIGH":       {"col": "dist_ib_high_pct", "proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 1},
    "CUR_VPOC":      {"col": "dist_cur_vpoc_pct","proximity_pct": 0.0003, "side": "NEUTRAL", "tier": 1},
    "CUR_VAH":       {"col": "dist_cur_vah_pct", "proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "CUR_VAL":       {"col": "dist_cur_val_pct", "proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "OPEN_830":      {"col": "dist_open_830_pct","proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 1},
    "OPEN_930":      {"col": "dist_open_930_pct","proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "PREV_VAH":      {"col": "dist_prev_vah_pct","proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "PREV_VAL":      {"col": "dist_prev_val_pct","proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "PDH":           {"col": "dist_pdh_pct",     "proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "PDL":           {"col": "dist_pdl_pct",     "proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "CASH_HIGH":     {"col": "dist_cash_high_pct","proximity_pct": 0.0005,"side": "NEUTRAL", "tier": 2},
    "CASH_LOW":      {"col": "dist_cash_low_pct","proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 2},
    "VWAP_D":        {"col": "dist_vwap_d_pct",  "proximity_pct": 0.0005, "side": "NEUTRAL", "tier": 1},
    "VWAP_SD1U":     {"col": "dist_vwap_d_sd1u_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "VWAP_SD1D":     {"col": "dist_vwap_d_sd1d_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "VWAP_SD2U":     {"col": "dist_vwap_d_sd2u_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "VWAP_SD2D":     {"col": "dist_vwap_d_sd2d_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "VWAP_W_SD1D":   {"col": "dist_vwap_w_sd1d_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "VWAP_W_SD1U":   {"col": "dist_vwap_w_sd1u_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "LONDON_HIGH":   {"col": "dist_london_high_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "LONDON_LOW":    {"col": "dist_london_low_pct", "proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "LONDON_OPEN":   {"col": "dist_london_open_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "ASIA_HIGH":     {"col": "dist_asia_high_pct",  "proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "ASIA_LOW":      {"col": "dist_asia_low_pct",   "proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "NY_OPEN":       {"col": "dist_ny_open_pct",    "proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "COLOR_UP_ZONE": {"col": "dist_color_up_nearest_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
    "COLOR_DN_ZONE": {"col": "dist_color_dn_nearest_pct","proximity_pct": 0.0005,"side": "NEUTRAL","tier": 2},
}


def get_all_gold_levels() -> dict:
    """Retourne dict combiné Gold-specific + MP."""
    return {**GOLD_LEVELS_SPECIFIC, **GOLD_LEVELS_MP}


def is_ticks_level(level_def: dict) -> bool:
    return "proximity_ticks" in level_def and level_def["proximity_ticks"] is not None


def get_proximity(level_def: dict):
    if is_ticks_level(level_def):
        return level_def["proximity_ticks"], True
    return level_def.get("proximity_pct", 0.0005), False
