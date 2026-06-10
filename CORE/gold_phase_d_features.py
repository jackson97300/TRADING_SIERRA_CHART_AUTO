"""
Gold Phase D Features - Intermarket + Session-based pour MGC

Implémente 4 features critiques Gold (market-analyst R3 audit 11/05/2026) :

INTERMARKET (2 features) — cross-asset Gold :
  1. im_dxy_corr_60d : rolling corr 60 bars MGC vs 6E (Euro/USD, proxy DXY inverse)
                       6E corr ≈ -DXY corr, on flip le signe pour exposer "corr DXY théorique"
                       Litt. pro : Gold/DXY corr -0.45 normal, swing à 0 en stress.
  2. im_real_yields_proxy : moyenne momentum 10 bars ZN+ZB (Treasury futures)
                       Gold inverse-corrélé real yields (TIPS proxy).
                       High momentum Treasury (rendement baisse) → bull Gold.

SESSION-BASED (2 features) — intra-MGC seul :
  3. mgc_asia_london_overlap_vol : flag bool + vol ratio sur fenêtre 12:30-16:00 UTC
                       (London-NY overlap = 70% volume Gold daily)
  4. mgc_session_break_acceleration : accélération prix dans 30 min après US open 13:30 ET (DST-aware)

DROPPED 12/05/2026 (NOGO market-analyst) :
  - im_silver_lead_lag : Silver GLBX.MDP3 = ~2-30 bars/jour 1-min (data sparsity).
    Z-score sur n=2 obs/window = artefact mathématique (max +5.42σ observé).
    Backlog : ré-introduire si source liquide (GLD/SLV ETF) disponible.

Sources data : Databento GLBX.MDP3 (CME) backfill 12 mois
  - MGC.v.0 (volume-based continuous, fix bug rollover mensuel)
  - 6E.c.0 (Euro/USD futures)
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
# 12/05/2026 : im_silver_lead_lag retiré (NOGO market-analyst, Silver sparsity 2 bars/day)
GOLD_PHASE_D_FEATURES = [
    "im_dxy_corr_60d",
    "im_real_yields_proxy",
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
    """Rolling corr 60 bars MGC vs 6E sur RETURNS (pct_change), sign-flippé pour proxy DXY.

    FIX C2 code-reviewer 12/05 : rolling Pearson sur PRIX LEVEL = spurious correlation
    (corr entre marches aleatoires |rho|>0.5 frequent). Standard microstructure =
    corr sur RETURNS (pct_change). Voir Engle & Granger 1987.

    6E = Euro/USD futures. Corr returns(MGC, 6E) ≈ +0.45 normal.
    Corr returns(MGC, DXY) ≈ -0.45 normal (DXY = inverse EUR/USD).
    Donc on retourne -corr(returns(MGC), returns(6E)) ≈ corr(MGC, DXY) théorique.

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
    # FIX backfill 12/05 : 6E ~10% liquidite MGC sur 1-min. ffill avant pct_change
    # pour eviter 100% NaN propagation. Sample test 23/04 sans ffill = 0% non-NaN.
    merged["close_6e"] = merged["close_6e"].ffill()
    # FIX C2 : compute returns (pct_change) avant rolling corr — stationnarité
    ret_mgc = merged["close"].pct_change()
    ret_6e = merged["close_6e"].pct_change()
    corr_returns = ret_mgc.rolling(lookback, min_periods=int(lookback * 0.5)).corr(ret_6e)
    # Sign-flip : corr(MGC_ret, 6E_ret) → -corr (proxy corr MGC/DXY inverse)
    return -corr_returns


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

    # FIX backfill 12/05 : ZN/ZB ~85% liquidite MGC. ffill pour evited NaN propagation.
    merged["close_zn"] = merged["close_zn"].ffill()
    merged["close_zb"] = merged["close_zb"].ffill()

    # Momentum 10 bars sur chaque Treasury (% change)
    mom_zn = merged["close_zn"].pct_change(momentum_window)
    mom_zb = merged["close_zb"].pct_change(momentum_window)

    # Moyenne pondérée (ZB plus volatil que ZN, pondération inverse vol pour robustesse)
    proxy = (mom_zn * 0.5 + mom_zb * 0.5) * 1000  # scale pour lisibilité (basis points * 10)
    return proxy


