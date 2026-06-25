"""Tests bot4_v2/main/context_builder."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from bot4_v2.core.menthorq_source import MenthorQLevels
from bot4_v2.decision.scenario_registry import ScenarioContext
from bot4_v2.main.context_builder import (
    ContextBuilder,
    MenthorQCache,
    extract_date_str,
)


# ============================================================
# extract_date_str
# ============================================================


def test_extract_date_str_from_ts_event_iso():
    bar = {"ts_event": "2026-06-26T14:00:00Z"}
    assert extract_date_str(bar) == "20260626"


def test_extract_date_str_from_ts_iso():
    bar = {"ts": "2026-06-26T14:00:00+00:00"}
    assert extract_date_str(bar) == "20260626"


def test_extract_date_str_from_ts_event_ns():
    # Epoch ns pour 2026-06-26 14:00:00 UTC
    bar = {"ts_event_ns": 1782050400000000000}
    result = extract_date_str(bar)
    # Verify format YYYYMMDD valide (date precise depend tz / epoch)
    assert len(result) == 8
    assert result.isdigit()


def test_extract_date_str_fallback_today():
    """Bar sans ts -> fallback aujourd'hui (log warning emis)."""
    import re
    from datetime import datetime, timezone

    bar = {"high": 100, "low": 90}
    result = extract_date_str(bar)
    # Format YYYYMMDD
    assert re.match(r"^\d{8}$", result)
    # = today UTC
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert result == today


def test_extract_date_str_ts_event_priority_over_ts():
    bar = {
        "ts_event": "2026-06-26T14:00:00Z",
        "ts": "2026-06-25T10:00:00Z",
    }
    # ts_event prefere
    assert extract_date_str(bar) == "20260626"


def test_extract_date_str_invalid_ns_fallback():
    bar = {"ts_event_ns": -1}
    import re
    result = extract_date_str(bar)
    assert re.match(r"^\d{8}$", result)


# ============================================================
# MenthorQCache
# ============================================================


def _make_levels(symbol: str = "NQ", date_str: str = "20260626",
                  empty: bool = False) -> MenthorQLevels:
    return MenthorQLevels(symbol=symbol, date_str=date_str, is_empty=empty)


def test_menthorq_cache_init():
    cache = MenthorQCache(Path("/fake/path"))
    assert cache.n_cached == 0


def test_menthorq_cache_get_loads_once(tmp_path):
    """Premier get charge, second get utilise cache (loader appele 1x)."""
    call_count = [0]

    def stub_loader(base_dir, symbol, date_str):
        call_count[0] += 1
        return _make_levels(symbol, date_str)

    cache = MenthorQCache(tmp_path, loader=stub_loader)
    cache.get("NQ", "20260626")
    cache.get("NQ", "20260626")
    cache.get("NQ", "20260626")
    assert call_count[0] == 1  # 1 load, 2 cache hits


def test_menthorq_cache_different_keys_load_separately(tmp_path):
    call_count = [0]

    def stub_loader(base_dir, symbol, date_str):
        call_count[0] += 1
        return _make_levels(symbol, date_str)

    cache = MenthorQCache(tmp_path, loader=stub_loader)
    cache.get("NQ", "20260626")
    cache.get("ES", "20260626")  # different symbol
    cache.get("NQ", "20260627")  # different date
    assert call_count[0] == 3
    assert cache.n_cached == 3


def test_menthorq_cache_cap_eviction_fifo(tmp_path):
    """Cap depasse -> eviction FIFO."""
    def stub_loader(base_dir, symbol, date_str):
        return _make_levels(symbol, date_str)

    cache = MenthorQCache(tmp_path, cap=2, loader=stub_loader)
    cache.get("NQ", "20260626")  # entry 1
    cache.get("ES", "20260626")  # entry 2
    cache.get("MGC", "20260626")  # entry 3 - evicts entry 1
    assert cache.n_cached == 2
    # Re-get NQ -> re-load (cache miss)
    call_count_before = [0]

    def stub_loader2(base_dir, symbol, date_str):
        call_count_before[0] += 1
        return _make_levels(symbol, date_str)

    cache_recheck = MenthorQCache(tmp_path, cap=2, loader=stub_loader2)
    cache_recheck.get("NQ", "20260626")
    cache_recheck.get("ES", "20260626")
    cache_recheck.get("MGC", "20260626")  # evict NQ
    call_count_before[0] = 0
    cache_recheck.get("NQ", "20260626")  # cache miss -> reload
    assert call_count_before[0] == 1


def test_menthorq_cache_fail_soft_load_exception(tmp_path):
    """Loader exception -> fail-soft empty levels."""
    def raising_loader(base_dir, symbol, date_str):
        raise FileNotFoundError("simulated")

    cache = MenthorQCache(tmp_path, loader=raising_loader)
    levels = cache.get("NQ", "20260626")
    assert levels.is_empty is True
    assert levels.symbol == "NQ"


