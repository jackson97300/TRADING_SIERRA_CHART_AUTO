"""Tests bar_history_loader (Bot BN V4 warmup persistant)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from CORE.bot_bn_v4.bar_history_loader import (
    DEFAULT_MAX_AGE_HOURS,
    _list_jsonl_files,
    _read_bars_from_file,
    load_recent_bars,
)


# ============================================================
# Fixtures helpers
# ============================================================


def _make_bar(ts_iso: str, close: float = 30000.0, extra: dict = None) -> dict:
    """Construit une bar minimale conforme schema sierra_enriched."""
    bar = {
        "ts_event": ts_iso,
        "close": close,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "vwap_slope_10": 0.1,
    }
    if extra:
        bar.update(extra)
    return bar


def _write_jsonl(path: Path, bars: list[dict]) -> None:
    """Ecrit une liste de bars dans un JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for b in bars:
            fh.write(json.dumps(b) + "\n")


# ============================================================
# Tests
# ============================================================


def test_load_returns_n_bars_from_recent_file(tmp_path: Path) -> None:
    """Fixture JSONL 300 bars, load 240 → ok, ordre chronologique."""
    bars = [_make_bar(f"2026-06-17T{i // 60:02d}:{i % 60:02d}:00+00:00",
                       close=30000.0 + i)
            for i in range(300)]
    file_path = tmp_path / "NQ" / "20260617_NQ_sierra_enriched.jsonl"
    _write_jsonl(file_path, bars)
    loaded = load_recent_bars("NQ", 240, data_root=tmp_path)
    assert len(loaded) == 240
    # Ordre chronologique : ts_event croissant
    ts_list = [b["ts_event"] for b in loaded]
    assert ts_list == sorted(ts_list)
    # Les 240 dernieres = bars[60:300]
    assert loaded[0]["close"] == 30000.0 + 60
    assert loaded[-1]["close"] == 30000.0 + 299


def test_load_spans_two_files_if_needed(tmp_path: Path) -> None:
    """Jour J 100 bars + jour J-1 300 bars, demande 240 = doit concatener."""
    # J-1 = mtime ancien
    bars_j1 = [_make_bar(f"2026-06-16T{i // 60:02d}:{i % 60:02d}:00+00:00",
                          close=29000.0 + i)
               for i in range(300)]
    j1_path = tmp_path / "NQ" / "20260616_NQ_sierra_enriched.jsonl"
    _write_jsonl(j1_path, bars_j1)
    # J = mtime recent
    bars_j = [_make_bar(f"2026-06-17T{i // 60:02d}:{i % 60:02d}:00+00:00",
                        close=30000.0 + i)
              for i in range(100)]
    j_path = tmp_path / "NQ" / "20260617_NQ_sierra_enriched.jsonl"
    _write_jsonl(j_path, bars_j)
    # Set mtime explicite : J > J-1
    now = time.time()
    import os
    os.utime(j1_path, (now - 86400, now - 86400))
    os.utime(j_path, (now, now))

    loaded = load_recent_bars("NQ", 240, data_root=tmp_path)
    assert len(loaded) == 240
    # Doit etre chronologique : J-1 d'abord, puis J
    # bars J-1 closes = 29000-29299, bars J closes = 30000-30099
    # On veut les 240 dernieres = 60 derniers J-1 + 100 bars J = 240 ?
    # Non : 300 + 100 = 400 total. 240 dernieres = bars[160:400].
    # bars[160:300] = J-1 closes 29160-29299 (140 bars J-1)
    # bars[300:400] = J closes 30000-30099 (100 bars J)
    assert loaded[0]["close"] == 29160.0  # bar 160 de J-1
    assert loaded[-1]["close"] == 30099.0  # derniere J


