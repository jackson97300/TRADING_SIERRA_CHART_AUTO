"""Gold Extra Features — features state-of-the-art Gold trading (12/05/2026).

Complète gold_phase_d_features.py avec features pro additionnelles :

CROSS-ASSET RATIOS (mean reversion edges classiques pro) :
  1. gold_silver_ratio          : Gold price / Silver price
  2. gold_silver_ratio_zscore_60d : z-score 60 bars (mean rev signal extrême)
  3. copper_gold_ratio          : Copper / Gold (risk-on/off proxy)
  4. copper_gold_ratio_momentum_30 : momentum 30 bars (leading indicator)
  5. oil_gold_ratio_zscore_60d  : Oil / Gold z-score (inflation proxy)

SESSION MICROSTRUCTURE :
  6. london_fix_window_10_30    : flag bool +/-5 min autour 10:30 GMT London fix
  7. london_fix_window_15_00    : flag bool +/-5 min autour 15:00 GMT London fix
  8. asia_breakout_strength     : range Asia session / ATR (continuation signal)

Sources Databento :
  - SI.c.0 (Silver), HG.c.0 (Copper), CL.c.0 (Oil)
  - MGC.v.0 base

Auteur : MIA Trading System
Date : 2026-05-12
"""
from __future__ import annotations
import numpy as np
import pandas as pd


GOLD_EXTRA_FEATURES = [
    "gold_silver_ratio",
    "gold_silver_ratio_zscore_60d",
    "copper_gold_ratio",
    "copper_gold_ratio_momentum_30",
    "oil_gold_ratio_zscore_60d",
    "london_fix_window_10_30",
    "london_fix_window_15_00",
    "asia_breakout_strength",
]


# ─────────────────────────────────────────────────────────────────────────────
# RATIO FEATURES
# ─────────────────────────────────────────────────────────────────────────────

def _merge_pair(df_mgc: pd.DataFrame, df_other: pd.DataFrame, suffix: str) -> pd.DataFrame:
    """Merge MGC with other symbol on ts_event, ffill missing bars."""
    merged = df_mgc[["ts_event", "close"]].merge(
        df_other[["ts_event", "close"]].rename(columns={"close": f"close_{suffix}"}),
        on="ts_event", how="left",
    )
    # ffill car certains symboles ont moins de bars que MGC sur 1-min
    merged[f"close_{suffix}"] = merged[f"close_{suffix}"].ffill()
    return merged


def compute_gold_silver_ratio(df_mgc: pd.DataFrame, df_si: pd.DataFrame) -> pd.Series:
    """Gold / Silver ratio.

    Edge connu pro : ratio mean ~80 historique, extrême >100 ou <60 = mean reversion.
    Quand ratio explosé haut → Silver under-priced vs Gold → spread compression à venir.

    Args:
        df_mgc : DataFrame MGC ['ts_event', 'close']
        df_si  : DataFrame SI ['ts_event', 'close']
    Returns:
        pd.Series ratio (typique 60-110)
    """
    merged = _merge_pair(df_mgc, df_si, "si")
    # Gold (MGC) en $/oz × 10 (micro), Silver (SI) en $/oz × 5000.
    # Pour ratio normalisé Gold price / Silver price, on utilise les prix bruts (unité $/oz comparable)
    # Gold ~$4000/oz, Silver ~$50/oz → ratio ~80
    ratio = merged["close"] / merged["close_si"].replace(0, np.nan)
    return ratio


def compute_gold_silver_ratio_zscore(df_mgc: pd.DataFrame, df_si: pd.DataFrame,
                                     lookback: int = 60) -> pd.Series:
    """Z-score rolling 60 bars du Gold/Silver ratio.

    Signal pro : |z| > 2 = setup mean reversion potentiel.
    """
    ratio = compute_gold_silver_ratio(df_mgc, df_si)
    rolling_mean = ratio.rolling(lookback, min_periods=int(lookback * 0.5)).mean()
    rolling_std = ratio.rolling(lookback, min_periods=int(lookback * 0.5)).std()
    zscore = (ratio - rolling_mean) / rolling_std.replace(0, np.nan)
    return zscore


