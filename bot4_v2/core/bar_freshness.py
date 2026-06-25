"""Bot 4 v2 bar_freshness — FORK CORE/bar_freshness.py (24/06 audit) + adaptations.

FORK Phase P2 (25/06/2026) :
- Params explicites (sierra_base + max_age_sec) au lieu de hardcoded path + env var
- Logger via bot4_v2.observability.telemetry (PAS stdlib logging direct)
- API stable pour P3 decision_router + bot4_v2 main loop

Heritages V1 conserves :
- Cross-check file_mtime vs bar_ts_event (anti pattern "logger flush touched")
- 5 dernieres lignes tail-read (anti-race writer-en-cours)
- Reasons explicites pour audit J+1

Convention source unique declaree Jackson 23/05 + 24/06 :
    DATA/live_enriched/sierra/{NQ,ES,MGC}/YYYYMMDD_{SYM}_sierra_enriched.jsonl

Usage standard :
    from bot4_v2.core.bar_freshness import check_bar_freshness
    from bot4_v2.config.settings import get_settings

    cfg = get_settings()
    sierra_base = cfg.repo_root / "DATA" / "live_enriched" / "sierra"
    is_fresh, age_sec, reason = check_bar_freshness("NQ", sierra_base, cfg.bar_max_age_sec)
    if not is_fresh:
        emit_safe(log, "BOT4V2_BAR_STALE", sym="NQ", age=age_sec, reason=reason)
        return None  # skip cycle
"""
from __future__ import annotations

import glob
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from bot4_v2.observability.telemetry import get_logger

_LOG = get_logger(__name__)

# R1 review batch 1 P2 (silent fallback pattern banni) :
# PAS de DEFAULT_MAX_AGE_SEC_FALLBACK. Source unique = bot4_v2.config.settings.bar_max_age_sec.
# Caller DOIT passer max_age_sec explicit -> raise ValueError sinon (fail-loud).


def _build_glob_pattern(sierra_base: Path, symbol: str) -> str:
    """Construit glob pattern fichiers enriched du symbole.

    Path convention : sierra_base/{SYM}/*_{SYM}_sierra_enriched.jsonl
    """
    return str(sierra_base / symbol / f"*_{symbol}_sierra_enriched.jsonl")


