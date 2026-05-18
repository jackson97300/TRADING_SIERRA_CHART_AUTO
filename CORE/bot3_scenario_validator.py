"""CORE/bot3_scenario_validator.py - Scenario Validator Bot 3 v2 (Phase 2).

Module : verifie si la narrative courante NSM est toujours valide selon :
  1. Time decay : bars_in_state > N (max ~4h sur 1m bars = 240) → INVALIDATED
  2. PlotTwist incompatible avec narrative_state actuel
     - BOS bearish dans TREND_UP_CONTINUATION → INVALIDATED
     - BOS bullish dans TREND_DOWN_CONTINUATION → INVALIDATED
     - CAPITULATION bearish dans TREND_UP_CONTINUATION → INVALIDATED (climax fin)
     - CAPITULATION bullish dans TREND_DOWN_CONTINUATION → INVALIDATED
     - DIVERGENCE contradictoire bias narrative (seuil severity 0.3 commun
       Phase 2 ; per-type tuning reporte Phase 3 cf review Claude 4.7)

Architecture : Bot 3 v2 Narrative Layer (Phase 2 TRACKING ONLY).
Pattern : stateless function-based (pas de state buffer, consomme NSM snapshot
+ liste PlotTwists). NSM gere son propre state.

Data source : NarrativeStateSnapshot (Phase 1) + list[PlotTwist] (Phase 2 detectors).

Created : 2026-05-18 by Jackson + Claude (Phase 2 J+1)
Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md (sect 247-258)

Auteur : Bot 3 v2 Narrative Layer Phase 2
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 PM : creation Phase 2 J+1 - validator stateless + time decay
# 2026-05-18 PM (2) : fix 3 bugs review Claude 4.7 externe :
#   #2 first-match-wins -> strongest-signal (attribution post-mortem correcte)
#   #3 bars_in_state < 0 (snapshot inconsistant) defensif anti-silent
#   #4 RANGE_RESPECTED/OPEN_ROTATION/OPEN_TEST_DRIVE pas de safety net :
#      decision explicite (NSM source unique verite via T17/T18/T19/T20/T21)
#   #1 cosmetique : retire "forte" du docstring DIVERGENCE (alignement code/intent
#      reporte Phase 3 via _SEVERITY_MIN_BY_TYPE per-type tuning)
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

from typing import Any, Callable

try:
    from CORE.bot3_narrative_logging import emit
    from CORE.bot3_narrative_state_machine import NarrativeState, NarrativeStateSnapshot
    from CORE.bot3_plot_twist_detectors import PlotTwist
except ModuleNotFoundError:
    from bot3_narrative_logging import emit  # type: ignore[no-redef]
    from bot3_narrative_state_machine import (  # type: ignore[no-redef]
        NarrativeState, NarrativeStateSnapshot,
    )
    from bot3_plot_twist_detectors import PlotTwist  # type: ignore[no-redef]

# ─── Constants ────────────────────────────────────────────────────────────

# Time decay : bars max dans un etat avant force INVALIDATED.
# FIX R5 review market-analyst : per-state time decay (vs unique 240 bars).
# Dalton MOM Ch.10 : auction cycles 4-6h typique RTH. Trend Day Dalton-canon
# dure facilement la session entiere (= 6.5h = 390 bars 1m).
# Au seuil unique 240 bars, OPEN_DRIVE_UP a 09:35 INVALIDATED a 13:35 alors
# que le trend continue jusqu'a la cloche = NSM coupe le narratif legitime.
TIME_DECAY_BARS_DEFAULT: int = 240  # fallback si state pas dans dict

# Per-state time decay (R5 fix) :
# - TREND_*_CONTINUATION : 390 bars (full RTH 6.5h) - Trend Day Dalton-canon
# - OPEN_DRIVE_* : 240 bars (4h = open auction window classic Dalton)
# - WYCKOFF_SPRING_LONG / UPTHRUST_SHORT : 120 bars (2h post-spring decision)
# - EXHAUSTION_TOP / BOTTOM : 60 bars (1h terminal state)
# - RANGE_RESPECTED : 240 bars (range peut tenir half session)
# - OPEN_ROTATION / OPEN_TEST_DRIVE : 60 bars (1h decision rapide)
_TIME_DECAY_BARS_BY_STATE: dict[NarrativeState, int] = {
    NarrativeState.TREND_UP_CONTINUATION:    390,
    NarrativeState.TREND_DOWN_CONTINUATION:  390,
    NarrativeState.OPEN_DRIVE_UP:            240,
    NarrativeState.OPEN_DRIVE_DOWN:          240,
    NarrativeState.WYCKOFF_SPRING_LONG:      120,
    NarrativeState.WYCKOFF_UPTHRUST_SHORT:   120,
    NarrativeState.EXHAUSTION_TOP:           60,
    NarrativeState.EXHAUSTION_BOTTOM:        60,
    NarrativeState.RANGE_RESPECTED:          240,
    NarrativeState.OPEN_ROTATION:            60,
    NarrativeState.OPEN_TEST_DRIVE:          60,
}

# Etats exempts du time decay (terminal states ou PRE_OPEN long-running)
_TIME_DECAY_EXEMPT_STATES: frozenset[NarrativeState] = frozenset({
    NarrativeState.INVALIDATED,           # deja invalide
    NarrativeState.PRE_OPEN_NEUTRAL,      # pre-open peut durer 16h+ (Asia/London)
    NarrativeState.PRE_OPEN_BEARISH,
    NarrativeState.PRE_OPEN_BULLISH,
})

# Mapping NarrativeState -> set de twists qui INVALIDENT cet etat.
# Logique : si on est en TREND_UP_CONTINUATION et qu'on detecte un BOS bearish
# (STRUCTURE_BREAK avec direction=-1), la thesis trend_up est cassee.
_INVALIDATING_TWISTS: dict[NarrativeState, list[tuple[str, int]]] = {
    # TREND_UP : invalide par BOS bearish, CAPITULATION bearish (climax top), divergence bearish
    # NOTE per-type severity tuning reporte Phase 3 (cf bug #1 review Claude 4.7 18/05).
    # Pour Phase 2, seuil unique 0.3 sur tous types (data point pour calibration future).
    NarrativeState.TREND_UP_CONTINUATION: [
        ("STRUCTURE_BREAK", -1),
        ("CAPITULATION", -1),
        ("DIVERGENCE", -1),
    ],
    NarrativeState.TREND_DOWN_CONTINUATION: [
        ("STRUCTURE_BREAK", +1),
        ("CAPITULATION", +1),
        ("DIVERGENCE", +1),
    ],
    # OPEN_DRIVE_UP : invalide par BOS bearish (reversal) ou CAPITULATION bearish
    NarrativeState.OPEN_DRIVE_UP: [
        ("STRUCTURE_BREAK", -1),
        ("CAPITULATION", -1),
    ],
    NarrativeState.OPEN_DRIVE_DOWN: [
        ("STRUCTURE_BREAK", +1),
        ("CAPITULATION", +1),
    ],
    # WYCKOFF_SPRING_LONG : invalide si BOS bearish (spring failed)
    NarrativeState.WYCKOFF_SPRING_LONG: [
        ("STRUCTURE_BREAK", -1),
    ],
    NarrativeState.WYCKOFF_UPTHRUST_SHORT: [
        ("STRUCTURE_BREAK", +1),
    ],
    # EXHAUSTION_TOP : invalide si BOS bullish (climax pas confirmé)
    NarrativeState.EXHAUSTION_TOP: [
        ("STRUCTURE_BREAK", +1),
    ],
    NarrativeState.EXHAUSTION_BOTTOM: [
        ("STRUCTURE_BREAK", -1),
    ],
    # Fix #4 review Claude 4.7 18/05 : decision design EXPLICITE.
    # NSM est source unique de verite pour ces 3 etats. Phase 2 TRACKING ONLY
    # n'ajoute PAS de safety net validator-side. Justification :
    # - RANGE_RESPECTED : T18 (close>prev_vah + prev_close>prev_vah → TREND_UP)
    #   et T19 (mirror) gerent breakout. Validator dupliquerait = double-fire risk.
    # - OPEN_ROTATION : T17 (ib_complete + inside_va) gere transition vers RANGE.
    # - OPEN_TEST_DRIVE : T14/T15/T16 gerent transitions D-type final.
    # Si NSM rate une transition, le replay log differential pre/post detectera.
    # Re-evaluer en Phase 3 quand DirectionResolver consume validator output.
    NarrativeState.RANGE_RESPECTED: [],
    NarrativeState.OPEN_ROTATION: [],
    NarrativeState.OPEN_TEST_DRIVE: [],
}

# Severity minimale pour qu'un twist invalidate (anti-bruit).
# Seuil derive backtest empirique (data Bot 3 v1 11j observation 18/05).
# Per-type tuning reporte Phase 3 (cf review Claude 4.7 bug #1).
_INVALIDATION_SEVERITY_MIN: float = 0.3


def is_narrative_still_valid(
    snapshot: NarrativeStateSnapshot,
    twists: list[PlotTwist],
    time_decay_bars: int = TIME_DECAY_BARS_DEFAULT,
    log_fn: Callable[..., None] | None = None,
) -> tuple[bool, str]:
    """Verifie si la narrative courante est encore valide.

    Args:
        snapshot : NarrativeStateSnapshot NSM (post .transition()).
        twists : list[PlotTwist] detectes sur la bar courante (sortie de scan_all).
        time_decay_bars : seuil bars_in_state au-dela duquel on force INVALIDATED.
        log_fn : callable optionnel pour log capture en tests.

    Returns:
        (is_valid, reason) : (True, "") si OK, sinon (False, raison concise).
        Raisons possibles :
          - "TIME_DECAY"
          - "INVALIDATING_TWIST_{type}_{direction}"
    """
    state = snapshot.state
    delta = snapshot.bar_idx_current - snapshot.state_entered_at_bar_idx

    # Fix #3 review Claude 4.7 : bars_in_state ne devrait jamais etre negatif.
    # Cas pathologique : NSM rollback / pickle corrompu / partial reset. On ne
    # invalidate PAS sur donnee inconsistante (defensif), on laisse passer +
    # log diagnostique pour permettre investigation upstream.
    if delta < 0:
        emit(
            "BOT3_NSM_PERSIST_RECOVERED",
            log_fn=log_fn,
            sym=snapshot.symbol,
            reason=f"snapshot_inconsistent_current={snapshot.bar_idx_current}_entered={snapshot.state_entered_at_bar_idx}",
        )
        return True, ""
    bars_in_state = delta

    # 1. Time decay check (R5 fix : per-state threshold).
    # Priorite : _TIME_DECAY_BARS_BY_STATE > time_decay_bars param > default.
    if state not in _TIME_DECAY_EXEMPT_STATES:
        # Si caller a passe override explicite (non-default), on respecte.
        if time_decay_bars != TIME_DECAY_BARS_DEFAULT:
            effective_threshold = time_decay_bars
        else:
            effective_threshold = _TIME_DECAY_BARS_BY_STATE.get(
                state, time_decay_bars
            )
        if bars_in_state > effective_threshold:
            emit(
                "BOT3_SCENARIO_TIME_DECAY",
                log_fn=log_fn,
                sym=snapshot.symbol,
                state=state.value,
                bars_in_state=bars_in_state,
                threshold=effective_threshold,
            )
            return False, "TIME_DECAY"

    # 2. PlotTwist incompatibility check
    invalidating_rules = _INVALIDATING_TWISTS.get(state, [])
    if not invalidating_rules or not twists:
        return True, ""

    # Fix #2 review Claude 4.7 : strongest-signal au lieu de first-match-wins.
    # Si plusieurs twists invalident, on retourne celui de severity max (attribution
    # post-mortem correcte). Phase 3 DirectionResolver consume cette raison pour
    # decider l'action - prend la plus forte cause pour eviter mauvais arbitrage.
    candidates: list[PlotTwist] = []
    for twist in twists:
        if twist.severity < _INVALIDATION_SEVERITY_MIN:
            continue
        for (rule_type, rule_dir) in invalidating_rules:
            if twist.twist_type == rule_type and twist.direction == rule_dir:
                candidates.append(twist)
                break  # 1 match suffit par twist

    if not candidates:
        return True, ""

    strongest = max(candidates, key=lambda t: t.severity)
    reason = f"INVALIDATING_TWIST_{strongest.twist_type}_{strongest.direction}"
    emit(
        "BOT3_SCENARIO_INVALIDATED",
        log_fn=log_fn,
        sym=snapshot.symbol,
        state=state.value,
        reason=reason,
        bars_in_state=bars_in_state,
    )
    return False, reason
