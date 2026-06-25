"""Tests tools/bot4v2_sentinel.py - verification cross-day logs emission."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add tools to sys.path pour import
_TOOLS_ROOT = Path(__file__).parent.parent.parent / "tools"
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from bot4v2_sentinel import (  # noqa: E402
    audit_date,
    count_codes_in_file,
    date_range,
    format_human,
    main,
)


# ============================================================
# count_codes_in_file
# ============================================================


def test_count_codes_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    counter = count_codes_in_file(path, {"BOT4V2_ROUTER_FIRE"})
    assert counter == {}


def test_count_codes_nonexistent_file(tmp_path):
    path = tmp_path / "missing.jsonl"
    counter = count_codes_in_file(path, {"BOT4V2_ROUTER_FIRE"})
    assert counter == {}


def test_count_codes_basic(tmp_path):
    path = tmp_path / "logs.jsonl"
    entries = [
        {"code": "BOT4V2_ROUTER_FIRE", "ts": "X"},
        {"code": "BOT4V2_ROUTER_FIRE", "ts": "Y"},
        {"code": "BOT4V2_MAIN_BOOT", "ts": "Z"},
        {"code": "OTHER_CODE", "ts": "W"},
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    counter = count_codes_in_file(
        path, {"BOT4V2_ROUTER_FIRE", "BOT4V2_MAIN_BOOT"},
    )
    assert counter["BOT4V2_ROUTER_FIRE"] == 2
    assert counter["BOT4V2_MAIN_BOOT"] == 1
    assert "OTHER_CODE" not in counter


def test_count_codes_skips_malformed(tmp_path):
    path = tmp_path / "logs.jsonl"
    path.write_text(
        '{"code": "BOT4V2_ROUTER_FIRE"}\n'
        'NOT_JSON\n'
        '{"code": "BOT4V2_MAIN_BOOT"}\n',
        encoding="utf-8",
    )
    counter = count_codes_in_file(
        path, {"BOT4V2_ROUTER_FIRE", "BOT4V2_MAIN_BOOT"},
    )
    assert counter["BOT4V2_ROUTER_FIRE"] == 1
    assert counter["BOT4V2_MAIN_BOOT"] == 1


# ============================================================
# audit_date
# ============================================================


def test_audit_date_empty_logs_root(tmp_path):
    """Logs root vide + BOOT=0 -> NOT_RUN (R12 ULTRATHINK anti faux positif)."""
    audit = audit_date(tmp_path, "20260626")
    assert audit["status"] == "NOT_RUN"
    assert "reason" in audit
    assert audit["files_scanned"] == 0


def test_audit_date_boot_zero_returns_not_run(tmp_path):
    """R12 : BOOT manquant -> NOT_RUN, pas VALIDATION_MISS."""
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    # ROUTER_FIRE present mais BOOT absent
    (decisions_dir / "decisions_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_ROUTER_FIRE"}\n',
        encoding="utf-8",
    )
    audit = audit_date(tmp_path, "20260626")
    assert audit["status"] == "NOT_RUN"


def test_audit_date_with_real_files(tmp_path):
    """Audit avec logs presents -> OK si critical codes emis."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()

    # Critical : BOT4V2_MAIN_BOOT, BOT4V2_MAIN_SHUTDOWN
    (events_dir / "events_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_MAIN_BOOT"}\n'
        '{"code": "BOT4V2_MAIN_SHUTDOWN"}\n',
        encoding="utf-8",
    )
    # Critical : BOT4V2_ROUTER_FIRE
    (decisions_dir / "decisions_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_ROUTER_FIRE"}\n'
        '{"code": "BOT4V2_ROUTER_FIRE"}\n',
        encoding="utf-8",
    )
    # Critical : BOT4V2_RECONCILER_HEARTBEAT
    (execution_dir / "execution_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_RECONCILER_HEARTBEAT"}\n',
        encoding="utf-8",
    )

    audit = audit_date(tmp_path, "20260626")
    assert audit["status"] == "OK"
    assert audit["codes_missing_critical"] == []
    assert audit["codes_found"]["BOT4V2_MAIN_BOOT"] == 1
    assert audit["codes_found"]["BOT4V2_ROUTER_FIRE"] == 2


