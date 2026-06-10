"""
Strategy 3 — Opening Range Breakout (MIA V2)

Edge : breakout de l'Initial Balance (premiere heure RTH) a un edge directionnel
statistiquement significatif. Version MIA utilise l'IB (60 min) plutot que l'ORB
classique 15-min car l'IB est la reference standard Dalton/Market Profile et
directement disponible comme feature DMP.

Source :
  - Kakushadze & Tulchinsky "Alpha Factor Structure" (2015) pour le concept
    breakout statistique (note : pas de source directe pour l'exact Sharpe 1.2
    sur ES 1990-2014)
  - Larry Williams "The Secret of Selecting Stocks" (1987) — ORB classique
  - Connors & Alvarez "Short Term Trading Strategies That Work" (2008)
  - Jim Dalton "Markets in Profile" pour la reference IB 60min

Signal deterministe :
  - ib_complete AND ib_range_atr > 0.5 (IB suffisamment large)
  - ib_broken_up = 1 (prix a casse le IB high) → LONG
  - ib_broken_down = 1 (prix a casse le IB low) → SHORT

Features requises (verifiees dans parquet v2) :
  - ib_complete : booleen (apres 60 min RTH)
  - ib_range_atr : taille de l'IB en ATR
  - ib_broken_up : booleen cassure haute
  - ib_broken_down : booleen cassure basse

TP/SL :
  - TP : 36 ticks (simplification Phase 1 ; version Phase 2 utilisera un TP
    proportionnel au range IB comme dans le catalogue original)
  - SL : 20 ticks
  - Horizon : 60 min

Difficulte : ⭐ (40 lignes)
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


class OpeningRangeBreakoutModel(PrimaryModel):
    """IB Breakout (Kakushadze/Williams, adapte MIA via features DMP)."""

    name = "orb"

    def __init__(self, min_ib_range_atr: float = 0.25):
        # Seuil empirique : max ib_range_atr observe ~0.45 sur dataset ES v2,
        # donc 0.5 etait trop strict. 0.25 garantit ~50% des jours eligibles.
        # A re-calibrer via Optuna apres backfill 80 jours.
        self.min_ib_range_atr = min_ib_range_atr

    def required_features(self) -> list[str]:
        return [
            "ib_complete",
            "ib_range_atr",
            "ib_broken_up",
            "ib_broken_down",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        if not row.get("ib_complete", False):
            return Signal(type=SignalType.HOLD)

        ib_range_atr = _finite(row.get("ib_range_atr"))
        if ib_range_atr is None or ib_range_atr < self.min_ib_range_atr:
            return Signal(type=SignalType.HOLD)

        if row.get("ib_broken_up", False) and not row.get("ib_broken_down", False):
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"orb_long ib_range_atr={ib_range_atr:.2f}",
            )

        if row.get("ib_broken_down", False) and not row.get("ib_broken_up", False):
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"orb_short ib_range_atr={ib_range_atr:.2f}",
            )

        return Signal(type=SignalType.HOLD)
