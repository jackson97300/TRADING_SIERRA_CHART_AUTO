"""
Primary Model — Bataille Navale (Dow Theory stateful via swing dots)
======================================================================

Setup Jackson formalise 21/04/2026 soir.
Source : papier V6 C++ `CPP/MIA_DowHybrid_System.cpp` (2715 LOC) +
         regle d'or Jackson "pas de boule rouge sous la derniere verte".

PHILOSOPHIE
-----------
Theorie de Dow classique appliquee intraday via les swing points du footprint :
  - Boule VERTE = new_swing_low (support)
  - Boule ROUGE = new_swing_high (resistance)
  - UPTREND CONFIRME = 3+ boules vertes ASCENDANTES (Higher Lows)

PHASE 1 : BUY/UPTREND SEULEMENT. DOWNTREND SELL = TODO Phase 2.
  Code-reviewer 21/04/2026 a flague l'incoherence doc vs code.
  Implementation miroir possible : 3+ boules rouges descendantes (Lower Highs)
  + regle d'or "aucune verte AU-DESSUS derniere rouge" + pullback vers last_red.

REGLE D'OR ABSOLUE (Jackson)
-----------------------------
Uptrend valide SI aucune boule ROUGE sous la derniere boule VERTE.
Si rouge casse sous verte recente -> trend INVALIDE, reset.
Equivalent a "structure Dow cassee" = sortie obligatoire.

ENTRY LOGIC
-----------
1. Trend UPTREND confirme (>= 3 HL consecutifs)
2. Golden rule respectee (pas de rouge sous derniere verte)
3. Pullback vers derniere boule verte (prix s'en rapproche)
4. Footprint confirm (bn_color_up=1 OU bn_long_up=1)
5. Entry BUY @ current price

MATURITY (V6 concept)
---------------------
FRESH   : 3 boules vertes ascendantes (OPTIMAL POUR ENTRER)
MATURE  : 4-5 boules (trailing serre)
EXTENDED: 6+ boules (TP reduit 30%, tendance peut epuiser)

SL / TP
-------
SL = sous l'AVANT-DERNIERE boule verte (buffer - 3 ticks)
     = si cassure = trend mort, sortie immediate
TP = dynamique GEX proche si disponible, sinon 36 ticks fixe

STATE INTERNE (stateful)
-------------------------
- `swings_buffer` : liste derniers N swings (verts + rouges, alternes ou non)
- `current_trend` : "UPTREND" / "DOWNTREND" / "NONE"
- `hl_streak` : nombre de HL consecutifs (pour UPTREND)
- `lh_streak` : nombre de LH consecutifs (pour DOWNTREND)
- `trend_broken` : flag si golden rule violee
- `last_signal_bar` : pour dedup

IMPORTANT : ce modele MUTE son etat interne a chaque generate_signal().
Dans un multi-primary setup, chaque symbole doit avoir SA propre instance.

FEATURES REQUISES
-----------------
- new_swing_high, new_swing_low (0/1 events)
- dist_swing_high, dist_swing_low (ticks vers dernier swing)
- bn_color_up, bn_color_dn, bn_long_up, bn_long_dn
- dist_gex_nearest_up, dist_gex_nearest_dn (pour TP dynamique)
- mq_gamma_condition (filtre optionnel)
- price

Auteur : Claude (mentor Jackson) — 21/04/2026
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from CORE.primary_models.base import PrimaryModel, Signal, SignalType


TICK_SIZE_NQ = 0.25


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


@dataclass
class SwingDot:
    """Un swing point detecte (vert=low ou rouge=high)."""
    bar_index: int
    price: float
    is_low: bool  # True = GREEN swing_low, False = RED swing_high


class BatailleNavaleModel(PrimaryModel):
    """
    Setup #3 Jackson — Bataille Navale (Dow stateful).

    Stateful : maintient buffer swings recents et tracke HL/LH streaks.
    Version Phase 1 minimum viable, portage partiel V6 C++ (2715 LOC -> ~200 LOC).
    """

    name = "bataille_navale"

    def __init__(
        self,
        swing_buffer_size: int = 10,
        min_confirm_streak: int = 3,         # 3 HL = uptrend confirme
        fresh_max_greens: int = 3,           # <=3 vertes = FRESH
        mature_max_greens: int = 5,          # 4-5 = MATURE
        # EXTENDED = 6+
        sl_buffer_ticks: int = 3,             # SL = avant-derniere verte - buffer
        sl_fallback_ticks: int = 20,          # v1.1 : fallback si calc SL hors range
        tp_ticks_fixed: int = 36,
        tp_dyn_min_ticks: int = 20,
        tp_dyn_max_ticks: int = 80,
        extended_tp_reduction: float = 0.7,   # v1.1 : TP reduit 30% si EXTENDED
        pullback_zone_ticks: int = 10,        # Entry zone autour derniere verte (+/- 10t)
        require_footprint_confirm: bool = True,
        dedup_bars: int = 30,                 # v1.1 : dedup param (code-reviewer fix)
    ):
        self.swing_buffer_size = int(swing_buffer_size)
        self.min_confirm_streak = int(min_confirm_streak)
        self.fresh_max_greens = int(fresh_max_greens)
        self.mature_max_greens = int(mature_max_greens)
        self.sl_buffer_ticks = int(sl_buffer_ticks)
        self.sl_fallback_ticks = int(sl_fallback_ticks)
        self.tp_ticks_fixed = int(tp_ticks_fixed)
        self.tp_dyn_min_ticks = int(tp_dyn_min_ticks)
        self.tp_dyn_max_ticks = int(tp_dyn_max_ticks)
        self.extended_tp_reduction = float(extended_tp_reduction)
        self.pullback_zone_ticks = int(pullback_zone_ticks)
        self.require_footprint_confirm = bool(require_footprint_confirm)
        self.dedup_bars = int(dedup_bars)

        # State interne (mute au fil des barres)
        self.swings: deque[SwingDot] = deque(maxlen=self.swing_buffer_size)
        self.current_bar = 0
        self.last_signal_bar = -9999

    def reset_state(self):
        """Reset state (utile entre sessions ou apres trade)."""
        self.swings.clear()
        self.last_signal_bar = -9999

    def required_features(self) -> list[str]:
        return [
            "new_swing_high", "new_swing_low",
            "bn_color_up", "bn_color_dn", "bn_long_up", "bn_long_dn",
            "dist_gex_nearest_up", "dist_gex_nearest_dn",
            "mq_gamma_condition",
            "price",
        ]

    def _update_swings(self, row: pd.Series) -> None:
        """Detecte new_swing events et update buffer."""
        price = _finite(row.get("price"))
        if price is None:
            return
        new_sh = int(_finite(row.get("new_swing_high")) or 0)
        new_sl = int(_finite(row.get("new_swing_low")) or 0)
        if new_sh == 1:
            self.swings.append(SwingDot(self.current_bar, price, is_low=False))
        if new_sl == 1:
            self.swings.append(SwingDot(self.current_bar, price, is_low=True))

    def _analyze_trend(self) -> tuple[str, int, str, Optional[SwingDot], Optional[SwingDot]]:
        """Analyse buffer swings pour detecter trend confirme + golden rule.

        Returns:
            (trend_state, streak, maturity, last_green, prev_green)
            trend_state : "UPTREND_VALID" / "UPTREND_BROKEN" / "NONE"
            streak : nombre de HL consecutifs
            maturity : "FRESH" / "MATURE" / "EXTENDED" / "NONE"
            last_green : derniere boule verte (support actuel)
            prev_green : avant-derniere boule verte (pour SL)
        """
        greens = [s for s in self.swings if s.is_low]
        reds = [s for s in self.swings if not s.is_low]

        if len(greens) < self.min_confirm_streak:
            return ("NONE", 0, "NONE", greens[-1] if greens else None, None)

        # Check HL streak : compter verts ascendants consecutifs (en partant de la fin)
        streak = 1
        for i in range(len(greens) - 1, 0, -1):
            if greens[i].price > greens[i-1].price:
                streak += 1
            else:
                break

        if streak < self.min_confirm_streak:
            return ("NONE", streak, "NONE", greens[-1], greens[-2] if len(greens) >= 2 else None)

        last_green = greens[-1]
        prev_green = greens[-2]

        # REGLE D'OR Jackson : aucune boule rouge SOUS la derniere verte
        # (ie : apres last_green.bar_index, aucun red a price < last_green.price)
        for r in reds:
            if r.bar_index > last_green.bar_index and r.price < last_green.price:
                return ("UPTREND_BROKEN", streak, "NONE", last_green, prev_green)

        # Maturity
        if streak <= self.fresh_max_greens:
            maturity = "FRESH"
        elif streak <= self.mature_max_greens:
            maturity = "MATURE"
        else:
            maturity = "EXTENDED"

        return ("UPTREND_VALID", streak, maturity, last_green, prev_green)

    def _compute_tp_ticks(self, row: pd.Series, maturity: str) -> tuple[int, str]:
        """TP dynamique vers GEX si proche. Reduit si EXTENDED (configurable)."""
        base_tp = self.tp_ticks_fixed
        if maturity == "EXTENDED":
            base_tp = int(base_tp * self.extended_tp_reduction)

        d_gex_up = _finite(row.get("dist_gex_nearest_up"))
        if d_gex_up is not None and d_gex_up > 0:
            d_abs = abs(d_gex_up)
            if self.tp_dyn_min_ticks <= d_abs <= self.tp_dyn_max_ticks:
                tp_dyn = max(self.tp_dyn_min_ticks, int(d_abs) - 3)
                if maturity == "EXTENDED":
                    tp_dyn = int(tp_dyn * self.extended_tp_reduction)
                return tp_dyn, f"gex_dyn_{int(d_abs)}t_{maturity}"

        return base_tp, f"fixed_{maturity}"

    def _compute_sl_ticks(self, entry_price: float,
                         prev_green: Optional[SwingDot]) -> int:
        """SL = sous avant-derniere boule verte - buffer.

        Si prev_green absent ou calcul hors range raisonnable, fallback sl_fallback_ticks.
        """
        if prev_green is None:
            return self.sl_fallback_ticks
        sl_price = prev_green.price - self.sl_buffer_ticks * TICK_SIZE_NQ
        sl_ticks = int((entry_price - sl_price) / TICK_SIZE_NQ)
        if sl_ticks < 5 or sl_ticks > 50:
            return self.sl_fallback_ticks  # fallback configurable
        return sl_ticks

    def generate_signal(self, row: pd.Series, context: Optional[dict] = None) -> Signal:
        self.current_bar += 1

        # Update swing buffer AVANT d'analyser (on integre la barre courante)
        self._update_swings(row)

        # Features lecture
        price = _finite(row.get("price"))
        if price is None:
            return Signal(type=SignalType.HOLD, reason="no_price")

        # Dedup : eviter triggers consecutifs (configurable v1.1 code-reviewer)
        if self.current_bar - self.last_signal_bar < self.dedup_bars:
            return Signal(type=SignalType.HOLD, reason="dedup")

        # Analyse trend
        trend_state, streak, maturity, last_green, prev_green = self._analyze_trend()

        if trend_state == "UPTREND_BROKEN":
            return Signal(type=SignalType.HOLD, reason=f"trend_broken_streak{streak}")

        if trend_state != "UPTREND_VALID":
            return Signal(type=SignalType.HOLD, reason=f"no_trend_streak{streak}")

        # Pullback check : prix doit etre proche (zone) de la derniere verte
        # "Pullback" = prix au-dessus mais dans pullback_zone_ticks de last_green
        # NB BUG D 15/05/2026 : variable locale (price - last_green) volontairement
        # convention LOCALE (close - level), pas (level - close). Pas impact features
        # externes (variable interne fonction). Logique L285 if < 0 = "below green"
        # OK avec cette convention locale.
        if last_green is None:
            return Signal(type=SignalType.HOLD, reason="no_last_green")
        dist_from_green_ticks = (price - last_green.price) / TICK_SIZE_NQ
        if dist_from_green_ticks < 0:
            return Signal(type=SignalType.HOLD, reason=f"below_green_{dist_from_green_ticks:.0f}t")
        if dist_from_green_ticks > self.pullback_zone_ticks:
            return Signal(type=SignalType.HOLD, reason=f"too_far_from_green_{dist_from_green_ticks:.0f}t")

        # Footprint confirm
        if self.require_footprint_confirm:
            color_up = int(_finite(row.get("bn_color_up")) or 0)
            long_up = int(_finite(row.get("bn_long_up")) or 0)
            if color_up == 0 and long_up == 0:
                return Signal(type=SignalType.HOLD, reason="no_footprint_confirm")

        # Signal valide !
        sl_ticks = self._compute_sl_ticks(price, prev_green)
        tp_ticks, tp_src = self._compute_tp_ticks(row, maturity)

        self.last_signal_bar = self.current_bar

        return Signal(
            type=SignalType.BUY,
            sl_ticks=sl_ticks,
            tp_ticks=tp_ticks,
            reason=f"bataille_navale_UP streak={streak} {maturity} green={last_green.price:.2f} tp={tp_src}",
            meta={
                "trend": "UPTREND_VALID",
                "streak": streak,
                "maturity": maturity,
                "last_green_price": last_green.price,
                "prev_green_price": prev_green.price if prev_green else None,
                "pullback_ticks": dist_from_green_ticks,
                "tp_source": tp_src,
            },
        )
