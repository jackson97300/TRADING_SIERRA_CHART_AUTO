"""Audit empirique efficacite features footprint — ES + NQ, data propre 17-22/04.

Question : quelles features footprint meritent d'etre dans le training ML et
dans quelle config SC ? Jackson : "on ne cherche pas a harmoniser mais l'efficacite".

Methodologie :
  1. Charge JSONL propres 17-22/04 (post-fix C++, data supposee clean)
  2. Pour chaque feature footprint, calcule :
     - Fire rate (% barres avec valeur != 0/NaN)
     - Distribution (mean, std, min, max, quantiles)
     - Signal predictif = correlation Spearman vs forward return (t+5, t+15, t+30)
     - Signal MAE/MFE = correlation avec adverse/favorable excursion
  3. Classement par pouvoir predictif
  4. Rapport top 10 / bottom 10 par symbole

Zero risque (read-only sur data existante). Duree ~30s.

Usage :
  python -X utf8 CORE/research/audit_footprint_efficiency_20260422.py
  python -X utf8 CORE/research/audit_footprint_efficiency_20260422.py --symbol NQ --detail
"""
import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = ROOT / "DATA"
REPORT_DIR = ROOT / "DATA" / "RESEARCH"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# 48 features footprint identifiees a auditer
FOOTPRINT_FEATURES = [
    # Rotation Reversal Bar
    "rotation_up", "rotation_dn", "rotation_zz_osc",
    # Battle Navale (derive footprint)
    "bn_color_up", "bn_color_dn", "bn_color_up_2", "bn_color_dn_2",
    "bn_absorb_ask", "bn_absorb_bid",
    "bn_long_up", "bn_long_dn",
    # Cluster Volume
    "big_ask_cluster_20t", "big_bid_cluster_20t",
    "big_ask_cluster_50t", "big_bid_cluster_50t",
    "big_ask_cluster_20t_t1", "big_ask_cluster_20t_t2",
    "big_ask_cluster_20t_t3", "big_ask_cluster_20t_t4",
    "big_bid_cluster_20t_t1", "big_bid_cluster_20t_t2",
    "big_bid_cluster_20t_t3", "big_bid_cluster_20t_t4",
    "dist_cluster_nearest_up", "dist_cluster_nearest_dn",
    "n_clusters_20t", "n_clusters_50t",
    # Bar-level footprint triggers
    "bar_color_up", "bar_color_dn",
    "bar_long_up_bar", "bar_long_dn_bar",
    "bar_long_dn_up", "bar_long_up_dn",
    "bar_edge_buy", "bar_edge_sell",
    # Extension Lines (distance aux triggers historiques)
    "dist_ext_color_up", "dist_ext_color_dn",
    "dist_ext_long_up", "dist_ext_long_dn",
    "dist_ext_edge_buy", "dist_ext_edge_sell",
    # Footprint edge (fp_* vs bar_*)
    "fp_edge_buy", "fp_edge_sell",
    # Autres
    "vwap_triple_align", "is_double_dist",
    "rvol_absorb_buy", "rvol_absorb_sell",
]

# Dates data propre (memoire project_data_clean_since_20260417.md)
CLEAN_DATES = ["20260417", "20260419", "20260420", "20260421", "20260422"]


def load_jsonl_clean(symbol: str) -> pd.DataFrame:
    """Charge JSONL propres pour symbole."""
    rows = []
    for date_str in CLEAN_DATES:
        fp = DATA_DIR / symbol / f"{date_str}_{symbol}.jsonl"
        if not fp.exists():
            continue
        with fp.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    row = json.loads(s)
                    rows.append(row)
                except json.JSONDecodeError:
                    continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def compute_forward_returns(df: pd.DataFrame, horizons_bars: Tuple[int, ...] = (5, 15, 30)) -> pd.DataFrame:
    """Forward returns en ticks a h barres dans le futur."""
    price_col = "price" if "price" in df.columns else "bar_close"
    tick_size = 0.25
    for h in horizons_bars:
        df[f"fwd_ret_{h}"] = (df[price_col].shift(-h) - df[price_col]) / tick_size
    return df


def compute_mae_mfe(df: pd.DataFrame, window_bars: int = 15) -> pd.DataFrame:
    """Pour chaque barre, MAE et MFE sur la fenetre suivante."""
    price_col = "price" if "price" in df.columns else "bar_close"
    tick_size = 0.25
    mae = np.full(len(df), np.nan)
    mfe = np.full(len(df), np.nan)
    prices = df[price_col].values
    for i in range(len(df) - window_bars):
        future = prices[i + 1:i + 1 + window_bars]
        if len(future) == 0:
            continue
        # Supposer direction LONG pour MAE/MFE (on inversera pour SELL dans l'analyse)
        move = (future - prices[i]) / tick_size
        mae[i] = move.min() if len(move) > 0 else np.nan
        mfe[i] = move.max() if len(move) > 0 else np.nan
    df["mae_15"] = mae
    df["mfe_15"] = mfe
    return df


