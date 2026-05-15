"""
Strategy 1 — Value Area Failure Fade (MIA V2)

Edge : ouverture hors de la Value Area de la veille + retour dans VA + position
actuelle du prix ambigue. Le setup Dalton dit que 80% du temps le prix atteint
l'autre bord de prev VA apres rentree.
Source :
  - Jim Dalton "Markets in Profile" (2007), ch.4-5
  - Peter Steidlmayer CBOT Market Profile methodology

Signal deterministe (version single-direction pour eviter BUY/SELL simultanes) :
Puisque `open_in_prev_va` est un booleen sans direction, on utilise la position
ACTUELLE du prix dans la VA par rapport au VPOC comme proxy du cote d'ouverture :
  - Open outside prev VA (open_in_prev_va=0) + actuellement dans VA (inside_prev_va=1)
  - SI dist_prev_vpoc_atr > 0 (VPOC au-dessus du prix = prix moitie basse VA) : LONG vers VAH
    (interpretation : ouverture probablement sous le VAL, retour dans VA depuis le bas)
  - SI dist_prev_vpoc_atr < 0 (VPOC sous le prix = prix moitie haute VA) : SHORT vers VAL
  - SI prix pile sur VPOC : HOLD (pas de direction)
  FIX BUG D 15/05/2026 : convention DMP unique (level - close).

Cette approximation est imparfaite (stateless ne peut pas tracker l'ouverture
exacte) mais elimine le bug de double-signal BUY/SELL sur la meme barre.
Version complete avec `open_side_prev_va` (feature upstream) en Phase 3.

Features requises (toutes verifiees dans parquet v2) :
  - open_in_prev_va : booleen (0 = open outside, 1 = open inside)
  - inside_prev_va : booleen actuel
  - dist_prev_vpoc_atr : distance signee (level - close) au prev VPOC : + = VPOC au-dessus du prix, - = VPOC sous le prix
  - dist_prev_vah_atr : pour sanity check
  - dist_prev_val_atr : pour sanity check

TP/SL :
  - TP : 36 ticks (9 points NQ, proxy pour "retour vers autre bord VA")
  - SL : 20 ticks
  - Horizon : 390 min (EOD)

Difficulte : ⭐⭐ (40 lignes)
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


class VaFailureFadeModel(PrimaryModel):
    """VA Failure Fade direction-aware (Dalton Market Profile)."""

    name = "va_failure_fade"

    def __init__(self, min_vpoc_bias_atr: float = 0.1):
        self.min_vpoc_bias_atr = min_vpoc_bias_atr

    def required_features(self) -> list[str]:
        return [
            "open_in_prev_va",
            "inside_prev_va",
            "dist_prev_vpoc_atr",
            "dist_prev_vah_atr",
            "dist_prev_val_atr",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        """Convention DMP : dist = niveau - prix.
          - dist_vah > 0 → VAH au-dessus prix → prix SOUS VAH (dans VA si > 0)
          - dist_val < 0 → VAL sous prix → prix AU-DESSUS VAL (dans VA si < 0)
          - Etre dans VA : dist_vah > 0 AND dist_val < 0
          - dist_vpoc > 0 → VPOC au-dessus prix → prix SOUS VPOC → LONG vers VAH
          - dist_vpoc < 0 → VPOC sous prix → prix AU-DESSUS VPOC → SHORT vers VAL
        """
        open_inside = row.get("open_in_prev_va")
        now_inside = row.get("inside_prev_va")
        if open_inside is None or now_inside is None:
            return Signal(type=SignalType.HOLD)

        # Setup Dalton : ouverture hors VA + retour dans VA
        if open_inside == 1 or now_inside == 0:
            return Signal(type=SignalType.HOLD)

        vpoc_dist = _finite(row.get("dist_prev_vpoc_atr"))
        vah_dist = _finite(row.get("dist_prev_vah_atr"))
        val_dist = _finite(row.get("dist_prev_val_atr"))
        if vpoc_dist is None or vah_dist is None or val_dist is None:
            return Signal(type=SignalType.HOLD)

        # Sanity : on doit vraiment etre dans la VA (prix entre VAL et VAH)
        # dist_vah > 0 (VAH au-dessus prix) AND dist_val < 0 (VAL sous prix)
        if vah_dist < 0 or val_dist > 0:
            return Signal(type=SignalType.HOLD)

        # Direction selon moitie de VA (sans bug BUY/SELL simultane)
        # vpoc_dist > 0 → prix sous VPOC → moitie basse → LONG vers VAH
        if vpoc_dist > self.min_vpoc_bias_atr:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"va_fade_long vpoc={vpoc_dist:.2f} val={val_dist:.2f}",
            )
        # vpoc_dist < 0 → prix au-dessus VPOC → moitie haute → SHORT vers VAL
        if vpoc_dist < -self.min_vpoc_bias_atr:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"va_fade_short vpoc={vpoc_dist:.2f} vah={vah_dist:.2f}",
            )

        return Signal(type=SignalType.HOLD)
