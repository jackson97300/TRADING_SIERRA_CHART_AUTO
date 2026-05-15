"""sessions_swings_lag_streaming.py

API streaming-aware sessions_swings_engine.py - PARTIE LAG-N (17 features).
Couvre les 4 sous-fonctions avec lookahead :
  - add_swing_features_v2 (lookback N=10 centered, lag-10) - 8 features
  - add_liquidity_sweep (lag-5 confirmation reversal) - 2 features
  - add_equal_swings (depend swings detectes) - 2 features
  - add_spike_origin_features (lookback 3 only, PAS lookahead) - 5 features

CONVENTION LAG-N :
  swing_high_active_lag10 dans stream ROW i = valeur batch ROW i-10
  (= pivot confirme avec window centered [i-20, i] vu maintenant).

Pour features derivees (dist_last_swing_high_pct, bars_since) :
  Stream emit a ROW i la valeur "distance/bars depuis le dernier pivot
  CONFIRME jusqu'a present" (= pivot j tel que j+10 <= i, soit j <= i-10).
  Parite avec batch[i-10] sur features booleens (exact). Parite approximative
  sur dist_*_pct (close[i] vs close[i-10] differs).

Spike origin features : SANS lag (lookback 3 only, pas lookahead).

DIVERGENCE SEMANTIQUE BATCH/STREAM DOCUMENTEE (liquidity_sweep_*_lag5) :
  Batch utilise swing_h_price[i] = ffilled depuis dernier swing detecte
  avec LOOKAHEAD (= batch voit le futur pour confirmer pivot).
  Stream utilise state.last_swing_high.price = dernier swing CONFIRME
  (= lag-10, sans lookahead - C'EST LE COMPORTEMENT LIVE REEL).

  Consequence : stream emit plus de sweeps (swing_h_price plus ancien
  -> break plus facile). Ex : 4x plus de fires sur synth 1440 bars.

  Cette divergence est INHERENTE a la convention LAG-N pour les features
  derivees. Le batch est inatteignable en inference (lookahead impossible).
  Stream = comportement bot live correct.

  DISTRIBUTION SHIFT ML : training batch vs inference stream sur les
  sweep_*_lag5 features. ml-trainer review obligatoire AVANT deploy live
  (similar pattern : volume_profile commit 0a6cf7b).

  Mirror pattern aussi dans dist_last_swing_high/low_pct, bars_since_*.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, List, Optional

import numpy as np
import pandas as pd

from extension_lines_manager import ExtensionLineBuffer
from sessions_swings_engine import (
    SWING_LOOKBACK,
    SWING_MIN_PROMINENCE_PCT,
    LIQUIDITY_SWEEP_WINDOW,
    EQUAL_THRESHOLD_TICKS,
    SPIKE_ROC_THRESHOLD_PCT,
    SPIKE_WINDOW_BARS,
)

try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size


@dataclass
class SwingPivot:
    """Pivot detecte (high ou low) pour state."""
    bar_idx: int
    price: float
    session_id: int


@dataclass
class PendingSweep:
    """Pending sweep awaiting reversal confirmation."""
    break_bar_idx: int       # bar i ou le break a eu lieu
    swing_price: float        # prix du swing casse
    side: str                 # 'high' ou 'low'


@dataclass
class SessionsSwingsLagState:
    """State streaming sessions_swings LAG-N.

    Pickle-safe : deques + dataclasses primitives.
    """
    symbol: str = "ES"
    tick: float = 0.25
    n_bars_swing: int = SWING_LOOKBACK
    min_prominence_pct: float = SWING_MIN_PROMINENCE_PCT
    sweep_window: int = LIQUIDITY_SWEEP_WINDOW
    equal_threshold_ticks: int = 10
    spike_threshold_pct: float = SPIKE_ROC_THRESHOLD_PCT
    spike_window_bars: int = SPIKE_WINDOW_BARS

    # Swing window centered : maxlen=2*N+1=21 bars
    # Bar du milieu (idx N=10) est candidat pivot quand le deque est plein
    swing_window_high: deque = field(default_factory=lambda: deque(maxlen=21))
    swing_window_low: deque = field(default_factory=lambda: deque(maxlen=21))
    swing_window_close: deque = field(default_factory=lambda: deque(maxlen=21))
    swing_window_sid: deque = field(default_factory=lambda: deque(maxlen=21))
    swing_window_bar_idx: deque = field(default_factory=lambda: deque(maxlen=21))

    # Last swing detecte (confirme)
    last_swing_high: Optional[SwingPivot] = None
    last_swing_low: Optional[SwingPivot] = None
    # Previous swing pour equal swings comparison
    prev_swing_high_price: Optional[float] = None
    prev_swing_low_price: Optional[float] = None

    # Pending sweeps awaiting reversal (window=5)
    # Liste de PendingSweep, on check chaque bar si close confirme reversal
    pending_sweeps_high: list = field(default_factory=list)
    pending_sweeps_low: list = field(default_factory=list)

    # Spike origin : window=3 lookback
    spike_window_close: deque = field(default_factory=lambda: deque(maxlen=4))
    spike_window_open: deque = field(default_factory=lambda: deque(maxlen=4))
    spike_buf: ExtensionLineBuffer = field(default_factory=ExtensionLineBuffer)
    last_spike_bar_idx: int = -1

    # Compteur global bars vues
    bar_idx: int = 0


def make_sessions_swings_lag_state(symbol: str = "ES") -> "SessionsSwingsLagState":
    """Factory per-symbole."""
    sym = symbol.upper().split(".")[0]
    return SessionsSwingsLagState(
        symbol=sym,
        tick=_get_tick_size(sym),
        equal_threshold_ticks=EQUAL_THRESHOLD_TICKS.get(sym, 10),
    )


def add_sessions_swings_lag_streaming(
    row: dict,
    state: SessionsSwingsLagState,
    cluster_pct: float = 0.2,
) -> dict:
    """Sub-engine streaming sessions_swings LAG-N - 17 features.

    Args:
        row : dict avec open, high, low, close + session_id (depuis simple stream).
        state : SessionsSwingsLagState mutable.

    Returns:
        dict row + 17 features lag.
    """
    out = dict(row)

    try:
        o = float(out["open"]) if out.get("open") is not None else np.nan
        h = float(out["high"]) if out.get("high") is not None else np.nan
        l = float(out["low"]) if out.get("low") is not None else np.nan
        c = float(out["close"]) if out.get("close") is not None else np.nan
    except (TypeError, ValueError):
        o = h = l = c = np.nan

    sid = out.get("session_id", -1)
    if sid is None:
        sid = -1
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        sid = -1

    bar_idx = state.bar_idx

    # ─── 1. SWING DETECTION (window centered N=10) ─────────────────────────
    # Append bar courante au deque
    state.swing_window_high.append(h)
    state.swing_window_low.append(l)
    state.swing_window_close.append(c)
    state.swing_window_sid.append(sid)
    state.swing_window_bar_idx.append(bar_idx)

    swing_h_active = 0
    swing_l_active = 0

    # Pivot candidate = milieu du deque (idx N=10) quand deque plein (21 bars)
    N = state.n_bars_swing
    if len(state.swing_window_high) == 2 * N + 1:
        # Bar candidate = idx N dans le deque
        pivot_h = state.swing_window_high[N]
        pivot_l = state.swing_window_low[N]
        pivot_close = state.swing_window_close[N]
        pivot_sid = state.swing_window_sid[N]
        pivot_bar_idx = state.swing_window_bar_idx[N]

        win_h_list = [x for x in state.swing_window_high if not np.isnan(x)]
        win_l_list = [x for x in state.swing_window_low if not np.isnan(x)]

        if (
            win_h_list and win_l_list
            and not np.isnan(pivot_h) and not np.isnan(pivot_close)
            and pivot_h > 0 and pivot_close > 0
        ):
            win_h_max = max(win_h_list)
            win_l_min = min(win_l_list)
            # Swing high : extremum local + prominence >= 0.1% close
            if pivot_h >= win_h_max:
                prominence = (pivot_h - win_l_min) / pivot_close * 100
                if prominence >= state.min_prominence_pct:
                    swing_h_active = 1
                    # Update equal swings prev BEFORE last
                    if state.last_swing_high is not None:
                        state.prev_swing_high_price = state.last_swing_high.price
                    state.last_swing_high = SwingPivot(
                        bar_idx=pivot_bar_idx,
                        price=pivot_h,
                        session_id=pivot_sid,
                    )
            # Swing low : extremum local + prominence
            if pivot_l <= win_l_min:
                prominence = (win_h_max - pivot_l) / pivot_close * 100
                if prominence >= state.min_prominence_pct:
                    swing_l_active = 1
                    if state.last_swing_low is not None:
                        state.prev_swing_low_price = state.last_swing_low.price
                    state.last_swing_low = SwingPivot(
                        bar_idx=pivot_bar_idx,
                        price=pivot_l,
                        session_id=pivot_sid,
                    )

    out["swing_high_active_lag10"] = swing_h_active
    out["swing_low_active_lag10"] = swing_l_active

    # ─── 2. DIST/BARS_SINCE/SESSION du dernier swing confirme ──────────────
    # Fix code-reviewer Pass 4a R2 P4 (15/05) : expose aussi dist_swing_high/low
    # POINTS (raw) en plus du _pct, pour rolling_features ctx_div_at_swing /
    # div_at_key_level_ticks qui consomment POINTS. Sans : 2 ctx_* mortes.
    if state.last_swing_high is not None and not np.isnan(c) and c > 0:
        out["dist_last_swing_high_pct"] = (
            (c - state.last_swing_high.price) / c * 100
        )
        out["dist_swing_high"] = c - state.last_swing_high.price  # POINTS raw
        out["bars_since_last_swing_high"] = bar_idx - state.last_swing_high.bar_idx
        out["last_swing_high_session"] = state.last_swing_high.session_id
    else:
        out["dist_last_swing_high_pct"] = np.nan
        out["dist_swing_high"] = np.nan
        out["bars_since_last_swing_high"] = -1
        out["last_swing_high_session"] = -1

    if state.last_swing_low is not None and not np.isnan(c) and c > 0:
        out["dist_last_swing_low_pct"] = (
            (c - state.last_swing_low.price) / c * 100
        )
        out["dist_swing_low"] = c - state.last_swing_low.price  # POINTS raw
        out["bars_since_last_swing_low"] = bar_idx - state.last_swing_low.bar_idx
        out["last_swing_low_session"] = state.last_swing_low.session_id
    else:
        out["dist_last_swing_low_pct"] = np.nan
        out["dist_swing_low"] = np.nan
        out["bars_since_last_swing_low"] = -1
        out["last_swing_low_session"] = -1

    # ─── 3. EQUAL SWINGS (compare current swing avec previous) ─────────────
    threshold_pts = state.equal_threshold_ticks * state.tick
    eq_h = 0
    eq_l = 0
    if swing_h_active == 1 and state.prev_swing_high_price is not None:
        if abs(state.last_swing_high.price - state.prev_swing_high_price) <= threshold_pts:
            eq_h = 1
    if swing_l_active == 1 and state.prev_swing_low_price is not None:
        if abs(state.last_swing_low.price - state.prev_swing_low_price) <= threshold_pts:
            eq_l = 1
    out["equal_highs_detected"] = eq_h
    out["equal_lows_detected"] = eq_l

    # ─── 4. LIQUIDITY SWEEP (window=5 reversal confirmation) ───────────────
    # Pour chaque bar i avec break (high > last_swing_high.price) :
    #   on enregistre PendingSweep
    #   apres window=5 bars, on check close[i+5] < last_swing_high.price (reversal)
    sweep_h = 0
    sweep_l = 0

    # Add new pending sweeps (current bar break of last swing high/low)
    if state.last_swing_high is not None and not np.isnan(h):
        if h > state.last_swing_high.price:
            # Break du swing high. Si close[i+window] < swing_h -> sweep
            state.pending_sweeps_high.append(PendingSweep(
                break_bar_idx=bar_idx,
                swing_price=state.last_swing_high.price,
                side="high",
            ))
    if state.last_swing_low is not None and not np.isnan(l):
        if l < state.last_swing_low.price:
            state.pending_sweeps_low.append(PendingSweep(
                break_bar_idx=bar_idx,
                swing_price=state.last_swing_low.price,
                side="low",
            ))

    # Check pending sweeps : si window=5 ecoule, evaluer reversal
    # Le sweep_h_lag5 du batch est emis au bar du BREAK (= bar i), pas a bar i+5.
    # En stream : on ne peut le savoir qu'a bar i+5. Donc on emit dans ROW i+5
    # la valeur "1 si break a bar i et reversal confirme a bar i+5".
    # Pour la PARITE batch test : stream[i+5].sweep_h_lag5 == batch[i].sweep_h_lag5.
    resolved_sweeps_h = []
    for ps in state.pending_sweeps_high:
        bars_elapsed = bar_idx - ps.break_bar_idx
        if bars_elapsed >= state.sweep_window:
            # Window ecoulee - evaluate reversal
            if not np.isnan(c) and c < ps.swing_price:
                sweep_h = 1
            resolved_sweeps_h.append(ps)
    for ps in resolved_sweeps_h:
        state.pending_sweeps_high.remove(ps)

    resolved_sweeps_l = []
    for ps in state.pending_sweeps_low:
        bars_elapsed = bar_idx - ps.break_bar_idx
        if bars_elapsed >= state.sweep_window:
            if not np.isnan(c) and c > ps.swing_price:
                sweep_l = 1
            resolved_sweeps_l.append(ps)
    for ps in resolved_sweeps_l:
        state.pending_sweeps_low.remove(ps)

    out["liquidity_sweep_high_lag5"] = sweep_h
    out["liquidity_sweep_low_lag5"] = sweep_l

    # ─── 5. SPIKE ORIGIN (lookback 3 only, PAS lookahead) ──────────────────
    state.spike_window_close.append(c)
    state.spike_window_open.append(o)

    # Update buffer : deactivate zones touchees par cette bar
    if not (np.isnan(l) or np.isnan(h)):
        state.spike_buf.update_with_bar(bar_idx, l, h)

    spike_det = 0
    W = state.spike_window_bars
    if (
        len(state.spike_window_close) == W + 1
        and not np.isnan(c)
    ):
        c_back = state.spike_window_close[0]  # close[i-W]
        if c_back is not None and not np.isnan(c_back) and c_back > 0:
            roc = abs(c - c_back) / c_back * 100
            if roc >= state.spike_threshold_pct:
                spike_det = 1
                # Origin = open de la 1ere bar du spike (= bar i-W+1 = idx 1 dans deque)
                origin_open = state.spike_window_open[1] if len(state.spike_window_open) > 1 else state.spike_window_open[0]
                if origin_open is not None and not np.isnan(origin_open):
                    state.spike_buf.add_zone(bar_idx, [float(origin_open)], "buy")
                state.last_spike_bar_idx = bar_idx

    out["spike_detected_lag3"] = spike_det
    n_active = sum(1 for z in state.spike_buf.zones if z.active)
    out["n_spike_origins_active"] = n_active

    if not np.isnan(c) and c > 0:
        active_zones = [z for z in state.spike_buf.zones if z.active]
        if active_zones:
            distances = []
            for z in active_zones:
                if c < z.min_price:
                    d = z.min_price - c
                elif c > z.max_price:
                    d = -(c - z.max_price)
                else:
                    d = 0
                distances.append(d)
            d_min = min(distances, key=abs)
            out["dist_last_spike_origin_pct"] = (d_min / c) * 100
        else:
            out["dist_last_spike_origin_pct"] = np.nan
        # Cluster
        cluster_range = c * (cluster_pct / 100)
        cluster_low = c - cluster_range
        cluster_high = c + cluster_range
        out["n_spike_origins_cluster_within_0_2pct"] = sum(
            1 for z in state.spike_buf.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
    else:
        out["dist_last_spike_origin_pct"] = np.nan
        out["n_spike_origins_cluster_within_0_2pct"] = 0

    if state.last_spike_bar_idx >= 0:
        out["bars_since_last_spike"] = bar_idx - state.last_spike_bar_idx
    else:
        out["bars_since_last_spike"] = -1

    state.bar_idx += 1
    return out