def compute_copper_gold_ratio(df_mgc: pd.DataFrame, df_hg: pd.DataFrame) -> pd.Series:
    """Copper / Gold ratio.

    Edge connu : Copper / Gold = leading indicator risk appetite + GDP nominal.
    Quand Cu/Au monte → industrials > safe haven → bull regime. Quand baisse → risk-off.

    Args:
        df_mgc : DataFrame MGC
        df_hg  : DataFrame HG (Copper) — prix en $/lb
    Returns:
        pd.Series : Copper $/lb / Gold $/oz (ordre de grandeur 0.001)
    """
    merged = _merge_pair(df_mgc, df_hg, "hg")
    ratio = merged["close_hg"] / merged["close"].replace(0, np.nan)
    return ratio


def compute_copper_gold_ratio_momentum(df_mgc: pd.DataFrame, df_hg: pd.DataFrame,
                                       window: int = 30) -> pd.Series:
    """Momentum 30 bars du Copper/Gold ratio (pct change).

    Signal : momentum positif Cu/Au = risk-on incoming → bearish Gold à moyen terme.
    """
    ratio = compute_copper_gold_ratio(df_mgc, df_hg)
    return ratio.pct_change(window) * 100  # en %


def compute_oil_gold_ratio_zscore(df_mgc: pd.DataFrame, df_cl: pd.DataFrame,
                                  lookback: int = 60) -> pd.Series:
    """Z-score 60 bars du Oil/Gold ratio.

    Edge : Oil/Gold = inflation regime proxy. Spike haut = inflation expectations rising → bull Gold mid-term.

    Args:
        df_cl : DataFrame CL (Crude Oil) — prix en $/bbl
    """
    merged = _merge_pair(df_mgc, df_cl, "cl")
    ratio = merged["close_cl"] / merged["close"].replace(0, np.nan)
    rolling_mean = ratio.rolling(lookback, min_periods=int(lookback * 0.5)).mean()
    rolling_std = ratio.rolling(lookback, min_periods=int(lookback * 0.5)).std()
    return (ratio - rolling_mean) / rolling_std.replace(0, np.nan)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION MICROSTRUCTURE FEATURES
# ─────────────────────────────────────────────────────────────────────────────

def compute_london_fix_window(df_mgc: pd.DataFrame, fix_hour_gmt: int,
                              fix_minute_gmt: int = 0, window_min: int = 5) -> pd.Series:
    """Flag bool : 1 si bar dans fenêtre +/-X min autour London Gold Fix.

    London Gold Fixings :
      - AM Fix : 10:30 GMT (approx 10:30 UTC pas DST UK = 10:30 BST = 09:30 UTC en été)
      - PM Fix : 15:00 GMT (15:00 UTC pas DST = 14:00 UTC en été)

    Note : on utilise UTC (Databento ts_event UTC). En été (BST), London Fix réel = 09:30/14:00 UTC.
    En hiver (GMT), London Fix = 10:30/15:00 UTC. On garde UTC fix_hour fournie par caller.

    Edge connu : volatility spike + reprise institutional liquidity autour des fixings.

    Args:
        df_mgc : DataFrame avec ts_event UTC
        fix_hour_gmt : heure UTC du fix (10 pour AM, 15 pour PM en hiver ; 9/14 en été)
        fix_minute_gmt : minute (default 0 pour 15:00, 30 pour 10:30)
        window_min : fenêtre +/- en minutes (default 5)
    Returns:
        pd.Series : 1 dans fenêtre, 0 hors
    """
    ts = pd.to_datetime(df_mgc["ts_event"], utc=True)
    # Convert to minutes since midnight UTC
    minutes_utc = ts.dt.hour * 60 + ts.dt.minute
    fix_minutes = fix_hour_gmt * 60 + fix_minute_gmt
    in_window = (minutes_utc >= fix_minutes - window_min) & (minutes_utc <= fix_minutes + window_min)
    return in_window.astype(int)


def compute_london_fix_window_10_30(df_mgc: pd.DataFrame) -> pd.Series:
    """AM London Fix : 10:30 GMT (≈ 10:30 UTC hiver, 09:30 UTC été DST).

    Approximation simple : fenêtre 10:25-10:35 UTC (ne corrige pas DST, accepte 4-5 mois biais).
    """
    return compute_london_fix_window(df_mgc, fix_hour_gmt=10, fix_minute_gmt=30, window_min=5)


