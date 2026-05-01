"""
QualityGate v3 — Filtre data-driven + 9 dimensions pro pour Bot 2 Databento V4.

Date : 2026-05-01 (mode crise + ULTRATHINK Jackson)

Philosophie : "Le trading paraît simple en respectant les règles" (Jackson 01/05).
- BUY proche swing LOW, SELL proche swing HIGH (zones d'intervention)
- Order flow direction (qui a la main)
- Pièges (trapped traders)
- Color UP / Edge zones
- Swing hit (Wyckoff Spring / SMC sweep)
- Divergences (delta, retest, SMT)
- Imbalances (delta, aggressor, volume)
- Clusters HVN (single prints, color clusters)
- Big orders (institutional footprint)

Validation empirique 42 trades Bot 2 (28-30/04 + 01/05) :
- delta_div_buy > 0 (BUY)        : WR 75% / +$227    (+57 dWR)
- big_buy_dominance > 0 (BUY)    : WR 25% / -$1,298  (+25 dWR)
- delta_pct aligned              : WR 30.8% / -$602  (+21.7 dWR)
- aggressor_imbalance aligned    : WR 29.6% / -$665  (+19.6 dWR)
- n_big_t1 > 0                   : WR 33.3% / -$196  (+13.3 dWR)

4 vetos data-driven (0% WR sur sample observé) :
- sig_aggressor_flip (en TREND)        : 6 trades / -$694
- sig_long_directional_bar (counter)   : 4 trades / -$254
- sig_cvd_divergence (en TREND)        : 2 trades / -$101
- delta_div_sell pour BUY              : 3 trades / -$272

Plus règles souveraines :
- Anti-FOMO : JAMAIS LONG en TREND_DOWN, JAMAIS SHORT en TREND_UP
- Anti haut/bas range : range_pos > 0.75 LONG / < 0.25 SHORT
- Hiérarchie sizing : PREMIUM (5 micros, $150 DD) / STRONG (3, $75) / WEAK (1, $25)

Reference : Wyckoff (Spring/Upthrust), SMC (liquidity grab), Linda Raschke,
Mark Douglas (edge statistique), V1 MIA-IA-SYSTEM-2026 (range_strategy hiérarchie).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple, Union


# ════════════════════════════════════════════════════════════════════
# CONSTANTES — calibrées sur 42 trades Bot 2
# ════════════════════════════════════════════════════════════════════

# Seuils order flow / imbalances
THR_DELTA_PCT = 0.05            # |delta_pct| > 5% = signal aligned
THR_AGGRESSOR = 0.0
THR_BIG_DOMINANCE = 0.55
THR_LARGE_TRADER = 0.55

# Anti haut/bas range (Jackson : "achète au haut" interdit)
THR_RANGE_POS_TOP = 0.75        # LONG interdit si range_pos > 0.75
THR_RANGE_POS_BOTTOM = 0.25     # SHORT interdit si range_pos < 0.25

# Score thresholds (max 13 points)
# 🆕 RECALIBRAGE 01/05 backtest dry-run sur 42 trades + market-analyst :
#   tier WEAK = 17 trades / 5.9% WR / -$1,446 = PIÈGE (laisse passer bruit)
#   tier STRONG = 13 trades / 46.2% WR / +$102 = sweet spot
#   tier PREMIUM = 1 trade / 0% WR = N=1 indefendable (market-analyst NOGO)
# Decision : tier UNIQUE STRONG (3 micros uniforme) jusqu'a N≥50 par tier confirme.
# WEAK + PREMIUM desactives (sizing=0). Re-evaluer a J+30 sur N≥100.
THR_PREMIUM = 999  # 🔴 DESACTIVE 01/05 : N=1 = pas de signal stat (market-analyst)
THR_STRONG = 6
THR_WEAK = 999     # 🔴 DESACTIVE 01/05 : 5.9% WR sample (backtest)

# Sizing par tier (n_micros) — uniforme STRONG seul actif
SIZING_BY_TIER = {
    "PREMIUM": 0,  # 🔴 DESACTIVE 01/05 (market-analyst : N=1 indefendable)
    "STRONG": 3,   # ← seul tier actif
    "WEAK": 0,     # 🔴 DESACTIVE 01/05 (backtest : 5.9% WR piège)
    "NO_TRADE": 0,
}

# Budget DD par tier ($)
DD_BUDGET_BY_TIER = {
    "PREMIUM": 0.0,
    "STRONG": 75.0,
    "WEAK": 0.0,
    "NO_TRADE": 0.0,
}


# ════════════════════════════════════════════════════════════════════
# RÉSULTAT
# ════════════════════════════════════════════════════════════════════

@dataclass
class QualityGateResult:
    """Résultat évaluation QualityGate v3."""
    allow: bool
    reason: str
    tier: str               # PREMIUM / STRONG / WEAK / NO_TRADE
    score: int              # 0-13
    score_max: int = 13
    sizing: int = 0         # n_micros recommandé
    dd_budget_usd: float = 0.0

    # Diagnostic
    veto_triggered: Optional[str] = None
    score_breakdown: Dict[str, int] = field(default_factory=dict)


# ════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════

def _fget(features: Dict, key: str, default=0):
    """Safe get avec coercion None/NaN/pd.NA → default.

    Databento V4 envoie parfois None ou NaN pour features derivees (ex: delta_pct
    quand bar incomplete). Comparaison NaN > threshold = False silencieux qui
    masque un setup valide. Fix code-reviewer 01/05 : check explicit isfinite.
    """
    v = features.get(key)
    if v is None:
        return default
    # NaN check (float) — pd.NA / np.nan
    if isinstance(v, float) and not math.isfinite(v):
        return default
    # pd.NA (pandas extension dtype) — duck-typing
    if hasattr(v, '__class__') and v.__class__.__name__ == 'NAType':
        return default
    return v


def _is_long(direction: str) -> bool:
    return direction in ("LONG", "BUY", 1, "long", "buy")


def _is_short(direction: str) -> bool:
    return direction in ("SHORT", "SELL", -1, "short", "sell")


def _aligned(value: float, direction: str, threshold: float = 0.0) -> bool:
    """value > threshold pour LONG, value < -threshold pour SHORT."""
    if _is_long(direction):
        return value > threshold
    if _is_short(direction):
        return value < -threshold
    return False


# ════════════════════════════════════════════════════════════════════
# VETOS DATA-DRIVEN (priorité absolue avant scoring)
# ════════════════════════════════════════════════════════════════════

def _check_vetos(features: Dict, direction: str, regime: Optional[str]) -> Optional[str]:
    """Retourne raison veto si trade doit être bloqué, sinon None."""

    # Veto 1 — sig_aggressor_flip en TREND (0% WR / -$694 sur 6 trades)
    if _fget(features, "sig_aggressor_flip") > 0:
        if regime in ("TREND_UP", "TREND_DOWN", "TREND"):
            return "veto_aggressor_flip_in_trend"

    # Veto 2 — sig_long_directional_bar counter-trend (0% WR / -$254)
    if _fget(features, "sig_long_directional_bar") > 0:
        if (_is_long(direction) and regime in ("TREND_DOWN",)) or \
           (_is_short(direction) and regime in ("TREND_UP",)):
            return "veto_long_directional_counter_trend"

    # Veto 3 — sig_cvd_divergence en TREND
    # 🔴 RETIRÉ 01/05 (market-analyst NOGO statistique) : N=2 = noise pur,
    #   pas de signal exploitable. Probabilite que 2 trades a 0% WR soient
    #   du hasard (true WR=40%) = 0.6^2 = 36%. Re-introduire seulement si
    #   pattern persiste sur N>=20.
    # if _fget(features, "sig_cvd_divergence") > 0:
    #     if regime in ("TREND_UP", "TREND_DOWN", "TREND"):
    #         return "veto_cvd_divergence_in_trend"

    # Veto 4 — delta_div_sell pour BUY
    # 🔴 RETIRE 01/05 (Jackson "PAS DE VETO DIVERGENCE, ELLE ARRIVE TRES PEU")
    # Statistique : N=3 trades 0% WR -$272 = sample insuffisant (cousin Veto 3
    # retire pour N=2 noise). Divergences = events rares, N<5 = noise pur.
    # Coherence avec Veto 5 (delta_div_buy pour SHORT) retire 01/05.
    # Re-introduction conditionnee a N>=20 trades avec WR<30% mesure.
    # if _is_long(direction) and _fget(features, "delta_div_sell") > 0:
    #     return "veto_delta_div_sell_for_buy_0pct_wr"

    # Veto 5 — delta_div_buy pour SHORT
    # 🔴 RETIRE 01/05 (Jackson "PAS DE VETO") : veto base sur "symetrie attendue
    # avec Veto 4 (delta_div_sell pour BUY)" mais JAMAIS valide empiriquement.
    # Audit historique 01/05 : 15 SHORTs Bot 2 sur 28-30/04+01/05 → 0 trade
    # observable avec delta_div_buy>0 (matching parent_id imparfait + sample
    # peut-etre nul). Veto bloquait 100% des SHORTs NQ aujourd'hui en regime
    # BEAR fort (cvd_ffd=-649) = trop strict sans evidence.
    # Re-introduction conditionnee a N>=20 SHORTs avec WR<30% mesure empirique.
    # if _is_short(direction) and _fget(features, "delta_div_buy") > 0:
    #     return "veto_delta_div_buy_for_short"

    # Veto 6 — Anti-FOMO (règle Jackson souveraine)
    ma_trend = features.get("ma_trend", "")
    momentum_5b = _fget(features, "momentum_5b")
    if _is_long(direction) and ma_trend == "DOWN" and momentum_5b < 0:
        return "anti_fomo_long_in_strong_downtrend"
    if _is_short(direction) and ma_trend == "UP" and momentum_5b > 0:
        return "anti_fomo_short_in_strong_uptrend"

    # Veto 7 — Anti haut/bas range (Jackson : "achète au haut")
    # 🆕 CONDITIONNÉ 01/05 (market-analyst) : en TREND_UP, le prix passe son
    # temps haut de range et continue → veto trop strict ferait rater les
    # meilleures continuations. Veto uniquement hors TREND aligné.
    range_pos = _fget(features, "range_pos", 0.5)
    if _is_long(direction) and range_pos > THR_RANGE_POS_TOP:
        # En TREND_UP : range_pos > 0.75 = continuation, pas piège → pas veto
        if regime != "TREND_UP":
            return f"buy_top_of_range_{range_pos:.2f}"
    if _is_short(direction) and range_pos < THR_RANGE_POS_BOTTOM:
        # En TREND_DOWN : range_pos < 0.25 = continuation → pas veto
        if regime != "TREND_DOWN":
            return f"sell_bottom_of_range_{range_pos:.2f}"

    return None  # pas de veto


# ════════════════════════════════════════════════════════════════════
# SCORING COMPOSITE (signaux empiriquement validés)
# ════════════════════════════════════════════════════════════════════

def _score_quality(features: Dict, direction: str) -> Tuple[int, Dict[str, int]]:
    """Calcule score 0-13 + breakdown détaillé.

    Pondération :
      - delta_div_aligned : 3 pts (signal A++ 75% WR validé)
      - big_dominance     : 2 pts (+25 dWR validé)
      - delta_pct         : 2 pts (+21.7 dWR validé)
      - aggressor_imbal   : 1 pt  (+19.6 dWR validé)
      - n_big_t1          : 1 pt  (+13.3 dWR validé)
      - sig_no_big_inverse: 1 pt
      - color_aligned     : 1 pt
      - edge_aligned      : 1 pt
      - aggressor_strong  : 1 pt  (bonus si > 0.30)
    """
    breakdown = {}

    # ── Q6 A++ delta divergence aligned (75% WR validé empiriquement) ──
    if _is_long(direction):
        if _fget(features, "delta_div_buy") > 0:
            breakdown["delta_div_aligned"] = 3
    elif _is_short(direction):
        if _fget(features, "delta_div_sell") > 0:
            breakdown["delta_div_aligned"] = 3

    # ── Q9 big_*_dominance aligned (+25 dWR validé) ──
    if _is_long(direction):
        big_dom = _fget(features, "big_buy_dominance")
    else:
        big_dom = _fget(features, "big_sell_dominance")
    if big_dom > THR_BIG_DOMINANCE:
        breakdown["big_dominance_aligned"] = 2

    # ── Q7 delta_pct aligned (+21.7 dWR validé) ──
    delta_pct = _fget(features, "delta_pct")
    if _aligned(delta_pct, direction, threshold=THR_DELTA_PCT):
        breakdown["delta_pct_aligned"] = 2

    # ── Q2 aggressor_imbalance aligned (+19.6 dWR validé) ──
    aggr = _fget(features, "aggressor_imbalance")
    if _aligned(aggr, direction, threshold=THR_AGGRESSOR):
        breakdown["aggressor_aligned"] = 1
        # Bonus si fortement aligné (> 0.30)
        if _aligned(aggr, direction, threshold=0.30):
            breakdown["aggressor_strong"] = 1

    # ── Q9 n_big_t1 > 0 (+13.3 dWR validé) ──
    if _fget(features, "n_big_t1") > 0:
        breakdown["n_big_t1_present"] = 1

    # ── Q9 sig_no_big_inverse (pas d'inversion big) ──
    if _fget(features, "sig_no_big_inverse") > 0:
        breakdown["sig_no_big_inverse"] = 1

    # ── Q4 Color zones aligned ──
    if _is_long(direction):
        if _fget(features, "bn_color_up") >= 1:
            breakdown["color_aligned"] = 1
        if _fget(features, "bar_edge_buy") > 0 or _fget(features, "fp_edge_buy") > 0:
            breakdown["edge_aligned"] = 1
    elif _is_short(direction):
        if _fget(features, "bn_color_dn") >= 1:
            breakdown["color_aligned"] = 1
        if _fget(features, "bar_edge_sell") > 0 or _fget(features, "fp_edge_sell") > 0:
            breakdown["edge_aligned"] = 1

    score = sum(breakdown.values())
    return score, breakdown


# ════════════════════════════════════════════════════════════════════
# API PUBLIQUE
# ════════════════════════════════════════════════════════════════════

def quality_gate(
    features: Dict,
    direction: str,
    regime: Optional[str] = None,
) -> QualityGateResult:
    """API principale QualityGate v3.

    Args:
        features: dict de features Databento V4 (features_at_entry).
        direction: "LONG"/"BUY" ou "SHORT"/"SELL".
        regime: "TREND_UP", "TREND_DOWN", "RANGE", "UNKNOWN" (optionnel).

    Returns:
        QualityGateResult avec allow, tier, score, sizing, dd_budget.

    Raises:
        ValueError: direction non reconnue (fail loud cf rule data-quality).

    Logique :
      1. Vetos absolus (sig_aggressor_flip en trend, etc.) → NO_TRADE
      2. Anti-FOMO (counter-trend) → NO_TRADE
      3. Anti haut/bas range (sauf si trend aligne) → NO_TRADE
      4. Score composite 0-13 sur signaux empiriquement validés
      5. Tier UNIQUE STRONG ≥6 (PREMIUM/WEAK desactives 01/05)
    """
    # 🆕 Fail loud direction inconnue (code-reviewer 01/05)
    if not (_is_long(direction) or _is_short(direction)):
        raise ValueError(
            f"quality_gate v3 : direction inconnue '{direction}'. "
            f"Attendu : 'LONG'/'BUY'/'long'/'buy'/1 ou 'SHORT'/'SELL'/'short'/'sell'/-1."
        )

    # Étape 1-3 : vetos absolus
    veto = _check_vetos(features, direction, regime)
    if veto:
        return QualityGateResult(
            allow=False,
            reason=veto,
            tier="NO_TRADE",
            score=0,
            sizing=0,
            dd_budget_usd=0.0,
            veto_triggered=veto,
            score_breakdown={},
        )

    # Étape 4 : score composite
    score, breakdown = _score_quality(features, direction)

    # Étape 5 : hiérarchie (WEAK desactive 01/05 — 5.9% WR sample)
    if score >= THR_PREMIUM:
        tier = "PREMIUM"
    elif score >= THR_STRONG:
        tier = "STRONG"
    else:
        tier = "NO_TRADE"  # WEAK supprime, score <6 = NO_TRADE

    allow = tier != "NO_TRADE"
    sizing = SIZING_BY_TIER[tier]
    dd_budget = DD_BUDGET_BY_TIER[tier]
    reason = f"{tier} (score {score}/13)" if allow else f"insufficient_score_{score}"

    return QualityGateResult(
        allow=allow,
        reason=reason,
        tier=tier,
        score=score,
        sizing=sizing,
        dd_budget_usd=dd_budget,
        score_breakdown=breakdown,
    )


# ════════════════════════════════════════════════════════════════════
# UTILITAIRES (debug + integration)
# ════════════════════════════════════════════════════════════════════

def explain(result: QualityGateResult) -> str:
    """Format human-readable du résultat pour logs."""
    lines = [
        f"QualityGate v3 → {result.tier} (allow={result.allow})",
        f"  Reason : {result.reason}",
        f"  Score  : {result.score}/{result.score_max}",
        f"  Sizing : {result.sizing} micros / DD ${result.dd_budget_usd:.0f}",
    ]
    if result.veto_triggered:
        lines.append(f"  VETO   : {result.veto_triggered}")
    if result.score_breakdown:
        lines.append(f"  Detail : {result.score_breakdown}")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# LOGGER JSONL DEDIE (BLOCKER code-reviewer 01/05)
# ════════════════════════════════════════════════════════════════════
# Sans ce log, validation N=100 impossible → repartirait en data mining.
# Chaque appel quality_gate stocke : ts, signal_id, tier, score, breakdown,
# veto, executed (si trade pris), pnl_usd (si exit). Append-only.

_DEFAULT_LOG_DIR = Path("D:/TRADING_SIERRA_CHART_AUTO/LOGS/quality_gate")


def log_decision(
    result: QualityGateResult,
    *,
    signal_id: Optional[str] = None,
    symbol: Optional[str] = None,
    direction: Optional[str] = None,
    regime: Optional[str] = None,
    bar_ts: Optional[str] = None,
    executed: Optional[bool] = None,
    pnl_usd: Optional[float] = None,
    log_dir: Optional[Path] = None,
) -> None:
    """Log la decision QualityGate dans LOGS/quality_gate/qg_v3_YYYYMMDD.jsonl.

    Append-only. Si executed=False (NO_TRADE / veto), pnl=None. Si executed=True,
    pnl_usd renseigne au trade close (call separe avec meme signal_id).

    Critique : sans ce log, validation N=100 (Lopez DSR) impossible.
    """
    log_dir = log_dir or _DEFAULT_LOG_DIR
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_file = log_dir / f"qg_v3_{date_str}.jsonl"

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "signal_id": signal_id,
            "symbol": symbol,
            "direction": direction,
            "regime": regime,
            "bar_ts": bar_ts,
            "tier": result.tier,
            "score": result.score,
            "score_max": result.score_max,
            "score_breakdown": result.score_breakdown,
            "veto_triggered": result.veto_triggered,
            "allow": result.allow,
            "sizing": result.sizing,
            "dd_budget_usd": result.dd_budget_usd,
            "executed": executed,
            "pnl_usd": pnl_usd,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        # Log fail ne doit JAMAIS bloquer le trading. Print silent fallback.
        print(f"[QualityGate v3] log_decision fail (non-bloquant): {exc}")


__all__ = [
    "quality_gate",
    "QualityGateResult",
    "explain",
    "log_decision",
    "SIZING_BY_TIER",
    "DD_BUDGET_BY_TIER",
    "THR_PREMIUM",
    "THR_STRONG",
    "THR_WEAK",
]
