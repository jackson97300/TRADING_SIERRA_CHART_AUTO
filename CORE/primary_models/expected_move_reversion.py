"""
Strategy 9 — Expected Move Reversion (MIA V2, GAMMA PRIMARY)

Edge : quand le prix atteint le 1D Expected Move (max ou min) calcule a partir
de l'ATM straddle implied volatility, la probabilite statistique de rester dans
le range 1-sigma est ~68% (distribution log-normale des returns).

Sources verifiables :
  - Barbon & Buraschi "Gamma Fragility" (2021) SSRN 3725454 — papier academique
    demontrant que Gamma Exposure predit des return patterns intraday
  - MenthorQ expected move methodology
  - Krishnan & Ni "Stock Price Clustering on Option Expiration Dates" (2005)

Note franchise : ce setup n'est PAS documente directement dans Sinclair
"Volatility Trading" ch.10 (qui traite du smile) ni Natenberg (pricing manual).
L'edge vient de la propriete statistique du 1-sigma (log-normal) et du dealer
hedging au niveau strike, pas d'une strategie publiee. Les 2 features utilisees
(mq_dist_1d_max/min) sont les #1 et #2 en rho Spearman BETON dans le bench MIA
(+0.072, +0.069) sur 12 jours — edge empirique valide dans NOS donnees.

Signal deterministe :
  - Prix proche du 1D_max (abs(dist_1d_max_atr) < 0.5) AND au-dessus VWAP → SHORT
  - Prix proche du 1D_min (abs(dist_1d_min_atr) < 0.5) AND en-dessous VWAP → LONG

Convention DMP : dist_X_atr = X - price (positif = level ABOVE price)
  → prix au-dessus VWAP = dist_vwap_d_atr < 0
  → prix en-dessous VWAP = dist_vwap_d_atr > 0

Features requises (toutes presentes dans dataset v2) :
  - mq_dist_1d_max_atr : distance au Expected Move veille haut en ATR
  - mq_dist_1d_min_atr : distance au Expected Move veille bas en ATR
  - dist_vwap_d_atr : confirmation direction vs VWAP daily

Note empirique (backtest 19 jours ES+NQ v2) : le 1D_max n'est JAMAIS touche
(min ES=1.39 ATR, min NQ=1.00 ATR — IV surestime le range upside pendant
la periode bull). Le SHORT ne firera pas sur ce dataset, seul le LONG
near 1D_min est actif. Comportement asymetrique attendu, pas un bug.

TP/SL :
  - TP : retour vers VWAP_d (36 ticks)
  - SL : 0.5 ATR au-dela du 1D max/min (20 ticks)
  - Horizon : 60 min (reversion classique intraday)

Difficulte : ⭐ (40 lignes)
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


class ExpectedMoveReversionModel(PrimaryModel):
    """Expected Move Reversion (Barbon & Buraschi 2021 + MenthorQ empirique)."""

    name = "expected_move_reversion"

    def __init__(self, proximity_atr: float = 0.5, min_vwap_dist_atr: float = 0.3):
        self.proximity_atr = proximity_atr
        self.min_vwap_dist_atr = min_vwap_dist_atr

    def required_features(self) -> list[str]:
        return [
            "mq_dist_1d_max_atr",
            "mq_dist_1d_min_atr",
            "dist_vwap_d_atr",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        d_max = _finite(row.get("mq_dist_1d_max_atr"))
        d_min = _finite(row.get("mq_dist_1d_min_atr"))
        vwap_dist = _finite(row.get("dist_vwap_d_atr"))
        if d_max is None or d_min is None or vwap_dist is None:
            return Signal(type=SignalType.HOLD)

        # Short : prix proche du 1D max ET au-dessus du VWAP
        # Convention DMP : prix au-dessus VWAP → vwap_dist < 0
        if abs(d_max) < self.proximity_atr and vwap_dist < -self.min_vwap_dist_atr:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"em_reversion_short d_max={d_max:.2f} vwap={vwap_dist:.2f}",
            )

        # Long : prix proche du 1D min ET en-dessous du VWAP
        # Convention DMP : prix en-dessous VWAP → vwap_dist > 0
        if abs(d_min) < self.proximity_atr and vwap_dist > self.min_vwap_dist_atr:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"em_reversion_long d_min={d_min:.2f} vwap={vwap_dist:.2f}",
            )

        return Signal(type=SignalType.HOLD)
