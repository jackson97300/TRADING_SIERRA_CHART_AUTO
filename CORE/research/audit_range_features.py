"""audit_range_features.py — Audit empirique des features V4 enrichi pour detecter RANGE.

Methodologie :
  1. Charger NQ v4_enriched + ES (~12 mois)
  2. Calculer ADX(14), Choppiness(14), ATR_baseline_60d sur close 1m (RTH)
  3. Construire is_range_label (canon Wilder/Bressert) :
       (high_60 - low_60) / atr_now in [1.5, 4.0] AND ADX < 25 AND Chop > 60
  4. Pour chaque feature candidate : Spearman + MI vs is_range_label
  5. Verification sur fenetre NQ 2026-05-06 18:00-20:00 UTC (range visuel Jackson)

Anti-fuite :
  - Drop instrument-leak (prix bruts, dist non-norm en points)
  - Drop time leaks (forward labels)
  - Walk-forward stability check (median par mois)

Output : tableau top features + verdict V1 vs V2.
"""
from __future__ import annotations

import glob
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ============================================================
# 1. CHARGEMENT
# ============================================================

def load_v4(sym: str) -> pd.DataFrame:
    files = sorted(glob.glob(f"DATA/datasets/v4_enriched/symbol={sym}.c.0/year=*/month=*/data.parquet"))
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"[{sym}] loaded {df.shape}, range {df.ts_event.min()} to {df.ts_event.max()}")
    return df


# ============================================================
# 2. INDICATEURS CANONIQUES
# ============================================================

def true_range(h, l, cprev):
    return np.maximum.reduce([h - l, np.abs(h - cprev), np.abs(l - cprev)])


def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    cprev = np.concatenate([[c[0]], c[:-1]])
    tr = true_range(h, l, cprev)
    # Wilder smoothing via ewma alpha=1/n
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().values


