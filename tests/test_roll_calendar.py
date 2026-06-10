"""Tests Phase 3.6 roll_calendar.py (Sierra Migration 10/06/2026)."""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


def test_es_nq_roll_dates_2026():
    """ES/NQ rolls 2026 : 20/03, 19/06, 18/09, 18/12 (3e vendredi Mar/Jun/Sep/Dec)."""
    from CORE.roll_calendar import get_roll_dates_es_nq

    rolls = get_roll_dates_es_nq(2026)
    assert rolls == [
        date(2026, 3, 20),
        date(2026, 6, 19),
        date(2026, 9, 18),
        date(2026, 12, 18),
    ], f"Roll dates 2026 attendus, obtenu {rolls}"


def test_es_nq_roll_dates_2025():
    """ES/NQ rolls 2025 : 21/03, 20/06, 19/09, 19/12."""
    from CORE.roll_calendar import get_roll_dates_es_nq

    rolls = get_roll_dates_es_nq(2025)
    assert rolls == [
        date(2025, 3, 21),
        date(2025, 6, 20),
        date(2025, 9, 19),
        date(2025, 12, 19),
    ]


def test_mgc_roll_dates_2026():
    """MGC rolls 2026 : G/J/M/Q/V/Z = mois 2/4/6/8/10/12 (3e jeudi)."""
    from CORE.roll_calendar import get_roll_dates_mgc

    rolls = get_roll_dates_mgc(2026)
    assert len(rolls) == 6
    # Verifier que tous sont des jeudis
    for r in rolls:
        assert r.weekday() == 3, f"{r} doit etre un jeudi"
    # Premiers : Feb (G), Apr (J)
    assert rolls[0].month == 2
    assert rolls[1].month == 4
    assert rolls[5].month == 12


def test_is_roll_day_exact():
    """is_roll_day = True le jour exact du roll."""
    from CORE.roll_calendar import compute_roll_features

    # 19 juin 2026 = roll NQ
    features = compute_roll_features(date(2026, 6, 19), "NQ")
    assert features["is_roll_day"] is True
    assert features["roll_phase"] == 0
    assert features["days_since_roll"] == 0


def test_is_roll_day_off():
    """is_roll_day = False jours hors roll."""
    from CORE.roll_calendar import compute_roll_features

    features = compute_roll_features(date(2026, 6, 18), "NQ")  # veille
    assert features["is_roll_day"] is False


def test_days_since_roll_increases():
    """days_since_roll s'incremente jour apres jour."""
    from CORE.roll_calendar import compute_roll_features

    # Apres roll 20/03/2026
    f1 = compute_roll_features(date(2026, 3, 20), "NQ")
    f2 = compute_roll_features(date(2026, 3, 21), "NQ")
    f3 = compute_roll_features(date(2026, 4, 1), "NQ")

    assert f1["days_since_roll"] == 0
    assert f2["days_since_roll"] == 1
    assert f3["days_since_roll"] == 12


def test_roll_phase_minus_1_pre_roll():
    """roll_phase = -1 dans la fenetre pre-roll (5 jours avant)."""
    from CORE.roll_calendar import compute_roll_features

    # 5 jours avant 19/06/2026 = 14/06 (samedi). 4 jours = 15/06 lundi (-1).
    # Plus simple : 16/06 mardi (3 jours avant 19/06 vendredi) -> phase=-1
    f = compute_roll_features(date(2026, 6, 16), "NQ")
    assert f["roll_phase"] == -1


def test_roll_phase_zero_at_roll_and_j_plus_1():
    """roll_phase = 0 le jour roll ET J+1 (transition)."""
    from CORE.roll_calendar import compute_roll_features

    f_jour = compute_roll_features(date(2026, 6, 19), "NQ")
    f_j_plus_1 = compute_roll_features(date(2026, 6, 20), "NQ")  # samedi

    assert f_jour["roll_phase"] == 0
    assert f_j_plus_1["roll_phase"] == 0


