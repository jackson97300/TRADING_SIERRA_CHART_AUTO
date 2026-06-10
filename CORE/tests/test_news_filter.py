"""
Tests unitaires pour CORE/news_filter.py — MIA V2
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from CORE.news_filter import NewsBlackoutFilter, filter_signals_by_news


@pytest.fixture
def calendar_file(tmp_path):
    events = [
        {"ts_utc": "2026-04-14T12:30:00Z", "impact": "HIGH", "name": "CPI y/y", "currency": "USD"},
        {"ts_utc": "2026-04-14T14:00:00Z", "impact": "HIGH", "name": "Retail Sales", "currency": "USD"},
        {"ts_utc": "2026-04-14T15:30:00Z", "impact": "MEDIUM", "name": "Fed Speak", "currency": "USD"},
    ]
    f = tmp_path / "cal.json"
    f.write_text(json.dumps(events))
    return f


class TestNewsBlackoutFilter:

    def test_is_blackout_exact_start_boundary(self, calendar_file):
        """Test : ts == event - 15min → True (debut inclusif)."""
        nf = NewsBlackoutFilter(calendar_file, before_min=15, after_min=15)
        ts = pd.Timestamp("2026-04-14T12:15:00Z")  # 15 min avant CPI
        is_blocked, _ = nf.is_blackout_now(ts)
        assert is_blocked

    def test_is_blackout_exact_end_boundary(self, calendar_file):
        """Test : ts == event + 15min → False (fin exclusive, convention [start, end))."""
        nf = NewsBlackoutFilter(calendar_file, before_min=15, after_min=15)
        ts = pd.Timestamp("2026-04-14T12:45:00Z")  # exactement +15 min apres CPI
        is_blocked, _ = nf.is_blackout_now(ts)
        assert not is_blocked, "End boundary should be exclusive"

    def test_is_blackout_outside_window(self, calendar_file):
        """Test : ts bien en dehors de toute fenetre → False."""
        nf = NewsBlackoutFilter(calendar_file, before_min=15, after_min=15)
        ts = pd.Timestamp("2026-04-14T10:00:00Z")  # 2h30 avant CPI
        is_blocked, _ = nf.is_blackout_now(ts)
        assert not is_blocked

    def test_naive_timestamp_input(self, calendar_file):
        """Test : ts naive → soit assume UTC, soit raise explicitement."""
        nf = NewsBlackoutFilter(calendar_file)
        ts_naive = pd.Timestamp("2026-04-14 12:30:00")  # pas de tz
        # Accepter le comportement : assume UTC
        is_blocked, _ = nf.is_blackout_now(ts_naive)
        assert is_blocked  # 12:30 est au milieu du blackout CPI

    def test_corrupted_calendar_skips_event(self, tmp_path):
        """Test : event malforme dans le JSON → skip, les autres events restent."""
        events = [
            {"ts_utc": "2026-04-14T12:30:00Z", "impact": "HIGH", "name": "CPI", "currency": "USD"},
            {"ts_utc": "INVALID_DATE", "impact": "HIGH", "name": "Bad", "currency": "USD"},
            {"ts_utc": "2026-04-14T14:00:00Z", "impact": "HIGH", "name": "Retail", "currency": "USD"},
        ]
        f = tmp_path / "cal.json"
        f.write_text(json.dumps(events))
        nf = NewsBlackoutFilter(f)
        # Le loader doit skipper le bad event sans crash
        assert len(nf.events) == 2

    def test_empty_calendar_file_missing(self, tmp_path):
        """Test : fichier absent → events=[], pas de crash."""
        nf = NewsBlackoutFilter(tmp_path / "missing.json")
        assert nf.events == []
        ts = pd.Timestamp("2026-04-14T12:30:00Z")
        is_blocked, _ = nf.is_blackout_now(ts)
        assert not is_blocked
