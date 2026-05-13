"""test_engine_parity.py — outil reutilisable test parite batch vs streaming.

Phase 3a Jour 5 du Chantier 3 (Live Enricher Option D), reframe Plan agent.

Plan agent verdict Jour 5 : refacto engines streaming-aware DOIT etre validee
par test parite strict pour eviter Pattern 11 V1 (refacto 13 engines avec
drift cumulatif si critere lache).

Critere parite strict (Plan agent recommandations) :
  - Colonnes int / bool / categorial : == exact (pas de tolerance)
  - Colonnes float                  : abs_diff.max() < 1e-9 (IEEE 754)
  - NaN mask                        : df_batch.isna() == df_stream.isna()
  - Structure                       : memes colonnes + memes dtypes

Outil reutilisable :
  test_engine_parity(
      engine_name="vix_lite",
      batch_fn=enrich_vix_lite,           # API batch existante
      streaming_fn=enrich_vix_lite_streaming,  # API streaming nouvelle
      state_factory=VixLiteState,
      input_df=df_real,
      float_atol=1e-9,
  ) -> dict[str, Any]  # report

Usage CLI :
  python -m tools.test_engine_parity --engine vix_lite

Auteur : MIA Trading System V2
  v1.0 (2026-05-13 nuit) : version initiale Phase 3a Jour 5
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))


def _nan_mask_match(s_batch: pd.Series, s_stream: pd.Series) -> tuple[bool, int]:
    """Compare NaN mask exact. Returns (match, n_diff)."""
    mask_batch = s_batch.isna()
    mask_stream = s_stream.isna()
    diff = (mask_batch != mask_stream)
    return (not diff.any(), int(diff.sum()))


def _value_match(
    s_batch: pd.Series,
    s_stream: pd.Series,
    float_atol: float = 1e-9,
) -> tuple[bool, dict]:
    """Compare valeurs non-NaN. int/bool: ==, float: abs_diff < atol.

    Returns (match, stats).
    """
    # Compare sur les bars ou les 2 sont non-NaN
    both_valid = s_batch.notna() & s_stream.notna()
    if both_valid.sum() == 0:
        return (True, {"n_compare": 0, "all_nan_match": True})

    b = s_batch[both_valid]
    st = s_stream[both_valid]

    # Type detection
    is_int = pd.api.types.is_integer_dtype(b) and pd.api.types.is_integer_dtype(st)
    is_bool = pd.api.types.is_bool_dtype(b) and pd.api.types.is_bool_dtype(st)
    is_datetime = pd.api.types.is_datetime64_any_dtype(b) and pd.api.types.is_datetime64_any_dtype(st)
    is_object = pd.api.types.is_object_dtype(b) and pd.api.types.is_object_dtype(st)
    is_string = pd.api.types.is_string_dtype(b) and pd.api.types.is_string_dtype(st)

    if is_int or is_bool or is_datetime or is_object or is_string:
        # Exact match required (passthrough columns identiques)
        match_mask = (b == st)
        n_diff = int((~match_mask).sum())
        dtype_label = (
            "int" if is_int else "bool" if is_bool else
            "datetime" if is_datetime else "string" if is_string else "object"
        )
        return (n_diff == 0, {
            "n_compare": int(both_valid.sum()),
            "n_diff_exact": n_diff,
            "dtype": dtype_label,
        })
    else:
        # Float : abs_diff.max() < atol
        try:
            diff = (b.astype("float64") - st.astype("float64")).abs()
        except (TypeError, ValueError) as e:
            return (False, {"error": f"dtype mismatch: {e}"})
        max_diff = float(diff.max())
        return (max_diff < float_atol, {
            "n_compare": int(both_valid.sum()),
            "max_diff": max_diff,
            "atol": float_atol,
            "dtype": "float",
        })


def test_engine_parity(
    engine_name: str,
    batch_fn: Callable[[pd.DataFrame], pd.DataFrame],
    streaming_fn: Callable[[dict, Any], dict],
    state_factory: Callable[[], Any],
    input_df: pd.DataFrame,
    float_atol: float = 1e-9,
    verbose: bool = True,
) -> dict[str, Any]:
    """Test parite strict batch vs streaming pour 1 engine.

    Args:
        engine_name : nom logique pour affichage
        batch_fn(df) -> df enriched
        streaming_fn(row_dict, state) -> enriched_row_dict
        state_factory() -> nouveau state (creer 1 fois pour streaming complet)
        input_df : DataFrame entree (avant enrichissement)
        float_atol : tolerance abs_diff pour floats (default IEEE 754)
        verbose : print rapport

    Returns:
        dict report avec keys :
          status : "PASS" / "FAIL"
          n_rows : nb rows testes
          n_cols_compared : nb colonnes comparees
          failures : list[dict] des colonnes en echec
          summary : str resumee
    """
    # 1. Run batch
    df_batch = batch_fn(input_df.copy())

    # 2. Run streaming row-by-row
    state = state_factory()
    rows_stream = []
    for _, row in input_df.iterrows():
        enriched = streaming_fn(row.to_dict(), state)
        rows_stream.append(enriched)
    df_stream = pd.DataFrame(rows_stream, index=input_df.index)

    # 3. Compare structure
    cols_batch = set(df_batch.columns)
    cols_stream = set(df_stream.columns)
    missing_in_stream = cols_batch - cols_stream
    extra_in_stream = cols_stream - cols_batch
    common = cols_batch & cols_stream

    # 4. Compare colonnes communes
    failures = []
    for col in sorted(common):
        s_batch = df_batch[col]
        s_stream = df_stream[col]

        nan_match, n_nan_diff = _nan_mask_match(s_batch, s_stream)
        val_match, val_stats = _value_match(s_batch, s_stream, float_atol=float_atol)

        if not nan_match:
            failures.append({
                "col": col, "reason": "NaN mask mismatch",
                "n_diff": n_nan_diff,
            })
        if not val_match:
            failures.append({
                "col": col, "reason": "value mismatch",
                "stats": val_stats,
            })

    # 5. Build report
    report = {
        "engine_name": engine_name,
        "n_rows": len(input_df),
        "n_cols_input": len(input_df.columns),
        "n_cols_batch": len(df_batch.columns),
        "n_cols_stream": len(df_stream.columns),
        "n_cols_common": len(common),
        "n_cols_missing_in_stream": len(missing_in_stream),
        "n_cols_extra_in_stream": len(extra_in_stream),
        "missing_in_stream": sorted(missing_in_stream),
        "extra_in_stream": sorted(extra_in_stream),
        "n_failures": len(failures),
        "failures": failures,
        "status": "PASS" if (
            len(failures) == 0
            and len(missing_in_stream) == 0
        ) else "FAIL",
        "float_atol": float_atol,
    }

    if verbose:
        _print_report(report)

    return report


def _print_report(report: dict) -> None:
    """Print rapport formatte console."""
    print("=" * 70)
    print(f"PARITE BATCH vs STREAMING — engine '{report['engine_name']}'")
    print("=" * 70)
    print(f"  Status                  : {report['status']}")
    print(f"  Rows testees            : {report['n_rows']}")
    print(f"  Cols (input/batch/stream/common) : "
          f"{report['n_cols_input']}/{report['n_cols_batch']}/"
          f"{report['n_cols_stream']}/{report['n_cols_common']}")
    print(f"  Float atol              : {report['float_atol']}")
    if report['n_cols_missing_in_stream'] > 0:
        print(f"  MISSING in stream       : {report['missing_in_stream']}")
    if report['n_cols_extra_in_stream'] > 0:
        print(f"  EXTRA in stream         : {report['extra_in_stream']}")
    if report['failures']:
        print(f"  FAILURES ({len(report['failures'])}) :")
        for f in report['failures'][:10]:
            print(f"    - {f}")
    print("=" * 70)


def _test_vix_lite():
    """Test parite vix_lite (pilote stateless Phase 3a Jour 5)."""
    from vix_lite_reader import (
        load_vix_lite_jsonl, enrich_vix_lite,
        VixLiteState, enrich_vix_lite_streaming,
    )

    # Load donnees reelles VIX (sync VPS si dispo)
    today = date(2026, 5, 13)
    df = load_vix_lite_jsonl(today - timedelta(days=2), today)
    if df.empty:
        print("[SKIP] aucun fichier VIX_Lite local pour test vix_lite parity")
        return

    print(f"\nTest vix_lite parite sur {len(df)} rows reelles...")
    report = test_engine_parity(
        engine_name="vix_lite",
        batch_fn=enrich_vix_lite,
        streaming_fn=enrich_vix_lite_streaming,
        state_factory=VixLiteState,
        input_df=df,
        float_atol=1e-9,
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="vix_lite",
                        choices=["vix_lite"])
    args = parser.parse_args()

    if args.engine == "vix_lite":
        report = _test_vix_lite()
        if report and report["status"] != "PASS":
            sys.exit(1)


if __name__ == "__main__":
    main()