def test_load_skips_corrupt_lines(tmp_path: Path) -> None:
    """JSONL avec ligne malformee → skip + continue."""
    path = tmp_path / "NQ" / "20260617_NQ_sierra_enriched.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_make_bar("2026-06-17T13:30:00+00:00", 30000.0)) + "\n")
        fh.write("{ tronquee\n")  # ligne malformee
        fh.write(json.dumps(_make_bar("2026-06-17T13:31:00+00:00", 30001.0)) + "\n")
        fh.write("\n")  # ligne vide
        fh.write(json.dumps(_make_bar("2026-06-17T13:32:00+00:00", 30002.0)) + "\n")
    loaded = load_recent_bars("NQ", 240, data_root=tmp_path)
    assert len(loaded) == 3
    assert [b["close"] for b in loaded] == [30000.0, 30001.0, 30002.0]


def test_load_ignores_files_older_than_ttl(tmp_path: Path) -> None:
    """Fichier mtime > 36h → ignore."""
    bars = [_make_bar("2025-01-01T00:00:00+00:00", 28000.0)]
    old_path = tmp_path / "NQ" / "20250101_NQ_sierra_enriched.jsonl"
    _write_jsonl(old_path, bars)
    # Set mtime tres ancien (5 jours)
    import os
    old_mtime = time.time() - 5 * 86400
    os.utime(old_path, (old_mtime, old_mtime))
    loaded = load_recent_bars("NQ", 240, data_root=tmp_path, max_age_hours=36)
    assert loaded == []


def test_load_no_files_returns_empty_list(tmp_path: Path) -> None:
    """Dossier vide → retourne [] sans exception."""
    loaded = load_recent_bars("NQ", 240, data_root=tmp_path)
    assert loaded == []


def test_load_preserves_chronological_order(tmp_path: Path) -> None:
    """Verifie monotonie croissante des ts_event meme si fichiers desordres."""
    # 2 fichiers : jour 2 (mtime recent), jour 1 (mtime ancien)
    bars_d1 = [_make_bar(f"2026-06-15T{i:02d}:00:00+00:00", 28000.0 + i)
               for i in range(10)]
    bars_d2 = [_make_bar(f"2026-06-16T{i:02d}:00:00+00:00", 29000.0 + i)
               for i in range(10)]
    d1_path = tmp_path / "NQ" / "20260615_NQ_sierra_enriched.jsonl"
    d2_path = tmp_path / "NQ" / "20260616_NQ_sierra_enriched.jsonl"
    _write_jsonl(d1_path, bars_d1)
    _write_jsonl(d2_path, bars_d2)
    # mtime : d2 plus recent
    import os
    now = time.time()
    os.utime(d1_path, (now - 86400, now - 86400))
    os.utime(d2_path, (now, now))
    loaded = load_recent_bars("NQ", 20, data_root=tmp_path)
    ts_list = [b["ts_event"] for b in loaded]
    assert ts_list == sorted(ts_list)
    # 10 bars d1 + 10 bars d2
    assert loaded[0]["close"] == 28000.0
    assert loaded[-1]["close"] == 29009.0


def test_load_zero_n_returns_empty(tmp_path: Path) -> None:
    """n=0 → retourne [] immediat."""
    bars = [_make_bar("2026-06-17T13:30:00+00:00", 30000.0)]
    path = tmp_path / "NQ" / "20260617_NQ_sierra_enriched.jsonl"
    _write_jsonl(path, bars)
    assert load_recent_bars("NQ", 0, data_root=tmp_path) == []
    assert load_recent_bars("NQ", -5, data_root=tmp_path) == []


def test_load_skips_bars_without_ts(tmp_path: Path) -> None:
    """Bars sans ts_event ni ts → skip."""
    path = tmp_path / "NQ" / "20260617_NQ_sierra_enriched.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(_make_bar("2026-06-17T13:30:00+00:00", 30000.0)) + "\n")
        fh.write(json.dumps({"close": 30001.0}) + "\n")  # NO ts
        fh.write(json.dumps(_make_bar("2026-06-17T13:31:00+00:00", 30002.0)) + "\n")
    loaded = load_recent_bars("NQ", 240, data_root=tmp_path)
    assert len(loaded) == 2
    assert [b["close"] for b in loaded] == [30000.0, 30002.0]
