"""
market_profile_rolling.py — Phase 3 : 11 features ctx_* Market Profile rolling V4-natif.

Reecriture V4-natif (pas adaptation legacy rolling_features.py 845 LOC).
Utilise UNIQUEMENT les colonnes V4 (cur_vpoc/vah/val running de Phase C +
inputs Phase 1 + Phase B helpers).

11 features ctx_* (FIX 27/04 review code-reviewer + market-analyst) :

  Market Profile (5) :
    1. ctx_poc_migration_10    : slope poc_position sur 10 bars
    2. ctx_va_developing_10    : delta va_width sur 10 bars
    3. ctx_va_width            : abs(dist_cur_vah) + abs(dist_cur_val)
    4. ctx_ib_extension_ratio  : max_ext / (ib_range/2) Steidlmayer
    5. ctx_rotation_factor_20  : count cur_vpoc crosses sur 20 bars

  Auctions (1) :
    6. ctx_failed_auction      : sortie+retour VA en <5 bars (signed continu)

  Climax/Exhaustion/Absorption (5) :
    7.  ctx_vol_z_5            : Z-score volume 5 bars (PROMU helper -> feature)
    8.  ctx_delta_sum_3        : somme delta_bar 3 bars (PROMU helper -> feature)
    9.  ctx_delta_exhaustion   : ratio delta vs max recent
    10. ctx_instant_absorption : delta seuil dynamique k*std vs price_diff
    11. ctx_absorption_streak_5: rolling sum 5 sur ctx_instant_absorption

DROPPED (FIX 27/04 review market-analyst + empirique) :
  - ctx_climax_signal : pattern 11 (composite hardcode vol_z*sign(delta_sum)).
    Reference : feedback_lightgbm_no_composite_indicators.md.
  - ctx_poor_high / ctx_poor_low : calibration impossible avec atr_intraday 1m
    (~5 ticks). Le V1 utilisait atr_daily (~150 ticks) avec seuil 0.04. En V4
    avec atr_intraday, fire rate 99.3% (poor_high=1 ET poor_low=1 simultane
    quasi tout le temps = signal vide). A reimplementer Phase D avec atr_daily
    dedie ou tracker high-revisits via rolling_max(high, 60) au lieu de sess_high.

Fail-loud : KeyError explicite si colonne V4 manquante (pas silent fail comme
rolling_features.py legacy line 70).

Auteur : Phase 3 V4 (2026-04-27)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from constants import DEFAULT_TICK_SIZE  # FIX 27/04 : pas de hardcode 0.25


# Constantes calibrees (FIX 27/04 review market-analyst)
INSTANT_ABSORPTION_DELTA_K = 1.5  # k * std(delta_bar) seuil
INSTANT_ABSORPTION_WINDOW = 50
# FIX 27/04 : 0.04 trop serre avec atr_intraday 1m (~5 ticks).
# Recalibre 0.15 (=> ~0.75 tick = revisite proche du high, plus stable).
# Originellement 0.04 etait calibre sur DMP atr_daily (~150 ticks),
# donc 0.04 * 150 = 6 ticks. Avec atr_intraday ~5 ticks, equivalent = 0.15 * 5 = 0.75 tick.
POOR_HIGH_LOW_ATR_THRESHOLD = 0.15
POOR_HIGH_LOW_ROLLING_WINDOW = 60
POOR_HIGH_LOW_THRESHOLD = 3  # < 3 bars near high = poor (unfinished)
SHORT_WINDOW = 3
MID_WINDOW = 5
LONG_WINDOW = 10
ROTATION_WINDOW = 20
FAILED_AUCTION_LOOKBACKS = [3, 4, 5]


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers numeriques
# ═══════════════════════════════════════════════════════════════════════════════

def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    """
    Pente lineaire (regression) sur une fenetre glissante.
    Identique a rolling_features.RollingFeatures._slope (parite legacy).
    """
    def linreg_slope(arr):
        n = len(arr)
        if n < 2:
            return np.nan
        valid = ~np.isnan(arr)
        if valid.sum() < 2:
            return np.nan
        x = np.arange(n)[valid]
        y = arr[valid]
        if len(x) < 2:
            return np.nan
        mx, my = x.mean(), y.mean()
        denom = ((x - mx) ** 2).sum()
        if denom == 0:
            return 0.0
        return ((x - mx) * (y - my)).sum() / denom

    return series.rolling(window, min_periods=2).apply(linreg_slope, raw=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Bloc 1 : Market Profile rolling (5 features)
# ═══════════════════════════════════════════════════════════════════════════════

def _ctx_poc_migration_10(df: pd.DataFrame) -> pd.Series:
    """
    Slope poc_position sur 10 bars.
    Positif = POC monte (acheteurs dominent) | Negatif = vendeurs.
    """
    if "poc_position" not in df.columns:
        raise KeyError("[Phase 3] poc_position manquant. Phase 1 requise.")
    return _rolling_slope(df["poc_position"], LONG_WINDOW).astype("float32")


def _ctx_va_width_and_developing(df: pd.DataFrame, tick: float = DEFAULT_TICK_SIZE) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    va_width = abs(dist_cur_vah) + abs(dist_cur_val) (largeur VA effective en POINTS)
    va_developing_10 = va_width - va_width.shift(10) (delta sur 10 bars en POINTS)

    FIX 27/04 (quality-auditor) : versions _atr ML-usable (raw = helper interne).
    Sans normalisation, ces features sont en POINTS bruts -> fuite instrument
    NQ x4 ES (std_ratio ~1.06 en valeur, mais NQ 30 vs ES 7 ticks = 4x).
    """
    if "dist_cur_vah" not in df.columns or "dist_cur_val" not in df.columns:
        raise KeyError("[Phase 3] dist_cur_vah/val manquant. Phase 1 requise.")
    if "atr" not in df.columns:
        raise KeyError("[Phase 3] atr manquant. Phase 1 requise.")
    va_width = df["dist_cur_vah"].abs() + df["dist_cur_val"].abs()
    va_developing = va_width - va_width.shift(LONG_WINDOW)
    # Versions normalisees ATR (POINTS / tick / atr_ticks => sans unite)
    atr_safe = df["atr"].replace(0, np.nan)
    va_width_atr = va_width / tick / atr_safe
    va_developing_atr = va_developing / tick / atr_safe
    return (
        va_width.astype("float32"),
        va_developing.astype("float32"),
        va_width_atr.astype("float32"),
        va_developing_atr.astype("float32"),
    )


