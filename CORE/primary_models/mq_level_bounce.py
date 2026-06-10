"""
Strategy 10 — MQ Level Bounce (MIA V2, GAMMA PRIMARY)

Edge : quand le prix touche un niveau gamma MenthorQ (Call Resistance 0DTE,
Put Support 0DTE, HVL), les market makers options doivent hedger leur
positioning, ce qui cree une reaction contrariante statistiquement mesurable.

Source :
  - Barbon & Buraschi "Gamma Fragility" (2021), SSRN id 3725454
    (https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3725454)
    Seul papier academique demontrant que Gamma Exposure predit des return
    patterns intraday.
  - MenthorQ methodology (Brent Kochuba / SpotGamma)

Ce setup est confirme par le bench MIA V2 :
  - mq_dist_call_0dte_atr : +0.053 rho BETON
  - mq_dist_put_0dte_atr  : +0.058 rho BETON
  - mq_dist_call_res_atr  : +0.050 rho BETON
  - mq_dist_hvl_atr       : +0.038 rho BETON

Note : le catalogue initial mentionnait `mq_dist_put_sup_atr` mais cette feature
n'existe PAS dans le parquet v2 (seulement le 0DTE). On utilise `mq_dist_put_0dte_atr`
comme proxy du Put Support (les 2 sont correles en pratique).

Signal deterministe :
  - Prix approche Call Resistance (abs(dist_call_res_atr) < 0.2) + haut du range → SHORT
  - Prix approche Put 0DTE (abs(dist_put_0dte_atr) < 0.2) + bas du range → LONG
  - Prix colle au HVL (abs(dist_hvl_atr) < 0.2) + zone extreme du range → fade

Features requises (toutes verifiees dans parquet v2) :
  - mq_dist_call_res_atr : distance au Call Resistance en ATR
  - mq_dist_put_0dte_atr : distance au Put Support 0DTE (proxy put_sup)
  - mq_dist_call_0dte_atr : distance au Call Resistance 0DTE
  - mq_dist_hvl_atr : distance au High Vol Level en ATR
  - dist_sess_high_atr : distance au plus haut de la session en ATR
  - dist_sess_low : distance au plus bas de la session (en points bruts, sans _atr)

TP/SL :
  - TP : 36 ticks (~9 points NQ, retour vers VWAP)
  - SL : 20 ticks
  - Horizon : 60 min

Difficulte : ⭐⭐ (50 lignes)
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


class MqLevelBounceModel(PrimaryModel):
    """MQ Level Bounce (Barbon & Buraschi 2021)."""

    name = "mq_level_bounce"

    def __init__(
        self,
        proximity_atr: float = 0.5,
        range_edge_atr: float = 0.5,
        range_edge_pts: float = 20.0,
    ):
        # Seuils empiriques recalibres : mq_dist_call_res_atr min=0.617 dans
        # dataset ES v2, donc 0.2 etait inatteignable. 0.5 laisse firer le cote
        # SHORT. range_edge_atr (top range) et range_edge_pts (bot range) sont
        # equilibres : 0.5 ATR top <=> ~20 points bot (facteur 4 pour ATR~5pts).
        self.proximity_atr = proximity_atr
        self.range_edge_atr = range_edge_atr
        self.range_edge_pts = range_edge_pts

    def required_features(self) -> list[str]:
        return [
            "mq_dist_call_res_atr",
            "mq_dist_put_0dte_atr",
            "mq_dist_call_0dte_atr",
            "mq_dist_hvl_atr",
            "dist_sess_high_atr",
            "dist_sess_low",
        ]

    def generate_signal(self, row, context=None) -> Signal:
        d_call_res = _finite(row.get("mq_dist_call_res_atr"))
        d_put_0dte = _finite(row.get("mq_dist_put_0dte_atr"))
        d_call_0dte = _finite(row.get("mq_dist_call_0dte_atr"))
        d_hvl = _finite(row.get("mq_dist_hvl_atr"))
        d_sess_high = _finite(row.get("dist_sess_high_atr"))
        d_sess_low_pts = _finite(row.get("dist_sess_low"))

        if any(v is None for v in (d_call_res, d_put_0dte, d_hvl)):
            return Signal(type=SignalType.HOLD)

        in_top = d_sess_high is not None and abs(d_sess_high) < self.range_edge_atr
        in_bot = d_sess_low_pts is not None and abs(d_sess_low_pts) < self.range_edge_pts

        # Call Resistance bounce SHORT (haut du range)
        if abs(d_call_res) < self.proximity_atr and in_top:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"mq_call_res_short d={d_call_res:.2f}",
            )

        # Call 0DTE bounce SHORT
        if d_call_0dte is not None and abs(d_call_0dte) < self.proximity_atr and in_top:
            return Signal(
                type=SignalType.SELL,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"mq_call_0dte_short d={d_call_0dte:.2f}",
            )

        # Put 0DTE bounce LONG (bas du range)
        if abs(d_put_0dte) < self.proximity_atr and in_bot:
            return Signal(
                type=SignalType.BUY,
                sl_ticks=20,
                tp_ticks=36,
                reason=f"mq_put_0dte_long d={d_put_0dte:.2f}",
            )

        # HVL fade selon position dans le range
        if abs(d_hvl) < self.proximity_atr:
            if in_top:
                return Signal(
                    type=SignalType.SELL,
                    sl_ticks=20,
                    tp_ticks=36,
                    reason=f"mq_hvl_pin_short d={d_hvl:.2f}",
                )
            if in_bot:
                return Signal(
                    type=SignalType.BUY,
                    sl_ticks=20,
                    tp_ticks=36,
                    reason=f"mq_hvl_pin_long d={d_hvl:.2f}",
                )

        return Signal(type=SignalType.HOLD)
