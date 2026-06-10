"""
fix_leaks_v5_to_v5b.py — Patch anti-leak features broadcast session.

Applique les masks NaN sur 6 features détectées leaky par SHAP analysis 27/04 :
  - dist_ovn_high_pct (#1 SHAP, domine 4× le #2)
  - dist_ovn_low_pct
  - dist_ib_high_pct (#5 SHAP)
  - dist_ib_low_pct (#8 SHAP)
  - above_open_830 (#4 SHAP)
  - above_open_930 (#2 SHAP)
  - dist_open_830_pct
  - dist_open_930_pct
  - ovn_high, ovn_low, ib_high, ib_low (raw)

Mask :
  - OVN : NaN pendant session OVN active (mins_et < 570 OU mins_et >= 1080)
  - IB  : NaN avant 10:30 ET (mins_et < 630)
  - Open 08:30 : NaN avant 08:30 ET (mins_et < 510)
  - Open 09:30 : NaN avant 09:30 ET (mins_et < 570)

Output : ES_dataset_v5b.parquet, NQ_dataset_v5b.parquet
Logique cohérente avec phase_b_plus_engine.py + phase_b_helpers.py post-fix 27/04.

Auteur : MIA Trading System V2
Date   : 2026-04-27 21:00
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def patch_leaks(symbol: str) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print(f"  FIX LEAKS — {symbol}")
    print(f"{'='*60}")

    src = ROOT / f"DATA/datasets/{symbol}_dataset_v5.parquet"
    df = pd.read_parquet(src)
    print(f"  Loaded {len(df):,} bars, {df.shape[1]} cols")

    # mins_et
    ts_et = df["ts_event"].dt.tz_convert("US/Eastern") if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert("US/Eastern")
    mins_et = (ts_et.dt.hour * 60 + ts_et.dt.minute).values

    closes = df["close"].values

    # ─── FIX 1 : OVN ───────────────────────────────────────────────
    # OVN active = avant 09:30 ET (570) OU apres 18:00 ET (1080)
    is_ovn_active = (mins_et < 570) | (mins_et >= 1080)
    n_ovn_active = int(is_ovn_active.sum())
    print(f"  [FIX 1] OVN active bars: {n_ovn_active:,} ({n_ovn_active/len(df)*100:.1f}%) → mask NaN")

    if "ovn_high" in df.columns:
        df.loc[is_ovn_active, "ovn_high"] = np.nan
        df.loc[is_ovn_active, "ovn_low"] = np.nan
        # Recalculer dist
        df["dist_ovn_high_pct"] = ((closes - df["ovn_high"].values) / closes * 100).astype("float32")
        df["dist_ovn_low_pct"] = ((closes - df["ovn_low"].values) / closes * 100).astype("float32")
        # ovn_broken : valide seulement post-OVN
        if "ovn_broken_up" in df.columns:
            df.loc[is_ovn_active, "ovn_broken_up"] = 0
            df.loc[is_ovn_active, "ovn_broken_dn"] = 0

    # ─── FIX 2 : IB ────────────────────────────────────────────────
    # IB pas complete = avant 10:30 ET (mins_et < 630)
    is_pre_ib_close = mins_et < 630
    n_pre_ib = int(is_pre_ib_close.sum())
    print(f"  [FIX 2] Pre-IB close bars: {n_pre_ib:,} ({n_pre_ib/len(df)*100:.1f}%) → mask NaN")

    if "ib_high" in df.columns:
        df.loc[is_pre_ib_close, "ib_high"] = np.nan
        df.loc[is_pre_ib_close, "ib_low"] = np.nan
        # Recalculer dist + range
        df["dist_ib_high_pct"] = ((df["ib_high"].values - closes) / closes * 100).astype("float64")
        df["dist_ib_low_pct"] = ((closes - df["ib_low"].values) / closes * 100).astype("float64")
        if "ib_range_ticks" in df.columns:
            df["ib_range_ticks"] = ((df["ib_high"] - df["ib_low"]) / 0.25).astype("float64")
        if "ib_range" in df.columns:
            df["ib_range"] = df["ib_high"] - df["ib_low"]

    # ─── FIX 3 : Open 08:30 + 09:30 ────────────────────────────────
    is_pre_830 = mins_et < 510
    is_pre_930 = mins_et < 570
    print(f"  [FIX 3] Pre-08:30 bars: {is_pre_830.sum():,} ({is_pre_830.sum()/len(df)*100:.1f}%) → mask open_830")
    print(f"          Pre-09:30 bars: {is_pre_930.sum():,} ({is_pre_930.sum()/len(df)*100:.1f}%) → mask open_930")

    if "open_830_et" in df.columns:
        df.loc[is_pre_830, "open_830_et"] = np.nan
        df["dist_open_830_pct"] = ((closes - df["open_830_et"].values) / closes * 100).astype("float32")
        df["above_open_830"] = (closes > df["open_830_et"].values).astype("int8")
        # Mask above_open_830 a 0 (cohérent avec absence info) sur is_pre_830
        df.loc[is_pre_830, "above_open_830"] = 0

    if "open_930_et" in df.columns:
        df.loc[is_pre_930, "open_930_et"] = np.nan
        df["dist_open_930_pct"] = ((closes - df["open_930_et"].values) / closes * 100).astype("float32")
        df["above_open_930"] = (closes > df["open_930_et"].values).astype("int8")
        df.loc[is_pre_930, "above_open_930"] = 0

    # Stats post-fix
    if "dist_ovn_high_pct" in df.columns:
        print(f"\n  Post-fix stats :")
        for col in ["dist_ovn_high_pct", "dist_ib_high_pct", "above_open_930", "above_open_830"]:
            if col in df.columns:
                s = df[col]
                print(f"    {col:<25s}  NaN={s.isna().sum():,} ({s.isna().sum()/len(s)*100:.1f}%)  mean={s.mean():+.4f}")

    out = ROOT / f"DATA/datasets/{symbol}_dataset_v5b.parquet"
    df.to_parquet(out, index=False)
    print(f"\n  [SAVED] {out} ({out.stat().st_size // 1024 // 1024} MB)")
    return df


def main():
    print("=" * 70)
    print("FIX LEAKS v5 → v5b (masks anti-leak features broadcast session)")
    print("=" * 70)
    for sym in ["ES", "NQ"]:
        patch_leaks(sym)

    print("\n" + "=" * 70)
    print("DONE — datasets v5b prets pour re-train ML + re-SHAP")
    print("=" * 70)


if __name__ == "__main__":
    main()
