"""
Regime Filter — CVR3 VIX Regime (MIA V2)

Role : filtrer les primary models selon le regime VIX pour eviter les pivots de
regime catastrophiques. C'est un GATE, PAS une strategy primary standalone.
Source :
  - Larry Connors VIX Reversal 3 methodology
  - Rishi Narang "Inside the Black Box" ch.4 risk models
  - LTCM/Amaranth/Knight Capital post-mortem : pivots de regime = cause de mort

Logique :
  VIX > 30 (chaos)    : bloquer mean reversion, autoriser trend_day_rider avec size /2
  15 <= VIX <= 25     : regime normal, toutes strategies actives
  VIX < 15 (complacency) : privilegier mean reversion (VWAP Rev, VA Failure),
                           bloquer trend_day_rider (peu probable en faible VIX)

Features requises :
  - vix_level : niveau du VIX (deja present dans DMP)
  - vix_regime : categoriel 0/1/2 (calme/normal/stress)

Usage dans le pipeline signal_aggregator :
    filter = CVR3VixFilter()
    if not filter.allows(strategy_name, bar_features):
        return Signal(type=HOLD, reason="regime filter")
    size_multiplier = filter.size_multiplier(strategy_name, bar_features)
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


VIX_CALM_MAX = 15.0
VIX_NORMAL_MAX = 25.0
VIX_STRESS_MIN = 30.0

# Mapping strategy name → autorisation par regime
# "calm" = VIX < 15, "normal" = 15-25, "stress" = 25-30, "chaos" = > 30
# Alignement catalogue Strategy 8 :
#   VIX > 25 → bloquer mean reversion (vwap, va_failure, em_reversion, mq_bounce)
#   VIX > 30 → tout bloquer sauf trend_day et orb (avec size reduite)
#   VIX < 15 → bloquer trend_day (peu probable en faible VIX)
STRATEGY_REGIME_MAP = {
    "vwap_reversion":          {"calm": True,  "normal": True,  "stress": False, "chaos": False},
    "va_failure_fade":         {"calm": True,  "normal": True,  "stress": False, "chaos": False},
    "orb":                     {"calm": True,  "normal": True,  "stress": True,  "chaos": True},
    "trend_day_rider":         {"calm": False, "normal": True,  "stress": True,  "chaos": True},
    "expected_move_reversion": {"calm": True,  "normal": True,  "stress": False, "chaos": False},
    "mq_level_bounce":         {"calm": True,  "normal": True,  "stress": False, "chaos": False},
    "swing_rejection_fade":    {"calm": True,  "normal": True,  "stress": False, "chaos": False},
    "gap_fade":                {"calm": True,  "normal": True,  "stress": False, "chaos": False},
    "poor_high_low_touch_fade": {"calm": True, "normal": True,  "stress": False, "chaos": False},
    "swing_pullback":          {"calm": False, "normal": True,  "stress": True,  "chaos": True},
}


class CVR3VixFilter:
    """CVR3 VIX Regime Filter — gate conditionnel sur les primary models."""

    def __init__(
        self,
        calm_max: float = VIX_CALM_MAX,
        normal_max: float = VIX_NORMAL_MAX,
        stress_min: float = VIX_STRESS_MIN,
    ):
        self.calm_max = calm_max
        self.normal_max = normal_max
        self.stress_min = stress_min

    def regime(self, vix_level: Optional[float]) -> str:
        if vix_level is None:
            return "normal"
        if vix_level < self.calm_max:
            return "calm"
        if vix_level < self.normal_max:
            return "normal"
        if vix_level < self.stress_min:
            return "stress"
        return "chaos"

    def allows(self, strategy_name: str, row: pd.Series) -> bool:
        """Retourne True si la strategy est autorisee dans le regime courant."""
        vix = row.get("vix_level")
        regime_key = self.regime(vix)
        policy = STRATEGY_REGIME_MAP.get(strategy_name, {})
        return policy.get(regime_key, True)

    def size_multiplier(self, strategy_name: str, row: pd.Series) -> float:
        """Retourne le multiplicateur de size selon le regime.
        - chaos : 0.5 (taille reduite de 50%)
        - stress : 0.75
        - normal : 1.0
        - calm : 1.0
        """
        vix = row.get("vix_level")
        regime_key = self.regime(vix)
        if regime_key == "chaos":
            return 0.5
        if regime_key == "stress":
            return 0.75
        return 1.0
