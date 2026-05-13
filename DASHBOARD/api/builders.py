"""Fonctions build_* du dashboard MIA.

Chaque builder prend une barre JSONL (dict) et retourne un dict structure
pour le frontend. Toutes les distances sont converties en prix absolus.
"""
import logging
from typing import List, Optional, Tuple

from CORE.bias_calculator import calc_confidence, compute_bias  # 3.7.9 (24/04) source unique biais
# 11/05 J2b MGC integration : get_tick_size strict (source unique CORE/constants).
# TICK_SIZE legacy de readers = default ES/NQ 0.25 hardcode (cf rules/tick-size-policy.md).
# Pour MGC (tick=0.10), il FAUT lire dynamiquement le tick par symbole.
try:
    from CORE.constants import get_tick_size as _get_tick_size_strict
except ImportError:
    from constants import get_tick_size as _get_tick_size_strict  # fallback path
from DASHBOARD.api.readers import (
    DAY_TYPE_LABELS,
    OPEN_TYPE_LABELS,
    PROFILE_SHAPE_LABELS,
    RVOL_REGIME_LABELS,
    TICK_SIZE,  # legacy 0.25 default, conserve pour helpers tick-agnostic existants
    VIX_REGIME_LABELS,
    dist_to_price,
    get_field,
    get_int_field,
    get_nullable_field,
    get_str_field,
    rvol_to_regime,
    vix_dist_to_price,
)


def _tick_for(symbol):
    """Helper tick-size par symbole (ES/NQ=0.25, MGC=0.10).

    Fallback safe sur TICK_SIZE (0.25) si symbole inconnu — pour ne pas casser
    les call sites legacy. Le warning est emit cote constants.get_tick_size.
    """
    if symbol is None:
        return TICK_SIZE
    try:
        return _get_tick_size_strict(symbol)
    except (KeyError, ValueError):
        return TICK_SIZE


def _nullable_round(val, ndigits=4):
    """Round si val est numerique, sinon retourne None (pour features nullable)."""
    if val is None:
        return None
    try:
        return round(float(val), ndigits)
    except (ValueError, TypeError):
        return None

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Helper partage
# ═══════════════════════════════════════════════════════════════


# _calc_confidence DEPLACE dans CORE/bias_calculator.py (3.7.9 — 24/04)
# Alias pour retrocompat interne builders.py (ancien appel ligne ~363)
_calc_confidence = calc_confidence


# ═══════════════════════════════════════════════════════════════
# Builder 0 : Bot Status
# ═══════════════════════════════════════════════════════════════


def build_bot_status(bot_data: dict) -> dict:
    """Statut bot basique."""
    bs = bot_data.get("bot_status", {})
    return {
        "running": bs.get("running", False),
        "global_status": bs.get("global_status", "UNKNOWN"),
        "last_heartbeat": bs.get("last_heartbeat", ""),
    }