def compute_london_fix_window_15_00(df_mgc: pd.DataFrame) -> pd.Series:
    """PM London Fix : 15:00 GMT (≈ 15:00 UTC hiver, 14:00 UTC été DST).

    Fenêtre 14:55-15:05 UTC.
    """
    return compute_london_fix_window(df_mgc, fix_hour_gmt=15, fix_minute_gmt=0, window_min=5)


def compute_asia_breakout_strength(df_mgc: pd.DataFrame) -> pd.Series:
    """Range Asia session (00:00-07:00 UTC approx) / ATR_14m.

    Edge pro : range Asia large = setup continuation directional jour. Range Asia étroit = consolidation
    → breakout NY session probable.

    Calcul : pour chaque bar, range = max(high) - min(low) sur toutes les bars Asia du jour courant /
    ATR_14m moyen sur la session Asia. Ratio > 2 = breakout fort à venir.

    Output : 0 hors Asia, ratio normalisé dans Asia.
    """
    if "is_in_asia" not in df_mgc.columns or "atr" not in df_mgc.columns:
        return pd.Series(0.0, index=df_mgc.index)

    ts = pd.to_datetime(df_mgc["ts_event"], utc=True)
    df = df_mgc.copy()
    df["_date"] = ts.dt.date
    df["_in_asia"] = df["is_in_asia"].fillna(0).astype(int)

    # Pour chaque jour, range Asia
    asia_mask = df["_in_asia"] == 1
    daily_asia_range = (
        df[asia_mask]
        .groupby("_date")
        .apply(lambda g: g["high"].max() - g["low"].min() if len(g) > 0 else 0.0)
    )
    # ATR moyen Asia per day
    daily_asia_atr = df[asia_mask].groupby("_date")["atr"].mean()

    # Ratio per day
    daily_ratio = daily_asia_range / daily_asia_atr.replace(0, np.nan)
    # Broadcast back
    df = df.merge(daily_ratio.rename("asia_ratio"), left_on="_date", right_index=True, how="left")
    # Zéro hors Asia
    df["asia_ratio"] = df["asia_ratio"].where(df["_in_asia"] == 1, 0.0)
    df["asia_ratio"] = df["asia_ratio"].fillna(0.0)
    return df["asia_ratio"].values


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATION
# ─────────────────────────────────────────────────────────────────────────────

def apply_gold_extra_features(
    df_mgc: pd.DataFrame,
    df_si: pd.DataFrame | None = None,
    df_hg: pd.DataFrame | None = None,
    df_cl: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Applique les 8 features Gold extra au DataFrame MGC.

    Args:
        df_mgc : DataFrame MGC enrichi (post Phase A+B+D session)
        df_si  : DataFrame SI (Silver) — peut être None → ratio NaN
        df_hg  : DataFrame HG (Copper) — peut être None
        df_cl  : DataFrame CL (Oil) — peut être None
    Returns:
        df_mgc + 8 nouvelles colonnes
    """
    df = df_mgc.copy()
    drop_cols = [c for c in GOLD_EXTRA_FEATURES if c in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    # Ratios cross-asset
    if df_si is not None and not df_si.empty:
        df["gold_silver_ratio"] = compute_gold_silver_ratio(df, df_si).values
        df["gold_silver_ratio_zscore_60d"] = compute_gold_silver_ratio_zscore(df, df_si).values
    else:
        df["gold_silver_ratio"] = np.nan
        df["gold_silver_ratio_zscore_60d"] = np.nan

    if df_hg is not None and not df_hg.empty:
        df["copper_gold_ratio"] = compute_copper_gold_ratio(df, df_hg).values
        df["copper_gold_ratio_momentum_30"] = compute_copper_gold_ratio_momentum(df, df_hg).values
    else:
        df["copper_gold_ratio"] = np.nan
        df["copper_gold_ratio_momentum_30"] = np.nan

    if df_cl is not None and not df_cl.empty:
        df["oil_gold_ratio_zscore_60d"] = compute_oil_gold_ratio_zscore(df, df_cl).values
    else:
        df["oil_gold_ratio_zscore_60d"] = np.nan

    # Session features (self-contained)
    df["london_fix_window_10_30"] = compute_london_fix_window_10_30(df).values
    df["london_fix_window_15_00"] = compute_london_fix_window_15_00(df).values
    df["asia_breakout_strength"] = compute_asia_breakout_strength(df)

    return df
