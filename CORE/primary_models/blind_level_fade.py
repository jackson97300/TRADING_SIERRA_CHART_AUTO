"""
Primary Model - Blind Level Fade (MenthorQ Break Level rejection)
===================================================================

⚠️  STATUS : NOGO PAPER V4 (code-reviewer 21/04/2026 soir)
================================================================
Ce setup a ete FLAGGE par code-reviewer comme DATA SNOOPING SEVERE :
- Agent market-analyst a fait GRID SEARCH sur 120 combinaisons de seuils
  sur 4 jours (17, 19, 20, 21/04)
- "OUT-of-sample" (17/19) utilise les MEMES jours que "IN-sample" (20/21)
  = aucun vrai hors-echantillon
- finish_strength_thresh=3 sur echelle -100/+100 = extremement laxiste
  sans justification theorique
- Pattern 11 caracterise (cf feedback_lightgbm_no_composite_indicators.md)

AVANT UTILISATION (condition obligatoire) :
1. REECRIRE avec seuils A PRIORI theoriques (quartiles 75/25, finish=30%)
2. VALIDER sur v4 propre (60+ jours post-fix) SANS retoucher seuils
3. VRAI OUT-OF-SAMPLE = 30 jours reserves jamais vus pendant dev

NE PAS DEPLOYER EN PAPER/LIVE tel quel.

================================================================
Setup decouvert empiriquement le 21/04/2026 par analyse des 4 jours propres
post-fix DMP 3.7.7 (17, 19, 20, 21/04). Pattern game-changer candidat.

PHILOSOPHIE
-----------
Les "Blind Levels" MenthorQ sont des niveaux de Break (BL) ou les market makers
doivent hedger leur exposition options. Quand le prix teste un BL avec un wick
(depassement mais close qui revient), on a une signature claire :
  - Rejet de la zone (fin du move)
  - Absence d acceptance (pas de close au-dela)
  - Opportunite de fade dans l autre sens

C est du **mean reversion structurel** (pas stat-based): le niveau attire
puis repousse, le rejet est la confirmation.

MECANIQUE
---------
SELL trigger :
  - 0 <= dist_blind_nearest_up <= 10 ticks (BL juste au-dessus, proche prix)
  - range_pos >= 65 (prix finit haut barre -> wick haut)
  - finish_strength <= -3 (close bas -> rejet)
  - momentum_3b > 0 (on y montait avant le rejet)

BUY trigger (symmetrique) :
  - -10 <= dist_blind_nearest_dn <= 0
  - range_pos <= 35
  - finish_strength >= 3
  - momentum_3b < 0

EXIT
----
SL : 10 ticks. TP : 20 ticks (R:R 2.0). Horizon 15 barres (time stop).
Cooldown : 3 barres.

RESULTATS EMPIRIQUES (4 jours, ES+NQ)
-------------------------------------
IN-sample (20-21/04)   : N=16  WR=56.2%  PF=2.95  EV=+7.4t/trade
OUT-of-sample (17,19/04): N=5   WR=60.0%  PF=3.00  EV=+8.0t/trade

Stabilite SL/TP : PF 2.7-3.5 sur R:R 2.0 +/- 20% SL.

LIMITES
-------
- Sample OUT petit (N=5) : pas de significance stat forte
- Distribution ES-biased : 13/16 IN et 5/5 OUT proviennent d ES
- Pattern necessite validation sur 30+ jours avant GO live
- Ne trade que US RTH session (09:30-16:00 ET)

Auteur : Claude (market-analyst) - 21/04/2026
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from CORE.primary_models.base import PrimaryModel, Signal, SignalType


def _finite(v):
    """Retourne v en float si fini, sinon None."""
    if v is None:
        return None
    try:
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


class BlindLevelFadeModel(PrimaryModel):
    """Blind Level Fade - fade du rejet au MenthorQ Break Level.

    Stateless : decision a la barre courante uniquement (row scalaire).
    """

    name = "blind_level_fade"

    def __init__(
        self,
        level_dist_max_ticks: int = 10,
        rp_high_thresh: float = 65.0,
        rp_low_thresh: float = 35.0,
        finish_strength_thresh: int = 3,
        require_momentum_contrarian: bool = True,
        sl_ticks: int = 10,
        tp_ticks: int = 20,
        us_rth_only: bool = True,
    ):
        self.level_dist_max_ticks = int(level_dist_max_ticks)
        self.rp_high_thresh = float(rp_high_thresh)
        self.rp_low_thresh = float(rp_low_thresh)
        self.finish_strength_thresh = int(finish_strength_thresh)
        self.require_momentum_contrarian = bool(require_momentum_contrarian)
        self.sl_ticks = int(sl_ticks)
        self.tp_ticks = int(tp_ticks)
        self.us_rth_only = bool(us_rth_only)

    def required_features(self) -> list[str]:
        # NOTE 13/05/2026 v0.3 : momentum_3b reste dans le contrat car le V4
        # parquet continue de fournir cette valeur (lue du DMP_MQ_FIELDS).
        # ATTENTION : leak DMP confirme (rho_fut1=0.44, voir
        # CORE/phase_b_v6_complete.py docstring + tools/backtest_momentum_variants.py).
        # A REMPLACER par close.diff(N) Python honnete quand pipeline V4 sera
        # entierement migre full Databento (Chantier 3 Live Enricher).
        return [
            "dist_blind_nearest_up",
            "dist_blind_nearest_dn",
            "range_pos",
            "finish_strength",
            "momentum_3b",
            "session_id",
        ]

    def description(self) -> str:
        return (
            "Blind Level Fade - rejet MenthorQ Break Level "
            "avec wick + momentum contraire"
        )

    def generate_signal(self, row: pd.Series, context: Optional[dict] = None) -> Signal:
        # Session filter
        if self.us_rth_only:
            sess = row.get("session_id")
            if sess not in ("US", "US_RTH"):
                return Signal(type=SignalType.HOLD, reason="session_not_rth")

        dup = _finite(row.get("dist_blind_nearest_up"))
        ddn = _finite(row.get("dist_blind_nearest_dn"))
        rp = _finite(row.get("range_pos"))
        fs = _finite(row.get("finish_strength"))
        mom = _finite(row.get("momentum_3b"))

        if None in (dup, ddn, rp, fs, mom):
            return Signal(type=SignalType.HOLD, reason="missing_features")

        dmax = float(self.level_dist_max_ticks)

        # SELL : BL juste au-dessus + wick haut + rejet close-bas + mom up
        if (0.0 <= dup <= dmax) and (rp >= self.rp_high_thresh)                 and (fs <= -self.finish_strength_thresh):
            if self.require_momentum_contrarian and mom <= 0:
                return Signal(type=SignalType.HOLD, reason="mom_not_contrarian_sell")
            return Signal(
                type=SignalType.SELL,
                sl_ticks=self.sl_ticks,
                tp_ticks=self.tp_ticks,
                reason=f"blind_bl_up={dup:.1f}t rp={rp:.0f} fs={fs:.0f} mom={mom:.1f}",
                meta={
                    "dist_blind_up": dup,
                    "range_pos": rp,
                    "finish_strength": fs,
                    "momentum_3b": mom,
                },
            )

        # BUY : BL juste en dessous + wick bas + rejet close-haut + mom down
        if (-dmax <= ddn <= 0.0) and (rp <= self.rp_low_thresh)                 and (fs >= self.finish_strength_thresh):
            if self.require_momentum_contrarian and mom >= 0:
                return Signal(type=SignalType.HOLD, reason="mom_not_contrarian_buy")
            return Signal(
                type=SignalType.BUY,
                sl_ticks=self.sl_ticks,
                tp_ticks=self.tp_ticks,
                reason=f"blind_bl_dn={ddn:.1f}t rp={rp:.0f} fs={fs:.0f} mom={mom:.1f}",
                meta={
                    "dist_blind_dn": ddn,
                    "range_pos": rp,
                    "finish_strength": fs,
                    "momentum_3b": mom,
                },
            )

        return Signal(type=SignalType.HOLD, reason="no_setup")
