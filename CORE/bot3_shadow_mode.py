"""CORE/bot3_shadow_mode.py - Shadow Mode Bot 3 v2 (Phase 3).

Module : logger parallele JSONL legacy vs narrative comparison.

Architecture : Phase 3 SHADOW MODE - aucune decision propagee.
But : tracker les divergences entre Bot 3 v1 legacy (side hardcoded au niveau)
et Bot 3 v2 narrative (DirectionResolver). Mesurer bidirectional ratio shadow.

Critere Phase 3 GO (cf master plan sect 268) :
  - Bidirectional ratio shadow >= 35% SHORT (vs 6.7% legacy Bot 3 v1)
  - n_divergences 30-60 sur 5 jours
  - Audit manuel 30 cases >= 50% defendable canon

Data source : pas de state, fonction pure log JSONL.

Created : 2026-05-18 by Jackson + Claude (Phase 3 J+2)
"""
# ─── HISTORY ──────────────────────────────────────────────────────────────
# 2026-05-18 PM : creation Phase 3 J+2 - logger JSONL parallele simple
# ──────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    from CORE.bot3_narrative_logging import emit
except ModuleNotFoundError:
    from bot3_narrative_logging import emit  # type: ignore[no-redef]


SHADOW_MODE_SCHEMA_VERSION: str = "3.0.0"


@dataclass
class ShadowComparison:
    """Comparaison legacy vs narrative pour 1 evaluation level touched."""
    ts: str
    symbol: str
    level_name: str
    level_nature: str
    narrative_state: str
    legacy_side: str           # Bot 3 v1 hardcoded side at level definition
    narrative_side: str        # Bot 3 v2 ResolvedDirection.side
    narrative_scenario_id: str
    narrative_confidence: float
    is_divergence: bool        # True si legacy != narrative (et narrative != NO_TRADE)


class ShadowModeLogger:
    """Logger JSONL parallele append-only thread-safe.

    Usage : logger.log_comparison(...) a chaque level evaluated par mp_engine.
    Append au fichier LOGS/bot3_v2/shadow_divergences_YYYYMMDD.jsonl.

    Phase 3 J+2 minimaliste : 1 fichier par jour, pas de rotation, pas de buffer.
    Phase 5+ : ajouter buffer batch flush pour latence prod.
    """

    def __init__(self, output_dir: str | Path = "LOGS/bot3_v2") -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock: threading.Lock = threading.Lock()

    def log_comparison(
        self,
        comparison: ShadowComparison,
        log_fn: Callable[..., None] | None = None,
    ) -> None:
        """Append 1 comparison JSONL. Emit BOT3_SHADOW_DIVERGENCE si divergence."""
        # Construct filename par jour (extract YYYYMMDD du ts)
        date_str = comparison.ts[:10].replace("-", "")  # "2026-05-18" → "20260518"
        path = self.output_dir / f"shadow_divergences_{date_str}.jsonl"

        record = {
            "ts": comparison.ts,
            "sym": comparison.symbol,
            "level": comparison.level_name,
            "nature": comparison.level_nature,
            "narrative_state": comparison.narrative_state,
            "legacy_side": comparison.legacy_side,
            "narrative_side": comparison.narrative_side,
            "scenario_id": comparison.narrative_scenario_id,
            "confidence": comparison.narrative_confidence,
            "divergence": comparison.is_divergence,
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"

        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)

        if comparison.is_divergence:
            emit(
                "BOT3_SHADOW_DIVERGENCE",
                log_fn=log_fn,
                sym=comparison.symbol,
                legacy_side=comparison.legacy_side,
                narrative_side=comparison.narrative_side,
                scenario_id=comparison.narrative_scenario_id,
            )


def detect_divergence(legacy_side: str, narrative_side: str) -> bool:
    """Pure function : legacy vs narrative diverge ?

    Divergence = sides opposes ET narrative pas NO_TRADE.
    NO_TRADE narrative != legacy LONG/SHORT = NOT divergence (narrative s'abstient).
    """
    if narrative_side == "NO_TRADE":
        return False
    return legacy_side != narrative_side
