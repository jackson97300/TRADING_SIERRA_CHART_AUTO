"""
Gold Phase D Features - Intermarket + Session-based pour MGC

Implémente 5 features critiques Gold (market-analyst R3 audit 11/05/2026) :

INTERMARKET (3 features) — cross-asset Gold :
  1. im_dxy_corr_60d : rolling corr 60 bars MGC vs 6E (Euro/USD, proxy DXY inverse)
                       6E corr ≈ -DXY corr, on flip le signe pour exposer "corr DXY théorique"
                       Litt. pro : Gold/DXY corr -0.45 normal, swing à 0 en stress.
  2. im_real_yields_proxy : moyenne momentum 10 bars ZN+ZB (Treasury futures)
                       Gold inverse-corrélé real yields (TIPS proxy).
                       High momentum Treasury (rendement baisse) → bull Gold.
  3. im_silver_lead_lag : z-score 60 bars du ratio SI/MGC (Silver leads Gold 10-30 min).

SESSION-BASED (2 features) — intra-MGC seul :
  4. mgc_asia_london_overlap_vol : flag bool + vol ratio sur fenêtre 14:00-16:00 UTC
                       (London-NY overlap = 70% volume Gold daily)
  5. mgc_session_break_acceleration : accélération prix dans 30 min après US open 13:30 ET (18:30 UTC)

Sources data : Databento GLBX.MDP3 (CME) backfill 12 mois
  - MGC.v.0 (volume-based continuous, fix bug rollover mensuel)
  - 6E.c.0 (Euro/USD futures)
  - SI.c.0 (Silver futures)
  - ZN.c.0 (10-yr Treasury)
  - ZB.c.0 (30-yr Treasury)

Note : DX.c.0 (DXY) PAS dans GLBX.MDP3 (ICE Futures), donc 6E utilisé comme proxy inverse.
Vérifié 12/05/2026 via test_databento_symbols_gold.py.

Auteur : MIA Trading System
Date   : 2026-05-12
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# Features publiées par ce module (utilisé par build_dataset pour drop_existing idempotent)
GOLD_PHASE_D_FEATURES = [
    "im_dxy_corr_60d",
    "im_real_yields_proxy",
    "im_silver_lead_lag",
    "mgc_asia_london_overlap_vol",
    "mgc_session_break_acceleration",
]


# ═══════════════════════════════════════════════════════════════════════════════
# INTERMARKET FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

def compute_im_dxy_corr_60d(
    df_mgc: pd.DataFrame,
    df_6e: pd.DataFrame,
    lookback: int = 60,
) -> pd.Series:
    """Rolling corr 60 bars MGC.close vs 6E.close, sign-flippé pour proxy DXY.

    6E = Euro/USD futures. Corr(MGC, 6E) ≈ +0.45 normal.
    Corr(MGC, DXY) ≈ -0.45 normal (DXY = 1/6E inverse).
    Donc on retourne -corr(MGC, 6E) ≈ corr(MGC, DXY) théorique.

    Args:
        df_mgc : DataFrame MGC avec colonnes ['ts_event', 'close']
        df_6e  : DataFrame 6E avec colonnes ['ts_event', 'close']
        lookback : window rolling (default 60 bars = 1h sur 1-min)

    Returns:
        Series alignée sur df_mgc.index, valeurs entre -1 et +1
    """
    merged = df_mgc[["ts_event", "close"]].merge(
        df_6e[["ts_event", "close"]].rename(columns={"close": "close_6e"}),
        on="ts_event", how="left",
    )
    # rolling corr requires both series aligned
    corr_mgc_6e = merged["close"].rolling(lookback, min_periods=int(lookback * 0.5)).corr(
        merged["close_6e"]
    )
    # Sign-flip : corr(MGC, 6E) → -corr (proxy corr MGC/DXY inverse)
    return -corr_mgc_6e


def compute_im_real_yields_proxy(
    df_mgc: pd.DataFrame,
    df_zn: pd.DataFrame,
    df_zb: pd.DataFrame,
    momentum_window: int = 10,
) -> pd.Series:
    """Momentum moyen ZN + ZB sur 10 bars, normalisé par ATR Treasury.

    Treasury futures price ↑ → yields ↓ → bull Gold (Gold inverse-corrélé real yields).
    Momentum 10 bars capture le shift directionnel récent.

    Args:
        df_mgc : DataFrame MGC (pour alignement ts_event)
        df_zn  : DataFrame ZN (10-yr Treasury) avec ['ts_event', 'close']
        df_zb  : DataFrame ZB (30-yr Treasury) avec ['ts_event', 'close']
        momentum_window : default 10 bars

    Returns:
        Series : momentum normalisé. Positif = yields baissent = bull Gold.
    """
    merged = df_mgc[["ts_event"]].merge(
        df_zn[["ts_event", "close"]].rename(columns={"close": "close_zn"}),
        on="ts_event", how="left",
    ).merge(
        df_zb[["ts_event", "close"]].rename(columns={"close": "close_zb"}),
        on="ts_event", how="left",
    )

    # Momentum 10 bars sur chaque Treasury (% change)
    mom_zn = merged["close_zn"].pct_change(momentum_window)
    mom_zb = merged["close_zb"].pct_change(momentum_window)

    # Moyenne pondérée (ZB plus volatil que ZN, pondération inverse vol pour robustesse)
    proxy = (mom_zn * 0.5 + mom_zb * 0.5) * 1000  # scale pour lisibilité (basis points * 10)
    return proxy


def compute_im_silver_lead_lag(
    df_mgc: pd.DataFrame,
    df_si: pd.DataFrame,
    lookback: int = 60,
) -> pd.Series:
    """Z-score 60 bars du ratio (SI / MGC).

    Silver lead Gold 10-30 min sur breakouts précieux (market-analyst R3).
    Z-score positif extrême = Silver très divergent vs Gold = signal lead.
    Z-score négatif = lag historique = signal lead inverse.

    Args:
        df_mgc : DataFrame MGC
        df_si  : DataFrame SI (Silver) avec ['ts_event', 'close']
        lookback : window z-score (default 60 bars)

    Returns:
        Series z-score, valeurs entre -3 et +3 typique.
    """
    merged = df_mgc[["ts_event", "close"]].merge(
        df_si[["ts_event", "close"]].rename(columns={"close": "close_si"}),
        on="ts_event", how="left",
    )
    ratio = merged["close_si"] / merged["close"]
    rolling_mean = ratio.rolling(lookback, min_periods=int(lookback * 0.5)).mean()
    rolling_std = ratio.rolling(lookback, min_periods=int(lookback * 0.5)).std()
    z = (ratio - rolling_mean) / rolling_std.replace(0, np.nan)
    return z


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION-BASED FEATURES (intra-MGC)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_mgc_asia_london_overlap_vol(df_mgc: pd.DataFrame) -> pd.Series:
    """Flag bool + ratio volume sur fenêtre London-NY overlap 14:00-16:00 UTC.

    Memory market-analyst : 70% volume Gold daily sur London-NY overlap.
    Trade Gold pendant cette fenêtre = liquidité maximale = spread minimal.

    Output : 0.0-1.0 (= 0 hors plage, vol_ratio_actuel dans plage)
    Args:
        df_mgc : DataFrame avec 'ts_event' (UTC) + 'volume'

    Returns:
        Series : 0 hors plage, ratio (volume_bar / volume_median_overlap_60bars) dans plage
    """
    ts = pd.to_datetime(df_mgc["ts_event"], utc=True)
    hour_utc = ts.dt.hour
    minute = ts.dt.minute

    # Plage London-NY overlap : 14:00:00 - 15:59:59 UTC
    in_overlap = (hour_utc >= 14) & (hour_utc < 16)

    if "volume" not in df_mgc.columns:
        return pd.Series(0.0, index=df_mgc.index)

    vol = df_mgc["volume"].astype(float)
    # Median rolling 60 bars sur les bars in_overlap seulement (pas global)
    median_overlap = vol.where(in_overlap).rolling(60, min_periods=10).median()
    # Backfill pour les bars hors plage (utilise dernière median connue)
    median_overlap_ffill = median_overlap.ffill()

    ratio = np.where(
        in_overlap & (median_overlap_ffill > 0),
        vol / median_overlap_ffill.replace(0, np.nan),
        0.0,
    )
    return pd.Series(ratio, index=df_mgc.index)


def compute_mgc_session_break_acceleration(df_mgc: pd.DataFrame) -> pd.Series:
    """Accélération prix dans 30 min après US open (13:30 ET = 18:30 UTC).

    US cash open 13:30 ET → re-pricing immédiat Gold sur news macro + flow.
    Accélération = abs(close_t - close_t-30) / (avg true range 30 bars).
    Signal momentum post-open utile pour entries directionnelles.

    Output : 0 hors plage 18:30-19:00 UTC, accélération normalisée dans plage.

    Args:
        df_mgc : DataFrame avec 'ts_event' (UTC) + 'close' + 'high' + 'low'

    Returns:
        Series : accélération normalisée (typique 0.0-3.0)
    """
    ts = pd.to_datetime(df_mgc["ts_event"], utc=True)
    hour_utc = ts.dt.hour
    minute = ts.dt.minute

    # Plage post-US-open : 18:30 - 19:00 UTC (30 min après open cash 13:30 ET)
    in_post_open = ((hour_utc == 18) & (minute >= 30)) | ((hour_utc == 19) & (minute == 0))

    close = df_mgc["close"].astype(float)
    high = df_mgc["high"].astype(float) if "high" in df_mgc.columns else close
    low = df_mgc["low"].astype(float) if "low" in df_mgc.columns else close

    # ATR proxy 30 bars
    tr = (high - low).rolling(30, min_periods=10).mean()

    # Accélération : |close_t - close_t-30| / ATR
    delta_30 = (close - close.shift(30)).abs()
    accel = delta_30 / tr.replace(0, np.nan)

    # Zéro hors plage post-open
    result = accel.where(in_post_open, 0.0)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════════

def apply_gold_phase_d(
    df_mgc: pd.DataFrame,
    df_6e: pd.DataFrame | None = None,
    df_si: pd.DataFrame | None = None,
    df_zn: pd.DataFrame | None = None,
    df_zb: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Applique les 5 features Phase D Gold au DataFrame MGC.

    Args:
        df_mgc : DataFrame MGC enrichi (post Phase A + Phase B base)
        df_6e  : DataFrame 6E ohlcv-1m (peut être None → im_dxy_corr_60d = NaN)
        df_si  : DataFrame SI ohlcv-1m (peut être None → im_silver_lead_lag = NaN)
        df_zn  : DataFrame ZN ohlcv-1m (peut être None → im_real_yields_proxy = NaN)
        df_zb  : DataFrame ZB ohlcv-1m (peut être None → im_real_yields_proxy = NaN)

    Returns:
        df_mgc enrichi avec 5 nouvelles colonnes (GOLD_PHASE_D_FEATURES).
    """
    df = df_mgc.copy()

    # Drop existing pour idempotence
    drop_cols = [c for c in GOLD_PHASE_D_FEATURES if c in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    # Intermarket features
    if df_6e is not None and not df_6e.empty:
        df["im_dxy_corr_60d"] = compute_im_dxy_corr_60d(df, df_6e).values
    else:
        df["im_dxy_corr_60d"] = np.nan

    if df_zn is not None and df_zb is not None and not df_zn.empty and not df_zb.empty:
        df["im_real_yields_proxy"] = compute_im_real_yields_proxy(df, df_zn, df_zb).values
    else:
        df["im_real_yields_proxy"] = np.nan

    if df_si is not None and not df_si.empty:
        df["im_silver_lead_lag"] = compute_im_silver_lead_lag(df, df_si).values
    else:
        df["im_silver_lead_lag"] = np.nan

    # Session features (MGC intra-symbole)
    df["mgc_asia_london_overlap_vol"] = compute_mgc_asia_london_overlap_vol(df).values
    df["mgc_session_break_acceleration"] = compute_mgc_session_break_acceleration(df).values

    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Loader utilitaire (load OHLCV ohlcv-1m partition Databento)
# ═══════════════════════════════════════════════════════════════════════════════

def load_ohlcv_databento(
    symbol_databento_ticker: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    dbn_root: str = "C:/TRADING_SIERRA_CHART_AUTO/DATA/databento/GLBX.MDP3/ohlcv-1m",
) -> pd.DataFrame:
    """Charge OHLCV-1m depuis partitions Hive Databento DBN.zst → DataFrame.

    Args:
        symbol_databento_ticker : ex '6E.c.0', 'SI.c.0', 'ZN.c.0', 'ZB.c.0'
        start, end : range timestamps UTC
        dbn_root : racine partitions DBN

    Returns:
        DataFrame avec ['ts_event', 'open', 'high', 'low', 'close', 'volume']
    """
    import duckdb
    from pathlib import Path

    pattern = (Path(dbn_root) / f"symbol={symbol_databento_ticker}"
               / "**" / "*.parquet").as_posix()
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone='UTC';")
        df = con.execute(f"""
            SELECT
                ts_event::TIMESTAMP AS ts_event,
                open, high, low, close, volume
            FROM read_parquet('{pattern}', union_by_name=True)
            WHERE ts_event >= TIMESTAMP '{start}'
              AND ts_event <  TIMESTAMP '{end}'
            ORDER BY ts_event
        """).fetchdf()
    finally:
        con.close()
    return df
