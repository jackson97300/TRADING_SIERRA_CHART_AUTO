"""
Strategy 8 — Swing High/Low Rejection Fade (MIA V2)

Nom honnete : ce n'est PAS un vrai "Double Top" pattern (qui necessite detection
stateful de 2 highs distincts + neckline + breakdown trigger). C'est un PROXY
stateless qui detecte l'approche d'un swing high/low significatif en zone
extreme du range du jour. Le meta-labeler LightGBM est responsable du filtrage
par contexte.

Source originale citee (pour la strategy "vrai double top" en Phase 3 future) :
  - Robert Edwards & John Magee "Technical Analysis of Stock Trends" (1948)
  - Thomas Bulkowski "Encyclopedia of Chart Patterns" 2e ed. (2005)

Pour la version Phase 1 stateless :
  - Utilise les features dist_swing_high_atr (top feature Spearman #1 bench
    MIA avec rho 0.080) et dist_sess_high_atr (position dans le range jour)

Signal deterministe :
  - Prix a moins de 0.15 ATR d'un swing high significatif (swing_range_atr > 1)
    ET prix dans le haut du range du jour → SHORT (fade rejection probable)
  - Symetrique pour swing low → LONG

Features requises (verifiees dans parquet v2) :
  - dist_swing_high_atr : distance au swing high en ATR
  - dist_swing_low : distance au swing low en points bruts (sans _atr)
  - swing_range_atr : amplitude du swing en ATR
  - dist_sess_high_atr : position vs plus haut de session
  - dist_sess_low : position vs plus bas de session en points

TP/SL :
  - TP : 36 ticks
  - SL : 20 ticks
  - Horizon : 60 min

Difficulte : ⭐⭐ (60 lignes stateless)
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


class DoubleTopBottomModel(PrimaryModel):
    """Swing High/Low Rejection Fade (proxy stateless du pattern double top)."""

    name = "swing_rejection_fade"

    def __init__(
        self,
        proximity_swing_atr: float = 0.15,
        proximity_swing_pts: float = 5.0,
        min_swing_range_atr: float = 1.0,
        range_edge_atr: float = 0.3,
        range_edge_pts: float = 20.0,
    ):
        # proximity_swing_pts : seuil pour dist_swing_low (points bruts, pas ATR)
        # range_edge_pts : seuil pour dist_sess_low (points bruts)
        # Ancienne version avait magic number 10.0 hardcode — recalibre ici.
        self.proximity_swing_atr = proximity_swing_atr
        self.proximity_swing_pts = proximity_swing_pts
        self.min_swing_range_atr = min_swing_range_atr
        self.range_edge_atr = range_edge_atr
        self.range_edge_pts = range_edge_pts

    def required_features(self) -> list[str]:
        return [
            "dist_swing_high_atr",
            "dist_swing_low",
            "swing_range_atr",
            "dist_sess_high_atr",
            "dist_sess_low",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        dist_sh = _finite(row.get("dist_swing_high_atr"))
        dist_sl = _finite(row.get("dist_swing_low"))
        swing_range = _finite(row.get("swing_range_atr"))
        dist_sess_high = _finite(row.get("dist_sess_high_atr"))
        dist_sess_low = _finite(row.get("dist_sess_low"))

        if dist_sh is None or swing_range is None:
            return Signal(type=SignalType.HOLD)
        if swing_range < self.min_swing_range_atr:
            return Signal(type=SignalType.HOLD)

        in_top = dist_sess_high is not None and abs(dist_sess_high) < self.range_edge_atr
        in_bot = dist_sess_low is not None and abs(dist_sess_low) < self.range_edge_pts

        # Swing high rejection en haut du range → short
        if abs(dist_sh) < self.proximity_swing_atr and in_top:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"swing_high_fade dist_sh={dist_sh:.2f}",
            )

        # Swing low rejection en bas du range → long (dist_sl en points bruts)
        if dist_sl is not None and abs(dist_sl) < self.proximity_swing_pts and in_bot:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"swing_low_fade dist_sl={dist_sl:.1f}",
            )

        return Signal(type=SignalType.HOLD)
