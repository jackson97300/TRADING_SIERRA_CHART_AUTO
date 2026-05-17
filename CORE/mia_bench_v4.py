# -*- coding: utf-8 -*-
"""
mia_bench_v4.py — Benchmark V4 enriched (Databento + DMP fusion)
=================================================================

Equivalent de `mia_bench.py` mais pour les donnees V4 enriched parquet
(`DATA/datasets/v4_enriched/symbol={ES,NQ,MGC}.c.0/year=*/month=*/data.parquet`).

36 tests (mai 2026) couvrant schema, coverage, edges marginaux, etc.

Usage :
    python -X utf8 CORE/mia_bench_v4.py [--month YYYY-MM] [--symbol ES|NQ|MGC]

Output : `DATA/MIA_BENCH_V4_REPORT_YYYYMMDD_HHMM.txt`

NOTES SCHEMA (17/05/2026, post audit complet 6 mois) :
- ES/NQ : 454-460 colonnes Phase A + Phase B complet
- MGC : 420 cols (VPS Phase B complet) OU 57 cols (LOCAL Phase A seul)
  -> Si bench dit "MGC schema FAIL 57 cols", check si Phase B a tourne
     local (vs LOCAL = Phase A seul = 57 cols basic Databento).
- MGC design 38 cols ABSENTES vs ES (legitime) :
  * im_* (10) : intermarket NQ/ES, pas de pair MGC
  * Long color zones (5) : Sierra Chart Extension Lines pas activees MGC
  * Market Profile (5) : bars_in_va, range_pos, profile_shape, etc.
  * VIX cross (3) : dist_vix_gex_*
  * Misc (5) : cvd_day_dir, momentum_3b, ma_trend, delta_divergence, dist_blind_*

NOTES TESTS MORTS (17/05) :
- Test 34 AMD Power of 3 : "Aucune colonne amd_*" sur 3 symboles. Features
  amd_* du V1 DMP non migrees vers v4 enriched. A soit :
    (a) retirer du bench, (b) re-generer dans Phase B via mia_amd.py adapter

NOTES ENRICHISSEMENTS BACKLOG :
- Ajouter test_noyau_dur (present dans mia_bench.py DMP, absent ici).
  Methode : top N features les + stables/discriminantes sur 6+ mois,
  ratio Spearman vs forward returns, std/range, fire rate stable.
"""
from __future__ import annotations

import argparse
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V4_ROOT = ROOT / "DATA" / "datasets" / "v4_enriched"
TICK = 0.25

# Schema attendu (audit 05/05 post-fix features cassees)
# P0.3 fix code-reviewer 06/05 : 420 trop bas (V4 reel = 446-456 cols).
# Le test passait trivialement = du theatre. Bumpe a 450 (en-dessous = regression schema).
EXPECTED_COLS_MIN = 450
SCHEMA_VERSION_V4 = "v4_enriched_2026_05"

# Features critiques V4 (presence obligatoire)
CRITICAL_V4 = [
    # OHLCV
    "open", "high", "low", "close", "volume",
    "delta_bar", "buy_vol", "sell_vol", "cvd_session",
    # MQ levels (post-fix MQ_Lite)
    "dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
    # Range
    "range_pos",
    # ATR
    "atr_14m_pct",
    # OF
    "bn_absorb_ask_raw", "bn_absorb_bid_raw",
    "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
    # Big orders
    "n_big_t1", "n_big_t2",
    # Cluster
    "cluster_at_high", "cluster_at_low",
    # Liquidity sweep
    "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
    # Regime engine output
    "regime_mode", "regime_favor", "regime_actionable",
    # Phase B+++ Edge zones / VWAP
    "vwap_d_sd1u", "vwap_d_sd2u", "vwap_d_sd3u",
    "vwap_d_sd1d", "vwap_d_sd2d", "vwap_d_sd3d",
]

# Features post-fix 05/05 (devraient avoir fire rate >0.1% sur ES RTH)
POST_FIX_FEATURES = [
    "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    "im_smt_divergence",
    "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
]


# ═════════════════════════════════════════════════════════════════════
# DISCOVERY
# ═════════════════════════════════════════════════════════════════════

def discover_v4(month_filter: str | None = None, sym_filter: str | None = None) -> dict:
    """Trouve tous les parquets V4 disponibles. Returns {sym: [paths sorted]}."""
    found = defaultdict(list)
    for sym_dir in V4_ROOT.glob("symbol=*.c.0"):
        sym = sym_dir.name.replace("symbol=", "").replace(".c.0", "")
        if sym_filter and sym != sym_filter:
            continue
        for parquet in sym_dir.glob("year=*/month=*/data.parquet"):
            year_part = parquet.parent.parent.name.replace("year=", "")
            month_part = parquet.parent.name.replace("month=", "")
            month_str = f"{year_part}-{month_part}"
            if month_filter and month_str != month_filter:
                continue
            found[sym].append({
                "path": parquet,
                "year": int(year_part),
                "month": int(month_part),
                "month_str": month_str,
                "size_mb": parquet.stat().st_size / 1024 / 1024,
            })
    for sym in found:
        found[sym].sort(key=lambda x: (x["year"], x["month"]))
    return dict(found)