def _ctx_ib_extension_ratio(df: pd.DataFrame) -> pd.Series:
    """
    max_ext / (ib_range / 2). Steidlmayer 70% du temps prix dans 1x IB.
    > 1.5 = trend day probable | > 2.0 = trend day confirme.
    """
    required = ["ib_range_ticks", "dist_ib_high", "dist_ib_low"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"[Phase 3] {missing} manquant. Phase 1 requise.")
    ib_range = df["ib_range_ticks"].replace(0, np.nan)
    d_high = df["dist_ib_high"].abs()
    d_low = df["dist_ib_low"].abs()
    max_ext = pd.concat([d_high, d_low], axis=1).max(axis=1)
    return (max_ext / (ib_range / 2.0)).astype("float32")


def _ctx_rotation_factor_20(df: pd.DataFrame) -> pd.Series:
    """
    Count cur_vpoc crosses sur 20 bars.
    Beaucoup = range day (ping-pong) | Peu = trend day.
    Dalton : > 6 rotations en 1h = range confirme.
    """
    if "dist_cur_vpoc" not in df.columns:
        raise KeyError("[Phase 3] dist_cur_vpoc manquant. Phase 1 requise.")
    vpoc_side = (df["dist_cur_vpoc"] > 0).astype(int)
    vpoc_cross = (vpoc_side != vpoc_side.shift(1)).astype(float)
    return vpoc_cross.rolling(ROTATION_WINDOW, min_periods=5).sum().astype("float32")


# ═══════════════════════════════════════════════════════════════════════════════
# Bloc 2 : Auctions (3 features + 2 helpers)
# ═══════════════════════════════════════════════════════════════════════════════

