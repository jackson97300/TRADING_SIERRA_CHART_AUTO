"""relabel_v5d_with_kssl.py — Re-label v5d avec K_SL custom (regle d'or Jackson).

Charge ES/NQ_dataset_v5d.parquet (deja enrichi rules tags V1+V2), recalcule
uniquement les labels Triple Barrier avec K_SL custom, ecrit v5e.parquet.

Preserve toutes les features ML (rules tags, BN, MQ, etc.) — change que les
labels et sample_weight pour cohérence labels↔simulator avec K_SL plus large.

Usage : python -X utf8 CORE/relabel_v5d_with_kssl.py --k-sl 2.5 --output v5e
        python -X utf8 CORE/relabel_v5d_with_kssl.py --k-sl 4.0 --k-tp-ratio 2.0 --output v5e
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))

# Reuse Triple Barrier numba kernel from label_v5_dataset
from label_v5_dataset import (
    _label_atr_dynamic,
    compute_sample_weight_uniqueness,
    TICK_SIZE,
    FORWARD_BARS,
)


def relabel_dataset(symbol: str, k_sl: float, k_tp_ratio: float,
                     output_suffix: str = "v5e") -> Path:
    """Re-label v5d.parquet avec nouveau K_SL, ecrit v5{output_suffix}.parquet."""
    print(f"\n{'='*70}")
    print(f"  RE-LABEL {symbol} : K_SL={k_sl}, K_TP_ratio={k_tp_ratio}, output={output_suffix}")
    print(f"{'='*70}")

    src = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_v5d.parquet"
    dst = ROOT / "DATA" / "datasets" / f"{symbol}_dataset_{output_suffix}.parquet"
    if not src.exists():
        print(f"  [FAIL] Source absent : {src}")
        return None

    print(f"  [1/4] Loading {src.name}...")
    df = pd.read_parquet(src)
    df = df.sort_values("ts").reset_index(drop=True)
    print(f"        {len(df):,} bars × {df.shape[1]} cols")

    tick = TICK_SIZE[symbol]
    highs = df["high"].values.astype(np.float64)
    lows = df["low"].values.astype(np.float64)
    closes = df["close"].values.astype(np.float64)
    atrs = df["atr"].values.astype(np.float64)

    median_atr = np.nanmedian(atrs)
    median_sl = k_sl * median_atr
    median_tp = k_sl * k_tp_ratio * median_atr
    print(f"  [2/4] Triple Barrier ATR-dynamique...")
    print(f"        ATR median = {median_atr:.2f}t")
    print(f"        SL median  = {median_sl:.1f}t  ({median_sl*tick:.2f}pt)")
    print(f"        TP median  = {median_tp:.1f}t  ({median_tp*tick:.2f}pt)")

    t0 = time.perf_counter()
    labels, exit_offsets, realized = _label_atr_dynamic(
        highs, lows, closes, atrs, k_sl, k_tp_ratio, FORWARD_BARS, tick
    )
    print(f"        Done in {time.perf_counter()-t0:.1f}s")

    print(f"  [3/4] Sample weight uniqueness Lopez ch.4...")
    t0 = time.perf_counter()
    sample_weight = compute_sample_weight_uniqueness(labels, exit_offsets)
    print(f"        Done in {time.perf_counter()-t0:.1f}s, mean sw = {sample_weight.mean():.3f}")

    n_buy = int((labels == 1).sum())
    n_sell = int((labels == -1).sum())
    n_hold = int((labels == 0).sum())
    print(f"  [4/4] Labels : BUY={n_buy} ({n_buy/len(df)*100:.1f}%), "
          f"SELL={n_sell} ({n_sell/len(df)*100:.1f}%), "
          f"HOLD={n_hold} ({n_hold/len(df)*100:.1f}%)")
    if n_buy + n_sell > 0:
        print(f"        Balance BUY/(BUY+SELL) = {n_buy/(n_buy+n_sell):.3f}")

    # Override labels + sample_weight + exit_offset + realized_pts
    df["label"] = labels
    df["exit_offset"] = exit_offsets
    df["realized_pts"] = realized
    df["sample_weight"] = sample_weight

    print(f"        Saving {dst.name}...")
    df.to_parquet(dst, index=False)
    print(f"  [OK] {dst} ({dst.stat().st_size // 1024 // 1024} MB)")
    return dst


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k-sl", type=float, default=2.5,
                        help="K_SL multiplier (default 2.5 = laisser respirer Jackson)")
    parser.add_argument("--k-tp-ratio", type=float, default=2.0,
                        help="K_TP_ratio (default 2.0 standard)")
    parser.add_argument("--output", type=str, default="v5e",
                        help="Output suffix (default v5e)")
    parser.add_argument("--symbol", type=str, default=None,
                        help="ES, NQ, ou both (default both)")
    args = parser.parse_args()

    print("=" * 70)
    print("RE-LABEL V5D — Triple Barrier with custom K_SL (Jackson regle d'or)")
    print("=" * 70)
    print(f"  K_SL          : {args.k_sl}  (vs default 1.5)")
    print(f"  K_TP_ratio    : {args.k_tp_ratio}")
    print(f"  Output suffix : {args.output}")

    syms = [args.symbol.upper()] if args.symbol else ["ES", "NQ"]
    for sym in syms:
        relabel_dataset(sym, k_sl=args.k_sl, k_tp_ratio=args.k_tp_ratio,
                        output_suffix=args.output)

    print("\n" + "=" * 70)
    print("DONE — re-labeled datasets ready")
    print("=" * 70)
    print("\nNext step : re-train Optuna with new dataset")
    print(f"  python -X utf8 CORE/train_lightgbm.py --{args.output} --no-strict --symbol ES --skip-mda --threshold-floor 0.45")


if __name__ == "__main__":
    main()
