"""Regime gate Bot BN V4 - pre-filter avant SignalEngine evaluation.

NOTE : la logique BN V4 (trend baissier + density + edge buy) est DEJA
implementee dans CORE.bn_v4_engine.check_zone via GATE_TREND_BLOCK /
GATE_LEVELS_BLOCK / GATE_DENSITY_BLOCK / GATE_EDGE_BLOCK. Ce gate REGIME
est un pre-filter SOFT qui :

  1. Bloque les bars manifestement non-tradables AVANT le cout du SignalEngine
     (mode degrade : VIX extreme, gamma_block_long, news lockout)
  2. Renvoie le contexte pour log JSONL

Le hard work des gates BN V4 reste dans bn_v4_engine (single source of truth).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from CORE.bot_bn_v4.config import BotBNV4Config


@dataclass(frozen=True)
class RegimeVerdict:
    """Verdict regime gate."""
    allowed: bool
    skip_reason: str = ""
    # Pour log JSONL : direction qui serait tradee (heuristic trend)
    proposed_direction: Optional[str] = None


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return f


class RegimeGate:
    """Filtre regime soft avant evaluation BN V4."""

    def __init__(self, cfg: BotBNV4Config):
        self.cfg = cfg

    def check_allow_entry(self, bar: dict, direction: str) -> RegimeVerdict:
        """Pre-filter regime.

        Returns :
            RegimeVerdict avec allowed/skip_reason/proposed_direction.
        """
        # 1. Gamma block (Bot 1 v2 racine du -$967 trade ignore)
        if direction == "long":
            gamma_block = bar.get("mq_gamma_block_long") or bar.get("gamma_block_long")
            if gamma_block:
                return RegimeVerdict(
                    allowed=False,
                    skip_reason="GAMMA_BLOCK_LONG",
                    proposed_direction=direction,
                )
        elif direction == "short":
            gamma_block = bar.get("mq_gamma_block_short") or bar.get("gamma_block_short")
            if gamma_block:
                return RegimeVerdict(
                    allowed=False,
                    skip_reason="GAMMA_BLOCK_SHORT",
                    proposed_direction=direction,
                )

        # 2. VIX extreme (regime ingerable)
        vix = _f(bar.get("vix_level")) or _f(bar.get("vix"))
        if vix is not None:
            if vix > 35.0:
                return RegimeVerdict(
                    allowed=False,
                    skip_reason=f"VIX_EXTREME:{vix:.1f}>35",
                    proposed_direction=direction,
                )
            if vix < 12.0:
                # VIX trop calme = pas d'edge BN V4 (trend baissier prealable
                # requis = volatilite minimale necessaire)
                return RegimeVerdict(
                    allowed=False,
                    skip_reason=f"VIX_CALM:{vix:.1f}<12",
                    proposed_direction=direction,
                )

        # 3. News lockout (delegue a la session gate idealement, mais
        # safety net si bar contient flag eco)
        if bar.get("is_eco_blocked"):
            return RegimeVerdict(
                allowed=False,
                skip_reason="ECO_BLOCKED",
                proposed_direction=direction,
            )
        if bar.get("is_news_5m"):
            return RegimeVerdict(
                allowed=False,
                skip_reason="NEWS_LOCKOUT_5MIN",
                proposed_direction=direction,
            )

        # 4. Heuristic trend pour log (informatif - ne BLOQUE pas)
        # bn_v4_engine.check_zone fait le vrai check trend_recent
        slope = _f(bar.get("vwap_slope_10"))
        proposed = direction
        if slope is not None:
            if slope < -self.cfg.TREND_SLOPE_THRESHOLD:
                proposed = "long"  # trend baissier prealable -> setup BN long
            elif slope > self.cfg.TREND_SLOPE_THRESHOLD:
                proposed = "short"

        return RegimeVerdict(
            allowed=True,
            proposed_direction=proposed,
        )
