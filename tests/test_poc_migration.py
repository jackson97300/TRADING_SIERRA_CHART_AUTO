"""Tests Phase 3.1 poc_migration.py (Sierra Migration 10/06/2026).

8 cas couverts (cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md section 3.1) :

1. VPOC monte 10 bars consecutifs -> dir=+1, slope>0
2. VPOC descend -> dir=-1, slope<0
3. VPOC flat (variance<eps) -> dir=0
4. Buffer < 10 bars -> NaN propre (pas crash)
5. NaN dans buffer -> handling defensif
6. Cross-day reset (calc.reset())
7. Idempotence : 2x call meme bar = meme valeur (state coherent)
8. Batch mode compute_poc_migration_features sur DataFrame
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_vpoc_monte_10_bars_consecutifs():
    """VPOC monte 10 bars -> dir=+1, slope>0."""
    from CORE.poc_migration import POCMigrationCalculator

    calc = POCMigrationCalculator()
    # Push 10 valeurs croissantes (10 -> 19)
    for i in range(10):
        features = calc.update(10.0 + i)

    # Apres 10 bars : features non-NaN
    assert features["poc_migration_dir"] == 1, (
        f"VPOC monte -> dir=+1, obtenu {features['poc_migration_dir']}"
    )
    assert features["ctx_poc_migration_10"] > 0, (
        f"VPOC monte -> slope > 0, obtenu {features['ctx_poc_migration_10']}"
    )


def test_vpoc_descend_10_bars():
    """VPOC descend -> dir=-1, slope<0."""
    from CORE.poc_migration import POCMigrationCalculator

    calc = POCMigrationCalculator()
    for i in range(10):
        features = calc.update(19.0 - i)

    assert features["poc_migration_dir"] == -1, (
        f"VPOC descend -> dir=-1, obtenu {features['poc_migration_dir']}"
    )
    assert features["ctx_poc_migration_10"] < 0, (
        f"VPOC descend -> slope < 0, obtenu {features['ctx_poc_migration_10']}"
    )


def test_vpoc_flat_variance_below_threshold():
    """VPOC flat (variance ~0) -> dir=0."""
    from CORE.poc_migration import POCMigrationCalculator

    calc = POCMigrationCalculator()
    # 10 valeurs identiques
    for _ in range(10):
        features = calc.update(15.0)

    assert features["poc_migration_dir"] == 0, (
        f"VPOC flat -> dir=0, obtenu {features['poc_migration_dir']}"
    )


def test_cold_start_buffer_under_10():
    """Buffer < 10 bars -> NaN propre (pas crash)."""
    from CORE.poc_migration import POCMigrationCalculator

    calc = POCMigrationCalculator()

    # Apres 1 update : NaN
    features = calc.update(10.0)
    assert math.isnan(features["poc_migration_dir"])
    assert math.isnan(features["ctx_poc_migration_10"])

    # Apres 9 updates : still NaN
    for i in range(8):
        features = calc.update(10.0 + i)
    assert math.isnan(features["poc_migration_dir"])

    # Apres 10 updates : non-NaN
    features = calc.update(20.0)
    assert not math.isnan(features["poc_migration_dir"])


def test_nan_input_handling():
    """NaN input -> ne push pas buffer, features NaN propre."""
    from CORE.poc_migration import POCMigrationCalculator

    calc = POCMigrationCalculator()

    # Buffer rempli avec valeurs valides
    for i in range(10):
        calc.update(10.0 + i)

    # NaN input -> NaN features
    features = calc.update(float("nan"))
    assert math.isnan(features["poc_migration_dir"])
    assert math.isnan(features["ctx_poc_migration_10"])

    # None input -> NaN features
    features = calc.update(None)
    assert math.isnan(features["poc_migration_dir"])


def test_reset_clears_buffer():
    """calc.reset() vide buffer -> retour cold-start."""
    from CORE.poc_migration import POCMigrationCalculator

    calc = POCMigrationCalculator()

    # Buffer rempli
    for i in range(10):
        calc.update(10.0 + i)
    features = calc.update(25.0)
    assert not math.isnan(features["poc_migration_dir"])

    # Reset -> cold-start
    calc.reset()
    features = calc.update(15.0)
    assert math.isnan(features["poc_migration_dir"]), (
        "Apres reset, premier update doit retourner NaN (cold-start)"
    )


def test_state_coherence_apres_multiple_calls():
    """State coherent : appels successifs produisent features croissantes/decroissantes coherentes."""
    from CORE.poc_migration import POCMigrationCalculator

    calc = POCMigrationCalculator()

    # Sequence sinusoidale
    values = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
    last_features = None
    for v in values:
        features = calc.update(v)
        if not math.isnan(features["poc_migration_dir"]):
            # Continue ascending, dir doit rester +1
            assert features["poc_migration_dir"] == 1
            last_features = features

    assert last_features is not None
    # Slope doit etre proche de 1 (pente unite)
    assert 0.9 < last_features["ctx_poc_migration_10"] < 1.1, (
        f"Slope sequence +1 par bar attendu ~1.0, obtenu "
        f"{last_features['ctx_poc_migration_10']}"
    )


def test_batch_mode_dataframe():
    """compute_poc_migration_features batch sur DataFrame."""
    from CORE.poc_migration import compute_poc_migration_features

    # DataFrame 20 bars, VPOC croissant
    df = pd.DataFrame({
        "dist_cur_vpoc": [float(10 + i) for i in range(20)],
    })

    result = compute_poc_migration_features(df)

    # Colonnes ajoutees
    assert "poc_migration_dir" in result.columns
    assert "ctx_poc_migration_10" in result.columns

    # 9 premieres lignes NaN (cold-start), suivantes non-NaN
    assert result["poc_migration_dir"].iloc[:9].isna().all()
    assert not result["poc_migration_dir"].iloc[9:].isna().any()

    # Toutes les valeurs apres cold-start doivent etre +1 (sequence croissante)
    assert (result["poc_migration_dir"].iloc[9:] == 1).all()


def test_batch_mode_missing_column_raises():
    """compute_poc_migration_features sans 'dist_cur_vpoc' -> ValueError."""
    from CORE.poc_migration import compute_poc_migration_features

    df = pd.DataFrame({"other_col": [1, 2, 3]})

    with pytest.raises(ValueError, match="dist_cur_vpoc"):
        compute_poc_migration_features(df)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
