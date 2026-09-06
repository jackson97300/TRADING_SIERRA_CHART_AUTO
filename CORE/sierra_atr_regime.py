"""ATR Regime Z-Score streaming Welford (60 jours rolling).

Port batch -> streaming de la feature `atr_regime_zscore_60d` consommee par
`bot4_v2/core/regime_source.py:412` pour classifier `vol_regime` :
- atr_z >= 2.5  -> EXTREME (Bot 4 v2 blacklist scenarios)
- atr_z >= 1.5  -> HIGH
- atr_z >= -0.5 -> NORMAL
- atr_z <  -0.5 -> LOW

Sans cette feature, vol_regime est figé à NORMAL en permanence (NaN -> default).
Le gate EXTREME ne bloque jamais les news/gap/FOMC = trou safety critique.

Implementation : Welford online sum/sum_sq + deque ring buffer.

Source de verite originale :
- Code reference batch : CORE/phase_b_option_c_plus.py:93 (`add_atr_regime_zscore_60d`)
- Code reference streaming : CORE/enricher_chain.py:1838-1877 (`_apply_phase_3c_C`)

Reutilisation directe via helper class pour decoupler du LiveEnricherState
(qui n'est pas utilise par SierraPipelineOrchestrator).

Warm-up : 10 jours = 13800 bars CME 24h avant emission. Avant -> None.

Sans persistance pickle entre restarts. Backlog P1 : persister state dans
SierraPipelineOrchestrator._cross_day_resets si Sierra Enricher restart frequent.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional


# Constantes alignees sur enricher_chain.py:1737-1738 + phase_b_option_c_plus.py
_ATR_Z_WINDOW_BARS = 60 * 1380  # 60 jours * 1380 bars CME 24h = 82800
_ATR_Z_MIN_PERIODS = 10 * 1380  # 10 jours warm-up minimum = 13800
_STALE_FEATURE_THRESHOLD_BARS = 30  # FIX #3 anti-pattern 11 V1 silent fallback


class AtrRegimeStreaming:
    """Welford rolling 60d ATR z-score streaming.

    Usage :
        helper = AtrRegimeStreaming()
        for bar in stream:
            z = helper.update(bar.get("atr"))
            bar["atr_regime_zscore_60d"] = z  # None tant que warm-up incomplet
    """

    def __init__(self) -> None:
        self._buf: deque[float] = deque(maxlen=_ATR_Z_WINDOW_BARS)
        self._sum: float = 0.0
        self._sum_sq: float = 0.0
        self._consec_none: int = 0

    def update(self, atr_value: Optional[float]) -> Optional[float]:
        """Met a jour le rolling et retourne le z-score (ou None si warm-up).

        Args:
            atr_value : ATR de la bar courante (None si feed coupe).

        Returns:
            float z-score si >=10j accumules + variance non-degeneree, None sinon.

        Side effect :
            - Compteur `consec_none` incremente si atr_value None.
            - Reset si atr_value valide vu.
        """
        if atr_value is None or (isinstance(atr_value, float)
                                  and math.isnan(atr_value)):
            self._consec_none += 1
            return None

        self._consec_none = 0
        atr_f = float(atr_value)

        # Welford-style maintenance : si buffer full, soustraire valeur evictee.
        if len(self._buf) == self._buf.maxlen:
            old = self._buf[0]
            self._sum -= old
            self._sum_sq -= old * old

        self._buf.append(atr_f)
        self._sum += atr_f
        self._sum_sq += atr_f * atr_f

        n = len(self._buf)
        if n < _ATR_Z_MIN_PERIODS:
            return None

        mean = self._sum / n
        var = self._sum_sq / n - mean * mean
        if var <= 1e-12:
            return None

        std = math.sqrt(var)
        return float((atr_f - mean) / std)

    @property
    def is_stale(self) -> bool:
        """True si ATR feed coupe depuis >= 30 bars (~30 min)."""
        return self._consec_none >= _STALE_FEATURE_THRESHOLD_BARS

    @property
    def consec_none(self) -> int:
        return self._consec_none

    @property
    def buffer_size(self) -> int:
        return len(self._buf)

    def reset(self) -> None:
        """Reset complet (testing / dev only - PAS sur cross-day !)."""
        self._buf.clear()
        self._sum = 0.0
        self._sum_sq = 0.0
        self._consec_none = 0


def derive_ib_formed_bool(sierra_bar: dict) -> int:
    """Derive ib_formed_bool depuis Sierra natif.

    Source canonique : `ib_complete` (flag Sierra DMP 0/1).
    Fallback : `ib_range_ticks > 0` (cf regime_source.py:219-222 logique).

    Args:
        sierra_bar : dict bar Sierra natif.

    Returns:
        int 0 ou 1.
    """
    ib_complete = sierra_bar.get("ib_complete")
    if ib_complete is not None:
        try:
            return 1 if int(ib_complete) == 1 else 0
        except (TypeError, ValueError):
            pass

    ib_range_ticks = sierra_bar.get("ib_range_ticks")
    if ib_range_ticks is not None:
        try:
            return 1 if float(ib_range_ticks) > 0 else 0
        except (TypeError, ValueError):
            pass

    return 0
