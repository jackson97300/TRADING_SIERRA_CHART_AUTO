"""Live Enricher Validator — a la `CORE/dmp_validator.py` pour DMP C++.

Source : Jackson 15/05/2026 "TROUVER LA SOLUTION POUR SNAPSHOT PROPRE ET FIABLE
A LA MEGA DU C++. ON DOIS FAIRE UN FICHIER VALIDATION POUR CONTROLER.
SUR LE DMP C++ ON AVAIS FAIS BEAUCOUP D'ERREUR. APRES 3 SEMAINES DE COLLECTE
ON DOIS ETRE A L'AFFUT ET DETECTER TOUTES LES VALEUR SUSPECTES, CELLES QUI
FIRE TOUT LE TEMPS."

Reference DMP : 16 features big_orders mortes 26 jours (fix 13/04 ext_lines→VAP),
delta_div toujours 0 (fix 07/04 ext_lines), bar_color_up saturation > 95%
(retour bug pre-17/04 cf SATURATION_FEATURES dmp_validator.py:69-81).

Check les 5 criteres + extensions Live Enricher specifiques.

Usage:
  python tools/live_enricher_validator.py                    # check today all syms
  python tools/live_enricher_validator.py --date 20260515
  python tools/live_enricher_validator.py --symbol NQ.c.0
  python tools/live_enricher_validator.py --no-strict        # non-fatal (warning only)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "DATA" / "live_enriched"
V4_DIR = ROOT / "DATA" / "datasets" / "v4_enriched"


# ═══════════════════════════════════════════════════════════════════════════════
# WHITELISTS LEGITIMES (NaN attendu, ne pas flagger)
# ═══════════════════════════════════════════════════════════════════════════════

# Features 100% NaN hors session active (pre-RTH/Asia/post-close)
PRE_RTH_LEGIT_NAN = {
    # IB window (09:30-10:30 ET)
    "ib_high", "ib_low", "ib_range", "ib_range_ticks", "ib_position_pct",
    "ib_range_atr", "ib_complete",
    "dist_ib_high_pct", "dist_ib_low_pct", "dist_ib_high", "dist_ib_low",
    "ctx_ib_extension_ratio", "ctx_ib_position_velocity",
    # Cash session (09:30-16:00 ET)
    "cash_high", "cash_low",
    "dist_cash_high_pct", "dist_cash_low_pct",
    "is_new_cash_high", "is_new_cash_low",
    "open_cash", "price_1030",
    "open_830_et", "open_930_et", "dist_open_830_pct", "dist_open_930_pct",
    "above_open_830", "above_open_930",
    # Sessions futures
    "us_high", "us_low", "dist_us_high_pct", "dist_us_low_pct",
    "after_high", "after_low", "dist_after_high_pct", "dist_after_low_pct",
    "ny_open", "dist_ny_open_pct", "above_ny_open",
    "after_open", "dist_after_open_pct", "above_after_open",
    # Asia/London openings (capture moment uniquement)
    "asia_open", "dist_asia_open_pct", "above_asia_open",
    "london_open", "dist_london_open_pct", "above_london_open",
}

# Features 0DTE legit NaN si MenthorQ ne fournit pas (NQ vendredi/Gold)
ZERO_DTE_LEGIT_NAN = {
    "mq_call_0dte", "mq_put_0dte", "vix_call_0dte", "vix_put_0dte",
    "vix_gamma_wall_0dte",
    "dist_vix_call_0dte", "dist_vix_put_0dte", "dist_vix_gamma_wall_0dte",
}

# Features R1 known (commit a46eb0e ML_EXCLUDE diag_imbalance/large_trader)
R1_KNOWN_NAN = {
    "im_ltr_slope_diff",  # large_trader_ratio absent Databento
    "diag_imbalance", "large_trader_ratio",
    "ctx_diag_imbalance_mean_5", "ctx_large_trader_slope_5",
}

# Features event-based legit NaN si event absent
EVENT_BASED_LEGIT_NAN = {
    "dist_big_ask_nearest_pct", "dist_big_bid_nearest_pct",
    "dist_cluster_nearest_up_pct", "dist_cluster_nearest_dn_pct",
    "dist_swing_high", "dist_swing_low",
    "dist_last_swing_high_pct", "dist_last_swing_low_pct",
    "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
    "dist_delta_div_buy_nearest_pct", "dist_delta_div_sell_nearest_pct",
    "div_at_key_level_ticks",
    # Overnight (session prev close-Asia open)
    "ovn_high", "ovn_low", "ovn_range_ticks",
    "dist_ovn_high_pct", "dist_ovn_low_pct",
}

# Intermarket legit NaN si partner stale
INTERMARKET_LEGIT_NAN = {
    "im_delta_day_divergence", "im_volume_lead",
}

# MGC macro features (DXY corr / yields proxy) — pas alimentes
MGC_MACRO_LEGIT_NAN = {
    "im_dxy_corr_60d", "im_real_yields_proxy",
    "mgc_asia_london_overlap_vol", "mgc_session_break_acceleration",
}

ALL_LEGIT_NAN = (
    PRE_RTH_LEGIT_NAN | ZERO_DTE_LEGIT_NAN | R1_KNOWN_NAN
    | EVENT_BASED_LEGIT_NAN | INTERMARKET_LEGIT_NAN | MGC_MACRO_LEGIT_NAN
)

# Features bool qui ne doivent JAMAIS saturer > 95% (Pattern V1 cousin DMP C++)
# Reference dmp_validator.py:69-81 (bar_color_up saturation bug arr[sz-1] retour)
SATURATION_BOOL_FEATURES = {
    # Bar colors / long bars
    "long_up_bar", "long_dn_bar",
    "long_dn_up_pattern", "long_up_dn_pattern",
    # Battle Navale
    "bn_stack_ask", "bn_stack_bid",
    "bn_absorb_ask", "bn_absorb_bid",
    "bn_absorb_ask_raw", "bn_absorb_bid_raw",
    "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
    # Edge zones
    "near_resistance_level", "near_support_level",
    # Spikes
    "spike_detected_lag3",
    # Swing detection
    "swing_high_active_lag10", "swing_low_active_lag10",
    "equal_highs_detected", "equal_lows_detected",
    "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
    # Delta div
    "delta_div_buy", "delta_div_sell",
    # rvol
    "rvol_buy", "rvol_sell", "rvol_buy_strong", "rvol_sell_strong",
    "rvol_absorb_buy", "rvol_absorb_sell", "rvol_extreme",
    # Vol spike
    "vol_spike_up", "vol_spike_dn",
    "rotation_up", "rotation_dn",
    # VWAP cross
    "vwap_d_cross_up", "vwap_d_cross_dn",
    # Bool flags MQ
    "bool_above_mq_call", "bool_above_mq_hvl", "bool_gex_flip_zone",
    "vix_above_hvl", "vix_above_hvl_0dte",
    # News
    "is_news_715", "is_news_730", "is_news_830",
    "is_news_845", "is_news_900", "is_news_930",
}

SATURATION_CEILING = 0.95  # fire_rate > 95% = bug

# Snapshots daily legit constants (MQ + VIX broadcast quotidien)
CONST_SNAPSHOTS_LEGIT = {
    "mq_call", "mq_put", "mq_hvl",
    "mq_1d_max", "mq_1d_min",
    "vix_call", "vix_put", "vix_hvl",
    "vix_1d_max", "vix_1d_min",
    "vix_call_0dte", "vix_put_0dte", "vix_hvl_0dte",
    "mq_call_0dte", "mq_put_0dte", "mq_hvl_0dte",
    "vix_gex_0", "vix_gex_1", "vix_gex_2", "vix_gex_3", "vix_gex_4",
    "vix_gex_5", "vix_gex_6", "vix_gex_7", "vix_gex_8", "vix_gex_9",
    "vix_regime",
    "latency_s",  # hardcoded 60.0
    "trades_window_sec",
    # Schema fields
    "schema_version", "mq_schema_version", "instrument_id", "symbol",
    "mq_sym", "mq_trigger", "mq_snapshot_ts",
    # Bool/int events RARES legit constants si 0 sur fenetre courte/Asia/London
    # MGC overnight = peu d'activite (no big orders, no IB breakouts, no
    # divergences). Asia London ES/NQ = idem. Flag uniquement si >= 200 bars
    # ET symbol = US RTH actif (cf logic CHECK3 ci-dessous).
    # tier counts trades big orders
    "n_big_t1", "n_big_t2", "n_big_t3", "n_big_t4",
    "n_big_buy_t1", "n_big_buy_t2", "n_big_buy_t3", "n_big_buy_t4",
    "n_big_sell_t1", "n_big_sell_t2", "n_big_sell_t3", "n_big_sell_t4",
    "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_ask_v2_t3", "n_big_ask_v2_t4",
    "n_big_bid_v2_t1", "n_big_bid_v2_t2", "n_big_bid_v2_t3", "n_big_bid_v2_t4",
    # Cluster counts (rare events overnight)
    "n_clusters", "n_cluster_groups",
    "cluster_at_high", "cluster_at_low",
    "max_cluster_size", "max_cluster_volume_v2",
    # Bool flags pre-RTH (jamais set Asia/London)
    "ib_broken_up", "ib_broken_dn", "ib_broken_down",
    "ovn_broken_up", "ovn_broken_dn",
    "vwap_d_cross_up", "vwap_d_cross_dn",
    "is_new_cash_high", "is_new_cash_low",
    "rotation_up", "rotation_dn",
    "vol_spike_up", "vol_spike_dn",
    # News flags (calendrier, jamais set hors news window)
    "is_news_715", "is_news_730", "is_news_830",
    "is_news_845", "is_news_900", "is_news_930",
    "within_news_715_5m", "within_news_730_5m", "within_news_830_5m",
    "within_news_845_5m", "within_news_900_5m", "within_news_930_5m",
    # Battle Navale (events rares stack/absorb/trapped)
    "bn_stack_ask", "bn_stack_bid",
    "bn_absorb_ask", "bn_absorb_bid",
    "bn_absorb_ask_raw", "bn_absorb_bid_raw",
    "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
    "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    # Delta divergence + clean
    "delta_div_buy", "delta_div_sell",
    "delta_div_buy_clean", "delta_div_sell_clean",
    # Zones tracker (count events)
    "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
    "n_delta_div_buy_zones_active", "n_delta_div_sell_zones_active",
    "n_trapped_buyers_cluster_within_0_2pct",
    "n_trapped_sellers_cluster_within_0_2pct",
    "n_delta_div_buy_cluster_within_0_2pct",
    "n_delta_div_sell_cluster_within_0_2pct",
    # Swing + sweep events rares
    "swing_high_active_lag10", "swing_low_active_lag10",
    "equal_highs_detected", "equal_lows_detected",
    "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
    "spike_detected_lag3",
    "retest_high_delta_div", "retest_low_delta_div",
    # Finish strength
    "finish_strong_up", "finish_strong_dn",
    # Open type events (pre-IB-close = constant 0/UNKNOWN)
    "open_type", "open_zone", "open_direction", "open_bias_conf",
    "day_type", "profile_shape",
    "im_cross_open_signal", "im_open_type_agreement",
    # Premium/discount + intraday VA flags
    "inside_value_area", "premium_zone", "discount_zone",
    "vwap_d_sd1_above", "vwap_d_sd1_below",
    "vwap_d_sd2_above", "vwap_d_sd2_below",
    "vix_above_hvl", "vix_above_hvl_0dte",
    "above_asia_open", "above_london_open", "above_ny_open",
    "above_after_open", "above_open_830", "above_open_930",
    "is_in_asia", "is_in_london", "is_in_us_cash", "is_in_us_after",
    "is_cash_session", "is_ib_window", "is_new_sess_high", "is_new_sess_low",
    "ib_complete", "bool_above_mq_call", "bool_above_mq_hvl",
    "bool_gex_flip_zone",
    "poc_position", "poc_migration_dir",
    # ctx_* day_type intensity (early session = 0)
    "ctx_day_type_intensity", "ctx_session_phase",
    "ctx_failed_auction",
    # Session-fixed levels (seeded au cold start, change 1x/jour session change)
    "prev_vpoc", "prev_vah", "prev_val", "pdh", "pdl",
    "asia_high", "asia_low", "asia_open",
    "ctx_bars_since_div",  # counter
    "im_smt_divergence",   # event rare cross-symbol
    # MQ snapshot daily fixe (broadcast 1x/jour matin)
    "mq_call", "mq_put", "mq_hvl",
    "mq_call_0dte", "mq_put_0dte", "mq_hvl_0dte",
    "mq_1d_min", "mq_1d_max",
    "next_wall_is_call",
    "cur_pdh", "cur_pdl",  # idem session-fixed
}

# Outlier explosion threshold (cf DMP_validator.py:65)
OUTLIER_RATIO_THRESHOLD = 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationReport:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.info = []
        self.n_checks = 0

    def err(self, code: str, msg: str, **ctx):
        self.errors.append({"code": code, "msg": msg, **ctx})

    def warn(self, code: str, msg: str, **ctx):
        self.warnings.append({"code": code, "msg": msg, **ctx})

    def add_info(self, msg: str):
        self.info.append(msg)


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line.replace("NaN", "null")))
                except json.JSONDecodeError:
                    pass
    return pd.DataFrame(rows)


def check_100_nan(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 1 — features 100% NaN hors whitelist legit."""
    report.n_checks += 1
    suspect = []
    for c in df.columns:
        if c in ALL_LEGIT_NAN:
            continue
        if df[c].dtype.kind not in "fc":
            continue
        if df[c].isna().mean() >= 0.99:
            suspect.append(c)

    if len(suspect) > 5:
        report.err("CHECK1_100_NAN", f"{sym} : {len(suspect)} features 100% NaN hors whitelist",
                   features=suspect[:20])
    elif len(suspect) > 0:
        report.warn("CHECK1_100_NAN", f"{sym} : {len(suspect)} features 100% NaN",
                    features=suspect)


