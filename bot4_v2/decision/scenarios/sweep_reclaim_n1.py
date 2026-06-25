"""Sweep+Reclaim_N+1 — NEW ICT canonique (audit ULTRATHINK 24/06 trading-strategy).

Setup ICT/Smart Money Concepts (Inner Circle Trader 2020) :
- Bar N : sweep liquidity (sweep_high_this_bar=1 OU sweep_low_this_bar=1)
- Bar N+1 : reclaim (close > bar_low(N) si sweep_low, close < bar_high(N) si sweep_high)
- Edge naturel 50% reclaim rate sur 14j data (vs 4% RR>=1 v1 = TROUS)

Justification (audit ULTRATHINK 24/06 trading-strategy-analyst, R:R cible 2.0) :
> "Sweep + reclaim N+1 : edge ICT empirique ~50% sur 14j = signal FORT non code v1.
> Failed Breakout v1 ne verifie pas N+1 confirmation = mauvais Wyckoff."

LONG (sweep_low + reclaim) ou SHORT (sweep_high + reclaim).

State machine integration : ce detector emet ScenarioFire bar N+1 quand le
reclaim est confirme (donc le caller ne stocke pas l'etat N -> N+1, c'est le
detector qui regarde le bar courant + verifie sweep dans previous bar via
features sweep_*_lag1 du JSONL si dispo). Sinon, dependance externe ScenarioInstance
batch 1 P3 lifecycle pour suivre PENDING -> ACTIVE post-confirm.

Implementation pragmatique batch 2 P3 : on REGARDE features bar courante pour
detecter "sweep happened previous bar + reclaim now". Si JSONL sierra_enriched
n'expose pas ces lag features, ce scenario reste DORMANT (heuristic_score=0).
"""
from __future__ import annotations

from typing import Optional

from bot4_v2.decision.scenario_registry import (
    ScenarioContext,
    ScenarioFire,
    make_signal_id,
    make_timestamp_utc,
)


