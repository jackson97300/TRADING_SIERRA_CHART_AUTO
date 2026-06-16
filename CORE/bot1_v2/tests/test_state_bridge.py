"""Tests StateBridge Bot 1 v2 -> dashboard state.json.

Verifie que :
  - heartbeat() update updated_ts visible dans state.json
  - open_position() ajoute a open_by_symbol avec format compatible
  - close_position() retire de open + ajoute closed_today + pnl
  - rotate_day() reset closed_today + archive vers historique mensuel
  - Atomic write (pas de fichier corrompu si crash)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


def test_heartbeat_updates_timestamp(tmp_path):
    from CORE.bot1_v2.state_bridge import StateBridge

    p = tmp_path / "state.json"
    sb = StateBridge(path=p)
    sb.heartbeat()
    assert p.exists()
    state = json.loads(p.read_text(encoding="utf-8"))
    assert "updated_ts" in state
    assert isinstance(state["updated_ts"], float)
    # Doit etre close de now (a 5s pres)
    assert abs(state["updated_ts"] - time.time()) < 5.0
    assert state["closed_today"] == []
    assert state["open_by_symbol"] == {}


def test_open_position_adds_to_state(tmp_path):
    from CORE.bot1_v2.state_bridge import StateBridge

    p = tmp_path / "state.json"
    sb = StateBridge(path=p)
    sb.open_position(
        "ES", direction="LONG", entry_price=7600.0,
        sl_price=7596.0, tp_price=7610.0,
        sl_ticks=16, tp_ticks=40,
        signal_id="abc123", sl_wall="VAH", n_micros=1,
    )
    state = json.loads(p.read_text(encoding="utf-8"))
    assert "ES" in state["open_by_symbol"]
    pos = state["open_by_symbol"]["ES"]
    assert pos["direction"] == "LONG"
    assert pos["entry_price"] == 7600.0
    assert pos["sl_ticks"] == 16
    assert pos["tp_ticks"] == 40
    assert pos["sl_wall"] == "VAH"
    assert pos["schema_version"] == "trade_v2_ml_2026_04_22"
    # trade_id format : YYYYMMDD_N
    assert "_" in pos["trade_id"]


def test_close_position_moves_to_closed_today(tmp_path):
    from CORE.bot1_v2.state_bridge import StateBridge

    p = tmp_path / "state.json"
    sb = StateBridge(path=p)
    sb.open_position(
        "ES", direction="SHORT", entry_price=7600.0,
        sl_price=7604.0, tp_price=7590.0,
        sl_ticks=16, tp_ticks=40,
    )
    # Close avec PnL
    sb.close_position(
        "ES", exit_price=7590.5, exit_reason="TP_HIT",
        outcome="WIN", pnl_ticks=38.0, pnl_usd=190.0,
    )
    state = json.loads(p.read_text(encoding="utf-8"))
    assert "ES" not in state["open_by_symbol"]
    assert len(state["closed_today"]) == 1
    closed = state["closed_today"][0]
    assert closed["exit_price"] == 7590.5
    assert closed["pnl_usd"] == 190.0
    assert closed["outcome"] == "WIN"
    assert closed["exit_reason"] == "TP_HIT"
    assert "duration_sec" in closed


def test_close_unknown_symbol_returns_false(tmp_path):
    from CORE.bot1_v2.state_bridge import StateBridge

    p = tmp_path / "state.json"
    sb = StateBridge(path=p)
    result = sb.close_position("NQ", exit_price=30000.0)
    assert result is False


def test_rotate_day_resets_closed_archives_history(tmp_path):
    from CORE.bot1_v2.state_bridge import StateBridge

    p = tmp_path / "state.json"
    sb = StateBridge(path=p)
    # Add a closed trade
    sb.open_position("ES", direction="LONG", entry_price=7600.0,
                      sl_price=7596.0, tp_price=7610.0,
                      sl_ticks=16, tp_ticks=40)
    sb.close_position("ES", exit_price=7610.0, pnl_ticks=40.0, pnl_usd=200.0)
    assert len(sb.state["closed_today"]) == 1

    # Rotate vers nouveau jour
    sb.rotate_day("20260617")
    state = json.loads(p.read_text(encoding="utf-8"))
    assert state["date"] == "20260617"
    assert state["closed_today"] == []
    # Historique mensuel doit contenir le trade archive
    archive = tmp_path / "closed_202606.jsonl"
    assert archive.exists()
    archive_content = archive.read_text(encoding="utf-8").strip()
    assert "ES" in archive_content
    assert "pnl_usd" in archive_content


def test_load_existing_preserves_closed_today_same_date(tmp_path):
    from CORE.bot1_v2.state_bridge import StateBridge
    from datetime import datetime, timezone

    p = tmp_path / "state.json"
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    # Pre-write un state avec date=today + 1 trade closed
    existing = {
        "updated_ts": time.time(),
        "updated_iso": "2026-06-16T08:00:00+00:00",
        "date": today,
        "open_by_symbol": {},
        "closed_today": [
            {"symbol": "ES", "pnl_usd": 100.0, "trade_id": f"{today}_1"},
        ],
    }
    p.write_text(json.dumps(existing), encoding="utf-8")

    # Nouveau StateBridge sur ce path : doit preserver closed_today
    sb = StateBridge(path=p)
    assert len(sb.state["closed_today"]) == 1
    assert sb.state["closed_today"][0]["pnl_usd"] == 100.0


def test_atomic_write_no_partial_file_on_serialization_error(tmp_path):
    """Verify atomic write : tmp file cleanup si serialize fail."""
    from CORE.bot1_v2.state_bridge import StateBridge

    p = tmp_path / "state.json"
    sb = StateBridge(path=p)
    # Inject un objet non-serializable dans state pour forcer JSONEncodeError
    class NotSerializable: pass
    sb.state["bad"] = NotSerializable()
    result = sb._save()
    assert result is False
    # Pas de tmp leftover
    tmp_files = list(tmp_path.glob("state_*.tmp"))
    assert tmp_files == [], f"tmp leftover : {tmp_files}"
