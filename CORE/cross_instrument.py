"""
cross_instrument.py — Bonus/malus cross-instrument ES/NQ pour scoring MIA.

Capture la corrélation directionnelle ES/NQ que Jackson regarde visuellement
("ES arrivait sur un niveau aussi quand j'ai pris NQ LONG").

**RÈGLE SOUVERAINE — ANTI PATTERN 11 V1** (Jackson 24/04/2026) :
    C'est un BONUS/MALUS dans le confluence_score, **PAS** un gate bloquant.

Pourquoi ce choix :
- V1 avait 11 layers de gates cascadés → 65% vrais setups rejetés, overfitting.
- ES ≠ NQ peut être légitime (rotation tech vs large caps, earnings, etc.).
- `bias_gate` (STEP 6bis paper_trader) bloque déjà sur NQ directionnel.
  Un 2e gate directionnel (cross) serait redondant ET plus restrictif.
- Le bonus de score permet d'amplifier les signaux confirmés cross-instrument
  **sans sacrifier** les signaux NQ-specific forts qui ont d'autres confluences.

Logique appliquée (depuis l'analyse du trade Jackson 12:22 UTC NQ LONG) :
    +2  si ES et NQ ont la même direction ET les 2 bias_clarity >= 0.30
         → "ES confirme la direction NQ" (top setup)
    -4  si ES et NQ ont des directions opposées (BULL vs BEAR)
         → "ES contredit NQ" (warning, mais le setup NQ peut encore atteindre
           seuil 8 si autres confluences fortes → pas bloquant)
     0  sinon : au moins un neutre ou clarity insuffisante
         → "info insuffisante, pas d'impact"

Usage prévu (Phase Option 2 scoring confluence) :
    from CORE.cross_instrument import compute_cross_bonus
    cross = compute_cross_bonus(nq_bar, es_bar)
    confluence_score += cross.score_delta

Auteur : MIA Trading System
Date   : 2026-04-24 (Jackson validation "bonus, pas gate")
Version: 1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from CORE.bias_calculator import compute_bias


# ==============================================================================
# CONSTANTES (calibration initiale, à raffiner empiriquement)
# ==============================================================================

BOTH_MIN_CLARITY = 0.30       # min clarity requis sur les 2 bias pour considerer confirme
CONFIRM_BONUS = 2             # points bonus si aligned et clarity OK
CONFLICT_PENALTY = 4          # points malus si directions opposees (BULL vs BEAR)


# ==============================================================================
# DATACLASS RESULTAT
# ==============================================================================


@dataclass
class CrossInstrumentBonus:
    """Résultat du calcul bonus/malus cross-instrument ES/NQ.

    Attributs :
    - `score_delta` : entier à ajouter au confluence_score composite.
        +CONFIRM_BONUS (+2) si ES confirme la direction NQ (et inverse)
        -CONFLICT_PENALTY (-4) si directions opposées
        0 sinon (au moins un neutre, ou clarity insuffisante, ou bar manquante)
    - `reasons` : raisons détaillées pour audit trade + affichage dashboard.
    """

    nq_direction: str = "NEUTRE"       # "BULL" / "BEAR" / "NEUTRE"
    nq_clarity: float = 0.0
    es_direction: str = "NEUTRE"
    es_clarity: float = 0.0

    confirmed: bool = False            # même direction + clarity OK
    conflict: bool = False             # directions opposées

    score_delta: int = 0               # impact sur confluence_score
    reasons: List[str] = field(default_factory=list)


# ==============================================================================
# FONCTION PRINCIPALE
# ==============================================================================


def compute_cross_bonus(
    nq_bar: Optional[Dict[str, Any]],
    es_bar: Optional[Dict[str, Any]],
) -> CrossInstrumentBonus:
    """Calcule le bonus/malus cross-instrument ES/NQ.

    Args:
        nq_bar: Dernière barre JSONL NQ (dict) — peut être None si indisponible.
        es_bar: Dernière barre JSONL ES (dict) — peut être None si indisponible.

    Returns:
        CrossInstrumentBonus avec score_delta:
          +2 si aligned + clarity OK
          -4 si conflit (directions opposées)
           0 sinon
    """
    result = CrossInstrumentBonus()

    # Cas 1 : au moins une barre manque → pas de cross possible, score 0 neutre
    if nq_bar is None or es_bar is None:
        result.reasons.append("bar_missing_no_cross")
        return result

    # Calculer biais sur chaque instrument via module partagé
    nq_bias = compute_bias(nq_bar)
    es_bias = compute_bias(es_bar)

    result.nq_direction = nq_bias.direction
    result.nq_clarity = nq_bias.bias_clarity
    result.es_direction = es_bias.direction
    result.es_clarity = es_bias.bias_clarity

    # Cas 2 : CONFLIT strict — directions opposées (BULL vs BEAR uniquement)
    # NEUTRE vs BULL ne compte pas comme conflit (ES indifférent, pas contraire)
    opposite_pairs = [{"BULL", "BEAR"}]
    if {nq_bias.direction, es_bias.direction} in opposite_pairs:
        result.conflict = True
        result.score_delta = -CONFLICT_PENALTY
        result.reasons.append(
            f"conflict: NQ={nq_bias.direction} (clarity={nq_bias.bias_clarity:.2f}) "
            f"vs ES={es_bias.direction} (clarity={es_bias.bias_clarity:.2f})"
        )
        return result

    # Cas 3 : CONFIRMATION — même direction non-neutre + clarity OK sur les 2
    if (
        nq_bias.direction == es_bias.direction
        and nq_bias.direction != "NEUTRE"
        and min(nq_bias.bias_clarity, es_bias.bias_clarity) >= BOTH_MIN_CLARITY
    ):
        result.confirmed = True
        result.score_delta = CONFIRM_BONUS
        result.reasons.append(
            f"confirmed: both {nq_bias.direction} "
            f"(NQ clarity={nq_bias.bias_clarity:.2f}, ES clarity={es_bias.bias_clarity:.2f})"
        )
        return result

    # Cas 4 : NEUTRE / MIXTE — au moins un neutre OU clarity insuffisante
    # → pas de bonus, pas de malus. Information insuffisante.
    result.reasons.append(
        f"neutral_info: NQ={nq_bias.direction}(clarity={nq_bias.bias_clarity:.2f}) "
        f"ES={es_bias.direction}(clarity={es_bias.bias_clarity:.2f})"
    )
    return result


# ==============================================================================
# EXPORT
# ==============================================================================

__all__ = ["CrossInstrumentBonus", "compute_cross_bonus",
           "BOTH_MIN_CLARITY", "CONFIRM_BONUS", "CONFLICT_PENALTY"]
