"""Tests Phase 3.3.5 session_utils.py (Sierra Migration 10/06/2026)."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))

ET = ZoneInfo("America/New_York")


def test_utc_to_et_naive_raises():
    """ts naive -> ValueError FAIL LOUD."""
    from CORE.session_utils import utc_to_et

    with pytest.raises(ValueError, match="tz-aware"):
        utc_to_et(datetime(2026, 6, 10, 14, 0))


def test_utc_to_et_summer_edt():
    """Ete : EDT = UTC-4."""
    from CORE.session_utils import utc_to_et

    # 10 juin 2026 18:00 UTC = 14:00 EDT
    ts_utc = datetime(2026, 6, 10, 18, 0, tzinfo=timezone.utc)
    ts_et = utc_to_et(ts_utc)
    assert ts_et.hour == 14
    assert ts_et.minute == 0


def test_utc_to_et_winter_est():
    """Hiver : EST = UTC-5."""
    from CORE.session_utils import utc_to_et

    # 10 janvier 2026 19:00 UTC = 14:00 EST
    ts_utc = datetime(2026, 1, 10, 19, 0, tzinfo=timezone.utc)
    ts_et = utc_to_et(ts_utc)
    assert ts_et.hour == 14


def test_compute_trading_date_avant_18h_et():
    """Avant 18:00 ET -> trading_date = jour civil ET."""
    from CORE.session_utils import compute_trading_date

    ts_et = datetime(2026, 6, 10, 14, 0, tzinfo=ET)
    assert compute_trading_date(ts_et) == date(2026, 6, 10)


def test_compute_trading_date_apres_18h_et():
    """Apres 18:00 ET -> trading_date = J+1."""
    from CORE.session_utils import compute_trading_date

    ts_et = datetime(2026, 6, 10, 19, 0, tzinfo=ET)
    assert compute_trading_date(ts_et) == date(2026, 6, 11)


def test_compute_trading_date_boundary_18h_exact():
    """18:00 ET EXACT -> trading_date = J+1 (boundary inclusive)."""
    from CORE.session_utils import compute_trading_date

    ts_et = datetime(2026, 6, 10, 18, 0, tzinfo=ET)
    assert compute_trading_date(ts_et) == date(2026, 6, 11)


def test_compute_trading_date_vendredi_soir_samedi():
    """Vendredi 19:00 ET -> trading_date = samedi (week-end CME OK).

    Documentation : pendant le week-end, trading_date peut etre samedi/dimanche
    meme si marche CME ferme. Volontaire.
    """
    from CORE.session_utils import compute_trading_date

    # Vendredi 13 fevrier 2026 19:00 ET
    ts_et = datetime(2026, 2, 13, 19, 0, tzinfo=ET)
    assert compute_trading_date(ts_et) == date(2026, 2, 14)  # samedi


def test_get_trading_date_from_utc_helper():
    """Helper UTC -> ET -> trading_date en 1 etape."""
    from CORE.session_utils import get_trading_date_from_utc

    # 10 juin 2026 23:00 UTC = 19:00 EDT = trading_date J+1
    ts_utc = datetime(2026, 6, 10, 23, 0, tzinfo=timezone.utc)
    assert get_trading_date_from_utc(ts_utc) == date(2026, 6, 11)


def test_get_trading_date_from_utc_naive_raises():
    """Helper propage le FAIL LOUD naive."""
    from CORE.session_utils import get_trading_date_from_utc

    with pytest.raises(ValueError, match="tz-aware"):
        get_trading_date_from_utc(datetime(2026, 6, 10, 14, 0))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
