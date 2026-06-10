"""Tests Phase 3.7 eco_news_features.py (Sierra Migration 10/06/2026).

Mock eco_calendar pour tests deterministes (pas d'appel ForexFactory reseau).
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ────────────────────────────────────────────────────────────────────────────
# Helpers : mock status + next_event payloads
# ────────────────────────────────────────────────────────────────────────────

def _mock_status(
    eco_blocked: bool = False,
    session_blocked: bool = False,
) -> dict:
    return {
        "ts": "2026-06-10T15:30:00+00:00",
        "blocked": eco_blocked or session_blocked,
        "eco_blocked": eco_blocked,
        "session_blocked": session_blocked,
        "block_reason": None,
        "blocked_until_utc": None,
        "next_event": None,
        "today_events_count": 0,
        "cache_age_sec": 100,
    }


def _mock_next_event(in_seconds: int, is_critical: bool = False) -> dict:
    return {
        "title": "FOMC Press Conference" if is_critical else "Building Permits",
        "country": "USD",
        "impact": "High",
        "ts_utc": "2026-06-10T16:00:00+00:00",
        "in_seconds": in_seconds,
        "is_critical": is_critical,
    }


# ────────────────────────────────────────────────────────────────────────────
# Tests forward-looking windows
# ────────────────────────────────────────────────────────────────────────────

def test_event_dans_3min_active_5m_seulement():
    """Event dans 180s -> is_news_5m True, 15/30/60 True aussi (3min < 5,15,30,60)."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(180)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is True
    assert f["is_news_15m"] is True
    assert f["is_news_30m"] is True
    assert f["is_news_60m"] is True
    assert f["news_seconds_until"] == 180
    assert abs(f["news_minutes_until"] - 3.0) < 0.01


def test_event_dans_10min_active_15_30_60_pas_5():
    """Event dans 600s -> is_news_5m False, is_news_15m+30+60 True."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(600)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is False
    assert f["is_news_15m"] is True
    assert f["is_news_30m"] is True
    assert f["is_news_60m"] is True


def test_event_dans_45min_active_60_seulement():
    """Event dans 2700s (45min) -> is_news_60m True, autres False."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(2700)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is False
    assert f["is_news_15m"] is False
    assert f["is_news_30m"] is False
    assert f["is_news_60m"] is True


def test_event_dans_2h_aucune_fenetre_active():
    """Event dans 7200s (120min) -> aucune fenetre active."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(7200)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is False
    assert f["is_news_15m"] is False
    assert f["is_news_30m"] is False
    assert f["is_news_60m"] is False


def test_event_exactement_a_la_borne_5m():
    """Event dans 300s EXACT (= boundary 5min) -> is_news_5m True (inclusif).

    Boundary inclusive `0 <= in_sec <= window_sec` (nit 1 review batch 10/06).
    """
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(300)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is True, "in_sec=300 (5min exact) doit etre inclusif"


def test_event_a_zero_seconde_active_toutes_fenetres():
    """Event maintenant (in_sec=0) -> toutes is_news_*m True."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(0)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is True
    assert f["is_news_15m"] is True
    assert f["is_news_60m"] is True
    assert f["news_seconds_until"] == 0


def test_event_negative_in_sec_pas_compte():
    """in_sec < 0 (event passe juste apres parsing) -> aucune fenetre True.

    Defensive : next_event_block filtre normalement les past events, mais
    si race condition, in_sec < 0 doit retourner False (pas True comme bug
    potentiel si `<= window_sec` checke sans borne basse).
    """
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(-30)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is False
    assert f["is_news_60m"] is False


def test_aucun_event_upcoming_tout_false():
    """next_event=None -> toutes features False/NaN."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=None):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_news_5m"] is False
    assert f["is_news_60m"] is False
    assert f["is_critical_news_60m"] is False
    assert math.isnan(f["news_seconds_until"])
    assert math.isnan(f["news_minutes_until"])


# ────────────────────────────────────────────────────────────────────────────
# Tests is_critical_news_60m (FOMC, NFP, CPI)
# ────────────────────────────────────────────────────────────────────────────

def test_event_critical_dans_30min_active_critical_60m():
    """Event critical (FOMC) dans 1800s -> is_critical_news_60m True."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block",
                       return_value=_mock_next_event(1800, is_critical=True)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_critical_news_60m"] is True
    assert f["is_news_60m"] is True


