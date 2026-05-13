"""meta_audit_leak_features.py — scanner toutes features V4 pour leaks suspects.

Audit Phase 1b suite (13/05/2026 nuit) : suite a la decouverte du leak DMP
momentum_3b (rho_fut1 = 0.44), scanner les ~462 features V4 enriched pour
identifier d'autres leaks suspects.

Critere : |rho(feature, close.diff(1).shift(-1))| > 0.10 = SUSPECT.

Une feature qui correle > 0.10 avec le RETOUR de la barre SUIVANTE
est mathematiquement un look-ahead leak (aucune formule causale ne peut
predire le close suivant avec un edge > 0.05 en moyenne).

Output : table top-20 suspects + sauvegarde DOCS/INCIDENT_LOG.md entry.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]


def main():
    print("=" * 80)
    print("META-AUDIT : scanner 462 features V4 pour leaks suspects")
    print("=" * 80)

    fpath = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=ES.c.0" / "year=2026" / "month=04" / "data.parquet"
    df = pd.read_parquet(fpath)
    print(f"Loaded {len(df)} bars, {len(df.columns)} cols from {fpath.name}")

    # Target : retour du bar SUIVANT (look-ahead 1 bar)
    fut_return = df["close"].shift(-1) - df["close"]
    print(f"Target fut_return : n_valid={fut_return.notna().sum()}, p10={fut_return.quantile(0.1):.2f}, p50={fut_return.median():.2f}, p90={fut_return.quantile(0.9):.2f}")
    print()

    # Skip colonnes non-numeriques + metadata
    skip_cols = {"ts_event", "session_id", "session_date_trading",
                 "date_et", "instrument_id", "year", "month", "day",
                 "is_roll_day", "is_cash_session", "is_ib_window"}

    results = []
    print("Scanning features...")
    for col in df.columns:
        if col in skip_cols:
            continue
        s = df[col]
        if not pd.api.types.is_numeric_dtype(s):
            continue
        if s.notna().sum() < 1000:
            continue
        mask = s.notna() & fut_return.notna()
        if mask.sum() < 1000:
            continue
        try:
            rho, _ = spearmanr(s[mask], fut_return[mask])
        except Exception:
            continue
        if pd.isna(rho):
            continue
        results.append({"feature": col, "rho_fut1": rho, "abs_rho": abs(rho), "n": int(mask.sum())})

    # Sort by abs rho descending
    results_sorted = sorted(results, key=lambda x: x["abs_rho"], reverse=True)

    # Top suspects
    print()
    print(f"TOP 25 features par |rho_fut1| (seuil suspect : 0.10) :")
    print("-" * 80)
    print(f"{'#':>3} {'feature':<35} {'rho_fut1':>10} {'|rho|':>10} {'n':>8} {'flag':>10}")
    print("-" * 80)

    n_suspect = 0
    n_strong = 0
    n_total = len(results_sorted)
    for i, r in enumerate(results_sorted[:25]):
        if r["abs_rho"] > 0.20:
            flag = "[CRITIQUE]"
            n_strong += 1
            n_suspect += 1
        elif r["abs_rho"] > 0.10:
            flag = "[SUSPECT]"
            n_suspect += 1
        elif r["abs_rho"] > 0.05:
            flag = "[A_VOIR]"
        else:
            flag = ""
        print(f"{i+1:>3} {r['feature']:<35} {r['rho_fut1']:>10.4f} {r['abs_rho']:>10.4f} {r['n']:>8} {flag:>10}")

    # Compteur global
    print("-" * 80)
    total_suspect = sum(1 for r in results_sorted if r["abs_rho"] > 0.10)
    total_strong = sum(1 for r in results_sorted if r["abs_rho"] > 0.20)
    print(f"TOTAL : {n_total} features scannees")
    print(f"        {total_suspect} suspects (|rho| > 0.10)")
    print(f"        {total_strong} CRITIQUES (|rho| > 0.20)")

    # Sauve top 30 en CSV pour audit
    out_csv = ROOT / "DOCS" / "meta_audit_leak_features_20260513.csv"
    pd.DataFrame(results_sorted[:50]).to_csv(out_csv, index=False)
    print()
    print(f"Top 50 sauve dans : {out_csv}")


if __name__ == "__main__":
    main()
