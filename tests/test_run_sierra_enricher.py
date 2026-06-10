"""Tests Phase 4.2.1 wrapper BOT/run_sierra_enricher.py."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "BOT"))
sys.path.insert(0, str(_ROOT / "CORE"))

ET = ZoneInfo("America/New_York")


def _et_to_utc(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET).astimezone(timezone.utc)


def _make_sierra_jsonl(tmp_path: Path, n_bars: int = 12) -> Path:
    """Helper : cree un fichier JSONL Sierra simulé avec N bars."""
    path = tmp_path / "20260610_NQ.jsonl"
    base_ts = _et_to_utc(2026, 6, 10, 10, 0)
    lines = []
    for i in range(n_bars):
        ts = base_ts.replace(minute=i)
        bar = {
            "ts_utc": ts.isoformat(),
            "sym": "NQ",
            "close": 100.0 + i * 0.5,
            "bar_high": 100.5 + i * 0.5,
            "bar_low": 99.5 + i * 0.5,
            "delta_bar": 100.0,
            "total_vol": 1000.0,
            "atr": 2.0,
            "dist_cur_vpoc": 5.0 - i * 0.2,
            "dist_swing_high": 3.0,
            "dist_swing_low": 8.0,
        }
        lines.append(json.dumps(bar))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ────────────────────────────────────────────────────────────────────────────
# Tests serialization
# ────────────────────────────────────────────────────────────────────────────

def test_serialize_payload_numpy_types():
    """Numpy types serialises en JSON Python native."""
    from run_sierra_enricher import _serialize_payload
    import numpy as np

    payload = {
        "int_val": np.int64(42),
        "float_val": np.float64(3.14),
        "bool_val": np.bool_(True),
        "nan_val": np.float64(np.nan),
        "array_val": np.array([1, 2, 3]),
        "string_val": "test",
    }
    line = _serialize_payload(payload)
    parsed = json.loads(line)
    assert parsed["int_val"] == 42
    assert abs(parsed["float_val"] - 3.14) < 0.01
    assert parsed["bool_val"] is True
    assert parsed["nan_val"] is None  # NaN -> null
    assert parsed["array_val"] == [1, 2, 3]


# ────────────────────────────────────────────────────────────────────────────
# Tests mode batch
# ────────────────────────────────────────────────────────────────────────────

def test_batch_mode_enriches_all_bars(tmp_path):
    """Mode batch : enrich N bars -> output JSONL avec features Phase 3."""
    from run_sierra_enricher import run_batch_mode

    batch_file = _make_sierra_jsonl(tmp_path, n_bars=12)
    output_file = tmp_path / "output.jsonl"

    stats = run_batch_mode(
        symbol="NQ",
        batch_file=batch_file,
        output_file=output_file,
        dry_run=False,
    )

    assert stats["bars_read"] == 12
    assert stats["bars_enriched"] == 12
    assert stats["errors"] == 0
    assert output_file.exists()

    # Verifier que output contient features Phase 3
    with open(output_file, "r", encoding="utf-8") as f:
        first_line = json.loads(f.readline())
    assert "poc_migration_dir" in first_line
    assert "ctx_climax_signal" in first_line
    assert "pdh" in first_line
    assert "session_segment" in first_line
    assert "is_roll_day" in first_line
    assert "delta_div_buy" in first_line


def test_batch_mode_dry_run_no_write(tmp_path):
    """Dry-run : compute mais pas d'ecriture."""
    from run_sierra_enricher import run_batch_mode

    batch_file = _make_sierra_jsonl(tmp_path, n_bars=5)
    output_file = tmp_path / "should_not_exist.jsonl"

    stats = run_batch_mode(
        symbol="NQ",
        batch_file=batch_file,
        output_file=output_file,
        dry_run=True,
    )

    assert stats["bars_enriched"] == 5
    assert not output_file.exists()


def test_batch_mode_missing_file_raises(tmp_path):
    """Fichier batch absent -> FileNotFoundError."""
    from run_sierra_enricher import run_batch_mode

    missing = tmp_path / "missing.jsonl"
    with pytest.raises(FileNotFoundError):
        run_batch_mode(
            symbol="NQ",
            batch_file=missing,
            output_file=tmp_path / "out.jsonl",
        )


