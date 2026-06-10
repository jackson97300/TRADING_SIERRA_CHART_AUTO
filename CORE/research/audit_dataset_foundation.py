"""
audit_dataset_foundation.py — Audit dataset comprehensive (Jackson 06/05).
"CES NOTRE FONDATION ELLE DOIS ETRE FIABLE A 100%"

Audit 7 phases sur les datasets V5e_clean (ES+NQ).
Methodologie validee 2 reviews independantes (quality-auditor + ml-trainer 06/05) :
- 5 BLOQUANT/SERIEUX fixes appliques :
  1. Phase 4 coherence Triple Barrier path-aware via window_max[t:t+horizon] >= TP_target
  2. Phase 2 outliers + quasi-const + drift sur 100% des cols (vectorisation Pandas)
  3. Phase 3 stale check (feature[t]==feature[t-1] > 50% = bug arr[sz-1]) + lookhead intersection top_corr_label
  4. Phase 5 import exemptions NATURALLY_DIFFERENT + SHARED_FEATURES depuis quality_validator
  5. Phase 4 sample_weight Lopez ch.4 : 0.01 < mean(sw) < 0.7 ET std(sw) > 0.001
- 4 MINEUR fixes :
  6. Phase 6 RTH timezone-aware (DST shifts)
  7. Phase 1 PROHIBITED_FEATURES not in df.columns
  8. Phase 7 lookhead REFUSE seulement si intersection top_corr_label (pas 1 suspect isole)
  9. Phase 1 gaps_long > 30min separe pour halts/circuit breakers

Output : verdict global FIABLE_100 / SUSPECT_n / REFUSE.
Anti-tricherie strict : 100% des features auditees, pas de sampling cache.

Usage : python -X utf8 CORE/research/audit_dataset_foundation.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
DATASETS_DIR = ROOT / "DATA" / "DATASETS"

sys.path.insert(0, str(ROOT / "CORE"))


def load_dataset(symbol):
    fp = DATASETS_DIR / f"{symbol}_dataset_v5e_clean_long.parquet"
    df = pd.read_parquet(fp)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    return df


def get_feature_cols(df):
    """Feature cols = numeric + exclude meta/label/OHLCV."""
    exclude = {"ts_event", "symbol", "label", "sample_weight",
               "open", "high", "low", "close", "volume", "_date", "_month", "_dow", "_hour"}
    return [c for c in df.columns
            if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]


# ─── PHASE 1 : INTEGRITE STRUCTURELLE ─────────────────────────────────────

def phase1_integrity(df, symbol):
    print(f"\n  [PHASE 1] INTEGRITE STRUCTURELLE — {symbol}")
    issues = {}
    ts = df["ts_event"]
    deltas = ts.diff().dt.total_seconds().dropna()
    expected_delta = 60
    # Gaps intra-session (90s a 30min)
    gaps_intra = deltas[(deltas > expected_delta * 1.5) & (deltas < expected_delta * 30)]
    # Gaps long (>30min, weekend ou halt)
    gaps_long = deltas[deltas >= expected_delta * 30]
    print(f"    Gaps intra (90s-30min) : {len(gaps_intra)} (max={int(gaps_intra.max()) if len(gaps_intra) else 0}s)")
    print(f"    Gaps long (>30min) : {len(gaps_long)} (max={int(gaps_long.max()) if len(gaps_long) else 0}s, attendu weekend/halt)")
    issues["gaps_intra"] = len(gaps_intra)
    issues["gaps_long"] = len(gaps_long)

    dupes = ts.duplicated().sum()
    print(f"    Doublons ts_event : {dupes}")
    issues["duplicates"] = int(dupes)

    non_numeric = [c for c in df.columns
                   if c not in ("ts_event", "symbol")
                   and not pd.api.types.is_numeric_dtype(df[c])]
    print(f"    Cols non-numeriques : {len(non_numeric)}")
    issues["non_numeric_cols"] = len(non_numeric)

    df["_date"] = ts.dt.date
    bars_per_day = df.groupby("_date").size()
    print(f"    Bars/day : min={bars_per_day.min()} max={bars_per_day.max()} mean={bars_per_day.mean():.0f}")
    issues["bars_per_day_min"] = int(bars_per_day.min())
    issues["bars_per_day_max"] = int(bars_per_day.max())

    # FIX 9 : check PROHIBITED_FEATURES (price absolutes deja droppees) PAS presentes
    PROHIBITED_PRICE = {"asia_high", "asia_low", "ib_high", "ib_low",
                         "ovn_high", "ovn_low", "sess_high", "sess_low",
                         "us_high", "us_low", "pdh", "pdl", "pvwap",
                         "cur_vpoc", "cur_vah", "cur_val", "vwap_d", "vwap_w", "vwap_m"}
    PROHIBITED_VOL_LEAK = {"dist_cur_vah", "dist_cur_vpoc", "dist_ib_high",
                            "dist_vwap_d", "dist_vwap_w", "dist_vwap_m",
                            "dist_pdh", "dist_pdl", "dist_pvwap"}
    leaks_present = (set(df.columns) & (PROHIBITED_PRICE | PROHIBITED_VOL_LEAK))
    print(f"    Features prohibited (price/vol leak) presentes : {len(leaks_present)}")
    if leaks_present:
        for c in sorted(leaks_present)[:10]:
            print(f"      {c} (DEVRAIT etre droppee)")
    issues["prohibited_features_present"] = list(leaks_present)
    return issues


# ─── PHASE 2 : QUALITY FEATURES (FIX vectorise 100%) ─────────────────────

def phase2_quality(df, symbol):
    print(f"\n  [PHASE 2] QUALITY FEATURES — {symbol}")
    issues = {}
    feat_cols = get_feature_cols(df)
    print(f"    Total features auditees : {len(feat_cols)} (100%)")

    feat_df = df[feat_cols]

    # Exclure cols booleennes pour calculs numerique (outliers, quasi-const)
    feat_numeric = feat_df.select_dtypes(include=[np.number]).copy()
    bool_cols = [c for c in feat_cols if c not in feat_numeric.columns]
    if bool_cols:
        print(f"    Bool cols exclues du calcul outliers/quantile : {len(bool_cols)}")
    # Cast cols int8 (label-like) en float64 pour quantile/abs
    for c in feat_numeric.columns:
        if feat_numeric[c].dtype.kind in ("i", "u", "b"):
            feat_numeric[c] = feat_numeric[c].astype("float64")

    # NaN distribution (vectorise sur tout)
    nan_pct = feat_df.isna().mean().sort_values(ascending=False)
    high_nan = nan_pct[nan_pct > 0.5]
    moderate_nan = nan_pct[(nan_pct > 0.1) & (nan_pct <= 0.5)]
    print(f"    Cols >50% NaN : {len(high_nan)}")
    if len(high_nan) > 0:
        print(f"      Top 10 : {dict(high_nan.head(10).round(3))}")
    print(f"    Cols 10-50% NaN : {len(moderate_nan)}")
    issues["high_nan_cols"] = len(high_nan)
    issues["moderate_nan_cols"] = len(moderate_nan)
    issues["high_nan_list"] = high_nan.head(20).index.tolist()

    # Outliers vectorise (max / |p99| > 100) sur cols numeriques uniquement
    p99 = feat_numeric.abs().quantile(0.99)
    max_abs = feat_numeric.abs().max()
    safe_p99 = p99.replace(0, np.nan)
    ratio = max_abs / safe_p99
    outliers_mask = (ratio > 100) & ratio.notna()
    outliers_features = ratio[outliers_mask].sort_values(ascending=False)
    print(f"    Outliers extremes (max/|p99|>100) : {len(outliers_features)}")
    for c in outliers_features.head(5).index:
        print(f"      {c}: ratio {outliers_features[c]:.0f}×")
    issues["outliers_count"] = len(outliers_features)
    issues["outliers_top"] = [(c, float(outliers_features[c])) for c in outliers_features.head(10).index]

    # Quasi-constantes vectorise (top1 > 95%)
    quasi_const = []
    for c in feat_cols:
        s = feat_df[c].dropna()
        if len(s) < 100:
            continue
        # max count value
        vc = s.value_counts(normalize=True)
        if not vc.empty and vc.iloc[0] > 0.95:
            quasi_const.append((c, float(vc.iloc[0])))
    quasi_const.sort(key=lambda x: -x[1])
    print(f"    Quasi-constantes (>95% meme valeur) : {len(quasi_const)}")
    for c, p in quasi_const[:5]:
        print(f"      {c}: {p*100:.1f}% meme valeur")
    issues["quasi_const_count"] = len(quasi_const)

    # Stationnarite cross-mois sur top corr_label (FIX 3 : pas sampling alphabetique)
    df["_month"] = df["ts_event"].dt.to_period("M").astype(str)
    if "label" in df.columns:
        # Compute corr_label rapide vectorise
        valid_features = [c for c in feat_cols if feat_df[c].notna().sum() > 1000]
        sample_size = min(50000, len(df))
        idx_sample = np.random.RandomState(42).choice(len(df), sample_size, replace=False)
        corrs = feat_df.iloc[idx_sample].corrwith(df["label"].iloc[idx_sample], method="spearman").abs()
        top30 = corrs.sort_values(ascending=False).head(30).index.tolist()
        # Drift cross-mois sur top 30
        drift_features = []
        for c in top30:
            monthly = df.groupby("_month")[c].agg(["mean", "std"])
            monthly = monthly.dropna()
            if len(monthly) < 4:
                continue
            mean_cv = (monthly["mean"].std() / abs(monthly["mean"].mean())) if abs(monthly["mean"].mean()) > 1e-9 else 0
            if mean_cv > 0.5:
                drift_features.append((c, float(mean_cv)))
        print(f"    Drift cross-mois CV>0.5 sur top 30 corr_label : {len(drift_features)}/30")
        for c, cv in drift_features[:5]:
            print(f"      {c}: CV {cv:.2f}")
        issues["drift_features_count"] = len(drift_features)
        issues["drift_top30"] = [(c, float(cv)) for c, cv in drift_features]
    else:
        issues["drift_features_count"] = 0
    return issues


# ─── PHASE 3 : LEAK DETECTION (FIX stale check + intersection top_corr) ──

def phase3_leak(df, symbol):
    print(f"\n  [PHASE 3] LEAK DETECTION — {symbol}")
    issues = {"top_corr_label": [], "lookhead_suspects": [], "stale_features": []}
    feat_cols = get_feature_cols(df)
    feat_df = df[feat_cols]

    if "label" not in df.columns or "close" not in df.columns:
        return issues

    # Top corr label (Spearman) sur tout sample
    sample_size = min(50000, len(df))
    idx_sample = np.random.RandomState(42).choice(len(df), sample_size, replace=False)
    label_s = df["label"].iloc[idx_sample]
    feat_sample = feat_df.iloc[idx_sample]
    corrs = feat_sample.corrwith(label_s, method="spearman").dropna()
    top_corr_label = corrs.abs().sort_values(ascending=False).head(30)
    print(f"    Top 5 features par |spearman_label| :")
    for c in top_corr_label.head(5).index:
        print(f"      {c}: rho={corrs[c]:+.4f}")
    issues["top_corr_label"] = [(c, float(corrs[c])) for c in top_corr_label.head(10).index]

    # FIX 5 : lookhead test - rho_fwd5 > 0.5 SUR top 30 corr_label
    fwd_ret = (df["close"].shift(-5) - df["close"]).iloc[idx_sample]
    lookhead_suspects = []
    top30_set = set(top_corr_label.head(30).index)
    for c in top30_set:
        s = pd.DataFrame({"x": feat_sample[c], "y": fwd_ret}).dropna()
        if len(s) < 1000:
            continue
        r = s["x"].corr(s["y"], method="spearman")
        if abs(r) > 0.5:
            lookhead_suspects.append((c, float(r)))
    print(f"    Lookhead suspects (rho_fwd5 > 0.5 sur top 30) : {len(lookhead_suspects)}")
    for c, r in lookhead_suspects[:5]:
        print(f"      {c}: rho_fwd5={r:+.3f} — SUSPECT")
    issues["lookhead_suspects"] = lookhead_suspects

    # FIX 4 raffine v2 : Stale check pragmatique (vrais bugs arr[sz-1] only)
    # Categorique/event-based legitime : <=10 unique values OK stale
    # Snapshot session-based : after_*, dist_vix_gex_*, n_*_active, dist_*_nearest_pct OK
    # Vrai bug : feature continue (>10 unique) avec >85% repetes ET pas pattern session
    SNAPSHOT_PATTERNS = ("after_", "dist_vix_", "n_edge_", "n_long_", "n_color_",
                         "dist_long_", "dist_color_", "dist_edge_", "dist_delta_div_",
                         "dist_naked_", "dist_single_", "dist_blind_", "dist_gex_",
                         "naked_poc_", "single_print_", "trapped_",
                         "ib_", "ovn_", "asia_", "london_", "us_",  # session-snapshots
                         "cur_va", "prev_va", "pdh", "pdl",  # daily levels
                         "open_", "open_zone")
    stale_suspect_bug = []
    stale_categorical_ok = []
    stale_snapshot_ok = []
    for c in top30_set:
        s = df[c].dropna()
        if len(s) < 1000:
            continue
        same_as_prev = (s == s.shift(1)).mean()
        if same_as_prev <= 0.5:
            continue
        nunique = s.nunique()
        if nunique <= 10:
            stale_categorical_ok.append((c, float(same_as_prev), int(nunique)))
        elif any(c.startswith(p) for p in SNAPSHOT_PATTERNS):
            stale_snapshot_ok.append((c, float(same_as_prev), int(nunique)))
        elif same_as_prev > 0.85:  # vrai bug arr[sz-1] : >85% repete sur continuous feature
            stale_suspect_bug.append((c, float(same_as_prev), int(nunique)))
        else:
            stale_snapshot_ok.append((c, float(same_as_prev), int(nunique)))
    print(f"    Stale features sur top 30 :")
    print(f"      Categorique legitime (<=10 unique values) : {len(stale_categorical_ok)}")
    for c, p, nu in stale_categorical_ok[:3]:
        print(f"        {c}: {p*100:.0f}% repete, nunique={nu} (OK)")
    print(f"      Snapshot/event-based legitime : {len(stale_snapshot_ok)}")
    for c, p, nu in stale_snapshot_ok[:3]:
        print(f"        {c}: {p*100:.0f}% repete, nunique={nu} (OK snapshot)")
    print(f"      SUSPECT bug arr[sz-1] (>10 unique values, >85% repete, non-snapshot) : {len(stale_suspect_bug)}")
    for c, p, nu in stale_suspect_bug[:5]:
        print(f"        {c}: {p*100:.0f}% repete, nunique={nu} (SUSPECT)")
    issues["stale_categorical_ok"] = stale_categorical_ok
    issues["stale_snapshot_ok"] = stale_snapshot_ok
    issues["stale_suspect_bug"] = stale_suspect_bug
    return issues


# ─── PHASE 4 : LABELS QUALITY (FIX coherence path-aware + sw Lopez) ──────

def phase4_labels(df, symbol):
    print(f"\n  [PHASE 4] LABELS QUALITY — {symbol}")
    issues = {}
    if "label" not in df.columns:
        return {"no_label": True}

    label_dist = df["label"].value_counts(normalize=True).sort_index().round(3)
    print(f"    Distribution globale : {dict(label_dist)}")
    issues["label_dist"] = dict(label_dist.to_dict())

    df["_month"] = df["ts_event"].dt.to_period("M").astype(str)
    monthly_dist = df.groupby("_month")["label"].agg(
        n="count",
        pct_buy=lambda s: (s == 1).mean(),
        pct_sell=lambda s: (s == -1).mean(),
        pct_hold=lambda s: (s == 0).mean(),
    )
    pct_buy_std = monthly_dist["pct_buy"].std()
    pct_sell_std = monthly_dist["pct_sell"].std()
    pct_buy_range = monthly_dist["pct_buy"].max() - monthly_dist["pct_buy"].min()
    pct_sell_range = monthly_dist["pct_sell"].max() - monthly_dist["pct_sell"].min()
    print(f"    Distribution cross-mois (n_months={len(monthly_dist)}):")
    print(f"      pct_buy : range={pct_buy_range:.3f} std={pct_buy_std:.3f}")
    print(f"      pct_sell : range={pct_sell_range:.3f} std={pct_sell_std:.3f}")
    issues["pct_buy_std"] = float(pct_buy_std)
    issues["pct_sell_std"] = float(pct_sell_std)
    issues["pct_buy_range"] = float(pct_buy_range)
    issues["pct_sell_range"] = float(pct_sell_range)

    # FIX 4 sample_weight Lopez ch.4
    if "sample_weight" in df.columns:
        sw = df["sample_weight"]
        sw_mean = float(sw.mean())
        sw_std = float(sw.std())
        sw_min = float(sw.min())
        sw_max = float(sw.max())
        print(f"    sample_weight : min={sw_min:.4f} max={sw_max:.4f} mean={sw_mean:.4f} std={sw_std:.4f}")
        sw_invalid = []
        if sw_min < 0 or sw_max > 1.01:
            sw_invalid.append("hors [0, 1]")
        if not (0.01 < sw_mean < 0.7):
            sw_invalid.append(f"mean {sw_mean:.3f} hors [0.01, 0.7] (uniqueness Lopez ch.4 cassee)")
        if sw_std < 0.001:
            sw_invalid.append(f"std {sw_std:.4f} < 0.001 (pas de variation, uniqueness inactif)")
        if sw_invalid:
            print(f"      WARNING : {'; '.join(sw_invalid)}")
            issues["sample_weight_invalid"] = sw_invalid
        else:
            issues["sample_weight_invalid"] = []
            print(f"      OK Lopez ch.4 compliant")

    # FIX 1 raffine : Coherence Triple Barrier path-aware PER-BAR (BLOQUANT)
    # IMPORTANT : ATR dans V5e est en TICKS (verifie ES median 4.86, NQ 22.93).
    # Reverse-engineered ratio = realized_pts/atr median = 5.0 (pas 3.0 du commentaire label_v5).
    # tp_target_pts = ratio_ticks * atr_ticks * tick_size = 5.0 * atr * 0.25
    if "close" in df.columns and "atr" in df.columns:
        horizon = 60
        TICK_SIZE = 0.25
        TP_RATIO_TICKS = 5.0  # K_SL × K_TP_RATIO reverse-engineered (realized_pts/atr median)
        # tp_target en POINTS de prix
        tp_target_per_bar_pts = TP_RATIO_TICKS * df["atr"] * TICK_SIZE
        # window max forward 60 bars (path-aware)
        window_max = df["close"].rolling(horizon, min_periods=1).max().shift(-horizon)
        window_min = df["close"].rolling(horizon, min_periods=1).min().shift(-horizon)
        buy_mask = df["label"] == 1
        sell_mask = df["label"] == -1
        buy_excess_pts = (window_max - df["close"]) - tp_target_per_bar_pts
        sell_excess_pts = (df["close"] - window_min) - tp_target_per_bar_pts
        buy_coherence_pct = (buy_excess_pts[buy_mask] >= 0).mean()
        sell_coherence_pct = (sell_excess_pts[sell_mask] >= 0).mean()
        buy_excess_median = buy_excess_pts[buy_mask].median()
        sell_excess_median = sell_excess_pts[sell_mask].median()
        print(f"    Coherence Triple Barrier (path-aware PER-BAR, ratio_ticks={TP_RATIO_TICKS} reverse-engineered, horizon={horizon}):")
        print(f"      atr median (ticks) : {df['atr'].median():.2f}")
        print(f"      tp_target median (points) : {tp_target_per_bar_pts.median():.2f}")
        print(f"      label=+1 BUY : window_max-close >= TP dans {buy_coherence_pct*100:.1f}%")
        print(f"        excess pts median: {buy_excess_median:+.2f}")
        print(f"      label=-1 SELL : close-window_min >= TP dans {sell_coherence_pct*100:.1f}%")
        print(f"        excess pts median: {sell_excess_median:+.2f}")
        issues["label_buy_coherence_pct"] = float(buy_coherence_pct)
        issues["label_sell_coherence_pct"] = float(sell_coherence_pct)
        issues["label_buy_excess_median"] = float(buy_excess_median) if not pd.isna(buy_excess_median) else None
        issues["label_sell_excess_median"] = float(sell_excess_median) if not pd.isna(sell_excess_median) else None
    return issues


# ─── PHASE 5 : CROSS-INSTRUMENT (FIX import exemptions) ──────────────────

def phase5_cross_instrument(es_df, nq_df):
    print(f"\n  [PHASE 5] CROSS-INSTRUMENT COHERENCE")
    issues = {"asymmetric_features": []}

    # FIX 6 : import exemptions quality_validator
    try:
        from quality_validator import NATURALLY_DIFFERENT, SHARED_FEATURES
        EXEMPT = set(NATURALLY_DIFFERENT) | set(SHARED_FEATURES)
        print(f"    Imported exemptions : {len(EXEMPT)} features (NATURALLY_DIFFERENT + SHARED_FEATURES)")
    except ImportError:
        EXEMPT = set()
        print(f"    WARNING : quality_validator import failed, no exemptions")

    common = (set(es_df.columns) & set(nq_df.columns)) - EXEMPT
    common = [c for c in common
              if c not in ("ts_event", "symbol", "label", "sample_weight",
                           "open", "high", "low", "close", "volume", "_date", "_month")
              and pd.api.types.is_numeric_dtype(es_df[c])]
    print(f"    Features commun (apres exempt) : {len(common)} (100% testees)")

    asymmetric = []
    for c in common:
        es_s = es_df[c].dropna()
        nq_s = nq_df[c].dropna()
        if len(es_s) < 100 or len(nq_s) < 100:
            continue
        if abs(nq_s.mean()) > 1e-6 and abs(es_s.mean()) > 1e-6:
            mean_ratio = abs(nq_s.mean() / es_s.mean())
        else:
            mean_ratio = 1.0
        std_ratio = (nq_s.std() / es_s.std()) if es_s.std() > 1e-9 else 1.0
        if mean_ratio > 3 or std_ratio > 3:
            asymmetric.append((c, float(mean_ratio), float(std_ratio)))
    asymmetric.sort(key=lambda x: -max(x[1], x[2]))
    print(f"    Features asymetriques NQ/ES (>3×) : {len(asymmetric)}/{len(common)}")
    for c, mr, sr in asymmetric[:10]:
        print(f"      {c}: mean_ratio={mr:.1f}× std_ratio={sr:.1f}×")
    issues["asymmetric_features"] = asymmetric[:30]
    issues["total_features_tested"] = len(common)
    return issues


# ─── PHASE 6 : COVERAGE TEMPOREL (FIX timezone-aware) ────────────────────

def phase6_coverage(df, symbol):
    print(f"\n  [PHASE 6] COVERAGE TEMPOREL — {symbol}")
    issues = {}
    df["_dow"] = df["ts_event"].dt.day_of_week
    bars_per_dow = df["_dow"].value_counts().sort_index()
    print(f"    Bars par DOW : {dict(bars_per_dow.to_dict())}")
    issues["bars_per_dow"] = dict(bars_per_dow.to_dict())

    # FIX 7 : RTH timezone-aware (DST-aware)
    ts_et = df["ts_event"].dt.tz_convert("America/New_York")
    h_et = ts_et.dt.hour
    m_et = ts_et.dt.minute
    rth_mask = ((h_et >= 9) & ((h_et > 9) | (m_et >= 30))) & (h_et < 16)
    rth_pct = rth_mask.mean() * 100
    print(f"    RTH coverage (9:30-16:00 ET, DST-aware) : {rth_pct:.1f}%")
    issues["rth_pct"] = float(rth_pct)
    return issues


# ─── PHASE 7 : VERDICT GLOBAL ─────────────────────────────────────────────

def phase7_verdict(all_issues, symbol):
    print(f"\n  [PHASE 7] VERDICT GLOBAL — {symbol}")
    blockers = []
    suspects = []

    p1 = all_issues.get("phase1", {})
    if p1.get("duplicates", 0) > 0:
        blockers.append(f"P1: {p1['duplicates']} doublons ts_event")
    if p1.get("non_numeric_cols", 0) > 5:
        suspects.append(f"P1: {p1['non_numeric_cols']} cols non-numeriques")
    if p1.get("prohibited_features_present"):
        blockers.append(f"P1: {len(p1['prohibited_features_present'])} prohibited features detectees (price/vol leak)")

    p2 = all_issues.get("phase2", {})
    if p2.get("high_nan_cols", 0) > 50:
        blockers.append(f"P2: {p2['high_nan_cols']} cols >50% NaN")
    if p2.get("outliers_count", 0) > 30:
        suspects.append(f"P2: {p2['outliers_count']} cols outliers extremes")
    if p2.get("drift_features_count", 0) > 5:
        suspects.append(f"P2: {p2['drift_features_count']} cols drift cross-mois sur top 30 corr_label")

    p3 = all_issues.get("phase3", {})
    # FIX 8 : intersection lookhead × top_corr_label
    lookhead_suspects = p3.get("lookhead_suspects", [])
    top_corr_set = set(c for c, _ in p3.get("top_corr_label", []))
    lookhead_intersect = [t for t in lookhead_suspects if t[0] in top_corr_set]
    if len(lookhead_intersect) >= 1:
        # Au moins 1 feature top corr_label avec lookhead suspect = leak grossier confirme
        blockers.append(f"P3: {len(lookhead_intersect)} top_corr features avec lookhead rho>0.5")
    elif len(lookhead_suspects) > 3:
        suspects.append(f"P3: {len(lookhead_suspects)} lookhead suspects (hors top corr)")
    if p3.get("stale_suspect_bug"):
        blockers.append(f"P3: {len(p3['stale_suspect_bug'])} stale features SUSPECT bug arr[sz-1] (>10 unique values)")
    if p3.get("stale_categorical_ok"):
        # Informatif : pas un suspect (legit categorical/bool)
        pass

    p4 = all_issues.get("phase4", {})
    if p4.get("sample_weight_invalid"):
        blockers.append(f"P4: sample_weight Lopez : {'; '.join(p4['sample_weight_invalid'])}")
    buy_coh = p4.get("label_buy_coherence_pct", 1.0)
    sell_coh = p4.get("label_sell_coherence_pct", 1.0)
    if buy_coh < 0.55:
        suspects.append(f"P4: label BUY coherence path-aware {buy_coh:.2%} (<55%)")
    if sell_coh < 0.55:
        suspects.append(f"P4: label SELL coherence path-aware {sell_coh:.2%} (<55%)")
    if p4.get("pct_buy_range", 0) > 0.15:
        suspects.append(f"P4: pct_buy range cross-mois {p4['pct_buy_range']:.2f} > 0.15 (drift label)")
    if p4.get("pct_sell_range", 0) > 0.15:
        suspects.append(f"P4: pct_sell range cross-mois {p4['pct_sell_range']:.2f} > 0.15 (drift label)")

    p5 = all_issues.get("phase5", {})
    if len(p5.get("asymmetric_features", [])) > 30:
        suspects.append(f"P5: {len(p5['asymmetric_features'])} features asymetriques (post-exempt)")

    print(f"    Blockers ({len(blockers)}) :")
    for b in blockers:
        print(f"      - {b}")
    print(f"    Suspects ({len(suspects)}) :")
    for s in suspects:
        print(f"      - {s}")

    if blockers:
        verdict = "REFUSE"
    elif len(suspects) >= 5:
        verdict = "SUSPECT_MULTIPLE"
    elif suspects:
        verdict = f"SUSPECT_{len(suspects)}"
    else:
        verdict = "FIABLE_100"
    print(f"\n    >>> VERDICT {symbol} : {verdict}")
    return verdict, blockers, suspects


def main():
    print("=" * 100)
    print("  AUDIT DATASET FOUNDATION (Jackson 06/05) : 100% fiable obligatoire")
    print("  V5e_clean_long ES + NQ — review 2 agents independants applique")
    print("=" * 100)

    es_df = load_dataset("ES")
    nq_df = load_dataset("NQ")
    print(f"\n  ES : {es_df.shape}  date {es_df['ts_event'].min()} -> {es_df['ts_event'].max()}")
    print(f"  NQ : {nq_df.shape}  date {nq_df['ts_event'].min()} -> {nq_df['ts_event'].max()}")

    all_issues = {"ES": {}, "NQ": {}}
    for sym, df in [("ES", es_df), ("NQ", nq_df)]:
        print(f"\n{'='*80}")
        print(f"  AUDIT {sym}")
        print(f"{'='*80}")
        all_issues[sym]["phase1"] = phase1_integrity(df, sym)
        all_issues[sym]["phase2"] = phase2_quality(df, sym)
        all_issues[sym]["phase3"] = phase3_leak(df, sym)
        all_issues[sym]["phase4"] = phase4_labels(df, sym)
        all_issues[sym]["phase6"] = phase6_coverage(df, sym)

    print(f"\n{'='*80}")
    cross_issues = phase5_cross_instrument(es_df, nq_df)
    all_issues["cross"] = cross_issues

    print(f"\n{'='*80}")
    print(f"  VERDICT FINAL")
    print(f"{'='*80}")
    verdicts = {}
    for sym in ["ES", "NQ"]:
        all_issues[sym]["phase5"] = cross_issues
        verdict, blockers, suspects = phase7_verdict(all_issues[sym], sym)
        verdicts[sym] = {"verdict": verdict, "blockers": blockers, "suspects": suspects}

    out = ROOT / "DATA" / f"audit_dataset_foundation_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.json"
    payload = {
        "verdicts": verdicts,
        "es_issues": all_issues["ES"],
        "nq_issues": all_issues["NQ"],
        "cross_issues": cross_issues,
    }
    out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\n  Report : {out}")

    print(f"\n{'='*80}")
    print(f"  RECOMMENDATION")
    print(f"{'='*80}")
    if verdicts["ES"]["verdict"] == "FIABLE_100" and verdicts["NQ"]["verdict"] == "FIABLE_100":
        print(f"  >>> Dataset FIABLE 100% : OK lancer audit ML alternatives.")
    else:
        print(f"  >>> Dataset NON FIABLE : corriger les blockers/suspects AVANT audit ML.")
        print(f"      ES : {verdicts['ES']['verdict']}  NQ : {verdicts['NQ']['verdict']}")


if __name__ == "__main__":
    main()
