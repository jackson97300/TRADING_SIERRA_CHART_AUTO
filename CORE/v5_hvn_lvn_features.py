"""
v5_hvn_lvn_features.py — HVN/LVN session features V5.

Created : 2026-05-02 samedi V5 build (Jackson validation Y).
Source : INVENTAIRE_DUMPER_VS_BOT.md TIER 2 ⭐⭐⭐⭐ (9 features manquantes V4).

Reproduit en Python depuis Databento trades (jamais re-import DMP polluant).

Volume profile per session :
  - Bucket prix = round(price / tick_size)
  - Volume cumule par bucket sur session RTH (9:30-16:00 ET)
  - HVN = bucket avec volume >= quantile_70 (top 30%)
  - LVN = bucket avec volume <= quantile_30 (bottom 30%)

Features ajoutees (9) :
  1. dist_session_hvn_above   : distance ticks au HVN le plus proche au-dessus
  2. dist_session_hvn_below   : ditto en-dessous
  3. dist_session_lvn_above   : distance LVN au-dessus
  4. dist_session_lvn_below   : ditto en-dessous
  5. session_hvn_count        : count HVN dans +/- 100 ticks
  6. session_lvn_count        : count LVN dans +/- 100 ticks
  7. lvn_between              : 0/1 LVN entre close et target (target=cur_vah/val ou ATR move)
  8. hvn_between              : 0/1 HVN entre close et target
  9. lvn_confluence_count     : count de LVN clusters (>=3 LVN consecutifs)

Anti-leak : pour bar at T, profile session = trades AVANT T strictement.
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
TRADES_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "trades"

TICK_SIZE = 0.25
HVN_QUANTILE = 0.70
LVN_QUANTILE = 0.30
NEAR_RANGE_TICKS = 100
LVN_CLUSTER_MIN = 3  # >=3 LVN consecutifs = confluence


def load_trades_session(symbol: str, session_date: str) -> pd.DataFrame:
    """Charge trades Databento pour 1 session RTH (9:30-16:00 ET).

    Args:
        symbol : 'ES.c.0' ou 'NQ.c.0'
        session_date : 'YYYY-MM-DD' (date du jour ET)
    """
    sd = pd.Timestamp(session_date)
    base = TRADES_ROOT / f"symbol={symbol}" / f"year={sd.year}" / f"month={sd.month}" / f"day={sd.day}"
    if not base.exists():
        return pd.DataFrame()

    parts = []
    for parquet in sorted(base.glob("data_*.parquet")):
        df = pd.read_parquet(parquet)
        parts.append(df)
    if not parts:
        return pd.DataFrame()

    full = pd.concat(parts, ignore_index=True)
    full["ts_event"] = pd.to_datetime(full["ts_event"], utc=True).dt.tz_convert(None)
    # RTH filter 13:30-20:00 UTC (= 9:30-16:00 ET DST)
    rth_start = pd.Timestamp(session_date) + pd.Timedelta(hours=13, minutes=30)
    rth_end = pd.Timestamp(session_date) + pd.Timedelta(hours=20)
    full = full[(full["ts_event"] >= rth_start) & (full["ts_event"] < rth_end)]
    return full.reset_index(drop=True)


def compute_volume_profile_buckets(df_trades: pd.DataFrame,
                                      tick_size: float = TICK_SIZE) -> pd.Series:
    """Aggregat trades → volume par bucket prix (session ENTIRE).

    Returns : Series indexed bucket_idx (int) → total volume.
    Note : utilise pour SESSION FERMEE uniquement. Pour anti-leak intra-session,
    utiliser compute_rolling_profile_per_minute() à la place.
    """
    if df_trades.empty:
        return pd.Series(dtype=float)
    df_trades = df_trades.copy()
    df_trades["bucket"] = (df_trades["price"] / tick_size).round().astype(int)
    return df_trades.groupby("bucket")["size"].sum()


def compute_rolling_profile_per_minute(df_trades: pd.DataFrame,
                                          tick_size: float = TICK_SIZE) -> pd.DataFrame:
    """FIX review Q1 (anti-leak strict) : profile cumul ROLLING par minute.

    Pour bar at T, profile = somme volume buckets sur trades [open_session, T-1min[
    (strictement avant T pour eviter look-ahead).

    Args:
        df_trades : trades 1 session avec ts_event UTC + price + size

    Returns:
        DataFrame indexed ts_min (datetime), columns = bucket_idx, values = cumul volume.
        Pour bar at T, lookup cumul[floor(T - 1min, '1min')] → profile valide.
    """
    if df_trades.empty:
        return pd.DataFrame()
    df = df_trades.copy()
    df["ts_min"] = df["ts_event"].dt.floor("1min")
    df["bucket"] = (df["price"] / tick_size).round().astype(int)
    # Volume par minute par bucket
    per_min = df.groupby(["ts_min", "bucket"])["size"].sum().unstack(fill_value=0)
    # Cumsum par minute (rolling depuis open session)
    cumul = per_min.cumsum()
    return cumul


def get_profile_at_time(cumul: pd.DataFrame, ts: pd.Timestamp) -> pd.Series:
    """Récupère profile cumul au moment T-1min (anti-leak strict).

    Args:
        cumul : output compute_rolling_profile_per_minute() (index tz-naive)
        ts : timestamp courant (bar at T) — peut etre tz-aware

    Returns:
        Series indexed bucket_idx → volume cumule jusqu'a T-1min strict.
        Empty si T trop tot (avant 1ere minute).
    """
    if cumul.empty:
        return pd.Series(dtype=float)
    # Normalise tz : cumul.index = tz-naive (depuis load_trades_session)
    ts_naive = ts.tz_convert(None) if hasattr(ts, "tz") and ts.tz is not None else ts
    ts_lookback = ts_naive.floor("1min") - pd.Timedelta(minutes=1)
    if ts_lookback < cumul.index.min():
        return pd.Series(dtype=float)
    valid_idx = cumul.index[cumul.index <= ts_lookback]
    if len(valid_idx) == 0:
        return pd.Series(dtype=float)
    last_ts = valid_idx[-1]
    profile = cumul.loc[last_ts]
    return profile[profile > 0]  # Filter buckets sans volume


def identify_hvn_lvn(profile: pd.Series,
                       hvn_q: float = HVN_QUANTILE,
                       lvn_q: float = LVN_QUANTILE,
                       min_buckets: int = 10) -> tuple:
    """HVN = top 30% volume, LVN = bottom 30%.

    FIX review R1 (CRITIQUE 2nd round) : early-session noise guard.
    Profile <10 buckets ou distribution plate (quantile_70 <= quantile_30)
    → HVN/LVN math meaningless → retourner empty (NaN propage).

    Sinon : on aurait HVN et LVN qui overlappent (meme buckets dans 2 ensembles)
    → features bidon sur 09:30-09:40.

    Returns : (hvn_buckets sorted, lvn_buckets sorted)
    """
    if profile.empty or len(profile) < min_buckets:
        return np.array([]), np.array([])
    hvn_thresh = profile.quantile(hvn_q)
    lvn_thresh = profile.quantile(lvn_q)
    if hvn_thresh <= lvn_thresh:
        # Distribution trop plate (rare : tous bucket meme volume)
        return np.array([]), np.array([])
    hvn = np.sort(profile[profile >= hvn_thresh].index.values)
    lvn = np.sort(profile[profile <= lvn_thresh].index.values)
    return hvn, lvn


def count_lvn_confluence(lvn_buckets: np.ndarray,
                            min_consecutive: int = LVN_CLUSTER_MIN,
                            max_gap: int = 2) -> int:
    """Count clusters de LVN >= min_consecutive (gap <= max_gap tolere).

    FIX review code-reviewer Q5 : Steidlmayer "zone vide" tolere 1-2 ticks
    parsemees → max_gap=2 plus realiste que strict gap=1.
    """
    if len(lvn_buckets) < min_consecutive:
        return 0
    sorted_lvn = np.sort(lvn_buckets)
    diffs = np.diff(sorted_lvn)
    cluster_count = 0
    cur_run = 1
    for d in diffs:
        if d <= max_gap:
            cur_run += 1
        else:
            if cur_run >= min_consecutive:
                cluster_count += 1
            cur_run = 1
    if cur_run >= min_consecutive:
        cluster_count += 1
    return cluster_count


def compute_hvn_lvn_features_for_bar(close: float,
                                        target_price: float,
                                        hvn: np.ndarray,
                                        lvn: np.ndarray,
                                        tick_size: float = TICK_SIZE,
                                        near_range: int = NEAR_RANGE_TICKS) -> dict:
    """Calcule les 9 features pour 1 bar donne.

    Args:
        close : prix close du bar
        target_price : prix cible (cur_vah ou ATR move) pour lvn/hvn_between
        hvn / lvn : np.array de bucket_idx
    """
    close_bucket = int(round(close / tick_size))
    # FIX review Q3/Q6 : NaN au lieu de 0 quand info indisponible (pas signal faux)
    feats = {
        "dist_session_hvn_above": np.nan,
        "dist_session_hvn_below": np.nan,
        "dist_session_lvn_above": np.nan,
        "dist_session_lvn_below": np.nan,
        "session_hvn_count": np.nan,
        "session_lvn_count": np.nan,
        "lvn_between": np.nan,
        "hvn_between": np.nan,
        "lvn_confluence_count": np.nan,
    }

    if len(hvn) > 0:
        hvn_above = hvn[hvn > close_bucket]
        hvn_below = hvn[hvn < close_bucket]
        if len(hvn_above) > 0:
            feats["dist_session_hvn_above"] = float(hvn_above[0] - close_bucket)
        if len(hvn_below) > 0:
            feats["dist_session_hvn_below"] = float(close_bucket - hvn_below[-1])
        feats["session_hvn_count"] = int(((hvn >= close_bucket - near_range) &
                                            (hvn <= close_bucket + near_range)).sum())

    if len(lvn) > 0:
        lvn_above = lvn[lvn > close_bucket]
        lvn_below = lvn[lvn < close_bucket]
        if len(lvn_above) > 0:
            feats["dist_session_lvn_above"] = float(lvn_above[0] - close_bucket)
        if len(lvn_below) > 0:
            feats["dist_session_lvn_below"] = float(close_bucket - lvn_below[-1])
        feats["session_lvn_count"] = int(((lvn >= close_bucket - near_range) &
                                            (lvn <= close_bucket + near_range)).sum())
        # FIX review Q4 : confluence LOCALE au close (pas globale session)
        # Variance intra-session = 0 si globale → feature inutile.
        lvn_local = lvn[(lvn >= close_bucket - near_range) &
                          (lvn <= close_bucket + near_range)]
        feats["lvn_confluence_count"] = count_lvn_confluence(lvn_local)

    # FIX review Q6 : NaN si target indisponible (pas 0 = info fausse)
    if not pd.isna(target_price):
        target_bucket = int(round(target_price / tick_size))
        lo, hi = min(close_bucket, target_bucket), max(close_bucket, target_bucket)
        if len(lvn) > 0:
            feats["lvn_between"] = int(((lvn >= lo) & (lvn <= hi)).any())
        if len(hvn) > 0:
            feats["hvn_between"] = int(((hvn >= lo) & (hvn <= hi)).any())

    return feats


def add_hvn_lvn_features(df_v4: pd.DataFrame,
                           symbol: str,
                           target_col: str = "cur_vah") -> pd.DataFrame:
    """Pipeline principal : ajoute 9 HVN/LVN features per bar V4.

    ANTI-LEAK STRICT (Lopez ch.7) — fix 2nd round review :
    Pour bar at T, profile = volume cumul rolling jusqu'a T-1min STRICTEMENT.
    Implementation via compute_rolling_profile_per_minute + get_profile_at_time.

    Cumul aggregat per minute (1 fois par session) → lookup O(log N) par bar.
    Cout : ~7 min sur 7 mois data, ~2.6h sur 15 ans (one-shot).

    Edge cases geres :
      - Bar pre-1ere minute session → empty profile → NaN
      - Bar hors RTH (trades RTH-only filtre) → empty cumul → NaN
      - Profile <10 buckets early-session → identify_hvn_lvn retourne empty
        (fix R1 : evite quantile(0.7)==quantile(0.3) noise)

    Args:
        df_v4 : DataFrame V4 indexed ts_event avec close + target_col
        symbol : 'ES' ou 'NQ' (sans .c.0)
        target_col : col V4 utilisee pour lvn_between/hvn_between target
    """
    out = df_v4.copy()
    if "ts_event" not in out.columns:
        raise ValueError("df_v4 must have ts_event col")

    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True)
    # Date session ET pour grouping
    out["__session_date"] = out["ts_event"].dt.tz_convert("America/New_York").dt.date

    sym_full = f"{symbol}.c.0"
    new_feature_cols = [
        "dist_session_hvn_above", "dist_session_hvn_below",
        "dist_session_lvn_above", "dist_session_lvn_below",
        "session_hvn_count", "session_lvn_count",
        "lvn_between", "hvn_between", "lvn_confluence_count",
    ]
    for c in new_feature_cols:
        out[c] = np.nan

    sessions = sorted(out["__session_date"].unique())
    print(f"[hvn_lvn] Processing {len(sessions)} sessions for {symbol} (rolling anti-leak)...")

    for i, session_date in enumerate(sessions):
        if i % 20 == 0:
            print(f"  [hvn_lvn] Session {i+1}/{len(sessions)}: {session_date}")
        df_trades = load_trades_session(sym_full, str(session_date))
        if df_trades.empty:
            continue

        # FIX review Q1 (anti-leak strict) : rolling intra-session par minute
        cumul = compute_rolling_profile_per_minute(df_trades)
        if cumul.empty:
            continue

        # Bars de la session courante
        mask = out["__session_date"] == session_date
        sub_idx = out.index[mask]
        if len(sub_idx) == 0:
            continue

        # Calc per-bar avec profile rolling at T-1min (strict anti-leak)
        for idx in sub_idx:
            close = out.at[idx, "close"]
            target = out.at[idx, target_col] if target_col in out.columns else np.nan
            if pd.isna(close):
                continue
            ts_bar = out.at[idx, "ts_event"]
            profile_t = get_profile_at_time(cumul, ts_bar)
            if profile_t.empty:
                continue  # Trop tot dans session (premiere minute) → NaN partout

            hvn, lvn = identify_hvn_lvn(profile_t)
            feats = compute_hvn_lvn_features_for_bar(close, target, hvn, lvn)
            for c, v in feats.items():
                out.at[idx, c] = v

    out = out.drop(columns=["__session_date"])
    print(f"[hvn_lvn] +{len(new_feature_cols)} features ajoutees (rolling anti-leak applique)")
    return out


# ═════════════════════════════════════════════════════════════════════
# CLI smoke test
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time
    df = pd.read_parquet(ROOT / "DATA" / "DATASETS" / "ES_dataset_v4.parquet")
    # Sample 5 jours pour smoke rapide
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df["__d"] = df["ts_event"].dt.tz_convert("America/New_York").dt.date
    sessions = sorted(df["__d"].unique())[-5:]  # 5 dernieres sessions
    df_sample = df[df["__d"].isin(sessions)].drop(columns=["__d"]).reset_index(drop=True)
    print(f"[smoke] V4 ES sample 5j : {df_sample.shape}")

    t0 = time.time()
    df_v5 = add_hvn_lvn_features(df_sample, symbol="ES")
    print(f"[smoke] HVN/LVN ajoutees en {time.time()-t0:.1f}s")
    print(f"[smoke] Shape final : {df_v5.shape}")

    new_cols = ["dist_session_hvn_above", "dist_session_lvn_above",
                "session_hvn_count", "session_lvn_count",
                "lvn_between", "hvn_between", "lvn_confluence_count"]
    print("\nStats per nouvelle col :")
    for c in new_cols:
        if c in df_v5.columns:
            s = df_v5[c]
            print(f"  {c:30}: NaN={s.isna().mean():.1%}, "
                  f"unique={s.nunique()}, "
                  f"mean={s.dropna().mean():.2f}")

    # FIX R2 (review 2nd) : diagnostic NaN par heure (verifier cohérence RTH)
    # RTH = 13:30-20:00 UTC → heures 13-19 should be ~0% NaN, autres ~100% NaN.
    df_v5["__h_utc"] = pd.to_datetime(df_v5["ts_event"], utc=True).dt.hour
    print("\nNaN ratio dist_session_hvn_above par heure UTC (RTH=13-19) :")
    nan_per_hour = df_v5.groupby("__h_utc")["dist_session_hvn_above"].apply(lambda s: s.isna().mean())
    for h, r in nan_per_hour.items():
        marker = " ← RTH" if 13 <= h < 20 else ""
        print(f"  hour {h:02d}: NaN={r:.1%}{marker}")