def test_batch_mode_skips_invalid_lines(tmp_path):
    """Lignes JSON corrompues : skip + stats errors increment."""
    from run_sierra_enricher import run_batch_mode

    path = tmp_path / "corrupt.jsonl"
    lines = [
        '{"ts_utc": "2026-06-10T14:00:00+00:00", "close": 100.0, "bar_high": 101.0, '
        '"bar_low": 99.0, "delta_bar": 100.0, "total_vol": 1000.0, "atr": 2.0, '
        '"dist_cur_vpoc": 5.0, "dist_swing_high": 3.0, "dist_swing_low": 8.0}',
        '{INVALID JSON',  # corrupt
        '',  # empty
    ]
    path.write_text("\n".join(lines), encoding="utf-8")

    stats = run_batch_mode(
        symbol="NQ",
        batch_file=path,
        output_file=tmp_path / "out.jsonl",
    )

    assert stats["bars_read"] == 2  # 2 non-empty lines
    assert stats["bars_enriched"] == 1  # 1 valid
    assert stats["errors"] == 1  # 1 corrupt
    assert stats["bars_skipped"] == 1


def test_batch_mode_pipeline_stats_populated(tmp_path):
    """Stats orchestrateur retournees dans output."""
    from run_sierra_enricher import run_batch_mode

    batch_file = _make_sierra_jsonl(tmp_path, n_bars=10)
    output_file = tmp_path / "out.jsonl"

    stats = run_batch_mode(
        symbol="NQ",
        batch_file=batch_file,
        output_file=output_file,
    )

    assert "pipeline" in stats
    assert stats["pipeline"]["bars_processed"] == 10
    assert stats["pipeline"]["symbol"] == "NQ"


# ────────────────────────────────────────────────────────────────────────────
# Tests output path construction
# ────────────────────────────────────────────────────────────────────────────

def test_build_output_path_creates_dirs(tmp_path):
    """_build_output_path cree dirs si necessaire."""
    from run_sierra_enricher import _build_output_path

    base = tmp_path / "sierra"
    ts = _et_to_utc(2026, 6, 10, 14, 0)
    path = _build_output_path(base, "NQ", ts)

    expected_parent = base / "NQ"
    assert path.parent == expected_parent
    assert expected_parent.exists()
    assert path.name == "20260610_NQ_sierra_enriched.jsonl"


def test_build_output_path_different_dates(tmp_path):
    """Bars de dates differentes -> fichiers differents."""
    from run_sierra_enricher import _build_output_path

    base = tmp_path / "sierra"
    ts1 = _et_to_utc(2026, 6, 10, 14, 0)
    ts2 = _et_to_utc(2026, 6, 11, 14, 0)
    path1 = _build_output_path(base, "NQ", ts1)
    path2 = _build_output_path(base, "NQ", ts2)
    assert path1.name == "20260610_NQ_sierra_enriched.jsonl"
    assert path2.name == "20260611_NQ_sierra_enriched.jsonl"


# ────────────────────────────────────────────────────────────────────────────
# Tests integration end-to-end
# ────────────────────────────────────────────────────────────────────────────

