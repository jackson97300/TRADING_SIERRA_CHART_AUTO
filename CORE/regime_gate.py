"""RegimeGate — skip trade en regime adverse empirique (profile_shape D / day_type Normal).

Date : 2026-04-30 soir (Jackson directive : "ON APPLIQUE EN PAPER DIRECT, PAS OBSERVATION")

Findings empiriques market-analyst (n=50 Bot 1 sur 24/04 + 29/04) :
- `profile_shape == 0` (D Range, n=13) : WR 8%, mPnL **-19.4t** ← LOSER
- `profile_shape == 3` (B Breakout, n=25) : WR 44%, mPnL +18.2t ← WINNER
- `day_type == 1` (Normal, n=17) : WR 6%, mPnL **-19.6t** ← LOSER
- `day_type == 2` (NormVar, n=31) : WR 29%, mPnL +7.6t ← OK

Decision : SKIP les 2 categories LOSERS empiriques connues.

Garde-fous Lopez (incident DATA_MINING_TRAP 28/04 + verdict ml-trainer NOGO 30/04) :
- n=50 sur 2 jours = INSUFFISANT pour validation Lopez
- ml-trainer dit DSR < 0.95 sur dataset v3 (mais profile_shape ABSENT du v3 → invalidable)
- Doctrine 30/04 mode observe-only **NON SUIVIE** par directive Jackson explicite
- **Reversibilite via flag** OBLIGATOIRE (anti pattern 11 V1)

Bot 1 only : Bot 2 Databento V4 ne contient PAS profile_shape/open_type/day_type
(chantier futur : enrichir parquet V4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


# ─── Categories LOSERS empiriques (a SKIP) ───────────────────────────

LOSER_PROFILE_SHAPES = {0}  # D Range : mPnL -19.4t empirique n=13
LOSER_DAY_TYPES = {1}        # Normal : mPnL -19.6t empirique n=17


@dataclass
class RegimeGateResult:
    skip: bool = False
    skip_reason: str = ""
    profile_shape: Optional[int] = None
    day_type: Optional[int] = None
    open_type: Optional[int] = None  # observability only


def _safe_int(bar: Any, key: str) -> Optional[int]:
    """Lit une valeur enum (int) defensive. Retourne None si absent / NaN."""
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
    return int(f)


def evaluate_regime_gate(
    bar: Any,
    direction: str,
    enabled: bool = True,
) -> RegimeGateResult:
    """Evalue le RegimeGate sur une bar.

    Args:
        bar: dict ou pd.Series contenant les features DMP
        direction: "BUY" / "SELL" / "LONG" / "SHORT" (compat 2 formats)
        enabled: cfg.regime_gate_enabled (default True)

    Returns:
        RegimeGateResult avec skip + breakdown observability.
    """
    res = RegimeGateResult()
    if not enabled:
        return res

    profile_shape = _safe_int(bar, "profile_shape")
    day_type = _safe_int(bar, "day_type")
    open_type = _safe_int(bar, "open_type")

    res.profile_shape = profile_shape
    res.day_type = day_type
    res.open_type = open_type

    # SKIP si profile_shape == 0 (D Range, mPnL -19.4t empirique)
    if profile_shape is not None and profile_shape in LOSER_PROFILE_SHAPES:
        res.skip = True
        res.skip_reason = f"REGIME_LOSER_PROFILE_SHAPE_{profile_shape} (D Range, mPnL -19t historique)"
        return res

    # SKIP si day_type == 1 (Normal, mPnL -19.6t empirique)
    if day_type is not None and day_type in LOSER_DAY_TYPES:
        res.skip = True
        res.skip_reason = f"REGIME_LOSER_DAY_TYPE_{day_type} (Normal, mPnL -19t historique)"
        return res

    return res
