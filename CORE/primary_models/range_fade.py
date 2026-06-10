"""
Primary Model — Range Fade (Setup #2 Jackson)
===============================================

Setup Jackson formalise 21/04/2026 soir via Protocole A.

PHILOSOPHIE
-----------
Dans un range tradable (assez large pour gagner des ticks) :
  - Les boules ROUGES en haut sont defendues par les VENDEURS (resistance)
  - Les boules VERTES en bas sont defendues par les ACHETEURS (support)
  - Fader les extremes avec stop de l'autre cote + TP middle ou 3/4

Citation Jackson : "boule rouge en haut defendue par les vendeurs,
boule verte en bas defendue par les acheteurs, SL et TP au middle ou 3/4"

DETECTION DU RANGE
------------------
Un range est confirme si :
  1. Au moins 2 boules ROUGES recentes groupees (ecart <= cluster_tolerance_ticks)
     -> forme une zone RESISTANCE (niveau_red = moyenne de leurs prix)
  2. Au moins 2 boules VERTES recentes groupees -> zone SUPPORT (niveau_green)
  3. range_width = niveau_red - niveau_green >= min_range_ticks
  4. Pas de boule VERTE recente AU-DESSUS des rouges (trend bullish = pas range)
  5. Pas de boule ROUGE recente EN-DESSOUS des vertes (trend bearish = pas range)

ENTRY LOGIC
-----------
LONG (fade support vert) :
  - Prix revient a distance entry_zone_ticks de niveau_green
  - bn_color_up=1 AND bn_long_up=1 (double confirm achat)
  - Entry @ current price
  - SL = niveau_green - sl_buffer_ticks (invalide support)
  - TP = middle OR 3/4 selon tp_mode

SHORT (fade resistance rouge) :
  - Prix revient a distance entry_zone_ticks de niveau_red
  - bn_color_dn=1 AND bn_long_dn=1 (double confirm vente)
  - Entry @ current price
  - SL = niveau_red + sl_buffer_ticks
  - TP = middle OR 3/4

INVALIDATION DU RANGE
---------------------
Range INVALIDE si :
  - Prix casse niveau_green de plus de breakout_ticks (support casse = trend down)
  - Prix casse niveau_red de plus de breakout_ticks (resistance casse = trend up)
  -> reset state, attente nouveau range

STATE INTERNE
-------------
- `swings_buffer` : deque SwingDot (reutilise Bataille Navale)
- `current_range` : dict {green_level, red_level, width} ou None
- `range_since_bar` : bar index ou le range a ete detecte

FEATURES REQUISES
-----------------
- price, new_swing_high, new_swing_low (events boules)
- bn_color_up/dn, bn_long_up/dn (double confirm)

Auteur : Claude (mentor Jackson) — 21/04/2026
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
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
class Swing:
    bar_index: int
    price: float
    is_low: bool


class RangeFadeModel(PrimaryModel):
    """
    Range Fade — fade des extremes d'un range defendu par boules.

    Stateful : detecte et maintient un range valide.
    """

    name = "range_fade"

    def __init__(
        self,
        swing_buffer_size: int = 15,
        min_range_ticks: int = 20,             # Range >= 5 pts NQ pour tradable
        max_range_ticks: int = 80,             # Range <= 20 pts (au-dela c'est pas range)
        cluster_tolerance_ticks: int = 6,      # 2 rouges/vertes groupees <= 6t ecart
        entry_zone_ticks: int = 8,             # Entry si prix a <= 8t de l'extreme
        sl_buffer_ticks: int = 4,              # SL de l'autre cote extreme + 4t
        breakout_ticks: int = 6,               # Range casse si prix sort > 6t
        tp_mode: str = "middle",               # "middle" ou "three_quarter"
        require_footprint_confirm: bool = True,
        dedup_bars: int = 15,
    ):
        self.swing_buffer_size = int(swing_buffer_size)
        self.min_range_ticks = int(min_range_ticks)
        self.max_range_ticks = int(max_range_ticks)
        self.cluster_tolerance_ticks = int(cluster_tolerance_ticks)
        self.entry_zone_ticks = int(entry_zone_ticks)
        self.sl_buffer_ticks = int(sl_buffer_ticks)
        self.breakout_ticks = int(breakout_ticks)
        self.tp_mode = tp_mode
        self.require_footprint_confirm = bool(require_footprint_confirm)
        self.dedup_bars = int(dedup_bars)

        self.swings: deque[Swing] = deque(maxlen=self.swing_buffer_size)
        self.current_bar = 0
        self.last_signal_bar = -9999
        self.current_range: Optional[dict] = None
        self.range_since_bar = -9999

    def required_features(self) -> list[str]:
        return [
            "price",
            "new_swing_high", "new_swing_low",
            "bn_color_up", "bn_color_dn", "bn_long_up", "bn_long_dn",
        ]

    def _update_swings(self, row: pd.Series) -> None:
        price = _finite(row.get("price"))
        if price is None:
            return
        if int(_finite(row.get("new_swing_high")) or 0) == 1:
            self.swings.append(Swing(self.current_bar, price, is_low=False))
        if int(_finite(row.get("new_swing_low")) or 0) == 1:
            self.swings.append(Swing(self.current_bar, price, is_low=True))

    def _detect_range(self) -> Optional[dict]:
        """Detecte si buffer contient un range valide.

        Retour : {green_level, red_level, width_ticks} ou None.
        """
        greens = [s for s in self.swings if s.is_low]
        reds = [s for s in self.swings if not s.is_low]

        if len(greens) < 2 or len(reds) < 2:
            return None

        # 2 dernieres vertes doivent etre groupees
        g_last = greens[-1]
        g_prev = greens[-2]
        g_spread = abs(g_last.price - g_prev.price) / TICK_SIZE_NQ
        if g_spread > self.cluster_tolerance_ticks:
            return None
        green_level = (g_last.price + g_prev.price) / 2

        # 2 dernieres rouges groupees
        r_last = reds[-1]
        r_prev = reds[-2]
        r_spread = abs(r_last.price - r_prev.price) / TICK_SIZE_NQ
        if r_spread > self.cluster_tolerance_ticks:
            return None
        red_level = (r_last.price + r_prev.price) / 2

        # Width range
        width_ticks = (red_level - green_level) / TICK_SIZE_NQ
        if width_ticks < self.min_range_ticks:
            return None
        if width_ticks > self.max_range_ticks:
            return None

        # Rouge ne doit pas etre SOUS verte (trend cassé)
        if red_level <= green_level:
            return None

        # FIX 21/04/2026 (code-reviewer CRITIQUE) :
        # Bug initial = iterer sur TOUS les greens/reds du buffer (15 max)
        # Consequence : si trend bullish anterieur avait produit un green
        # au-dessus du red_level actuel -> range rejete a tort.
        #
        # Fix : ne regarder que les RECENTS (les 3 derniers par cote).
        # Rationale : un range se confirme sur les 3 derniers tests, pas
        # sur toute l'histoire.
        recent_greens = greens[-3:] if len(greens) >= 3 else greens
        recent_reds = reds[-3:] if len(reds) >= 3 else reds

        for g in recent_greens:
            if g.price > red_level + self.breakout_ticks * TICK_SIZE_NQ:
                return None
        for r in recent_reds:
            if r.price < green_level - self.breakout_ticks * TICK_SIZE_NQ:
                return None

        return {
            "green_level": green_level,
            "red_level": red_level,
            "width_ticks": width_ticks,
            "middle": (green_level + red_level) / 2,
        }

    def _check_range_still_valid(self, range_info: dict, current_price: float) -> bool:
        """Range invalide si prix casse niveau + breakout_ticks."""
        green = range_info["green_level"]
        red = range_info["red_level"]
        if current_price < green - self.breakout_ticks * TICK_SIZE_NQ:
            return False
        if current_price > red + self.breakout_ticks * TICK_SIZE_NQ:
            return False
        return True

    def _compute_tp_long(self, entry_price: float, range_info: dict) -> int:
        """TP LONG depuis entry selon mode."""
        green = range_info["green_level"]
        red = range_info["red_level"]
        if self.tp_mode == "three_quarter":
            tp_price = green + 0.75 * (red - green)
        else:  # middle
            tp_price = range_info["middle"]
        tp_ticks = int((tp_price - entry_price) / TICK_SIZE_NQ)
        return max(5, tp_ticks)  # min 5 ticks

    def _compute_tp_short(self, entry_price: float, range_info: dict) -> int:
        green = range_info["green_level"]
        red = range_info["red_level"]
        if self.tp_mode == "three_quarter":
            tp_price = red - 0.75 * (red - green)
        else:
            tp_price = range_info["middle"]
        tp_ticks = int((entry_price - tp_price) / TICK_SIZE_NQ)
        return max(5, tp_ticks)

    def generate_signal(self, row: pd.Series, context: Optional[dict] = None) -> Signal:
        self.current_bar += 1
        self._update_swings(row)

        price = _finite(row.get("price"))
        if price is None:
            return Signal(type=SignalType.HOLD, reason="no_price")

        # Dedup
        if self.current_bar - self.last_signal_bar < self.dedup_bars:
            return Signal(type=SignalType.HOLD, reason="dedup")

        # Invalidation range existant
        if self.current_range is not None:
            if not self._check_range_still_valid(self.current_range, price):
                self.current_range = None

        # Detection range si pas deja actif
        if self.current_range is None:
            r = self._detect_range()
            if r is not None:
                self.current_range = r
                self.range_since_bar = self.current_bar

        if self.current_range is None:
            return Signal(type=SignalType.HOLD, reason="no_range_detected")

        r = self.current_range
        green = r["green_level"]
        red = r["red_level"]
        middle = r["middle"]

        # Position prix
        dist_to_green_ticks = (price - green) / TICK_SIZE_NQ
        dist_to_red_ticks = (red - price) / TICK_SIZE_NQ

        color_up = int(_finite(row.get("bn_color_up")) or 0)
        color_dn = int(_finite(row.get("bn_color_dn")) or 0)
        long_up = int(_finite(row.get("bn_long_up")) or 0)
        long_dn = int(_finite(row.get("bn_long_dn")) or 0)

        # LONG : prix proche du support vert
        if 0 <= dist_to_green_ticks <= self.entry_zone_ticks:
            if self.require_footprint_confirm:
                if color_up == 0 or long_up == 0:
                    return Signal(type=SignalType.HOLD,
                                 reason=f"green_close_no_footprint d={dist_to_green_ticks:.0f}t")
            # Signal BUY
            sl_price = green - self.sl_buffer_ticks * TICK_SIZE_NQ
            sl_ticks = int((price - sl_price) / TICK_SIZE_NQ)
            sl_ticks = max(5, min(30, sl_ticks))
            tp_ticks = self._compute_tp_long(price, r)
            self.last_signal_bar = self.current_bar
            return Signal(
                type=SignalType.BUY,
                sl_ticks=sl_ticks,
                tp_ticks=tp_ticks,
                reason=f"range_fade_long green={green:.2f} red={red:.2f} width={r['width_ticks']:.0f}t tp_mode={self.tp_mode}",
                meta={
                    "pattern": "RANGE_FADE_LONG",
                    "green": green,
                    "red": red,
                    "middle": middle,
                    "width_ticks": r["width_ticks"],
                    "dist_to_support": dist_to_green_ticks,
                    "tp_mode": self.tp_mode,
                },
            )

        # SHORT : prix proche de la resistance rouge
        if 0 <= dist_to_red_ticks <= self.entry_zone_ticks:
            if self.require_footprint_confirm:
                if color_dn == 0 or long_dn == 0:
                    return Signal(type=SignalType.HOLD,
                                 reason=f"red_close_no_footprint d={dist_to_red_ticks:.0f}t")
            sl_price = red + self.sl_buffer_ticks * TICK_SIZE_NQ
            sl_ticks = int((sl_price - price) / TICK_SIZE_NQ)
            sl_ticks = max(5, min(30, sl_ticks))
            tp_ticks = self._compute_tp_short(price, r)
            self.last_signal_bar = self.current_bar
            return Signal(
                type=SignalType.SELL,
                sl_ticks=sl_ticks,
                tp_ticks=tp_ticks,
                reason=f"range_fade_short green={green:.2f} red={red:.2f} width={r['width_ticks']:.0f}t tp_mode={self.tp_mode}",
                meta={
                    "pattern": "RANGE_FADE_SHORT",
                    "green": green,
                    "red": red,
                    "middle": middle,
                    "width_ticks": r["width_ticks"],
                    "dist_to_resistance": dist_to_red_ticks,
                    "tp_mode": self.tp_mode,
                },
            )

        return Signal(type=SignalType.HOLD,
                     reason=f"in_range_middle price={price:.2f} G={green:.2f} R={red:.2f}")
