"""
phase_b_helpers.py — Pre-compute helpers pour Phase B (port modules V1 sur v4)

Calcule les colonnes derivees necessaires aux modules V1 (game_changers, rvol,
intermarket) a partir du dataset v4_enriched (OHLCV Databento + MQ DMP merges).

Inputs : DataFrame v4_enriched + Trades parquet (pour Volume Profile reel).
Outputs : DataFrame enrichi avec :
  - delta_pct, finish_strength, range_size  (rvol)
  - ib_high, ib_low, ib_range, ib_complete, ib_atr  (game_changers + sessions)
  - sess_high, sess_low, dist_sess_high, dist_sess_low  (sessions)
  - open_cash, price_1030  (game_changers open_type)
  - prev_vah, prev_val, prev_vpoc, pdh, pdl  (game_changers open_zone)
  - cur_vah, cur_val, cur_vpoc  (rolling features)
  - cvd_day  (existant cvd_session, alias pour code V1)
  - ts (alias ts_event en ms epoch)

Convention :
  - Tous les timestamps en UTC (Databento natif)
  - Sessions ET via zoneinfo("America/New_York")
  - Ne MODIFIE PAS les colonnes existantes du v4_enriched

Auteur : Phase B Session 1 (2026-04-26)
"""
from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller doit passer tick explicitement
                  # via tick=get_tick_size(symbol). Voir CORE/constants.py.


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SESSION HELPERS (ET timezone)
# ═══════════════════════════════════════════════════════════════════════════════

