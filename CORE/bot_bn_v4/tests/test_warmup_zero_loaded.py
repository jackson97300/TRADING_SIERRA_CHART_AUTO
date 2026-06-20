"""Tests FIX B.6 BOTBN_WARMUP_ZERO_LOADED MAJEUR alert (schema-auditor 19/06).

Avant fix : warmup_from_disk retournait 0 silencieusement si pipeline enricher
off. 4 restarts d'affilee le 18/06 avec n_loaded=0 = bot aveugle 4h+ sans
alerte.

Apres fix : emit BOTBN_WARMUP_ZERO_LOADED MAJEUR avec diagnostic detaille
(n_files_36h, latest_file) + Discord alert.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_log_code_botbn_warmup_zero_loaded_registered():
    """Code log BOTBN_WARMUP_ZERO_LOADED doit etre dans log_catalog."""
    from CORE.log_catalog import LOG_CODES
    from CORE.logging_v2 import LogLevel

    assert "BOTBN_WARMUP_ZERO_LOADED" in LOG_CODES
    level, category, template = LOG_CODES["BOTBN_WARMUP_ZERO_LOADED"]
    assert level == LogLevel.MAJEUR, "Doit etre MAJEUR (Discord alert pipeline down)"
    assert category == "events"


def test_source_signal_engine_emits_zero_loaded_on_empty():
    """signal_engine.py warmup_from_disk doit emit BOTBN_WARMUP_ZERO_LOADED si bars vide."""
    se_path = _ROOT / "CORE" / "bot_bn_v4" / "signal_engine.py"
    content = se_path.read_text(encoding="utf-8")
    assert "BOTBN_WARMUP_ZERO_LOADED" in content, \
        "Fix B.6 absent : signal_engine ne emit pas BOTBN_WARMUP_ZERO_LOADED"
    # Diagnostic detaille requis
    assert "n_files_36h" in content
    assert "latest_file" in content


def test_warmup_zero_emits_when_no_files(tmp_path, monkeypatch):
    """Test fonctionnel : warmup_from_disk avec dossier vide emit ZERO_LOADED."""
    from CORE.bot_bn_v4.signal_engine import SignalEngine
    from CORE.bot_bn_v4.config import BotBNV4Config

    cfg = BotBNV4Config()
    emitted = []

    def log_fn(code, **ctx):
        emitted.append((code, ctx))

    # SignalEngine avec log_fn injecte
    eng = SignalEngine(symbol="NQ", cfg=cfg, log_fn=log_fn)

    # Monkey-patch _data_root pour pointer vers tmp_path vide
    import CORE.bot_bn_v4.bar_history_loader as bhl
    monkeypatch.setattr(bhl, "_data_root", lambda: tmp_path)

    n_loaded = eng.warmup_from_disk(target=240)
    assert n_loaded == 0

    # Verifier emit BOTBN_WARMUP_ZERO_LOADED avec diagnostic
    zero_emits = [e for e in emitted if e[0] == "BOTBN_WARMUP_ZERO_LOADED"]
    assert len(zero_emits) == 1, \
        f"Expected 1 BOTBN_WARMUP_ZERO_LOADED emit, got {len(zero_emits)}"
    ctx = zero_emits[0][1]
    assert ctx["sym"] == "NQ"
    assert ctx["n_loaded"] == 0
    assert ctx["target"] == 240
    # Diagnostic : 0 files OU au moins le champ existe
    assert "n_files_36h" in ctx
    assert "latest_file" in ctx
