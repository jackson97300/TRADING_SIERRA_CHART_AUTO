"""Lecture des donnees MIA depuis le JSON dashboard et les JSONL barres."""
import json
import logging
import os
from glob import glob

from DASHBOARD.config import DASHBOARD_JSON, DATA_DIR

logger = logging.getLogger(__name__)

# --- Labels ---

OPEN_TYPE_LABELS = {
    0: "UNKNOWN",
    1: "OD UP",
    2: "OD DOWN",
    3: "OTD UP",
    4: "OTD DOWN",
    5: "ORR UP",
    6: "ORR DOWN",
    7: "OAIR",
    8: "OAOR UP",
    9: "OAOR DOWN",
    10: "ODF UP",
    11: "ODF DOWN",
}

DAY_TYPE_LABELS = {
    0: "NON TREND",
    1: "NORMAL",
    2: "NORM VARIATION",
    3: "NEUTRAL",
    4: "TREND",
}

PROFILE_SHAPE_LABELS = {
    0: "D-Shape",
    1: "P-Shape",
    2: "b-Shape",
    3: "Double Dist",
}

RVOL_REGIME_LABELS = {
    0: "Low",
    1: "Normal",
    2: "High",
    3: "Spike",
    4: "Extreme",
}

AMD_PHASE_LABELS = {
    0: "Asia",
    1: "London",
    2: "US",
}


# --- Helpers ---


def get_field(bar: dict, field: str, default: float = 0.0) -> float:
    """Extrait un champ numerique avec fallback. Gere None et 'INVALID'."""
    val = bar.get(field, default)
    if val is None or val == "INVALID":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def get_int_field(bar: dict, field: str, default: int = 0) -> int:
    """Extrait un champ entier avec fallback."""
    val = bar.get(field, default)
    if val is None or val == "INVALID":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def get_str_field(bar: dict, field: str, default: str = "") -> str:
    """Extrait un champ texte avec fallback."""
    val = bar.get(field, default)
    if val is None or val == "INVALID":
        return default
    return str(val)


# --- Sources de donnees ---


