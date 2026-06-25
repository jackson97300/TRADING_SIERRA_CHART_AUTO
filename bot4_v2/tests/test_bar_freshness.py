"""Tests bot4_v2/core/bar_freshness."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import bot4_v2.core.bar_freshness as bfm
from bot4_v2.core.bar_freshness import (
    _parse_ts_event,
    _read_last_valid_jsonl_line,
    check_bar_freshness,
)


def _make_bar(ts_event: datetime | None = None, close: float = 20000.0) -> dict:
    if ts_event is None:
        ts_event = datetime.now(timezone.utc)
    return {
        "ts_event": ts_event.isoformat(),
        "ts": int(ts_event.timestamp() * 1000),
        "ts_event_ns": int(ts_event.timestamp() * 1e9),
        "open": close - 1.0,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
    }


def _write_jsonl(path: Path, bars: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        for bar in bars:
            f.write(json.dumps(bar) + "\n")


def _make_sierra_file(
    sierra_base: Path,
    symbol: str,
    bars: list[dict],
    date_str: str = "20260625",
) -> Path:
    sym_dir = sierra_base / symbol
    path = sym_dir / f"{date_str}_{symbol}_sierra_enriched.jsonl"
    _write_jsonl(path, bars)
    return path


# ============================================================
# check_bar_freshness : cas nominal
# ============================================================

def test_check_bar_freshness_ok_recent(tmp_path):
    """Bar recente -> is_fresh=True."""
    bar = _make_bar()
    _make_sierra_file(tmp_path, "NQ", [bar])
    is_fresh, age, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is True
    assert age < 60
    assert reason == "ok"


def test_check_bar_freshness_no_symbol(tmp_path):
    is_fresh, age, reason = check_bar_freshness("", tmp_path, max_age_sec=60)
    assert is_fresh is False
    assert age == -1.0
    assert reason == "no_symbol"


def test_check_bar_freshness_no_file(tmp_path):
    is_fresh, age, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is False
    assert age == -1.0
    assert reason == "no_file_for_NQ"


def test_check_bar_freshness_symbol_case_insensitive(tmp_path):
    bar = _make_bar()
    _make_sierra_file(tmp_path, "NQ", [bar])
    is_fresh, _, _ = check_bar_freshness("nq", tmp_path, max_age_sec=60)
    assert is_fresh is True


# ============================================================
# Staleness detection
# ============================================================

def test_check_bar_freshness_bar_ts_stale(tmp_path):
    """Fichier recent mais bar ts ancien -> bar_ts_stale (enricher zombie pattern)."""
    old_dt = datetime.now(timezone.utc) - timedelta(seconds=300)
    bar = _make_bar(ts_event=old_dt)
    _make_sierra_file(tmp_path, "NQ", [bar])
    is_fresh, age, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is False
    assert age >= 300
    assert reason.startswith("bar_ts_stale_")


def test_check_bar_freshness_file_mtime_stale(tmp_path):
    """Fichier ancien (touched il y a longtemps) -> file_mtime_stale ou bar_ts_stale."""
    old_dt = datetime.now(timezone.utc) - timedelta(seconds=200)
    bar = _make_bar(ts_event=old_dt)
    path = _make_sierra_file(tmp_path, "NQ", [bar])
    # Force mtime du fichier ancien
    old_mtime = time.time() - 200
    os.utime(path, (old_mtime, old_mtime))

    is_fresh, age, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is False
    assert age >= 60
    # Selon ordre eval, peut etre bar_ts_stale OU file_mtime_stale
    assert reason.startswith("bar_ts_stale_") or reason.startswith("file_mtime_stale_")


# ============================================================
# Corruption / edge cases
# ============================================================

def test_check_bar_freshness_empty_file(tmp_path):
    sym_dir = tmp_path / "NQ"
    sym_dir.mkdir()
    empty = sym_dir / "20260625_NQ_sierra_enriched.jsonl"
    empty.touch()
    is_fresh, age, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is False
    assert reason.startswith("empty_or_unreadable")


def test_check_bar_freshness_corrupt_last_line_but_valid_before(tmp_path):
    """Derniere ligne tronquee mais avant-derniere valide -> use avant-derniere (R5 review).

    BUG FIX 24/06 : writer en plein flush peut produire ligne tronquee.
    """
    bar1 = _make_bar()
    sym_dir = tmp_path / "NQ"
    sym_dir.mkdir()
    path = sym_dir / "20260625_NQ_sierra_enriched.jsonl"
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(bar1) + "\n")
        f.write('{"ts_event": "2026-06-25T12:00:00+00:00", "ts": 17822')  # ligne tronquee
    is_fresh, _, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    # Trouve bar1 valide -> is_fresh=True
    assert is_fresh is True
    assert reason == "ok"


def test_check_bar_freshness_no_ts_event(tmp_path):
    """Bar sans ts_event, ts, ts_event_ns -> no_ts_event."""
    bar = {"close": 20000.0}  # pas de ts
    _make_sierra_file(tmp_path, "NQ", [bar])
    is_fresh, _, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is False
    assert reason == "no_ts_event"


def test_check_bar_freshness_picks_latest_file(tmp_path):
    """Plusieurs fichiers -> picks le plus recent."""
    sym_dir = tmp_path / "NQ"
    sym_dir.mkdir()
    # Old file (1h ago)
    old_bar = _make_bar(ts_event=datetime.now(timezone.utc) - timedelta(hours=1))
    old_path = sym_dir / "20260624_NQ_sierra_enriched.jsonl"
    _write_jsonl(old_path, [old_bar])
    old_mtime = time.time() - 3600
    os.utime(old_path, (old_mtime, old_mtime))

    # New file (recent)
    new_bar = _make_bar()
    new_path = sym_dir / "20260625_NQ_sierra_enriched.jsonl"
    _write_jsonl(new_path, [new_bar])

    is_fresh, _, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is True
    assert reason == "ok"


# ============================================================
# max_age_sec parameter (R1 review : source unique fail-loud, plus de fallback)
# ============================================================

def test_check_bar_freshness_raises_on_max_age_none(tmp_path):
    """R1 review : max_age_sec=None -> ValueError (source unique settings)."""
    bar = _make_bar()
    _make_sierra_file(tmp_path, "NQ", [bar])
    with pytest.raises(ValueError, match="positive int"):
        check_bar_freshness("NQ", tmp_path, max_age_sec=None)  # type: ignore


def test_check_bar_freshness_raises_on_max_age_zero(tmp_path):
    """R1 review : max_age_sec=0 -> ValueError."""
    bar = _make_bar()
    _make_sierra_file(tmp_path, "NQ", [bar])
    with pytest.raises(ValueError):
        check_bar_freshness("NQ", tmp_path, max_age_sec=0)


def test_check_bar_freshness_raises_on_max_age_negative(tmp_path):
    """R1 review : max_age_sec<0 -> ValueError."""
    bar = _make_bar()
    _make_sierra_file(tmp_path, "NQ", [bar])
    with pytest.raises(ValueError):
        check_bar_freshness("NQ", tmp_path, max_age_sec=-10)


def test_check_bar_freshness_raises_on_max_age_non_int(tmp_path):
    """R1 review : max_age_sec=str -> ValueError."""
    bar = _make_bar()
    _make_sierra_file(tmp_path, "NQ", [bar])
    with pytest.raises(ValueError):
        check_bar_freshness("NQ", tmp_path, max_age_sec="120")  # type: ignore


# ============================================================
# R2 review : symbol path safety validation
# ============================================================

def test_check_bar_freshness_rejects_path_traversal_symbol(tmp_path):
    """R2 review : symbol avec '/' '.' '../' -> invalid_symbol reason."""
    is_fresh, age, reason = check_bar_freshness(
        "../../etc/passwd", tmp_path, max_age_sec=60,
    )
    assert is_fresh is False
    assert age == -1.0
    assert reason.startswith("invalid_symbol_")


def test_check_bar_freshness_rejects_symbol_too_long(tmp_path):
    """R2 review : symbol >8 chars -> invalid_symbol (anti DOS futur)."""
    is_fresh, _, reason = check_bar_freshness(
        "ABCDEFGHIJKLMNOP", tmp_path, max_age_sec=60,
    )
    assert is_fresh is False
    assert reason.startswith("invalid_symbol_")


def test_check_bar_freshness_accepts_valid_alphanumeric_symbol(tmp_path):
    """R2 review : symbol alphanumeric <=8 chars -> accepte (no_file car pas cree)."""
    is_fresh, _, reason = check_bar_freshness("MGC2", tmp_path, max_age_sec=60)
    # Pas de fichier MGC2 -> no_file_for_MGC2 (PAS invalid_symbol)
    assert is_fresh is False
    assert reason == "no_file_for_MGC2"


# ============================================================
# _parse_ts_event helper
# ============================================================

def test_parse_ts_event_iso_string():
    bar = {"ts_event": "2026-06-25T10:00:00+00:00"}
    dt = _parse_ts_event(bar)
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_ts_event_iso_string_naive():
    """ISO sans timezone -> UTC fallback."""
    bar = {"ts_event": "2026-06-25T10:00:00"}
    dt = _parse_ts_event(bar)
    assert dt is not None
    assert dt.tzinfo is timezone.utc


def test_parse_ts_event_iso_with_z_suffix():
    """Suffix 'Z' (UTC) doit etre supporte."""
    bar = {"ts_event": "2026-06-25T10:00:00Z"}
    dt = _parse_ts_event(bar)
    assert dt is not None


def test_parse_ts_event_fallback_ts_ms():
    """Si ts_event invalide, fallback ts (ms)."""
    expected_dt = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
    bar = {"ts_event": "bad", "ts": int(expected_dt.timestamp() * 1000)}
    dt = _parse_ts_event(bar)
    assert dt is not None
    assert abs((dt - expected_dt).total_seconds()) < 1


def test_parse_ts_event_fallback_ts_event_ns():
    """Si ts_event + ts invalides, fallback ts_event_ns."""
    expected_dt = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
    bar = {"ts_event": None, "ts": None, "ts_event_ns": int(expected_dt.timestamp() * 1e9)}
    dt = _parse_ts_event(bar)
    assert dt is not None
    assert abs((dt - expected_dt).total_seconds()) < 1


def test_parse_ts_event_all_missing():
    bar = {"close": 20000.0}
    dt = _parse_ts_event(bar)
    assert dt is None


# ============================================================
# _read_last_valid_jsonl_line helper
# ============================================================

def test_read_last_valid_returns_none_for_missing_file(tmp_path):
    assert _read_last_valid_jsonl_line(str(tmp_path / "missing.jsonl")) is None


def test_read_last_valid_returns_none_for_empty_file(tmp_path):
    f = tmp_path / "empty.jsonl"
    f.touch()
    assert _read_last_valid_jsonl_line(str(f)) is None


def test_read_last_valid_returns_last_valid_skipping_corrupt(tmp_path):
    """Multi-lignes : derniere corrompue -> renvoie avant-derniere valide."""
    f = tmp_path / "mixed.jsonl"
    bar1 = _make_bar()
    bar2 = _make_bar(close=20100.0)
    with f.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(bar1) + "\n")
        fh.write(json.dumps(bar2) + "\n")
        fh.write('{"corrupt')  # tronquee
    result = _read_last_valid_jsonl_line(str(f))
    assert result is not None
    parsed = json.loads(result)
    assert parsed["close"] == 20100.0  # bar2 = derniere valide


def test_read_last_valid_returns_none_when_all_corrupt(tmp_path):
    """R3 review : 7 lignes toutes corrompues -> None (audit J+1 fail-loud caller)."""
    f = tmp_path / "all_corrupt.jsonl"
    with f.open("w", encoding="utf-8") as fh:
        for _ in range(7):
            fh.write('{"corrupt_truncated_line\n')
    assert _read_last_valid_jsonl_line(str(f)) is None


# ============================================================
# R3 review : stat_fail OSError mock
# ============================================================

def test_check_bar_freshness_stat_fail_permission_denied(tmp_path, monkeypatch):
    """R3 review : os.stat raise PermissionError -> stat_fail_PermissionError reason."""
    bar = _make_bar()
    _make_sierra_file(tmp_path, "NQ", [bar])
    real_stat = bfm.os.stat
    calls = {"n": 0}

    def fake_stat(p, *a, **kw):
        calls["n"] += 1
        # 1er appel = max(matches, key=os.stat).st_mtime -> doit reussir
        # 2eme appel = ligne 175 file_mtime = os.stat -> raise
        if calls["n"] >= 2:
            raise PermissionError("denied (simulated)")
        return real_stat(p, *a, **kw)

    monkeypatch.setattr(bfm.os, "stat", fake_stat)
    is_fresh, age, reason = check_bar_freshness("NQ", tmp_path, max_age_sec=60)
    assert is_fresh is False
    assert age == -1.0
    assert reason.startswith("stat_fail_")
