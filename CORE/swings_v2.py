"""swings_v2.py — Features Wyckoff + ICT derivees des swings Sierra natif.

Phase 3.2 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.2

Module reproduit 6 features Wyckoff/ICT sur source Sierra natif :

  1. bars_since_last_swing_high : compteur bars depuis dernier swing high
  2. bars_since_last_swing_low  : compteur bars depuis dernier swing low
  3. equal_highs_detected       : 2 swings highs recents quasi-egaux (Wyckoff)
  4. equal_lows_detected        : 2 swings lows quasi-egaux
  5. liquidity_sweep_high_lag5  : ICT sweep pattern (wick au-dela swing high
                                   puis close en-dessous) sur 5 dernieres bars
  6. liquidity_sweep_low_lag5   : ICT sweep pattern lows

Source data unique (Sierra natif schema 3.7.14+) :
  - dist_swing_high (points absolus, ou 0 si bar courante = swing high)
  - dist_swing_low (idem)
  - bar_high, bar_low, close (price action)

Detection new_swing :
  Sierra ne produit pas `new_swing_high/low` directement. On les derive :
  prev_dist_swing_high > 0 ET current_dist_swing_high == 0 -> new swing high.

Conventions :
  - Tolerance equal highs/lows : 4 ticks par defaut (Wyckoff standard)
  - Window lookback liquidity sweep : 5 bars
  - tick_size pris depuis CORE.constants si dispo, sinon param

Anti-patterns interdits :
  - Composite hardcode "skip if equal_highs" -> garder features brutes
  - Silent fallback : NaN propre si cold-start, raise si input invalide

Auteur : MIA Trading V2 (Phase 3.2 Sierra Migration)
"""
from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

# Tick size par defaut (NQ/ES = 0.25, MGC = 0.10)
DEFAULT_TICK_SIZE = 0.25

# Tolerance equal highs/lows en ticks (Wyckoff standard)
EQUAL_TOLERANCE_TICKS = 4

# Window lookback liquidity sweep ICT
SWEEP_LOOKBACK_BARS = 5