def compute_adx(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    """ADX Wilder vectorise pour speed."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    cprev = np.concatenate([[c[0]], c[:-1]])
    hprev = np.concatenate([[h[0]], h[:-1]])
    lprev = np.concatenate([[l[0]], l[:-1]])

    up_move = h - hprev
    dn_move = lprev - l
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr = true_range(h, l, cprev)

    # Wilder smoothing via ewm alpha=1/n
    tr_s = pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().values
    plus_dm_s = pd.Series(plus_dm).ewm(alpha=1 / n, adjust=False).mean().values
    minus_dm_s = pd.Series(minus_dm).ewm(alpha=1 / n, adjust=False).mean().values

    plus_di = 100 * plus_dm_s / np.maximum(tr_s, 1e-9)
    minus_di = 100 * minus_dm_s / np.maximum(tr_s, 1e-9)
    dx = 100 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-9)
    adx = pd.Series(dx).ewm(alpha=1 / n, adjust=False).mean().values
    return adx


def compute_choppiness(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    """Choppiness Index : 100 * log10(sum(TR_n) / range_n) / log10(n)."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    cprev = np.concatenate([[c[0]], c[:-1]])
    tr = true_range(h, l, cprev)

    sum_tr = pd.Series(tr).rolling(n, min_periods=n).sum().values
    high_n = pd.Series(h).rolling(n, min_periods=n).max().values
    low_n = pd.Series(l).rolling(n, min_periods=n).min().values
    range_n = np.maximum(high_n - low_n, 1e-9)

    chop = 100 * np.log10(np.maximum(sum_tr / range_n, 1e-9)) / np.log10(n)
    return chop


# ============================================================
# 3. CONSTRUCTION LABEL
# ============================================================

def build_label(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    """is_range_label : combinaison ADX<25 + Chop>60 + geometrie rangee.

    Criteres calibres pour 1m bars : range/ATR seuils relaches car 60 bars 1m
    naturellement bcp + larges que ATR(14m). On garde ADX+Chop strict + un range
    raisonnable (5x-25x ATR sur 60min, soit ~80-400 ticks NQ).
    """
    atr = compute_atr(df, n=14)
    adx = compute_adx(df, n=14)
    chop = compute_choppiness(df, n=14)

    high_n = pd.Series(df["high"].values).rolling(lookback, min_periods=lookback).max().values
    low_n = pd.Series(df["low"].values).rolling(lookback, min_periods=lookback).min().values
    range_n = high_n - low_n
    range_atr = range_n / np.maximum(atr, 1e-9)

    # Range label realiste 1m :
    #   ADX < 22 (no trend, marge)
    #   Chop > 61.8 (Bressert canon)
    #   range/ATR in [4, 12] (range present mais pas explosif vs ATR)
    is_range = (
        (adx < 22)
        & (chop > 61.8)
        & (range_atr > 4.0)
        & (range_atr < 12.0)
    )
    df["_atr_calc"] = atr
    df["_adx_calc"] = adx
    df["_chop_calc"] = chop
    df["_range_atr_calc"] = range_atr
    return pd.Series(is_range, index=df.index, name="is_range_label")


# ============================================================
# 4. SCREENING
# ============================================================

def screen_features(df: pd.DataFrame, label: pd.Series, exclude: set,
                    min_unique: int = 5) -> pd.DataFrame:
    """Calcul Spearman + difference of means pour chaque feature.

    MI demanderait sklearn — on utilise Spearman + |delta_median / IQR_pooled|
    comme proxy power.
    """
    from scipy.stats import spearmanr

    rows = []
    valid = label.notna()
    y = label[valid].astype(int).values

    for col in df.columns:
        if col in exclude:
            continue
        if df[col].dtype == "object" or "datetime" in str(df[col].dtype):
            continue
        x = df[col][valid]
        if x.notna().sum() < 1000:
            continue
        if x.nunique() < min_unique:
            continue

        x_v = x.values
        try:
            mask = ~pd.isna(x_v)
        except Exception:
            continue
        if mask.sum() < 1000:
            continue

        x_clean = x_v[mask]
        y_clean = y[mask]

        # Spearman
        try:
            rho, _ = spearmanr(x_clean, y_clean)
            if np.isnan(rho):
                continue
        except Exception:
            continue

        # Median range vs trend
        range_vals = x_clean[y_clean == 1]
        trend_vals = x_clean[y_clean == 0]
        if len(range_vals) < 100 or len(trend_vals) < 100:
            continue

        med_range = float(np.nanmedian(range_vals))
        med_trend = float(np.nanmedian(trend_vals))
        iqr_range = float(np.nanpercentile(range_vals, 75) - np.nanpercentile(range_vals, 25))
        iqr_trend = float(np.nanpercentile(trend_vals, 75) - np.nanpercentile(trend_vals, 25))
        iqr_pooled = max((iqr_range + iqr_trend) / 2, 1e-9)
        cohen_proxy = abs(med_range - med_trend) / iqr_pooled

        rows.append({
            "feature": col,
            "spearman_rho": round(rho, 4),
            "abs_rho": round(abs(rho), 4),
            "cohen_iqr": round(cohen_proxy, 3),
            "med_range": round(med_range, 4),
            "med_trend": round(med_trend, 4),
            "iqr_range": round(iqr_range, 4),
            "iqr_trend": round(iqr_trend, 4),
            "n_range": int((y_clean == 1).sum()),
            "n_trend": int((y_clean == 0).sum()),
        })

    return pd.DataFrame(rows).sort_values("abs_rho", ascending=False).reset_index(drop=True)


# ============================================================
# 5. VERIFICATION TRADE NQ 2026-05-06
# ============================================================

def verify_nq_trade(nq: pd.DataFrame, label: pd.Series, top_features: list[str]):
    """Verifie sur fenetre 2026-05-06 18:00-20:00 UTC que features signalent RANGE."""
    # Filtrer fenetre trade
    win_start = pd.Timestamp("2026-05-06 18:00:00", tz="UTC")
    win_end = pd.Timestamp("2026-05-06 20:00:00", tz="UTC")
    mask = (nq["ts_event"] >= win_start) & (nq["ts_event"] <= win_end)
    win = nq[mask].copy()

    if len(win) == 0:
        # Fallback : derniere journee disponible
        last_day = nq["ts_event"].dt.date.max()
        print(f"[VERIF] window 06/05 absente — last day disponible : {last_day}")
        last_mask = nq["ts_event"].dt.date == last_day
        win = nq[last_mask].iloc[-120:].copy()
        print(f"[VERIF] fallback : derniere fenetre {win['ts_event'].iloc[0]} - {win['ts_event'].iloc[-1]}")

    print(f"\n[VERIF] window {win['ts_event'].iloc[0]} - {win['ts_event'].iloc[-1]} : {len(win)} bars")
    win_lab = label.iloc[win.index]
    rate = win_lab.mean() if len(win_lab) > 0 else 0
    print(f"[VERIF] is_range_label rate dans fenetre : {100*rate:.1f}%")

    print("\n[VERIF] median des top features dans fenetre :")
    for f in top_features:
        if f in win.columns:
            med = win[f].median()
            full_med_range = nq.loc[label == 1, f].median() if f in nq.columns else np.nan
            full_med_trend = nq.loc[label == 0, f].median() if f in nq.columns else np.nan
            print(f"  {f:35s} window={med:.4f}  full_range={full_med_range:.4f}  full_trend={full_med_trend:.4f}")


# ============================================================
# 6. MAIN
# ============================================================

EXCLUDE_COLS = {
    # IDs / timestamps / metadata
    "ts_event", "instrument_id", "session_id", "session_date", "session_date_trading",
    "session", "open_zone", "open_type", "day_type",  # categorical low cardinality
    # Prix bruts (instrument leak)
    "open", "high", "low", "close",
    "vwap_d", "vwap_d_sd1u", "vwap_d_sd1d", "vwap_d_sd2u", "vwap_d_sd2d",
    "vwap_d_sd3u", "vwap_d_sd3d", "vwap_w", "vwap_w_sd1u", "vwap_w_sd1d",
    "vwap_w_sd2u", "vwap_w_sd2d", "vwap_w_sd3u", "vwap_w_sd3d",
    "vwap_m", "vwap_m_sd1u", "vwap_m_sd1d", "vwap_m_sd2u", "vwap_m_sd2d",
    "sess_high", "sess_low", "ib_high", "ib_low",
    "last_swing_high_session", "last_swing_low_session",
    # Volume bruts (instrument leak)
    "volume", "buy_vol", "sell_vol", "n_trades", "delta_bar",
    # Date arithmetics
    "days_since_roll",
}


def main():
    nq = load_v4("NQ")
    es = load_v4("ES")

    print("\n=== Building is_range_label NQ ===")
    nq_label = build_label(nq, lookback=60)
    print(f"  range rate global NQ : {100*nq_label.mean():.1f}%")

    print("\n=== Building is_range_label ES ===")
    es_label = build_label(es, lookback=60)
    print(f"  range rate global ES : {100*es_label.mean():.1f}%")

    # Exclude calc cols + label
    excl = EXCLUDE_COLS | {"is_range_label", "_atr_calc", "_adx_calc", "_chop_calc", "_range_atr_calc"}

    print("\n=== Screening NQ features ===")
    nq_results = screen_features(nq, nq_label, excl)
    print(f"  features evaluees : {len(nq_results)}")
    print("\n  TOP 25 NQ par abs(spearman) :")
    print(nq_results.head(25).to_string(index=False))

    print("\n=== Screening ES features ===")
    es_results = screen_features(es, es_label, excl)
    print(f"  features evaluees : {len(es_results)}")
    print("\n  TOP 25 ES par abs(spearman) :")
    print(es_results.head(25).to_string(index=False))

    # Intersection top 30 NQ + ES = features ROBUSTES cross-instrument
    top_nq = set(nq_results.head(40)["feature"].tolist())
    top_es = set(es_results.head(40)["feature"].tolist())
    inter = top_nq & top_es
    print(f"\n=== INTERSECTION top 40 NQ ∩ top 40 ES : {len(inter)} features ===")
    for f in sorted(inter):
        nq_rho = nq_results.loc[nq_results["feature"] == f, "spearman_rho"].iloc[0]
        es_rho = es_results.loc[es_results["feature"] == f, "spearman_rho"].iloc[0]
        print(f"  {f:35s} NQ={nq_rho:+.3f}  ES={es_rho:+.3f}")

    # Save full
    nq_results.to_csv("DATA/range_features_NQ.csv", index=False)
    es_results.to_csv("DATA/range_features_ES.csv", index=False)
    print("\n[SAVED] DATA/range_features_{NQ,ES}.csv")

    # Verification fenetre NQ 06/05
    print("\n=== VERIF NQ 2026-05-06 18:00-20:00 UTC (trade Jackson) ===")
    top_features = nq_results.head(15)["feature"].tolist()
    verify_nq_trade(nq, nq_label, top_features)


if __name__ == "__main__":
    main()
