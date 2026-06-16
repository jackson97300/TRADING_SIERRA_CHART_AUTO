"""Data source Bot 1 v2 - lit sierra_enriched JSONL.

Source UNIQUE de verite : DATA/live_enriched/sierra/{symbol}/YYYYMMDD_*_sierra_enriched.jsonl

Pattern :
  - read_last_bar() : retourne derniere bar (tail-follow + dedup par ts)
  - is_fresh() : check staleness (max age vs config DMP_BAR_MAX_AGE_SEC)
  - get_current_file() : trouve le JSONL le plus recent du jour
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from CORE.bot1_v2.config import Bot1V2Config


class SierraDataSource:
    """Tail-follow d'un JSONL sierra_enriched.

    Maintient un cache du dernier ts lu pour dedup.
    """

    def __init__(self, symbol: str, cfg: Optional[Bot1V2Config] = None):
        self.symbol = symbol.upper()
        self.cfg = cfg or Bot1V2Config.from_env()
        self.last_ts_seen: Optional[int] = None
        self._cached_path: Optional[Path] = None

    @property
    def data_dir(self) -> Path:
        """Repertoire des JSONL pour ce symbole."""
        try:
            from pathlib import Path
            root = Path(__file__).resolve().parents[2]
        except Exception:
            root = Path.cwd()
        return root / "DATA" / "live_enriched" / "sierra" / self.symbol

    def get_current_file(self) -> Optional[Path]:
        """Trouve le fichier JSONL le plus recent (par mtime).

        Returns None si aucun fichier.
        """
        d = self.data_dir
        if not d.exists() or not d.is_dir():
            return None
        candidates = list(d.glob("*_sierra_enriched.jsonl"))
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    def read_last_bar(self) -> Optional[dict]:
        """Lit la derniere bar du fichier le plus recent.

        Returns None si :
          - Aucun fichier
          - Fichier vide
          - Derniere bar = meme ts que precedente (pas de nouvelle bar)
        """
        path = self.get_current_file()
        if path is None:
            return None
        try:
            # Read last line (efficient : seek depuis fin)
            with open(path, "rb") as f:
                try:
                    f.seek(-2, os.SEEK_END)
                    while f.read(1) != b"\n":
                        f.seek(-2, os.SEEK_CUR)
                except OSError:
                    f.seek(0)
                last_line = f.readline().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None

        if not last_line.strip():
            return None

        try:
            bar = json.loads(last_line)
        except json.JSONDecodeError:
            return None

        bar_ts = bar.get("ts")
        if bar_ts is None:
            return None

        try:
            bar_ts = int(bar_ts)
        except (TypeError, ValueError):
            return None

        # Dedup : si meme ts que precedent = pas de nouvelle bar
        if self.last_ts_seen is not None and bar_ts <= self.last_ts_seen:
            return None

        self.last_ts_seen = bar_ts
        return bar

    def peek_last_bar(self) -> Optional[dict]:
        """Snapshot read-only de la derniere bar SANS modifier last_ts_seen.

        Usage : Bot MR IntermarketGate qui doit lire la bar du LEADER (ES) depuis
        une autre instance SierraDataSource sans consumer son curseur dedup.
        Sans cette methode, lire la bar ES via read_last_bar() avancerait
        last_ts_seen et bloquerait les futures lectures legitimes du leader.

        Returns:
            La derniere bar (meme si deja vue), None si fichier absent/vide/invalide.

        Side effects : AUCUN sur last_ts_seen (rollback systematique).
        """
        saved = self.last_ts_seen
        # Force re-lecture en bypassant le dedup
        self.last_ts_seen = None
        try:
            bar = self.read_last_bar()
        finally:
            # Restore l'etat precedent quel que soit le resultat
            self.last_ts_seen = saved
        return bar

    def is_fresh(self, bar: dict) -> tuple[bool, float]:
        """Verifie si la bar est fraiche (age <= DMP_BAR_MAX_AGE_SEC).

        Returns:
            (is_fresh, age_seconds)
        """
        bar_ts = bar.get("ts")
        if bar_ts is None:
            return False, float("inf")
        try:
            bar_ts_ms = int(bar_ts)
        except (TypeError, ValueError):
            return False, float("inf")
        now_ms = int(time.time() * 1000)
        age_sec = (now_ms - bar_ts_ms) / 1000.0
        return age_sec <= self.cfg.DMP_BAR_MAX_AGE_SEC, age_sec
