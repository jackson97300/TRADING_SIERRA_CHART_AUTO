"""backtest_composite_features.py — test 2 composites GROUPE B remplacements.

Phase 1b v0.4 (13/05/2026 nuit) : suite a l'audit ml-trainer qui recommandait
DROP les 3 features GROUPE B (ma_trend, vwap_slope_30, vwap_ma_align), on
teste 2 composites Python intelligents qui CAPTURENT LES MEMES 3 AXES :

  1. trend_composite_score : direction multi-TF + flow institutionnel
     Remplace conceptuellement ma_trend + vwap_ma_align
  2. flow_velocity         : vitesse CVD ATR-normalized
     Remplace conceptuellement vwap_slope_30

Critere decision :
  Si |rho| composite >= 0.05 ET > max DMP des 3 features remplacees :
    => GO ajouter aux features Bot 2 V6
  Si entre 0.03 et 0.05 :
    => MEDIUM, garder mais pas critique
  Si < 0.03 :
    => DROP definitif (les composites n'ont pas d'edge non plus)

Test aussi rho_fut1 pour s'assurer ZERO leak (anti-momentum_3b trap).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
from phase_b_v6_complete import add_trend_composite_score, add_flow_velocity  # noqa


def tbm(df, tp=10, sl=5, h=30, tk=0.25, side="long"):
    c, hi, lo = df["close"].values, df["high"].values, df["low"].values
    n = len(df)
    labels = np.zeros(n, dtype=np.int8)
    tp_p, sl_p = tp * tk, sl * tk
    for i in range(n - h):
        e = c[i]
        if side == "long":
            for j in range(1, h + 1):
                if hi[i + j] >= e + tp_p: labels[i] = 1; break
                if lo[i + j] <= e - sl_p: labels[i] = -1; break
        else:
            for j in range(1, h + 1):
                if lo[i + j] <= e - tp_p: labels[i] = 1; break
                if hi[i + j] >= e + sl_p: labels[i] = -1; break
    return labels


def main():
    print("=" * 80)
    print("Backtest composites GROUPE B v0.4 (trend_composite + flow_velocity)")
    print("=" * 80)

    fpath = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=ES.c.0" / "year=2026" / "month=04" / "data.parquet"
    df = pd.read_parquet(fpath)
    print(f"Loaded {len(df)} bars from {fpath.name}")

    # Calcul des composites
    df = add_trend_composite_score(df)
    df = add_flow_velocity(df, window=30)
    df = add_flow_velocity(df.rename(columns={"flow_velocity": "_tmp"}), window=15)
    df = df.rename(columns={"flow_velocity": "flow_velocity_15", "_tmp": "flow_velocity_30"})
    df = add_flow_velocity(df, window=60)
    df = df.rename(columns={"flow_velocity": "flow_velocity_60"})

    # Test rho_fut1 pour leak (CRITIQUE post momentum_3b discovery)
    fut_return = df["close"].shift(-1) - df["close"]
    print()
    print("LEAK CHECK (rho vs fut_return_t+1, seuil suspect > 0.10) :")
    print("-" * 80)
    for col in ("trend_composite_score", "flow_velocity_15", "flow_velocity_30", "flow_velocity_60"):
        s = df[col]
        mask = s.notna() & fut_return.notna()
        rho, _ = spearmanr(s[mask], fut_return[mask])
        flag = "[LEAK!]" if abs(rho) > 0.10 else "[OK]"
        print(f"  {col:<28}: rho_fut1={rho:+.4f}, n={mask.sum()} {flag}")

    # Labels TBM
    print()
    print("Generating TBM labels (TP=10t, SL=5t, horizon=30 bars)...")
    label_long = tbm(df)
    label_short = tbm(df, side="short")

    # Spearman edge predictif
    print()
    print("EDGE PREDICTIF (rho composite vs labels TBM):")
    print("-" * 80)
    print(f"{'Feature':<30}{'rho LONG':>12}{'rho SHORT':>12}{'|rho| max':>14}{'verdict':>12}")
    print("-" * 80)

    composites = {
        "trend_composite_score": df["trend_composite_score"],
        "flow_velocity_15": df["flow_velocity_15"],
        "flow_velocity_30": df["flow_velocity_30"],
        "flow_velocity_60": df["flow_velocity_60"],
    }

    for name, vals in composites.items():
        mask = vals.notna()
        rho_long, _ = spearmanr(vals[mask], label_long[mask])
        rho_short, _ = spearmanr(vals[mask], label_short[mask])
        abs_max = max(abs(rho_long), abs(rho_short))
        if abs_max >= 0.05:
            verdict = "STRONG"
        elif abs_max >= 0.03:
            verdict = "MEDIUM"
        elif abs_max >= 0.02:
            verdict = "WEAK"
        else:
            verdict = "REJET"
        print(f"  {name:<30}{rho_long:>12.4f}{rho_short:>12.4f}{abs_max:>14.4f}{verdict:>12}")

    # Reference : DMP 3 features (max edge)
    print("-" * 80)
    print("BASELINE DMP GROUPE B (3 features individuelles) :")
    for col in ("ma_trend", "vwap_slope_30", "vwap_ma_align"):
        s = df[col]
        mask = s.notna()
        rho_long, _ = spearmanr(s[mask], label_long[mask])
        rho_short, _ = spearmanr(s[mask], label_short[mask])
        abs_max = max(abs(rho_long), abs(rho_short))
        print(f"  {col:<30}{rho_long:>12.4f}{rho_short:>12.4f}{abs_max:>14.4f}{'[DMP]':>12}")
    print("=" * 80)

    # Verdict global
    max_dmp = max(
        max(abs(spearmanr(df[c].dropna(), label_long[df[c].notna()])[0]),
            abs(spearmanr(df[c].dropna(), label_short[df[c].notna()])[0]))
        for c in ("ma_trend", "vwap_slope_30", "vwap_ma_align")
    )
    max_composite = max(
        max(abs(spearmanr(v[v.notna()], label_long[v.notna()])[0]),
            abs(spearmanr(v[v.notna()], label_short[v.notna()])[0]))
        for v in composites.values()
    )
    print()
    print(f"Best DMP GROUPE B    : |rho| = {max_dmp:.4f}")
    print(f"Best composite Python: |rho| = {max_composite:.4f}")
    delta = max_composite - max_dmp
    print(f"Delta composite vs DMP: {delta:+.4f}")
    if max_composite >= 0.05:
        print(f"=> GO ajouter composites a apply_v6_complete (STRONG edge)")
    elif max_composite > max_dmp + 0.01:
        print(f"=> GO ajouter composites (BONUS vs DMP)")
    elif max_composite > 0.03:
        print(f"=> MEDIUM, decision Jackson")
    else:
        print(f"=> NOGO : composites n'apportent rien, DROP definitif")


if __name__ == "__main__":
    main()