def _read_last_valid_jsonl_line(
    file_path: str,
    tail_bytes: int = 16384,
    max_tries: int = 5,
) -> Optional[str]:
    """Lit derniere ligne JSONL VALIDE via seek depuis EOF.

    BUG FIX heritage 24/06/2026 : fichier en cours d'ecriture peut avoir derniere
    ligne TRONQUEE -> JSONDecodeError -> faux positif block 100% trafic Bot 4.

    Solution : essayer les `max_tries` dernieres lignes, retourner premiere
    ligne valide JSON depuis la fin. Si toutes invalides -> None.

    Anti-OOM gros fichiers (60+MB/1380 bars) : tail_bytes=16KB suffit ~20 bars.
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
            # Essayer derniere, puis avant-derniere, etc. jusqu'a ligne JSON valide
            for line in reversed(lines[-max_tries:]):
                try:
                    json.loads(line)
                    return line
                except (json.JSONDecodeError, ValueError):
                    continue
            return None  # toutes invalides
    except (OSError, UnicodeDecodeError):
        return None


def _parse_ts_event(bar: dict) -> Optional[datetime]:
    """Parse ts_event d'une bar enriched en datetime UTC.

    Convention enricher :
        ts_event = "2026-06-24T09:15:00+00:00" (ISO 8601 string)
        ts = 1782292500000 (epoch ms)
        ts_event_ns = 1782292500000000000 (epoch ns)

    Fallback : ts_event > ts (ms) > ts_event_ns (ns).
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

    ts_ms = bar.get("ts")
    if ts_ms is not None:
        try:
            return datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    ts_ns = bar.get("ts_event_ns")
    if ts_ns is not None:
        try:
            return datetime.fromtimestamp(float(ts_ns) / 1e9, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass

    return None


def check_bar_freshness(
    symbol: str,
    sierra_base: Path,
    max_age_sec: int,
) -> Tuple[bool, float, str]:
    """Verifie fraicheur derniere bar live_enriched/sierra/{SYM}/.

    Args:
        symbol : "ES", "NQ", "MGC" (case insensitive, [A-Za-z0-9]+ <=8 chars)
        sierra_base : Path racine sierra (ex cfg.repo_root/DATA/live_enriched/sierra)
        max_age_sec : seuil staleness sec OBLIGATOIRE (positif > 0).
                      Source unique = bot4_v2.config.settings.bar_max_age_sec.

    Returns:
        (is_fresh, age_sec, reason) :
            - is_fresh : True si bar fraiche
            - age_sec : age max(file_age, bar_ts_age) ou -1.0 si echec
            - reason : "ok" si fresh, sinon code skip explicit :
                "no_symbol", "invalid_symbol_{X}", "no_file_for_{SYM}",
                "stat_fail_{ExcName}", "empty_or_unreadable_age={X}s",
                "corrupt_tail_{ExcName}", "no_ts_event",
                "bar_ts_stale_{X}s", "file_mtime_stale_{X}s"

    Raises:
        ValueError : si max_age_sec invalide (None, 0, negatif, non-int).
                     Source unique = settings (R1 review batch 1 P2 anti silent fallback).

    Fail-loud : aucune erreur silencieuse. Si lecture echoue OU ts invalide,
    retourne (False, -1, "{cause}") pour caller skip + emit log MAJEUR.

    Convention "bar_ts_stale_Xs" : derniere ligne a ts_event valide MAIS date
    > max_age_sec. C'est le cas le plus courant en panne (enricher zombie :
    fichier touched par flush mais pas de nouvelle bar ecrite).
    """
    if not symbol:
        return False, -1.0, "no_symbol"

    # R1 review : source unique max_age_sec = settings.bar_max_age_sec (fail-loud)
    if not isinstance(max_age_sec, int) or max_age_sec <= 0:
        raise ValueError(
            f"max_age_sec must be positive int, got {max_age_sec!r}. "
            "Use bot4_v2.config.settings.get_settings().bar_max_age_sec "
            "(source unique source-of-truth)."
        )

    sym_upper = str(symbol).upper()

    # R2 review : validation symbol path safety (defense en profondeur futur MGC + autres)
    if not sym_upper.isalnum() or not (1 <= len(sym_upper) <= 8):
        return False, -1.0, f"invalid_symbol_{sym_upper[:16]}"

    # 1. Glob match : fichier le plus recent pour ce symbole
    pattern = _build_glob_pattern(sierra_base, sym_upper)
    matches = glob.glob(pattern)
    if not matches:
        return False, -1.0, f"no_file_for_{sym_upper}"

    latest_path = max(matches, key=lambda p: os.stat(p).st_mtime)

    # 2. Check mtime fichier (premier garde-fou)
    try:
        file_mtime = os.stat(latest_path).st_mtime
    except OSError as exc:
        return False, -1.0, f"stat_fail_{type(exc).__name__}"

    file_age = time.time() - file_mtime

    # 3. Cross-check : lire derniere bar VALIDE et son ts_event
    # Anti-pattern V1 : fichier touched par logger flush sans nouvelle bar.
    last_line = _read_last_valid_jsonl_line(latest_path)
    if last_line is None:
        return False, file_age, f"empty_or_unreadable_age={file_age:.0f}s"

    try:
        last_bar = json.loads(last_line)
    except (json.JSONDecodeError, ValueError) as exc:
        # Ne devrait jamais arriver car _read_last_valid_jsonl_line valide deja.
        # Defense en profondeur.
        return False, file_age, f"corrupt_tail_{type(exc).__name__}"

    bar_dt = _parse_ts_event(last_bar)
    if bar_dt is None:
        return False, file_age, "no_ts_event"

    bar_age = (datetime.now(timezone.utc) - bar_dt).total_seconds()

    # Age effectif = max(file_age, bar_age). Si bar_age > seuil mais file_age OK,
    # c'est le pattern "enricher zombie" -> reporter bar_age.
    effective_age = max(file_age, bar_age)

    if bar_age > max_age_sec:
        return False, effective_age, f"bar_ts_stale_{bar_age:.0f}s"

    if file_age > max_age_sec:
        return False, effective_age, f"file_mtime_stale_{file_age:.0f}s"

    return True, effective_age, "ok"
