"""bot3_narrative_logging.py — Centralized emit helpers Bot 3 v2 Narrative Layer.

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
Last modified : 2026-05-18 - creation Phase 1 J+0 PM

Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md
Review trace : LOGS/reviews/REVIEW_BOT3V2_narrative_logging_*.json (Phase 1)
Memory feedback : .claude/memory/feedback_bot3v2_logging_*.md (post-review)

Auteur : Bot 3 v2 Narrative Layer Phase 1
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 : creation skeleton (Phase 1 foundation, 11 codes BOT3_NSM/STORY)
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import logging
from typing import Any, Callable

try:
    from CORE.log_catalog import LogLevel, format_message, get_action, resolve
except ImportError:
    from log_catalog import LogLevel, format_message, get_action, resolve

logger = logging.getLogger("bot3_v2.narrative")

# Liste des 11 codes Bot 3 v2 - check au load module pour fail-fast si manquant
# (anti-pattern V1 KeyError silencieux runtime cf INCIDENT_LOG 2026-05-18 12:30).
BOT3V2_NARRATIVE_CODES: frozenset[str] = frozenset({
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

    level, _category, _template = resolve(code)
    msg = format_message(code, **ctx)
    actions = get_action(level)

    if level == LogLevel.CRITIQUE:
        logger.critical(f"[{code}] {msg}")
    elif level == LogLevel.MAJEUR:
        logger.error(f"[{code}] {msg}")
    elif level == LogLevel.ALERTE:
        logger.warning(f"[{code}] {msg}")
    else:
        logger.info(f"[{code}] {msg}")

    # Discord/snapshot actions deferred Phase 3+ (cf master plan section Logging)
    _ = actions  # silence unused (reserved for future Discord webhook)