def check_saturation(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 2 — features bool fire_rate > 95% (Pattern V1 cousin DMP)."""
    report.n_checks += 1
    saturated = []
    for c in SATURATION_BOOL_FEATURES:
        if c not in df.columns:
            continue
        # bool/int -> fire_rate = sum / n
        non_nan = df[c].dropna()
        if len(non_nan) == 0:
            continue
        try:
            fire_rate = float((non_nan != 0).sum()) / len(non_nan)
        except (TypeError, ValueError):
            continue
        if fire_rate > SATURATION_CEILING:
            saturated.append({"col": c, "fire_rate": round(fire_rate, 3),
                              "n": len(non_nan)})

    if saturated:
        report.err("CHECK2_SATURATION", f"{sym} : {len(saturated)} bool saturees > 95%",
                   features=saturated)


def check_constant(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 3 — features numeriques quasi-constantes hors whitelist."""
    report.n_checks += 1
    constants = []
    for c in df.columns:
        if c in CONST_SNAPSHOTS_LEGIT:
            continue
        if c in ALL_LEGIT_NAN:
            continue
        if df[c].dtype.kind not in "fc":
            continue
        non_nan = df[c].dropna()
        if len(non_nan) < 10:
            continue
        # Check arrays (mq_gex/mq_blind list-of-floats)
        if non_nan.iloc[0] is None or (isinstance(non_nan.iloc[0], (list, dict))):
            continue
        std = float(non_nan.std())
        if std < 1e-6:
            constants.append({"col": c, "std": std, "n": len(non_nan),
                              "value": float(non_nan.iloc[0])})

    if len(constants) > 10:
        report.err("CHECK3_CONSTANTS", f"{sym} : {len(constants)} features quasi-constantes",
                   features=constants[:15])
    elif constants:
        report.warn("CHECK3_CONSTANTS", f"{sym} : {len(constants)} quasi-constantes",
                    features=constants)


def check_outliers(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 4 — outlier max/|p99| > 100 (scale break)."""
    report.n_checks += 1
    outliers = []
    for c in df.columns:
        if df[c].dtype.kind not in "fc":
            continue
        non_nan = df[c].dropna()
        if len(non_nan) < 30:
            continue
        try:
            p99 = float(non_nan.abs().quantile(0.99))
            max_abs = float(non_nan.abs().max())
            if p99 > 1e-9 and max_abs / p99 > OUTLIER_RATIO_THRESHOLD:
                outliers.append({"col": c, "max": max_abs, "p99": p99,
                                 "ratio": round(max_abs / p99, 1)})
        except (TypeError, ValueError):
            continue

    if outliers:
        report.warn("CHECK4_OUTLIER", f"{sym} : {len(outliers)} outliers max/p99 > 100",
                    features=outliers[:10])


def check_duplicates(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 5 — doublons ts_event_ns (race condition close-then-update)."""
    report.n_checks += 1
    if "ts_event_ns" not in df.columns:
        return
    dup = df.duplicated(subset=["ts_event_ns"], keep=False)
    n_dup = int(dup.sum())
    if n_dup > 0:
        dup_ts = df.loc[dup, "ts_event_ns"].unique().tolist()[:5]
        report.err("CHECK5_DUPLICATES", f"{sym} : {n_dup} doublons ts_event_ns",
                   n_dup=n_dup, sample_ts=dup_ts)


def check_ts_monotonic(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 6 — ts_event_ns monotone increasing (gap < 5 min)."""
    report.n_checks += 1
    if "ts_event_ns" not in df.columns or len(df) < 2:
        return
    ts = df["ts_event_ns"].astype("int64").sort_values()
    diffs = ts.diff().dropna()
    # Expected ~60s gap (= 60_000_000_000 ns)
    n_neg = int((diffs < 0).sum())
    n_huge = int((diffs > 5 * 60 * 1_000_000_000).sum())  # > 5 min
    if n_neg > 0:
        report.err("CHECK6_TS_NON_MONOTONIC", f"{sym} : {n_neg} ts decroissants",
                   n=n_neg)
    if n_huge > 0:
        report.warn("CHECK6_TS_LARGE_GAP", f"{sym} : {n_huge} gaps > 5min",
                    n=n_huge)


def check_drift_vs_v4(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 7 — drift LIVE vs V4 batch sur overlap bars."""
    report.n_checks += 1
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    year = int(today_str[:4])
    month = int(today_str[4:6])
    # Mapping MGC.v.0 -> MGC.c.0 (V4 batch utilise canonical Databento)
    sym_v4 = "MGC.c.0" if sym == "MGC.v.0" else sym
    v4_path = V4_DIR / f"symbol={sym_v4}" / f"year={year}" / f"month={month:02d}" / "data.parquet"
    if not v4_path.exists():
        report.add_info(f"V4 batch absent {v4_path.name} (drift check skip)")
        return
    df_v4 = pd.read_parquet(v4_path)
    df_v4["ts_event"] = pd.to_datetime(df_v4["ts_event"], utc=True)
    df_live = df.copy()
    if "ts_event_ns" in df_live.columns:
        df_live["ts_event"] = pd.to_datetime(df_live["ts_event_ns"], unit="ns", utc=True)
    else:
        return
    merged = df_live.merge(df_v4, on="ts_event", how="inner", suffixes=("_live", "_v4"))
    n_overlap = len(merged)
    if n_overlap == 0:
        report.add_info(f"V4 batch overlap=0 (drift check skip)")
        return

    drifts = []
    for c in df_live.columns:
        live_col = f"{c}_live"
        v4_col = f"{c}_v4"
        if live_col not in merged.columns or v4_col not in merged.columns:
            continue
        if merged[live_col].dtype.kind not in "fc":
            continue
        try:
            b = merged[v4_col].astype("float64").values
            s = merged[live_col].astype("float64").values
            mask = ~(np.isnan(b) | np.isnan(s))
            if mask.sum() < 10:
                continue
            diff = np.abs(b[mask] - s[mask])
            max_diff = float(np.nanmax(diff))
            mean_v4 = float(np.nanmean(b[mask]))
            std_v4 = float(np.nanstd(b[mask]))
            if std_v4 > 1e-9 and max_diff / std_v4 > 0.5:
                drifts.append({"col": c, "max_diff": round(max_diff, 6),
                               "mean_v4": round(mean_v4, 4),
                               "std_v4": round(std_v4, 4),
                               "ratio": round(max_diff / std_v4, 2)})
        except (TypeError, ValueError):
            continue

    if len(drifts) > 30:
        report.warn("CHECK7_DRIFT_V4",
                    f"{sym} : {len(drifts)} features drift > 0.5σ vs V4",
                    n_overlap=n_overlap, top=drifts[:15])
    report.add_info(f"V4 drift check : {n_overlap} bars overlap / {len(drifts)} drifts")


def check_schema_completeness(df: pd.DataFrame, sym: str, report: ValidationReport):
    """CHECK 8 — schema coverage vs V4 batch (cible >= 90% cols)."""
    report.n_checks += 1
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    year = int(today_str[:4])
    month = int(today_str[4:6])
    # Mapping MGC.v.0 -> MGC.c.0 (V4 batch utilise canonical Databento)
    sym_v4 = "MGC.c.0" if sym == "MGC.v.0" else sym
    v4_path = V4_DIR / f"symbol={sym_v4}" / f"year={year}" / f"month={month:02d}" / "data.parquet"
    if not v4_path.exists():
        return
    df_v4 = pd.read_parquet(v4_path)
    v4_cols = set(df_v4.columns)
    live_cols = set(df.columns)
    missing = sorted(v4_cols - live_cols)
    coverage = len(live_cols & v4_cols) / len(v4_cols) if v4_cols else 0.0

    report.add_info(f"Schema coverage {sym} : {coverage*100:.1f}% ({len(live_cols & v4_cols)}/{len(v4_cols)})")
    if coverage < 0.70:
        report.err("CHECK8_LOW_COVERAGE",
                   f"{sym} : schema coverage {coverage*100:.1f}% < 70% (cible C++ DMP)",
                   missing_count=len(missing), missing_sample=missing[:20])
    elif coverage < 0.90:
        report.warn("CHECK8_PARTIAL_COVERAGE",
                    f"{sym} : schema coverage {coverage*100:.1f}% < 90%",
                    missing_count=len(missing), missing_sample=missing[:10])


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def validate_file(path: Path, sym: str) -> ValidationReport:
    report = ValidationReport()
    df = load_jsonl(path)
    if df.empty:
        report.err("EMPTY_FILE", f"{path.name} : 0 lignes")
        return report
    report.add_info(f"{sym} : {len(df)} bars, {len(df.columns)} cols")

    check_100_nan(df, sym, report)
    check_saturation(df, sym, report)
    check_constant(df, sym, report)
    check_outliers(df, sym, report)
    check_duplicates(df, sym, report)
    check_ts_monotonic(df, sym, report)
    check_drift_vs_v4(df, sym, report)
    check_schema_completeness(df, sym, report)

    return report


def print_report(sym: str, rep: ValidationReport):
    print(f"\n{'='*70}")
    print(f"  {sym}  —  {rep.n_checks} checks")
    print(f"{'='*70}")
    for line in rep.info:
        print(f"  [INFO]  {line}")
    if not rep.errors and not rep.warnings:
        print(f"  [GREEN] tous checks OK")
    for w in rep.warnings:
        print(f"\n  [WARN]  {w['code']} : {w['msg']}")
        for k, v in w.items():
            if k in ("code", "msg"):
                continue
            if isinstance(v, list) and len(v) > 0:
                print(f"          {k} ({len(v)}) :")
                for item in v[:5]:
                    print(f"            {item}")
                if len(v) > 5:
                    print(f"            ... ({len(v)-5} more)")
            else:
                print(f"          {k} = {v}")
    for e in rep.errors:
        print(f"\n  [ERROR] {e['code']} : {e['msg']}")
        for k, v in e.items():
            if k in ("code", "msg"):
                continue
            if isinstance(v, list) and len(v) > 0:
                print(f"          {k} ({len(v)}) :")
                for item in v[:8]:
                    print(f"            {item}")
                if len(v) > 8:
                    print(f"            ... ({len(v)-8} more)")
            else:
                print(f"          {k} = {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, help="ES.c.0 / NQ.c.0 / MGC.v.0")
    ap.add_argument("--date", default=None, help="YYYYMMDD (default today UTC)")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 si erreurs (CI mode)")
    args = ap.parse_args()

    if args.symbol:
        symbols = [args.symbol]
    else:
        symbols = ["ES.c.0", "NQ.c.0", "MGC.v.0"]

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")

    print("="*70)
    print(f"  MIA-Live-Enricher VALIDATOR (a la dmp_validator.py)")
    print(f"  Date : {date_str}  /  Symbols : {symbols}")
    print("="*70)

    total_errors = 0
    total_warnings = 0
    for sym in symbols:
        # Pattern DMP C++ : DATA/live_enriched/{SYM}/{YYYYMMDD}_{SYM}.jsonl
        # MGC -> GC filesystem (cf lessons.md mapping)
        sym_pure = sym.split(".")[0]
        sym_fs = "GC" if sym_pure == "MGC" else sym_pure
        path = LIVE_DIR / sym_fs / f"{date_str}_{sym_fs}.jsonl"
        if not path.exists():
            print(f"\n  [SKIP] {sym} : {path} absent")
            continue
        rep = validate_file(path, sym)
        print_report(sym, rep)
        total_errors += len(rep.errors)
        total_warnings += len(rep.warnings)

    print(f"\n{'='*70}")
    print(f"  GLOBAL : {total_errors} errors / {total_warnings} warnings")
    print(f"{'='*70}")

    if total_errors > 0:
        verdict = "RED"
    elif total_warnings > 5:
        verdict = "YELLOW"
    else:
        verdict = "GREEN"
    print(f"  VERDICT : {verdict}")

    if args.strict and total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
