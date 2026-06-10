"""test_banner_utils.py — Tests centralisation lecture banner ts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from CORE.banner_utils import read_banner_ts_ms, compute_last_bar_age_sec


class TestReadBannerTsMs:
    def test_new_schema_ts(self):
        b = {"ts": 1778231519000.0, "price": 28857.25}
        assert read_banner_ts_ms(b) == 1778231519000.0

    def test_old_schema_ts_ms(self):
        b = {"ts_ms": 1778231519000.0, "price": 28857.25}
        assert read_banner_ts_ms(b) == 1778231519000.0

    def test_old_schema_bar_ts_ms(self):
        b = {"bar_ts_ms": 1778231519000.0, "price": 28857.25}
        assert read_banner_ts_ms(b) == 1778231519000.0

    def test_priority_ts_over_aliases(self):
        """Si plusieurs alias presents, ts gagne (nouveau schema)."""
        b = {"ts": 100, "ts_ms": 200, "bar_ts_ms": 300}
        assert read_banner_ts_ms(b) == 100.0

    def test_empty_dict(self):
        assert read_banner_ts_ms({}) is None

    def test_none_input(self):
        assert read_banner_ts_ms(None) is None

    def test_non_dict_input(self):
        assert read_banner_ts_ms("not a dict") is None
        assert read_banner_ts_ms([1, 2, 3]) is None

    def test_zero_value_falsy_falls_through(self):
        """ts=0 = pas de bar (souvent 0 par defaut). Doit retourner None."""
        b = {"ts": 0}
        assert read_banner_ts_ms(b) is None

    def test_invalid_value_skipped(self):
        """ts non numerique -> skip puis fallback alias."""
        b = {"ts": "garbage", "ts_ms": 1778231519000.0}
        assert read_banner_ts_ms(b) == 1778231519000.0


class TestComputeLastBarAgeSec:
    def test_fresh_bar_returns_age(self):
        now_ms = 1778231600000.0  # 80s apres
        banner = {"es": {"ts": 1778231520000.0}, "nq": {"ts": 1778231580000.0}}
        age = compute_last_bar_age_sec(banner, now_ms)
        assert 78 <= age <= 82  # NQ age ~20s, ES age ~80s -> max = 80s

    def test_no_bars_returns_fallback(self):
        now_ms = 1778231600000.0
        banner = {"es": {}, "nq": {}}
        age = compute_last_bar_age_sec(banner, now_ms)
        assert age == 99999.0

    def test_old_schema_compat(self):
        """Bot legacy banner avec ts_ms doit etre lu correctement."""
        now_ms = 1778231600000.0
        banner = {"es": {"ts_ms": 1778231570000.0}, "nq": {"bar_ts_ms": 1778231590000.0}}
        age = compute_last_bar_age_sec(banner, now_ms)
        assert 28 <= age <= 32

    def test_outlier_clamp(self):
        """ts trop loin dans le futur ou passe (>24h) ignored."""
        now_ms = 1778231600000.0
        banner = {"es": {"ts": 1000000000000.0}}  # tres vieux
        age = compute_last_bar_age_sec(banner, now_ms)
        assert age == 99999.0  # clamp filtre l'ES, NQ absent -> fallback

    def test_negative_age_skipped(self):
        """ts dans le futur (>now) -> age negatif -> skipped."""
        now_ms = 1778231600000.0
        banner = {"es": {"ts": 1778231700000.0}}  # 100s dans le futur
        age = compute_last_bar_age_sec(banner, now_ms)
        assert age == 99999.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
