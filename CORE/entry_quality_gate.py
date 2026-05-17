"""EntryQualityGate — skip trade si order flow contre l'entree.

Date : 2026-04-30 soir LOT 2B (Jackson "ON APPLIQUE PAPER DIRECT")

Findings empiriques market-analyst (n=50 Bot 1, 24+29/04) :

Discriminance #1 — `momentum_5b` aligne :
  PRO_MOMENTUM (mom * dir > 0, n=15) : WR 47%
  CONTRA       (mom * dir < 0, n=10) : WR 0%

Discriminance #2 — `cvd_bar_delta` aligne :
  PRO_CVD      (cvd * dir > 0, n=27) : WR 41%
  CONTRA       (cvd * dir < 0, n=23) : WR 4% (1 TP / 13 SL) <-- CATASTROPHE

Discriminance #3 — `next_wall_dist_ticks` realiste :
  IDEAL (40-100t, n=9 + PRO_BOTH) : WR 67% (6 TP / 9, 0 SL)
  TROP_PROCHE (<30t)              : WR 33% (mur trop pres = TP impossible)
  TROP_LOIN (>100t)               : WR 20% (mur trop loin = signal sans cible)

Combo BOTH_PRO (momentum + CVD aligne) sur n=20 → WR 50%.
BOTH_CONTRA (n=17) → WR 0%, 12 SL, 0 TP (filtre golden).

Logique : SKIP si AU MOINS 1 des 3 conditions adverses :
  1. momentum_5b * direction_sign < 0 (contre-momentum strict)
  2. cvd_bar_delta * direction_sign < 0 (order flow contre)
  3. next_wall_dist_ticks < 30 OU > 100 (TP non realiste)

Graceful degradation : si feature manque (Bot 2 V4 manque cvd/wall_dist),
ne pas compter cette condition. Bot 1 = 3 conditions, Bot 2 = 1 (momentum).

Garde-fous Lopez (incident DATA_MINING_TRAP 28/04) :
- n=50 sur 2 jours = INSUFFISANT pour validation Lopez stricte
- Validation empirique paper Sim (Jackson directive "ON APPLIQUE PAPER DIRECT")
- Reversibilite via flag (anti pattern 11 V1)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


# ─── Seuils (paramétrables) ─────────────────────────────────────────

DEFAULT_WALL_DIST_MIN = 30.0     # ticks : <30 = mur trop proche, TP impossible
DEFAULT_WALL_DIST_MAX = 100.0    # ticks : >100 = mur trop loin, signal sans cible


@dataclass
class EntryQualityGateResult:
    skip: bool = False
    skip_reason: str = ""
    momentum_5b: Optional[float] = None
    cvd_bar_delta: Optional[float] = None
    next_wall_dist_ticks: Optional[float] = None
    direction_sign: int = 0          # +1 LONG, -1 SHORT
    contra_momentum: bool = False
    contra_cvd: bool = False
    wall_too_close: bool = False
    wall_too_far: bool = False


def _safe_float(bar: Any, key: str) -> Optional[float]:
    try:
        if hasattr(bar, "get"):
            v = bar.get(key)
        elif key in bar:
            v = bar[key]
        else:
            return None
    except (KeyError, TypeError):
        return None
    if v is None:
        return None
    try:
        f = float(v)
    except (ValueError, TypeError):
        return None
    if f != f:  # NaN
        return None
    return f


def evaluate_entry_quality_gate(
    bar: Any,
    direction: str,
    enabled: bool = True,
    wall_dist_min: float = DEFAULT_WALL_DIST_MIN,
    wall_dist_max: float = DEFAULT_WALL_DIST_MAX,
    strict_mode: bool = False,
) -> EntryQualityGateResult:
    """Evalue EntryQualityGate.

    Args:
        bar: dict ou pd.Series avec features DMP
        direction: "BUY"/"LONG" (+1) ou "SELL"/"SHORT" (-1)
        enabled: cfg.entry_quality_gate_enabled
        wall_dist_min/max: seuils ticks (default 30-100)
        strict_mode: True = skip si AU MOINS 1 condition adverse
                     False = skip UNIQUEMENT si BOTH_CONTRA (mom + cvd ensemble)

    Logique BOTH_CONTRA (default, recommandee market-analyst) :
        SKIP si momentum * sign < 0 ET cvd * sign < 0
        (n=17 historique : WR 0%, 12 SL, 0 TP — filtre golden)

    Logique strict (option) :
        SKIP si AU MOINS 1 des 4 conditions adverses
        (Backtest 104 trades : 87.5% rejection + PnL bloque +4936$ = TROP LARGE)

    Backtest empirique BOTH_CONTRA Bot 1 :
        n=17 trades skipes / 104 = 16% rejection rate (acceptable)
        PnL evite : ~-560$ (12 SL skipes)
    """
    res = EntryQualityGateResult()
    if not enabled:
        return res

    # Direction sign
    if direction in ("BUY", "LONG"):
        sign = 1
    elif direction in ("SELL", "SHORT"):
        sign = -1
    else:
        return res
    res.direction_sign = sign

    # Lecture features
    # 17/05 FIX GHOST NAME (audit code-reviewer Etape 3 Bot 2 V7) :
    # AVANT : `cvd_bar_delta` n'existe PAS dans v4 enriched -> _safe_float
    #         retourne None -> contra_cvd jamais True -> gate degrade
    #         (momentum_5b SEUL en pratique, cvd contra ignore depuis creation).
    # APRES : `delta_bar` (vraie cle v4 enriched, 0% NaN, 98.99% non-zero,
    #         1369 valeurs uniques = delta volume du bar = order flow direct).
    # Backtest historique "104 trades 32.7% bloques PnL eviter -1803$" = artefact
    # momentum_5b seul. Vrai impact gate complet a re-mesurer post-fix.
    momentum = _safe_float(bar, "momentum_5b")
    cvd = _safe_float(bar, "delta_bar")
    wall_dist = _safe_float(bar, "next_wall_dist_ticks")
    res.momentum_5b = momentum
    res.cvd_bar_delta = cvd  # nom de champ conserve pour log compat
    res.next_wall_dist_ticks = wall_dist

    # Conditions
    if momentum is not None and momentum * sign < 0:
        res.contra_momentum = True
    if cvd is not None and cvd * sign < 0:
        res.contra_cvd = True
    if wall_dist is not None:
        if 0 < wall_dist < wall_dist_min:
            res.wall_too_close = True
        elif wall_dist > wall_dist_max:
            res.wall_too_far = True

    # Decision selon mode
    reasons = []
    if strict_mode:
        # SKIP si AU MOINS 1 adverse
        if res.contra_momentum:
            reasons.append(f"contra_mom={momentum:.1f}")
        if res.contra_cvd:
            reasons.append(f"contra_cvd={cvd:.0f}")
        if res.wall_too_close:
            reasons.append(f"wall_close={wall_dist:.0f}t")
        if res.wall_too_far:
            reasons.append(f"wall_far={wall_dist:.0f}t")
    else:
        # MODE BOTH_CONTRA (default) : skip UNIQUEMENT si mom ET cvd contra
        if res.contra_momentum and res.contra_cvd:
            reasons.append(f"contra_mom={momentum:.1f}")
            reasons.append(f"contra_cvd={cvd:.0f}")

    if reasons:
        res.skip = True
        mode_label = "STRICT" if strict_mode else "BOTH_CONTRA"
        res.skip_reason = f"ENTRY_QUALITY_FAIL_{mode_label} ({', '.join(reasons)})"

    return res
