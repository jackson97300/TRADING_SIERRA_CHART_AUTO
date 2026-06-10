"""poc_migration.py — Calcul POC migration features pour live_enricher Sierra-only.

Phase 3.1 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md
Cf plan DOCS/superpowers/plans/2026-06-10-sierra-migration-phase3.md (TODO)

Module reproduit 2 features Databento sur source Sierra natif :

  1. poc_migration_dir : sign(dist_cur_vpoc(t) - dist_cur_vpoc(t-10))
     -> +1 si VPOC remonte (= prix descend vers VPOC OU VPOC suit prix),
     -> -1 si VPOC descend, 0 si flat (<0.01% variance).

  2. ctx_poc_migration_10 : slope linregress sur dist_cur_vpoc[t-9:t+1]
     -> indicateur continu vitesse de migration POC sur 10 dernieres bars.

Source data unique :
  dist_cur_vpoc Sierra natif (DMP_Transform.h, schema 3.7.14+ AS-IS).

Garde-fou SIGNE :
  poc_migration_dir est SIGNE. Test obligatoire :
  - Sur 5 jours baissiers : sum negative attendue (POC descend avec prix)
  - Sur 5 jours haussiers : sum positive attendue
  - Convergence > 60% sur 10 jours
  Cf tools/check_feature_sign.py (Phase 3.1.3).

Anti-pattern interdit :
  - Silent fallback si buffer < 10 bars (FAIL LOUD via NaN propre)
  - Composite hardcode sans backtest (Pattern 11 V1 - cf BN V5 KILL 10/06)

Auteur : MIA Trading V2 (Phase 3.1 Sierra Migration)
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

# Variance threshold sous laquelle on considere VPOC "flat" -> dir=0
# 0.01% du prix = ~3 ticks NQ a 30000 = noise level
FLAT_VARIANCE_THRESHOLD = 0.0001

# Buffer minimum requis (10 bars rolling window)
MIN_BUFFER_SIZE = 10


class POCMigrationCalculator:
    """Calculateur stateful POC migration sur rolling window 10 bars.

    Usage:
        calc = POCMigrationCalculator()
        for bar in bars:
            features = calc.update(bar["dist_cur_vpoc"])
            # features = {"poc_migration_dir": int, "ctx_poc_migration_10": float}

    Reset cross-day : appelle calc.reset() au boundary 00:00 UTC.
    """

    def __init__(self) -> None:
        # Rolling buffer fixed size 10 (deque automatique drop oldest)
        self._buffer: deque[float] = deque(maxlen=MIN_BUFFER_SIZE)

    def reset(self) -> None:
        """Reset buffer (cross-day boundary)."""
        self._buffer.clear()

    def update(self, dist_cur_vpoc: Optional[float]) -> dict:
        """Update buffer + compute features.

        Args:
            dist_cur_vpoc: distance current VPOC (Sierra natif, points absolus
                ou ticks selon DMP convention).
                None ou NaN -> ne pas update buffer, features = NaN.

        Returns:
            dict {"poc_migration_dir": int (0/+1/-1) ou NaN,
                  "ctx_poc_migration_10": float ou NaN}
        """
        # NaN handling defensif
        if dist_cur_vpoc is None or (
            isinstance(dist_cur_vpoc, float) and np.isnan(dist_cur_vpoc)
        ):
            return {
                "poc_migration_dir": np.nan,
                "ctx_poc_migration_10": np.nan,
            }

        # Push dans buffer
        self._buffer.append(float(dist_cur_vpoc))

        # Cold-start : buffer < 10 -> NaN propre (anti silent fallback)
        if len(self._buffer) < MIN_BUFFER_SIZE:
            return {
                "poc_migration_dir": np.nan,
                "ctx_poc_migration_10": np.nan,
            }

        # Compute features
        values = list(self._buffer)
        return {
            "poc_migration_dir": self._compute_dir(values),
            "ctx_poc_migration_10": self._compute_slope(values),
        }

    @staticmethod
    def _compute_dir(values: list[float]) -> int:
        """Sign(dist_cur_vpoc(t) - dist_cur_vpoc(t-9)).

        +1 si difference positive (VPOC remonte),
        -1 si negative (VPOC descend),
         0 si variance < threshold (flat).
        """
        current = values[-1]
        ten_bars_ago = values[0]
        diff = current - ten_bars_ago

        # Variance threshold (relatif au prix ~30000 NQ -> ~3 ticks)
        # Si VPOC quasi-stable, dir=0
        if abs(diff) < FLAT_VARIANCE_THRESHOLD * abs(ten_bars_ago) if ten_bars_ago != 0 else FLAT_VARIANCE_THRESHOLD:
            return 0
        return int(np.sign(diff))

    @staticmethod
    def _compute_slope(values: list[float]) -> float:
        """Slope linregress sur 10 dernieres bars.

        Returns slope (= velocity migration POC). Positive = accelere
        upward, negative = accelere downward, ~0 = stationnaire.
        """
        # Linregress slope = covar(x,y) / var(x) ; x = indices [0..9]
        x = np.arange(MIN_BUFFER_SIZE, dtype=np.float64)
        y = np.asarray(values, dtype=np.float64)

        # Defense profondeur : NaN dans buffer (peut arriver si update avec
        # None ne push pas mais valeurs anciennes NaN existent)
        if np.any(np.isnan(y)):
            return np.nan

        # Slope = cov(x,y) / var(x). var(x) constant pour x=[0..9].
        x_mean = x.mean()
        y_mean = y.mean()
        cov = np.mean((x - x_mean) * (y - y_mean))
        var_x = np.mean((x - x_mean) ** 2)
        if var_x == 0:  # impossible vu x fixe, defensive
            return 0.0
        return float(cov / var_x)


def compute_poc_migration_features(df: pd.DataFrame) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df: DataFrame avec colonne 'dist_cur_vpoc'. Trie chronologiquement.

    Returns:
        DataFrame copie avec colonnes ajoutees 'poc_migration_dir',
        'ctx_poc_migration_10' (NaN sur les premieres 9 lignes = cold-start).
    """
    if "dist_cur_vpoc" not in df.columns:
        raise ValueError(
            "compute_poc_migration_features : colonne 'dist_cur_vpoc' manquante "
            "(source Sierra natif requise)"
        )

    result = df.copy()
    calc = POCMigrationCalculator()

    dirs = []
    slopes = []
    for val in df["dist_cur_vpoc"].values:
        features = calc.update(val if not pd.isna(val) else None)
        dirs.append(features["poc_migration_dir"])
        slopes.append(features["ctx_poc_migration_10"])

    result["poc_migration_dir"] = dirs
    result["ctx_poc_migration_10"] = slopes
    return result
