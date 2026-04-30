"""RangeGate — skip trade en zone extreme de range (haut/bas).

Date : 2026-04-30 (Jackson "ON A ACHETE HAUT DE RANGE")
Bug observe : Bot 1 ES LONG @ 7198.50 → range_pos=100% (sommet VA),
ib_position_pct=81.6% (haut IB), inside_cur_va=0 (HORS VA = breakout
au-dessus). Aucun gate range awareness → trade pris malgre confluence
de 3 mesures "haut de range".

Approche **confluence 4 metriques** (cohesion avec Jackson "ratiser large"
CAS 4 v3) :

  1. VA   : range_pos (position dans Value Area, 0-100%)
  2. IB   : ib_position_pct (position dans Initial Balance, 0-1)
  3. DAY  : sess_position_pct calcule a partir de dist_sess_high/low
           ou dist_1d_max/min_ticks_pct (Bot 2 V4)
  4. MQ_1D: dist_1d_max_ticks proche 0 = pile au sommet MQ 1D officiel
           (niveau MenthorQ daily)

SKIP si CONFLUENCE >= 2/4 metriques en zone extreme :
  - LONG  → high_count >= 2 → SKIP "HIGH_OF_RANGE_CONFLUENCE"
  - SHORT → low_count  >= 2 → SKIP "LOW_OF_RANGE_CONFLUENCE"

Avantage confluence vs seuil unique :
- 1 metrique extreme seule = peut etre faux signal (VA etroite, IB
  cassee, etc.)
- 2/4 confirme structurellement haut/bas de range = vrai trap
- Permissif : laisse passer les trades pullback en milieu de range

Reversibilite : `cfg.range_gate_enabled` desactive (anti pattern 11 V1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


# ─── Seuils par defaut (paramétrables via cfg) ───────────────────────

DEFAULT_HIGH_THRESHOLD = {
    "range_pos_pct":     85.0,    # haut VA si >= 85%
    "ib_position_pct":   0.85,    # haut IB si >= 0.85
    "sess_position_pct": 0.85,    # haut session si >= 0.85
    "dist_1d_max_ticks": {        # niveau MQ 1D officiel (proche 0 = pile)
        "ES": 30.0,               # <= 30 ticks (~7.5 pts)
        "NQ": 100.0,              # <= 100 ticks (~25 pts)
    },
}
DEFAULT_LOW_THRESHOLD = {
    "range_pos_pct":     15.0,
    "ib_position_pct":   0.15,
    "sess_position_pct": 0.15,
    "dist_1d_min_ticks": {
        "ES": 30.0,
        "NQ": 100.0,
    },
}


@dataclass
class RangeGateResult:
    """Resultat du RangeGate avec breakdown observability.

    `skip` : True si en mode "skip" ET conditions remplies.
    `would_skip` : True si conditions remplies (peut etre logge meme en obs).
    """
    skip: bool = False                # mutation effective (skip trade)
    would_skip: bool = False          # conditions remplies (mode obs)
    skip_reason: str = ""
    direction: str = ""               # "BUY" / "SELL"
    high_count: int = 0
    low_count: int = 0
    metrics_high: list = None
    metrics_low: list = None
    mode: str = "skip"                # "skip" ou "observe"

    def __post_init__(self):
        if self.metrics_high is None:
            self.metrics_high = []
        if self.metrics_low is None:
            self.metrics_low = []


def _safe_get(bar: Any, key: str, default: Optional[float] = None) -> Optional[float]:
    """Lit une valeur depuis bar (dict ou pd.Series). Retourne default si
    absent / NaN / non-numerique."""
    try:
        if hasattr(bar, "get"):
            v = bar.get(key, default)
        elif key in bar:
            v = bar[key]
        else:
            return default
    except (KeyError, TypeError):
        return default
    if v is None:
        return default
    try:
        f = float(v)
    except (ValueError, TypeError):
        return default
    # NaN check
    if f != f:  # NaN != NaN
        return default
    return f


def _compute_sess_position_pct(bar: Any) -> Optional[float]:
    """Calcule position dans le range session a partir de
    dist_sess_high/low (Bot 1 DMP) OU dist_1d_max/min_ticks_pct (Bot 2 V4).

    Returns:
      0.0 = bas range, 1.0 = haut range, None = features absentes
    """
    # Methode 1 : dist_sess_high / dist_sess_low (Bot 1 DMP)
    sess_high = _safe_get(bar, "dist_sess_high")
    sess_low = _safe_get(bar, "dist_sess_low")
    if sess_high is not None and sess_low is not None:
        # sess_high > 0 (au-dessus prix), sess_low < 0 (en-dessous)
        total_range = sess_high - sess_low  # positif
        if total_range > 0:
            # position = abs(sess_low) / total_range
            return abs(sess_low) / total_range
    # Methode 2 : dist_1d_max_ticks_pct (Bot 2 V4 — pourcentage normalise)
    pct_to_max = _safe_get(bar, "dist_1d_max_ticks_pct")
    pct_to_min = _safe_get(bar, "dist_1d_min_ticks_pct")
    if pct_to_max is not None and pct_to_min is not None:
        # pct_to_max et pct_to_min sont des pourcentages signes du prix
        # On veut la position (0-1) entre min et max.
        # Simplification : si dist_1d_min_ticks_pct est negatif (prix au-dessus
        # du min) et dist_1d_max_ticks_pct est positif (prix sous max),
        # position = abs(pct_to_min) / (abs(pct_to_min) + pct_to_max)
        if pct_to_min < 0 and pct_to_max > 0:
            denom = abs(pct_to_min) + pct_to_max
            if denom > 0:
                return abs(pct_to_min) / denom
    return None


def evaluate_range_gate(
    bar: Any,
    direction: str,
    symbol: str,
    enabled: bool = True,
    min_confluence: int = 2,
    mode: str = "observe",
) -> RangeGateResult:
    """Evalue le RangeGate sur une bar.

    Args:
        bar: dict ou pd.Series contenant les features
        direction: "BUY" (LONG) ou "SELL" (SHORT)
        symbol: "ES" ou "NQ" (pour seuils dist_1d_max/min)
        enabled: cfg.range_gate_enabled (default True)
        min_confluence: nb min de metriques en zone pour skip (default 2)
        mode: "skip" = mutation effective (bloque trade)
              "observe" = log only (R2 code-reviewer 30/04)
              Default "observe" : backtest 30/04 montre 65% rejection + PnL
              bloque +$753. Calibrer 5j avant mode skip.

    Returns:
        RangeGateResult avec skip / would_skip + breakdown observability.
    """
    res = RangeGateResult(direction=direction, mode=mode)
    if not enabled:
        return res

    if direction not in ("BUY", "SELL"):
        return res

    # Lecture des metriques
    range_pos = _safe_get(bar, "range_pos")              # 0-100% (VA)
    ib_pos = _safe_get(bar, "ib_position_pct")           # 0-1 (IB)
    sess_pos = _compute_sess_position_pct(bar)           # 0-1 (DAY)
    dist_1d_max = _safe_get(bar, "dist_1d_max_ticks")    # ticks signe
    dist_1d_min = _safe_get(bar, "dist_1d_min_ticks")    # ticks signe

    # Seuils symbole
    sym_high = DEFAULT_HIGH_THRESHOLD["dist_1d_max_ticks"].get(symbol, 30.0)
    sym_low = DEFAULT_LOW_THRESHOLD["dist_1d_min_ticks"].get(symbol, 30.0)

    inside_va = _safe_get(bar, "inside_cur_va")          # 0 ou 1

    if direction == "BUY":
        # HAUT de range = mauvais pour LONG
        metrics = []
        # 1. VA : range_pos >= 85%
        if range_pos is not None and range_pos >= DEFAULT_HIGH_THRESHOLD["range_pos_pct"]:
            metrics.append(f"VA={range_pos:.0f}%")
        # 2. IB : ib_position_pct >= 0.85
        if ib_pos is not None and ib_pos >= DEFAULT_HIGH_THRESHOLD["ib_position_pct"]:
            metrics.append(f"IB={ib_pos:.2f}")
        # 3. DAY : sess_position >= 0.85
        if sess_pos is not None and sess_pos >= DEFAULT_HIGH_THRESHOLD["sess_position_pct"]:
            metrics.append(f"DAY={sess_pos:.2f}")
        # 4. MQ_1D : 0 < dist_1d_max_ticks <= sym_high (proche du sommet MQ)
        if dist_1d_max is not None and 0 < dist_1d_max <= sym_high:
            metrics.append(f"MQ_1D_MAX={dist_1d_max:.0f}t")

        res.metrics_high = metrics
        res.high_count = len(metrics)

        # CAS SPECIAL — Breakout VA au sommet (Jackson 30/04 Bot 1 ES LONG @ 7197.75) :
        # range_pos=100 (clampe au sommet VA) + inside_cur_va=0 (HORS VA)
        # FIX R2 code-reviewer 30/04 v3 : risque bloquer breakouts sains
        # → require AU MOINS 1 metric confluence supplementaire (pas binaire).
        if (inside_va == 0 and range_pos is not None and range_pos >= 99.0
                and res.high_count >= 1):
            res.would_skip = True
            res.skip_reason = (
                f"BREAKOUT_VA_HIGH (range_pos={range_pos:.0f}% + HORS_VA"
                + f" + {res.high_count} metric(s) confluence)"
            )
        elif res.high_count >= min_confluence:
            res.would_skip = True
            res.skip_reason = (
                f"HIGH_OF_RANGE_CONFLUENCE_{res.high_count}of4 "
                f"({'+'.join(metrics)})"
            )
        # Mode skip vs observe (R2 + S3 code-reviewer)
        if res.would_skip and mode == "skip":
            res.skip = True

    else:  # SELL
        metrics = []
        # 1. VA : range_pos <= 15%
        if range_pos is not None and range_pos <= DEFAULT_LOW_THRESHOLD["range_pos_pct"]:
            metrics.append(f"VA={range_pos:.0f}%")
        # 2. IB : ib_position_pct <= 0.15
        if ib_pos is not None and ib_pos <= DEFAULT_LOW_THRESHOLD["ib_position_pct"]:
            metrics.append(f"IB={ib_pos:.2f}")
        # 3. DAY : sess_position <= 0.15
        if sess_pos is not None and sess_pos <= DEFAULT_LOW_THRESHOLD["sess_position_pct"]:
            metrics.append(f"DAY={sess_pos:.2f}")
        # 4. MQ_1D : -sym_low <= dist_1d_min_ticks < 0 (proche plancher MQ)
        if dist_1d_min is not None and -sym_low <= dist_1d_min < 0:
            metrics.append(f"MQ_1D_MIN={dist_1d_min:.0f}t")

        res.metrics_low = metrics
        res.low_count = len(metrics)

        # CAS SPECIAL — Breakout VA au plancher : range_pos=0 + HORS VA + ≥1 confluence
        if (inside_va == 0 and range_pos is not None and range_pos <= 1.0
                and res.low_count >= 1):
            res.would_skip = True
            res.skip_reason = (
                f"BREAKOUT_VA_LOW (range_pos={range_pos:.0f}% + HORS_VA"
                + f" + {res.low_count} metric(s) confluence)"
            )
        elif res.low_count >= min_confluence:
            res.would_skip = True
            res.skip_reason = (
                f"LOW_OF_RANGE_CONFLUENCE_{res.low_count}of4 "
                f"({'+'.join(metrics)})"
            )
        if res.would_skip and mode == "skip":
            res.skip = True

    return res
