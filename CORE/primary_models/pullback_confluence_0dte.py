"""
Primary Model — Pullback Confluence Call/Put 0DTE + Double Footprint Confirm
==============================================================================

Setup Jackson formalise sur trade concret session Londres NQ 21/04/2026.
Version 2 (21/04/2026 soir) : ameliorations apres backtest v1.

VERSION HISTORY
---------------
v1 (21/04 21h) : base — trigger double confirm + gamma + proximite 0DTE
                 Backtest 4j : PF NQ 1.08 / PF ES 3.95 (N=4)

v2 (21/04 23h) : + TP dynamique GEX proche (si <80 ticks, sinon fixe 36)
                 + filtre session (exclure Asia si illiquide)
                 + pullback prealable via context (rolling 20 bars)

PHILOSOPHIE (inchangee)
-----------
Jackson trade des reversals LONG/SHORT apres pullback dans zone d'influence
options 0DTE, avec confirmation double footprint (color + long bar) et
filtre gamma_condition. Hedge dealers en gamma positif = mean reversion.

LOGIQUE DIRECTIONNELLE
----------------------
LONG (reversal haussier apres pullback sous resistance 0DTE) :
  - bn_color_up = 1 AND bn_long_up = 1
  - mq_gamma_condition = 1
  - |dist_mq_call_0dte| < max_dist_0dte_ticks
  - [v2] Si require_pullback : context doit montrer pullback recent
  - [v2] Si skip_asia : session_id != "Asia"

SHORT : symetrique avec bn_color_dn, bn_long_dn, dist_mq_put_0dte.

TP DYNAMIQUE (v2)
-----------------
LONG : si dist_gex_nearest_up dans [20, max_tp_ticks_dyn] : TP = GEX
       sinon TP fixe 36 ticks.
SHORT : miroir avec dist_gex_nearest_dn.

Justification : Jackson a TP GEX 5 dans son trade reel 21/04. Le fixe 36t
ratait 65% du potentiel. TP dynamique atteint le TP Jackson reel.

CONTEXT PASSE PAR BACKTEST/LIVE
-------------------------------
context = {
    "lookback_max_price": float,  # max price sur N bars precedentes
    "lookback_min_price": float,  # min price
    "lookback_bars": int,         # N (default 20)
}
Si context["lookback_max_price"] - current_price >= pullback_ticks * 0.25
-> pullback LONG valide (prix a recule depuis high recent).

FEATURES REQUISES
-----------------
  JSONL direct :
    - bn_color_up, bn_color_dn, bn_long_up, bn_long_dn
    - dist_mq_call_0dte, dist_mq_put_0dte
    - dist_gex_nearest_up, dist_gex_nearest_dn
    - session_id (string: "Asia" / "London" / "RTH" / "US_AH")
    - price
  Injector MenthorQ :
    - mq_gamma_condition

Auteur : Claude (mentor Jackson) — 21/04/2026 v2
"""

from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from CORE.primary_models.base import PrimaryModel, Signal, SignalType


TICK_SIZE_NQ = 0.25  # NQ tick = 0.25 points


def _finite(v):
    """Retourne float(v) si fini, sinon None."""
    if v is None:
        return None
    try:
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