def _ctx_failed_auction(df: pd.DataFrame, tick: float = DEFAULT_TICK_SIZE) -> pd.Series:
    """
    Failed Auction : sortie+retour VA en < 5 bars.

    FIX 27/04 (market-analyst) : version SIGNED CONTINUE.
    Magnitude = max distance hors VA (en ticks ATR-normalisee) pendant
    la sortie, avec signe (+ si sortie haut, - si sortie bas).
    Plus la sortie etait loin, plus le reversal signal est fort.

    Anciennement binaire 0/1 -> perte d'info.
    """
    required = ["inside_cur_va", "close", "cur_vah", "cur_val", "atr"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"[Phase 3] {missing} manquant. Phase 1 requise.")

    inside = df["inside_cur_va"].fillna(0).astype(int)
    n = len(df)
    failed_signed = np.zeros(n, dtype=np.float32)
    atr_safe = df["atr"].replace(0, np.nan).values
    close = df["close"].values
    vah = df["cur_vah"].values
    val = df["cur_val"].values

    for lookback in FAILED_AUCTION_LOOKBACKS:
        was_in = inside.shift(lookback).fillna(0).astype(int).values
        is_now_in = inside.values == 1
        # Min inside sur la fenetre
        min_inside = inside.rolling(lookback, min_periods=1).min().fillna(0).astype(int).values
        is_failed = is_now_in & (was_in == 1) & (min_inside == 0)

        # Magnitude : max(close - vah, val - close, 0) sur la fenetre
        for i in range(lookback, n):
            if is_failed[i] and not np.isnan(atr_safe[i]):
                # Excursion max (en POINTS) hors VA sur les `lookback` bars
                max_above = 0.0
                max_below = 0.0
                for k in range(i - lookback + 1, i + 1):
                    if not np.isnan(close[k]) and not np.isnan(vah[k]):
                        d_above = max(close[k] - vah[k], 0.0)
                        if d_above > max_above:
                            max_above = d_above
                    if not np.isnan(close[k]) and not np.isnan(val[k]):
                        d_below = max(val[k] - close[k], 0.0)
                        if d_below > max_below:
                            max_below = d_below
                # Sign + magnitude (POINTS / tick / atr_ticks => ATR units)
                if max_above > max_below and atr_safe[i] > 0:
                    failed_signed[i] = max(failed_signed[i], +max_above / tick / atr_safe[i])
                elif max_below > max_above and atr_safe[i] > 0:
                    failed_signed[i] = min(failed_signed[i], -max_below / tick / atr_safe[i])
    return pd.Series(failed_signed, index=df.index, dtype="float32")


# ctx_poor_high / ctx_poor_low DROPPED (FIX 27/04) - cf docstring du module.
# Calibration impossible avec atr_intraday. A reimplementer Phase D.


# ═══════════════════════════════════════════════════════════════════════════════
# Bloc 3 : Climax / Exhaustion / Absorption (5 features)
# ═══════════════════════════════════════════════════════════════════════════════

def _ctx_vol_z_5(df: pd.DataFrame) -> pd.Series:
    """
    Z-score volume sur 5 bars. Detecte les spikes de volume.
    PROMU FEATURE ML (anciennement helper).

    LightGBM peut apprendre l'interaction vol_z * sign(delta_sum_3) tout seul,
    pas besoin du composite ctx_climax_signal hardcode.
    """
    if "total_vol" not in df.columns:
        raise KeyError("[Phase 3] total_vol manquant. Phase B helpers requis.")
    vol = df["total_vol"]
    vol_mean = vol.rolling(MID_WINDOW, min_periods=2).mean()
    vol_std = vol.rolling(MID_WINDOW, min_periods=2).std()
    z = (vol - vol_mean) / vol_std.replace(0, np.nan)
    return z.fillna(0).astype("float32")


def _ctx_delta_sum_3(df: pd.DataFrame) -> pd.Series:
    """
    Somme delta_bar sur 3 bars.
    PROMU FEATURE ML (anciennement helper).
    """
    if "delta_bar" not in df.columns:
        raise KeyError("[Phase 3] delta_bar manquant.")
    return df["delta_bar"].rolling(SHORT_WINDOW, min_periods=1).sum().astype("float32")


def _ctx_delta_exhaustion(df: pd.DataFrame) -> pd.Series:
    """
    Ratio delta actuel vs max recent (10 bars).
    Capte le pattern "3 pushes" : chaque push plus faible.
    < 0.5 = move s'essouffle.
    """
    if "delta_bar" not in df.columns:
        raise KeyError("[Phase 3] delta_bar manquant.")
    rolling_max = df["delta_bar"].abs().rolling(LONG_WINDOW, min_periods=2).max()
    return (df["delta_bar"].abs() / rolling_max.replace(0, np.nan)).astype("float32")