def add_session_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute date_et, mins_et, session_date_trading, is_cash_session, is_ib_window.

    FIX 4 (review code-reviewer 26/04) : ajout `session_date_trading` qui aligne
    avec convention CME (session lundi = dim 18:00 ET -> lun 17:00 ET).
    Calcul : si mins_et >= 1080 (18:00) ET, session = date_et + 1 jour.
    Permet sess_high/low de couvrir la session entiere (overnight inclus).
    """
    df = df.copy()
    ts_et = df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET) if df["ts_event"].dt.tz is None else df["ts_event"].dt.tz_convert(ET)
    df["date_et"] = ts_et.dt.date
    df["mins_et"] = ts_et.dt.hour * 60 + ts_et.dt.minute
    # Session trading date = date+1 si on est apres 18:00 ET
    df["session_date_trading"] = np.where(
        df["mins_et"] >= 1080,
        (ts_et + pd.Timedelta(days=1)).dt.date,
        df["date_et"],
    )
    # Cash session = 09:30-16:00 ET
    df["is_cash_session"] = ((df["mins_et"] >= 570) & (df["mins_et"] < 960)).astype("int8")
    # IB window = 09:30-10:30 ET
    df["is_ib_window"] = ((df["mins_et"] >= 570) & (df["mins_et"] < 630)).astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INITIAL BALANCE (IB)
# ═══════════════════════════════════════════════════════════════════════════════

def add_ib_features(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """ib_high/low/range/complete/atr/broken + position_pct.

    FIX 27/04 (anti-leak) : ib_high/low broadcast a tout le jour creait un leak
    pour les bars avant 10:30 ET (fin IB). Bars 09:30-10:30 voyaient le futur de
    la fenetre IB. Solution : masker ib_high/low/range a NaN si ib_complete=0
    (avant 10:30 ET). Distances et derives suivent automatiquement le mask.

    Detection bug : SHAP analysis 27/04 -> dist_ib_high_pct #5 SHAP, dist_ib_low_pct #8.
    Voir DOCS/INCIDENT_LOG.md 2026-04-27 20:30 (cascade leak features broadcast).
    """
    df = df.copy()
    if "date_et" not in df.columns:
        df = add_session_metadata(df)

    # IB stats par jour : max(high)/min(low) sur fenetre 09:30-10:30 ET
    ib_rows = df[df["is_ib_window"] == 1]
    ib_agg = ib_rows.groupby("date_et").agg(
        ib_high=("high", "max"),
        ib_low=("low", "min"),
    ).reset_index()
    df = df.merge(ib_agg, on="date_et", how="left")

    # ib_complete : 1 si bar apres 10:30 ET (fin IB window)
    df["ib_complete"] = (df["mins_et"] >= 630).astype("int8")

    # FIX ANTI-LEAK : masker ib_high/low avant 10:30 ET (IB pas encore termine)
    is_pre_ib_close = df["ib_complete"] == 0
    df.loc[is_pre_ib_close, "ib_high"] = np.nan
    df.loc[is_pre_ib_close, "ib_low"] = np.nan

    df["ib_range_ticks"] = ((df["ib_high"] - df["ib_low"]) / tick).round().astype("float64")
    df["ib_range"] = df["ib_high"] - df["ib_low"]
    df["ib_broken_up"] = ((df["ib_complete"] == 1) & (df["high"] > df["ib_high"])).astype("int8")
    df["ib_broken_dn"] = ((df["ib_complete"] == 1) & (df["low"] < df["ib_low"])).astype("int8")
    # Distances IB en pct (NOUVEAU - normalised, ML-usable). NaN avant 10:30 ET (anti-leak).
    df["dist_ib_high_pct"] = ((df["ib_high"] - df["close"]) / df["close"] * 100).astype("float64")
    df["dist_ib_low_pct"] = ((df["close"] - df["ib_low"]) / df["close"] * 100).astype("float64")

    # ib_position_pct (uniquement si ib_complete)
    ib_rng = df["ib_range"].replace(0, np.nan)
    pos = (df["close"] - df["ib_low"]) / ib_rng
    df["ib_position_pct"] = pos.where(df["ib_complete"] == 1)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SESSION HIGH/LOW (cumulative)
# ═══════════════════════════════════════════════════════════════════════════════

def add_session_high_low(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    sess_high/low cumulatif par session trading (CME : dim 18:00 ET -> ven 17:00 ET).
    + cash_high/low (cash session 09:30-16:00 ET seulement)
    + is_new_sess_high/low + is_new_cash_high/low (event detection)
    """
    df = df.copy()
    if "session_date_trading" not in df.columns:
        df = add_session_metadata(df)

    # Full trading session HH/LL
    df["sess_high"] = df.groupby("session_date_trading")["high"].cummax()
    df["sess_low"] = df.groupby("session_date_trading")["low"].cummin()
    df["dist_sess_high_pct"] = ((df["sess_high"] - df["close"]) / df["close"] * 100).astype("float64")
    df["dist_sess_low_pct"] = ((df["close"] - df["sess_low"]) / df["close"] * 100).astype("float64")
    # is_new event : high de cette barre > sess_high de la barre precedente
    prev_sess_high = df.groupby("session_date_trading")["sess_high"].shift(1)
    prev_sess_low = df.groupby("session_date_trading")["sess_low"].shift(1)
    df["is_new_sess_high"] = (df["high"] > prev_sess_high.fillna(-np.inf)).astype("int8")
    df["is_new_sess_low"] = (df["low"] < prev_sess_low.fillna(np.inf)).astype("int8")
    # First bar of session : pas un new high/low
    df.loc[prev_sess_high.isna(), "is_new_sess_high"] = 0
    df.loc[prev_sess_low.isna(), "is_new_sess_low"] = 0

    # Cash session HH/LL (09:30-16:00 ET only)
    cash_mask = df["is_cash_session"] == 1
    df["cash_high"] = df.where(cash_mask).groupby("date_et")["high"].cummax()
    df["cash_low"] = df.where(cash_mask).groupby("date_et")["low"].cummin()
    df["dist_cash_high_pct"] = ((df["cash_high"] - df["close"]) / df["close"] * 100).astype("float64")
    df["dist_cash_low_pct"] = ((df["close"] - df["cash_low"]) / df["close"] * 100).astype("float64")
    prev_cash_high = df.groupby("date_et")["cash_high"].shift(1)
    prev_cash_low = df.groupby("date_et")["cash_low"].shift(1)
    df["is_new_cash_high"] = ((df["high"] > prev_cash_high.fillna(-np.inf)) & cash_mask).astype("int8")
    df["is_new_cash_low"] = ((df["low"] < prev_cash_low.fillna(np.inf)) & cash_mask).astype("int8")
    df.loc[prev_cash_high.isna() | ~cash_mask, "is_new_cash_high"] = 0
    df.loc[prev_cash_low.isna() | ~cash_mask, "is_new_cash_low"] = 0
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 4. OPEN CASH + PRICE 10:30
# ═══════════════════════════════════════════════════════════════════════════════