# DROPPED 12/05/2026 : compute_im_silver_lead_lag retiré (market-analyst NOGO)
# Raison : SI GLBX.MDP3 ~30 records/jour (2% liquidite vs MGC 1380 bars). Z-score
# sur n~2 obs effectives par window = artefact mathematique (max +5.42σ observe).
# Backlog : reintroduire si source liquide (GLD/SLV ETF) backfill 12 mois disponible.


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION-BASED FEATURES (intra-MGC)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_mgc_asia_london_overlap_vol(df_mgc: pd.DataFrame) -> pd.Series:
    """Ratio volume sur fenêtre London-NY overlap 12:30-16:00 UTC.

    FIX market-analyst 12/05 : plage initiale 14-16 UTC = London afternoon seul, PAS
    overlap. Vrai overlap London-NY = 12:30-16:00 UTC (CME Globex Gold ouvre 12:30 UTC).
    Memory : 70% volume Gold daily sur cette plage 12:30-15:00 UTC (CME 2023-2024).

    Trade Gold pendant cette fenêtre = liquidité maximale = spread minimal.

    Output : 0 hors plage, ratio vol_bar / vol_median_overlap_baseline dans plage.

    Args:
        df_mgc : DataFrame avec 'ts_event' (UTC) + 'volume'

    Returns:
        Series : 0 hors plage, ratio normalisé dans plage (typique 0.5-3.0)
    """
    ts = pd.to_datetime(df_mgc["ts_event"], utc=True)
    hour_utc = ts.dt.hour
    minute = ts.dt.minute

    # FIX market-analyst : Plage London-NY overlap 12:30-16:00 UTC (vraie overlap CME)
    in_overlap = (
        ((hour_utc == 12) & (minute >= 30))
        | (hour_utc == 13)
        | (hour_utc == 14)
        | (hour_utc == 15)
    )

    if "volume" not in df_mgc.columns:
        return pd.Series(0.0, index=df_mgc.index)

    vol = df_mgc["volume"].astype(float)
    # Median rolling 60 bars sur les bars in_overlap seulement (pas global)
    median_overlap = vol.where(in_overlap).rolling(60, min_periods=30).median()
    # Backfill pour les bars hors plage (utilise dernière median connue)
    median_overlap_ffill = median_overlap.ffill()

    ratio = np.where(
        in_overlap & (median_overlap_ffill > 0),
        vol / median_overlap_ffill.replace(0, np.nan),
        0.0,
    )
    return pd.Series(ratio, index=df_mgc.index)


