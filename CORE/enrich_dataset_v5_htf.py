"""
enrich_dataset_v5_htf.py — V5 dataset enrichi multi-TF (5m + 15m + 1h)

Created : 2026-05-02 00:50 UTC
Author : Plan V3 SANS DETTE — Jackson + ULTRATHINK code-reviewer

Sources :
  - 1m natif Databento ohlcv-1m DBN files (15 ans deja telecharges)
  - 1h natif Databento ohlcv-1h DBN files (15 ans en cours de download)
  - 5m / 15m via RESAMPLE depuis 1m natif + anti-lookahead strict

Anti-lookahead strict (rule code-reviewer ULTRATHINK Q3) :
  Pour bar 1m at T :
    - Bar 5m label "10:00" inclut bars 1m de 10:00-10:04 → LEAK si utilise pour bar 1m at 10:00
    - Solution : prendre bar 5m FERMEE strictement AVANT T = bar 5m label floor(T-1min, "5min")
    - Ex bar 1m at 10:03 → bar 5m fermee = label "09:55" (couvre 09:55-09:59)
    - Ex bar 1m at 10:00 → bar 5m fermee = label "09:55" (la 10:00 vient de commencer)

Architecture :
  load_raw_1m_databento(symbol, start, end) : charge bars 1m depuis ohlcv-1m DBN
  resample_to_htf(df_1m, freq) : resample avec label='left', closed='left'
  add_htf_columns_with_lag(df_1m, df_htf, freq, prefix) : join asof anti-lookahead
  compute_htf_features(df_htf) : ema, rsi, momentum, atr, etc.

Output : DataFrame 1m enrichi avec cols suffixees _5m, _15m, _1h.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DBN_OHLCV_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1m"
DBN_OHLCV_1H_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "ohlcv-1h"

# Gap weekend threshold (vendredi 17:00 ET → dimanche 18:00 ET = ~49h)
GAP_RESET_HOURS = 12  # tout gap > 12h = reset HTF rolling features

# FIX BUG #2 (code-reviewer 02/05) : pd.Timedelta("1h") peut crasher selon version pandas
# Mapping explicite OBLIGATOIRE pour eviter crash silencieux sur freq="1h"
FREQ_TO_DELTA = {
    "5min": pd.Timedelta(minutes=5),
    "15min": pd.Timedelta(minutes=15),
    "1h":    pd.Timedelta(hours=1),
    "1H":    pd.Timedelta(hours=1),
    "4h":    pd.Timedelta(hours=4),
    "1d":    pd.Timedelta(days=1),
}


# ═════════════════════════════════════════════════════════════════════
# LOAD RAW BARS DEPUIS DATABENTO DBN
# ═════════════════════════════════════════════════════════════════════

def load_raw_1m_databento(symbol: str = "NQ.c.0",
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> pd.DataFrame:
    """
    Charge bars 1m natifs Databento depuis fichiers DBN compresses.

    Args:
        symbol : "ES.c.0" ou "NQ.c.0"
        start_date : YYYY-MM-DD (inclusive). None = tout depuis 2011.
        end_date : YYYY-MM-DD (inclusive). None = jusqu'a aujourd'hui.

    Returns:
        DataFrame avec ts_event (UTC, naive), open, high, low, close, volume.
    """
    try:
        import databento as db
    except ImportError:
        raise ImportError("databento package required. pip install databento")

    base = DBN_OHLCV_ROOT / f"symbol={symbol}"
    if not base.exists():
        raise FileNotFoundError(f"Databento ohlcv-1m base introuvable : {base}")

    bars = []
    for dbn_path in sorted(base.rglob("data.dbn.zst")):
        try:
            store = db.DBNStore.from_file(str(dbn_path))
            df = store.to_df()
            if not df.empty:
                bars.append(df[["open", "high", "low", "close", "volume"]].reset_index())
        except Exception as e:
            print(f"  ! Skip {dbn_path}: {e}")

    if not bars:
        return pd.DataFrame()

    full = pd.concat(bars, ignore_index=True)
    full["ts_event"] = pd.to_datetime(full["ts_event"], utc=True).dt.tz_convert(None)
    full = full.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)

    if start_date:
        full = full[full["ts_event"] >= pd.Timestamp(start_date)].reset_index(drop=True)
    if end_date:
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)  # inclusive
        full = full[full["ts_event"] < end_ts].reset_index(drop=True)

    return full


def load_raw_1h_databento(symbol: str = "NQ.c.0") -> pd.DataFrame:
    """Charge bars 1h natifs Databento.

    FIX 02/05 : pipeline backfill convertit DBN → parquet (data_0.parquet),
    pas data.dbn.zst. On lit directement les parquet (plus rapide aussi).
    """
    base = DBN_OHLCV_1H_ROOT / f"symbol={symbol}"
    if not base.exists():
        return pd.DataFrame()

    bars = []
    # Try parquet first (post-backfill format)
    for parquet_path in sorted(base.rglob("data_0.parquet")):
        try:
            df = pd.read_parquet(parquet_path)
            if not df.empty:
                cols_keep = [c for c in ("ts_event", "open", "high", "low", "close", "volume") if c in df.columns]
                bars.append(df[cols_keep])
        except Exception:
            continue

    # Fallback : DBN raw
    if not bars:
        try:
            import databento as db
            for dbn_path in sorted(base.rglob("data.dbn.zst")):
                try:
                    store = db.DBNStore.from_file(str(dbn_path))
                    df = store.to_df()
                    if not df.empty:
                        bars.append(df[["open", "high", "low", "close", "volume"]].reset_index())
                except Exception:
                    pass
        except ImportError:
            pass

    if not bars:
        return pd.DataFrame()

    full = pd.concat(bars, ignore_index=True)
    if "ts_event" in full.columns:
        full["ts_event"] = pd.to_datetime(full["ts_event"], utc=True).dt.tz_convert(None)
        full = full.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)
    return full


# ═════════════════════════════════════════════════════════════════════
# RESAMPLE ANTI-LOOKAHEAD STRICT
# ═════════════════════════════════════════════════════════════════════

def resample_to_htf(df_1m: pd.DataFrame, freq: str = "5min") -> pd.DataFrame:
    """
    Resample 1m → HTF (5min, 15min, 1h, etc.) avec convention RIGOUREUSE.

    Convention pandas resample:
      label='left'  : bar at 10:00 covers 10:00-10:04 (LABEL = start of bar)
      closed='left' : interval is [10:00, 10:05) = include 10:00, exclude 10:05

    Returns DataFrame indexed by ts_event_htf (label 'left' = start of bar).
    """
    if df_1m.empty:
        return pd.DataFrame()

    df = df_1m.set_index("ts_event")
    df_htf = df.resample(freq, label="left", closed="left").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(subset=["close"])

    df_htf = df_htf.reset_index()
    return df_htf


def add_htf_columns_with_lag(df_1m: pd.DataFrame,
                                df_htf: pd.DataFrame,
                                freq: str,
                                suffix: str) -> pd.DataFrame:
    """
    Joint cols HTF sur df_1m via merge_asof avec ANTI-LOOKAHEAD STRICT.

    Pour bar 1m at T :
      - Bar HTF label "10:00" couvre 10:00-10:04 → LEAK si utilisee pour bar 1m at T in [10:00, 10:05)
      - Solution : prendre bar HTF avec ts_event_htf <= floor(T, freq) - freq_delta

    Implementation :
      1. Pour chaque bar HTF, calculer ts_event_htf_close = ts_event_htf + freq (= start of next HTF bar)
      2. merge_asof avec direction='backward' sur ts_event_htf_close
         → bar 1m at T trouve la bar HTF dont ts_event_htf_close <= T (= bar HTF fermee strictement avant T)

    Args:
        df_1m : bars 1m avec ts_event
        df_htf : bars HTF avec ts_event (label 'left')
        freq : "5min", "15min", "1h"
        suffix : "_5m", "_15m", "_1h" — appended to col names

    Returns:
        df_1m enrichi avec cols open{suffix}, high{suffix}, low{suffix}, close{suffix}, volume{suffix}
    """
    if df_1m.empty or df_htf.empty:
        return df_1m

    df_1m = df_1m.sort_values("ts_event").reset_index(drop=True)
    df_htf = df_htf.sort_values("ts_event").reset_index(drop=True)

    # FIX BUG #2 (code-reviewer 02/05) : mapping explicite freq → Timedelta
    # pd.Timedelta("1h") peut crasher selon version pandas (>=2.2 deprecated 'h')
    if freq not in FREQ_TO_DELTA:
        raise ValueError(f"freq '{freq}' non supporte. Valides : {list(FREQ_TO_DELTA.keys())}")
    freq_delta = FREQ_TO_DELTA[freq]

    # Calcul ts_event_htf_close = end of HTF bar (= start of next bar)
    df_htf_lagged = df_htf.copy()
    df_htf_lagged["ts_event_htf_close"] = df_htf_lagged["ts_event"] + freq_delta

    # Renomme cols avec suffix (sauf ts_event_htf_close qui sera drop)
    feature_cols = [c for c in df_htf_lagged.columns
                    if c not in ("ts_event", "ts_event_htf_close")]
    rename_map = {c: c + suffix for c in feature_cols}
    df_htf_lagged = df_htf_lagged.rename(columns=rename_map)
    # Drop original ts_event (on garde ts_event_htf_close pour merge)
    df_htf_lagged = df_htf_lagged.drop(columns=["ts_event"])

    # FIX BUG #1 CRITIQUE (code-reviewer 02/05) : allow_exact_matches=False
    # Bar 1m at T=10:00:00 ne doit PAS recuperer bar HTF dont ts_event_htf_close = 10:00:00
    # (la cloture exacte = info pas physiquement disponible au demarrage de bar 1m at 10:00).
    # Avec False : bar 1m at T cherche bar HTF avec ts_event_htf_close STRICTEMENT < T.
    # Conservateur de 1 freq mais defendable en live (anti-leak strict).
    merged = pd.merge_asof(
        df_1m,
        df_htf_lagged,
        left_on="ts_event",
        right_on="ts_event_htf_close",
        direction="backward",
        allow_exact_matches=False,  # FIX BUG #1 — anti-leak strict
    )

    # Drop merge key
    merged = merged.drop(columns=["ts_event_htf_close"])
    return merged


# ═════════════════════════════════════════════════════════════════════
# FEATURES HTF (EMA, RSI, MOMENTUM, ATR, etc.)
# ═════════════════════════════════════════════════════════════════════

def compute_htf_features(df_htf: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule features sur bars HTF (avant le join sur 1m).

    Features (CAT2 reproduit per TF) :
      - ema_20, ema_slope_3, ema_slope_5
      - rsi_14
      - momentum_3bars, momentum_10bars
      - atr_14
      - range_pct
      - bar_color (+1 bull, -1 bear, 0 doji)
      - bar_body_pct
      - vol_z (volume z-score 20 bars)
      - pos_in_range_20

    Le gap weekend handling :
      Si gap > GAP_RESET_HOURS, RESET les rolling features (EMA, RSI) pour eviter slope artificielle
    """
    if df_htf.empty:
        return df_htf

    df = df_htf.copy()

    # Detection gap session (reset rolling features)
    # FIX RESERVE #1 (code-reviewer 02/05) : reset par session_id sur TOUTES les
    # rolling features, pas seulement EMA. Sinon RSI/ATR/momentum/vol_z/pos_in_range
    # cassent sur gap weekend (jusqu'a 14h ATR pollue post-gap sur 1h TF).
    df["gap_h"] = df["ts_event"].diff().dt.total_seconds() / 3600
    df["session_break"] = (df["gap_h"] > GAP_RESET_HOURS).fillna(False)
    df["session_id"] = df["session_break"].cumsum()

    # Bar color (intra-bar uniquement, pas de reset necessaire)
    df["bar_color"] = np.sign(df["close"] - df["open"]).astype("int8")

    # Bar body pct (intra-bar)
    body = (df["close"] - df["open"]).abs()
    range_ = (df["high"] - df["low"]).replace(0, np.nan)
    df["bar_body_pct"] = (body / range_).fillna(0)

    # Range pct (intra-bar)
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]

    # ─── ROLLING FEATURES par session_id (RESET sur gap > 12h) ────

    def _per_session(group_col: str, fn):
        """Apply fn par session_id sans casser l'index global."""
        return df.groupby("session_id")[group_col].transform(fn)

    # EMA 20 (causal exponential, reset par session)
    df["ema_20"] = _per_session("close", lambda s: s.ewm(span=20, adjust=False).mean())
    df["ema_slope_3"] = df.groupby("session_id")["ema_20"].transform(lambda s: s.diff(3))
    df["ema_slope_5"] = df.groupby("session_id")["ema_20"].transform(lambda s: s.diff(5))

    # RSI 14 (per session — sinon delta cross gap = saut artificiel)
    def _rsi_14(close_series):
        delta = close_series.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(50)

    df["rsi_14"] = df.groupby("session_id", group_keys=False)["close"].transform(_rsi_14)

    # Momentum (per session — sinon shift cross gap)
    df["momentum_3bars"] = df.groupby("session_id")["close"].transform(lambda s: s - s.shift(3))
    df["momentum_10bars"] = df.groupby("session_id")["close"].transform(lambda s: s - s.shift(10))

    # ATR 14 — approche masque NaN sur session_break (plus simple que groupby.apply)
    # Pour bar = 1ere de session, close.shift(1) recupere close session precedente (gap)
    # Solution : forcer TR=NaN sur premiere bar post-gap → propage NaN sur 14 bars rolling
    c_prev = df.groupby("session_id")["close"].shift(1)  # shift PER SESSION → NaN sur 1ere bar
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - c_prev).abs()
    tr3 = (df["low"] - c_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr_14"] = tr.groupby(df["session_id"]).transform(lambda s: s.rolling(14).mean())

    # Vol z-score 20 (per session)
    def _vol_z(vol_series):
        m = vol_series.rolling(20).mean()
        s = vol_series.rolling(20).std()
        return (vol_series - m) / s.replace(0, np.nan)

    df["vol_z"] = df.groupby("session_id", group_keys=False)["volume"].transform(_vol_z)

    # Position in range 20 (per session — high_20/low_20 reset par session)
    df["high_20_sess"] = df.groupby("session_id")["high"].transform(lambda s: s.rolling(20).max())
    df["low_20_sess"] = df.groupby("session_id")["low"].transform(lambda s: s.rolling(20).min())
    df["pos_in_range_20"] = (df["close"] - df["low_20_sess"]) / (df["high_20_sess"] - df["low_20_sess"]).replace(0, np.nan)
    df = df.drop(columns=["high_20_sess", "low_20_sess"])

    # Cleanup helper cols
    df = df.drop(columns=["gap_h", "session_break", "session_id"])

    return df


# ═════════════════════════════════════════════════════════════════════
# TRAPPED TRADERS — agregats HTF (rolling sum sur fenetre TF)
# ═════════════════════════════════════════════════════════════════════
# Recommandation agent feature-engineer : ne pas recalc concept HTF
# (microstructure 1m-only), agreger via rolling sum/mean pour exposer
# contexte HTF aux modeles.
#
# 6 features × 3 TF (5m, 15m, 1h) = +18 cols

# FIX agent ULTRATHINK 02/05 00:50 :
# - Strategy par feature : sum pour fires binaires, max pour counters persistants
# - Reset session_id obligatoire (rolling traverse weekend gap = leak cross-session)
TRAPPED_FEATURES_AGG = {
    "bn_trapped_buyers_raw":              "sum",  # binary fire 0/1
    "bn_trapped_sellers_raw":             "sum",
    "bn_trapped_buyers_at_resistance":    "sum",
    "bn_trapped_sellers_at_support":      "sum",
    "n_trapped_buyers_zones_active":      "max",  # counter persistant — sum=non-sense
    "n_trapped_sellers_zones_active":     "max",
}

# Window bars 1m equivalent par TF
TRAPPED_HTF_WINDOWS = {"_5m": 5, "_15m": 15, "_1h": 60}


def add_trapped_htf_aggregates(df_1m_enriched: pd.DataFrame,
                                  gap_reset_hours: float = GAP_RESET_HOURS) -> pd.DataFrame:
    """Ajoute agregats HTF features trapped traders 1m, avec session reset.

    FIX agent ULTRATHINK 02/05 :
    - Reset par session_id (gap weekend > 12h) → evite leak cross-session
    - Strategy agg : sum pour fires binaires, max pour counters persistants
    - min_periods=1 conserve (sparse features)

    Output : 6 features × 3 TF = +18 cols.
    """
    if df_1m_enriched.empty:
        return df_1m_enriched
    df = df_1m_enriched.copy()

    # Detection sessions pour reset (idem compute_htf_features)
    df["_gap_h"] = df["ts_event"].diff().dt.total_seconds() / 3600
    df["_session_id"] = (df["_gap_h"] > gap_reset_hours).fillna(False).cumsum()

    for feat, agg_strategy in TRAPPED_FEATURES_AGG.items():
        if feat not in df.columns:
            continue
        for suffix, window in TRAPPED_HTF_WINDOWS.items():
            new_col = f"{feat}{suffix}"
            if agg_strategy == "sum":
                df[new_col] = df.groupby("_session_id")[feat].transform(
                    lambda s: s.rolling(window=window, min_periods=1).sum()
                )
            elif agg_strategy == "max":
                df[new_col] = df.groupby("_session_id")[feat].transform(
                    lambda s: s.rolling(window=window, min_periods=1).max()
                )

    df = df.drop(columns=["_gap_h", "_session_id"])
    return df


# ═════════════════════════════════════════════════════════════════════
# MENTHORQ RECALCUL × 3 TF (51 cols)
# ═════════════════════════════════════════════════════════════════════
# Pour chaque distance MQ existante 1m, recalculer depuis close TF.
# Logique : dist_mq_X_pct_TF = (mq_X_level - close_TF) / close_TF * 100
#
# Si close_TF est NaN (boundary, no HTF history) → dist NaN aussi (propage).

# 17 features MQ × 3 TF = +51 cols
MQ_FEATURES_TO_RECALC = {
    # Distances ticks (basees sur level absolu - close)
    "dist_1d_min_ticks":   {"level_col": "_dummy_1d_min", "type": "ticks"},
    "dist_1d_max_ticks":   {"level_col": "_dummy_1d_max", "type": "ticks"},
    "dist_gex_nearest_up": {"level_col": "_dummy_gex_up", "type": "ticks"},
    "dist_gex_nearest_dn": {"level_col": "_dummy_gex_dn", "type": "ticks"},
    "dist_blind_nearest_up": {"level_col": "_dummy_blind_up", "type": "ticks"},
    "dist_blind_nearest_dn": {"level_col": "_dummy_blind_dn", "type": "ticks"},
    "dist_vix_gex_nearest_up": {"level_col": "_dummy_vix_up", "type": "ticks"},
    "dist_vix_gex_nearest_dn": {"level_col": "_dummy_vix_dn", "type": "ticks"},
    # Distances pct (basees sur level absolu - close pct)
    "dist_mq_call_pct":   {"level_col": "mq_call",   "type": "pct"},
    "dist_mq_put_pct":    {"level_col": "mq_put",    "type": "pct"},
    "dist_mq_hvl_pct":    {"level_col": "mq_hvl",    "type": "pct"},
    "dist_mq_call_0dte_pct": {"level_col": "mq_call_0dte", "type": "pct"},
    "dist_mq_put_0dte_pct":  {"level_col": "mq_put_0dte",  "type": "pct"},
    "dist_mq_hvl_0dte_pct":  {"level_col": "mq_hvl_0dte",  "type": "pct"},
    # Booleans (recalc sign)
    "bool_above_mq_call":  {"level_col": "mq_call",  "type": "bool_above"},
    "bool_above_mq_hvl":   {"level_col": "mq_hvl",   "type": "bool_above"},
    "bool_gex_flip_zone":  {"level_col": "_gex_flip_zone", "type": "passthrough"},
}


def add_mq_levels_per_tf(df_1m_enriched: pd.DataFrame,
                          tf_suffixes: list = None) -> pd.DataFrame:
    """Recalcule features MQ par TF en utilisant close_TF natif.

    Pour chaque feature MQ existante (1m natif), si on a close_TF dans le df :
      dist_X_pct_TF = (level - close_TF) / close_TF * 100
      bool_above_X_TF = 1 if close_TF > level else 0

    Si level_col absent du df (1d_min, gex_up, etc.) : derive level depuis
    dist 1m + close 1m (level = close_1m + dist_1m * TICK_SIZE).
    """
    if df_1m_enriched.empty:
        return df_1m_enriched
    df = df_1m_enriched.copy()
    if tf_suffixes is None:
        tf_suffixes = ["_5m", "_15m", "_1h"]

    TICK_SIZE = 0.25  # ES + NQ futures

    for feat, cfg in MQ_FEATURES_TO_RECALC.items():
        if feat not in df.columns:
            continue
        level_col = cfg["level_col"]
        feat_type = cfg["type"]

        # Recover level absolu (si pas dispo dans df)
        if level_col.startswith("_dummy") or level_col.startswith("_gex"):
            # Derive level = close_1m + dist_1m * TICK_SIZE (ticks features)
            if feat_type == "ticks":
                level_series = df["close"] + df[feat] * TICK_SIZE
            else:
                level_series = df["close"]  # passthrough
        else:
            if level_col not in df.columns:
                continue  # level absent → skip recalc TF (garde feat 1m)
            level_series = df[level_col]

        for suffix in tf_suffixes:
            close_tf_col = f"close{suffix}"
            if close_tf_col not in df.columns:
                continue
            close_tf = df[close_tf_col]

            new_col = f"{feat}{suffix}"
            if feat_type == "ticks":
                df[new_col] = (level_series - close_tf) / TICK_SIZE
            elif feat_type == "pct":
                df[new_col] = (level_series - close_tf) / close_tf.replace(0, np.nan) * 100
            elif feat_type == "bool_above":
                df[new_col] = (close_tf > level_series).astype("Int8")
            elif feat_type == "passthrough":
                # bool_gex_flip_zone : valeur 1m broadcastee
                df[new_col] = df[feat]

    return df


# ═════════════════════════════════════════════════════════════════════
# CAT4 CROSS-INSTRUMENT × 3 TF (30 cols)
# ═════════════════════════════════════════════════════════════════════
# Reuse module CORE/intermarket_features.py existing.
# Pour chaque TF (5m, 15m, 1h), resample ES + NQ + recompute IntermarketFeatures.

def add_im_features_per_tf(df_es_v5: pd.DataFrame, df_nq_v5: pd.DataFrame,
                              tf_suffixes: list = None) -> tuple:
    """Recalcule im_* cross-instrument par TF.

    Args:
        df_es_v5 : dataset V5 ES enrichi (avec close_5m, close_15m, close_1h)
        df_nq_v5 : dataset V5 NQ enrichi
        tf_suffixes : ["_5m", "_15m", "_1h"]

    Returns:
        (df_es_with_im_per_tf, df_nq_with_im_per_tf)
    """
    if tf_suffixes is None:
        tf_suffixes = ["_5m", "_15m", "_1h"]
    try:
        from intermarket_features import IntermarketFeatures
    except ImportError as e:
        print(f"[add_im_features_per_tf] ImportError IntermarketFeatures: {e}")
        return df_es_v5, df_nq_v5

    df_es = df_es_v5.copy()
    df_nq = df_nq_v5.copy()
    im_calculator = IntermarketFeatures()  # FIX 02/05: instance pas classmethod

    for suffix in tf_suffixes:
        close_es_col = f"close{suffix}"
        close_nq_col = f"close{suffix}"
        if close_es_col not in df_es.columns or close_nq_col not in df_nq.columns:
            print(f"[add_im_features_per_tf] {suffix}: cols absentes (skip)")
            continue

        # Build mini-DF par TF avec close + volume agreges TF
        es_tf = df_es[["ts_event", close_es_col, f"volume{suffix}"]].rename(
            columns={close_es_col: "close", f"volume{suffix}": "volume"}
        ).dropna()
        nq_tf = df_nq[["ts_event", close_nq_col, f"volume{suffix}"]].rename(
            columns={close_nq_col: "close", f"volume{suffix}": "volume"}
        ).dropna()

        if es_tf.empty or nq_tf.empty:
            print(f"[add_im_features_per_tf] {suffix}: TF empty after dropna (skip)")
            continue

        try:
            # FIX 02/05 (smoke test silent failure) : signature correcte
            # IntermarketFeatures().compute(df_target=NQ, df_other=ES, target="NQ")
            im_features = im_calculator.compute(nq_tf, es_tf, target="NQ")
        except Exception as e:
            print(f"[add_im_features_per_tf] {suffix} compute CRASH: {type(e).__name__}: {e}")
            continue

        # Suffix les im_* cols et merge sur df_nq (cross instrument vu cote NQ)
        if isinstance(im_features, pd.DataFrame):
            for col in im_features.columns:
                if col.startswith("im_"):
                    new_col = f"{col}{suffix}"
                    # Map via ts_event
                    df_nq[new_col] = df_nq["ts_event"].map(
                        im_features.set_index("ts_event")[col].to_dict()
                    )
                    df_es[new_col] = df_es["ts_event"].map(
                        im_features.set_index("ts_event")[col].to_dict()
                    )

    return df_es, df_nq


def enrich_1m_with_all_htf(df_1m: pd.DataFrame,
                              df_5m: Optional[pd.DataFrame] = None,
                              df_15m: Optional[pd.DataFrame] = None,
                              df_1h: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """
    Pipeline complet : 1m + HTF features (5m, 15m, 1h) avec anti-lookahead.

    Args:
        df_1m : bars 1m natives Databento
        df_5m : bars 5m (resample depuis 1m si None)
        df_15m : bars 15m (idem)
        df_1h : bars 1h natives ou None (resample depuis 1m)

    Returns:
        df_1m enrichi avec ~70 cols HTF additionnelles (15-20 features × 3 TF)
    """
    if df_1m.empty:
        return df_1m

    # Resample 5m + 15m si non fournis
    if df_5m is None:
        df_5m = resample_to_htf(df_1m, "5min")
    if df_15m is None:
        df_15m = resample_to_htf(df_1m, "15min")
    if df_1h is None:
        df_1h = resample_to_htf(df_1m, "1h")

    # Calcul features HTF
    df_5m_feat = compute_htf_features(df_5m)
    df_15m_feat = compute_htf_features(df_15m)
    df_1h_feat = compute_htf_features(df_1h)

    # Join anti-lookahead
    df = df_1m.copy()
    df = add_htf_columns_with_lag(df, df_5m_feat, "5min", "_5m")
    df = add_htf_columns_with_lag(df, df_15m_feat, "15min", "_15m")
    df = add_htf_columns_with_lag(df, df_1h_feat, "1h", "_1h")

    return df


# ═════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ.c.0")
    parser.add_argument("--start", default="2026-04-01")
    parser.add_argument("--end", default="2026-04-30")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    print(f"Loading 1m bars : {args.symbol} [{args.start} → {args.end}]...")
    df_1m = load_raw_1m_databento(args.symbol, args.start, args.end)
    print(f"  {len(df_1m)} bars 1m loaded")

    print(f"Loading 1h native bars (if available)...")
    df_1h = load_raw_1h_databento(args.symbol)
    if not df_1h.empty:
        # FIX BUG #3 (code-reviewer 02/05) : end_ts + 1 day pour inclure derniere journee
        # Bug original : <= pd.Timestamp(args.end) inclut SEULEMENT bar at midnight, perd 1 jour entier
        end_ts_filt = pd.Timestamp(args.end) + pd.Timedelta(days=1)
        df_1h_filtered = df_1h[(df_1h["ts_event"] >= pd.Timestamp(args.start)) &
                                 (df_1h["ts_event"] < end_ts_filt)].reset_index(drop=True)
        print(f"  {len(df_1h_filtered)} bars 1h native (filtered to range)")
    else:
        print(f"  No 1h native available, will resample from 1m")
        df_1h_filtered = None

    print(f"Enriching with HTF features (5m + 15m + 1h)...")
    df_enriched = enrich_1m_with_all_htf(df_1m, df_1h=df_1h_filtered)
    print(f"  Result : {df_enriched.shape}")
    print(f"  Cols suffixed _5m : {len([c for c in df_enriched.columns if c.endswith('_5m')])}")
    print(f"  Cols suffixed _15m : {len([c for c in df_enriched.columns if c.endswith('_15m')])}")
    print(f"  Cols suffixed _1h : {len([c for c in df_enriched.columns if c.endswith('_1h')])}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        df_enriched.to_parquet(out_path, index=False)
        print(f"  Saved : {out_path}")