def add_open_cash_price1030(df: pd.DataFrame) -> pd.DataFrame:
    """open_cash (close de barre 09:30 ET) + price_1030 (close de barre 10:30 ET)."""
    df = df.copy()
    if "date_et" not in df.columns:
        df = add_session_metadata(df)
    # Open cash = close de la barre 09:30 (mins_et == 570)
    open_cash = df[df["mins_et"] == 570].groupby("date_et")["close"].first().rename("open_cash")
    # Price 10:30 = close de la barre 10:30 (mins_et == 630), premiere apres IB complete
    price_1030 = df[df["mins_et"] == 630].groupby("date_et")["close"].first().rename("price_1030")
    df = df.merge(open_cash, on="date_et", how="left")
    df = df.merge(price_1030, on="date_et", how="left")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 5. VOLUME PROFILE (Trades-based)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_volume_profile_dict(volume_by_price: dict, value_area_pct: float = 70.0) -> dict:
    """
    Algo Steidlmayer standard : VPOC + extension VA jusqu'a 70% volume.

    Args:
        volume_by_price: dict[price -> total_volume]
        value_area_pct: % volume cible (70% default)
    Returns:
        dict{vpoc, vah, val, total_vol}
    """
    if not volume_by_price:
        return {"vpoc": np.nan, "vah": np.nan, "val": np.nan, "total_vol": 0}
    total_vol = sum(volume_by_price.values())
    if total_vol <= 0:
        return {"vpoc": np.nan, "vah": np.nan, "val": np.nan, "total_vol": 0}
    target_vol = total_vol * value_area_pct / 100

    prices_sorted = sorted(volume_by_price.keys())
    vpoc = max(volume_by_price, key=volume_by_price.get)
    poc_idx = prices_sorted.index(vpoc)
    cum_vol = volume_by_price[vpoc]
    low_idx = high_idx = poc_idx

    while cum_vol < target_vol and (low_idx > 0 or high_idx < len(prices_sorted) - 1):
        vol_up = volume_by_price[prices_sorted[high_idx + 1]] if high_idx < len(prices_sorted) - 1 else -1
        vol_dn = volume_by_price[prices_sorted[low_idx - 1]] if low_idx > 0 else -1
        if vol_up >= vol_dn:
            high_idx += 1
            cum_vol += vol_up
        else:
            low_idx -= 1
            cum_vol += vol_dn

    return {
        "vpoc": vpoc,
        "vah": prices_sorted[high_idx],
        "val": prices_sorted[low_idx],
        "total_vol": total_vol,
    }


