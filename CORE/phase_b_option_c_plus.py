"""
phase_b_option_c_plus.py — Transformations Option C+ (audit ULTRATHINK 27/04).

Combine :
  - After-hours conditional fillna (ml-trainer rescue, 3 features)
  - Winsorize vwap_slope_10_atr (clip p99.5)
  - 3 nouvelles features feature-engineer :
    * vol_imbalance_3bar_build : cumul delta normalise 3 bars same-sign
    * atr_regime_zscore_60d : z-score ATR vs moyenne 60j
    * time_to_session_close_norm : (16:00 ET - now) / session_length

Module a appliquer APRES toutes les autres phases (B, B+, B+++, C, 1, 3, D)
mais AVANT clustering Spearman.

Auteur : Audit ULTRATHINK Option C+ (2026-04-27)
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
BARS_PER_DAY_RTH = 390  # 6h30 RTH = 390 min


OPTION_C_PLUS_GENERATED = {
    # After-hours conditional fillna (3)
    "dist_after_high_pct_filled",
    "dist_after_low_pct_filled",
    "dist_after_open_pct_filled",
    # 3 nouvelles features feature-engineer
    "vol_imbalance_3bar_build",
    "atr_regime_zscore_60d",
    "time_to_session_close_norm",
    # FIX 3 ml-trainer (27/04) : session_segment pour contextualiser drift early/mid/late
    "session_segment",
}


def add_after_hours_conditional_fillna(df: pd.DataFrame) -> pd.DataFrame:
    """
    Conditional fillna pour features after-hours 95% NaN.

    Strategie ml-trainer : ffill().fillna(0) + boolean is_in_us_after.
    LightGBM splittera d'abord sur is_in_us_after, puis sur valeur filled.
    """
    df = df.copy()
    for col in ["dist_after_high_pct", "dist_after_low_pct", "dist_after_open_pct"]:
        new_col = f"{col}_filled"
        if col in df.columns:
            df[new_col] = df[col].ffill().fillna(0).astype("float32")
        else:
            df[new_col] = 0.0
    return df


def add_vol_imbalance_3bar_build(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cumul delta normalise sur 3 barres CONSECUTIVES de meme signe.
    Capture order flow accumulation pre-breakout (Bookmap pattern).

    Calcul :
      1. sign(delta_bar) sur chaque bar
      2. Si 3 bars consecutives meme signe (run >= 3) : sum(delta_bar) / sum(volume)
      3. Sinon : 0
    """
    df = df.copy()
    if "delta_bar" not in df.columns or "volume" not in df.columns:
        df["vol_imbalance_3bar_build"] = 0.0
        return df

    delta = df["delta_bar"].values
    vol = df["volume"].values
    n = len(df)
    out = np.zeros(n, dtype=np.float32)

    for i in range(2, n):
        s2 = np.sign(delta[i])
        s1 = np.sign(delta[i - 1])
        s0 = np.sign(delta[i - 2])
        if s0 == s1 == s2 != 0:
            cum_delta = delta[i] + delta[i - 1] + delta[i - 2]
            cum_vol = vol[i] + vol[i - 1] + vol[i - 2]
            if cum_vol > 0:
                out[i] = cum_delta / cum_vol  # ratio normalise [-1, +1]

    df["vol_imbalance_3bar_build"] = out
    return df


def add_atr_regime_zscore_60d(df: pd.DataFrame, lookback_days: int = 60) -> pd.DataFrame:
    """
    Z-score ATR vs sa moyenne 60j.
    Distingue low-vol vs high-vol regime sans leak forward.
    Lopez ch.5 stationnarite via standardisation rolling.
    """
    df = df.copy()
    if "atr" not in df.columns:
        df["atr_regime_zscore_60d"] = np.nan
        return df

    bars_60d = lookback_days * 1380  # bars CME 24h
    rolling_mean = df["atr"].rolling(bars_60d, min_periods=10 * 1380).mean()
    rolling_std = df["atr"].rolling(bars_60d, min_periods=10 * 1380).std()

    z = (df["atr"] - rolling_mean) / rolling_std.replace(0, np.nan)
    df["atr_regime_zscore_60d"] = z.astype("float32")
    return df


