"""gold_phase_d_streaming.py

API streaming-aware gold_phase_d_features.py (MGC-specific intermarket).
4 features critiques Gold :
  im_dxy_corr_60d              : rolling corr 60 bars returns MGC vs 6E (signe flippe)
  im_real_yields_proxy         : momentum 10 bars ZN+ZB ponderee
  mgc_asia_london_overlap_vol  : ratio vol bar / median rolling 60 dans overlap 12:30-16:00 UTC
  mgc_session_break_acceleration : abs(close_t - close_open) / ATR_30 dans 13:30-14:00 ET

Note : ces features sont MGC-specific. Pour ES/NQ : pas utilisees.
Cross-instrument data (6E, ZN, ZB) doit etre passe en input via row.

Module batch INTOUCHE (additive-only).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")


@dataclass
class GoldPhaseDState:
    """State streaming Gold Phase D - 4 features rolling/state-based.

    Necessite cross-instrument inputs (6E, ZN, ZB close) en plus du MGC close.
    """
    # Rolling windows pour corr 60 bars MGC vs 6E (returns)
    ret_mgc_60: deque = field(default_factory=lambda: deque(maxlen=60))
    ret_6e_60: deque = field(default_factory=lambda: deque(maxlen=60))
    prev_mgc_close: Optional[float] = None
    prev_6e_close: Optional[float] = None

    # Rolling 10 bars pour ZN/ZB momentum
    zn_close_window: deque = field(default_factory=lambda: deque(maxlen=11))  # 10+1 pour pct_change
    zb_close_window: deque = field(default_factory=lambda: deque(maxlen=11))

    # Rolling 60 bars vol pour median overlap
    vol_overlap_60: deque = field(default_factory=lambda: deque(maxlen=60))

    # Rolling 30 bars (high-low) pour ATR proxy
    range_30: deque = field(default_factory=lambda: deque(maxlen=30))

    # Capture close at 13:30 ET (US cash open) - reset chaque jour
    close_at_open: Optional[float] = None
    current_date_et: Optional[str] = None
    bars_since_open: int = 0  # pour limit=30 ffill


def _safe_float(x) -> float:
    if x is None:
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def add_gold_phase_d_streaming(
    row: dict,
    state: GoldPhaseDState,
    close_6e: Optional[float] = None,
    close_zn: Optional[float] = None,
    close_zb: Optional[float] = None,
) -> dict:
    """Sub-engine streaming Gold Phase D - 4 features intermarket + session.

    Args:
        row : dict avec ts_event (UTC), close, high, low, volume (MGC).
        state : GoldPhaseDState mutable.
        close_6e : close 6E (Euro/USD) bar synchro MGC. None = NaN.
        close_zn : close ZN (10-yr Treasury) bar synchro. None = NaN.
        close_zb : close ZB (30-yr Treasury) bar synchro. None = NaN.

    Returns:
        dict row + 4 features.
    """
    out = dict(row)

    # Init defaults
    out["im_dxy_corr_60d"] = np.nan
    out["im_real_yields_proxy"] = np.nan
    out["mgc_asia_london_overlap_vol"] = 0.0
    out["mgc_session_break_acceleration"] = 0.0

    close_mgc = _safe_float(out.get("close"))
    h = _safe_float(out.get("high"))
    l = _safe_float(out.get("low"))
    vol = _safe_float(out.get("volume"))

    ts_event = out.get("ts_event")
    if ts_event is None or pd.isna(ts_event):
        return out

    if isinstance(ts_event, pd.Timestamp):
        ts_utc = ts_event if ts_event.tz else ts_event.tz_localize("UTC")
    else:
        try:
            ts_utc = pd.Timestamp(ts_event)
            if ts_utc.tz is None:
                ts_utc = ts_utc.tz_localize("UTC")
        except (TypeError, ValueError):
            return out

    hour_utc = ts_utc.hour
    minute_utc = ts_utc.minute
    ts_ny = ts_utc.tz_convert(ET)
    hour_ny = ts_ny.hour
    minute_ny = ts_ny.minute
    date_ny = str(ts_ny.date())

    # ═══════════════════════════════════════════════════════════════════════
    # 1. im_dxy_corr_60d : rolling corr 60 bars returns MGC vs 6E (signe flippe)
    # ═══════════════════════════════════════════════════════════════════════
    close_6e_f = _safe_float(close_6e)

    # Compute returns (pct_change) si prev disponible
    if not np.isnan(close_mgc) and state.prev_mgc_close is not None and state.prev_mgc_close > 0:
        ret_mgc = (close_mgc - state.prev_mgc_close) / state.prev_mgc_close
    else:
        ret_mgc = None
    if not np.isnan(close_6e_f) and state.prev_6e_close is not None and state.prev_6e_close > 0:
        ret_6e = (close_6e_f - state.prev_6e_close) / state.prev_6e_close
    else:
        ret_6e = None

    # Append returns aux windows (None compte comme NaN pour corr)
    if ret_mgc is not None:
        state.ret_mgc_60.append(ret_mgc)
    else:
        state.ret_mgc_60.append(np.nan)
    if ret_6e is not None:
        state.ret_6e_60.append(ret_6e)
    else:
        state.ret_6e_60.append(np.nan)

    # Corr rolling 60 (min_periods = 30) sur les returns
    arr_mgc = np.array(state.ret_mgc_60)
    arr_6e = np.array(state.ret_6e_60)
    valid_mask = ~np.isnan(arr_mgc) & ~np.isnan(arr_6e)
    if valid_mask.sum() >= 30:  # min_periods 0.5 * 60
        m = arr_mgc[valid_mask]
        e = arr_6e[valid_mask]
        if len(m) >= 2:
            corr = np.corrcoef(m, e)[0, 1]
            if not np.isnan(corr):
                # Sign-flip : proxy DXY inverse
                out["im_dxy_corr_60d"] = -corr

    # Update prev closes
    if not np.isnan(close_mgc):
        state.prev_mgc_close = close_mgc
    if not np.isnan(close_6e_f):
        state.prev_6e_close = close_6e_f

    # ═══════════════════════════════════════════════════════════════════════
    # 2. im_real_yields_proxy : momentum 10 bars (ZN+ZB) ponderee
    # ═══════════════════════════════════════════════════════════════════════
    close_zn_f = _safe_float(close_zn)
    close_zb_f = _safe_float(close_zb)
    state.zn_close_window.append(close_zn_f)
    state.zb_close_window.append(close_zb_f)

    if len(state.zn_close_window) >= 11 and len(state.zb_close_window) >= 11:
        zn_t = state.zn_close_window[-1]
        zn_t_10 = state.zn_close_window[0]  # = T-10 (maxlen=11, index 0 = oldest)
        zb_t = state.zb_close_window[-1]
        zb_t_10 = state.zb_close_window[0]
        if (
            not np.isnan(zn_t) and not np.isnan(zn_t_10) and zn_t_10 != 0
            and not np.isnan(zb_t) and not np.isnan(zb_t_10) and zb_t_10 != 0
        ):
            mom_zn = (zn_t - zn_t_10) / zn_t_10
            mom_zb = (zb_t - zb_t_10) / zb_t_10
            proxy = (mom_zn * 0.5 + mom_zb * 0.5) * 1000
            out["im_real_yields_proxy"] = proxy

    # ═══════════════════════════════════════════════════════════════════════
    # 3. mgc_asia_london_overlap_vol : ratio vol_bar / median rolling 60
    # ═══════════════════════════════════════════════════════════════════════
    # Plage overlap : 12:30 - 16:00 UTC
    in_overlap = (
        (hour_utc == 12 and minute_utc >= 30)
        or hour_utc in (13, 14, 15)
    )

    if in_overlap and not np.isnan(vol):
        state.vol_overlap_60.append(vol)
        if len(state.vol_overlap_60) >= 30:
            median_overlap = float(np.median(state.vol_overlap_60))
            if median_overlap > 0:
                out["mgc_asia_london_overlap_vol"] = vol / median_overlap

    # ═══════════════════════════════════════════════════════════════════════
    # 4. mgc_session_break_acceleration : 13:30-14:00 ET post-US open
    # ═══════════════════════════════════════════════════════════════════════
    # Reset close_at_open par jour
    if date_ny != state.current_date_et:
        state.current_date_et = date_ny
        state.close_at_open = None
        state.bars_since_open = 0

    # Capture close at 13:30 ET (1ere bar a cet horaire)
    if hour_ny == 13 and minute_ny == 30 and not np.isnan(close_mgc):
        if state.close_at_open is None:
            state.close_at_open = close_mgc
            state.bars_since_open = 0
    elif state.close_at_open is not None:
        state.bars_since_open += 1
        # Limit ffill 30 bars
        if state.bars_since_open > 30:
            state.close_at_open = None

    # Update range_30 (ATR proxy)
    if not (np.isnan(h) or np.isnan(l)):
        state.range_30.append(h - l)

    # Plage 13:30 - 14:00 ET post-open
    in_post_open = (
        (hour_ny == 13 and minute_ny >= 30)
        or (hour_ny == 14 and minute_ny == 0)
    )

    if in_post_open and state.close_at_open is not None and not np.isnan(close_mgc):
        if len(state.range_30) >= 10:
            atr = float(np.mean(state.range_30))
            if atr > 0:
                accel = abs(close_mgc - state.close_at_open) / atr
                out["mgc_session_break_acceleration"] = accel

    return out
