"""Tests Phase 4.1 sierra_pipeline.py (Sierra Migration 10/06/2026)."""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))

ET = ZoneInfo("America/New_York")


def _make_sierra_bar(
    ts_utc: datetime,
    close: float = 100.0,
    bar_high: float = 101.0,
    bar_low: float = 99.0,
    delta_bar: float = 100.0,
    total_vol: float = 1000.0,
    atr: float = 2.0,
    dist_cur_vpoc: float = 5.0,
    dist_swing_high: float = 3.0,
    dist_swing_low: float = 8.0,
    **kwargs,
) -> dict:
    """Helper : construire une bar Sierra natif simulee."""
    bar = {
        "ts_utc": ts_utc.isoformat(),
        "close": close,
        "bar_high": bar_high,
        "bar_low": bar_low,
        "delta_bar": delta_bar,
        "total_vol": total_vol,
        "atr": atr,
        "dist_cur_vpoc": dist_cur_vpoc,
        "dist_swing_high": dist_swing_high,
        "dist_swing_low": dist_swing_low,
    }
    bar.update(kwargs)
    return bar


def _et_to_utc(year, month, day, hour, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET).astimezone(timezone.utc)


# ────────────────────────────────────────────────────────────────────────────
# Tests integration enrich_bar
# ────────────────────────────────────────────────────────────────────────────

def test_enrich_bar_returns_phase3_features():
    """enrich_bar ajoute les features Phase 3 au sierra_bar."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    bar = _make_sierra_bar(ts)

    enriched = pipeline.enrich_bar(bar)

    # Sierra natif preserve
    assert enriched["close"] == 100.0
    assert enriched["atr"] == 2.0
    # Phase 3 features ajoutees (au moins quelques cles connues)
    assert "poc_migration_dir" in enriched
    assert "bars_since_last_swing_high" in enriched
    assert "pdh" in enriched
    assert "session_segment" in enriched
    assert "is_roll_day" in enriched
    assert "delta_div_buy" in enriched
    assert "ctx_climax_signal" in enriched
    # Meta orchestrateur
    assert enriched["_phase3_enriched"] is True
    assert enriched["_phase3_bars_processed"] == 1


def test_enrich_bar_cold_start_features_nan():
    """Premiere bar : features stateful en cold-start (NaN/False)."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    bar = _make_sierra_bar(ts)
    enriched = pipeline.enrich_bar(bar)

    # poc_migration cold-start = NaN
    assert math.isnan(enriched["poc_migration_dir"])
    # ctx_rolling cold-start = NaN ou 0
    assert math.isnan(enriched["ctx_vol_z_20"]) or enriched["ctx_vol_z_20"] == 0


def test_enrich_bar_stateful_progression():
    """Apres N bars, features stateful sont calculees."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    base_ts = _et_to_utc(2026, 6, 10, 10, 0)

    # 12 bars croissantes
    for i in range(12):
        ts = base_ts.replace(minute=i)
        bar = _make_sierra_bar(
            ts,
            close=100.0 + i * 0.5,
            bar_high=100.5 + i * 0.5,
            bar_low=99.5 + i * 0.5,
            dist_cur_vpoc=10.0 - i * 0.5,  # VPOC se rapproche
            dist_swing_high=max(0.1, 5.0 - i * 0.4),
        )
        enriched = pipeline.enrich_bar(bar)

    # Apres 12 bars, ctx_vol_z_20 doit etre calcule
    assert not math.isnan(enriched["ctx_vol_z_20"])
    # poc_migration_dir : VPOC se rapproche (dist diminue) -> dir
    assert enriched["poc_migration_dir"] in (-1, 0, 1)


# ────────────────────────────────────────────────────────────────────────────
# Tests cross-day reset
# ────────────────────────────────────────────────────────────────────────────

def test_cross_day_reset_at_18h_et():
    """Cross-day a 18:00 ET reset les Calculator stateful."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")

    # 5 bars jour 1
    for i in range(5):
        ts = _et_to_utc(2026, 6, 10, 10 + i, 0)
        bar = _make_sierra_bar(ts, close=100.0 + i)
        pipeline.enrich_bar(bar)

    stats_before = pipeline.get_stats()
    assert stats_before["cross_day_resets"] == 0

    # Bar 18:30 ET = nouveau trading_date
    ts_reset = _et_to_utc(2026, 6, 10, 18, 30)
    bar_reset = _make_sierra_bar(ts_reset, close=105.0)
    pipeline.enrich_bar(bar_reset)

    stats_after = pipeline.get_stats()
    assert stats_after["cross_day_resets"] == 1


def test_no_cross_day_reset_same_day():
    """Bars dans meme trading_date : pas de reset."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")

    for i in range(5):
        ts = _et_to_utc(2026, 6, 10, 10 + i, 0)
        bar = _make_sierra_bar(ts, close=100.0 + i)
        pipeline.enrich_bar(bar)

    assert pipeline.get_stats()["cross_day_resets"] == 0


# ────────────────────────────────────────────────────────────────────────────
# Tests resolve timestamp
# ────────────────────────────────────────────────────────────────────────────

def test_extract_ts_from_ts_utc_iso():
    """ts_utc ISO string -> datetime UTC."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    bar = _make_sierra_bar(_et_to_utc(2026, 6, 10, 10, 0))
    enriched = pipeline.enrich_bar(bar)
    # Pas de crash, features ajoutees
    assert "session_segment" in enriched


