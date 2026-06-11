"""Tests Phase 0 V5 features (tod_bucket + week_of_month + opex + countdown)."""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# tod_bucket_rth
# ════════════════════════════════════════════════════════════════════════════

def test_tod_bucket_pre_rth():
    """mins_et < 570 (09:30 ET) -> bucket 0 (pre-RTH)."""
    from CORE.features_v5_phase0 import compute_tod_bucket_rth
    assert compute_tod_bucket_rth(0) == 0       # midnight ET
    assert compute_tod_bucket_rth(569) == 0     # 09:29 ET
    assert compute_tod_bucket_rth(500) == 0     # 08:20 ET


def test_tod_bucket_rth_open():
    """09:30 ET (mins_et=570) -> bucket 1 (premier 30min RTH)."""
    from CORE.features_v5_phase0 import compute_tod_bucket_rth
    assert compute_tod_bucket_rth(570) == 1     # 09:30
    assert compute_tod_bucket_rth(599) == 1     # 09:59


def test_tod_bucket_rth_mid_day():
    """Buckets RTH 30min cohherents."""
    from CORE.features_v5_phase0 import compute_tod_bucket_rth
    assert compute_tod_bucket_rth(600) == 2     # 10:00
    assert compute_tod_bucket_rth(630) == 3     # 10:30
    assert compute_tod_bucket_rth(900) == 12    # 15:00
    assert compute_tod_bucket_rth(930) == 13    # 15:30 (dernier bucket RTH)
    assert compute_tod_bucket_rth(959) == 13    # 15:59


def test_tod_bucket_post_rth():
    """mins_et >= 960 (16:00 ET) -> bucket 14 (post-RTH)."""
    from CORE.features_v5_phase0 import compute_tod_bucket_rth
    assert compute_tod_bucket_rth(960) == 14    # 16:00
    assert compute_tod_bucket_rth(1018) == 14   # 16:58 (bar Jackson)
    assert compute_tod_bucket_rth(1200) == 14   # 20:00


def test_tod_bucket_none_or_nan():
    """None ou NaN gracieux -> 0 (pas crash)."""
    from CORE.features_v5_phase0 import compute_tod_bucket_rth
    assert compute_tod_bucket_rth(None) == 0
    assert compute_tod_bucket_rth(float("nan")) == 0


# ════════════════════════════════════════════════════════════════════════════
# week_of_month
# ════════════════════════════════════════════════════════════════════════════

def test_week_of_month_first_week():
    """Jours 1-7 = semaine 1."""
    from CORE.features_v5_phase0 import compute_week_of_month
    assert compute_week_of_month(datetime(2026, 6, 1, tzinfo=timezone.utc)) == 1
    assert compute_week_of_month(datetime(2026, 6, 7, tzinfo=timezone.utc)) == 1


def test_week_of_month_second_week():
    """Jours 8-14 = semaine 2."""
    from CORE.features_v5_phase0 import compute_week_of_month
    assert compute_week_of_month(datetime(2026, 6, 8, tzinfo=timezone.utc)) == 2
    assert compute_week_of_month(datetime(2026, 6, 14, tzinfo=timezone.utc)) == 2


def test_week_of_month_opex_week():
    """Jours 15-21 = semaine 3 (OPEX)."""
    from CORE.features_v5_phase0 import compute_week_of_month
    assert compute_week_of_month(datetime(2026, 6, 15, tzinfo=timezone.utc)) == 3
    assert compute_week_of_month(datetime(2026, 6, 19, tzinfo=timezone.utc)) == 3  # 3e vendredi typique
    assert compute_week_of_month(datetime(2026, 6, 21, tzinfo=timezone.utc)) == 3


def test_week_of_month_fifth_week():
    """Jours 29-31 = semaine 5 (rare)."""
    from CORE.features_v5_phase0 import compute_week_of_month
    assert compute_week_of_month(datetime(2026, 6, 29, tzinfo=timezone.utc)) == 5
    assert compute_week_of_month(datetime(2026, 7, 31, tzinfo=timezone.utc)) == 5


# ════════════════════════════════════════════════════════════════════════════
# is_opex_week
# ════════════════════════════════════════════════════════════════════════════

def test_is_opex_week_true():
    """Jours 15-21 = OPEX week."""
    from CORE.features_v5_phase0 import compute_is_opex_week
    assert compute_is_opex_week(datetime(2026, 6, 15, tzinfo=timezone.utc)) is True
    assert compute_is_opex_week(datetime(2026, 6, 19, tzinfo=timezone.utc)) is True
    assert compute_is_opex_week(datetime(2026, 6, 21, tzinfo=timezone.utc)) is True


def test_is_opex_week_false():
    """Hors jours 15-21 = pas OPEX."""
    from CORE.features_v5_phase0 import compute_is_opex_week
    assert compute_is_opex_week(datetime(2026, 6, 1, tzinfo=timezone.utc)) is False
    assert compute_is_opex_week(datetime(2026, 6, 14, tzinfo=timezone.utc)) is False
    assert compute_is_opex_week(datetime(2026, 6, 22, tzinfo=timezone.utc)) is False
    assert compute_is_opex_week(datetime(2026, 6, 30, tzinfo=timezone.utc)) is False


# ════════════════════════════════════════════════════════════════════════════
# days_to_next_* (smoke tests + naive timestamp)
# ════════════════════════════════════════════════════════════════════════════

def test_compute_phase0_features_naive_raises():
    """Timestamp naive doit raise (anti DST hell, regle eco_calendar)."""
    from CORE.features_v5_phase0 import compute_phase0_features
    with pytest.raises(ValueError, match="tz-aware"):
        compute_phase0_features(now_utc=datetime(2026, 6, 12, 12, 0))  # naive


def test_compute_phase0_features_returns_all_keys():
    """API publique retourne 7 features cohherentes."""
    from CORE.features_v5_phase0 import compute_phase0_features
    out = compute_phase0_features(
        now_utc=datetime(2026, 6, 19, 14, 30, tzinfo=timezone.utc),
        mins_et=600,  # 10:00 ET
    )
    expected_keys = {
        "tod_bucket_rth", "week_of_month", "is_opex_week",
        "days_to_next_fomc", "days_to_next_nfp", "days_to_next_cpi",
        "days_to_next_critical_ev",
    }
    assert set(out.keys()) == expected_keys
    assert out["tod_bucket_rth"] == 2  # 10:00 ET
    assert out["week_of_month"] == 3   # day 19 = semaine 3
    assert out["is_opex_week"] is True # 19 in [15-21]


def test_days_to_next_fomc_returns_float_or_nan():
    """days_to_next_fomc retourne float (jours fractionnaires) ou NaN si rien cette semaine."""
    from CORE.features_v5_phase0 import compute_days_to_next_fomc
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    result = compute_days_to_next_fomc(now)
    # Soit float positif, soit NaN
    assert isinstance(result, float)
    # Pas de check valeur exacte (depend cache ForexFactory)


def test_days_to_next_nfp_returns_float_or_nan():
    from CORE.features_v5_phase0 import compute_days_to_next_nfp
    now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    result = compute_days_to_next_nfp(now)
    assert isinstance(result, float)


def test_empty_features_structure():
    """_empty_features() retourne 7 keys avec defaults sains."""
    from CORE.features_v5_phase0 import _empty_features
    out = _empty_features()
    assert out["tod_bucket_rth"] == 0
    assert out["week_of_month"] == 1
    assert out["is_opex_week"] is False
    assert math.isnan(out["days_to_next_fomc"])
    assert math.isnan(out["days_to_next_critical_ev"])


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
