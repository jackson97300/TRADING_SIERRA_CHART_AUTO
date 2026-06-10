"""
Strategy 5 — Poor High/Low Touch Fade (MIA V2)

Nom honnete : ce n'est PAS le vrai "Poor High Retest" stratege de Dalton (qui
requiert detection multi-jours des poor highs + tracker des retests). C'est un
PROXY stateless qui utilise les features ctx_poor_high / ctx_poor_low du DMP
(detection intraday de la signature TPO). Le meta-labeler decide de trader ou
non selon le contexte.

Source originale (pour version Phase 3 stateful future) :
  - Jim Dalton "Markets in Profile" (2007), ch.5
  - Peter Steidlmayer CBOT Market Profile

Pour la version Phase 1 stateless :
  - Utilise les features ctx_poor_high, ctx_poor_low (existent dans parquet v2)

Signal deterministe :
  - ctx_poor_high = 1 AND prix touche le swing high (proxy fade rejection) → SHORT
  - ctx_poor_low = 1 AND prix touche le swing low → LONG
  - Filtre : position dans haut/bas du range

Features requises (verifiees dans parquet v2) :
  - ctx_poor_high : booleen poor high intraday detecte
  - ctx_poor_low : booleen poor low intraday detecte
  - dist_swing_high_atr : distance au swing high
  - dist_swing_low : distance au swing low (en points)
  - dist_sess_high_atr, dist_sess_low : position range

TP/SL :
  - TP : 36 ticks
  - SL : 20 ticks
  - Horizon : 60 min

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


class PoorHighLowRetestModel(PrimaryModel):
    """Poor High/Low Touch Fade (proxy stateless Dalton)."""

    name = "poor_high_low_touch_fade"

    def __init__(
        self,
        proximity_atr: float = 0.2,
        proximity_pts: float = 5.0,
        range_edge_atr: float = 0.3,
        range_edge_pts: float = 20.0,
    ):
        # proximity_pts pour dist_swing_low (points bruts), parametrise au lieu
        # du magic number 10.0 de la version round 3.
        self.proximity_atr = proximity_atr
        self.proximity_pts = proximity_pts
        self.range_edge_atr = range_edge_atr
        self.range_edge_pts = range_edge_pts

    def required_features(self) -> list[str]:
        return [
            "ctx_poor_high",
            "ctx_poor_low",
            "dist_swing_high_atr",
            "dist_swing_low",
            "dist_sess_high_atr",
            "dist_sess_low",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        poor_high = row.get("ctx_poor_high", 0)
        poor_low = row.get("ctx_poor_low", 0)
        dist_sh = _finite(row.get("dist_swing_high_atr"))
        dist_sl = _finite(row.get("dist_swing_low"))
        dist_sess_high = _finite(row.get("dist_sess_high_atr"))
        dist_sess_low = _finite(row.get("dist_sess_low"))

        in_top = dist_sess_high is not None and abs(dist_sess_high) < self.range_edge_atr
        in_bot = dist_sess_low is not None and abs(dist_sess_low) < self.range_edge_pts

        if poor_high and dist_sh is not None \
                and abs(dist_sh) < self.proximity_atr and in_top:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"poor_high_touch dist_sh={dist_sh:.2f}",
            )

        if poor_low and dist_sl is not None \
                and abs(dist_sl) < self.proximity_pts and in_bot:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"poor_low_touch dist_sl={dist_sl:.1f}",
            )

        return Signal(type=SignalType.HOLD)