def add_volume_profile_features(
    df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    tick: float = TICK_SIZE,
) -> pd.DataFrame:
    """
    Ajoute cur_vpoc/vah/val (current day) + prev_vpoc/vah/val (yesterday) + pdh/pdl.

    Si trades_df fourni, utilise vrai volume au tick.
    Sinon, fallback : approximation depuis OHLC bar (volume distribue uniformement
    entre low et high de chaque bar).
    """
    df = df.copy()
    if "date_et" not in df.columns:
        df = add_session_metadata(df)

    daily_profiles = {}
    daily_hl = {}

    # FIX 28/04 (Jackson) : grouper par session_date_trading (CME 18:00 ET cutoff)
    # au lieu de date_et (calendar UTC). Sinon les niveaux veille (prev_vpoc, pdh,
    # etc.) CHANGENT pendant 1 session CME (qui chevauche 2 calendar days).
    # Ces niveaux DOIVENT etre constants intraday = lignes horizontales SC,
    # comme les niveaux MenthorQ.
    if trades_df is None or trades_df.empty:
        print("  [WARN] No trades_df : cur/prev VPOC/VAH/VAL = NaN, pdh/pdl from OHLC")
        # pdh/pdl par session_date_trading (sinon split entre 2 calendar days)
        for sess_date, grp in df.groupby("session_date_trading"):
            daily_profiles[sess_date] = {"vpoc": np.nan, "vah": np.nan, "val": np.nan, "total_vol": 0}
            daily_hl[sess_date] = {"pdh": grp["high"].max(), "pdl": grp["low"].min()}
    else:
        # Vraie VAP depuis Trades, groupe par session_date_trading
        trades_df = trades_df.copy()
        trades_df["price_bucket"] = (trades_df["price"] / tick).round() * tick
        # Calculer session_date_trading sur trades (CME 18:00 ET cutoff)
        ts_et = trades_df["ts_event"].dt.tz_convert(ET)
        mins_et = ts_et.dt.hour * 60 + ts_et.dt.minute
        trades_df["session_date_trading"] = np.where(
            mins_et >= 1080,
            (ts_et + pd.Timedelta(days=1)).dt.date,
            ts_et.dt.date,
        )
        for sess_date, grp in trades_df.groupby("session_date_trading"):
            vbp = grp.groupby("price_bucket")["size"].sum().to_dict()
            daily_profiles[sess_date] = compute_volume_profile_dict(vbp)
            daily_hl[sess_date] = {"pdh": grp["price"].max(), "pdl": grp["price"].min()}

    # Map current session stats (utilisation session_date_trading -> constants intraday)
    df["cur_vpoc"] = df["session_date_trading"].map(lambda d: daily_profiles.get(d, {}).get("vpoc", np.nan))
    df["cur_vah"] = df["session_date_trading"].map(lambda d: daily_profiles.get(d, {}).get("vah", np.nan))
    df["cur_val"] = df["session_date_trading"].map(lambda d: daily_profiles.get(d, {}).get("val", np.nan))
    df["cur_pdh"] = df["session_date_trading"].map(lambda d: daily_hl.get(d, {}).get("pdh", np.nan))
    df["cur_pdl"] = df["session_date_trading"].map(lambda d: daily_hl.get(d, {}).get("pdl", np.nan))

    # Previous session stats (shift 1 trading session, pas calendar day)
    sorted_dates = sorted(daily_profiles.keys())
    prev_map = {d: sorted_dates[i - 1] for i, d in enumerate(sorted_dates) if i > 0}
    df["prev_vpoc"] = df["session_date_trading"].map(lambda d: daily_profiles.get(prev_map.get(d), {}).get("vpoc", np.nan))
    df["prev_vah"] = df["session_date_trading"].map(lambda d: daily_profiles.get(prev_map.get(d), {}).get("vah", np.nan))
    df["prev_val"] = df["session_date_trading"].map(lambda d: daily_profiles.get(prev_map.get(d), {}).get("val", np.nan))
    df["pdh"] = df["session_date_trading"].map(lambda d: daily_hl.get(prev_map.get(d), {}).get("pdh", np.nan))
    df["pdl"] = df["session_date_trading"].map(lambda d: daily_hl.get(prev_map.get(d), {}).get("pdl", np.nan))

    # Derivees ML-usable (NOUVEAU - E.1 inside_value_area + poc_migration_dir)
    # inside_value_area : close entre VAL et VAH (current day VP)
    df["inside_value_area"] = (
        (df["close"] >= df["cur_val"]) & (df["close"] <= df["cur_vah"])
    ).astype("int8")
    # poc_migration_dir : signe(cur_vpoc - prev_vpoc) -> +1 vpoc up, -1 vpoc down, 0 unchanged
    df["poc_migration_dir"] = np.sign(df["cur_vpoc"] - df["prev_vpoc"]).fillna(0).astype("int8")
    # Distances en pct (ML-usable)
    df["dist_cur_vpoc_pct"] = ((df["close"] - df["cur_vpoc"]) / df["close"] * 100).astype("float32")
    df["dist_cur_vah_pct"] = ((df["close"] - df["cur_vah"]) / df["close"] * 100).astype("float32")
    df["dist_cur_val_pct"] = ((df["close"] - df["cur_val"]) / df["close"] * 100).astype("float32")
    df["dist_prev_vpoc_pct"] = ((df["close"] - df["prev_vpoc"]) / df["close"] * 100).astype("float32")
    df["dist_prev_vah_pct"] = ((df["close"] - df["prev_vah"]) / df["close"] * 100).astype("float32")
    df["dist_prev_val_pct"] = ((df["close"] - df["prev_val"]) / df["close"] * 100).astype("float32")
    df["dist_pdh_pct"] = ((df["close"] - df["pdh"]) / df["close"] * 100).astype("float32")
    df["dist_pdl_pct"] = ((df["close"] - df["pdl"]) / df["close"] * 100).astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 6. RVOL PRE-COMPUTE (delta_pct, finish_strength, range_size)
# ═══════════════════════════════════════════════════════════════════════════════

