"""
build_dataset_v4_phase_b.py — Phase B : enrichit v4_enriched avec features V1.

Pipeline :
  1. Load v4_enriched existant (ES + NQ separement)
  2. Pre-compute helpers (CORE/phase_b_helpers.py)
  3. Apply game_changers (open_type, day_type, profile_shape, bias_boost)
  4. Apply rvol (10 features volume relatif)
  5. Apply intermarket (ES vs NQ, 10 features im_*)
  6. Quality validator + write back

Input  : DATA/datasets/v4_enriched/symbol={ES.c.0, NQ.c.0, MGC.c.0}/year=*/month=*/data.parquet
Trades : DATA/databento/GLBX.MDP3/trades/symbol={ES.c.0, NQ.c.0, MGC.v.0}/year=*/...
         (path Databento ticker via get_databento_ticker(symbol) — MGC -> .v.0
         car .c.0 bug rollover monthly, cf Chantier 5bis 10/05/2026)
Output : meme chemin que input (overwrite atomique apres backup)
         Convention pipeline : symbol={SYM}.c.0/ pour TOUS (incl. MGC) pour
         coherence consumers aval (dashboard, backtest, etc.)

Convention :
  - Append columns uniquement (32 features existantes preservees byte-identique)
  - Test non-regression sur 32 cols existantes avant overwrite
  - Backup .backup avant overwrite, supprime apres validation

Usage :
  python -X utf8 CORE/build_dataset_v4_phase_b.py --month 2026-04 --symbols ES NQ
  python -X utf8 CORE/build_dataset_v4_phase_b.py --all-months --symbols ES NQ
  # MGC supporte (Chantier 5 - 10/05/2026) : intermarket auto-skip pour MGC
  python -X utf8 CORE/build_dataset_v4_phase_b.py --month 2026-04 --symbols MGC

Auteur : Phase B Session 1 (2026-04-26)
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

from phase_b_helpers import add_all_phase_b_helpers, PHASE_B_HELPER_COLS, ET, TICK_SIZE
# try/except : 2 conventions sys.path (ROOT/ via -m, vs CORE/ direct CLI)
try:
    from CORE.constants import get_tick_size, get_databento_ticker
except ImportError:
    from constants import get_tick_size, get_databento_ticker
from phase_b_plus_engine import apply_phase_b_plus, PHASE_B_PLUS_GENERATED
from phase_b_plus_plus_engine import apply_phase_b_plus_plus, PHASE_B_PLUS_PLUS_GENERATED
from sessions_swings_engine import apply_sessions_swings, SESSIONS_SWINGS_GENERATED
from footprint_builder import build_footprint_per_bar
from edge_zones_engine import apply_edge_zones, EDGE_ZONES_GENERATED
from rvol import RvolEngine, FEATURES as RVOL_FEATURES
from intermarket_features import IntermarketFeatures
from phase_b_rolling_inputs import apply_rolling_inputs, PHASE_B_ROLLING_INPUTS_COLS
from market_profile_rolling import apply_market_profile_rolling, MARKET_PROFILE_ROLLING_COLS
from phase_d_dalton_levels import apply_phase_d_dalton_levels, PHASE_D_GENERATED
from phase_b_vwap_diff import apply_vwap_diff, VWAP_DIFF_GENERATED
from phase_b_option_c_plus import apply_option_c_plus_transforms, OPTION_C_PLUS_GENERATED
# Phase D Gold features (MGC only) + VIX cross-join (depuis ES JSONL)
from gold_phase_d_features import apply_gold_phase_d, load_ohlcv_databento, GOLD_PHASE_D_FEATURES
from vix_cross_join import add_vix_cross_join
import game_changers as gc

DATASET_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"
TRADES_ROOT = ROOT / "DATA" / "databento" / "GLBX.MDP3" / "trades"

# Toutes les colonnes generees par Phase B + B+ + B+++ (pour identifier les vraies cols originales sur re-run)
GAME_CHANGERS_COLS = {"open_type", "open_zone", "day_type", "open_direction", "open_bias_conf"}
INTERMARKET_PREFIX = "im_"
# Chantier 5bis3 P1 (10/05/2026) : regime_* recalcule en Phase B (Phase A skip car
# day_type/open_type pas encore presents). Ces colonnes peuvent exister dans le
# parquet Phase A (UNKNOWN fallback) et sont overwrite ici legitimement.
REGIME_GENERATED = {
    "regime_mode", "regime_favor", "regime_confidence",
    "regime_trend_votes", "regime_range_votes", "regime_vol", "regime_actionable",
    "ib_formed_bool",  # derive depuis ib_range_ticks (FIX R1.3)
}
PHASE_B_GENERATED = (PHASE_B_HELPER_COLS | GAME_CHANGERS_COLS | set(RVOL_FEATURES)
                    | PHASE_B_PLUS_GENERATED | PHASE_B_PLUS_PLUS_GENERATED
                    | EDGE_ZONES_GENERATED | SESSIONS_SWINGS_GENERATED
                    | PHASE_B_ROLLING_INPUTS_COLS | MARKET_PROFILE_ROLLING_COLS
                    | PHASE_D_GENERATED | VWAP_DIFF_GENERATED | OPTION_C_PLUS_GENERATED
                    | REGIME_GENERATED)


# ═══════════════════════════════════════════════════════════════════════════════
# I/O
# ═══════════════════════════════════════════════════════════════════════════════

def load_v4_partition(symbol: str, year: int, month: int) -> pd.DataFrame:
    """Lit 1 partition v4_enriched.

    Note 10/05 (Chantier 5bis) : v4_enriched output toujours en `MGC.c.0` (convention
    pipeline interne, pas le ticker Databento). Le DBN_ROOT switch (MGC.v.0) ne
    s'applique qu'aux INPUTS Databento (load_trades_for_month).
    """
    path = DATASET_ROOT / f"symbol={symbol}.c.0" / f"year={year}" / f"month={month:02d}" / "data.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if df["ts_event"].dt.tz is None:
        df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
    return df


def load_trades_for_month(symbol: str, year: int, month: int) -> pd.DataFrame:
    """Charge les Trades pour 1 mois (toutes partitions day) avec side (aggressor).

    FIX BUG CRITIQUE 10/05/2026 (Chantier 5bis) : path utilise get_databento_ticker
    pour MGC -> "MGC.v.0" (au lieu de hardcode "MGC.c.0"). Avant fix : trades_df
    vide pour MGC -> 207 features mortes en cascade (Volume Profile, big orders,
    clusters, BN absorption, edge zones, regime engine, game changers).
    """
    db_ticker = get_databento_ticker(symbol)
    pattern = str(TRADES_ROOT / f"symbol={db_ticker}" / f"year={year}" / f"month={month}" / "day=*" / "*.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    dfs = []
    for f in files:
        d = pd.read_parquet(f, columns=["ts_event", "price", "size", "side"])
        if d["ts_event"].dt.tz is None:
            d["ts_event"] = d["ts_event"].dt.tz_localize("UTC")
        dfs.append(d)
    return pd.concat(dfs, ignore_index=True)


def load_trades_for_window(symbol: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
    """Charge les Trades pour une fenetre [start_ts, end_ts) au lieu du mois entier.

    Refacto Phase 1b (13/05/2026) : reduit IO 5x sur cycle incremental window 3j.
    Iterer sur les jours UTC touches par la fenetre seulement (au lieu du mois entier),
    puis filter strict sur le range timestamps.

    Args:
        symbol : ES, NQ, MGC (format court, sans .c.0)
        start_ts : timestamp UTC inclusif
        end_ts : timestamp UTC exclusif

    Returns:
        DataFrame trades sur [start_ts, end_ts) avec colonnes [ts_event, price, size, side]
        DataFrame vide si aucun trade dispo.
    """
    db_ticker = get_databento_ticker(symbol)
    # Normaliser tz UTC (defense input non-tz-aware)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    # Iterer sur les jours UTC dans la fenetre (inclus partial day si fenetre traverse minuit)
    days = pd.date_range(start_ts.normalize(), end_ts.normalize(), freq="D", tz="UTC")
    dfs = []
    for day_ts in days:
        y, m, d = day_ts.year, day_ts.month, day_ts.day
        pattern = str(TRADES_ROOT / f"symbol={db_ticker}" / f"year={y}" / f"month={m}" / f"day={d}" / "*.parquet")
        for f in glob.glob(pattern):
            df = pd.read_parquet(f, columns=["ts_event", "price", "size", "side"])
            if df["ts_event"].dt.tz is None:
                df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
            dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    df_all = pd.concat(dfs, ignore_index=True)
    # Filter strict sur [start_ts, end_ts)
    mask = (df_all["ts_event"] >= start_ts) & (df_all["ts_event"] < end_ts)
    return df_all[mask].reset_index(drop=True)


def write_v4_atomic(df: pd.DataFrame, symbol: str, year: int, month: int, original_cols: set):
    """
    Sauvegarde atomique avec test non-regression sur cols originales.
    1. Backup current file -> .backup
    2. Verify byte-identique on original_cols
    3. Write new -> .tmp -> rename
    4. Cleanup .backup si OK
    """
    out_path = DATASET_ROOT / f"symbol={symbol}.c.0" / f"year={year}" / f"month={month:02d}" / "data.parquet"
    backup = out_path.with_suffix(".parquet.backup")
    tmp = out_path.with_suffix(".parquet.tmp")

    # Drop helper-only cols (pas pour persistance)
    drop_helpers = {"date_et", "mins_et", "is_cash_session", "is_ib_window",
                    "ts", "price"}
    df_out = df.drop(columns=[c for c in drop_helpers if c in df.columns], errors="ignore")

    # Test non-regression (tolere tz_localize sur datetime, sinon byte-identique)
    df_orig = pd.read_parquet(out_path)
    for col in original_cols:
        if col not in df_out.columns:
            raise RuntimeError(f"Original column {col!r} disappeared in Phase B output")
        s_orig = df_orig[col]
        s_new = df_out[col]
        # Datetime cols : normaliser tz avant compare (UTC)
        if pd.api.types.is_datetime64_any_dtype(s_orig):
            o = s_orig.dt.tz_localize("UTC") if s_orig.dt.tz is None else s_orig.dt.tz_convert("UTC")
            n = s_new.dt.tz_localize("UTC") if s_new.dt.tz is None else s_new.dt.tz_convert("UTC")
            if not o.equals(n):
                raise RuntimeError(f"Original datetime column {col!r} modified in Phase B output")
            continue
        # Numeric cols
        if pd.api.types.is_numeric_dtype(s_orig):
            if not np.allclose(s_orig.fillna(-9e18).values,
                               s_new.fillna(-9e18).values,
                               equal_nan=True, rtol=1e-9, atol=1e-12):
                raise RuntimeError(f"Original numeric column {col!r} modified in Phase B output")
            continue
        # Object/string/bool : equals strict
        if not s_orig.equals(s_new):
            raise RuntimeError(f"Original column {col!r} modified in Phase B output")

    # Backup + write tmp + rename
    shutil.copy(out_path, backup)
    df_out.to_parquet(tmp, compression="zstd", index=False)
    os.replace(tmp, out_path)
    backup.unlink()


# ═══════════════════════════════════════════════════════════════════════════════
# GAME CHANGERS WRAPPER
# ═══════════════════════════════════════════════════════════════════════════════

def apply_game_changers(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """
    Applique game_changers par jour : open_type, day_type, profile_shape +
    derivees (open_direction, open_bias_conf).

    Inputs requis (pre-compute via phase_b_helpers) :
      open_cash, prev_vah, prev_val, prev_vpoc, pdh, pdl,
      ib_high, ib_low, ib_atr, ib_range, ib_complete,
      sess_high, sess_low, price_1030, close

    FIX 10/05/2026 (Chantier 5bis2) : avant le fix, la fonction utilisait
    grp.iloc[0] (1ere barre du jour, 18:00 ET J-1 = Asia open) ou ib_high/low
    sont NaN (masked anti-leak avant fin IB). Resultat : open_type/day_type
    toujours UNKNOWN/NORM_VAR. Cascade : open_direction/open_bias_conf const=0.
    Fix : prendre la 1ere row POST-IB (mins_et >= us_start + 60) ou tous les
    inputs sont valides. Per-symbole : ES/NQ ib_close=10:30, MGC ib_close=09:30.
    """
    # Bounds per-symbole pour identifier la fin de la fenetre IB
    try:
        from CORE.constants import get_session_boundaries
    except ImportError:
        from constants import get_session_boundaries
    bounds = get_session_boundaries(symbol)
    ib_close_min = bounds["us_start"] + 60  # ES 10:30 ET, MGC 09:30 ET

    df = df.copy()
    out_open_type = []
    out_open_zone = []
    out_day_type = []
    out_open_direction = []
    out_open_bias_conf = []

    # Group par date (1 classification par jour, broadcast sur barres)
    for date, grp in df.groupby("date_et", sort=False):
        # FIX 10/05 : prendre row POST-IB (ib_high/low valides)
        # Avant : first = grp.iloc[0] = 18:00 ET J-1 = ib_high/low NaN
        # Apres : 1ere row apres ib_close_min (09:30 MGC, 10:30 ES/NQ)
        post_ib = grp[grp["mins_et"] >= ib_close_min]
        if post_ib.empty:
            # Pas de bar post-IB ce jour (weekend, holiday, partial) - fallback UNKNOWN
            n_bars = len(grp)
            out_open_type.extend([0] * n_bars)
            out_open_zone.extend([0] * n_bars)
            out_day_type.extend([2] * n_bars)  # NORM_VAR default
            out_open_direction.extend([0] * n_bars)
            out_open_bias_conf.extend([0.0] * n_bars)
            continue
        first = post_ib.iloc[0]
        open_cash = first["open_cash"]
        prev_vah = first["prev_vah"]
        prev_val = first["prev_val"]
        prev_vpoc = first["prev_vpoc"]
        pdh = first["pdh"]
        pdl = first["pdl"]
        ib_high = first["ib_high"]
        ib_low = first["ib_low"]
        ib_atr = first["ib_atr"]
        price_1030 = first["price_1030"]
        sess_high = grp["sess_high"].iloc[-1]  # final session high
        sess_low = grp["sess_low"].iloc[-1]
        close_eod = grp["close"].iloc[-1]

        # Classifications
        ot = gc.classify_open_type(open_cash, prev_vah, prev_val, ib_high, ib_low, price_1030)
        oz = gc.classify_open_zone(open_cash, prev_vah, prev_val, prev_vpoc, pdh, pdl)
        dt = gc.classify_day_type(ib_atr, sess_high, sess_low, close_eod, ib_high, ib_low)

        n_bars = len(grp)
        out_open_type.extend([int(ot)] * n_bars)
        out_open_zone.extend([int(oz)] * n_bars)
        out_day_type.extend([int(dt)] * n_bars)
        out_open_direction.extend([int(gc.direction(ot))] * n_bars)
        out_open_bias_conf.extend([float(gc.confidence(ot))] * n_bars)

    df["open_type"] = pd.Series(out_open_type, dtype="int8", index=df.index)
    df["open_zone"] = pd.Series(out_open_zone, dtype="int8", index=df.index)
    df["day_type"] = pd.Series(out_day_type, dtype="int8", index=df.index)
    df["open_direction"] = pd.Series(out_open_direction, dtype="int8", index=df.index)
    df["open_bias_conf"] = pd.Series(out_open_bias_conf, dtype="float32", index=df.index)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# RVOL WRAPPER
# ═══════════════════════════════════════════════════════════════════════════════

def apply_rvol(df: pd.DataFrame) -> pd.DataFrame:
    """Applique RvolEngine. Inputs requis : total_vol, delta_pct, finish_strength, ts."""
    engine = RvolEngine(filter_close=True)
    return engine.compute(df)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PROCESSING (1 partition)
# ═══════════════════════════════════════════════════════════════════════════════

def process_partition(symbol: str, year: int, month: int, write: bool = True) -> dict:
    """Pipeline complet sur 1 (symbol, year, month)."""
    t0 = time.time()
    print(f"\n[{symbol} {year}-{month:02d}] Start")

    df_orig = load_v4_partition(symbol, year, month)
    if df_orig.empty:
        print(f"  [SKIP] No data")
        return {"status": "SKIP", "reason": "no_data"}

    n_bars = len(df_orig)
    n_cols_orig = len(df_orig.columns)
    # Vraies colonnes originales (exclure Phase B already-generated cols si re-run)
    original_cols = set(df_orig.columns) - PHASE_B_GENERATED - {c for c in df_orig.columns if c.startswith(INTERMARKET_PREFIX)}
    print(f"  Loaded {n_bars} bars x {n_cols_orig} cols ({len(original_cols)} non-PhaseB)")

    # Trades pour Volume Profile
    trades_df = load_trades_for_month(symbol, year, month)
    print(f"  Loaded {len(trades_df):,} trades")

    # Pipeline (10/05/2026 : tick + bounds per-symbole — supporte MGC=0.10 + 08:30 RTH)
    tick = get_tick_size(symbol)
    try:
        from CORE.constants import get_session_boundaries
    except ImportError:
        from constants import get_session_boundaries
    bounds = get_session_boundaries(symbol)
    df = add_all_phase_b_helpers(
        df_orig, trades_df=trades_df if not trades_df.empty else None,
        tick=tick, bounds=bounds,
    )
    print(f"  After helpers: {df.shape[1]} cols (+{df.shape[1]-n_cols_orig})")

    df = apply_game_changers(df, symbol=symbol)
    print(f"  After game_changers: {df.shape[1]} cols (+5)")

    df = apply_rvol(df)
    n_rvol = sum(1 for c in df.columns if c.startswith("rvol"))
    print(f"  After rvol: {df.shape[1]} cols ({n_rvol} rvol_*)")

    # Phase B+ (OHLC-only : Color/Long/VWAP/OVN/Opens/News)
    df = apply_phase_b_plus(df, symbol=symbol)
    n_bp = sum(1 for c in df.columns if c in PHASE_B_PLUS_GENERATED)
    print(f"  After Phase B+: {df.shape[1]} cols ({n_bp} B+ features)")

    # Phase B+++ MVP (Trades agreges : big orders + clusters + aggressor)
    df = apply_phase_b_plus_plus(df, trades_df, symbol=symbol, tick=tick)
    n_bpp = sum(1 for c in df.columns if c in PHASE_B_PLUS_PLUS_GENERATED)
    print(f"  After Phase B+++: {df.shape[1]} cols ({n_bpp} B+++ features)")

    # Bloc 3 #1 Edge Zones (footprint cellule + extension lines manager)
    # 11/05 J3 FIX BUG GOLD : passer tick=tick au footprint_builder.
    # Avant ce fix, MGC (tick=0.10) utilisait default tick=0.25 -> bucketize
    # incorrect -> cellules sparse -> 0% fire rate edge_zones (4 features mortes).
    # ES/NQ inchanges car tick=0.25 = default.
    if not trades_df.empty:
        footprint = build_footprint_per_bar(trades_df, df["ts_event"], tick=tick)
        df = apply_edge_zones(df, footprint, symbol=symbol, tick=tick)
    else:
        # No trades : initialise Edge Zones cols a 0
        for col in EDGE_ZONES_GENERATED:
            if col.startswith("dist_"):
                df[col] = np.nan
            else:
                df[col] = 0
    n_ez = sum(1 for c in df.columns if c in EDGE_ZONES_GENERATED)
    print(f"  After Edge Zones: {df.shape[1]} cols ({n_ez} edge features)")

    # Bloc 3 #8-10 Sessions + Swings + ICT bonus
    df = apply_sessions_swings(df, symbol=symbol)
    n_ss = sum(1 for c in df.columns if c in SESSIONS_SWINGS_GENERATED)
    print(f"  After Sessions+Swings: {df.shape[1]} cols ({n_ss} sessions/swings features)")

    # Phase 1 + Phase 3 (rolling inputs V4-natif + market profile rolling)
    df = apply_rolling_inputs(df, tick=tick)
    n_ri = sum(1 for c in df.columns if c in PHASE_B_ROLLING_INPUTS_COLS)
    print(f"  After Rolling Inputs: {df.shape[1]} cols ({n_ri} rolling inputs)")
    df = apply_market_profile_rolling(df, tick=tick)
    n_mpr = sum(1 for c in df.columns if c in MARKET_PROFILE_ROLLING_COLS)
    print(f"  After Market Profile Rolling: {df.shape[1]} cols ({n_mpr} ctx_* features)")

    # Phase D : Dalton levels (pVWAP + Naked POC + Single Prints + Excess)
    df = apply_phase_d_dalton_levels(df, trades_df=trades_df, tick=tick)
    n_pd = sum(1 for c in df.columns if c in PHASE_D_GENERATED)
    print(f"  After Phase D Dalton: {df.shape[1]} cols ({n_pd} dalton features)")

    # === Audit ULTRATHINK Option C+ (2026-04-27) ===
    # VWAP differentiels (5 features remplacant 10 raw vwap_w/m_*)
    df = apply_vwap_diff(df)
    n_vd = sum(1 for c in df.columns if c in VWAP_DIFF_GENERATED)
    print(f"  After VWAP diff (Option C+): {df.shape[1]} cols ({n_vd} vwap_diff features)")

    # Option C+ : after-hours fillna + 3 nouvelles features feature-engineer
    df = apply_option_c_plus_transforms(df)
    n_ocp = sum(1 for c in df.columns if c in OPTION_C_PLUS_GENERATED)
    print(f"  After Option C+ transforms: {df.shape[1]} cols ({n_ocp} new features)")

    # === Chantier 5bis3 (10/05/2026) — Regime engine en Phase B ===
    # Phase A (build_dataset_v4_dmp_databento) skip systematiquement le regime
    # car day_type/open_type/profile_shape/trend_day_probability n'existent
    # PAS en Phase A (calcules par apply_game_changers en Phase B).
    # Bug ES/NQ depuis Chantier 1 : regime_* features ABSENTES dans tous les
    # parquets v4_enriched ES/NQ historiques.
    # Fix : recalculer regime ICI apres game_changers/Phase B+/Phase D.
    if "open_type" in df.columns and "day_type" in df.columns:
        try:
            from regime_engine import compute_regime_dict
        except ImportError:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent))
            from regime_engine import compute_regime_dict

        # FIX R1.3 Phase A : derive ib_formed_bool depuis ib_range_ticks (avant drop)
        if "ib_range_ticks" in df.columns:
            df["ib_formed_bool"] = (df["ib_range_ticks"].fillna(0) > 0).astype(int)

        regime_records = []
        for _, row in df.iterrows():
            bar = row.to_dict()
            regime_records.append(compute_regime_dict(bar))
        df_regime = pd.DataFrame(regime_records, index=df.index)
        # Drop colonnes existantes (Phase A UNKNOWN fallback) avant concat
        for c in df_regime.columns:
            if c in df.columns:
                df = df.drop(columns=[c])
        df = pd.concat([df, df_regime], axis=1)
        actionable_pct = df["regime_actionable"].mean() * 100 if "regime_actionable" in df.columns else 0
        print(f"  After Regime engine: {df.shape[1]} cols (actionable {actionable_pct:.1f}%)")

    # ─────────────────────────────────────────────────────────────────────────
    # MGC-only enrichments : VIX cross-join + Gold Phase D features (12/05/2026)
    # ─────────────────────────────────────────────────────────────────────────
    # VIX : absent du parquet MGC car pipeline Databento (pas DMP JSONL Sierra).
    # Cross-join depuis ES JSONL (vix_level/vix_regime communs CBOE).
    # Gold Phase D : 4 features intermarket + session (6E, ZN, ZB, sessions UTC/ET).
    if symbol == "MGC":
        # 1. VIX cross-join (depuis ES JSONL vix_level/vix_regime)
        n_before_vix = df.shape[1]
        df = add_vix_cross_join(df)
        n_vix_added = df.shape[1] - n_before_vix
        print(f"  After VIX cross-join: {df.shape[1]} cols (+{n_vix_added} VIX features)")

        # 2. Gold Phase D : 4 features intermarket + session
        try:
            ts_min = pd.to_datetime(df["ts_event"]).min()
            ts_max = pd.to_datetime(df["ts_event"]).max()
            # Marge 60+ bars pour rolling windows (real_yields proxy, dxy_corr)
            start_load = (ts_min - pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=None)
            end_load = (ts_max + pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=None)

            df_6e = load_ohlcv_databento("6E.c.0", pd.Timestamp(start_load), pd.Timestamp(end_load))
            df_zn = load_ohlcv_databento("ZN.c.0", pd.Timestamp(start_load), pd.Timestamp(end_load))
            df_zb = load_ohlcv_databento("ZB.c.0", pd.Timestamp(start_load), pd.Timestamp(end_load))

            print(f"  Gold Phase D loaders : 6E={len(df_6e)} bars, ZN={len(df_zn)}, ZB={len(df_zb)}")

            df = apply_gold_phase_d(df, df_6e=df_6e, df_zn=df_zn, df_zb=df_zb)
            n_gpd = sum(1 for c in df.columns if c in GOLD_PHASE_D_FEATURES)
            print(f"  After Gold Phase D: {df.shape[1]} cols ({n_gpd} gold features)")
        except Exception as e:
            print(f"  [WARN] Gold Phase D failed: {e}. Setting features to NaN.")
            for col in GOLD_PHASE_D_FEATURES:
                if col not in df.columns:
                    df[col] = np.nan

    # Sanity stats
    if "open_type" in df.columns:
        ot_dist = df.groupby("date_et")["open_type"].first().value_counts().to_dict()
        print(f"  open_type distribution: {ot_dist}")
    if "rvol_buy" in df.columns:
        n_rvol_buy = int(df["rvol_buy"].sum())
        n_rvol_sell = int(df["rvol_sell"].sum())
        print(f"  rvol_buy={n_rvol_buy} | rvol_sell={n_rvol_sell} | rvol_extreme={int(df['rvol_extreme'].sum())}")

    if write:
        write_v4_atomic(df, symbol, year, month, original_cols)
        print(f"  [WRITE] OK")

    elapsed = time.time() - t0
    print(f"[{symbol} {year}-{month:02d}] Done in {elapsed:.1f}s")
    return {
        "status": "OK",
        "symbol": symbol, "year": year, "month": month,
        "n_bars": n_bars,
        "n_cols_orig": n_cols_orig,
        "n_cols_final": len(df.columns),
        "elapsed_s": elapsed,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# INTERMARKET (cross ES + NQ apres process individuel)
# ═══════════════════════════════════════════════════════════════════════════════

def apply_intermarket_pair(year: int, month: int, write: bool = True) -> dict:
    """
    Apres que ES et NQ ont ete enrichis individuellement, applique intermarket
    qui necessite les 2 dataframes synchronises.
    """
    t0 = time.time()
    print(f"\n[INTERMARKET {year}-{month:02d}] Start")

    df_es = load_v4_partition("ES", year, month)
    df_nq = load_v4_partition("NQ", year, month)

    if df_es.empty or df_nq.empty:
        print("  [SKIP] ES or NQ missing")
        return {"status": "SKIP"}

    # FIX 2 : capturer original_cols AVANT toute mutation (idempotence)
    intermarket_temps = {"ts", "price", "delta_day", "total_vol",
                         "dist_sess_high", "dist_sess_low"}  # alias V1 ticks
    original_cols_es = (set(df_es.columns) - intermarket_temps
                        - {c for c in df_es.columns if c.startswith(INTERMARKET_PREFIX)})
    original_cols_nq = (set(df_nq.columns) - intermarket_temps
                        - {c for c in df_nq.columns if c.startswith(INTERMARKET_PREFIX)})

    # Verifier que les inputs intermarket sont presents (apres Phase B individuel)
    required = {"open_type", "open_bias_conf", "open_direction", "delta_bar"}
    miss_es = required - set(df_es.columns)
    miss_nq = required - set(df_nq.columns)
    if miss_es or miss_nq:
        print(f"  [SKIP] Missing inputs: ES={miss_es}, NQ={miss_nq}")
        return {"status": "SKIP", "reason": "missing_inputs"}

    # IntermarketFeatures attend 'ts' (ms epoch) + 'price' + types reguliers (pas Int nullable)
    for d in (df_es, df_nq):
        if "ts" not in d.columns:
            d["ts"] = (d["ts_event"].astype("int64") // 1_000_000).astype("int64")
        if "price" not in d.columns:
            d["price"] = d["close"]
        if "delta_day" not in d.columns and "cvd_session" in d.columns:
            d["delta_day"] = d["cvd_session"]
        if "total_vol" not in d.columns and "volume" in d.columns:
            d["total_vol"] = d["volume"].astype(float)
        # FIX 4+8 side-effect : intermarket V1 attend dist_sess_high/low (en ticks).
        # Recreer alias depuis dist_sess_high_pct (nouveau nom apres fix).
        # NOTE 10/05/2026 : apply_intermarket_pair() est appele UNIQUEMENT pour
        # paire ES/NQ (df_es + df_nq lignes 353-354), pas MGC. Donc TICK_SIZE=0.25
        # constant est correct pour ces 2 symboles. Si etendu a MGC dans le futur
        # (Chantier 5 - intermarket), remplacer TICK_SIZE par get_tick_size(sym)
        # avec sym detecte par d[ticker_col] ou via dispatcher per-pair.
        if "dist_sess_high" not in d.columns and "dist_sess_high_pct" in d.columns:
            # Reconvertir pct -> ticks (approximatif via close * pct / 100 / tick)
            d["dist_sess_high"] = (d["dist_sess_high_pct"] / 100 * d["close"] / TICK_SIZE).astype("float64")
        if "dist_sess_low" not in d.columns and "dist_sess_low_pct" in d.columns:
            d["dist_sess_low"] = (d["dist_sess_low_pct"] / 100 * d["close"] / TICK_SIZE).astype("float64")
        # Cast Int* nullable -> float pour eviter "boolean value of NA is ambiguous"
        for col in ("dist_sess_high", "dist_sess_low", "ib_range_ticks"):
            if col in d.columns and pd.api.types.is_extension_array_dtype(d[col]):
                d[col] = d[col].astype("float64")
        # Cast Int8 (open_type, etc.) en int64 simple
        for col in ("open_type", "open_zone", "day_type", "open_direction",
                    "ib_complete", "ib_broken_up", "ib_broken_dn"):
            if col in d.columns and pd.api.types.is_extension_array_dtype(d[col]):
                d[col] = d[col].astype("int64")

    im = IntermarketFeatures(short=3, mid=5, long=10)
    df_es_enriched = im.compute(df_es, df_nq, target="ES")
    df_nq_enriched = im.compute(df_nq, df_es, target="NQ")

    new_im_cols = sorted([c for c in df_es_enriched.columns if c.startswith("im_")])
    print(f"  Generated {len(new_im_cols)} im_* features: {new_im_cols}")

    if write:
        # original_cols_es/nq deja capture AVANT mutations (FIX 2)
        # Drop helper temps avant write (write_v4_atomic les drop aussi mais explicit ici)
        for d in (df_es_enriched, df_nq_enriched):
            d.drop(columns=[c for c in intermarket_temps if c in d.columns],
                   inplace=True, errors="ignore")
        write_v4_atomic(df_es_enriched, "ES", year, month, original_cols_es)
        write_v4_atomic(df_nq_enriched, "NQ", year, month, original_cols_nq)
        print(f"  [WRITE] OK ES + NQ")

    elapsed = time.time() - t0
    print(f"[INTERMARKET {year}-{month:02d}] Done in {elapsed:.1f}s")
    return {"status": "OK", "n_im_cols": len(new_im_cols), "elapsed_s": elapsed}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (1 mois specifique)")
    ap.add_argument("--all-months", action="store_true", help="Tous les mois disponibles")
    ap.add_argument("--symbols", nargs="+", default=["ES", "NQ"])
    ap.add_argument("--no-write", action="store_true", help="Dry-run, ne sauvegarde pas")
    ap.add_argument("--no-intermarket", action="store_true", help="Skip intermarket")
    args = ap.parse_args()

    write = not args.no_write

    # Determine months
    months = []
    if args.month:
        y, m = args.month.split("-")
        months = [(int(y), int(m))]
    elif args.all_months:
        # Detect all (year, month) partitions sous v4_enriched/symbol=ES.c.0/
        for ydir in (DATASET_ROOT / "symbol=ES.c.0").glob("year=*"):
            year = int(ydir.name.split("=")[1])
            for mdir in ydir.glob("month=*"):
                month = int(mdir.name.split("=")[1])
                months.append((year, month))
        months.sort()
    else:
        ap.error("Specify --month YYYY-MM or --all-months")

    print(f"Phase B processing : {len(months)} months × {len(args.symbols)} symbols")

    results = []
    for year, month in months:
        for sym in args.symbols:
            r = process_partition(sym, year, month, write=write)
            results.append(r)

        # Intermarket = paire ES↔NQ uniquement (im_* features cross instrument).
        # MGC n'est PAS concerne : pas de pair naturel cross-instrument dans
        # le pipeline V1. Decision design Chantier 5 (10/05/2026) : skip total
        # pour MGC. Si paire MGC↔DXY/SI un jour, refactor module dedie en V2.
        if not args.no_intermarket and "ES" in args.symbols and "NQ" in args.symbols:
            apply_intermarket_pair(year, month, write=write)
        elif "MGC" in args.symbols:
            print(f"  [INFO] MGC traite sans intermarket (skip Chantier 5 - pas de pair naturel)")

    print(f"\n=== SUMMARY ({len(results)} runs) ===")
    ok = [r for r in results if r["status"] == "OK"]
    skip = [r for r in results if r["status"] == "SKIP"]
    print(f"  OK   : {len(ok)}")
    print(f"  SKIP : {len(skip)}")
    if ok:
        cols_added = ok[0]["n_cols_final"] - ok[0]["n_cols_orig"]
        total_s = sum(r["elapsed_s"] for r in ok)
        print(f"  Cols added/partition: {cols_added}")
        print(f"  Total elapsed: {total_s:.1f}s")


if __name__ == "__main__":
    main()