def test_e2e_batch_enriched_output_parseable(tmp_path):
    """E2E : output JSONL est parseable et contient features attendues."""
    from run_sierra_enricher import run_batch_mode

    batch_file = _make_sierra_jsonl(tmp_path, n_bars=15)
    output_file = tmp_path / "enriched.jsonl"

    run_batch_mode(
        symbol="NQ",
        batch_file=batch_file,
        output_file=output_file,
    )

    # Re-parse output
    with open(output_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 15

    # Verifier features Phase 3 presentes sur derniere bar (post-cold-start)
    last = lines[-1]
    # Sierra natif preserve
    assert "close" in last
    assert "atr" in last
    # Phase 3 ajoute
    expected_phase3_keys = [
        "poc_migration_dir", "ctx_poc_migration_10",
        "bars_since_last_swing_high", "equal_highs_detected",
        "pdh", "pdl", "cash_high",
        "is_in_us_cash", "session_segment", "mins_et",
        "is_roll_day", "days_since_roll",
        "delta_div_buy", "delta_div_strength",
        "ctx_climax_signal", "ctx_vol_z_20",
    ]
    missing = [k for k in expected_phase3_keys if k not in last]
    assert not missing, f"Missing Phase 3 keys : {missing}"


# ────────────────────────────────────────────────────────────────────────────
# Tests live mode (R2 review code-reviewer agentId a4209bcd08629b740 10/06)
# Mock SierraLiveReader pour eviter dependance fichier reel + tail.
# ────────────────────────────────────────────────────────────────────────────

def _make_sierra_df(n_bars: int = 3, base_ts_ms: int = None) -> pd.DataFrame:
    """Helper : creer DataFrame Sierra natif simule pour tests live."""
    if base_ts_ms is None:
        base_ts_ms = int(_et_to_utc(2026, 6, 10, 10, 0).timestamp() * 1000)
    rows = []
    for i in range(n_bars):
        rows.append({
            "ts": base_ts_ms + i * 60_000,  # +1 min en ms
            "sym": "NQ",
            "close": 100.0 + i * 0.5,
            "bar_high": 100.5 + i * 0.5,
            "bar_low": 99.5 + i * 0.5,
            "delta_bar": 100.0,
            "total_vol": 1000.0,
            "atr": 2.0,
            "dist_cur_vpoc": 5.0,
            "dist_swing_high": 3.0,
            "dist_swing_low": 8.0,
        })
    return pd.DataFrame(rows)


def test_live_mode_max_iterations_exits(tmp_path, monkeypatch):
    """max_iterations limite la boucle live (anti boucle infinie tests)."""
    from unittest.mock import MagicMock
    import run_sierra_enricher

    # Mock SierraLiveReader pour retourner DataFrame stub
    mock_reader_instance = MagicMock()
    mock_reader_instance.load_rolling_window.return_value = _make_sierra_df(n_bars=2)
    monkeypatch.setattr(
        run_sierra_enricher, "SierraLiveReader",
        lambda **kwargs: mock_reader_instance,
    )

    stats = run_sierra_enricher.run_live_mode(
        symbol="NQ",
        output_dir=tmp_path / "sierra",
        poll_interval_sec=0.01,
        dry_run=True,
        max_iterations=3,
    )

    # Apres 3 iterations, exit propre
    assert stats["polls"] == 3
    # 2 bars enrichies au 1er poll, puis 0 (deja vues) aux 2-3
    assert stats["bars_enriched_total"] == 2


def test_live_mode_dedup_seen_ts(tmp_path, monkeypatch):
    """seen_ts evite reenrich des bars deja vues (idempotence)."""
    from unittest.mock import MagicMock
    import run_sierra_enricher

    df_same = _make_sierra_df(n_bars=3)
    mock_reader_instance = MagicMock()
    # Le reader retourne TOUJOURS le meme df (simule tail apres bar buffer)
    mock_reader_instance.load_rolling_window.return_value = df_same
    monkeypatch.setattr(
        run_sierra_enricher, "SierraLiveReader",
        lambda **kwargs: mock_reader_instance,
    )

    stats = run_sierra_enricher.run_live_mode(
        symbol="NQ",
        output_dir=tmp_path / "sierra",
        poll_interval_sec=0.01,
        dry_run=True,
        max_iterations=5,
    )

    # 5 polls, mais seulement 3 bars uniques par ts -> pas de double enrich
    assert stats["polls"] == 5
    assert stats["bars_enriched_total"] == 3, (
        f"Attendu 3 bars uniques enrichies (dedup seen_ts), "
        f"obtenu {stats['bars_enriched_total']}"
    )


def test_live_mode_reader_exception_increments_errors(tmp_path, monkeypatch):
    """Exception SierraLiveReader.load_rolling_window -> stats.errors + continue."""
    from unittest.mock import MagicMock
    import run_sierra_enricher

    mock_reader_instance = MagicMock()
    mock_reader_instance.load_rolling_window.side_effect = RuntimeError(
        "Simulated reader failure"
    )
    monkeypatch.setattr(
        run_sierra_enricher, "SierraLiveReader",
        lambda **kwargs: mock_reader_instance,
    )

    stats = run_sierra_enricher.run_live_mode(
        symbol="NQ",
        output_dir=tmp_path / "sierra",
        poll_interval_sec=0.01,
        dry_run=True,
        max_iterations=3,
    )

    # 3 polls -> 3 erreurs reader, mais pas de crash
    assert stats["polls"] == 3
    assert stats["errors"] == 3
    assert stats["bars_enriched_total"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
