"""Batch tagger : apply 9 V1 rules to a DataFrame, add 18 columns.

Uses a row-iteration approach (not numba). For 351K bars × 9 rules,
estimated runtime ~5-10 min. Optimization deferred to V2.

Spec : DOCS/specs/2026-04-27-signal-engine-rules-design.md section 4.1
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from CORE.signal_engine_rules.rules import RULES_V1


def _ensure_mins_et(df: pd.DataFrame) -> pd.DataFrame:
    """Compute mins_et from ts_event (US/Eastern) if absent.

    FIX 27/04 (anomaly investigation) : rule_failed_ib_poor_high requires
    mins_et for anti-leak guard pre-10:30. Parquet v5b doesn't have this
    column natively. Compute on-the-fly from ts_event.
    """
    if "mins_et" in df.columns:
        return df
    if "ts_event" not in df.columns:
        return df  # cannot compute, rules will use default 0 (safe block)
    if len(df) == 0:
        df = df.copy()
        df["mins_et"] = pd.Series(dtype="int32")
        return df
    # Ensure datetime dtype (parquet read sometimes returns object on empty df)
    if not pd.api.types.is_datetime64_any_dtype(df["ts_event"]):
        try:
            df = df.copy()
            df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
        except Exception:
            df["mins_et"] = 0
            return df
    df = df.copy()
    ts_et = df["ts_event"].dt.tz_convert("US/Eastern") if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert("US/Eastern")
    df["mins_et"] = (ts_et.dt.hour * 60 + ts_et.dt.minute).astype("int32")
    return df


def apply_rules_to_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all V1 rules to each row, add rule_<name>_dir + rule_<name>_strength cols.

    Args:
        df: input DataFrame with v5b features (must include ts_event, close,
            atr, and feature columns referenced by rules). mins_et is computed
            on-the-fly from ts_event if absent (anti-leak guard for IB rules).

    Returns:
        DataFrame with original cols + 18 new cols (2 per rule).
    """
    # Ensure mins_et is present (required by failed_ib_poor_high anti-leak guard)
    df = _ensure_mins_et(df)

    n = len(df)
    rule_names = list(RULES_V1.keys())

    # Pre-allocate output arrays
    dir_arrays = {name: np.zeros(n, dtype=np.int8) for name in rule_names}
    strength_arrays = {name: np.zeros(n, dtype=np.float32) for name in rule_names}

    # Iterate rows
    for idx, row in enumerate(df.to_dict(orient="records")):
        for name, fn in RULES_V1.items():
            tag = fn(row)
            dir_arrays[name][idx] = tag.direction
            strength_arrays[name][idx] = tag.strength

    df_out = df.copy()
    for name in rule_names:
        df_out[f"rule_{name}_dir"] = dir_arrays[name]
        df_out[f"rule_{name}_strength"] = strength_arrays[name]
    return df_out


def batch_tag_parquet(input_parquet: str, output_parquet: str,
                      verbose: bool = True) -> dict:
    """Read input parquet, apply all rules, write enriched parquet.

    Returns: stats dict {n_bars, n_rules, elapsed_s, fire_counts}
    """
    if verbose:
        print(f"[BATCH TAGGER] Reading {input_parquet}...")
    df = pd.read_parquet(input_parquet)
    if verbose:
        print(f"  Loaded {len(df):,} bars x {df.shape[1]} cols")

    t0 = time.perf_counter()
    df_out = apply_rules_to_dataframe(df)
    elapsed = time.perf_counter() - t0

    fire_counts = {}
    for name in RULES_V1:
        col = f"rule_{name}_dir"
        n_buy = int((df_out[col] == 1).sum())
        n_sell = int((df_out[col] == -1).sum())
        fire_counts[name] = {"buy": n_buy, "sell": n_sell, "total": n_buy + n_sell}
        if verbose:
            print(f"  {name:25s}  BUY={n_buy:>6}  SELL={n_sell:>6}  TOTAL={n_buy+n_sell:>6}")

    if verbose:
        print(f"[BATCH TAGGER] Writing {output_parquet}...")
    df_out.to_parquet(output_parquet, index=False)

    if verbose:
        size_mb = Path(output_parquet).stat().st_size // 1024 // 1024
        print(f"[DONE] Elapsed {elapsed:.1f}s. Output {size_mb} MB.")

    return {
        "n_bars": len(df),
        "n_rules": len(RULES_V1),
        "elapsed_s": elapsed,
        "fire_counts": fire_counts,
    }


def main():
    """CLI entry: python -m CORE.signal_engine_rules.batch_tagger ES (or NQ)."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", choices=["ES", "NQ"])
    parser.add_argument("--input-suffix", default="v5b")
    parser.add_argument("--output-suffix", default="v5c")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    input_parquet = root / f"DATA/datasets/{args.symbol}_dataset_{args.input_suffix}.parquet"
    output_parquet = root / f"DATA/datasets/{args.symbol}_dataset_{args.output_suffix}.parquet"

    if not input_parquet.exists():
        print(f"[ERROR] Input parquet missing : {input_parquet}")
        sys.exit(1)

    batch_tag_parquet(str(input_parquet), str(output_parquet))


if __name__ == "__main__":
    main()
