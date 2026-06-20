"""Tests FIX B.4 DIRECTION_MODE=both default (decision Jackson 18/06 souveraine).

Memory `project_bot3_bn_v4_audit_20260618.md` : "revenir both directions".
Avant : DIRECTION_MODE="long" hardcode -> rate SHORTs en regime bearish
(trade -$967 15/06 missed).
Apres : default "both", override env BOTBN_DIRECTION_MODE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_direction_mode_default_both(monkeypatch):
    """Default DIRECTION_MODE doit etre 'both' (decision Jackson 18/06)."""
    monkeypatch.delenv("BOTBN_DIRECTION_MODE", raising=False)
    import importlib
    from CORE.bot_bn_v4 import config as _cfg_mod
    importlib.reload(_cfg_mod)
    cfg = _cfg_mod.BotBNV4Config()
    assert cfg.DIRECTION_MODE == "both", \
        f"Default DIRECTION_MODE doit etre 'both' (got '{cfg.DIRECTION_MODE}')"


def test_direction_mode_env_override_long(monkeypatch):
    """Env BOTBN_DIRECTION_MODE=long doit override default."""
    monkeypatch.setenv("BOTBN_DIRECTION_MODE", "long")
    import importlib
    from CORE.bot_bn_v4 import config as _cfg_mod
    importlib.reload(_cfg_mod)
    cfg = _cfg_mod.BotBNV4Config()
    assert cfg.DIRECTION_MODE == "long"


def test_direction_mode_env_override_short(monkeypatch):
    """Env BOTBN_DIRECTION_MODE=short doit override default."""
    monkeypatch.setenv("BOTBN_DIRECTION_MODE", "short")
    import importlib
    from CORE.bot_bn_v4 import config as _cfg_mod
    importlib.reload(_cfg_mod)
    cfg = _cfg_mod.BotBNV4Config()
    assert cfg.DIRECTION_MODE == "short"


def test_direction_mode_propagated_in_proposed_dir():
    """Verifier que main.py respecte cfg.DIRECTION_MODE pour proposed_dir."""
    main_path = _ROOT / "CORE" / "bot_bn_v4" / "main.py"
    content = main_path.read_text(encoding="utf-8")
    # Pattern existant : self.cfg.DIRECTION_MODE utilise
    assert "self.cfg.DIRECTION_MODE" in content, \
        "main.py doit lire self.cfg.DIRECTION_MODE pour propager le default"
