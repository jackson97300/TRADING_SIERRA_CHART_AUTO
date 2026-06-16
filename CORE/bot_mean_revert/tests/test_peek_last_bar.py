"""Test peek_last_bar SierraDataSource - snapshot read-only sans modifier last_ts_seen.

Critique pour IntermarketGate : permet de lire la bar du LEADER (ES) depuis
une autre instance SierraDataSource sans consumer le curseur dedup et bloquer
les lectures legitimes du leader.
"""
from __future__ import annotations

import json
from pathlib import Path

from CORE.bot1_v2.config import Bot1V2Config
from CORE.bot1_v2.data_source import SierraDataSource


def _write_jsonl(path: Path, bars: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for b in bars:
            fh.write(json.dumps(b) + "\n")


def _make_bar(ts_ms: int, close: float = 5800.0) -> dict:
    return {
        "ts": ts_ms,
        "close": close,
        "bar_high": close + 1.0,
        "bar_low": close - 1.0,
        "session_id": "US",
        "is_in_us_cash": True,
    }


def test_peek_last_bar_does_not_advance_cursor(tmp_path, monkeypatch):
    """peek_last_bar() retourne la derniere bar SANS modifier last_ts_seen."""
    # Setup data dir
    sym = "ES"
    data_dir = tmp_path / "DATA" / "live_enriched" / "sierra" / sym
    bars = [_make_bar(1000), _make_bar(2000), _make_bar(3000)]
    _write_jsonl(data_dir / "20260616_ES_sierra_enriched.jsonl", bars)

    # Patch chemin root
    monkeypatch.chdir(tmp_path)
    cfg = Bot1V2Config()
    ds = SierraDataSource(symbol=sym, cfg=cfg)
    # Hack pour rediriger data_dir vers tmp_path
    monkeypatch.setattr(
        type(ds),
        "data_dir",
        property(lambda self: data_dir),
    )

    # 1er peek : doit retourner la derniere bar (ts=3000) sans changer last_ts_seen
    assert ds.last_ts_seen is None
    bar1 = ds.peek_last_bar()
    assert bar1 is not None
    assert bar1["ts"] == 3000
    # last_ts_seen reste None apres peek (PROPRIETE CRITIQUE)
    assert ds.last_ts_seen is None

    # 2eme peek : meme bar retournee (vs read_last_bar qui retournerait None par dedup)
    bar2 = ds.peek_last_bar()
    assert bar2 is not None
    assert bar2["ts"] == 3000
    assert ds.last_ts_seen is None


def test_peek_does_not_break_subsequent_read(tmp_path, monkeypatch):
    """Apres peek_last_bar, read_last_bar() doit toujours marcher normalement."""
    sym = "ES"
    data_dir = tmp_path / "DATA" / "live_enriched" / "sierra" / sym
    bars = [_make_bar(1000), _make_bar(2000)]
    _write_jsonl(data_dir / "20260616_ES_sierra_enriched.jsonl", bars)

    monkeypatch.chdir(tmp_path)
    cfg = Bot1V2Config()
    ds = SierraDataSource(symbol=sym, cfg=cfg)
    monkeypatch.setattr(
        type(ds),
        "data_dir",
        property(lambda self: data_dir),
    )

    # Peek d'abord
    peek_bar = ds.peek_last_bar()
    assert peek_bar is not None
    assert peek_bar["ts"] == 2000

    # Puis read_last_bar normal : doit avancer le curseur
    read_bar = ds.read_last_bar()
    assert read_bar is not None
    assert read_bar["ts"] == 2000
    assert ds.last_ts_seen == 2000

    # Re-read : dedup actif
    re_read = ds.read_last_bar()
    assert re_read is None  # Dedup empeche relecture meme ts

    # Mais peek toujours possible
    peek_again = ds.peek_last_bar()
    assert peek_again is not None
    assert peek_again["ts"] == 2000
    # last_ts_seen preserve apres peek
    assert ds.last_ts_seen == 2000


def test_peek_returns_none_when_no_file(tmp_path, monkeypatch):
    """peek_last_bar retourne None si fichier absent (pas de crash)."""
    sym = "ES"
    data_dir = tmp_path / "DATA" / "live_enriched" / "sierra" / sym
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(tmp_path)
    cfg = Bot1V2Config()
    ds = SierraDataSource(symbol=sym, cfg=cfg)
    monkeypatch.setattr(
        type(ds),
        "data_dir",
        property(lambda self: data_dir),
    )

    bar = ds.peek_last_bar()
    assert bar is None
    assert ds.last_ts_seen is None  # Pas d'effet de bord
