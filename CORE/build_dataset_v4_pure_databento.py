"""
build_dataset_v4_pure_databento.py — Dataset V4 PURE Databento (zero DMP raw Sierra).

CONTEXTE :
  Decision Option C Jackson 19/05/2026 : Python = source canonique 100% Databento.
  Abandon parite DMP historique. Sierra Chart reste UNIQUEMENT pour execution DTC.

CONVENTIONS CANONIQUES (cf DOCS/DATA_SOURCES_V5.md) :
  - open_cash      = OHLCV.open bar mins_et==us_start (FIX #1 phase_b_helpers.py:773)
  - day_type       = progressif intra-session via sess_high/low running cumsum (FIX #2)
  - range_pos      = recalcule sur cur_val/cur_vah Python running (FIX #4)
  - sess_range_atr = ATR Wilder daily 14j (phase_b_v6_complete v0.3)
  - cvd_day_dir    = sign(cumsum delta_bar Trades Databento)
  - vix_level/regime = via vix_lite_reader (DATA/vix_levels/ Sierra replay 8 mois)
  - MenthorQ levels  = API JSON files scrapes (DATA/MENTHORQ/*.json)

SOURCES (zero DMP Sierra raw) :
  - Databento OHLCV-1m + Trades (DATA/databento/GLBX.MDP3/...)
  - MenthorQ API JSON (DATA/MENTHORQ/*_menthorq_complete.json)
  - VIX historique (DATA/vix_levels/year=*/month=*/day=*/vix.jsonl)

OUTPUT :
  DATA/datasets/v4_pure/symbol={sym}.c.0/year=YYYY/month=MM/data.parquet

Architecture :
  build_for_symbol_pure() orchestre un pipeline lineaire reutilisant les
  orchestrants Python autonomes existants. Zero duplication, zero dette.

  1. Load Databento OHLCV-1m + Trades (DRY : reuse load_ohlcv + aggregate_trades_1min)
  2. Load VIX historique + enrich (vix_lite_reader)
  3. Load MenthorQ JSON + asof distances (load_mq_levels + attach_mq_distances)
  4. Merge OHLCV + Trades + VIX
  5. ATR Wilder daily 14j (compute_atr) + detect_roll
  6. apply_all_engines (build_dataset_v4_phase_b orchestrant complet) :
     - helpers Phase B (sessions, IB, VPOC running, open_cash FIX #1, ...)
     - game_changers (open_type, day_type progressif FIX #2, profile_shape)
     - rvol + Phase B+ (Color/Long/VWAP) + Phase B+++ (big orders, clusters)
     - Edge Zones (footprint cells)
     - Sessions + Swings + ICT
     - Rolling inputs + Market Profile Rolling (ctx_*)
     - Phase D Dalton (Naked POC, Single Prints, pVWAP)
     - VWAP diff + Option C+ transforms
     - Regime engine (10 votes)
  7. apply_v6_complete (range_pos FIX #4 + sess_range_atr + vwap_w_side + vwap_triple_align + cvd_day_dir)
  8. CVD session reset (CME 22:00 UTC)
  9. PCT-normalized distances + OHLC derived
 10. Sort + dedup + partition Hive year=YYYY/month=MM

Usage :
  python -X utf8 CORE/build_dataset_v4_pure_databento.py --symbols ES NQ --test-day 2026-05-01
  python -X utf8 CORE/build_dataset_v4_pure_databento.py --symbols ES NQ --start 2025-10-01 --end 2026-05-19

Version : 1.0 — 2026-05-19 — Refactor PRO sans duplication
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

try:
    from CORE.constants import get_tick_size, get_databento_ticker
except ImportError:
    from constants import get_tick_size, get_databento_ticker

# Loaders + helpers reutilises depuis builder mixed (sans load_dmp_jsonl)
from build_dataset_v4_dmp_databento import (
    load_ohlcv,
    aggregate_trades_1min,
    add_session_cvd,
    detect_roll,
    compute_atr,
    add_pct_normalized_distances,
    add_ohlc_derived_features,
)

# Orchestrants Phase B/B+/Phase D/Regime (autonomes Python, zero DMP raw)
# load_trades_for_window : Trades tick-par-tick (price/size/side) requis par
#                          apply_all_engines pour Volume Profile, footprint, VPOC running.
from build_dataset_v4_phase_b import apply_all_engines, load_trades_for_window
from phase_b_v6_complete import apply_v6_complete
# Option C extras 19/05/2026 : profile_shape + trend_day_probability Python canoniques
# (formules portees C++ DMP_Transform.h:1310-1326 + DMP_ProfileShape.h:452-480).
from phase_b_v6_extras import apply_v6_extras

# Sources VIX + MenthorQ
# FIX R1 audit code-reviewer 19/05 : utiliser load_menthorq_json (124 fichiers JSON
# couvrent dec 2025+) au lieu de load_mq_levels (Hive deploy 28/04 only -> 95% trou).
from load_mq_levels import attach_mq_distances
from load_menthorq_json import load_menthorq_json
from vix_lite_reader import load_vix_lite_jsonl, enrich_vix_lite

# Session boundaries per-symbole
try:
    from CORE.constants import get_session_boundaries
except ImportError:
    from constants import get_session_boundaries

OUT_ROOT_PURE = ROOT / "DATA" / "datasets" / "v4_pure"


def build_for_symbol_pure(symbol: str, start: date, end: date) -> pd.DataFrame:
    """Pipeline V4 PURE Databento pour un symbole.

    Voir docstring module pour orchestration complete (10 etapes).

    Args:
        symbol : "ES" | "NQ" | "MGC" (sans suffixe .c.0)
        start, end : range inclusif

    Returns:
        DataFrame V4 pure Databento prete pour write_partitioned_pure().
        Empty si pas de OHLCV pour le range.
    """
    t0 = time.time()
    print(f"\n{'='*70}")
    print(f" V4 PURE DATABENTO — {symbol} [{start} -> {end}]")
    print(f"{'='*70}")

    tick = get_tick_size(symbol)
    bounds = get_session_boundaries(symbol)

    # ─── 1. OHLCV Databento ─────────────────────────────────────────
    print("  [1/10] Load OHLCV Databento...")
    ohlcv = load_ohlcv(symbol, start, end)
    print(f"        {len(ohlcv)} bars")
    if ohlcv.empty:
        print(f"  [SKIP] No OHLCV for {symbol}")
        return pd.DataFrame()

    # ─── 2. Trades Databento : tick-par-tick (pour apply_all_engines)
    #       + agrege 1-min (pour merge OHLCV) ─────────────────────────
    print("  [2/10] Load Trades Databento : tick-par-tick + agrege 1-min...")
    trades_1min = aggregate_trades_1min(symbol, start, end)
    print(f"        {len(trades_1min)} 1-min bars trades agreges")
    # Trades tick-par-tick requis par add_volume_profile_features / footprint / VPOC running
    # Convention BUILDER : ts_event tz-NAIVE partout (alignee builder mixed).
    # add_session_metadata gere tz_localize("UTC").tz_convert(ET) en interne.
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    trades_tick = load_trades_for_window(symbol, start_ts, end_ts)
    if not trades_tick.empty:
        trades_tick["ts_event"] = pd.to_datetime(trades_tick["ts_event"])
        if isinstance(trades_tick["ts_event"].dtype, pd.DatetimeTZDtype):
            trades_tick["ts_event"] = trades_tick["ts_event"].dt.tz_localize(None)
    print(f"        {len(trades_tick)} ticks Trades raw")

    # ─── 3. VIX historique (Sierra replay 8 mois) ───────────────────
    print("  [3/10] Load VIX historique (DATA/vix_levels/)...")
    try:
        vix_df = load_vix_lite_jsonl(start, end)
        print(f"        {len(vix_df)} bars VIX")
    except Exception as e:
        print(f"        [WARN] VIX load failed: {type(e).__name__}: {e}")
        vix_df = pd.DataFrame()

    # ─── 4. MenthorQ API JSON ───────────────────────────────────────
    # FIX R1 audit code-reviewer 19/05 : load_menthorq_json lit 124 fichiers JSON
    # daily (DATA/MENTHORQ/{YYYYMMDD}_menthorq_complete.json), couverture dec 2025+.
    # Avant : load_mq_levels Hive deploy 28/04 only -> 95% trou sur 8 mois.
    print("  [4/10] Load MenthorQ levels (JSON files daily)...")
    mq_levels = load_menthorq_json(symbol, start, end)
    print(f"        {len(mq_levels)} levels rows (daily broadcast)")

    # ─── 5. Merge OHLCV + Trades + VIX ──────────────────────────────
    # Convention BUILDER MIXED : ts_event tz-NAIVE pour merge + attach_mq_distances.
    # add_session_metadata gere tz_localize("UTC").tz_convert(ET) en interne.
    print("  [5/10] Merge OHLCV + Trades + VIX (LEFT JOIN sur ts_event, tz-naive)...")
    ohlcv["ts_event"] = pd.to_datetime(ohlcv["ts_event"])
    if isinstance(ohlcv["ts_event"].dtype, pd.DatetimeTZDtype):
        ohlcv["ts_event"] = ohlcv["ts_event"].dt.tz_localize(None)
    if not trades_1min.empty:
        trades_1min["ts_event"] = pd.to_datetime(trades_1min["ts_event"])
        if isinstance(trades_1min["ts_event"].dtype, pd.DatetimeTZDtype):
            trades_1min["ts_event"] = trades_1min["ts_event"].dt.tz_localize(None)

    df = ohlcv.merge(trades_1min, on="ts_event", how="left") if not trades_1min.empty else ohlcv

    if not vix_df.empty:
        vix_df["ts_event"] = pd.to_datetime(vix_df["ts_event"])
        if isinstance(vix_df["ts_event"].dtype, pd.DatetimeTZDtype):
            vix_df["ts_event"] = vix_df["ts_event"].dt.tz_localize(None)
        df = df.merge(vix_df, on="ts_event", how="left")
        df = enrich_vix_lite(df)
    print(f"        merge done : {len(df)} bars × {len(df.columns)} cols")

    # ─── 6. ATR Wilder + roll detection ─────────────────────────────
    print("  [6/10] ATR Wilder 14j + roll detection...")
    if "delta_bar" in df.columns:
        df["bar_no_trade"] = df["delta_bar"].isna().astype(int)
        for c in ["buy_vol", "sell_vol", "delta_bar", "n_trades", "max_trade_size"]:
            if c in df.columns:
                df[c] = df[c].fillna(0)
    df = compute_atr(df, period=14)
    df = detect_roll(df)

    # ─── 7. MenthorQ asof + distances _pct ──────────────────────────
    # attach_mq_distances (load_mq_levels.py:209) fait astype("datetime64[ns]") qui
    # NE PEUT PAS convertir tz-aware -> exige tz-naive. df est deja tz-naive depuis
    # etape 5 donc OK. apres on tz-localize UTC pour apply_all_engines.
    print("  [7/10] Asof merge MenthorQ + distances _pct (tz-naive)...")
    if not mq_levels.empty:
        df = attach_mq_distances(df, mq_levels, tick_size=tick)

    # Re-localize tz-aware UTC pour apply_all_engines (process_partition convention)
    df["ts_event"] = pd.to_datetime(df["ts_event"]).dt.tz_localize("UTC")
    if not trades_tick.empty:
        trades_tick["ts_event"] = pd.to_datetime(trades_tick["ts_event"]).dt.tz_localize("UTC")

    # ─── 8. APPLY ALL ENGINES (Phase B + B+ + B+++ + Edge + Sessions + Rolling + MP + Dalton + Regime) ───
    # apply_all_engines exige Trades tick-par-tick (cols price/size/side) tz-aware UTC pour
    # Volume Profile, footprint cells, VPOC running (process_partition convention).
    print("  [8/10] apply_all_engines (Phase B + B+ + B+++ + Edge + ... + Regime) [tz-aware UTC]...")
    df = apply_all_engines(df, trades_df=trades_tick, symbol=symbol, tick=tick, bounds=bounds)

    # ─── 9. add_session_cvd + apply_v6_complete ─────────────────────
    # ORDRE CRITIQUE : add_session_cvd AVANT apply_v6_complete car cvd_day_dir
    # exige cvd_session (calcule via CVD session reset CME 22:00 UTC).
    # range_pos s'appuie sur cur_val/cur_vah RUNNING (deja calcules par Phase C
    # dans apply_all_engines/add_all_phase_b_helpers). Coherence interne garantie.
    print("  [9/12] CVD session reset + apply_v6_complete (range_pos FIX #4)...")
    df = add_session_cvd(df)
    df = apply_v6_complete(df, tick=tick)

    # ─── 9bis. Option C extras (profile_shape + trend_day_probability) ───
    # FIX audit 19/05 : ces 2 features critiques pour regime_engine etaient
    # absentes du builder pure (DMP-only avant). Ports Python canoniques :
    # profile_shape via game_changers.classify_profile_shape (poc_position),
    # trend_day_probability via heuristique DMP_Transform.h:1310-1326.
    print("  [10/12] apply_v6_extras (profile_shape + trend_day_probability)...")
    df = apply_v6_extras(df, symbol=symbol)

    # ─── 9ter. RE-RUN regime_engine avec profile_shape + trend_day_probability ───
    # apply_all_engines a deja appele regime_engine (etape 8) MAIS sans ces 2
    # features (alors absentes). On re-applique pour integrer ces inputs.
    # Coherence Option C : regime_actionable monte de ~0% a niveau utilisable.
    print("  [11/12] Re-run regime_engine (avec profile_shape + trend_day_probability)...")
    try:
        from regime_engine import compute_regime_dict
    except ImportError:
        sys.path.insert(0, str(ROOT / "CORE"))
        from regime_engine import compute_regime_dict

    regime_records = []
    for _, row in df.iterrows():
        regime_records.append(compute_regime_dict(row.to_dict()))
    df_regime = pd.DataFrame(regime_records, index=df.index)
    # Drop anciennes colonnes regime_* (Phase 8 sans profile_shape/trend) avant concat
    for c in df_regime.columns:
        if c in df.columns:
            df = df.drop(columns=[c])
    df = pd.concat([df, df_regime], axis=1)
    if "regime_actionable" in df.columns:
        pct = df["regime_actionable"].mean() * 100
        print(f"        regime_actionable rate (post profile/trend): {pct:.1f}%")

    # ─── Sanity check post-build (anti regression silencieuse) ───
    # Suite incident IB_NARROW_THRESHOLD 19/05 : valider que les features critiques
    # ont une distribution non-degeneree. Si fail = bug calibration regression.
    if "trend_day_probability" in df.columns:
        tdp = df["trend_day_probability"]
        nunique = tdp.nunique()
        mean = tdp.mean()
        if nunique < 4:
            print(f"  ⚠️  WARNING : trend_day_probability nunique={nunique} (<4 attendu). "
                  f"Verifier calibration IB_NARROW_THRESHOLDS / open_gap_threshold.")
        if not (0.20 <= mean <= 0.80):
            print(f"  ⚠️  WARNING : trend_day_probability mean={mean:.3f} (hors [0.20, 0.80]). "
                  f"Distribution suspecte.")

    # ─── 10. PCT distances + OHLC derived + partition ───
    print("  [12/12] PCT distances + OHLC derived + partition...")
    df = add_pct_normalized_distances(df, symbol=symbol)
    df = add_ohlc_derived_features(df)

    # Sort + dedup safety
    df = df.sort_values("ts_event").drop_duplicates("ts_event").reset_index(drop=True)

    # Year/month/day pour partitioning
    ts = pd.to_datetime(df["ts_event"])
    df["year"] = ts.dt.year
    df["month"] = ts.dt.month
    df["day"] = ts.dt.day

    elapsed = time.time() - t0
    print(f"\n  ✅ DONE : {len(df)} bars × {len(df.columns)} cols ({elapsed:.1f}s)")
    return df


def write_partitioned_pure(df: pd.DataFrame, symbol: str):
    """Ecrit V4 pure partition Hive year=YYYY/month=MM (atomic write via .tmp).

    Output : DATA/datasets/v4_pure/symbol={sym}.c.0/year=YYYY/month=MM/data.parquet
    """
    if df.empty:
        return
    OUT_ROOT_PURE.mkdir(parents=True, exist_ok=True)

    db_ticker = get_databento_ticker(symbol)
    for (yr, mo), grp in df.groupby(["year", "month"], sort=True):
        out_dir = OUT_ROOT_PURE / f"symbol={db_ticker}" / f"year={yr}" / f"month={mo:02d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "data.parquet"
        tmp_path = out_dir / "data.parquet.tmp"

        # Drop partition cols avant write (deja dans le path Hive)
        grp_clean = grp.drop(columns=["year", "month", "day"], errors="ignore")
        table = pa.Table.from_pandas(grp_clean, preserve_index=False)
        pq.write_table(table, tmp_path, compression="snappy")
        tmp_path.replace(out_path)
        print(f"  wrote {out_path.name} : {len(grp_clean)} bars × {len(grp_clean.columns)} cols")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["ES", "NQ"],
                    help="Symboles a builder (default ES NQ)")
    ap.add_argument("--start", help="YYYY-MM-DD (default 2025-10-01)")
    ap.add_argument("--end", help="YYYY-MM-DD (default today)")
    ap.add_argument("--test-day", help="YYYY-MM-DD pour test 1 jour seulement")
    args = ap.parse_args()

    if args.test_day:
        d = date.fromisoformat(args.test_day)
        start_d, end_d = d, d
    else:
        start_d = date.fromisoformat(args.start) if args.start else date(2025, 10, 1)
        end_d = date.fromisoformat(args.end) if args.end else date.today()

    print(f"\nConfig V4 PURE Databento : symbols={args.symbols} {start_d} -> {end_d}")
    print(f"Output : {OUT_ROOT_PURE}")

    OUT_ROOT_PURE.mkdir(parents=True, exist_ok=True)

    summary = []
    for sym in args.symbols:
        try:
            df = build_for_symbol_pure(sym, start_d, end_d)
            if not df.empty:
                write_partitioned_pure(df, sym)
                summary.append({
                    "symbol": sym,
                    "bars": len(df),
                    "cols": len(df.columns),
                    "ts_min": str(df["ts_event"].min()),
                    "ts_max": str(df["ts_event"].max()),
                })
        except Exception as e:
            print(f"\n[ERROR] {sym} : {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 70)
    print(" SUMMARY V4 PURE")
    print("=" * 70)
    for s in summary:
        print(f"  {s['symbol']:6s} bars={s['bars']:>7d} cols={s['cols']:>3d}  "
              f"{s['ts_min']} -> {s['ts_max']}")


if __name__ == "__main__":
    main()
