"""
Strategy 6 — Swing Point Pullback (MIA V2)

Nom honnete : ce n'est PAS le vrai "Dow Trend" qui necessite comptage de 3+
Higher Lows consecutifs (stateful). C'est un PROXY stateless qui trade les
pullbacks sur un swing point majeur dans le sens d'une tendance etablie par
le contexte DMP.

Source originale (pour version Phase 3 stateful future) :
  - Theorie de Dow (Charles Dow 1900s)
  - MIA DowHybrid v6 C++ (CPP/MIA_DowHybrid_System.cpp)

Pour la version Phase 1 stateless :
  - Utilise ctx_trend_day_score pour identifier la direction du trend
  - Utilise dist_swing_high_atr / dist_swing_low pour localiser le pullback

Signal deterministe :
  - Trend day probable (trend_day_probability > 0.55) ET pullback sur swing
    low proche → LONG
  - Downtrend probable (< 0.45) ET pullback sur swing high proche → SHORT

Features requises (verifiees dans parquet v2) :
  - trend_day_probability : score Dalton
  - dist_swing_high_atr : distance au swing high
  - dist_swing_low : distance au swing low en points
  - swing_range_atr : amplitude
  - ctx_trend_day_score : score alternatif

TP/SL :
  - TP : 36 ticks
  - SL : 20 ticks
  - Horizon : 120 min (trend continuation)

Difficulte : ⭐⭐ (50 lignes stateless)
"""

from __future__ import annotations

import math

from CORE.primary_models.base import PrimaryModel, Signal, SignalType


def _finite(v):
    if v is None:
        return None
    try:
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


class DowTrendFractalModel(PrimaryModel):
    """Swing Point Pullback (proxy stateless Dow trend)."""

    name = "swing_pullback"

    def __init__(
        self,
        pullback_zone_atr: float = 0.25,
        pullback_zone_pts: float = 5.0,
        min_swing_range_atr: float = 1.0,
        trend_up_thresh: float = 0.55,
        trend_down_thresh: float = 0.45,
    ):
        # pullback_zone_pts pour dist_swing_low (points bruts), parametrise.
        self.pullback_zone_atr = pullback_zone_atr
        self.pullback_zone_pts = pullback_zone_pts
        self.min_swing_range_atr = min_swing_range_atr
        self.trend_up_thresh = trend_up_thresh
        self.trend_down_thresh = trend_down_thresh

    def required_features(self) -> list[str]:
        return [
            "trend_day_probability",
            "dist_swing_high_atr",
            "dist_swing_low",
            "swing_range_atr",
            "ctx_trend_day_score",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        trend_prob = _finite(row.get("trend_day_probability"))
        swing_range = _finite(row.get("swing_range_atr"))
        if trend_prob is None or swing_range is None:
            return Signal(type=SignalType.HOLD)
        if swing_range < self.min_swing_range_atr:
            return Signal(type=SignalType.HOLD)

        dist_sh = _finite(row.get("dist_swing_high_atr"))
        dist_sl = _finite(row.get("dist_swing_low"))

        # Uptrend : pullback sur swing low → long
        if trend_prob > self.trend_up_thresh and dist_sl is not None \
                and abs(dist_sl) < self.pullback_zone_pts:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"swing_pullback_long trend={trend_prob:.2f}",
            )

        # Downtrend : pullback sur swing high → short
        if trend_prob < self.trend_down_thresh and dist_sh is not None \
                and abs(dist_sh) < self.pullback_zone_atr:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"swing_pullback_short trend={trend_prob:.2f}",
            )

        return Signal(type=SignalType.HOLD)
