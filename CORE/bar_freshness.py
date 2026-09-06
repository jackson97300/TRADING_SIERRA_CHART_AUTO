"""bar_freshness.py - Helper unique check fraicheur bar live cross-bot.

REECRITURE 24/06/2026 suite audit garde-fous (agent general-purpose) :
- Bot 1 MR, Bot 2 Mirror v2 (bot1_v2), Bot 3 BN V4 ont leur propre helper
  (SierraDataSource.is_fresh) mais Bot 4 MIA Trader N'EN AVAIT AUCUN
  -> trade aveugle sur bars obsoletes possible (incident silent type 24/06).
- Ce module fournit une API unique pour TOUS les bots, anti silent fallback
  pattern V1 "Gamma=0.0" (cf lessons.md).

Source de verite unique declaree Jackson 23/05 + 24/06 :
  DATA/live_enriched/sierra/{NQ,ES,MGC}/YYYYMMDD_{SYM}_sierra_enriched.jsonl

Convention "fresh" :
  - age_sec = max(file_mtime_age, last_bar_ts_event_age)
  - "fresh" = age_sec < max_age_sec
  - max_age_sec lu via env DMP_BAR_MAX_AGE_SEC (default 90s = 1 bar + 30s marge)
  - Si fichier absent OU bar corrompue OU age >= max_age_sec -> fresh=False

Anti-pattern V1 :
  - Le file mtime peut etre touched sans nouvelle bar (logger flush).
  - On cross-check via ts_event de la derniere ligne -> SI fichier touched
    mais bar reste vieille, age_sec garde la vraie staleness.

Usage standard :
    from CORE.bar_freshness import check_bar_freshness

    is_fresh, age_sec, reason = check_bar_freshness("NQ")
    if not is_fresh:
        bot_log.emit("BOTX_BAR_STALE", sym="NQ", age=age_sec, reason=reason)
        return None  # skip cycle
"""
from __future__ import annotations

import glob
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("bar_freshness")

ROOT = Path(__file__).resolve().parents[1]
SIERRA_BASE = ROOT / "DATA" / "live_enriched" / "sierra"

# Lecture env var au moment de l'appel (pas import time) pour permettre override
# runtime via service nssm sans reload code.
DEFAULT_MAX_AGE_SEC_ENV = "DMP_BAR_MAX_AGE_SEC"
# REVISION 24/06/2026 audit verification : 120s (2 bars 1m) au lieu de 90s
# pour absorber gaps legitimes Asia 00:00-04:00 UTC sans faux positif.
# Le watchdog garde 90s warn / 300s crit pour les SOURCES Sierra (alerte != trade).
DEFAULT_MAX_AGE_SEC_FALLBACK = 120  # 2 bars 1m, tolerant gaps Asia calme


def _get_default_max_age_sec() -> int:
    """Lit DMP_BAR_MAX_AGE_SEC env var (default 90)."""
    raw = os.environ.get(DEFAULT_MAX_AGE_SEC_ENV)
    if raw is None:
        return DEFAULT_MAX_AGE_SEC_FALLBACK
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_AGE_SEC_FALLBACK


def _build_glob_path(symbol: str) -> str:
    """Construit le glob pattern pour les fichiers enriched du symbole.

    Path convention 24/06/2026 :
        DATA/live_enriched/sierra/{SYM}/YYYYMMDD_{SYM}_sierra_enriched.jsonl
    """
    return str(SIERRA_BASE / symbol / f"*_{symbol}_sierra_enriched.jsonl")