def audit_feature(series: pd.Series, name: str, df: pd.DataFrame) -> Dict:
    """Audit complet d'une feature : distribution + signal predictif."""
    if name not in df.columns:
        return {"feature": name, "status": "ABSENT", "n_bars": 0}

    vals = pd.to_numeric(series, errors="coerce")
    n = len(vals)
    n_nan = vals.isna().sum()
    n_valid = n - n_nan

    if n_valid == 0:
        return {"feature": name, "status": "ALL_NAN", "n_bars": n}

    # Verifier si binaire ou continue
    uniq = vals.dropna().unique()
    is_binary = len(uniq) <= 2 and set(uniq).issubset({0, 0.0, 1, 1.0})

    # Fire rate (pour binaires : %1, pour continues : % != 0)
    if is_binary:
        fire = (vals == 1).sum()
        fire_rate = 100.0 * fire / n_valid if n_valid else 0
    else:
        fire = (vals != 0).sum()
        fire_rate = 100.0 * fire / n_valid if n_valid else 0

    # Distribution
    mean = float(vals.mean()) if n_valid else 0
    std = float(vals.std()) if n_valid else 0

    # Correlation Spearman avec forward returns
    rho_5 = rho_15 = rho_30 = rho_mae = rho_mfe = np.nan
    try:
        fr5 = df["fwd_ret_5"]
        fr15 = df["fwd_ret_15"]
        fr30 = df["fwd_ret_30"]
        mae = df.get("mae_15", pd.Series([np.nan] * len(df)))
        mfe = df.get("mfe_15", pd.Series([np.nan] * len(df)))

        mask5 = vals.notna() & fr5.notna()
        mask15 = vals.notna() & fr15.notna()
        mask30 = vals.notna() & fr30.notna()
        mask_mae = vals.notna() & mae.notna()
        mask_mfe = vals.notna() & mfe.notna()

        if mask5.sum() >= 30:
            rho_5, _ = spearmanr(vals[mask5], fr5[mask5])
        if mask15.sum() >= 30:
            rho_15, _ = spearmanr(vals[mask15], fr15[mask15])
        if mask30.sum() >= 30:
            rho_30, _ = spearmanr(vals[mask30], fr30[mask30])
        if mask_mae.sum() >= 30:
            rho_mae, _ = spearmanr(vals[mask_mae], mae[mask_mae])
        if mask_mfe.sum() >= 30:
            rho_mfe, _ = spearmanr(vals[mask_mfe], mfe[mask_mfe])
    except Exception:
        pass

    # Score utility : max abs corrélation sur les 3 horizons
    rhos = [abs(r) for r in (rho_5, rho_15, rho_30) if not np.isnan(r)]
    max_rho = max(rhos) if rhos else 0.0

    # Verdict
    if fire_rate == 0 or fire_rate == 100:
        verdict = "DEAD"
    elif fire_rate > 70:
        verdict = "SATURATED"
    elif max_rho < 0.02:
        verdict = "WEAK_SIGNAL"
    elif max_rho >= 0.05:
        verdict = "STRONG"
    else:
        verdict = "MARGINAL"

    return {
        "feature": name,
        "status": "OK",
        "binary": is_binary,
        "n_bars": n,
        "n_valid": int(n_valid),
        "fire_rate_pct": round(fire_rate, 2),
        "mean": round(mean, 4),
        "std": round(std, 4),
        "rho_fwd_5": round(rho_5, 4) if not np.isnan(rho_5) else None,
        "rho_fwd_15": round(rho_15, 4) if not np.isnan(rho_15) else None,
        "rho_fwd_30": round(rho_30, 4) if not np.isnan(rho_30) else None,
        "rho_mae": round(rho_mae, 4) if not np.isnan(rho_mae) else None,
        "rho_mfe": round(rho_mfe, 4) if not np.isnan(rho_mfe) else None,
        "max_abs_rho": round(max_rho, 4),
        "verdict": verdict,
    }