def test_event_non_critical_dans_30min_pas_critical():
    """Event non-critical dans 1800s -> is_critical_news_60m False (mais is_news_60m True)."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block",
                       return_value=_mock_next_event(1800, is_critical=False)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_critical_news_60m"] is False
    assert f["is_news_60m"] is True


def test_event_critical_dans_2h_pas_dans_fenetre_60m():
    """Event critical dans 7200s (au-dela 60m) -> is_critical_news_60m False."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block",
                       return_value=_mock_next_event(7200, is_critical=True)):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_critical_news_60m"] is False


# ────────────────────────────────────────────────────────────────────────────
# Tests is_*_blocked (etat actuel)
# ────────────────────────────────────────────────────────────────────────────

def test_eco_blocked_propage():
    """status eco_blocked=True -> is_eco_blocked True + is_blocked_combined True."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status(eco_blocked=True)), \
         patch.object(enf, "next_event_block", return_value=None):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_eco_blocked"] is True
    assert f["is_blocked_combined"] is True
    assert f["is_session_blocked"] is False


def test_session_blocked_propage():
    """status session_blocked=True -> is_session_blocked True + is_blocked_combined True."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status",
                       return_value=_mock_status(session_blocked=True)), \
         patch.object(enf, "next_event_block", return_value=None):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_session_blocked"] is True
    assert f["is_blocked_combined"] is True
    assert f["is_eco_blocked"] is False


def test_aucun_block_actif():
    """Aucun blocage -> tous is_*_blocked False."""
    from CORE import eco_news_features as enf

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=None):
        f = enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30, tzinfo=timezone.utc))

    assert f["is_eco_blocked"] is False
    assert f["is_session_blocked"] is False
    assert f["is_blocked_combined"] is False


# ────────────────────────────────────────────────────────────────────────────
# Tests defensive : ts naive interdit (FAIL LOUD)
# ────────────────────────────────────────────────────────────────────────────

def test_naive_datetime_raises():
    """ts naive (sans tz) -> ValueError FAIL LOUD anti DST hell."""
    from CORE import eco_news_features as enf

    with pytest.raises(ValueError, match="tz-aware"):
        enf.compute_eco_news_features(datetime(2026, 6, 10, 15, 30))


# ────────────────────────────────────────────────────────────────────────────
# Tests batch mode
# ────────────────────────────────────────────────────────────────────────────

def test_batch_mode_dataframe():
    """compute_eco_news_features_batch sur DataFrame."""
    from CORE import eco_news_features as enf

    df = pd.DataFrame({
        "ts_utc": [
            "2026-06-10T15:30:00+00:00",
            "2026-06-10T15:31:00+00:00",
            "2026-06-10T15:32:00+00:00",
        ],
    })

    # Mock retourne event dans 300s constant
    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(300)):
        result = enf.compute_eco_news_features_batch(df)

    assert "is_news_5m" in result.columns
    assert "is_blocked_combined" in result.columns
    assert all(result["is_news_5m"])
    assert all(result["news_seconds_until"] == 300)


def test_batch_missing_column_raises():
    """Missing ts_col -> ValueError."""
    from CORE import eco_news_features as enf

    df = pd.DataFrame({"other": [1, 2]})
    with pytest.raises(ValueError, match="manquante"):
        enf.compute_eco_news_features_batch(df)


def test_batch_nan_timestamp_handled():
    """NaN dans ts_utc -> empty features (False/NaN), pas crash."""
    from CORE import eco_news_features as enf

    df = pd.DataFrame({"ts_utc": [None, "2026-06-10T15:30:00+00:00"]})

    with patch.object(enf, "get_status", return_value=_mock_status()), \
         patch.object(enf, "next_event_block", return_value=_mock_next_event(300)):
        result = enf.compute_eco_news_features_batch(df)

    # Premiere ligne (NaN) : empty features
    assert result["is_news_5m"].iloc[0] == False
    assert math.isnan(result["news_seconds_until"].iloc[0])
    # Seconde ligne : computed
    assert result["is_news_5m"].iloc[1] == True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
