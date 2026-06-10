"""
phase_b_vwap_diff.py — VWAP différentiels weekly/monthly vs daily.

FIX 27/04 (audit ULTRATHINK + ml-trainer + feature-engineer) :
Remplace 10 features `dist_vwap_w/m_*_pct` raw (redondantes sur 1 mois,
divergentes sur 24m mais collineaires) par 5 features DIFFERENTIELLES qui
encodent la divergence cross-timeframe (signal trend persistence).

5 features generees :
  vwap_w_minus_d_pct      : weekly vs daily (signal trend casse)
  vwap_m_minus_w_pct      : monthly vs weekly (signal long-term trend)
  vwap_w_sd1u_minus_d_sd1u_pct : divergence bandes hautes weekly/daily
  vwap_w_sd1d_minus_d_sd1d_pct : divergence bandes basses
  vwap_w_d_aligned        : boolean (signe(dist_w_pct) == signe(dist_d_pct))

Note : sur 1 mois data, ces features peuvent etre quasi-nulles. Re-evaluer
post-backfill 24m.

Auteur : Audit ULTRATHINK Option C+ (2026-04-27)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


VWAP_DIFF_GENERATED = {
    "vwap_w_minus_d_pct",
    "vwap_m_minus_w_pct",
    "vwap_w_sd1u_minus_d_sd1u_pct",
    "vwap_w_sd1d_minus_d_sd1d_pct",
    "vwap_w_d_aligned",
}


def apply_vwap_diff(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule 5 features VWAP differentiels.

    Pre-requis : dist_vwap_d_pct, dist_vwap_w_pct, dist_vwap_m_pct,
    dist_vwap_d_sd1u_pct, dist_vwap_w_sd1u_pct, dist_vwap_d_sd1d_pct,
    dist_vwap_w_sd1d_pct (Phase B+ engine).
    """
    df = df.copy()

    # Drop existing pour idempotence
    drop_existing = [c for c in VWAP_DIFF_GENERATED if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    # 1. Weekly vs Daily (trend persistence cross-timeframe)
    if "dist_vwap_w_pct" in df.columns and "dist_vwap_d_pct" in df.columns:
        df["vwap_w_minus_d_pct"] = (df["dist_vwap_w_pct"] - df["dist_vwap_d_pct"]).astype("float32")
    else:
        df["vwap_w_minus_d_pct"] = np.nan

    # 2. Monthly vs Weekly (long-term trend)
    if "dist_vwap_m_pct" in df.columns and "dist_vwap_w_pct" in df.columns:
        df["vwap_m_minus_w_pct"] = (df["dist_vwap_m_pct"] - df["dist_vwap_w_pct"]).astype("float32")
    else:
        df["vwap_m_minus_w_pct"] = np.nan

    # 3. SD1u divergence (bandes hautes weekly vs daily)
    if "dist_vwap_w_sd1u_pct" in df.columns and "dist_vwap_d_sd1u_pct" in df.columns:
        df["vwap_w_sd1u_minus_d_sd1u_pct"] = (
            df["dist_vwap_w_sd1u_pct"] - df["dist_vwap_d_sd1u_pct"]
        ).astype("float32")
    else:
        df["vwap_w_sd1u_minus_d_sd1u_pct"] = np.nan

    # 4. SD1d divergence
    if "dist_vwap_w_sd1d_pct" in df.columns and "dist_vwap_d_sd1d_pct" in df.columns:
        df["vwap_w_sd1d_minus_d_sd1d_pct"] = (
            df["dist_vwap_w_sd1d_pct"] - df["dist_vwap_d_sd1d_pct"]
        ).astype("float32")
    else:
        df["vwap_w_sd1d_minus_d_sd1d_pct"] = np.nan

    # 5. Boolean alignement (signal regime trending fort)
    if "dist_vwap_w_pct" in df.columns and "dist_vwap_d_pct" in df.columns:
        df["vwap_w_d_aligned"] = (
            (np.sign(df["dist_vwap_w_pct"]) == np.sign(df["dist_vwap_d_pct"]))
            .astype("int8")
        )
    else:
        df["vwap_w_d_aligned"] = 0

    return df