def add_rvol_inputs(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Calcule les inputs requis par RvolEngine :
      - delta_pct = delta_bar / volume (entre -1 et 1)
      - finish_strength = (close - open) / range_size * 100 (signed, en %)
      - range_size = high - low (en points)
      - total_vol = alias pour volume (compat code V1)
      - ts = ts_event en ms epoch (compat code V1)
    """
    df = df.copy()
    df["range_size"] = df["high"] - df["low"]
    rng_safe = df["range_size"].replace(0, np.nan)
    df["finish_strength"] = ((df["close"] - df["open"]) / rng_safe * 100).fillna(0)
    vol_safe = df["volume"].replace(0, np.nan)
    df["delta_pct"] = (df["delta_bar"] / vol_safe).fillna(0)
    df["total_vol"] = df["volume"].astype(float)
    # ts en ms epoch (UTC) pour compat code V1 (rvol filter close)
    if df["ts_event"].dt.tz is None:
        df["ts"] = (df["ts_event"].dt.tz_localize("UTC").astype("int64") // 1_000_000).astype("int64")
    else:
        df["ts"] = (df["ts_event"].astype("int64") // 1_000_000).astype("int64")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ATR (Average True Range) sur fenetre IB pour day_type
# ═══════════════════════════════════════════════════════════════════════════════

def add_ib_atr(df: pd.DataFrame, lookback_days: int = 14) -> pd.DataFrame:
    """
    ib_atr = moyenne(ib_range) sur lookback_days jours precedents.
    Utilise par classify_day_type pour normaliser ib_range.
    """
    df = df.copy()
    if "ib_range" not in df.columns:
        raise ValueError("add_ib_features() doit etre appele avant add_ib_atr()")

    # Une valeur ib_range par jour (constante a l'interieur d'un jour)
    daily_ib = df.groupby("date_et")["ib_range"].first().sort_index()
    ib_atr_series = daily_ib.shift(1).rolling(lookback_days, min_periods=3).mean()
    df["ib_atr"] = df["date_et"].map(ib_atr_series)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 8. ALL-IN-ONE PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

PHASE_B_HELPER_COLS = {
    # Session
    "date_et", "mins_et", "session_date_trading", "is_cash_session", "is_ib_window",
    # IB
    "ib_high", "ib_low", "ib_range", "ib_range_ticks", "ib_complete",
    "ib_broken_up", "ib_broken_dn", "ib_position_pct", "ib_atr",
    "dist_ib_high_pct", "dist_ib_low_pct",
    # Session HL trading + cash + new event
    "sess_high", "sess_low", "dist_sess_high", "dist_sess_low",
    "dist_sess_high_pct", "dist_sess_low_pct",
    "is_new_sess_high", "is_new_sess_low",
    "cash_high", "cash_low", "dist_cash_high_pct", "dist_cash_low_pct",
    "is_new_cash_high", "is_new_cash_low",
    # Open cash + 10:30
    "open_cash", "price_1030",
    # Volume Profile
    "cur_vpoc", "cur_vah", "cur_val", "cur_pdh", "cur_pdl",
    "prev_vpoc", "prev_vah", "prev_val", "pdh", "pdl",
    "inside_value_area", "poc_migration_dir",
    "dist_cur_vpoc_pct", "dist_cur_vah_pct", "dist_cur_val_pct",
    "dist_prev_vpoc_pct", "dist_prev_vah_pct", "dist_prev_val_pct",
    "dist_pdh_pct", "dist_pdl_pct",
    # Phase C running (ecrasent cur_* EOD)
    "cur_va_n_buckets", "cur_va_total_vol",
    # RVOL inputs
    "delta_pct", "finish_strength", "range_size", "total_vol", "ts",
}


def add_all_phase_b_helpers(
    df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    tick: float = TICK_SIZE,
    enable_phase_c_running: bool = True,
) -> pd.DataFrame:
    """Pipeline complet Phase B helpers : sessions + IB + VP + sess HL + RVOL inputs + ATR.

    IDEMPOTENT : drop les helpers existants avant recalcul (utile si re-run sur
    un dataset deja partiellement enrichi).

    Phase C (NOUVEAU 2026-04-27) : si enable_phase_c_running=True (default) ET
    trades_df fourni, ecrase cur_vpoc/vah/val EOD broadcast par leur version
    RUNNING (cumulatif depuis debut session), eliminant le lookahead intraday
    documente dans ML_EXCLUDE_FEATURES.
    """
    df = df.copy()
    drop_existing = [c for c in PHASE_B_HELPER_COLS if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)
    df = add_session_metadata(df)
    df = add_ib_features(df, tick=tick)
    df = add_session_high_low(df, tick=tick)
    df = add_open_cash_price1030(df)
    df = add_volume_profile_features(df, trades_df=trades_df, tick=tick)
    # Phase C : VPOC/VA running cumsum (ecrase cur_vpoc/vah/val EOD)
    if enable_phase_c_running and trades_df is not None and not trades_df.empty:
        from value_area_running import apply_value_area_running
        df = apply_value_area_running(df, trades_df=trades_df, tick=tick)
    df = add_rvol_inputs(df, tick=tick)
    df = add_ib_atr(df, lookback_days=14)
    return df