def build_instrument_status(bot_data: dict, symbol: str) -> dict:
    """Statut d'un instrument (ES ou NQ)."""
    instr = bot_data.get(symbol.lower(), {})
    return {
        "enabled": instr.get("enabled", False),
        "in_position": instr.get("in_position", False),
        "status": instr.get("status", "Bot offline"),
        "trades_today": instr.get("trades_today", 0),
        "wins": instr.get("wins", 0),
        "losses": instr.get("losses", 0),
        "pnl_today": instr.get("pnl_today", 0.0),
        "consecutive_losses": instr.get("consecutive_losses", 0),
        "last_rejected": instr.get("last_rejected", ""),
        "signals_rejected": instr.get("signals_rejected", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 1 : Price Banner
# ═══════════════════════════════════════════════════════════════


def build_price_banner(bar_es: dict, bar_nq: dict, bar_mgc: Optional[dict] = None) -> dict:
    """Bandeau prix live ES + NQ + MGC (11/05 J2b).

    bar_mgc kwarg optionnel (retro-compat). Si None, slot mgc absent du banner.
    """
    def _instrument(bar: dict) -> dict:
        if not bar:
            return {"price": 0, "atr": 0, "change_pct": 0, "session": "N/A"}
        price = get_field(bar, "price", 0.0)
        sess_range = get_field(bar, "sess_range_ticks", 0.0)
        dist_sess_low = get_field(bar, "dist_sess_low", 0.0)
        # Position dans le range session en %
        range_pct = 0.0
        if sess_range > 0:
            range_pct = round(dist_sess_low / sess_range * 100, 1)
        # FIX 08/05 (incident Bot 1 07/05 + Bot 2 V6 08/05) : emettre 3 alias
        # `ts`, `ts_ms`, `bar_ts_ms` pour eviter regression silent quand un
        # consommateur cherche un nom different. Cause = renommage progressif
        # `ts_ms` -> `ts` non propage dans tous les bots = last_bar_age=99999
        # = STALE CRITICAL faux + watchdog restart loop.
        # Source unique : bar.get("ts"). Alias purement defensifs.
        ts_value = bar.get("ts", 0)
        return {
            "price": price,
            "bar_high": get_field(bar, "bar_high", price),
            "bar_low": get_field(bar, "bar_low", price),
            "atr": round(get_field(bar, "atr", 0.0), 1),
            "session": get_str_field(bar, "session_id", "N/A"),
            "session_range": sess_range,
            "range_position_pct": range_pct,
            "ts": ts_value,
            # Alias retro-compat (anciens consommateurs Bot 1/2 V6) - meme valeur
            "ts_ms": ts_value,
            "bar_ts_ms": ts_value,
        }

    result = {
        "es": _instrument(bar_es),
        "nq": _instrument(bar_nq),
    }
    # 11/05 J2b MGC : ajout slot banner MGC si dispo.
    # Frontend doit savoir si "mgc" est present (peut etre absent en retro-compat).
    if bar_mgc:
        result["mgc"] = _instrument(bar_mgc)
    return result


# ═══════════════════════════════════════════════════════════════
# Builder 2 : Regime & Context
# ═══════════════════════════════════════════════════════════════


def build_regime_context(bar: dict) -> dict:
    """VIX complet + VWAP tendance + momentum + bias calcule."""
    if not bar:
        return {}

    vix = get_field(bar, "vix_level", 0.0)
    vix_regime = get_int_field(bar, "vix_regime", 1)
    atr = get_field(bar, "atr", 0.0)
    atr_ratio = get_field(bar, "sess_range_atr", 0.0)

    # VWAP slopes et sides
    vwap_slope_10 = get_field(bar, "vwap_slope_10", 0.0)
    vwap_slope_30 = get_field(bar, "vwap_slope_30", 0.0)
    vwap_d_side = get_int_field(bar, "vwap_d_side", 0)
    vwap_w_side = get_int_field(bar, "vwap_w_side", 0)
    vwap_m_side = get_int_field(bar, "vwap_m_side", 0)
    triple_align = get_int_field(bar, "vwap_triple_align", 0)

    # Momentum
    momentum_3 = get_field(bar, "momentum_3b", 0.0)
    momentum_5 = get_field(bar, "momentum_5b", 0.0)
    ma_trend = get_int_field(bar, "ma_trend", 0)

    # ═══════════════════════════════════════════════════════════════
    # BIAS — 3.7.9 (24/04) : source unique CORE/bias_calculator.py
    # ═══════════════════════════════════════════════════════════════
    # Logique identique a la version inline V1 (validee 37/37 tests unitaires +
    # parite empirique sur 10 barres reelles). Remplace 170 lignes inline par
    # un appel pur + extraction des champs. Le module est aussi utilise par
    # CORE/mia_paper_trader.py pour le gate directionnel STEP 6bis
    # (cohérence bot/dashboard garantie).
    bias_result = compute_bias(bar)

    # Variables utilisees plus loin dans le dict sortant (pos, dist_vwap, etc.)
    pos = get_field(bar, "range_pos", 50.0)
    dist_vwap = get_field(bar, "dist_vwap_d", 0.0)
    delta_day_dir = get_int_field(bar, "delta_day_dir", 0)

    # Extraction des champs bias pour retrocompat dashboard
    score = bias_result.score_signed
    bias_dict = bias_result.to_dashboard_dict()
    bias = bias_dict["bias"]
    bias_label = bias_dict["bias_label"]
    factors = bias_dict["bias_factors"]
    delta_div = get_int_field(bar, "delta_divergence", 0)
    div_quality = bias_result.div_quality
    div_grade = bias_result.div_grade
    div_factors = bias_result.div_factors
    is_trending = bias_result.is_trending

    # 🆕 03/05 (Plan B Action 3) : refactor pour appeler regime_engine.compute_regime
    # SOURCE UNIQUE : Bot 1 dashboard + Bot 2/3 regime_engine partagent meme logique +
    # meme calibration optimale (vol_extreme=5.5, mode_strong=3, etc. — grid search 14j).
    # Anti-Pattern 11 V1 : 1 verdict regime, pas 2 implementations divergentes.
    regime_actionable = 0
    regime_confidence_val = 0.0
    try:
        from CORE.regime_engine import compute_regime
        regime_result = compute_regime(bar)
        mode = regime_result.mode
        favor = regime_result.favor
        vol_regime = regime_result.vol_regime
        trend_votes = regime_result.trend_votes
        range_votes = regime_result.range_votes
        regime_details = regime_result.details
        regime_actionable = int(regime_result.is_actionable)
        regime_confidence_val = regime_result.confidence
    except Exception as e:
        import logging
        logging.error(f"regime_engine fail in build_regime_context: {e}")
        # Fallback safe (mode=NORMAL favor=NEUTRE = pas de gate active)
        mode = "NORMAL"
        favor = "NEUTRE"
        vol_regime = "NORMAL"
        trend_votes = 0
        range_votes = 0
        regime_details = ["regime_engine_fail"]

    # Override coherence bias : evite LONG quand la structure est bearish (3+ facteurs bear)
    # Cette logique est preservee cote dashboard (compute_bias officiel) plutot que regime_engine.
    bear_factors = sum(1 for f in factors if f.get("icon") == "bear")
    bull_factors = sum(1 for f in factors if f.get("icon") == "bull")
    if favor == "LONG" and bear_factors >= 3:
        favor = "NEUTRE"
    elif favor == "SHORT" and bull_factors >= 3:
        favor = "NEUTRE"

    return {
        "vix": vix,
        "vix_regime": vix_regime,
        "vix_regime_label": VIX_REGIME_LABELS.get(vix_regime, "NORMAL"),
        "atr": round(atr, 1),
        "sess_range_ticks": get_field(bar, "sess_range_ticks", 0.0),
        "sess_range_atr": round(atr_ratio, 3),
        "vwap_slope_10": round(vwap_slope_10, 2),
        "vwap_slope_30": round(vwap_slope_30, 2),
        "vwap_slope_10_dir": get_int_field(bar, "vwap_slope_10_dir", 0),
        "vwap_d_side": vwap_d_side,
        "vwap_w_side": vwap_w_side,
        "vwap_m_side": vwap_m_side,
        "vwap_ma_align": get_int_field(bar, "vwap_ma_align", 0),
        "vwap_triple_align": triple_align,
        "momentum_3b": momentum_3,
        "momentum_5b": momentum_5,
        "ma_trend": ma_trend,
        "bias": bias,
        "bias_label": bias_label,
        "bias_score": round(score, 3),
        "bias_confidence": round(_calc_confidence(score, factors), 2),
        "bias_factors": factors,
        "mode": mode,
        "mode_trend_votes": trend_votes,
        "mode_range_votes": range_votes,
        "mode_details": regime_details,
        "favor": favor,
        "vol_regime": vol_regime,
        # 🆕 03/05 (Bot 1 STEP 0 STRICT) : expose is_actionable + confidence
        # pour permettre Bot 1 (mia_paper_trader.py) de filtrer trades hors regime.
        "regime_actionable": regime_actionable,
        "regime_confidence": round(regime_confidence_val, 2),
        "range_pos": round(pos, 1),
        "_price": get_field(bar, "price", 0.0),
        # Divergence
        "div_active": bool(delta_div),
        "div_quality": round(div_quality, 1),
        "div_grade": div_grade,
        "div_factors": div_factors,
    }


# ═══════════════════════════════════════════════════════════════
# Builder 3 : Session & Open
# ═══════════════════════════════════════════════════════════════


def build_session_open(bar: dict) -> dict:
    """Open type, overnight, gap, AMD phase."""
    if not bar:
        return {}

    open_type = get_int_field(bar, "open_type", 0)
    session_val = get_int_field(bar, "session", 0)

    return {
        "open_type": open_type,
        "open_type_label": OPEN_TYPE_LABELS.get(open_type, "UNKNOWN"),
        "open_direction": get_int_field(bar, "open_direction", 0),
        "open_zone": get_int_field(bar, "open_zone", 0),
        "open_gap_ticks": get_field(bar, "open_gap_ticks", 0.0),
        "open_in_prev_va": get_int_field(bar, "open_in_prev_va", 0),
        "open_position": get_int_field(bar, "open_position", 0),
        "open_bias_conf": get_field(bar, "open_bias_conf", 0.0),
        "session": session_val,
        "session_label": get_str_field(bar, "session_id", "Closed"),
        "session_id": get_str_field(bar, "session_id", "N/A"),
        "day_type": get_int_field(bar, "day_type", 0),
        "day_type_label": DAY_TYPE_LABELS.get(get_int_field(bar, "day_type", 0), "NEUTRAL"),
        "trend_day_prob": get_field(bar, "trend_day_probability", 0.0),
        "ovn_range_ticks": get_field(bar, "ovn_range_ticks", 0.0),
        "ovn_high_price": dist_to_price(bar, "dist_ovn_high"),
        "ovn_low_price": dist_to_price(bar, "dist_ovn_low"),
        "open_cash_price": dist_to_price(bar, "dist_open_cash"),
        "open_830_price": dist_to_price(bar, "dist_open_830"),
        "sess_high_price": dist_to_price(bar, "dist_sess_high"),
        "sess_low_price": dist_to_price(bar, "dist_sess_low"),
        "bool_session_early": get_int_field(bar, "bool_session_early", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 4 : Options & Gamma (PRIX ABSOLUS)
# ═══════════════════════════════════════════════════════════════


def build_options_levels(bar: dict, symbol: Optional[str] = None) -> dict:
    """Murs options MQ + GEX en prix absolus.

    11/05 J2b MGC : kwarg `symbol` optionnel (retro-compat, default None = TICK_SIZE
    legacy 0.25 ES/NQ). Si symbol fourni → tick dynamique via _tick_for.
    """
    if not bar:
        return {}

    price = get_field(bar, "price", 0.0)
    next_wall_dist = get_field(bar, "next_wall_dist_ticks", 0.0)
    next_wall_is_call = get_int_field(bar, "next_wall_is_call", 0)
    wall_sign = 1 if next_wall_is_call else -1
    _tick = _tick_for(symbol) if symbol else TICK_SIZE  # retro-compat ES/NQ
    next_wall_price = round(price + wall_sign * next_wall_dist * _tick, 2) if price else None

    return {
        "call_wall_price": dist_to_price(bar, "dist_mq_call"),
        "put_wall_price": dist_to_price(bar, "dist_mq_put"),
        "hvl_price": dist_to_price(bar, "dist_mq_hvl"),
        "call_0dte_price": dist_to_price(bar, "dist_mq_call_0dte"),
        "put_0dte_price": dist_to_price(bar, "dist_mq_put_0dte"),
        "dist_mq_call": get_field(bar, "dist_mq_call", 0.0),
        "dist_mq_put": get_field(bar, "dist_mq_put", 0.0),
        "dist_mq_hvl": get_field(bar, "dist_mq_hvl", 0.0),
        "dist_mq_call_0dte": get_field(bar, "dist_mq_call_0dte", 0.0),
        "dist_mq_put_0dte": get_field(bar, "dist_mq_put_0dte", 0.0),
        "gex_up_price": dist_to_price(bar, "dist_gex_nearest_up"),
        "gex_dn_price": dist_to_price(bar, "dist_gex_nearest_dn"),
        "dist_gex_up": get_field(bar, "dist_gex_nearest_up", 0.0),
        "dist_gex_dn": get_field(bar, "dist_gex_nearest_dn", 0.0),
        "gex_cluster_count": get_int_field(bar, "gex_cluster_count", 0),
        "gex_flip_zone": get_int_field(bar, "bool_gex_flip_zone", 0),
        "next_wall_price": next_wall_price,
        "next_wall_dist": next_wall_dist,
        "next_wall_side": "CALL" if next_wall_is_call else "PUT",
        "bool_above_mq_hvl": get_int_field(bar, "bool_above_mq_hvl", 0),
        "bool_above_mq_call": get_int_field(bar, "bool_above_mq_call", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 5 : VIX Gamma (prix VIX absolus)
# ═══════════════════════════════════════════════════════════════


def build_vix_gamma(bar: dict) -> dict:
    """VIX options en prix absolus."""
    if not bar:
        return {}

    vix = get_field(bar, "vix_level", 0.0)
    return {
        "vix_level": vix,
        "vix_regime": get_int_field(bar, "vix_regime", 1),
        "vix_regime_label": VIX_REGIME_LABELS.get(get_int_field(bar, "vix_regime", 1), "NORMAL"),
        "vix_call_price": vix_dist_to_price(bar, "dist_vix_call"),
        "vix_put_price": vix_dist_to_price(bar, "dist_vix_put"),
        "vix_hvl_price": vix_dist_to_price(bar, "dist_vix_hvl"),
        "vix_call_0dte_price": vix_dist_to_price(bar, "dist_vix_call_0dte"),
        "vix_put_0dte_price": vix_dist_to_price(bar, "dist_vix_put_0dte"),
        "vix_hvl_0dte_price": vix_dist_to_price(bar, "dist_vix_hvl_0dte"),
        "vix_gex_up_price": vix_dist_to_price(bar, "dist_vix_gex_nearest_up"),
        "vix_gex_dn_price": vix_dist_to_price(bar, "dist_vix_gex_nearest_dn"),
        "vix_above_hvl": get_int_field(bar, "vix_above_hvl", 0),
        "vix_above_hvl_0dte": get_int_field(bar, "vix_above_hvl_0dte", 0),
        "dist_vix_call": get_field(bar, "dist_vix_call", 0.0),
        "dist_vix_put": get_field(bar, "dist_vix_put", 0.0),
        "dist_vix_hvl": get_field(bar, "dist_vix_hvl", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 6 : Order Flow V2 (30 champs)
# ═══════════════════════════════════════════════════════════════


def build_order_flow(bar: dict) -> dict:
    """Delta, CVD, RVOL, volume, pression, diagnostics."""
    if not bar:
        return {}

    rvol = get_field(bar, "rvol", 0.0)
    rvol_regime = rvol_to_regime(rvol)
    delta_pct = get_field(bar, "delta_pct", 0.0)

    # Climax : volume > 3x ET delta extreme
    climax = 0
    if rvol >= 3.0 and abs(delta_pct) > 0.6:
        climax = 1 if delta_pct > 0 else -1

    return {
        "delta_bar": get_field(bar, "delta_bar", 0.0),
        "delta_pct": round(delta_pct, 4),
        "delta_bar_vol_norm": get_field(bar, "delta_bar_vol_norm", 0.0),
        "delta_day": get_field(bar, "delta_day", 0.0),
        "delta_day_dir": get_int_field(bar, "delta_day_dir", 0),
        "delta_divergence": get_int_field(bar, "delta_divergence", 0),
        "cvd_day": get_field(bar, "cvd_day", 0.0),
        "cvd_day_dir": get_int_field(bar, "cvd_day_dir", 0),
        "cvd_bar_delta": get_field(bar, "cvd_bar_delta", 0.0),
        "cvd_ohlc_range": get_field(bar, "cvd_ohlc_range", 0.0),
        "rvol": round(rvol, 4),
        "rvol_zscore": round(get_field(bar, "rvol_zscore", 0.0), 4),
        "rvol_regime": rvol_regime,
        "rvol_regime_label": RVOL_REGIME_LABELS.get(rvol_regime, "Normal"),
        "rvol_buy": get_int_field(bar, "rvol_buy", 0),
        "rvol_sell": get_int_field(bar, "rvol_sell", 0),
        "rvol_absorb_buy": get_field(bar, "rvol_absorb_buy", 0.0),
        "rvol_absorb_sell": get_field(bar, "rvol_absorb_sell", 0.0),
        "total_vol": get_field(bar, "total_vol", 0.0),
        "buy_vol": get_field(bar, "buy_vol", 0.0),
        "sell_vol": get_field(bar, "sell_vol", 0.0),
        "buy_sell_ratio": round(get_field(bar, "buy_sell_ratio", 0.5), 4),
        "vol_per_sec": round(get_field(bar, "vol_per_sec", 0.0), 2),
        "volume_imbalance": round(get_field(bar, "volume_imbalance", 0.0), 4),
        "ask_pct": round(get_field(bar, "ask_pct", 0.5), 4),
        "bid_pct": round(get_field(bar, "bid_pct", 0.5), 4),
        "ask_bid_imbalance": round(get_field(bar, "ask_bid_imbalance", 0.0), 4),
        "large_trader_ratio": round(get_field(bar, "large_trader_ratio", 0.0), 4),
        "finish_strength": get_field(bar, "finish_strength", 0.0),
        "climax_signal": climax,
        "diag_imbalance": round(get_field(bar, "diag_imbalance", 0.0), 4),
        "diag_pos_delta": get_field(bar, "diag_pos_delta", 0.0),
        "diag_neg_delta": get_field(bar, "diag_neg_delta", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 7 : Battle Navale
# ═══════════════════════════════════════════════════════════════


def build_battle_navale(bar: dict) -> dict:
    """BN score + 12 composants + edges."""
    if not bar:
        return {}

    # Features GARDER uniquement (DROP list du CLAUDE.md retiree)
    return {
        "bn_score_raw": get_field(bar, "bn_score_raw", 0.0),
        "bn_score_bear": get_field(bar, "bn_score_bear", 0.0),
        "bn_color_up_2": get_int_field(bar, "bn_color_up_2", 0),
        "bn_color_dn_2": get_int_field(bar, "bn_color_dn_2", 0),
        "bn_absorb_ask": get_int_field(bar, "bn_absorb_ask", 0),
        "bn_absorb_bid": get_int_field(bar, "bn_absorb_bid", 0),
        "bn_pressure_bid": get_field(bar, "bn_pressure_bid", 0.0),
        "bar_edge_buy": get_int_field(bar, "bar_edge_buy", 0),
        "bar_edge_sell": get_int_field(bar, "bar_edge_sell", 0),
        "fp_edge_buy": get_int_field(bar, "fp_edge_buy", 0),
        "fp_edge_sell": get_int_field(bar, "fp_edge_sell", 0),
        "bar_pressure_bid": get_int_field(bar, "bar_pressure_bid", 0),
        "avg_trade_size": round(get_field(bar, "avg_trade_size", 0.0), 2),
        "avg_ask_size": round(get_field(bar, "avg_ask_size", 0.0), 2),
        "avg_bid_size": round(get_field(bar, "avg_bid_size", 0.0), 2),
        "finish_delta_pct": get_field(bar, "finish_delta_pct", 0.0),
        "high_pullback_delta": get_field(bar, "high_pullback_delta", 0.0),
        "low_pullback_delta": get_field(bar, "low_pullback_delta", 0.0),
        "rotation_up": get_field(bar, "rotation_up", 0.0),
        "rotation_dn": get_field(bar, "rotation_dn", 0.0),
        "rotation_zz_osc": get_field(bar, "rotation_zz_osc", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 8 : Market Profile (PRIX ABSOLUS)
# ═══════════════════════════════════════════════════════════════


def build_market_profile(bar: dict) -> dict:
    """VPOC, VA, composites, HVN/LVN, profil shape — tout en prix."""
    if not bar:
        return {}

    profile_shape = get_int_field(bar, "profile_shape", 0)
    day_type = get_int_field(bar, "day_type", 0)
    ib_range = get_field(bar, "ib_range_ticks", 0.0)
    sess_range = get_field(bar, "sess_range_ticks", 0.0)
    ib_ext = round((sess_range - ib_range) / ib_range, 3) if ib_range > 0 else 0.0

    return {
        "profile_shape": profile_shape,
        "profile_shape_label": PROFILE_SHAPE_LABELS.get(profile_shape, "D-Shape"),
        "profile_skew": round(get_field(bar, "profile_skew", 0.0), 4),
        "profile_hvn_dominant": get_field(bar, "profile_hvn_dominant", 0.0),
        "is_double_dist": get_int_field(bar, "is_double_dist", 0),
        "day_type": day_type,
        "day_type_label": DAY_TYPE_LABELS.get(day_type, "NEUTRAL"),
        "poc_position": get_field(bar, "poc_position", 0.0),
        "poc_bar_dist": get_field(bar, "poc_bar_dist", 0.0),
        "poc_separation_ticks": get_field(bar, "poc_separation_ticks", 0.0),
        # VPOC en prix
        "cur_vpoc_price": dist_to_price(bar, "dist_cur_vpoc"),
        "cur_vah_price": dist_to_price(bar, "dist_cur_vah"),
        "cur_val_price": dist_to_price(bar, "dist_cur_val"),
        "cur_vwap_vp_price": dist_to_price(bar, "dist_cur_vwap_vp"),
        "inside_cur_va": get_int_field(bar, "inside_cur_va", 0),
        # FIX 2026-04-16 : va_position_pct est null hors VA (pas 0.5 default).
        # Sinon le dashboard affichait "VA Position 50%" en meme temps que
        # "Dans VA : non" -> contradiction visuelle. Le JS fmtPct(null) -> "--".
        "va_position_pct": _nullable_round(get_nullable_field(bar, "va_position_pct"), 4),
        "bars_in_va": get_field(bar, "bars_in_va", 0.0),
        "vah_touches_20b": get_field(bar, "vah_touches_20b", 0.0),
        "val_touches_20b": get_field(bar, "val_touches_20b", 0.0),
        # Previous day
        "prev_vpoc_price": dist_to_price(bar, "dist_prev_vpoc"),
        "prev_vah_price": dist_to_price(bar, "dist_prev_vah"),
        "prev_val_price": dist_to_price(bar, "dist_prev_val"),
        "prev_vwap_price": dist_to_price(bar, "dist_prev_vwap"),
        "inside_prev_va": get_int_field(bar, "inside_prev_va", 0),
        # Composites
        "comp_20d_vpoc_price": dist_to_price(bar, "dist_comp_20d_vpoc"),
        "comp_20d_vah_price": dist_to_price(bar, "dist_comp_20d_vah"),
        "comp_20d_val_price": dist_to_price(bar, "dist_comp_20d_val"),
        "comp_50d_vpoc_price": dist_to_price(bar, "dist_comp_50d_vpoc"),
        "comp_50d_vah_price": dist_to_price(bar, "dist_comp_50d_vah"),
        "comp_50d_val_price": dist_to_price(bar, "dist_comp_50d_val"),
        "comp_vpoc_align_20_50": get_int_field(bar, "comp_vpoc_align_20_50", 0),
        "comp_vpoc_align_day_20": get_int_field(bar, "comp_vpoc_align_day_20", 0),
        # HVN / LVN
        "session_hvn_above_price": dist_to_price(bar, "dist_session_hvn_above"),
        "session_hvn_below_price": dist_to_price(bar, "dist_session_hvn_below"),
        "session_lvn_above_price": dist_to_price(bar, "dist_session_lvn_above"),
        "session_lvn_below_price": dist_to_price(bar, "dist_session_lvn_below"),
        "session_hvn_count": get_int_field(bar, "session_hvn_count", 0),
        "session_lvn_count": get_int_field(bar, "session_lvn_count", 0),
        "hvn_between": get_int_field(bar, "hvn_between", 0),
        "lvn_between": get_int_field(bar, "lvn_between", 0),
        "lvn_confluence_count": get_int_field(bar, "lvn_confluence_count", 0),
        # Single prints
        "single_print_count": get_int_field(bar, "single_print_count", 0),
        "single_print_mid": get_field(bar, "single_print_mid", 0.0),
        # Rule 80%
        "rule_80pct": get_int_field(bar, "rule_80pct", 0),
        # IB extension ratio
        "ib_extension_ratio": ib_ext,
        "bool_va_confluence": get_int_field(bar, "bool_va_confluence", 0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 9 : Initial Balance
# ═══════════════════════════════════════════════════════════════


def build_initial_balance(bar: dict) -> dict:
    """IB complet en prix absolus."""
    if not bar:
        return {}

    ib_range = get_field(bar, "ib_range_ticks", 0.0)
    sess_range = get_field(bar, "sess_range_ticks", 0.0)
    ib_ext = round((sess_range - ib_range) / ib_range, 3) if ib_range > 0 else 0.0

    # Fix C1-data : masque le bug C++ ou ib_complete=1 en Asia/London
    # IB valide seulement si ib_range_ticks > 0 ET session US
    ib_complete_raw = get_int_field(bar, "ib_complete", 0)
    session_id = bar.get("session_id", "")
    ib_complete_fixed = 1 if (ib_complete_raw == 1 and ib_range > 0 and session_id == "US") else 0

    return {
        "ib_high_price": dist_to_price(bar, "dist_ib_high"),
        "ib_low_price": dist_to_price(bar, "dist_ib_low"),
        "ib_range_ticks": ib_range,
        "ib_range_atr": get_field(bar, "ib_range_atr", 0.0),
        "ib_complete": ib_complete_fixed,
        "ib_broken_up": get_int_field(bar, "ib_broken_up", 0),
        "ib_broken_down": get_int_field(bar, "ib_broken_down", 0),
        "ib_is_narrow": get_int_field(bar, "ib_is_narrow", 0),
        "ib_is_wide": get_int_field(bar, "ib_is_wide", 0),
        # FIX 2026-04-16 : ib_position_pct est null hors IB/RTH (pas 0.0 default).
        # Sinon le dashboard affichait "ib_position 0%" en pre-IB (09:30-10:30 ET)
        # et hors RTH, suggerant "au plus bas de l'IB" (trompeur).
        "ib_position_pct": get_nullable_field(bar, "ib_position_pct"),
        "bool_ib_inside": get_int_field(bar, "bool_ib_inside", 0),
        "ib_extension_ratio": ib_ext,
    }


# ═══════════════════════════════════════════════════════════════
# Builder 10 : Niveaux & Distances (PRIX ABSOLUS)
# ═══════════════════════════════════════════════════════════════


def build_levels_distances(bar: dict) -> dict:
    """Tous les niveaux de S/R en prix absolus."""
    if not bar:
        return {}

    return {
        # Swing
        "swing_high_price": dist_to_price(bar, "dist_swing_high"),
        "swing_low_price": dist_to_price(bar, "dist_swing_low"),
        "swing_range_ticks": get_field(bar, "swing_range_ticks", 0.0),
        "price_vs_swing_mid": get_field(bar, "price_vs_swing_mid", 0.0),
        "new_swing_high": get_int_field(bar, "new_swing_high", 0),
        "new_swing_low": get_int_field(bar, "new_swing_low", 0),
        # Session
        "sess_high_price": dist_to_price(bar, "dist_sess_high"),
        "sess_low_price": dist_to_price(bar, "dist_sess_low"),
        "sess_range_ticks": get_field(bar, "sess_range_ticks", 0.0),
        "range_pos": get_field(bar, "range_pos", 50.0),
        "range_size_ticks": get_field(bar, "range_size_ticks", 0.0),
        # VWAP Daily + SD bands
        "vwap_d_price": dist_to_price(bar, "dist_vwap_d"),
        "vwap_d_sd1u_price": dist_to_price(bar, "dist_vwap_d_sd1u"),
        "vwap_d_sd1d_price": dist_to_price(bar, "dist_vwap_d_sd1d"),
        "vwap_d_sd2u_price": dist_to_price(bar, "dist_vwap_d_sd2u"),
        "vwap_d_sd2d_price": dist_to_price(bar, "dist_vwap_d_sd2d"),
        "vwap_d_sd3u_price": dist_to_price(bar, "dist_vwap_d_sd3u"),
        "vwap_d_sd3d_price": dist_to_price(bar, "dist_vwap_d_sd3d"),
        "dist_vwap_d_atr": get_field(bar, "dist_vwap_d_atr", 0.0),
        "bool_above_vwap_d": get_int_field(bar, "bool_above_vwap_d", 0),
        # VWAP Weekly/Monthly
        "vwap_w_price": dist_to_price(bar, "dist_vwap_w"),
        "dist_vwap_w_atr": get_field(bar, "dist_vwap_w_atr", 0.0),
        "bool_above_vwap_w": get_int_field(bar, "bool_above_vwap_w", 0),
        "vwap_m_price": dist_to_price(bar, "dist_vwap_m"),
        "dist_vwap_m_atr": get_field(bar, "dist_vwap_m_atr", 0.0),
        "bool_above_vwap_m": get_int_field(bar, "bool_above_vwap_m", 0),
        # Overnight
        "ovn_high_price": dist_to_price(bar, "dist_ovn_high"),
        "ovn_low_price": dist_to_price(bar, "dist_ovn_low"),
        "ovn_range_ticks": get_field(bar, "ovn_range_ticks", 0.0),
        "open_cash_price": dist_to_price(bar, "dist_open_cash"),
        "open_830_price": dist_to_price(bar, "dist_open_830"),
        # Retest
        "retest_high_count": get_int_field(bar, "retest_high_count", 0),
        "retest_low_count": get_int_field(bar, "retest_low_count", 0),
        "retest_high_delta_div": get_int_field(bar, "retest_high_delta_div", 0),
        "retest_low_delta_div": get_int_field(bar, "retest_low_delta_div", 0),
        "bars_since_retest_high": bar.get("bars_since_retest_high"),
        "bars_since_retest_low": bar.get("bars_since_retest_low"),
        # Range 1D
        "day_max_price": dist_to_price(bar, "dist_1d_max_ticks"),
        "day_min_price": dist_to_price(bar, "dist_1d_min_ticks"),
        # Extreme zones
        "ext_color_up_price": dist_to_price(bar, "dist_ext_color_up"),
        "ext_color_dn_price": dist_to_price(bar, "dist_ext_color_dn"),
        "ext_long_up_price": dist_to_price(bar, "dist_ext_long_up"),
        "ext_long_dn_price": dist_to_price(bar, "dist_ext_long_dn"),
        "ext_edge_buy_price": dist_to_price(bar, "dist_ext_edge_buy"),
        "ext_edge_sell_price": dist_to_price(bar, "dist_ext_edge_sell"),
        # Blind spots
        "blind_up_price": dist_to_price(bar, "dist_blind_nearest_up"),
        "blind_dn_price": dist_to_price(bar, "dist_blind_nearest_dn"),
        # Booleans position
        "bool_above_cur_vpoc": get_int_field(bar, "bool_above_cur_vpoc", 0),
        "bool_above_prev_vpoc": get_int_field(bar, "bool_above_prev_vpoc", 0),
        "bool_near_level": get_int_field(bar, "bool_near_level", 0),
        # Previous day VWAP bands
        "prev_vwap_sd1u_price": dist_to_price(bar, "dist_prev_vwap_sd1u"),
        "prev_vwap_sd1d_price": dist_to_price(bar, "dist_prev_vwap_sd1d"),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 11 : Big Orders
# ═══════════════════════════════════════════════════════════════


def build_big_orders(bar: dict) -> dict:
    """Big orders institutionnels par tier + clusters."""
    if not bar:
        return {}

    return {
        # Counts par tier
        "n_big_ask_t1": get_field(bar, "n_big_ask_t1", 0.0),
        "n_big_bid_t1": get_field(bar, "n_big_bid_t1", 0.0),
        "n_big_ask_t2": get_field(bar, "n_big_ask_t2", 0.0),
        "n_big_bid_t2": get_field(bar, "n_big_bid_t2", 0.0),
        "n_big_ask_t3": get_field(bar, "n_big_ask_t3", 0.0),
        "n_big_bid_t3": get_field(bar, "n_big_bid_t3", 0.0),
        "n_big_ask_t4": get_field(bar, "n_big_ask_t4", 0.0),
        "n_big_bid_t4": get_field(bar, "n_big_bid_t4", 0.0),
        # Clusters
        "big_ask_cluster_20t": get_field(bar, "big_ask_cluster_20t", 0.0),
        "big_bid_cluster_20t": get_field(bar, "big_bid_cluster_20t", 0.0),
        "big_ask_cluster_50t": get_field(bar, "big_ask_cluster_50t", 0.0),
        "big_bid_cluster_50t": get_field(bar, "big_bid_cluster_50t", 0.0),
        # Clusters par tier (20t)
        "big_ask_cluster_20t_t1": get_field(bar, "big_ask_cluster_20t_t1", 0.0),
        "big_bid_cluster_20t_t1": get_field(bar, "big_bid_cluster_20t_t1", 0.0),
        "big_ask_cluster_20t_t2": get_field(bar, "big_ask_cluster_20t_t2", 0.0),
        "big_bid_cluster_20t_t2": get_field(bar, "big_bid_cluster_20t_t2", 0.0),
        "big_ask_cluster_20t_t3": get_field(bar, "big_ask_cluster_20t_t3", 0.0),
        "big_bid_cluster_20t_t3": get_field(bar, "big_bid_cluster_20t_t3", 0.0),
        "big_ask_cluster_20t_t4": get_field(bar, "big_ask_cluster_20t_t4", 0.0),
        "big_bid_cluster_20t_t4": get_field(bar, "big_bid_cluster_20t_t4", 0.0),
        # Nearest big orders en prix
        "big_ask_up_price": dist_to_price(bar, "dist_big_ask_nearest_up"),
        "big_ask_dn_price": dist_to_price(bar, "dist_big_ask_nearest_dn"),
        "big_bid_up_price": dist_to_price(bar, "dist_big_bid_nearest_up"),
        "big_bid_dn_price": dist_to_price(bar, "dist_big_bid_nearest_dn"),
        # Volume details
        "high_ask_vol_pct": get_field(bar, "high_ask_vol_pct", 0.0),
        "low_bid_vol_pct": get_field(bar, "low_bid_vol_pct", 0.0),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 12 : Intermarket ES/NQ
# ═══════════════════════════════════════════════════════════════


def build_intermarket(bar_es: dict, bar_nq: dict) -> dict:
    """Comparaison ES vs NQ."""
    if not bar_es and not bar_nq:
        return {}

    es_dir = get_int_field(bar_es, "delta_day_dir", 0) if bar_es else 0
    nq_dir = get_int_field(bar_nq, "delta_day_dir", 0) if bar_nq else 0
    cross_delta = 1 if (es_dir == nq_dir and es_dir != 0) else 0

    # SMT divergence : prefere V4 `im_smt_divergence` si dispo (signe -1/0/+1),
    # fallback swing-based DMP (binaire 0/1) sinon. Audit R6 : assure une
    # seule source de verite SMT dans le payload (vs widget order_flow_advanced).
    im_smt_es = get_int_field(bar_es, "im_smt_divergence", 0) if bar_es else 0
    im_smt_nq = get_int_field(bar_nq, "im_smt_divergence", 0) if bar_nq else 0
    es_new_h = get_int_field(bar_es, "new_swing_high", 0) if bar_es else 0
    nq_new_h = get_int_field(bar_nq, "new_swing_high", 0) if bar_nq else 0
    es_new_l = get_int_field(bar_es, "new_swing_low", 0) if bar_es else 0
    nq_new_l = get_int_field(bar_nq, "new_swing_low", 0) if bar_nq else 0
    if im_smt_es != 0 or im_smt_nq != 0:
        # V4 : valeur signee, prendre l'instrument actif (NQ priorite si conflit)
        smt = 1 if (im_smt_nq != 0 or im_smt_es != 0) else 0
    else:
        smt = 1 if (es_new_h != nq_new_h or es_new_l != nq_new_l) else 0

    # SMT enrichi : direction de la divergence
    smt_direction = "NONE"
    smt_detail = ""
    if es_new_h and not nq_new_h:
        smt_direction = "BEARISH"
        smt_detail = "ES fait un nouveau high, NQ ne confirme PAS — faiblesse NQ"
    elif nq_new_h and not es_new_h:
        smt_direction = "BEARISH"
        smt_detail = "NQ fait un nouveau high, ES ne confirme PAS — faiblesse ES"
    elif es_new_l and not nq_new_l:
        smt_direction = "BULLISH"
        smt_detail = "ES fait un nouveau low, NQ ne confirme PAS — force NQ"
    elif nq_new_l and not es_new_l:
        smt_direction = "BULLISH"
        smt_detail = "NQ fait un nouveau low, ES ne confirme PAS — force ES"

    # Divergence de momentum : ES et NQ en directions opposees
    es_range_pos = get_field(bar_es, "range_pos", 50.0) if bar_es else 50.0
    nq_range_pos = get_field(bar_nq, "range_pos", 50.0) if bar_nq else 50.0
    range_pos_gap = abs(es_range_pos - nq_range_pos)
    momentum_div = range_pos_gap > 30  # gap significatif entre ES et NQ

    es_rvol = get_field(bar_es, "rvol", 0.0) if bar_es else 0.0
    nq_rvol = get_field(bar_nq, "rvol", 0.0) if bar_nq else 0.0
    if es_rvol > nq_rvol * 1.2:
        vol_lead = "ES"
    elif nq_rvol > es_rvol * 1.2:
        vol_lead = "NQ"
    else:
        vol_lead = "EQUAL"

    es_ltr = get_field(bar_es, "large_trader_ratio", 0.0) if bar_es else 0.0
    nq_ltr = get_field(bar_nq, "large_trader_ratio", 0.0) if bar_nq else 0.0

    es_price = get_field(bar_es, "price", 0.0) if bar_es else 0.0
    nq_price = get_field(bar_nq, "price", 0.0) if bar_nq else 0.0
    ratio = round(es_price / nq_price, 6) if nq_price > 0 else 0.0

    es_mid = get_field(bar_es, "price_vs_swing_mid", 0.0) if bar_es else 0.0
    nq_mid = get_field(bar_nq, "price_vs_swing_mid", 0.0) if bar_nq else 0.0

    # Correlation multi-facteurs : swing_mid + delta_dir + range_pos
    es_rpos = get_field(bar_es, "range_pos", 50.0) if bar_es else 50.0
    nq_rpos = get_field(bar_nq, "range_pos", 50.0) if bar_nq else 50.0
    # Normaliser range_pos de 0-100 vers -1..+1
    es_rn = (es_rpos - 50) / 50
    nq_rn = (nq_rpos - 50) / 50
    # Score concordance sur 3 facteurs
    mid_agree = 1.0 if es_mid * nq_mid > 0 else (-1.0 if es_mid * nq_mid < 0 else 0.0)
    dir_agree = 1.0 if es_dir == nq_dir and es_dir != 0 else (-1.0 if es_dir != 0 and nq_dir != 0 and es_dir != nq_dir else 0.0)
    rpos_agree = es_rn * nq_rn  # produit : meme cote = positif
    corr = round(0.4 * mid_agree + 0.3 * dir_agree + 0.3 * min(1.0, max(-1.0, rpos_agree * 2)), 3)
    corr = round(corr, 3)

    return {
        "cross_delta_agreement": cross_delta,
        "smt_divergence": smt,
        "smt_direction": smt_direction,
        "smt_detail": smt_detail,
        "momentum_divergence": momentum_div,
        "range_pos_gap": round(range_pos_gap, 1),
        "rolling_correlation": corr,
        "price_ratio": ratio,
        "volume_lead": vol_lead,
        "ltr_diff": round(es_ltr - nq_ltr, 4),
        "es_rvol": round(es_rvol, 4),
        "nq_rvol": round(nq_rvol, 4),
        "es_delta_dir": es_dir,
        "nq_delta_dir": nq_dir,
        "es_range_pos": round(es_range_pos, 1),
        "nq_range_pos": round(nq_range_pos, 1),
    }


# ═══════════════════════════════════════════════════════════════
# Builder 13 : Advisory / Conseils educatifs
# ═══════════════════════════════════════════════════════════════


def build_advisory(regime: dict, session_open: dict) -> dict:
    """Genere les conseils educatifs : QUI A LA MAIN, FAVORISER, conseils."""
    if not regime:
        return {"conseils": [], "favor": "NEUTRE", "qui_a_la_main": "PERSONNE"}

    bias = regime.get("bias", "NEUTRAL")
    mode = regime.get("mode", "NORMAL")
    favor = regime.get("favor", "NEUTRE")
    vol = regime.get("vol_regime", "NORMAL")
    score = regime.get("bias_score", 0.0)

    # Qui a la main
    if abs(score) > 0.5:
        qui = "ACHETEURS" if score > 0 else "VENDEURS"
        force = "FORTE"
    elif abs(score) > 0.25:
        qui = "ACHETEURS" if score > 0 else "VENDEURS"
        force = "MODEREE"
    else:
        qui = "PERSONNE"
        force = "EQUILIBRE"

    conseils = []

    # Session
    session_label = session_open.get("session_label", "Closed") if session_open else "N/A"
    if session_label == "US":
        conseils.append({
            "type": "ok",
            "text": f"Session US active — Meilleure liquidite, ideal pour trader",
        })
    elif session_label in ("Asia", "London"):
        conseils.append({
            "type": "warn",
            "text": f"Session {session_label} — Liquidite reduite, spreads plus larges",
        })
    else:
        conseils.append({
            "type": "danger",
            "text": "Hors session — NE PAS TRADER",
        })

    # Volatilite
    if vol == "EXTREME":
        conseils.append({
            "type": "danger",
            "text": "VOLATILITE EXTREME — Reduire la taille, elargir les stops",
        })
    elif vol == "HIGH":
        conseils.append({
            "type": "warn",
            "text": "Volatilite elevee — Prudence, stops elargis recommandes",
        })
    elif vol == "LOW":
        conseils.append({
            "type": "info",
            "text": "Volatilite basse — Targets reduits, patience requise",
        })

    # Mode
    if mode == "TREND":
        conseils.append({
            "type": "ok",
            "text": f"Mode TREND — Suivre la direction ({favor}), pas de fade",
        })
    elif mode == "RANGE":
        conseils.append({
            "type": "info",
            "text": "Mode RANGE — Fader les extremes, eviter le milieu du range",
        })
    else:
        conseils.append({
            "type": "info",
            "text": "Mode NORMAL — Chercher des confluences de niveaux",
        })

    # Divergence override — une div FORTE/EXTREME au bord du range
    # prime sur le bias classique (Mark Douglas : le casino joue son edge)
    # MAIS ne pas fade un breakout en mode TREND
    div_active = regime.get("div_active", False)
    div_grade = regime.get("div_grade", "NONE")
    div_quality = regime.get("div_quality", 0)
    range_pos = regime.get("range_pos", 50)
    reg_mode = regime.get("mode", "NORMAL")

    # En mode TREND, pas de divergence contrarian
    if div_grade in ("EXTREME", "FORTE") and (range_pos >= 80 or range_pos <= 20) and reg_mode != "TREND":
        if range_pos >= 80:
            favor = "SHORT"
            regime["favor"] = "SHORT"  # Propager au regime pour coherence
            conseils.append({
                "type": "danger",
                "text": f"DIVERGENCE {div_grade} ({div_quality:.0f}/10) — Prix au TOP du range "
                        f"({range_pos:.0f}%), le flow ne confirme PAS la montee. FAVORISER SHORT.",
            })
        else:
            favor = "LONG"
            regime["favor"] = "LONG"  # Propager au regime pour coherence
            conseils.append({
                "type": "danger",
                "text": f"DIVERGENCE {div_grade} ({div_quality:.0f}/10) — Prix au BOTTOM du range "
                        f"({range_pos:.0f}%), le flow ne confirme PAS la baisse. FAVORISER LONG.",
            })
    elif div_active and div_grade == "MODEREE":
        conseils.append({
            "type": "warn",
            "text": f"Divergence detectee ({div_quality:.0f}/10) mais contexte insuffisant — "
                    "NE PAS trader sur ce signal seul",
        })
    elif div_active and div_grade == "FAIBLE":
        conseils.append({
            "type": "info",
            "text": "Divergence faible detectee — surveiller si le contexte se renforce",
        })

    # Direction (apres override eventuel par la div)
    if favor == "LONG":
        conseils.append({
            "type": "ok",
            "text": "FAVORISER ACHAT — Le biais est haussier, chercher des longs sur support",
        })
    elif favor == "SHORT":
        conseils.append({
            "type": "ok",
            "text": "FAVORISER VENTE — Le biais est baissier, chercher des shorts sur resistance",
        })
    else:
        conseils.append({
            "type": "warn",
            "text": "PAS DE DIRECTION CLAIRE — Attendre un signal ou une cassure",
        })

    # Open type
    if session_open:
        ot = session_open.get("open_type_label", "")
        if "OD" in ot:
            conseils.append({
                "type": "info",
                "text": f"Open Drive ({ot}) — Forte conviction directionnelle a l'open",
            })
        elif "OTD" in ot:
            conseils.append({
                "type": "info",
                "text": f"Open Test Drive ({ot}) — Test d'un niveau puis continuation",
            })

    return {
        "qui_a_la_main": qui,
        "force": force,
        "favor": favor,
        "bias": bias,
        "mode": mode,
        "vol_regime": vol,
        "conseils": conseils,
    }


# ═══════════════════════════════════════════════════════════════
# Gamma Gate — positionnement options (MenthorQ walls + GEX)
# ═══════════════════════════════════════════════════════════════
#
# Regle Jackson (mentor) : "Mieux vaut avoir moins de recommandations a
# trader que de trader contre le flux institutionnel."
#
# Architecture : cap absolu au lieu de penalite graduee.
#   - Si le prix est proche d'un call wall MQ (seuil adaptatif ATR),
#     bull_pts est cape a 3 → impossible d'atteindre "ACHAT" (besoin 4+).
#   - Idem symetrique pour put support.
#   - GEX flip zone = regime change dealer → cap les deux cotes.
#
# Propriete mathematique garantie : jamais de reco ACHAT/VENTE en presence
# d'un mur proche, quel que soit le score des 6 autres signaux.
#
# Reference : audit dashboard 2026-04-13 (agent Explore) + review plan
# gamma gate 2026-04-13 (code-reviewer).


# Gamma gate — constantes (AT modifiable via PR si recalibration necessaire)
_GAMMA_THRESHOLD_MIN_TICKS: float = 10.0   # plancher seuil (evite desactiver sur ATR bas)
_GAMMA_THRESHOLD_MAX_TICKS: float = 80.0   # plafond seuil (evite derive sur ATR extreme)
_GAMMA_THRESHOLD_ATR_RATIO: float = 0.5    # seuil = 0.5 × ATR (demi range de barre typique)
_GAMMA_CAP_BULL_BEAR: int = 4              # cap applique sur bull_pts / bear_pts si mur proche
# FIX 28/04 13:15 (Jackson "deploy toutes sessions") :
# Ancien cap=3 forcait verdict ATTENDRE 100% en zone gamma car ACHAT PRUDENT
# necessite bull_pts >= 4. Nouveau cap=4 permet ACHAT PRUDENT mais bloque ACHAT
# (>= 5). Garde la philosophie "moins de recos > contre-trader" tout en
# permettant signaux modestes en zone gamma.
_GAMMA_DEFAULT_ATR: float = 30.0           # fallback ATR si absent de la barre


def _gamma_gate_check(
    bar: dict,
    options: Optional[dict],
) -> Tuple[bool, bool, List[str]]:
    """Check gamma gate : renvoie (block_long, block_short, warnings).

    Logique :
      - block_long  = True si le prix est proche d'un call wall MQ
        ou dans une zone GEX flip. Signal : ne pas recommander LONG.
      - block_short = True idem pour put support.
      - warnings = liste de strings explicatifs a afficher au user.

    Gestion de la sentinelle 0.0 ambigue (DMP retourne 0.0 quand mur
    absent OU quand prix pile sur le mur) :
      - On considere `0 < dist < threshold` comme "mur proche mais pas dessus"
      - On considere `dist == 0` avec un prix absolu pour le mur
        (`call_wall_price` / `put_wall_price`) non null comme "pile dessus"
        → block = True (cas le plus critique, ne JAMAIS passer a cote).

    Args:
        bar     : barre JSONL courante (pour lire ATR)
        options : dict retourne par build_options_levels() — peut etre None.
                  Si None → aucun blocage (rétro-compat).

    Returns:
        (block_long, block_short, warnings)
    """
    if not options:
        return False, False, []

    # Seuil adaptatif proportionnel a l'ATR, borne [10, 80]
    atr = get_field(bar, "atr", _GAMMA_DEFAULT_ATR) or _GAMMA_DEFAULT_ATR
    threshold = max(
        _GAMMA_THRESHOLD_MIN_TICKS,
        min(_GAMMA_THRESHOLD_MAX_TICKS, atr * _GAMMA_THRESHOLD_ATR_RATIO),
    )

    block_long = False
    block_short = False
    warnings: List[str] = []

    call_dist = options.get("dist_mq_call", 0.0) or 0.0
    put_dist = options.get("dist_mq_put", 0.0) or 0.0
    call_wall_price = options.get("call_wall_price")
    put_wall_price = options.get("put_wall_price")
    gex_flip = options.get("gex_flip_zone", 0)

    # Call wall : proche (dist > 0) OU pile dessus (dist == 0 + prix absolu present)
    call_near = 0 < call_dist <= threshold
    call_on = call_dist == 0.0 and call_wall_price is not None
    if call_near or call_on:
        block_long = True
        if call_on:
            warnings.append("GAMMA: prix PILE sur CALL WALL MQ")
        else:
            warnings.append(f"GAMMA: CALL WALL a {call_dist:.0f}t (seuil {threshold:.0f}t)")

    # Put support : idem symetrique
    put_near = 0 < put_dist <= threshold
    put_on = put_dist == 0.0 and put_wall_price is not None
    if put_near or put_on:
        block_short = True
        if put_on:
            warnings.append("GAMMA: prix PILE sur PUT SUPPORT MQ")
        else:
            warnings.append(f"GAMMA: PUT SUPPORT a {put_dist:.0f}t (seuil {threshold:.0f}t)")

    # GEX flip zone = regime dealer instable, bloque les deux cotes
    if gex_flip:
        block_long = True
        block_short = True
        warnings.append("GAMMA: GEX FLIP ZONE — regime dealer instable")

    return block_long, block_short, warnings


# ═══════════════════════════════════════════════════════════════
# Builder : Conseil Global (meme logique que le JS renderGlobalAdvice)
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# Signal State Tracker — fix bug critique signal persistance (22/04)
# ═══════════════════════════════════════════════════════════════
# Bug identifie par Jackson : signal ACHAT emis a 9h00 affiche "ACHAT"
# pendant plusieurs barres (9h05, 9h15 etc) car conditions toujours
# vraies. Humain croit voir nouveau signal → FOMO trade late = perdant.
# Fix : distinguer EVENEMENT (transition False→True) de ETAT (persistance).
#
# UPDATE 05/05/2026 (Option B audit market-analyst + empirique 188 EXPIRED NQ
# avec raw_active aujourd'hui) : DISSOCIER seuil DISPLAY (UI anti-FOMO) du
# seuil EXECUTION (gate paper tradabilite).
#   - DISPLAY=2 : UI affiche "EXPIRED" apres 2 bars (bug 22/04 reste corrige)
#   - EXECUTION=4 : gate paper accepte le signal jusqu'a 4 bars (debloque
#     ~half des candidats raw_active EXPIRED qui etaient etouffes)
#   Le bot 1 lit `executable_action` (basee sur freshness_exec), pas `action`
#   (basee sur freshness_display).
_SIGNAL_STATE = {}  # {symbol: {"action": str, "first_bar_ts": int, "signal_id": str, "last_seen_ts": int}}
_MAX_SIGNAL_AGE_BARS_DISPLAY = 2    # UI : EXPIRED apres 2 bars (timeframe 1min) — anti-FOMO affichage
_MAX_SIGNAL_AGE_BARS_EXECUTION = 4  # Gate paper : EXPIRED apres 4 bars — anti-chase late entry
# Backward-compat alias (deprecated, garde pour eviter casser un import externe)
_MAX_SIGNAL_AGE_BARS = _MAX_SIGNAL_AGE_BARS_DISPLAY


def _evaluate_signal_freshness(symbol: str, action: str, bar_ts_ms: int) -> dict:
    """State machine transition vs persistance.

    Retourne dict avec 2 freshness :
      - freshness     = UI display (seuil DISPLAY=2 bars)
      - freshness_exec = gate paper (seuil EXECUTION=4 bars)
    Plus age_bars + signal_id partages.

    Etats possibles (chaque freshness independamment) :
      NEW        = transition ATTENDRE/autre → signal actif (evenement tradable)
      PERSISTENT = meme signal, age 1-MAX → encore affichable mais pas tradable
      EXPIRED    = meme signal, age > MAX → action forcee ATTENDRE, pas tradable
      IDLE       = pas de signal (ATTENDRE/CONFLIT)
    """
    import uuid as _uuid
    prev = _SIGNAL_STATE.get(symbol, {"action": "ATTENDRE", "first_bar_ts": 0, "signal_id": None, "last_seen_ts": 0})

    is_active = action in ("ACHAT", "VENTE", "ACHAT PRUDENT", "VENTE PRUDENTE")

    if not is_active:
        _SIGNAL_STATE[symbol] = {"action": action, "first_bar_ts": 0, "signal_id": None, "last_seen_ts": bar_ts_ms}
        return {"freshness": "IDLE", "freshness_exec": "IDLE", "age_bars": 0, "signal_id": None}

    if action != prev["action"]:
        new_id = _uuid.uuid4().hex[:8]
        _SIGNAL_STATE[symbol] = {"action": action, "first_bar_ts": bar_ts_ms, "signal_id": new_id, "last_seen_ts": bar_ts_ms}
        return {"freshness": "NEW", "freshness_exec": "NEW", "age_bars": 0, "signal_id": new_id}

    age_bars = int((bar_ts_ms - prev["first_bar_ts"]) / 60000)
    if age_bars == 0:
        fresh_display = "NEW"
        fresh_exec = "NEW"
    else:
        fresh_display = "PERSISTENT" if age_bars <= _MAX_SIGNAL_AGE_BARS_DISPLAY else "EXPIRED"
        fresh_exec = "PERSISTENT" if age_bars <= _MAX_SIGNAL_AGE_BARS_EXECUTION else "EXPIRED"
    _SIGNAL_STATE[symbol] = {**prev, "last_seen_ts": bar_ts_ms}
    return {
        "freshness": fresh_display,
        "freshness_exec": fresh_exec,
        "age_bars": age_bars,
        "signal_id": prev["signal_id"],
    }


def build_conseil_global(
    bar: dict,
    regime: dict,
    options: Optional[dict] = None,
) -> dict:
    """Calcule le Conseil Global — verdict final ACHAT/VENTE/ATTENDRE/CONFLIT.

    Integre le gamma gate via cap absolu sur bull_pts / bear_pts quand
    options != None et qu'un mur MQ est proche (voir `_gamma_gate_check`).
    Le parametre `options` est optionnel pour retro-compatibilite — les
    anciens appelants continueront de fonctionner sans gamma gate.

    v1.5 (22/04) : ajoute freshness (NEW/PERSISTENT/EXPIRED/IDLE) + signal_id
    + age_bars pour distinguer evenement (transition) de etat (persistance).
    Fix bug signal ACHAT affiche pendant 15 min (Jackson directive).
    """
    if not bar or not regime:
        return {"action": "ATTENDRE", "bull_points": 0, "bear_points": 0, "reason": "pas de donnees",
                "freshness": "IDLE", "age_bars": 0, "signal_id": None}

    bull_pts = 0
    bear_pts = 0
    checks = []

    # 1. Bias regime (poids 2)
    bias = regime.get("bias", "NEUTRAL")
    if bias == "BULLISH":
        bull_pts += 2
    elif bias == "BEARISH":
        bear_pts += 2
    checks.append(f"Bias: {bias}")

    # 2. Delta direction jour
    delta_dir = get_int_field(bar, "delta_day_dir", 0)
    if delta_dir > 0:
        bull_pts += 1
    elif delta_dir < 0:
        bear_pts += 1
    checks.append(f"Delta: {'acheteurs' if delta_dir > 0 else 'vendeurs' if delta_dir < 0 else 'neutre'}")

    # 3. RVOL (informatif, pas de points)
    rvol = get_field(bar, "rvol", 0)
    checks.append(f"RVOL: {rvol:.1f}x")

    # 4. Position range — seuils alignes avec build_regime_context (80/20)
    pos = regime.get("range_pos", 50)
    if pos <= 20:
        bull_pts += 1
    elif pos >= 80:
        bear_pts += 1
    checks.append(f"Range: {pos:.0f}%")

    # 5. MTF (poids 2 si 4/4, 1 si 3/4, 1 si 2/4 — fix 28/04 marche indecis)
    # FIX 28/04 (Jackson "deploy toutes sessions Asia/Londres/US") :
    # ancien seuil >= 3 trop strict marche neutral (NEUTRAL bias 40% bars 27/04 = 0 pts MTF).
    # Nouveau seuil >= 2 donne 1 pt → permet bull_pts atteindre 4 (ACHAT PRUDENT eligible).
    # 24/04 (PF 2.64) avait MTF >= 3 fréquemment, le fix ne casse pas cette journée.
    # 27/04 marche indecis : 735 bars bull=3 deviendraient bull=4 → ~50 candidats post-filtres aval.
    mtf_bulls = regime.get("mtf_bulls", 0)
    mtf_bears = regime.get("mtf_bears", 0)
    if mtf_bulls >= 2:
        mtf_w = 2 if mtf_bulls == 4 else 1
        bull_pts += mtf_w
    if mtf_bears >= 2:
        mtf_w = 2 if mtf_bears == 4 else 1
        bear_pts += mtf_w
    checks.append(f"MTF: {regime.get('mtf_verdict', 'N/A')}")

    # 6. Divergence forte (poids 2) — seuils alignes 80/20
    div_grade = regime.get("div_grade", "NONE")
    if div_grade in ("EXTREME", "FORTE"):
        if pos <= 20:
            bull_pts += 2
        elif pos >= 80:
            bear_pts += 2
    checks.append(f"DIV: {div_grade}")

    # 7. Gamma gate — cap absolu (regle Jackson : "moins de recos > contre-trader")
    # Applique APRES les 6 signaux, AVANT le verdict. Garantit qu'un mur proche
    # force ATTENDRE quel que soit le score des autres signaux.
    block_long, block_short, gamma_warnings = _gamma_gate_check(bar, options)
    if block_long:
        bull_pts = min(bull_pts, _GAMMA_CAP_BULL_BEAR)
    if block_short:
        bear_pts = min(bear_pts, _GAMMA_CAP_BULL_BEAR)
    checks.extend(gamma_warnings)

    # NOTE 04/05 : widgets V4 (cluster_signal, big_signal, smt_signal, npoc_signal)
    # restent en MODE OBSERVE-ONLY (verdict market-analyst NOGO Phase 3 directe).
    # Le swap Option 1 (sources live au lieu de mortes) est applique cote
    # build_order_flow_advanced pour exposition dashboard. Les compteurs cumulatifs
    # sont logges via _observe_v4_widgets dans mia_paper_trader (Bot 1) pour
    # audit J+7 + walk-forward DSR avant integration en gate (Phase 3).
    # Cf market-analyst audit 04/05 : "NOGO sur Phase 3 immediate (3/4 features
    # avec problemes empiriques). GO Phase 1 OBSERVE-ONLY 60 jours avant decision".

    # PATCH 22/04/2026 : Ajout BN footprint events aux checks (visibilite trader)
    # Ne modifie PAS bull_pts/bear_pts (pour eviter pattern 11 hardcoded).
    # Audit market-analyst 22/04 : v2 enrichi degrade PF -> on garde v1 pondere,
    # on ajoute juste les events BN comme CONTEXTE dans la deroulante.
    bn_color_up = get_int_field(bar, "bn_color_up", 0)
    bn_color_dn = get_int_field(bar, "bn_color_dn", 0)
    bn_long_up = get_int_field(bar, "bn_long_up", 0)
    bn_long_dn = get_int_field(bar, "bn_long_dn", 0)
    bn_absorb_bid = get_int_field(bar, "bn_absorb_bid", 0)
    bn_absorb_ask = get_int_field(bar, "bn_absorb_ask", 0)
    bn_bull = bn_color_up + bn_long_up + bn_absorb_bid
    bn_bear = bn_color_dn + bn_long_dn + bn_absorb_ask
    if bn_bull > 0 or bn_bear > 0:
        bn_parts = []
        if bn_color_up: bn_parts.append("color_up")
        if bn_long_up: bn_parts.append("long_up")
        if bn_absorb_bid: bn_parts.append("absorb_bid")
        if bn_color_dn: bn_parts.append("color_dn")
        if bn_long_dn: bn_parts.append("long_dn")
        if bn_absorb_ask: bn_parts.append("absorb_ask")
        checks.append(f"BN events ({bn_bull}+/{bn_bear}-): {' '.join(bn_parts)}")

    # Verdict
    conflict = bull_pts >= 3 and bear_pts >= 3
    if conflict:
        action = "CONFLIT"
    elif bull_pts >= 5 and bear_pts <= 2:
        action = "ACHAT"
    elif bear_pts >= 5 and bull_pts <= 2:
        action = "VENTE"
    elif bull_pts >= 4 and bear_pts <= 2:
        action = "ACHAT PRUDENT"
    elif bear_pts >= 4 and bull_pts <= 2:
        action = "VENTE PRUDENTE"
    else:
        action = "ATTENDRE"

    # PATCH 22/04/2026 → LEVE 24/04/2026 : SELL ré-activé (paper seulement).
    #
    # HISTORIQUE :
    #   22/04 : Jackson bust Topstep LIVE sur trade SELL (news imprevue). Audit
    #     market-analyst 22/04 → PF SELL=0.00 ES (0/6 wins), PF 0.60 NQ.
    #     Decision : SELL DISABLED en attendant validation v4 propre mi-mai.
    #   24/04 (ce soir) : analyse 23/04 montre 0 trade pris journee complete
    #     (4026 polls → 3884 conseil_attendre). Cause : NQ baisse 400pt +
    #     ES baisse 60pt → 50-70% des signaux etaient SELL → tous etouffes.
    #     Base statistique 6 trades = Bayesien inutilisable (IC95% enorme).
    #
    # DECISION 24/04 (Jackson valide + Claude audit) :
    #   Re-activer SELL EN PAPER UNIQUEMENT pour collecter distribution WR/PF
    #   empirique propre. On est deja sous safety nets multiples :
    #     - DTC Sim3 (pas de $ reel)
    #     - Paper trader (pas de routing broker)
    #     - Gates bias + SLTP + payoff toujours actifs en aval
    #
    # CONDITION DE RE-DESACTIVATION (auto) :
    #   Si apres N>=50 trades SELL empiriques : PF_sell < 0.5 ET WR_sell < 0.40
    #   → re-disable. Monitoring manuel chaque fin de journee + review vendredi.
    #
    # TODO V2CLEAN : deplacer ce flag dans V2CLEAN/config.py comme
    #   ENABLE_SELL_PAPER=True / ENABLE_SELL_LIVE=False pour separer proprement.
    # Cf memory feedback_config_centralise.md.
    if action in ("VENTE", "VENTE PRUDENTE"):
        checks.append(f"SELL active (paper, re-activation 24/04 pour collecte stats)")
        checks.append(f"  Si PF<0.5 apres N>=50 SELL → re-disable auto")

    # v1.5 (22/04) State machine transition vs persistance
    # v2 (05/05) Option B : seuils dissocies DISPLAY (2 bars) vs EXECUTION (4 bars)
    symbol_key = str(bar.get("sym", "UNKNOWN")).upper()
    bar_ts_ms = int(bar.get("ts", 0))
    # R2 code-reviewer 05/05 : fail-loud si sym manque. Sans ce guard, tous les
    # symbols UNKNOWN partagent le meme _SIGNAL_STATE -> corruption cross-symbol
    # (un signal NQ ecrase un signal ES si tous les deux UNKNOWN).
    if symbol_key == "UNKNOWN":
        return {
            "action": "ATTENDRE", "executable_action": "ATTENDRE",
            "bull_points": 0, "bear_points": 0,
            "reason": "bar.sym manquant",
            "checks": ["bar.sym manquant — fail-loud guard R2"],
            "gamma_block_long": False, "gamma_block_short": False,
            "freshness": "IDLE", "freshness_exec": "IDLE",
            "age_bars": 0, "signal_id": None, "raw_action": "ATTENDRE",
        }
    state = _evaluate_signal_freshness(symbol_key, action, bar_ts_ms)

    # display_action (UI) : EXPIRED apres 2 bars → ATTENDRE (anti-FOMO 22/04)
    if state["freshness"] == "EXPIRED":
        checks.append(f"SIGNAL EXPIRE UI apres {state['age_bars']} barres (max display {_MAX_SIGNAL_AGE_BARS_DISPLAY})")
        display_action = "ATTENDRE"
    else:
        display_action = action

    # executable_action (gate paper) : EXPIRED apres 4 bars → ATTENDRE
    # Le bot lit ce champ (pas `action`) → debloque ~half des candidats stables
    # qui etaient etouffes par la limite UI 2 bars (audit empirique 188 NQ 05/05).
    if state["freshness_exec"] == "EXPIRED":
        executable_action = "ATTENDRE"
    else:
        executable_action = action

    return {
        "action": display_action,                # UI (legacy, dashboard)
        "executable_action": executable_action,  # Gate paper (Bot 1, V6, etc.)
        "bull_points": bull_pts,
        "bear_points": bear_pts,
        "reason": f"{bull_pts} bull / {bear_pts} bear",
        "checks": checks,
        "gamma_block_long": block_long,
        "gamma_block_short": block_short,
        "freshness": state["freshness"],          # UI freshness
        "freshness_exec": state["freshness_exec"],# Gate freshness
        "age_bars": state["age_bars"],
        "signal_id": state["signal_id"],
        "raw_action": action,  # action avant expiration (pour debug)
    }


# ═══════════════════════════════════════════════════════════════
# Builder 14 : Trade Suggestion
# ═══════════════════════════════════════════════════════════════


def build_trade_suggestion(bar: dict, symbol: str, regime: dict, options: dict) -> dict:
    """Suggestion de trade + checklist pre-trade.

    Integre le gamma gate en check #7 : si le prix est proche d'un mur MQ
    du cote de la direction favoree (LONG vs call wall, SHORT vs put), la
    check echoue → grade degrade → has_signal = False.

    Regle Jackson : "mieux vaut moins de signaux que trader contre le flux".
    """
    if not bar or not regime:
        return {"has_signal": False}

    favor = regime.get("favor", "NEUTRE")
    mode = regime.get("mode", "NORMAL")
    vol = regime.get("vol_regime", "NORMAL")
    bias_conf = regime.get("bias_confidence", 0.0)

    # Checklist pre-trade
    checks = []

    # 1. Session tradable?
    session = get_str_field(bar, "session_id", "N/A")
    is_us = session == "US"
    checks.append({"name": "Session US", "ok": is_us})

    # 2. VIX pas extreme
    vix = get_field(bar, "vix_level", 0.0)
    vix_ok = 12 < vix < 35
    checks.append({"name": f"VIX acceptable ({vix:.1f})", "ok": vix_ok})

    # 3. Volatilite pas extreme
    vol_ok = vol != "EXTREME"
    checks.append({"name": f"Volatilite {vol}", "ok": vol_ok})

    # 4. Direction claire
    dir_ok = favor in ("LONG", "SHORT")
    checks.append({"name": f"Direction: {favor}", "ok": dir_ok})

    # 5. Pas de divergence prix/delta
    div = get_int_field(bar, "delta_divergence", 0)
    checks.append({"name": "Pas de divergence P/D", "ok": div == 0})

    # 6. Confidence suffisante
    conf_ok = bias_conf >= 0.4
    checks.append({"name": f"Confidence {bias_conf:.0%}", "ok": conf_ok})

    # 7. Gamma gate — options positioning (ajoute si options fournis)
    # On utilise la meme logique que build_conseil_global pour coherence.
    if options:
        block_long, block_short, _gamma_warnings = _gamma_gate_check(bar, options)
        if favor == "LONG" and block_long:
            checks.append({"name": "Gamma: mur CALL proche", "ok": False})
        elif favor == "SHORT" and block_short:
            checks.append({"name": "Gamma: support PUT proche", "ok": False})
        else:
            checks.append({"name": "Gamma: clair", "ok": True})

    # SL/TP adaptatifs
    atr = get_field(bar, "atr", 0.0)
    sl_ticks = round(atr * 0.08, 1) if atr > 0 else 10.0
    tp_ticks = round(sl_ticks * 2.0, 1)
    price = get_field(bar, "price", 0.0)

    # 11/05 J2b MGC : tick par symbole (ES/NQ=0.25, MGC=0.10).
    # _tick_for(symbol) fallback TICK_SIZE si symbole inconnu = ES/NQ inchanges.
    _tick = _tick_for(symbol)
    if favor == "LONG":
        sl_price = round(price - sl_ticks * _tick, 2)
        tp_price = round(price + tp_ticks * _tick, 2)
    elif favor == "SHORT":
        sl_price = round(price + sl_ticks * _tick, 2)
        tp_price = round(price - tp_ticks * _tick, 2)
    else:
        sl_price = None
        tp_price = None

    passed = sum(1 for c in checks if c["ok"])
    total = len(checks)
    # Grade dynamique adapte au nombre de checks (6 ou 7 selon options fournis)
    # Seuils relatifs au total pour eviter une regression "A → B" juste parce
    # qu'on a ajoute une 7e check.
    if passed == total:
        grade = "A"
    elif passed >= total - 1:
        grade = "B"
    elif passed >= total - 2:
        grade = "C"
    else:
        grade = "D"

    # Gamma gate hard-fail : si le check gamma est rouge, on refuse le signal
    # meme si le grade reste B. Coherent avec la regle Jackson "moins de
    # signaux > contre-trader le flux institutionnel".
    gamma_failed = any(
        c["name"].startswith("Gamma:") and not c["ok"] for c in checks
    )
    has_signal = (
        grade in ("A", "B")
        and dir_ok
        and conf_ok
        and not gamma_failed
    )

    action = "GO" if has_signal else "WAIT" if grade in ("B", "C") else "NO TRADE"

    return {
        "has_signal": has_signal,
        "action": action,
        "grade": grade,
        "direction": favor,
        "checks": checks,
        "passed": passed,
        "total": total,
        "sl_ticks": sl_ticks,
        "tp_ticks": tp_ticks,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "rr": 2.0,
    }


# ═══════════════════════════════════════════════════════════════
# Builder 15 : Signals Journal (depuis bot JSON)
# ═══════════════════════════════════════════════════════════════


def build_signals_journal(bot_data: dict) -> dict:
    """Signaux et journal depuis le dashboard JSON du bot."""
    sj = bot_data.get("signals_journal", {})
    return {
        "current_signal": sj.get("current_signal"),
        "signal_score": sj.get("signal_score"),
        "signal_reason": sj.get("signal_reason", ""),
        "sl_ticks": sj.get("sl_ticks"),
        "tp_ticks": sj.get("tp_ticks"),
        "rr_ratio": sj.get("rr_ratio"),
        "recent_trades": sj.get("recent_trades", []),
        "recent_rejections": sj.get("recent_rejections", []),
    }


# ═══════════════════════════════════════════════════════════════
# Builder MANUAL INDICATORS (Jackson trading manuel — 04/05/2026)
# Audit market-analyst : top 6 indicateurs pertinents pour decision <5s
# Phase 1 = quick wins
# ═══════════════════════════════════════════════════════════════


def build_manual_indicators(bar: dict) -> dict:
    """Indicateurs trading manuel pour Jackson — decision <5s.

    Phase 1 (4 widgets) :
      A. VWAP triple align + slope direction
      B. RVOL zscore (gauge -2/+3)
      C. Delta divergence clean (badge BUY/SELL/OFF + force)
      D. Next wall distance + side (MenthorQ)

    Phase 3 (filtre conditionnel) :
      E. Trapped @ niveau (banner alert si proche niveau)
      F. POC migration vitesse + position

    Cf market-analyst audit 04/05 + memory feedback_extraction_expertise_jackson.
    """
    if not bar:
        return {}

    # ─── A. VWAP triple align + slope ────────────────────────────
    vwap_d_side = get_int_field(bar, "vwap_d_side", 0)  # +1/-1
    vwap_w_side = get_int_field(bar, "vwap_w_side", 0)
    vwap_m_side = get_int_field(bar, "vwap_m_side", 0)
    vwap_triple_align = get_int_field(bar, "vwap_triple_align", 0)  # 1 si tous alignes
    vwap_slope_10 = get_field(bar, "vwap_slope_10", 0.0)
    vwap_slope_10_dir = get_int_field(bar, "vwap_slope_10_dir", 0)  # +1/0/-1

    # ─── B. RVOL zscore ──────────────────────────────────────────
    rvol = get_field(bar, "rvol", 0.0)
    rvol_zscore = get_field(bar, "rvol_zscore", 0.0)
    # Classification visuelle
    if rvol_zscore >= 2.0:
        rvol_zone = "EXCEPTIONAL"      # vert vif
    elif rvol_zscore >= 1.0:
        rvol_zone = "ELEVATED"         # vert
    elif rvol_zscore >= -0.5:
        rvol_zone = "NORMAL"           # gris
    else:
        rvol_zone = "LOW"              # rouge (no-trade)

    # ─── C. Delta divergence (DMP brut + V4 enrichi 04/05) ────────
    # `delta_divergence` est dans DMP brut (signe +1/-1/0) ET dans V4.
    # V4 enrichit avec `n_delta_div_*_zones_active` pour mesurer la force.
    # Les cles DMP `_clean` n'existent pas (audit R5), donc on utilise
    # le brut + zones V4 quand dispo.
    div_value = get_int_field(bar, "delta_divergence", 0)  # +1/-1/0
    n_div_buy_zones = get_int_field(bar, "n_delta_div_buy_zones_active", 0)   # V4 only
    n_div_sell_zones = get_int_field(bar, "n_delta_div_sell_zones_active", 0)  # V4 only
    n_div_zones = n_div_buy_zones + n_div_sell_zones
    if n_div_zones > 0:
        # V4 frais : force basee sur nombre de zones actives (proxy intensite)
        div_strength = min(n_div_zones * 25.0, 100.0)  # cap 4 zones
    elif div_value != 0:
        # DMP seul : signal binaire, force conservatrice 50
        div_strength = 50.0
    else:
        div_strength = 0.0
    if div_value > 0 and div_strength >= 25:
        div_signal = "BUY"
    elif div_value < 0 and div_strength >= 25:
        div_signal = "SELL"
    else:
        div_signal = "OFF"

    # ─── D. Next wall (V4/DMP : convention DMP_Transform.h:508) ───────
    # CalcDistTicks = (level - price) / tick_size (DEJA EN TICKS dans le JSONL).
    # Convention : dist > 0 = level au-dessus (resistance), dist < 0 = en-dessous (support).
    # Mur valide :
    #   - CALL au-dessus (dist_mq_call > 0) = vraie resistance
    #   - PUT en-dessous (dist_mq_put < 0) = vrai support
    # Sinon le strike est ITM (pas un mur exploitable).
    # Fallback DMP `next_wall_*` si V4 absent ou aucun mur cote correct.
    dist_mq_call = get_field(bar, "dist_mq_call", 0.0)   # deja en ticks
    dist_mq_put = get_field(bar, "dist_mq_put", 0.0)
    # Garder seulement les murs exploitables (call above, put below)
    call_dist_ticks = dist_mq_call if dist_mq_call > 0 else 99999.0
    put_dist_ticks = abs(dist_mq_put) if dist_mq_put < 0 else 99999.0
    if call_dist_ticks < 99999.0 or put_dist_ticks < 99999.0:
        if call_dist_ticks <= put_dist_ticks:
            next_wall_dist_ticks = call_dist_ticks
            next_wall_is_call = 1
        else:
            next_wall_dist_ticks = put_dist_ticks
            next_wall_is_call = 0
    else:
        # Aucun mur cote correct -> Fallback DMP (deja signe-aware)
        next_wall_dist_ticks = get_field(bar, "next_wall_dist_ticks", 0.0)
        next_wall_is_call = get_int_field(bar, "next_wall_is_call", 0)
    wall_side = "CALL" if next_wall_is_call else "PUT"
    wall_reaction_zone = abs(next_wall_dist_ticks) <= 8.0 if next_wall_dist_ticks else False

    # ─── E. Trapped @ niveau (Phase 3) ───────────────────────────
    trapped_buyers_at_res = get_int_field(bar, "bn_trapped_buyers_at_resistance", 0)
    trapped_sellers_at_sup = get_int_field(bar, "bn_trapped_sellers_at_support", 0)
    n_trap_buy_zones = get_int_field(bar, "n_trapped_buyers_zones_active", 0)
    n_trap_sell_zones = get_int_field(bar, "n_trapped_sellers_zones_active", 0)
    if trapped_buyers_at_res:
        trapped_signal = "TRAPPED_BUYERS"   # bias SHORT (acheteurs piéges en haut)
    elif trapped_sellers_at_sup:
        trapped_signal = "TRAPPED_SELLERS"  # bias LONG (vendeurs piéges en bas)
    else:
        trapped_signal = "OFF"

    # ─── F. POC migration vitesse + position (Phase 3) ───────────
    poc_mig_dir = get_int_field(bar, "poc_migration_dir", 0)
    poc_mig_speed = get_field(bar, "ctx_poc_migration_10", 0.0)
    poc_position = get_field(bar, "poc_position", 0.5)  # 0-1
    dist_cur_vpoc = get_field(bar, "dist_cur_vpoc", 0.0)
    if poc_mig_speed > 0.5:
        poc_state = "MIGRATING_UP"
    elif poc_mig_speed < -0.5:
        poc_state = "MIGRATING_DN"
    else:
        poc_state = "STABLE"

    # ─── Absorption @ niveau (V4 prioritaire avec _at_level direct) ──
    # V4 fournit bn_absorb_*_at_level qui combine deja la condition niveau.
    # Fallback DMP bn_absorb_* + bool_near_level si V4 absent.
    absorb_bid_at_level = get_int_field(bar, "bn_absorb_bid_at_level", 0)
    absorb_ask_at_level = get_int_field(bar, "bn_absorb_ask_at_level", 0)
    if absorb_bid_at_level or absorb_ask_at_level:
        absorb_signal = "BID_DEFENDED" if absorb_bid_at_level else "ASK_DEFENDED"
    else:
        # Fallback DMP
        absorb_bid = get_int_field(bar, "bn_absorb_bid", 0)
        absorb_ask = get_int_field(bar, "bn_absorb_ask", 0)
        near_level = get_int_field(bar, "bool_near_level", 0)
        if absorb_bid and near_level:
            absorb_signal = "BID_DEFENDED"
        elif absorb_ask and near_level:
            absorb_signal = "ASK_DEFENDED"
        else:
            absorb_signal = "OFF"

    return {
        # A. VWAP align
        "vwap_d_side": vwap_d_side,
        "vwap_w_side": vwap_w_side,
        "vwap_m_side": vwap_m_side,
        "vwap_triple_align": vwap_triple_align,
        "vwap_slope_10": round(vwap_slope_10, 4),
        "vwap_slope_10_dir": vwap_slope_10_dir,
        # B. RVOL
        "rvol": round(rvol, 2),
        "rvol_zscore": round(rvol_zscore, 2),
        "rvol_zone": rvol_zone,
        # C. Delta divergence clean
        "div_signal": div_signal,
        "div_strength": round(div_strength, 1),
        "div_clean_active": int(div_signal != "OFF"),
        # D. Next wall
        "next_wall_dist_ticks": round(next_wall_dist_ticks, 1) if next_wall_dist_ticks else None,
        "next_wall_side": wall_side,
        "wall_reaction_zone": wall_reaction_zone,
        # E. Trapped @ niveau
        "trapped_signal": trapped_signal,
        "trapped_zones_buy": n_trap_buy_zones,
        "trapped_zones_sell": n_trap_sell_zones,
        # F. POC migration
        "poc_state": poc_state,
        "poc_migration_dir": poc_mig_dir,
        "poc_migration_speed": round(poc_mig_speed, 3),
        "poc_position": round(poc_position, 2),
        "dist_cur_vpoc_ticks": round(dist_cur_vpoc, 1),
        # Absorption @ niveau (bonus)
        "absorb_signal": absorb_signal,
    }


# ═══════════════════════════════════════════════════════════════
# Builder ORDER FLOW AVANCE (V4 enriched — bonus widgets 04/05)
# 4 widgets : cluster_distance, big_orders, smt_divergence, naked_poc
# Source : DATA/datasets/v4_enriched/ (Databento + features pipeline)
# ═══════════════════════════════════════════════════════════════


def build_order_flow_advanced(bar: dict) -> dict:
    """Indicateurs order flow avances issus du parquet V4 enriched.

    4 widgets bonus (cf demande Jackson 04/05) :
      H. Cluster acheteur/vendeur (distance + niveau touche)
      I. Gros ordres bid/ask (dominance + tier + max volume)
      J. SMT divergence ES/NQ (inter-marche)
      K. Naked POC (distance + age max)

    Toutes les distances V4 sont en pourcentage du prix (`*_pct`).
    Pour affichage on garde le % brut, plus stable que conversion ticks
    (pas besoin de connaitre tick_size cote dashboard).

    Returns : dict prefixe `of_*` pour eviter collision avec mi_*.
    """
    if not bar:
        return {}

    # ─── H. Cluster volumique @ niveau (REFACTOR 04/05 — features live) ──
    # Anciennes sources cluster_at_high/low sont mortes (ES 0.18% / NQ 0%) car
    # phase_b_plus_plus_engine threshold ML strict (250/70) tue la feature live.
    # Empirique mai 2026 sur 1109 barres : on swap pour features deja live :
    #   - n_big_ask_v2_t1 ≥ 1 (29% ES / 7% NQ) = gros ordres ASK = resistance
    #   - n_big_bid_v2_t1 ≥ 1 (29% ES / 8% NQ) = gros ordres BID = support
    #   - near_resistance_level / near_support_level = niveau structurel (HVL/POC/VWAP/BL)
    #   - bn_trapped_*_at_resistance/support = trap haute conviction
    # Semantique preservee : "concentration volume @ niveau structurel".
    n_big_ask_t1 = get_int_field(bar, "n_big_ask_v2_t1", 0)
    n_big_bid_t1 = get_int_field(bar, "n_big_bid_v2_t1", 0)
    near_res = get_int_field(bar, "near_resistance_level", 0)
    near_sup = get_int_field(bar, "near_support_level", 0)
    trap_buy_res = get_int_field(bar, "bn_trapped_buyers_at_resistance", 0)
    trap_sell_sup = get_int_field(bar, "bn_trapped_sellers_at_support", 0)
    # Bonus contextuel preserve : nb clusters detectes (peut rester pour info)
    n_clusters = get_int_field(bar, "n_cluster_groups", 0)
    # Distances aux gros ordres (en %, vivant cote V4) — vars locales section H
    # (les vars `dist_big_ask_pct` / `dist_big_bid_pct` sont redefinies section I).
    _dist_big_ask_h = get_field(bar, "dist_big_ask_nearest_pct", 0.0)
    _dist_big_bid_h = get_field(bar, "dist_big_bid_nearest_pct", 0.0)

    # Side cluster proche : compare distances aux gros ordres ASK vs BID
    # ASK pres = resistance acheteurs / BID pres = support vendeurs
    if _dist_big_ask_h > 0 and (_dist_big_bid_h == 0
                                 or _dist_big_ask_h < _dist_big_bid_h):
        cluster_nearest_side = "ASK"
        cluster_nearest_dist_pct = round(_dist_big_ask_h, 3)
    elif _dist_big_bid_h > 0:
        cluster_nearest_side = "BID"
        cluster_nearest_dist_pct = round(_dist_big_bid_h, 3)
    else:
        cluster_nearest_side = "OFF"
        cluster_nearest_dist_pct = 0.0

    # Signal compose : trap @ niveau = haute conviction reversal (rare event Lopez)
    # Sinon big orders @ niveau structurel = AT_RES / AT_SUP normal
    if trap_buy_res:
        cluster_signal = "TRAP_BUY_AT_RES"      # bearish reversal probable
    elif trap_sell_sup:
        cluster_signal = "TRAP_SELL_AT_SUP"     # bullish reversal probable
    elif n_big_ask_t1 >= 1 and near_res:
        cluster_signal = "AT_RESISTANCE"        # gros ordres ASK pres niveau
    elif n_big_bid_t1 >= 1 and near_sup:
        cluster_signal = "AT_SUPPORT"           # gros ordres BID pres niveau
    else:
        cluster_signal = "OFF"

    # ─── I. Gros ordres bid/ask ──────────────────────────────────
    big_buy_dom = get_field(bar, "big_buy_dominance", 0.0)   # ratio 0-1
    big_sell_dom = get_field(bar, "big_sell_dominance", 0.0)
    # Total counts par tier (T1 = plus gros volume)
    n_big_buy_t1 = get_int_field(bar, "n_big_buy_t1", 0)
    n_big_buy_t2 = get_int_field(bar, "n_big_buy_t2", 0)
    n_big_sell_t1 = get_int_field(bar, "n_big_sell_t1", 0)
    n_big_sell_t2 = get_int_field(bar, "n_big_sell_t2", 0)
    n_big_buy_total = n_big_buy_t1 + n_big_buy_t2 + \
        get_int_field(bar, "n_big_buy_t3", 0) + get_int_field(bar, "n_big_buy_t4", 0)
    n_big_sell_total = n_big_sell_t1 + n_big_sell_t2 + \
        get_int_field(bar, "n_big_sell_t3", 0) + get_int_field(bar, "n_big_sell_t4", 0)
    max_big_ask_vol = get_int_field(bar, "max_big_ask_vol_in_bar", 0)
    max_big_bid_vol = get_int_field(bar, "max_big_bid_vol_in_bar", 0)
    dist_big_ask_pct = get_field(bar, "dist_big_ask_nearest_pct", 0.0)
    dist_big_bid_pct = get_field(bar, "dist_big_bid_nearest_pct", 0.0)

    # Side dominant + signal compose
    # big_buy_dominance > 0.65 = pression acheteuse forte (ordres > vendeurs)
    if big_buy_dom >= 0.65 and n_big_buy_t1 >= 1:
        big_signal = "BUY_AGGRESSIVE"
        big_side = "BUY"
    elif big_sell_dom >= 0.65 and n_big_sell_t1 >= 1:
        big_signal = "SELL_AGGRESSIVE"
        big_side = "SELL"
    elif big_buy_dom >= 0.55:
        big_signal = "BUY_LEAN"
        big_side = "BUY"
    elif big_sell_dom >= 0.55:
        big_signal = "SELL_LEAN"
        big_side = "SELL"
    else:
        big_signal = "BALANCED"
        big_side = "NEUTRAL"

    # ─── J. SMT divergence ES/NQ (REFACTOR 04/05 — features live) ──
    # Ancienne source `im_smt_divergence` est morte (ES 0% / NQ 0.5% mai 2026)
    # car seuils ticks bruts hardcodes 10t mal calibres (cf pipeline V4 builder
    # commentaire "ES 99.93% zeros (seuils 10pts hardcodes)" ligne 154).
    # Swap pour `im_delta_day_divergence` : (sign_t - sign_o)/2 antisymetrique
    # mathematique, fire 21.7% ES + NQ avec miroir parfait (ES +1 ↔ NQ -1).
    # Semantique preservee : "decoupling directionnel ES/NQ" = concept ICT.
    im_delta_div = get_int_field(bar, "im_delta_day_divergence", 0)  # -1/0/+1
    if im_delta_div > 0:
        smt_signal = "BULL"      # ES/NQ desync favorable acheteurs
    elif im_delta_div < 0:
        smt_signal = "BEAR"
    else:
        smt_signal = "OFF"

    # ─── K. Naked POC ────────────────────────────────────────────
    dist_npoc_pct = get_field(bar, "dist_naked_poc_nearest_pct", 0.0)
    n_npoc_active = get_int_field(bar, "n_naked_poc_active", 0)
    n_npoc_close = get_int_field(bar, "n_naked_poc_within_0_5pct", 0)
    npoc_age_max = get_int_field(bar, "naked_poc_age_max_days", 0)

    # ─── L. Cluster strength (Phase 2 enrichissement OFA 13/05/2026) ──
    # Force du cluster present = nombre de clusters + niveaux structurels touches
    # cluster_strength : 0=off, 1=light (1 cluster), 2=medium (2+ clusters),
    #                    3=heavy (cluster + near_level)
    if n_clusters >= 2 and (near_res or near_sup):
        cluster_strength = 3
        cluster_strength_label = "HEAVY"
    elif n_clusters >= 1 and (near_res or near_sup):
        cluster_strength = 2
        cluster_strength_label = "MEDIUM"
    elif n_clusters >= 1:
        cluster_strength = 1
        cluster_strength_label = "LIGHT"
    else:
        cluster_strength = 0
        cluster_strength_label = "OFF"

    # ─── M. Bid/Ask imbalance par bar (Phase 2 13/05/2026) ──────────
    # Delta normalise : (buy_vol - sell_vol) / total_vol = imbalance [-1, +1]
    # Plus stable que delta_bar absolu (depend du volume).
    # Seuils (code-reviewer reserve R2 13/05) : abaissés de ±0.3/±0.6 a
    # ±0.2/±0.4 pour 1-min bars liquides ES/NQ ou imbalance > 50% rare.
    delta_bar = get_field(bar, "delta_bar", 0.0)
    bar_volume = get_field(bar, "volume", 0.0)
    if bar_volume > 0:
        imbalance = delta_bar / bar_volume
        imbalance = max(-1.0, min(1.0, imbalance))  # clamp [-1, +1]
    else:
        imbalance = 0.0
    # Label visuel
    if imbalance >= 0.4:
        imbalance_label = "BUY_STRONG"
    elif imbalance >= 0.2:
        imbalance_label = "BUY_LIGHT"
    elif imbalance <= -0.4:
        imbalance_label = "SELL_STRONG"
    elif imbalance <= -0.2:
        imbalance_label = "SELL_LIGHT"
    else:
        imbalance_label = "BALANCED"

    # ─── N. Absorption velocity (Phase 2 13/05/2026) ────────────────
    # Mesure agressivite absorption : nombre d'events absorb au niveau dans
    # les N dernieres barres / window. V4 expose bn_absorb_bid_at_level et
    # bn_absorb_ask_at_level (booleens bar courante). On combine avec _streak_5
    # ou comptage rolling pour estimer velocity.
    absorb_bid_now = get_int_field(bar, "bn_absorb_bid_at_level", 0)
    absorb_ask_now = get_int_field(bar, "bn_absorb_ask_at_level", 0)
    # Stack absorb counter (rolling 5 bars proxy via ctx_absorption_streak_5)
    absorb_streak = get_int_field(bar, "ctx_absorption_streak_5", 0)
    # FIX code-reviewer R3 13/05 : formule additive lineaire vs multiplicative.
    # `(absorb_now * (1 + streak/5))` etait instable : si streak=5 et absorb=1
    # → velocity = 2 (HIGH) meme sans nouvel event. Additif plus interpretable.
    absorb_velocity = (absorb_bid_now + absorb_ask_now) + 0.2 * absorb_streak
    if absorb_velocity >= 2.0:
        velocity_label = "VERY_HIGH"
    elif absorb_velocity >= 1.5:
        velocity_label = "HIGH"
    elif absorb_velocity >= 1.0:
        velocity_label = "MODERATE"
    elif absorb_velocity >= 0.4:
        velocity_label = "LIGHT"  # streak only (legacy absorption visible)
    else:
        velocity_label = "OFF"
    velocity_side = "BID" if absorb_bid_now else "ASK" if absorb_ask_now else "NONE"

    # ─── O. Big orders momentum sliding (Phase 2 13/05/2026) ────────
    # Somme T1+T2+T3 buy vs sell sur la bar courante (proxy momentum).
    # V4 expose n_big_buy_t1/t2/t3 et n_big_sell_t1/t2/t3 par bar.
    # Le "sliding 5 bars" necessiterait acces a historique → on utilise les
    # ratio buy_dom et sell_dom (dejacalcules sur window phase B+++) comme
    # proxy momentum directionnel.
    big_buy_tier_sum = n_big_buy_t1 + n_big_buy_t2 + get_int_field(bar, "n_big_buy_t3", 0)
    big_sell_tier_sum = n_big_sell_t1 + n_big_sell_t2 + get_int_field(bar, "n_big_sell_t3", 0)
    if big_buy_tier_sum + big_sell_tier_sum > 0:
        momentum_ratio = (big_buy_tier_sum - big_sell_tier_sum) / (big_buy_tier_sum + big_sell_tier_sum)
    else:
        momentum_ratio = 0.0
    momentum_total = big_buy_tier_sum + big_sell_tier_sum
    # FIX code-reviewer R4 13/05 : seuils RUSH abaisses 5->3, LEAN 2->2 inchange.
    # n_big_buy_t1+t2+t3 souvent 0-2 par 1-min bar V4 -> total>=5 quasi-jamais.
    if momentum_total >= 3 and momentum_ratio >= 0.6:
        momentum_label = "BUY_RUSH"
    elif momentum_total >= 3 and momentum_ratio <= -0.6:
        momentum_label = "SELL_RUSH"
    elif momentum_total >= 2 and momentum_ratio >= 0.2:
        momentum_label = "BUY_LEAN"
    elif momentum_total >= 2 and momentum_ratio <= -0.2:
        momentum_label = "SELL_LEAN"
    elif momentum_total >= 1:
        momentum_label = "ACTIVE"
    else:
        momentum_label = "QUIET"

    # Signal : Naked POC proche (<0.2%) = aimant fort, age >5j = haute conviction
    if dist_npoc_pct > 0 and dist_npoc_pct <= 0.2 and npoc_age_max >= 5:
        npoc_signal = "MAGNET_STRONG"
    elif dist_npoc_pct > 0 and dist_npoc_pct <= 0.5:
        npoc_signal = "MAGNET_NEAR"
    elif n_npoc_active > 0:
        npoc_signal = "PRESENT"
    else:
        npoc_signal = "OFF"

    return {
        # H. Cluster (refactor 04/05 — sources live big_t1 + near_*_level + trapped)
        "cluster_signal": cluster_signal,
        "cluster_nearest_side": cluster_nearest_side,
        "cluster_nearest_dist_pct": cluster_nearest_dist_pct,
        "cluster_count": n_clusters,
        "cluster_trap_buy": trap_buy_res,
        "cluster_trap_sell": trap_sell_sup,
        "cluster_near_res": near_res,
        "cluster_near_sup": near_sup,
        "cluster_big_ask_t1": n_big_ask_t1,
        "cluster_big_bid_t1": n_big_bid_t1,
        # I. Big orders
        "big_signal": big_signal,
        "big_side": big_side,
        "big_buy_dom": round(big_buy_dom, 2),
        "big_sell_dom": round(big_sell_dom, 2),
        "big_buy_count": n_big_buy_total,
        "big_sell_count": n_big_sell_total,
        "big_buy_t1": n_big_buy_t1,
        "big_sell_t1": n_big_sell_t1,
        "big_max_ask_vol": max_big_ask_vol,
        "big_max_bid_vol": max_big_bid_vol,
        "big_dist_ask_pct": round(dist_big_ask_pct, 3),
        "big_dist_bid_pct": round(dist_big_bid_pct, 3),
        # J. SMT (refactor 04/05 — source im_delta_day_divergence)
        "smt_signal": smt_signal,
        "smt_value": im_delta_div,           # principal signal (-1/0/+1)
        "smt_delta_day": im_delta_div,       # garde pour compat dashboard JS
        # K. Naked POC
        "npoc_signal": npoc_signal,
        "npoc_dist_pct": round(dist_npoc_pct, 3),
        "npoc_active": n_npoc_active,
        "npoc_close": n_npoc_close,
        "npoc_age_max_days": npoc_age_max,
        # L. Cluster strength (Phase 2 13/05/2026)
        "cluster_strength": cluster_strength,
        "cluster_strength_label": cluster_strength_label,
        # M. Bid/Ask imbalance par bar (Phase 2 13/05/2026)
        "imbalance": round(imbalance, 3),
        "imbalance_label": imbalance_label,
        # N. Absorption velocity (Phase 2 13/05/2026)
        "absorb_velocity": round(absorb_velocity, 2),
        "absorb_velocity_label": velocity_label,
        "absorb_velocity_side": velocity_side,
        # O. Big orders momentum sliding (Phase 2 13/05/2026)
        "big_momentum_ratio": round(momentum_ratio, 3),
        "big_momentum_total": momentum_total,
        "big_momentum_label": momentum_label,
    }


# ═══════════════════════════════════════════════════════════════
# Builder ACTIVE SETUPS (Phase 2 — banner alerts composite)
# Audit market-analyst : 4 setups composites haut conviction
# ═══════════════════════════════════════════════════════════════


def detect_active_setups(bar: dict) -> List[dict]:
    """Detecte les setups composites actifs sur la barre courante.

    4 setups (cf audit market-analyst 04/05) :
      1. SHORT haut conviction (trapped buyers + POC dn + div SELL + VWAP dn)
      2. LONG breakout (IB broken up + RVOL elevated + VWAP triple align up)
      3. MEAN REVERSION (range day + VA extreme + div active)
      4. NO-TRADE (RVOL low + VIX low + profile mixte + bars_in_va high)

    Returns : liste de setups actifs avec metadata (name, side, conviction, reasons).
    """
    if not bar:
        return []

    setups: List[dict] = []

    # ─── Variables partagees ─────────────────────────────────────
    trapped_buyers = get_int_field(bar, "bn_trapped_buyers_at_resistance", 0)
    trapped_sellers = get_int_field(bar, "bn_trapped_sellers_at_support", 0)
    poc_mig_speed = get_field(bar, "ctx_poc_migration_10", 0.0)
    div_clean = get_int_field(bar, "delta_divergence_clean", 0)
    div_buy = get_int_field(bar, "delta_div_buy_clean", 0)
    div_sell = get_int_field(bar, "delta_div_sell_clean", 0)
    div_strength = get_field(bar, "delta_div_strength", 0.0)
    vwap_slope = get_field(bar, "vwap_slope_10", 0.0)
    vwap_triple_align = get_int_field(bar, "vwap_triple_align", 0)
    vwap_d_side = get_int_field(bar, "vwap_d_side", 0)
    dist_swing_high = get_field(bar, "dist_swing_high", 999.0)
    dist_swing_low = get_field(bar, "dist_swing_low", 999.0)
    ib_broken_up = get_int_field(bar, "ib_broken_up", 0)
    ib_broken_down = get_int_field(bar, "ib_broken_down", 0)
    ib_is_narrow = get_int_field(bar, "ib_is_narrow", 0)
    rvol_zscore = get_field(bar, "rvol_zscore", 0.0)
    next_wall_dist = get_field(bar, "next_wall_dist_ticks", 0.0)
    open_bias_conf = get_field(bar, "open_bias_conf", 0.0)
    profile_shape = get_int_field(bar, "profile_shape", 0)
    va_position = get_field(bar, "va_position_pct", 0.5)
    bars_in_va = get_int_field(bar, "bars_in_va", 0)
    vix_regime = get_int_field(bar, "vix_regime", 1)

    # ─── Setup #1 : SHORT haut conviction ────────────────────────
    short_reasons = []
    if trapped_buyers:
        short_reasons.append("Trapped buyers @ resistance")
    if poc_mig_speed < -0.3:
        short_reasons.append(f"POC migrating dn ({poc_mig_speed:.2f})")
    if div_clean and div_sell and div_strength >= 60:
        short_reasons.append(f"Delta div SELL ({div_strength:.0f})")
    if vwap_slope < 0:
        short_reasons.append("VWAP slope dn")
    if dist_swing_high <= 5.0:
        short_reasons.append(f"Swing high {dist_swing_high:.0f}t")
    # Setup actif si >= 4 conditions sur 5
    if len(short_reasons) >= 4:
        setups.append({
            "name": "SHORT_HIGH_CONVICTION",
            "side": "SHORT",
            "conviction": "HIGH",
            "n_reasons": len(short_reasons),
            "reasons": short_reasons,
            "color": "#e57373",  # rouge
        })

    # ─── Setup #2 : LONG breakout ────────────────────────────────
    long_reasons = []
    if ib_broken_up:
        long_reasons.append("IB broken UP")
    if rvol_zscore >= 1.5:
        long_reasons.append(f"RVOL z={rvol_zscore:.1f}")
    if vwap_triple_align and vwap_d_side > 0:
        long_reasons.append("VWAP triple align UP")
    if next_wall_dist >= 15:
        long_reasons.append(f"Next wall {next_wall_dist:.0f}t (espace)")
    if open_bias_conf >= 0.6:
        long_reasons.append(f"Open bias conf {open_bias_conf:.2f}")
    if len(long_reasons) >= 4:
        setups.append({
            "name": "LONG_BREAKOUT",
            "side": "LONG",
            "conviction": "HIGH",
            "n_reasons": len(long_reasons),
            "reasons": long_reasons,
            "color": "#4caf50",  # vert
        })

    # ─── Setup #3 : MEAN REVERSION (range day) ───────────────────
    fade_reasons = []
    if profile_shape == 3:  # range
        fade_reasons.append("Profile shape RANGE")
    if va_position >= 0.85 or va_position <= 0.15:
        side_fade = "SHORT" if va_position >= 0.85 else "LONG"
        fade_reasons.append(f"VA extreme ({va_position:.2f})")
    if div_clean and div_strength >= 50:
        fade_reasons.append("Delta div active")
    if rvol_zscore < 1.0:
        fade_reasons.append(f"RVOL calme z={rvol_zscore:.1f}")
    if ib_is_narrow:
        fade_reasons.append("IB narrow")
    if len(fade_reasons) >= 4 and (va_position >= 0.85 or va_position <= 0.15):
        side_fade = "SHORT" if va_position >= 0.85 else "LONG"
        setups.append({
            "name": "FADE_EXTREME",
            "side": side_fade,
            "conviction": "MEDIUM",
            "n_reasons": len(fade_reasons),
            "reasons": fade_reasons,
            "color": "#ffa726",  # orange
        })

    # ─── Setup #4 : NO-TRADE filter ─────────────────────────────
    notrade_reasons = []
    if rvol_zscore < -0.5:
        notrade_reasons.append(f"RVOL low z={rvol_zscore:.1f}")
    if vix_regime == 0:  # LOW
        notrade_reasons.append("VIX regime LOW")
    if profile_shape == 0:  # mixte
        notrade_reasons.append("Profile mixte")
    if bars_in_va >= 30:
        notrade_reasons.append(f"Bars in VA = {bars_in_va}")
    if len(notrade_reasons) >= 3:
        setups.append({
            "name": "NO_TRADE_ZONE",
            "side": "NEUTRAL",
            "conviction": "FILTER",
            "n_reasons": len(notrade_reasons),
            "reasons": notrade_reasons,
            "color": "#9e9e9e",  # gris
        })

    return setups