def _ctx_instant_absorption(df: pd.DataFrame) -> pd.Series:
    """
    Absorption instantanee bar-by-bar signee.
    Seuil dynamique k*std(delta_bar, 50).
    +1 = bull absorption (delta < -threshold ET prix monte)
    -1 = bear absorption (delta > +threshold ET prix baisse)
     0 = pas d'absorption

    FIX 27/04 (code-reviewer) : type int8 (anciennement float32).
    """
    if "delta_bar" not in df.columns or "close" not in df.columns:
        raise KeyError("[Phase 3] delta_bar ou close manquant.")
    price_diff = df["close"].diff()
    delta_std = df["delta_bar"].rolling(
        INSTANT_ABSORPTION_WINDOW, min_periods=10
    ).std()
    threshold = delta_std * INSTANT_ABSORPTION_DELTA_K

    result = pd.Series(0, index=df.index, dtype="int8")
    bear_absorb = (df["delta_bar"] > threshold) & (price_diff < 0)
    bull_absorb = (df["delta_bar"] < -threshold) & (price_diff > 0)
    result[bear_absorb] = -1
    result[bull_absorb] = +1
    return result


def _ctx_absorption_streak_5(instant_absorption: pd.Series) -> pd.Series:
    """
    Streak d'absorption sur 5 bars.
    FIX 27/04 (code-reviewer) : prend instant_absorption en parametre explicite
    (decoupling, pas de coupling implicite via df).
    """
    return instant_absorption.rolling(MID_WINDOW, min_periods=1).sum().astype("float32")


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline complet
# ═══════════════════════════════════════════════════════════════════════════════

# 11 features ML (poor_high/low + climax_signal DROPPED, cf docstring)
# FIX 27/04 (quality-auditor) : versions _atr utilisees pour ML, raw en helpers.
MARKET_PROFILE_ROLLING_FEATURES = {
    "ctx_poc_migration_10",
    "ctx_va_width_atr", "ctx_va_developing_10_atr",  # FIX 27/04 : versions ATR-normalisees
    "ctx_ib_extension_ratio",
    "ctx_rotation_factor_20",
    "ctx_failed_auction",
    "ctx_vol_z_5", "ctx_delta_sum_3",  # PROMUS helpers -> features
    "ctx_delta_exhaustion",
    "ctx_instant_absorption",
    "ctx_absorption_streak_5",
}

# Helpers internes (fuite instrument NQ x4 ES, raw POINTS) -> drop ML_EXCLUDE
MARKET_PROFILE_ROLLING_HELPERS: set[str] = {
    "ctx_va_width", "ctx_va_developing_10",  # raw POINTS, helpers seulement
}

MARKET_PROFILE_ROLLING_COLS = MARKET_PROFILE_ROLLING_FEATURES | MARKET_PROFILE_ROLLING_HELPERS


def apply_market_profile_rolling(df: pd.DataFrame, tick: float = DEFAULT_TICK_SIZE) -> pd.DataFrame:
    """
    Calcule les 13 features ctx_* Market Profile + 2 helpers internes.

    Pre-requis : Phase B helpers + Phase C VPOC running + Phase 1 rolling inputs.
    Idempotent : drop existing avant recalcul.

    Returns:
        df enrichi avec 15 cols ctx_* (13 ML + 2 helpers).
    """
    df = df.copy()
    drop_existing = [c for c in MARKET_PROFILE_ROLLING_COLS if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    # Bloc 1 : Market Profile (5 features)
    df["ctx_poc_migration_10"] = _ctx_poc_migration_10(df)
    va_width, va_developing, va_width_atr, va_developing_atr = _ctx_va_width_and_developing(df, tick=tick)
    df["ctx_va_width"] = va_width  # helper raw (drop ML)
    df["ctx_va_developing_10"] = va_developing  # helper raw (drop ML)
    df["ctx_va_width_atr"] = va_width_atr  # ML feature (normalise)
    df["ctx_va_developing_10_atr"] = va_developing_atr  # ML feature (normalise)
    df["ctx_ib_extension_ratio"] = _ctx_ib_extension_ratio(df)
    df["ctx_rotation_factor_20"] = _ctx_rotation_factor_20(df)

    # Bloc 2 : Auctions (1 feature : failed_auction signed)
    df["ctx_failed_auction"] = _ctx_failed_auction(df, tick=tick)

    # Bloc 3 : Climax/Exhaustion/Absorption (5 features)
    df["ctx_vol_z_5"] = _ctx_vol_z_5(df)
    df["ctx_delta_sum_3"] = _ctx_delta_sum_3(df)
    df["ctx_delta_exhaustion"] = _ctx_delta_exhaustion(df)
    instant_absorption = _ctx_instant_absorption(df)
    df["ctx_instant_absorption"] = instant_absorption
    # FIX 27/04 (code-reviewer) : passer en parametre explicite, pas via df
    df["ctx_absorption_streak_5"] = _ctx_absorption_streak_5(instant_absorption)

    return df
