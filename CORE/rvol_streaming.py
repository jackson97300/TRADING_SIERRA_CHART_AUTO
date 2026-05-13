"""rvol_streaming.py

API streaming-aware du module CORE/rvol.py (RvolEngine).
Reproduit 10 features rvol_* avec rolling 20 sur volume.

Convention pipeline :
  add_rvol_inputs_streaming(row, state)         # phase_b_helpers (range, delta_pct, ...)
  add_rvol_engine_streaming(row, state)         # CE MODULE (rvol_* signaux)

Features (10) :
  rvol, rvol_zscore, rvol_regime, rvol_buy, rvol_sell, rvol_buy_strong,
  rvol_sell_strong, rvol_absorb_buy, rvol_absorb_sell, rvol_extreme

Module batch INTOUCHE (additive-only).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from rvol import (
    RVOL_LOOKBACK,
    RVOL_SPIKE_THRESHOLD,
    RVOL_EXTREME_THRESHOLD,
    DELTA_CONFIRM_PCT,
    EXCLUDE_AFTER_EDT_HOUR,
    EXCLUDE_AFTER_EDT_MIN,
)


@dataclass
class RvolEngineState:
    """State sub-engine RvolEngine streaming.

    Pickle-safe : deque + scalars primitifs.
    """
    vol_window: deque = field(
        default_factory=lambda: deque(maxlen=RVOL_LOOKBACK)
    )
    lookback: int = RVOL_LOOKBACK
    spike_threshold: float = RVOL_SPIKE_THRESHOLD
    delta_confirm: float = DELTA_CONFIRM_PCT
    filter_close: bool = True


def add_rvol_engine_streaming(
    row: dict,
    state: RvolEngineState,
) -> dict:
    """Sub-engine RvolEngine — 10 features streaming.

    Args:
        row : dict avec total_vol, delta_pct, finish_strength, ts.
              Requiert add_rvol_inputs_streaming AVANT (delta_pct, finish_strength).
        state : RvolEngineState mutable.

    Returns:
        dict row + 10 features rvol_*.
    """
    out = dict(row)

    # ─── Inputs (safe cast) ────────────────────────────────────────────────
    try:
        vol = float(out.get("total_vol", 0))
        if pd.isna(vol):
            vol = 0.0
    except (TypeError, ValueError):
        vol = 0.0
    try:
        delta_pct = float(out.get("delta_pct", 0))
        if pd.isna(delta_pct):
            delta_pct = 0.0
    except (TypeError, ValueError):
        delta_pct = 0.0
    try:
        finish = float(out.get("finish_strength", 0))
        if pd.isna(finish):
            finish = 0.0
    except (TypeError, ValueError):
        finish = 0.0
    ts = out.get("ts")

    # ─── Append vol au window ──────────────────────────────────────────────
    state.vol_window.append(vol)

    # ─── 1. RVOL = vol / SMA(vol, lookback) ────────────────────────────────
    # Mirror batch : rolling(lookback, min_periods=5).mean()
    if len(state.vol_window) >= 5:
        vol_sma = sum(state.vol_window) / len(state.vol_window)
        if vol_sma > 0:
            rvol = vol / vol_sma
        else:
            rvol = 1.0  # mirror batch np.where fallback
    else:
        # batch min_periods=5 -> NaN avant 5 bars -> vol_sma=NaN -> where NaN<>0 = False -> 1.0
        vol_sma = np.nan
        rvol = 1.0
    out["rvol"] = rvol

    # ─── 2. RVOL zscore ────────────────────────────────────────────────────
    if len(state.vol_window) >= 5:
        # std avec ddof=1 (pandas default)
        m = vol_sma
        var = sum((v - m) ** 2 for v in state.vol_window) / (len(state.vol_window) - 1)
        vol_std = var ** 0.5
        if vol_std > 0:
            out["rvol_zscore"] = (vol - m) / vol_std
        else:
            out["rvol_zscore"] = 0.0
    else:
        out["rvol_zscore"] = 0.0

    # ─── 3. Regime (0=low, 1=normal, 2=high, 3=spike, 4=extreme) ───────────
    # Mirror batch : assignations sequentielles avec ecrasement
    regime = 1  # normal par defaut
    if rvol < 0.7:
        regime = 0
    if rvol > 1.3:
        regime = 2
    if rvol > state.spike_threshold:
        regime = 3
    if rvol > RVOL_EXTREME_THRESHOLD:
        regime = 4
    out["rvol_regime"] = regime

    is_spike = rvol >= state.spike_threshold

    # ─── 4. Tier 1 signaux directionnels ───────────────────────────────────
    out["rvol_buy"] = 1 if (is_spike and delta_pct > 0.05) else 0
    out["rvol_sell"] = 1 if (is_spike and delta_pct < -0.05) else 0

    # ─── 5. Tier 2 signaux confirmes (delta + finish alignes) ──────────────
    out["rvol_buy_strong"] = 1 if (
        is_spike and delta_pct > state.delta_confirm and finish > 0
    ) else 0
    out["rvol_sell_strong"] = 1 if (
        is_spike and delta_pct < -state.delta_confirm and finish < 0
    ) else 0

    # ─── 6. Absorption (delta + finish contradictoires) ────────────────────
    out["rvol_absorb_buy"] = 1 if (
        is_spike and delta_pct < -0.05 and finish > 20
    ) else 0
    out["rvol_absorb_sell"] = 1 if (
        is_spike and delta_pct > 0.05 and finish < -20
    ) else 0

    # ─── 7. Extreme ────────────────────────────────────────────────────────
    out["rvol_extreme"] = 1 if rvol >= RVOL_EXTREME_THRESHOLD else 0

    # ─── 8. Filtre session apres 15:50 EDT ─────────────────────────────────
    # Mirror batch ligne 173-186 : annule rvol_buy/sell apres 15:50 EDT
    if state.filter_close and ts is not None:
        try:
            ts_int = int(ts)
            ts_dt = pd.to_datetime(ts_int, unit="ms", utc=True)
            edt_hour = (ts_dt.hour - 4) % 24
            edt_min = ts_dt.minute
            is_close = (
                edt_hour > EXCLUDE_AFTER_EDT_HOUR
                or (edt_hour == EXCLUDE_AFTER_EDT_HOUR and edt_min >= EXCLUDE_AFTER_EDT_MIN)
            )
            if is_close:
                out["rvol_buy"] = 0
                out["rvol_sell"] = 0
        except (TypeError, ValueError):
            pass

    return out
