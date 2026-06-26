"""Tests bot4_v2/main/__main__ entry point + ReplayStream + wiring."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot4_v2.main.__main__ import (
    ReplayStream,
    _DryRunBackend,
    build_loop,
    build_registry,
    main,
    parse_args,
)
from bot4_v2.main.bot_main_v2 import StreamEnded


# ============================================================
# parse_args
# ============================================================


def test_parse_args_defaults():
    args = parse_args([])
    assert args.symbols == "NQ"
    assert args.trade_account == "Sim5"
    assert args.max_cycles == 0
    assert args.no_dry_run is False  # dry_run par defaut
    assert args.heartbeat_sec == 30.0
    assert args.max_concurrent == 3


def test_parse_args_custom_symbols():
    args = parse_args(["--symbols", "NQ,ES,MGC"])
    assert args.symbols == "NQ,ES,MGC"


def test_parse_args_replay_path():
    args = parse_args(["--replay", "DATA/sample.jsonl"])
    assert args.replay == "DATA/sample.jsonl"


def test_parse_args_no_dry_run_flag():
    args = parse_args(["--no-dry-run"])
    assert args.no_dry_run is True


# ============================================================
# ReplayStream
# ============================================================


def test_replay_stream_reads_bars(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"high": 1, "low": 0, "close": 0.5}\n'
        '{"high": 2, "low": 1, "close": 1.5}\n',
        encoding="utf-8",
    )
    stream = ReplayStream(path)
    bar1 = stream.next_bar()
    bar2 = stream.next_bar()
    assert bar1 == {"high": 1, "low": 0, "close": 0.5}
    assert bar2 == {"high": 2, "low": 1, "close": 1.5}
    # EOF -> StreamEnded
    with pytest.raises(StreamEnded):
        stream.next_bar()


def test_replay_stream_skips_empty_lines(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"a": 1}\n'
        '\n'
        '{"b": 2}\n',
        encoding="utf-8",
    )
    stream = ReplayStream(path)
    bar1 = stream.next_bar()
    skipped = stream.next_bar()  # empty line
    bar3 = stream.next_bar()
    assert bar1 == {"a": 1}
    assert skipped is None
    assert bar3 == {"b": 2}


def test_replay_stream_skips_malformed(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"a": 1}\n'
        'NOT_JSON\n'
        '{"b": 2}\n',
        encoding="utf-8",
    )
    stream = ReplayStream(path)
    bar1 = stream.next_bar()
    skipped = stream.next_bar()
    bar3 = stream.next_bar()
    assert bar1 == {"a": 1}
    assert skipped is None
    assert bar3 == {"b": 2}


def test_replay_stream_n_lines(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"a": 1}\n'
        '{"b": 2}\n'
        '{"c": 3}\n',
        encoding="utf-8",
    )
    stream = ReplayStream(path)
    assert stream.n_lines == 3


# ============================================================
# build_registry
# ============================================================


def test_build_registry_has_2_detectors():
    registry = build_registry()
    assert registry.n_detectors == 2
    names = registry.detector_names
    assert "Bearish_Rejection" in names
    assert "Sweep_Reclaim_N1" in names


# ============================================================
# _DryRunBackend stub Protocol
# ============================================================


def test_dry_run_backend_implements_protocol():
    from bot4_v2.execution.dtc_adapter import IDTCBackend
    backend = _DryRunBackend()
    assert isinstance(backend, IDTCBackend)


def test_dry_run_backend_connected_lifecycle():
    """R5 ULTRATHINK : connected=False par defaut, True apres connect()."""
    backend = _DryRunBackend()
    assert backend.connected is False
    assert backend.connect() is True
    assert backend.connected is True
    backend.disconnect()
    assert backend.connected is False


def test_dry_run_backend_methods_safe():
    backend = _DryRunBackend()
    assert backend.connect() is True
    backend.disconnect()  # noop
    result = backend.send_market_with_stop_only(
        symbol="NQ", side=2, quantity=1, sl_price=20010.0,
        trade_account="Sim5",
    )
    assert result == ("DRYRUN_PARENT", "DRYRUN_SL", 20000.0)


# ============================================================
# build_loop wiring
# ============================================================


def test_build_loop_dry_run_default(tmp_path):
    """Dry-run par defaut wire up sans erreur."""
    # Cree sample replay
    replay_path = tmp_path / "sample.jsonl"
    replay_path.write_text(
        '{"sym": "NQ", "ts_event": "2026-06-26T14:00:00+00:00", '
        '"high": 20010, "low": 19995, "close": 20000, "atr": 10, "atr_14m": 40, '
        '"vix_level": 18}\n',
        encoding="utf-8",
    )
    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()

    args = parse_args([
        "--symbols", "NQ",
        "--replay", str(replay_path),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "1",
        "--heartbeat-sec", "0",
    ])
    loop = build_loop(args)
    assert loop is not None
    assert loop.settings.symbols == ("NQ",)
    assert loop.processed_bars == 0  # avant run()


def test_build_loop_no_dry_run_attempts_sierra_backend(monkeypatch, tmp_path):
    """P5.4.A : --no-dry-run construit SierraDTCBackend (mock dependencies)."""
    # Stub _build_sierra_backend pour eviter import BOT.dtc_connector lourd
    from bot4_v2.main import __main__ as main_mod

    class FakeBackend:
        connected = True

        def connect(self):
            return True

        def disconnect(self):
            pass

        def send_market_with_stop_only(self, **kw):
            return ("", "", 0.0)

        def send_close_market(self, **kw):
            return ""

        def cancel_order(self, **kw):
            return True

    monkeypatch.setattr(main_mod, "_build_sierra_backend",
                          lambda args: FakeBackend())

    replay_path = tmp_path / "sample.jsonl"
    replay_path.write_text(
        '{"sym": "NQ", "ts_event": "2026-06-26T14:00:00+00:00", '
        '"high": 20010, "low": 19995, "close": 20000, "atr": 10, "atr_14m": 40, '
        '"vix_level": 18}\n',
        encoding="utf-8",
    )
    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()

    args = parse_args([
        "--no-dry-run",
        "--symbols", "NQ",
        "--replay", str(replay_path),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "1",
        "--heartbeat-sec", "0",
    ])
    loop = build_loop(args)
    assert loop is not None


# ============================================================
# main() integration light (dry-run + sample bar)
# ============================================================


def test_main_dry_run_sample_replay_exits_clean(tmp_path):
    """main() avec replay 1 bar dry-run exit code 0."""
    replay_path = tmp_path / "sample.jsonl"
    replay_path.write_text(
        '{"sym": "NQ", "ts_event": "2026-06-26T14:00:00+00:00", '
        '"high": 20010, "low": 19995, "close": 20000, "atr": 10, "atr_14m": 40, '
        '"vix_level": 18}\n',
        encoding="utf-8",
    )
    menthorq_dir = tmp_path / "menthorq"
    menthorq_dir.mkdir()
    rc = main([
        "--symbols", "NQ",
        "--replay", str(replay_path),
        "--menthorq-dir", str(menthorq_dir),
        "--max-cycles", "1",
        "--heartbeat-sec", "0",
    ])
    assert rc == 0


def test_main_no_dry_run_import_fail_returns_1(monkeypatch):
    """--no-dry-run si BOT/dtc_connector indispo (ImportError) -> exit 1."""
    from bot4_v2.main import __main__ as main_mod

    def fake_build_sierra(args):
        raise ImportError("simulated BOT/dtc_connector missing")

    monkeypatch.setattr(main_mod, "_build_sierra_backend", fake_build_sierra)
    rc = main(["--no-dry-run"])
    assert rc == 1