def test_audit_date_missing_one_critical_triggers_validation_miss(tmp_path):
    """BOOT present + SHUTDOWN/FIRE/HEARTBEAT manquant = VALIDATION_MISS."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    # Critical BOOT present mais SHUTDOWN absent
    (events_dir / "events_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_MAIN_BOOT"}\n',
        encoding="utf-8",
    )
    audit = audit_date(tmp_path, "20260626")
    assert audit["status"] == "VALIDATION_MISS"
    assert "BOT4V2_MAIN_SHUTDOWN" in audit["codes_missing_critical"]


def test_audit_date_naked_codes_not_in_missing_critical(tmp_path):
    """R11 : NAKED codes = 0 emit OK (sain). Pas dans missing_critical."""
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir()
    execution_dir = tmp_path / "execution"
    execution_dir.mkdir()

    (events_dir / "events_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_MAIN_BOOT"}\n'
        '{"code": "BOT4V2_MAIN_SHUTDOWN"}\n',
        encoding="utf-8",
    )
    (decisions_dir / "decisions_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_ROUTER_FIRE"}\n',
        encoding="utf-8",
    )
    (execution_dir / "execution_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_RECONCILER_HEARTBEAT"}\n',
        encoding="utf-8",
    )
    audit = audit_date(tmp_path, "20260626")
    # Tous critical core present + NAKED/KILL absent = OK (pas miss)
    assert audit["status"] == "OK"
    assert "BOT4V2_ROUTER_BRACKET_NAKED" not in audit["codes_missing_critical"]
    assert "BOT4V2_MAIN_KILL_SWITCH" not in audit["codes_missing_critical"]


# ============================================================
# date_range
# ============================================================


def test_date_range_same_day():
    dates = date_range("20260626", "20260626")
    assert dates == ["20260626"]


def test_date_range_3_days():
    dates = date_range("20260624", "20260626")
    assert dates == ["20260624", "20260625", "20260626"]


def test_date_range_reversed_returns_empty():
    dates = date_range("20260626", "20260624")
    assert dates == []


def test_date_range_month_boundary():
    dates = date_range("20260628", "20260702")
    assert dates == ["20260628", "20260629", "20260630", "20260701", "20260702"]


# ============================================================
# format_human
# ============================================================


def test_format_human_basic():
    audit = {
        "date": "20260626", "logs_root": "LOGS",
        "files_scanned": 5,
        "codes_found": {"BOT4V2_ROUTER_FIRE": 100},
        "codes_missing_critical": [],
        "status": "OK",
    }
    output = format_human(audit)
    assert "20260626" in output
    assert "BOT4V2_ROUTER_FIRE" in output
    assert "OK" in output


def test_format_human_validation_miss():
    audit = {
        "date": "20260626", "logs_root": "LOGS",
        "files_scanned": 0,
        "codes_found": {},
        "codes_missing_critical": ["BOT4V2_MAIN_BOOT"],
        "status": "VALIDATION_MISS",
    }
    output = format_human(audit)
    assert "VALIDATION_MISS" in output
    assert "CRITICAL CODES MISSING" in output
    assert "BOT4V2_MAIN_BOOT" in output


# ============================================================
# main() CLI
# ============================================================


def test_main_strict_returns_1_on_validation_miss(tmp_path):
    """--strict + critical missing -> exit code 1.

    R12 ULTRATHINK : il faut que BOOT >= 1 pour qu'on detecte VALIDATION_MISS
    (sinon NOT_RUN). Setup avec BOOT mais autres critical absents.
    """
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "events_20260626_bot4v2.jsonl").write_text(
        '{"code": "BOT4V2_MAIN_BOOT"}\n',  # SHUTDOWN, FIRE, HEARTBEAT absents
        encoding="utf-8",
    )
    rc = main([
        "--date", "20260626",
        "--logs-root", str(tmp_path),
        "--strict",
        "--json",
    ])
    assert rc == 1


def test_main_non_strict_returns_0_even_with_validation_miss(tmp_path):
    """--strict absent -> exit 0 meme si VALIDATION_MISS."""
    rc = main([
        "--date", "20260626",
        "--logs-root", str(tmp_path),
        "--json",
    ])
    assert rc == 0


def test_main_batch_since_until(tmp_path, capsys):
    """Batch mode --since/--until."""
    rc = main([
        "--since", "20260624",
        "--until", "20260626",
        "--logs-root", str(tmp_path),
        "--json",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    # JSON output multi-dates
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) == 3
