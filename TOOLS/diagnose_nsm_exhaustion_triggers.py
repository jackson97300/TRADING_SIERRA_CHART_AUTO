"""Diagnostic NSM EXHAUSTION/RANGE triggers - pourquoi T28/T29/T17 ne declenchent jamais.

Mandate Jackson : STEP 2 avant switch V2 live. Identifier si :
  a) Features manquantes (vol_zscore, atr, ib_range, ib_complete, inside_va, prev_vah/val)
  b) Seuils trop stricts (VOL_Z_EXHAUSTION_MIN=2.5, ATR_MULT_EXHAUSTION_RANGE=2.0,
     IB_RANGE_ATR_MAX=1.2)
  c) Combinaison des deux

Strategy : compter sur 11 jours ES quelle fraction de barres passe chaque
sub-condition individuellement, puis intersection.

Usage : python -X utf8 tools/diagnose_nsm_exhaustion_triggers.py
"""
from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    path = ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=05/data.parquet"
    df = pd.read_parquet(path)
    print(f"Loaded {len(df)} bars ES mai 2026")
    print(f"Date range : {df.iloc[0]['ts_event']} -> {df.iloc[-1]['ts_event']}")
    print()

    # Find vol_z col (mapping possible)
    vol_z_col = None
    for c in ["vol_zscore_20", "ctx_vol_z_5", "rvol_zscore"]:
        if c in df.columns:
            vol_z_col = c
            print(f"vol_z col -> {c}")
            break
    if vol_z_col is None:
        print("ABSENT vol_zscore")
    print()

    # Sub-conditions T28 EXHAUSTION_TOP (état candidat = TREND_UP) :
    # 1. vol_z > 2.5
    # 2. close < open
    # 3. (high - low) > 2.0 * atr  [PIVOT TEST]
    # Verify presence atr/high/low/open/close + vol_z
    needed = ["open", "high", "low", "close", "atr_14"]
    for c in needed:
        if c not in df.columns:
            print(f"  MANQUE : {c}")
    print()

    # Use bar_high/bar_low if direct high/low absent
    high = df.get("high", df.get("bar_high"))
    low = df.get("low", df.get("bar_low"))
    open_ = df.get("open", df.get("bar_open"))
    close = df.get("close", df.get("bar_close"))
    atr = df.get("atr_14")
    vol_z = df.get(vol_z_col) if vol_z_col else None

    # Stats brutes
    print("=== STATISTIQUES FEATURES ===")
    if atr is not None:
        print(f"atr_14 : mean={atr.mean():.2f} min={atr.min():.2f} max={atr.max():.2f} "
              f"NaN={atr.isna().sum()}")
    if vol_z is not None:
        print(f"{vol_z_col} : mean={vol_z.mean():.2f} min={vol_z.min():.2f} "
              f"max={vol_z.max():.2f} NaN={vol_z.isna().sum()}")
    if high is not None and low is not None:
        bar_range = high - low
        print(f"bar_range (high-low) : mean={bar_range.mean():.2f} "
              f"p50={bar_range.median():.2f} p90={bar_range.quantile(0.90):.2f} "
              f"p99={bar_range.quantile(0.99):.2f} max={bar_range.max():.2f}")
        if atr is not None:
            ratio = (bar_range / atr).replace([float("inf"), -float("inf")], pd.NA).dropna()
            print(f"bar_range/atr : mean={ratio.mean():.3f} p50={ratio.median():.3f} "
                  f"p90={ratio.quantile(0.90):.3f} p99={ratio.quantile(0.99):.3f} "
                  f"max={ratio.max():.3f}")

    print()
    print("=== T28/T29 SUB-CONDITIONS (sur TOUTES bars, pas filtre TREND_UP) ===")
    if vol_z is not None:
        n_volz_25 = (vol_z > 2.5).sum()
        n_volz_20 = (vol_z > 2.0).sum()
        n_volz_15 = (vol_z > 1.5).sum()
        n_volz_10 = (vol_z > 1.0).sum()
        print(f"vol_z > 2.5 (actuel) : {n_volz_25}  ({n_volz_25/len(df)*100:.2f}%)")
        print(f"vol_z > 2.0          : {n_volz_20}  ({n_volz_20/len(df)*100:.2f}%)")
        print(f"vol_z > 1.5          : {n_volz_15}  ({n_volz_15/len(df)*100:.2f}%)")
        print(f"vol_z > 1.0          : {n_volz_10}  ({n_volz_10/len(df)*100:.2f}%)")

    if high is not None and low is not None and atr is not None:
        bar_range = high - low
        for m in [2.0, 1.5, 1.2, 1.0, 0.8]:
            mask = bar_range > m * atr
            n = mask.sum()
            print(f"bar_range > {m} * atr : {n}  ({n/len(df)*100:.2f}%)")

    # Intersection T28 (sans state filter): vol_z>2.5 AND close<open AND range>2*atr
    if all(x is not None for x in [vol_z, close, open_, high, low, atr]):
        bar_range = high - low
        m_volz = vol_z > 2.5
        m_red = close < open_
        for m in [2.0, 1.5, 1.2, 1.0, 0.8]:
            m_range = bar_range > m * atr
            m_all = m_volz & m_red & m_range
            print(f"T28 conds (vol_z>2.5 & red & range>{m}*atr) : {m_all.sum()}  "
                  f"({m_all.sum()/len(df)*100:.2f}%)")

    print()
    print("=== T17 RANGE_RESPECTED SUB-CONDITIONS ===")
    for c in ["ib_complete", "ib_range", "value_area_high_dev", "inside_va",
              "prev_vah", "prev_val"]:
        if c in df.columns:
            v = df[c]
            if v.dtype == bool or set(v.dropna().unique()).issubset({0, 1, True, False}):
                print(f"  {c} : True count = {v.sum()}/{len(df)} ({v.sum()/len(df)*100:.2f}%)")
            else:
                print(f"  {c} : NaN={v.isna().sum()} mean={v.mean():.2f}")
        else:
            print(f"  {c} : ABSENT")

    # Look for similar
    print()
    print("=== COLS pertinentes 'ib_'/'va_'/'prev_va*' ===")
    for c in df.columns:
        lc = c.lower()
        if "ib_" in lc or "va_" in lc or "prev_va" in lc or "value_area" in lc:
            print(f"  {c}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
