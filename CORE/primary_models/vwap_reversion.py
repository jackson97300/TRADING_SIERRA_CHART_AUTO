"""
Strategy 4 — VWAP Mean Reversion (MIA V2)

Edge : prix touchant VWAP_d SD2/SD3 revient vers VWAP avec probabilite > 60%.
Source :
  - Mark Fisher "The Logical Trader" (2002) — VWAP bands strategy
  - Berlinger, Illes, Liechtenstein "Volume Weighted Average Price" (2016)
  - Goldman Sachs execution algo papers : VWAP utilise comme benchmark de reference

Note : Lopez de Prado AFML ch.17 (microstructural features) ne traite PAS
directement de VWAP mean reversion. Cette strategie est de l'analyse technique
classique, pas du ML. L'edge vient de la distribution statistique des returns
autour du VWAP intraday.

Signal deterministe :
  - Prix > VWAP_d SD2 upper + momentum delta s'essouffle → SHORT vers VWAP
  - Prix < VWAP_d SD2 lower + momentum delta s'inverse → LONG vers VWAP

Features requises (verifiees via _validate_features.py) :
  - dist_vwap_d_sd2u_atr : distance au VWAP_d SD2 upper en ATR (positif si au-dessus)
  - dist_vwap_d_sd2d : distance au VWAP_d SD2 lower en points bruts (positif si
    sous la bande) — ATTENTION : sans suffixe `_atr`, unite differente de sd2u
  - ctx_delta_slope_5 : slope du delta sur 5 barres (feature contextuelle)

TP/SL :
  - TP : retour VWAP_d (36 ticks typique, ~9 points NQ)
  - SL : SD3 break (20 ticks)
  - Horizon : 60 min (mean reversion intraday classique)

Difficulte : ⭐ (35 lignes)
"""

from __future__ import annotations

import math

from CORE.primary_models.base import PrimaryModel, Signal, SignalType


def _finite(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


class VwapReversionModel(PrimaryModel):
    """VWAP SD2 mean reversion (Fisher 2002)."""

    name = "vwap_reversion"

    def __init__(
        self,
        sd2_proximity_atr: float = 0.0,
        sd2d_proximity_pts: float = 0.0,
        delta_slope_min: float = 0.3,
    ):
        self.sd2_proximity_atr = sd2_proximity_atr
        self.sd2d_proximity_pts = sd2d_proximity_pts
        self.delta_slope_min = delta_slope_min

    def required_features(self) -> list[str]:
        return [
            "dist_vwap_d_sd2u_atr",
            "dist_vwap_d_sd2d",
            "ctx_delta_slope_5",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        """Convention DMP : dist = niveau - prix.
          - dist_sd2u_atr < 0 → prix AU-DESSUS SD2u (breakout) → SHORT vers VWAP
          - dist_sd2d > 0 → prix SOUS SD2d (breakout) → LONG vers VWAP
        """
        sd2u_atr = _finite(row.get("dist_vwap_d_sd2u_atr"))
        sd2d_pts = _finite(row.get("dist_vwap_d_sd2d"))
        slope = _finite(row.get("ctx_delta_slope_5"))
        if sd2u_atr is None or sd2d_pts is None or slope is None:
            return Signal(type=SignalType.HOLD)

        # SHORT : prix au-dessus SD2u (dist_sd2u_atr < 0) + momentum baissier
        if sd2u_atr < -self.sd2_proximity_atr and slope < -self.delta_slope_min:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"vwap_short sd2u={sd2u_atr:.2f} slope={slope:.2f}",
            )

        # LONG : prix sous SD2d (dist_sd2d > 0) + momentum haussier
        if sd2d_pts > self.sd2d_proximity_pts and slope > self.delta_slope_min:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"vwap_long sd2d={sd2d_pts:.2f} slope={slope:.2f}",
            )

        return Signal(type=SignalType.HOLD)
