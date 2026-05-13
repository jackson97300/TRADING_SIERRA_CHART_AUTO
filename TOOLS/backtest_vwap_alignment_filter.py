"""backtest_vwap_alignment_filter.py — test FILTRE vwap_alignment_score.

Phase 1b v0.4 (13/05/2026 nuit) : suite avis market-analyst, on teste le
composite `vwap_alignment_score` (entier -3 a +3) en mode FILTRE et pas
en signal direct.

Methode (anti pattern 11) :
  1. Pre-register buckets [-3, -2, -1, 0, +1, +2, +3]
  2. Walk-forward : split avril 2026 en 4 semaines, train sem 1-2, test sem 3-4
  3. Pour chaque bucket : WR LONG et WR SHORT separes (regime baissier VIX>30
     = edge artificiel possible sur SHORT only, caveat market-analyst)
  4. Critere GO : WR(|score|>=2) - WR(|score|<=1) >= 10pp ET stabilite cross-fold
  5. Bonferroni : 7 buckets x 2 directions = 14 tests, alpha/14 = 0.0036
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))
from phase_b_v6_complete import add_vwap_alignment_score  # noqa


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


def wr_by_bucket(score, labels, bucket_values=(-3, -2, -1, 0, 1, 2, 3)):
    """Calcule WR par bucket score. Ignore labels=0 (timeout TBM)."""
    rows = []
    for b in bucket_values:
        mask = (score == b) & (labels != 0)
        if mask.sum() < 50:
            rows.append({"bucket": b, "n": int(mask.sum()), "wr": np.nan, "wins": 0})
            continue
        wins = (labels[mask] == 1).sum()
        wr = wins / mask.sum() * 100.0
        rows.append({"bucket": b, "n": int(mask.sum()), "wr": wr, "wins": int(wins)})
    return pd.DataFrame(rows)


def main():
    print("=" * 80)
    print("Backtest FILTRE vwap_alignment_score (entier -3 a +3)")
    print("Methode : walk-forward 4 semaines + WR par bucket LONG/SHORT")
    print("=" * 80)

    fpath = ROOT / "DATA" / "datasets" / "v4_enriched" / "symbol=ES.c.0" / "year=2026" / "month=04" / "data.parquet"
    df = pd.read_parquet(fpath)
    df["ts_event"] = pd.to_datetime(df["ts_event"])
    print(f"Loaded {len(df)} bars from {fpath.name}")

    # Calcul vwap_alignment_score
    df = add_vwap_alignment_score(df)
    print(f"Distribution vwap_alignment_score :")
    print(df["vwap_alignment_score"].value_counts(normalize=True).sort_index().to_string())
    print()

    # Labels TBM long + short
    label_long = tbm(df, side="long")
    label_short = tbm(df, side="short")

    # Walk-forward 4 semaines (avril 2026)
    df["week_idx"] = df["ts_event"].dt.isocalendar().week - df["ts_event"].dt.isocalendar().week.min()
    df["week_idx"] = df["week_idx"].clip(0, 3)
    score = df["vwap_alignment_score"].values

    print("=" * 80)
    print("WR par bucket - GLOBAL (toutes semaines)")
    print("=" * 80)
    print("LONG :")
    wr_long_global = wr_by_bucket(score, label_long)
    print(wr_long_global.to_string(index=False))
    print()
    print("SHORT :")
    wr_short_global = wr_by_bucket(score, label_short)
    print(wr_short_global.to_string(index=False))

    # Walk-forward : train sem 0-1, test sem 2-3
    train_mask = df["week_idx"].isin([0, 1]).values
    test_mask = df["week_idx"].isin([2, 3]).values

    print()
    print("=" * 80)
    print("Walk-forward : train sem 0-1, test sem 2-3")
    print("=" * 80)

    for side, labels, name in [("long", label_long, "LONG"), ("short", label_short, "SHORT")]:
        print(f"\n{name} :")
        wr_train = wr_by_bucket(score[train_mask], labels[train_mask])
        wr_test = wr_by_bucket(score[test_mask], labels[test_mask])
        cmp = wr_train.merge(wr_test, on="bucket", suffixes=("_train", "_test"))
        cmp = cmp[["bucket", "n_train", "wr_train", "n_test", "wr_test"]]
        print(cmp.to_string(index=False))

    # CRITERE GO : WR(|score|>=2) - WR(|score|<=1) >= 10pp
    print()
    print("=" * 80)
    print("CRITERE GO/NOGO (market-analyst): WR(|score|>=2) - WR(|score|<=1) >= 10pp")
    print("=" * 80)

    for direction, labels in [("LONG", label_long), ("SHORT", label_short)]:
        # signed match : LONG -> score >= 2, SHORT -> score <= -2
        if direction == "LONG":
            confluence_mask = (score >= 2) & (labels != 0)
            mitige_mask = (score >= -1) & (score <= 1) & (labels != 0)
        else:
            confluence_mask = (score <= -2) & (labels != 0)
            mitige_mask = (score >= -1) & (score <= 1) & (labels != 0)

        wr_conf = 100 * (labels[confluence_mask] == 1).sum() / max(1, confluence_mask.sum())
        wr_mit = 100 * (labels[mitige_mask] == 1).sum() / max(1, mitige_mask.sum())
        delta = wr_conf - wr_mit
        verdict = "GO" if delta >= 10 else ("MEDIUM" if delta >= 5 else "NOGO")
        print(f"  {direction}: WR_confluence={wr_conf:.1f}% (n={confluence_mask.sum()}) "
              f"vs WR_mitige={wr_mit:.1f}% (n={mitige_mask.sum()}) "
              f"=> delta={delta:+.1f}pp [{verdict}]")


if __name__ == "__main__":
    main()
