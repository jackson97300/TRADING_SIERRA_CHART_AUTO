"""
Strategy 7 — Gap Fade (MIA V2)

Edge : les gaps d'ouverture intraday sur ES/NQ tendent a se combler partiellement
durant la session RTH, surtout en environnement de faible volatilite. Les market
makers reversent la surreaction nocturne au fill.

Source :
  - Larry Connors "How Markets Really Work" (2012) — gap trading sur ETFs daily
  - Scott Andrews "Gap Trading Strategy" (2013)

Note franchise : Connors trade les gaps en DAILY sur ETFs (SPY, QQQ) avec filtre
SMA200. L'adaptation intraday 1-min sur futures est non documentee. Edge reel a
re-verifier via Monte Carlo permutation sur 80 jours backfill (catalogue MIA).

Signal deterministe (version simplifiee) :
  - Debut de session RTH (bool_session_early = 1)
  - Gap mesure par open_gap_atr dans [0.3, 1.5] ATR en valeur absolue
  - Filtre regime : VIX level < 25 (environnement mean reverting favorable)
  - Gap down → LONG (fade haussier vers fill)
  - Gap up → SHORT (fade baissier vers fill)

Features requises (verifiees dans parquet v2) :
  - open_gap_atr : gap a l'open en ATR signe (negatif = gap down)
  - bool_session_early : booleen premiere heure de session
  - vix_level : niveau du VIX pour filtre regime

TP/SL :
  - TP : 36 ticks
  - SL : 20 ticks
  - Horizon : 60 min (gap fill rapide)

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


class GapFadeModel(PrimaryModel):
    """Gap Fade intraday (Connors-inspired)."""

    name = "gap_fade"

    def __init__(
        self,
        min_gap_atr: float = 0.15,
        max_gap_atr: float = 2.0,
        max_vix: float = 25.0,
    ):
        # Seuils relaches : min 0.15 (au lieu de 0.3), max 2.0 (au lieu de 1.5)
        # Observation empirique : open_gap_atr est souvent faible sur ES apres
        # backfill 12 jours. Strategy deja niche, ne pas sur-filtrer.
        self.min_gap_atr = min_gap_atr
        self.max_gap_atr = max_gap_atr
        self.max_vix = max_vix

    def required_features(self) -> list[str]:
        return [
            "open_gap_atr",
            "vix_level",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        """Filtre bool_session_early supprime (trop restrictif dans le dataset
        actuel). Le gap est mesure des l'open, la strategy fade des que les
        conditions gap + vix sont remplies."""
        gap = _finite(row.get("open_gap_atr"))
        vix = _finite(row.get("vix_level"))
        if gap is None:
            return Signal(type=SignalType.HOLD)
        if vix is not None and vix > self.max_vix:
            return Signal(type=SignalType.HOLD)

        gap_abs = abs(gap)
        if gap_abs < self.min_gap_atr or gap_abs > self.max_gap_atr:
            return Signal(type=SignalType.HOLD)

        # Gap down → long (fade vers fill)
        if gap < 0:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"gap_fade_long gap={gap:.2f} vix={vix or 0:.1f}",
            )

        # Gap up → short
        return Signal(
            type=SignalType.SELL,
            sl_ticks=20,
            tp_ticks=36,
            reason=f"gap_fade_short gap={gap:.2f} vix={vix or 0:.1f}",
        )
