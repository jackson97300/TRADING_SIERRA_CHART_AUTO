"""backtest_momentum_variants.py — recherche d'un momentum honnete a edge predictif.

Phase 1b (suite) : suite a la decouverte du bug DMP momentum_3b (commit ce2de94),
on cherche une formule Python qui :
  1. N'utilise PAS de look-ahead (timing capture honnete)
  2. A un edge predictif > 0.05 Spearman sur labels TBM
  3. Reproductible et auditable

10 variantes testees, toutes calculables a partir de V4 enriched data
(close, high, low, vwap_d, atr_14m_pct, cvd_session) — pas de dependance
au DMP JSONL.

Output : tableau decisionnel avec verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]


def tbm_labels(df: pd.DataFrame, tp_ticks=10, sl_ticks=5, h=30, tick=0.25, side="long") -> np.ndarray:
    c, hi, lo = df["close"].values, df["high"].values, df["low"].values
    n = len(df)
    labels = np.zeros(n, dtype=np.int8)
    tp_pts, sl_pts = tp_ticks * tick, sl_ticks * tick
    for i in range(n - h):
        entry = c[i]
        if side == "long":
            tp_lev, sl_lev = entry + tp_pts, entry - sl_pts
            for j in range(1, h + 1):
                if hi[i + j] >= tp_lev: labels[i] = 1; break
                if lo[i + j] <= sl_lev: labels[i] = -1; break
        else:
            tp_lev, sl_lev = entry - tp_pts, entry + sl_pts
            for j in range(1, h + 1):
                if lo[i + j] <= tp_lev: labels[i] = 1; break
                if hi[i + j] >= sl_lev: labels[i] = -1; break
    return labels


def spearman_safe(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    mask = x.notna() & pd.Series(y).notna()
    if mask.sum() < 100:
        return (np.nan, int(mask.sum()))
    rho, _ = spearmanr(x[mask], y[mask])
    return (float(rho), int(mask.sum()))


def main():
    print("=" * 80)
    print("Backtest variantes momentum_3b honnetes (sans look-ahead leak)")
    print("=" * 80)

    fpath = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=ES.c.0" / "year=2026" / "month=04" / "data.parquet"
    df = pd.read_parquet(fpath)
    print(f"Loaded {len(df)} bars from {fpath.name}")

    # Labels TBM long + short
    print("Generating TBM labels...")
    label_long = tbm_labels(df, side="long")
    label_short = tbm_labels(df, side="short")

    # === 10 VARIANTES MOMENTUM ===
    variants = {}

    # 1-3. Simple close.diff(N) — baseline
    variants["v01_diff_1"]   = df["close"].diff(1)
    variants["v02_diff_3"]   = df["close"].diff(3)
    variants["v03_diff_5"]   = df["close"].diff(5)
    variants["v04_diff_10"]  = df["close"].diff(10)

    # 5. Log returns
    log_close = np.log(df["close"].replace(0, np.nan))
    variants["v05_logret_3"] = log_close.diff(3) * 1e4  # scaled bp

    # 6. VWAP deviation momentum
    variants["v06_vwap_dev_change"] = (df["close"] - df["vwap_d"]).diff(3)

    # 7. ATR-normalized (compense vol ES vs NQ)
    variants["v07_diff3_atr"] = df["close"].diff(3) / df["atr_14m_pct"].replace(0, np.nan)

    # 8. Z-score rolling 20 bars
    diff3 = df["close"].diff(3)
    variants["v08_diff3_zscore_20"] = (diff3 - diff3.rolling(20).mean()) / diff3.rolling(20).std()

    # 9. EWMA momentum (lisse)
    variants["v09_ema_diff3"] = df["close"].diff(3).ewm(span=5, adjust=False).mean()

    # 10. CVD momentum (delta cumulatif intraday)
    variants["v10_cvd_diff3"] = df["cvd_session"].diff(3)

    # 11. Body momentum (close - open momentum)
    variants["v11_body_diff3"] = (df["close"] - df["open"]).rolling(3, min_periods=1).sum()

    # === EVALUATION ===
    print()
    print(f"{'Variante':<28}{'rho LONG':>12}{'rho SHORT':>12}{'|rho| max':>12}{'verdict':>12}")
    print("-" * 80)

    results = []
    for name, vals in variants.items():
        rho_long, n_long = spearman_safe(vals, pd.Series(label_long))
        rho_short, n_short = spearman_safe(vals, pd.Series(label_short))
        abs_max = max(abs(rho_long), abs(rho_short))

        if abs_max >= 0.10:
            verdict = "STRONG"
        elif abs_max >= 0.05:
            verdict = "OK"
        elif abs_max >= 0.02:
            verdict = "WEAK"
        else:
            verdict = "REJET"

        print(f"  {name:<28}{rho_long:>12.4f}{rho_short:>12.4f}{abs_max:>12.4f}{verdict:>12}")
        results.append({
            "name": name, "rho_long": rho_long, "rho_short": rho_short,
            "abs_max": abs_max, "verdict": verdict,
        })

    # Reference DMP momentum_3b
    print("-" * 80)
    rho_dmp_long, _ = spearman_safe(df["momentum_3b"], pd.Series(label_long))
    rho_dmp_short, _ = spearman_safe(df["momentum_3b"], pd.Series(label_short))
    abs_dmp = max(abs(rho_dmp_long), abs(rho_dmp_short))
    print(f"  {'DMP momentum_3b (buggue)':<28}{rho_dmp_long:>12.4f}{rho_dmp_short:>12.4f}{abs_dmp:>12.4f}{'[SUSPECT]':>12}")
    print("=" * 80)

    # Top 3
    print()
    print("TOP 3 variantes honnetes par |rho| max :")
    sorted_res = sorted(results, key=lambda x: x["abs_max"], reverse=True)
    for i, r in enumerate(sorted_res[:3]):
        print(f"  {i+1}. {r['name']}: |rho|={r['abs_max']:.4f} ({r['verdict']})")

    # Verdict global
    n_strong = sum(1 for r in results if r["verdict"] == "STRONG")
    n_ok = sum(1 for r in results if r["verdict"] == "OK")
    print()
    print(f"VERDICT : {n_strong} STRONG + {n_ok} OK / {len(results)} variantes")
    if n_strong + n_ok >= 1:
        print(f"  => GO definir momentum_3b_v2 = {sorted_res[0]['name']}")
    else:
        print(f"  => NOGO : aucune variante > 0.05, abandonner feature momentum")


if __name__ == "__main__":
    main()
