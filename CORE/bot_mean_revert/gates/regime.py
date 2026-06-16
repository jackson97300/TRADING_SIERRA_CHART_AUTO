"""Regime gate Bot MR - filtre asymetrique ES (trend_align) / NQ (contrarian).

Sweep v2 valide :
  - ES : trend_align_es (LONG si slope>0, SHORT si slope<0 + VIX>20)
  - NQ : contrarian_nq (LONG si slope<0, SHORT si slope>0 + trend_day<0.65)

Le gate est une couche redondante avec SignalEngine._apply_regime_filter
mais expose une interface standalone pour tests + audit + future composition
(ex: ajouter d'autres filtres regime sans toucher SignalEngine).
"""
from __future__ import annotations

from dataclasses import dataclass

from CORE.bot_mean_revert.config import BotMRConfig


@dataclass(frozen=True)
class RegimeVerdict:
    """Verdict du filtre regime."""
    allowed: bool
    reason: str = ""
    mode: str = ""


class RegimeGate:
    """Gate regime asymetrique par symbole."""

    def __init__(self, cfg: BotMRConfig):
        self.cfg = cfg

    def check(
        self,
        symbol: str,
        direction: str,
        *,
        slope_30: float,
        vix: float = 0.0,
        trend_day_score: float = 0.0,
    ) -> RegimeVerdict:
        """Verifie si le regime autorise la direction pour ce symbole.

        Args:
            symbol : "ES" / "NQ" / "MGC"
            direction : "LONG" / "SHORT"
            slope_30 : vwap_slope_30 (positif = trend up)
            vix : niveau VIX (ES SHORT necessite >20)
            trend_day_score : ctx_trend_day_score (NQ SHORT necessite <0.65)

        Returns:
            RegimeVerdict(allowed, reason, mode)
        """
        mode = self.cfg.regime_filter_mode(symbol)
        if mode == "off":
            return RegimeVerdict(allowed=True, mode=mode)

        if mode == "trend_align_es":
            if direction == "LONG":
                if slope_30 <= 0:
                    return RegimeVerdict(
                        allowed=False,
                        reason=f"TREND_ALIGN_LONG_SLOPE_NEG:{slope_30:.4f}",
                        mode=mode,
                    )
            elif direction == "SHORT":
                if slope_30 >= 0:
                    return RegimeVerdict(
                        allowed=False,
                        reason=f"TREND_ALIGN_SHORT_SLOPE_POS:{slope_30:.4f}",
                        mode=mode,
                    )
                if self.cfg.VIX_MIN_FOR_SHORT > 0 and vix <= self.cfg.VIX_MIN_FOR_SHORT:
                    return RegimeVerdict(
                        allowed=False,
                        reason=f"VIX_TOO_LOW_FOR_SHORT:{vix:.2f}<={self.cfg.VIX_MIN_FOR_SHORT:.2f}",
                        mode=mode,
                    )
            return RegimeVerdict(allowed=True, mode=mode)

        if mode == "contrarian_nq":
            if direction == "LONG":
                if slope_30 >= 0:
                    return RegimeVerdict(
                        allowed=False,
                        reason=f"CONTRA_LONG_SLOPE_POS:{slope_30:.4f}",
                        mode=mode,
                    )
            elif direction == "SHORT":
                if slope_30 <= 0:
                    return RegimeVerdict(
                        allowed=False,
                        reason=f"CONTRA_SHORT_SLOPE_NEG:{slope_30:.4f}",
                        mode=mode,
                    )
                if trend_day_score > self.cfg.NQ_TREND_DAY_MAX:
                    return RegimeVerdict(
                        allowed=False,
                        reason=f"NQ_TREND_DAY_TOO_HIGH:{trend_day_score:.2f}>{self.cfg.NQ_TREND_DAY_MAX:.2f}",
                        mode=mode,
                    )
            return RegimeVerdict(allowed=True, mode=mode)

        # Mode inconnu : ne bloque pas (fail open)
        return RegimeVerdict(allowed=True, mode=mode)
