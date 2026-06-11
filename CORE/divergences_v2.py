"""divergences_v2.py — Features divergences delta-price (rolling slopes).

Phase 3.8 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.3

# ATTENTION NAMING COLLISION (12/06/2026 — doc seulement)
#
# Cette implementation calcule des features SLOPE-based 10 bars rolling.
# Elle PARTAGE le prefixe `delta_div` avec DEUX autres implementations :
#
#   1. C++ DMP `delta_divergence` (CPP/MIA_REFACTORED/DUMPER/DMP_Reader.h:2517)
#      = EVENT-based session daily extreme (fire rate ~0.4%, rare)
#      consume par : BN V4 live (Sierra natif)
#
#   2. Python `rolling_features_streaming.py:1052-1062` ecrit
#      `delta_div_buy_clean/sell_clean/delta_divergence_clean` = CUMMAX daily
#      reset session. Cohabite/court-circuite par fix M1 sierra_pipeline:669-680.
#
#   3. Cette implementation (`divergences_v2.py`) = SLOPE 10 bars rolling
#      (fire rate ~30-60%, continu)
#      consume par : ML features dataset_builder, backtests, quality_gate
#
# Refactor naming complete REPORTE (audit 12/06 NOGO code-reviewer : 3 sources
# distinctes ecrivent les memes cles, fix M1 ne court-circuite pas correctement
# sub-engine #4 -> aliases retro ne garantissent PAS value-equivalence).
# Cf INCIDENT_LOG.md categorie PATTERN_11 + VALIDATION_MISS 2026-06-12.
# Cf DOCS/INVENTAIRE_DUMPER_VS_BOT.md section "CLARIFICATION NAMING `delta_div*`".
#
# Prerequis avant refactor :
#   - Auditer les 3 sources (trades_streaming Sierra, divergences_v2 slope,
#     rolling_features_streaming CUMMAX) et decider qui ecrit quoi
#   - Test pytest invariant `test_no_delta_div_collision`
#   - Migration coordonnee des 8+ consumers (bias_calculator_v6,
#     databento_paper_trader, phase_b_plus_plus_engine, log_catalog, etc.)

14 features divergences delta vs prix sur rolling window :

## Detection brute (4)
  1. delta_div_buy     : bool, price slope < 0 ET delta slope > 0 (bullish div)
  2. delta_div_sell    : bool, price slope > 0 ET delta slope < 0 (bearish div)
  3. delta_div_strength : float, |slope_delta - slope_price| normalise (SIGNED)
  4. delta_divergence_any : bool, buy OR sell

## Filtre regime (2)
  5. delta_div_buy_clean  : delta_div_buy ET delta_slope >= MIN_DELTA_SLOPE
  6. delta_div_sell_clean : delta_div_sell ET delta_slope <= -MIN_DELTA_SLOPE

## Zones tracking (4)
  7. n_delta_div_buy_zones_active  : int, count zones bullish dans buffer
  8. n_delta_div_sell_zones_active : int, count zones bearish
  9. dist_delta_div_buy_nearest_atr  : float, distance proche zone bullish (SIGNED)
  10. dist_delta_div_sell_nearest_atr : float, distance proche zone bearish (SIGNED)

## Retest (2)
  11. retest_high_delta_div : bool, price retourne dans zone bearish active
  12. retest_low_delta_div  : bool, price retourne dans zone bullish active

## Context rolling (2)
  13. ctx_div_density_20 : int, count divergences derniers 20 bars
  14. ctx_bars_since_div : int (NaN si jamais), bars depuis derniere divergence

Source data unique :
  - close (price)
  - delta_bar (= AskVolume - BidVolume Sierra)
  - atr (pour normalisation dist_*_atr)

Conventions :
  - Window slope : 10 bars (configurable)
  - Window context : 20 bars
  - Zone retention : 50 bars (configurable)
  - MIN_DELTA_SLOPE : 100 contrats/bar (filtre bruit)

Garde-fou SIGNE (3 features SIGNEES) :
  - delta_div_strength : positif si bullish, negatif si bearish
  - dist_delta_div_buy_nearest_atr : positif si zone au-dessus du close
  - dist_delta_div_sell_nearest_atr : positif si zone au-dessus

Anti-pattern interdit :
  - Composite hardcode "buy if delta_div_buy_clean" -> features brutes
  - Silent fallback : NaN cold-start, raise inputs invalides

Auteur : MIA Trading V2 (Phase 3.8 Sierra Migration)
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

# Rolling window pour slope calcul
SLOPE_WINDOW_BARS = 10
# Rolling window context (density)
CONTEXT_WINDOW_BARS = 20
# Buffer zones actives (rolling)
ZONE_RETENTION_BARS = 50
# Filtre bruit delta slope (contrats/bar minimum)
MIN_DELTA_SLOPE = 100.0


class DivergencesV2Calculator:
    """Calculateur stateful 14 features divergences delta-price.

    Usage:
        calc = DivergencesV2Calculator()
        for bar in bars:
            features = calc.update(
                close=bar["close"],
                delta_bar=bar["delta_bar"],
                atr=bar["atr"],
            )

    Reset cross-day : caller appelle calc.reset() au boundary 18:00 ET.
    """

    def __init__(
        self,
        slope_window: int = SLOPE_WINDOW_BARS,
        context_window: int = CONTEXT_WINDOW_BARS,
        zone_retention: int = ZONE_RETENTION_BARS,
        min_delta_slope: float = MIN_DELTA_SLOPE,
    ) -> None:
        self.slope_window = slope_window
        self.context_window = context_window
        self.zone_retention = zone_retention
        self.min_delta_slope = min_delta_slope

        # Rolling buffers
        self._price_buffer: deque[float] = deque(maxlen=slope_window)
        self._delta_buffer: deque[float] = deque(maxlen=slope_window)
        # Divergence history (rolling) : list de tuples (bar_idx, side, price)
        self._zones: list[dict] = []  # active zones
        # Bar counter
        self._bar_idx: int = 0
        # Track divergence events pour ctx
        self._div_events: deque[int] = deque(maxlen=context_window)
        self._last_div_idx: Optional[int] = None

    def reset(self) -> None:
        """Reset state cross-day."""
        self._price_buffer.clear()
        self._delta_buffer.clear()
        self._zones.clear()
        self._bar_idx = 0
        self._div_events.clear()
        self._last_div_idx = None

    def update(
        self,
        close: Optional[float],
        delta_bar: Optional[float],
        atr: Optional[float],
    ) -> dict:
        """Update state + compute 14 features."""
        # NaN handling
        if any(v is None or (isinstance(v, float) and np.isnan(v))
               for v in (close, delta_bar, atr)) or atr == 0:
            return self._empty_features()

        close = float(close)
        delta_bar = float(delta_bar)
        atr = float(atr)

        # Push buffers
        self._price_buffer.append(close)
        self._delta_buffer.append(delta_bar)
        self._bar_idx += 1

        # Cold-start : buffer < slope_window -> NaN propre
        if len(self._price_buffer) < self.slope_window:
            return self._empty_features()

        # Compute slopes
        slope_price = self._compute_slope(list(self._price_buffer))
        slope_delta = self._compute_slope(list(self._delta_buffer))

        # Detection brute
        delta_div_buy = slope_price < 0 and slope_delta > 0
        delta_div_sell = slope_price > 0 and slope_delta < 0
        delta_divergence_any = delta_div_buy or delta_div_sell

        # Strength (signed : positive si bullish, negatif si bearish)
        # delta_div_strength = (slope_delta - slope_price) / atr
        delta_div_strength = (slope_delta - slope_price) / atr if atr > 0 else 0.0

        # Filtre regime (min delta slope threshold)
        delta_div_buy_clean = delta_div_buy and slope_delta >= self.min_delta_slope
        delta_div_sell_clean = delta_div_sell and slope_delta <= -self.min_delta_slope

        # Update zones tracking
        if delta_div_buy_clean:
            self._zones.append({
                "bar_idx": self._bar_idx,
                "side": "buy",
                "price": close,
            })
            self._div_events.append(self._bar_idx)
            self._last_div_idx = self._bar_idx
        if delta_div_sell_clean:
            self._zones.append({
                "bar_idx": self._bar_idx,
                "side": "sell",
                "price": close,
            })
            self._div_events.append(self._bar_idx)
            self._last_div_idx = self._bar_idx

        # Purge zones expirees (au-dela retention)
        self._zones = [
            z for z in self._zones
            if self._bar_idx - z["bar_idx"] <= self.zone_retention
        ]

        # Compte zones actives
        buy_zones = [z for z in self._zones if z["side"] == "buy"]
        sell_zones = [z for z in self._zones if z["side"] == "sell"]
        n_buy_zones = len(buy_zones)
        n_sell_zones = len(sell_zones)

        # Distance to nearest zone (signed : positif si zone au-dessus close)
        dist_buy = self._dist_to_nearest_zone(close, buy_zones, atr)
        dist_sell = self._dist_to_nearest_zone(close, sell_zones, atr)

        # Retest : price entre dans zone (= bar_high+low traversent zone price)
        # Simplification : retest si dist < 0.5 ATR de la zone proche
        retest_high = bool(
            sell_zones and abs(dist_sell) < 0.5
        )
        retest_low = bool(
            buy_zones and abs(dist_buy) < 0.5
        )

        # Context rolling
        ctx_div_density_20 = len([
            idx for idx in self._div_events
            if self._bar_idx - idx <= self.context_window
        ])
        ctx_bars_since_div = (
            self._bar_idx - self._last_div_idx
            if self._last_div_idx is not None else np.nan
        )

        return {
            "delta_div_buy": bool(delta_div_buy),
            "delta_div_sell": bool(delta_div_sell),
            "delta_div_strength": delta_div_strength,
            "delta_divergence_any": bool(delta_divergence_any),
            "delta_div_buy_clean": bool(delta_div_buy_clean),
            "delta_div_sell_clean": bool(delta_div_sell_clean),
            "n_delta_div_buy_zones_active": n_buy_zones,
            "n_delta_div_sell_zones_active": n_sell_zones,
            "dist_delta_div_buy_nearest_atr": dist_buy,
            "dist_delta_div_sell_nearest_atr": dist_sell,
            "retest_high_delta_div": retest_high,
            "retest_low_delta_div": retest_low,
            "ctx_div_density_20": ctx_div_density_20,
            "ctx_bars_since_div": ctx_bars_since_div,
        }

    @staticmethod
    def _compute_slope(values: list[float]) -> float:
        """Linregress slope sur sequence (indices 0..N-1)."""
        n = len(values)
        x = np.arange(n, dtype=np.float64)
        y = np.asarray(values, dtype=np.float64)
        x_mean = x.mean()
        y_mean = y.mean()
        cov = np.mean((x - x_mean) * (y - y_mean))
        var_x = np.mean((x - x_mean) ** 2)
        if var_x == 0:
            return 0.0
        return float(cov / var_x)

    @staticmethod
    def _dist_to_nearest_zone(
        close: float,
        zones: list[dict],
        atr: float,
    ) -> float:
        """Distance vers zone la plus proche (signed, normalise atr).

        Returns:
            (zone_price - close) / atr de la zone la plus proche.
            NaN si aucune zone.
            Convention SIGNED : positif si zone au-dessus close.
        """
        if not zones or atr == 0:
            return np.nan
        # Nearest by absolute distance
        nearest = min(zones, key=lambda z: abs(z["price"] - close))
        return (nearest["price"] - close) / atr

    @staticmethod
    def _empty_features() -> dict:
        """Features defaut pour cold-start / NaN inputs."""
        return {
            "delta_div_buy": False,
            "delta_div_sell": False,
            "delta_div_strength": np.nan,
            "delta_divergence_any": False,
            "delta_div_buy_clean": False,
            "delta_div_sell_clean": False,
            "n_delta_div_buy_zones_active": 0,
            "n_delta_div_sell_zones_active": 0,
            "dist_delta_div_buy_nearest_atr": np.nan,
            "dist_delta_div_sell_nearest_atr": np.nan,
            "retest_high_delta_div": False,
            "retest_low_delta_div": False,
            "ctx_div_density_20": 0,
            "ctx_bars_since_div": np.nan,
        }


def compute_divergences_v2_features(
    df: pd.DataFrame,
    slope_window: int = SLOPE_WINDOW_BARS,
    context_window: int = CONTEXT_WINDOW_BARS,
    zone_retention: int = ZONE_RETENTION_BARS,
    min_delta_slope: float = MIN_DELTA_SLOPE,
) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df : DataFrame avec colonnes 'close', 'delta_bar', 'atr'.
             Trie chronologiquement.

    Returns:
        DataFrame copie + 14 colonnes ajoutees.

    Raises:
        ValueError : si colonne manquante.
    """
    required = ["close", "delta_bar", "atr"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"compute_divergences_v2_features : colonnes manquantes {missing}"
        )

    result = df.copy()
    calc = DivergencesV2Calculator(
        slope_window=slope_window,
        context_window=context_window,
        zone_retention=zone_retention,
        min_delta_slope=min_delta_slope,
    )

    rows = []
    for _, row in df.iterrows():
        rows.append(calc.update(
            close=row["close"],
            delta_bar=row["delta_bar"],
            atr=row["atr"],
        ))

    features_df = pd.DataFrame(rows, index=result.index)
    for col in features_df.columns:
        result[col] = features_df[col].values
    return result
