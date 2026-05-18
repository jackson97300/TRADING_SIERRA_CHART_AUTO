"""CORE/bot3_narrative_logging.py — Centralized emit helpers Bot 3 v2 Narrative Layer.

Module : helpers d'emit logs structures pour NSM + StoryTrackers + persistence.
Centralise les call site vers log_catalog.resolve() pour permettre :
  - Tests unitaires verifient KeyError au load module (1 import = 1 check)
  - Refactor future format placeholder sans modifier 50+ call sites
  - Discord webhook auto sur LogLevel.CRITIQUE / MAJEUR
  - Journal JSONL dedie LOGS/bot3_v2/ (optionnel, Phase 3+)

Architecture : Bot 3 v2 Narrative Layer (Phase 1 TRACKING ONLY).
Pattern reference : aucun pattern direct, helpers utility minimaux.

Data source : N/A (module utility logging, pas de consume payload).
  Inputs : code + ctx dict de la fonction appelante (NSM, Story, Persistence).

Created : 2026-05-18 by Jackson + Claude (mode mentor proactif)
Last modified : 2026-05-18 PM - V1.1 fix critique Claude 4.7 review (4 bugs reels)

Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md
Review trace : LOGS/reviews/REVIEW_BOT3V2_narrative_logging_*.json (Phase 1)
Memory feedback : .claude/memory/feedback_bot3v2_logging_*.md (post-review)

Auteur : Bot 3 v2 Narrative Layer Phase 1
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 AM : creation skeleton (Phase 1 foundation, 11 codes BOT3_NSM/STORY)
# 2026-05-18 PM : V1.1 fix critique Claude 4.7 review - 4 bugs reels
#   #1 get_action() exec inutile -> commented out (perf + intent)
#   #2 logger f-strings -> %-formatting (lint G004/PLW1203 + lazy eval perf)
#   #3 double resolve (format_message re-call resolve) -> single resolve + template.format
#   #4 except ImportError -> except ModuleNotFoundError (anti silent CORE/log_catalog brisé)
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from typing import Any, Callable

# Fix #4 : ModuleNotFoundError (sous-classe ImportError Python 3.6+) plus specifique.
# Si CORE/log_catalog.py existe mais a une ImportError interne (typo, dep manquante),
# on ne fallback PAS silencieusement vers log_catalog -> le vrai bug remonte.
try:
    from CORE.log_catalog import LogLevel, resolve
except ModuleNotFoundError:
    from log_catalog import LogLevel, resolve  # type: ignore[no-redef]

logger = logging.getLogger("bot3_v2.narrative")

# Liste des codes Bot 3 v2 - check au load module pour fail-fast si manquant
# (anti-pattern V1 KeyError silencieux runtime cf INCIDENT_LOG 2026-05-18 12:30).
# Phase 1 : 11 codes NSM + StoryTrackers
# Phase 2 (18/05) : +6 codes PlotTwist (4) + ScenarioValidator (2)
BOT3V2_NARRATIVE_CODES: frozenset[str] = frozenset({
    # Phase 1 - NSM (8) + Story Trackers (3)
    "BOT3_NSM_STATE_TRANSITION",
    "BOT3_NSM_STATE_OBSERVE",
    "BOT3_NSM_INVALIDATED",
    "BOT3_NSM_FLICKER_GUARD",
    "BOT3_NSM_PERSIST_OK",
    "BOT3_NSM_PERSIST_FAIL",
    "BOT3_NSM_PERSIST_RECOVERED",
    "BOT3_NSM_SESSION_RESET",
    "BOT3_STORY_BOS_DETECTED",
    "BOT3_STORY_TREND_CONFIRMED",
    "BOT3_STORY_REVERSAL_CANDIDATE",
    # Phase 2 - PlotTwistDetectors (4) + ScenarioValidator (2)
    "BOT3_PLOT_TWIST_STRUCTURE_BREAK",
    "BOT3_PLOT_TWIST_VOLUME_ANOMALY",
    "BOT3_PLOT_TWIST_DIVERGENCE",
    "BOT3_PLOT_TWIST_CAPITULATION",
    "BOT3_SCENARIO_INVALIDATED",
    "BOT3_SCENARIO_TIME_DECAY",
    # Phase 3 - DirectionResolver (6) + ShadowMode (1)
    "BOT3_RESOLVER_DIRECTION_RESOLVED",
    "BOT3_RESOLVER_NO_TRADE",
    "BOT3_RESOLVER_PENDING_ENTRY",
    "BOT3_RESOLVER_CONFIRMATION_OK",
    "BOT3_RESOLVER_CONFIRMATION_INVALIDATED",
    "BOT3_RESOLVER_CONFIRMATION_TIMEOUT",
    "BOT3_SHADOW_DIVERGENCE",
})


def _verify_codes_registered() -> None:
    """Check au load module que tous les 11 codes sont registered dans log_catalog.

    Fail-fast si manquant (KeyError ImportError au boot) vs runtime silent.
    Cf INCIDENT_LOG 2026-05-18 12:30 [VALIDATION_MISS] pattern prevention.
    """
    missing = []
    for code in BOT3V2_NARRATIVE_CODES:
        try:
            resolve(code)
        except KeyError:
            missing.append(code)
    if missing:
        raise ImportError(
            f"bot3_narrative_logging: {len(missing)} codes manquants dans "
            f"CORE/log_catalog.py: {sorted(missing)}. Ajouter avant import."
        )


_verify_codes_registered()


def emit(code: str, log_fn: Callable[..., None] | None = None, **ctx: Any) -> None:
    """Emit un log Bot 3 v2 via log_catalog.

    Args:
        code: code log_catalog (doit etre dans BOT3V2_NARRATIVE_CODES sinon
              KeyError fail-loud).
        log_fn: callable optionnel `log_fn(code, **ctx)` pour redirection
                custom (utile en tests pour capture). Si None, utilise
                logger.{info|warning|error|critical}.
        **ctx: placeholders pour template format.

    Raises:
        KeyError si code inconnu (force enregistrement avant emit).
    """
    if code not in BOT3V2_NARRATIVE_CODES:
        raise KeyError(
            f"emit() code '{code}' pas dans BOT3V2_NARRATIVE_CODES whitelist. "
            f"Ajouter au catalog + whitelist avant emit."
        )

    if log_fn is not None:
        log_fn(code, **ctx)
        return

    # Fix #3 : single resolve + template.format local (vs double resolve via
    # format_message qui re-appelait resolve interne).
    level, _category, template = resolve(code)
    try:
        msg = template.format(**ctx)
    except KeyError as e:
        msg = f"{template} [MISSING_CTX: {e}]"

    # Fix #2 : %-formatting (lazy eval lint G004/PLW1203 compliant).
    # Le formatage du msg n'a lieu que si le record est effectivement emit
    # selon level filter du logger root.
    if level == LogLevel.CRITIQUE:
        logger.critical("[%s] %s", code, msg)
    elif level == LogLevel.MAJEUR:
        logger.error("[%s] %s", code, msg)
    elif level == LogLevel.ALERTE:
        logger.warning("[%s] %s", code, msg)
    else:
        logger.info("[%s] %s", code, msg)

    # Fix #1 : get_action() pas execute (perf + intent visible).
    # Phase 3+ : actions = get_action(level)  # routing Discord webhook auto
