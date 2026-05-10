"""
phase_b_rolling_inputs.py — Phase 1 : Aliases V4-natif pour rolling features.

Calcule les 22 inputs requis par market_profile_rolling.py (V4-natif) depuis
les colonnes OHLCV + cvd_session + Phase C VPOC running deja presents en V4.

PAS de chargement DMP (strategie : se debarrasser progressivement du DMP, cf
feedback Jackson 27/04). Tous les inputs sont recrees depuis Databento clean.

Inputs ajoutes (22) :
  ATR (1)            : atr (en ticks, True Range rolling 14)
  VWAP derivees (4)  : vwap_slope_10, dist_vwap_d (POINTS), vwap_d_side, dist_vwap_d_atr
  Momentum (1)       : momentum_5b
  IB derivees (4)    : ib_range_atr, dist_ib_high (POINTS), dist_ib_low (POINTS), ib_broken_down (alias)
  Session HL (2)     : dist_sess_high (POINTS), dist_sess_low (POINTS)
  CVD (2)            : cvd_day (alias cvd_session), delta_day_dir (sign cvd)
  VPOC running (5)   : poc_position, va_position_pct (alias), inside_cur_va (alias),
                       dist_cur_vpoc (POINTS), dist_cur_vah (POINTS), dist_cur_val (POINTS)
  Session (1)        : session (entier 0/1/2/3)
  Bar aliases (2)    : bar_high (alias high), bar_low (alias low)

NON-REPRODUCTIBLE en V4 (drop documente) :
  - large_trader_ratio (necessite MBO bid/ask sizes, pas dispo Databento trades)
    -> drop feature ctx_large_trader_slope_5 dans market_profile_rolling.py
  - diag_imbalance (necessite footprint VAP, code separement dans Phase B+++)
    -> NaN par defaut, calcul futur Phase 1.bis via footprint_builder

Ces inputs sont des HELPERS internes (drop ML_EXCLUDE_FEATURES). Seules les
features ctx_* derivees arrivent au modele.

Convention :
  - distances POINTS = close - level (signe : close > level -> positif)
  - distances pct = (close - level) / close * 100 (deja calculees en Phase B helpers)

Auteur : Phase 1 V4 (2026-04-27)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick via apply_rolling_inputs(tick)
ATR_LOOKBACK = 14


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ATR True Range rolling (en ticks)
# ═══════════════════════════════════════════════════════════════════════════════

def add_atr_intraday(
    df: pd.DataFrame,
    lookback: int = ATR_LOOKBACK,
    tick: float = TICK_SIZE,
) -> pd.DataFrame:
    """
    Calcule atr (en TICKS) = True Range rolling lookback bars / tick_size.

    True Range = max(high-low, abs(high-close_prev), abs(low-close_prev))

    Args:
        df : OHLCV V4
        lookback : 14 standard
        tick : 0.25 ES + NQ
    Returns:
        df + col 'atr' (FLOAT, ticks).
    """
    df = df.copy()
    high, low, close = df["high"].values, df["low"].values, df["close"].values
    close_prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - close_prev),
        np.abs(low - close_prev),
    ])
    # ATR rolling en POINTS, puis convertir en ticks
    atr_points = pd.Series(tr).rolling(lookback, min_periods=1).mean().values
    df["atr"] = (atr_points / tick).astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 2. VWAP derivees (slope, dist POINTS, side, dist_atr)
# ═══════════════════════════════════════════════════════════════════════════════

def add_vwap_derivees(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Calcule vwap_slope_10 (raw helper), vwap_slope_10_atr (ML feature),
    dist_vwap_d (POINTS helper), vwap_d_side, dist_vwap_d_atr (ML feature).

    FIX 27/04 (quality-auditor) : vwap_slope_10 raw en POINTS/bar a une fuite
    volatilite (NQ 4x ES). Version _atr ML-usable.

    Requis en V4 : vwap_d (Phase B+ engine), close, atr (add_atr_intraday).
    """
    df = df.copy()
    if "vwap_d" not in df.columns:
        raise KeyError("[Phase 1] vwap_d manquant. Appeler phase_b_plus_engine avant.")
    if "atr" not in df.columns:
        raise KeyError("[Phase 1] atr manquant. Appeler add_atr_intraday avant.")

    # Slope 10 bars : (vwap_d - vwap_d.shift(10)) / 10 (en POINTS / bar - helper raw)
    df["vwap_slope_10"] = ((df["vwap_d"] - df["vwap_d"].shift(10)) / 10).astype("float32")

    # Distance close - vwap_d (POINTS, signe conserve - helper raw)
    df["dist_vwap_d"] = (df["close"] - df["vwap_d"]).astype("float32")

    # Side : -1, 0, +1 selon close vs vwap_d (ML feature)
    df["vwap_d_side"] = np.sign(df["dist_vwap_d"]).fillna(0).astype("int8")

    # Versions ATR-normalisees (ML features)
    atr_safe = df["atr"].replace(0, np.nan)
    df["dist_vwap_d_atr"] = (df["dist_vwap_d"] / tick / atr_safe).astype("float32")
    df["vwap_slope_10_atr"] = (df["vwap_slope_10"] / tick / atr_safe).astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 3. IB derivees (range_atr, dist points, broken alias)
