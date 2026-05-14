"""phase_b_rolling_inputs_streaming.py

API streaming-aware du module CORE/phase_b_rolling_inputs.py (Pass 4a Phase 3c).

Resout la dette B5 code-reviewer Pass 3b R2 : 18 inputs amont manquants pour
rolling_features streaming (atr, vwap_slope_10, dist_vwap_d, vwap_d_side,
momentum_5b, cvd_day, delta_day_dir, dist_ib_high/low, ib_range_atr,
dist_sess_high/low, poc_position, va_position_pct, inside_cur_va, dist_cur_*).

Module batch (`phase_b_rolling_inputs.py`) INTOUCHE (additive-only). Sub-engines
streaming = ADDITIONNELS.

Ordre dependancy obligatoire (caller doit avoir applique AVANT) :
  - add_atr_streaming               <- high, low, close (LOT 1)
  - add_vwap_derivees_streaming     <- vwap_d (phase_b_plus Pass 4c-prereq), atr
  - add_ib_derivees_streaming       <- ib_high/low/range_ticks (Pass 4c-prereq), atr
  - add_session_derivees_streaming  <- sess_high/low (Pass 4c-prereq), is_in_*
  - add_cvd_momentum_streaming      <- delta_bar (LOT 1 Fix B2), cvd_session (Pass 3b)
                                       OU session_date_trading (Pass 4c-prereq)
  - add_vpoc_derivees_streaming     <- cur_vpoc/vah/val/inside_value_area (Pass 4c-prereq)

Convention : streaming TOLERE NaN sur inputs critiques (vs batch qui raise
KeyError). Justification : raise dans live = interruption cycle entier =
trades manques. Tolerance NaN propagee proprement vs silent fallback :
les NaN sont VISIBLES dans le payload (pas reset a 0), downstream filtre
peut detecter via `pd.isna()`. Cf code-reviewer Pass 4a R1 concern #3.

NB : si input manquant systematiquement (ex: vwap_d toujours NaN), c'est un
bug de pipeline upstream (Pass 4c-prereq) - signaler via emit log au lieu
de raise. La fail-loud production = nssm restart vide qui ne resout rien.

Auteur : MIA Trading System V2
  v1.0 (2026-05-15) : Pass 4a Phase 3c semaine 4 - resolution dette B5
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


TICK_SIZE = 0.25  # default ES/NQ
ATR_LOOKBACK = 14
VWAP_SLOPE_LOOKBACK = 10
MOMENTUM_LOOKBACK = 5


# ═══════════════════════════════════════════════════════════════════════════════
# STATES (pickle-safe : deques + Optional + primitifs)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ATRStreamingState:
    """State streaming ATR : rolling True Range + prev close."""
    tr_window: deque = field(default_factory=lambda: deque(maxlen=ATR_LOOKBACK))
    prev_close: Optional[float] = None


@dataclass
class VWAPDerivesState:
    """State streaming VWAP derivees : window vwap_d pour slope (lookback+1)."""
    vwap_d_window: deque = field(
        default_factory=lambda: deque(maxlen=VWAP_SLOPE_LOOKBACK + 1)
    )


@dataclass
class CVDMomentumState:
    """State streaming CVD/Momentum : delta_bar window 5 + cvd_day cumsum."""
    delta_window: deque = field(default_factory=lambda: deque(maxlen=MOMENTUM_LOOKBACK))
    cvd_day_running: float = 0.0
    current_session_date_trading: Optional[object] = None  # date pour reset


def make_phase_b_rolling_inputs_state(symbol: str = "ES") -> dict:
    """Factory unifiee : retourne dict des 3 states stateful (ATR + VWAP + CVD).

    Les 3 autres fonctions (ib_derivees, session_derivees, vpoc_derivees) sont
    STATELESS (transformations row-level pures).
    """
    return {
        "atr": ATRStreamingState(),
        "vwap_derives": VWAPDerivesState(),
        "cvd_momentum": CVDMomentumState(),
        "symbol": symbol.upper().split(".")[0],
        "tick": _get_tick_size(symbol.upper().split(".")[0]),
    }


def _safe_float(x) -> float:
    if x is None:
        return float("nan")
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ATR intraday streaming (True Range rolling 14 bars / tick)
# ═══════════════════════════════════════════════════════════════════════════════

def add_atr_streaming(
    row: dict,
    state: ATRStreamingState,
    tick: float = TICK_SIZE,
    lookback: int = ATR_LOOKBACK,
) -> dict:
    """Sub-engine ATR streaming.

    TR = max(high - low, |high - prev_close|, |low - prev_close|)
    ATR = mean(TR rolling lookback) / tick

    Args:
        row : dict avec high, low, close.
        state : ATRStreamingState mutable.
        tick : tick_size per-symbole.
        lookback : 14 standard.

    Returns:
        dict row + atr (float ticks).
    """
    out = dict(row)
    h = _safe_float(out.get("high"))
    l = _safe_float(out.get("low"))
    c = _safe_float(out.get("close"))

    if np.isnan(h) or np.isnan(l) or np.isnan(c):
        out["atr"] = np.nan
        return out

    # True Range
    if state.prev_close is None:
        # 1ere bar : TR = high - low (batch fait close_prev = close[0])
        tr = h - l
    else:
        pc = state.prev_close
        tr = max(h - l, abs(h - pc), abs(l - pc))

    state.tr_window.append(tr)
    state.prev_close = c

    # ATR mean rolling (min_periods=1 mirror batch)
    if state.tr_window:
        atr_points = sum(state.tr_window) / len(state.tr_window)
        out["atr"] = atr_points / tick
    else:
        out["atr"] = np.nan
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 2. VWAP derivees streaming (slope_10, dist_vwap_d, vwap_d_side, _atr)
# ═══════════════════════════════════════════════════════════════════════════════

def add_vwap_derivees_streaming(
    row: dict,
    state: VWAPDerivesState,
    tick: float = TICK_SIZE,
    lookback: int = VWAP_SLOPE_LOOKBACK,
) -> dict:
    """Sub-engine VWAP derivees streaming.

    Calcule vwap_slope_10 (raw + _atr), dist_vwap_d (raw + _atr), vwap_d_side.

    Args:
        row : dict avec vwap_d (Pass 4c-prereq phase_b_plus), close, atr.
        state : VWAPDerivesState mutable.

    Returns:
        dict row + 5 features.
    """
    out = dict(row)
    vwap_d = _safe_float(out.get("vwap_d"))
    c = _safe_float(out.get("close"))
    atr = _safe_float(out.get("atr"))

    # Init defaults NaN si inputs critiques manquants
    out["vwap_slope_10"] = np.nan
    out["dist_vwap_d"] = np.nan
    out["vwap_d_side"] = 0
    out["dist_vwap_d_atr"] = np.nan
    out["vwap_slope_10_atr"] = np.nan

    if np.isnan(vwap_d):
        # vwap_d absent (warmup ou cum_v=0) - garde defauts NaN
        # MAIS append au window pour ne pas casser le slope au prochain bar
        state.vwap_d_window.append(np.nan)
        return out

    state.vwap_d_window.append(vwap_d)

    # Slope 10 bars : (vwap_d[t] - vwap_d[t-10]) / 10
    if len(state.vwap_d_window) >= lookback + 1:
        vwap_d_prev = state.vwap_d_window[0]  # = T-10 (maxlen=11, index 0 oldest)
        if not np.isnan(vwap_d_prev):
            out["vwap_slope_10"] = (vwap_d - vwap_d_prev) / lookback

    # Distance close - vwap_d (POINTS)
    if not np.isnan(c):
        out["dist_vwap_d"] = c - vwap_d
        # Side : signe(dist)
        if out["dist_vwap_d"] > 0:
            out["vwap_d_side"] = 1
        elif out["dist_vwap_d"] < 0:
            out["vwap_d_side"] = -1
        else:
            out["vwap_d_side"] = 0

    # Versions ATR-normalisees (eviter fuite vol NQ 4x ES, FIX 27/04 quality-auditor)
    if not np.isnan(atr) and atr > 0:
        if not np.isnan(out["dist_vwap_d"]):
            out["dist_vwap_d_atr"] = out["dist_vwap_d"] / tick / atr
        if not np.isnan(out["vwap_slope_10"]):
            out["vwap_slope_10_atr"] = out["vwap_slope_10"] / tick / atr

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 3. IB derivees streaming (STATELESS : ib_range_atr, dist_ib_high/low, alias)
# ═══════════════════════════════════════════════════════════════════════════════

def add_ib_derivees_streaming(row: dict, tick: float = TICK_SIZE) -> dict:
    """Sub-engine IB derivees streaming - STATELESS.

    Calcule ib_range_atr, dist_ib_high/low (POINTS), ib_broken_down (alias V1).
    """
    out = dict(row)
    ib_range_ticks = _safe_float(out.get("ib_range_ticks"))
    atr = _safe_float(out.get("atr"))
    ib_high = _safe_float(out.get("ib_high"))
    ib_low = _safe_float(out.get("ib_low"))
    c = _safe_float(out.get("close"))

    # ib_range_atr
    if not np.isnan(ib_range_ticks) and not np.isnan(atr) and atr > 0:
        out["ib_range_atr"] = ib_range_ticks / atr
    else:
        out["ib_range_atr"] = np.nan

    # Distances POINTS
    if not np.isnan(c) and not np.isnan(ib_high):
        out["dist_ib_high"] = c - ib_high
    else:
        out["dist_ib_high"] = np.nan
    if not np.isnan(c) and not np.isnan(ib_low):
        out["dist_ib_low"] = c - ib_low
    else:
        out["dist_ib_low"] = np.nan

    # Alias V1 ib_broken_down <- ib_broken_dn (Pass 4c-prereq ib_features)
    ib_broken_dn = out.get("ib_broken_dn")
    if ib_broken_dn is not None:
        try:
            out["ib_broken_down"] = int(ib_broken_dn)
        except (TypeError, ValueError):
            out["ib_broken_down"] = 0
    else:
        out["ib_broken_down"] = 0

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Session derivees streaming (STATELESS : dist_sess, session entier, bar_*)
# ═══════════════════════════════════════════════════════════════════════════════

def add_session_derivees_streaming(row: dict) -> dict:
    """Sub-engine Session derivees streaming - STATELESS.

    Calcule dist_sess_high/low (POINTS), session entier 0/1/2/3, bar_high/low aliases.
    """
    out = dict(row)
    sess_high = _safe_float(out.get("sess_high"))
    sess_low = _safe_float(out.get("sess_low"))
    c = _safe_float(out.get("close"))
    h = _safe_float(out.get("high"))
    l = _safe_float(out.get("low"))

    # Distances POINTS
    if not np.isnan(c) and not np.isnan(sess_high):
        out["dist_sess_high"] = c - sess_high
    else:
        out["dist_sess_high"] = np.nan
    if not np.isnan(c) and not np.isnan(sess_low):
        out["dist_sess_low"] = c - sess_low
    else:
        out["dist_sess_low"] = np.nan

    # Session entier : 0=Asia, 1=London, 2=US cash, 3=US after-hours
    # Pass 3a sessions_swings_simple produit is_in_asia/london/us_cash/us_after.
    sess = -1
    if int(out.get("is_in_asia", 0) or 0) == 1:
        sess = 0
    if int(out.get("is_in_london", 0) or 0) == 1:
        sess = 1
    if int(out.get("is_in_us_cash", 0) or 0) == 1:
        sess = 2
    if int(out.get("is_in_us_after", 0) or 0) == 1:
        sess = 3
    out["session"] = sess

    # Bar aliases V1 (bar_high/low) - utiles pour delta_div_streaming Pass 3b
    if not np.isnan(h):
        out["bar_high"] = h
    if not np.isnan(l):
        out["bar_low"] = l

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CVD Momentum streaming (cvd_day cumsum session + momentum_5b rolling)
# ═══════════════════════════════════════════════════════════════════════════════

def add_cvd_momentum_streaming(row: dict, state: CVDMomentumState) -> dict:
    """Sub-engine CVD/Momentum streaming.

    Calcule cvd_day (cumsum delta_bar par session_date_trading), delta_day_dir
    (sign), momentum_5b (rolling sum 5 bars).

    Args:
        row : dict avec delta_bar (LOT 1 Fix B2) + session_date_trading
              (Pass 4c-prereq) OU cvd_session (Pass 3b - alias direct si dispo).
        state : CVDMomentumState mutable.

    Returns:
        dict row + 3 features.
    """
    out = dict(row)
    delta_bar = _safe_float(out.get("delta_bar"))
    if np.isnan(delta_bar):
        delta_bar = 0.0  # batch fillna(0)

    # Fix code-reviewer Pass 4a R2 #3 : REMOVED code mort cvd_session fast path.
    # Apres refactor ordre (Pass 4a AVANT Pass 3b), `cvd_session` produit par
    # Pass 3b session_confluence n'est JAMAIS dispo a Pass 4a -> fast path
    # ne s'activait jamais. Seul chemin reel : cumsum running par
    # session_date_trading (produit par Pass 4c-prereq AVANT Pass 4a).
    sess_d = out.get("session_date_trading")
    if sess_d != state.current_session_date_trading:
        # Nouvelle session -> reset cumsum
        state.current_session_date_trading = sess_d
        state.cvd_day_running = 0.0
    state.cvd_day_running += delta_bar
    out["cvd_day"] = state.cvd_day_running

    # delta_day_dir = sign(cvd_day)
    cvd = out["cvd_day"]
    if cvd > 0:
        out["delta_day_dir"] = 1
    elif cvd < 0:
        out["delta_day_dir"] = -1
    else:
        out["delta_day_dir"] = 0

    # momentum_5b = rolling sum delta_bar 5 bars (min_periods=1)
    state.delta_window.append(delta_bar)
    out["momentum_5b"] = float(sum(state.delta_window))

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 6. VPOC derivees streaming (STATELESS : poc_position, dist_cur_*, aliases)
# ═══════════════════════════════════════════════════════════════════════════════

def add_vpoc_derivees_streaming(row: dict) -> dict:
    """Sub-engine VPOC derivees streaming - STATELESS.

    Calcule poc_position [0,1] clampe, va_position_pct (alias), inside_cur_va
    (alias), dist_cur_vpoc/vah/val (POINTS).

    Args:
        row : dict avec close, cur_vpoc, cur_vah, cur_val, inside_value_area
              (tous produits par Pass 4c-prereq volume_profile_features).

    Returns:
        dict row + 6 features.
    """
    out = dict(row)
    c = _safe_float(out.get("close"))
    cur_vpoc = _safe_float(out.get("cur_vpoc"))
    cur_vah = _safe_float(out.get("cur_vah"))
    cur_val = _safe_float(out.get("cur_val"))

    # poc_position : (close - val) / (vah - val) clampe [0,1]
    if not np.isnan(c) and not np.isnan(cur_vah) and not np.isnan(cur_val):
        va_width = cur_vah - cur_val
        if va_width > 0:
            poc_pos = (c - cur_val) / va_width
            poc_pos = max(0.0, min(1.0, poc_pos))
            out["poc_position"] = poc_pos
        else:
            out["poc_position"] = np.nan
    else:
        out["poc_position"] = np.nan

    # va_position_pct : alias V1 de poc_position
    out["va_position_pct"] = out["poc_position"]

    # inside_cur_va : alias V1 de inside_value_area
    inside_va = out.get("inside_value_area")
    if inside_va is not None:
        try:
            out["inside_cur_va"] = int(inside_va)
        except (TypeError, ValueError):
            out["inside_cur_va"] = 0
    else:
        out["inside_cur_va"] = 0

    # Distances POINTS (close - level, signe conserve)
    if not np.isnan(c):
        out["dist_cur_vpoc"] = c - cur_vpoc if not np.isnan(cur_vpoc) else np.nan
        out["dist_cur_vah"] = c - cur_vah if not np.isnan(cur_vah) else np.nan
        out["dist_cur_val"] = c - cur_val if not np.isnan(cur_val) else np.nan
    else:
        out["dist_cur_vpoc"] = np.nan
        out["dist_cur_vah"] = np.nan
        out["dist_cur_val"] = np.nan

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE COMPLET (helper pour live_enricher)
# ═══════════════════════════════════════════════════════════════════════════════

def apply_rolling_inputs_streaming(
    row: dict,
    states: dict,
) -> dict:
    """Pipeline streaming complet 6 sous-fonctions.

    Args:
        row : dict bar courante (apres Pass 1+2+3+4c-prereq).
        states : dict produit par make_phase_b_rolling_inputs_state(symbol).

    Returns:
        dict row + 24 features (atr, vwap_*, dist_*, ib_*, sess_*, cvd_*, vpoc_*).
    """
    tick = states["tick"]
    row = add_atr_streaming(row, states["atr"], tick=tick)
    row = add_vwap_derivees_streaming(row, states["vwap_derives"], tick=tick)
    row = add_ib_derivees_streaming(row, tick=tick)
    row = add_session_derivees_streaming(row)
    row = add_cvd_momentum_streaming(row, states["cvd_momentum"])
    row = add_vpoc_derivees_streaming(row)
    return row
