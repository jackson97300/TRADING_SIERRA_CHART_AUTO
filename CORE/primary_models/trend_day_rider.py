"""
Strategy 2 — Trend Day Rider (MIA V2)

Edge : trend day detecte tot (IB etroite + extension > 1.5 IB avant 11h30 ET) =
probabilite tres elevee de close proche de l'extreme de la journee.
Source :
  - Jim Dalton "Markets in Profile" (2007)
  - Peter Steidlmayer Market Profile methodology CBOT

Signal deterministe :
  - Detection trend day : ib_is_narrow AND ctx_ib_extension_ratio > 1.5
    AND bool_session_early = 1 (avant 11h30 ET)
  - Direction UP (ib_broken_up=1) → LONG sur pullback vers VWAP_d
  - Direction DOWN (ib_broken_down=1) → SHORT sur pullback vers VWAP_d

Features requises (verifiees dans parquet v2) :
  - ib_complete : booleen (60 min passees)
  - ib_is_narrow : booleen IB etroite
  - ib_broken_up, ib_broken_down : booleens direction du breakout
  - ctx_ib_extension_ratio : ratio d'extension IB
  - bool_session_early : booleen premiere heure de session
  - dist_vwap_d_atr : proximite VWAP pour timing pullback
  - trend_day_probability : score Dalton (feature contextuelle, pour filtre)

TP/SL :
  - TP : 36 ticks (version Phase 1 avec TP fixe, hold-to-close en Phase 2)
  - SL : 20 ticks
  - Horizon : 60 min

Difficulte : ⭐⭐ (60 lignes)
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


class TrendDayRiderModel(PrimaryModel):
    """Trend Day Rider (Dalton)."""

    name = "trend_day_rider"

    def __init__(
        self,
        min_extension_ratio: float = 1.5,
        pullback_vwap_atr: float = 0.5,
        min_trend_prob: float = 0.40,
    ):
        # Seuils empiriques : trend_day_probability max=0.65 dans dataset ES v2,
        # donc 0.55 etait trop strict. 0.40 laisse firer les trend days probables.
        # A re-calibrer via Optuna apres backfill 80 jours.
        self.min_extension_ratio = min_extension_ratio
        self.pullback_vwap_atr = pullback_vwap_atr
        self.min_trend_prob = min_trend_prob

    def required_features(self) -> list[str]:
        return [
            "ib_complete",
            "ib_broken_up",
            "ib_broken_down",
            "ctx_ib_extension_ratio",
            "dist_vwap_d_atr",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        """Filtres simplifies : ib_complete + extension > 1.5 + pullback VWAP.
        Filtre trend_day_probability supprime (redondant avec extension ratio
        et trop strict sur NQ). Le meta-labeler LightGBM fera le filtrage fin."""
        if not row.get("ib_complete", False):
            return Signal(type=SignalType.HOLD)

        ib_ext = _finite(row.get("ctx_ib_extension_ratio"))
        vwap_dist = _finite(row.get("dist_vwap_d_atr"))
        if ib_ext is None or vwap_dist is None:
            return Signal(type=SignalType.HOLD)

        if ib_ext <= self.min_extension_ratio:
            return Signal(type=SignalType.HOLD)
        if abs(vwap_dist) > self.pullback_vwap_atr:
            return Signal(type=SignalType.HOLD)

        if row.get("ib_broken_up", False):
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"trend_day_long ext={ib_ext:.2f} vwap={vwap_dist:.2f}",
            )
        if row.get("ib_broken_down", False):
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"trend_day_short ext={ib_ext:.2f} vwap={vwap_dist:.2f}",
            )

        return Signal(type=SignalType.HOLD)
