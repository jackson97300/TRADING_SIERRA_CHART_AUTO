"""intermarket_streaming.py

API streaming-aware intermarket_features.py - features cross-sym ES/NQ.
10 features cross-asset utilisant les bars du symbole partenaire (other).

Convention : caller fournit les valeurs other (price_o, delta_o, vol_o, etc.)
pour la bar courante. State maintient les rolling windows pour les statistiques.

Features (10) :
  im_cross_delta_agreement_5  : rolling mean 5 sign(delta_t)==sign(delta_o)
  im_cross_delta_weighted_5   : rolling mean 5 magnitude-weighted agreement
  im_smt_divergence           : velocity sess_high/low cross-sym (-1/0/+1)
  im_delta_day_divergence     : (sign(delta_day_t) - sign(delta_day_o)) / 2
  im_price_ratio_slope_10     : linreg slope ratio price_t/price_o sur 10
  im_volume_lead              : slope vol_t(5) - slope vol_o(5)
  im_rolling_correlation_10   : Pearson corr 10 bars price_t vs price_o
  im_ltr_slope_diff           : slope ltr_t(5) - slope ltr_o(5)
  im_cross_open_signal        : cross open signal (target neutre -> other)
  im_open_type_agreement      : +1/-1/0 direction agreement
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class IntermarketState:
    """State streaming intermarket - 12+ deques rolling."""
    short: int = 3
    mid: int = 5
    long: int = 10

    # Cross-delta agreement / weighted (rolling mean 5)
    agreement_window: deque = field(default_factory=lambda: deque(maxlen=5))
    weighted_window: deque = field(default_factory=lambda: deque(maxlen=5))

    # Price windows (long=10 pour ratio slope + corr)
    price_t_window: deque = field(default_factory=lambda: deque(maxlen=10))
    price_o_window: deque = field(default_factory=lambda: deque(maxlen=10))

    # Volume windows (mid=5 pour volume_lead slope)
    vol_t_window: deque = field(default_factory=lambda: deque(maxlen=5))
    vol_o_window: deque = field(default_factory=lambda: deque(maxlen=5))

    # LTR windows (mid=5)
    ltr_t_window: deque = field(default_factory=lambda: deque(maxlen=5))
    ltr_o_window: deque = field(default_factory=lambda: deque(maxlen=5))

    # SMT divergence velocity : shift(short=3) sur dist_sess_high/low (4 bars history)
    dist_high_t_window: deque = field(default_factory=lambda: deque(maxlen=4))
    dist_high_o_window: deque = field(default_factory=lambda: deque(maxlen=4))
    dist_low_t_window: deque = field(default_factory=lambda: deque(maxlen=4))
    dist_low_o_window: deque = field(default_factory=lambda: deque(maxlen=4))

    # Price ratio for slope (long=10)
    ratio_window: deque = field(default_factory=lambda: deque(maxlen=10))


def _linreg_slope(values: list) -> float:
    """Pente regression lineaire (mirror batch _slope)."""
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    if n < 2:
        return np.nan
    valid = ~np.isnan(arr)
    if valid.sum() < 2:
        return np.nan
    x = np.arange(n, dtype=float)[valid]
    y = arr[valid]
    mx, my = x.mean(), y.mean()
    denom = ((x - mx) ** 2).sum()
    if denom == 0:
        return 0.0
    return float(((x - mx) * (y - my)).sum() / denom)


def _safe_float(x) -> float:
    if x is None:
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def add_intermarket_streaming(
    row: dict,
    state: IntermarketState,
    other_inputs: Optional[dict] = None,
) -> dict:
    """Sub-engine streaming intermarket - 10 features cross-sym.

    Args:
        row : dict bar courante du target avec price, delta_bar, total_vol,
              delta_day, dist_sess_high/low, large_trader_ratio, open_direction,
              open_bias_conf.
        state : IntermarketState mutable.
        other_inputs : dict valeurs other-sym pour la meme bar (price, delta_bar,
                       total_vol, delta_day, dist_sess_high/low, large_trader_ratio,
                       open_direction, open_bias_conf).
                       None = toutes features = NaN.

    Returns:
        dict row + 10 features im_*.
    """
    out = dict(row)

    # Init defaults
    for col in (
        "im_cross_delta_agreement_5", "im_cross_delta_weighted_5",
        "im_smt_divergence", "im_delta_day_divergence",
        "im_price_ratio_slope_10", "im_volume_lead",
        "im_rolling_correlation_10", "im_ltr_slope_diff",
        "im_cross_open_signal", "im_open_type_agreement",
    ):
        out[col] = np.nan

    if other_inputs is None:
        return out

    # Inputs target
    price_t = _safe_float(out.get("price"))
    delta_t = _safe_float(out.get("delta_bar"))
    vol_t = _safe_float(out.get("total_vol"))
    delta_day_t = _safe_float(out.get("delta_day"))
    dist_high_t = _safe_float(out.get("dist_sess_high"))
    dist_low_t = _safe_float(out.get("dist_sess_low"))
    ltr_t = _safe_float(out.get("large_trader_ratio"))
    conf_t = _safe_float(out.get("open_bias_conf"))
    if np.isnan(conf_t):
        conf_t = 0.0
    dir_t = _safe_float(out.get("open_direction"))
    if np.isnan(dir_t):
        dir_t = 0.0

    # Inputs other
    price_o = _safe_float(other_inputs.get("price"))
    delta_o = _safe_float(other_inputs.get("delta_bar"))
    vol_o = _safe_float(other_inputs.get("total_vol"))
    delta_day_o = _safe_float(other_inputs.get("delta_day"))
    dist_high_o = _safe_float(other_inputs.get("dist_sess_high"))
    dist_low_o = _safe_float(other_inputs.get("dist_sess_low"))
    ltr_o = _safe_float(other_inputs.get("large_trader_ratio"))
    conf_o = _safe_float(other_inputs.get("open_bias_conf"))
    if np.isnan(conf_o):
        conf_o = 0.0
    dir_o = _safe_float(other_inputs.get("open_direction"))
    if np.isnan(dir_o):
        dir_o = 0.0

    # ─── 1. Cross-delta agreement (rolling mean 5) ──────────────────────────
    # sign agreement + handle both zero -> 0.5
    if not np.isnan(delta_t) and not np.isnan(delta_o):
        sign_t = np.sign(delta_t)
        sign_o = np.sign(delta_o)
        if delta_t == 0 and delta_o == 0:
            agreement = 0.5
        else:
            agreement = 1.0 if sign_t == sign_o else 0.0
        state.agreement_window.append(agreement)

        # Magnitude weighted
        magnitude = min(abs(delta_t), abs(delta_o))
        weighted = agreement * magnitude
        state.weighted_window.append(weighted)

        # Rolling mean (min_periods=1 -> output dès 1 bar)
        out["im_cross_delta_agreement_5"] = float(np.mean(state.agreement_window))
        out["im_cross_delta_weighted_5"] = float(np.mean(state.weighted_window))

    # ─── 2. SMT divergence (velocity dist_sess_high/low cross) ──────────────
    # high_vel = dist_high - dist_high.shift(short=3)
    state.dist_high_t_window.append(dist_high_t)
    state.dist_high_o_window.append(dist_high_o)
    state.dist_low_t_window.append(dist_low_t)
    state.dist_low_o_window.append(dist_low_o)

    if len(state.dist_high_t_window) >= 4:
        dh_t_prev = state.dist_high_t_window[0]  # T-3
        dh_o_prev = state.dist_high_o_window[0]
        dl_t_prev = state.dist_low_t_window[0]
        dl_o_prev = state.dist_low_o_window[0]
        if not (
            np.isnan(dist_high_t) or np.isnan(dh_t_prev)
            or np.isnan(dist_high_o) or np.isnan(dh_o_prev)
            or np.isnan(dist_low_t) or np.isnan(dl_t_prev)
            or np.isnan(dist_low_o) or np.isnan(dl_o_prev)
        ):
            high_vel_t = dist_high_t - dh_t_prev
            high_vel_o = dist_high_o - dh_o_prev
            low_vel_t = dist_low_t - dl_t_prev
            low_vel_o = dist_low_o - dl_o_prev
            smt_bear = (high_vel_t < -10) and (high_vel_o > 0)
            smt_bull = (low_vel_t > 10) and (low_vel_o < 0)
            if smt_bear:
                out["im_smt_divergence"] = -1.0
            elif smt_bull:
                out["im_smt_divergence"] = 1.0
            else:
                out["im_smt_divergence"] = 0.0
    else:
        # Warmup (bar < 4) : batch retourne NaN car shift(3) -> NaN sur 3 premieres bars
        # Stream doit aussi retourner NaN pendant warmup (P1 #9 align batch)
        out["im_smt_divergence"] = np.nan

    # ─── 3. Delta day divergence ───────────────────────────────────────────
    if not np.isnan(delta_day_t) and not np.isnan(delta_day_o):
        day_dir_t = np.sign(delta_day_t)
        day_dir_o = np.sign(delta_day_o)
        out["im_delta_day_divergence"] = (day_dir_t - day_dir_o) / 2.0

    # ─── 4. Price ratio slope 10 ───────────────────────────────────────────
    if not np.isnan(price_t) and not np.isnan(price_o) and price_o != 0:
        ratio = price_t / price_o
        state.ratio_window.append(ratio)
        out["im_price_ratio_slope_10"] = _linreg_slope(list(state.ratio_window))
    else:
        state.ratio_window.append(np.nan)

    # ─── 5. Volume lead (slope vol_t - slope vol_o, mid=5) ─────────────────
    state.vol_t_window.append(vol_t)
    state.vol_o_window.append(vol_o)
    if len(state.vol_t_window) >= 2:
        slope_t = _linreg_slope(list(state.vol_t_window))
        slope_o = _linreg_slope(list(state.vol_o_window))
        if not (np.isnan(slope_t) or np.isnan(slope_o)):
            out["im_volume_lead"] = slope_t - slope_o

    # ─── 6. Rolling correlation 10 ─────────────────────────────────────────
    state.price_t_window.append(price_t)
    state.price_o_window.append(price_o)
    if len(state.price_t_window) >= 5:
        arr_t = np.array(state.price_t_window)
        arr_o = np.array(state.price_o_window)
        valid = ~np.isnan(arr_t) & ~np.isnan(arr_o)
        if valid.sum() >= 5:
            corr = np.corrcoef(arr_t[valid], arr_o[valid])[0, 1]
            if not np.isnan(corr):
                out["im_rolling_correlation_10"] = corr

    # ─── 7. LTR slope diff ─────────────────────────────────────────────────
    state.ltr_t_window.append(ltr_t)
    state.ltr_o_window.append(ltr_o)
    if len(state.ltr_t_window) >= 2:
        slope_t = _linreg_slope(list(state.ltr_t_window))
        slope_o = _linreg_slope(list(state.ltr_o_window))
        if not (np.isnan(slope_t) or np.isnan(slope_o)):
            out["im_ltr_slope_diff"] = slope_t - slope_o

    # ─── 8. Cross open signal (target neutre -> prendre other) ──────────────
    target_neutral = conf_t < 0.35
    if target_neutral:
        out["im_cross_open_signal"] = dir_o * conf_o
    else:
        out["im_cross_open_signal"] = dir_t * conf_t

    # ─── 9. Open type agreement ─────────────────────────────────────────────
    if dir_t != 0 and dir_o != 0:
        out["im_open_type_agreement"] = 1.0 if dir_t == dir_o else -1.0
    else:
        out["im_open_type_agreement"] = 0.0

    return out
