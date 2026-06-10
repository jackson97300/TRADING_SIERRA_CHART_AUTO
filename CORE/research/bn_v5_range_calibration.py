"""bn_v5_range_calibration.py — Calibration empirique seuil range_drift_min_pct BN V5.

Mission Jackson (03/06/2026 — BN V5 ne trade pas depuis 13j) :
- Calcul distribution drift_pct sur 30j live_enriched NQ + ES
- Identification seuil optimal (cible 5-15 trades/j)
- Audit cascade Pattern 11 (rejection rate par filtre)

Usage:
    python -X utf8 CORE/research/bn_v5_range_calibration.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path("D:/TRADING_SIERRA_CHART_AUTO")
LIVE = ROOT / "DATA" / "live_enriched"

LOOKBACK_BARS = 30  # = BNV5Params.range_lookback_bars default

NEEDED_COLS = (
    "ts_event_iso", "open", "high", "low", "close",
    "delta_bar", "aggressor_imbalance",
    # confluence cols LONG
    "dist_mq_hvl_pct", "dist_mq_put_pct", "dist_vwap_d_sd1d_pct", "dist_gex_nearest_dn_pct",
    "dist_blind_nearest_dn_pct",
    # confluence cols SHORT
    "dist_mq_call_pct", "dist_mq_call_0dte_pct", "dist_vwap_d_sd1u_pct", "dist_gex_nearest_up_pct",
    "dist_blind_nearest_up_pct",
    # session
    "date_et", "mins_et",
)


def load_jsonl(path: Path) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            kept = {k: rec.get(k) for k in NEEDED_COLS}
            # also keep long_up_bar / long_dn_bar if present
            for k in ("long_up_bar", "long_dn_bar"):
                if k in rec:
                    kept[k] = rec[k]
            rows.append(kept)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


def load_symbol(sym: str, n_days: int = 30) -> pd.DataFrame:
    dir_ = LIVE / sym
    files = sorted([p for p in dir_.glob(f"*_{sym}.jsonl")])
    files = files[-n_days:]
    dfs = []
    for p in files:
        df = load_jsonl(p)
        if df.empty:
            continue
        df["_file"] = p.name
        dfs.append(df)
    if not dfs:
        return pd.DataFrame()
    out = pd.concat(dfs, ignore_index=True)
    return out


def compute_drift(df: pd.DataFrame, lookback: int = LOOKBACK_BARS) -> pd.Series:
    """drift_pct = abs(close - close_{lookback bars ago}) / close_{lookback} * 100."""
    c = df["close"].astype(float)
    c_lag = c.shift(lookback)
    drift = (c - c_lag).abs() / c_lag * 100
    return drift


def session_label(mins_et) -> str:
    """ET minutes since midnight -> session label."""
    try:
        m = int(mins_et)
    except Exception:
        return "UNK"
    # Asia approx 18:00 ET prev -> 03:00 ET = mins 1080..1440 OR 0..180
    # London approx 03:00 -> 09:30 ET = 180..570
    # US RTH 09:30 -> 16:00 ET = 570..960
    # US AH 16:00 -> 18:00 ET = 960..1080
    if 180 <= m < 570:
        return "LONDON"
    if 570 <= m < 960:
        return "US_RTH"
    if 960 <= m < 1080:
        return "US_AH"
    return "ASIA"


def quantiles_table(s: pd.Series, label: str) -> dict:
    s2 = s.dropna()
    if s2.empty:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": int(len(s2)),
        "p50": float(s2.quantile(0.50)),
        "p75": float(s2.quantile(0.75)),
        "p90": float(s2.quantile(0.90)),
        "p95": float(s2.quantile(0.95)),
        "p99": float(s2.quantile(0.99)),
        "max": float(s2.max()),
        "mean": float(s2.mean()),
    }


def pass_rates(s: pd.Series, thresholds: Iterable[float]) -> list[dict]:
    s2 = s.dropna()
    n = len(s2)
    out = []
    for t in thresholds:
        passed = int((s2 >= t).sum())
        out.append({
            "threshold_pct": t,
            "bars_passed": passed,
            "pass_rate_pct": round(100.0 * passed / n, 2) if n > 0 else 0.0,
        })
    return out


# --- Cascade audit (rejection rate par filtre, ordre BN V5 actuel) -----------

SUPPORT_COLS = (
    "dist_blind_nearest_dn_pct", "dist_mq_hvl_pct", "dist_mq_put_pct",
    "dist_vwap_d_sd1d_pct", "dist_gex_nearest_dn_pct",
)
RESIST_COLS = (
    "dist_blind_nearest_up_pct", "dist_mq_call_pct", "dist_mq_call_0dte_pct",
    "dist_vwap_d_sd1u_pct", "dist_gex_nearest_up_pct",
)


def cascade_audit_long(df: pd.DataFrame, conf_max: float = 0.20,
                       drift_min: float = 0.20, lookback: int = 30,
                       aggressor_min: float = 0.3) -> dict:
    """Mesure le taux de rejection cumulatif par filtre, mock proxy par-bar.

    Proxy : on ne reproduit pas pivot detection exact, mais on mesure pour
    chaque bar comme si elle etait candidate entry LONG.
    """
    n_total = len(df)
    if n_total == 0:
        return {}

    # Filtre 1 : confluence (au moins 1 SUPPORT_COL dans [0, conf_max])
    near_sup = pd.Series(False, index=df.index)
    for c in SUPPORT_COLS:
        if c in df.columns:
            v = pd.to_numeric(df[c], errors="coerce").abs()
            near_sup |= (v <= conf_max) & v.notna()
    pass1 = int(near_sup.sum())

    # Filtre 2 : range (drift_pct >= drift_min) — conditionne au pass1
    drift = compute_drift(df, lookback)
    pass_drift = drift >= drift_min
    pass2 = int((near_sup & pass_drift).sum())

    # Filtre 3 : bar_reversal niveau 1 close > open — conditionne pass2
    bar_green = (pd.to_numeric(df["close"], errors="coerce") >
                 pd.to_numeric(df["open"], errors="coerce"))
    pass3 = int((near_sup & pass_drift & bar_green).sum())

    # Filtre 4 : delta_bar > 0 — conditionne pass3
    if "delta_bar" in df.columns:
        dpos = pd.to_numeric(df["delta_bar"], errors="coerce") > 0
    else:
        dpos = pd.Series(True, index=df.index)
    pass4 = int((near_sup & pass_drift & bar_green & dpos).sum())

    # Filtre 5 : aggressor_imbalance >= 0.3 — conditionne pass4
    if "aggressor_imbalance" in df.columns:
        agg_ok = pd.to_numeric(df["aggressor_imbalance"], errors="coerce") >= aggressor_min
    else:
        agg_ok = pd.Series(True, index=df.index)
    pass5 = int((near_sup & pass_drift & bar_green & dpos & agg_ok).sum())

    # Filtre 6 : long_up_bar = 1 — conditionne pass5
    if "long_up_bar" in df.columns:
        lub_ok = pd.to_numeric(df["long_up_bar"], errors="coerce") >= 1
    else:
        lub_ok = pd.Series(True, index=df.index)
    pass6 = int((near_sup & pass_drift & bar_green & dpos & agg_ok & lub_ok).sum())

    return {
        "n_bars_total": n_total,
        "F1_confluence_long": pass1,
        "F1_pass_rate_pct": round(100 * pass1 / n_total, 2),
        "F2_range_drift": pass2,
        "F2_rejection_from_F1_pct": round(100 * (pass1 - pass2) / max(pass1, 1), 2),
        "F3_bar_green": pass3,
        "F3_rejection_from_F2_pct": round(100 * (pass2 - pass3) / max(pass2, 1), 2),
        "F4_delta_pos": pass4,
        "F4_rejection_from_F3_pct": round(100 * (pass3 - pass4) / max(pass3, 1), 2),
        "F5_aggressor": pass5,
        "F5_rejection_from_F4_pct": round(100 * (pass4 - pass5) / max(pass4, 1), 2),
        "F6_long_up_bar": pass6,
        "F6_rejection_from_F5_pct": round(100 * (pass5 - pass6) / max(pass5, 1), 2),
    }


def main():
    print("=" * 80)
    print("BN V5 RANGE CALIBRATION — Empirical study")
    print("=" * 80)

    results = {}

    for sym in ("NQ", "ES"):
        print(f"\n>>> Loading {sym} live_enriched (last 30 days) ...")
        df = load_symbol(sym, n_days=30)
        if df.empty:
            print(f"   No data for {sym}")
            continue
        print(f"   Bars loaded : {len(df):,}")
        print(f"   Date range  : {df['date_et'].min()} -> {df['date_et'].max()}")

        # Drift
        df["drift_pct"] = compute_drift(df, LOOKBACK_BARS)

        # Session label
        if "mins_et" in df.columns:
            df["session"] = df["mins_et"].map(session_label)
        else:
            df["session"] = "UNK"

        # Quantiles global
        q_global = quantiles_table(df["drift_pct"], f"{sym}_GLOBAL")

        # Quantiles par session
        q_sessions = []
        for s in ("ASIA", "LONDON", "US_RTH", "US_AH"):
            sub = df.loc[df["session"] == s, "drift_pct"]
            q_sessions.append(quantiles_table(sub, f"{sym}_{s}"))

        # Pass rates pour seuils candidats
        thresholds = [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20]
        pr_global = pass_rates(df["drift_pct"], thresholds)

        # Pass rates US RTH (session principale bot)
        pr_rth = pass_rates(df.loc[df["session"] == "US_RTH", "drift_pct"], thresholds)

        # Cascade audit (proxy LONG seulement)
        cascade = {}
        for thr in (0.05, 0.10, 0.15, 0.20):
            cascade[f"drift_thr_{thr}"] = cascade_audit_long(df, drift_min=thr)

        results[sym] = {
            "n_bars": len(df),
            "date_min": str(df["date_et"].min()),
            "date_max": str(df["date_et"].max()),
            "drift_quantiles_global": q_global,
            "drift_quantiles_by_session": q_sessions,
            "pass_rates_global": pr_global,
            "pass_rates_us_rth": pr_rth,
            "cascade_audit_long": cascade,
        }

        # Print
        print(f"\n   --- {sym} drift_pct quantiles (GLOBAL, n={q_global['n']:,}) ---")
        print(f"      P50 : {q_global['p50']:.4f}")
        print(f"      P75 : {q_global['p75']:.4f}")
        print(f"      P90 : {q_global['p90']:.4f}")
        print(f"      P95 : {q_global['p95']:.4f}")
        print(f"      P99 : {q_global['p99']:.4f}")
        print(f"      Max : {q_global['max']:.4f}")
        print(f"      Mean: {q_global['mean']:.4f}")

        print(f"\n   --- {sym} drift_pct quantiles BY SESSION ---")
        for q in q_sessions:
            if q.get("n", 0) > 0:
                print(f"      {q['label']:18s} n={q['n']:6,} p50={q['p50']:.4f}  p90={q['p90']:.4f}  p95={q['p95']:.4f}  max={q['max']:.4f}")

        print(f"\n   --- {sym} pass rates GLOBAL ---")
        for r in pr_global:
            print(f"      thr={r['threshold_pct']:.2f}%  -> {r['bars_passed']:6,} bars  ({r['pass_rate_pct']:.2f}%)")

        print(f"\n   --- {sym} pass rates US_RTH ---")
        for r in pr_rth:
            print(f"      thr={r['threshold_pct']:.2f}%  -> {r['bars_passed']:6,} bars  ({r['pass_rate_pct']:.2f}%)")

        print(f"\n   --- {sym} cascade audit (proxy LONG, per-bar) ---")
        for thr_lbl, cas in cascade.items():
            print(f"      {thr_lbl}:")
            for k, v in cas.items():
                print(f"         {k:36s} = {v}")

    # Save
    out_path = ROOT / "DATA" / "BN_V5_RANGE_CALIBRATION.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n>>> Results saved to {out_path}")


if __name__ == "__main__":
    main()
