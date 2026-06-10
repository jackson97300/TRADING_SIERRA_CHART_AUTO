"""audit_mq_historical_pollution.py — Detection bug arr[sz-1] sur niveaux MQ historiques.

Hypothese : le bug DMP arr[sz-1] (incident 15/04) ecrase les barres historiques
avec la VALEUR ACTUELLE du jour de backfill. Si actif, dist_mq_*_pct devrait
etre quasi-constant intraday (alors qu'il devrait bouger avec le prix).

Tests par jour :
  1. n_unique de dist_mq_call_pct (devrait etre ~> 100 sur 1380 bars si propre)
  2. std de dist_mq_call_pct (devrait etre > 0.05 sur normal day)
  3. correlation dist_mq_call_pct vs close (devrait etre forte si propre :
     prix monte -> distance diminue ou augmente selon cote)
  4. mq_call / mq_put / mq_hvl : niveaux absolus, devraient etre CONSTANTS
     intraday (broadcast journalier OK). Mais devrait CHANGER d'un jour a
     l'autre si data MQ propre.

Verdict :
  - Jour avec n_unique(dist_mq_*) <= 3 ET std <= 0.001 = JOUR POLLUE
  - Jour avec mq_call constant sur 5+ jours d'affilee = JOUR POLLUE (broadcast)
  - Jour avec correlation dist vs close > 0.5 = JOUR PROPRE
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def load_v4(symbol, max_months=6):
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={symbol}.c.0"
    files = sorted(base.glob("**/*.parquet"))[-max_months:]
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df = df.dropna(subset=["ts_event"]).sort_values("ts_event").reset_index(drop=True)
    df["date_utc"] = df["ts_event"].dt.date
    return df


MQ_DIST_FEATURES = [
    "dist_mq_call_pct",
    "dist_mq_put_pct",
    "dist_mq_hvl_pct",
    "dist_mq_call_0dte_pct",
    "dist_mq_put_0dte_pct",
    "dist_gex_nearest_up_pct",
    "dist_gex_nearest_dn_pct",
]

MQ_LEVEL_FEATURES = [
    "mq_call",
    "mq_put",
    "mq_hvl",
]


def audit_per_day(df, sym):
    """Pour chaque jour, calcule stats par feature MQ."""
    dates = sorted(df["date_utc"].unique())
    print(f"\n=== AUDIT MQ HISTORICAL POLLUTION — {sym} ===")
    print(f"  Total jours : {len(dates)}, total bars : {len(df)}")

    # Header
    cols_dist = [c for c in MQ_DIST_FEATURES if c in df.columns]
    cols_level = [c for c in MQ_LEVEL_FEATURES if c in df.columns]
    print(f"  Features dist_mq_* trouvees : {cols_dist}")
    print(f"  Features mq_* (level) trouvees : {cols_level}")

    if not cols_dist:
        print("  ERREUR : aucune feature dist_mq_* dans le parquet")
        return

    # Audit dist features (devrait varier intraday)
    print(f"\n--- Test 1 : dist_mq_*_pct doit VARIER intraday ---")
    print(f"  Si n_unique <= 3 et std <= 0.001 sur >50% des jours -> POLLUE")
    print()
    print(f"  {'Feature':<32s}  {'jours OK':>10s}  {'jours pollu':>12s}  {'jours NaN':>10s}  "
          f"{'verdict':>20s}")
    pollution_summary = {}
    for col in cols_dist:
        n_ok = 0
        n_polluted = 0
        n_nan = 0
        for d in dates:
            sub = df[df["date_utc"] == d][col].dropna()
            if len(sub) < 10:
                n_nan += 1
                continue
            nu = sub.nunique()
            std = float(sub.std())
            if nu <= 3 and std <= 0.001:
                n_polluted += 1
            else:
                n_ok += 1
        total = n_ok + n_polluted
        pollution_pct = (n_polluted / total * 100) if total else 0
        verdict = "POLLUE" if pollution_pct > 50 else ("DOUTEUX" if pollution_pct > 10 else "PROPRE")
        pollution_summary[col] = {"pct_polluted": pollution_pct, "verdict": verdict}
        print(f"  {col:<32s}  {n_ok:>10d}  {n_polluted:>12d}  {n_nan:>10d}  "
              f"{verdict + f' ({pollution_pct:.0f}%)':>20s}")

    # Audit niveaux absolus (devrait varier d'un jour a l'autre, constants intraday)
    if cols_level:
        print(f"\n--- Test 2 : mq_* (levels) doivent VARIER d'un jour a l'autre ---")
        print(f"  Si meme valeur sur >7j consecutifs = broadcast valeur actuelle = POLLUE")
        for col in cols_level:
            day_values = []
            for d in dates:
                sub = df[df["date_utc"] == d][col].dropna()
                if len(sub) > 0:
                    day_values.append((d, sub.iloc[0]))
            if not day_values:
                print(f"  {col:<20s} : ABSENT")
                continue
            # Detect runs of same value
            runs = []
            cur_val = None
            cur_len = 0
            for d, v in day_values:
                if cur_val is None or abs(v - cur_val) > 0.01:
                    if cur_len > 0:
                        runs.append(cur_len)
                    cur_val = v
                    cur_len = 1
                else:
                    cur_len += 1
            if cur_len > 0:
                runs.append(cur_len)
            max_run = max(runs) if runs else 0
            n_unique_days = len(set(round(v, 2) for _, v in day_values))
            print(f"  {col:<20s} : n_unique_days={n_unique_days}/{len(day_values)} ({n_unique_days*100/len(day_values):.0f}%), "
                  f"max consecutive run={max_run}j")

    # Test 3 : correlation dist vs close (sur jours propres uniquement)
    print(f"\n--- Test 3 : correlation |dist_mq_call_pct| vs close ---")
    print(f"  Sur jours OK : devrait etre forte (~|>0.5|) si data propre")
    if "dist_mq_call_pct" in df.columns and "close" in df.columns:
        sample_dates = dates[:3] + dates[len(dates)//2:len(dates)//2+3] + dates[-3:]
        for d in sample_dates:
            sub = df[df["date_utc"] == d].dropna(subset=["dist_mq_call_pct", "close"])
            if len(sub) < 20:
                continue
            corr = sub["dist_mq_call_pct"].corr(sub["close"])
            std_dist = sub["dist_mq_call_pct"].std()
            std_close = sub["close"].std()
            print(f"  {d} : corr={corr:.3f}, std(dist)={std_dist:.4f}, std(close)={std_close:.2f}, n={len(sub)}")

    # Verdict global
    print(f"\n=== VERDICT GLOBAL {sym} ===")
    n_polluted_features = sum(1 for v in pollution_summary.values() if v["verdict"] == "POLLUE")
    n_doubt = sum(1 for v in pollution_summary.values() if v["verdict"] == "DOUTEUX")
    n_clean = sum(1 for v in pollution_summary.values() if v["verdict"] == "PROPRE")
    print(f"  Features dist_mq_* : {n_clean} PROPRES, {n_doubt} DOUTEUX, {n_polluted_features} POLLUES")
    if n_polluted_features >= 3:
        print(f"  -> CONCLUSION : MQ HISTORIQUE POLLUE -> boost +0.68t V2 etait LEAK")
    elif n_polluted_features == 0 and n_doubt <= 1:
        print(f"  -> CONCLUSION : MQ HISTORIQUE PROPRE -> boost +0.68t V2 etait edge MQ legitime")
    else:
        print(f"  -> CONCLUSION : MITIGE, audit jour-par-jour necessaire avant trust")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True, choices=["ES", "NQ"])
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()
    df = load_v4(args.symbol, args.months)
    print(f"[{args.symbol}] Loaded {len(df)} bars, {df['date_utc'].nunique()} jours")
    audit_per_day(df, args.symbol)


if __name__ == "__main__":
    main()
