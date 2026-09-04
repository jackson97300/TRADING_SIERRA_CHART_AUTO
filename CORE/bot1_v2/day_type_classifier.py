"""Day-Type Classifier Bot 1 v2 (Phase 2 audit ULTRATHINK 19/06).

Distingue regime de marche pour adapter la cascade Bot 1 v2 :
  - BALANCE : prix oscille autour des niveaux → strategie current (CORE near_level)
  - TREND_UP : trend day haussier → mode continuation (relax near_level, bypass pullback)
  - TREND_DOWN : trend day baissier → mode continuation
  - CHOP : chop intraday post-volatilite → strict (comme balance)
  - UNKNOWN : warmup ou features manquantes → strict fail-safe

Pourquoi pas day_type Sierra natif ?
  Empirique 19/06 : day_type = constant 2 (NormVar) sur 990/990 bars NQ. Sierra
  DMP OpenType n'est pas fiable intra-day. On combine plusieurs signaux derives :
    - slope_30 (rolling VWAP slope) - le plus discriminant
    - ctx_trend_day_score (10 distinct values sur live 19/06)
    - trend_day_probability Sierra (binaire 0/0.45)
    - range vs ATR (largeur jour)

Seuils env-configurables via BOT1V2_DAYTYPE_*.

Sources methodologiques :
  - Dalton "Mind over Markets" : trend day = "find direction in morning, stick"
  - Wyckoff : phase markup/markdown vs accumulation/distribution
  - Empirique 19/06 J+1 post-FOMC : slope_30=-0.43 toute la journee = trend day strong
    mais Sierra day_type=NormVar -> on doit detecter via slope.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    from CORE.bot1_v2.config import Bot1V2Config
except ImportError:  # type: ignore[unreachable]
    from bot1_v2.config import Bot1V2Config  # type: ignore[no-redef]


@dataclass(frozen=True)
class DayTypeVerdict:
    """Verdict day-type classifier."""
    regime: str  # BALANCE / TREND_UP / TREND_DOWN / CHOP / UNKNOWN
    slope_30: float  # raw signal
    ctx_trend_day_score: float
    trend_day_probability: float
    confidence: float  # 0.0-1.0
    reason: str  # diagnostic


def _env_float(name: str, default: float) -> float:
    """Read env var with BOT1V2_ prefix, fallback default."""
    val = os.environ.get(f"BOT1V2_{name}")
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _as_float(x, default: float = 0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def classify_day_type(bar: dict, cfg: Optional[Bot1V2Config] = None) -> DayTypeVerdict:
    """Classifie le regime du jour a partir de signaux derives.

    Args:
        bar : sierra_enriched dict (besoin slope_30, ctx_trend_day_score, etc.)
        cfg : Bot1V2Config (utilise getattr defensif pour seuils)

    Returns:
        DayTypeVerdict avec regime + confiance
    """
    # Seuils env-configurables (defaults Dalton classiques)
    slope_strong = _env_float("DAYTYPE_SLOPE_STRONG", 0.30)  # >0.30 = trend strong
    slope_balance = _env_float("DAYTYPE_SLOPE_BALANCE", 0.10)  # <0.10 = balance
    ctx_trend_min = _env_float("DAYTYPE_CTX_TREND_MIN", 0.50)  # ctx_trend_day_score
    prob_trend_min = _env_float("DAYTYPE_PROB_TREND_MIN", 0.40)  # trend_day_probability

    slope_30 = _as_float(bar.get("vwap_slope_30") or bar.get("slope_30"))
    ctx_trend = _as_float(bar.get("ctx_trend_day_score"))
    prob_trend = _as_float(bar.get("trend_day_probability"))
    ma_trend = _as_float(bar.get("ma_trend"))

    # Garde-fou : si aucun signal disponible -> UNKNOWN
    if slope_30 == 0.0 and ctx_trend == 0.0 and prob_trend == 0.0:
        return DayTypeVerdict(
            regime="UNKNOWN",
            slope_30=slope_30, ctx_trend_day_score=ctx_trend,
            trend_day_probability=prob_trend,
            confidence=0.0,
            reason="all_signals_zero_warmup",
        )

    # 1. TREND fort base sur slope_30 (signal primaire le plus fiable)
    abs_slope = abs(slope_30)
    if abs_slope >= slope_strong:
        # Confluence avec ctx_trend_day_score / trend_day_probability ?
        confluence = 0
        if ctx_trend >= ctx_trend_min:
            confluence += 1
        if prob_trend >= prob_trend_min:
            confluence += 1
        if ma_trend != 0 and (ma_trend > 0) == (slope_30 > 0):
            confluence += 1
        confidence = 0.5 + 0.15 * confluence  # 0.5-0.95

        regime = "TREND_UP" if slope_30 > 0 else "TREND_DOWN"
        return DayTypeVerdict(
            regime=regime, slope_30=slope_30,
            ctx_trend_day_score=ctx_trend, trend_day_probability=prob_trend,
            confidence=confidence,
            reason=f"slope_strong({slope_30:.2f}>={slope_strong}) confluence={confluence}/3",
        )

    # 2. BALANCE : slope faible + ctx_trend_day_score bas
    if abs_slope <= slope_balance and ctx_trend < ctx_trend_min:
        return DayTypeVerdict(
            regime="BALANCE", slope_30=slope_30,
            ctx_trend_day_score=ctx_trend, trend_day_probability=prob_trend,
            confidence=0.7,
            reason=f"slope_weak({abs_slope:.2f}<={slope_balance}) ctx_low({ctx_trend:.2f})",
        )

    # 3. CHOP : slope mixte ou ctx_trend hint mais pas confirme
    return DayTypeVerdict(
        regime="CHOP", slope_30=slope_30,
        ctx_trend_day_score=ctx_trend, trend_day_probability=prob_trend,
        confidence=0.5,
        reason=f"slope_mid({slope_30:.2f}) ctx={ctx_trend:.2f}",
    )


def is_trend_day(verdict: DayTypeVerdict) -> bool:
    """Helper : True si regime trend (UP ou DOWN)."""
    return verdict.regime in ("TREND_UP", "TREND_DOWN")


def is_balance_day(verdict: DayTypeVerdict) -> bool:
    """Helper : True si regime balance."""
    return verdict.regime == "BALANCE"


def near_level_max_ticks_for_regime(
    base_max_ticks: int, verdict: DayTypeVerdict, cfg: Optional[Bot1V2Config] = None,
) -> int:
    """Adapte NEAR_LEVEL_MAX_TICKS au regime.

    BALANCE → seuil strict actuel (16t NQ)
    TREND_UP/DOWN → seuil relax (multiplier env-configurable, default 4x)
    CHOP/UNKNOWN → seuil strict (fail-safe)
    """
    if not is_trend_day(verdict):
        return base_max_ticks
    multiplier = _env_float("DAYTYPE_TREND_NEAR_LEVEL_MULT", 4.0)
    return int(base_max_ticks * multiplier)


def should_bypass_pullback(verdict: DayTypeVerdict) -> bool:
    """Helper : True si on doit waiver le check pullback en trend day.

    En trend day strong, le prix ne fait pas de pullback significatif (continuation
    pure). Le filtre pullback contradict la philosophie with-trend.

    FIX B2 review code-reviewer 19/06 : seuil aligne avec bypass_near_level
    via env var BOT1V2_DAYTYPE_BYPASS_CONF_MIN (default 0.65).
    Avant : 0.7 (different de 0.65 bypass near). Incoherent.
    """
    conf_min = _env_float("DAYTYPE_BYPASS_CONF_MIN", 0.65)
    return is_trend_day(verdict) and verdict.confidence >= conf_min
