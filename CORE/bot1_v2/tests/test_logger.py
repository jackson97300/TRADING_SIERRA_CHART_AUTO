"""Tests logger Bot 1 v2 (catalog + JSONL decisions dedie).

Verifie regle souveraine LOGS TRACABILITE (01/05/2026) :
  - Codes BOT1V2_* sont resolvable via log_catalog
  - emit() ecrit dans LOGS/<cat>/*_bot1v2.jsonl avec ctx
  - log_decision_jsonl ecrit dans LOGS/bot1_v2_decisions/*.jsonl avec verdict
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


BOT1V2_CODES = (
    "BOT1V2_BOOT",
    "BOT1V2_SHUTDOWN",
    "BOT1V2_STATE_LOAD",
    "BOT1V2_DAY_ROLLOVER",
    "BOT1V2_HEARTBEAT",
    "BOT1V2_BAR_STALE",
    "BOT1V2_LOOP_EXCEPTION",
    "BOT1V2_DTC_CONNECTED",
    "BOT1V2_DTC_FALLBACK_DRYRUN",
    "BOT1V2_SKIP_HAS_POSITION",
    "BOT1V2_GATE_SESSION_BLOCK",
    "BOT1V2_GATE_DAILY_BLOCK",
    "BOT1V2_NOT_TRADABLE",
    "BOT1V2_TRADABLE",
    "BOT1V2_ORDER_SENT",
    "BOT1V2_ORDER_FAIL",
)


def test_all_16_codes_in_catalog():
    """16/16 codes BOT1V2_* presents + resolvables."""
    from CORE.log_catalog import LOG_CODES, resolve, LogLevel
    for code in BOT1V2_CODES:
        assert code in LOG_CODES, f"{code} absent du catalog"
        level, category, template = resolve(code)
        assert isinstance(level, LogLevel)
        assert category in ("events", "execution", "decisions", "trading")
        assert isinstance(template, str) and template


def test_codes_categories_correct():
    """Verifie repartition categorielle : execution pour DTC/order, decisions pour gates."""
    from CORE.log_catalog import resolve
    expected_cats = {
        "BOT1V2_BOOT": "events",
        "BOT1V2_SHUTDOWN": "events",
        "BOT1V2_HEARTBEAT": "events",
        "BOT1V2_DTC_CONNECTED": "execution",
        "BOT1V2_DTC_FALLBACK_DRYRUN": "execution",
        "BOT1V2_ORDER_SENT": "execution",
        "BOT1V2_ORDER_FAIL": "execution",
        "BOT1V2_GATE_SESSION_BLOCK": "decisions",
        "BOT1V2_GATE_DAILY_BLOCK": "decisions",
        "BOT1V2_NOT_TRADABLE": "decisions",
        "BOT1V2_TRADABLE": "decisions",
    }
    for code, expected_cat in expected_cats.items():
        _, cat, _ = resolve(code)
        assert cat == expected_cat, f"{code}: cat={cat} expected {expected_cat}"


def test_critical_codes_have_critique_level():
    """ORDER_FAIL + LOOP_EXCEPTION = CRITIQUE (Discord auto + error_file)."""
    from CORE.log_catalog import resolve, LogLevel
    for code in ("BOT1V2_ORDER_FAIL", "BOT1V2_LOOP_EXCEPTION"):
        level, _, _ = resolve(code)
        assert level == LogLevel.CRITIQUE, f"{code} doit etre CRITIQUE"


def test_majeur_codes_correct():
    """DAILY_BLOCK + DTC_FALLBACK = MAJEUR (Discord auto, sans mention)."""
    from CORE.log_catalog import resolve, LogLevel
    for code in ("BOT1V2_GATE_DAILY_BLOCK", "BOT1V2_DTC_FALLBACK_DRYRUN"):
        level, _, _ = resolve(code)
        assert level == LogLevel.MAJEUR, f"{code} doit etre MAJEUR"


def test_emit_writes_jsonl_with_ctx(tmp_path, monkeypatch):
    """emit() ecrit JSONL avec code + ctx + msg_fr."""
    monkeypatch.setenv("MIA_LOG_DIR", str(tmp_path))
    # Re-import pour utiliser le nouveau MIA_LOG_DIR
    import importlib
    import CORE.logging_v2 as logging_v2_mod
    importlib.reload(logging_v2_mod)
    log = logging_v2_mod.get_logger("test", process="bot1v2_test")

    log.emit("BOT1V2_BOOT", dry_run=False, symbols="ES,NQ", trade_account="Sim2")

    events_dir = tmp_path / "events"
    files = list(events_dir.glob("events_*_bot1v2_test.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip()
    entry = json.loads(content)
    assert entry["code"] == "BOT1V2_BOOT"
    assert entry["level"] == "INFO"
    assert entry["cat"] == "events"
    assert entry["ctx"]["dry_run"] is False
    assert entry["ctx"]["trade_account"] == "Sim2"
    assert "ES,NQ" in entry["msg_fr"]


def test_decisions_jsonl_writes_verdict_complete(tmp_path, monkeypatch):
    """log_decision_jsonl ecrit verdict mirror + sltp + decision dans JSONL dedie."""
    monkeypatch.setenv("MIA_LOG_DIR", str(tmp_path))
    # Re-import pour reinit _DECISIONS_DIR
    import importlib
    import CORE.bot1_v2.logger as logger_mod
    importlib.reload(logger_mod)

    from CORE.bot1_v2.cluster import ClusterDecision
    from CORE.bot1_v2.dashboard_mirror import MirrorVerdict, VetoFired
    from CORE.bot1_v2.risk.sl_tp import SLTPResult

    verdict = MirrorVerdict(
        action="VENTE", direction="SHORT", ready_to_arm=False,
        bull_pts=0, bear_pts=4, bias_score=-0.7, bias_label="BEARISH",
        mtf_bulls=0, mtf_bears=4, mtf_neutres=0, mtf_verdict="ALIGNE",
        vetos=(VetoFired(name="CLIMAX_WYCKOFF", reason="rare event", value=True),),
        quality_misses=(),
        stars_count=6, stars_total=7,
        skip_reason="VETO:CLIMAX_WYCKOFF",
        vix_level=18.5, rvol_zscore=2.1, ctx_climax_signal=True,
    )
    decision = ClusterDecision(
        tradable=False, skip_reason="VETO:CLIMAX_WYCKOFF",
        signal_id="abc123", direction="SHORT", entry_price=7625.0,
        symbol="ES", mirror=verdict, sltp=None,
        stars_count=6, stars_total=7,
    )

    logger_mod.log_decision_jsonl(
        bar_ts=1781560800000, symbol="ES",
        mirror=verdict, sltp=None, decision=decision, executed=False,
    )

    dec_dir = tmp_path / "bot1_v2_decisions"
    files = list(dec_dir.glob("bot1_v2_decisions_*.jsonl"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert entry["symbol"] == "ES"
    assert entry["bar_ts"] == 1781560800000
    assert entry["tradable"] is False
    assert entry["skip_reason"] == "VETO:CLIMAX_WYCKOFF"
    assert entry["executed"] is False
    assert entry["verdict"]["direction"] == "SHORT"
    assert entry["verdict"]["stars_count"] == 6
    assert len(entry["verdict"]["vetos"]) == 1
    assert entry["verdict"]["vetos"][0]["name"] == "CLIMAX_WYCKOFF"
    assert entry["verdict"]["ctx_climax_signal"] is True


def test_decisions_jsonl_append_mode(tmp_path, monkeypatch):
    """Plusieurs appels = plusieurs lignes (append-only, jamais d'overwrite)."""
    monkeypatch.setenv("MIA_LOG_DIR", str(tmp_path))
    import importlib
    import CORE.bot1_v2.logger as logger_mod
    importlib.reload(logger_mod)

    from CORE.bot1_v2.cluster import ClusterDecision

    for i in range(3):
        d = ClusterDecision(
            tradable=False, skip_reason=f"TEST_{i}",
            signal_id=f"sig{i}", symbol="ES",
        )
        logger_mod.log_decision_jsonl(
            bar_ts=1781560800000 + i, symbol="ES",
            mirror=None, sltp=None, decision=d, executed=False,
        )

    dec_dir = tmp_path / "bot1_v2_decisions"
    files = list(dec_dir.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 3
    for i, line in enumerate(lines):
        entry = json.loads(line)
        assert entry["skip_reason"] == f"TEST_{i}"
        assert entry["signal_id"] == f"sig{i}"
