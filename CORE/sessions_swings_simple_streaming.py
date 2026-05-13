"""sessions_swings_simple_streaming.py

API streaming-aware sessions_swings_engine.py - PARTIE SIMPLE (38 features).
Couvre les 4 sous-fonctions NON-LOOKAHEAD :
  - add_session_metadata_v2 (session_id v2 + is_in_*) - 7 features
  - add_session_highs_lows (running max/min per session) - 16 features
  - add_session_opens (asia/london/ny/after open + dist + above) - 12 features
  - add_premium_discount (pct_in_range, premium/discount_zone) - 3 features

Reste a porter dans commit B (sessions_swings_lag_streaming.py) :
  - add_swing_features_v2 (lag-10)
  - add_liquidity_sweep (lag-5)
  - add_equal_swings (depend swings)
  - add_spike_origin_features (lag-3, Extension Lines)

Module batch INTOUCHE (additive-only).

Auteur : Phase 3b semaine 3 (2026-05-14)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    from CORE.constants import get_tick_size as _get_tick_size
    from CORE.constants import get_session_boundaries as _get_session_boundaries
except ImportError:
    from constants import get_tick_size as _get_tick_size
    from constants import get_session_boundaries as _get_session_boundaries

ET = ZoneInfo("America/New_York")


@dataclass
class SessionsSwingsSimpleState:
    """State streaming sessions_swings simple (NON-lookahead, 38 features).

    Reset des running max/min ET opens par changement de session_date
    (= cycle CME complet Asia+London+US+After d'un meme jour de trading).
    """
    # Config per-symbole
    symbol: str = "ES"
    tick: float = 0.25
    asia_start: int = 1080      # 18:00 ET (ES/NQ default)
    london_start: int = 180     # 03:00 ET
    us_start: int = 570         # 09:30 ET (ES/NQ) ou 510 (MGC 08:30 RTH gold)
    us_after_start: int = 960   # 16:00 ET (ES/NQ) ou 810 (MGC 13:30)

    # Session tracking : current (session_date)
    current_session_date: Optional[Any] = None

    # Running highs/lows per session (4 sessions Asia/London/US/After)
    asia_high: Optional[float] = None
    asia_low: Optional[float] = None
    london_high: Optional[float] = None
    london_low: Optional[float] = None
    us_high: Optional[float] = None
    us_low: Optional[float] = None
    after_high: Optional[float] = None
    after_low: Optional[float] = None

    # Session opens (capture au 1er bar de chaque session)
    asia_open: Optional[float] = None
    london_open: Optional[float] = None
    ny_open: Optional[float] = None
    after_open: Optional[float] = None


def make_sessions_swings_simple_state(symbol: str = "ES") -> "SessionsSwingsSimpleState":
    """Factory per-symbole avec bounds session corrects."""
    sym = symbol.upper().split(".")[0]
    bounds = _get_session_boundaries(sym)
    return SessionsSwingsSimpleState(
        symbol=sym,
        tick=_get_tick_size(sym),
        asia_start=bounds["asia_start"],
        london_start=bounds["london_start"],
        us_start=bounds["us_start"],
        us_after_start=bounds["us_after_start"],
    )


def _ts_to_et(ts_event) -> Optional[Any]:
    """Convert ts_event -> datetime ET."""
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


def add_sessions_swings_simple_streaming(
    row: dict,
    state: SessionsSwingsSimpleState,
) -> dict:
    """Sub-engine streaming sessions_swings simple - 38 features NON-LOOKAHEAD.

    Args:
        row : dict avec ts_event, open, high, low, close.
              Optionnel : sess_high, sess_low (depuis phase_b_helpers) pour
              premium/discount. Si absents -> premium/discount = NaN/0.
        state : SessionsSwingsSimpleState mutable.

    Returns:
        dict row + 38 features sessions_swings simple.
    """
    out = dict(row)

    # ─── Inputs ────────────────────────────────────────────────────────────
    try:
        o = float(out["open"]) if out.get("open") is not None else np.nan
        h = float(out["high"]) if out.get("high") is not None else np.nan
        l = float(out["low"]) if out.get("low") is not None else np.nan
        c = float(out["close"]) if out.get("close") is not None else np.nan
    except (TypeError, ValueError):
        o = h = l = c = np.nan

    ts_event = out.get("ts_event")
    ts_et = _ts_to_et(ts_event)
    if ts_et is None:
        # Inputs critiques manquants - output all NaN
        for k in (
            "session_id", "is_in_asia", "is_in_london", "is_in_us_cash",
            "is_in_us_after", "session_date", "mins_et",
        ):
            out[k] = -1 if k == "session_id" else (np.nan if k in ("session_date",) else 0)
        for prefix in ("asia", "london", "us", "after"):
            out[f"{prefix}_high"] = np.nan
            out[f"{prefix}_low"] = np.nan
            out[f"dist_{prefix}_high_pct"] = np.nan
            out[f"dist_{prefix}_low_pct"] = np.nan
        for prefix in ("asia", "london", "ny", "after"):
            out[f"{prefix}_open"] = np.nan
            out[f"dist_{prefix}_open_pct"] = np.nan
            out[f"above_{prefix}_open"] = 0
        out["pct_in_range"] = np.nan
        out["premium_zone"] = 0
        out["discount_zone"] = 0
        return out

    mins_et = ts_et.hour * 60 + ts_et.minute

    # ─── 1. SESSION METADATA V2 ────────────────────────────────────────────
    # session_id selon mins_et (avec bounds per-symbole)
    if mins_et >= state.asia_start or mins_et < state.london_start:
        sid = 0  # Asia
    elif mins_et >= state.london_start and mins_et < state.us_start:
        sid = 1  # London
    elif mins_et >= state.us_start and mins_et < state.us_after_start:
        sid = 2  # US Cash
    elif mins_et >= state.us_after_start and mins_et < state.asia_start:
        sid = 3  # US After
    else:
        sid = -1

    # session_date : jour de session CME (si apres asia_start, jour suivant)
    if mins_et >= state.asia_start:
        session_date = (ts_et + pd.Timedelta(days=1)).date()
    else:
        session_date = ts_et.date()

    out["session_id"] = sid
    out["is_in_asia"] = 1 if sid == 0 else 0
    out["is_in_london"] = 1 if sid == 1 else 0
    out["is_in_us_cash"] = 1 if sid == 2 else 0
    out["is_in_us_after"] = 1 if sid == 3 else 0
    out["session_date"] = session_date
    out["mins_et"] = mins_et

    # ─── 2. RESET running highs/lows + opens si nouvelle session_date ──────
    if session_date != state.current_session_date:
        state.current_session_date = session_date
        # Reset all running stats
        state.asia_high = None
        state.asia_low = None
        state.london_high = None
        state.london_low = None
        state.us_high = None
        state.us_low = None
        state.after_high = None
        state.after_low = None
        state.asia_open = None
        state.london_open = None
        state.ny_open = None
        state.after_open = None

    # ─── 3. UPDATE running highs/lows pour la session courante ─────────────
    if not (np.isnan(h) or np.isnan(l)):
        if sid == 0:  # Asia
            if state.asia_high is None or h > state.asia_high:
                state.asia_high = h
            if state.asia_low is None or l < state.asia_low:
                state.asia_low = l
        elif sid == 1:  # London
            if state.london_high is None or h > state.london_high:
                state.london_high = h
            if state.london_low is None or l < state.london_low:
                state.london_low = l
        elif sid == 2:  # US Cash
            if state.us_high is None or h > state.us_high:
                state.us_high = h
            if state.us_low is None or l < state.us_low:
                state.us_low = l
        elif sid == 3:  # US After
            if state.after_high is None or h > state.after_high:
                state.after_high = h
            if state.after_low is None or l < state.after_low:
                state.after_low = l

    # ─── 4. CAPTURE session opens au 1er bar de chaque session ─────────────
    if mins_et == state.asia_start and state.asia_open is None and not np.isnan(o):
        state.asia_open = o
    if mins_et == state.london_start and state.london_open is None and not np.isnan(o):
        state.london_open = o
    if mins_et == state.us_start and state.ny_open is None and not np.isnan(o):
        state.ny_open = o
    if mins_et == state.us_after_start and state.after_open is None and not np.isnan(o):
        state.after_open = o

    # ─── 5. OUTPUT highs/lows + distances ──────────────────────────────────
    for prefix, attr_h, attr_l in [
        ("asia", "asia_high", "asia_low"),
        ("london", "london_high", "london_low"),
        ("us", "us_high", "us_low"),
        ("after", "after_high", "after_low"),
    ]:
        h_val = getattr(state, attr_h)
        l_val = getattr(state, attr_l)
        out[f"{prefix}_high"] = h_val if h_val is not None else np.nan
        out[f"{prefix}_low"] = l_val if l_val is not None else np.nan
        if not np.isnan(c) and c > 0:
            out[f"dist_{prefix}_high_pct"] = (
                (c - h_val) / c * 100 if h_val is not None else np.nan
            )
            out[f"dist_{prefix}_low_pct"] = (
                (c - l_val) / c * 100 if l_val is not None else np.nan
            )
        else:
            out[f"dist_{prefix}_high_pct"] = np.nan
            out[f"dist_{prefix}_low_pct"] = np.nan

    # ─── 6. OUTPUT session opens + distances + above ───────────────────────
    for prefix, attr in [
        ("asia", "asia_open"),
        ("london", "london_open"),
        ("ny", "ny_open"),
        ("after", "after_open"),
    ]:
        o_val = getattr(state, attr)
        out[f"{prefix}_open"] = o_val if o_val is not None else np.nan
        if not np.isnan(c) and c > 0 and o_val is not None:
            out[f"dist_{prefix}_open_pct"] = (c - o_val) / c * 100
            out[f"above_{prefix}_open"] = 1 if c > o_val else 0
        else:
            out[f"dist_{prefix}_open_pct"] = np.nan
            out[f"above_{prefix}_open"] = 0

    # ─── 7. PREMIUM / DISCOUNT zone (consomme sess_high/sess_low) ──────────
    # Inputs depuis phase_b_helpers (chain pipeline). Si absents -> defaults.
    sess_high = out.get("sess_high")
    sess_low = out.get("sess_low")
    if (
        sess_high is not None and sess_low is not None
        and not pd.isna(sess_high) and not pd.isna(sess_low)
        and (sess_high - sess_low) > 0
        and not np.isnan(c)
    ):
        rng = float(sess_high) - float(sess_low)
        pct = (c - float(sess_low)) / rng * 100
        pct = max(0.0, min(100.0, pct))
        out["pct_in_range"] = pct
        out["premium_zone"] = 1 if pct > 50 else 0
        out["discount_zone"] = 1 if pct < 50 else 0
    else:
        out["pct_in_range"] = 50.0  # batch default = 50 (NaN replaced)
        out["premium_zone"] = 0
        out["discount_zone"] = 0

    return out
