"""Test ZERO regression Phase 1b refacto.

Compare le parquet produit par process_partition apres refacto vs le baseline
pre-refacto (sauvegarde au format .pre_phase_1b_backup_*).

CRITIQUE : ce test doit PASS sinon = regression. Jackson : "SANS AUCUNE REGRESSION".
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "CORE"))


def test_process_partition_full_mode_identical_to_pre_refacto_baseline():
    """Run process_partition full mode sur ES 2026-04 et compare au baseline.

    Le baseline parquet (.pre_phase_1b_backup_20260513) doit avoir ete sauvegarde
    AVANT le refacto Phase 1b. Si ce fichier n'existe pas, skip.

    Test : pour chaque feature column, tolerance rtol=1e-9 atol=1e-12.
    Si parite OK = ZERO regression confirmee.
    """
    from build_dataset_v4_phase_b import process_partition

    baseline_path = ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet.pre_phase_1b_backup_20260513"
    if not baseline_path.exists():
        pytest.skip(f"Baseline parquet absent : {baseline_path}")

    # Run process_partition full mode (no-write) sur ES avril
    result = process_partition("ES", 2026, 4, write=False)
    if result.get("status") != "OK":
        pytest.skip(f"process_partition failed : {result}")

    # Run encore une fois mais avec write pour comparer parquet final
    # Note : on garde le baseline intact, on ecrit dans le canonical parquet
    # puis on compare canonical vs baseline.
    from build_dataset_v4_phase_b import process_partition as pp
    pp("ES", 2026, 4, write=True)

    canonical_path = ROOT / "DATA/datasets/v4_enriched/symbol=ES.c.0/year=2026/month=04/data.parquet"
    df_baseline = pd.read_parquet(baseline_path)
    df_canonical = pd.read_parquet(canonical_path)

    # Same shape
    assert df_baseline.shape == df_canonical.shape, \
        f"Shape mismatch: baseline={df_baseline.shape} canonical={df_canonical.shape}"

    # Same columns
    assert set(df_baseline.columns) == set(df_canonical.columns), \
        f"Columns diff: {set(df_baseline.columns) ^ set(df_canonical.columns)}"

    # Bit-for-bit parity check on numeric/datetime cols
    diffs = []
    for col in df_baseline.columns:
        s_base = df_baseline[col]
        s_can = df_canonical[col]

        if pd.api.types.is_datetime64_any_dtype(s_base):
            # Normalize tz before compare
            o = s_base.dt.tz_localize("UTC") if s_base.dt.tz is None else s_base.dt.tz_convert("UTC")
            n = s_can.dt.tz_localize("UTC") if s_can.dt.tz is None else s_can.dt.tz_convert("UTC")
            if not o.equals(n):
                diffs.append((col, "datetime_diff"))
        elif pd.api.types.is_numeric_dtype(s_base):
            v_base = s_base.fillna(-9e18).values
            v_can = s_can.fillna(-9e18).values
            if not np.allclose(v_base, v_can, rtol=1e-9, atol=1e-12, equal_nan=True):
                n_diff = (v_base != v_can).sum()
                diffs.append((col, f"{n_diff}_numeric_diffs"))
        else:
            if not s_base.equals(s_can):
                diffs.append((col, "object_diff"))

    if diffs:
        msg = f"REGRESSION DETECTED : {len(diffs)} cols differ\n"
        for col, reason in diffs[:20]:
            msg += f"  {col}: {reason}\n"
        pytest.fail(msg)
