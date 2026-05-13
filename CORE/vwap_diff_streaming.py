"""vwap_diff_streaming.py

API streaming-aware phase_b_vwap_diff.py (5 features VWAP differentiels).
Sub-engine TRIVIAL : pure transforms row-level sur features VWAP deja
streaming (dist_vwap_d/w/m_pct depuis phase_b_plus_streaming).

Aucun state. Mirror exact batch apply_vwap_diff().

Features (5) :
  vwap_w_minus_d_pct           : trend persistence cross-timeframe
  vwap_m_minus_w_pct           : long-term trend signal
  vwap_w_sd1u_minus_d_sd1u_pct : divergence bandes hautes
  vwap_w_sd1d_minus_d_sd1d_pct : divergence bandes basses
  vwap_w_d_aligned             : bool sign alignment (regime trending fort)

Convention pipeline : appele APRES phase_b_plus_streaming (qui produit
dist_vwap_d/w/m_pct + dist_vwap_d/w/m_sd1u/d_pct).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class VwapDiffState:
    """State streaming VWAP diff - STATELESS (factory uniforme)."""
    pass


def _safe_float_nan(x) -> float:
    if x is None:
        return np.nan
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def add_vwap_diff_streaming(
    row: dict,
    state: VwapDiffState,
) -> dict:
    """Sub-engine streaming VWAP diff - 5 features stateless.

    Args:
        row : dict avec dist_vwap_d_pct, dist_vwap_w_pct, dist_vwap_m_pct,
              dist_vwap_d_sd1u_pct, dist_vwap_w_sd1u_pct,
              dist_vwap_d_sd1d_pct, dist_vwap_w_sd1d_pct
              (depuis phase_b_plus_streaming).
        state : VwapDiffState (stateless, conserve symetrie API).

    Returns:
        dict row + 5 features VWAP diff.
    """
    out = dict(row)

    d_d = _safe_float_nan(out.get("dist_vwap_d_pct"))
    d_w = _safe_float_nan(out.get("dist_vwap_w_pct"))
    d_m = _safe_float_nan(out.get("dist_vwap_m_pct"))
    d_d_sd1u = _safe_float_nan(out.get("dist_vwap_d_sd1u_pct"))
    d_w_sd1u = _safe_float_nan(out.get("dist_vwap_w_sd1u_pct"))
    d_d_sd1d = _safe_float_nan(out.get("dist_vwap_d_sd1d_pct"))
    d_w_sd1d = _safe_float_nan(out.get("dist_vwap_w_sd1d_pct"))

    # 1. Weekly vs Daily
    out["vwap_w_minus_d_pct"] = d_w - d_d if not (np.isnan(d_w) or np.isnan(d_d)) else np.nan

    # 2. Monthly vs Weekly
    out["vwap_m_minus_w_pct"] = d_m - d_w if not (np.isnan(d_m) or np.isnan(d_w)) else np.nan

    # 3. SD1u divergence
    out["vwap_w_sd1u_minus_d_sd1u_pct"] = (
        d_w_sd1u - d_d_sd1u if not (np.isnan(d_w_sd1u) or np.isnan(d_d_sd1u)) else np.nan
    )

    # 4. SD1d divergence
    out["vwap_w_sd1d_minus_d_sd1d_pct"] = (
        d_w_sd1d - d_d_sd1d if not (np.isnan(d_w_sd1d) or np.isnan(d_d_sd1d)) else np.nan
    )

    # 5. Bool alignement signe (regime trending fort)
    if not (np.isnan(d_w) or np.isnan(d_d)):
        out["vwap_w_d_aligned"] = 1 if (np.sign(d_w) == np.sign(d_d)) else 0
    else:
        out["vwap_w_d_aligned"] = 0

    return out
