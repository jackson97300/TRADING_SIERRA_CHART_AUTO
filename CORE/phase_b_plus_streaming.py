"""phase_b_plus_streaming.py

API streaming-aware du module phase_b_plus_engine.py (Phase B+ P1 OHLC-only).
Reproduit 74 features NON-LOOKAHEAD streaming :
  - vol_spike + vol_zscore_20 (3)
  - rotation_up/dn (2)
  - VWAP D + SD bands + cross/above (18)
  - VWAP W + SD bands (12)
  - VWAP M + SD bands (12)
  - OVN high/low + dist + broken (7)
  - Opens 08:30/09:30 + dist + above (6)
  - News flags + mins_since/to (14)

LOOKAHEAD features NON portees ici (batch-only ou backlog lag-1) :
  - color_features (utilise O[1], H[1] = bar future)
  - long_bar_features (range_h_minus_lprev utilise H[1])
  - long_updown_features (idem)
  -> 23 features dependent du futur, stream impossible sans lag 1 bar.

Module batch INTOUCHE (additive-only).

Auteur : Phase 3b semaine 3 (2026-05-13)
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import timezone as dt_tz
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from phase_b_plus_engine import VOLUME_THRESHOLD, NEWS_TIMES_ET

ET = ZoneInfo("America/New_York")
TICK_SIZE = 0.25

# News mins (cache pour calc mins_since/to)
_NEWS_MINS = np.array([h * 60 + m for h, m, _ in NEWS_TIMES_ET])


@dataclass
class PhaseBPlusState:
    """State streaming Phase B+ (74 features NON-LOOKAHEAD).

    Pickle-safe : tous primitifs + deques.
    """
    symbol: str = "ES"
    threshold_vol: float = 1200.0

    # ─── Rotation / vol_spike : shift 1 + 2 ────────────────────────────────
    prev_close: Optional[float] = None
    prev_high_1: Optional[float] = None
    prev_low_1: Optional[float] = None
    prev_high_2: Optional[float] = None
    prev_low_2: Optional[float] = None

    # ─── vol_zscore 20 ─────────────────────────────────────────────────────
    vol_window: deque = field(default_factory=lambda: deque(maxlen=20))

    # ─── VWAP D anchored (reset par date_et) ───────────────────────────────
    vwap_d_date: Optional[Any] = None
    vwap_d_cum_pv: float = 0.0
    vwap_d_cum_v: float = 0.0
    vwap_d_cum_sq: float = 0.0   # sum((typical - vwap)^2 * vol)
    # Pour cross detection (close > vwap_d sur bar precedente)
    prev_above_vwap_d: Optional[bool] = None

    # ─── VWAP W anchored (reset par week_anchor 'YYYY-Www') ────────────────
    vwap_w_anchor: Optional[str] = None
    vwap_w_cum_pv: float = 0.0
    vwap_w_cum_v: float = 0.0
    vwap_w_cum_sq: float = 0.0

    # ─── VWAP M anchored (reset par month_anchor 'YYYY-MM') ────────────────
    vwap_m_anchor: Optional[str] = None
    vwap_m_cum_pv: float = 0.0
    vwap_m_cum_v: float = 0.0
    vwap_m_cum_sq: float = 0.0

    # ─── OVN session running (reset 09:30 ET) ──────────────────────────────
    ovn_session_date: Optional[Any] = None
    ovn_high_running: Optional[float] = None
    ovn_low_running: Optional[float] = None
    # Frozen apres fin OVN (mins_et=570 = 09:30 ET) jusqu'a prochaine OVN
    ovn_high_frozen: Optional[float] = None
    ovn_low_frozen: Optional[float] = None

    # ─── Opens 08:30 / 09:30 (per session date_et) ─────────────────────────
    opens_date: Optional[Any] = None
    open_830: Optional[float] = None
    open_930: Optional[float] = None


def make_phase_b_plus_state(symbol: str = "ES") -> "PhaseBPlusState":
    """Factory avec config per-symbole."""
    sym = symbol.upper().split(".")[0]
    return PhaseBPlusState(
        symbol=sym,
        threshold_vol=float(VOLUME_THRESHOLD.get(sym, 400)),
    )


def _ts_to_et(ts_event) -> Optional[Any]:
    """Convert ts_event (tz-aware ou naive) -> datetime ET."""
    if ts_event is None:
        return None
    if isinstance(ts_event, pd.Timestamp):
        ts = ts_event
    else:
        try:
            ts = pd.Timestamp(ts_event)
        except (TypeError, ValueError):
            return None
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(ET)


def add_phase_b_plus_streaming(
    row: dict,
    state: PhaseBPlusState,
    tick: float = TICK_SIZE,
) -> dict:
    """Sub-engine Phase B+ streaming — 74 features NON-LOOKAHEAD.

    Convention : caller passe tick correct pour le symbole (0.25 ES/NQ, 0.10 MGC).
    """
    out = dict(row)

    # ─── Extract inputs ────────────────────────────────────────────────────
    try:
        o = float(out["open"]) if out.get("open") is not None else np.nan
        h = float(out["high"]) if out.get("high") is not None else np.nan
        l = float(out["low"]) if out.get("low") is not None else np.nan
        c = float(out["close"]) if out.get("close") is not None else np.nan
        v = float(out["volume"]) if out.get("volume") is not None else 0.0
    except (TypeError, ValueError):
        o = h = l = c = np.nan
        v = 0.0

    ts_event = out.get("ts_event")
    ts_et = _ts_to_et(ts_event)
    if ts_et is None:
        date_et = None
        mins_et = None
        week_anchor = None
        month_anchor = None
    else:
        date_et = ts_et.date()
        mins_et = ts_et.hour * 60 + ts_et.minute
        iso = ts_et.isocalendar()
        week_anchor = f"{iso[0]}-W{iso[1]:02d}"
        month_anchor = ts_et.strftime("%Y-%m")

    # ═══════════════════════════════════════════════════════════════════════
    # A. VOLUME SPIKE + zscore 20
    # ═══════════════════════════════════════════════════════════════════════
    # vol_spike_up = (o > c[-1]) & (v > threshold)
    # vol_spike_dn = (o < c[-1]) & (v > threshold)
    vol_spike_up = 0
    vol_spike_dn = 0
    if state.prev_close is not None:
        if o > state.prev_close and v > state.threshold_vol:
            vol_spike_up = 1
        if o < state.prev_close and v > state.threshold_vol:
            vol_spike_dn = 1
    out["vol_spike_up"] = vol_spike_up
    out["vol_spike_dn"] = vol_spike_dn

    # vol_zscore_20 : rolling 20 mean + std (ddof=1), clip(-5, 5)
    state.vol_window.append(v)
    if len(state.vol_window) >= 5:
        vols = list(state.vol_window)
        mean = sum(vols) / len(vols)
        var = sum((x - mean) ** 2 for x in vols) / (len(vols) - 1)
        std = var ** 0.5
        if std > 0:
            z = (v - mean) / std
            z = max(-5.0, min(5.0, z))
            out["vol_zscore_20"] = z
        else:
            out["vol_zscore_20"] = np.nan
    else:
        out["vol_zscore_20"] = np.nan

    # ═══════════════════════════════════════════════════════════════════════
    # B. ROTATION UP / DOWN
    # ═══════════════════════════════════════════════════════════════════════
    # rotation_up = (o > c[-1]) & (h > h[-2])
    # rotation_dn = (o < c[-1]) & (l < l[-2])
    rot_up = 0
    rot_dn = 0
    if state.prev_close is not None and state.prev_high_2 is not None:
        if o > state.prev_close and h > state.prev_high_2:
            rot_up = 1
    if state.prev_close is not None and state.prev_low_2 is not None:
        if o < state.prev_close and l < state.prev_low_2:
            rot_dn = 1
    out["rotation_up"] = rot_up
    out["rotation_dn"] = rot_dn

    # ═══════════════════════════════════════════════════════════════════════
    # C. VWAP D (anchored daily) + SD1/2/3 bands + cross
    # ═══════════════════════════════════════════════════════════════════════
    if date_et != state.vwap_d_date:
        state.vwap_d_date = date_et
        state.vwap_d_cum_pv = 0.0
        state.vwap_d_cum_v = 0.0
        state.vwap_d_cum_sq = 0.0
        # FIX : NE PAS reset prev_above_vwap_d au cross-day (batch above_d.shift(1)
        # traverse les jours sans reset). Le reset au cross-day cassait la parite
        # sur cross_dn (bar 0 de chaque nouvelle session declenchait fillna logic).

    if not (np.isnan(h) or np.isnan(l) or np.isnan(c)) and v > 0:
        typical = (h + l + c) / 3
        state.vwap_d_cum_pv += typical * v
        state.vwap_d_cum_v += v
        vwap_d = state.vwap_d_cum_pv / state.vwap_d_cum_v
        # SD : accumule (typical - vwap_d_current)^2 * vol APRES update
        # batch fait sq_diff = (typical - vwap)^2 * v puis cumsum
        # En stream, vwap est current donc on accumule avec vwap actuel
        # NB: difference subtile vs batch qui utilise vwap_t a chaque etape
        # mais cum_sq = sum((typical_i - vwap_i)^2 * v_i) -> meme math
        state.vwap_d_cum_sq += (typical - vwap_d) ** 2 * v
        var = state.vwap_d_cum_sq / state.vwap_d_cum_v
        sd = (max(0.0, var)) ** 0.5
    else:
        vwap_d = state.vwap_d_cum_pv / state.vwap_d_cum_v if state.vwap_d_cum_v > 0 else np.nan
        sd = 0.0 if state.vwap_d_cum_v > 0 else np.nan

    out["vwap_d"] = vwap_d if state.vwap_d_cum_v > 0 else np.nan
    for n in (1, 2, 3):
        out[f"vwap_d_sd{n}u"] = vwap_d + n * sd if not np.isnan(vwap_d) else np.nan
        out[f"vwap_d_sd{n}d"] = vwap_d - n * sd if not np.isnan(vwap_d) else np.nan

    # dist_vwap_d_pct, sd1u/d, sd2u/d
    # FIX BUG D 15/05/2026 : convention unique (level - close) compliant DMP C++
    if not np.isnan(c) and c > 0 and not np.isnan(vwap_d):
        out["dist_vwap_d_pct"] = (vwap_d - c) / c * 100
        out["dist_vwap_d_sd1u_pct"] = (out["vwap_d_sd1u"] - c) / c * 100
        out["dist_vwap_d_sd1d_pct"] = (out["vwap_d_sd1d"] - c) / c * 100
        out["dist_vwap_d_sd2u_pct"] = (out["vwap_d_sd2u"] - c) / c * 100
        out["dist_vwap_d_sd2d_pct"] = (out["vwap_d_sd2d"] - c) / c * 100
    else:
        for k in ("dist_vwap_d_pct", "dist_vwap_d_sd1u_pct", "dist_vwap_d_sd1d_pct",
                  "dist_vwap_d_sd2u_pct", "dist_vwap_d_sd2d_pct"):
            out[k] = np.nan

    # vwap_d_cross_up/dn (vs prev bar)
    # Mirror batch asymetrie :
    #   cross_up = above & ~above.shift(1).fillna(above)  -> au bar 0 : above & ~above = False
    #   cross_dn = ~above & above.shift(1).fillna(~above) -> au bar 0 : ~above & ~above = ~above
    # Asymetrique mais c'est le batch (bug ?). On reproduit pour parite.
    above_d_curr = (not np.isnan(c)) and (not np.isnan(vwap_d)) and (c > vwap_d)
    if state.prev_above_vwap_d is None:
        # Premier bar : reproduire batch fillna(...) different cross_up vs cross_dn
        out["vwap_d_cross_up"] = 0  # batch : above & ~above = False
        out["vwap_d_cross_dn"] = 1 if not above_d_curr else 0  # batch : ~above & ~above = ~above
    else:
        out["vwap_d_cross_up"] = 1 if (above_d_curr and not state.prev_above_vwap_d) else 0
        out["vwap_d_cross_dn"] = 1 if (not above_d_curr and state.prev_above_vwap_d) else 0
    state.prev_above_vwap_d = above_d_curr

    # vwap_d_sd1/2 above/below
    out["vwap_d_sd1_above"] = 1 if (not np.isnan(c) and not np.isnan(out["vwap_d_sd1u"]) and c > out["vwap_d_sd1u"]) else 0
    out["vwap_d_sd1_below"] = 1 if (not np.isnan(c) and not np.isnan(out["vwap_d_sd1d"]) and c < out["vwap_d_sd1d"]) else 0
    out["vwap_d_sd2_above"] = 1 if (not np.isnan(c) and not np.isnan(out["vwap_d_sd2u"]) and c > out["vwap_d_sd2u"]) else 0
    out["vwap_d_sd2_below"] = 1 if (not np.isnan(c) and not np.isnan(out["vwap_d_sd2d"]) and c < out["vwap_d_sd2d"]) else 0

    # ═══════════════════════════════════════════════════════════════════════
    # D. VWAP W (weekly) + SD
    # ═══════════════════════════════════════════════════════════════════════
    if week_anchor != state.vwap_w_anchor:
        state.vwap_w_anchor = week_anchor
        state.vwap_w_cum_pv = 0.0
        state.vwap_w_cum_v = 0.0
        state.vwap_w_cum_sq = 0.0
    if not (np.isnan(h) or np.isnan(l) or np.isnan(c)) and v > 0:
        typical = (h + l + c) / 3
        state.vwap_w_cum_pv += typical * v
        state.vwap_w_cum_v += v
        vwap_w = state.vwap_w_cum_pv / state.vwap_w_cum_v
        state.vwap_w_cum_sq += (typical - vwap_w) ** 2 * v
        sd_w = (max(0.0, state.vwap_w_cum_sq / state.vwap_w_cum_v)) ** 0.5
    else:
        vwap_w = state.vwap_w_cum_pv / state.vwap_w_cum_v if state.vwap_w_cum_v > 0 else np.nan
        sd_w = 0.0 if state.vwap_w_cum_v > 0 else np.nan

    out["vwap_w"] = vwap_w if state.vwap_w_cum_v > 0 else np.nan
    for n in (1, 2, 3):
        out[f"vwap_w_sd{n}u"] = vwap_w + n * sd_w if not np.isnan(vwap_w) else np.nan
        out[f"vwap_w_sd{n}d"] = vwap_w - n * sd_w if not np.isnan(vwap_w) else np.nan
    # FIX BUG D 15/05/2026 : convention unique (level - close) compliant DMP C++
    if not np.isnan(c) and c > 0 and not np.isnan(vwap_w):
        out["dist_vwap_w_pct"] = (vwap_w - c) / c * 100
        out["dist_vwap_w_sd1u_pct"] = (out["vwap_w_sd1u"] - c) / c * 100
        out["dist_vwap_w_sd1d_pct"] = (out["vwap_w_sd1d"] - c) / c * 100
        out["dist_vwap_w_sd2u_pct"] = (out["vwap_w_sd2u"] - c) / c * 100
        out["dist_vwap_w_sd2d_pct"] = (out["vwap_w_sd2d"] - c) / c * 100
    else:
        for k in ("dist_vwap_w_pct", "dist_vwap_w_sd1u_pct", "dist_vwap_w_sd1d_pct",
                  "dist_vwap_w_sd2u_pct", "dist_vwap_w_sd2d_pct"):
            out[k] = np.nan

    # ═══════════════════════════════════════════════════════════════════════
    # E. VWAP M (monthly) + SD
    # ═══════════════════════════════════════════════════════════════════════
    if month_anchor != state.vwap_m_anchor:
        state.vwap_m_anchor = month_anchor
        state.vwap_m_cum_pv = 0.0
        state.vwap_m_cum_v = 0.0
        state.vwap_m_cum_sq = 0.0
    if not (np.isnan(h) or np.isnan(l) or np.isnan(c)) and v > 0:
        typical = (h + l + c) / 3
        state.vwap_m_cum_pv += typical * v
        state.vwap_m_cum_v += v
        vwap_m = state.vwap_m_cum_pv / state.vwap_m_cum_v
        state.vwap_m_cum_sq += (typical - vwap_m) ** 2 * v
        sd_m = (max(0.0, state.vwap_m_cum_sq / state.vwap_m_cum_v)) ** 0.5
    else:
        vwap_m = state.vwap_m_cum_pv / state.vwap_m_cum_v if state.vwap_m_cum_v > 0 else np.nan
        sd_m = 0.0 if state.vwap_m_cum_v > 0 else np.nan

    out["vwap_m"] = vwap_m if state.vwap_m_cum_v > 0 else np.nan
    for n in (1, 2, 3):
        out[f"vwap_m_sd{n}u"] = vwap_m + n * sd_m if not np.isnan(vwap_m) else np.nan
        out[f"vwap_m_sd{n}d"] = vwap_m - n * sd_m if not np.isnan(vwap_m) else np.nan
    # FIX BUG D 15/05/2026 : convention unique (level - close) compliant DMP C++
    if not np.isnan(c) and c > 0 and not np.isnan(vwap_m):
        out["dist_vwap_m_pct"] = (vwap_m - c) / c * 100
        out["dist_vwap_m_sd1u_pct"] = (out["vwap_m_sd1u"] - c) / c * 100
        out["dist_vwap_m_sd1d_pct"] = (out["vwap_m_sd1d"] - c) / c * 100
        out["dist_vwap_m_sd2u_pct"] = (out["vwap_m_sd2u"] - c) / c * 100
        out["dist_vwap_m_sd2d_pct"] = (out["vwap_m_sd2d"] - c) / c * 100
    else:
        for k in ("dist_vwap_m_pct", "dist_vwap_m_sd1u_pct", "dist_vwap_m_sd1d_pct",
                  "dist_vwap_m_sd2u_pct", "dist_vwap_m_sd2d_pct"):
            out[k] = np.nan

    # ═══════════════════════════════════════════════════════════════════════
    # F. OVN HIGH/LOW (overnight 18:00 ET -> 09:30 ET)
    # ═══════════════════════════════════════════════════════════════════════
    # is_ovn = mins_et >= 1080 OR mins_et < 570
    # Trading day session = date_et+1 si mins_et >= 1080 sinon date_et
    if mins_et is not None and date_et is not None:
        is_ovn_active = (mins_et >= 1080) or (mins_et < 570)
        if mins_et >= 1080:
            # OVN evening : trading session = date_et + 1
            ovn_sess_date = ts_et.date() + pd.Timedelta(days=1)
            ovn_sess_date = ovn_sess_date.date() if hasattr(ovn_sess_date, "date") else ovn_sess_date
        else:
            ovn_sess_date = date_et

        # Reset OVN si nouvelle session OVN
        if ovn_sess_date != state.ovn_session_date:
            state.ovn_session_date = ovn_sess_date
            state.ovn_high_running = None
            state.ovn_low_running = None
            state.ovn_high_frozen = None
            state.ovn_low_frozen = None

        if is_ovn_active and not (np.isnan(h) or np.isnan(l)):
            if state.ovn_high_running is None or h > state.ovn_high_running:
                state.ovn_high_running = h
            if state.ovn_low_running is None or l < state.ovn_low_running:
                state.ovn_low_running = l
        else:
            # OVN terminee (mins_et entre 570 et 1080 du JOUR de trading)
            # Freeze les valeurs running une seule fois (1ere bar hors OVN)
            if (state.ovn_high_frozen is None and state.ovn_high_running is not None):
                state.ovn_high_frozen = state.ovn_high_running
                state.ovn_low_frozen = state.ovn_low_running

        # Output : ovn_high/low = frozen quand dispo, NaN sinon
        if is_ovn_active:
            out["ovn_high"] = np.nan
            out["ovn_low"] = np.nan
            out["ovn_range_ticks"] = np.nan
            out["dist_ovn_high_pct"] = np.nan
            out["dist_ovn_low_pct"] = np.nan
            out["ovn_broken_up"] = 0
            out["ovn_broken_dn"] = 0
        else:
            ovn_h = state.ovn_high_frozen
            ovn_l = state.ovn_low_frozen
            out["ovn_high"] = ovn_h if ovn_h is not None else np.nan
            out["ovn_low"] = ovn_l if ovn_l is not None else np.nan
            if ovn_h is not None and ovn_l is not None:
                out["ovn_range_ticks"] = round((ovn_h - ovn_l) / tick)
                if not np.isnan(c) and c > 0:
                    out["dist_ovn_high_pct"] = (c - ovn_h) / c * 100
                    out["dist_ovn_low_pct"] = (c - ovn_l) / c * 100
                else:
                    out["dist_ovn_high_pct"] = np.nan
                    out["dist_ovn_low_pct"] = np.nan
                out["ovn_broken_up"] = 1 if (not np.isnan(h) and h > ovn_h) else 0
                out["ovn_broken_dn"] = 1 if (not np.isnan(l) and l < ovn_l) else 0
            else:
                out["ovn_range_ticks"] = np.nan
                out["dist_ovn_high_pct"] = np.nan
                out["dist_ovn_low_pct"] = np.nan
                out["ovn_broken_up"] = 0
                out["ovn_broken_dn"] = 0
    else:
        # ts manquant -> tous NaN
        for k in ("ovn_high", "ovn_low", "ovn_range_ticks",
                  "dist_ovn_high_pct", "dist_ovn_low_pct"):
            out[k] = np.nan
        out["ovn_broken_up"] = 0
        out["ovn_broken_dn"] = 0

    # ═══════════════════════════════════════════════════════════════════════
    # G. OPENS 08:30 / 09:30
    # ═══════════════════════════════════════════════════════════════════════
    # open_830 = open de bar a 08:30 ET (mins_et=510), broadcast a partir 08:30
    # open_930 = open de bar a 09:30 ET (mins_et=570), broadcast a partir 09:30
    if mins_et is not None and date_et is not None:
        # Reset per session date
        if date_et != state.opens_date:
            state.opens_date = date_et
            state.open_830 = None
            state.open_930 = None
        # Capture open_830 a mins_et=510
        if mins_et == 510 and state.open_830 is None and not np.isnan(o):
            state.open_830 = o
        # Capture open_930 a mins_et=570
        if mins_et == 570 and state.open_930 is None and not np.isnan(o):
            state.open_930 = o

        # Output : NaN avant 08:30/09:30 ET (anti-leak batch fix 27/04)
        out["open_830_et"] = state.open_830 if mins_et >= 510 and state.open_830 is not None else np.nan
        out["open_930_et"] = state.open_930 if mins_et >= 570 and state.open_930 is not None else np.nan
    else:
        out["open_830_et"] = np.nan
        out["open_930_et"] = np.nan

    if not np.isnan(c) and c > 0 and not pd.isna(out["open_830_et"]):
        out["dist_open_830_pct"] = (c - out["open_830_et"]) / c * 100
        out["above_open_830"] = 1 if c > out["open_830_et"] else 0
    else:
        out["dist_open_830_pct"] = np.nan
        out["above_open_830"] = 0
    if not np.isnan(c) and c > 0 and not pd.isna(out["open_930_et"]):
        out["dist_open_930_pct"] = (c - out["open_930_et"]) / c * 100
        out["above_open_930"] = 1 if c > out["open_930_et"] else 0
    else:
        out["dist_open_930_pct"] = np.nan
        out["above_open_930"] = 0

    # ═══════════════════════════════════════════════════════════════════════
    # H. NEWS FLAGS (07:15, 07:30, 08:30, 08:45, 09:00, 09:30 ET)
    # ═══════════════════════════════════════════════════════════════════════
    if mins_et is not None:
        for h_n, m_n, name in NEWS_TIMES_ET:
            tgt = h_n * 60 + m_n
            out[f"is_{name}"] = 1 if mins_et == tgt else 0
            out[f"within_{name}_5m"] = 1 if (mins_et >= tgt and mins_et < tgt + 5) else 0
        # mins_since_news (latest news <= mins_et, default -1 si aucun)
        diffs_since = mins_et - _NEWS_MINS
        valid_since = diffs_since[diffs_since >= 0]
        out["mins_since_news"] = int(valid_since.min()) if len(valid_since) > 0 else -1
        # mins_to_next_news (next news > mins_et)
        diffs_to = _NEWS_MINS - mins_et
        valid_to = diffs_to[diffs_to > 0]
        out["mins_to_next_news"] = int(valid_to.min()) if len(valid_to) > 0 else -1
    else:
        for h_n, m_n, name in NEWS_TIMES_ET:
            out[f"is_{name}"] = 0
            out[f"within_{name}_5m"] = 0
        out["mins_since_news"] = -1
        out["mins_to_next_news"] = -1

    # ═══════════════════════════════════════════════════════════════════════
    # Update state pour bar suivante
    # ═══════════════════════════════════════════════════════════════════════
    if not np.isnan(c):
        state.prev_close = c
    state.prev_high_2 = state.prev_high_1
    state.prev_low_2 = state.prev_low_1
    if not np.isnan(h):
        state.prev_high_1 = h
    if not np.isnan(l):
        state.prev_low_1 = l

    return out