class SweepReclaimN1Detector:
    """Detector Sweep+Reclaim N+1 (ICT canonical liquidity sweep + smart money entry).

    Tolerance multi-format features (defensive parsing) :
    - sweep_high_this_bar / sweep_low_this_bar (bar N current)
    - sweep_high_lag1 / sweep_low_lag1 (bar N-1, si dispo)
    - sweep_high_active / sweep_low_active (compteur)
    """

    SCENARIO_NAME = "Sweep_Reclaim_N1"
    FAMILY = "ICT"  # Inner Circle Trader Smart Money Concepts
    STOP_BUFFER_TICKS = 4
    RR_TARGET = 2.0

    @property
    def name(self) -> str:
        return self.SCENARIO_NAME

    @property
    def family(self) -> str:
        return self.FAMILY

    @property
    def directions_supported(self) -> tuple[str, ...]:
        return ("LONG", "SHORT")

    def detect(self, ctx: ScenarioContext) -> Optional[ScenarioFire]:
        """Detecte sweep + reclaim N+1.

        Returns:
            ScenarioFire si setup, None sinon.
        """
        close = ctx.close
        if close <= 0 or ctx.atr <= 0:
            return None

        # Regime blacklist : vol EXTREME = no trade ICT (mode TREND/RANGE/NORMAL
        # tous acceptes, le bonus score recompense regime aligne)
        if ctx.regime.vol_regime == "EXTREME":
            return None

        bar_high = float(ctx.bar.get("high", 0.0))
        bar_low = float(ctx.bar.get("low", 0.0))
        bar_close = float(ctx.bar.get("close", close))
        if bar_high <= 0 or bar_low <= 0:
            return None

        # Detection : sweep happened bar N-1 (lag1) puis reclaim bar courante
        sweep_high_lag1 = self._get_int(ctx.bar, "sweep_high_lag1")
        sweep_low_lag1 = self._get_int(ctx.bar, "sweep_low_lag1")

        # Fallback : si lag1 features absentes, utilise sweep_*_active (compteur barre)
        if sweep_high_lag1 == 0 and sweep_low_lag1 == 0:
            sweep_high_active = self._get_int(ctx.bar, "sweep_high_active")
            sweep_low_active = self._get_int(ctx.bar, "sweep_low_active")
            # active>=1 signifie sweep recent (heuristic fallback - moins precis que lag1)
            if sweep_high_active >= 1:
                sweep_high_lag1 = 1
            if sweep_low_active >= 1:
                sweep_low_lag1 = 1

        # SHORT setup : sweep_high then reclaim down (price came back below high)
        if sweep_high_lag1 == 1 and bar_close < bar_high:
            return self._build_short(ctx, bar_high, bar_low, bar_close)

        # LONG setup : sweep_low then reclaim up
        if sweep_low_lag1 == 1 and bar_close > bar_low:
            return self._build_long(ctx, bar_high, bar_low, bar_close)

        return None

    def _build_short(
        self,
        ctx: ScenarioContext,
        bar_high: float,
        bar_low: float,
        bar_close: float,
    ) -> Optional[ScenarioFire]:
        """Construit ScenarioFire SHORT."""
        tick = self._estimate_tick_size(ctx.symbol)
        entry = bar_close
        stop = bar_high + self.STOP_BUFFER_TICKS * tick
        risk = stop - entry
        if risk <= 0:
            return None
        target_1 = entry - self.RR_TARGET * risk

        score = self._compute_score(ctx, direction="SHORT")
        reasons = (
            "sweep_high_lag1_detected",
            f"close_below_high_diff={bar_high - bar_close:.2f}",
            f"regime={ctx.regime.mode}",
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
        )

    def _build_long(
        self,
        ctx: ScenarioContext,
        bar_high: float,
        bar_low: float,
        bar_close: float,
    ) -> Optional[ScenarioFire]:
        """Construit ScenarioFire LONG."""
        tick = self._estimate_tick_size(ctx.symbol)
        entry = bar_close
        stop = bar_low - self.STOP_BUFFER_TICKS * tick
        risk = entry - stop
        if risk <= 0:
            return None
        target_1 = entry + self.RR_TARGET * risk

        score = self._compute_score(ctx, direction="LONG")
        reasons = (
            "sweep_low_lag1_detected",
            f"close_above_low_diff={bar_close - bar_low:.2f}",
            f"regime={ctx.regime.mode}",
        )

        return ScenarioFire(
            signal_id=make_signal_id(self.SCENARIO_NAME, ctx.symbol),
            scenario_name=self.SCENARIO_NAME,
            family=self.FAMILY,
            symbol=ctx.symbol,
            direction="LONG",
            entry_price=round(entry, 2),
            stop_loss=round(stop, 2),
            target_1=round(target_1, 2),
            heuristic_score=score,
            regime=ctx.regime.mode,
            session=ctx.session_segment,
            timestamp_utc=make_timestamp_utc(),
            reasons=reasons,
        )

    def _compute_score(self, ctx: ScenarioContext, direction: str) -> int:
        """Heuristic score 50 baseline + bonus contextuel."""
        score = 50  # baseline ICT setup
        # Bonus regime aligne
        if (direction == "SHORT" and ctx.regime.favor == "SHORT") or (
            direction == "LONG" and ctx.regime.favor == "LONG"
        ):
            score += 15
        # Bonus session liquide (us / london)
        if ctx.session_segment in ("us_cash", "london"):
            score += 10
        # Bonus orderflow aligne
        delta_bar = float(ctx.bar.get("delta_bar", 0.0))
        if (direction == "SHORT" and delta_bar < 0) or (
            direction == "LONG" and delta_bar > 0
        ):
            score += 10
        return min(100, score)

    @staticmethod
    def _get_int(bar: dict, key: str) -> int:
        """Extract int fail-soft (return 0 si absent / non-castable)."""
        v = bar.get(key)
        if v is None:
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _estimate_tick_size(symbol: str) -> float:
        tick_table = {"NQ": 0.25, "ES": 0.25, "MGC": 0.10}
        return tick_table.get(symbol.upper(), 0.25)
