"""Test parametrique anti-regression VALIDATION_MISS — Bot 3 v2.

Origine : 5e occurrence du pattern VALIDATION_MISS (17/05/2026 Phase 1.7d).
  - Bot 3 evaluate_decision lit ctx[X] mais analyze_context ne populait pas X
  - Tests unitaires verts (ctx injecte) mais 0 effet en prod
  - Detecte par code-reviewer + backtest comparatif (conf avg identique)
  - Cf DOCS/INCIDENT_LOG.md 2026-05-17 06:30

Ce test parametrique parse les sources de bot3_decision_engine.py et
bot3_context_analyzer.py pour detecter automatiquement les cles ctx lues
mais jamais populees. Si nouveau bug VALIDATION_MISS introduit, le test
FAIL.

Si une cle ctx est lue dans `evaluate_decision` (via ctx.get(...) ou ctx[...])
elle DOIT etre populee dans `analyze_context` (via ctx[X] = ...).

Cas legitimes ou la cle est lue mais pas populee par analyze_context :
  - cle "session" : alias possible (sess_period, session_id_short, etc.)
  - cle metadata injectee par paper_trader avant evaluate_decision
  -> liste autorisee dans CTX_KEYS_INJECTED_EXTERNALLY ci-dessous

Couvre aussi le funnel _resolve_neutral_side / _build_funnel qui lit ctx.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DECISION_ENGINE = ROOT / "CORE" / "bot3_decision_engine.py"
CONTEXT_ANALYZER = ROOT / "CORE" / "bot3_context_analyzer.py"

# Cles legitimement injectees par autre code que analyze_context
# (ex: paper_trader ajoute mq_levels_stale_check apres analyze_context).
# Si tu ajoutes une cle ici, JUSTIFIE en commentaire avec le pattern d'injection.
CTX_KEYS_INJECTED_EXTERNALLY: set[str] = set()
# Si besoin d'ajouter une cle, l'ajouter via .add("nom_cle") ici avec commentaire
# justifiant la source d'injection externe.


def _read_source(path: Path) -> str:
    """Lit le source en UTF-8 (force) pour eviter cp1252 issues Windows."""
    return path.read_text(encoding="utf-8")


def _extract_ctx_reads(source: str) -> set[str]:
    """Extrait toutes les cles ctx lues : ctx.get('X') ou ctx['X'].

    Note : ne match pas les ctx[var] dynamiques (variable, pas litteral),
    mais Phase 1.7b+1.7d n'utilise pas ce pattern.
    """
    reads = set(re.findall(r"ctx\.get\(\s*['\"](\w+)['\"]", source))
    reads |= set(re.findall(r"ctx\[\s*['\"](\w+)['\"]\s*\]", source))
    return reads


def _extract_ctx_writes(source: str) -> set[str]:
    """Extrait toutes les cles populees : ctx['X'] = ..."""
    return set(re.findall(r"ctx\[\s*['\"](\w+)['\"]\s*\]\s*=", source))


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_anti_validation_miss_evaluate_decision():
    """Toute cle ctx lue dans bot3_decision_engine.py DOIT etre populee dans
    bot3_context_analyzer.py (sauf liste autorisee CTX_KEYS_INJECTED_EXTERNALLY).

    Anti pattern VALIDATION_MISS (5e occurrence 17/05). Cf INCIDENT_LOG.md.
    """
    dec_src = _read_source(DECISION_ENGINE)
    ctx_src = _read_source(CONTEXT_ANALYZER)

    reads = _extract_ctx_reads(dec_src)
    writes = _extract_ctx_writes(ctx_src)

    missing = reads - writes - CTX_KEYS_INJECTED_EXTERNALLY

    assert not missing, (
        f"\n\n*** PATTERN VALIDATION_MISS detecte ! ***\n\n"
        f"Bot 3 decision_engine lit {len(missing)} cles ctx JAMAIS populees "
        f"par analyze_context :\n"
        f"  {sorted(missing)}\n\n"
        f"FIX :\n"
        f"  1. Ajouter ces cles dans CORE/bot3_context_analyzer.py:analyze_context()\n"
        f"  2. Avec defaults safe (ex: 999.0 pour distances pour eviter faux positif "
        f"     CONFLUENCE avec default 0.0)\n"
        f"  3. Ajouter test integration end-to-end (bar -> ctx -> decision)\n"
        f"  4. Si la cle est legitimement injectee par autre source (ex: paper_trader),\n"
        f"     ajouter dans CTX_KEYS_INJECTED_EXTERNALLY avec commentaire justifiant.\n\n"
        f"Source : DOCS/INCIDENT_LOG.md 2026-05-17 06:30 VALIDATION_MISS"
    )


def test_anti_validation_miss_no_unused_writes_drift():
    """Sanity : trop de cles populees mais jamais lues = data prep code mort.

    Acceptable : certaines cles sont consommees par mp_engine, paper_trader,
    snapshot_recorder, ou stockees pour debug. Mais si > 60% des writes ne
    sont pas references quelque part dans CORE/, flagger.
    """
    ctx_src = _read_source(CONTEXT_ANALYZER)
    writes = _extract_ctx_writes(ctx_src)

    # Lire tous les .py de CORE/ pour voir si les cles ecrites sont references
    referenced_anywhere = set()
    core_dir = ROOT / "CORE"
    for py in core_dir.glob("*.py"):
        try:
            src = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        referenced_anywhere |= _extract_ctx_reads(src)

    dead = writes - referenced_anywhere
    drift_pct = len(dead) / max(len(writes), 1) * 100
    # Seuil 70% : si on depasse, alerter (peut indiquer features prep pour
    # decision_engine future qui ne sont pas connectees).
    assert drift_pct < 70.0, (
        f"\nDrift ctx writes/reads : {len(dead)}/{len(writes)} ({drift_pct:.0f}%) "
        f"cles populees mais jamais lues dans CORE/ :\n"
        f"  {sorted(dead)[:10]}...\n"
        f"Si trop de drift, soit code mort dans analyze_context, "
        f"soit decision_engine ne les utilise pas encore."
    )


def test_log_codes_referenced_anywhere():
    """Tout code BOT3_* defini dans log_catalog doit etre reference (emit
    direct ou via reason_to_log_code).

    Anti code mort : sinon une feature de log JAMAIS emise = aveugle a l'audit
    en prod.
    """
    log_catalog = ROOT / "CORE" / "log_catalog.py"
    src = _read_source(log_catalog)
    defined = set(re.findall(r'"(BOT3_\w+)"\s*:\s*\(', src))

    # Chercher references dans tout CORE/
    referenced = set()
    for py in (ROOT / "CORE").glob("*.py"):
        try:
            src2 = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        referenced |= set(re.findall(r'["\'](BOT3_\w+)["\']', src2))

    dead = defined - referenced
    assert not dead, (
        f"\nCodes log BOT3_* definis dans log_catalog mais JAMAIS reference :\n"
        f"  {sorted(dead)}\n"
        f"Soit emit le code dans un module (_emit + reason mapping), soit retirer du catalog."
    )


def test_log_codes_emit_all_defined():
    """Tout code log emit dans CORE doit etre defini dans log_catalog.

    Anti KeyError silent prod : `log_catalog.resolve()` leve KeyError si code
    non defini.
    """
    log_catalog = ROOT / "CORE" / "log_catalog.py"
    src_lc = _read_source(log_catalog)
    defined = set(re.findall(r'"(BOT3_\w+)"\s*:\s*\(', src_lc))

    # Codes emit avec _emit("BOT3_...")
    emitted = set()
    for py in (ROOT / "CORE").glob("*.py"):
        try:
            src2 = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        emitted |= set(re.findall(r'_emit\(\s*["\'](BOT3_\w+)', src2))

    ghost = emitted - defined
    assert not ghost, (
        f"\nCodes BOT3_* emit mais NON DEFINIS dans log_catalog (KeyError silent) :\n"
        f"  {sorted(ghost)}\n"
        f"Ajouter ces codes dans LOG_CODES de CORE/log_catalog.py avec template "
        f"(LogLevel, category, message)."
    )
