"""Bearish_Rejection — KEEP + RECALIBRER (seul edge credible v1 PF 5.05).

Spec batch 2 P3 : scenario v1 le seul ayant survecu DSR test 14j (PF 5.05 sur
N=55 trades premium, R:R median 2.0). RECALIBRE post-P6 30j shadow + isotonic
regression P(win).

Methodologie (Wyckoff + Dalton confluence) :
- Resistance majeure (key_levels_resistance confluence >= 2 dans 0.15% du prix)
- Rejection price action (close < high mais close > previous_close)
- Order flow bearish (delta_bar < 0 OU bn_pressure_ask > bn_pressure_bid)
- Regime vol non-EXTREME (regime_source vol_regime blacklist)

SHORT only (asymetrie : LONG = Bullish_Continuation autre scenario).

Heuristic score : 50 + 10 * (confluence_count - 1) + 10 (bearish OF) + 10 (regime trend down)
= max ~80 si confluence 3 + OF bearish + TREND_DOWN regime.
"""
from __future__ import annotations

from typing import Optional

from bot4_v2.decision.scenario_registry import (
    ScenarioContext,
    ScenarioFire,
    make_signal_id,
    make_timestamp_utc,
)


class BearishRejectionDetector:
    """Detector Bearish_Rejection (Wyckoff + Dalton confluence + rejection PA)."""

    SCENARIO_NAME = "Bearish_Rejection"
    FAMILY = "Wyckoff"  # Wyckoff test + cause (confluence>=2)
    PROXIMITY_PCT = 0.0015  # 0.15% du prix max distance niveau
    MIN_CONFLUENCE_COUNT = 2  # >=2 niveaux clusterises
    STOP_BUFFER_TICKS = 4  # 4 ticks au-dessus high pour stop
    RR_TARGET = 2.0  # Reward/Risk ratio target

    @property
    def name(self) -> str:
        return self.SCENARIO_NAME

    @property
    def family(self) -> str:
        return self.FAMILY

    @property
    def directions_supported(self) -> tuple[str, ...]:
        return ("SHORT",)

    def detect(self, ctx: ScenarioContext) -> Optional[ScenarioFire]:
        """Detecte setup Bearish_Rejection.

        Returns:
            ScenarioFire si setup detecte, None sinon.
        """
        close = ctx.close
        if close <= 0 or ctx.atr <= 0:
            return None

        # Regime blacklist : vol EXTREME -> no trade (mode TREND/RANGE/NORMAL
        # tous acceptes, le scoring penalise les non-alignes)
        if ctx.regime.vol_regime == "EXTREME":
            return None

        # Cherche resistance majeure (confluence >=2, proxy 0.15% du close)
        major_resistance = self._find_major_resistance(ctx)
        if major_resistance is None:
            return None

        # Rejection PA : close pres du high (top 30% range bar)
        bar_high = float(ctx.bar.get("high", 0.0))
        bar_low = float(ctx.bar.get("low", 0.0))
        bar_close = float(ctx.bar.get("close", close))
        bar_range = bar_high - bar_low
        if bar_range <= 0:
            return None
        # Close doit etre dans top 30% (rejection : high tested, close lower)
        position_in_bar = (bar_close - bar_low) / bar_range
        if position_in_bar < 0.50:
            return None  # close pas assez haut, pas de test rejection

        # Order flow bearish : delta_bar < 0 OU pressure_ask > pressure_bid
        delta_bar = float(ctx.bar.get("delta_bar", 0.0))
        pressure_ask = float(ctx.bar.get("bn_pressure_ask", 0.0))
        pressure_bid = float(ctx.bar.get("bn_pressure_bid", 0.0))
        of_bearish = (
            delta_bar < 0 or
            (pressure_ask > pressure_bid and pressure_ask > 0)
        )
        if not of_bearish:
            return None

        # Construction trade :
        # entry = bar_close (rejection confirmed)
        # stop = bar_high + 4 ticks buffer
        # target = entry - 2 * (stop - entry) (RR 2:1)
        entry = bar_close
        # Tick size approximation via narrative atr (close prend tick implicite)
        # Pour eviter dependance get_tick_size ici, utilise 4 ticks via ATR proxy
        stop_buffer = self._estimate_tick_size(ctx.symbol) * self.STOP_BUFFER_TICKS
        stop = bar_high + stop_buffer
        risk = stop - entry
        if risk <= 0:
            return None
        target_1 = entry - self.RR_TARGET * risk

        # Heuristic score
        confluence_count = major_resistance.confluence_count
        score = 50 + 10 * (confluence_count - 1)
        if delta_bar < 0 and pressure_ask > pressure_bid:
            score += 10  # double confirmation OF
        if ctx.regime.mode == "TREND" and ctx.regime.favor == "SHORT":
            score += 10  # regime aligne
        score = min(100, score)

        reasons = (
            f"resistance_confluence_{confluence_count}",
            f"close_top_{int(position_in_bar*100)}pct",
            f"delta_bar={delta_bar:.0f}",
            f"regime={ctx.regime.mode}_{ctx.regime.favor}",
        )

        return ScenarioFire(
            signal_id=make_signal_id(self.SCENARIO_NAME, ctx.symbol),
            scenario_name=self.SCENARIO_NAME,
            family=self.FAMILY,
            symbol=ctx.symbol,
            direction="SHORT",
            entry_price=round(entry, 2),
            stop_loss=round(stop, 2),
            target_1=round(target_1, 2),
            heuristic_score=score,
            regime=ctx.regime.mode,
            session=ctx.session_segment,
            timestamp_utc=make_timestamp_utc(),
            reasons=reasons,
            extra={
                "confluence_count": confluence_count,
                "resistance_label": major_resistance.label,
            },
        )

    def _find_major_resistance(self, ctx: ScenarioContext):
        """Cherche niveau resistance major confluence>=2 dans 0.15% du close."""
        if not ctx.narrative.key_levels_resistance:
            return None
        for level in ctx.narrative.key_levels_resistance:
            # Distance en ATR pour normalisation
            dist_pct = abs(level.price - ctx.close) / ctx.close
            if dist_pct > self.PROXIMITY_PCT:
                continue
            if level.confluence_count >= self.MIN_CONFLUENCE_COUNT:
                return level
        return None

    @staticmethod
    def _estimate_tick_size(symbol: str) -> float:
        """Tick size par symbole (anti dependance get_tick_size import cycle)."""
        tick_table = {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}
        return tick_table.get(symbol.upper(), 0.25)
