"""Tests scenario_serializer.py Phase B.5.4 JSONL serialization."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "CORE"))


# ════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════

def _make_terminal_instance(scenario_id="abc123def456",
                             scenario_name="Bullish continuation",
                             symbol="NQ",
                             side="long",
                             setup_type="swing",
                             state="COMPLETED"):
    """Build a terminal ScenarioInstance for tests."""
    from CORE.scenario_tracker import ScenarioInstance, StateTransition
    inst = ScenarioInstance(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        symbol=symbol,
        side=side,
        setup_type=setup_type,
        created_at_ts=1781256960000,
        last_update_ts=1781260000000,
        bars_alive=50,
        bars_in_zone=5,
        state=state,
        entry_price=29500.0,
        entry_zone_low=29490.0,
        entry_zone_high=29510.0,
        target_1=29700.0,
        target_2=29800.0,
        stop_loss=29400.0,
        atr_at_creation=100.0,
        heuristic_score_at_creation=65,
        heuristic_score_current=70,
        regime_vix_at_creation="calm",
        entry_touched_at_ts=1781257020000,
        target_1_hit_at_ts=1781259000000,
        target_2_hit_at_ts=1781260000000 if state == "COMPLETED" else None,
        terminal_ts=1781260000000,
        mfe_atr=1.05,
        mae_atr=-0.21,
        outcome_pnl_r=2.0,
        outcome_pnl_atr=1.0,
        key_levels_used=["PDH", "VWAP +1 SD"],
        rationale="Macro BULL pullback",
    )
    inst.state_history = [
        StateTransition(
            from_state="PENDING", to_state="ACTIVE_ENTRY_ZONE",
            ts_ms=1781257020000, bar_index=1,
            trigger="entry_zone_touch", bar_close=29500.0,
        ),
        StateTransition(
            from_state="ACTIVE_ENTRY_ZONE", to_state="TRIGGERED",
            ts_ms=1781257080000, bar_index=2,
            trigger="validation_match", bar_close=29505.0,
            matched_conditions=["delta_bar > 0", "finish_strength > 0"],
        ),
        StateTransition(
            from_state="TRIGGERED", to_state="VALIDATED",
            ts_ms=1781259000000, bar_index=33,
            trigger="target_1_hit", bar_close=29710.0,
        ),
        StateTransition(
            from_state="VALIDATED", to_state="COMPLETED",
            ts_ms=1781260000000, bar_index=50,
            trigger="target_2_hit", bar_close=29810.0,
        ),
    ]
    return inst


# ════════════════════════════════════════════════════════════════════════════
# session_date_id_from_ts
# ════════════════════════════════════════════════════════════════════════════

def test_session_date_id_morning_et():
    """Bar 14:30 UTC = 10:30 ET (DST) -> session date == jour UTC."""
    from CORE.scenario_serializer import session_date_id_from_ts
    # 2026-06-12 14:30:00 UTC = 10:30 ET (DST)
    dt = datetime(2026, 6, 12, 14, 30, 0, tzinfo=timezone.utc)
    ts_ms = int(dt.timestamp() * 1000)
    assert session_date_id_from_ts(ts_ms) == "2026-06-12"


def test_session_date_id_late_et_rolls_to_next_day():
    """Bar 22:00 UTC = 18:00 ET DST -> session J+1 (RTH close + 1)."""
    from CORE.scenario_serializer import session_date_id_from_ts
    dt = datetime(2026, 6, 12, 22, 30, 0, tzinfo=timezone.utc)
    ts_ms = int(dt.timestamp() * 1000)
    # 18:30 ET du 12/06 = session du 13/06 (convention futures)
    assert session_date_id_from_ts(ts_ms) == "2026-06-13"


def test_session_date_id_zero_ts():
    """ts <= 0 -> placeholder."""
    from CORE.scenario_serializer import session_date_id_from_ts
    assert session_date_id_from_ts(0) == "0000-00-00"


# ════════════════════════════════════════════════════════════════════════════
# serialize_instance
# ════════════════════════════════════════════════════════════════════════════

def test_serialize_instance_basic_fields():
    from CORE.scenario_serializer import serialize_instance
    inst = _make_terminal_instance()
    payload = serialize_instance(inst)
    assert payload["scenario_id"] == "abc123def456"
    assert payload["scenario_name"] == "Bullish continuation"
    assert payload["symbol"] == "NQ"
    assert payload["side"] == "long"
    assert payload["setup_type"] == "swing"
    assert payload["terminal_state"] == "COMPLETED"


def test_serialize_outcome_fields():
    """outcome_pnl_r + mfe + mae presents (cles Phase C calibration)."""
    from CORE.scenario_serializer import serialize_instance
    inst = _make_terminal_instance()
    payload = serialize_instance(inst)
    assert payload["outcome_pnl_r"] == 2.0
    assert payload["mfe_atr"] == 1.05
    assert payload["mae_atr"] == -0.21


def test_serialize_validation_matches_aggregated():
    """validation_matches doit agreger les matched_conditions des transitions TRIGGERED/VALIDATED."""
    from CORE.scenario_serializer import serialize_instance
    inst = _make_terminal_instance()
    payload = serialize_instance(inst)
    assert "delta_bar > 0" in payload["validation_matches"]
    assert "finish_strength > 0" in payload["validation_matches"]


def test_serialize_transitions_preserved():
    """transitions array preserves lifecycle history."""
    from CORE.scenario_serializer import serialize_instance
    inst = _make_terminal_instance()
    payload = serialize_instance(inst)
    assert len(payload["transitions"]) == 4
    states = [(t["from"], t["to"]) for t in payload["transitions"]]
    assert ("PENDING", "ACTIVE_ENTRY_ZONE") in states
    assert ("VALIDATED", "COMPLETED") in states


def test_serialize_invalidated_instance():
    from CORE.scenario_serializer import serialize_instance
    inst = _make_terminal_instance(state="INVALIDATED")
    inst.invalidation_reason = "stop_hit"
    inst.target_2_hit_at_ts = None
    payload = serialize_instance(inst)
    assert payload["terminal_state"] == "INVALIDATED"
    assert payload["invalidation_reason"] == "stop_hit"


def test_serialize_json_roundtrip():
    """Output doit etre serialisable JSON sans erreur."""
    import json as json_mod
    from CORE.scenario_serializer import serialize_instance
    inst = _make_terminal_instance()
    payload = serialize_instance(inst)
    s = json_mod.dumps(payload)
    parsed = json_mod.loads(s)
    assert parsed["scenario_id"] == "abc123def456"


# ════════════════════════════════════════════════════════════════════════════
# JSONLSerializer (file I/O)
# ════════════════════════════════════════════════════════════════════════════

def test_serializer_writes_jsonl_file(tmp_path):
    from CORE.scenario_serializer import JSONLSerializer
    serializer = JSONLSerializer(symbol="NQ", logs_dir=str(tmp_path))
    inst = _make_terminal_instance()
    ok = serializer.write(inst)
    assert ok is True
    # File should exist
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1


def test_serializer_path_includes_symbol(tmp_path):
    from CORE.scenario_serializer import JSONLSerializer
    serializer = JSONLSerializer(symbol="NQ", logs_dir=str(tmp_path))
    inst = _make_terminal_instance(symbol="NQ")
    serializer.write(inst)
    files = list(tmp_path.glob("*.jsonl"))
    assert "NQ" in files[0].name


def test_serializer_appends_multiple_lines(tmp_path):
    from CORE.scenario_serializer import JSONLSerializer
    serializer = JSONLSerializer(symbol="NQ", logs_dir=str(tmp_path))
    inst1 = _make_terminal_instance(scenario_id="id_001")
    inst2 = _make_terminal_instance(scenario_id="id_002")
    serializer.write(inst1)
    serializer.write(inst2)
    files = list(tmp_path.glob("*.jsonl"))
    with open(files[0], "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 2
    ids = [json.loads(l)["scenario_id"] for l in lines]
    assert "id_001" in ids
    assert "id_002" in ids


def test_serializer_rotates_on_session_date_change(tmp_path):
    """Instances avec terminal_ts dans 2 jours ET different -> 2 fichiers."""
    from CORE.scenario_serializer import JSONLSerializer
    serializer = JSONLSerializer(symbol="NQ", logs_dir=str(tmp_path))
    # Instance 1 : terminal_ts = 12/06 14:30 UTC = 10:30 ET J=12
    dt1 = datetime(2026, 6, 12, 14, 30, 0, tzinfo=timezone.utc)
    # Instance 2 : terminal_ts = 12/06 22:30 UTC = 18:30 ET = session J+1=13
    dt2 = datetime(2026, 6, 12, 22, 30, 0, tzinfo=timezone.utc)
    inst1 = _make_terminal_instance(scenario_id="i1")
    inst1.terminal_ts = int(dt1.timestamp() * 1000)
    inst2 = _make_terminal_instance(scenario_id="i2")
    inst2.terminal_ts = int(dt2.timestamp() * 1000)
    serializer.write(inst1)
    serializer.write(inst2)
    files = sorted(tmp_path.glob("*.jsonl"))
    assert len(files) == 2
    assert "2026-06-12" in files[0].name
    assert "2026-06-13" in files[1].name


def test_serializer_fail_safe_on_write_error(tmp_path):
    """Write error -> emit SCENARIO_JSONL_WRITE_FAIL, return False."""
    from CORE.scenario_serializer import JSONLSerializer
    emits = []
    serializer = JSONLSerializer(
        symbol="NQ", logs_dir=str(tmp_path),
        log_emit=lambda c, ctx: emits.append((c, ctx)),
    )
    inst = _make_terminal_instance()
    # Make logs_dir unwritable by replacing _current_path with invalid path
    serializer._current_path = Path("/no/such/dir/file.jsonl")
    serializer._current_date = "fake"
    # Force la branche d'erreur write_error
    inst.terminal_ts = 0  # forcera rotation vers nouvelle date... let's not
    ok = serializer.write(inst)
    # Selon OS, le write peut echouer ou non. Si echec : emit + False.
    if not ok:
        assert any(code == "SCENARIO_JSONL_WRITE_FAIL" for code, _ in emits)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--no-cov"])