def _read_last_valid_jsonl_line(
    file_path: str, tail_bytes: int = 16384, max_tries: int = 5,
) -> Optional[str]:
    """Lit la derniere ligne JSONL VALIDE d'un fichier via seek depuis EOF.

    BUG FIX 24/06/2026 : un fichier JSONL en cours d'ecriture peut avoir
    sa derniere ligne TRONQUEE (writer en plein flush) -> JSONDecodeError
    -> faux positif "corrupt_tail" qui block 100% du trafic Bot 4.

    Solution : essayer les `max_tries` dernieres lignes et retourner la
    premiere ligne valide JSON depuis la fin. Si toutes invalides -> None.

    Anti-OOM sur gros fichiers (60+MB / 1380 bars/jour) : tail_bytes=16KB
    suffit pour ~20 bars (chaque bar ~800 bytes).
    """
    try:
        with open(file_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if size == 0:
                return None
            chunk_size = min(tail_bytes, size)
            f.seek(-chunk_size, os.SEEK_END)
            chunk = f.read().decode("utf-8", errors="replace")
            lines = [ln for ln in chunk.strip().split("\n") if ln.strip()]
            if not lines:
                return None
            # Essayer derniere ligne, puis avant-derniere, etc. jusqu'a
            # trouver une ligne JSON valide (anti-race condition writer).
            for line in reversed(lines[-max_tries:]):
                try:
                    json.loads(line)
                    return line  # valide
                except (json.JSONDecodeError, ValueError):
                    continue
            return None  # toutes invalides
    except (OSError, UnicodeDecodeError):
        return None


# Alias backward compat (au cas ou)
_read_last_line = _read_last_valid_jsonl_line


def _parse_ts_event(bar: dict) -> Optional[datetime]:
    """Parse le ts_event d'une bar enriched en datetime UTC.

    Convention enricher (verifie 24/06 sur 20260624_ES_sierra_enriched.jsonl) :
        ts_event = "2026-06-24T09:15:00+00:00" (ISO 8601)
        ts = 1782292500000 (epoch ms, ts_event * 1000)
        ts_event_ns = 1782292500000000000 (epoch ns)

    Fallback : si ts_event absent, on essaie ts (ms) puis ts_event_ns.
    """
    ts_event = bar.get("ts_event")
    if ts_event:
        try:
            dt = datetime.fromisoformat(str(ts_event).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

    # Fallback ts (epoch ms)
    ts_ms = bar.get("ts")
    if ts_ms is not None:
        try:
            return datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    # Fallback ts_event_ns (epoch ns)
    ts_ns = bar.get("ts_event_ns")
    if ts_ns is not None:
        try:
            return datetime.fromtimestamp(float(ts_ns) / 1e9, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    return None


def check_bar_freshness(
    symbol: str,
    max_age_sec: Optional[int] = None,
) -> Tuple[bool, float, str]:
    """Verifie la fraicheur de la derniere bar live_enriched/sierra/{SYM}/.

    Args:
        symbol : "ES", "NQ", "MGC" (case insensitive, converti upper).
        max_age_sec : seuil staleness en secondes. Si None, lit
                      DMP_BAR_MAX_AGE_SEC env var (default 90).

    Returns:
        (is_fresh, age_sec, reason) :
            - is_fresh : True si bar fraiche, False sinon
            - age_sec : age en secondes (max(file_age, bar_ts_age))
                        ou -1.0 si echec lecture
            - reason : "ok" si fresh, sinon code skip explicite
                       ("no_file_for_{SYM}", "file_mtime_stale_Xs",
                        "corrupt_tail_TypeError", "no_ts_event",
                        "bad_ts_event_VALUE", "bar_ts_stale_Xs")

    Fail-loud : aucune erreur silencieuse. Si lecture echoue ou ts
    invalide, retourne (False, -1, "{cause}") pour permettre au bot
    de skip + emit log MAJEUR.

    Convention reason "bar_ts_stale_Xs" : la derniere ligne a bien un
    ts_event valide MAIS il date de > max_age_sec. C'est le cas le plus
    courant en panne (enricher zombie : fichier touched par flush, mais
    plus de nouvelle bar ecrite).
    """
    if not symbol:
        return False, -1.0, "no_symbol"

    sym_upper = str(symbol).upper()
    if max_age_sec is None:
        max_age_sec = _get_default_max_age_sec()

    # 1. Glob match : trouver le fichier le plus recent pour ce symbole
    pattern = _build_glob_path(sym_upper)
    matches = glob.glob(pattern)
    if not matches:
        return False, -1.0, f"no_file_for_{sym_upper}"

    latest_path = max(matches, key=lambda p: os.stat(p).st_mtime)

    # 2. Check mtime du fichier (premier garde-fou)
    try:
        file_mtime = os.stat(latest_path).st_mtime
    except OSError as e:
        return False, -1.0, f"stat_fail_{type(e).__name__}"

    file_age = time.time() - file_mtime

    # 3. Cross-check : lire la derniere bar VALIDE et son ts_event
    # Anti-pattern V1 : fichier touched par logger flush sans nouvelle bar.
    # Sans cross-check, on croit que le fichier est frais alors que la
    # derniere bar effective date d'1h.
    # FIX 24/06/2026 : _read_last_valid_jsonl_line essaie les 5 dernieres
    # lignes pour gerer le cas writer-en-cours (derniere ligne tronquee).
    last_line = _read_last_valid_jsonl_line(latest_path)
    if last_line is None:
        # Fichier vide, illisible OU 5 dernieres lignes corrompues -> fail-loud
        return False, file_age, f"empty_or_unreadable_age={file_age:.0f}s"

    try:
        last_bar = json.loads(last_line)
    except (json.JSONDecodeError, ValueError) as e:
        # Ne devrait jamais arriver car _read_last_valid_jsonl_line a deja
        # validate le JSON. Mais on garde le fail-loud par defense.
        return False, file_age, f"corrupt_tail_{type(e).__name__}"

    bar_dt = _parse_ts_event(last_bar)
    if bar_dt is None:
        return False, file_age, "no_ts_event"

    bar_age = (datetime.now(timezone.utc) - bar_dt).total_seconds()

    # Age effectif = max(file_age, bar_age). Si bar_age > max_age_sec
    # mais file_age <= max_age_sec, c'est le pattern "enricher zombie"
    # (fichier touched par flush, pas de nouvelle bar). On reporte bar_age
    # comme age effectif.
    effective_age = max(file_age, bar_age)

    if bar_age > max_age_sec:
        return False, effective_age, f"bar_ts_stale_{bar_age:.0f}s"

    if file_age > max_age_sec:
        return False, effective_age, f"file_mtime_stale_{file_age:.0f}s"

    return True, effective_age, "ok"


def check_bar_freshness_with_emit(
    symbol: str,
    emit_fn=None,
    bot_id: str = "unknown",
    max_age_sec: Optional[int] = None,
) -> Tuple[bool, float, str]:
    """Variante avec emit log structured pour audit J+1.

    Args:
        symbol : ES/NQ/MGC
        emit_fn : callable(code: str, **ctx). Si None, utilise logger.warning.
                  Pour bots : passer `bot_log.emit` du logger structure.
        bot_id : identifiant du bot caller (ex: "bot_mr", "bot1v2", "bot4")
        max_age_sec : idem check_bar_freshness

    Returns: idem check_bar_freshness

    Emit code structure : {BOT_ID_UPPER}_BAR_STALE_DETECTED
        ctx: sym, age_sec, reason
    """
    is_fresh, age_sec, reason = check_bar_freshness(symbol, max_age_sec)

    if not is_fresh:
        code = f"{bot_id.upper()}_BAR_STALE_DETECTED"
        ctx = {
            "sym": str(symbol).upper(),
            "age_sec": round(age_sec, 1),
            "reason": reason,
        }
        if emit_fn is not None:
            try:
                emit_fn(code, **ctx)
            except Exception as e:  # noqa: BLE001
                # safe-fail : un emit qui echoue ne doit pas casser la
                # decision de trading
                logger.warning(
                    f"emit {code} fail: {e} (orig ctx: {ctx})"
                )
        else:
            logger.warning(f"{code} {ctx}")

    return is_fresh, age_sec, reason
