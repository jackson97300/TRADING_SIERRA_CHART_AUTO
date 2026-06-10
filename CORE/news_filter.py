"""
News Blackout Filter — MIA V2

Bloque les entrees de trades pendant les fenetres d'annonces economiques HIGH
impact. Protection obligatoire selon Narang "Inside the Black Box" (ch.4 Risk).

Source calendar : stub JSON local pour le MVP. A remplacer par scraping Forex
Factory ou API TradingEconomics en Phase 2.

Fenetre blackout par defaut : 15 min AVANT + 15 min APRES chaque annonce HIGH.

Usage :
    nf = NewsBlackoutFilter(calendar_path="DATA/CALENDAR/eco_calendar.json")

    is_blocked, event = nf.is_blackout_now(pd.Timestamp.now(tz="UTC"))
    if is_blocked:
        print(f"Trade bloque : {event}")

    minutes = nf.minutes_until_next_high(pd.Timestamp.now(tz="UTC"))
    if minutes is not None and minutes < 5:
        print(f"Annonce dans {minutes} min — flatten positions")

Format attendu du calendar JSON :
    [
      {"ts_utc": "2026-04-14T12:30:00Z", "impact": "HIGH", "name": "CPI y/y", "currency": "USD"},
      {"ts_utc": "2026-04-14T14:00:00Z", "impact": "MEDIUM", "name": "Retail Sales", "currency": "USD"},
      ...
    ]

Auteur : MIA Trading System
Date   : 2026-04-14
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

import pandas as pd


DEFAULT_BLACKOUT_BEFORE_MIN = 15
DEFAULT_BLACKOUT_AFTER_MIN = 15
DEFAULT_IMPACTS_BLOCKING = ("HIGH",)
DEFAULT_CURRENCIES = ("USD",)


@dataclass
class EconomicEvent:
    ts_utc: pd.Timestamp
    impact: str
    name: str
    currency: str = "USD"


class NewsBlackoutFilter:
    """
    Filtre de blackout pour les annonces economiques.

    Charge un calendar JSON local, retourne True si le timestamp actuel est dans
    une fenetre de blackout (N min avant/apres une annonce HIGH impact).
    """

    def __init__(
        self,
        calendar_path: str | Path,
        before_min: int = DEFAULT_BLACKOUT_BEFORE_MIN,
        after_min: int = DEFAULT_BLACKOUT_AFTER_MIN,
        impacts_blocking: tuple[str, ...] = DEFAULT_IMPACTS_BLOCKING,
        currencies: tuple[str, ...] = DEFAULT_CURRENCIES,
    ):
        self.calendar_path = Path(calendar_path)
        self.before = timedelta(minutes=before_min)
        self.after = timedelta(minutes=after_min)
        self.impacts_blocking = set(impacts_blocking)
        self.currencies = set(currencies)
        self.events: list[EconomicEvent] = []
        self._load()

    def _load(self) -> None:
        if not self.calendar_path.exists():
            self.events = []
            return
        with open(self.calendar_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        parsed = []
        for e in raw:
            try:
                impact = e.get("impact", "").upper()
                currency = e.get("currency", "USD").upper()
                if impact not in self.impacts_blocking:
                    continue
                if currency not in self.currencies:
                    continue
                ts = pd.Timestamp(e["ts_utc"])
                if ts.tz is None:
                    ts = ts.tz_localize("UTC")
                else:
                    ts = ts.tz_convert("UTC")
                parsed.append(EconomicEvent(
                    ts_utc=ts,
                    impact=impact,
                    name=e.get("name", "Unknown"),
                    currency=currency,
                ))
            except (ValueError, KeyError, TypeError):
                continue
        parsed.sort(key=lambda x: x.ts_utc)
        self.events = parsed

    def reload(self) -> None:
        self._load()

    def is_blackout_now(self, ts: pd.Timestamp) -> tuple[bool, Optional[str]]:
        """Retourne (True, event_name) si `ts` est dans une fenetre de blackout.

        Convention d'intervalle : [start, end) — borne de fin exclusive pour eviter
        de double-compter les frontieres entre 2 events adjacents.

        Normalise systematiquement en UTC avant comparaison (naive → tz_localize,
        tz-aware non-UTC → tz_convert).
        """
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        for event in self.events:
            start = event.ts_utc - self.before
            end = event.ts_utc + self.after
            if start <= ts < end:
                return True, f"{event.name} ({event.impact})"
        return False, None

    def minutes_until_next_high(self, ts: pd.Timestamp) -> Optional[float]:
        """Retourne minutes jusqu'a la prochaine annonce HIGH, ou None si aucune."""
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        for event in self.events:
            if event.ts_utc > ts:
                delta = (event.ts_utc - ts).total_seconds() / 60.0
                return delta
        return None

    def next_event(self, ts: pd.Timestamp) -> Optional[EconomicEvent]:
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        for event in self.events:
            if event.ts_utc > ts:
                return event
        return None

    def events_in_window(
        self, start: pd.Timestamp, end: pd.Timestamp
    ) -> list[EconomicEvent]:
        if start.tz is None:
            start = start.tz_localize("UTC")
        if end.tz is None:
            end = end.tz_localize("UTC")
        return [e for e in self.events if start <= e.ts_utc <= end]


def filter_signals_by_news(
    signals: pd.DataFrame,
    news_filter: NewsBlackoutFilter,
    ts_col: str = "ts",
) -> pd.DataFrame:
    """
    Applique le news filter a un DataFrame de signaux backtestes.

    Version vectorisee via IntervalIndex — O(n log m) au lieu de O(n*m).
    """
    result = signals.copy()
    if not news_filter.events:
        result["news_blocked"] = False
        return result

    ts_series = pd.to_datetime(result[ts_col])
    if ts_series.dt.tz is None:
        ts_series = ts_series.dt.tz_localize("UTC")
    else:
        ts_series = ts_series.dt.tz_convert("UTC")

    starts = [e.ts_utc - news_filter.before for e in news_filter.events]
    ends = [e.ts_utc + news_filter.after for e in news_filter.events]
    intervals = pd.IntervalIndex.from_arrays(
        pd.to_datetime(starts), pd.to_datetime(ends), closed="left"
    )
    mask = intervals.get_indexer(ts_series) >= 0
    result.loc[mask, "signal"] = "HOLD"
    result["news_blocked"] = mask
    return result