def test_roll_phase_plus_1_post_roll_stable():
    """roll_phase = +1 regime stable post-roll (> J+1 et > 5 jours avant prochain)."""
    from CORE.roll_calendar import compute_roll_features

    # 1er avril 2026 : 12 jours apres roll 20/03 et 79 jours avant 19/06
    f = compute_roll_features(date(2026, 4, 1), "NQ")
    assert f["roll_phase"] == 1


def test_year_1_lookback_couvre_q1_premier_jour_annee():
    """1er janvier : year-1 lookback couvre dernier roll Dec annee precedente.

    NOTE : cold-start strict (avant 1er roll connu) IMPOSSIBLE en pratique
    car compute_roll_features inclut year-1 + year + year+1 dans roll_dates.
    Test renomme + objectif clarifie (fix review code-reviewer 10/06 :
    ancien `test_cold_start` faux test, assertion triviale).
    """
    from CORE.roll_calendar import compute_roll_features, get_roll_dates_es_nq

    f = compute_roll_features(date(2026, 1, 1), "NQ")
    # 1er janvier 2026 : dernier roll = 18/12/2025 (3e vendredi Dec 2025)
    last_roll_2025 = get_roll_dates_es_nq(2025)[-1]
    expected_days = (date(2026, 1, 1) - last_roll_2025).days

    assert f["days_since_roll"] == expected_days, (
        f"1er janvier doit voir dec annee precedente, "
        f"attendu {expected_days}, obtenu {f['days_since_roll']}"
    )
    # 1er janvier = 14 jours apres 18/12 -> phase=+1 stable
    # (> POST_ROLL_TRANSITION_DAYS=1 et next roll 20/03/2026 dans 78 jours > PRE_ROLL_DAYS=5)
    assert f["roll_phase"] == 1, (
        f"1er janvier dans regime stable post-roll, obtenu {f['roll_phase']}"
    )


def test_batch_mode_dataframe():
    """compute_roll_features_batch sur DataFrame."""
    from CORE.roll_calendar import compute_roll_features_batch

    df = pd.DataFrame({
        "session_date": [
            "2026-06-19",  # roll day
            "2026-06-20",  # J+1
            "2026-04-01",  # post-roll stable
            "2026-06-16",  # pre-roll
        ],
    })
    result = compute_roll_features_batch(df, "NQ")

    # Cast explicite (pandas peut retourner np.bool_) - fix review 10/06
    assert bool(result["is_roll_day"].iloc[0]) is True
    assert result["roll_phase"].iloc[0] == 0
    assert result["roll_phase"].iloc[1] == 0  # J+1 transition
    assert result["roll_phase"].iloc[2] == 1  # stable
    assert result["roll_phase"].iloc[3] == -1  # pre-roll


def test_batch_missing_column_raises():
    """Missing date_col -> ValueError."""
    from CORE.roll_calendar import compute_roll_features_batch

    df = pd.DataFrame({"other": [1, 2]})
    with pytest.raises(ValueError, match="manquante"):
        compute_roll_features_batch(df)


def test_unknown_symbol_raises_value_error():
    """Symbol inconnu -> ValueError FAIL LOUD (fix silent fallback review 10/06).

    Ancien test documentait une dette (`roll_phase=0` sur symbol inconnu = faux
    signal roll-day). Refactor en fail-loud anti-pattern data-quality.md.
    """
    from CORE.roll_calendar import compute_roll_features

    with pytest.raises(ValueError, match="symbol inconnu"):
        compute_roll_features(date(2026, 6, 19), "UNKNOWN")


def test_unknown_symbol_btc_raises():
    """Verifier que le fail-loud s'applique aussi aux symboles plausibles non-CME."""
    from CORE.roll_calendar import compute_roll_features

    with pytest.raises(ValueError, match="BTC"):
        compute_roll_features(date(2026, 6, 19), "BTC")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
