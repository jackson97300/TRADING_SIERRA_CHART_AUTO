"""Tests bot4_v2/core/menthorq_source."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from bot4_v2.core.menthorq_source import (
    MenthorQLevels,
    _is_status_ok,
    _menthorq_file_path,
    _safe_extract_float,
    _safe_extract_int,
    _safe_extract_strikes,
    _validate_date_str,
    _validate_symbol,
    load_menthorq_levels,
    menthorq_levels_to_key_levels,
)
from bot4_v2.core.narrative_engine import KeyLevel


def _make_menthorq_json(
    *,
    symbol: str = "ES",
    call_resistance: float = 4200.0,
    put_support: float = 4100.0,
    hvl: float = 4150.0,
    level_0dte: float = 4180.0,
    gamma_wall_0dte: float = 4175.0,
    top_gex_strikes: list = None,
    bl_levels: list = None,
) -> dict:
    """Construit JSON MenthorQ format CLAUDE.md spec officielle."""
    if top_gex_strikes is None:
        top_gex_strikes = [4180.0, 4170.0, 4190.0, 4150.0]
    if bl_levels is None:
        bl_levels = [4100.0, 4250.0]
    return {
        "date": "20260625",
        "source": "menthorq",
        "key_levels": {
            symbol: {
                "call_resistance": call_resistance,
                "put_support": put_support,
                "hvl": hvl,
                "0dte": level_0dte,
                "1d_max": 4250.0,
                "1d_min": 4050.0,
                "iv_30d": 18.5,
                "total_gex": 100000.0,
                "net_gex": -25000.0,
                "gamma_condition": 1,
            }
        },
        "vol_model": {
            symbol: {
                "top_gex_strikes": top_gex_strikes,
                "bl_levels": bl_levels,
                "gamma_wall_0dte": gamma_wall_0dte,
            }
        },
    }


def _write_menthorq_file(base_dir: Path, date_str: str, data: dict) -> Path:
    """Ecrit fichier MenthorQ JSON pour test."""
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{date_str}_menthorq_complete.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ============================================================
# MenthorQLevels dataclass
# ============================================================

def test_menthorq_levels_default_is_empty():
    levels = MenthorQLevels(symbol="ES", date_str="20260625", is_empty=True)
    assert levels.is_empty is True
    assert levels.has_data is False


def test_menthorq_levels_has_data_with_call_resistance():
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        call_resistance=4200.0,
    )
    assert levels.has_data is True


def test_menthorq_levels_frozen():
    from dataclasses import FrozenInstanceError
    levels = MenthorQLevels(symbol="ES", date_str="20260625")
    with pytest.raises(FrozenInstanceError):
        levels.symbol = "NQ"  # type: ignore


# ============================================================
# _validate_symbol
# ============================================================

def test_validate_symbol_valid():
    assert _validate_symbol("ES") == "ES"
    assert _validate_symbol("nq") == "NQ"  # case insensitive
    assert _validate_symbol("MGC") == "MGC"


def test_validate_symbol_non_string():
    with pytest.raises(ValueError, match="must be str"):
        _validate_symbol(123)  # type: ignore


def test_validate_symbol_path_traversal():
    with pytest.raises(ValueError, match="path safety"):
        _validate_symbol("../../etc")


def test_validate_symbol_too_long():
    with pytest.raises(ValueError):
        _validate_symbol("ABCDEFGHIJ")  # > 8 chars


def test_validate_symbol_special_chars():
    with pytest.raises(ValueError):
        _validate_symbol("ES-FUT")  # dash not allowed


# ============================================================
# _validate_date_str
# ============================================================

def test_validate_date_str_valid():
    assert _validate_date_str("20260625") == "20260625"


def test_validate_date_str_from_datetime_date():
    assert _validate_date_str(date(2026, 6, 25)) == "20260625"


def test_validate_date_str_invalid_format():
    with pytest.raises(ValueError, match="YYYYMMDD"):
        _validate_date_str("2026-06-25")


def test_validate_date_str_too_short():
    with pytest.raises(ValueError):
        _validate_date_str("202606")


def test_validate_date_str_invalid_type():
    with pytest.raises(ValueError):
        _validate_date_str(123)  # type: ignore


# ============================================================
# _safe_extract_float / int / strikes
# ============================================================

def test_safe_extract_float_valid():
    assert _safe_extract_float({"x": 1.5}, "x") == 1.5


def test_safe_extract_float_missing():
    assert _safe_extract_float({}, "x") is None


def test_safe_extract_float_none():
    assert _safe_extract_float({"x": None}, "x") is None


def test_safe_extract_float_nan():
    assert _safe_extract_float({"x": float("nan")}, "x") is None


def test_safe_extract_float_invalid_string():
    assert _safe_extract_float({"x": "not_a_float"}, "x") is None


def test_safe_extract_int_valid():
    assert _safe_extract_int({"x": "1"}, "x") == 1


def test_safe_extract_int_missing():
    assert _safe_extract_int({}, "x") is None


def test_safe_extract_strikes_valid_list():
    result = _safe_extract_strikes({"strikes": [1.0, 2.0, 3.0]}, "strikes")
    assert result == (1.0, 2.0, 3.0)


def test_safe_extract_strikes_truncate_max():
    """max_count=10 par default."""
    result = _safe_extract_strikes(
        {"strikes": list(range(20))}, "strikes",
    )
    assert len(result) == 10


def test_safe_extract_strikes_filters_nan():
    result = _safe_extract_strikes(
        {"strikes": [1.0, float("nan"), 2.0]}, "strikes",
    )
    assert result == (1.0, 2.0)


def test_safe_extract_strikes_missing():
    assert _safe_extract_strikes({}, "strikes") == ()


def test_safe_extract_strikes_not_list():
    """Si pas list/tuple -> tuple vide."""
    assert _safe_extract_strikes({"strikes": "string"}, "strikes") == ()


# ============================================================
# _is_status_ok
# ============================================================

def test_is_status_ok_no_status_keys():
    """Section sans message/error_type/status -> OK."""
    assert _is_status_ok({"call_resistance": 4200}) is True


def test_is_status_ok_explicit_ok():
    assert _is_status_ok({
        "message": "ok", "error_type": None, "status": "ok"
    }) is True


def test_is_status_ok_error():
    assert _is_status_ok({
        "message": "scrape fail", "error_type": "timeout", "status": "error"
    }) is False


def test_is_status_ok_non_dict():
    assert _is_status_ok("not_a_dict") is False  # type: ignore


# ============================================================
# _menthorq_file_path
# ============================================================

def test_menthorq_file_path_format(tmp_path):
    path = _menthorq_file_path(tmp_path, "20260625")
    assert path.name == "20260625_menthorq_complete.json"


# ============================================================
# load_menthorq_levels
# ============================================================

def test_load_menthorq_levels_file_not_found_returns_empty(tmp_path, caplog):
    """File absent -> MenthorQLevels is_empty=True + warning."""
    import logging
    with caplog.at_level(logging.WARNING):
        levels = load_menthorq_levels("20260625", "ES", tmp_path)
    assert levels.is_empty is True
    assert any("file_not_found" in r.message for r in caplog.records)


def test_load_menthorq_levels_invalid_symbol_raises(tmp_path):
    with pytest.raises(ValueError):
        load_menthorq_levels("20260625", "../../etc", tmp_path)


def test_load_menthorq_levels_invalid_date_raises(tmp_path):
    with pytest.raises(ValueError):
        load_menthorq_levels("2026/06/25", "ES", tmp_path)


def test_load_menthorq_levels_corrupt_json(tmp_path, caplog):
    """JSON corrompu -> is_empty + warning explicit."""
    import logging
    path = tmp_path / "20260625_menthorq_complete.json"
    path.write_text("not valid json {", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        levels = load_menthorq_levels("20260625", "ES", tmp_path)
    assert levels.is_empty is True
    assert any("read_fail" in r.message for r in caplog.records)


def test_load_menthorq_levels_json_not_dict(tmp_path):
    path = tmp_path / "20260625_menthorq_complete.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")  # liste, pas dict
    levels = load_menthorq_levels("20260625", "ES", tmp_path)
    assert levels.is_empty is True


def test_load_menthorq_levels_symbol_section_missing(tmp_path):
    """ES present mais NQ absent -> NQ is_empty."""
    data = _make_menthorq_json(symbol="ES")
    _write_menthorq_file(tmp_path, "20260625", data)
    levels = load_menthorq_levels("20260625", "NQ", tmp_path)
    assert levels.is_empty is True


def test_load_menthorq_levels_section_error_status(tmp_path):
    """Section avec status=error -> is_empty + warning."""
    data = {
        "key_levels": {
            "ES": {
                "message": "scrape failed",
                "error_type": "timeout",
                "status": "error",
            }
        }
    }
    _write_menthorq_file(tmp_path, "20260625", data)
    levels = load_menthorq_levels("20260625", "ES", tmp_path)
    assert levels.is_empty is True


def test_load_menthorq_levels_full_data(tmp_path):
    """Format officiel CLAUDE.md spec : key_levels + vol_model."""
    data = _make_menthorq_json(
        symbol="ES",
        call_resistance=4200.0,
        put_support=4100.0,
        hvl=4150.0,
        level_0dte=4180.0,
        gamma_wall_0dte=4175.0,
        top_gex_strikes=[4180.0, 4170.0, 4190.0],
        bl_levels=[4100.0, 4250.0],
    )
    _write_menthorq_file(tmp_path, "20260625", data)
    levels = load_menthorq_levels("20260625", "ES", tmp_path)
    assert levels.is_empty is False
    assert levels.symbol == "ES"
    assert levels.date_str == "20260625"
    assert levels.call_resistance == 4200.0
    assert levels.put_support == 4100.0
    assert levels.hvl == 4150.0
    assert levels.level_0dte == 4180.0
    assert levels.gamma_wall_0dte == 4175.0
    assert levels.top_gex_strikes == (4180.0, 4170.0, 4190.0)
    assert levels.bl_levels == (4100.0, 4250.0)
    assert levels.iv_30d == 18.5
    assert levels.gamma_condition == 1


def test_load_menthorq_levels_flat_direct_format(tmp_path):
    """R1 review : Format 3 flat direct {ES: {call_resistance: ...}} sans wrapper."""
    data = {
        "ES": {
            "call_resistance": 4200.0,
            "put_support": 4100.0,
            "hvl": 4150.0,
        }
    }
    _write_menthorq_file(tmp_path, "20260625", data)
    levels = load_menthorq_levels("20260625", "ES", tmp_path)
    assert levels.is_empty is False
    assert levels.call_resistance == 4200.0
    assert levels.put_support == 4100.0
    assert levels.hvl == 4150.0


def test_load_menthorq_levels_legacy_structured_format(tmp_path):
    """Format legacy : {symbol: {structured: {...}}}."""
    data = {
        "ES": {
            "structured": {
                "call_resistance": 4200.0,
                "put_support": 4100.0,
                "top_gex_strikes": [4180.0, 4170.0],
                "gamma_wall_0dte": 4175.0,
            }
        }
    }
    _write_menthorq_file(tmp_path, "20260625", data)
    levels = load_menthorq_levels("20260625", "ES", tmp_path)
    assert levels.is_empty is False
    assert levels.call_resistance == 4200.0
    assert levels.put_support == 4100.0


def test_load_menthorq_levels_case_insensitive_symbol(tmp_path):
    data = _make_menthorq_json(symbol="ES")
    _write_menthorq_file(tmp_path, "20260625", data)
    # Pass lowercase, must work
    levels = load_menthorq_levels("20260625", "es", tmp_path)
    assert levels.is_empty is False


def test_load_menthorq_levels_date_input_datetime(tmp_path):
    data = _make_menthorq_json(symbol="ES")
    _write_menthorq_file(tmp_path, "20260625", data)
    levels = load_menthorq_levels(date(2026, 6, 25), "ES", tmp_path)
    assert levels.is_empty is False


# ============================================================
# menthorq_levels_to_key_levels conversion
# ============================================================

def test_menthorq_to_key_levels_empty():
    """is_empty=True -> retourne []."""
    empty = MenthorQLevels(symbol="ES", date_str="20260625", is_empty=True)
    assert menthorq_levels_to_key_levels(empty, close=4200.0, atr=10.0) == []


def test_menthorq_to_key_levels_zero_atr():
    """atr<=0 -> retourne [] (anti div zero)."""
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        call_resistance=4200.0,
    )
    assert menthorq_levels_to_key_levels(levels, close=4180.0, atr=0) == []


def test_menthorq_to_key_levels_call_resistance_above():
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        call_resistance=4220.0,
    )
    result = menthorq_levels_to_key_levels(levels, close=4200.0, atr=10.0)
    assert len(result) == 1
    assert result[0].price == 4220.0
    assert result[0].level_type == "resistance"
    assert result[0].distance_atr == 2.0  # (4220-4200)/10
    assert result[0].label == "MQ_call_resistance"


def test_menthorq_to_key_levels_put_support_below():
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        put_support=4180.0,
    )
    result = menthorq_levels_to_key_levels(levels, close=4200.0, atr=10.0)
    assert len(result) == 1
    assert result[0].price == 4180.0
    assert result[0].level_type == "support"
    assert result[0].distance_atr == -2.0


def test_menthorq_to_key_levels_pivot_hvl():
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        hvl=4205.0,
    )
    result = menthorq_levels_to_key_levels(levels, close=4200.0, atr=10.0)
    assert len(result) == 1
    assert result[0].level_type == "pivot"
    assert result[0].label == "MQ_hvl"


def test_menthorq_to_key_levels_sort_by_abs_distance():
    """Le plus proche en premier (abs distance)."""
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        call_resistance=4250.0,  # +5 ATR
        put_support=4195.0,      # -0.5 ATR (plus proche)
        hvl=4205.0,              # +0.5 ATR
    )
    result = menthorq_levels_to_key_levels(levels, close=4200.0, atr=10.0)
    assert len(result) == 3
    # Premier = le plus proche en valeur absolue
    assert abs(result[0].distance_atr) <= abs(result[1].distance_atr)
    assert abs(result[1].distance_atr) <= abs(result[2].distance_atr)


def test_menthorq_to_key_levels_top_gex_strikes():
    """Max 5 top_gex_strikes inclus."""
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        top_gex_strikes=(4180.0, 4190.0, 4210.0, 4220.0, 4230.0,
                          4240.0, 4250.0, 4260.0),  # 8 strikes
    )
    result = menthorq_levels_to_key_levels(levels, close=4200.0, atr=10.0)
    # Max 5 top_gex inclus
    gex_labels = [r.label for r in result if r.label.startswith("MQ_top_gex_")]
    assert len(gex_labels) == 5


def test_menthorq_to_key_levels_bl_levels():
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        bl_levels=(4100.0, 4250.0),
    )
    result = menthorq_levels_to_key_levels(levels, close=4200.0, atr=10.0)
    bl_labels = [r.label for r in result if r.label.startswith("MQ_bl_")]
    assert len(bl_labels) == 2


def test_menthorq_to_key_levels_all_levels_returned_as_KeyLevel():
    """Tous niveaux KeyLevel instances."""
    levels = MenthorQLevels(
        symbol="ES", date_str="20260625",
        call_resistance=4220.0, put_support=4180.0, hvl=4205.0,
    )
    result = menthorq_levels_to_key_levels(levels, close=4200.0, atr=10.0)
    assert all(isinstance(kl, KeyLevel) for kl in result)
    assert all(kl.sources[0].startswith("MenthorQ_") for kl in result)