# ═══════════════════════════════════════════════════════════════════════════════

def add_ib_derivees(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Calcule ib_range_atr, dist_ib_high (POINTS), dist_ib_low (POINTS), ib_broken_down.
    """
    df = df.copy()
    if "ib_range_ticks" not in df.columns or "atr" not in df.columns:
        raise KeyError("[Phase 1] ib_range_ticks ou atr manquant.")
    if "ib_high" not in df.columns or "ib_low" not in df.columns:
        raise KeyError("[Phase 1] ib_high/low manquant.")

    atr_safe = df["atr"].replace(0, np.nan)
    df["ib_range_atr"] = (df["ib_range_ticks"] / atr_safe).astype("float32")
    df["dist_ib_high"] = (df["close"] - df["ib_high"]).astype("float32")
    df["dist_ib_low"] = (df["close"] - df["ib_low"]).astype("float32")

    # Alias V1 (ib_broken_down) -> V4 (ib_broken_dn)
    if "ib_broken_dn" in df.columns:
        df["ib_broken_down"] = df["ib_broken_dn"].astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Session HL POINTS + session entier + bar aliases
# ═══════════════════════════════════════════════════════════════════════════════

def add_session_derivees(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule dist_sess_high/low (POINTS), session entier 0/1/2/3, bar_high/low aliases.
    """
    df = df.copy()
    if "sess_high" not in df.columns or "sess_low" not in df.columns:
        raise KeyError("[Phase 1] sess_high/low manquant.")

    df["dist_sess_high"] = (df["close"] - df["sess_high"]).astype("float32")
    df["dist_sess_low"] = (df["close"] - df["sess_low"]).astype("float32")

    # Session entier : 0=Asia, 1=London, 2=US cash, 3=US after-hours
    # Si is_in_us_cash=1 -> 2 ; is_in_london=1 -> 1 ; is_in_asia=1 -> 0 ; is_in_us_after=1 -> 3
    if "is_in_us_cash" in df.columns:
        sess = np.full(len(df), -1, dtype=np.int8)  # -1 = inconnu
        if "is_in_asia" in df.columns:
            sess = np.where(df["is_in_asia"] == 1, 0, sess)
        if "is_in_london" in df.columns:
            sess = np.where(df["is_in_london"] == 1, 1, sess)
        sess = np.where(df["is_in_us_cash"] == 1, 2, sess)
        if "is_in_us_after" in df.columns:
            sess = np.where(df["is_in_us_after"] == 1, 3, sess)
        df["session"] = sess.astype("int8")
    else:
        df["session"] = -1

    # Bar aliases V1 (bar_high/low) -> V4 (high/low)
    df["bar_high"] = df["high"].astype("float32")
    df["bar_low"] = df["low"].astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CVD derivees + Momentum
# ═══════════════════════════════════════════════════════════════════════════════

def add_cvd_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule cvd_day (alias cvd_session), delta_day_dir (sign), momentum_5b.
    """
    df = df.copy()
    if "delta_bar" not in df.columns:
        raise KeyError("[Phase 1] delta_bar manquant.")

    # cvd_day = alias cvd_session si exists, sinon recompute via cumsum delta_bar par session_date_trading
    if "cvd_session" in df.columns:
        df["cvd_day"] = df["cvd_session"].astype("float32")
    elif "session_date_trading" in df.columns:
        df["cvd_day"] = (
            df.groupby("session_date_trading")["delta_bar"]
            .cumsum()
            .astype("float32")
        )
    else:
        raise KeyError("[Phase 1] Ni cvd_session ni session_date_trading dispo.")

    # delta_day_dir : sign(cvd_day)
    df["delta_day_dir"] = np.sign(df["cvd_day"]).fillna(0).astype("int8")

    # momentum_5b : delta_bar rolling sum 5 bars (= cumul delta sur 5 dernieres minutes)
    df["momentum_5b"] = df["delta_bar"].rolling(5, min_periods=1).sum().astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 6. VPOC running derivees (POINTS + position)
# ═══════════════════════════════════════════════════════════════════════════════

def add_vpoc_derivees(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule poc_position [0,1], va_position_pct (alias), inside_cur_va (alias),
    dist_cur_vpoc/vah/val (POINTS).

    Requis : Phase C deja appliquee (cur_vpoc/vah/val running, inside_value_area).
    """
    df = df.copy()
    required = ["close", "cur_vpoc", "cur_vah", "cur_val", "inside_value_area"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"[Phase 1] manquant {missing}. Appeler Phase C avant.")

    # poc_position : (close - val) / (vah - val) clampe [0,1]
    # 0 = close au VAL, 1 = close au VAH, 0.5 = milieu VA
    va_width = df["cur_vah"] - df["cur_val"]
    va_safe = va_width.replace(0, np.nan)
    poc_pos = (df["close"] - df["cur_val"]) / va_safe
    poc_pos = poc_pos.clip(lower=0.0, upper=1.0)
    df["poc_position"] = poc_pos.astype("float32")

    # va_position_pct : alias V1 de poc_position
    df["va_position_pct"] = df["poc_position"]

    # inside_cur_va : alias V1 de inside_value_area
    df["inside_cur_va"] = df["inside_value_area"].astype("int8")

    # Distances POINTS (close - level), signe conserve
    df["dist_cur_vpoc"] = (df["close"] - df["cur_vpoc"]).astype("float32")
    df["dist_cur_vah"] = (df["close"] - df["cur_vah"]).astype("float32")
    df["dist_cur_val"] = (df["close"] - df["cur_val"]).astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ALL-IN-ONE PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

PHASE_B_ROLLING_INPUTS_COLS = {
    "atr",
    "vwap_slope_10", "vwap_slope_10_atr",  # FIX 27/04 : version _atr ML
    "dist_vwap_d", "vwap_d_side", "dist_vwap_d_atr",
    "ib_range_atr", "dist_ib_high", "dist_ib_low", "ib_broken_down",
    "dist_sess_high", "dist_sess_low", "session", "bar_high", "bar_low",
    "cvd_day", "delta_day_dir", "momentum_5b",
    "poc_position", "va_position_pct", "inside_cur_va",
    "dist_cur_vpoc", "dist_cur_vah", "dist_cur_val",
}


def apply_rolling_inputs(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Pipeline complet : 22 inputs V4-natif pour market_profile_rolling.py.

    Pre-requis : df doit contenir Phase B helpers + Phase C VPOC running.
    Idempotent (drop existing avant recalcul).
    """
    df = df.copy()
    drop_existing = [c for c in PHASE_B_ROLLING_INPUTS_COLS if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    df = add_atr_intraday(df, tick=tick)
    df = add_vwap_derivees(df, tick=tick)
    df = add_ib_derivees(df, tick=tick)
    df = add_session_derivees(df)
    df = add_cvd_momentum(df)
    df = add_vpoc_derivees(df)
    return df
