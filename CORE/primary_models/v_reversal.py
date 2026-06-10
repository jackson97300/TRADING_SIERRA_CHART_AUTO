"""
Primary Model — V-bottom / Λ-top Reversal Pattern
===================================================

Setup Jackson formalise 21/04/2026 soir apres analyse empirique crash 20/04 17:07 Paris.
Post-it Jackson : "Secoue (V ou ∧)" = pattern de capitulation + rebond violent.

PHILOSOPHIE
-----------
Apres une chute violente (capitulation vendeurs), les institutionnels absorbent
la vente panique et poussent le rebond. Le pattern V se caracterise par :
  1. Descente violente (range significatif en N bars)
  2. Pause breve (consolidation au low)
  3. Rally violent avec volume spike (> 1.5x moyenne)
  4. Confirmation footprint (color_up + long_up simultanes)

Meme logique pour Λ-top (symmetrique) apres montee violente.

SOURCE
------
Trade empirique Jackson 20/04 :
  - HIGH 26783 @ 16:08 Paris
  - LOW  26575 @ 17:07 Paris (-208 pts en 90 min)
  - Rally confirme 17:20 Paris @ 26649 avec vol 3833 + color_up + long_up
  - Target 26699 @ 17:29 Paris (+124 pts depuis low en 22 min)

LOGIQUE STATEFUL
----------------
1. Maintenir buffer N dernieres barres (prix, volume, bar_high, bar_low)
2. Detecter CAPITULATION :
   - Prix a chute de >= drop_min_pts sur les last_N_bars
   - bar_low du low recent est significativement sous les precedents
3. Detecter REBOUND :
   - Prix a rebondi de >= rebound_min_pts depuis le low recent
   - Volume de la barre rebound > vol_spike_ratio * vol_moyen_20
   - bn_color_up=1 AND bn_long_up=1
4. Trigger : BUY @ current price

ENTRY / SL / TP
---------------
Entry : current close apres confirmation rebound
SL    : sous le LOW recent - buffer (ex: low - 5 ticks)
TP    : 50% du drop initial (Fibonacci 50%) OU R:R >= 2 OU niveau option

ANTI-PATTERNS EVITES
--------------------
- Pas de buy-the-dip "knife catcher" : attend confirmation footprint
- Pas d'entry sur la 1ere bar de rebound : attend volume + double confirm
- Cooldown : pas de 2e trigger dans les 30 bars apres trigger precedent

FEATURES REQUISES (code-reviewer 21/04 fix : cohérence doc vs code)
-----------------
- price, bar_high, bar_low (range bar)
- total_vol
- bn_color_up, bn_color_dn, bn_long_up, bn_long_dn

Phase 2 (non implémenté ici) : dist_mq_put_0dte, dist_mq_call_0dte,
mq_gamma_condition pourraient enrichir les filtres options. À ajouter
quand validé empiriquement via backtest sur v4.

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
class BarSnap:
    bar_index: int
    price: float
    bar_high: float
    bar_low: float
    total_vol: float
    color_up: int
    color_dn: int
    long_up: int
    long_dn: int


class VReversalModel(PrimaryModel):
    """
    V-bottom / Λ-top Reversal.

    Stateful : buffer barres pour detecter capitulation + rebound.
    """

    name = "v_reversal"

    def __init__(
        self,
        buffer_size: int = 30,
        capitulation_bars: int = 10,        # Fenetre pour detecter chute
        capitulation_drop_pts: float = 15.0,  # Chute min en pts
        rebound_min_pts: float = 5.0,         # Rebond min depuis low
        rebound_max_bars: int = 10,          # Window pour detecter rebound apres low
        vol_spike_ratio: float = 1.5,        # Vol de bar rebound vs moyenne 20 bars
        require_footprint_confirm: bool = True,
        sl_buffer_ticks: int = 5,
        tp_retracement_pct: float = 0.5,    # TP = 50% du drop (Fib)
        tp_ticks_min: int = 20,
        tp_ticks_max: int = 120,
        dedup_bars: int = 30,
    ):
        self.buffer_size = int(buffer_size)
        self.capitulation_bars = int(capitulation_bars)
        self.capitulation_drop_pts = float(capitulation_drop_pts)
        self.rebound_min_pts = float(rebound_min_pts)
        self.rebound_max_bars = int(rebound_max_bars)
        self.vol_spike_ratio = float(vol_spike_ratio)
        self.require_footprint_confirm = bool(require_footprint_confirm)
        self.sl_buffer_ticks = int(sl_buffer_ticks)
        self.tp_retracement_pct = float(tp_retracement_pct)
        self.tp_ticks_min = int(tp_ticks_min)
        self.tp_ticks_max = int(tp_ticks_max)
        self.dedup_bars = int(dedup_bars)

        self.buffer: deque[BarSnap] = deque(maxlen=self.buffer_size)
        self.current_bar = 0
        self.last_signal_bar = -9999

    def required_features(self) -> list[str]:
        return [
            "price", "bar_high", "bar_low", "total_vol",
            "bn_color_up", "bn_color_dn", "bn_long_up", "bn_long_dn",
        ]

    def _update_buffer(self, row: pd.Series) -> None:
        price = _finite(row.get("price"))
        if price is None:
            return
        bh = _finite(row.get("bar_high")) or price
        bl = _finite(row.get("bar_low")) or price
        vol = _finite(row.get("total_vol")) or 0
        snap = BarSnap(
            bar_index=self.current_bar,
            price=price,
            bar_high=bh,
            bar_low=bl,
            total_vol=vol,
            color_up=int(_finite(row.get("bn_color_up")) or 0),
            color_dn=int(_finite(row.get("bn_color_dn")) or 0),
            long_up=int(_finite(row.get("bn_long_up")) or 0),
            long_dn=int(_finite(row.get("bn_long_dn")) or 0),
        )
        self.buffer.append(snap)

    def _detect_v_bottom(self) -> Optional[dict]:
        """Detecte pattern V-bottom dans buffer.

        Returns dict avec {low_bar, low_price, high_before, drop_pts, rebound_pts} ou None.
        """
        if len(self.buffer) < self.capitulation_bars + 3:
            return None

        # LOW et HIGH dans les last N bars
        recent = list(self.buffer)[-(self.capitulation_bars + 5):]
        low_snap = min(recent, key=lambda s: s.bar_low)
        # High AVANT le low (dans les bars avant low_snap)
        bars_before_low = [s for s in recent if s.bar_index < low_snap.bar_index]
        if not bars_before_low:
            return None
        high_snap = max(bars_before_low, key=lambda s: s.bar_high)

        drop_pts = high_snap.bar_high - low_snap.bar_low
        if drop_pts < self.capitulation_drop_pts:
            return None

        # Current bar = rebound attendu. Dist depuis low.
        current = self.buffer[-1]
        rebound_pts = current.price - low_snap.bar_low
        if rebound_pts < self.rebound_min_pts:
            return None

        # Low doit etre RECENT (dans rebound_max_bars)
        if current.bar_index - low_snap.bar_index > self.rebound_max_bars:
            return None

        return {
            "low_bar": low_snap.bar_index,
            "low_price": low_snap.bar_low,
            "high_before": high_snap.bar_high,
            "drop_pts": drop_pts,
            "rebound_pts": rebound_pts,
            "bars_since_low": current.bar_index - low_snap.bar_index,
        }

    def _detect_lambda_top(self) -> Optional[dict]:
        """Symmetrique V-bottom : detecte Λ-top (high violent + rejet)."""
        if len(self.buffer) < self.capitulation_bars + 3:
            return None

        recent = list(self.buffer)[-(self.capitulation_bars + 5):]
        high_snap = max(recent, key=lambda s: s.bar_high)
        bars_before_high = [s for s in recent if s.bar_index < high_snap.bar_index]
        if not bars_before_high:
            return None
        low_snap = min(bars_before_high, key=lambda s: s.bar_low)

        rise_pts = high_snap.bar_high - low_snap.bar_low
        if rise_pts < self.capitulation_drop_pts:
            return None

        current = self.buffer[-1]
        retrace_pts = high_snap.bar_high - current.price
        if retrace_pts < self.rebound_min_pts:
            return None

        if current.bar_index - high_snap.bar_index > self.rebound_max_bars:
            return None

        return {
            "high_bar": high_snap.bar_index,
            "high_price": high_snap.bar_high,
            "low_before": low_snap.bar_low,
            "rise_pts": rise_pts,
            "retrace_pts": retrace_pts,
            "bars_since_high": current.bar_index - high_snap.bar_index,
        }

    def _check_volume_spike(self) -> tuple[bool, float]:
        """Current bar vol >= vol_spike_ratio * moyenne 20 bars precedentes.

        FIX 21/04/2026 (code-reviewer) : si avg_vol=0 (transition Asia->London ou
        pause CME), REJETTE au lieu d'accepter. Evite faux positifs en bordure.
        """
        if len(self.buffer) < 21:
            return False, 0.0
        current = self.buffer[-1]
        prev_vols = [s.total_vol for s in list(self.buffer)[-21:-1]]
        avg_vol = sum(prev_vols) / max(len(prev_vols), 1)
        if avg_vol < 10:  # Seuil minimum vol pour reference fiable
            return False, 0.0  # Rejet safe en transition session
        ratio = current.total_vol / avg_vol
        return ratio >= self.vol_spike_ratio, ratio

    def _footprint_confirm(self, direction: str) -> bool:
        """Double confirm footprint sur current bar."""
        current = self.buffer[-1]
        if direction == "BUY":
            return current.color_up == 1 and current.long_up == 1
        else:
            return current.color_dn == 1 and current.long_dn == 1

    def generate_signal(self, row: pd.Series, context: Optional[dict] = None) -> Signal:
        self.current_bar += 1
        self._update_buffer(row)

        if self.current_bar - self.last_signal_bar < self.dedup_bars:
            return Signal(type=SignalType.HOLD, reason="dedup")

        if len(self.buffer) < self.capitulation_bars + 3:
            return Signal(type=SignalType.HOLD, reason="buffer_warmup")

        # V-bottom (BUY)
        v = self._detect_v_bottom()
        if v is not None:
            vol_ok, vol_ratio = self._check_volume_spike()
            if not vol_ok:
                return Signal(type=SignalType.HOLD,
                             reason=f"no_vol_spike_{vol_ratio:.1f}x")
            if self.require_footprint_confirm:
                if not self._footprint_confirm("BUY"):
                    return Signal(type=SignalType.HOLD, reason="no_footprint_BUY")

            # SL = low - buffer
            price = self.buffer[-1].price
            sl_price = v["low_price"] - self.sl_buffer_ticks * TICK_SIZE_NQ
            sl_ticks = int((price - sl_price) / TICK_SIZE_NQ)
            sl_ticks = max(10, min(40, sl_ticks))  # clamp

            # TP = 50% retracement du drop
            tp_ticks = int(v["drop_pts"] * self.tp_retracement_pct / TICK_SIZE_NQ)
            tp_ticks = max(self.tp_ticks_min, min(self.tp_ticks_max, tp_ticks))

            self.last_signal_bar = self.current_bar
            return Signal(
                type=SignalType.BUY,
                sl_ticks=sl_ticks,
                tp_ticks=tp_ticks,
                reason=f"v_bottom drop={v['drop_pts']:.1f} rebound={v['rebound_pts']:.1f} vol={vol_ratio:.1f}x",
                meta={
                    "pattern": "V_BOTTOM",
                    "drop_pts": v["drop_pts"],
                    "rebound_pts": v["rebound_pts"],
                    "vol_ratio": vol_ratio,
                    "low_price": v["low_price"],
                    "bars_since_low": v["bars_since_low"],
                },
            )

        # Λ-top (SELL)
        l = self._detect_lambda_top()
        if l is not None:
            vol_ok, vol_ratio = self._check_volume_spike()
            if not vol_ok:
                return Signal(type=SignalType.HOLD,
                             reason=f"no_vol_spike_{vol_ratio:.1f}x")
            if self.require_footprint_confirm:
                if not self._footprint_confirm("SELL"):
                    return Signal(type=SignalType.HOLD, reason="no_footprint_SELL")

            price = self.buffer[-1].price
            sl_price = l["high_price"] + self.sl_buffer_ticks * TICK_SIZE_NQ
            sl_ticks = int((sl_price - price) / TICK_SIZE_NQ)
            sl_ticks = max(10, min(40, sl_ticks))

            tp_ticks = int(l["rise_pts"] * self.tp_retracement_pct / TICK_SIZE_NQ)
            tp_ticks = max(self.tp_ticks_min, min(self.tp_ticks_max, tp_ticks))

            self.last_signal_bar = self.current_bar
            return Signal(
                type=SignalType.SELL,
                sl_ticks=sl_ticks,
                tp_ticks=tp_ticks,
                reason=f"lambda_top rise={l['rise_pts']:.1f} retrace={l['retrace_pts']:.1f} vol={vol_ratio:.1f}x",
                meta={
                    "pattern": "LAMBDA_TOP",
                    "rise_pts": l["rise_pts"],
                    "retrace_pts": l["retrace_pts"],
                    "vol_ratio": vol_ratio,
                    "high_price": l["high_price"],
                    "bars_since_high": l["bars_since_high"],
                },
            )

        return Signal(type=SignalType.HOLD, reason="no_pattern")