def run_audit(symbol: str, verbose: bool = False) -> pd.DataFrame:
    """Audit complet pour un symbole."""
    print(f"\n{'=' * 70}")
    print(f"AUDIT FOOTPRINT — {symbol}")
    print(f"{'=' * 70}")

    df = load_jsonl_clean(symbol)
    if df.empty:
        print(f"  Aucun JSONL propre trouve pour {symbol}")
        return pd.DataFrame()
    print(f"  Barres chargees : {len(df)}")
    print(f"  Dates : {sorted(df.get('ts', pd.Series()).apply(lambda x: pd.Timestamp(x * 1e6, unit='ns').date().isoformat() if pd.notna(x) else '?').unique())[:10]}")

    df = compute_forward_returns(df)
    df = compute_mae_mfe(df)

    # Audit chaque feature
    results = []
    for feat in FOOTPRINT_FEATURES:
        res = audit_feature(df[feat] if feat in df.columns else pd.Series([]), feat, df)
        results.append(res)

    rdf = pd.DataFrame(results)
    rdf["symbol"] = symbol

    # Trier par max_abs_rho decroissant
    rdf_ok = rdf[rdf["status"] == "OK"].copy()
    rdf_ok = rdf_ok.sort_values("max_abs_rho", ascending=False)

    # TOP 10
    print(f"\n  TOP 10 features footprint (meilleur signal Spearman) :")
    print(f"  {'Feature':<30} {'Fire%':>7} {'ρ5':>8} {'ρ15':>8} {'ρ30':>8} {'ρMAE':>8} {'ρMFE':>8} {'Verdict':<12}")
    print(f"  {'-'*30} {'-'*7} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*12}")
    for _, r in rdf_ok.head(10).iterrows():
        print(f"  {r['feature']:<30} {r['fire_rate_pct']:>6.1f}% {_fmt(r['rho_fwd_5']):>8} {_fmt(r['rho_fwd_15']):>8} {_fmt(r['rho_fwd_30']):>8} {_fmt(r['rho_mae']):>8} {_fmt(r['rho_mfe']):>8} {r['verdict']:<12}")

    # BOTTOM 10
    print(f"\n  BOTTOM 10 (signal le + faible ou sature) :")
    print(f"  {'Feature':<30} {'Fire%':>7} {'ρ5':>8} {'ρ15':>8} {'ρ30':>8} {'Verdict':<12}")
    for _, r in rdf_ok.tail(10).iterrows():
        print(f"  {r['feature']:<30} {r['fire_rate_pct']:>6.1f}% {_fmt(r['rho_fwd_5']):>8} {_fmt(r['rho_fwd_15']):>8} {_fmt(r['rho_fwd_30']):>8} {r['verdict']:<12}")

    # Features absentes ou mortes
    dead = rdf[rdf["status"] != "OK"]
    if len(dead) > 0:
        print(f"\n  Features absentes / mortes : {len(dead)}")
        for _, r in dead.iterrows():
            print(f"    {r['feature']:<30} {r['status']}")

    return rdf_ok


def _fmt(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "   -"
    return f"{v:+.3f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, help="ES ou NQ (default : les 2)")
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else ["ES", "NQ"]
    all_results = []
    for sym in symbols:
        rdf = run_audit(sym, verbose=args.detail)
        if not rdf.empty:
            all_results.append(rdf)

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        out_csv = REPORT_DIR / "audit_footprint_efficiency_20260422.csv"
        combined.to_csv(out_csv, index=False)
        print(f"\n{'=' * 70}")
        print(f"Rapport CSV : {out_csv}")
        print(f"{'=' * 70}")

        # Synthese ES vs NQ si les 2 audites
        if len(all_results) == 2:
            _print_es_vs_nq_synthese(all_results[0], all_results[1])


def _print_es_vs_nq_synthese(es_df, nq_df):
    """Compare ES vs NQ feature par feature."""
    print(f"\n{'=' * 70}")
    print(f"SYNTHESE ES vs NQ")
    print(f"{'=' * 70}")

    es_map = {r["feature"]: r for _, r in es_df.iterrows()}
    nq_map = {r["feature"]: r for _, r in nq_df.iterrows()}

    print(f"  {'Feature':<30} {'ES fire%':>10} {'NQ fire%':>10} {'ES ρmax':>10} {'NQ ρmax':>10} {'Verdict':<15}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*15}")

    # Features avec ecart significatif ou top performers
    all_feats = set(es_map.keys()) | set(nq_map.keys())
    rows = []
    for feat in all_feats:
        es_r = es_map.get(feat, {})
        nq_r = nq_map.get(feat, {})
        rows.append({
            "feat": feat,
            "es_fire": es_r.get("fire_rate_pct", 0),
            "nq_fire": nq_r.get("fire_rate_pct", 0),
            "es_rho": es_r.get("max_abs_rho", 0),
            "nq_rho": nq_r.get("max_abs_rho", 0),
        })
    rows.sort(key=lambda x: max(x["es_rho"], x["nq_rho"]), reverse=True)

    for r in rows[:20]:
        # Verdict comparatif
        es_fire = r["es_fire"]
        nq_fire = r["nq_fire"]
        diff = abs(es_fire - nq_fire)
        if diff > 30:
            verdict = "ASYM >30%"
        elif max(r["es_rho"], r["nq_rho"]) >= 0.05:
            verdict = "STRONG_BOTH"
        elif r["es_rho"] >= 0.03 or r["nq_rho"] >= 0.03:
            verdict = "ONE_SIDED"
        else:
            verdict = "WEAK"
        print(f"  {r['feat']:<30} {r['es_fire']:>9.1f}% {r['nq_fire']:>9.1f}% {r['es_rho']:>10.3f} {r['nq_rho']:>10.3f} {verdict:<15}")


if __name__ == "__main__":
    main()