def add_session_segment(df: pd.DataFrame) -> pd.DataFrame:
    """
    FIX 3 ml-trainer (27/04) : session_segment pour contextualiser drift early/mid/late.

    Categoriel 0/1/2/3 :
      0 : pre-RTH (hors 09:30-16:00 ET)
      1 : RTH early (09:30-11:00 ET, premiere 1h30)
      2 : RTH mid (11:00-14:00 ET, milieu 3h)
      3 : RTH late (14:00-16:00 ET, derniere 2h)

    Permet a LightGBM de splitter sur ce contexte et donc d'apprendre
    "ce drift est normal car c'est session_segment X".
    """
    df = df.copy()
    if "ts_event" not in df.columns:
        df["session_segment"] = 0
        return df

    ts = df["ts_event"]
    if ts.dt.tz is None:
        ts_et = ts.dt.tz_localize("UTC").dt.tz_convert(ET)
    else:
        ts_et = ts.dt.tz_convert(ET)
    mins_et = ts_et.dt.hour * 60 + ts_et.dt.minute

    seg = np.zeros(len(df), dtype=np.int8)
    in_rth = (mins_et >= 570) & (mins_et < 960)
    seg = np.where(~in_rth, 0, seg)
    seg = np.where(in_rth & (mins_et < 660), 1, seg)   # 09:30-11:00
    seg = np.where(in_rth & (mins_et >= 660) & (mins_et < 840), 2, seg)  # 11:00-14:00
    seg = np.where(in_rth & (mins_et >= 840), 3, seg)  # 14:00-16:00

    df["session_segment"] = seg.astype("int8")
    return df


def winsorize_vwap_slope_10_atr(df: pd.DataFrame, p: float = 0.995) -> pd.DataFrame:
    """
    FIX 27/04 (quality-auditor BLOCKER) : winsorize vwap_slope_10_atr a p99.5.

    Cause racine : vwap_d.shift(10) croise frontiere de session = gap overnight
    cree saut artificiel (max=20.6 sur ES, p99=0.12, ratio 165x).

    Fix : clip directement dans le PARQUET (pas seulement train_lightgbm).
    Sinon LightGBM lit le parquet brut et split sur l'outlier.
    """
    df = df.copy()
    if "vwap_slope_10_atr" not in df.columns:
        return df
    s = df["vwap_slope_10_atr"]
    if s.notna().sum() < 100:
        return df
    p_high = s.quantile(p)
    p_low = s.quantile(1 - p)
    df["vwap_slope_10_atr"] = s.clip(lower=p_low, upper=p_high).astype("float32")
    return df


def add_time_to_session_close_norm(df: pd.DataFrame) -> pd.DataFrame:
    """
    Distance normalisee a la cloture US RTH (16:00 ET).
    Decay risk-on en fin de session, pattern empirique solide.

    Calcul :
      - Si dans session RTH (09:30-16:00 ET) : (16:00 - now_et) / 390 min
        Range [0, 1] : 1.0 a 09:30, 0.0 a 16:00
      - Hors session : 0.0 (pas de risk-on intraday)
    """
    df = df.copy()
    if "ts_event" not in df.columns:
        df["time_to_session_close_norm"] = 0.0
        return df

    ts = df["ts_event"]
    if ts.dt.tz is None:
        ts_et = ts.dt.tz_localize("UTC").dt.tz_convert(ET)
    else:
        ts_et = ts.dt.tz_convert(ET)

    mins_et = ts_et.dt.hour * 60 + ts_et.dt.minute
    in_rth = (mins_et >= 570) & (mins_et < 960)  # 09:30-16:00 ET

    # Distance to close 960 (16:00) divise par 390 (RTH duration)
    dist_to_close = (960 - mins_et) / 390.0
    out = np.where(in_rth, dist_to_close, 0.0)
    df["time_to_session_close_norm"] = out.astype("float32")
    return df


def apply_option_c_plus_transforms(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline complet Option C+ : after-hours fillna + 3 nouvelles features."""
    df = df.copy()
    drop_existing = [c for c in OPTION_C_PLUS_GENERATED if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    df = add_after_hours_conditional_fillna(df)
    df = add_vol_imbalance_3bar_build(df)
    df = add_atr_regime_zscore_60d(df)
    df = add_time_to_session_close_norm(df)
    df = add_session_segment(df)  # FIX 3 ml-trainer (drift contextualisation)
    df = winsorize_vwap_slope_10_atr(df)  # FIX BLOCKER quality-auditor
    return df