def test_extract_ts_from_ts_event_ns():
    """ts_event_ns Databento nanoseconds -> datetime UTC."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    # 10 juin 2026 14:00 UTC en nanoseconds
    ts_ns = int(_et_to_utc(2026, 6, 10, 10, 0).timestamp() * 1e9)
    bar = {
        "ts_event_ns": ts_ns,
        "close": 100.0, "bar_high": 101.0, "bar_low": 99.0,
        "delta_bar": 100.0, "total_vol": 1000.0, "atr": 2.0,
        "dist_cur_vpoc": 5.0, "dist_swing_high": 3.0, "dist_swing_low": 8.0,
    }
    enriched = pipeline.enrich_bar(bar)
    assert "session_segment" in enriched


def test_extract_ts_from_ts_milliseconds():
    """ts en millisecondes (Sierra DMP convention) -> datetime UTC.

    Sierra DMP utilise ts en ms (13 chiffres) dans les JSONL DMP_Writer.
    Cf sierra_live_io.py:_read_new_lines (assertion ts en ms).
    """
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    # 10 juin 2026 14:00 UTC en ms = secondes * 1000
    ts_ms = int(_et_to_utc(2026, 6, 10, 10, 0).timestamp() * 1000)
    bar = {
        "ts": ts_ms,
        "close": 100.0, "bar_high": 101.0, "bar_low": 99.0,
        "delta_bar": 100.0, "total_vol": 1000.0, "atr": 2.0,
        "dist_cur_vpoc": 5.0, "dist_swing_high": 3.0, "dist_swing_low": 8.0,
    }
    enriched = pipeline.enrich_bar(bar)
    # Pas de crash, features ajoutees
    assert "session_segment" in enriched


def test_extract_ts_missing_raises():
    """Aucun timestamp -> ValueError FAIL LOUD."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    bar = {
        "close": 100.0, "bar_high": 101.0, "bar_low": 99.0,
        "delta_bar": 100.0, "total_vol": 1000.0, "atr": 2.0,
        "dist_cur_vpoc": 5.0, "dist_swing_high": 3.0, "dist_swing_low": 8.0,
    }
    with pytest.raises(ValueError, match="timestamp UTC"):
        pipeline.enrich_bar(bar)


# ────────────────────────────────────────────────────────────────────────────
# Tests defensive : champs Sierra manquants
# ────────────────────────────────────────────────────────────────────────────

def test_missing_optional_fields_dont_crash():
    """Champs optionnels Sierra (vwap_d, finish_strength, etc.) absents -> pas crash."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    ts = _et_to_utc(2026, 6, 10, 10, 0)
    # Bar minimaliste (que les requis)
    bar = _make_sierra_bar(ts)
    enriched = pipeline.enrich_bar(bar)
    # Pas crash, features ajoutees
    assert "ctx_climax_signal" in enriched
    # vwap_d absent -> ctx_dist_vwap_velocity NaN
    assert math.isnan(enriched["ctx_dist_vwap_velocity"])


# ────────────────────────────────────────────────────────────────────────────
# Tests batch mode
# ────────────────────────────────────────────────────────────────────────────

def test_enrich_batch_dataframe():
    """enrich_batch_dataframe sur DataFrame Sierra historique."""
    from CORE.sierra_pipeline import enrich_batch_dataframe

    base_ts = _et_to_utc(2026, 6, 10, 10, 0)
    rows = []
    for i in range(15):
        ts = base_ts.replace(minute=i)
        rows.append(_make_sierra_bar(
            ts,
            close=100.0 + i * 0.5,
            bar_high=100.5 + i * 0.5,
            bar_low=99.5 + i * 0.5,
        ))
    df = pd.DataFrame(rows)
    result = enrich_batch_dataframe(df, symbol="NQ")

    # 113 features Phase 3 ajoutees (au moins quelques unes)
    assert "poc_migration_dir" in result.columns
    assert "ctx_vol_z_20" in result.columns
    assert "is_roll_day" in result.columns
    # Sierra natif preserve
    assert "close" in result.columns
    assert len(result) == 15


def test_enrich_batch_missing_ts_col_raises():
    """ts_col manquant -> ValueError."""
    from CORE.sierra_pipeline import enrich_batch_dataframe

    df = pd.DataFrame({"close": [100.0]})
    with pytest.raises(ValueError, match="ts_utc"):
        enrich_batch_dataframe(df, symbol="NQ")


# ────────────────────────────────────────────────────────────────────────────
# Tests stats orchestrateur
# ────────────────────────────────────────────────────────────────────────────

def test_get_stats_after_processing():
    """get_stats() retourne stats coherentes."""
    from CORE.sierra_pipeline import SierraPipelineOrchestrator

    pipeline = SierraPipelineOrchestrator(symbol="NQ")
    for i in range(3):
        ts = _et_to_utc(2026, 6, 10, 10 + i, 0)
        bar = _make_sierra_bar(ts)
        pipeline.enrich_bar(bar)

    stats = pipeline.get_stats()
    assert stats["symbol"] == "NQ"
    assert stats["bars_processed"] == 3
    assert stats["cross_day_resets"] == 0
    assert stats["current_trading_date"] == "2026-06-10"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