def load_v4(symbol: str, partitions: list, days: int | None = None) -> pd.DataFrame:
    """Load V4 parquets. Optionally limit to last N days."""
    dfs = []
    for p in partitions:
        df = pd.read_parquet(p["path"])
        df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
        df = df.dropna(subset=["ts_event"]).sort_values("ts_event")
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    full = pd.concat(dfs, ignore_index=True).drop_duplicates(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    if days is not None:
        cutoff = full["ts_event"].max() - pd.Timedelta(days=days)
        full = full[full["ts_event"] >= cutoff].reset_index(drop=True)
    return full


# ═════════════════════════════════════════════════════════════════════
# TEST 1 — SCHEMA
# ═════════════════════════════════════════════════════════════════════

def test_schema(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 1 — SCHEMA V4")
    out.append("=" * 70)
    out.append("")
    total = 0
    passed = 0
    for sym, df in data.items():
        if df.empty:
            continue
        ncols = len(df.columns)
        ok_count = ncols >= EXPECTED_COLS_MIN
        total += 1; passed += int(ok_count)
        status = "OK" if ok_count else "FAIL"
        out.append(f"  Cols {sym}: {ncols} (min attendu {EXPECTED_COLS_MIN}) [{status}]")
        # Critical features
        missing = [c for c in CRITICAL_V4 if c not in df.columns]
        ok_crit = len(missing) == 0
        total += 1; passed += int(ok_crit)
        status = "OK" if ok_crit else "FAIL"
        out.append(f"  Critical features {sym}: {len(CRITICAL_V4)-len(missing)}/{len(CRITICAL_V4)} present [{status}]")
        if missing:
            out.append(f"    Missing: {', '.join(missing[:8])}{'...' if len(missing)>8 else ''}")
    out.append(f"\n  Total: {passed}/{total} tests passent")
    out.append("")
    return passed, total


# ═════════════════════════════════════════════════════════════════════
# TEST 2 — INVENTORY
# ═════════════════════════════════════════════════════════════════════

def test_inventory(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 2 — INVENTORY V4")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty:
            out.append(f"  {sym}: AUCUNE DATA")
            continue
        n = len(df)
        ts_min = df["ts_event"].min()
        ts_max = df["ts_event"].max()
        days = df["ts_event"].dt.date.nunique()
        # RTH bars (13:30-21:00 UTC)
        rth_mask = (df["ts_event"].dt.hour >= 13) & (df["ts_event"].dt.hour < 21)
        n_rth = rth_mask.sum()
        # Premiere/derniere bar age
        now = pd.Timestamp.now(tz="UTC")
        last_age_min = (now - ts_max).total_seconds() / 60
        out.append(f"  {sym}: {n} bars total | {n_rth} RTH ({n_rth/n*100:.1f}%) | {days} jours")
        out.append(f"    range: {ts_min} -> {ts_max}")
        out.append(f"    derniere bar: il y a {last_age_min:.1f} min")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 3 — COVERAGE (% notna par feature)
# ═════════════════════════════════════════════════════════════════════

def test_coverage(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 3 — COVERAGE FEATURES (notna%)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty:
            continue
        out.append(f"\n  --- {sym} ---")
        # Sample 25 features critiques
        sample = ["dist_mq_call_pct", "dist_mq_put_pct", "regime_mode", "regime_actionable",
                   "atr_14m_pct", "delta_bar", "cvd_session",
                   "bn_absorb_ask_raw", "bn_trapped_buyers_raw",
                   "n_big_t1", "n_big_t2", "cluster_at_high",
                   "liquidity_sweep_high_lag5", "vwap_d_sd1u", "vwap_d_sd2u",
                   "im_smt_divergence", "im_cross_delta_agreement_5"]
        for col in sample:
            if col not in df.columns:
                out.append(f"    {col:35s}: ABSENT")
                continue
            cov = df[col].notna().mean() * 100
            status = "OK" if cov >= 50 else ("WARN" if cov >= 20 else "LOW")
            out.append(f"    {col:35s}: {cov:5.1f}% [{status}]")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 4 — QUALITY (nonzero rate, uniques)
# ═════════════════════════════════════════════════════════════════════

def test_quality(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 4 — QUALITY (nonzero%, uniques) — features post-fix 05/05")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty:
            continue
        out.append(f"\n  --- {sym} ---")
        # Filtre RTH only pour mesure plus precise
        rth = df[(df["ts_event"].dt.hour >= 13) & (df["ts_event"].dt.hour < 21)]
        for col in POST_FIX_FEATURES:
            if col not in df.columns:
                out.append(f"    {col:40s}: ABSENT")
                continue
            vals_all = df[col].fillna(0)
            nz_all = (vals_all != 0).mean() * 100
            n_unique = df[col].dropna().nunique()
            vals_rth = rth[col].fillna(0) if not rth.empty else vals_all
            nz_rth = (vals_rth != 0).mean() * 100 if len(vals_rth) > 0 else 0
            # Verdict
            if nz_rth >= 0.5:
                v = "OK FIRE"
            elif nz_rth >= 0.1:
                v = "RARE OK"
            else:
                v = "DEAD?"
            out.append(f"    {col:40s}: ALL={nz_all:5.2f}% RTH={nz_rth:5.2f}% uniq={n_unique:3d} [{v}]")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 5 — CROSS-ASSET SYMMETRY (ES vs NQ)
# ═════════════════════════════════════════════════════════════════════

def test_symmetry(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 5 — CROSS-ASSET SYMMETRY (ES vs NQ)")
    out.append("=" * 70)
    out.append("")
    if "ES" not in data or "NQ" not in data:
        out.append("  ES ou NQ manque, skip")
        return
    df_es = data["ES"]
    df_nq = data["NQ"]
    if df_es.empty or df_nq.empty:
        out.append("  ES ou NQ vide, skip")
        return
    # Features percentage / normalized = devraient etre comparables
    pct_features = ["range_pos", "atr_14m_pct", "dist_mq_call_pct", "dist_mq_put_pct"]
    out.append(f"  {'Feature':35s} {'ES_med':>10s} {'NQ_med':>10s} {'ES_std':>10s} {'NQ_std':>10s} {'Ratio':>8s}")
    for col in pct_features:
        if col not in df_es.columns or col not in df_nq.columns:
            continue
        es_med = df_es[col].median()
        nq_med = df_nq[col].median()
        es_std = df_es[col].std()
        nq_std = df_nq[col].std()
        ratio = nq_std / es_std if es_std and not pd.isna(es_std) and es_std > 0 else float("nan")
        status = "OK" if 0.5 < ratio < 2.0 else "ASYM"
        out.append(f"  {col:35s} {es_med:>10.3f} {nq_med:>10.3f} {es_std:>10.3f} {nq_std:>10.3f} {ratio:>7.2f}x [{status}]")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 6 — FEATURE HEALTH (detect mortes / quasi-constantes)
# ═════════════════════════════════════════════════════════════════════

def test_health(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 6 — FEATURE HEALTH (mortes / quasi-constantes)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty:
            continue
        out.append(f"\n  --- {sym} ---")
        n_total = len(df)
        dead_features = []
        constant_features = []
        outlier_features = []
        for col in df.columns:
            if df[col].dtype.kind not in ("i", "u", "f"):
                continue
            vals = df[col].dropna()
            if len(vals) < 10:
                continue
            n_unique = vals.nunique()
            # Mort : >99% zero
            zero_rate = (vals == 0).mean()
            if zero_rate > 0.99 and n_unique <= 2:
                dead_features.append((col, zero_rate))
            # Quasi-constante : 1 valeur >95% du temps
            top_freq = vals.value_counts(normalize=True).iloc[0] if len(vals) > 0 else 0
            if top_freq > 0.95 and col not in dead_features:
                constant_features.append((col, top_freq))
            # Outlier : max / |p99| > 100
            try:
                p99 = vals.quantile(0.99)
                vmax = abs(vals.max())
                if abs(p99) > 0 and vmax / abs(p99) > 100:
                    outlier_features.append((col, vmax / abs(p99)))
            except Exception:
                pass
        out.append(f"    DEAD (>99% zero, <=2 uniques): {len(dead_features)}")
        for col, rate in dead_features[:8]:
            out.append(f"      {col:35s}: zero={rate*100:.1f}%")
        if len(dead_features) > 8:
            out.append(f"      ... +{len(dead_features)-8} more")
        out.append(f"    QUASI-CONSTANT (>95% top freq, hors dead): {len(constant_features)}")
        for col, freq in constant_features[:5]:
            out.append(f"      {col:35s}: top_freq={freq*100:.1f}%")
        out.append(f"    OUTLIER (max/p99 > 100x): {len(outlier_features)}")
        for col, ratio in outlier_features[:5]:
            out.append(f"      {col:35s}: ratio={ratio:.0f}x")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 7 — STATIONARITY (drift mensuel)
# ═════════════════════════════════════════════════════════════════════

def test_stationarity(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 7 — STATIONARITY (drift mensuel sur features cles)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty:
            continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["ym"] = df["ts_event"].dt.strftime("%Y-%m")
        months = sorted(df["ym"].unique())
        if len(months) < 2:
            out.append(f"    Un seul mois ({months[0] if months else 'NA'}) — skip stationarity test")
            continue
        check_features = ["range_pos", "atr_14m_pct", "delta_bar"]
        for col in check_features:
            if col not in df.columns:
                continue
            line = f"    {col:25s}: "
            for m in months:
                sub = df[df["ym"] == m][col].dropna()
                if len(sub) < 100:
                    continue
                med = sub.median()
                line += f"{m}={med:7.3f}  "
            out.append(line)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 8 — RANKING BOOTSTRAP (corr features -> returns futurs IC 95%)
# ═════════════════════════════════════════════════════════════════════

def test_ranking(data: dict, out: list, n_bootstrap: int = 500, seed: int = 42):
    out.append("=" * 70)
    out.append("  TEST 8 — RANKING BOOTSTRAP (correlation feature -> fut_r3, IC 95%)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty or "close" not in df.columns:
            continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["fut_r3"] = df["close"].shift(-3) - df["close"]
        df["fut_r5"] = df["close"].shift(-5) - df["close"]
        # Pool features V4 (ctx_, im_, mq_, regime_, dist_*_pct, etc.)
        feat_cols = [c for c in df.columns
                     if c.startswith(("ctx_", "im_", "mq_", "regime_"))
                     or c.endswith(("_pct", "_atr", "_z"))
                     or c in ("delta_bar", "cvd_session", "range_pos", "atr_14m_pct",
                              "open_bias_conf", "trend_day_probability")]
        feat_cols = [c for c in feat_cols if c in df.columns and df[c].dtype.kind in "iuf"]
        rng = np.random.RandomState(seed)
        results = []
        # P0.1 fix code-reviewer (06/05) : vectorisation bootstrap (gain ~50x)
        # Avant : 200K iloc+corr -> 30+ min. Apres : np.corrcoef sur arrays.
        for col in feat_cols:
            sub = df[[col, "fut_r3"]].dropna()
            n = len(sub)
            if n < 100: continue
            x = sub[col].values
            y = sub["fut_r3"].values
            # Skip si variance nulle
            if np.std(x) == 0 or np.std(y) == 0: continue
            r = float(np.corrcoef(x, y)[0, 1])
            if not np.isfinite(r): continue
            # Bootstrap CI 95% vectorise
            boots = np.empty(n_bootstrap)
            n_valid = 0
            for i in range(n_bootstrap):
                idx = rng.choice(n, size=n, replace=True)
                xs, ys = x[idx], y[idx]
                if np.std(xs) == 0 or np.std(ys) == 0: continue
                rb = float(np.corrcoef(xs, ys)[0, 1])
                if np.isfinite(rb):
                    boots[n_valid] = rb
                    n_valid += 1
            if n_valid < 50: continue
            boots = boots[:n_valid]
            ci_lo = float(np.percentile(boots, 2.5))
            ci_hi = float(np.percentile(boots, 97.5))
            ci_ok = not (ci_lo < 0 and ci_hi > 0)
            results.append({"col": col, "r": r, "ci_lo": ci_lo, "ci_hi": ci_hi, "ci_ok": ci_ok})
        results.sort(key=lambda x: abs(x["r"]), reverse=True)
        out.append(f"  Top 15 features par |r| (n_bootstrap={n_bootstrap}, |r| min affiche=0.02) :")
        out.append(f"  {'Feature':40s} {'r':>7s} {'CI_lo':>7s} {'CI_hi':>7s} {'Class':>8s}")
        n_beton = 0
        for r in results[:15]:
            cls = "BETON" if (abs(r["r"]) >= 0.05 and r["ci_ok"]) else ("PROB" if r["ci_ok"] else "frag")
            if cls == "BETON": n_beton += 1
            mark = " *" if r["ci_ok"] and abs(r["r"]) >= 0.05 else ""
            out.append(f"  {r['col']:40s} {r['r']:+.3f} {r['ci_lo']:+7.3f} {r['ci_hi']:+7.3f} {cls:>8s}{mark}")
        out.append(f"  Total feature analysees: {len(results)}, {n_beton} BETON (|r|>=0.05 + CI ne croise pas 0)")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 9 — GAME CHANGERS (open_type, day_type, profile_shape -> outcomes)
# ═════════════════════════════════════════════════════════════════════

OPEN_TYPE_NAMES = {0: "OO", 1: "ODup", 2: "ODdn", 3: "OTDup", 4: "OTDdn", 5: "ORRup", 6: "ORRdn"}
DAY_TYPE_NAMES = {0: "NonTrend", 1: "Normal", 2: "NormVar", 3: "Neutral", 4: "Trend"}
PROFILE_SHAPE_NAMES = {0: "D-Range", 1: "P-Shape", 2: "b-Shape", 3: "DoubleDist"}

def test_game_changers(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 9 — GAME CHANGERS (open_type, day_type, profile_shape)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        if "close" in df.columns:
            df["fut_r5"] = df["close"].shift(-5) - df["close"]
        for col, names in [("open_type", OPEN_TYPE_NAMES),
                           ("day_type", DAY_TYPE_NAMES),
                           ("profile_shape", PROFILE_SHAPE_NAMES)]:
            if col not in df.columns:
                continue
            out.append(f"  {col}:")
            for v, name in names.items():
                sub = df[df[col] == v]
                if len(sub) < 5: continue
                fut_med = sub["fut_r5"].median() if "fut_r5" in sub.columns else float("nan")
                out.append(f"    {v} {name:12s}: n={len(sub):>5d}  fut_r5 median={fut_med:+.2f}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 10 — REGIME SPLIT (TREND vs RANGE vs NORMAL)
# ═════════════════════════════════════════════════════════════════════

def test_regime_split(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 10 — REGIME SPLIT (TREND vs RANGE vs NORMAL)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty or "regime_mode" not in df.columns:
            continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        if "close" in df.columns:
            df["fut_r5"] = df["close"].shift(-5) - df["close"]
        regime_dist = df["regime_mode"].value_counts()
        out.append(f"  Distribution regime_mode :")
        for mode, n in regime_dist.items():
            sub = df[df["regime_mode"] == mode]
            fut_mean = sub["fut_r5"].mean() if "fut_r5" in sub.columns else float("nan")
            actionable = sub["regime_actionable"].mean() * 100 if "regime_actionable" in sub.columns else float("nan")
            out.append(f"    {str(mode):10s}: n={n:>5d} ({n/len(df)*100:5.1f}%)  fut_r5_mean={fut_mean:+.3f}  actionable={actionable:.0f}%")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 11 — THRESHOLDS SENSIBILITY (variation seuils key features)
# ═════════════════════════════════════════════════════════════════════

def test_thresholds(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 11 — THRESHOLDS SENSIBILITY")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty or "close" not in df.columns:
            continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["fut_r3"] = df["close"].shift(-3) - df["close"]
        # range_pos thresholds
        if "range_pos" in df.columns:
            out.append(f"  range_pos extreme (LONG potential)")
            for t in [60, 70, 80, 90, 100]:
                sig = df[df["range_pos"] >= t]
                n = len(sig)
                if n < 10: continue
                wr_long = (sig["fut_r3"] > 0).mean()
                fut_med = sig["fut_r3"].median()
                out.append(f"    >= {t:>3d}%: n={n:>5d} ({n/len(df)*100:.1f}%) WR_long={wr_long*100:.0f}% fut_r3_med={fut_med:+.2f}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 12 — SESSION TIMING (Asia/London/RTH/post-RTH)
# ═════════════════════════════════════════════════════════════════════

def test_session_timing(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 12 — SESSION TIMING (best/worst hours)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty or "close" not in df.columns: continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["fut_r5"] = df["close"].shift(-5) - df["close"]
        df["hour_utc"] = df["ts_event"].dt.hour
        # Sessions standard : Asia 22-2 UTC, London 6-12 UTC, RTH 13-20 UTC
        sessions = {
            "Asia (22-02 UTC)": ((df["hour_utc"] >= 22) | (df["hour_utc"] < 2)),
            "London (06-12 UTC)": (df["hour_utc"] >= 6) & (df["hour_utc"] < 12),
            "Pre-RTH (12-13 UTC)": (df["hour_utc"] >= 12) & (df["hour_utc"] < 13),
            "RTH (13-20 UTC)": (df["hour_utc"] >= 13) & (df["hour_utc"] < 20),
            "Post-RTH (20-22 UTC)": (df["hour_utc"] >= 20) & (df["hour_utc"] < 22),
        }
        for name, mask in sessions.items():
            sub = df[mask]
            if len(sub) < 50: continue
            n = len(sub)
            mean_abs_r = sub["fut_r5"].abs().median()  # volatility proxy
            wr_pos = (sub["fut_r5"] > 0).mean()
            out.append(f"    {name:25s}: n={n:>5d} med|fut_r5|={mean_abs_r:.2f} WR_pos={wr_pos*100:.0f}%")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 13 — WALL TRACKER (touches MQ/IB/VWAP -> outcome)
# ═════════════════════════════════════════════════════════════════════

WALL_FEATURES = {
    "MQ_CALL": "dist_mq_call_pct",
    "MQ_PUT": "dist_mq_put_pct",
    "MQ_HVL": "dist_mq_hvl_pct",
    "VWAP_D_SD2U": "dist_vwap_d_sd2u_pct",
    "VWAP_D_SD2D": "dist_vwap_d_sd2d_pct",
    "IB_HIGH": "dist_ib_high_pct",
    "IB_LOW": "dist_ib_low_pct",
    "PDH": "dist_pdh_pct",
    "PDL": "dist_pdl_pct",
}
TOUCH_TOL_PCT = 0.05  # 5 bps = ~3-4 ticks ES, ~13 ticks NQ

def test_wall_tracker(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 13 — WALL TRACKER (touche niveau -> outcome fut_r5)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty or "close" not in df.columns: continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["fut_r5"] = df["close"].shift(-5) - df["close"]
        out.append(f"  {'Wall':12s} {'N touches':>10s} {'fut_r5 mean':>14s} {'WR>0':>7s}")
        for wall_name, dist_col in WALL_FEATURES.items():
            if dist_col not in df.columns: continue
            mask = df[dist_col].abs() <= TOUCH_TOL_PCT
            sub = df[mask]
            if len(sub) < 5: continue
            mean_r = sub["fut_r5"].mean()
            wr = (sub["fut_r5"] > 0).mean()
            out.append(f"  {wall_name:12s} {len(sub):>10d} {mean_r:>+13.3f} {wr*100:>6.0f}%")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 14 — SIGNAL vs BRUIT (filter quality auto-tri)
# ═════════════════════════════════════════════════════════════════════

def test_signal_vs_bruit(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 14 — SIGNAL vs BRUIT (auto-tri colonnes)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty or "close" not in df.columns: continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["fut_r3"] = df["close"].shift(-3) - df["close"]
        signals = []  # |r|>0.05 + nunique>2
        bruit = []
        for col in df.columns:
            if df[col].dtype.kind not in "iuf": continue
            if col in ("ts_event", "year", "month", "day", "fut_r3", "fut_r5"): continue
            sub = df[[col, "fut_r3"]].dropna()
            if len(sub) < 100: continue
            n_unique = sub[col].nunique()
            if n_unique <= 2: continue
            r = sub[col].corr(sub["fut_r3"])
            if pd.isna(r): continue
            # P0.2 fix code-reviewer : .loc[] au lieu de .iloc[] sur sub.index
            # (sub.index = labels, pas positions, apres dropna).
            # Permet exemption colonnes _pct / _atr / _z (deja normalisees).
            if col.endswith(("_pct", "_atr", "_z")):
                pass  # deja normalisee, anti-proxy non requis
            else:
                r_close = sub[col].corr(df["close"].loc[sub.index])
                if pd.notna(r_close) and abs(r_close) > 0.80: continue  # proxy prix
            if abs(r) >= 0.05:
                signals.append((col, r))
            elif abs(r) < 0.02:
                bruit.append((col, r))
        out.append(f"  SIGNAUX (|r|>=0.05) : {len(signals)}")
        for col, r in sorted(signals, key=lambda x: -abs(x[1]))[:10]:
            out.append(f"    {col:40s}: r={r:+.3f}")
        out.append(f"  BRUIT (|r|<0.02)    : {len(bruit)}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 15 — VERDICT GLOBAL (synthese B/P/F par symbol)
# ═════════════════════════════════════════════════════════════════════

def test_verdict(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 15 — VERDICT GLOBAL")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        n = len(df)
        days = df["ts_event"].dt.date.nunique() if "ts_event" in df.columns else 0
        ncols = len(df.columns)
        # Health checks
        crit_present = sum(1 for c in CRITICAL_V4 if c in df.columns)
        crit_total = len(CRITICAL_V4)
        # Coverage moyenne sur features critiques
        cov_avg = float("nan")
        if crit_present > 0:
            covs = [df[c].notna().mean() for c in CRITICAL_V4 if c in df.columns]
            cov_avg = np.mean(covs) * 100 if covs else 0
        # Verdict empirique
        if n >= 1000 and days >= 5 and ncols >= EXPECTED_COLS_MIN and crit_present >= crit_total*0.9 and cov_avg >= 50:
            verdict = "BETON"
        elif n >= 500 and ncols >= EXPECTED_COLS_MIN and crit_present >= crit_total*0.7:
            verdict = "PROBABLE"
        else:
            verdict = "FRAGILE"
        out.append(f"  {sym}:")
        out.append(f"    bars      : {n}")
        out.append(f"    jours     : {days}")
        out.append(f"    cols      : {ncols} (min {EXPECTED_COLS_MIN})")
        out.append(f"    critical  : {crit_present}/{crit_total} ({crit_present/crit_total*100:.0f}%)")
        out.append(f"    coverage  : {cov_avg:.1f}%")
        out.append(f"    VERDICT   : {verdict}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 16 — RVOL DATABENTO VALIDATION (rvol stocke vs recalcul time-of-day)
# ═════════════════════════════════════════════════════════════════════

def test_rvol_databento(data: dict, out: list):
    """Equivalent V4 du test 14 DMP (RVOL C++ vs Python).
    Ici on compare le rvol stocke dans V4 avec un recalcul time-of-day
    (volume_bar / median(volume_meme_minute_du_jour_sur_N_jours)).
    """
    out.append("=" * 70)
    out.append("  TEST 16 — RVOL DATABENTO VALIDATION (stocke vs recalcul TOD)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        # Verif presence colonnes
        cols_present = [c for c in ["rvol", "rvol_z", "rvol_buy", "rvol_sell", "rvol_extreme"] if c in df.columns]
        out.append(f"  Colonnes RVOL presentes : {cols_present}")
        if "rvol" not in df.columns:
            out.append(f"  rvol absent — skip recalcul validation")
            continue
        # Distribution rvol
        rvol = df["rvol"].dropna()
        if len(rvol) < 100:
            out.append(f"  rvol n={len(rvol)} insuffisant")
            continue
        out.append(f"  Distribution rvol :")
        out.append(f"    n notna     : {len(rvol)} ({rvol.notna().mean()*100:.1f}%)")
        out.append(f"    median      : {rvol.median():.2f}")
        out.append(f"    mean        : {rvol.mean():.2f}")
        out.append(f"    p75         : {rvol.quantile(0.75):.2f}")
        out.append(f"    p95         : {rvol.quantile(0.95):.2f}")
        out.append(f"    p99         : {rvol.quantile(0.99):.2f}")
        out.append(f"    max         : {rvol.max():.2f}")
        # Sanity : rvol = 1.0 attendu en moyenne (ratio vol_actuel / vol_median_jour-meme-heure)
        sanity_ok = 0.5 <= rvol.median() <= 2.0
        out.append(f"    SANITY (0.5 <= median <= 2.0) : {'OK' if sanity_ok else 'WARN'}")

        # Recalcul time-of-day si possible
        if "volume" in df.columns and "ts_event" in df.columns:
            df = df.copy()
            df["minute_of_day"] = df["ts_event"].dt.hour * 60 + df["ts_event"].dt.minute
            df["date"] = df["ts_event"].dt.date
            # Median volume par minute-of-day sur l'historique (moins le jour courant pour eviter leakage)
            vol_by_mod = df.groupby("minute_of_day")["volume"].transform(
                lambda x: x.expanding(min_periods=10).median().shift(1)
            )
            with np.errstate(divide="ignore", invalid="ignore"):
                rvol_recompute = df["volume"] / vol_by_mod
            cmp_df = pd.DataFrame({"stored": df["rvol"], "recomp": rvol_recompute}).dropna()
            if len(cmp_df) > 100:
                # Correlation et ecart median
                corr = cmp_df["stored"].corr(cmp_df["recomp"])
                ratio = (cmp_df["stored"] / cmp_df["recomp"].replace(0, np.nan)).median()
                out.append(f"  Comparaison rvol stocke vs recompute :")
                out.append(f"    n         : {len(cmp_df)}")
                out.append(f"    corr      : {corr:.3f}  (>0.7 = OK)")
                out.append(f"    ratio med : {ratio:.2f}  (~1.0 = OK)")
                if pd.notna(corr) and corr > 0.7:
                    out.append(f"    VERDICT   : OK pipeline rvol coherent")
                else:
                    out.append(f"    VERDICT   : WARN pipeline rvol divergent")
        # Outliers extremes
        n_extreme = (rvol > 5).sum()
        out.append(f"  Outliers (rvol>5) : {n_extreme} ({n_extreme/len(rvol)*100:.2f}%)")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 36 — EDGE RETEST OUTCOMES (zone edge sell/buy retests)
# ═════════════════════════════════════════════════════════════════════

def test_long_color_retest(data: dict, out: list):
    """Test 37 (NEW 06/05) — LONG_UP/DN + COLOR_UP/DN Extension Lines retest outcomes.

    Mesure outcomes des retests de zones LONG (impulsion bar >= threshold) et COLOR
    (cellule bullish/bearish) dans le contexte trading manuel Jackson.

    Trigger : n_*_zones_active >= 1 AND |dist_*_nearest_pct| <= 0.10%.
    Hypothese Jackson : zones LONG/COLOR fonctionnent en RETEST avant invalidation
    (touch tue la zone). Si vrai -> WR > 50% sur fut_r3/r5 dans direction support/resistance.
    """
    out.append("=" * 70)
    out.append("  TEST 37 — LONG/COLOR RETEST OUTCOMES (Extension Lines Jackson trading manuel)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["fut_r3"] = df["close"].shift(-3) - df["close"]
        df["fut_r5"] = df["close"].shift(-5) - df["close"]
        df["fut_r10"] = df["close"].shift(-10) - df["close"]

        # Mapping (zone_type, support_or_resist, expected_dir_for_win)
        configs = [
            ("long_up", "support", "long"),     # zone support -> LONG potential -> fut > 0
            ("long_dn", "resistance", "short"), # zone resistance -> SHORT potential -> fut < 0
            ("color_up", "support", "long"),
            ("color_dn", "resistance", "short"),
        ]
        for zone, _typ, dir_ in configs:
            n_col = f"n_{zone}_zones_active"
            d_col = f"dist_{zone}_nearest_pct"
            if n_col not in df.columns or d_col not in df.columns:
                continue
            mask = (df[n_col] >= 1) & (df[d_col].abs() <= 0.10)
            sub = df[mask]
            n = len(sub)
            if n < 5:
                out.append(f"  {zone:10s} retest ({dir_.upper():>5s}) : n={n} (<5, skip)")
                continue
            fut3 = sub["fut_r3"].dropna()
            fut5 = sub["fut_r5"].dropna()
            fut10 = sub["fut_r10"].dropna()
            if dir_ == "long":
                wr5 = (fut5 > 0).mean() if len(fut5) > 0 else 0
            else:
                wr5 = (fut5 < 0).mean() if len(fut5) > 0 else 0
            out.append(f"  {zone:10s} retest ({dir_.upper():>5s}) : n={n}")
            out.append(f"    fut_r3 mean={fut3.mean():+.2f} med={fut3.median():+.2f}")
            out.append(f"    fut_r5 mean={fut5.mean():+.2f} med={fut5.median():+.2f}  WR_{dir_.upper()}={wr5*100:.0f}%")
            out.append(f"    fut_r10 mean={fut10.mean():+.2f} med={fut10.median():+.2f}")

        # Cluster outcomes : zones empilees pres du prix = niveau S/R puissant
        for zone, _typ, dir_ in configs:
            c_col = f"n_{zone}_cluster_within_0_2pct"
            if c_col not in df.columns:
                continue
            mask = df[c_col] >= 2
            sub = df[mask]
            n = len(sub)
            if n < 5: continue
            f5 = sub["fut_r5"].dropna()
            if dir_ == "long":
                wr5 = (f5 > 0).mean() if len(f5) > 0 else 0
            else:
                wr5 = (f5 < 0).mean() if len(f5) > 0 else 0
            out.append(f"  {zone:10s} cluster>=2 ({dir_.upper():>5s}): n={n} fut_r5_med={f5.median():+.2f} WR={wr5*100:.0f}%")
    out.append("")


def test_edge_retest(data: dict, out: list):
    """Mesure outcomes des retests de zones edge (sell = resistance, buy = support).

    Setup ICT typique : push violent cree une zone edge -> prix revient ->
    rebond/rejet attendu. Trigger : n_edge_*_active >= 1 AND |dist| <= 0.10%.
    """
    out.append("=" * 70)
    out.append("  TEST 36 — EDGE RETEST OUTCOMES (zones imbalance ICT)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["fut_r3"] = df["close"].shift(-3) - df["close"]
        df["fut_r5"] = df["close"].shift(-5) - df["close"]
        df["fut_r10"] = df["close"].shift(-10) - df["close"]
        # EDGE SELL retest (resistance) : SHORT potential, fut_r5 < 0 expected
        if "dist_edge_sell_nearest_pct" in df.columns and "n_edge_sell_active" in df.columns:
            mask = (df["n_edge_sell_active"] >= 1) & (df["dist_edge_sell_nearest_pct"].abs() <= 0.10)
            sub = df[mask]
            n = len(sub)
            if n >= 5:
                fut3 = sub["fut_r3"].dropna()
                fut5 = sub["fut_r5"].dropna()
                fut10 = sub["fut_r10"].dropna()
                wr_short_5 = (fut5 < 0).mean() if len(fut5) > 0 else 0
                out.append(f"  EDGE SELL retest (SHORT pot): n={n}")
                out.append(f"    fut_r3 mean={fut3.mean():+.2f} med={fut3.median():+.2f}")
                out.append(f"    fut_r5 mean={fut5.mean():+.2f} med={fut5.median():+.2f}  WR_SHORT={wr_short_5*100:.0f}%")
                out.append(f"    fut_r10 mean={fut10.mean():+.2f} med={fut10.median():+.2f}")
        # EDGE BUY retest (support) : LONG potential
        if "dist_edge_buy_nearest_pct" in df.columns and "n_edge_buy_active" in df.columns:
            mask = (df["n_edge_buy_active"] >= 1) & (df["dist_edge_buy_nearest_pct"].abs() <= 0.10)
            sub = df[mask]
            n = len(sub)
            if n >= 5:
                fut3 = sub["fut_r3"].dropna()
                fut5 = sub["fut_r5"].dropna()
                fut10 = sub["fut_r10"].dropna()
                wr_long_5 = (fut5 > 0).mean() if len(fut5) > 0 else 0
                out.append(f"  EDGE BUY retest (LONG pot)  : n={n}")
                out.append(f"    fut_r3 mean={fut3.mean():+.2f} med={fut3.median():+.2f}")
                out.append(f"    fut_r5 mean={fut5.mean():+.2f} med={fut5.median():+.2f}  WR_LONG={wr_long_5*100:.0f}%")
                out.append(f"    fut_r10 mean={fut10.mean():+.2f} med={fut10.median():+.2f}")
        # bar_edge_*_fire (creation zone) outcomes
        for col in ["bar_edge_sell_fire", "bar_edge_buy_fire"]:
            if col not in df.columns: continue
            mask = df[col] == 1
            sub = df[mask]
            n = len(sub)
            if n >= 5:
                f5 = sub["fut_r5"].dropna()
                wr_dir = (f5 < 0).mean() if "sell" in col else (f5 > 0).mean()
                out.append(f"  {col} (creation zone): n={n} fut_r5_mean={f5.mean():+.2f} WR_dir={wr_dir*100:.0f}%")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# HELPER : compute fut returns once
# ═════════════════════════════════════════════════════════════════════

def _add_fut(df: pd.DataFrame) -> pd.DataFrame:
    if "close" in df.columns:
        df = df.copy()
        df["fut_r3"] = df["close"].shift(-3) - df["close"]
        df["fut_r5"] = df["close"].shift(-5) - df["close"]
        df["fut_r10"] = df["close"].shift(-10) - df["close"]
    return df


def _wr_pos(series: pd.Series) -> float:
    s = series.dropna()
    return (s > 0).mean() if len(s) > 0 else 0


def _print_signal_outcome(out, name, sub_df, fut_col="fut_r5"):
    if len(sub_df) < 5 or fut_col not in sub_df.columns:
        return
    n = len(sub_df)
    fut = sub_df[fut_col].dropna()
    if len(fut) < 5: return
    out.append(f"    {name:35s}: n={n:>5d} fut_med={fut.median():+.2f} mean={fut.mean():+.2f} WR>0={_wr_pos(fut)*100:.0f}%")


# ═════════════════════════════════════════════════════════════════════
# TEST 17 — VWAP W/M SD BANDS (touches outcomes weekly/monthly)
# ═════════════════════════════════════════════════════════════════════

def test_vwap_wm_bands(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 17 — VWAP W/M SD BANDS (touches outcomes)")
    out.append("=" * 70)
    out.append("")
    bands = ["dist_vwap_w_sd1u_pct", "dist_vwap_w_sd1d_pct",
             "dist_vwap_w_sd2u_pct", "dist_vwap_w_sd2d_pct",
             "dist_vwap_m_sd1u_pct", "dist_vwap_m_sd1d_pct",
             "dist_vwap_m_sd2u_pct", "dist_vwap_m_sd2d_pct"]
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        any_present = False
        for b in bands:
            if b not in df.columns: continue
            any_present = True
            mask = df[b].abs() <= 0.05  # touch tolerance 5bps
            sub = df[mask]
            _print_signal_outcome(out, b, sub)
        if not any_present:
            out.append(f"    Aucune VWAP W/M SD band presente (V4 ancien sans Phase 11)")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 18 — MULTI-SESSION LEVELS (asia_*, london_*)
# ═════════════════════════════════════════════════════════════════════

def test_multi_session(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 18 — MULTI-SESSION LEVELS (Asia/London carry-over)")
    out.append("=" * 70)
    out.append("")
    levels = ["dist_asia_high_pct", "dist_asia_low_pct",
              "dist_london_high_pct", "dist_london_low_pct",
              "dist_london_open_pct"]
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for lvl in levels:
            if lvl not in df.columns: continue
            mask = df[lvl].abs() <= 0.05
            sub = df[mask]
            _print_signal_outcome(out, lvl, sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 19 — NAKED POC MAGNETISM
# ═════════════════════════════════════════════════════════════════════

def test_naked_poc(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 19 — NAKED POC MAGNETISM (touches + age effects)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["n_naked_poc_within_0_5pct", "n_naked_poc_active",
                     "dist_naked_poc_nearest_pct", "naked_poc_age_max_days"]:
            if col not in df.columns: continue
            vals = df[col].dropna()
            if len(vals) < 50: continue
            out.append(f"  {col}:")
            out.append(f"    notna={vals.notna().mean()*100:.0f}% median={vals.median():.2f} p75={vals.quantile(0.75):.2f}")
            if "dist_naked_poc" in col:
                # Touches outcomes
                mask = df[col].abs() <= 0.05
                sub = df[mask]
                _print_signal_outcome(out, "TOUCH naked_poc", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 20 — PRE-NEWS WINDOWS (volatility around news events)
# ═════════════════════════════════════════════════════════════════════

def test_news_windows(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 20 — PRE-NEWS WINDOWS (volatility/WR pre/post news)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        news_cols = [c for c in df.columns if c.startswith(("within_news_", "is_news_"))]
        for nc in news_cols[:8]:  # limit print
            mask = df[nc] == 1
            sub = df[mask]
            if len(sub) < 5: continue
            _print_signal_outcome(out, nc, sub)
        if "mins_to_next_news" in df.columns:
            ms = df["mins_to_next_news"].dropna()
            if len(ms) > 50:
                out.append(f"  mins_to_next_news distribution :")
                out.append(f"    notna={ms.notna().mean()*100:.0f}% median={ms.median():.0f}min p25={ms.quantile(0.25):.0f}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 21 — BARS-SINCE EVENTS (recency impact)
# ═════════════════════════════════════════════════════════════════════

def test_bars_since(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 21 — BARS-SINCE EVENTS (recency -> outcome)")
    out.append("=" * 70)
    out.append("")
    cols = [c for c in ["bars_since_last_swing_high", "bars_since_last_swing_low",
                         "bars_since_roll", "bars_since_retest_high", "bars_since_retest_low"]]
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in cols:
            if col not in df.columns: continue
            vals = df[col].dropna()
            if len(vals) < 100: continue
            # Bins recency
            for thr in [5, 10, 30]:
                sub = df[df[col] <= thr]
                _print_signal_outcome(out, f"{col}<={thr}", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 22 — EDGE ZONES & COLOR ZONES
# ═════════════════════════════════════════════════════════════════════

def test_edge_color_zones(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 22 — EDGE ZONES & COLOR ZONES")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["bar_edge_buy_fire", "bar_edge_sell_fire"]:
            if col not in df.columns: continue
            mask = df[col] == 1
            sub = df[mask]
            _print_signal_outcome(out, col, sub)
        for col in ["dist_edge_buy_nearest_pct", "dist_edge_sell_nearest_pct",
                     "dist_color_up_nearest_pct", "dist_color_dn_nearest_pct"]:
            if col not in df.columns: continue
            mask = df[col].abs() <= 0.05
            sub = df[mask]
            _print_signal_outcome(out, "TOUCH " + col, sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 23 — DELTA DIVERGENCE ZONES
# ═════════════════════════════════════════════════════════════════════

def test_delta_div_zones(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 23 — DELTA DIVERGENCE ZONES")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["delta_div_buy", "delta_div_sell"]:
            if col not in df.columns: continue
            mask = df[col] == 1
            sub = df[mask]
            _print_signal_outcome(out, col, sub)
        for col in ["dist_delta_div_buy_nearest_pct", "dist_delta_div_sell_nearest_pct"]:
            if col not in df.columns: continue
            mask = df[col].abs() <= 0.05
            sub = df[mask]
            _print_signal_outcome(out, "TOUCH " + col, sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 24 — BIG ORDERS MULTI-TIER (n_big_t1/t2/t3/t4 -> outcomes)
# ═════════════════════════════════════════════════════════════════════

def test_big_orders_multi_tier(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 24 — BIG ORDERS MULTI-TIER")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for tier in [1, 2, 3, 4]:
            for side in ["buy", "sell"]:
                col = f"n_big_{side}_t{tier}"
                if col not in df.columns: continue
                mask = df[col] >= 1
                sub = df[mask]
                if len(sub) >= 5:
                    _print_signal_outcome(out, col + ">=1", sub)
        if "max_big_ask_vol_in_bar" in df.columns:
            vals = df["max_big_ask_vol_in_bar"].dropna()
            if len(vals) > 100:
                p95 = vals.quantile(0.95)
                if p95 > 0:
                    sub = df[df["max_big_ask_vol_in_bar"] >= p95]
                    _print_signal_outcome(out, "max_big_ask_vol p95", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 25 — REGIME CONFIDENCE CALIBRATION
# ═════════════════════════════════════════════════════════════════════

def test_regime_confidence(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 25 — REGIME CONFIDENCE CALIBRATION")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        if "regime_confidence" not in df.columns:
            out.append("    regime_confidence absent — skip")
            continue
        # Quantiles
        for lo, hi in [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]:
            mask = (df["regime_confidence"] >= lo) & (df["regime_confidence"] < hi)
            sub = df[mask]
            _print_signal_outcome(out, f"conf [{lo:.1f}, {hi:.1f})", sub)
        if "regime_actionable" in df.columns:
            actionable_rate = df["regime_actionable"].mean() * 100
            out.append(f"  regime_actionable rate global : {actionable_rate:.1f}%")
            sub_act = df[df["regime_actionable"] == 1]
            sub_not = df[df["regime_actionable"] == 0]
            _print_signal_outcome(out, "actionable=1", sub_act)
            _print_signal_outcome(out, "actionable=0", sub_not)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 26 — TRAPPED TRADERS POSITIONING
# ═════════════════════════════════════════════════════════════════════

def test_trapped_traders(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 26 — TRAPPED TRADERS POSITIONING")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
                     "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support"]:
            if col not in df.columns: continue
            mask = df[col] == 1
            sub = df[mask]
            _print_signal_outcome(out, col, sub)
        for col in ["dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct"]:
            if col not in df.columns: continue
            mask = df[col].abs() <= 0.05
            sub = df[mask]
            _print_signal_outcome(out, "TOUCH " + col, sub)
        for col in ["n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active"]:
            if col not in df.columns: continue
            sub = df[df[col] >= 1]
            _print_signal_outcome(out, col + ">=1", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 27 — CROSS-INSTRUMENT IM_ FEATURES
# ═════════════════════════════════════════════════════════════════════

def test_cross_instrument(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 27 — CROSS-INSTRUMENT (im_*)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["im_smt_divergence", "im_open_type_agreement",
                     "im_volume_lead", "im_cross_delta_agreement_5",
                     "im_cross_delta_weighted_5"]:
            if col not in df.columns: continue
            vals = df[col].dropna()
            if len(vals) < 100: continue
            # Si binaire/categoriel
            n_unique = vals.nunique()
            if n_unique <= 5:
                for v in sorted(vals.unique()):
                    sub = df[df[col] == v]
                    if len(sub) >= 50:
                        _print_signal_outcome(out, f"{col}={v}", sub)
            else:
                # Continu : split p90 vs reste
                p90 = vals.quantile(0.90)
                sub = df[df[col].abs() >= abs(p90)]
                _print_signal_outcome(out, f"{col} extreme (p90)", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 28 — VAP / CLUSTER STATS
# ═════════════════════════════════════════════════════════════════════

def test_vap_cluster(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 28 — VAP / CLUSTER STATS")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["max_cluster_volume", "max_cluster_volume_v2",
                     "n_cluster_groups", "max_cluster_size"]:
            if col not in df.columns: continue
            vals = df[col].dropna()
            if len(vals) < 100: continue
            p90 = vals.quantile(0.90)
            sub = df[df[col] >= p90]
            _print_signal_outcome(out, f"{col} >= p90 ({p90:.0f})", sub)
        for col in ["cluster_at_high", "cluster_at_low"]:
            if col not in df.columns: continue
            sub = df[df[col] == 1]
            _print_signal_outcome(out, col, sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 29 — PROFILE CONTEXT (bars_in_va, va_pct)
# ═════════════════════════════════════════════════════════════════════

def test_profile_context(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 29 — PROFILE CONTEXT (bars_in_va etc.)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        if "bars_in_va" in df.columns:
            for thr in [10, 30, 50, 70]:
                sub = df[df["bars_in_va"] >= thr]
                _print_signal_outcome(out, f"bars_in_va >= {thr}%", sub)
        if "trend_day_probability" in df.columns:
            for lo, hi in [(0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.01)]:
                sub = df[(df["trend_day_probability"] >= lo) & (df["trend_day_probability"] < hi)]
                _print_signal_outcome(out, f"trend_day_prob [{lo:.1f},{hi:.1f})", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 30 — SPIKE ORIGINS / COLOR PERSISTENCE
# ═════════════════════════════════════════════════════════════════════

def test_spike_color(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 30 — SPIKE ORIGINS / COLOR PERSISTENCE")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["vol_spike_up", "vol_spike_dn", "spike_detected_lag3"]:
            if col not in df.columns: continue
            sub = df[df[col] == 1]
            _print_signal_outcome(out, col, sub)
        for col in ["color_up_persistence", "color_dn_persistence"]:
            if col not in df.columns: continue
            vals = df[col].dropna()
            if len(vals) < 100: continue
            p75 = vals.quantile(0.75)
            sub = df[df[col] >= p75]
            _print_signal_outcome(out, f"{col} >= p75 ({p75:.0f})", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 31 — SESSION IB & TRANSITIONS (porte du DMP TEST 15)
# ═════════════════════════════════════════════════════════════════════

def test_session_ib_transitions(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 31 — SESSION IB & TRANSITIONS")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["ib_complete", "ib_broken_up", "ib_broken_down"]:
            if col not in df.columns: continue
            sub = df[df[col] == 1]
            _print_signal_outcome(out, col, sub)
        if "ib_range_ticks" in df.columns:
            vals = df["ib_range_ticks"].dropna()
            vals = vals[vals > 0]
            if len(vals) > 50:
                out.append(f"  ib_range_ticks distribution : median={vals.median():.0f}t p75={vals.quantile(0.75):.0f}t")
        if "session_id" in df.columns:
            transitions = (df["session_id"] != df["session_id"].shift()).sum()
            out.append(f"  Transitions session_id : {transitions}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 32 — PREV RETURNS / AUTOCORR (porte DMP)
# ═════════════════════════════════════════════════════════════════════

def test_prev_returns(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 32 — PREV RETURNS / AUTOCORRELATIONS")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty or "close" not in df.columns: continue
        out.append(f"\n  --- {sym} ---")
        df = df.copy()
        df["ret_1"] = df["close"].diff(1)
        df["ret_3"] = df["close"].diff(3)
        df["ret_5"] = df["close"].diff(5)
        df["fut_r3"] = df["close"].shift(-3) - df["close"]
        df["fut_r5"] = df["close"].shift(-5) - df["close"]
        # Autocorr lag 1
        for lag, ret_col in [(1, "ret_1"), (3, "ret_3"), (5, "ret_5")]:
            sub = df[[ret_col, "fut_r3"]].dropna()
            if len(sub) < 200: continue
            r = sub[ret_col].corr(sub["fut_r3"])
            out.append(f"    autocorr ret_{lag} -> fut_r3 : r={r:+.3f} (n={len(sub)})")
            r5_sub = df[[ret_col, "fut_r5"]].dropna()
            if len(r5_sub) > 200:
                r5 = r5_sub[ret_col].corr(r5_sub["fut_r5"])
                out.append(f"    autocorr ret_{lag} -> fut_r5 : r={r5:+.3f}")
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 33 — MARKET PROFILE ADVANCED (POC migration, VPOC stability)
# ═════════════════════════════════════════════════════════════════════

def test_market_profile_advanced(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 33 — MARKET PROFILE ADVANCED")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        for col in ["poc_position", "poc_bar_dist", "single_print_count",
                     "ctx_poc_migration_10", "ctx_vpoc_stable_3d"]:
            if col not in df.columns: continue
            vals = df[col].dropna()
            if len(vals) < 100: continue
            out.append(f"    {col:35s}: median={vals.median():+.3f} p25={vals.quantile(0.25):+.3f} p75={vals.quantile(0.75):+.3f}")
        if "poc_position" in df.columns:
            for lo, hi in [(0, 0.3), (0.3, 0.7), (0.7, 1.01)]:
                sub = df[(df["poc_position"] >= lo) & (df["poc_position"] < hi)]
                _print_signal_outcome(out, f"poc_pos [{lo:.1f},{hi:.1f})", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 34 — AMD POWER OF 3 (porte DMP)
# ═════════════════════════════════════════════════════════════════════

def test_amd_power3(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 34 — AMD POWER OF 3 (Asia/London/RTH)")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        amd_cols = [c for c in df.columns if c.startswith("amd_")]
        if not amd_cols:
            out.append("    Aucune colonne amd_* — skip")
            continue
        out.append(f"  Colonnes amd_* presentes : {len(amd_cols)}")
        for col in amd_cols[:8]:
            vals = df[col].dropna()
            if len(vals) < 100: continue
            n_unique = vals.nunique()
            if n_unique <= 5:
                for v in sorted(vals.unique()):
                    sub = df[df[col] == v]
                    if len(sub) >= 50:
                        _print_signal_outcome(out, f"{col}={v}", sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# TEST 35 — DOUBLE TOP / DOUBLE BOTTOM PATTERNS (porte DMP)
# ═════════════════════════════════════════════════════════════════════

def test_double_top_bottom(data: dict, out: list):
    out.append("=" * 70)
    out.append("  TEST 35 — DOUBLE TOP / DOUBLE BOTTOM")
    out.append("=" * 70)
    out.append("")
    for sym, df in data.items():
        if df.empty: continue
        out.append(f"\n  --- {sym} ---")
        df = _add_fut(df)
        # Detection rough double top : 2 swing highs proches dans 20 bars
        if "new_swing_high" in df.columns and "new_swing_low" in df.columns:
            n_sw_high = (df["new_swing_high"] == 1).sum()
            n_sw_low = (df["new_swing_low"] == 1).sum()
            out.append(f"    new_swing_high : {n_sw_high} ({n_sw_high/len(df)*100:.1f}%)")
            out.append(f"    new_swing_low  : {n_sw_low} ({n_sw_low/len(df)*100:.1f}%)")
        # retest counts
        for col in ["retest_high_count", "retest_low_count"]:
            if col not in df.columns: continue
            sub = df[df[col] >= 2]
            _print_signal_outcome(out, f"{col}>=2 (double touch)", sub)
        # Ratio fwd1 / current : detect color flip
        for col in ["bn_color_up_2_fwd1", "bn_color_dn_2_fwd1"]:
            if col not in df.columns: continue
            sub = df[df[col] == 1]
            if len(sub) >= 5:
                _print_signal_outcome(out, col, sub)
    out.append("")


# ═════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default=None, help="Filtre YYYY-MM")
    ap.add_argument("--symbol", default=None, help="Filtre ES ou NQ")
    ap.add_argument("--days", type=int, default=None, help="Limite N derniers jours")
    args = ap.parse_args()

    print(f"=== MIA BENCH V4 — {datetime.now().isoformat()[:19]} ===\n")
    discovered = discover_v4(args.month, args.symbol)
    if not discovered:
        print("Aucun parquet V4 trouve.")
        return 1
    print(f"Parquets trouves :")
    for sym, parts in discovered.items():
        print(f"  {sym}: {len(parts)} mois")
        for p in parts:
            print(f"    {p['month_str']} ({p['size_mb']:.1f} MB)")

    print(f"\nLoading data...")
    data = {}
    for sym, parts in discovered.items():
        data[sym] = load_v4(sym, parts, days=args.days)
        print(f"  {sym}: {len(data[sym])} bars chargees")

    out = []
    out.append(f"MIA BENCH V4 REPORT — {datetime.now().isoformat()[:19]}")
    out.append(f"Schema version: {SCHEMA_VERSION_V4}")
    out.append(f"Filter: month={args.month or 'ALL'} symbol={args.symbol or 'ALL'} days={args.days or 'ALL'}")
    out.append("")

    # Tests 1-16 (data quality, features, predictive power)
    test_schema(data, out)
    test_inventory(data, out)
    test_coverage(data, out)
    test_quality(data, out)
    test_symmetry(data, out)
    test_health(data, out)
    test_stationarity(data, out)
    test_ranking(data, out)
    test_game_changers(data, out)
    test_regime_split(data, out)
    test_thresholds(data, out)
    test_session_timing(data, out)
    test_wall_tracker(data, out)
    test_signal_vs_bruit(data, out)
    test_verdict(data, out)
    test_rvol_databento(data, out)
    # Tests 17-30 (V4-only features deep dives)
    test_vwap_wm_bands(data, out)
    test_multi_session(data, out)
    test_naked_poc(data, out)
    test_news_windows(data, out)
    test_bars_since(data, out)
    test_edge_color_zones(data, out)
    test_delta_div_zones(data, out)
    test_big_orders_multi_tier(data, out)
    test_regime_confidence(data, out)
    test_trapped_traders(data, out)
    test_cross_instrument(data, out)
    test_vap_cluster(data, out)
    test_profile_context(data, out)
    test_spike_color(data, out)
    # Tests 31-35 (portes du bench DMP)
    test_session_ib_transitions(data, out)
    test_prev_returns(data, out)
    test_market_profile_advanced(data, out)
    test_amd_power3(data, out)
    test_double_top_bottom(data, out)
    # Test 36 (NEW 06/05) — EDGE RETEST setup ICT
    test_edge_retest(data, out)

    # Test 37 (NEW 06/05) — LONG/COLOR RETEST Extension Lines Jackson trading manuel
    test_long_color_retest(data, out)

    out.append("=" * 70)
    out.append("  END BENCH V4 — 36 tests executes")
    out.append("=" * 70)

    report = "\n".join(out)
    print(report)
    out_file = ROOT / "DATA" / f"MIA_BENCH_V4_REPORT_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    out_file.write_text(report, encoding="utf-8")
    print(f"\nRapport sauve : {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