def read_bot_status() -> dict:
    """Lit le JSON de statut du bot. Retourne dict vide si absent."""
    if not os.path.exists(DASHBOARD_JSON):
        logger.warning("Dashboard JSON absent: %s", DASHBOARD_JSON)
        return {}
    try:
        with open(DASHBOARD_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Erreur lecture dashboard JSON: %s", exc)
        return {}


def get_latest_jsonl(symbol: str) -> str | None:
    """Trouve le fichier JSONL le plus recent par mtime (PAS par nom).

    Pattern: DATA/{symbol}/*_{symbol}.jsonl
    """
    pattern = os.path.join(DATA_DIR, symbol, f"*_{symbol}.jsonl")
    files = glob(pattern)
    if not files:
        logger.warning("Aucun JSONL pour %s (pattern: %s)", symbol, pattern)
        return None
    return max(files, key=os.path.getmtime)


def read_last_bar(symbol: str) -> dict:
    """Lit la derniere ligne non-vide du JSONL le plus recent.

    Retourne dict vide si fichier absent ou vide.
    """
    path = get_latest_jsonl(symbol)
    if not path:
        return {}
    try:
        last_line = ""
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
        if not last_line:
            return {}
        return json.loads(last_line)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Erreur lecture derniere barre %s: %s", symbol, exc)
        return {}


def read_features(symbol: str) -> dict:
    """Lit features_es ou features_nq depuis le dashboard JSON."""
    bot_data = read_bot_status()
    key = f"features_{symbol.lower()}"
    return bot_data.get(key, {})


# --- Builders ---


def build_bot_status_basic(bot_data: dict) -> dict:
    """Extrait le statut bot basique."""
    bs = bot_data.get("bot_status", {})
    return {
        "running": bs.get("running", False),
        "global_status": bs.get("global_status", "UNKNOWN"),
        "last_heartbeat": bs.get("last_heartbeat", ""),
    }


def build_instrument_status(bot_data: dict, symbol: str) -> dict | None:
    """Extrait le statut d'un instrument."""
    instr = bot_data.get(symbol.lower())
    if not instr:
        return None
    return {
        "enabled": instr.get("enabled", False),
        "in_position": instr.get("in_position", False),
        "status": instr.get("status", ""),
        "trades_today": instr.get("trades_today", 0),
        "wins": instr.get("wins", 0),
        "losses": instr.get("losses", 0),
        "pnl_today": instr.get("pnl_today", 0.0),
        "consecutive_losses": instr.get("consecutive_losses", 0),
        "last_rejected": instr.get("last_rejected", ""),
        "signals_rejected": instr.get("signals_rejected", 0),
    }


def build_market_context_basic(bot_data: dict) -> dict:
    """Extrait VIX, ATR, VWAP slope depuis market_live."""
    ml = bot_data.get("market_live", {})
    return {
        "vix": ml.get("vix", 0.0),
        "vix_regime": ml.get("vix_regime", "UNKNOWN"),
        "atr_es": ml.get("atr_es", 0.0),
        "atr_nq": ml.get("atr_nq", 0.0),
        "vwap_slope_es": ml.get("vwap_slope_es", 0.0),
        "vwap_slope_nq": ml.get("vwap_slope_nq", 0.0),
    }


def build_market_context_full(
    bot_data: dict,
    bar_es: dict,
    bar_nq: dict,
) -> dict:
    """Contexte marche complet : basic + open_type, day_type, profile, IB."""
    basic = build_market_context_basic(bot_data)

    # On prend les donnees depuis ES en priorite, fallback NQ
    bar = bar_es if bar_es else bar_nq

    open_type_val = get_int_field(bar, "open_type", 0)
    day_type_val = get_int_field(bar, "day_type", 0)
    profile_shape_val = get_int_field(bar, "profile_shape", 0)

    ib_range = get_field(bar, "ib_range_ticks", 0.0)
    ib_broken_up = get_int_field(bar, "ib_broken_up", 0)
    ib_broken_down = get_int_field(bar, "ib_broken_down", 0)

    # Calcul extension ratio : (session_range - IB_range) / IB_range
    sess_range = get_field(bar, "sess_range_ticks", 0.0)
    ib_ext_ratio = 0.0
    if ib_range > 0:
        ib_ext_ratio = round((sess_range - ib_range) / ib_range, 3)

    full = {
        **basic,
        "open_type": open_type_val,
        "open_type_label": OPEN_TYPE_LABELS.get(open_type_val, "UNKNOWN"),
        "open_zone": get_field(bar, "open_zone", 0.0),
        "day_type": day_type_val,
        "day_type_label": DAY_TYPE_LABELS.get(day_type_val, "NON TREND"),
        "ib_range_ticks": ib_range,
        "ib_broken_up": ib_broken_up,
        "ib_broken_down": ib_broken_down,
        "ib_extension_ratio": ib_ext_ratio,
        "profile_shape": profile_shape_val,
        "profile_shape_label": PROFILE_SHAPE_LABELS.get(
            profile_shape_val, "D-Shape"
        ),
        "poc_position": get_field(bar, "poc_position", 0.0),
        "vwap_d_side": get_int_field(bar, "vwap_d_side", 0),
        "vwap_triple_align": get_int_field(bar, "vwap_triple_align", 0),
        "trend_day_probability": get_field(bar, "trend_day_probability", 0.0),
        "session_id": get_int_field(bar, "session_id", 0),
    }
    return full


def build_order_flow(bar: dict) -> dict:
    """Panel order flow : delta, CVD, RVOL, absorption, divergence."""
    if not bar:
        return {}

    rvol_val = get_field(bar, "rvol", 0.0)

    # Calcul rvol_regime depuis rvol si absent du JSONL
    rvol_regime_val = get_int_field(bar, "rvol_regime", -1)
    if rvol_regime_val < 0:
        if rvol_val < 0.5:
            rvol_regime_val = 0
        elif rvol_val < 1.0:
            rvol_regime_val = 1
        elif rvol_val < 2.0:
            rvol_regime_val = 2
        elif rvol_val < 3.0:
            rvol_regime_val = 3
        else:
            rvol_regime_val = 4

    # absorption_score = max(rvol_absorb_buy, rvol_absorb_sell)
    absorb_buy = get_field(bar, "rvol_absorb_buy", 0.0)
    absorb_sell = get_field(bar, "rvol_absorb_sell", 0.0)
    absorption_score = max(absorb_buy, absorb_sell)

    # absorption_streak : pas de champ direct, on utilise rvol_zscore comme proxy
    absorption_streak = get_field(bar, "rvol_zscore", 0.0)

    # price_delta_div = delta_divergence
    price_delta_div = get_field(bar, "delta_divergence", 0.0)

    # climax_signal : volume > 3x rvol ET delta_pct extreme
    delta_pct = get_field(bar, "delta_pct", 0.0)
    climax = 0.0
    if rvol_val >= 3.0 and abs(delta_pct) > 0.6:
        climax = 1.0 if delta_pct > 0 else -1.0

    return {
        "delta_bar": get_field(bar, "delta_bar", 0.0),
        "delta_pct": delta_pct,
        "cvd_day": get_field(bar, "cvd_day", 0.0),
        "cvd_day_dir": get_int_field(bar, "cvd_day_dir", 0),
        "rvol": rvol_val,
        "rvol_regime": rvol_regime_val,
        "rvol_regime_label": RVOL_REGIME_LABELS.get(rvol_regime_val, "Normal"),
        "absorption_score": round(absorption_score, 4),
        "absorption_streak": round(absorption_streak, 4),
        "price_delta_div": round(price_delta_div, 4),
        "climax_signal": climax,
        "large_trader_ratio": get_field(bar, "large_trader_ratio", 0.0),
        "ask_bid_imbalance": get_field(bar, "ask_bid_imbalance", 0.0),
        "finish_strength": get_field(bar, "finish_strength", 0.0),
    }


def build_options_gamma(bar: dict) -> dict:
    """Panel options/gamma : distances murs options, GEX, VIX."""
    if not bar:
        return {}
    return {
        "dist_mq_call": get_field(bar, "dist_mq_call", 0.0),
        "dist_mq_put": get_field(bar, "dist_mq_put", 0.0),
        "dist_mq_hvl": get_field(bar, "dist_mq_hvl", 0.0),
        "dist_mq_call_0dte": get_field(bar, "dist_mq_call_0dte", 0.0),
        "dist_mq_put_0dte": get_field(bar, "dist_mq_put_0dte", 0.0),
        "dist_gex_nearest_up": get_field(bar, "dist_gex_nearest_up", 0.0),
        "dist_gex_nearest_dn": get_field(bar, "dist_gex_nearest_dn", 0.0),
        "gex_cluster_count": get_int_field(bar, "gex_cluster_count", 0),
        "bool_gex_flip_zone": get_int_field(bar, "bool_gex_flip_zone", 0),
        "vix_level": get_field(bar, "vix_level", 0.0),
        "vix_regime": get_int_field(bar, "vix_regime", 0),
        "dist_vix_call": get_field(bar, "dist_vix_call", 0.0),
        "dist_vix_put": get_field(bar, "dist_vix_put", 0.0),
        "next_wall_dist_ticks": get_field(bar, "next_wall_dist_ticks", 0.0),
        "next_wall_is_call": get_int_field(bar, "next_wall_is_call", 0),
    }


def build_intermarket(bar_es: dict, bar_nq: dict) -> dict:
    """Panel intermarket : correlation, SMT, AMD."""
    # On prend les features intermarket depuis ES (calculees dans le DMP)
    bar = bar_es if bar_es else bar_nq
    if not bar:
        return {}

    # cross_delta_agreement : delta_day_dir ES == delta_day_dir NQ
    es_dir = get_int_field(bar_es, "delta_day_dir", 0) if bar_es else 0
    nq_dir = get_int_field(bar_nq, "delta_day_dir", 0) if bar_nq else 0
    cross_delta = 1 if (es_dir == nq_dir and es_dir != 0) else 0

    # SMT divergence : ES new swing high mais NQ non (ou inverse)
    es_new_high = get_int_field(bar_es, "new_swing_high", 0) if bar_es else 0
    nq_new_high = get_int_field(bar_nq, "new_swing_high", 0) if bar_nq else 0
    es_new_low = get_int_field(bar_es, "new_swing_low", 0) if bar_es else 0
    nq_new_low = get_int_field(bar_nq, "new_swing_low", 0) if bar_nq else 0
    smt = 0
    if es_new_high != nq_new_high or es_new_low != nq_new_low:
        smt = 1

    # Volume lead : qui a le RVOL le plus eleve
    es_rvol = get_field(bar_es, "rvol", 0.0) if bar_es else 0.0
    nq_rvol = get_field(bar_nq, "rvol", 0.0) if bar_nq else 0.0
    volume_lead = 0
    if es_rvol > nq_rvol * 1.2:
        volume_lead = 1  # ES leads
    elif nq_rvol > es_rvol * 1.2:
        volume_lead = -1  # NQ leads

    # LTR slope diff
    es_ltr = get_field(bar_es, "large_trader_ratio", 0.0) if bar_es else 0.0
    nq_ltr = get_field(bar_nq, "large_trader_ratio", 0.0) if bar_nq else 0.0

    # Rolling correlation : price_vs_swing_mid ES vs NQ (proxy)
    es_mid = get_field(bar_es, "price_vs_swing_mid", 0.0) if bar_es else 0.0
    nq_mid = get_field(bar_nq, "price_vs_swing_mid", 0.0) if bar_nq else 0.0
    # Simplified: si meme direction, correlation positive
    rolling_corr = 1.0 if (es_mid * nq_mid > 0) else -1.0

    # Price ratio slope (ES/NQ prix)
    es_price = get_field(bar_es, "price", 0.0) if bar_es else 0.0
    nq_price = get_field(bar_nq, "price", 0.0) if bar_nq else 0.0
    price_ratio_slope = 0.0
    if nq_price > 0:
        price_ratio_slope = round(es_price / nq_price, 6)

    # AMD features (depuis la barre, calculees par le DMP si im_* present,
    # sinon fallback sur les champs DMP bruts)
    amd_phase_val = get_int_field(bar, "session", 0)
    # Mapping session DMP : 1=Asia, 2=London, 3=US -> 0,1,2
    amd_phase_mapped = max(0, amd_phase_val - 1)
    if amd_phase_mapped > 2:
        amd_phase_mapped = 2

    return {
        "cross_delta_agreement": cross_delta,
        "smt_divergence": smt,
        "rolling_correlation": rolling_corr,
        "price_ratio_slope": price_ratio_slope,
        "volume_lead": volume_lead,
        "ltr_slope_diff": round(es_ltr - nq_ltr, 4),
        "amd_phase": amd_phase_mapped,
        "amd_phase_label": AMD_PHASE_LABELS.get(amd_phase_mapped, "Asia"),
        "amd_session_bias": get_field(bar, "open_bias_conf", 0.0),
        "amd_po3_score": get_field(bar, "trend_day_probability", 0.0),
        "amd_po3_bullish": get_int_field(bar, "vwap_triple_align", 0),
        "amd_po3_bearish": 1 if get_int_field(bar, "vwap_triple_align", 0) == -1 else 0,
        "amd_judas_swing": get_int_field(bar, "new_swing_high", 0)
        | get_int_field(bar, "new_swing_low", 0),
        "amd_manip_score": get_field(bar, "diag_imbalance", 0.0),
    }


def build_signals_journal(bot_data: dict) -> dict:
    """Panel signaux et journal depuis le dashboard JSON."""
    # Le bot ecrit signals_journal dans le JSON quand disponible
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
