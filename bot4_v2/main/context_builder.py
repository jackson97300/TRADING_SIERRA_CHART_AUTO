"""Bot 4 v2 context_builder — Compose regime + narrative + menthorq pour ScenarioContext.

Module NEW Phase P5.3.A (26/06/2026) — Wiring critique entry point bot_main_v2.

Responsabilites strictes (SRP) :
- `build_scenario_context(bar, symbol)` -> ScenarioContext
- Compose les 3 sources isolees P2 :
  * regime_source.compute_regime(bar) -> RegimeAnalysis
  * narrative_engine.build_narrative_context(bar) -> NarrativeContext
  * menthorq_source.load_menthorq_levels(base_dir, symbol, date) -> MenthorQLevels (cache daily)

Pattern usage :
    builder = MenthorQCachedBuilder(menthorq_dir=Path("DATA/MENTHORQ"))
    ctx = builder.build(bar={...}, symbol="NQ")
    # ctx = ScenarioContext compatible router.route_bar(ctx)

EXCLU scope (backlog) :
- Multi-symbol context aggregation cross-instrument (cf cross-instrument trap scenario P3 batch suivant)
- Regime smoothing fenetres glissantes (regime_source.compute_regime stateless = single bar)

Garde-fous :
- Frozen MenthorQ cache (anti-mutation)
- Fail-soft date parsing (utilise bar.ts_event_ns OR ts string)
- Logs traceability via emit_safe (regle souveraine)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from bot4_v2.core.menthorq_source import (
    MenthorQLevels,
    load_menthorq_levels,
)
from bot4_v2.core.narrative_engine import build_narrative_context
from bot4_v2.core.regime_source import compute_regime
from bot4_v2.decision.scenario_registry import ScenarioContext
from bot4_v2.observability.telemetry import emit_safe, get_logger

_LOG = get_logger(__name__)


# ============================================================
# DATE EXTRACTION (fail-soft multi-format)
# ============================================================


_DATE_REGEX_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
)


def extract_date_str(bar: dict) -> str:
    """Extrait date YYYYMMDD du bar.

    Multi-format defensive :
    1. `ts_event` ISO 8601 (preferred) : "2026-06-26T14:00:00Z"
    2. `ts` ISO 8601
    3. `ts_event_ns` epoch nanoseconds
    4. Fallback : UTC today
    """
    for ts_key in ("ts_event", "ts"):
        ts_str = bar.get(ts_key)
        if isinstance(ts_str, str):
            match = _DATE_REGEX_ISO.match(ts_str)
            if match:
                return f"{match.group(1)}{match.group(2)}{match.group(3)}"

    ts_ns = bar.get("ts_event_ns")
    if isinstance(ts_ns, (int, float)) and ts_ns > 0:
        try:
            dt = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
            return dt.strftime("%Y%m%d")
        except (ValueError, OSError):
            pass

    # Fallback UTC today (sera log warning si arrive ici)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    _LOG.warning(
        "context_builder: extract_date_str fallback today=%s (bar missing ts)",
        today,
    )
    return today


# ============================================================
# MENTHORQ CACHE (daily reload)
# ============================================================


@dataclass(frozen=True)
class _MenthorQCacheEntry:
    """Entry cache MenthorQ (1 par date_str + symbol)."""

    date_str: str
    symbol: str
    levels: MenthorQLevels


class MenthorQCache:
    """Cache MenthorQ niveaux par (symbol, date).

    Reload automatique au changement de date. Cap defensif 30 entries
    (rolling window cross-symbol cross-date).
    """

    DEFAULT_CAP = 30

    def __init__(
        self,
        menthorq_dir: Path,
        cap: int = DEFAULT_CAP,
        loader: Optional[Callable[..., MenthorQLevels]] = None,
    ):
        self._dir = Path(menthorq_dir)
        self._cap = cap
        self._cache: dict[tuple[str, str], _MenthorQCacheEntry] = {}
        # Injectable pour tests (stub loader). Defaut = real loader.
        self._loader = loader or load_menthorq_levels

    @property
    def n_cached(self) -> int:
        return len(self._cache)

    def get(self, symbol: str, date_str: str) -> MenthorQLevels:
        """Retourne MenthorQLevels pour (symbol, date). Cache + fail-soft."""
        key = (symbol.upper(), date_str)
        if key in self._cache:
            return self._cache[key].levels

        # Load via injected loader (default = load_menthorq_levels)
        try:
            levels = self._loader(
                base_dir=self._dir, symbol=symbol, date_str=date_str,
            )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning(
                "context_builder: menthorq load fail symbol=%s date=%s exc=%s",
                symbol, date_str, type(exc).__name__,
            )
            # Fail-soft : retourne empty levels
            levels = MenthorQLevels(
                symbol=symbol.upper(), date_str=date_str, is_empty=True,
            )

        # Eviction FIFO si cap atteint
        if len(self._cache) >= self._cap:
            evicted_key = next(iter(self._cache))
            del self._cache[evicted_key]

        self._cache[key] = _MenthorQCacheEntry(
            date_str=date_str, symbol=key[0], levels=levels,
        )
        return levels

    def clear(self) -> None:
        """Force reload au prochain get (hot-reload P6 / tests)."""
        self._cache.clear()


# ============================================================
# CONTEXT BUILDER (composer principal)
# ============================================================


class ContextBuilder:
    """Composer ScenarioContext depuis bar dict + cache MenthorQ.

    Pattern usage entry point :
        builder = ContextBuilder(menthorq_dir=Path("DATA/MENTHORQ"))
        # Injecte dans BotMainLoop via lambda :
        loop = BotMainLoop(
            ..., context_builder=lambda bar, sym: builder.build(bar, sym),
        )

    SRP : compose APIs P2 (regime + narrative + menthorq) en ScenarioContext.
    PAS de regime computing custom, PAS de scenario logic, PAS de logic broker.
    """

    def __init__(
        self,
        menthorq_dir: Path,
        menthorq_cache: Optional[MenthorQCache] = None,
    ):
        """Init builder.

        Args:
            menthorq_dir : repertoire JSON MenthorQ (DATA/MENTHORQ/).
            menthorq_cache : injection pour tests. Defaut = nouveau MenthorQCache.
        """
        self._mq_dir = Path(menthorq_dir)
        self._mq_cache = menthorq_cache or MenthorQCache(menthorq_dir)

    @property
    def menthorq_cache(self) -> MenthorQCache:
        return self._mq_cache

    def build(self, bar: dict, symbol: str) -> ScenarioContext:
        """Compose ScenarioContext depuis bar + symbol.

        Args:
            bar : bar JSONL live_enriched dict (features completes)
            symbol : "NQ" / "ES" / "MGC" / ... (upper case enforce)

        Returns:
            ScenarioContext immutable, pret pour router.route_bar(ctx).

        Raises:
            Pas d'exception explicite (fail-soft via load_menthorq_levels +
            compute_regime + build_narrative_context handle errors internally).
        """
        sym = symbol.upper()
        # Injection symbol dans bar. narrative_engine lit `sym` (cf
        # narrative_engine.py:658,689). regime_source lit features, pas symbol.
        # On set les 2 clefs pour compat downstream.
        bar_enriched = dict(bar)
        bar_enriched["sym"] = sym
        bar_enriched.setdefault("symbol", sym)

        # 1. Regime (single bar, stateless)
        regime = compute_regime(bar_enriched)

        # 2. Narrative (single bar avec features deja dans bar)
        narrative = build_narrative_context(bar_enriched)

        # 3. MenthorQ (daily file, cache)
        date_str = extract_date_str(bar_enriched)
        menthorq = self._mq_cache.get(symbol=sym, date_str=date_str)

        return ScenarioContext(
            bar=bar_enriched,
            regime=regime,
            narrative=narrative,
            menthorq=menthorq,
        )