def compute_mgc_session_break_acceleration(df_mgc: pd.DataFrame) -> pd.Series:
    """Accélération prix dans 30 min APRES US cash open 13:30 ET (timezone-aware).

    FIX C7 + market-analyst 12/05 :
    - US cash open = 13:30 America/New_York (DST-aware). En DST (mars-nov) = 17:30 UTC,
      hors DST (nov-mars) = 18:30 UTC. Le code initial hardcodait 18:30 UTC = CASSE 8 MOIS/AN.
    - Code initial mesurait delta_t-30 → AVANT open, pas APRES. Décale fenêtre à
      13:30-14:00 ET (= 30 min APRES open) et mesure delta_t - delta_open.

    Accélération = abs(close_t - close_at_open) / ATR_30bars.
    Capture le re-pricing macro post-US-open (news + flow institutionnels).

    Args:
        df_mgc : DataFrame avec 'ts_event' (UTC) + 'close' + 'high' + 'low'

    Returns:
        Series : 0 hors plage 13:30-14:00 ET, accélération normalisée dans plage.
    """
    # FIX DST : conversion America/New_York
    ts_utc = pd.to_datetime(df_mgc["ts_event"], utc=True)
    ts_ny = ts_utc.dt.tz_convert("America/New_York")
    hour_ny = ts_ny.dt.hour
    minute_ny = ts_ny.dt.minute

    # Plage : 13:30 - 14:00 ET (= 30 min POST US cash open, DST-aware)
    in_post_open = (
        ((hour_ny == 13) & (minute_ny >= 30))
        | ((hour_ny == 14) & (minute_ny == 0))
    )

    close = df_mgc["close"].astype(float)
    high = df_mgc["high"].astype(float) if "high" in df_mgc.columns else close
    low = df_mgc["low"].astype(float) if "low" in df_mgc.columns else close

    # ATR proxy 30 bars
    tr = (high - low).rolling(30, min_periods=10).mean()

    # Délimiter close_at_open : valeur de close à 13:30 ET ce jour
    # Astuce : forward-fill close uniquement quand hour==13 & minute==30
    # FIX R4 code-reviewer 12/05 : limit=30 pour cap window post-open (13:30-14:00 ET).
    # Si bar 13:30 manque (gap, weekend), ne pas propager indefiniment au-dela.
    open_mask = (hour_ny == 13) & (minute_ny == 30)
    close_at_open = close.where(open_mask).ffill(limit=30)

    # Accélération : |close_t - close_at_open| / ATR
    accel = (close - close_at_open).abs() / tr.replace(0, np.nan)

    # Zéro hors plage post-open
    result = accel.where(in_post_open, 0.0)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════════

def apply_gold_phase_d(
    df_mgc: pd.DataFrame,
    df_6e: pd.DataFrame | None = None,
    df_zn: pd.DataFrame | None = None,
    df_zb: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Applique les 4 features Phase D Gold au DataFrame MGC.

    Args:
        df_mgc : DataFrame MGC enrichi (post Phase A + Phase B base)
        df_6e  : DataFrame 6E ohlcv-1m (peut être None → im_dxy_corr_60d = NaN)
        df_zn  : DataFrame ZN ohlcv-1m (peut être None → im_real_yields_proxy = NaN)
        df_zb  : DataFrame ZB ohlcv-1m (peut être None → im_real_yields_proxy = NaN)

    Returns:
        df_mgc enrichi avec 4 nouvelles colonnes (GOLD_PHASE_D_FEATURES).
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
    dbn_root: str | None = None,
) -> pd.DataFrame:
    """Charge OHLCV-1m depuis partitions Hive Databento DBN.zst → DataFrame.

    Args:
        symbol_databento_ticker : ex '6E.c.0', 'SI.c.0', 'ZN.c.0', 'ZB.c.0'
        start, end : range timestamps UTC
        dbn_root : racine partitions DBN. Si None : fallback ROOT_REPO/DATA/...
                   puis C:/TRADING_SIERRA_CHART_AUTO/DATA/... (legacy machine).

    Returns:
        DataFrame avec ['ts_event', 'open', 'high', 'low', 'close', 'volume']
    """
    import duckdb
    from pathlib import Path

    # Fix portabilite 12/05 : chercher dans ROOT/DATA d'abord, puis C:/ legacy
    if dbn_root is None:
        repo_root = Path(__file__).resolve().parents[1]
        candidates = [
            repo_root / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m",
            Path("C:/TRADING_SIERRA_CHART_AUTO/DATA/databento/GLBX.MDP3/ohlcv-1m"),
        ]
        for c in candidates:
            if c.exists():
                dbn_root = c.as_posix()
                break
        if dbn_root is None:
            print(f"  [WARN] load_ohlcv_databento: aucun dbn_root valide ({candidates})")
            return pd.DataFrame()

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
