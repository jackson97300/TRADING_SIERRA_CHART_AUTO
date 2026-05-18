"""tests/bot3/test_shadow_mode.py - Tests Phase 3 ShadowMode.

Tests pytest pour `CORE/bot3_shadow_mode.py`.
Coverage cible >= 85%. Tests JSONL append + divergence detection + emit.

HISTORY
2026-05-18 PM : creation tests Phase 3 J+2 (logger + divergence pure function)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from CORE.bot3_shadow_mode import (
    ShadowComparison,
    ShadowModeLogger,
    detect_divergence,
)


# ════════════════════════════════════════════════════════════════════════════
# detect_divergence (pure function)
# ════════════════════════════════════════════════════════════════════════════


def test_divergence_legacy_long_narrative_short():
    """legacy LONG vs narrative SHORT = divergence."""
    assert detect_divergence("LONG", "SHORT") is True


def test_divergence_legacy_short_narrative_long():
    """legacy SHORT vs narrative LONG = divergence."""
    assert detect_divergence("SHORT", "LONG") is True


def test_no_divergence_same_side():
    """legacy = narrative = pas de divergence."""
    assert detect_divergence("LONG", "LONG") is False
    assert detect_divergence("SHORT", "SHORT") is False


def test_no_divergence_narrative_no_trade():
    """narrative NO_TRADE = abstention = pas de divergence (legacy peut LONG/SHORT)."""
    assert detect_divergence("LONG", "NO_TRADE") is False
    assert detect_divergence("SHORT", "NO_TRADE") is False


# ════════════════════════════════════════════════════════════════════════════
# ShadowModeLogger JSONL
# ════════════════════════════════════════════════════════════════════════════


def test_logger_appends_jsonl_line(tmp_path: Path):
    """Logger ecrit 1 ligne JSON par log_comparison."""
    logger = ShadowModeLogger(output_dir=tmp_path)
    cmp = ShadowComparison(
        ts="2026-05-18T13:30:00Z", symbol="ES",
        level_name="MQ_PUT", level_nature="support",
        narrative_state="OPEN_DRIVE_UP",
        legacy_side="LONG", narrative_side="LONG",
        narrative_scenario_id="S01", narrative_confidence=0.85,
        is_divergence=False,
    )
    logger.log_comparison(cmp)

    fpath = tmp_path / "shadow_divergences_20260518.jsonl"
    assert fpath.exists()
    lines = fpath.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["sym"] == "ES"
    assert record["legacy_side"] == "LONG"
    assert record["narrative_side"] == "LONG"
    assert record["divergence"] is False


def test_logger_emits_event_on_divergence(tmp_path: Path):
    """log_comparison avec is_divergence=True emit BOT3_SHADOW_DIVERGENCE."""
    logger = ShadowModeLogger(output_dir=tmp_path)
    captured: list[tuple[str, dict]] = []

    def cap(code, **ctx):
        captured.append((code, ctx))

    cmp = ShadowComparison(
        ts="2026-05-18T13:30:00Z", symbol="NQ",
        level_name="MQ_CALL", level_nature="resistance",
        narrative_state="EXHAUSTION_TOP",
        legacy_side="LONG", narrative_side="SHORT",
        narrative_scenario_id="S09_EXHAUSTION_TOP_short",
        narrative_confidence=0.65,
        is_divergence=True,
    )
    logger.log_comparison(cmp, log_fn=cap)

    # Emit BOT3_SHADOW_DIVERGENCE
    assert any(c == "BOT3_SHADOW_DIVERGENCE" for c, _ in captured)


def test_logger_groups_by_date(tmp_path: Path):
    """Logger separe par fichier YYYYMMDD."""
    logger = ShadowModeLogger(output_dir=tmp_path)
    cmp_d1 = ShadowComparison(
        ts="2026-05-18T13:30:00Z", symbol="ES",
        level_name="MQ_PUT", level_nature="support",
        narrative_state="OPEN_DRIVE_UP",
        legacy_side="LONG", narrative_side="LONG",
        narrative_scenario_id="S01", narrative_confidence=0.85,
        is_divergence=False,
    )
    cmp_d2 = ShadowComparison(
        ts="2026-05-19T13:30:00Z", symbol="ES",
        level_name="MQ_PUT", level_nature="support",
        narrative_state="TREND_UP_CONTINUATION",
        legacy_side="LONG", narrative_side="LONG",
        narrative_scenario_id="S03", narrative_confidence=0.80,
        is_divergence=False,
    )
    logger.log_comparison(cmp_d1)
    logger.log_comparison(cmp_d2)

    assert (tmp_path / "shadow_divergences_20260518.jsonl").exists()
    assert (tmp_path / "shadow_divergences_20260519.jsonl").exists()