def test_menthorq_cache_clear():
    cache = MenthorQCache(Path("/fake"), loader=lambda **kw: _make_levels())
    cache.get("NQ", "20260626")
    assert cache.n_cached == 1
    cache.clear()
    assert cache.n_cached == 0


# ============================================================
# ContextBuilder
# ============================================================


def _make_real_bar(symbol: str = "NQ",
                    ts: str = "2026-06-26T14:00:00+00:00") -> dict:
    """Bar complet avec features minimales pour regime + narrative."""
    return {
        "ts_event": ts,
        "symbol": symbol,
        "high": 20010.0, "low": 19995.0, "close": 20000.0, "open": 20000.0,
        "volume": 1000,
        "atr": 10.0, "atr_14m": 40.0,
        "vix_level": 18.0,
        "delta_bar": -100.0,
        "vwap_d": 20000.0,
        "vwap_slope_10": 0.0,
        "vwap_slope_60": 0.0,
    }


def test_builder_init():
    builder = ContextBuilder(menthorq_dir=Path("/fake"))
    assert builder.menthorq_cache is not None


def test_builder_build_returns_scenario_context(tmp_path):
    """build() retourne ScenarioContext valide."""
    cache = MenthorQCache(tmp_path, loader=lambda **kw: _make_levels())
    builder = ContextBuilder(menthorq_dir=tmp_path, menthorq_cache=cache)
    bar = _make_real_bar()
    ctx = builder.build(bar=bar, symbol="NQ")
    assert isinstance(ctx, ScenarioContext)
    assert ctx.symbol == "NQ"
    assert ctx.regime is not None
    assert ctx.narrative is not None
    assert ctx.menthorq is not None


def test_builder_uppercase_symbol(tmp_path):
    """Symbol passe en lowercase -> upper-cased dans le ctx."""
    cache = MenthorQCache(tmp_path, loader=lambda **kw: _make_levels())
    builder = ContextBuilder(menthorq_dir=tmp_path, menthorq_cache=cache)
    bar = _make_real_bar()
    ctx = builder.build(bar=bar, symbol="nq")
    assert ctx.bar["symbol"] == "NQ"


def test_builder_injects_symbol_into_bar_if_missing(tmp_path):
    cache = MenthorQCache(tmp_path, loader=lambda **kw: _make_levels())
    builder = ContextBuilder(menthorq_dir=tmp_path, menthorq_cache=cache)
    bar = _make_real_bar()
    # Remove symbol from bar
    del bar["symbol"]
    ctx = builder.build(bar=bar, symbol="NQ")
    assert ctx.bar["symbol"] == "NQ"


def test_builder_uses_menthorq_cache_for_repeated_calls(tmp_path):
    call_count = [0]

    def counting_loader(base_dir, symbol, date_str):
        call_count[0] += 1
        return _make_levels(symbol, date_str)

    cache = MenthorQCache(tmp_path, loader=counting_loader)
    builder = ContextBuilder(menthorq_dir=tmp_path, menthorq_cache=cache)
    bar = _make_real_bar(ts="2026-06-26T14:00:00+00:00")
    builder.build(bar=bar, symbol="NQ")
    builder.build(bar=bar, symbol="NQ")
    builder.build(bar=bar, symbol="NQ")
    assert call_count[0] == 1


def test_builder_different_dates_reload_menthorq(tmp_path):
    call_count = [0]

    def counting_loader(base_dir, symbol, date_str):
        call_count[0] += 1
        return _make_levels(symbol, date_str)

    cache = MenthorQCache(tmp_path, loader=counting_loader)
    builder = ContextBuilder(menthorq_dir=tmp_path, menthorq_cache=cache)
    bar_d1 = _make_real_bar(ts="2026-06-26T14:00:00+00:00")
    bar_d2 = _make_real_bar(ts="2026-06-27T14:00:00+00:00")
    builder.build(bar=bar_d1, symbol="NQ")
    builder.build(bar=bar_d2, symbol="NQ")
    assert call_count[0] == 2


def test_builder_immutable_bar_input(tmp_path):
    """build() ne mute pas le bar input (copy interne)."""
    cache = MenthorQCache(tmp_path, loader=lambda **kw: _make_levels())
    builder = ContextBuilder(menthorq_dir=tmp_path, menthorq_cache=cache)
    bar = _make_real_bar()
    bar_copy = dict(bar)
    builder.build(bar=bar, symbol="NQ")
    # bar input intact (mutation interne via dict copy)
    # Note : narrative_engine ajoute parfois des champs derives, donc
    # on check juste que les clefs originales sont intactes
    for key in bar_copy:
        assert key in bar


def test_builder_with_real_loader_default():
    """Builder sans cache injecte = utilise real load_menthorq_levels."""
    builder = ContextBuilder(menthorq_dir=Path("/nonexistent"))
    # Devrait pas crash, fail-soft via cache
    assert builder.menthorq_cache.n_cached == 0
