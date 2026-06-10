"""
Test killer (agent ml-trainer 17/04/2026) :

Avant de conclure que les combinaisons SHAP revelent un edge, il faut mesurer
la BASELINE p_primary SEUL. Si p_primary > p75 seul donne deja 75-80% WR,
alors les interactions "X × p_primary" ne sont QUE de la tautologie decoree.

Output : tableau WR(p_primary >= threshold) pour ES buy et sell.

Critere :
  - Si WR(p_primary > 0.75) >= 78% → interactions SHAP sont tautologie (NO-GO)
  - Si WR(p_primary > 0.75) entre 65-75% ET hh_WR 82% → vrai edge contextuel
  - Si WR(p_primary > 0.75) < 60% → primary inutilisable
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

MODELS_DIR = Path("DATA/MODELS")
DATASETS_DIR = Path("DATA/DATASETS")


def load_primary(symbol: str, side: str):
    path = MODELS_DIR / f"{symbol}_{side}_model.pkl"
    with open(path, "rb") as f:
        return pickle.load(f)


def load_config(symbol: str, side: str) -> dict:
    import json
    path = MODELS_DIR / f"{symbol}_{side}_config.json"
    with open(path, "r") as f:
        return json.load(f)


def load_dataset(symbol: str) -> pd.DataFrame:
    for version in ["v3", "v2"]:
        path = DATASETS_DIR / f"{symbol}_dataset_{version}.parquet"
        if path.exists():
            return pd.read_parquet(path)
    raise FileNotFoundError(f"No dataset for {symbol}")


def test_killer(symbol: str, side: str):
    print(f"\n{'='*80}")
    print(f"  TEST KILLER — {symbol} {side.upper()}")
    print(f"{'='*80}")

    primary = load_primary(symbol, side)
    config = load_config(symbol, side)
    df = load_dataset(symbol)

    features = [f for f in config["features"] if f in df.columns]
    X = df[features]
    p_primary = primary.predict_proba(X)[:, 1]

    target = 1 if side == "buy" else -1

    # Label reel : 1 si trade primary aurait gagne (TP touche dans le sens target)
    y_correct = (df["label"].values == target).astype(int)

    # Split primary_active (primary predit trade = p_primary > threshold_training)
    # Pour l'analyse, on regarde TOUS les niveaux p_primary.
    print(f"\n  Dataset : {len(df)} rows")
    print(f"  Baseline (toutes barres) : WR = {y_correct.mean():.1%}")
    print(f"  Primary actif (p>{config.get('train_config', {}).get('primary_threshold', 0.30)}) : "
          f"WR = {y_correct[p_primary > 0.30].mean():.1%}")

    # Percentiles p_primary pour reference
    p_p75 = np.quantile(p_primary, 0.75)
    p_p90 = np.quantile(p_primary, 0.90)
    print(f"\n  p_primary percentiles : p75={p_p75:.3f}, p90={p_p90:.3f}, max={p_primary.max():.3f}")

    # Table des WR par seuil
    print(f"\n  {'Threshold':>10s}  {'N':>6s}  {'N%':>6s}  {'WR':>7s}  {'Lift_base':>10s}")
    print(f"  {'-'*50}")

    base_wr = y_correct.mean()
    thresholds = [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
    results = []
    for thr in thresholds:
        mask = p_primary >= thr
        n = int(mask.sum())
        if n < 10:
            print(f"  {thr:>10.2f}  {n:>6d}  {'-':>6s}  {'n/a':>7s}  {'n/a':>10s}")
            continue
        wr = y_correct[mask].mean()
        pct = 100.0 * n / len(p_primary)
        lift = wr / base_wr if base_wr > 0 else np.nan
        print(f"  {thr:>10.2f}  {n:>6d}  {pct:>5.1f}%  {wr:>6.1%}  {lift:>9.2f}x")
        results.append({"threshold": thr, "n": n, "wr": float(wr), "lift": float(lift)})

    # Comparaison avec meta hh cell
    print(f"\n  COMPARAISON avec meta model (p_primary_p75 × day_type_p75 hh) :")
    print(f"  ES {side} hh_WR observed = {'81.9%' if side == 'buy' else '87.3%'}")

    wr_at_p75 = y_correct[p_primary >= p_p75].mean()
    print(f"  WR(p_primary >= p75={p_p75:.3f}) SEUL = {wr_at_p75:.1%}")

    expected_hh = 0.819 if side == "buy" else 0.873
    gap = expected_hh - wr_at_p75
    print(f"  GAP additionnel day_type : {gap*100:+.1f} points WR")
    print(f"  VERDICT : ", end="")
    if gap < 0.03:
        print(f"TAUTOLOGIE — day_type n'ajoute quasi rien ({gap*100:+.1f} points)")
    elif gap < 0.07:
        print(f"EDGE MARGINAL — {gap*100:+.1f} points, probablement noise")
    else:
        print(f"EDGE REEL POTENTIEL — +{gap*100:.1f} points, a valider OOS")

    return results, wr_at_p75, expected_hh


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None, choices=["ES", "NQ"])
    ap.add_argument("--side", default=None, choices=["buy", "sell"])
    args = ap.parse_args()

    symbols = [args.symbol] if args.symbol else ["ES"]
    sides = [args.side] if args.side else ["buy", "sell"]

    all_results = []
    for symbol in symbols:
        for side in sides:
            try:
                results, wr_p75, hh_wr = test_killer(symbol, side)
                all_results.append({
                    "symbol": symbol, "side": side,
                    "wr_p_primary_p75": wr_p75,
                    "wr_hh_meta": hh_wr,
                    "gap_additionnel": hh_wr - wr_p75,
                })
            except Exception as e:
                print(f"\n[ERR] {symbol} {side}: {e}")
                import traceback
                traceback.print_exc()

    print(f"\n\n{'='*80}")
    print(f"  VERDICT FINAL")
    print(f"{'='*80}\n")
    print(f"  {'Setup':<12s}  {'WR p75 seul':>12s}  {'WR hh meta':>12s}  {'Gap':>7s}  {'Verdict':<30s}")
    print(f"  {'-'*75}")
    for r in all_results:
        verdict = "TAUTOLOGIE" if r["gap_additionnel"] < 0.03 else \
                  "MARGINAL" if r["gap_additionnel"] < 0.07 else \
                  "EDGE REEL"
        print(f"  {r['symbol']} {r['side']:<8s}  "
              f"{r['wr_p_primary_p75']:>11.1%}  "
              f"{r['wr_hh_meta']:>11.1%}  "
              f"{r['gap_additionnel']*100:>+6.1f}  "
              f"{verdict:<30s}")


if __name__ == "__main__":
    main()
