"""Bot BN V4 bar history loader - preload buffer au boot depuis sierra_enriched JSONL.

PROBLEME RESOLU (Jackson 17/06 ULTRATHINK) :
    BNV4Engine.detect_setup exige `trend_long_lookback=240` bars dans le buffer
    avant de pouvoir evaluer un setup. Au boot, deque vide → 240 minutes (4h) de
    WARMUP avant que le bot puisse trader. Si restart en debut RTH = manque toute
    la session RTH du jour.

SOLUTION (plan agent code-reviewer 17/06) :
    Pas de fichier de buffer dedie. On relit le JSONL `sierra_enriched` du jour
    (deja persiste par le pipeline DMP) au boot, et on remplit le deque avec les
    240 dernieres bars.

    Avantage decisif :
      - Zero ecriture pendant la loop hot path (zero I/O ajoute)
      - Zero risque de corruption (lecture seule)
      - Zero nouveau format a versionner (schema sierra_enriched suffit)
      - La source de verite reste le JSONL `sierra_enriched`

APPROCHE HYBRIDE :
    1. Source primaire : tail du JSONL du jour (`DATA/live_enriched/sierra/{SYM}/YYYYMMDD_*.jsonl`)
    2. Source secondaire (fallback) : si jour J vide ou < n bars → lire J-1 pour completer
    3. TTL 36h : ignore fichiers plus anciens (warmup stale dangereux)

ROBUSTESSE :
    - JSONDecodeError sur une ligne → skip cette ligne, continue
    - Fichier illisible / inexistant → retourne [] sans raise
    - Bars sans ts_event → skip
    - Lecture seule : aucun risque d'ecriture cassante
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# TTL : on accepte des fichiers jusqu'a 36h (couvre weekend Vendredi -> Lundi).
# Au-dela, le buffer est trop stale pour servir de warmup utile.
DEFAULT_MAX_AGE_HOURS = 36


def _data_root() -> Path:
    """Resout DATA/live_enriched/sierra/ depuis l'emplacement du module."""
    try:
        return Path(__file__).resolve().parents[2] / "DATA" / "live_enriched" / "sierra"
    except Exception:
        return Path.cwd() / "DATA" / "live_enriched" / "sierra"


def _symbol_dir(symbol: str, data_root: Optional[Path] = None) -> Path:
    """Resout le dossier des JSONL pour ce symbole."""
    root = data_root or _data_root()
    return root / symbol.upper()


def _list_jsonl_files(symbol: str, max_age_hours: int,
                       data_root: Optional[Path] = None) -> list[Path]:
    """Liste les *_sierra_enriched.jsonl du symbole, tries par mtime decroissant,
    filtres par age max.

    Returns:
        Liste de Path (peut etre vide). Plus recent en premier.
    """
    d = _symbol_dir(symbol, data_root)
    if not d.exists() or not d.is_dir():
        return []
    now = time.time()
    max_age_sec = max_age_hours * 3600
    files = []
    for f in d.glob("*_sierra_enriched.jsonl"):
        try:
            mtime = f.stat().st_mtime
            if now - mtime <= max_age_sec:
                files.append((mtime, f))
        except OSError:
            continue
    files.sort(key=lambda x: x[0], reverse=True)
    return [f for _, f in files]


def _read_bars_from_file(path: Path) -> list[dict]:
    """Lit toutes les bars d'un JSONL. Skip lignes corrompues.

    Returns:
        Liste de dicts. Vide si fichier illisible.
    """
    bars: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    bar = json.loads(line)
                except json.JSONDecodeError:
                    continue  # ligne tronquee (ecriture en cours du DMP)
                if "ts_event" not in bar and "ts" not in bar:
                    continue  # bar sans timestamp = inutilisable
                bars.append(bar)
    except OSError:
        return []
    return bars


def load_recent_bars(
    symbol: str,
    n: int,
    max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    data_root: Optional[Path] = None,
) -> list[dict]:
    """Charge les `n` dernieres bars du symbole depuis les JSONL sierra_enriched.

    Strategie :
        1. Lister tous les *_sierra_enriched.jsonl tries par mtime decroissant,
           filtres par age <= max_age_hours.
        2. Charger du plus recent vers le plus ancien jusqu'a accumuler `n` bars.
        3. Trier par ts_event croissant et retourner les `n` dernieres.

    Args:
        symbol: "NQ" / "ES" / "MGC"
        n: nombre de bars desirees (typiquement 240 = lookback BN V4 long)
        max_age_hours: age max des fichiers a considerer (default 36h)
        data_root: optional override (utile pour tests). Default DATA/live_enriched/sierra/

    Returns:
        Liste de dicts (bars) ordonnee chronologiquement (ts_event croissant).
        Peut etre < n si pas assez de donnees disponibles. Vide si aucun fichier.

    Robust to :
        - Dossier inexistant
        - Fichiers illisibles
        - JSONL avec lignes corrompues
        - Bars sans ts_event
    """
    if n <= 0:
        return []
    files = _list_jsonl_files(symbol, max_age_hours, data_root)
    if not files:
        return []
    # Accumule du plus recent vers le plus ancien
    accumulated: list[dict] = []
    for f in files:
        bars = _read_bars_from_file(f)
        if not bars:
            continue
        # Prepend (les fichiers plus recents = bars plus recentes en fin de liste finale)
        accumulated = bars + accumulated
        if len(accumulated) >= n:
            break
    if not accumulated:
        return []
    # Tri chronologique (ts_event croissant). Utilise ts_event si dispo, sinon ts.
    def _bar_ts(b: dict) -> str:
        return str(b.get("ts_event") or b.get("ts") or "")
    accumulated.sort(key=_bar_ts)
    # Retourne les n dernieres bars
    return accumulated[-n:] if len(accumulated) > n else accumulated