class PullbackConfluence0DTEModel(PrimaryModel):
    """
    Pullback Confluence Call/Put 0DTE + Double Footprint Confirm (v2).

    v2 ajoute :
      - TP dynamique vers GEX proche (20-80 ticks) sinon fixe 36
      - Filtre session configurable (skip_asia par defaut)
      - Pullback prealable via context rolling
    """

    name = "pullback_confluence_0dte"

    def __init__(
        self,
        max_dist_0dte_ticks: float = 100.0,
        sl_ticks: int = 20,              # Fallback si sl_structural=False
        sl_structural: bool = True,       # v2.1 : SL anti-stop-hunt (Jackson 21/04)
        sl_min_ticks: int = 15,           # Bornes SL structurel
        sl_max_ticks: int = 60,
        sl_buffer_ticks: int = 3,         # Buffer sous niveau structurel
        sl_atr_multiplier: float = 2.5,   # v2.2 : ATR mult pour fallback SL
        tp_ticks_fixed: int = 36,
        tp_dyn_min_ticks: int = 20,   # TP dynamique minimum (evite TP trop proche)
        tp_dyn_max_ticks: int = 80,   # TP dynamique maximum (au-dela = fixe 36)
        tp_gex_buffer_ticks: int = 3, # v2.2 : buffer sous GEX pour TP (evite rejet pile)
        require_gamma_positive: bool = True,
        require_pullback: bool = True,
        pullback_min_ticks: int = 15,  # Pullback minimum requis en ticks
        skip_sessions: tuple = ("Asia",),  # Sessions a skipper
    ):
        self.max_dist_0dte_ticks = float(max_dist_0dte_ticks)
        self.sl_ticks = int(sl_ticks)
        self.sl_structural = bool(sl_structural)
        self.sl_min_ticks = int(sl_min_ticks)
        self.sl_max_ticks = int(sl_max_ticks)
        self.sl_buffer_ticks = int(sl_buffer_ticks)
        self.sl_atr_multiplier = float(sl_atr_multiplier)
        self.tp_ticks_fixed = int(tp_ticks_fixed)
        self.tp_dyn_min_ticks = int(tp_dyn_min_ticks)
        self.tp_dyn_max_ticks = int(tp_dyn_max_ticks)
        self.tp_gex_buffer_ticks = int(tp_gex_buffer_ticks)
        self.require_gamma_positive = bool(require_gamma_positive)
        self.require_pullback = bool(require_pullback)
        self.pullback_min_ticks = int(pullback_min_ticks)
        self.skip_sessions = tuple(skip_sessions)

    def required_features(self) -> list[str]:
        return [
            "bn_color_up", "bn_color_dn", "bn_long_up", "bn_long_dn",
            "mq_gamma_condition",
            "dist_mq_call_0dte", "dist_mq_put_0dte",
            "dist_gex_nearest_up", "dist_gex_nearest_dn",
            "dist_swing_low", "dist_swing_high",  # v2.1 SL structurel
            "atr",                                  # v2.1 fallback ATR
            "session_id",
            "price",
        ]

    def _compute_structural_sl(self, direction: str, row: pd.Series) -> int:
        """
        Calcule SL base sur NIVEAU STRUCTUREL (anti stop-hunters).

        Priorite :
          1. Swing low/high (boule) si raisonnable
          2. Put/Call 0DTE si tres proche (confluence double)
          3. ATR-based (2.5x atr_ticks)
          4. Fallback sl_ticks fixe (20t)

        Returns SL en ticks (borne sl_min/sl_max).
        """
        if not self.sl_structural:
            return self.sl_ticks

        # v2.2 (code-reviewer 22/04) : Nouvelle priorite = prendre le PLUS PROCHE
        # valide entre swing et put/call 0DTE, pas swing systematiquement.
        # Rationale : 0DTE domine comportement intraday (hedge dealers).
        # Si put_0dte a 10t et swing_low a 45t -> put_0dte plus pertinent.
        candidates = []

        if direction == "BUY":
            dsl = _finite(row.get("dist_swing_low"))
            if dsl is not None and dsl < 0:
                c = int(abs(dsl)) + self.sl_buffer_ticks
                if self.sl_min_ticks <= c <= self.sl_max_ticks:
                    candidates.append((c, "swing_low"))
            dput = _finite(row.get("dist_mq_put_0dte"))
            if dput is not None and dput < 0 and abs(dput) < self.sl_max_ticks:
                c = int(abs(dput)) + self.sl_buffer_ticks
                if self.sl_min_ticks <= c <= self.sl_max_ticks:
                    candidates.append((c, "put_0dte"))
        else:  # SELL
            dsh = _finite(row.get("dist_swing_high"))
            if dsh is not None and dsh > 0:
                c = int(dsh) + self.sl_buffer_ticks
                if self.sl_min_ticks <= c <= self.sl_max_ticks:
                    candidates.append((c, "swing_high"))
            dcall = _finite(row.get("dist_mq_call_0dte"))
            if dcall is not None and dcall > 0 and dcall < self.sl_max_ticks:
                c = int(dcall) + self.sl_buffer_ticks
                if self.sl_min_ticks <= c <= self.sl_max_ticks:
                    candidates.append((c, "call_0dte"))

        # v2.2 : prendre le PLUS PROCHE (SL le plus serre mais structurel)
        if candidates:
            best = min(candidates, key=lambda x: x[0])
            return best[0]

        # Priorite 3 : ATR-based (fallback si aucun niveau structurel)
        atr = _finite(row.get("atr"))
        if atr is not None and atr > 0:
            # atr est en ticks dans le JSONL (verifie 09/04 lessons.md)
            candidate = max(self.sl_min_ticks, int(self.sl_atr_multiplier * atr))
            return min(candidate, self.sl_max_ticks)

        # Priorite 4 : fallback hardcoded sl_ticks
        return self.sl_ticks

    def _compute_tp_ticks(self, direction: str, row: pd.Series) -> tuple[int, str]:
        """Calcule TP dynamique vers GEX si proche, sinon fixe.

        Returns:
            (tp_ticks, tp_source) ou tp_source in {"gex_dyn", "fixed"}
        """
        if direction == "BUY":
            d_gex_up = _finite(row.get("dist_gex_nearest_up"))
            if d_gex_up is not None:
                d_abs = abs(d_gex_up)
                # dist_gex = niveau - prix. Pour LONG, on veut GEX au-dessus = dist > 0
                if d_gex_up > 0 and self.tp_dyn_min_ticks <= d_abs <= self.tp_dyn_max_ticks:
                    # TP = GEX distance - buffer (eviter rejet pile au niveau)
                    tp_dyn = max(self.tp_dyn_min_ticks, int(d_abs) - self.tp_gex_buffer_ticks)
                    return tp_dyn, f"gex_dyn_{int(d_abs)}t"
        else:  # SELL
            d_gex_dn = _finite(row.get("dist_gex_nearest_dn"))
            if d_gex_dn is not None:
                d_abs = abs(d_gex_dn)
                # Pour SHORT, on veut GEX en-dessous = dist < 0
                if d_gex_dn < 0 and self.tp_dyn_min_ticks <= d_abs <= self.tp_dyn_max_ticks:
                    tp_dyn = max(self.tp_dyn_min_ticks, int(d_abs) - self.tp_gex_buffer_ticks)
                    return tp_dyn, f"gex_dyn_{int(d_abs)}t"

        # Fallback fixe
        return self.tp_ticks_fixed, "fixed"

    def _check_pullback(self, direction: str, row: pd.Series,
                       context: Optional[dict]) -> tuple[bool, str]:
        """Verifie qu'un pullback prealable existe.

        Returns:
            (pullback_ok, reason)
        """
        if not self.require_pullback:
            return True, "pullback_not_required"

        if context is None:
            return False, "no_context"

        current_price = _finite(row.get("price"))
        if current_price is None:
            return False, "no_price"

        min_ticks = self.pullback_min_ticks
        threshold = min_ticks * TICK_SIZE_NQ

        if direction == "BUY":
            # Pour LONG : prix doit avoir PULL DOWN depuis un high recent
            lookback_max = context.get("lookback_max_price")
            if lookback_max is None:
                return False, "no_lookback_max"
            pull = float(lookback_max) - current_price
            if pull >= threshold:
                return True, f"pullback_down_{pull:.1f}pts"
            return False, f"pullback_insuffisant_{pull:.1f}pts"

        else:  # SELL
            # Pour SHORT : prix doit avoir RALLY UP depuis un low recent
            lookback_min = context.get("lookback_min_price")
            if lookback_min is None:
                return False, "no_lookback_min"
            rally = current_price - float(lookback_min)
            if rally >= threshold:
                return True, f"rally_up_{rally:.1f}pts"
            return False, f"rally_insuffisant_{rally:.1f}pts"

    def generate_signal(self, row: pd.Series, context: Optional[dict] = None) -> Signal:
        # Features features
        color_up = int(_finite(row.get("bn_color_up")) or 0)
        color_dn = int(_finite(row.get("bn_color_dn")) or 0)
        long_up = int(_finite(row.get("bn_long_up")) or 0)
        long_dn = int(_finite(row.get("bn_long_dn")) or 0)
        gamma_cond = _finite(row.get("mq_gamma_condition"))
        dist_call_0dte = _finite(row.get("dist_mq_call_0dte"))
        dist_put_0dte = _finite(row.get("dist_mq_put_0dte"))
        session_id = row.get("session_id", "")

        # HOLD si gamma_condition manque
        if gamma_cond is None:
            return Signal(type=SignalType.HOLD, reason="gamma_condition_missing")

        # Filtre session (skip Asia par defaut)
        if session_id in self.skip_sessions:
            return Signal(type=SignalType.HOLD, reason=f"session_skipped_{session_id}")

        # Filtre gamma
        if self.require_gamma_positive and int(gamma_cond) != 1:
            return Signal(type=SignalType.HOLD, reason=f"gamma_negative_{int(gamma_cond)}")

        # Trigger LONG
        long_trigger = (color_up == 1 and long_up == 1)
        if long_trigger and dist_call_0dte is not None:
            if abs(dist_call_0dte) < self.max_dist_0dte_ticks:
                # Pullback check
                pb_ok, pb_reason = self._check_pullback("BUY", row, context)
                if not pb_ok:
                    return Signal(type=SignalType.HOLD, reason=f"no_pullback:{pb_reason}")
                # TP dynamique
                tp_ticks, tp_src = self._compute_tp_ticks("BUY", row)
                sl_ticks = self._compute_structural_sl("BUY", row)
                return Signal(
                    type=SignalType.BUY,
                    sl_ticks=sl_ticks,
                    tp_ticks=tp_ticks,
                    reason=f"long_call0dte_confluence dist={dist_call_0dte:.0f}t tp={tp_src} pb={pb_reason}",
                    meta={
                        "dist_call_0dte": dist_call_0dte,
                        "gamma_condition": int(gamma_cond),
                        "session": str(session_id),
                        "tp_source": tp_src,
                        "pullback_reason": pb_reason,
                    },
                )

        # Trigger SHORT
        short_trigger = (color_dn == 1 and long_dn == 1)
        if short_trigger and dist_put_0dte is not None:
            if abs(dist_put_0dte) < self.max_dist_0dte_ticks:
                pb_ok, pb_reason = self._check_pullback("SELL", row, context)
                if not pb_ok:
                    return Signal(type=SignalType.HOLD, reason=f"no_rally:{pb_reason}")
                tp_ticks, tp_src = self._compute_tp_ticks("SELL", row)
                sl_ticks = self._compute_structural_sl("SELL", row)
                return Signal(
                    type=SignalType.SELL,
                    sl_ticks=sl_ticks,
                    tp_ticks=tp_ticks,
                    reason=f"short_put0dte_confluence dist={dist_put_0dte:.0f}t tp={tp_src} rally={pb_reason}",
                    meta={
                        "dist_put_0dte": dist_put_0dte,
                        "gamma_condition": int(gamma_cond),
                        "session": str(session_id),
                        "tp_source": tp_src,
                        "rally_reason": pb_reason,
                    },
                )

        return Signal(type=SignalType.HOLD)
