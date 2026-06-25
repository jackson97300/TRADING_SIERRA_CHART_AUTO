"""Bot 4 v2 telemetry — wrapper logging_v2.

Pattern v2 strict :
- TOUTES les emissions log passent par `emit_safe(logger, code, **ctx)`.
- Code log defini dans CORE/log_catalog.py namespace `BOT4V2_*`.
- Fallback fail-soft : si code absent du catalog -> swallow KeyError mais
  emit logger.warning explicit (pas silent fallback).
- `get_logger()` retourne stdlib `logging.Logger` (PAS la classe custom
  CORE.logging_v2.Logger). Raison : on garde l'API stdlib standard pour
  les .info/.warning/.error directs ; emit_safe gere le routing vers
  log_catalog via codes.

Anti-pattern v1 interdit (spec section 7) :
- print() : INTERDIT (utiliser emit_safe ou logger.info)
- except: pass purs : INTERDIT
- emit sans contexte : INTERDIT (toujours **ctx kwargs)

Compatible CORE.log_catalog.resolve() partage cross-bot. Tests : test_telemetry.py
"""
from __future__ import annotations

import logging
from typing import Any

try:
    from CORE.log_catalog import resolve as _v2_resolve_code
    _CATALOG_AVAILABLE = True
except ImportError:
    _CATALOG_AVAILABLE = False
    _v2_resolve_code = None


_LOGGERS_CACHE: dict[str, logging.Logger] = {}


def get_logger(module_name: str) -> logging.Logger:
    """Retourne stdlib logging.Logger pour module donne (cache).

    Args:
        module_name : nom module (ex "bot4_v2.observability.shadow_logger")

    Returns:
        logging.Logger configure avec StreamHandler si pas deja attache.
    """
    if module_name in _LOGGERS_CACHE:
        return _LOGGERS_CACHE[module_name]

    log = logging.getLogger(module_name)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
        )
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    _LOGGERS_CACHE[module_name] = log
    return log


def emit_safe(logger: logging.Logger, code: str, **ctx: Any) -> bool:
    """Emit un code log catalog avec fail-soft contrele.

    Args:
        logger : stdlib logging.Logger via get_logger()
        code : code BOT4V2_* defini dans CORE/log_catalog.py
        **ctx : contexte (sym, direction, score, etc.)

    Returns:
        True si code resolu + emis, False si code absent catalog ou erreur

    Fail-soft logic :
    - Si log_catalog non disponible (test isole) -> emit logger.info direct, return True
    - Si code absent du catalog -> log warning explicit (pas silent) + return False
    - Si erreur format msg_fr -> log warning explicit + fallback msg brut + return True
    - Toute exception interne -> log warning + return False (jamais raise)
    """
    if not _CATALOG_AVAILABLE or _v2_resolve_code is None:
        # Mode test/standalone : direct log info
        logger.info("[%s] ctx=%s", code, ctx)
        return True

    try:
        resolved = _v2_resolve_code(code)
    except KeyError:
        logger.warning(
            "emit_safe: code '%s' absent du log_catalog (ctx=%s). "
            "Ajouter dans CORE/log_catalog.py namespace BOT4V2_*.",
            code, ctx,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("emit_safe: resolve('%s') exception : %s", code, exc)
        return False

    # log_catalog.resolve() retourne (level, category, template)
    try:
        level, _category, template = resolved
    except (TypeError, ValueError) as exc:
        logger.warning(
            "emit_safe: resolve('%s') retour inattendu %s : %s",
            code, resolved, exc,
        )
        return False

    try:
        msg_fr = template.format(**ctx)
    except (KeyError, ValueError, IndexError) as exc:
        # Template attend des placeholders que ctx ne fournit pas
        logger.warning(
            "emit_safe: format error code='%s' template='%s' ctx=%s exc=%s",
            code, template, ctx, exc,
        )
        msg_fr = f"{code} [format_error] ctx={ctx}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("emit_safe: format unexpected error code='%s' : %s", code, exc)
        msg_fr = f"{code} [format_error] ctx={ctx}"

    # Emit selon level (level peut etre Enum, str ou int)
    level_str = getattr(level, "name", str(level)).upper()
    if level_str in ("CRITIQUE", "CRITICAL", "ERROR"):
        logger.error("[%s] %s ctx=%s", code, msg_fr, ctx)
    elif level_str in ("MAJEUR", "MAJOR", "WARNING", "ALERTE", "ALERT"):
        logger.warning("[%s] %s ctx=%s", code, msg_fr, ctx)
    else:
        logger.info("[%s] %s ctx=%s", code, msg_fr, ctx)
    return True


def reset_logger_cache_for_tests() -> None:
    """Reset cache loggers pour tests independants."""
    _LOGGERS_CACHE.clear()