class SwingsV2Calculator:
    """Calculateur stateful 6 features swings Wyckoff + ICT.

    Usage:
        calc = SwingsV2Calculator(tick_size=0.25)
        for bar in bars:
            features = calc.update(
                dist_swing_high=bar["dist_swing_high"],
                dist_swing_low=bar["dist_swing_low"],
                bar_high=bar["bar_high"],
                bar_low=bar["bar_low"],
                close=bar["close"],
            )

    Reset cross-day : appelle calc.reset() au boundary 00:00 UTC.
    """

    def __init__(
        self,
        tick_size: float = DEFAULT_TICK_SIZE,
        equal_tolerance_ticks: int = EQUAL_TOLERANCE_TICKS,
        sweep_lookback: int = SWEEP_LOOKBACK_BARS,
    ) -> None:
        self.tick_size = tick_size
        self.equal_tolerance = equal_tolerance_ticks * tick_size
        self.sweep_lookback = sweep_lookback

        # State : detection new swing via front montant prev>0 -> current=0
        self._prev_dist_high: Optional[float] = None
        self._prev_dist_low: Optional[float] = None

        # Compteurs bars depuis dernier swing
        self._bars_since_high: int = 0
        self._bars_since_low: int = 0
        self._has_swing_high: bool = False
        self._has_swing_low: bool = False

        # Historique prix swing high/low pour equal detection
        self._swing_high_prices: deque[float] = deque(maxlen=4)
        self._swing_low_prices: deque[float] = deque(maxlen=4)
        # Niveau actuel du dernier swing high/low (pour ICT sweep)
        self._last_swing_high_price: Optional[float] = None
        self._last_swing_low_price: Optional[float] = None

        # Buffer 5 dernieres bars (bar_high, bar_low, close, last_sh, last_sl)
        # pour detection liquidity sweep ICT
        self._bars_buffer: deque[dict] = deque(maxlen=sweep_lookback)

    def reset(self) -> None:
        """Reset state cross-day."""
        self._prev_dist_high = None
        self._prev_dist_low = None
        self._bars_since_high = 0
        self._bars_since_low = 0
        self._has_swing_high = False
        self._has_swing_low = False
        self._swing_high_prices.clear()
        self._swing_low_prices.clear()
        self._last_swing_high_price = None
        self._last_swing_low_price = None
        self._bars_buffer.clear()

    def update(
        self,
        dist_swing_high: Optional[float],
        dist_swing_low: Optional[float],
        bar_high: Optional[float],
        bar_low: Optional[float],
        close: Optional[float],
    ) -> dict:
        """Update state + compute 6 features."""
        # NaN handling -> features NaN, pas crash
        if any(v is None or (isinstance(v, float) and np.isnan(v))
               for v in (dist_swing_high, dist_swing_low, bar_high, bar_low, close)):
            return self._empty_features()

        # Detection new swing high : prev_dist > 0 ET current_dist == 0
        new_high = (
            self._prev_dist_high is not None
            and self._prev_dist_high > 0
            and dist_swing_high == 0
        )
        new_low = (
            self._prev_dist_low is not None
            and self._prev_dist_low > 0
            and dist_swing_low == 0
        )
        # Premiere bar avec dist_swing_high == 0 : aussi new (cold-start)
        if self._prev_dist_high is None and dist_swing_high == 0:
            new_high = True
        if self._prev_dist_low is None and dist_swing_low == 0:
            new_low = True

        # Update compteurs
        if new_high:
            self._bars_since_high = 0
            self._has_swing_high = True
            # Le swing high price = bar_high de la bar courante (on EST le swing)
            self._swing_high_prices.append(float(bar_high))
            self._last_swing_high_price = float(bar_high)
        elif self._has_swing_high:
            self._bars_since_high += 1

        if new_low:
            self._bars_since_low = 0
            self._has_swing_low = True
            self._swing_low_prices.append(float(bar_low))
            self._last_swing_low_price = float(bar_low)
        elif self._has_swing_low:
            self._bars_since_low += 1

        # Update prev_dist pour prochaine bar
        self._prev_dist_high = float(dist_swing_high)
        self._prev_dist_low = float(dist_swing_low)

        # Push buffer (pour detection sweep lookback)
        self._bars_buffer.append({
            "bar_high": float(bar_high),
            "bar_low": float(bar_low),
            "close": float(close),
            "swing_high_at_time": self._last_swing_high_price,
            "swing_low_at_time": self._last_swing_low_price,
        })

        return {
            "bars_since_last_swing_high": (
                self._bars_since_high if self._has_swing_high else np.nan
            ),
            "bars_since_last_swing_low": (
                self._bars_since_low if self._has_swing_low else np.nan
            ),
            "equal_highs_detected": self._detect_equal_highs(),
            "equal_lows_detected": self._detect_equal_lows(),
            "liquidity_sweep_high_lag5": self._detect_sweep_high(),
            "liquidity_sweep_low_lag5": self._detect_sweep_low(),
        }

    def _detect_equal_highs(self) -> bool:
        """2 derniers swing highs dans tolerance |H1 - H2| <= tolerance ticks."""
        if len(self._swing_high_prices) < 2:
            return False
        h_last = self._swing_high_prices[-1]
        h_prev = self._swing_high_prices[-2]
        return abs(h_last - h_prev) <= self.equal_tolerance

    def _detect_equal_lows(self) -> bool:
        """2 derniers swing lows dans tolerance."""
        if len(self._swing_low_prices) < 2:
            return False
        l_last = self._swing_low_prices[-1]
        l_prev = self._swing_low_prices[-2]
        return abs(l_last - l_prev) <= self.equal_tolerance

    def _detect_sweep_high(self) -> bool:
        """ICT liquidity sweep high pattern.

        Sur les 5 dernieres bars (lookback) : au moins une bar ou
          bar_high > swing_high_at_time (wick depasse swing)
          ET close < swing_high_at_time (close en-dessous = rejet/sweep)

        Cf ICT methodology (Inner Circle Trader).
        """
        if len(self._bars_buffer) < 1:
            return False
        for bar in self._bars_buffer:
            sh = bar["swing_high_at_time"]
            if sh is None:
                continue
            if bar["bar_high"] > sh and bar["close"] < sh:
                return True
        return False

    def _detect_sweep_low(self) -> bool:
        """ICT liquidity sweep low pattern (symetrique high)."""
        if len(self._bars_buffer) < 1:
            return False
        for bar in self._bars_buffer:
            sl = bar["swing_low_at_time"]
            if sl is None:
                continue
            if bar["bar_low"] < sl and bar["close"] > sl:
                return True
        return False

    @staticmethod
    def _empty_features() -> dict:
        """Features NaN/False pour input NaN (anti silent fallback)."""
        return {
            "bars_since_last_swing_high": np.nan,
            "bars_since_last_swing_low": np.nan,
            "equal_highs_detected": False,
            "equal_lows_detected": False,
            "liquidity_sweep_high_lag5": False,
            "liquidity_sweep_low_lag5": False,
        }


def compute_swings_v2_features(
    df: pd.DataFrame,
    tick_size: float = DEFAULT_TICK_SIZE,
    equal_tolerance_ticks: int = EQUAL_TOLERANCE_TICKS,
    sweep_lookback: int = SWEEP_LOOKBACK_BARS,
) -> pd.DataFrame:
    """Batch compute (mode backtest dataset).

    Args:
        df : DataFrame avec colonnes 'dist_swing_high', 'dist_swing_low',
             'bar_high', 'bar_low', 'close'. Trie chronologiquement.
        tick_size : tick size instrument (0.25 ES/NQ, 0.10 MGC).
        equal_tolerance_ticks : tolerance equal highs/lows.
        sweep_lookback : window lookback liquidity sweep ICT.

    Returns:
        DataFrame copie + 6 colonnes ajoutees.

    Raises:
        ValueError : si une colonne requise manque (FAIL LOUD).
    """
    required = ["dist_swing_high", "dist_swing_low", "bar_high", "bar_low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"compute_swings_v2_features : colonnes manquantes {missing} "
            f"(requises Sierra natif schema 3.7.14+)"
        )

    result = df.copy()
    calc = SwingsV2Calculator(
        tick_size=tick_size,
        equal_tolerance_ticks=equal_tolerance_ticks,
        sweep_lookback=sweep_lookback,
    )

    rows = []
    for _, row in df.iterrows():
        rows.append(calc.update(
            dist_swing_high=row["dist_swing_high"],
            dist_swing_low=row["dist_swing_low"],
            bar_high=row["bar_high"],
            bar_low=row["bar_low"],
            close=row["close"],
        ))

    features_df = pd.DataFrame(rows, index=result.index)
    for col in features_df.columns:
        result[col] = features_df[col].values
    return result
